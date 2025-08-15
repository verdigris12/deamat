from __future__ import annotations
from dataclasses import dataclass

import pyglet
from imgui_bundle import imgui


@dataclass
class _Surface:
    """Holds one independent Batch plus its top-left offset in window coords."""
    batch: pyglet.graphics.Batch
    ox: float = 0.0          # updated every frame by pg_surface()
    oy: float = 0.0
    w:  int  = 0
    h:  int  = 0
    key: str = ''


def pg_surface(gui, width: int, height: int, key: str) -> None:
    """
    Reserve a WxH rectangle in ImGui and make sure a pyglet Batch exists for it.
    All objects added to surf.batch can be positioned in *local* coords
    (0, 0 = rectangle’s top-left).
    """
    # create (once) or fetch (every frame)
    surf = gui._pg_surfaces.get(key)
    if surf is None:
        surf = _Surface(pyglet.graphics.Batch(), 0, 0, width, height, key)
        gui._register_pg_surface(surf, key)

    win_w, win_h = gui.window.get_size()

    # current ImGui cursor → window coordinates (top-left origin)
    tl_x, tl_y = imgui.get_cursor_screen_pos()
    surf.ox = tl_x
    surf.oy = win_h - tl_y - height   # flip Y because OpenGL origin is bottom-left
    surf.w, surf.h = width, height

    imgui.dummy(imgui.ImVec2(width, height))        # reserve space in the layout
