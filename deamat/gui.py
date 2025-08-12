"""
High‑level GUI class built on top of pyglet and imgui_bundle.  The
``GUI`` class manages the event loop, window creation and figure updates.  It
exposes a simple callback interface to update the UI every frame.
"""

from imgui_bundle import imgui
from imgui_bundle.python_backends import pyglet_backend
import pyglet
from pyglet import gl

from matplotlib import pyplot as plt

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Lock

import asyncio
import threading


class GUI:
    def __init__(self, state: "GUIState", width: int = 1280, height: int = 720) -> None:
        global window
        window = pyglet.window.Window(
            width=width,
            height=height,
            resizable=True
        )
        gl.glClearColor(0, 0, 0, 1)
        self.ctx = imgui.create_context()
        impl = pyglet_backend.create_renderer(window)

        self.asyncio_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.asyncio_loop)
        self.asyncio_thread = threading.Thread(
            target=self.asyncio_loop.run_forever,
            daemon=True
        )
        self.update_async = None

        self.window = window
        self.main_window_fullscreen = False
        self.main_window_name = "Main"
        self.impl = impl
        self.fps = 60.0
        self.executor = ProcessPoolExecutor()
        self.job_mutex = Lock()
        self.job_counter = 0
        self.update = None  # type: ignore
        self.state = state
        state.window = {
            'width': self.window.get_size()[0],
            'height': self.window.get_size()[1]
        }

    def _create_main_window(self) -> None:
        mv = imgui.get_main_viewport()
        imgui.set_next_window_pos((mv.pos.x, mv.pos.y))
        imgui.set_next_window_size((mv.size.x, mv.size.y))
        flags = imgui.WindowFlags_.menu_bar \
            | imgui.WindowFlags_.no_decoration \
            | imgui.WindowFlags_.no_resize \
            | imgui.WindowFlags_.no_move \
            | imgui.WindowFlags_.no_collapse \
            | imgui.WindowFlags_.no_bring_to_front_on_focus
        imgui.begin("Main", flags=flags)

    def _update_ui(self, dt: float) -> None:
        self.impl.process_inputs()
        imgui.new_frame()
        self.state.update_window(self.window)
        if self.main_window_fullscreen:
            self._create_main_window()
        else:
            imgui.begin("Main")
        self.job_mutex.acquire()
        if self.update:
            self.update(self.state, self, dt)
        self.job_mutex.release()
        imgui.end()

    def _update_figures(self) -> None:
        plt.style.use(self.state.plt_style)
        plt.tight_layout()
        for f in self.state.figures.values():
            if 'dirty' not in f or f['dirty']:
                f['dirty'] = False
                f['figure'] = f['make'](self.state)
                f['figure'].set_figwidth(f['width'] / 100)
                f['figure'].set_figheight(f['height'] / 100)

    def submit_job(self, job, *args, callback=None) -> None:
        future = self.executor.submit(job, *args)
        self.job_counter += 1
        self.state.statusline = f'Executing {self.job_counter} tasks...'
        if callback is not None:
            def callback_wrapper(future) -> None:
                self.job_mutex.acquire()
                try:
                    callback(future.result())
                finally:
                    self.job_counter -= 1
                    if self.job_counter == 0:
                        status = 'Ready'
                    else:
                        status = f'Executing {self.job_counter} tasks...'
                    self.state.statusline = status
                    self.job_mutex.release()
            future.add_done_callback(callback_wrapper)

    def exec_coroutine(self, co: asyncio.coroutines) -> None:
        asyncio.run_coroutine_threadsafe(co, self.asyncio_loop)

    def run(self) -> None:
        def draw(dt: float) -> None:
            self._update_figures()
            self._update_ui(dt)
            self.window.clear()
            imgui.render()
            self.state.batch.draw()
            self.impl.render(imgui.get_draw_data())
        pyglet.clock.schedule_interval(draw, 1 / self.fps)
        self.asyncio_thread.start()
        pyglet.app.run()
        self.impl.shutdown()