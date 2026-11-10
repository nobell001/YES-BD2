"""淡紫 <-> 深色 opens as a circle from the pressed option (Leo 2026-11-10).

The motion is decoration: whatever happens to it, the colours must switch.
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEasingCurve  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from src.ui.shell import motion, theme  # noqa: E402


class ThemeRevealTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.window.resize(1000, 600)
        self.button = QPushButton("深色", self.window)
        self.button.setGeometry(40, 520, 80, 30)
        self.dark = False
        self.modes = []

        def set_mode(mode):
            self.modes.append(mode)
            self.dark = mode == "dark"

        for patch in (
            mock.patch.object(theme, "set_theme_mode", side_effect=set_mode),
            mock.patch.object(theme, "isDarkTheme", side_effect=lambda: self.dark),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.window.deleteLater)

    def test_matches_the_reference_video(self):
        self.assertEqual(motion.REVEAL_MS, 550)
        self.window.show()
        reveal = motion.switch_theme("dark", self.button)
        self.assertEqual(self.modes, ["dark"])
        self.assertIsNotNone(reveal)
        self.assertEqual(reveal._anim.easingCurve().type(), QEasingCurve.InQuart)
        # starts on the pressed option, covers the whole window, lets clicks through
        self.assertEqual(reveal._origin.toPoint(), self.button.geometry().center())
        self.assertEqual(reveal.geometry(), self.window.rect())
        self.assertTrue(reveal.testAttribute(motion.Qt.WA_TransparentForMouseEvents))
        self.assertLess(reveal.radius(), 20)
        reveal._step(1.0)
        far = ((1000 - 80) ** 2 + 535**2) ** 0.5
        self.assertGreater(reveal.radius(), far)
        reveal.grab()  # paints without error
        reveal.finish()
        self.assertFalse(reveal.isVisible())

    def test_a_second_press_drops_the_first_cover(self):
        self.window.show()
        first = motion.switch_theme("dark", self.button)
        second = motion.switch_theme("light", self.button)
        self.assertFalse(first.isVisible())
        self.assertTrue(second.isVisible())
        self.assertEqual(self.modes, ["dark", "light"])
        second.finish()

    def test_same_colours_means_no_motion(self):
        self.window.show()
        self.assertIsNone(motion.switch_theme("light", self.button))
        self.assertEqual(self.modes, ["light"])
        self.assertEqual(self.window.findChildren(motion.ThemeReveal)[0].isVisible(), False)

    def test_hidden_window_or_no_source_switches_at_once(self):
        self.assertIsNone(motion.switch_theme("dark", self.button))
        self.assertIsNone(motion.switch_theme("light", None))
        self.assertEqual(self.modes, ["dark", "light"])

    def test_a_failed_picture_never_blocks_the_switch(self):
        self.window.show()
        with mock.patch.object(QWidget, "grab", side_effect=RuntimeError("no picture")):
            self.assertIsNone(motion.switch_theme("dark", self.button))
        self.assertEqual(self.modes, ["dark"])


class SidebarSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sidebar_has_the_switch_and_settings_does_not(self):
        from src.ui.shell import settings, sidebar

        side = sidebar.Sidebar()
        self.addCleanup(side.deleteLater)
        self.assertEqual(list(side.theme_switch._buttons), ["light", "dark"])
        self.assertFalse(hasattr(settings, "THEME_LABELS"))
        with mock.patch.object(motion, "switch_theme") as switch:
            side.theme_switch.button("dark").click()
        switch.assert_called_once_with("dark", side.theme_switch.button("dark"))

    def test_switch_fits_inside_the_sidebar(self):
        from src.ui.shell import sidebar

        side = sidebar.Sidebar()
        self.addCleanup(side.deleteLater)
        side.resize(side.width(), 900)
        side.show()
        self.app.processEvents()
        box = side.theme_switch.geometry()
        self.assertGreaterEqual(box.left(), 0)
        self.assertLessEqual(box.right(), side.width())
        for button in side.theme_switch._buttons.values():
            need = button.fontMetrics().horizontalAdvance(button.text())
            self.assertGreaterEqual(button.width(), need + 8)


if __name__ == "__main__":
    unittest.main()
