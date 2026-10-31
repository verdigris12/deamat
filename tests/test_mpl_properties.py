"""Behavior coverage for the shared live inspector, without a GPU window."""

import pickle
from types import SimpleNamespace

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import numpy as np
import pytest

from deamat import mpl_properties
from deamat.mpl_properties import FigureInspector, available_fonts, set_text_group
from deamat.mpl_view import MPLView, load_trusted_figure


class InspectorUI:
    """Immediate-mode input driver; artist changes still use real Matplotlib."""

    InputTextFlags_ = SimpleNamespace(enter_returns_true=1)
    ChildFlags_ = SimpleNamespace(borders=1)

    def __init__(self, edits=None, expanded=False):
        self.edits = edits or {}
        self.messages = []
        self.expanded = expanded

    def _input(self, label, current, *args):
        if label in self.edits:
            return True, self.edits.pop(label)
        return False, current

    input_text = checkbox = combo = color_edit4 = _input

    def text_wrapped(self, text):
        self.messages.append(text)

    text_disabled = text_wrapped

    def push_id(self, value):
        pass

    def pop_id(self):
        pass

    def begin_child(self, *args):
        return True

    def end_child(self):
        pass

    def selectable(self, label, selected):
        return False, selected

    def tree_node(self, label):
        return False

    def separator_text(self, label):
        pass

    def collapsing_header(self, label):
        return self.expanded

    def is_item_active(self):
        return False

    def is_item_hovered(self):
        return False

    def button(self, label):
        return False


@pytest.fixture
def inspector_ui(monkeypatch):
    ui = InspectorUI()
    monkeypatch.setattr(mpl_properties, "imgui", ui)
    return ui


def test_idle_inspection_does_not_allocate_titles_or_mutate_figure(inspector_ui, monkeypatch):
    figure = Figure(figsize=(8.25, 4.75), dpi=117)
    figure.subplots().plot([1, 2], [3, 4])
    FigureCanvasAgg(figure).draw()
    inspector = FigureInspector()
    original_texts = tuple(figure.texts)
    calls = []
    monkeypatch.setattr(figure, "suptitle", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(figure, "set_size_inches", lambda *args, **kwargs: calls.append(args))
    for _ in range(25):
        assert not inspector.draw(figure)
    assert not calls
    assert tuple(figure.texts) == original_texts
    assert figure._suptitle is None
    assert not figure.stale
    np.testing.assert_allclose(figure.get_size_inches(), (8.25, 4.75))
    assert figure.dpi == 117


def test_suptitle_reuses_original_artist(inspector_ui):
    figure = Figure()
    inspector = FigureInspector()
    assert inspector.apply(figure, "suptitle", "First")
    title = figure._suptitle
    for value in ("", "Second", "", "Third"):
        assert inspector.apply(figure, "suptitle", value)
        inspector.draw(figure)
        assert figure._suptitle is title
    assert figure.texts == [title]
    assert title.get_text() == "Third"


def test_actual_ui_edit_and_visible_rejection(inspector_ui):
    figure = Figure()
    inspector = FigureInspector()
    inspector_ui.edits = {"Suptitle": "Live title"}
    assert inspector.draw(figure)
    assert figure._suptitle.get_text() == "Live title"
    dpi = figure.dpi
    inspector_ui.edits = {"DPI": "-2"}
    assert not inspector.draw(figure)
    assert figure.dpi == dpi
    inspector.draw(figure)
    assert any("Edit rejected: DPI" in message for message in inspector_ui.messages)


def test_tick_style_does_not_collapse_positions():
    figure = Figure()
    axes = figure.subplots()
    axes.set_xticks([0, 1, 2])
    FigureCanvasAgg(figure).draw()
    labels = axes.get_xticklabels()
    positions = [label.get_position() for label in labels]
    set_text_group(labels, "horizontalalignment", "right")
    set_text_group(labels, "fontsize", 16)
    assert [label.get_position() for label in labels] == positions
    assert all(label.get_horizontalalignment() == "right" for label in labels)
    assert all(label.get_fontsize() == 16 for label in labels)
    set_text_group([], "fontsize", 16)


@pytest.mark.parametrize("projection", ["rectilinear", "polar"])
def test_empty_ticks_and_polar_inspection(inspector_ui, projection):
    figure = Figure()
    axes = figure.add_subplot(projection=projection)
    axes.set_xticks([])
    axes.set_yticks([])
    FigureCanvasAgg(figure).draw()
    inspector = FigureInspector()
    inspector.draw(figure)
    inspector.selected = axes
    inspector_ui.expanded = True
    assert not inspector.draw(figure)
    assert len(axes.get_xticks()) == len(axes.get_yticks()) == 0
    assert inspector.apply(axes, "title", "Edited axes")
    assert axes.get_title() == "Edited axes"
    keys = {prop.key for prop in inspector.properties(axes)}
    assert ("xscale" in keys) is (projection != "polar")


def test_ticks_can_be_explicitly_emptied_from_ui(inspector_ui):
    figure = Figure()
    axes = figure.subplots()
    inspector = FigureInspector()
    inspector.draw(figure)
    inspector.selected = axes
    inspector_ui.expanded = True
    inspector_ui.edits = {"Tick positions (JSON; [] hides ticks)": "[]"}
    assert inspector.draw(figure)
    assert len(axes.get_xticks()) == 0


def test_shared_log_axes_limits_update_originals():
    figure = Figure()
    first, second = figure.subplots(2, sharex=True)
    first.plot([1, 2, 3], [2, 4, 6])
    inspector = FigureInspector()
    assert inspector.apply(first, "xscale", "log")
    assert inspector.apply(first, "xlim", [1, 20])
    assert second.get_xscale() == "log"
    np.testing.assert_allclose(second.get_xlim(), (1, 20))
    assert not inspector.apply(second, "xlim", [-1, 2])
    np.testing.assert_allclose(first.get_xlim(), (1, 20))
    assert "positive" in inspector.error


def test_line_text_patch_legend_live_styles():
    figure = Figure()
    axes = figure.subplots()
    line, = axes.plot([0, 1], [1, 2], label="signal")
    patch = Rectangle((0, 0), 0.2, 0.3)
    axes.add_patch(patch)
    legend = axes.legend()
    inspector = FigureInspector()
    for artist, key, value in (
        (line, "linewidth", 3.5), (line, "linestyle", "--"),
        (line, "color", "red"), (line, "marker", "s"),
        (line, "markersize", 9), (axes.title, "text", "Result"),
        (axes.title, "fontweight", "bold"), (axes.title, "rotation", 12),
        (patch, "hatch", "//"), (patch, "facecolor", "cyan"),
        (legend, "loc", "lower left"), (legend, "title", "Legend title"),
        (legend.get_frame(), "alpha", 0.4),
    ):
        assert inspector.apply(artist, key, value), inspector.error
    assert line.get_linewidth() == 3.5
    assert line.get_marker() == "s"
    assert line.get_color() == "red"
    assert axes.get_title() == "Result"
    assert axes.title.get_fontweight() == "bold"
    assert patch.get_hatch() == "//"
    assert patch.get_facecolor() == to_rgba("cyan")
    assert legend.get_title().get_text() == "Legend title"
    assert legend.get_frame().get_alpha() == 0.4
    FigureCanvasAgg(figure).draw()


def test_scatter_and_image_styles_preserve_data():
    figure = Figure()
    axes = figure.subplots()
    scatter = axes.scatter([0, 1], [1, 2], c=[0.2, 0.8])
    image = axes.imshow([[0, 1], [2, 3]])
    offsets = scatter.get_offsets().copy()
    pixels = image.get_array().copy()
    inspector = FigureInspector()
    for artist, key, value in (
        (scatter, "sizes", [20, 80]), (scatter, "cmap", "plasma"),
        (scatter, "clim", [0, 1]), (scatter, "alpha", 0.5),
        (image, "cmap", "magma"), (image, "clim", [-1, 4]),
        (image, "interpolation", "nearest"), (image, "origin", "lower"),
    ):
        assert inspector.apply(artist, key, value), inspector.error
    np.testing.assert_allclose(scatter.get_sizes(), [20, 80])
    np.testing.assert_array_equal(scatter.get_offsets(), offsets)
    np.testing.assert_array_equal(image.get_array(), pixels)
    assert image.origin == "lower"
    assert image.get_clim() == (-1, 4)
    literal = axes.scatter([2], [2], color="red")
    assert inspector.apply(literal, "facecolor", ["blue"])
    np.testing.assert_allclose(literal.get_facecolor(), [to_rgba("blue")])
    FigureCanvasAgg(figure).draw()


@pytest.mark.parametrize("key,value", [("linewidth", -1), ("alpha", 2), ("color", "not-a-color"), ("marker", "not-a-marker"), ("linestyle", "not-a-style")])
def test_invalid_line_edits_preserve_artist(key, value):
    figure = Figure()
    line, = figure.subplots().plot([1, 2], [3, 4], marker="o", linewidth=2)
    inspector = FigureInspector()
    old = getattr(line, f"get_{key}")()
    assert not inspector.apply(line, key, value)
    assert inspector.error
    assert getattr(line, f"get_{key}")() == old


def test_invalid_collection_and_figure_values_preserve_state():
    figure = Figure(figsize=(7, 4))
    scatter = figure.subplots().scatter([0, 1], [1, 2], s=[5, 10], c=[0, 1])
    inspector = FigureInspector()
    assert not inspector.apply(figure, "size", [0, 4])
    np.testing.assert_allclose(figure.get_size_inches(), [7, 4])
    assert not inspector.apply(scatter, "sizes", [1, -1])
    np.testing.assert_allclose(scatter.get_sizes(), [5, 10])
    old = scatter.get_clim()
    assert not inspector.apply(scatter, "clim", [2, 1])
    assert scatter.get_clim() == old
    assert not inspector.apply(scatter, "cmap", "unknown-map")


def test_font_inventory_is_cached():
    assert available_fonts() is available_fonts()


@pytest.mark.parametrize("format,signature", [("png", b"\x89PNG"), ("pdf", b"%PDF"), ("svg", b"<?xml")])
def test_file_export_writes_real_format(tmp_path, format, signature):
    viewer = MPLView.__new__(MPLView)
    figure = Figure(figsize=(3, 2))
    figure.subplots().plot([0, 1], [1, 0])
    viewer.state = SimpleNamespace(fig=figure, error="", status="")
    path = viewer.export(tmp_path / "export", format)
    assert path.suffix == f".{format}"
    assert path.read_bytes().startswith(signature)
    np.testing.assert_allclose(figure.get_size_inches(), [3, 2])


def test_trusted_pickle_round_trip_and_type_validation(tmp_path):
    viewer = MPLView.__new__(MPLView)
    figure = Figure(figsize=(9, 3), dpi=123)
    figure.subplots().plot([0, 1], [1, 0])
    viewer.state = SimpleNamespace(fig=figure, error="", status="")
    path = viewer.save_pickle(tmp_path / "figure")
    restored = load_trusted_figure(path)
    np.testing.assert_allclose(restored.get_size_inches(), [9, 3])
    assert restored.dpi == 123
    assert len(restored.axes[0].lines) == 1
    bad = tmp_path / "not-figure.pkl"
    bad.write_bytes(pickle.dumps({"not": "a figure"}))
    with pytest.raises(TypeError, match="Expected a matplotlib Figure"):
        load_trusted_figure(bad)


def test_invalid_mathtext_rejected_before_live_title_changes():
    figure = Figure()
    axes = figure.subplots()
    axes.set_title("Original")
    inspector = FigureInspector()
    assert not inspector.apply(axes, "title", r"$\notacommand{broken}$")
    assert axes.get_title() == "Original"
    assert inspector.error
    FigureCanvasAgg(figure).draw()


def test_layout_switch_rejection_preserves_existing_engine():
    figure = Figure(layout="constrained")
    axes = figure.subplots()
    image = axes.imshow([[0, 1], [2, 3]])
    figure.colorbar(image, ax=axes)
    engine = figure.get_layout_engine()
    inspector = FigureInspector()
    assert not inspector.apply(figure, "layout", "tight")
    assert figure.get_layout_engine() is engine
    assert "compatible" in inspector.error
