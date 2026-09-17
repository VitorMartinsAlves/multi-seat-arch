import unittest

from multiseat_arch import display_manager_current, gui_current, plasma_session_current
from multiseat_arch import display_manager_session_v2, gui_v4, plasma_session_v2


class PublicEntrypointTests(unittest.TestCase):
    def test_gui_facade_preserves_current_implementation(self):
        self.assertIs(gui_current.MainWindow, gui_v4.MainWindow)
        self.assertIs(gui_current.main, gui_v4.main)

    def test_display_manager_facade_preserves_current_implementation(self):
        self.assertIs(display_manager_current.greeter_main, display_manager_session_v2.greeter_main)
        self.assertIs(display_manager_current.plasma_main, display_manager_session_v2.plasma_main)

    def test_plasma_session_facade_preserves_current_implementation(self):
        self.assertIs(plasma_session_current.main, plasma_session_v2.main)


if __name__ == "__main__":
    unittest.main()
