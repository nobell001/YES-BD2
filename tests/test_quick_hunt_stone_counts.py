"""The five 圣石 counts (火 水 风 光 暗, top to bottom) before the torches are
used.  A player's run (2026-10-10) stopped with 「圣石数量区域未从上到下识别
出火、水、风、光、暗5个数字」 and nothing else to go on.
"""

import unittest
import unittest.mock
from types import SimpleNamespace

import numpy as np

from src.tasks import quick_hunt
from src.tasks.quick_hunt import quick_hunt_stone_value


def box(text, y, x=1700, height=20):
    return SimpleNamespace(name=text, x=x, y=y, width=40, height=height)


COLUMN = [box("300", 90), box("250", 130), box("200", 165), box("180", 200), box("90", 240)]


class FakeVision:
    def __init__(self, *reads):
        self.reads = list(reads)
        self.scales = []

    def ocr_boxes(self, _frame, _name, relative_roi=None, ocr_scale=None):
        self.scales.append(ocr_scale)
        return self.reads.pop(0) if self.reads else []


def _task(vision, height=1080):
    from src.tasks.QuickHuntTask import QuickHuntTask

    task = object.__new__(QuickHuntTask)
    task.logs, task.diagnostics = [], []
    task.capture_frame = lambda: np.zeros((height, height * 16 // 9, 3), dtype=np.uint8)
    task.info_set = lambda *_a, **_k: None
    task.log_info = lambda message, *_a, **_k: task.logs.append(message)
    task.sleep = lambda _s: None
    task._quick_vision = lambda: vision
    task._save_flow_diagnostic = task.diagnostics.append
    return task


class StoneValueTest(unittest.TestCase):
    def test_counts_as_the_game_shows_them(self):
        for text, value in (
            ("300", 300), ("1,250", 1250), ("1.2K", 1200), ("1.5万", 15000),
            ("x90", 90), ("0", 0), ("", None), ("火", None),
        ):
            with self.subTest(text=text):
                self.assertEqual(value, quick_hunt_stone_value(text))


class StoneCountsTest(unittest.TestCase):
    def setUp(self):
        patcher = unittest.mock.patch.object(quick_hunt, "QUICK_HUNT_DIALOG_DRAW_SECONDS", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_small_digits_missed_at_1080p_are_read_enlarged(self):
        vision = FakeVision(COLUMN[:3], COLUMN)
        counts = _task(vision)._quick_hunt_stone_counts()
        self.assertEqual({"火": 300, "水": 250, "风": 200, "光": 180, "暗": 90}, counts)
        # As shown first, then as if the frame were 4K (like the torch counter).
        self.assertEqual([None, 2.0], vision.scales)

    def test_a_count_split_into_two_boxes_is_one_row(self):
        split = [box("1,", 90, x=1690), box("250", 91, x=1712)] + COLUMN[1:]
        counts = _task(FakeVision(split))._quick_hunt_stone_counts()
        self.assertEqual(1250, counts["火"])
        self.assertEqual(90, counts["暗"])

    def test_4k_is_not_read_twice(self):
        vision = FakeVision(COLUMN[:4])
        task = _task(vision, height=2160)
        self.assertIsNone(task._quick_hunt_stone_counts())
        self.assertEqual([None], vision.scales)

    def test_a_failure_says_what_was_read_and_keeps_the_screen(self):
        task = _task(FakeVision(COLUMN[:2], COLUMN[:2]))
        self.assertIsNone(task._quick_hunt_stone_counts())
        self.assertIn("读到：300 / 250", task.logs[-1])
        self.assertEqual(["quick_hunt_stone_count_failed"], task.diagnostics)


if __name__ == "__main__":
    unittest.main()
