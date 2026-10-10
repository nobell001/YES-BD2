"""Stop the running task as soon as the user takes over the game.

The tool clicks by posting messages to the game window, so the real mouse and
keyboard belong to the user.  A real click, wheel turn or key press on the
game while a one-time task runs means the user took over (users do this
within seconds of anything looking stuck): the task is stopped the way the
Stop button does it, so the tool never fights the user for the game.

Ignored:
- our own real input (sale-list drags, WASD walking): Windows flags it as
  injected;
- anything in other windows: the tool is meant to run in the background;
- a click that only brings the game to the front (it was behind another
  window when pressed);
- mouse movement alone, F1-F24 (ok's Start/Stop hotkey is F9) and PrintScreen;
  Alt+F4 does count: it closes the game, the run is not to reopen it;
- anything on the 桌面分身 (input reaches the clone only by accident);
- any input while the running task says the player plays along
  (``player_plays_along``, e.g. recording a 魔兽追踪者 fight).

A paused run is not stopped (decision 8 of the 10-10 plan, its default: 暂停 is there so the player
can step in); it is marked ``player_stepped_in`` and, after 继续, looks at
the screen again before its next press (BaseBD2Task.sleep).
"""

from __future__ import annotations

import sys
import threading

from ok import Logger

logger = Logger.get_logger(__name__)

WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
MOUSE_PRESS_MESSAGES = frozenset(
    {
        0x0201,  # WM_LBUTTONDOWN
        0x0204,  # WM_RBUTTONDOWN
        0x0207,  # WM_MBUTTONDOWN
        0x020A,  # WM_MOUSEWHEEL
        0x020B,  # WM_XBUTTONDOWN
        0x020E,  # WM_MOUSEHWHEEL
    }
)
LLMHF_INJECTED = 0x01
LLKHF_INJECTED = 0x10
LLKHF_ALTDOWN = 0x20
FUNCTION_KEYS = range(0x70, 0x88)  # VK_F1 .. VK_F24
VK_F4 = 0x73
# Lock and modifier keys alone never operate the game.  On the 桌面分身,
# Remote Desktop re-sends their state as real key presses whenever its window
# gains or loses focus (live 2026-10-03: 公会、小屋、酒馆 stopped as 「键盘」
# while nobody typed into the clone).
STATE_KEYS = frozenset(
    {
        0x10, 0x11, 0x12,  # Shift, Ctrl, Alt
        0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,  # left/right Shift, Ctrl, Alt
        0x5B, 0x5C,  # Windows keys
        0x14, 0x90, 0x91,  # Caps Lock, Num Lock, Scroll Lock
        0x15, 0x19,  # IME Kana/Hangul, Kanji
    }
)  # fmt: skip
# Taking a screenshot never operates the game (live 2026-10-07: Leo's
# PrintScreen for a bug report stopped 一键完成日常 on the 桌面分身).
IGNORED_KEYS = STATE_KEYS | {0x2C}  # VK_SNAPSHOT


def mouse_takeover(msg: int, flags: int, window_is_game: bool, game_in_front: bool) -> bool:
    """A real press or wheel on the game window while it already had focus."""
    return (
        msg in MOUSE_PRESS_MESSAGES
        and not flags & LLMHF_INJECTED
        and window_is_game
        and game_in_front
    )


def key_takeover(msg: int, flags: int, vk: int, game_in_front: bool) -> bool:
    """A real key press while the game has the keyboard (F-keys and state keys excepted)."""
    # The player closing the game is no 闪退 to reopen (decision 9 of the 10-10 plan, its default).
    closes_game = vk == VK_F4 and bool(flags & LLKHF_ALTDOWN)
    return (
        msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
        and not flags & LLKHF_INJECTED
        and (closes_game or (vk not in FUNCTION_KEYS and vk not in IGNORED_KEYS))
        and game_in_front
    )


def game_window_handles(executor) -> set[int]:
    interaction = getattr(executor, "interaction", None)
    window = getattr(interaction, "hwnd_window", None)
    handles = {getattr(window, "hwnd", None), getattr(window, "top_hwnd", None)}
    handles.update(info[0] for info in (getattr(window, "hwnds", None) or []) if info)
    return {handle for handle in handles if handle}


class TakeoverMonitor:
    """Low-level input listener, started once the first task runs."""

    def __init__(self, executor):
        self.executor = executor
        self._stopped_task = None
        self._listeners = []
        try:
            from src.utils.clone_desktop import in_clone

            self.in_clone = in_clone()
        except Exception:
            self.in_clone = False

    # -- decisions (run inside the hook: keep them fast) -----------------------

    def _running_task(self):
        task = getattr(self.executor, "current_task", None)
        if task is None or task not in (getattr(self.executor, "onetime_tasks", None) or []):
            return None  # idle, or a trigger such as auto-login
        if task is self._stopped_task:
            return None
        if getattr(task, "player_plays_along", False):
            return None  # e.g. recording a fight: the player's clicks are expected
        return task

    def _root_is_game(self, hwnd) -> bool:
        import win32gui

        handles = game_window_handles(self.executor)
        if not hwnd or not handles:
            return False
        try:
            root = win32gui.GetAncestor(hwnd, 2)  # GA_ROOT
        except Exception:
            return False
        return hwnd in handles or root in handles

    def on_mouse(self, msg, data) -> bool:
        if self.in_clone:
            # Input reaches the 桌面分身 only through its viewer window, mostly
            # by accident: a click to focus the viewer (the game is always in
            # front inside the clone), or typing and screenshots meant for the
            # own desktop (live 2026-10-07: Right arrow, PrintScreen; 10-03 a
            # click).  The run there is stopped with the tool's stop button.
            return False
        try:
            if msg in MOUSE_PRESS_MESSAGES and not data.flags & LLMHF_INJECTED:
                task = self._running_task()
                if task is not None:
                    import win32gui

                    hwnd = win32gui.WindowFromPoint((data.pt.x, data.pt.y))
                    # The hook runs before the click is handled, so the
                    # foreground is still the window that had focus.
                    front = self._root_is_game(win32gui.GetForegroundWindow())
                    # While paused, the click that brings the game forward
                    # may have changed its screen too.
                    front = front or bool(getattr(task, "paused", False))
                    if mouse_takeover(msg, data.flags, self._root_is_game(hwnd), front):
                        self._take_over(task, "鼠标")
        except Exception:
            pass
        return False  # never hand the event to pynput callbacks (none are set)

    def on_key(self, msg, data) -> bool:
        if self.in_clone:
            return False
        try:
            if msg in (WM_KEYDOWN, WM_SYSKEYDOWN) and not data.flags & LLKHF_INJECTED:
                task = self._running_task()
                if task is not None:
                    import win32gui

                    front = self._root_is_game(win32gui.GetForegroundWindow())
                    if key_takeover(msg, data.flags, data.vkCode, front):
                        if not getattr(task, "paused", False):
                            logger.info(f"takeover: real key vk=0x{data.vkCode:02X} on the game")
                        self._take_over(task, "键盘")
        except Exception:
            pass
        return False

    def _take_over(self, task, source: str) -> None:
        if getattr(task, "paused", False):
            # Paused for the player to step in: no stop, a look after 继续.
            if not getattr(task, "player_stepped_in", False):
                logger.info(f"takeover: the player used the paused game ({source})")
            task.player_stepped_in = True
            return
        self._stopped_task = task
        # Off the hook thread: Windows drops a hook that answers slowly.
        threading.Thread(target=self._stop, args=(task, source), daemon=True).start()

    def _stop(self, task, source: str) -> None:
        if getattr(self.executor, "current_task", None) is not task:
            return
        self.executor.stop_current_task()
        try:
            task.log_warning(
                f"检测到你在操作游戏（{source}），已自动停止「{task.name}」。"
                "需要继续时重新点开始即可。",
                notify=True,
            )
        except Exception:
            logger.warning(f"takeover: stopped {task.name} ({source})")

    def on_task(self, task) -> None:
        # Emitted when a one-time task starts (running) and when it ends; a
        # start, even of the task stopped last time, is watched again.
        if getattr(task, "running", False):
            self._stopped_task = None

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> bool:
        try:
            from pynput import keyboard, mouse
        except Exception as exc:  # pragma: no cover - missing optional backend
            logger.warning(f"takeover monitor unavailable: {exc}")
            return False
        self._listeners = [
            mouse.Listener(win32_event_filter=self.on_mouse),
            keyboard.Listener(win32_event_filter=self.on_key),
        ]
        for listener in self._listeners:
            listener.daemon = True
            listener.start()
        logger.info("takeover monitor started")
        return True


def install_takeover_monitor() -> bool:
    """Start watching for a user takeover when the first task runs."""
    if sys.platform != "win32" or getattr(install_takeover_monitor, "_installed", False):
        return False
    from ok.core.events import communicate

    install_takeover_monitor._installed = True
    state = {"monitor": None}

    def on_task(task):
        monitor = state["monitor"]
        if monitor is None:
            if not getattr(task, "running", False):
                return
            from ok import og

            executor = getattr(og, "executor", None)
            if executor is None:
                return
            monitor = TakeoverMonitor(executor)
            if not monitor.start():
                return
            state["monitor"] = monitor
        monitor.on_task(task)

    communicate.task.connect(on_task)
    install_takeover_monitor._state = state
    install_takeover_monitor._on_task = on_task
    return True
