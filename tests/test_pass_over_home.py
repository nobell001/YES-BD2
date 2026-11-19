"""Player 4K v0.4.1 2026-11-19 (一键日常, 领取通行证): after 沙漠之花席比雅角色通行证
the way home tapped the notice's blank spot ten times and never pressed back.

The 通行证 page is drawn over a dimmed 主页: 我的小屋/好友 and 抽抽乐 read
through the dimming, the same three signs as a notice over 主页, so the page
was taken for one.  Its title at the top left tells it apart.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import recovery
from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.map_trade.models import ScreenState
from src.utils.home_confirmation import page_title_shown


class PageTitleTextTest(unittest.TestCase):
    def test_a_page_title_is_shown(self):
        for text in ("通行证", "任务", "邮箱 ", "< 活动"):
            self.assertTrue(page_title_shown(text), text)

    def test_home_has_no_title_there(self):
        for text in ("", None, "D-6", "00:19:46", "A"):
            self.assertFalse(page_title_shown(text), text)


class NoticeTapTest(unittest.TestCase):
    """clear_temporary_home_announcement_if_needed, shared by every task."""

    def _task(self, title):
        clicks, logs = [], []
        task = SimpleNamespace(
            config={},
            info_set=lambda *a, **k: None,
            log_info=lambda text, **k: logs.append(text),
            sleep=lambda *_a: None,
            operate_click=lambda *a, **k: clicks.append(a),
            _sleep_after_recognition=lambda: None,
            _page_title_over_home=lambda: title,
        )
        return task, clicks, logs

    def _call(self, task):
        return BaseBD2Task.clear_temporary_home_announcement_if_needed(
            task,
            # The player's 通行证 frame: 2 of 2 left labels, p95 47, 抽抽乐 read.
            left_hits=2,
            required_left_hits=2,
            brightness=47.0,
            brightness_threshold=185.0,
            gacha_ocr_text="抽抽乐",
            context="回到主页",
        )

    def test_page_over_home_is_not_tapped(self):
        task, clicks, logs = self._task("通行证")
        self.assertFalse(self._call(task))
        self.assertEqual([], clicks)
        self.assertTrue(any("通行证" in line for line in logs))

    def test_notice_over_home_is_still_tapped(self):
        task, clicks, _logs = self._task("")
        self.assertTrue(self._call(task))
        self.assertEqual(1, len(clicks))


class RecoveryNoticeTapsCappedTest(unittest.TestCase):
    """Taps on the blank spot that did not bring 主页 leave room for the
    back arrow (whatever the page was taken for)."""

    def test_back_arrow_is_pressed_after_the_capped_taps(self):
        page = np.full((1080, 1920, 3), 60, np.uint8)
        home = np.full((1080, 1920, 3), 200, np.uint8)
        state = {"frame": page}
        taps, back = [], []

        class FakeNavigator:
            def __init__(self, task, _vision):
                self.vision = SimpleNamespace(capture=lambda: state["frame"])

            def _home_confirmation_signals(self, frame):
                return (frame is home, 0, 0.0, "")

            def classify(self, _frame=None):
                return ScreenState.HOME if state["frame"] is home else ScreenState.UNKNOWN

            def clear_home_announcement(self, _frame, clicks_so_far=0):
                # Always reads as a notice over 主页; the tap does nothing.
                if clicks_so_far >= 5:
                    return False
                taps.append(clicks_so_far)
                return True

        def operate_click(*a, **_k):
            back.append(a)
            state["frame"] = home

        task = SimpleNamespace(
            info_set=lambda *a: None,
            log_info=lambda *a, **k: None,
            log_warning=lambda *a, **k: None,
            sleep=lambda *_a: None,
            operate_click=operate_click,
            tap_key=lambda key, after_sleep=0.0: False,
            tap_escape=lambda after_sleep=0.0: False,
        )
        with (
            mock.patch.object(recovery, "Navigator", FakeNavigator),
            mock.patch.object(recovery, "Vision", lambda task: SimpleNamespace(ocr_boxes=lambda *a, **k: [])),
            mock.patch.object(recovery, "_handle_dialog", lambda *_a: "none"),
            mock.patch.object(recovery, "_keep_failure_picture", lambda *_a: None),
            mock.patch.object(recovery, "_press_top_right_home", lambda *a, **k: None),
            mock.patch.object(recovery, "channel_button_at_back", lambda *_a: False),
            mock.patch.object(recovery, "monotonic", iter(range(0, 100000)).__next__),
        ):
            reached = recovery.recover_to_home(task)
        self.assertTrue(reached)
        self.assertEqual([0, 1, 2, 3, 4], taps)
        self.assertEqual(1, len(back))


if __name__ == "__main__":
    unittest.main()
