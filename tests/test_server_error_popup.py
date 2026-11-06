"""Server notices during a battle (player report v0.2.26 2026-11-01 23:00).

镜中之战 38 of 40: after VICTORY the game showed 「当前并非赛季。，error:100019」
with one 确认 (every Sunday 23:00 the season settles and the server drops the
connection, Leo 2026-11-02).  Nothing knew that notice: the result wait ran
into its stuck limit, the way home could not close it, and the rest of
一键日常 stopped.  Leo: 「看到這種 就確認 然後退出 且要和用戶說賽季結算無法進行
鏡中之戰」.
"""

import unittest
from types import SimpleNamespace

import numpy as np

from src.tasks import recovery
from src.tasks.PVPTask import PVPTask
from src.utils import known_popups


def _box(name, x=100, y=100):
    return SimpleNamespace(name=name, x=x, y=y, width=40, height=20)


# What OCR reads on the player's frame (the message and its code in one box,
# or the code in a box of its own).
SEASON_NOTICE = ["当前并非赛季。，error:100019", "确认"]
SEASON_NOTICE_SPLIT = ["当前并非赛季。，", "error:100019", "确认"]


class ServerErrorRecogniseTest(unittest.TestCase):
    def test_season_notice_is_read_with_its_code(self):
        for names in (SEASON_NOTICE, SEASON_NOTICE_SPLIT):
            with self.subTest(names=names):
                boxes = [_box(n) for n in names]
                error = known_popups.server_error(boxes)
                self.assertIsNotNone(error)
                self.assertEqual("100019", error.code)
                self.assertTrue(error.season_over)
                self.assertIs(boxes[-1], error.confirm)
                self.assertEqual(
                    "镜中之战赛季结算中，无法进行镜中之战",
                    known_popups.server_error_note(error),
                )

    def test_other_codes_are_named_in_the_games_words(self):
        error = known_popups.server_error([_box("网络连接中断，error:20001"), _box("确认")])
        self.assertFalse(error.season_over)
        self.assertEqual(
            "游戏提示「网络连接中断」（error:20001）", known_popups.server_error_note(error)
        )

    def test_pick_presses_its_confirm_mid_task(self):
        boxes = [_box(n) for n in SEASON_NOTICE]
        press = known_popups.pick(boxes)
        self.assertEqual("确认", press.label)
        self.assertIs(boxes[1], press.box)

    def test_never_with_cancel_or_a_spend_or_without_a_code(self):
        for names in (
            ["当前并非赛季。，error:100019", "取消", "确认"],
            ["是否购买", "消耗 100 钻石 error:100019", "确认"],
            ["当前并非赛季。", "确认"],
            ["当前并非赛季。，error:100019"],
        ):
            with self.subTest(names=names):
                self.assertIsNone(known_popups.server_error([_box(n) for n in names]))


# 「與伺服器連接中斷。重新開始遊戲 (-6)」 as OCR reads it on the live frame
# (tests/fixtures/pvp/server_disconnect_6_over_home_1440.jpg, 2026-11-06):
# raw 繁中, and after the tool's 繁→简 step.  No 「error:」 on it.
DISCONNECT_NOTICE_TW = ["公告", "與伺服器連接中斷。重新開始遊戲（-6)", "確認"]
DISCONNECT_NOTICE_CN = ["公告", "与伺服器连接中断。重新开始游戏（-6)", "确认"]


class DisconnectNoticeTest(unittest.TestCase):
    def test_disconnect_notice_is_known_in_both_scripts(self):
        for names in (DISCONNECT_NOTICE_TW, DISCONNECT_NOTICE_CN):
            with self.subTest(names=names):
                boxes = [_box(n) for n in names]
                error = known_popups.server_error(boxes)
                self.assertIsNotNone(error)
                self.assertEqual("-6", error.code)
                self.assertTrue(error.disconnected)
                self.assertFalse(error.season_over)
                self.assertIs(boxes[-1], error.confirm)
                self.assertIn("连接断了（-6）", known_popups.server_error_note(error))
                press = known_popups.pick(boxes)
                self.assertIs(boxes[-1], press.box)

    def test_a_bracketed_number_alone_is_not_a_notice(self):
        for names in (
            ["攻击力（-6)", "确认"],  # no disconnect word
            ["与伺服器连接中断。重新开始游戏（-6)", "取消", "确认"],
            ["與伺服器連接中斷。重新開始遊戲（-6)", "取消", "確認"],
            ["与伺服器连接中断。重新开始游戏（-6)"],  # no button
        ):
            with self.subTest(names=names):
                self.assertIsNone(known_popups.server_error([_box(n) for n in names]))


class WayHomeTest(unittest.TestCase):
    def test_way_home_closes_the_notice_and_says_why(self):
        clicks, warnings = [], []
        task = SimpleNamespace(
            capture_frame=lambda: np.zeros((1080, 1920, 3), np.uint8),
            log_info=lambda *a, **k: None,
            log_warning=lambda message, **k: warnings.append(message),
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y)),
            _ocr_box_center=lambda box: (box.x + 20, box.y + 10),
        )
        vision = SimpleNamespace(ocr_boxes=lambda frame, name: [_box(n) for n in SEASON_NOTICE])
        self.assertEqual("dismissed", recovery._handle_dialog(task, vision))
        self.assertEqual(1, len(clicks))
        self.assertIn("镜中之战赛季结算中，无法进行镜中之战", warnings[0])


def _pvp(notice_reads):
    """A PVPTask whose screen shows the notice for the first ``notice_reads``
    looks, then nothing."""
    events, warnings, infos = [], [], {}
    reads = {"n": notice_reads}
    task = object.__new__(PVPTask)
    task.config = {}
    task.info_set = lambda key, value: infos.__setitem__(key, value)
    task.log_warning = lambda message, notify=False: warnings.append(message)
    task.log_info = lambda *a, **k: None
    task.log_completion = lambda message: events.append(("done", message))
    task.sleep = lambda *_a: None
    task.capture_frame = lambda: np.zeros((1080, 1920, 3), np.uint8)

    def boxes(_frame, name, roi=None, **_kw):
        if name == "PVP 服务器提示" and reads["n"] > 0:
            reads["n"] -= 1
            return [_box(n) for n in SEASON_NOTICE]
        return []

    task._ocr_boxes = boxes
    task._click_frame_point = lambda frame, point, after_sleep=0.0: events.append("确认")
    return task, events, warnings, infos


class PVPServerErrorTest(unittest.TestCase):
    def test_result_wait_stops_at_the_notice_and_leaves_home(self):
        task, events, warnings, infos = _pvp(1)
        task._target_multiplier = lambda: 1
        task._ensure_pvp_hub = lambda: True
        task._start_auto_battle = lambda multiplier: "started"
        task._verified_battles = 40

        def wait(*_a, server_error_check=False, **_k):
            # The battle screen froze under the notice.
            self.assertTrue(server_error_check)
            task._close_server_error()
            return False, ""

        task._wait_for_ocr_pattern_majority = wait
        task._leave_result_after_timeout = lambda patterns, roi: events.append("leave") or True

        self.assertTrue(PVPTask.run(task))
        self.assertEqual("确认", events[0])
        self.assertIn("leave", events)
        self.assertIn("镜中之战赛季结算中，无法进行镜中之战", warnings[0])
        self.assertIn("退出镜中之战", warnings[0])
        self.assertNotIn("等待战斗结算超时", "".join(warnings))
        self.assertIn("赛季结算中", infos["状态"])

    def test_left_to_the_batch_way_home_when_it_cannot_leave(self):
        task, events, _warnings, infos = _pvp(1)
        task._target_multiplier = lambda: 1
        task._ensure_pvp_hub = lambda: True
        task._start_auto_battle = lambda multiplier: "failed"
        task._leave_result_after_timeout = lambda patterns, roi: False

        self.assertFalse(PVPTask.run(task))
        self.assertEqual(["确认"], events)
        self.assertEqual("镜中之战赛季结算中，无法进行镜中之战。", infos["状态"])

    def test_frozen_screen_is_checked_for_the_notice_before_the_stuck_limit(self):
        task, events, _warnings, _infos = _pvp(1)
        clock = {"t": 0.0}
        import src.tasks.PVPTask as module

        original = module.monotonic
        module.monotonic = lambda: clock["t"]
        try:
            def sleep(seconds):
                clock["t"] += seconds

            task.sleep = sleep
            task._ocr_text = lambda *_a, **_k: ""
            found, _text = PVPTask._wait_for_ocr_pattern_majority(
                task,
                ["反复战斗结果"],
                min_matches=1,
                timeout=10.0,
                name="PVP 结算",
                extra_wait_patterns=[("正在进行", (0, 0, 10, 10), "PVP 战斗中 OCR")],
                max_timeout=600.0,
                server_error_check=True,
            )
        finally:
            module.monotonic = original
        self.assertFalse(found)
        self.assertEqual(["确认"], events)
        self.assertLess(clock["t"], 5.0)


if __name__ == "__main__":
    unittest.main()
