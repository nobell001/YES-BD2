"""Game sizes the tool is built and tested for, and what happens on others.

A player on 2026-10-09 ran the game in a smaller window: the tool started
anyway (ok-script accepts any 16:9 size from 1280x720 up), the shrunken
cartridge numbers and buttons were never recognised, and 跑图 slid the
cartridge bar and clicked the map's back button for minutes on end.  Leo
(2026-10-09) chose 「提醒但照跑」, then asked for it to be solved, not only
warned about (the player's window was 1467x824).  So a run first sets the
game to 1920x1080 itself, the way 首页「游戏视窗大小」「调整」 does, and
warns only when that cannot be done (a screen smaller than 1920x1080).
"""

from __future__ import annotations

import time

SUPPORTED_SIZES = ((1920, 1080), (2560, 1440), (3840, 2160))
# The smallest supported size: the one most screens fit, and it takes the
# least of the screen from a player who wanted a small window.
FIX_SIZE = (1920, 1080)
# The picture the tool captures follows the new window size within a frame
# or two; give it this long before the run starts.
FIX_SETTLE_SECONDS = 3.0
# A window sized by hand can be a pixel or two off.
TOLERANCE = 2
# One notice is enough while the batch's children and the scheduler's
# retries each start on the same window.
NOTIFY_GAP_SECONDS = 600.0

_last_notified = {"at": 0.0}
# A resize that failed is not tried again for each child of the same batch.
_last_failed_fix = {"at": 0.0}


def supported(width: int, height: int) -> bool:
    return any(
        abs(int(width) - w) <= TOLERANCE and abs(int(height) - h) <= TOLERANCE
        for w, h in SUPPORTED_SIZES
    )


def current_size(executor) -> tuple[int, int] | None:
    """The game's client size, None while no game window is known."""
    manager = getattr(executor, "device_manager", None)
    # The captured picture's size first: what every recognition works on
    # (ok's own 16:9 check reads the same).
    method = getattr(manager, "capture_method", None)
    try:
        connected = method is not None and (
            not hasattr(method, "connected") or method.connected()
        )
    except Exception:
        connected = False
    if connected:
        width = int(getattr(method, "width", 0) or 0)
        height = int(getattr(method, "height", 0) or 0)
        if width > 0 and height > 0:
            return width, height
    window = getattr(manager, "hwnd_window", None)
    if window is None or not getattr(window, "exists", False):
        return None
    width = int(getattr(window, "width", 0) or 0)
    height = int(getattr(window, "height", 0) or 0)
    if width <= 0 or height <= 0:
        return None
    return width, height


def unsupported_size(executor) -> tuple[int, int] | None:
    """The game's size when it is one the tool does not support, else None."""
    size = current_size(executor)
    if size is None or supported(*size):
        return None
    return size


def message(size: tuple[int, int], reason: str = "") -> str:
    why = f"没能自动调成 1920×1080（{reason}）。" if reason else ""
    return (
        f"游戏画面是 {size[0]}×{size[1]}，工具只在 1920×1080、2560×1440、3840×2160 测过，"
        f"其他大小可能认不准、卡住。{why}建议把游戏改成全屏，或在首页「游戏视窗大小」"
        "按「调整」。这次照常执行。"
    )


def fixed_message(size: tuple[int, int]) -> str:
    return (
        f"游戏画面原本是 {size[0]}×{size[1]}，工具在这个大小容易认不准，"
        "已自动调成 1920×1080。"
    )


def resize_to_fix(executor) -> str:
    """Set the game window to ``FIX_SIZE``; "" when done, else why not."""
    try:
        from src.ui.manual_resolution import resize_game_window
    except Exception as exc:  # pragma: no cover - Windows-only imports
        return str(exc) or type(exc).__name__
    manager = getattr(executor, "device_manager", None)
    if manager is None:
        return "没有连接游戏"
    try:
        # executor=None: this runs at the start of the run itself, before it
        # clicks anything, so the 「任务正在运行」 check does not apply.
        resize_game_window(manager, FIX_SIZE, executor=None)
    except Exception as exc:
        return str(exc) or type(exc).__name__
    return ""


def _refresh_capture(executor) -> None:
    """The capture's size only follows the window on a new frame; nothing
    else captures before the run starts (audit #65: a resize that took was
    reported as failed and not tried again for ten minutes)."""
    method = getattr(getattr(executor, "device_manager", None), "capture_method", None)
    get_frame = getattr(method, "get_frame", None)
    if callable(get_frame):
        try:
            get_frame()
        except Exception:
            pass


def _wait_for_supported(executor, sleep, monotonic) -> bool:
    deadline = monotonic() + FIX_SETTLE_SECONDS
    while True:
        _refresh_capture(executor)
        size = current_size(executor)
        if size is not None and supported(*size):
            return True
        if monotonic() >= deadline:
            return False
        sleep(0.2)


def should_notify(now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    if _last_notified["at"] and now - _last_notified["at"] < NOTIFY_GAP_SECONDS:
        return False
    _last_notified["at"] = now
    return True


NOTICE_KEY = "画面大小提醒"


def fix_or_warn(task, *, resize=None, sleep=time.sleep, monotonic=time.monotonic) -> bool:
    """Before a run: set an untested game size to 1920x1080, else tell the user.

    True when the game is still at an untested size; the run goes on either way.
    """
    executor = getattr(task, "executor", None)
    size = unsupported_size(executor)
    if size is None:
        return False
    now = monotonic()
    if _last_failed_fix["at"] and now - _last_failed_fix["at"] < NOTIFY_GAP_SECONDS:
        reason = _last_failed_fix.get("reason", "")
    else:
        reason = (resize or resize_to_fix)(executor)
    if not reason:
        if _wait_for_supported(executor, sleep, monotonic):
            text = fixed_message(size)
            task.info_set(NOTICE_KEY, text)
            task.log_info(text, notify=True)
            return False
        after = current_size(executor)
        reason = f"调整后画面是 {after[0]}×{after[1]}" if after else "调整后读不到画面大小"
    if not _last_failed_fix["at"] or now - _last_failed_fix["at"] >= NOTIFY_GAP_SECONDS:
        _last_failed_fix.update(at=now, reason=reason)
    text = message(size, reason)
    task.info_set(NOTICE_KEY, text)
    task.log_warning(text, notify=should_notify())
    return True
