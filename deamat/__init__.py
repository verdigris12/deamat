"""
The :mod:`deamat` package provides a minimal wrapper around imgui and
matplotlib to ease the construction of immediate‑mode graphical interfaces.

The top‑level namespace re‑exports the core classes and functions used by most
applications:

* :class:`deamat.gui.GUI` – the main application window and event loop.
* :class:`deamat.guistate.GUIState` – a simple container for user state and
  figure definitions.
* :mod:`imgui` – imported from imgui_bundle and re‑exported to ensure a
  consistent implementation throughout your application.
"""

from imgui_bundle import imgui as _imgui

from .gui import GUI
from .guistate import GUIState
from . import widgets

# Re-export imgui so that examples and users can rely on the same implementation
imgui = _imgui

# Define the public API of the package
__all__ = [
    "GUI",
    "GUIState",
    "widgets",
    "imgui"
]
