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
