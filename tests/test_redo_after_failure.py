"""A run that failed goes home and runs once more before it counts as failed
(Leo 2026-11-05 「你不要一個地方沒辨識到就出錯 明明有很多方法」).  Only for
tasks whose second run cannot spend or dismantle twice."""

import unittest
from unittest import mock

from src.tasks import BaseBD2Task as base_module


def _task(retry=True, failure_retry=None):
    task_type = type("Task", (), {"frozen_retry": retry, "failure_retry": failure_retry})
    task = task_type()
    task.name = "测试"
    task._why = ""
    task.log_warning = mock.Mock()
    task.log_info = mock.Mock()
    return task


def _runner(task, results, whys=()):
    results, whys = iter(results), iter(whys)
    calls = []

    def run(t):
        calls.append(1)
        t._why = next(whys, "")
        return next(results)

    return run, calls


class RedoAfterFailureTest(unittest.TestCase):
    def test_a_failed_run_goes_home_and_runs_once_more(self):
        task = _task()
        run, calls = _runner(task, [False, True], ["没认出生活玩法类别高亮"])
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True) as home:
            self.assertTrue(base_module._run_watched(task, run, (), {}, watched=True))
        home.assert_called_once_with(task)
        self.assertEqual(2, len(calls))
        self.assertIn("没认出生活玩法类别高亮", task.log_warning.call_args.args[0])
        self.assertIn("回主页再做一次", task.log_warning.call_args.args[0])

    def test_failed_twice_the_reason_names_both_tries(self):
        task = _task()
        run, calls = _runner(task, [False, False], ["没进到亲密度", "谈心面板没读到"])
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True):
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual(2, len(calls))
        self.assertEqual("谈心面板没读到（第一次：没进到亲密度）", task._why)

    def test_the_same_reason_twice_says_so(self):
        task = _task()
        run, _calls = _runner(task, [False, False], ["没进到亲密度", "没进到亲密度"])
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True):
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual("没进到亲密度（回主页再做一次还是一样）", task._why)

    def test_no_redo_when_home_is_not_reached(self):
        task = _task()
        run, calls = _runner(task, [False, True])
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=False):
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual(1, len(calls))

    def test_a_task_that_may_spend_is_not_run_again(self):
        task = _task(retry=False)
        run, calls = _runner(task, [False, True])
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True) as home:
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual(1, len(calls))
        home.assert_not_called()

    def test_a_task_that_redoes_its_own_parts_is_not_run_again(self):
        task = _task(retry=True, failure_retry=False)
        run, calls = _runner(task, [False, True])
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True):
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual(1, len(calls))

    def test_a_good_run_is_not_run_again(self):
        task = _task()
        run, calls = _runner(task, [True])
        self.assertTrue(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual(1, len(calls))

    def test_a_failure_then_a_frozen_screen_is_tried_only_twice(self):
        task = _task()
        results = iter([False, base_module.FrozenScreen()])
        calls = []

        def run(t):
            calls.append(1)
            result = next(results)
            if isinstance(result, Exception):
                raise result
            t._why = "没进到亲密度"
            return result

        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True), mock.patch(
            "src.tasks.recovery.home_now", return_value=True
        ):
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual(2, len(calls))
        self.assertIn("第一次：没进到亲密度", task._why)

    def test_which_tasks_run_again_after_a_failure(self):
        from src.tasks.AffinityTalkTask import AffinityTalkTask
        from src.tasks.CraftGearTask import CraftGearTask
        from src.tasks.GearTasks import DailyRefineTask
        from src.tasks.JunkGearTask import JunkGearTask
        from src.tasks.MapCollectionTask import MapCollectionTask
        from src.tasks.MapTradeTask import MapTradeTask
        from src.tasks.RedemptionTowerTask import RedemptionTowerTask
        from src.tasks.SquareGoddessTask import SquareGoddessTask

        def redoes(cls):
            flag = cls.failure_retry
            return cls.frozen_retry if flag is None else flag

        # Leo 2026-11-05: 精煉, 製作, 爛裝, 跑商, 救贖之塔 run once more too.
        for cls in (AffinityTalkTask, SquareGoddessTask, DailyRefineTask, JunkGearTask,
                    CraftGearTask, MapTradeTask, RedemptionTowerTask):
            self.assertTrue(redoes(cls), cls.__name__)
        # 跑图 already runs each card once more; a whole rerun redoes skipped cards blind.
        self.assertFalse(redoes(MapCollectionTask))


if __name__ == "__main__":
    unittest.main()
