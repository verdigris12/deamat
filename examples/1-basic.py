#!/usr/bin/env python3

"""
Basic example: open an empty window using deamat.

Run with `python examples/1-basic.py` after installing the package.
"""

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState


class State(GUIState):
    def __init__(self) -> None:
        super().__init__()
        self.value = 123


def main() -> None:
    gui = dGUI(State())
    gui.run()


if __name__ == "__main__":
    main()
