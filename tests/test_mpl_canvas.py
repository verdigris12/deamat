"""Behavior regressions use real Agg/navigation with a recording GPU boundary."""

from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from matplotlib.backend_bases import MouseButton
from matplotlib.figure import Figure
from PIL import Image

from deamat.guistate import GUIState
from deamat.mpl_canvas import FigureView, _handle_input, _view_id, get_figure_view
from deamat.widgets.figure import _resolve_figure


def recording_gui():
    textures = []
    backend = Mock()
    backend.register_texture.side_effect = lambda texture: object()
    device = Mock()

    def create_texture(**kwargs):
        texture = Mock()
        texture.dimensions = kwargs["size"]
        textures.append(texture)
        return texture

    device.create_texture.side_effect = create_texture
    cleanups = []
    return SimpleNamespace(
        renderer=SimpleNamespace(device=device),
        gui_renderer=SimpleNamespace(backend=backend),
        request_draw=Mock(), add_cleanup=cleanups.append,
        add_input_handler=Mock(), remove_input_handler=Mock(),
        get_pixel_ratio=Mock(return_value=1),
        cleanups=cleanups, textures=textures,
    )


class TestFigureCanvas(unittest.TestCase):
    def setUp(self):
        self.gui = recording_gui()
        self.figure = Figure(figsize=(4, 3), dpi=100)
        self.axes = self.figure.subplots()
        self.line, = self.axes.plot([1, 2, 3], [2, 4, 3])
        self.view = get_figure_view(self.gui, "plot", self.figure)
        self.addCleanup(self.view.close)
        self.view.render()

    def center(self, axes=None):
        return tuple((axes or self.axes).bbox.get_points().mean(axis=0))

    def test_static_frames_and_stale_artist_changes(self):
        queue = self.gui.renderer.device.queue
        with patch.object(self.view.canvas, "draw", wraps=self.view.canvas.draw) as draw:
            texture, size = self.view.render()
            self.view.render()
            self.assertEqual(size, (400, 300))
            self.assertEqual(draw.call_count, 0)
            self.assertEqual(queue.write_texture.call_count, 1)
            self.line.set_color("red")
            changed_texture, _ = self.view.render()
            self.assertIs(texture, changed_texture)
            self.assertEqual(draw.call_count, 1)
            self.assertEqual(queue.write_texture.call_count, 2)
            self.view.invalidate()
            self.view.render()
            self.assertEqual(draw.call_count, 2)

    def test_fit_preserves_intrinsic_size_aspect_and_export_dimensions(self):
        _, size = self.view.render(size=(700, 450), fit=True, pixel_ratio=2)
        self.assertEqual(size, (600, 450))
        self.assertEqual(self.gui.textures[-1].dimensions, (1200, 900, 1))
        self.assertEqual(self.figure.dpi, 100)
        np.testing.assert_allclose(self.figure.get_size_inches(), [4, 3])
        output = BytesIO()
        self.figure.savefig(output, format="png", dpi=100)
        output.seek(0)
        with Image.open(output) as image:
            self.assertEqual(image.size, (400, 300))
        self.view.render(fit=False, pixel_ratio=2)
        np.testing.assert_allclose(self.figure.get_size_inches(), [4, 3])
        self.assertEqual(self.gui.textures[-1].dimensions, (800, 600, 1))
        self.figure.set_size_inches(6, 4)
        self.view.render(size=(500, 200), fit=True)
        np.testing.assert_allclose(self.figure.get_size_inches(), [6, 4])
        self.view.render(fit=False)
        np.testing.assert_allclose(self.figure.get_size_inches(), [6, 4])
        self.assertTrue(self.gui.textures[0].destroy.called)

    def test_pan_release_outside_records_final_position_and_history(self):
        initial = self.axes.get_xlim()
        x, y = self.center()
        self.view.mouse_event("button_press_event", x, y, button=MouseButton.LEFT)
        self.view.mouse_event("motion_notify_event", x + 20, y)
        intermediate = self.axes.get_xlim()
        self.view.mouse_event("button_release_event", x + 500, y, button=MouseButton.LEFT)
        final = self.axes.get_xlim()
        self.assertNotEqual(initial, intermediate)
        self.assertNotEqual(intermediate, final)
        self.assertFalse(self.view._pressed)
        self.view.back()
        np.testing.assert_allclose(self.axes.get_xlim(), initial)
        self.view.forward()
        np.testing.assert_allclose(self.axes.get_xlim(), final)
        self.view.home()
        np.testing.assert_allclose(self.axes.get_xlim(), initial)

    def test_native_releases_captured_drag_outside_image(self):
        initial = self.axes.get_xlim()
        x, y = self.center()
        self.view.mouse_event("button_press_event", x, y, button=MouseButton.LEFT)
        io = SimpleNamespace(key_ctrl=False, key_alt=False, key_shift=False,
                             key_super=False, mouse_wheel=0)
        with patch.multiple(
            "deamat.mpl_canvas.imgui",
            get_io=Mock(return_value=io),
            is_item_hovered=Mock(return_value=False),
            get_mouse_pos=Mock(return_value=SimpleNamespace(x=500, y=150)),
            is_key_down=Mock(return_value=False),
            set_next_frame_want_capture_mouse=Mock(),
        ):
            _handle_input(self.view, SimpleNamespace(x=0, y=0), (400, 300))
        intermediate = self.axes.get_xlim()
        self.view._native_event({"event_type": "pointer_up", "button": 1,
                                 "x": 650, "y": 150, "modifiers": ()})
        self.assertFalse(self.view._pressed)
        self.assertNotEqual(self.axes.get_xlim(), initial)
        self.assertNotEqual(self.axes.get_xlim(), intermediate)
        self.view.back()
        np.testing.assert_allclose(self.axes.get_xlim(), initial)

    def test_detached_native_release_uses_screen_coordinates_and_button_mapping(self):
        events = []
        self.view.canvas.mpl_connect("button_release_event", events.append)
        self.view._origin = (800, 400)
        self.view._display_size = (200, 150)
        self.view.mouse_event("button_press_event", 100, 100, button=MouseButton.RIGHT)
        self.view._native_event({"event_type": "pointer_up", "button": 2,
                                 "x": 950, "y": 450, "modifiers": ()})
        self.assertEqual(events[-1].button, MouseButton.RIGHT)
        self.assertEqual((events[-1].x, events[-1].y), (300, 200))
        self.assertFalse(self.view._pressed)

    def test_focus_loss_releases_hidden_capture_without_upload(self):
        events = []
        self.view.canvas.mpl_connect("key_release_event", events.append)
        self.view._keys["left"] = "ctrl+left"
        self.view.mouse_event("button_press_event", *self.center(), button=MouseButton.LEFT)
        self.view._native_event({"event_type": "focus_out"})
        self.assertFalse(self.view._pressed)
        self.assertEqual([event.key for event in events], ["ctrl+left"])
        self.assertFalse(self.view._keys)

    def test_detached_move_reuses_agg_upload_and_ratio_changes_density(self):
        from deamat.mpl_canvas import draw_figure

        origin = SimpleNamespace(x=800, y=400)
        queue = self.gui.renderer.device.queue
        with patch("deamat.mpl_canvas._handle_input"), patch.multiple(
            "deamat.mpl_canvas.imgui",
            push_id=Mock(), pop_id=Mock(), image=Mock(), set_cursor_screen_pos=Mock(),
            invisible_button=Mock(), get_cursor_screen_pos=Mock(return_value=origin),
        ):
            draw_figure(self.gui, "plot", self.figure, size=(400, 300), toolbar=False)
            self.assertEqual(queue.write_texture.call_count, 1)
            origin.x, origin.y = 1200, 600
            draw_figure(self.gui, "plot", self.figure, size=(400, 300), toolbar=False)
            self.assertEqual(queue.write_texture.call_count, 1)
            self.gui.get_pixel_ratio.return_value = 2
            draw_figure(self.gui, "plot", self.figure, size=(400, 300), toolbar=False)
            self.assertEqual(queue.write_texture.call_count, 2)
            self.assertEqual(self.view._texture_size, (800, 600))
            self.assertIs(self.view.figure, self.figure)

    def test_rectangle_zoom_preserves_data(self):
        xdata = self.line.get_xdata().copy()
        ydata = self.line.get_ydata().copy()
        before = self.axes.get_xlim()
        self.view.set_mode("zoom")
        x0, y0, x1, y1 = self.axes.bbox.extents
        self.view.mouse_event("button_press_event", x0 + 40, y0 + 30, button=MouseButton.LEFT)
        self.view.mouse_event("button_release_event", x1 - 40, y1 - 30, button=MouseButton.LEFT)
        after = self.axes.get_xlim()
        self.assertLess(after[1] - after[0], before[1] - before[0])
        np.testing.assert_array_equal(self.line.get_xdata(), xdata)
        np.testing.assert_array_equal(self.line.get_ydata(), ydata)
        self.view.home()
        np.testing.assert_allclose(self.axes.get_xlim(), before)

    def test_wheel_anchor_log_inverted_and_shared_axes(self):
        self.axes.set_xscale("log")
        self.axes.set_xlim(100, 1)
        twin = self.axes.twinx()
        twin.set_ylim(1, 100)
        self.view.render()
        initial = self.axes.get_xlim()
        x0, y0, x1, y1 = self.axes.bbox.extents
        x, y = x0 + (x1 - x0) * .3, (y0 + y1) / 2
        data = self.axes.transData.inverted().transform((x, y))
        self.view.mouse_event("scroll_event", x, y, step=1)
        after = self.axes.get_xlim()
        self.assertGreater(after[0], after[1])
        self.assertLess(abs(np.log(after[1] / after[0])), abs(np.log(initial[1] / initial[0])))
        np.testing.assert_allclose(twin.get_xlim(), after)
        np.testing.assert_allclose(self.axes.transData.transform(data)[0], x, atol=2)
        self.view.back()
        np.testing.assert_allclose(self.axes.get_xlim(), initial)
        self.view.forward()
        np.testing.assert_allclose(self.axes.get_xlim(), after)
        self.view.mouse_event("scroll_event", x, y, step=-1)
        self.assertGreater(abs(np.log(self.axes.get_xlim()[1] / self.axes.get_xlim()[0])),
                           abs(np.log(after[1] / after[0])))

    def test_mouse_callbacks_receive_real_events(self):
        events = []
        self.view.canvas.mpl_connect("button_press_event", events.append)
        x, y = self.center()
        self.view.mouse_event("button_press_event", x, y, button=MouseButton.LEFT)
        self.view.mouse_event("button_release_event", x, y, button=MouseButton.LEFT)
        self.assertEqual(len(events), 1)
        self.assertIs(events[0].inaxes, self.axes)
        self.assertIsNotNone(events[0].xdata)
        self.assertIs(events[0].canvas, self.view.canvas)

    def test_replacement_cleanup_and_control_ids(self):
        other_figure = Figure(figsize=(2, 2))
        other = get_figure_view(self.gui, "second", other_figure)
        self.addCleanup(other.close)
        ids = []
        with patch("deamat.mpl_canvas.imgui.push_id", side_effect=ids.append), patch("deamat.mpl_canvas.imgui.pop_id"):
            with _view_id(self.view):
                pass
            with _view_id(other):
                pass
        self.assertNotEqual(ids[0], ids[1])
        self.assertIs(get_figure_view(self.gui, "plot", self.figure), self.view)
        original_canvas = self.view._previous_canvas
        replacement = get_figure_view(self.gui, "plot", Figure())
        self.assertTrue(self.view.closed)
        self.assertIs(self.figure.canvas, original_canvas)
        self.assertEqual(self.gui.textures[0].destroy.call_count, 1)
        self.view.close()
        self.assertEqual(self.gui.textures[0].destroy.call_count, 1)
        self.assertEqual(len(self.gui.cleanups), 1)
        self.gui.cleanups[0]()
        self.assertTrue(other.closed)
        self.assertTrue(replacement.closed)
        self.assertEqual(self.gui._mpl_figure_views, {})

    def test_polar_navigation_uses_matplotlib_capabilities(self):
        figure = Figure()
        axes = figure.add_subplot(projection="polar")
        axes.plot([0, 1, 2], [1, 2, 3])
        view = FigureView(self.gui, "polar", figure)
        self.addCleanup(view.close)
        view.render()
        x, y = axes.transData.transform((1, 1))
        view.mouse_event("scroll_event", x, y, step=1)
        self.assertFalse(axes.can_zoom())
        self.assertFalse(view._pressed)


class TestLazyEmbeddedFigure(unittest.TestCase):
    def test_factory_dimensions_invalidation_resize_and_removal(self):
        state = GUIState()
        gui = recording_gui()
        calls = []

        def factory(current):
            entry = current.figures["data"]
            calls.append((entry["width"], entry["height"]))
            figure = Figure()
            figure.subplots().plot([1, 2], [3, 4])
            return figure

        state.add_figure("data", factory, width=0, height=0)
        self.assertEqual(calls, [])
        with patch("deamat.widgets.figure.imgui.get_content_region_avail", return_value=SimpleNamespace(x=480, y=320)):
            entry, view = _resolve_figure(gui, state, "data", None, None, False)
            self.assertEqual(calls, [(480, 320)])
            first = entry["figure"]
            view.render(size=(entry["width"], entry["height"]), fit=True)
            _, same = _resolve_figure(gui, state, "data", 600, 400, False)
            self.assertIs(same, view)
            self.assertIs(entry["figure"], first)
            self.assertEqual(len(calls), 1)
            state.invalidate_figure("data")
            _, updated = _resolve_figure(gui, state, "data", None, None, False)
            self.assertEqual(calls, [(480, 320), (600, 400)])
            self.assertTrue(view.closed)
            self.assertIsNot(updated.figure, first)
            state.remove_figure("data")
            self.assertTrue(updated.closed)
            self.assertNotIn("data", gui._mpl_figure_views)

    def test_gui_cleanup_removes_owned_state_figure(self):
        state = GUIState()
        gui = recording_gui()
        state.add_figure("owned", lambda current: Figure(), width=400, height=300)
        with patch("deamat.widgets.figure.imgui.get_content_region_avail", return_value=SimpleNamespace(x=400, y=300)):
            _, view = _resolve_figure(gui, state, "owned", None, None, False)
        for cleanup in reversed(gui.cleanups):
            cleanup()
        self.assertTrue(view.closed)
        self.assertNotIn("owned", state.figures)
