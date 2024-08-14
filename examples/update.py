#!/usr/bin/env python3

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
import imgui


class State(GUIState):
    def __init__(self):
        GUIState.__init__(self)
        self.value = 0


def update_ui(state, gui, dt):
    if imgui.button('Increase value'):
        state.value = state.value + 1
    imgui.same_line()
    imgui.text(f'{state.value}')


def main():
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
