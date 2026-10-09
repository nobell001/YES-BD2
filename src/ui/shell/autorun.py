"""打开工具就自动跑一键日常：玩家在首页自己勾（默认不勾）。

Leo 2026-10-09（玩家建议 YES-BD2 issue #1：配合 Windows 任务计划程序每天
开工具跑日常）：之前拿掉的「打开就跑」改成玩家自己在首页选；同一个勾
也打开启动器的「自动启动」，点启动器就会一路跑到日常。勾了之后，
工具打开几秒后照「跑没跑完的」开始（不跳确认视窗，倒数就是确认），今天（周常是本周）做完的不再跑；
游戏没开会自己打开并登录，不再问。都做完了、已经在跑、或在桌面分身里
（由外面的工具交派）就不跑。
"""

from __future__ import annotations

import time

from ok import Logger

from src.ui.shell import data

logger = Logger.get_logger(__name__)

CONFIG_KEY = "打开工具时自动开始"
DELAY_MS = 5000

# When the scheduled start is due (首页 counts down to it, Leo 2026-10-09:
# players must see that it is about to run); None when nothing is pending.
_due: float | None = None


def enabled() -> bool:
    batch = data.task_by_name(data.DAILY_BATCH)
    return bool((getattr(batch, "config", None) or {}).get(CONFIG_KEY, False))


def set_enabled(on: bool) -> None:
    batch = data.task_by_name(data.DAILY_BATCH)
    if batch is not None:
        batch.config[CONFIG_KEY] = bool(on)
    set_launcher_auto_start(on)


def set_launcher_auto_start(on: bool) -> bool:
    """The launcher's own 「自动启动」: it opens the tool 10 s after it starts.

    Leo 2026-10-09: opening the launcher should go all the way to 一键日常,
    so the one box on 首页 sets both.  Only in installs the launcher made.
    """
    try:
        import pyappify

        if not pyappify.get_app_json_path():
            return False
        pyappify.set_auto_start(bool(on))
        return True
    except Exception as exc:
        logger.warning(f"auto-run on open: launcher auto start not changed ({exc})")
        return False


def remaining() -> list:
    batch = data.task_by_name(data.DAILY_BATCH)
    return [
        child
        for child in data.batch_children(batch)
        if child.included and not data.child_done(child)
    ]


def should_start(in_clone: bool) -> str | None:
    """None when it should start now, else why not (for the log)."""
    if in_clone:
        return "in the clone"
    if not enabled():
        return "off"
    if not data.executor() or data.busy():
        return "busy"
    if not remaining():
        return "nothing left today"
    return None


def maybe_start() -> bool:
    """Start 一键日常 (only what is left) when the player ticked it."""
    from src.ui.shell import actions, clone_flow
    from src.utils.clone_desktop import in_clone

    reason = should_start(in_clone())
    if reason is None and clone_flow.busy_in_clone():
        reason = "running in the clone"
    if reason is not None:
        logger.info(f"auto-run on open: not started ({reason})")
        return False
    from src.tasks.DailyBatchTask import RUN_MODE_INCOMPLETE

    if not actions.game_running():
        clone_flow.log_in_this_run()  # opens the game and logs in, without asking
    logger.info("auto-run on open: starting 一键完成日常 (only what is left)")
    # No window: nothing to ask, and the game opens on its own if it is closed.
    return actions.start(data.task_by_name(data.DAILY_BATCH), None, RUN_MODE_INCOMPLETE)


def schedule(delay_ms: int = DELAY_MS) -> bool:
    """Count down on 首页, then start (unless the player cancels)."""
    global _due
    from PySide6.QtCore import QTimer

    from src.utils.clone_desktop import in_clone

    reason = should_start(in_clone())
    if reason is not None:
        logger.info(f"auto-run on open: not scheduled ({reason})")
        return False
    _due = time.time() + delay_ms / 1000
    logger.info(f"auto-run on open: starting in {delay_ms // 1000} s")
    QTimer.singleShot(delay_ms, _fire)
    return True


def _fire() -> None:
    global _due
    if _due is None:
        return  # cancelled
    _due = None
    maybe_start()


def seconds_left() -> int | None:
    if _due is None:
        return None
    return max(1, round(_due - time.time()))


def cancel() -> None:
    global _due
    if _due is not None:
        _due = None
        logger.info("auto-run on open: cancelled by the player")
