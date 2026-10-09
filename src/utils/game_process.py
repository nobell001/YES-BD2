"""Whether the game runs on this Windows session.

Used to tell a game that closed by itself (闪退) from a page the tool could
not read, and to open the game before a run when it is closed.
"""

from __future__ import annotations

import ctypes
import os

from src.game_path import get_game_exe_names


def game_running() -> bool | None:
    """BrownDust II runs on this Windows session (not only on a 桌面分身).

    None when it cannot tell (no psutil, not Windows).
    """
    try:
        import psutil
    except ImportError:
        return None
    try:
        session_of = ctypes.windll.kernel32.ProcessIdToSessionId
    except AttributeError:
        return None
    names = {name.lower() for name in get_game_exe_names()}
    own = ctypes.c_ulong(0)
    session_of(os.getpid(), ctypes.byref(own))
    for process in psutil.process_iter(["pid", "name"]):
        if (process.info.get("name") or "").lower() not in names:
            continue
        session = ctypes.c_ulong(0)
        if session_of(process.info["pid"], ctypes.byref(session)):
            if session.value == own.value:
                return True
    return False
