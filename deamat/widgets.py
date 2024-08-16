import matplotlib
import imgui
import imgui_datascience as imgui_ds
from imgui_bundle import portable_file_dialogs as pfd
import pickle
import multiprocessing
import matplotlib.pyplot as plt


def open_figure_in_pyplot(pickled_figure):
    matplotlib.use('TkAgg')
    fig = pickle.loads(pickled_figure)
    new_fig = plt.figure()
    new_ax = new_fig.add_subplot(111)
    for ax in fig.get_axes():
        for line in ax.get_lines():
            new_ax.plot(line.get_xdata(), line.get_ydata(), label=line.get_label())
    new_ax.legend()
    plt.draw()
    plt.show()


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
    if imgui.button('Save figure'):
        fpath = pfd.save_file(title + '.png', state.figure_path).result()
        if len(fpath) > 0:
            state.figure_path = fpath
            figure.savefig(fpath)
    imgui_ds.imgui_fig.fig(figure=figure, title='')
