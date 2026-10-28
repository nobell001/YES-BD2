"""Classify freshly pulled equipment as junk (enhance to +7 and dismantle).

User rule (2026-09-26): keep only UR exclusive gear of 5★ characters; every
R and SR item, and UR exclusive gear of 3★/4★ characters, is junk.  Owner
stars come from assets/gear/exclusive_gear.json (built from the community
database browndust2-db.souseha.com: exclusive item -> character -> star).

Only gear carrying the new-item badge is considered.  Anything uncertain is
kept: rarity OCR and label colour must agree, a UR not found in the table is
kept, and equipped, locked or enhanced items are never touched.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

EXCLUSIVE_TABLE = Path(__file__).resolve().parents[2] / "assets" / "gear" / "exclusive_gear.json"

# OCR sometimes reads the gradient "U" of UR as J/I/L (seen live: "JR").
_UR_TOKENS = {"UR", "JR", "IR", "LR", "UF"}


@dataclass(frozen=True)
class GearItem:
    name: str
    rarity: str | None
    equipped: bool
    locked: bool
    enhanced: bool
    # The line above 「专用装备」 in the detail popup: the owner's star badge
    # and name ("☆艾玛"); None when the popup shows no such line.
    owner_line: str | None = None


def load_exclusive_stars(path: Path = EXCLUSIVE_TABLE) -> dict[str, int]:
    """Map exclusive item names (Simplified and Traditional) to owner stars."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    stars: dict[str, int] = {}
    for row in data["items"]:
        for key in ("zh_cn", "zh_tw"):
            if row.get(key):
                stars[normalize_name(row[key])] = int(row["star"])
    return stars


def load_exclusive_owners(path: Path = EXCLUSIVE_TABLE) -> dict[str, frozenset[str]]:
    """Map exclusive item names (Simplified and Traditional) to the owner's
    names in both scripts."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    owners: dict[str, frozenset[str]] = {}
    for row in data["items"]:
        names = frozenset(
            normalize_name(row[key]) for key in ("character_cn", "character_tw") if row.get(key)
        )
        for key in ("zh_cn", "zh_tw"):
            if row.get(key):
                owners[normalize_name(row[key])] = names
    return owners


def normalize_name(name: str) -> str:
    return re.sub(r"[\s·•.。…]", "", str(name))


def ocr_rarity(token: str) -> str | None:
    text = re.sub(r"[^A-Za-z0-9]", "", str(token)).upper()
    if text in _UR_TOKENS:
        return "UR"
    if text in {"SR", "5R"}:
        return "SR"
    if text == "R":
        return "R"
    if text == "N":
        return "N"
    return None


def colour_rarity(label_bgr: np.ndarray) -> str | None:
    """Rarity from the label colour: R blue, SR purple, UR rainbow gradient.

    Live 2026-09-26: R labels had one hue (median 106, spread ~5); UR labels
    spanned the spectrum (spread ~35).
    """
    if label_bgr is None or label_bgr.size == 0:
        return None
    hsv = cv2.cvtColor(label_bgr[:, :, :3], cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    hues = hue[(saturation > 90) & (value > 120)]
    if hues.size < 80:
        return None
    if float(hues.std()) > 20.0:
        return "UR"
    median = float(np.median(hues))
    if 90 <= median < 120:
        return "R"
    if 120 <= median <= 165:
        return "SR"
    return None


def label_hues(label_bgr: np.ndarray) -> np.ndarray:
    """Hues (OpenCV 0-179) of a rarity label's saturated, bright pixels.

    New items carry a yellow "!" badge right beside the label (60% of the
    coloured pixels of a live R label, 2026-09-27) and gold item art bleeds
    in too; no rarity letter is yellow, so yellow is left out.
    """
    if label_bgr is None or label_bgr.size == 0:
        return np.empty(0, np.uint8)
    hsv = cv2.cvtColor(label_bgr[:, :, :3], cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    hues = hue[(saturation > 90) & (value > 120)]
    return hues[(hues < 10) | (hues > 34)]


def hue_share(hues: np.ndarray, low: int, high: int) -> float:
    return float(((hues >= low) & (hues <= high)).mean()) if hues.size else 0.0


def only_blue(hues: np.ndarray, trace: float) -> bool:
    """The R label's cyan-to-blue alone: at most a trace of green (N and UR
    labels), purple (SR, UR) or red (UR).

    Live 2K 2026-09-30 (珍藏集 labels): R letters spanned hue 90-109, so the
    cyan end fell in the old 35-95 "green" band and every R was left unsure
    (full-res crops even looked UR); UR labels there were 20-23% green
    (35-84) and 40% purple, N labels are green.
    """
    return (
        hues.size > 0
        and hue_share(hues, 35, 84) <= trace
        and hue_share(hues, 125, 165) <= trace
        and float(((hues < 10) | (hues > 165)).mean()) <= trace
    )


def grid_label_rarity(label_bgr: np.ndarray) -> str | None:
    """R / SR / UR from a bag grid cell's rarity label, or None when unsure.

    The grid crop also catches the item art (a golden gauntlet made an SR
    label look like a rainbow UR to ``colour_rarity``).  UR letters always
    carry green-cyan (hue 35-95: 25-34% of the coloured pixels, live 4K
    2026-09-27); SR letters have none and are purple (72%); R letters are
    cyan to blue only.  Anything in between is left unsure so the detail
    gets opened.
    """

    hues = label_hues(label_bgr)
    if hues.size < 60:
        return None
    if only_blue(hues, GRID_R_TRACE_MAX) or blue_with_red_trace(hues):
        return "R"
    green = hue_share(hues, 35, 95)
    if green >= GRID_UR_GREEN_MIN:
        return "UR"
    if green > GRID_NO_GREEN_MAX:
        return None
    if hue_share(hues, 125, 165) >= GRID_MAIN_HUE_MIN:
        return "SR"
    if hue_share(hues, 96, 124) >= GRID_MAIN_HUE_MIN:
        return "R"
    return None


def blue_with_red_trace(hues: np.ndarray) -> bool:
    """Cyan-blue alone apart from a little red: no green (UR, N) and no
    purple (SR, UR) at all.  Live 2K 2026-10-22, a new R beside its 「!」 on a
    colour-distorted screen: 「绿0.00 青蓝0.94 紫0.00」, the 6 % red was the
    badge's orange edge, and the R was kept as 「认不出」."""
    return (
        hues.size >= GRID_CERTAIN_MIN_PIXELS
        and hue_share(hues, 35, 84) <= GRID_CERTAIN_GREEN_MAX
        and hue_share(hues, 125, 165) <= GRID_CERTAIN_GREEN_MAX
        and hue_share(hues, 85, 124) >= GRID_BLUE_WITH_RED_MIN
    )


GRID_BLUE_WITH_RED_MIN = 0.9
GRID_UR_GREEN_MIN = 0.15
GRID_NO_GREEN_MAX = 0.03
GRID_MAIN_HUE_MIN = 0.5
GRID_R_TRACE_MAX = 0.05
# "Certain" colour: enough to skip the label OCR when that cannot read the tiny
# italic letters (2K, 2026-09-30).  Every UR label had 20-45 % green.
GRID_CERTAIN_GREEN_MAX = 0.02
GRID_CERTAIN_MAIN_MIN = 0.85
GRID_CERTAIN_MIN_PIXELS = 80


def grid_label_colour_certain(label_bgr: np.ndarray, rarity: str) -> bool:
    """True when the label is unmistakably R (cyan-blue alone) or SR (purple,
    no green at all): every UR label carries green and purple."""

    if rarity not in ("R", "SR"):
        return False
    hues = label_hues(label_bgr)
    if hues.size < GRID_CERTAIN_MIN_PIXELS:
        return False
    if rarity == "R":
        return only_blue(hues, GRID_CERTAIN_GREEN_MAX) or blue_with_red_trace(hues)
    if hue_share(hues, 35, 95) > GRID_CERTAIN_GREEN_MAX:
        return False
    return hue_share(hues, 125, 165) >= GRID_CERTAIN_MAIN_MIN


def label_text_looks_ur(text: str) -> bool:
    """The label OCR shows a U (or its usual misreads before an R)."""
    letters = re.sub(r"[^A-Za-z]", "", str(text)).upper()
    return "U" in letters or letters.startswith(("JR", "IR", "LR"))


def agreed_rarity(token: str, label_bgr: np.ndarray) -> str | None:
    by_text = ocr_rarity(token)
    by_colour = colour_rarity(label_bgr)
    return by_text if by_text is not None and by_text == by_colour else None


def classify(
    item: GearItem,
    exclusive_stars: dict[str, int],
    *,
    dismantle_r_sr: bool = True,
    dismantle_low_star_ur: bool = True,
    exclusive_owners: dict[str, frozenset[str]] | None = None,
) -> tuple[bool, str]:
    """Return (is_junk, reason).

    With ``exclusive_owners``, a 3★/4★ UR exclusive is junk only when the
    popup's owner line also names its 3★/4★ owner: a 5★ exclusive shows a
    5★ name there, and an unread line keeps the item (Leo 2026-10-11
    「點開裝備是五星 一定不要拆」「寧願不拆也不要誤拆」).
    """
    if item.equipped:
        return False, "穿戴中"
    if item.locked:
        return False, "已上锁"
    if item.enhanced:
        return False, "已强化"
    if item.rarity is None:
        return False, "品质无法确认"
    if item.rarity in {"R", "SR"}:
        return (True, f"{item.rarity}") if dismantle_r_sr else (False, "未开启分解R/SR")
    if item.rarity == "UR":
        star = exclusive_stars.get(normalize_name(item.name))
        if star is None:
            return False, "UR 不在专用装备表中"
        if star >= 5:
            return False, "5★角色UR专用"
        if not dismantle_low_star_ur:
            return False, "未开启分解3★/4★专用UR"
        if exclusive_owners is not None:
            names = exclusive_owners.get(normalize_name(item.name), frozenset())
            line = normalize_name(item.owner_line or "")
            if not line:
                return False, "详情没读到专用角色"
            if not any(name in line for name in names):
                return False, f"详情的专用角色不是{star}★角色"
        return True, f"{star}★角色UR专用"
    return False, f"{item.rarity} 不在规则内"


EXCLUSIVE_TEXT = ("专用", "專用")


def classify_low_grade(
    item: GearItem,
    grade: str,
    exclusive_stars: dict[str, int],
    exclusive_owners: dict[str, frozenset[str]],
    popup_text: str = "",
    five_star_sr: bool = False,
) -> tuple[bool, str]:
    """R/SR shown by the bag filter, judged from its opened detail.

    R/SR come as character exclusives too, 5★ ones included (Leo's bag
    2026-10-11: 翼角头盔 SR of 格兰希特, 名剑飞燕 SR of 斑鸠).  An item is an
    exclusive when its name is on the table or the popup says 专用; such an
    item is junk only as a 3★/4★ exclusive whose owner line names that
    owner (Leo 「寧願不拆也不要誤拆」).  An SR that is no exclusive is kept.
    ``five_star_sr``: the player also lets 5★ characters' exclusives go (Leo
    2026-10-11 「讓玩家選擇要不要分解5星角色的SR」), still with the owner proven.
    """
    if item.equipped:
        return False, "穿戴中"
    if item.locked:
        return False, "已上锁"
    if item.enhanced:
        return False, "已强化"
    if item.rarity != grade:
        return False, f"详情稀有度{item.rarity or '?'}不是{grade}"
    name = normalize_name(item.name)
    star = exclusive_stars.get(name)
    exclusive = star is not None or any(word in str(popup_text) for word in EXCLUSIVE_TEXT)
    if not exclusive:
        # An SR is junk only as a proven 3★/4★ exclusive (Leo 2026-10-11 on
        # his 顶级英雄盔甲: 「他點開沒有寫 3星 專用裝備 … 你怎麼想把它強化拆了」).
        if grade == "SR":
            return False, "SR 不是3★/4★角色专用"
        return True, grade
    if star is None:
        return False, "专用装备不在表中"
    if star >= 5 and not five_star_sr:
        return False, "5★角色专用"
    line = normalize_name(item.owner_line or "")
    if not any(owner in line for owner in exclusive_owners.get(name, frozenset())):
        return False, f"详情没读到{star}★专用角色"
    return True, f"{grade} {star}★角色专用"


def occupied_cells(frame_1080, columns, rows, cap: int) -> list[tuple[int, int]]:
    """The leading cells that hold an item (an empty cell is flat: live 4K
    2026-10-11, empty std ≤ 4, items ≥ 22), at most ``cap``."""
    cells = []
    for cell in front_cells(columns, rows, cap):
        row, column = cell
        dx, dy, w, h = OCCUPIED_ICON_BOX
        x, y = columns[column] + dx, rows[row] + dy
        patch = frame_1080[max(0, y) : y + h, max(0, x) : x + w]
        if patch.size == 0:
            break
        grey = cv2.cvtColor(patch[:, :, :3], cv2.COLOR_BGR2GRAY)
        if float(grey.std()) < OCCUPIED_MIN_STD:
            break
        cells.append(cell)
    return cells


OCCUPIED_ICON_BOX = (-45, -40, 75, 85)
OCCUPIED_MIN_STD = 12.0


# The yellow "!" badge at a cell's top-right marks gear acquired since the bag
# was last opened (user, 2026-09-26): every freshly pulled item carries it
# when the daily automation opens the bag.  Offsets from the cell centre in
# 1920x1080 reference; live: 29% orange in the marked cell, 0% elsewhere.
NEW_MARKER_BOX = (42, -68, 28, 26)
NEW_MARKER_MIN_RATIO = 0.12


def new_marker_ratio(frame_1080: np.ndarray, centre: tuple[int, int]) -> float:
    dx, dy, w, h = NEW_MARKER_BOX
    x, y = centre[0] + dx, centre[1] + dy
    patch = frame_1080[max(0, y) : y + h, max(0, x) : x + w]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch[:, :, :3], cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    orange = (hue >= 10) & (hue <= 25) & (saturation >= 170) & (value >= 200)
    return float(orange.mean())


def leading_new_cells(
    frame_1080: np.ndarray,
    columns: tuple[int, ...],
    rows: tuple[int, ...],
    cap: int,
) -> list[tuple[int, int]]:
    """Cells marked new, read from the top-left in acquisition order.

    With the bag sorted newest first the new items are contiguous at the
    top; stop at the first unmarked cell so nothing older is ever included.
    """
    cells: list[tuple[int, int]] = []
    for row, cy in enumerate(rows):
        for column, cx in enumerate(columns):
            if len(cells) >= cap:
                return cells
            if new_marker_ratio(frame_1080, (cx, cy)) < NEW_MARKER_MIN_RATIO:
                return cells
            cells.append((row, column))
    return cells


# Top-left of a bag cell: a gear not worn shows its slot icon (a light glyph
# on a dark slate rounded square); a worn one shows the wearer's round
# portrait with a light ring (Leo's 4K bag, 2026-10-11, R/SR/UR filters).
# Offsets from the cell centre in 1920x1080 reference.  Measured on the PNGs
# and their q90 JPEG fixtures: slot icons slate 0.73-0.82 with ring <= 0.03;
# portraits slate <= 0.49 (ring 0.17-0.81); empty cells slate <= 0.15.  The
# slot square is V≈55 S≈50, so the band leaves room for JPEG and dim screens.
SLOT_ICON_BOX = (-60, -58, 34, 34)
SLOT_ICON_MIN_SLATE = 0.60
SLOT_ICON_MAX_RING = 0.10


def slot_icon_scores(frame_1080: np.ndarray, centre: tuple[int, int]) -> tuple[float, float]:
    """(slate share, light-ring share) of a cell's top-left icon."""
    dx, dy, w, h = SLOT_ICON_BOX
    x, y = centre[0] + dx, centre[1] + dy
    patch = frame_1080[max(0, y) : y + h, max(0, x) : x + w]
    if patch.size == 0:
        return 0.0, 1.0
    hsv = cv2.cvtColor(np.ascontiguousarray(patch[:, :, :3]), cv2.COLOR_BGR2HSV).astype(int)
    value, saturation = hsv[..., 2], hsv[..., 1]
    slate = float(((value >= 35) & (value <= 80) & (saturation <= 80)).mean())
    rows, cols = value.shape
    yy, xx = np.mgrid[:rows, :cols]
    distance = np.hypot(yy - rows / 2, xx - cols / 2)
    ring = (distance >= 14) & (distance <= 17)
    light = (value >= 120) & (saturation <= 50)
    return slate, float(light[ring].mean()) if ring.any() else 1.0


# The enhance / refine badge right of the cell centre: white digits in a
# diamond (「15」) or a plain 「+7」.  The grid OCR missed many of the diamonds
# (Leo's 4K bag 2026-10-11), so a fully enhanced 顶级英雄盔甲 (15) was taken
# as +0; the white pixels there are looked at as well.
# White item art can reach more than a small 「+7」 (0.044): the silver band of
# an R ring (Leo's 冰雪红宝石, 4K 2026-10-28) read 0.063 and the bag kept the
# unenhanced ring as 已强化.  So the share alone never decides: a cell counts
# as badged when one white blob there is shaped like a digit: 12-22 px tall,
# at most 13 wide, in the right part of the spot where the number sits
# (「15」 strokes at x 28-44, 「+7」's 7 at 42-52; ring band x 9-25, h 10; a
# sword hilt x 15-33, 18 wide).  161 cells of Leo's 4K bags plus his two rings
# on the live bag: no miss either way, also blurred, at 2K and darker.
BADGE_GLYPH_BOX = (5, -15, 65, 60)
BADGE_GLYPH_HEIGHT = (12, 22)
BADGE_GLYPH_WIDTH = (2, 13)
BADGE_GLYPH_X = (24, 60)
BADGE_GLYPH_Y = (-5, 35)


def badge_glyph_found(frame_1080: np.ndarray, centre: tuple[int, int]) -> bool:
    """A white digit-shaped blob in the badge spot (offsets from ``centre``)."""
    dx, dy, width, height = BADGE_GLYPH_BOX
    x0, y0 = centre[0] + dx, centre[1] + dy
    patch = frame_1080[max(0, y0) : y0 + height, max(0, x0) : x0 + width, :3]
    if patch.size == 0:
        return True
    hsv = cv2.cvtColor(np.ascontiguousarray(patch), cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 200)).astype(np.uint8)
    count, _labels, stats, _centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
    left = max(0, y0) - centre[1], max(0, x0) - centre[0]
    for x, y, w, h, _area in stats[1:count]:
        x, y = x + left[1], y + left[0]
        if (
            BADGE_GLYPH_HEIGHT[0] <= h <= BADGE_GLYPH_HEIGHT[1]
            and BADGE_GLYPH_WIDTH[0] <= w <= BADGE_GLYPH_WIDTH[1]
            and x >= BADGE_GLYPH_X[0]
            and x + w <= BADGE_GLYPH_X[1]
            and y >= BADGE_GLYPH_Y[0]
            and y + h <= BADGE_GLYPH_Y[1]
        ):
            return True
    return False


def badge_shown(frame_1080: np.ndarray, centre: tuple[int, int]) -> bool:
    """The cell shows an enhance or refine number (or anything unsure)."""
    return badge_glyph_found(frame_1080, centre)


def slot_icon_shown(frame_1080: np.ndarray, centre: tuple[int, int]) -> bool:
    """True only for the not-worn slot icon; a portrait or anything unsure is False."""
    slate, ring = slot_icon_scores(frame_1080, centre)
    return slate >= SLOT_ICON_MIN_SLATE and ring <= SLOT_ICON_MAX_RING


def front_cells(
    columns: tuple[int, ...], rows: tuple[int, ...], cap: int
) -> list[tuple[int, int]]:
    """The first ``cap`` cells, row by row: with the bag sorted newest first
    these are the latest items, marked new or not (Leo 2026-10-11)."""
    cells = [(row, column) for row in range(len(rows)) for column in range(len(columns))]
    return cells[: max(0, cap)]


# The detail popup's ✕ (1080 reference): x is fixed, y moves with the popup's
# height.  The popup is centred, so an item with 基本能力 and 属性 rows shows a
# taller popup whose ✕ sits higher (player 2026-10-12, 猎人之弓: y 196 against
# 首席勋章's 325) and whose bottom buttons sit lower by the same amount.
POPUP_CLOSE_REFERENCE_Y = 325
POPUP_CLOSE_SEARCH = (1395, 40, 50, 560)  # x, y, width, height
POPUP_CLOSE_WHITE = 190
POPUP_CLOSE_SIDE = (14, 32)
POPUP_CLOSE_AREA = (60, 320)


def popup_close_point(frame_1080: np.ndarray) -> tuple[int, int] | None:
    """Centre of the detail popup's white ✕, or None when it is not found."""
    x0, y0, width, height = POPUP_CLOSE_SEARCH
    strip = frame_1080[y0 : y0 + height, x0 : x0 + width, :3]
    if strip.size == 0:
        return None
    mask = (strip.min(axis=2) > POPUP_CLOSE_WHITE).astype(np.uint8)
    count, _labels, stats, _centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
    low, high = POPUP_CLOSE_SIDE
    found = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if not (low <= w <= high and low <= h <= high):
            continue
        if not (POPUP_CLOSE_AREA[0] <= area <= POPUP_CLOSE_AREA[1]):
            continue
        # A cross fills well under half of its box; a white blob or text block
        # does not.
        if area > 0.6 * w * h:
            continue
        found.append((y0 + y + h // 2, x0 + x + w // 2))
    if not found:
        return None
    y, x = min(found)
    return x, y


def popup_shift(frame_1080: np.ndarray) -> int:
    """How far the popup's top moved from the reference (negative = up)."""
    point = popup_close_point(frame_1080)
    return 0 if point is None else point[1] - POPUP_CLOSE_REFERENCE_Y

