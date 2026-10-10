"""Daily and weekly runs fix a game size the tool was not tested on.

A player on 2026-10-09 ran the game in a 1467x824 window: 跑图 slid the
cartridge bar and clicked the map's back button for minutes on end.  Leo
first chose 「提醒但照跑」, then asked for it to be solved: a run sets the
game to 1920x1080 first and warns only when that cannot be done.
"""

import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks.BaseBD2Task import BaseBD2Task
from src.utils import game_size


def executor(width, height, connected=True):
    method = SimpleNamespace(width=width, height=height, connected=lambda: connected)
    window = SimpleNamespace(exists=True, width=width, height=height)
    manager = SimpleNamespace(capture_method=method, hwnd_window=window)
    return SimpleNamespace(device_manager=manager)


def resizes_to(found, size=(1920, 1080), reason=""):
    """A resize that changes ``found``'s picture to ``size`` and reports ``reason``."""
    calls = []

    def resize(target_executor):
        calls.append(target_executor)
        found.device_manager.capture_method.width = size[0]
        found.device_manager.capture_method.height = size[1]
        return reason

    resize.calls = calls
    return resize


def reset():
    game_size._last_notified["at"] = 0.0
    game_size._last_failed_fix.clear()
    game_size._last_failed_fix["at"] = 0.0


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Recorder:
    def __init__(self, found):
        self.executor = found
        self.info = {}
        self.infos = []
        self.warnings = []

    def info_set(self, key, value):
        self.info[key] = value

    def log_info(self, message, notify=False):
        self.infos.append((message, notify))

    def log_warning(self, message, notify=False):
        self.warnings.append((message, notify))


class GameSizeTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_supported_sizes(self):
        for size in ((1920, 1080), (2560, 1440), (3840, 2160), (1919, 1080), (3840, 2158)):
            with self.subTest(size=size):
                self.assertTrue(game_size.supported(*size))

    def test_other_16_9_sizes_are_not(self):
        for size in ((1280, 720), (1467, 824), (1600, 900), (1366, 768), (1920, 1050)):
            with self.subTest(size=size):
                self.assertFalse(game_size.supported(*size))

    def test_no_game_window_is_left_alone(self):
        self.assertIsNone(game_size.unsupported_size(None))
        manager = SimpleNamespace(
            capture_method=None, hwnd_window=SimpleNamespace(exists=False, width=0, height=0)
        )
        self.assertIsNone(game_size.unsupported_size(SimpleNamespace(device_manager=manager)))

    def test_capture_size_wins_over_window(self):
        found = executor(1920, 1080)
        found.device_manager.hwnd_window.width = 1464
        self.assertEqual((1920, 1080), game_size.current_size(found))
        found.device_manager.capture_method.connected = lambda: False
        self.assertEqual((1464, 1080), game_size.current_size(found))

    def test_notice_once_per_gap(self):
        self.assertTrue(game_size.should_notify(1000.0))
        self.assertFalse(game_size.should_notify(1100.0))
        self.assertTrue(game_size.should_notify(1000.0 + game_size.NOTIFY_GAP_SECONDS + 1))

    def test_supported_size_is_not_touched(self):
        found = executor(2560, 1440)
        resize = resizes_to(found)
        task = Recorder(found)
        self.assertFalse(game_size.fix_or_warn(task, resize=resize))
        self.assertEqual([], resize.calls)
        self.assertEqual({}, task.info)

    def test_untested_size_is_set_to_1920x1080(self):
        found = executor(1467, 824)
        resize = resizes_to(found)
        task = Recorder(found)
        clock = Clock()
        self.assertFalse(
            game_size.fix_or_warn(task, resize=resize, sleep=clock.sleep, monotonic=clock)
        )
        self.assertEqual([found], resize.calls)
        self.assertIn("1467×824", task.info[game_size.NOTICE_KEY])
        self.assertIn("已自动调成 1920×1080", task.info[game_size.NOTICE_KEY])
        self.assertEqual([True], [notify for _text, notify in task.infos])
        self.assertEqual([], task.warnings)

    def test_resize_refused_warns_with_the_reason(self):
        found = executor(1600, 900)
        reason = "当前显示器无法容纳 1920 × 1080 游戏客户区。"
        resize = resizes_to(found, size=(1600, 900), reason=reason)
        task = Recorder(found)
        clock = Clock()
        self.assertTrue(
            game_size.fix_or_warn(task, resize=resize, sleep=clock.sleep, monotonic=clock)
        )
        text = task.info[game_size.NOTICE_KEY]
        self.assertIn("1600×900", text)
        self.assertIn("无法容纳", text)
        self.assertIn("全屏", text)
        self.assertEqual([True], [notify for _text, notify in task.warnings])

    def test_resize_that_does_not_take_warns(self):
        found = executor(1467, 824)
        resize = resizes_to(found, size=(1467, 824))
        task = Recorder(found)
        clock = Clock()
        self.assertTrue(
            game_size.fix_or_warn(task, resize=resize, sleep=clock.sleep, monotonic=clock)
        )
        self.assertIn("调整后画面是 1467×824", task.info[game_size.NOTICE_KEY])
        # It waited for the picture to follow before giving up.
        self.assertGreaterEqual(clock.now, 1000.0 + game_size.FIX_SETTLE_SECONDS)

    def test_the_new_size_is_read_from_a_new_frame(self):
        # Audit #65: the capture kept the old size until a frame was taken.
        found = executor(1467, 824)
        method = found.device_manager.capture_method
        frames = []

        def get_frame():
            frames.append(1)
            method.width, method.height = window_now

        method.get_frame = get_frame
        window_now = (1467, 824)

        def resize(_executor):
            nonlocal window_now
            window_now = (1920, 1080)  # the window took it; the capture lags
            return ""

        task = Recorder(found)
        clock = Clock()
        self.assertFalse(
            game_size.fix_or_warn(task, resize=resize, sleep=clock.sleep, monotonic=clock)
        )
        self.assertTrue(frames)
        self.assertEqual([], task.warnings)
        self.assertLess(clock.now, 1000.0 + game_size.FIX_SETTLE_SECONDS)

    def test_failed_resize_is_not_retried_for_each_child(self):
        found = executor(1600, 900)
        resize = resizes_to(found, size=(1600, 900), reason="窗口无法容纳")
        clock = Clock()
        game_size.fix_or_warn(Recorder(found), resize=resize, sleep=clock.sleep, monotonic=clock)
        second = Recorder(found)
        clock.now += 60
        game_size.fix_or_warn(second, resize=resize, sleep=clock.sleep, monotonic=clock)
        self.assertEqual(1, len(resize.calls))
        self.assertEqual([False], [notify for _text, notify in second.warnings])
        clock.now += game_size.NOTIFY_GAP_SECONDS
        game_size.fix_or_warn(Recorder(found), resize=resize, sleep=clock.sleep, monotonic=clock)
        self.assertEqual(2, len(resize.calls))

    def test_resize_uses_the_home_page_resizer_without_the_running_check(self):
        resizer = mock.Mock()
        fake = SimpleNamespace(resize_game_window=resizer)
        found = executor(1467, 824)
        with mock.patch.dict(sys.modules, {"src.ui.manual_resolution": fake}):
            self.assertEqual("", game_size.resize_to_fix(found))
            resizer.side_effect = RuntimeError("游戏窗口已最小化，请先恢复窗口。")
            self.assertEqual("游戏窗口已最小化，请先恢复窗口。", game_size.resize_to_fix(found))
        resizer.assert_called_with(found.device_manager, (1920, 1080), executor=None)


class GuardedRunTest(unittest.TestCase):
    def setUp(self):
        reset()

    def _task(self, size, opt_in=True):
        class Task(BaseBD2Task):
            recover_home_on_failure = opt_in
            start_from_home = opt_in

            @property
            def executor(self):
                return self._executor

            def __init__(self):
                self._action_interval_lock = None
                self._executor = executor(*size)
                self.ran = 0
                self.home_calls = 0
                self.before_calls = 0
                self.info = {}
                self.warnings = []
                self.infos = []

            def run(self):
                self.ran += 1
                return True

            def info_set(self, key, value):
                self.info[key] = value

            def log_info(self, message, notify=False):
                self.infos.append((message, notify))

            def log_warning(self, message, notify=False):
                self.warnings.append((message, notify))

            def _leave_home_after_failed_run(self):
                self.home_calls += 1

            def _go_home_before_run(self):
                self.before_calls += 1

        return Task()

    def test_untested_size_is_fixed_before_the_run(self):
        task = self._task((1467, 824))
        resize = resizes_to(task.executor)
        with mock.patch.object(game_size, "resize_to_fix", resize):
            self.assertTrue(task.run())
        self.assertEqual(1, len(resize.calls))
        self.assertEqual(1, task.ran)
        self.assertEqual(1, task.before_calls)
        self.assertEqual(0, task.home_calls)
        self.assertEqual([], task.warnings)
        self.assertNotIn("状态", task.info)

    def test_unfixable_size_warns_and_still_runs(self):
        task = self._task((1366, 768))
        resize = resizes_to(task.executor, size=(1366, 768), reason="当前显示器无法容纳")
        with mock.patch.object(game_size, "resize_to_fix", resize):
            self.assertTrue(task.run())
        self.assertEqual(1, task.ran)
        self.assertEqual([True], [notify for _text, notify in task.warnings])

    def test_supported_size_runs_untouched(self):
        task = self._task((2560, 1440))
        resize = resizes_to(task.executor)
        with mock.patch.object(game_size, "resize_to_fix", resize):
            self.assertTrue(task.run())
        self.assertEqual([], resize.calls)
        self.assertEqual([], task.warnings)

    def test_trigger_tasks_are_untouched(self):
        # Auto-login and other trigger tasks must still run on any size.
        task = self._task((1280, 720), opt_in=False)
        resize = resizes_to(task.executor)
        with mock.patch.object(game_size, "resize_to_fix", resize):
            self.assertTrue(task.run())
        self.assertEqual([], resize.calls)
        self.assertEqual(1, task.ran)


class BatchTest(unittest.TestCase):
    def test_batch_fixes_the_size_once_then_runs_its_children(self):
        try:
            from src.tasks.DailyBatchTask import DailyBatchTask
        except ImportError as exc:  # pragma: no cover - Windows-only imports
            self.skipTest(str(exc))

        found = executor(1600, 900)

        class Batch(DailyBatchTask):
            executor = found

        batch = object.__new__(Batch)
        batch.config = {"启用": True}
        batch.info = {}
        batch.log_info = mock.Mock()
        batch.log_warning = mock.Mock()
        batch.info_set = lambda key, value: batch.info.__setitem__(key, value)
        batch._auto_login_pending = lambda: False
        batch._take_run_mode = lambda mode: mode
        batch._run_children = mock.Mock(return_value=True)
        batch._begin_report = mock.Mock()
        reset()
        resize = resizes_to(found)
        with (
            mock.patch.object(game_size, "resize_to_fix", resize),
            mock.patch("src.tasks.DailyBatchTask.run_report.finish"),
        ):
            self.assertTrue(batch.run())
        self.assertEqual(1, len(resize.calls))
        batch._run_children.assert_called_once()
        self.assertIn("已自动调成 1920×1080", batch.info[game_size.NOTICE_KEY])
        batch.log_warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
