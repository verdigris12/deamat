import matplotlib
import multiprocessing
import imgui
import imgui_datascience as imgui_ds
from imgui_bundle import portable_file_dialogs as pfd
import pickle
from bokeh.plotting import figure, show
from bokeh.io import output_notebook
import matplotlib.pyplot as plt


def open_figure_in_pyplot(pickled_figure):
    matplotlib.use('TkAgg', force=True)
    # plt.ion()
    fig = pickle.loads(pickled_figure)
    dummy = plt.figure()
    new_manager = dummy.canvas.manager
    new_manager.canvas.figure = fig
    fig.set_canvas(new_manager.canvas)
    print(fig)
    fig.show()
    plt.show()


def open_figure_in_bokeh(pickled_figure):
    fig = pickle.loads(pickled_figure)
    output_notebook()
    p = figure(title="Bokeh Figure")
    # Assuming fig is a matplotlib figure, we need to convert it to Bokeh
    # This is a placeholder for actual conversion logic
    show(p)
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
    if imgui.button('Open in bokeh'):
        pickled_figure = pickle.dumps(figure)
        p = multiprocessing.Process(target=open_figure_in_bokeh, args=(pickled_figure,))
        p.start()
    imgui.same_line()
        fpath = pfd.save_file(title + '.png', state.figure_path).result()
        if len(fpath) > 0:
            state.figure_path = fpath
            figure.savefig(fpath)
    imgui_ds.imgui_fig.fig(figure=figure, title='')
