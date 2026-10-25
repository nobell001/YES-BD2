"""A swallowed press is repeated once, only while the pre-click screen is
still confirmed (never a second action on a screen that already moved on)."""

import unittest
from time import monotonic
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

import numpy as np

from src.tasks import recovery
from src.tasks.map_trade.models import MatchResult
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_constants import (
    BARGAIN_CONFIRM_POINT,
    BARGAIN_POINT,
    SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT,
)
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_cooking import CookingDetailSnapshot
from src.tasks.trigger.AutoLoginTask import TOUCH_TO_START_TEMPLATE, AutoLoginTask

FRAME = np.zeros((1080, 1920, 3), dtype=np.uint8)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds, *_a, **_k):
        self.now += seconds


def _navigator(clock, clicks, texts):
    task = SimpleNamespace(
        config={},
        sleep=clock.sleep,
        operate_click=lambda x, y, after_sleep=0.0: clicks.append((x, y)),
        info_set=lambda *_a, **_k: None,
        log_warning=lambda *_a, **_k: None,
        log_info=lambda *_a, **_k: None,
    )
    vision = SimpleNamespace(
        capture=lambda: FRAME,
        ocr_text=lambda *_a, **_k: texts(),
        simplify=lambda value: value,
        match=lambda *_a: MatchResult(-1.0, (0, 0), (0, 0)),
        passes=lambda *_a: False,
    )
    navigator = Navigator(task, vision)
    navigator.ensure_small_minimap = lambda: True
    return navigator


class ShopEntryReclickTest(unittest.TestCase):
    def test_bargain_card_is_pressed_again_while_the_menu_stays(self):
        clock, clicks = Clock(), []
        reads = iter(["砍价 对话 商店"] * 10 + ["使用砍价技能后可享受商店折扣价"])
        navigator = _navigator(clock, clicks, lambda: next(reads))
        with patch("src.tasks.map_trade.navigator_trade.monotonic", clock):
            tip = navigator._wait_for_bargain_tip("使用砍价技能后可享受商店折扣价")
        self.assertEqual("tip", tip)
        self.assertEqual([BARGAIN_POINT], clicks)

    def test_bargain_confirm_is_pressed_again_only_while_the_popup_stays(self):
        clock, clicks = Clock(), []
        shop = "购买 出售 一键购买全部收藏"
        reads = iter(["砍价成功率100% 取消"] * 16 + [shop, shop])
        navigator = _navigator(clock, clicks, lambda: next(reads))
        with patch("src.tasks.map_trade.navigator_trade.monotonic", clock):
            self.assertTrue(navigator._wait_for_bargain_shop_confirmation(timeout=10.0))
        self.assertEqual([BARGAIN_CONFIRM_POINT], clicks)

    def test_a_shop_that_opens_normally_gets_no_second_press(self):
        clock, clicks = Clock(), []
        navigator = _navigator(clock, clicks, lambda: "一键购买全部收藏")
        with patch("src.tasks.map_trade.navigator_trade.monotonic", clock):
            self.assertTrue(navigator._wait_for_bargain_shop_confirmation(timeout=10.0))
        self.assertEqual([], clicks)

    def test_plain_shop_option_is_pressed_again_while_the_menu_stays(self):
        clock, clicks = Clock(), []
        shop = "一键购买全部收藏"
        reads = iter(["对话 商店"] * 16 + [shop, shop])
        navigator = _navigator(clock, clicks, lambda: next(reads))
        option = SimpleNamespace(name="商店", x=100, y=200, width=40, height=20)
        navigator.vision.ocr_boxes = lambda *_a, **_k: [option]
        navigator.vision.click_client = lambda center, _shape, after_sleep=0: clicks.append(center)
        with patch("src.tasks.map_trade.navigator_trade.monotonic", clock):
            self.assertTrue(
                navigator._wait_for_bargain_shop_confirmation(
                    timeout=10.0, reclick_plain_option=True
                )
            )
        self.assertEqual([(120, 210)], clicks)


class CookingStartReclickTest(unittest.TestCase):
    def _trader(self, clock, clicks, details):
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(sleep=clock.sleep, info_set=lambda *_a, **_k: None)
        trader.vision = SimpleNamespace(
            match=lambda *_a: MatchResult(0.99, (0, 0), (1, 1)),
            passes=lambda *_a: True,
            click_client=lambda center, _shape, after_sleep=0: clicks.append(center),
        )
        trader._cooking_detail_snapshot = lambda _recipe: next(details)
        return trader

    def test_bright_start_button_at_max_is_pressed_once_more(self):
        clock, clicks = Clock(), []
        start = MatchResult(0.98, (1110, 975), (40, 40), pixel_score=0.96)
        bright = CookingDetailSnapshot(FRAME, start, True, 0.7)
        grey = CookingDetailSnapshot(FRAME, start, False, 0.01)
        details = iter([bright] * 20 + [grey])
        trader = self._trader(clock, clicks, details)
        with patch("src.tasks.map_trade.trader_cooking.monotonic", clock):
            self.assertTrue(trader._wait_for_cooking_started("冰镇甜点", 6.0))
        self.assertEqual([start.center], clicks)

    def test_grey_button_means_started_and_no_second_press(self):
        clock, clicks = Clock(), []
        start = MatchResult(0.98, (1110, 975), (40, 40), pixel_score=0.96)
        grey = CookingDetailSnapshot(FRAME, start, False, 0.01)
        trader = self._trader(clock, clicks, iter([grey]))
        with patch("src.tasks.map_trade.trader_cooking.monotonic", clock):
            self.assertTrue(trader._wait_for_cooking_started("冰镇甜点", 6.0))
        self.assertEqual([], clicks)

    def test_owned_count_up_means_done_and_no_second_press(self):
        # Live 2026-10-25: 50 蘑菇汤 done (91 → 141) before the grey button
        # was read; the re-press then made a 51st.
        clock, clicks = Clock(), []
        start = MatchResult(0.98, (1110, 975), (40, 40), pixel_score=0.96)
        before = CookingDetailSnapshot(FRAME, start, True, 0.78, owned=91)
        after = CookingDetailSnapshot(FRAME, start, True, 0.78, owned=141)
        trader = self._trader(clock, clicks, iter([before, after] + [after] * 20))
        trader._owned_before = 91
        with patch("src.tasks.map_trade.trader_cooking.monotonic", clock):
            self.assertTrue(trader._wait_for_cooking_started("蘑菇汤", 6.0))
        self.assertEqual([], clicks)
        self.assertTrue(trader._cooked_by_count("蘑菇汤"))
        self.assertEqual("蘑菇汤×50", trader._last_cooking_result_text)

    def test_owned_count_read_from_the_name_line(self):
        from src.tasks.map_trade.trader_cooking import _owned

        self.assertEqual(91, _owned("蘑菇汤 米 拥有91个食物"))
        self.assertEqual(1410, _owned("蘑菇汤 拥有1,410个食物"))
        self.assertIsNone(_owned("蘑菇汤"))


class FieldMapCloseTest(unittest.TestCase):
    def test_map_still_open_is_closed_again_once(self):
        clock, clicks = Clock(), []
        headers = iter(["卢戈森林 战斗区域", "卢戈森林 战斗区域", ""])
        navigator = _navigator(clock, clicks, lambda: "")
        navigator._field_map_header = lambda: next(headers)
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", clock):
            navigator._close_field_map()
        self.assertEqual([SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT] * 2, clicks)

    def test_closed_map_returns_after_the_first_look(self):
        clock, clicks = Clock(), []
        navigator = _navigator(clock, clicks, lambda: "")
        navigator._field_map_header = lambda: ""
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", clock):
            navigator._close_field_map()
        self.assertEqual([SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT], clicks)


def _login_task():
    task = object.__new__(AutoLoginTask)
    task.config = {
        "TOUCH TO START 阈值": 0.78,
        "加载页面阈值": 0.72,
        "小屋按钮阈值": 0.78,
        "小屋按钮遮挡阈值": 0.62,
        "主页 UI 等待宽限秒数": 15.0,
        "登录后主页总等待秒数": 300.0,
        "登录按钮点击 X 百分比": 72.2396,
        "登录按钮点击 Y 百分比": 65.0926,
    }
    task.info_set = lambda *_a, **_k: None
    task.log_info = lambda *_a, **_k: None
    task.log_warning = lambda *_a, **_k: None
    task._sleep_after_recognition = lambda: None
    task._home_bright_since = None
    task._waiting_home_since = None
    task._login_retry_not_before = 0.0
    task._last_clear_click_at = 0.0
    task._finished = False
    return task


class LoginReclickTest(unittest.TestCase):
    def test_title_still_up_after_login_press_is_pressed_again(self):
        task = _login_task()
        clicks = []
        task.operate_click = lambda x, y, after_sleep=0: clicks.append((x, y))
        task._state = "waiting_home"
        task._login_clicks = 1
        task._login_clicked_at = monotonic() - 6.0

        def fake_match(_frame, spec):
            if spec is TOUCH_TO_START_TEMPLATE:
                return MatchResult(0.92, (700, 600), (400, 80), pixel_score=0.92)
            return MatchResult(-1.0, (0, 0), (0, 0), pixel_score=-1.0)

        task._match = fake_match
        AutoLoginTask._wait_loading_then_home(task, FRAME)
        self.assertEqual([], clicks)  # one look is not enough
        AutoLoginTask._wait_loading_then_home(task, FRAME)
        self.assertEqual(1, len(clicks))
        self.assertEqual("waiting_loading", task._state)
        self.assertEqual(2, task._login_clicks)

    def test_press_count_is_bounded(self):
        task = _login_task()
        task.operate_click = lambda *_a, **_k: self.fail("no press past the limit")
        task._state = "waiting_home"
        task._login_clicks = 3
        task._login_clicked_at = monotonic() - 6.0
        task._match = lambda *_a: MatchResult(0.92, (0, 0), (1, 1), pixel_score=0.92)
        task._clear_popups_until_home = lambda *_a, **_k: False
        AutoLoginTask._wait_loading_then_home(task, FRAME)
        AutoLoginTask._wait_loading_then_home(task, FRAME)

    def test_long_quiet_wait_with_gated_batch_checks_in_game(self):
        task = _login_task()
        task._executor = SimpleNamespace(
            get_task_by_class=lambda _cls: SimpleNamespace(_start_after_login=True)
        )
        recovered = []
        task._finish_by_recovery = lambda: recovered.append(1) or True
        task._no_login_signal_since = monotonic() - 1000.0
        self.assertTrue(task._quiet_prelogin_recovery())
        self.assertEqual([1], recovered)

    def test_quiet_wait_without_a_gated_batch_leaves_the_game_alone(self):
        task = _login_task()
        task._executor = SimpleNamespace(get_task_by_class=lambda _cls: None)
        task._finish_by_recovery = lambda: self.fail("no recovery without a waiting batch")
        task._no_login_signal_since = monotonic() - 1000.0
        self.assertFalse(task._quiet_prelogin_recovery())


class RecoveryTitleAndBackTest(unittest.TestCase):
    def test_misread_touch_to_start_is_still_the_title(self):
        task = SimpleNamespace(capture_frame=lambda: FRAME)
        vision = SimpleNamespace(
            ocr_boxes=lambda *_a: [SimpleNamespace(name="T0UCH TO STAR")]
        )
        self.assertEqual("title", recovery._handle_dialog(task, vision))

    def test_back_press_waits_for_late_home_instead_of_pressing_again(self):
        looks = iter([False] * 8 + [True])
        navigator = SimpleNamespace(
            _home_confirmation_signals=lambda _f: (next(looks), 0, 0.0, ""),
            vision=SimpleNamespace(capture=lambda: FRAME),
        )
        clock = Clock()
        with mock.patch.object(recovery, "monotonic", clock):
            self.assertTrue(
                recovery._wait_after_back(SimpleNamespace(sleep=clock.sleep), navigator, FRAME)
            )
        self.assertGreater(clock.now, recovery.BACK_HOME_POLL_SECONDS)

    def test_back_press_returns_early_once_another_page_settled(self):
        page = np.full((1080, 1920, 3), 150, dtype=np.uint8)
        navigator = SimpleNamespace(
            _home_confirmation_signals=lambda _f: (False, 0, 0.0, ""),
            vision=SimpleNamespace(capture=lambda: page),
        )
        clock = Clock()
        with mock.patch.object(recovery, "monotonic", clock):
            self.assertFalse(
                recovery._wait_after_back(SimpleNamespace(sleep=clock.sleep), navigator, FRAME)
            )
        self.assertLess(clock.now, recovery.BACK_HOME_WAIT_SECONDS)


if __name__ == "__main__":
    unittest.main()
