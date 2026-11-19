"""Player v0.4.3, 1080p windowed, 2026-11-19 19:38 (problem summary).

巧克力面包 was cooked with MAX.  A big batch cooks longer than STUCK_SECONDS
and on the detail page only the small 「製作中.. N%」 and the ring change, so
the whole picture counts as still: the wait gave up after 10 s with
「未识别到含料理名和数量的结果条，OCR=-（画面 10 秒没动）」, 返回 was then
ignored (the game ignores 返回 while a batch cooks) and the bar showed later.
Every later dish was stopped.

A new percentage is the game working: keep waiting (up to the 40 s cap).
A percentage that stays the same for STUCK_SECONDS is still stuck.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from src.tasks.map_trade.trader import Trader
from src.utils.wait_limits import STUCK_SECONDS, StillTimer

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade"
COOKING = "cooking_second_batch_tw_in_progress_2k_clone_as_1080.jpg"
RECIPE = "巧克力面包"
STILL_FRAME = np.full((1080, 1920, 3), 20, dtype=np.uint8)


class _Task:
    def __init__(self):
        self.logs = []

    def log_info(self, message, **_kwargs):
        self.logs.append(("info", message))

    def log_warning(self, message, **_kwargs):
        self.logs.append(("warning", message))

    def info_set(self, *_args):
        pass


def _timed_trader(script):
    """``script(now) -> (bar text, centre text)``; the picture never moves."""
    clock = {"now": 0.0}
    task = _Task()
    task.sleep = lambda seconds: clock.__setitem__("now", clock["now"] + seconds)
    trader = object.__new__(Trader)
    trader.task = task

    def ocr_text(_frame, name, **_kwargs):
        bar, centre = script(clock["now"])
        return centre if name.endswith("制作中") else bar

    trader.vision = SimpleNamespace(
        capture=lambda: STILL_FRAME, ocr_text=ocr_text, simplify=str
    )
    trader._cooking_detail_snapshot = lambda *_args: object()
    return trader, task, clock


def _cooking_for(seconds):
    """A batch at a steady pace that ends with its bar after ``seconds``."""

    def script(now):
        if now >= seconds:
            return "巧克力麵包×10000", ""
        return "", f"製作中..{int(now * 100 / seconds)}%"

    return script


class LongBatchTest(unittest.TestCase):
    def _wait(self, script, timeout=40.0):
        trader, task, clock = _timed_trader(script)
        with patch("src.tasks.map_trade.trader_cooking.monotonic", lambda: clock["now"]):
            frame = trader._wait_for_cooking_result(RECIPE, timeout)
        return frame, trader, task, clock

    def test_batch_longer_than_stuck_seconds_is_waited_for(self):
        frame, trader, task, clock = self._wait(_cooking_for(18.0))
        self.assertIsNotNone(frame, task.logs)
        self.assertGreaterEqual(clock["now"], 18.0)
        self.assertEqual("巧克力麵包×10000", trader._last_cooking_result_text)
        self.assertFalse([m for level, m in task.logs if level == "warning"])

    def test_progress_that_stops_moving_is_still_stuck(self):
        def frozen(now):
            return "", "製作中..40%" if now >= 5.0 else f"製作中..{int(now * 8)}%"

        frame, _trader, task, clock = self._wait(frozen)
        self.assertIsNone(frame)
        self.assertLess(clock["now"], 40.0)
        warning = " ".join(m for level, m in task.logs if level == "warning")
        self.assertIn("40%", warning)
        self.assertIn("秒没动", warning)

    def test_still_cooking_at_the_cap_gives_up(self):
        frame, _trader, task, clock = self._wait(_cooking_for(100.0))
        self.assertIsNone(frame)
        self.assertGreaterEqual(clock["now"], 40.0)
        self.assertTrue(any(level == "warning" for level, _ in task.logs))

    def test_still_screen_without_cooking_text_stops_at_stuck_seconds(self):
        frame, _trader, _task, clock = self._wait(lambda _now: ("", ""))
        self.assertIsNone(frame)
        self.assertLess(clock["now"], STUCK_SECONDS + 1.0)

    def test_warning_names_what_ocr_read_when_nothing_matched(self):
        # Since #582 the warning said 「OCR=-」 for any unmatched read.
        _frame, _trader, task, _clock = self._wait(lambda _now: ("巧克力", ""))
        warning = " ".join(m for level, m in task.logs if level == "warning")
        self.assertIn("OCR=巧克力", warning)


class CookingPictureLooksStillTest(unittest.TestCase):
    def test_new_percentage_alone_is_not_a_moving_scene(self):
        # Real 繁中 frame 「製作中.. 76%」: erase the number (more change than
        # 76% → 77%) and the picture is still by the scene-move rule.
        frame = cv2.imread(str(FIXTURES / COOKING))
        self.assertIsNotNone(frame)
        changed = frame.copy()
        changed[580:620, 960:1035] = frame[640:680, 960:1035]
        timer = StillTimer()
        timer.still_for(frame, 0.0)
        self.assertGreaterEqual(timer.still_for(changed, STUCK_SECONDS), STUCK_SECONDS)


if __name__ == "__main__":
    unittest.main()
