"""An unread ↑120% marker sells nothing for that item, so the 卖 phase is not
recorded as done today and the next run tries again (audit #18)."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.tasks.map_trade.models import CalendarEntry
from src.tasks.map_trade.phase_ledger import PhaseDeferred, PhaseLedger


def _trader(reasons):
    from src.tasks.map_trade.trader import Trader

    trader = object.__new__(Trader)
    trader.task = SimpleNamespace(
        log_warning=lambda *_a, **_k: None,
        log_info=lambda *_a, **_k: None,
        info_set=lambda *_a: None,
    )
    trader._sale_date_changed = lambda: False
    trader.select_shop_tab = lambda _shop: True

    def sell(entry):
        reason = reasons.get(entry.item)
        trader._last_sale_unavailable = reason is not None
        trader._last_sale_reason = reason or ""
        return reason is None

    trader._sell_entry_with_retry = sell
    return trader


class UnconfirmedMarkerTest(unittest.TestCase):
    def test_an_unread_marker_is_not_recorded_as_sold(self):
        trader = _trader({"苹果": "未确认↑120%标志：局部定位失败"})
        result = trader._sell_resolved_entries(
            [CalendarEntry("苹果", "S6"), CalendarEntry("白糖", "S2")]
        )
        self.assertIsInstance(result, PhaseDeferred)
        self.assertTrue(result.success)
        self.assertIn("苹果", result.message)

        with tempfile.TemporaryDirectory() as folder:
            ledger = PhaseLedger(Path(folder) / "ledger.json")
            ledger.once("卖", lambda: result)()
            self.assertFalse(ledger.done("卖"))

    def test_a_real_reason_still_counts_as_done(self):
        trader = _trader({"苹果": "商店里没有这个商品"})
        self.assertIs(True, trader._sell_resolved_entries([CalendarEntry("苹果", "S6")]))

    def test_everything_sold_counts_as_done(self):
        self.assertIs(True, _trader({})._sell_resolved_entries([CalendarEntry("苹果", "S6")]))


if __name__ == "__main__":
    unittest.main()
