import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.config import config
from src.tasks import run_report, scheduler, weekly_ticks
from src.tasks.DailyBatchTask import (
    RUN_MODE_ALL,
    RUN_MODE_INCOMPLETE,
    SHUTDOWN_COUNTDOWN_SECONDS,
    DailyBatchChild,
    DailyBatchTask,
)
from src.tasks.MapCollectionTask import MapCollectionTask
from src.tasks.run_history import RunHistoryStore, set_default_store
from src.tasks.task_notifications import log_task_completion

_report_dir = None
_TICKS = mock.patch.object(
    weekly_ticks, "STATE_FILE", Path(tempfile.mkdtemp()) / "weekly_ticks.json"
)


def setUpModule():
    # Batches save a run report; keep it out of the real configs folder.
    global _report_dir
    _report_dir = tempfile.TemporaryDirectory()
    run_report.set_report_file(f"{_report_dir.name}/run_reports.json")
    # 周常 ticks too.
    _TICKS.start()


def tearDownModule():
    run_report.set_report_file(None)
    _TICKS.stop()
    _report_dir.cleanup()


class _ChildTask:
    def __init__(self, name, calls, result=True):
        self.name = name
        self.calls = calls
        self.result = result
        self.config = {"启用": False, "保留配置": 1}

    def info_clear(self):
        pass

    def run(self):
        self.calls.append((self.name, self.config.get("启用")))
        return self.result


class DailyBatchTaskTest(unittest.TestCase):
    def make_task(self, children, child_specs, task_config):
        task = object.__new__(DailyBatchTask)
        task.child_tasks = child_specs
        task.config = task_config
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_args, **_kwargs: None
        task.log_warning = lambda *_args, **_kwargs: None
        task.log_error = lambda *_args, **_kwargs: None
        resets = []
        task._executor = SimpleNamespace(
            get_task_by_class=lambda cls: children.get(cls),
            reset_scene=lambda **kwargs: resets.append(kwargs),
        )
        return task, resets

    def test_registered_before_the_other_daily_tasks(self):
        self.assertEqual(
            ["src.tasks.DailyBatchTask", "DailyBatchTask"],
            config["onetime_tasks"][0],
        )

    def test_config_lists_every_child_including_weekly_map_collection(self):
        executor = SimpleNamespace(scene=None)
        task = DailyBatchTask(executor, SimpleNamespace())
        expected = [
            "公会、小屋、酒馆",
            "领取常客圣石",
            "快速狩猎",
            "免费抽抽乐",
            "爛装强化分解",
            "每日精炼一次",
            "广场女神像",
            "自动PVP",
            "跑商",
            "活动每日战斗",
            # Leo 2026-10-09: the 周常 run in 一键日常, skipped once done this week.
            "浏览街机菜单",
            "小屋增加人气",
            "制作装备",
            "末日之书",
            "领取任务奖励",
            "领取通行证",
            "领取邮件",
            # Leo 2026-10-03: the red-badged 活动 pages, after the mail.
            "领取活动奖励",
            # User 2026-09-28: collection runs daily until the week is done;
            # 2026-10-03: as the very last item, after the mail.
            "每周跑图",
        ]
        self.assertEqual(expected, task.config_type["启用"]["sub_configs"][True])
        self.assertTrue(all(task.default_config[key] for key in expected))

    def test_weekly_map_collection_card_is_shown_in_the_daily_group(self):
        executor = SimpleNamespace(scene=None)
        for debug in (False, True):
            with self.subTest(debug=debug):
                task = MapCollectionTask(executor, SimpleNamespace(debug=debug))
                self.assertTrue(task.visible)
                self.assertEqual("日常/周常", task.group_name)
        self.assertIn(
            ["src.tasks.MapCollectionTask", "MapCollectionTask"],
            config["onetime_tasks"],
        )

    def test_runs_enabled_children_in_order_and_restores_their_configs(self):
        class First:
            pass

        class Second:
            pass

        calls = []
        first = _ChildTask("first", calls)
        second = _ChildTask("second", calls)
        original_first_config = first.config
        original_second_config = second.config
        specs = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("第二项", Second),
        )
        task, resets = self.make_task(
            {First: first, Second: second},
            specs,
            {"启用": True, "第一项": True, "第二项": True},
        )

        self.assertTrue(DailyBatchTask.run(task))
        self.assertEqual([("first", True), ("second", True)], calls)
        self.assertIs(original_first_config, first.config)
        self.assertIs(original_second_config, second.config)
        self.assertEqual(2, len(resets))

    def test_progress_is_published_after_each_child(self):
        class First:
            pass

        class Second:
            pass

        first = _ChildTask("first", [])
        second = _ChildTask("second", [])
        specs = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("第二项", Second),
        )
        task, _resets = self.make_task(
            {First: first, Second: second},
            specs,
            {"启用": True, "第一项": True, "第二项": True},
        )
        observed = []
        original_run = second.run

        def second_run():
            # By the time the second child runs, the first must already be
            # published so the run panel can paint its live segments.
            observed.append(task.info.get("完成"))
            return original_run()

        second.run = second_run

        self.assertTrue(DailyBatchTask.run(task))
        self.assertEqual(["第一项"], observed)
        self.assertEqual("第一项、第二项", task.info.get("完成"))

    def test_failure_stops_later_children_and_disabled_switch_is_skipped(self):
        class Skipped:
            pass

        class Failed:
            pass

        class Later:
            pass

        calls = []
        skipped = _ChildTask("skipped", calls)
        failed = _ChildTask("failed", calls, result=False)
        later = _ChildTask("later", calls)
        specs = (
            DailyBatchChild("关闭项", Skipped),
            DailyBatchChild("失败项", Failed),
            DailyBatchChild("后续项", Later),
        )
        task, _resets = self.make_task(
            {Skipped: skipped, Failed: failed, Later: later},
            specs,
            {"启用": True, "关闭项": False, "失败项": True, "后续项": True},
        )

        self.assertFalse(DailyBatchTask.run(task))
        self.assertEqual([("failed", True)], calls)

    def test_children_cut_off_by_an_abort_wait_out_the_failure_backoff(self):
        # Without this the auto-scheduler relaunched the aborted batch 8 s
        # later onto the same stuck screen (review 2026-09-26).
        class Failed:
            pass

        class Later:
            pass

        calls = []
        task, _resets = self.make_task(
            {Failed: _ChildTask("failed", calls, result=False), Later: _ChildTask("later", calls)},
            (DailyBatchChild("失败项", Failed), DailyBatchChild("后续项", Later)),
            {"启用": True, "失败项": True, "后续项": True, "失败后继续": False},
        )
        schedule = mock.Mock()
        with mock.patch("src.tasks.scheduler.default_store", return_value=schedule):
            self.assertFalse(DailyBatchTask.run(task))
        self.assertEqual([("failed", True)], calls)
        schedule.delay_after_run.assert_any_call("later", ok=False)
        self.assertIn("失败项", task._child_finished)

    def test_release_after_login_keeps_the_remaining_only_mode(self):
        task = object.__new__(DailyBatchTask)
        task._start_after_login = True
        task.log_info = lambda *_a, **_k: None
        task.request_run_mode(RUN_MODE_INCOMPLETE)
        task._requested_run_mode_deadline = 0.0  # login took longer than the TTL
        executor = SimpleNamespace(
            get_task_by_class=lambda cls: task, enqueue_onetime_task=lambda t: True
        )
        self.assertTrue(DailyBatchTask.release_after_login(executor))
        self.assertEqual(RUN_MODE_INCOMPLETE, DailyBatchTask._take_run_mode(task, None))

    def _failing_middle_batch(self, batch_config):
        class Failed:
            pass

        class Later:
            pass

        calls = []
        specs = (DailyBatchChild("失败项", Failed), DailyBatchChild("后续项", Later))
        task, _resets = self.make_task(
            {Failed: _ChildTask("failed", calls, result=False), Later: _ChildTask("later", calls)},
            specs,
            {"启用": True, "失败项": True, "后续项": True, **batch_config},
        )
        return task, calls

    def test_failure_continues_after_recovering_home(self):
        task, calls = self._failing_middle_batch({})
        with mock.patch.object(DailyBatchTask, "_recover_home", return_value=True) as recover:
            self.assertFalse(DailyBatchTask.run(task))
        recover.assert_called_once()
        self.assertEqual([("failed", True), ("later", True)], calls)
        self.assertEqual("失败项", task.info.get("失败"))
        self.assertEqual("后续项", task.info.get("完成"))
        # It ran to the end: not "中止" (users read that as broken).
        self.assertIn("完成（1项失败）", task.info.get("状态"))

    def test_stop_keeps_children_done_before_it_so_continue_skips_them(self):
        # Leo 2026-10-06: stopped during 抽抽乐, 继续 must not redo the
        # children already done.  ok-script sends no task_done on Stop, so
        # the batch records them itself.
        from ok.task.exceptions import TaskDisabledException

        class First:
            pass

        class Gacha:
            pass

        class Later:
            pass

        class _StoppedChild(_ChildTask):
            def run(self):
                super().run()
                raise TaskDisabledException()

        calls = []
        stopped = _StoppedChild("gacha", calls)
        task, _resets = self.make_task(
            {First: _ChildTask("first", calls), Gacha: stopped, Later: _ChildTask("later", calls)},
            (
                DailyBatchChild("前面", First),
                DailyBatchChild("抽抽乐", Gacha),
                DailyBatchChild("后面", Later),
            ),
            {"启用": True, "前面": True, "抽抽乐": True, "后面": True},
        )
        schedule = mock.Mock()
        schedule.is_due.return_value = True
        with tempfile.TemporaryDirectory() as folder:
            store = RunHistoryStore(f"{folder}/history.json")
            set_default_store(store)
            try:
                with mock.patch("src.tasks.scheduler.default_store", return_value=schedule):
                    with self.assertRaises(TaskDisabledException):
                        DailyBatchTask.run(task, RUN_MODE_ALL)
                    reloaded = RunHistoryStore(store.path)
                    self.assertTrue(reloaded.is_completed_today("first"))
                    self.assertIsNone(reloaded.last_run("gacha"))
                    self.assertIsNone(reloaded.last_run("later"))
                    # The batch itself did not finish.
                    self.assertIsNone(reloaded.last_run("一键完成日常"))
                    saved = run_report.load("一键完成日常")
                    self.assertEqual(run_report.ENDED_STOPPED, saved["ended"])

                    calls.clear()
                    stopped.run = lambda: _ChildTask.run(stopped)
                    self.assertTrue(DailyBatchTask.run(task, RUN_MODE_INCOMPLETE))
            finally:
                set_default_store(None)
        self.assertEqual([("gacha", True), ("later", True)], calls)

    def test_weekly_batch_skips_children_done_this_week(self):
        from src.tasks.DailyBatchTask import WeeklyBatchTask

        class Done:
            pass

        class Pending:
            pass

        calls = []
        done = _ChildTask("done", calls)
        pending = _ChildTask("pending", calls)
        task, _resets = self.make_task(
            {Done: done, Pending: pending},
            (DailyBatchChild("已完成", Done), DailyBatchChild("未完成", Pending)),
            {"启用": True, "已完成": True, "未完成": True},
        )
        task.__class__ = WeeklyBatchTask
        history = mock.Mock()
        history.is_completed_this_week.side_effect = lambda name: name == "done"
        history.is_completed_today.return_value = False
        schedule = mock.Mock()
        schedule.is_due.return_value = True
        with (
            mock.patch("src.tasks.run_history.default_store", return_value=history),
            mock.patch("src.tasks.scheduler.default_store", return_value=schedule),
        ):
            self.assertTrue(WeeklyBatchTask.run(task, RUN_MODE_INCOMPLETE))
        self.assertEqual([("pending", True)], calls)
        history.is_completed_today.assert_not_called()
        self.assertEqual("一键完成周常", WeeklyBatchTask.batch_label)
        self.assertNotIsInstance(task, DailyBatchTask)

    def test_weekly_full_run_redoes_children_done_this_week(self):
        # User 2026-09-27: clicking again means doing it again.
        from src.tasks.DailyBatchTask import RUN_MODE_ALL, WeeklyBatchTask

        class Done:
            pass

        class Pending:
            pass

        calls = []
        task, _resets = self.make_task(
            {Done: _ChildTask("done", calls), Pending: _ChildTask("pending", calls)},
            (DailyBatchChild("已完成", Done), DailyBatchChild("未完成", Pending)),
            {"启用": True, "已完成": True, "未完成": True},
        )
        task.__class__ = WeeklyBatchTask
        history = mock.Mock()
        history.is_completed_this_week.side_effect = lambda name: name == "done"
        with (
            mock.patch("src.tasks.run_history.default_store", return_value=history),
            mock.patch("src.tasks.scheduler.default_store"),
        ):
            self.assertTrue(WeeklyBatchTask.run(task, RUN_MODE_ALL))
        self.assertEqual([("done", True), ("pending", True)], calls)

    def _weekly_batch(self, calls, ticks):
        class Daily:
            pass

        class WeekDone:
            pass

        class WeekPending:
            pass

        return self.make_task(
            {
                Daily: _ChildTask("daily", calls),
                WeekDone: _ChildTask("week-done", calls),
                WeekPending: _ChildTask("week-pending", calls),
            },
            (
                DailyBatchChild("日常", Daily),
                DailyBatchChild("做完的周常", WeekDone, weekly=True),
                DailyBatchChild("没做的周常", WeekPending, weekly=True),
            ),
            {"启用": True, "日常": True, **ticks},
        )[0]

    def _run_with_week_done(self, task, done_at=None):
        from src.tasks.run_history import week_start_ts

        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunHistoryStore(f"{temp_dir}/history.json")
            store.record_task_done(
                SimpleNamespace(name="week-done", start_time=0, info={"状态": "完成。"}),
                finished=done_at or week_start_ts() + 1,
            )
            set_default_store(store)
            try:
                with mock.patch("src.tasks.scheduler.default_store"):
                    self.assertTrue(DailyBatchTask.run(task, RUN_MODE_ALL))
            finally:
                set_default_store(None)

    def test_weekly_child_done_this_week_loses_its_tick(self):
        # Leo 2026-10-09: 一键日常 runs the ticked 周常; one done this week has
        # its tick taken away (so it is not run), and one that runs now too.
        weekly_ticks.STATE_FILE.unlink(missing_ok=True)
        calls = []
        task = self._weekly_batch(calls, {"做完的周常": True, "没做的周常": True})
        self._run_with_week_done(task)
        self.assertEqual([("daily", True), ("week-pending", True)], calls)
        self.assertIs(False, task.config["做完的周常"])
        self.assertIs(False, task.config["没做的周常"])
        self.assertIs(True, task.config["日常"])

    def test_weekly_child_ticked_again_by_the_player_runs_again(self):
        # Leo 2026-10-09: ticking it again (to test) runs it again this week.
        weekly_ticks.STATE_FILE.unlink(missing_ok=True)
        calls = []
        task = self._weekly_batch(calls, {"做完的周常": True, "没做的周常": False})
        self._run_with_week_done(task)
        self.assertIs(False, task.config["做完的周常"])
        task.config["做完的周常"] = True
        calls.clear()
        self._run_with_week_done(task)
        self.assertEqual([("daily", True), ("week-done", True)], calls)
        self.assertIs(False, task.config["做完的周常"])
        self.assertIs(False, task.config["没做的周常"])  # the player's own untick stays

    def test_shutdown_counts_weekly_child_done_earlier_this_week(self):
        from src.tasks.run_history import week_start_ts

        class Daily:
            pass

        class Week:
            pass

        task, _resets = self.make_task(
            {Daily: _ChildTask("daily", []), Week: _ChildTask("week", [])},
            (DailyBatchChild("日常", Daily), DailyBatchChild("周常", Week, weekly=True)),
            {"启用": True, "完成日常后自动关机": True, "日常": True, "周常": True},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunHistoryStore(f"{temp_dir}/history.json")
            store.record_task_done(
                SimpleNamespace(name="week", start_time=0, info={"状态": "完成。"}),
                finished=week_start_ts() + 1,
            )
            set_default_store(store)
            try:
                with mock.patch(
                    "src.tasks.DailyBatchTask._schedule_system_shutdown"
                ) as shutdown:
                    self.assertTrue(DailyBatchTask.run(task, RUN_MODE_ALL))
            finally:
                set_default_store(None)
        shutdown.assert_called_once_with(SHUTDOWN_COUNTDOWN_SECONDS)

    def test_weekly_switches_carry_over_from_the_old_weekly_batch(self):
        import json
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "WeeklyBatchTask.json").write_text(
                json.dumps({"末日之书": False, "制作装备": True}), encoding="utf-8"
            )
            with (
                mock.patch(
                    "src.tasks.DailyBatchTask._config_file",
                    side_effect=lambda name: folder / f"{name}.json",
                ),
                mock.patch("ok.util.config.Config.config_folder", temp_dir),
            ):
                task = DailyBatchTask(SimpleNamespace(scene=None), SimpleNamespace())
                task.load_config()
            self.assertFalse(task.config["末日之书"])
            self.assertTrue(task.config["制作装备"])
            self.assertFalse(task.config["打开工具时自动开始"])

    def test_child_lookup_matches_the_exact_class_not_a_subclass(self):
        class Refine:
            pass

        class Junk(Refine):
            pass

        junk, refine = Junk(), Refine()
        task = object.__new__(DailyBatchTask)
        # The subclass is registered first: isinstance would return it.
        task._executor = SimpleNamespace(
            onetime_tasks=[junk, refine], trigger_tasks=[], get_task_by_class=None
        )
        self.assertIs(refine, DailyBatchTask._child_task(task, Refine))
        self.assertIs(junk, DailyBatchTask._child_task(task, Junk))

    def test_failure_stops_when_home_not_recovered_or_switch_off(self):
        task, calls = self._failing_middle_batch({})
        with mock.patch.object(DailyBatchTask, "_recover_home", return_value=False):
            self.assertFalse(DailyBatchTask.run(task))
        self.assertEqual([("failed", True)], calls)

        task, calls = self._failing_middle_batch({"失败后继续": False})
        with mock.patch.object(DailyBatchTask, "_recover_home", return_value=True) as recover:
            self.assertFalse(DailyBatchTask.run(task))
        recover.assert_not_called()
        self.assertEqual([("failed", True)], calls)
        self.assertIn("中止", task.info.get("状态"))

    def test_child_completion_is_silent_and_batch_emits_one_overview(self):
        class NotifyingChild:
            pass

        notifications = []
        child = _ChildTask("child", [])
        child.log_info = lambda message, notify=False: notifications.append(
            ("child", message, notify)
        )

        def run_child():
            log_task_completion(child, "子任务完成。")
            return True

        child.run = run_child
        specs = (DailyBatchChild("子任务", NotifyingChild),)
        task, _resets = self.make_task(
            {NotifyingChild: child},
            specs,
            {"启用": True, "子任务": True},
        )
        task.log_info = lambda message, notify=False: notifications.append(
            ("batch", message, notify)
        )

        self.assertTrue(DailyBatchTask.run(task))
        self.assertEqual(
            [
                ("batch", "一键完成日常：开始 子任务。", False),
                ("child", "子任务完成。", False),
                ("batch", "一键完成日常：子任务 完成。", False),
                ("batch", "一键完成日常完成：已执行 1 项，跳过 0 项。", True),
            ],
            notifications,
        )
        self.assertFalse(
            hasattr(child, "_completion_notification_suppression_depth")
        )

    def test_incomplete_mode_skips_children_completed_today_without_mutating_config(self):
        class First:
            pass

        class Second:
            pass

        calls = []
        first = _ChildTask("first", calls)
        second = _ChildTask("second", calls)
        specs = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("第二项", Second),
        )
        task, _resets = self.make_task(
            {First: first, Second: second},
            specs,
            {"启用": True, "第一项": True, "第二项": True},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunHistoryStore(f"{temp_dir}/history.json")
            set_default_store(store)
            store.record_task_done(
                SimpleNamespace(
                    name="first",
                    start_time=0,
                    info={"状态": "first 完成。"},
                )
            )
            original_config = task.config
            try:
                self.assertTrue(DailyBatchTask.run(task, RUN_MODE_INCOMPLETE))
            finally:
                set_default_store(None)

        self.assertEqual([("second", True)], calls)
        self.assertIs(original_config, task.config)
        self.assertEqual("第一项", task.info.get("跳过"))

    def test_requested_run_mode_is_transient_and_next_run_defaults_to_all(self):
        class First:
            pass

        class Second:
            pass

        calls = []
        first = _ChildTask("first", calls)
        second = _ChildTask("second", calls)
        specs = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("第二项", Second),
        )
        task, _resets = self.make_task(
            {First: first, Second: second},
            specs,
            {"启用": True, "第一项": True, "第二项": True},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunHistoryStore(f"{temp_dir}/history.json")
            set_default_store(store)
            store.record_task_done(
                SimpleNamespace(
                    name="first",
                    start_time=0,
                    info={"状态": "first 完成。"},
                )
            )
            try:
                task.request_run_mode(RUN_MODE_INCOMPLETE)
                self.assertTrue(DailyBatchTask.run(task))
                self.assertTrue(DailyBatchTask.run(task))
            finally:
                set_default_store(None)

        self.assertEqual(
            [("second", True), ("first", True), ("second", True)],
            calls,
        )

    def test_incomplete_mode_skips_child_in_failure_backoff(self):
        class First:
            pass

        calls = []
        first = _ChildTask("快速狩猎", calls)
        specs = (DailyBatchChild("第一项", First),)
        task, _resets = self.make_task(
            {First: first},
            specs,
            {"启用": True, "第一项": True},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            schedule_store = scheduler.TaskScheduleStore(f"{temp_dir}/schedule.json")
            scheduler.set_default_store(schedule_store)
            # INCOMPLETE 模式会读 run_history 判断“今日已完成”；必须钉住
            # 独立空账本，否则开发机上 configs/task_run_history.json 的真实
            # 记录会把用例变成空跑。
            set_default_store(RunHistoryStore(f"{temp_dir}/history.json"))
            try:
                # 刚失败过：next_run 在未来，处于退避期。
                schedule_store.delay_after_run("快速狩猎", ok=False)
                self.assertTrue(DailyBatchTask.run(task, RUN_MODE_INCOMPLETE))
            finally:
                scheduler.set_default_store(None)
                set_default_store(None)

        self.assertEqual([], calls)
        self.assertEqual("第一项", task.info.get("跳过"))

    def test_incomplete_mode_runs_child_once_backoff_expired(self):
        class First:
            pass

        calls = []
        first = _ChildTask("快速狩猎", calls)
        specs = (DailyBatchChild("第一项", First),)
        task, _resets = self.make_task(
            {First: first},
            specs,
            {"启用": True, "第一项": True},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            schedule_store = scheduler.TaskScheduleStore(f"{temp_dir}/schedule.json")
            scheduler.set_default_store(schedule_store)
            set_default_store(RunHistoryStore(f"{temp_dir}/history.json"))
            try:
                # 退避点已过期（next_run 在过去）→ 视为到期，应执行。
                schedule_store.mark_due_now("快速狩猎", now=time.time() - 3600)
                self.assertTrue(DailyBatchTask.run(task, RUN_MODE_INCOMPLETE))
            finally:
                scheduler.set_default_store(None)
                set_default_store(None)

        self.assertEqual([("快速狩猎", True)], calls)

    def test_requested_run_mode_expires_and_defaults_to_all(self):
        # MEDIUM 回归：「执行剩余」请求的 run_mode 带有效期。启动失败时
        # run() 不执行、请求无法消费，过期作废，避免残留的 INCOMPLETE 被
        # 之后的用户手动点击静默继承。
        class First:
            pass

        first = _ChildTask("快速狩猎", [])
        task, _resets = self.make_task(
            {First: first},
            (DailyBatchChild("第一项", First),),
            {"启用": True, "第一项": True},
        )
        task.request_run_mode(RUN_MODE_INCOMPLETE)
        self.assertEqual(RUN_MODE_INCOMPLETE, task._take_run_mode(None))

        task.request_run_mode(RUN_MODE_INCOMPLETE)
        task._requested_run_mode_deadline = time.monotonic() - 1.0
        self.assertEqual(RUN_MODE_ALL, task._take_run_mode(None))
        # 作废后不留残留。
        self.assertEqual(RUN_MODE_ALL, task._take_run_mode(None))

    def test_run_defers_while_auto_login_pending(self):
        # 回归：手动点开始且游戏冷启动时，onetime 出队优先于登录 trigger
        # 且运行期间 trigger 不执行；立即跑子任务只会在登录页把主页确认
        # 烧超时并中止整批，登录完成后也没有任何东西重新拉起批次。
        from src.tasks.trigger.AutoLoginTask import AutoLoginTask

        class First:
            pass

        calls = []
        first = _ChildTask("first", calls)
        login = SimpleNamespace(_enabled=True, _finished=False)
        task, _resets = self.make_task(
            {First: first, AutoLoginTask: login},
            (DailyBatchChild("第一项", First),),
            {"启用": True, "第一项": True},
        )

        self.assertTrue(DailyBatchTask.run(task))
        self.assertEqual([], calls)
        self.assertTrue(task._start_after_login)
        self.assertIn("等待自动登录", task.info.get("状态"))

    def test_run_proceeds_when_auto_login_settled(self):
        from src.tasks.trigger.AutoLoginTask import AutoLoginTask

        class First:
            pass

        for login in (
            SimpleNamespace(_enabled=True, _finished=True),
            SimpleNamespace(_enabled=False, _finished=False),
            None,
        ):
            with self.subTest(login=login):
                calls = []
                first = _ChildTask("first", calls)
                children = {First: first}
                if login is not None:
                    children[AutoLoginTask] = login
                task, _resets = self.make_task(
                    children,
                    (DailyBatchChild("第一项", First),),
                    {"启用": True, "第一项": True},
                )

                self.assertTrue(DailyBatchTask.run(task))
                self.assertEqual([("first", True)], calls)
                self.assertFalse(getattr(task, "_start_after_login", False))

    def test_deferral_preserves_requested_run_mode(self):
        from src.tasks.trigger.AutoLoginTask import AutoLoginTask

        login = SimpleNamespace(_enabled=True, _finished=False)
        task, _resets = self.make_task(
            {AutoLoginTask: login},
            (),
            {"启用": True},
        )
        task.request_run_mode(RUN_MODE_INCOMPLETE)

        self.assertTrue(DailyBatchTask.run(task))
        self.assertEqual(RUN_MODE_INCOMPLETE, task._take_run_mode(None))

    def test_release_after_login_reenqueues_gated_batch_once(self):
        task, _resets = self.make_task({}, (), {"启用": True})
        task._start_after_login = True
        task._enabled = False
        enqueued = []
        task._executor = SimpleNamespace(
            get_task_by_class=lambda cls: task if cls is DailyBatchTask else None,
            enqueue_onetime_task=lambda t: enqueued.append(t) or True,
        )

        self.assertTrue(DailyBatchTask.release_after_login(task._executor))
        self.assertEqual([task], enqueued)
        self.assertTrue(task._enabled)
        self.assertFalse(task._start_after_login)

        task._enabled = False
        self.assertFalse(DailyBatchTask.release_after_login(task._executor))
        self.assertEqual(1, len(enqueued))

    def test_all_mode_records_child_schedule_after_success_and_failure(self):
        class First:
            pass

        class Second:
            pass

        calls = []
        first = _ChildTask("快速狩猎", calls)
        second = _ChildTask("镜中之战", calls, result=False)
        specs = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("第二项", Second),
        )
        task, _resets = self.make_task(
            {First: first, Second: second},
            specs,
            {"启用": True, "第一项": True, "第二项": True},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            schedule_store = scheduler.TaskScheduleStore(f"{temp_dir}/schedule.json")
            scheduler.set_default_store(schedule_store)
            try:
                self.assertFalse(DailyBatchTask.run(task))
            finally:
                scheduler.set_default_store(None)

        # 成功子任务推迟到下一次日常锚点（北京 04:00）。
        first_next = schedule_store.next_run("快速狩猎")
        self.assertIsNotNone(first_next)
        self.assertGreaterEqual(first_next, scheduler.next_daily_anchor_ts() - 1)
        self.assertTrue(schedule_store.last_run_ok("快速狩猎"))
        # 失败子任务按失败间隔退避，不推进锚点。
        second_next = schedule_store.next_run("镜中之战")
        self.assertIsNotNone(second_next)
        # The first failures in a row retry after 5 minutes.
        self.assertGreater(second_next, time.time() + 4 * 60)
        self.assertFalse(schedule_store.last_run_ok("镜中之战"))

    def test_shutdown_scheduled_when_all_enabled_children_completed(self):
        class First:
            pass

        class Second:
            pass

        class Disabled:
            pass

        first = _ChildTask("first", [])
        second = _ChildTask("second", [])
        specs = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("第二项", Second),
            DailyBatchChild("关闭项", Disabled),
        )
        task, _resets = self.make_task(
            {First: first, Second: second},
            specs,
            {
                "启用": True,
                "完成日常后自动关机": True,
                "第一项": True,
                "第二项": True,
                # 关闭的子任务不属于今日日常，不影响关机判定。
                "关闭项": False,
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            set_default_store(RunHistoryStore(f"{temp_dir}/history.json"))
            try:
                with mock.patch(
                    "src.tasks.DailyBatchTask._schedule_system_shutdown"
                ) as shutdown:
                    self.assertTrue(DailyBatchTask.run(task))
            finally:
                set_default_store(None)

        shutdown.assert_called_once_with(SHUTDOWN_COUNTDOWN_SECONDS)
        self.assertIn("自动关机", task.info.get("状态"))

    def test_shutdown_counts_child_completed_before_the_run(self):
        class First:
            pass

        class Second:
            pass

        first = _ChildTask("first", [])
        second = _ChildTask("second", [])
        specs = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("第二项", Second),
        )
        task, _resets = self.make_task(
            {First: first, Second: second},
            specs,
            {"启用": True, "完成日常后自动关机": True, "第一项": True, "第二项": True},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunHistoryStore(f"{temp_dir}/history.json")
            set_default_store(store)
            store.record_task_done(
                SimpleNamespace(name="first", start_time=0, info={"状态": "first 完成。"})
            )
            try:
                with mock.patch(
                    "src.tasks.DailyBatchTask._schedule_system_shutdown"
                ) as shutdown:
                    self.assertTrue(DailyBatchTask.run(task, RUN_MODE_INCOMPLETE))
            finally:
                set_default_store(None)

        shutdown.assert_called_once_with(SHUTDOWN_COUNTDOWN_SECONDS)

    def test_shutdown_not_scheduled_when_child_not_completed(self):
        class First:
            pass

        class Second:
            pass

        first = _ChildTask("快速狩猎", [])
        second = _ChildTask("镜中之战", [])
        specs = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("第二项", Second),
        )
        task, _resets = self.make_task(
            {First: first, Second: second},
            specs,
            {"启用": True, "完成日常后自动关机": True, "第一项": True, "第二项": True},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            schedule_store = scheduler.TaskScheduleStore(f"{temp_dir}/schedule.json")
            scheduler.set_default_store(schedule_store)
            set_default_store(RunHistoryStore(f"{temp_dir}/history.json"))
            try:
                # 退避中的子任务被跳过且今日未完成：批运行成功也不关机。
                schedule_store.delay_after_run("镜中之战", ok=False)
                with mock.patch(
                    "src.tasks.DailyBatchTask._schedule_system_shutdown"
                ) as shutdown:
                    self.assertTrue(DailyBatchTask.run(task, RUN_MODE_INCOMPLETE))
            finally:
                scheduler.set_default_store(None)
                set_default_store(None)

        shutdown.assert_not_called()

    def test_shutdown_not_scheduled_after_failure_or_when_switch_off(self):
        class First:
            pass

        class Second:
            pass

        for switch_on, second_result in ((False, True), (True, False)):
            with self.subTest(switch_on=switch_on, second_result=second_result):
                first = _ChildTask("first", [])
                second = _ChildTask("second", [], result=second_result)
                specs = (
                    DailyBatchChild("第一项", First),
                    DailyBatchChild("第二项", Second),
                )
                task, _resets = self.make_task(
                    {First: first, Second: second},
                    specs,
                    {
                        "启用": True,
                        "完成日常后自动关机": switch_on,
                        "第一项": True,
                        "第二项": True,
                    },
                )
                with mock.patch(
                    "src.tasks.DailyBatchTask._schedule_system_shutdown"
                ) as shutdown:
                    DailyBatchTask.run(task)
                shutdown.assert_not_called()

    def test_shutdown_not_scheduled_when_no_enabled_children(self):
        class First:
            pass

        first = _ChildTask("first", [])
        specs = (DailyBatchChild("第一项", First),)
        task, _resets = self.make_task(
            {First: first},
            specs,
            # 全部子开关关闭时一次成功运行没有执行任何日常；
            # 「全部已启用子任务已完成」对空集合为真，但不得触发关机。
            {"启用": True, "完成日常后自动关机": True, "第一项": False},
        )
        with mock.patch(
            "src.tasks.DailyBatchTask._schedule_system_shutdown"
        ) as shutdown:
            self.assertTrue(DailyBatchTask.run(task))
        shutdown.assert_not_called()
        self.assertNotIn("自动关机", task.info.get("状态", ""))

    def test_shutdown_survives_day_boundary_for_pre_completed_children(self):
        class First:
            pass

        first = _ChildTask("first", [])
        specs = (DailyBatchChild("第一项", First),)
        task, _resets = self.make_task(
            {First: first},
            specs,
            {"启用": True, "完成日常后自动关机": True, "第一项": True},
        )

        class BoundaryStore:
            """运行循环内记「今日已完成」，之后重算视为已跨过 04:00 日界。"""

            def __init__(self):
                self.calls = 0

            def is_completed_today(self, _name, now=None):
                self.calls += 1
                return self.calls == 1

        set_default_store(BoundaryStore())
        try:
            with mock.patch(
                "src.tasks.DailyBatchTask._schedule_system_shutdown"
            ) as shutdown:
                self.assertTrue(DailyBatchTask.run(task, RUN_MODE_INCOMPLETE))
        finally:
            set_default_store(None)

        # 运行前已完成跳过的子任务不能因关机判定时刻重算翻转为「非今日」而漏关机。
        shutdown.assert_called_once_with(SHUTDOWN_COUNTDOWN_SECONDS)

    def test_shutdown_not_claimed_when_system_rejects_schedule(self):
        class First:
            pass

        first = _ChildTask("first", [])
        specs = (DailyBatchChild("第一项", First),)
        task, _resets = self.make_task(
            {First: first},
            specs,
            {"启用": True, "完成日常后自动关机": True, "第一项": True},
        )
        errors = []
        task.log_error = lambda *args, **kwargs: errors.append(args)
        with mock.patch(
            "src.tasks.DailyBatchTask._schedule_system_shutdown",
            return_value=False,
        ) as shutdown:
            self.assertTrue(DailyBatchTask.run(task))
        shutdown.assert_called_once_with(SHUTDOWN_COUNTDOWN_SECONDS)
        # shutdown.exe 非零退出（如权限拒绝）时不得虚假宣称已安排关机。
        self.assertNotIn("自动关机", task.info.get("状态", ""))
        self.assertTrue(errors)

    def test_schedule_system_shutdown_uses_system32_and_reports_exit_code(self):
        from src.tasks.DailyBatchTask import _schedule_system_shutdown

        for returncode, expected in ((0, True), (5, False)):
            with self.subTest(returncode=returncode):
                completed = SimpleNamespace(returncode=returncode)
                with mock.patch(
                    "src.tasks.DailyBatchTask.subprocess.run",
                    return_value=completed,
                ) as run:
                    self.assertEqual(
                        expected,
                        _schedule_system_shutdown(SHUTDOWN_COUNTDOWN_SECONDS),
                    )
                command = run.call_args.args[0]
                # 绝对路径调用 System32 的 shutdown.exe，防止安装目录同名顶替。
                self.assertTrue(command[0].endswith("shutdown.exe"))
                self.assertEqual(["/s", "/t", "60"], command[1:])
                self.assertTrue(run.call_args.kwargs["capture_output"])


if __name__ == "__main__":
    unittest.main()


class OnlyIncompleteFlagTest(unittest.TestCase):
    def _run(self, mode):
        from src.tasks.map_trade.phase_ledger import ONLY_INCOMPLETE_KEY

        seen = []

        class Child:
            name = "每日跑商"
            config = {}

            def info_clear(self):
                pass

            def run(self):
                seen.append(self.config.get(ONLY_INCOMPLETE_KEY))
                return True

        class Trade:
            pass

        child = Child()
        task = object.__new__(DailyBatchTask)
        task.child_tasks = (DailyBatchChild("跑商", Trade),)
        task.config = {"启用": True, "跑商": True}
        task.info = {}
        task.info_set = lambda key, value: None
        task.log_info = task.log_warning = task.log_error = lambda *a, **k: None
        task._executor = SimpleNamespace(
            get_task_by_class=lambda cls: child, reset_scene=lambda **k: None
        )
        task._auto_login_pending = lambda: False
        history = mock.Mock()
        history.is_completed_today.return_value = False
        schedule = mock.Mock()
        schedule.is_due.return_value = True
        with (
            mock.patch("src.tasks.run_history.default_store", return_value=history),
            mock.patch("src.tasks.scheduler.default_store", return_value=schedule),
        ):
            DailyBatchTask.run(task, mode)
        return seen

    def test_children_learn_whether_to_skip_their_finished_parts(self):
        self.assertEqual([True], self._run(RUN_MODE_INCOMPLETE))
        self.assertEqual([False], self._run(RUN_MODE_ALL))


class CrashRestartTest(unittest.TestCase):
    """The game closed by itself (闪退) in 一键日常: open it again, log in, run
    what is left (Leo 2026-10-09)."""

    def setUp(self):
        self.game = {"running": True}
        patcher = mock.patch(
            "src.utils.game_process.game_running", side_effect=lambda: self.game["running"]
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        opener = mock.patch.object(DailyBatchTask, "_open_game")
        self.open_game = opener.start()
        self.addCleanup(opener.stop)
        self.schedule = mock.Mock()
        self.schedule.is_due.return_value = True
        store = mock.patch("src.tasks.scheduler.default_store", return_value=self.schedule)
        store.start()
        self.addCleanup(store.stop)

    def _batch(self, crash_in_run=True, crash_result=False):
        from src.tasks.trigger.AutoLoginTask import AutoLoginTask

        class First:
            pass

        class Crash:
            pass

        class Later:
            pass

        calls = []
        game = self.game

        class Crashing(_ChildTask):
            def run(self):
                calls.append((self.name, self.config.get("启用")))
                if not game.get("crashed"):  # closes once
                    game["crashed"] = True
                    game["running"] = False
                    return crash_result
                return True

        login = SimpleNamespace(_enabled=False, _finished=True)
        login._reset_login_state = lambda _action: setattr(login, "_finished", False)
        children = {
            First: _ChildTask("first", calls),
            Crash: Crashing("crash", calls) if crash_in_run else _ChildTask("crash", calls),
            Later: _ChildTask("later", calls),
            AutoLoginTask: login,
        }
        specs = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("闪退项", Crash),
            DailyBatchChild("后续项", Later),
        )
        task, _resets = DailyBatchTaskTest.make_task(
            self,
            children,
            specs,
            {"启用": True, "第一项": True, "闪退项": True, "后续项": True, "失败后继续": True},
        )
        return task, calls, login

    def test_crash_reopens_the_game_and_runs_what_is_left_after_login(self):
        task, calls, login = self._batch()

        self.assertFalse(DailyBatchTask.run(task))

        self.assertEqual([("first", True), ("crash", True)], calls)
        self.open_game.assert_called_once()
        self.assertTrue(login._enabled)
        self.assertFalse(login._finished)
        self.assertTrue(task._start_after_login)
        self.assertEqual(1, task._crash_restarts)
        # The mode the player picked carries on (here 跑勾选的 / all).
        self.assertEqual(RUN_MODE_ALL, task._take_run_mode(None))
        self.assertIn("闪退", task.info["状态"])
        self.assertEqual(run_report.ENDED_ABORTED, task._report_ended)
        # Not the child's fault: no failure wait, so the run after the login
        # does it again; nor for the children cut off.
        failed_waits = [
            c for c in self.schedule.delay_after_run.call_args_list if c.kwargs.get("ok") is False
        ]
        self.assertEqual([], failed_waits)

    def test_the_run_after_the_restart_goes_on_from_where_it_was(self):
        # Live 2026-10-10: the run after the restart was 跑没跑完的 and skipped
        # every ticked item done earlier today ("已执行 0 项").
        task, calls, login = self._batch()
        DailyBatchTask.run(task, RUN_MODE_ALL)
        self.game["running"] = True
        login._finished = True  # logged in again
        calls.clear()

        DailyBatchTask.run(task)

        self.assertEqual([("crash", True), ("later", True)], calls)
        self.assertEqual(run_report.ENDED_DONE, task._report_ended)

    def test_a_left_items_run_stays_left_items_after_the_restart(self):
        task, _calls, _login = self._batch()

        DailyBatchTask.run(task, RUN_MODE_INCOMPLETE)

        self.assertEqual(RUN_MODE_INCOMPLETE, task._take_run_mode(None))

    def test_a_new_start_by_the_player_runs_everything_again(self):
        task, calls, login = self._batch()
        DailyBatchTask.run(task, RUN_MODE_ALL)
        self.game["running"] = True
        login._finished = True  # logged in again
        task._resuming_after_crash = False
        calls.clear()

        DailyBatchTask.run(task, RUN_MODE_ALL)

        self.assertEqual(("first", True), calls[0])

    def test_closed_between_children_is_a_crash_too(self):
        task, calls, _login = self._batch(crash_result=True)

        self.assertFalse(DailyBatchTask.run(task))

        self.assertEqual([("first", True), ("crash", True)], calls)
        self.open_game.assert_called_once()
        self.assertTrue(task._start_after_login)

    def test_stops_after_the_restarts_run_out(self):
        task, calls, login = self._batch()
        task._resuming_after_crash = True
        task._crash_restarts = 2  # CRASH_RESTARTS_MAX

        self.assertFalse(DailyBatchTask.run(task))

        self.open_game.assert_not_called()
        self.assertFalse(getattr(task, "_start_after_login", False))
        self.assertIn("一直闪退", task.info["状态"])

    def test_a_start_by_the_player_counts_again(self):
        task, _calls, _login = self._batch()
        task._crash_restarts = 2  # left from an earlier run

        DailyBatchTask.run(task)

        self.open_game.assert_called_once()
        self.assertEqual(1, task._crash_restarts)

    def test_game_not_open_at_the_start_is_no_crash(self):
        for running in (False, None):  # closed, or cannot tell
            with self.subTest(running=running):
                self.game["running"] = running
                task, calls, _login = self._batch(crash_in_run=False)
                self.assertTrue(DailyBatchTask.run(task))
                self.open_game.assert_not_called()
                self.assertEqual(3, len(calls))
