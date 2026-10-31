"""A chore done today, kept in its own small file per 帳號.

The run history keeps only a task's latest run, so a later failed run (or a
run whose way home failed) hides what was already done that game day
(Leo 2026-10-31 「都已經成功抽了 工具應該要紀錄起來吧」).  The chore's own
file says it was done today, however the run ended.
"""

from __future__ import annotations

import json
from pathlib import Path


def _path(relative: Path) -> Path:
    from src.utils import accounts, test_run

    path = Path(accounts.scoped(relative))
    return test_run.scratch() / path if test_run.active() else path


def game_day() -> str:
    from datetime import datetime

    from src.tasks.map_trade.progress import UTC_PLUS_8, daily_cycle_key

    return daily_cycle_key(datetime.now(UTC_PLUS_8))


def done_today(relative: Path) -> bool:
    try:
        data = json.loads(_path(relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("day") == game_day()


def record_today(relative: Path) -> None:
    try:
        path = _path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"day": game_day()}), encoding="utf-8")
    except OSError:
        pass  # a record must never stop the run
