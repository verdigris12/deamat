#!/usr/bin/env python3

"""
Example: display a histogram generated with matplotlib and update it when the
state changes.  This example demonstrates how to integrate matplotlib figures
into an imgui interface using deamat.
"""

from matplotlib import pyplot as plt

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat.widgets import im_plot_figure
from deamat import imgui
import numpy as np


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        self.value = 0
        # generate an initial series of 1000 normally distributed points
        self.series = np.random.standard_normal(1000)

    def reroll(self) -> None:
        # regenerate the series with mean equal to the current value
        self.series = np.random.normal(loc=self.value, scale=1.0, size=1000)


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    if imgui.button('Increase value'):
        state.value += 1
        state.reroll()
        state.invalidate_figure('hist')
    imgui.text(f'{state.value}')
    imgui.begin("Figure")
    im_plot_figure(state, 'hist', autosize=True)
    imgui.end()


def imfig_hist(state: State) -> plt.Figure:
    fig, ax = plt.subplots()
    ax.hist(state.series, bins=20, alpha=0.75)
    ax.set_title('Histogram of Series')
    ax.set_xlabel('Value')
    ax.set_ylabel('Frequency')
    return fig


def main() -> None:
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


if __name__ == "__main__":
    main()
