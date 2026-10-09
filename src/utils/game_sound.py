"""跑的时候游戏静音：玩家在「设置」里自己选，默认不静音（Leo 2026-10-09）。

开跑时在 Windows 的音量合成器里把游戏这个程序静音，不动游戏自己的音量设定；
跑完、停止或出错都恢复成开跑前的样子（本来就静音的就保持静音）。工具当掉、
没来得及恢复的，下次打开工具时恢复。
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path

from ok import Logger

logger = Logger.get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = ROOT / "configs" / "game_sound.json"
MUTE_KEY = "mute_while_running"
# The game process this tool muted (and whether it was muted already), per
# Windows session: the tool in 桌面分身 shares this file with the one outside.
MUTED_KEY = "muted"
# A game that just opened may have no sound yet; look again after this long.
RETRY_SECONDS = 3.0


def _read() -> dict:
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _write(saved: dict) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(saved), encoding="utf-8")
    except OSError as exc:
        logger.warning(f"game sound: not saved ({exc})")


def enabled() -> bool:
    """Read from the file each time: the tool in 桌面分身 shares the configs folder."""
    return bool(_read().get(MUTE_KEY, False))


def set_enabled(on: bool) -> None:
    saved = _read()
    saved[MUTE_KEY] = bool(on)
    _write(saved)


# ------------------------------------------------------------------ mixer


class _Mixer:
    """The game's entries in the Windows volume mixer (pycaw); tests use a fake."""

    @staticmethod
    def volumes(pid: int) -> list:
        from pycaw.utils import AudioUtilities

        return [
            session.SimpleAudioVolume
            for session in AudioUtilities.GetAllSessions()
            if session.ProcessId == pid
        ]


mixer = _Mixer()


def pid_of(hwnd: int) -> int:
    """The process of a window (0 when there is none or not on Windows)."""
    if not hwnd or sys.platform != "win32":
        return 0
    pid = ctypes.c_ulong(0)
    try:
        ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    except Exception:
        return 0
    return int(pid.value)


def _session_key() -> str:
    if sys.platform != "win32":
        return "0"
    session = ctypes.c_ulong(0)
    try:
        ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
    except Exception:
        return "0"
    return str(session.value)


def _volumes(pid: int) -> list:
    try:
        return list(mixer.volumes(pid))
    except Exception as exc:
        logger.warning(f"game sound: volume mixer not readable ({exc})")
        return []


def _set_mute(volumes: list, mute: bool) -> None:
    for volume in volumes:
        try:
            volume.SetMute(1 if mute else 0, None)
        except Exception as exc:
            logger.warning(f"game sound: mute not changed ({exc})")


# ------------------------------------------------------------------ runs

# What this tool muted: the game process and whether it was muted before.
_held = {"pid": 0, "was_muted": False}
_retry = {"pid": 0, "at": 0.0}
# Windows keeps an app's mute for its next start: a game this tool muted that
# closed before the sound came back (闪退, killed) opens muted next time.  The
# unmute is then owed to the next game process (live 2026-10-10).
_owed = {"unmute": False, "at": 0.0}


def holding() -> bool:
    return bool(_held["pid"])


def follow(running: bool, pid: int, now: float | None = None) -> None:
    """Called about once a second: mute the game while a run goes, give the
    sound back when it ends (also when the player turns the setting off)."""
    now = time.monotonic() if now is None else now
    want = bool(running and pid and enabled())
    if _held["pid"] and (not want or _held["pid"] != pid):
        restore()
    if want and _held["pid"] != pid:
        _mute(pid, now)
    elif not want and pid and _owed["unmute"]:
        _pay_owed(pid, now)


def _mute(pid: int, now: float) -> None:
    if _retry["pid"] == pid and now < _retry["at"]:
        return
    volumes = _volumes(pid)
    if not volumes:
        _retry.update(pid=pid, at=now + RETRY_SECONDS)
        return
    if _owed["unmute"]:
        # Muted only because this tool muted the game before it closed.
        was_muted = False
        _owed.update(unmute=False, at=0.0)
    else:
        try:
            was_muted = all(bool(volume.GetMute()) for volume in volumes)
        except Exception:
            was_muted = False
    _set_mute(volumes, True)
    _held.update(pid=pid, was_muted=was_muted)
    _retry.update(pid=0, at=0.0)
    saved = _read()
    marks = saved.get(MUTED_KEY) if isinstance(saved.get(MUTED_KEY), dict) else {}
    marks[_session_key()] = {"pid": pid, "was_muted": was_muted}
    saved[MUTED_KEY] = marks
    _write(saved)
    logger.info(f"game sound: muted the game while running (pid {pid}, was muted {was_muted})")


def restore() -> None:
    """Give the sound back now (run ended, setting off, tool closing)."""
    pid, was_muted = _held["pid"], _held["was_muted"]
    _held.update(pid=0, was_muted=False)
    _retry.update(pid=0, at=0.0)
    if not pid or was_muted:
        _forget_mark()
        return
    volumes = _volumes(pid)
    if not volumes:
        # The game closed while muted: its next start opens muted.  The mark
        # stays saved, so a tool closed before then still gives it back.
        _owed.update(unmute=True, at=0.0)
        logger.info(f"game sound: game closed while muted (pid {pid}), sound back when it opens")
        return
    _forget_mark()
    _set_mute(volumes, False)
    logger.info(f"game sound: sound back (pid {pid})")


def _pay_owed(pid: int, now: float) -> None:
    if now < _owed["at"]:
        return
    volumes = _volumes(pid)
    if not volumes:
        _owed["at"] = now + RETRY_SECONDS
        return
    _owed.update(unmute=False, at=0.0)
    _forget_mark()
    _set_mute(volumes, False)
    logger.info(f"game sound: sound back after the game reopened (pid {pid})")


def _forget_mark() -> dict | None:
    saved = _read()
    marks = saved.get(MUTED_KEY)
    if not isinstance(marks, dict) or _session_key() not in marks:
        return None
    mark = marks.pop(_session_key())
    saved[MUTED_KEY] = marks
    _write(saved)
    return mark if isinstance(mark, dict) else None


def restore_left_over() -> None:
    """At start: a tool that closed mid-run left the game muted; unmute it."""
    marks = _read().get(MUTED_KEY)
    mark = marks.get(_session_key()) if isinstance(marks, dict) else None
    if not isinstance(mark, dict) or mark.get("was_muted"):
        _forget_mark()
        return
    try:
        pid = int(mark.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    volumes = _volumes(pid) if pid else []
    if volumes:
        _forget_mark()
        _set_mute(volumes, False)
        logger.info(f"game sound: sound back after the tool closed mid-run (pid {pid})")
        return
    # That game is gone: the next one opens muted; give it back then (the
    # mark stays until then).
    _owed.update(unmute=True, at=0.0)
