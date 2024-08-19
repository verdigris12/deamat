import matplotlib
import imgui
import imgui_datascience as imgui_ds
from imgui_bundle import portable_file_dialogs as pfd
import pickle
import multiprocessing
import matplotlib.pyplot as plt
import plotly.tools as tls


def open_figure_in_pyplot(pickled_figure):
    matplotlib.use('TkAgg')
    fig = pickle.loads(pickled_figure)
    dummy = plt.figure()
    new_manager = dummy.canvas.manager
    new_manager.canvas.figure = fig
    fig.set_canvas(new_manager.canvas)
    plt.show()

def open_figure_in_plotly(pickled_figure):
    matplotlib.use('TkAgg')
    fig = pickle.loads(pickled_figure)
    plotly_fig = tls.mpl_to_plotly(fig)
    plotly_fig.update_layout(bargap=0.2)  # Set a valid value for bargap
    plotly_fig.show()

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
    matplotlib.use(state.matplotlib_backend)
    if imgui.button('Redraw ' + title):
        state.invalidate_figure(figname)
    imgui.same_line()
    if imgui.button('Open in pyplot'):
        pickled_figure = pickle.dumps(figure)
        p = multiprocessing.Process(target=open_figure_in_pyplot, args=(pickled_figure,))
        p.start()
    imgui.same_line()
    if imgui.button('Open in plotly'):
        pickled_figure = pickle.dumps(figure)
        p = multiprocessing.Process(target=open_figure_in_plotly, args=(pickled_figure,))
        p.start()
    imgui.same_line()
    if imgui.button('Save figure'):
        fpath = pfd.save_file(title + '.png', state.figure_path).result()
        if len(fpath) > 0:
            state.figure_path = fpath
            figure.savefig(fpath)
    imgui_ds.imgui_fig.fig(figure=figure, title='')
