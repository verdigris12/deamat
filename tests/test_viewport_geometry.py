"""Detached viewport geometry and framebuffer scaling regressions."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deamat import GUI, GUIState, imgui
from deamat._glfw_viewports import _window
import glfw


def test_reused_native_address_retires_old_resources_before_install(monkeypatch):
    from deamat import _glfw_viewports as backend

    old = SimpleNamespace(window=21, id_=1)
    stable = SimpleNamespace(window=22, id_=2)
    new = SimpleNamespace(window=None, id_=3)
    context = SimpleNamespace(frame_count=100, viewports=[
        SimpleNamespace(draw_data_p=SimpleNamespace(owner_viewport=old),
                        last_frame_active=99, window=SimpleNamespace(active=False, hidden=False)),
        SimpleNamespace(draw_data_p=SimpleNamespace(owner_viewport=stable),
                        last_frame_active=100, window=SimpleNamespace(active=True, hidden=False)),
    ])
    host = backend.GlfwViewportHost.__new__(backend.GlfwViewportHost)
    host.main = 1
    host.callbacks = {1: object(), 21: object(), 22: object(), 23: object()}
    host.geometry = {1: (0, 0, 640, 480), 21: (10, 20, 100, 100),
                     22: (30, 40, 100, 100), 23: (50, 60, 100, 100)}
    host._drag_request = None
    old_surface, stable_surface, stale_surface = Mock(), Mock(), Mock()
    host.surfaces = {21: old_surface, 22: stable_surface, 23: stale_surface}
    monkeypatch.setattr(backend.imgui, "get_current_context", lambda: context)
    monkeypatch.setattr(backend, "_window", lambda viewport: viewport.window)
    monkeypatch.setattr(backend, "_address", lambda window: window)

    def update():
        # The already-deleted window is retired first; the old callback stays
        # referenced while GLFW destroys its window.
        assert 23 not in host.callbacks and 21 in host.callbacks
        old_surface.unconfigure.assert_called_once()
        old_surface._release.assert_called_once()
        old.window = None
        new.window = 21  # allocator reuses the address in the same update
        stable.id_ = 99  # in-place viewport ID reassignment is not destruction
        context.viewports.append(SimpleNamespace(
            draw_data_p=SimpleNamespace(owner_viewport=new)))

    monkeypatch.setattr(backend.imgui, "update_platform_windows", update)
    host._update_platform_windows()
    assert 21 not in host.callbacks and 21 not in host.surfaces
    assert 21 not in host.geometry and 23 not in host.geometry
    assert 22 in host.geometry
    assert 22 in host.callbacks and host.surfaces[22] is stable_surface
    old_surface.unconfigure.assert_called_once()
    stale_surface.unconfigure.assert_called_once()
    stale_surface._release.assert_called_once()
    stable_surface._release.assert_not_called()
    stable_surface.unconfigure.assert_not_called()


@pytest.mark.parametrize(
    "last_active,active,hidden,retire",
    [(99, True, False, False), (98, True, False, True),
     (100, True, True, True), (100, False, False, True)],
)
def test_surface_released_before_imminent_platform_destruction(
        monkeypatch, last_active, active, hidden, retire):
    from deamat import _glfw_viewports as backend

    viewport = SimpleNamespace(window=21)
    internal = SimpleNamespace(draw_data_p=SimpleNamespace(owner_viewport=viewport),
                               last_frame_active=last_active,
                               window=SimpleNamespace(active=active, hidden=hidden))
    context = SimpleNamespace(frame_count=100, viewports=[internal])
    surface = Mock()
    host = backend.GlfwViewportHost.__new__(backend.GlfwViewportHost)
    host.main = 1
    host.callbacks = {1: object(), 21: object()}
    host.geometry = {1: (0, 0, 640, 480), 21: (10, 20, 100, 100)}
    host._drag_request = None
    host.surfaces = {21: surface}
    monkeypatch.setattr(backend.imgui, "get_current_context", lambda: context)
    monkeypatch.setattr(backend, "_window", lambda v: v.window)
    monkeypatch.setattr(backend, "_address", lambda window: window)

    def update():
        assert 21 in host.callbacks
        assert surface.unconfigure.call_count == int(retire)
        assert surface._release.call_count == int(retire)
        if retire:
            viewport.window = None

    monkeypatch.setattr(backend.imgui, "update_platform_windows", update)
    host._update_platform_windows()
    assert (21 in host.callbacks) is not retire
    assert (21 in host.surfaces) is not retire
    assert (21 in host.geometry) is not retire


def test_shutdown_releases_surface_before_destroying_platform_window(monkeypatch):
    from deamat import _glfw_viewports as backend

    surface = Mock()
    host = backend.GlfwViewportHost.__new__(backend.GlfwViewportHost)
    host.main = 1
    host.enabled = True
    host.callbacks = {1: (1, []), 21: object()}
    host.geometry = {1: (0, 0, 640, 480), 21: (10, 20, 100, 100)}
    host._drag_request = None
    host.surfaces = {21: surface}
    monkeypatch.setattr(backend, "_address", lambda window: window)

    def destroy():
        surface.unconfigure.assert_called_once()
        surface._release.assert_called_once()
        assert 21 in host.callbacks

    monkeypatch.setattr(backend.imgui, "destroy_platform_windows", destroy)
    monkeypatch.setattr(backend.imgui.backends, "glfw_shutdown", lambda: None)
    host.close()
    assert not host.callbacks and not host.surfaces
    assert not host.geometry


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"),
    reason="requires a Linux GLFW display",
)
def test_detached_resize_converges_to_native_geometry_and_scale(monkeypatch):
    gui = GUI(GUIState(), width=640, height=480, update_mode="ondemand", viewports=True)
    try:
        host = gui._viewport_host
        if not host.enabled:
            pytest.skip("native detached viewports unavailable")
        imgui.get_io().set_ini_filename("")
        state = {"viewport": None, "scales": [], "requested_size": None}
        draw = host._draw

        def capture(draw_data, view):
            viewport = state["viewport"]
            if viewport and draw_data == viewport.draw_data:
                window = _window(viewport)
                state["scales"].append((
                    tuple(glfw.get_window_size(window)),
                    tuple(glfw.get_framebuffer_size(window)),
                    (draw_data.framebuffer_scale.x, draw_data.framebuffer_scale.y),
                ))
            draw(draw_data, view)

        monkeypatch.setattr(host, "_draw", capture)

        def update(_state, _gui, _dt):
            imgui.set_next_window_pos((1050, 150), imgui.Cond_.once)
            imgui.set_next_window_size((450, 600), imgui.Cond_.once)
            if state["requested_size"]:
                imgui.set_next_window_size(state["requested_size"], imgui.Cond_.always)
                state["requested_size"] = None
            imgui.begin("Native geometry regression")
            state["viewport"] = imgui.get_window_viewport()
            imgui.text("Detached window")
            imgui.end()

        gui.update = update
        gui.gui_renderer.set_gui(gui._draw_imgui)
        gui.canvas.request_draw(gui._render_frame)

        def frame():
            glfw.poll_events()
            gui.canvas.force_draw()

        for _ in range(6):
            frame()
        viewport = state["viewport"]
        assert viewport.id_ != imgui.get_main_viewport().id_
        window = _window(viewport)
        assert window
        old_position = glfw.get_window_pos(window)
        glfw.set_window_pos(window, old_position[0] + 80, old_position[1] + 60)
        for _ in range(6):
            frame()
        native_position = glfw.get_window_pos(window)
        assert native_position != old_position
        assert (state["viewport"].pos.x, state["viewport"].pos.y) == pytest.approx(native_position)
        glfw.set_window_size(window, 720, 460)
        assert glfw.get_window_pos(window) == native_position
        for _ in range(6):
            frame()
        viewport = state["viewport"]
        width, height = glfw.get_window_size(window)
        assert (viewport.size.x, viewport.size.y) == pytest.approx((width, height))
        assert (viewport.draw_data.display_size.x, viewport.draw_data.display_size.y) == pytest.approx((width, height))
        assert state["scales"]
        state["requested_size"] = (510, 370)
        for _ in range(6):
            frame()
        assert glfw.get_window_size(window) == pytest.approx((510, 370))
        assert (state["viewport"].size.x, state["viewport"].size.y) == pytest.approx((510, 370))
        for logical, physical, scale in state["scales"]:
            assert scale == pytest.approx((physical[0] / logical[0], physical[1] / logical[1]))
        assert not gui.errors
    finally:
        gui.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"),
    reason="requires a Linux GLFW display",
)
def test_main_surface_tracks_native_framebuffer_before_layout(monkeypatch):
    gui = GUI(GUIState(), width=640, height=480, update_mode="ondemand")
    try:
        host = gui._viewport_host
        if host is None:
            pytest.skip("requires native GLFW host")
        imgui.get_io().set_ini_filename("")
        gui.update = lambda *_args: None
        gui.gui_renderer.set_gui(gui._draw_imgui)
        gui.canvas.request_draw(gui._render_frame)
        glfw.poll_events()
        gui.canvas.force_draw()

        canvas = gui.canvas
        native_size = glfw.get_framebuffer_size(canvas._window)
        assert native_size[0] > 100 and native_size[1] > 100
        # Model a pending native framebuffer event: rendercanvas has stale
        # dimensions when it sets the context size before calling our draw.
        canvas._size_info.set_physical_size(100, 100, canvas.get_pixel_ratio())
        sizes = []
        context = gui.gui_renderer._canvas_context
        acquire = context.get_current_texture

        def capture_texture():
            texture = acquire()
            sizes.append((texture.width, texture.height))
            return texture

        monkeypatch.setattr(context, "get_current_texture", capture_texture)
        canvas.force_draw()
        assert canvas.get_physical_size() == native_size
        assert sizes[-1] == native_size
        assert not gui.errors
    finally:
        gui.close()
