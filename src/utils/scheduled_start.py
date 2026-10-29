"""定时启动: at times the player sets, open the tool and run 一键日常 (Leo 2026-10-22).

The player sets time slots on 首页 (each with its own time and weekdays, or
「游戏每天重置后」 that follows the game's 08:00 UTC+8 reset).  The tool
registers one task in Windows 任务计划程序 with a trigger per slot, so the
tool may be closed and a sleeping PC is woken; turning 定时启动 off deletes
the task, nothing is left behind (Leo: 「也要在上面可以完全取消」).

The task starts the tool with :data:`FLAG`; it then counts down on 首页 and
runs only what is left today, as 「打开就自动跑日常」 does.  When the tool is
already open, the task's copy exits without a word and the open tool starts
the run itself (:func:`due_between`), so nothing pops up and nothing runs
twice.  This module has no Qt and no ok-script, main.py reads it early.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from src.utils.game_day import DAILY_REFRESH_HOUR, GAME_TZ

FLAG = "--scheduled-start"
SETTINGS_FILE = Path("configs") / "scheduled_start.json"
TASK_FOLDER = "YES-BD2"
# 「游戏每天重置后」 starts this long after the reset: the server needs a
# moment and the reset popups come first.
RESET_DELAY_MINUTES = 5
# The open tool starts a slot it noticed this late at the latest; a PC that
# slept through a slot and was woken by the player later does not start then.
LATE_LIMIT = timedelta(minutes=5)
MAX_SLOTS = 5  # Leo 2026-10-22 「最多可以設定5個時間」: per 帳號
# All 帳號 together (accounts.MAX_ACCOUNTS of them).
MAX_ALL_SLOTS = MAX_SLOTS * 5
# Minutes come in quarters (Leo 2026-10-22 「分鐘改成每15分鐘間隔」).
MINUTE_STEP = 15
# Two slots at least this far apart (Leo 2026-10-22 picked 「擋下來」 for
# slots under an hour apart, and 「時間不可以衝突吧」 for the same time).
MIN_GAP_MINUTES = 60
# Two 帳號 at least this far apart (Leo 2026-10-29 「不同帳號 也要間隔至少
# 半小時」); the second waits for the first run to end all the same.
MIN_GAP_OTHER_MINUTES = 30
DAY_MINUTES = 24 * 60
WEEK_MINUTES = 7 * DAY_MINUTES


def _current_account() -> str:
    try:
        from src.utils import accounts

        return accounts.current_id()
    except Exception:
        return ""


def _apart(a: int, b: int) -> int:
    gap = abs(a - b) % WEEK_MINUTES
    return min(gap, WEEK_MINUTES - gap)
KIND_RESET = "reset"
KIND_TIME = "time"
DAY_TAGS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# powercfg: 「允许使用唤醒定时器」 (0 off, 1 on, 2 important ones only).
SUB_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
RTC_WAKE = "bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d"
CREATE_NO_WINDOW = 0x08000000

# The tool was opened by the task (main.py takes the flag off sys.argv, so a
# language change or the 桌面分身 does not start a run again).
launched_by_schedule = False
# When the task opened it: after an update the launcher opens it again later,
# and the slot (its 帳號) is the one that fired then.  None = just now.
opened_at: datetime | None = None
# 定时启动 started 一键日常 and its run has not begun yet (it may wait for the
# login first); DailyBatchTask takes it when the run begins.
_run_pending = False
# The items that run picks (a slot's own list), None = the 帳號's ticks.
_run_tasks: list[str] | None = None
# Item -> its settings for that run only (镜中之战's 倍数 ...).
_run_settings: dict[str, dict] = {}
# Other 帳號 waiting to run right after this one (autorun's line): 做完关闭
# 游戏 / 做完关机 wait for the last.
queued = 0


def mark_run_pending(
    pending: bool = True,
    tasks: list[str] | None = None,
    settings: dict[str, dict] | None = None,
) -> None:
    global _run_pending, _run_tasks, _run_settings
    _run_pending = pending
    _run_tasks = list(tasks) if pending and tasks is not None else None
    _run_settings = {k: dict(v) for k, v in (settings or {}).items()} if pending else {}


def take_run_settings() -> dict[str, dict]:
    """Once: each item's own settings for the scheduled run ({} = none)."""
    global _run_settings
    settings, _run_settings = _run_settings, {}
    return settings


def take_run_tasks() -> list[str] | None:
    """Once: the items the scheduled run does (None = the ticks as they are)."""
    global _run_tasks
    tasks, _run_tasks = _run_tasks, None
    return tasks


def take_run_pending() -> bool:
    """True once for the run 定时启动 started."""
    global _run_pending
    pending, _run_pending = _run_pending, False
    return pending


@dataclass
class Slot:
    kind: str = KIND_TIME
    hour: int = 21
    minute: int = 0
    days: list[int] = field(default_factory=lambda: list(range(7)))  # 0 = Monday
    on: bool = True
    # Which 帳號 this slot runs, with its own ticks (YES-BD2 #64, Leo
    # 2026-10-28: one 帳號 at one time, another at another); "" = the current one.
    account: str = ""
    # What it runs (Leo 2026-10-29 「也要選擇該時段進行的任務」): 一键日常's
    # item names; None = what the 帳號 has ticked.
    tasks: list[str] | None = None
    # Item -> {setting: value} for this slot's runs only (Leo 2026-10-29
    # 「鏡中之戰也可以選倍數那些」); the items' own settings stay as they are.
    settings: dict[str, dict] = field(default_factory=dict)

    def to_json(self) -> dict:
        if self.kind == KIND_RESET:
            return {"kind": KIND_RESET, "on": self.on}
        value = {
            "kind": KIND_TIME,
            "time": f"{self.hour:02d}:{self.minute:02d}",
            "days": sorted(set(self.days)),
            "on": self.on,
        }
        if self.account:
            value["account"] = self.account
        if self.tasks is not None:
            value["tasks"] = list(self.tasks)
        if self.settings:
            value["settings"] = {k: dict(v) for k, v in self.settings.items() if v}
        return value

    @classmethod
    def from_json(cls, value: dict) -> Slot | None:
        if not isinstance(value, dict):
            return None
        on = bool(value.get("on", True))
        if value.get("kind") == KIND_RESET:
            # 「游戏每天重置后」 is gone (Leo 2026-10-22 「預設每天重製那個要去掉」).
            return None
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value.get("time", "")))
        if not match:
            return None
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        days = sorted({d for d in value.get("days", []) if isinstance(d, int) and 0 <= d <= 6})
        account = value.get("account", "")
        account = account if isinstance(account, str) else ""
        tasks = value.get("tasks")
        if isinstance(tasks, list):
            tasks = [str(task) for task in tasks if isinstance(task, str)]
        else:
            tasks = None
        settings = value.get("settings")
        settings = {
            str(item): dict(own)
            for item, own in (settings.items() if isinstance(settings, dict) else ())
            if isinstance(own, dict) and own
        }
        return cls(KIND_TIME, hour, snap_minute(minute), days, on, account, tasks, settings)

    def week_minutes(self) -> list[int]:
        """When it fires, as minutes from Monday 00:00."""
        return [day * DAY_MINUTES + self.hour * 60 + self.minute for day in self.days]

    def runs(self, current: str) -> str:
        """The 帳號 it runs, "" (the current one) read as ``current``."""
        return self.account or current

    def clashes_with(self, other: Slot, current: str | None = None) -> bool:
        """Both on and too close on some day (over midnight too): under
        ``MIN_GAP_MINUTES`` for the same 帳號 (its run would still be going),
        under ``MIN_GAP_OTHER_MINUTES`` for two 帳號 (Leo 2026-10-29 「同時段
        同帳號不能重疊 不同帳號可以」「不同帳號 也要間隔至少半小時」: the
        later one waits for the run before it).  ``current``: the 帳號 ""
        stands for (None = now's)."""
        if not (self.on and other.on):
            return False
        if current is None:
            current = _current_account()
        same = self.runs(current) == other.runs(current)
        gap = MIN_GAP_MINUTES if same else MIN_GAP_OTHER_MINUTES
        return any(
            _apart(mine, theirs) < gap
            for mine in self.week_minutes()
            for theirs in other.week_minutes()
        )

    def active(self) -> bool:
        return self.on and (self.kind == KIND_RESET or bool(self.days))


@dataclass
class Settings:
    enabled: bool = False
    wake: bool = True
    # No slot until the player adds one (Leo 2026-10-22 「預設的8:05不要」).
    slots: list[Slot] = field(default_factory=list)
    # For a scheduled run only, on top of 一键日常's own settings: Leo
    # 2026-10-22 「設定好定時就不管他」, so the game closes after a clean run.
    close_game: bool = True
    shutdown: bool = False
    # 帳號 switched off on the week calendar (Leo 2026-10-29 「點帳號可以讓
    # 該帳號變淺變深 變淺該帳號行程隱藏(失效)」): their slots do not run.
    paused: list[str] = field(default_factory=list)
    migrated: bool = field(default=False, compare=False, repr=False)

    def to_json(self) -> dict:
        return {
            "enabled": self.enabled,
            "wake": self.wake,
            "close_game": self.close_game,
            "shutdown": self.shutdown,
            "slots": [slot.to_json() for slot in self.slots],
            **({"paused": list(self.paused)} if self.paused else {}),
        }

    @classmethod
    def from_json(cls, value: dict) -> Settings:
        if not isinstance(value, dict):
            return cls()
        stored = value.get("slots", [])
        slots, per_account = [], {}
        for slot in (Slot.from_json(v) for v in stored):
            if slot and per_account.get(slot.account, 0) < MAX_SLOTS:
                per_account[slot.account] = per_account.get(slot.account, 0) + 1
                slots.append(slot)
        slots = slots[:MAX_ALL_SLOTS]
        settings = cls(
            bool(value.get("enabled", False)),
            bool(value.get("wake", True)),
            slots,
            bool(value.get("close_game", True)),
            bool(value.get("shutdown", False)),
            [str(each) for each in value.get("paused") or [] if each],
        )
        # A dropped 「游戏每天重置后」 or a minute moved to its quarter: the
        # file and the Windows task are written again (schedule_ui).
        settings.migrated = [slot.to_json() for slot in slots] != stored
        return settings

    def active_slots(self) -> list[Slot]:
        if not self.enabled:
            return []
        current = _current_account() if self.paused else ""
        return [
            slot
            for slot in self.slots
            if slot.active() and slot.runs(current) not in self.paused
        ]


def snap_minute(minute: int) -> int:
    """The quarter closest to ``minute`` inside its hour (07 → 00, 53 → 45)."""
    return min(round(minute / MINUTE_STEP) * MINUTE_STEP, 60 - MINUTE_STEP)


def free_time(slots: list[Slot]) -> tuple[int, int]:
    """For a new slot (every day): the first whole hour from 21:00 that is an
    hour or more from every slot."""
    for step in range(24):
        hour = (21 + step) % 24
        if not any(Slot(KIND_TIME, hour, 0).clashes_with(slot) for slot in slots):
            return hour, 0
    return 21, 0  # not reachable with MAX_SLOTS slots


def slot_problems(slots: list[Slot]) -> list[str]:
    """Why each slot cannot be saved as it is ('' when fine), in the slots' order."""
    found = []
    for index, slot in enumerate(slots):
        if slot.on and not slot.days:
            found.append("没选星期，这个时段不会跑")
        elif any(slot.clashes_with(other) for n, other in enumerate(slots) if n != index):
            found.append(_clash_note(slot, slots, index))
        else:
            found.append("")
    return found


def _clash_note(slot: Slot, slots: list[Slot], index: int) -> str:
    current = _current_account()
    same = any(
        other.runs(current) == slot.runs(current) and slot.clashes_with(other, current)
        for n, other in enumerate(slots)
        if n != index
    )
    if same:
        return "同一个账号的另一个时段隔不到 1 小时，请错开"
    return "和别的账号的时段隔不到半小时，请错开"


def load(path: Path = SETTINGS_FILE) -> Settings:
    from src.compat.safe_json import read_text_retrying

    try:
        return Settings.from_json(json.loads(read_text_retrying(path)))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError):
        return Settings()


def save(settings: Settings, path: Path = SETTINGS_FILE) -> None:
    from src.compat.safe_json import write_text_atomic

    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(settings.to_json(), ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- times


def local_now() -> datetime:
    return datetime.now().astimezone()


def reset_moment(day: datetime) -> datetime:
    """The 「游戏每天重置后」 start on the game day that begins on ``day``'s date (UTC+8)."""
    game = day.astimezone(GAME_TZ).replace(
        hour=DAILY_REFRESH_HOUR, minute=RESET_DELAY_MINUTES, second=0, microsecond=0
    )
    return game.astimezone(day.tzinfo)


def reset_clock(now: datetime | None = None) -> tuple[int, int]:
    """「游戏每天重置后」 on the player's clock (Taiwan: 08:05)."""
    moment = reset_moment(now or local_now())
    return moment.hour, moment.minute


def slot_moments(slot: Slot, start: datetime, end: datetime) -> list[datetime]:
    """When ``slot`` fires in (``start``, ``end``], both aware local times."""
    found = []
    day = start - timedelta(days=1)
    while day.date() <= end.date() + timedelta(days=1):
        if slot.kind == KIND_RESET:
            moment = reset_moment(day.replace(hour=12))
        elif day.weekday() in slot.days:
            moment = day.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
        else:
            moment = None
        if moment is not None and start < moment <= end:
            found.append(moment)
        day += timedelta(days=1)
    return sorted(set(found))


def next_run(settings: Settings, now: datetime | None = None) -> datetime | None:
    now = now or local_now()
    moments = [
        moment
        for slot in settings.active_slots()
        for moment in slot_moments(slot, now, now + timedelta(days=8))
    ]
    return min(moments) if moments else None


def due_between(settings: Settings, last: datetime, now: datetime) -> datetime | None:
    """A slot that came in (``last``, ``now``] and is not too late to start."""
    moments = [
        moment
        for slot in settings.active_slots()
        for moment in slot_moments(slot, last, now)
        if now - moment <= LATE_LIMIT
    ]
    return max(moments) if moments else None


def slots_at(settings: Settings, moment: datetime) -> list[Slot]:
    """The slots that fired last at or before ``moment``: the ones that
    opened the tool (its start may come late after an update).  Several
    when 帳號 share a time; they run one after the other, in their order."""
    found = [
        (fired, slot)
        for slot in settings.active_slots()
        for fired in slot_moments(slot, moment - timedelta(days=8), moment)
    ]
    if not found:
        return []
    last = max(fired for fired, _slot in found)
    return [slot for fired, slot in found if fired == last]


def slot_at(settings: Settings, moment: datetime) -> Slot | None:
    """The first of :func:`slots_at`."""
    slots = slots_at(settings, moment)
    return slots[0] if slots else None


def account_at(settings: Settings, moment: datetime) -> str:
    """The 帳號 the slot at ``moment`` runs ("" = the current one)."""
    slot = slot_at(settings, moment)
    return slot.account if slot is not None else ""


def tasks_at(settings: Settings, moment: datetime) -> list[str] | None:
    """What the slot at ``moment`` runs (None = the 帳號's ticks)."""
    slot = slot_at(settings, moment)
    return None if slot is None or slot.tasks is None else list(slot.tasks)


def item_settings_at(settings: Settings, moment: datetime) -> dict[str, dict]:
    """The slot's own settings per item ({} = the items' own)."""
    slot = slot_at(settings, moment)
    return {k: dict(v) for k, v in slot.settings.items()} if slot is not None else {}


def jobs_at(settings: Settings, moment: datetime) -> list[dict]:
    """What each slot at ``moment`` runs, for ``autorun.schedule``: one per
    帳號 (the first slot of a 帳號 wins), in the slots' order."""
    jobs, seen = [], set()
    for slot in slots_at(settings, moment):
        if slot.account in seen:
            continue
        seen.add(slot.account)
        jobs.append(
            {
                "account": slot.account,
                "tasks": None if slot.tasks is None else list(slot.tasks),
                "item_settings": {k: dict(v) for k, v in slot.settings.items()},
            }
        )
    return jobs


# ---------------------------------------------------------------- Windows task


def task_name(folder: str | None = None) -> str:
    """One task per install folder (two installs keep their own)."""
    folder = os.getcwd() if folder is None else folder
    digest = hashlib.md5(
        os.path.normcase(os.path.abspath(folder)).encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:8]
    return f"\\{TASK_FOLDER}\\定时启动-{digest}"


def tool_command(*extra: str) -> tuple[str, str, str]:
    """(program, arguments, folder) that open this tool without a console window."""
    program = sys.executable
    if os.path.basename(program).lower() == "python.exe":
        windowless = os.path.join(os.path.dirname(program), "pythonw.exe")
        if os.path.exists(windowless):
            program = windowless
    if getattr(sys, "frozen", False):
        arguments = [FLAG, *extra]
    else:
        arguments = [os.path.abspath(sys.argv[0]), FLAG, *extra]
    return program, subprocess.list2cmdline(arguments), os.getcwd()


def _trigger(slot: Slot, now: datetime) -> str:
    if slot.kind == KIND_RESET:
        # With the +08:00 offset Windows keeps it on the game's reset in any
        # time zone and across daylight saving.
        start = now.astimezone(GAME_TZ).replace(
            hour=DAILY_REFRESH_HOUR, minute=RESET_DELAY_MINUTES, second=0, microsecond=0
        )
        return (
            "<CalendarTrigger>"
            f"<StartBoundary>{start.strftime('%Y-%m-%dT%H:%M:%S')}+08:00</StartBoundary>"
            "<Enabled>true</Enabled>"
            "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
            "</CalendarTrigger>"
        )
    start = now.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
    days = "".join(f"<{DAY_TAGS[day]} />" for day in sorted(set(slot.days)))
    return (
        "<CalendarTrigger>"
        f"<StartBoundary>{start.strftime('%Y-%m-%dT%H:%M:%S')}</StartBoundary>"
        "<Enabled>true</Enabled>"
        "<ScheduleByWeek>"
        f"<DaysOfWeek>{days}</DaysOfWeek><WeeksInterval>1</WeeksInterval>"
        "</ScheduleByWeek>"
        "</CalendarTrigger>"
    )


def task_xml(
    settings: Settings,
    command: tuple[str, str, str],
    user: str,
    now: datetime | None = None,
    triggers: str | None = None,
) -> str:
    """The Windows task; ``triggers`` replaces the slots' own (a one-time retry)."""
    now = now or local_now()
    program, arguments, folder = command
    if triggers is None:
        triggers = "".join(_trigger(slot, now) for slot in settings.active_slots())
    wake = "true" if settings.wake else "false"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>YES-BD2</Author>
    <Description>YES-BD2 定时启动：打开工具并跑今天还没做的日常。在 YES-BD2 首页「定时启动」关掉就会删除。</Description>
  </RegistrationInfo>
  <Triggers>{triggers}</Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>{wake}</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(program)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(folder)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


class TaskError(Exception):
    """Windows did not take the change; the text says why, for the player."""


def _schtasks(*arguments: str, run=subprocess.run) -> subprocess.CompletedProcess:
    return run(
        ["schtasks", *arguments],
        capture_output=True,
        text=True,
        encoding="mbcs" if sys.platform == "win32" else "utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        timeout=30,
    )


def _current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    name = os.environ.get("USERNAME", "")
    return f"{domain}\\{name}" if domain else name


def apply(settings: Settings, run=subprocess.run) -> None:
    """Make the Windows task match ``settings``: none when off or no slot is on."""
    if not settings.active_slots():
        remove(run=run)
        return
    register(task_name(), task_xml(settings, tool_command(), _current_user()), run=run)


def register(name: str, xml: str, run=subprocess.run) -> None:
    """Create (or replace) the Windows task ``name`` from ``xml``."""
    handle, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(handle, "w", encoding="utf-16") as file:
            file.write(xml)
        result = _schtasks("/Create", "/TN", name, "/XML", path, "/F", run=run)
    except (OSError, subprocess.SubprocessError) as exc:
        raise TaskError(str(exc)) from exc
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if result.returncode != 0:
        raise TaskError((result.stderr or result.stdout or "").strip())


def remove(run=subprocess.run, name: str | None = None) -> None:
    """Delete the task; nothing to delete is fine."""
    name = task_name() if name is None else name
    try:
        if _schtasks("/Query", "/TN", name, run=run).returncode != 0:
            return
        result = _schtasks("/Delete", "/TN", name, "/F", run=run)
    except (OSError, subprocess.SubprocessError) as exc:
        raise TaskError(str(exc)) from exc
    if result.returncode != 0:
        raise TaskError((result.stderr or result.stdout or "").strip())


# ---------------------------------------------------------------- wake timers


def _powercfg(*arguments: str, run=subprocess.run) -> subprocess.CompletedProcess:
    return run(
        ["powercfg", *arguments],
        capture_output=True,
        text=True,
        encoding="mbcs" if sys.platform == "win32" else "utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        timeout=15,
    )


def wake_timer_index(output: str) -> int | None:
    """The plugged-in value of 「允许使用唤醒定时器」 from ``powercfg /query``.

    The labels are in the Windows language; the current AC and DC values are
    the last two 0x numbers of the setting.
    """
    values = re.findall(r"0x([0-9a-fA-F]{8})", output)
    if len(values) < 2:
        return None
    return int(values[-2], 16)


def ensure_wake_timers(run=subprocess.run) -> bool | None:
    """Turn on wake timers for the current power plan when they are off.

    The player ticked 「电脑睡着时叫醒它」, which needs them.  True when they
    are on (or were turned on), False when Windows refused, None when it
    could not be read (not Windows).
    """
    try:
        query = _powercfg("/query", "SCHEME_CURRENT", SUB_SLEEP, RTC_WAKE, run=run)
    except (OSError, subprocess.SubprocessError):
        return None
    index = wake_timer_index(query.stdout or "")
    if index is None:
        return None
    if index == 1:
        return True
    try:
        changed = _powercfg(
            "/setacvalueindex", "SCHEME_CURRENT", SUB_SLEEP, RTC_WAKE, "1", run=run
        ).returncode == 0
        changed = changed and _powercfg(
            "/setdcvalueindex", "SCHEME_CURRENT", SUB_SLEEP, RTC_WAKE, "1", run=run
        ).returncode == 0
        changed = changed and _powercfg("/setactive", "SCHEME_CURRENT", run=run).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    return changed


def screen_locked() -> bool:
    """Windows shows the lock screen: no input reaches the game then.

    A PC woken from sleep often waits at it for the password.  Not Windows,
    or not readable: False.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = ctypes.c_void_p
        desktop = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not desktop:
            return True
        try:
            return not user32.SwitchDesktop(ctypes.c_void_p(desktop))
        finally:
            user32.CloseDesktop(ctypes.c_void_p(desktop))
    except Exception:
        return False


def take_flag(argv: list[str]) -> bool:
    """Remove :data:`FLAG` from ``argv``; True when it was there."""
    if FLAG not in argv:
        return False
    argv[:] = [arg for arg in argv if arg != FLAG]
    return True
