import matplotlib
import imgui
import imgui_datascience as imgui_ds
from imgui_bundle import portable_file_dialogs as pfd


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
    if imgui.button('Plot ' + title):
        state.invalidate_figure(figname)
    # imgui.same_line()
    # if imgui.button('Open PyPlot'):
    #     p = mp.Process(target=plot_fig, args=(figure,))
    #     p.start()

    imgui.same_line()
    if imgui.button('Save figure'):
        fpath = pfd.save_file(title + '.png', state.figure_path).result()
        if len(fpath) > 0:
            state.figure_path = fpath
            figure.savefig(fpath)
    # imgui.same_line()
    # imgui.push_id(f'figh_{figname}')
    # imgui.push_item_width(100)
    # _, state.figures[figname]['height'] = imgui.input_int(
    #     'Figure height, px',
    #     state.figures[figname]['height']
    # )
    # imgui.pop_id()
    imgui_ds.imgui_fig.fig(figure=figure, title='')
