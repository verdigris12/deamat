"""Embedded ImFileDialog picker."""

from dataclasses import dataclass
from pathlib import Path

from imgui_bundle import imgui, im_file_dialog


@dataclass(frozen=True)
class DialogResult:
    """Completed selection; an empty paths tuple means the user cancelled."""

    paths: tuple[Path, ...]


class FileDialog:
    """An embedded picker. Call draw every frame in the same ImGui ID scope.

    Only one request may be active across all wrappers.
    Close releases the widget permanently.
    """

    _owner = None

    def __init__(self, gui):
        gui._require_open()
        self._gui = gui
        self._dialog = im_file_dialog.FileDialog.instance()
        self._key = f"deamat_file_dialog_{id(self):x}"
        self._title = ""
        self._active = False
        self._drawn = False
        self._multiple = False
        self._save = False
        self._overwrite = None
        self._closed = False
        self._native_pending = False
        self._native_closed = True
        gui.add_cleanup(self._dispose)

    @property
    def active(self):
        return self._active

    def _start(self, title, filter, starting_dir, *, save=False, multiselect=False):
        self._gui._require_open()
        self._require_frame()
        if self._closed:
            raise RuntimeError("file dialog is closed")
        if FileDialog._owner is not None:
            raise RuntimeError("a file dialog request is already active")
        FileDialog._owner = self
        self._title = title
        self._multiple = multiselect
        self._save = save
        self._native_closed = False
        try:
            if save:
                opened = self._dialog.save(self._key, title, filter, str(starting_dir))
            else:
                opened = self._dialog.open(self._key, title, filter, multiselect, str(starting_dir))
            if not opened:
                raise RuntimeError("ImFileDialog rejected the request")
        except BaseException:
            self._schedule_close()
            raise
        self._active = True
        self._drawn = False

    def open(self, title, filter=".*", starting_dir="", multiselect=False):
        """Request files; set multiselect to return all selected paths."""
        if not filter:
            raise ValueError("an empty filter selects directories; use select_folder")
        self._start(title, filter, starting_dir, multiselect=multiselect)

    def save(self, title, filter=".*", starting_dir=""):
        """Request a destination path."""
        if not filter:
            raise ValueError("save requires a nonempty file filter")
        self._start(title, filter, starting_dir, save=True)

    def select_folder(self, title, starting_dir=""):
        """Request a directory using ImFileDialog's empty-filter sentinel."""
        self._start(title, "", starting_dir)

    def draw(self):
        """Render/poll the modal; return DialogResult once, or None while idle/pending."""
        self._gui._require_open()
        self._require_frame()
        if not self._active:
            return None
        try:
            if self._overwrite is not None:
                return self._draw_overwrite()
            self._drawn = True
            if not self._dialog.is_done(self._key):
                return None
            if not self._dialog.has_result():
                result = DialogResult(())
            else:
                paths = self._dialog.get_results() if self._multiple else (self._dialog.get_result(),)
                result = DialogResult(tuple(Path(path.path()) for path in paths))
            self._schedule_close()
            if self._save and result.paths and (result.paths[0].exists() or result.paths[0].is_symlink()):
                imgui.open_popup(self._overwrite_title())
                self._overwrite = result
                return self._draw_overwrite()
        except BaseException:
            self._schedule_close()
            self._release()
            raise
        self._release()
        return result

    def _overwrite_title(self):
        return f"Replace existing file?###{self._key}_overwrite"

    def _draw_overwrite(self):
        font_size = imgui.get_font_size()
        imgui.set_next_window_size_constraints((font_size * 24, 0), (font_size * 42, float("inf")))
        opened, keep_open = imgui.begin_popup_modal(
            self._overwrite_title(), True, imgui.WindowFlags_.always_auto_resize
        )
        result = None
        if opened:
            try:
                imgui.text_wrapped(f"Replace existing file?\n{self._overwrite.paths[0]}")
                if imgui.button("Replace"):
                    result = self._overwrite
                imgui.same_line()
                if imgui.button("Cancel") or imgui.is_key_pressed(imgui.Key.escape, False):
                    result = DialogResult(())
                if result is not None:
                    imgui.close_current_popup()
            finally:
                imgui.end_popup()
        if keep_open is False:
            result = DialogResult(())
        if result is not None:
            self._release()
        return result


    def _require_frame(self):
        if not self._gui._frame_active or imgui.get_current_context() != self._gui.imgui_context:
            raise RuntimeError("file dialog drawing requires its GUI's active ImGui frame")

    def close(self):
        """Dispose the widget; an active modal must be closed in its drawing ID scope."""
        self._gui._assert_ui_thread()
        if self._closed:
            return
        if self._active and self._drawn:
            self._require_frame()
            title = self._overwrite_title() if self._overwrite is not None else f"{self._title}###{self._key}"
            opened, _ = imgui.begin_popup_modal(title)
            if not opened:
                raise RuntimeError("close the active file dialog in the same ImGui window and ID scope as draw")
            imgui.close_current_popup()
            imgui.end_popup()
        self._dispose()

    def _release(self):
        self._active = False
        self._drawn = False
        self._overwrite = None
        if FileDialog._owner is self and not self._native_pending:
            FileDialog._owner = None

    def _schedule_close(self):
        if self._native_closed or self._native_pending:
            return
        self._native_pending = True
        if self._gui._frame_active:
            self._gui.post(self._finish_close)
        else:
            self._finish_close()

    def _finish_close(self):
        if not self._native_pending:
            return
        try:
            self._dialog.close()
        except BaseException:
            self._active = False
            self._drawn = False
            self._overwrite = None
            raise
        finally:
            self._native_closed = True
            self._native_pending = False
            if not self._active and FileDialog._owner is self:
                FileDialog._owner = None

    def _dispose(self):
        if not self._closed:
            self._closed = True
            if FileDialog._owner is self:
                self._schedule_close()
                self._release()
        if self._native_pending and not self._gui._frame_active:
            self._finish_close()
