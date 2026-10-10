"""Trade phases run once per period, so a retry never cooks or buys twice."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.tasks.map_trade.phase_ledger import PhaseLedger
from src.tasks.map_trade.progress import UTC_PLUS_8


class PhaseLedgerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = [datetime(2026, 9, 26, 16, 0, tzinfo=UTC_PLUS_8)]
        self.ledger = PhaseLedger(
            Path(self.folder.name) / "phases.json", now_provider=lambda: self.now[0]
        )
        self.calls = []

    def _phase(self, name, ok=True):
        return self.ledger.once(name, lambda: self.calls.append(name) or ok)

    def test_retry_after_a_failed_sell_only_sells(self):
        self._phase("制作料理")()
        self._phase("买")()
        self._phase("卖", ok=False)()
        self.calls.clear()
        self.now[0] = datetime(2026, 9, 26, 16, 30, tzinfo=UTC_PLUS_8)  # the retry
        for name in ("制作料理", "买", "卖"):
            self.assertTrue(getattr(self._phase(name)(), "success", True))
        self.assertEqual(["卖"], self.calls)

    def test_a_manual_run_redoes_done_phases(self):
        self._phase("制作料理")()
        self.calls.clear()
        self.ledger.once("制作料理", lambda: self.calls.append("again") or True, skip_done=False)()
        self.assertEqual(["again"], self.calls)

    def test_cooking_and_buying_come_back_after_the_08_00_restock(self):
        self._phase("制作料理")()
        self.now[0] = datetime(2026, 9, 27, 8, 5, tzinfo=UTC_PLUS_8)
        self.calls.clear()
        self._phase("制作料理")()
        self.assertEqual(["制作料理"], self.calls)

    def test_selling_comes_back_after_the_23_00_price_change(self):
        self._phase("买")()
        self._phase("卖")()
        self.now[0] = datetime(2026, 9, 26, 23, 5, tzinfo=UTC_PLUS_8)  # same game day
        self.calls.clear()
        self._phase("卖")()
        self._phase("买")()  # still the same 08:00 day: skipped
        self.assertEqual(["卖"], self.calls)

    def _phase_ending_at(self, name, end):
        def action():
            self.calls.append(name)
            self.now[0] = end  # the clock moves on while the phase runs
            return True

        return self.ledger.once(name, action)

    def test_a_sell_that_crosses_23_00_leaves_the_next_days_sale_to_do(self):
        self.now[0] = datetime(2026, 10, 8, 22, 55, tzinfo=UTC_PLUS_8)
        self._phase_ending_at("卖", datetime(2026, 10, 8, 23, 5, tzinfo=UTC_PLUS_8))()
        self.now[0] = datetime(2026, 10, 9, 9, 0, tzinfo=UTC_PLUS_8)  # next morning's run
        self.calls.clear()
        self._phase("卖")()
        self.assertEqual(["卖"], self.calls)

    def test_a_buy_that_crosses_08_00_leaves_the_new_stock_to_buy(self):
        self.now[0] = datetime(2026, 10, 9, 7, 58, tzinfo=UTC_PLUS_8)
        self._phase_ending_at("买", datetime(2026, 10, 9, 8, 1, tzinfo=UTC_PLUS_8))()
        self.calls.clear()
        self._phase("买")()
        self.assertEqual(["买"], self.calls)
        self.calls.clear()
        self._phase("买")()  # now done for the 08:00 day
        self.assertEqual([], self.calls)


if __name__ == "__main__":
    unittest.main()
