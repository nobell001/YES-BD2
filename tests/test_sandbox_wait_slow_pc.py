"""Entering a map on a slow PC (audit #9, #10).

#10: a long loading screen used up the 'stuck' budget, so the entry failed.
#9: the first wait took the whole budget, so a reward page that hid the field
was never dismissed.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.tasks.BaseBD2Task import CartridgeSpecialPageResult
from src.tasks.map_trade import navigator_sandbox
from src.tasks.map_trade.models import NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_sandbox import (
    STORY_ENTRY_AFTER_PAGE_SECONDS,
    STORY_ENTRY_PAGE_RESERVE_SECONDS,
)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _navigator(states, clock, step=1.0):
    def capture():
        clock.now += step
        return "frame"

    task = SimpleNamespace(config={}, sleep=lambda *_a: None)
    navigator = Navigator(task, SimpleNamespace(capture=capture))
    sequence = iter(states)
    navigator._black_frame = lambda _frame: False
    navigator.classify = lambda _frame=None: next(sequence)
    navigator._auto_moving = lambda _frame: False
    navigator._status = lambda *_a: None
    return navigator


class LoadingIsProgressTest(unittest.TestCase):
    def test_a_long_loading_screen_does_not_count_as_stuck(self):
        clock = _Clock()
        states = [ScreenState.LOADING] * 25 + [ScreenState.SANDBOX] * 2
        navigator = _navigator(states, clock)
        with patch.object(navigator_sandbox, "monotonic", clock):
            result = navigator._wait_for_field_hud(
                timeout=15.0, interval=0.0, success_message="ok", failure_message="stuck"
            )
        self.assertTrue(result.success)
        self.assertGreater(clock.now, 15.0)

    def test_a_screen_that_never_changes_still_ends(self):
        clock = _Clock()
        navigator = _navigator([ScreenState.UNKNOWN] * 100, clock)
        with patch.object(navigator_sandbox, "monotonic", clock):
            result = navigator._wait_for_field_hud(
                timeout=15.0, interval=0.0, success_message="ok", failure_message="stuck"
            )
        self.assertFalse(result.success)
        self.assertLessEqual(clock.now, 17.0)

    def test_an_endless_loading_screen_ends_at_the_cap(self):
        clock = _Clock()
        navigator = _navigator([ScreenState.LOADING] * 500, clock)
        with patch.object(navigator_sandbox, "monotonic", clock):
            result = navigator._wait_for_field_hud(
                timeout=15.0, interval=0.0, success_message="ok", failure_message="stuck"
            )
        self.assertFalse(result.success)
        self.assertLess(clock.now, 15.0 + navigator_sandbox.SANDBOX_NAVIGATION_WALK_TIMEOUT + 2)


class RewardPageGetsItsTurnTest(unittest.TestCase):
    def test_the_first_wait_leaves_time_for_the_reward_page(self):
        failure = NavigationResult(False, ScreenState.UNKNOWN, "入场确认超时")
        success = NavigationResult(True, ScreenState.SANDBOX, "Q_sp1")
        clock = _Clock()
        timeouts = []

        def wait(**kwargs):
            timeouts.append(kwargs["timeout"])
            clock.now += kwargs["timeout"]
            return failure if len(timeouts) == 1 else success

        pages = Mock(return_value=CartridgeSpecialPageResult.HANDLED)
        navigator = Navigator(
            SimpleNamespace(_handle_recent_cartridge_special_pages=pages), SimpleNamespace()
        )
        navigator._wait_for_field_hud = wait
        with (
            patch.object(navigator_sandbox, "monotonic", clock),
            patch.object(navigator_sandbox, "dismiss_once_per_run", lambda _task: None),
        ):
            result = navigator._wait_for_story_sandbox(1, timeout=45.0)

        self.assertIs(success, result)
        self.assertEqual(45.0 - STORY_ENTRY_PAGE_RESERVE_SECONDS, timeouts[0])
        self.assertLessEqual(pages.call_args.kwargs["timeout"], STORY_ENTRY_PAGE_RESERVE_SECONDS)
        self.assertGreater(pages.call_args.kwargs["timeout"], 0.0)
        self.assertGreaterEqual(timeouts[1], STORY_ENTRY_AFTER_PAGE_SECONDS)


if __name__ == "__main__":
    unittest.main()
