"""设置「游戏里显示执行状态」: a status bar on top of the game while a run is on
(YES-BD2 #60, Leo 2026-10-28 「做一個執行中可以置頂在遊戲視窗的狀態欄」).

The bar itself is ``src.ui.shell.game_status``.  This module only keeps the
setting (off unless the player turns it on) and the bar's window handles, so
the task side can tell the bar apart from a window really covering the game
without importing the UI.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path

from ok import Logger

logger = Logger.get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = ROOT / "configs" / "game_status_bar.json"
SHOW_KEY = "show_on_game"

_handles: set[int] = set()
# Screen rects (pixels) of the bar's buttons while they take clicks: only
# while the player's own mouse is on one (Leo 2026-10-28 「要有滑鼠可以點的
# 樣子」).  Everywhere else, and always while the tool presses, the mouse
# goes through.
_live: dict[int, list[tuple[int, int, int, int]]] = {}
# Where the buttons are drawn, taking clicks or not: a real press there is
# the player pressing the bar, never playing the game (Leo's 4K 2026-10-28
# 16:02: a quick press on ▶ went through to the paused game, so 继续 went
# home instead of to the picked stage).
_buttons: dict[int, list[tuple[int, int, int, int]]] = {}
# The same buttons by what they do, for a press the hook made for the bar
# (src/tasks/takeover.py, src/utils/mouse_guard.py).
_actions: dict[int, list[tuple[str, tuple[int, int, int, int]]]] = {}
_press_handler = None  # the bar's press, safe to call from any thread
_held = 0
_lock = threading.Lock()
WS_EX_TRANSPARENT = 0x20
GWL_EXSTYLE = -20


def _read() -> dict:
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def enabled() -> bool:
    """Read from the file each time: the tool in 桌面分身 shares the configs
    folder, so turning it off outside reaches the run inside at once."""
    return bool(_read().get(SHOW_KEY, False))


def set_enabled(on: bool) -> None:
    saved = _read()
    saved[SHOW_KEY] = bool(on)
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(saved), encoding="utf-8")
    except OSError as exc:
        logger.warning(f"game status bar: setting not saved ({exc})")


def register(hwnd: int) -> None:
    if hwnd:
        _handles.add(int(hwnd))


def unregister(hwnd: int) -> None:
    _handles.discard(int(hwnd or 0))
    _live.pop(int(hwnd or 0), None)
    _buttons.pop(int(hwnd or 0), None)
    _actions.pop(int(hwnd or 0), None)


def set_buttons(hwnd: int, rects: list[tuple[int, int, int, int]], actions=None) -> None:
    """Where the bar's buttons are on screen now (empty: none shown), and
    what each does (``actions``, same order)."""
    if rects:
        if _buttons.get(int(hwnd)) != list(rects):
            logger.info(f"game status bar: buttons at {list(rects)}")
        _buttons[int(hwnd)] = list(rects)
        if actions is not None:
            _actions[int(hwnd)] = list(zip(actions, rects))
    else:
        _buttons.pop(int(hwnd), None)
        _actions.pop(int(hwnd), None)


def button_at(point) -> str | None:
    """What the bar's button at ``point`` does (None: no button there)."""
    if not point:
        return None
    for pairs in list(_actions.values()):
        for action, rect in pairs:
            if _in(point, rect):
                return action
    return None


def live_at(point) -> bool:
    """A button at ``point`` takes the click itself right now."""
    return any(_in(point, rect) for rects in list(_live.values()) for rect in rects)


def set_press_handler(handler) -> None:
    global _press_handler
    _press_handler = handler


def press(action: str) -> bool:
    """Press the bar's ``action`` for the player (from the mouse hook)."""
    handler = _press_handler
    if handler is None:
        return False
    handler(action)
    return True


def on_button(point: tuple[int, int]) -> bool:
    """``point`` is on one of the bar's buttons (taking clicks or not)."""
    return any(_in(point, rect) for rects in list(_buttons.values()) for rect in rects)


def set_live(hwnd: int, rects: list[tuple[int, int, int, int]]) -> bool:
    """Let the buttons at ``rects`` take clicks (empty: none).  Refused (False)
    while the tool is pressing the real mouse (:func:`hold_clicks`)."""
    with _lock:
        if rects and _held:
            return False
        if rects:
            _live[int(hwnd)] = list(rects)
        else:
            _live.pop(int(hwnd), None)
        _set_click_through(int(hwnd), not rects)
        return True


def live_rects(hwnd: int) -> list[tuple[int, int, int, int]]:
    return list(_live.get(int(hwnd), ()))


def _set_click_through(hwnd: int, through: bool) -> None:
    import sys

    if sys.platform != "win32":
        return
    import ctypes

    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    wanted = style | WS_EX_TRANSPARENT if through else style & ~WS_EX_TRANSPARENT
    if wanted != style:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, wanted)


@contextmanager
def hold_clicks():
    """Around a real mouse press by the tool (the drag): every button goes
    back to letting the mouse through first, and none wakes up until it ends."""
    global _held
    with _lock:
        _held += 1
        for hwnd in list(_live):
            _live.pop(hwnd, None)
            try:
                _set_click_through(hwnd, True)
            except Exception:
                pass
    try:
        yield
    finally:
        with _lock:
            _held -= 1


def _in(point, rect) -> bool:
    return rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]


def is_bar(hwnd) -> bool:
    """``hwnd`` is the status bar (mouse goes through it to the game)."""
    try:
        return int(hwnd or 0) in _handles
    except (TypeError, ValueError):
        return False


def window_at(point: tuple[int, int]) -> int:
    """The top-level window under a screen point, looking through the bar.

    The bar lets the mouse through (WS_EX_TRANSPARENT), so Windows already
    skips it here; the walk below the bar is a second safety net, so 「游戏
    被别的窗口遮住」 is never decided from the bar (Leo 2026-10-28 「不要干擾到
    辨識和判定」).  A button taking clicks right now is the bar itself: the
    player pressing 暂停 there is not playing the game.
    """
    import win32con
    import win32gui

    hwnd = win32gui.WindowFromPoint(point)
    root = win32gui.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
    if not is_bar(root):
        return hwnd
    if any(_in(point, rect) for rect in _live.get(int(root), ())):
        return root  # a button the player is pressing: not the game
    below = win32gui.GetWindow(root, win32con.GW_HWNDNEXT)
    while below:
        if not is_bar(below) and win32gui.IsWindowVisible(below):
            left, top, right, bottom = win32gui.GetWindowRect(below)
            if left <= point[0] < right and top <= point[1] < bottom:
                return below
        below = win32gui.GetWindow(below, win32con.GW_HWNDNEXT)
    return 0
