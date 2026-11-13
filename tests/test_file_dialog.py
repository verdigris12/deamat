from pathlib import Path
from types import SimpleNamespace

import pytest

from deamat.widgets.file_dialog import DialogResult, FileDialog
import deamat.widgets.file_dialog as dialog_module


class NativeDialog:
    def __init__(self):
        self.done = False
        self.results = []
        self.close_count = 0
        self.referenced = False
        self.submitted = False

    def open(self, *args):
        return True

    def save(self, *args):
        return True

    def is_done(self, key):
        self.referenced = True
        self.submitted = False
        return self.done

    def has_result(self):
        return bool(self.results)

    def get_result(self):
        return SimpleNamespace(path=lambda: self.results[0])

    def get_results(self):
        return [SimpleNamespace(path=lambda path=path: path) for path in self.results]

    def close(self):
        assert not self.referenced or self.submitted
        self.close_count += 1


def submit_frame(dialog, native):
    native.submitted = True
    dialog._gui._frame_active = False
    while dialog._gui.posts:
        dialog._gui.posts.pop(0)()
    dialog._gui._frame_active = True


@pytest.fixture
def widget(monkeypatch):
    native = NativeDialog()
    monkeypatch.setattr(dialog_module.im_file_dialog, "FileDialog", SimpleNamespace(instance=lambda: native))
    cleanups = []
    context = object()
    monkeypatch.setattr(dialog_module.imgui, "get_current_context", lambda: context)
    posts = []
    gui = SimpleNamespace(imgui_context=context, add_cleanup=cleanups.append, _frame_active=True,
                          _require_open=lambda: None, _assert_ui_thread=lambda: None,
                          post=posts.append, posts=posts)
    dialog = FileDialog(gui)
    yield dialog, native, cleanups
    native.submitted = True
    gui._frame_active = False
    for cleanup in cleanups:
        cleanup()


def test_completion_cancellation_and_overlap(widget, tmp_path):
    dialog, native, _ = widget
    dialog.open("Open", "Images .png", "/tmp", multiselect=True)
    assert dialog.draw() is None
    with pytest.raises(RuntimeError, match="already active"):
        dialog.save("Save")
    native.results = ["/tmp/a.png", "/tmp/b.png"]
    native.done = True
    assert dialog.draw() == DialogResult((Path("/tmp/a.png"), Path("/tmp/b.png")))
    assert not dialog.active
    assert dialog.draw() is None
    assert native.close_count == 0
    with pytest.raises(RuntimeError, match="already active"):
        dialog.select_folder("Folder")
    submit_frame(dialog, native)
    dialog.select_folder("Folder", "/tmp")
    native.results = []
    assert dialog.draw() == DialogResult(())
    submit_frame(dialog, native)
    dialog.save("Save", "PNG .png")
    native.results = [str(tmp_path / "out.png")]
    assert dialog.draw() == DialogResult((tmp_path / "out.png",))


@pytest.mark.parametrize("choice", ["Replace", "Cancel", "Escape"])
def test_existing_save_waits_for_confirmation(widget, tmp_path, monkeypatch, choice):
    dialog, native, _ = widget
    second = FileDialog(dialog._gui)
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
    with pytest.raises(RuntimeError, match="already active"):
        second.open("Other")
    pressed.add(choice)
    expected = (target,) if choice == "Replace" else ()
    assert dialog.draw() == DialogResult(expected)
    assert not dialog.active
    assert dialog.draw() is None
    submit_frame(dialog, native)
    second.open("Other")


@pytest.mark.parametrize("failure", ["start", "poll", "result"])
def test_request_recovers_after_native_failure(widget, monkeypatch, failure):
    dialog, native, _ = widget
    original_open, original_result = native.open, native.get_result

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
        method = {"poll": "is_done", "result": "get_result"}[failure]
        monkeypatch.setattr(native, method, fail)
        with pytest.raises(ValueError, match="native failure"):
            dialog.draw()
    assert not dialog.active
    monkeypatch.setattr(native, "open", original_open)
    monkeypatch.setattr(native, "get_result", original_result)
    submit_frame(dialog, native)
    monkeypatch.setattr(native, "is_done", lambda key: native.done)
    native.done = False
    dialog.open("Again")
    assert dialog.active

def test_deferred_close_failure_releases_owner(widget, monkeypatch):
    first, native, _ = widget
    second = FileDialog(first._gui)
    first.open("First")
    native.done = True
    assert first.draw() == DialogResult(())

    def fail():
        raise ValueError("native failure")

    original_close = native.close
    monkeypatch.setattr(native, "close", fail)
    with pytest.raises(ValueError, match="native failure"):
        submit_frame(first, native)
    monkeypatch.setattr(native, "close", original_close)
    first._gui._frame_active = True
    second.open("Second")


def test_wrong_context_rejected(widget, monkeypatch):
    dialog, _, _ = widget
    monkeypatch.setattr(dialog_module.imgui, "get_current_context", lambda: object())
    with pytest.raises(RuntimeError, match="active ImGui frame"):
        dialog.open("Open")

def test_singleton_ownership_and_cleanup(widget):
    first, native, cleanups = widget
    second = FileDialog(first._gui)
    first.open("First")
    with pytest.raises(RuntimeError, match="already active"):
        second.open("Second")
    second.close()
    assert native.close_count == 0
    assert first.active
    cleanups[0]()
    assert native.close_count == 0
    submit_frame(first, native)
    assert native.close_count == 1
    third = FileDialog(first._gui)
    third.open("Third")
    native.done = True
    assert third.draw() == DialogResult(())
    submit_frame(first, native)
    fourth = FileDialog(first._gui)
    fourth.open("Fourth")
    assert fourth.active


def test_modal_close_requires_correct_scope(widget, monkeypatch):
    first, native, _ = widget
    second = FileDialog(first._gui)
    first.open("First")
    assert first.draw() is None
    monkeypatch.setattr(dialog_module.imgui, "begin_popup_modal", lambda title: (False, True))
    with pytest.raises(RuntimeError, match="same ImGui window"):
        first.close()
    with pytest.raises(RuntimeError, match="already active"):
        second.open("Second")
    monkeypatch.setattr(dialog_module.imgui, "begin_popup_modal", lambda title: (True, True))
    monkeypatch.setattr(dialog_module.imgui, "close_current_popup", lambda: None)
    monkeypatch.setattr(dialog_module.imgui, "end_popup", lambda: None)
    first.close()
    assert native.close_count == 0
    submit_frame(first, native)
    assert native.close_count == 1
    second.open("Second")


