# Deamat

Python GUI components for exploratory scientific applications: Dear ImGui, an interactive Matplotlib viewer, pygfx scenes, background coroutines and process jobs.

Requires Python 3.11+ and a working GLFW/OpenGL desktop environment.
Deamat uses the public imgui-bundle package. It does not require a custom wheel or a source build.
ImAnim is available through `from imgui_bundle import im_anim`.

## Install and run

```sh
uv sync --locked
uv run deamat-demo
uv run mplview --trust-pickle figure.pkl
```

Install the optional pygfx widget dependencies with `uv sync --locked --extra pygfx`.
The normal UI and Matplotlib viewer do not initialize WGPU.
The pygfx widget renders off screen with WGPU, then uploads changed images to OpenGL.

On NixOS, use `nix develop` for an interactive shell.
To run one command, use `nix run . -- -c 'command'`.
The flake supplies native graphics libraries.

**Pickle files can execute Python code. They are not a safe data-exchange format.** `mplview` requires `--trust-pickle`. The File menu asks for confirmation before it opens a pickle file. Never open an untrusted figure. PNG, PDF and SVG export do not require pickle.

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

The embedded widget includes **Properties**, **Fit figure**, **Refresh data**, **Open in viewer** and **Save image**. Opening a separate viewer transfers a trusted in-process figure via pickle and requires a normal `if __name__ == "__main__"` entry point. Both embedded and standalone file dialogs are drawn without blocking frame updates.

## Embedded file dialogs

Retain a `FileDialog` for its owning GUI and draw it in the same ImGui window and ID scope every frame:

```python
from deamat import GUI, GUIState, imgui
from deamat.widgets import FileDialog


def main():
    gui = GUI(GUIState())
    picker = FileDialog(gui)

    def update(state, gui, dt):
        imgui.begin("Files")
        if imgui.button("Open files"):
            picker.open("Open files", "JSON files{.json},.*", multiselect=True)
        result = picker.draw()
        if result is not None:
            state.paths = result.paths
        imgui.end()

    gui.update = update
    gui.run()


if __name__ == "__main__":
    main()
```

`open`, `save`, and `select_folder` start a request; `active` reports whether one is pending. Starting another request on the same picker while active raises `RuntimeError`. `draw()` returns `None` while pending or idle, then one `DialogResult` containing a tuple of `pathlib.Path` objects. An empty tuple means cancellation. `save()` requires confirmation before returning an existing destination. The picker selects paths; the application performs the actual file I/O.

`starting_dir` is a directory, not a suggested filename.
File filters use ImFileDialog syntax, for example `"Images{.png,.jpg},.*"`.
The public bundle initializes the dialog's OpenGL icons and thumbnails.
Only one dialog request can be active across all wrappers.
GUI shutdown closes its picker.
An explicit `close()` permanently disposes a wrapper.
Close an already-drawn active dialog in its original drawing frame and ID scope.

## Threads, coroutines and jobs

Construct and run `GUI` on the main thread. GUI state and all Matplotlib/ImGui/GPU operations belong to that thread. Background work returns data; it must not mutate live figures or GUI state.

- `gui.post(callback, *args)` queues a main-thread callback and returns a `concurrent.futures.Future`. In a coroutine use `await asyncio.wrap_future(gui.post(...))`; never block the GUI thread waiting for queued work.
- `gui.exec_coroutine(coro)` runs a coroutine on the background asyncio loop and returns a Future. Post results back to the GUI thread.
- `gui.submit_job(function, *args, callback=None)` returns the process-computation Future. Its optional result callback runs on the GUI thread; completion of the Future does not mean that callback has already run. Functions and arguments must be spawn-pickleable: define worker functions at module scope and guard the entry point.
- Background/callback failures are logged and retained in `gui.errors`; posted callback exceptions are available on their returned Future.
- `gui.add_cleanup(callback)` registers reverse-order, one-time UI-thread resource disposal.
- `gui.close()` is idempotent and safe from a UI callback. Pending jobs are cancelled; running process workers are terminated and joined before resource cleanup. Workers that do not stop within a shared one-second grace period are killed. On Linux, pool workers also die if the GUI process exits abruptly, including SIGKILL. This ownership covers the executor workers, not subprocesses created by user jobs. Coroutines must cooperate with cancellation; an async shutdown exceeding one second is reported.

`GUI(..., update_mode="continuous", max_fps=60)` selects continuous rendering. `GUI(..., update_mode="ondemand", max_fps=60)` selects on-demand rendering. `max_fps` limits the frame rate in both modes. In on-demand mode, input and posted work request frames. Call `gui.request_draw()` when external state needs a frame.

For ImAnim, call `im_anim.update_begin_frame()` once at the start of your update callback. Make this call before any tween calls. Use stable ImGui IDs for animation channels. Pass the update callback's `dt` to tween functions. In on-demand mode, call `gui.request_draw()` while an animation is active. Deamat does not call `im_anim.update_begin_frame()` for the application.

See `examples/4-async_update.py` and `examples/7-main-thread-dispatch.py` for executable usage.

## Native windows

On GLFW/X11, ImGui panels can leave the main window and dock again. This is enabled by default. `GUI(..., viewports=False)` keeps panels inside the main window. Native Wayland does not support detached viewports through the GLFW platform backend.

Detached windows stay separate when they overlap the main window; docking requires a deliberate titlebar drag onto a docking target. Ordinary detached windows request standard native decorations, allowing compositor-owned titlebar movement where supported; ImGui popups and tooltips remain undecorated. Closing a detached window closes its panel, not the application. Native window geometry is reconciled before layout, and each surface uses its actual framebuffer-to-window ratio when resized or moved between outputs.

Only already-detached ordinary panes opt out of automatic merging. Main-owned modal dialogs, nested popups and tooltips retain ImGui's normal viewport ownership instead of being forced into separate native windows.

Applications may explicitly give a modal its own native window using `WindowClass.viewport_flags_override_set = imgui.ViewportFlags_.no_auto_merge`. On X11, deamat translates ImGui's `parent_viewport_id` into `WM_TRANSIENT_FOR`, updates or removes it when ownership changes, and retires its cached native identity with the window. It does not create a second logical ownership model.

When an application window gains focus while an ImGui modal blocks it, the X11 host requests focus for that modal after native focus callbacks settle. Focus leaving the application is not redirected. Window-manager activation policy still applies: Sway's default `urgent` policy refuses this activation request. Set `focus_on_window_activation smart` in Sway to allow restoration on the visible workspace. Deamat never changes compositor configuration, forces topmost, or bypasses activation policy. Windows/macOS behavior is unchanged.

Native input callbacks stay alive until the platform window is destroyed. The stock OpenGL renderer creates and releases each viewport's rendering resources.

On X11, secondary windows use the `DeamatViewport` class, `deamat-viewport` instance and utility window type; the main window's identity is unchanged. They are not forced always-on-top. For Sway/XWayland, add this narrowly scoped rule to your Sway configuration:

```sway
for_window [class="^DeamatViewport$" instance="^deamat-viewport$"] floating enable
```

The stock binding exposes secondary windows only after they are mapped. The class rule supplies Sway's floating policy when the identity arrives. Deamat does not modify compositor configuration.

Sway 1.12 has a separate movement limitation: its [mapped floating XWayland configure handler](https://github.com/swaywm/sway/blob/1.12/sway/desktop/xwayland.c#L584-L607) ignores the position requested by GLFW. During an ImGui titlebar drag, deamat reconciles layout and docking overlays to the confirmed native origin before application layout. This prevents alternating dock indicators and permits drag-to-dock without moving the source native window. Use the compositor-owned outer titlebar for native movement on Sway; the inner ImGui titlebar remains the docking gesture. Deamat does not bypass the window manager or send Sway IPC commands.

All windows share one ImGui context and OpenGL textures. The optional pygfx widget renders off screen with WGPU. It reads back changed frames and uploads them to an OpenGL image. Matplotlib renders through Agg and uploads only when dirty. Moving a panel does not recreate its figure.

`gui.get_pixel_ratio()` returns the current ImGui viewport's framebuffer ratio, or the main window's ratio outside a frame. It is not the monitor's content scale. The retained widgets use it when their backing image dimensions change.

`gui.add_input_handler(callback, *event_types)` and `remove_input_handler` subscribe to `pointer_up`, `key_down`, `key_up`, and application-wide `focus_out` events from any viewport. Pointer coordinates are in ImGui screen space (global desktop coordinates when viewports are enabled, window-local otherwise). Native input also wakes on-demand rendering; deferred ImGui input is drained before the GUI returns to idle.

The Python GLFW binding and imgui-bundle must use the same GLFW library. Import `deamat` or `imgui_bundle` before importing `glfw`; deamat rejects mismatched libraries rather than passing window pointers between them.

## pygfx scenes

`pygfx_canvas(gui, state, id, on_init=None, controller=None, *, camera=None, continuous=True)` returns a public `PygfxCanvas` handle with `scene`, `camera`, `controller`, `renderer`, `invalidate()` and `close()`. An initializer receives `(scene, camera)` and may return a replacement camera. Do not access private GUI scene dictionaries.

The canvas retains its offscreen WGPU target. When the scene redraws, it reads back RGBA pixels and updates an OpenGL image for ImGui. Static scenes reuse that image without repeated readback. It forwards pointer, wheel and keyboard input, including captured releases outside the canvas. Controller camera filters are preserved; resizing preserves camera field of view/world-space extents. Set `material.pick_write=True` for pygfx objects that need pick events.

Use `continuous=False` for static scenes and call `invalidate()` after scene changes. Animated scenes should update existing geometry buffers/materials rather than allocating a new scene every frame. See `examples/5-pygfx.py`, `examples/6-pygfx_more.py` and `examples/8-pygfx_2d.py`.

## Development

```sh
uv sync --locked --extra pygfx
uv run pytest -q
uv build
```

Run GUI checks on an isolated display. On headless Linux, use Xvfb and software OpenGL. The optional pygfx widget also requires a working WGPU driver. Set `DEAMAT_GLFW_EGL=1` to select EGL context creation for off-screen checks when GLX is unavailable.

`DEAMAT_SWAY_ACCEPTANCE=1 uv run pytest -s tests/test_sway_viewports.py` starts a private two-output headless Sway session. It requires `sway`, `swaymsg`, `grim` and working OpenGL. It does not access the user's desktop or modify compositor configuration.

The interactive, self-contained viewer design draft is `.ui-drafts/figure-viewer/v1.html`. It uses a labelled SVG sample, not the Python renderer; native screenshots beside it document the implemented surface. It can be opened directly in a browser, or served with the accompanying localhost-only review server for persisted feedback.

## 0.3 migration

- Replace `im_plot_figure(...)` with `figure(gui, state, name, ...)`.
- Replace `state.sync()` / `SyncContext` deep-copy merging with `gui.post(...)`; the sync module is removed.
- Use `GUI(max_fps=...)`, not an unused `gui.fps` attribute.
- Retain the public pygfx canvas handle instead of mutating private scene/renderer registries.
- Importing the package no longer changes the global multiprocessing start method. Workers and standalone figure windows explicitly use a spawn context.
- Figure dimensions and existing artists are preserved; editing properties does not create a suptitle merely by displaying its control.
- Core GUI dependencies are the public imgui-bundle package, GLFW, PyOpenGL, Matplotlib and NumPy. The `pygfx` extra provides pygfx, WGPU and rendercanvas.
