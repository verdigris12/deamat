"""Native window dimensions and draw scheduling."""
import glfw


class NativeWindow:
    def __init__(self, gui):
        self.gui = gui

    def get_logical_size(self):
        return glfw.get_window_size(self.gui.window)

    def get_physical_size(self):
        return glfw.get_framebuffer_size(self.gui.window)

    def get_pixel_ratio(self):
        width, _ = self.get_logical_size()
        pixels, _ = self.get_physical_size()
        return pixels / width if width else 1.0

    def request_draw(self):
        self.gui.request_draw()

    def force_draw(self):
        self.gui._render_frame()
