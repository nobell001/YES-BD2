"""Locate the PVP stage and plan WASD steps onto its centre.

For players who move with WASD instead of mouse clicks (click-to-move off),
the mirror-battle stage must be reached by walking.  The camera keeps the
player character at the screen centre, so the red stage's position on screen
is the offset still to walk.  Calibrated 2026-09-26 on the live client
(1920x1080 reference): the pre-battle screen opens once the character stands
on the stage centre, which is then about (-35, +25) px from the sprite at
(955, 500); S moved the view ~390 px/s vertically, A/D ~550 px/s (650 on
11-05, see PIXELS_PER_SECOND).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Where the stage centre sits on screen when the character stands on it.
STAGE_TARGET = (925, 535)
# The stage is told from the other red things by its shape, not by where it
# is: a flat ellipse about 190-270 x 100-150 px (1080p).  The bar's red
# carpet is a far bigger block (about 450-550 x 280-330); the crossed-swords
# marker, stools and HUD badges are far smaller or not flat.  A search area
# around the character used to keep those out, but it also kept out a stage
# that stood farther away: the carpet was then the largest red patch inside
# and the walk headed for it (screen library b3f20b3bac46: stage at
# (319, 683), outside the old area; 4K PC clone 11-05: W 0.6 s put the
# stage at (754, 962)).  Measured on six PVP hall frames (1080p/2K/4K):
# stage area 13 300-25 000, width 185-270, height 103-147, width/height
# 1.65-2.11; carpet area 57 000-74 000, 444-547 x 279-331.
STAGE_AREA = (6000, 40000)
STAGE_MAX_SIZE = (400, 220)
STAGE_ASPECT = (1.35, 2.8)
ARRIVED_DISTANCE = 30.0
# A red patch that does not come this much nearer in this many steps is not
# the stage (a cut-off piece of the bar carpet, clone 11-05 W 1.2 s); the
# game's 「定位修正」 is pressed at most this often in one walk.
STAGE_PROGRESS_PIXELS = 20.0
STAGE_NO_PROGRESS_STEPS = 4
STAGE_RESETS_PER_WALK = 2
# Nothing red right after a step that should have ended this near the
# target: the line-up stands on the stage and hides it.
STAGE_HIDDEN_NEAR = 80.0
# A/D measured again on the 4K PC 1080p clone 2026-11-05: about 650 px/s
# (550 overshot, the walk went left and right 7 times).
PIXELS_PER_SECOND = {"x": 650.0, "y": 390.0}
MIN_STEP_SECONDS = 0.06
MAX_STEP_SECONDS = 0.35


@dataclass(frozen=True)
class WalkStep:
    key: str
    seconds: float


def stage_shaped(area: int, width: int, height: int) -> bool:
    """A red patch the size and shape of the stage's top."""
    if not STAGE_AREA[0] <= area <= STAGE_AREA[1]:
        return False
    if width > STAGE_MAX_SIZE[0] or height > STAGE_MAX_SIZE[1] or height <= 0:
        return False
    return STAGE_ASPECT[0] <= width / height <= STAGE_ASPECT[1]


def find_stage(frame_1080: np.ndarray) -> tuple[int, int] | None:
    """Centre of the red stage top in a 1920x1080 BGR frame, or None."""
    hsv = cv2.cvtColor(frame_1080[:, :, :3], cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    red = ((hue <= 8) | (hue >= 168)) & (saturation >= 120) & (value >= 50)
    mask = red.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    best = None
    for index in range(1, count):
        area = int(stats[index][cv2.CC_STAT_AREA])
        width = int(stats[index][cv2.CC_STAT_WIDTH])
        height = int(stats[index][cv2.CC_STAT_HEIGHT])
        if not stage_shaped(area, width, height):
            continue
        if best is None or area > best[0]:
            best = (area, int(centroids[index][0]), int(centroids[index][1]))
    return None if best is None else (best[1], best[2])


def plan_step(stage: tuple[int, int], target: tuple[int, int] = STAGE_TARGET) -> WalkStep | None:
    """Next key press that brings the stage toward ``target`` (None: arrived).

    The camera follows the character, so walking left moves the stage right on
    screen: a stage left of the target means walk left (A), below means S.
    """
    dx = stage[0] - target[0]
    dy = stage[1] - target[1]
    if (dx * dx + dy * dy) ** 0.5 <= ARRIVED_DISTANCE:
        return None
    if abs(dx) / PIXELS_PER_SECOND["x"] >= abs(dy) / PIXELS_PER_SECOND["y"]:
        key, distance, speed = ("a" if dx < 0 else "d"), abs(dx), PIXELS_PER_SECOND["x"]
    else:
        key, distance, speed = ("s" if dy > 0 else "w"), abs(dy), PIXELS_PER_SECOND["y"]
    seconds = min(MAX_STEP_SECONDS, max(MIN_STEP_SECONDS, distance / speed))
    return WalkStep(key, round(seconds, 3))


# A step moves the stage on screen by about the step's walk (speeds above;
# measured 2026-11-05 at 1080p: W/S ~420, A/D ~650 px/s).  A red patch this
# far from where the stage should be after a step is something else: the
# bar's red carpet, 500+ px away (4K PC 1080p clone 2026-11-05).
STAGE_JUMP_LIMIT = 250.0
OPPOSITE_KEYS = {"w": "s", "s": "w", "a": "d", "d": "a"}

# Short taps tried around the centre when the stage is reached but the
# pre-battle screen has not opened yet (occlusion biases the stage centroid).
NUDGE_SEQUENCE = (
    WalkStep("s", 0.08),
    WalkStep("a", 0.08),
    WalkStep("w", 0.08),
    WalkStep("w", 0.08),
    WalkStep("d", 0.08),
    WalkStep("d", 0.08),
    WalkStep("s", 0.08),
    WalkStep("s", 0.08),
)


# 末日之书 (LAST NIGHT) field: the red crossed-swords battle marker, about
# 30x28 px and 420 red pixels (live 2026-09-26).  Walking onto it opens the
# boss page.  The whole screen is searched (the field keeps the character's
# last position, so the marker can sit at the very edge, live (1877, 133))
# except the HUD parts that carry red: minimap with its own small marker,
# the event logo, the red "!" badges of the top-right icons.
MARKER_HUD_MASKS = (
    (115, 85, 180, 175),  # minimap
    (1560, 100, 285, 115),  # event logo
    (1540, 10, 350, 95),  # top-right icons and their badges
)
MARKER_AREA = (250, 900)
MARKER_SIDE = (18, 48)
# The character's feet: the marker sits here when the character stands on it.
MARKER_TARGET = (955, 545)


def find_marker(frame_1080: np.ndarray) -> tuple[int, int] | None:
    """Centre of the red crossed-swords battle marker, or None."""
    hsv = cv2.cvtColor(frame_1080[:, :, :3], cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    red = ((hue <= 8) | (hue >= 168)) & (saturation >= 120) & (value >= 50)
    mask = red.astype(np.uint8) * 255
    for x, y, w, h in MARKER_HUD_MASKS:
        mask[y : y + h, x : x + w] = 0
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    best = None
    for index in range(1, count):
        area = int(stats[index][cv2.CC_STAT_AREA])
        width = int(stats[index][cv2.CC_STAT_WIDTH])
        height = int(stats[index][cv2.CC_STAT_HEIGHT])
        if not MARKER_AREA[0] <= area <= MARKER_AREA[1]:
            continue
        low, high = MARKER_SIDE
        if not (low <= width <= high and low <= height <= high):
            continue
        if best is None or area > best[0]:
            best = (area, int(centroids[index][0]), int(centroids[index][1]))
    return None if best is None else (best[1], best[2])


def predict_after_step(position: tuple[int, int], step: WalkStep) -> tuple[int, int]:
    """Where a ground point moves on screen after ``step``.

    Used while the marker hides behind a masked HUD area (live: it slid under
    the event logo after one D step): walking right moves the view right, so
    the point moves left on screen, and so on.
    """
    x, y = position
    if step.key in ("a", "d"):
        shift = round(PIXELS_PER_SECOND["x"] * step.seconds)
        x += shift if step.key == "a" else -shift
    else:
        shift = round(PIXELS_PER_SECOND["y"] * step.seconds)
        y += shift if step.key == "w" else -shift
    return x, y
