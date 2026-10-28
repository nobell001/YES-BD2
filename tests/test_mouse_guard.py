"""The player's mouse held while the tool moves the real cursor, not the
whole input (Leo's 4K 2026-10-28 16:29: 「按好幾次才有反應」「你不應該鎖住暫停
最少要給一點反饋」): the status bar's buttons and F9 keep working."""

import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from src.interaction.BD2Interaction import BD2Interaction
from src.tasks import takeover
from src.utils import game_status_bar, mouse_guard

LBUTTONDOWN, LBUTTONUP, MOUSEMOVE = 0x0201, 0x0202, 0x0200
BAR = 900
PAUSE_RECT = (300, 60, 340, 80)


class _Suppressed(Exception):
    pass


def _reset():
    mouse_guard.set_hooked(False)
    while mouse_guard.active():
        mouse_guard.stop()
    game_status_bar.unregister(BAR)
    game_status_bar.set_press_handler(None)


class GuardTest(unittest.TestCase):
    def setUp(self):
        _reset()
        self.addCleanup(_reset)

    def test_without_the_hook_nothing_is_held(self):
        self.assertFalse(mouse_guard.start((1, 2)))
        self.assertFalse(mouse_guard.active())

    def test_nested_holds_end_with_the_outer_one(self):
        mouse_guard.set_hooked(True)
        self.assertTrue(mouse_guard.start((5, 6)))
        self.assertTrue(mouse_guard.start((7, 8)))
        self.assertEqual((5, 6), mouse_guard.player_point())  # where the player left it
        mouse_guard.stop()
        self.assertTrue(mouse_guard.active())
        mouse_guard.stop()
        self.assertFalse(mouse_guard.active())

    def test_a_hold_never_stuck_on(self):
        mouse_guard.set_hooked(True)
        mouse_guard.start((1, 1))
        with mock.patch.object(mouse_guard.time, "monotonic", return_value=10**9):
            self.assertFalse(mouse_guard.active())


class InteractionTest(unittest.TestCase):
    def setUp(self):
        _reset()
        self.addCleanup(_reset)

    def interaction(self):
        interaction = object.__new__(BD2Interaction)
        interaction._input_lock = threading.RLock()
        interaction._operating = False
        interaction.cursor_position = (320, 70)
        interaction.user32 = mock.Mock()
        interaction._restore_cursor = lambda: None
        return interaction

    def test_with_the_hook_only_the_mouse_is_held(self):
        mouse_guard.set_hooked(True)
        interaction = self.interaction()
        seen = []
        with mock.patch("src.interaction.BD2Interaction.GetCursorPos", return_value=(320, 70)):
            interaction.operate(lambda: seen.append(mouse_guard.active()), block=True)
        self.assertEqual([True], seen)
        self.assertFalse(mouse_guard.active())
        interaction.user32.BlockInput.assert_not_called()

    def test_without_it_blockinput_as_before(self):
        interaction = self.interaction()
        with mock.patch("src.interaction.BD2Interaction.GetCursorPos", return_value=(1, 1)):
            interaction.operate(lambda: None, block=True)
        self.assertEqual(
            [mock.call(True), mock.call(False)], interaction.user32.BlockInput.call_args_list
        )


class HookTest(unittest.TestCase):
    def setUp(self):
        _reset()
        self.addCleanup(_reset)
        mouse_guard.set_hooked(True)
        game_status_bar.register(BAR)
        game_status_bar.set_buttons(BAR, [PAUSE_RECT], ["pause"])
        self.pressed = []
        game_status_bar.set_press_handler(self.pressed.append)
        task = SimpleNamespace(name="塔洛斯战术教材", paused=False, log_warning=mock.Mock())
        self.executor = SimpleNamespace(
            current_task=task,
            onetime_tasks=[task],
            interaction=SimpleNamespace(
                hwnd_window=SimpleNamespace(hwnd=100, top_hwnd=100, hwnds=[])
            ),
            stop_current_task=mock.Mock(),
        )
        self.monitor = takeover.TakeoverMonitor(self.executor)
        self.monitor.in_clone = False
        self.monitor._listeners = [SimpleNamespace(suppress_event=self._suppress)]

    @staticmethod
    def _suppress():
        raise _Suppressed()

    def send(self, msg, point, flags=0):
        """True when the event was kept off the game."""
        data = SimpleNamespace(flags=flags, pt=SimpleNamespace(x=point[0], y=point[1]))
        with (
            mock.patch("win32gui.WindowFromPoint", return_value=100),
            mock.patch("win32gui.GetForegroundWindow", return_value=100),
            mock.patch("win32gui.GetAncestor", side_effect=lambda h, _flag: h),
        ):
            try:
                self.monitor.on_mouse(msg, data)
            except _Suppressed:
                return True
        return False

    def test_pause_pressed_while_the_tool_drags_is_pressed(self):
        mouse_guard.start((320, 70))  # the player's cursor on 暂停
        # the press arrives where the tool has the cursor now: on the game
        self.assertTrue(self.send(MOUSEMOVE, (900, 500)))
        self.assertTrue(self.send(LBUTTONDOWN, (900, 500)))
        mouse_guard.stop()
        self.assertTrue(self.send(LBUTTONUP, (320, 70)))  # its up goes nowhere either
        self.assertEqual(["pause"], self.pressed)
        self.executor.stop_current_task.assert_not_called()

    def test_a_press_elsewhere_while_the_tool_drags_is_kept_off_the_game(self):
        mouse_guard.start((1000, 900))
        self.assertTrue(self.send(LBUTTONDOWN, (900, 500)))
        mouse_guard.stop()
        self.assertEqual([], self.pressed)
        self.executor.stop_current_task.assert_not_called()

    def test_the_tools_own_drag_goes_through(self):
        mouse_guard.start((320, 70))
        self.assertFalse(self.send(LBUTTONDOWN, (900, 500), flags=takeover.LLMHF_INJECTED))
        self.assertEqual([], self.pressed)

    def test_a_quick_press_before_the_button_woke_up(self):
        self.assertTrue(self.send(LBUTTONDOWN, (320, 70)))
        self.assertTrue(self.send(LBUTTONUP, (320, 70)))
        self.assertEqual(["pause"], self.pressed)
        self.executor.stop_current_task.assert_not_called()

    def test_a_button_taking_clicks_gets_it_itself(self):
        with mock.patch.object(game_status_bar, "_set_click_through"):
            game_status_bar.set_live(BAR, [PAUSE_RECT])
        self.assertFalse(self.send(LBUTTONDOWN, (320, 70)))
        self.assertEqual([], self.pressed)  # the bar's own mousePressEvent presses it


class RelayTest(unittest.TestCase):
    def setUp(self):
        _reset()
        self.addCleanup(_reset)

    def test_the_hooks_press_reaches_the_bars_button(self):
        from PySide6.QtWidgets import QApplication

        from src.ui.shell import game_status

        app = QApplication.instance() or QApplication([])
        presses = []
        bar = game_status.StatusBar(presses.append)
        self.addCleanup(bar.deleteLater)
        with mock.patch.object(bar, "isVisible", return_value=True):
            game_status_bar.press("pause")
            app.processEvents()
        self.assertEqual(["pause"], presses)


if __name__ == "__main__":
    unittest.main()
