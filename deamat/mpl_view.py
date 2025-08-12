#!/usr/bin/env python3

"""
Standalone viewer for matplotlib figures.  The :class:`MPLView` class opens a
full‑screen window with a sidebar that exposes various figure and axes settings.

It is used internally by the widgets module to allow users to inspect and
modify figures in a separate window while the main GUI remains responsive.
"""

import pickle
from matplotlib import font_manager
import matplotlib.colors as mcolors
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvasAgg

from imgui_bundle import portable_file_dialogs as pfd
from imgui_bundle import imgui, imgui_fig

from .guistate import GUIState
from .gui import GUI


class MPLVState(GUIState):
    def __init__(self, fig):
        super().__init__()
        self.fig = fig
        self._ensure_agg(fig)
        self.fig_x: float | None = None
        self.fig_y: float | None = None
        self.sidebar_width = 450
        self.refresh_required = True

    def _ensure_agg(self, fig):
        if fig is not None and not hasattr(getattr(fig, "canvas", None), "buffer_rgba"):
            FigureCanvasAgg(fig)

    def load_figure(self, filename: str) -> None:
        with open(filename, 'rb') as file:
            fig = pickle.load(file)
        self.fig = fig
        self._ensure_agg(fig)


class MPLView:
    def __init__(self, fig) -> None:
        self.state = MPLVState(fig)
        self.gui = GUI(self.state)
        # hook our update method into the GUI
        self.gui.update = lambda state, gui, dt: self.update_ui(state, gui, dt)
        self.gui.main_window_fullscreen = True

        # register the figure so widgets can draw it
        self.gui.state.add_figure(
            'Fig',
            lambda state: self.state.fig,
            height=300,
            width=500,
            title='Figure 1'
        )


    def _figure_view_ui(self) -> None:
        state = self.state
        figure = state.fig

        if imgui.is_mouse_clicked(imgui.MOUSE_BUTTON_LEFT):
            mouse_x, mouse_y = imgui.get_mouse_pos()
            ax = figure.gca()
            if ax.bbox.contains(mouse_x, mouse_y):
                self.state.fig_x, self.state.fig_y = ax.transData.inverted().transform(
                    (mouse_x, mouse_y)
                )

    def _sidebar_ui(self, state: MPLVState) -> None:
        # apply button placeholder – refresh the figure when pressed
        if imgui.button("Apply Changes"):
            state.refresh_required = True

        if imgui.begin_tab_bar("SidebarTabs"):
            if imgui.begin_tab_item("Figure")[0]:
                self._figure_settings_ui(state.fig)
                imgui.end_tab_item()
            for ax_n, ax in enumerate(state.fig.axes):
                if imgui.begin_tab_item(f'Axes_{ax_n}')[0]:
                    self._axes_settings_ui(ax)
                    imgui.end_tab_item()

            imgui.end_tab_bar()

    # -------------------------------------------------------------------------
    # Font editing helpers

    def _font_ui(self, text_object):
        if isinstance(text_object, list):
            mpl_text = text_object[0]
        else:
            mpl_text = text_object

        mpltext_fontsize = mpl_text.get_fontsize()
        mpltext_fontweight = mpl_text.get_fontweight()
        mpltext_font = mpl_text.get_fontname()
        mpltext_color = mcolors.to_rgba(mpl_text.get_color())
        mpltext_va = mpl_text.get_va()
        mpltext_ha = mpl_text.get_ha()
        mpltext_x = mpl_text.get_position()[0]
        mpltext_y = mpl_text.get_position()[1]

        def update_mpltext() -> None:
            def update(mtext) -> None:
                mtext.set(
                    fontsize=mpltext_fontsize, fontweight=mpltext_fontweight,
                    fontname=mpltext_font,
                    verticalalignment=mpltext_va, horizontalalignment=mpltext_ha,
                    x=mpltext_x, y=mpltext_y,
                    color=mpltext_color
                )

            if isinstance(text_object, list):
                for element in text_object:
                    update(element)
            else:
                update(mpl_text)

        changed, mpltext_fontsize = imgui.input_int(
            "Font Size", int(mpl_text.get_fontsize())
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
                        'extra bold', 'black']
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

        changed, mpltext_color = imgui.color_edit3("Font Color", mpltext_color[:3])
        if changed:
            update_mpltext()

        changed, (mpltext_x, mpltext_y) = imgui.input_float2(
            "Position", (mpltext_x, mpltext_y)
        )
        if changed:
            update_mpltext()

    def _figure_settings_ui(self, fig):
        imgui.text('Figure settings')

        changed, fig_width = imgui.input_float(
            "Width, in", fig.get_figwidth(), 0.1, 1.0
        )
        if changed and fig_width > 0.5:
            fig.set_figwidth(fig_width)
            self.state.refresh_required = True

        changed, fig_height = imgui.input_float(
            "Height, in", fig.get_figheight(), 0.1, 1.0

        )
        if changed and fig_height > 0.5:
            fig.set_figheight(fig_height)
            self.state.refresh_required = True

        changed, fig_dpi = imgui.input_float(
            "DPI", fig.get_dpi(), 1.0, 10.0

        )
        if changed and fig_dpi > 10:
            fig.set_dpi(fig_dpi)
            self.state.refresh_required = True

        changed, bg_color = imgui.color_edit3("Background Color", fig.get_facecolor()[:3])
        if changed:
            fig.patch.set_facecolor(bg_color)

        _, has_suptitle = imgui.checkbox("Figure title", fig._suptitle is not None)
        if not has_suptitle:
            fig.suptitle('')
            fig._suptitle = None
            return
        if has_suptitle and fig._suptitle is None:
            fig.suptitle("")

        self._font_button_ui(fig._suptitle, id="suptitle")
        imgui.same_line()
        changed, sptext = imgui.input_text("Suptitle text", fig._suptitle.get_text(), 256)
        if changed:
            fig.suptitle(sptext)

    def _axis_gridline_settings(self, ax, gridlines, which: str, axis: str) -> None:
        id = f'ax_grid_{which}_{axis}'

        if len(gridlines) == 0:
            visible = False
            changed, visible = imgui.checkbox(
                f'Visible##nan_{id}', visible
            )
            if changed:
                ax.grid(visible, which=which, axis=axis)

            if not visible:
                return

        else:
            linetype_list = ['-', '--', '-.', ':']

            color = mcolors.to_rgba(gridlines[0].get_color())
            alpha = gridlines[0].get_alpha() or 1
            linetype = gridlines[0].get_linestyle()
            width = gridlines[0].get_linewidth()
            visible = gridlines[0].get_visible()

            if color is None:
                color = (1, 1, 1)
            if linetype is None:
                linetype = '-'
            if width is None:
                width = 0.1

            try:
                lt_id = linetype_list.index(linetype)
            except ValueError:
                lt_id = 0

            changed, visible = imgui.checkbox(
                f'Visible##{id}', visible
            )
            if changed:
                ax.grid(visible, which=which, axis=axis)

            if not visible:
                return

            changed, alpha = imgui.slider_float(
                f'Alpha##{id}', alpha, 0.0, 1.0
            )
            if changed:
                ax.grid(True, which=which, axis=axis, alpha=alpha)

            changed, lt_id = imgui.combo(
                f'Linetype##{id}', lt_id, linetype_list
            )
            if changed:
                ax.grid(True, which=which, axis=axis, linestyle=linetype_list[lt_id])

            changed, color = imgui.color_edit3(f'Color##{id}', color[:3])
            if changed:
                ax.grid(True, which=which, axis=axis, color=color)

            changed, width = imgui.input_float(
                f'Linewidth##{id}', width
            )
            if changed:
                ax.grid(True, which=which, axis=axis, linewidth=width)

    def _axis_grid_settings(self, ax) -> None:
        if imgui.begin_tab_bar("GridlineTabs"):
            if imgui.begin_tab_item("Major X")[0]:
                self._axis_gridline_settings(ax, ax.xaxis.get_gridlines(), 'major', 'x')
                imgui.end_tab_item()
            if imgui.begin_tab_item("Minor X")[0]:
                self._axis_gridline_settings(ax, ax.xaxis.get_minorticklines(), 'minor', 'x')
                imgui.end_tab_item()
            if imgui.begin_tab_item("Major Y")[0]:
                self._axis_gridline_settings(ax, ax.yaxis.get_gridlines(), 'major', 'y')
                imgui.end_tab_item()
            if imgui.begin_tab_item("Minor Y")[0]:
                self._axis_gridline_settings(ax, ax.yaxis.get_minorticklines(), 'minor', 'y')
                imgui.end_tab_item()
            imgui.end_tab_bar()

        if imgui.button('Start IPython console'):
            from IPython import embed
            embed()

    def _font_button_ui(self, mpl_text, id: str | None = None) -> None:
        if id is None:
            id = 'font_settings_button'
        modal_id = f'{id}_modal'
        imgui.push_id(id)
        if imgui.button("T"):
            imgui.open_popup(modal_id)

        if imgui.begin_popup_modal(modal_id)[0]:
            self._font_ui(mpl_text)
            if imgui.button("Close"):
                imgui.close_current_popup()
            imgui.end_popup()
        imgui.pop_id()

    def _axis_settings(self, ax) -> None:
        self._font_button_ui(ax.yaxis.get_label(), id="xaxis_font")
        imgui.same_line()
        changed, xlabel = imgui.input_text("X Label", ax.get_xlabel(), 256)
        if changed:
            ax.set_xlabel(xlabel)

        self._font_button_ui(ax.yaxis.get_label(), id="yaxis_font")
        imgui.same_line()
        changed, ylabel = imgui.input_text("Y Label", ax.get_ylabel(), 256)
        if changed:
            ax.set_ylabel(ylabel)

        changed, axis_on = imgui.checkbox("Axis On", ax.axison)
        if changed:
            ax.set_axis_on() if axis_on else ax.set_axis_off()

        imgui.same_line()
        changed, frame_on = imgui.checkbox("Frame On", ax.get_frame_on())
        if changed:
            ax.set_frame_on(frame_on)

        changed, top_spine_on = imgui.checkbox("Top Spine", ax.spines['top'].get_visible())
        if changed:
            ax.spines['top'].set_visible(top_spine_on)

        imgui.same_line()
        changed, bottom_spine_on = imgui.checkbox("Bottom Spine", ax.spines['bottom'].get_visible())
        if changed:
            ax.spines['top'].set_visible(bottom_spine_on)

        imgui.same_line()
        changed, right_spine_on = imgui.checkbox("Right Spine", ax.spines['right'].get_visible())
        if changed:
            ax.spines['right'].set_visible(right_spine_on)

        imgui.same_line()
        changed, left_spine_on = imgui.checkbox("Left Spine", ax.spines['left'].get_visible())
        if changed:
            ax.spines['left'].set_visible(left_spine_on)

        axis_color_x = ax.spines['bottom'].get_edgecolor()
        axis_color_y = ax.spines['left'].get_edgecolor()

        changed, (lw_t, lw_b, lw_r, lw_l) = imgui.input_float4(
            "Linewidth",
            (
                ax.spines['top'].get_linewidth(),
                ax.spines['bottom'].get_linewidth(),
                ax.spines['right'].get_linewidth(),
                ax.spines['left'].get_linewidth()
            )
        )
        if changed:
            ax.spines['bottom'].set_linewidth(lw_b)
            ax.spines['top'].set_linewidth(lw_t)
            ax.spines['left'].set_linewidth(lw_l)
            ax.spines['right'].set_linewidth(lw_r)

        changed, axis_color_x = imgui.color_edit3("X Axis Color", axis_color_x[:3])
        if changed:
            ax.spines['bottom'].set_edgecolor(axis_color_x)
            ax.spines['top'].set_edgecolor(axis_color_x)

        changed, axis_color_y = imgui.color_edit3("Y Axis Color", axis_color_y[:3])
        if changed:
            ax.spines['left'].set_edgecolor(axis_color_y)
            ax.spines['right'].set_edgecolor(axis_color_y)

        if imgui.collapsing_header('X Tick properties'):
            imgui.begin_child('xtickprops')
            self._font_ui(ax.xaxis.get_ticklabels())
            imgui.end_child()

        if imgui.collapsing_header('Y Tick properties'):
            imgui.begin_child('ytickprops')
            self._font_ui(ax.xaxis.get_ticklabels())
            imgui.end_child()

    def _axes_settings_ui(self, ax) -> None:
        changed, title = imgui.input_text("Title", ax.get_title(), 256)
        if changed:
            ax.set_title(title)

        changed, bg_color = imgui.color_edit3("Axes Background Color", ax.get_facecolor()[:3])
        if changed:
            ax.set_facecolor(bg_color)

        imgui.separator_text('Scale')

        changed, x_log_scale = imgui.checkbox("Logarithmic X Scale", ax.get_xscale() == 'log')
        if changed:
            ax.set_xscale('log' if x_log_scale else 'linear')

        changed, y_log_scale = imgui.checkbox("Logarithmic Y Scale", ax.get_yscale() == 'log')
        if changed:
            ax.set_yscale('log' if y_log_scale else 'linear')

        imgui.separator_text('Axis')
        self._axis_settings(ax)

        imgui.separator_text('Grid')
        self._axis_grid_settings(ax)

    # -------------------------------------------------------------------------
    # Main update

    def update_ui(self, state: MPLVState, gui: GUI, dt: float) -> None:
        # main menu bar
        if imgui.begin_main_menu_bar():
            if imgui.begin_menu("File", True):
                clicked_save_pickle, _ = imgui.menu_item("Save as pickle", "Ctrl+S", False, True)
                clicked_save, _ = imgui.menu_item("Export as PNG", "Ctrl+S", False, True)
                clicked_exit, _ = imgui.menu_item("Exit", "Ctrl+Q", False, True)
                if clicked_save_pickle:
                    file_path = pfd.save_file(
                        "Save Figure as Pickle", "", "",
                        ["Pickle files (*.pkl)", "All files (*.*)"]
                    )
                    if file_path:
                        with open(file_path, 'wb') as file:
                            pickle.dump(self.state.fig, file)
                elif clicked_exit:
                    exit(0)
                imgui.end_menu()
            imgui.end_main_menu_bar()

        available_width, available_height = imgui.get_content_region_avail()
        imgui.columns(2, "columns", False)
        imgui.set_column_width(0, available_width - state.sidebar_width)
        imgui.set_column_width(1, state.sidebar_width)

        # Center the figure horizontally and vertically within the left column
        column_width = imgui.get_column_width()
        figure_width = state.fig.get_figwidth() * state.fig.get_dpi()
        figure_height = state.fig.get_figheight() * state.fig.get_dpi()

        imgui.set_cursor_pos_x((column_width - figure_width) / 2)
        imgui.set_cursor_pos_y((available_height - figure_height) / 2)

        imgui_fig.fig(
            '',
            state.fig,
            size=(figure_width, figure_height),
            refresh_image=state.refresh_required,
            resizable=False
        )
        state.refresh_required = False

        imgui.next_column()
        self._sidebar_ui(state)

    # -------------------------------------------------------------------------
    def run(self) -> None:
        self.gui.run()
