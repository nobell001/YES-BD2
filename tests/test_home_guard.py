"""A failed daily task goes back home (live 2026-09-28: goddess stayed in
the square, junk gear in the bag)."""

import unittest
from unittest import mock

from src.tasks.BaseBD2Task import BaseBD2Task


class HomeGuardTest(unittest.TestCase):
    def _classes(self, opt_in):
        class Task(BaseBD2Task):
            recover_home_on_failure = opt_in

            def __init__(self, result):
                self._action_interval_lock = None  # as BaseBD2Task.__init__ sets
                self.result = result
                self.home_calls = 0

            def run(self):
                if isinstance(self.result, BaseException):
                    raise self.result
                return self.result

            def _leave_home_after_failed_run(self):
                self.home_calls += 1

            def _go_home_before_run(self):
                self.before_calls = getattr(self, "before_calls", 0) + 1

        return Task

    def test_failed_run_goes_home(self):
        task = self._classes(True)(False)
        self.assertFalse(task.run())
        self.assertEqual(1, task.home_calls)

    def test_successful_run_does_not(self):
        task = self._classes(True)(True)
        self.assertTrue(task.run())
        self.assertEqual(0, task.home_calls)

    def test_crashed_run_goes_home_and_still_raises(self):
        task = self._classes(True)(ValueError("boom"))
        with self.assertRaises(ValueError):
            task.run()
        self.assertEqual(1, task.home_calls)

    def test_stop_during_run_does_not_go_home(self):
        from ok.task.exceptions import TaskDisabledException

        task = self._classes(True)(TaskDisabledException())
        with self.assertRaises(TaskDisabledException):
            task.run()
        self.assertEqual(0, task.home_calls)

    def test_tasks_without_the_flag_are_untouched(self):
        # Trigger tasks return False for "nothing to do".
        task = self._classes(False)(False)
        self.assertFalse(task.run())
        self.assertEqual(0, task.home_calls)

    def test_home_starting_tasks_go_home_first(self):
        cls = self._classes(True)
        cls.start_from_home = True
        task = cls(True)
        task.run()
        self.assertEqual(1, task.before_calls)
        plain = self._classes(True)(True)
        plain.run()
        self.assertEqual(0, getattr(plain, "before_calls", 0))

    def test_stop_is_never_swallowed(self):
        from ok.task.exceptions import TaskDisabledException

        task = self._classes(True)(False)
        with mock.patch(
            "src.tasks.recovery.recover_to_home", side_effect=TaskDisabledException()
        ):
            with self.assertRaises(TaskDisabledException):
                BaseBD2Task._leave_home_after_failed_run(task)

    def test_daily_tasks_opt_in(self):
        from src.tasks.DailyTask import DailyTask
        from src.tasks.FreeGachaTask import FreeGachaTask
        from src.tasks.GearTasks import DailyRefineTask
        from src.tasks.JunkGearTask import JunkGearTask
        from src.tasks.MapTradeTask import MapTradeTask
        from src.tasks.PVPTask import PVPTask
        from src.tasks.QuickHuntTask import QuickHuntTask
        from src.tasks.SquareGoddessTask import SquareGoddessTask

        for cls in (DailyTask, FreeGachaTask, DailyRefineTask, JunkGearTask, MapTradeTask,
                    PVPTask, QuickHuntTask, SquareGoddessTask):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(cls.recover_home_on_failure)
                self.assertTrue(getattr(cls.run, "_bd2_home_guard", False))


class StepInAfterPauseTest(unittest.TestCase):
    """decision 8 of the 10-10 plan, its default: a click on the paused game does not stop the run;
    after 继续 it looks at the screen again before its next press."""

    def _task(self, results, home=True, start_from_home=True):
        from types import SimpleNamespace

        runs = []

        class Task(BaseBD2Task):
            recover_home_on_failure = home

            def __init__(self):
                self._action_interval_lock = None  # as BaseBD2Task.__init__ sets
                self.name = "免费抽抽乐"
                self.info = {}
                self.warnings = []

            def run(self):
                runs.append(1)
                result = results.pop(0)
                if isinstance(result, BaseException):
                    raise result
                return result

            def info_set(self, key, value):
                self.info[key] = value

            def log_info(self, *_args, **_kwargs):
                pass

            def log_warning(self, message, **_kwargs):
                self.warnings.append(message)

            def _leave_home_after_failed_run(self):
                pass

            def _go_home_before_run(self):
                pass

        Task.start_from_home = start_from_home and home
        task = Task()
        task._executor = SimpleNamespace(current_task=None)
        return task, runs

    def test_sleep_after_continue_raises_once_when_the_player_stepped_in(self):
        from types import SimpleNamespace

        from src.tasks.BaseBD2Task import PlayerSteppedIn

        task, _runs = self._task([])
        batch = SimpleNamespace(paused=False, player_stepped_in=True)
        task._executor = SimpleNamespace(current_task=batch, sleep=lambda _seconds: None)

        with self.assertRaises(PlayerSteppedIn):
            task.sleep(1)
        self.assertFalse(batch.player_stepped_in)
        self.assertTrue(task.sleep(1))  # once only

    def test_a_pause_without_the_player_goes_on(self):
        from types import SimpleNamespace

        task, _runs = self._task([])
        batch = SimpleNamespace(paused=False)
        task._executor = SimpleNamespace(current_task=batch, sleep=lambda _seconds: None)

        self.assertTrue(task.sleep(1))

    def test_the_run_starts_again_from_home(self):
        from src.tasks.BaseBD2Task import PlayerSteppedIn

        task, runs = self._task([PlayerSteppedIn(), True])
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True) as home:
            self.assertTrue(task.run())
        home.assert_called_once_with(task)
        self.assertEqual(2, len(runs))

    def test_no_home_no_further_presses(self):
        from src.tasks.BaseBD2Task import PlayerSteppedIn

        task, runs = self._task([PlayerSteppedIn(), True])
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=False):
            self.assertFalse(task.run())
        self.assertEqual(1, len(runs))
        self.assertIn("暂停时你动了游戏，回不到主页", task.info["状态"])

    def test_a_task_that_does_not_start_from_home_stops(self):
        from src.tasks.BaseBD2Task import PlayerSteppedIn

        task, runs = self._task([PlayerSteppedIn(), True], home=False)
        with mock.patch("src.tasks.recovery.recover_to_home") as home:
            self.assertFalse(task.run())
        home.assert_not_called()
        self.assertEqual(1, len(runs))
        self.assertIn("暂停时你动了游戏", task.info["状态"])

    def test_stepping_in_again_while_it_goes_home(self):
        from src.tasks.BaseBD2Task import PlayerSteppedIn

        task, runs = self._task([PlayerSteppedIn(), True])
        with mock.patch(
            "src.tasks.recovery.recover_to_home", side_effect=[PlayerSteppedIn(), True]
        ):
            self.assertTrue(task.run())
        self.assertEqual(2, len(runs))

    def test_stepping_in_on_the_way_home_before_the_run(self):
        from src.tasks.BaseBD2Task import PlayerSteppedIn

        task, runs = self._task([True])
        task._go_home_before_run = mock.Mock(side_effect=PlayerSteppedIn())
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True) as home:
            self.assertTrue(task.run())
        home.assert_called_once_with(task)
        self.assertEqual(1, len(runs))

    def test_a_new_run_forgets_a_step_in_left_by_a_stop(self):
        task, _runs = self._task([True])
        task._executor.current_task = task
        task.player_stepped_in = True  # stopped while paused, after a click
        task._accounts_stop = task._setup_stops = lambda: False
        with (
            mock.patch("src.tasks.problem_report.is_trigger", return_value=False),
            mock.patch("src.utils.game_size.fix_or_warn"),
        ):
            task.run()
        self.assertFalse(task.player_stepped_in)


if __name__ == "__main__":
    unittest.main()
