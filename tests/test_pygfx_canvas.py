"""Real pygfx event/camera/target tests; only the immediate-mode UI is simulated."""

import importlib
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
gfx = pytest.importorskip("pygfx")
pytest.importorskip("wgpu")
RenderCanvas = pytest.importorskip("rendercanvas.offscreen").RenderCanvas

canvas_module = importlib.import_module("deamat.widgets.pygfx_canvas")


class Image:
    def __init__(self, pixels):
        self.ref = object()
        self.closed = False
        self.uploads = 0
        self.update(pixels)

    def update(self, pixels):
        self.pixels = np.array(pixels, copy=True)
        self.uploads += 1

    def close(self):
        self.closed = True


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(canvas_module.glfw, "make_context_current", lambda window: None)
    images = []
    def create_image(pixels):
        image = Image(pixels)
        images.append(image)
        return image
    cleanups = []
    requests = []
    gui = SimpleNamespace(
        canvas=RenderCanvas(size=(640, 480), pixel_ratio=2),
        create_image=create_image, make_current=lambda: None,
        _pygfx_scenes={}, scenes={}, add_cleanup=cleanups.append,
        get_pixel_ratio=lambda: gui.canvas.get_pixel_ratio(),
        add_input_handler=lambda callback, *types: None,
        remove_input_handler=lambda callback, *types: None,
        request_draw=lambda: requests.append(True),
    )
    yield gui, images, requests
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
    gui, images, _ = host
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
    assert len(images) == 1
    assert images[0].pixels.shape == (200, 360, 4)
    assert images[0].uploads == 2
    canvas_module.pygfx_canvas(gui, None, "view", camera=camera, continuous=False)
    assert len(renders) == 2  # static idle frame does not render
    assert images[0].uploads == 2

def test_detached_move_keeps_texture_and_ratio_change_preserves_scene(host, ui, monkeypatch):
    gui, images, _ = host
    ratio = [1]
    origin = [10, 20]
    monkeypatch.setattr(gui, "get_pixel_ratio", lambda: ratio[0])
    monkeypatch.setattr(canvas_module.imgui, "get_cursor_screen_pos",
                        lambda: canvas_module.imgui.ImVec2(*origin))
    view = canvas_module.pygfx_canvas(gui, None, "view", continuous=False)
    renderer, scene, camera, image = view.renderer, view.scene, view.camera, view._image
    origin[:] = [800, 400]
    canvas_module.pygfx_canvas(gui, None, "view", continuous=False)
    assert view._image is image
    assert image.uploads == 1
    ratio[0] = 2
    canvas_module.pygfx_canvas(gui, None, "view", continuous=False)
    assert view._texture.size == (240, 200, 1)
    assert (view.renderer, view.scene, view.camera) == (renderer, scene, camera)
    assert image.uploads == 2


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


@pytest.mark.parametrize("release_before_press", [True, False])
def test_queued_click_releases_once(host, ui, release_before_press):
    view = make_view(host, gfx.OrthographicCamera(4, 4))
    mesh = gfx.Mesh(gfx.plane_geometry(4, 4), gfx.MeshBasicMaterial(pick_write=True))
    view.scene.add(mesh)
    view.renderer.render(view.scene, view.camera)
    events = []
    mesh.add_event_handler(lambda event: events.append(event.type), "pointer_down", "pointer_up")
    view._image_pos = (10, 20)
    left = canvas_module.imgui.MouseButton_.left
    release = {"event_type": "pointer_up", "button": 1, "x": ui.x, "y": ui.y}
    if release_before_press:
        view._native_event(release)
    ui.hovered, ui.down, ui.clicked = True, {left}, {left}
    canvas_module._handle_imgui_events(view)
    if not release_before_press:
        view._native_event(release)
    ui.down.clear()
    ui.clicked.clear()
    canvas_module._handle_imgui_events(view)
    assert events == ["pointer_down", "pointer_up"]
    assert not view._buttons


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
    gui, images, _ = host
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
    assert not images
    assert not gui._pygfx_scenes
    assert not gui.scenes
    assert view.renderer is None


def test_init_can_select_camera_before_first_render(host, ui):
    gui, _, _ = host
    selected = gfx.OrthographicCamera(9, 7)
    view = canvas_module.pygfx_canvas(gui, None, "view", on_init=lambda scene, camera: selected)
    assert view.camera is selected
    assert (selected.width, selected.height) == (9, 7)


def _native_context_worker():
    """Exercise the first adapter probe and real GL textures in a fresh process."""
    import ctypes
    from deamat import GUI, GUIState
    import glfw
    from OpenGL import GL
    import wgpu
    from pygfx.renderers.wgpu.engine.shared import Shared

    gui = GUI(GUIState(), width=320, height=240)
    patch = pytest.MonkeyPatch()
    try:
        gui.make_current()
        context_address = ctypes.cast(glfw.get_current_context(), ctypes.c_void_p).value
        assert context_address
        assert Shared._instance is None
        original_probe = wgpu.gpu.request_adapter_sync
        probes = []

        def probe(*args, **kwargs):
            assert not glfw.get_current_context()
            probes.append(True)
            return original_probe(*args, **kwargs)

        def failing_probe(*args, **kwargs):
            assert not glfw.get_current_context()
            raise RuntimeError("probe failure")

        patch.setattr(wgpu.gpu, "request_adapter_sync", failing_probe)
        with pytest.raises(RuntimeError, match="probe failure"):
            canvas_module.PygfxCanvas(gui, "failure", (120, 100), 1)
        assert ctypes.cast(glfw.get_current_context(), ctypes.c_void_p).value == context_address
        assert GL.glGetString(GL.GL_VERSION)
        patch.setattr(wgpu.gpu, "request_adapter_sync", probe)
        state = ui.__wrapped__(patch)
        original_create_image = gui.create_image

        def create_image(pixels):
            assert ctypes.cast(glfw.get_current_context(), ctypes.c_void_p).value == context_address
            return original_create_image(pixels)

        patch.setattr(gui, "create_image", create_image)
        camera = gfx.OrthographicCamera(4, 4)
        def init(scene, camera):
            scene.add(gfx.Mesh(gfx.plane_geometry(2, 2), gfx.MeshBasicMaterial(color="red", pick_write=True)))

        view = canvas_module.pygfx_canvas(gui, None, "native", camera=camera, on_init=init)
        assert probes

        def assert_texture():
            assert ctypes.cast(glfw.get_current_context(), ctypes.c_void_p).value == context_address
            assert GL.glIsTexture(view._image._texture)
            GL.glBindTexture(GL.GL_TEXTURE_2D, view._image._texture)
            pixels = np.frombuffer(GL.glGetTexImage(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE),
                                   dtype=np.uint8).reshape(view._image.size[1], view._image.size[0], 4)
            center = pixels[pixels.shape[0] // 2, pixels.shape[1] // 2]
            assert center[0] > 200 and center[1] < 30 and center[2] < 30

        assert_texture()
        view._dispatch("pointer_move", x=60, y=50, button=0, buttons=(), modifiers=(), pointer_id=0)
        assert ctypes.cast(glfw.get_current_context(), ctypes.c_void_p).value == context_address
        view._resize((160, 100), 1)
        assert ctypes.cast(glfw.get_current_context(), ctypes.c_void_p).value == context_address
        state.width = 160
        canvas_module.pygfx_canvas(gui, None, "native", camera=camera)
        assert_texture()
        view.close()
        assert ctypes.cast(glfw.get_current_context(), ctypes.c_void_p).value == context_address
        image = gui.create_image(np.full((2, 2, 4), 255, dtype=np.uint8))
        assert GL.glIsTexture(image._texture)
        image.close()
    finally:
        patch.undo()
        gui.close()


@pytest.mark.skipif(os.environ.get("DEAMAT_PYGFX_NATIVE") != "1", reason="explicit isolated-display native test")
def test_native_gl_context_ownership():
    subprocess.run(
        [sys.executable, "-c",
         "import runpy, sys; runpy.run_path(sys.argv[1])['_native_context_worker']()", str(Path(__file__).resolve())],
        check=True, timeout=120,
    )
