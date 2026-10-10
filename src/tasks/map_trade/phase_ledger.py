"""Remember which trade phases already succeeded in their current period.

A failed trade is retried 30 minutes later.  Without this, the retry after a
failed 卖 cooked MAX and bought again, spending the day's currency twice.
料理 and 买 follow the shop restock (08:00 UTC+8); 卖 follows the price table,
which switches to the next day at 23:00 UTC+8.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.tasks.map_trade.calendar import sale_price_calendar_date
from src.tasks.map_trade.progress import UTC_PLUS_8, daily_cycle_key
from src.utils import accounts

LEDGER_PATH = Path("configs") / "map_trade_phases.json"
# Set by the batches in 执行剩余 mode (and so by automatic retries): only
# then are phases done this period skipped.  A manual run redoes them.
ONLY_INCOMPLETE_KEY = "_仅补做未完成"
SELL_PHASE = "卖"


def period_key(phase: str, now: datetime) -> str:
    if phase == SELL_PHASE:
        return sale_price_calendar_date(now).isoformat()
    return daily_cycle_key(now)


class PhaseLedger:
    def __init__(
        self,
        path: Path | str | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        # One ledger per game account (GitHub issue #4).
        self.path = Path(path) if path is not None else Path(accounts.scoped(LEDGER_PATH))
        self.now_provider = now_provider or (lambda: datetime.now(UTC_PLUS_8))

    def _read(self) -> dict[str, str]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(key): str(value) for key, value in raw.items()} if isinstance(raw, dict) else {}

    def done(self, phase: str) -> bool:
        return self._read().get(phase) == period_key(phase, self.now_provider())

    def mark_done(self, phase: str, key: str) -> None:
        records = self._read()
        records[phase] = key
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def once(
        self, phase: str, action: Callable[[], object], *, skip_done: bool = True
    ) -> Callable[[], object]:
        """Wrap a phase: record its success; skip it if done and ``skip_done``."""

        def run():
            if skip_done and self.done(phase):
                return PhaseSkipped(f"本期已完成{phase}，跳过（避免重复消耗）。")
            # The period the work started in: a sell from 22:55 that ends at
            # 23:05 must not mark the next day's sale as done (nor a buy
            # across 08:00 the next day's stock).
            key = period_key(phase, self.now_provider())
            result = action()
            if bool(getattr(result, "success", result)) and getattr(result, "record", True):
                self.mark_done(phase, key)
            return result

        return run


class PhaseSkipped:
    success = True

    def __init__(self, message: str) -> None:
        self.message = message


class PhaseDeferred:
    """Nothing done yet, but the later phases may go on; not recorded, so the
    next run tries this phase again (e.g. bargain waiting for its star-up)."""

    success = True
    record = False

    def __init__(self, message: str) -> None:
        self.message = message

