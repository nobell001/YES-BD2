"""问题摘要: what a run looked like, for players to send the author (Leo 2026-10-09).

Players only talk to Leo in comments; they cannot send files and will not
dig for logs.  So each run (一键日常 / 一键周常 or a single task) leaves a
small record: what ran, where it stopped and why, the game window and screen
it ran on, the last log lines of that moment and, when something went wrong,
the game frame of that moment and a few small frames of the seconds before it
(差異化點子 8, Leo 2026-10-10 「做8」: the last frame alone often shows only
where it ended up, not how it got there).  The UI turns a record into a picture or a few
lines of text to paste, or a picture saved to the desktop.

Records live in ``screenshots/problem_report/<game day>/``; the last
``KEEP_DAYS`` game days are kept.  Nothing personal goes in: no account, no
Windows user name, no paths.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
from collections import deque
from datetime import datetime
from functools import wraps
from pathlib import Path

from ok import Logger
from ok.util.file import get_relative_path

from src.utils.game_day import GAME_TZ

logger = Logger.get_logger(__name__)

ROOT = ("screenshots", "problem_report")
KEEP_DAYS = 7
# Log lines kept in memory for the record of the moment something went wrong.
RING_SIZE = 600
# Lines of a record (repeats folded into one).
LOG_LINES = 6
FRAME_WIDTH = 1920
# The seconds before a problem: one small frame every BEFORE_GAP seconds of
# the run, the last BEFORE_FRAMES of them saved with the problem (about 1 MB
# a problem at most).
BEFORE_FRAMES = 5
BEFORE_GAP = 2.0
BEFORE_WIDTH = 480
# A before-frame this close to the problem is the problem's own frame.
BEFORE_SKIP = 0.5
# ok-script's own line for every task.info_set call.
INFO_SET_PREFIX = "info_set "

# How a run ended, the words of run_report.
DONE = "done"
FAILED = "failed"
ABORTED = "aborted"
STOPPED = "stopped"
ERROR = "error"
# The 开跑前检查 found the game set to 繁中: nothing was pressed (setup_check).
SETUP = "setup"
PROBLEM_ENDS = (FAILED, ABORTED, STOPPED, ERROR)

ENDED_TEXT = {
    DONE: "全部完成",
    FAILED: "有项目失败",
    ABORTED: "中途停了",
    STOPPED: "手动停止",
    ERROR: "出错停了",
    SETUP: "没有开始跑",
}

_lock = threading.RLock()
_current: dict | None = None
_depth = threading.local()
_root_override: str | None = None
# (time, small frame) of the running record, oldest first.
_before: deque = deque(maxlen=BEFORE_FRAMES)


# ------------------------------------------------------------------ logs


class _Ring(logging.Handler):
    """The last log lines of the app (info and up), kept in memory."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: deque = deque(maxlen=RING_SIZE)

    def emit(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return
        # ok-script logs every info_set as a line; a run going home after a
        # failure wrote enough of them that the summary kept only those and
        # lost the failure itself (YES-BD2 issue #5, 2026-10-09).
        if _clean(message).startswith(INFO_SET_PREFIX):
            return
        self.lines.append((record.created, record.levelno, record.thread, message))


_ring: _Ring | None = None


def install_log_ring() -> None:
    global _ring
    if _ring is None:
        _ring = _Ring()
    _attach()
    _watch_frames()


def _attach() -> None:
    """Put the ring back on the "ok" logger: ok-script's config_logger replaces
    the logger's handlers when the app starts, which dropped it (Leo's 4K
    test, 10-09: the summary had no 最后 line)."""
    if _ring is None:
        return
    log = logging.getLogger("ok")
    if _ring not in log.handlers:
        log.addHandler(_ring)


def _clean(message: str) -> str:
    """'BaseBD2Task:每周跑图：开始' -> '每周跑图：开始'; the first line only."""
    text = str(message or "").strip().splitlines()[0] if message else ""
    head, sep, rest = text.partition(":")
    if sep and head and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", head):
        text = rest
    return text.strip()


# A user name can have spaces; up to the next folder sign or quote.
_USER_FOLDER = re.compile(r"(?i)([a-z]:[\\/]+users[\\/]+)[^\\/\"'\n]+")


def scrub(text: str) -> str:
    """No Windows user name in a record: 'C:\\Users\\<name>\\…' loses the name."""
    return _USER_FOLDER.sub(lambda m: m.group(1) + "<用户>", str(text or ""))


def _shape(text: str) -> str:
    """The line with its numbers blanked, so 'score 0.81' and 'score 0.79' fold."""
    return re.sub(r"\d+(?:\.\d+)?", "#", text)


def fold(lines: list[tuple[float, int, str]]) -> list[dict]:
    """Repeated lines (same words, other numbers) become one with a count.

    ``lines`` are (time, level, text) oldest first; a line repeats when it is
    the same as the one before, or as the one two before (a loop of two
    steps, like 'slide right' / 'slide left').
    """
    folded: list[dict] = []
    for at, level, text in lines:
        shape = _shape(text)
        for back in (1, 2):
            if len(folded) >= back and folded[-back]["shape"] == shape:
                entry = folded[-back]
                entry.update(at=at, text=text, level=max(entry["level"], level))
                entry["count"] += 1
                if back == 2:
                    folded.append(folded.pop(-2))
                break
        else:
            folded.append({"at": at, "level": level, "text": text, "shape": shape, "count": 1})
    return folded


def recent_lines(since: float | None, thread: int | None = None) -> list[tuple[float, int, str]]:
    """Log lines (time, level, text) since ``since`` from one thread, oldest first."""
    if _ring is None:
        return []
    found = []
    for at, level, ident, message in list(_ring.lines):
        if since is not None and at < since:
            continue
        if thread is not None and ident != thread:
            continue
        text = scrub(_clean(message))
        if text:
            found.append((at, level, text))
    return found


# ------------------------------------------------------------- the screen


def environment(executor) -> dict:
    """Game window, screen and tool facts for the record (best effort)."""
    info: dict = {}
    try:
        from src.config import config

        info["version"] = str(config.get("version") or "")
    except Exception:
        info["version"] = ""
    try:
        from src.utils.game_size import current_size

        size = current_size(executor)
    except Exception:
        size = None
    if size:
        info["game_size"] = [int(size[0]), int(size[1])]
    manager = getattr(executor, "device_manager", None)
    window = getattr(manager, "hwnd_window", None)
    hwnd = int(getattr(window, "hwnd", 0) or 0)
    scaling = getattr(window, "scaling", None)
    if isinstance(scaling, (int, float)) and scaling > 0:
        info["scaling"] = round(float(scaling) * 100)
    if hwnd:
        info.update(_window_facts(hwnd))
        try:
            from src.capture.hdr_wgc import display_hdr_white

            hdr, _white, detail = display_hdr_white(hwnd)
            if "failed" not in detail and "no display" not in detail:
                info["hdr"] = bool(hdr)
        except Exception:
            pass
    try:
        from src.utils import clone_desktop

        info["clone"] = bool(clone_desktop.in_clone())
    except Exception:
        pass
    try:
        from src.ui.shell.settings import LANGUAGE_LABELS, language_mode

        mode = language_mode()
        if mode and mode != "auto":
            info["ui_language"] = LANGUAGE_LABELS.get(mode, mode)
    except Exception:
        pass
    return info


def _window_facts(hwnd: int) -> dict:
    """窗口化 / 无边框 / 全屏 and the monitor's size (Windows only)."""
    try:
        import win32api
        import win32con
        import win32gui
    except Exception:
        return {}
    facts: dict = {}
    try:
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        left, top, right, bottom = win32api.GetMonitorInfo(monitor)["Monitor"]
        facts["monitor"] = [right - left, bottom - top]
        client = win32gui.GetClientRect(hwnd)
        width, height = client[2] - client[0], client[3] - client[1]
        if style & win32con.WS_CAPTION:
            facts["window_mode"] = "窗口化"
        elif (width, height) == (right - left, bottom - top):
            facts["window_mode"] = "全屏"
        else:
            facts["window_mode"] = "无边框"
    except Exception:
        pass
    return facts


def _last_frame(executor):
    """The last game frame the tool saw, without waiting for a new one."""
    frame = getattr(executor, "_frame", None)
    if frame is not None:
        return frame
    try:
        method = getattr(getattr(executor, "device_manager", None), "capture_method", None)
        return method.get_frame() if method is not None else None
    except Exception:
        return None


_WATCH_MARKER = "_bd2_problem_report_frames"


def _watch_frames() -> None:
    """Every frame a task waits for also goes to note_frame (once)."""
    try:
        from ok.task.TaskExecutor import TaskExecutor
    except Exception:
        return
    original = TaskExecutor.next_frame
    if getattr(original, _WATCH_MARKER, False):
        return

    @wraps(original)
    def next_frame_noted(self, *args, **kwargs):
        frame = original(self, *args, **kwargs)
        if frame is not None and _current is not None:
            note_frame(frame)
        return frame

    setattr(next_frame_noted, _WATCH_MARKER, True)
    TaskExecutor.next_frame = next_frame_noted


def note_frame(frame, now: float | None = None) -> None:
    """Keep a small copy of a frame of the running record, one per BEFORE_GAP."""
    if _current is None:
        return
    now = time.time() if now is None else now
    if _before and now - _before[-1][0] < BEFORE_GAP:
        return
    try:
        import cv2

        height, width = frame.shape[:2]
        if width <= 0 or height <= 0:
            return
        if width > BEFORE_WIDTH:
            small = cv2.resize(
                frame, (BEFORE_WIDTH, max(1, round(height * BEFORE_WIDTH / width))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            small = frame.copy()
        if small.ndim == 3 and small.shape[2] == 4:
            small = cv2.cvtColor(small, cv2.COLOR_BGRA2BGR)
    except Exception:
        return  # a copy that fails must never break the run
    with _lock:
        if _current is not None:
            _before.append((now, small))


def note_give_up(task, frame, now: float | None = None) -> None:
    """A task gave up a step (``_save_flow_diagnostic``): keep that screen.

    The problem itself is noted after the task went home, so its frame
    showed the home page (a player's 圣石洞穴 问题摘要, 2026-10-10).  If this
    task's run fails, the record shows this screen and the seconds before it.
    """
    if _current is None or frame is None:
        return
    now = time.time() if now is None else now
    try:
        import cv2

        height, width = frame.shape[:2]
        if width > FRAME_WIDTH:  # what _save_frame keeps anyway
            kept = cv2.resize(
                frame, (FRAME_WIDTH, round(height * FRAME_WIDTH / width)),
                interpolation=cv2.INTER_AREA,
            )
        else:
            kept = frame.copy()
    except Exception:
        return  # a copy that fails must never break the run
    with _lock:
        current = _current
        if current is None or current.get("thread") != threading.get_ident():
            return  # another thread's task (a trigger) is not this run
        current["give_up"] = {
            "at": now,
            "task": str(getattr(task, "name", "") or ""),
            "frame": kept,
            "before": [(at, small) for at, small in _before if at <= now - BEFORE_SKIP],
        }


# ------------------------------------------------------------------ files


def set_root(path: str | None) -> None:
    """Keep the records somewhere else (tests); None restores the default."""
    global _root_override
    _root_override = path


def root() -> Path:
    if _root_override:
        return Path(_root_override)
    from src.utils import test_run

    if test_run.active():
        return test_run.scratch().joinpath(*ROOT)
    return Path(get_relative_path(*ROOT))


def _day_key(ts: float) -> str:
    from src.tasks.run_report import game_day_key

    return game_day_key(ts)


def _stamp(ts: float) -> str:
    moment = datetime.fromtimestamp(ts, tz=GAME_TZ)
    return moment.strftime("%H%M%S") + f"-{int(ts * 1000) % 1000:03d}"


def _save_frame(frame, ts: float, suffix: str = "", quality: int = 88) -> str:
    try:
        import cv2

        height, width = frame.shape[:2]
        if width > FRAME_WIDTH:
            frame = cv2.resize(
                frame, (FRAME_WIDTH, round(height * FRAME_WIDTH / width)),
                interpolation=cv2.INTER_AREA,
            )
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        folder = root() / _day_key(ts)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_stamp(ts)}{suffix}.jpg"
        if cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, quality]):
            return path.name
    except Exception as exc:
        logger.error(f"problem report frame failed: {exc}")
    return ""


def _prune() -> None:
    try:
        days = sorted(p for p in root().iterdir() if p.is_dir())
    except OSError:
        return
    for old in days[:-KEEP_DAYS]:
        shutil.rmtree(old, ignore_errors=True)


def _write(record: dict) -> str | None:
    try:
        folder = root() / _day_key(record["finished"])
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_stamp(record['finished'])}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        _prune()
        return str(path)
    except Exception as exc:
        logger.error(f"save problem report failed: {exc}")
        return None


# The same problem again within this many seconds updates the last record
# instead of adding one (a task the tool retries must not fill the page).
REPEAT_SECONDS = 120
_last_written: dict = {}
# Leo's first 4K test build (10-09) saved 自动登录游戏's every-second checks.
OLD_TRIGGER_LABELS = {"自动登录游戏"}


def _repeat_key(record: dict) -> tuple:
    problem = record.get("problem") or {}
    return (record.get("label"), record.get("ended"), problem.get("task"), problem.get("stage"))


def _save(record: dict) -> str | None:
    """Write the record, or fold it into the last one when it is a quick repeat."""
    with _lock:
        last = dict(_last_written)
    key = _repeat_key(record)
    path = last.get("path")
    if (
        path
        and last.get("key") == key
        and 0 <= float(record["finished"]) - float(last.get("finished") or 0) <= REPEAT_SECONDS
    ):
        try:
            earlier = json.loads(Path(path).read_text(encoding="utf-8"))
            earlier["repeats"] = int(earlier.get("repeats") or 1) + 1
            earlier["finished"] = record["finished"]
            Path(path).write_text(
                json.dumps(earlier, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            for name in _frame_files(record):
                (Path(path).parent / name).unlink(missing_ok=True)
            with _lock:
                _last_written["finished"] = record["finished"]
            return path
        except (OSError, ValueError):
            pass  # the earlier file is gone: write a new one
    saved = _write(record)
    with _lock:
        _last_written.clear()
        if saved:
            _last_written.update(key=key, path=saved, finished=record["finished"])
    return saved


def _frame_files(record: dict) -> list[str]:
    """The image files a record's problem saved (its frame and the ones before)."""
    problem = record.get("problem") or {}
    names = [problem.get("frame")]
    names += [item.get("file") for item in problem.get("before") or [] if isinstance(item, dict)]
    return [str(name) for name in names if name]


def is_trigger(task) -> bool:
    """A task the executor runs by itself every second (自动登录游戏), not one
    the player started: it keeps no record."""
    try:
        from ok import TriggerTask

        if isinstance(task, TriggerTask):
            return True
    except ImportError:
        pass
    if getattr(type(task), "runs_by_itself", False):
        return True
    executor = getattr(task, "executor", None)
    return any(other is task for other in (getattr(executor, "trigger_tasks", None) or []))


def records(limit: int = 60) -> list[dict]:
    """Saved records, newest first; each has ``path`` and, if any, ``frame_path``."""
    found = []
    try:
        files = sorted(root().glob("*/*.json"), reverse=True)
    except OSError:
        return []
    for path in files[: limit * 2]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or not record.get("finished"):
            continue
        if record.get("label") in OLD_TRIGGER_LABELS:
            continue  # written by the first test build; not a run anyone started
        record["path"] = str(path)
        problem = record.get("problem") or {}
        frame = problem.get("frame")
        if frame:
            record["frame_path"] = str(path.parent / frame)
        before = [
            {"at": item.get("at"), "path": str(path.parent / item["file"])}
            for item in problem.get("before") or []
            if isinstance(item, dict) and item.get("file")
        ]
        if before:
            record["before_paths"] = before
        found.append(record)
    found.sort(key=lambda r: r.get("finished") or 0, reverse=True)
    return found[:limit]


def find(label: str | None, finished: float | None) -> dict | None:
    """The record of the run that ended at ``finished`` (a batch summary)."""
    if not finished:
        return None
    for record in records(20):
        if abs(float(record.get("finished") or 0) - float(finished)) <= 5 and (
            not label or record.get("label") == label
        ):
            return record
    return None


# --------------------------------------------------------------- the run


def depth() -> int:
    return getattr(_depth, "value", 0)


class run_scope:
    """``with run_scope(task):`` around a task's run; the outermost one keeps a record.

    Only in the app (the log ring installed) and only for ``keep`` runs: a
    trigger task or a test double never writes one.
    """

    def __init__(self, task, keep: bool = True):
        self.task = task
        self.keep = keep
        self.outer = False
        # What the task's run returned (set by the caller), for a single run.
        self.result = None
        # How it ended when the caller knows better than the result (SETUP).
        self.ended = None

    def __enter__(self):
        self.outer = depth() == 0 and self.keep and _ring is not None
        _depth.value = depth() + 1
        if self.outer:
            _attach()
            begin(self.task)
        elif depth() > 1:
            _forget_give_up()  # the next task of a batch starts clean
        return self

    def __exit__(self, kind, error, _trace):
        _depth.value = max(0, depth() - 1)
        if not self.outer:
            return False
        from ok.task.exceptions import FinishedException, TaskDisabledException

        if kind is not None and issubclass(kind, FinishedException):
            _drop()
            return False
        if kind is not None and issubclass(kind, TaskDisabledException):
            end(self.task, STOPPED)
        elif kind is not None:
            end(self.task, ERROR, str(error or ""))
        else:
            end(self.task, self.ended, ok=self.result is not False)
        return False


def begin(task) -> None:
    global _current
    with _lock:
        _before.clear()
        _current = {
            "label": str(getattr(task, "name", "") or ""),
            "started": time.time(),
            "thread": threading.get_ident(),
            "problem": None,
        }


def forget_give_up() -> None:
    """The task starts over from 主页: an earlier give-up is not where it stopped."""
    _forget_give_up()


def _forget_give_up() -> None:
    with _lock:
        if _current is not None and _current.get("thread") == threading.get_ident():
            _current.pop("give_up", None)


def _drop() -> None:
    global _current
    with _lock:
        _current = None
        _before.clear()


def note_problem(task, how: str, note: str = "") -> None:
    """A task inside the run failed, threw or was stopped: keep that moment.

    Only the first problem of a run is kept (a later one is often the
    recovery after it).
    """
    with _lock:
        current = _current
        if current is None or current.get("problem") is not None:
            return
        try:
            current["problem"] = _capture(task, how, note, current)
        except Exception as exc:  # never let the record break a run
            logger.error(f"problem report note failed: {exc}")


def _stage(task) -> str:
    try:
        from src.tasks.BaseBD2Task import task_info_snapshot

        info = task_info_snapshot(task)
    except Exception:
        return ""
    name = str(getattr(task, "name", "") or "")
    for key in ("当前阶段", "状态"):
        text = str(info.get(key) or "").strip()
        if text and text != "-":
            if name and text.startswith(name):
                text = text[len(name):].lstrip("：: ")
            return text.rstrip("。.")[:60]
    return ""


def _capture(task, how: str, note: str, current: dict) -> dict:
    now = time.time()
    executor = getattr(task, "executor", None)
    give_up = current.get("give_up") if how == "fail" else None
    if give_up is not None and give_up.get("task") != str(getattr(task, "name", "") or ""):
        give_up = None
    problem = {
        "at": give_up["at"] if give_up is not None else now,
        "how": how,
        "task": str(getattr(task, "name", "") or ""),
        "stage": _stage(task),
        "note": scrub(note)[:120],
        "env": environment(executor),
        "logs": _logs(current, now),
    }
    frame = give_up["frame"] if give_up is not None else _last_frame(executor)
    if frame is not None:
        problem["frame"] = _save_frame(frame, now)
    if how != "stop":  # the player pressed stop: they saw it themselves
        before = _save_before(now, give_up["before"] if give_up is not None else None)
        if before:
            problem["before"] = before
    return problem


def _save_before(now: float, frames: list | None = None) -> list[dict]:
    """The small frames of the seconds before ``now`` (or ``frames``), saved next to the record."""
    if frames is None:
        with _lock:
            frames = [(at, small) for at, small in _before if at <= now - BEFORE_SKIP]
    saved = []
    for index, (at, small) in enumerate(frames, start=1):
        name = _save_frame(small, now, suffix=f"-b{index}", quality=80)
        if name:
            saved.append({"at": at, "file": name})
    return saved


def _logs(current: dict, until: float) -> list[dict]:
    lines = [
        line for line in recent_lines(current.get("started"), current.get("thread"))
        if line[0] <= until + 0.5
    ]
    folded = fold(lines)[-LOG_LINES:]
    return [
        {"at": entry["at"], "level": entry["level"], "text": entry["text"][:120],
         "count": entry["count"]}
        for entry in folded
    ]


def end(task, ended: str | None, error: str = "", ok: bool = True) -> dict | None:
    """Close the run's record and save it; ``ended`` None reads it from the run."""
    global _current
    with _lock:
        current = _current
        _current = None
    if current is None:
        return None
    try:
        return _end(task, current, ended, error, ok)
    except Exception as exc:  # never let the record break a run
        logger.error(f"problem report failed: {exc}")
        return None
    finally:
        with _lock:
            if _current is None:
                _before.clear()


def _end(task, current: dict, ended: str | None, error: str, ok: bool) -> dict:
    now = time.time()
    record = {
        "label": current["label"],
        "started": current["started"],
        "finished": now,
        "problem": current.get("problem"),
    }
    report = None
    if getattr(task, "child_tasks", None):
        try:
            from src.tasks import run_report

            report = run_report.load(current["label"])
        except Exception:
            report = None
        if report and abs(float(report.get("finished") or 0) - now) > 30:
            report = None  # an older run's report
    if report:
        record["finished"] = float(report.get("finished") or now)
        rows = report.get("rows") or []
        record["counts"] = {
            state: sum(1 for row in rows if row.get("state") == state)
            for state in ("done", "skip", "fail")
        }
        ended = ended if ended in (STOPPED, ERROR) else report.get("ended") or ended
        if record["problem"] is None:
            row = _problem_row(rows)
            if row is not None and ended in PROBLEM_ENDS:
                record["problem"] = _capture(task, "fail", "", current)
                record["problem"]["task"] = str(row.get("name") or "")
                record["problem"]["note"] = str(row.get("note") or "")
        elif rows:
            row = next(
                (r for r in rows if r.get("name") == record["problem"].get("task")), None
            )
            if row is not None and row.get("note") and not record["problem"].get("note"):
                record["problem"]["note"] = str(row["note"])
    if ended is None:
        ended = DONE if ok else FAILED
    record["ended"] = ended
    if ended in PROBLEM_ENDS and record["problem"] is None:
        how = {STOPPED: "stop", ERROR: "error"}.get(ended, "fail")
        record["problem"] = _capture(task, how, error, current)
    if record["problem"] is None:
        # A run that went fine still keeps its screen facts and last lines
        # (「没失败但觉得不对劲」), without a frame.
        record["env"] = environment(getattr(task, "executor", None))
        record["logs"] = _logs(current, now)
    _save(record)
    return record


def _problem_row(rows: list[dict]) -> dict | None:
    for row in rows:
        if row.get("state") == "fail":
            return row
    for row in rows:
        if row.get("started") and str(row.get("note") or "").startswith("手动停止"):
            return row
    return None


def env_of(record: dict) -> dict:
    problem = record.get("problem") or {}
    return problem.get("env") or record.get("env") or {}


def logs_of(record: dict) -> list[dict]:
    problem = record.get("problem") or {}
    return problem.get("logs") or record.get("logs") or []

