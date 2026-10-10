"""快速狩猎 tries once more from 主页 when a step stays stuck, and waits
for a menu that is still loading (YES-BD2 #8, snowly233, 2026-10-10:
「有可能脚本点击时画面还在转圈卡顿，需要多添加确认步骤」, 「卡住了建议设置成
退出主界面从头再来」).
"""

import unittest

from src.tasks import problem_report
from src.tasks.QuickHuntTask import QuickHuntTask


def _task(runs, home=True):
    task = object.__new__(QuickHuntTask)
    task._quick_hunt_test_action = None
    task.config = {"启用": True}
    task.logs, task.runs = [], 0
    task.info_set = lambda *_a, **_k: None
    task.log_info = lambda message, *_a, **_k: task.logs.append(message)
    task.log_completion = lambda *_a, **_k: None
    task._wait_for_quick_hunt_home = lambda: home

    def run_quick_hunt():
        task.runs += 1
        return runs[task.runs - 1]

    task.run_quick_hunt = run_quick_hunt
    return task


class RetryFromHomeTest(unittest.TestCase):
    def test_a_stuck_run_is_tried_once_more_from_home(self):
        task = _task([False, True])
        self.assertTrue(QuickHuntTask.run(task))
        self.assertEqual(2, task.runs)
        self.assertIn("从头再试一次", "\n".join(task.logs))

    def test_it_stops_after_the_second_try(self):
        task = _task([False, False])
        self.assertFalse(QuickHuntTask.run(task))
        self.assertEqual(2, task.runs)

    def test_no_second_try_away_from_home(self):
        # Unknown screen: nothing is pressed; the batch takes it home.
        task = _task([False], home=False)
        self.assertFalse(QuickHuntTask.run(task))
        self.assertEqual(1, task.runs)

    def test_a_done_run_is_not_repeated(self):
        task = _task([True])
        self.assertTrue(QuickHuntTask.run(task))
        self.assertEqual(1, task.runs)

    def test_the_second_try_drops_the_first_give_up_frame(self):
        forgotten = []
        original = problem_report.forget_give_up
        problem_report.forget_give_up = lambda: forgotten.append(True)
        self.addCleanup(setattr, problem_report, "forget_give_up", original)
        QuickHuntTask.run(_task([False, False]))
        self.assertEqual([True], forgotten)


def _menu_task(menu_after, home_after_press):
    """The menu shows after ``menu_after`` seconds of waiting."""
    task = object.__new__(QuickHuntTask)
    task.config = {"快速狩猎界面等待秒数": 8.0}
    task.logs, task.presses, task.waited = [], [], [0.0]
    task.info_set = lambda *_a, **_k: None
    task._status_set = lambda *_a, **_k: None
    task.log_info = lambda message, *_a, **_k: task.logs.append(message)
    task.capture_frame = lambda: None
    task._wait_for_quick_hunt_home = lambda: True
    task._quick_hunt_home_signals = lambda _frame: (not task.presses or home_after_press, 0, 0, "")

    def click_ocr(_patterns, _roi, _timeout, name):
        task.presses.append(name)
        return True

    def wait_ocr(_patterns, _roi, timeout, name):
        task.waited[0] += timeout
        return ("狩猎场" if task.waited[0] >= menu_after else "", None)

    task._quick_hunt_click_ocr = click_ocr
    task._quick_hunt_wait_ocr = wait_ocr
    task.operate_click = lambda *_a, **_k: task.presses.append("fixed")
    return task


class LoadingMenuTest(unittest.TestCase):
    def test_a_slow_menu_is_waited_for_without_pressing_again(self):
        task = _menu_task(menu_after=10.0, home_after_press=False)
        self.assertEqual("opened", task._quick_hunt_open_menu())
        self.assertEqual(["主页快速狩猎入口"], task.presses)
        self.assertIn("可能还在加载", "\n".join(task.logs))

    def test_a_menu_that_never_shows_fails_after_the_wait(self):
        task = _menu_task(menu_after=99.0, home_after_press=False)
        self.assertEqual("failed", task._quick_hunt_open_menu())
        self.assertEqual(1, len(task.presses))

    def test_a_press_lost_on_home_is_pressed_again(self):
        task = _menu_task(menu_after=6.0, home_after_press=True)
        self.assertEqual("opened", task._quick_hunt_open_menu())
        self.assertEqual(2, len(task.presses))


if __name__ == "__main__":
    unittest.main()
