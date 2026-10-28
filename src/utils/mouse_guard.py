"""The player's mouse kept off the game while the tool moves the real cursor.

The fight's taps and drags (and the sale list's) move the real cursor with
posted clicks, so the player's own mouse must not move it meanwhile.  That
was Windows' BlockInput, which also swallowed every key and every press on
the in-game status bar: 暂停 there had to be pressed several times (Leo's 4K
2026-10-28 16:29 「按好幾次才有反應」「你不應該鎖住暫停 最少要給一點反饋」).

Now only the player's mouse is held, in the takeover monitor's mouse hook
(src/tasks/takeover.py): moves and presses are kept off the game, keys pass
(F9 always works), and a press made with the cursor on a bar button is that
button's press.  Without the hook (not started, the 桌面分身) the caller
falls back to BlockInput.
"""

from __future__ import annotations

import threading
import time

# A guard left on (a crash between start and stop) never holds the mouse
# longer than this; the longest real action (a drag) takes about 2 s.
MAX_SECONDS = 15.0

_lock = threading.Lock()
_hooked = False
_depth = 0
_since = 0.0
_player_point: tuple[int, int] | None = None


def set_hooked(on: bool) -> None:
    """The takeover monitor's mouse hook runs on this desktop (it does the holding)."""
    global _hooked
    _hooked = bool(on)


def start(player_point) -> bool:
    """Hold the player's mouse; False when there is no hook to do it."""
    global _depth, _since, _player_point
    with _lock:
        if not _hooked:
            return False
        if _depth == 0 or _expired():
            _depth = 0
            _since = time.monotonic()
            _player_point = tuple(player_point) if player_point else None
        _depth += 1
        return True


def stop() -> None:
    global _depth, _player_point
    with _lock:
        _depth = max(0, _depth - 1)
        if _depth == 0:
            _player_point = None


def active() -> bool:
    with _lock:
        return _depth > 0 and not _expired()


def player_point() -> tuple[int, int] | None:
    """Where the player's cursor was when the hold began (it goes back there after)."""
    return _player_point


def _expired() -> bool:
    return time.monotonic() - _since > MAX_SECONDS
