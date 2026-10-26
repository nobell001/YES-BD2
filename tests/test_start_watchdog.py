"""The start dialog no longer sits on 「加载中」 (YES-BD2 #56, 2026-10-26).

The player's game was open at TOUCH TO START and connected, yet ok's
「正在启动，N 秒后超时」 never ended.  A step that does not return is logged
with where it was, and the run starts anyway when the game is connected;
timeouts wait one more round first and say what they waited for.
"""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.compat import start_watchdog as watchdog
from src.tasks.trigger.AutoLoginTask import AutoLoginTask
from src.utils import wait_settings


class _Signal:
    def __init__(self, name, log):
        self.name = name
        self.log = log

    def emit(self, *args):
        self.log.append((self.name, args))


class _Bus:
    def __init__(self):
        self.log = []
        self.starting_emulator = _Signal("starting", self.log)
        self.notification = _Signal("notification", self.log)

    def emitted(self, name):
        return [args for signal, args in self.log if signal == name]


class _Controller:
    def __init__(self, start_timeout=180):
        self.start_timeout = start_timeout
        self.exit_event = threading.Event()


def _wait_for(condition, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


class _WatchdogCase(unittest.TestCase):
    def setUp(self):
        self.bus = _Bus()
        self.signals = watchdog._StartSignals(self.bus)
        patches = [
            mock.patch.object(watchdog, "_real_communicate", lambda: self.bus),
            mock.patch.object(watchdog, "POLL_SECONDS", 0.02),
            mock.patch.dict(watchdog.STEP_LIMIT_SECONDS, {watchdog.STEP_GPU: 0.2}),
            mock.patch.object(wait_settings, "get", lambda setting: self.settings[setting]),
        ]
        self.settings = {
            wait_settings.START_TIMEOUT: 180,
            wait_settings.START_RETRIES: 1,
        }
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)


class StuckStepTest(_WatchdogCase):
    def _run_stuck(self, ready):
        release = threading.Event()
        self.addCleanup(release.set)
        stuck = watchdog._step(watchdog.STEP_GPU, lambda: release.wait(5))
        started = []

        def do_start(controller, task, exit_after):
            stuck()
            self.signals.starting_emulator.emit(True, None, 0)  # after it returns
            return True

        controller = _Controller()
        with (
            mock.patch.object(watchdog, "_game_ready", lambda: ready),
            mock.patch.object(watchdog, "_start_without_waiting", started.append),
        ):
            thread = threading.Thread(
                target=watchdog._wrap_do_start(do_start), args=(controller, "task", False)
            )
            thread.start()
            self.assertTrue(_wait_for(lambda: self.bus.emitted("starting")))
            release.set()
            thread.join(3)
        return controller, started

    def test_a_stuck_step_with_the_game_connected_starts_the_run(self):
        controller, started = self._run_stuck(ready=True)
        self.assertEqual([(True, None, 0)], self.bus.emitted("starting"))
        self.assertEqual(1, len(started))
        self.assertEqual("task", started[0].task)
        ((message, title, *_rest),) = self.bus.emitted("notification")
        self.assertIn("「检查显卡滤镜设定」卡了", message)
        self.assertIn("直接开始跑", message)
        # The stuck step returned later: its own done is not shown again.
        self.assertTrue(controller._ok_bd2_start_run.finished)

    def test_a_stuck_step_without_the_game_says_where_it_stuck(self):
        _controller, started = self._run_stuck(ready=False)
        self.assertEqual([], started)
        ((done, error, _seconds),) = self.bus.emitted("starting")
        self.assertTrue(done)
        self.assertIn("「检查显卡滤镜设定」卡了", error)
        self.assertIn("游戏也还没连上", error)
        self.assertIn("ok-bd2.log", error)

    def test_a_stuck_task_start_is_not_started_again(self):
        with mock.patch.dict(watchdog.STEP_LIMIT_SECONDS, {watchdog.STEP_EXECUTOR: 0.2}):
            release = threading.Event()
            self.addCleanup(release.set)
            stuck = watchdog._step(watchdog.STEP_EXECUTOR, lambda: release.wait(5))
            ready = mock.Mock(return_value=True)
            with mock.patch.object(watchdog, "_game_ready", ready):
                thread = threading.Thread(
                    target=watchdog._wrap_do_start(lambda *_a: stuck()),
                    args=(_Controller(), None, False),
                )
                thread.start()
                self.assertTrue(_wait_for(lambda: self.bus.emitted("starting")))
                release.set()
                thread.join(3)
        ready.assert_not_called()
        ((_done, error, _seconds),) = self.bus.emitted("starting")
        self.assertIn("任务没能开始执行", error)

    def test_a_step_that_returns_in_time_changes_nothing(self):
        quick = watchdog._step(watchdog.STEP_GPU, lambda: "ok")

        def do_start(controller, task, exit_after):
            self.assertEqual("ok", quick())
            self.signals.starting_emulator.emit(True, None, 0)
            return True

        controller = _Controller(start_timeout=120)
        self.settings[wait_settings.START_TIMEOUT] = 240
        self.assertTrue(watchdog._wrap_do_start(do_start)(controller, None, False))
        self.assertEqual([(True, None, 0)], self.bus.emitted("starting"))
        self.assertEqual(240, controller.start_timeout)  # the player's value

    def test_outside_a_start_the_steps_pass_straight_through(self):
        self.assertEqual(3, watchdog._step(watchdog.STEP_GPU, lambda: 3)())
        self.signals.starting_emulator.emit(True, "x", 0)
        self.assertEqual([(True, "x", 0)], self.bus.emitted("starting"))


class TimeoutTest(_WatchdogCase):
    def _device(self, timeouts):
        """start_device whose wait times out ``timeouts`` times, then is ready."""
        calls = []
        wait = watchdog._step(watchdog.STEP_READY, lambda: None)

        def start_device(controller, initial_refresh_done=False):
            calls.append(initial_refresh_done)
            if len(calls) <= timeouts:

                def timed_out():
                    self.signals.starting_emulator.emit(True, "Start game timeout!", 0)

                watchdog._step(watchdog.STEP_READY, timed_out)()
                return False
            wait()
            self.signals.starting_emulator.emit(True, None, 0)
            return True

        return start_device, calls

    def _call(self, start_device, again=None):
        controller = _Controller()
        run = watchdog.StartRun(controller, None, False)
        run.last_reason = "BrownDust II 没有连上"
        with watchdog._runs_lock:
            watchdog._runs[run.thread_ident] = run
        self.addCleanup(watchdog._runs.pop, run.thread_ident, None)
        again = again or (lambda c, original: original(c, False))
        with mock.patch.object(watchdog, "_wait_again", again):
            return watchdog._wrap_start_device(start_device)(controller, initial_refresh_done=True)

    def test_a_timeout_waits_one_more_round_before_saying_so(self):
        start_device, calls = self._device(timeouts=1)
        self.assertTrue(self._call(start_device))
        self.assertEqual([True, False], calls)
        self.assertEqual([(False, None, 180), (True, None, 0)], self.bus.emitted("starting"))

    def test_the_last_timeout_says_how_long_and_what_it_waited_for(self):
        start_device, calls = self._device(timeouts=5)
        self.assertFalse(self._call(start_device))
        self.assertEqual(2, len(calls))  # 1 retry by default
        done, error, _ = self.bus.emitted("starting")[-1]
        self.assertTrue(done)
        self.assertIn("等了 180 秒", error)
        self.assertIn("游戏还是截不到画面（BrownDust II 没有连上）", error)
        self.assertIn("网络慢时的等待", error)
        self.assertNotIn("Start game timeout", error)

    def test_no_retries_when_the_player_set_none(self):
        self.settings[wait_settings.START_RETRIES] = 0
        start_device, calls = self._device(timeouts=1)
        self.assertFalse(self._call(start_device))
        self.assertEqual(1, len(calls))
        self.assertEqual(1, len(self.bus.emitted("starting")))

    def test_other_start_errors_are_shown_at_once(self):
        def start_device(controller, initial_refresh_done=False):
            self.signals.starting_emulator.emit(True, "Game path does not exist", 0)
            return False

        self.assertFalse(self._call(start_device))
        self.assertEqual([(True, "Game path does not exist", 0)], self.bus.emitted("starting"))

    def test_a_retry_does_not_open_a_running_game_again(self):
        opened = []
        controller = _Controller()
        controller._wait_until_started_window_stable = lambda: True
        controller._wait_until_device_ready = lambda: True
        og = SimpleNamespace(
            device_manager=SimpleNamespace(get_preferred_device=lambda: {"device": "windows"})
        )
        with (
            mock.patch("src.utils.game_process.game_running", lambda: True),
            mock.patch.object(watchdog, "import_module", lambda name: SimpleNamespace(og=og)),
        ):
            self.assertTrue(watchdog._wait_again(controller, lambda *a: opened.append(a)))
        self.assertEqual([], opened)
        self.assertEqual([(True, None, 0)], self.bus.emitted("starting"))

    def test_a_retry_opens_the_game_when_it_closed(self):
        opened = []
        with mock.patch("src.utils.game_process.game_running", lambda: False):
            watchdog._wait_again("controller", lambda *a: opened.append(a) or True)
        self.assertEqual([("controller", False)], opened)


class StartAgainTest(unittest.TestCase):
    def test_a_new_press_does_not_wait_behind_a_stuck_start(self):
        ran = threading.Event()
        controller = SimpleNamespace(
            _ok_bd2_start_run=SimpleNamespace(abandoned=True, finished=False),
            do_start=lambda task, exit_after: ran.set(),
            starting=False,
        )
        original = mock.Mock()
        watchdog._wrap_start(original)(controller, "task")
        self.assertTrue(ran.wait(2))
        original.assert_not_called()

    def test_a_normal_press_goes_through_ok(self):
        controller = SimpleNamespace(_ok_bd2_start_run=None)
        original = mock.Mock()
        watchdog._wrap_start(original)(controller, "task")
        original.assert_called_once_with(controller, "task", False)


class DialogGuardTest(unittest.TestCase):
    def test_done_closes_the_dialog_even_when_the_update_fails(self):
        dialog = mock.Mock()
        window = SimpleNamespace(emulator_starting_dialog=dialog)

        def fails(self, done, error, seconds_left):
            raise RuntimeError("switchTo failed")

        with mock.patch("ok.core.notifications.alert_error") as alert:
            watchdog._guard_dialog(fails)(window, True, "why", 0)
        dialog.close.assert_called_once()
        alert.assert_called_once_with("why", True)


class InstallTest(unittest.TestCase):
    def test_installed_once_on_ok_start_controller(self):
        from ok.core import start_controller

        watchdog.install_start_watchdog()
        wrapped = start_controller.StartController.do_start
        watchdog.install_start_watchdog()
        self.assertIs(wrapped, start_controller.StartController.do_start)
        self.assertIsInstance(start_controller.communicate, watchdog._StartSignals)
        self.assertTrue(callable(start_controller.StartController.try_capture_a_frame))


class WaitSettingsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patch = mock.patch.object(wait_settings, "SETTINGS_FILE", Path(folder.name) / "w.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_defaults_until_the_player_changes_them(self):
        self.assertEqual(180, wait_settings.get(wait_settings.START_TIMEOUT))
        self.assertIsNone(wait_settings.saved(wait_settings.LOGIN_HOME_WAIT))

    def test_saved_values_are_kept_within_range(self):
        wait_settings.set_values(
            {wait_settings.START_TIMEOUT: 9999, wait_settings.START_RETRIES: -3}
        )
        self.assertEqual(600, wait_settings.get(wait_settings.START_TIMEOUT))
        self.assertEqual(0, wait_settings.get(wait_settings.START_RETRIES))
        self.assertEqual(300, wait_settings.get(wait_settings.LOGIN_HOME_WAIT))

    def test_a_broken_file_reads_as_defaults(self):
        wait_settings.SETTINGS_FILE.write_text("{nope", encoding="utf-8")
        self.assertEqual(3, wait_settings.get(wait_settings.LOGIN_GIVE_UP))

    def test_login_waits_follow_the_player_setting(self):
        task = object.__new__(AutoLoginTask)
        task.config = {"登录后主页总等待秒数": 300.0}
        task._login_clicked_at = 0.0
        self.assertFalse(task._login_wait_timed_out(250.0))
        wait_settings.set_values({wait_settings.LOGIN_HOME_WAIT: 120})
        self.assertTrue(task._login_wait_timed_out(250.0))


class RealStartFlowTest(unittest.TestCase):
    """ok's own start flow, with a capture that never returns a frame."""

    def test_a_capture_that_hangs_still_starts_the_connected_game(self):
        from ok import og
        from ok.core import start_controller

        watchdog.install_start_watchdog()
        bus = _Bus()
        release = threading.Event()
        self.addCleanup(release.set)
        enabled = []
        executor = SimpleNamespace(
            current_task=None,
            get_all_tasks=lambda: [],
            start=mock.Mock(),
            feature_set=None,
        )
        capture = SimpleNamespace(connected=lambda: True, get_frame=lambda: release.wait(5))
        refreshes = []
        device_manager = SimpleNamespace(
            do_refresh=watchdog._step(watchdog.STEP_REFRESH, refreshes.append),
            get_preferred_device=lambda: {"connected": True, "device": "windows", "nick": "BD2"},
            capture_method=capture,
            device_connected=lambda: True,
        )
        task = SimpleNamespace(enabled=False, paused=False)
        controller = start_controller.StartController.__new__(start_controller.StartController)
        controller.config = {}
        controller.exit_event = threading.Event()
        controller.start_timeout = 180
        controller.start_exe = True
        controller.starting = False
        with (
            mock.patch.object(og, "executor", executor, create=True),
            mock.patch.object(og, "device_manager", device_manager, create=True),
            mock.patch.object(start_controller.communicate, "_real", bus),
            mock.patch.object(
                start_controller.communicate.starting_emulator, "_signal", bus.starting_emulator
            ),
            mock.patch.object(watchdog, "_real_communicate", lambda: bus),
            mock.patch.object(watchdog, "POLL_SECONDS", 0.02),
            mock.patch.dict(watchdog.STEP_LIMIT_SECONDS, {watchdog.STEP_CAPTURE: 0.3}),
            mock.patch.object(watchdog, "_game_ready", lambda: True),
            mock.patch.object(
                start_controller.StartController,
                "_mark_task_enabled",
                staticmethod(enabled.append),
            ),
        ):
            thread = threading.Thread(target=controller.do_start, args=(task,))
            thread.start()
            self.assertTrue(_wait_for(lambda: executor.start.called))
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())  # the stale start went no further
        executor.start.assert_called_once()
        self.assertEqual([task], enabled)
        starting = bus.emitted("starting")
        self.assertEqual((False, None, 180), starting[0])
        self.assertIn((True, None, 0), starting)
        ((message, *_rest),) = bus.emitted("notification")
        self.assertIn("「截一张游戏画面」卡了", message)


if __name__ == "__main__":
    unittest.main()
