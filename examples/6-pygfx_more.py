#!/usr/bin/env python3

"""
Example: pygfx 3D visualization with orbit controls.

Demonstrates:
- OrbitController for mouse-based camera navigation
- Event forwarding from imgui to pygfx
- Material color and light intensity controls
"""

import pygfx as gfx
import pylinalg as la
import numpy as np

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui
from deamat import widgets as dw


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()

        # Mesh reference
        self.mesh: gfx.Mesh | None = None

        # Rotation (Euler angles in degrees)
        self.box_rot = [0.0, 0.0, 0.0]
        self._last_rot = self.box_rot.copy()
        
        # Auto-rotation
        self.auto_rotate = False
        self.rotate_speed = 45.0  # degrees per second

        # Color
        self.box_color = (0.8, 0.3, 0.3, 1.0)
        self._last_color = self.box_color

        # Lighting
        self.light: gfx.DirectionalLight | None = None
        self.light_intensity = 0.8
        self._last_intensity = self.light_intensity

        self.camera = gfx.PerspectiveCamera(45, 4 / 3)
        self.controller = gfx.OrbitController(self.camera, target=(0, 0, 0))
        self.controller.controls["mouse1"] = ("rotate", "drag", (0.004, 0.004))
        self.controller.controls["mouse2"] = ("pan", "drag", (0.8, 0.8))

    def init_scene(self, scene: gfx.Scene, camera: gfx.PerspectiveCamera):
        """Initialize the 3D scene with a box."""
        self.camera = camera

        # Create box mesh
        geometry = gfx.box_geometry(2.0, 2.0, 2.0)
        material = gfx.MeshPhongMaterial(color=self.box_color)
        self.mesh = gfx.Mesh(geometry, material)
        scene.add(self.mesh)

        # Add lighting
        scene.add(gfx.AmbientLight(intensity=0.3))
        self.light = gfx.DirectionalLight(intensity=self.light_intensity)
        self.light.local.position = (5, 10, 7)
        scene.add(self.light)

        # Add background
        scene.add(gfx.Background.from_color((0.1, 0.1, 0.1, 1.0)))


        # Position camera
        camera.local.position = (5, 3, 5)
        camera.show_pos((0, 0, 0))
        self.update(0.0)

    def update(self, dt: float) -> None:
        """Update scene state each frame."""
        if self.mesh is None:
            return

        # Auto-rotate
        if self.auto_rotate:
            self.box_rot[1] = (self.box_rot[1] + self.rotate_speed * dt) % 360.0

        # Update rotation if changed
        if self.box_rot != self._last_rot:
            angles = [np.radians(a) for a in self.box_rot]
            rotation = la.quat_from_euler(angles, order="XYZ")
            self.mesh.local.rotation = rotation
            self._last_rot = self.box_rot.copy()

        # Update color if changed
        if self.box_color != self._last_color:
            self.mesh.material.color = self.box_color
            self._last_color = self.box_color

        if self.light is not None and self.light_intensity != self._last_intensity:
            self.light.intensity = self.light_intensity
            self._last_intensity = self.light_intensity


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Apply visible controls before updating and rendering the scene."""
    imgui.set_next_window_size(imgui.ImVec2(300, 250), cond=imgui.Cond_.once)
    visible, _ = imgui.begin("Controls")
    if visible:
        imgui.text("Mouse Controls:")
        imgui.bullet_text("Left drag: Orbit")
        imgui.bullet_text("Right drag: Pan")
        imgui.bullet_text("Scroll: Zoom")
        imgui.separator()
        imgui.text("Box Rotation")
        _, state.box_rot[0] = imgui.slider_float("X (deg)", state.box_rot[0], -180.0, 180.0)
        _, state.box_rot[1] = imgui.slider_float("Y (deg)", state.box_rot[1], -180.0, 180.0)
        _, state.box_rot[2] = imgui.slider_float("Z (deg)", state.box_rot[2], -180.0, 180.0)
        _, state.auto_rotate = imgui.checkbox("Auto-rotate", state.auto_rotate)
        if state.auto_rotate:
            _, state.rotate_speed = imgui.slider_float("Speed (deg/s)", state.rotate_speed, 10.0, 180.0)
        imgui.separator()
        imgui.text("Appearance")
        changed_color, color = imgui.color_edit4("Box Color", list(state.box_color))
        if changed_color:
            state.box_color = tuple(color)
        _, state.light_intensity = imgui.slider_float("Light Intensity", state.light_intensity, 0.0, 2.0)
    imgui.end()

    imgui.set_next_window_size(imgui.ImVec2(640, 480), cond=imgui.Cond_.once)
    visible, _ = imgui.begin("pygfx Orbit Controls")
    if visible:
        state.update(dt)
        dw.pygfx_canvas(
            gui, state, "main_3d", on_init=state.init_scene,
            camera=state.camera, controller=state.controller,
        )
    imgui.end()


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
