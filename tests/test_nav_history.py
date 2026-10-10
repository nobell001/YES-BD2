import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from src.ui.shell.nav_history import MAX_STEPS, BackForward, History


class HistoryTest(unittest.TestCase):
    """Leo 2026-10-10: 上一页快捷键，像浏览器的."""

    def test_back_and_forward_like_a_browser(self):
        history = History()
        for key in ("home", "daily", "map"):
            history.visit(key)
        self.assertEqual("daily", history.go_back())
        self.assertEqual("home", history.go_back())
        self.assertIsNone(history.go_back())
        self.assertEqual("daily", history.go_forward())
        # the page change the step itself causes adds nothing
        history.arrived("daily")
        self.assertEqual("map", history.go_forward())
        self.assertIsNone(history.go_forward())

    def test_a_new_page_after_going_back_drops_forward(self):
        history = History()
        for key in ("home", "daily", "map"):
            history.visit(key)
        history.go_back()
        history.visit("about")
        self.assertIsNone(history.go_forward())
        self.assertEqual("daily", history.go_back())

    def test_quick_steps_reported_late_are_not_new_pages(self):
        # the switch animation reports a page after the next step began
        history = History()
        for key in ("home", "daily", "map", "about"):
            history.arrived(key)
        history.go_back()
        history.go_back()
        history.arrived("map")
        history.arrived("daily")
        self.assertEqual("daily", history.current)
        self.assertEqual("map", history.go_forward())
        history.arrived("map")
        history.arrived("trade")
        self.assertIsNone(history.go_forward())
        self.assertEqual("map", history.go_back())

    def test_the_list_stays_short(self):
        history = History()
        for index in range(MAX_STEPS * 2):
            history.visit(f"page{index}")
        self.assertEqual(MAX_STEPS, len(history.back))


class BackForwardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.label = QLabel("page", self.window)
        QVBoxLayout(self.window).addWidget(self.label)
        self.calls = []
        self.wiring = BackForward(
            self.window, lambda: self.calls.append("back"), lambda: self.calls.append("forward")
        )
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()

    def press(self, button):
        event = QMouseEvent(
            QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), button, button, Qt.NoModifier
        )
        QApplication.sendEvent(self.label, event)

    def test_mouse_side_buttons_anywhere_in_the_window(self):
        self.press(Qt.BackButton)
        self.press(Qt.ForwardButton)
        self.press(Qt.LeftButton)
        self.assertEqual(["back", "forward"], self.calls)

    def test_alt_arrows_and_back_keys(self):
        keys = [shortcut.key().toString() for shortcut in self.wiring.shortcuts]
        self.assertIn("Alt+Left", keys)
        self.assertIn("Alt+Right", keys)
        for shortcut in self.wiring.shortcuts:
            shortcut.activated.emit()
        self.assertEqual(["back", "forward", "back", "forward"], self.calls)


if __name__ == "__main__":
    unittest.main()
