#!/usr/bin/env python3

from deamat.gui import GUI as dGUI
from deamat.guistate import GUIState


class State(GUIState):
    def __init__(self):
        GUIState.__init__(self)
        self.value = 123


def main():
    gui = dGUI(State())
    gui.run()


if __name__ == "__main__":
    main()
