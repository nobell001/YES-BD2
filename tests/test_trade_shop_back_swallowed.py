"""跑商: the discount shop's back pressed and ignored (player v0.2.27, 1080p
fullscreen at 125%, 2026-11-02).

What the player's 问题摘要 showed:

- 料理 began on the 购买 page left open by 买; the back pill was pressed
  (its template matches that very frame at 0.97, see
  tests/fixtures/map_trade/trade_shop/bought_page_player_1080_v0227.jpg) and
  the page stayed for 13 s.  One press, then 「点击返回后未识别到折扣商店关闭确认」.
- Going home, the stuck-screen watch fired (10 s with no press) inside the
  trade navigator.  Caught as a plain error it was logged 「返回章节主页异常。
  Traceback」; the fired watch then raised again in the screenshot
  (「诊断截图保存失败」 with no reason) and, after the generic way home, at the
  first look of 料理 run once more, so 料理 failed without being tried.

Now the back is pressed once more, then Esc, while the shop page still reads
(docs/dev-notes/bug-prevention.md 3 and 4), and a fired watch is said in
player words, started over, and never costs the screenshot or the retry.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks.map_trade.models import ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_constants import DISCOUNT_SHOP_CLOSE_POINT
from src.utils.frozen_screen import FrozenScreen, FrozenWatch


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.5
        return self.now


class _DiscountShop:
    """The 购买 page; the game takes or drops each back press.

    ``takes`` per back press: True opens 是否关闭折扣商店, False drops it,
    "late" opens it only after the tool stopped waiting for it.
    """

    STATES = {
        "shop": ScreenState.SHOP,
        "menu": ScreenState.MERCHANT_DIALOG,
        "field": ScreenState.SANDBOX,
        "other": ScreenState.UNKNOWN,
    }

    def __init__(self, takes=(True,), esc_takes=True, after_drop="shop"):
        self.takes = list(takes)
        self.esc_takes = esc_takes
        self.after_drop = after_drop
        self.page = "shop"
        self.dialog = False
        self.late = False
        self.presses = []

    def back(self, after_sleep=0.0):
        self.presses.append("返回")
        if self.page == "menu":
            self.page = "field"
            return
        if self.page != "shop":
            return
        take = self.takes.pop(0) if self.takes else False
        if take == "late":
            self.late = True
        elif take:
            self.dialog = True
        else:
            self.page = self.after_drop

    def escape(self, after_sleep=0.0):
        self.presses.append("Esc")
        if self.page == "shop" and self.esc_takes:
            self.dialog = True

    def click(self, x, y, after_sleep=0.0):
        if (x, y) == DISCOUNT_SHOP_CLOSE_POINT and self.dialog:
            self.presses.append("确认")
            self.dialog = False
            self.page = "menu"
        else:
            self.presses.append(("click", x, y))

    def wait_dialog(self, *_args, **_kwargs):
        shown = self.dialog
        if self.late:
            self.late, self.dialog = False, True
        return shown

    def state(self, *_args):
        return self.STATES[self.page]


def _navigator(test, screen, esc=True):
    patcher = mock.patch("src.tasks.map_trade.navigator_trade.monotonic", _Clock())
    patcher.start()
    test.addCleanup(patcher.stop)
    logs = []
    task = SimpleNamespace(
        config={},
        operate_click=screen.click,
        sleep=lambda *_a: None,
        log_info=lambda message, **_k: logs.append(message),
        log_warning=lambda message, **_k: logs.append(message),
    )
    if esc:
        task.tap_escape = screen.escape
    vision = SimpleNamespace(capture=lambda: np.zeros((1080, 1920, 3), np.uint8))
    navigator = Navigator(task, vision)
    navigator._status = lambda *_a: None
    navigator._close_sale_dialog_before_return = lambda: True
    navigator._click_shop_close_control = screen.back
    navigator._wait_for_ocr_keywords = screen.wait_dialog
    navigator._discount_close_dialog_shown = lambda: screen.dialog
    navigator.classify_trade = screen.state
    navigator.classify = screen.state
    return navigator, logs


class ShopBackRemedyTest(unittest.TestCase):
    def test_a_back_that_works_is_pressed_once(self):
        screen = _DiscountShop(takes=(True,))
        navigator, _logs = _navigator(self, screen)
        self.assertTrue(navigator._close_shop_to_field().success)
        self.assertEqual(["返回", "确认", "返回"], screen.presses)

    def test_the_players_dropped_back_is_pressed_again(self):
        screen = _DiscountShop(takes=(False, True))
        navigator, logs = _navigator(self, screen)
        self.assertTrue(navigator._close_shop_to_field().success)
        self.assertEqual(["返回", "返回", "确认", "返回"], screen.presses)
        self.assertIn("跑商：点了商店的返回，画面还是商店页，改用补按。", logs)

    def test_esc_after_two_dropped_backs(self):
        screen = _DiscountShop(takes=(False, False))
        navigator, logs = _navigator(self, screen)
        self.assertTrue(navigator._close_shop_to_field().success)
        self.assertEqual(["返回", "返回", "Esc", "确认", "返回"], screen.presses)
        self.assertIn("跑商：点了商店的返回，画面还是商店页，改用快捷键 Esc。", logs)

    def test_all_dropped_says_why_and_presses_nothing_else(self):
        screen = _DiscountShop(takes=(False, False), esc_takes=False)
        navigator, _logs = _navigator(self, screen)
        result = navigator._close_shop_to_field()
        self.assertFalse(result.success)
        self.assertEqual("点击返回后未识别到折扣商店关闭确认", result.message)
        self.assertEqual(["返回", "返回", "Esc"], screen.presses)

    def test_no_esc_without_the_key(self):
        screen = _DiscountShop(takes=(False, False))
        navigator, _logs = _navigator(self, screen, esc=False)
        self.assertFalse(navigator._close_shop_to_field().success)
        self.assertEqual(["返回", "返回"], screen.presses)

    def test_a_late_dialog_is_answered_not_pressed_beside(self):
        # A press beside 是否关闭折扣商店 could cancel it.
        screen = _DiscountShop(takes=("late",))
        navigator, _logs = _navigator(self, screen)
        self.assertTrue(navigator._close_shop_to_field().success)
        self.assertEqual(["返回", "确认", "返回"], screen.presses)

    def test_no_second_press_once_the_page_is_not_the_shop(self):
        screen = _DiscountShop(takes=(False,), after_drop="other")
        navigator, _logs = _navigator(self, screen)
        self.assertFalse(navigator._close_shop_to_field().success)
        self.assertEqual(["返回"], screen.presses)


class BargainLoopShopBackTest(unittest.TestCase):
    """循环砍价 closes only the discount shop, back to the merchant's menu:
    the same back, the same remedies (it gave up after one press)."""

    def _navigator(self, screen, **kwargs):
        navigator, logs = _navigator(self, screen, **kwargs)
        navigator._menu_bargain_readable = lambda *_a: screen.page == "menu"
        return navigator, logs

    def test_a_back_that_works_is_pressed_once(self):
        screen = _DiscountShop(takes=(True,))
        navigator, _logs = self._navigator(screen)
        self.assertTrue(navigator.close_discount_shop_to_menu().success)
        self.assertEqual(["返回", "确认"], screen.presses)

    def test_a_dropped_back_is_pressed_again_then_esc(self):
        screen = _DiscountShop(takes=(False, False))
        navigator, _logs = self._navigator(screen)
        self.assertTrue(navigator.close_discount_shop_to_menu().success)
        self.assertEqual(["返回", "返回", "Esc", "确认"], screen.presses)

    def test_a_shop_closed_earlier_lands_on_the_menu_without_a_dialog(self):
        screen = _DiscountShop(takes=(False,), after_drop="menu")
        navigator, _logs = self._navigator(screen)
        self.assertTrue(navigator.close_discount_shop_to_menu().success)
        self.assertEqual(["返回"], screen.presses)

    def test_all_dropped_says_why(self):
        screen = _DiscountShop(takes=(False, False), esc_takes=False)
        navigator, _logs = self._navigator(screen)
        result = navigator.close_discount_shop_to_menu()
        self.assertFalse(result.success)
        self.assertEqual(["返回", "返回", "Esc"], screen.presses)


def _fired_watch():
    watch = FrozenWatch()
    watch.fired = True
    return watch


class FiredWatchTest(unittest.TestCase):
    def test_the_screenshot_is_taken_even_after_the_watch_fired(self):
        from src.tasks.BaseBD2Task import BaseBD2Task

        frame = np.zeros((1080, 1920, 3), np.uint8)
        task = SimpleNamespace(_frozen_watch=_fired_watch())
        task.capture_frame = lambda: task._frozen_watch.look(frame) or frame
        self.assertIs(frame, BaseBD2Task.diagnostic_frame(task))
        self.assertEqual(0, task._frozen_watch.paused)
        # Still fired for the task's own looks: only the picture is spared.
        with self.assertRaises(FrozenScreen):
            task.capture_frame()

    def _trade_task(self, raised):
        from src.tasks.MapTradeTask import MapTradeTask

        task = object.__new__(MapTradeTask)
        calls = []
        task.info_set = lambda *_a, **_k: None
        task.log_warning = lambda message, **_k: calls.append(("warn", message))
        task.log_error = lambda message, *_a, **_k: calls.append(("error", message))
        task._save_diagnostic = lambda name: calls.append(("picture", name))
        task._recover_home_after_trade = lambda: calls.append(("home",)) or True
        task._frozen_watch = _fired_watch()

        def return_home():
            raise raised

        return task, SimpleNamespace(return_home=return_home), calls

    def test_stuck_going_home_is_said_in_player_words_and_starts_over(self):
        task, navigator, calls = self._trade_task(FrozenScreen())
        self.assertTrue(task._return_home_after_phases(navigator))
        self.assertEqual(
            [
                (
                    "warn",
                    "跑商：返回章节主页时画面 10 秒没有变化（点了没反应或认不出画面），改用通用返回。",
                ),
                ("picture", "map_trade_return_home_frozen"),
                ("home",),
            ],
            calls,
        )
        self.assertFalse(task._frozen_watch.fired)

    def test_a_program_error_going_home_is_still_logged_as_one(self):
        task, navigator, calls = self._trade_task(ValueError("x"))
        self.assertTrue(task._return_home_after_phases(navigator))
        self.assertEqual(("error", "跑商：返回章节主页异常。"), calls[0])

    def test_home_reached_ends_a_fired_watch(self):
        # Else the phase run again from home failed at its first look.
        from src.tasks import recovery

        for home in (True, False):
            with self.subTest(home=home):
                task = SimpleNamespace(_frozen_watch=_fired_watch())
                with mock.patch.object(recovery, "_recover_to_home", lambda *_a: home):
                    self.assertEqual(home, recovery.recover_to_home(task))
                self.assertEqual(not home, task._frozen_watch.fired)


if __name__ == "__main__":
    unittest.main()
