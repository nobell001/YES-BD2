"""Read a small text box again, bordered and enlarged, when it read nothing.

Small boxes (a title, a value, one button's label) are where reads were lost:
a player's 跑商 title and 镜中之战 multiplier read 「-」 (v0.1.21,
2026-10-11, 1080p window at 250%), and 圣石 counts, badge digits and gear
labels before them.  Each was mended where it happened, so the next small box
failed the same way.  ``BaseBD2Task.ocr`` now runs every read through this:

1. the box as given (unchanged: a box that reads keeps its result);
2. read nothing: the same box with a plain border around it, because the
   text finder misses text that touches the image edge (the player's 跑商
   title on a fixed-size OCR input: nothing as cut, 「购买」 with a border);
3. still nothing: enlarged 2×, then 3×, each with the border (small digits,
   the way 圣石 counts and gear labels were already read).

It stops at the first read that finds text.  Only small boxes qualify (a full
frame is never enlarged), and a box that keeps reading nothing is enlarged at
most once per ``REREAD_COOLDOWN_SECONDS``, so a wait that polls an empty box
does not triple its OCR time.  Leo 2026-10-11: 「先做放大再讀」.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Boxes this size or smaller get the extra reads (pixels of the image handed
# to the OCR).  Larger images are pages or lists, not one label.
REREAD_MAX_HEIGHT = 360
REREAD_MAX_WIDTH = 1400
# Enlargements after the bordered read at the original size.
REREAD_SCALES = (1.0, 2.0, 3.0)
# Border around the box: half its height, at least this many pixels.
REREAD_MIN_BORDER = 12
# An enlarged image stays within this size (an OCR input, not a page).
REREAD_MAX_SIDE = 2400
REREAD_COOLDOWN_SECONDS = 1.0
# A reread may only add text it is sure of.  On 1286 empty boxes cut from
# real frames, the extra reads found text in 87: mostly words the box cut
# through (9/21, MIRROR, UR), but also stray marks such as 「-」 (0.99) or
# 「X」 on a coloured bar.  Kept: boxes at this confidence or more, and a
# lone character only when it is a digit read at REREAD_LONE_DIGIT_CONFIDENCE.
REREAD_MIN_CONFIDENCE = 0.8
REREAD_LONE_DIGIT_CONFIDENCE = 0.9


@dataclass(frozen=True)
class RereadImage:
    image: np.ndarray
    scale: float
    border: int


def qualifies(image) -> bool:
    """A small box that read nothing may be read again."""
    shape = getattr(image, "shape", None)
    if shape is None or len(shape) < 2:
        return False
    height, width = int(shape[0]), int(shape[1])
    return 0 < height <= REREAD_MAX_HEIGHT and 0 < width <= REREAD_MAX_WIDTH


def _border_colour(image: np.ndarray):
    """The box's own median colour, so the border adds no edge of its own."""
    if image.ndim == 2:
        return int(np.median(image))
    channels = image.shape[2]
    return [int(value) for value in np.median(image.reshape(-1, channels), axis=0)]


def reread_images(image: np.ndarray, scales=REREAD_SCALES):
    """The bordered, enlarged versions of ``image`` to try, in order."""
    for scale in scales:
        height, width = image.shape[:2]
        if max(height, width) * scale > REREAD_MAX_SIDE:
            break
        target = image
        if scale != 1.0:
            target = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        border = max(REREAD_MIN_BORDER, target.shape[0] // 2)
        bordered = cv2.copyMakeBorder(
            target,
            border,
            border,
            border,
            border,
            cv2.BORDER_CONSTANT,
            value=_border_colour(target),
        )
        yield RereadImage(bordered, float(scale), border)


def _confidence(box) -> float:
    value = getattr(box, "confidence", None)
    if value is None:
        value = getattr(box, "score", 1.0)
    value = float(value)
    return value / 100.0 if value > 1.0 else value


def trusted(boxes) -> list:
    """The reread boxes sure enough to count (stray marks left out)."""
    kept = []
    for box in boxes:
        text = "".join(str(getattr(box, "name", "") or "").split())
        confidence = _confidence(box)
        if not text or confidence < REREAD_MIN_CONFIDENCE:
            continue
        if len(text) == 1 and not (text.isdigit() and confidence >= REREAD_LONE_DIGIT_CONFIDENCE):
            continue
        kept.append(box)
    return kept


def _text(boxes) -> str:
    return "".join("".join(str(getattr(box, "name", "") or "").split()) for box in boxes)


def keeps_first_read(first, found) -> bool:
    """False when ``found`` lost digits or text the first read had.

    The 活动每日战斗 button: 「战斗。5」 at 0.79 is under the bar, the 2x read
    「战斗。」 at 0.86 passes, and the count was gone (Leo 2026-11-07).  Every
    box goes through this read, so a sure but shorter read is no better read
    anywhere: the next look is tried, and it stays the last resort.
    A lone character in the first read is a stray mark, not text to keep
    (the 跑商 title read as 「4」 at 0.77).
    """
    words = _text(box for box in first if len(_text([box])) > 1)
    text = _text(found)
    digits = sum(ch.isdigit() for ch in words)
    return len(text) >= len(words) and sum(ch.isdigit() for ch in text) >= digits


def map_back(boxes, reread: RereadImage, width: int, height: int) -> list:
    """Boxes found on a reread image, moved back onto the original box."""
    mapped = []
    for box in boxes:
        x = (float(box.x) - reread.border) / reread.scale
        y = (float(box.y) - reread.border) / reread.scale
        right = x + float(box.width) / reread.scale
        bottom = y + float(box.height) / reread.scale
        x, y = max(0.0, x), max(0.0, y)
        right, bottom = min(float(width), right), min(float(height), bottom)
        box.x, box.y = int(round(x)), int(round(y))
        box.width = max(1, int(round(right - x)))
        box.height = max(1, int(round(bottom - y)))
        mapped.append(box)
    return mapped
