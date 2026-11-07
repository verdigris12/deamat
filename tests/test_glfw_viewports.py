"""Native regressions: run on Linux with a display (CI can use Xvfb)."""
import os
import sys

import pytest

from deamat import GUI, GUIState, imgui
from deamat._glfw_viewports import _window
import glfw


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"),
    reason="requires a Linux GLFW display",
)


def _callback(window, setter, callback_type):
    """Borrow the installed native callback without replacing its chain."""
    previous = setter(window, callback_type())
    setter(window, previous)
    assert previous
    return previous


@pytest.mark.parametrize("detached", [False, True])
def test_fast_native_click_reaches_viewport_checkbox(detached):
    gui = GUI(GUIState(), width=640, height=480, update_mode="ondemand")
    try:
        if not gui._viewport_host.enabled:
            pytest.skip("native detached viewports unavailable")
        glfw.set_window_pos(gui.canvas._window, 50, 50)
        imgui.get_io().set_ini_filename("")
        state = {"checked": False, "window": None, "point": None, "mouse": None}

        def update(_state, _gui, _dt):
            imgui.set_next_window_pos((1050, 150) if detached else (150, 150), imgui.Cond_.always)
            imgui.set_next_window_size((320, 240), imgui.Cond_.always)
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
        wx, wy = glfw.get_window_pos(window)
        glfw.focus_window(window)
        glfw.set_cursor_pos(window, x - wx, y - wy)
        # Poll the native hover/motion, but do not start an ImGui frame before
        # the button burst: this exercises the initially stale hovered viewport.
        glfw.poll_events()
        assert glfw.get_window_attrib(window, glfw.HOVERED)
        motion = _callback(window, glfw._glfw.glfwSetCursorPosCallback, glfw._GLFWcursorposfun)
        button = _callback(window, glfw._glfw.glfwSetMouseButtonCallback, glfw._GLFWmousebuttonfun)
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
        close = _callback(window, glfw._glfw.glfwSetWindowCloseCallback, glfw._GLFWwindowclosefun)
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
