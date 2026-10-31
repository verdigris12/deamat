#!/usr/bin/env python3

"""
Example: await explicit main-thread callbacks from background coroutines.

Each completed task increments the current value on the GUI thread. Concurrent
tasks cannot overwrite each other's changes with a stale state snapshot.
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


def finish_increment(state: State) -> int:
    state.value += 1
    state.status = f"Completed increment {state.value}"
    return state.value


async def delayed_exec(gui: dGUI) -> int:
    await asyncio.wrap_future(gui.post(setattr, gui.state, "status", "sleeping"))
    await asyncio.sleep(2)
    return await asyncio.wrap_future(gui.post(finish_increment, gui.state))


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
