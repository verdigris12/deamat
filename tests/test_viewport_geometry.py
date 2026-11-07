"""Detached viewport geometry and framebuffer scaling regressions."""
import os
import sys

import pytest

from deamat import GUI, GUIState, imgui
from deamat._glfw_viewports import _window
import glfw


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
        glfw.set_window_size(window, 720, 460)
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
