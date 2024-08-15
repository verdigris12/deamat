from matplotlib import pyplot as plt
import pyglet


class GUIState():
    def __init__(self):
        self.batch = None
        self.window = None
        self.figure_path = 'figures/'
        self.matplotlib_backend = 'Agg'
        self.config_path = ""
        self.input_path = ""
        self.config = None
        self.fig_width = 100
        self.data = None
        self.residuals = {}
        self.results = {}
        self.figures = {}
        self.plt_style = 'dark_background'
        self.show_test_window = False
        self.show_demo_window = False
        self.load_seq_ids = False
        self.statusline = 'Ready'
        self.batch = pyglet.graphics.Batch()

    def set_plt_style(self, style):
        self.plt_style = style
        plt.style.use(style)
        self.invalidate_all_figures()

    def add_figure(self, figname, figfunc, height=250, title="", width=0):
        self.figures[figname] = {
            'figure': plt.figure(),
            'make': figfunc,
            'height': height,
            'title': title,
            'width': width
        }

    def invalidate_figure(self, figname, width=None, height=None):
        if figname in self.figures:
            self.figures[figname]['dirty'] = True
            if width:
                self.figures[figname]['width'] = width
            if height:
                self.figures[figname]['height'] = height

    def invalidate_all_figures(self):
        for f in self.figures.values():
            f['dirty'] = True

    def config_loaded(self):
        return self.config is not None

    def data_loaded(self):
        return self.data is not None

    def update_window(self, window):
        self.window['width'], self.window['height'] = window.get_size()

    # Produce a function that invalidates given
    # figures when called
    def invalidator(self, *args):
        def inv():
            for figname in args:
                self.invalidate_figure(figname)
        return inv
