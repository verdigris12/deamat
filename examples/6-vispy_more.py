#!/usr/bin/env python3
from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui
from deamat import widgets as dw
from vispy import scene
from vispy.visuals.transforms import MatrixTransform
from vispy.visuals.filters import ShadingFilter


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        # box + transform
        self.box: scene.visuals.Box | None = None
        self._xf = MatrixTransform()
        self.box_pos = [0.0, 0.0, 0.0]
        self.box_rot = [0.0, 0.0, 0.0]      # deg about X,Y,Z
        self._last_pos = self.box_pos.copy()
        self._last_rot = self.box_rot.copy()

        # color (only re-upload when changed)
        self.box_color = (0.8, 0.3, 0.3, 1.0)
        self._last_color = self.box_color

        # camera (Turntable)
        self.view: scene.widgets.ViewBox | None = None
        self.cam = dict(distance=4.0, elevation=20.0, azimuth=30.0, fov=60.0, center=(0.0, 0.0, 0.0))
        self._last_cam = self.cam.copy()

        # optional spin
        self.spin = False
        self.spin_speed = 30.0  # deg/s about Y

        # shading mode (via ShadingFilter)
        self.shading_filter: ShadingFilter | None = None
        self.shading_modes = ['flat', 'smooth', None]
        self.shading_labels = ['Flat', 'Smooth', 'None']
        self.shading_idx = 0  # default to flat
        self._last_shading_idx = self.shading_idx

        # material properties
        self.shininess = 100.0
        self._last_shininess = self.shininess

    def init_main3d_canvas(self, canvas: scene.SceneCanvas, view: scene.widgets.ViewBox):
        self.view = view
        view.camera = scene.cameras.TurntableCamera(**self.cam)

        # BoxVisual is a compound visual; its drawable MeshVisual is at .mesh
        self.box = scene.visuals.Box(width=2.0, height=2.0, depth=2.0, color=self.box_color)

        # Attach ShadingFilter for proper lighting control
        self.shading_filter = ShadingFilter(
            shading=self.shading_modes[self.shading_idx],
            shininess=self.shininess
        )
        self.box.mesh.attach(self.shading_filter)

        self.box.transform = self._xf
        view.add(self.box)

    def update(self, dt: float) -> None:
        if self.box is None or self.view is None:
            return

        # animate
        if self.spin:
            self.box_rot[1] = (self.box_rot[1] + self.spin_speed * dt) % 360.0

        # transform (mutate the same MatrixTransform; no per-frame reassign)
        if self.box_rot != self._last_rot or self.box_pos != self._last_pos:
            self._xf.reset()
            self._xf.rotate(self.box_rot[0], (1, 0, 0))
            self._xf.rotate(self.box_rot[1], (0, 1, 0))
            self._xf.rotate(self.box_rot[2], (0, 0, 1))
            self._xf.translate(tuple(self.box_pos))
            self._last_rot = self.box_rot.copy()
            self._last_pos = self.box_pos.copy()

        # color (update the inner MeshVisual only when it changed)
        if self.box_color != self._last_color:
            try:
                self.box.mesh.color = self.box_color
            except Exception:
                self.box.mesh.set_data(color=self.box_color)
            self._last_color = self.box_color

        # shading mode and shininess via ShadingFilter
        if self.shading_filter is not None:
            if self.shading_idx != self._last_shading_idx:
                self.shading_filter.shading = self.shading_modes[self.shading_idx]
                self._last_shading_idx = self.shading_idx
            if self.shininess != self._last_shininess:
                self.shading_filter.shininess = self.shininess
                self._last_shininess = self.shininess

        # camera (write only what changed)
        cam = self.view.camera
        if self.cam != self._last_cam:
            if self.cam["distance"]  != self._last_cam["distance"]:  cam.distance  = self.cam["distance"]
            if self.cam["elevation"] != self._last_cam["elevation"]: cam.elevation = self.cam["elevation"]
            if self.cam["azimuth"]   != self._last_cam["azimuth"]:   cam.azimuth   = self.cam["azimuth"]
            if self.cam["fov"]       != self._last_cam["fov"]:       cam.fov       = self.cam["fov"]
            if self.cam["center"]    != self._last_cam["center"]:    cam.center    = self.cam["center"]
            self._last_cam = self.cam.copy()


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    # 3D view
    imgui.set_next_window_size(imgui.ImVec2(640, 480), cond=imgui.Cond_.once)
    imgui.begin("VisPy example")
    dw.vispy_canvas(gui, state, "main_3d", on_init=state.init_main3d_canvas)
    imgui.end()

    # Controls
    imgui.set_next_window_size(imgui.ImVec2(360, 330), cond=imgui.Cond_.once)
    imgui.begin("3D Controls")

    imgui.text("box transform")
    _, state.box_pos[0] = imgui.drag_float("pos X", state.box_pos[0], 0.01, -100.0, 100.0)
    _, state.box_pos[1] = imgui.drag_float("pos Y", state.box_pos[1], 0.01, -100.0, 100.0)
    _, state.box_pos[2] = imgui.drag_float("pos Z", state.box_pos[2], 0.01, -100.0, 100.0)
    _, state.box_rot[0] = imgui.slider_float("rot X (deg)", state.box_rot[0], -180.0, 180.0)
    _, state.box_rot[1] = imgui.slider_float("rot Y (deg)", state.box_rot[1], -180.0, 180.0)
    _, state.box_rot[2] = imgui.slider_float("rot Z (deg)", state.box_rot[2], -180.0, 180.0)
    _, state.spin = imgui.checkbox("spin", state.spin)
    _, state.spin_speed = imgui.drag_float("spin (deg/s)", state.spin_speed, 1.0, 0.0, 720.0)

    imgui.separator()
    imgui.text("Camera (Turntable)")
    _, state.cam["distance"]  = imgui.drag_float("distance", state.cam["distance"], 0.05, 0.1, 100.0)
    _, state.cam["elevation"] = imgui.slider_float("elevation", state.cam["elevation"], -89.9, 89.9)
    _, state.cam["azimuth"]   = imgui.slider_float("azimuth", state.cam["azimuth"], -180.0, 180.0)
    _, state.cam["fov"]       = imgui.slider_float("fov", state.cam["fov"], 15.0, 120.0)

    imgui.separator()
    imgui.text("Shading")
    changed, state.shading_idx = imgui.combo("Shading Mode", state.shading_idx, state.shading_labels)
    _, state.shininess = imgui.slider_float("Shininess", state.shininess, 1.0, 500.0)

    imgui.separator()
    imgui.text("box color")
    c0 = imgui.ImVec4(*state.box_color)
    changed, c = imgui.color_edit4("color", c0)
    if changed:
        # imgui-bundle may return ImVec4 or a list/tuple; support both
        try:
            state.box_color = (c.x, c.y, c.z, c.w)  # ImVec4
        except AttributeError:
            state.box_color = (c[0], c[1], c[2], c[3])  # list/tuple

    imgui.end()

    # apply to scene
    state.update(dt)


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()

