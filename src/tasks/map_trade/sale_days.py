"""Per-day sale checklist on the trade settings page (user choice, 2026-09-26).

Every date of the bundled price table becomes one multi-selection setting
("出售19号") listing that day's items, all ticked by default.  Unticking an
item keeps it from being sold on that date; items that are not in the
bundled table (online or custom tables) cannot be unticked and are sold.

The setting stores the ticked items, so an item later added to a date the
user already saved starts unticked (not sold, and logged as such); a new
date gets its own checklist with everything ticked.

Two tables are bundled (Leo 2026-11-10 「賣的部分先維持舊的直到19號」,
「19號之後我希望出售日曆可以自動換成新的」): the game's 2026-11-19 update
changes what sells at ↑120%.  The sale date picks the table, and the saved
ticks are carried over to the table in use once, so an item the new table
adds is sold while an item the player unticked stays unticked.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from datetime import date, datetime
from pathlib import Path

from src.tasks.map_trade.calendar import (
    UTC_PLUS_8,
    parse_calendar_payload,
    sale_price_calendar_date,
)
from src.tasks.map_trade.models import CalendarEntry
from src.tasks.map_trade.trader_constants import CALENDAR_DIR

BUNDLED_CALENDAR_FILE = CALENDAR_DIR / "price_calendar.v1.json"
# The table of the game's 2026-11-19 update, used for sale dates from then on.
# (Sale date: day N's prices start at 23:00 UTC+8 of day N-1.  Both tables are
# the same for the 19th-21st, so the exact moment makes no difference.)
NEXT_CALENDAR_FILE = CALENDAR_DIR / "price_calendar.20261119.v1.json"
NEXT_CALENDAR_FROM = date(2026, 11, 19)
OLD_TABLE = "v1"
NEXT_TABLE = "20261119"
# Hidden setting (ok-script hides "_" keys): the table the saved ticks fit.
SALE_TABLE_KEY = "_出售价表"


def sale_day_key(day: int) -> str:
    return f"出售{day}号"


def current_sale_date(now: datetime | None = None) -> date:
    return sale_price_calendar_date(now or datetime.now(UTC_PLUS_8))


def table_for(sale_date: date | None = None) -> str:
    """Which bundled table sells on ``sale_date`` (default: now)."""

    sale_date = sale_date or current_sale_date()
    return NEXT_TABLE if sale_date >= NEXT_CALENDAR_FROM else OLD_TABLE


def table_file(table: str) -> Path:
    return NEXT_CALENDAR_FILE if table == NEXT_TABLE else BUNDLED_CALENDAR_FILE


def bundled_calendar_file(sale_date: date | None = None) -> Path:
    return table_file(table_for(sale_date))


def _table_days(table: str) -> dict[int, tuple[CalendarEntry, ...]]:
    try:
        calendar = parse_calendar_payload(table_file(table).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {day: entries for day, entries in calendar.days.items() if entries}


def bundled_sale_days(sale_date: date | None = None) -> dict[int, tuple[CalendarEntry, ...]]:
    """Dates that have something to sell, in the table of ``sale_date`` (default: now)."""

    return _table_days(table_for(sale_date))


def every_sale_day() -> list[int]:
    """Dates with something to sell in either table (each gets a checklist)."""

    return sorted(set(_table_days(OLD_TABLE)) | set(_table_days(NEXT_TABLE)))


def every_bundled_entry() -> list[CalendarEntry]:
    """All goods of both tables: their names are known whichever one is in use."""

    return [
        entry
        for table in (OLD_TABLE, NEXT_TABLE)
        for entries in _table_days(table).values()
        for entry in entries
    ]


def carry_checklists_over(
    config: MutableMapping, sale_date: date | None = None
) -> list[str]:
    """Make the saved ticks fit the table in use; returns the settings changed.

    The checklists store the TICKED items, so after the table changes an item
    it adds would read as unticked and never be sold.  Once per change: an item
    both tables have keeps its tick, an item only the new one has is ticked.
    """

    target = table_for(sale_date)
    saved = str(config.get(SALE_TABLE_KEY) or OLD_TABLE)
    if saved == target:
        return []
    after = _table_days(target)
    if not after:
        return []  # unreadable now: nothing changed, tried again next time
    before = _table_days(saved)
    changed = []
    for day, entries in after.items():
        key = sale_day_key(day)
        ticked = config.get(key)
        carried = _carried(ticked, entries, before, day)
        if ticked != carried:
            config[key] = carried
            changed.append(key)
    config[SALE_TABLE_KEY] = target
    return changed


def _carried(ticked, entries, before: Mapping, day: int) -> list[str]:
    """``ticked`` (saved for the table ``before``) as it reads for ``entries``."""

    items = day_items(entries)
    if not isinstance(ticked, list):
        return items
    # Without the old table nobody can tell new from unticked: only what was
    # ticked stays ticked (never sell what was switched off).
    known = set(day_items(before.get(day, ()))) if before else set(items)
    return [item for item in items if item in ticked or item not in known]


def month_sale_days(
    today: date | None = None,
) -> tuple[dict[int, tuple[CalendarEntry, ...]], date | None]:
    """What each date of ``today``'s month sells, and the date the table changes.

    The page shows a whole month.  In the month of the change, the dates from
    the change on already show the new table (second value: that date, None
    in every other month and once the change has happened), so the calendar
    never promises goods the game will no longer pay ↑120% for.
    """

    today = today or current_sale_date()
    table = table_for(today)
    days = dict(_table_days(table))
    same_month = (NEXT_CALENDAR_FROM.year, NEXT_CALENDAR_FROM.month) == (today.year, today.month)
    if table == NEXT_TABLE or not same_month:
        return days, None
    after = _table_days(NEXT_TABLE)
    if not after:
        return days, None
    first = NEXT_CALENDAR_FROM.day
    days = {day: entries for day, entries in days.items() if day < first}
    days.update({day: entries for day, entries in after.items() if day >= first})
    return days, NEXT_CALENDAR_FROM


def ticks_after_change(config: Mapping, day: int) -> list[str]:
    """The items of ``day`` that will be ticked once the new table is in use
    (the same rule ``carry_checklists_over`` applies on that day)."""

    entries = _table_days(NEXT_TABLE).get(day, ())
    saved = str(config.get(SALE_TABLE_KEY) or OLD_TABLE)
    if saved == NEXT_TABLE:
        ticked = config.get(sale_day_key(day))
        return day_items(entries) if not isinstance(ticked, list) else [
            item for item in day_items(entries) if item in ticked
        ]
    return _carried(config.get(sale_day_key(day)), entries, _table_days(saved), day)


def day_items(entries: Iterable[CalendarEntry]) -> list[str]:
    return list(dict.fromkeys(entry.item for entry in entries))


def describe_entry(entry: CalendarEntry) -> str:
    text = f"{entry.item}→{entry.shop}"
    return f"{text}（保留{entry.reserve}）" if entry.reserve else text


def apply_sale_checklist(
    config: Mapping,
    day: int,
    entries: Iterable[CalendarEntry],
    bundled_entries: Iterable[CalendarEntry],
) -> tuple[list[CalendarEntry], list[CalendarEntry]]:
    """Split today's entries into (to sell, unticked by the user)."""

    entries = list(entries)
    options = set(day_items(bundled_entries))
    key = sale_day_key(day)
    if key not in config:
        return entries, []
    selected = set(config.get(key) or [])
    unticked = options - selected
    keep = [entry for entry in entries if entry.item not in unticked]
    dropped = [entry for entry in entries if entry.item in unticked]
    return keep, dropped
