"""The full update notes of each version, for 关于 → 更新内容.

The launcher hands the tool at most 10 note lines per update (pyappify's
``MAX_UPDATE_NOTE_LINES``), so v0.1.17 → v0.1.18 showed 10 of its 65
changes (Leo 2026-10-10).  ``scripts/sync_public.py`` writes every note of
every release into ``assets/update_notes.json`` when it tags one; this reads
that file and falls back to the launcher's lines for versions it does not
know (a newer version picked in the version list, or a source checkout).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

NOTES_FILE = Path(__file__).resolve().parents[3] / "assets" / "update_notes.json"
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)$")
_BULLET = re.compile(r"^\s*[•·\-*]\s*")


def version_key(version: str | None) -> tuple[int, ...] | None:
    match = _VERSION.match(str(version or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def load(path: Path | None = None) -> dict[tuple[int, ...], list[str]]:
    """version -> its notes; empty when the file is missing or broken."""
    try:
        data = json.loads((path or NOTES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = data.get("versions") if isinstance(data, dict) else None
    versions = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        key = version_key(item.get("version"))
        notes = item.get("notes")
        if key and isinstance(notes, list):
            versions[key] = [str(note).strip() for note in notes if str(note).strip()]
    return versions


def notes_between(
    versions: dict[tuple[int, ...], list[str]], old: str | None, new: str | None
) -> list[str] | None:
    """Notes of every version after ``old`` up to ``new``, newest first.

    Either way round (a downgrade lists what it takes away).  Without ``old``
    only ``new``'s own notes.  None when the file does not know the newer
    end, so the caller keeps the launcher's lines.
    """
    low, high = version_key(old), version_key(new)
    if high is None:
        return None
    if low is not None and low > high:
        low, high = high, low
    if high not in versions:
        return None
    if low is None or low == high:
        return list(versions[high])
    notes: list[str] = []
    for key in sorted(versions, reverse=True):
        if low < key <= high:
            notes.extend(note for note in versions[key] if note not in notes)
    return notes


def split_lines(text: str) -> list[str]:
    """The launcher's notes text, one line each, without its own bullets."""
    lines = []
    for line in (text or "").splitlines():
        line = _BULLET.sub("", line).strip()
        if line and line not in lines:
            lines.append(line)
    return lines
