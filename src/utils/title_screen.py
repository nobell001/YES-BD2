"""The game's title screen (the login page), read from OCR boxes.

YES-BD2 #75 (2026-11-09): a player says that when the title loads slowly the
screen goes into a standby where 「TOUCH TO START」 is hidden and never comes
back, so a login that only looks for those words waits forever.

The title is known by any one of (extra cues only help, Leo 2026-11-06):
1. the words TOUCH TO START;
2. the version line and the UID line together in the top-left corner
   (「v2.38.11(FHD-902:727)」 over 「UID:20756418」, live 2K 2026-11-09,
   tests/fixtures/title/).  Both are needed: a profile page may show a UID.

While 「啟動遊戲中」 (the spinner's words) shows, the game is still starting:
nothing is pressed (the player's own suggestion: wait for the spinner to go,
then tap the screen).  Any tap on the title logs in (live 2K 2026-11-09: one
tap on the blank upper middle went straight to the loading logo and home).
"""

from __future__ import annotations

import re

from src.utils.ocr_utils import fuzzy_substring_match, normalize_ocr_text

TOUCH_TEXT = "touchtostart"
# OCR misreads like "T0UCH TO STAR" (recovery's tolerance since 2026-10).
TOUCH_FUZZY_RATIO = 0.8
# The top-left corner holding the version and UID lines (at 1080p they sit
# at x≈275, y≈45..95).
CORNER_MAX_X = 0.35
CORNER_MAX_Y = 0.15
# OCR drops or garbles the leading v (「2.38.11」, 「/2.38.11」, live 4K
# 2026-11-09, #528) and reads UID as JID: the digits stay exact.
VERSION_PATTERN = re.compile(r"^\W?v?\d+\.\d+\.\d+")
UID_PATTERN = re.compile(r"^[uj][il1|]d[:：;]?\d{5,}")
# The spinner's words while the title is still starting.  啟動遊戲中 is the
# live 繁中 frame; the others are the same words in the other languages
# (not seen yet).
STARTING_WORDS = ("啟動遊戲中", "启动游戏中", "ゲーム起動中", "게임시작중", "startinggame")
# Where a wake tap goes: the blank upper middle of the title (the live test
# point, 960,200 at 1920x1080), away from the corner buttons (power,
# settings) and the logo.
WAKE_TAP_X = 0.5
WAKE_TAP_Y = 0.185


def _text(box) -> str:
    return normalize_ocr_text(getattr(box, "name", ""))


def _in_corner(box, width: int, height: int) -> bool:
    try:
        x = float(getattr(box, "x"))
        y = float(getattr(box, "y"))
    except (TypeError, ValueError, AttributeError):
        return False
    return x < width * CORNER_MAX_X and y < height * CORNER_MAX_Y


def touch_text_read(boxes) -> bool:
    alnum = normalize_ocr_text("".join(_text(box) for box in boxes), alnum_only=True)
    return fuzzy_substring_match(alnum, TOUCH_TEXT, TOUCH_FUZZY_RATIO)


def corner_lines_read(boxes, shape) -> bool:
    """The version line and the UID line, both in the top-left corner."""
    height, width = int(shape[0]), int(shape[1])
    version = uid = False
    for box in boxes:
        if not _in_corner(box, width, height):
            continue
        text = _text(box)
        version = version or bool(VERSION_PATTERN.match(text))
        uid = uid or bool(UID_PATTERN.match(text))
    return version and uid


def shown(boxes, shape) -> bool:
    """The title screen, with or without its TOUCH TO START words."""
    boxes = list(boxes or ())
    return touch_text_read(boxes) or corner_lines_read(boxes, shape)


def still_starting(boxes) -> bool:
    """The spinner's 「啟動遊戲中」: the title is still loading."""
    text = "".join(_text(box) for box in boxes or ())
    return any(word in text for word in STARTING_WORDS)
