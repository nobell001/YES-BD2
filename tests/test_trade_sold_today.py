"""YES-BD2 #60: a sell run again after a failure skips what was already sold
when the 价目表 does not open, and a swallowed 价目表 press is pressed again."""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.tasks.map_trade.models import CalendarEntry
from src.tasks.map_trade.sold_today import SoldToday

DAY = "2026-10-27"


class SoldTodayTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.record = SoldToday(Path(folder.name) / "sold.json")

    def test_items_are_kept_per_price_day(self):
        self.record.add(DAY, "苹果")
        self.record.add(DAY, "火圣石")
        self.assertEqual({"苹果", "火圣石"}, self.record.items(DAY))
        self.assertEqual(set(), self.record.items("2026-10-28"))

    def test_a_new_day_starts_over(self):
        self.record.add(DAY, "苹果")
        self.record.add("2026-10-28", "红酒")
        self.assertEqual({"红酒"}, self.record.items("2026-10-28"))
        self.assertEqual(set(), self.record.items(DAY))

    def test_no_file_means_nothing_sold(self):
        self.assertEqual(set(), self.record.items(DAY))


def _trader(record, owned):
    from src.tasks.map_trade.trader import Trader

    trader = object.__new__(Trader)
    logs = []
    trader.task = SimpleNamespace(log_info=logs.append, log_warning=logs.append)
    trader.vision = SimpleNamespace(simplify=lambda value: value)
    trader._status = lambda *args: None
    trader.owned_items_at_max_rate = lambda: owned
    trader._sold_today = record
    trader._sale_calendar_date = date(2026, 10, 27)
    return trader, logs


class ShopSearchTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.record = SoldToday(Path(folder.name) / "sold.json")
        self.entries = [CalendarEntry("苹果", "S6"), CalendarEntry("穿山甲鳞片", "S16")]

    def test_an_unreadable_list_skips_what_was_sold_today(self):
        self.record.add(DAY, "苹果")
        trader, logs = _trader(self.record, None)
        kept = trader._keep_owned_at_max_rate(self.entries)
        self.assertEqual(["穿山甲鳞片"], [entry.item for entry in kept])
        self.assertTrue(any("苹果今天已经卖过" in message for message in logs))

    def test_a_readable_list_still_decides(self):
        # Bought again after selling: the 价目表 shows it at 120%, so it sells.
        self.record.add(DAY, "苹果")
        trader, _logs = _trader(self.record, {"苹果"})
        kept = trader._keep_owned_at_max_rate(self.entries)
        self.assertEqual(["苹果"], [entry.item for entry in kept])

    def test_a_finished_item_is_recorded(self):
        trader, _logs = _trader(self.record, None)
        trader.select_shop_tab = lambda shop: True
        trader._sale_date_changed = lambda: False
        trader._sell_entry_with_retry = lambda entry: entry.item == "苹果"
        trader._last_sale_unavailable = False
        trader._last_sale_reason = ""
        trader._sell_resolved_entries(self.entries)
        self.assertEqual({"苹果"}, self.record.items(DAY))


class PriceListPressTest(unittest.TestCase):
    BUTTON = SimpleNamespace(name="价目表", x=1400, y=990, width=80, height=30)

    def _reader(self, button_after_press, opened_after):
        from src.tasks.map_trade.trader_price_list import PriceListMixin

        reader = object.__new__(PriceListMixin)
        clicks, logs = [], []
        reader.task = SimpleNamespace(
            operate_click=lambda *args, **kwargs: clicks.append(args),
            log_info=logs.append,
            sleep=lambda *_args: None,
        )
        reader._ref_point = lambda x, y: (x, y)
        reader._price_list_button = lambda: (
            self.BUTTON if not clicks or button_after_press else None
        )
        reader._price_list_open = lambda: len(clicks) >= opened_after
        # No real waiting: each press is looked at once.
        patcher = mock.patch(
            "src.tasks.map_trade.trader_price_list.PRICE_LIST_OPEN_SECONDS", 0.0
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return reader, clicks, logs

    def test_a_swallowed_press_is_pressed_again(self):
        reader, clicks, logs = self._reader(button_after_press=True, opened_after=2)
        self.assertTrue(reader._open_price_list())
        self.assertEqual(2, len(clicks))
        self.assertTrue(any("补按" in message for message in logs))

    def test_no_second_press_once_the_button_is_gone(self):
        reader, clicks, _logs = self._reader(button_after_press=False, opened_after=9)
        self.assertFalse(reader._open_price_list())
        self.assertEqual(1, len(clicks))


if __name__ == "__main__":
    unittest.main()
