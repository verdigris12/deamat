# Deamat

Immediate-mode GUI scaffolding for Python that brings together `imgui_bundle` (on top of `pyglet`) and `matplotlib`.
Supports simple spawning job processes and executing async coroutines.

---

## Install


```bash
uv pip install "deamat @ git+https://github.com/verdigris12/deamat"
```

---

## Basic concepts

* `deamat.gui.GUI`: the app window and loop. Set `gui.update = your_update_fn`.
* `deamat.guistate.GUIState`: your mutable state holder; includes figure registry.
* `deamat.widgets.im_plot_figure(state, name, ...)`: ImGUI widget for displaying matplotlib figures
* `from deamat import imgui`: Deamat re-exports `imgui` from `imgui_bundle`. Don’t import `imgui_bundle.imgui` directly in examples or apps.

---

## Quick start

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

Install from a local checkout:

```bash
uv pip install -U "setuptools>=68" wheel
uv pip install -e .
```

This fixes `ModuleNotFoundError: setuptools` when running `uv pip install -e .` without isolation.

For NixOS, the project flake has a devshell.


---

## Running the examples

```bash
uv run examples/1-basic.py
uv run examples/2-ui_update.py
uv run examples/3-matplotlib.py
uv run examples/4-pyglet_animation.py
uv run examples/5-async_update.py
```

---
