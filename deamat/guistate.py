"""
Simple container class used by the GUI to store per‑application state.

An instance of :class:`GUIState` is passed to the ``GUI`` and made
available to your UI update function.  It holds information about the
window, matplotlib figures and the preferred plotting style, and provides
helpers to invalidate figures when state changes.
"""

from __future__ import annotations

from typing import Any

from matplotlib import pyplot as plt


class GUIState:
    """Base class for application state.
    
    Subclass this to hold your application-specific state. The GUI will
    pass an instance of your state class to the update callback each frame.
    
    State belongs to the GUI thread. Background work must dispatch explicit
    mutations with ``gui.post(callback, *args)``; no state is copied or merged.
    """
    
    def __init__(self) -> None:
        # State and figure resources are owned by the GUI thread.
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
        
        Raises
        ------
        TypeError
            If ``figfunc`` is not callable.
        ValueError
            If ``height`` or ``width`` is negative.
        """
        if not callable(figfunc):
            raise TypeError(f"figfunc must be callable, got {type(figfunc).__name__}")
        if height < 0:
            raise ValueError(f"height must be non-negative, got {height}")
        if width < 0:
            raise ValueError(f"width must be non-negative, got {width}")
        
        if figname in self.figures:
            self.remove_figure(figname)
        self.figures[figname] = {
            'figure': None,         # Created lazily by the figure widget
            'dirty': True,          # Figure update requested
            'texture_dirty': True,  # Texture update necessary
            'make': figfunc,        # Figure update function
            'height': height,       # Figure height
            'width': width,         # Figure width
            'title': title,         # Figure title
        }

    def remove_figure(self, figname: str) -> None:
        """Remove a figure and dispose its retained view and Matplotlib object."""
        entry = self.figures.pop(figname)
        try:
            dispose = entry.get('_dispose_view')
            if dispose is not None:
                dispose()
        finally:
            if entry['figure'] is not None:
                plt.close(entry['figure'])

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

    def update_window(self, canvas: Any) -> None:
        """Update window dimensions from the canvas.
        
        Parameters
        ----------
        canvas : RenderCanvas
            The wgpu render canvas.
        """
        size = canvas.get_logical_size()
        self.window['width'] = size[0]
        self.window['height'] = size[1]
