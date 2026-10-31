"""Embedded Matplotlib figures using the same canvas as the standalone viewer."""

import multiprocessing
import pickle
from typing import Any

from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd
from matplotlib import pyplot as plt
from matplotlib.figure import Figure

from deamat.mpl_canvas import dispose_figure_view, draw_figure, get_figure_view


def open_figure_in_pyplot(pickled_figure: bytes) -> None:
    """Child-process entry point for a figure serialized by this application."""
    from deamat.mpl_view import MPLView

    MPLView(pickle.loads(pickled_figure)).run()


def _resolve_figure(gui, state, figname, width, height, autosize):
    entry = state.figures[figname]
    available = imgui.get_content_region_avail()
    if autosize:
        entry["width"] = max(1, int(available.x))
        entry["height"] = max(1, int(available.y))
    else:
        if width is not None:
            entry["width"] = max(1, int(width))
        if height is not None:
            entry["height"] = max(1, int(height))
        if entry["width"] <= 0:
            entry["width"] = max(1, int(available.x))
        if entry["height"] <= 0:
            entry["height"] = max(1, int(available.y))
    if entry["dirty"] or entry["figure"] is None:
        # Factories may use entry dimensions; resolve these before their first
        # invocation. Resizing never regenerates data or reruns the factory.
        previous = entry["figure"]
        result = entry["make"](state)
        if not isinstance(result, Figure):
            raise TypeError(f"Figure factory {figname!r} must return a matplotlib Figure")
        if previous is not None and previous is not result:
            dispose_figure_view(gui, figname)
            plt.close(previous)
        entry["figure"] = result
        entry["dirty"] = False
        entry["texture_dirty"] = True
    view = get_figure_view(gui, figname, entry["figure"])
    if "_dispose_view" not in entry:
        entry["_dispose_view"] = lambda: dispose_figure_view(gui, figname)

        def close_owned_figure():
            if state.figures.get(figname) is entry:
                state.remove_figure(figname)

        gui.add_cleanup(close_owned_figure)
    if entry["texture_dirty"]:
        view.invalidate()
    return entry, view


def figure(
    gui: Any,
    state: Any,
    figname: str,
    width: int | None = None,
    height: int | None = None,
    autosize: bool = False,
) -> None:
    """Embed a lazy figure with pan, zoom, history and editable properties.

    ``autosize`` fits the available region; otherwise registered or explicit
    width/height set the image dimensions in logical pixels. Changes to artists
    rerasterize automatically. ``state.invalidate_figure`` reruns the factory
    only when its source data changes. Properties and actual-size mode preserve
    the figure's intrinsic dimensions. Each figure owns independent controls.
    """
    imgui.push_id(f"deamat-figure-{figname}")
    try:
        entry, view = _resolve_figure(gui, state, figname, width, height, autosize)
        if imgui.button("Refresh data"):
            state.invalidate_figure(figname)
        imgui.same_line()
        if imgui.button("Open in viewer"):
            process = multiprocessing.get_context("spawn").Process(
                target=open_figure_in_pyplot, args=(pickle.dumps(entry["figure"]),),
            )
            process.start()
        imgui.same_line()
        if imgui.button("Save image"):
            path = pfd.save_file(
                "Save figure", state.figure_path,
                ["PNG image", "*.png", "PDF document", "*.pdf", "SVG image", "*.svg"],
            ).result()
            if path:
                entry["figure"].savefig(path)
                state.figure_path = path
        imgui.same_line()
        _, entry["_show_properties"] = imgui.checkbox("Properties", entry.get("_show_properties", False))
        _, entry["_fit"] = imgui.checkbox("Fit figure", entry.get("_fit", True))
        if entry["_show_properties"]:
            from deamat.mpl_properties import FigureInspector

            if "_inspector" not in entry:
                entry["_inspector"] = FigureInspector()
            visible, opened = imgui.begin(f"{entry['title']} properties##{figname}", True)
            entry["_show_properties"] = opened
            if visible and entry["_inspector"].draw(entry["figure"]):
                view.invalidate()
            imgui.end()
        if autosize:
            available = imgui.get_content_region_avail()
            size = (max(1, available.x), max(1, available.y))
        else:
            size = (entry["width"], entry["height"])
        draw_figure(gui, figname, entry["figure"], size=size, fit=entry["_fit"])
        entry["texture_dirty"] = False
    finally:
        imgui.pop_id()
