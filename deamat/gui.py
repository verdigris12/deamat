from typing import Any, Callable, Coroutine, Optional
import logging
import time
import os
import asyncio
import threading
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

import glfw                                   # window + input backend (import **before** imgui_bundle)
from OpenGL import GL as gl                   # raw OpenGL calls
from imgui_bundle import imgui                # Dear ImGui core
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer
from matplotlib import pyplot as plt


class GUI:
    """High‑level GUI manager backed by GLFW."""

    logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Construction / initialisation
    # ------------------------------------------------------------------
    def __init__(self, state: Any, *, width: int = 1280, height: int = 720) -> None:
        # ‑‑ GLFW init ‑‑ ------------------------------------------------
        if not glfw.init():
            raise RuntimeError("Could not initialise GLFW; check DISPLAY / drivers")
 
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_COMPAT_PROFILE)  # VisPy/gloo needs a compat profile (not core)
        glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)

        self.window: glfw._GLFWwindow | None = glfw.create_window(
            width, height, "deamat", None, None
        )
        if self.window is None:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")
        glfw.make_context_current(self.window)
        glfw.swap_interval(1)  # V‑sync

        # ‑‑ ImGui -------------------------------------------------------
        self.ctx: imgui.Context = imgui.create_context()
        self.impl = GlfwRenderer(self.window)

        self._io = imgui.get_io()
        self._io.config_flags |= (
            imgui.ConfigFlags_.docking_enable | imgui.ConfigFlags_.viewports_enable
        )

        # ‑‑ Runtime state ----------------------------------------------
        self.state: Any = state
        self.fps: float = 60.0
        self.update: Optional[Callable[[Any, "GUI", float], None]] = None
        self.update_async: Optional[Callable[[Any, "GUI", float], Coroutine[Any, Any, None]]] = None

        # Public/Private canvas registries for widgets
        self.canvases: dict[str, Any] = {}
        self._vispy_canvases: dict[str, Any] = {}

        # ‑‑ asyncio helper thread --------------------------------------
        self.asyncio_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.asyncio_loop)
        self.asyncio_thread = threading.Thread(target=self.asyncio_loop.run_forever, daemon=True)

        # ‑‑ Process pool ----------------------------------------------
        self.executor = ProcessPoolExecutor(mp_context=mp.get_context("spawn"))
        self.job_mutex: mp.Lock = mp.Lock()
        self.job_counter: int = 0

        # ‑‑ Matplotlib figure cache ------------------------------------
        self._init_matplotlib()

        # ‑‑ GL clear colour -------------------------------------------
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _init_matplotlib(self) -> None:
        pass

    def _create_main_window(self) -> None:
        mv = imgui.get_main_viewport()
        imgui.set_next_window_pos((mv.pos.x, mv.pos.y))
        imgui.set_next_window_size((mv.size.x, mv.size.y))
        imgui.set_next_window_bg_alpha(0)
        flags = (
            imgui.WindowFlags_.menu_bar
            | imgui.WindowFlags_.no_decoration
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_bring_to_front_on_focus
            | imgui.WindowFlags_.no_background
        )
        imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_padding, (0.0, 0.0))
        imgui.begin("MainDockHost", flags=flags)
        imgui.dock_space(
            imgui.get_id("MainDockSpace"), (0.0, 0.0), imgui.DockNodeFlags_.passthru_central_node
        )
        imgui.pop_style_var(2)

    # ------------------------------------------------------------------
    # Per‑frame handlers
    # ------------------------------------------------------------------
    def _drain_sync_queue(self) -> None:
        """Process pending state synchronization callbacks from async coroutines."""
        while not self.state._sync_queue.empty():
            try:
                merge_fn = self.state._sync_queue.get_nowait()
                merge_fn()
            except Exception:
                self.logger.error("Exception in sync queue merge function", exc_info=True)
    
    def _update_ui(self, dt: float) -> None:
        # Process any pending state updates from async coroutines
        self._drain_sync_queue()
        
        self.impl.process_inputs()
        imgui.new_frame()
        self.state.update_window(self.window)  # type: ignore[arg-type]
        self._create_main_window()
        with self.job_mutex:
            if self.update is not None:
                self.update(self.state, self, dt)
        imgui.end()

    def _update_figures(self) -> None:
        plt.style.use(self.state.plt_style)
        for f in self.state.figures.values():
            if f.get("dirty", True):
                f["dirty"] = False
                old_fig = f.get("figure")
                if old_fig is not None:
                    plt.close(old_fig)
                fig = f["make"](self.state)
                fig.set_figwidth(f["width"] / 100)
                fig.set_figheight(f["height"] / 100)
                f["figure"] = fig

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def submit_job(
        self,
        job: Callable[..., Any],
        *args: Any,
        callback: Optional[Callable[[Any], None]] = None,
    ) -> None:
        future = self.executor.submit(job, *args)
        with self.job_mutex:
            self.job_counter += 1
            self.state.statusline = f"Executing {self.job_counter} tasks…"

        def _cb(fut):
            with self.job_mutex:
                self.job_counter -= 1
                self.state.statusline = (
                    "Ready" if self.job_counter == 0 else f"Executing {self.job_counter} tasks…"
                )
            try:
                result = fut.result()
            except Exception:
                self.logger.error("Exception in submitted job", exc_info=True)
                return
            if callback is not None:
                callback(result)

        future.add_done_callback(_cb)

    def exec_coroutine(self, co: Coroutine[Any, Any, Any]) -> None:
        asyncio.run_coroutine_threadsafe(co, self.asyncio_loop)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        if self.window is None:
            raise RuntimeError("GUI has no valid window")

        self.state.update_window(self.window)  # type: ignore[arg-type]
        # If subclasses need GL objects, they can override gl_init
        if hasattr(self.state, "gl_init"):
            try:
                self.state.gl_init(self.window, None)  # type: ignore[arg-type]
            except TypeError:
                # Backward-compat: some implementations take just (window)
                self.state.gl_init(self.window)  # type: ignore[misc]

        self.asyncio_thread.start()

        last_time: float = time.perf_counter()
        frame_dur: float = 1.0 / self.fps

        while not glfw.window_should_close(self.window):
            now = time.perf_counter()
            dt = now - last_time
            last_time = now

            # ‑‑ per‑frame processing ‑‑
            self._update_figures()
            self._update_ui(dt)

            # ‑‑ rendering ‑‑
            fb_width, fb_height = glfw.get_framebuffer_size(self.window)
            gl.glViewport(0, 0, fb_width, fb_height)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)

            imgui.render()
            self.impl.render(imgui.get_draw_data())

            if self._io.config_flags & imgui.ConfigFlags_.viewports_enable:
                imgui.update_platform_windows()
                imgui.render_platform_windows_default()
                glfw.make_context_current(self.window)

            glfw.swap_buffers(self.window)
            glfw.poll_events()

            elapsed = time.perf_counter() - now
            if elapsed < frame_dur:
                time.sleep(frame_dur - elapsed)

        # ‑‑ shutdown ‑‑
        self.asyncio_loop.call_soon_threadsafe(self.asyncio_loop.stop)
        self.executor.shutdown(wait=False)
        self.impl.shutdown()
        glfw.terminate()
