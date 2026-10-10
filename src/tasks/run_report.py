"""What one 一键完成日常 / 一键完成周常 run did, for the 跑完的结算 page.

The batch fills one report while it runs (each child's state, how long it
took and why it was skipped or failed) and saves it when it ends, normally,
by Stop or by an error.  The UI reads the live copy for the 跑的时候 view and
the saved one for the summary and the home page's 上次运行 card.

Tasks can add pictures to the report while it runs (the claimed mail
rewards); they are saved under ``screenshots/run_report/<game day>/`` and only
the last few game days are kept.
"""

from __future__ import annotations

import copy
import os
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from ok import Logger
from ok.util.file import get_relative_path, read_json_file, write_json_file

from src.utils import accounts
from src.utils.game_day import DAILY_REFRESH_HOUR, GAME_TZ

logger = Logger.get_logger(__name__)

REPORT_FILE = ("configs", "run_reports.json")
IMAGE_ROOT = ("screenshots", "run_report")
KEEP_IMAGE_DAYS = 7
MAX_IMAGES_PER_KIND = 8

# Row states, shared with the UI.
WAIT = "wait"
RUN = "run"
DONE = "done"
SKIP = "skip"
FAIL = "fail"

# Report end states.
ENDED_DONE = "done"
ENDED_FAILED = "failed"
ENDED_ABORTED = "aborted"
ENDED_STOPPED = "stopped"
ENDED_ERROR = "error"
# The 开跑前检查 stopped it before anything was pressed (setup_check).
ENDED_SETUP = "setup"

_lock = threading.RLock()
_active: dict | None = None
_loose: list[tuple[float, str, str]] = []
# What a single trade run (outside a batch) sold and cooked.
_loose_trade: list[tuple[float, dict]] = []
_report_file: str | None = None


def game_day_key(ts: float | None = None) -> str:
    moment = datetime.fromtimestamp(time.time() if ts is None else ts, tz=GAME_TZ)
    return (moment - timedelta(hours=DAILY_REFRESH_HOUR)).date().isoformat()


def set_report_file(path: str | None) -> None:
    """Point the saved reports at another file (tests); None restores the default."""
    global _report_file
    _report_file = path


def _report_path() -> str:
    # Each game account has its own last run (GitHub issue #4).
    return _report_file or accounts.scoped(get_relative_path(*REPORT_FILE))


def begin(label: str, mode: str, rows: list[tuple[str, str]]) -> None:
    """Start a report: ``rows`` are (config key, display name) in run order."""
    global _active
    with _lock:
        _active = {
            "label": label,
            "mode": mode,
            "started": time.time(),
            "finished": None,
            "ended": None,
            "current": None,
            "rows": [
                {"key": key, "name": name, "state": WAIT, "started": None,
                 "finished": None, "duration": None, "note": ""}
                for key, name in rows
            ],
            "images": {},
        }


def _row(key: str) -> dict | None:
    if _active is None:
        return None
    for row in _active["rows"]:
        if row["key"] == key:
            return row
    return None


def row_started(key: str) -> None:
    with _lock:
        row = _row(key)
        if row is None:
            return
        row["state"] = RUN
        row["started"] = time.time()
        row["note"] = ""
        row.pop("trade", None)
        _active["current"] = key


def row_ended(key: str, state: str, note: str = "") -> None:
    with _lock:
        row = _row(key)
        if row is None:
            return
        now = time.time()
        row["state"] = state
        if row.get("started"):
            row["finished"] = now
            row["duration"] = max(0.0, now - row["started"])
        row["note"] = note or ""
        if _active.get("current") == key:
            _active["current"] = None
        _log_row(row, _active.get("label"))


def _log_row(row: dict, label: str | None) -> None:
    """A row that actually ran goes into the day's run log (今日报表)."""
    if not row.get("started"):
        return  # skipped before starting (already done this period, …)
    try:
        from src.tasks import run_log

        run_log.add(
            str(row.get("name") or row.get("key") or ""),
            row.get("state") or SKIP,
            started=row.get("started"),
            finished=row.get("finished"),
            note=str(row.get("note") or ""),
            via=str(label or ""),
            images=row.get("images"),
            trade=row.get("trade"),
            folder=os.path.dirname(_report_path()),
        )
    except Exception as exc:  # never let the log break a run
        logger.error(f"run log failed: {exc}")


def add_trade(trade: dict) -> None:
    """What the running trade sold and cooked, shown under its row (YES-BD2 #6).

    In a batch it goes on the running row; a single run's run-log entry
    picks it up when it ends.
    """
    with _lock:
        if _active is not None:
            row = _row(_active.get("current") or "")
            if row is not None:
                row["trade"] = copy.deepcopy(trade)
            return
        _loose_trade.append((time.time(), copy.deepcopy(trade)))
        del _loose_trade[:-4]


def loose_trade(started: float | None, finished: float) -> dict | None:
    """The trade summary a single run left between ``started`` and ``finished``."""
    with _lock:
        found = [
            trade
            for ts, trade in _loose_trade
            if (started is None or ts >= started - 1) and ts <= finished + 1
        ]
    return copy.deepcopy(found[-1]) if found else None


def add_note(key: str, note: str) -> None:
    with _lock:
        row = _row(key)
        if row is not None and note:
            row["note"] = f"{row['note']}，{note}" if row.get("note") else note


def set_notice(text: str) -> None:
    """What the results page says under its title (the 开跑前检查's reminder)."""
    with _lock:
        if _active is not None:
            _active["notice"] = str(text or "")


def finish(ended: str) -> dict | None:
    """Close the active report, save it and return a copy."""
    global _active
    with _lock:
        if _active is None:
            return None
        report = _active
        _active = None
        report["finished"] = time.time()
        report["ended"] = ended
        report["current"] = None
        for row in report["rows"]:
            if row["state"] == RUN:
                row["state"] = FAIL if ended == ENDED_ERROR else SKIP
                if row.get("started"):
                    row["finished"] = report["finished"]
                    row["duration"] = max(0.0, report["finished"] - row["started"])
                if ended == ENDED_STOPPED and not row.get("note"):
                    row["note"] = "手动停止"
                _log_row(row, report.get("label"))
        saved = copy.deepcopy(report)
    _save(saved)
    return saved


def active() -> dict | None:
    """A copy of the report being filled right now, or None."""
    with _lock:
        return copy.deepcopy(_active) if _active is not None else None


def _save(report: dict) -> None:
    try:
        data = read_json_file(_report_path())
        if not isinstance(data, dict):
            data = {}
        data[str(report.get("label") or "")] = report
        write_json_file(_report_path(), data)
    except Exception as exc:  # never let the report break a run
        logger.error(f"save run report failed: {exc}")


def load(label: str) -> dict | None:
    try:
        data = read_json_file(_report_path())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    report = data.get(label)
    return report if isinstance(report, dict) else None


def saved() -> list[dict]:
    """Every finished saved report (one per batch), newest first."""
    try:
        data = read_json_file(_report_path())
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    reports = [r for r in data.values() if isinstance(r, dict) and r.get("finished")]
    return sorted(reports, key=lambda r: r.get("finished") or 0, reverse=True)


def latest() -> dict | None:
    """The most recently finished saved report of any batch."""
    try:
        data = read_json_file(_report_path())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    reports = [r for r in data.values() if isinstance(r, dict) and r.get("finished")]
    return max(reports, key=lambda r: r.get("finished") or 0, default=None)


def stopped_row(report: dict | None, now: float | None = None) -> dict | None:
    """Where 继续 picks up after a manual Stop, or None.

    Only a run stopped by hand in the current game day: after the 08:00
    reset everything is due again and a normal start does it all.  The row
    Stop cut short is run again from its start; when Stop landed between
    two items, the first one that never started.
    """
    if not report or report.get("ended") != ENDED_STOPPED:
        return None
    if game_day_key(report.get("finished") or 0) != game_day_key(now):
        return None
    rows = report.get("rows") or []
    for row in rows:
        if (
            row.get("started")
            and row.get("state") == SKIP
            and str(row.get("note") or "").startswith("手动停止")
        ):
            return row
    return next((row for row in rows if row.get("state") == WAIT), None)


# --------------------------------------------------------------- pictures

def _image_root() -> Path:
    return Path(get_relative_path(*IMAGE_ROOT))


def _prune_old_days(root: Path) -> None:
    try:
        days = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return
    for old in days[:-KEEP_IMAGE_DAYS]:
        shutil.rmtree(old, ignore_errors=True)


def save_picture(frame, kind: str) -> str | None:
    """Save a game frame (BGR array) for the report; returns the file path.

    Added to the active report's ``images[kind]`` when a batch is running.
    """
    if frame is None:
        return None
    try:
        import cv2

        root = _image_root()
        folder = root / game_day_key()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(time.time(), tz=GAME_TZ).strftime("%H%M%S")
        path = folder / f"{kind}-{stamp}-{int(time.time() * 1000) % 1000:03d}.png"
        if not cv2.imwrite(str(path), frame):
            return None
        _prune_old_days(root)
    except Exception as exc:
        logger.error(f"save report picture failed: {exc}")
        return None
    with _lock:
        if _active is not None:
            pictures = _active["images"].setdefault(kind, [])
            pictures.append(str(path))
            del pictures[:-MAX_IMAGES_PER_KIND]
            row = _row(_active.get("current") or "")
            if row is not None:
                row.setdefault("images", {}).setdefault(kind, []).append(str(path))
        else:
            # A single run: picked up by its run-log entry when it ends.
            _loose.append((time.time(), kind, str(path)))
            del _loose[:-MAX_IMAGES_PER_KIND * 4]
    return str(path)


def loose_pictures(started: float | None, finished: float) -> dict[str, list[str]]:
    """Pictures saved outside a batch between ``started`` and ``finished``."""
    found: dict[str, list[str]] = {}
    with _lock:
        for ts, kind, path in _loose:
            if (started is None or ts >= started - 1) and ts <= finished + 1:
                found.setdefault(kind, []).append(path)
    return found
