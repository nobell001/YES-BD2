"""A button paints from its own icon, text, icon size and box, never from
those fields of its style option.

UI check 2026-10-28 (148 pictures, zh_CN): ``label.rect`` in Button.paintEvent
came back as a QWidgetItem, PySide's stale wrapper for an object that had
lived at that address before, and the paint failed with
「'QWidgetItem' object has no attribute 'translated'」.  It hit one paint out of
thousands, so the test makes every read of those fields come back that way.
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QStyleOptionButton, QWidget, QWidgetItem

from src.ui.shell import widgets
from src.ui.shell.widgets import Button


class _StaleFields(QStyleOptionButton):
    """Reading these fields gives another type's object, as a stale wrapper
    does; writing them still reaches the real option."""

    holder = None

    def _stale(self):
        return QWidgetItem(_StaleFields.holder)

    rect = property(_stale, QStyleOptionButton.rect.__set__)
    iconSize = property(_stale, QStyleOptionButton.iconSize.__set__)
    icon = property(_stale, QStyleOptionButton.icon.__set__)


class ButtonPaintFieldsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        _StaleFields.holder = QWidget()

    def paint_errors(self, button: Button) -> list[str]:
        """Exceptions raised inside paintEvent (Qt only prints them)."""
        errors = []

        def hook(kind, value, _tb):
            errors.append(f"{kind.__name__}: {value}")

        button.resize(button.sizeHint())
        with mock.patch.object(widgets, "QStyleOptionButton", _StaleFields), mock.patch.object(
            sys, "excepthook", hook
        ):
            self.assertFalse(button.grab().isNull())
        return errors

    def test_icon_and_text_paint_with_stale_option_fields(self):
        for hover in (0.0, 0.5, 1.0):
            button = Button("一键完成日常", "primary", "play")
            button._hover.value = hover
            self.assertEqual([], self.paint_errors(button), hover)

    def test_text_only_and_icon_only_paint_with_stale_option_fields(self):
        self.assertEqual([], self.paint_errors(Button("开始", "secondary")))
        self.assertEqual([], self.paint_errors(Button("", "icon", "play")))

    def test_the_trap_reproduces_the_failure(self):
        # The stand-in really breaks code that reads the option's box.
        option = _StaleFields()
        with self.assertRaises(AttributeError):
            option.rect.translated(1, 0)


if __name__ == "__main__":
    unittest.main()
