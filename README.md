# Deamat

Python GUI components for exploratory scientific applications: Dear ImGui, an interactive Matplotlib viewer, pygfx scenes, background coroutines and process jobs.

Requires Python 3.11+ and a desktop graphics environment supported by wgpu. Python dependencies install with uv; the OS must provide working window-system and graphics drivers. Embedded file dialogs use ImFileDialog through WGPU, not Zenity, KDialog, or a second OpenGL renderer.

`imgui-bundle` is pinned to 1.92.0: the wgpu 0.29 ImGui backend uses draw-data APIs removed by later 1.92 builds. Upgrade the binding and backend together, with a native rendering smoke test.

## Install and run

From a checkout, rebuild the pinned imgui-bundle source with the texture-callback patch:

```sh
uv sync --locked
CMAKE_BUILD_PARALLEL_LEVEL=4 sh build-imgui-bundle.sh
uv pip install --no-deps --no-index --find-links dist 'imgui-bundle==1.92.0+deamat.1'
uv run --no-sync deamat-demo
uv run --no-sync mplview --trust-pickle figure.pkl
```

The build requires Git, uv, CMake, Ninja, a C++ compiler, and the upstream X11/OpenGL development headers on Linux. On NixOS, use `nix develop`, or run commands through `nix run . -- -c 'command'`; the flake supplies these build dependencies without changing its nixpkgs pin. `DEAMAT_IMGUI_BUILD_DIR` selects the retained source/build cache; the default is `.cache/deamat-imgui-bundle`.

The public imgui-bundle 1.92.0 wheel does **not** expose ImFileDialog's texture callbacks. `imgui-bundle-deamat.patch` adds those bindings and identifies the local wheel as `1.92.0+deamat.1`; `imgui-bundle-build-constraints.txt` pins compatible binding build tools. No upstream fork or binary release is assumed. The built wheel is specific to its Python version and platform.

`uv sync` or a normal `uv run` can replace the patched wheel with the public version from `uv.lock`. Reinstall the patched wheel after syncing and use `uv run --no-sync`, or lock the built wheel as a direct dependency in the consuming project. Other projects can add this checkout with `uv add /path/to/deamat` and add the matching wheel with `uv add /path/to/imgui_bundle-...whl`. For an isolated CLI installation, use `uv tool install --with /path/to/imgui_bundle-...whl .`.

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

`starting_dir` is a directory, not a suggested filename; the bundled widget has no public filename-preset API. File filters use ImFileDialog syntax, for example `"Images{.png,.jpg},.*"`. Image thumbnails and icons use the owning GUI's WGPU texture registry, including detached viewports.

GUI shutdown closes the picker and releases its callbacks and textures. An explicit `close()` permanently disposes it; an already-drawn active dialog must be closed in its original drawing frame and ID scope. Construction with an unpatched binding fails clearly rather than switching to another file browser.

## Threads, coroutines and jobs

Construct and run `GUI` on the main thread. GUI state and all Matplotlib/ImGui/GPU operations belong to that thread. Background work returns data; it must not mutate live figures or GUI state.

- `gui.post(callback, *args)` queues a main-thread callback and returns a `concurrent.futures.Future`. In a coroutine use `await asyncio.wrap_future(gui.post(...))`; never block the GUI thread waiting for queued work.
- `gui.exec_coroutine(coro)` runs a coroutine on the background asyncio loop and returns a Future. Post results back to the GUI thread.
- `gui.submit_job(function, *args, callback=None)` returns the process-computation Future. Its optional result callback runs on the GUI thread; completion of the Future does not mean that callback has already run. Functions and arguments must be spawn-pickleable: define worker functions at module scope and guard the entry point.
- Background/callback failures are logged and retained in `gui.errors`; posted callback exceptions are available on their returned Future.
- `gui.add_cleanup(callback)` registers reverse-order, one-time UI-thread resource disposal.
- `gui.close()` is idempotent and safe from a UI callback. Pending jobs are cancelled; running process workers are terminated and joined before resource cleanup. Workers that do not stop within a shared one-second grace period are killed. On Linux, pool workers also die if the GUI process exits abruptly, including SIGKILL. This ownership covers the executor workers, not subprocesses created by user jobs. Coroutines must cooperate with cancellation; an async shutdown exceeding one second is reported.

`GUI(..., update_mode="continuous", max_fps=60)` controls the rendercanvas scheduler. `update_mode="ondemand"` is useful for non-animated applications: input and posted work request frames; call `gui.request_draw()` when external state needs a frame.

See `examples/4-async_update.py` and `examples/7-main-thread-dispatch.py` for executable usage.

## Native windows

On GLFW/X11, ImGui panels can be dragged outside the main window and docked back inside it. This is enabled by default; `GUI(..., viewports=False)` keeps panels inside the main window. The GLFW platform backend does not support detached viewports on native Wayland, so deamat leaves them disabled there. Other rendercanvas backends retain single-window rendering.

Detached windows stay separate when they overlap the main window; docking requires a deliberate titlebar drag onto a docking target. Ordinary detached windows request standard native decorations, allowing compositor-owned titlebar movement where supported; ImGui popups and tooltips remain undecorated. Closing a detached window closes its panel, not the application. Native window geometry is reconciled before layout, and each surface uses its actual framebuffer-to-window ratio when resized or moved between outputs.

Only already-detached ordinary panes opt out of automatic merging. Main-owned modal dialogs, nested popups and tooltips retain ImGui's normal viewport ownership instead of being forced into separate native windows.

Applications may explicitly give a modal its own native window using `WindowClass.viewport_flags_override_set = imgui.ViewportFlags_.no_auto_merge`. On X11, deamat translates ImGui's `parent_viewport_id` into `WM_TRANSIENT_FOR`, updates or removes it when ownership changes, and retires its cached native identity with the window. It does not create a second logical ownership model.

When an application window gains focus while an ImGui modal blocks it, the X11 host requests focus for that modal after native focus callbacks settle. Focus leaving the application is not redirected. Window-manager activation policy still applies: Sway's default `urgent` policy refuses this activation request. Set `focus_on_window_activation smart` in Sway to allow restoration on the visible workspace. Deamat never changes compositor configuration, forces topmost, or bypasses activation policy. Windows/macOS behavior is unchanged.

Native input callbacks stay alive through platform-window destruction, including transitions where a still-live viewport is temporarily absent from the rendering list. Its presentation surface is unconfigured and released before the native window is destroyed. The main surface synchronizes against the native framebuffer before layout; if a resize races layout, rendering resumes on the next frame with matching dimensions.

On X11, secondary windows use the `DeamatViewport` class, `deamat-viewport` instance and utility window type; the main window's identity is unchanged. They are not forced always-on-top. For Sway/XWayland, add this narrowly scoped rule to your Sway configuration:

```sway
for_window [class="^DeamatViewport$" instance="^deamat-viewport$"] floating enable
```

The stock binding exposes secondary windows only after they are mapped, too late for Sway's initial utility-window floating decision. The class rule supplies that policy when the identity arrives. Deamat does not modify compositor configuration. These viewport features work with the public imgui-bundle 1.92.0 wheel; the embedded FileDialog patch is unrelated.

Sway 1.12 has a separate movement limitation: its [mapped floating XWayland configure handler](https://github.com/swaywm/sway/blob/1.12/sway/desktop/xwayland.c#L584-L607) ignores the position requested by GLFW. During an ImGui titlebar drag, deamat reconciles layout and docking overlays to the confirmed native origin before application layout. This prevents alternating dock indicators and permits drag-to-dock without moving the source native window. Use the compositor-owned outer titlebar for native movement on Sway; the inner ImGui titlebar remains the docking gesture. Deamat does not bypass the window manager or send Sway IPC commands.

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
# Install the patched binding as described above first.
uv run --no-sync pytest -q
uv build
```

Tests that construct a GUI require a display and working wgpu driver. On a headless Linux machine, provide Xvfb and a software Vulkan implementation, then use `xvfb-run -a uv run --no-sync pytest -q`. Native driver availability remains host-specific; choose a working Vulkan ICD explicitly if automatic driver discovery fails.

`DEAMAT_SWAY_ACCEPTANCE=1 uv run --no-sync pytest -s tests/test_sway_viewports.py` starts a private two-output headless Sway session; it requires `sway`, `swaymsg`, `grim` and a working Vulkan driver. It checks geometry, floating identity, overlap without merging and native close lifecycle, and writes screenshots to pytest's temporary directory. It does not touch the user's display or configuration and does not claim to pass the Sway titlebar-drag/docking limitation above. This viewport test does not need the patched FileDialog binding.

The interactive, self-contained viewer design draft is `.ui-drafts/figure-viewer/v1.html`. It uses a labelled SVG sample, not the Python renderer; native screenshots beside it document the implemented surface. It can be opened directly in a browser, or served with the accompanying localhost-only review server for persisted feedback.

## 0.3 migration

- Replace `im_plot_figure(...)` with `figure(gui, state, name, ...)`.
- Replace `state.sync()` / `SyncContext` deep-copy merging with `gui.post(...)`; the sync module is removed.
- Use `GUI(max_fps=...)`, not an unused `gui.fps` attribute.
- Retain the public pygfx canvas handle instead of mutating private scene/renderer registries.
- Importing the package no longer changes the global multiprocessing start method. Workers and standalone figure windows explicitly use a spawn context.
- Figure dimensions and existing artists are preserved; editing properties does not create a suptitle merely by displaying its control.
- Dependencies are limited to the current imgui-bundle/wgpu/rendercanvas/pygfx stack, Matplotlib, NumPy and GLFW. Unused legacy rendering and processing dependencies have been removed.
