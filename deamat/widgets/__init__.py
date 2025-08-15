"""
deamat.widgets
==============

Bundle of immediate-mode widgets that integrate external renderers
(matplotlib, pyglet…) into an ImGui layout.
"""

from .figure import im_plot_figure as figure # matplotlib helper
from .pg_surface import pg_surface        # pyglet surface

__all__ = ["figure", "pg_surface"]
