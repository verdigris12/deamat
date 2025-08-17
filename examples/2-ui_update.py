#!/usr/bin/env python3

"""
Example: update a value in the UI using a button.  Demonstrates how to use
imgui widgets imported from the deamat package.
"""

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        self.value = 0


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Callback executed each frame to build the UI."""
    imgui.set_next_window_size(imgui.ImVec2(300, 100))
    imgui.begin('UI example')
    if imgui.button('Increase value'):
        state.value += 1
    imgui.same_line()
    imgui.text(f'{state.value}')
    imgui.end()


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
