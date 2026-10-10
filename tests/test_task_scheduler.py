"""ALAS/NKAS 式 next_run 调度账本的回归."""

import inspect
import json
import os
import re
import tempfile
import unittest
from datetime import datetime

from src.tasks import scheduler
from src.tasks.run_history import BEIJING_TZ


def _beijing_ts(year, month, day, hour, minute=0) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=BEIJING_TZ).timestamp()


class NextAnchorTest(unittest.TestCase):
    def test_next_daily_anchor(self):
        # 周三 09:00 -> 周四 08:00
        self.assertEqual(
            scheduler.next_daily_anchor_ts(_beijing_ts(2026, 8, 19, 9, 0)),
            _beijing_ts(2026, 8, 20, 8, 0),
        )
        # 07:00 -> 当天 08:00
        self.assertEqual(
            scheduler.next_daily_anchor_ts(_beijing_ts(2026, 8, 19, 7, 0)),
            _beijing_ts(2026, 8, 19, 8, 0),
        )
        # 恰好 08:00 -> 明天 08:00
        self.assertEqual(
            scheduler.next_daily_anchor_ts(_beijing_ts(2026, 8, 19, 8, 0)),
            _beijing_ts(2026, 8, 20, 8, 0),
        )

    def test_next_weekly_anchor(self):
        # 周三 12:00 -> 下周一 08:00
        self.assertEqual(
            scheduler.next_weekly_anchor_ts(_beijing_ts(2026, 8, 19, 12, 0)),
            _beijing_ts(2026, 8, 24, 8, 0),
        )
        # 周一 07:00（本周尚未刷新）-> 当天 08:00
        self.assertEqual(
            scheduler.next_weekly_anchor_ts(_beijing_ts(2026, 8, 17, 7, 0)),
            _beijing_ts(2026, 8, 17, 8, 0),
        )
        # 周一 09:00 -> 下周一 08:00
        self.assertEqual(
            scheduler.next_weekly_anchor_ts(_beijing_ts(2026, 8, 17, 9, 0)),
            _beijing_ts(2026, 8, 24, 8, 0),
        )


class TaskScheduleStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "task_schedule.json")
        self.store = scheduler.TaskScheduleStore(self.path)

    def test_no_record_means_due(self):
        self.assertTrue(self.store.is_due("快速狩猎"))
        self.assertIsNone(self.store.next_run("快速狩猎"))
        self.assertEqual(self.store.backoff_remaining_minutes("快速狩猎"), 0.0)

    def test_success_daily_delay_lands_on_next_4am(self):
        next_run = self.store.delay_after_run(
            "快速狩猎", ok=True, now=_beijing_ts(2026, 8, 19, 9, 0)
        )
        self.assertEqual(next_run, _beijing_ts(2026, 8, 20, 8, 0))
        self.assertFalse(
            self.store.is_due("快速狩猎", now=_beijing_ts(2026, 8, 19, 23, 0))
        )
        self.assertTrue(
            self.store.is_due("快速狩猎", now=_beijing_ts(2026, 8, 20, 8, 0))
        )

    def test_success_weekly_delay_lands_on_next_monday(self):
        next_run = self.store.delay_after_run(
            "末日之书", ok=True, now=_beijing_ts(2026, 8, 19, 12, 0)
        )
        self.assertEqual(next_run, _beijing_ts(2026, 8, 24, 8, 0))

    def test_map_collection_is_due_again_the_next_game_day(self):
        # 每周跑图 runs up to 7 cards a day: a Tuesday success must not hold
        # 「跑没跑完的」 back until Monday.
        self.store.delay_after_run("每周跑图", ok=True, now=_beijing_ts(2026, 10, 6, 10, 0))
        self.assertFalse(self.store.is_due("每周跑图", now=_beijing_ts(2026, 10, 6, 23, 0)))
        self.assertTrue(self.store.is_due("每周跑图", now=_beijing_ts(2026, 10, 7, 8, 0)))

    def test_a_success_saved_under_the_old_weekly_rule_waits_one_day_only(self):
        tuesday = _beijing_ts(2026, 10, 6, 10, 0)
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "version": scheduler.STORE_VERSION,
                    "tasks": {
                        "每周跑图": {
                            "next_run": _beijing_ts(2026, 10, 12, 8, 0),
                            "ok": True,
                            "updated": tuesday,
                            "failures": 0,
                        }
                    },
                },
                file,
            )
        store = scheduler.TaskScheduleStore(self.path)
        self.assertEqual(_beijing_ts(2026, 10, 7, 8, 0), store.next_run("每周跑图"))
        self.assertTrue(store.is_due("每周跑图", now=_beijing_ts(2026, 10, 7, 9, 0)))

    def test_failure_delays_by_backoff_interval(self):
        # Two quick retries after 5 minutes, then the full 30-minute backoff.
        now = _beijing_ts(2026, 8, 19, 9, 0)
        next_run = self.store.delay_after_run("镜中之战", ok=False, now=now)
        self.assertEqual(next_run, now + 5 * 60)
        self.assertAlmostEqual(
            self.store.backoff_remaining_minutes("镜中之战", now=now + 60), 4.0
        )
        self.assertTrue(self.store.last_run_ok("镜中之战") is False)
        self.assertEqual(now + 5 * 60, self.store.delay_after_run("镜中之战", ok=False, now=now))
        self.assertEqual(now + 30 * 60, self.store.delay_after_run("镜中之战", ok=False, now=now))

    def test_a_success_resets_the_quick_retries(self):
        now = _beijing_ts(2026, 8, 19, 9, 0)
        for _ in range(3):
            self.store.delay_after_run("镜中之战", ok=False, now=now)
        self.store.delay_after_run("镜中之战", ok=True, now=now)
        self.assertEqual(now + 5 * 60, self.store.delay_after_run("镜中之战", ok=False, now=now))

    def test_success_interval_can_be_nearer_than_anchor(self):
        policy = scheduler.SchedulePolicy(
            anchor="daily", success_interval_minutes=15.0
        )
        now = _beijing_ts(2026, 8, 19, 7, 30)
        next_run = self.store.delay_after_run(
            "自定义", ok=True, now=now, policy=policy
        )
        # now+15min(07:45) 比锚点 08:00 更近，按 ALAS 语义取最近者。
        self.assertEqual(next_run, now + 15 * 60)

    def test_unknown_task_is_not_scheduled(self):
        self.assertIsNone(self.store.delay_after_run("未知任务", ok=True))
        self.assertIsNone(self.store.next_run("未知任务"))

    def test_mark_due_now_forces_execution(self):
        self.store.delay_after_run(
            "快速狩猎", ok=True, now=_beijing_ts(2026, 8, 19, 9, 0)
        )
        forced = _beijing_ts(2026, 8, 19, 10, 0)
        self.store.mark_due_now("快速狩猎", now=forced)
        self.assertTrue(self.store.is_due("快速狩猎", now=forced))

    def test_roundtrip_and_corrupt_inputs(self):
        self.store.delay_after_run(
            "快速狩猎", ok=True, now=_beijing_ts(2026, 8, 19, 9, 0)
        )
        record = self.store.next_run("快速狩猎")
        reloaded = scheduler.TaskScheduleStore(self.path)
        self.assertEqual(reloaded.next_run("快速狩猎"), record)

        with open(self.path, "w", encoding="utf-8") as file:
            file.write("{not json")
        self.assertIsNone(scheduler.TaskScheduleStore(self.path).next_run("快速狩猎"))

        with open(self.path, "w", encoding="utf-8") as file:
            file.write('{"version": 999, "tasks": {"a": {"next_run": 1}}}')
        self.assertIsNone(scheduler.TaskScheduleStore(self.path).next_run("a"))

    def test_policy_registry_covers_batch_children(self):
        for name in (
            "公会、小屋、酒馆",
            "快速狩猎",
            "白嫖抽抽乐",
            "广场女神像",
            "镜中之战",
            "每日跑商",
            "活动每日战斗",
            "领取常客圣石",
            "每日精炼一次",
            "爛装强化分解",
            "领取任务奖励",
            "领取通行证",
            "领取邮件",
            "每周跑图",
        ):
            self.assertEqual(scheduler.TASK_POLICIES[name].anchor, "daily")
        # 批处理自身没有调度策略：「执行剩余」只看子任务账本，批处理整体
        # 的 next_run 无消费者（避免只写不读的误导条目）。
        self.assertNotIn("一键完成日常", scheduler.TASK_POLICIES)


class BatchChildPolicyTest(unittest.TestCase):
    """The schedule must agree with how 一键日常 counts a child as done."""

    def test_daily_children_are_due_daily_and_weekly_children_weekly(self):
        from src.tasks.DailyBatchTask import DAILY_BATCH_CHILDREN

        for child in DAILY_BATCH_CHILDREN:
            name = re.search(
                r'self\.name = "([^"]+)"', inspect.getsource(child.task_class)
            ).group(1)
            policy = scheduler.policy_for(name)
            if policy is None:
                continue  # unscheduled: always due
            with self.subTest(child=child.config_key):
                self.assertEqual("weekly" if child.weekly else "daily", policy.anchor)


if __name__ == "__main__":
    unittest.main()
