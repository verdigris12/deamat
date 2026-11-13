"""Native input and X11 policy for ImGui GLFW windows."""
import ctypes
import sys

import glfw
from imgui_bundle import imgui
KEY_MAP = {
    glfw.KEY_DOWN: "ArrowDown",
    glfw.KEY_UP: "ArrowUp",
    glfw.KEY_LEFT: "ArrowLeft",
    glfw.KEY_RIGHT: "ArrowRight",
    glfw.KEY_BACKSPACE: "Backspace",
    glfw.KEY_CAPS_LOCK: "CapsLock",
    glfw.KEY_DELETE: "Delete",
    glfw.KEY_END: "End",
    glfw.KEY_ENTER: "Enter",  # aka return
    glfw.KEY_ESCAPE: "Escape",
    glfw.KEY_F1: "F1",
    glfw.KEY_F2: "F2",
    glfw.KEY_F3: "F3",
    glfw.KEY_F4: "F4",
    glfw.KEY_F5: "F5",
    glfw.KEY_F6: "F6",
    glfw.KEY_F7: "F7",
    glfw.KEY_F8: "F8",
    glfw.KEY_F9: "F9",
    glfw.KEY_F10: "F10",
    glfw.KEY_F11: "F11",
    glfw.KEY_F12: "F12",
    glfw.KEY_HOME: "Home",
    glfw.KEY_INSERT: "Insert",
    glfw.KEY_LEFT_ALT: "Alt",
    glfw.KEY_LEFT_CONTROL: "Control",
    glfw.KEY_LEFT_SHIFT: "Shift",
    glfw.KEY_LEFT_SUPER: "Meta",  # in glfw super means Windows or MacOS-command
    glfw.KEY_NUM_LOCK: "NumLock",
    glfw.KEY_PAGE_DOWN: "PageDown",
    glfw.KEY_PAGE_UP: "PageUp",
    glfw.KEY_PAUSE: "Pause",
    glfw.KEY_PRINT_SCREEN: "PrintScreen",
    glfw.KEY_RIGHT_ALT: "Alt",
    glfw.KEY_RIGHT_CONTROL: "Control",
    glfw.KEY_RIGHT_SHIFT: "Shift",
    glfw.KEY_RIGHT_SUPER: "Meta",
    glfw.KEY_SCROLL_LOCK: "ScrollLock",
    glfw.KEY_TAB: "Tab",
}



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
    """Native X11 identity and ImGui-requested ownership, without topmost."""

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
        self.x11.XSetTransientForHint.argtypes = (
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
        )
        self.x11.XDeleteProperty.argtypes = (
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
        )
        self.parents = {}
        atom = lambda name: self.x11.XInternAtom(self.display, name, False)
        self.window_type = atom(b"_NET_WM_WINDOW_TYPE")
        self.utility = atom(b"_NET_WM_WINDOW_TYPE_UTILITY")
        self.wm_class = atom(b"WM_CLASS")
        self.atom_type = atom(b"ATOM")
        self.string_type = atom(b"STRING")
        self.transient_for = atom(b"WM_TRANSIENT_FOR")

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

    def set_parent(self, window, parent):
        address = _address(window)
        parent_xid = glfw.get_x11_window(parent) if parent else 0
        if self.parents.get(address, 0) == parent_xid:
            return
        xid = glfw.get_x11_window(window)
        if parent_xid:
            self.x11.XSetTransientForHint(self.display, xid, parent_xid)
            self.parents[address] = parent_xid
        else:
            self.x11.XDeleteProperty(self.display, xid, self.transient_for)
            self.parents.pop(address, None)
        self.x11.XFlush(self.display)




def _sync_viewport_geometry(viewport, window, geometry):
    """Report native changes, not pending ImGui position or size requests."""
    address = _address(window)
    x, y = glfw.get_window_pos(window)
    width, height = glfw.get_window_size(window)
    previous = geometry.get(address)
    geometry[address] = (x, y, width, height)
    if previous is None:
        # The WM may have placed or resized a new window before callbacks
        # were installed. Reconcile that initial geometry once.
        previous = (viewport.pos.x, viewport.pos.y, viewport.size.x, viewport.size.y)
    if (x, y) != previous[:2]:
        viewport.platform_request_move = True
    if (width, height) != previous[2:]:
        viewport.platform_request_resize = True





class GlfwViewportHost:
    def __init__(self, gui, enabled):
        self.gui = gui
        self.main = gui.window
        self.callbacks = {}
        self.geometry = {}
        self._drag_request = None
        self.focus_pending = False
        self._close_frame_pending = False
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
            # Let the window manager decorate ordinary detached windows; ImGui
            # still marks popups and tooltips as undecorated.
            imgui.get_io().config_viewports_no_decoration = False
            imgui.get_io().config_flags |= imgui.ConfigFlags_.viewports_enable
        else:
            imgui.get_io().config_flags &= ~imgui.ConfigFlags_.viewports_enable
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
                imgui.set_current_context(self.gui.imgui_context)
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
                    if previous_context != self.gui.imgui_context:
                        imgui.set_current_context(previous_context)
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
            # Keep the main window alive until backend cleanup completes.
            glfw.set_window_should_close(window, False)
            self.gui.close()
        else:
            self._close_frame_pending = True
            self.gui.request_draw()

    def _focus(self, window, focused):
        if not focused or self._x11_policy:
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

    def _retire_windows(self, addresses):
        for address in addresses:
            self.callbacks.pop(address, None)
            self.geometry.pop(address, None)
            if self._x11_policy:
                self._x11_policy.parents.pop(address, None)
            if self._drag_request and self._drag_request[0] == address:
                self._drag_request = None

    def _reconcile_drag_position(self):
        moving = imgui.get_current_context().moving_window
        root = moving.root_window_dock_tree if moving else None
        viewport = root.viewport if root and root.viewport_owned else None
        public_viewport = viewport.draw_data_p.owner_viewport if viewport else None
        window = _window(public_viewport) if public_viewport else None
        if not window or _address(window) == _address(self.main):
            self._drag_request = None
            return
        address = _address(window)
        requested = (int(root.pos.x), int(root.pos.y))
        actual = glfw.get_window_pos(window)
        if self._drag_request != (address, requested):
            self._drag_request = (address, requested)
            if requested != actual:
                glfw.set_window_pos(window, *requested)
                actual = glfw.get_window_pos(window)
        # ImGui's requested drag position can be rejected by the WM. Keep
        # layout, hit testing and global-coordinate overlays in the confirmed
        # native coordinate space, separately from the requested position.
        native_pos = imgui.ImVec2(*actual)
        imgui.internal.set_window_pos(root, native_pos)
        public_viewport.pos = native_pos
        viewport.update_work_rect()
        viewport.last_platform_pos = native_pos

    def pre_new_frame(self):
        if self.enabled:
            # Preserve viewports only after an ordinary window has actually
            # detached. Global no-auto-merge also detaches modal popups.
            main_id = imgui.get_main_viewport().id_
            for imgui_window in imgui.get_current_context().windows:
                if (imgui_window.viewport_owned and imgui_window.viewport_id != main_id
                        and not imgui_window.flags & (
                            imgui.WindowFlags_.child_window | imgui.WindowFlags_.popup
                            | imgui.WindowFlags_.tooltip)):
                    imgui_window.window_class.viewport_flags_override_set |= imgui.ViewportFlags_.no_auto_merge
            for viewport in imgui.get_platform_io().viewports:
                window = _window(viewport)
                if window and _address(window) != _address(self.main):
                    _sync_viewport_geometry(viewport, window, self.geometry)
        if self.focus_pending:
            self.focus_pending = False
            focused = next((window for window, _ in self.callbacks.values()
                            if glfw.get_window_attrib(window, glfw.FOCUSED)), None)
            if not focused:
                self.gui._emit_input({"event_type": "focus_out"})
            elif self._x11_policy:
                # Resolve focus after native callbacks settle. Redirect focus
                # within this application only; never steal it from another app.
                modal = imgui.internal.get_top_most_and_visible_popup_modal()
                viewport = imgui.find_viewport_by_id(modal.viewport_id) if modal else None
                target = _window(viewport) if viewport else None
                if target and _address(target) != _address(focused):
                    glfw.focus_window(target)
    def post_new_frame(self):
        if self.enabled:
            self._reconcile_drag_position()
        if not imgui.get_current_context().input_events_queue.empty():
            self.gui.request_draw()

    def after_frame(self):
        if self._close_frame_pending:
            self._close_frame_pending = False
            self.gui.request_draw()
        if not self.enabled:
            return
        live = {_address(self.main)}
        for internal in imgui.get_current_context().viewports:
            viewport = internal.draw_data_p.owner_viewport
            window = _window(viewport) if viewport else None
            if not window or _address(window) == _address(self.main):
                continue
            address = _address(window)
            live.add(address)
            if address not in self.callbacks:
                self._install(window)
                self.gui.request_draw()
            if self._x11_policy:
                parent = imgui.find_viewport_by_id(viewport.parent_viewport_id)
                self._x11_policy.set_parent(window, _window(parent) if parent else None)
        self._retire_windows((self.callbacks.keys() | self.geometry.keys()) - live)

    def close(self):
        # Restore only the live main window; platform destruction owns secondary windows.
        window, callbacks = self.callbacks.pop(_address(self.main))
        for setter, callback, previous in callbacks:
            setter(window, previous)
        self.geometry.clear()
        self._drag_request = None
