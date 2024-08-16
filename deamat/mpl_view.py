#!/usr/bin/env python3

import pickle
import imgui_datascience as imgui_ds
import matplotlib.pyplot as plt

import imgui

from .guistate import GUIState
from .gui import GUI


class MPLVState(GUIState):
    def __init__(self, fig):
        GUIState.__init__(self)
        self.fig = fig

    def load_figure(self, filename):
        with open(filename, 'rb') as file:
            fig = pickle.load(file)
        self.fig = fig


class MPLView():
    def __init__(self, fig):
        self.state = MPLVState(fig)
        self.gui = GUI(self.state)
        self.gui.update = lambda state, gui, dt: self.update_ui(state, gui, dt)
        self.gui.main_window_fullscreen = True

        # Reset canvas if the figure was pickled before
        dummy = plt.figure()
        new_manager = dummy.canvas.manager
        new_manager.canvas.figure = fig
        fig.set_canvas(new_manager.canvas)

        self.gui.state.add_figure(
            'Fig',
            lambda state: self.state.fig,
            height=200,
            width=500,
            title='Figure 1'
        )

    def update_ui(self, state, gui, dt):
        imgui_ds.imgui_fig.fig(figure=state.fig, title='')

    def run(self):
        self.gui.run()
