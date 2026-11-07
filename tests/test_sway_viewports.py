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
        imgui.end()
        tmp = Path(state_path + ".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(state_path)

    gui.update = update
    gui.run()


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

        p = _wait(pane, "detached native pane")
        m = _wait(main, "main native window")
        assert p["type"] == "floating_con", p
        assert p["window_properties"]["class"] != m["window_properties"]["class"], (p, m)
        cmd(m["id"], "floating enable")
        d = settled("initial")
        for output in ("HEADLESS-2", "HEADLESS-1", "HEADLESS-2"):
            cmd(p["id"], f"move container to output {output}")
            _wait(lambda: next((n for n in _nodes(tree()) if n.get("name") == output and any(x.get("id") == p["id"] for x in _nodes(n))), None), f"move to {output}")
            d = settled(f"move-{output}-{d['frame']}", d["frame"])
        old_pane_size = d["native_size"]
        cmd(p["id"], "resize set 700 500")
        d = settled("resize-pane", d["frame"], ("native_size", old_pane_size))
        old_main_size = d["main_size"]
        cmd(m["id"], "resize set 900 650")
        d = settled("resize-main", d["frame"], ("main_size", old_main_size))
        # Overlap alone is not a docking gesture.
        mr = _wait(main, "main after resize")["rect"]
        old_pane_pos = d["native_pos"]
        cmd(p["id"], f"move absolute position {mr['x'] + 100} {mr['y'] + 100}")
        d = settled("overlap", d["frame"], ("native_pos", old_pane_pos))
        assert all(abs(a-b) <= 2 for a, b in zip(d["native_pos"], [mr["x"] + 100, mr["y"] + 100])), d
        assert pane(), d
        pr = pane()["rect"]
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
