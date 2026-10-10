"""The 快速狩猎 press only counts once its dialog is on screen.

A player's run (v0.1.17, 1080p, 2026-10-10) pressed 快速狩猎 at 狩猎场, then
found neither 「仅使用免费」 nor 「取消」 and stopped: the press had not opened
the dialog, and the log only said the switch was missing.
"""

import unittest
from unittest import mock

from src.tasks import quick_hunt


class OpenDialogTest(unittest.TestCase):
    def _task(self, button=(True,), dialog=(False,)):
        from src.tasks.QuickHuntTask import QuickHuntTask

        task = object.__new__(QuickHuntTask)
        task.config = {"快速狩猎界面等待秒数": 0.05}
        task.warnings, task.infos, task.clicks = [], [], []
        task.log_warning = lambda message, **k: task.warnings.append(message)
        task.log_info = lambda message, **k: task.infos.append(message)
        task._status_set = lambda *a: None
        task.sleep = lambda *a: None
        buttons, dialogs = iter(button), iter(dialog)
        task._quick_hunt_button_ready = lambda _stage: next(buttons, button[-1])
        task._quick_hunt_dialog_visible = lambda _stage: next(dialogs, dialog[-1])
        task._quick_hunt_click_ocr = lambda patterns, roi, timeout, name, **k: (
            task.clicks.append(name) or True
        )
        return task

    def setUp(self):
        patcher = mock.patch.object(quick_hunt, "QUICK_HUNT_DIALOG_DRAW_SECONDS", 0.05)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dialog_seen_after_one_press(self):
        task = self._task(dialog=(True,))
        self.assertTrue(task._quick_hunt_open_dialog("狩猎场"))
        self.assertEqual(["狩猎场-快速狩猎按钮"], task.clicks)
        self.assertEqual([], task.warnings)

    def test_lost_press_is_pressed_once_more(self):
        task = self._task()
        # The dialog only shows up after the second press.
        task._quick_hunt_dialog_visible = lambda _stage: len(task.clicks) >= 2
        self.assertTrue(task._quick_hunt_open_dialog("狩猎场"))
        self.assertEqual(2, len(task.clicks))
        self.assertEqual([], task.warnings)

    def test_dialog_never_opening_stops_without_a_third_press(self):
        task = self._task()
        task._quick_hunt_dialog_seen = lambda: "当时画面：所在地图「狩猎场」。"
        self.assertFalse(task._quick_hunt_open_dialog("狩猎场"))
        self.assertEqual(2, len(task.clicks))
        self.assertEqual(1, len(task.warnings))
        self.assertIn("没看到快速狩猎视窗", task.warnings[0])
        self.assertIn("所在地图「狩猎场」", task.warnings[0])

    def test_no_second_press_once_the_screen_moved_on(self):
        task = self._task(button=(True, False))
        task._quick_hunt_dialog_seen = lambda: ""
        self.assertFalse(task._quick_hunt_open_dialog("狩猎场"))
        self.assertEqual(1, len(task.clicks))

    def test_missing_button_is_not_pressed(self):
        task = self._task(button=(False,))
        self.assertFalse(task._quick_hunt_open_dialog("狩猎场"))
        self.assertEqual([], task.clicks)

    def test_dialog_not_opened_does_not_try_to_cancel(self):
        task = self._task()
        task._quick_hunt_open_dialog = lambda _stage: False
        task._quick_hunt_ensure_free_only = lambda _stage: self.fail("no dialog to check")
        task._quick_hunt_cancel_dialog = lambda _stage: self.fail("no dialog to cancel")
        self.assertEqual("failed", task._quick_hunt_execute_current_map("MAX", "狩猎场"))


class DialogVisibleTest(unittest.TestCase):
    def _task(self, label, buttons):
        from src.tasks.QuickHuntTask import QuickHuntTask

        task = object.__new__(QuickHuntTask)
        task.capture_frame = lambda: "frame"
        reads = {"仅使用免费": label, "次数": buttons}
        task._quick_hunt_ocr_text = lambda frame, roi, name, small_text=False: next(
            value for key, value in reads.items() if name.endswith(key)
        )
        task._quick_hunt_current_map_context = lambda _frame: "狩猎场"
        return task

    def test_free_label_means_open(self):
        self.assertTrue(self._task("仅使用免费米饭", "")._quick_hunt_dialog_visible("x"))

    def test_count_buttons_mean_open(self):
        self.assertTrue(self._task("", "取消 MIN MAX")._quick_hunt_dialog_visible("x"))

    def test_map_screen_is_not_the_dialog_and_is_described(self):
        task = self._task("", "")
        self.assertFalse(task._quick_hunt_dialog_visible("x"))
        seen = task._quick_hunt_dialog_seen()
        self.assertIn("开关处读到「-」", seen)
        self.assertIn("所在地图「狩猎场」", seen)


if __name__ == "__main__":
    unittest.main()
