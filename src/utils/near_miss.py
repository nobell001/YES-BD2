"""Note a check that read most of its words but not enough (差一点对上).

Leo 2026-11-06 「繁中有很多和簡中表達不一樣的地方…很多地方並不是直譯」: a
繁中 screen that says one word differently (在場域中查看 for 在战场中查看,
雷瓦汀祕密基地 for 雷瓦汀据点) left a check at 6/7 or 1/3 and was only found
when the task failed.  Every such near miss is written to the log once per
run with the words wanted and the text actually read, so a test run lists the
words to add to the 繁中 table (tools/i18n/tw_client_ui.json) before a player
meets them.  Only notes; it never changes what a check decides.
"""

from __future__ import annotations

from typing import Callable, Iterable

NEAR_MISS_LABEL = "差一点对上"
# At most this many words short counts as near; fewer read is another screen.
NEAR_MISS_MAX_SHORT = 2
_TEXT_LIMIT = 160

_seen: set[tuple[str, tuple[str, ...]]] = set()


def is_near(matched: int, needed: int) -> bool:
    """Some words read, but 1..NEAR_MISS_MAX_SHORT fewer than needed."""
    return 0 < matched < needed and needed - matched <= NEAR_MISS_MAX_SHORT


def note(
    log: Callable[[str], object] | None,
    name: str,
    words: Iterable[str],
    text: str,
    matched: int,
    needed: int,
    found: Callable[[str, str], bool] | None = None,
) -> bool:
    """Log a near miss of check ``name`` once per (name, missing words) in a
    run; True when logged.

    ``found(word, text)`` tells which words were read (default: ``word in text``),
    so the line names the missing ones.
    """
    if log is None or not is_near(matched, needed):
        return False
    full = str(text or "")
    found = found or (lambda word, read: word in read)
    missing = [word for word in words if not found(word, full)]
    # Per missing set, not per text: the text changes frame to frame (counts,
    # timers) while the word that is not read stays the same.
    key = (str(name), tuple(missing))
    if key in _seen:
        return False
    _seen.add(key)
    text = " ".join(full.split())[:_TEXT_LIMIT]
    try:
        log(
            f"{NEAR_MISS_LABEL}：{name} 读到 {matched}/{needed}，"
            f"缺「{'」「'.join(missing) or '-'}」；画面读到：{text or '-'}"
        )
    except Exception:
        return False
    return True


def reset() -> None:
    """Forget what was logged (a new run, or a test)."""
    _seen.clear()
