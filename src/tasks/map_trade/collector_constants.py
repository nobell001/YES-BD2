from __future__ import annotations

import re
from dataclasses import dataclass

from src.tasks.map_trade.action_icons import (
    ABSORB_ICON,
    SEARCH_ICON,
    SKILL_GROUP_CENTERS_REFERENCE,
    SUBDUE_ICON,
    SUMMON_ICON,
    ActionIconSpec,
)
from src.tasks.map_trade.models import TemplateSpec
from src.utils.calibration import FHD_1080

SEARCH_COUNTDOWN_TIMEOUT = 3.0
SEARCH_COUNTDOWN_INTERVAL = 0.25
# After a missed 探查 toast, look this long for its countdown.
SEARCH_MISSED_FEEDBACK_COUNTDOWN_SECONDS = 3.0
SEARCH_COUNTDOWN_PATTERN = re.compile(r"^\d{1,3}$")
ACTION_AFTER_CLICK_SECONDS = 0.0
ACTION_OCR_WINDOW_SAMPLES = 3
ACTION_OCR_WINDOW_INTERVAL = 0.25
ACTION_FEEDBACK_TIMEOUT = 3.0
ACTION_FEEDBACK_SUCCESS_DELAY_SECONDS = 0.8
ACTION_FEEDBACK_CHARACTER_RATIO = 0.80
SKILL_OCR_UPSCALE = 2.0
SKILL_OCR_FALLBACK_UPSCALE = 3.0
ACTION_ICON_DETECTION_SAMPLES = 3
ACTION_ICON_DETECTION_INTERVAL = 0.15
# A dark icon on a map with no record yet is read again after a pause: right
# after 探查 the skill bar dims for a moment (live 2K 2026-10-01: 召集 on
# 妖怪森林 read used, brightness 0.61, while it could still be pressed - Leo).
ACTION_USED_RECHECKS = 2
ACTION_USED_RECHECK_SECONDS = 1.5
# A grey icon is waited out only this soon after 探查 was pressed, and once
# for the whole bar (Leo 2026-10-15: ~4 s per grey icon in turn felt like 7 s).
DIM_WAIT_VALID_SECONDS = 10.0
SKILL_FAILURE_EVIDENCE_LIMIT = 12
SKILL_FAILURE_TEXT_LIMIT = 320
# Chapters the weekly run skips without writing progress (none since chapter
# 14 got its route, live 2K 2026-09-30).
UNSUPPORTED_COLLECTION_CARD_NUMBERS: frozenset[int] = frozenset()
SKILL_REFERENCE_SIZE = FHD_1080.size
SKILL_GROUP_SWITCH_SETTLE_SECONDS = 0.8


def _relative_reference_point(point: tuple[int, int]) -> tuple[float, float]:
    width, height = SKILL_REFERENCE_SIZE
    return point[0] / width, point[1] / height


def _relative_reference_roi(
    roi: tuple[int, int, int, int],
) -> tuple[float, float, float, float]:
    left, top, width, height = roi
    reference_width, reference_height = SKILL_REFERENCE_SIZE
    return (
        left / reference_width,
        top / reference_height,
        (left + width) / reference_width,
        (top + height) / reference_height,
    )


SKILL_GROUP_REFERENCE_POINTS = SKILL_GROUP_CENTERS_REFERENCE
SKILL_GROUP_RELATIVE_POINTS = {
    group: _relative_reference_point(point)
    for group, point in SKILL_GROUP_REFERENCE_POINTS.items()
}
SKILL_FIXED_COUNT_REFERENCE_ROIS = {
    "吸收": (1498, 890, 66, 37),
    "召集": (1542, 790, 66, 33),
    "压制": (1645, 743, 75, 33),
}
SKILL_FIXED_COUNT_RELATIVE_ROIS = {
    name: _relative_reference_roi(roi)
    for name, roi in SKILL_FIXED_COUNT_REFERENCE_ROIS.items()
}
# Widened 2026-09-29: at 2K the digits span x 1546-1603 and the tight box read
# nothing (探查 ran, the run stopped as failed).
SEARCH_COUNTDOWN_REFERENCE_ROI = (1535, 960, 82, 60)
SEARCH_COUNTDOWN_RELATIVE_ROI = _relative_reference_roi(
    SEARCH_COUNTDOWN_REFERENCE_ROI
)
# Taller since 2026-10-14 (live 4K): a second toast line (「升星天赋技能后，
# 可获得经验值。」) pushes the skill's own line up out of the old 210-270 box,
# and 压制 that worked was reported as failed.
ACTION_FEEDBACK_REFERENCE_ROI = (735, 165, 1182 - 735, 270 - 165)
ACTION_FEEDBACK_RELATIVE_ROI = _relative_reference_roi(ACTION_FEEDBACK_REFERENCE_ROI)
ACTION_SUCCESS_FEEDBACK = {
    "探查": ("在秒内确认隐藏物品的位置",),
    "吸收": ("吸收周围的拾取物",),
    "召集": ("召集带奖励的战场怪物",),
    "压制": (
        "已制伏地图内所有怪物",
        "已制伏地图内所有的怪物",
    ),
}
ACTION_FAILURE_FEEDBACK = {
    "吸收": ("周围没有可以吸收的拾取物",),
    "召集": ("无可召集的战场怪物",),
    "压制": ("没有可制伏的怪物",),
}
# A toast this close to another skill's phrase says that skill was pressed
# (skills in the wrong slots, a player 2026-10-26).
OTHER_SKILL_TOAST_RATIO = 0.8
# The words that make a failure toast one: 无 / 没有.
ACTION_FAILURE_MARKERS = ("无", "没")


@dataclass(frozen=True)
class SkillAction:
    name: str
    icon: ActionIconSpec
    fixed_count_relative_roi: tuple[float, float, float, float] | None = None

    @property
    def template(self) -> TemplateSpec:
        return self.icon.template


@dataclass(frozen=True)
class SkillExecutionResult:
    completed: bool
    depleted: bool = False
    message: str = ""
    # Local map success can be durable even while daily absolute OCR is
    # pending.  Keep the action names visible to the caller for status and
    # final-map warnings without changing the existing positional interface.
    pending_actions: tuple[str, ...] = ()
    # The press did not take: the icon is still bright, no toast came and
    # the count read steadily unchanged, so pressing again is not charged
    # twice.
    press_again: bool = False


@dataclass(frozen=True)
class SearchCountdownSession:
    relative_roi: tuple[float, float, float, float]
    value: int


@dataclass(frozen=True)
class SkillFeedbackObservation:
    text: str
    outcome: str | None
    ratio: float = 0.0
    keyword: str = ""


# The counter is positioned relative to the icon on the live client. Keeping
# a fixed 1920x1080 ROI here can miss it after UI scaling or when the skill
# row shifts, so all limited-action counters use the current match geometry.
SEARCH_ACTION = SkillAction(
    "探查",
    SEARCH_ICON,
    fixed_count_relative_roi=SEARCH_COUNTDOWN_RELATIVE_ROI,
)
ABSORB_ACTION = SkillAction(
    "吸收",
    ABSORB_ICON,
    fixed_count_relative_roi=SKILL_FIXED_COUNT_RELATIVE_ROIS["吸收"],
)
SUMMON_ACTION = SkillAction(
    "召集",
    SUMMON_ICON,
    fixed_count_relative_roi=SKILL_FIXED_COUNT_RELATIVE_ROIS["召集"],
)
SUPPRESS_ACTION = SkillAction(
    "压制",
    SUBDUE_ICON,
    fixed_count_relative_roi=SKILL_FIXED_COUNT_RELATIVE_ROIS["压制"],
)
BATTLE_ACTIONS = (ABSORB_ACTION, SUMMON_ACTION, SUPPRESS_ACTION)

