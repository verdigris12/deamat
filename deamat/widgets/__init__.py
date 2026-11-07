"""
deamat.widgets
==============

Bundle of immediate-mode widgets that integrate external renderers
"""

from .figure import figure
from .file_dialog import DialogResult, FileDialog
from .pygfx_canvas import pygfx_canvas

__all__ = ["DialogResult", "FileDialog", "figure", "pygfx_canvas"]
