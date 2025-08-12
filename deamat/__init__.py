"""
The :mod:`deamat` package provides a minimal wrapper around imgui and
matplotlib to ease the construction of immediate‑mode graphical interfaces.

The top‑level namespace re‑exports the core classes and functions used by most
applications:

* :class:`deamat.gui.GUI` – the main application window and event loop.
* :class:`deamat.guistate.GUIState` – a simple container for user state and
  figure definitions.
* :func:`deamat.widgets.im_plot_figure` – embed a matplotlib figure in an
  imgui window.
* :mod:`imgui` – imported from imgui_bundle and re‑exported to ensure a
  consistent implementation throughout your application.
"""

from imgui_bundle import imgui as _imgui

from .gui import GUI
from .guistate import GUIState
from .widgets import im_plot_figure

# Re-export imgui so that examples and users can rely on the same implementation
imgui = _imgui

# Define the public API of the package
__all__ = [
    "GUI",
    "GUIState",
    "im_plot_figure",
    "imgui",
]