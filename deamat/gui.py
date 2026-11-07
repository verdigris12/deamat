from typing import Any, Callable, Coroutine, Optional
import logging
import asyncio
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from queue import Empty, SimpleQueue
import multiprocessing as mp

import glfw
from rendercanvas.auto import RenderCanvas, loop
from wgpu.utils.imgui import ImguiRenderer
import wgpu
import pygfx as gfx
from pygfx.renderers.wgpu.engine.shared import Shared
from imgui_bundle import imgui


def _configure_pygfx_features() -> None:
    """Configure pygfx to only request GPU features that are actually available.
    
    This must be called before creating any WgpuRenderer, as pygfx creates
    a global shared device on first use.
    """
    if Shared._instance is not None:
        # Already initialized, nothing to do
        return
    
    # Get available features from the adapter
    adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    available = set(adapter.features)
    
    # Filter pygfx's required features to only those available
    # pygfx defaults to requiring 'float32-filterable' which may not be supported
    Shared._features = Shared._features & available


class GUI:
    """High-level GUI manager backed by wgpu and pygfx."""

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
        self._shutdown_complete = False
        self._dispatch_ready = False
        self._cleanups = []
        self.errors: list[BaseException] = []
        self._jobs: set[Future] = set()
        self._coroutines: set[Future] = set()
        self.update_mode = update_mode
        self.max_fps = max_fps
        # Configure pygfx to only request available GPU features
        _configure_pygfx_features()

        # -- wgpu canvas --
        self.canvas = RenderCanvas(
            size=(width, height),
            title=title,
            update_mode=update_mode,
            max_fps=max_fps,
        )

        # -- UI options --
        self._menubar = menubar

        # -- pygfx renderer --
        self.renderer = gfx.WgpuRenderer(self.canvas)

        # GLFW uses its native input backend, not ImguiRenderer's canvas event
        # bridge. Other canvas backends retain the existing renderer.
        native_glfw = getattr(self.canvas, "_window", None) is not None
        if native_glfw:
            from ._glfw_viewports import GlfwViewportHost, NativeImguiRenderer
            self.gui_renderer = NativeImguiRenderer(self.renderer.device, self.canvas)
        else:
            self.gui_renderer = ImguiRenderer(self.renderer.device, self.canvas)

        self._io = imgui.get_io()
        self._io.config_flags |= imgui.ConfigFlags_.docking_enable
        self._input_handlers: dict[str, list[Callable]] = {}
        self._viewport_host = None
        if native_glfw:
            self._viewport_host = GlfwViewportHost(self, viewports)

        # -- Runtime state --
        self.state: Any = state
        self.update: Optional[Callable[[Any, "GUI", float], None]] = None

        # Public/Private scene registries for widgets
        self.scenes: dict[str, Any] = {}
        self._pygfx_scenes: dict[str, Any] = {}

        # -- Clock for delta time --
        self._clock = gfx.Clock()

        # -- asyncio helper thread --
        self.asyncio_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self.asyncio_thread = threading.Thread(
            target=self._run_asyncio, name="deamat-asyncio", daemon=True
        )

        # Explicit spawn policy avoids inheriting GUI/GPU resources in workers.
        self.executor = ProcessPoolExecutor(
            max_workers=max_workers, mp_context=mp.get_context("spawn")
        )
        self.job_counter: int = 0
        self.canvas.add_event_handler(self._on_canvas_close, "close")
        self.canvas.add_event_handler(
            self._on_canvas_input, "pointer_down", "pointer_up", "pointer_move",
            "wheel", "key_down", "key_up", "char", "resize"
        )
        self.add_cleanup(self._dispose_gui_renderer)

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

    def _dispatch(self) -> None:
        self._drain_posts()
        if not self._closed:
            self.canvas.request_draw()

    def _start_dispatch(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._dispatch_ready = True
        self._dispatch()

    def _on_canvas_input(self, event: dict) -> None:
        self.request_draw()
        if self._viewport_host is None:
            self._emit_input(event)

    def _on_canvas_close(self, event: dict) -> None:
        self.close()

    def _record_error(self, error: BaseException) -> None:
        self.errors.append(error)
        self.state.statusline = f"Error: {error}"
        self.logger.error(
            "Background or cleanup operation failed",
            exc_info=(type(error), error, error.__traceback__),
        )

    def _render_frame(self) -> None:
        if self._closed:
            return
        self._frame_active = True
        try:
            if self._viewport_host is None:
                self.gui_renderer.render()
            else:
                self._viewport_host.render()
        finally:
            self._frame_active = False
            if self._closed:
                self._shutdown()

    def _dispose_gui_renderer(self) -> None:
        # ImguiRenderer has no public close method. Release the context via
        # ImGui's API, then drop renderer references after widget cleanup.
        if self._viewport_host is not None:
            self._viewport_host.close()
            self._viewport_host = None
        context = self.gui_renderer.imgui_context
        self.gui_renderer.set_gui(None)
        imgui.destroy_context(context)
        self.gui_renderer = None
        self.renderer = None
        self._io = None

    def _draw_imgui(self) -> None:
        """Called by ImguiRenderer to build the imgui frame."""
        dt = self._clock.get_delta()

        self._drain_posts()
        if self._closed:
            return

        # Update window dimensions in state
        self.state.update_window(self.canvas)

        # Create main docking window
        self._create_main_window()

        # Call user update callback
        try:
            if self.update is not None:
                self.update(self.state, self, dt)
        except Exception as error:
            self._record_error(error)
            raise
        finally:
            imgui.end()

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
                loop.call_soon_threadsafe(self._dispatch)
        return future

    def request_draw(self) -> None:
        """Wake an on-demand canvas, safely callable from worker threads."""
        if threading.get_ident() == self._ui_thread:
            if not self._closed:
                self.canvas.request_draw()
        else:
            with self._lifecycle_lock:
                if not self._closed and self._dispatch_ready:
                    loop.call_soon_threadsafe(self._dispatch)
        # Before run, the initial draw and startup dispatch consume queued work.

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
        """Close once without waiting for running process jobs.

        Pending jobs are cancelled where possible. Running process jobs continue;
        Python itself waits for those workers at interpreter exit. Coroutines
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
        self.executor.shutdown(wait=False, cancel_futures=True)
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
        context = self.gui_renderer.imgui_context
        previous_context = imgui.get_current_context()
        imgui.set_current_context(context)
        while self._cleanups:
            cleanup = self._cleanups.pop()
            try:
                cleanup()
            except Exception as error:
                self._record_error(error)
        if previous_context != context:
            imgui.set_current_context(previous_context)
        self.canvas.close()

    def set_floating(self, aspect_ratio: Optional[tuple[int, int]] = None) -> None:
        """Make the window floating (always on top) with an optional fixed aspect ratio.

        This method only works with the GLFW backend. On other backends, a warning
        is logged and the call has no effect.

        Args:
            aspect_ratio: Optional tuple of (width, height) to constrain the window
                aspect ratio during resizing. For example, (16, 9) for 16:9 ratio.
        """
        # Check if we have a GLFW window (rendercanvas stores it as _window)
        window = getattr(self.canvas, "_window", None)
        if window is None:
            self.logger.warning(
                "set_floating() is only supported with the GLFW backend"
            )
            return

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
        try:
            self.state.update_window(self.canvas)
            if hasattr(self.state, "gl_init"):
                self.state.gl_init(self.canvas, self.renderer)
            self.gui_renderer.set_gui(self._draw_imgui)
            self.canvas.request_draw(self._render_frame)
            loop.call_soon(self._start_dispatch)
            loop.run()
        finally:
            self._running = False
            self.close()
            self._shutdown()
