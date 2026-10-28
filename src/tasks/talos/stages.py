"""塔洛斯战术教材: the nine stages, which are cleared, which to play next.

Leo 2026-10-28: nine stages a month, the same enemies and the same own
characters and costumes for every player, so one record per stage (shipped
in fiend_hunt/data/talos) plays them for everyone.  The stages are played
in order 1-9 (the list's grid read row by row: 1 2 3 / 4 5 6 / 7 8 9),
skipping the cleared ones, and the cleared ones are remembered per account
so an interrupted run carries on where it stopped.

What counts as cleared: the stage list's own red ✕ when it can be read
(the game's memory wins), else this file.  The file belongs to one set of
records (``edition``): next month's records make a new edition and the old
marks no longer count.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from src.tasks.fiend_hunt.recording import RECORD_FILE

STAGE_COUNT = 9
RECORDS_DIR = Path(__file__).resolve().parents[1] / "fiend_hunt" / "data" / "talos"
PROGRESS_FILE = "talos_progress.json"


def record_folder(stage: int, root: Path = RECORDS_DIR) -> Path:
    return root / f"塔洛斯-关卡{stage}"


def edition(root: Path = RECORDS_DIR) -> str:
    """A short name for this set of records: changes when any record does."""
    digest = hashlib.sha1()
    for stage in range(1, STAGE_COUNT + 1):
        path = record_folder(stage, root) / RECORD_FILE
        digest.update(str(stage).encode())
        digest.update(path.read_bytes() if path.is_file() else b"-")
    return digest.hexdigest()[:12]


def missing_records(root: Path = RECORDS_DIR) -> list[int]:
    return [
        stage
        for stage in range(1, STAGE_COUNT + 1)
        if not (record_folder(stage, root) / RECORD_FILE).is_file()
    ]


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
        return cls(edition_now, cleared, {int(s): str(w) for s, w in failed.items() if _stage(s)})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "edition": self.edition,
            "cleared": sorted(self.cleared),
            "failed": {str(s): w for s, w in sorted(self.failed.items()) if s not in self.cleared},
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


def to_play(cleared: Iterable[int], count: int = STAGE_COUNT) -> list[int]:
    done = set(cleared)
    return [stage for stage in range(1, count + 1) if stage not in done]


class StagePicker:
    """What the in-game status bar shows and changes while a run is paused.

    Leo 2026-10-28 「暫停後可以在上面切換關卡」: ◀ 第 N 关 ▶ on the bar
    (src/ui/shell/game_status.py) calls ``pick``; on 继续 the task leaves
    the fight it is in and plays the chosen stage (``take``), or carries on
    where it was when nothing else was chosen.
    """

    def __init__(self, count: int = STAGE_COUNT):
        self.count = count
        self.current: int = 1
        self.cleared: set[int] = set()
        self.chosen: int | None = None

    def pick(self, stage: int) -> None:
        if 1 <= int(stage) <= self.count:
            self.chosen = int(stage)

    def take(self) -> int | None:
        """The stage chosen on the bar, when it is not the one being played (then cleared)."""
        chosen, self.chosen = self.chosen, None
        return chosen if chosen is not None and chosen != self.current else None


def next_order(start: int, cleared: Iterable[int], count: int = STAGE_COUNT) -> list[int]:
    """The chosen stage first, then the stages not cleared yet in order (Leo:
    「換了關再按繼續：先退出現在這場，再去打選的那關，打完照順序往後打沒打過的」)."""
    rest = [stage for stage in to_play(cleared, count) if stage != start]
    rest.sort(key=lambda stage: (stage - start) % count)  # on from the chosen one, then round
    return [start, *rest]
