"""Press the game while another window is in front (Leo 2026-11-07
「我希望程式可以就算被蓋住也能繼續運行」).

BD2 only takes keys while it is the foreground window, so each press borrows
that for a moment and gives it straight back.  Measured live on 2026-11-07 (M
key, game covered by a test window): 90 ms in front landed 24 of 24 presses and
the window came back 24 of 24 times, at most 113 ms later.

The game would jump to the top each time (Leo 「會一直跳遊戲的視窗出來又跳回去」),
so the window in front is pinned on top for that moment: the game gets the
keys from under it.  Measured 2026-11-07, game under a test window, M key: 8 of
8 landed both ways; sampling the screen, 324 frames showed the game unpinned,
0 pinned; the window came back and lost its pin 8 of 8 times.

The player's mouse comes first (「那最少滑鼠要可以」): nothing is borrowed while it
moves or a button is held, so a drag or a click is never cut in two.  The
keyboard is not waited for (「鍵盤不管」).  The cursor is watched, not
GetLastInputInfo: on Leo's PC some program resets that every second.
"""

from __future__ import annotations

from typing import Callable

MOUSE_QUIET = 0.6  # the mouse stood still this long
MOUSE_LOOK = 0.1
REACH_SECONDS = 0.4  # the foreground change has this long to show
REACH_LOOK = 0.005
SETTLE = 0.03  # the game sees its focus before the key comes
RESTORE_TRIES = 2
VK_BUTTONS = (0x01, 0x02, 0x04)  # left, right, middle


def wait_mouse_quiet(
    cursor: Callable[[], tuple[int, int]],
    button_held: Callable[[], bool],
    sleep: Callable[[float], None],
    quiet: float = MOUSE_QUIET,
) -> float:
    """Return once the mouse stood still with no button held; how long it took
    (``sleep`` ends the wait when the run is stopped)."""
    waited = still = 0.0
    last = cursor()
    while still < quiet:
        sleep(MOUSE_LOOK)
        waited += MOUSE_LOOK
        now = cursor()
        still = 0.0 if now != last or button_held() else still + MOUSE_LOOK
        last = now
    return waited


def _reach(window: int, foreground: Callable[[], int], sleep: Callable[[float], None]) -> bool:
    spent = 0.0
    while spent < REACH_SECONDS:
        if foreground() == window:
            return True
        sleep(REACH_LOOK)
        spent += REACH_LOOK
    return foreground() == window


def _hand_back(before: int, foreground, set_foreground, sleep) -> bool:
    if not before:
        return True
    for _try in range(RESTORE_TRIES):  # 不是重试点击：把窗口还回去，没回来再还一次
        set_foreground(before)
        if _reach(before, foreground, sleep):
            return True
    return False


def borrow_foreground(
    game: int,
    action: Callable[[], object],
    foreground: Callable[[], int],
    set_foreground: Callable[[int], None],
    sleep: Callable[[float], None],
    pin: Callable[[int], Callable[[], None]] = lambda _window: (lambda: None),
) -> tuple[bool, bool]:
    """Run ``action`` with ``game`` the foreground window, then hand it back.
    ``pin`` keeps a window on top and returns how to undo that.  Returns (it
    ran, the window that was in front came back)."""
    before = foreground()
    if before == game:
        action()
        return True, True
    unpin = pin(before) if before else (lambda: None)
    try:
        set_foreground(game)
        if not _reach(game, foreground, sleep):
            return False, foreground() == before or _hand_back(before, foreground, set_foreground, sleep)
        sleep(SETTLE)
        returned = False
        try:
            action()
        finally:
            returned = _hand_back(before, foreground, set_foreground, sleep)
        return True, returned
    finally:
        unpin()


def pin_on_top(window: int) -> Callable[[], None]:
    """Keep ``window`` above the game; undone only if it was not on top itself."""
    import win32con
    import win32gui

    flags = win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
    try:
        if win32gui.GetWindowLong(window, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOPMOST:
            return lambda: None
        win32gui.SetWindowPos(window, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
    except Exception:  # a window that refuses (run as admin): the game just shows for a moment
        return lambda: None

    def unpin() -> None:
        try:
            win32gui.SetWindowPos(window, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        except Exception:  # it was closed meanwhile
            pass

    return unpin
