"""Embedded ImFileDialog with WGPU-owned icon and thumbnail textures."""

from dataclasses import dataclass
from pathlib import Path

import wgpu
from imgui_bundle import imgui, im_file_dialog


@dataclass(frozen=True)
class DialogResult:
    """Completed selection; an empty paths tuple means the user cancelled."""

    paths: tuple[Path, ...]


class FileDialog:
    """An embedded picker. Call draw every frame in the same ImGui ID scope.

    A patched imgui-bundle providing FileDialog texture callbacks is required.
    One request may be active at a time; close releases the widget permanently.
    """

    def __init__(self, gui):
        gui._require_open()
        self._gui = gui
        self._dialog = im_file_dialog.FileDialog()
        if not callable(getattr(self._dialog, "set_texture_callbacks", None)) or not callable(
            getattr(self._dialog, "clear_texture_callbacks", None)
        ):
            raise RuntimeError(
                "Embedded file dialogs require the patched imgui-bundle 1.92.0 "
                "with FileDialog texture callbacks; vanilla imgui-bundle is unsupported"
            )
        self._textures = {}
        self._retired = []
        self._retire_posted = False
        self._key = f"deamat_file_dialog_{id(self):x}"
        self._title = ""
        self._active = False
        self._drawn = False
        self._multiple = False
        self._save = False
        self._overwrite = None
        self._closed = False
        self._dialog.set_texture_callbacks(self._create_texture, self._delete_texture)
        try:
            gui.add_cleanup(self._dispose)
        except BaseException:
            self._dialog.clear_texture_callbacks()
            raise

    @property
    def active(self):
        return self._active

    def _start(self, title, filter, starting_dir, *, save=False, multiselect=False):
        self._gui._require_open()
        self._require_frame()
        if self._closed:
            raise RuntimeError("file dialog is closed")
        if self._active:
            raise RuntimeError("a file dialog request is already active")
        self._title = title
        self._multiple = multiselect
        self._save = save
        try:
            if save:
                opened = self._dialog.save(self._key, title, filter, str(starting_dir))
            else:
                opened = self._dialog.open(self._key, title, filter, multiselect, str(starting_dir))
            if not opened:
                raise RuntimeError("ImFileDialog rejected the request")
        except BaseException:
            self._dialog.close()
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
        if self._overwrite is not None:
            return self._draw_overwrite()
        self._drawn = True
        if not self._dialog.is_done(self._key):
            return None
        try:
            if not self._dialog.has_result():
                result = DialogResult(())
            else:
                paths = self._dialog.get_results() if self._multiple else (self._dialog.get_result(),)
                result = DialogResult(tuple(Path(path.path()) for path in paths))
        finally:
            try:
                self._dialog.close()
            finally:
                self._active = False
                self._drawn = False
        if self._save and result.paths and (result.paths[0].exists() or result.paths[0].is_symlink()):
            imgui.open_popup(self._overwrite_title())
            self._overwrite = result
            self._active = True
            self._drawn = True
            return self._draw_overwrite()
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
            self._overwrite = None
            self._active = False
            self._drawn = False
        return result

    def _create_texture(self, pixels, width, height, format):
        device = self._gui.renderer.device
        texture = device.create_texture(
            label="imfiledialog", size=(width, height, 1),
            format=wgpu.TextureFormat.bgra8unorm if format == 0 else wgpu.TextureFormat.rgba8unorm,
            usage=wgpu.TextureUsage.COPY_DST | wgpu.TextureUsage.TEXTURE_BINDING,
        )
        try:
            device.queue.write_texture(
                destination={"texture": texture, "origin": (0, 0, 0)},
                data=pixels,
                data_layout={"bytes_per_row": width * 4, "rows_per_image": height},
                size=(width, height, 1),
            )
            ref = self._gui.gui_renderer.backend.register_texture(texture.create_view())
        except BaseException:
            texture.destroy()
            raise
        tex_id = ref.get_tex_id()
        self._textures[tex_id] = (ref, texture)
        return tex_id

    def _delete_texture(self, tex_id):
        resource = self._textures.pop(tex_id, None)
        if resource is None:
            return
        self._retired.append(resource)
        if self._gui._frame_active:
            # Draw data in this frame may still refer to this view, including
            # in secondary viewports. Unregister only after the frame submits.
            if not self._retire_posted:
                self._retire_posted = True
                self._gui.post(self._flush_retired)
        else:
            self._flush_retired()

    def _flush_retired(self):
        self._retire_posted = False
        while self._retired:
            ref, texture = self._retired.pop()
            try:
                self._gui.gui_renderer.backend.unregister_texture(ref)
            finally:
                texture.destroy()

    def _require_frame(self):
        if not self._gui._frame_active or imgui.get_current_context() != self._gui.gui_renderer.imgui_context:
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

    def _dispose(self):
        if self._closed:
            if not self._gui._frame_active:
                self._flush_retired()
            return
        self._closed = True
        try:
            self._dialog.close()
        finally:
            self._active = False
            self._overwrite = None
            try:
                for tex_id in tuple(self._textures):
                    self._delete_texture(tex_id)
            finally:
                self._dialog.clear_texture_callbacks()
