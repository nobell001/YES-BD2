"""The teleport circle as the field itself draws it: a glowing blue-green
disc in a stone ring, seen from above at an angle (an ellipse about twice as
wide as tall).  Found by colour and shape so the character can walk onto it
with the movement keys when the area map's circle icon is hidden.

Player v0.3.8 1080p 2026-11-10, 每周跑图 第14章: the character stood a few
steps from the town's circle (in plain view) while its icon on the area map
was not found; Leo 「可以控制人物走去主地圖上的傳送陣嗎」.

Teal roofs and water share the colour, so the shape decides: an ellipse of
the circle's size, filled.  Only looked for on a confirmed field: a popup's
glow can pass (a 156x102 one did).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

REFERENCE_WIDTH = 1920
# OpenCV HSV, any one of: the pale blue-green glow (day maps, snow), and
# the darker green pattern in its blue rim as dim maps draw it (Leo's frames
# 2026-11-10 「傳送陣會隨著地圖光線而不同」: a dungeon lit yellow, hue 17-77,
# value 44-166; the rim closes the shape, its inside counts with it).
DISC_HSV_RANGES = (
    ((70, 40, 120), (105, 255, 255)),
    ((45, 70, 50), (118, 255, 255)),
)
# px at 1080p.  Nine frames (day, night, snow, dungeon, lava with a rope
# across, a dark subway, an office, two of a forest village): 178-206 wide,
# 96-128 tall, 1.54-1.85.
DISC_WIDTH_RANGE = (170, 240)
DISC_HEIGHT_RANGE = (90, 130)
DISC_ASPECT_RANGE = (1.5, 2.3)  # width / height
DISC_MIN_ELLIPSE_FILL = 0.80
DISC_MIN_SOLIDITY = 0.90
SAME_DISC_PIXELS = 40


@dataclass(frozen=True)
class FieldCircle:
    center: tuple[int, int]  # in the frame's own pixels
    size: tuple[int, int]
    fill: float


def find_field_circle(frame: np.ndarray | None) -> FieldCircle | None:
    """The one disc on ``frame`` shaped like the teleport circle, or None
    when there is none or more than one (no guess between two)."""
    if frame is None or frame.ndim != 3 or frame.shape[1] < 320:
        return None
    scale = frame.shape[1] / REFERENCE_WIDTH
    small = frame[..., :3]
    if abs(scale - 1) > 0.01:
        small = cv2.resize(
            small,
            (REFERENCE_WIDTH, round(frame.shape[0] / scale)),
            interpolation=cv2.INTER_AREA if scale > 1 else cv2.INTER_LINEAR,
        )
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    found: list[FieldCircle] = []
    for low, high in DISC_HSV_RANGES:
        mask = cv2.inRange(hsv, low, high)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if not DISC_WIDTH_RANGE[0] <= width <= DISC_WIDTH_RANGE[1]:
                continue
            if not DISC_HEIGHT_RANGE[0] <= height <= DISC_HEIGHT_RANGE[1]:
                continue
            if not DISC_ASPECT_RANGE[0] <= width / height <= DISC_ASPECT_RANGE[1]:
                continue
            area = cv2.contourArea(contour)
            fill = area / (np.pi / 4 * width * height)
            hull = cv2.contourArea(cv2.convexHull(contour))
            if not DISC_MIN_ELLIPSE_FILL <= fill <= 1.1 or hull <= 0:
                continue
            if area / hull < DISC_MIN_SOLIDITY:
                continue
            centre = (round((x + width / 2) * scale), round((y + height / 2) * scale))
            if any(
                abs(centre[0] - other.center[0]) < SAME_DISC_PIXELS * scale
                and abs(centre[1] - other.center[1]) < SAME_DISC_PIXELS * scale
                for other in found
            ):
                continue  # the same disc, seen by both colour ranges
            found.append(
                FieldCircle(centre, (round(width * scale), round(height * scale)), float(fill))
            )
    return found[0] if len(found) == 1 else None
