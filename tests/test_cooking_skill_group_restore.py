"""Cooking puts the player's skill group back (4K 2026-10-10: 每日跑商's
cooking switched to group 1 and left it there; Leo keeps 跑图 on group 2)."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np
from ok.task.exceptions import TaskDisabledException

from src.tasks.map_trade import trader_cooking
from src.tasks.map_trade.action_icons import selected_skill_group, skill_group_yellow_shares
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_cooking import COOKING_SKILL_GROUP_POINTS

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade" / "skill_groups"


def _frame(name, scale=1):
    """A real 1080p frame's bottom-right corner (the skill bar) on black."""
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[810:1080, 1440:1920] = cv2.imread(str(FIXTURES / f"{name}_br.png"))
    if scale != 1:
        frame = cv2.resize(frame, (1920 * scale, 1080 * scale), interpolation=cv2.INTER_LINEAR)
    return frame


class SelectedGroupTest(unittest.TestCase):
    def test_the_yellow_button_is_the_selected_group(self):
        for group in (1, 2, 3):
            with self.subTest(group=group):
                self.assertEqual(group, selected_skill_group(_frame(f"group{group}")))
                self.assertEqual(group, selected_skill_group(_frame(f"group{group}", scale=2)))

    def test_no_skill_bar_reads_as_unknown(self):
        self.assertIsNone(selected_skill_group(_frame("bigmap")))
        self.assertIsNone(selected_skill_group(np.zeros((1080, 1920, 3), np.uint8)))
        self.assertIsNone(selected_skill_group(None))

    def test_two_yellow_buttons_read_as_unknown(self):
        frame = _frame("group1")
        frame[960:1060, 1690:1800] = _frame("group1")[960:1060, 1610:1720]
        shares = skill_group_yellow_shares(frame)
        self.assertGreater(shares[2], 0.35)
        self.assertIsNone(selected_skill_group(frame))


class _Task:
    def __init__(self):
        self.clicks = []
        self.logs = []

    def operate_click(self, x, y, after_sleep=0.0):
        self.clicks.append((x, y))

    def sleep(self, _seconds):
        pass

    def log_info(self, message, **_kwargs):
        self.logs.append(("info", message))

    def log_warning(self, message, **_kwargs):
        self.logs.append(("warning", message))


def _trader(groups, cooking_in=1, fail=None):
    """The game: ``groups`` is the selected group; a group click selects it."""
    task = _Task()
    state = {"group": groups}
    trader = object.__new__(Trader)
    trader.task = task
    trader._status = lambda *_a: None
    trader._selected_cooking_recipes = lambda: ()

    def capture():
        return _frame(f"group{state['group']}") if state["group"] else _frame("bigmap")

    def click(x, y, after_sleep=0.0):
        task.clicks.append((x, y))
        for group, point in enumerate(COOKING_SKILL_GROUP_POINTS, start=1):
            if (x, y) == point:
                state["group"] = group

    task.operate_click = click

    def click_stable_template(*_a, **_k):
        return state["group"] == cooking_in

    trader.vision = SimpleNamespace(capture=capture, click_stable_template=click_stable_template)

    def enter():
        trader._cooking_opened = True
        if not trader._open_cooking_skill():
            return False
        if fail is not None:
            raise fail
        return True

    trader._enter_cooking_list = enter
    trader._cook_one_recipe = lambda _recipe: None
    trader._leave_cooking_to_q_sp6 = lambda: True
    return trader, task, state


class CookingRestoresGroupTest(unittest.TestCase):
    def _cook(self, trader):
        # The part of run_cooking around the list: enter, then the finally.
        trader._cooking_opened = False
        trader._group_before_cooking = None
        trader._group_switched = False
        try:
            trader._enter_cooking_list()
        finally:
            trader._restore_skill_group(stopped=trader_cooking._stopping())

    def test_group_2_comes_back_after_cooking_on_group_1(self):
        trader, task, state = _trader(groups=2, cooking_in=1)
        self._cook(trader)
        self.assertEqual(2, state["group"])
        self.assertTrue(any("切回原本的第2组" in message for _kind, message in task.logs))

    def test_nothing_is_pressed_when_cooking_was_already_shown(self):
        trader, task, state = _trader(groups=1, cooking_in=1)
        self._cook(trader)
        self.assertEqual([], task.clicks)
        self.assertEqual(1, state["group"])

    def test_it_comes_back_after_a_failure_too(self):
        trader, task, state = _trader(groups=2, cooking_in=1, fail=RuntimeError("list"))
        with self.assertRaises(RuntimeError):
            self._cook(trader)
        self.assertEqual(2, state["group"])

    def test_a_stop_presses_nothing_more_but_says_so(self):
        trader, task, state = _trader(groups=2, cooking_in=1, fail=TaskDisabledException())
        with self.assertRaises(TaskDisabledException):
            self._cook(trader)
        self.assertEqual(1, state["group"])
        self.assertTrue(
            any("原本是第2组" in message for kind, message in task.logs if kind == "warning")
        )

    def test_an_unreadable_group_is_not_guessed(self):
        trader, task, state = _trader(groups=None, cooking_in=1)
        self._cook(trader)
        self.assertTrue(any("没认出原本是第几组" in message for _kind, message in task.logs))
        # Only the search clicks; no extra click back.
        self.assertEqual(1, len(task.clicks))

    def test_run_cooking_restores_in_its_finally(self):
        trader, task, state = _trader(groups=2, cooking_in=1)
        trader._selected_cooking_recipes = lambda: ("x",)
        trader.progress = SimpleNamespace(should_cook=lambda **_k: True)
        with mock.patch.dict(
            trader_cooking.COOKING_RECIPE_SPECS, {"x": SimpleNamespace(file_name="x")}
        ):
            with mock.patch.object(trader_cooking.Path, "is_file", lambda _self: True):
                trader.run_cooking()
        self.assertEqual(2, state["group"])


if __name__ == "__main__":
    unittest.main()
