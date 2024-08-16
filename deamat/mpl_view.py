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
        self.fig_x = None
        self.fig_y = None
        self.colwidth = None

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
        imgui.columns(2, "columns", True)
        fig = state.figures['Fig']['figure']

        # Left column for the figure
        imgui.set_column_width(-1, imgui.get_window_width() - 200)
        if state.colwidth != imgui.get_column_width():
            state.colwidth = imgui.get_column_width()
            print(state.colwidth)
            fig.set_figwidth(state.colwidth / fig.dpi)
            state.invalidate_all_figures()

        imgui_ds.imgui_fig.fig(figure=state.fig, title='')

        if imgui.is_mouse_clicked(imgui.MOUSE_BUTTON_LEFT):
            mouse_x, mouse_y = imgui.get_mouse_pos()
            ax = state.fig.gca()
            if ax.bbox.contains(mouse_x, mouse_y):
                self.state.fig_x, self.state.fig_y = ax.transData.inverted().transform((mouse_x, mouse_y))
                print(self.state.fig_x)
                print(self.state.fig_y)

        imgui.next_column()

        # Right column for additional controls
        imgui.set_column_width(-1, 200)
        imgui.text("Right Column")

    def run(self):
        self.gui.run()
