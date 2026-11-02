"""Presses that had one try and no remedy (audit of helper presses, Leo
2026-11-02 「每個無害的按鍵都要有補救」「說了10次以上」)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.JunkGearTask import JunkGearTask

from src.utils import field_battle

LEAVE = SimpleNamespace(name="离开", x=900, y=900, width=80, height=40)
# The result screen: its title and its 离开.
RESULT = [SimpleNamespace(name=field_battle.RESULT_TITLES[0], x=900, y=100, width=200, height=50), LEAVE]


def _battle_task(screens):
    task = object.__new__(BaseBD2Task)
    task.log_info = lambda *_a, **_k: None
    task.sleep = lambda *_a, **_k: None
    presses = []
    task._click_battle_box = lambda box, after_sleep=0.0: presses.append(box) or True
    reads = iter(screens)
    last = {"boxes": []}

    def boxes():
        last["boxes"] = next(reads, last["boxes"])
        return last["boxes"]

    task._battle_boxes = boxes
    return task, presses


class BattleLeaveTest(unittest.TestCase):
    def test_dropped_leave_is_pressed_once_more(self):
        task, presses = _battle_task([RESULT, []])
        with patch("src.tasks.BaseBD2Task.SLOW_PC_GRACE_SECONDS", 0.0):
            self.assertEqual("left", BaseBD2Task._press_battle_leave(task, "跑图", LEAVE))
        self.assertEqual(2, len(presses))

    def test_leave_taken_first_time_is_not_pressed_again(self):
        task, presses = _battle_task([[]])
        self.assertEqual("left", BaseBD2Task._press_battle_leave(task, "跑图", LEAVE))
        self.assertEqual(1, len(presses))

    def test_leave_still_there_after_two_presses_says_why(self):
        task, presses = _battle_task([RESULT])
        with patch("src.tasks.BaseBD2Task.SLOW_PC_GRACE_SECONDS", 0.0):
            why = BaseBD2Task._press_battle_leave(task, "跑图", LEAVE)
        self.assertIn("两次", why)
        self.assertEqual(2, len(presses))


class SortOptionTest(unittest.TestCase):
    def _task(self, labels):
        task = object.__new__(JunkGearTask)
        task.log_info = lambda *_a, **_k: None
        task.sleep = lambda *_a, **_k: None
        presses = []
        task._click_reference_box = lambda box, after_sleep=0.0: presses.append(box)
        reads = iter(labels)
        last = {"label": None}

        def menu():
            last["label"] = next(reads, last["label"])
            return [last["label"]]

        task._sort_menu_boxes = menu
        return task, presses

    def test_dropped_option_press_is_pressed_once_more(self):
        # before, after the 1st press (unchanged), after the 2nd (changed)
        task, presses = self._task(["品质", "品质", "强化值"])
        with patch("src.tasks.JunkGearTask.active_sort_label", lambda boxes: boxes[0]), patch(
            "src.tasks.JunkGearTask.SORT_MENU_WAIT_SECONDS", 0.0
        ):
            JunkGearTask._pick_sort_option(task, "强化值")
        self.assertEqual(2, len(presses))

    def test_option_taken_is_pressed_once(self):
        task, presses = self._task(["品质", "强化值"])
        with patch("src.tasks.JunkGearTask.active_sort_label", lambda boxes: boxes[0]), patch(
            "src.tasks.JunkGearTask.SORT_MENU_WAIT_SECONDS", 0.0
        ):
            JunkGearTask._pick_sort_option(task, "强化值")
        self.assertEqual(1, len(presses))


if __name__ == "__main__":
    unittest.main()
