"""Real pygfx event/camera/target tests; only the immediate-mode UI is simulated."""

import importlib
from types import SimpleNamespace

import numpy as np
import pygfx as gfx
import pytest
from rendercanvas.offscreen import RenderCanvas

canvas_module = importlib.import_module("deamat.widgets.pygfx_canvas")


class TextureRegistry:
    def __init__(self):
        self.textures = {}
        self.removed = []
        self.counter = 0

    def register_texture(self, texture):
        self.counter += 1
        self.textures[self.counter] = texture
        return self.counter

    def unregister_texture(self, texture_id):
        self.removed.append(texture_id)
        del self.textures[texture_id]


@pytest.fixture
def host():
    backend = TextureRegistry()
    cleanups = []
    requests = []
    gui = SimpleNamespace(
        canvas=RenderCanvas(size=(640, 480), pixel_ratio=2),
        gui_renderer=SimpleNamespace(backend=backend),
        _pygfx_scenes={}, scenes={}, add_cleanup=cleanups.append,
        get_pixel_ratio=lambda: gui.canvas.get_pixel_ratio(),
        add_input_handler=lambda callback, *types: None,
        remove_input_handler=lambda callback, *types: None,
        request_draw=lambda: requests.append(True),
    )
    yield gui, backend, requests
    for cleanup in reversed(cleanups):
        cleanup()
    gui.canvas.close()


@pytest.fixture
def ui(monkeypatch):
    imgui = canvas_module.imgui
    state = SimpleNamespace(
        x=60, y=70, hovered=False, down=set(), clicked=set(),
        width=120, height=100, images=[],
        io=SimpleNamespace(key_shift=False, key_ctrl=False, key_alt=False,
                           key_super=False, mouse_wheel=0, mouse_wheel_h=0,
                           want_text_input=False),
    )
    monkeypatch.setattr(imgui, "get_io", lambda: state.io)
    monkeypatch.setattr(imgui, "get_mouse_pos", lambda: SimpleNamespace(x=state.x, y=state.y))
    monkeypatch.setattr(imgui, "is_item_hovered", lambda: state.hovered)
    monkeypatch.setattr(imgui, "is_mouse_down", lambda button: button in state.down)
    monkeypatch.setattr(imgui, "is_mouse_clicked", lambda button: button in state.clicked)
    monkeypatch.setattr(imgui, "get_content_region_avail", lambda: SimpleNamespace(x=state.width, y=state.height))
    monkeypatch.setattr(imgui, "get_cursor_screen_pos", lambda: imgui.ImVec2(10, 20))
    monkeypatch.setattr(imgui, "invisible_button", lambda *args: False)
    monkeypatch.setattr(imgui, "get_window_draw_list", lambda: SimpleNamespace(add_image=lambda *args: state.images.append(args)))
    return state


def make_view(host, camera=None):
    gui, _, _ = host
    view = canvas_module.PygfxCanvas(gui, "view", (120, 100), 2, camera)
    gui._pygfx_scenes["view"] = view
    gui.scenes["view"] = view.scene
    return view


def test_single_initial_and_resize_render_preserves_camera_and_renderer(host, ui, monkeypatch):
    gui, backend, _ = host
    camera = gfx.OrthographicCamera(6, 4)
    renders = []
    original = gfx.WgpuRenderer.render

    def render(renderer, scene, active_camera, **kwargs):
        renders.append((renderer, len(scene.children), active_camera))
        return original(renderer, scene, active_camera, **kwargs)

    monkeypatch.setattr(gfx.WgpuRenderer, "render", render)
    view = canvas_module.pygfx_canvas(
        gui, None, "view", camera=camera, continuous=False,
        on_init=lambda scene, camera: scene.add(gfx.AmbientLight()) and None,
    )
    assert len(renders) == 1
    assert renders[0][1] == 1
    renderer = view.renderer
    assert renderer.logical_size == (120, 100)
    assert view._texture.size == (240, 200, 1)
    extents = (camera.width, camera.height, camera.fov)
    ui.width = 180
    canvas_module.pygfx_canvas(gui, None, "view", camera=camera, continuous=False)
    assert len(renders) == 2
    assert view.renderer is renderer
    assert view._texture.size == (360, 200, 1)
    assert (camera.width, camera.height, camera.fov) == extents
    assert len(backend.textures) == 1
    canvas_module.pygfx_canvas(gui, None, "view", camera=camera, continuous=False)
    assert len(renders) == 2  # static idle frame does not render


def test_detached_move_keeps_texture_and_ratio_change_preserves_scene(host, ui, monkeypatch):
    gui, backend, _ = host
    ratio = [1]
    origin = [10, 20]
    monkeypatch.setattr(gui, "get_pixel_ratio", lambda: ratio[0])
    monkeypatch.setattr(canvas_module.imgui, "get_cursor_screen_pos",
                        lambda: canvas_module.imgui.ImVec2(*origin))
    view = canvas_module.pygfx_canvas(gui, None, "view", continuous=False)
    renderer, scene, camera, texture = view.renderer, view.scene, view.camera, view._texture
    origin[:] = [800, 400]
    canvas_module.pygfx_canvas(gui, None, "view", continuous=False)
    assert view._texture is texture
    assert not backend.removed
    ratio[0] = 2
    canvas_module.pygfx_canvas(gui, None, "view", continuous=False)
    assert view._texture.size == (240, 200, 1)
    assert (view.renderer, view.scene, view.camera) == (renderer, scene, camera)
    assert len(backend.removed) == 1


def test_focus_loss_releases_captured_input(host, ui):
    view = make_view(host)
    view.controller = gfx.PanZoomController(damping=0)
    view._image_pos = (800, 400)
    left = canvas_module.imgui.MouseButton_.left
    ui.x, ui.y, ui.hovered, ui.down, ui.clicked = 850, 450, True, {left}, {left}
    canvas_module._handle_imgui_events(view)
    view._native_event({"event_type": "focus_out"})
    assert not view._buttons
    view.controller.tick()
    position = view.camera.local.position.copy()
    view._native_event({"event_type": "pointer_up", "button": 1, "x": 1200, "y": 450})
    view.controller.tick()
    np.testing.assert_allclose(view.camera.local.position, position)


def test_controller_filters_and_detach_ownership(host):
    camera = gfx.PerspectiveCamera(63, 1.2)
    controller = gfx.OrbitController()
    controller.add_camera(camera, include_state={"position"})
    view = make_view(host, camera)
    view.controller = controller
    old_zoom = camera.zoom
    controller.quickzoom(1)
    assert camera.zoom == old_zoom  # add_camera was not called again without filters
    view.controller = None
    assert camera in controller.cameras  # borrowed registration remains owned by caller
    owned = gfx.OrbitController()
    view.controller = owned
    assert camera in owned.cameras
    view.controller = None
    assert camera not in owned.cameras
    view._resize((200, 80), 1)
    assert camera.fov == 63


def test_wheel_up_zooms_in_and_tick_precedes_render(host, ui, monkeypatch):
    gui, _, _ = host
    camera = gfx.OrthographicCamera(6, 4)
    controller = gfx.PanZoomController(camera, damping=0)
    view = canvas_module.pygfx_canvas(gui, None, "view", camera=camera, controller=controller, continuous=False)
    old_width = camera.width
    widths_at_render = []
    original = view.renderer.render

    def render(*args, **kwargs):
        widths_at_render.append(camera.width)
        return original(*args, **kwargs)

    monkeypatch.setattr(view.renderer, "render", render)
    ui.hovered = True
    ui.io.mouse_wheel = 1
    canvas_module.pygfx_canvas(gui, None, "view", camera=camera, controller=controller, continuous=False)
    assert camera.width < old_width
    assert widths_at_render == [camera.width]


def test_drag_releases_outside_and_applies_final_position(host, ui):
    view = make_view(host, gfx.OrthographicCamera(6, 4))
    view.controller = gfx.PanZoomController(damping=0)
    view._image_pos = (10, 20)
    left = canvas_module.imgui.MouseButton_.left
    ui.hovered, ui.down, ui.clicked = True, {left}, {left}
    canvas_module._handle_imgui_events(view)
    view.controller.tick()
    ui.hovered, ui.clicked = False, set()
    ui.x = 240
    canvas_module._handle_imgui_events(view)
    view.controller.tick()
    intermediate = view.camera.local.position.copy()
    ui.x = 300
    ui.down.clear()
    view._native_event({"event_type": "pointer_up", "button": 1,
                        "x": ui.x, "y": ui.y, "modifiers": ()})
    view.controller.tick()
    final = view.camera.local.position.copy()
    assert not np.allclose(intermediate, final)
    assert not view._buttons
    ui.x = 400
    canvas_module._handle_imgui_events(view)
    view.controller.tick()
    np.testing.assert_allclose(view.camera.local.position, final)


def test_renderer_picks_scene_click_hover_and_pointer_capture(host):
    view = make_view(host, gfx.OrthographicCamera(4, 4))
    mesh = gfx.Mesh(gfx.plane_geometry(2, 2), gfx.MeshBasicMaterial(color="red", pick_write=True))
    view.scene.add(mesh)
    view.renderer.render(view.scene, view.camera)
    events = []
    mesh.add_event_handler(lambda event: events.append(event.type), "pointer_enter", "click", "pointer_up")
    args = dict(x=60, y=50, button=1, buttons=(), modifiers=(), pointer_id=0)
    view._dispatch("pointer_move", **args)
    view._dispatch("pointer_down", **args)
    view._dispatch("pointer_up", **args)
    assert "pointer_enter" in events
    assert "click" in events
    mesh.set_pointer_capture(0, view.renderer)
    view._buttons.add(1)
    view._native_event({"event_type": "pointer_up", "button": 1, "x": 400, "y": 400, "modifiers": ()})
    assert events.count("pointer_up") == 2
    assert not view._buttons
    # A subsequent out-of-bounds release no longer reaches the mesh.
    view._dispatch("pointer_up", **{**args, "x": 400, "y": 400})
    assert events.count("pointer_up") == 2


def test_keyboard_release_survives_focus_change_and_close_is_idempotent(host, ui):
    gui, backend, _ = host
    view = make_view(host)
    gui._pygfx_keyboard_view = view
    events = []
    view.renderer.add_event_handler(lambda event: events.append((event.type, event.key)), "key_down", "key_up")
    view._native_event({"event_type": "key_down", "key": "w", "modifiers": ()})
    gui._pygfx_keyboard_view = None
    view._native_event({"event_type": "key_up", "key": "w", "modifiers": ()})
    assert events == [("key_down", "w"), ("key_up", "w")]
    view.close()
    view.close()
    assert not backend.textures
    assert len(backend.removed) == 1
    assert not gui._pygfx_scenes
    assert not gui.scenes
    assert view.renderer is None


def test_init_can_select_camera_before_first_render(host, ui):
    gui, _, _ = host
    selected = gfx.OrthographicCamera(9, 7)
    view = canvas_module.pygfx_canvas(gui, None, "view", on_init=lambda scene, camera: selected)
    assert view.camera is selected
    assert (selected.width, selected.height) == (9, 7)
