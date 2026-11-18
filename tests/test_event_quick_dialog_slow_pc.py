"""A slow PC reading the quick-battle dialog is not stuck (player v0.3.23, 2026-11-17).

The player's 问题摘要 (1920x1080 fullscreen, 125%, 简中, no clone):
停在 「活动每日战斗 · 挑战战斗15：准备快速战斗 · 启动活动每日战斗，已回主页」,
读到 「鼠标点击=…0.916204)；截图方式=…；游戏分辨率=1920x1080；免费AP开关=黄色占比 0.000」.

截图方式 and 游戏分辨率 are written on every capture, so the last capture that
went through was the switch's first look, right after the 快速战斗 press (y 989
of 1080 is the stage page's bottom buttons).  The switch's second look 0.5 s
later raised the page guard: 10 s had passed since the press, spent reading
the dialog, and the dialog showing never counted as progress.  Replayed here
with the dialog's big OCR area taking about 4 s a read: the old code read it
twice per look and raised exactly there, after one switch read of 0.000.
"""

import unittest
from unittest import mock

import numpy as np

from src.tasks import EventBattleTask as event_module
from src.utils.frozen_screen import FrozenWatch
from tests.test_event_battle_flow import box, make_task

BIG_OCR_SECONDS = 4.2  # the dialog's area: a slow PC's read (≥ 8.5 s for two)
SMALL_OCR_SECONDS = 0.3
CAPTURE_SECONDS = 0.05
DIALOG_WORDS = ("快速战斗", "仅使用免费活动AP", "MAX", "MIN", "获得奖励")
BIG_AREAS = (event_module.DIALOG_ROI, event_module.QUICK_DIALOG_ROI)


class SlowPcQuickDialogTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.switch_on = False
        self.dialog_from = None
        self.reads = []
        self.frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.watch = FrozenWatch()
        for patch in (
            mock.patch.object(event_module, "monotonic", side_effect=lambda: self.now),
            mock.patch.object(event_module._ClaimTaskBase, "capture_frame", self._capture),
            mock.patch.object(
                event_module, "switch_yellow_ratio", lambda crop: 0.3 if self.switch_on else 0.0
            ),
            mock.patch.object(event_module, "is_loading_dark", return_value=False),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def _capture(self, _task, _name=None):
        self.now += CAPTURE_SECONDS
        # The still-screen watch sees the same dialog picture every time.
        self.watch.look(self.frame, now=self.now)
        self.reads.append("capture")
        return self.frame

    def _boxes(self, _frame, roi, _name, enlarge=1.0):
        started = self.now
        self.now += BIG_OCR_SECONDS if roi in BIG_AREAS else SMALL_OCR_SECONDS
        if roi == event_module.BOTTOM_BUTTONS_ROI:
            return [box("快速战斗")]
        if roi in BIG_AREAS:
            shown = self.dialog_from is not None and started >= self.dialog_from
            return [box(word) for word in DIALOG_WORDS] if shown else []
        if roi == event_module.QUICK_DIALOG_START_ROI:
            return [box("战斗5")]
        return []

    def _press(self, point=None, after_sleep=0.0):
        # operate(): both watches count from the press.
        self.task._progressed()
        self.watch.pressed(point)
        if point == event_module.QUICK_FREE_AP_SWITCH_POINT:
            self.switch_on = True
        self.now += after_sleep

    def _task(self):
        task = make_task()
        self.task = task
        task.name = "活动每日战斗"
        task._frozen_watch = self.watch
        task._roi_boxes = self._boxes
        task._sleep_after_recognition = lambda: None

        def sleep(seconds):
            self.now += seconds

        task.sleep = sleep

        def click_box(found, after_sleep=0.0):
            self._press(("box", found.name))
            if found.name == "快速战斗":
                self.dialog_from = self.now  # the dialog shows right after the press
            self.now += after_sleep

        task._click_box = click_box
        task._click_reference = lambda x, y, after_sleep=0.0: self._press((x, y), after_sleep)
        task._resume_guard()
        return task

    def test_dialog_read_slowly_then_switch_off_still_reaches_the_count(self):
        task = self._task()
        state = {"stage": 15, "free_ap": 5, "bonus_ap": 0, "auto": False, "quick": True}
        self.assertTrue(task._open_quick_dialog())
        # Before: the second look at the switch raised 「10 秒没走到下一步」.
        self.assertEqual(5, task._set_quick_count(5, state))
        self.assertTrue(self.switch_on)

    def test_one_read_per_look_for_the_popup_and_the_dialog(self):
        task = self._task()
        reads = []
        boxes = task._roi_boxes

        def counting(frame, roi, name, enlarge=1.0):
            reads.append(roi)
            return boxes(frame, roi, name, enlarge)

        task._roi_boxes = counting
        self.assertTrue(task._open_quick_dialog())
        big = [roi for roi in reads if roi in BIG_AREAS]
        self.assertEqual([event_module.DIALOG_ROI], big)

    def test_an_ap_shortage_popup_is_still_cancelled_from_that_read(self):
        task = self._task()
        cancelled = []

        def popup(_frame, roi, _name, enlarge=1.0):
            self.now += BIG_OCR_SECONDS if roi in BIG_AREAS else SMALL_OCR_SECONDS
            if roi == event_module.BOTTOM_BUTTONS_ROI:
                return [box("快速战斗")]
            if roi == event_module.DIALOG_ROI:
                return [box(event_module.AP_SHORT_TEXT), box(event_module.CANCEL_TEXT)]
            return []

        task._roi_boxes = popup
        task._click_box = lambda found, after_sleep=0.0: cancelled.append(found.name)
        self.assertFalse(task._open_quick_dialog())
        self.assertIn(event_module.CANCEL_TEXT, cancelled)
        self.assertNotIn("补充", cancelled)

    def test_a_dialog_that_never_reads_still_hits_the_guard(self):
        # Nothing recognised and nothing pressed: still stuck after 10 s.
        task = self._task()
        task._roi_boxes = lambda frame, roi, name, enlarge=1.0: (
            setattr(self, "now", self.now + BIG_OCR_SECONDS) or []
        )
        with self.assertRaises(Exception) as stuck:
            for _ in range(20):
                task._quick_dialog_open()
        self.assertIn("没走到下一步", str(stuck.exception))


class RecognisedCountsForBothWatchesTest(unittest.TestCase):
    def test_recognised_resets_the_page_guard_and_the_still_watch(self):
        task = make_task()
        task._frozen_watch = watch = FrozenWatch()
        watch.picture = np.zeros((1, 1), dtype=np.uint8)
        with mock.patch.object(event_module, "monotonic", return_value=100.0):
            task._resume_guard()
            task._page_deadline = 101.0
            task._recognised()
        self.assertEqual(100.0 + event_module.PAGE_STUCK_SECONDS, task._page_deadline)
        self.assertIsNone(watch.picture)

    def test_a_press_alone_keeps_the_pressed_still_count(self):
        # operate() calls _progressed, not _recognised: 「点了几次都没变化」 keeps counting.
        task = make_task()
        task._frozen_watch = watch = FrozenWatch()
        watch.still_picture = np.zeros((1, 1), dtype=np.uint8)
        with mock.patch.object(event_module, "monotonic", return_value=0.0):
            task._resume_guard()
            task._progressed()
        self.assertIsNotNone(watch.still_picture)


if __name__ == "__main__":
    unittest.main()
