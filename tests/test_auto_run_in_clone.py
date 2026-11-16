"""打开就自动跑日常 and 定时启动 can run in the 桌面分身 (玩家 2026-11-16).

「打开自动跑日常的功能可以加一个选项吗，可以选择打开自动用桌面分身跑日常」:
在桌面跑 or 在桌面分身跑, and Leo 「開啟程式就跑 和定時跑 都可以選擇」: each
its own choice, under 首页's box and in the 定时启动 window.  With 在桌面分身跑 the automatic start opens the 桌面分身
(the tool there runs it); when the 桌面分身 cannot open by itself with
nobody at the PC, it runs on the desktop as before.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from src.tasks.DailyBatchTask import (
    AUTO_WHERE_CLONE,
    AUTO_WHERE_HERE,
    AUTO_WHERE_KEY,
)
from src.ui.shell import actions, autorun, clone_flow, data, schedule_ui
from src.utils import clone_desktop, scheduled_start


class _Harness:
    def setUp(self):
        self.batch = SimpleNamespace(name=data.DAILY_BATCH, config={}, batch_label="一键完成日常")
        self.here = []
        self.clone = []
        self.after = []
        self.problem = None
        self.opens = True
        self.scheduled_in_clone = False
        patches = [
            mock.patch.object(
                scheduled_start,
                "load",
                lambda *a: scheduled_start.Settings(in_clone=self.scheduled_in_clone),
            ),
            mock.patch.object(data, "task_by_name", lambda name: self.batch),
            mock.patch.object(data, "executor", lambda: object()),
            mock.patch.object(data, "busy", lambda: False),
            mock.patch.object(autorun, "remaining", lambda: [1]),
            mock.patch.object(clone_desktop, "in_clone", lambda: False),
            mock.patch.object(clone_flow, "busy_in_clone", lambda: False),
            mock.patch.object(clone_flow, "available", lambda: True),
            mock.patch.object(clone_flow, "auto_problem", lambda scheduled: self.problem),
            mock.patch.object(clone_flow, "auto_start", self._auto_start),
            mock.patch.object(clone_flow, "log_in_this_run", lambda: None),
            mock.patch.object(clone_flow, "message", lambda *a, **k: None),
            mock.patch.object(actions, "game_running", lambda: True),
            mock.patch.object(actions, "start", self._start_here),
            mock.patch.object(schedule_ui, "after_start", self.after.append),
            mock.patch.object(scheduled_start, "screen_locked", lambda: False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(autorun.cancel)
        self.addCleanup(scheduled_start.mark_run_pending, False)
        self.addCleanup(setattr, scheduled_start, "queued", 0)

    def _start_here(self, task, window, run_mode, **kwargs):
        self.here.append((task, run_mode))
        return True

    def _auto_start(self, window, task, run_mode, scheduled=None):
        self.clone.append((task, run_mode, scheduled))
        return self.opens


class ChoiceTest(_Harness, unittest.TestCase):
    def test_the_desktop_is_the_default(self):
        self.assertEqual(AUTO_WHERE_HERE, autorun.where())
        self.assertFalse(autorun.in_clone_chosen())

    def test_the_choice_is_kept_on_the_daily_batch(self):
        autorun.set_where(AUTO_WHERE_CLONE)
        self.assertEqual(AUTO_WHERE_CLONE, self.batch.config[AUTO_WHERE_KEY])
        self.assertTrue(autorun.in_clone_chosen())
        autorun.set_where("nonsense")
        self.assertEqual(AUTO_WHERE_CLONE, autorun.where())

    def test_a_pc_without_the_clone_runs_on_the_desktop(self):
        autorun.set_where(AUTO_WHERE_CLONE)
        with mock.patch.object(clone_flow, "available", lambda: False):
            self.assertFalse(autorun.in_clone_chosen())

    def test_the_key_is_a_daily_batch_setting_with_a_desktop_default(self):
        from src.tasks import DailyBatchTask as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("AUTO_WHERE_KEY: AUTO_WHERE_HERE,", source)


class OpenRunTest(_Harness, unittest.TestCase):
    """打开就自动跑日常 (the 首页 box)."""

    def setUp(self):
        super().setUp()
        self.batch.config["打开工具时自动开始"] = True

    def test_desktop_choice_runs_here(self):
        self.assertTrue(autorun.maybe_start())
        self.assertEqual(1, len(self.here))
        self.assertEqual([], self.clone)

    def test_clone_choice_opens_the_clone(self):
        autorun.set_where(AUTO_WHERE_CLONE)
        self.assertTrue(autorun.maybe_start())
        self.assertEqual([], self.here)
        ((task, run_mode, scheduled),) = self.clone
        self.assertIs(self.batch, task)
        self.assertEqual("incomplete", run_mode)
        self.assertIsNone(scheduled)

    def test_a_clone_that_is_not_set_up_runs_here(self):
        autorun.set_where(AUTO_WHERE_CLONE)
        self.problem = clone_flow.AUTO_NOT_SET_UP
        self.assertTrue(autorun.maybe_start())
        self.assertEqual([], self.clone)
        self.assertEqual(1, len(self.here))

    def test_a_clone_that_does_not_open_runs_here(self):
        autorun.set_where(AUTO_WHERE_CLONE)
        self.opens = False
        self.assertTrue(autorun.maybe_start())
        self.assertEqual(1, len(self.clone))
        self.assertEqual(1, len(self.here))


class ScheduledRunTest(_Harness, unittest.TestCase):
    """定时启动: the slot's own items and settings go with the job."""

    def _start(self):
        autorun._tasks = ["领取邮件"]
        autorun._item_settings = {"镜中之战": {"倍数": 2}}
        scheduled_start.queued = 1
        return autorun.maybe_start(scheduled=True)

    def test_the_slot_goes_to_the_clone_with_its_items(self):
        self.scheduled_in_clone = True
        self.assertTrue(self._start())
        self.assertEqual([], self.here)
        ((_, _, scheduled),) = self.clone
        self.assertEqual(
            {"tasks": ["领取邮件"], "settings": {"镜中之战": {"倍数": 2}}, "queued": 1},
            scheduled,
        )
        # Nothing left here for a later run on the desktop to take.
        self.assertFalse(scheduled_start.take_run_pending())
        self.assertIsNone(scheduled_start.take_run_tasks())
        # The watchdog still checks that the run really begins.
        self.assertEqual([True], self.after)

    def test_a_clone_that_does_not_open_runs_the_slot_here(self):
        self.scheduled_in_clone = True
        self.opens = False
        self.assertTrue(self._start())
        self.assertEqual(1, len(self.here))
        # The slot's items are back for the run here.
        self.assertTrue(scheduled_start.take_run_pending())
        self.assertEqual(["领取邮件"], scheduled_start.take_run_tasks())
        self.assertEqual({"镜中之战": {"倍数": 2}}, scheduled_start.take_run_settings())

    def test_each_has_its_own_choice(self):
        # 打开就跑 in the clone does not move 定时启动 there ...
        autorun.set_where(AUTO_WHERE_CLONE)
        self.assertTrue(self._start())
        self.assertEqual(([], 1), (self.clone, len(self.here)))
        # ... and 定时启动 in the clone leaves 打开就跑 on the desktop.
        autorun.set_where(AUTO_WHERE_HERE)
        self.scheduled_in_clone = True
        self.assertTrue(autorun.in_clone_chosen(scheduled=True))
        self.assertFalse(autorun.in_clone_chosen())

    def test_the_schedule_choice_is_saved_with_the_schedule(self):
        settings = scheduled_start.Settings(in_clone=True)
        self.assertTrue(scheduled_start.Settings.from_json(settings.to_json()).in_clone)
        self.assertNotIn("in_clone", scheduled_start.Settings().to_json())
        self.assertFalse(scheduled_start.Settings.from_json({}).in_clone)

    def test_a_locked_screen_still_stops_it(self):
        self.scheduled_in_clone = True
        failures = []
        with (
            mock.patch.object(scheduled_start, "screen_locked", lambda: True),
            mock.patch.object(schedule_ui, "report_failure", failures.append),
        ):
            self.assertFalse(autorun.maybe_start(scheduled=True))
        self.assertEqual([], self.clone)
        self.assertEqual([schedule_ui.LOCKED_NOTE], failures)


class AutoProblemTest(unittest.TestCase):
    """Nobody may be at the PC: no sign-in box, no Windows confirmation."""

    def setUp(self):
        self.saved = True
        self.admin = True
        self.ready = True
        for patch in (
            mock.patch.object(clone_flow, "available", lambda: True),
            mock.patch.object(clone_flow, "ready_to_go", lambda: self.ready),
            mock.patch.object(clone_desktop, "saved_sign_in", lambda: self.saved),
            mock.patch.object(clone_desktop, "is_admin", lambda: self.admin),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_ready(self):
        self.assertIsNone(clone_flow.auto_problem(True))

    def test_not_set_up(self):
        self.ready = False
        self.assertEqual(clone_flow.AUTO_NOT_SET_UP, clone_flow.auto_problem(False))

    def test_scheduled_needs_a_saved_sign_in(self):
        self.saved = False
        self.assertEqual(clone_flow.AUTO_NO_SAVED_SIGN_IN, clone_flow.auto_problem(True))
        # The player opened the tool: they are there to type it.
        self.assertIsNone(clone_flow.auto_problem(False))

    def test_scheduled_needs_administrator(self):
        self.admin = False
        self.assertEqual(clone_flow.AUTO_NOT_ADMIN, clone_flow.auto_problem(True))
        self.assertIsNone(clone_flow.auto_problem(False))


class JobTest(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        for patch in (
            mock.patch.object(clone_desktop, "DATA_DIR", folder),
            mock.patch.object(clone_desktop, "JOB_FILE", folder / "job.json"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(scheduled_start.mark_run_pending, False)
        self.addCleanup(setattr, scheduled_start, "queued", 0)

    def test_an_automatic_job_is_not_a_press_and_carries_the_slot(self):
        task = SimpleNamespace(name=data.DAILY_BATCH)
        payload = {"tasks": ["领取邮件"], "settings": {}, "queued": 0}
        clone_flow._request_job(object(), task, "incomplete", {"scheduled": payload})
        job = json.loads(clone_desktop.JOB_FILE.read_text(encoding="utf-8"))
        self.assertIs(False, job["by_player"])
        self.assertEqual(payload, job["scheduled"])

    def test_the_open_run_job_has_no_slot(self):
        task = SimpleNamespace(name=data.DAILY_BATCH)
        clone_flow._request_job(None, task, "incomplete", {"scheduled": None})
        job = json.loads(clone_desktop.JOB_FILE.read_text(encoding="utf-8"))
        self.assertIs(False, job["by_player"])
        self.assertNotIn("scheduled", job)

    def test_a_press_is_still_a_press(self):
        task = SimpleNamespace(name=data.DAILY_BATCH)
        clone_flow._request_job(object(), task, "all")
        job = json.loads(clone_desktop.JOB_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("by_player", job)

    def test_the_tool_in_the_clone_takes_the_slot(self):
        clone_flow._take_scheduled(
            {"tasks": ["领取邮件"], "settings": {"镜中之战": {"倍数": 2}}, "queued": 1}
        )
        self.assertEqual(1, scheduled_start.queued)
        self.assertTrue(scheduled_start.take_run_pending())
        self.assertEqual(["领取邮件"], scheduled_start.take_run_tasks())
        self.assertEqual({"镜中之战": {"倍数": 2}}, scheduled_start.take_run_settings())

    def test_no_slot_leaves_nothing_pending(self):
        clone_flow._take_scheduled(None)
        self.assertFalse(scheduled_start.take_run_pending())


class WatchdogTest(unittest.TestCase):
    def test_a_run_going_in_the_clone_has_begun(self):
        batch = SimpleNamespace(name=data.DAILY_BATCH, batch_label="一键完成日常")
        report = {"label": "一键完成日常", "started": 200.0}
        with (
            mock.patch.object(data, "task_by_name", lambda name: batch),
            mock.patch.object(clone_flow, "active_run", lambda: (report, None)),
            mock.patch("src.tasks.run_report.load", lambda label: None),
        ):
            self.assertTrue(schedule_ui.begun_since(100.0))
            self.assertFalse(schedule_ui.begun_since(300.0))

    def test_a_clone_that_does_not_open_is_reported_at_once(self):
        failures = []
        with mock.patch.object(schedule_ui, "report_failure", failures.append):
            schedule_ui._watch_started = 5.0
            schedule_ui.clone_failed("桌面分身没有打开")
        self.assertIsNone(schedule_ui._watch_started)
        self.assertEqual(
            [schedule_ui.CLONE_FAILED_NOTE.format(why="桌面分身没有打开")], failures
        )


class NotifyTest(unittest.TestCase):
    """Leo 「微信通知 一樣要通知」: a run in the 桌面分身 sends the 跑完通知
    from there, like one on the desktop."""

    def test_a_run_in_the_clone_sends_it(self):
        from src.tasks import run_report
        from src.utils import run_notify

        folder = Path(tempfile.mkdtemp())
        sent = []
        with (
            mock.patch.object(clone_desktop, "in_clone", lambda: True),
            mock.patch.object(run_report, "_report_path", lambda: str(folder / "report.json")),
            mock.patch.object(run_notify, "after_run", sent.append),
        ):
            run_report.begin("一键完成日常", "incomplete", [("领取邮件", "领取邮件")])
            run_report.mark("scheduled", True)
            run_report.finish(run_report.ENDED_DONE)
        self.assertEqual(1, len(sent))
        self.assertTrue(sent[0]["scheduled"])

    def test_a_clone_that_does_not_open_sends_why(self):
        from src.tasks import run_report
        from src.utils import run_notify

        folder = Path(tempfile.mkdtemp())
        sent = []
        with (
            mock.patch.object(run_report, "_report_path", lambda: str(folder / "report.json")),
            mock.patch.object(run_notify, "after_run", sent.append),
            mock.patch.object(data, "task_by_name", lambda name: None),
        ):
            schedule_ui.clone_failed("桌面分身没有打开")
        self.assertEqual(1, len(sent))
        self.assertIn("桌面分身没有打开", sent[0]["notice"])


class SwitchUiTest(unittest.TestCase):
    """The switch on 首页 and in the 定时启动 window."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ok import og

        from src.tasks.DailyBatchTask import DAILY_BATCH_CHILDREN

        self.available = True
        self.batch = SimpleNamespace(
            name=data.DAILY_BATCH,
            info={},
            batch_label="一键完成日常",
            config={"打开工具时自动开始": False},
            child_tasks=DAILY_BATCH_CHILDREN,
        )
        for patch in (
            mock.patch.object(data, "task_by_name", lambda name: self.batch),
            mock.patch.object(data, "busy", lambda: False),
            mock.patch.object(data, "executor", lambda: None),
            mock.patch.object(clone_flow, "available", lambda: self.available),
            mock.patch.object(schedule_ui, "problem", ""),
            mock.patch.object(og, "app", SimpleNamespace(tr=lambda text: text), create=True),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def _home(self):
        from src.ui.shell.home import HomePage

        page = HomePage(lambda *_a: None, lambda *_a: None)
        page.resize(1100, 700)
        page.show()
        self.addCleanup(page.close)
        page._refresh_idle()
        QApplication.processEvents()
        return page

    def test_home_box_works_only_while_the_one_above_is_ticked(self):
        # Leo 「要上面那個勾選才可以勾 不然就文字變淡」.
        page = self._home()
        self.assertFalse(page.autorun_clone.isHidden())
        self.assertFalse(page.autorun_clone.isEnabled())
        page.autorun_box.setChecked(True)
        self.assertTrue(page.autorun_clone.isEnabled())
        self.assertFalse(page.autorun_clone.isChecked())
        # Same left edge as the box above.
        self.assertEqual(page.autorun_box.x(), page.autorun_clone.x())
        page.autorun_clone.setChecked(True)
        self.assertEqual(AUTO_WHERE_CLONE, self.batch.config[AUTO_WHERE_KEY])
        page.autorun_clone.setChecked(False)
        self.assertEqual(AUTO_WHERE_HERE, self.batch.config[AUTO_WHERE_KEY])
        page.autorun_box.setChecked(False)
        self.assertFalse(page.autorun_clone.isEnabled())

    def test_home_hides_it_without_the_clone(self):
        self.available = False
        self.batch.config["打开工具时自动开始"] = True
        page = self._home()
        self.assertTrue(page.autorun_clone.isHidden())

    def _dialog(self):
        from src.utils.scheduled_start import Settings, Slot

        host = QWidget()
        host.resize(1100, 760)
        host.show()
        self.addCleanup(host.close)
        with mock.patch.object(schedule_ui, "_settings", Settings(True, True, [Slot(hour=21)])):
            dialog = schedule_ui.ScheduleDialog(host)
        dialog.show()
        self.addCleanup(dialog.close)
        return dialog

    def test_the_schedule_window_saves_its_own_choice(self):
        dialog = self._dialog()
        self.assertFalse(dialog.in_clone.isHidden())
        self.assertFalse(dialog.in_clone.isChecked())
        dialog.in_clone.setChecked(True)
        saved = []
        with mock.patch("src.ui.shell.schedule_week.store", lambda new: saved.append(new) or ""):
            dialog._save()
        self.assertTrue(saved[0].in_clone)
        # 打开就跑 keeps its own.
        self.assertNotIn(AUTO_WHERE_KEY, self.batch.config)

    def test_the_schedule_window_shows_the_saved_choice(self):
        from src.utils.scheduled_start import Settings, Slot

        host = QWidget()
        self.addCleanup(host.close)
        chosen = Settings(True, True, [Slot(hour=21)], in_clone=True)
        with mock.patch.object(schedule_ui, "_settings", chosen):
            dialog = schedule_ui.ScheduleDialog(host)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.in_clone.isChecked())

    def test_the_schedule_window_hides_it_without_the_clone(self):
        self.available = False
        dialog = self._dialog()
        self.assertTrue(dialog.in_clone.isHidden())
        saved = []
        with mock.patch("src.ui.shell.schedule_week.store", lambda new: saved.append(new) or ""):
            dialog._save()
        self.assertFalse(saved[0].in_clone)

if __name__ == "__main__":
    unittest.main()
