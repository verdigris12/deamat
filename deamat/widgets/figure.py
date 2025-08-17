"""
Widgets for embedding matplotlib figures into an imgui interface.

The functions here are intended to be called from your UI update callback.  They
wrap up the bookkeeping needed to resize figures, redraw them on demand and
launch separate viewers for interactive inspection.
"""

import multiprocessing
from imgui_bundle import portable_file_dialogs as pfd
from imgui_bundle import imgui, imgui_fig
import pickle

from deamat.mpl_view import MPLView


def open_figure_in_pyplot(pickled_figure: bytes) -> None:
    """Spawn a new process to view a pickled figure using MPLView."""
    fig = pickle.loads(pickled_figure)
    view = MPLView(fig)
    view.run()


def im_plot_figure(state, figname: str, width: int | None = None, height: int | None = None, autosize: bool = False) -> None:
    """Render a matplotlib figure inside an imgui window.

    Parameters
    ----------
    state : GUIState
        The current GUI state containing the registered figures.
    figname : str
        The key under which the figure was registered via ``add_figure``.
    width : int, optional
        Desired width in pixels.  If ``autosize`` is True this value is ignored.
    height : int, optional
        Desired height in pixels.  If ``autosize`` is True this value is ignored.
    autosize : bool, default False
        If True, the figure will be resized to fill the available content region.
    """
    fig_entry = state.figures[figname]
    if autosize:
        fig_entry['width'], fig_entry['height'] = imgui.get_content_region_avail()
    else:
        fig_entry['width'] = width if width is not None else fig_entry['width']
        fig_entry['height'] = height if height is not None else fig_entry['height']

    figure = fig_entry['figure']
    title = fig_entry['title']
    refresh = (not fig_entry['dirty']) and (fig_entry['texture_dirty'])
    width = fig_entry['width']
    height = fig_entry['height']

    if imgui.button('Redraw ' + title):
        state.invalidate_figure(figname, width=width, height=height)

    imgui.same_line()

    if imgui.button('Open in viewer'):
        pickled_figure = pickle.dumps(figure)
        # Ensure the new process is spawned instead of forked to avoid issues on MacOS
        multiprocessing.set_start_method(method='spawn', force=True)
        p = multiprocessing.Process(target=open_figure_in_pyplot, args=(pickled_figure,))
        p.start()

    imgui.same_line()

    if imgui.button('Save image'):
        fpath = pfd.save_file(title + '.png', state.figure_path).result()
        if len(fpath) > 0:
            state.figure_path = fpath
            figure.savefig(fpath)
    return imgui_fig.fig('', figure, refresh_image=refresh, size=imgui.ImVec2(width, height))
