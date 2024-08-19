#!/usr/bin/env python3

import sys
import pickle
import matplotlib.pyplot as plt

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat.widgets import im_plot_figure
import imgui


class State(GUIState):
    def __init__(self):
        GUIState.__init__(self)
        self.fig = None

    def load_figure(self, filename):
        with open(filename, 'rb') as file:
            fig = pickle.load(file)
        self.fig = fig


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
    # ax.hist(state.series, bins=20, alpha=0.75)
    ax.plot(range(len(state.series)), state.series)
    ax.set_title('Histogram of Series')
    ax.set_xlabel('Value')
    ax.set_ylabel('Frequency')
    return fig


def main():
    if len(sys.argv) != 2:
        print("Usage: python mpl_view.py <path_to_pickled_figure>")
        sys.exit(1)

    state = State()
    state.load_figure(sys.argv[1])
    gui = dGUI(State())
    gui.update = update_ui
    gui.state.add_figure(
        'hist',
        lambda: state.fig,
        height=200,
        width=500,
        title='Figure 1'
    )
    gui.run()


if __name__ == "__main__":
    main()
