"""问题摘要 shows the screen a task gave up on, not the home page it went
back to afterwards (a player's 圣石洞穴 summary, 2026-10-10: 「用户发log档给
你了你就要明确能知道问题在哪」)."""

import logging
import tempfile
import threading
import time
import unittest

import cv2
import numpy as np

from src.tasks import problem_report
from tests.test_problem_report import Task


def frame(shade, width=1920, height=1080):
    return np.full((height, width, 3), shade, dtype=np.uint8)


class GiveUpFrameTest(unittest.TestCase):
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

    def test_the_failure_shows_the_screen_it_gave_up_on(self):
        task = Task("快速狩猎")
        task.executor._frame = frame(0)  # the home page it went back to
        with problem_report.run_scope(task) as scope:
            gave_up = time.time() - 10
            for back in (8, 6, 4, 2):
                problem_report.note_frame(frame(100 + back, 640, 360), now=gave_up - back)
            problem_report.note_give_up(task, frame(200, 3840, 2160), now=gave_up)
            # Going home afterwards: more frames, none of them the problem.
            problem_report.note_frame(frame(10, 640, 360), now=gave_up + 4)
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        self.assertAlmostEqual(200, self.shade(record["frame_path"]), delta=2)
        self.assertEqual((1080, 1920), cv2.imread(record["frame_path"]).shape[:2])
        self.assertEqual(gave_up, record["problem"]["at"])
        shades = [self.shade(item["path"]) for item in record["before_paths"]]
        self.assertEqual([108, 106, 104, 102], [round(s) for s in shades])

    def test_a_later_task_of_the_batch_does_not_show_an_earlier_give_up(self):
        batch, first, second = Task("一键完成日常"), Task("快速狩猎"), Task("镜中之战")
        second.executor = batch.executor
        batch.executor._frame = frame(30)
        with problem_report.run_scope(batch):
            with problem_report.run_scope(first):
                problem_report.note_give_up(first, frame(200))  # then it recovered
            with problem_report.run_scope(second):
                problem_report.note_problem(second, "fail")
        [record] = problem_report.records()
        self.assertEqual("镜中之战", record["problem"]["task"])
        self.assertAlmostEqual(30, self.shade(record["frame_path"]), delta=2)

    def test_the_same_task_run_again_starts_clean(self):
        batch, hunt = Task("一键完成日常"), Task("快速狩猎")
        hunt.executor = batch.executor
        batch.executor._frame = frame(30)
        with problem_report.run_scope(batch):
            with problem_report.run_scope(hunt):
                problem_report.note_give_up(hunt, frame(200))
            with problem_report.run_scope(hunt):
                problem_report.note_problem(hunt, "fail")
        [record] = problem_report.records()
        self.assertAlmostEqual(30, self.shade(record["frame_path"]), delta=2)

    def test_stop_shows_where_it_stopped(self):
        task = Task("快速狩猎")
        task.executor._frame = frame(30)
        with problem_report.run_scope(task):
            problem_report.note_give_up(task, frame(200))
            problem_report.note_problem(task, "stop")
        [record] = problem_report.records()
        self.assertAlmostEqual(30, self.shade(record["frame_path"]), delta=2)

    def test_another_threads_give_up_is_not_this_run(self):
        task = Task("快速狩猎")
        task.executor._frame = frame(30)
        with problem_report.run_scope(task) as scope:
            other = threading.Thread(
                target=problem_report.note_give_up, args=(Task("自动登录"), frame(200))
            )
            other.start()
            other.join()
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        self.assertAlmostEqual(30, self.shade(record["frame_path"]), delta=2)

    def test_the_flow_diagnostic_notes_the_give_up(self):
        from src.tasks.BaseBD2Task import BaseBD2Task

        task = object.__new__(BaseBD2Task)
        task.name = "快速狩猎"
        shown = frame(200)
        saved = []
        task.capture_frame = lambda: shown
        task.save_frame = lambda name, image: saved.append((name, image))
        problem_report.begin(task)
        task._save_flow_diagnostic("quick_hunt_crystal_entry_failed")
        self.assertEqual([("quick_hunt_crystal_entry_failed", shown)], saved)
        kept = problem_report._current["give_up"]
        self.assertEqual("快速狩猎", kept["task"])
        self.assertTrue(np.array_equal(shown, kept["frame"]))


if __name__ == "__main__":
    unittest.main()
