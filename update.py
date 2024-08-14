#!/usr/bin/env python3

import imgui
import pyglet
from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState


class State(GUIState):
    def __init__(self):
        GUIState.__init__(self)
        self.value = 1
        self.main_window_fullscreen = False
        self.main_window_name = "Example"


def update_ui(state):
    if imgui.button('Increase value'):
        state.value = state.value + 1
    imgui.same_line()
    imgui.text(f'{state.value}')


def update_gl(state, gui, dt):
    wwidth = gui.window.width
    wheight = gui.window.height
    label = pyglet.text.Label('Hello, world',
                              font_name='Times New Roman',
                              font_size=36,
                              color=(255, 255, 255, 255),
                              x=wwidth // 2, y=wheight // 2,
                              anchor_x='center', anchor_y='center',
                              batch=state.batch
                              )
    label.draw()


def update(state, gui, dt):
    update_ui(state)
    update_gl(state, gui, dt)


def main():
    gui = dGUI(State())
    gui.update = update
    gui.run()


if __name__ == "__main__":
    main()
