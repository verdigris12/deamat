# Deamat

Immediate-mode GUI scaffolding for Python that brings together **imgui_bundle** and **matplotlib** with a tiny wrapper around **pyglet**. It’s minimal on purpose: a window, a state object, an update loop, and helpers to embed and pop out Matplotlib figures.

- Python ≥ 3.11
- Linux/macOS (X11/GL; Nix devshell provided)
- Deamat re-exports `imgui` → use `from deamat import imgui` in your code

---

## Install (uv)

Install from a local checkout:

```bash
uv pip install -e .
````

Or install from GitHub:

```bash
uv pip install "deamat @ git+https://github.com/verdigris12/deamat"
```

If you see `ModuleNotFoundError: setuptools` during editable install, see “Development (robust, no isolation)” below.

---

## Quick start

A blank window:

```python
from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState

class State(GUIState):
    pass

if __name__ == "__main__":
    dGUI(State()).run()
```

Using `imgui` via deamat (note the import):

```python
from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui

class State(GUIState):
    def __init__(self):
        super().__init__()
        self.value = 0

def update_ui(state, gui, dt):
    if imgui.button("Increase"):
        state.value += 1
    imgui.same_line()
    imgui.text(str(state.value))

if __name__ == "__main__":
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()
```

Embedding a Matplotlib figure:

```python
from matplotlib import pyplot as plt
from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat.widgets import im_plot_figure
from deamat import imgui
import numpy as np

class State(GUIState):
    def __init__(self):
        super().__init__()
        self.value = 0
        self.series = np.random.standard_normal(1000)
    def reroll(self):
        self.series = np.random.normal(loc=self.value, scale=1.0, size=1000)

def imfig_hist(state) -> plt.Figure:
    fig, ax = plt.subplots()
    ax.hist(state.series, bins=20, alpha=0.75)
    ax.set_title("Histogram")
    return fig

def update_ui(state, gui, dt):
    if imgui.button("Increase"):
        state.value += 1
        state.reroll()
        state.invalidate_figure("hist")
    imgui.text(str(state.value))
    imgui.begin("Figure")
    im_plot_figure(state, "hist", autosize=True)
    imgui.end()

if __name__ == "__main__":
    gui = dGUI(State())
    gui.update = update_ui
    gui.state.add_figure("hist", imfig_hist, width=500, height=200, title="Figure 1")
    gui.run()
```

---

## Development (robust, no isolation)

The Nix devshell in this repo sets `UV_NO_BUILD_ISOLATION=1`. That means the build backend must already be in your venv before doing an editable install (PEP 660). Use **Option B + preinstall**:

1. Ensure `pyproject.toml` has a modern backend:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```

2. Preinstall the backend, then do the editable install:

```bash
uv pip install -U "setuptools>=68" wheel
uv pip install -e .
```

This fixes `ModuleNotFoundError: setuptools` when running `uv pip install -e .` without isolation.

---

## Nix devshell

Enter the devshell (it provides Python 3.11, uv, GL/X11 libs, and a `.venv`):

```bash
nix develop
# if needed:
source .venv/bin/activate
```

Because the devshell exports `UV_NO_BUILD_ISOLATION=1`, preinstall and then install editable:

```bash
uv pip install -U "setuptools>=68" wheel
uv pip install -e .
```

You can now run the examples or your own code.

---

## Running the examples

From the project root (after the editable install):

```bash
python examples/1-basic.py
python examples/2-ui_update.py
python examples/3-matplotlib.py
python examples/4-pyglet_animation.py
python examples/5-async_update.py
```

Notes:

* Examples must import ImGui via deamat: `from deamat import imgui`.
* `3-matplotlib.py` shows an embedded figure with a “Open in viewer” button that spawns a separate interactive viewer without blocking the main UI.

---

## API surface you’ll actually use

* `deamat.gui.GUI`: the app window and loop. Set `gui.update = your_update_fn`.
* `deamat.guistate.GUIState`: your mutable state holder; includes figure registry and window size.
* `deamat.widgets.im_plot_figure(state, name, ...)`: draw a registered Matplotlib figure inside the current ImGui window. Handles autosizing, redraws, and saving.
* `from deamat import imgui`: Deamat re-exports `imgui` from `imgui_bundle`. Don’t import `imgui_bundle.imgui` directly in examples or apps.

---

## Troubleshooting

* **`ModuleNotFoundError: setuptools` during `uv pip install -e .`**
  You disabled build isolation. Run:
  `uv pip install -U "setuptools>=68" wheel && uv pip install -e .`
* **Black/blank window**
  Ensure the GPU/GL drivers and X11 libraries are available. The Nix devshell already provides these.
* **Running over SSH**
  You need a working X server/forwarding or a local session; this is an on-screen GUI.

---

