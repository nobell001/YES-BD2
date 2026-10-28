"""One shared way to close popups; the way home steps back with Esc.

Leo 2026-10-12: 「共用彈窗處理」, 「建議還是逐步回主頁 連按也可以 但這遊戲按沒幾下
就會變成問你要不要關閉遊戲 所以根本不用連按」.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import recovery
from src.utils import known_popups


def _box(name, x=100, y=100):
    return SimpleNamespace(name=name, x=x, y=y, width=40, height=20)


def _boxes(*names):
    return [_box(name, x=100 + 60 * i) for i, name in enumerate(names)]


class PickTest(unittest.TestCase):
    def test_mid_task_never_cancels(self):
        self.assertIsNone(known_popups.pick(_boxes("是否使用", "取消", "确认")))

    def test_way_home_may_cancel(self):
        press = known_popups.pick(_boxes("是否使用", "取消", "确认"), allow_cancel=True)
        self.assertEqual(press.label, "取消")

    def test_purchase_confirm_is_never_picked(self):
        self.assertIsNone(known_popups.pick(_boxes("是否购买", "消耗 100 钻石", "确认")))

    def test_reward_overlays_and_info_confirms(self):
        self.assertEqual(
            known_popups.pick(_boxes("赛季奖励", "点击画面即可返回")).label, "点击画面即可返回"
        )
        self.assertEqual(known_popups.pick(_boxes("获得道具", "确认")).label, "确认")
        self.assertEqual(known_popups.pick(_boxes("公告", "关闭")).label, "关闭")

    def test_quit_dialog_is_cancelled_even_mid_task_never_confirmed(self):
        boxes = _boxes("是否退出游戏？", "取消", "确认")
        self.assertTrue(known_popups.is_quit_dialog(boxes))
        press = known_popups.pick(boxes)
        self.assertEqual(press.label, "取消")
        self.assertIs(press.box, boxes[1])

    def test_stray_settings_panel_is_cancelled_mid_task(self):
        # Live 4K clone 2026-10-23: a stray press opened 战场角色设置 over the
        # PVP field; no task opens it, so its 取消 is safe at any step.
        boxes = _boxes("战场角色设置", "剧情角色阵形", "取消", "确认")
        press = known_popups.pick(boxes)
        self.assertEqual(press.label, "取消")
        self.assertTrue(press.stray)
        self.assertIs(press.box, boxes[2])

    def test_quit_words_without_cancel_or_without_game_are_not_quit(self):
        self.assertFalse(known_popups.is_quit_dialog(_boxes("是否退出游戏？", "确认")))
        self.assertFalse(known_popups.is_quit_dialog(_boxes("退出公会", "取消")))


class BattleMenuTest(unittest.TestCase):
    """Leo's 4K 2026-10-28 16:02: the way home from a 塔洛斯 fight opened the
    battle's 暂停 menu and pressed its 「关闭」 (the 技能过场动画 setting) 11
    times as if it closed a popup."""

    MENU = (
        "暂停", "简化版技能过场动画", "技能过场动画", "过场动画单独设置", "每次观看",
        "1天观看1次", "仅观看新技能", "关闭", "整体音量", "BGM音量", "离开", "重新挑战",
        "点击继续",
    )

    def test_only_continue_is_pressed_never_the_close_setting(self):
        for allow_cancel in (False, True):
            press = known_popups.pick(_boxes(*self.MENU), allow_cancel=allow_cancel)
            self.assertEqual(press.label, "点击继续")
            self.assertEqual(press.box.name, "点击继续")

    def test_the_field_battle_menu_too(self):
        press = known_popups.pick(_boxes("暂停", "关闭", "逃跑", "重新挑战", "点击继续"))
        self.assertEqual(press.label, "点击继续")

    def test_a_plain_close_button_still_closes(self):
        self.assertEqual(known_popups.pick(_boxes("活动公告", "关闭")).label, "关闭")
        self.assertFalse(known_popups.is_battle_menu(_boxes("点击继续")))

    def test_leos_picture(self):
        import cv2

        from tests.test_page_lookalikes import ONNXPaddleOcr, navigator_with_real_ocr

        if ONNXPaddleOcr is None:
            self.skipTest("no OCR")
        from pathlib import Path

        picture = Path(__file__).parent / "fixtures/talos/pause_menu_leo_4k_as_1080.jpg"
        frame = cv2.imread(str(picture))
        boxes = navigator_with_real_ocr().task.ocr(frame=frame)
        self.assertTrue(any(box.name == "关闭" for box in boxes))  # what was pressed
        press = known_popups.pick(boxes, allow_cancel=True)
        self.assertEqual(press.label, "点击继续")
        self.assertGreater(press.box.y, 900)  # the bottom button, not the setting row


class QuitDialogOnTheWayHomeTest(unittest.TestCase):
    def test_quit_dialog_is_cancelled_and_reported(self):
        clicks = []
        task = SimpleNamespace(
            capture_frame=lambda: np.zeros((1080, 1920, 3), np.uint8),
            log_info=lambda *a, **k: None,
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y)),
            _ocr_box_center=lambda box: (box.x + 20, box.y + 10),
        )
        vision = SimpleNamespace(
            ocr_boxes=lambda frame, name: _boxes("要关闭游戏吗", "取消", "确认")
        )
        self.assertEqual("quit", recovery._handle_dialog(task, vision))
        self.assertEqual(clicks, [((160 + 20) / 1920, 110 / 1080)])


class EscapeStepTest(unittest.TestCase):
    """Back arrow does nothing → H → one Esc at a time, never after the quit dialog."""

    def _run(self, dialogs, home_after_presses=None):
        events = []
        frame = np.full((1080, 1920, 3), 120, np.uint8)
        home = {"now": False}
        navigator = SimpleNamespace(
            _home_confirmation_signals=lambda f: (home["now"], 0, 0, ""),
            vision=SimpleNamespace(capture=lambda: frame),
            classify=lambda frame=None: recovery.ScreenState.UNKNOWN,
            clear_home_announcement=lambda f: False,
        )
        outcomes = list(dialogs)

        def press(name):
            events.append(name)
            if home_after_presses is not None and len(events) >= home_after_presses:
                home["now"] = True
            return True

        task = SimpleNamespace(
            info_set=lambda *a: None,
            log_info=lambda *a, **k: None,
            sleep=lambda s: None,
            operate_click=lambda x, y, after_sleep=0: press("back"),
            tap_key=lambda key, after_sleep=0: press(key),
            tap_escape=lambda after_sleep=0: press("esc"),
        )
        with (
            mock.patch.object(recovery, "Vision", lambda t: navigator.vision),
            mock.patch.object(recovery, "Navigator", lambda t, v: navigator),
            mock.patch.object(
                recovery, "_handle_dialog", lambda t, v: outcomes.pop(0) if outcomes else "none"
            ),
            mock.patch.object(recovery, "_note_leaving_step", lambda *a: None),
            mock.patch.object(recovery, "_keep_failure_picture", lambda *a: None),
            mock.patch.object(recovery, "BACK_HOME_WAIT_SECONDS", 0.0),
            mock.patch.object(recovery, "UNKNOWN_SETTLE_SECONDS", 0.0),
        ):
            result = recovery.recover_to_home(task)
        return result, events

    def test_esc_follows_a_back_arrow_that_changed_nothing(self):
        result, events = self._run([], home_after_presses=3)
        self.assertTrue(result)
        self.assertEqual(events, ["back", "H", "esc"])

    def test_esc_is_pressed_one_at_a_time_and_at_most_three_times(self):
        result, events = self._run([])
        self.assertFalse(result)
        self.assertEqual(events.count("esc"), recovery.ESCAPE_STEPS_MAX)
        # Never two Esc in a row: the back arrow is tried between them.
        self.assertNotIn(["esc", "esc"], [events[i : i + 2] for i in range(len(events) - 1)])

    def test_no_more_esc_after_the_quit_dialog(self):
        # The first Esc brings the quit dialog; it is cancelled, Esc stops.
        result, events = self._run(["none", "none", "none", "quit"])
        self.assertFalse(result)
        self.assertEqual(events.count("esc"), 1)


if __name__ == "__main__":
    unittest.main()


class NoButtonPopupsTest(unittest.TestCase):
    """Live 2K 2026-10-22: two popups with no text button stopped 一键日常."""

    def test_season_reward_without_button_is_tapped_on_its_line(self):
        boxes = _boxes("魔兽追踪者赛季奖励", "深渊魔姬卡（水）", "奖励", "奖励已发放至背包。")
        press = known_popups.pick(boxes)
        self.assertEqual("点击画面返回", press.label)
        self.assertIs(boxes[3], press.box)

    def test_season_reward_with_confirm_still_presses_confirm(self):
        boxes = _boxes("奖励已发放至背包", "确认")
        self.assertEqual("确认", known_popups.pick(boxes).label)

    def test_notice_list_closes_with_esc(self):
        boxes = _boxes(
            "公告",
            "10月22日(四)定期维护及更新完成公告",
            "2026年10月22日",
            "公告",
            "10月22日更新后出售的商品资讯",
            "2026年10月20日",
            "更新",
            "2026年10月20日",
        )
        self.assertTrue(known_popups.is_notice_list(boxes))
        press = known_popups.pick(boxes)
        self.assertEqual(known_popups.ESC_LABEL, press.key)

    def test_one_dated_line_is_not_a_notice_list(self):
        self.assertFalse(known_popups.is_notice_list(_boxes("公告", "2026年10月22日")))
        self.assertIsNone(known_popups.pick(_boxes("公告", "2026年10月22日", "购买")))

    def _pass_signin(self):
        # Live 4K 2026-10-22 (3840x2160), 「午夜装扮之选通行证」 over 主页.
        return [
            SimpleNamespace(name="我的小屋", x=200, y=340, width=90, height=50),
            SimpleNamespace(name="活动还剩13天", x=720, y=450, width=300, height=52),
            SimpleNamespace(name="签到成功", x=1652, y=1048, width=232, height=68),
            SimpleNamespace(name="午夜装扮之选通行证", x=688, y=1155, width=696, height=80),
            SimpleNamespace(name="活动期间，连续3天签到可获得奖励", x=688, y=1255, width=900, height=50),
            SimpleNamespace(name="购买后可获得额外奖励！", x=688, y=1322, width=620, height=50),
            SimpleNamespace(name="各账号可购买0/1次", x=832, y=1469, width=380, height=48),
            SimpleNamespace(name="购买JP¥1,140", x=856, y=1552, width=416, height=80),
        ]

    def test_pass_signin_is_closed_left_of_the_panel_never_on_buy(self):
        boxes = self._pass_signin()
        press = known_popups.pick(boxes)
        self.assertEqual(known_popups.PASS_SIGNIN_LABEL, press.label)
        self.assertEqual("", press.key)
        # Left of the panel (starts at x 620), on the backdrop where the live
        # blank tap at x 338 closed it; nowhere near 购买 (x 856-1272).
        self.assertLess(press.box.x, 600)
        self.assertGreater(press.box.x, 200)
        self.assertAlmostEqual(1347, press.box.y)

    def test_pass_signin_tap_reaches_the_click(self):
        task = SimpleNamespace(
            capture_frame=lambda: np.zeros((2160, 3840, 3), np.uint8),
            log_info=lambda *a, **k: None,
            _ocr_box_center=recovery.BaseBD2Task._ocr_box_center,
            operate_click=mock.Mock(),
        )
        vision = SimpleNamespace(ocr_boxes=lambda frame, name: self._pass_signin())
        self.assertEqual("dismissed", recovery._handle_dialog(task, vision))
        x, y = task.operate_click.call_args.args
        self.assertLess(x * 3840, 600)
        self.assertGreater(y, 0.5)

    def test_buy_text_alone_is_not_the_pass_signin(self):
        self.assertIsNone(known_popups.pass_signin_spot(_boxes("通行证", "购买")))
        self.assertIsNone(known_popups.pass_signin_spot(_boxes("购买后可获得额外奖励")))
        self.assertIsNone(known_popups.pick(_boxes("通行证", "签到", "购买")))

    def test_way_home_presses_esc_for_the_notice_list(self):
        names = ("公告", "2026年10月22日", "更新", "2026年10月20日")
        escapes = []
        task = SimpleNamespace(
            capture_frame=lambda: np.zeros((1080, 1920, 3), np.uint8),
            log_info=lambda *a, **k: None,
            tap_escape=lambda after_sleep=0: escapes.append(after_sleep) or True,
        )
        vision = SimpleNamespace(ocr_boxes=lambda frame, name: _boxes(*names))
        self.assertEqual("dismissed", recovery._handle_dialog(task, vision))
        self.assertEqual(1, len(escapes))
