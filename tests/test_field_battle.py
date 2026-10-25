"""A field battle met on the way, and popups closed by every page wait.

Live 2K 2026-10-22 一键日常: 跑图 第14章 walked into a monster, the game won
the battle by itself and stood on VICTORY / 「离开」 (Esc does nothing there)
while the way home pressed back, H and Esc for two minutes; 魔兽追踪者赛季奖励
over 餐厅 kept a 45 s page wait waiting.  Leo 「我說的10秒沒反應就退出或esc
這時候竟然沒有用上」.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import recovery
from src.tasks.BaseBD2Task import BaseBD2Task
from src.utils import field_battle, known_popups, wait_limits
from src.utils.press_confirm import PressOutcome
from src.utils.wait_limits import POPUP_CLOSES_MAX, POPUP_LOOK_SECONDS, ProgressWait, load_wait


def _box(name, x=100, y=100):
    return SimpleNamespace(name=name, x=x, y=y, width=40, height=20)


def _boxes(*names):
    return [_box(name, x=100 + 60 * i) for i, name in enumerate(names)]


VICTORY = ("VICTORY", "REWARD", "117", "28,000", "离开")
IN_BATTLE_AUTO = ("« TURN.1 »", "自动战斗中", "结束自动战斗", "ESC")
IN_BATTLE_MANUAL = ("« TURN.1 »", "更换", "预设", "TURN.1", "BATTLE")
MENU = ("继续", "设置", "逃跑")
FLEE_CONFIRM = ("确定要逃跑吗？", "取消", "确认")
FIELD = ("吸收", "召集", "压制")
# Live 4K 2026-10-22 (角色卡7 卡勒塔市), 1080 reference positions.
GAME_MENU = "game_menu"
GAME_FLEE_DIALOG = "game_flee_dialog"


def game_menu():
    return [
        SimpleNamespace(name="暂停", x=930, y=205, width=60, height=34),
        SimpleNamespace(name="逃跑", x=776, y=990, width=44, height=28),
        SimpleNamespace(name="重新挑战", x=962, y=990, width=84, height=28),
        SimpleNamespace(name="点击继续", x=1166, y=990, width=84, height=28),
    ]


def game_flee_dialog():
    return [
        SimpleNamespace(name="逃跑", x=930, y=440, width=60, height=34),
        SimpleNamespace(name="从战斗中逃跑后重新挑战时，敌人的生命力初", x=740, y=500, width=440, height=28),
        SimpleNamespace(name="始化为100%。是否放弃战斗逃跑？", x=786, y=537, width=340, height=28),
        SimpleNamespace(name="取消", x=838, y=619, width=44, height=28),
        SimpleNamespace(name="逃跑", x=1038, y=619, width=44, height=28),
        SimpleNamespace(name="逃跑", x=776, y=990, width=44, height=28),
    ]


class ScreensTest(unittest.TestCase):
    def test_victory_screen_leaves_by_its_button(self):
        boxes = _boxes(*VICTORY)
        self.assertIs(boxes[4], field_battle.leave_button(boxes))
        self.assertFalse(field_battle.in_battle(boxes))

    def test_power_icon_read_before_the_word(self):
        boxes = _boxes("DEFEAT", "O离开")
        self.assertIs(boxes[1], field_battle.leave_button(boxes))

    def test_leave_elsewhere_is_no_battle_result(self):
        self.assertIsNone(field_battle.leave_button(_boxes("确定要离开吗", "离开", "取消")))
        self.assertIsNone(field_battle.leave_button(_boxes("VICTORY", "离开这个箱庭吧")))

    def test_battle_screens(self):
        self.assertTrue(field_battle.in_battle(_boxes(*IN_BATTLE_AUTO)))
        self.assertTrue(field_battle.auto_on(_boxes(*IN_BATTLE_AUTO)))
        self.assertTrue(field_battle.in_battle(_boxes(*IN_BATTLE_MANUAL)))
        self.assertFalse(field_battle.auto_on(_boxes(*IN_BATTLE_MANUAL)))
        self.assertEqual("turn.1", field_battle.turn_text(_boxes(*IN_BATTLE_MANUAL)))
        self.assertFalse(field_battle.in_battle(_boxes("TURN.1")))
        self.assertFalse(field_battle.in_battle(_boxes("吸收", "召集", "压制")))

    def test_run_away_entry_and_its_confirm(self):
        self.assertIsNotNone(field_battle.flee_button(_boxes(*MENU)))
        self.assertIsNone(field_battle.flee_button(_boxes("吸收", "召集")))
        self.assertIsNotNone(field_battle.flee_confirm_button(_boxes(*FLEE_CONFIRM)))
        self.assertIsNone(field_battle.flee_confirm_button(_boxes("是否购买", "确认")))

    def test_live_dialog_button_is_the_run_away_beside_cancel(self):
        boxes = game_flee_dialog()
        self.assertIs(boxes[4], field_battle.flee_confirm_button(boxes))
        # The menu alone (its 逃跑 entry) is no confirm.
        self.assertIsNone(field_battle.flee_confirm_button(game_menu()))
        self.assertIs(game_menu()[1].name, field_battle.flee_button(game_menu()).name)

    def test_pause_menu_is_the_battle_and_its_settings_close_is_no_button(self):
        # bd2 session 2026-10-22: the Esc menu shows the cut-scene setting
        # 「关闭」; recovery pressed it as a close button ten times.
        boxes = [
            SimpleNamespace(name="暂停", x=930, y=205, width=60, height=34),
            SimpleNamespace(name="技能过场动画", x=840, y=480, width=140, height=28),
            SimpleNamespace(name="1天观看1次", x=1450, y=565, width=110, height=28),
            SimpleNamespace(name="关闭", x=1480, y=665, width=44, height=28),
            *game_menu()[1:],
        ]
        self.assertTrue(field_battle.pause_menu(boxes))
        self.assertTrue(field_battle.in_battle(boxes))
        self.assertTrue(field_battle.in_battle(game_menu()))
        # The run-away dialog is still its own screen, not the menu.
        self.assertFalse(field_battle.pause_menu(game_flee_dialog()))
        self.assertFalse(field_battle.pause_menu(_boxes("暂停", "关闭")))

    def test_shared_popup_closer_presses_leave(self):
        press = known_popups.pick(_boxes(*VICTORY))
        self.assertEqual("离开", press.label)

    def test_way_home_hands_a_battle_over_instead_of_pressing(self):
        escapes = []
        task = SimpleNamespace(
            FIELD_BATTLE_ESCAPE=True,
            capture_frame=lambda: np.zeros((1080, 1920, 3), np.uint8),
            log_info=lambda *a, **k: None,
            tap_escape=lambda after_sleep=0: escapes.append(after_sleep) or True,
        )
        vision = SimpleNamespace(ocr_boxes=lambda frame, name: _boxes(*IN_BATTLE_AUTO))
        self.assertEqual("battle", recovery._handle_dialog(task, vision))
        self.assertEqual([], escapes)

    def test_only_the_map_run_treats_a_battle_as_one_to_run_from(self):
        # Leo 2026-10-23 「撞怪逃跑這個機制只能在跑圖的時候」「其他都不要亂用」:
        # 活动每日战斗's own auto battle got Esc from the way home.
        from src.tasks.EventBattleTask import EventBattleTask
        from src.tasks.MapCollectionTask import MapCollectionTask
        from src.tasks.MapTradeTask import MapTradeTask

        self.assertTrue(MapCollectionTask.FIELD_BATTLE_ESCAPE)
        self.assertFalse(MapTradeTask.FIELD_BATTLE_ESCAPE)
        self.assertFalse(EventBattleTask.FIELD_BATTLE_ESCAPE)
        self.assertFalse(BaseBD2Task.FIELD_BATTLE_ESCAPE)
        task = SimpleNamespace(
            capture_frame=lambda: np.zeros((1080, 1920, 3), np.uint8),
            log_info=lambda *a, **k: None,
        )
        vision = SimpleNamespace(ocr_boxes=lambda frame, name: _boxes(*IN_BATTLE_AUTO))
        self.assertEqual("none", recovery._handle_dialog(task, vision))


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Task:
    """Just what leave_field_battle and press_and_confirm use (每周跑图)."""

    FIELD_BATTLE_ESCAPE = True

    def __init__(self, screens, clock):
        self.screens = list(screens)
        self.clock = clock
        self.clicks = []
        self.logs = []
        self.popups = []
        self.escapes = []

    def capture_frame(self):
        return np.zeros((1080, 1920, 3), np.uint8)

    def ocr(self, frame=None, name="", reread=False):
        screen = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        if screen == GAME_MENU:
            return game_menu()
        if screen == GAME_FLEE_DIALOG:
            return game_flee_dialog()
        return _boxes(*screen)

    def operate_click(self, x, y, **_kwargs):
        self.clicks.append((round(x, 3), round(y, 3)))

    def log_info(self, message, **_kwargs):
        self.logs.append(message)

    def info_set(self, *_args):
        pass

    def sleep(self, seconds):
        self.clock.sleep(seconds)

    def close_known_popup(self, label="", info_only=False):
        return bool(self.popups.pop(0)) if self.popups else False

    def tap_escape(self, after_sleep=0.0):
        self.escapes.append(after_sleep)
        return True

    _ocr_box_center = staticmethod(BaseBD2Task._ocr_box_center)
    leave_field_battle = BaseBD2Task.leave_field_battle
    _battle_boxes = BaseBD2Task._battle_boxes
    _click_battle_box = BaseBD2Task._click_battle_box
    _press_battle_leave = BaseBD2Task._press_battle_leave
    _confirm_flee = BaseBD2Task._confirm_flee
    press_and_confirm = BaseBD2Task.press_and_confirm


class LeaveBattleTest(unittest.TestCase):
    def test_a_task_other_than_the_map_run_never_runs_away(self):
        task = _Task([IN_BATTLE_AUTO], _Clock())
        task.FIELD_BATTLE_ESCAPE = False
        self.assertEqual("none", task.leave_field_battle("活动每日战斗", _boxes(*IN_BATTLE_AUTO)))
        self.assertEqual([], task.escapes)
        self.assertEqual([], task.clicks)

    """Leo 2026-10-22 「判定進戰鬥 就直接按esc 1秒按一下 最多按4下 看到有逃跑就不按」."""

    def setUp(self):
        self.clock = _Clock()
        self.patch = mock.patch("src.tasks.BaseBD2Task.monotonic", self.clock)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_no_battle_presses_nothing(self):
        task = _Task([("吸收", "召集")], self.clock)
        self.assertEqual("none", task.leave_field_battle("跑图"))
        self.assertEqual([], task.clicks)
        self.assertEqual([], task.escapes)

    def test_auto_battle_turned_off_then_run_away(self):
        # The first Esc ends the auto battle, the second opens the menu.
        task = _Task([IN_BATTLE_MANUAL, MENU, FLEE_CONFIRM, FIELD], self.clock)
        self.assertEqual("left", task.leave_field_battle("跑图", _boxes(*IN_BATTLE_AUTO)))
        self.assertEqual(2, len(task.escapes))
        self.assertEqual(2, len(task.clicks))  # 逃跑, then 确认

    def test_manual_battle_opens_the_menu_at_once(self):
        task = _Task([MENU, FIELD], self.clock)
        self.assertEqual("left", task.leave_field_battle("跑图", _boxes(*IN_BATTLE_MANUAL)))
        self.assertEqual(1, len(task.escapes))
        self.assertEqual(1, len(task.clicks))

    def test_menu_without_run_away_says_what_it_read(self):
        task = _Task([("继续", "设置")], self.clock)
        why = task.leave_field_battle("跑图", _boxes(*IN_BATTLE_MANUAL))
        self.assertIn("逃跑", why)
        self.assertIn("继续", why)
        self.assertEqual([], task.clicks)
        self.assertEqual(field_battle.ESC_PRESSES_MAX, len(task.escapes))

    def test_live_flee_dialog_presses_its_own_run_away(self):
        # Live 4K 2026-10-22 角色卡7: the dialog's button reads 逃跑, not 确认,
        # and the run stayed on it for 10 s.
        task = _Task([GAME_MENU, GAME_FLEE_DIALOG, FIELD], self.clock)
        self.assertEqual("left", task.leave_field_battle("跑图", _boxes(*IN_BATTLE_MANUAL)))
        self.assertEqual(2, len(task.clicks))
        self.assertEqual((0.552, 0.586), task.clicks[1])  # 取消's row, right of it

    def test_dialog_already_open_is_confirmed(self):
        task = _Task([FIELD], self.clock)
        self.assertEqual("left", task.leave_field_battle("跑图", game_flee_dialog()))
        self.assertEqual([], task.escapes)
        self.assertEqual(1, len(task.clicks))

    def test_result_screen_presses_leave(self):
        task = _Task([FIELD], self.clock)
        self.assertEqual("left", task.leave_field_battle("跑图", _boxes(*VICTORY)))
        self.assertEqual([], task.escapes)
        self.assertEqual(1, len(task.clicks))


class PressAfterPopupTest(unittest.TestCase):
    def test_press_swallowed_by_a_popup_is_made_again(self):
        clock = _Clock()
        task = _Task([()], clock)
        task.popups = [True]
        presses = []
        state = {"page": False}

        def press():
            presses.append(1)
            state["page"] = len(presses) >= 3

        outcome = task.press_and_confirm(
            "公会入口",
            press,
            lambda: state["page"],
            still_before=lambda: True,
            timeout=0.0,
            retry_after=0.0,
        )
        self.assertTrue(outcome)
        self.assertEqual(3, len(presses))

    def test_spend_press_is_never_repeated(self):
        task = _Task([()], _Clock())
        task.popups = [True]
        presses = []
        outcome = task.press_and_confirm(
            "购买", lambda: presses.append(1), lambda: False, still_before=lambda: True, retries=0, timeout=0.0
        )
        self.assertIsInstance(outcome, PressOutcome)
        self.assertFalse(outcome)
        self.assertEqual(1, len(presses))
        self.assertEqual([True], task.popups)


class PageWaitClosesPopupsTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.answers = []
        wait_limits.set_popup_closer(lambda: self.calls.append(1) or (self.answers.pop(0) if self.answers else False))
        wait_limits.set_loading_reader(None)

    def tearDown(self):
        wait_limits.set_popup_closer(None)

    def _moving(self, t):
        # Sparkles over the page: the picture keeps changing.
        return np.full((108, 192, 3), int(t * 10) % 250, np.uint8)

    def test_animated_overlay_is_closed_and_the_wait_goes_on(self):
        self.answers = [True]
        wait = load_wait(0.0, 45.0)
        for t in range(int(POPUP_LOOK_SECONDS)):
            self.assertFalse(wait.over(self._moving(t), float(t)))
        self.assertEqual([], self.calls)
        self.assertFalse(wait.over(self._moving(4), POPUP_LOOK_SECONDS))
        self.assertEqual(1, len(self.calls))

    def test_no_popup_looks_again_later_not_every_frame(self):
        wait = load_wait(0.0, 45.0)
        for t in range(12):
            wait.over(self._moving(t), t * 0.5 + POPUP_LOOK_SECONDS)
        self.assertEqual(2, len(self.calls))

    def test_closes_are_capped(self):
        self.answers = [True] * 10
        wait = load_wait(0.0, 45.0)
        t = 0.0
        while t < 40:
            wait.over(self._moving(t), t)
            t += 1.0
        self.assertEqual(POPUP_CLOSES_MAX, len(self.calls))

    def test_result_waits_and_plain_waits_close_nothing(self):
        self.answers = [True]
        for wait in (load_wait(0.0, 45.0, popups=False), ProgressWait(0.0)):
            for t in range(20):
                wait.over(self._moving(t), float(t))
        self.assertEqual([], self.calls)

    def test_still_screen_without_popup_is_still_stuck_after_10_s(self):
        still = np.full((108, 192, 3), 120, np.uint8)
        wait = load_wait(0.0, 10.0)
        self.assertFalse(wait.over(still, 0.0))
        self.assertFalse(wait.over(still, POPUP_LOOK_SECONDS))
        self.assertTrue(wait.over(still, 10.0))



class AfterEscapeOrderTest(unittest.TestCase):
    def test_suppress_goes_first_after_running_away(self):
        # Leo 2026-10-22 「逃跑完 就優先按壓制 再按其他的」「先把怪清掉」.
        from src.tasks.map_trade.collector import AFTER_ESCAPE_ACTIONS
        from src.tasks.map_trade.collector_constants import BATTLE_ACTIONS, SUPPRESS_ACTION

        self.assertIs(SUPPRESS_ACTION, AFTER_ESCAPE_ACTIONS[0])
        self.assertEqual(set(BATTLE_ACTIONS), set(AFTER_ESCAPE_ACTIONS))
        self.assertEqual(len(BATTLE_ACTIONS), len(AFTER_ESCAPE_ACTIONS))


if __name__ == "__main__":
    unittest.main()
