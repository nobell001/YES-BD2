"""Field skills that are not 探查/吸收/召集/压制 (Leo 2026-11-09 「把那些不相干
的技能放進黑名單」).

Ten skills a player can put on the bar, cut from the live 4K 繁中 bar
(2560x1440, slot 5, 卢戈森林; branch test/skill-icons-1109) and scaled to
1080p (``other_skills/*.png``, green = not part of the glyph).  One of them
clearly seen in a slot means that slot holds no collection skill: it is
never pressed as one, and the stop message names the skill.

Strict (Leo: 「這個分數要求要嚴格一點 有時候會因為地圖原因 被遮住之類的」):
a hit needs a masked match of at least ``HIT_MIN_SCORE`` and to beat every
other blacklisted skill by ``HIT_MIN_MARGIN``.  A hit only vetoes a blind
press; a skill whose own icon is recognised is never held back by it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from src.utils import image_io
from src.utils.image_utils import template_match_response
from src.tasks.map_trade.action_icons import (
    ACTION_SLOT_CENTERS_REFERENCE,
    SKILL_REFERENCE_HEIGHT,
    SKILL_REFERENCE_WIDTH,
)

OTHER_SKILLS = {
    "swift": "迅速",
    "cooking": "料理",
    "craft": "制作装备",
    "revive": "复活",
    "danger": "侦测危险",
    "dash": "飞奔",
    "circle": "创建魔法阵",
    "hide": "藏身",
    "dispatch": "派遣",
    "alchemy": "炼金术",
}
TEMPLATE_DIR = (
    Path(__file__).resolve().parents[3]
    / "recognition-assets"
    / "template-assets"
    / "image"
    / "green"
    / "other_skills"
)
# Around the slot centre, 1080p px: the icon circle is ~80 px across.
SEARCH_HALF = 48
SCALES = (0.90, 0.95, 1.0, 1.05, 1.10)
HIT_MIN_SCORE = 0.90
HIT_MIN_MARGIN = 0.10


@lru_cache(maxsize=None)
def _template(key: str):
    image = image_io.read(TEMPLATE_DIR / f"{key}.png")
    if image is None:
        return None
    green = (image[..., 1] == 255) & (image[..., 0] == 0) & (image[..., 2] == 0)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return gray, (~green).astype(np.uint8) * 255


def _slot_patch(frame, slot: str):
    """The slot's surroundings, scaled to 1080p, in grey."""
    height, width = frame.shape[:2]
    cx, cy = ACTION_SLOT_CENTERS_REFERENCE[slot]
    sx, sy = width / SKILL_REFERENCE_WIDTH, height / SKILL_REFERENCE_HEIGHT
    left = max(0, round((cx - SEARCH_HALF) * sx))
    top = max(0, round((cy - SEARCH_HALF) * sy))
    right = min(width, round((cx + SEARCH_HALF) * sx))
    bottom = min(height, round((cy + SEARCH_HALF) * sy))
    patch = frame[top:bottom, left:right]
    if patch.size == 0:
        return None
    size = (2 * SEARCH_HALF, 2 * SEARCH_HALF)
    patch = cv2.resize(patch, size, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(patch[..., :3], cv2.COLOR_BGR2GRAY)


def scores(frame, slot: str) -> dict[str, float]:
    """Best masked match of each blacklisted skill in ``slot``."""
    patch = _slot_patch(frame, slot)
    found: dict[str, float] = {}
    if patch is None:
        return found
    for key, label in OTHER_SKILLS.items():
        loaded = _template(key)
        if loaded is None:
            continue
        gray, mask = loaded
        best = -1.0
        for scale in SCALES:
            size = (max(4, round(gray.shape[1] * scale)), max(4, round(gray.shape[0] * scale)))
            if size[0] >= patch.shape[1] or size[1] >= patch.shape[0]:
                continue
            tpl = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
            msk = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
            result = template_match_response(patch, tpl, msk, zero_mean=True)
            best = max(best, float(result.max()))
        found[label] = best
    return found


def other_skill_at(frame, slot: str) -> str | None:
    """The non-collection skill clearly seen in ``slot``, else None."""
    ranked = sorted(scores(frame, slot).items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] < HIT_MIN_SCORE:
        return None
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < HIT_MIN_MARGIN:
        return None
    return ranked[0][0]
