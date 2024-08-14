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
        self.assertEqual(self.gui.fps, 120.0)
        self.assertEqual(self.gui.state, self.state)

    def test_run(self):
        # This test will just ensure that the run method can be called without errors.
        # Note: This won't actually open a window in a test environment.
        try:
            self.gui.run()
        except Exception as e:
            self.fail(f"GUI run method raised an exception: {e}")

if __name__ == '__main__':
    unittest.main()
