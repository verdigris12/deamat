"""
Simple container class used by the GUI to store per‑application state.

An instance of :class:`GUIState` is passed to the ``GUI`` and made
available to your UI update function.  It holds information about the
window, matplotlib figures and the preferred plotting style, and provides
helpers to invalidate figures when state changes.
"""

from __future__ import annotations

import queue
from typing import Any

from matplotlib import pyplot as plt

from .sync import SyncContext


class GUIState:
    """Base class for application state.
    
    Subclass this to hold your application-specific state. The GUI will
    pass an instance of your state class to the update callback each frame.
    
    Thread Safety
    -------------
    When mutating state from async coroutines, use the :meth:`sync` context
    manager to ensure changes are applied on the main thread::
    
        async def fetch_data(gui):
            result = await some_api()
            async with gui.state.sync() as state:
                state.data = result
    
    Deep Copy Customization
    -----------------------
    The sync context uses ``copy.deepcopy`` to create a snapshot of the state.
    If your state contains objects that cannot be deep copied (e.g., file handles,
    locks, GUI resources), override ``__deepcopy__`` in your subclass::
    
        def __deepcopy__(self, memo):
            cls = self.__class__
            result = cls.__new__(cls)
            memo[id(self)] = result
            for k, v in self.__dict__.items():
                if k in ('_sync_queue', 'some_uncopyable_resource'):
                    setattr(result, k, v)  # shallow copy reference
                else:
                    setattr(result, k, copy.deepcopy(v, memo))
            return result
    """
    
    def __init__(self) -> None:
        # Sync queue for thread-safe state updates from async coroutines
        self._sync_queue: queue.Queue = queue.Queue()
        
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
    
    def sync(self, deep: bool = False) -> SyncContext:
        """Create an async context manager for thread-safe state mutation.
        
        Use this when mutating state from async coroutines to ensure changes
        are applied on the main thread.
        
        Parameters
        ----------
        deep : bool, default False
            If True, perform recursive merge of nested objects.
            If False, only merge top-level attributes (faster).
        
        Returns
        -------
        SyncContext
            An async context manager that yields a copy of this state.
        
        Example
        -------
        ::
        
            async def my_coroutine(gui):
                result = await some_async_api()
                async with gui.state.sync() as state:
                    state.data = result
                    state.status = "loaded"
        """
        return SyncContext(self, deep=deep)

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

    def update_window(self, canvas: Any) -> None:
        """Update window dimensions from the canvas.
        
        Parameters
        ----------
        canvas : RenderCanvas
            The wgpu render canvas.
        """
        try:
            size = canvas.get_logical_size()
            self.window['width'] = size[0]
            self.window['height'] = size[1]
        except (AttributeError, TypeError):
            # Fallback for different canvas implementations
            pass 
