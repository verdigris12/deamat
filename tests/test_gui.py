import unittest
from deamat.gui import GUI
from deamat.guistate import GUIState


class TestGUI(unittest.TestCase):
    def setUp(self):
        self.state = GUIState()
        self.gui = GUI(self.state)

    def test_initialization(self):
        self.assertIsNotNone(self.gui.window)
        self.assertIsNotNone(self.gui.impl)
        self.assertEqual(self.gui.state, self.state)


if __name__ == '__main__':
    unittest.main()
