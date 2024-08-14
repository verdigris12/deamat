#!/usr/bin/env python3

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


if __name__ == "__main__":
    main()
