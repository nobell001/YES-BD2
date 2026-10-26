"""镜中之战 倍率: a value already set is seen even when its small box reads nothing.

A player's run (v0.1.21, 1920×1080 windowed, scaling 250%, 2026-10-11)
stopped with 「倍率没能设成 40，当时倍率处读到「-」，标题处「自动战斗
1鸡尾酒消耗量 1次战斗的鲜血」，确认处「▲」」 while the frame shows 40倍
and 「40倍战斗开始 40」.  Read on that frame, the area where the setting
dialog's title is looked for holds the main popup's own 「…设置为1~40倍」, so
the closed dialog counted as open and 确认 was pressed again on the main
popup's battle-count bar.  The screen below answers each box with what the
OCR read there on the player's frame.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import PVPTask as pvp_module
from src.tasks.PVPTask import (
    PVP_MULTIPLIER_40_OPTION_SCREEN_POINT,
    PVP_MULTIPLIER_BUTTON_SCREEN_POINT,
    PVP_MULTIPLIER_CONFIRM_SCREEN_POINT,
    PVP_MULTIPLIER_OCR_REFERENCE_ROI,
    PVP_MULTIPLIER_SETTING_OCR_REFERENCE_ROI,
    PVP_MULTIPLIER_SETTING_VALUE_OCR_REFERENCE_ROI,
    PVP_MULTIPLIER_WIDER_GROW,
    PVP_SETTING_CONFIRM_REFERENCE_ROI,
    PVP_SETTING_VALUE_WIDER_GROW,
    PVP_START_BUTTON_ROI,
    PVPTask,
)

VALUE = PVPTask._mf_roi(*PVP_MULTIPLIER_OCR_REFERENCE_ROI)
WIDER = PVPTask._grown_roi(VALUE, PVP_MULTIPLIER_WIDER_GROW)
TITLE = PVPTask._mf_roi(*PVP_MULTIPLIER_SETTING_OCR_REFERENCE_ROI)
SETTING_VALUE = PVPTask._mf_roi(*PVP_MULTIPLIER_SETTING_VALUE_OCR_REFERENCE_ROI)
SETTING_WIDER = PVPTask._grown_roi(SETTING_VALUE, PVP_SETTING_VALUE_WIDER_GROW)
CONFIRM = PVP_SETTING_CONFIRM_REFERENCE_ROI
START = PVP_START_BUTTON_ROI
# What the OCR read in the title area on the player's frame (main popup).
MAIN_TITLE = ["自动战斗", "1鸡尾酒消耗量", "1次战斗的鲜血鸡尾酒消耗量设置为1~40倍。"]


class _Screen:
    """The auto-battle popup, with the 倍率 setting dialog over it when open."""

    def __init__(self, main=40, value_read=False, wider_read=False, cost_read=True):
        self.main = main
        self.setting = main
        self.value_read = value_read
        self.wider_read = wider_read
        self.cost_read = cost_read
        self.dialog = False
        self.presses = []

    def labels(self, roi):
        if self.dialog:
            return {
                TITLE: ["设置鲜血鸡尾酒消耗量"],
                CONFIRM: ["确认"],
                SETTING_VALUE: [f"{self.setting}倍"],
            }.get(roi, [])
        return {
            VALUE: [f"{self.main}倍"] if self.value_read else [],
            WIDER: [f"{self.main}倍"] if self.wider_read else [],
            TITLE: MAIN_TITLE,
            CONFIRM: ["▲"],
            START: [f"{self.main}倍战斗开始", str(self.main)] if self.cost_read else [],
        }.get(roi, [])

    def press_screen(self, x, y):
        point = (x, y)
        if point == PVP_MULTIPLIER_BUTTON_SCREEN_POINT and not self.dialog:
            self.presses.append("gear")
            self.dialog = True
        elif point == PVP_MULTIPLIER_40_OPTION_SCREEN_POINT and self.dialog:
            self.presses.append("40")
            self.setting = 40
        elif point == PVP_MULTIPLIER_CONFIRM_SCREEN_POINT:
            self.presses.append("fixed 确认" if self.dialog else "main popup bar")
            self._close()
        else:
            self.presses.append(f"other {point}")

    def press_read_confirm(self):
        self.presses.append("read 确认")
        self._close()

    def _close(self):
        if self.dialog:
            self.main = self.setting
            self.dialog = False


def _task(screen, clock):
    task = object.__new__(PVPTask)
    task.config = {}
    task.infos, task.logs, task.diagnostics = {}, [], []
    task.info_set = lambda key, value: task.infos.__setitem__(key, value)
    task.log_info = task.logs.append
    task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    task.capture_frame = lambda: frame

    def boxes(_frame, name, roi=None, ocr_scale=1.0):
        return [
            SimpleNamespace(name=label, confidence=0.9, x=10, y=10, width=40, height=20)
            for label in screen.labels(roi)
        ]

    task._ocr_boxes = boxes
    task._click_screen_reference = lambda x, y, after_sleep=0.0: screen.press_screen(x, y)
    task._click_client = lambda *_args, **_kwargs: screen.press_read_confirm()
    task._click_reference = lambda x, y, after_sleep=0.0: screen.presses.append("step")
    task._save_flow_diagnostic = task.diagnostics.append
    return task


class MultiplierReadTest(unittest.TestCase):
    def setUp(self):
        self.clock = [0.0]
        patcher = mock.patch.object(pvp_module, "monotonic", lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _task(self, screen):
        return _task(screen, self.clock)

    def test_a_value_already_set_but_unread_is_seen_on_the_start_button(self):
        # The player's case: 40倍 showing, the small box read 「-」.
        screen = _Screen(main=40)
        task = self._task(screen)
        self.assertTrue(PVPTask._ensure_multiplier(task, 40))
        self.assertEqual([], screen.presses)
        self.assertTrue(any("倍率已经是 40" in line for line in task.logs))

    def test_the_value_is_read_again_with_room_around_it(self):
        screen = _Screen(main=40, wider_read=True, cost_read=False)
        task = self._task(screen)
        self.assertTrue(PVPTask._multiplier_matches(task, 40))
        self.assertEqual("40倍", task.infos["PVP 倍率 OCR"])

    def test_the_wider_read_does_not_take_another_value(self):
        screen = _Screen(main=4, wider_read=True)
        self.assertFalse(PVPTask._multiplier_matches(self._task(screen), 40))

    def test_the_wider_box_keeps_the_gear_out(self):
        # The gear starts at x 1303 (1080p); merged into the box it reads 「1倍a」.
        self.assertEqual(VALUE[0] + VALUE[2], WIDER[0] + WIDER[2])
        self.assertLess(WIDER[0] + WIDER[2], 1303)
        self.assertLess(WIDER[0], VALUE[0])
        self.assertGreater(WIDER[3], VALUE[3])

    def test_the_main_popup_is_not_taken_for_the_setting_dialog(self):
        screen = _Screen(main=40)
        self.assertIn("设置", " ".join(MAIN_TITLE))
        self.assertFalse(PVPTask._setting_dialog_open(self._task(screen), 40))

    def test_the_open_setting_dialog_is_still_seen(self):
        screen = _Screen(main=1)
        screen.dialog = True
        self.assertTrue(PVPTask._setting_dialog_open(self._task(screen), 40))

    def test_a_changed_value_is_confirmed_once_and_the_main_popup_left_alone(self):
        # Was 1, set to 40; the main popup's value stays unread afterwards.
        screen = _Screen(main=1)
        task = self._task(screen)
        self.assertTrue(PVPTask._ensure_multiplier(task, 40))
        self.assertEqual(["gear", "40", "read 确认"], screen.presses)
        self.assertEqual(40, screen.main)
        self.assertFalse(any("未生效" in line for line in task.logs))

    def test_nothing_read_after_确认_stops_without_pressing_the_main_popup(self):
        screen = _Screen(main=1, cost_read=False)
        task = self._task(screen)
        self.assertFalse(PVPTask._ensure_multiplier(task, 40))
        self.assertEqual(["gear", "40", "read 确认"], screen.presses)
        self.assertNotIn("main popup bar", screen.presses)
        self.assertEqual(["pvp_multiplier_confirm_failed"], task.diagnostics)
        self.assertIn("当时倍率处读到「-」", task.logs[-1])



class _UnreadSettingScreen(_Screen):
    """Player v0.2.12 2026-10-25 (1920×1080 fullscreen, 125%): after MIN the
    dialog showed 「🍷1倍」, but its small box read nothing three times."""

    def __init__(self, wider_setting=False, **kwargs):
        super().__init__(**kwargs)
        self.wider_setting = wider_setting

    def labels(self, roi):
        if self.dialog and roi == SETTING_VALUE:
            return []
        if self.dialog and roi == SETTING_WIDER:
            return [f"{self.setting}倍"] if self.wider_setting else []
        return super().labels(roi)

    def press_screen(self, x, y):
        from src.tasks.PVPTask import PVP_MULTIPLIER_1_OPTION_SCREEN_POINT

        if (x, y) == PVP_MULTIPLIER_1_OPTION_SCREEN_POINT and self.dialog:
            self.presses.append("MIN")
            self.setting = 1
            return
        super().press_screen(x, y)


class SettingValueReadTest(MultiplierReadTest):
    def test_setting_value_is_read_again_with_room_around_it(self):
        screen = _UnreadSettingScreen(main=40, wider_setting=True)
        screen.dialog = True
        self.assertTrue(PVPTask._setting_multiplier_matches(self._task(screen), 40))

    def test_the_setting_wider_box_stays_below_the_step_row(self):
        # MIN / -5 / +5 / MAX sit right above: a 「+5」 read without its sign
        # would pass for 5.
        self.assertEqual(SETTING_VALUE[1], SETTING_WIDER[1])
        self.assertLess(SETTING_WIDER[0], SETTING_VALUE[0])
        self.assertGreater(SETTING_WIDER[2], SETTING_VALUE[2])

    def test_unread_min_still_reaches_battle_when_the_main_popup_agrees(self):
        # The player's run stopped with 未能开始战斗 here.  Now the steps go
        # on and 确认 is judged by the main popup and the 战斗开始 cost.
        screen = _UnreadSettingScreen(main=40)
        task = self._task(screen)
        task._read_until = lambda read: read()
        with mock.patch(
            "src.tasks.PVPTask.steps_between", lambda _start, _target, _step: []
        ):
            self.assertTrue(PVPTask._ensure_multiplier(task, 1))
        self.assertEqual(["gear", "MIN", "MIN", "MIN", "read 确认"], screen.presses)
        self.assertEqual(1, screen.main)
        self.assertTrue(any("读到「没有字」" in line for line in task.logs), task.logs)

    def test_unread_min_does_not_start_on_a_wrong_value(self):
        # MIN swallowed, the value stays 40: 确认 reads 40 on the main popup
        # and the start cost, so the target 1 is never taken as set.
        screen = _UnreadSettingScreen(main=40)
        screen.press_screen = lambda x, y, _base=screen.press_screen: (
            screen.presses.append("MIN lost")
            if (x, y) == pvp_module.PVP_MULTIPLIER_1_OPTION_SCREEN_POINT and screen.dialog
            else _base(x, y)
        )
        task = self._task(screen)
        task._read_until = lambda read: read()
        with mock.patch(
            "src.tasks.PVPTask.steps_between", lambda _start, _target, _step: []
        ):
            self.assertFalse(PVPTask._ensure_multiplier(task, 1))
        self.assertEqual(40, screen.main)


if __name__ == "__main__":
    unittest.main()
