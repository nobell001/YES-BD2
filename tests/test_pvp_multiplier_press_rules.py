"""镜中之战 倍率: every multiplier 1~40 is pressed by the buttons' real rules.

A player's run (v0.2.31, 1920×1080 windowed, 125%, 2026-11-05) wanted 10倍
and stopped with 「倍率没能设成 10，当时倍率处读到「9倍」」: the main popup and
「9倍战斗开始 9」 both showed 9.  The tool pressed MIN +5 +1 +1 +1 +1, counting
1 +5 as 6.  Pressed in the game (2K clone, 2026-11-05, 164 presses, every value
walked by +5 / -5): from 1, +5 gives 5; otherwise +5 / -5 / +1 / -1 move by
that much and stop at 40 / 1.  So 6~39 all ended one short.  The setting
dialog's small value is misread now and then (the cocktail icon read as a
leading 「1」: 7 as 17), so the missing +1 was never pressed either.
"""

import unittest

from src.tasks.PVPTask import (
    PVP_MULTIPLIER_1_OPTION_SCREEN_POINT,
    PVP_MULTIPLIER_40_OPTION_SCREEN_POINT,
    PVP_MULTIPLIER_BUTTON_SCREEN_POINT,
    PVP_MULTIPLIER_CONFIRM_SCREEN_POINT,
    PVP_MULTIPLIER_STEP_POINTS,
    PVPTask,
)
from src.utils.pvp_dialog import (
    multiplier_after,
    multiplier_plan,
    multiplier_presses,
    steps_between,
)

# (value, press) -> value, as seen on the game's frames 2026-11-05.
LIVE = {
    (1, "big_plus"): 5,
    (2, "big_plus"): 7,
    (3, "big_plus"): 8,
    (4, "big_plus"): 9,
    (5, "big_plus"): 10,
    (6, "big_plus"): 11,
    (7, "big_plus"): 12,
    (10, "big_plus"): 15,
    (35, "big_plus"): 40,
    (36, "big_plus"): 40,
    (39, "big_plus"): 40,
    (40, "big_minus"): 35,
    (38, "big_minus"): 33,
    (11, "big_minus"): 6,
    (9, "big_minus"): 4,
    (7, "big_minus"): 2,
    (6, "big_minus"): 1,
    (3, "big_minus"): 1,
    (2, "big_minus"): 1,
    (40, "plus"): 40,
    (1, "minus"): 1,
    (9, "plus"): 10,
}


def _press(start, presses):
    value = start
    for step in presses:
        value = multiplier_after(value, step)
    return value


class PressRulesTest(unittest.TestCase):
    def test_the_rules_match_the_live_presses(self):
        for (value, step), shown in LIVE.items():
            with self.subTest(value=value, step=step):
                self.assertEqual(shown, multiplier_after(value, step))

    def test_every_multiplier_is_reached_from_min_or_max(self):
        for target in range(1, 41):
            with self.subTest(target=target):
                start, presses = multiplier_plan(target)
                self.assertIn(start, (1, 40))
                self.assertEqual(target, _press(start, presses))
                self.assertLessEqual(len(presses), 6)

    def test_the_presses_go_one_way_and_never_past_the_target(self):
        # A read on the far side of the target can then only be a misread.
        for target in range(1, 41):
            start, presses = multiplier_plan(target)
            value = start
            for step in presses:
                after = multiplier_after(value, step)
                with self.subTest(target=target, value=value, step=step):
                    if start == 1:
                        self.assertTrue(value < after <= target)
                    else:
                        self.assertTrue(target <= after < value)
                value = after

    def test_the_old_count_left_6_to_39_one_short(self):
        # What the tool pressed before: 1 +5 taken as 6.
        short = [
            target
            for target in range(1, 40)  # 40 was MAX alone
            if _press(1, steps_between(1, target, 5)) != target
        ]
        self.assertEqual(list(range(6, 40)), short)
        self.assertEqual(9, _press(1, steps_between(1, 10, 5)))

    def test_ten_is_min_then_two_big_steps(self):
        self.assertEqual((1, ["big_plus", "big_plus"]), multiplier_plan(10))

    def test_from_any_value(self):
        self.assertEqual(["plus"], multiplier_presses(9, 10))
        self.assertEqual(["minus"], multiplier_presses(11, 10))
        self.assertEqual([], multiplier_presses(10, 10))


class _Popup:
    """The auto-battle popup and its 倍率 setting dialog, pressed by the real
    rules.  ``read_setting`` is False when the dialog's small value is never
    read (the player's PC); the main popup's N倍 and 战斗开始 are read."""

    def __init__(self, main=1, read_setting=False, lose=()):
        self.main = main
        self.setting = main
        self.dialog = False
        self.read_setting = read_setting
        self.lose = list(lose)  # step presses (1-based, +/- only) the game swallows
        self.steps = 0
        self.presses = []
        self.by_point = {point: name for name, point in PVP_MULTIPLIER_STEP_POINTS.items()}

    def press_screen(self, x, y, after_sleep=0.0):
        if (x, y) == PVP_MULTIPLIER_BUTTON_SCREEN_POINT:
            self.presses.append("gear")
            self.dialog, self.setting = True, self.main
        elif (x, y) == PVP_MULTIPLIER_1_OPTION_SCREEN_POINT and self.dialog:
            self.presses.append("MIN")
            self.setting = 1
        elif (x, y) == PVP_MULTIPLIER_40_OPTION_SCREEN_POINT and self.dialog:
            self.presses.append("MAX")
            self.setting = 40
        elif (x, y) == PVP_MULTIPLIER_CONFIRM_SCREEN_POINT and self.dialog:
            self.presses.append("确认")
            self.dialog, self.main = False, self.setting

    def press_step(self, x, y, after_sleep=0.0):
        name = self.by_point[(x, y)]
        self.presses.append(name)
        self.steps += 1
        if self.steps in self.lose:
            return
        self.setting = multiplier_after(self.setting, name)


def _task(popup, cost_agrees=True):
    task = object.__new__(PVPTask)
    task.config = {}
    task.logs = []
    task.info_set = lambda *_args, **_kwargs: None
    task.log_info = task.logs.append
    task.sleep = lambda *_args: None
    task._save_flow_diagnostic = lambda *_args: None
    task._multiplier_seen = lambda: "（画面）"
    task._click_screen_reference = popup.press_screen
    task._click_reference = popup.press_step
    task._click_ocr_pattern_center = lambda *_args, **_kwargs: False
    task._wait_for_ocr_patterns = lambda *_args, **_kwargs: (popup.dialog, "")
    task._multiplier_matches = lambda value, timeout=2.0: (
        not popup.dialog and popup.main == value
    )
    task._start_cost_is = lambda value: not popup.dialog and popup.main == value
    task._setting_dialog_open = lambda _value: popup.dialog
    task._setting_multiplier_matches = lambda value: (
        popup.dialog and popup.read_setting and popup.setting == value
    )
    task._setting_multiplier_value = lambda: (
        popup.setting if popup.dialog and popup.read_setting else None
    )
    task._read_until = lambda reader: reader()
    task._set_multiplier_seen = lambda: (
        popup.main if not popup.dialog and cost_agrees else None
    )
    return task


class EnsureMultiplierTest(unittest.TestCase):
    def test_the_players_ten_is_set_even_with_the_setting_value_unread(self):
        popup = _Popup(main=1)
        task = _task(popup)

        self.assertTrue(PVPTask._ensure_multiplier(task, 10))
        self.assertEqual(10, popup.main)
        # MIN is pressed again while its 1 is not read (harmless), then +5 +5.
        self.assertEqual(
            ["gear", "MIN", "MIN", "MIN", "big_plus", "big_plus", "确认"], popup.presses
        )

    def test_every_multiplier_is_set_with_the_setting_value_unread(self):
        for target in range(1, 41):
            with self.subTest(target=target):
                popup = _Popup(main=1 if target != 1 else 40)
                self.assertTrue(PVPTask._ensure_multiplier(_task(popup), target))
                self.assertEqual(target, popup.main)

    def test_short_on_the_main_popup_reopens_and_presses_the_missing_step(self):
        # A +5 swallowed: 5 set where 10 was wanted.  The main popup and the
        # cost agree on 5, the reopened dialog reads 5, and one +5 follows.
        popup = _Popup(main=1, read_setting=True, lose=[1])
        task = _task(popup)
        task._setting_multiplier_matches = lambda value: (
            popup.dialog and popup.setting == value and value != 10
        )
        task._setting_multiplier_value = lambda: None

        self.assertTrue(PVPTask._ensure_multiplier(task, 10))
        self.assertEqual(10, popup.main)
        self.assertEqual(
            ["gear", "MIN", "big_plus", "big_plus", "确认", "gear", "big_plus", "确认"],
            popup.presses,
        )
        self.assertTrue(any("都是 5" in line for line in task.logs), task.logs)

    def test_a_reopened_dialog_whose_value_is_unread_starts_from_min(self):
        popup = _Popup(main=1, lose=[1])
        task = _task(popup)

        self.assertTrue(PVPTask._ensure_multiplier(task, 10))
        self.assertEqual(10, popup.main)
        self.assertEqual(
            ["gear", "MIN", "MIN", "MIN", "big_plus", "big_plus", "确认"] * 2,
            popup.presses,
        )

    def test_no_second_round_when_the_main_popup_and_cost_disagree(self):
        popup = _Popup(main=1, lose=[1])
        task = _task(popup, cost_agrees=False)

        self.assertFalse(PVPTask._ensure_multiplier(task, 10))
        self.assertEqual(1, popup.presses.count("gear"))
        self.assertTrue(any("没能设成 10" in line for line in task.logs), task.logs)

    def test_a_second_wrong_round_stops(self):
        popup = _Popup(main=1, lose=[1, 3])
        task = _task(popup)

        self.assertFalse(PVPTask._ensure_multiplier(task, 10))
        self.assertEqual(2, popup.presses.count("gear"))


class SetMultiplierSeenTest(unittest.TestCase):
    def _task(self, main_text, cost):
        task = object.__new__(PVPTask)
        task.sleep = lambda *_args: None
        task.capture_frame = lambda: object()
        task._ocr_text = lambda *_args, **_kwargs: main_text
        task._start_cost_on = lambda _frame: cost
        return task

    def test_main_popup_and_cost_agree(self):
        self.assertEqual(9, PVPTask._set_multiplier_seen(self._task("9倍", 9)))

    def test_disagreeing_cost_is_not_taken(self):
        self.assertIsNone(PVPTask._set_multiplier_seen(self._task("9倍", 19)))

    def test_unread_main_popup_is_not_taken(self):
        self.assertIsNone(PVPTask._set_multiplier_seen(self._task("", 9)))


if __name__ == "__main__":
    unittest.main()
