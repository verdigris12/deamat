"""Typed, live Matplotlib properties shared by embedded and standalone views.

The inspector edits existing artists, not plotting data or arbitrary Python code.
Only explicit controls below are supported; custom transforms, arbitrary artist
subclasses and projection-specific geometry are intentionally not synthesized.
"""

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import json
from typing import Callable
import warnings

from imgui_bundle import imgui
import matplotlib as mpl
from matplotlib import cbook, colors, font_manager
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.collections import Collection, PathCollection
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
from matplotlib.layout_engine import ConstrainedLayoutEngine, PlaceHolderLayoutEngine, TightLayoutEngine
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.mathtext import MathTextParser
from matplotlib.patches import Patch
from matplotlib.text import Text
import numpy as np


@lru_cache(maxsize=1)
def available_fonts() -> tuple[str, ...]:
    """Inventory once, rather than scanning every text widget every frame."""
    return tuple(sorted({font.name for font in font_manager.fontManager.ttflist}))


@lru_cache(maxsize=1)
def _mathtext_parser():
    return MathTextParser("agg")


def _text(value):
    if not isinstance(value, str):
        raise ValueError("Text must be a string")
    if cbook.is_math_text(value):
        _mathtext_parser().parse(value)


def _finite(value):
    if not np.all(np.isfinite(value)):
        raise ValueError("Values must be finite")


def _positive(value):
    _finite(value)
    if np.any(np.asarray(value) <= 0):
        raise ValueError("Values must be greater than zero")


def _nonnegative(value):
    _finite(value)
    if np.any(np.asarray(value) < 0):
        raise ValueError("Values must not be negative")


def _alpha(value):
    if value is not None:
        _finite(value)
        if np.any((np.asarray(value) < 0) | (np.asarray(value) > 1)):
            raise ValueError("Alpha must be between 0 and 1, or null")


def _numeric_list(value):
    if not isinstance(value, (list, tuple, np.ndarray)) or np.asarray(value).ndim != 1:
        raise ValueError("Enter a JSON list of numbers, for example [0, 1, 2]")
    _finite(value)


def _pair(value):
    _numeric_list(value)
    if len(value) != 2:
        raise ValueError("Exactly two numbers are required")


def _limits(value):
    _pair(value)
    if value[0] == value[1]:
        raise ValueError("Limits must be different")


def _clim(value):
    _pair(value)
    if value[0] > value[1]:
        raise ValueError("Color minimum must not exceed maximum")


def _sizes(value):
    _numeric_list(value)
    _nonnegative(value)


def _aspect(value):
    if value not in ("auto", "equal"):
        _positive(float(value))


def _weight(value):
    if value.isdecimal():
        value = int(value)
    font_manager.FontProperties(weight=value)
    return value


def _font_families(value):
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise ValueError("Enter a nonempty JSON list of font family names")


def _scale(axes, direction, value):
    shared = getattr(axes, f"get_shared_{direction}_axes")().get_siblings(axes)
    for sibling in shared:
        limits = getattr(sibling, f"get_{direction}lim")()
        if value == "log" and min(limits) <= 0:
            raise ValueError("Set positive limits on shared axes before selecting log scale")
        if value == "logit" and not all(0 < item < 1 for item in limits):
            raise ValueError("Set limits strictly between 0 and 1 before selecting logit scale")


@dataclass(frozen=True)
class Property:
    """One explicitly typed public Matplotlib property, never an eval string."""

    key: str
    label: str
    get: Callable
    set: Callable
    kind: str = "text"
    choices: tuple = ()
    validate: Callable | None = None
    help: str = ""
    snapshot: Callable | None = None
    restore: Callable | None = None

    def check(self, value):
        if self.choices and value not in self.choices:
            raise ValueError(f"Choose one of: {', '.join(map(str, self.choices))}")
        if self.validate is not None:
            self.validate(value)


def _property(artist, key, label=None, kind="text", choices=(), validate=None, help=""):
    if validate is None and kind == "color":
        validate = colors.to_rgba
    if validate is None and key in ("text", "title", "xlabel", "ylabel"):
        validate = _text
    return Property(key, label or key.replace('_', ' ').title(),
                    getattr(artist, f"get_{key}"), getattr(artist, f"set_{key}"),
                    kind, tuple(choices), validate, help)


def set_text_group(texts, property_name, value):
    """Change only the named style, preserving every tick's own position."""
    old = [deepcopy(getattr(text, f"get_{property_name}")()) for text in texts]
    try:
        for text in texts:
            getattr(text, f"set_{property_name}")(value)
    except (ValueError, TypeError) as error:
        for text, previous in zip(texts, old):
            getattr(text, f"set_{property_name}")(previous)
        raise error


def _layout_name(figure):
    engine = figure.get_layout_engine()
    if isinstance(engine, ConstrainedLayoutEngine):
        return "compressed" if engine._compress else "constrained"
    if isinstance(engine, TightLayoutEngine):
        return "tight"
    return "none" if engine is None or isinstance(engine, PlaceHolderLayoutEngine) else type(engine).__name__


def _set_suptitle(figure, value):
    if figure._suptitle is None:
        if value:
            figure.suptitle(value)
    else:
        figure._suptitle.set_text(value)


def _set_origin(image, value):
    image.origin = value
    image.stale = True


def _set_clim(artist, value):
    # Norm callbacks may consult the bounds while they are being changed.
    with artist.norm.callbacks.blocked():
        artist.set_clim(value)
    artist.norm.callbacks.process("changed")


class FigureInspector:
    """A reusable immediate-mode artist inspector with visible validation errors.

    ``draw(figure)`` returns True only after successful edits. ``properties`` and
    ``apply`` expose the same typed edit path for programmatic use and tests.
    Unsupported artist classes retain generic visibility/layer/export controls.
    """

    def __init__(self):
        self.selected = None
        self.error = ""
        self._drafts = {}
        self._changed = False
        self._figure = None

    def properties(self, artist):
        props = []
        add = props.append
        if isinstance(artist, Figure):
            add(Property("size", "Size (inches)", lambda: list(artist.get_size_inches()),
                         lambda value: artist.set_size_inches(value, forward=False), "pair",
                         validate=lambda value: (_pair(value), _positive(value))))
            add(_property(artist, "dpi", "DPI", "float", validate=_positive))
            add(_property(artist, "facecolor", "Background", "color"))
            add(Property("layout", "Layout", lambda: _layout_name(artist),
                         artist.set_layout_engine, "choice", ("none", "tight", "constrained", "compressed"),
                         snapshot=artist.get_layout_engine, restore=artist.set_layout_engine))
            add(Property("suptitle", "Suptitle", lambda: artist._suptitle.get_text() if artist._suptitle else "",
                         lambda value: _set_suptitle(artist, value), validate=_text))
        elif isinstance(artist, Axes):
            add(_property(artist, "title", "Title"))
            add(_property(artist, "xlabel", "X label"))
            add(_property(artist, "ylabel", "Y label"))
            add(_property(artist, "facecolor", "Background", "color"))
            add(_property(artist, "frame_on", "Frame", "bool"))
            add(Property("axis_on", "Axes visible", lambda: artist.axison,
                         lambda value: artist.set_axis_on() if value else artist.set_axis_off(), "bool"))
            for direction in ("x", "y"):
                def validate_limits(value, direction=direction):
                    _limits(value)
                    scale = getattr(artist, f"get_{direction}scale")()
                    if scale == "log" and min(value) <= 0:
                        raise ValueError("Logarithmic limits must be positive")
                    if scale == "logit" and not all(0 < item < 1 for item in value):
                        raise ValueError("Logit limits must lie strictly between 0 and 1")
                add(_property(artist, f"{direction}lim", f"{direction.upper()} limits", "pair", validate=validate_limits))
                # Polar theta is angular, not a Cartesian scale.
                if not (artist.name == "polar" and direction == "x"):
                    add(_property(artist, f"{direction}scale", f"{direction.upper()} scale", "choice",
                                  ("linear", "log", "symlog", "logit", "asinh"),
                                  validate=lambda value, direction=direction: _scale(artist, direction, value)))
                add(_property(artist, f"autoscale{direction}_on", f"Autoscale {direction.upper()}", "bool"))
            add(_property(artist, "aspect", kind="text", validate=_aspect))
            add(_property(artist, "adjustable", kind="choice", choices=("box", "datalim")))
        elif isinstance(artist, Text):
            add(_property(artist, "text", "Text"))
            add(_property(artist, "fontfamily", "Font family", "json",
                          validate=_font_families))
            add(_property(artist, "fontsize", "Font size", "float", validate=_positive))
            add(Property("fontweight", "Font weight", lambda: str(artist.get_fontweight()),
                         lambda value: artist.set_fontweight(_weight(value))))
            add(_property(artist, "fontstyle", "Font style", "choice", ("normal", "italic", "oblique")))
            add(_property(artist, "color", kind="color"))
            add(_property(artist, "horizontalalignment", "Horizontal alignment", "choice", ("left", "center", "right")))
            add(_property(artist, "verticalalignment", "Vertical alignment", "choice", ("top", "center", "bottom", "baseline", "center_baseline")))
            add(_property(artist, "rotation", "Rotation (degrees)", "float", validate=_finite))
            add(_property(artist, "rotation_mode", kind="choice", choices=("default", "anchor", "xtick", "ytick")))
            add(_property(artist, "position", "Position (artist coordinates)", "pair", validate=_pair))
            add(_property(artist, "wrap", "Wrap text", "bool"))
        elif isinstance(artist, Line2D):
            for key in ("color", "markerfacecolor", "markeredgecolor"):
                add(_property(artist, key, kind="color"))
            for key in ("linewidth", "markersize", "markeredgewidth"):
                add(_property(artist, key, kind="float", validate=_nonnegative))
            add(_property(artist, "linestyle", kind="choice", choices=("-", "--", "-.", ":", "None")))
            add(_property(artist, "marker", kind="text", help="Matplotlib marker string, e.g. o, s, ^, +, x, . or None"))
            add(_property(artist, "drawstyle", kind="choice", choices=("default", "steps", "steps-pre", "steps-mid", "steps-post")))
            add(_property(artist, "solid_capstyle", kind="choice", choices=("butt", "projecting", "round")))
            add(_property(artist, "solid_joinstyle", kind="choice", choices=("miter", "round", "bevel")))
        elif isinstance(artist, AxesImage):
            self._mapping_properties(artist, props)
            add(_property(artist, "interpolation", kind="choice", choices=("none", "nearest", "bilinear", "bicubic", "spline16", "spline36", "hanning", "hamming", "hermite", "kaiser", "quadric", "catrom", "gaussian", "bessel", "mitchell", "sinc", "lanczos", "blackman", "antialiased", "auto")))
            add(Property("origin", "Origin", lambda: artist.origin, lambda value: _set_origin(artist, value), "choice", ("upper", "lower")))
            add(_property(artist, "resample", kind="bool"))
        elif isinstance(artist, Collection):
            if isinstance(artist, PathCollection):
                add(_property(artist, "sizes", "Marker areas (pt^2; JSON list)", "json", validate=_sizes))
            for key in ("facecolor", "edgecolor"):
                if key == "facecolor" and artist.get_array() is not None:
                    continue
                add(Property(key, f"{key.title()} (JSON colors)",
                             getattr(artist, f"get_{key}"), getattr(artist, f"set_{key}"), "json",
                             validate=colors.to_rgba_array,
                             help="A color string or list of colors/RGBA arrays; mapped data overrides facecolors."))
            add(_property(artist, "linewidth", "Line widths (JSON list)", "json", validate=_sizes))
            if artist.get_array() is not None:
                self._mapping_properties(artist, props)
        elif isinstance(artist, Legend):
            # Matplotlib exposes set_loc but no public location getter.
            add(Property("loc", "Location", lambda: next((name for name, code in Legend.codes.items() if code == artist._loc), str(artist._loc)),
                         artist.set_loc, "choice", tuple(name for name in Legend.codes if name != "best" or artist.isaxes)))
            add(Property("title", "Legend title", lambda: artist.get_title().get_text(), artist.set_title, validate=_text))
            add(_property(artist, "frame_on", "Show frame", "bool"))
            add(_property(artist, "draggable", "Draggable", "bool"))
        elif isinstance(artist, Patch):
            for key in ("facecolor", "edgecolor"):
                add(_property(artist, key, kind="color"))
            add(_property(artist, "linewidth", kind="float", validate=_nonnegative))
            add(_property(artist, "linestyle", kind="text"))
            add(_property(artist, "fill", kind="bool"))
            add(_property(artist, "hatch", kind="text", help="Hatch characters: / \\ | - + x o O . *"))
            add(_property(artist, "joinstyle", kind="choice", choices=("miter", "round", "bevel")))
            add(_property(artist, "capstyle", kind="choice", choices=("butt", "projecting", "round")))
        if isinstance(artist, Artist):
            add(_property(artist, "visible", kind="bool"))
            add(_property(artist, "alpha", "Alpha (0-1 or null)", "json", validate=_alpha))
            add(_property(artist, "zorder", "Layer / z-order", "float", validate=_finite))
            add(_property(artist, "clip_on", "Clip to axes", "bool"))
            add(_property(artist, "rasterized", "Rasterize in vector export", "bool"))
            add(_property(artist, "label", "Artist label"))
            add(_property(artist, "gid", "SVG group ID"))
            add(_property(artist, "url", "Export hyperlink"))
        return props

    @staticmethod
    def _mapping_properties(artist, props):
        props.append(Property("cmap", "Colormap", lambda: artist.get_cmap().name,
                              artist.set_cmap, "choice", tuple(mpl.colormaps)))
        props.append(Property("clim", "Color limits", artist.get_clim,
                              lambda value: _set_clim(artist, value), "pair", validate=_clim))

    def apply(self, artist, key, value):
        """Apply a typed edit transactionally; rejection is available as ``error``."""
        prop = next((prop for prop in self.properties(artist) if prop.key == key), None)
        if prop is None:
            self.error = f"Unsupported property: {key}"
            return False
        return self._apply_property(prop, value)

    def _apply_property(self, prop, value):
        old = prop.snapshot() if prop.snapshot is not None else deepcopy(prop.get())
        attempted = False
        try:
            prop.check(value)
            with warnings.catch_warnings():
                warnings.simplefilter("error", UserWarning)
                attempted = True
                prop.set(value)
        except (ValueError, TypeError, OverflowError, RuntimeError, UserWarning) as error:
            if attempted:
                (prop.restore or prop.set)(old)
            self.error = f"{prop.label}: {error}"
            return False
        self.error = ""
        self._changed = True
        return True

    def _control(self, prop, owner):
        key = (id(owner), prop.key)
        current = prop.get()
        imgui.push_id(prop.key)
        if prop.kind == "bool":
            edited, value = imgui.checkbox(prop.label, bool(current))
        elif prop.kind == "choice":
            choices = list(prop.choices)
            if current not in choices:
                choices.insert(0, current)
            edited, index = imgui.combo(prop.label, choices.index(current), [str(v) for v in choices])
            value = choices[index]
        elif prop.kind == "color":
            edited, value = imgui.color_edit4(prop.label, list(colors.to_rgba(current)))
        else:
            if prop.kind in ("json", "pair"):
                if isinstance(current, np.ndarray):
                    current = current.tolist()
                shown = json.dumps(current)
            else:
                shown = "" if current is None else str(current)
            draft = self._drafts.get(key, shown)
            edited, value = imgui.input_text(prop.label, draft, imgui.InputTextFlags_.enter_returns_true)
            if imgui.is_item_active() or edited:
                self._drafts[key] = value
            elif key in self._drafts and not self.error:
                del self._drafts[key]
            if edited:
                try:
                    if prop.kind in ("json", "pair"):
                        value = json.loads(value)
                    elif prop.kind == "float":
                        value = float(value)
                except (ValueError, TypeError) as error:
                    self.error = f"{prop.label}: {error}"
                    edited = False
        if prop.help and imgui.is_item_hovered():
            imgui.set_tooltip(prop.help)
        if edited and self._apply_property(prop, value):
            self._drafts.pop(key, None)
        imgui.pop_id()

    def _select(self, label, artist):
        if imgui.selectable(f"{label}##{id(artist)}", self.selected is artist)[0]:
            self.selected = artist
            self.error = ""
            self._drafts.clear()

    def _legend_tree(self, legend):
        self._select("Legend", legend)
        if imgui.tree_node(f"Legend contents##{id(legend)}"):
            self._select("Frame", legend.get_frame())
            self._select("Title", legend.get_title())
            for index, text in enumerate(legend.get_texts()):
                self._select(f"Label {index + 1}: {text.get_text()}", text)
            imgui.tree_pop()

    def _hierarchy(self, figure):
        self._select("Figure", figure)
        for index, text in enumerate(figure.texts):
            self._select(f"Figure text {index + 1}: {text.get_text()}", text)
        for index, axes in enumerate(figure.axes):
            self._select(f"Axes {index + 1} ({axes.name})", axes)
            if imgui.tree_node(f"Axes {index + 1} artists##{id(axes)}"):
                self._select("Title", axes.title)
                self._select("Left title", axes._left_title)
                self._select("Right title", axes._right_title)
                self._select("X label", axes.xaxis.label)
                self._select("Y label", axes.yaxis.label)
                for direction, axis in (("X", axes.xaxis), ("Y", axes.yaxis)):
                    if imgui.tree_node(f"{direction} tick labels##{id(axis)}"):
                        for which, ticks in (("Major", axis.majorTicks), ("Minor", axis.minorTicks)):
                            for number, tick in enumerate(ticks):
                                for side, label in enumerate((tick.label1, tick.label2)):
                                    if label.get_visible():
                                        self._select(f"{which} {number + 1}, side {side + 1}: {label.get_text()}", label)
                        imgui.tree_pop()
                for name, spine in axes.spines.items():
                    self._select(f"Spine: {name}", spine)
                for name, artists in (("Line", axes.lines), ("Collection", axes.collections),
                                      ("Image", axes.images), ("Patch", axes.patches),
                                      ("Text", axes.texts), ("Artist", axes.artists)):
                    for number, artist in enumerate(artists):
                        self._select(f"{name} {number + 1}: {artist.get_label()}", artist)
                if axes.get_legend() is not None:
                    self._legend_tree(axes.get_legend())
                imgui.tree_pop()
        for legend in figure.legends:
            self._legend_tree(legend)

    def _ticks(self, axes):
        for direction in ("x", "y"):
            axis = getattr(axes, f"{direction}axis")
            for which in ("major", "minor"):
                if not imgui.collapsing_header(f"{direction.upper()} {which} ticks / grid"):
                    continue
                imgui.push_id(f"{direction}_{which}")
                minor = which == "minor"
                ticks = axis.minorTicks if minor else axis.majorTicks
                self._control(Property("locations", "Tick positions (JSON; [] hides ticks)",
                                       lambda axis=axis, minor=minor: axis.get_ticklocs(minor=minor),
                                       lambda value, axis=axis, minor=minor: axis.set_ticks(value, minor=minor),
                                       "json", validate=_numeric_list), ticks)
                labels = [label for tick in ticks for label in (tick.label1, tick.label2)]
                params = axis.get_tick_params(which=which)
                for key, label, kind, default, validator in (
                    ("length", "Length", "float", 3.5, _nonnegative),
                    ("width", "Width", "float", 0.8, _nonnegative),
                    ("labelsize", "Label size", "float", 10.0, _positive),
                    ("labelrotation", "Label rotation", "float", 0.0, _finite),
                    ("color", "Tick color", "color", "black", None),
                    ("labelcolor", "Label color", "color", "black", None),
                ):
                    self._control(Property(key, label, lambda key=key, default=default: params.get(key, default),
                                           lambda value, key=key: axis.set_tick_params(which=which, **{key: value}),
                                           kind, validate=validator), ticks)
                if labels:
                    for key, choices in (("horizontalalignment", ("left", "center", "right")),
                                         ("verticalalignment", ("top", "center", "bottom", "baseline", "center_baseline"))):
                        self._control(Property(key, key.replace("alignment", " alignment").title(),
                                               lambda key=key: getattr(labels[0], f"get_{key}")(),
                                               lambda value, key=key: set_text_group(labels, key, value),
                                               "choice", choices), ticks)
                else:
                    imgui.text_disabled("No tick labels; no label positions are modified.")
                self._control(Property("grid", "Grid visible", lambda: params.get("gridOn", False),
                                       lambda value: axes.grid(value, which=which, axis=direction), "bool"), ticks)
                for key, label, kind, default, validator in (
                    ("grid_color", "Grid color", "color", mpl.rcParams["grid.color"], None),
                    ("grid_alpha", "Grid alpha", "float", mpl.rcParams["grid.alpha"], _alpha),
                    ("grid_linewidth", "Grid width", "float", mpl.rcParams["grid.linewidth"], _nonnegative),
                    ("grid_linestyle", "Grid style", "text", mpl.rcParams["grid.linestyle"], None),
                ):
                    self._control(Property(key, label, lambda key=key, default=default: params.get(key, default),
                                           lambda value, key=key: axis.set_tick_params(which=which, **{key: value}),
                                           kind, validate=validator), ticks)
                imgui.pop_id()

    def draw(self, figure):
        """Draw artist hierarchy and properties within the caller's ImGui window."""
        self._changed = False
        if self._figure is not figure:
            self._figure = figure
            self.selected = figure
            self._drafts.clear()
            self.error = ""
        imgui.push_id(f"inspector_{id(self)}")
        imgui.text_wrapped("Select an artist. Text and numeric fields apply with Enter; colors and choices apply immediately.")
        if imgui.begin_child("Artist hierarchy", (0, 200), imgui.ChildFlags_.borders):
            self._hierarchy(figure)
        imgui.end_child()
        if self.error:
            imgui.text_wrapped(f"Edit rejected: {self.error}")
        artist = self.selected
        imgui.separator_text(type(artist).__name__)
        if isinstance(artist, Axes) and artist.name == "polar":
            imgui.text_wrapped("Polar: X limits/ticks are theta in radians; Y is radius. Spines are listed by their actual names.")
        imgui.text_wrapped("Supported: curated style, layout and axis properties. Plot data, custom transforms and projection-specific geometry are not edited.")
        if isinstance(artist, Collection) and not isinstance(artist, PathCollection):
            imgui.text_wrapped("Collection: common colors, line widths and scalar mapping only; geometry is not edited.")
        if isinstance(artist, Collection) and artist.get_array() is not None:
            imgui.text_wrapped("Facecolors come from scalar data: edit Colormap / Color limits. Literal facecolors are not applied over mapped data.")
        for prop in self.properties(artist):
            self._control(prop, artist)
        if isinstance(artist, Text) and imgui.collapsing_header("Installed fonts"):
            fonts = available_fonts()
            current = artist.get_fontname()
            choices = (current,) + tuple(font for font in fonts if font != current)
            self._control(Property("fontname", "Installed font", artist.get_fontname, artist.set_fontname,
                                   "choice", choices), artist)
        if isinstance(artist, Axes):
            self._ticks(artist)
        if isinstance(artist, Figure) and artist._suptitle is not None:
            if imgui.button("Edit suptitle typography"):
                self.selected = artist._suptitle
        imgui.pop_id()
        return self._changed
