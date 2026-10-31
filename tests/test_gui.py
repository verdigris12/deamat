import asyncio
from concurrent.futures import Future, ProcessPoolExecutor
from queue import Empty, SimpleQueue
import threading
from types import SimpleNamespace

import pytest

import deamat.gui as gui_module
from deamat.gui import GUI
from deamat.guistate import GUIState


class Canvas:
    def __init__(self, **options):
        self.options = options
        self.handlers = {}
        self.draw_requests = []
        self.close_count = 0

    def add_event_handler(self, callback, *events):
        for event in events:
            self.handlers[event] = callback

    def request_draw(self, callback=None):
        self.draw_requests.append((threading.get_ident(), callback))

    def get_logical_size(self):
        return (640, 480)

    def close(self):
        self.close_count += 1


class Loop:
    def __init__(self):
        self.pending = SimpleQueue()
        self.wakeup_threads = []

    def call_soon(self, callback, *args):
        self.pending.put((callback, args))

    def call_soon_threadsafe(self, callback, *args):
        self.wakeup_threads.append(threading.get_ident())
        self.pending.put((callback, args))

    def run(self):
        while True:
            try:
                callback, args = self.pending.get_nowait()
            except Empty:
                return
            callback(*args)


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
    render_loop = Loop()
    monkeypatch.setattr(gui_module, "loop", render_loop)
    monkeypatch.setattr(gui_module, "RenderCanvas", Canvas)
    monkeypatch.setattr(gui_module, "_configure_pygfx_features", lambda: None)
    monkeypatch.setattr(gui_module.gfx, "WgpuRenderer", lambda canvas: SimpleNamespace(device=None))
    monkeypatch.setattr(gui_module.gfx, "Clock", lambda: SimpleNamespace(get_delta=lambda: 0.1))
    monkeypatch.setattr(gui_module, "ImguiRenderer", lambda *args: SimpleNamespace(
        set_gui=lambda callback: None, render=lambda: None, imgui_context=object()
    ))
    monkeypatch.setattr(gui_module.imgui, "get_io", lambda: SimpleNamespace(config_flags=0))
    monkeypatch.setattr(gui_module.imgui, "get_current_context", lambda: None)
    monkeypatch.setattr(gui_module.imgui, "set_current_context", lambda context: None)
    monkeypatch.setattr(gui_module.imgui, "destroy_context", lambda context: None)
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
    assert render_loop.wakeup_threads == []  # No running rendercanvas loop yet.
    gui._start_dispatch()
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
    gui._start_dispatch()
    count = len(gui.canvas.draw_requests)
    future = on_worker(lambda: gui.post(threading.get_ident))
    on_worker(gui.request_draw)
    assert len(gui.canvas.draw_requests) == count
    assert render_loop.wakeup_threads
    assert not future.done()
    render_loop.run()
    assert future.result() == threading.get_ident()
    assert len(gui.canvas.draw_requests) > count
    assert all(thread == threading.get_ident() for thread, _ in gui.canvas.draw_requests)


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
    create, _ = gui_factory
    gui = create()
    cleanups = []
    gui.add_cleanup(lambda: cleanups.append(("first", threading.get_ident())))
    gui.add_cleanup(lambda: cleanups.append(("second", threading.get_ident())))
    results = []
    pending = gui.submit_job(int, callback=results.append)
    running = gui.submit_job(int, callback=results.append)
    running.set_running_or_notify_cancel()
    gui.close()
    gui.close()
    assert pending.cancelled()
    assert not running.cancelled()
    on_worker(lambda: running.set_result(5))
    assert running.result() == 5
    assert gui._posts.empty()
    assert results == []
    assert gui.job_counter == 0
    assert cleanups == [("second", threading.get_ident()), ("first", threading.get_ident())]
    assert gui.canvas.close_count == 1
    assert gui.executor.shutdown_calls == [{"wait": False, "cancel_futures": True}]
    assert gui.asyncio_loop.is_closed()
    with pytest.raises(RuntimeError, match="closed"):
        gui.add_cleanup(lambda: None)


def test_cleanup_failure_does_not_skip_other_disposal(gui_factory):
    create, _ = gui_factory
    gui = create()
    disposed = []
    gui.add_cleanup(lambda: disposed.append(True))

    def bad_cleanup():
        raise RuntimeError("cleanup failed")

    gui.add_cleanup(bad_cleanup)
    gui.close()
    assert disposed == [True]
    assert str(gui.errors[-1]) == "cleanup failed"
    assert gui.canvas.close_count == 1


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
    assert gui.canvas.options == {
        "size": (1280, 720), "title": "A figure", "update_mode": "ondemand", "max_fps": 24
    }
    assert gui.executor.options["max_workers"] == 2
    assert gui.executor.options["mp_context"].get_start_method() == "spawn"
    render_loop.call_soon(gui.canvas.handlers["close"], {"event_type": "close"})
    gui.run()
    assert gui.canvas.close_count == 1
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
    create, _ = gui_factory
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
    assert gui.canvas.close_count == 1


def test_initialization_failure_closes_resources_without_retry(gui_factory):
    create, _ = gui_factory
    state = GUIState()
    calls = []

    def gl_init(canvas, renderer):
        calls.append((canvas, renderer))
        raise TypeError("failure inside initialization")

    state.gl_init = gl_init
    gui = create(state)
    with pytest.raises(TypeError, match="failure inside initialization"):
        gui.run()
    assert len(calls) == 1
    assert gui.canvas.close_count == 1
    assert gui.asyncio_loop.is_closed()


def test_close_from_update_waits_for_backend_render_completion(gui_factory, monkeypatch):
    create, _ = gui_factory
    gui = create()
    events = []
    context = gui.gui_renderer.imgui_context
    monkeypatch.setattr(gui, "_create_main_window", lambda: events.append("begin"))
    monkeypatch.setattr(gui_module.imgui, "end", lambda: events.append("end"))
    monkeypatch.setattr(
        gui_module.imgui, "destroy_context",
        lambda disposed: events.append(("destroy_context", disposed)),
    )
    gui.add_cleanup(lambda: events.append("dispose_widget_texture"))

    def update(state, owner, dt):
        owner.close()
        assert owner.gui_renderer is not None
        assert owner.canvas.close_count == 0
        events.append("close_requested")

    def render():
        gui._draw_imgui()
        assert gui.gui_renderer is not None
        assert gui.canvas.close_count == 0
        events.append("backend_render_complete")

    gui.update = update
    gui.gui_renderer.render = render
    gui._render_frame()
    assert events == [
        "begin", "close_requested", "end", "backend_render_complete",
        "dispose_widget_texture", ("destroy_context", context),
    ]
    assert gui.gui_renderer is None
    assert gui.renderer is None
    assert gui.canvas.close_count == 1
    gui.close()
    assert gui.canvas.close_count == 1


def test_closing_one_gui_restores_other_windows_context(gui_factory, monkeypatch):
    create, _ = gui_factory
    first = create()
    second = create()
    first_context = first.gui_renderer.imgui_context
    second_context = second.gui_renderer.imgui_context
    current = [second_context]
    disposed = []
    monkeypatch.setattr(gui_module.imgui, "get_current_context", lambda: current[0])
    monkeypatch.setattr(gui_module.imgui, "set_current_context", lambda context: current.__setitem__(0, context))
    monkeypatch.setattr(gui_module.imgui, "destroy_context", disposed.append)
    first.add_cleanup(lambda: disposed.append(("widget_context", current[0])))
    first.close()
    assert disposed == [("widget_context", first_context), first_context]
    assert current[0] is second_context
    assert not second._closed
