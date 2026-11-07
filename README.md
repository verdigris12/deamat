# Deamat

Python GUI components for exploratory scientific applications: Dear ImGui, an interactive Matplotlib viewer, pygfx scenes, background coroutines and process jobs.

Requires Python 3.11+ and a desktop graphics environment supported by wgpu. Python dependencies install with uv; the OS must provide working window-system and graphics drivers. On Linux, native file dialogs also need a supported dialog helper such as Zenity or KDialog.

`imgui-bundle` is pinned to 1.92.0: the wgpu 0.29 ImGui backend uses draw-data APIs removed by later 1.92 builds. Upgrade the binding and backend together, with a native rendering smoke test.

## Install and run

From a checkout:

```sh
uv sync --locked
uv run deamat-demo
uv run mplview --trust-pickle figure.pkl
```

Install the command-line tools from a checkout with `uv tool install .`. To use the library in another uv project, use `uv add /path/to/deamat`; published repository revisions can be installed with `uv add git+https://github.com/verdigris12/deamat`.

**Pickle is executable Python, not a safe interchange format.** `mplview` requires `--trust-pickle`; the File menu asks for confirmation before opening a pickle. Never open an untrusted figure. PNG, PDF and SVG export do not require pickle.

## Figure viewer

```python
from matplotlib.figure import Figure
from deamat.mpl_view import MPLView

figure = Figure(figsize=(8, 5), layout="constrained")
axes = figure.subplots()
axes.plot([0, 1, 2], [0, 1, 0], label="Signal")
axes.legend()
MPLView(figure).run()
```

The standalone viewer and embedded figure widget share the same canvas and property inspector:

- Drag in **Pan** mode; select **Zoom** and drag a rectangle; scroll to zoom around the cursor.
- **Home**, **Back** and **Forward** navigate view history. Shared, logarithmic and inverted axes retain Matplotlib navigation semantics.
- **Actual size** preserves figure inches and DPI. **Fit** renders for the available area without changing intrinsic figure dimensions or export size.
- Select a figure, axes or artist in the inspector. Text and numeric entries apply with Enter; choices and colors apply immediately. Invalid values leave a visible error rather than being silently coerced.
- The standalone File menu opens/saves trusted pickles and exports PNG, PDF or SVG. Export uses the current edited Matplotlib figure, not a screen capture.

| Object | Editable properties |
| --- | --- |
| Figure | Size, DPI, background, layout engine, suptitle |
| Axes | Titles/labels, limits, scales, aspect, spines, ticks and grid |
| Text | Content, font, size, color, alignment and rotation |
| Lines | Width/style/color, markers and marker styling |
| Collections/scatter | Sizes, colors, scalar colormap and limits |
| Images | Colormap, limits, interpolation and origin |
| Patches and legends | Supported public styling and layout properties |
| Artists | Visibility, alpha, z-order, clipping, rasterization, label and SVG metadata |

This is a curated editor, not a generic Python object inspector. It does not edit data arrays, custom transforms or projection-specific geometry. Unsupported properties remain available through Matplotlib's Python API. Empty figures and non-Cartesian axes can be displayed; their navigation depends on the axes implementation.

## Embedded figures

```python
from matplotlib.figure import Figure
from deamat import GUI, GUIState, imgui
from deamat.widgets import figure


def make_plot(state):
    plot = Figure(figsize=(8, 5), layout="constrained")
    plot.subplots().plot([0, 1, 2], [0, state.amplitude, 0])
    return plot


def update(state, gui, dt):
    imgui.begin("Signal")
    if imgui.button("Increase amplitude"):
        state.amplitude += 1
        state.invalidate_figure("signal")
    figure(gui, state, "signal", autosize=True)
    imgui.end()


if __name__ == "__main__":
    state = GUIState()
    state.amplitude = 1
    state.add_figure("signal", make_plot, width=800, height=500)
    gui = GUI(state)
    gui.update = update
    gui.run()
```

Factories are lazy. `invalidate_figure()` marks source data dirty and reruns the factory when displayed. Resizing does **not** rerun it. Public Matplotlib artist setters mark the figure stale and trigger a cached-canvas redraw; idle figures retain their texture without repeated Agg rendering or upload. Explicitly call `view.invalidate()` after changes that bypass Matplotlib's stale tracking.

For an existing figure, `deamat.mpl_canvas.draw_figure(gui, id, figure, size=None, fit=False, toolbar=True)` draws the same canvas and returns its `FigureView`. `deamat.mpl_properties.FigureInspector` can be retained alongside it; invalidate the view when `inspector.draw(figure)` returns true. Figure removal and GUI shutdown dispose callbacks and textures.

The embedded widget includes **Properties**, **Fit figure**, **Refresh data**, **Open in viewer** and **Save image**. Opening a separate viewer transfers a trusted in-process figure via pickle and requires a normal `if __name__ == "__main__"` entry point. The embedded Save image dialog is synchronous; standalone dialogs are polled without blocking frame updates.

## Threads, coroutines and jobs

Construct and run `GUI` on the main thread. GUI state and all Matplotlib/ImGui/GPU operations belong to that thread. Background work returns data; it must not mutate live figures or GUI state.

- `gui.post(callback, *args)` queues a main-thread callback and returns a `concurrent.futures.Future`. In a coroutine use `await asyncio.wrap_future(gui.post(...))`; never block the GUI thread waiting for queued work.
- `gui.exec_coroutine(coro)` runs a coroutine on the background asyncio loop and returns a Future. Post results back to the GUI thread.
- `gui.submit_job(function, *args, callback=None)` returns the process-computation Future. Its optional result callback runs on the GUI thread; completion of the Future does not mean that callback has already run. Functions and arguments must be spawn-pickleable: define worker functions at module scope and guard the entry point.
- Background/callback failures are logged and retained in `gui.errors`; posted callback exceptions are available on their returned Future.
- `gui.add_cleanup(callback)` registers reverse-order, one-time UI-thread resource disposal.
- `gui.close()` is idempotent and safe from a UI callback. Pending work is cancelled where possible. **Already-running process jobs continue; Python waits for them at interpreter exit.** Coroutines must cooperate with cancellation; an async shutdown exceeding one second is reported.

`GUI(..., update_mode="continuous", max_fps=60)` controls the rendercanvas scheduler. `update_mode="ondemand"` is useful for non-animated applications: input and posted work request frames; call `gui.request_draw()` when external state needs a frame.

See `examples/4-async_update.py` and `examples/7-main-thread-dispatch.py` for executable usage.

## Native windows

On GLFW/X11, ImGui panels can be dragged outside the main window and docked back inside it. This is enabled by default; `GUI(..., viewports=False)` keeps panels inside the main window. The GLFW platform backend does not support detached viewports on native Wayland, so deamat leaves them disabled there. Other rendercanvas backends retain single-window rendering.

All windows share one ImGui context, WGPU device and texture registry. Detached pygfx widgets sample the same GPU textures without CPU image readback. Matplotlib still rasterizes through Agg on the CPU and uploads only when dirty; moving a panel does not rebuild its figure or rerasterize an unchanged image. Each native window has its own presentation surface, not a separate rendering process.

`gui.get_pixel_ratio()` returns the current ImGui viewport's framebuffer ratio, or the main window's ratio outside a frame. It is not the monitor's content scale. The retained widgets use it when their backing image dimensions change.

`gui.add_input_handler(callback, *event_types)` and `remove_input_handler` subscribe to `pointer_up`, `key_down`, `key_up`, and application-wide `focus_out` events from any viewport. Pointer coordinates are in ImGui screen space (global desktop coordinates when viewports are enabled, window-local otherwise). Native input also wakes on-demand rendering; deferred ImGui input is drained before the GUI returns to idle.

The Python GLFW binding and imgui-bundle must use the same GLFW library. Import `deamat` or `imgui_bundle` before importing `glfw`; deamat rejects mismatched libraries rather than passing window pointers between them.

## pygfx scenes

`pygfx_canvas(gui, state, id, on_init=None, controller=None, *, camera=None, continuous=True)` returns a public `PygfxCanvas` handle with `scene`, `camera`, `controller`, `renderer`, `invalidate()` and `close()`. An initializer receives `(scene, camera)` and may return a replacement camera. Do not access private GUI scene dictionaries.

The canvas retains its offscreen target and shares the resulting GPU texture with ImGui without CPU readback. It forwards pointer, wheel and keyboard input, including captured releases outside the canvas. Controller camera filters are preserved; resizing preserves camera field of view/world-space extents. Set `material.pick_write=True` for pygfx objects that need pick events.

Use `continuous=False` for static scenes and call `invalidate()` after scene changes. Animated scenes should update existing geometry buffers/materials rather than allocating a new scene every frame. See `examples/5-pygfx.py`, `examples/6-pygfx_more.py` and `examples/8-pygfx_2d.py`.

## Development

```sh
uv sync --locked
uv run pytest -q
uv build
```

Tests that construct a GUI require a display and working wgpu driver. On a headless Linux machine, provide Xvfb and a software Vulkan implementation, then use `xvfb-run -a uv run pytest -q`. The repository also contains a Nix development flake; native driver availability remains host-specific.

The interactive, self-contained viewer design draft is `.ui-drafts/figure-viewer/v1.html`. It uses a labelled SVG sample, not the Python renderer; native screenshots beside it document the implemented surface. It can be opened directly in a browser, or served with the accompanying localhost-only review server for persisted feedback.

## 0.3 migration

- Replace `im_plot_figure(...)` with `figure(gui, state, name, ...)`.
- Replace `state.sync()` / `SyncContext` deep-copy merging with `gui.post(...)`; the sync module is removed.
- Use `GUI(max_fps=...)`, not an unused `gui.fps` attribute.
- Retain the public pygfx canvas handle instead of mutating private scene/renderer registries.
- Importing the package no longer changes the global multiprocessing start method. Workers and standalone figure windows explicitly use a spawn context.
- Figure dimensions and existing artists are preserved; editing properties does not create a suptitle merely by displaying its control.
- Dependencies are limited to the current imgui-bundle/wgpu/rendercanvas/pygfx stack, Matplotlib, NumPy and GLFW. Unused legacy rendering and processing dependencies have been removed.
