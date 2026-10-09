import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.ui.shell import data
from src.ui.shell.run_confirm import MODE_LEFT, MODE_TICKED, RunConfirm, default_mode, will_run


def _child(key, included=True, weekly=False):
    return data.Child(key, None, key, key, "mail", "claim", included, weekly)


class RunConfirmTest(unittest.TestCase):
    """Leo 2026-10-09: 一键日常 / 桌面分身 first ask 跑勾选的 or 跑没跑完的,
    with every 日常 and 周常 as a tile to tick; unticked never runs."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.children = [
            _child("a"),
            _child("b"),
            _child("c", included=False),
            _child("w", weekly=True),
        ]
        self.done = {"a": True, "b": False, "c": False, "w": False}

    def make(self):
        dialog = RunConfirm(self.children, self.done, {"a": "08:40"})
        dialog.resize(1335, 1020)
        dialog.show()
        self.addCleanup(dialog.close)
        QApplication.processEvents()
        return dialog

    def test_unfinished_skips_done_and_unticked(self):
        ticks = {"a": True, "b": True, "c": False, "w": True}
        self.assertEqual(will_run(ticks, self.done, MODE_LEFT), ["b", "w"])

    def test_ticked_runs_done_ones_again(self):
        ticks = {"a": True, "b": True, "c": False, "w": True}
        self.assertEqual(will_run(ticks, self.done, MODE_TICKED), ["a", "b", "w"])

    def test_opens_on_unfinished_while_something_is_left(self):
        self.assertEqual(default_mode(self.children, self.done), MODE_LEFT)
        all_done = dict.fromkeys(self.done, True)
        self.assertEqual(default_mode(self.children, all_done), MODE_TICKED)

    def test_lists_daily_and_weekly_tiles(self):
        dialog = self.make()
        self.assertEqual(set(dialog.tiles), {"a", "b", "c", "w"})

    def test_done_tile_has_no_check_in_unfinished_mode(self):
        dialog = self.make()
        self.assertFalse(dialog.tiles["a"].check.isVisible())
        dialog.switch.set_value(MODE_TICKED)
        dialog._set_mode(MODE_TICKED)
        self.assertTrue(dialog.tiles["a"].check.isVisible())
        self.assertTrue(dialog.tiles["a"].check.isChecked())

    def test_clicking_a_tile_flips_its_check(self):
        dialog = self.make()
        tile = dialog.tiles["c"]
        QTest.mouseClick(tile, Qt.LeftButton, Qt.NoModifier, QPoint(20, tile.height() - 12))
        self.assertTrue(dialog.ticks["c"])
        self.assertEqual(dialog.run_keys(), ["b", "c", "w"])

    def test_start_shows_the_count_and_is_off_at_zero(self):
        dialog = self.make()
        self.assertIn("2", dialog.start.text())
        for key in ("b", "w"):
            dialog.tiles[key].check.setChecked(False)
        self.assertFalse(dialog.start.isEnabled())

    def test_select_all_ticks_every_open_tile(self):
        dialog = self.make()
        dialog.select_all.setChecked(True)
        self.assertEqual(dialog.run_keys(), ["b", "c", "w"])
        self.assertTrue(dialog.select_all.isChecked())
        dialog.select_all.setChecked(False)
        self.assertEqual(dialog.run_keys(), [])
        self.assertTrue(dialog.ticks["a"])  # a done tile in 跑没跑完的 keeps its tick

    def test_ticked_option_is_on_the_left(self):
        dialog = self.make()
        buttons = dialog.switch._buttons
        self.assertLess(buttons[MODE_TICKED].x(), buttons[MODE_LEFT].x())


if __name__ == "__main__":
    unittest.main()
