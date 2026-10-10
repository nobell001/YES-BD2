"""圣石洞穴 is pressed only on the hunt menu (YES-BD2 #8 and a player's
问题摘要, v0.1.17, 1080p, 2026-10-10).

The run read neither the entry nor the cave list for 30 s, pressed the fixed
point three times anyway, and its summary only showed the home page it went
back to.  Now a leftover reward page or dialog is put away first, nothing is
pressed on a screen that is not the menu, and the log says what it showed.
"""

import unittest

from src.tasks.quick_hunt import (
    QUICK_HUNT_CRYSTAL_CLICK_ROI,
    QUICK_HUNT_CRYSTAL_ENTRY_LOOKS,
    QUICK_HUNT_CRYSTAL_POINT,
)


def _task(*, entry_after=None, strip="", whole="", reward=False, list_shown=True):
    from src.tasks.QuickHuntTask import QuickHuntTask

    task = object.__new__(QuickHuntTask)
    task.config = {"快速狩猎界面等待秒数": 8.0}
    task.logs, task.looks, task.presses, task.diagnostics = [], [], [], []
    task.info_set = lambda *_a, **_k: None
    task.log_info = lambda message, *_a, **_k: task.logs.append(message)
    task.capture_frame = lambda: None
    state = {"reward": reward}

    def click_ocr(_patterns, roi, _timeout, name):
        task.looks.append(roi)
        if entry_after is not None and len(task.looks) >= entry_after and not state["reward"]:
            task.presses.append(name)
            return True
        return False

    def ocr_text(_frame, roi, name):
        if roi is None:
            return whole
        if roi == QUICK_HUNT_CRYSTAL_CLICK_ROI:
            return strip
        return ""

    def close_reward(_stage):
        task.presses.append("结算")
        state["reward"] = False
        return True

    task._quick_hunt_click_ocr = click_ocr
    task._quick_hunt_ocr_text = ocr_text
    task._quick_hunt_reward_shown = lambda _stage: state["reward"]
    task._quick_hunt_close_reward = close_reward
    task._quick_hunt_dialog_visible = lambda _stage: False
    task._click_reference = lambda x, y, **_k: task.presses.append((x, y))
    task._quick_hunt_wait_ocr = lambda *_a, **_k: ("火之洞穴" if list_shown else "", None)
    task._save_flow_diagnostic = task.diagnostics.append
    return task


class CrystalEntryTest(unittest.TestCase):
    def test_a_screen_that_is_not_the_menu_is_not_pressed(self):
        task = _task(whole="点击画面即可 某个画面")
        self.assertFalse(task._quick_hunt_enter_crystal_cave())
        self.assertEqual([], task.presses)
        # Strip, then whole screen, on each look: one attempt only.
        self.assertEqual(2 * QUICK_HUNT_CRYSTAL_ENTRY_LOOKS, len(task.looks))
        self.assertEqual(["quick_hunt_crystal_entry_failed"], task.diagnostics)
        self.assertIn("没按圣石洞穴", "\n".join(task.logs))
        # What the screen showed is in the last line of the 问题摘要.
        self.assertIn("当时画面读到「点击画面即可 某个画面」", task.logs[-1])

    def test_a_leftover_reward_page_is_put_away_first(self):
        task = _task(entry_after=1, reward=True)
        self.assertTrue(task._quick_hunt_enter_crystal_cave())
        self.assertEqual(["结算", "圣石洞穴入口"], task.presses)

    def test_the_fixed_point_is_pressed_under_a_read_menu(self):
        # Some clients' OCR misses the entry's own words (RPT-20260902-225925).
        task = _task(whole="狩猎场 冒险航线")
        self.assertTrue(task._quick_hunt_enter_crystal_cave())
        self.assertEqual([QUICK_HUNT_CRYSTAL_POINT], task.presses)

    def test_a_list_that_never_shows_says_what_was_on_screen(self):
        task = _task(entry_after=1, list_shown=False, whole="狩猎场 冒险航线 圣石洞穴")
        self.assertFalse(task._quick_hunt_enter_crystal_cave())
        self.assertEqual(3, len(task.presses))
        self.assertIn("圣石洞穴没进去", task.logs[-1])
        self.assertIn("狩猎场 冒险航线 圣石洞穴", task.logs[-1])


if __name__ == "__main__":
    unittest.main()
