"""GLFW platform windows and WGPU surfaces for one ImGui context."""
import ctypes
import os

import glfw
import wgpu
from imgui_bundle import imgui
from rendercanvas.glfw import KEY_MAP
from wgpu.utils.glfw_present_info import get_glfw_present_info


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


class GlfwViewportHost:
    def __init__(self, gui, enabled):
        self.gui = gui
        self.renderer = gui.gui_renderer
        self.main = gui.canvas._window
        self.surfaces = {}
        self.callbacks = {}
        self.focus_pending = False
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
        if self.enabled:
            imgui.get_io().backend_flags |= imgui.BackendFlags_.renderer_has_viewports
            imgui.get_io().config_flags |= imgui.ConfigFlags_.viewports_enable
        self._install(self.main)

    def _install(self, window):
        address = _address(window)
        if address in self.callbacks:
            return
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
            ("glfwSetWindowCloseCallback", glfw._GLFWwindowclosefun, self._dirty),
        ):
            setter = getattr(glfw._glfw, name)
            previous = [None]
            def dispatch(*args, previous=previous, handler=handler):
                previous_context = imgui.get_current_context()
                imgui.set_current_context(self.renderer.imgui_context)
                was_active = self.gui._frame_active
                self.gui._frame_active = True
                try:
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
        ratio = context.pixel_ratio
        self.renderer.backend.io.display_framebuffer_scale = (ratio, ratio)
        imgui.new_frame()
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
