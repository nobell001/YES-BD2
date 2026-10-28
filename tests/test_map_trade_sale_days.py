import unittest
from types import SimpleNamespace

from src.tasks.map_trade.models import CalendarEntry
from src.tasks.map_trade.sale_days import (
    apply_sale_checklist,
    bundled_sale_days,
    describe_entry,
    sale_day_key,
)
from src.tasks.map_trade.trader_sell import SellFlowMixin

ALMOND = CalendarEntry("杏仁", "R1:杰登之门", reserve=5000)
MELON = CalendarEntry("哈密瓜", "R6:御剑传")


class SaleChecklistTest(unittest.TestCase):
    def test_everything_is_sold_until_the_user_saves_a_choice(self):
        keep, dropped = apply_sale_checklist({}, 19, [ALMOND, MELON], [ALMOND, MELON])
        self.assertEqual([ALMOND, MELON], keep)
        self.assertEqual([], dropped)

    def test_unticked_item_is_not_sold(self):
        config = {sale_day_key(19): ["哈密瓜"]}
        keep, dropped = apply_sale_checklist(config, 19, [ALMOND, MELON], [ALMOND, MELON])
        self.assertEqual([MELON], keep)
        self.assertEqual([ALMOND], dropped)

    def test_items_outside_the_bundled_table_cannot_be_unticked(self):
        extra = CalendarEntry("苹果", "S6:异教塔")
        config = {sale_day_key(19): []}
        keep, dropped = apply_sale_checklist(config, 19, [ALMOND, extra], [ALMOND, MELON])
        self.assertEqual([extra], keep)
        self.assertEqual([ALMOND], dropped)

    def test_bundled_days_and_labels(self):
        days = bundled_sale_days()
        self.assertEqual(set(range(1, 29)), set(days))
        self.assertEqual("杏仁→R1:杰登之门（保留5000）", describe_entry(ALMOND))
        self.assertEqual("哈密瓜→R6:御剑传", describe_entry(MELON))


class SellFlowChecklistTest(unittest.TestCase):
    def test_sell_flow_logs_the_plan_and_skips_unticked_items(self):
        logs, status = [], {}
        trader = object.__new__(SellFlowMixin)
        trader.task = SimpleNamespace(config={sale_day_key(19): ["哈密瓜"]}, log_info=logs.append)
        trader._status = status.__setitem__

        keep = trader._apply_day_checklist(19, [ALMOND, MELON])

        self.assertEqual([MELON], keep)
        self.assertIn("卖：杏仁在19号出售清单中未勾选，不卖。", logs)
        self.assertIn("卖：19号要卖：哈密瓜→R6:御剑传。", logs)
        self.assertEqual("哈密瓜→R6:御剑传", status["今日出售"])


class SaleListSearchTest(unittest.TestCase):
    def trader(self, scans, views):
        """scans: results of each on-screen search; views: list image per capture."""
        trader = object.__new__(SellFlowMixin)
        scrolls, statuses = [], []
        trader._move_sale_list = lambda direction: scrolls.append(direction) or True
        trader._status = lambda *args: statuses.append(args)
        views = iter(views)
        trader._sale_list_view = lambda: next(views)
        scans = iter(scans)

        def wait(entry, timeout=None, empty_hits=None):
            located, seen = next(scans)
            trader._last_sale_name_seen = seen
            trader._last_sale_ocr_output = True
            return located

        trader._wait_sale_item_candidates = wait
        return trader, scrolls

    def test_item_further_down_is_found_after_scrolling(self):
        import numpy as np

        top, lower = np.zeros((64, 96), np.int16), np.full((64, 96), 50, np.int16)
        found = (["card"], "frame")
        trader, scrolls = self.trader([(None, False), (found, True)], [top, lower])
        self.assertEqual(found, trader._find_sale_item_candidates(ALMOND))
        self.assertEqual([-1], scrolls)

    def test_search_stops_when_the_list_no_longer_moves(self):
        import numpy as np

        still = np.zeros((64, 96), np.int16)
        trader, scrolls = self.trader([(None, False)], [still, still])
        self.assertIsNone(trader._find_sale_item_candidates(ALMOND))
        self.assertEqual([-1], scrolls)

    def test_no_scrolling_when_the_name_is_on_screen(self):
        trader, scrolls = self.trader([(None, True)], [])
        self.assertIsNone(trader._find_sale_item_candidates(ALMOND))
        self.assertEqual([], scrolls)

    def test_shop_keeper_line_is_outside_the_item_list(self):
        frame_shape = (1080, 1920, 3)
        speech = SimpleNamespace(x=600, y=85, width=500, height=24)  # 这里好像正在收购黄金罗勒
        card_name = SimpleNamespace(x=600, y=640, width=120, height=24)
        self.assertFalse(SellFlowMixin._in_sale_item_list(speech, frame_shape))
        self.assertTrue(SellFlowMixin._in_sale_item_list(card_name, frame_shape))

    def test_traditional_ocr_glyphs_fold_to_simplified(self):
        from src.utils.chinese import to_simplified

        self.assertEqual("黄金罗勒", to_simplified("黃金罗勒"))


class SaleListDragTest(unittest.TestCase):
    def test_a_refused_drag_is_reported(self):
        import numpy as np

        trader = object.__new__(SellFlowMixin)
        statuses = []
        # drag_client refuses (game not in front) by returning False.
        trader.task = SimpleNamespace(drag_client=lambda *args, **kwargs: False)
        trader.vision = SimpleNamespace(capture=lambda: np.zeros((1080, 1920, 3), np.uint8))
        trader._status = lambda *args: statuses.append(args)
        trader._sale_drag_refused = False
        self.assertFalse(trader._move_sale_list(-1))
        self.assertTrue(trader._sale_drag_refused)

    def test_a_refused_drag_fails_the_sell_instead_of_skipping_the_item(self):
        trader = object.__new__(SellFlowMixin)
        warnings = []
        trader.task = SimpleNamespace(
            log_warning=lambda message, **kwargs: warnings.append(message),
            log_info=lambda *a, **k: None,
        )

        def refuse_top():
            trader._sale_drag_refused = True

        trader._scroll_sale_list_to_top = refuse_top
        trader._find_sale_item_candidates = lambda entry: self.fail("searched without a drag")
        entry = SimpleNamespace(item="黄金罗勒")
        self.assertFalse(trader._sell_selected_entry(entry))
        self.assertFalse(trader._last_sale_unavailable)  # a failure, not "not in shop"
        self.assertIn("不在最前面", warnings[0])

    def test_drag_direction(self):
        import numpy as np

        trader = object.__new__(SellFlowMixin)
        drags = []
        trader.task = SimpleNamespace(
            drag_client=lambda start, end, **kwargs: drags.append((start, end)) or True,
        )
        trader.vision = SimpleNamespace(capture=lambda: np.zeros((1080, 1920, 3), np.uint8))
        trader._move_sale_list(-1)
        trader._move_sale_list(1)
        (down_start, down_end), (up_start, up_end) = drags
        self.assertGreater(down_start[1], down_end[1])  # drag up = show lower items
        self.assertLess(up_start[1], up_end[1])


class SaleListTopTest(unittest.TestCase):
    def test_scrolls_up_until_the_list_stops_moving(self):
        import numpy as np

        trader = object.__new__(SellFlowMixin)
        scrolls = []
        trader._move_sale_list = lambda direction: scrolls.append(direction) or True
        # Loading restored the old offset once: the first scroll moves, the
        # second moves again, the third finds the list already at the top.
        views = iter([np.full((64, 96), v, np.int16) for v in (0, 40, 40, 80, 80, 80)])
        trader._sale_list_view = lambda: next(views)
        trader._scroll_sale_list_to_top()
        self.assertEqual(3, len(scrolls))
        self.assertTrue(all(direction > 0 for direction in scrolls))


if __name__ == "__main__":
    unittest.main()


def _dialog_trader(texts, config=None):
    """A sell mixin whose dialog OCR returns ``texts`` one read at a time."""

    import numpy as np

    trader = object.__new__(SellFlowMixin)
    clicks, warnings = [], []
    reads = iter(texts)
    last = [""]

    def ocr_text(_frame, _name, relative_roi=None):
        last[0] = next(reads, last[0])
        return last[0]

    trader.task = SimpleNamespace(
        config=config or {},
        operate_click=lambda x, y, after_sleep=0: clicks.append((x, y)),
        sleep=lambda *_a: None,
        log_info=lambda *a, **k: None,
        log_warning=lambda message, **kwargs: warnings.append(message),
        info_set=lambda *a: None,
    )
    trader.vision = SimpleNamespace(
        capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
        ocr_text=ocr_text,
        simplify=lambda value: value,
        click_client=lambda point, shape, after_sleep=0: clicks.append(("list", point)),
    )
    trader._status = lambda *a: None
    return trader, clicks, warnings


class SaleDialogGuardTest(unittest.TestCase):
    """Review 2026-09-26: clicks never land in an open dialog by accident."""

    def test_close_is_only_proven_by_two_clean_reads(self):
        from src.tasks.map_trade.trader_constants import SALE_CLOSE_POINT

        trader, clicks, _ = _dialog_trader(["拥有 400个 可购买 50", "出售 商店", "出售 商店"])
        self.assertTrue(trader._close_sale_dialog())
        self.assertEqual([SALE_CLOSE_POINT], clicks)

    def test_close_fails_while_the_dialog_stays(self):
        from unittest import mock

        trader, _, _ = _dialog_trader(["拥有 400个 可购买 50"])
        clock = iter(range(100))
        with mock.patch("src.tasks.map_trade.trader_sell.monotonic", lambda: next(clock)):
            self.assertFalse(trader._close_sale_dialog())

    def test_a_retry_click_first_closes_an_unconfirmed_dialog(self):
        import numpy as np

        trader, clicks, warnings = _dialog_trader([])
        trader._sale_name_signature = lambda *a: ()
        trader._sale_toast_id = lambda *a: None
        trader._last_sale_toast_id = None
        trader._wait_sale_dialog_item = lambda entry: False
        trader._sale_dialog_shown = lambda frame=None: True
        trader._close_sale_dialog = lambda: False  # it will not close
        result = trader._sell_one_candidate(
            CalendarEntry("白糖", "S2"),
            SimpleNamespace(center=(640, 460)),
            np.zeros((1080, 1920, 3), np.uint8),
            previous_owned=None,
        )
        self.assertIsNone(result)
        # One list click only: the second never went into the open dialog.
        self.assertEqual([("list", (640, 460))], clicks)
        self.assertIn("无法关闭", warnings[-1])

    def test_title_is_not_judged_before_the_dialog_draws(self):
        from unittest import mock

        trader, _, _ = _dialog_trader([])
        trader._sale_title_catalog = lambda entry: {}
        trader._normal = lambda value: value
        trader._sale_dialog_shown = lambda frame=None: False
        trader._sale_dialog_rejected = False
        trader._sale_dialog_title_identity = lambda *a: self.fail("judged the list behind")
        clock = iter(range(100))
        with mock.patch("src.tasks.map_trade.trader_sell.monotonic", lambda: next(clock)):
            self.assertFalse(trader._wait_sale_dialog_item(CalendarEntry("白糖", "S2"), timeout=3))
        self.assertFalse(trader._sale_dialog_rejected)

    def test_reserve_close_failure_stops_the_item(self):
        import numpy as np

        trader, clicks, _ = _dialog_trader([])
        trader._sale_name_signature = lambda *a: ()
        trader._sale_toast_id = lambda *a: None
        trader._last_sale_toast_id = None
        trader._wait_sale_dialog_item = lambda entry: True
        trader._wait_owned_quantity = lambda: 100
        trader._wait_available_quantity = lambda: 100
        trader._close_sale_dialog = lambda: False
        result = trader._sell_one_candidate(
            CalendarEntry("杏仁", "R1", reserve=5000),
            SimpleNamespace(center=(640, 460)),
            np.zeros((1080, 1920, 3), np.uint8),
            previous_owned=None,
        )
        self.assertIsNone(result)

    def test_sale_insurance_sells_once(self):
        import numpy as np

        trader, _, _ = _dialog_trader([], config={"出售保险": True})
        trader._scroll_sale_list_to_top = lambda: None
        trader._candidate_unmoved = lambda *a: True
        frame = np.zeros((1080, 1920, 3), np.uint8)
        trader._find_sale_item_candidates = lambda entry: ([SimpleNamespace(center=(1, 1))], frame)
        sales = []
        trader._sell_one_candidate = lambda *a, **k: sales.append(1) or (100 - len(sales), True)
        self.assertTrue(trader._sell_selected_entry(CalendarEntry("白糖", "S2")))
        self.assertEqual(1, len(sales))

    def test_a_card_still_moving_is_not_clicked(self):
        import numpy as np

        trader, _, warnings = _dialog_trader([])
        trader._scroll_sale_list_to_top = lambda: None
        trader._candidate_unmoved = lambda *a: False
        frame = np.zeros((1080, 1920, 3), np.uint8)
        trader._find_sale_item_candidates = lambda entry: ([SimpleNamespace(center=(1, 1))], frame)
        trader._sell_one_candidate = lambda *a, **k: self.fail("clicked a moving card")
        self.assertFalse(trader._sell_selected_entry(CalendarEntry("白糖", "S2")))
        self.assertIn("一直在变化", warnings[-1])


class CandidateStillTest(unittest.TestCase):
    def _trader(self, current):
        trader = object.__new__(SellFlowMixin)
        trader.vision = SimpleNamespace(capture=lambda: current)
        return trader

    def test_same_view_passes_and_a_shifted_list_fails(self):
        import numpy as np

        rng = np.random.default_rng(5)
        frame = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        candidate = SimpleNamespace(
            name_box=SimpleNamespace(name="白糖", x=600, y=560, width=60, height=24),
            percent_box=SimpleNamespace(x=480, y=556, width=52, height=16),
        )
        self.assertTrue(self._trader(frame.copy())._candidate_unmoved(candidate, frame))
        shifted = np.roll(frame, 40, axis=0)  # the list scrolled by 40 px
        self.assertFalse(self._trader(shifted)._candidate_unmoved(candidate, frame))


class SaleDateRolloverTest(unittest.TestCase):
    def test_selling_stops_when_the_price_day_changes(self):
        from datetime import date

        trader, _, warnings = _dialog_trader([])
        trader._sale_calendar_date = date(2026, 9, 26)
        trader._current_market_time = lambda: None
        sold = []
        trader._sell_selected_entry = lambda entry: sold.append(entry.item) or True
        trader.select_shop_tab = lambda shop: True
        trader._sell_entry_cartridge_order = lambda entry: 0
        from unittest import mock

        with mock.patch(
            "src.tasks.map_trade.trader_sell.sale_price_calendar_date",
            return_value=date(2026, 9, 27),
        ):
            self.assertTrue(trader._sell_resolved_entries([CalendarEntry("白糖", "S2")]))
        self.assertEqual([], sold)
        self.assertIn("价表已刷新", warnings[0])


class BuyConfirmCloseTest(unittest.TestCase):
    def _trader(self, closed, sold_out=False):
        import numpy as np

        from src.tasks.map_trade.trader_buy import BuyFlowMixin

        trader = object.__new__(BuyFlowMixin)
        clicks, warnings = [], []
        trader.task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y)),
            sleep=lambda *a: None,
            log_info=lambda *a, **k: None,
            log_warning=lambda message, **k: warnings.append(message),
        )
        trader.vision = SimpleNamespace(click_client=lambda *a, **k: None)
        trader._status = lambda *a: None
        frame = np.zeros((1080, 1920, 3), np.uint8)
        trader._wait_for_buy_all_favorites_state = lambda: ((1454, 1004), frame)
        trader._wait_for_purchase_confirmation = lambda *a, **k: True
        results = iter(closed)
        trader._wait_purchase_dialog_closed = lambda: next(results)
        trader._sold_out_after_buy = lambda: sold_out
        return trader, clicks, warnings

    def test_a_swallowed_confirm_is_pressed_once_more(self):
        trader, clicks, _ = self._trader([False, True])
        self.assertTrue(trader.buy_all_favorites())
        self.assertEqual(2, len(clicks))

    def test_a_dialog_that_stays_fails_the_buy_unless_sold_out_shows(self):
        trader, clicks, _ = self._trader([False, False])
        self.assertFalse(trader.buy_all_favorites())
        self.assertEqual(2, len(clicks))
        trader, _, _ = self._trader([False, False], sold_out=True)
        self.assertTrue(trader.buy_all_favorites())


def _button_presses(presses):
    """The read-button presses, without the fixed-place 确认 press."""
    return [press for press in presses if press[0] != "fixed"]


class BuyFirstPressTest(unittest.TestCase):
    """A 一键购买全部收藏 press that opened nothing (a player's 1080p run sat
    10 s on the unchanged shop and the stuck guard stopped it, 2026-10-16)."""

    def _trader(self, confirmations, *, button_again=True, dialog_partly=False, sold_out=False):
        import numpy as np

        from src.tasks.map_trade.trader_buy import BuyFlowMixin

        trader = object.__new__(BuyFlowMixin)
        presses, warnings, waits = [], [], []
        trader.task = SimpleNamespace(
            operate_click=lambda x, y, **k: presses.append(("fixed", round(x, 3), round(y, 3))),
            sleep=lambda *a: None,
            log_info=lambda *a, **k: None,
            log_warning=lambda message, **k: warnings.append(message),
        )
        trader.vision = SimpleNamespace(click_client=lambda center, *a, **k: presses.append(center))
        trader._status = lambda *a: None
        frame = np.zeros((1080, 1920, 3), np.uint8)

        def wait_button(*_a):
            waits.append(1)
            return ((1454, 1004), frame) if button_again else None

        trader._wait_for_buy_all_favorites_state = wait_button
        results = iter(confirmations)
        trader._wait_for_purchase_confirmation = lambda *a, **k: next(results)
        trader._purchase_dialog_partly_read = lambda: dialog_partly
        trader._wait_purchase_dialog_closed = lambda: True
        trader._sold_out_after_buy = lambda: sold_out
        # Stars not read (the black frame): the gray-star stop stays out
        # (tests/test_trade_buy_no_favorites.py).
        trader._nothing_favorited = lambda: None
        return trader, frame, presses, warnings, waits

    def test_the_button_read_by_run_buy_is_pressed_without_reading_again(self):
        trader, frame, presses, _, waits = self._trader([True])
        self.assertTrue(trader.buy_all_favorites(located=((1454, 1004), frame)))
        self.assertEqual([], waits)
        self.assertEqual([(1454, 1004)], _button_presses(presses))

    def test_a_press_that_opened_nothing_is_pressed_once_more(self):
        trader, frame, presses, warnings, _ = self._trader([False, True])
        self.assertTrue(trader.buy_all_favorites(located=((1454, 1004), frame)))
        self.assertEqual(2, len(_button_presses(presses)))
        self.assertEqual([], warnings)

    def test_no_dialog_after_two_presses_presses_confirm_where_it_sits(self):
        # Leo 2026-10-19 「買如果沒有成功就點固定位置 確保買到」: 确认 is pressed
        # at its place and the 售罄 labels decide.
        trader, frame, presses, _, _ = self._trader([False, False])
        self.assertFalse(trader.buy_all_favorites(located=((1454, 1004), frame)))
        self.assertEqual([(1454, 1004), (1454, 1004), ("fixed", 0.544, 0.645)], presses)
        trader, frame, _, _, _ = self._trader([False, False], sold_out=True)
        self.assertTrue(trader.buy_all_favorites(located=((1454, 1004), frame)))

    def test_an_unread_button_is_pressed_at_its_fixed_place(self):
        trader, frame, presses, _, _ = self._trader([False, True], button_again=False)
        self.assertTrue(trader.buy_all_favorites(located=((1454, 1004), frame)))
        # Read press, then 一键购买全部收藏's place, then 确认's place.
        self.assertEqual(
            [(1454, 1004), ("fixed", 0.747, 0.931), ("fixed", 0.544, 0.645)], presses
        )

    def test_a_slow_dialog_is_waited_for_not_pressed_again(self):
        trader, frame, presses, _, _ = self._trader([False, True], dialog_partly=True)
        self.assertTrue(trader.buy_all_favorites(located=((1454, 1004), frame)))
        self.assertEqual(1, len(_button_presses(presses)))


class SoldOutTest(unittest.TestCase):
    def test_a_sale_that_took_everything_ends_the_item(self):
        import numpy as np

        trader, _, _ = _dialog_trader([])
        trader._scroll_sale_list_to_top = lambda: None
        trader._candidate_unmoved = lambda *a: True
        frame = np.zeros((1080, 1920, 3), np.uint8)
        searches = []
        trader._find_sale_item_candidates = lambda entry: searches.append(1) or (
            [SimpleNamespace(center=(1, 1))], frame
        )

        def sell(*_a, **_k):
            trader._last_sale_cleared = True  # owned 1456, group 1456
            return 1456, True

        trader._sell_one_candidate = sell
        self.assertTrue(trader._sell_selected_entry(CalendarEntry("苹果", "S6")))
        self.assertEqual(1, len(searches))  # no further list search
