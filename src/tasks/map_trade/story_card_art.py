"""Story cartridges told apart by their cover art on the quick bar.

Leo 2026-10-09 (桌面分身 1920x1080): the number badges of look-alike cards
(10/19, 15/18, 16/18) differ by about 0.01 in template score, so a card could
search the bar for minutes.  The cover art does not look alike: on his frame
each card's own art scores 0.80-0.85 at its slot and any other card's art at
most 0.75 there.  The bar is not strictly in number order: pinned cards
come first (fixture native_720_q6_visible: 6, 18, 20, then 1, 2, 3...), so
the target's art is looked for along the whole bar and must clearly beat
every other card's art at that spot.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from src.utils.image_utils import template_match_response

ART_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[3]
    / "recognition-assets"
    / "template-assets"
    / "quick_switch_cartridges"
)
ART_FILE = "story_cartridge_art_{:02d}.png"
ART_NUMBERS = tuple(range(1, 20))
# Template pixels to 1080p client pixels (best fit 1.70 on Leo's frame).
ART_SCALE_1080 = 1.7
ART_SCALE_STEPS = (0.97, 1.0, 1.03)
# Rows of the 1080p client that hold the cartridges (art top 920, 105 high).
ART_BAND_TOP_1080 = 895
ART_BAND_BOTTOM_1080 = 1050
# The number badge sits on the art's top-left corner (1080p): badge 10 at
# (453, 922), its art at (453, 920).
BADGE_FROM_ART_1080 = (0.0, 2.0)
BADGE_SIZE_1080 = 29
CARD_SPACING_1080 = 180.0
# A card's own art at its slot; another card's art there stays below.
ART_MIN_SCORE = 0.72
ART_MIN_LEAD = 0.04
# Arts that vote for where the bar stands.
ART_VOTE_SCORE = 0.76
ART_VOTE_TOLERANCE = 0.3
ART_VOTE_MIN = 2
# How far the art may sit from the slot the order gives (cards).
ART_SLOT_TOLERANCE = 0.3


@dataclass(frozen=True)
class ArtMatch:
    number: int
    score: float
    # Art top-left in 1080p client pixels.
    left: float
    top: float

    @property
    def badge_x(self) -> float:
        """Badge centre x (1080p), the coordinate the bar order uses."""
        return self.left + BADGE_FROM_ART_1080[0] + BADGE_SIZE_1080 / 2


@dataclass(frozen=True)
class SlotCheck:
    ok: bool
    reason: str
    target: ArtMatch | None = None
    other: ArtMatch | None = None


@lru_cache(maxsize=None)
def _template(number: int) -> np.ndarray | None:
    path = ART_TEMPLATE_DIR / ART_FILE.format(number)
    if not path.is_file():
        # A card newer than the shipped pictures goes by its badge.
        return None
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


def has_art(number: int) -> bool:
    """A picture ships for this card (cards newer than them go by badge)."""
    return _template(number) is not None


@lru_cache(maxsize=64)
def _scaled_template(number: int, scale: float) -> np.ndarray | None:
    template = _template(number)
    if template is None:
        return None
    return cv2.resize(
        template,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )


def _band_1080(frame: np.ndarray) -> np.ndarray:
    """The cartridge rows, resized so the client is 1080 pixels high."""

    height, width = frame.shape[:2]
    factor = 1080.0 / height
    top = int(ART_BAND_TOP_1080 / factor)
    bottom = int(np.ceil(ART_BAND_BOTTOM_1080 / factor))
    band = frame[top:bottom, :, :3]
    if factor != 1.0:
        band = cv2.resize(
            band,
            (round(width * factor), round((bottom - top) * factor)),
            interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC,
        )
    return band


def _best(
    band: np.ndarray,
    number: int,
    x_range: tuple[float, float] | None = None,
) -> ArtMatch | None:
    best: ArtMatch | None = None
    for step in ART_SCALE_STEPS:
        template = _scaled_template(number, round(ART_SCALE_1080 * step, 3))
        if template is None:
            return None
        th, tw = template.shape[:2]
        left = 0
        right = band.shape[1]
        if x_range is not None:
            left = max(0, int(x_range[0]))
            right = min(band.shape[1], int(np.ceil(x_range[1])) + tw)
        region = band[:, left:right]
        if region.shape[0] < th or region.shape[1] < tw:
            continue
        response = template_match_response(region, template)
        _, score, _, location = cv2.minMaxLoc(response)
        if best is None or score > best.score:
            best = ArtMatch(
                number,
                float(score),
                float(left + location[0]),
                float(ART_BAND_TOP_1080 + location[1]),
            )
    return best


def bar_matches(frame: np.ndarray, numbers=ART_NUMBERS) -> tuple[ArtMatch, ...]:
    """Each card's best spot on the bar (1080p coordinates)."""

    band = _band_1080(frame)
    found = (_best(band, number) for number in numbers)
    return tuple(match for match in found if match is not None)


def bar_offset(matches: tuple[ArtMatch, ...]) -> float | None:
    """Card number = offset + badge x / 180: the strong arts vote and the
    largest agreeing group wins, so a stray match drops out."""

    votes = [
        match.number - match.badge_x / CARD_SPACING_1080
        for match in matches
        if match.score >= ART_VOTE_SCORE
    ]
    best: list[float] = []
    for value in votes:
        group = [other for other in votes if abs(other - value) <= ART_VOTE_TOLERANCE]
        if len(group) > len(best):
            best = group
    if len(best) < ART_VOTE_MIN:
        return None
    return float(np.median(best))


def check_slot(frame: np.ndarray, target: int, badge_x: float) -> SlotCheck:
    """Is the card whose badge the order puts at ``badge_x`` (1080p) the
    target?  Its own art must be the best art there, by a clear lead."""

    if _template(target) is None:
        return SlotCheck(False, f"没有卡带{target}的图片")
    band = _band_1080(frame)
    art_left = badge_x - BADGE_SIZE_1080 / 2 - BADGE_FROM_ART_1080[0]
    window = ART_SLOT_TOLERANCE * CARD_SPACING_1080
    x_range = (art_left - window, art_left + window)
    target_match = _best(band, target, x_range)
    if target_match is None:
        return SlotCheck(False, f"卡带{target}的位置超出画面")
    other: ArtMatch | None = None
    for number in ART_NUMBERS:
        if number == target:
            continue
        match = _best(band, number, x_range)
        if match is not None and (other is None or match.score > other.score):
            other = match
    if target_match.score < ART_MIN_SCORE:
        return SlotCheck(
            False,
            f"卡带{target}图片相似度{target_match.score:.3f}<{ART_MIN_SCORE:.2f}",
            target_match,
            other,
        )
    if other is not None and target_match.score - other.score < ART_MIN_LEAD:
        return SlotCheck(
            False,
            (
                f"卡带{target}图片{target_match.score:.3f}没有明显赢过"
                f"卡带{other.number}的{other.score:.3f}"
            ),
            target_match,
            other,
        )
    return SlotCheck(True, "", target_match, other)


def find_card(frame: np.ndarray, target: int) -> SlotCheck:
    """The target's art anywhere on the bar, clearly ahead of every other
    card's art at that spot."""

    if _template(target) is None:
        return SlotCheck(False, f"没有卡带{target}的图片")
    band = _band_1080(frame)
    target_match = _best(band, target)
    if target_match is None:
        return SlotCheck(False, f"卡带{target}的图片超出画面")
    if target_match.score < ART_MIN_SCORE:
        return SlotCheck(
            False,
            f"卡带{target}图片相似度{target_match.score:.3f}<{ART_MIN_SCORE:.2f}",
            target_match,
        )
    window = ART_SLOT_TOLERANCE * CARD_SPACING_1080
    x_range = (target_match.left - window, target_match.left + window)
    other: ArtMatch | None = None
    for number in ART_NUMBERS:
        if number == target:
            continue
        match = _best(band, number, x_range)
        if match is not None and (other is None or match.score > other.score):
            other = match
    if other is not None and target_match.score - other.score < ART_MIN_LEAD:
        return SlotCheck(
            False,
            (
                f"卡带{target}图片{target_match.score:.3f}没有明显赢过"
                f"卡带{other.number}的{other.score:.3f}"
            ),
            target_match,
            other,
        )
    return SlotCheck(True, "", target_match, other)
