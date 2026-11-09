"""跑图的技能栏：右下角第 1→4 格要放探查、吸收、召集、压制。

玩家的问题摘要（v0.2.14，2026-10-26，1920×1080 视窗）：每张卡都「探查没有
开始（探查点击后未确认执行反馈：ratio=0.167, text=无可召集的战场怪物）」，一张
一张失败到最后，玩家看不出是技能放错了。画面上第 3 格是压制、第 4 格是探查，
第 1 格（被角色挡住）按下去是召集。跑图按固定栏位找技能，放错了每一格都按错。

这里在地图上看一次技能栏：四格各自认是哪一个采集技能。有一格清楚认出是
另一个采集技能，就停下来，一句话说哪一格放了什么、要怎么放。认不出的格子
（被角色、特效挡住）不算错，照常跑（「认不准就不按」只用在会按错的地方）。
"""

from __future__ import annotations

from dataclasses import replace

from src.tasks.map_trade.action_icons import (
    ABSORB_ICON,
    ACTION_SLOT_CENTER_RELATIVE_ROIS,
    ACTION_SLOT_RELATIVE_ROIS,
    ACTION_SLOT_SEARCH_RADII_REFERENCE,
    SEARCH_ICON,
    SUBDUE_ICON,
    SUMMON_ICON,
    ActionIconSpec,
    ActionIconState,
)

# (slot number on the skill bar, slot name in action_icons, skill, its icon)
FIXED_SLOTS = (
    (1, "search", "探查", SEARCH_ICON),
    (2, "absorb", "吸收", ABSORB_ICON),
    (3, "summon", "召集", SUMMON_ICON),
    (4, "subdue", "压制", SUBDUE_ICON),
)
LAYOUT_TEXT = "探查、吸收、召集、压制"
# Every slot a skill may sit in: the four above and the fifth (the player's
# own; Leo 2026-11-09 picked 「1～5 格都找，找到就在那格按」).
ALL_SLOTS = ((1, "search"), (2, "absorb"), (3, "summon"), (4, "subdue"), (5, "teleport"))
SLOT_NAMES = dict(ALL_SLOTS)
HOME_SLOT = {skill: slot for _number, slot, skill, _icon in FIXED_SLOTS}
# Two slots read: the collection group is on screen (else another group or
# no skill bar, and nothing can be said yet).
CONCLUSIVE_SLOTS = 2
SEEN = frozenset({ActionIconState.AVAILABLE, ActionIconState.USED})


class SkillLayoutWrong(RuntimeError):
    """The skill bar holds the collection skills in other slots."""


def icon_at_slot(icon: ActionIconSpec, slot: str) -> ActionIconSpec:
    """``icon`` looked for in another slot of the skill bar."""
    roi = ACTION_SLOT_RELATIVE_ROIS[slot]
    center = ACTION_SLOT_CENTER_RELATIVE_ROIS[slot]
    template = replace(icon.template, relative_roi=roi, candidate_center_roi=center)
    detection = icon.detection_template
    if detection is not None:
        detection = replace(detection, relative_roi=roi, candidate_center_roi=center)
    return replace(
        icon,
        template=template,
        detection_template=detection,
        slot_name=slot,
        search_radius_reference=ACTION_SLOT_SEARCH_RADII_REFERENCE[slot],
    )


_SPECS = {
    (number, skill): icon_at_slot(icon, slot)
    for number, slot in ALL_SLOTS
    for _n, _s, skill, icon in FIXED_SLOTS
}


def read_layout(detector, frame) -> dict[int, str | None]:
    """Slot number -> the one collection skill seen there (None: not clear)."""
    layout: dict[int, str | None] = {}
    for number, _slot in ALL_SLOTS:
        seen = [
            skill
            for _n, _s, skill, _i in FIXED_SLOTS
            if detector.detect(frame, _SPECS[(number, skill)]).state in SEEN
        ]
        layout[number] = seen[0] if len(seen) == 1 else None
    return layout


def conclusive(layout: dict[int, str | None]) -> bool:
    return sum(skill is not None for skill in layout.values()) >= CONCLUSIVE_SLOTS


def wrong_slots(layout: dict[int, str | None]) -> list[tuple[int, str, str]]:
    """(slot, skill seen there, skill that belongs there) for each wrong slot."""
    expected = {number: skill for number, _slot, skill, _icon in FIXED_SLOTS}
    return [
        (number, seen, expected[number])
        for number, seen in sorted(layout.items())
        if number in expected and seen is not None and seen != expected[number]
    ]


def placement(reads) -> tuple[dict[str, str], list[tuple[int, str, str]]]:
    """(skill -> slot name for each skill seen away from its own slot in
    every read, wrong slots whose own skill is seen nowhere).

    Leo 2026-11-09: a skill found in any of slots 1-5 is pressed where it
    is; only one not found anywhere stops the run.  A skill also seen in its
    own slot stays there."""
    moved: dict[str, str] = {}
    for _n, home, skill, _icon in FIXED_SLOTS:
        places = [
            {number for number, seen in layout.items() if seen == skill} for layout in reads
        ]
        common = set.intersection(*places) if places else set()
        home_number = next(n for n, slot in ALL_SLOTS if slot == home)
        if home_number in common or len(common) != 1:
            continue
        moved[skill] = SLOT_NAMES[next(iter(common))]
    wrong = [
        (number, seen, should)
        for number, seen, should in wrong_slots(reads[0])
        if (number, seen, should) in wrong_slots(reads[-1]) and should not in moved
    ]
    return moved, wrong


def slot_number_of(slot_name: str) -> int:
    return next(n for n, slot in ALL_SLOTS if slot == slot_name)


def _box_at(home_box, home_slot: str, slot: str):
    """``home_box`` (relative, measured under ``home_slot``) moved by the
    distance from that slot's centre to ``slot``'s."""
    from src.tasks.map_trade.action_icons import (
        ACTION_SLOT_CENTERS_REFERENCE,
        SKILL_REFERENCE_HEIGHT,
        SKILL_REFERENCE_WIDTH,
    )

    hx, hy = ACTION_SLOT_CENTERS_REFERENCE[home_slot]
    tx, ty = ACTION_SLOT_CENTERS_REFERENCE[slot]
    dx, dy = (tx - hx) / SKILL_REFERENCE_WIDTH, (ty - hy) / SKILL_REFERENCE_HEIGHT
    left, top, right, bottom = home_box
    return (left + dx, top + dy, right + dx, bottom + dy)


def count_roi_at(home_box, skill: str, slot: str):
    """The skill's count box when it sits in ``slot``: where it sits under
    its own icon, moved with the icon."""
    return _box_at(home_box, HOME_SLOT[skill], slot)


def message(wrong: list[tuple[int, str, str]]) -> str:
    """「技能栏放的位置不对：第3格是压制（要放召集）……」 in player words."""
    slots = "、".join(f"第{number}格是{seen}（要放{should}）" for number, seen, should in wrong)
    return (
        f"技能栏放的位置不对：{slots}。跑图要把右下角技能按第 1→4 格放成：{LAYOUT_TEXT}"
        "（第5格随你放）。请在游戏里换好技能位置再开始，这次先不跑。"
    )


def slot_number(skill: str) -> int:
    return next(n for n, _slot, name, _icon in FIXED_SLOTS if name == skill)


def missing_message(skill: str) -> str:
    """The skill is not on the bar: its slot shows neither its icon nor a
    count (Leo 2026-11-09 「沒數字 代表根本不是 吸收召集壓制這三個」「玩家設定錯
    …停下來 然後說…應該設定成怎麼樣 然後重試」)."""
    number = slot_number(skill)
    return (
        f"技能栏第{number}格不是{skill}（认不出图标，下面也没有次数）。"
        f"跑图要把右下角技能按第 1→4 格放成：{LAYOUT_TEXT}"
        "（第5格随你放）。请在游戏里换好技能位置后重新开始跑图，这次先不跑。"
    )


def other_skill_message(skill: str, other: str, number: int | None = None) -> str:
    """A skill that is not a collection one sits where ``skill`` belongs and
    ``skill`` is found in no other slot."""
    number = number or slot_number(skill)
    return (
        f"技能栏第{number}格是{other}，不是{skill}，其他格也没找到{skill}。"
        f"跑图要把右下角技能按第 1→4 格放成：{LAYOUT_TEXT}"
        "（第5格随你放）。请在游戏里换好技能位置后重新开始跑图，这次先不跑。"
    )
