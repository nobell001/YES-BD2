"""YES-BD2 issue #28 (2026-10-15): with the game closed the auto-login check
ran every few seconds as the current task (「正在跑：自动登录游戏」 on 首页),
and a 开始 pressed then was only queued behind it, so the game never opened."""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks.trigger import AutoLoginTask as module
from src.tasks.trigger.AutoLoginTask import AutoLoginTask


class AutoLoginGameClosedTest(unittest.TestCase):
    def _task(self, state="waiting"):
        task = AutoLoginTask.__new__(AutoLoginTask)
        task._finished = False
        task._state = state
        task.trigger_interval = 0
        task.last_trigger_time = 0
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        # No 一键日常 waiting for the login (tests/test_waiting_run_game_gone.py).
        task._executor = SimpleNamespace(get_task_by_class=lambda cls: None)
        return task

    def test_closed_game_is_not_checked(self):
        task = self._task()
        with mock.patch.object(module, "game_running", return_value=False):
            self.assertFalse(AutoLoginTask.should_trigger(task))
        self.assertEqual("等待游戏启动", task.info["阶段"])

    def test_running_game_is_checked(self):
        task = self._task()
        with mock.patch.object(module, "game_running", return_value=True):
            self.assertTrue(AutoLoginTask.should_trigger(task))

    def test_cannot_tell_keeps_checking(self):
        task = self._task()
        with mock.patch.object(module, "game_running", return_value=None):
            self.assertTrue(AutoLoginTask.should_trigger(task))

    def test_closed_mid_login_starts_over_next_opening(self):
        task = self._task("waiting_loading")
        task._login_clicked_at = 12.0
        with mock.patch.object(module, "game_running", return_value=False):
            self.assertFalse(AutoLoginTask.should_trigger(task))
        self.assertEqual("waiting", task._state)
        self.assertIsNone(task._login_clicked_at)
        self.assertFalse(task._finished)

    def test_finished_login_does_not_look_for_the_game(self):
        task = self._task("done")
        task._finished = True
        with mock.patch.object(module, "game_running", side_effect=AssertionError):
            self.assertFalse(AutoLoginTask.should_trigger(task))


if __name__ == "__main__":
    unittest.main()
