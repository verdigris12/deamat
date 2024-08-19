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
        self.fig_colwidth = None
        self.sidebar_width = 200

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
            height=300,
            width=500,
            title='Figure 1'
        )

    def _figure_view_ui(self, state, fig):
        imgui_ds.imgui_fig.fig(figure=state.fig, title='')

        if imgui.is_mouse_clicked(imgui.MOUSE_BUTTON_LEFT):
            mouse_x, mouse_y = imgui.get_mouse_pos()
            ax = state.fig.gca()
            if ax.bbox.contains(mouse_x, mouse_y):
                self.state.fig_x, self.state.fig_y = ax.transData.inverted().transform(
                    (mouse_x, mouse_y)
                )

    def _sidebar_ui(self, state):
        fig = state.fig
        with imgui.begin_tab_bar("CfgTabs"):
            with imgui.begin_tab_item("Figure") as tab:
                if tab.selected:
                    self._figure_settings_ui(fig)
            for ax_n, ax in enumerate(fig.axes):
                with imgui.begin_tab_item(f'Axes {ax_n}') as tab:
                    if tab.selected:
                        self._axes_settings_ui(ax)

    def _figure_settings_ui(self, fig):
        imgui.text('Figure settings')

        changed, fig_width = imgui.input_float("Width", fig.get_figwidth(), 0.1, 1.0)
        if changed:
            fig.set_figwidth(fig_width)

        changed, fig_height = imgui.input_float("Height", fig.get_figheight(), 0.1, 1.0)
        if changed:
            fig.set_figheight(fig_height)

        changed, fig_dpi = imgui.input_float("DPI", fig.get_dpi(), 1.0, 10.0)
        if changed:
            fig.set_dpi(fig_dpi)

        changed, bg_color = imgui.color_edit3("Background Color", *fig.get_facecolor()[:3])
        if changed:
            fig.patch.set_facecolor(bg_color)

        suptitle_text = fig._suptitle.get_text() if fig._suptitle else ""
        suptitle_fontsize = fig._suptitle.get_fontsize() if fig._suptitle else 12
        suptitle_fontweight = fig._suptitle.get_fontweight() if fig._suptitle else "normal"
        suptitle_va = fig._suptitle.get_va() if fig._suptitle else "center"
        suptitle_ha = fig._suptitle.get_ha() if fig._suptitle else "center"
        suptitle_x = fig._suptitle.get_position()[0] if fig._suptitle else 0.5
        suptitle_y = fig._suptitle.get_position()[1] if fig._suptitle else 0.98

        def update_suptitle():
            fig.suptitle(
                suptitle_text, fontsize=suptitle_fontsize, fontweight=suptitle_fontweight,
                verticalalignment=suptitle_va, horizontalalignment=suptitle_ha,
                x=suptitle_x, y=suptitle_y
            )

        changed, suptitle_text = imgui.input_text(
            "Text", fig._suptitle.get_text() if fig._suptitle else "", 256
        )
        if changed:
            update_suptitle()

        changed, suptitle_fontsize = imgui.input_int(
            "Font Size", fig._suptitle.get_fontsize() if fig._suptitle else 12
        )
        if changed:
            update_suptitle()

        font_weights = [
            "ultralight",
            "light",
            "normal",
            "regular",
            "book",
            "medium",
            "roman",
            "semibold",
            "demibold",
            "demi",
            "bold",
            "heavy",
            "extra bold",
            "black"
        ]
        changed, selected_fontweight = imgui.combo(
            "Font Weight", font_weights.index(suptitle_fontweight), font_weights
        )
        if changed:
            suptitle_fontweight = font_weights[selected_fontweight]
            update_suptitle()

        vertical_alignments = ["center", "top", "bottom", "baseline"]
        changed, selected_va = imgui.combo(
            "Vertical Alignment", vertical_alignments.index(suptitle_va), vertical_alignments
        )
        if changed:
            suptitle_va = vertical_alignments[selected_va]
            update_suptitle()

        horizontal_alignments = ["center", "left", "right"]
        changed, selected_ha = imgui.combo(
            "Horizontal Alignment", horizontal_alignments.index(suptitle_ha), horizontal_alignments
        )
        if changed:
            suptitle_ha = horizontal_alignments[selected_ha]
            update_suptitle()

        changed, suptitle_x = imgui.input_float(
            "X", fig._suptitle.get_position()[0] if fig._suptitle else 0.5
        )
        if changed:
            update_suptitle()

        changed, suptitle_y = imgui.input_float(
            "Y", fig._suptitle.get_position()[1] if fig._suptitle else 0.98
        )
        if changed:
            update_suptitle()

        if imgui.button("Apply Changes"):
            self._rerender_figure(fig)

    def _axes_settings_ui(self, ax):
        imgui.text('Axes settings')

    def _rerender_figure(self, fig, width=None, height=None):
        dummy = plt.figure()
        new_manager = dummy.canvas.manager
        new_manager.canvas.figure = fig
        fig.set_canvas(new_manager.canvas)
        if width is not None:
            fig.set_figwidth(width / fig.dpi)
        if height is not None:
            fig.set_figheight(height / fig.dpi)
        # This clears rendered figure cache and forces rerendering
        imgui_ds.imgui_fig._fig_to_image.statics.fig_cache.clear()

    def update_ui(self, state, gui, dt):
        imgui.columns(2, "columns", True)
        fig = state.figures['Fig']['figure']

        # Left column for the figure
        # imgui.set_column_width(-1, imgui.get_window_width() - state.sidebar_width)
        if state.fig_colwidth != imgui.get_column_width():
            state.fig_colwidth = imgui.get_column_width()
            self._rerender_figure(fig, width=state.fig_colwidth)

        self._figure_view_ui(state, fig)

        imgui.next_column()

        self._sidebar_ui(state)

    def run(self):
        self.gui.run()
