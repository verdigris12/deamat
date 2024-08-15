#!/usr/bin/env python3

import imgui
import math
from pyglet import shapes
from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState


class State(GUIState):
    def __init__(self):
        GUIState.__init__(self)
        batch = self.batch
        self.speed = 5
        self.main_window_fullscreen = False
        self.main_window_name = "Example"
        self.circle = shapes.Circle(0, 0, 5, color=(50, 225, 30), batch=batch)
        self.t = 0

    def update(self, dt):
        self.t = self.t + dt
        wcenter = (
            self.window['width'] // 2,
            self.window['height'] // 2
        )
        self.circle.x = wcenter[0] + 20 * math.cos(self.speed * self.t)
        self.circle.y = wcenter[1] + 20 * math.sin(self.speed * self.t)


def update_ui(state):
    if imgui.button('Increase speed'):
        state.speed = state.speed + 1
    imgui.same_line()
    imgui.text(f'{state.speed}')


def update_gui(state, gui, dt):
    state.update(dt)
    update_ui(state)


def main():
    gui = dGUI(State())
    gui.update = update_gui
    gui.run()


if __name__ == "__main__":
    main()
