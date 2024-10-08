from imgui_bundle import imgui
from imgui_bundle.python_backends import pyglet_backend
import pyglet
from pyglet import gl

from matplotlib import pyplot as plt

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Lock


class GUI():
    def __init__(self, state, width=1280, height=720):
        global window
        window = pyglet.window.Window(
            width=width,
            height=height,
            resizable=True
        )
        gl.glClearColor(0, 0, 0, 1)
        self.ctx = imgui.create_context()
        impl = pyglet_backend.create_renderer(window)

        self.window = window
        self.main_window_fullscreen = False
        self.main_window_name = "Main"
        self.impl = impl
        self.fps = 60.0
        self.executor = ProcessPoolExecutor()
        self.job_mutex = Lock()
        self.job_counter = 0
        self.update = lambda state, submit_job, dt: None
        self.state = state
        state.window = {
            'width': self.window.get_size()[0],
            'height': self.window.get_size()[1]
        }

    def submit_job(self, job, *args, callback=None):
        future = self.executor.submit(job, *args)
        self.job_counter = self.job_counter + 1
        self.state.statusline = f'Executing {self.job_counter} tasks...'
        if callback is not None:
            def callback_wrapper(future):
                self.job_mutex.acquire()
                try:
                    callback(future.result())
                finally:
                    self.job_counter = self.job_counter - 1
                    if self.job_counter == 0:
                        status = 'Ready'
                    else:
                        status = f'Executing {self.job_counter} tasks...'
                    self.state.statusline = status
                    self.job_mutex.release()
            future.add_done_callback(callback_wrapper)

    def __create_main_window(self):
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

    def __update_ui(self, dt):
        self.impl.process_inputs()
        imgui.new_frame()
        self
        self.state.update_window(self.window)
        if self.main_window_fullscreen:
            self.__create_main_window()
        else:
            imgui.begin("Main")
        self.job_mutex.acquire()
        self.update(self.state, self, dt)
        self.job_mutex.release()
        imgui.end()

    def __update_figures(self):
        plt.style.use(self.state.plt_style)
        plt.tight_layout()
        for f in self.state.figures.values():
            if 'dirty' not in f or f['dirty']:
                f['dirty'] = False
                f['figure'] = f['make'](self.state)
                f['figure'].set_figwidth(f['width'] / 100)
                f['figure'].set_figheight(f['height'] / 100)

    def run(self):
        def draw(dt):
            self.__update_figures()
            self.__update_ui(dt)
            self.window.clear()
            imgui.render()
            self.state.batch.draw()
            self.impl.render(imgui.get_draw_data())
        pyglet.clock.schedule_interval(draw, 1 / self.fps)
        pyglet.app.run()
        self.impl.shutdown()
