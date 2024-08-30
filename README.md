# Deamat: a Python GUI boilerplate
-----------------------------

***WORK IN PROGRESS***

* Based on `pyimgui` + `pygame`
* Matplotlib integration thanks to `imgui_datascience`
* Integrated multiprocessing job scheduler (yes, I need it)


This is a bare-bones library I use to construct immediate mode GUIs in Python.

## Installation

```bash
pip install git+https://github.com/verdigris12/deamat
```

## Usage

### Empty window

```python
from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState


class State(GUIState):
    def __init__(self):
        GUIState.__init__(self)

def main():
    gui = dGUI(State())
    gui.run()

```

### Adding widgets

```python

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
import imgui


class State(GUIState):
    def __init__(self):
        GUIState.__init__(self)
        self.value = 0


def update_ui(state, gui, dt):
    if imgui.button('Increase value'):
        state.value = state.value + 1
    imgui.same_line()
    imgui.text(f'{state.value}')


def main():
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


```

### Adding `matplotlib` figures

```python
from matplotlib import pyplot as plt

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat.widgets import im_plot_figure
import imgui
import numpy as np


class State(GUIState):
    def __init__(self):
        GUIState.__init__(self)
        self.value = 0
        self.series = np.random.standard_normal(1000)

    def reroll(self):
        self.series = np.random.normal(loc=self.value, scale=1.0, size=1000)


def update_ui(state, gui, dt):
    if imgui.button('Increase value'):
        state.value = state.value + 1
        state.reroll()
        state.invalidate_figure('hist')
    imgui.text(f'{state.value}')
    imgui.begin("Figure")
    im_plot_figure(state, 'hist', autosize=True)
    imgui.end()


def imfig_hist(state: State) -> plt.Figure:
    fig, ax = plt.subplots()
    ax.hist(state.series, bins=20, alpha=0.75)
    return fig


def main():
    gui = dGUI(State())
    gui.update = update_ui
    gui.state.add_figure(
        'hist',
        imfig_hist,
        height=200,
        width=500,
        title='Figure 1'
    )
    gui.run()
```


## Etymology
*Dea*-*mat*: *DEA*r imgui and *MAT*plotlib
