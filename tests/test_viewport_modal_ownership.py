"""Modal windows remain in their owner viewport and accept input."""
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


def test_main_modal_remains_in_owner_and_accepts_input():
    gui = GUI(GUIState(), width=800, height=600, update_mode="ondemand")
    try:
        if not gui._viewport_host.enabled:
            pytest.skip("requires detached viewport support")
        imgui.get_io().set_ini_filename("")
        glfw.set_window_pos(gui.canvas._window, 50, 50)
        state = {"first": True, "checked": False, "viewport": None, "point": None}

        def update(_state, _gui, _dt):
            if state["first"]:
                imgui.open_popup("Main modal")
                state["first"] = False
            imgui.set_next_window_pos((150, 150), imgui.Cond_.always)
            imgui.set_next_window_size((300, 200), imgui.Cond_.always)
            visible, _ = imgui.begin_popup_modal("Main modal")
            if visible:
                state["viewport"] = imgui.get_window_viewport().id_
                _, state["checked"] = imgui.checkbox("Modal checkbox", state["checked"])
                a, b = imgui.get_item_rect_min(), imgui.get_item_rect_max()
                state["point"] = ((a.x + b.x) / 2, (a.y + b.y) / 2)
                imgui.end_popup()

        gui.update = update
        gui.gui_renderer.set_gui(gui._draw_imgui)
        gui.canvas.request_draw(gui._render_frame)

        def frame():
            glfw.poll_events()
            gui.canvas.force_draw()

        for _ in range(6):
            frame()
        assert state["viewport"] == imgui.get_main_viewport().id_
        assert len(imgui.get_platform_io().viewports) == 1
        window = _window(imgui.get_main_viewport())
        wx, wy = glfw.get_window_pos(window)
        x, y = state["point"]
        glfw.focus_window(window)
        glfw.set_cursor_pos(window, x - wx, y - wy)
        glfw.poll_events()
        assert glfw.get_window_attrib(window, glfw.HOVERED)
        motion_setter = glfw._glfw.glfwSetCursorPosCallback
        motion = motion_setter(window, motion_setter.argtypes[1]())
        motion_setter(window, motion)
        assert motion
        motion(window, x - wx, y - wy)
        setter = glfw._glfw.glfwSetMouseButtonCallback
        callback = setter(window, setter.argtypes[1]())
        setter(window, callback)
        assert callback
        callback(window, glfw.MOUSE_BUTTON_LEFT, glfw.PRESS, 0)
        callback(window, glfw.MOUSE_BUTTON_LEFT, glfw.RELEASE, 0)
        for _ in range(5):
            frame()
        assert state["checked"]
        assert not gui.errors
    finally:
        gui.close()
