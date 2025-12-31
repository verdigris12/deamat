"""
deamat.widgets
==============

Bundle of immediate-mode widgets that integrate external renderers
"""

from .figure import im_plot_figure as figure  # matplotlib helper
from .pygfx_canvas import pygfx_canvas

__all__ = ["figure", "pygfx_canvas"]
