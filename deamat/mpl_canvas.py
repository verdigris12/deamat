"""Retained Agg textures and Matplotlib navigation shared by all figure viewers."""

from contextlib import contextmanager

from imgui_bundle import imgui
from matplotlib.backend_bases import Event, KeyEvent, MouseButton, MouseEvent, NavigationToolbar2
from matplotlib.backends.backend_agg import FigureCanvasAgg


class _Canvas(FigureCanvasAgg):
    def __init__(self, figure, view):
        self.view = view
        self.connections = set()
        super().__init__(figure)

    def draw_idle(self, *args, **kwargs):
        self.view.invalidate()

    def draw(self):
        super().draw()
        if not self.view._rendering:
            self.view.invalidate()

    def mpl_connect(self, event, callback):
        connection = super().mpl_connect(event, callback)
        self.connections.add(connection)
        return connection

    def mpl_disconnect(self, connection):
        self.connections.discard(connection)
        super().mpl_disconnect(connection)


class _Toolbar(NavigationToolbar2):
    def set_message(self, message):
        self.canvas.view.status = message

    def draw_rubberband(self, event, x0, y0, x1, y1):
        self.canvas.view.rubberband = (x0, y0, x1, y1)

    def remove_rubberband(self):
        self.canvas.view.rubberband = None


class FigureView:
    """One figure's navigation, input capture and lazily uploaded texture.

    ``render`` accepts logical pixels. HiDPI rasterization does not change the
    figure's public DPI or intrinsic size. User artist callbacks receive normal
    Matplotlib events in the figure's logical display coordinates.
    """

    def __init__(self, gui, fig_id, figure):
        self.gui = gui
        self.fig_id = fig_id
        self.figure = figure
        self.closed = False
        self.status = ""
        self.rubberband = None
        self._dirty = True
        self._rendering = False
        self._texture = None
        self._pixel_ratio = None
        self._pressed = set()
        self._last_mouse = None
        self._hovered = False
        self._keys = {}
        self._origin = (0, 0)
        self._display_size = (1, 1)
        self._previous_canvas = figure.canvas
        self._previous_stale_callback = figure.stale_callback
        self.canvas = _Canvas(figure, self)
        self.toolbar = _Toolbar(self.canvas)
        self._stale_callback = self._on_stale
        figure.stale_callback = self._stale_callback
        gui.add_input_handler(self._native_event, "pointer_up", "key_up", "focus_out")
        self.set_mode("pan")

    def _on_stale(self, artist, stale):
        if stale and not self._rendering:
            self.invalidate()

    def invalidate(self):
        if not self.closed:
            self._dirty = True
            self.gui.request_draw()

    @property
    def mode(self):
        return self.toolbar.mode.name.lower()

    def set_mode(self, mode):
        if mode not in {"pan", "zoom", "none"}:
            raise ValueError("Navigation mode must be pan, zoom, or none")
        if self.mode == mode:
            return
        if mode == "pan":
            self.toolbar.pan()
        elif mode == "zoom":
            self.toolbar.zoom()
        elif self.mode == "pan":
            self.toolbar.pan()
        elif self.mode == "zoom":
            self.toolbar.zoom()

    def home(self):
        self.toolbar.home()

    def back(self):
        self.toolbar.back()

    def forward(self):
        self.toolbar.forward()

    def _native_event(self, event):
        if self.closed:
            return
        kind = event["event_type"]
        if kind == "focus_out":
            self._release_input()
        elif kind == "pointer_up":
            button = {1: MouseButton.LEFT, 2: MouseButton.RIGHT, 3: MouseButton.MIDDLE}.get(event["button"])
            if button not in self._pressed:
                return
            width, height = self.figure.bbox.size
            x = (event["x"] - self._origin[0]) * width / self._display_size[0]
            y = (1 - (event["y"] - self._origin[1]) / self._display_size[1]) * height
            modifiers = {"Control": "ctrl", "Alt": "alt", "Shift": "shift", "Meta": "super"}
            key = "+".join(modifiers[m] for m in event.get("modifiers", ()) if m in modifiers) or None
            self.mouse_event("button_release_event", x, y, button=button, key=key)
            self._last_mouse = (x, y)
        elif kind == "key_up":
            name = event["key"].lower().replace("arrow", "")
            if name == "space":
                name = " "
            key = self._keys.pop(name, None)
            if key is not None:
                x, y = self._last_mouse or (0, 0)
                self.canvas.callbacks.process("key_release_event", KeyEvent("key_release_event", self.canvas, key, x, y))

    def _release_input(self):
        x, y = self._last_mouse or (0, 0)
        for button in tuple(self._pressed):
            self.mouse_event("button_release_event", x, y, button=button)
        for key in self._keys.values():
            self.canvas.callbacks.process("key_release_event", KeyEvent("key_release_event", self.canvas, key, x, y))
        self._keys.clear()

    def mouse_event(self, name, x, y, *, button=None, step=0, key=None, dblclick=False):
        """Forward an event, retaining capture until release even outside axes."""
        if name == "button_press_event":
            self._pressed.add(button)
        elif name == "button_release_event":
            # Matplotlib pan release records history but does not apply the
            # last pointer position itself. Deliver it before releasing.
            self.mouse_event("motion_notify_event", x, y, key=key)
            self._pressed.discard(button)
        event = MouseEvent(
            name, self.canvas, x, y, button=button, step=step, key=key,
            dblclick=dblclick,
            buttons=self._pressed if name == "motion_notify_event" else None,
        )
        self.canvas.callbacks.process(name, event)
        if name == "scroll_event" and not self._pressed:
            self._wheel_zoom(event)
        return event

    def _wheel_zoom(self, event):
        ax = event.inaxes
        if not event.step or ax is None or not ax.get_navigate() or not ax.can_zoom():
            return
        # Use the public rectangle-zoom lifecycle, including its shared/twin
        # axes handling, scale transforms and history. A cursor-anchored
        # rectangle is equally valid on linear, log and inverted axes.
        fraction = 1.2 ** (-abs(event.step))
        x0, y0, x1, y1 = ax.bbox.extents
        left = event.x + (x0 - event.x) * fraction
        right = event.x + (x1 - event.x) * fraction
        bottom = event.y + (y0 - event.y) * fraction
        top = event.y + (y1 - event.y) * fraction
        button = MouseButton.LEFT if event.step > 0 else MouseButton.RIGHT
        start = MouseEvent("button_press_event", self.canvas, left, bottom, button=button, key=event.key)
        end = MouseEvent("button_release_event", self.canvas, right, top, button=button, key=event.key)
        self.toolbar.press_zoom(start)
        self.toolbar.release_zoom(end)

    def render(self, *, size=None, fit=False, pixel_ratio=1.0):
        """Return (texture reference, logical image size), reusing static frames."""
        if self.closed:
            raise RuntimeError("Cannot render a closed FigureView")
        if pixel_ratio <= 0:
            raise ValueError("pixel_ratio must be positive")
        logical_size = tuple(float(value) for value in self.figure.bbox.size)
        if fit and size is not None:
            scale = min(size[0] / logical_size[0], size[1] / logical_size[1])
            logical_size = tuple(value * scale for value in logical_size)
            pixel_ratio *= scale
        if self._pixel_ratio != pixel_ratio:
            self._dirty = True
            self._pixel_ratio = pixel_ratio
        if not self._dirty and not self.figure.stale:
            return self._texture.ref, logical_size
        dpi = self.figure.dpi
        self._rendering = True
        try:
            if pixel_ratio != 1:
                self.figure.set_dpi(dpi * pixel_ratio)
            self.canvas.draw()
            rgba = self.canvas.buffer_rgba()
        finally:
            if self.figure.dpi != dpi:
                self.figure.set_dpi(dpi)
            self._rendering = False
        # Restoring DPI marks the figure stale; the uploaded render already
        # represents this figure at the requested pixel density.
        self.figure.stale = False
        if self._texture is None:
            self._texture = self.gui.create_image(rgba)
        else:
            self._texture.update(rgba)
        self._dirty = False
        return self._texture.ref, logical_size

    def _dispose_texture(self):
        if self._texture is not None:
            self._texture.close()
            self._texture = None

    def close(self):
        """Detach input and release GPU resources; the caller owns the Figure."""
        if self.closed:
            return
        self._release_input()
        self.gui.remove_input_handler(self._native_event, "pointer_up", "key_up", "focus_out")
        self.set_mode("none")
        self.closed = True
        for connection in tuple(self.canvas.connections):
            self.canvas.mpl_disconnect(connection)
        self._dispose_texture()
        if self.figure.canvas is self.canvas:
            self.figure.set_canvas(self._previous_canvas)
        if self.figure.stale_callback == self._stale_callback:
            self.figure.stale_callback = self._previous_stale_callback


@contextmanager
def _view_id(view):
    imgui.push_id(f"mpl-view-{id(view)}")
    try:
        yield
    finally:
        imgui.pop_id()


def dispose_figure_view(gui, fig_id):
    view = getattr(gui, "_mpl_figure_views", {}).pop(fig_id, None)
    if view is not None:
        view.close()


def dispose_figure_views(gui):
    for fig_id in tuple(getattr(gui, "_mpl_figure_views", {})):
        dispose_figure_view(gui, fig_id)


def get_figure_view(gui, fig_id, figure):
    """Get a retained view, replacing and disposing it when its figure changes."""
    if not hasattr(gui, "_mpl_figure_views"):
        gui._mpl_figure_views = {}
        gui.add_cleanup(lambda: dispose_figure_views(gui))
    view = gui._mpl_figure_views.get(fig_id)
    if view is None or view.figure is not figure or view.closed:
        dispose_figure_view(gui, fig_id)
        view = FigureView(gui, fig_id, figure)
        gui._mpl_figure_views[fig_id] = view
    return view


def _draw_toolbar(view):
    for label, action in (("Home", view.home), ("Back", view.back), ("Forward", view.forward)):
        if imgui.button(label):
            action()
        imgui.same_line()
    for mode, label in (("pan", "Pan"), ("zoom", "Zoom")):
        changed, enabled = imgui.checkbox(label, view.mode == mode)
        if changed:
            view.set_mode(mode if enabled else "none")
        if mode == "pan":
            imgui.same_line()


def _modifier_key(io):
    keys = []
    if io.key_ctrl:
        keys.append("ctrl")
    if io.key_alt:
        keys.append("alt")
    if io.key_shift:
        keys.append("shift")
    if io.key_super:
        keys.append("super")
    # Matplotlib pan constraints accept an unmodified x or y.
    for key in ("x", "y"):
        if imgui.is_key_down(getattr(imgui.Key, key)):
            keys.append(key)
    return "+".join(keys) or None


def _handle_input(view, origin, display_size):
    io = imgui.get_io()
    view._origin = (origin.x, origin.y)
    view._display_size = display_size
    hovered = imgui.is_item_hovered()
    if hovered != view._hovered:
        name = "figure_enter_event" if hovered else "figure_leave_event"
        view.canvas.callbacks.process(name, Event(name, view.canvas))
        view._hovered = hovered
    mouse = imgui.get_mouse_pos()
    width, height = view.figure.bbox.size
    x = (mouse.x - origin.x) * width / display_size[0]
    y = (1 - (mouse.y - origin.y) / display_size[1]) * height
    key = _modifier_key(io)
    if hovered or view._pressed:
        if view._last_mouse != (x, y):
            view.mouse_event("motion_notify_event", x, y, key=key)
            view._last_mouse = (x, y)
        for index, button in ((0, MouseButton.LEFT), (1, MouseButton.RIGHT), (2, MouseButton.MIDDLE)):
            if hovered and imgui.is_mouse_clicked(index):
                view.mouse_event("button_press_event", x, y, button=button, key=key,
                                 dblclick=imgui.is_mouse_double_clicked(index))
            # Native release can precede ImGui's queued press; only release
            # here if native input has not already cleared the capture.
            if button in view._pressed and not imgui.is_mouse_down(index):
                view.mouse_event("button_release_event", x, y, button=button, key=key)
        if hovered and io.mouse_wheel:
            view.mouse_event("scroll_event", x, y, step=io.mouse_wheel, key=key)
        if view._pressed:
            imgui.set_next_frame_want_capture_mouse(True)
    if hovered:
        imgui.set_item_key_owner(imgui.Key.mouse_wheel_y)
        for name in ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
                     "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
                     "left_arrow", "right_arrow", "up_arrow", "down_arrow", "escape", "enter", "space"):
            code = getattr(imgui.Key, name)
            mpl_key = name.removesuffix("_arrow")
            if name == "space":
                mpl_key = " "
            modifiers = "+".join(part for part in ("ctrl" if io.key_ctrl else "", "alt" if io.key_alt else "",
                                                   "shift" if io.key_shift else "", "super" if io.key_super else "") if part)
            if modifiers:
                mpl_key = modifiers + "+" + mpl_key
            if imgui.is_key_pressed(code, False):
                view._keys[mpl_key.split("+")[-1]] = mpl_key
                view.canvas.callbacks.process("key_press_event", KeyEvent("key_press_event", view.canvas, mpl_key, x, y))
    for name, mpl_key in tuple(view._keys.items()):
        imgui_name = (name + "_arrow" if name in ("left", "right", "up", "down")
                      else "space" if name == " " else name)
        if imgui.is_key_released(getattr(imgui.Key, imgui_name)):
            del view._keys[name]
            view.canvas.callbacks.process("key_release_event", KeyEvent("key_release_event", view.canvas, mpl_key, x, y))


def draw_figure(gui, fig_id, figure, *, size=None, fit=False, toolbar=True):
    """Draw the shared navigation toolbar and image, returning its retained view."""
    view = get_figure_view(gui, fig_id, figure)
    with _view_id(view):
        start_y = imgui.get_cursor_screen_pos().y
        if toolbar:
            _draw_toolbar(view)
        if size is None:
            available = imgui.get_content_region_avail()
            size = (available.x, available.y)
        elif toolbar:
            size = (size[0], max(1, size[1] - (imgui.get_cursor_screen_pos().y - start_y)))
        texture, display_size = view.render(size=size, fit=fit, pixel_ratio=gui.get_pixel_ratio())
        origin = imgui.get_cursor_screen_pos()
        imgui.image(texture, imgui.ImVec2(*display_size))
        imgui.set_cursor_screen_pos(origin)
        imgui.invisible_button("canvas", imgui.ImVec2(*display_size),
                               imgui.ButtonFlags_.mouse_button_left | imgui.ButtonFlags_.mouse_button_right |
                               imgui.ButtonFlags_.mouse_button_middle)
        _handle_input(view, origin, display_size)
        if view.rubberband is not None:
            x0, y0, x1, y1 = view.rubberband
            width, height = figure.bbox.size
            p0 = (origin.x + min(x0, x1) / width * display_size[0],
                  origin.y + (1 - max(y0, y1) / height) * display_size[1])
            p1 = (origin.x + max(x0, x1) / width * display_size[0],
                  origin.y + (1 - min(y0, y1) / height) * display_size[1])
            imgui.get_window_draw_list().add_rect(p0, p1, imgui.get_color_u32(imgui.Col_.plot_lines))
    return view
