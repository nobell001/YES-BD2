"""镜中之战 倍率 setting: 确认 counts only by the setting dialog's own cues.

A player's run (v0.1.17, 1920×1080 windowed, scaling 250%, 2026-10-10)
stopped at 「倍率确认第2次点击未生效，重试。」 twice: three presses, and the
dialog read as still open each time.  The old check read 鲜血鸡尾酒…消耗量,
which the main popup's 鲜血鸡尾酒 row can show as well.
"""

import unittest

from src.tasks.PVPTask import (
    PVP_CLICK_VERIFY_ATTEMPTS,
    PVP_MULTIPLIER_CONFIRM_SCREEN_POINT,
    PVP_SETTING_CONFIRM_PATTERNS,
    PVP_SETTING_CONFIRM_REFERENCE_ROI,
    PVPTask,
)


class _Screen:
    """The setting dialog over the main popup; a landed 确认 closes it."""

    def __init__(self, *, confirm_read=True, main_read=True, cost=40, lands_after=1):
        self.confirm_read = confirm_read
        self.main_read = main_read
        self.cost = cost
        self.lands_after = lands_after
        self.presses = []
        self.dialog_open = True

    def press(self, how):
        self.presses.append(how)
        if len(self.presses) >= self.lands_after:
            self.dialog_open = False

    def ocr(self, patterns, roi=None):
        """What _wait_for_ocr_patterns finds on this screen."""
        joined = " ".join(patterns)
        if "鲜血鸡尾酒" in joined:
            return True  # the dialog's title or the main popup's row
        if "设置" in joined:
            return self.dialog_open
        if "确" in joined:
            return self.dialog_open and self.confirm_read
        return False


def _task(screen, multiplier=40):
    task = object.__new__(PVPTask)
    task.config = {}
    task.infos, task.logs, task.diagnostics = {}, [], []
    task.info_set = lambda key, value: task.infos.__setitem__(key, value)
    task.log_info = task.logs.append
    task.sleep = lambda _s: None
    task.capture_frame = lambda: None

    def read_confirm(patterns, name, roi=None, after_sleep=0.0):
        if patterns != PVP_SETTING_CONFIRM_PATTERNS or roi != PVP_SETTING_CONFIRM_REFERENCE_ROI:
            raise AssertionError("only the setting's 确认 is looked for")
        if screen.dialog_open and screen.confirm_read:
            screen.press("read")
            return True
        return False

    def fixed(x, y, after_sleep=0.0):
        assert (x, y) == PVP_MULTIPLIER_CONFIRM_SCREEN_POINT
        screen.press("fixed")

    task._click_ocr_pattern_center = read_confirm
    task._click_screen_reference = fixed
    task._multiplier_matches = lambda m, timeout=2.0: (
        not screen.dialog_open and screen.main_read and m == multiplier
    )
    task._wait_for_ocr_patterns = lambda patterns, **kwargs: (
        screen.ocr(patterns, kwargs.get("roi")),
        "",
    )
    task._setting_multiplier_matches = lambda m: screen.dialog_open and m == multiplier
    task._start_cost_on = lambda _frame: None if screen.dialog_open else screen.cost
    task._multiplier_seen = lambda: "当时倍率处读到「-」。"
    task._save_flow_diagnostic = task.diagnostics.append
    return task


class ConfirmTest(unittest.TestCase):
    def test_the_read_confirm_is_pressed(self):
        screen = _Screen()
        self.assertTrue(PVPTask._confirm_setting_multiplier(_task(screen), 40))
        self.assertEqual(["read"], screen.presses)

    def test_an_unread_confirm_falls_back_to_the_fixed_point(self):
        screen = _Screen(confirm_read=False)
        self.assertTrue(PVPTask._confirm_setting_multiplier(_task(screen), 40))
        self.assertEqual(["fixed"], screen.presses)

    def test_a_closed_dialog_with_an_unread_value_is_confirmed_by_the_start_cost(self):
        # The player's case as far as the log shows: the dialog had closed,
        # the main popup's value was not read, and its 鲜血鸡尾酒 row looked
        # like the dialog's title.  Old: two more presses on the main popup.
        screen = _Screen(main_read=False)
        task = _task(screen)
        self.assertTrue(PVPTask._confirm_setting_multiplier(task, 40))
        self.assertEqual(["read"], screen.presses)
        self.assertFalse(any("未生效" in line for line in task.logs))
        self.assertTrue(any("每场消耗是 40" in line for line in task.logs))

    def test_a_wrong_start_cost_stops_without_pressing_again(self):
        screen = _Screen(main_read=False, cost=1)
        task = _task(screen)
        self.assertFalse(PVPTask._confirm_setting_multiplier(task, 40))
        self.assertEqual(["read"], screen.presses)
        self.assertEqual("未确认", task.infos["PVP 倍率 OCR"])
        self.assertEqual(["pvp_multiplier_confirm_failed"], task.diagnostics)
        self.assertIn("当时倍率处读到", task.logs[-1])

    def test_a_dialog_that_stays_open_is_pressed_again(self):
        screen = _Screen(lands_after=2)
        self.assertTrue(PVPTask._confirm_setting_multiplier(_task(screen), 40))
        self.assertEqual(["read", "read"], screen.presses)

    def test_a_dialog_that_never_closes_stops_with_what_it_showed(self):
        screen = _Screen(lands_after=99)
        task = _task(screen)
        self.assertFalse(PVPTask._confirm_setting_multiplier(task, 40))
        self.assertEqual(PVP_CLICK_VERIFY_ATTEMPTS, len(screen.presses))
        self.assertEqual(["pvp_multiplier_confirm_failed"], task.diagnostics)

    def test_the_start_cost_needs_two_agreeing_looks(self):
        task = object.__new__(PVPTask)
        task.sleep = lambda _s: None
        task.capture_frame = lambda: None
        reads = iter([40, 4])
        task._start_cost_on = lambda _frame: next(reads)
        self.assertFalse(PVPTask._start_cost_is(task, 40))


if __name__ == "__main__":
    unittest.main()
