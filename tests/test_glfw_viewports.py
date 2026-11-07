"""Native regressions: run on Linux with a display (CI can use Xvfb)."""
import os
import sys
from types import SimpleNamespace

import pytest

from deamat import GUI, GUIState, imgui
from deamat._glfw_viewports import _window
from deamat._glfw_viewports import _address
import glfw


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"),
    reason="requires a Linux GLFW display",
)


def _callback(window, setter):
    """Borrow the installed native callback without replacing its chain."""
    previous = setter(window, setter.argtypes[1]())
    setter(window, previous)
    assert previous
    return previous


@pytest.mark.parametrize("viewports,detached", [(True, False), (True, True), (False, False)])
def test_fast_native_click_reaches_viewport_checkbox(viewports, detached):
    gui = GUI(GUIState(), width=640, height=480, update_mode="ondemand", viewports=viewports)
    try:
        if viewports and not gui._viewport_host.enabled:
            pytest.skip("native detached viewports unavailable")
        glfw.set_window_pos(gui.canvas._window, 50, 50)
        imgui.get_io().set_ini_filename("")
        state = {"checked": False, "window": None, "point": None, "mouse": None}

        def update(_state, _gui, _dt):
            imgui.set_next_window_pos((1050, 150) if detached else (150, 150), imgui.Cond_.always)
            imgui.set_next_window_size((320, 240), imgui.Cond_.always)
            if viewports and not detached:
                imgui.set_next_window_viewport(imgui.get_main_viewport().id_)
            imgui.begin("Native input regression")
            viewport = imgui.get_window_viewport()
            state["window"] = _window(viewport)
            state["viewport"] = viewport.id_
            _, state["checked"] = imgui.checkbox("Native checkbox", state["checked"])
            a, b = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            state["point"] = ((a.x + b.x) / 2, (a.y + b.y) / 2)
            mouse = imgui.get_mouse_pos()
            state["mouse"] = (mouse.x, mouse.y)
            imgui.end()

        gui.update = update
        gui.gui_renderer.set_gui(gui._draw_imgui)
        gui.canvas.request_draw(gui._render_frame)

        def frame():
            glfw.poll_events()
            gui.canvas.force_draw()

        for _ in range(6):
            frame()
        assert state["window"]
        assert (state["viewport"] != imgui.get_main_viewport().id_) == detached
        window = state["window"]
        x, y = state["point"]
        wx, wy = glfw.get_window_pos(window) if viewports else (0, 0)
        glfw.focus_window(window)
        glfw.set_cursor_pos(window, x - wx, y - wy)
        # Poll the native hover/motion, but do not start an ImGui frame before
        # the button burst: this exercises the initially stale hovered viewport.
        glfw.poll_events()
        assert glfw.get_window_attrib(window, glfw.HOVERED)
        motion = _callback(window, glfw._glfw.glfwSetCursorPosCallback)
        button = _callback(window, glfw._glfw.glfwSetMouseButtonCallback)
        motion(window, x - wx, y - wy)
        button(window, glfw.MOUSE_BUTTON_LEFT, glfw.PRESS, 0)
        button(window, glfw.MOUSE_BUTTON_LEFT, glfw.RELEASE, 0)
        for _ in range(5):
            frame()
        assert state["checked"]
        assert state["mouse"] == pytest.approx((x, y), abs=1)
        assert not gui.errors
    finally:
        gui.close()


def test_native_main_close_shuts_down_before_window_destruction():
    gui = GUI(GUIState(), width=640, height=480)
    try:
        window = gui.canvas._window
        close = _callback(window, glfw._glfw.glfwSetWindowCloseCallback)
        glfw.set_window_should_close(window, True)
        close(window)
        assert gui._closed
        assert not glfw.window_should_close(window)
        assert not gui._shutdown_complete
        gui._shutdown()
        assert gui._shutdown_complete
        assert not gui.errors
    finally:
        gui.close()


def test_callback_survives_render_list_omission_until_native_destruction(monkeypatch):
    gui = GUI(GUIState(), width=640, height=480, update_mode="ondemand", viewports=True)
    try:
        host = gui._viewport_host
        if not host.enabled:
            pytest.skip("native detached viewports unavailable")
        imgui.get_io().set_ini_filename("")
        state = {"show": True, "viewport": None}

        def update(_state, _gui, _dt):
            if state["show"]:
                imgui.set_next_window_pos((1050, 150), imgui.Cond_.once)
                imgui.set_next_window_size((320, 240), imgui.Cond_.once)
                imgui.begin("Callback lifetime")
                state["viewport"] = imgui.get_window_viewport().id_
                imgui.end()

        gui.update = update
        gui.gui_renderer.set_gui(gui._draw_imgui)
        gui.canvas.request_draw(gui._render_frame)

        def frame():
            glfw.poll_events()
            gui.canvas.force_draw()

        for _ in range(6):
            frame()
        viewport_id = state["viewport"]
        viewport = imgui.find_viewport_by_id(viewport_id)
        window = _window(viewport)
        assert window and viewport_id != imgui.get_main_viewport().id_
        address = _address(window)
        assert address in host.callbacks and address in host.surfaces

        # Model the ImGui frame where the native viewport still exists but is
        # omitted from the renderer-facing PlatformIO viewport list.
        platform_io = imgui.get_platform_io
        with monkeypatch.context() as patch:
            patch.setattr(imgui, "get_platform_io", lambda: SimpleNamespace(
                viewports=[v for v in platform_io().viewports if v.id_ != viewport_id]))
            frame()
            assert address in host.callbacks and address in host.surfaces
            callback = _callback(window, glfw._glfw.glfwSetCursorPosCallback)
            callback(window, 10, 10)

        state["show"] = False
        for _ in range(5):
            frame()
        assert address not in host.callbacks and address not in host.surfaces
        assert not gui.errors
    finally:
        gui.close()
