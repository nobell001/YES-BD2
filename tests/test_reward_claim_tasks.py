import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks.RewardClaimTasks import (
    PASS_LIST_EXTENDED_ROI,
    PASS_LIST_ROI,
    PASS_LIST_SCROLL_POINT,
    PassRewardTask,
)


def box(name, y=0):
    return SimpleNamespace(name=name, x=330, y=y, width=180, height=30)


class PassListTest(unittest.TestCase):
    def _task(self, lists):
        """``lists(roi, scrolls)`` returns the OCR boxes of the pass list."""
        task = object.__new__(PassRewardTask)
        task.name = "领取通行证"
        task.config = {}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        state = {"scrolls": 0}
        task._roi_boxes = lambda _frame, roi, _name: lists(roi, state["scrolls"])
        scrolls = []

        def fake_scroll(point, amount, **kwargs):
            scrolls.append((point, amount))
            state["scrolls"] += 1

        task.scroll_client = fake_scroll
        claimed = []
        task._claim_one_pass = lambda index, caption, roi=PASS_LIST_ROI, position=None: (
            claimed.append((index, caption, roi, position)) or caption
        )
        task._open_page_from_home = lambda *_args: True
        left = []
        task._leave_to_home = lambda *_args: left.append(True) or True
        return task, claimed, scrolls, left

    def test_three_passes_scrolls_once_then_stops(self):
        three = [box("基础通行证"), box("角色通行证"), box("服装通行证")]
        task, claimed, scrolls, left = self._task(lambda _roi, _scrolls: three)

        self.assertTrue(PassRewardTask.run_claim(task))
        self.assertEqual(
            ["基础通行证", "角色通行证", "服装通行证"], [c[1] for c in claimed]
        )
        self.assertEqual([(PASS_LIST_SCROLL_POINT, -1)], scrolls)
        self.assertEqual([True], left)
        self.assertEqual(3, task.info["通行证数量"])

    def test_traditional_glyph_is_the_same_pass(self):
        # Live 2K 2026-09-29: the extended read saw 滿月 and claimed 满月 again.
        first = [box("满月赛季通行证"), box("特别赛季通行证")]
        extended = [box("滿月赛季通行证"), box("特别赛季通行证")]
        task, claimed, _scrolls, _left = self._task(
            lambda roi, _scrolls: first if roi == PASS_LIST_ROI else extended
        )

        self.assertTrue(PassRewardTask.run_claim(task))
        self.assertEqual(["满月赛季通行证", "特别赛季通行证"], [c[1] for c in claimed])

    def test_fourth_pass_below_the_list_is_claimed_without_scrolling(self):
        three = [box("基础通行证"), box("角色通行证"), box("服装通行证")]

        def lists(roi, _scrolls):
            if roi == PASS_LIST_EXTENDED_ROI:
                return three + [box("活动通行证")]
            return three

        task, claimed, scrolls, _left = self._task(lists)

        self.assertTrue(PassRewardTask.run_claim(task))
        self.assertEqual(
            (4, "活动通行证", PASS_LIST_EXTENDED_ROI, 3), claimed[-1]
        )
        self.assertEqual(4, len(claimed))
        # One scroll to confirm nothing further is hidden below.
        self.assertEqual(1, len(scrolls))
        self.assertEqual(4, task.info["通行证数量"])

    def test_fourth_pass_found_after_scrolling_the_list(self):
        three = [box("基础通行证"), box("角色通行证"), box("服装通行证")]
        scrolled = [box("角色通行证"), box("服装通行证"), box("活动通行证")]
        task, claimed, scrolls, _left = self._task(
            lambda _roi, n: scrolled if n else three
        )

        self.assertTrue(PassRewardTask.run_claim(task))
        self.assertEqual((4, "活动通行证", PASS_LIST_EXTENDED_ROI, 2), claimed[-1])
        self.assertEqual(4, len(claimed))
        # Second scroll shows nothing new, so the search ends there.
        self.assertEqual(2, len(scrolls))

    def test_purchase_caption_is_never_a_pass_card(self):
        task, _claimed, _scrolls, _left = self._task(
            lambda _roi, _n: [box("基础通行证"), box("购买高级通行证")]
        )

        self.assertEqual(["基础通行证"], PassRewardTask._pass_cards(task))

    def test_failed_extra_pass_fails_the_task(self):
        three = [box("基础通行证"), box("角色通行证"), box("服装通行证")]
        task, _claimed, _scrolls, left = self._task(
            lambda roi, _n: three + [box("活动通行证")] if roi == PASS_LIST_EXTENDED_ROI else three
        )
        task._claim_one_pass = lambda index, caption, **_kwargs: (
            None if caption == "活动通行证" else caption
        )

        self.assertFalse(PassRewardTask.run_claim(task))
        self.assertEqual([], left)
        self.assertIn("活动通行证", task.info["状态"])

    def test_claim_one_pass_falls_back_to_list_position_skipping_purchase(self):
        task = object.__new__(PassRewardTask)
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        rois = []
        # The earlier scan read the caption with a stray character, so the
        # card is found by its position; the purchase box must not count.
        task._roi_boxes = lambda _frame, roi, _name: rois.append(roi) or [
            box("购买通行证", 100),
            box("角色通行证", 200),
            box("服装通行证", 300),
            box("活动通行证", 400),
        ]
        clicked = []
        task._click_box = lambda target, **_kwargs: clicked.append(target.name)
        task._click_reference = lambda *_args, **_kwargs: None
        task._click_until_changed = lambda _label, click, _rois, **_kwargs: click() or True
        task._claim_all = lambda *_args, **_kwargs: True

        # The card opened by position is reported under its own caption, so
        # the misread "活动通行证X" is not marked handled by mistake.
        self.assertEqual(
            "活动通行证",
            PassRewardTask._claim_one_pass(
                task, 4, "活动通行证X", roi=PASS_LIST_EXTENDED_ROI, position=2
            ),
        )
        self.assertEqual(["活动通行证"], clicked)
        self.assertEqual([PASS_LIST_EXTENDED_ROI], rois)

    def test_claim_one_pass_without_card_does_not_click(self):
        task = object.__new__(PassRewardTask)
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        task._roi_boxes = lambda *_args: [box("购买通行证")]
        task._click_box = lambda *_args, **_kwargs: self.fail("must not click")
        task._click_reference = lambda *_args, **_kwargs: self.fail("must not click")

        self.assertIsNone(PassRewardTask._claim_one_pass(task, 1, "基础通行证"))

    def _card_task(self, changed):
        task = object.__new__(PassRewardTask)
        task.claim_log_name = "pass"
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task._save_flow_diagnostic = lambda *_args: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        task._roi_boxes = lambda *_args: [box("基础通行证", 300), box("角色通行证", 410)]
        task._click_box = lambda *_args, **_kwargs: None
        task._click_reference = lambda *_args, **_kwargs: None
        # The card click reports ``changed``; the tab clicks always change.
        task._click_until_changed = lambda label, click, _rois, **_kwargs: (
            click() or (changed if label.startswith("通行证") else True)
        )
        claimed = []
        task._claim_all = lambda label, *_args: claimed.append(label) or True
        return task, claimed

    def test_card_that_never_opens_is_not_claimed(self):
        # Both presses on the second card were lost: claiming now would claim
        # the first pass again and mark this one handled.
        task, claimed = self._card_task(changed=False)
        self.assertIsNone(
            PassRewardTask._claim_one_pass(task, 2, "角色通行证", position=1)
        )
        self.assertEqual([], claimed)

    def test_preselected_first_card_unchanged_is_still_claimed(self):
        task, claimed = self._card_task(changed=False)
        self.assertEqual(
            "基础通行证", PassRewardTask._claim_one_pass(task, 1, "基础通行证", position=0)
        )
        self.assertEqual(["基础通行证任务", "基础通行证奖励"], claimed)

    def test_first_pass_on_another_card_must_open(self):
        # Only the top card is selected on entry.
        task, claimed = self._card_task(changed=False)
        self.assertIsNone(PassRewardTask._claim_one_pass(task, 1, "角色通行证", position=1))
        self.assertEqual([], claimed)

    def test_misread_caption_opened_by_position_is_not_marked_handled(self):
        task, _claimed, _scrolls, _left = self._task(lambda _roi, _n: [])
        opened = {"活动通行证X": "角色通行证"}
        task._claim_one_pass = lambda index, caption, **_kwargs: opened.get(caption, caption)
        handled = []

        self.assertIsNone(
            PassRewardTask._claim_passes(
                task, ["基础通行证", "活动通行证X"], handled, PASS_LIST_ROI
            )
        )
        self.assertEqual(["基础通行证", "角色通行证"], handled)
        self.assertFalse(PassRewardTask._pass_handled("活动通行证X", handled))


class ClickUntilChangedTest(unittest.TestCase):
    def _task(self, frames):
        task = object.__new__(PassRewardTask)
        task.log_info = lambda *_args, **_kwargs: None
        task.sleep = lambda *_args: None
        frames = iter(frames)
        last = {"frame": None}

        def capture():
            last["frame"] = next(frames, last["frame"])
            return last["frame"]

        task.capture_frame = capture
        return task

    def test_stale_tab_is_clicked_again_until_it_changes(self):
        old = np.zeros((1080, 1920, 3), dtype=np.uint8)
        new = old.copy()
        new[186:256, 155:415] = 200
        # Click 1 changes nothing within the wait; click 2 switches the tab.
        task = self._task([old] + [old] * 3 + [old, new, new])
        clicks = []
        with mock.patch("src.tasks.claim_page.monotonic", side_effect=[0, 0, 1, 5, 10, 10, 10, 10]):
            changed = PassRewardTask._click_until_changed(
                task, "商品邮箱", lambda: clicks.append(1), ((155, 186, 260, 70),), attempts=3
            )
        self.assertTrue(changed)
        self.assertEqual(2, len(clicks))

    def test_click_that_lands_late_still_counts(self):
        # Click 1 shows its effect only after its wait; click 2 hits the card
        # that is already selected and changes nothing more.
        old = np.zeros((1080, 1920, 3), dtype=np.uint8)
        new = old.copy()
        new[186:256, 155:415] = 200
        task = self._task([old, old, new])
        clicks = []
        changed = PassRewardTask._click_until_changed(
            task, "通行证", lambda: clicks.append(1), ((155, 186, 260, 70),), attempts=2, wait=0
        )
        self.assertTrue(changed)
        self.assertEqual(2, len(clicks))

    def test_unchanged_page_gives_up_after_the_attempts(self):
        old = np.zeros((1080, 1920, 3), dtype=np.uint8)
        task = self._task([old])
        clicks = []
        changed = PassRewardTask._click_until_changed(
            task, "任务", lambda: clicks.append(1), ((155, 186, 260, 70),), attempts=2, wait=0
        )
        self.assertFalse(changed)
        self.assertEqual(2, len(clicks))


if __name__ == "__main__":
    unittest.main()
