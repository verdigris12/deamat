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


def update_lissajous(positions, samples, a, b, delta):
    """Fill the retained float32 vertex array without per-frame curve buffers."""
    np.multiply(samples, a, out=positions[:, 0])
    np.add(positions[:, 0], delta, out=positions[:, 0])
    np.sin(positions[:, 0], out=positions[:, 0])
    np.multiply(samples, b, out=positions[:, 1])
    np.sin(positions[:, 1], out=positions[:, 1])


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
        self.camera = gfx.OrthographicCamera(2.2, 2.2, maintain_aspect=True)
        self.controller = gfx.PanZoomController(self.camera)
        self.samples = np.linspace(0, 2 * np.pi, self.num_points, dtype=np.float32)
        self._needs_update = True
        self._last_appearance = None

    def init_scene(self, scene: gfx.Scene, camera: gfx.OrthographicCamera):
        """Initialize the 2D scene with the explicit orthographic camera."""
        positions = np.zeros((self.num_points, 3), dtype=np.float32)
        update_lissajous(positions, self.samples, self.freq_a, self.freq_b, self.phase_delta)
        self.geometry = gfx.Geometry(positions=positions)
        self._needs_update = False
        
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
        self._last_appearance = (self.line_color, self.line_thickness, self.show_axes)
        self.x_axis.visible = self.y_axis.visible = self.show_axes

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
            update_lissajous(
                self.geometry.positions.data, self.samples,
                self.freq_a, self.freq_b, self.phase_delta,
            )
            self.geometry.positions.update_range()
            self._needs_update = False
        
        appearance = (self.line_color, self.line_thickness, self.show_axes)
        previous = self._last_appearance
        if self.line_color != previous[0]:
            self.line.material.color = self.line_color
        if self.line_thickness != previous[1]:
            self.line.material.thickness = self.line_thickness
        if self.show_axes != previous[2]:
            self.x_axis.visible = self.y_axis.visible = self.show_axes
        self._last_appearance = appearance


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    """Apply controls and animation before rendering visible windows."""
    imgui.set_next_window_size(imgui.ImVec2(300, 400), cond=imgui.Cond_.once)
    visible, _ = imgui.begin("Lissajous Controls")
    if visible:
        imgui.text("Curve Parameters")
        imgui.text("x = sin(a*t + delta)")
        imgui.text("y = sin(b*t)")
        imgui.separator()
        changed_a, state.freq_a = imgui.slider_float("Freq A", state.freq_a, 1.0, 10.0)
        changed_b, state.freq_b = imgui.slider_float("Freq B", state.freq_b, 1.0, 10.0)
        imgui.text("Quick ratios (A:B):")
        for index, (a, b) in enumerate(((1, 1), (2, 1), (3, 2), (5, 4), (3, 4), (5, 6), (7, 8))):
            if index % 4:
                imgui.same_line()
            if imgui.button(f"{a}:{b}"):
                state.freq_a, state.freq_b = float(a), float(b)
                state._needs_update = True
        changed_delta, state.phase_delta = imgui.slider_float(
            "Phase (delta)", state.phase_delta, 0.0, 2 * np.pi, "%.2f rad"
        )
        state._needs_update |= changed_a or changed_b or changed_delta
        imgui.separator()
        imgui.text("Animation")
        _, state.animate = imgui.checkbox("Animate phase", state.animate)
        _, state.anim_speed = imgui.slider_float("Speed", state.anim_speed, 0.1, 5.0)
        imgui.separator()
        imgui.text("Appearance")
        _, state.line_thickness = imgui.slider_float("Thickness", state.line_thickness, 1.0, 10.0)
        _, state.show_axes = imgui.checkbox("Show axes", state.show_axes)
        changed_color, color = imgui.color_edit4("Line Color", list(state.line_color))
        if changed_color:
            state.line_color = tuple(color)
    imgui.end()

    imgui.set_next_window_size(imgui.ImVec2(500, 500), cond=imgui.Cond_.once)
    visible, _ = imgui.begin("Lissajous Figure")
    if visible:
        state.update(dt)
        dw.pygfx_canvas(
            gui, state, "lissajous_2d", on_init=state.init_scene,
            camera=state.camera, controller=state.controller,
        )
    imgui.end()


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
