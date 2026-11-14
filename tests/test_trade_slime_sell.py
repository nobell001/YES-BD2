"""卖史莱姆 (Leo 2026-11-10): an account asset, sold only when the player
switched it on AND typed how many to keep; what is left after the slider may
be 5% under to 10% over that amount.  「這個數量絕對不可以看錯」."""

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.tasks.map_trade.asset_keep import (
    SELL_SLIMES_KEY,
    SLIME_KEEP_KEYS,
    SLIMES,
    parse_keep,
    slime_sale_plan,
)
from src.tasks.map_trade.models import KNOWN_SHOPS, CalendarEntry
from src.tasks.map_trade.phase_ledger import PhaseDeferred
from src.tasks.map_trade.sold_today import SoldToday
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_constants import (
    SALE_CONFIRM_POINT,
    SALE_MAX_POINT,
    SALE_MINUS_ONE_POINT,
    SALE_MINUS_TEN_POINT,
    SALE_ONE_UNIT_POINT,
    SALE_PLUS_ONE_POINT,
    SALE_PLUS_TEN_POINT,
    SALE_SLIDER_REGION,
)

YELLOW, BLUE, RED = SLIME_KEEP_KEYS
# The dialog's − / + / -10 / +10 buttons.
STEP_BUTTONS = {
    SALE_MINUS_ONE_POINT: -1,
    SALE_PLUS_ONE_POINT: 1,
    SALE_MINUS_TEN_POINT: -10,
    SALE_PLUS_TEN_POINT: 10,
}


class KeepBoxTest(unittest.TestCase):
    def test_an_empty_box_is_not_a_number(self):
        for value in ("", "   ", None, "abc", "-5", "1.5", True, False, -3, 2.5):
            with self.subTest(value=value):
                self.assertIsNone(parse_keep(value))

    def test_what_the_player_typed(self):
        self.assertEqual(20000, parse_keep("20000"))
        self.assertEqual(20000, parse_keep(" 20,000 "))
        self.assertEqual(20000, parse_keep(20000))
        self.assertEqual(0, parse_keep("0"))  # keep none: the player said so


class SlimePlanTest(unittest.TestCase):
    def test_off_by_default_sells_nothing(self):
        config = {YELLOW: "20000", BLUE: "5000", RED: "5000"}
        self.assertEqual(([], []), slime_sale_plan(config, 10))
        self.assertEqual(([], []), slime_sale_plan({**config, SELL_SLIMES_KEY: False}, 10))

    def test_only_on_the_slime_day(self):
        config = {SELL_SLIMES_KEY: True, YELLOW: "20000"}
        for day in (1, 9, 11, 19, 31):
            with self.subTest(day=day):
                self.assertEqual(([], []), slime_sale_plan(config, day))

    def test_switched_on_with_empty_boxes_sells_nothing(self):
        # Leo: 「就算打開介面 沒有填就當不賣」.
        plan, skipped = slime_sale_plan({SELL_SLIMES_KEY: True}, 10)
        self.assertEqual([], plan)
        self.assertEqual(3, len(skipped))
        self.assertTrue(all("没填" in detail for detail in skipped))

    def test_only_the_filled_colours_are_sold(self):
        config = {SELL_SLIMES_KEY: True, YELLOW: "20000", BLUE: "", RED: "x"}
        plan, skipped = slime_sale_plan(config, 10)
        self.assertEqual([("黄色史莱姆", 20000)], plan)
        self.assertEqual(2, len(skipped))


def _plan_trader(config):
    trader = object.__new__(Trader)
    logs = []
    trader.task = SimpleNamespace(config=config, log_info=logs.append, log_warning=logs.append)
    return trader, logs


class SlimeEntriesTest(unittest.TestCase):
    def test_entries_carry_the_range_leo_allowed(self):
        trader, _logs = _plan_trader({SELL_SLIMES_KEY: True, YELLOW: "20000"})
        with mock.patch("src.tasks.map_trade.trader_sell.run_report.add_current_note"):
            entries = trader._asset_sale_entries(10)
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual("黄色史莱姆", entry.item)
        self.assertEqual(KNOWN_SHOPS["S3"], entry.shop)
        self.assertEqual((20000, 19000, 22000), (entry.reserve, entry.keep_low, entry.keep_high))
        self.assertIn("黃色史萊姆", entry.aliases)
        self.assertEqual((19000, 22000), trader._kept_range(entry))

    def test_an_unfilled_colour_is_said_on_the_report(self):
        trader, logs = _plan_trader({SELL_SLIMES_KEY: True, YELLOW: "20000"})
        with mock.patch("src.tasks.map_trade.trader_sell.run_report.add_current_note") as note:
            trader._asset_sale_entries(10)
        self.assertEqual(2, note.call_count)
        self.assertTrue(any("蓝色史莱姆（没填要留多少）" in message for message in logs))

    def test_keep_zero_sells_everything_like_an_ordinary_item(self):
        # Leo 2026-11-10 「填0代表全賣」: no reserve, so the plain MAX path.
        trader, logs = _plan_trader({SELL_SLIMES_KEY: True, RED: "0"})
        with mock.patch("src.tasks.map_trade.trader_sell.run_report.add_current_note"):
            (entry,) = trader._asset_sale_entries(10)
        self.assertEqual(("红色史莱姆", 0), (entry.item, entry.reserve))
        self.assertTrue(any("填了0，全部卖出" in message for message in logs))
        slider, state, clicks, _warnings = _slider_trader(7289, available=7289)
        self.assertTrue(slider._choose_sale_quantity(entry, 7289, 7289))
        self.assertEqual([SALE_MAX_POINT[0]], clicks)
        self.assertEqual(7289, state["selected"])

    def test_an_ordinary_reserve_keeps_its_old_range(self):
        trader, _logs = _plan_trader({})
        entry = CalendarEntry("黄油", "S2", reserve=5000)
        self.assertEqual((5000, 6000), trader._kept_range(entry))  # +20%
        # Small reserves get the fixed 300 allowance.
        self.assertEqual((1000, 1300), trader._kept_range(CalendarEntry("甜椒", "S11", reserve=1000)))


def _slider_trader(owned, shift=0.0, available=None):
    """The sale dialog: MAX and a slider that may sell more than its place says."""

    left, _top, right, _bottom = SALE_SLIDER_REGION
    state = {"selected": None}
    clicks, warnings, infos = [], [], []
    most = min(owned, available) if available else owned

    def click(x, y, after_sleep=0):
        clicks.append(x)
        if (x, y) == SALE_MAX_POINT:
            state["selected"] = most
            return
        if (x, y) in STEP_BUTTONS:
            moved = (state["selected"] or 1) + STEP_BUTTONS[(x, y)]
            state["selected"] = max(1, min(most, moved))
            return
        ratio = max(0.0, min(1.0, (x - left) / (right - left) + shift))
        state["selected"] = round(1 + (most - 1) * ratio)

    trader = object.__new__(Trader)
    trader.task = SimpleNamespace(
        config={},
        operate_click=click,
        log_info=infos.append,
        log_warning=warnings.append,
        info_set=lambda *_args: None,
        sleep=lambda *_args: None,
    )
    trader.vision = SimpleNamespace(
        capture=lambda: None,
        ocr_text=lambda *_a, **_k: f"{state['selected']}个",
    )
    return trader, state, clicks, warnings


def _slime(keep, item="黄色史莱姆"):
    key = dict(SLIMES)[item]
    trader, _logs = _plan_trader({SELL_SLIMES_KEY: True, key: str(keep)})
    with mock.patch("src.tasks.map_trade.trader_sell.run_report.add_current_note"):
        (entry,) = trader._asset_sale_entries(10)
    return entry


class SlimeSliderTest(unittest.TestCase):
    def test_leos_example_lands_inside_19000_to_22000(self):
        # 33458 yellow slimes owned (his bag 2026-11-10), keep 20000.
        for shift in (0.0, 0.04, -0.04, 0.1):
            with self.subTest(shift=shift):
                owned = 33458
                trader, state, _clicks, warnings = _slider_trader(owned, shift, available=owned)
                self.assertTrue(trader._choose_sale_quantity(_slime(20000), owned, owned))
                self.assertTrue(19000 <= owned - state["selected"] <= 22000)
                self.assertEqual([], warnings)

    def test_a_misread_owned_count_sells_nothing(self):
        # Really 3458, read as 33458 every time: MAX can only select 3458.
        trader, _state, clicks, warnings = _slider_trader(3458, available=3458)
        self.assertFalse(trader._choose_sale_quantity(_slime(20000), 33458, 3458))
        self.assertEqual([SALE_MAX_POINT[0]], clicks)
        self.assertEqual(1, len(warnings))
        self.assertIn("可能把拥有数量认错了", warnings[0])

    def test_a_slider_that_cannot_be_corrected_sells_nothing(self):
        owned = 33458
        trader, _state, _clicks, warnings = _slider_trader(owned, shift=1.0, available=owned)
        self.assertFalse(trader._choose_sale_quantity(_slime(20000), owned, owned))
        self.assertTrue(warnings)

    def test_a_slider_a_few_off_is_finished_with_the_step_buttons(self):
        # 500 owned, keep 400 (380..440 is fine): this slider always lands 45
        # too many; -10 x4 and − x5 put it exactly on the target.
        owned = 500
        trader, state, clicks, warnings = _slider_trader(owned, shift=0.09, available=owned)
        self.assertTrue(trader._choose_sale_quantity(_slime(400), owned, owned))
        self.assertTrue(380 <= owned - state["selected"] <= 440)
        self.assertEqual([], warnings)
        self.assertTrue(trader._reserve_reached)

    def test_never_fewer_than_five_percent_under(self):
        # Whatever the slider does, an accepted choice leaves at least 95%.
        for owned in (20950, 22001, 25000, 99999, 250000):
            for shift in (0.0, 0.02, -0.02):
                with self.subTest(owned=owned, shift=shift):
                    trader, state, _clicks, _warnings = _slider_trader(owned, shift, owned)
                    if trader._choose_sale_quantity(_slime(20000), owned, owned):
                        self.assertGreaterEqual(owned - state["selected"], 19000)


def _dialog_trader(owned, available=None):
    """One visible card whose dialog opens; records every press."""

    import numpy as np

    presses, warnings = [], []
    trader, state, _clicks, _warnings = _slider_trader(owned, 0.0, available or owned)
    slider_click = trader.task.operate_click

    def click(x, y, after_sleep=0):
        presses.append((x, y))
        if (x, y) == SALE_CONFIRM_POINT:
            return  # the sell button is not on the slider
        if (x, y) == SALE_ONE_UNIT_POINT:
            if not state.get("min_dead"):
                state["selected"] = 1
            return
        slider_click(x, y, after_sleep)

    trader.task.operate_click = click
    trader.task.log_warning = lambda message, **_k: warnings.append(message)
    trader.vision.click_client = lambda point, shape, after_sleep=0: presses.append(("list", point))
    trader.vision.simplify = lambda value: value
    trader._status = lambda *a: None
    trader._sale_name_signature = lambda *a: ()
    trader._sale_toast_id = lambda *a: None
    trader._last_sale_toast_id = None
    trader._unconfirmed_sale = None
    trader._wait_sale_dialog_item = lambda entry: True
    trader._wait_owned_quantity = lambda: owned
    trader._wait_available_quantity = lambda: available or owned
    closed = []
    trader._close_sale_dialog = lambda: closed.append(1) or True
    trader._wait_sale_completion = lambda *a, **k: True
    frame = np.zeros((1080, 1920, 3), np.uint8)
    candidate = SimpleNamespace(center=(640, 460))
    return trader, state, presses, closed, warnings, (candidate, frame)


class SlimeDialogTest(unittest.TestCase):
    def test_look_only_never_presses_sell(self):
        owned = 33458
        trader, state, presses, closed, warnings, (candidate, frame) = _dialog_trader(owned)
        with mock.patch.dict(os.environ, {"YES_BD2_SELL_LOOK_ONLY": "1"}):
            result = trader._sell_one_candidate(
                _slime(20000), candidate, frame, previous_owned=None
            )
        self.assertEqual((owned, False), result)
        self.assertNotIn(SALE_CONFIRM_POINT, presses)
        self.assertEqual([1], closed)
        self.assertTrue(19000 <= owned - state["selected"] <= 22000)
        self.assertEqual([], warnings)

    def test_a_real_run_presses_sell_once_inside_the_range(self):
        owned = 33458
        trader, state, presses, _closed, _warnings, (candidate, frame) = _dialog_trader(owned)
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch(
            "src.tasks.map_trade.trader_sell.trade_detail.note_sale"
        ):
            os.environ.pop("YES_BD2_SELL_LOOK_ONLY", None)
            result = trader._sell_one_candidate(
                _slime(20000), candidate, frame, previous_owned=None
            )
        self.assertEqual((owned, True), result)
        self.assertEqual(1, presses.count(SALE_CONFIRM_POINT))
        self.assertTrue(19000 <= owned - state["selected"] <= 22000)

    def test_the_one_unit_test_sells_exactly_one_once(self):
        owned = 33458
        trader, state, presses, _closed, warnings, (candidate, frame) = _dialog_trader(owned)
        completions = []
        trader._wait_sale_completion = lambda *a, **k: completions.append(k["selected"]) or True
        with mock.patch.dict(os.environ, {"YES_BD2_SELL_ONE_UNIT": "黄色史莱姆"}), mock.patch(
            "src.tasks.map_trade.trader_sell.trade_detail.note_sale"
        ):
            result = trader._sell_one_candidate(
                _slime(20000), candidate, frame, previous_owned=None
            )
        self.assertEqual((owned, True), result)
        self.assertEqual([1], completions)
        self.assertEqual(1, presses.count(SALE_CONFIRM_POINT))
        # MIN was the last press before the sell button.
        self.assertEqual(
            SALE_ONE_UNIT_POINT, presses[presses.index(SALE_CONFIRM_POINT) - 1]
        )
        self.assertTrue(trader._reserve_reached)  # never loops on the item
        self.assertFalse(trader._last_sale_cleared)
        self.assertEqual([], warnings)

    def test_the_one_unit_test_only_looks_at_every_other_item(self):
        owned = 6579
        trader, _state, presses, closed, _w, (candidate, frame) = _dialog_trader(owned)
        with mock.patch.dict(os.environ, {"YES_BD2_SELL_ONE_UNIT": "黄色史莱姆"}):
            result = trader._sell_one_candidate(
                _slime(5000, "蓝色史莱姆"), candidate, frame, previous_owned=None
            )
        self.assertEqual((owned, False), result)
        self.assertNotIn(SALE_CONFIRM_POINT, presses)
        self.assertEqual([1], closed)

    def test_the_one_unit_test_can_name_every_slime(self):
        for item in ("黄色史莱姆", "蓝色史莱姆", "红色史莱姆"):
            owned = 6579
            trader, _state, presses, _closed, _w, (candidate, frame) = _dialog_trader(owned)
            trader._wait_sale_completion = lambda *a, **k: True
            names = "黄色史莱姆,蓝色史莱姆，红色史莱姆"
            with mock.patch.dict(os.environ, {"YES_BD2_SELL_ONE_UNIT": names}), mock.patch(
                "src.tasks.map_trade.trader_sell.trade_detail.note_sale"
            ):
                result = trader._sell_one_candidate(
                    _slime(0, item), candidate, frame, previous_owned=None
                )
            self.assertEqual((owned, True), result, item)
            self.assertEqual(1, presses.count(SALE_CONFIRM_POINT))
            self.assertEqual(
                SALE_ONE_UNIT_POINT, presses[presses.index(SALE_CONFIRM_POINT) - 1]
            )

    def test_the_one_unit_test_sells_nothing_when_min_is_not_read_back(self):
        owned = 33458
        trader, state, presses, closed, warnings, (candidate, frame) = _dialog_trader(owned)
        state["min_dead"] = True  # the MIN press does nothing: the slider's amount stays
        real = trader._wait_selected_sale_quantity
        trader._wait_selected_sale_quantity = lambda expected, timeout=0: real(expected, 0)
        with mock.patch.dict(os.environ, {"YES_BD2_SELL_ONE_UNIT": "黄色史莱姆"}):
            result = trader._sell_one_candidate(
                _slime(20000), candidate, frame, previous_owned=None
            )
        self.assertIsNone(result)
        self.assertNotIn(SALE_CONFIRM_POINT, presses)
        self.assertEqual([1], closed)
        self.assertTrue(any("只卖1个的测试" in message for message in warnings))

    def test_stock_already_inside_the_range_is_left_alone(self):
        for owned in (500, 19000, 20000, 22000):
            with self.subTest(owned=owned):
                trader, _state, presses, closed, _w, (candidate, frame) = _dialog_trader(owned)
                result = trader._sell_one_candidate(
                    _slime(20000), candidate, frame, previous_owned=None
                )
                self.assertEqual((owned, False), result)
                self.assertEqual([("list", (640, 460))], presses)  # nothing in the dialog
                self.assertNotIn(SALE_CONFIRM_POINT, presses)
                self.assertEqual([1], closed)


class LookOnlyTest(unittest.TestCase):
    """The test switch stops before the 出售 press and records nothing."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.record = SoldToday(Path(folder.name) / "sold.json")

    def _trader(self):
        trader = object.__new__(Trader)
        logs = []
        trader.task = SimpleNamespace(log_info=logs.append, log_warning=logs.append)
        trader.vision = SimpleNamespace(simplify=lambda value: value)
        trader._status = lambda *args: None
        trader._sold_today = self.record
        trader._sale_calendar_date = date(2026, 11, 10)
        trader.select_shop_tab = lambda shop: True
        trader._sale_date_changed = lambda: False
        trader._sell_entry_with_retry = lambda entry: True
        trader._last_sale_unavailable = False
        trader._last_sale_reason = ""
        return trader

    def test_off_unless_the_test_shell_sets_it(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YES_BD2_SELL_LOOK_ONLY", None)
            self.assertFalse(Trader._sale_look_only())
        with mock.patch.dict(os.environ, {"YES_BD2_SELL_LOOK_ONLY": "1"}):
            self.assertTrue(Trader._sale_look_only())

    def test_a_look_only_run_is_not_recorded_as_sold(self):
        trader = self._trader()
        with mock.patch.dict(os.environ, {"YES_BD2_SELL_LOOK_ONLY": "1"}):
            result = trader._sell_resolved_entries([_slime(20000)])
        self.assertIsInstance(result, PhaseDeferred)
        self.assertEqual(set(), self.record.items("2026-11-10"))

    def test_a_real_run_is_recorded(self):
        trader = self._trader()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YES_BD2_SELL_LOOK_ONLY", None)
            result = trader._sell_resolved_entries([_slime(20000)])
        self.assertTrue(result is True)
        self.assertEqual({"黄色史莱姆"}, self.record.items("2026-11-10"))


if __name__ == "__main__":
    unittest.main()


class SaleListPositionTest(unittest.TestCase):
    """The game puts the sale list back at the top after every sale (Leo by
    hand, 2026-11-10), and the slimes sit at the end of the list: from the top
    each slime cost ~30 s.  史莱姆 / 招募契约书 start from the bottom."""

    def _trader(self, finds):
        """``finds(direction, calls)`` answers each search."""

        import numpy as np

        calls = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            config={}, sleep=lambda *_a: None, log_info=lambda *_a, **_k: None,
            log_warning=lambda *_a, **_k: None,
        )
        trader._status = lambda *_a: None
        frame = np.zeros((10, 10, 3), np.uint8)
        found = ([SimpleNamespace(center=(1, 1))], frame)

        def to_end(direction, attempts):
            calls.append("top" if direction > 0 else "bottom")

        trader._scroll_sale_list_to_end = to_end

        def search(entry, direction=-1, settled=False):
            self.assertEqual(direction > 0, settled)  # after the drags it has stopped
            calls.append("up" if direction > 0 else "down")
            return found if finds(direction, calls) else None

        trader._find_sale_item_candidates = search
        trader._candidate_unmoved = lambda *_a: True
        trader._sell_one_candidate = lambda entry, *_a, **_k: (100, False)
        return trader, calls

    def test_a_slime_starts_at_the_bottom_and_looks_upward(self):
        trader, calls = self._trader(lambda direction, _calls: True)
        self.assertTrue(trader._sell_selected_entry(_slime(20000)))
        self.assertEqual(["bottom", "up"], calls)

    def test_a_contract_starts_at_the_bottom_too(self):
        trader, calls = self._trader(lambda direction, _calls: True)
        entry = CalendarEntry("顶级招募契约书", "S1", reserve=1, asset=True)
        self.assertTrue(trader._sell_selected_entry(entry))
        self.assertEqual(["bottom", "up"], calls)

    def test_normal_goods_still_start_at_the_top(self):
        trader, calls = self._trader(lambda direction, _calls: True)
        self.assertTrue(trader._sell_selected_entry(CalendarEntry("苹果", "S6")))
        self.assertEqual(["top", "down"], calls)

    def test_not_found_from_the_bottom_searches_from_the_top_as_before(self):
        trader, calls = self._trader(lambda direction, _calls: direction < 0)
        self.assertTrue(trader._sell_selected_entry(_slime(0, "红色史莱姆")))
        self.assertEqual(["bottom", "up", "top", "down"], calls)

    def test_a_name_seen_without_120_is_not_searched_again(self):
        trader, calls = self._trader(lambda direction, _calls: False)
        trader._last_sale_name_seen = True
        self.assertFalse(trader._sell_selected_entry(_slime(0, "红色史莱姆")))
        self.assertEqual(["bottom", "up"], calls)

    def test_after_a_sale_the_slime_goes_back_to_the_bottom(self):
        trader, calls = self._trader(lambda direction, _calls: True)
        sales = iter([(500, True), (400, False)])
        trader._sell_one_candidate = lambda entry, *_a, **_k: next(sales)
        trader._reserve_reached = False
        trader._last_sale_cleared = False
        self.assertTrue(trader._sell_selected_entry(_slime(20000)))
        self.assertEqual(["bottom", "up", "bottom", "up"], calls)


    def test_a_slime_done_by_its_sale_is_not_dragged_to_the_bottom_again(self):
        # Live 2026-11-10: 9-13 s of drags ran after the last sale of each slime.
        trader, calls = self._trader(lambda direction, _calls: True)
        trader._sell_one_candidate = lambda entry, *_a, **_k: (500, True)
        trader._reserve_reached = True
        self.assertTrue(trader._sell_selected_entry(_slime(20000)))
        self.assertEqual(["bottom", "up"], calls)

class ScrollToEndTest(unittest.TestCase):
    def _trader(self, views):
        import numpy as np

        trader = object.__new__(Trader)
        moves = []
        frames = iter(views)
        trader._sale_list_view = lambda: np.full((4, 4), next(frames), np.int16)
        trader._move_sale_list = lambda direction: moves.append(direction) or True
        return trader, moves

    def test_drags_down_until_the_list_stops(self):
        trader, moves = self._trader([0, 50, 50, 90, 90, 90])
        trader._scroll_sale_list_to_end(-1, 15)
        self.assertEqual([-1, -1, -1], moves)

    def test_to_top_drags_up(self):
        trader, moves = self._trader([0, 0])
        trader._scroll_sale_list_to_top()
        self.assertEqual([1], moves)
