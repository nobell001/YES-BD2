"""A folded 圣石 panel is opened before the counts are read.

A player's 快速狩猎 (Bilibili 琴烟, v0.1.17, 1920×1080 windowed, 2026-10-10)
stopped with 「圣石数量…实际识别0个」 seven times in 3 s: the top-right panel
was folded and showed only 火把 60/60 with a round ∨ under it.  Leo:
「聖石如果偵測玩家收起來 就把它點開」.  The fixture is that player's screen,
scaled to 1080p and cut to the top-right corner.
"""

import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks import quick_hunt
from src.tasks.quick_hunt import quick_hunt_fold_button

FIXTURE = Path(__file__).parent / "fixtures" / "quick_hunt" / "stone_panel_collapsed_1080p.png"
BUTTON = (1720, 118)  # measured on the fixture, 1920×1080


def folded_frame():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[0:260, 1480:1920] = cv2.imread(str(FIXTURE))
    return frame


def box(text, y, x=1740, height=20):
    return SimpleNamespace(name=text, x=x, y=y, width=40, height=height)


COLUMN = [box("300", 90), box("250", 130), box("200", 165), box("180", 200), box("90", 240)]


class FoldButtonTest(unittest.TestCase):
    def assertNear(self, expected, found, slack=3):
        self.assertIsNotNone(found)
        self.assertLessEqual(max(abs(found[0] - expected[0]), abs(found[1] - expected[1])), slack)

    def test_the_players_folded_panel(self):
        self.assertNear(BUTTON, quick_hunt_fold_button(folded_frame()))

    def test_at_4k(self):
        frame = cv2.resize(folded_frame(), (3840, 2160), interpolation=cv2.INTER_CUBIC)
        self.assertNear((BUTTON[0] * 2, BUTTON[1] * 2), quick_hunt_fold_button(frame), slack=6)

    def test_an_up_arrow_is_not_pressed(self):
        # ∧ would fold the panel away again.
        frame = folded_frame()
        x, y = BUTTON
        frame[y - 12 : y + 13, x - 16 : x + 17] = frame[y - 12 : y + 13, x - 16 : x + 17][::-1]
        self.assertIsNone(quick_hunt_fold_button(frame))

    def test_no_button_on_the_map_or_a_blank_screen(self):
        frame = folded_frame()
        x, y = BUTTON
        frame[y - 32 : y + 33, x - 32 : x + 33] = frame[180:245, 1600:1665]  # plain map
        self.assertIsNone(quick_hunt_fold_button(frame))
        self.assertIsNone(quick_hunt_fold_button(np.zeros((1080, 1920, 3), dtype=np.uint8)))


class FakeVision:
    def __init__(self, screen):
        self.screen = screen

    def ocr_boxes(self, _frame, _name, relative_roi=None, ocr_scale=None):
        return list(COLUMN) if self.screen["open"] else []


def _task(*, opens=True, button_looks=99):
    from src.tasks.QuickHuntTask import QuickHuntTask

    screen = {"open": False, "looks": 0}
    task = object.__new__(QuickHuntTask)
    task.logs, task.presses, task.diagnostics = [], [], []

    def capture():
        screen["looks"] += 1
        if screen["open"] or screen["looks"] > button_looks:
            return np.zeros((1080, 1920, 3), dtype=np.uint8)
        return folded_frame()

    def press(x, y, after_sleep=0.0):
        task.presses.append((x, y))
        screen["open"] = opens

    task.capture_frame = capture
    task.info_set = lambda *_a, **_k: None
    task.log_info = lambda message, *_a, **_k: task.logs.append(message)
    task.sleep = lambda _s: None
    task._quick_vision = lambda: FakeVision(screen)
    task._click_reference = press
    task._save_flow_diagnostic = task.diagnostics.append

    def press_and_confirm(_label, press, confirmed, still_before=None, **_k):
        press()
        if confirmed():
            return True
        if still_before is not None and still_before():
            press()
        return bool(confirmed())

    task.press_and_confirm = press_and_confirm
    return task


class UnfoldThenReadTest(unittest.TestCase):
    def setUp(self):
        patcher = unittest.mock.patch.object(quick_hunt, "QUICK_HUNT_DIALOG_DRAW_SECONDS", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_folded_panel_is_opened_and_read(self):
        task = _task()
        counts = task._quick_hunt_stone_counts()
        self.assertEqual({"火": 300, "水": 250, "风": 200, "光": 180, "暗": 90}, counts)
        [(x, y)] = task.presses
        self.assertLessEqual(max(abs(x - BUTTON[0]), abs(y - BUTTON[1])), 3)
        self.assertIn("已点开", task.logs[-1])
        self.assertEqual([], task.diagnostics)

    def test_one_look_is_not_enough_to_press(self):
        # The button shows on the stone read's look and the first unfold
        # look, not on the second one.
        task = _task(button_looks=2)
        self.assertIsNone(task._quick_hunt_stone_counts())
        self.assertEqual([], task.presses)

    def test_still_unread_after_opening_says_so(self):
        task = _task(opens=False)
        self.assertIsNone(task._quick_hunt_stone_counts())
        # Pressed once more only while the ∨ still shows and nothing was read.
        self.assertEqual(2, len(task.presses))
        self.assertIn("原本收起来了，点开后还是没读到", task.logs[-1])
        self.assertEqual(["quick_hunt_stone_count_failed"], task.diagnostics)

    def test_no_digits_and_no_button_names_the_likely_cause(self):
        task = _task(button_looks=0)
        self.assertIsNone(task._quick_hunt_stone_counts())
        self.assertEqual([], task.presses)
        self.assertIn("圣石栏可能收起来了", task.logs[-1])


if __name__ == "__main__":
    unittest.main()
