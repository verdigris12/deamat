from typing import Any, Callable, Coroutine, Optional
import logging
import asyncio
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from queue import Empty, SimpleQueue
import multiprocessing as mp
import os
import signal
import sys
import time

# Import the bundle first so Python GLFW uses the bundled native library.
from imgui_bundle import imgui, hello_imgui, immapp
import glfw

from ._native_window import NativeWindow
from ._glfw_viewports import GlfwViewportHost, _window


def _worker_initializer(parent_pid: int) -> None:
    """Make Linux pool workers die with the process that created the pool."""
    if sys.platform != "linux":
        return
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    # SIGKILL cannot be ignored by a job. Check the parent after prctl to
    # cover the race where it died before the death signal was installed.
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
    if os.getppid() != parent_pid:
        os._exit(1)


def _stop_executor(executor: ProcessPoolExecutor) -> None:
    """Terminate only this executor's workers, escalating before joining."""
    # Python 3.11–3.13 have no public API to terminate executor workers.
    # Snapshot before shutdown clears the executor's process registry.
    processes = tuple(getattr(executor, "_processes", {}).copy().values())
    for process in processes:
        if process.is_alive():
            try:
                process.terminate()
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 1.0
    for process in processes:
        process.join(timeout=max(0.0, deadline - time.monotonic()))
    for process in processes:
        if process.is_alive():
            try:
                process.kill()
            except ProcessLookupError:
                pass
    for process in processes:
        process.join()
    executor.shutdown(wait=True, cancel_futures=True)


class GUI:
    """High-level GUI manager backed by GLFW and OpenGL."""

    logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Construction / initialisation
    # ------------------------------------------------------------------
    def __init__(
        self, state: Any, *, width: int = 1280, height: int = 720,
        menubar: bool = False, title: str = "deamat",
        max_workers: int | None = None, update_mode: str = "continuous",
        max_fps: float = 60, viewports: bool = True,
    ) -> None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("GUI must be constructed on the main thread")
        self._ui_thread = threading.get_ident()
        self._lifecycle_lock = threading.Lock()
        self._posts = SimpleQueue()
        self._closed = False
        self._running = False
        self._frame_active = False
        self._rendered = False
        self._startup_frames_remaining = 4
        self._frame_error = None
        self._shutdown_complete = False
        self._dispatch_ready = False
        self._cleanups = []
        self.errors: list[BaseException] = []
        self._jobs: set[Future] = set()
        self._coroutines: set[Future] = set()
        self.update_mode = update_mode
        self.max_fps = max_fps
        if update_mode not in ("continuous", "ondemand"):
            raise ValueError("update_mode must be continuous or ondemand")
        if max_fps <= 0:
            raise ValueError("max_fps must be positive")
        self._menubar = menubar
        self._input_handlers: dict[str, list[Callable]] = {}
        self._images = set()
        self._deferred_image_deletions = []
        self._draw_requested = True
        self._last_frame = time.perf_counter()
        self._runner_params = hello_imgui.RunnerParams()
        params = self._runner_params
        params.platform_backend_type = hello_imgui.PlatformBackendType.glfw
        params.renderer_backend_type = hello_imgui.RendererBackendType.open_gl3
        params.app_window_params.window_title = title
        params.app_window_params.window_geometry.size = (width, height)
        params.imgui_window_params.default_imgui_window_type = hello_imgui.DefaultImGuiWindowType.no_default_window
        params.imgui_window_params.enable_viewports = viewports
        params.fps_idling.enable_idling = False
        params.fps_idling.vsync_to_monitor = False
        params.ini_disable = True
        params.callbacks.show_gui = self._draw_imgui
        params.callbacks.pre_new_frame = self._pre_new_frame
        params.callbacks.post_new_frame = self._post_new_frame
        if os.environ.get("DEAMAT_GLFW_EGL") == "1":
            if not glfw.init():
                raise RuntimeError("GLFW initialization failed")
            glfw.window_hint(glfw.CONTEXT_CREATION_API, glfw.EGL_CONTEXT_API)
        immapp.manual_render.setup_from_runner_params(params)
        self.imgui_context = imgui.get_current_context()
        self.window = _window(imgui.get_main_viewport())
        self.canvas = NativeWindow(self)
        self._io = imgui.get_io()
        self._io.config_flags |= imgui.ConfigFlags_.docking_enable
        self._viewport_host = GlfwViewportHost(self, viewports)

        # -- Runtime state --
        self.state: Any = state
        self.update: Optional[Callable[[Any, "GUI", float], None]] = None

        # Public/Private scene registries for widgets
        self.scenes: dict[str, Any] = {}
        self._pygfx_scenes: dict[str, Any] = {}

        # -- Clock for delta time --
        self._last_frame = time.perf_counter()

        # -- asyncio helper thread --
        self.asyncio_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self.asyncio_thread = threading.Thread(
            target=self._run_asyncio, name="deamat-asyncio", daemon=True
        )

        # Explicit spawn policy avoids inheriting GUI/GPU resources in workers.
        self.executor = ProcessPoolExecutor(
            max_workers=max_workers, mp_context=mp.get_context("spawn"),
            initializer=_worker_initializer, initargs=(os.getpid(),),
        )
        self.job_counter: int = 0
    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _create_main_window(self) -> None:
        mv = imgui.get_main_viewport()
        imgui.set_next_window_viewport(mv.id_)
        imgui.set_next_window_pos((mv.work_pos.x, mv.work_pos.y))
        imgui.set_next_window_size((mv.work_size.x, mv.work_size.y))
        imgui.set_next_window_bg_alpha(0)
        flags = (
            imgui.WindowFlags_.no_decoration
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_bring_to_front_on_focus
            | imgui.WindowFlags_.no_background
        )
        if self._menubar:
            flags |= imgui.WindowFlags_.menu_bar
        imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_padding, (0.0, 0.0))
        imgui.begin("MainDockHost", flags=flags)
        imgui.dock_space(
            imgui.get_id("MainDockSpace"), (0.0, 0.0), imgui.DockNodeFlags_.passthru_central_node
        )
        imgui.pop_style_var(2)

    # ------------------------------------------------------------------
    # Per-frame handlers
    # ------------------------------------------------------------------
    def _assert_ui_thread(self) -> None:
        if threading.get_ident() != self._ui_thread:
            raise RuntimeError("Use GUI.post() to call this method on the GUI thread")

    def _require_open(self) -> None:
        self._assert_ui_thread()
        if self._closed:
            raise RuntimeError("GUI is closed")

    def _drain_posts(self) -> None:
        self._assert_ui_thread()
        while not self._closed:
            try:
                future, callback, args = self._posts.get_nowait()
            except Empty:
                break
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = callback(*args)
            except BaseException as error:
                future.set_exception(error)
            else:
                future.set_result(result)

    def _record_error(self, error: BaseException) -> None:
        self.errors.append(error)
        self.state.statusline = f"Error: {error}"
        self.logger.error(
            "Background or cleanup operation failed",
            exc_info=(type(error), error, error.__traceback__),
        )

    def make_current(self) -> None:
        glfw.make_context_current(self.window)
        imgui.set_current_context(self.imgui_context)

    def create_image(self, pixels):
        from .image import ImageTexture
        self._require_open()
        return ImageTexture(self, pixels)

    def _pre_new_frame(self) -> None:
        self._viewport_host.pre_new_frame()

    def _post_new_frame(self) -> None:
        self._viewport_host.post_new_frame()

    def _render_frame(self) -> None:
        if self._closed:
            return
        self.make_current()
        self._frame_active = True
        try:
            immapp.manual_render.render()
            self._rendered = True
            self.make_current()
            self._viewport_host.after_frame()
            if self._startup_frames_remaining:
                self._startup_frames_remaining -= 1
                if self._startup_frames_remaining:
                    # Hello ImGui maps its initially hidden main window on
                    # frame four, even when the application renders on demand.
                    self.request_draw()
            if self._frame_error is not None:
                error, traceback = self._frame_error
                self._frame_error = None
                raise error.with_traceback(traceback)
        finally:
            self._frame_active = False
            if self._closed:
                self._shutdown()
            else:
                self._drain_posts()

    def _draw_imgui(self) -> None:
        """Build the ImGui frame."""
        now = time.perf_counter()
        dt = now - self._last_frame
        self._last_frame = now

        # Recover all ImGui stacks before returning to the runner. It must
        # finish rendering before an exception can escape.
        recovery = imgui.internal.ErrorRecoveryState()
        imgui.internal.error_recovery_store_state(recovery)
        try:
            self._drain_posts()
            if self._closed:
                return
            self.state.update_window(self.canvas)
            self._create_main_window()
            if self.update is not None:
                self.update(self.state, self, dt)
            imgui.end()
        except BaseException as error:
            io = imgui.get_io()
            enable_assert = io.config_error_recovery_enable_assert
            io.config_error_recovery_enable_assert = False
            try:
                imgui.internal.error_recovery_try_to_recover_state(recovery)
            finally:
                io.config_error_recovery_enable_assert = enable_assert
            if isinstance(error, Exception):
                self._record_error(error)
            self._frame_error = (error, error.__traceback__)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def add_input_handler(self, callback: Callable, *event_types: str) -> None:
        """Subscribe to native events from any ImGui viewport."""
        self._require_open()
        if not callable(callback):
            raise TypeError("callback must be callable")
        for event_type in event_types:
            handlers = self._input_handlers.setdefault(event_type, [])
            if callback not in handlers:
                handlers.append(callback)

    def remove_input_handler(self, callback: Callable, *event_types: str) -> None:
        """Remove an input subscription; safe after resource disposal."""
        self._assert_ui_thread()
        for event_type in event_types:
            handlers = self._input_handlers.get(event_type, [])
            if callback in handlers:
                handlers.remove(callback)

    def _emit_input(self, event: dict) -> None:
        for callback in tuple(self._input_handlers.get(event["event_type"], ())):
            if self._closed:
                break
            callback(event)

    def get_pixel_ratio(self) -> float:
        """Return the framebuffer ratio of the current ImGui viewport."""
        if self._viewport_host is not None:
            return self._viewport_host.pixel_ratio()
        return self.canvas.get_pixel_ratio()

    def post(self, callback: Callable[..., Any], *args: Any) -> Future:
        """Queue an explicit GUI-thread callback and return its result future.

        Await with ``asyncio.wrap_future(gui.post(...))``. Cancellation before
        dispatch skips the callback. Posting after close returns a failed future.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        future = Future()
        with self._lifecycle_lock:
            if self._closed:
                future.set_exception(RuntimeError("GUI is closed"))
                return future
            self._posts.put((future, callback, args))
            if self._dispatch_ready:
                self._draw_requested = True
                glfw.post_empty_event()
        return future

    def request_draw(self) -> None:
        """Request a frame and wake the native event loop."""
        with self._lifecycle_lock:
            if not self._closed:
                self._draw_requested = True
                if self._dispatch_ready:
                    glfw.post_empty_event()

    def submit_job(
        self,
        job: Callable[..., Any],
        *args: Any,
        callback: Optional[Callable[[Any], None]] = None,
    ) -> Future:
        """Submit spawn-safe compute work from the GUI thread.

        The returned future contains the compute result/error. The optional
        result callback and status bookkeeping run on the GUI thread. Callback
        errors are logged and retained in ``errors``.
        """
        self._require_open()
        future = self.executor.submit(job, *args)
        self._jobs.add(future)
        self.job_counter += 1
        self.state.statusline = f"Executing {self.job_counter} tasks..."
        future.add_done_callback(
            lambda done: self.post(self._finish_job, done, callback)
        )
        return future

    def _finish_job(self, future: Future, callback: Callable | None) -> None:
        self._jobs.discard(future)
        self.job_counter -= 1
        self.state.statusline = (
            "Ready" if self.job_counter == 0
            else f"Executing {self.job_counter} tasks..."
        )
        if future.cancelled():
            return
        try:
            result = future.result()
            if callback is not None:
                callback(result)
        except Exception as error:
            self._record_error(error)

    def _run_asyncio(self) -> None:
        asyncio.set_event_loop(self.asyncio_loop)
        try:
            self.asyncio_loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.asyncio_loop)
            for task in pending:
                task.cancel()
            if pending:
                results = self.asyncio_loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
                for result in results:
                    if isinstance(result, BaseException) and not isinstance(
                        result, asyncio.CancelledError
                    ):
                        self.logger.error(
                            "Coroutine failed during shutdown",
                            exc_info=(type(result), result, result.__traceback__),
                        )
            self.asyncio_loop.run_until_complete(self.asyncio_loop.shutdown_asyncgens())
            self.asyncio_loop.close()

    def exec_coroutine(self, co: Coroutine[Any, Any, Any]) -> Future:
        """Run a coroutine off-thread; dispatch all state changes with post()."""
        self._require_open()
        if self.asyncio_thread.ident is None:
            self.asyncio_thread.start()
        future = asyncio.run_coroutine_threadsafe(co, self.asyncio_loop)
        self._coroutines.add(future)
        future.add_done_callback(lambda done: self.post(self._finish_coroutine, done))
        return future

    def _finish_coroutine(self, future: Future) -> None:
        self._coroutines.discard(future)
        if not future.cancelled():
            error = future.exception()
            if error is not None:
                self._record_error(error)

    def add_cleanup(self, callback: Callable[[], None]) -> None:
        """Register resource disposal on the GUI thread, in reverse order."""
        self._require_open()
        if not callable(callback):
            raise TypeError("cleanup must be callable")
        self._cleanups.append(callback)

    def close(self) -> None:
        """Close once, terminating and joining owned process workers.

        Pending jobs are cancelled and running jobs are terminated. Coroutines
        must cooperate with cancellation; an unresponsive async thread is a
        reported error and is left daemonized after a bounded one-second join.
        Closing inside a UI callback defers resource disposal until the complete
        ImGui backend render has returned.
        """
        self._assert_ui_thread()
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            self._dispatch_ready = False
        if not self._frame_active:
            self._shutdown()

    def _shutdown(self) -> None:
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        while True:
            try:
                future, _, _ = self._posts.get_nowait()
            except Empty:
                break
            future.cancel()
        for future in tuple(self._coroutines):
            future.cancel()
        self._coroutines.clear()
        for future in tuple(self._jobs):
            future.cancel()
        self._jobs.clear()
        self.job_counter = 0
        self.state.statusline = "Closed"
        _stop_executor(self.executor)
        if self.asyncio_thread.ident is None:
            self.asyncio_loop.close()
        else:
            self.asyncio_loop.call_soon_threadsafe(self.asyncio_loop.stop)
            self.asyncio_thread.join(timeout=1.0)
            if self.asyncio_thread.is_alive():
                self._record_error(RuntimeError(
                    "Coroutine shutdown exceeded one second; background work "
                    "must cooperate with cancellation"
                ))
        context = self.imgui_context
        previous_context = imgui.get_current_context()
        self.make_current()
        while self._cleanups:
            cleanup = self._cleanups.pop()
            try:
                cleanup()
            except Exception as error:
                self._record_error(error)
        for delete in tuple(self._deferred_image_deletions):
            delete()
        for image in tuple(self._images):
            image.close()
        if not self._rendered:
            # Hello ImGui captures a final screenshot during teardown. Produce
            # draw data without calling application code if no frame ran.
            callbacks = self._runner_params.callbacks
            callbacks.show_gui = lambda: None
            callbacks.pre_new_frame = lambda: None
            callbacks.post_new_frame = lambda: None
            self._runner_params.app_shall_exit = False
            immapp.manual_render.render()
            self.make_current()
        self._viewport_host.close()
        immapp.manual_render.tear_down()
        if previous_context != context:
            imgui.set_current_context(previous_context)

    def set_floating(self, aspect_ratio: Optional[tuple[int, int]] = None) -> None:
        """Make the window floating (always on top) with an optional fixed aspect ratio.

        This method only works with the GLFW backend. On other backends, a warning
        is logged and the call has no effect.

        Args:
            aspect_ratio: Optional tuple of (width, height) to constrain the window
                aspect ratio during resizing. For example, (16, 9) for 16:9 ratio.
        """
        window = self.window

        # Make window floating (always on top)
        glfw.set_window_attrib(window, glfw.FLOATING, glfw.TRUE)

        # Set aspect ratio if provided
        if aspect_ratio is not None:
            glfw.set_window_aspect_ratio(window, aspect_ratio[0], aspect_ratio[1])

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._require_open()
        if self._running:
            raise RuntimeError("GUI is already running")
        self._running = True
        with self._lifecycle_lock:
            self._dispatch_ready = True
        next_frame = time.perf_counter()
        try:
            while not self._closed and not self._runner_params.app_shall_exit:
                self._drain_posts()
                if self._closed:
                    break
                now = time.perf_counter()
                if (self.update_mode == "continuous" or self._draw_requested) and now >= next_frame:
                    with self._lifecycle_lock:
                        self._draw_requested = False
                    self._render_frame()
                    next_frame = time.perf_counter() + 1.0 / self.max_fps
                else:
                    timeout = max(0.0, next_frame - now) if (self.update_mode == "continuous" or self._draw_requested) else None
                    if timeout is None:
                        glfw.wait_events()
                    else:
                        glfw.wait_events_timeout(timeout)
        finally:
            self._running = False
            self.close()
            self._shutdown()
