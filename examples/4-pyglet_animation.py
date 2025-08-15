#!/usr/bin/env python3

"""
Example: animate a small circle using pyglet and update its speed from the UI.
This demonstrates how to mix raw pyglet drawing with deamat's immediate mode UI.
"""

import math
import pyglet as pg

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui
import multiprocessing as mp


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        self.speed = 5
        self.main_window_fullscreen = False
        self.main_window_name = "Example"
        self.t = 0.0

        # Initialize GL elements in gl_init, where GL context is guaranteed
        self.circle = None

    def gl_init(self, window: pg.window.Window, batch: pg.graphics.Batch):
        self.circle = pg.shapes.Circle(0, 0, 5, color=(50, 225, 30), batch=batch)

    def update(self, dt: float) -> None:
        self.t += dt
        # compute the centre of the window
        wcenter = (
            self.window['width'] // 2,
            self.window['height'] // 2
        )
        self.circle.x = wcenter[0] + 20 * math.cos(self.speed * self.t)
        self.circle.y = wcenter[1] + 20 * math.sin(self.speed * self.t)

def update(state: State, gui: dGUI, dt: float) -> None:
    state.update(dt)

    if imgui.button('Increase speed'):
        state.speed += 1
    imgui.same_line()
    imgui.text(f'{state.speed}')

def main() -> None:
    gui = dGUI(State())
    gui.update = update
    gui.run()

if __name__ == "__main__":
    main()
