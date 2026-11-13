# AGENTS.md

## general

* Use KISS
* No defensive code, unless explicitly required.
* Ask me before making judgement calls.
* Do not implement backwards-compatibility unless explictly required.

## Language

Use ASD-STE100 Simplified Technical English in specifications and documentation.

- Use short, direct sentences.
- Use active voice.
- Give one instruction in each sentence.
- Use one term for one concept.
- Give each term one meaning.
- Use the terms in `CONTEXT.md` and the names in the public API.
- Define a necessary new term before its first use.
- Do not invent labels for implementation eras, architecture qualities, migrations, or revisions.
- State the current requirements in specifications.
- Keep implementation history in implementation records.
- Put a representative example before reference material in a data-format specification.
- Do not use the word `provenance`. Use `source`, `producer`, `derivation`, or `history`.
- Do not use the word `contract`. Use `specification`, `requirements`, `API`, `behavior`, or `rules`.
- Use `reader`, `writer`, `encoding`, `decoding`, or `serialization` for data conversion. Do not use `codec`.
- Do not use `wire` as a noun for serialized data. Use `JSON representation`, `JSON document`, or the exact format name.

## Project Overview

Deamat is a Python library for interactive scientific applications.
It combines Dear ImGui, Matplotlib and pygfx.
`pyproject.toml` defines the package version and dependency requirements.
`README.md` contains installation instructions and public API examples.

## Architecture

| Module | Purpose |
|---|---|
| `deamat/__init__.py` | Exports `GUI`, `GUIState`, `widgets` and `imgui`. |
| `deamat/__main__.py` | Creates the example figure for `deamat-demo`. |
| `deamat/gui.py` | Owns the window, render loop, background work and resource cleanup. |
| `deamat/_glfw_viewports.py` | Integrates native GLFW input and detached OpenGL viewports. |
| `deamat/guistate.py` | Stores application state and the figure registry. |
| `deamat/mpl_canvas.py` | Handles Matplotlib input and figure textures. |
| `deamat/mpl_properties.py` | Provides Matplotlib property controls. |
| `deamat/mpl_view.py` | Provides `MPLView` and the `mplview` CLI. |
| `deamat/widgets/figure.py` | Embeds a registered Matplotlib figure. |
| `deamat/widgets/pygfx_canvas.py` | Embeds an optional offscreen pygfx renderer through OpenGL image upload. |
| `deamat/widgets/file_dialog.py` | Provides `FileDialog` and `DialogResult`. |

## Application State and Background Work

- Construct and run `GUI` on the main thread.
- Keep application state, Matplotlib objects, ImGui calls and GPU operations on that thread.
- Assign the application update function to `gui.update`.
- Use a `GUIState` subclass for application data.
- Use `GUIState.add_figure()` to register a figure factory.
- Use `invalidate_figure()` or `invalidate_all_figures()` to request figure updates.
- Use `remove_figure()` to remove a figure and release its resources.
- Use `gui.post(callback, *args)` to send state changes from background work to the GUI thread.
- Do not copy or merge live GUI state between threads.
- Use `gui.exec_coroutine()` for background coroutines.
- Use `gui.submit_job()` for process jobs.
- Define process-job functions at module scope.
- Protect the application entry point with `if __name__ == "__main__":`.

`GUI` creates its process pool with the `spawn` method.
Job result callbacks run on the GUI thread.
`gui.add_cleanup()` registers resource cleanup.
`gui.close()` stops background work and releases GUI resources.
`gui.errors` stores background and callback failures.

## Rendering and Native Windows

`GUI(..., update_mode="continuous", max_fps=60)` selects continuous rendering.
`GUI(..., update_mode="ondemand", max_fps=60)` selects on-demand rendering.
`max_fps` limits the frame rate in both modes.
Input and posted work request frames in on-demand mode.
Call `gui.request_draw()` when external state needs a frame.

The GLFW integration uses the native ImGui platform backend.
It supports detached viewports on X11.
`GUI(..., viewports=False)` disables detached viewports.
The public imgui-bundle runner initializes GLFW and OpenGL.
All ImGui viewports share OpenGL textures.
Matplotlib renders through Agg before it uploads a figure image.
The optional pygfx widget reads changed WGPU images and uploads them to OpenGL.
See the README for Sway window rules and movement limitations.

## Dependencies

Use the dependency requirements in `pyproject.toml`.
Use the public imgui-bundle wheel.
Do not maintain or ship a patched dependency wheel.
Install `deamat[pygfx]` to use the optional pygfx widget.
Do not add a separate `imgui` package.
Import ImGui from `deamat` or `imgui_bundle`.
Import `deamat` or `imgui_bundle` before `glfw` so they use the same GLFW library.
Use `gui.create_image(pixels)` for CPU RGBA images.
Close the returned image when the application no longer needs it.
Do not access the pygfx device to upload ordinary UI images.

Import ImAnim with `from imgui_bundle import im_anim`.
Call `im_anim.update_begin_frame()` once before tween calls in each update callback.
Use stable ImGui IDs for animation channels.
Pass the update callback's `dt` to tween functions.
Call `gui.request_draw()` while an animation is active in on-demand mode.
Deamat does not update ImAnim automatically.

## CLI Tools

- `deamat-demo` and `python -m deamat` open an editable example figure.
- `mplview --trust-pickle <figure.pkl>` opens a trusted pickled Matplotlib figure.

Pickle files can execute Python code.
Never open an untrusted pickle file.

## Examples

The `examples/` directory contains:

- `1-basic.py`: Window creation.
- `2-ui_update.py`: Widgets and state updates.
- `3-matplotlib.py`: Matplotlib figure embedding.
- `4-async_update.py`: Background coroutines.
- `5-pygfx.py` and `6-pygfx_more.py`: pygfx scenes.
- `7-main-thread-dispatch.py`: State changes through `gui.post()`.
- `8-pygfx_2d.py`: A 2D pygfx scene.

## Verification

Use the Nix environment in `flake.nix` for development tools and native libraries.
Run commands with `nix run . -- -c 'command'`.
Run the test suite with `uv run --no-sync pytest -q`.

Tests cover GUI lifecycle, background work, Matplotlib input and properties, pygfx widgets, file dialogs and native viewports.
Native-window tests require a Linux X11 display.
Use an isolated X server such as Xvfb for tests that require absolute window placement or pointer movement.
Sway/XWayland can reject client-requested window movement.
Desktop output positions can invalidate fixed test coordinates.
The Sway acceptance test starts an isolated compositor.
Enable that test with `DEAMAT_SWAY_ACCEPTANCE=1`.
See `tests/test_sway_viewports.py` for its tool requirements.
