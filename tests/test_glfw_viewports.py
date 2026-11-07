from types import SimpleNamespace

from deamat import _glfw_viewports as host_module


def test_native_renderer_does_not_install_canvas_input_handlers(monkeypatch):
    context = SimpleNamespace(_config={"format": "rgba8unorm"})
    canvas = SimpleNamespace(get_wgpu_context=lambda: context)
    device = object()
    imgui_context = object()
    backend = object()
    monkeypatch.setattr(host_module.imgui, "create_context", lambda: imgui_context)
    monkeypatch.setattr(host_module.imgui, "set_current_context", lambda value: None)
    monkeypatch.setattr(host_module, "ImguiWgpuBackend", lambda gpu, fmt: (
        backend if (gpu, fmt) == (device, "rgba8unorm") else None
    ))
    renderer = host_module.NativeImguiRenderer(device, canvas)
    assert renderer.imgui_context is imgui_context
    assert renderer.backend is backend
    callback = lambda: None
    renderer.set_gui(callback)
    assert renderer._update_gui_function is callback


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


def test_main_close_is_deferred_to_gui_while_child_close_only_redraws(monkeypatch):
    host = host_module.GlfwViewportHost.__new__(host_module.GlfwViewportHost)
    host.main = "main"
    calls = []
    host.gui = SimpleNamespace(
        close=lambda: calls.append("close"),
        request_draw=lambda: calls.append("draw"),
    )
    monkeypatch.setattr(host_module, "_address", lambda window: window)
    monkeypatch.setattr(host_module.glfw, "set_window_should_close",
                        lambda window, value: calls.append((window, value)))
    host._close_window("main")
    host._close_window("child")
    assert calls == [("main", False), "close", "draw"]


def test_native_callback_reports_handler_errors(monkeypatch):
    host = host_module.GlfwViewportHost.__new__(host_module.GlfwViewportHost)
    errors = []
    host.gui = SimpleNamespace(_frame_active=False, _closed=False, _record_error=errors.append)
    host.renderer = SimpleNamespace(imgui_context=object())
    host.callbacks = {}
    host.enabled = False
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


def test_hovered_viewport_is_queued_before_native_mouse_input(monkeypatch):
    host = host_module.GlfwViewportHost.__new__(host_module.GlfwViewportHost)
    host.enabled = True
    host.callbacks = {}
    events = []
    host.gui = SimpleNamespace(_frame_active=False, _closed=False,
                               _record_error=lambda error: events.append(error),
                               request_draw=lambda: None)
    host.renderer = SimpleNamespace(imgui_context=object())
    viewport = SimpleNamespace(id_=42)
    monkeypatch.setattr(host_module, "_address", lambda window: 1)
    monkeypatch.setattr(host_module, "_window", lambda viewport: object())
    monkeypatch.setattr(host_module.glfw, "get_window_attrib", lambda *args: True)
    monkeypatch.setattr(host_module.imgui, "get_current_context", lambda: host.renderer.imgui_context)
    monkeypatch.setattr(host_module.imgui, "set_current_context", lambda context: None)
    monkeypatch.setattr(host_module.imgui, "get_platform_io", lambda: SimpleNamespace(viewports=[viewport]))
    monkeypatch.setattr(host_module.imgui, "get_io", lambda: SimpleNamespace(
        add_mouse_viewport_event=lambda identifier: events.append(("viewport", identifier))))
    names = ("MouseButton", "Key", "CursorPos", "Scroll", "Char", "WindowFocus",
             "WindowSize", "WindowRefresh", "WindowPos", "WindowClose")
    setters = {f"glfwSet{name}Callback": lambda window, callback: None for name in names}
    setters["glfwSetMouseButtonCallback"] = lambda window, callback: (
        lambda *args: events.append("native mouse"))
    monkeypatch.setattr(host_module.glfw, "_glfw", SimpleNamespace(**setters))
    host._mouse = lambda *args: events.append("handler")
    host._install(None)
    host.callbacks[1][1][0][1](None, 0, 1, 0)
    assert events == [("viewport", 42), "native mouse", "handler"]


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
