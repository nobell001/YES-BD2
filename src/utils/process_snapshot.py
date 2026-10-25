"""Every process's pid and executable name in one Toolhelp32 snapshot.

``psutil.process_iter(["name"])`` opens each process for its name; a process
of another user is denied to a non-Administrator, and psutil then walks the
whole process list again for that one name.  On win4090's bd2 Remote Desktop
session (459 processes over four sessions, live 2026-10-22) that took 50 s
against 0.13 s for the snapshot, and the tool took 37 s before it asked for
Administrator.  The snapshot needs no access to the processes.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x2
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _snapshot() -> list[tuple[int, str]] | None:
    try:
        kernel32 = ctypes.windll.kernel32
    except AttributeError:
        return None
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return None
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        found = []
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            found.append((int(entry.th32ProcessID), entry.szExeFile))
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return found
    finally:
        kernel32.CloseHandle(snapshot)


def process_names() -> list[tuple[int, str]]:
    """(pid, executable name) of every process; psutil when no snapshot."""
    if sys.platform == "win32":
        found = _snapshot()
        if found is not None:
            return found
    try:
        import psutil

        return [(process.info["pid"], process.info.get("name") or "") for process in psutil.process_iter(["pid", "name"])]
    except Exception:
        return []


def pids_named(names) -> list[int]:
    """Pids of the processes whose executable name is one of ``names`` (any case)."""
    wanted = {name.lower() for name in names}
    return [pid for pid, name in process_names() if name.lower() in wanted]
