"""Home never showing after the login does not keep a run waiting forever
(audit #39/#72): after 3 timeouts in a row the waiting 一键日常/周常 is
cancelled with the reason; only the first timeout and the give-up notify."""

import unittest
from types import SimpleNamespace

from src.tasks.DailyBatchTask import DailyBatchTask, WeeklyBatchTask
from src.tasks.trigger.AutoLoginTask import LOGIN_TIMEOUTS_BEFORE_GIVING_UP, AutoLoginTask


class _Batch:
    def __init__(self):
        self._start_after_login = True
        self.calls = []

    def cancel_resume(self):
        self.calls.append("cancel_resume")
        self._start_after_login = False

    def disable(self):
        self.calls.append("disable")


def _task(batches):
    task = object.__new__(AutoLoginTask)
    task.config = {"登录超时重试间隔秒数": 60.0}
    task._login_clicked_at = 0.0
    task.warnings = []
    task.log_warning = lambda message, notify=False: task.warnings.append((message, notify))
    task.info_set = lambda *_a, **_k: None
    task._reset_login_state = lambda *_a, **_k: None
    task._executor = SimpleNamespace(get_task_by_class=lambda cls: batches.get(cls))
    return task


class LoginWaitCapTest(unittest.TestCase):
    def test_the_third_timeout_cancels_the_waiting_run_with_a_reason(self):
        daily = _Batch()
        task = _task({DailyBatchTask: daily})
        for minute in range(LOGIN_TIMEOUTS_BEFORE_GIVING_UP - 1):
            task._handle_login_wait_timeout(300.0 * (minute + 1))
        self.assertEqual([], daily.calls)
        task._handle_login_wait_timeout(900.0)
        self.assertEqual(["cancel_resume", "disable"], daily.calls)
        reason, notify = task.warnings[-1]
        self.assertIn("失败", reason)
        self.assertIn("没有等到主页", reason)
        self.assertTrue(notify)

    def test_only_the_first_timeout_notifies(self):
        task = _task({})
        for minute in range(5):
            task._handle_login_wait_timeout(300.0 * (minute + 1))
        self.assertEqual([True, False, False, False, False], [n for _m, n in task.warnings])
        self.assertTrue(task._login_retry_not_before > 0)

    def test_a_run_started_later_is_cancelled_on_the_next_timeout(self):
        weekly = _Batch()
        weekly._start_after_login = False
        task = _task({WeeklyBatchTask: weekly})
        for minute in range(LOGIN_TIMEOUTS_BEFORE_GIVING_UP):
            task._handle_login_wait_timeout(300.0 * (minute + 1))
        self.assertEqual([], weekly.calls)
        weekly._start_after_login = True
        task._handle_login_wait_timeout(1500.0)
        self.assertEqual(["cancel_resume", "disable"], weekly.calls)


if __name__ == "__main__":
    unittest.main()
