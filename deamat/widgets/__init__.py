"""
deamat.widgets
==============

Bundle of immediate-mode widgets that integrate external renderers
"""

from .figure import im_plot_figure as figure # matplotlib helper
from .vispy_canvas import vispy_canvas

__all__ = ["figure", "vispy_canvas"]
