"""Audit #77: 确认 is pressed only after two agreeing frames; a 付费 cost
cancels.  (Leo 11-07: event pages no longer look for 钻石.)"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import EventRewardTask as event_module
from src.tasks.EventRewardTask import EventRewardTask


def _frame():
    return np.full((1080, 1920, 3), 40, np.uint8)


def _box(name, x=900, y=600):
    return SimpleNamespace(name=name, x=x, y=y, width=80, height=40)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.5
        return self.now


def _task(dialogs):
    """``dialogs``: the OCR boxes of the dialog on each successive frame."""
    task = object.__new__(EventRewardTask)
    reads = list(dialogs)
    task.clicks = []
    task.logs = []
    task.capture_frame = _frame
    task._reference_boxes = lambda _f, _roi, _name: reads.pop(0) if reads else []
    task._click_reference_box = lambda box, after_sleep=0.0: task.clicks.append(box.name)
    task.sleep = lambda _s: None
    task.log_info = task.logs.append
    task.log_warning = task.logs.append
    task.info_set = lambda *_a: None
    return task


class ConfirmTwoFramesTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(event_module, "monotonic", _Clock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_two_agreeing_frames_press_confirm(self):
        task = _task([[_box("确认"), _box("取消", x=700)], [_box("确认"), _box("取消", x=700)]])
        self.assertTrue(task._confirm_dialog("测试"))
        self.assertEqual(["确认"], task.clicks)

    def test_one_frame_is_not_enough(self):
        task = _task([[_box("确认")]])
        self.assertFalse(task._confirm_dialog("测试"))
        self.assertEqual([], task.clicks)

    def test_a_paid_cost_drawn_on_the_second_frame_cancels(self):
        plain = [_box("确认"), _box("取消", x=700)]
        task = _task([plain, [_box("消耗付费钻石x50"), *plain]])
        self.assertFalse(task._confirm_dialog("测试"))
        self.assertEqual(["取消"], task.clicks)

    def test_a_moving_button_is_not_pressed_yet(self):
        task = _task([[_box("确认", y=500)], [_box("确认", y=600)], [_box("确认", y=601)]])
        self.assertTrue(task._confirm_dialog("测试"))
        self.assertEqual(["确认"], task.clicks)
        self.assertEqual(1, len(task.clicks))


class DiamondWordIsFineTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(event_module, "monotonic", _Clock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_diamond_reward_in_the_dialog_is_confirmed(self):
        plain = [_box("获得钻石x1000"), _box("确认"), _box("取消", x=700)]
        task = _task([plain, plain])
        self.assertTrue(task._confirm_dialog("测试"))
        self.assertEqual(["确认"], task.clicks)


if __name__ == "__main__":
    unittest.main()
