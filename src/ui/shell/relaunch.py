"""Close the tool and open it again (a new language only loads at start).

A small detached Python process waits until this one has exited, then
starts the tool the same way it was started, so the single-instance lock
is free by then.
"""

from __future__ import annotations

import os
import subprocess
import sys

from ok import Logger

logger = Logger.get_logger(__name__)

_WAITER = """
import ctypes, subprocess, sys, time
pid = int(sys.argv[1])
SYNCHRONIZE = 0x00100000
handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
if handle:
    ctypes.windll.kernel32.WaitForSingleObject(handle, 60000)
    ctypes.windll.kernel32.CloseHandle(handle)
time.sleep(1)
subprocess.Popen(sys.argv[2:], cwd=None, close_fds=True)
"""


def relaunch_command() -> list[str]:
    """How this tool was started: the same Python and arguments."""
    return [sys.executable, *sys.argv]


def relaunch_env(environ=None) -> dict[str, str]:
    """This tool's variables without PYAPPIFY_PID.

    That launcher was closed when this copy's window first showed; its number
    may belong to another program by now (even the game), and the new copy
    would minimise and close it (2026-10-09 review).
    """
    environ = os.environ if environ is None else environ
    return {key: value for key, value in environ.items() if key.upper() != "PYAPPIFY_PID"}


def relaunch(app) -> bool:
    """Start the waiter, then quit; False when it could not be started."""
    if os.name != "nt":
        logger.warning("relaunch only works on Windows")
        return False
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    try:
        subprocess.Popen(
            [sys.executable, "-c", _WAITER, str(os.getpid()), *relaunch_command()],
            cwd=os.getcwd(),
            env=relaunch_env(),
            creationflags=flags,
            close_fds=True,
        )
    except Exception as exc:
        logger.error("relaunch failed", exc)
        return False
    logger.info("relaunching for a new language")
    app.quit()
    return True
