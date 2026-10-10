"""A pinned (置顶) story card sits at the front of the quick bar, not where its
number puts it, and the numbers after it leave gaps (YES-BD2 #6, Leo
2026-10-10: 「设置了置顶可能会导致脚本识别不到某个卡带」).

The count from the numbers on screen is only a guide: the cover art is looked
for wherever the count puts the card, a sweep stops at an end of the bar
instead of looking at the same view again, and once the numbers missed the
card the front is searched first.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_story import STORY_BAR_WHEEL_STEPS
from src.tasks.map_trade.vision import Vision

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "map_trade" / "story_badge_grid"


class _Bar:
    """A bar that moves by ``step`` per wheel between 0 and ``end``."""

    def __init__(self, position=0, end=4):
        self.position = position
        self.end = end
        self.looks = []

    def frame(self):
        return np.full((1080, 8, 3), 20 + 10 * self.position, np.uint8)

    def wheel(self, toward_larger):
        self.position = min(self.end, max(0, self.position + (1 if toward_larger else -1)))


def _navigator(bar):
    navigator = Navigator(SimpleNamespace(), SimpleNamespace(capture=bar.frame))
    navigator._status = lambda *_a: None
    navigator.task = SimpleNamespace(
        sleep=lambda _s: None,
        scroll_client=lambda _point, amount, **_k: bar.wheel(amount > 0),
    )
    return navigator


class WheelMovedTest(unittest.TestCase):
    def test_the_wheel_tells_whether_the_bar_moved(self):
        bar = _Bar(position=3, end=4)
        navigator = _navigator(bar)
        self.assertTrue(navigator._wheel_story_bar(True, 3))
        # At the end the bar stays put.
        self.assertFalse(navigator._wheel_story_bar(True, 3))
        self.assertTrue(navigator._wheel_story_bar(False, 3))


class SweepTest(unittest.TestCase):
    def _sweep(self, bar, target, found_at, *, out_of_order=False):
        navigator = _navigator(bar)
        wheels = []
        real_wheel = navigator._wheel_story_bar

        def wheel(toward_larger, notches):
            wheels.append(toward_larger)
            return real_wheel(toward_larger, notches)

        navigator._wheel_story_bar = wheel

        def guided(*_a, **_k):
            navigator._story_bar_out_of_order = out_of_order
            return None

        navigator._scan_story_bar_guided = guided

        def look():
            bar.looks.append(bar.position)
            return "card" if bar.position == found_at else None

        found = navigator._scan_story_bar_by_wheel(
            target, lambda: self.fail("full look"), sweep_look=look
        )
        return found, wheels

    def test_the_far_end_is_not_looked_at_again_and_again(self):
        # Card 18 is pinned at the front; the guided wheel left the bar at
        # the far end.  Old: eight more looks there (~1 min at 2K).
        bar = _Bar(position=4, end=4)
        found, wheels = self._sweep(bar, 18, found_at=0)
        self.assertEqual("card", found)
        self.assertEqual([True, True] + [False] * 4, wheels)
        self.assertEqual([4, 3, 2, 1, 0], bar.looks)

    def test_a_card_the_numbers_missed_is_looked_for_at_the_front_first(self):
        bar = _Bar(position=2, end=4)
        found, wheels = self._sweep(bar, 18, found_at=0, out_of_order=True)
        self.assertEqual("card", found)
        self.assertEqual([False, False], wheels)

    def test_without_pinned_cards_a_late_card_is_still_looked_for_toward_the_end(self):
        bar = _Bar(position=1, end=4)
        found, wheels = self._sweep(bar, 15, found_at=3)
        self.assertEqual("card", found)
        self.assertEqual([True, True], wheels)

    def test_both_ends_are_searched(self):
        bar = _Bar(position=2, end=4)
        found, wheels = self._sweep(bar, 3, found_at=None)
        self.assertIsNone(found)
        # To the front, two still wheels there, then to the end: every view
        # looked at once.
        self.assertEqual([False] * 4 + [True] * 6, wheels)
        self.assertEqual([1, 0, 1, 2, 3, 4], bar.looks)
        self.assertLess(len(wheels), 2 * STORY_BAR_WHEEL_STEPS)

    def test_the_swipe_stops_at_an_end_too(self):
        bar = _Bar(position=4, end=4)
        navigator = _navigator(bar)
        navigator._story_bar_out_of_order = True
        swipes = []

        def swipe(x1, _y1, x2, _y2):
            swipes.append(x2 > x1)
            bar.wheel(x2 < x1)

        navigator.task.executor = SimpleNamespace(interaction=SimpleNamespace(post_swipe=swipe))

        def look():
            bar.looks.append(bar.position)
            return None

        self.assertIsNone(navigator._scan_story_bar_by_swipe(18, look))
        # Front first (drag right): 4 -> 0 in four swipes, then toward the end.
        self.assertEqual([True] * 4, swipes[:4])
        self.assertEqual([3, 2, 1, 0], bar.looks[:4])


class PinnedFixtureTest(unittest.TestCase):
    """Leo's real 720p bar with 6, 18 and 20 pinned before 1, 2, 3..."""

    def test_a_pinned_card_the_count_puts_off_screen_is_found_by_its_art(self):
        frame = cv2.imread(str(FIXTURE / "native_720_q6_visible.png"), cv2.IMREAD_COLOR)
        task = SimpleNamespace(config={}, info_set=lambda *_a: None, ocr=lambda **_k: [])
        navigator = Navigator(task, Vision(task))
        navigator.vision.capture = lambda: frame
        navigator._badge_category = "story"
        # What the badge-row OCR read on this frame (cloud run of the real
        # model, 2026-10-10): pinned 18 read as 8, 20 not read.
        navigator._visible_story_reads = lambda _frame: [
            (6, 74.0), (8, 272.0), (2, 812.0), (3, 992.0), (5, 1334.0), (8, 1692.0), (9, 1886.0)
        ]
        offset = navigator._story_bar_offset(frame)
        self.assertGreater(navigator._story_card_x(offset, 18), 3000)  # the count is wrong
        navigator._scan_story_bar_by_wheel = lambda *_a, **_k: self.fail("no scrolling needed")
        navigator._find_story_badge = lambda *_a: self.fail("no badge templates needed")

        found = navigator._wait_for_story_badge_with_scroll(18)

        self.assertIsNotNone(found)
        detection = found[1]
        self.assertEqual("card_art", detection.recovery_mode)
        self.assertEqual(18, detection.best.number)
        self.assertLess(abs(detection.best.result.center[0] / (720 / 1080) - 274), 8.0)


if __name__ == "__main__":
    unittest.main()
