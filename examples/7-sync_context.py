#!/usr/bin/env python3

"""
Example: thread-safe state mutation from async coroutines using sync context.

When async coroutines need to modify state, use gui.state.sync() to ensure
changes are safely merged on the main thread.
"""

import asyncio

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState
from deamat import imgui


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        self.status = ""
        self.value = 0


async def delayed_exec(gui: dGUI) -> None:
    async with gui.state.sync() as state:
        state.status = 'sleeping'
    
    await asyncio.sleep(2)
    
    async with gui.state.sync() as state:
        state.value += 1
        state.status = ''


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    if imgui.button('Increase value with delay'):
        gui.exec_coroutine(delayed_exec(gui))
    imgui.text(f'{state.status}')
    imgui.text(f'{state.value}')


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()
