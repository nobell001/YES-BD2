"""The top-right 主页 house of 餐厅, 广场, 箱庭, the PVP hall and the fields.

The house is see-through: guests and plates walking behind it in 格鲁菲餐厅
pulled its match from ~0.86 to under the 0.85 bar on 43 of 61 frames (4K
繁中 live test of #518, 2026-11-09).  The 「H」 key badge under it is solid
white with a dark letter, so what walks behind does not change it: either
cue is enough (any-one-of, Leo 2026-11-06 「额外的参考只帮忙」).  Pressing the
badge's spot is not the button, so the press goes to the house above it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ok.task.exceptions import FinishedException, TaskDisabledException

from src.tasks.map_trade.navigator_constants import CHAPTER_HOME_POINT, CHAPTER_HOME_TEMPLATES
from src.utils.vision_models import TemplateSpec

HOUSE_KEY_RELATIVE_ROI = (0.86, 0.0, 1.0, 0.2)
HOUSE_KEY_TEMPLATE = TemplateSpec(
    "主页按钮H键",
    "HomeHouseKeyH.png",
    0.85,
    min_pixel_score=0.85,
    min_zncc_score=0.85,
    relative_roi=HOUSE_KEY_RELATIVE_ROI,
)
# House centre above the badge centre, as a share of the window height
# (4K: house (3596,123), badge (3596,188)).
HOUSE_ABOVE_KEY = 65 / 2160
# Where the house sits when nothing could be read (1080p calibration).
HOUSE_POINT = CHAPTER_HOME_POINT


@dataclass(frozen=True)
class HouseHit:
    center: tuple[int, int]
    score: float
    cue: str  # "house" or "H"


def _passes(vision, frame, spec):
    try:
        result = vision.match(frame, spec)
        return result if vision.passes(result, spec) else None
    except (TaskDisabledException, FinishedException):
        raise
    except Exception:
        return None


def find_house(vision, frame) -> HouseHit | None:
    """Where to press for the top-right house, or None."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    for spec in CHAPTER_HOME_TEMPLATES:
        result = _passes(vision, frame, spec)
        if result is not None:
            return HouseHit(tuple(result.center), float(result.score), "house")
    result = _passes(vision, frame, HOUSE_KEY_TEMPLATE)
    if result is not None:
        x, y = result.center
        height = frame.shape[0]
        return HouseHit((int(x), max(0, round(y - HOUSE_ABOVE_KEY * height))), float(result.score), "H")
    return None
