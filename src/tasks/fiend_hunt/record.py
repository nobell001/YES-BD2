"""Saved 魔兽追踪者 turns: the planning screen right before BATTLE.

A fight is recorded by playing it once by hand.  Each turn, right before
BATTLE, the tool saves who stands on which cell, the 1-5 order of the left
list, the team in use and each unit's selected skill, plus a screenshot
for the player to look at.  Replay compares the live planning screen with
the saved turn of the same number (see turn_plan.py).

Units are identified by the name the game shows top-left when a unit is
selected (Simplified Chinese client).  List slots and portraits are not
identities: the list re-sorts when someone dies (living units move up,
dead ones drop to the bottom marked OUT) and portraits follow the costume
in use (seen 2026-09-30 in 模擬戰鬥 on the 4K PC).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from src.tasks.fiend_hunt.planner import Cell, FormationPlanError, validate_formation

RECORD_VERSION = 1


class TurnStateError(ValueError):
    """A turn or a saved fight doesn't hold together."""


@dataclass(frozen=True)
class TurnState:
    """One turn's planning screen.

    ``order`` lists the living units of the left list from slot 1 down; the
    dead are left out.  ``cells`` has every unit on the grid, tombstones and
    summons included.  ``skills`` maps a living unit to the label of its
    picked action card (攻击, 技能1, ...; see turn_plan); units whose card
    wasn't read are left out.  ``bursts`` maps a unit on a skill to its
    爆发 level (the header's BURST n, set with ◀ ▶ on the lit card; 1-3,
    0 = burst off; Leo 2026-10-01); units whose level wasn't read are left out.
    ``costumes`` maps a unit on a skill to the costume whose skill it is
    (souseha costume id, costumes.py; Leo 2026-10-06): the card's row can
    differ between players, the costume can't.  Units whose costume isn't
    known are left out and go by ``skills``.
    ``preempt`` maps a unit to the skill card (技能1, ...) whose 「先发制人」
    switch beside it is turned on this turn (5 SP; the card then greys with
    a clock).  塔洛斯 stage 7, 2K PC 2026-10-28: lost without it, won with it.
    """

    turn: int
    team: int
    order: tuple[str, ...]
    cells: Mapping[str, Cell]
    dead: frozenset[str] = frozenset()
    skills: Mapping[str, str] = field(default_factory=dict)
    bursts: Mapping[str, int] = field(default_factory=dict)
    costumes: Mapping[str, str] = field(default_factory=dict)
    preempt: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "order", tuple(self.order))
        object.__setattr__(self, "cells", {unit: tuple(cell) for unit, cell in self.cells.items()})
        object.__setattr__(self, "dead", frozenset(self.dead))
        object.__setattr__(self, "skills", dict(self.skills))
        object.__setattr__(self, "bursts", dict(self.bursts))
        object.__setattr__(self, "costumes", dict(self.costumes))
        object.__setattr__(self, "preempt", dict(self.preempt))
        _validate_turn(self)

    @property
    def living(self) -> set[str]:
        return set(self.cells) - self.dead


def _validate_turn(state: TurnState) -> None:
    if state.turn < 1:
        raise TurnStateError(f"回合数 {state.turn} 不对")
    if state.team < 1:
        raise TurnStateError(f"第 {state.turn} 回合的队伍 {state.team} 不对")
    try:
        validate_formation(state.cells)
    except FormationPlanError as error:
        raise TurnStateError(f"第 {state.turn} 回合：{error}") from error
    if len(set(state.order)) != len(state.order):
        raise TurnStateError(f"第 {state.turn} 回合的顺序里有重复的角色")
    for unit in state.order:
        if unit not in state.cells:
            raise TurnStateError(f"第 {state.turn} 回合：顺序里的 {unit} 不在场上")
        if unit in state.dead:
            raise TurnStateError(f"第 {state.turn} 回合：{unit} 已阵亡，不该在顺序里")
    for unit in state.dead:
        if unit not in state.cells:
            raise TurnStateError(f"第 {state.turn} 回合：阵亡的 {unit} 没有墓碑格")
    for unit in state.skills:
        if unit not in state.living:
            raise TurnStateError(f"第 {state.turn} 回合：{unit} 不在场上或已阵亡，不该有技能")
    for unit, level in state.bursts.items():
        if unit not in state.living:
            raise TurnStateError(f"第 {state.turn} 回合：{unit} 不在场上或已阵亡，不该有爆发")
        if isinstance(level, bool) or not isinstance(level, int) or level < 0:
            raise TurnStateError(f"第 {state.turn} 回合：{unit} 的爆发 {level!r} 不对")
    for unit in state.costumes:
        if unit not in state.living:
            raise TurnStateError(f"第 {state.turn} 回合：{unit} 不在场上或已阵亡，不该有服装技能")
    for unit, skill in state.preempt.items():
        if unit not in state.living:
            raise TurnStateError(f"第 {state.turn} 回合：{unit} 不在场上或已阵亡，不该开先发制人")
        if not skill.startswith("技能"):
            raise TurnStateError(
                f"第 {state.turn} 回合：{unit} 的先发制人要写在技能卡上（{skill}）"
            )


@dataclass
class FightRecord:
    """Every saved turn of one fight, keyed by TURN number (1, 3, 5, ...)."""

    turns: dict[int, TurnState]
    title: str = ""
    source: str = "recorded"
    screenshots: dict[int, str] = field(default_factory=dict)  # file names beside the record
    # Units whose card, 爆发 or place in the order the player changed on the
    # chart (Leo 2026-10-06): the screenshot no longer shows them as saved,
    # so replay checks their card by its label instead.
    edited: dict[int, frozenset[str]] = field(default_factory=dict)
    # unit -> card label -> costume id, as learned from the card columns while
    # recording (the cards' rows on the recording player's PC).
    cards: dict[str, dict[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.edited = {number: frozenset(units) for number, units in self.edited.items() if units}
        for number, units in self.edited.items():
            if number not in self.turns:
                raise TurnStateError(f"第 {number} 回合改过但没有存档")
            if not units <= self.turns[number].living:
                raise TurnStateError(f"第 {number} 回合改过的角色不在场上")
        for number, state in self.turns.items():
            if number != state.turn:
                raise TurnStateError(f"第 {number} 回合的存档写的是第 {state.turn} 回合")
        for number in self.screenshots:
            if number not in self.turns:
                raise TurnStateError(f"第 {number} 回合有截图但没有存档")
        team, since = 1, None
        for number in sorted(self.turns):
            state = self.turns[number]
            if state.team < team:
                raise TurnStateError(
                    f"第 {number} 回合用 TEAM{state.team}，但第 {since} 回合已经换成"
                    f" TEAM{team}，游戏里换不回去"
                )
            if state.team > team:
                team, since = state.team, number


def record_to_dict(record: FightRecord) -> dict:
    turns = []
    for number in sorted(record.turns):
        state = record.turns[number]
        entry = {
            "turn": state.turn,
            "team": state.team,
            "order": list(state.order),
            "cells": {unit: list(cell) for unit, cell in state.cells.items()},
            "dead": sorted(state.dead),
            "skills": dict(state.skills),
        }
        if state.bursts:
            entry["bursts"] = dict(state.bursts)
        if state.costumes:
            entry["costumes"] = dict(state.costumes)
        if state.preempt:
            entry["preempt"] = dict(state.preempt)
        if number in record.screenshots:
            entry["screenshot"] = record.screenshots[number]
        if record.edited.get(number):
            entry["edited"] = sorted(record.edited[number])
        turns.append(entry)
    data = {
        "version": RECORD_VERSION,
        "title": record.title,
        "source": record.source,
        "turns": turns,
    }
    if record.cards:
        data["cards"] = {unit: dict(cards) for unit, cards in record.cards.items()}
    return data


def record_from_dict(data: object) -> FightRecord:
    if not isinstance(data, dict):
        raise TurnStateError("存档格式不对")
    if data.get("version") != RECORD_VERSION:
        raise TurnStateError(f"不支持的存档版本 {data.get('version')!r}")
    turns: dict[int, TurnState] = {}
    screenshots: dict[int, str] = {}
    edited: dict[int, frozenset[str]] = {}
    for entry in _list(data.get("turns"), "turns"):
        if not isinstance(entry, dict):
            raise TurnStateError("存档里的回合格式不对")
        state = TurnState(
            turn=_int(entry.get("turn"), "turn"),
            team=_int(entry.get("team"), "team"),
            order=tuple(_str(unit, "order") for unit in _list(entry.get("order"), "order")),
            cells={
                _str(unit, "cells"): _cell(cell)
                for unit, cell in _dict(entry.get("cells"), "cells").items()
            },
            dead=frozenset(_str(unit, "dead") for unit in _list(entry.get("dead", []), "dead")),
            skills={
                _str(unit, "skills"): _str(skill, "skills")
                for unit, skill in _dict(entry.get("skills", {}), "skills").items()
            },
            bursts={
                _str(unit, "bursts"): _int(level, "bursts")
                for unit, level in _dict(entry.get("bursts", {}), "bursts").items()
            },
            costumes={
                _str(unit, "costumes"): _costume_id(_str(costume, "costumes"))
                for unit, costume in _dict(entry.get("costumes", {}), "costumes").items()
            },
            preempt={
                _str(unit, "preempt"): _str(skill, "preempt")
                for unit, skill in _dict(entry.get("preempt", {}), "preempt").items()
            },
        )
        if state.turn in turns:
            raise TurnStateError(f"第 {state.turn} 回合存了两次")
        turns[state.turn] = state
        if "screenshot" in entry:
            screenshots[state.turn] = _str(entry["screenshot"], "screenshot")
        if "edited" in entry:
            edited[state.turn] = frozenset(
                _str(unit, "edited") for unit in _list(entry["edited"], "edited")
            )
    return FightRecord(
        turns=turns,
        title=_str(data["title"], "title") if data.get("title") else "",
        source=_str(data.get("source", "recorded"), "source"),
        screenshots=screenshots,
        edited=edited,
        cards={
            _str(unit, "cards"): {
                _str(label, "cards"): _costume_id(_str(costume, "cards"))
                for label, costume in _dict(cards, "cards").items()
            }
            for unit, cards in _dict(data.get("cards", {}), "cards").items()
        },
    )


def _costume_id(costume_id: str) -> str:
    """A costume id as the character list knows it now: a costume first added
    from the official notice (temporary) keeps working in saves once souseha's
    entry replaces it (costumes.py aliases, Leo 2026-10-07)."""
    try:
        from src.tasks.fiend_hunt import costumes
    except ImportError:  # the list needs OpenCV; a save reads without it
        return costume_id
    return costumes.book().canonical(costume_id)


def save_record(record: FightRecord, path: str | Path) -> None:
    """Write the record whole or not at all: a crash or power cut while
    writing must not leave half a file (a save that can't be read is lost)."""
    path = Path(path)
    text = json.dumps(record_to_dict(record), ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            # Windows: a virus scanner or the indexer can hold the old file a moment.
            if attempt == 4:
                raise
            time.sleep(0.1)


def load_record(path: str | Path) -> FightRecord:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TurnStateError(f"存档不是有效的 JSON：{error}") from error
    return record_from_dict(data)


def _int(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TurnStateError(f"存档的 {key} 应该是整数：{value!r}")
    return value


def _str(value: object, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise TurnStateError(f"存档的 {key} 应该是文字：{value!r}")
    return value


def _list(value: object, key: str) -> Iterable:
    if not isinstance(value, list):
        raise TurnStateError(f"存档的 {key} 应该是列表：{value!r}")
    return value


def _dict(value: object, key: str) -> dict:
    if not isinstance(value, dict):
        raise TurnStateError(f"存档的 {key} 应该是对照表：{value!r}")
    return value


def _cell(value: object) -> Cell:
    if not isinstance(value, list) or len(value) != 2:
        raise TurnStateError(f"存档的格子应该是 [行, 列]：{value!r}")
    return _int(value[0], "cells"), _int(value[1], "cells")
