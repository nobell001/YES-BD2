import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

from src.tasks.run_history import (
    BEIJING_TZ,
    RunHistoryStore,
    contains_joined_name,
    day_start_ts,
    week_start_ts,
)


def _beijing_ts(year, month, day, hour, minute=0) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=BEIJING_TZ).timestamp()


class _ExecutorStub:
    def __init__(self, tasks_by_class):
        self._tasks_by_class = tasks_by_class

    def get_task_by_class(self, cls):
        return self._tasks_by_class.get(cls)


class _ChildTaskStub:
    def __init__(self, name):
        self.name = name


class _ChildSpec:
    def __init__(self, config_key, task_class):
        self.config_key = config_key
        self.task_class = task_class


class _TaskStub:
    def __init__(self, name, info=None, start_time=1000.0, child_tasks=None, executor=None):
        self.name = name
        self.info = info or {}
        self.start_time = start_time
        if child_tasks is not None:
            self.child_tasks = child_tasks
        self.executor = executor


class DayBoundaryTest(unittest.TestCase):
    def test_before_4am_belongs_to_previous_day(self):
        anchor = day_start_ts(_beijing_ts(2026, 8, 18, 7, 59))
        self.assertEqual(anchor, _beijing_ts(2026, 8, 17, 8, 0))

    def test_after_4am_belongs_to_today(self):
        anchor = day_start_ts(_beijing_ts(2026, 8, 18, 8, 1))
        self.assertEqual(anchor, _beijing_ts(2026, 8, 18, 8, 0))

    def test_week_starts_monday_4am(self):
        # Wednesday noon -> this Monday 08:00.
        anchor = week_start_ts(_beijing_ts(2026, 8, 19, 12, 0))
        self.assertEqual(anchor, _beijing_ts(2026, 8, 17, 8, 0))

    def test_monday_before_4am_belongs_to_previous_week(self):
        anchor = week_start_ts(_beijing_ts(2026, 8, 17, 7, 59))
        self.assertEqual(anchor, _beijing_ts(2026, 8, 10, 8, 0))


class JoinedNameTest(unittest.TestCase):
    def test_element_containing_separator_matches_whole(self):
        joined = "公会、小屋、酒馆、快速狩猎"
        self.assertTrue(contains_joined_name(joined, "公会、小屋、酒馆"))
        self.assertTrue(contains_joined_name(joined, "快速狩猎"))

    def test_non_member_is_rejected(self):
        joined = "公会、小屋、酒馆、快速狩猎"
        self.assertFalse(contains_joined_name(joined, "跑商"))
        self.assertFalse(contains_joined_name(joined, ""))
        self.assertFalse(contains_joined_name("-", "跑商"))
        self.assertFalse(contains_joined_name(None, "跑商"))


class RunHistoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "task_run_history.json")
        self.store = RunHistoryStore(self.path)

    def test_record_and_reload_roundtrip(self):
        task = _TaskStub("快速狩猎", info={"状态": "快速狩猎完成。"}, start_time=1000.0)
        self.store.record_task_done(task, finished=1090.0)

        record = self.store.last_run("快速狩猎")
        self.assertTrue(record["ok"])
        self.assertEqual(record["duration"], 90.0)

        reloaded = RunHistoryStore(self.path)
        self.assertEqual(reloaded.last_run("快速狩猎"), record)

    def test_error_info_marks_run_failed(self):
        task = _TaskStub("每日跑商", info={"状态": "跑商完成。", "Error": "boom"})
        self.store.record_task_done(task, finished=2000.0)
        self.assertFalse(self.store.last_run("每日跑商")["ok"])

    def test_aborted_status_marks_run_failed(self):
        task = _TaskStub("一键完成日常", info={"状态": "一键完成日常中止。"})
        self.store.record_task_done(task, finished=2000.0)
        self.assertFalse(self.store.last_run("一键完成日常")["ok"])

    def test_neutral_status_with_failure_count_marks_run_failed(self):
        task = _TaskStub(
            "公会、小屋、酒馆",
            info={"状态": "公会、小屋、酒馆结束。", "完成": "[]", "失败": "['公会签到']"},
        )
        self.store.record_task_done(task, finished=2000.0)
        self.assertFalse(self.store.last_run("公会、小屋、酒馆")["ok"])

    def test_neutral_status_with_failed_phase_names_marks_run_failed(self):
        # MapTradeTask/MapCollectionTask report "…部分流程未完成。" with the
        # failed phase names in the 失败 key.
        task = _TaskStub(
            "每日跑商",
            info={"状态": "跑商部分流程未完成。", "完成": "-", "失败": "跑商买入", "跳过": "-"},
        )
        self.store.record_task_done(task, finished=2000.0)
        self.assertFalse(self.store.last_run("每日跑商")["ok"])

    def test_result_key_failure_marks_run_failed(self):
        # A task may write its verdict into 结果 instead of 状态.
        task = _TaskStub(
            "某个任务",
            info={"状态": "页面文字确认超时，任务结束。", "结果": "失败"},
        )
        self.store.record_task_done(task, finished=2000.0)
        self.assertFalse(self.store.last_run("某个任务")["ok"])

    def test_placeholder_failure_values_still_count_as_success(self):
        task = _TaskStub(
            "每日跑商",
            info={"状态": "跑商完成。", "完成": "跑商买入", "失败": "-", "跳过": "-"},
        )
        self.store.record_task_done(task, finished=2000.0)
        self.assertTrue(self.store.last_run("每日跑商")["ok"])

        task = _TaskStub(
            "公会、小屋、酒馆",
            info={"状态": "公会、小屋、酒馆结束。", "完成": "3", "失败": "0", "跳过": "0"},
        )
        self.store.record_task_done(task, finished=2100.0)
        self.assertTrue(self.store.last_run("公会、小屋、酒馆")["ok"])

    def test_pvp_and_goddess_failed_runs_remain_due_for_retry(self):
        from src.tasks.PVPTask import PVPTask
        from src.tasks.scheduler import TaskScheduleStore
        from src.tasks.SquareGoddessTask import SquareGoddessTask

        finished = _beijing_ts(2026, 9, 12, 12)
        for task_class, methods in (
            (PVPTask, ("_ensure_pvp_hub", "_start_auto_battle", "_wait_result_and_leave")),
            (SquareGoddessTask, (
                "_enter_square_from_home", "_pray_at_goddess", "_return_home_from_square",
            )),
        ):
            for failed_method in methods:
                with self.subTest(task=task_class.__name__, failed=failed_method):
                    info = {}
                    task = SimpleNamespace(
                        config={}, info=info, start_time=finished - 10,
                        name="镜中之战" if task_class is PVPTask else "广场女神像",
                        info_set=lambda key, value: info.__setitem__(key, value),
                        _status_set=lambda key, value: info.__setitem__(key, value),
                        log_info=lambda *args, **kwargs: None,
                        _target_multiplier=lambda: 4,
                        _record_wish=lambda: None,
                    )
                    for method in methods:
                        value = False if method == failed_method else True
                        if method == "_start_auto_battle":
                            value = "failed" if method == failed_method else "started"
                        setattr(task, method, lambda *args, value=value: value)
                    self.assertFalse(task_class.run(task))
                    self.store.record_task_done(task, finished=finished)
                    record = self.store.last_run(task.name)
                    self.assertFalse(record["ok"])
                    self.assertFalse(self.store.is_completed_today(task.name, now=finished))
                    schedule = TaskScheduleStore(os.path.join(self.dir, "schedule.json"))
                    retry_at = schedule.delay_after_run(task.name, ok=record["ok"], now=finished)
                    self.assertGreater(retry_at, finished)
                    self.assertLess(retry_at, _beijing_ts(2026, 9, 13, 8))

    def test_is_completed_today_respects_4am_boundary(self):
        task = _TaskStub("广场女神像", info={"状态": "ok"})
        self.store.record_task_done(task, finished=_beijing_ts(2026, 8, 18, 9, 0))

        self.assertTrue(
            self.store.is_completed_today("广场女神像", now=_beijing_ts(2026, 8, 18, 23, 0))
        )
        # After the next 08:00 refresh it no longer counts.
        self.assertFalse(
            self.store.is_completed_today("广场女神像", now=_beijing_ts(2026, 8, 19, 9, 0))
        )
        # A failed run never counts.
        self.store.record_task_done(
            _TaskStub("广场女神像", info={"Error": "x"}), finished=_beijing_ts(2026, 8, 18, 10, 0)
        )
        self.assertFalse(
            self.store.is_completed_today("广场女神像", now=_beijing_ts(2026, 8, 18, 11, 0))
        )

    def test_is_completed_this_week(self):
        task = _TaskStub("每周跑图", info={})
        self.store.record_task_done(task, finished=_beijing_ts(2026, 8, 17, 8, 0))
        self.assertTrue(
            self.store.is_completed_this_week("每周跑图", now=_beijing_ts(2026, 8, 19, 12, 0))
        )
        self.assertFalse(
            self.store.is_completed_this_week("每周跑图", now=_beijing_ts(2026, 8, 24, 8, 1))
        )

    def test_batch_run_fans_out_to_child_display_names(self):
        daily_cls = type("DailyTask", (), {})
        pvp_cls = type("PVPTask", (), {})
        trade_cls = type("MapTradeTask", (), {})
        children = [
            _ChildSpec("公会、小屋、酒馆", daily_cls),
            _ChildSpec("自动PVP", pvp_cls),
            _ChildSpec("跑商", trade_cls),
        ]
        executor = _ExecutorStub(
            {
                daily_cls: _ChildTaskStub("公会、小屋、酒馆"),
                pvp_cls: _ChildTaskStub("镜中之战"),
                trade_cls: _ChildTaskStub("每日跑商"),
            }
        )
        info = {
            "状态": "一键完成日常中止。",
            "完成": "公会、小屋、酒馆",
            "失败": "自动PVP",
            "跳过": "跑商",
            "Error": "x",
        }
        batch = _TaskStub("一键完成日常", info=info, child_tasks=children, executor=executor)
        self.store.record_task_done(batch, finished=_beijing_ts(2026, 8, 18, 9, 30))

        self.assertTrue(self.store.last_run("公会、小屋、酒馆")["ok"])
        # Config keys are resolved to the child tasks' display names.
        self.assertIsNotNone(self.store.last_run("镜中之战"))
        self.assertFalse(self.store.last_run("镜中之战")["ok"])
        # Skipped children get no record, so they stay "not done".
        self.assertIsNone(self.store.last_run("每日跑商"))
        self.assertFalse(
            self.store.is_completed_today("每日跑商", now=_beijing_ts(2026, 8, 18, 12, 0))
        )

    def test_batch_child_keeps_its_own_finish_time(self):
        # Done at 07:58, batch ended at 08:10: still yesterday's game day.
        class DailyCls:
            pass

        children = [_ChildSpec("公会、小屋、酒馆", DailyCls)]
        executor = _ExecutorStub({DailyCls: _ChildTaskStub("公会、小屋、酒馆")})
        info = {"状态": "一键完成日常完成。", "完成": "公会、小屋、酒馆", "失败": "-", "跳过": "-"}
        batch = _TaskStub("一键完成日常", info=info, child_tasks=children, executor=executor)
        batch._child_finished = {"公会、小屋、酒馆": _beijing_ts(2026, 8, 18, 7, 58)}
        self.store.record_task_done(batch, finished=_beijing_ts(2026, 8, 18, 8, 10))
        self.assertFalse(
            self.store.is_completed_today("公会、小屋、酒馆", now=_beijing_ts(2026, 8, 18, 9, 0))
        )

    def _child_across(self, name, started, finished):
        class ChildCls:
            pass

        children = [_ChildSpec(name, ChildCls)]
        executor = _ExecutorStub({ChildCls: _ChildTaskStub(name)})
        info = {"状态": "一键完成日常完成。", "完成": name, "失败": "-", "跳过": "-"}
        batch = _TaskStub("一键完成日常", info=info, child_tasks=children, executor=executor)
        batch._child_started = {name: started}
        batch._child_finished = {name: finished}
        self.store.record_task_done(batch, finished=finished + 60)

    def test_batch_child_started_before_8am_is_the_old_days(self):
        # Started 07:58, finished 08:01: the new day still has it to do.
        self._child_across(
            "快速狩猎", _beijing_ts(2026, 8, 18, 7, 58), _beijing_ts(2026, 8, 18, 8, 1)
        )
        now = _beijing_ts(2026, 8, 18, 9, 0)
        self.assertFalse(self.store.is_completed_today("快速狩猎", now=now))
        self.assertEqual([True, None], self.store.recent_days("快速狩猎", 2, now=now))

    def test_batch_child_started_before_monday_8am_is_last_weeks(self):
        self._child_across(
            "末日之书", _beijing_ts(2026, 8, 17, 7, 59), _beijing_ts(2026, 8, 17, 8, 1)
        )
        now = _beijing_ts(2026, 8, 17, 9, 0)
        self.assertFalse(self.store.is_completed_this_week("末日之书", now=now))

    def test_batch_child_within_one_day_keeps_its_finish_time(self):
        finished = _beijing_ts(2026, 8, 18, 8, 3)
        self._child_across("快速狩猎", _beijing_ts(2026, 8, 18, 8, 1), finished)
        self.assertEqual(finished, self.store.last_run("快速狩猎")["finished"])
        self.assertTrue(
            self.store.is_completed_today("快速狩猎", now=_beijing_ts(2026, 8, 18, 9, 0))
        )

    def test_corrupt_file_loads_empty(self):
        with open(self.path, "w", encoding="utf-8") as file:
            file.write("{not json")
        store = RunHistoryStore(self.path)
        self.assertIsNone(store.last_run("快速狩猎"))

    def test_unknown_version_loads_empty(self):
        with open(self.path, "w", encoding="utf-8") as file:
            file.write('{"version": 999, "tasks": {"a": {"finished": 1}}}')
        store = RunHistoryStore(self.path)
        self.assertIsNone(store.last_run("a"))


if __name__ == "__main__":
    unittest.main()
