"""周常的勾：这周做过就自动取消，下周自动勾回来（Leo 2026-10-09）。

一键日常（桌面分身里跑的也一样）照勾选跑周常那几项。哪一项这周做完了，
工具就把它的勾取消，所以这周不会再跑；到了下周（周一 08:00，UTC+8）
工具取消过的勾会自己勾回来。玩家这周想再跑一次（例如测试），手动勾回去
就会跑，跑完又会被取消。玩家自己取消的勾不会被勾回来。

记录放在 configs/weekly_ticks.json：每一项「哪一次完成被处理过、在哪一周」，
桌面上的工具和桌面分身里的工具共用，每次都重新读，不留在内存里。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from src.tasks.run_history import week_start_ts
from src.utils import accounts

ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = ROOT / "configs" / "weekly_ticks.json"
# The batch's own finish stamp and the one run_history writes can differ a
# little; a completion this close to the handled one is the same completion.
SAME_RUN_SECONDS = 5.0


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # never let the ticks stop a run; the next sync tries again


def _entry(state: dict, key: str) -> dict | None:
    entry = state.get(key)
    if isinstance(entry, dict) and isinstance(entry.get("done"), (int, float)):
        return entry
    return None


def sync(
    config,
    children: Iterable[tuple[str, str]],
    last_run: Callable[[str], dict | None],
    now: float | None = None,
    path: Path | None = None,
) -> list[str]:
    """Bring the 周常 ticks in ``config`` up to date; returns the keys changed.

    ``children`` are (config key, task name) pairs; ``last_run`` is
    run_history's lookup by task name.
    """
    path = accounts.scoped(STATE_FILE) if path is None else path
    state = _read(path)
    week = week_start_ts(now)
    changed: list[str] = []
    dirty = False
    for key, name in children:
        entry = _entry(state, key)
        record = last_run(name) or {}
        finished = record.get("finished") if record.get("ok") else None
        new_done = (
            isinstance(finished, (int, float))
            and finished >= week
            and (entry is None or finished > entry["done"] + SAME_RUN_SECONDS)
        )
        if new_done:
            state[key] = {"done": finished, "week": week}
            dirty = True
            if bool(config.get(key, True)):
                config[key] = False
                changed.append(key)
        elif entry is not None and entry.get("week", 0) < week:
            # A new week: give back the tick the tool took away.
            state.pop(key, None)
            dirty = True
            if not bool(config.get(key, True)):
                config[key] = True
                changed.append(key)
    if dirty:
        _write(path, state)
    return changed


def mark_done(
    config, key: str, finished: float | None = None, now: float | None = None, path=None
) -> None:
    """A 周常 just finished in a run: take its tick away for this week."""
    path = accounts.scoped(STATE_FILE) if path is None else path
    finished = time.time() if finished is None else finished
    state = _read(path)
    state[key] = {"done": finished, "week": week_start_ts(now)}
    _write(path, state)
    if bool(config.get(key, True)):
        config[key] = False
