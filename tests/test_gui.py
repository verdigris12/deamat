import unittest

from deamat.gui import GUI
from deamat.guistate import GUIState


class TestGUI(unittest.TestCase):
    """Basic sanity checks for the GUI class."""

    def setUp(self) -> None:
        self.state = GUIState()
        self.gui = GUI(self.state)

    def test_initialization(self) -> None:
        """Ensure the GUI is properly initialised."""
        self.assertIsNotNone(self.gui.canvas)
        self.assertIsNotNone(self.gui.gui_renderer)
        # The GUI should retain a reference to the state passed in
        self.assertEqual(self.gui.state, self.state)


if __name__ == '__main__':
    unittest.main()