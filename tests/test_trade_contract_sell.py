"""Selling 招募契约书 on the 1st, by 「至少能招募 N 個 5 星」 (Leo 2026-11-10).

His rule, word for word:
  每10本可以合成1本高一级的招募书…一个最高级招募书可以招募一个5星角色…
  假设用户设定3个，然后他有5本最高级招募书、30本最低级招募书，那么工具就贩卖
  2本最高级的，30本最低级的都卖掉。
  假设他有250本最低级的、3本次级的，那么工具就绝对不可以卖掉任何一本。
  然后要卖的时候，最优先留最高级的，其次次级，最低级。
and 「招募書規則千萬別搞錯了」.
"""

import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from src.tasks.map_trade.asset_keep import (
    CONTRACT_KEEP_KEY,
    CONTRACT_TIERS,
    SELL_CONTRACTS_KEY,
    ContractCounts,
    contract_plan,
    contract_recruits,
    contracts_to_keep,
)
from src.tasks.map_trade.models import KNOWN_SHOPS, CalendarEntry
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_constants import (
    SALE_CONFIRM_POINT,
    SALE_MAX_POINT,
    SALE_MINUS_ONE_POINT,
    SALE_MINUS_TEN_POINT,
    SALE_PLUS_ONE_POINT,
    SALE_PLUS_TEN_POINT,
)
from tests.test_trade_slime_sell import _dialog_trader, _slider_trader

TOP, MIDDLE, LOW = CONTRACT_TIERS
NOTE = "src.tasks.map_trade.trader_sell.run_report.add_current_note"


def _counts(top=0, middle=0, low=0):
    return {TOP: top, MIDDLE: middle, LOW: low}


class SettingTest(unittest.TestCase):
    def test_only_on_the_first_with_the_switch_on_and_a_number(self):
        on = {SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: "3"}
        self.assertEqual((3, ""), contract_recruits(on, 1))
        self.assertEqual((None, ""), contract_recruits(on, 2))
        self.assertEqual((None, ""), contract_recruits({**on, SELL_CONTRACTS_KEY: False}, 1))
        self.assertEqual((None, ""), contract_recruits({}, 1))

    def test_an_empty_box_sells_nothing_and_says_so(self):
        recruits, why = contract_recruits({SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: ""}, 1)
        self.assertIsNone(recruits)
        self.assertIn("没填", why)

    def test_zero_is_a_number(self):
        on = {SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: "0"}
        self.assertEqual((0, ""), contract_recruits(on, 1))


class PlanTest(unittest.TestCase):
    def test_leos_first_example(self):
        plan, _owned, keep = contract_plan(_counts(top=5, low=30), 3)
        self.assertEqual({TOP: (5, 3), LOW: (30, 0)}, plan)
        self.assertEqual(ContractCounts(3, 0, 0), keep)

    def test_leos_second_example_sells_not_one_book(self):
        plan, owned, keep = contract_plan(_counts(middle=3, low=250), 3)
        self.assertEqual({}, plan)
        self.assertEqual(owned, keep)

    def test_top_is_kept_first_then_middle_then_low(self):
        # 2 top + 12 middle + 500 low, keep 3: both tops, 10 middles for the
        # third recruit; 2 middles and every low book are surplus.
        plan, _owned, keep = contract_plan(_counts(2, 12, 500), 3)
        self.assertEqual(ContractCounts(2, 10, 0), keep)
        self.assertEqual({MIDDLE: (12, 10), LOW: (500, 0)}, plan)

    def test_low_books_fill_what_the_higher_tiers_lack(self):
        # 1 top + 4 middle + 100 low, keep 2: top 1, middle 4 (40), low 60.
        plan, _owned, keep = contract_plan(_counts(1, 4, 100), 2)
        self.assertEqual(ContractCounts(1, 4, 60), keep)
        self.assertEqual({LOW: (100, 60)}, plan)

    def test_exactly_enough_sells_nothing(self):
        self.assertEqual({}, contract_plan(_counts(3, 0, 0), 3)[0])
        self.assertEqual({}, contract_plan(_counts(0, 30, 0), 3)[0])
        self.assertEqual({}, contract_plan(_counts(0, 0, 300), 3)[0])

    def test_zero_sells_every_book(self):
        plan, _owned, _keep = contract_plan(_counts(2, 4, 34), 0)
        self.assertEqual({TOP: (2, 0), MIDDLE: (4, 0), LOW: (34, 0)}, plan)

    def test_what_is_kept_can_always_recruit_n(self):
        for top in range(0, 6):
            for middle in (0, 3, 9, 10, 27, 45):
                for low in (0, 7, 30, 99, 250, 1234):
                    for recruits in range(0, 7):
                        owned = ContractCounts(top, middle, low)
                        keep = contracts_to_keep(owned, recruits)
                        with self.subTest(owned=owned, recruits=recruits):
                            if owned.worth < recruits * 100:
                                self.assertEqual(owned, keep)  # nothing sold
                            else:
                                self.assertGreaterEqual(keep.worth, recruits * 100)
                            # Never more than owned, and selling again sells nothing.
                            self.assertLessEqual(keep.top, top)
                            self.assertLessEqual(keep.middle, middle)
                            self.assertLessEqual(keep.low, low)
                            self.assertEqual(keep, contracts_to_keep(keep, recruits))

    def test_a_tier_that_was_not_counted_is_never_sold_and_counts_as_none(self):
        # Really 5 top + 30 low, but the top tier was not read: the 30 low
        # books are all that is known, and they do not cover 3 -> keep all.
        plan, owned, _keep = contract_plan({LOW: 30}, 3)
        self.assertEqual({}, plan)
        self.assertEqual(0, owned.top)
        # Low not read: tops alone cover it, the surplus tops are sold, lows never.
        plan, _owned, _keep = contract_plan({TOP: 5}, 3)
        self.assertEqual({TOP: (5, 3)}, plan)


def _plan_trader(config, counts=None, fail=None):
    """A trader whose shop search is replaced: counting fills in ``counts``."""

    logs, sold = [], []
    trader = object.__new__(Trader)
    trader.task = SimpleNamespace(
        config=config,
        log_info=lambda message, **_k: logs.append(message),
        log_warning=lambda message, **_k: logs.append("!" + message),
    )
    trader._status = lambda *_a: None
    trader._sale_dialog_shown = lambda *_a: False
    trader._sale_drag_refused = False

    def search(entry):
        if trader._contract_counting is not None:
            if fail == "drag":
                trader._sale_drag_refused = True
                return False
            if counts and entry.item in counts:
                trader._contract_counting[entry.item] = counts[entry.item]
                return True
            return False
        sold.append(entry)
        return True

    trader._sell_entry_with_retry = search
    return trader, logs, sold


class EntriesTest(unittest.TestCase):
    def test_three_tiers_at_story_cartridge_one_on_the_first(self):
        trader, _logs, _sold = _plan_trader({SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: "3"})
        with mock.patch(NOTE):
            entries = trader._asset_sale_entries(1)
        self.assertEqual(list(CONTRACT_TIERS), [entry.item for entry in entries])
        for entry in entries:
            self.assertEqual(KNOWN_SHOPS["S1"], entry.shop)
            self.assertTrue(entry.asset)
        self.assertIn("最高級契約書", entries[0].aliases)

    def test_off_empty_or_another_day_gives_none(self):
        for config, day in (
            ({SELL_CONTRACTS_KEY: False, CONTRACT_KEEP_KEY: "3"}, 1),
            ({SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: ""}, 1),
            ({SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: "3"}, 10),
            ({}, 1),
        ):
            trader, _logs, _sold = _plan_trader(config)
            with self.subTest(config=config, day=day), mock.patch(NOTE):
                self.assertEqual([], trader._asset_sale_entries(day))

    def test_an_empty_box_is_said_on_the_report(self):
        trader, _logs, _sold = _plan_trader({SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: ""})
        with mock.patch(NOTE) as note:
            trader._asset_sale_entries(1)
        self.assertIn("没填", note.call_args.args[0])


class CountThenPlanTest(unittest.TestCase):
    def _entries(self, counts, recruits="3", fail=None):
        trader, logs, sold = _plan_trader(
            {SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: recruits}, counts, fail
        )
        with mock.patch(NOTE) as note:
            entries = trader._asset_sale_entries(1)
            planned = [trader._planned_contract(entry) for entry in entries]
        return planned, logs, note

    def test_leos_first_example_as_exact_keep_amounts(self):
        (top, middle, low), logs, _note = self._entries(_counts(top=5, low=30))
        self.assertEqual((3, 3, 3, 5), (top.reserve, top.keep_low, top.keep_high, top.expect_owned))
        self.assertIsNone(middle)  # none owned
        self.assertEqual((0, 0, 0, 30), (low.reserve, low.keep_low, low.keep_high, low.expect_owned))
        self.assertTrue(any("留顶级3本，卖顶级2本、普通30本" in line for line in logs))

    def test_leos_second_example_plans_no_sale_and_says_why(self):
        planned, logs, note = self._entries(_counts(middle=3, low=250))
        self.assertEqual([None, None, None], planned)
        said = note.call_args.args[0]
        self.assertIn("不够招募3个5星", said)
        self.assertIn("普通250本", said)

    def test_all_three_are_counted_before_any_decision(self):
        trader, _logs, sold = _plan_trader(
            {SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: "3"}, _counts(5, 0, 30)
        )
        counted_first = []
        search = trader._sell_entry_with_retry

        def watch(entry):
            if trader._contract_counting is not None:
                counted_first.append(entry.item)
            return search(entry)

        trader._sell_entry_with_retry = watch
        with mock.patch(NOTE):
            first = trader._asset_sale_entries(1)[0]
            trader._planned_contract(first)
        self.assertEqual(list(CONTRACT_TIERS), counted_first)
        self.assertEqual([], sold)
        self.assertIsNone(trader._contract_counting)

    def test_counting_happens_once(self):
        trader, _logs, _sold = _plan_trader(
            {SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: "3"}, _counts(5, 0, 30)
        )
        calls = []
        search = trader._sell_entry_with_retry
        trader._sell_entry_with_retry = lambda entry: calls.append(entry.item) or search(entry)
        with mock.patch(NOTE):
            for entry in trader._asset_sale_entries(1):
                trader._planned_contract(entry)
        self.assertEqual(3, len(calls))

    def test_a_list_that_cannot_be_moved_sells_nothing(self):
        planned, logs, note = self._entries(_counts(5, 0, 30), fail="drag")
        self.assertEqual([None, None, None], planned)
        self.assertIn("没能数完", note.call_args.args[0])

    def test_an_unread_tier_is_said_and_never_sold(self):
        planned, logs, _note = self._entries({TOP: 5, LOW: 30})
        self.assertIsNone(planned[1])
        self.assertTrue(any("高级招募契约书没在出售列表里读到" in line for line in logs))


class CountingDialogTest(unittest.TestCase):
    def _count(self, owned, shown_by_max=None):
        trader, state, presses, closed, warnings, (candidate, frame) = _dialog_trader(owned)
        if shown_by_max is not None:
            # MAX selects another count than the one read as owned.
            real = trader.task.operate_click

            def click(x, y, after_sleep=0):
                real(x, y, after_sleep)
                if (x, y) == SALE_MAX_POINT:
                    state["selected"] = shown_by_max

            trader.task.operate_click = click
        counted = {}
        trader._contract_counting = counted
        result = trader._sell_one_candidate(
            Trader._contract_entry(TOP), candidate, frame, previous_owned=None
        )
        return result, counted, presses, closed

    def test_counting_reads_the_dialog_and_never_presses_sell(self):
        result, counted, presses, closed = self._count(5)
        self.assertEqual((5, False), result)
        self.assertEqual({TOP: 5}, counted)
        self.assertNotIn(SALE_CONFIRM_POINT, presses)
        self.assertIn(SALE_MAX_POINT, presses)
        self.assertEqual([1], closed)

    def test_a_count_max_does_not_confirm_is_not_used(self):
        # Read as 34, but MAX selects only 4: one of them is wrong.
        result, counted, presses, closed = self._count(34, shown_by_max=4)
        self.assertEqual((34, False), result)
        self.assertEqual({}, counted)
        self.assertNotIn(SALE_CONFIRM_POINT, presses)
        self.assertEqual([1], closed)


class ExactSaleTest(unittest.TestCase):
    def _sell(self, owned, keep, expect=None, env=None):
        trader, state, presses, closed, warnings, (candidate, frame) = _dialog_trader(owned)
        entry = CalendarEntry(
            item=TOP,
            shop=KNOWN_SHOPS["S1"],
            reserve=keep,
            keep_low=keep,
            keep_high=keep,
            asset=True,
            expect_owned=owned if expect is None else expect,
        )
        with mock.patch.dict(os.environ, env or {}), mock.patch(
            "src.tasks.map_trade.trader_sell.trade_detail.note_sale"
        ):
            os.environ.pop("YES_BD2_SELL_LOOK_ONLY", None) if not env else None
            result = trader._sell_one_candidate(entry, candidate, frame, previous_owned=None)
        return trader, result, state, presses, closed, warnings

    def test_two_of_five_top_books_are_sold_exactly(self):
        trader, result, state, presses, _closed, warnings = self._sell(5, 3)
        self.assertEqual((5, True), result)
        self.assertEqual(2, state["selected"])
        self.assertEqual(1, presses.count(SALE_CONFIRM_POINT))
        self.assertEqual([], warnings)

    def test_exact_counts_at_every_size(self):
        for owned, keep in ((34, 4), (30, 0), (12, 10), (250, 60), (2500, 63), (99999, 12345)):
            with self.subTest(owned=owned, keep=keep):
                _trader, result, state, presses, _closed, warnings = self._sell(owned, keep)
                self.assertEqual((owned, True), result)
                self.assertEqual(owned - keep, state["selected"])
                self.assertEqual(1, presses.count(SALE_CONFIRM_POINT))
                self.assertEqual([], warnings)

    def test_nothing_to_sell_closes_the_dialog(self):
        _trader, result, _state, presses, closed, _warnings = self._sell(3, 3)
        self.assertEqual((3, False), result)
        self.assertNotIn(SALE_CONFIRM_POINT, presses)
        self.assertEqual([1], closed)

    def test_another_count_than_the_one_planned_from_sells_nothing(self):
        trader, result, _state, presses, closed, warnings = self._sell(6, 3, expect=5)
        self.assertIsNone(result)
        self.assertNotIn(SALE_CONFIRM_POINT, presses)
        self.assertEqual([1], closed)
        self.assertTrue(trader._last_sale_unavailable)
        self.assertTrue(any("不一样" in message for message in warnings))

    def test_look_only_never_presses_sell(self):
        _trader, result, state, presses, closed, _w = self._sell(
            5, 3, env={"YES_BD2_SELL_LOOK_ONLY": "1"}
        )
        self.assertEqual((5, False), result)
        self.assertEqual(2, state["selected"])
        self.assertNotIn(SALE_CONFIRM_POINT, presses)

    def test_a_dialog_that_shows_too_many_selected_is_not_confirmed(self):
        # Whatever went before, a selection that would leave fewer than the
        # keep amount is stopped at the last check.
        trader, state, presses, closed, warnings, (candidate, frame) = _dialog_trader(5)
        entry = CalendarEntry(
            TOP, KNOWN_SHOPS["S1"], reserve=3, keep_low=3, keep_high=3, asset=True, expect_owned=5
        )
        trader._choose_sale_quantity = lambda *_a: True  # leaves MAX (5) selected
        state["selected"] = 5
        result = trader._sell_one_candidate(entry, candidate, frame, previous_owned=None)
        self.assertIsNone(result)
        self.assertNotIn(SALE_CONFIRM_POINT, presses)
        self.assertTrue(any("会剩不到3个" in message for message in warnings))


class WholeSellRunTest(unittest.TestCase):
    """The 1st of a month from the price table to the per-tier sales."""

    def _run(self, config, counts, now=datetime(2026, 12, 1, 12)):
        events, logs, recorded = [], [], []
        trader = object.__new__(Trader)
        trader.started_at = now
        trader.calendar_client = SimpleNamespace(
            load=lambda **_kwargs: SimpleNamespace(
                source="bundled",
                entries_for=lambda _day: (CalendarEntry("黄铜块", KNOWN_SHOPS["S4"]),),
            )
        )
        trader.task = SimpleNamespace(
            config=config,
            log_info=lambda message, **_k: logs.append(message),
            log_warning=lambda message, **_k: logs.append("!" + message),
            info_set=lambda *_args: None,
        )
        trader._sold_today = SimpleNamespace(
            add=lambda _day, item: recorded.append(item), items=lambda _day: set()
        )
        trader._sale_dialog_shown = lambda *_a: False
        trader.select_shop_tab = lambda shop: events.append(("shop", shop)) or True

        def search(entry):
            if getattr(trader, "_contract_counting", None) is not None:
                events.append(("count", entry.item))
                if entry.item in counts:
                    trader._contract_counting[entry.item] = counts[entry.item]
                return True
            events.append(("sell", entry.item, entry.reserve, entry.expect_owned))
            return True

        trader._sell_selected_entry = search
        with mock.patch(NOTE) as note:
            result = trader.sell_max_price_items()
        return result, events, logs, recorded, note

    def test_count_all_three_then_sell_only_the_surplus(self):
        config = {SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: "3"}
        result, events, _logs, recorded, _note = self._run(config, _counts(top=5, low=30))
        self.assertTrue(result)
        self.assertEqual(
            [
                ("shop", KNOWN_SHOPS["S1"]),
                ("count", TOP),
                ("count", MIDDLE),
                ("count", LOW),
                ("sell", TOP, 3, 5),
                ("sell", LOW, 0, 30),
                ("shop", KNOWN_SHOPS["S4"]),
                ("sell", "黄铜块", 0, None),
            ],
            events,
        )
        self.assertEqual([TOP, LOW, "黄铜块"], recorded)

    def test_not_enough_books_sells_none_and_the_days_goods_still_sell(self):
        config = {SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: "3"}
        result, events, _logs, recorded, note = self._run(config, _counts(middle=3, low=250))
        self.assertTrue(result)
        self.assertEqual([("sell", "黄铜块", 0, None)], [e for e in events if e[0] == "sell"])
        self.assertEqual(["黄铜块"], recorded)
        self.assertTrue(any("不够招募3个5星" in call.args[0] for call in note.call_args_list))

    def test_switch_off_never_opens_a_contract_dialog(self):
        result, events, _logs, _recorded, _note = self._run({}, _counts(top=5, low=30))
        self.assertTrue(result)
        self.assertEqual(
            [("shop", KNOWN_SHOPS["S4"]), ("sell", "黄铜块", 0, None)], events
        )

    def test_any_other_day_leaves_the_books_alone(self):
        config = {SELL_CONTRACTS_KEY: True, CONTRACT_KEEP_KEY: "3"}
        result, events, _logs, _recorded, _note = self._run(
            config, _counts(top=5, low=30), now=datetime(2026, 12, 2, 12)
        )
        self.assertEqual([], [e for e in events if e[0] == "count"])
        self.assertEqual([("sell", "黄铜块", 0, None)], [e for e in events if e[0] == "sell"])


class StepButtonsTest(unittest.TestCase):
    def test_down_and_up_to_an_exact_count(self):
        for start, target in ((5, 2), (34, 30), (1, 30), (100, 141), (77, 77)):
            trader, state, clicks, _warnings = _slider_trader(1000, available=1000)
            state["selected"] = start
            with self.subTest(start=start, target=target):
                self.assertEqual(target, trader._step_to_quantity(start, target))
                self.assertEqual(target, state["selected"])

    def test_the_fewest_presses(self):
        trader, state, clicks, _warnings = _slider_trader(1000, available=1000)
        state["selected"] = 100
        trader._step_to_quantity(100, 63)  # -10 x3, − x7
        self.assertEqual(
            [SALE_MINUS_TEN_POINT[0]] * 3 + [SALE_MINUS_ONE_POINT[0]] * 7, clicks
        )
        clicks.clear()
        state["selected"] = 1
        trader._step_to_quantity(1, 23)  # +10 x2, + x2
        self.assertEqual([SALE_PLUS_TEN_POINT[0]] * 2 + [SALE_PLUS_ONE_POINT[0]] * 2, clicks)

    def test_too_far_is_left_to_the_slider(self):
        trader, state, clicks, _warnings = _slider_trader(1000, available=1000)
        state["selected"] = 900
        self.assertEqual(900, trader._step_to_quantity(900, 100))
        self.assertEqual([], clicks)

    def test_a_swallowed_press_is_made_up_for(self):
        trader, state, clicks, _warnings = _slider_trader(1000, available=1000)
        state["selected"] = 10
        real = trader.task.operate_click
        dropped = []

        def click(x, y, after_sleep=0):
            if not dropped:
                dropped.append(1)  # the first press does nothing
                return
            real(x, y, after_sleep)

        trader.task.operate_click = click
        self.assertEqual(7, trader._step_to_quantity(10, 7))


class NamesInsideOtherNamesTest(unittest.TestCase):
    def _trader(self):
        trader = object.__new__(Trader)
        trader.vision = SimpleNamespace(simplify=lambda value: value)
        trader._sale_title_catalog_cache = None
        trader._sale_title_entries = tuple(Trader._contract_entry(item) for item in CONTRACT_TIERS)
        return trader

    def test_the_top_tiers_card_is_not_the_middle_tier(self):
        # 繁中 最高級契約書 (simplified 最高级契约书) holds 高级契约书.
        trader = self._trader()
        middle = Trader._contract_entry(MIDDLE)
        self.assertTrue(trader._is_another_goods_name(middle, trader._normal("最高级契约书")))
        self.assertFalse(trader._is_another_goods_name(middle, trader._normal("高级契约书")))
        top = Trader._contract_entry(TOP)
        self.assertFalse(trader._is_another_goods_name(top, trader._normal("最高级契约书")))

    def test_a_dish_is_not_its_ingredient(self):
        trader = self._trader()
        potato = CalendarEntry("土豆", KNOWN_SHOPS["S16"])
        self.assertTrue(trader._is_another_goods_name(potato, trader._normal("土豆汤")))
        self.assertFalse(trader._is_another_goods_name(potato, trader._normal("土豆")))

    def test_an_unknown_text_is_left_to_the_other_checks(self):
        trader = self._trader()
        middle = Trader._contract_entry(MIDDLE)
        self.assertFalse(trader._is_another_goods_name(middle, trader._normal("高级契约书x")))


if __name__ == "__main__":
    unittest.main()
