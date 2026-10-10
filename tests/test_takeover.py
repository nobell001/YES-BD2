"""A real click or key press on the game stops the running task."""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks import takeover
from src.tasks.takeover import (
    LLKHF_ALTDOWN,
    LLKHF_INJECTED,
    LLMHF_INJECTED,
    TakeoverMonitor,
    key_takeover,
    mouse_takeover,
)

LBUTTONDOWN, MOUSEMOVE, KEYDOWN, KEYUP = 0x0201, 0x0200, 0x0100, 0x0101
SYSKEYDOWN, VK_F4 = 0x0104, 0x73


class RulesTest(unittest.TestCase):
    def test_real_click_on_the_game(self):
        self.assertTrue(mouse_takeover(LBUTTONDOWN, 0, True, game_in_front=True))

    def test_a_click_that_only_brings_the_game_forward(self):
        self.assertFalse(mouse_takeover(LBUTTONDOWN, 0, True, game_in_front=False))

    def test_our_own_drag_is_injected(self):
        self.assertFalse(mouse_takeover(LBUTTONDOWN, LLMHF_INJECTED, True, game_in_front=True))

    def test_clicks_elsewhere_and_plain_moves_are_ignored(self):
        self.assertFalse(mouse_takeover(LBUTTONDOWN, 0, False, game_in_front=True))
        self.assertFalse(mouse_takeover(MOUSEMOVE, 0, True, game_in_front=True))

    def test_keys(self):
        self.assertTrue(key_takeover(KEYDOWN, 0, ord("W"), game_in_front=True))
        self.assertFalse(key_takeover(KEYDOWN, LLKHF_INJECTED, ord("W"), game_in_front=True))
        self.assertFalse(key_takeover(KEYDOWN, 0, 0x78, game_in_front=True))  # F9 start/stop
        self.assertFalse(key_takeover(KEYDOWN, 0, ord("W"), game_in_front=False))
        self.assertFalse(key_takeover(KEYUP, 0, ord("W"), game_in_front=True))
        # Live 2026-10-07: a PrintScreen for a bug report stopped the run.
        self.assertFalse(key_takeover(KEYDOWN, 0, 0x2C, game_in_front=True))

    def test_alt_f4_on_the_game_is_the_player_closing_it(self):
        # decision 9 of the 10-10 plan, its default: not a 闪退 to reopen.
        self.assertTrue(key_takeover(SYSKEYDOWN, LLKHF_ALTDOWN, VK_F4, game_in_front=True))
        self.assertFalse(key_takeover(KEYDOWN, 0, VK_F4, game_in_front=True))
        self.assertFalse(
            key_takeover(SYSKEYDOWN, LLKHF_ALTDOWN | LLKHF_INJECTED, VK_F4, game_in_front=True)
        )
        self.assertFalse(key_takeover(SYSKEYDOWN, LLKHF_ALTDOWN, VK_F4, game_in_front=False))


class MonitorTest(unittest.TestCase):
    def _monitor(self, running=True, trigger=False):
        task = SimpleNamespace(name="一键完成日常", log_warning=mock.Mock())
        executor = SimpleNamespace(
            current_task=task if running else None,
            onetime_tasks=[] if trigger else [task],
            interaction=SimpleNamespace(
                hwnd_window=SimpleNamespace(hwnd=100, top_hwnd=100, hwnds=[])
            ),
        )
        executor.stop_current_task = mock.Mock()
        monitor = TakeoverMonitor(executor)
        # Run the stop inline instead of on a helper thread.
        monitor._take_over = lambda task, source: (
            setattr(monitor, "_stopped_task", task) or monitor._stop(task, source)
        )
        return monitor, executor, task

    def _click(self, monitor, hwnd, flags=0, front=100):
        data = SimpleNamespace(flags=flags, pt=SimpleNamespace(x=10, y=10))
        with (
            mock.patch("win32gui.WindowFromPoint", return_value=hwnd),
            mock.patch("win32gui.GetForegroundWindow", return_value=front),
            mock.patch("win32gui.GetAncestor", side_effect=lambda h, _flag: h),
        ):
            self.assertIs(False, monitor.on_mouse(LBUTTONDOWN, data))

    def test_click_on_the_game_stops_the_task_once(self):
        monitor, executor, task = self._monitor()
        self._click(monitor, 100)
        self._click(monitor, 100)
        executor.stop_current_task.assert_called_once()
        self.assertIn("已自动停止", task.log_warning.call_args[0][0])

    def test_click_on_another_window_does_nothing(self):
        monitor, executor, _task = self._monitor()
        self._click(monitor, 555)
        executor.stop_current_task.assert_not_called()

    def test_clicking_the_game_to_focus_it_does_nothing(self):
        monitor, executor, _task = self._monitor()
        self._click(monitor, 100, front=555)
        executor.stop_current_task.assert_not_called()

    def test_idle_or_auto_login_is_never_stopped(self):
        for running, trigger in ((False, False), (True, True)):
            monitor, executor, _task = self._monitor(running=running, trigger=trigger)
            self._click(monitor, 100)
            executor.stop_current_task.assert_not_called()

    def _key(self, monitor, vk=0x27):
        data = SimpleNamespace(flags=0, vkCode=vk)
        with (
            mock.patch("win32gui.GetForegroundWindow", return_value=100),
            mock.patch("win32gui.GetAncestor", side_effect=lambda h, _flag: h),
        ):
            self.assertIs(False, monitor.on_key(KEYDOWN, data))

    def test_a_key_on_the_game_stops_the_task(self):
        monitor, executor, _task = self._monitor()
        monitor.in_clone = False
        self._key(monitor)
        executor.stop_current_task.assert_called_once()

    def test_input_on_the_clone_never_stops_the_run(self):
        # Live 2026-10-07: Right arrow and PrintScreen reached the 桌面分身
        # through its viewer and stopped 一键完成日常 twice.
        monitor, executor, _task = self._monitor()
        monitor.in_clone = True
        self._key(monitor)
        self._click(monitor, 100)
        executor.stop_current_task.assert_not_called()

    def test_a_new_run_is_watched_again(self):
        monitor, executor, task = self._monitor()
        self._click(monitor, 100)
        task.running = True
        monitor.on_task(task)  # the same task started again
        self._click(monitor, 100)
        self.assertEqual(2, executor.stop_current_task.call_count)


class PausedRunTest(unittest.TestCase):
    """The plan's default for decision 8: 暂停 is there so the player can
    step in; a click on the paused game marks the run instead of stopping it."""

    def _monitor(self):
        monitor, executor, task = MonitorTest._monitor(self)
        del monitor._take_over  # the real one: a paused run is never stopped
        monitor.in_clone = False
        task.paused = True
        return monitor, executor, task

    def test_a_click_on_the_paused_game_does_not_stop_it(self):
        monitor, executor, task = self._monitor()
        MonitorTest._click(self, monitor, 100)
        executor.stop_current_task.assert_not_called()
        task.log_warning.assert_not_called()
        self.assertTrue(task.player_stepped_in)

    def test_the_click_that_brings_the_paused_game_forward_counts(self):
        monitor, _executor, task = self._monitor()
        MonitorTest._click(self, monitor, 100, front=555)
        self.assertTrue(task.player_stepped_in)

    def test_a_key_on_the_paused_game_does_not_stop_it(self):
        monitor, executor, task = self._monitor()
        MonitorTest._key(self, monitor)
        executor.stop_current_task.assert_not_called()
        self.assertTrue(task.player_stepped_in)

    def test_a_click_elsewhere_while_paused_is_nothing(self):
        monitor, _executor, task = self._monitor()
        MonitorTest._click(self, monitor, 555)
        self.assertFalse(getattr(task, "player_stepped_in", False))

    def test_after_continue_a_click_stops_as_before(self):
        monitor, executor, task = self._monitor()
        task.paused = False
        inline = lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args))  # noqa: E731
        with mock.patch.object(takeover.threading, "Thread", inline):
            MonitorTest._click(self, monitor, 100)
        executor.stop_current_task.assert_called_once()


class InstallTest(unittest.TestCase):
    def test_nothing_starts_without_a_running_app(self):
        # Unit tests import the config (which installs the monitor); with no
        # executor the hooks must not start.
        on_task = getattr(takeover.install_takeover_monitor, "_on_task", None)
        state = getattr(takeover.install_takeover_monitor, "_state", None)
        if on_task is None or state["monitor"] is not None:
            self.skipTest("monitor not installed in this process")
        with mock.patch.object(TakeoverMonitor, "start") as start:
            on_task(SimpleNamespace(running=True))
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
