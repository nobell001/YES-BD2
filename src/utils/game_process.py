"""Whether the game runs on this Windows session.

Used to tell a game that closed by itself (闪退) from a page the tool could
not read, to open the game before a run when it is closed, and to close it
after a clean 一键日常 when the player asked for that.
"""

from __future__ import annotations

import ctypes
import os

from src.game_path import get_game_exe_names
from src.utils.process_snapshot import pids_named

CLOSE_WAIT_SECONDS = 15.0


def _game_processes() -> list | None:
    """The game's processes on this Windows session; None when it cannot tell."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        session_of = ctypes.windll.kernel32.ProcessIdToSessionId
    except AttributeError:
        return None
    own = ctypes.c_ulong(0)
    session_of(os.getpid(), ctypes.byref(own))
    found = []
    for pid in pids_named(get_game_exe_names()):
        session = ctypes.c_ulong(0)
        if session_of(pid, ctypes.byref(session)) and session.value == own.value:
            try:
                found.append(psutil.Process(pid))
            except psutil.NoSuchProcess:
                continue
    return found


def game_running() -> bool | None:
    """BrownDust II runs on this Windows session (not only on a 桌面分身).

    None when it cannot tell (no psutil, not Windows).
    """
    found = _game_processes()
    return None if found is None else bool(found)


def _press_alt_f4(pids: set[int]) -> int:
    """What Alt+F4 does (WM_SYSCOMMAND SC_CLOSE) to each visible game window;
    sent to the window, so it works without the focus and in a 桌面分身."""
    import win32con
    import win32gui
    import win32process

    pressed = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in pids:
            win32gui.PostMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_CLOSE, 0)
            pressed.append(hwnd)

    win32gui.EnumWindows(visit, None)
    return len(pressed)


def close_game(wait: float = CLOSE_WAIT_SECONDS) -> bool:
    """Close BrownDust II on this Windows session with Alt+F4; True once it is gone.

    Leo 2026-10-20 「關閉就alt+f4就好」: the game is never ended by force; one
    that is still open after ``wait`` (a dialog of its own, say) is left as it
    is and False tells the player to close it.  Only the game on this session:
    a game on the player's own desktop is left alone when this runs in a 桌面分身.
    """
    found = _game_processes()
    if not found:
        return found is not None
    import psutil

    if not _press_alt_f4({process.pid for process in found}):
        return False
    _gone, alive = psutil.wait_procs(found, timeout=wait)
    return not alive
