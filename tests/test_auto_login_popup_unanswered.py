"""Player reports 2026-11-23 (v0.4.12): 自动登录 sat on 「清理公告」 for good.
The popup's own way (Esc for the 公告 list, or its button) was pressed on
every look, did not close it, and the blank spot beside the popup, which
closes every login notice, was never clicked.

Now (Leo 2026-11-23 「你可以不要一直esc嗎」「你可以都點」「交叉來回也可以」):
the notice list is closed by the blank spot beside it, Esc only in turn
with the tap while it stays; any popup press that did not close it is
followed by the blank spot (BaseBD2Task)."""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks.trigger.AutoLoginTask import AutoLoginTask
from src.utils import game_text

CLEAR_SPOT = (0.088, 0.569)

# The game's notice list, as each client draws it (tags and dates per row).
NOTICE_LIST_CN = ("公告", "2026年11月23日", "活动", "2026年11月20日", "更新", "2026年11月19日")
NOTICE_LIST_TW = ("公告", "2026年11月23日", "活動", "2026年11月20日", "更新", "2026年11月19日")
# A banner with its own 关闭 that, on this look, does not take the press.
CLOSE_BANNER_CN = ("7天内不再显示", "关闭")
CLOSE_BANNER_TW = ("7天內不再顯示", "關閉")


def _boxes(names, traditional):
    boxes = [
        SimpleNamespace(name=name, x=300 + 10 * i, y=200 + 60 * i, width=120, height=30)
        for i, name in enumerate(names)
    ]
    # What every task's OCR does to a read (BaseBD2Task.fix_texts).
    for box in boxes:
        box.name = game_text.to_tool_text(box.name, traditional)
    return boxes


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class PopupPressUnansweredTest(unittest.TestCase):
    def _task(self, names, traditional):
        task = object.__new__(AutoLoginTask)
        task.config = {"公告清理点击 X 百分比": 8.8, "公告清理点击 Y 百分比": 56.9}
        task.info_set = lambda *_a, **_k: None
        task.log_info = lambda *_a, **_k: None
        task.sleep = lambda *_a, **_k: None
        task._sleep_after_recognition = lambda: None
        task._finish_by_recovery = lambda: False
        task._last_clear_click_at = 0.0
        task._login_clicked_at = 1.0
        task._home_bright_since = None
        task.capture_frame = lambda: np.zeros((720, 1280, 3), np.uint8)
        task.ocr = lambda *_a, **_k: _boxes(names, traditional)
        task.events = []
        task.operate_click = lambda x, y, **_k: task.events.append((round(x, 3), round(y, 3)))
        task.tap_escape = lambda **_k: task.events.append("esc") or True
        return task

    def _rounds(self, task, count):
        clock = _Clock()
        with mock.patch("src.tasks.trigger.AutoLoginTask.monotonic", clock), mock.patch(
            "src.tasks.BaseBD2Task.time.monotonic", clock
        ):
            for _ in range(count):
                # A slow PC: each round several seconds after the last.
                clock.now += 4.0
                task._clear_home_popup(0.08)
        return task.events

    def _assert_clear_spot_between(self, events):
        self.assertIn(CLEAR_SPOT, events)
        # Never the popup's own press twice in a row without the clear spot.
        for first, second in zip(events, events[1:]):
            self.assertFalse(first != CLEAR_SPOT and second == first, events)

    def _assert_notice_list_taps_first(self, events):
        self.assertEqual(CLEAR_SPOT, events[0])
        self.assertIn("esc", events)
        # Mostly the spot beside it; Esc never twice in a row.
        self.assertGreater(events.count(CLEAR_SPOT), 2 * events.count("esc"))
        for first, second in zip(events, events[1:]):
            self.assertFalse(first == second == "esc", events)

    def test_notice_list_is_tapped_beside_esc_only_in_turn_cn(self):
        events = self._rounds(self._task(NOTICE_LIST_CN, traditional=False), 6)
        self._assert_notice_list_taps_first(events)

    def test_notice_list_is_tapped_beside_esc_only_in_turn_tw(self):
        events = self._rounds(self._task(NOTICE_LIST_TW, traditional=True), 6)
        self._assert_notice_list_taps_first(events)

    def test_a_close_button_that_did_not_close_is_followed_by_the_clear_spot_cn(self):
        events = self._rounds(self._task(CLOSE_BANNER_CN, traditional=False), 6)
        self.assertEqual(3, events.count(CLEAR_SPOT))
        self._assert_clear_spot_between(events)

    def test_a_close_button_that_did_not_close_is_followed_by_the_clear_spot_tw(self):
        events = self._rounds(self._task(CLOSE_BANNER_TW, traditional=True), 6)
        self.assertEqual(3, events.count(CLEAR_SPOT))
        self._assert_clear_spot_between(events)

    def test_without_a_popup_only_the_clear_spot(self):
        events = self._rounds(self._task((), traditional=False), 3)
        self.assertEqual([CLEAR_SPOT] * 3, events)

    def test_recovery_is_tried_even_while_a_popup_press_answers(self):
        task = self._task(NOTICE_LIST_CN, traditional=False)
        tried = []
        task._finish_by_recovery = lambda: tried.append(1) and False
        self._rounds(task, 5)
        self.assertEqual(1, len(tried))


class NoticeListTapThenEscTest(unittest.TestCase):
    """Every caller of close_known_popup (the way home, claim pages, the
    login): the notice list gets the blank spot beside it first, then Esc and
    the tap take turns while it stays."""

    def _task(self, traditional):
        task = object.__new__(AutoLoginTask)
        task.info_set = lambda *_a, **_k: None
        task.log_info = lambda *_a, **_k: None
        task._sleep_after_recognition = lambda: None
        task.capture_frame = lambda: np.zeros((720, 1280, 3), np.uint8)
        names = NOTICE_LIST_TW if traditional else NOTICE_LIST_CN
        task.ocr = lambda *_a, **_k: _boxes(names, traditional)
        task.events = []
        task.operate_click = lambda x, y, **_k: task.events.append((round(x, 3), round(y, 3)))
        task.tap_escape = lambda **_k: task.events.append("esc") or True
        return task

    def _check(self, traditional):
        task = self._task(traditional)
        answers = [task.close_known_popup("测试") for _ in range(6)]
        self.assertEqual([True] * 6, answers)
        self.assertEqual([CLEAR_SPOT, "esc"] * 3, task.events)

    def test_cn(self):
        self._check(traditional=False)

    def test_tw(self):
        self._check(traditional=True)


if __name__ == "__main__":
    unittest.main()
