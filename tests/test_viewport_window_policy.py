"""X11 viewport policy regressions; run with a display, e.g. Xvfb."""
import os
import shutil
import subprocess
import sys

import pytest

from deamat import GUI, GUIState, imgui
from deamat._glfw_viewports import _window
import glfw


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"),
    reason="requires a Linux GLFW display",
)


def test_secondary_identity_overlap_and_native_close():
    if not shutil.which("xprop"):
        pytest.skip("requires xprop")
    gui = GUI(GUIState(), width=640, height=480, update_mode="ondemand")
    try:
        if not gui._viewport_host.enabled or not gui._viewport_host._x11_policy:
            pytest.skip("requires X11 detached viewports")
        imgui.get_io().set_ini_filename("")
        state = {"open": True, "window": None, "viewport": None}

        def update(_state, _gui, _dt):
            if state["open"]:
                imgui.set_next_window_pos((1050, 150), imgui.Cond_.once)
                imgui.set_next_window_size((320, 240), imgui.Cond_.once)
                _, state["open"] = imgui.begin("Policy pane", state["open"])
                viewport = imgui.get_window_viewport()
                state["window"] = _window(viewport)
                state["viewport"] = viewport.id_
                imgui.end()

        gui.update = update
        gui.gui_renderer.set_gui(gui._draw_imgui)
        gui.canvas.request_draw(gui._render_frame)

        def frame():
            glfw.poll_events()
            gui.canvas.force_draw()

        for _ in range(6):
            frame()
        window = state["window"]
        viewport_id = state["viewport"]
        assert window and viewport_id != imgui.get_main_viewport().id_
        # The dock host must stay in the main native window; the pane is the
        # only secondary platform viewport.
        assert {viewport.id_ for viewport in imgui.get_platform_io().viewports} == {
            imgui.get_main_viewport().id_, viewport_id,
        }
        props = subprocess.check_output(
            ["xprop", "-id", str(glfw.get_x11_window(window)), "WM_CLASS", "_NET_WM_WINDOW_TYPE", "_NET_WM_STATE"],
            text=True,
        )
        assert '"deamat-viewport", "DeamatViewport"' in props
        assert "_NET_WM_WINDOW_TYPE_UTILITY" in props
        assert "_NET_WM_STATE_ABOVE" not in props
        main_props = subprocess.check_output(
            ["xprop", "-id", str(glfw.get_x11_window(gui.canvas._window)), "WM_CLASS"], text=True,
        )
        assert '"DeamatViewport"' not in main_props

        x, y = glfw.get_window_pos(gui.canvas._window)
        glfw.set_window_pos(window, x + 50, y + 50)
        for _ in range(4):
            frame()
        assert state["viewport"] == viewport_id

        setter = glfw._glfw.glfwSetWindowCloseCallback
        callback = setter(window, setter.argtypes[1]())
        setter(window, callback)
        assert callback
        glfw.set_window_should_close(window, True)
        callback(window)
        for _ in range(4):
            frame()
        assert not state["open"]
        assert not gui._closed
        assert not gui.errors
    finally:
        gui.close()
