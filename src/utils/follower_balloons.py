"""The "!" balloons over the heads of the 派遣 crowd in a field.

Every game day the characters back from 派遣 walk to the player with a beige
speech balloon holding a dark "!" over each head (Leo's 1080p 镜中之战 frame,
2026-11-09).  The field F button only shows its own "!" once they stand next
to the player, so the balloons tell what the F button cannot: the crowd is
on screen but still walking over → keep waiting for it.  They only add
waiting: a look never gets shorter because no balloon was seen (Leo
2026-11-06 「額外的線索只能幫忙，不能限制」).

After the press the balloons go with the crowd, a second sign beside the F
icon going away (Leo 2026-11-05: every check two ways).

Found by colour and shape, not a template: balloons pile up and cover each
other in a crowd, so each "!" bar is counted, with beige on both sides of it
and its dot under it.  The talk "…" balloons of the bar's NPCs have dots
only, no bar.  All numbers are 1920x1080 reference pixels.
"""

from __future__ import annotations

import cv2
import numpy as np

REFERENCE = (1920, 1080)
# Leo's frame: balloon fill H 13-16, S 43-57, V 184-195 (OpenCV HSV).  Wide
# enough for HDR / 鲜艳度 shifts, narrow enough to leave skin and gold out.
FILL_HUE = (6, 28)
FILL_SAT = (18, 120)
FILL_VAL_MIN = 120
# The "!" bar on Leo's frame: about 5x15 px at 1080p.
BAR_HEIGHT = (9, 26)
BAR_WIDTH = (2, 10)
BAR_MIN_ASPECT = 2.0
DARK_VAL_MAX = 110
SIDE_GAP = 4
SIDE_REACH = 6
MIN_SIDE_FILL = 0.6
# The balloon is wide and smooth around its bar; parchment maps and wood
# grain are beige too but streaked (quick-hunt map, 2026-10-11 frames).
WIDE_REACH = 14
MIN_WIDE_FILL = 0.75
MAX_FILL_STD = 45.0
MIN_BAR_CONTRAST = 80.0


def _reference(frame: np.ndarray) -> np.ndarray:
    image = frame[:, :, :3]
    if (image.shape[1], image.shape[0]) != REFERENCE:
        image = cv2.resize(image, REFERENCE, interpolation=cv2.INTER_AREA)
    return image


def _fill_mask(hsv: np.ndarray) -> np.ndarray:
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (
        (hue >= FILL_HUE[0]) & (hue <= FILL_HUE[1])
        & (sat >= FILL_SAT[0]) & (sat <= FILL_SAT[1])
        & (val >= FILL_VAL_MIN)
    )


def _side_fill(fill: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> float:
    height, width = fill.shape
    x0, x1 = max(0, x0), min(width, x1)
    y0, y1 = max(0, y0), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float(fill[y0:y1, x0:x1].mean())


def _has_dot_below(dark: np.ndarray, x: int, w: int, bottom: int, bar_height: int) -> bool:
    height, width = dark.shape
    y0 = bottom + 1
    y1 = min(height, bottom + max(4, bar_height // 2) + 3)
    x0, x1 = max(0, x - 2), min(width, x + w + 2)
    return y1 > y0 and bool(dark[y0:y1, x0:x1].any())


def _smooth_balloon(val: np.ndarray, fill: np.ndarray, x: int, y: int, w: int, h: int) -> bool:
    height, width = val.shape
    y0, y1 = max(0, y), min(height, y + h)
    windows = []
    for x0, x1 in (
        (x - SIDE_GAP - WIDE_REACH, x - SIDE_GAP),
        (x + w + SIDE_GAP, x + w + SIDE_GAP + WIDE_REACH),
    ):
        x0, x1 = max(0, x0), min(width, x1)
        if x1 <= x0:
            return False
        windows.append((x0, x1))
    sides = np.concatenate([val[y0:y1, a:b].ravel() for a, b in windows]).astype(np.float32)
    side_fill = np.concatenate([fill[y0:y1, a:b].ravel() for a, b in windows])
    if side_fill.mean() < MIN_WIDE_FILL or sides.std() > MAX_FILL_STD:
        return False
    bar = val[y0:y1, max(0, x):min(width, x + w)].astype(np.float32)
    return float(np.median(sides) - bar.min()) >= MIN_BAR_CONTRAST


def find_balloons(frame: np.ndarray | None) -> list[tuple[float, float]]:
    """Centres (0-1 of the frame) of the "!" balloons seen in ``frame``."""
    if frame is None or getattr(frame, "ndim", 0) != 3 or frame.size == 0:
        return []
    image = _reference(frame)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    fill = _fill_mask(hsv)
    dark = (hsv[:, :, 2] <= DARK_VAL_MAX).astype(np.uint8)
    count, _labels, stats, _centres = cv2.connectedComponentsWithStats(dark, connectivity=8)
    found: list[tuple[float, float]] = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if not (BAR_HEIGHT[0] <= h <= BAR_HEIGHT[1] and BAR_WIDTH[0] <= w <= BAR_WIDTH[1]):
            continue
        if h / max(1, w) < BAR_MIN_ASPECT or area < 0.45 * w * h:
            continue
        left = _side_fill(fill, x - SIDE_GAP - SIDE_REACH, x - SIDE_GAP, y, y + h)
        right = _side_fill(fill, x + w + SIDE_GAP, x + w + SIDE_GAP + SIDE_REACH, y, y + h)
        above = _side_fill(fill, x - 1, x + w + 1, y - SIDE_GAP - 3, y - 1)
        if min(left, right) < MIN_SIDE_FILL or above < MIN_SIDE_FILL * 0.5:
            continue
        if not _smooth_balloon(hsv[:, :, 2], fill, x, y, w, h):
            continue
        # The bar ends above its dot; the dot is dark too but its own part.
        if not _has_dot_below(dark, x, w, y + h, h):
            continue
        found.append(((x + w / 2) / REFERENCE[0], (y + h / 2) / REFERENCE[1]))
    return found


# One balloon alone can be a lookalike (a bright pool edge, a parchment
# streak: 1 hit on 10 of 360 saved frames); a crowd shows several (Leo's hub
# 7, the square 7, 救赎之塔 spawn 8).
MIN_CROWD = 2


def crowd_seen(frame: np.ndarray | None) -> bool:
    """Several "!" balloons on screen: the 派遣 crowd is in this field."""
    return len(find_balloons(frame)) >= MIN_CROWD
