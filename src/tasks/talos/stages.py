"""塔洛斯战术教材: the stages, which are cleared, which to play next.

Leo 2026-10-28: a fixed set of stages each period, the same enemies and the
same own characters and costumes for every player, so one record per stage
(shipped in fiend_hunt/data/talos) plays them for everyone.  The stages are
played in order (the list's grid read row by row: 1 2 3 / 4 5 6 / 7 8 9 for
nine, 1 2 3 4 / 5 6 7 8 / ... for sixteen), skipping the cleared ones, and
the cleared ones are remembered per account so an interrupted run carries on
where it stopped.

How many stages there are is not a game limit the tool knows: it is the
number of records shipped for this period (2026-10-22 nine on a 3x3 list,
2026-11-19 sixteen on a 4x4 list).  A new period ships new records and the
count and the list's grid follow them.

What counts as cleared: the stage list's own red ✕ when it can be read
(the game's memory wins), else this file.  The file belongs to one set of
records (``edition``): next month's records make a new edition and the old
marks no longer count.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from src.tasks.fiend_hunt.recording import RECORD_FILE

RECORDS_DIR = Path(__file__).resolve().parents[1] / "fiend_hunt" / "data" / "talos"
PROGRESS_FILE = "talos_progress.json"
FOLDER_PREFIX = "塔洛斯-关卡"
SOURCE_FILE = "source.json"  # where the records came from (tools/talos_gamekee.py)


def record_folder(stage: int, root: Path = RECORDS_DIR) -> Path:
    return root / f"{FOLDER_PREFIX}{stage}"


def stage_count(root: Path = RECORDS_DIR) -> int:
    """How many stages this period has: the highest stage shipped, or the
    guide page's stage count when it lists stages without a chart yet (those
    show up in ``missing_records`` and are skipped)."""
    try:
        listed = int(json.loads((root / SOURCE_FILE).read_text(encoding="utf-8")).get("stages") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        listed = 0
    numbers = [
        int(path.name[len(FOLDER_PREFIX) :])
        for path in (root.iterdir() if root.is_dir() else ())
        if path.is_dir() and path.name.startswith(FOLDER_PREFIX) and path.name[len(FOLDER_PREFIX) :].isdigit()
    ]
    return max(numbers + [listed], default=0)


def grid_columns(count: int) -> int:
    """Tiles per row on the stage list: a square grid (9 → 3x3, 16 → 4x4)."""
    side = 1
    while side * side < count:
        side += 1
    return side


STAGE_COUNT = stage_count()


def edition(root: Path = RECORDS_DIR) -> str:
    """A short name for this set of records: changes when any record does."""
    digest = hashlib.sha1()
    for stage in range(1, stage_count(root) + 1):
        path = record_folder(stage, root) / RECORD_FILE
        digest.update(str(stage).encode())
        digest.update(path.read_bytes() if path.is_file() else b"-")
    return digest.hexdigest()[:12]


def missing_records(root: Path = RECORDS_DIR) -> list[int]:
    return [
        stage
        for stage in range(1, stage_count(root) + 1)
        if not (record_folder(stage, root) / RECORD_FILE).is_file()
    ]


# -- a new period ----------------------------------------------------------------
#
# Leo 2026-11-19 「想辦法判定 如果週期沒對上 就先跳出 跟用戶說攻略尚未更新」
# (no lock kept: each run looks again): the game changes the stages each
# period (about four weeks: 10-22 ~
# 11-18 nine stages, from 11-19 sixteen); the records of the last period
# would lose every fight of the new one.  The tool tells from the list itself,
# offline, and that run stops with 「攻略尚未更新」.  Any one of these is enough:
#  - the list has another grid than the records (3x3 vs 4x4);
#  - the list's 「还剩N天」 ends the period long after the records were made
#    (one period plus a margin: a guide comes out within days of the start);
#  - this account saw another end date with these records before, or that
#    end date has passed by more than a couple of days (only when nothing
#    was read this time).
RECORDS_LAST_DAYS = 42  # a period is ~28 days; the next one ends ~56 days after it started
END_SLACK_DAYS = 2  # 「还剩N天」 read on different days and around the 08:00 reset


def records_made(root: Path = RECORDS_DIR) -> date | None:
    """When the guide's charts for these records were made (source.json)."""
    try:
        return date.fromisoformat(str(json.loads((root / SOURCE_FILE).read_text(encoding="utf-8"))["made"]))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


_DAYS = re.compile(r"(?:还剩|還剩|剩余|剩餘|剩下)\s*(\d{1,3})\s*[天日]")
_HOURS = re.compile(r"(?:还剩|還剩|剩余|剩餘|剩下)\s*\d{1,2}\s*(?:小时|小時|时|時|分)")


def period_end(text: str, today: date) -> date | None:
    """The period's last day from the list's 「活动 还剩27天」 (None: not read)."""
    found = _DAYS.search(text.replace(" ", ""))
    if found:
        return today + timedelta(days=int(found.group(1)))
    if _HOURS.search(text.replace(" ", "")):
        return today
    return None


def period_change(
    *,
    count: int,
    columns: int | None,
    end: date | None,
    made: date | None,
    seen_end: date | None,
    today: date,
) -> str:
    """Why the list on screen is a newer period than the records ("" when it is not)."""
    if columns is not None and count and columns != grid_columns(count):
        return f"游戏这期的关卡是 {columns}x{columns}，工具里的轴是上一期的（{count} 关）"
    if end is not None and made is not None and (end - made).days > RECORDS_LAST_DAYS:
        return f"游戏这期到 {end:%m-%d}，工具里的轴是 {made:%m-%d} 那期的"
    if end is not None and seen_end is not None and abs((end - seen_end).days) > END_SLACK_DAYS:
        return f"游戏这期到 {end:%m-%d}，工具里的轴是到 {seen_end:%m-%d} 那期的"
    # the day 「还剩N天」 counts to can be the day before the update (10-28
    # read 21 days → 11-18, the new period came 11-19): a margin, not the day after
    if end is None and seen_end is not None and (today - seen_end).days > END_SLACK_DAYS:
        return f"工具里的轴那期 {seen_end:%m-%d} 已经结束"
    return ""


def _stage(value) -> bool:
    return str(value).isdigit() and 1 <= int(value) <= STAGE_COUNT


@dataclass
class Progress:
    """Cleared stages of one account, for one edition of the records."""

    edition: str
    cleared: set[int] = field(default_factory=set)
    # The last run's stages that stopped, with why (the 塔洛斯教材 page shows it).
    failed: dict[int, str] = field(default_factory=dict)
    # False until a run has read this month's stage list for this account
    # (a new install, a new account, next month's records).
    known: bool = True
    # The period's last day as read on the list with these records.
    period_end: date | None = None

    @classmethod
    def load(cls, path: Path, edition_now: str) -> Progress:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(edition_now, known=False)
        if not isinstance(data, dict) or data.get("edition") != edition_now:
            return cls(edition_now, known=False)  # another month's records: start over
        stages = data.get("cleared") or []
        cleared = {int(s) for s in stages if _stage(s)}
        failed = data.get("failed") if isinstance(data.get("failed"), dict) else {}
        try:
            end = date.fromisoformat(str(data.get("period_end")))
        except ValueError:
            end = None
        return cls(
            edition_now,
            cleared,
            {int(s): str(w) for s, w in failed.items() if _stage(s)},
            period_end=end,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "edition": self.edition,
            "cleared": sorted(self.cleared),
            "failed": {str(s): w for s, w in sorted(self.failed.items()) if s not in self.cleared},
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(path)

    def merge_screen(self, marks: dict[int, bool]) -> None:
        """The stage list as read (stage -> cleared); stages not read keep the file's word."""
        for stage, cleared in marks.items():
            if cleared:
                self.cleared.add(stage)
            else:
                self.cleared.discard(stage)


def to_play(cleared: Iterable[int], count: int | None = None) -> list[int]:
    count = STAGE_COUNT if count is None else count
    done = set(cleared)
    return [stage for stage in range(1, count + 1) if stage not in done]


class StagePicker:
    """What the in-game status bar shows and changes while a run is paused.

    Leo 2026-10-28 「暫停後可以在上面切換關卡」: ◀ 第 N 关 ▶ on the bar
    (src/ui/shell/game_status.py) calls ``pick``; on 继续 the task leaves
    the fight it is in and plays the chosen stage (``take``), or carries on
    where it was when nothing else was chosen.
    """

    def __init__(self, count: int | None = None):
        self._count = count
        self.current: int = 1
        self.cleared: set[int] = set()
        self.chosen: int | None = None

    @property
    def count(self) -> int:
        return STAGE_COUNT if self._count is None else self._count

    def pick(self, stage: int) -> None:
        if 1 <= int(stage) <= self.count:
            self.chosen = int(stage)

    def take(self) -> int | None:
        """The stage chosen on the bar, when it is not the one being played (then cleared)."""
        chosen, self.chosen = self.chosen, None
        return chosen if chosen is not None and chosen != self.current else None


def next_order(start: int, cleared: Iterable[int], count: int | None = None) -> list[int]:
    """The chosen stage first, then the stages not cleared yet in order (Leo:
    「換了關再按繼續：先退出現在這場，再去打選的那關，打完照順序往後打沒打過的」)."""
    count = STAGE_COUNT if count is None else count
    rest = [stage for stage in to_play(cleared, count) if stage != start]
    rest.sort(key=lambda stage: (stage - start) % count)  # on from the chosen one, then round
    return [start, *rest]
