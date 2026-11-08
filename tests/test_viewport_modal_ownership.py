"""Modal windows remain in their owner viewport and accept input."""
import os
import sys
import shutil
import subprocess

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


def test_detached_modal_native_parent_chain():
    if not shutil.which("xprop"):
        pytest.skip("requires xprop")
    gui = GUI(GUIState(), width=800, height=600, update_mode="ondemand")
    try:
        if not gui._viewport_host.enabled or not gui._viewport_host._x11_policy:
            pytest.skip("requires X11 detached viewports")
        imgui.get_io().set_ini_filename("")
        window_class = imgui.WindowClass()
        window_class.viewport_flags_override_set = imgui.ViewportFlags_.no_auto_merge
        state = {"first": True, "nested": False, "open_nested": False}

        def update(_state, _gui, _dt):
            if state["first"]:
                imgui.open_popup("Detached modal")
                state["first"] = False
            imgui.set_next_window_class(window_class)
            imgui.set_next_window_size((300, 200))
            visible, _ = imgui.begin_popup_modal("Detached modal")
            if visible:
                state["parent"] = imgui.get_window_viewport().id_
                if state["open_nested"]:
                    imgui.open_popup("Nested confirmation")
                    state["open_nested"] = False
                if state["nested"]:
                    imgui.set_next_window_class(window_class)
                    imgui.set_next_window_size((200, 100))
                    nested, _ = imgui.begin_popup_modal("Nested confirmation")
                    if nested:
                        state["child"] = imgui.get_window_viewport().id_
                        imgui.end_popup()
                imgui.end_popup()

        gui.update = update
        gui.gui_renderer.set_gui(gui._draw_imgui)
        gui.canvas.request_draw(gui._render_frame)

        def frames():
            for _ in range(8):
                glfw.poll_events()
                gui.canvas.force_draw()

        def xid(viewport_id):
            return glfw.get_x11_window(_window(imgui.find_viewport_by_id(viewport_id)))

        def parent_of(viewport_id):
            return subprocess.check_output(
                ["xprop", "-id", str(xid(viewport_id)), "WM_TRANSIENT_FOR"], text=True,
            )

        frames()
        main = imgui.get_main_viewport().id_
        assert state["parent"] != main
        assert f"0x{xid(main):x}" in parent_of(state["parent"])
        state["nested"] = state["open_nested"] = True
        frames()
        assert state["child"] not in (main, state["parent"])
        assert f"0x{xid(state['parent']):x}" in parent_of(state["child"])
        child = _window(imgui.find_viewport_by_id(state["child"]))
        glfw.focus_window(gui.canvas._window)
        frames()
        assert glfw.get_window_attrib(child, glfw.FOCUSED)
        glfw.default_window_hints()
        glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)
        unrelated = glfw.create_window(160, 120, "Unrelated window", None, None)
        try:
            assert unrelated
            glfw.focus_window(unrelated)
            frames()
            assert glfw.get_window_attrib(unrelated, glfw.FOCUSED)
        finally:
            if unrelated:
                glfw.destroy_window(unrelated)
        window_class.parent_viewport_id = 0
        frames()
        assert "window id #" not in parent_of(state["child"])
        assert "window id #" not in parent_of(state["parent"])
        assert not gui.errors
    finally:
        gui.close()
