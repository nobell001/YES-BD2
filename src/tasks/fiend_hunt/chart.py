"""A saved fight as a turn chart, like a souseha formation page (Leo 2026-10-06).

For each turn: the 1-N order with each unit's portrait, card (攻击 / 技能 /
击退) and 爆发 level, and the grid with who stands where.  Portraits are cut
from the save's own screenshots (the list entry's portrait), so a costume
or character the souseha list lacks still shows.  A card the record didn't
keep is read off the screenshot: a round skill icon on the portrait means a
skill, none an attack; the 爆发 level from the entry's flame.  Nothing here
touches the game.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.tasks.fiend_hunt import layout, vision
from src.tasks.fiend_hunt.planner import Cell
from src.tasks.fiend_hunt.record import FightRecord


@dataclass
class ChartUnit:
    name: str
    slot: int | None  # 0-based list slot; None for the dead
    cell: Cell | None
    action: str = ""  # 攻击 / 击退 / 技能 / 技能2 ...; '' when unknown
    burst: int = 0
    dead: bool = False
    portrait: np.ndarray | None = None  # BGR
    costume: str | None = None  # the skill's costume id, when known (costumes.py)
    listed: bool = False  # portrait from the built-in list, not a screenshot


@dataclass
class ChartTurn:
    turn: int
    team: int
    units: list[ChartUnit] = field(default_factory=list)

    def by_cell(self) -> dict[Cell, ChartUnit]:
        return {unit.cell: unit for unit in self.units if unit.cell is not None}


def portrait(frame: np.ndarray, slot: int) -> np.ndarray:
    """The list entry's portrait, square, cut from a planning screenshot (any size)."""
    left, top, right, bottom = layout.slot_box(slot)
    middle = (left + right) / 2 + 4.0  # clear of the slot number bottom-left
    # The face: below the buff icons along the top, above the HP number.
    top += 8.0
    side = (bottom - top) * 0.82
    return layout.crop(frame, (middle - side / 2, top, middle + side / 2, top + side)).copy()


def _action(saved: str | None, frame: np.ndarray | None, slot: int) -> str:
    if saved:
        return "攻击" if saved == "攻击" else saved
    if frame is None:
        return ""
    return vision.list_action(frame, slot) or ""


def _burst(saved: int | None, frame: np.ndarray | None, slot: int, action: str) -> int:
    if saved is not None:
        return int(saved)
    if frame is None or not action.startswith("技能"):
        return 0
    return vision.burst_flame(frame, slot) or 0


def build_chart(
    record: FightRecord, folder: Path, load, kept: dict | None = None
) -> list[ChartTurn]:
    """Every saved turn as a chart; ``load(path)`` gives a BGR frame or None.

    Portraits come from the built-in character list (Leo 2026-10-06: not cut
    from the game's screenshots); only a unit the list lacks (a character
    newer than it) gets its face cut from the save's screenshot.
    ``kept`` holds turns built before: a turn whose save and screenshot are
    unchanged isn't built (nor its screenshot read) again, as after each
    record key press.
    """
    faces: dict[str, np.ndarray] = {}
    turns = []
    used = set()
    for number in sorted(record.turns):
        state = record.turns[number]
        shot = record.screenshots.get(number)
        key = (number, repr(state), shot, _stamp(Path(folder) / shot) if shot else None)
        used.add(key)
        if kept is not None and key in kept:
            turns.append(kept[key])
            faces.update(
                {
                    u.name: u.portrait
                    for u in kept[key].units
                    if not u.listed and u.portrait is not None
                }
            )
            continue
        frame = None
        if shot and any(list_face(name) is None for name in state.order):
            frame = load(Path(folder) / shot)
        chart = ChartTurn(number, state.team)
        for slot, name in enumerate(state.order):
            # cards and 爆发 a save didn't keep are still read off its screenshot
            needs_frame = not state.skills.get(name) or (
                state.bursts.get(name) is None
                and str(state.skills.get(name, "")).startswith("技能")
            )
            if frame is None and shot and needs_frame:
                frame = load(Path(folder) / shot)
            action = _action(state.skills.get(name), frame, slot)
            costume = state.costumes.get(name) if action.startswith("技能") else None
            unit = ChartUnit(
                name,
                slot,
                state.cells.get(name),
                action,
                _burst(state.bursts.get(name), frame, slot, action),
                costume=costume,
            )
            unit.portrait = list_face(name, costume)
            unit.listed = unit.portrait is not None
            if unit.portrait is None and frame is not None:
                unit.portrait = portrait(frame, slot)
                faces[name] = unit.portrait
            chart.units.append(unit)
        for name in sorted(state.dead):
            dead = ChartUnit(name, None, state.cells.get(name), dead=True)
            dead.portrait = list_face(name)
            dead.listed = dead.portrait is not None
            chart.units.append(dead)
        turns.append(chart)
        if kept is not None:
            kept[key] = chart
    for chart in turns:  # a face seen on any turn serves the turns without one
        for unit in chart.units:
            if unit.portrait is None:
                unit.portrait = faces.get(unit.name)
    if kept is not None:
        for key in [key for key in kept if key not in used]:
            del kept[key]  # turns changed or gone
    return turns


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def list_face(name: str, costume: str | None = None) -> np.ndarray | None:
    """A unit's portrait from the built-in list (costumes.py), or None."""
    from src.tasks.fiend_hunt import costumes

    picture = costumes.book().picture_id(name, costume)
    return costumes.picture_alpha(picture) if picture else None


def team_members(turns: list[ChartTurn]) -> dict[int, list[str]]:
    """Team number -> its units, in the order they first show up."""
    teams: dict[int, list[str]] = {}
    for chart in turns:
        members = teams.setdefault(chart.team, [])
        for unit in chart.units:
            if unit.name not in members:
                members.append(unit.name)
    return teams


def timelines(turns: list[ChartTurn]) -> dict[int, dict[str, list[tuple[int, ChartUnit | None]]]]:
    """Team -> unit -> (turn, what it did) for each of that team's turns, like
    souseha's per-character table (Leo 2026-10-06); None where it wasn't there."""
    result: dict[int, dict[str, list[tuple[int, ChartUnit | None]]]] = {}
    for team, members in team_members(turns).items():
        team_turns = [chart for chart in turns if chart.team == team]
        result[team] = {
            name: [
                (chart.turn, next((unit for unit in chart.units if unit.name == name), None))
                for chart in team_turns
            ]
            for name in members
        }
    return result
