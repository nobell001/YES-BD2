"""A tool 定时启动 opened goes straight to 一键日常 (Leo 2026-10-22).

「使用排程開啟的 有沒有確保 打開程式就是直接開始日常」 and 「如果遇到更新
要點掉框框甚麼的 也要處理」: a tool that is not free yet is waited for, and
nothing that waits for a click shows on a scheduled open.
"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer

from src.ui.shell import autorun, data, schedule_ui
from src.utils import scheduled_start


class _Clock:
    def __init__(self):
        self.now = 1000.0
        self.later = []

    def single_shot(self, ms, call):
        self.later.append((ms, call))

    def run_next(self):
        ms, call = self.later.pop(0)
        self.now += ms / 1000
        call()


class _Harness:
    def setUp(self):
        self.clock = _Clock()
        self.busy = True
        self.current = None
        self.started = []
        self.failures = []
        batch = SimpleNamespace(name=data.DAILY_BATCH)
        self.batch = batch
        patches = [
            mock.patch.object(QTimer, "singleShot", self.clock.single_shot),
            mock.patch.object(autorun.time, "time", lambda: self.clock.now),
            mock.patch.object(data, "executor", lambda: object()),
            mock.patch.object(data, "busy", lambda: self.busy),
            mock.patch.object(data, "current_task", lambda: self.current),
            mock.patch.object(data, "task_by_name", lambda name: batch),
            mock.patch.object(autorun, "remaining", lambda: [1]),
            mock.patch("src.utils.clone_desktop.in_clone", lambda: False),
            mock.patch("src.ui.shell.clone_flow.busy_in_clone", lambda: False),
            mock.patch.object(autorun, "maybe_start", self.started.append),
            mock.patch.object(schedule_ui, "report_failure", self.failures.append),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(autorun.cancel)
        autorun.cancel()


class WaitTest(_Harness, unittest.TestCase):
    def test_a_busy_tool_is_waited_for_then_it_starts(self):
        self.assertTrue(autorun.schedule(scheduled=True))
        self.assertIsNone(autorun.seconds_left())  # waiting, not counting down
        for _ in range(5):
            self.clock.run_next()
        self.assertEqual([], self.started)
        self.busy = False
        self.clock.run_next()  # free now: the count down begins
        self.assertIsNotNone(autorun.seconds_left())
        self.clock.run_next()
        self.assertEqual([True], self.started)
        self.assertEqual([], self.failures)

    def test_never_free_says_why(self):
        autorun.schedule(scheduled=True)
        while self.clock.later:
            self.clock.run_next()
        self.assertEqual([], self.started)
        self.assertEqual(1, len(self.failures))
        self.assertIn(f"{autorun.WAIT_MINUTES} 分钟", self.failures[0])
        self.assertLessEqual(self.clock.now - 1000.0, autorun.WAIT_MINUTES * 60 + 11)

    def test_busy_again_during_the_count_down_waits_again(self):
        self.busy = False
        autorun.schedule(scheduled=True)
        self.busy = True
        self.clock.run_next()  # the count down ends while a task runs
        self.assertEqual([], self.started)
        self.busy = False
        self.clock.run_next()
        self.clock.run_next()
        self.assertEqual([True], self.started)

    def test_daily_already_running_is_left_alone(self):
        self.current = self.batch
        self.assertFalse(autorun.schedule(scheduled=True))
        self.assertEqual([], self.clock.later)
        self.assertEqual([], self.failures)

    def test_the_players_own_box_does_not_wait(self):
        with mock.patch.object(autorun, "enabled", return_value=True):
            self.assertFalse(autorun.schedule())
        self.assertEqual([], self.clock.later)

    def test_cancel_stops_the_wait(self):
        autorun.schedule(scheduled=True)
        autorun.cancel()
        self.clock.run_next()
        self.assertEqual([], self.clock.later)
        self.assertEqual([], self.failures)


class _AccountHarness(_Harness):
    def setUp(self):
        super().setUp()
        from src.utils import accounts

        self.busy = False
        self.now_id = "1"
        self.switched = []
        known = [accounts.Account("1", "", ""), accounts.Account("2", "", "")]

        def switch(account_id):
            if self.busy:
                return False
            self.switched.append(account_id)
            self.now_id = account_id
            return True

        patches = [
            mock.patch.object(accounts, "accounts", lambda: known),
            mock.patch.object(accounts, "current_id", lambda: self.now_id),
            mock.patch.object(data, "switch_account", switch),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)


class SlotAccountTest(_AccountHarness, unittest.TestCase):
    """YES-BD2 #64: each slot runs its own 帳號."""

    def test_the_slots_account_is_switched_to_before_it_starts(self):
        seen = []
        with mock.patch.object(autorun, "remaining", lambda: seen.append(self.now_id) or [1]):
            self.assertTrue(autorun.schedule(scheduled=True, account="2"))
        self.assertEqual(["2"], self.switched)
        # What is left today is the 帳號's own, read after the switch.
        self.assertEqual("2", seen[-1])
        self.clock.run_next()
        self.assertEqual([True], self.started)

    def test_the_current_account_is_not_switched(self):
        autorun.schedule(scheduled=True, account="1")
        autorun.schedule(scheduled=True)
        self.assertEqual([], self.switched)

    def test_a_busy_tool_switches_once_it_is_free(self):
        self.busy = True
        autorun.schedule(scheduled=True, account="2")
        self.clock.run_next()
        self.assertEqual([], self.switched)
        self.busy = False
        self.clock.run_next()
        self.assertEqual(["2"], self.switched)
        self.clock.run_next()
        self.assertEqual([True], self.started)

    def test_a_deleted_account_runs_the_current_one(self):
        autorun.schedule(scheduled=True, account="9")
        self.assertEqual([], self.switched)
        self.clock.run_next()
        self.assertEqual([True], self.started)

    def test_a_switch_that_fails_says_why_and_does_not_run(self):
        with mock.patch.object(data, "switch_account", lambda account_id: False):
            self.assertFalse(autorun.schedule(scheduled=True, account="2"))
        self.assertEqual([], self.started)
        self.assertEqual(1, len(self.failures))
        self.assertIn("账号 2", self.failures[0])

    def test_a_run_of_another_account_is_waited_for_and_5_minutes_more(self):
        # Leo 2026-10-29 「他也不會幫你換帳號 無縫一定會出問題」「跑完後間隔5分鐘
        # 再繼續」: 帳號 1 is still running when 帳號 2's time comes.
        self.current, self.busy = self.batch, True
        self.assertTrue(autorun.schedule(scheduled=True, account="2"))
        for _ in range(5):
            self.clock.run_next()
        self.assertEqual([], self.switched)
        self.current, self.busy = None, False
        ended = self.clock.now
        while not self.switched:
            self.clock.run_next()
        self.assertGreaterEqual(self.clock.now - ended, autorun.GAP_AFTER_RUN_S)
        self.assertEqual(["2"], self.switched)
        self.clock.run_next()
        self.assertEqual([True], self.started)
        self.assertEqual([], self.failures)

    def test_a_run_of_the_same_account_is_left_alone(self):
        self.current, self.busy = self.batch, True
        self.assertFalse(autorun.schedule(scheduled=True, account="1"))
        self.assertFalse(autorun.schedule(scheduled=True))
        self.assertEqual([], self.switched)

    def test_the_clone_is_never_switched_under(self):
        with mock.patch("src.utils.clone_desktop.in_clone", lambda: True):
            self.assertFalse(autorun.schedule(scheduled=True, account="2"))
        self.assertEqual([], self.switched)
        self.assertEqual([], self.failures)

    def test_nothing_left_on_the_current_account_still_runs_the_other(self):
        left = {"1": [], "2": [1]}
        with mock.patch.object(autorun, "remaining", lambda: left[self.now_id]):
            self.assertTrue(autorun.schedule(scheduled=True, account="2"))
        self.assertEqual(["2"], self.switched)

    def test_the_players_own_box_never_switches(self):
        with mock.patch.object(autorun, "enabled", return_value=True):
            autorun.schedule(account="2")
        self.assertEqual([], self.switched)


class QueueTest(_AccountHarness, unittest.TestCase):
    """Two 帳號 at one time (Leo 2026-10-29 「同時段同帳號不能重疊 不同帳號
    可以」): one runs, then the other."""

    def setUp(self):
        super().setUp()
        self.begun = False

        def start(scheduled):
            self.started.append(self.now_id)
            self.current, self.busy = self.batch, True
            return True

        patches = [
            mock.patch.object(autorun, "maybe_start", start),
            mock.patch.object(schedule_ui, "begun_since", lambda since: self.begun),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _jobs(self, *accounts):
        return [{"account": a, "tasks": None, "item_settings": {}} for a in accounts]

    def test_the_second_account_runs_after_the_first_ends(self):
        self.assertTrue(autorun.schedule_jobs(self._jobs("1", "2")))
        self.assertEqual(1, scheduled_start.queued)
        self.clock.run_next()  # 帳號 1 starts
        self.assertEqual(["1"], self.started)
        self.begun = True
        for _ in range(5):
            self.clock.run_next()
        self.assertEqual([], self.switched)  # never under a run
        self.current, self.busy = None, False
        ended = self.clock.now
        while not self.switched:
            self.clock.run_next()
        self.assertGreaterEqual(self.clock.now - ended, autorun.GAP_AFTER_RUN_S)
        self.assertEqual(["2"], self.switched)
        self.assertEqual(0, scheduled_start.queued)
        self.clock.run_next()
        self.assertEqual(["1", "2"], self.started)

    def test_a_run_that_never_shows_up_lets_the_next_go(self):
        autorun.schedule_jobs(self._jobs("1", "2"))
        self.clock.run_next()
        self.current, self.busy = None, False  # it did not begin
        for _ in range(autorun.BEGIN_LIMIT_S // (autorun.WAIT_RETRY_MS // 1000) + 2):
            if self.switched:
                break
            self.clock.run_next()
        self.assertEqual(["2"], self.switched)

    def test_a_slot_coming_during_a_run_waits_for_it(self):
        autorun.schedule_jobs(self._jobs("1"))
        self.clock.run_next()
        self.begun = True
        # 帳號 2's slot comes 30 minutes later, 帳號 1 still running.
        self.assertTrue(autorun.schedule(scheduled=True, account="2"))
        self.clock.run_next()
        self.assertEqual([], self.switched)
        self.current, self.busy = None, False
        ended = self.clock.now
        while not self.switched:
            self.clock.run_next()
        self.assertGreaterEqual(self.clock.now - ended, autorun.GAP_AFTER_RUN_S)

    def test_one_account_is_queued_once(self):
        autorun.schedule_jobs(self._jobs("1", "2", "2"))
        self.assertEqual(1, scheduled_start.queued)

    def test_cancel_empties_the_line(self):
        autorun.schedule_jobs(self._jobs("1", "2"))
        autorun.cancel()
        self.assertEqual(0, scheduled_start.queued)


class SlotTasksTest(_Harness, unittest.TestCase):
    """Leo 2026-10-29: what is left today counts the slot's own items."""

    def setUp(self):
        super().setUp()
        self.busy = False
        children = [
            SimpleNamespace(key="a", included=True),
            SimpleNamespace(key="b", included=False),
        ]
        self.done = set()
        for patch in (
            mock.patch.object(data, "batch_children", lambda batch: children),
            mock.patch.object(data, "child_done", lambda child: child.key in self.done),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        # The harness stands in for remaining(); this test uses the real one.
        self.real_remaining = mock.patch.object(autorun, "remaining", _real_remaining)
        self.real_remaining.start()
        self.addCleanup(self.real_remaining.stop)

    def test_the_slots_items_decide_what_is_left(self):
        self.done = {"a"}
        # Ticked 「a」 is done: nothing left for the 帳號's ticks ...
        self.assertFalse(autorun.schedule(scheduled=True))
        # ... but the slot asks for 「b」.
        self.assertTrue(autorun.schedule(scheduled=True, tasks=["b"]))
        self.assertEqual(["b"], [child.key for child in autorun.remaining()])
        autorun.cancel()
        self.assertEqual([], autorun.remaining())

    def test_the_players_own_box_uses_the_ticks(self):
        with mock.patch.object(autorun, "enabled", return_value=True):
            autorun.schedule(tasks=["b"])
        self.assertEqual(["a"], [child.key for child in autorun.remaining()])


_real_remaining = autorun.remaining


class QuietOpenTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(scheduled_start, "launched_by_schedule", True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_ok_notices_are_left_out(self):
        from ok.ui.qt.MainWindow import MainWindow

        from src.compat import quiet_scheduled_open

        quiet_scheduled_open.install()
        window = SimpleNamespace(switchTo=mock.Mock())
        MainWindow.show_startup_version_change_notice(window)
        MainWindow.show_update_copyright(window)
        window.switchTo.assert_not_called()

    def test_launcher_notices_are_left_out(self):
        from src.compat import launcher_update_notice

        with mock.patch.object(QTimer, "singleShot") as later:
            launcher_update_notice.schedule_notices(SimpleNamespace(config={}))
        later.assert_not_called()
        with mock.patch.object(scheduled_start, "launched_by_schedule", False), \
                mock.patch.object(QTimer, "singleShot") as later:
            launcher_update_notice.schedule_notices(SimpleNamespace(config={}))
        self.assertEqual(2, later.call_count)

    def test_walk_throughs_wait_for_the_next_open(self):
        from src.ui.shell import new_setting_notice

        with mock.patch.object(QTimer, "singleShot") as later:
            new_setting_notice.schedule(SimpleNamespace())
        later.assert_not_called()


if __name__ == "__main__":
    unittest.main()
