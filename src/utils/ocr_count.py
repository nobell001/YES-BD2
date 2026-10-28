"""Read an "a/b" count (used/limit) by one set of rules.

The slash of a small count is what OCR gets wrong: 7/70 read "7170"
(2026-09-28), 11/75 "11775" (4K 2026-10-14), 7/75 "7175" (2K 2026-10-15).
Each case was mended where it showed up, so the next count failed the same
way (Leo 2026-10-28 「11/75 這個問題很多次了 沒辦法解決嗎」, 「像讀不到 讀錯時
應該都會要有補救方案」).

95 count boxes cut from players' and Leo's pictures (2026-10-28,
tests/fixtures/hud_counts) were read with the app's recognizer (PP-OCRv6
small, src/compat/ocr_models.py).  The run's reads (2x, then 3x) gave 92
right, 1 nothing and 2 wrong: 0/21 read "121" at 2x, which the old split
took as 1/21.  Other reads: "0775" for 0/75, "177" for 1/7, "1/21" for
21/21 with a border at 2x.

What a read can be (``count_values``):

1. a clean "a/b": a ≤ b and no leading zero ("07/75" is 0/75 with the slash
   read twice).  A limit that is only the start of the one seen on screen
   today lost its last digits ("2/2" for 2/21, "7/7" for 7/75) and is no
   read: it would look full.  Only a limit seen on screen counts
   (``seen_limit``), never one written in the code (a player's 召集 is 7);
2. no slash: the slash was read as 1 or 7, so the digits split just before
   ``limit``, the limit seen on screen ("0775" is 0/75).  Never a limit
   written in the code: they differ by player (压制 50, 55, 70, 75, 80 on
   players' pictures).  A slash that is not there at all is not assumed:
   "121" (0/21, its 0 lost) would then be 1/21;
3. a number with a letter glued to it ("V21", "L0/75") is no read: the
   letter may be a lost digit.

Under these rules a read is one value or none, so a read that is not clean
is read again another way (``LOOKS``, ``read_count``), never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

import cv2
import numpy as np

# What OCR reads where the slash is, in a count that kept one.
_SLASH = r"[/／\\|:：\-~]"
_CLEAN = re.compile(rf"^(\d+){_SLASH}(\d+)$")
_SPACED_SLASH = re.compile(rf"\s*({_SLASH})\s*")
# Words around the count ("次数 10:10") are not part of it.
_WORDS = re.compile(r"[\u4e00-\u9fff]+")
# What the slash becomes in a count read without one.
SLASH_READ_AS = ("1", "7")


@dataclass(frozen=True)
class Look:
    """One way to read the box: enlarged ``scale`` times; ``bordered`` first
    puts it inside a plain border (the text finder misses digits that touch
    the box's edge)."""

    scale: float
    bordered: bool = False


# The order every count is read in, each on a fresh frame.  On the 95 boxes
# above, with the limit seen on screen: 3x alone read 94 right and 1
# nothing, the bordered 3x read that one; none was read wrong (2x first read
# two 0/21 as "121").  With the older PP-OCRv5 recognizer (an install
# without the v6 files) the same two looks read 94 right and 1 nothing,
# where 2x then 3x read 90 and 5 nothing.
LOOKS = (Look(3.0), Look(3.0, bordered=True))


@dataclass(frozen=True)
class CountRead:
    value: tuple[int, int] | None
    texts: tuple[str, ...] = ()  # what each look read, in order

    def __bool__(self) -> bool:
        return self.value is not None

    def why(self) -> str:
        """Why no value, in player words (for the skip reason)."""
        seen = [text for text in self.texts if text.strip()]
        if not seen:
            return "没读到数字"
        return f"读到「{seen[0].strip()}」，看不出是多少"


def _number(digits: str) -> int | None:
    """A count as the game writes it: no leading zero."""
    if not digits or (len(digits) > 1 and digits[0] == "0"):
        return None
    return int(digits)


def _cut_short(top: int, seen_limit: int | None) -> bool:
    """The limit read is the start of the one seen on screen: its last
    digits were lost ("2/2" for 2/21)."""
    if not seen_limit or top == seen_limit:
        return False
    return str(seen_limit).startswith(str(top))


def _token_values(
    token: str, limit: int | None, seen_limit: int | None = None
) -> set[tuple[int, int]]:
    match = _CLEAN.match(token)
    if match is not None:
        used, top = _number(match.group(1)), _number(match.group(2))
        if used is None or top is None or top <= 0 or used > top:
            return set()
        if _cut_short(top, seen_limit):
            return set()
        return {(used, top)}
    if limit is None or not token.isdigit():
        return set()
    tail = str(limit)
    if len(token) <= len(tail) or not token.endswith(tail):
        return set()
    head = token[: -len(tail)]
    values = set()
    for slash in SLASH_READ_AS:
        if head.endswith(slash):
            used = _number(head[: -len(slash)])
            if used is not None and used <= limit:
                values.add((used, limit))
    return values


def count_values(
    text: str, *, limit: int | None = None, seen_limit: int | None = None
) -> set[tuple[int, int]]:
    """Every (used, limit) the read ``text`` can be under the rules above."""
    text = _SPACED_SLASH.sub(r"\1", _WORDS.sub(" ", str(text or "")))
    values: set[tuple[int, int]] = set()
    for token in text.split():
        values |= _token_values(token, limit, seen_limit)
    return values


def parse_count(
    text: str, *, limit: int | None = None, seen_limit: int | None = None
) -> tuple[int, int] | None:
    """The one (used, limit) ``text`` can be, else None (two counts in one
    read are no read either)."""
    values = count_values(text, limit=limit, seen_limit=seen_limit)
    return next(iter(values)) if len(values) == 1 else None


def read_count(
    looks: Iterable[Callable[[], str]],
    *,
    limit: int | None = None,
    seen_limit: int | None = None,
) -> CountRead:
    """Read with each look in turn until one read is a count."""
    texts: list[str] = []
    for look in looks:
        text = str(look() or "")
        texts.append(text)
        value = parse_count(text, limit=limit, seen_limit=seen_limit)
        if value is not None:
            return CountRead(value, tuple(texts))
    return CountRead(None, tuple(texts))


def bordered(image: np.ndarray) -> tuple[np.ndarray, int]:
    """The box inside a border of its own median colour (half its height, at
    least 12 px); returns the image and the border width."""
    border = max(12, int(image.shape[0] * 0.5))
    if image.ndim == 2:
        colour = int(np.median(image))
    else:
        colour = [int(v) for v in np.median(image.reshape(-1, image.shape[2]), axis=0)]
    framed = cv2.copyMakeBorder(
        image, border, border, border, border, cv2.BORDER_CONSTANT, value=colour
    )
    return framed, border
