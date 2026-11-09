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
from pathlib import Path

import cv2
import numpy as np

from src.utils.image_utils import template_match_response

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


# The crossed swords' shape (cut from the 魔王城 altar marker, the same icon
# on the 末日之书 field; alpha = its red pixels).  Colour and size alone also
# take red clothes on the party: a player's 2560x1440 frame (11-09) had a red
# skirt at (907, 521), 469 px against the marker's 466, so the walk went for
# the skirt, which moves with the character, and never got anywhere.  On that
# frame the shape scores 0.79 on the marker and at most 0.45 elsewhere.
MARKER_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "recognition-assets" / "template-assets" / "evil_castle" / "castle_marker.png"
)
# A red patch with this crossed-swords score is the marker for sure.
MARKER_SHAPE_SCORE = 0.6
# The shape alone, without a red patch of the right size (e.g. partly
# covered): needs a higher score and mostly marker-red pixels.
MARKER_SHAPE_ONLY_SCORE = 0.8
MARKER_SHAPE_ONLY_RED = 0.6
# Where the character and the party following it stand (the camera keeps
# the character at the centre).  A red patch here that does not have the
# crossed-swords shape is someone's clothes, not the marker.
PARTY_BOX = (830, 340, 1090, 600)
_marker_template: list = []


def _marker_shape() -> tuple[np.ndarray, np.ndarray] | None:
    if not _marker_template:
        image = cv2.imdecode(np.fromfile(str(MARKER_TEMPLATE), np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None or image.ndim != 3 or image.shape[2] != 4:
            _marker_template.append(None)
        else:
            _marker_template.append(
                (cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY), image[:, :, 3])
            )
    return _marker_template[0]


def _shape_response(grey: np.ndarray, box: tuple[int, int, int, int]) -> tuple[float, tuple[int, int]]:
    """Best crossed-swords score inside ``box`` (x0, y0, x1, y1) and its centre."""
    shape = _marker_shape()
    if shape is None:
        return 0.0, (0, 0)
    template, mask = shape
    height, width = template.shape
    x0, y0 = max(0, box[0] - width // 2), max(0, box[1] - height // 2)
    x1 = min(grey.shape[1], box[2] + width - width // 2)
    y1 = min(grey.shape[0], box[3] + height - height // 2)
    if x1 - x0 < width or y1 - y0 < height:
        return 0.0, (0, 0)
    response = np.nan_to_num(
        template_match_response(grey[y0:y1, x0:x1], template, mask, zero_mean=True),
        nan=-1.0, posinf=-1.0, neginf=-1.0,
    )
    _low, score, _where, (x, y) = cv2.minMaxLoc(response)
    return float(score), (x0 + x + width // 2, y0 + y + height // 2)


def marker_shape_score(frame_1080: np.ndarray, centre: tuple[int, int], reach: int = 8) -> float:
    """How much the spot around ``centre`` looks like the crossed swords."""
    grey = cv2.cvtColor(frame_1080[:, :, :3], cv2.COLOR_BGR2GRAY)
    x, y = centre
    return _shape_response(grey, (x - reach, y - reach, x + reach, y + reach))[0]


def _in_party_box(point: tuple[int, int]) -> bool:
    x0, y0, x1, y1 = PARTY_BOX
    return x0 <= point[0] <= x1 and y0 <= point[1] <= y1


def _red_mask(frame_1080: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame_1080[:, :, :3], cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    return ((hue <= 8) | (hue >= 168)) & (saturation >= 120) & (value >= 50)


# A spot that stays this close after a step that should have moved it at
# least FOLLOW_MIN_SHIFT is on the party (moves with the camera), not on the
# ground; IGNORE_RADIUS around such a spot is left out afterwards.
FOLLOW_STILL_PIXELS = 12.0
FOLLOW_MIN_SHIFT = 25.0
IGNORE_RADIUS = 20.0


def follows_character(
    before: tuple[int, int], after: tuple[int, int], step: "WalkStep"
) -> bool:
    """True when a red spot did not move although ``step`` moved the view."""
    expected = predict_after_step(before, step)
    shift = ((expected[0] - before[0]) ** 2 + (expected[1] - before[1]) ** 2) ** 0.5
    still = ((after[0] - before[0]) ** 2 + (after[1] - before[1]) ** 2) ** 0.5
    return shift >= FOLLOW_MIN_SHIFT and still <= FOLLOW_STILL_PIXELS


# The view counts as moved after a step when the scene shifted this much
# (1080 reference); walking into a wall leaves it still, and then a red spot
# that stayed put proves nothing.
VIEW_MOVED_PIXELS = 10.0


def view_shift(before_1080: np.ndarray, after_1080: np.ndarray) -> float:
    """How far the whole scene moved between two 1080 frames, in pixels."""
    small = []
    for frame in (before_1080, after_1080):
        grey = cv2.cvtColor(cv2.resize(frame[:, :, :3], (480, 270)), cv2.COLOR_BGR2GRAY)
        small.append(np.float32(grey))
    (dx, dy), _response = cv2.phaseCorrelate(small[0], small[1])
    return 4.0 * (dx * dx + dy * dy) ** 0.5


def _ignored(point: tuple[int, int], ignore) -> bool:
    return any(
        ((point[0] - x) ** 2 + (point[1] - y) ** 2) ** 0.5 <= IGNORE_RADIUS for x, y in ignore
    )


def find_marker(
    frame_1080: np.ndarray, ignore: tuple[tuple[int, int], ...] = ()
) -> tuple[int, int] | None:
    """Centre of the red crossed-swords battle marker, or None.

    Three cues, any one can find it; the shape decides between them:
    1. a red patch of the marker's size that has the crossed-swords shape;
    2. the shape alone, mostly marker red (a patch cut by something);
    3. a red patch of the marker's size away from the party (the shape can
       be blurred on a low-quality capture), the largest one.
    A red patch on the party without the shape is never taken.  ``ignore``
    (spots seen to move with the character, see follows_character) only
    drops cue 3: a patch with the crossed-swords shape is always the marker.
    """
    red = _red_mask(frame_1080)
    mask = red.astype(np.uint8) * 255
    for x, y, w, h in MARKER_HUD_MASKS:
        mask[y : y + h, x : x + w] = 0
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    patches = []
    for index in range(1, count):
        area = int(stats[index][cv2.CC_STAT_AREA])
        width = int(stats[index][cv2.CC_STAT_WIDTH])
        height = int(stats[index][cv2.CC_STAT_HEIGHT])
        if not MARKER_AREA[0] <= area <= MARKER_AREA[1]:
            continue
        low, high = MARKER_SIDE
        if not (low <= width <= high and low <= height <= high):
            continue
        patches.append((area, (int(centroids[index][0]), int(centroids[index][1]))))
    shaped = []
    for area, centre in patches:
        score = marker_shape_score(frame_1080, centre)
        if score >= MARKER_SHAPE_SCORE:
            shaped.append((score, centre))
    if shaped:
        return max(shaped)[1]
    shape_only = _marker_by_shape(frame_1080, red)
    if shape_only is not None:
        return shape_only
    away = [
        (area, centre)
        for area, centre in patches
        if not _in_party_box(centre) and not _ignored(centre, ignore)
    ]
    return max(away)[1] if away else None


def _marker_by_shape(frame_1080: np.ndarray, red: np.ndarray) -> tuple[int, int] | None:
    """The crossed swords found by shape over the whole screen, or None."""
    shape = _marker_shape()
    if shape is None:
        return None
    _template, mask = shape
    height, width = mask.shape
    grey = cv2.cvtColor(frame_1080[:, :, :3], cv2.COLOR_BGR2GRAY)
    response = np.nan_to_num(
        template_match_response(grey, _template, mask, zero_mean=True),
        nan=-1.0, posinf=-1.0, neginf=-1.0,
    )
    for x, y, w, h in MARKER_HUD_MASKS:
        response[max(0, y - height) : y + h, max(0, x - width) : x + w] = -1.0
    inside = mask > 0
    for _candidate in range(3):
        _low, score, _where, (x, y) = cv2.minMaxLoc(response)
        if score < MARKER_SHAPE_ONLY_SCORE:
            return None
        patch = red[y : y + height, x : x + width]
        if patch.shape == mask.shape and float(patch[inside].mean()) >= MARKER_SHAPE_ONLY_RED:
            return x + width // 2, y + height // 2
        response[max(0, y - 10) : y + 10, max(0, x - 10) : x + 10] = -1.0
    return None


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
