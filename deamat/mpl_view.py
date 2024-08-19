#!/usr/bin/env python3

import pickle
import imgui_datascience as imgui_ds
import matplotlib.pyplot as plt
from matplotlib import font_manager

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

        if imgui.button("Apply Changes"):
            self._rerender_figure(fig)

        with imgui.begin_tab_bar("CfgTabs"):
            with imgui.begin_tab_item("Figure") as tab:
                if tab.selected:
                    self._figure_settings_ui(fig)
            for ax_n, ax in enumerate(fig.axes):
                with imgui.begin_tab_item(f'Axes {ax_n}') as tab:
                    if tab.selected:
                        self._axes_settings_ui(ax)

    def _text_ui(self, mpl_text, update_callback):
        mpltext_text = mpl_text.get_text()
        mpltext_fontsize = mpl_text.get_fontsize()
        mpltext_fontweight = mpl_text.get_fontweight()
        mpltext_font = mpl_text.get_fontname()
        mpltext_va = mpl_text.get_va()
        mpltext_ha = mpl_text.get_ha()
        mpltext_x = mpl_text.get_position()[0]
        mpltext_y = mpl_text.get_position()[1]

        def update_mpltext():
            update_callback(
                mpltext_text, fontsize=mpltext_fontsize, fontweight=mpltext_fontweight,
                fontname=mpltext_font, verticalalignment=mpltext_va, horizontalalignment=mpltext_ha,
                x=mpltext_x, y=mpltext_y
            )

        changed, mpltext_text = imgui.input_text(
            "Text", mpl_text.get_text(), 256
        )
        if changed:
            update_mpltext()

        changed, mpltext_fontsize = imgui.input_int(
            "Font Size", mpl_text.get_fontsize()
        )
        if changed:
            update_mpltext()

        available_fonts = sorted(set([f.name for f in font_manager.fontManager.ttflist]))
        changed, selected_font = imgui.combo(
            "Font", available_fonts.index(mpltext_font), available_fonts
        )
        if changed:
            mpltext_font = available_fonts[selected_font]
            mpltext_fontweight = "normal"  # Reset font weight to default
            update_mpltext()

        font_weights = ['ultralight', 'light', 'normal', 'regular', 'book', 'medium',
                        'roman', 'semibold', 'demibold', 'demi', 'bold', 'heavy',
                        'extra bold', 'black'
                        ]
        changed, fw_selection = imgui.combo(
            "Font Weight", font_weights.index(mpltext_fontweight), font_weights
        )
        if changed:
            mpltext_fontweight = font_weights[fw_selection]
            update_mpltext()

        vertical_alignments = ["center", "top", "bottom", "baseline"]
        changed, selected_va = imgui.combo(
            "Vertical Alignment", vertical_alignments.index(mpltext_va), vertical_alignments
        )
        if changed:
            mpltext_va = vertical_alignments[selected_va]
            update_mpltext()

        horizontal_alignments = ["center", "left", "right"]
        changed, selected_ha = imgui.combo(
            "Horizontal Alignment", horizontal_alignments.index(mpltext_ha), horizontal_alignments
        )
        if changed:
            mpltext_ha = horizontal_alignments[selected_ha]
            update_mpltext()

        changed, (mpltext_x, mpltext_y) = imgui.input_float2(
            "Position", mpltext_x, mpltext_y
        )
        if changed:
            update_mpltext()

    def _figure_suptitile_ui(self, fig):
        _, has_suptitle = imgui.checkbox("Figure title", fig._suptitle is not None)
        if not has_suptitle:
            fig.suptitle('')
            fig._suptitle = None
            return
        if has_suptitle and fig._suptitle is None:
            fig.suptitle("")

        self._text_ui(fig._suptitle, fig.suptitle)

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

        self._figure_suptitile_ui(fig)

    def _axes_settings_ui(self, ax):
        imgui.text('Axes settings')

        changed, grid_major = imgui.checkbox("Show Major Grid", ax.xaxis._major_tick_kw.get('gridOn', False))
        if changed:
            ax.grid(grid_major, which='major')

        major_alpha = next((line.get_alpha() for line in ax.get_xgridlines() if line.get_linestyle() == '-'), 1.0)
        minor_alpha = next((line.get_alpha() for line in ax.get_xgridlines() if line.get_linestyle() == '--'), 1.0)
        changed, (major_alpha, minor_alpha) = imgui.slider_float2("Grid Alpha (Major, Minor)", major_alpha, minor_alpha, 0.0, 1.0)
        if changed:
            for line in ax.get_xgridlines() + ax.get_ygridlines():
                if line.get_linestyle() == '-':
                    line.set_alpha(major_alpha)
                elif line.get_linestyle() == '--':
                    line.set_alpha(minor_alpha)

        changed, grid_minor = imgui.checkbox("Show Minor Grid", ax.xaxis._minor_tick_kw.get('gridOn', False))
        if changed:
            ax.grid(grid_minor, which='minor')

        minor_alpha = next((line.get_alpha() for line in ax.get_xgridlines() if line.get_linestyle() == '--'), 1.0)

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
        self.state.invalidate_all_figures()
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
