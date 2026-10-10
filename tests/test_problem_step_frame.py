"""问题摘要 shows the step a task left for home, not the way home (下一批 #2,
the gap #142 left): most failures go home first and say why after."""

import logging
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks import problem_report, recovery
from tests.test_problem_report import Task


def frame(shade, width=1920, height=1080):
    return np.full((height, width, 3), shade, dtype=np.uint8)


class StepFrameTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        problem_report.set_root(self.folder.name)
        problem_report.install_log_ring()

    def tearDown(self):
        logging.getLogger("ok").removeHandler(problem_report._ring)
        problem_report._ring = None
        problem_report._drop()
        problem_report._last_written.clear()
        problem_report.set_root(None)
        self.folder.cleanup()

    def shade(self, path):
        return int(cv2.imread(path).mean())

    def fail(self, task, steps):
        task.executor._frame = frame(0)  # home, where it ended up
        with problem_report.run_scope(task) as scope:
            steps()
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        return record

    def test_the_failure_shows_the_step_it_left_for_home(self):
        task = Task("公会签到")
        left = time.time() - 10

        def steps():
            for back in (6, 4, 2):
                problem_report.note_frame(frame(100 + back, 640, 360), now=left - back)
            problem_report.note_leaving_step(task, frame(150), now=left)
            problem_report.note_frame(frame(10, 640, 360), now=left + 3)  # way home

        record = self.fail(task, steps)
        self.assertAlmostEqual(150, self.shade(record["frame_path"]), delta=2)
        self.assertEqual(left, record["problem"]["at"])
        self.assertEqual(
            [106, 104, 102], [round(self.shade(item["path"])) for item in record["before_paths"]]
        )

    def test_a_give_up_keeps_its_own_frame_through_its_trip_home(self):
        task = Task("快速狩猎")

        def steps():
            problem_report.note_give_up(task, frame(200))
            problem_report.note_leaving_step(task, frame(120))

        self.assertAlmostEqual(200, self.shade(self.fail(task, steps)["frame_path"]), delta=2)

    def test_a_retry_after_going_home_shows_the_second_try(self):
        task = Task("公会签到")

        def steps():
            problem_report.note_leaving_step(task, frame(120))
            problem_report.note_stage(task)  # 认不准就不按: again from 主城
            problem_report.note_leaving_step(task, frame(180))

        self.assertAlmostEqual(180, self.shade(self.fail(task, steps)["frame_path"]), delta=2)

    def test_going_on_after_a_trip_home_drops_it(self):
        task = Task("公会签到")
        task.executor._frame = frame(90)  # the later step it failed on

        def steps():
            problem_report.note_leaving_step(task, frame(120))
            problem_report.note_stage(task)

        with problem_report.run_scope(task) as scope:
            steps()
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        self.assertAlmostEqual(90, self.shade(record["frame_path"]), delta=2)

    def test_a_new_stage_keeps_a_give_up_not_yet_followed_home(self):
        task = Task("快速狩猎")

        def steps():
            problem_report.note_give_up(task, frame(200))
            problem_report.note_stage(task)

        self.assertAlmostEqual(200, self.shade(self.fail(task, steps)["frame_path"]), delta=2)

    def test_outside_a_run_nothing_is_kept(self):
        problem_report.note_leaving_step(Task(), frame(120))
        problem_report.note_stage(Task())
        self.assertIsNone(problem_report._current)


class RecoveryNotesTheStepTest(unittest.TestCase):
    def _recover(self, home_at_once):
        task = SimpleNamespace(
            name="公会签到", info_set=lambda *_a: None, log_info=lambda *_a: None
        )
        shown = frame(150)
        navigator = SimpleNamespace(
            vision=SimpleNamespace(capture=lambda: shown),
            classify=lambda *_a: recovery.ScreenState.HOME,
        )
        with (
            mock.patch.object(recovery, "Vision", lambda _task: navigator.vision),
            mock.patch.object(recovery, "Navigator", lambda _task, _vision: navigator),
            mock.patch.object(recovery, "_home_now", lambda _nav: home_at_once),
            mock.patch.object(problem_report, "note_leaving_step") as noted,
        ):
            self.assertTrue(recovery.recover_to_home(task))
        return noted, task, shown

    def test_leaving_a_page_notes_it_once(self):
        noted, task, shown = self._recover(home_at_once=False)
        noted.assert_called_once_with(task, shown)

    def test_already_home_notes_nothing(self):
        noted, _task, _shown = self._recover(home_at_once=True)
        noted.assert_not_called()


class StageNoteTest(unittest.TestCase):
    def test_only_a_new_stage_tells_the_record(self):
        from src.tasks import BaseBD2Task as base

        task = object.__new__(base.BaseBD2Task)
        with (
            mock.patch.object(problem_report, "note_stage") as noted,
            mock.patch.object(base.BaseTask, "info_set") as stored,
            mock.patch.object(base.BaseBD2Task, "_task_info_lock", lambda _self: mock.MagicMock()),
        ):
            task.info_set("当前阶段", "点击签到")
            task.info_set("状态", "公会签到失败：没有找到签到按钮。")
        noted.assert_called_once_with(task)
        self.assertEqual(2, stored.call_count)


if __name__ == "__main__":
    unittest.main()
