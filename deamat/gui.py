from typing import Any, Callable, Coroutine, Optional
import logging
import asyncio
import threading
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

import glfw
from rendercanvas.auto import RenderCanvas, loop
from wgpu.utils.imgui import ImguiRenderer
import wgpu
import pygfx as gfx
from pygfx.renderers.wgpu.engine.shared import Shared
from imgui_bundle import imgui
from matplotlib import pyplot as plt


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
        self, state: Any, *, width: int = 1280, height: int = 720, menubar: bool = False
    ) -> None:
        # Configure pygfx to only request available GPU features
        _configure_pygfx_features()

        # -- wgpu canvas --
        self.canvas = RenderCanvas(
            size=(width, height),
            title="deamat",
            update_mode="continuous",
        )

        # -- UI options --
        self._menubar = menubar

        # -- pygfx renderer --
        self.renderer = gfx.WgpuRenderer(self.canvas)

        # -- ImGui renderer (uses same wgpu device) --
        self.gui_renderer = ImguiRenderer(self.renderer.device, self.canvas)

        self._io = imgui.get_io()
        self._io.config_flags |= imgui.ConfigFlags_.docking_enable

        # -- Runtime state --
        self.state: Any = state
        self.fps: float = 60.0
        self.update: Optional[Callable[[Any, "GUI", float], None]] = None

        # Public/Private scene registries for widgets
        self.scenes: dict[str, Any] = {}
        self._pygfx_scenes: dict[str, Any] = {}

        # -- Clock for delta time --
        self._clock = gfx.Clock()

        # -- asyncio helper thread --
        self.asyncio_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.asyncio_loop)
        self.asyncio_thread = threading.Thread(target=self.asyncio_loop.run_forever, daemon=True)

        # -- Process pool --
        self.executor = ProcessPoolExecutor(mp_context=mp.get_context("spawn"))
        self.job_mutex: mp.Lock = mp.Lock()
        self.job_counter: int = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _create_main_window(self) -> None:
        mv = imgui.get_main_viewport()
        imgui.set_next_window_pos((mv.pos.x, mv.pos.y))
        imgui.set_next_window_size((mv.size.x, mv.size.y))
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
    def _drain_sync_queue(self) -> None:
        """Process pending state synchronization callbacks from async coroutines."""
        while not self.state._sync_queue.empty():
            try:
                merge_fn = self.state._sync_queue.get_nowait()
                merge_fn()
            except Exception:
                self.logger.error("Exception in sync queue merge function", exc_info=True)

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

    def _draw_imgui(self) -> None:
        """Called by ImguiRenderer to build the imgui frame."""
        dt = self._clock.get_delta()

        # Process any pending state updates from async coroutines
        self._drain_sync_queue()

        # Update window dimensions in state
        self.state.update_window(self.canvas)

        # Update figures (matplotlib)
        self._update_figures()

        # Create main docking window
        self._create_main_window()

        # Call user update callback
        with self.job_mutex:
            if self.update is not None:
                self.update(self.state, self, dt)

        imgui.end()

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
        # Update window dimensions initially
        self.state.update_window(self.canvas)

        # If subclasses need initialization, they can override gl_init
        if hasattr(self.state, "gl_init"):
            try:
                self.state.gl_init(self.canvas, self.renderer)
            except TypeError:
                # Backward-compat: some implementations take just (window)
                self.state.gl_init(self.canvas)

        self.asyncio_thread.start()

        # Set up the imgui draw function
        self.gui_renderer.set_gui(self._draw_imgui)

        def animate():
            # Render imgui (this calls _draw_imgui internally)
            self.gui_renderer.render()
            self.canvas.request_draw()

        self.renderer.request_draw(animate)
        loop.run()

        # -- shutdown --
        self.asyncio_loop.call_soon_threadsafe(self.asyncio_loop.stop)
        self.executor.shutdown(wait=False)
