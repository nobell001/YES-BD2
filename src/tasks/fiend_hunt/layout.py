"""Where things are on the 魔兽追踪者 planning screen.

Every position is in 1920x1080 reference pixels (measured on the 4K PC,
2026-09-30, and halved) and used as a ratio of the client size, so the
same numbers serve 1080p, 2K and 4K.  Boxes are (left, top, right, bottom).

The grid is read in the top-down view (切换视角); cells are (row, col) as
in record.py: row 0 = top, col 3 = the front column next to the boss.
"""

from __future__ import annotations

import numpy as np

from src.tasks.fiend_hunt.planner import COLS, ROWS, Cell
from src.utils.calibration import FHD_1080

REF_W, REF_H = FHD_1080.size

Point = tuple[float, float]
Box = tuple[float, float, float, float]

# Left list: slot centres from the top (a team with a summon has 6 slots).
SLOT_Y = (157.5, 245.0, 332.5, 420.0, 507.5, 595.0)
MAX_SLOTS = len(SLOT_Y)
SLOT_HALF_H = 35.0
PORTRAIT_X = (95.0, 215.0)  # portrait left/right
PORTRAIT_TAP_X = 155.0  # tap: select that unit
SWAP_X = 243.5  # the slot's ⇅ button: drag onto another ⇅ to swap; tap clears a selection
# A list entry shows the unit's card: the portrait is a costume, and a skill
# card adds a round skill icon top-right (an attack has none).  Compared:
# the face band, clear of the slot number, buff icons (above), HP (below)
# and the arc that sweeps out from ⇅ for about 0.1 s after a tap there, and
# whether the icon's round edge is there (its inside and ring may glow).
FACE_X = (110.0, 160.0)
FACE_DY = (-15.0, 12.0)  # from the slot's SLOT_Y
ICON_CENTRE = (202.0, -20.0)  # x, and y from SLOT_Y
ICON_RING = (12.5, 18.5)  # radii searched for the icon's round edge

# Card column right of the list while a unit is selected: one card per
# row, lined up with the list slots.  Row 0 is the normal attack (titled
# 最前方 or 越过), row 1 击退 (its own action: knocks the target back),
# rows 2.. one skill card per costume (1-4 of them).  The chosen card is
# lit in the unit's element colour.
CARD_X = (276.0, 463.0)  # left/right edge
CARD_TOP, CARD_BOTTOM = -37.0, 39.5  # from the row's SLOT_Y
CARD_TAP_X = 370.0
ATTACK_ROW, KNOCKBACK_ROW, FIRST_SKILL_ROW = 0, 1, 2
# A lit skill card has ◀ ▶ at its left and right edge: the 爆发 level
# (L1-L3), shown as "BURST n" in the header line above the battlefield
# ("◆5 ◷3 预约 BURST 2"; 2K PC 2026-10-01).
# Each skill card shows its skill's round icon top-left, the same icon the
# list entry shows while that skill is up (2K PC 2026-10-01).
CARD_ICON_X = (278.0, 330.0)
CARD_ICON_DY = (-42.0, 2.0)  # from the row's SLOT_Y
LIST_ICON_R = 10.5  # inside the list icon's ring, round ICON_CENTRE
BURST_DOWN_X, BURST_UP_X = 288.0, 443.0
# 「先发制人」 beside a skill card (塔洛斯 stage 7, 格兰希特, 2K PC 2026-10-28):
# its word right of the card, a switch under it, orange when on (5 SP).
PREEMPT_TEXT_X = (445.0, 560.0)
PREEMPT_TEXT_DY = (-30.0, 4.0)  # from the row's SLOT_Y
PREEMPT_SWITCH = (499.0, 15.0)  # x, and y from SLOT_Y
PREEMPT_SWITCH_HALF = (24.0, 10.0)
BURST_BOX: Box = (560.0, 48.0, 1100.0, 84.0)
# The lit skill's name, the header line above BURST_BOX (Leo 2026-10-06:
# "特级三重箭矢 +5", 4K PC); the costume list knows each costume's skill name.
SKILL_NAME_BOX: Box = (600.0, 16.0, 1100.0, 50.0)
# The list entry shows the level too: a white flame bottom-right, small
# for L1, two tongues for L2, a white inner flame for L3, none without.
FLAME_X = (186.0, 222.0)
FLAME_DY = (0.0, 40.0)  # from the slot's SLOT_Y

# Name of the selected unit, top-left (replaces "TEAM1" and the buff icons).
NAME_BOX: Box = (112.0, 20.0, 350.0, 65.0)  # right of the element icon
# "TEAM1"/"TEAM2" under the buff icons when nobody is selected.
TEAM_BOX: Box = (88.0, 82.0, 190.0, 116.0)

# Top-down grid: cell brackets (4K 962-1551 x 865-1295, halved).
CELL_X = ((481.0, 549.0), (556.0, 624.5), (631.5, 700.0), (707.0, 775.5))
CELL_Y = ((432.5, 495.0), (507.0, 571.5), (582.5, 647.5))
CELL_PRESS_DY = 10.0  # press a little below the centre, on the unit's body
# The floor under the grid: light grey in the top-down view, near black isometric.
FLOOR_BOX: Box = (350.0, 750.0, 750.0, 900.0)
# Floor grey (FLOOR_BOX) top-down: 119 in the practice room, 98 in the cave of
# the real fight (purple-tinted grid, 2K PC 2026-10-01); isometric 24-56.  The
# top-down floor is a grey grid (saturation 25-28), a lit scene is coloured.
TOPDOWN_FLOOR_MIN = 80.0
TOPDOWN_FLOOR_SAT_MAX = 60.0
# Grid and boss area compared with data/topdown_view.png (the real fight's
# cave, top-down) to see whether the camera was dragged: a drag that starts
# on bare floor pans the view, and the cells' fixed points then miss
# (2K PC 2026-10-01, T3: 22 px left, 75 px up).  Toggling the view twice
# puts the camera back.
VIEW_BOX: Box = (350.0, 150.0, 1450.0, 950.0)
VIEW_SHIFT_MAX = 6.0  # 1080p px
# A smaller shift is only logged, to see when a drag starts panning the view.
VIEW_SHIFT_NOTE = 2.0

# Top right, fourth icon from the right: auto skills (the costume order puts
# up skills and bursts), blue while on, white while off.  Off, every unit
# starts on attack (2K PC 2026-10-01, Leo).
AUTO_SKILL: Point = (1497.5, 50.0)
AUTO_SKILL_BOX: Box = (1470.0, 22.0, 1525.0, 78.0)

# Bottom row.
CHANGE_TEAM: Point = (124.0, 978.0)  # 更换队伍
CHANGE_LABEL_BOX: Box = (70.0, 990.0, 175.0, 1022.0)  # its label; 「更换」 alone with no teams
VIEW_TOGGLE: Point = (1520.0, 980.0)  # 切换视角
BATTLE: Point = (1772.5, 985.0)
TURN_BOX: Box = (1620.0, 950.0, 1740.0, 1020.0)  # "TURN. 13"
BATTLE_WORD_BOX: Box = (1728.0, 958.0, 1818.0, 1012.0)  # the word BATTLE

# 更换队伍 confirmation dialog.
TEAM_DIALOG_TITLE_BOX: Box = (840.0, 270.0, 1080.0, 330.0)
TEAM_DIALOG_CONFIRM: Point = (1072.0, 803.0)

# BATTLE END screen, top right.
BATTLE_END_BOX: Box = (1370.0, 40.0, 1600.0, 108.0)
# Under BATTLE END: the fiend's HP left / its full HP ("49,399,316,779/64,500,000,000").
BOSS_HP_END_BOX: Box = (1370.0, 222.0, 1790.0, 260.0)

assert len(CELL_X) == COLS and len(CELL_Y) == ROWS


def to_client(point: Point, width: int, height: int) -> tuple[int, int]:
    return round(point[0] * width / REF_W), round(point[1] * height / REF_H)


def crop(frame: np.ndarray, box: Box) -> np.ndarray:
    """The part of ``frame`` (any size) inside a reference box."""
    height, width = frame.shape[:2]
    left, top, right, bottom = box
    return frame[
        round(top * height / REF_H) : round(bottom * height / REF_H),
        round(left * width / REF_W) : round(right * width / REF_W),
    ]


def slot_box(slot: int) -> Box:
    y = SLOT_Y[slot]
    return PORTRAIT_X[0], y - SLOT_HALF_H, PORTRAIT_X[1], y + SLOT_HALF_H


def slot_tap(slot: int) -> Point:
    return PORTRAIT_TAP_X, SLOT_Y[slot]


def slot_swap(slot: int) -> Point:
    return SWAP_X, SLOT_Y[slot]


def face_box(slot: int) -> Box:
    y = SLOT_Y[slot]
    return FACE_X[0], y + FACE_DY[0], FACE_X[1], y + FACE_DY[1]


def icon_box(slot: int) -> Box:
    """Square round the skill icon, reaching a little past its ring."""
    x, dy = ICON_CENTRE
    y, reach = SLOT_Y[slot] + dy, ICON_RING[1] + 3.5
    return x - reach, y - reach, x + reach, y + reach


def card_box(row: int) -> Box:
    y = SLOT_Y[row]
    return CARD_X[0], y + CARD_TOP, CARD_X[1], y + CARD_BOTTOM


def card_tap(row: int) -> Point:
    return CARD_TAP_X, SLOT_Y[row]


def preempt_text_box(row: int) -> Box:
    y = SLOT_Y[row]
    return PREEMPT_TEXT_X[0], y + PREEMPT_TEXT_DY[0], PREEMPT_TEXT_X[1], y + PREEMPT_TEXT_DY[1]


def preempt_switch(row: int) -> Point:
    return PREEMPT_SWITCH[0], SLOT_Y[row] + PREEMPT_SWITCH[1]


def preempt_switch_box(row: int) -> Box:
    x, y = preempt_switch(row)
    half_x, half_y = PREEMPT_SWITCH_HALF
    return x - half_x, y - half_y, x + half_x, y + half_y


def card_icon_box(row: int) -> Box:
    y = SLOT_Y[row]
    return CARD_ICON_X[0], y + CARD_ICON_DY[0], CARD_ICON_X[1], y + CARD_ICON_DY[1]


def list_icon_box(slot: int) -> Box:
    x, dy = ICON_CENTRE
    y = SLOT_Y[slot] + dy
    return x - LIST_ICON_R, y - LIST_ICON_R, x + LIST_ICON_R, y + LIST_ICON_R


def flame_box(slot: int) -> Box:
    y = SLOT_Y[slot]
    return FLAME_X[0], y + FLAME_DY[0], FLAME_X[1], y + FLAME_DY[1]


def burst_tap(row: int, up: bool) -> Point:
    """▶ (up) or ◀ on the lit skill card in row ``row``."""
    return BURST_UP_X if up else BURST_DOWN_X, SLOT_Y[row]


def cell_box(cell: Cell) -> Box:
    row, col = cell
    (left, right), (top, bottom) = CELL_X[col], CELL_Y[row]
    return left, top, right, bottom


def cell_press(cell: Cell) -> Point:
    left, top, right, bottom = cell_box(cell)
    return (left + right) / 2, (top + bottom) / 2 + CELL_PRESS_DY
