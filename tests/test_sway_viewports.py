"""Opt-in native Sway/XWayland regression; never connects to the user's display.

Run with DEAMAT_SWAY_ACCEPTANCE=1 python -m pytest -s tests/test_sway_viewports.py.
Requires sway, swaymsg, grim and a working software Vulkan driver.
The test starts its own compositor and records screenshots in the pytest temp dir.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest


def _worker(state_path):
    # Import deamat first: imgui-bundle and Python GLFW must share a library.
    from deamat import GUI, GUIState, imgui
    import glfw
    from deamat._glfw_viewports import _window

    gui = GUI(GUIState(), width=1000, height=700, update_mode="ondemand", viewports=True)
    imgui.get_io().set_ini_filename("")
    opened = True
    frames = 0
    control = Path(state_path + ".drag")
    sequence = {"step": None, "viewport": None, "start": None, "samples": []}
    stopped = threading.Event()
    original_new_frame = imgui.backends.glfw_new_frame
    original_render = gui._viewport_host.render

    def presented_render():
        original_render()
        path = Path(state_path)
        if not path.exists():
            return
        d = json.loads(path.read_text())
        viewport = next((v for v in imgui.get_platform_io().viewports
                         if v.id_ == d.get("viewport")), None)
        win = _window(viewport) if viewport else None
        if win:
            d["native_pos"] = list(glfw.get_window_pos(win))
            d["native_size"] = list(glfw.get_window_size(win))
        tmp = Path(state_path + ".presented.tmp")
        tmp.write_text(json.dumps(d))
        tmp.replace(state_path + ".presented")

    gui._viewport_host.render = presented_render

    def input_frame():
        original_new_frame()
        if sequence["step"] is None and control.exists() and sequence["start"] is not None:
            sequence["step"] = 0
        step = sequence["step"]
        if step is None or step > 30:
            return
        io = imgui.get_io()
        io.add_mouse_viewport_event(sequence["viewport"])
        x, y = sequence["start"]
        if step >= 7:
            x, y = x + 180, y - 120
        io.add_mouse_pos_event(x, y)
        if step == 3:
            io.add_mouse_button_event(0, True)
        elif step == 27:
            io.add_mouse_button_event(0, False)
        sequence["step"] += 1

    imgui.backends.glfw_new_frame = input_frame

    def wake_for_control():
        while not stopped.wait(.05):
            if control.exists() and sequence["step"] is None:
                gui.request_draw()

    threading.Thread(target=wake_for_control, daemon=True).start()

    def update(_state, _gui, _dt):
        nonlocal opened, frames
        frames += 1
        if not opened:
            Path(state_path).write_text(json.dumps({"frame": frames, "open": False}))
            return
        dock_host_viewport = imgui.get_window_viewport().id_
        main_vp = imgui.get_main_viewport()
        # Place the pane outside the actual main viewport so this is an
        # intentional detach even when the compositor initially tiles main.
        x = main_vp.pos.x + main_vp.size.x + 100
        if x + 450 > 4480:
            x = 100
        imgui.set_next_window_pos((x, 1500), imgui.Cond_.first_use_ever)
        imgui.set_next_window_size((450, 600), imgui.Cond_.first_use_ever)
        visible, opened = imgui.begin("Viewport acceptance pane", opened)
        vp = imgui.get_window_viewport()
        win = _window(vp)
        if win and vp.id_ != imgui.get_main_viewport().id_ and sequence["step"] is None:
            native_x, native_y = glfw.get_window_pos(win)
            sequence["viewport"] = vp.id_
            sequence["start"] = (native_x + 40, native_y + imgui.get_frame_height() / 2)
        if visible and opened:
            imgui.text("Native viewport acceptance")
            imgui.text("A square below must remain square after resizing")
            p = imgui.get_cursor_screen_pos()
            imgui.get_window_draw_list().add_rect_filled(p, (p.x + 100, p.y + 100), 0xff44ccff)
            imgui.dummy((100, 100))
        data = {"frame": frames, "open": opened, "viewport": vp.id_,
                "main_viewport": imgui.get_main_viewport().id_,
                "dock_host_viewport": dock_host_viewport,
                "viewport_pos": [vp.pos.x, vp.pos.y], "viewport_size": [vp.size.x, vp.size.y],
                "native_pos": list(glfw.get_window_pos(win)) if win else None,
                "native_size": list(glfw.get_window_size(win)) if win else None,
                "main_size": list(glfw.get_window_size(gui.canvas._window)),
                "errors": [str(e) for e in gui.errors]}
        step = sequence["step"]
        if step is not None:
            window = imgui.internal.find_window_by_name("Viewport acceptance pane")
            moving = imgui.get_current_context().moving_window
            if 12 <= step <= 27:
                sequence["samples"].append({
                    "frame": frames,
                    "moving": bool(moving and moving.name == "Viewport acceptance pane"),
                    "mouse_down": bool(imgui.get_io().mouse_down[0]),
                    "mouse_pos": [imgui.get_io().mouse_pos.x, imgui.get_io().mouse_pos.y],
                    "window_pos": [window.pos.x, window.pos.y],
                    "viewport_pos": [vp.pos.x, vp.pos.y],
                    "native_pos": list(glfw.get_window_pos(win)),
                })
            data["drag_samples"] = sequence["samples"]
            data["drag_done"] = step > 30
            if step <= 30:
                gui.request_draw()
        imgui.end()
        tmp = Path(state_path + ".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(state_path)

    gui.update = update
    try:
        gui.run()
    finally:
        stopped.set()
        imgui.backends.glfw_new_frame = original_new_frame


def _wait(predicate, description, timeout=15):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (FileNotFoundError, json.JSONDecodeError, subprocess.CalledProcessError):
            pass
        time.sleep(.1)
    raise AssertionError(f"timed out waiting for {description}; last={last!r}")


def _nodes(node):
    yield node
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        yield from _nodes(child)


@pytest.mark.skipif(os.environ.get("DEAMAT_SWAY_ACCEPTANCE") != "1", reason="explicit native acceptance opt-in required")
def test_two_output_native_viewports_and_pane_close(tmp_path):
    for tool in ("sway", "swaymsg", "grim"):
        if not shutil.which(tool):
            pytest.fail(f"native acceptance requires {tool}")
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    config = tmp_path / "sway.conf"
    endpoints = tmp_path / "endpoints"
    state = tmp_path / "state.json"
    config.write_text(f'''xwayland force
output HEADLESS-1 mode 2560x1440 position 1920 1080 scale 1
output HEADLESS-2 mode 1920x1080 position 0 1440 scale 1
for_window [class="^DeamatViewport$" instance="^deamat-viewport$"] floating enable
exec sh -c 'printf \"DISPLAY=%s\\nWAYLAND_DISPLAY=%s\\nSWAYSOCK=%s\\n\" \"$DISPLAY\" \"$WAYLAND_DISPLAY\" \"$SWAYSOCK\" > {endpoints}'
''')
    env = os.environ.copy()
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "SWAYSOCK", "I3SOCK"):
        env.pop(key, None)
    env.update(XDG_RUNTIME_DIR=str(runtime), WLR_BACKENDS="headless", WLR_HEADLESS_OUTPUTS="2",
               WLR_RENDERER="pixman", LIBGL_ALWAYS_SOFTWARE="1", WGPU_BACKEND_TYPE="Vulkan")
    log = (tmp_path / "sway.log").open("w")
    sway = subprocess.Popen(["sway", "-c", str(config)], env=env, stdout=log, stderr=log)
    worker = None
    worker_log = None
    try:
        _wait(lambda: endpoints.exists() and endpoints.stat().st_size, "isolated compositor endpoints")
        exported = dict(line.split("=", 1) for line in endpoints.read_text().splitlines() if "=" in line)
        assert exported.get("SWAYSOCK") and exported.get("WAYLAND_DISPLAY") and exported.get("DISPLAY"), exported
        env.update({key: exported[key] for key in ("SWAYSOCK", "WAYLAND_DISPLAY", "DISPLAY")})
        # Force GLFW onto this compositor's Xwayland, not native Wayland.
        client_env = env.copy()
        client_env.pop("WAYLAND_DISPLAY")
        worker_log = (tmp_path / "worker.log").open("w")
        worker = subprocess.Popen([sys.executable, __file__, "--worker", str(state)], env=client_env,
                                  stdout=worker_log, stderr=worker_log)

        def data():
            return json.loads(state.read_text())

        def tree():
            return json.loads(subprocess.check_output(["swaymsg", "-r", "-t", "get_tree"], env=env))

        def pane():
            return next((n for n in _nodes(tree()) if n.get("name") == "Viewport acceptance pane" and n.get("window")), None)

        def main():
            return next((n for n in _nodes(tree()) if n.get("window") and n.get("window_properties", {}).get("class") != "DeamatViewport"), None)

        def cmd(selector, command):
            result = json.loads(subprocess.check_output(["swaymsg", "-r", f"[con_id={selector}] {command}"], env=env))
            assert all(item["success"] for item in result), result

        def settled(label, previous=0, changed=None):
            def check():
                d = data()
                if d["frame"] <= previous or not d["native_size"] or d["viewport"] == d["main_viewport"]:
                    return False
                if changed and d[changed[0]] == changed[1]:
                    return False
                if any(abs(a-b) > 2 for a, b in zip(d["native_size"], d["viewport_size"])):
                    return False
                if any(abs(a-b) > 2 for a, b in zip(d["native_pos"], d["viewport_pos"])):
                    return False
                assert min(d["native_size"]) > 100, d
                assert d["dock_host_viewport"] == d["main_viewport"], d
                assert not d["errors"], d
                return d
            d = _wait(check, label)
            for output in ("HEADLESS-1", "HEADLESS-2"):
                subprocess.run(["grim", "-o", output, str(tmp_path / f"{label}-{output}.png")], env=env, check=True)
            return d
        def presented_fullscreen(label, enabled, previous):
            def check():
                d = json.loads(Path(str(state) + ".presented").read_text())
                n = pane()
                if not n or bool(n.get("fullscreen_mode")) != enabled or d["frame"] <= previous:
                    return False
                if not d.get("native_size"):
                    return False
                rect, client = n["rect"], n["window_rect"]
                origin = (rect["x"] + client["x"], rect["y"] + client["y"])
                size = (client["width"], client["height"])
                for actual, expected in ((d["native_pos"], origin), (d["native_size"], size),
                                         (d["viewport_pos"], d["native_pos"]),
                                         (d["viewport_size"], d["native_size"])):
                    if any(abs(a-b) > 2 for a, b in zip(actual, expected)):
                        return False
                assert not d["errors"], d
                return d
            _wait(check, label)
            for output in ("HEADLESS-1", "HEADLESS-2"):
                subprocess.run(["grim", "-o", output, str(tmp_path / f"{label}-{output}.png")],
                               env=env, check=True)
            return _wait(check, label + " after capture")


        p = _wait(pane, "detached native pane")
        m = _wait(main, "main native window")
        assert p["type"] == "floating_con", p
        assert p["window_properties"]["class"] != m["window_properties"]["class"], (p, m)
        cmd(m["id"], "floating enable")
        d = settled("initial")
        control = Path(str(state) + ".drag")
        control.write_text("start")
        d = _wait(lambda: (s if (s := data()).get("drag_done") else None),
                  "synthetic ImGui caption drag")
        samples = d["drag_samples"]
        assert len(samples) >= 10, samples
        assert all(sample["moving"] and sample["mouse_down"] for sample in samples), samples
        assert len({tuple(sample["mouse_pos"]) for sample in samples}) == 1, samples
        assert len({tuple(sample["native_pos"]) for sample in samples}) == 1, samples
        for sample in samples:
            assert sample["window_pos"] == pytest.approx(sample["native_pos"], abs=2), sample
            assert sample["viewport_pos"] == pytest.approx(sample["native_pos"], abs=2), sample
        assert not d["errors"], d
        current_output = next(n["name"] for n in _nodes(tree())
                              if n.get("type") == "output"
                              and any(x.get("id") == p["id"] for x in _nodes(n)))
        other_output = "HEADLESS-1" if current_output == "HEADLESS-2" else "HEADLESS-2"
        for output in (other_output, current_output, other_output):
            cmd(p["id"], f"move container to output {output}")
            _wait(lambda: next((n for n in _nodes(tree()) if n.get("name") == output and any(x.get("id") == p["id"] for x in _nodes(n))), None), f"move to {output}")
            d = settled(f"move-{output}-{d['frame']}", d["frame"])
        old_pane_size = d["native_size"]
        cmd(p["id"], "resize set 700 500")
        d = settled("resize-pane", d["frame"], ("native_size", old_pane_size))
        before_fullscreen = d["native_size"]
        cmd(p["id"], "fullscreen enable")
        d = presented_fullscreen("fullscreen-pane", True, d["frame"])
        fullscreen_size = d["native_size"]
        cmd(p["id"], "fullscreen disable")
        d = presented_fullscreen("restore-pane", False, d["frame"])
        assert d["native_size"] == pytest.approx(before_fullscreen, abs=2)
        old_main_size = d["main_size"]
        cmd(m["id"], "resize set 900 650")
        d = settled("resize-main", d["frame"], ("main_size", old_main_size))
        # Overlap alone is not a docking gesture.
        mr = _wait(main, "main after resize")["rect"]
        old_pane_pos = d["native_pos"]
        cmd(p["id"], f"move absolute position {mr['x'] + 100} {mr['y'] + 100}")
        d = settled("overlap", d["frame"], ("native_pos", old_pane_pos))
        p = pane()
        assert p is not None
        pr = p["rect"]
        client = p["window_rect"]
        assert all(abs(a-b) <= 2 for a, b in zip(
            d["native_pos"], [pr["x"] + client["x"], pr["y"] + client["y"]]
        )), d
        assert max(pr["x"], mr["x"]) < min(pr["x"] + pr["width"], mr["x"] + mr["width"])
        assert max(pr["y"], mr["y"]) < min(pr["y"] + pr["height"], mr["y"] + mr["height"])
        cmd(p["id"], "kill")
        _wait(lambda: not data()["open"], "pane close delivered to ImGui")
        _wait(lambda: pane() is None, "native pane destruction")
        assert worker.poll() is None
        assert main() is not None
        cmd(m["id"], "kill")
        _wait(lambda: worker.poll() is not None, "main close after pane close")
        assert worker.returncode == 0
    finally:
        if worker and worker.poll() is None:
            worker.terminate()
            worker.wait(timeout=10)
        sway.terminate()
        sway.wait(timeout=10)
        log.close()
        if worker_log is not None:
            worker_log.close()


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--worker":
    _worker(sys.argv[2])
