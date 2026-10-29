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
# 定时启动 does not give up when the tool is not ready yet (still opening,
# another task running): it looks again every few seconds, and only after
# this long says it could not start (Leo 2026-10-22 「有沒有確保 打開程式
# 就是直接開始日常」).
WAIT_RETRY_MS = 10_000
WAIT_MINUTES = 30
# The longest a 帳號 in line waits for the run before it.
QUEUE_WAIT_MINUTES = 240
# When another 帳號's 一键日常 was last seen running (0 = not lately).
_other_run_seen = 0.0
WAIT_REASONS = ("busy", "running in the clone")
BUSY_NOTE = "等了 {m} 分钟，工具一直在忙（有别的任务在跑），一键日常没能开始，这次没有跑。"
# Only these are decided by the 帳號 (what is left today is its own); the
# clone or a run already going is never switched under.
ACCOUNT_REASONS = (None, "nothing left today")
SWITCH_NOTE = "这个时段要跑账号「{name}」，但没能切换过去，这次没有跑。"
# Another 帳號's run still going when this one's time comes: this one waits
# for it, then 5 more minutes (Leo 2026-10-29 「他也不會幫你換帳號 無縫一定
# 會出問題」「跑完後間隔5分鐘再繼續」).
GAP_AFTER_RUN_S = 5 * 60

# When the scheduled start is due (首页 counts down to it, Leo 2026-10-09:
# players must see that it is about to run); None when nothing is pending.
_due: float | None = None
# A scheduled start waiting for the tool to be free: since when.
_waiting_since: float | None = None
# The 帳號 the slot runs (YES-BD2 #64), switched to once the tool is free.
_account = ""
# The slot's own items (Leo 2026-10-29), None = the 帳號's ticks.
_tasks: list[str] | None = None
# And their settings for that run (镜中之战's 倍数 ...).
_item_settings: dict = {}
# Other 帳號 whose slot came at the same time or while this one waits or
# runs: each starts once the run before it is over.
_queue: list[dict] = []


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
    """What is left today: of the slot's own items when it has them."""
    batch = data.task_by_name(data.DAILY_BATCH)
    return [
        child
        for child in data.batch_children(batch)
        if (child.included if _tasks is None else child.key in _tasks)
        and not data.child_done(child)
    ]


def should_start(in_clone: bool, scheduled: bool = False) -> str | None:
    """None when it should start now, else why not (for the log).

    ``scheduled``: 定时启动 asked for it, the 首页 box does not matter.
    """
    if in_clone:
        return "in the clone"
    if not scheduled and not enabled():
        return "off"
    if not data.executor():
        return "busy"
    if data.busy():
        if scheduled and data.current_task() is data.task_by_name(data.DAILY_BATCH):
            return "already running"
        return "busy"
    if not remaining():
        return "nothing left today"
    return None


def maybe_start(scheduled: bool = False) -> bool:
    """Start 一键日常 (only what is left) when the player ticked it.

    ``scheduled``: 定时启动 asked; a start that cannot happen (lock screen,
    not started) leaves a report that says why (schedule_ui).
    """
    from src.ui.shell import actions, clone_flow, schedule_ui

    reason = _why_not(scheduled)
    if reason is not None:
        logger.info(f"auto-run on open: not started ({reason})")
        return False
    if scheduled and not schedule_ui.before_start(_tasks, _item_settings):
        return False
    from src.tasks.DailyBatchTask import RUN_MODE_INCOMPLETE

    if not actions.game_running():
        clone_flow.log_in_this_run()  # opens the game and logs in, without asking
    logger.info("auto-run on open: starting 一键完成日常 (only what is left)")
    # No window: nothing to ask, and the game opens on its own if it is closed.
    started = actions.start(data.task_by_name(data.DAILY_BATCH), None, RUN_MODE_INCOMPLETE)
    if scheduled:
        schedule_ui.after_start(started)
    return started


def _why_not(scheduled: bool) -> str | None:
    from src.ui.shell import clone_flow
    from src.utils.clone_desktop import in_clone

    reason = should_start(in_clone(), scheduled)
    if reason is None and clone_flow.busy_in_clone():
        reason = "running in the clone"
    return reason


def schedule(
    delay_ms: int = DELAY_MS,
    scheduled: bool = False,
    account: str = "",
    tasks: list[str] | None = None,
    item_settings: dict | None = None,
) -> bool:
    """Count down on 首页, then start (unless the player cancels).

    ``scheduled``: a tool that is not free yet is waited for (:func:`_wait`).
    ``account``: the 帳號 the slot runs ("" = the current one); switched to
    before anything is decided, since what is left today is that 帳號's.
    ``tasks``: the slot's own items (None = the 帳號's ticks);
    ``item_settings``: their settings for this run only.
    """
    global _account, _tasks, _item_settings
    if scheduled:
        # "" is the 帳號 current when the slot comes, not after another
        # 帳號's run has switched away.
        account = account or _current_account()
    if _due is not None or _waiting_since is not None:
        if scheduled:
            _enqueue(account, tasks, item_settings)
            return True
        return False  # already counting down or waiting
    _account = account if scheduled else ""
    _tasks = list(tasks) if scheduled and tasks is not None else None
    _item_settings = dict(item_settings or {}) if scheduled else {}
    reason = _why_not(scheduled)
    if scheduled and _must_wait(reason):
        _wait(delay_ms)
        return True
    if scheduled and reason in ACCOUNT_REASONS:
        if not _take_account():
            _next()
            return False
        reason = _why_not(scheduled)
    if reason is not None:
        logger.info(f"auto-run on open: not scheduled ({reason})")
        if scheduled:
            _next()
        return False
    _count_down(delay_ms, scheduled)
    return True


def schedule_jobs(jobs: list[dict], delay_ms: int = DELAY_MS) -> bool:
    """Every slot that came at one time (:func:`scheduled_start.jobs_at`):
    the first starts, the other 帳號 follow one after the other."""
    started = False
    for job in jobs:
        started = schedule(delay_ms, scheduled=True, **job) or started
    return started


def _current_account() -> str:
    from src.utils import accounts

    try:
        return accounts.current_id()
    except Exception:
        return ""


def _enqueue(account: str, tasks, item_settings) -> None:
    if account == _account or any(job["account"] == account for job in _queue):
        logger.info(f"scheduled start: account {account} is already waiting, not queued twice")
        return
    logger.info(f"scheduled start: account {account} queued after the run in progress")
    _queue.append(
        {
            "account": account,
            "tasks": None if tasks is None else list(tasks),
            "item_settings": dict(item_settings or {}),
        }
    )
    _publish_queue()


def _publish_queue() -> None:
    # 做完关闭游戏 / 做完关机 wait for the last 帳號 in line.
    from src.utils import scheduled_start

    scheduled_start.queued = len(_queue)


def _next() -> None:
    """The next 帳號 in line, once the one before it has started or given up."""
    if not _queue:
        return
    job = _queue.pop(0)
    _publish_queue()
    schedule(DELAY_MS, scheduled=True, **job)


def _behind_daily() -> bool:
    """一键日常 is running for another 帳號 than the one this start runs."""
    return bool(_account) and _account != _current_account() and data.busy() and (
        data.current_task() is data.task_by_name(data.DAILY_BATCH)
    )


def _must_wait(reason: str | None) -> bool:
    """Not free yet: another task, another 帳號's 一键日常 (and the 5
    minutes after it), or the clone."""
    global _other_run_seen
    if reason == "already running" and _behind_daily():
        _other_run_seen = time.time()
        return True
    if _other_run_seen and time.time() - _other_run_seen < GAP_AFTER_RUN_S:
        return True
    return reason in WAIT_REASONS


def _wait(delay_ms: int) -> None:
    """Look again in a moment; after :data:`WAIT_MINUTES`, say why not."""
    global _waiting_since
    from PySide6.QtCore import QTimer

    from src.ui.shell.safe import guarded

    if _waiting_since is None:
        _waiting_since = time.time()
        logger.info("scheduled start: the tool is not free yet, waiting")
    behind = _other_run_seen and time.time() - _other_run_seen < GAP_AFTER_RUN_S + 60
    limit = QUEUE_WAIT_MINUTES if behind else WAIT_MINUTES
    if time.time() - _waiting_since >= limit * 60:
        _waiting_since = None
        from src.ui.shell import schedule_ui

        schedule_ui.report_failure(BUSY_NOTE.format(m=limit))
        _next()
        return
    QTimer.singleShot(WAIT_RETRY_MS, guarded("scheduled start wait", lambda: _retry(delay_ms)))


def _take_account() -> bool:
    """Switch to the 帳號 the slot runs: its ticks and today's records.

    False (and a report that says why) when the switch did not take.
    """
    global _account
    from src.utils import accounts

    wanted, _account = _account, ""
    if not wanted or wanted == accounts.current_id():
        return True
    known = {account.id: account for account in accounts.accounts()}
    if wanted not in known:
        # Deleted since: the slot runs the current one, as its window shows.
        logger.warning(f"scheduled start: account {wanted} is gone, running the current one")
        return True
    if data.switch_account(wanted):
        logger.info(f"scheduled start: switched to account {wanted}")
        return True
    from src.ui.shell import schedule_ui
    from src.ui.shell.accounts_ui import display_name

    schedule_ui.report_failure(
        SWITCH_NOTE.format(name=display_name(known[wanted]))
    )
    return False


def _retry(delay_ms: int) -> None:
    global _waiting_since
    if _waiting_since is None:
        return  # cancelled
    reason = _why_not(True)
    if _must_wait(reason):
        _wait(delay_ms)
        return
    _waiting_since = None
    if reason in ACCOUNT_REASONS:
        if not _take_account():
            _next()
            return
        reason = _why_not(True)
    if reason is not None:
        logger.info(f"scheduled start: not started ({reason})")
        _next()
        return
    _count_down(delay_ms, True)


def _count_down(delay_ms: int, scheduled: bool) -> None:
    global _due
    from PySide6.QtCore import QTimer

    _due = time.time() + delay_ms / 1000
    logger.info(f"auto-run on open: starting in {delay_ms // 1000} s")
    QTimer.singleShot(delay_ms, lambda: _fire(scheduled))


def schedule_on_open() -> bool:
    """When the tool opens: 定时启动 opened it, or the 首页 box is ticked."""
    from src.utils import scheduled_start

    if not scheduled_start.launched_by_schedule:
        return schedule()
    moment = scheduled_start.opened_at or scheduled_start.local_now()
    jobs = scheduled_start.jobs_at(scheduled_start.load(), moment)
    return schedule_jobs(jobs or [{"account": "", "tasks": None, "item_settings": {}}])


def _fire(scheduled: bool = False) -> None:
    global _due
    if _due is None:
        return  # cancelled
    _due = None
    if scheduled and _must_wait(_why_not(True)):
        _wait(DELAY_MS)  # something started during the count down
        return
    since = time.time()
    started = maybe_start(scheduled)
    if scheduled:
        _follow(since) if started else _next()


# How long a started run may take to show up (opening the game, logging in)
# before the next 帳號 in line stops waiting for it.
BEGIN_LIMIT_S = 10 * 60


def _follow(since: float) -> None:
    """The next 帳號 in line starts only after this run has begun and ended:
    switching 帳號 under a run would mix two 帳號's records."""
    if not _queue:
        return
    from PySide6.QtCore import QTimer

    from src.ui.shell import schedule_ui
    from src.ui.shell.safe import guarded

    global _other_run_seen
    waited = time.time() - since
    begun = schedule_ui.begun_since(since)
    if data.busy():
        _other_run_seen = time.time()
    if waited < QUEUE_WAIT_MINUTES * 60 and (
        data.busy() or (not begun and waited < BEGIN_LIMIT_S)
    ):
        QTimer.singleShot(WAIT_RETRY_MS, guarded("scheduled start queue", lambda: _follow(since)))
        return
    _next()


def seconds_left() -> int | None:
    if _due is None:
        return None
    return max(1, round(_due - time.time()))


def cancel() -> None:
    global _due, _waiting_since, _account, _tasks, _item_settings, _other_run_seen
    _waiting_since = None
    _other_run_seen = 0.0
    _queue.clear()
    _publish_queue()
    _account = ""
    _tasks = None
    _item_settings = {}
    if _due is not None:
        _due = None
        logger.info("auto-run on open: cancelled by the player")
