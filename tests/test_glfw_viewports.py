from types import SimpleNamespace

from deamat import _glfw_viewports as host_module


def test_callbacks_remain_alive_during_platform_destruction(monkeypatch):
    host = host_module.GlfwViewportHost.__new__(host_module.GlfwViewportHost)
    host.main = "main"
    host.surfaces = {}
    host.callbacks = {1: ("main", []), 2: ("child", [object()])}
    host.enabled = True
    monkeypatch.setattr(host_module, "_address", lambda window: 1)
    monkeypatch.setattr(host_module.imgui, "destroy_platform_windows", lambda: (
        host.callbacks[2][1][0]
    ))
    monkeypatch.setattr(host_module.imgui.backends, "glfw_shutdown", lambda: None)
    host.close()
    assert host.callbacks == {}


def test_native_callback_reports_handler_errors(monkeypatch):
    host = host_module.GlfwViewportHost.__new__(host_module.GlfwViewportHost)
    errors = []
    host.gui = SimpleNamespace(_frame_active=False, _closed=False, _record_error=errors.append)
    host.renderer = SimpleNamespace(imgui_context=object())
    host.callbacks = {}
    monkeypatch.setattr(host_module, "_address", lambda window: 1)
    monkeypatch.setattr(host_module.imgui, "get_current_context", lambda: host.renderer.imgui_context)
    monkeypatch.setattr(host_module.imgui, "set_current_context", lambda context: None)
    names = ("MouseButton", "Key", "CursorPos", "Scroll", "Char", "WindowFocus",
             "WindowSize", "WindowRefresh", "WindowPos", "WindowClose")
    library = SimpleNamespace(**{f"glfwSet{name}Callback": lambda window, callback: None for name in names})
    monkeypatch.setattr(host_module.glfw, "_glfw", library)
    def fail(*args):
        raise ValueError("input failed")
    host._mouse = fail
    host._install(None)
    callback = host.callbacks[1][1][0][1]
    callback(None, 0, 0, 0)
    assert len(errors) == 1
    assert str(errors[0]) == "input failed"
    assert host.gui._frame_active is False


def test_trickled_input_requests_frames_until_queue_is_empty(monkeypatch):
    events = ["move", "down", "up"]
    seen = []
    requests = []
    queue = SimpleNamespace(empty=lambda: not events)
    imgui_context = SimpleNamespace(input_events_queue=queue)
    canvas_context = SimpleNamespace(
        pixel_ratio=1,
        get_current_texture=lambda: SimpleNamespace(create_view=lambda: None),
    )
    host = host_module.GlfwViewportHost.__new__(host_module.GlfwViewportHost)
    host.renderer = SimpleNamespace(
        imgui_context=imgui_context, _canvas_context=canvas_context,
        backend=SimpleNamespace(io=SimpleNamespace()),
        _update_gui_function=lambda: seen.append("frame"),
    )
    host.gui = SimpleNamespace(request_draw=lambda: requests.append("draw"))
    host.focus_pending = False
    host.enabled = False
    host._draw = lambda *args: None
    monkeypatch.setattr(host_module.imgui, "set_current_context", lambda context: None)
    monkeypatch.setattr(host_module.imgui, "get_current_context", lambda: imgui_context)
    monkeypatch.setattr(host_module.imgui.backends, "glfw_new_frame", lambda: None)
    monkeypatch.setattr(host_module.imgui, "new_frame", lambda: seen.append(events.pop(0)))
    monkeypatch.setattr(host_module.imgui, "render", lambda: None)
    monkeypatch.setattr(host_module.imgui, "get_draw_data", lambda: None)
    host.render()
    host.render()
    host.render()
    assert seen == ["move", "frame", "down", "frame", "up", "frame"]
    assert requests == ["draw", "draw"]
