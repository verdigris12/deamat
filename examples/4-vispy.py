#!/usr/bin/env python3

"""
Example: update a value in the UI using a button.  Demonstrates how to use
imgui widgets imported from the deamat package.
"""

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui
from deamat import widgets as dw



class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        self.value = 0

    # canvas = gui.canvases["main_3d"]
    # view = canvas._default_view           # turntable camera already set
    # mesh = scene.visuals.Sphere(radius=1.0, color=(0.8, 0.3, 0.3, 1))
    # view.add(mesh)
    #

def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Callback executed each frame to build the UI."""
    imgui.set_next_window_size(imgui.ImVec2(300, 100))
    imgui.begin('VisPy example')
    dw.vispy_canvas(gui, state, "main_3d")
    imgui.end()


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
