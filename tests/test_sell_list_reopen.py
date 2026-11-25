"""跑商出售：清单只显示「食物」时，切别的卡带再切回来重找一次。

Player via Leo 2026-11-24: the first time a cartridge's sell list opened it
sometimes showed only 食物, without 料理食材 and the rest; the tool took the
item as not owned and skipped it.  Clicking another cartridge and back showed
the full list.  The fix screens no new words (cartridges are found by picture
in both the 繁中 and 简中 clients), so one set of tests covers both.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from src.tasks.map_trade.calendar import CalendarEntry
from src.tasks.map_trade.trader import Trader


def _detection(y: int):
    return SimpleNamespace(best=SimpleNamespace(result=SimpleNamespace(center=(300, y))))


def _seller(scans, *, name_seen=False, as_read=False):
    """A seller whose list reads answer from ``scans`` (None = not found).

    ``as_read``: the flags as _locate_sale_items leaves them after a real
    read of a list without the name (text read, item marked unavailable).
    """

    trader = object.__new__(Trader)
    logs, warnings, events = [], [], []
    trader.task = SimpleNamespace(
        config={},
        sleep=lambda *_args: None,
        log_info=logs.append,
        log_warning=lambda message, **_kw: warnings.append(message),
        info_set=lambda *_args: None,
    )
    trader._start_sale_search = lambda _entry: events.append("start") or -1
    trader._candidate_unmoved = lambda _candidate, _frame: True

    def find(_entry, direction=-1, settled=False):
        located = scans.pop(0)
        trader._last_sale_name_seen = name_seen if located is None else True
        trader._last_sale_reason = "未发现商品名" if located is None else ""
        trader._last_sale_page_empty = located is None
        if as_read:
            trader._last_sale_ocr_output = True
            trader._last_sale_unavailable = located is None and not name_seen
            if located is None:
                trader._last_sale_reason = "全画面OCR未形成可用商品候选"
        return located

    trader._find_sale_item_candidates = find

    def sell_one(_entry, _candidate, _frame, *, previous_owned):
        events.append("sold")
        trader._last_sale_cleared = True
        return 5, True

    trader._sell_one_candidate = sell_one
    return trader, logs, warnings, events


class SellListReopenTest(unittest.TestCase):
    def test_item_missing_on_first_open_is_sold_after_switching_cartridge_and_back(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        candidate = SimpleNamespace(center=(620, 572))
        trader, _logs, _warnings, events = _seller([None, ([candidate], frame)])
        reopens = []
        trader._reopen_sale_cartridge = lambda entry: reopens.append(entry.item) or True

        sold = trader._sell_selected_entry(CalendarEntry("番茄", "S12:海边天使"))

        self.assertTrue(sold)
        self.assertEqual(["番茄"], reopens)
        # Searched again from the start of the list after the re-open.
        self.assertEqual(["start", "start", "sold"], events)

    def test_reopen_runs_after_a_real_list_read_without_the_name(self):
        """v0.4.16 shipped the re-open behind 「not unavailable」, but a read
        without the name is exactly what marks the item unavailable: after a
        real read it never ran (found 2026-11-25)."""

        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        candidate = SimpleNamespace(center=(620, 572))
        trader, _logs, _warnings, events = _seller(
            [None, ([candidate], frame)], as_read=True
        )
        reopens = []
        trader._reopen_sale_cartridge = lambda entry: reopens.append(entry.item) or True

        self.assertTrue(trader._sell_selected_entry(CalendarEntry("番茄", "S12:海边天使")))
        self.assertEqual(["番茄"], reopens)
        self.assertEqual(["start", "start", "sold"], events)

    def test_real_read_still_missing_after_the_reopen_says_it_was_reopened(self):
        trader, _logs, _warnings, _events = _seller([None, None], as_read=True)

        def reopen(_entry):
            if getattr(trader, "_sale_cartridge_reopened", False):
                return False
            trader._sale_cartridge_reopened = True
            return True

        trader._reopen_sale_cartridge = reopen

        self.assertFalse(trader._sell_selected_entry(CalendarEntry("番茄", "S12:海边天使")))
        self.assertTrue(trader._last_sale_unavailable)
        self.assertIn("已切别的卡带再切回来重找过", trader._last_sale_reason)

    def test_item_still_missing_after_the_reopen_is_skipped_with_the_reason(self):
        trader, _logs, _warnings, events = _seller([None, None])
        reopens = []

        def reopen(entry):
            if trader._sale_cartridge_reopened:
                return False
            trader._sale_cartridge_reopened = True
            reopens.append(entry.item)
            return True

        trader._reopen_sale_cartridge = reopen

        sold = trader._sell_selected_entry(CalendarEntry("番茄", "S12:海边天使"))

        self.assertFalse(sold)
        self.assertEqual(["番茄"], reopens)
        self.assertTrue(trader._last_sale_unavailable)
        self.assertIn("已切别的卡带再切回来重找过", trader._last_sale_reason)
        self.assertNotIn("sold", events)

    def test_name_seen_without_marker_does_not_reopen(self):
        """The list is there, the ↑120% check failed: re-opening would not help."""

        trader, _logs, _warnings, _events = _seller([None], name_seen=True)
        trader._reopen_sale_cartridge = lambda _entry: self.fail("不该切卡带")

        self.assertFalse(trader._sell_selected_entry(CalendarEntry("番茄", "S12:海边天使")))
        self.assertTrue(trader._last_sale_unavailable)

    def _reopen_trader(self, select_answers, *, tab_answer=True):
        trader = object.__new__(Trader)
        logs, warnings, clicks, tabs = [], [], [], []
        trader.task = SimpleNamespace(
            log_info=logs.append,
            log_warning=lambda message, **_kw: warnings.append(message),
            info_set=lambda *_args: None,
        )
        trader.vision = SimpleNamespace(capture=lambda: np.zeros((1080, 1920, 3), np.uint8))
        # S12 at y=500; S11 just above it, S3 far up the list.
        trader._confirmed_shop_cartridge_detections = lambda _frame: {
            "S3": _detection(150),
            "S11": _detection(400),
            "S12": _detection(500),
        }
        answers = list(select_answers)
        trader._select_purchase_cartridge = lambda shop_id: (
            clicks.append(shop_id) or (answers.pop(0) if answers else True)
        )
        trader.select_shop_tab = lambda shop: tabs.append(shop) or tab_answer
        trader._sell_cartridge_page = 2
        return trader, warnings, clicks, tabs

    def test_reopen_clicks_the_nearest_other_cartridge_then_this_one_once_per_visit(self):
        trader, _warnings, clicks, tabs = self._reopen_trader([True, True])
        entry = CalendarEntry("番茄", "S12:海边天使")

        self.assertTrue(trader._reopen_sale_cartridge(entry))
        self.assertEqual(["S11", "S12"], clicks)
        self.assertEqual([], tabs)
        self.assertEqual(2, trader._sell_cartridge_page)  # a click does not move the list
        # Once per cartridge visit: a second missing item is really missing.
        self.assertFalse(trader._reopen_sale_cartridge(entry))
        self.assertEqual(["S11", "S12"], clicks)

    def test_reopen_without_another_cartridge_on_screen_does_nothing(self):
        trader, _warnings, clicks, _tabs = self._reopen_trader([])
        trader._confirmed_shop_cartridge_detections = lambda _frame: {"S12": _detection(500)}

        self.assertFalse(trader._reopen_sale_cartridge(CalendarEntry("番茄", "S12:海边天使")))
        self.assertEqual([], clicks)

    def test_reopen_whose_first_click_failed_keeps_the_old_answer(self):
        trader, _warnings, clicks, _tabs = self._reopen_trader([False])

        self.assertFalse(trader._reopen_sale_cartridge(CalendarEntry("番茄", "S12:海边天使")))
        self.assertEqual(["S11"], clicks)
        self.assertFalse(trader._sale_cartridge_lost)

    def test_reopen_that_cannot_come_back_finds_the_cartridge_from_the_list_top(self):
        trader, _warnings, clicks, tabs = self._reopen_trader([True, False])

        self.assertTrue(trader._reopen_sale_cartridge(CalendarEntry("番茄", "S12:海边天使")))
        self.assertEqual(["S11", "S12"], clicks)
        self.assertEqual(["S12:海边天使"], tabs)
        self.assertIsNone(trader._sell_cartridge_page)

    def test_lost_cartridge_skips_the_item_and_the_next_item_selects_again(self):
        trader, warnings, _clicks, tabs = self._reopen_trader([True, False], tab_answer=False)
        entry = CalendarEntry("番茄", "S12:海边天使")

        self.assertFalse(trader._reopen_sale_cartridge(entry))
        self.assertTrue(trader._sale_cartridge_lost)
        self.assertTrue(trader._last_sale_unavailable)
        self.assertTrue(any("没切回" in message for message in warnings))

        # In the sell loop: the next item of the same shop picks its cartridge again.
        seller = object.__new__(Trader)
        picked, sold = [], []
        seller.task = SimpleNamespace(
            config={},
            log_info=lambda *_args: None,
            log_warning=lambda *_args, **_kw: None,
            info_set=lambda *_args: None,
        )
        seller.select_shop_tab = lambda shop: picked.append(shop) or True
        seller._sale_date_changed = lambda: False

        def sell(item_entry):
            if item_entry.item == "番茄":
                seller._sale_cartridge_lost = True
                seller._last_sale_unavailable = True
                seller._last_sale_reason = "切换卡带重新载入清单后没切回本卡带"
                return False
            sold.append(item_entry.item)
            return True

        seller._sell_selected_entry = sell
        result = seller._sell_resolved_entries(
            [entry, CalendarEntry("小麦", "S12:海边天使")]
        )

        self.assertIs(True, result)
        self.assertEqual(["小麦"], sold)
        self.assertEqual(["S12:海边天使", "S12:海边天使"], picked)
        self.assertEqual([], tabs[1:])

    def test_each_cartridge_visit_may_reopen_once(self):
        seller = object.__new__(Trader)
        seen = []
        seller.task = SimpleNamespace(
            config={},
            log_info=lambda *_args: None,
            log_warning=lambda *_args, **_kw: None,
            info_set=lambda *_args: None,
        )
        seller.select_shop_tab = lambda _shop: True
        seller._sale_date_changed = lambda: False

        def sell(item_entry):
            seen.append((item_entry.item, seller._sale_cartridge_reopened))
            seller._sale_cartridge_reopened = True
            return True

        seller._sell_selected_entry = sell
        seller._sell_resolved_entries(
            [
                CalendarEntry("番茄", "S11:圣诞夜"),
                CalendarEntry("土豆", "S11:圣诞夜"),
                CalendarEntry("小麦", "S12:海边天使"),
            ]
        )

        self.assertEqual([("番茄", False), ("土豆", True), ("小麦", False)], seen)


if __name__ == "__main__":
    unittest.main()
