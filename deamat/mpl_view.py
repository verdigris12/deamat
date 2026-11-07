"""Standalone Matplotlib viewer using the same canvas and inspector as widgets.

Pickle is executable code: open only files from a source you trust. PNG, PDF and
SVG export are available without serializing Python objects.
"""

from pathlib import Path
import pickle

from imgui_bundle import imgui
from matplotlib.figure import Figure

from .gui import GUI
from .guistate import GUIState
from .mpl_canvas import draw_figure, get_figure_view
from .mpl_properties import FigureInspector
from .widgets.file_dialog import FileDialog


PICKLE_FILTERS = "Matplotlib pickle{.pkl,.pickle},.*"
EXPORT_FILTERS = {
    "png": "PNG image{.png}",
    "pdf": "PDF document{.pdf}",
    "svg": "SVG image{.svg}",
}


def load_trusted_figure(filename):
    """Unpickle a Figure. The caller must establish trust *before* calling."""
    with open(filename, "rb") as stream:
        figure = pickle.load(stream)
    if not isinstance(figure, Figure):
        raise TypeError(f"Expected a matplotlib Figure, got {type(figure).__name__}")
    return figure


class MPLVState(GUIState):
    def __init__(self, figure):
        super().__init__()
        if not isinstance(figure, Figure):
            raise TypeError("MPLView requires a matplotlib Figure")
        self.fig = figure
        self.fit = False
        self.show_inspector = True
        self.status = "Ready - pan, rectangle zoom or scroll to zoom."
        self.error = ""


class MPLView:
    """Inspect the supplied Figure in place, without factory registration."""

    def __init__(self, fig):
        self.state = MPLVState(fig)
        self.inspector = FigureInspector()
        self.gui = GUI(self.state, width=1440, height=900, title="Matplotlib figure viewer")
        self.gui.update = self.update_ui
        self._dialog = None
        self._dialog_action = None
        self._dialog_request = None

    def _draw_dialogs(self):
        # Open and draw in one stable scope, never inside a transient menu.
        if self._dialog_request == "trust":
            self._dialog_request = None
            self._dialog_action = "trust"
            imgui.open_popup("Open trusted pickle")
        imgui.set_next_window_size((460, 0), imgui.Cond_.appearing)
        visible, opened = imgui.begin_popup_modal(
            "Open trusted pickle", True, imgui.WindowFlags_.always_auto_resize
        )
        if visible:
            imgui.text_wrapped(
                "Pickle files can execute arbitrary code. Only open files from a source you trust."
            )
            imgui.spacing()
            if imgui.button("Open trusted file"):
                self._dialog_request = "open"
                self._dialog_action = None
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel") or imgui.is_key_pressed(imgui.Key.escape):
                self._dialog_action = None
                imgui.close_current_popup()
            imgui.end_popup()
        if not opened and self._dialog_action == "trust":
            self._dialog_action = None

        try:
            if self._dialog_request is not None:
                action, self._dialog_request = self._dialog_request, None
                if self._dialog is None:
                    self._dialog = FileDialog(self.gui)
                if action == "open":
                    self._dialog.open("Open trusted Matplotlib pickle", PICKLE_FILTERS)
                elif action == "pickle":
                    self._dialog.save("Save Matplotlib pickle", PICKLE_FILTERS)
                else:
                    self._dialog.save(f"Export {action.upper()}", EXPORT_FILTERS[action])
                self._dialog_action = action
            if self._dialog is None:
                return
            result = self._dialog.draw()
            if result is None:
                return
            action, self._dialog_action = self._dialog_action, None
            if not result.paths:
                return
            if action == "open":
                self.open_trusted(result.paths[0])
            elif action == "pickle":
                self.save_pickle(result.paths[0])
            else:
                self.export(result.paths[0], action)
        except Exception as error:
            # A file/serialization boundary: the full error remains visible.
            self.state.error = f"File operation: {type(error).__name__}: {error}"

    def open_trusted(self, filename):
        figure = load_trusted_figure(filename)
        self.state.fig = figure
        # Replacing the retained view releases the old texture and callbacks.
        get_figure_view(self.gui, "standalone", figure)
        self.state.error = ""
        self.state.status = f"Opened {filename}"

    def save_pickle(self, filename):
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(".pkl")
        with path.open("wb") as stream:
            pickle.dump(self.state.fig, stream, protocol=pickle.HIGHEST_PROTOCOL)
        self.state.error = ""
        self.state.status = f"Saved trusted Python pickle: {path}"
        return path

    def export(self, filename, format):
        if format not in EXPORT_FILTERS:
            raise ValueError("Export format must be png, pdf or svg")
        path = Path(filename)
        if path.suffix.lower() != f".{format}":
            path = path.with_suffix(f".{format}")
        self.state.fig.savefig(path, format=format)
        self.state.error = ""
        self.state.status = f"Exported {path}"
        return path

    def _menu(self):
        if not imgui.begin_main_menu_bar():
            return
        if imgui.begin_menu("File"):
            available = self._dialog_action is None and self._dialog_request is None
            if imgui.menu_item("Open trusted pickle...", "", False, available)[0]:
                self._dialog_request = "trust"
            if imgui.menu_item("Save pickle...", "", False, available)[0]:
                self._dialog_request = "pickle"
            imgui.separator()
            for format in EXPORT_FILTERS:
                if imgui.menu_item(f"Export {format.upper()}...", "", False, available)[0]:
                    self._dialog_request = format
            imgui.separator()
            if imgui.menu_item("Close", "", False)[0]:
                self.gui.close()
            imgui.end_menu()
        if imgui.begin_menu("View"):
            clicked, shown = imgui.menu_item("Artist inspector", "", self.state.show_inspector)
            if clicked:
                self.state.show_inspector = shown
            imgui.end_menu()
        imgui.end_main_menu_bar()

    def update_ui(self, state, gui, dt):
        self._menu()
        if gui._closed:
            return
        self._draw_dialogs()
        viewport = imgui.get_main_viewport()
        top = viewport.pos.y + imgui.get_frame_height()
        height = max(100, viewport.size.y - imgui.get_frame_height())
        inspector_width = min(460, viewport.size.x * 0.34)
        plot_width = viewport.size.x - inspector_width
        imgui.set_next_window_pos((viewport.pos.x, top), imgui.Cond_.first_use_ever)
        imgui.set_next_window_size((plot_width, height), imgui.Cond_.first_use_ever)
        visible, _ = imgui.begin("Figure view")
        if visible:
            changed, mode = imgui.combo("Display", int(state.fit), ["Actual size", "Fit viewport"])
            if changed:
                state.fit = bool(mode)
            imgui.same_line()
            imgui.text_disabled("Drag: pan / zoom | Wheel: cursor zoom")
            if state.error:
                imgui.text_wrapped(f"File operation failed: {state.error}")
            imgui.text_wrapped(state.status)
            size = imgui.get_content_region_avail()
            draw_figure(gui, "standalone", state.fig, size=(size.x, size.y), fit=state.fit)
        imgui.end()
        if state.show_inspector:
            imgui.set_next_window_pos((viewport.pos.x + plot_width, top), imgui.Cond_.first_use_ever)
            imgui.set_next_window_size((inspector_width, height), imgui.Cond_.first_use_ever)
            visible, state.show_inspector = imgui.begin("Artist inspector", state.show_inspector)
            if visible and self.inspector.draw(state.fig):
                get_figure_view(gui, "standalone", state.fig).invalidate()
            imgui.end()

    def run(self):
        self.gui.run()


def main():
    """Launch the viewer only after explicit acknowledgement of pickle trust."""
    import argparse

    parser = argparse.ArgumentParser(description="View/edit a trusted pickled Matplotlib Figure")
    parser.add_argument("figure", help="Path to a trusted pickled Figure")
    parser.add_argument("--trust-pickle", action="store_true", help="Acknowledge that loading this trusted file may execute Python code")
    args = parser.parse_args()
    if not args.trust_pickle:
        parser.error("Pickle may execute arbitrary code. For a trusted file, pass --trust-pickle.")
    try:
        figure = load_trusted_figure(args.figure)
    except Exception as error:
        parser.exit(1, f"Cannot load figure: {type(error).__name__}: {error}\n")
    MPLView(figure).run()


if __name__ == "__main__":
    main()
