"""Retained pygfx views embedded in ImGui."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable
from weakref import ref

from imgui_bundle import imgui
import glfw


@contextmanager
def _wgpu_context(gui):
    """Release GLFW's GL context while wgpu owns the thread's GPU context."""
    glfw.make_context_current(None)
    try:
        yield
    finally:
        gui.make_current()

if TYPE_CHECKING:
    import pygfx as gfx


_INPUT_EVENTS = ("pointer_down", "pointer_move", "pointer_up", "wheel", "key_down", "key_up")


class PygfxCanvas:
    """Public scene/camera/renderer handle returned by :func:`pygfx_canvas`.

    The renderer remains stable across resizes, so its event handlers remain
    attached. Enable ``material.pick_write`` for object picking, then register
    pygfx click/hover handlers on objects, the scene, or ``renderer``. Coordinates
    are logical pixels relative to the image. ``close()`` releases this view;
    GUI shutdown also closes it. Set ``continuous=False`` on the widget for a
    static scene and call ``invalidate()`` after changing its contents.
    """

    def __init__(self, gui, canvas_id, size, pixel_ratio, camera=None):
        try:
            import pygfx as gfx
            import wgpu
            from pygfx.renderers.wgpu.engine.shared import Shared
            from rendercanvas.offscreen import RenderCanvas
        except ImportError as exc:
            raise ImportError("The pygfx widget requires the deamat pygfx extra: install deamat[pygfx]") from exc

        self._gfx = gfx
        self._wgpu = wgpu
        with _wgpu_context(gui):
            if Shared._instance is None:
                adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
                Shared._features = Shared._features & set(adapter.features)
            self._target = RenderCanvas(size=size, pixel_ratio=pixel_ratio)
            self.renderer = gfx.WgpuRenderer(self._target, pixel_scale=1, enable_events=False)
            self._context = self._target.get_context("wgpu")
            self._configure_target()
        self._gui = gui
        self._canvas_id = canvas_id
        self.scene = gfx.Scene()
        self._camera = camera if camera is not None else gfx.PerspectiveCamera(45, size[0] / size[1])
        self._controller = None
        self._owns_camera = False
        self._closed = False
        self._dirty = True
        self._inited = False
        self._buttons = set()
        self._keys = set()
        self._mouse_pos = None
        self._hovered = False
        self._image_pos = (0.0, 0.0)
        self._size = size
        self._pixel_ratio = pixel_ratio
        self._image = None
        self._viewport = gfx.Viewport(self.renderer)
        self.renderer.add_event_handler(self._controller_event, *_INPUT_EVENTS)
        gui.add_input_handler(self._native_event, "key_down", "key_up", "pointer_up", "focus_out")
        weak_view = ref(self)

        def cleanup():
            view = weak_view()
            if view is not None:
                view.close()

        gui.add_cleanup(cleanup)

    def _configure_target(self):
        self._context.configure(
            device=self.renderer.device,
            format="rgba8unorm",
            usage=(self._wgpu.TextureUsage.RENDER_ATTACHMENT | self._wgpu.TextureUsage.TEXTURE_BINDING |
                   self._wgpu.TextureUsage.COPY_SRC),
        )
        self._texture = self._context.get_current_texture()

    @property
    def camera(self):
        return self._camera

    @camera.setter
    def camera(self, camera):
        if not isinstance(camera, self._gfx.Camera):
            raise TypeError("camera must be a pygfx Camera")
        if camera is self._camera:
            return
        controller = self.controller
        self.controller = None
        self._camera = camera
        self.controller = controller
        self.invalidate()

    @property
    def controller(self):
        return self._controller

    @controller.setter
    def controller(self, controller):
        if controller is self._controller:
            return
        self._release_input()
        if self._controller is not None and self._owns_camera:
            self._controller.remove_camera(self.camera)
        self._controller = controller
        self._owns_camera = False
        if controller is not None and self.camera not in controller.cameras:
            controller.add_camera(self.camera)
            self._owns_camera = True
        # Do not re-add a caller-owned camera: that resets include/exclude filters.
        self.invalidate()

    def _controller_event(self, event):
        if self.controller is not None:
            self.controller.handle_event(event, self._viewport)

    def invalidate(self):
        """Request a redraw after a scene change (also wakes an on-demand GUI)."""
        if not self._closed:
            self._dirty = True
            self._gui.request_draw()

    def _dispatch(self, event_type, **event):
        with _wgpu_context(self._gui):
            self.renderer.convert_event({"event_type": event_type, **event})
        self.invalidate()

    def _native_event(self, event):
        # Native releases also reach a canvas whose ImGui window was collapsed
        # during a drag. Keyboard events preserve renderer key names/modifiers.
        kind = event["event_type"]
        if self._closed:
            return
        if kind == "focus_out":
            self._release_input()
        elif kind == "pointer_up":
            button = event["button"]
            if button in self._buttons:
                x = event["x"] - self._image_pos[0]
                y = event["y"] - self._image_pos[1]
                buttons = tuple(b for b in self._buttons if b != button)
                self._pointer_release(button, x, y, buttons, tuple(event.get("modifiers", ())))
        elif kind == "key_up" and event["key"] in self._keys:
            self._keys.remove(event["key"])
            self._dispatch(kind, key=event["key"], modifiers=event.get("modifiers", ()))
        elif kind == "key_down" and getattr(self._gui, "_pygfx_keyboard_view", None) is self:
            if not imgui.get_io().want_text_input:
                self._keys.add(event["key"])
                self._dispatch(kind, key=event["key"], modifiers=event.get("modifiers", ()))

    def _pointer_release(self, button, x, y, buttons, modifiers):
        # Controllers consume the final position on move, not on pointer_up.
        args = dict(x=x, y=y, buttons=buttons, modifiers=modifiers, pointer_id=0)
        self._dispatch("pointer_move", button=0, **args)
        self._dispatch("pointer_up", button=button, **args)
        self._buttons.discard(button)
        self._mouse_pos = (x, y)

    def _release_input(self):
        x, y = self._mouse_pos or (0, 0)
        for button in tuple(self._buttons):
            self._pointer_release(button, x, y, (), ())
        for key in tuple(self._keys):
            self._dispatch("key_up", key=key, modifiers=())
        self._keys.clear()

    def _resize(self, size, pixel_ratio):
        if (size, pixel_ratio) == (self._size, self._pixel_ratio):
            return
        with _wgpu_context(self._gui):
            self._texture.destroy()
            self._texture = None
            self._context.unconfigure()
            self._target.set_pixel_ratio(pixel_ratio)
            self._target.set_logical_size(*size)
            self._configure_target()
        self._size, self._pixel_ratio = size, pixel_ratio
        # set_view_size affects projection, never camera world extents or FOV.
        self.camera.set_view_size(*size)
        self.invalidate()

    def close(self):
        """Detach input handlers and release GPU registrations, idempotently."""
        if self._closed:
            return
        self.controller = None
        self._release_input()
        self._closed = True
        self.renderer.remove_event_handler(self._controller_event, *_INPUT_EVENTS)
        self._gui.remove_input_handler(self._native_event, "key_down", "key_up", "pointer_up", "focus_out")
        if getattr(self._gui, "_pygfx_keyboard_view", None) is self:
            self._gui._pygfx_keyboard_view = None
        if self._image is not None:
            self._image.close()
            self._image = None
        with _wgpu_context(self._gui):
            self._texture.destroy()
            self._texture = None
            self._context.unconfigure()
            self._target.close()
            # Pygfx has no renderer.close(); dropping it releases its internal buffers.
            self.renderer = self._viewport = self._context = self._target = None
        if self._gui._pygfx_scenes.get(self._canvas_id) is self:
            self._gui._pygfx_scenes.pop(self._canvas_id)
            self._gui.scenes.pop(self._canvas_id, None)


def _handle_imgui_events(view):
    io = imgui.get_io()
    mouse = imgui.get_mouse_pos()
    x, y = mouse.x - view._image_pos[0], mouse.y - view._image_pos[1]
    hovered = imgui.is_item_hovered()
    modifiers = tuple(name for enabled, name in (
        (io.key_shift, "Shift"), (io.key_ctrl, "Control"),
        (io.key_alt, "Alt"), (io.key_super, "Meta"),
    ) if enabled)
    buttons = tuple(n for n, button in ((1, imgui.MouseButton_.left), (2, imgui.MouseButton_.right), (3, imgui.MouseButton_.middle)) if imgui.is_mouse_down(button))
    args = dict(x=x, y=y, buttons=buttons, modifiers=modifiers, pointer_id=0)
    for n, button in ((1, imgui.MouseButton_.left), (2, imgui.MouseButton_.right), (3, imgui.MouseButton_.middle)):
        if hovered and imgui.is_mouse_clicked(button):
            previous = getattr(view._gui, "_pygfx_keyboard_view", None)
            if previous is not None and previous is not view:
                previous._release_input()
            view._gui._pygfx_keyboard_view = view
            view._buttons.add(n)
            view._dispatch("pointer_down", button=n, **args)
        # ImGui can deliver a queued press after the native release callback.
        # The captured set makes this fallback and native release mutually exclusive.
        if n in view._buttons and not imgui.is_mouse_down(button):
            view._pointer_release(n, x, y, buttons, modifiers)
    if (hovered or view._hovered or view._buttons) and (view._mouse_pos != (x, y) or hovered != view._hovered):
        # Send one out-of-bounds move on leaving, so pygfx emits pointer_leave.
        move_args = args if hovered or view._buttons else {**args, "x": -1, "y": -1}
        view._dispatch("pointer_move", button=0, **move_args)
    view._mouse_pos, view._hovered = (x, y), hovered
    if hovered and (io.mouse_wheel or io.mouse_wheel_h):
        # ImGui positive means up; rendercanvas/pygfx positive means down.
        view._dispatch("wheel", dx=-io.mouse_wheel_h * 100, dy=-io.mouse_wheel * 100, button=0, **args)


def pygfx_canvas(
    gui: Any,
    state: Any,
    canvas_id: str,
    on_init: Callable[[gfx.Scene, gfx.Camera], gfx.Camera | None] | None = None,
    controller: gfx.Controller | None = None,
    *,
    camera: gfx.Camera | None = None,
    continuous: bool = True,
) -> PygfxCanvas:
    """Draw a retained pygfx view and return its public :class:`PygfxCanvas`.

    ``camera`` selects an explicit camera; alternatively ``on_init(scene,
    camera)`` may return one. The callback runs once, before the first render.
    Passing ``controller=None`` detaches controls. Existing camera filters on
    caller-owned controllers are preserved. Continuous rendering is the default
    for animation; static callers can opt out and use ``handle.invalidate()``.
    Call only inside a visible ImGui window (check ``imgui.begin``'s result).
    """
    avail = imgui.get_content_region_avail()
    size = (max(1, int(avail.x)), max(1, int(avail.y)))
    pixel_ratio = gui.get_pixel_ratio()
    view = gui._pygfx_scenes.get(canvas_id)
    if view is None:
        view = PygfxCanvas(gui, canvas_id, size, pixel_ratio, camera)
        gui._pygfx_scenes[canvas_id] = view
        gui.scenes[canvas_id] = view.scene
    elif camera is not None:
        view.camera = camera
    if not view._inited and on_init is not None:
        replacement = on_init(view.scene, view.camera)
        if replacement is not None:
            view.camera = replacement
        view._inited = True
    view.controller = controller
    view._resize(size, pixel_ratio)
    view.camera.set_view_size(*size)
    pos = imgui.get_cursor_screen_pos()
    view._image_pos = (pos.x, pos.y)
    flags = imgui.ButtonFlags_.mouse_button_left | imgui.ButtonFlags_.mouse_button_right | imgui.ButtonFlags_.mouse_button_middle
    imgui.invisible_button(f"##{canvas_id}_input", imgui.ImVec2(*size), flags)
    _handle_imgui_events(view)
    changed = view.controller.tick() if view.controller is not None else None
    if continuous or view._dirty or changed is not None:
        view._dirty = False
        with _wgpu_context(gui):
            view.renderer.render(view.scene, view.camera)
            width, height, _ = view._texture.size
            pixels = view.renderer.device.queue.read_texture(
                {"texture": view._texture},
                {"bytes_per_row": width * 4, "rows_per_image": height},
                (width, height, 1),
            )
        import numpy as np
        rgba = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)
        if view._image is None:
            view._image = gui.create_image(rgba)
        else:
            view._image.update(rgba)
    # Drawing after the input item keeps the layout item and its focus intact.
    imgui.get_window_draw_list().add_image(view._image.ref, pos, imgui.ImVec2(pos.x + size[0], pos.y + size[1]))
    if continuous or changed is not None:
        gui.request_draw()
    return view
