"""Persisted per-task run records backing the quest-style UI metadata.

The task cards and the daily board banner need "上次完成 · 今天 09:12" style
information, which the framework does not track.  This module records the most
recent finished run of every one-time task into a small JSON file and derives
"completed today / this week" from the game's Beijing-time refresh anchors
(daily 08:00, weekly Monday 08:00, UTC+8).

Batch tasks (一键完成日常) run their children through ``task.run()`` directly,
so the executor never emits ``task_done`` for them.  ``record_task_done``
therefore fans a batch record out into per-child records using the batch's
``info`` lists (完成/失败/跳过), making a child finished inside the batch count
the same as running it standalone.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any

from ok import Logger
from ok.util.file import get_relative_path, read_json_file, write_json_file

from src.tasks.BaseBD2Task import task_info_snapshot
from src.utils import accounts
from src.utils.game_day import DAILY_REFRESH_HOUR, GAME_TZ

logger = Logger.get_logger(__name__)

# Game-day boundary lives in src.utils.game_day (08:00 UTC+8).
BEIJING_TZ = GAME_TZ

STORE_VERSION = 1
DEFAULT_FILE = ("configs", "task_run_history.json")

# Status texts containing any of these markers never count as a completion.
_FAILURE_MARKERS = ("中止", "失败")

# A run whose info carries this key stopped before pressing anything (the
# 开跑前检查 found the game set to 繁中): not a run, so neither a record nor a
# failure backoff that would skip the item once the player fixed the game.
NOT_STARTED_KEY = "没有开始"

# The 失败 field uses list strings, joined stage names, or empty placeholders.
_NO_FAILURE_VALUES = frozenset({"", "-", "0", "无", "[]", "none", "false"})

# Game days kept per task for the 最近 7 天 dots ("YYYY-MM-DD" -> done that day).
KEEP_DAYS = 14


def _to_beijing(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=BEIJING_TZ)


def day_start_ts(now: float | None = None) -> float:
    """Return the start of the current game day (today 08:00 UTC+8)."""
    moment = _to_beijing(time.time() if now is None else now)
    anchor = moment.replace(hour=DAILY_REFRESH_HOUR, minute=0, second=0, microsecond=0)
    if moment < anchor:
        anchor -= timedelta(days=1)
    return anchor.timestamp()


def game_day_key(ts: float) -> str:
    """The game day (08:00 UTC+8 boundary) a moment belongs to, as YYYY-MM-DD."""
    return _to_beijing(day_start_ts(ts)).date().isoformat()


def _merge_days(previous: dict | None, finished: float, ok: bool) -> dict:
    """Carry a task's per-day results forward; a day counts once any run succeeded."""
    days = {}
    if isinstance(previous, dict) and isinstance(previous.get("days"), dict):
        days = {str(key): bool(value) for key, value in previous["days"].items()}
    key = game_day_key(finished)
    days[key] = bool(days.get(key)) or bool(ok)
    for old in sorted(days)[:-KEEP_DAYS]:
        days.pop(old, None)
    return days


def week_start_ts(now: float | None = None) -> float:
    """Return the start of the current game week (Monday 08:00 UTC+8)."""
    day_start = _to_beijing(day_start_ts(now))
    monday = day_start - timedelta(days=day_start.weekday())
    return monday.timestamp()


def _is_successful_run(info: dict) -> bool:
    if info.get("Error"):
        return False
    status = str(info.get("状态", ""))
    if any(marker in status for marker in _FAILURE_MARKERS):
        return False
    # Several tasks return False with a status text that carries no failure
    # marker (e.g. DailyTask's "公会、小屋、酒馆结束。"), so the structured
    # 失败/结果 keys must be consulted too, or failed runs get recorded as
    # completions and the scheduler skips them for the whole day.
    failure = str(info.get("失败", "")).strip()
    if failure and failure.casefold() not in _NO_FAILURE_VALUES:
        return False
    return "失败" not in str(info.get("结果", ""))


def is_successful_run(info: dict) -> bool:
    """Public wrapper so the scheduler can reuse the same success rule."""
    return _is_successful_run(info)


def contains_joined_name(joined: Any, name: str) -> bool:
    """Boundary-aware membership test for '、'-joined info lists.

    Child names may themselves contain '、' (e.g. 公会、小屋、酒馆), so plain
    split('、') corrupts them.  Elements of these lists are always whole
    config keys, so an exact substring bounded by start/end or '、' is a
    reliable membership test.
    """
    if not isinstance(joined, str) or not name:
        return False
    start = joined.find(name)
    while start >= 0:
        end = start + len(name)
        before_ok = start == 0 or joined[start - 1] == "、"
        after_ok = end == len(joined) or joined[end] == "、"
        if before_ok and after_ok:
            return True
        start = joined.find(name, start + 1)
    return False


class RunHistoryStore:
    """JSON-backed ``task name -> last finished run`` records."""

    def __init__(self, path: str | None = None):
        self.path = path or get_relative_path(*DEFAULT_FILE)
        self._records: dict[str, dict] = {}
        self._mtime = None
        self._load()

    def _file_mtime(self):
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return None

    def _refresh(self) -> None:
        # The tool on the 桌面分身 writes this file while the one on the
        # user's desktop shows it (Leo, 2026-10-03).
        if self._file_mtime() != self._mtime:
            self._load()

    def _load(self) -> None:
        self._mtime = self._file_mtime()
        data = read_json_file(self.path)
        if not isinstance(data, dict):
            if data is not None:
                logger.warning(f"run history file is not a dict, reset: {self.path}")
            self._records = {}
            return
        records = data.get("tasks")
        if data.get("version") != STORE_VERSION or not isinstance(records, dict):
            self._records = {}
            return
        self._records = {
            str(name): record
            for name, record in records.items()
            if isinstance(record, dict) and isinstance(record.get("finished"), (int, float))
        }

    def _save(self) -> None:
        try:
            write_json_file(
                self.path,
                {"version": STORE_VERSION, "tasks": self._records},
            )
            self._mtime = self._file_mtime()
        except Exception as exc:  # never let UI metadata break task execution
            logger.error(f"save run history failed: {exc}")

    def last_run(self, task_name: str) -> dict | None:
        self._refresh()
        return self._records.get(task_name)

    def is_completed_today(self, task_name: str, now: float | None = None) -> bool:
        self._refresh()
        record = self._records.get(task_name)
        return bool(record and record.get("ok") and record["finished"] >= day_start_ts(now))

    def is_completed_this_week(self, task_name: str, now: float | None = None) -> bool:
        self._refresh()
        record = self._records.get(task_name)
        return bool(record and record.get("ok") and record["finished"] >= week_start_ts(now))

    def recent_days(self, task_name: str, count: int = 7, now: float | None = None) -> list:
        """Oldest first: True (done), False (ran, failed) or None (no run) per game day."""
        self._refresh()
        record = self._records.get(task_name) or {}
        days = record.get("days") if isinstance(record.get("days"), dict) else {}
        if not days and record.get("finished"):
            # Records written before the per-day history: only the last run.
            days = {game_day_key(record["finished"]): bool(record.get("ok"))}
        today = day_start_ts(now)
        result = []
        for offset in range(count - 1, -1, -1):
            key = game_day_key(today - offset * 86400 + 1)
            result.append(days.get(key))
        return result

    def record_task_done(self, task, finished: float | None = None) -> None:
        """Record a finished run, fanning batch results out to children."""
        finished = time.time() if finished is None else finished
        started = getattr(task, "start_time", 0) or 0
        duration = max(0.0, finished - started) if started else None
        info = task_info_snapshot(task)

        ok = _is_successful_run(info)
        self._records[str(task.name)] = {
            "finished": finished,
            "duration": duration,
            "status": str(info.get("状态", "")),
            "ok": ok,
            "days": _merge_days(self._records.get(str(task.name)), finished, ok),
        }

        child_tasks = getattr(task, "child_tasks", None)
        if child_tasks:
            self._record_batch_children(task, child_tasks, info, finished, duration)
        else:
            # Batch children are logged by run_report as their rows end.
            _log_single_run(task, info, ok, started or None, finished, os.path.dirname(self.path))

        self._save()

    def record_stopped_batch(self, task, stopped: float | None = None) -> None:
        """Keep what a batch finished before Stop was pressed.

        ok-script emits ``task_done`` only for a run that ends by itself, so
        without this the children done before a manual Stop were never
        recorded and 继续 ran them again (Leo 2026-10-06: stopped during
        抽抽乐, 继续 should not redo what was already done).  The batch's own
        record is left alone: the batch did not finish.
        """
        child_tasks = getattr(task, "child_tasks", None)
        if not child_tasks:
            return
        stopped = time.time() if stopped is None else stopped
        started = getattr(task, "start_time", 0) or 0
        duration = max(0.0, stopped - started) if started else None
        info = task_info_snapshot(task)
        if self._record_batch_children(task, child_tasks, info, stopped, duration):
            self._save()

    def _record_batch_children(self, task, child_tasks, info, finished, duration) -> bool:
        done_text = info.get("完成")
        fail_text = info.get("失败")
        name_by_config_key = self._child_display_names(task, child_tasks)
        child_finished = getattr(task, "_child_finished", None) or {}
        child_started = getattr(task, "_child_started", None) or {}
        recorded = False
        for child in child_tasks:
            config_key = child.config_key
            completed = contains_joined_name(done_text, config_key)
            failed = contains_joined_name(fail_text, config_key)
            if completed == failed:
                # Skipped (in neither list) or ambiguous; only the unambiguous
                # states become records.
                continue
            recorded = True
            name = name_by_config_key.get(config_key, config_key)
            child_end = child_finished.get(config_key, finished)
            child_start = child_started.get(config_key)
            # The child's own time when the batch measured it (older batches
            # only knew the whole run's duration).
            child_duration = max(0.0, child_end - child_start) if child_start else duration
            # One started before the 08:00 refresh counts for the game day
            # (and week) it started in, not the new one.
            stamp = child_end
            if child_start and day_start_ts(child_start) != day_start_ts(child_end):
                stamp = child_start
            self._records[name] = {
                "finished": stamp,
                "duration": child_duration,
                "status": "随一键完成日常完成" if completed else "随一键完成日常失败",
                "ok": completed,
                "days": _merge_days(self._records.get(name), stamp, completed),
            }
        return recorded

    @staticmethod
    def _child_display_names(task, child_tasks) -> dict[str, str]:
        """Map batch config keys to the child tasks' display names."""
        names: dict[str, str] = {}
        executor = getattr(task, "executor", None)
        for child in child_tasks:
            child_task = None
            if executor is not None:
                try:
                    child_task = executor.get_task_by_class(child.task_class)
                except Exception:
                    child_task = None
            names[child.config_key] = str(getattr(child_task, "name", None) or child.config_key)
        return names


def _log_single_run(task, info: dict, ok: bool, started, finished: float, folder: str) -> None:
    try:
        from src.tasks import run_log, run_report

        run_log.add(
            str(task.name),
            run_log.DONE if ok else run_log.FAIL,
            started=started,
            finished=finished,
            note="" if ok else str(info.get("状态", "")),
            images=run_report.loose_pictures(started, finished),
            trade=run_report.loose_trade(started, finished),
            folder=folder,
        )
    except Exception as exc:  # never let the log break a run
        logger.error(f"run log failed: {exc}")


_default_store: RunHistoryStore | None = None
_default_store_own = True  # False while a test put its own store in


def default_store() -> RunHistoryStore:
    """The current game account's store (GitHub issue #4): switching accounts
    hands out the other account's file from the next call on."""
    global _default_store
    wanted = accounts.scoped(get_relative_path(*DEFAULT_FILE))
    if _default_store is None or (_default_store_own and _default_store.path != wanted):
        _default_store = RunHistoryStore(wanted)
    return _default_store


def set_default_store(store: RunHistoryStore | None) -> None:
    """Override the process-wide store (tests); None restores lazy creation."""
    global _default_store, _default_store_own
    _default_store = store
    _default_store_own = store is None


def install_run_history_recorder() -> bool:
    """Record every finished one-time task into the default store."""

    from ok.core.events import communicate
    from PySide6.QtCore import QObject

    if getattr(install_run_history_recorder, "_installed", False):
        return False

    class _Recorder(QObject):
        def on_task_done(self, task):
            name = str(getattr(task, "name", ""))
            try:
                if task_info_snapshot(task).get(NOT_STARTED_KEY):
                    return
            except Exception:
                pass
            try:
                default_store().record_task_done(task)
                record = default_store().last_run(name)
            except Exception as exc:
                logger.error(f"record run history failed: {exc}")
                record = None
            try:
                # ALAS 式调度账本：任务结束后按策略推迟 next_run 并落盘。
                from src.tasks import scheduler as task_scheduler

                if record is not None:
                    ok = bool(record.get("ok"))
                else:
                    ok = is_successful_run(task_info_snapshot(task))
                task_scheduler.default_store().delay_after_run(name, ok=ok)
            except Exception as exc:
                logger.error(f"record schedule failed: {exc}")

    recorder = _Recorder()
    communicate.task_done.connect(recorder.on_task_done)
    # Keep the receiver alive for the app's lifetime.
    install_run_history_recorder._recorder = recorder
    install_run_history_recorder._installed = True
    return True
