"""FPS tools running on this Windows session (Leo 2026-11-04).

「偵測到玩家開啟 fps 工具的時候提醒可能會導致失敗」: these draw an FPS
counter (or other numbers) into the game's own picture, cap or generate its
frames.  The tool reads that picture, so the counter can cover the words it
reads and a capped or generated frame can make it see a half-drawn page.
A player report on 2026-10-12 showed RTSS's 「MHz」 read as part of a
recipe name (每周制作装备).

Only programs that always do this while they run are listed: RTSS is what
MSI Afterburner, HWiNFO and CapFrameX draw their counters with, so it covers
them.  The NVIDIA app, AMD Adrenalin, Xbox Game Bar and Steam run on most
PCs whether their counter is on or not; warning for them would warn nearly
everyone, so they are not listed.
"""

from __future__ import annotations

import ctypes
import os

# exe name (lower case) -> the name the player knows.
KNOWN: dict[str, str] = {
    "rtss.exe": "RivaTuner (RTSS)",
    "fpsmonitor.exe": "FPS Monitor",
    "fraps.exe": "Fraps",
    "losslessscaling.exe": "Lossless Scaling",
    "bdcam.exe": "Bandicam",
    "dxtory.exe": "Dxtory",
}


# Under a failed run in 今日报表 and on the results page (Leo 「報表要說明清楚」).
FAILED_WITH = "当时开着 FPS 工具（{names}），可能让工具认错画面，关掉再跑试试"


def names_of(process_names) -> list[str]:
    """The player-facing names of the FPS tools among ``process_names``, each once."""
    found: list[str] = []
    for name in process_names:
        label = KNOWN.get(str(name or "").lower())
        if label and label not in found:
            found.append(label)
    return found


def running() -> list[str]:
    """FPS tools running on this Windows session; [] when none or it cannot tell.

    Only this session: a tool on the player's own desktop does not touch a
    game on a 桌面分身, and the other way round.  Never raises.
    """
    try:
        import psutil
    except ImportError:
        return []
    try:
        session_of = ctypes.windll.kernel32.ProcessIdToSessionId
    except AttributeError:
        return []
    try:
        own = ctypes.c_ulong(0)
        session_of(os.getpid(), ctypes.byref(own))
        names = []
        for process in psutil.process_iter(["pid", "name"]):
            name = str(process.info.get("name") or "").lower()
            if name not in KNOWN:
                continue
            session = ctypes.c_ulong(0)
            if session_of(process.info["pid"], ctypes.byref(session)):
                if session.value == own.value:
                    names.append(name)
        return names_of(names)
    except Exception:
        return []


def joined(labels: list[str]) -> str:
    """'RivaTuner (RTSS), Bandicam'."""
    return ", ".join(labels)
