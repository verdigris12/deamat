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
        self.geometry = {}
        self._drag_request = None
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
            # Let the window manager decorate ordinary detached windows; ImGui
            # still marks popups and tooltips as undecorated.
            imgui.get_io().config_viewports_no_decoration = False
            imgui.get_io().backend_flags |= imgui.BackendFlags_.renderer_has_viewports
            imgui.get_io().config_flags |= imgui.ConfigFlags_.viewports_enable
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

    def _retire_surfaces(self, addresses):
        for address in addresses:
            surface = self.surfaces.pop(address, None)
            if surface is not None:
                surface.unconfigure()
                # wgpu-py unconfigure drops the swapchain but not the raw
                # surface. Release it while its native window is still alive.
                surface._release()

    def _retire_windows(self, addresses):
        self._retire_surfaces(addresses)
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

    def _update_platform_windows(self):
        # Render initialized DrawDataP.owner_viewport for every internal
        # viewport, including viewports omitted from the public render list.
        snapshot = []
        imminent = set()
        context = imgui.get_current_context()
        for internal in context.viewports:
            viewport = internal.draw_data_p.owner_viewport
            window = _window(viewport) if viewport else None
            if window:
                address = _address(window)
                snapshot.append((viewport, address))
                owner = internal.window
                # Match ImGui 1.92's UpdatePlatformWindows destruction test.
                if address != _address(self.main) and (
                    internal.last_frame_active < context.frame_count - 1
                    or (owner is not None and (not owner.active or owner.hidden))
                ):
                    imminent.add(address)

        # NewFrame may already have destroyed a viewport. Retire its resources
        # before UpdatePlatformWindows can allocate another GLFW window there.
        live = {address for _, address in snapshot}
        live.add(_address(self.main))
        self._retire_windows((self.surfaces.keys() | self.callbacks.keys() | self.geometry.keys()) - live)
        # Renderer destruction must precede platform destruction; keep the
        # ctypes callbacks until after GLFW has actually destroyed the window.
        self._retire_surfaces(imminent)

        # Keep ctypes callbacks alive through native destruction. Viewport
        # objects themselves remain valid until a subsequent NewFrame.
        imgui.update_platform_windows()
        retired = set()
        for viewport, address in snapshot:
            window = _window(viewport)
            if not window or _address(window) != address:
                retired.add(address)
        retired.discard(_address(self.main))
        self._retire_windows(retired)


    def render(self):
        imgui.set_current_context(self.renderer.imgui_context)
        # The native resize can precede rendercanvas' queued framebuffer event,
        # especially at startup. Synchronize its size bookkeeping and WGPU
        # surface before ImGui lays out against GLFW's current dimensions.
        canvas = self.gui.canvas
        context = self.renderer._canvas_context
        framebuffer_size = glfw.get_framebuffer_size(self.main)
        if framebuffer_size != canvas.get_physical_size():
            canvas._determine_size()
            context._rc_set_size_dict(canvas._size_info)
        imgui.backends.glfw_new_frame()
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
        imgui.new_frame()
        if self.enabled:
            self._reconcile_drag_position()
        # Dear ImGui may trickle a burst of input over several frames. The
        # rendercanvas scheduler clears its draw flag before invoking us, so
        # request another frame only while unprocessed events remain.
        if not imgui.get_current_context().input_events_queue.empty():
            self.gui.request_draw()
        try:
            self.renderer._update_gui_function()
        finally:
            imgui.render()
        if self._close_frame_pending:
            # The pane observes its close in this frame; ImGui retires its
            # platform viewport after the pane is omitted in the next one.
            self._close_frame_pending = False
            self.gui.request_draw()
        if self.enabled:
            self._update_platform_windows()
        draw_data = imgui.get_draw_data()
        texture = context.get_current_texture()
        expected = (round(draw_data.display_size.x * draw_data.framebuffer_scale.x),
                    round(draw_data.display_size.y * draw_data.framebuffer_scale.y))
        if expected == (texture.width, texture.height):
            self._draw(draw_data, texture.create_view())
        else:
            # A resize raced this layout. Rebuild it for the next attachment
            # instead of issuing scissor rectangles outside the texture.
            self.gui.request_draw()
        if not self.enabled:
            return
        for viewport in imgui.get_platform_io().viewports:
            window = _window(viewport)
            if not window or _address(window) == _address(self.main):
                continue
            address = _address(window)
            self._install(window)
            if self._x11_policy:
                parent = imgui.find_viewport_by_id(viewport.parent_viewport_id)
                self._x11_policy.set_parent(window, _window(parent) if parent else None)
            size = glfw.get_framebuffer_size(window)
            if size[0] <= 0 or size[1] <= 0:
                continue
            surface = self.surfaces.get(address)
            if surface is None:
                surface = wgpu.gpu.get_canvas_context(get_glfw_present_info(window))
                surface.configure(device=self.renderer.backend._device, format=self.renderer.backend._target_format)
                self.surfaces[address] = surface
                # Creation and window-manager placement can happen after this
                # frame's layout, before our callbacks have been installed.
                self.gui.request_draw()
            surface.set_physical_size(*size)
            logical_size = glfw.get_window_size(window)
            draw_data = viewport.draw_data
            if not draw_data or logical_size[0] <= 0 or logical_size[1] <= 0:
                continue
            if (draw_data.display_size.x, draw_data.display_size.y) != logical_size:
                # The WM changed the client size after layout. Drawing it now
                # either stretches the old layout or exceeds the attachment.
                self.gui.request_draw()
                continue
            draw_data.framebuffer_scale = (
                size[0] / logical_size[0],
                size[1] / logical_size[1],
            )
            self._draw(viewport.draw_data, surface.get_current_texture().create_view())
            surface.present()

    def _draw(self, draw_data, view):
        device = self.renderer.backend._device
        encoder = device.create_command_encoder()
        render_pass = encoder.begin_render_pass(color_attachments=[{"view": view, "resolve_target": None, "clear_value": (0, 0, 0, 1), "load_op": wgpu.LoadOp.clear, "store_op": wgpu.StoreOp.store}])
        self.renderer.backend.render(draw_data, render_pass)
        render_pass.end()
        # Submit before the next viewport writes the backend's shared buffers.
        device.queue.submit([encoder.finish()])

    def close(self):
        self._retire_surfaces(tuple(self.surfaces))
        # Restore only the live main window; platform destruction owns secondary windows.
        window, callbacks = self.callbacks.pop(_address(self.main))
        for setter, callback, previous in callbacks:
            setter(window, previous)
        if self.enabled:
            imgui.destroy_platform_windows()
        self.callbacks.clear()
        self.geometry.clear()
        self._drag_request = None
        imgui.backends.glfw_shutdown()
