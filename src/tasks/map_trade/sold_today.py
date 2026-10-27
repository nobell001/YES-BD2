"""Which planned items were already sold for the current price day.

YES-BD2 #60 (2026-10-27): a sell that failed halfway was run again; the
价目表 did not open that time, so the shop search went to the shops of
items the first run had already sold.  The 价目表 stays the authority when
it reads; this record only steers the shop search used when it does not.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.utils import accounts

SOLD_PATH = Path("configs") / "map_trade_sold.json"


class SoldToday:
    def __init__(self, path: Path | str | None = None) -> None:
        # One record per game account, like the phase ledger.
        self.path = Path(path) if path is not None else Path(accounts.scoped(SOLD_PATH))

    def items(self, day: str) -> set[str]:
        """Items finished on price day ``day`` (an ISO date)."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        if not isinstance(raw, dict) or raw.get("day") != day:
            return set()
        return {str(item) for item in raw.get("items", ()) if str(item)}

    def add(self, day: str, item: str) -> None:
        items = self.items(day) | {item}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"day": day, "items": sorted(items)}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
