#!/usr/bin/env python3

"""
Example: perform an asynchronous update in response to a button press.  The
button increments a counter after a short delay without blocking the UI.
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


async def delayed_exec(state: State) -> None:
    state.status = 'sleeping'
    await asyncio.sleep(2)
    state.value += 1
    state.status = ''


def update_ui(state: State, gui: dGUI, dt: float) -> None:
    if imgui.button('Increase value with delay'):
        gui.exec_coroutine(delayed_exec(state))
    imgui.text(f'{state.status}')
    imgui.text(f'{state.value}')


def main() -> None:
    gui = dGUI(State())
    gui.update = update_ui
    gui.run()


if __name__ == "__main__":
    main()