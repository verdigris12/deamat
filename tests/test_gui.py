import asyncio
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import threading
import multiprocessing as mp
import os
from pathlib import Path
import signal
import sys
import time
from types import SimpleNamespace

import pytest

import deamat.gui as gui_module
from deamat.gui import GUI
from deamat.guistate import GUIState


class NativeSurface:
    def __init__(self, gui):
        self.gui = gui

    def get_logical_size(self):
        return (640, 480)


class NativeHost:
    def __init__(self, gui, enabled):
        self.gui = gui
        self.enabled = enabled

    def pre_new_frame(self):
        pass

    def post_new_frame(self):
        pass

    def after_frame(self):
        pass

    def close(self):
        pass

    def pixel_ratio(self):
        return 1.0


class Runner:
    def __init__(self):
        self.params = None
        self.teardowns = 0
        self.wakeup_threads = []

    def setup(self, params):
        self.params = params

    def render(self):
        self.params.callbacks.show_gui()

    def teardown(self):
        self.teardowns += 1

    def wake(self):
        self.wakeup_threads.append(threading.get_ident())

class Executor:
    def __init__(self, **options):
        self.options = options
        self.futures = []
        self.shutdown_calls = []

    def submit(self, job, *args):
        future = Future()
        self.futures.append(future)
        return future

    def shutdown(self, **options):
        self.shutdown_calls.append(options)


@pytest.fixture
def gui_factory(monkeypatch):
    render_loop = Runner()
    monkeypatch.setattr(gui_module.immapp.manual_render, "setup_from_runner_params", render_loop.setup)
    monkeypatch.setattr(gui_module.immapp.manual_render, "render", render_loop.render)
    monkeypatch.setattr(gui_module.immapp.manual_render, "tear_down", render_loop.teardown)
    monkeypatch.setattr(gui_module, "NativeWindow", NativeSurface)
    monkeypatch.setattr(gui_module, "GlfwViewportHost", NativeHost)
    monkeypatch.setattr(gui_module, "_window", lambda viewport: object())
    monkeypatch.setattr(gui_module.imgui, "get_main_viewport", lambda: object())
    monkeypatch.setattr(gui_module.imgui, "get_io", lambda: SimpleNamespace(config_flags=0))
    monkeypatch.setattr(gui_module.imgui, "get_current_context", lambda: None)
    monkeypatch.setattr(gui_module.imgui, "set_current_context", lambda context: None)
    monkeypatch.setattr(gui_module.imgui.internal, "error_recovery_store_state", lambda state: None)
    monkeypatch.setattr(gui_module.glfw, "make_context_current", lambda window: None)
    monkeypatch.setattr(gui_module.glfw, "post_empty_event", render_loop.wake)
    monkeypatch.setattr(gui_module, "ProcessPoolExecutor", Executor)
    instances = []

    def create(state=None, **options):
        gui = GUI(state if state is not None else GUIState(), **options)
        instances.append(gui)
        return gui

    yield create, render_loop
    for gui in instances:
        gui.close()


def on_worker(callback):
    results = []
    failures = []

    def run():
        try:
            results.append(callback())
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    if failures:
        raise failures[0]
    return results[0]

def test_global_input_handlers(gui_factory):
    create, _ = gui_factory
    gui = create(viewports=False)
    events = []
    gui.add_input_handler(events.append, "pointer_up", "key_up")
    gui.add_input_handler(events.append, "pointer_up")
    event = {"event_type": "pointer_up", "button": 1, "x": 2, "y": 3}
    gui._emit_input(event)
    assert events == [event]
    gui.remove_input_handler(events.append, "pointer_up", "key_up")
    gui._emit_input(event)
    assert events == [event]
    gui.close()
    gui.remove_input_handler(events.append, "pointer_up")


def test_input_disposal_stops_following_handlers(gui_factory):
    create, _ = gui_factory
    gui = create()
    calls = []
    gui.add_input_handler(lambda event: gui.close(), "key_up")
    gui.add_input_handler(calls.append, "key_up")
    gui._emit_input({"event_type": "key_up", "key": "a"})
    assert calls == []


def test_post_preserves_state_and_runs_on_main_thread(gui_factory):
    create, render_loop = gui_factory
    state = GUIState()
    state.lock = threading.Lock()  # Deliberately not deepcopyable.
    state.values = []
    gui = create(state)
    main_thread = threading.get_ident()

    def append(value):
        state.values.append(value)
        return threading.get_ident(), state.lock

    first = on_worker(lambda: gui.post(append, 1))
    second = on_worker(lambda: gui.post(append, 2))
    assert not first.done()
    assert state.values == []
    assert render_loop.wakeup_threads == []  # The native loop has not started.
    gui._dispatch_ready = True
    gui._drain_posts()
    assert first.result() == (main_thread, state.lock)
    assert second.result() == (main_thread, state.lock)
    assert state.values == [1, 2]
    assert gui.state is state


def test_post_errors_cancellation_and_close_are_terminal(gui_factory):
    create, _ = gui_factory
    gui = create()
    called = []
    cancelled = gui.post(called.append, "cancelled")
    assert cancelled.cancel()

    def fail():
        raise ValueError("bad edit")

    failed = gui.post(fail)
    following = gui.post(called.append, "following")
    gui._drain_posts()
    with pytest.raises(ValueError, match="bad edit"):
        failed.result()
    assert cancelled.cancelled()
    assert following.result() is None
    assert called == ["following"]
    pending = gui.post(called.append, "closed")
    gui.close()
    assert pending.cancelled()
    with pytest.raises(RuntimeError, match="closed"):
        gui.post(called.append, "late").result()
    assert called == ["following"]


def test_worker_wakeup_is_marshaled_to_render_loop(gui_factory):
    create, render_loop = gui_factory
    gui = create(update_mode="ondemand")
    gui._dispatch_ready = True
    gui._drain_posts()
    gui._draw_requested = False
    future = on_worker(lambda: gui.post(threading.get_ident))
    on_worker(gui.request_draw)
    assert gui._draw_requested
    assert len(render_loop.wakeup_threads) == 2
    assert not future.done()
    gui._drain_posts()
    assert future.result() == threading.get_ident()


def test_submit_from_update_and_job_completion_stay_on_gui_thread(gui_factory, monkeypatch):
    create, render_loop = gui_factory
    gui = create()
    callbacks = []
    submitted = []
    monkeypatch.setattr(gui, "_create_main_window", lambda: None)
    monkeypatch.setattr(gui_module.imgui, "end", lambda: None)

    def update(state, owner, dt):
        submitted.append(owner.submit_job(int, "7", callback=lambda result: callbacks.append(
            (result, threading.get_ident())
        )))

    gui.update = update
    gui._draw_imgui()
    future = submitted[0]
    assert gui.job_counter == 1
    on_worker(lambda: future.set_result(7))
    assert callbacks == []
    assert gui.job_counter == 1
    gui._drain_posts()
    assert callbacks == [(7, threading.get_ident())]
    assert gui.job_counter == 0
    assert future.result() == 7


def test_compute_and_callback_errors_are_observable(gui_factory):
    create, _ = gui_factory
    gui = create()
    called = []
    failed = gui.submit_job(int, callback=called.append)
    error = ValueError("compute failed")
    on_worker(lambda: failed.set_exception(error))
    gui._drain_posts()
    assert gui.errors == [error]
    assert called == []
    with pytest.raises(ValueError, match="compute failed"):
        failed.result()

    def bad_callback(result):
        raise LookupError("callback failed")

    successful = gui.submit_job(int, callback=bad_callback)
    on_worker(lambda: successful.set_result(9))
    gui._drain_posts()
    assert successful.result() == 9
    assert isinstance(gui.errors[-1], LookupError)
    assert gui.job_counter == 0


def test_cancelled_job_updates_status_without_callback(gui_factory):
    create, _ = gui_factory
    gui = create()
    called = []
    future = gui.submit_job(int, callback=called.append)
    assert future.cancel()
    gui._drain_posts()
    assert gui.job_counter == 0
    assert not called
    assert not gui.errors


def test_close_is_idempotent_and_does_not_deliver_late_results(gui_factory):
    create, render_loop = gui_factory
    gui = create()
    cleanups = []
    gui.add_cleanup(lambda: cleanups.append(("first", threading.get_ident())))
    gui.add_cleanup(lambda: cleanups.append(("second", threading.get_ident())))
    results = []
    pending = gui.submit_job(int, callback=results.append)
    queued = gui.submit_job(int, callback=results.append)
    gui.close()
    gui.close()
    assert pending.cancelled()
    assert queued.cancelled()
    assert gui._posts.empty()
    assert results == []
    assert gui.job_counter == 0
    assert cleanups == [("second", threading.get_ident()), ("first", threading.get_ident())]
    assert render_loop.teardowns == 1
    assert gui.executor.shutdown_calls == [{"wait": True, "cancel_futures": True}]
    assert gui.asyncio_loop.is_closed()
    with pytest.raises(RuntimeError, match="closed"):
        gui.add_cleanup(lambda: None)


def test_cleanup_failure_does_not_skip_other_disposal(gui_factory):
    create, render_loop = gui_factory
    gui = create()
    disposed = []
    gui.add_cleanup(lambda: disposed.append(True))

    def bad_cleanup():
        raise RuntimeError("cleanup failed")

    gui.add_cleanup(bad_cleanup)
    gui.close()
    assert disposed == [True]
    assert str(gui.errors[-1]) == "cleanup failed"
    assert render_loop.teardowns == 1


def test_async_coroutine_can_await_gui_callback_and_expose_errors(gui_factory):
    create, _ = gui_factory
    gui = create()
    posted = threading.Event()
    value = []

    async def work():
        future = gui.post(lambda: (value.append(3), threading.get_ident())[1])
        posted.set()
        return await asyncio.wrap_future(future)

    future = gui.exec_coroutine(work())
    assert posted.wait(timeout=2)
    assert value == []
    gui._drain_posts()
    assert future.result(timeout=2) == threading.get_ident()
    assert value == [3]

    async def fail():
        raise ValueError("coroutine failed")

    failed = gui.exec_coroutine(fail())
    reported = threading.Event()
    failed.add_done_callback(lambda done: reported.set())
    assert reported.wait(timeout=2)
    with pytest.raises(ValueError, match="coroutine failed"):
        failed.result()
    gui._drain_posts()
    assert str(gui.errors[-1]) == "coroutine failed"
    gui.close()
    assert not gui.asyncio_thread.is_alive()
    assert gui.asyncio_loop.is_closed()


def test_close_cancels_coroutine_waiting_on_ui_post(gui_factory):
    create, _ = gui_factory
    gui = create()
    posted = threading.Event()
    finished = threading.Event()

    async def work():
        try:
            future = gui.post(lambda: None)
            posted.set()
            await asyncio.wrap_future(future)
        finally:
            finished.set()

    future = gui.exec_coroutine(work())
    assert posted.wait(timeout=2)
    gui.close()
    assert future.cancelled()
    assert finished.is_set()
    assert not gui.asyncio_thread.is_alive()


def test_run_options_spawn_policy_and_window_close(gui_factory):
    create, render_loop = gui_factory
    gui = create(title="A figure", max_fps=24, update_mode="ondemand", max_workers=2)
    assert gui.executor.options["max_workers"] == 2
    assert gui.executor.options["mp_context"].get_start_method() == "spawn"
    gui.post(gui.close)
    gui.run()
    assert render_loop.teardowns == 1
    with pytest.raises(RuntimeError, match="closed"):
        gui.run()


def test_ui_owned_methods_reject_worker_mutation(gui_factory):
    create, _ = gui_factory
    gui = create()
    for callback in (gui.close, lambda: gui.submit_job(int), lambda: gui.add_cleanup(lambda: None)):
        with pytest.raises(RuntimeError, match="GUI.post"):
            on_worker(callback)
    assert not gui._closed


def _worker_identity(value):
    import multiprocessing
    return value * 2, multiprocessing.get_start_method()


def test_real_spawn_job_returns_result_and_dispatches_callback(gui_factory, monkeypatch):
    create, _ = gui_factory
    monkeypatch.setattr(gui_module, "ProcessPoolExecutor", ProcessPoolExecutor)
    gui = create(max_workers=1)
    received = []
    future = gui.submit_job(_worker_identity, 21, callback=received.append)
    queued = threading.Event()
    future.add_done_callback(lambda done: queued.set())
    assert future.result(timeout=30) == (42, "spawn")
    assert queued.wait(timeout=2)
    assert received == []
    gui._drain_posts()
    assert received == [(42, "spawn")]
    assert gui.job_counter == 0
    gui.close()


def _blocking_worker(ready, ignore_term=False):
    if ignore_term:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path(ready).write_text(str(os.getpid()))
    while True:
        time.sleep(1)


def _pool_parent(ready):
    executor = ProcessPoolExecutor(
        max_workers=1, mp_context=mp.get_context("spawn"),
        initializer=gui_module._worker_initializer, initargs=(os.getpid(),),
    )
    executor.submit(_blocking_worker, ready, True)
    while True:
        time.sleep(1)


def _wait_for_file(path, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            value = path.read_text()
            if value:
                return value
        time.sleep(0.02)
    pytest.fail(f"worker did not create {path}")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux signals and process state")
@pytest.mark.parametrize("close_path", ["close", "run"])
def test_close_terminates_owned_workers_before_cleanup(
    gui_factory, monkeypatch, tmp_path, close_path
):
    create, _ = gui_factory
    monkeypatch.setattr(gui_module, "ProcessPoolExecutor", ProcessPoolExecutor)
    gui = create(max_workers=1)
    ready = tmp_path / "running"
    queued_ready = tmp_path / "queued"
    results = []
    running = gui.submit_job(_blocking_worker, str(ready), True, callback=results.append)
    _wait_for_file(ready)
    workers = tuple(gui.executor._processes.values())
    queued = gui.submit_job(_blocking_worker, str(queued_ready), callback=results.append)
    alive_at_cleanup = []
    gui.add_cleanup(lambda: alive_at_cleanup.extend(p.is_alive() for p in workers))
    start = time.monotonic()
    if close_path == "close":
        gui.close()
    else:
        gui.post(gui.close)
        gui.run()
    assert time.monotonic() - start < 10
    gui.close()
    assert alive_at_cleanup == [False]
    assert all(not process.is_alive() for process in workers)
    assert running.done() and queued.done()
    assert not queued_ready.exists()
    assert results == []
    assert gui._posts.empty()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death signal")
def test_sigkill_parent_kills_pool_worker(tmp_path):
    ready = tmp_path / "worker"
    parent = mp.get_context("spawn").Process(target=_pool_parent, args=(str(ready),))
    parent.start()
    worker_pid = None
    try:
        worker_pid = int(_wait_for_file(ready))
        parent.kill()
        parent.join(timeout=10)
        assert not parent.is_alive()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                state = Path(f"/proc/{worker_pid}/stat").read_text().split(") ", 1)[1][0]
            except FileNotFoundError:
                worker_pid = None
                break
            if state == "Z":
                worker_pid = None
                break
            time.sleep(0.02)
        else:
            pytest.fail(f"worker {worker_pid} survived its parent")
    finally:
        if parent.is_alive():
            parent.kill()
            parent.join()
        if worker_pid is not None:
            try:
                os.kill(worker_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death signal")
def test_worker_initializer_exits_if_parent_already_changed():
    with ProcessPoolExecutor(
        max_workers=1, mp_context=mp.get_context("spawn"),
        initializer=gui_module._worker_initializer, initargs=(0,),
    ) as executor:
        future = executor.submit(_worker_identity, 1)
        with pytest.raises(BrokenProcessPool):
            future.result(timeout=30)


def test_figures_are_lazy_and_removed_views_are_disposed(monkeypatch):
    state = GUIState()
    made = []
    closed = []
    disposed = []
    monkeypatch.setattr("deamat.guistate.plt.close", closed.append)
    state.add_figure("plot", lambda owner: made.append(owner))
    entry = state.figures["plot"]
    assert made == []
    assert entry["figure"] is None
    assert entry["width"] == 0
    assert entry["dirty"] and entry["texture_dirty"]
    figure = object()
    entry["figure"] = figure
    entry["_dispose_view"] = lambda: disposed.append(figure)
    state.invalidate_figure("plot", width=300)
    assert entry["width"] == 300
    state.remove_figure("plot")
    assert "plot" not in state.figures
    assert disposed == [figure]
    assert closed == [figure]
    assert made == []


def test_replacing_figure_releases_previous_registration(monkeypatch):
    state = GUIState()
    disposed = []
    state.add_figure("plot", lambda owner: None)
    state.figures["plot"]["_dispose_view"] = lambda: disposed.append(True)
    state.add_figure("plot", lambda owner: None, width=200)
    assert disposed == [True]
    assert state.figures["plot"]["figure"] is None
    assert state.figures["plot"]["width"] == 200


def test_noncooperative_coroutine_shutdown_is_bounded_and_reported(gui_factory):
    create, render_loop = gui_factory
    gui = create()
    gui.asyncio_loop.close()
    stop_calls = []
    join_calls = []
    gui.asyncio_loop = SimpleNamespace(
        stop=lambda: None,
        call_soon_threadsafe=lambda callback: stop_calls.append(callback),
    )
    gui.asyncio_thread = SimpleNamespace(
        ident=123, join=lambda timeout: join_calls.append(timeout),
        is_alive=lambda: True,
    )
    gui.close()
    assert join_calls == [1.0]
    assert len(stop_calls) == 1
    assert "must cooperate with cancellation" in str(gui.errors[-1])
    assert render_loop.teardowns == 1


def test_close_from_update_waits_for_backend_render_completion(gui_factory, monkeypatch):
    create, runner = gui_factory
    gui = create()
    events = []
    monkeypatch.setattr(gui, "_create_main_window", lambda: events.append("begin"))
    monkeypatch.setattr(gui_module.imgui, "end", lambda: events.append("end"))
    gui.add_cleanup(lambda: events.append("cleanup"))

    def update(state, owner, dt):
        owner.close()
        assert runner.teardowns == 0
        events.append("close")

    def render():
        gui._draw_imgui()
        assert runner.teardowns == 0
        events.append("rendered")

    gui.update = update
    monkeypatch.setattr(gui_module.immapp.manual_render, "render", render)
    gui._render_frame()
    assert events == ["begin", "close", "end", "rendered", "cleanup"]
    assert runner.teardowns == 1
