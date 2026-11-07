"""The 11-05 wheel (转盘): spin 10 before 1, in 简中 and 繁中, and a 钻石 prize
slice does not skip the page (live 4K OCR 2026-11-07)."""

import unittest
from types import SimpleNamespace

import numpy as np

from src.tasks.EventRewardTask import EventRewardTask, spin_buttons, spun_count


def _box(name, x, y, w=90, h=30):
    return SimpleNamespace(name=name, x=x, y=y, width=w, height=h)


def _wheel_page(one="轉1次", ten="轉10次", one_cost="1次免費"):
    """The OCR boxes the app read on the 繁中 wheel page (4K, 11-07)."""
    return [
        _box("幫助", 629, 298, 50, 30),
        _box("累積參與0次", 1482, 283, 121, 28),
        _box("鑽石", 834, 356, 41, 22),
        _box("煉製水晶", 934, 363, 47, 72),
        _box("1,000", 838, 450, 34, 17),
        _box("轉盤活動", 1145, 481, 131, 39),
        _box("轉盤累積參與獎勵", 1307, 550, 145, 23),
        _box("10次", 1190, 593, 39, 21),
        _box("50次", 1532, 592, 43, 25),
        _box(one_cost, 1233, 770, 76, 27),
        _box(one, 1238, 740, 64, 30),
        _box(ten, 1451, 741, 78, 29),
        _box("⑤活動 剩下11日", 571, 773, 148, 27),
        _box("10", 1524, 774, 19, 21),
    ]


class SpinButtonsTest(unittest.TestCase):
    def test_traditional_wheel_ten_first(self):
        counts = [count for count, _box in spin_buttons(_wheel_page())]
        self.assertEqual(counts, [10, 1])

    def test_simplified_wheel_ten_first(self):
        page = _wheel_page("旋转1次", "旋转10次", "1次免费")
        self.assertEqual([count for count, _b in spin_buttons(page)], [10, 1])

    def test_reward_row_and_task_line_are_not_spin_buttons(self):
        rows = [_box("10次", 1190, 593), _box("转盘旋转1次", 1100, 400, 300)]
        self.assertEqual(spin_buttons(rows), [])

    def test_spun_count(self):
        self.assertEqual(spun_count(_wheel_page()), 0)
        self.assertIsNone(spun_count([_box("帮助", 0, 0)]))


class DiamondPrizeTest(unittest.TestCase):
    """Leo 11-07: event pages never look for 钻石; only 付费 skips one."""

    def _task(self):
        task = object.__new__(EventRewardTask)
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task._reference_boxes = lambda *a: []
        return task

    def _paid(self, page):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        return self._task()._page_is_paid(frame, page, "转盘", "转盘")

    def test_wheel_page_with_diamond_prize_is_not_skipped(self):
        self.assertFalse(self._paid(_wheel_page()))

    def test_diamond_word_under_a_button_is_not_skipped_either(self):
        self.assertFalse(self._paid(_wheel_page(one_cost="鑽石100")))

    def test_paid_word_anywhere_skips(self):
        self.assertTrue(self._paid(_wheel_page() + [_box("付費限定", 700, 300)]))


class SpinPressTest(unittest.TestCase):
    def _task(self, frames, boxes, pressed, counts):
        task = object.__new__(EventRewardTask)
        task.capture_frame = lambda: frames[0]
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task._paid_now = lambda *_a: False
        task._reference_boxes = lambda *a: boxes
        task._hand_points = lambda *_a: []
        task._settle = lambda *_a: None
        task._confirm_dialog = lambda *_a: True
        task._tokens = lambda *_a: counts[0]
        task._wait_spin_stop = lambda *_a: None

        def press(box, **_k):
            pressed.append(box.name)
            if len(frames) > 1:
                frames.pop(0)
            if len(counts) > 1:
                counts.pop(0)

        task._click_reference_box = press
        return task

    @staticmethod
    def _lit(frame, *boxes):
        frame = frame.copy()
        for box in boxes:
            frame[box.y : box.y + box.height, box.x : box.x + box.width] = 255
        return frame

    def test_ten_pressed_before_one(self):
        page = _wheel_page()
        one, ten = page[10], page[11]
        grey = np.full((1080, 1920, 3), 128, np.uint8)
        frames = [self._lit(grey, one, ten), self._lit(grey, one, ten), self._lit(grey, one), grey]
        pressed = []
        self._task(frames, page, pressed, [25, 15, 5, 4])._press_what_is_lit("转盘")
        self.assertEqual(pressed, ["轉10次", "轉10次", "轉1次"])

    def test_white_ten_that_does_not_spin_is_left(self):
        # Too few tokens but the button stays white: the count does not move.
        page = _wheel_page()
        one, ten = page[10], page[11]
        grey = np.full((1080, 1920, 3), 128, np.uint8)
        frames = [self._lit(grey, one, ten), self._lit(grey, one, ten), self._lit(grey, ten)]
        pressed = []
        task = self._task(frames, page, pressed, [5, 5, 4, 4])
        task._press_what_is_lit("转盘")
        self.assertEqual(pressed[:2], ["轉10次", "轉1次"])
        self.assertEqual(pressed.count("轉10次"), 1)


class WaitSpinStopTest(unittest.TestCase):
    def _task(self, frames):
        task = object.__new__(EventRewardTask)
        looks = []

        def capture():
            looks.append(1)
            return frames[min(len(looks) - 1, len(frames) - 1)]

        task.capture_frame = capture
        task.sleep = lambda *_a: None
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        return task, looks

    def test_waits_while_the_wheel_turns(self):
        rng = np.random.default_rng(5)
        turning = [rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8) for _ in range(6)]
        still = np.full((1080, 1920, 3), 90, np.uint8)
        task, looks = self._task(turning + [still])
        task._wait_spin_stop("转盘")
        self.assertEqual(len(looks), 9)  # six turning looks, then still three times

    def test_still_page_returns_quickly(self):
        still = np.full((1080, 1920, 3), 90, np.uint8)
        task, looks = self._task([still])
        task._wait_spin_stop("转盘")
        self.assertEqual(len(looks), 3)


if __name__ == "__main__":
    unittest.main()
