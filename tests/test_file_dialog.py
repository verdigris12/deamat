from pathlib import Path
from types import SimpleNamespace

import pytest
import wgpu

from deamat.widgets.file_dialog import DialogResult, FileDialog
import deamat.widgets.file_dialog as dialog_module


class NativeDialog:
    def __init__(self):
        self.done = False
        self.results = []
        self.callbacks = None

    def set_texture_callbacks(self, create, delete):
        self.callbacks = (create, delete)

    def clear_texture_callbacks(self):
        self.callbacks = None

    def open(self, *args):
        return True

    def save(self, *args):
        return True

    def is_done(self, key):
        return self.done

    def has_result(self):
        return bool(self.results)

    def get_result(self):
        return SimpleNamespace(path=lambda: self.results[0])

    def get_results(self):
        return [SimpleNamespace(path=lambda path=path: path) for path in self.results]

    def close(self):
        pass


class Texture:
    def __init__(self):
        self.destroyed = False

    def create_view(self):
        return self

    def destroy(self):
        self.destroyed = True


class Backend:
    def __init__(self):
        self.registered = []
        self.unregistered = []

    def register_texture(self, view):
        tex_id = len(self.registered) + 1
        ref = SimpleNamespace(get_tex_id=lambda: tex_id)
        self.registered.append((ref, view))
        return ref

    def unregister_texture(self, ref):
        self.unregistered.append(ref)


class Device:
    def __init__(self):
        self.textures = []
        self.queue = self

    def create_texture(self, **kwargs):
        texture = Texture()
        self.textures.append((texture, kwargs))
        return texture

    def write_texture(self, **kwargs):
        pass


@pytest.fixture
def widget(monkeypatch):
    native = NativeDialog()
    monkeypatch.setattr(dialog_module.im_file_dialog, "FileDialog", lambda: native)
    backend = Backend()
    device = Device()
    cleanups = []
    context = object()
    monkeypatch.setattr(dialog_module.imgui, "get_current_context", lambda: context)
    posts = []
    gui = SimpleNamespace(renderer=SimpleNamespace(device=device),
                          gui_renderer=SimpleNamespace(backend=backend, imgui_context=context),
                          add_cleanup=cleanups.append, _frame_active=True,
                          _require_open=lambda: None, _assert_ui_thread=lambda: None,
                          post=posts.append, posts=posts)
    return FileDialog(gui), native, device, backend, cleanups


def test_completion_cancellation_and_overlap(widget, tmp_path):
    dialog, native, _, _, _ = widget
    dialog.open("Open", "Images .png", "/tmp", multiselect=True)
    assert dialog.draw() is None
    with pytest.raises(RuntimeError, match="already active"):
        dialog.save("Save")
    native.results = ["/tmp/a.png", "/tmp/b.png"]
    native.done = True
    assert dialog.draw() == DialogResult((Path("/tmp/a.png"), Path("/tmp/b.png")))
    assert not dialog.active
    assert dialog.draw() is None
    dialog.select_folder("Folder", "/tmp")
    native.results = []
    assert dialog.draw() == DialogResult(())
    dialog.save("Save", "PNG .png")
    native.results = [str(tmp_path / "out.png")]
    assert dialog.draw() == DialogResult((tmp_path / "out.png",))


@pytest.mark.parametrize("choice", ["Replace", "Cancel", "Escape"])
def test_existing_save_waits_for_confirmation(widget, tmp_path, monkeypatch, choice):
    dialog, native, _, _, _ = widget
    target = tmp_path / "existing.png"
    target.write_bytes(b"original")
    monkeypatch.setattr(dialog_module.imgui, "open_popup", lambda title: None)
    monkeypatch.setattr(dialog_module.imgui, "get_font_size", lambda: 14)
    monkeypatch.setattr(dialog_module.imgui, "set_next_window_size_constraints", lambda *args: None)
    monkeypatch.setattr(dialog_module.imgui, "begin_popup_modal",
                        lambda title, opened, flags: (True, opened))
    monkeypatch.setattr(dialog_module.imgui, "text_wrapped", lambda text: None)
    monkeypatch.setattr(dialog_module.imgui, "same_line", lambda: None)
    monkeypatch.setattr(dialog_module.imgui, "close_current_popup", lambda: None)
    monkeypatch.setattr(dialog_module.imgui, "end_popup", lambda: None)
    pressed = set()
    monkeypatch.setattr(dialog_module.imgui, "is_key_pressed",
                        lambda key, repeat: "Escape" in pressed)
    monkeypatch.setattr(dialog_module.imgui, "button", lambda label: label in pressed)
    dialog.save("Save")
    native.results = [str(target)]
    native.done = True
    assert dialog.draw() is None
    assert dialog.active
    with pytest.raises(RuntimeError, match="already active"):
        dialog.open("Open")
    pressed.add(choice)
    expected = (target,) if choice == "Replace" else ()
    assert dialog.draw() == DialogResult(expected)
    assert not dialog.active
    assert dialog.draw() is None


@pytest.mark.parametrize("failure", ["start", "result", "close"])
def test_request_recovers_after_native_failure(widget, monkeypatch, failure):
    dialog, native, _, _, _ = widget
    original_open, original_result, original_close = native.open, native.get_result, native.close

    def fail(*args):
        raise ValueError("native failure")

    if failure == "start":
        monkeypatch.setattr(native, "open", fail)
        with pytest.raises(ValueError, match="native failure"):
            dialog.open("Open")
    else:
        dialog.open("Open")
        native.done = True
        native.results = ["/tmp/result"]
        monkeypatch.setattr(native, "get_result" if failure == "result" else "close", fail)
        with pytest.raises(ValueError, match="native failure"):
            dialog.draw()
    assert not dialog.active
    monkeypatch.setattr(native, "open", original_open)
    monkeypatch.setattr(native, "get_result", original_result)
    monkeypatch.setattr(native, "close", original_close)
    native.done = False
    dialog.open("Again")
    assert dialog.active


def test_texture_formats_upload_delete_and_cleanup(widget):
    dialog, native, device, backend, cleanups = widget
    create, delete = native.callbacks
    bgra = create(b"12345678", 2, 1, 0)
    create(b"abcdefgh", 1, 2, 1)
    assert device.textures[0][1]["format"] == wgpu.TextureFormat.bgra8unorm
    assert device.textures[1][1]["format"] == wgpu.TextureFormat.rgba8unorm
    delete(0)
    delete(bgra)
    assert not device.textures[0][0].destroyed
    assert not backend.unregistered
    assert len(dialog._gui.posts) == 1
    dialog._gui._frame_active = False
    dialog._gui.posts.pop()()
    assert device.textures[0][0].destroyed
    assert len(backend.unregistered) == 1
    cleanups[0]()
    assert device.textures[1][0].destroyed
    assert len(backend.unregistered) == 2
    assert native.callbacks is None
    dialog.close()
    assert len(backend.unregistered) == 2


def test_missing_binding_fails_clearly(monkeypatch):
    monkeypatch.setattr(dialog_module.im_file_dialog, "FileDialog", object)
    with pytest.raises(RuntimeError, match="patched imgui-bundle"):
        FileDialog(SimpleNamespace(_require_open=lambda: None))


def test_wrong_context_rejected(widget, monkeypatch):
    dialog, _, _, _, _ = widget
    monkeypatch.setattr(dialog_module.imgui, "get_current_context", lambda: object())
    with pytest.raises(RuntimeError, match="active ImGui frame"):
        dialog.open("Open")


def test_cleanup_registration_failure_releases_callbacks(monkeypatch):
    native = NativeDialog()
    monkeypatch.setattr(dialog_module.im_file_dialog, "FileDialog", lambda: native)

    def reject_cleanup(callback):
        raise RuntimeError("GUI closed")

    gui = SimpleNamespace(_require_open=lambda: None, add_cleanup=reject_cleanup)
    with pytest.raises(RuntimeError, match="GUI closed"):
        FileDialog(gui)
    assert native.callbacks is None


def test_shutdown_releases_deferred_textures(widget):
    dialog, native, device, backend, cleanups = widget
    tex_id = native.callbacks[0](b"1234", 1, 1, 1)
    native.callbacks[1](tex_id)
    dialog.close()
    assert not device.textures[0][0].destroyed
    dialog._gui._frame_active = False
    cleanups[0]()
    assert device.textures[0][0].destroyed
    assert len(backend.unregistered) == 1
