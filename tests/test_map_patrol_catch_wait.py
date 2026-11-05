"""A patrol's catch is the game's own scene, not a stuck field.

Player v0.2.31 2026-11-05 (1080p window, 噩梦之冬): right after the last map
a patrol caught the character (「被发现了！！」 on the 问题摘要's frames) and
sent it back to the start.  The 3 s check that the field is still there ran
out under the banner, 「Q_ep2完成后无法打开快速切换页：未稳定确认当前剧情卡带箱庭」
stopped the whole 跑图, and the field was back a moment later.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.tasks.map_trade import navigator_sandbox
from src.tasks.map_trade.models import NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.utils.wait_limits import STUCK_SECONDS


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _navigator(scenes, clock, step=1.0):
    """scenes: (state, walk-area text) per look."""
    shown = iter(scenes)
    current = {}

    def capture():
        clock.now += step
        current["scene"] = next(shown)
        return "frame"

    navigator = Navigator(SimpleNamespace(config={}, sleep=lambda *_a: None), SimpleNamespace(capture=capture))
    navigator._black_frame = lambda _frame: False
    navigator.classify = lambda _frame=None: current["scene"][0]
    navigator._walk_text = lambda _frame: current["scene"][1]
    navigator._status = lambda *_a: None
    return navigator


class PatrolCatchHoldsTheFieldWaitTest(unittest.TestCase):
    def test_the_catch_words_count_as_the_game_moving(self):
        navigator = _navigator([], _Clock())
        navigator._walk_text = lambda _frame: "被发现了"
        self.assertTrue(navigator._auto_moving("frame"))
        navigator._walk_text = lambda _frame: "被光明监视者发现已遭驱逐"
        self.assertTrue(navigator._auto_moving("frame"))
        navigator._walk_text = lambda _frame: ""
        self.assertFalse(navigator._auto_moving("frame"))

    def test_the_field_check_waits_through_the_catch(self):
        clock = _Clock()
        caught = [(ScreenState.UNKNOWN, "被发现了")] * 6
        field = [(ScreenState.SANDBOX, "")] * 2
        navigator = _navigator(caught + field, clock)
        with patch.object(navigator_sandbox, "monotonic", clock):
            result = navigator._wait_for_current_sandbox()
        self.assertTrue(result.success, result.message)

    def test_a_field_that_never_comes_back_still_ends(self):
        clock = _Clock()
        navigator = _navigator([(ScreenState.UNKNOWN, "")] * 50, clock)
        with patch.object(navigator_sandbox, "monotonic", clock):
            result = navigator._wait_for_current_sandbox()
        self.assertFalse(result.success)
        self.assertLess(clock.now, 6.0)


class QuickSwitchLooksAgainTest(unittest.TestCase):
    def test_a_missed_field_is_looked_at_once_more_before_giving_up(self):
        navigator = Navigator(SimpleNamespace(config={}), SimpleNamespace())
        navigator._status = lambda *_a: None
        waits = []

        def wait(timeout=3.0, interval=0.5):
            waits.append(timeout)
            if len(waits) == 1:
                return NavigationResult(False, ScreenState.UNKNOWN, "未稳定确认当前剧情卡带箱庭")
            return NavigationResult(True, ScreenState.SANDBOX)

        navigator._wait_for_current_sandbox = wait
        navigator._click_quick_switch = lambda *_a: True
        navigator._wait_for_quick_switch_page = lambda: True
        navigator._select_story_category = lambda _category: True
        result = navigator.open_story_quick_switcher_from_sandbox(category="event")
        self.assertTrue(result.success, result.message)
        self.assertEqual([3.0, STUCK_SECONDS], waits)

    def test_no_field_after_the_second_look_is_reported(self):
        navigator = Navigator(SimpleNamespace(config={}), SimpleNamespace())
        navigator._status = lambda *_a: None
        failed = NavigationResult(False, ScreenState.UNKNOWN, "未稳定确认当前剧情卡带箱庭")
        navigator._wait_for_current_sandbox = lambda timeout=3.0, interval=0.5: failed
        navigator._click_quick_switch = lambda *_a: self.fail("pressed without the field")
        self.assertIs(failed, navigator.open_story_quick_switcher_from_sandbox())


if __name__ == "__main__":
    unittest.main()
