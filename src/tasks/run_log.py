"""Every task run of the game day, for the 今日报表 page (Leo 2026-10-05).

``run_report`` keeps only the last 一键日常 / 一键周常 run and ``run_history``
only each task's last result, so a re-run hid the first one.  Here every
finished run is one entry: batch children as their rows end, single runs
when the executor reports them.  Entries live per game day (08:00 UTC+8) in
``configs/run_log.json``; the last few days are kept.
"""

from __future__ import annotations

import os
import threading
import time

from ok import Logger
from ok.util.file import get_relative_path, read_json_file, write_json_file

from src.utils import accounts
from src.utils.game_day import DAILY_REFRESH_HOUR, GAME_TZ

logger = Logger.get_logger(__name__)

LOG_FILE = ("configs", "run_log.json")
REPORT_FILE = ("configs", "run_reports.json")
KEEP_DAYS = 7

# Entry states, the same words as run_report rows.
DONE = "done"
FAIL = "fail"
SKIP = "skip"

# Where a run came from when it was not part of a batch.
SINGLE = "单独执行"

_lock = threading.RLock()


def _folder(folder: str | None) -> str:
    """The configs folder; callers pass the folder of their own file so a
    test writing a temporary report never touches the real log."""
    # Each game account has its own day (GitHub issue #4).
    return folder or os.path.dirname(accounts.scoped(get_relative_path(*LOG_FILE)))


def _log_path(folder: str | None) -> str:
    return os.path.join(_folder(folder), LOG_FILE[-1])


def _report_path(folder: str | None) -> str:
    return os.path.join(_folder(folder), REPORT_FILE[-1])


def day_key(ts: float | None = None) -> str:
    from datetime import datetime, timedelta

    moment = datetime.fromtimestamp(time.time() if ts is None else ts, tz=GAME_TZ)
    return (moment - timedelta(hours=DAILY_REFRESH_HOUR)).date().isoformat()


def _read(folder: str | None) -> dict:
    try:
        data = read_json_file(_log_path(folder))
    except Exception:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
        return {"days": {}}
    return data


def _write(data: dict, folder: str | None) -> None:
    days = data["days"]
    for old in sorted(days)[:-KEEP_DAYS]:
        days.pop(old, None)
    try:
        write_json_file(_log_path(folder), data)
    except Exception as exc:  # never let the log break a run
        logger.error(f"save run log failed: {exc}")


def add(
    name: str,
    state: str,
    *,
    started: float | None,
    finished: float | None = None,
    note: str = "",
    via: str = SINGLE,
    images: dict | None = None,
    trade: dict | None = None,
    folder: str | None = None,
) -> None:
    finished = time.time() if finished is None else finished
    entry = {
        "name": str(name),
        "state": state,
        "started": started,
        "finished": finished,
        "duration": max(0.0, finished - started) if started else None,
        "note": str(note or ""),
        "via": str(via or SINGLE),
        "images": {kind: list(paths) for kind, paths in (images or {}).items() if paths},
    }
    if trade:
        # What a trade run sold and cooked (YES-BD2 #6).
        entry["trade"] = trade
    with _lock:
        data = _read(folder)
        key = day_key(finished)
        if key not in data["days"]:
            data["days"][key] = _backfill(key, folder)
        data["days"][key].append(entry)
        _write(data, folder)


def entries(day: str | None = None, folder: str | None = None) -> list[dict]:
    """The runs of a game day (today by default), oldest first."""
    key = day or day_key()
    with _lock:
        data = _read(folder)
        found = data["days"].get(key)
        if found is None:
            found = _backfill(key, folder)
            if found:
                data["days"][key] = found
                _write(data, folder)
    return sorted(
        (entry for entry in found if isinstance(entry, dict)),
        key=lambda entry: entry.get("finished") or 0,
    )


def week_seconds(now: float | None = None, folder: str | None = None) -> float:
    """How long tasks ran this game week (since Monday's reset), for 今日报表.

    Leo 2026-10-09: the time the tool really spent, not an estimate of what
    playing by hand would take.  KEEP_DAYS covers the whole week.
    """
    from src.tasks.run_history import week_start_ts

    now = time.time() if now is None else now
    start = week_start_ts(now)
    total = 0.0
    for offset in range(7):
        moment = start + offset * 86400
        if moment > now:
            break
        for entry in entries(day_key(moment), folder):
            try:
                total += max(0.0, float(entry.get("duration") or 0))
            except (TypeError, ValueError):
                continue
    return total


def _backfill(key: str, folder: str | None) -> list[dict]:
    """Runs of that day already in the saved batch reports (before this log)."""
    try:
        reports = read_json_file(_report_path(folder))
    except Exception:
        return []
    if not isinstance(reports, dict):
        return []
    found = []
    for report in reports.values():
        if not isinstance(report, dict) or not report.get("finished"):
            continue
        if day_key(report["finished"]) != key:
            continue
        for row in report.get("rows") or []:
            if not row.get("started") or row.get("state") not in (DONE, FAIL, SKIP):
                continue
            found.append(
                {
                    "name": str(row.get("name") or row.get("key") or ""),
                    "state": row["state"],
                    "started": row.get("started"),
                    "finished": row.get("finished") or report["finished"],
                    "duration": row.get("duration"),
                    "note": str(row.get("note") or ""),
                    "via": str(report.get("label") or ""),
                    "images": {},
                }
            )
    return found


def group_by_task(day_entries: list[dict]) -> list[tuple[str, list[dict]]]:
    """(task name, its runs oldest first), tasks in the order they first ran."""
    groups: dict[str, list[dict]] = {}
    for entry in day_entries:
        groups.setdefault(str(entry.get("name") or ""), []).append(entry)
    return list(groups.items())
