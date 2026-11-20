"""跑商: the shop's back, 补按 and Esc all ignored, pressed for 41 minutes
(player v0.4.6 2026-11-20, 简中, 1920x1080 windowed at 125%, no 桌面分身).

What the player's 问题摘要 showed (picture:
tests/fixtures/map_trade/trade_shop/sell_page_back_dead_player_1080_v046.jpg):

- 卖 entered 泰瑞丝's shop at 10:01:55; 返回章节主页 began at 10:02:04 and
  the run stopped at 10:43:47, still on the 出售 page.
- The log repeats 「点了商店的返回，画面还是商店页，改用补按 / 快捷键 Esc」 and
  「第N次返回主页未完成（点击返回后未识别到折扣商店关闭确认），再试」 about
  every 40 s: one return pass = back, 补按, Esc (~40 s), three passes per
  ``return_home`` (~2 min).
- ``return_home`` ran from the phase's own way home, then once per attempt
  of the generic recovery (10), then 10 more in the task's 「回主页再做一次」
  recovery: 21 x ~2 min = the 41 minutes, ~190 presses of a back that did
  nothing, and H was never tried.

Now a pass that left the screen exactly as it was is not repeated, the
recovery does not hand the same screen to the trade navigator again (also
not in the redo's recovery).  On the shop it then stops with the reason: its
only ways out are the back and Esc, both just pressed, and it has no H (Leo
2026-11-20 「在這個介面按H是沒有用的」「畫面又沒有H可以按」).  Other pages
(field, maps) go on with H and Esc.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks import recovery
from src.tasks.map_trade.models import NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "map_trade"
    / "trade_shop"
    / "sell_page_back_dead_player_1080_v046.jpg"
)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.5
        return self.now


def _player_frame():
    frame = cv2.imread(str(FIXTURE))
    assert frame is not None, FIXTURE
    return frame


def _dead_shop_navigator(test, frame):
    """The trade navigator on the player's 出售 page: nothing changes it."""

    patcher = mock.patch("src.tasks.map_trade.navigator_trade.monotonic", _Clock())
    patcher.start()
    test.addCleanup(patcher.stop)
    presses, logs = [], []
    task = SimpleNamespace(
        config={},
        operate_click=lambda *a, **_k: presses.append(("click", *a)),
        sleep=lambda *_a: None,
        log_info=lambda message, **_k: logs.append(message),
        log_warning=lambda message, **_k: logs.append(message),
        tap_escape=lambda after_sleep=0.0: presses.append("Esc") or True,
    )
    vision = SimpleNamespace(capture=lambda: frame)
    navigator = Navigator(task, vision)
    navigator._status = lambda *_a: None
    navigator._close_sale_dialog_before_return = lambda: True
    navigator._click_shop_close_control = lambda after_sleep=0.0: presses.append("返回")
    navigator._wait_for_ocr_keywords = lambda *_a, **_k: False
    navigator._discount_close_dialog_shown = lambda: False
    navigator.classify_trade = lambda *_a: ScreenState.SHOP
    navigator.classify = lambda *_a: ScreenState.SHOP
    return navigator, presses, logs


class ReturnHomeOnDeadShopTest(unittest.TestCase):
    def test_one_round_of_presses_not_three(self):
        navigator, presses, logs = _dead_shop_navigator(self, _player_frame())
        result = navigator.return_home()
        self.assertFalse(result.success)
        # Before: 3 passes x (返回, 补按, Esc) = 9 presses on the same screen.
        self.assertEqual(["返回", "返回", "Esc"], presses)
        self.assertTrue(navigator.return_home_changed_nothing)
        self.assertIn("画面没变", result.message)
        self.assertTrue(any("不再重复同样的按法" in line for line in logs), logs)

    def test_a_pass_that_moved_the_screen_still_gets_its_retry(self):
        # Something did change (a page on its way): the old three passes stay.
        frames = iter([np.full((1080, 1920, 3), value, np.uint8) for value in range(0, 250, 40)] * 4)
        navigator, presses, _logs = _dead_shop_navigator(self, None)
        navigator.vision.capture = lambda: next(frames)
        result = navigator.return_home()
        self.assertFalse(result.success)
        self.assertFalse(navigator.return_home_changed_nothing)
        self.assertEqual(9, len(presses))

    def test_a_loading_screen_is_not_given_up_on(self):
        dark = np.full((1080, 1920, 3), 5, np.uint8)
        navigator, presses, _logs = _dead_shop_navigator(self, dark)
        navigator.return_home()
        self.assertFalse(navigator.return_home_changed_nothing)
        self.assertEqual(9, len(presses))


class RecoveryOnDeadShopTest(unittest.TestCase):
    """The generic way home on the same page: the navigator once, then H
    and Esc, and in the redo's recovery not the navigator at all."""

    def _recover(self, task, frame, state=ScreenState.SHOP):
        calls = {"navigator": 0}

        class FakeNavigator:
            def __init__(self, _task, _vision):
                self.vision = SimpleNamespace(capture=lambda: frame, click_client=lambda *a, **k: None)
                self.return_home_changed_nothing = False

            def _home_confirmation_signals(self, _frame):
                return (False, 0, 0.0, "")

            def classify(self):
                return state

            def clear_home_announcement(self, _frame, _clicks=0):
                return False

            def return_home(self):
                calls["navigator"] += 1
                self.return_home_changed_nothing = True
                return NavigationResult(False, state, "点击返回后未识别到折扣商店关闭确认")

        with (
            mock.patch.object(recovery, "Navigator", FakeNavigator),
            mock.patch.object(recovery, "Vision", lambda task: SimpleNamespace(ocr_boxes=lambda *a, **k: [])),
            mock.patch.object(recovery, "_handle_dialog", lambda *_a: "none"),
            mock.patch.object(recovery, "_keep_failure_picture", lambda *_a: None),
            mock.patch.object(recovery, "top_right_home_button", lambda *_a: None),
            mock.patch.object(recovery, "monotonic", iter(range(0, 100000)).__next__),
        ):
            reached = recovery.recover_to_home(task)
        return reached, calls["navigator"]

    def _task(self):
        keys, clicks, logs = [], [], []
        task = SimpleNamespace(
            info_set=lambda *a: None,
            log_info=lambda message, **_k: logs.append(message),
            log_warning=lambda message, **_k: logs.append(message),
            sleep=lambda *_a: None,
            operate_click=lambda *a, **_k: clicks.append(a),
            tap_key=lambda key, after_sleep=0.0: keys.append(key) or True,
            tap_escape=lambda after_sleep=0.0: keys.append("Esc") or True,
            release_move_keys=lambda after_sleep=0.0: keys.append("移动键") or True,
        )
        return task, keys, clicks, logs

    def test_shop_navigator_once_then_stops_with_the_reason(self):
        task, keys, clicks, logs = self._task()
        reached, navigator_calls = self._recover(task, _player_frame())
        self.assertFalse(reached)
        # Before: return_home on each of the 10 attempts (30 rounds of presses).
        self.assertEqual(1, navigator_calls)
        # The shop has no H (Leo 2026-11-20 「畫面又沒有H可以按」); its back
        # and Esc were just pressed by the navigator: nothing more is pressed.
        self.assertEqual([], keys)
        self.assertEqual([], clicks)
        self.assertIn("商店页的返回、补按和 Esc 都没反应", task._recovery_why)

    def test_a_field_whose_way_home_did_nothing_gets_h_and_esc(self):
        task, keys, clicks, logs = self._task()
        reached, navigator_calls = self._recover(
            task, np.full((1080, 1920, 3), 90, np.uint8), state=ScreenState.SANDBOX
        )
        self.assertFalse(reached)
        self.assertEqual(1, navigator_calls)
        self.assertIn("H", keys)
        self.assertIn("Esc", keys)
        from src.tasks.map_trade.home_house import HOUSE_POINT

        self.assertNotIn(HOUSE_POINT, clicks)
        self.assertTrue(any("画面一直停在同一页没变" in line for line in logs), logs)

    def test_the_redo_recovery_does_not_press_the_navigator_again(self):
        task, _keys, _clicks, logs = self._task()
        frame = _player_frame()
        self._recover(task, frame)
        reached, navigator_calls = self._recover(task, frame)
        self.assertFalse(reached)
        self.assertEqual(0, navigator_calls)
        self.assertIn("商店页的返回、补按和 Esc 都没反应", task._recovery_why)

    def test_another_screen_gets_the_navigator_again(self):
        task, _keys, _clicks, _logs = self._task()
        self._recover(task, _player_frame())
        _reached, navigator_calls = self._recover(task, np.full((1080, 1920, 3), 200, np.uint8))
        self.assertEqual(1, navigator_calls)


class TradePhaseReturnMarksTheScreenTest(unittest.TestCase):
    def test_phase_return_hands_the_dead_screen_to_recovery(self):
        from src.tasks.MapTradeTask import MapTradeTask

        frame = _player_frame()
        navigator = SimpleNamespace(
            return_home=lambda: NavigationResult(False, ScreenState.SHOP, "画面没变"),
            return_home_changed_nothing=True,
            vision=SimpleNamespace(capture=lambda: frame),
        )
        task = SimpleNamespace(
            info_set=lambda *a: None,
            log_warning=lambda *a, **k: None,
            diagnostic_prefix="trade",
            _save_diagnostic=lambda *_a: None,
            _recover_home_after_trade=lambda: False,
        )
        self.assertFalse(MapTradeTask._return_home_after_phases(task, navigator))
        self.assertIsNotNone(getattr(task, "_navigator_dead_screen", None))


class SayWhyTest(unittest.TestCase):
    def test_nothing_said_off_windows(self):
        from src.tasks.BaseBD2Task import BaseBD2Task

        logs = []
        task = SimpleNamespace(log_warning=lambda message, **_k: logs.append(message))
        with mock.patch("src.tasks.BaseBD2Task._game_input_facts", lambda *_a: []):
            self.assertEqual("", BaseBD2Task.say_why_presses_did_nothing(task, "跑商：商店的返回"))
        self.assertEqual([], logs)

    def test_said_once_per_cause(self):
        from src.tasks.BaseBD2Task import BaseBD2Task

        logs = []
        task = SimpleNamespace(log_warning=lambda message, **_k: logs.append(message))
        facts = ["游戏窗口「没有响应」（游戏卡住了，不是工具没按）", "游戏在最前面"]
        with mock.patch("src.tasks.BaseBD2Task._game_input_facts", lambda *_a: facts):
            for _ in range(3):
                BaseBD2Task.say_why_presses_did_nothing(task, "跑商：商店的返回", (0.06, 0.05))
        self.assertEqual(1, len(logs))
        self.assertIn("没有响应", logs[0])
        self.assertIn("补按和 Esc 都没反应", logs[0])

    def test_shop_back_says_why_after_all_presses(self):
        navigator, _presses, _logs = _dead_shop_navigator(self, _player_frame())
        asked = []
        navigator.task.say_why_presses_did_nothing = lambda label, point=None: asked.append((label, point))
        navigator._close_shop_to_field()
        self.assertEqual(1, len(asked))
        label, point = asked[0]
        self.assertEqual("跑商：商店的返回", label)
        # The back pill's spot, as a fraction of the screen (1080p ~ 123,54).
        self.assertAlmostEqual(123 / 1920, point[0], delta=0.01)
        self.assertAlmostEqual(54 / 1080, point[1], delta=0.01)


if __name__ == "__main__":
    unittest.main()
