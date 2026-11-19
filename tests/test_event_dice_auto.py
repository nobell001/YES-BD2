"""骰子活动 (Leo 2026-11-19 「他骰子沒有按自動運行」): the dice page turns on
「自动进行」 and lets the dice roll, instead of pressing 掷骰子 one at a time;
the second pass looks again at an event that kept its badge."""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.EventRewardTask import (
    STILL_BADGED,
    EventRewardTask,
    auto_switch_state,
    switch_changed,
)

FIXTURE = Path(__file__).parent / "fixtures" / "event_dice_auto_off_1003.png"
# Leo's 4K 繁中 11-19 (2560x1440): 7 dice, 「丟骰子」 lit, switch off.
FIXTURE_TW = Path(__file__).parent / "fixtures" / "event_dice_auto_off_tw_1119.png"
# The same page on the 简中 client (Leo 11-19): 「掷骰子」, 「自动进行」.
FIXTURE_CN = Path(__file__).parent / "fixtures" / "event_dice_auto_off_cn_1119.png"
# Where the fixture crop sits in the 1920x1080 reference frame.
CROP_AT = (1240, 690)


def _box(name, x, y, w=90, h=24):
    return SimpleNamespace(name=name, x=x, y=y, width=w, height=h)


# OCR boxes of the 10-03 dice page (4K 简中), reference pixels.
LABEL = _box("自动进行", 1508, 711, 76, 22)
DICE = _box("掷骰子", 1345, 752, 70, 24)


def _dice_page(on=False, colour=False, fixture=FIXTURE):
    """The real 10-03 dice page row (switch off); on = knob mirrored right."""
    crop = cv2.imread(str(fixture))
    reference = np.full((1080, 1920, 3), 60, dtype=np.uint8)
    x, y = CROP_AT
    reference[y : y + crop.shape[0], x : x + crop.shape[1]] = crop
    if on or colour:
        task = object.__new__(EventRewardTask)
        switch = task._auto_switch_box([LABEL, DICE])
        x0, y0 = int(switch.x), int(switch.y)
        x1, y1 = x0 + int(switch.width), y0 + int(switch.height)
        if on:
            reference[y0:y1, x0:x1] = reference[y0:y1, x0:x1][:, ::-1]
        if colour:
            reference[y0:y1, x0:x1] = (60, 200, 90)
    return reference


class AutoSwitchTest(unittest.TestCase):
    def setUp(self):
        task = object.__new__(EventRewardTask)
        self.switch = task._auto_switch_box([LABEL, DICE])

    def test_switch_is_under_its_label_on_the_dice_row(self):
        centre = (self.switch.x + self.switch.width / 2, self.switch.y + self.switch.height / 2)
        self.assertAlmostEqual(1546, centre[0], delta=6)
        self.assertAlmostEqual(764, centre[1], delta=6)

    def test_switch_without_the_dice_button_read(self):
        task = object.__new__(EventRewardTask)
        switch = task._auto_switch_box([LABEL])
        self.assertAlmostEqual(764, switch.y + switch.height / 2, delta=6)

    def test_switch_beside_the_dice_button_when_the_label_is_not_read(self):
        task = object.__new__(EventRewardTask)
        switch = task._auto_switch_box([DICE])
        self.assertAlmostEqual(1546, switch.x + switch.width / 2, delta=8)
        self.assertAlmostEqual(764, switch.y + switch.height / 2, delta=6)
        self.assertIs(False, auto_switch_state(_dice_page(fixture=FIXTURE_TW), switch))

    def test_the_real_page_reads_off(self):
        self.assertIs(False, auto_switch_state(_dice_page(), self.switch))

    def test_the_traditional_page_reads_off(self):
        task = object.__new__(EventRewardTask)
        switch = task._auto_switch_box([_box("自動進行", 1508, 711, 76, 22), _box("丟骰子", 1345, 754, 70, 26)])
        page = _dice_page(fixture=FIXTURE_TW)
        self.assertIs(False, auto_switch_state(page, switch))
        mirrored = page.copy()
        x0, y0 = int(switch.x), int(switch.y)
        x1, y1 = x0 + int(switch.width), y0 + int(switch.height)
        mirrored[y0:y1, x0:x1] = mirrored[y0:y1, x0:x1][:, ::-1]
        self.assertIs(True, auto_switch_state(mirrored, switch))

    def test_todays_simplified_page_reads_off(self):
        self.assertIs(False, auto_switch_state(_dice_page(fixture=FIXTURE_CN), self.switch))

    def test_the_traditional_dice_button_is_known(self):
        # 繁中 says 丟骰子 (not 擲骰子): before, the page had no known button.
        task = object.__new__(EventRewardTask)
        self.assertEqual("丟骰子", task._dice_button([_box("丟骰子", 1345, 754)]).name)
        self.assertEqual("擲骰子", task._dice_button([_box("擲骰子", 1345, 754)]).name)

    def test_knob_on_the_right_or_a_coloured_track_reads_on(self):
        self.assertIs(True, auto_switch_state(_dice_page(on=True), self.switch))
        self.assertIs(True, auto_switch_state(_dice_page(colour=True), self.switch))

    def test_a_flat_patch_is_not_guessed(self):
        self.assertIsNone(auto_switch_state(np.full((1080, 1920, 3), 190, np.uint8), self.switch))

    def test_a_press_the_game_took_changes_the_switch(self):
        self.assertTrue(switch_changed(_dice_page(), _dice_page(on=True), self.switch))
        self.assertFalse(switch_changed(_dice_page(), _dice_page(), self.switch))

    def test_traditional_label(self):
        task = object.__new__(EventRewardTask)
        self.assertIsNotNone(task._auto_roll_label([_box("自動進行", 1508, 711)]))
        self.assertIsNone(task._auto_roll_label([_box("开启自动进行可以连续掷骰子", 600, 700)]))


class DicePageTest(unittest.TestCase):
    """counts: what the dice counter reads on each look (the 4K 11-19 log
    read 3 dice as 「8l」); the dice button goes grey with the last one."""

    def _task(self, pages, counts, label_word="自动战斗", dice_word="丢骰子"):
        import src.tasks.EventRewardTask as module

        state = {"page": 0, "pressed": [], "logs": [], "counts": list(counts), "t": 0.0}
        task = object.__new__(EventRewardTask)
        task.info_set = lambda *a, **k: None
        task.log_info = lambda message, *a, **k: state["logs"].append(message)
        task._save_flow_diagnostic = lambda *_a: None
        task._paid_now = lambda *_a: False
        task._hand_points = lambda *_a: []
        task._settle = lambda *_a: None
        task._spin_reward_shown = lambda *_a: False
        task._spin_did_nothing = lambda *_a: False
        task.capture_frame = lambda: pages[min(state["page"], len(pages) - 1)]
        label = _box(label_word, LABEL.x, LABEL.y, LABEL.width, LABEL.height)
        dice = _box(dice_word, DICE.x, DICE.y, DICE.width, DICE.height)
        task._reference_boxes = lambda *a: [label, dice]

        def count_now(_frame):
            if len(state["counts"]) > 1:
                return state["counts"].pop(0)
            return state["counts"][0]

        task._token_text = count_now

        def press(box, **_k):
            state["pressed"].append(box.name)
            state["page"] += 1

        task._click_reference_box = press
        task.sleep = lambda seconds: state.__setitem__("t", state["t"] + seconds)
        old_monotonic, old_lit = module.monotonic, module.button_lit
        module.monotonic = lambda: state["t"]
        self.addCleanup(setattr, module, "monotonic", old_monotonic)
        self.addCleanup(setattr, module, "button_lit", old_lit)
        # Live 4K 11-19: 丢骰子 goes grey as soon as auto runs, so only the
        # first look (before the switch) sees it lit.
        module.button_lit = lambda frame, box: state["page"] == 0
        return task, state

    def test_switch_off_is_turned_on_and_the_dice_roll_by_themselves(self):
        # v0.4.3 (Leo 11-19): 「丟骰子」 and 「自動進行」 (read as 自动战斗)
        # were no known button, so the page was skipped with 3 dice left.
        task, state = self._task([_dice_page(), _dice_page(on=True)], ["7"] * 3 + ["5", "3", "1", "0", "0", "0"])
        self.assertTrue(task._press_what_is_lit("骰子游戏"))
        self.assertEqual(["自动进行开关"], state["pressed"])

    def test_simplified_page_too(self):
        task, state = self._task(
            [_dice_page(), _dice_page(on=True)], ["2", "1", "0", "0", "0"], "自动进行", "掷骰子"
        )
        task._press_what_is_lit("骰子游戏")
        self.assertEqual(["自动进行开关"], state["pressed"])

    def test_switch_already_on_is_not_pressed_off(self):
        task, state = self._task([_dice_page(on=True)], ["3", "2", "1", "0", "0", "0"])
        task._press_what_is_lit("骰子游戏")
        self.assertEqual([], state["pressed"])

    def test_auto_that_never_moves_stops_waiting_without_hand_rolls(self):
        # Leo 11-19 「只要按自動運行他就會全部丟完」: never 丟骰子 by hand
        # after the switch; a count that stays put ends the wait in 10 s.
        task, state = self._task([_dice_page(), _dice_page(on=True)], ["4"])
        task._press_what_is_lit("骰子游戏")
        self.assertEqual(["自动进行开关"], state["pressed"])
        self.assertGreaterEqual(state["t"], 10)
        self.assertLess(state["t"], 30)

    def test_switch_that_cannot_be_read_falls_back_to_rolling(self):
        flat = np.full((1080, 1920, 3), 190, np.uint8)
        task, state = self._task([flat, flat, flat], ["2", "2", "1", "0"])
        import src.tasks.EventRewardTask as module

        rolls = {"n": 0}
        module.button_lit = lambda frame, box: rolls["n"] < 2
        original = task._click_reference_box

        def press(box, **k):
            rolls["n"] += 1
            original(box, **k)

        task._click_reference_box = press
        task._press_what_is_lit("骰子游戏")
        self.assertEqual(["丢骰子", "丢骰子"], state["pressed"])

    def test_no_dice_leaves_the_switch_alone(self):
        task, state = self._task([_dice_page()], ["0"])
        import src.tasks.EventRewardTask as module

        module.button_lit = lambda frame, box: False
        task._press_what_is_lit("骰子游戏")
        self.assertEqual([], state["pressed"])

    def test_label_not_read_still_turns_auto_on(self):
        task, state = self._task([_dice_page(), _dice_page(on=True)], ["2", "1", "0", "0", "0"], label_word="DICEGAME")
        task._press_what_is_lit("骰子游戏")
        self.assertEqual(["自动进行开关"], state["pressed"])

    def test_grey_dice_button_while_auto_runs_is_not_the_end(self):
        # Live 4K 11-19: the wait ended after 4 s on the grey 丢骰子 with 3
        # dice left.  The count reads badly here (「8l」), so the end is the
        # game turning 自动进行 off by itself at 0 dice.
        task, state = self._task([_dice_page(), _dice_page(on=True)], ["8l"])
        looks = {"n": 0}
        on, off = _dice_page(on=True), _dice_page()
        task.capture_frame = lambda: off if state["page"] == 0 else (looks.__setitem__("n", looks["n"] + 1) or (on if looks["n"] < 9 else off))
        task._press_what_is_lit("骰子游戏")
        self.assertEqual(["自动进行开关"], state["pressed"])
        self.assertGreaterEqual(looks["n"], 10)
        self.assertTrue(any("自动进行已关" in line for line in state["logs"]), state["logs"])

    def test_back_on_a_page_still_rolling_waits_without_pressing(self):
        task, state = self._task([_dice_page(on=True)], ["3", "2", "1", "0", "0", "0"])
        import src.tasks.EventRewardTask as module

        module.button_lit = lambda frame, box: False
        task._press_what_is_lit("骰子游戏")
        self.assertEqual([], state["pressed"])
        self.assertTrue(any("已经开着" in line for line in state["logs"]), state["logs"])

    def test_battle_word_without_a_dice_button_is_not_a_dice_page(self):
        task, state = self._task([_dice_page()], ["5"], dice_word="开始战斗")
        task._press_what_is_lit("活动")
        self.assertNotIn("自动进行开关", state["pressed"])


class SecondPassLooksAgainTest(unittest.TestCase):
    def test_badge_left_after_two_goes_is_opened_again_on_the_second_pass(self):
        # Leo 11-19 「第二次打開活動頁檢查 他沒有去點紅色驚嘆號」.
        task = object.__new__(EventRewardTask)
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task._open_page_from_home = lambda *a: True
        task._leave_to_home = lambda *a: True
        seen = []

        def sweep(skipped):
            seen.append(dict(skipped))
            if len(seen) == 1:
                skipped["骰子游戏"] = STILL_BADGED
                skipped["满月兑换所"] = "付费页面，不碰"
                return 1
            return 0

        task._sweep_list = sweep
        self.assertTrue(task.run_claim())
        self.assertEqual({"满月兑换所": "付费页面，不碰"}, seen[1])


if __name__ == "__main__":
    unittest.main()
