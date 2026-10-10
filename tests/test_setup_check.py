"""The 开跑前检查 (差異化點子 5): a reminder before a run the player started;
a game set to 繁中 does not start (Leo 2026-10-09 「5提醒就好了」)."""

import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
from ok.task.exceptions import TaskDisabledException

from src.tasks import problem_report, run_history, run_report, setup_check
from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.DailyBatchTask import DailyBatchChild, DailyBatchTask
from src.tasks.map_trade.vision import Vision
from src.utils import accounts, colour_check

TRADITIONAL_LEFT = "我的小屋 格魯TALK 街機遊戲"
SIMPLIFIED_LEFT = "我的小屋 格鲁TALK 街机游戏"


class _Task:
    def __init__(self, frames=None):
        self.frames = list(frames if frames is not None else [np.zeros((4, 4, 3), np.uint8)] * 8)
        self.info = {}
        self.warnings = []
        self.config = {}

    def next_frame(self):
        return self.frames.pop(0) if self.frames else None

    def sleep(self, _seconds):
        pass

    def info_set(self, key, value):
        self.info[key] = value

    def log_warning(self, message, notify=False):
        self.warnings.append((message, notify))


def _reads(*left_texts, gacha=""):
    """Vision.ocr_text that reads ``left_texts`` one frame after another."""
    lefts = list(left_texts)
    calls = []

    def ocr_text(_vision, _frame, name, **_kwargs):
        calls.append(name)
        if name.endswith("左列"):
            return lefts.pop(0) if lefts else ""
        return gacha

    return mock.patch.object(Vision, "ocr_text", ocr_text), calls


def _colours(distance):
    return mock.patch.object(
        colour_check,
        "check_capture_colours",
        lambda _frame: colour_check.ColourCheck(distance, "测试"),
    )


class LookTest(unittest.TestCase):
    def setUp(self):
        setup_check.reset()
        self.addCleanup(setup_check.reset)
        colour_check.forget_capture()
        self.addCleanup(colour_check.forget_capture)
        previous = colour_check.last_check()
        self.addCleanup(lambda: colour_check.remember(previous))

    def test_traditional_home_on_two_frames_stops_with_a_reminder(self):
        task = _Task()
        reads, _calls = _reads(TRADITIONAL_LEFT, TRADITIONAL_LEFT)
        with reads, _colours(2.0):
            notice = setup_check.look(task)
        self.assertEqual(setup_check.LANGUAGE_NOTICE, notice)
        self.assertEqual([(setup_check.LANGUAGE_MESSAGE, True)], task.warnings)
        self.assertEqual(setup_check.LANGUAGE_NOTICE, task.info[run_history.NOT_STARTED_KEY])

    def test_one_traditional_frame_is_not_enough(self):
        task = _Task()
        reads, _calls = _reads(TRADITIONAL_LEFT, "")
        with reads, _colours(None):
            self.assertEqual("", setup_check.look(task))
        self.assertEqual([], task.warnings)
        self.assertNotIn(run_history.NOT_STARTED_KEY, task.info)

    def test_simplified_home_goes_on_without_reading_the_gacha_label(self):
        task = _Task()
        reads, calls = _reads(SIMPLIFIED_LEFT)
        with reads, _colours(3.0):
            self.assertEqual("", setup_check.look(task))
        self.assertEqual([], task.warnings)
        self.assertEqual(1, len(calls))

    def test_traditional_gacha_label_with_part_of_the_left_column(self):
        task = _Task()
        reads, _calls = _reads("格魯", "格魯", gacha="抽抽樂")
        with reads, _colours(None):
            self.assertEqual(setup_check.LANGUAGE_NOTICE, setup_check.look(task))

    def test_a_page_that_is_not_home_is_no_reminder(self):
        task = _Task()
        reads, _calls = _reads("", gacha="")
        with reads, _colours(None):
            self.assertEqual("", setup_check.look(task))
        self.assertEqual([], task.warnings)

    def test_a_traditional_guild_description_is_no_reminder(self):
        # Live 2K 10-10: a 简中 client left on the guild page, whose player-written
        # description is 繁中, refused every start 76 times.
        guild = "8 30/30 审核 申請請DC聯絡公 #zaga12022"
        for gacha in ("", "小尤里樂園Ⅱ 申請請DC聯絡公會長"):
            with self.subTest(gacha=gacha):
                task = _Task()
                reads, _calls = _reads(guild, guild, gacha=gacha)
                with reads, _colours(None):
                    self.assertEqual("", setup_check.look(task))
                self.assertEqual([], task.warnings)
                self.assertNotIn(run_history.NOT_STARTED_KEY, task.info)

    def test_no_frame_or_a_broken_reading_never_stops_the_run(self):
        self.assertEqual("", setup_check.look(_Task(frames=[])))

        def broken(*_args, **_kwargs):
            raise RuntimeError("ocr down")

        with mock.patch.object(Vision, "ocr_text", broken):
            self.assertEqual("", setup_check.look(_Task()))

    def test_stop_pressed_during_the_look_still_stops(self):
        def stopped(*_args, **_kwargs):
            raise TaskDisabledException()

        with mock.patch.object(Vision, "ocr_text", stopped):
            with self.assertRaises(TaskDisabledException):
                setup_check.look(_Task())

    def test_odd_colours_remind_once_in_a_while_and_the_run_goes_on(self):
        task = _Task()
        reads, _calls = _reads(SIMPLIFIED_LEFT, SIMPLIFIED_LEFT)
        with reads, _colours(40.0):
            self.assertEqual("", setup_check.look(task, now=100.0))
            self.assertEqual("", setup_check.look(task, now=200.0))
        self.assertEqual(
            [(setup_check.COLOUR_MESSAGE, True), (setup_check.COLOUR_MESSAGE, False)],
            task.warnings,
        )
        self.assertEqual(40.0, colour_check.last_check().distance)

    def test_normal_colours_say_nothing(self):
        task = _Task()
        reads, _calls = _reads(SIMPLIFIED_LEFT)
        with reads, _colours(4.0):
            setup_check.look(task)
        self.assertEqual([], task.warnings)
        self.assertEqual("测试", task.info[setup_check.COLOUR_KEY])

    def test_started_alone_means_the_executor_runs_this_task(self):
        task = _Task()
        task.executor = SimpleNamespace(current_task=task)
        self.assertTrue(setup_check.started_alone(task))
        task.executor = SimpleNamespace(current_task=object())
        self.assertFalse(setup_check.started_alone(task))
        self.assertFalse(setup_check.started_alone(_Task()))


class _Child:
    def __init__(self, calls):
        self.name = "子任务"
        self.calls = calls
        self.config = {}

    def info_clear(self):
        pass

    def run(self):
        self.calls.append(self.name)
        return True


class BatchTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        run_report.set_report_file(f"{folder.name}/run_reports.json")
        self.addCleanup(run_report.set_report_file, None)

    def _batch(self, calls):
        class Child:
            pass

        task = object.__new__(DailyBatchTask)
        task.child_tasks = (DailyBatchChild("第一项", Child),)
        task.config = {"启用": True, "第一项": True}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_args, **_kwargs: None
        task.log_warning = lambda *_args, **_kwargs: None
        task.log_error = lambda *_args, **_kwargs: None
        child = _Child(calls)
        task._executor = SimpleNamespace(
            get_task_by_class=lambda cls: child if cls is Child else None,
            reset_scene=lambda **_kwargs: None,
        )
        return task

    def test_traditional_game_ends_the_batch_before_its_first_item(self):
        calls = []
        task = self._batch(calls)
        with mock.patch.object(setup_check, "look", lambda _task: setup_check.LANGUAGE_NOTICE):
            self.assertFalse(DailyBatchTask.run(task))
        self.assertEqual([], calls)
        report = run_report.load(task.batch_label)
        self.assertEqual(run_report.ENDED_SETUP, report["ended"])
        self.assertEqual(setup_check.LANGUAGE_NOTICE, report["notice"])
        self.assertEqual([run_report.WAIT], [row["state"] for row in report["rows"]])
        # Never counted as a finished run (the run history's success rule).
        self.assertIn("中止", task.info["状态"])

    def test_unreadable_account_list_ends_the_batch_before_its_first_item(self):
        calls = []
        task = self._batch(calls)
        notice = setup_check.ACCOUNTS_TEXTS[accounts.BROKEN][1]
        with (
            mock.patch.object(accounts, "unreadable", return_value=accounts.BROKEN),
            mock.patch.object(setup_check, "look", lambda _task: ""),
        ):
            self.assertFalse(DailyBatchTask.run(task))
        self.assertEqual([], calls)
        report = run_report.load(task.batch_label)
        self.assertEqual(run_report.ENDED_SETUP, report["ended"])
        self.assertEqual(notice, report["notice"])
        self.assertEqual(notice, task.info[run_history.NOT_STARTED_KEY])
        self.assertIn("账号清单", task.info["状态"])

    def test_a_clear_look_runs_the_items(self):
        calls = []
        task = self._batch(calls)
        with mock.patch.object(setup_check, "look", lambda _task: ""):
            self.assertTrue(DailyBatchTask.run(task))
        self.assertEqual(["子任务"], calls)
        self.assertEqual(run_report.ENDED_DONE, run_report.load(task.batch_label)["ended"])


class SingleTaskTest(unittest.TestCase):
    def _task(self, alone=True):
        class Task(BaseBD2Task):
            start_from_home = True

            def __init__(self):
                self._action_interval_lock = None  # as BaseBD2Task.__init__ sets
                self.ran = 0
                self.went_home = 0
                self._executor = SimpleNamespace(current_task=self if alone else object())

            def run(self):
                self.ran += 1
                return True

            def _go_home_before_run(self):
                self.went_home += 1

            def info_set(self, key, value):
                self.info[key] = value

            def log_warning(self, message, notify=False):
                pass

        task = Task()
        task.info = {}
        return task

    def test_traditional_game_does_not_start_a_task_run_alone(self):
        task = self._task()
        with mock.patch.object(setup_check, "look", lambda _task: setup_check.LANGUAGE_NOTICE):
            self.assertFalse(task.run())
        self.assertEqual((0, 0), (task.ran, task.went_home))

    def test_a_clear_look_runs_it(self):
        task = self._task()
        with mock.patch.object(setup_check, "look", lambda _task: ""):
            self.assertTrue(task.run())
        self.assertEqual((1, 1), (task.ran, task.went_home))

    def test_unreadable_account_list_starts_no_task_not_even_a_batch_item(self):
        for alone in (True, False):
            task = self._task(alone=alone)
            with mock.patch.object(accounts, "unreadable", return_value=accounts.BUSY):
                self.assertFalse(task.run())
            self.assertEqual((0, 0), (task.ran, task.went_home))
            notice = setup_check.ACCOUNTS_TEXTS[accounts.BUSY][1]
            self.assertEqual(notice, task.info[run_history.NOT_STARTED_KEY])

    def test_an_item_of_the_batch_does_not_look_again(self):
        task = self._task(alone=False)
        looked = []
        with mock.patch.object(setup_check, "look", lambda t: looked.append(t) or "x"):
            self.assertTrue(task.run())
        self.assertEqual([], looked)


class RecordTest(unittest.TestCase):
    def test_the_problem_record_says_it_did_not_start(self):
        task = SimpleNamespace(name="每周跑图", executor=None)
        with mock.patch.object(problem_report, "_save", lambda record: None):
            problem_report.begin(task)
            record = problem_report.end(task, problem_report.SETUP)
        self.assertEqual(problem_report.SETUP, record["ended"])
        self.assertIsNone(record["problem"])
        self.assertNotIn(problem_report.SETUP, problem_report.PROBLEM_ENDS)

    def test_a_run_that_did_not_start_leaves_no_history_or_backoff(self):
        run_history.install_run_history_recorder()
        recorder = run_history.install_run_history_recorder._recorder
        store = mock.Mock()
        schedule = mock.Mock()
        task = SimpleNamespace(name="每周跑图", info={run_history.NOT_STARTED_KEY: "x"})
        with (
            mock.patch.object(run_history, "default_store", return_value=store),
            mock.patch("src.tasks.scheduler.default_store", return_value=schedule),
        ):
            recorder.on_task_done(task)
            store.record_task_done.assert_not_called()
            schedule.delay_after_run.assert_not_called()
            task.info = {}
            recorder.on_task_done(task)
            store.record_task_done.assert_called_once()


if __name__ == "__main__":
    unittest.main()
