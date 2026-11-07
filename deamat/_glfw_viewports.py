"""GLFW platform windows and WGPU surfaces for one ImGui context."""
import ctypes
import os
import sys

import glfw
import wgpu
from imgui_bundle import imgui
from rendercanvas.glfw import KEY_MAP
from wgpu.utils.glfw_present_info import get_glfw_present_info
from wgpu.utils.imgui.imgui_backend import ImguiWgpuBackend


_capsule_pointer = ctypes.pythonapi.PyCapsule_GetPointer
_capsule_pointer.argtypes = (ctypes.py_object, ctypes.c_char_p)
_capsule_pointer.restype = ctypes.c_void_p


def _window(viewport):
    if viewport.platform_handle is None:
        return None
    address = _capsule_pointer(viewport.platform_handle, b"nb_handle")
    return ctypes.cast(address, ctypes.POINTER(glfw._GLFWwindow)) if address else None


def _address(window):
    return ctypes.cast(window, ctypes.c_void_p).value

class _X11ViewportPolicy:
    """Identify secondary windows for X11 window managers, without topmost."""

    def __init__(self):
        self.display = glfw.get_x11_display()
        self.x11 = ctypes.CDLL("libX11.so.6")
        self.x11.XInternAtom.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int)
        self.x11.XInternAtom.restype = ctypes.c_ulong
        self.x11.XChangeProperty.argtypes = (
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
        )
        self.x11.XFlush.argtypes = (ctypes.c_void_p,)
        atom = lambda name: self.x11.XInternAtom(self.display, name, False)
        self.window_type = atom(b"_NET_WM_WINDOW_TYPE")
        self.utility = atom(b"_NET_WM_WINDOW_TYPE_UTILITY")
        self.wm_class = atom(b"WM_CLASS")
        self.atom_type = atom(b"ATOM")
        self.string_type = atom(b"STRING")

    def install(self, window):
        xid = glfw.get_x11_window(window)
        utility = ctypes.c_ulong(self.utility)
        self.x11.XChangeProperty(
            self.display, xid, self.window_type, self.atom_type, 32, 0,
            ctypes.byref(utility), 1,
        )
        identity = ctypes.create_string_buffer(b"deamat-viewport\0DeamatViewport\0")
        self.x11.XChangeProperty(
            self.display, xid, self.wm_class, self.string_type, 8, 0,
            identity, len(identity.raw) - 1,
        )
        self.x11.XFlush(self.display)



class NativeImguiRenderer:
    """One ImGui context and shared WGPU backend, without canvas input hooks."""

    def __init__(self, device, canvas):
        self._canvas_context = canvas.get_wgpu_context()
        config = self._canvas_context._config
        if config is None:
            target_format = self._canvas_context.get_preferred_format(device.adapter)
            self._canvas_context.configure(device=device, format=target_format)
        else:
            target_format = config["format"]
        self.imgui_context = imgui.create_context()
        imgui.set_current_context(self.imgui_context)
        self.backend = ImguiWgpuBackend(device, target_format)
        self._update_gui_function = None

    def set_gui(self, callback):
        self._update_gui_function = callback


class GlfwViewportHost:
    def __init__(self, gui, enabled):
        self.gui = gui
        self.renderer = gui.gui_renderer
        self.main = gui.canvas._window
        self.surfaces = {}
        self.callbacks = {}
        self.focus_pending = False
        self._close_frame_pending = False
        # The bundled platform backend and Python GLFW must share one library.
        import imgui_bundle
        bundled = os.path.join(os.path.dirname(imgui_bundle.__file__), "libglfw.so.3")
        if os.path.exists(bundled) and not os.path.samefile(glfw._glfw._name, bundled):
            raise RuntimeError("Python GLFW and imgui-bundle use different GLFW libraries; import imgui_bundle before glfw")
        if not imgui.backends.glfw_init_for_other(_address(self.main), True):
            raise RuntimeError("ImGui GLFW backend initialization failed")
        wayland = (hasattr(glfw, "get_platform") and
                   glfw.get_platform() == getattr(glfw, "PLATFORM_WAYLAND", -1))
        self.enabled = bool(enabled and not wayland and (imgui.get_io().backend_flags & imgui.BackendFlags_.platform_has_viewports))
        self._x11_policy = (
            _X11ViewportPolicy()
            if self.enabled and sys.platform.startswith("linux")
            and hasattr(glfw, "get_x11_display") and hasattr(glfw, "get_x11_window")
            else None
        )
        if self.enabled:
            imgui.get_io().backend_flags |= imgui.BackendFlags_.renderer_has_viewports
            imgui.get_io().config_flags |= imgui.ConfigFlags_.viewports_enable
            imgui.get_io().config_viewports_no_auto_merge = True
        self._install(self.main)

    def _install(self, window):
        address = _address(window)
        if address in self.callbacks:
            return
        if self._x11_policy and address != _address(self.main):
            self._x11_policy.install(window)
        callbacks = []
        # Use GLFW's C setter directly: pyglfw's setter only returns callbacks
        # installed through Python, not the native ImGui backend's callbacks.
        for name, ctype, handler in (
            ("glfwSetMouseButtonCallback", glfw._GLFWmousebuttonfun, self._mouse),
            ("glfwSetKeyCallback", glfw._GLFWkeyfun, self._key),
            ("glfwSetCursorPosCallback", glfw._GLFWcursorposfun, self._dirty),
            ("glfwSetScrollCallback", glfw._GLFWscrollfun, self._dirty),
            ("glfwSetCharCallback", glfw._GLFWcharfun, self._dirty),
            ("glfwSetWindowFocusCallback", glfw._GLFWwindowfocusfun, self._focus),
            ("glfwSetWindowSizeCallback", glfw._GLFWwindowsizefun, self._dirty),
            ("glfwSetWindowRefreshCallback", glfw._GLFWwindowrefreshfun, self._dirty),
            ("glfwSetWindowPosCallback", glfw._GLFWwindowposfun, self._dirty),
            ("glfwSetWindowCloseCallback", glfw._GLFWwindowclosefun, self._close_window),
        ):
            setter = getattr(glfw._glfw, name)
            previous = [None]
            def dispatch(*args, previous=previous, handler=handler, name=name):
                previous_context = imgui.get_current_context()
                imgui.set_current_context(self.renderer.imgui_context)
                was_active = self.gui._frame_active
                self.gui._frame_active = True
                try:
                    if name in ("glfwSetCursorPosCallback", "glfwSetMouseButtonCallback"):
                        self._route_mouse_viewport(args[0])
                    if previous[0]:
                        previous[0](*args)
                    if not self.gui._closed:
                        handler(*args)
                except Exception as error:
                    self.gui._record_error(error)
                finally:
                    self.gui._frame_active = was_active
                    if previous_context != self.renderer.imgui_context:
                        imgui.set_current_context(previous_context)
                    if self.gui._closed and not was_active:
                        from rendercanvas.auto import loop
                        loop.call_soon(self.gui._shutdown)
            callback = ctype(dispatch)
            previous[0] = setter(window, callback)
            callbacks.append((setter, callback, previous[0]))
        self.callbacks[address] = (window, callbacks)

    def _dirty(self, *args):
        self.gui.request_draw()

    def _route_mouse_viewport(self, window):
        # The GLFW backend normally queues this in glfw_new_frame(), after
        # callbacks have already queued mouse movement and button events.
        # Queue it first so a trickled first click targets the right viewport.
        if not self.enabled or not glfw.get_window_attrib(window, glfw.HOVERED):
            return
        address = _address(window)
        for viewport in imgui.get_platform_io().viewports:
            candidate = _window(viewport)
            if candidate and _address(candidate) == address:
                imgui.get_io().add_mouse_viewport_event(viewport.id_)
                break

    def _close_window(self, window):
        if _address(window) == _address(self.main):
            # rendercanvas otherwise destroys the GLFW window at the end of
            # polling, before our backend and child windows can be shut down.
            glfw.set_window_should_close(window, False)
            self.gui.close()
        else:
            self._close_frame_pending = True
            self.gui.request_draw()

    def _focus(self, window, focused):
        if not focused:
            self.focus_pending = True
        self.gui.request_draw()

    @staticmethod
    def _modifiers(mods):
        return tuple(name for bit, name in ((glfw.MOD_ALT, "Alt"), (glfw.MOD_CONTROL, "Control"), (glfw.MOD_SUPER, "Meta"), (glfw.MOD_SHIFT, "Shift")) if mods & bit)

    def _mouse(self, window, button, action, mods):
        if action == glfw.RELEASE:
            x, y = glfw.get_cursor_pos(window)
            if self.enabled:
                wx, wy = glfw.get_window_pos(window)
                x, y = x + wx, y + wy
            button = {glfw.MOUSE_BUTTON_LEFT: 1, glfw.MOUSE_BUTTON_RIGHT: 2, glfw.MOUSE_BUTTON_MIDDLE: 3}.get(button, button + 1)
            self.gui._emit_input({"event_type": "pointer_up", "x": x, "y": y, "button": button, "modifiers": self._modifiers(mods)})
        self.gui.request_draw()

    def _key(self, window, key, scancode, action, mods):
        if action in (glfw.PRESS, glfw.RELEASE):
            name = KEY_MAP.get(key)
            if name is None:
                try:
                    name = chr(key)
                except ValueError:
                    return
                if not mods & glfw.MOD_SHIFT:
                    name = name.lower()
            self.gui._emit_input({"event_type": "key_down" if action == glfw.PRESS else "key_up", "key": name, "modifiers": self._modifiers(mods)})
        self.gui.request_draw()

    def pixel_ratio(self):
        window = None
        context = imgui.get_current_context()
        if context and context.within_frame_scope and context.current_window:
            window = _window(imgui.get_window_viewport())
        if not window:
            window = self.main
        width, _ = glfw.get_window_size(window)
        pixels, _ = glfw.get_framebuffer_size(window)
        return pixels / width if width else self.gui.canvas.get_pixel_ratio()

    def render(self):
        imgui.set_current_context(self.renderer.imgui_context)
        imgui.backends.glfw_new_frame()
        if self.focus_pending:
            self.focus_pending = False
            if not any(glfw.get_window_attrib(window, glfw.FOCUSED) for window, _ in self.callbacks.values()):
                self.gui._emit_input({"event_type": "focus_out"})
        context = self.renderer._canvas_context
        imgui.new_frame()
        # Dear ImGui may trickle a burst of input over several frames. The
        # rendercanvas scheduler clears its draw flag before invoking us, so
        # request another frame only while unprocessed events remain.
        if not imgui.get_current_context().input_events_queue.empty():
            self.gui.request_draw()
        try:
            self.renderer._update_gui_function()
        finally:
            imgui.render()
        if self.enabled:
            imgui.update_platform_windows()
        self._draw(imgui.get_draw_data(), context.get_current_texture().create_view())
        if not self.enabled:
            return
        active = set()
        for viewport in imgui.get_platform_io().viewports:
            window = _window(viewport)
            if not window or _address(window) == _address(self.main):
                continue
            address = _address(window)
            active.add(address)
            self._install(window)
            size = glfw.get_framebuffer_size(window)
            if size[0] <= 0 or size[1] <= 0:
                continue
            surface = self.surfaces.get(address)
            if surface is None:
                surface = wgpu.gpu.get_canvas_context(get_glfw_present_info(window))
                surface.configure(device=self.renderer.backend._device, format=self.renderer.backend._target_format)
                self.surfaces[address] = surface
            surface.set_physical_size(*size)
            if viewport.draw_data and viewport.draw_data.display_size.x and viewport.draw_data.display_size.y:
                viewport.draw_data.framebuffer_scale = (
                    size[0] / viewport.draw_data.display_size.x,
                    size[1] / viewport.draw_data.display_size.y,
                )
            self._draw(viewport.draw_data, surface.get_current_texture().create_view())
            surface.present()
        for address in self.surfaces.keys() - active:
            self.surfaces.pop(address).unconfigure()
        for address in self.callbacks.keys() - active - {_address(self.main)}:
            self.callbacks.pop(address)

    def _draw(self, draw_data, view):
        device = self.renderer.backend._device
        encoder = device.create_command_encoder()
        render_pass = encoder.begin_render_pass(color_attachments=[{"view": view, "resolve_target": None, "clear_value": (0, 0, 0, 1), "load_op": wgpu.LoadOp.clear, "store_op": wgpu.StoreOp.store}])
        self.renderer.backend.render(draw_data, render_pass)
        render_pass.end()
        # Submit before the next viewport writes the backend's shared buffers.
        device.queue.submit([encoder.finish()])

    def close(self):
        for surface in self.surfaces.values():
            surface.unconfigure()
        self.surfaces.clear()
        # Restore only the live main window; platform destruction owns secondary windows.
        window, callbacks = self.callbacks.pop(_address(self.main))
        for setter, callback, previous in callbacks:
            setter(window, previous)
        if self.enabled:
            imgui.destroy_platform_windows()
        self.callbacks.clear()
        imgui.backends.glfw_shutdown()
