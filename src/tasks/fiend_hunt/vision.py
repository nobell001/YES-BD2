"""Read the 魔兽追踪者 planning screen from one frame.

Pure image code (no capture, no mouse) so it can be tested on saved frames
at any resolution.  Text is read through an injected ``ocr`` callable
(image -> list of recognised strings); everything else is pixel checks
measured on the 4K PC's frames (2026-09-30) and checked at 1080p/2K/4K.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from src.tasks.fiend_hunt import layout
from src.tasks.fiend_hunt.planner import COLS, ROWS, Cell
from src.utils.image_utils import correlation_response, template_match_response, to_gray

Ocr = Callable[[np.ndarray], Sequence[str]]

DATA = Path(__file__).resolve().parent / "data"

BATTLE_BUTTON_MIN = 0.8
BATTLE_END_MIN = 0.7
# 塔洛斯战术教材 ends on VICTORY, drawn where BATTLE END is and in the same
# letters (2K PC 2026-10-28, stages 1-2: 0.99-1.00; the guide video's nine
# wins at 480p 0.92-0.94, their fade-in 0.6-0.7; every planning, battle and
# BATTLE END frame kept 0.38 or less).
VICTORY_MIN = 0.8
OUT_MIN = 0.6
# A selected unit's portrait gets white corner brackets; unselected slots
# score 0.00, selected ones 0.32-0.43 on every saved frame.
SELECTED_MIN = 0.2
SWAP_BUTTON_MIN = 8.0  # % of white ⇅ arrow pixels; 18-19 with a unit, 0 on an empty slot


def _ref(frame: np.ndarray, box: layout.Box) -> np.ndarray:
    """``box`` cut from ``frame`` and scaled to reference (1080p) pixels."""
    part = layout.crop(frame, box)
    size = (round(box[2] - box[0]), round(box[3] - box[1]))
    if part.shape[1] == size[0] and part.shape[0] == size[1]:
        return part
    return cv2.resize(part, size, interpolation=cv2.INTER_AREA)


def _bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


@lru_cache(maxsize=None)
def _template(name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(DATA / name, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(DATA / name)
    return image


def _match(frame: np.ndarray, box: layout.Box, name: str, margin: float = 12.0) -> float:
    left, top, right, bottom = box
    area = to_gray(_ref(frame, (left - margin, top - margin, right + margin, bottom + margin)))
    template = _template(name)
    if area.shape[0] < template.shape[0] or area.shape[1] < template.shape[1]:
        return -1.0
    return float(template_match_response(area, template).max())


# --- which screen -------------------------------------------------------------------------


def battle_button_score(frame: np.ndarray) -> float:
    """The word BATTLE on its white pill: the planning screen is up."""
    return _match(frame, layout.BATTLE_WORD_BOX, "battle_word.png")


def planning_visible(frame: np.ndarray) -> bool:
    return battle_button_score(frame) >= BATTLE_BUTTON_MIN


def battle_end_score(frame: np.ndarray) -> float:
    return _match(frame, layout.BATTLE_END_BOX, "battle_end.png")


def battle_end_visible(frame: np.ndarray) -> bool:
    return battle_end_score(frame) >= BATTLE_END_MIN


def victory_score(frame: np.ndarray) -> float:
    return _match(frame, layout.BATTLE_END_BOX, "victory_word.png")


def victory_visible(frame: np.ndarray) -> bool:
    return victory_score(frame) >= VICTORY_MIN


# A lost fight: 塔洛斯 stage 7 on the 2K PC 2026-10-28 showed 「DEFEAT」 in
# white on a red band across the whole screen's middle (返回 / 重新挑战
# under it), not where VICTORY shows.  The band is checked by colour first
# (every column red, dark above it), then its middle read; the VICTORY box is
# read too, for a word shown there.
DEFEAT_WORDS = ("DEFEAT", "LOSE", "FAIL", "失败")
DEFEAT_BAND_BOX: layout.Box = (0.0, 458.0, 1920.0, 538.0)
DEFEAT_ABOVE_BOX: layout.Box = (0.0, 405.0, 1920.0, 435.0)
DEFEAT_WORD_BOX: layout.Box = (760.0, 458.0, 1160.0, 538.0)
DEFEAT_RED_MIN = 30.0  # red over green/blue, per column (the band: 50+)
DEFEAT_RED_COLUMNS = 0.8  # share of columns that must be that red


def end_word(frame: np.ndarray, ocr: Ocr) -> str:
    """The word where BATTLE END / VICTORY shows, read as text (upper case, no spaces)."""
    return _ocr_text(_text_image(frame, layout.BATTLE_END_BOX, 68), ocr).upper().replace(" ", "")


PREEMPT_WORDS = ("先发制人", "先發制人")
PREEMPT_ON_MIN = 0.1  # share of the switch that is orange when on (0.23 on, 0.0 off)


def preempt_beside(frame: np.ndarray, ocr: Ocr, row: int) -> bool:
    """Whether card row ``row`` has the 「先发制人」 switch beside it."""
    text = _ocr_text(_text_image(frame, layout.preempt_text_box(row), 68), ocr)
    return any(word in text for word in PREEMPT_WORDS)


def preempt_on(frame: np.ndarray, row: int) -> bool:
    hsv = cv2.cvtColor(_bgr(_ref(frame, layout.preempt_switch_box(row))), cv2.COLOR_BGR2HSV)
    orange = (
        (hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 30) & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 120)
    )
    return float(orange.mean()) >= PREEMPT_ON_MIN


def _redness(frame: np.ndarray, box: layout.Box) -> np.ndarray:
    """Red over the larger of green and blue, the median of each column."""
    part = _bgr(_ref(frame, box)).astype(np.int16)
    red = part[:, :, 2] - np.maximum(part[:, :, 0], part[:, :, 1])
    return np.median(red, axis=0)


def defeat_band(frame: np.ndarray) -> bool:
    band = _redness(frame, DEFEAT_BAND_BOX)
    above = _redness(frame, DEFEAT_ABOVE_BOX)
    return (
        float((band >= DEFEAT_RED_MIN).mean()) >= DEFEAT_RED_COLUMNS
        and float((above >= DEFEAT_RED_MIN).mean()) < DEFEAT_RED_COLUMNS
    )


def lost_word(frame: np.ndarray, ocr: Ocr) -> str | None:
    """The lost fight's word as read (DEFEAT), or None."""
    words = []
    if defeat_band(frame):
        words.append(_ocr_text(_text_image(frame, DEFEAT_WORD_BOX, 68), ocr).upper())
    words.append(end_word(frame, ocr))
    for word in words:
        word = word.replace(" ", "")
        if any(each in word for each in DEFEAT_WORDS):
            return word
    return None


def lost_visible(frame: np.ndarray, ocr: Ocr) -> bool:
    return lost_word(frame, ocr) is not None


# A battle never holds still: the units, the boss and the effects keep
# moving.  The whole screen, shrunk, is compared with how it looked when it
# last changed; a still screen means the game stopped (a disconnect dialog,
# a freeze).  A dialog's spinner moves far fewer pixels than this.
STILL_SIZE = (160, 90)
STILL_PIXEL_DIFF = 12  # grey levels for a pixel to count as changed
STILL_CHANGED_MAX = 0.005  # share of changed pixels a still screen stays under


def still_picture(frame: np.ndarray) -> np.ndarray:
    """The screen shrunk to grey, to tell a still screen from a moving one."""
    small = cv2.resize(_bgr(frame), STILL_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def same_still(earlier: np.ndarray, now: np.ndarray) -> bool:
    changed = cv2.absdiff(earlier, now) > STILL_PIXEL_DIFF
    return float(changed.mean()) <= STILL_CHANGED_MAX


def floor_level(frame: np.ndarray) -> float:
    """Mean grey of the floor under the grid (about 119 top-down, 52 isometric)."""
    return float(to_gray(_ref(frame, layout.FLOOR_BOX)).mean())


def is_topdown(frame: np.ndarray) -> bool:
    """Top-down view: the floor under the grid is light grey, not dark or coloured.

    塔洛斯战术教材 is told by its own floor (talos_topdown): stage 3's angled
    view stands on light stone, which the floor check took for the top-down
    grey (2K PC 2026-10-28: cells pressed in the angled view)."""
    if talos_layout(frame):
        return talos_topdown(frame)
    if floor_level(frame) <= layout.TOPDOWN_FLOOR_MIN:
        return False
    hsv = cv2.cvtColor(_bgr(_ref(frame, layout.FLOOR_BOX)), cv2.COLOR_BGR2HSV)
    return float(hsv[..., 1].mean()) <= layout.TOPDOWN_FLOOR_SAT_MAX


# 切换视角 isn't always in the same place: 塔洛斯战术教材 puts 切换画面 where
# it stands in a 魔兽 fight and moves it 100 px left (2K PC 2026-10-22, the
# fixed tap hit the greyed-out 切换画面).  Its white icon (data/view_toggle.png)
# is found along the bottom right: 0.90-0.99 on every frame showing it, at
# most 0.43 elsewhere; the button is pressed where the icon is.
VIEW_TOGGLE_BOX: layout.Box = (1250.0, 925.0, 1700.0, 1000.0)
VIEW_TOGGLE_MIN = 0.7
VIEW_TOGGLE_BELOW_ICON = 13.0  # reference px from the icon's centre to the press


def view_toggle_point(frame: np.ndarray) -> layout.Point | None:
    """Where to press 切换视角; None when its icon isn't seen."""
    area = np.where(to_gray(_ref(frame, VIEW_TOGGLE_BOX)) > 200, 255, 0).astype(np.uint8)
    icon = np.where(_template("view_toggle.png") > 200, 255, 0).astype(np.uint8)
    _, score, _, (x, y) = cv2.minMaxLoc(template_match_response(area, icon))
    if score < VIEW_TOGGLE_MIN:
        return None
    left, top = VIEW_TOGGLE_BOX[:2]
    return (
        left + x + icon.shape[1] / 2,
        top + y + icon.shape[0] / 2 + VIEW_TOGGLE_BELOW_ICON,
    )


# 塔洛斯战术教材 puts 切换视角 at x 1420 (a 魔兽 fight: 1520).  Its top-down
# view stands on a lavender tiled floor; every angled stage shows its own
# scenery, light stone too (stage 3), which the floor check took for the
# top-down grey.  Three places away from the list, the grid and the buttons
# (2K PC 2026-10-28, stages 3-5): top-down hue 131-161, saturation 26-37;
# angled hue 26-93, saturation 64-103.  (切换画面 beside it is no sign:
# lit in stage 3's angled view, greyed in stage 5's.)
TALOS_TOGGLE_X_MAX = 1470.0
TALOS_FLOOR_BOXES: tuple[layout.Box, ...] = (
    (170.0, 600.0, 330.0, 760.0),
    (400.0, 130.0, 1500.0, 220.0),
    (700.0, 820.0, 1250.0, 900.0),
)
TALOS_FLOOR_HUE = (115.0, 170.0)
TALOS_FLOOR_SAT_MAX = 50.0


def talos_layout(frame: np.ndarray) -> bool:
    """塔洛斯战术教材's planning buttons (切换视角 left of its usual place)."""
    point = view_toggle_point(frame)
    return point is not None and point[0] <= TALOS_TOGGLE_X_MAX


def talos_topdown(frame: np.ndarray) -> bool:
    """塔洛斯: the lavender top-down floor in at least two of the three places."""
    lavender = 0
    for box in TALOS_FLOOR_BOXES:
        hsv = cv2.cvtColor(_bgr(_ref(frame, box)), cv2.COLOR_BGR2HSV)
        hue, saturation = float(hsv[..., 0].mean()), float(hsv[..., 1].mean())
        if TALOS_FLOOR_HUE[0] <= hue <= TALOS_FLOOR_HUE[1] and saturation <= TALOS_FLOOR_SAT_MAX:
            lavender += 1
    return lavender >= 2


_VIEW_SCALE = 0.5  # the reference is kept at half the 1080p size


def view_offset(frame: np.ndarray) -> tuple[float, float] | None:
    """How far (1080p px) the top-down camera is from its place; None if unsure."""
    reference = _template("topdown_view.png")
    if reference.ndim == 3:
        reference = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    part = to_gray(_ref(frame, layout.VIEW_BOX))
    part = cv2.resize(part, reference.shape[::-1], interpolation=cv2.INTER_AREA)
    (dx, dy), response = cv2.phaseCorrelate(np.float32(reference), np.float32(part))
    if response < VIEW_RESPONSE_MIN:
        return None
    return dx / _VIEW_SCALE, dy / _VIEW_SCALE


VIEW_RESPONSE_MIN = 0.08


# --- left list ----------------------------------------------------------------------------


def swap_button_score(frame: np.ndarray, slot: int) -> float:
    x, y = layout.slot_swap(slot)
    part = _bgr(_ref(frame, (x - 12, y - 14, x + 12, y + 14)))
    return float((part.min(axis=2) > 200).mean() * 100)


def slot_count(frame: np.ndarray) -> int:
    """How many list slots hold a unit (5, or 6 with a summon)."""
    filled = [swap_button_score(frame, slot) >= SWAP_BUTTON_MIN for slot in range(layout.MAX_SLOTS)]
    count = 0
    while count < len(filled) and filled[count]:
        count += 1
    if any(filled[count:]):
        return -1  # a gap in the list: not the planning list
    return count


# The list can sit lower than usual: 10-12 px on the 2K PC's 2-unit team of
# 2026-10-07 (cards and header where they always are), and the brackets were
# missed on every hold.  The pair of corners is looked for this far up and
# down; a neighbour's corners are 87.5 px away, and both must show at one shift.
SELECTED_SHIFTS = range(-8, 25, 2)


def selected_score(frame: np.ndarray, slot: int) -> float:
    """White corner brackets left of the portrait (both corners must show)."""
    y = layout.SLOT_Y[slot]
    part = _bgr(
        _ref(frame, (84.0, y - 44 + SELECTED_SHIFTS[0], 90.0, y + 44 + SELECTED_SHIFTS[-1]))
    )
    white = part.min(axis=2) > 215  # rows from y - 52, about 1 px per reference px
    scale = white.shape[0] / (88.0 + SELECTED_SHIFTS[-1] - SELECTED_SHIFTS[0])

    def rows(start: float, end: float) -> np.ndarray:
        return white[round(start * scale) : max(round(end * scale), round(start * scale) + 1)]

    best = 0.0
    for shift in SELECTED_SHIFTS:
        at = shift - SELECTED_SHIFTS[0]  # reference px from the part's top
        top = float(rows(at, at + 28).mean(axis=0).max())
        bottom = float(rows(at + 60, at + 88).mean(axis=0).max())
        best = max(best, min(top, bottom))
    return best


def selected_slots(frame: np.ndarray, count: int = layout.MAX_SLOTS) -> list[int]:
    return [slot for slot in range(count) if selected_score(frame, slot) >= SELECTED_MIN]


def out_score(frame: np.ndarray, slot: int) -> float:
    """The white word OUT on a dead unit's portrait (art behind it doesn't matter)."""
    part = to_gray(_ref(frame, layout.slot_box(slot)))
    white = np.where(part > 215, 255, 0).astype(np.uint8)
    return float(template_match_response(white, _template("out_text.png")).max())


def out_slots(frame: np.ndarray, count: int) -> list[int]:
    return [slot for slot in range(count) if out_score(frame, slot) >= OUT_MIN]


# --- card column (the selected unit's actions) ------------------------------------------
# A card shows at its left edge: a light border line 10-110 grey levels
# above the pixels beside it, or (a greyed card on the light top-down
# floor) a panel at least 13 levels darker than the floor outside it (a
# greyed card 14).  An empty row scored 0.2 at most until the 4K 水魔兽 floor
# beside the ⇅ buttons scored 7 (2026-10-08).
CARD_EDGE_MIN = 10.0
# The chosen card is lit in the element colour: brightness x saturation of
# its rim is 41-80.  Other cards and empty rows score 32 at most (a
# saturated purple skill art at T21) and at least 25 below the lit one
# (1080p/2K/4K, top-down and isometric, 27 frames of 2026-09-30/10-01).
CARD_LIT_MIN = 36.0
CARD_LIT_MARGIN = 15.0
CARD_LABELS = ("攻击", "击退")


def card_edge_score(frame: np.ndarray, row: int) -> float:
    """How clearly a card's left edge shows in list row ``row``."""
    left, top, right, bottom = layout.card_box(row)
    height = bottom - top
    box = (left - 6, top + height * 0.15, left + 6, bottom - height * 0.15)
    part = to_gray(_bgr(layout.crop(frame, box))).astype(np.float32)
    size = (48, round((box[3] - box[1]) * 2))  # 4 px per reference pixel across
    gray = cv2.resize(part, size, interpolation=cv2.INTER_AREA)
    line = -255.0
    for x in range(16, 33):  # the border within 2 reference pixels of CARD_X[0]
        beside = np.maximum(gray[:, x - 12], gray[:, x + 12])
        line = max(line, float(np.median(gray[:, x] - beside)))
    darker = float(np.median(gray[:, 4] - gray[:, 44]))  # floor 5 px outside vs 5 px inside
    return max(line, darker)


def card_count(frame: np.ndarray) -> int:
    """Cards in the column (0 when no unit's column is up)."""
    count = 0
    while count < layout.MAX_SLOTS and card_edge_score(frame, count) >= CARD_EDGE_MIN:
        count += 1
    return count


def card_lit_score(frame: np.ndarray, row: int) -> float:
    left, top, right, bottom = layout.card_box(row)
    part = _bgr(_ref(frame, (left - 4, top - 4, right + 4, bottom + 4)))
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV).astype(np.float32)
    lit = hsv[..., 1] * hsv[..., 2] / 255.0
    rim = np.ones(lit.shape, bool)
    rim[10:-10, 10:-10] = False
    rim[:2, :] = rim[-2:, :] = False
    rim[:, :2] = rim[:, -2:] = False
    return float(lit[rim].mean())


def lit_card(frame: np.ndarray) -> int | None:
    """Row of the chosen card; None unless one card is clearly lit above the rest."""
    count = card_count(frame)
    if count <= layout.FIRST_SKILL_ROW:
        return None
    scores = [card_lit_score(frame, row) for row in range(count)]
    best = max(range(count), key=scores.__getitem__)
    runner_up = max(score for row, score in enumerate(scores) if row != best)
    if scores[best] < CARD_LIT_MIN or scores[best] - runner_up < CARD_LIT_MARGIN:
        return None
    return best


def card_label(row: int) -> str:
    """攻击 / 击退 / 技能1.. (skill cards counted top to bottom)."""
    if row < len(CARD_LABELS):
        return CARD_LABELS[row]
    return f"技能{row - layout.FIRST_SKILL_ROW + 1}"


def card_row(label: str) -> int | None:
    """The row of a card label; None for a label that names no one card."""
    if label in CARD_LABELS:
        return CARD_LABELS.index(label)
    number = label.removeprefix("技能")
    if number != label and number.isdigit() and int(number) >= 1:
        return layout.FIRST_SKILL_ROW + int(number) - 1
    return None


# --- the card a list entry shows ------------------------------------------------------------
# Measured on the 4K PC (2026-10-01): 58 captures of T1 with every unit on
# each of its cards, and the saves self_0930, self_1001 and self_1001b (the
# same fight recorded three times), also scaled to 2K and 1080p.
#
# Face band, median over pixels of the largest channel difference, between
# entries on a skill card: 0 between settled captures of one card (also
# 90 s apart), at most 3 between recordings of the same turn and when one
# frame catches the arc that sweeps an entry for about 0.1 s after a pick
# or a tap on ⇅; 40 or more between different skill cards (each skill card
# is its own costume).  An attack is told by having no icon.
FACE_SAME_MAX = 12.0
FACE_DIFFERENT_MIN = 24.0
# Round skill icon: share of 72 directions round the icon centre with a
# sharp step (> ICON_EDGE_STEP grey levels per reference pixel) where its
# ring should be.  Skill cards 0.69-1.00, attacks 0.07-0.56 (1080p-4K, arcs
# included).  Its inside is not compared: its ring and glow change colour
# between runs.
ICON_EDGE_STEP = 30.0
ICON_PRESENT_MIN = 0.65
ICON_ABSENT_MAX = 0.60
_ICON_SCALE = 4  # icon work image: 4 px per reference pixel
# 击退 (knockback, the card under the normal attack; 塔洛斯战术教材 uses it,
# Leo 2026-10-22): a white arrow on a dark disc where the skill icon sits.
# Over a bright portrait the disc is faint and the ring check fails, so the
# arrow's white shape is fitted (IoU with knockback_arrow.png, cut from a 2K
# capture).  Arrows 0.87-1.00, skill icons and bare portraits 0.00-0.63 (2K
# capture + 32 turns of a 720p guide video, every turn and direction).
ARROW_WHITE_V = 200
ARROW_WHITE_S = 60
ARROW_R = 9.0  # reference px round the icon centre holding the arrow
ARROW_SHIFT = 8  # work px tried off centre
ARROW_PRESENT_MIN = 0.80
ARROW_ABSENT_MAX = 0.70
SKILL_LABEL = "技能"
_ICON_DIRECTIONS = 72
# Two captures of the list agree (90th percentile of the pixel difference
# in each entry's face band) once nothing sweeps it.
LIST_STEADY_DIFF = 8.0
LIST_STEADY_ICON_DIFF = 0.03  # an unclear icon score that holds this well


def face_difference(frame: np.ndarray, slot: int, other: np.ndarray, other_slot: int) -> float:
    """Median largest-channel difference of two entries' face bands (0 = the same)."""
    face = _bgr(_ref(frame, layout.face_box(slot))).astype(np.int16)
    theirs = _bgr(_ref(other, layout.face_box(other_slot))).astype(np.int16)
    return float(np.median(np.abs(face - theirs).max(axis=2)))


def skill_icon_score(frame: np.ndarray, slot: int) -> float:
    """How much of a round edge there is where a skill card's icon sits (0..1)."""
    box = layout.icon_box(slot)
    part = to_gray(_bgr(layout.crop(frame, box))).astype(np.float32)
    side = round((box[2] - box[0]) * _ICON_SCALE)
    shrink = part.shape[0] > side
    gray = cv2.resize(
        part, (side, side), interpolation=cv2.INTER_AREA if shrink else cv2.INTER_LINEAR
    )
    centre = side / 2
    angles = np.linspace(0, 2 * np.pi, _ICON_DIRECTIONS, endpoint=False)
    radii = np.arange(layout.ICON_RING[0] * _ICON_SCALE, layout.ICON_RING[1] * _ICON_SCALE)
    xs = (centre + np.outer(np.cos(angles), radii)).astype(np.float32)
    ys = (centre + np.outer(np.sin(angles), radii)).astype(np.float32)
    profiles = cv2.remap(gray, xs, ys, cv2.INTER_LINEAR)
    steps = np.abs(np.diff(profiles, axis=1)).max(axis=1) * _ICON_SCALE
    return float((steps > ICON_EDGE_STEP).mean())


@lru_cache(maxsize=None)
def _arrow_masks() -> tuple[np.ndarray, ...]:
    """The 击退 arrow (white, pointing up) turned in 45° steps."""
    arrow = _template("knockback_arrow.png") > 127
    side = arrow.shape[0]
    masks = []
    for step in range(8):
        turn = cv2.getRotationMatrix2D((side / 2 - 0.5, side / 2 - 0.5), -45 * step, 1)
        turned = cv2.warpAffine(arrow.astype(np.uint8), turn, (side, side), flags=cv2.INTER_NEAREST)
        masks.append(turned > 0)
    return tuple(masks)


def knockback_score(frame: np.ndarray, slot: int) -> float:
    """How well the white shape where the list icon sits fits the 击退 arrow (0..1).

    The arrow points the way the unit knocks (each character its own way, Leo
    2026-10-22), so every 45° turn is tried, a few pixels off centre too.
    """
    x, dy = layout.ICON_CENTRE
    y = layout.SLOT_Y[slot] + dy
    masks = _arrow_masks()
    side = masks[0].shape[0]
    reach = side / _ICON_SCALE / 2
    part = _bgr(layout.crop(frame, (x - reach, y - reach, x + reach, y + reach)))
    if part.size == 0:
        return 0.0
    shrink = part.shape[0] > side
    part = cv2.resize(
        part, (side, side), interpolation=cv2.INTER_AREA if shrink else cv2.INTER_CUBIC
    )
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
    white = (hsv[..., 2] > ARROW_WHITE_V) & (hsv[..., 1] < ARROW_WHITE_S)
    ys, xs = np.mgrid[:side, :side]
    inside = np.hypot(xs - side / 2 + 0.5, ys - side / 2 + 0.5) < ARROW_R * _ICON_SCALE
    area = int(masks[0].sum())
    around = np.hypot(xs - side / 2 + 0.5, ys - side / 2 + 0.5)
    most = int((white & (around < ARROW_R * _ICON_SCALE + ARROW_SHIFT * 1.5)).sum())
    least = int((white & (around < ARROW_R * _ICON_SCALE - ARROW_SHIFT * 1.5)).sum())
    if most < area * ARROW_ABSENT_MAX or least > area / ARROW_ABSENT_MAX:
        return 0.0  # too little or too much white to fit the arrow at all (quick way out)
    best = 0.0
    for dx in range(-ARROW_SHIFT, ARROW_SHIFT + 1, 2):
        for dy_ in range(-ARROW_SHIFT, ARROW_SHIFT + 1, 2):
            near = white & np.roll(inside, (dy_, dx), (0, 1))
            for mask in masks:
                shifted = np.roll(mask, (dy_, dx), (0, 1))
                union = (near | shifted).sum()
                if union:
                    best = max(best, float((near & shifted).sum() / union))
    return best


def has_knockback(frame: np.ndarray, slot: int) -> bool | None:
    """True: the entry shows the 击退 arrow; False: it doesn't; None: can't tell."""
    score = knockback_score(frame, slot)
    if score >= ARROW_PRESENT_MIN:
        return True
    if score <= ARROW_ABSENT_MAX:
        return False
    return None


def list_action(frame: np.ndarray, slot: int) -> str | None:
    """攻击 / 击退 / 技能 as list entry ``slot`` shows it; None when unsure."""
    knockback = has_knockback(frame, slot)
    if knockback is None:
        return None
    if knockback:
        return CARD_LABELS[layout.KNOCKBACK_ROW]
    icon = _round_icon(frame, slot)
    if icon is None:
        return None
    return SKILL_LABEL if icon else CARD_LABELS[layout.ATTACK_ROW]


def has_skill_icon(frame: np.ndarray, slot: int) -> bool | None:
    """True: a skill card; False: an attack or 击退 (no SP); None: can't tell.

    The 击退 arrow sits in a round dark disc where a skill icon sits, so it
    is ruled out first (塔洛斯战术教材, 2026-10-22)."""
    knockback = has_knockback(frame, slot)
    if knockback is None:
        return None
    return False if knockback else _round_icon(frame, slot)


def _round_icon(frame: np.ndarray, slot: int) -> bool | None:
    score = skill_icon_score(frame, slot)
    if score >= ICON_PRESENT_MIN:
        return True
    if score <= ICON_ABSENT_MAX:
        return False
    return None


def same_card(frame: np.ndarray, slot: int, saved: np.ndarray, saved_slot: int) -> bool | None:
    """Whether list entry ``slot`` shows the card ``saved_slot`` shows in ``saved``.

    A skill card shows its costume's portrait with the round icon: the same
    only with the icon and the same face.  An attack has no icon and 击退
    its arrow; their portrait is not tied to the card (on the 4K PC it
    changed after picks within one planning screen), so an attack is the
    same as an attack, 击退 as 击退.
    Both frames are compared at 1080p reference size, so they may differ in
    resolution, but should come from the same PC (same colours).  None when
    it isn't clear.
    """
    action, saved_action = list_action(frame, slot), list_action(saved, saved_slot)
    if action is None or saved_action is None:
        return None
    if action != saved_action:
        return False
    if saved_action != SKILL_LABEL:
        return True  # 攻击 or 击退: the portrait isn't tied to the card
    face = face_difference(frame, slot, saved, saved_slot)
    if face <= FACE_SAME_MAX:
        return True
    if face >= FACE_DIFFERENT_MIN:
        return False
    return None


def list_steady(frame: np.ndarray, other: np.ndarray, slots: int) -> bool:
    """The first ``slots`` list entries hold still between the two frames.

    Their face bands agree and each has, or lacks, its skill icon in both (the
    icon's inside shimmers, so it isn't compared).  An entry whose icon can't
    be told counts as still when its score holds (4K PC 2026-10-01, 尤里光盾
    TURN 21: 尤里's portrait scored 0.639 on every capture, between "no icon"
    and "icon", and the list was never steady, so every card check gave up).
    """
    for slot in range(slots):
        face = _bgr(_ref(frame, layout.face_box(slot))).astype(np.int16)
        theirs = _bgr(_ref(other, layout.face_box(slot))).astype(np.int16)
        if np.percentile(np.abs(face - theirs).max(axis=2), 90) > LIST_STEADY_DIFF:
            return False
        icon, their_icon = has_skill_icon(frame, slot), has_skill_icon(other, slot)
        if icon is None or their_icon is None:
            score, their_score = skill_icon_score(frame, slot), skill_icon_score(other, slot)
            if abs(score - their_score) > LIST_STEADY_ICON_DIFF:
                return False
        elif icon != their_icon:
            return False
    return True


# --- grid ---------------------------------------------------------------------------------


def grid_cell_box(cell: Cell, grid: Grid | None = None) -> layout.Box:
    """The cell's box as drawn: layout's, or moved and sized with ``grid``."""
    left, top, right, bottom = layout.cell_box(cell)
    if grid is None:
        return left, top, right, bottom
    (left, top), (right, bottom) = grid.point((left, top)), grid.point((right, bottom))
    return left, top, right, bottom


def cell_busy_score(frame: np.ndarray, cell: Cell, grid: Grid | None = None) -> float:
    """Contrast inside a cell: a unit or tombstone scores high, bare floor low.

    Only used to decide which cells to hold first, never as the answer.
    ``grid``: where the cells are really drawn (塔洛斯: a bigger grid, Leo
    2026-10-28 「我看你常常一格一格點 找角色」 — read at layout's places
    the units' cells looked like bare floor).
    """
    return float(to_gray(_ref(frame, grid_cell_box(cell, grid))).std())


# Where the top-down grid really is, from the white brackets at the cells'
# corners: some fights move and shrink it (4K PC 2026-10-08, 水魔兽 T3: cells
# 0.90 the size, the grid 46 px right), and the fixed cells then miss.  The
# bracket pattern of layout's cells is matched at scales 0.80-1.12; on the
# saved 1080p/2K/4K top-down frames it came out at scale 0.99-1.00, its top
# left within 1 px of GRID_FOUND_AT, and at 0.90 on the 水魔兽 frame.
GRID_SEARCH_BOX: layout.Box = (380.0, 330.0, 880.0, 750.0)
GRID_SCALES = tuple(round(0.80 + 0.01 * step, 2) for step in range(33))
# 塔洛斯战术教材 draws it far bigger and higher (2K PC 2026-10-22: scale 1.31,
# top left 395,264; the guide video's nine stages 1.31-1.32, top 398-498).
# Searched only when the usual room finds nothing (it takes 4 times as long).
GRID_WIDE_BOX: layout.Box = (380.0, 240.0, 920.0, 800.0)
GRID_WIDE_SCALES = tuple(round(0.80 + 0.01 * step, 2) for step in range(61))
GRID_ARM = 9.0  # bracket arm, reference px
GRID_FOUND_AT = (480.0, 432.0)  # where the match puts layout's own grid
GRID_MATCH_MIN = 0.2


# 塔洛斯战术教材's top-down view zooms with the mouse wheel: a bar with
# 「N%」 under its knob shows top middle while it turns (2K PC 2026-10-28:
# 78-80% at the far end, then 84, 88, 92, 97, 101, 105, 110, 114 a notch;
# the grid drawn about 1.32 x N/100 times layout's size).  The text is read
# along the whole bar, as it follows the knob.
ZOOM_TEXT_BOX: layout.Box = (780.0, 95.0, 1110.0, 130.0)
_ZOOM_TEXT = re.compile(r"(\d{2,3})\s*%")


def zoom_percent(frame: np.ndarray, ocr: Ocr) -> int | None:
    """N of the 「N%」 zoom bar while it shows; None otherwise."""
    found = _ZOOM_TEXT.search(_ocr_text(_text_image(frame, ZOOM_TEXT_BOX, 68), ocr))
    if found is None:
        return None
    value = int(found.group(1))
    return value if 50 <= value <= 200 else None


@dataclass(frozen=True)
class Grid:
    """The grid as drawn: layout's cells scaled by ``scale`` about their top
    left, which stands at (``left``, ``top``) in reference px."""

    scale: float
    left: float
    top: float

    def point(self, point: layout.Point) -> layout.Point:
        x, y = point
        origin_x, origin_y = layout.CELL_X[0][0], layout.CELL_Y[0][0]
        return self.left + (x - origin_x) * self.scale, self.top + (y - origin_y) * self.scale

    def off(self, other: Grid) -> bool:
        """Whether cells pressed by ``other`` would land noticeably wrong here."""
        return (
            abs(self.scale - other.scale) > GRID_SCALE_SLACK
            or abs(self.left - other.left) > GRID_SHIFT_SLACK
            or abs(self.top - other.top) > GRID_SHIFT_SLACK
        )


LAYOUT_GRID = Grid(1.0, layout.CELL_X[0][0], layout.CELL_Y[0][0])
GRID_SCALE_SLACK = 0.03
GRID_SHIFT_SLACK = 8.0  # reference px


@lru_cache(maxsize=None)
def _grid_brackets(scale: float) -> np.ndarray:
    origin_x, origin_y = layout.CELL_X[0][0], layout.CELL_Y[0][0]
    width = int(np.ceil((layout.CELL_X[-1][1] - origin_x) * scale)) + 4
    height = int(np.ceil((layout.CELL_Y[-1][1] - origin_y) * scale)) + 4
    image = np.zeros((height, width), np.float32)
    arm = max(3, round(GRID_ARM * scale))
    for left, right in layout.CELL_X:
        for top, bottom in layout.CELL_Y:
            xs = (
                (round((left - origin_x) * scale) + 1, 1),
                (round((right - origin_x) * scale) + 1, -1),
            )
            ys = (
                (round((top - origin_y) * scale) + 1, 1),
                (round((bottom - origin_y) * scale) + 1, -1),
            )
            for x, step_x in xs:
                for y, step_y in ys:
                    cv2.line(image, (x, y), (x + step_x * arm, y), 1.0, 2)
                    cv2.line(image, (x, y), (x, y + step_y * arm), 1.0, 2)
    return image


def grid_on_screen(frame: np.ndarray) -> Grid | None:
    """The top-down grid as drawn (see GRID_SEARCH_BOX); None when its brackets aren't seen."""
    found = _find_grid(frame, GRID_SEARCH_BOX, GRID_SCALES)
    if found is not None:
        return found
    return _find_grid(frame, GRID_WIDE_BOX, GRID_WIDE_SCALES, every_column=True)


# 塔洛斯's empty columns have dim brackets, so a match one column right (its
# last column on the bare floor between the two sides) scored about as well:
# 2K PC frame scaled to 2560, 0.316 there against 0.306 in place.  That last
# column then holds no bracket at all (0.00 of its arms lit; the dimmest real
# column 0.05).  The wide search takes the best match whose every column has some.
GRID_COLUMN_MIN = 0.02
GRID_TRIES = 4


def _column_arms(bright: np.ndarray, brackets: np.ndarray, x: int, y: int, scale: float) -> float:
    """The least lit share of one column's bracket arms, with the match at ``x``, ``y``."""
    height, width = brackets.shape
    window = bright[y : y + height, x : x + width]
    origin_x = layout.CELL_X[0][0]
    least = 1.0
    for left, right in layout.CELL_X:
        a, b = round((left - origin_x) * scale), round((right - origin_x) * scale) + 3
        arms = brackets[:, a:b]
        least = min(least, float((window[:, a:b] * arms).sum() / max(arms.sum(), 1.0)))
    return least


def _find_grid(
    frame: np.ndarray, box: layout.Box, scales: tuple[float, ...], every_column: bool = False
) -> Grid | None:
    part = _bgr(_ref(frame, box))
    gray = cv2.cvtColor(part, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bright = ((gray - cv2.blur(gray, (9, 9)) > 22) & (gray > 165)).astype(np.float32)
    best = (GRID_MATCH_MIN, None)
    for scale in scales:
        brackets = _grid_brackets(scale)
        if brackets.shape[0] > bright.shape[0] or brackets.shape[1] > bright.shape[1]:
            continue
        scores = correlation_response(bright, brackets)
        for _ in range(GRID_TRIES if every_column else 1):
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            if score <= best[0]:
                break
            if not every_column or _column_arms(bright, brackets, x, y, scale) >= GRID_COLUMN_MIN:
                best = (score, (scale, x, y))
                break
            # no bracket in a column: not the grid; look past this place
            reach = round(GRID_ARM * scale)
            scores[max(0, y - reach) : y + reach + 1, max(0, x - reach) : x + reach + 1] = 0
    if best[1] is None:
        return None
    scale, x, y = best[1]
    found_x, found_y = GRID_FOUND_AT
    return Grid(
        scale,
        box[0] + x + (layout.CELL_X[0][0] - found_x) * scale,
        box[1] + y + (layout.CELL_Y[0][0] - found_y) * scale,
    )


def cells_by_busy(frame: np.ndarray, grid: Grid | None = None) -> list[Cell]:
    cells = [(row, col) for row in range(ROWS) for col in range(COLS)]
    return sorted(cells, key=lambda cell: -cell_busy_score(frame, cell, grid))


# --- who stands on a cell, from the look of the unit (fighting from screenshots) -----------
# A unit is drawn standing on its cell and about one cell tall, so the patch
# is the cell plus one cell height above it.  Measured on the 2K saves
# self_2k_a and self_2k_b (the same fight recorded twice, 2026-10-01): a
# unit's patch from one recording found its own cell in the other's
# screenshot of the same turn 60/60 times, by 0.084 or more over any other
# cell (normalised cross-correlation, the patch let slide 6 px).  Across
# turns, where costumes (and so the drawings) change, it was far less sure,
# so units are only compared once their cards match the screenshot.
SPRITE_UP = 1.0  # cell heights above the cell
SPRITE_SLIDE = 6.0  # reference px the patch may slide each way


def sprite_patch(frame: np.ndarray, cell: Cell, slide: float = 0.0) -> np.ndarray:
    """The unit standing on ``cell``, at reference size (with ``slide`` px around it)."""
    left, top, right, bottom = layout.cell_box(cell)
    top -= SPRITE_UP * (bottom - top)
    return _bgr(_ref(frame, (left - slide, top - slide, right + slide, bottom + slide)))


def sprite_likeness(frame: np.ndarray, cell: Cell, other: np.ndarray, other_cell: Cell) -> float:
    """How much the unit on ``cell`` looks like what ``other`` shows on ``other_cell`` (-1..1)."""
    patch = sprite_patch(frame, cell)
    area = sprite_patch(other, other_cell, SPRITE_SLIDE)
    return float(template_match_response(area, patch, zero_mean=True).max())


# Room above a cell compared when trying a unit on it: a little, for a taller
# summon; more takes in the glow of the unit standing above (4K PC TURN 15:
# the robot's lead 11.1 with a whole cell above, 13.0 with 0.3).
TRY_ROOM_UP = 0.3


# A summon's countdown badge: a gold glow with a white digit and a white ▼
# floating above its cell (data/summon_badge.png, the 2K TURN 15 robot's, at
# 1080p; the digit changes, so it is masked out).  On the 2K screenshots it
# scored 0.63-1.0 over the robot and at most 0.51 elsewhere (0.43 on turns
# with no summon); its ▼ stands 35-36 px above the top of the robot's cell.
BADGE_MIN = 0.58
BADGE_DIGIT = (3, 24, 8, 21)  # rows, cols of the template left out
BADGE_TIP = (14, 30)  # the ▼ in the template (x, y)
BADGE_ABOVE = (30.0, 42.0)  # px from the ▼ down to the top of the summon's cell


@lru_cache(maxsize=None)
def _badge() -> tuple[np.ndarray, np.ndarray]:
    image = cv2.imdecode(np.fromfile(DATA / "summon_badge.png", dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(DATA / "summon_badge.png")
    mask = np.full(image.shape, 255, np.uint8)
    top, bottom, left, right = BADGE_DIGIT
    mask[top:bottom, left:right] = 0
    return image, mask


def badge_cells(frame: np.ndarray) -> list[tuple[float, Cell]]:
    """(score, cell) of each summon badge over the grid whose ▼ stands where a
    summon's would above a cell; best first."""
    template, mask = _badge()
    left = layout.CELL_X[0][0] - 20
    top = layout.CELL_Y[0][0] - 110
    box = (left, top, layout.CELL_X[-1][1] + 20, layout.CELL_Y[-1][1])
    area = _bgr(_ref(frame, box))
    scores = template_match_response(area, template, mask, zero_mean=True)
    scores = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)
    found = []
    for _ in range(4):
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score < BADGE_MIN:
            break
        scores[max(0, y - 10) : y + 10, max(0, x - 10) : x + 10] = 0
        tip_x, tip_y = left + x + BADGE_TIP[0], top + y + BADGE_TIP[1]
        col = next((c for c, (a, b) in enumerate(layout.CELL_X) if a <= tip_x <= b), None)
        low, high = BADGE_ABOVE
        row = next((r for r, (t, _) in enumerate(layout.CELL_Y) if low <= t - tip_y <= high), None)
        if col is not None and row is not None:
            found.append((float(score), (row, col)))
    return found


# The common summon (Leo 2026-10-01: nearly always the robot 魔法增幅器ET001):
# its own look, cut from labelled saves (data/robot/, the cell and half a cell
# above, 1080p).  Leave-one-session-out over 41 robot turns at 4K, 2K and
# 1080p: its cell came first every time, by 0.025 to 0.5 (median 0.24), so
# it only ever confirms the badge or stands in for one that can't be read.
ROBOT_NAME = "魔法增幅器ET001"
ROBOT_UP = 0.5
ROBOT_LEAD_ALONE = 0.10  # without a badge: its cell must lead this much


@lru_cache(maxsize=None)
def _robot_bank() -> tuple[np.ndarray, ...]:
    images = []
    for path in sorted((DATA / "robot").glob("*.png")):
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is not None:
            images.append(image)
    return tuple(images)


def robot_cells(frame: np.ndarray, cells: Sequence[Cell]) -> list[tuple[float, Cell]]:
    """(likeness, cell) of the robot to each of ``cells`` of ``frame``, best first."""
    bank = _robot_bank()
    if not bank:
        return []
    out = []
    for cell in cells:
        left, top, right, bottom = layout.cell_box(cell)
        box = (
            left - SPRITE_SLIDE,
            top - ROBOT_UP * (bottom - top) - SPRITE_SLIDE,
            right + SPRITE_SLIDE,
            bottom + SPRITE_SLIDE,
        )
        area = _bgr(_ref(frame, box))
        score = max(
            (
                float(template_match_response(area, sample, zero_mean=True).max())
                for sample in bank
                if sample.shape[0] <= area.shape[0] and sample.shape[1] <= area.shape[1]
            ),
            default=-1.0,
        )
        out.append((score, cell))
    return sorted(out, reverse=True)


def cell_differences(frame: np.ndarray, other: np.ndarray, cells: Sequence[Cell]) -> list[float]:
    """How much ``frame`` and ``other`` differ on each of ``cells`` and a little
    room above it (mean Lab difference after a light blur; 0 = the same).

    For trying a unit on each free cell (shots.ScreenshotTurns._try_cells):
    the game draws it with its overlaps and glow, so only where it stands
    differs; over the whole grid the skill animation drowns it out.
    """
    out = []
    for cell in cells:
        left, top, right, bottom = layout.cell_box(cell)
        box = (left, top - TRY_ROOM_UP * (bottom - top), right, bottom)
        here, there = (
            cv2.cvtColor(cv2.GaussianBlur(_bgr(_ref(image, box)), (5, 5), 0), cv2.COLOR_BGR2LAB)
            for image in (frame, other)
        )
        out.append(float(cv2.absdiff(here, there).mean()))
    return out


# --- text ---------------------------------------------------------------------------------


def _ocr_text(image: np.ndarray, ocr: Ocr) -> str:
    return "".join(str(text) for text in ocr(image))


def _text_image(frame: np.ndarray, box: layout.Box, height: int = 90) -> np.ndarray:
    """A text box scaled to its 4K height and padded: OCR drops lone glyphs
    (a one-character name like 鲁) in tight, small crops."""
    part = _bgr(layout.crop(frame, box))
    scale = height / max(1, part.shape[0])
    part = cv2.resize(
        part, (max(1, round(part.shape[1] * scale)), height), interpolation=cv2.INTER_CUBIC
    )
    pad = height // 2
    return cv2.copyMakeBorder(part, pad, pad, pad, pad, cv2.BORDER_REPLICATE)


def read_name(frame: np.ndarray, ocr: Ocr) -> str:
    """Raw text where the selected unit's name shows (snap it with names.snap_name)."""
    return _ocr_text(_text_image(frame, layout.NAME_BOX), ocr)


TEAMS = (1, 2, 3)


def read_team(frame: np.ndarray, ocr: Ocr) -> int | None:
    """TEAM1 / TEAM2 / TEAM3 (shown only while nobody is selected; Leo
    2026-10-01: some fights have a third team)."""
    text = _ocr_text(_text_image(frame, layout.TEAM_BOX, 68), ocr).upper().replace(" ", "")
    text = text.replace("I", "1").replace("L", "1").replace("Z", "2")
    if not text.startswith("TEAM") or len(text) != 5 or not text[4].isdigit():
        return None
    team = int(text[4])
    return team if team in TEAMS else None


def single_team(frame: np.ndarray, ocr: Ocr) -> bool:
    """A fight with no teams: the button bottom-left reads 「更换」, not 「更换队伍」,
    and no TEAMn shows top-left (塔洛斯战术教材, 2K 2026-10-22)."""
    text = _ocr_text(_text_image(frame, layout.CHANGE_LABEL_BOX, 68), ocr).replace(" ", "")
    return text == "更换"


# 爆发 flame on a list entry (layout.flame_box), read at 4 px per reference
# pixel.  On the 2K PC's 66 saved entries (2026-10-01) the best template
# scored 0.80+ on a flame and 0.66 at most without one; a flame's body is
# 236+ grey (no flame: about 190-200), and L3's inner flame 250+ where
# L1/L2 show the dark background (100 or less) through it.
_FLAME_SCALE = 4
FLAME_PRESENT_MIN, FLAME_ABSENT_MAX = 0.74, 0.70
FLAME_BODY_MIN, FLAME_INNER_L3_MIN = 220.0, 200.0
_FLAME_BODY = (slice(40, 70), slice(16, 30))  # left tongue, in template pixels
_FLAME_INNER = (slice(68, 88), slice(36, 52))  # the inner drop


def burst_flame(frame: np.ndarray, slot: int) -> int | None:
    """爆发 level the list entry's flame shows: 0 without one, None when unsure."""
    part = _bgr(layout.crop(frame, layout.flame_box(slot)))
    sides = (layout.FLAME_X[1] - layout.FLAME_X[0], layout.FLAME_DY[1] - layout.FLAME_DY[0])
    width, height = (round(side * _FLAME_SCALE) for side in sides)
    gray = to_gray(cv2.resize(part, (width, height), interpolation=cv2.INTER_CUBIC))
    gray = gray.astype(np.float32)
    best, level, at = -1.0, 0, (0, 0)
    for candidate in (1, 2, 3):
        template = _template(f"burst_flame_l{candidate}.png").astype(np.float32)
        _, score, _, where = cv2.minMaxLoc(template_match_response(gray, template, zero_mean=True))
        if score > best:
            best, level, at = score, candidate, where
    x, y = at
    window = gray[y : y + template.shape[0], x : x + template.shape[1]]
    body = float(window[_FLAME_BODY].mean())
    if best < FLAME_ABSENT_MAX or body < FLAME_BODY_MIN - 20:
        return 0
    if best < FLAME_PRESENT_MIN or body < FLAME_BODY_MIN:
        return None
    if float(window[_FLAME_INNER].mean()) >= FLAME_INNER_L3_MIN:
        return 3
    return 1 if level == 1 else 2


# The card whose icon is the saved list entry's skill icon: on the 2K PC
# (2026-10-01) the right card scored 0.73-0.91, the other 0.24-0.29, a card
# on cooldown included.  Icons are compared at 4 px per reference pixel.
_ICON_SCALES = (0.8, 0.9, 1.0, 1.1, 1.2, 1.3)
CARD_ICON_MIN, CARD_ICON_MARGIN = 0.6, 0.2
CARD_ICON_LOW_MIN, CARD_ICON_LOW_MARGIN = 0.45, 0.25
CARD_ICON_COLOUR_MIN, CARD_ICON_COLOUR_GAP = 0.4, 10.0


def _scaled(frame: np.ndarray, box: layout.Box) -> np.ndarray:
    part = _bgr(layout.crop(frame, box))
    size = (round((box[2] - box[0]) * _FLAME_SCALE), round((box[3] - box[1]) * _FLAME_SCALE))
    return cv2.resize(part, size, interpolation=cv2.INTER_CUBIC)


def card_with_icon(
    frame: np.ndarray, cards: int, saved: np.ndarray, saved_slot: int, lenient: bool = False
) -> int | None:
    """Card row (of an open card column) showing the saved entry's skill icon; None if unclear.

    ``lenient`` also takes a weaker but clear match: only for picking among a
    unit already known to be the entry's, whose portrait is checked after the
    pick.  Telling who an entry is stays strict (1080p TURN 31: lenient
    matching found entry 1's icon in three units' columns).
    """
    icon = _scaled(saved, layout.list_icon_box(saved_slot))
    want = _icon_colour(icon)
    scores = []
    colours: dict[int, float] = {}
    for row in range(layout.FIRST_SKILL_ROW, cards):
        region = _scaled(frame, layout.card_icon_box(row))
        best, spot = -1.0, None
        for scale in _ICON_SCALES:
            template = cv2.resize(icon, None, fx=scale, fy=scale)
            if template.shape[0] <= region.shape[0] and template.shape[1] <= region.shape[1]:
                match = template_match_response(region, template, zero_mean=True)
                _, value, _, (x, y) = cv2.minMaxLoc(match)
                if value > best:
                    h, w = template.shape[:2]
                    best, spot = float(value), region[y : y + h, x : x + w]
        scores.append((best, row))
        if spot is not None:
            colours[row] = float(np.linalg.norm(_icon_colour(spot) - want))
    scores.sort(reverse=True)
    if not scores:
        return None
    lead = scores[0][0] - scores[1][0] if len(scores) > 1 else scores[0][0]
    if scores[0][0] >= CARD_ICON_MIN and lead >= CARD_ICON_MARGIN:
        return scores[0][1]
    if not lenient:
        return None
    # Small icons (1080p live, a 4K screenshot): a weaker match still counts
    # when it stands well clear of every other card (1080p 2026-10-02, 海伦娜
    # TURN 27: 0.494 against 0.212 and 0.175, the saved card) ...
    if scores[0][0] >= CARD_ICON_LOW_MIN and lead >= CARD_ICON_LOW_MARGIN:
        return scores[0][1]
    # ... or when its colour picks the same card clearly (格兰希特 TURN 29:
    # shape 0.566 / 0.419, colour 28 against 45 for the next card).
    by_colour = sorted(colours, key=colours.__getitem__)
    if (
        scores[0][0] >= CARD_ICON_COLOUR_MIN
        and len(by_colour) > 1
        and by_colour[0] == scores[0][1]
        and colours[by_colour[1]] - colours[by_colour[0]] >= CARD_ICON_COLOUR_GAP
    ):
        return scores[0][1]
    return None


def _icon_colour(icon: np.ndarray) -> np.ndarray:
    """Mean Lab colour inside a round icon (its middle disc)."""
    h, w = icon.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    cv2.circle(mask, (w // 2, h // 2), max(1, min(h, w) * 3 // 8), 255, -1)
    return np.array(cv2.mean(cv2.cvtColor(icon, cv2.COLOR_BGR2LAB), mask=mask)[:3])


# A list entry's portrait is one of the unit's costumes, attack or not (the
# attack has no icon but still shows a costume), and each skill card of the
# unit's card column shows its costume's art at the same scale.  So an entry
# whose face matches nobody's in the live list (another session last used
# other costumes) is told by the face band found inside one of the unit's
# skill cards: 2K screenshot vs 4K cards, TURN 1 (2026-10-01): 0.96-0.99 on
# the unit's own card, 0.77 at most on any other card.
_COSTUME_SCALE = 3  # work px per reference px
_COSTUME_SIZES = (0.95, 1.0, 1.05)
COSTUME_SAME_MIN = 0.88
COSTUME_MARGIN = 0.1


def _costume_part(frame: np.ndarray, box: layout.Box) -> np.ndarray:
    part = _bgr(layout.crop(frame, box))
    size = (
        round((box[2] - box[0]) * _COSTUME_SCALE),
        round((box[3] - box[1]) * _COSTUME_SCALE),
    )
    shrink = part.shape[1] > size[0]
    return cv2.resize(part, size, interpolation=cv2.INTER_AREA if shrink else cv2.INTER_CUBIC)


def costume_card(
    frame: np.ndarray, cards: int, saved: np.ndarray, saved_slot: int
) -> tuple[float, int | None]:
    """The skill card of the card column open in ``frame`` whose costume art best
    matches the saved entry's portrait: (match -1..1, its row; None without cards)."""
    face = _costume_part(saved, layout.face_box(saved_slot))
    best, best_row = -1.0, None
    for row in range(layout.FIRST_SKILL_ROW, cards):
        art = _costume_part(frame, layout.card_box(row))
        for size in _COSTUME_SIZES:
            template = cv2.resize(face, None, fx=size, fy=size, interpolation=cv2.INTER_CUBIC)
            if template.shape[0] <= art.shape[0] and template.shape[1] <= art.shape[1]:
                match = float(template_match_response(art, template, zero_mean=True).max())
                if match > best:
                    best, best_row = match, row
    return best, best_row


def card_like(
    frame: np.ndarray, cards: int, saved: np.ndarray, saved_slot: int, lenient: bool = False
) -> int | None:
    """The skill card of the open card column that the saved entry shows: by its
    icon, else (two icons nearly the same) by its costume art, only when that
    is clear.  4K PC 2026-10-01, 尤里光盾 TURN 21: 克蕾西亚's eyepatch and
    headband costumes have near-identical blue icons."""
    row = card_with_icon(frame, cards, saved, saved_slot, lenient)
    if row is not None:
        return row
    score, art_row = costume_card(frame, cards, saved, saved_slot)
    return art_row if art_row is not None and score >= COSTUME_SAME_MIN else None


def costume_likeness(frame: np.ndarray, cards: int, saved: np.ndarray, saved_slot: int) -> float:
    """How well the saved entry's portrait matches one of the skill cards of the
    card column open in ``frame`` (best match, -1..1)."""
    return costume_card(frame, cards, saved, saved_slot)[0]


# Auto-skill icon, read at the small dot inside its ⟳ arrows: solid light blue
# while on, the hole showing the background while off.  The glow around the
# diamond is too faint to trust over a real fight's scenery (Leo 2026-10-01).
# On means the dot has its on colour and stands out from the ring of
# background just outside the icon, so blue scenery showing through the hole
# is not read as on.  Practice fight, 2K PC (BGR): dot 224,179,110 on (std 2),
# 34,25,26 off; ring 100,86,83 on, 35,27,28 off.
AUTO_SKILL_DOT = (42.0, 10.6, 2.5)  # x, y, radius in AUTO_SKILL_BOX (1080p px)
AUTO_SKILL_DIAMOND = (22.2, 30.4)  # diamond centre in AUTO_SKILL_BOX
AUTO_SKILL_RING = (27.0, 31.0)  # L1 distance from the diamond centre
AUTO_SKILL_ON_BGR = (224.0, 179.0, 110.0)
AUTO_SKILL_ON_DISTANCE_MAX = 45.0  # dot from the on colour
AUTO_SKILL_RING_DISTANCE_MIN = 40.0  # dot from the background ring


def _auto_skill_masks(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:height, 0:width]
    dot_x, dot_y, radius = AUTO_SKILL_DOT
    from_dot = np.hypot(xx - dot_x, yy - dot_y)
    l1 = np.abs(xx - AUTO_SKILL_DIAMOND[0]) + np.abs(yy - AUTO_SKILL_DIAMOND[1])
    ring = (l1 >= AUTO_SKILL_RING[0]) & (l1 <= AUTO_SKILL_RING[1]) & (from_dot > 9)
    return from_dot <= radius, ring


# The top-right icons once the planning screen has faded in: the diamond's
# white outline (98th percentile 244-255 on and off, 魔兽追踪者 and every
# 塔洛斯 stage, dark ones too) is grey (85) while the screen still fades in
# after a load (4K PC clone 2026-10-28), when the game also ignores taps.
ICONS_LIT_MIN = 200


def icons_lit(frame: np.ndarray) -> bool:
    """Whether the top-right icons are fully shown (not still fading in)."""
    part = cv2.cvtColor(_bgr(_ref(frame, layout.AUTO_SKILL_BOX)), cv2.COLOR_BGR2GRAY)
    return float(np.percentile(part, 98)) >= ICONS_LIT_MIN


def auto_skill_on(frame: np.ndarray) -> bool:
    """Whether the auto-skill icon (top right, the diamond) is on (blue dot)."""
    part = _bgr(_ref(frame, layout.AUTO_SKILL_BOX)).astype(np.float32)
    dot_mask, ring_mask = _auto_skill_masks(*part.shape[:2])
    dot = part[dot_mask].mean(axis=0)
    ring = part[ring_mask].mean(axis=0)
    on_colour = np.array(AUTO_SKILL_ON_BGR, dtype=np.float32)
    return (
        float(np.linalg.norm(dot - on_colour)) <= AUTO_SKILL_ON_DISTANCE_MAX
        and float(np.linalg.norm(dot - ring)) >= AUTO_SKILL_RING_DISTANCE_MIN
    )


# While on, the ⟳ arrows spin (Leo 2026-10-01): two captures ~0.1 s apart
# differ there by 9.8-11.8 (mean abs, 1080p px) against 0.0 while off, the
# background ring by 0.2-2.6 either way.  Scenery that moves raises both.
AUTO_SKILL_TURN_BOX: layout.Box = (1500.0, 22.0, 1525.0, 45.0)
AUTO_SKILL_TURN_MIN = 5.0  # ⟳ change minus ring change


def auto_skill_turning(first: np.ndarray, second: np.ndarray) -> bool:
    """Whether the auto-skill ⟳ spun between two captures (it only spins while on)."""
    turn = np.abs(
        _bgr(_ref(first, AUTO_SKILL_TURN_BOX)).astype(np.float32)
        - _bgr(_ref(second, AUTO_SKILL_TURN_BOX)).astype(np.float32)
    )
    part = np.abs(
        _bgr(_ref(first, layout.AUTO_SKILL_BOX)).astype(np.float32)
        - _bgr(_ref(second, layout.AUTO_SKILL_BOX)).astype(np.float32)
    )
    _, ring = _auto_skill_masks(*part.shape[:2])
    return float(turn.mean()) - float(part[ring].mean()) >= AUTO_SKILL_TURN_MIN


_BURST = re.compile(r"BURST(\d)")


def read_burst(frame: np.ndarray, ocr: Ocr) -> int | None:
    """The selected unit's 爆发 level ("BURST n" in the header); None when not shown."""
    text = _ocr_text(_text_image(frame, layout.BURST_BOX, 60), ocr).upper().replace(" ", "")
    match = _BURST.search(text)
    return int(match.group(1)) if match else None


def read_skill_name(frame: np.ndarray, ocr: Ocr) -> str:
    """The lit skill's name in the header ('' when none is shown)."""
    return _ocr_text(_text_image(frame, layout.SKILL_NAME_BOX, 60), ocr).strip()


_GROUPED = r"\d{1,3}(?:,\d{3})*"
_BOSS_HP = re.compile(rf"({_GROUPED})/({_GROUPED})")
BOSS_HP_HEIGHTS = (40, 60, 90)  # OCR text heights tried


def _parse_boss_hp(text: str) -> tuple[int, int] | None:
    text = re.sub(r"[^0-9,/]", "", text.replace(".", ","))
    match = _BOSS_HP.fullmatch(text)
    if match is None:
        return None
    left, full = (int(part.replace(",", "")) for part in match.groups())
    if full <= 0 or left > full:
        return None
    return left, full


def read_boss_hp(frame: np.ndarray, ocr: Ocr) -> tuple[int, int] | None:
    """(HP left, full HP) under BATTLE END, or None unless read cleanly.

    Only the white digits are kept (black on white): over the red HP bar of a
    real fight OCR split the number where the bar ends.  Read at three sizes;
    each read must keep its thousands commas in place (a dropped digit fails
    instead of giving a wrong damage), at least two must parse, all must agree.
    """
    reads = []
    for height in BOSS_HP_HEIGHTS:
        image = _text_image(frame, layout.BOSS_HP_END_BOX, height=height)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        ink = (hsv[..., 2] > 170) & (hsv[..., 1] < 90)
        image = cv2.cvtColor(np.where(ink, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
        hp = _parse_boss_hp(_ocr_text(image, ocr))
        if hp is not None:
            reads.append(hp)
    if len(reads) < 2 or len(set(reads)) != 1:
        return None
    return reads[0]


def read_dialog_title(frame: np.ndarray, ocr: Ocr) -> str:
    # At 2K the OCR reads 更换 as 更換 (繁體).
    title = _ocr_text(_bgr(layout.crop(frame, layout.TEAM_DIALOG_TITLE_BOX)), ocr)
    return title.replace("換", "换")


# TURN digits: the crop is scaled to its 4K size before thresholding (the
# reader was tuned there: 54/54 at 1080p/2K/4K).
_TURN_WORK_SIZE = (240, 140)


def _turn_glyphs(frame: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    crop = cv2.resize(
        _bgr(layout.crop(frame, layout.TURN_BOX)), _TURN_WORK_SIZE, interpolation=cv2.INTER_CUBIC
    )
    gray = cv2.normalize(to_gray(crop), None, 0, 255, cv2.NORM_MINMAX)
    white = (gray > 225).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    height, width = white.shape
    blobs = [
        tuple(int(value) for value in stats[index][:4])
        for index in range(1, count)
        if stats[index][4] > 15
        and stats[index][0] > 0
        and stats[index][1] > 0
        and stats[index][0] + stats[index][2] < width
        and stats[index][1] + stats[index][3] < height
    ]
    if not blobs:
        return white, []
    tall = max(blob[3] for blob in blobs)
    # the dot of "TURN." is the small, roughly square blob; the digits are the
    # tall blobs right of it.  Thin streaks along the pill's edge (1 px wide or
    # high) are no dot: at 1080p on the 4K PC's second monitor (2026-10-01) they
    # stood right of the digits and TURN 1 couldn't be read.
    dots = [
        blob
        for blob in blobs
        if blob[3] < tall * 0.3
        and blob[2] < tall * 0.3
        and min(blob[2], blob[3]) >= 2
        and 0.5 <= blob[2] / blob[3] <= 2.0
    ]
    if not dots:
        return white, []
    dot_x = max(dot[0] for dot in dots)
    digits = sorted(blob for blob in blobs if blob[0] > dot_x and blob[3] > tall * 0.8)
    return white, digits


def read_turn(frame: np.ndarray, ocr: Ocr) -> int | None:
    """N of "TURN. N" on the BATTLE pill, or None when unsure."""
    white, digits = _turn_glyphs(frame)
    if not digits or len(digits) > 2:
        return None
    narrow = [width < height * 0.35 for _, _, width, height in digits]
    if all(narrow):
        return int("1" * len(digits))
    # OCR the whole pill ("TURN. N") in black on white: single digits alone
    # are often dropped, with the word in front they are read reliably.
    pad = digits[0][3]
    image = np.where(white > 0, 0, 255).astype(np.uint8)
    image = cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    text = _ocr_text(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), ocr).upper().split(".")[-1]
    text = text.replace("O", "0").replace("S", "5").replace("B", "8").replace("Z", "2")
    wide = [char for char in text if char.isdigit() and char != "1"]
    if len(wide) != narrow.count(False):
        return None
    result, index = "", 0
    for is_narrow in narrow:
        if is_narrow:
            result += "1"
        else:
            result += wide[index]
            index += 1
    return int(result)
