#!/usr/bin/env python3

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from imgui_bundle import imgui

import asyncio

class State(GUIState):
    def __init__(self):
        GUIState.__init__(self)
        self.status = ""
        self.value = 0

async def delayed_exec(state):
    state.status = 'sleeping'
    await asyncio.sleep(2)
    state.value += 1
    state.status = ''


def update_ui(state, gui, dt):
    if imgui.button('Increase value with delay'):
        gui.exec_coroutine(delayed_exec(state))
    imgui.text(f'{state.status}')
    imgui.text(f'{state.value}')


def main():
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
