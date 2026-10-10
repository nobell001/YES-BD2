"""问题摘要 keeps a few small frames of the seconds before a problem
(差異化點子 8, Leo 2026-10-10 「做8」)."""

import logging
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication

from src.tasks import problem_report
from src.ui.shell import problem_image
from tests.test_problem_report import Task


def frame(shade, width=3840, height=2160):
    return np.full((height, width, 3), shade, dtype=np.uint8)


class BeforeFramesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        problem_report.set_root(self.folder.name)
        problem_report.install_log_ring()
        self.log = logging.getLogger("ok")

    def tearDown(self):
        self.log.removeHandler(problem_report._ring)
        problem_report._ring = None
        problem_report._drop()
        problem_report._last_written.clear()
        problem_report.set_root(None)
        self.folder.cleanup()

    def kept(self):
        return [(at, small.shape) for at, small in problem_report._before]

    def test_one_small_frame_per_gap_and_only_the_last_five(self):
        problem_report.begin(Task())
        start = 1000.0
        for step in range(30):  # a frame every half second for 15 s
            problem_report.note_frame(frame(step), now=start + step * 0.5)
        kept = self.kept()
        self.assertEqual(problem_report.BEFORE_FRAMES, len(kept))
        self.assertEqual([1006.0, 1008.0, 1010.0, 1012.0, 1014.0], [at for at, _ in kept])
        # 3840 wide shrinks to 480, in the game's shape, without the alpha.
        self.assertEqual((270, 480, 3), kept[0][1])

    def test_nothing_is_kept_outside_a_run(self):
        problem_report.note_frame(frame(1), now=1000.0)
        self.assertEqual([], self.kept())
        problem_report.begin(Task())
        problem_report.note_frame(frame(1, 1920, 1080), now=1000.0)
        problem_report._drop()
        self.assertEqual([], self.kept())

    def test_a_new_run_starts_without_the_last_runs_frames(self):
        problem_report.begin(Task())
        problem_report.note_frame(frame(1, 1920, 1080), now=1000.0)
        problem_report.begin(Task())
        self.assertEqual([], self.kept())

    def test_a_failure_saves_them_oldest_first(self):
        task = Task(stage="找卡带")
        with problem_report.run_scope(task) as scope:
            now = time.time()
            for back in (8, 6, 4, 2, 0.2):
                problem_report.note_frame(frame(int(back * 10), 2560, 1440), now=now - back)
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        before = record["problem"]["before"]
        # The one 0.2 s before is the problem's own frame, not a second copy.
        self.assertEqual(4, len(before))
        self.assertEqual(sorted(item["at"] for item in before), [item["at"] for item in before])
        paths = [item["path"] for item in record["before_paths"]]
        self.assertTrue(all(Path(path).is_file() for path in paths))
        self.assertTrue(all(path.endswith(f"-b{i}.jpg") for i, path in enumerate(paths, 1)))
        self.assertEqual((270, 480), cv2.imread(paths[0]).shape[:2])
        self.assertTrue(Path(record["frame_path"]).is_file())
        # Small: the five together stay far under 1 MB.
        self.assertLess(sum(Path(path).stat().st_size for path in paths), 1_000_000)
        # Kept no longer than the run.
        self.assertEqual([], self.kept())

    def test_stop_pressed_by_the_player_keeps_no_seconds_before(self):
        task = Task()
        with self.assertRaises(problem_report_stop()):
            with problem_report.run_scope(task):
                problem_report.note_frame(frame(1, 1920, 1080), now=time.time() - 3)
                raise problem_report_stop()()
        [record] = problem_report.records()
        self.assertEqual("stopped", record["ended"])
        self.assertNotIn("before", record["problem"])
        self.assertNotIn("before_paths", record)

    def test_a_good_run_keeps_no_frames(self):
        task = Task()
        with problem_report.run_scope(task) as scope:
            problem_report.note_frame(frame(1, 1920, 1080), now=time.time() - 3)
            scope.result = True
        [record] = problem_report.records()
        self.assertNotIn("before_paths", record)
        self.assertEqual([], list(Path(self.folder.name).glob("*/*.jpg")))

    def test_a_quick_repeat_removes_its_own_frames(self):
        task = Task(stage="找卡带")
        for _ in range(3):
            with problem_report.run_scope(task) as scope:
                problem_report.note_frame(frame(1, 1920, 1080), now=time.time() - 3)
                problem_report.note_problem(task, "fail")
                scope.result = False
        self.assertEqual(1, len(problem_report.records()))
        # The first run's frame and one before-frame; the repeats' went.
        self.assertEqual(2, len(list(Path(self.folder.name).glob("*/*.jpg"))))

    def test_frames_the_executor_waits_for_are_noted(self):
        import threading
        from types import SimpleNamespace

        from ok.task.TaskExecutor import TaskExecutor

        problem_report.install_log_ring()  # twice: wrapped once
        self.assertTrue(getattr(TaskExecutor.next_frame, problem_report._WATCH_MARKER, False))
        self.assertFalse(
            getattr(TaskExecutor.next_frame.__wrapped__, problem_report._WATCH_MARKER, False)
        )
        shown = frame(3, 1920, 1080)
        executor = object.__new__(TaskExecutor)
        executor.reset_scene = lambda *args, **kwargs: None
        executor.exit_event = threading.Event()
        executor.check_enabled = lambda *args, **kwargs: None
        executor.can_capture = lambda: True
        executor.device_manager = SimpleNamespace(
            capture_method=SimpleNamespace(get_frame=lambda: shown)
        )
        executor.blur_overlay_processor = None
        self.assertIs(shown, executor.next_frame())
        self.assertEqual([], self.kept())  # no run: nothing kept
        problem_report.begin(Task())
        self.assertIs(shown, executor.next_frame())
        self.assertEqual([(270, 480, 3)], [shape for _at, shape in self.kept()])


def problem_report_stop():
    from ok.task.exceptions import TaskDisabledException

    return TaskDisabledException


class StripPictureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_the_seconds_before_add_one_row_of_small_frames(self):
        from tests.test_problem_image import FINISHED, record

        with tempfile.TemporaryDirectory() as folder:
            before = []
            for index, back in enumerate((8, 6, 4, 2), start=1):
                path = Path(folder) / f"x-b{index}.jpg"
                cv2.imwrite(str(path), np.full((270, 480, 3), 30 * index, dtype=np.uint8))
                before.append({"at": FINISHED - back, "path": str(path)})
            plain = problem_image.render(record())
            strip = problem_image.render(record(before_paths=before))
            missing = problem_image.render(
                record(before_paths=[{"at": FINISHED - 2, "path": str(Path(folder) / "gone.jpg")}])
            )
        added = (strip.height() - plain.height()) / problem_image.SCALE
        # One row: a title, frames about 80 tall, the 「N 秒前」 under them.
        self.assertGreater(added, 100)
        self.assertLess(added, 220)
        self.assertEqual(plain.height(), missing.height())


if __name__ == "__main__":
    unittest.main()
