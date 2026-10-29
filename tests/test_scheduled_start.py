import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.utils import scheduled_start as ss
from src.utils.scheduled_start import KIND_RESET, KIND_TIME, Settings, Slot

TAIPEI = timezone(timedelta(hours=8))
NEW_YORK = timezone(timedelta(hours=-4))


def _done(code=0, out=""):
    return subprocess.CompletedProcess([], code, out, "")


class SettingsTest(unittest.TestCase):
    """Leo 2026-10-22: several time slots, each with its own time and days."""

    def test_round_trip(self):
        slots = [Slot(KIND_TIME, 21, 0), Slot(KIND_TIME, 7, 15, [5, 6], False)]
        settings = Settings(True, False, slots)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "configs" / "scheduled_start.json"
            ss.save(settings, path)
            again = ss.load(path)
        self.assertEqual(again.to_json(), settings.to_json())
        self.assertFalse(again.migrated)

    def test_missing_or_broken_file_is_off(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "x.json"
            self.assertFalse(ss.load(path).enabled)
            path.write_text("{oops", encoding="utf-8")
            self.assertFalse(ss.load(path).enabled)

    def test_bad_slots_are_dropped(self):
        settings = Settings.from_json(
            {"enabled": True, "slots": [{"time": "25:00"}, {"time": "9:30", "days": [0, 9]}, 3]}
        )
        self.assertEqual([s.to_json() for s in settings.slots],
                         [{"kind": "time", "time": "09:30", "days": [0], "on": True}])

    def test_off_means_no_active_slot(self):
        settings = Settings(False, True, [Slot(KIND_RESET)])
        self.assertEqual(settings.active_slots(), [])
        settings.enabled = True
        settings.slots.append(Slot(KIND_TIME, days=[]))
        settings.slots.append(Slot(KIND_TIME, on=False))
        self.assertEqual(len(settings.active_slots()), 1)


class TimesTest(unittest.TestCase):
    def test_reset_follows_game_time_in_any_zone(self):
        self.assertEqual(ss.reset_clock(datetime(2026, 10, 22, 12, tzinfo=TAIPEI)), (8, 5))
        # 08:05 UTC+8 is 20:05 the day before in New York (UTC-4).
        self.assertEqual(ss.reset_clock(datetime(2026, 10, 22, 12, tzinfo=NEW_YORK)), (20, 5))

    def test_next_run_picks_the_nearest_day(self):
        settings = Settings(True, True, [Slot(KIND_TIME, 21, 0, [5])])  # Saturday
        now = datetime(2026, 10, 22, 22, 0, tzinfo=TAIPEI)  # Thursday
        self.assertEqual(ss.next_run(settings, now), datetime(2026, 10, 24, 21, 0, tzinfo=TAIPEI))

    def test_next_run_reset_slot(self):
        settings = Settings(True, True, [Slot(KIND_RESET)])
        before = datetime(2026, 10, 22, 7, 0, tzinfo=TAIPEI)
        after = datetime(2026, 10, 22, 9, 0, tzinfo=TAIPEI)
        self.assertEqual(ss.next_run(settings, before), datetime(2026, 10, 22, 8, 5, tzinfo=TAIPEI))
        self.assertEqual(ss.next_run(settings, after), datetime(2026, 10, 23, 8, 5, tzinfo=TAIPEI))

    def test_nothing_when_off(self):
        self.assertIsNone(ss.next_run(Settings(False), datetime.now(TAIPEI)))

    def test_due_only_once_and_not_too_late(self):
        settings = Settings(True, True, [Slot(KIND_TIME, 21, 0)])
        slot = datetime(2026, 10, 22, 21, 0, tzinfo=TAIPEI)
        self.assertEqual(
            ss.due_between(settings, slot - timedelta(seconds=20), slot + timedelta(seconds=1)), slot
        )
        # The next tick does not start it again.
        self.assertIsNone(
            ss.due_between(settings, slot + timedelta(seconds=1), slot + timedelta(seconds=21))
        )
        # The PC slept through it and woke an hour later: no start then.
        self.assertIsNone(
            ss.due_between(settings, slot - timedelta(minutes=1), slot + timedelta(hours=1))
        )


class SlotAccountTest(unittest.TestCase):
    """YES-BD2 #64: each slot its own 帳號 (and its own items, Leo 2026-10-29)."""

    def setUp(self):
        self.settings = Settings(True, True, [
            Slot(KIND_TIME, 8, 0, account="1"),
            Slot(KIND_TIME, 21, 0, account="2"),
            Slot(KIND_TIME, 13, 0, days=[5, 6]),
        ])

    def test_the_account_is_saved_and_old_files_have_none(self):
        again = Settings.from_json(self.settings.to_json())
        self.assertEqual(["1", "2", ""], [slot.account for slot in again.slots])
        self.assertFalse(again.migrated)
        old = Settings.from_json({"enabled": True, "slots": [{"kind": "time", "time": "08:00", "days": [0], "on": True}]})
        self.assertEqual("", old.slots[0].account)
        self.assertNotIn("account", old.slots[0].to_json())
        self.assertFalse(old.migrated)

    def test_the_slot_that_fired_gives_the_account(self):
        thursday = datetime(2026, 10, 22, tzinfo=TAIPEI)
        at = lambda h, m=0: thursday.replace(hour=h, minute=m)
        self.assertEqual("1", ss.account_at(self.settings, at(8, 0)))
        # Opened late after an update: still the slot that fired.
        self.assertEqual("1", ss.account_at(self.settings, at(8, 50)))
        self.assertEqual("2", ss.account_at(self.settings, at(21, 0, )))
        self.assertEqual("2", ss.account_at(self.settings, at(7, 59) + timedelta(days=1)))
        # The Saturday slot runs the current one.
        self.assertEqual("", ss.account_at(self.settings, at(13, 5) + timedelta(days=2)))

    def test_switched_off_slots_never_count(self):
        self.settings.slots[1].on = False
        moment = datetime(2026, 10, 22, 21, 1, tzinfo=TAIPEI)
        self.assertEqual("1", ss.account_at(self.settings, moment))
        self.assertEqual("", ss.account_at(Settings(), moment))


class SharedTimeTest(unittest.TestCase):
    """Leo 2026-10-29 「同時段同帳號不能重疊 不同帳號可以」."""

    def test_an_hour_for_one_account_half_an_hour_between_two(self):
        # Leo 2026-10-29 「不同帳號 也要間隔至少半小時」.
        a = Slot(KIND_TIME, 21, 0, [0], account="1")
        self.assertTrue(a.clashes_with(Slot(KIND_TIME, 21, 30, [0], account="1"), current="1"))
        self.assertTrue(a.clashes_with(Slot(KIND_TIME, 21, 15, [0], account="2"), current="1"))
        self.assertFalse(a.clashes_with(Slot(KIND_TIME, 21, 30, [0], account="2"), current="1"))
        # "" is the current 帳號.
        self.assertTrue(a.clashes_with(Slot(KIND_TIME, 21, 30, [0]), current="1"))
        self.assertFalse(a.clashes_with(Slot(KIND_TIME, 21, 30, [0]), current="2"))
        with mock.patch.object(ss, "_current_account", lambda: "1"):
            self.assertEqual(["", ""], ss.slot_problems([a, Slot(KIND_TIME, 21, 30, [0], account="2")]))
            problems = ss.slot_problems([a, Slot(KIND_TIME, 21, 0, [0], account="2")])
            self.assertIn("半小时", problems[0])
            problems = ss.slot_problems([a, Slot(KIND_TIME, 21, 45, [0], account="1")])
            self.assertIn("1 小时", problems[0])

    def test_every_account_at_one_time_runs(self):
        settings = Settings(True, True, [
            Slot(KIND_TIME, 21, 0, account="1", tasks=["领取邮件"]),
            Slot(KIND_TIME, 21, 0, account="2"),
            Slot(KIND_TIME, 8, 0, account="3"),
        ])
        moment = datetime(2026, 10, 22, 21, 1, tzinfo=TAIPEI)
        jobs = ss.jobs_at(settings, moment)
        self.assertEqual(["1", "2"], [job["account"] for job in jobs])
        self.assertEqual(["领取邮件"], jobs[0]["tasks"])
        self.assertIsNone(jobs[1]["tasks"])
        self.assertEqual("1", ss.account_at(settings, moment))


class SlotTasksTest(unittest.TestCase):
    """Leo 2026-10-29 「也要選擇該時段進行的任務」: a slot's own items."""

    def test_saved_and_none_means_the_accounts_ticks(self):
        settings = Settings(True, True, [
            Slot(KIND_TIME, 8, 0, tasks=["领取邮件", "快速狩猎"]),
            Slot(KIND_TIME, 21, 0),
        ])
        again = Settings.from_json(settings.to_json())
        self.assertEqual(["领取邮件", "快速狩猎"], again.slots[0].tasks)
        self.assertIsNone(again.slots[1].tasks)
        self.assertNotIn("tasks", again.slots[1].to_json())
        moment = datetime(2026, 10, 22, 8, 1, tzinfo=TAIPEI)
        self.assertEqual(["领取邮件", "快速狩猎"], ss.tasks_at(again, moment))
        self.assertIsNone(ss.tasks_at(again, moment.replace(hour=21, minute=5)))

    def test_item_settings_are_saved_per_slot(self):
        settings = Settings(True, True, [
            Slot(KIND_TIME, 8, 0, settings={"镜中之战": {"竞技场战斗倍数": 2}}),
            Slot(KIND_TIME, 21, 0),
        ])
        again = Settings.from_json(settings.to_json())
        self.assertEqual({"镜中之战": {"竞技场战斗倍数": 2}}, again.slots[0].settings)
        self.assertEqual({}, again.slots[1].settings)
        self.assertNotIn("settings", again.slots[1].to_json())
        moment = datetime(2026, 10, 22, 8, 1, tzinfo=TAIPEI)
        self.assertEqual({"镜中之战": {"竞技场战斗倍数": 2}}, ss.item_settings_at(again, moment))
        self.addCleanup(ss.mark_run_pending, False)
        ss.mark_run_pending(settings={"镜中之战": {"竞技场战斗倍数": 2}})
        self.assertEqual({"镜中之战": {"竞技场战斗倍数": 2}}, ss.take_run_settings())
        self.assertEqual({}, ss.take_run_settings())

    def test_handed_to_the_run_once(self):
        self.addCleanup(ss.mark_run_pending, False)
        ss.mark_run_pending(tasks=["领取邮件"])
        self.assertEqual(["领取邮件"], ss.take_run_tasks())
        self.assertIsNone(ss.take_run_tasks())
        ss.mark_run_pending(tasks=["领取邮件"])
        ss.mark_run_pending(False)  # the start failed: nothing is left for a later run
        self.assertIsNone(ss.take_run_tasks())


class TaskXmlTest(unittest.TestCase):
    def xml(self, settings):
        return ss.task_xml(
            settings,
            ("C:\\yes\\pythonw.exe", '"C:\\yes\\main.py" --scheduled-start', "C:\\yes"),
            "PC\\leo",
            datetime(2026, 10, 22, 9, 0, tzinfo=TAIPEI),
        )

    def test_one_trigger_per_slot(self):
        xml = self.xml(Settings(True, True, [Slot(KIND_RESET), Slot(KIND_TIME, 12, 30, [5, 6])]))
        self.assertEqual(xml.count("<CalendarTrigger>"), 2)
        self.assertIn("<StartBoundary>2026-10-22T08:05:00+08:00</StartBoundary>", xml)
        self.assertIn("<StartBoundary>2026-10-22T12:30:00</StartBoundary>", xml)
        self.assertIn("<Saturday /><Sunday />", xml)

    def test_wakes_runs_elevated_and_never_stops_the_tool(self):
        xml = self.xml(Settings(True, True, [Slot(KIND_RESET)]))
        self.assertIn("<WakeToRun>true</WakeToRun>", xml)
        self.assertIn("<RunLevel>HighestAvailable</RunLevel>", xml)
        self.assertIn("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", xml)
        self.assertIn("<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>", xml)
        self.assertIn("&quot;C:\\yes\\main.py&quot; --scheduled-start", xml.replace('"', "&quot;"))
        self.assertIn("<WakeToRun>false</WakeToRun>", self.xml(Settings(True, False, [Slot(KIND_RESET)])))

    def test_task_name_per_folder(self):
        self.assertNotEqual(ss.task_name("C:\\a"), ss.task_name("C:\\b"))
        self.assertTrue(ss.task_name("C:\\a").startswith("\\YES-BD2\\"))


class ApplyTest(unittest.TestCase):
    def test_on_creates_the_task(self):
        calls = []
        ss.apply(Settings(True, True, [Slot(KIND_RESET)]),
                 run=lambda args, **kw: calls.append(args) or _done())
        self.assertEqual(calls[0][:2], ["schtasks", "/Create"])
        self.assertIn("/F", calls[0])

    def test_off_deletes_the_task(self):
        calls = []
        ss.apply(Settings(False, True, [Slot(KIND_RESET)]),
                 run=lambda args, **kw: calls.append(args) or _done())
        self.assertEqual([c[1] for c in calls], ["/Query", "/Delete"])

    def test_off_without_a_task_is_fine(self):
        calls = []
        ss.apply(Settings(False), run=lambda args, **kw: calls.append(args) or _done(1))
        self.assertEqual([c[1] for c in calls], ["/Query"])

    def test_refused_says_why(self):
        def run(args, **kw):
            return subprocess.CompletedProcess(args, 1, "", "ERROR: Access is denied.")

        with self.assertRaises(ss.TaskError) as caught:
            ss.apply(Settings(True, True, [Slot(KIND_RESET)]), run=run)
        self.assertIn("Access is denied", str(caught.exception))

    def test_missing_schtasks(self):
        def run(args, **kw):
            raise FileNotFoundError("schtasks")

        with self.assertRaises(ss.TaskError):
            ss.apply(Settings(True, True, [Slot(KIND_RESET)]), run=run)


class WakeTimerTest(unittest.TestCase):
    QUERY = (
        "    电源设置 GUID: bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d  (允许使用唤醒定时器)\n"
        "      可能的设置索引: 000\n      可能的设置索引: 001\n      可能的设置索引: 002\n"
        "    当前交流电源设置索引: 0x{ac:08x}\n    当前直流电源设置索引: 0x00000001\n"
    )

    def test_reads_the_plugged_in_value(self):
        self.assertEqual(ss.wake_timer_index(self.QUERY.format(ac=2)), 2)
        self.assertIsNone(ss.wake_timer_index("nothing"))

    def test_on_already(self):
        calls = []
        result = ss.ensure_wake_timers(
            run=lambda args, **kw: calls.append(args) or _done(0, self.QUERY.format(ac=1))
        )
        self.assertTrue(result)
        self.assertEqual(len(calls), 1)

    def test_turned_on_when_off(self):
        calls = []
        result = ss.ensure_wake_timers(
            run=lambda args, **kw: calls.append(args) or _done(0, self.QUERY.format(ac=0))
        )
        self.assertTrue(result)
        self.assertEqual([c[1] for c in calls],
                         ["/query", "/setacvalueindex", "/setdcvalueindex", "/setactive"])

    def test_refused(self):
        def run(args, **kw):
            return _done(0, self.QUERY.format(ac=0)) if args[1] == "/query" else _done(1)

        self.assertFalse(ss.ensure_wake_timers(run=run))


class FlagTest(unittest.TestCase):
    def test_flag_taken_off(self):
        argv = ["main.py", ss.FLAG]
        self.assertTrue(ss.take_flag(argv))
        self.assertEqual(argv, ["main.py"])
        self.assertFalse(ss.take_flag(argv))


class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from src.tasks.DailyBatchTask import CLOSE_GAME_KEY
        from src.ui.shell import data, schedule_ui

        self.ui = schedule_ui
        self.config = {CLOSE_GAME_KEY: False}
        batch = SimpleNamespace(
            name=data.DAILY_BATCH, child_tasks=[], config=self.config, info={},
            batch_label="一键完成日常",
        )
        patches = [
            mock.patch.object(data, "task_by_name", lambda name: batch),
            mock.patch.object(
                schedule_ui, "_settings", Settings(True, True, [Slot(KIND_TIME, 8, 15)])
            ),
            mock.patch.object(schedule_ui, "problem", ""),
            mock.patch.object(ss, "save"),
            mock.patch.object(ss, "ensure_wake_timers", return_value=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_master_switch_off_removes_everything(self):
        with mock.patch.object(ss, "apply") as apply:
            self.assertEqual(self.ui.set_enabled(False), "")
        self.assertFalse(apply.call_args[0][0].enabled)
        self.assertFalse(self.ui.settings().enabled)

    def test_refused_keeps_the_old_settings(self):
        with mock.patch.object(ss, "apply", side_effect=ss.TaskError("denied")):
            why = self.ui.set_enabled(False)
        self.assertIn("denied", why)
        self.assertTrue(self.ui.settings().enabled)
        ss.save.assert_not_called()

    def _editing(self, change):
        from src.ui.shell import schedule_week

        def run(editor):
            return change(editor)

        return mock.patch.object(schedule_week.SlotEditor, "exec", run)

    def test_dialog_adds_and_deletes_slots(self):
        dialog = self.ui.ScheduleDialog(None)
        self.addCleanup(dialog.close)
        with self._editing(lambda editor: True):
            dialog._add_now()
        self.assertEqual(len(dialog.working.slots), 2)
        # A free time, not a copy (Leo 2026-10-22 「時間不可以衝突吧」).
        self.assertEqual((21, 0), (dialog.working.slots[1].hour, dialog.working.slots[1].minute))

        def delete(editor):
            editor._delete()
            return True

        with self._editing(delete):
            dialog._edit(dialog.working.slots[0])
        self.assertEqual([(s.hour, s.minute) for s in dialog.working.slots], [(21, 0)])
        with self._editing(lambda editor: True):
            for _ in range(10):
                dialog._add_now()
        self.assertEqual(len(dialog.working.slots), ss.MAX_SLOTS)
        self.assertEqual(5, ss.MAX_SLOTS)
        self.assertFalse(dialog.add_button.isEnabled())
        # Every added slot can be saved as it is.
        self.assertEqual([""] * 5, ss.slot_problems(dialog.working.slots))
        self.assertTrue(dialog.save_button.isEnabled())
        # Nothing is kept before 保存.
        self.assertEqual(len(self.ui.settings().slots), 1)

    def test_clashing_slots_are_marked_and_block_saving(self):
        dialog = self.ui.ScheduleDialog(None)
        self.addCleanup(dialog.close)
        dialog.working.slots.append(Slot(KIND_TIME, 8, 0))  # 15 min from 08:15
        dialog._fill()
        self.assertTrue(all(block.problem for block in dialog.week.blocks))
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.working.slots[1].hour = 10  # 10:00: more than an hour
        dialog._fill()
        self.assertFalse(any(block.problem for block in dialog.week.blocks))
        self.assertTrue(dialog.save_button.isEnabled())
        dialog.working.slots[1].days = []
        dialog._fill()
        self.assertIn("星期", dialog.problem.text())
        self.assertFalse(dialog.save_button.isEnabled())
        # With 定时启动 off the slots do nothing, so it saves.
        dialog.master.setChecked(False)
        self.assertTrue(dialog.save_button.isEnabled())

    def test_dialog_save_writes_task_and_options(self):
        from src.tasks.DailyBatchTask import CLOSE_GAME_KEY

        dialog = self.ui.ScheduleDialog(None)
        self.addCleanup(dialog.close)
        # Leo 2026-10-22: a scheduled run closes the game by default.
        self.assertTrue(dialog.close_game.isChecked())

        def weekdays(editor):
            for day, chip in enumerate(editor.days):
                chip.setChecked(day < 6)
            return True

        with self._editing(weekdays):
            dialog._add(0, 21)
        dialog.shutdown.setChecked(True)
        with mock.patch.object(ss, "apply") as apply:
            dialog._save()
        saved = apply.call_args[0][0]
        self.assertEqual(saved.slots[1].days, [0, 1, 2, 3, 4, 5])
        self.assertTrue(saved.close_game and saved.shutdown)
        # 一键日常's own setting (manual runs) is left as it was.
        self.assertFalse(self.config[CLOSE_GAME_KEY])
        self.assertEqual(len(self.ui.settings().slots), 2)

    def test_master_off_in_dialog_greys_the_slots(self):
        dialog = self.ui.ScheduleDialog(None)
        self.addCleanup(dialog.close)
        dialog.master.setChecked(False)
        self.assertFalse(dialog.body.isEnabled())

    def test_next_text(self):
        now = datetime(2026, 10, 22, 7, 0, tzinfo=TAIPEI)
        self.assertEqual(self.ui.next_text(now), ("08:15", "下次 · 今天"))
        self.ui._settings.enabled = False
        self.assertEqual(self.ui.next_text(now), ("", ""))


class FailureReportTest(UiTest):
    """A scheduled start that never became a run still ends in a report
    (Leo 2026-10-22: 「有問題也要說」; the 跑完通知 sends on run_report.finish)."""

    def setUp(self):
        super().setUp()
        from src.tasks import run_report

        self.run_report = run_report
        folder = tempfile.mkdtemp()
        run_report.set_report_file(os.path.join(folder, "reports.json"))
        self.addCleanup(run_report.set_report_file, None)
        self.finished = []
        real_finish = run_report.finish
        patch = mock.patch.object(
            run_report, "finish", lambda ended: self.finished.append(real_finish(ended))
        )
        patch.start()
        self.addCleanup(patch.stop)
        ss.mark_run_pending(False)

    def test_lock_screen(self):
        with mock.patch.object(ss, "screen_locked", return_value=True):
            self.assertFalse(self.ui.before_start())
        report = self.finished[-1]
        self.assertEqual(report["ended"], self.run_report.ENDED_ERROR)
        self.assertEqual(report["label"], "一键完成日常")
        self.assertEqual(report["rows"], [])
        self.assertTrue(report["scheduled"])
        self.assertIn("锁屏", report["notice"])
        self.assertFalse(ss.take_run_pending())

    def test_unlocked_marks_the_run(self):
        with mock.patch.object(ss, "screen_locked", return_value=False):
            self.assertTrue(self.ui.before_start())
        self.assertTrue(ss.take_run_pending())
        self.assertFalse(ss.take_run_pending())
        self.assertEqual(self.finished, [])

    def test_not_started(self):
        ss.mark_run_pending()
        self.ui.after_start(False)
        self.assertIn("没能开始", self.finished[-1]["notice"])
        self.assertFalse(ss.take_run_pending())

    def test_game_never_logged_in(self):
        from src.ui.shell import data

        with mock.patch.object(self.ui.QTimer, "singleShot"):
            self.ui.after_start(True)
        with mock.patch.object(data, "busy", return_value=False):
            self.ui._check_begun()
        self.assertIn("没登录进去", self.finished[-1]["notice"])

    def test_run_began_no_report(self):
        from src.ui.shell import data

        with mock.patch.object(self.ui.QTimer, "singleShot"):
            self.ui.after_start(True)
        self.run_report.begin("一键完成日常", "x", [("a", "a")])
        self.run_report.finish(self.run_report.ENDED_DONE)
        count = len(self.finished)
        with mock.patch.object(data, "busy", return_value=False):
            self.ui._check_begun()
        self.assertEqual(len(self.finished), count)

    def test_still_busy_checks_again(self):
        from src.ui.shell import data

        with mock.patch.object(self.ui.QTimer, "singleShot"):
            self.ui.after_start(True)
        with mock.patch.object(data, "busy", return_value=True), \
                mock.patch.object(self.ui.QTimer, "singleShot") as later:
            self.ui._check_begun()
        later.assert_called_once()
        self.assertEqual(self.finished, [])

    def test_no_report_over_a_running_one(self):
        self.run_report.begin("一键完成日常", "x", [("a", "a")])
        self.addCleanup(self.run_report.finish, self.run_report.ENDED_DONE)
        self.ui.report_failure("x")
        self.assertEqual(self.finished, [])


class ScheduledOptionTest(unittest.TestCase):
    def test_only_for_the_scheduled_run(self):
        from src.tasks.DailyBatchTask import DailyBatchTask

        task = SimpleNamespace(_scheduled_run=False)
        settings = Settings(True, True, [Slot(KIND_RESET)], close_game=True, shutdown=False)
        with mock.patch.object(ss, "load", return_value=settings):
            self.assertFalse(DailyBatchTask._scheduled_option(task, "close_game"))
            task._scheduled_run = True
            self.assertTrue(DailyBatchTask._scheduled_option(task, "close_game"))
            self.assertFalse(DailyBatchTask._scheduled_option(task, "shutdown"))


class AutorunTest(unittest.TestCase):
    def test_scheduled_start_ignores_the_home_box(self):
        from src.ui.shell import autorun

        with mock.patch.object(autorun, "enabled", return_value=False), \
                mock.patch.object(autorun.data, "executor", return_value=object()), \
                mock.patch.object(autorun.data, "busy", return_value=False), \
                mock.patch.object(autorun, "remaining", return_value=[1]):
            self.assertEqual(autorun.should_start(False), "off")
            self.assertIsNone(autorun.should_start(False, scheduled=True))
            self.assertEqual(autorun.should_start(True, scheduled=True), "in the clone")


if __name__ == "__main__":
    unittest.main()


class SlotRulesTest(unittest.TestCase):
    """Leo 2026-10-22: no reset slot, quarters, at most 5, an hour apart."""

    def test_minutes_go_to_their_quarter(self):
        self.assertEqual([0, 0, 15, 45, 45], [ss.snap_minute(m) for m in (0, 7, 8, 50, 59)])
        settings = Settings.from_json({"slots": [{"kind": "time", "time": "21:07", "days": [0]}]})
        self.assertEqual(0, settings.slots[0].minute)
        self.assertTrue(settings.migrated)

    def test_a_saved_reset_slot_is_dropped(self):
        settings = Settings.from_json(
            {
                "enabled": True,
                "slots": [
                    {"kind": "reset", "on": True},
                    {"kind": "time", "time": "21:00", "days": [0, 1], "on": True},
                ],
            }
        )
        self.assertEqual([(21, 0)], [(s.hour, s.minute) for s in settings.slots])
        self.assertTrue(settings.migrated)
        clean = Settings.from_json(Settings(True, True, [Slot(KIND_TIME, 21, 0, [0, 1])]).to_json())
        self.assertFalse(clean.migrated)

    def test_at_most_five_are_kept(self):
        stored = [Slot(KIND_TIME, hour, 0).to_json() for hour in (1, 4, 7, 10, 13, 16)]
        settings = Settings.from_json({"slots": stored})
        self.assertEqual(5, len(settings.slots))
        self.assertTrue(settings.migrated)

    def test_slots_an_hour_apart_or_more(self):
        monday = Slot(KIND_TIME, 21, 0, [0])
        self.assertTrue(monday.clashes_with(Slot(KIND_TIME, 21, 0, [0])))
        self.assertTrue(monday.clashes_with(Slot(KIND_TIME, 21, 45, [0, 3])))
        self.assertFalse(monday.clashes_with(Slot(KIND_TIME, 22, 0, [0])))
        self.assertFalse(monday.clashes_with(Slot(KIND_TIME, 21, 0, [1])))
        self.assertFalse(monday.clashes_with(Slot(KIND_TIME, 21, 0, [0], on=False)))
        # Over midnight: Monday 23:30 and Tuesday 00:15; Sunday 23:45 and Monday 00:30.
        self.assertTrue(Slot(KIND_TIME, 23, 30, [0]).clashes_with(Slot(KIND_TIME, 0, 15, [1])))
        self.assertTrue(Slot(KIND_TIME, 23, 45, [6]).clashes_with(Slot(KIND_TIME, 0, 30, [0])))

    def test_problems_name_the_slot(self):
        slots = [
            Slot(KIND_TIME, 9, 0, []),
            Slot(KIND_TIME, 21, 0),
            Slot(KIND_TIME, 21, 30),
            Slot(KIND_TIME, 7, 0),
        ]
        found = ss.slot_problems(slots)
        self.assertIn("星期", found[0])
        self.assertIn("1 小时", found[1])
        self.assertIn("1 小时", found[2])
        self.assertEqual("", found[3])

    def test_a_new_slot_gets_a_free_hour(self):
        self.assertEqual((21, 0), ss.free_time([]))
        self.assertEqual((22, 0), ss.free_time([Slot(KIND_TIME, 21, 0)]))
        # 22:00 and 23:00 are under an hour from 21:00 / 22:15.
        self.assertEqual((0, 0), ss.free_time([Slot(KIND_TIME, 21, 0), Slot(KIND_TIME, 22, 15)]))
        # Taken only on Monday still leaves no room on Monday for an everyday slot.
        self.assertEqual((22, 0), ss.free_time([Slot(KIND_TIME, 21, 0, [0])]))

    def test_old_settings_are_written_again_when_the_tool_opens(self):
        from PySide6.QtWidgets import QApplication

        from src.ui.shell import schedule_ui

        QApplication.instance() or QApplication([])
        old = Settings.from_json({"enabled": True, "slots": [{"kind": "reset", "on": True}]})
        with (
            mock.patch.object(schedule_ui, "_settings", old),
            mock.patch.object(schedule_ui, "store", return_value="") as store,
        ):
            schedule_ui.start_watch(None)
        self.assertEqual([], store.call_args[0][0].slots)
        with (
            mock.patch.object(schedule_ui, "_settings", Settings()),
            mock.patch.object(schedule_ui, "store") as store,
        ):
            schedule_ui.start_watch(None)
        store.assert_not_called()
