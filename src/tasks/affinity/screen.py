"""Reading the 亲密度 pages (1920x1080 reference, calibrated on Leo's 2K
简体 client 2026-10-21, tests/fixtures/affinity).

List page: one card per costume, 13 a row; under the picture three lines,
costume name (白色猫咪), character name (鲁), 「Lv.20 (0%)」.  Top right
「今日剩余谈心次数 | 3」: the talks left today for costumes below LV20.
A costume the player does not own is greyed with 「未拥有」 across its
picture, its level still 「LV.1 (0%)」; pressed, the game only shows
「未拥有穿戴该服装的角色，拥有后即可进行谈心。」 (player frame 2026-10-28).

Detail page (a card pressed): the white panel on the right shows the
character and costume names, 「LV.20 MAX」 or 「LV.16」, 「谈心记录 3/15」 and
the buttons 赠送礼物 / 谈心 / 快速谈心; below LV20 the 谈心 button carries
「1/1」 (one talk today) or 「0/1」 (used).  At LV15 a costume can be locked
(「完成服装潜力释放后解锁下一级」): its affinity does not rise until the
costume's potential is released.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from src.tasks.affinity.answers import normalize

MAX_LEVEL = 20
RECORD_FULL = 15

# -- list page ---------------------------------------------------------------
LIST_TITLE = ("亲密度",)
LIST_GRID_ROI = (170, 160, 1600, 900)
LIST_REMAINING_ROI = (1500, 20, 400, 60)
# The card's picture, pressed to open it: above its name lines.
CARD_PRESS_ABOVE_LEVEL = 80
CARD_PRESS_RIGHT_OF_LEVEL = 40
# Name lines sit this far above the level line (box tops, reference px).
COSTUME_LINE_ABOVE = (35, 60)
CHARACTER_LINE_ABOVE = (10, 34)
CARD_COLUMN_SLACK = 45
# 「未拥有」 sits across the picture, about 100 px above the level line.
UNOWNED_WORDS = ("未拥有",)
UNOWNED_LABEL_ABOVE = (65, 140)
UNOWNED_LABEL_MAX_CHARS = 5
# Where the game's 「未拥有穿戴该服装的角色…」 shows after such a press
# (screen centre, above the first row; one player frame: a guess for others).
UNOWNED_TOAST_ROI = (460, 195, 1000, 90)

# -- detail page -------------------------------------------------------------
DETAIL_HEADER_ROI = (900, 80, 740, 210)
DETAIL_TALK_BUTTON_ROI = (1400, 950, 250, 60)
DETAIL_TALK_BUTTON_POINT = (1517, 991)
DETAIL_BACK_POINT = (138, 40)
# The names are left-aligned at x 926; the gift icon at x ~1590 reads as
# stray letters (「f」 on 白缕轻缠木乃伊, 4K clone 2026-10-21).
DETAIL_NAME_MAX_X = 1300
NAME_MIN_RATIO = 0.6
LOCKED_WORDS = ("潜力释放", "解锁下一级")
# 谈心 opens 「谈心 / 将与 X 进行谈心。… [取消] [确认]」 (2K clone 2026-10-21).
TALK_DIALOG_ROI = (600, 360, 720, 330)
TALK_DIALOG_CONFIRM_POINT = (1072, 628)
TALK_WORD = ("谈心",)

_LEVEL = re.compile(r"lv\.?\s*(\d{1,2})", re.IGNORECASE)
_RECORD = re.compile(r"(?:谈心记录|记录)\D*(\d{1,2})\s*/\s*(\d{1,2})")
_DAILY = re.compile(r"(?<![\d/])([01])\s*/\s*1(?!\d)")
_REMAINING = re.compile(r"(?:剩余谈心次数|谈心次数|次数)\D*?(\d)")


@dataclass(frozen=True)
class Card:
    costume: str  # as read, 简体
    character: str
    level: int | None
    press: tuple[int, int]  # reference point that opens it
    owned: bool = True  # False: 「未拥有」 read on its picture

    @property
    def key(self) -> str:
        return card_key(self.costume, self.character)


@dataclass(frozen=True)
class Detail:
    costume: str
    character: str
    level: int | None
    record: tuple[int, int] | None  # 谈心记录 n / 15
    daily: int | None  # below LV20: talks left today on this costume (1/1 → 1)
    locked: bool

    @property
    def key(self) -> str:
        return card_key(self.costume, self.character)


def card_key(costume: str, character: str) -> str:
    """How a costume is remembered: 「白色猫咪/鲁」, simplified."""
    return f"{normalize(costume)}/{normalize(character)}"


def same_costume(detail: Detail, expected_key: str) -> bool:
    """Whether a panel belongs to the card pressed, its names read with a
    misread character or two: the costume alike, or the character the same
    while the costume is unreadable (a stray letter or nothing)."""
    costume, _, character = expected_key.partition("/")
    if detail.key == expected_key:
        return True
    if costume and SequenceMatcher(None, detail.costume, costume).ratio() >= NAME_MIN_RATIO:
        return True
    same_character = bool(character) and (
        SequenceMatcher(None, detail.character, character).ratio() >= NAME_MIN_RATIO
    )
    return same_character and len(detail.costume) <= 1


def _text(box) -> str:
    return str(getattr(box, "name", "") or "")


# Letters OCR gives for digits right after 「LV」 (「LV.2O」, 「LV.l5」);
# 「LV.B(33%)」 for LV.8 (player frame 2026-10-28, 1080p at 125%).
_DIGIT_LOOKALIKES = str.maketrans(
    {"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1", "B": "8"}
)
_LEVEL_DIGITS = re.compile(r"(lv\.?)([0-9OoDlI|B]{1,2})", re.IGNORECASE)


def read_level(text: str) -> int | None:
    text = _LEVEL_DIGITS.sub(
        lambda m: m.group(1) + m.group(2).translate(_DIGIT_LOOKALIKES), str(text).replace(" ", "")
    )
    match = _LEVEL.search(text)
    if match is None:
        return None
    level = int(match.group(1))
    return level if 1 <= level <= MAX_LEVEL else None


def unowned_label(text: str) -> bool:
    """The short 「未拥有」 on a greyed card (not the game's longer toast)."""
    text = normalize(text)
    return len(text) <= UNOWNED_LABEL_MAX_CHARS and any(w in text for w in UNOWNED_WORDS)


def unowned_toast(text: str) -> bool:
    """The game's answer to pressing a costume not owned."""
    text = normalize(text)
    return any(w in text for w in UNOWNED_WORDS) and ("谈心" in text or "穿戴" in text)


def parse_cards(boxes: list) -> list[Card]:
    """The cards in reading order (rows top to bottom, left to right).

    ``boxes`` are in 1920x1080 reference coordinates.  A card is its level
    line plus the two name lines above it in the same column; a 「未拥有」
    over its picture marks it not owned."""
    levels = [b for b in boxes if read_level(_text(b)) is not None]
    labels = [b for b in boxes if unowned_label(_text(b))]
    names = [
        b
        for b in boxes
        if read_level(_text(b)) is None and normalize(_text(b)) and not unowned_label(_text(b))
    ]
    cards = []
    for level_box in levels:
        lx, ly = float(level_box.x), float(level_box.y)

        def above(span, lx=lx, ly=ly):
            low, high = span
            found = [
                b
                for b in names
                if abs(float(b.x) - lx) <= CARD_COLUMN_SLACK and low <= ly - float(b.y) <= high
            ]
            return min(found, key=lambda b: abs(float(b.x) - lx), default=None)

        costume = above(COSTUME_LINE_ABOVE)
        low, high = UNOWNED_LABEL_ABOVE
        owned = not any(
            abs(float(b.x) - lx) <= CARD_COLUMN_SLACK and low <= ly - float(b.y) <= high
            for b in labels
        )
        character = above(CHARACTER_LINE_ABOVE)
        if costume is None:
            continue
        cards.append(
            Card(
                costume=normalize(_text(costume)),
                character=normalize(_text(character)) if character is not None else "",
                level=read_level(_text(level_box)),
                press=(
                    round(lx + CARD_PRESS_RIGHT_OF_LEVEL),
                    round(ly - CARD_PRESS_ABOVE_LEVEL),
                ),
                owned=owned,
            )
        )
    cards.sort(key=lambda c: (round(c.press[1] / 60), c.press[0]))
    return cards


def read_remaining(text: str) -> int | None:
    """「今日剩余谈心次数 | 3」 → 3."""
    match = _REMAINING.search(normalize(text))
    return int(match.group(1)) if match else None


def parse_detail(header_boxes: list, button_text: str) -> Detail:
    """The detail panel from its header read and the 谈心 button's read."""
    lines = sorted(header_boxes, key=lambda b: (float(b.y), float(b.x)))
    texts = [_text(b) for b in lines]
    joined = " ".join(texts)
    level = None
    record = None
    plain = []
    for line, text in zip(lines, texts):
        if level is None and read_level(text) is not None:
            level = read_level(text)
            continue
        match = _RECORD.search(normalize(text))
        if match:
            record = (int(match.group(1)), int(match.group(2)))
            continue
        word = normalize(text)
        # Exp like 50/160(31%) and the lock note are not names.
        if not word or re.search(r"\d", word) or any(w in word for w in LOCKED_WORDS):
            continue
        if float(getattr(line, "x", 0)) > DETAIL_NAME_MAX_X:
            continue
        plain.append(word)
    daily = None
    if level is not None and level < MAX_LEVEL:
        match = _DAILY.search(button_text.replace(" ", ""))
        daily = int(match.group(1)) if match else None
    return Detail(
        character=plain[0] if plain else "",
        costume=plain[1] if len(plain) > 1 else "",
        level=level,
        record=record,
        daily=daily,
        locked=any(word in normalize(joined) for word in LOCKED_WORDS),
    )
