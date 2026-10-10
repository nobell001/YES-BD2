"""One tool per folder: opening it again brings the open one to the front.

ok-script's own check (``check_mutex``) waits 5 s and then kills the copy
that is open, busy or not, so a second click on the icon (or the launcher's
自动启动, or a scheduled start) ended a running 一键日常 without a word
(review 2026-10-09).  src/config.py turns that check off; the entry points
call ``acquire`` here instead, which never closes anything.

The lock is a ``Local\\`` mutex, one per Windows session: the tool in the
桌面分身 has its own, and the window search only sees this session's desktop.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
import time

TITLE = "YES-BD2"
ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5
# A copy that is closing (language change, restart as Administrator) gets
# this long to let go, as ok-script waited before.
WAIT_TRIES = 20
WAIT_SECONDS = 0.25
ALREADY_OPEN = (
    "YES-BD2 已经开着了，不用再开一次（看看任务栏或右下角的小图标）。"
    "如果它卡住了，先在任务管理器里结束它再打开。"
)
_handle = None


def mutex_name(folder: str | None = None) -> str:
    folder = os.getcwd() if folder is None else folder
    digest = hashlib.md5(
        os.path.normcase(folder).encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    return f"Local\\{TITLE}-{digest}"


def _create_mutex(name: str) -> tuple[int | None, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    handle = kernel32.CreateMutexW(None, False, name)
    return handle, ctypes.get_last_error()


def _close(handle: int) -> None:
    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


def _try_acquire(create, close) -> bool:
    global _handle
    handle, error = create(mutex_name())
    if handle and error != ERROR_ALREADY_EXISTS:
        _handle = handle  # kept until this process ends
        return True
    if handle:
        close(handle)
        return False
    # No handle: an Administrator copy holds it and this one is not one.
    # Any other failure cannot tell, and then the tool starts as before.
    return error != ERROR_ACCESS_DENIED


def acquire(create=None, close=_close, sleep=time.sleep) -> bool:
    """True when no other copy runs from this folder in this Windows session."""
    if _handle is not None:
        return True
    if create is None:
        if sys.platform != "win32":
            return True
        create = _create_mutex
    for attempt in range(WAIT_TRIES):
        if attempt:
            sleep(WAIT_SECONDS)
        if _try_acquire(create, close):
            return True
    return False


def _process_name(pid: int) -> str:
    try:
        import psutil

        return psutil.Process(pid).name().lower()
    except Exception:
        return ""


def _tool_window() -> int | None:
    """A shown main window of another copy of this tool on this desktop."""
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    names = {os.path.basename(sys.executable).lower(), "python.exe", "pythonw.exe"}
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(handle, _param):
        hwnd = wintypes.HWND(handle)
        if not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        if title.value != TITLE and not title.value.startswith(f"{TITLE} "):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != os.getpid() and _process_name(pid.value) in names:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def bring_to_front() -> bool:
    """False when no window of the other copy is shown (tray, hung, starting)."""
    if sys.platform != "win32":
        return False
    try:
        hwnd = _tool_window()
        if hwnd is None:
            return False
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _in_clone() -> bool:
    try:
        from src.utils.clone_desktop import in_clone

        return in_clone()
    except Exception:
        return False


def _message_box(text: str) -> None:
    try:
        # MB_ICONINFORMATION | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x40 | 0x10000)
    except Exception:
        pass


def show_existing(front=bring_to_front, in_clone=_in_clone, message_box=_message_box) -> None:
    """The open copy comes to the front; without a window to show, say so.

    Not on the 桌面分身: nobody would answer the message there.
    """
    if front() or in_clone():
        return
    message_box(ALREADY_OPEN)
