# AGENTS.md

## Project Overview

**Deamat** is a Python GUI scaffolding library (v0.2.0) for building interactive scientific visualization applications. It combines:

- **imgui_bundle** with wgpu-based ImGui rendering
- **wgpu/rendercanvas** for window management and GPU access
- **pygfx** for 3D visualization (zerocopy texture sharing with imgui)
- **matplotlib** for 2D plotting

## Architecture

```
deamat/
├── __init__.py          # Package entry, re-exports core classes, widgets, and imgui
├── __main__.py          # CLI entry point (deamat-demo)
├── gui.py               # Main GUI class with wgpu/pygfx/ImGui integration
├── guistate.py          # State container base class with figure registry
├── mpl_view.py          # Standalone matplotlib figure viewer (CLI: mplview)
├── sync.py              # Thread-safe state synchronization (SyncContext)
└── widgets/
    ├── __init__.py      # Widget exports (figure, pygfx_canvas)
    ├── figure.py        # Matplotlib figure embedding
    └── pygfx_canvas.py  # pygfx 3D canvas widget (zerocopy)
```

## CLI Tools

- `deamat-demo` - Placeholder entry point with usage instructions
- `mplview <figure.pkl>` - Standalone viewer for pickled matplotlib figures

## Core Components

### GUI (`gui.py`)
Central application manager:
- Creates/manages `RenderCanvas` via wgpu/rendercanvas
- Uses `gfx.WgpuRenderer` for pygfx rendering
- Uses `ImguiRenderer` from `wgpu.utils.imgui` for imgui integration
- Initializes Dear ImGui with docking support
- Runs continuous render loop with delta time via `gfx.Clock`
- Provides async support via background asyncio thread
- Provides `ProcessPoolExecutor` for CPU-bound jobs
- Manages figure caching and updates
- Logs errors via module-level logger

Key methods: `run()`, `submit_job()`, `exec_coroutine()`

### GUIState (`guistate.py`)
Base class for application state:
- Window dimension tracking
- Figure registry (dict-based) with input validation
- Matplotlib style configuration
- Thread-safe sync queue

Key methods: `add_figure()`, `invalidate_figure()`, `invalidate_all_figures()`, `sync()`, `set_plt_style()`

### SyncContext (`sync.py`)
Async context manager for thread-safe state mutation from background threads using deep-copy/merge pattern.

### Widgets (`widgets/`)
- `figure()`: Embeds matplotlib figures into ImGui windows
- `pygfx_canvas()`: Renders pygfx Scene into ImGui via zerocopy texture sharing

### MPLView (`mpl_view.py`)
Standalone matplotlib figure viewer with interactive editing, styling controls, and export capabilities. Can be invoked via CLI (`mplview`) or programmatically.

## Key Patterns

1. **Immediate-Mode GUI**: UI rebuilt each frame in update callback
2. **State Subclassing**: Users extend `GUIState` with application data
3. **Figure Factory**: Figures created via `(state) -> Figure` functions
4. **Invalidation Pattern**: Mark-dirty for efficient redraws
5. **Callback Injection**: `gui.update` set to user function
6. **Context Manager Threading**: `sync()` for thread safety
7. **Registry Pattern**: Figures/canvases stored by name in dicts

## Dependencies

- imgui_bundle (>=1.5.2), imgui (>=2.0.0)
- pygfx (>=0.6.0), wgpu (>=0.18.0), rendercanvas (>=1.0.0)
- matplotlib (>=3.9.2)
- numpy (>=2.0.1), pydantic (>=2.8.2)
- Python >=3.11

## Examples

Located in `examples/`:
1. `1-basic.py` - Basic window creation
2. `2-ui_update.py` - UI widgets and state updates
3. `3-matplotlib.py` - Matplotlib figure integration
4. `4-async_update.py` - Async operations (see note about `sync()` for thread safety)
5. `5-pygfx.py`, `6-pygfx_more.py` - pygfx 3D visualization
6. `7-sync_context.py` - Thread-safe state synchronization
7. `8-pygfx_2d.py` - pygfx 2D visualization (Lissajous figure with OrthographicCamera)

## Tests

`tests/test_gui.py` - Basic sanity checks for GUI initialization and state management.

## Development Notes

- Uses Nix flake for development environment (see `flake.nix`)
- Package managed via `pyproject.toml` with uv
- ImGui is re-exported from `deamat` to ensure version consistency
- Multiprocessing uses 'spawn' method (set at module load in `widgets/figure.py`)
