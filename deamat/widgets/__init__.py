"""
deamat.widgets
==============

Bundle of immediate-mode widgets that integrate external renderers
"""

from .figure import figure
from .pygfx_canvas import pygfx_canvas

__all__ = ["figure", "pygfx_canvas"]
