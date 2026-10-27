import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from src.ui.shell.sidebar import SLIDE_MAX_STEP_MS, SLIDE_MS, Sidebar


class SidebarSlideTest(unittest.TestCase):
    """Leo 2026-10-27: the selected shade slides from row to row, its place
    and size follow the target, the text stays still, and a quick second
    click goes on from wherever the shade is."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patches = (
            mock.patch.object(Sidebar, "_refresh_now", lambda self: None),
            mock.patch.object(Sidebar, "_refresh_map_now", lambda self: None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.side = Sidebar()
        self.side.resize(self.side.width(), 700)
        self.addCleanup(self.side.close)

    def settle(self):
        for _ in range(5):
            self.app.processEvents()

    def row(self, key):
        item = self.side.items[key]
        box = QRectF(item.geometry())
        return QRectF(box.x(), box.y(), item.pill_width(), box.height()).adjusted(
            0.5, 0.5, -0.5, -0.5
        )

    def test_before_the_window_shows_the_shade_sits_on_the_row(self):
        self.side.select("trade")
        self.side.show()
        self.settle()
        self.assertEqual(self.row("trade"), self.side._pill_rect())
        self.assertEqual(1.0, self.side.items["trade"]._on)
        self.assertEqual(0.0, self.side.items["home"]._on)

    def test_the_shade_leaves_from_the_old_row_and_ends_on_the_new_one(self):
        self.side.show()
        self.settle()
        self.side.select("home")
        self.side.select("fiend")
        self.assertTrue(self.side._slide.running())
        self.side._slide.stop()
        self.side._slide.value = 0.0
        self.assertEqual(self.row("home"), self.side._pill_rect())
        self.side._slide.value = 1.0
        self.side._slide_step()
        self.assertEqual(self.row("fiend"), self.side._pill_rect())
        self.assertEqual(1.0, self.side.items["fiend"]._on)
        self.assertEqual(0.0, self.side.items["home"]._on)

    def test_a_quick_second_click_turns_around_mid_way(self):
        self.side.show()
        self.settle()
        self.side.select("home")
        self.side.select("settings")
        self.side._slide.stop()
        self.side._slide.value = 0.4
        self.side._slide_step()
        mid = self.side._pill_rect()
        self.assertGreater(mid.top(), self.row("home").top())
        self.assertLess(mid.top(), self.row("settings").top())
        self.side.select("daily")
        self.side._slide.stop()
        self.assertEqual(mid, self.side._pill_rect())

    def test_rows_under_the_shade_blend_by_how_much_it_covers(self):
        self.side.show()
        self.settle()
        self.side.select("daily")
        self.side.select("trade")
        self.side._slide.stop()
        self.side._slide.value = 0.5
        self.side._slide_step()
        daily, trade = self.side.items["daily"]._on, self.side.items["trade"]._on
        self.assertTrue(0.0 < daily < 1.0 and 0.0 < trade < 1.0)
        self.assertEqual(0.0, self.side.items["map"]._on)

    def test_a_row_moving_with_the_window_takes_the_shade_along(self):
        self.side.show()
        self.settle()
        self.side.select("settings")
        self.side.resize(self.side.width(), 900)
        self.settle()
        self.assertEqual(self.row("settings"), self.side._pill_rect())
        self.assertEqual(1.0, self.side.items["settings"]._on)

    def test_a_held_up_frame_pauses_the_slide_instead_of_jumping(self):
        # A page drawn for the first time can hold the window up for a
        # tenth of a second; the pill must not skip that stretch.
        self.side.show()
        self.settle()
        self.side.select("home")
        self.side.select("fiend")
        slide = self.side._slide
        with mock.patch.object(slide._clock, "restart", return_value=150):
            slide._tick()
        self.assertLessEqual(slide._progress, SLIDE_MAX_STEP_MS / SLIDE_MS + 1e-9)
        self.assertTrue(slide.running())
        slide.stop()

    def test_the_shade_hugs_the_words_and_its_width_follows_them(self):
        self.side.show()
        self.settle()
        short, long = self.side.items["home"], self.side.items["fiend"]
        self.assertLess(short.pill_width(), long.pill_width())
        self.assertLess(long.pill_width(), long.width())
        self.side.select("home")
        self.side.select("fiend")
        self.side._slide.stop()
        self.side._slide.value = 0.5
        width = self.side._pill_rect().width()
        self.assertTrue(self.row("home").width() < width < self.row("fiend").width())

    def test_the_landing_bounces_a_little_past_the_target_and_settles(self):
        self.side.show()
        self.settle()
        self.side.select("home")
        self.side.select("fiend")
        slide = self.side._slide
        seen = []
        with mock.patch.object(slide._clock, "restart", return_value=16):
            while slide.running():
                slide._tick()
                seen.append(slide.value)
        self.assertGreater(max(seen), 1.0)
        self.assertLess(max(seen), 1.08)
        self.assertEqual(1.0, seen[-1])
        self.assertEqual(self.row("fiend"), self.side._pill_rect())

    def test_no_page_selected_draws_no_shade(self):
        self.side.show()
        self.settle()
        self.side.select("home")
        self.side.select(None)
        self.assertIsNone(self.side._pill_rect())
        self.assertTrue(all(item._on == 0.0 for item in self.side.items.values()))


if __name__ == "__main__":
    unittest.main()
