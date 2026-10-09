"""Keep the PC awake while a run goes (Leo 2026-10-09).

ok-script asks Windows to keep only the display on, and only around a
one-time task; a Stop or an error leaves that request on, so the display then
never turns off while the tool stays open.  A run on the 桌面分身 sends no
input to this session, so the PC could fall asleep in the middle of it.

A timer on the main window calls :func:`apply` every few seconds with
:func:`level_for`: while a run goes in this tool, Windows is asked to keep the
system and the display awake; while a run goes in the clone, only the system
(the player's own screen may turn off); with nothing running the request is
given back.  Power settings are never changed: a request only lasts until it
is given back or the tool closes.
"""

from __future__ import annotations

import ctypes
from collections.abc import Iterator
from contextlib import contextmanager

from ok import Logger

logger = Logger.get_logger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

NONE = "none"
SYSTEM = "system"  # the PC stays on, the screen may turn off
DISPLAY = "display"  # the PC and the screen stay on

FLAGS = {
    NONE: ES_CONTINUOUS,
    SYSTEM: ES_CONTINUOUS | ES_SYSTEM_REQUIRED,
    DISPLAY: ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED,
}

# What the main window's timer last asked for (requests belong to a thread).
_held = NONE


def level_for(running_here: bool, paused: bool, running_in_clone: bool) -> str:
    """The request for what is going on now.

    A paused run waits for the player, who is at the PC: nothing is held.
    """
    if running_here and not paused:
        return DISPLAY
    if running_in_clone:
        return SYSTEM
    return NONE


def _set_thread_state(flags: int) -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
    except AttributeError:
        return False  # not Windows
    try:
        kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
    except Exception as exc:
        logger.warning(f"keep awake: SetThreadExecutionState failed: {exc}")
        return False
    return True


def apply(level: str) -> bool:
    """Ask Windows for ``level`` (from the main window's thread).

    True when the request changed.
    """
    global _held
    if level == _held or level not in FLAGS:
        return False
    if not _set_thread_state(FLAGS[level]):
        return False
    logger.info(f"keep awake: {_held} -> {level}")
    _held = level
    return True


def held() -> str:
    return _held


def release_this_thread() -> None:
    """Give back a request made on the calling thread.

    For the task thread at the end of a run: ok-script's own display request
    stays on after a Stop or an error otherwise.
    """
    _set_thread_state(ES_CONTINUOUS)


@contextmanager
def released_after(active: bool) -> Iterator[None]:
    """Around a run that the task thread started: give the request back at
    the end, however the run ends."""
    try:
        yield
    finally:
        if active:
            release_this_thread()
