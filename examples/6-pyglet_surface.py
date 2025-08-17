#!/usr/bin/env python3
import math, time
from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat.widgets import pg_surface
from deamat import imgui
import pyglet.shapes as shapes

KEY = 'demo'


class State(GUIState):
    def __init__(self):
        super().__init__()
        self.circle = None
        self.t0 = time.time()


def ui(state: State, gui: dGUI, dt: float):
    # imgui.Col_.window_bg
    imgui.push_style_color(imgui.Col_.window_bg, (0.12, 0.05, 0.25, 1.0))
    imgui.begin("Pyglet-inside-ImGui")

    # 1. reserve a 220×160 rectangle and keep surf updated
    pg_surface(gui, 220, 160, KEY)
    surf = gui.get_surface(KEY)

    if state.circle is None:
        state.circle = shapes.Circle(110, 80, 25, color=(240, 70, 70),
                                     batch=surf.batch)

    t = time.time() - state.t0
    state.circle.x = 110 + 45 * math.cos(t * 2)
    state.circle.y =  80 + 45 * math.sin(t * 2)

    imgui.end()
    imgui.pop_style_color()


if __name__ == "__main__":
    gui = dGUI(State())
    gui.update = ui
    gui.main_window_fullscreen = True
    gui.run()

