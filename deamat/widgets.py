import multiprocessing
# import imgui
from imgui_bundle import portable_file_dialogs as pfd
from imgui_bundle import imgui, imgui_fig
import pickle

from .mpl_view import MPLView


def open_figure_in_pyplot(pickled_figure):
    fig = pickle.loads(pickled_figure)
    view = MPLView(fig)
    view.run()


def im_plot_figure(state, figname, width=None, height=None, autosize=False):
    fig_obj = state.figures[figname]
    figure = fig_obj['figure']
    title = fig_obj['title']

    if autosize:
        fig_obj['width'], fig_obj['height'] = imgui.get_content_region_available()
    else:
        if width:
            fig_obj['width'] = width
        if height:
            fig_obj['height'] = height
    if imgui.button('Redraw ' + title):
        state.invalidate_figure(figname)
    imgui.same_line()
    if imgui.button('Open in viewer'):
        pickled_figure = pickle.dumps(figure)
        multiprocessing.set_start_method(method='spawn', force=True)
        p = multiprocessing.Process(target=open_figure_in_pyplot, args=(pickled_figure,))
        p.start()
    imgui.same_line()
    if imgui.button('Save image'):
        fpath = pfd.save_file(title + '.png', state.figure_path).result()
        if len(fpath) > 0:
            state.figure_path = fpath
            figure.savefig(fpath)
    imgui_fig.fig('', figure)
