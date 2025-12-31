#!/usr/bin/env python3

"""
Example: Advanced pygfx 3D visualization with interactive controls.
Demonstrates transform controls, camera settings, color picker, animation,
and material properties using the pygfx_canvas widget.
"""

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui
from deamat import widgets as dw

import pygfx as gfx
import pylinalg as la
import numpy as np


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        
        # Box mesh reference
        self.box: gfx.Mesh | None = None
        
        # Transform controls
        self.box_pos = [0.0, 0.0, 0.0]
        self.box_rot = [0.0, 0.0, 0.0]  # degrees about X, Y, Z
        self._last_pos = self.box_pos.copy()
        self._last_rot = self.box_rot.copy()
        
        # Color (RGBA)
        self.box_color = (0.8, 0.3, 0.3, 1.0)
        self._last_color = self.box_color
        
        # Animation
        self.spin = False
        self.spin_speed = 30.0  # deg/s about Y
        
        # Material properties
        self.shininess = 100.0
        self._last_shininess = self.shininess
        
        # Flat shading toggle
        self.flat_shading = False
        self._last_flat_shading = self.flat_shading

    def init_main3d_scene(self, scene: gfx.Scene, viewport: gfx.Viewport):
        """Initialize the 3D scene with a box mesh."""
        # Create box geometry and phong material
        geometry = gfx.box_geometry(2.0, 2.0, 2.0)
        material = gfx.MeshPhongMaterial(
            color=self.box_color,
            shininess=self.shininess,
            flat_shading=self.flat_shading,
        )
        self.box = gfx.Mesh(geometry, material)
        scene.add(self.box)

    def update(self, dt: float) -> None:
        """Update scene state each frame."""
        if self.box is None:
            return
        
        # Animate spin
        if self.spin:
            self.box_rot[1] = (self.box_rot[1] + self.spin_speed * dt) % 360.0
        
        # Update transform if changed
        if self.box_rot != self._last_rot or self.box_pos != self._last_pos:
            # Build rotation quaternion from euler angles
            rot_x = la.quat_from_axis_angle((1, 0, 0), np.radians(self.box_rot[0]))
            rot_y = la.quat_from_axis_angle((0, 1, 0), np.radians(self.box_rot[1]))
            rot_z = la.quat_from_axis_angle((0, 0, 1), np.radians(self.box_rot[2]))
            rotation = la.quat_mul(la.quat_mul(rot_x, rot_y), rot_z)
            
            self.box.local.position = tuple(self.box_pos)
            self.box.local.rotation = rotation
            
            self._last_rot = self.box_rot.copy()
            self._last_pos = self.box_pos.copy()
        
        # Update color if changed
        if self.box_color != self._last_color:
            self.box.material.color = self.box_color
            self._last_color = self.box_color
        
        # Update material properties if changed
        if self.shininess != self._last_shininess:
            self.box.material.shininess = self.shininess
            self._last_shininess = self.shininess
        
        if self.flat_shading != self._last_flat_shading:
            self.box.material.flat_shading = self.flat_shading
            self._last_flat_shading = self.flat_shading


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Callback executed each frame to build the UI."""
    
    # 3D view window
    imgui.set_next_window_size(imgui.ImVec2(640, 480), cond=imgui.Cond_.once)
    imgui.begin("pygfx example")
    dw.pygfx_canvas(gui, state, "main_3d", on_init=state.init_main3d_scene)
    imgui.end()
    
    # Controls window
    imgui.set_next_window_size(imgui.ImVec2(360, 400), cond=imgui.Cond_.once)
    imgui.begin("3D Controls")
    
    # Transform section
    imgui.text("Box Transform")
    _, state.box_pos[0] = imgui.drag_float("pos X", state.box_pos[0], 0.01, -10.0, 10.0)
    _, state.box_pos[1] = imgui.drag_float("pos Y", state.box_pos[1], 0.01, -10.0, 10.0)
    _, state.box_pos[2] = imgui.drag_float("pos Z", state.box_pos[2], 0.01, -10.0, 10.0)
    _, state.box_rot[0] = imgui.slider_float("rot X (deg)", state.box_rot[0], -180.0, 180.0)
    _, state.box_rot[1] = imgui.slider_float("rot Y (deg)", state.box_rot[1], -180.0, 180.0)
    _, state.box_rot[2] = imgui.slider_float("rot Z (deg)", state.box_rot[2], -180.0, 180.0)
    
    imgui.separator()
    
    # Animation section
    imgui.text("Animation")
    _, state.spin = imgui.checkbox("Spin", state.spin)
    _, state.spin_speed = imgui.drag_float("Spin speed (deg/s)", state.spin_speed, 1.0, 0.0, 720.0)
    
    imgui.separator()
    
    # Material section
    imgui.text("Material")
    _, state.shininess = imgui.slider_float("Shininess", state.shininess, 1.0, 500.0)
    _, state.flat_shading = imgui.checkbox("Flat shading", state.flat_shading)
    
    imgui.separator()
    
    # Color section
    imgui.text("Box Color")
    c0 = imgui.ImVec4(*state.box_color)
    changed, c = imgui.color_edit4("Color", c0)
    if changed:
        try:
            state.box_color = (c.x, c.y, c.z, c.w)
        except AttributeError:
            state.box_color = (c[0], c[1], c[2], c[3])
    
    imgui.separator()
    
    # Instructions
    imgui.text_wrapped(
        "Drag with left mouse to orbit.\n"
        "Drag with right mouse to pan.\n"
        "Scroll to zoom."
    )
    
    imgui.end()
    
    # Update scene state
    state.update(dt)


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
