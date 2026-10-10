"""Map-trade trader tests (split from test_map_trade.py)."""

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from src.tasks.map_trade.models import (
    CARD_BY_ID,
    MERCHANT_CARD_ID,
    RECIPE_TEMPLATES,
    STORY_CARDS,
    CalendarEntry,
    MapPageMode,
    MatchResult,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator import (
    BARGAIN_CONFIRM_POINT,
    BARGAIN_POINT,
    CHAPTER_HOME_POINT,
    DISCOUNT_SHOP_CLOSE_DIALOG_REGION,
    DISCOUNT_SHOP_CLOSE_KEYWORDS,
    DISCOUNT_SHOP_CLOSE_POINT,
    DISCOUNT_SHOP_CLOSE_TIMEOUT,
    MERCHANT_PROMPT_FAILURE_MESSAGE,
    MERCHANT_PROMPT_PATTERN,
    Q_SP6_BARGAIN_CLICK_DELAY,
    Q_SP6_BARGAIN_OCR_TIMEOUT,
    Q_SP6_BARGAIN_RECHECK_DELAY,
    Q_SP6_SHOP_PRIORITY_TIMEOUT,
    QUICK_SWITCH_CARTRIDGE_REGION,
    QUICK_SWITCH_PAGE_KEYWORDS,
    QUICK_SWITCH_TEMPLATE,
    RETURN_HOME_ANNOUNCEMENT_KEYWORD_GROUPS,
    RETURN_HOME_ANNOUNCEMENT_MAX_CLICKS,
    RETURN_HOME_ANNOUNCEMENT_OCR_REGION,
    RETURN_HOME_TIMEOUT,
    SANDBOX_TEMPLATES,
    STORY_BADGE_CANDIDATE_ZNCC_SCORE,
    STORY_BADGE_SPECS,
    STORY_CATEGORY_HIGHLIGHT_MIN_RATIO,
    STORY_CATEGORY_HIGHLIGHT_REGION,
    STORY_CATEGORY_POINT,
    TRADE_STORY_NUMBER,
    LocatedStoryCard,
    Navigator,
    StoryBadgeCandidate,
    StoryBadgeDetection,
)
from src.tasks.map_trade.navigator_constants import (
    CHAPTER_HOME_RELATIVE_ROI,
    CHAPTER_HOME_TEMPLATES,
    CLASSIFY_CARD_MENU_CATEGORY_REFERENCE_ROI,
    CLASSIFY_CARD_MENU_CATEGORY_RELATIVE_ROI,
    CLASSIFY_CARD_MENU_TITLE_REFERENCE_ROI,
    CLASSIFY_CARD_MENU_TITLE_RELATIVE_ROI,
    CLASSIFY_COOKING_MATERIALS_REFERENCE_ROI,
    CLASSIFY_COOKING_MATERIALS_RELATIVE_ROI,
    CLASSIFY_COOKING_TITLE_REFERENCE_ROI,
    CLASSIFY_COOKING_TITLE_RELATIVE_ROI,
    CLASSIFY_LOADING_REFERENCE_ROI,
    CLASSIFY_LOADING_RELATIVE_ROI,
    CLASSIFY_SHOP_TABS_REFERENCE_ROI,
    CLASSIFY_SHOP_TABS_RELATIVE_ROI,
    CLASSIFY_SHOP_TITLE_REFERENCE_ROI,
    CLASSIFY_SHOP_TITLE_RELATIVE_ROI,
    MAP_MERCHANT_ICON_TEMPLATE,
    MAP_MERCHANT_ICON_TIMEOUT,
    MERCHANT_ARRIVAL_TIMEOUT,
    MERCHANT_NAV_CONFIRM_OCR_ROI,
    MERCHANT_NAV_GUIDE_TEMPLATE,
    MERCHANT_NAV_GUIDE_TIMEOUT,
    MERCHANT_NAV_LANDMARK_TIMEOUT,
    MERCHANT_NAV_MENU_OCR_ROI,
    MERCHANT_NAV_OUTCOME_TIMEOUT,
    MERCHANT_NAV_TOAST_OCR_ROI,
    MERCHANT_NAV_UNREACHABLE_KEYWORD,
    MERCHANT_PROMPT_OCR_ROI,
    MERCHANT_QUICK_ARRIVAL_TIMEOUT,
    MERCHANT_TRAVEL_DIALOG_KEYWORDS,
    MERCHANT_TRAVEL_DIALOG_OCR_ROI,
    MINIMAP_CENTER_REFERENCE,
    TRADE_CARD_SANDBOX_HITS,
)
from src.tasks.map_trade.progress import UTC_PLUS_8
from src.tasks.map_trade.trader import (
    Trader,
)
from src.tasks.map_trade.trader_constants import (
    BUY_ALL_FAVORITES_KEYWORD,
    BUY_ALL_FAVORITES_STABLE_HITS,
    BUY_CONFIRM_DIALOG_REGION,
    BUY_CONFIRM_KEYWORDS,
    BUY_CONFIRM_POINT,
    BUY_CONFIRM_PRE_CLICK_DELAY,
    BUY_CONFIRM_TIMEOUT,
    BUY_TO_SELL_POST_CLICK_DELAY,
    BUY_TO_SELL_PRE_CLICK_DELAY,
    BUY_TO_SELL_SOLD_OUT_STABLE_HITS,
    BUY_TO_SELL_SOLD_OUT_TEMPLATE,
    SALE_120_PERCENT_MARKER_BETA_TEMPLATE,
    SALE_120_PERCENT_MARKER_MAX_RESULTS,
    SALE_120_PERCENT_MARKER_PEAK_RADIUS,
    SALE_120_PERCENT_MARKER_TEMPLATE,
    SALE_CLOSE_POINT,
    SALE_CONFIRM_POINT,
    SALE_DIALOG_OPEN_MAX_CLICKS,
    SALE_DIALOG_REGION,
    SALE_DIALOG_TITLE_REGION,
    SALE_EMPTY_NAME_STABLE_HITS,
    SALE_FULL_PAGE_OCR_TARGET_HEIGHTS,
    SALE_MARKER_RELAXED_PIXEL_SCORE,
    SALE_MAX_POINT,
    SALE_NAME_FRAGMENT_MIN_CHARS,
    SALE_OCR_INTERVAL,
    SALE_SLIDER_REGION,
    SELL_MODE_POINT,
    SHOP_MODE_TITLE_REGION,
)
from src.tasks.map_trade.vision import Vision
from src.tasks.MapTradeTask import MapTradeTask
from src.utils.calibration import FHD_1080, reference_rect_to_relative_roi
from src.utils.home_confirmation import HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT
from src.utils.image_utils import relative_roi_frame, scale_reference_roi
from src.utils.template_resolution import offline_template_scale

ROOT = Path(__file__).resolve().parents[1]


class SellFlowTest(unittest.TestCase):
    def setUp(self):
        # The pre-click stillness check has its own tests
        # (test_map_trade_sale_days); here every located card is still.
        patcher = patch.object(Trader, "_candidate_unmoved", lambda *_args: True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_sale_template_trader(self, ocr_boxes, markers=()):
        trader = object.__new__(Trader)
        match_calls = []

        def match_all(frame, spec, **kwargs):
            match_calls.append((frame, spec, kwargs))
            search_roi = kwargs.get("search_roi")
            if search_roi is None:
                return tuple(markers)
            left, top, width, height = search_roi
            right = left + width
            bottom = top + height
            return tuple(
                marker
                for marker in markers
                if left <= marker.position[0]
                and top <= marker.position[1]
                and marker.position[0] + marker.size[0] <= right
                and marker.position[1] + marker.size[1] <= bottom
            )

        trader.vision = SimpleNamespace(
            ocr_boxes=ocr_boxes,
            simplify=lambda value: value,
            match_all=match_all,
            threshold_for=lambda spec: spec.threshold,
        )
        trader.task = SimpleNamespace(info_set=lambda *_args: None)
        return trader, match_calls

    @staticmethod
    def _marker_result(
        x: int,
        y: int,
        width: int = 52,
        height: int = 14,
    ) -> MatchResult:
        return MatchResult(
            0.99,
            (x, y),
            (width, height),
            pixel_score=0.98,
            zncc_score=0.97,
        )

    @staticmethod
    def _text_box(
        name: str,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            name=name,
            confidence=0.99,
            x=x,
            y=y,
            width=width,
            height=height,
        )

    def test_sale_whitelist_allows_only_intersection(self):
        trader = object.__new__(Trader)
        trader.vision = SimpleNamespace(simplify=lambda value: value)
        trader.task = SimpleNamespace(config={"出售白名单": ""})
        whitelist = trader._sale_whitelist()

        self.assertTrue(trader._entry_allowed(CalendarEntry("透明沙拉", "E1:夏日骑士"), whitelist))
        self.assertTrue(
            trader._entry_allowed(CalendarEntry("透明化沙拉", "E1:夏日骑士"), whitelist)
        )
        self.assertFalse(trader._entry_allowed(CalendarEntry("牛奶", "S2:苍蓝魔女"), whitelist))
        self.assertTrue(trader._entry_allowed(CalendarEntry("黄油", "S2:苍蓝魔女"), whitelist))

    def test_sell_page_switch_uses_given_title_region_and_waits_half_second(self):
        texts = iter(("购买", "出售"))
        ocr_calls = []
        clicks = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda _frame, name, relative_roi: (
                ocr_calls.append((name, relative_roi)) or next(texts)
            ),
            simplify=lambda value: value,
        )

        self.assertTrue(trader._ensure_sell_page())
        self.assertEqual([(*SELL_MODE_POINT, 0.5)], clicks)
        self.assertEqual(
            (226 / 1920, 24 / 1080, 359 / 1920, 80 / 1080),
            SHOP_MODE_TITLE_REGION,
        )
        self.assertEqual(
            [("商店买卖页标题", SHOP_MODE_TITLE_REGION)] * 2,
            ocr_calls,
        )

    def test_buy_and_sell_switches_current_shop_after_stable_sold_out_template(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        ocr_calls = []
        clicks = []
        sleeps = []
        match = MatchResult(
            0.96,
            (408, 248),
            (25, 15),
            pixel_score=0.96,
            zncc_score=0.96,
        )
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=sleeps.append,
            log_info=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )

        def ocr_text(_frame, name, roi=None, relative_roi=None):
            ocr_calls.append((name, roi, relative_roi))
            return "购买"

        trader.vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=ocr_text,
            simplify=lambda value: value,
            match=lambda captured, spec: (
                match
                if captured is frame and spec is BUY_TO_SELL_SOLD_OUT_TEMPLATE
                else self.fail("unexpected template match")
            ),
            passes=lambda result, spec: (
                result is match and spec is BUY_TO_SELL_SOLD_OUT_TEMPLATE
            ),
        )
        trader._ensure_sell_page = lambda: True

        self.assertTrue(trader._switch_from_completed_buy_to_sell())
        self.assertEqual(
            [(*SELL_MODE_POINT, BUY_TO_SELL_POST_CLICK_DELAY)],
            clicks,
        )
        self.assertEqual(
            [BUY_TO_SELL_PRE_CLICK_DELAY],
            [value for value in sleeps if value == BUY_TO_SELL_PRE_CLICK_DELAY],
        )
        self.assertEqual(BUY_TO_SELL_SOLD_OUT_STABLE_HITS - 1, sleeps.count(0.25))
        self.assertEqual(
            ("商店买卖页标题", None, SHOP_MODE_TITLE_REGION),
            ocr_calls[0],
        )
        self.assertEqual([ocr_calls[0]] * BUY_TO_SELL_SOLD_OUT_STABLE_HITS, ocr_calls)

    def test_buy_and_sell_accepts_sell_page_without_waiting_for_sold_out(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            sleep=lambda *_args: self.fail("出售页不应等待售罄"),
            operate_click=lambda *_args, **_kwargs: self.fail("出售页不应再次点击"),
            log_info=lambda *_args, **_kwargs: None,
        )
        trader.vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda *_args, **_kwargs: "出售",
            simplify=lambda value: value,
            match=lambda *_args, **_kwargs: self.fail("出售页不应匹配售罄模板"),
        )

        self.assertTrue(trader._switch_from_completed_buy_to_sell())

    def test_sell_page_switch_retries_when_first_click_is_ignored(self):
        texts = iter(("购买", "购买", "出售"))
        clicks = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda *_args, **_kwargs: next(texts),
            simplify=lambda value: value,
        )

        self.assertTrue(trader._ensure_sell_page())
        self.assertEqual([(*SELL_MODE_POINT, 0.5)] * 2, clicks)

    def test_run_sell_after_buy_reuses_current_shop_without_home_navigation(self):
        actions = []
        trader = object.__new__(Trader)
        trader.owned_items_at_max_rate = lambda: None
        trader._buy_completed_in_current_shop = True
        trader.task = SimpleNamespace(log_info=lambda *_args: None)
        trader._resolve_sale_entries = lambda: [
            CalendarEntry("水果罐头", "S2:苍蓝魔女")
        ]
        trader.navigator = SimpleNamespace()
        trader._switch_from_completed_buy_to_sell = lambda: actions.append("switch") or True
        trader.sell_max_price_items = lambda: actions.append("sell") or True

        self.assertTrue(trader.run_sell())
        self.assertEqual(["switch", "sell"], actions)
        self.assertFalse(trader._buy_completed_in_current_shop)

    def test_run_sell_only_enters_default_buy_shop_then_switches_to_sell(self):
        actions = []
        trader = object.__new__(Trader)
        trader.owned_items_at_max_rate = lambda: None
        trader.task = SimpleNamespace(
            log_warning=lambda *_args: self.fail("成功入店时不应记录警告"),
        )
        trader._resolve_sale_entries = lambda: [
            CalendarEntry("水果罐头", "S2:苍蓝魔女")
        ]
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_kw: (
                actions.append("enter") or NavigationResult(True, ScreenState.SHOP)
            ),
        )
        trader._ensure_sell_page = lambda: actions.append("sell-page") or True
        trader.sell_max_price_items = lambda: actions.append("sell") or True

        self.assertTrue(trader.run_sell())
        self.assertEqual(["enter", "sell-page", "sell"], actions)

    def test_run_sell_only_stops_and_logs_when_shop_entry_fails(self):
        warnings = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(log_warning=warnings.append)
        trader._resolve_sale_entries = lambda: [
            CalendarEntry("水果罐头", "S2:苍蓝魔女")
        ]
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_kw: NavigationResult(
                False,
                ScreenState.UNKNOWN,
                "未进入默认购买页",
            ),
        )
        trader._ensure_sell_page = lambda: self.fail("入店失败后不得切出售页")
        trader.sell_max_price_items = lambda: self.fail("入店失败后不得出售")

        self.assertFalse(trader.run_sell())
        self.assertEqual(["卖：未进入默认购买页"], warnings)

    def test_run_sell_only_stops_before_sell_page_when_entry_is_not_shop(self):
        warnings = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(log_warning=warnings.append)
        trader._resolve_sale_entries = lambda: [
            CalendarEntry("水果罐头", "S2:苍蓝魔女")
        ]
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_kw: NavigationResult(
                True,
                ScreenState.MERCHANT_DIALOG,
                "仍在商人对话",
            ),
        )
        trader._ensure_sell_page = lambda: self.fail("非商店状态不得切出售页")
        trader.sell_max_price_items = lambda: self.fail("非商店状态不得出售")

        self.assertFalse(trader.run_sell())
        self.assertEqual(
            ["卖：进入商店后状态为merchant_dialog，未确认商店页，停止出售。"],
            warnings,
        )

    def test_run_sell_skips_navigation_when_sale_plan_is_empty(self):
        actions = []
        statuses = []
        trader = object.__new__(Trader)
        trader._buy_completed_in_current_shop = True
        trader._resolve_sale_entries = lambda: []
        trader.task = SimpleNamespace(
            log_info=actions.append,
            log_warning=lambda message: self.fail(message),
            info_set=lambda key, value: statuses.append((key, value)),
        )
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_kw: self.fail("空价表不得重新进入商店"),
        )
        trader._switch_from_completed_buy_to_sell = lambda: self.fail(
            "空价表不得切换到出售页"
        )
        trader.sell_max_price_items = lambda: self.fail("空价表不得执行出售")

        self.assertTrue(trader.run_sell())
        self.assertFalse(trader._buy_completed_in_current_shop)
        self.assertEqual(
            [("未出售商品", "无（当前价表没有可出售商品）")],
            statuses,
        )
        self.assertEqual(
            ["卖：当前价表没有可出售商品，跳过进入出售页面。"],
            actions,
        )

    def test_sell_page_does_not_click_when_already_on_sell(self):
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            operate_click=lambda *_args, **_kwargs: self.fail("已经在出售页时不应再次点击"),
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda *_args, **_kwargs: "出售",
            simplify=lambda value: value,
        )

        self.assertTrue(trader._ensure_sell_page(timeout=0.0))

    def test_sell_shop_selection_scrolls_down_to_target_page_in_one_burst(self):
        confirmed = []
        scrolls = []
        selected = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader._sell_cartridge_page = None
        trader._ensure_sell_list_at_top = lambda: setattr(
            trader, "_sell_cartridge_page", 0
        ) or True
        trader._wait_for_shop_page = lambda shop_ids: confirmed.append(shop_ids) or True
        trader._scroll_shop_cartridges = lambda scroll_amount, count, interval, after_sleep: (
            scrolls.append((scroll_amount, count, interval, after_sleep))
        )
        trader._select_purchase_cartridge = lambda shop_id: selected.append(shop_id) or True

        self.assertTrue(trader.select_shop_tab("R2:火晶片"))
        # 第 1 页 → 第 3 页（R2）一口气滚 9+10=19 格，只确认目标页边界。
        self.assertEqual([("E5", "R2")], confirmed)
        self.assertEqual([(-1, 19, 0.0, 0.5)], scrolls)
        self.assertEqual(["R2"], selected)
        self.assertEqual(2, trader._sell_cartridge_page)

    def test_sell_shop_selection_continues_downward_without_reset(self):
        scrolls = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader._sell_cartridge_page = 1
        trader._wait_for_shop_page = lambda _shop_ids: True
        trader._scroll_shop_cartridges = lambda scroll_amount, count, interval, after_sleep: (
            scrolls.append((scroll_amount, count, interval, after_sleep))
        )
        trader._select_purchase_cartridge = lambda _shop_id: True
        trader._ensure_sell_list_at_top = lambda: False

        # 已停在第 2 页（S19），下一张选第 4 页 E7：只补滚 10+1=11 格，不向上复位。
        self.assertTrue(trader.select_shop_tab("E7:戏水女王"))
        self.assertEqual([(-1, 11, 0.0, 0.5)], scrolls)
        self.assertEqual(3, trader._sell_cartridge_page)

    def test_sell_list_at_top_scrolls_up_by_ocr_estimate(self):
        scrolls = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        visible = iter((False, True))
        trader._cartridge_visible = lambda _shop_id, _frame: next(visible)
        trader._shop_cartridge_ocr_rows = lambda _frame: (
            SimpleNamespace(shop_id="S8"),
        )
        trader._scroll_shop_cartridges = lambda scroll_amount, count, interval, after_sleep: (
            scrolls.append((scroll_amount, count, interval, after_sleep))
        )
        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        )

        # 顶部 OCR 到 S8（行号 7）：向上快滚 7+3=10 格后认到 S1。
        self.assertTrue(trader._ensure_sell_list_at_top())
        self.assertEqual([(1, 10, 0.0, 0.5)], scrolls)
        self.assertEqual(0, trader._sell_cartridge_page)

    def test_sell_shop_selection_resets_page_when_landing_never_confirmed(self):
        scrolls = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader._sell_cartridge_page = 0
        trader._wait_for_shop_page = lambda _shop_ids: False
        trader._scroll_shop_cartridges = lambda scroll_amount, count, interval, after_sleep: (
            scrolls.append((scroll_amount, count, interval, after_sleep))
        )
        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        )
        trader._shop_list_top_row_index = lambda _frame: 5

        # 两次落点确认都失败：会话页号必须作废，否则后续条目从失真基准少滚。
        self.assertFalse(trader.select_shop_tab("E7:戏水女王"))
        self.assertEqual(
            [(-1, 20, 0.0, 0.5), (-1, 25, 0.0, 0.5)],
            scrolls,
        )
        self.assertIsNone(trader._sell_cartridge_page)

    def test_sell_shop_selection_resets_page_when_landing_ocr_is_unreadable(self):
        scrolls = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader._sell_cartridge_page = 1
        trader._wait_for_shop_page = lambda _shop_ids: False
        trader._scroll_shop_cartridges = lambda scroll_amount, count, interval, after_sleep: (
            scrolls.append((scroll_amount, count, interval, after_sleep))
        )
        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        )
        trader._shop_list_top_row_index = lambda _frame: None

        self.assertFalse(trader.select_shop_tab("E7:戏水女王"))
        self.assertEqual([(-1, 11, 0.0, 0.5)], scrolls)
        self.assertIsNone(trader._sell_cartridge_page)

    def test_sell_shop_selection_resets_page_when_reanchor_fails(self):
        scrolls = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader._sell_cartridge_page = 2
        trader._ensure_sell_list_at_top = lambda: False
        trader._scroll_shop_cartridges = lambda scroll_amount, count, interval, after_sleep: (
            scrolls.append((scroll_amount, count, interval, after_sleep))
        )

        # 目标在当前位置上方且重新定位失败：作废页号，不滚动。
        self.assertFalse(trader.select_shop_tab("S3:迷雾神射手"))
        self.assertEqual([], scrolls)
        self.assertIsNone(trader._sell_cartridge_page)

    def test_sell_resolved_entries_follow_cartridge_order(self):
        sold = []
        selected = []
        entries = [
            CalendarEntry("b_item", "E7:戏水女王"),
            CalendarEntry("a_item", "S3:迷雾神射手"),
            CalendarEntry("c_item", "R2:火晶片"),
        ]
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader.select_shop_tab = lambda shop: selected.append(shop) or True
        trader._sell_selected_entry = lambda entry: sold.append(entry.item) or True

        self.assertTrue(trader._sell_resolved_entries(entries))
        self.assertEqual(
            ["S3:迷雾神射手", "R2:火晶片", "E7:戏水女王"],
            selected,
        )
        self.assertEqual(["a_item", "c_item", "b_item"], sold)

    def test_run_sell_stops_before_calendar_when_sell_page_is_not_confirmed(self):
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(log_warning=lambda *_args: None)
        trader._resolve_sale_entries = lambda: [
            CalendarEntry("水果罐头", "S2:苍蓝魔女")
        ]
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_kw: NavigationResult(True, ScreenState.SHOP)
        )
        trader._ensure_sell_page = lambda: False
        trader.sell_max_price_items = lambda: self.fail("未确认出售页面时不得加载价表或开始出售")

        self.assertFalse(trader.run_sell())

    def test_locate_sale_items_matches_120_percent_only_in_each_name_left_roi(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        boxes = [
            self._text_box("4120%", 492, 451, 56, 13),
            self._text_box("水果罐头", 613, 560, 42, 23),
            self._text_box("4129", 824, 560, 56, 13),
            self._text_box("水果罐头", 945, 560, 42, 23),
            self._text_box("120", 1156, 560, 52, 14),
            self._text_box("水果罐头", 1277, 560, 42, 23),
        ]
        markers = (
            self._marker_result(493, 563),
            self._marker_result(825, 563),
            self._marker_result(1157, 563),
        )
        trader, match_calls = self._make_sale_template_trader(
            lambda _frame, _name, target_height=900: boxes,
            markers,
        )

        candidates = trader._locate_sale_items(
            CalendarEntry("水果罐头", "S2:苍蓝魔女"),
            frame,
        )
        self.assertEqual(
            [(634, 572), (966, 572), (1298, 572)],
            [candidate.center for candidate in candidates],
        )
        self.assertEqual((493, 563), (candidates[0].percent_box.x, candidates[0].percent_box.y))
        self.assertEqual(3, len(match_calls))
        self.assertTrue(all(call[0] is frame for call in match_calls))
        self.assertTrue(
            all(call[1] is SALE_120_PERCENT_MARKER_TEMPLATE for call in match_calls)
        )
        self.assertEqual(
            [(463, 548, 150, 47), (795, 548, 150, 47), (1127, 548, 150, 47)],
            [call[2]["search_roi"] for call in match_calls],
        )
        for _frame, _spec, kwargs in match_calls:
            self.assertEqual(SALE_120_PERCENT_MARKER_TEMPLATE.threshold, kwargs["minimum_score"])
            self.assertEqual(SALE_120_PERCENT_MARKER_PEAK_RADIUS, kwargs["peak_radius"])
            self.assertEqual(SALE_120_PERCENT_MARKER_MAX_RESULTS, kwargs["max_results"])

    def test_locate_sale_items_rejects_marker_outside_name_left_roi(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        boxes = [
            self._text_box("水果罐头", 613, 560, 42, 23),
        ]
        trader, _match_calls = self._make_sale_template_trader(
            lambda *_args, **_kwargs: boxes,
            (self._marker_result(300, 563),),
        )

        self.assertEqual(
            [],
            trader._locate_sale_items(
                CalendarEntry("水果罐头", "S2:苍蓝魔女"),
                frame,
            ),
        )
        self.assertFalse(trader._last_sale_unavailable)
        self.assertEqual(
            "商品名左侧局部ROI未命中↑120%模板",
            trader._last_sale_reason,
        )

    def test_locate_sale_items_pairs_real_markers_with_name_ocr(self):
        fixture_path = (
            ROOT / "tests" / "fixtures" / "map_trade" / "trade_shop" / "sale_120_markers_fhd.png"
        )
        fixture = cv2.imread(str(fixture_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(fixture)
        boxes = [
            self._text_box("4120%", 493, 563, 52, 14),
            self._text_box("水果罐头", 613, 560, 42, 23),
            self._text_box("4129", 825, 563, 52, 14),
            self._text_box("水果罐头", 945, 560, 42, 23),
            self._text_box("120", 1157, 563, 52, 14),
            self._text_box("水果罐头", 1277, 560, 42, 23),
        ]
        trader = object.__new__(Trader)
        trader.vision = Vision(
            SimpleNamespace(config={}, vision_threshold_key="跑图跑商识图阈值")
        )
        trader.vision.ocr_boxes = lambda *_args, **_kwargs: boxes
        trader.task = SimpleNamespace(info_set=lambda *_args: None)

        candidates = trader._locate_sale_items(
            CalendarEntry("水果罐头", "S2:苍蓝魔女"),
            fixture,
        )

        self.assertEqual(
            [(634, 572), (966, 572), (1298, 572)],
            [candidate.center for candidate in candidates],
        )
        self.assertEqual(
            [(493, 563), (825, 563), (1157, 563)],
            [
                (candidate.percent_box.x, candidate.percent_box.y)
                for candidate in candidates
            ],
        )

    def test_locate_sale_items_retries_adjacent_ocr_height_for_item_name(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        target_heights = []
        markers = (self._marker_result(493, 563),)

        def ocr_boxes(_frame, _name, target_height=900):
            target_heights.append(target_height)
            item_name = "胡萝卜" if target_height == 900 else "水果罐头"
            return [
                self._text_box("4120%", 492, 451, 56, 13),
                self._text_box("4129", 824, 451, 56, 13),
                self._text_box("120", 1156, 451, 52, 14),
                self._text_box(item_name, 613, 560, 42, 23),
            ]

        trader, _match_calls = self._make_sale_template_trader(ocr_boxes, markers)

        candidates = trader._locate_sale_items(
            CalendarEntry("水果罐头", "S2:苍蓝魔女"),
            frame,
        )

        self.assertEqual([(634, 572)], [candidate.center for candidate in candidates])
        self.assertEqual((900, 840, 960), SALE_FULL_PAGE_OCR_TARGET_HEIGHTS)
        self.assertEqual([900, 840], target_heights)
        self.assertFalse(trader._last_sale_unavailable)

    def test_locate_sale_items_ignores_bad_percent_ocr_when_local_template_misses(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        target_heights = []
        boxes = [
            self._text_box("4120%", 492, 451, 56, 13),
            self._text_box("4129", 824, 451, 56, 13),
            self._text_box("120", 1156, 451, 52, 14),
            self._text_box("水果罐头", 945, 560, 42, 23),
        ]

        def ocr_boxes(_frame, _name, target_height=900):
            target_heights.append(target_height)
            return boxes

        trader, match_calls = self._make_sale_template_trader(ocr_boxes, ())

        self.assertEqual(
            [],
            trader._locate_sale_items(
                CalendarEntry("水果罐头", "S2:苍蓝魔女"),
                frame,
            ),
        )
        self.assertEqual([900, 840, 960], target_heights)
        # The strict pass misses, then the relaxed pass (which still needs a
        # template hit, OCR alone never makes a marker) finds nothing either.
        self.assertEqual(2, len(match_calls))
        self.assertEqual(
            SALE_MARKER_RELAXED_PIXEL_SCORE, match_calls[1][1].min_pixel_score
        )
        self.assertFalse(trader._last_sale_unavailable)
        self.assertEqual(
            "商品名左侧局部ROI未命中↑120%模板",
            trader._last_sale_reason,
        )

    def _relaxed_only_trader(self, badge_text):
        frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
        boxes = [
            self._text_box(badge_text, 1000, 1135, 110, 26),
            self._text_box("黄金罗勒", 1203, 1133, 160, 40),
        ]
        marker = MatchResult(0.98, (996, 1130), (104, 28), pixel_score=0.928)
        trader, match_calls = self._make_sale_template_trader(
            lambda *_args, **_kwargs: boxes, ()
        )

        def match_all(frame, spec, **kwargs):
            match_calls.append((frame, spec, kwargs))
            # Live 4K: pixel 0.928, below the strict 0.93 floor.
            return (marker,) if spec.min_pixel_score == SALE_MARKER_RELAXED_PIXEL_SCORE else ()

        trader.vision.match_all = match_all
        return trader, frame

    def test_4k_marker_below_strict_floor_counts_when_ocr_reads_120(self):
        trader, frame = self._relaxed_only_trader("1.20%")
        found = trader._locate_sale_items(CalendarEntry("黄金罗勒", "S6:异教塔"), frame)
        self.assertEqual(1, len(found))

    def test_4k_relaxed_marker_is_refused_when_ocr_reads_another_rate(self):
        trader, frame = self._relaxed_only_trader("4117%")
        self.assertEqual(
            [], trader._locate_sale_items(CalendarEntry("黄金罗勒", "S6:异教塔"), frame)
        )

    def test_locate_sale_items_with_no_ocr_output_is_not_marked_sold_out(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        target_heights = []
        trader, _match_calls = self._make_sale_template_trader(
            lambda _frame, _name, target_height=900: (
                target_heights.append(target_height) or []
            ),
            (self._marker_result(493, 563),),
        )

        self.assertEqual(
            [],
            trader._locate_sale_items(
                CalendarEntry("白糖", "S2:苍蓝魔女"),
                frame,
            ),
        )
        self.assertEqual([900, 840, 960], target_heights)
        self.assertFalse(trader._last_sale_unavailable)
        self.assertEqual("全画面OCR未返回任何文本", trader._last_sale_reason)

    def test_name_missed_with_other_page_text_is_marked_unavailable(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        target_heights = []
        other_item = self._text_box("胡萝卜", 613, 560, 42, 23)
        trader, match_calls = self._make_sale_template_trader(
            lambda _frame, _name, target_height=900: (
                target_heights.append(target_height) or [other_item]
            ),
            (self._marker_result(493, 563),),
        )

        self.assertEqual(
            [],
            trader._locate_sale_items(
                CalendarEntry("白糖", "S2:苍蓝魔女"),
                frame,
            ),
        )
        self.assertEqual([900, 840, 960], target_heights)
        self.assertEqual([], match_calls)
        self.assertTrue(trader._last_sale_unavailable)
        self.assertEqual("全画面OCR未识别到商品名", trader._last_sale_reason)

    def test_locate_sale_items_scales_left_roi_at_720p(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        boxes = [
            self._text_box("4120%", 328, 375, 35, 9),
            # 720p 下 150px 参考搜索宽度缩放为 100px，仍覆盖名称左侧标志。
            self._text_box("水果罐头", 409, 372, 42, 15),
        ]
        trader, _match_calls = self._make_sale_template_trader(
            lambda *_args, **_kwargs: boxes,
            (self._marker_result(328, 375, 35, 9),),
        )

        candidates = trader._locate_sale_items(
            CalendarEntry("水果罐头", "S2:苍蓝魔女"),
            frame,
        )
        self.assertEqual([(430, 380)], [candidate.center for candidate in candidates])

    def test_locate_sale_items_returns_all_same_item_in_reading_order(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        boxes = [
            self._text_box("兽肉", 1262, 560, 43, 23),
            self._text_box("兽肉", 598, 560, 44, 23),
            self._text_box("兽肉", 1594, 560, 42, 23),
            self._text_box("兽肉", 928, 560, 44, 23),
        ]
        markers = (
            self._marker_result(492, 562),
            self._marker_result(820, 562),
            self._marker_result(1154, 562),
            self._marker_result(1485, 562),
        )
        trader, _match_calls = self._make_sale_template_trader(
            lambda *_args, **_kwargs: boxes,
            markers,
        )

        candidates = trader._locate_sale_items(CalendarEntry("兽肉", "S3:迷雾神射手"), frame)

        self.assertEqual(
            [(620, 572), (950, 572), (1284, 572), (1615, 572)],
            [candidate.center for candidate in candidates],
        )

    def test_locate_sale_items_rejects_ambiguous_local_template_candidates(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        boxes = [
            self._text_box("兽肉", 598, 560, 44, 23),
            self._text_box("兽肉", 650, 560, 44, 23),
        ]
        trader, _match_calls = self._make_sale_template_trader(
            lambda *_args, **_kwargs: boxes,
            (
                self._marker_result(480, 562),
                self._marker_result(490, 562),
            ),
        )

        self.assertEqual([], trader._locate_sale_items(CalendarEntry("兽肉", "S3"), frame))
        self.assertFalse(trader._last_sale_unavailable)
        self.assertEqual(
            "商品名左侧局部ROI模板候选不唯一",
            trader._last_sale_reason,
        )

    def test_locate_sale_items_keeps_valid_pair_when_another_name_has_no_pair(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        boxes = [
            self._text_box("兽肉", 598, 560, 44, 23),
            self._text_box("兽肉", 928, 560, 44, 23),
        ]
        trader, _match_calls = self._make_sale_template_trader(
            lambda *_args, **_kwargs: boxes,
            (self._marker_result(492, 562),),
        )

        candidates = trader._locate_sale_items(CalendarEntry("兽肉", "S3"), frame)

        self.assertEqual([(620, 572)], [candidate.center for candidate in candidates])

    def test_sale_name_match_rejects_single_char_fragment_against_alias(self):
        # 回归 BUG-20260913-06：卖出后页面上的杂散单字母框"C"曾反向命中
        # 英文别名 Chocolat Cocktail，令已售完页面被误判为商品仍在售。
        normalized_names = ("巧克力鸡尾酒", "chocolatcocktail")
        self.assertFalse(Trader._sale_name_matches("c", normalized_names))
        self.assertTrue(Trader._sale_name_matches("cocktail", normalized_names))
        self.assertTrue(Trader._sale_name_matches("巧克力鸡尾酒", normalized_names))
        self.assertTrue(Trader._sale_name_matches("鸡尾酒", normalized_names))

    def test_sale_name_match_fragment_min_chars_boundary(self):
        self.assertEqual(2, SALE_NAME_FRAGMENT_MIN_CHARS)
        self.assertFalse(Trader._sale_name_matches("克", ("巧克力鸡尾酒",)))
        self.assertTrue(Trader._sale_name_matches("克力", ("巧克力鸡尾酒",)))

    def test_sale_name_match_single_char_item_keeps_forward_match(self):
        self.assertTrue(Trader._sale_name_matches("虾", ("虾",)))
        self.assertFalse(Trader._sale_name_matches("虫", ("虾",)))

    def test_missing_120_percent_before_any_sale_skips_the_item(self):
        trader = object.__new__(Trader)
        trader._move_sale_list = lambda _direction: True
        trader._scroll_sale_list_to_top = lambda: None
        trader.task = SimpleNamespace(
            operate_click=lambda *_args, **_kwargs: None,
            sleep=lambda *_args: None,
            log_info=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )

        def fail_wait(_entry):
            trader._last_sale_unavailable = False
            trader._last_sale_reason = "↑120%模板未命中"
            return None

        trader._wait_sale_item_candidates = fail_wait

        # Nothing was clicked: the item is skipped (unavailable) so later
        # items are still sold, instead of stopping the day.
        self.assertFalse(trader._sell_selected_entry(CalendarEntry("豆子", "S12:海边天使")))
        self.assertTrue(trader._last_sale_unavailable)
        self.assertEqual(
            "未确认↑120%标志：↑120%模板未命中",
            trader._last_sale_reason,
        )

    def test_marker_failure_after_sale_with_name_still_visible_finishes_the_item(self):
        warnings = []
        clicked = []
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        candidate = SimpleNamespace(center=(620, 572))
        scans = [([candidate], frame), None]
        trader = object.__new__(Trader)
        trader._move_sale_list = lambda _direction: True
        trader._scroll_sale_list_to_top = lambda: None
        trader.task = SimpleNamespace(
            config={},
            log_info=lambda *_args: None,
            log_warning=warnings.append,
            info_set=lambda *_args: None,
        )

        def wait_scan(_entry):
            located = scans.pop(0)
            if located is None:
                trader._last_sale_unavailable = False
                trader._last_sale_reason = "↑120%模板未命中"
                trader._last_sale_page_empty = False
            return located

        trader._wait_sale_item_candidates = wait_scan

        def sell_one(_entry, candidate, frame, **_kwargs):
            clicked.append((candidate.center, frame.shape))
            return 352_927, True

        trader._sell_one_candidate = sell_one

        # Already sold at ↑120%; a leftover name without the marker is never
        # sold at a worse rate, so the item counts as done.
        self.assertTrue(
            trader._sell_selected_entry(
                CalendarEntry("白糖", "S2:苍蓝魔女"),
            )
        )
        self.assertEqual(1, len(clicked))
        self.assertIn("已出售1组，继续下一项", warnings[0])

    def test_sale_after_successful_sale_finishes_without_warning_when_name_disappears(self):
        warnings = []
        logs = []
        statuses = []
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        candidate = SimpleNamespace(center=(620, 572))
        scans = [([candidate], frame), None]
        trader = object.__new__(Trader)
        trader._move_sale_list = lambda _direction: True
        trader._scroll_sale_list_to_top = lambda: None
        trader.task = SimpleNamespace(
            config={},
            log_info=logs.append,
            log_warning=warnings.append,
            info_set=lambda key, value: statuses.append((key, value)),
        )

        def wait_scan(_entry):
            located = scans.pop(0)
            if located is None:
                trader._last_sale_unavailable = True
                trader._last_sale_reason = "全画面OCR未识别到商品名"
                trader._last_sale_page_empty = True
            return located

        trader._wait_sale_item_candidates = wait_scan
        trader._sell_one_candidate = lambda *_args, **_kwargs: (352_927, True)

        self.assertTrue(
            trader._sell_selected_entry(CalendarEntry("白糖", "S2:苍蓝魔女"))
        )
        self.assertEqual([], warnings)
        self.assertFalse(trader._last_sale_unavailable)
        self.assertEqual("", trader._last_sale_reason)
        self.assertTrue(
            any("商品名连续消失" in value for key, value in statuses if key == "出售完成确认")
        )
        self.assertTrue(any("当前商店页已无剩余可出售组" in message for message in logs))

    def test_sale_after_successful_sale_requires_two_name_absence_scans(self):
        warnings = []
        logs = []
        statuses = []
        sleeps = []
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        candidate = SimpleNamespace(center=(620, 572))
        locate_calls = []
        trader = object.__new__(Trader)
        trader._move_sale_list = lambda _direction: True
        trader._scroll_sale_list_to_top = lambda: None
        trader.task = SimpleNamespace(
            config={},
            sleep=sleeps.append,
            log_info=logs.append,
            log_warning=warnings.append,
            info_set=lambda key, value: statuses.append((key, value)),
        )
        trader.vision = SimpleNamespace(capture=lambda: frame)

        def locate(_entry, _frame):
            locate_calls.append(True)
            if len(locate_calls) == 1:
                trader._last_sale_name_seen = True
                trader._last_sale_ocr_output = True
                return [candidate]
            trader._last_sale_name_seen = False
            trader._last_sale_ocr_output = True
            trader._last_sale_reason = "全画面OCR未识别到商品名"
            return []

        trader._locate_sale_items = locate
        trader._sell_one_candidate = lambda *_args, **_kwargs: (352_927, True)

        with patch(
            "src.tasks.map_trade.trader_sell.monotonic",
            side_effect=(0.0, 0.0, 0.0),
        ):
            self.assertTrue(
                trader._sell_selected_entry(
                    CalendarEntry("白糖", "S2:苍蓝魔女"),
                )
            )

        self.assertEqual(1 + SALE_EMPTY_NAME_STABLE_HITS, len(locate_calls))
        self.assertEqual(SALE_EMPTY_NAME_STABLE_HITS - 1, len(sleeps))
        self.assertEqual([], warnings)
        self.assertFalse(trader._last_sale_unavailable)
        self.assertEqual("", trader._last_sale_reason)
        self.assertTrue(any("商品名连续消失" in value for key, value in statuses))
        self.assertTrue(any("当前商店页已无剩余可出售组" in message for message in logs))

    def test_sale_candidate_wait_timeout_does_not_emit_warning_by_itself(self):
        warnings = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            log_warning=warnings.append,
            sleep=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(capture=lambda: np.zeros((720, 1280, 3), dtype=np.uint8))
        trader._locate_sale_items = lambda *_args: (
            setattr(trader, "_last_sale_name_seen", False)
            or setattr(trader, "_last_sale_ocr_output", False)
            or []
        )

        self.assertIsNone(
            trader._wait_sale_item_candidates(
                CalendarEntry("白糖", "S2:苍蓝魔女"),
                timeout=0.0,
            )
        )
        self.assertEqual([], warnings)

    def test_normal_sale_clicks_located_item_name_then_uses_max_and_sell(self):
        clicks = []
        client_clicks = []
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        trader = object.__new__(Trader)
        trader._move_sale_list = lambda _direction: True
        trader._scroll_sale_list_to_top = lambda: None
        trader.task = SimpleNamespace(
            config={"出售保险": False},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            log_info=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(
            click_client=lambda point, shape, after_sleep=0: client_clicks.append(
                (point, shape, after_sleep)
            )
        )
        candidates = [SimpleNamespace(center=(640, 462))]
        scans = [([candidates[0]], frame), None]
        def pop_scan(_entry):
            located = scans.pop(0)
            if located is None:
                trader._last_sale_unavailable = True
                trader._last_sale_reason = "全画面OCR未识别到商品名"
                trader._last_sale_page_empty = True
            return located

        trader._wait_sale_item_candidates = pop_scan
        trader._sale_name_signature = lambda _entry, _frame: ()
        trader._wait_sale_dialog_item = lambda _entry: True
        trader._wait_owned_quantity = lambda: 400
        trader._wait_available_quantity = lambda: 400
        trader._wait_selected_sale_quantity = lambda _expected: True
        trader._wait_sale_completion = lambda *_args, **_kwargs: True

        self.assertTrue(trader._sell_selected_entry(CalendarEntry("甜辣酱", "S10:霍尔蒙克斯")))
        self.assertEqual([((640, 462), frame.shape, 0.5)], client_clicks)
        self.assertEqual(
            [
                (*SALE_MAX_POINT, 0.5),
                (*SALE_CONFIRM_POINT, 0.5),
            ],
            clicks,
        )

    def _reserve_trader(self, owned_counts):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        trader = object.__new__(Trader)
        trader._move_sale_list = lambda _direction: True
        trader._scroll_sale_list_to_top = lambda: None
        messages = []
        trader.task = SimpleNamespace(
            config={"出售保险": False},
            operate_click=lambda *_args, **_kwargs: None,
            log_info=messages.append,
            log_warning=messages.append,
            info_set=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(click_client=lambda *_args, **_kwargs: None)
        # The item stays on the page: only the dialog's count tells when to stop.
        trader._wait_sale_item_candidates = lambda _entry: (
            [SimpleNamespace(center=(640, 462))],
            frame,
        )
        trader._candidate_unmoved = lambda *_args: True
        trader._sale_name_signature = lambda _entry, _frame: ()
        trader._sale_toast_id = lambda _frame: None
        trader._wait_sale_dialog_item = lambda _entry: True
        owned = iter(owned_counts)
        trader._wait_owned_quantity = lambda: next(owned)
        trader._wait_available_quantity = lambda: 99999
        trader._wait_selected_sale_quantity = lambda _expected: True
        trader._wait_sale_completion = lambda *_args, **_kwargs: True
        trader._close_sale_dialog = lambda: True
        sales = []

        def choose(entry, owned_now, available):
            sales.append(owned_now)
            # Like the slider: it sold down to about the reserve.
            trader._reserve_reached = owned_now - available < entry.reserve
            return True

        trader._choose_sale_quantity = choose
        return trader, sales, messages

    def test_selling_ends_once_the_slider_reached_the_reserve(self):
        # Live 2026-10-07: 兽肉 kept 10137, then sold one at a time
        # (10136, 10135, ...) because the item stayed on the page.
        trader, sales, _messages = self._reserve_trader([284775, 184776, 84777, 10500])
        self.assertTrue(trader._sell_selected_entry(CalendarEntry("兽肉", "S3", reserve=10000)))
        self.assertEqual([284775, 184776, 84777], sales)

    def test_an_item_already_near_its_reserve_is_skipped(self):
        # Leo 2026-10-07: keeping up to +20% over the reserve is fine.
        for owned in (10137, 12000):
            trader, sales, messages = self._reserve_trader([owned])
            self.assertTrue(
                trader._sell_selected_entry(CalendarEntry("兽肉", "S3", reserve=10000))
            )
            self.assertEqual([], sales)
            self.assertTrue(any("保留量10000附近" in message for message in messages))

    def test_more_than_twenty_percent_over_the_reserve_is_sold(self):
        trader, sales, _messages = self._reserve_trader([12001])
        self.assertTrue(trader._sell_selected_entry(CalendarEntry("兽肉", "S3", reserve=10000)))
        self.assertEqual([12001], sales)

    def test_the_slider_accepts_anything_up_to_twenty_percent_over(self):
        owned = 99999
        left, _top, right, _bottom = SALE_SLIDER_REGION
        trader, state, clicks, warnings = self._slider_trader(owned, shift=0.0)

        def click(x, y, after_sleep=0):
            clicks.append(x)
            if (x, y) == SALE_MAX_POINT:
                state["selected"] = owned
                return
            # The slider lands 900 short of where it was aimed (11000 kept):
            # 11900 is still fine, no second click.
            ratio = max(0.0, min(1.0, (x - left) / (right - left)))
            state["selected"] = round(1 + (owned - 1) * ratio) - 900

        trader.task.operate_click = click
        self.assertTrue(
            trader._choose_sale_quantity(CalendarEntry("兽肉", "S3", reserve=10000), owned, 99999)
        )
        # MAX checks the owned count, then one slider click.
        self.assertEqual(SALE_MAX_POINT[0], clicks[0])
        self.assertEqual(2, len(clicks))
        self.assertTrue(10000 <= owned - state["selected"] <= 12000)
        self.assertEqual([], warnings)

    def test_sale_dialog_open_retries_until_third_click(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        client_clicks = []
        messages = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            config={"出售保险": False},
            operate_click=lambda *_args, **_kwargs: None,
            log_info=messages.append,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(
            click_client=lambda point, shape, after_sleep=0: client_clicks.append(
                (point, shape, after_sleep)
            )
        )
        dialog_checks = iter((False, False, True))
        trader._sale_dialog_shown = lambda _frame=None: False
        trader._sale_name_signature = lambda _entry, _frame: ()
        trader._sale_toast_id = lambda _frame: None
        trader._wait_sale_dialog_item = lambda _entry: next(dialog_checks)
        trader._wait_owned_quantity = lambda: 400
        trader._wait_available_quantity = lambda: 400
        trader._choose_sale_quantity = lambda *_args: True
        trader._wait_selected_sale_quantity = lambda _expected: True
        trader._wait_sale_completion = lambda *_args, **_kwargs: True

        result = trader._sell_one_candidate(
            CalendarEntry("item", "S3"),
            SimpleNamespace(center=(951, 682)),
            frame,
            previous_owned=None,
        )

        self.assertEqual((400, True), result)
        self.assertEqual(SALE_DIALOG_OPEN_MAX_CLICKS, len(client_clicks))
        self.assertEqual(2, len([message for message in messages if "补点重试" in message]))

    def test_sale_dialog_open_stops_after_click_limit(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        client_clicks = []
        warnings = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            log_info=lambda *_args: None,
            log_warning=warnings.append,
        )
        trader.vision = SimpleNamespace(
            click_client=lambda point, shape, after_sleep=0: client_clicks.append(
                (point, shape, after_sleep)
            )
        )
        trader._sale_dialog_shown = lambda _frame=None: False
        trader._sale_name_signature = lambda _entry, _frame: ()
        trader._sale_toast_id = lambda _frame: None
        trader._wait_sale_dialog_item = lambda _entry: False

        result = trader._sell_one_candidate(
            CalendarEntry("item", "S3"),
            SimpleNamespace(center=(951, 682)),
            frame,
            previous_owned=None,
        )

        self.assertIsNone(result)
        self.assertEqual(SALE_DIALOG_OPEN_MAX_CLICKS, len(client_clicks))
        self.assertEqual(1, len(warnings))

    def test_sale_dialog_wrong_item_stops_without_reclick_or_quantity_change(self):
        trader, _ocr_calls, _warnings, clock = self._title_trader([("豆子", "豆子", "豆子")])
        clicks = []
        trader.vision.click_client = lambda *args, **kwargs: clicks.append(args)
        trader._sale_name_signature = lambda *_args: ()
        trader._sale_toast_id = lambda *_args: None
        trader._wait_owned_quantity = lambda: self.fail("错误商品不得进入数量设置")
        with patch("src.tasks.map_trade.trader_sell.monotonic", lambda: clock[0]):
            result = trader._sell_one_candidate(
                CalendarEntry("姜黄", "S12"), SimpleNamespace(center=(620, 579)),
                np.zeros((1080, 1920, 3), dtype=np.uint8), previous_owned=None,
            )
        self.assertIsNone(result)
        self.assertEqual(1, len(clicks))

    def test_sell_selected_entry_rescans_after_each_completed_sale(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        first = SimpleNamespace(center=(620, 572))
        second = SimpleNamespace(center=(620, 572))
        scans = [([first], frame), ([second], frame), None]
        clicked = []
        trader = object.__new__(Trader)
        trader._move_sale_list = lambda _direction: True
        trader._scroll_sale_list_to_top = lambda: None
        trader.task = SimpleNamespace(
            config={},log_info=lambda *_args: None)
        def pop_scan(_entry):
            located = scans.pop(0)
            if located is None:
                trader._last_sale_unavailable = True
                trader._last_sale_reason = "全画面OCR未识别到商品名"
                trader._last_sale_page_empty = True
            return located

        trader._wait_sale_item_candidates = pop_scan

        def sell_one(_entry, candidate, _frame, **_kwargs):
            clicked.append(candidate.center)
            return 240524 - len(clicked), True

        trader._sell_one_candidate = sell_one

        self.assertTrue(trader._sell_selected_entry(CalendarEntry("兽肉", "S3")))
        self.assertEqual([(620, 572), (620, 572)], clicked)
        self.assertEqual([], scans)

    def test_wait_sale_item_candidates_retries_until_located(self):
        sleeps = []
        warnings = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            sleep=sleeps.append,
            log_warning=warnings.append,
        )
        frames = [np.zeros((1080, 1920, 3), dtype=np.uint8) for _ in range(2)]
        calls = []
        trader.vision = SimpleNamespace(capture=lambda: frames[min(len(calls), 1)])
        trader._locate_sale_items = lambda _entry, _frame: (
            calls.append(_frame) or ([] if len(calls) < 2 else [SimpleNamespace(center=(640, 462))])
        )

        located = trader._wait_sale_item_candidates(
            CalendarEntry("水果罐头", "S2:苍蓝魔女"),
            timeout=5.0,
            interval=0.1,
        )
        self.assertEqual([(640, 462)], [candidate.center for candidate in located[0]])
        self.assertIs(frames[1], located[1])
        self.assertEqual(1, len(sleeps))
        self.assertEqual([], warnings)

    def _slider_trader(self, owned, shift, available=None):
        """A dialog whose slider sells more than its position says (shift).

        ``owned`` is the real stock; MAX and the slider reach at most
        min(owned, available).
        """
        left, _top, right, _bottom = SALE_SLIDER_REGION
        state = {"selected": None}
        clicks = []
        warnings = []
        most = min(owned, available) if available else owned

        def click(x, y, after_sleep=0):
            clicks.append(x)
            if (x, y) == SALE_MAX_POINT:
                state["selected"] = most
                return
            ratio = max(0.0, min(1.0, (x - left) / (right - left) + shift))
            state["selected"] = round(1 + (most - 1) * ratio)

        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            config={"出售保险": False},
            operate_click=click,
            log_info=lambda *_args: None,
            log_warning=warnings.append,
            info_set=lambda *_args: None,
            sleep=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(
            capture=lambda: None,
            ocr_text=lambda *_a, **_k: f"{state['selected']}个",
        )
        return trader, state, clicks, warnings

    def test_reserve_is_kept_even_when_the_slider_oversells(self):
        # Leo 2026-10-05: 40245 甜椒, keep 2000 -> one click sold 39879.
        owned = 40245
        trader, state, clicks, warnings = self._slider_trader(owned, shift=0.04)
        self.assertTrue(
            trader._choose_sale_quantity(CalendarEntry("甜椒", "S11", reserve=2000), owned)
        )
        kept = owned - state["selected"]
        self.assertGreaterEqual(kept, 2000)
        self.assertLessEqual(kept, 2000 * 1.2)  # up to +20% is fine (Leo 2026-10-07)
        self.assertGreater(len(clicks), 1)
        self.assertEqual([], warnings)

    def test_a_group_that_keeps_the_reserve_is_sold_with_max(self):
        # Live 2026-10-07: 兽肉 684771, keep 10000, groups of 99999.
        owned = 684771
        trader, _state, clicks, warnings = self._slider_trader(owned, shift=0.0, available=99999)
        self.assertTrue(
            trader._choose_sale_quantity(CalendarEntry("兽肉", "S1", reserve=10000), owned, 99999)
        )
        self.assertEqual([SALE_MAX_POINT[0]], clicks)
        self.assertEqual([], warnings)

    def test_a_group_reaching_into_the_reserve_uses_the_slider(self):
        owned = 105000
        trader, state, clicks, warnings = self._slider_trader(owned, shift=0.0, available=99999)
        self.assertTrue(
            trader._choose_sale_quantity(CalendarEntry("兽肉", "S1", reserve=10000), owned, 99999)
        )
        self.assertGreaterEqual(owned - state["selected"], 10000)
        # MAX only checks the owned count; the slider makes the selection.
        self.assertEqual(SALE_MAX_POINT[0], clicks[0])
        self.assertNotIn(SALE_MAX_POINT[0], clicks[1:])
        self.assertEqual([], warnings)

    def test_an_owned_count_with_an_extra_digit_sells_nothing(self):
        # Review #15: 4245 owned, read 14245 on every look, keep 2000.  The
        # slider can never select more than 4245; the old fallback sold all
        # 4245 and logged 「保留10000个」.
        trader, state, clicks, warnings = self._slider_trader(4245, shift=0.0, available=99999)
        messages = []
        trader.task.log_info = messages.append
        self.assertFalse(
            trader._choose_sale_quantity(CalendarEntry("番茄", "S1", reserve=2000), 14245, 99999)
        )
        self.assertEqual([SALE_MAX_POINT[0]], clicks)
        self.assertEqual(1, len(warnings))
        self.assertIn("可能把拥有数量认错了", warnings[0])
        self.assertFalse(any("保留" in message for message in messages))

    def test_an_owned_count_with_an_extra_digit_is_caught_when_the_group_is_the_stock(self):
        # The dialog's 可购买 is the real stock (4245): owned - group looked
        # like it kept 10000, and MAX alone would have sold everything.
        for read in (14245, 42455, 42450):
            with self.subTest(read=read):
                trader, _state, _clicks, warnings = self._slider_trader(4245, 0.0, 4245)
                self.assertFalse(
                    trader._choose_sale_quantity(
                        CalendarEntry("番茄", "S1", reserve=2000), read, 4245
                    )
                )
                self.assertEqual(1, len(warnings))

    def test_reserve_slider_that_cannot_be_corrected_sells_nothing(self):
        owned = 8400
        trader, state, clicks, warnings = self._slider_trader(owned, shift=1.0)
        self.assertFalse(
            trader._choose_sale_quantity(CalendarEntry("黄油", "S2", reserve=5500), owned)
        )
        self.assertTrue(warnings)

    def test_sale_slider_left_edge_represents_selling_one_item(self):
        left, top, _right, bottom = SALE_SLIDER_REGION

        self.assertEqual(
            (left, (top + bottom) / 2),
            Trader._sale_slider_point(owned=5501, reserve=5500),
        )
        self.assertIsNone(Trader._sale_slider_point(owned=5500, reserve=5500))

    def test_sale_dialog_title_region_is_ltrb_and_non_empty(self):
        expected = reference_rect_to_relative_roi(
            (495, 310, 300, 80),
            FHD_1080,
        )

        self.assertEqual(expected, SALE_DIALOG_TITLE_REGION)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        _left, _top, region = relative_roi_frame(frame, SALE_DIALOG_TITLE_REGION)

        self.assertEqual((80, 300), region.shape[:2])

    def _title_trader(self, readings, shape=(1080, 1920, 3)):
        calls, warnings = [], []
        clock = [0.0]
        position = [-1, 0]
        frame = np.full(shape, (20, 70, 150), dtype=np.uint8)

        def capture():
            position[0] += 1
            position[1] = 0
            return frame.copy()

        def ocr_boxes(target, name, **kwargs):
            frame_readings = readings[min(position[0], len(readings) - 1)]
            text = frame_readings[position[1]]
            position[1] += 1
            calls.append((position[0], name, target.copy(), kwargs))
            texts = text if isinstance(text, tuple) else (text,)
            return [SimpleNamespace(name=value, confidence=0.75) for value in texts if value]

        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            info_set=lambda *_args: None,
            log_warning=warnings.append,
        )
        trader.vision = SimpleNamespace(
            capture=capture,
            ocr_boxes=ocr_boxes,
            simplify=lambda value: value,
        )
        # The quantity rows (拥有/可购买) are on screen: the dialog is open.
        trader._sale_dialog_shown = lambda _frame=None: True
        return trader, calls, warnings, clock

    def test_sale_dialog_accepts_all_turmeric_spellings_in_two_captures(self):
        for spelling in ("姜黄", "姜黃", "薑黄", "薑黃"):
            with self.subTest(spelling=spelling):
                trader, calls, warnings, clock = self._title_trader(
                    [(spelling, spelling, spelling), (spelling, spelling, spelling)]
                )
                with patch("src.tasks.map_trade.trader_sell.monotonic", lambda: clock[0]):
                    self.assertTrue(trader._wait_sale_dialog_item(CalendarEntry("姜黄", "S12")))
                self.assertEqual([0, 1], [call[0] for call in calls])
                self.assertTrue(all(call[1].endswith("/原图") for call in calls))
                self.assertEqual([], warnings)

    def test_turmeric_catalog_maps_all_simplified_and_traditional_combinations(self):
        trader = object.__new__(Trader)
        trader._sale_title_entries = ()
        trader._sale_title_catalog_cache = None
        trader.vision = SimpleNamespace(simplify=lambda value: value)
        catalog = trader._sale_title_catalog(CalendarEntry("姜黄", "S12"))
        # OCR text is folded to Simplified before the lookup, so every
        # spelling reaches the same key.
        for spelling in ("姜黄", "姜黃", "薑黄", "薑黃"):
            self.assertEqual({"姜黄"}, catalog[trader._normal(spelling)])

    def test_sale_dialog_fallback_uses_scaled_roi_and_original_pixels(self):
        for shape in ((1080, 1920, 3), (720, 1280, 3)):
            for readings, modes in (
                (("未知", "白糖"), ["原图", "灰度"]),
                (("未知", "未识别", "白糖"), ["原图", "灰度", "CLAHE"]),
            ):
                with self.subTest(shape=shape, modes=modes):
                    trader, calls, _warnings, clock = self._title_trader([readings], shape)
                    with patch("src.tasks.map_trade.trader_sell.monotonic", lambda: clock[0]):
                        self.assertTrue(trader._wait_sale_dialog_item(CalendarEntry("白糖", "S2")))
                    self.assertEqual(modes * 2, [c[1].split("/")[-1] for c in calls])
                    frame = np.full(shape, (20, 70, 150), dtype=np.uint8)
                    _, _, crop = relative_roi_frame(frame, SALE_DIALOG_TITLE_REGION)
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    expected = [crop, cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)]
                    if len(modes) == 3:
                        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
                        expected.append(cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR))
                    for call, image in zip(calls, expected * 2):
                        np.testing.assert_array_equal(image, call[2])
                        self.assertEqual({"target_height": 0}, call[3])

    def test_sale_dialog_empty_title_resets_consecutive_confirmation(self):
        trader, calls, _warnings, clock = self._title_trader([
            ("白糖", "白糖", "白糖"),
            ("", "", ""),
            ("白糖", "白糖", "白糖"),
            ("白糖", "白糖", "白糖"),
        ])
        with patch("src.tasks.map_trade.trader_sell.monotonic", lambda: clock[0]):
            self.assertTrue(trader._wait_sale_dialog_item(CalendarEntry("白糖", "S2")))
        self.assertEqual([0, 1, 1, 1, 2, 3], [c[0] for c in calls])

    def test_sale_dialog_rejects_fragments_and_single_frame_confirmation(self):
        for text in ("", "姜", "黄", "姜黄油", "白糖"):
            with self.subTest(text=text):
                trader, calls, _warnings, clock = self._title_trader([(text, text, text)])
                with patch("src.tasks.map_trade.trader_sell.monotonic", lambda: clock[0]):
                    self.assertFalse(trader._wait_sale_dialog_item(
                        CalendarEntry("白糖" if text == "白糖" else "姜黄", "S12"), timeout=0,
                    ))
                self.assertLessEqual(len(calls), 3)

    def test_sale_dialog_rejects_wrong_or_ambiguous_identity_before_fallback(self):
        for texts, aliases in (("豆子", ()), (("姜黄", "豆子"), ())):
            with self.subTest(texts=texts, aliases=aliases):
                trader, calls, warnings, clock = self._title_trader([(texts, texts, texts)])
                with patch("src.tasks.map_trade.trader_sell.monotonic", lambda: clock[0]):
                    self.assertFalse(trader._wait_sale_dialog_item(
                        CalendarEntry("姜黄", "S12", aliases=aliases),
                    ))
                self.assertEqual(1, len(calls))
                self.assertTrue(trader._sale_dialog_rejected)
                self.assertTrue(warnings)

    def test_sale_dialog_owned_quantity_uses_given_region(self):
        calls = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(sleep=lambda *_args: None)
        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda _frame, name, relative_roi: (
                calls.append((name, relative_roi)) or "拥有 8,400 个"
            ),
            simplify=lambda value: value,
        )

        self.assertEqual(8400, trader._wait_owned_quantity(timeout=0.0))
        # Two reads that agree, even with no time left.
        self.assertEqual([("出售弹窗库存", SALE_DIALOG_REGION)] * 2, calls)

    def test_sale_dialog_owned_quantity_needs_two_matching_reads(self):
        # One read with an extra digit must not be taken (40245 → 140245
        # would make selling everything look like keeping the reserve).
        reads = iter(["拥有 140245 个", "拥有 40245 个", "拥有 40245 个"])
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(sleep=lambda *_args: None)
        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda _frame, _name, relative_roi: next(reads),
            simplify=lambda value: value,
        )

        self.assertEqual(40245, trader._wait_owned_quantity(timeout=1.0))

    def test_sale_dialog_separates_owned_and_available_quantities(self):
        calls = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(sleep=lambda *_args: None)
        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda _frame, name, relative_roi: (
                calls.append((name, relative_roi)) or "兽肉 拥有335,005个 1个 可购买94,481个"
            ),
            simplify=lambda value: value,
        )

        self.assertEqual(335005, trader._wait_owned_quantity(timeout=0.0))
        self.assertEqual(94481, trader._wait_available_quantity(timeout=0.0))
        self.assertEqual(
            94481,
            Trader._selected_quantity_from_text("兽肉 拥有335,005个 94481个 可购买94481个"),
        )
        self.assertEqual(
            [
                ("出售弹窗库存", SALE_DIALOG_REGION),
                ("出售弹窗库存", SALE_DIALOG_REGION),
                ("出售弹窗可购买数量", SALE_DIALOG_REGION),
                ("出售弹窗可购买数量", SALE_DIALOG_REGION),
            ],
            calls,
        )

    def test_sale_completion_ignores_previous_transaction_toast(self):
        frames = [
            np.zeros((1080, 1920, 3), dtype=np.uint8),
            np.zeros((1080, 1920, 3), dtype=np.uint8),
        ]
        toast_texts = iter(["交易差价5 完成!", "交易差价6 完成!"])
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            sleep=lambda *_args: None,
            info_set=lambda *_args: None,
            log_warning=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(
            capture=lambda: frames[0].copy(),
            ocr_text=lambda _frame, name, **_kwargs: "",
            simplify=lambda value: value,
            ocr_boxes=lambda *_args, **_kwargs: [SimpleNamespace(name=next(toast_texts))],
        )

        self.assertTrue(
            trader._wait_sale_completion(
                CalendarEntry("兽肉", "S3"),
                frames[0],
                (("兽肉", 620, 560, 44, 23),),
                timeout=1.0,
                before_toast_id=5,
            )
        )

    def test_sale_completion_reads_the_page_once_per_poll(self):
        calls = []
        moved = [SimpleNamespace(name="兽肉", x=620, y=600, width=44, height=23)]
        pages = iter([moved, moved])
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            sleep=lambda *_args: None,
            info_set=lambda *_args: None,
            log_warning=lambda *_args: None,
        )

        def ocr_boxes(*_args, **_kwargs):
            calls.append("page")
            return next(pages)

        def ocr_text(_frame, name, **_kwargs):
            calls.append(name)
            return ""

        trader.vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=ocr_text,
            simplify=lambda value: value,
            ocr_boxes=ocr_boxes,
        )
        self.assertTrue(
            trader._wait_sale_completion(
                CalendarEntry("兽肉", "S3"),
                np.zeros((1080, 1920, 3), dtype=np.uint8),
                (("兽肉", 620, 560, 44, 23),),
                timeout=5.0,
                before_toast_id=5,
            )
        )
        # The dialog is read until it is gone, then one page read per poll.
        self.assertEqual(["出售弹窗完成确认", "page", "page"], calls)

    def test_rare_items_are_skipped_and_same_shop_is_selected_only_once(self):
        selected = []
        sold = []
        logs = []
        entries = (
            CalendarEntry("魅惑粉末", "S6:异教塔", sell=False),
            CalendarEntry("甜辣酱", "S10:霍尔蒙克斯"),
            CalendarEntry("藏红花", "S10:霍尔蒙克斯"),
        )
        trader = object.__new__(Trader)
        trader.started_at = datetime(2026, 7, 18)
        trader.calendar_client = SimpleNamespace(
            load=lambda **_kwargs: SimpleNamespace(
                source="bundled",
                entries_for=lambda _day: entries,
            )
        )
        trader.task = SimpleNamespace(
            config={
                "使用程序默认价表": True,
                "使用在线价表": True,
                "自定义最高价表": "",
            },
            log_info=logs.append,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader._sale_whitelist = lambda: set()
        trader._entry_allowed = lambda _entry, _whitelist: True
        trader.select_shop_tab = lambda shop: selected.append(shop) or True
        trader._sell_selected_entry = lambda entry: sold.append(entry.item) or True

        self.assertTrue(trader.sell_max_price_items())
        self.assertEqual(["S10:霍尔蒙克斯"], selected)
        self.assertEqual(["甜辣酱", "藏红花"], sold)
        self.assertIn("卖：魅惑粉末标记为不出售，跳过。", logs)

    def test_disabled_sale_whitelist_sells_all_allowed_calendar_entries(self):
        sold = []
        logs = []
        statuses = []
        entries = (
            CalendarEntry("番茄", "S1:血骑士"),
            CalendarEntry("魅惑粉末", "S6:异教塔", sell=False),
            CalendarEntry("大麦", "S18:救赎"),
        )
        trader = object.__new__(Trader)
        trader.started_at = datetime(2026, 7, 4)
        trader.calendar_client = SimpleNamespace(
            load=lambda **_kwargs: SimpleNamespace(
                source="bundled",
                entries_for=lambda _day: entries,
            )
        )
        trader.task = SimpleNamespace(
            config={
                "使用程序默认价表": True,
                "使用在线价表": True,
                "自定义最高价表": "",
                "使用出售白名单": False,
                "出售白名单": "番茄",
            },
            log_info=logs.append,
            log_warning=lambda *_args: None,
            info_set=lambda key, value: statuses.append((key, value)),
        )
        trader.select_shop_tab = lambda _shop: True
        trader._sell_selected_entry = lambda entry: sold.append(entry.item) or True

        self.assertTrue(trader.sell_max_price_items())
        self.assertEqual(["番茄", "大麦"], sold)
        self.assertIn(("出售白名单", "关闭"), statuses)
        self.assertIn("卖：出售白名单已关闭，执行价表中全部允许出售的商品。", logs)

    def test_enabled_sale_blacklist_excludes_matching_allowed_entry(self):
        sold = []
        logs = []
        statuses = []
        entries = (
            CalendarEntry("番茄", "S1:血骑士"),
            CalendarEntry("大麦", "S18:救赎"),
        )
        trader = object.__new__(Trader)
        trader.started_at = datetime(2026, 7, 4)
        trader.calendar_client = SimpleNamespace(
            load=lambda **_kwargs: SimpleNamespace(
                source="bundled",
                entries_for=lambda _day: entries,
            )
        )
        trader.task = SimpleNamespace(
            config={
                "使用程序默认价表": True,
                "使用在线价表": True,
                "自定义最高价表": "",
                "使用出售白名单": False,
                "使用出售黑名单": True,
                "出售黑名单": "大麦",
            },
            log_info=logs.append,
            log_warning=lambda *_args: None,
            info_set=lambda key, value: statuses.append((key, value)),
        )
        trader.vision = SimpleNamespace(simplify=lambda value: value)
        trader.select_shop_tab = lambda _shop: True
        trader._sell_selected_entry = lambda entry: sold.append(entry.item) or True

        self.assertTrue(trader.sell_max_price_items())
        self.assertEqual(["番茄"], sold)
        self.assertIn(("出售黑名单", "开启"), statuses)
        self.assertIn("卖：大麦命中出售黑名单，跳过。", logs)

    def test_missing_sale_item_is_reported_and_does_not_stop_next_item(self):
        statuses = []
        warnings = []
        attempted = []
        entries = (
            CalendarEntry("豆子", "S12:海边天使"),
            CalendarEntry("小麦", "S12:海边天使"),
        )
        trader = object.__new__(Trader)
        trader.started_at = datetime(2026, 7, 21, 12, tzinfo=UTC_PLUS_8)
        trader.calendar_client = SimpleNamespace(
            load=lambda **_kwargs: SimpleNamespace(
                source="bundled",
                entries_for=lambda _day: entries,
            )
        )
        trader.task = SimpleNamespace(
            config={
                "使用程序默认价表": True,
                "使用在线价表": True,
                "自定义最高价表": "",
            },
            log_info=lambda *_args: None,
            log_warning=warnings.append,
            info_set=lambda key, value: statuses.append((key, value)),
        )
        trader.vision = SimpleNamespace(simplify=lambda value: value)
        trader._sale_whitelist = lambda: set()
        trader._entry_allowed = lambda _entry, _whitelist: True
        trader.select_shop_tab = lambda _shop: True

        def sell(entry):
            attempted.append(entry.item)
            trader._last_sale_unavailable = entry.item == "豆子"
            trader._last_sale_reason = (
                "未发现商品名，可能无货或已经售出"
                if trader._last_sale_unavailable
                else ""
            )
            return not trader._last_sale_unavailable

        trader._sell_selected_entry = sell

        self.assertTrue(trader.sell_max_price_items())
        self.assertEqual(["豆子", "小麦"], attempted)
        self.assertIn(
            ("未出售商品", "豆子（未发现商品名，可能无货或已经售出）"),
            statuses,
        )
        self.assertIn(
            "未出售商品：豆子（未发现商品名，可能无货或已经售出）",
            warnings,
        )

    def test_sale_execution_failure_stops_following_calendar_entry(self):
        attempted = []
        entries = (
            CalendarEntry("豆子", "S12:海边天使"),
            CalendarEntry("小麦", "S12:海边天使"),
        )
        trader = object.__new__(Trader)
        trader.started_at = datetime(2026, 7, 21, 12, tzinfo=UTC_PLUS_8)
        trader.calendar_client = SimpleNamespace(
            load=lambda **_kwargs: SimpleNamespace(
                source="bundled",
                entries_for=lambda _day: entries,
            )
        )
        trader.task = SimpleNamespace(
            config={
                "使用程序默认价表": True,
                "使用在线价表": True,
                "自定义最高价表": "",
            },
            log_info=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        trader._sale_whitelist = lambda: set()
        trader._entry_allowed = lambda _entry, _whitelist: True
        trader.select_shop_tab = lambda _shop: True

        def fail(entry):
            attempted.append(entry.item)
            trader._last_sale_unavailable = False
            trader._last_sale_reason = "出售完成确认超时"
            return False

        trader._sell_selected_entry = fail
        trader._sale_dialog_shown = lambda _frame=None: False

        self.assertFalse(trader.sell_max_price_items())
        # One on-the-spot retry of the failed item, then the later items stop.
        self.assertEqual(["豆子", "豆子"], attempted)

    def test_a_sale_that_works_on_the_quick_retry_carries_on(self):
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(log_info=lambda *_a: None)
        results = iter([False, True])

        def sell(_entry):
            trader._last_sale_unavailable = False
            return next(results)

        trader._sell_selected_entry = sell
        trader._sale_drag_refused = False
        closed = []
        trader._sale_dialog_shown = lambda _frame=None: True
        trader._close_sale_dialog = lambda: closed.append(True) or True
        self.assertTrue(trader._sell_entry_with_retry(CalendarEntry("豆子", "S12")))
        self.assertEqual([True], closed)  # the dialog was closed before retrying

    def test_no_retry_when_the_dialog_will_not_close(self):
        trader = object.__new__(Trader)
        calls = []

        def sell(_entry):
            calls.append(1)
            trader._last_sale_unavailable = False
            return False

        trader._sell_selected_entry = sell
        trader._sale_drag_refused = False
        trader._sale_dialog_shown = lambda _frame=None: True
        trader._close_sale_dialog = lambda: False
        self.assertFalse(trader._sell_entry_with_retry(CalendarEntry("豆子", "S12")))
        self.assertEqual(1, len(calls))


class TradeAssetsTest(unittest.TestCase):
    def test_card_and_recipe_templates_are_packaged(self):
        template_root = ROOT / "recognition-assets" / "template-assets"
        templates = [card.template for card in STORY_CARDS]
        templates.extend(RECIPE_TEMPLATES.values())
        templates.extend(
            [
                QUICK_SWITCH_TEMPLATE.file_name,
                MAP_MERCHANT_ICON_TEMPLATE.file_name,
                BUY_TO_SELL_SOLD_OUT_TEMPLATE.file_name,
                SALE_120_PERCENT_MARKER_BETA_TEMPLATE.file_name,
                SALE_120_PERCENT_MARKER_TEMPLATE.file_name,
            ]
        )
        templates.extend(spec.file_name for _number, spec in STORY_BADGE_SPECS)

        for relative_path in templates:
            with self.subTest(template=relative_path):
                self.assertTrue((template_root / relative_path).is_file())

    def test_sale_120_marker_template_matches_all_real_fixture_markers_at_fhd(self):
        fixture_path = (
            ROOT / "tests" / "fixtures" / "map_trade" / "trade_shop" / "sale_120_markers_fhd.png"
        )
        frame = cv2.imread(str(fixture_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        task = SimpleNamespace(config={}, vision_threshold_key="跑图跑商识图阈值")
        vision = Vision(task)
        threshold = vision.threshold_for(SALE_120_PERCENT_MARKER_TEMPLATE)

        results = vision.match_all(
            frame,
            SALE_120_PERCENT_MARKER_TEMPLATE,
            minimum_score=threshold,
            peak_radius=SALE_120_PERCENT_MARKER_PEAK_RADIUS,
            max_results=SALE_120_PERCENT_MARKER_MAX_RESULTS,
        )

        self.assertEqual(
            [(493, 563), (825, 563), (1157, 563)],
            sorted(result.position for result in results),
        )
        for result in results:
            self.assertGreaterEqual(result.score, threshold)
            self.assertGreaterEqual(
                result.pixel_score,
                SALE_120_PERCENT_MARKER_TEMPLATE.min_pixel_score,
            )

    def test_sale_120_marker_template_matches_real_markers_after_resolution_scaling(self):
        fixture_path = (
            ROOT / "tests" / "fixtures" / "map_trade" / "trade_shop" / "sale_120_markers_fhd.png"
        )
        fixture = cv2.imread(str(fixture_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(fixture)
        task = SimpleNamespace(config={}, vision_threshold_key="跑图跑商识图阈值")
        vision = Vision(task)
        threshold = vision.threshold_for(SALE_120_PERCENT_MARKER_TEMPLATE)

        for height, width in ((720, 1280), (1440, 2560), (2160, 3840)):
            with self.subTest(height=height):
                interpolation = cv2.INTER_AREA if height < 1080 else cv2.INTER_CUBIC
                frame = cv2.resize(fixture, (width, height), interpolation=interpolation)
                results = vision.match_all(
                    frame,
                    SALE_120_PERCENT_MARKER_TEMPLATE,
                    minimum_score=threshold,
                    peak_radius=SALE_120_PERCENT_MARKER_PEAK_RADIUS,
                    max_results=SALE_120_PERCENT_MARKER_MAX_RESULTS,
                )
                self.assertEqual(3, len(results))
                centers = sorted(result.center for result in results)
                expected_centers = [
                    (
                        round((x + 26) * width / 1920),
                        round((563 + 7) * height / 1080),
                    )
                    for x in (493, 825, 1157)
                ]
                for center, expected in zip(centers, expected_centers, strict=True):
                    self.assertLessEqual(abs(center[0] - expected[0]), 2)
                    self.assertLessEqual(abs(center[1] - expected[1]), 2)
                for result in results:
                    self.assertGreaterEqual(result.score, threshold)
                    self.assertGreaterEqual(
                        result.pixel_score,
                        SALE_120_PERCENT_MARKER_TEMPLATE.min_pixel_score,
                    )

    def test_beta_marker_matches_inside_name_driven_local_roi_with_full_frame_position(self):
        fixture_path = (
            ROOT / "tests" / "fixtures" / "map_trade" / "trade_shop" / "sale_120_markers_fhd.png"
        )
        frame = cv2.imread(str(fixture_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        task = SimpleNamespace(config={}, vision_threshold_key="跑图跑商识图阈值")
        vision = Vision(task)
        results = vision.match_all(
            frame,
            SALE_120_PERCENT_MARKER_BETA_TEMPLATE,
            minimum_score=SALE_120_PERCENT_MARKER_BETA_TEMPLATE.threshold,
            peak_radius=SALE_120_PERCENT_MARKER_PEAK_RADIUS,
            max_results=SALE_120_PERCENT_MARKER_MAX_RESULTS,
            search_roi=(463, 548, 150, 47),
        )

        self.assertEqual([(493, 563)], [result.position for result in results])
        self.assertGreaterEqual(results[0].score, 0.99)
        self.assertGreaterEqual(results[0].pixel_score, 0.97)

    def test_sold_out_template_separates_recorded_buy_and_sell_frames(self):
        fixture_root = ROOT / "tests" / "fixtures" / "map_trade" / "trade_shop"
        task = SimpleNamespace(
            config={"跑商识图阈值": 0.72},
            vision_threshold_key="跑商识图阈值",
        )
        vision = Vision(task)
        results = {}
        for name in ("before_purchase.png", "after_purchase.png", "sell_page.png"):
            frame = cv2.imread(str(fixture_root / name), cv2.IMREAD_COLOR)
            self.assertIsNotNone(frame, name)
            results[name] = vision.match(frame, BUY_TO_SELL_SOLD_OUT_TEMPLATE)

        self.assertFalse(
            vision.passes(results["before_purchase.png"], BUY_TO_SELL_SOLD_OUT_TEMPLATE)
        )
        self.assertTrue(
            vision.passes(results["after_purchase.png"], BUY_TO_SELL_SOLD_OUT_TEMPLATE)
        )
        self.assertFalse(
            vision.passes(results["sell_page.png"], BUY_TO_SELL_SOLD_OUT_TEMPLATE)
        )
        positive = results["after_purchase.png"]
        self.assertGreaterEqual(positive.score, 0.95)
        self.assertGreaterEqual(positive.pixel_score, 0.96)
        self.assertGreaterEqual(positive.zncc_score, 0.95)


class BuyEntryTest(unittest.TestCase):
    def setUp(self):
        # These tests stub the keyword wait; the menu check routes through it
        # (its re-press behaviour has its own test below).
        def confirm(navigator):
            return navigator._wait_for_ocr_keywords(
                ("砍价",), Q_SP6_BARGAIN_OCR_TIMEOUT, "砍价入口"
            )

        patcher = patch.object(Navigator, "_confirm_merchant_menu", confirm)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_menu_opens_after_re_pressing_the_prompt(self):
        # Live 2026-09-27: the first press came while still auto-walking.
        task = SimpleNamespace(
            config={}, sleep=lambda *_a: None, log_warning=lambda *a, **k: None,
            info_set=lambda *a: None,
        )
        navigator = Navigator(task, SimpleNamespace(capture=lambda: None))
        navigator.ensure_small_minimap = lambda: True
        reads = iter([False, False, True])
        navigator._ocr_keywords_in_frame = lambda *a, **k: (next(reads), "")
        presses = []
        navigator._click_merchant_interaction = lambda *a, **k: presses.append(1) or True
        self.assertTrue(self._real_confirm(navigator))
        self.assertEqual(2, len(presses))

    @staticmethod
    def _real_confirm(navigator):
        from src.tasks.map_trade.navigator_trade import TradeNavigationMixin

        return TradeNavigationMixin._confirm_merchant_menu(navigator)

    def test_buy_entry_goes_to_merchant_when_prompt_is_missing_then_bargains(self):
        clicks = []
        events = []
        keyword_checks = []
        shop_confirm_checks = []
        sleeps = []

        task = SimpleNamespace(
            config={"加载页面等待秒数": 45.0},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda seconds: sleeps.append(seconds),
            log_warning=lambda *_args, **_kwargs: None,
            open_cartridge_quick_switcher=lambda **_kwargs: self.fail(
                "buy entry must reach the merchant through go_to_trade_merchant"
            ),
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        shop_entry_results = iter((False, True))
        navigator._enter_q_sp6_shop = lambda timeout, *, log_timeout: (
            events.append(("shop", timeout, log_timeout)) or next(shop_entry_results)
        )
        navigator.go_to_trade_merchant = lambda: (
            events.append("go_to_trade_merchant")
            or NavigationResult(True, ScreenState.SANDBOX, "已到达商人旁")
        )
        navigator._wait_for_ocr_keywords = lambda keywords, timeout, name: (
            keyword_checks.append((keywords, timeout, name)) or True
        )
        navigator._wait_for_bargain_tip = lambda tip: (
            keyword_checks.append(((tip,), 10.0, "砍价说明")) or "tip"
        )
        navigator._wait_for_bargain_shop_confirmation = lambda: (
            shop_confirm_checks.append(True) or True
        )

        result = navigator.enter_q_sp6_buy_flow()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.SHOP, result.state)
        self.assertEqual([True], shop_confirm_checks)
        self.assertEqual(
            [
                ("shop", Q_SP6_SHOP_PRIORITY_TIMEOUT, False),
                "go_to_trade_merchant",
                ("shop", MERCHANT_NAV_LANDMARK_TIMEOUT, True),
            ],
            events,
        )
        self.assertEqual(
            [
                (*BARGAIN_POINT, 0.0),
                (*BARGAIN_CONFIRM_POINT, 0.0),
            ],
            clicks,
        )
        self.assertEqual(
            [
                (("砍价",), Q_SP6_BARGAIN_OCR_TIMEOUT, "砍价入口"),
                (("使用砍价技能后可享受商店折扣价",), 10.0, "砍价说明"),
            ],
            keyword_checks,
        )
        self.assertEqual(
            [Q_SP6_BARGAIN_RECHECK_DELAY, Q_SP6_BARGAIN_CLICK_DELAY],
            sleeps,
        )

    def test_buy_entry_uses_visible_merchant_prompt_before_any_navigation(self):
        clicks = []
        shop_entry_attempts = []
        keyword_checks = []
        shop_confirm_checks = []
        sleeps = []
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda seconds: sleeps.append(seconds),
            log_warning=lambda *_args, **_kwargs: None,
            open_cartridge_quick_switcher=lambda **_kwargs: self.fail(
                "initial merchant prompt hit must bypass HOME navigation"
            ),
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator.go_to_trade_merchant = lambda: self.fail(
            "initial merchant prompt hit must not navigate to the merchant"
        )
        navigator._enter_q_sp6_shop = lambda timeout, *, log_timeout: (
            shop_entry_attempts.append((timeout, log_timeout)) or True
        )
        navigator._wait_for_ocr_keywords = lambda keywords, timeout, name: (
            keyword_checks.append((keywords, timeout, name)) or True
        )
        navigator._wait_for_bargain_tip = lambda tip: (
            keyword_checks.append(((tip,), 10.0, "砍价说明")) or "tip"
        )
        navigator._wait_for_bargain_shop_confirmation = lambda: (
            shop_confirm_checks.append(True) or True
        )

        result = navigator.enter_q_sp6_buy_flow()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.SHOP, result.state)
        self.assertEqual([True], shop_confirm_checks)
        self.assertEqual(
            [(Q_SP6_SHOP_PRIORITY_TIMEOUT, False)],
            shop_entry_attempts,
        )
        self.assertEqual(
            [
                (*BARGAIN_POINT, 0.0),
                (*BARGAIN_CONFIRM_POINT, 0.0),
            ],
            clicks,
        )
        self.assertEqual(
            [
                (("砍价",), Q_SP6_BARGAIN_OCR_TIMEOUT, "砍价入口"),
                (("使用砍价技能后可享受商店折扣价",), 10.0, "砍价说明"),
            ],
            keyword_checks,
        )
        self.assertEqual(
            [Q_SP6_BARGAIN_RECHECK_DELAY, Q_SP6_BARGAIN_CLICK_DELAY],
            sleeps,
        )

    def test_buy_entry_does_not_click_bargain_before_bargain_ocr(self):
        clicks = []
        sleeps = []
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=sleeps.append,
            log_warning=lambda *_args, **_kwargs: None,
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator._enter_q_sp6_shop = lambda *_args, **_kwargs: True
        navigator._wait_for_ocr_keywords = lambda keywords, *_args, **_kwargs: keywords != ("砍价",)
        navigator.classify = lambda: ScreenState.MERCHANT_DIALOG

        result = navigator.enter_q_sp6_buy_flow()

        self.assertFalse(result.success)
        self.assertEqual("商店页面未识别到砍价入口", result.message)
        self.assertEqual([], clicks)
        self.assertEqual([Q_SP6_BARGAIN_RECHECK_DELAY], sleeps)

    def test_buy_entry_stops_when_shop_page_is_not_confirmed_after_bargain(self):
        clicks = []
        shop_confirm_checks = []
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator._enter_q_sp6_shop = lambda *_args, **_kwargs: True
        navigator._wait_for_ocr_keywords = lambda *_args, **_kwargs: True
        navigator._wait_for_bargain_shop_confirmation = lambda: (
            shop_confirm_checks.append(True) or False
        )
        navigator._wait_for_bargain_tip = lambda _tip: "tip"
        navigator.classify = lambda: ScreenState.SHOP

        result = navigator.enter_q_sp6_buy_flow()

        self.assertFalse(result.success)
        self.assertEqual("砍价确认后未通过OCR确认商店页面", result.message)
        self.assertEqual(
            [(*BARGAIN_POINT, 0.0), (*BARGAIN_CONFIRM_POINT, 0.0)],
            clicks,
        )
        self.assertEqual([True], shop_confirm_checks)

    def test_bargain_shop_confirmation_requires_popup_closed_and_stable_hits(self):
        texts = iter(
            (
                "仓库 严加管理 砍价成功率100% 取消",
                "BROWN DUST II",
                "购买 仓库管理石怪 出售 一键购买全部收藏",
                "购买 仓库管理石怪 出售 一键购买全部收藏",
            )
        )
        sleeps = []
        statuses = []
        task = SimpleNamespace(
            config={},
            sleep=sleeps.append,
            log_warning=lambda *_args, **_kwargs: None,
            info_set=lambda key, value: statuses.append((key, value)),
        )
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, _name: next(texts),
            simplify=lambda value: value,
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertTrue(navigator._wait_for_bargain_shop_confirmation(timeout=5.0))
        self.assertEqual(("砍价后商店页面 OCR稳定", "2/2"), statuses[-1])
        self.assertEqual(3, len(sleeps))

    def test_bargain_shop_confirmation_times_out_when_popup_never_closes(self):
        texts = iter(["仓库 严加管理 砍价成功率100% 取消"] * 20)
        warnings = []
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=warnings.append,
        )
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, _name: next(texts),
            simplify=lambda value: value,
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertFalse(navigator._wait_for_bargain_shop_confirmation(timeout=0.0))
        self.assertTrue(warnings)

    def test_bargain_shop_confirmation_accepts_stable_sold_out_fallback(self):
        texts = iter(("BROWN DUST II", "BROWN DUST II"))
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            log_info=lambda *_args: None,
        )
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        sold_out = MatchResult(
            0.90,
            (500, 250),
            (100, 50),
            pixel_score=0.95,
            zncc_score=0.90,
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, _name: next(texts),
            simplify=lambda value: value,
            match=lambda *_args: sold_out,
            passes=lambda result, _spec: result is sold_out,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertTrue(navigator._wait_for_bargain_shop_confirmation(timeout=5.0))

    def test_bargain_shop_confirmation_rejects_sold_out_while_bargain_popup_visible(self):
        texts = iter(
            (
                "购买全部收藏 砍价成功率100% 取消",
                "购买全部收藏 砍价成功率100% 取消",
            )
        )
        warnings = []
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=warnings.append,
            log_info=lambda *_args: None,
        )
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        sold_out = MatchResult(
            0.90,
            (500, 250),
            (100, 50),
            pixel_score=0.95,
            zncc_score=0.90,
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, _name: next(texts),
            simplify=lambda value: value,
            match=lambda *_args: sold_out,
            passes=lambda result, _spec: result is sold_out,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertFalse(navigator._wait_for_bargain_shop_confirmation(timeout=0.0))
        self.assertTrue(warnings)

    def test_buy_shop_entry_clicks_merchant_prompt_center_without_template_match(self):
        client_clicks = []
        ocr_calls = []
        warnings = []
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        task = SimpleNamespace(
            config={"加载页面等待秒数": 45.0},
            sleep=lambda *_args: None,
            log_warning=lambda message: warnings.append(message),
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda captured, name, roi: (
                ocr_calls.append((captured, name, roi))
                or [SimpleNamespace(name="F 无聊收集狂大叔", x=1100, y=300, width=120, height=40)]
            ),
            simplify=lambda value: value,
            match=lambda *_args: self.fail("merchant prompt must not use template matching"),
            click_client=lambda point, frame_shape, after_sleep=0: client_clicks.append(
                (point, frame_shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertTrue(navigator._enter_q_sp6_shop(5.0, log_timeout=True))
        self.assertEqual([((1160, 320), frame.shape, 0.0)], client_clicks)
        self.assertEqual([(frame, "商人互动按钮", MERCHANT_PROMPT_OCR_ROI)], ocr_calls)
        self.assertEqual([], warnings)

    def test_buy_shop_entry_logs_prompt_failure_only_when_asked(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for log_timeout, expected_warnings in ((False, 0), (True, 1)):
            with self.subTest(log_timeout=log_timeout):
                warnings = []
                task = SimpleNamespace(
                    config={},
                    sleep=lambda *_args: None,
                    log_warning=warnings.append,
                )
                vision = SimpleNamespace(
                    capture=lambda: frame,
                    ocr_boxes=lambda *_args: [],
                    simplify=lambda value: value,
                    click_client=lambda *_args, **_kwargs: self.fail("no prompt, no click"),
                )
                navigator = Navigator(task, vision)
                navigator.ensure_small_minimap = lambda: True

                with patch(
                    "src.tasks.map_trade.navigator_trade.monotonic",
                    side_effect=(0.0, 5.0),
                ):
                    self.assertFalse(navigator._enter_q_sp6_shop(1.0, log_timeout=log_timeout))
                self.assertEqual(expected_warnings, len(warnings))
                if warnings:
                    self.assertIn(MERCHANT_PROMPT_FAILURE_MESSAGE, warnings[0])

    def test_buy_entry_uses_seven_quick_page_labels_and_story_badge_templates(self):
        self.assertEqual(
            (
                "最近",
                "店长游戏卡",
                "剧情游戏卡",
                "角色游戏卡",
                "战斗玩法游戏卡带",
                "生活玩法游戏卡带",
                "活动游戏卡",
            ),
            QUICK_SWITCH_PAGE_KEYWORDS,
        )
        self.assertEqual((557 / 1920, 877 / 1080), STORY_CATEGORY_POINT)
        # The trade runs at chapter 1 血骑士's merchant 无聊收集狂大叔.
        self.assertEqual(1, TRADE_STORY_NUMBER)
        self.assertEqual("Q_sp1", MERCHANT_CARD_ID)
        self.assertEqual(TRADE_STORY_NUMBER, CARD_BY_ID[MERCHANT_CARD_ID].number)
        self.assertEqual(
            "quick_switch_cartridges/story_cartridge_badge_01.png",
            dict(STORY_BADGE_SPECS)[TRADE_STORY_NUMBER].file_name,
        )
        self.assertEqual((0.0, 908 / 1080, 1.0, 1.0), QUICK_SWITCH_CARTRIDGE_REGION)
        self.assertEqual(tuple(range(1, 21)), tuple(value[0] for value in STORY_BADGE_SPECS))
        self.assertEqual(
            "quick_switch_cartridges/story_cartridge_badge_06.png",
            STORY_BADGE_SPECS[5][1].file_name,
        )
        self.assertTrue(
            all(spec.relative_roi == QUICK_SWITCH_CARTRIDGE_REGION for _, spec in STORY_BADGE_SPECS)
        )
        self.assertTrue(all(not spec.green_mask for _, spec in STORY_BADGE_SPECS))
        self.assertTrue(
            all(
                spec.min_zncc_score == STORY_BADGE_CANDIDATE_ZNCC_SCORE
                for _, spec in STORY_BADGE_SPECS
            )
        )
        self.assertTrue(all(spec.scale_ratios == (1.0,) for _, spec in STORY_BADGE_SPECS))
        template_root = ROOT / "recognition-assets" / "template-assets"
        for _number, spec in STORY_BADGE_SPECS:
            template = cv2.imread(
                str(template_root / spec.file_name),
                cv2.IMREAD_UNCHANGED,
            )
            self.assertIsNotNone(template, spec.file_name)
            self.assertEqual((29, 29, 4), template.shape, spec.file_name)
            self.assertGreater(np.count_nonzero(template[:, :, 3] == 0), 0)
            self.assertGreater(np.count_nonzero(template[:, :, 3] == 255), 0)
            self.assertTrue(np.all(template[[0, 0, -1, -1], [0, -1, 0, -1], 3] == 0))
        self.assertEqual((191 / 1920, 900 / 1080), BARGAIN_POINT)
        self.assertEqual((1047 / 1920, 652 / 1080), BARGAIN_CONFIRM_POINT)
        self.assertEqual("image/green/QuickSwitchPlayIco.png", QUICK_SWITCH_TEMPLATE.file_name)
        self.assertEqual(
            ((0.15, 0.85, 0.65, 1.0), (0.16, 0.08, 0.24, 0.19)),
            QUICK_SWITCH_TEMPLATE.relative_rois,
        )
        self.assertEqual((0.95, 0.975, 1.0, 1.025, 1.05), QUICK_SWITCH_TEMPLATE.scale_ratios)
        self.assertEqual(0.85, QUICK_SWITCH_TEMPLATE.min_pixel_score)
        self.assertEqual(0.88, QUICK_SWITCH_TEMPLATE.minimum_safe_threshold)
        # BUG-20260902-06：广场内暗色圆底按钮 1600x901 实测 zncc 最高 0.838，
        # 误检位置最高 0.43；0.78 在两者之间有足够余量。
        self.assertEqual(0.78, QUICK_SWITCH_TEMPLATE.min_zncc_score)
        self.assertIsNone(QUICK_SWITCH_TEMPLATE.candidate_center_roi)

    def test_merchant_prompt_box_returns_first_ocr_box_naming_the_merchant(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        other = SimpleNamespace(name="F 对话", x=900, y=300, width=80, height=40)
        merchant = SimpleNamespace(name="F 无聊收集狂大叔", x=1100, y=300, width=120, height=40)
        later = SimpleNamespace(name="F收集狂大叔", x=1300, y=500, width=90, height=40)
        ocr_calls = []
        boxes = {"value": [other, merchant, later]}
        vision = SimpleNamespace(
            ocr_boxes=lambda captured, name, roi: (
                ocr_calls.append((captured, name, roi)) or boxes["value"]
            ),
            simplify=lambda value: value,
        )
        navigator = Navigator(SimpleNamespace(config={}), vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertIs(merchant, navigator._merchant_prompt_box(frame))
        self.assertEqual([(frame, "商人互动按钮", MERCHANT_PROMPT_OCR_ROI)], ocr_calls)
        self.assertEqual(r"收集狂大叔", MERCHANT_PROMPT_PATTERN)

        boxes["value"] = [
            other,
            SimpleNamespace(name="F 仓库管理石怪", x=1100, y=300, width=120, height=40),
            SimpleNamespace(name="收集狂", x=1100, y=360, width=60, height=40),
        ]
        self.assertIsNone(navigator._merchant_prompt_box(frame))
        boxes["value"] = []
        self.assertIsNone(navigator._merchant_prompt_box(frame))

    def test_merchant_interaction_clicks_prompt_box_center(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        statuses = []
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda key, value: statuses.append((key, value)),
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda *_args: [
                SimpleNamespace(name="F 对话", x=900, y=300, width=80, height=40),
                SimpleNamespace(name="F 无聊收集狂大叔", x=1133, y=301, width=101, height=41),
            ],
            simplify=lambda value: value,
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertTrue(navigator._click_merchant_interaction(timeout=1.0, after_sleep=1.2))
        self.assertEqual([((1184, 322), frame.shape, 1.2)], clicks)
        self.assertEqual(("商人交互点击位置", "center=(1184,322)"), statuses[-1])

    def test_merchant_interaction_waits_for_prompt_until_it_appears(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        prompt = SimpleNamespace(name="F 无聊收集狂大叔", x=1000, y=380, width=100, height=40)
        results = iter(
            ([], [SimpleNamespace(name="F 对话", x=0, y=0, width=1, height=1)], [prompt])
        )
        clicks = []
        sleeps = []
        task = SimpleNamespace(config={}, sleep=sleeps.append, log_warning=lambda *_args: None)
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda *_args: next(results),
            simplify=lambda value: value,
            click_client=lambda point, _shape, after_sleep=0: clicks.append(point),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        with patch(
            "src.tasks.map_trade.navigator_trade.monotonic",
            side_effect=(0.0, 0.5, 1.0),
        ):
            self.assertTrue(
                navigator._click_merchant_interaction(timeout=5.0, after_sleep=0.0, interval=0.3)
            )
        self.assertEqual([(1050, 400)], clicks)
        self.assertEqual([0.3, 0.3], sleeps)

    def test_merchant_interaction_ignores_prompts_that_are_not_the_merchant(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            info_set=lambda *_args: None,
            log_warning=lambda *_args: None,
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda *_args: [
                SimpleNamespace(name="F 对话", x=900, y=300, width=80, height=40),
                SimpleNamespace(name="F 仓库管理石怪", x=1100, y=300, width=120, height=40),
            ],
            simplify=lambda value: value,
            click_client=lambda point, *_args, **_kwargs: clicks.append(point),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        with patch(
            "src.tasks.map_trade.navigator_trade.monotonic",
            side_effect=(0.0, 1.0),
        ):
            self.assertFalse(navigator._click_merchant_interaction(timeout=0.0, after_sleep=1.2))
        self.assertEqual([], clicks)

    def test_merchant_interaction_miss_fails_without_navigation_fallback(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        fallback_calls = []
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
            operate_click=lambda *_args, **_kwargs: fallback_calls.append("operate_click"),
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda *_args: [],
            simplify=lambda value: value,
            click_client=lambda point, shape, after_sleep=0: clicks.append(point),
            wait_template=lambda *_args, **_kwargs: fallback_calls.append("wait_template"),
            click_template=lambda *_args, **_kwargs: fallback_calls.append("click_template"),
            click_ocr=lambda *_args, **_kwargs: fallback_calls.append("click_ocr"),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        with patch("src.tasks.map_trade.navigator_trade.monotonic", side_effect=(0.0, 3.0)):
            clicked = navigator._click_merchant_interaction(timeout=2.0, after_sleep=1.2)

        self.assertFalse(clicked)
        self.assertEqual([], clicks)
        self.assertEqual([], fallback_calls)

    def test_map_merchant_icon_is_root_1080p_crop_matching_at_client_sizes(self):
        template_root = ROOT / "recognition-assets" / "template-assets"
        self.assertEqual("TradeMapMerchantIcon.png", MAP_MERCHANT_ICON_TEMPLATE.file_name)
        self.assertFalse(MAP_MERCHANT_ICON_TEMPLATE.green_mask)
        self.assertAlmostEqual(
            1.0,
            offline_template_scale(MAP_MERCHANT_ICON_TEMPLATE.file_name, 1920, 1080),
        )
        self.assertAlmostEqual(
            2 / 3,
            offline_template_scale(MAP_MERCHANT_ICON_TEMPLATE.file_name, 1280, 720),
        )
        icon = cv2.imread(str(template_root / MAP_MERCHANT_ICON_TEMPLATE.file_name))
        self.assertIsNotNone(icon)

        rng = np.random.default_rng(3)
        background = cv2.GaussianBlur(
            rng.integers(40, 140, (1080, 1920, 3), dtype=np.uint8),
            (0, 0),
            6,
        )
        with_icon = background.copy()
        height, width = icon.shape[:2]
        with_icon[600:600 + height, 1000:1000 + width] = icon
        vision = Vision(SimpleNamespace(config={}, vision_threshold_key="跑图跑商识图阈值"))
        for size in ((1920, 1080), (1280, 720), (2560, 1440)):
            with self.subTest(size=size):
                interpolation = cv2.INTER_AREA if size[0] < 1920 else cv2.INTER_CUBIC
                frame = cv2.resize(with_icon, size, interpolation=interpolation)
                result = vision.match(frame, MAP_MERCHANT_ICON_TEMPLATE)
                self.assertTrue(vision.passes(result, MAP_MERCHANT_ICON_TEMPLATE))
                expected = (
                    round((1000 + width / 2) * size[0] / 1920),
                    round((600 + height / 2) * size[1] / 1080),
                )
                self.assertLessEqual(abs(result.center[0] - expected[0]), 2)
                self.assertLessEqual(abs(result.center[1] - expected[1]), 2)
        missing = vision.match(background, MAP_MERCHANT_ICON_TEMPLATE)
        self.assertFalse(vision.passes(missing, MAP_MERCHANT_ICON_TEMPLATE))

    def test_merchant_marker_asset_is_removed(self):
        template_root = ROOT / "recognition-assets" / "template-assets"
        self.assertFalse(
            any(
                path.name.endswith("IcoGE.png")
                for path in template_root.joinpath("image", "green").glob("Merchant_*.png")
            )
        )


class TradeMerchantNavigationTest(unittest.TestCase):
    """Reaching the chapter-1 merchant 无聊收集狂大叔 before bargaining or cooking."""

    def _navigator(self, vision=None, **task_overrides):
        self.warnings = []
        self.sleeps = []
        task = SimpleNamespace(
            config={"加载页面等待秒数": 45.0},
            sleep=self.sleeps.append,
            log_warning=lambda message, **_kwargs: self.warnings.append(message),
            info_set=lambda *_args: None,
            **task_overrides,
        )
        navigator = Navigator(task, vision if vision is not None else SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        return navigator

    @staticmethod
    def _located_trade_card():
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        badge = StoryBadgeDetection(
            best=StoryBadgeCandidate(
                TRADE_STORY_NUMBER,
                MatchResult(0.99, (80, 930), (30, 28), pixel_score=0.98),
            ),
            runner_up=StoryBadgeCandidate(
                2,
                MatchResult(0.80, (81, 930), (31, 31), pixel_score=0.82),
            ),
        )
        return LocatedStoryCard(CARD_BY_ID[MERCHANT_CARD_ID], frame, badge)

    # go_to_trade_merchant -------------------------------------------------

    def test_go_to_trade_merchant_is_done_when_prompt_already_visible(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        probed = []
        navigator = self._navigator(SimpleNamespace(capture=lambda: frame))
        navigator._merchant_prompt_box = lambda captured: probed.append(captured) or object()
        navigator._enter_trade_card = lambda: self.fail("prompt visible: no cartridge entry")
        navigator._walk_to_merchant = lambda: self.fail("prompt visible: no walking")

        result = navigator.go_to_trade_merchant()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.SANDBOX, result.state)
        self.assertEqual(1, len(probed))
        self.assertIs(frame, probed[0])

    def test_go_to_trade_merchant_enters_card_and_stops_when_prompt_shows(self):
        events = []
        navigator = self._navigator(SimpleNamespace(capture=lambda: None))
        navigator._merchant_prompt_box = lambda _frame: events.append("probe") or None
        navigator._enter_trade_card = lambda: (
            events.append("enter") or NavigationResult(True, ScreenState.SANDBOX, MERCHANT_CARD_ID)
        )
        navigator._wait_for_merchant_prompt = lambda timeout: (
            events.append(("prompt", timeout)) or True
        )
        navigator._walk_to_merchant = lambda: self.fail("prompt after entry: no walking")

        result = navigator.go_to_trade_merchant()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.SANDBOX, result.state)
        self.assertEqual(["probe", "enter", ("prompt", 2.0)], events)

    def test_go_to_trade_merchant_walks_when_prompt_missing_after_entry(self):
        events = []
        navigator = self._navigator(SimpleNamespace(capture=lambda: None))
        navigator._merchant_prompt_box = lambda _frame: events.append("probe") or None
        navigator._enter_trade_card = lambda: (
            events.append("enter") or NavigationResult(True, ScreenState.SANDBOX, MERCHANT_CARD_ID)
        )
        navigator._wait_for_merchant_prompt = lambda timeout: (
            events.append(("prompt", timeout)) or False
        )
        navigator._walk_to_merchant = lambda: events.append("walk") or True

        result = navigator.go_to_trade_merchant()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.SANDBOX, result.state)
        self.assertEqual(["probe", "enter", ("prompt", 2.0), "walk"], events)

    def test_go_to_trade_merchant_returns_card_entry_failure_unchanged(self):
        failure = NavigationResult(False, ScreenState.CARD_MENU, "未唯一确认剧情游戏卡1角标")
        navigator = self._navigator(SimpleNamespace(capture=lambda: None))
        navigator._merchant_prompt_box = lambda _frame: None
        navigator._enter_trade_card = lambda: failure
        navigator._wait_for_merchant_prompt = lambda _timeout: self.fail("entry failed")
        navigator._walk_to_merchant = lambda: self.fail("entry failed")

        self.assertIs(failure, navigator.go_to_trade_merchant())

    def test_go_to_trade_merchant_fails_with_prompt_message_when_walk_fails(self):
        navigator = self._navigator(SimpleNamespace(capture=lambda: None))
        navigator._merchant_prompt_box = lambda _frame: None
        navigator._enter_trade_card = lambda: NavigationResult(
            True, ScreenState.SANDBOX, MERCHANT_CARD_ID
        )
        navigator._wait_for_merchant_prompt = lambda _timeout: False
        navigator._walk_to_merchant = lambda: False
        navigator.classify = lambda: ScreenState.SANDBOX

        result = navigator.go_to_trade_merchant()

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.SANDBOX, result.state)
        self.assertEqual(MERCHANT_PROMPT_FAILURE_MESSAGE, result.message)

    def test_wait_for_merchant_prompt_polls_until_prompt_or_timeout(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        navigator = self._navigator(SimpleNamespace(capture=lambda: frame))
        prompts = iter((None, None, object()))
        navigator._merchant_prompt_box = lambda _frame: next(prompts)
        with patch(
            "src.tasks.map_trade.navigator_trade.monotonic",
            side_effect=(0.0, 1.0, 2.0),
        ):
            self.assertTrue(navigator._wait_for_merchant_prompt(5.0, interval=0.4))
        self.assertEqual([0.4, 0.4], self.sleeps)

        navigator._merchant_prompt_box = lambda _frame: None
        with patch(
            "src.tasks.map_trade.navigator_trade.monotonic",
            side_effect=(0.0, 1.0, 6.0),
        ):
            self.assertFalse(navigator._wait_for_merchant_prompt(5.0, interval=0.4))

    # _enter_trade_card ----------------------------------------------------

    def test_enter_trade_card_clicks_rechecked_badge_and_needs_consecutive_sandbox(self):
        self.assertGreaterEqual(TRADE_CARD_SANDBOX_HITS, 2)
        located = self._located_trade_card()
        confirmed_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        confirmed_badge = StoryBadgeDetection(
            best=StoryBadgeCandidate(
                TRADE_STORY_NUMBER,
                MatchResult(0.99, (60, 620), (20, 20), pixel_score=0.98),
            ),
            runner_up=None,
        )
        located_ids = []
        rechecks = []
        clicks = []
        states = [ScreenState.LOADING, ScreenState.SANDBOX, ScreenState.LOADING]
        states += [ScreenState.SANDBOX] * TRADE_CARD_SANDBOX_HITS
        pending_states = iter(states)
        classified = []
        vision = SimpleNamespace(
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = self._navigator(vision)
        navigator._locate_story_card = lambda card_id: located_ids.append(card_id) or located
        navigator._confirm_story_badge_before_click = lambda frame, badge: (
            rechecks.append((frame, badge)) or (confirmed_frame, confirmed_badge)
        )

        def classify():
            state = next(pending_states)
            classified.append(state)
            return state

        navigator.classify = classify

        result = navigator._enter_trade_card()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.SANDBOX, result.state)
        self.assertEqual(MERCHANT_CARD_ID, result.message)
        self.assertEqual([MERCHANT_CARD_ID], located_ids)
        self.assertEqual(1, len(rechecks))
        self.assertIs(located.frame, rechecks[0][0])
        self.assertIs(located.badge, rechecks[0][1])
        self.assertEqual([((70, 630), confirmed_frame.shape, 1.0)], clicks)
        # A lone SANDBOX frame between loading frames does not count.
        self.assertEqual(states, classified)

    def test_enter_trade_card_times_out_without_consecutive_sandbox_frames(self):
        located = self._located_trade_card()
        clicks = []
        states = iter(
            (
                ScreenState.SANDBOX,
                ScreenState.LOADING,
                ScreenState.SANDBOX,
                ScreenState.LOADING,
            )
        )
        navigator = self._navigator(
            SimpleNamespace(click_client=lambda point, *_args, **_kwargs: clicks.append(point))
        )
        navigator._locate_story_card = lambda _card_id: located
        navigator._confirm_story_badge_before_click = lambda frame, badge: (frame, badge)
        navigator.classify = lambda: next(states)

        with patch(
            "src.tasks.map_trade.navigator_trade.monotonic",
            side_effect=(0.0, 1.0, 2.0, 3.0, 100.0),
        ):
            result = navigator._enter_trade_card()

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.LOADING, result.state)
        self.assertEqual("剧情游戏卡1入场确认超时", result.message)
        self.assertEqual([located.badge.best.result.center], clicks)

    def test_enter_trade_card_returns_locate_failure_without_clicking(self):
        failure = NavigationResult(False, ScreenState.HOME, "无法从主页打开快速切换卡带页面")
        navigator = self._navigator(
            SimpleNamespace(click_client=lambda *_args, **_kwargs: self.fail("no click"))
        )
        navigator._locate_story_card = lambda _card_id: failure
        navigator._confirm_story_badge_before_click = lambda *_args: self.fail("no recheck")

        self.assertIs(failure, navigator._enter_trade_card())

    def test_enter_trade_card_stops_before_click_when_badge_recheck_fails(self):
        navigator = self._navigator(
            SimpleNamespace(click_client=lambda *_args, **_kwargs: self.fail("no click"))
        )
        navigator._locate_story_card = lambda _card_id: self._located_trade_card()
        navigator._confirm_story_badge_before_click = lambda *_args: None
        navigator.classify = lambda: self.fail("no field wait without a click")

        result = navigator._enter_trade_card()

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.CARD_MENU, result.state)

    # _walk_to_merchant ----------------------------------------------------

    def _walk_navigator(self, *, guide=True, destination=True):
        self.events = []
        vision = SimpleNamespace(
            click_template=lambda spec, timeout, after_sleep: (
                self.events.append(("template", spec, timeout)) or guide
            ),
            click_ocr=lambda patterns, roi, after_sleep, name: (
                self.events.append(("ocr", tuple(patterns), roi, name)) or destination
            ),
        )
        return self._navigator(vision)

    def test_walk_to_merchant_fails_without_ocr_when_guide_button_missing(self):
        navigator = self._walk_navigator(guide=False)
        navigator._confirm_travel = lambda: self.fail("no travel without the guide menu")

        self.assertFalse(navigator._walk_to_merchant())
        self.assertEqual(
            [("template", MERCHANT_NAV_GUIDE_TEMPLATE, MERCHANT_NAV_GUIDE_TIMEOUT)],
            self.events,
        )
        self.assertTrue(self.warnings)

    def test_walk_to_merchant_teleports_via_shop_destination_then_waits_for_prompt(self):
        navigator = self._walk_navigator()
        navigator._confirm_travel = lambda: self.events.append("confirm_travel") or "moving"
        navigator._walk_via_area_map = lambda: self.fail("shop reachable: no area map")
        navigator._wait_for_merchant_prompt = lambda timeout: (
            self.events.append(("prompt", timeout)) or True
        )

        self.assertTrue(navigator._walk_to_merchant())
        # Only 商店 is OCR-clicked in the menu; the travel dialog is _confirm_travel's job.
        self.assertEqual(
            [
                ("template", MERCHANT_NAV_GUIDE_TEMPLATE, MERCHANT_NAV_GUIDE_TIMEOUT),
                ("ocr", ("商店",), MERCHANT_NAV_MENU_OCR_ROI, "商店导航"),
                "confirm_travel",
                ("prompt", MERCHANT_QUICK_ARRIVAL_TIMEOUT),
                ("prompt", MERCHANT_ARRIVAL_TIMEOUT),
            ],
            self.events,
        )

    def test_walk_to_merchant_uses_area_map_when_shop_is_unreachable(self):
        navigator = self._walk_navigator()
        navigator._confirm_travel = lambda: self.events.append("confirm_travel") or "unreachable"
        navigator._walk_via_area_map = lambda: self.events.append("area_map") or True
        navigator._wait_for_merchant_prompt = lambda timeout: (
            self.events.append(("prompt", timeout)) or True
        )

        self.assertTrue(navigator._walk_to_merchant())
        self.assertEqual(
            ["confirm_travel", "area_map", ("prompt", MERCHANT_ARRIVAL_TIMEOUT)],
            self.events[2:],
        )

    def test_walk_to_merchant_fails_when_area_map_icon_is_missing(self):
        navigator = self._walk_navigator()
        navigator._confirm_travel = lambda: "unreachable"
        navigator._walk_via_area_map = lambda: False
        navigator._wait_for_merchant_prompt = lambda _timeout: self.fail("no walk started")

        self.assertFalse(navigator._walk_to_merchant())

    def test_walk_to_merchant_fails_when_prompt_never_appears(self):
        navigator = self._walk_navigator()
        navigator._confirm_travel = lambda: "moving"
        navigator._wait_for_merchant_prompt = lambda _timeout: False
        navigator.classify = lambda: ScreenState.LOADING  # not in the field: no map click
        navigator._walk_via_area_map = lambda: self.fail("still loading: no area map")

        self.assertFalse(navigator._walk_to_merchant())
        self.assertEqual(1, len(self.warnings))
        self.assertIn(MERCHANT_PROMPT_FAILURE_MESSAGE, self.warnings[0])

    def test_travel_that_moved_nothing_falls_back_to_the_area_map(self):
        # Inside the shop, away from the merchant: 立即前往 does nothing and
        # shows no toast (live 2026-09-27).
        navigator = self._walk_navigator()
        navigator._confirm_travel = lambda: "moving"
        prompts = iter([False, True])
        navigator._wait_for_merchant_prompt = lambda _timeout: next(prompts)
        navigator.classify = lambda: ScreenState.SANDBOX
        walked = []
        navigator._walk_via_area_map = lambda: walked.append(1) or True
        self.assertTrue(navigator._walk_to_merchant())
        self.assertEqual([1], walked)

    def test_walk_to_merchant_stops_when_shop_destination_missing(self):
        navigator = self._walk_navigator(destination=False)
        navigator._confirm_travel = lambda: self.fail("no travel without the 商店 destination")

        with patch(
            "src.tasks.map_trade.navigator_trade.monotonic",
            side_effect=(0.0, 0.0, 1000.0),
        ):
            self.assertFalse(navigator._walk_to_merchant())
        ocr_names = [event[3] for event in self.events if event[0] == "ocr"]
        self.assertEqual(["商店导航"], ocr_names)
        self.assertTrue(self.warnings)

    # _confirm_travel ------------------------------------------------------

    def _travel_navigator(self, texts, *, click_result=True):
        self.ocr_reads = []
        self.ocr_clicks = []
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, name, roi=None: (
                self.ocr_reads.append((name, roi)) or texts.get(name, "")
            ),
            click_ocr=lambda patterns, roi, after_sleep, name: (
                self.ocr_clicks.append((tuple(patterns), roi, after_sleep, name))
                or click_result
            ),
        )
        return self._navigator(vision)

    def test_confirm_travel_reports_unreachable_from_toast(self):
        self.assertIn(MERCHANT_NAV_UNREACHABLE_KEYWORD, "现在无法移动的区域")
        navigator = self._travel_navigator({"导航提示": "现在无法移动的区域"})

        self.assertEqual("unreachable", navigator._confirm_travel())
        self.assertEqual([("导航提示", MERCHANT_NAV_TOAST_OCR_ROI)], self.ocr_reads)
        self.assertEqual([], self.ocr_clicks)

    def test_confirm_travel_presses_confirm_on_travel_dialog(self):
        for title in ("是否立即前往？", "自动移动"):
            with self.subTest(title=title):
                navigator = self._travel_navigator({"前往确认": title})

                self.assertEqual("moving", navigator._confirm_travel())
                self.assertIn(("前往确认", MERCHANT_TRAVEL_DIALOG_OCR_ROI), self.ocr_reads)
                self.assertEqual(
                    [(("确认",), MERCHANT_NAV_CONFIRM_OCR_ROI, 0.8, "前往确认按钮")],
                    self.ocr_clicks,
                )
        self.assertEqual(("立即前往", "自动移动"), MERCHANT_TRAVEL_DIALOG_KEYWORDS)

    def test_confirm_travel_cancels_a_dialog_it_cannot_confirm(self):
        # 确认 unreadable until the timeout: the dialog is cancelled, not left up.
        navigator = self._travel_navigator({"前往确认": "是否立即前往？"}, click_result=False)
        with patch(
            "src.tasks.map_trade.navigator_trade.monotonic",
            side_effect=(0.0, 1.0, 2.0, MERCHANT_NAV_OUTCOME_TIMEOUT + 1.0),
        ):
            self.assertEqual("stuck", navigator._confirm_travel())
        self.assertEqual(("^取消$",), self.ocr_clicks[-1][0])

    def test_confirm_travel_assumes_moving_when_dialog_is_suppressed(self):
        navigator = self._travel_navigator({})

        with patch(
            "src.tasks.map_trade.navigator_trade.monotonic",
            side_effect=(0.0, 1.0, 2.0, MERCHANT_NAV_OUTCOME_TIMEOUT + 1.0),
        ):
            self.assertEqual("moving", navigator._confirm_travel())
        self.assertEqual([], self.ocr_clicks)
        self.assertEqual(4, len(self.ocr_reads))
        self.assertEqual(2, len(self.sleeps))

    # _walk_via_area_map ---------------------------------------------------

    def test_walk_via_area_map_opens_map_clicks_merchant_icon_and_confirms(self):
        events = []
        vision = SimpleNamespace(
            click_template=lambda spec, timeout, after_sleep: (
                events.append(("template", spec, timeout, after_sleep)) or True
            ),
        )
        navigator = self._navigator(
            vision,
            operate_click=lambda x, y, after_sleep=0: events.append(("click", x, y, after_sleep)),
        )
        navigator._confirm_travel = lambda: events.append("confirm_travel") or "moving"

        self.assertTrue(navigator._walk_via_area_map())
        self.assertEqual(
            [
                (
                    "click",
                    MINIMAP_CENTER_REFERENCE[0] / 1920,
                    MINIMAP_CENTER_REFERENCE[1] / 1080,
                    1.5,
                ),
                ("template", MAP_MERCHANT_ICON_TEMPLATE, MAP_MERCHANT_ICON_TIMEOUT, 0.8),
                "confirm_travel",
            ],
            events,
        )

    def test_walk_via_area_map_fails_when_merchant_icon_is_missing(self):
        vision = SimpleNamespace(click_template=lambda *_args, **_kwargs: False)
        navigator = self._navigator(vision, operate_click=lambda *_args, **_kwargs: None)
        navigator._confirm_travel = lambda: self.fail("no travel without the merchant icon")

        self.assertFalse(navigator._walk_via_area_map())
        self.assertTrue(self.warnings)


class BuyPhaseAndClassifyTest(unittest.TestCase):
    def setUp(self):
        if self._testMethodName.startswith("test_return_home"):
            # No 折扣商店结束 dialog and no merchant menu unless a test says so.
            for name in ("_discount_close_dialog_shown", "_merchant_menu_shown"):
                patcher = patch.object(Navigator, name, lambda _self: False)
                patcher.start()
                self.addCleanup(patcher.stop)

    def test_classify_rois_keep_reference_rect_boundaries_at_supported_resolutions(self):
        roi_pairs = (
            (CLASSIFY_LOADING_REFERENCE_ROI, CLASSIFY_LOADING_RELATIVE_ROI),
            (CLASSIFY_SHOP_TABS_REFERENCE_ROI, CLASSIFY_SHOP_TABS_RELATIVE_ROI),
            (CLASSIFY_SHOP_TITLE_REFERENCE_ROI, CLASSIFY_SHOP_TITLE_RELATIVE_ROI),
            (
                CLASSIFY_CARD_MENU_TITLE_REFERENCE_ROI,
                CLASSIFY_CARD_MENU_TITLE_RELATIVE_ROI,
            ),
            (
                CLASSIFY_CARD_MENU_CATEGORY_REFERENCE_ROI,
                CLASSIFY_CARD_MENU_CATEGORY_RELATIVE_ROI,
            ),
            (CLASSIFY_COOKING_TITLE_REFERENCE_ROI, CLASSIFY_COOKING_TITLE_RELATIVE_ROI),
            (
                CLASSIFY_COOKING_MATERIALS_REFERENCE_ROI,
                CLASSIFY_COOKING_MATERIALS_RELATIVE_ROI,
            ),
        )
        for frame_width, frame_height in (
            (1280, 720),
            (1920, 1080),
            (2560, 1440),
            (3840, 2160),
        ):
            frame = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)
            for reference_rect, relative_roi in roi_pairs:
                with self.subTest(size=(frame_width, frame_height), rect=reference_rect):
                    expected = scale_reference_roi(
                        reference_rect,
                        (frame_width, frame_height),
                        FHD_1080.size,
                    )
                    left, top, crop = relative_roi_frame(frame, relative_roi)
                    self.assertEqual(expected[:2], (left, top))
                    self.assertEqual((expected[3], expected[2]), crop.shape[:2])
                    self.assertGreater(crop.size, 0)

    def test_chapter_home_templates_use_nonempty_right_edge_roi_at_supported_resolutions(self):
        for frame_width, frame_height in (
            (1280, 720),
            (1920, 1080),
            (2560, 1440),
            (3840, 2160),
        ):
            frame = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)
            expected_left = round(frame_width * 0.86)
            expected_bottom = round(frame_height * 0.18)
            for spec in CHAPTER_HOME_TEMPLATES:
                with self.subTest(size=(frame_width, frame_height), template=spec.name):
                    left, top, crop = relative_roi_frame(frame, spec.relative_roi)
                    self.assertIs(CHAPTER_HOME_RELATIVE_ROI, spec.relative_roi)
                    self.assertEqual((expected_left, 0), (left, top))
                    self.assertEqual(
                        (expected_bottom, frame_width - expected_left),
                        crop.shape[:2],
                    )
                    self.assertEqual(frame_width, left + crop.shape[1])
                    self.assertGreater(crop.size, 0)

    def test_shop_classification_uses_actual_crop_geometry_not_ocr_name(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        expected_crops = {}
        for reference_rect, marker, texts in (
            (CLASSIFY_SHOP_TABS_REFERENCE_ROI, 17, ("购买", "出售")),
            (CLASSIFY_SHOP_TITLE_REFERENCE_ROI, 29, ("仓库", "严加管理")),
        ):
            left, top, width, height = scale_reference_roi(
                reference_rect,
                (frame.shape[1], frame.shape[0]),
                FHD_1080.size,
            )
            frame[top : top + height, left : left + width] = marker
            expected_crops[texts] = frame[top : top + height, left : left + width].copy()

        cropped_frames = []

        def image_driven_ocr(*, frame, **_kwargs):
            cropped_frames.append(frame.copy())
            for texts, expected_crop in expected_crops.items():
                if frame.shape == expected_crop.shape and np.array_equal(frame, expected_crop):
                    return [
                        SimpleNamespace(
                            name=text,
                            confidence=0.99,
                            x=0,
                            y=0,
                            width=10,
                            height=10,
                        )
                        for text in texts
                    ]
            return []

        task = SimpleNamespace(
            config={"跑图跑商 OCR 阈值": 0.2},
            info_set=lambda *_args: None,
            ocr=image_driven_ocr,
        )
        failed = MatchResult(-1.0, (0, 0), (0, 0))
        vision = Vision(task)
        vision.match = lambda *_args: failed
        vision.passes = lambda *_args: False
        vision.template_brightness_ratio = lambda *_args: 0.0
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertEqual(ScreenState.SHOP, navigator.classify(frame))
        for expected_crop in expected_crops.values():
            self.assertTrue(
                any(
                    crop.shape == expected_crop.shape and np.array_equal(crop, expected_crop)
                    for crop in cropped_frames
                )
            )

    def test_buy_entry_fails_when_prompt_is_missing_after_reaching_merchant(self):
        clicks = []
        shop_entry_attempts = []
        task = SimpleNamespace(
            config={"加载页面等待秒数": 45.0},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator._enter_q_sp6_shop = lambda timeout, *, log_timeout: (
            shop_entry_attempts.append((timeout, log_timeout)) or False
        )
        navigator.go_to_trade_merchant = lambda: NavigationResult(
            True, ScreenState.SANDBOX, "已到达商人旁"
        )
        navigator._wait_for_ocr_keywords = lambda *_args, **_kwargs: self.fail(
            "no bargain OCR without the merchant shop"
        )
        navigator.classify = lambda: ScreenState.UNKNOWN

        result = navigator.enter_q_sp6_buy_flow()

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.UNKNOWN, result.state)
        self.assertEqual(MERCHANT_PROMPT_FAILURE_MESSAGE, result.message)
        self.assertEqual([], clicks)
        self.assertEqual(
            [
                (Q_SP6_SHOP_PRIORITY_TIMEOUT, False),
                (MERCHANT_NAV_LANDMARK_TIMEOUT, True),
            ],
            shop_entry_attempts,
        )

    def test_buy_entry_returns_merchant_navigation_failure_unchanged(self):
        clicks = []
        shop_entry_attempts = []
        failure = NavigationResult(False, ScreenState.CARD_MENU, "未唯一确认剧情游戏卡1角标")
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator._enter_q_sp6_shop = lambda timeout, *, log_timeout: (
            shop_entry_attempts.append((timeout, log_timeout)) or False
        )
        navigator.go_to_trade_merchant = lambda: failure
        navigator._wait_for_ocr_keywords = lambda *_args, **_kwargs: self.fail(
            "no bargain OCR when the merchant was not reached"
        )

        self.assertIs(failure, navigator.enter_q_sp6_buy_flow())
        self.assertEqual([(Q_SP6_SHOP_PRIORITY_TIMEOUT, False)], shop_entry_attempts)
        self.assertEqual([], clicks)

    def test_buy_phase_enters_shop_then_runs_or_skips_local_favorite_rebuild(self):
        actions = []
        warnings = []
        task = SimpleNamespace(
            config={"收藏重建周期": "每周"},
            sleep=lambda seconds: actions.append(("sleep", seconds)),
            log_info=lambda message: actions.append(("log", message)),
            log_warning=warnings.append,
        )
        progress = SimpleNamespace(
            should_rebuild_favorites=lambda every_run=False: (
                actions.append(("should", every_run)) or True
            ),
            clear_favorite_cards=lambda: actions.append(("clear",)),
        )
        trader = object.__new__(Trader)
        trader.task = task
        trader.progress = progress
        trader.now_provider = lambda: datetime(2026, 7, 19, 7, 59, tzinfo=UTC_PLUS_8)
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_kw: NavigationResult(True, ScreenState.SHOP)
        )
        trader.rebuild_favorites = lambda: actions.append(("rebuild",)) or True
        trader.buy_all_favorites = lambda: actions.append(("buy-all",)) or True
        trader._wait_for_buy_all_favorites_state = lambda: (
            (1454, 1004), np.zeros((1080, 1920, 3), dtype=np.uint8)
        )

        self.assertTrue(trader.run_buy())
        self.assertEqual(
            [
                ("log", "买：按2026-07-18库存批次执行（每日08:00刷新）。"),
                ("should", False),
                ("rebuild",),
                ("buy-all",),
            ],
            actions,
        )

        actions.clear()
        warnings.clear()
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_kw: NavigationResult(
                True,
                ScreenState.MERCHANT_DIALOG,
            )
        )
        self.assertFalse(trader.run_buy())
        self.assertEqual(
            [("log", "买：按2026-07-18库存批次执行（每日08:00刷新）。")],
            actions,
        )
        self.assertIn(
            "买：砍价后状态为merchant_dialog，未确认商店页，停止购买。",
            warnings,
        )

        actions.clear()
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_kw: NavigationResult(True, ScreenState.SHOP)
        )
        task.config["收藏重建周期"] = "每周"
        progress.should_rebuild_favorites = lambda every_run=False: False
        self.assertTrue(trader.run_buy())
        self.assertEqual(
            [
                ("log", "买：按2026-07-18库存批次执行（每日08:00刷新）。"),
                ("log", "买：本周收藏已经按本地表重建，跳过收藏调整。"),
                ("buy-all",),
            ],
            actions,
        )

        actions.clear()
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_kw: NavigationResult(True, ScreenState.SHOP)
        )
        task.config["收藏重建周期"] = "永不"
        progress.should_rebuild_favorites = lambda **_kwargs: self.fail(
            "永不模式不应读取收藏重建进度"
        )
        self.assertTrue(trader.run_buy())
        self.assertEqual(
            [
                ("log", "买：按2026-07-18库存批次执行（每日08:00刷新）。"),
                ("log", "买：收藏重建周期设为永不，跳过收藏调整。"),
                ("buy-all",),
            ],
            actions,
        )

    def test_buy_phase_skips_sold_out_before_rebuilding_favorites(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        sold_out = MatchResult(0.99, (560, 230), (30, 18), pixel_score=0.99, zncc_score=0.99)
        for button_visible in (True, False):
            with self.subTest(button_visible=button_visible):
                trader = object.__new__(Trader)
                trader.task = SimpleNamespace(
                    config={"收藏重建周期": "每次"},
                    sleep=lambda *_args: None,
                    log_info=lambda *_args: None,
                    log_warning=lambda message: self.fail(message),
                )
                trader.now_provider = lambda: datetime(2026, 9, 10, 20, tzinfo=UTC_PLUS_8)
                trader.navigator = SimpleNamespace(
                    enter_q_sp6_buy_flow=lambda **_kw: NavigationResult(True, ScreenState.SHOP)
                )
                trader.rebuild_favorites = lambda: self.fail("售罄后不应切卡重建收藏")
                trader.buy_all_favorites = lambda: self.fail("售罄后不应继续购买")
                trader.vision = SimpleNamespace(
                    capture=lambda: frame,
                    ocr_boxes=lambda *_args: [
                        SimpleNamespace(
                            name="一键购买全部收藏", x=1377, y=990, width=152, height=28
                        )
                    ] if button_visible else [],
                    simplify=lambda value: value,
                    match=lambda *_args: sold_out,
                    passes=lambda *_args: True,
                )

                self.assertTrue(trader.run_buy())
                self.assertTrue(trader._buy_completed_in_current_shop)

    def _phase_task(self, statuses, actions, recovered=False):
        task = object.__new__(MapTradeTask)
        task.config = {"买": True, "卖": True, "制作料理": True}
        task.info_set = statuses.__setitem__
        task.log_info = lambda *_args: None
        task.log_warning = lambda *_args: None
        task.log_error = lambda *_args: None
        task.log_completion = lambda *_args: None
        task._save_diagnostic = lambda *_args: None
        task._recover_home_after_trade = lambda: actions.append("recover") or recovered
        return task

    def test_a_failed_buy_still_sells_from_home(self):
        # Audit #14: a failed 买 or 料理 stopped the day's 120% sale too.
        actions = []
        statuses = {}
        task = self._phase_task(statuses, actions)
        navigator = SimpleNamespace(
            return_home=lambda: actions.append("home") or NavigationResult(True, ScreenState.HOME)
        )
        phases = (
            ("买", "买", lambda: actions.append("buy") or False),
            # 料理 cooks what 买 bought today: not without it.
            ("制作料理", "制作料理", lambda: actions.append("cook") or True),
            ("卖", "卖", lambda: actions.append("sell") or True),
        )

        self.assertFalse(
            task._run_phases(navigator, phases, after_home=lambda: actions.append("left shop"))
        )
        self.assertEqual(["buy", "home", "left shop", "sell", "home"], actions)
        self.assertEqual("买", statuses["失败"])
        self.assertEqual("卖", statuses["完成"])
        self.assertEqual("制作料理", statuses["跳过"])
        self.assertEqual("跑商部分流程未完成。", statuses["状态"])

    def test_a_failed_or_broken_cooking_still_sells(self):
        def broken():
            raise RuntimeError("料理页变了")

        for cook in (lambda: False, broken):
            actions = []
            statuses = {}
            task = self._phase_task(statuses, actions)
            navigator = SimpleNamespace(
                return_home=lambda: actions.append("home")
                or NavigationResult(True, ScreenState.HOME)
            )
            phases = (
                ("买", "买", lambda: actions.append("buy") or True),
                ("制作料理", "制作料理", lambda: actions.append("cook") or cook()),
                ("卖", "卖", lambda: actions.append("sell") or True),
            )

            self.assertFalse(task._run_phases(navigator, phases))
            self.assertEqual(["buy", "cook", "home", "sell", "home"], actions)
            self.assertEqual("制作料理", statuses["失败"])
            self.assertEqual("买、卖", statuses["完成"])

    def test_later_phases_stop_when_home_is_not_reached(self):
        actions = []
        statuses = {}
        task = self._phase_task(statuses, actions, recovered=False)
        navigator = SimpleNamespace(
            return_home=lambda: actions.append("home")
            or NavigationResult(False, ScreenState.UNKNOWN, "没有安全返回路径")
        )
        phases = (
            ("买", "买", lambda: actions.append("buy") or False),
            ("卖", "卖", lambda: actions.append("sell") or True),
        )

        self.assertFalse(
            task._run_phases(navigator, phases, after_home=lambda: actions.append("left shop"))
        )
        # Tried once, not again on the way out.
        self.assertEqual(["buy", "home", "recover"], actions)
        self.assertEqual("买、返回章节主页", statuses["失败"])

    def test_trade_run_forgets_the_open_shop_after_going_home(self):
        # 买 leaves the shop open for 卖; once home, 卖 must enter it anew.
        trader = object.__new__(Trader)
        trader._buy_completed_in_current_shop = True
        task = object.__new__(MapTradeTask)
        task.config = {"启用": True}
        seen = {}

        def run_phases(_navigator, phases, after_home=None):
            seen["phases"] = [phase[0] for phase in phases]
            seen["after_home"] = after_home
            return True

        task._run_phases = run_phases
        with (
            patch("src.tasks.MapTradeTask.Vision"),
            patch("src.tasks.MapTradeTask.Navigator"),
            patch("src.tasks.MapTradeTask.ProgressStore"),
            patch("src.tasks.MapTradeTask.PhaseLedger"),
            patch("src.tasks.MapTradeTask.Trader", return_value=trader),
        ):
            self.assertTrue(task.run())
        self.assertEqual(["买", "制作料理", "卖"], seen["phases"])
        seen["after_home"]()
        self.assertFalse(trader._buy_completed_in_current_shop)
        self.assertEqual({"制作料理": "买"}, MapTradeTask.phase_needs)

    def test_successful_phases_emit_standalone_completion_notification(self):
        actions = []
        notifications = []
        task = object.__new__(MapTradeTask)
        task.config = {"买": True, "卖": False}
        task.task_log_name = "跑商"
        task.info_set = lambda *_args: None
        task.log_info = lambda message, notify=False: notifications.append(
            (message, notify)
        )
        task.log_warning = lambda *_args: None
        task.log_error = lambda *_args: None
        task._save_diagnostic = lambda *_args: None
        navigator = SimpleNamespace(
            return_home=lambda: (
                actions.append("home")
                or NavigationResult(True, ScreenState.HOME)
            )
        )
        phases = (
            ("买", "买", lambda: actions.append("buy") or True),
            ("卖", "卖", lambda: actions.append("sell") or True),
        )

        self.assertTrue(task._run_phases(navigator, phases))
        self.assertEqual(["buy", "home"], actions)
        self.assertEqual(("跑商：所有已开启流程完成。", True), notifications[-1])

    def test_return_home_exception_keeps_the_original_phase_failure(self):
        actions = []
        statuses = {}
        errors = []
        diagnostics = []
        task = object.__new__(MapTradeTask)
        task.config = {"买": True, "卖": True}
        task.info_set = statuses.__setitem__
        task.log_info = lambda *_args: None
        task.log_warning = lambda *_args: None
        task.log_error = lambda *args: errors.append(args)
        task._save_diagnostic = diagnostics.append
        task._recover_home_after_trade = lambda: actions.append("recover") or False

        def return_home():
            actions.append("home")
            raise RuntimeError("return failed")

        navigator = SimpleNamespace(return_home=return_home)
        phases = (
            ("买", "买", lambda: actions.append("buy") or False),
            ("卖", "卖", lambda: actions.append("sell") or True),
        )

        self.assertFalse(task._run_phases(navigator, phases))
        self.assertEqual(["buy", "home", "recover"], actions)
        self.assertEqual("买、返回章节主页", statuses["失败"])
        self.assertEqual(1, len(errors))
        self.assertEqual(
            ["map_trade_买_failed", "map_trade_return_home_error"],
            diagnostics,
        )

    def test_generic_recovery_home_does_not_count_as_a_failure(self):
        statuses = {}
        task = object.__new__(MapTradeTask)
        task.config = {"卖": True}
        task.info_set = statuses.__setitem__
        task.log_info = lambda *_args: None
        task.log_warning = lambda *_args: None
        task.log_completion = lambda *_args: None
        task._save_diagnostic = lambda *_args: None
        task._recover_home_after_trade = lambda: True
        navigator = SimpleNamespace(
            return_home=lambda: SimpleNamespace(success=False, message="没有安全返回路径")
        )
        phases = (("卖", "卖", lambda: True),)
        self.assertTrue(task._run_phases(navigator, phases))
        self.assertEqual("-", statuses["失败"])

    def test_buy_all_favorites_clicks_ocr_button_center_and_confirmation_point(self):
        clicks = []
        logs = []
        warnings = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda seconds: logs.append(("sleep", seconds)),
            log_info=lambda message: logs.append(("log", message)),
            log_warning=warnings.append,
        )
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        trader.vision = SimpleNamespace(
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            )
        )
        trader._wait_for_buy_all_favorites_state = lambda: ((1454, 1004), frame)
        trader._wait_for_purchase_confirmation = lambda: True
        trader._wait_purchase_dialog_closed = lambda: True

        self.assertTrue(trader.buy_all_favorites())
        self.assertEqual(
            [
                ((1454, 1004), frame.shape, 0.3),
                (*BUY_CONFIRM_POINT, 0.8),
            ],
            clicks,
        )
        self.assertEqual(
            (701 / 1920, 328 / 1080, 1219 / 1920, 753 / 1080),
            BUY_CONFIRM_DIALOG_REGION,
        )
        self.assertEqual((1045 / 1920, 697 / 1080), BUY_CONFIRM_POINT)
        self.assertEqual(30.0, BUY_CONFIRM_TIMEOUT)
        self.assertEqual([], warnings)
        self.assertEqual(
            [
                (
                    "log",
                    "买：购买确认弹窗OCR完成，等待0.8秒后点击确认。",
                ),
                ("sleep", BUY_CONFIRM_PRE_CLICK_DELAY),
                ("log", "买：已确认购买全部收藏商品。"),
            ],
            logs,
        )

    def test_buy_all_button_requires_two_consecutive_full_frame_ocr_hits(self):
        ocr_calls = []
        sleeps = []
        statuses = []
        boxes = iter(
            (
                [SimpleNamespace(name="一键购买全部收藏", x=1324, y=982, width=221, height=47)],
                [],
                [SimpleNamespace(name="-键购买全部收藏", x=1379, y=992, width=148, height=24)],
                [SimpleNamespace(name="一键购买全部收藏", x=1377, y=990, width=152, height=28)],
            )
        )
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            sleep=sleeps.append,
            log_warning=lambda *_args, **_kwargs: None,
            info_set=lambda key, value: statuses.append((key, value)),
        )
        trader.vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda captured, name: (
                ocr_calls.append((captured.shape, name)) or next(boxes)
            ),
            simplify=lambda value: value,
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )

        located = trader._wait_for_buy_all_favorites_state()

        self.assertIsNotNone(located)
        point, located_frame = located
        self.assertEqual((1453, 1004), point)
        self.assertIs(frame, located_frame)
        self.assertEqual(3, len(sleeps))
        self.assertEqual(BUY_ALL_FAVORITES_KEYWORD, "购买全部收藏")
        self.assertEqual(BUY_ALL_FAVORITES_STABLE_HITS, 2)
        self.assertTrue(all(call[0] == frame.shape for call in ocr_calls))
        self.assertEqual(
            ("一键购买全部收藏按钮 OCR稳定", "2/2"),
            statuses[-1],
        )

    def test_buy_all_favorites_prioritizes_same_frame_sold_out_over_visible_button(self):
        for sold_out_frames, should_buy in (
            ((True, True), False),
            ((False, True, True), False),
            ((True, False, True, True), False),
            ((False, True, False, False), True),
        ):
            with self.subTest(sold_out_frames=sold_out_frames):
                frames = [
                    np.full((2, 2, 3), index, dtype=np.uint8)
                    for index in range(len(sold_out_frames))
                ]
                captures = iter(frames)
                ocr_frames = []
                template_frames = []
                clicks = []
                trader = object.__new__(Trader)
                trader.task = SimpleNamespace(
                    sleep=lambda *_args: None,
                    operate_click=lambda *_args, **_kwargs: clicks.append("confirm"),
                    log_info=lambda *_args: None,
                    log_warning=lambda message: self.fail(message),
                )

                def match(frame, spec):
                    self.assertIs(spec, BUY_TO_SELL_SOLD_OUT_TEMPLATE)
                    template_frames.append(frame)
                    matched = sold_out_frames[int(frame[0, 0, 0])]
                    return MatchResult(float(matched), (0, 0), (1, 1))

                trader.vision = SimpleNamespace(
                    capture=lambda: next(captures),
                    ocr_boxes=lambda frame, _name: ocr_frames.append(frame) or [
                        SimpleNamespace(name="一键购买全部收藏", x=0, y=0, width=2, height=2)
                    ],
                    simplify=lambda value: value,
                    match=match,
                    passes=lambda result, _spec: result.score == 1.0,
                    click_client=lambda *_args, **_kwargs: clicks.append("buy"),
                )
                trader._wait_for_purchase_confirmation = lambda: True
                trader._wait_purchase_dialog_closed = lambda: True

                self.assertTrue(trader.buy_all_favorites())
                self.assertEqual(["buy", "confirm"] if should_buy else [], clicks)
                self.assertEqual(len(sold_out_frames), len(ocr_frames))
                self.assertEqual(len(ocr_frames), len(template_frames))
                for ocr_frame, template_frame in zip(ocr_frames, template_frames):
                    self.assertIs(ocr_frame, template_frame)

    def test_purchase_confirmation_requires_both_texts_in_given_region(self):
        ocr_calls = []
        warnings = []
        text = {"value": "一键购买全部收藏"}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            sleep=lambda *_args: None,
            log_warning=warnings.append,
            info_set=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda captured, name, relative_roi: (
                ocr_calls.append((captured.shape, name, relative_roi)) or text["value"]
            ),
            simplify=lambda value: value,
        )

        self.assertFalse(trader._wait_for_purchase_confirmation(timeout=0.0))
        text["value"] = "一键购买全部收藏 是否购买所有加入收藏的商品？"
        self.assertTrue(trader._wait_for_purchase_confirmation(timeout=0.0))
        self.assertEqual(
            ("一键购买全部收藏", "是否购买所有加入收藏的商品"),
            BUY_CONFIRM_KEYWORDS,
        )
        self.assertTrue(all(call[2] == BUY_CONFIRM_DIALOG_REGION for call in ocr_calls))

    def test_buy_all_favorites_stops_when_confirmation_is_missing(self):
        clicks = []
        warnings = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_info=lambda *_args, **_kwargs: None,
            log_warning=warnings.append,
        )
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        trader.vision = SimpleNamespace(
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            )
        )
        trader._wait_for_buy_all_favorites_state = lambda: ((969, 669), frame)
        trader._wait_for_purchase_confirmation = lambda: False

        self.assertFalse(trader.buy_all_favorites())
        self.assertEqual([((969, 669), frame.shape, 0.3)], clicks)
        self.assertEqual(
            ["买：点击一键购买全部收藏后，未同时识别到确认标题和询问文字。"],
            warnings,
        )

    def test_buy_home_confirmation_requires_keyword_votes_brightness_and_ocr(self):
        announcement_signals = []
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
            clear_temporary_home_announcement_if_needed=lambda **signals: (
                announcement_signals.append(signals) if not announcement_signals else None
            ),
        )
        bright_frame = np.full((1080, 1920, 3), 255, dtype=np.uint8)
        dimmed_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame = {"value": dimmed_frame}
        gacha_text = {"value": "抽抽乐"}

        def ocr_text(_frame, name, **_kwargs):
            if name == "主页左列":
                return "我的小屋 经营管理格鲁TALK 街机游戏"
            return gacha_text["value"]

        vision = SimpleNamespace(
            capture=lambda: frame["value"],
            ocr_text=ocr_text,
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertFalse(navigator._wait_for_cartridge_home(timeout=0.0))
        self.assertEqual(1, len(announcement_signals))
        self.assertEqual(3, announcement_signals[0]["left_hits"])
        self.assertEqual(0.0, announcement_signals[0]["brightness"])
        self.assertEqual("抽抽乐", announcement_signals[0]["gacha_ocr_text"])
        frame["value"] = bright_frame
        self.assertTrue(navigator._wait_for_cartridge_home(timeout=0.0))
        gacha_text["value"] = ""
        self.assertFalse(navigator._wait_for_cartridge_home(timeout=0.0))

    def test_return_home_update_notice_is_cleared_then_strictly_reconfirmed(self):
        frames = iter(("notice", "home"))
        clicks = []
        result = MatchResult(0.80, (10, 10), (20, 20), pixel_score=0.90)
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
            log_info=lambda *_args, **_kwargs: None,
            operate_click=lambda x, y, after_sleep=0: clicks.append(
                (x, y, after_sleep)
            ),
            clear_temporary_home_announcement_if_needed=lambda **_kwargs: False,
        )

        def ocr_text(frame, name, **_kwargs):
            if name == "返回主页公告":
                return "更新 抢先看 7天内不再显示 前往查看"
            if name == "主页抽抽乐" and frame == "home":
                return "抽抽乐"
            return ""

        vision = SimpleNamespace(
            capture=lambda: next(frames),
            match=lambda *_args: result,
            passes=lambda _match, _spec: False,
            template_brightness_ratio=lambda frame, *_args: (
                0.0 if frame == "notice" else 0.80
            ),
            ocr_text=ocr_text,
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        def signals(frame, clear_context=None):
            if frame == "notice":
                return False, 0, 0.0, ""
            return True, 3, 253.0, "抽抽乐"

        navigator._home_confirmation_signals = signals

        self.assertTrue(
            navigator._wait_for_cartridge_home(
                timeout=1.0,
                allow_return_announcement_cleanup=True,
            )
        )
        self.assertEqual(
            [(*HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT, 0.2)],
            clicks,
        )

    def test_return_home_notice_cleanup_requires_explicit_notice_keywords(self):
        clicks = []
        task = SimpleNamespace(
            config={},
            log_info=lambda *_args, **_kwargs: None,
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
        )
        text = {"value": "更新"}
        vision = SimpleNamespace(
            ocr_text=lambda _frame, name, relative_roi: text["value"],
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        self.assertFalse(
            navigator._clear_return_home_announcement_if_needed(
                frame,
                brightness=0.0,
            )
        )
        text["value"] = "更新 抢先看"
        self.assertTrue(
            navigator._clear_return_home_announcement_if_needed(
                frame,
                brightness=0.0,
            )
        )
        self.assertEqual([(*HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT, 0.2)], clicks)
        self.assertIn(("更新", "抢先看"), RETURN_HOME_ANNOUNCEMENT_KEYWORD_GROUPS)
        self.assertEqual(5, RETURN_HOME_ANNOUNCEMENT_MAX_CLICKS)
        self.assertEqual(
            (360 / 1920, 180 / 1080, 1560 / 1920, 900 / 1080),
            RETURN_HOME_ANNOUNCEMENT_OCR_REGION,
        )

    def test_return_home_notice_fixture_uses_expected_ocr_region_and_keywords(self):
        frame = cv2.imread(
            str(
                ROOT
                / "tests"
                / "fixtures"
                / "map_trade"
                / "home_return"
                / "update_notice.png"
            ),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(frame)
        ocr_shapes = []

        def ocr(**kwargs):
            target = kwargs["frame"]
            ocr_shapes.append(target.shape)
            self.assertGreater(int(np.count_nonzero(target)), 0)
            return [
                SimpleNamespace(name="7天内不再显示"),
                SimpleNamespace(name="更新"),
                SimpleNamespace(name="抢先看"),
                SimpleNamespace(name="前往查看"),
            ]

        task = SimpleNamespace(
            config={"跑商 OCR 阈值": 0.2},
            ocr=ocr,
            info_set=lambda *_args, **_kwargs: None,
            log_info=lambda *_args, **_kwargs: None,
            operate_click=lambda *_args, **_kwargs: None,
            sleep=lambda *_args: None,
        )
        navigator = Navigator(task, Vision(task))
        navigator.ensure_small_minimap = lambda: True

        self.assertTrue(
            navigator._clear_return_home_announcement_if_needed(
                frame,
                brightness=0.0,
            )
        )
        self.assertEqual([(720, 1200, 3)], ocr_shapes)

    def test_return_home_update_notice_clicks_at_most_three_times(self):
        clicks = []
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
            log_info=lambda *_args, **_kwargs: None,
            operate_click=lambda x, y, after_sleep=0: clicks.append(
                (x, y, after_sleep)
            ),
            clear_temporary_home_announcement_if_needed=lambda **_kwargs: False,
        )
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda *_args, **_kwargs: "更新 抢先看",
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        samples = {"count": 0}

        def signals(_frame, clear_context=None):
            samples["count"] += 1
            if samples["count"] >= 7:
                return True, 3, 253.0, "抽抽乐"
            return False, 0, 0.0, ""

        navigator._home_confirmation_signals = signals

        self.assertTrue(
            navigator._wait_for_cartridge_home(
                timeout=1.0,
                allow_return_announcement_cleanup=True,
            )
        )
        self.assertEqual(
            [(*HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT, 0.2)] * RETURN_HOME_ANNOUNCEMENT_MAX_CLICKS,
            clicks,
        )

    def test_screen_classification_only_reports_home_after_all_three_signals(self):
        task = SimpleNamespace(
            config={},
            info_set=lambda *_args, **_kwargs: None,
        )
        result = MatchResult(-1.0, (0, 0), (0, 0))
        gacha_text = {"value": ""}
        left_text = {"value": "我的小屋 格鲁TALK 街机游戏"}

        def ocr_text(_frame, name, **_kwargs):
            if name == "主页左列":
                return left_text["value"]
            return gacha_text["value"]

        vision = SimpleNamespace(
            capture=lambda: np.full((1080, 1920, 3), 255, dtype=np.uint8),
            match=lambda *_args: result,
            passes=lambda *_args: False,
            threshold_for=lambda spec: spec.threshold,
            ocr_text=ocr_text,
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertNotEqual(ScreenState.HOME, navigator.classify())
        gacha_text["value"] = "抽抽乐"
        self.assertEqual(ScreenState.HOME, navigator.classify())
        left_text["value"] = "设置 公告"
        self.assertNotEqual(ScreenState.HOME, navigator.classify())

    def test_loading_ocr_rejects_high_score_low_fidelity_sandbox_candidate(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        failed = MatchResult(-1.0, (0, 0), (0, 0))
        false_sandbox = MatchResult(
            0.98,
            (100, 100),
            (40, 40),
            pixel_score=0.34,
            zncc_score=0.20,
        )

        def match(_frame, spec):
            return false_sandbox if spec in SANDBOX_TEMPLATES else failed

        def passes(result, spec):
            return (
                result.score >= spec.threshold
                and (spec.min_pixel_score is None or result.pixel_score >= spec.min_pixel_score)
                and (spec.min_zncc_score is None or result.zncc_score >= spec.min_zncc_score)
            )

        vision = SimpleNamespace(
            match=match,
            passes=passes,
            threshold_for=lambda spec: spec.threshold,
            template_brightness_ratio=lambda *_args: 0.0,
            ocr_text=lambda _frame, name, **_kwargs: (
                "BROWN DUST II 94%" if name == "界面分类加载" else ""
            ),
            simplify=lambda value: value,
        )
        navigator = Navigator(SimpleNamespace(config={}), vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertEqual(ScreenState.LOADING, navigator.classify(frame))
        self.assertEqual(2, len(SANDBOX_TEMPLATES))
        spec = SANDBOX_TEMPLATES[0]
        self.assertEqual("image/UI_miniMap_B.png", spec.file_name)
        self.assertEqual(0.90, spec.threshold)
        self.assertEqual(0.90, spec.min_pixel_score)
        self.assertEqual(0.90, spec.min_zncc_score)
        self.assertIs(QUICK_SWITCH_TEMPLATE, SANDBOX_TEMPLATES[1])

    def test_quick_switch_button_alone_is_a_valid_sandbox_signal(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        failed = MatchResult(-1.0, (0, 0), (0, 0))
        quick_switch = MatchResult(
            0.98,
            (820, 980),
            (60, 50),
            pixel_score=0.91,
            zncc_score=0.92,
        )

        def match(_frame, spec):
            return quick_switch if spec is QUICK_SWITCH_TEMPLATE else failed

        def passes(result, spec):
            return (
                result.score >= spec.threshold
                and (spec.min_pixel_score is None or result.pixel_score >= spec.min_pixel_score)
                and (spec.min_zncc_score is None or result.zncc_score >= spec.min_zncc_score)
            )

        vision = SimpleNamespace(
            match=match,
            passes=passes,
            threshold_for=lambda spec: spec.threshold,
            template_brightness_ratio=lambda *_args: 0.0,
            ocr_text=lambda *_args, **_kwargs: "",
            simplify=lambda value: value,
        )
        navigator = Navigator(SimpleNamespace(config={}), vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertEqual(ScreenState.SANDBOX, navigator.classify(frame))

    def test_trade_classify_requires_interaction_options_and_talent_cards(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cases = (
            ("对话 商店", "天赋技能 砍价 选择", ScreenState.MERCHANT_DIALOG),
            ("对话", "天赋技能 选择", ScreenState.SANDBOX),
            ("对话 商店", "选择", ScreenState.SANDBOX),
            ("", "", ScreenState.SANDBOX),
        )
        for options, talents, expected in cases:
            with self.subTest(options=options, talents=talents):
                seen_frames = []

                def ocr(frame_arg, name, **_kwargs):
                    seen_frames.append(frame_arg)
                    return {
                        "跑商商人交互选项": options,
                        "跑商商人天赋技能": talents,
                    }.get(name, "")

                task = SimpleNamespace(config={}, info_set=lambda *_args: None)
                vision = SimpleNamespace(capture=self._fresh_frame, ocr_text=ocr,
                                         simplify=lambda value: value)
                navigator = Navigator(task, vision)
                navigator.ensure_small_minimap = lambda: True
                navigator._home_confirmation_signals = lambda _frame: (False,)
                navigator.classify = lambda _frame: ScreenState.SANDBOX
                self.assertEqual(expected, navigator.classify_trade(frame))
                self.assertTrue(all(value is frame for value in seen_frames))

    @staticmethod
    def _fresh_frame():
        return np.zeros((1080, 1920, 3), dtype=np.uint8)

    def test_trade_classify_default_argument_captures_frame(self):
        captured = self._fresh_frame()
        seen_frames = []

        def ocr(frame_arg, name, **_kwargs):
            seen_frames.append(frame_arg)
            return ""

        task = SimpleNamespace(config={}, info_set=lambda *_args: None)
        vision = SimpleNamespace(capture=lambda: captured, ocr_text=ocr,
                                 simplify=lambda value: value)
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._home_confirmation_signals = lambda _frame: (False,)
        navigator.classify = lambda _frame: ScreenState.SANDBOX
        self.assertEqual(ScreenState.SANDBOX, navigator.classify_trade())
        self.assertTrue(seen_frames)
        self.assertTrue(all(value is captured for value in seen_frames))

    def test_shared_classify_never_uses_trade_merchant_signals(self):
        task = SimpleNamespace(config={}, info_set=lambda *_args: None)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        failed = MatchResult(-1.0, (0, 0), (0, 0))
        ocr_names = []
        matched_specs = []

        def ocr(_frame, name, **_kwargs):
            ocr_names.append(name)
            return ""

        def match(_frame, spec):
            matched_specs.append(spec)
            return failed

        vision = SimpleNamespace(
            capture=lambda: frame,
            match=match,
            passes=lambda *_args: False,
            threshold_for=lambda spec: spec.threshold,
            template_brightness_ratio=lambda *_args: 0.0,
            ocr_text=ocr,
            ocr_boxes=lambda _frame, name, *_args, **_kwargs: ocr_names.append(name) or [],
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        navigator.classify(frame)

        self.assertNotIn("跑商商人交互选项", ocr_names)
        self.assertNotIn("跑商商人天赋技能", ocr_names)
        self.assertNotIn("商人互动按钮", ocr_names)
        self.assertNotIn(MAP_MERCHANT_ICON_TEMPLATE, matched_specs)

    def test_classify_shop_ocr_fallback_without_merchant_template(self):
        task = SimpleNamespace(config={}, info_set=lambda *_args: None)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        failed = MatchResult(-1.0, (0, 0), (0, 0))
        vision = SimpleNamespace(
            capture=lambda: frame,
            match=lambda *_args: failed,
            passes=lambda *_args: False,
            threshold_for=lambda spec: spec.threshold,
            template_brightness_ratio=lambda *_args: 0.0,
            ocr_text=lambda _frame, name, **_kwargs: {
                "界面分类商店页": "购买 出售",
                "界面分类商店标题": "仓库管理石怪 仓库 严加管理 天赋技能",
            }.get(name, ""),
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertEqual(ScreenState.SHOP, navigator.classify())

    def test_classify_map_mode_card_menu_and_cooking_use_scoped_signals(self):
        task = SimpleNamespace(config={}, info_set=lambda *_args: None)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        failed = MatchResult(-1.0, (0, 0), (0, 0))
        texts = {
            "界面分类加载": "",
            "界面分类商店页": "",
            "界面分类商店标题": "",
            "界面分类卡带标题": "",
            "界面分类卡带页": "",
            "界面分类料理标题": "",
            "界面分类料理材料": "",
        }
        vision = SimpleNamespace(
            capture=lambda: frame,
            match=lambda *_args: failed,
            passes=lambda *_args: False,
            threshold_for=lambda spec: spec.threshold,
            template_brightness_ratio=lambda *_args: 0.0,
            ocr_text=lambda _frame, name, **_kwargs: texts.get(name, ""),
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        map_mode = [MapPageMode.DIRECT_TELEPORT]
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(mode=map_mode[0])

        self.assertEqual(ScreenState.AREA_MAP, navigator.classify(frame))
        map_mode[0] = MapPageMode.UNKNOWN
        texts["界面分类卡带标题"] = "游戏卡珍藏集"
        self.assertEqual(ScreenState.CARD_MENU, navigator.classify(frame))
        texts["界面分类卡带标题"] = ""
        texts["界面分类料理标题"] = "料理"
        texts["界面分类料理材料"] = "所需材料"
        self.assertEqual(ScreenState.COOKING, navigator.classify(frame))

    def test_return_home_from_shop_closes_discount_shop_then_uses_home_button(self):
        actions = []
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: actions.append(("click", x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
            log_info=lambda *_args, **_kwargs: None,
        )
        vision = SimpleNamespace(
            ocr_text=lambda *_args, **_kwargs: "商店商品列表",
            click_reference=lambda x, y, after_sleep=0: actions.append(
                ("reference", x, y, after_sleep)
            ),
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator.classify = lambda: ScreenState.SHOP
        navigator._wait_for_ocr_keywords = (
            lambda keywords, timeout, name, interval=0.5, relative_roi=None, quiet=False: (
                actions.append(("ocr", keywords, timeout, name, interval, relative_roi)) or True
            )
        )
        navigator._wait_for_cartridge_home = lambda timeout, **kwargs: (
            actions.append(("home", timeout, kwargs)) or True
        )

        result = navigator.return_home()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.HOME, result.state)
        self.assertEqual(
            [
                ("reference", 82, 36, 0.0),
                (
                    "ocr",
                    DISCOUNT_SHOP_CLOSE_KEYWORDS,
                    DISCOUNT_SHOP_CLOSE_TIMEOUT,
                    "折扣商店关闭确认",
                    0.25,
                    DISCOUNT_SHOP_CLOSE_DIALOG_REGION,
                ),
                ("click", *DISCOUNT_SHOP_CLOSE_POINT, 0.8),
                ("reference", 82, 36, 0.8),
                ("click", *CHAPTER_HOME_POINT, 0.0),
                (
                    "home",
                    RETURN_HOME_TIMEOUT,
                    {"allow_return_announcement_cleanup": True},
                ),
            ],
            actions,
        )
        self.assertEqual((1045 / 1920, 639 / 1080), DISCOUNT_SHOP_CLOSE_POINT)
        self.assertEqual((1797 / 1920, 63 / 1080), CHAPTER_HOME_POINT)
        self.assertEqual(10.0, RETURN_HOME_TIMEOUT)

    def test_return_home_from_shop_stops_when_close_dialog_is_not_confirmed(self):
        actions = []
        task = SimpleNamespace(
            config={},
            operate_click=lambda *_args, **_kwargs: self.fail("未确认关闭弹窗时不得继续点击"),
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
            log_info=lambda *_args, **_kwargs: None,
        )
        vision = SimpleNamespace(
            ocr_text=lambda *_args, **_kwargs: "商店商品列表",
            click_reference=lambda x, y, after_sleep=0: actions.append((x, y, after_sleep)),
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        states = iter((ScreenState.SHOP, ScreenState.SHOP))
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator.classify = lambda: next(states)
        navigator._wait_for_ocr_keywords = lambda *_args, **_kwargs: False
        navigator.classify_trade = lambda: ScreenState.SHOP

        result = navigator._return_home_pass()

        self.assertFalse(result.success)
        self.assertEqual([(82, 36, 0.0)], actions)

    def test_return_home_closes_sale_popup_before_discount_shop(self):
        actions = []
        clock = [0.0]
        texts = iter(("姜黄 拥有54个 可购买54个 出售", "", "香草牛排 食物", "香草牛排 食物"))
        task = SimpleNamespace(
            operate_click=lambda *args, **kwargs: actions.append(("popup", args)),
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            log_info=lambda *_args, **_kwargs: None,
        )
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda *_args, **_kwargs: next(texts),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator.classify = lambda: ScreenState.SHOP
        navigator._click_shop_close_control = lambda **kwargs: actions.append(("shop",))
        navigator._wait_for_ocr_keywords = lambda *_args, **_kwargs: False
        navigator.classify_trade = lambda: ScreenState.SHOP
        with patch("src.tasks.map_trade.navigator_trade.monotonic", lambda: clock[0]):
            navigator._return_home_pass()
        self.assertEqual([("popup", SALE_CLOSE_POINT), ("shop",)], actions)
        self.assertEqual(2 * SALE_OCR_INTERVAL, clock[0])

    def test_return_home_stops_if_sale_popup_close_is_unconfirmed(self):
        for after_click in ("姜黄 拥有54个 可购买54个 出售", ""):
            with self.subTest(after_click=after_click):
                clock, clicks = [0.0], []
                task = SimpleNamespace(
                    operate_click=lambda *args, **kwargs: clicks.append(args),
                    sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
                )
                vision = SimpleNamespace(
                    capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
                    ocr_text=lambda *_args, **_kwargs: (
                        after_click if clicks else "拥有54个 可购买54个 出售"
                    ),
                )
                navigator = Navigator(task, vision)
                navigator.ensure_small_minimap = lambda: True
                navigator.classify = lambda: ScreenState.SHOP
                navigator._click_shop_close_control = lambda **kwargs: self.fail(
                    "弹窗未关不能关闭商店"
                )
                with patch("src.tasks.map_trade.navigator_trade.monotonic", lambda: clock[0]):
                    result = navigator._return_home_pass()
                self.assertFalse(result.success)
                self.assertEqual([SALE_CLOSE_POINT], clicks)

    def test_return_home_from_sandbox_clicks_home_once(self):
        actions = []
        matched_specs = []
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: actions.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_info=lambda *_args, **_kwargs: None,
        )
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            match=lambda _frame, spec: matched_specs.append(spec)
            or MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator.classify = lambda: ScreenState.SANDBOX
        navigator._wait_for_cartridge_home = lambda timeout, **kwargs: (
            actions.append(("wait_home", timeout, kwargs)) or True
        )

        result = navigator.return_home()

        self.assertTrue(result.success)
        self.assertEqual(
            [
                (*CHAPTER_HOME_POINT, 0.0),
                (
                    "wait_home",
                    RETURN_HOME_TIMEOUT,
                    {"allow_return_announcement_cleanup": True},
                ),
            ],
            actions,
        )
        self.assertGreaterEqual(len(matched_specs), len(CHAPTER_HOME_TEMPLATES))

    def test_return_home_closes_each_confirmed_map_page_before_home(self):
        cases = (
            (
                ScreenState.AREA_MAP,
                {
                    MapPageMode.DIRECT_TELEPORT,
                    MapPageMode.GENERATE_TELEPORT,
                },
            ),
            (
                ScreenState.SANDBOX_MAP,
                {MapPageMode.SANDBOX_LARGE_MAP},
            ),
        )
        for state, expected_modes in cases:
            with self.subTest(state=state):
                actions = []
                task = SimpleNamespace(
                    config={"加载页面等待秒数": 45.0},
                    operate_click=lambda x, y, after_sleep=0: actions.append(
                        ("click", x, y, after_sleep)
                    ),
                    sleep=lambda *_args: None,
                )
                vision = SimpleNamespace(
                    capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
                    match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
                    passes=lambda *_args: False,
                )
                navigator = Navigator(task, vision)
                navigator.ensure_small_minimap = lambda: True
                navigator.classify = lambda: state
                navigator._close_confirmed_map_page = (
                    lambda received_modes, **kwargs: (
                        self.assertEqual(expected_modes, received_modes)
                        or actions.append(("close", kwargs))
                        or NavigationResult(True, ScreenState.SANDBOX)
                    )
                )
                navigator._wait_for_cartridge_home = lambda timeout, **kwargs: (
                    actions.append(("home", timeout, kwargs)) or True
                )

                result = navigator.return_home()

                self.assertTrue(result.success)
                self.assertEqual(
                    [
                        ("close", {"timeout": 45.0}),
                        ("click", *CHAPTER_HOME_POINT, 0.0),
                        (
                            "home",
                            RETURN_HOME_TIMEOUT,
                            {"allow_return_announcement_cleanup": True},
                        ),
                    ],
                    actions,
                )

    def test_return_home_does_not_click_home_when_map_close_fails(self):
        task = SimpleNamespace(
            config={"加载页面等待秒数": 45.0},
            operate_click=lambda *_args, **_kwargs: self.fail(
                "failed map close must stop before home click"
            ),
            log_info=lambda *_args, **_kwargs: None,
            sleep=lambda *_args: None,
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator.classify = lambda: ScreenState.AREA_MAP
        navigator._close_confirmed_map_page = lambda *_args, **_kwargs: NavigationResult(
            False,
            ScreenState.AREA_MAP,
            "视觉模式冲突",
            map_page_mode=MapPageMode.UNKNOWN,
        )

        result = navigator.return_home()

        self.assertFalse(result.success)
        self.assertIn("关闭地图页面失败", result.message)

    def test_return_home_from_unknown_page_does_not_click(self):
        task = SimpleNamespace(
            config={},
            operate_click=lambda *_args, **_kwargs: self.fail("unknown page must not be clicked"),
            log_info=lambda *_args, **_kwargs: None,
            sleep=lambda *_args: None,
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator.classify = lambda: ScreenState.UNKNOWN

        result = navigator.return_home()

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.UNKNOWN, result.state)
        self.assertIn("未执行点击", result.message)

    def test_return_home_waits_out_loading_then_clicks_home_once(self):
        actions = []
        task = SimpleNamespace(
            config={"加载页面等待秒数": 45.0},
            operate_click=lambda x, y, after_sleep=0: actions.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_info=lambda *_args, **_kwargs: None,
        )
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator.classify = lambda: ScreenState.LOADING
        navigator.wait_state = lambda wanted, timeout: (
            actions.append((wanted, timeout)) or ScreenState.SANDBOX
        )
        navigator._wait_for_cartridge_home = lambda timeout, **kwargs: (
            actions.append(("wait_home", timeout, kwargs)) or True
        )

        result = navigator.return_home()

        self.assertTrue(result.success)
        self.assertEqual(
            [
                ({ScreenState.HOME, ScreenState.SANDBOX}, 45.0),
                (*CHAPTER_HOME_POINT, 0.0),
                (
                    "wait_home",
                    RETURN_HOME_TIMEOUT,
                    {"allow_return_announcement_cleanup": True},
                ),
            ],
            actions,
        )

    def test_buy_quick_page_requires_all_seven_labels(self):
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
        )
        text = {
            "value": (
                "最近 店长游戏卡 剧情游戏卡 角色游戏卡 "
                "战斗玩法游戏卡带 生活玩法游戏卡带"
            )
        }
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda *_args: text["value"],
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertFalse(navigator._wait_for_quick_switch_page(timeout=0.0))
        text["value"] += " 活动游戏卡"
        self.assertTrue(navigator._wait_for_quick_switch_page(timeout=0.0))

    def test_buy_story_category_requires_label_and_visual_highlight(self):
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=lambda *_args, **_kwargs: None,
        )
        text = {"value": "剧情游戏卡"}
        highlight = {"value": STORY_CATEGORY_HIGHLIGHT_MIN_RATIO - 0.01}
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda *_args: text["value"],
            simplify=lambda value: value,
            bright_neutral_ratio=lambda *_args: highlight["value"],
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertFalse(navigator._wait_for_story_category(timeout=0.0))
        highlight["value"] = STORY_CATEGORY_HIGHLIGHT_MIN_RATIO
        self.assertTrue(navigator._wait_for_story_category(timeout=0.0))

        text["value"] = "角色游戏卡"
        self.assertFalse(navigator._wait_for_story_category(timeout=0.0))

    def test_story_category_highlight_region_uses_1920_reference_ratios(self):
        self.assertEqual(
            (445 / 1920, 840 / 1080, 670 / 1920, 915 / 1080),
            STORY_CATEGORY_HIGHLIGHT_REGION,
        )

    def test_bright_neutral_ratio_detects_category_highlight(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        left, top, region = Vision._relative_roi(frame, STORY_CATEGORY_HIGHLIGHT_REGION)
        required = round(region.shape[0] * region.shape[1] * 0.06)
        width = region.shape[1]
        frame[
            top : top + required // width + 1,
            left : left + width,
        ] = (220, 220, 220)

        ratio = Vision.bright_neutral_ratio(frame, STORY_CATEGORY_HIGHLIGHT_REGION)

        self.assertGreaterEqual(ratio, STORY_CATEGORY_HIGHLIGHT_MIN_RATIO)


class ReturnHomeScreensTest(unittest.TestCase):
    """Review 2026-09-26: return_home leaves more trade screens behind."""

    def _navigator(self, states, dialog=False, merchant=False):
        actions = []
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: actions.append((x, y)),
            sleep=lambda *_args: None,
            log_info=lambda *_args, **_kwargs: None,
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        states = iter(states)
        navigator.classify = lambda: next(states)
        navigator._discount_close_dialog_shown = lambda: dialog
        navigator._merchant_menu_shown = lambda: merchant
        navigator._click_shop_close_control = lambda **kwargs: actions.append("close")
        navigator._click_chapter_home_button = lambda **kwargs: actions.append("home")
        navigator._wait_for_cartridge_home = lambda **kwargs: True
        navigator.wait_state = lambda wanted, timeout: next(states)
        return navigator, actions

    def test_merchant_menu_closes_to_the_field_then_home(self):
        navigator, actions = self._navigator(
            [ScreenState.SHOP, ScreenState.SANDBOX], merchant=True
        )
        self.assertTrue(navigator.return_home().success)
        self.assertEqual(["close", "home"], actions)

    def test_cooking_page_backs_out_to_the_field_then_home(self):
        from src.tasks.map_trade.trader_constants import COOKING_BACK_POINT

        navigator, actions = self._navigator([ScreenState.COOKING, ScreenState.SANDBOX])
        self.assertTrue(navigator.return_home().success)
        self.assertEqual([COOKING_BACK_POINT, "home"], actions)

    def test_an_open_close_dialog_is_confirmed_before_anything_else(self):
        from src.tasks.map_trade.navigator_constants import DISCOUNT_SHOP_CLOSE_POINT

        navigator, actions = self._navigator([ScreenState.SANDBOX], dialog=True)
        self.assertTrue(navigator.return_home().success)
        self.assertEqual([DISCOUNT_SHOP_CLOSE_POINT, "home"], actions)

    def test_a_failed_pass_is_retried(self):
        # Detail page → list (still cooking) → field → home: two passes.
        navigator, actions = self._navigator(
            [ScreenState.COOKING, ScreenState.COOKING, ScreenState.COOKING, ScreenState.SANDBOX]
        )
        self.assertTrue(navigator.return_home().success)
        self.assertEqual(2, actions.count(actions[0]))

    def test_an_unknown_screen_is_never_clicked_on_any_pass(self):
        navigator, actions = self._navigator([ScreenState.UNKNOWN] * 3)
        self.assertFalse(navigator.return_home().success)
        self.assertEqual([], actions)


class PlainShopForSellingTest(unittest.TestCase):
    """User 2026-09-27: bargain only to buy; selling uses the plain 商店."""

    def _navigator(self, boxes=(), clicks=None):
        task = SimpleNamespace(
            config={},
            sleep=lambda *_a: None,
            operate_click=lambda *a, **k: clicks.append(("click", a)),
            log_info=lambda *_a, **_k: None,
            log_warning=lambda *_a, **_k: None,
            info_set=lambda *_a, **_k: None,
        )
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_boxes=lambda *_a, **_k: list(boxes),
            simplify=lambda text: text,
            click_client=lambda center, _shape, after_sleep=0: clicks.append(("option", center)),
        )
        return Navigator(task, vision)

    def test_only_the_exact_shop_option_is_pressed(self):
        clicks = []
        boxes = [
            SimpleNamespace(name="砍价", x=100, y=100, width=40, height=20),
            SimpleNamespace(name="商店", x=100, y=200, width=40, height=20),
        ]
        navigator = self._navigator(boxes, clicks)
        self.assertTrue(navigator._click_plain_shop_option())
        self.assertEqual([("option", (120, 210))], clicks)

    def test_no_shop_option_means_no_click(self):
        clicks = []
        bargain = SimpleNamespace(name="砍价", x=1, y=1, width=4, height=4)
        navigator = self._navigator([bargain], clicks)
        self.assertFalse(navigator._click_plain_shop_option(timeout=0))
        self.assertEqual([], clicks)

    def test_shop_bubble_that_pops_up_late_is_still_pressed(self):
        clicks = []
        shop = SimpleNamespace(name="商店", x=100, y=200, width=40, height=20)
        reads = iter(([], [], [shop]))
        navigator = self._navigator(clicks=clicks)
        navigator.vision.ocr_boxes = lambda *_a, **_k: next(reads)
        self.assertTrue(navigator._click_plain_shop_option())
        self.assertEqual([("option", (120, 210))], clicks)

    def test_merchant_menu_read_as_unknown_is_closed_on_return(self):
        clicks = []
        navigator = self._navigator(clicks=clicks)
        navigator._discount_close_dialog_shown = lambda: False
        navigator.classify = lambda: ScreenState.UNKNOWN
        navigator._merchant_menu_shown = lambda: True
        navigator._click_shop_close_control = lambda **_k: clicks.append(("close",))
        navigator.wait_state = lambda *_a: ScreenState.HOME
        self.assertTrue(navigator._return_home_pass().success)
        self.assertEqual([("close",)], clicks)

    def test_plain_shop_closes_without_the_discount_dialog(self):
        clicks = []
        navigator = self._navigator(clicks=clicks)
        navigator._close_sale_dialog_before_return = lambda: True
        navigator._click_shop_close_control = lambda **_k: clicks.append(("close",))
        navigator._wait_for_ocr_keywords = lambda *_a, **_k: False
        navigator.classify_trade = lambda: ScreenState.MERCHANT_DIALOG
        navigator._click_chapter_home_button = lambda: clicks.append(("home",))
        navigator._wait_for_cartridge_home = lambda **_k: True
        self.assertTrue(navigator._return_home_from_discount_shop().success)
        self.assertEqual([("close",), ("close",), ("home",)], clicks)

    def test_leaving_the_plain_shop_does_not_wait_for_the_dialog(self):
        clicks = []
        navigator = self._navigator(clicks=clicks)
        navigator.shop_bargained = False
        navigator._close_sale_dialog_before_return = lambda: True
        navigator._click_shop_close_control = lambda **_k: clicks.append(("close",))
        navigator._wait_for_ocr_keywords = lambda *_a, **_k: self.fail("不应等待折扣关闭弹窗")
        navigator.classify_trade = lambda: ScreenState.MERCHANT_DIALOG
        navigator._click_chapter_home_button = lambda: clicks.append(("home",))
        navigator._wait_for_cartridge_home = lambda **_k: True
        self.assertTrue(navigator._return_home_from_discount_shop().success)

    def test_sell_phase_enters_without_bargaining(self):
        source = Path("src/tasks/map_trade/trader_sell.py").read_text(encoding="utf-8")
        self.assertIn("enter_q_sp6_buy_flow(bargain=False)", source)


class CookAfterBuyTest(unittest.TestCase):
    """User 2026-09-28: buy, then cook, then sell."""

    def _trader(self, left_ok=True):
        from src.tasks.map_trade.trader import Trader

        calls = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            config={"料理清单": []},
            log_info=lambda *a, **k: None,
            log_warning=lambda *a, **k: calls.append("warn"),
        )
        trader.navigator = SimpleNamespace(
            leave_shop_to_merchant=lambda: calls.append("leave")
            or SimpleNamespace(success=left_ok, message="x")
        )
        trader._selected_cooking_recipes = lambda: ("冰镇甜点",)
        trader._enter_cooking_list = lambda: calls.append("enter") or False
        return trader, calls

    def test_cooking_after_buy_leaves_the_shop_first(self):
        trader, calls = self._trader()
        trader._buy_completed_in_current_shop = True
        trader.run_cooking()
        self.assertEqual(["leave", "enter"], calls[:2])
        self.assertFalse(trader._buy_completed_in_current_shop)

    def test_shop_that_will_not_close_stops_cooking(self):
        trader, calls = self._trader(left_ok=False)
        trader._buy_completed_in_current_shop = True
        self.assertFalse(trader.run_cooking())
        self.assertNotIn("enter", calls)

    def test_no_buy_means_no_shop_to_leave(self):
        trader, calls = self._trader()
        trader._buy_completed_in_current_shop = False
        trader.run_cooking()
        self.assertNotIn("leave", calls)


class BargainUpgradeTest(unittest.TestCase):
    """Live 2026-09-28: a full bargain skill makes the game say 可以强化砍价了;
    the user stars it up by hand, so buying is skipped (not failed)."""

    def test_star_up_hint_skips_buying_without_recording_it(self):
        from src.tasks.map_trade.navigator_trade import BARGAIN_UPGRADE_MESSAGE
        from src.tasks.map_trade.phase_ledger import PhaseDeferred, PhaseLedger
        from src.tasks.map_trade.trader import Trader

        trader = object.__new__(Trader)
        warnings = []
        trader.task = SimpleNamespace(
            log_info=lambda *a, **k: None,
            log_warning=lambda message, **k: warnings.append((message, k)),
        )
        trader._status = lambda *a: None
        trader._current_market_time = lambda: datetime(2026, 9, 28, 10, 0, tzinfo=UTC_PLUS_8)
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda: NavigationResult(
                False, ScreenState.SANDBOX, BARGAIN_UPGRADE_MESSAGE
            )
        )
        result = trader.run_buy()
        self.assertIsInstance(result, PhaseDeferred)
        self.assertTrue(result.success)
        self.assertTrue(warnings[0][1].get("notify"))

        with TemporaryDirectory() as folder:
            ledger = PhaseLedger(Path(folder) / "phases.json")
            ledger.once("买", lambda: result)()
            self.assertFalse(ledger.done("买"))

    def test_hint_is_noticed_without_waiting_the_full_timeout(self):
        clock = [0.0]
        task = SimpleNamespace(sleep=lambda s: clock.__setitem__(0, clock[0] + s))
        navigator = Navigator(task, SimpleNamespace(capture=lambda: None))
        navigator.ensure_small_minimap = lambda: True
        said = "F 无聊收集狂大叔 可以强化砍价了喵"
        navigator._ocr_keywords_in_frame = lambda *a, **k: (False, said)
        with patch("src.tasks.map_trade.navigator_trade.monotonic", lambda: clock[0]):
            self.assertEqual("upgrade", navigator._wait_for_bargain_tip("使用砍价技能后"))
        self.assertEqual(0.0, clock[0])

