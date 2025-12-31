#!/usr/bin/env python3

"""
Example: Advanced pygfx 3D visualization with deamat.
Demonstrates animated transforms, camera control, material properties,
and color editing with pygfx.
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

        # Transform properties
        self.box_pos = [0.0, 0.0, 0.0]
        self.box_rot = [0.0, 0.0, 0.0]  # degrees about X, Y, Z
        self._last_pos = self.box_pos.copy()
        self._last_rot = self.box_rot.copy()

        # Color
        self.box_color = (0.8, 0.3, 0.3, 1.0)
        self._last_color = self.box_color

        # Animation
        self.spin = False
        self.spin_speed = 30.0  # deg/s about Y

        # Camera
        self.camera: gfx.PerspectiveCamera | None = None
        self.cam_distance = 5.0
        self.cam_elevation = 20.0
        self.cam_azimuth = 30.0

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
        directional = gfx.DirectionalLight(intensity=0.8)
        directional.local.position = (5, 10, 7)
        scene.add(directional)

        # Add background
        scene.add(gfx.Background.from_color((0.1, 0.1, 0.1, 1.0)))

        # Initial camera position
        self._update_camera()

    def _update_camera(self):
        """Update camera position based on spherical coordinates."""
        if self.camera is None:
            return

        # Convert spherical to Cartesian
        elev_rad = np.radians(self.cam_elevation)
        azim_rad = np.radians(self.cam_azimuth)

        x = self.cam_distance * np.cos(elev_rad) * np.sin(azim_rad)
        y = self.cam_distance * np.sin(elev_rad)
        z = self.cam_distance * np.cos(elev_rad) * np.cos(azim_rad)

        self.camera.local.position = (x, y, z)
        self.camera.look_at((0, 0, 0))

    def update(self, dt: float) -> None:
        """Update scene state each frame."""
        if self.mesh is None:
            return

        # Animate spin
        if self.spin:
            self.box_rot[1] = (self.box_rot[1] + self.spin_speed * dt) % 360.0

        # Update transform if changed
        if self.box_rot != self._last_rot or self.box_pos != self._last_pos:
            # Build rotation quaternion from Euler angles (XYZ order)
            angles = [np.radians(a) for a in self.box_rot]
            rotation = la.quat_from_euler(angles, order="XYZ")

            self.mesh.local.rotation = rotation
            self.mesh.local.position = tuple(self.box_pos)

            self._last_rot = self.box_rot.copy()
            self._last_pos = self.box_pos.copy()

        # Update color if changed
        if self.box_color != self._last_color:
            self.mesh.material.color = self.box_color
            self._last_color = self.box_color

        # Update camera
        self._update_camera()


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Callback executed each frame to build the UI."""

    # 3D view
    imgui.set_next_window_size(imgui.ImVec2(640, 480), cond=imgui.Cond_.once)
    imgui.begin("pygfx example")
    dw.pygfx_canvas(gui, state, "main_3d", on_init=state.init_scene)
    imgui.end()

    # Controls
    imgui.set_next_window_size(imgui.ImVec2(360, 400), cond=imgui.Cond_.once)
    imgui.begin("3D Controls")

    imgui.text("Box Transform")
    _, state.box_pos[0] = imgui.drag_float("pos X", state.box_pos[0], 0.01, -10.0, 10.0)
    _, state.box_pos[1] = imgui.drag_float("pos Y", state.box_pos[1], 0.01, -10.0, 10.0)
    _, state.box_pos[2] = imgui.drag_float("pos Z", state.box_pos[2], 0.01, -10.0, 10.0)
    _, state.box_rot[0] = imgui.slider_float("rot X (deg)", state.box_rot[0], -180.0, 180.0)
    _, state.box_rot[1] = imgui.slider_float("rot Y (deg)", state.box_rot[1], -180.0, 180.0)
    _, state.box_rot[2] = imgui.slider_float("rot Z (deg)", state.box_rot[2], -180.0, 180.0)
    _, state.spin = imgui.checkbox("Spin", state.spin)
    _, state.spin_speed = imgui.drag_float("Spin (deg/s)", state.spin_speed, 1.0, 0.0, 720.0)

    imgui.separator()
    imgui.text("Camera")
    _, state.cam_distance = imgui.drag_float("Distance", state.cam_distance, 0.05, 1.0, 50.0)
    _, state.cam_elevation = imgui.slider_float("Elevation", state.cam_elevation, -89.0, 89.0)
    _, state.cam_azimuth = imgui.slider_float("Azimuth", state.cam_azimuth, -180.0, 180.0)

    imgui.separator()
    imgui.text("Box Color")
    c0 = list(state.box_color)
    changed, c = imgui.color_edit4("Color", c0)
    if changed:
        state.box_color = tuple(c)

    imgui.end()

    # Update scene state
    state.update(dt)


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
