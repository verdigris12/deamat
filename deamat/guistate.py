"""
Simple container class used by the GUI to store per‑application state.

An instance of :class:`GUIState` is passed to the ``GUI`` and made
available to your UI update function.  It holds information about the
window, matplotlib figures and the preferred plotting style, and provides
helpers to invalidate figures when state changes.
"""

from matplotlib import pyplot as plt
import pyglet


class GUIState:
    def __init__(self) -> None:
        # Pyglet batch for custom drawing
        self.batch = pyglet.graphics.Batch()
        # window dimensions updated by GUI
        self.window: dict | None = None  # type: ignore
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
            'figure': plt.figure(),
            'make': figfunc,
            'height': height,
            'title': title,
            'width': width
        }

    def invalidate_figure(self, figname: str, width: int | None = None, height: int | None = None) -> None:
        if figname in self.figures:
            self.figures[figname]['dirty'] = True
            if width is not None:
                self.figures[figname]['width'] = width
            if height is not None:
                self.figures[figname]['height'] = height

    def invalidate_all_figures(self) -> None:
        for f in self.figures.values():
            f['dirty'] = True

    def config_loaded(self) -> bool:
        return self.config is not None

    def data_loaded(self) -> bool:
        return getattr(self, 'data', None) is not None

    def update_window(self, window: pyglet.window.Window) -> None:
        if self.window is not None:
            self.window['width'], self.window['height'] = window.get_size()

    def invalidator(self, *args: str):
        """Return a callable that invalidates the given figures when called."""
        def inv() -> None:
            for figname in args:
                self.invalidate_figure(figname)
        return inv