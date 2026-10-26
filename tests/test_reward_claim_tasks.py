import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks.claim_page import CLAIM_GREY, CLAIM_NO_BUTTON, CLAIM_PRESSED, find_red_badges
from src.tasks.RewardClaimTasks import (
    PASS_BADGE_STRIP,
    PASS_BADGE_TO_CARD_CENTER,
    PASS_CLAIM_BUTTON,
    PASS_CLAIM_BUTTON_WIDE,
    PASS_TAB_BADGE_STRIP,
    PassRewardTask,
)

PASS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pass" / "pass_page_badges_fhd.png"
CHARACTER_PASS = Path(__file__).resolve().parent / "fixtures" / "pass"


def box(name, y=0):
    return SimpleNamespace(name=name, x=330, y=y, width=180, height=30)


def badged_frame(badge_ys):
    """A 1080p frame with a red ◆! badge at each reference y."""
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    x = PASS_BADGE_STRIP[0] + 20
    for y in badge_ys:
        frame[y - 8 : y + 8, x : x + 17] = (0, 0, 230)
    return frame


class PassBadgeTest(unittest.TestCase):
    """Leo 2026-10-19: open only the red-badged passes, press 全部获得 once
    on each, look at the list again after every claim, no second round."""

    def _task(self, screens, claim_ok=True):
        """``screens(state)`` returns (badge ys, caption boxes) for the list."""
        task = object.__new__(PassRewardTask)
        task.name = "领取通行证"
        task.config = {}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.logs = []
        task.log_info = lambda text, **_kwargs: task.logs.append(text)
        task.log_warning = task.log_info
        task.state = {"scrolls": 0, "claims": []}
        task.capture_frame = lambda: badged_frame(screens(task.state)[0])
        task._roi_boxes = lambda _frame, _roi, _name: screens(task.state)[1]
        task._wait_boxes = lambda _roi, _name, _ok, timeout=0: screens(task.state)[1]

        def fake_scroll(point, amount, **_kwargs):
            task.state["scrolls"] += 1

        task.scroll_client = fake_scroll
        task.clicks = []
        task._click_reference = lambda x, y, **_kwargs: task.clicks.append((x, y))
        task._click_until_changed = lambda _label, click, _rois, **_kwargs: click() or True

        def fake_claim(label, button, _title):
            task.state["claims"].append(label)
            task._claim_outcome = CLAIM_PRESSED
            return claim_ok

        task._claim_all = fake_claim
        task._open_page_from_home = lambda *_args: True
        task.left = []
        task._leave_to_home = lambda *_args: task.left.append(True) or True
        return task

    def test_only_badged_passes_get_one_claim_each(self):
        cards = [box("基础通行证", 300), box("角色通行证", 407), box("服装通行证", 514)]

        def screens(state):
            # The badge leaves its card once that pass is claimed.
            badges = {"基础通行证": 255, "服装通行证": 469}
            for done in state["claims"]:
                badges.pop(done, None)
            return list(badges.values()), cards

        task = self._task(screens)
        self.assertTrue(PassRewardTask.run_claim(task))
        self.assertEqual(["基础通行证", "服装通行证"], task.state["claims"])
        self.assertEqual(
            [(425, 255 + PASS_BADGE_TO_CARD_CENTER), (425, 469 + PASS_BADGE_TO_CARD_CENTER)],
            task.clicks,
        )
        self.assertEqual([True], task.left)
        self.assertEqual(2, task.info["通行证数量"])

    def test_no_badge_claims_nothing_and_still_succeeds(self):
        task = self._task(lambda _state: ([], [box("基础通行证", 300)]))
        self.assertTrue(PassRewardTask.run_claim(task))
        self.assertEqual([], task.state["claims"])
        self.assertEqual([True], task.left)
        # Looked below the visible cards, then stopped: no second round.
        self.assertEqual(2, task.state["scrolls"])

    def test_badge_found_after_scrolling_is_claimed(self):
        def screens(state):
            if state["scrolls"] and "活动通行证" not in state["claims"]:
                return [469], [box("服装通行证", 407), box("活动通行证", 514)]
            return [], [box("基础通行证", 300)]

        task = self._task(screens)
        self.assertTrue(PassRewardTask.run_claim(task))
        self.assertEqual(["活动通行证"], task.state["claims"])

    def test_badge_that_stays_is_left_after_two_claims(self):
        task = self._task(lambda _state: ([255], [box("基础通行证", 300)]))
        self.assertTrue(PassRewardTask.run_claim(task))
        self.assertEqual(["基础通行证", "基础通行证"], task.state["claims"])
        self.assertTrue(any("基础通行证" in line and "没领" in line for line in task.logs))

    def test_claim_that_stays_lit_fails_the_task(self):
        task = self._task(lambda _state: ([255], [box("基础通行证", 300)]), claim_ok=False)
        self.assertFalse(PassRewardTask.run_claim(task))
        self.assertEqual([], task.left)
        self.assertIn("基础通行证", task.info["状态"])

    def test_traditional_caption_is_simplified(self):
        task = self._task(lambda _state: ([255], [box("滿月赛季通行证", 300)]))
        frame = badged_frame([255])
        self.assertEqual(("满月赛季通行证",), PassRewardTask._next_pass_badge(task, frame, {})[1:])

    def test_purchase_caption_is_never_a_pass_card(self):
        task = self._task(lambda _state: ([], [box("基础通行证"), box("购买高级通行证")]))
        self.assertEqual(["基础通行证"], PassRewardTask._pass_cards(task))


class PassFallbackTest(unittest.TestCase):
    """Player 2026-10-26: 角色通行证 never claimed, no error, the task 完成.
    A badged pass whose 全部获得 is missing or grey is tried on the whole
    panel and on the red-badged tabs; what is still left is said."""

    def _task(self, outcomes, tab_badges=()):
        """``outcomes`` maps a ClaimButton to the outcomes of its presses."""
        task = object.__new__(PassRewardTask)
        task.name = "领取通行证"
        task.info_set = lambda *_a: None
        task.logs, task.warnings, task.claims, task.clicks = [], [], [], []
        task.log_info = lambda text, **_k: task.logs.append(text)
        task.log_warning = lambda text, **_k: task.warnings.append(text)
        task._pass_misses = {}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for y in tab_badges:
            frame[y - 8 : y + 8, PASS_TAB_BADGE_STRIP[0] + 10 : PASS_TAB_BADGE_STRIP[0] + 27] = (
                0, 0, 230,
            )
        task.capture_frame = lambda: frame
        task._click_reference = lambda x, y, **_k: task.clicks.append((x, y))
        queues = {key: list(value) for key, value in outcomes.items()}

        def fake_claim(label, button, _title):
            task.claims.append(label)
            task._claim_outcome = queues[button].pop(0)
            return True

        task._claim_all = fake_claim
        return task

    def test_missing_button_is_found_on_the_whole_panel(self):
        task = self._task({PASS_CLAIM_BUTTON_WIDE: [CLAIM_PRESSED]})
        task._claim_outcome = CLAIM_NO_BUTTON
        self.assertTrue(PassRewardTask._claim_pass_elsewhere(task, "角色通行证"))
        self.assertEqual(["角色通行证（整块面板）"], task.claims)
        self.assertEqual({}, task._pass_misses)

    def test_grey_button_opens_the_badged_tab_and_claims_there(self):
        task = self._task({PASS_CLAIM_BUTTON: [CLAIM_PRESSED]}, tab_badges=(658,))
        task._claim_outcome = CLAIM_GREY
        self.assertTrue(PassRewardTask._claim_pass_elsewhere(task, "角色通行证"))
        self.assertEqual([(1593, 680)], task.clicks)
        self.assertEqual(["角色通行证（右侧分页）"], task.claims)
        self.assertEqual({}, task._pass_misses)

    def test_nothing_anywhere_keeps_the_reason(self):
        task = self._task({PASS_CLAIM_BUTTON_WIDE: [CLAIM_NO_BUTTON]})
        task._claim_outcome = CLAIM_NO_BUTTON
        self.assertTrue(PassRewardTask._claim_pass_elsewhere(task, "角色通行证"))
        self.assertEqual([], task.clicks)
        self.assertIn("没看到「全部获得」", task._pass_misses["角色通行证"])

    def test_pressed_claim_needs_no_fallback(self):
        task = self._task({})
        task._claim_outcome = CLAIM_PRESSED
        self.assertTrue(PassRewardTask._claim_pass_elsewhere(task, "角色通行证"))
        self.assertEqual([], task.claims)

    def test_unclaimed_badge_is_a_warning_and_a_report_note(self):
        task = PassBadgeTest._task(PassBadgeTest(), lambda _s: ([255], [box("角色通行证", 300)]))
        task.warnings = []
        task.log_warning = lambda text, **_k: task.warnings.append(text)

        def grey_claim(label, _button, _title):
            task.state["claims"].append(label)
            task._claim_outcome = CLAIM_GREY
            return True

        task._claim_all = grey_claim
        with mock.patch("src.tasks.RewardClaimTasks.run_report.add_current_note") as note:
            self.assertTrue(PassRewardTask.run_claim(task))
        self.assertTrue(any("角色通行证" in w and "灰的" in w for w in task.warnings))
        self.assertIn("没领到", note.call_args.args[0])

    def test_real_character_pass_claimables_sit_on_the_mission_tab(self):
        # 毁灭之星艾瑞克角色通行证, 4K clone 2026-10-26: grey on the star tab,
        # red ◆! on the 任务 tab, whose 全部获得 is lit.
        from src.tasks.claim_page import claim_button_dimmed

        button = SimpleNamespace(x=1396, y=750, width=90, height=28)
        reward = cv2.imread(str(CHARACTER_PASS / "character_pass_reward_tab_fhd.png"))
        mission = cv2.imread(str(CHARACTER_PASS / "character_pass_mission_tab_fhd.png"))
        self.assertTrue(claim_button_dimmed(reward, button))
        self.assertEqual([(1593, 680)], PassRewardTask._badged_pass_tabs(reward))
        self.assertFalse(claim_button_dimmed(mission, button))

    def test_real_pass_page_badges(self):
        frame = cv2.imread(str(PASS_FIXTURE), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        self.assertEqual([288, 394], find_red_badges(frame, PASS_BADGE_STRIP))
        self.assertEqual([(1593, 680)], PassRewardTask._badged_pass_tabs(frame))


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
