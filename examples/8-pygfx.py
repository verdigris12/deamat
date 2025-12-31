#!/usr/bin/env python3

"""
Example: Basic pygfx 3D visualization embedded in an ImGui window.
Demonstrates the pygfx_canvas widget with a simple sphere mesh.
"""

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui
from deamat import widgets as dw

import pygfx as gfx


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        self.value = 0

    def init_main3d_scene(self, scene: gfx.Scene, viewport: gfx.Viewport):
        """Initialize the 3D scene with a sphere mesh."""
        # Create a sphere geometry and material (three.js-style API)
        geometry = gfx.sphere_geometry(radius=1.0, width_segments=32, height_segments=16)
        material = gfx.MeshPhongMaterial(color=(0.8, 0.3, 0.3, 1.0))
        mesh = gfx.Mesh(geometry, material)
        scene.add(mesh)


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Callback executed each frame to build the UI."""
    imgui.set_next_window_size(imgui.ImVec2(400, 300), cond=imgui.Cond_.once)
    imgui.begin("pygfx example")
    dw.pygfx_canvas(gui, state, "main_3d", on_init=state.init_main3d_scene)
    imgui.end()


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
