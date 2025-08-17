"""
Simple container class used by the GUI to store per‑application state.

An instance of :class:`GUIState` is passed to the ``GUI`` and made
available to your UI update function.  It holds information about the
window, matplotlib figures and the preferred plotting style, and provides
helpers to invalidate figures when state changes.
"""

import glfw
from matplotlib import pyplot as plt


class GUIState:
    def __init__(self) -> None:
        # window dimensions updated by GUI
        self.window = {
            'width': 0,
            'height': 0
        }
        self.figure_path = 'figures/'
        self.matplotlib_backend = 'Agg'
        self.config_path: str = ""
        self.input_path: str = ""
        self.config = None
        self.fig_width = 100
        self.figures: dict[str, dict] = {}
        self.plt_style = 'dark_background'
        self.show_test_window = False
        self.show_demo_window = False
        self.load_seq_ids = False
        self.statusline = 'Ready'

    def set_plt_style(self, style: str) -> None:
        self.plt_style = style
        plt.style.use(style)
        self.invalidate_all_figures()


    def add_figure(self, figname: str, figfunc, height: int = 250, title: str = "", width: int = 0) -> None:
        """Register a figure that will be rendered inside the GUI.

        The ``figfunc`` should be a callable that accepts the state and returns
        a :class:`matplotlib.figure.Figure`.
        """
        self.figures[figname] = {
            'figure': plt.figure(), # MPL figure object
            'dirty': True,          # Figure update requested
            'texture_dirty': True,  # Texture update necessary
            'make': figfunc,        # Figure update function
            'height': height,       # Figure height
            'width': width,         # Figure width
            'title': title,         # Figure title
        }

    def invalidate_figure(self, figname: str, width: int | None = None, height: int | None = None) -> None:
        if figname in self.figures:
            self.figures[figname]['dirty'] = True
            self.figures[figname]['texture_dirty'] = True
            if width is not None:
                self.figures[figname]['width'] = width
            if height is not None:
                self.figures[figname]['height'] = height

    def invalidate_all_figures(self) -> None:
        for figname in self.figures:
            self.invalidate_figure(figname)

    def config_loaded(self) -> bool:
        return self.config is not None

    def data_loaded(self) -> bool:
        return getattr(self, 'data', None) is not None

    def update_window(self, window: glfw._GLFWwindow) -> None:
        self.window['width'], self.window['height'] = glfw.get_window_size(window) 
