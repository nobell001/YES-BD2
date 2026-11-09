"""镜中之战 on Sunday season settlement, before a battle (繁中 4K, Leo 2026-11-08).

On the pre-battle screen a press opens nothing: the game floats
「賽季結算時無法確認。」 at the top middle for a moment and the season box at
the top left reads 「結束」.  The tool used to press 自动战斗 three times and
report 「未能开始战斗」 as a failure.  Either cue, seen only when the press
opened nothing, now means: skip 镜中之战 (nothing spent) and go home.
"""

import unittest

import numpy as np

from src.tasks import PVPTask as pvp_module
from src.tasks.PVPTask import PVPTask

NOTE = "镜中之战赛季结算中，无法进行镜中之战"


def _task(reads):
    """``reads`` maps an OCR name to the text it returns."""
    infos, logs = {}, []
    task = object.__new__(PVPTask)
    task.config = {}
    task.info_set = lambda key, value: infos.__setitem__(key, value)
    task.log_info = lambda message, **k: logs.append(message)
    task.log_warning = lambda message, **k: logs.append(message)
    task.log_completion = lambda message: logs.append(message)
    task.sleep = lambda *_a: None
    task.capture_frame = lambda: np.zeros((1080, 1920, 3), np.uint8)
    task._ocr_text = lambda frame, name, roi=None, **k: reads.get(name, "")
    return task, infos, logs


class SettlingCueTest(unittest.TestCase):
    def test_toast_in_either_script(self):
        # OCR output passes through game_text (t2s) first; the raw 繁中 is
        # also accepted in case a box is left as it was read.
        for text in ("赛季结算时无法确认。", "赛季结算时无法确认。 赛季结算时无法确认。"):
            with self.subTest(text=text):
                task, _infos, _logs = _task({"PVP 赛季结算提示": text})
                self.assertTrue(task._season_settling_toast(task.capture_frame()))
                self.assertTrue(task._season_settling_seen)

    def test_no_toast_on_a_normal_screen(self):
        for text in ("", "攻击从5SP开始，每回合都会恢复SP6个。", "赛季"):
            with self.subTest(text=text):
                task, _infos, _logs = _task({"PVP 赛季结算提示": text})
                self.assertFalse(task._season_settling_toast(task.capture_frame()))

    def test_season_box_reads_ended(self):
        task, _infos, _logs = _task({"PVP 赛季状态": "结束 ›"})
        self.assertTrue(task._season_ended_shown())
        task, _infos, _logs = _task({"PVP 赛季状态": "2498名 积分2728"})
        self.assertFalse(task._season_ended_shown())

    def test_wait_stops_early_on_the_toast(self):
        task, _infos, _logs = _task({"PVP 赛季结算提示": "赛季结算时无法确认。"})
        task._season_settling_seen = False
        found, _text = task._wait_for_ocr_patterns(
            [r"鲜血鸡尾酒"], timeout=30.0, name="PVP 自动战斗菜单",
            stop_when=task._season_settling_toast,
        )
        self.assertFalse(found)
        self.assertTrue(task._season_settling_seen)

    def test_menu_found_wins_over_any_cue(self):
        task, _infos, _logs = _task(
            {"PVP 自动战斗菜单": "鲜血鸡尾酒", "PVP 赛季结算提示": "赛季结算时无法确认。"}
        )
        found, _text = task._wait_for_ocr_patterns(
            [r"鲜血鸡尾酒"], timeout=1.0, name="PVP 自动战斗菜单",
            stop_when=task._season_settling_toast,
        )
        self.assertTrue(found)

    def test_battle_start_reads_the_toast(self):
        task, _infos, _logs = _task({"PVP 赛季结算提示": "赛季结算时无法确认。"})
        self.assertEqual("season_settling", task._battle_start_state(1))
        task, _infos, _logs = _task({"PVP 战斗中": "正在进行", "PVP 赛季结算提示": "赛季结算时无法确认。"})
        self.assertEqual("started", task._battle_start_state(1))


class SettlingRunTest(unittest.TestCase):
    def test_run_skips_and_goes_home(self):
        task, infos, logs = _task({})
        events, notes = [], []
        task._target_multiplier = lambda: 1
        task._ensure_pvp_hub = lambda: True
        task._start_auto_battle = lambda multiplier: "season_settling"
        task._close_auto_battle_dialogs = lambda: events.append("close")
        task._click_reference = lambda *a, **k: events.append("back")
        task._ensure_pvp_hub_after_leave = lambda: events.append("hub")
        task._return_home_from_pvp_hub = lambda: events.append("home") or True
        original = pvp_module.run_report.add_current_note
        pvp_module.run_report.add_current_note = notes.append
        try:
            self.assertTrue(PVPTask.run(task))
        finally:
            pvp_module.run_report.add_current_note = original
        self.assertEqual(["close", "back", "hub", "home"], events)
        self.assertEqual(NOTE, task.done_already_note)
        self.assertEqual([NOTE], notes)
        self.assertIn(NOTE, infos["状态"])
        self.assertTrue(any("跳过" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
