#!/usr/bin/env python3

"""
Example: update a value in the UI using a button.  Demonstrates how to use
imgui widgets imported from the deamat package.
"""

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui
from deamat import widgets as dw

from vispy import scene
import vispy

class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        self.value = 0

    def init_main3d_canvas(self, canvas: scene.SceneCanvas, view: vispy.scene.ViewBox):
        mesh = scene.visuals.Sphere(radius=1.0, color=(0.8, 0.3, 0.3, 1))
        view.add(mesh)


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Callback executed each frame to build the UI."""
    imgui.set_next_window_size(imgui.ImVec2(300, 100), cond=imgui.Cond_.once)
    imgui.begin('VisPy example')
    dw.vispy_canvas(gui, state, "main_3d", on_init=state.init_main3d_canvas)
    imgui.end()


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
