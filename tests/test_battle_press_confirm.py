"""A battle press the game swallowed never ends as done (batch 2, 2026-10-09).

镜中之战「战斗开始」 and 场数, 快速狩猎's reward tap and 末日之书「去战斗」 are
each confirmed on screen; a second press only while the screen from before
is still shown.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.tasks.PVPTask import (
    PVP_BATTLE_START_SCREEN_POINT,
    PVP_COUNT_MIN_POINT,
    PVP_COUNT_STEP_POINTS,
    PVPTask,
)


class PvpBattleStartTest(unittest.TestCase):
    """战斗开始 spends cocktails: started only when seen, re-pressed only on proof."""

    def _run(self, after_press=None, flicker=False):
        """The 4x dialog with 36/40 free; ``after_press(n, screen)`` follows press n."""
        screen = {
            "PVP 自动战斗菜单": "鲜血鸡尾酒",
            "PVP 战斗开始": "4倍战斗开始4",
            "PVP 免费鸡尾酒": "36/40 1200",
        }
        seen = SimpleNamespace(starts=0, cancels=0, warnings=[], menu_reads=0)
        task = object.__new__(PVPTask)
        task.config = {"PVP 战斗开始等待秒数": 0.0}
        task.info_set = lambda *_a, **_k: None
        task.log_info = lambda *_a, **_k: None
        task.log_warning = lambda message, **_k: seen.warnings.append(message)
        task.sleep = lambda *_a: None
        task._save_flow_diagnostic = lambda *_a: None
        task.capture_frame = lambda: np.zeros((1440, 2560, 3), dtype=np.uint8)
        task._click_template_until = lambda *_a, **_k: True
        task._ensure_free_ap_enabled = lambda: True
        task._ensure_multiplier = lambda _m: True
        # _verify_free_cost read 36 free before the press.
        task._select_battle_count = lambda _m: setattr(task, "_verified_free", 36) or True

        def ocr_text(_frame, name, roi=None, **_kw):
            if name == "PVP 自动战斗菜单" and flicker:
                seen.menu_reads += 1
                if seen.menu_reads % 2 == 0:
                    return ""
            return screen.get(name, "")

        def wait_for_ocr(_patterns, timeout, name, **_kw):
            if name == "PVP 自动战斗":
                return True, "自动战斗"
            text = screen.get("PVP 自动战斗菜单", "")
            return "鲜血鸡尾酒" in text, text

        def click_ocr_center(patterns, name, **_kw):
            if name == "PVP 取消":
                seen.cancels += 1
                screen.clear()
            return True

        def click_screen(x, y, after_sleep=0.0):
            if (x, y) == PVP_BATTLE_START_SCREEN_POINT:
                seen.starts += 1
                if after_press is not None:
                    after_press(seen.starts, screen)

        task._ocr_text = ocr_text
        task._wait_for_ocr_patterns = wait_for_ocr
        task._click_ocr_pattern_center = click_ocr_center
        task._click_screen_reference = click_screen
        return PVPTask._start_auto_battle(task, 4), seen

    @staticmethod
    def _battle_from(press):
        def after_press(n, screen):
            if n >= press:
                screen.clear()
                screen["PVP 战斗中"] = "正在进行"

        return after_press

    def test_first_press_seen_starting_is_pressed_once(self):
        state, seen = self._run(self._battle_from(1))
        self.assertEqual("started", state)
        self.assertEqual(1, seen.starts)

    def test_swallowed_press_is_pressed_again_while_the_same_dialog_shows(self):
        state, seen = self._run(self._battle_from(2))
        self.assertEqual("started", state)
        self.assertEqual(2, seen.starts)

    def test_dialog_still_up_after_the_second_press_is_not_a_battle(self):
        # Used to count as started and wait out the whole result time.
        state, seen = self._run()
        self.assertEqual("failed", state)
        self.assertEqual(2, seen.starts)
        self.assertEqual(1, seen.cancels)
        self.assertTrue(any("仍停在开战前画面" in m for m in seen.warnings))

    def test_never_pressed_again_once_the_free_count_moved(self):
        def spent(_n, screen):
            screen["PVP 免费鸡尾酒"] = "32/40 1200"

        state, seen = self._run(spent)
        self.assertEqual("failed", state)
        self.assertEqual(1, seen.starts)

    def test_never_pressed_again_on_a_dialog_read_on_one_look_only(self):
        state, seen = self._run(flicker=True)
        self.assertEqual("failed", state)
        self.assertEqual(1, seen.starts)

    def test_dialog_gone_without_a_signal_still_waits_for_the_result(self):
        def loading(_n, screen):
            screen.clear()

        state, seen = self._run(loading)
        self.assertEqual("started", state)
        self.assertEqual(1, seen.starts)


class PvpBattleCountTest(unittest.TestCase):
    """An unchanged 场数 is the free cocktails' cap only after a second press."""

    def _task(self, swallowed=(), cap=40):
        task = object.__new__(PVPTask)
        task.config = {}
        task.info_set = lambda *_a: None
        task.log_info = lambda *_a, **_k: None
        task.sleep = lambda *_a: None
        steps = {point: name for name, point in PVP_COUNT_STEP_POINTS.items()}
        deltas = {"big_plus": 10, "big_minus": -10, "plus": 1, "minus": -1}
        state = {"count": 5, "presses": 0}

        def click(x, y, after_sleep=0.0):
            state["presses"] += 1
            if (x, y) == PVP_COUNT_MIN_POINT:
                state["count"] = 1
            elif state["presses"] not in swallowed:
                state["count"] = max(1, min(cap, state["count"] + deltas[steps[(x, y)]]))

        task._click_reference = click
        task._battle_count_value = lambda: state["count"]
        settle = patch("src.tasks.PVPTask.PVP_COUNT_CONFIRM_SECONDS", 0.0)
        settle.start()
        self.addCleanup(settle.stop)
        return task, state

    def test_a_swallowed_press_is_not_taken_as_the_cap(self):
        # Press 2 is the first +1 after MIN: lost.
        task, state = self._task(swallowed={2})
        self.assertEqual(3, PVPTask._set_battle_count(task, 3))
        self.assertEqual(3, state["count"])

    def test_three_battles_are_set_and_checked_after_a_lost_press(self):
        task, _state = self._task(swallowed={2})
        checked = []
        task._verify_free_cost = lambda _m, count: checked.append(count) or True
        task.config = {"战斗场数": "3"}
        self.assertTrue(PVPTask._select_battle_count(task, 1))
        self.assertEqual([3], checked)

    def test_the_real_cap_still_stops_after_one_extra_press(self):
        task, state = self._task(cap=2)
        self.assertEqual(2, PVPTask._set_battle_count(task, 3))
        # MIN, +1 (to 2), +1 at the cap, the same +1 once more.
        self.assertEqual(4, state["presses"])


class QuickHuntRewardTapTest(unittest.TestCase):
    """The 点击画面即可返回 tap counts once the reward page is gone."""

    def _wait(self, taps_needed):
        from src.tasks.QuickHuntTask import QuickHuntTask

        task = object.__new__(QuickHuntTask)
        task.config = {}
        task.warnings = []
        task.log_warning = lambda message, **_k: task.warnings.append(message)
        task.log_info = lambda *_a, **_k: None
        task.sleep = lambda *_a: None
        task.capture_frame = lambda: None
        taps = []

        def ocr(_frame, _roi, name, small_text=False):
            if name.endswith("奖励") and len(taps) < taps_needed:
                return "点击画面即可返回"
            return ""

        task._quick_hunt_ocr_text = ocr
        task._click_mf_reference = lambda x, y, after_sleep=0.0: taps.append((x, y))
        with patch("src.tasks.quick_hunt.QUICK_HUNT_REWARD_GONE_SECONDS", 0.0):
            return task._quick_hunt_wait_result("狩猎场"), taps, task.warnings

    def test_one_tap_that_closes_the_page(self):
        result, taps, _warnings = self._wait(taps_needed=1)
        self.assertEqual("done", result)
        self.assertEqual(1, len(taps))

    def test_a_lost_tap_is_tapped_again(self):
        result, taps, _warnings = self._wait(taps_needed=2)
        self.assertEqual("done", result)
        self.assertEqual(2, len(taps))

    def test_a_page_that_stays_is_not_done(self):
        # The double check behind it would skip the route without a word.
        result, taps, warnings = self._wait(taps_needed=99)
        self.assertEqual("failed", result)
        self.assertEqual(2, len(taps))
        self.assertEqual(1, len(warnings))


class DoomBookGoBattleTest(unittest.TestCase):
    """去战斗 counts once the page is really gone, not on one missed title read."""

    def _fight(self, swallowed, title_misses=()):
        from src.tasks import DoomBookTask as module
        from src.tasks.DoomBookTask import DoomBookTask

        task = object.__new__(DoomBookTask)
        stages = []
        task.info_set = lambda key, value: stages.append(value) if key == "当前阶段" else None
        task.log_info = lambda *_a, **_k: None
        task.sleep = lambda *_a: None
        task.capture_frame = lambda: np.zeros((108, 192, 3), np.uint8)
        state = {"clicks": 0, "page": True, "title_reads": 0}

        def title(_frame):
            state["title_reads"] += 1
            return state["page"] and state["title_reads"] not in title_misses

        def boxes(_frame, _roi, name):
            if name == "去战斗" and state["page"]:
                return [SimpleNamespace(name="去战斗", x=0, y=0, width=10, height=10)]
            return []

        def click(_box, after_sleep=0.0):
            state["clicks"] += 1
            if state["clicks"] not in swallowed:
                state["page"] = False

        task._doom_page_visible = title
        task._reference_boxes = boxes
        task._click_reference_box = click
        task._new_record_visible = lambda _frame: False
        task._text_in = lambda *_a: ""
        # Back on the page after a "battle": the old false success path.
        task._back_to_field_from_page = lambda: True
        with patch.object(module, "GO_BATTLE_LEAVE_SECONDS", 0.05), patch.object(
            module, "BATTLE_TIMEOUT_SECONDS", 0.5
        ):
            return task._fight(), state, stages

    def test_swallowed_clicks_with_one_missed_title_read_are_not_a_battle(self):
        # The first look after the click misses the title; the page never left.
        ok, state, stages = self._fight(swallowed={1, 2, 3}, title_misses={2})
        self.assertFalse(ok)
        self.assertEqual(3, state["clicks"])
        self.assertNotIn("战斗中", stages)

    def test_a_lost_click_is_clicked_again_while_the_page_shows(self):
        ok, state, stages = self._fight(swallowed={1})
        self.assertEqual(2, state["clicks"])
        self.assertIn("战斗中", stages)


if __name__ == "__main__":
    unittest.main()
