"""Game sizes the tool is built and tested for, and what happens on others.

A player on 2026-10-09 ran the game in a smaller window: the tool started
anyway (ok-script accepts any 16:9 size from 1280x720 up), the shrunken
cartridge numbers and buttons were never recognised, and 跑图 slid the
cartridge bar and clicked the map's back button for minutes on end.  Leo
(2026-10-09) chose 「提醒但照跑」, then asked for it to be solved, not only
warned about (the player's window was 1467x824).  So a run first sets the
game to 1920x1080 itself, the way 首页「游戏视窗大小」「调整」 does, and
warns only when that cannot be done (a screen smaller than 1920x1080).

A player on 2026-11-27: 「开自动会自己把窗口变成全屏，能不能窗口」.  On a
1920x1080 screen a framed 1920x1080 window does not fit above the taskbar,
so the resize takes the title bar off and the game covers the whole screen
(a maximised game window there is 1920x1009 or so, also too small).  The
size is still needed for the run, so when the run ends the window is put
back exactly as it was (``fixed_for_run``), and the notice says so.
"""

from __future__ import annotations

import contextlib
import itertools
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
# The last resize a run made: what to put back when that run ends.
_to_restore: dict = {}
_restore_ids = itertools.count(1)


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
    head = (
        f"游戏画面是 {size[0]}×{size[1]}，不是 1920×1080、2560×1440、3840×2160，"
        "很容易认不准、卡住，任务很可能失败。"
    )
    if "窗口模式" in reason:
        # The game's own 全屏 keeps it at the screen's size (a 16:10 screen,
        # 2026-10-12): the reason already says what to change in the game,
        # and 「改成全屏」 would be the wrong advice.
        return f"{head}没能自动调成 1920×1080：{reason}这次照常执行。"
    why = f"没能自动调成 1920×1080（{reason}）。" if reason else ""
    return (
        f"{head}{why}建议把游戏改成全屏，或在首页「游戏视窗大小」"
        "按「调整」。这次照常执行。"
    )


def fixed_message(size: tuple[int, int], covers_screen: bool = False) -> str:
    text = (
        f"游戏画面原本是 {size[0]}×{size[1]}，这个大小容易认不准，"
        "已自动调成 1920×1080"
    )
    if covers_screen:
        text += "（屏幕放不下带标题栏的 1920×1080 窗口，跑的时候会铺满屏幕）"
    return text + "，跑完会改回原来的窗口。"


def restored_message() -> str:
    return "跑完了，游戏窗口已改回原来的大小。"


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
        result = resize_game_window(manager, FIX_SIZE, executor=None)
    except Exception as exc:
        return str(exc) or type(exc).__name__
    if getattr(result, "changed", False):
        _to_restore.clear()
        _to_restore.update(
            id=next(_restore_ids),
            manager=manager,
            result=result,
            borderless=bool(getattr(result, "borderless", False)),
        )
    return ""


def put_back(entry: dict) -> str:
    """Give the window back the size and frame it had before ``entry``'s resize."""
    try:
        from src.ui.manual_resolution import restore_game_window
    except Exception as exc:  # pragma: no cover - Windows-only imports
        return str(exc) or type(exc).__name__
    try:
        return restore_game_window(entry["manager"], entry["result"])
    except Exception as exc:
        return str(exc) or type(exc).__name__


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
            text = fixed_message(size, bool(_to_restore.get("borderless")))
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


@contextlib.contextmanager
def fixed_for_run(task, *, restore=None, **fix_kwargs):
    """``fix_or_warn`` before the run; the window put back when the run ends.

    Only the run that resized puts it back: 一键日常's children find the
    size already fixed and leave it to the batch.  The run's end includes a
    Stop and an error.
    """
    before = _to_restore.get("id")
    fix_or_warn(task, **fix_kwargs)
    mine = _to_restore.get("id")
    owner = mine is not None and mine != before
    try:
        yield
    finally:
        if owner and _to_restore.get("id") == mine:
            give_back_now(task, restore=restore)


def give_back_now(task, *, restore=None) -> None:
    """Put a run's resized window back now, e.g. before 做完关闭游戏 closes
    the game, so the game keeps the player's own size for its next start."""
    if not _to_restore:
        return
    entry = dict(_to_restore)
    _to_restore.clear()
    why = (restore or put_back)(entry)
    try:
        if not why:
            task.info_set(NOTICE_KEY, restored_message())
            task.log_info(restored_message())
        else:
            task.log_info(f"游戏窗口没有改回原来的大小：{why}")
    except Exception:
        pass
