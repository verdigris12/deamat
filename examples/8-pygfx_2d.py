#!/usr/bin/env python3

"""
Example: 2D pygfx visualization with configurable Lissajous figure.

Demonstrates:
- 2D rendering with OrthographicCamera
- Dynamic geometry updates
- Line rendering with anti-aliasing
- Real-time parameter control
"""

import pygfx as gfx
import numpy as np

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui
from deamat import widgets as dw


def generate_lissajous(a: float, b: float, delta: float, num_points: int = 1000) -> np.ndarray:
    """Generate Lissajous curve points.
    
    Parametric equations:
        x = sin(a*t + delta)
        y = sin(b*t)
    
    Parameters
    ----------
    a : float
        Frequency for x-axis
    b : float
        Frequency for y-axis  
    delta : float
        Phase shift in radians
    num_points : int
        Number of points to generate
        
    Returns
    -------
    np.ndarray
        Array of shape (num_points, 3) with xyz coordinates (z=0)
    """
    t = np.linspace(0, 2 * np.pi, num_points)
    x = np.sin(a * t + delta)
    y = np.sin(b * t)
    z = np.zeros_like(t)
    return np.column_stack([x, y, z]).astype(np.float32)


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        
        # Lissajous parameters
        self.freq_a = 3.0
        self.freq_b = 2.0
        self.phase_delta = np.pi / 2
        self.num_points = 1000
        
        # Animation
        self.animate = False
        self.anim_speed = 1.0
        
        # Appearance
        self.line_color = (0.2, 0.8, 0.4, 1.0)
        self.line_thickness = 3.0
        self.show_axes = True
        
        # References
        self.line: gfx.Line | None = None
        self.geometry: gfx.Geometry | None = None
        self.camera: gfx.OrthographicCamera | None = None
        self._needs_update = True

    def init_scene(self, scene: gfx.Scene, camera: gfx.PerspectiveCamera):
        """Initialize the 2D scene."""
        # Replace with orthographic camera for 2D
        self.camera = gfx.OrthographicCamera(2.2, 2.2, maintain_aspect=True)
        
        # Create initial geometry
        positions = generate_lissajous(self.freq_a, self.freq_b, self.phase_delta, self.num_points)
        self.geometry = gfx.Geometry(positions=positions)
        
        # Create line with anti-aliasing
        material = gfx.LineMaterial(
            thickness=self.line_thickness,
            color=self.line_color,
            aa=True,
        )
        self.line = gfx.Line(self.geometry, material)
        scene.add(self.line)
        
        # Add coordinate axes
        self._add_axes(scene)
        
        # Background
        scene.add(gfx.Background.from_color((0.05, 0.05, 0.1, 1.0)))

    def _add_axes(self, scene: gfx.Scene):
        """Add X and Y axis lines."""
        # X axis (horizontal)
        x_positions = np.array([[-1.1, 0, 0], [1.1, 0, 0]], dtype=np.float32)
        x_geom = gfx.Geometry(positions=x_positions)
        x_mat = gfx.LineMaterial(thickness=1.0, color=(0.4, 0.4, 0.4, 1.0))
        self.x_axis = gfx.Line(x_geom, x_mat)
        scene.add(self.x_axis)
        
        # Y axis (vertical)
        y_positions = np.array([[0, -1.1, 0], [0, 1.1, 0]], dtype=np.float32)
        y_geom = gfx.Geometry(positions=y_positions)
        y_mat = gfx.LineMaterial(thickness=1.0, color=(0.4, 0.4, 0.4, 1.0))
        self.y_axis = gfx.Line(y_geom, y_mat)
        scene.add(self.y_axis)

    def update(self, dt: float) -> None:
        """Update the curve each frame."""
        if self.line is None or self.geometry is None:
            return
        
        # Animate phase
        if self.animate:
            self.phase_delta += self.anim_speed * dt
            self._needs_update = True
        
        # Update geometry if needed
        if self._needs_update:
            positions = generate_lissajous(
                self.freq_a, self.freq_b, self.phase_delta, self.num_points
            )
            self.geometry.positions.data[:] = positions
            self.geometry.positions.update_range()
            self._needs_update = False
        
        # Update line appearance
        self.line.material.color = self.line_color
        self.line.material.thickness = self.line_thickness
        
        # Toggle axes visibility
        if hasattr(self, 'x_axis'):
            self.x_axis.visible = self.show_axes
            self.y_axis.visible = self.show_axes


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Callback executed each frame to build the UI."""
    
    # 2D canvas
    imgui.set_next_window_size(imgui.ImVec2(500, 500), cond=imgui.Cond_.once)
    imgui.begin("Lissajous Figure")
    
    # Use custom camera for 2D rendering
    def on_init_2d(scene, camera):
        state.init_scene(scene, camera)
    
    dw.pygfx_canvas(gui, state, "lissajous_2d", on_init=on_init_2d)
    imgui.end()
    
    # Controls
    imgui.set_next_window_size(imgui.ImVec2(300, 400), cond=imgui.Cond_.once)
    imgui.begin("Lissajous Controls")
    
    imgui.text("Curve Parameters")
    imgui.text("x = sin(a*t + delta)")
    imgui.text("y = sin(b*t)")
    imgui.separator()
    
    # Frequency controls with common ratios
    changed_a, state.freq_a = imgui.slider_float("Freq A", state.freq_a, 1.0, 10.0)
    changed_b, state.freq_b = imgui.slider_float("Freq B", state.freq_b, 1.0, 10.0)
    
    # Quick ratio buttons
    imgui.text("Quick ratios (A:B):")
    if imgui.button("1:1"):
        state.freq_a, state.freq_b = 1.0, 1.0
        state._needs_update = True
    imgui.same_line()
    if imgui.button("2:1"):
        state.freq_a, state.freq_b = 2.0, 1.0
        state._needs_update = True
    imgui.same_line()
    if imgui.button("3:2"):
        state.freq_a, state.freq_b = 3.0, 2.0
        state._needs_update = True
    imgui.same_line()
    if imgui.button("5:4"):
        state.freq_a, state.freq_b = 5.0, 4.0
        state._needs_update = True
    
    if imgui.button("3:4"):
        state.freq_a, state.freq_b = 3.0, 4.0
        state._needs_update = True
    imgui.same_line()
    if imgui.button("5:6"):
        state.freq_a, state.freq_b = 5.0, 6.0
        state._needs_update = True
    imgui.same_line()
    if imgui.button("7:8"):
        state.freq_a, state.freq_b = 7.0, 8.0
        state._needs_update = True
    
    changed_delta, new_delta = imgui.slider_float(
        "Phase (delta)", state.phase_delta, 0.0, 2 * np.pi, "%.2f rad"
    )
    if changed_delta:
        state.phase_delta = new_delta
        state._needs_update = True
    
    if changed_a or changed_b:
        state._needs_update = True
    
    imgui.separator()
    imgui.text("Animation")
    _, state.animate = imgui.checkbox("Animate phase", state.animate)
    _, state.anim_speed = imgui.slider_float("Speed", state.anim_speed, 0.1, 5.0)
    
    imgui.separator()
    imgui.text("Appearance")
    _, state.line_thickness = imgui.slider_float("Thickness", state.line_thickness, 1.0, 10.0)
    _, state.show_axes = imgui.checkbox("Show axes", state.show_axes)
    
    c0 = list(state.line_color)
    changed_color, c = imgui.color_edit4("Line Color", c0)
    if changed_color:
        state.line_color = tuple(c)
    
    imgui.end()
    
    # Update state
    state.update(dt)
    
    # Override camera in the pygfx canvas registry to use orthographic
    if "lissajous_2d" in gui._pygfx_scenes and state.camera is not None:
        entry = gui._pygfx_scenes["lissajous_2d"]
        if entry["camera"] != state.camera:
            entry["camera"] = state.camera


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
