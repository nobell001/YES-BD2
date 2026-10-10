"""Read-only lookups shared by the new pages: tasks, run records, progress.

Nothing here writes a file: the map progress is read through a store whose
``save`` does nothing, so opening a page can never change what a run sees.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from ok import Logger

from src.ui.shell.widgets import t, tf

logger = Logger.get_logger(__name__)

ASSET_DIR = Path(__file__).resolve().parents[3] / "assets" / "ui"

DAILY_BATCH = "一键完成日常"
WEEKLY_BATCH = "一键完成周常"

# Batch config key -> (short name, icon, kind).  Order follows the batch.
# The kind (theme.KINDS) tints the icon in 深色.
CHILD_META = {
    "公会、小屋、酒馆": ("公会小屋酒馆", "house", "claim"),
    "领取常客圣石": ("常客圣石", "gem", "claim"),
    "快速狩猎": ("快速狩猎", "crosshair", "fight"),
    "免费抽抽乐": ("抽抽乐", "gift", "claim"),
    "爛装强化分解": ("爛装分解", "recycle", "grow"),
    "每日精炼一次": ("每日精炼", "sparkles", "grow"),
    "广场女神像": ("广场女神像", "landmark", "grow"),
    "自动PVP": ("镜中之战", "swords", "fight"),
    "跑商": ("每日跑商", "coins", "trade"),
    "每周跑图": ("每周跑图", "map", "map"),
    "活动每日战斗": ("活动战斗", "zap", "fight"),
    "领取任务奖励": ("任务奖励", "list-checks", "claim"),
    "领取通行证": ("通行证", "ticket", "claim"),
    "领取邮件": ("邮件", "mail", "claim"),
    "领取活动奖励": ("活动奖励", "star", "claim"),
    "浏览街机菜单": ("街机菜单", "gamepad-2", "week"),
    "小屋增加人气": ("小屋人气", "heart", "week"),
    "制作装备": ("制作装备", "hammer", "week"),
    "末日之书": ("末日之书", "book-open", "week"),
}
# Task display name -> (icon, kind) for tasks outside the batches.
TASK_ICONS = {
    "回到主页": ("undo-2", "plain"),
    "自动登录游戏": ("log-in", "plain"),
}


def og():
    from ok import og as _og

    return _og


def executor():
    return getattr(og(), "executor", None)


def onetime_tasks() -> list:
    return list(getattr(executor(), "onetime_tasks", None) or [])


def trigger_tasks() -> list:
    return list(getattr(executor(), "trigger_tasks", None) or [])


def task_by_name(name: str):
    for task in onetime_tasks() + trigger_tasks():
        if str(getattr(task, "name", "")) == name:
            return task
    return None


def task_by_class_name(class_name: str):
    for task in onetime_tasks() + trigger_tasks():
        if type(task).__name__ == class_name:
            return task
    return None


def current_task():
    return getattr(executor(), "current_task", None)


def busy() -> bool:
    """A run is going: a task the player (or a batch) started.

    The trigger tasks (自动登录游戏) are not runs: the executor makes each one
    the current task for its check every second.  Live 4K 2026-10-10 with the
    game on a menu: the login check never found a login screen, kept
    waiting, and every 开始 for 2 minutes was refused with "自动登录游戏 is
    running".  A started task runs after that check; a batch still waits for
    a login that is really going on (DailyBatchTask._auto_login_pending).
    """
    task = current_task()
    return task is not None and not any(task is each for each in trigger_tasks())


# ---------------------------------------------------------------- accounts


def _tick_keys(batch) -> list[str]:
    return [child.config_key for child in getattr(batch, "child_tasks", ()) or ()]


def switch_account(account_id: str) -> bool:
    """Make another game account current (GitHub issue #4): its records and
    its own 一键日常 ticks come in, the old account's ticks are kept."""
    from src.utils import accounts

    if busy():
        return False
    batch = task_by_name(DAILY_BATCH)
    try:
        return accounts.switch(account_id, getattr(batch, "config", None), _tick_keys(batch))
    except (accounts.AccountError, OSError) as exc:
        logger.error(f"switch account failed: {exc}")
        return False


def add_account():
    """A new account starting with the current account's ticks."""
    from src.utils import accounts

    batch = task_by_name(DAILY_BATCH)
    config = getattr(batch, "config", None) or {}
    ticks = {key: bool(config.get(key, True)) for key in _tick_keys(batch)}
    try:
        return accounts.add("", ticks)
    except (accounts.AccountError, OSError) as exc:
        logger.error(f"add account failed: {exc}")
        return None


def waiting_for_login() -> bool:
    """一键日常 is queued behind the auto-login (game opening or logging in)."""
    return any(getattr(task, "_start_after_login", False) for task in onetime_tasks())


def tr(text: str) -> str:
    app = getattr(og(), "app", None)
    try:
        return app.tr(text) if app is not None else text
    except Exception:
        return text


@dataclass
class Child:
    key: str  # config key in the batch
    task: object | None
    name: str  # the task's own display name
    short: str
    icon: str
    kind: str  # theme.KINDS
    included: bool  # switched on in the batch
    weekly: bool = False  # a 周常: done once a game week (Leo 2026-10-09)


def batch_children(batch) -> list[Child]:
    if batch is None:
        return []
    children = []
    config = getattr(batch, "config", {}) or {}
    for child in getattr(batch, "child_tasks", ()) or ():
        task = None
        for candidate in onetime_tasks():
            if type(candidate) is child.task_class:
                task = candidate
                break
        name = str(getattr(task, "name", None) or child.config_key)
        short, icon, kind = CHILD_META.get(child.config_key, (name, "circle-dashed", "plain"))
        children.append(
            Child(
                child.config_key,
                task,
                name,
                short,
                icon,
                kind,
                bool(config.get(child.config_key, True)),
                bool(getattr(child, "weekly", False)),
            )
        )
    return children


def sync_weekly_ticks(batch) -> None:
    """Untick the 周常 done this week, tick last week's again (src.tasks.weekly_ticks)."""
    if batch is None or not hasattr(batch, "_sync_weekly_ticks"):
        return
    try:
        from src.tasks.run_history import default_store

        batch._sync_weekly_ticks(default_store())
    except Exception as exc:
        logger.warning(f"weekly ticks: sync failed ({exc})")


def child_done(child: Child) -> bool:
    """Done today, or for a 周常 done this game week."""
    return done_this_week(child.name) if child.weekly else done_today(child.name)


def task_look(task) -> tuple[str, str]:
    """(icon, kind) of any task."""
    name = str(getattr(task, "name", ""))
    if name in TASK_ICONS:
        return TASK_ICONS[name]
    for batch_name in (DAILY_BATCH, WEEKLY_BATCH):
        for child in batch_children(task_by_name(batch_name)):
            if child.task is task:
                return child.icon, child.kind
    return "circle-dashed", "plain"


# ---------------------------------------------------------------- run records


def history():
    from src.tasks.run_history import default_store

    return default_store()


def done_today(name: str) -> bool:
    try:
        return history().is_completed_today(name)
    except Exception:
        return False


def done_this_week(name: str) -> bool:
    try:
        return history().is_completed_this_week(name)
    except Exception:
        return False


def last_run(name: str) -> dict | None:
    try:
        return history().last_run(name)
    except Exception:
        return None


def _local(ts: float) -> datetime:
    """A moment on the player's PC clock (their own time zone)."""
    return datetime.fromtimestamp(ts).astimezone()


def clock_text(ts: float | None) -> str:
    if not ts:
        return ""
    return _local(ts).strftime("%H:%M")


def day_text(ts: float | None) -> str:
    """'今天' / '昨天' / '10月5日' for a finished time (game days)."""
    if not ts:
        return ""
    from src.tasks.run_history import day_start_ts

    today = day_start_ts()
    if ts >= today:
        return "今天"
    if ts >= today - 86400:
        return "昨天"
    moment = _local(ts)
    return tf("{month}月{day}日", month=moment.month, day=moment.day)


def recent_days(name: str) -> list:
    try:
        return history().recent_days(name)
    except Exception:
        return [None] * 7


def estimate_seconds(names) -> float | None:
    """Sum of the last run times; None when nothing has been timed yet."""
    total = 0.0
    known = False
    for name in names:
        record = last_run(name) or {}
        duration = record.get("duration")
        if isinstance(duration, (int, float)) and duration > 0:
            total += duration
            known = True
    return total if known else None


def _day_word(moment: datetime, template_today: str, template_tomorrow: str, **values) -> str:
    """Pick 今天/明天 by the player's own calendar day, not the game's."""
    days = (moment.date() - _local(time.time()).date()).days
    return tf(template_today if days <= 0 else template_tomorrow, **values)


def next_refresh_text() -> str:
    """Next daily reset on the player's clock: before it 今天, after it 明天.

    The reset is 08:00 UTC+8; in Taiwan at 01:00 that is still 今天 08:00.
    """
    from src.tasks.run_history import day_start_ts

    moment = _local(day_start_ts() + 86400)
    return _day_word(moment, "今天 {time}", "明天 {time}", time=moment.strftime("%H:%M"))


def daily_reset_clock() -> str:
    """The daily reset (08:00 UTC+8) as the player's local time."""
    from src.tasks.run_history import day_start_ts

    return _local(day_start_ts()).strftime("%H:%M")


def weekly_reset_parts() -> dict:
    """The weekly reset (Monday 08:00 UTC+8) as the player's weekday and time."""
    from src.tasks.run_history import week_start_ts

    moment = _local(week_start_ts() + 7 * 86400)
    return {"weekday": t(WEEKDAYS[moment.weekday()]), "time": moment.strftime("%H:%M")}


def sale_refresh_clock() -> str:
    """The sale table switches days at 23:00 UTC+8; this is that on the player's clock."""
    from src.tasks.map_trade.calendar import SALE_PRICE_REFRESH_HOUR
    from src.utils.game_day import GAME_TZ

    moment = datetime.now(GAME_TZ).replace(
        hour=SALE_PRICE_REFRESH_HOUR, minute=0, second=0, microsecond=0
    )
    return moment.astimezone().strftime("%H:%M")


WEEKDAYS = "一二三四五六日"


def today_title() -> str:
    now = _local(time.time())
    return tf(
        "{month}月{day}日 周{weekday}",
        month=now.month,
        day=now.day,
        weekday=t(WEEKDAYS[now.weekday()]),
    )


# ---------------------------------------------------------------- pictures


@lru_cache(maxsize=None)
def _index(folder: str) -> dict:
    try:
        return json.loads((ASSET_DIR / folder / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def dish_picture(name: str) -> str | None:
    file = _index("dishes").get(name)
    return str(ASSET_DIR / "dishes" / file) if file else None


def item_picture(name: str) -> str | None:
    file = _index("items").get(name)
    return str(ASSET_DIR / "items" / file) if file else None


def cartridge_picture(code: str) -> str | None:
    path = ASSET_DIR / "cartridges" / f"{code}.png"
    return str(path) if path.exists() else None


# ---------------------------------------------------------------- map progress


@dataclass
class CardProgress:
    card_id: str
    code: str  # S1 / R2 / E3: picture and short label
    number: int
    name: str
    story: bool
    maps: int
    done_maps: int
    complete: bool
    category: str = "story"  # story / character / event


@dataclass
class MapProgress:
    cards: list[CardProgress]
    used: dict[str, int]
    limits: dict[str, int]

    @property
    def cards_done(self) -> int:
        return sum(1 for card in self.cards if card.complete)

    @property
    def maps_total(self) -> int:
        return sum(card.maps for card in self.cards)

    @property
    def maps_done(self) -> int:
        return sum(card.done_maps for card in self.cards)


def map_progress(account_id: str | None = None) -> MapProgress | None:
    """This week's 跑图; ``account_id`` reads another game account's records."""
    try:
        from src.tasks.map_trade.collector_constants import UNSUPPORTED_COLLECTION_CARD_NUMBERS
        from src.tasks.map_trade.models import COLLECTABLE_CARDS
        from src.tasks.map_trade.progress import ProgressStore

        class _ReadOnlyStore(ProgressStore):
            def save(self) -> None:  # never touch the run's file from the UI
                return None

            def _read_json(self) -> dict:
                try:
                    value = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    return {}
                return value if isinstance(value, dict) else {}

        from src.tasks.map_trade.progress import DEFAULT_PROGRESS_PATH
        from src.utils import accounts

        store = _ReadOnlyStore(accounts.scoped(DEFAULT_PROGRESS_PATH, account_id))
        state = store.load()
        cards = []
        prefixes = {"story": "S", "character": "R", "event": "E"}
        for card in COLLECTABLE_CARDS:
            if card.number in UNSUPPORTED_COLLECTION_CARD_NUMBERS and card.category == "story":
                continue
            story = card.category == "story"
            done = len(state.completed_targets(card.card_id))
            cards.append(
                CardProgress(
                    card_id=card.card_id,
                    code=f"{prefixes.get(card.category, 'S')}{card.number}",
                    number=card.number,
                    name=card.name,
                    story=story,
                    category=card.category,
                    maps=len(card.targets),
                    done_maps=done,
                    complete=state.card_complete(card.card_id),
                )
            )
        return MapProgress(
            cards=cards,
            used=store.effective_daily_counts(),
            # Today's limits as the game showed them (they differ per player).
            limits={name: store.limit_of(name) for name in ("吸收", "召集", "压制")},
        )
    except Exception as exc:
        logger.error(f"read map progress failed: {exc}")
        return None


# ---------------------------------------------------------------- trade


def sale_date(now: datetime | None = None) -> date:
    from src.tasks.map_trade.calendar import UTC_PLUS_8, sale_price_calendar_date

    return sale_price_calendar_date(now or datetime.now(UTC_PLUS_8))


def sale_days() -> dict:
    try:
        from src.tasks.map_trade.sale_days import bundled_sale_days

        return bundled_sale_days()
    except Exception as exc:
        logger.error(f"read sale calendar failed: {exc}")
        return {}


def trade_phases_done() -> dict[str, bool]:
    """买 / 制作料理 / 卖 done in their current period (the trade's own ledger)."""
    try:
        from src.tasks.map_trade.phase_ledger import PhaseLedger

        ledger = PhaseLedger()
        return {phase: ledger.done(phase) for phase in ("买", "制作料理", "卖")}
    except Exception:
        return {"买": False, "制作料理": False, "卖": False}


# ---------------------------------------------------------------- game window


def game_window() -> dict:
    """{'connected', 'title', 'size'} for the sidebar footer."""
    manager = getattr(og(), "device_manager", None)
    result = {"connected": False, "title": "", "size": ""}
    if manager is None:
        return result
    try:
        window = getattr(manager, "hwnd_window", None)
        capture = getattr(manager, "capture_method", None)
        if window is not None and getattr(window, "exists", False):
            result["connected"] = capture is not None
            result["title"] = str(getattr(window, "title", "") or "")
            width, height = (
                int(getattr(window, "width", 0) or 0),
                int(getattr(window, "height", 0) or 0),
            )
            if width and height:
                result["size"] = f"{width}×{height}"
    except Exception:
        pass
    return result
