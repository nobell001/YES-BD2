"""Player v0.4.3, 1080p windowed, 2026-11-19 19:38 (problem summary).

After cooking, a Steam friend toast (「… Counter-Strike 2」) sat over the
bottom-right corner, x ≥ ~1580 and y ≥ ~990 at 1080p, covering all three
skill group buttons (1671/1749/1824, 1011): 「想把技能组切回原本的第1组，但现在
认到的是认不出」.  A toast goes away after a few seconds: an unclear read on
the field is looked at again before it is given up (cooking and 跑图 alike).
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.map_trade.action_icons import (
    SKILL_GROUP_UNCLEAR_POLL_SECONDS,
    SKILL_GROUP_UNCLEAR_WAIT_SECONDS,
    read_skill_group_waiting,
    selected_skill_group,
)
from src.tasks.map_trade.collector_constants import SKILL_GROUP_RELATIVE_POINTS
from src.tasks.map_trade.skill_group_keeper import SkillGroupKeeper
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_cooking import COOKING_SKILL_GROUP_POINTS
from src.utils.wait_limits import STUCK_SECONDS

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade" / "skill_groups"


def _frame(group, toast=False):
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[810:1080, 1440:1920] = cv2.imread(str(FIXTURES / f"group{group}_br.png"))
    if toast:
        # The Steam toast: a dark panel with an avatar and a green line.
        frame[990:1080, 1580:1920] = (30, 26, 24)
        frame[1005:1065, 1595:1655] = (200, 200, 200)
        frame[1050:1056, 1670:1820] = (60, 170, 90)
    return frame


class _Game:
    """Selected group; the toast covers the next ``toast_looks`` captures."""

    def __init__(self, group, toast_looks):
        self.group = group
        self.toast_looks = toast_looks
        self.clicks = []
        self.logs = []
        self.slept = 0.0

    def capture(self):
        toast = self.toast_looks > 0
        self.toast_looks -= 1
        return _frame(self.group, toast=toast)

    def sleep(self, seconds):
        self.slept += seconds

    def log_info(self, message, **_kwargs):
        self.logs.append(("info", message))

    def log_warning(self, message, **_kwargs):
        self.logs.append(("warning", message))

    def warnings(self):
        return [message for kind, message in self.logs if kind == "warning"]


class ToastReadTest(unittest.TestCase):
    def test_toast_hides_every_group_button(self):
        for group in (1, 2, 3):
            with self.subTest(group=group):
                self.assertEqual(group, selected_skill_group(_frame(group)))
                self.assertIsNone(selected_skill_group(_frame(group, toast=True)))

    def test_read_waits_for_the_toast_to_go(self):
        game = _Game(1, toast_looks=5)
        self.assertEqual(1, read_skill_group_waiting(game.capture, game.sleep))
        self.assertLess(game.slept, SKILL_GROUP_UNCLEAR_WAIT_SECONDS)

    def test_read_gives_up_within_the_stuck_limit(self):
        game = _Game(1, toast_looks=10_000)
        self.assertIsNone(read_skill_group_waiting(game.capture, game.sleep))
        self.assertLessEqual(game.slept, SKILL_GROUP_UNCLEAR_WAIT_SECONDS)
        self.assertLess(SKILL_GROUP_UNCLEAR_WAIT_SECONDS, STUCK_SECONDS)

    def test_clear_read_takes_one_look(self):
        game = _Game(2, toast_looks=0)
        self.assertEqual(2, read_skill_group_waiting(game.capture, game.sleep))
        self.assertEqual(0.0, game.slept)


def _cooking_trader(game):
    trader = object.__new__(Trader)
    trader.task = game

    def click(x, y, after_sleep=0.0):
        game.clicks.append((x, y))
        for group, point in enumerate(COOKING_SKILL_GROUP_POINTS, start=1):
            if (x, y) == point:
                game.group = group

    game.operate_click = click
    trader.vision = SimpleNamespace(capture=game.capture)
    return trader


class CookingRestoreUnderToastTest(unittest.TestCase):
    def test_group_comes_back_when_a_toast_covers_the_buttons(self):
        # Cooking left group 2; the player had 1; a toast covers the corner.
        game = _Game(2, toast_looks=int(3.0 / SKILL_GROUP_UNCLEAR_POLL_SECONDS))
        trader = _cooking_trader(game)
        trader._group_switched = True
        trader._group_before_cooking = 1
        trader._restore_skill_group()
        self.assertEqual(1, game.group)
        self.assertEqual([], game.warnings())

    def test_swallowed_press_is_pressed_once_more(self):
        game = _Game(2, toast_looks=0)
        trader = _cooking_trader(game)
        presses = {"n": 0}
        original = game.operate_click

        def first_swallowed(x, y, after_sleep=0.0):
            presses["n"] += 1
            if presses["n"] == 1:
                game.clicks.append((x, y))
                return
            original(x, y, after_sleep)

        game.operate_click = first_swallowed
        trader._group_switched = True
        trader._group_before_cooking = 1
        trader._restore_skill_group()
        self.assertEqual(1, game.group)
        self.assertEqual(2, presses["n"])
        self.assertEqual([], game.warnings())

    def test_group_read_before_cooking_waits_for_the_toast(self):
        game = _Game(3, toast_looks=4)
        trader = _cooking_trader(game)
        self.assertEqual(3, trader._read_skill_group())


class KeeperUnderToastTest(unittest.TestCase):
    def _keeper(self, game):
        def click(x, y, after_sleep=0.0):
            game.clicks.append((x, y))
            for group, point in SKILL_GROUP_RELATIVE_POINTS.items():
                if (x, y) == point:
                    game.group = group

        game.operate_click = click
        return SkillGroupKeeper(game, SimpleNamespace(capture=game.capture), "地图采集")

    def test_start_group_is_read_after_the_toast(self):
        game = _Game(2, toast_looks=4)
        keeper = self._keeper(game)
        keeper.before_switch()
        self.assertEqual(2, keeper.before)

    def test_put_back_is_confirmed_after_the_toast(self):
        game = _Game(2, toast_looks=0)
        keeper = self._keeper(game)
        keeper.before_switch()
        game.group = 1  # the tool switched
        # The toast shows up right after the press back.
        original = game.operate_click

        def press_then_toast(x, y, after_sleep=0.0):
            original(x, y, after_sleep)
            game.toast_looks = 4

        game.operate_click = press_then_toast
        keeper.restore()
        self.assertEqual(2, game.group)
        self.assertEqual([], game.warnings())


if __name__ == "__main__":
    unittest.main()
