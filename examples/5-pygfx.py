#!/usr/bin/env python3

"""
Example: Basic pygfx 3D visualization with deamat.
Demonstrates how to embed a pygfx scene into an imgui window.
"""

import pygfx as gfx

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui
from deamat import widgets as dw


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        self.value = 0

    def init_scene(self, scene: gfx.Scene, camera: gfx.PerspectiveCamera):
        """Initialize the 3D scene with a sphere."""
        # Create a sphere mesh
        geometry = gfx.sphere_geometry(radius=1.0)
        material = gfx.MeshPhongMaterial(color=(0.8, 0.3, 0.3, 1.0))
        mesh = gfx.Mesh(geometry, material)
        scene.add(mesh)

        # Add lighting
        scene.add(gfx.AmbientLight(intensity=0.4))
        directional = gfx.DirectionalLight(intensity=0.8)
        directional.local.position = (3, 4, 5)
        scene.add(directional)

        # Position camera
        camera.local.z = 4


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Callback executed each frame to build the UI."""
    imgui.set_next_window_size(imgui.ImVec2(400, 300), cond=imgui.Cond_.once)
    imgui.begin('pygfx example')
    dw.pygfx_canvas(gui, state, "main_3d", on_init=state.init_scene)
    imgui.end()


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
