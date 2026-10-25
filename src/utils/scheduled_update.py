"""定时启动 updates the tool before the run (Leo 2026-10-22 picked 「排程也先更新」).

The Windows task opens the tool itself, not the launcher, so it never got an
update.  Now a scheduled open first asks the launcher for the newest release
(the same question 「检查更新」 asks).  When there is a newer one, this copy
hands over and exits: it opens the launcher with auto update and auto start
on.  The launcher updates the files, then opens the tool, which finds
:data:`PENDING_FILE` and runs as a scheduled open.

The launcher does not open the tool when its update fails, so a one-time
Windows task opens the tool again :data:`RETRY_MINUTES` later.  If the tool
has already run by then, that copy just exits.  If the launcher is still
updating, it waits again, for up to :data:`PENDING_MINUTES` in all.  After
that it runs the version that is there.

Anything that cannot be checked (no launcher in a source checkout, the
launcher already open, no network) keeps the old way: run now, no update.

The 首页 box 「打开工具时自动开始」 does the same when the tool was not opened by
the launcher (a player report 2026-10-25: opening the tool went straight to
一键日常 on the old version).  The launcher updates before it opens the tool,
so only the other ways in need it.  The copy the launcher opens then runs
because the box is ticked, not as a scheduled open.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from src.utils import scheduled_start

PENDING_FILE = Path("configs") / "scheduled_start_pending.json"
RETRY_FLAG = "--scheduled-retry"
RETRY_MINUTES = 10
PENDING_MINUTES = 60
VERSION_TIMEOUT_S = 60
KIND_SCHEDULE = "schedule"
KIND_OPEN = "open"
DAILY_CONFIG = Path("configs") / "DailyBatchTask.json"
OPEN_BOX_KEY = "打开工具时自动开始"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _log(text: str) -> None:
    # Runs before ok's logger exists: a line in logs/ is enough to follow it.
    try:
        Path("logs").mkdir(exist_ok=True)
        with open(Path("logs") / "scheduled-start.log", "a", encoding="utf-8") as file:
            file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
    except OSError:
        pass


def take_retry_flag(argv: list[str]) -> bool:
    if RETRY_FLAG not in argv:
        return False
    argv[:] = [arg for arg in argv if arg != RETRY_FLAG]
    return True


def _parts(version) -> tuple[int, ...] | None:
    text = str(version or "").strip().lstrip("vV")
    pieces = text.split(".")
    if not pieces or not all(piece.isdigit() for piece in pieces):
        return None  # a pre-release or a broken tag
    return tuple(int(piece) for piece in pieces)


def newer_version(versions, current: str | None) -> str | None:
    """The newest release in ``versions`` above ``current``, else None."""
    now = _parts(current)
    if now is None:
        return None
    best = None
    for item in versions or []:
        name = item.get("version") if isinstance(item, dict) else item
        parts = _parts(name)
        if parts is not None and parts > now and (best is None or parts > _parts(best)):
            best = str(name)
    return best


def retry_name(folder: str | None = None) -> str:
    return scheduled_start.task_name(folder).replace("定时启动-", "定时启动补跑-")


def retry_xml(at: datetime, settings: scheduled_start.Settings) -> str:
    trigger = (
        "<TimeTrigger>"
        f"<StartBoundary>{at.strftime('%Y-%m-%dT%H:%M:%S')}</StartBoundary>"
        "<Enabled>true</Enabled>"
        "</TimeTrigger>"
    )
    return scheduled_start.task_xml(
        settings,
        scheduled_start.tool_command(RETRY_FLAG),
        scheduled_start._current_user(),
        triggers=trigger,
    )


def _app_json(app_dir: Path) -> dict:
    from src.compat.launcher_env import read_app_json

    return read_app_json(app_dir / "app.json")


def launcher_running(exe: Path) -> bool:
    try:
        import psutil

        target = os.path.normcase(os.path.abspath(exe))
        for process in psutil.process_iter(["exe"]):
            path = process.info.get("exe")
            if path and os.path.normcase(os.path.abspath(path)) == target:
                return True
    except Exception:
        return False
    return False


def _write_pending(data: dict) -> None:
    PENDING_FILE.parent.mkdir(exist_ok=True)
    PENDING_FILE.write_text(json.dumps(data), encoding="utf-8")


def _read_pending() -> dict | None:
    try:
        data = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _drop_pending(run=subprocess.run) -> None:
    try:
        PENDING_FILE.unlink()
    except OSError:
        pass
    try:
        scheduled_start.remove(run=run, name=retry_name())
    except scheduled_start.TaskError as exc:
        _log(f"retry task not removed: {exc}")


def _age(data: dict, now: datetime) -> timedelta | None:
    try:
        return now - datetime.fromisoformat(data["at"])
    except (KeyError, TypeError, ValueError):
        return None


def auto_run_box_on(config=None) -> bool:
    """The 首页 box 「打开工具时自动开始」, read before ok loads the settings."""
    try:
        data = json.loads(Path(config or DAILY_CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get(OPEN_BOX_KEY) is True


def opened_by_launcher(environ=None) -> bool:
    """The launcher sets this before it opens the tool, after its own update."""
    environ = os.environ if environ is None else environ
    return bool(environ.get("PYAPPIFY_VERSION"))


def update_on_open(script_dir, by_launcher: bool, config=None, clone=None, **kwargs) -> bool:
    """The 首页 box is ticked and the launcher did not open the tool: update first.

    ``by_launcher``: :func:`opened_by_launcher`, read before main.py fills in
    the launcher's variables.  True when the launcher updates and reopens the
    tool; then this copy exits.
    """
    if by_launcher or not auto_run_box_on(config):
        return False
    if clone is None:
        from src.utils.clone_desktop import in_clone as clone
    if clone():
        return False  # the 桌面分身 is given its runs by the open tool
    return hand_to_launcher(script_dir, kind=KIND_OPEN, **kwargs)


def hand_to_launcher(
    script_dir,
    now: datetime | None = None,
    versions=None,
    run=subprocess.run,
    popen=subprocess.Popen,
    running=launcher_running,
    kind: str = KIND_SCHEDULE,
) -> bool:
    """A scheduled open: True when the launcher updates and reopens the tool.

    Then this copy exits.  False: run now, as before.
    """
    from src.compat.launcher_env import find_install

    now = now or scheduled_start.local_now()
    install = find_install(script_dir)
    if install is None:
        return False  # a source checkout: nothing to update through
    exe, app_dir = install
    if running(exe):
        _log("launcher already open: no update this time")
        return False
    current = _app_json(app_dir).get("current_version")
    try:
        if versions is None:
            import pyappify

            versions = pyappify.get_version_list(release_only=True, timeout=VERSION_TIMEOUT_S)
    except Exception as exc:
        _log(f"update check failed ({exc}): run without updating")
        return False
    target = newer_version(versions, current)
    if target is None:
        _log(f"{current} is the newest release")
        return False
    settings = scheduled_start.load()
    try:
        scheduled_start.register(
            retry_name(), retry_xml(now + timedelta(minutes=RETRY_MINUTES), settings), run=run
        )
    except scheduled_start.TaskError as exc:
        _log(f"retry task not set ({exc}): run without updating")
        return False
    try:
        _write_pending({"at": now.isoformat(), "from": current, "to": target, "kind": kind})
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        popen(
            [str(exe), "--auto-start", "true", "--update-method", "auto"],
            cwd=str(exe.parent),
            creationflags=flags,
            close_fds=True,
        )
    except OSError as exc:
        _log(f"launcher not opened ({exc}): run without updating")
        _drop_pending(run=run)
        return False
    _log(f"update {current} -> {target}: the launcher updates and reopens the tool")
    return True


def take_pending(now: datetime | None = None, run=subprocess.run) -> bool:
    """The launcher reopened the tool after the update: a scheduled open.

    After an update from the 首页 box it is an ordinary open (False): the
    ticked box starts the run.
    """
    data = _read_pending()
    if data is None:
        return False
    now = now or scheduled_start.local_now()
    age = _age(data, now)
    _drop_pending(run=run)
    if data.get("kind") == KIND_OPEN:
        _log(f"opened after the update ({data.get('to')}): the 首页 box starts the run")
        return False
    fresh = age is not None and timedelta(0) <= age <= timedelta(minutes=PENDING_MINUTES)
    _log(f"opened after the update ({data.get('to')}): {'run' if fresh else 'too late, no run'}")
    return fresh


def on_retry(
    script_dir,
    now: datetime | None = None,
    run=subprocess.run,
    running=launcher_running,
) -> bool:
    """The one-time task came: True to run now, False when nothing is left to do."""
    from src.compat.launcher_env import find_install

    now = now or scheduled_start.local_now()
    data = _read_pending()
    if data is None:
        return False  # the launcher reopened the tool and the run happened
    age = _age(data, now) or timedelta(0)
    install = find_install(script_dir)
    updating = (
        install is not None
        and running(install[0])
        and _app_json(install[1]).get("update_state") == "updating"
    )
    if updating and age < timedelta(minutes=PENDING_MINUTES - RETRY_MINUTES):
        try:
            scheduled_start.register(
                retry_name(),
                retry_xml(now + timedelta(minutes=RETRY_MINUTES), scheduled_start.load()),
                run=run,
            )
            _log("still updating: look again later")
            return False
        except scheduled_start.TaskError as exc:
            _log(f"retry task not set again ({exc}): run now")
    _drop_pending(run=run)
    _log("the launcher did not reopen the tool: run the version that is there")
    return True
