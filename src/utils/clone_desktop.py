"""桌面分身: the game and the tool on a second desktop of the same Windows user.

The clone desktop is a Windows child session with its own mouse and
keyboard, so a run there never takes the user's mouse (BetterGI's 桌面分身
works the same way).  ``tools/clone_desktop/setup.ps1`` does the one-time
setup with one UAC prompt, and ``CloneDesktop.exe`` (built by it) shows the
clone desktop in a window and, after sign-in, starts this tool inside it.
首页's 「在桌面分身跑」 button starts it (Leo, 2026-10-03).
"""

from __future__ import annotations

import ctypes
import functools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO / "tools" / "clone_desktop" / "setup.ps1"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "bd2-auto" / "clone-desktop"
VIEWER = DATA_DIR / "CloneDesktop.exe"
# Written by the viewer: "started", "running PID" or "failed WHY".
LAUNCH_RESULT = DATA_DIR / "launch-result.txt"
# Written by setup.ps1 at the first setup, deleted by 还原.
SETUP_STATE = DATA_DIR / "setup-state.json"
# One task handed from a start button outside to the tool started in the clone.
JOB_FILE = DATA_DIR / "pending-run.json"
# The run in the clone, as the tool outside shows it (Leo, 2026-10-03 13:17:
# everything is watched and operated on the real desktop).
STATUS_FILE = DATA_DIR / "clone-status.json"
LIVE_FILE = DATA_DIR / "clone-live.jpg"
# "pause", "resume" or "stop" from the tool outside, done once by the tool inside.
CONTROL_FILE = DATA_DIR / "clone-control.txt"
MODES = ("normal", "clone")


def _read_hklm(path: str, name: str):
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except (ImportError, OSError):
        return None


def supported() -> bool:
    """Windows Home (EditionID Core...) has no child sessions."""
    edition = _read_hklm(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "EditionID")
    return bool(edition) and not str(edition).startswith("Core")


def child_sessions_enabled() -> bool:
    try:
        enabled = ctypes.c_int(0)
        ok = ctypes.windll.wtsapi32.WTSIsChildSessionsEnabled(ctypes.byref(enabled))
    except (AttributeError, OSError):
        return False
    return bool(ok) and bool(enabled.value)


def ready() -> bool:
    """The one-time setup is done: the viewer is built and child sessions are on."""
    return VIEWER.exists() and child_sessions_enabled()


def viewer_removed() -> bool:
    """Set up once, but CloneDesktop.exe is gone: most likely an antivirus took it.

    The tool builds that program on the player's PC, so antivirus programs
    such as 360 or 火绒 may see an unknown program and remove it (review
    2026-10-09).
    """
    return SETUP_STATE.exists() and not VIEWER.exists()


def hello_only() -> bool:
    """A Microsoft account limited to Windows Hello cannot sign in to the clone."""
    value = _read_hklm(
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device",
        "DevicePasswordLessBuildVersion",
    )
    return value == 2


def viewer_running() -> bool:
    try:
        import psutil

        return any(
            (process.info.get("name") or "").lower() == "clonedesktop.exe"
            for process in psutil.process_iter(["name"])
        )
    except Exception:
        return False


def _session_of(pid: int) -> int | None:
    try:
        session = ctypes.c_ulong(0)
        if not ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(session)):
            return None
    except (AttributeError, OSError):
        return None
    return session.value


def _console_session() -> int | None:
    try:
        return ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
    except (AttributeError, OSError):
        return None


def _viewer_in_other_session(own: int) -> bool:
    """CloneDesktop.exe runs in a session other than ``own`` (the clone's parent)."""
    try:
        import psutil

        processes = list(psutil.process_iter(["pid", "name"]))
    except Exception:
        return False
    for process in processes:
        if (process.info.get("name") or "").lower() != "clonedesktop.exe":
            continue
        session = _session_of(process.info["pid"])
        if session is None or session != own:
            return True
    return False


@functools.lru_cache(maxsize=1)
def in_clone() -> bool:
    """True when this process itself runs on the clone desktop.

    Not the console session is not enough: a player who opens the tool over
    ordinary Remote Desktop is not on the console either, and there the tool
    must still ask for Administrator, stay on screen, stop on a key press and
    leave the startup programs (Steam, Discord...) alone.  The clone exists
    only while its window (CloneDesktop.exe) is open in another session.  A
    process never changes session, so the answer is kept.
    """
    own = _session_of(os.getpid())
    console = _console_session()
    if own is None or console is None or own == console:
        return False
    return _viewer_in_other_session(own)


def child_session_id() -> int | None:
    try:
        session = ctypes.c_ulong(0)
        if not ctypes.windll.wtsapi32.WTSGetChildSessionId(ctypes.byref(session)):
            return None
    except (AttributeError, OSError):
        return None
    return session.value if session.value not in (0, 0xFFFFFFFF) else None


GAME_NAMES = {"browndust ii.exe"}


def _tool_names() -> set[str]:
    return {os.path.basename(sys.executable).lower(), "python.exe", "pythonw.exe"}


def _in_clone_session(names: set[str]) -> bool:
    """A process named one of ``names`` runs on the 桌面分身 (seen from outside)."""
    child = child_session_id()
    if child is None or in_clone():
        return False
    try:
        import psutil
    except ImportError:
        return False
    for process in psutil.process_iter(["pid", "name"]):
        if (process.info.get("name") or "").lower() not in names:
            continue
        session = ctypes.c_ulong(0)
        if ctypes.windll.kernel32.ProcessIdToSessionId(process.info["pid"], ctypes.byref(session)):
            if session.value == child:
                return True
    return False


def tool_running_in_clone() -> bool:
    """The tool is open on the 桌面分身 (seen from the user's own desktop), busy or not."""
    return _in_clone_session(_tool_names())


def clone_open() -> bool:
    """The 桌面分身 still has the tool or the game in it (seen from outside)."""
    return _in_clone_session(_tool_names() | GAME_NAMES)


def end_clone(timeout: float = 20.0) -> bool:
    """From outside: close the viewer and sign out the 桌面分身, as its X does.

    The game and the tool in it close with it.  The viewer goes first, or it
    would sign in to a new clone right after the sign-out.  True once nothing
    of the tool or the game is left in the clone.
    """
    child = child_session_id()
    if child is None or in_clone():
        return True
    try:
        import psutil
    except ImportError:
        return False
    for process in psutil.process_iter(["name"]):
        if (process.info.get("name") or "").lower() != "clonedesktop.exe":
            continue
        try:
            process.terminate()
            process.wait(5)
        except psutil.NoSuchProcess:
            pass
        except Exception:
            return False
    try:
        subprocess.run(
            ["logoff", str(child)],
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not clone_open():
            return True
        time.sleep(0.5)
    return False


def run_setup(undo: bool = False) -> None:
    """Open a console window running setup.ps1; it asks for Administrator itself."""
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SETUP_SCRIPT),
    ]
    if undo:
        command.append("-Undo")
    subprocess.Popen(command, cwd=str(REPO), creationflags=subprocess.CREATE_NEW_CONSOLE)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _tool_command() -> tuple[str, str]:
    """How this tool was started, to start it the same way inside the clone."""
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(sys.argv[1:])
    script = os.path.abspath(sys.argv[0])
    return sys.executable, subprocess.list2cmdline([script, *sys.argv[1:]])


VIEWER_SOURCE = REPO / "tools" / "clone_desktop" / "CloneDesktop.cs"


def update_viewer() -> None:
    """Rebuild the viewer when the tool brings a newer one (no Administrator needed).

    Same compiler and options as setup.ps1; skipped while the viewer is open.
    """
    try:
        if not VIEWER.exists() or VIEWER.stat().st_mtime >= VIEWER_SOURCE.stat().st_mtime:
            return
    except OSError:
        return
    if viewer_running():
        return
    windir = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    csc = windir / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if not csc.exists():
        csc = windir / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"
    built = VIEWER.with_suffix(".new.exe")
    command = [
        str(csc),
        "/nologo",
        "/codepage:65001",
        "/target:winexe",
        f"/out:{built}",
        "/r:System.Windows.Forms.dll",
        "/r:System.Drawing.dll",
        "/r:Microsoft.CSharp.dll",
        "/r:System.Core.dll",
        "/r:System.Management.dll",
        str(VIEWER_SOURCE),
    ]
    try:
        subprocess.run(
            command,
            capture_output=True,
            timeout=120,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        os.replace(built, VIEWER)
    except (OSError, subprocess.SubprocessError):
        # Keep the old viewer; it still works.
        try:
            built.unlink()
        except OSError:
            pass


def open_viewer(launch_tool: bool = True) -> bool:
    """Open the clone desktop; after sign-in the viewer starts this tool in it.

    The tool needs Administrator to start the game, and "Run as
    administrator" does not work inside the clone, so a tool that is not
    elevated opens the viewer through one Windows confirmation and the viewer
    starts the tool elevated.  False when the user said no to it.
    """
    try:
        LAUNCH_RESULT.unlink()
    except OSError:
        pass
    update_viewer()
    write_startup_list()
    args = []
    if launch_tool:
        exe, arguments = _tool_command()
        args = ["-launch", exe, "-args", arguments, "-cwd", os.getcwd()]
    try:
        from src.compat.starter_launch import starter_launch_uri

        # 搬回桌面 on close opens the game the way the official shortcut does.
        args += ["-move", starter_launch_uri()]
    except Exception:
        pass
    open_failure["why"] = ""
    if is_admin():
        try:
            subprocess.Popen([str(VIEWER), *args], cwd=str(DATA_DIR))
        except OSError:
            # Missing, or an antivirus refused to start it.
            open_failure["why"] = "blocked"
            return False
        return True
    shell_execute = ctypes.windll.shell32.ShellExecuteW
    shell_execute.restype = ctypes.c_void_p
    result = shell_execute(
        None, "runas", str(VIEWER), subprocess.list2cmdline(args), str(DATA_DIR), 1
    )
    if (result or 0) > 32:
        return True
    # 5 (access denied) is the user's 「否」; anything else kept it from starting.
    open_failure["why"] = "declined" if result == 5 else "blocked"
    return False


# Why the last open_viewer() returned False: "declined" or "blocked".
open_failure = {"why": ""}


def launch_result() -> str | None:
    """What the viewer reported about starting the tool, None while it has not."""
    try:
        return LAUNCH_RESULT.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def open_sign_in_options() -> None:
    os.startfile("ms-settings:signinoptions")


def request_job(task: str, run_mode: str | None = None, by_player: bool = True) -> None:
    """``by_player`` False: 打开就自动跑 handed it over, not a press (a job
    file without the key is a press, as before)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    job = {"task": task, "run_mode": run_mode, "at": time.time()}
    if not by_player:
        job["by_player"] = False
    JOB_FILE.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")


def write_atomic(path: Path, payload: bytes) -> None:
    """Replace ``path`` in one step so the reader never sees half a file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(payload)
    os.replace(temp, path)


def read_status(max_age: float) -> dict | None:
    """The clone's last published run state, None when missing or older than ``max_age``."""
    try:
        status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(status, dict) or time.time() - float(status.get("at", 0)) > max_age:
        return None
    return status


def send_control(command: str) -> None:
    write_atomic(CONTROL_FILE, command.encode("utf-8"))


def take_control() -> str | None:
    try:
        command = CONTROL_FILE.read_text(encoding="utf-8").strip()
        CONTROL_FILE.unlink()
    except OSError:
        return None
    return command or None


def job_waiting(max_age: float) -> bool:
    """A start button outside handed a task the tool in the clone has not taken yet."""
    try:
        job = json.loads(JOB_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(job, dict) and time.time() - float(job.get("at", 0)) <= max_age


def clear_job() -> None:
    try:
        JOB_FILE.unlink()
    except OSError:
        pass


def take_job(max_age: float) -> dict | None:
    """The handed-over task, removed before it is returned; None when stale."""
    try:
        job = json.loads(JOB_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    clear_job()
    if not isinstance(job, dict) or time.time() - float(job.get("at", 0)) > max_age:
        return None
    return job


def reload_config(config) -> bool:
    """Re-read one ok-script ``Config`` from its file, in place, without saving.

    The tool outside and the tool in the clone share the configs folder but
    each keeps its own copy in memory, so a setting changed outside never
    reached a run in the clone (Leo, 2026-10-09: 镜中之战 kept clicking after
    he switched 舞台移动方式 to the keyboard).  Missing or broken files are
    left alone.
    """
    path = getattr(config, "config_file", None)
    if not path:
        return False
    try:
        current = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(current, dict):
        return False
    config.verify_config(current, config.default)
    return True


# Programs of the tool and the game, never closed in the clone.
KEEP_NAMES = {
    "python.exe",
    "pythonw.exe",
    "browndust ii.exe",
    "browndust2starter.exe",
    "explorer.exe",
    "conhost.exe",
    "cmd.exe",
}
_RUN_KEYS = (
    r"Software\Microsoft\Windows\CurrentVersion\Run",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
)


def _exe_of_command(command: str) -> str | None:
    command = os.path.expandvars(command.strip())
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    lowered = command.lower()
    end = lowered.find(".exe")
    return command[: end + 4] if end >= 0 else command.split(" ", 1)[0]


def startup_programs() -> set[str]:
    """Lower-case paths of the programs Windows starts at sign-in for this user."""
    paths: set[str] = set()
    try:
        import winreg
    except ImportError:
        return paths
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_path in _RUN_KEYS:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    index = 0
                    while True:
                        try:
                            _name, value, _kind = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        index += 1
                        exe = _exe_of_command(str(value))
                        if exe:
                            paths.add(os.path.normcase(exe))
            except OSError:
                continue
    folders = [
        Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
        Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
    ]
    for folder in folders:
        for link in folder.glob("*.lnk") if folder.is_dir() else ():
            try:
                import win32com.client

                target = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(link))
                if target.TargetPath:
                    paths.add(os.path.normcase(target.TargetPath))
            except Exception:
                continue
    return paths


def sign_in_task_programs() -> set[str]:
    """Programs of scheduled tasks that run at sign-in (logon or session-state triggers).

    Live 2026-10-03: 「Google Play Games Notifier」 (Bootstrapper.exe /bg, a
    session-state trigger) opened Google Play Games on the clone, which there
    only shows error SE102.  Read only: nothing is changed in Task Scheduler.
    """
    paths: set[str] = set()
    try:
        import win32com.client

        service = win32com.client.Dispatch("Schedule.Service")
        service.Connect()
    except Exception:
        return paths
    folders = [service.GetFolder("\\")]
    while folders:
        folder = folders.pop()
        try:
            folders.extend(folder.GetFolders(0))
            tasks = list(folder.GetTasks(0))
        except Exception:
            continue
        for task in tasks:
            try:
                if not task.Enabled:
                    continue
                definition = task.Definition
                # 9 = at logon, 11 = session state change (connect, unlock...).
                if not any(trigger.Type in (9, 11) for trigger in definition.Triggers):
                    continue
                for action in definition.Actions:
                    if action.Type == 0 and action.Path:
                        path = os.path.expandvars(str(action.Path).strip('"'))
                        paths.add(os.path.normcase(path))
            except Exception:
                continue
    return paths


STARTUP_LIST = DATA_DIR / "startup-programs.txt"
# Programs Windows starts through Task Scheduler at sign-in.
STARTUP_TASK_LIST = DATA_DIR / "startup-tasks.txt"
# Windows starts the startup programs from these at sign-in.
SIGN_IN_PARENTS = {"explorer.exe", "userinit.exe"}
# ... and the sign-in scheduled tasks from these.
TASK_PARENTS = {"svchost.exe", "taskhostw.exe"}


def _closable(path: str) -> bool:
    windows_dir = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    return not path.startswith(windows_dir) and os.path.basename(path) not in KEEP_NAMES


def write_startup_list() -> None:
    """For the viewer, which closes these on the clone the moment they start."""
    try:
        paths = sorted(path for path in startup_programs() if _closable(path))
        tasks = sorted(path for path in sign_in_task_programs() if _closable(path))
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STARTUP_LIST.write_text("\n".join(paths), encoding="utf-8")
        STARTUP_TASK_LIST.write_text("\n".join(tasks), encoding="utf-8")
    except OSError:
        pass


@functools.lru_cache(maxsize=1)
def _sign_in_tasks_once() -> frozenset[str]:
    """Read once per run: walking Task Scheduler takes a moment."""
    return frozenset(sign_in_task_programs())


def close_startup_programs() -> list[str]:
    """In the clone, close the programs Windows started at sign-in (Leo, 2026-10-03).

    Only processes of this clone session whose program is one of this user's
    startup programs; the tool, the game and Windows' own programs stay.
    """
    if not in_clone():
        return []
    try:
        import psutil
    except ImportError:
        return []
    startup = startup_programs()
    tasks = _sign_in_tasks_once()
    windows_dir = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    own = ctypes.c_ulong(0)
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(own))
    closed = []
    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = process.info.get("exe")
            name = (process.info.get("name") or "").lower()
            if not exe or name in KEEP_NAMES:
                continue
            exe = os.path.normcase(exe)
            from_task = exe in tasks
            if exe.startswith(windows_dir) or not (exe in startup or from_task):
                continue
            session = ctypes.c_ulong(0)
            if not ctypes.windll.kernel32.ProcessIdToSessionId(
                process.info["pid"], ctypes.byref(session)
            ):
                continue
            if session.value != own.value:
                continue
            # Only what the sign-in started: a browser the game's launcher
            # opens (e.g. a Google login) is on the list too and must stay.
            parent = process.parent()
            parents = SIGN_IN_PARENTS | TASK_PARENTS if from_task else SIGN_IN_PARENTS
            if parent is None or (parent.name() or "").lower() not in parents:
                continue
            # Steam, Discord and others start helpers; close those too.
            for child in process.children(recursive=True):
                try:
                    child.terminate()
                except Exception:
                    pass
            process.terminate()
            closed.append(name)
        except Exception:
            continue
    return closed


PLAY_GAMES_SERVICE = os.path.normcase(r"Google\Play Games\current\service\Service.exe")


def close_play_games_launcher() -> list[int]:
    """In the clone, close Google Play Games' own launcher once the game runs.

    Live 2026-10-04: starting BD2 through googleplaygames://launch in the
    clone starts Play Games' Service.exe there; Play Games does not support
    remote sessions, so it shows error SE102 over the game.  BD2 itself is
    started by the system-wide Play Games service and keeps running.  Only
    this clone session's copy is closed; the one on the real desktop stays.
    """
    if not in_clone():
        return []
    try:
        import psutil
    except ImportError:
        return []
    own = ctypes.c_ulong(0)
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(own))
    closed = []
    for process in psutil.process_iter(["pid", "exe"]):
        try:
            exe = process.info.get("exe")
            if not exe or not os.path.normcase(exe).endswith(PLAY_GAMES_SERVICE):
                continue
            session = ctypes.c_ulong(0)
            if not ctypes.windll.kernel32.ProcessIdToSessionId(
                process.info["pid"], ctypes.byref(session)
            ):
                continue
            if session.value != own.value:
                continue
            for child in process.children(recursive=True):
                try:
                    child.terminate()
                except Exception:
                    pass
            process.terminate()
            closed.append(process.info["pid"])
        except Exception:
            continue
    return closed
