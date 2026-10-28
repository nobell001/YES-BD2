"""Replay a saved 魔兽追踪者 fight turn by turn.

Each turn: read TURN, look up the saved turn, read who stands where,
then switch team / swap the order / drag / pick skills until the screen
matches the save, and only then press BATTLE.  Anything unexpected (a
turn the save doesn't have, a death, a screen that can't be read, a fix
that doesn't take) stops the fight before BATTLE and hands it back to the
player: 认不准就不按.

The screen itself is behind ``FightScreen`` so this loop has no capture
or mouse code and can be tested against a simulated battle.

Reading the whole screen means tapping every list slot for the names and
holding cells, which is too slow to do several times a turn: a replay has
to stay under 5 minutes (Leo) and the battles take about half of that.  A
screen that also offers ``QuickChecks`` is read in full only when
something changed that the tool didn't do itself: the first turn, a death,
a new list entry, a team switch, or a check that failed.  Otherwise a turn
starts from how the previous one was left, and before BATTLE every living
unit's cell is held to confirm it lights that unit's list slot, so a unit
the battle did move is still caught.  After a full read, only the units
the tool then moved or re-ordered are confirmed again.  Most bosses never
move anyone (Leo 2026-10-06: one in a year of play did), so unless the
player ticks that the boss pushes (``pushes``), carried-over cells are
held only before a drag touches them and after the tool moved them.

The action cards (attack or skill, see turn_plan) are checked last, once
the grid and the order are right.  The left list shows each unit's card:
its portrait turns into the costume whose skill is up, with a round skill
icon top-right, and an attack has no such icon (seen 2026-09-30 on the 4K
PC).  So on a recorded turn, which has a screenshot, each unit to check is
compared with its entry in the saved screenshot, all from one capture;
only a unit that looks different is fixed, by picking its cards until it
looks as saved (Leo's idea).  A chart has no screenshot: there the unit's
list slot is asked for its card and the saved one picked where it
differs.  Either way attacks go before skills, so the SP they free is
there for the skills.  ``check_card`` limits whose cards are checked,
e.g. ``summons_only`` when the player set the characters' attack or skill
in the costume order; the saved 爆发 levels are set for everyone either way.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from src.tasks.fiend_hunt.planner import Cell, Drag, apply_drags, apply_order_swaps
from src.tasks.fiend_hunt.record import FightRecord, TurnState
from src.tasks.fiend_hunt.turn_plan import (
    ATTACK,
    KNOCKBACK,
    SKILL,
    TurnActions,
    TurnMismatch,
    action_matches,
    pick_order,
    plan_turn,
)

FIX_ROUNDS = 3
TURN_READS = 3  # more reads of a TURN that isn't the expected one, until two agree
# Cards tried on a unit that doesn't look as in the saved screenshot, after
# the saved card if the save has one.  Units have 1-4 skill cards (seen on
# the 4K PC); 击退 isn't used against a 魔兽 (Leo), so it is only tried
# when the screenshot shows its arrow (塔洛斯战术教材, Leo 2026-10-22).
CARD_TRIES = (ATTACK, *(f"{SKILL}{number}" for number in range(1, 5)))


class ScreenReadError(Exception):
    """The planning screen couldn't be read with confidence."""


class FightScreen(Protocol):
    def read_turn(self) -> int | None:
        """TURN number on the BATTLE button, or None when it can't be read."""

    def read_state(self, turn: int) -> TurnState:
        """Who stands where, the list order, team and dead, plus the cards it read.

        A screen with ``same_card`` needn't read cards here.  Raises
        ScreenReadError when unsure.
        """

    def switch_team(self, team: int) -> bool:
        """更换队伍 → confirm the switch to ``team``; False if not done."""

    def swap_order(self, first: int, second: int) -> None:
        """Drag slot ``first``'s ⇅ onto slot ``second``'s (0-based)."""

    def drag(self, drag: Drag) -> None: ...

    def pick_skill(self, slot: int, skill: str) -> bool:
        """Select list slot ``slot`` (0-based) and pick the card labelled ``skill``.

        True only once the screen shows that card picked.  For a bare 技能
        the unit's only skill card is picked; False if it has several.
        """

    def press_battle(self) -> None: ...

    def wait_after_battle(self) -> Literal["planning", "end"] | None:
        """Wait for the next planning screen or the end screen (None: timeout)."""


@dataclass(frozen=True)
class ListGlance:
    """What one screenshot of the planning screen shows without touching it."""

    team: int
    slots: int  # entries in the left list, the dead included
    out: int  # entries marked OUT


class QuickChecks(Protocol):
    """Cheap checks a FightScreen may offer besides ``read_state``."""

    def glance(self) -> ListGlance | None:
        """Team, list length and OUT marks from one screenshot; None when unsure."""

    def lit_slot(self, cell: Cell) -> int | None:
        """Hold ``cell``: the 0-based list slot that lights up.

        None when nothing lights up or it isn't clear which slot did.
        """

    def skill_of(self, slot: int) -> str | None:
        """The label of the card list slot ``slot`` has picked; None when unsure.

        Needed only on turns whose save has cards but no screenshot (charts).
        """

    def same_card(self, turn: int, slot: int) -> bool | None:
        """Whether list slot ``slot`` shows the card it has in turn ``turn``'s screenshot.

        Compares the slot's entry with the same slot of the saved screenshot
        (the order already matches the save): the portrait, which is the
        costume whose skill is up, and the round skill icon top-right of it,
        which an attack doesn't have.  What changes from turn to turn (HP
        number and bar, buff icons) is left out.  None when unsure or when
        the turn has no screenshot.  Needed on turns with a screenshot.
        """


def glance_of(state: TurnState) -> ListGlance:
    return ListGlance(state.team, len(state.order) + len(state.dead), len(state.dead))


@dataclass(frozen=True)
class FightOutcome:
    finished: bool  # reached the end screen
    turns_played: tuple[int, ...]
    stopped_at: int | None = None
    reason: str = ""
    seconds: float = 0.0  # the whole replay, battles included
    arrange_seconds: tuple[tuple[int, float], ...] = ()  # (turn, reading TURN → BATTLE)


def summons_only(characters: Collection[str]) -> Callable[[str], bool]:
    """``check_card`` for players who set the characters' cards in the costume order.

    Checks the units that aren't known characters: summons, which can't be
    set there, and names the character list doesn't have yet, which may be
    new summons.
    """
    known = frozenset(characters)
    return lambda unit: unit not in known


def minutes_and_seconds(seconds: float) -> str:
    whole = round(seconds)
    return f"{whole // 60} 分 {whole % 60} 秒"


def replay_fight(
    screen: FightScreen,
    record: FightRecord,
    *,
    last_turn: int | None = None,
    check_card: Callable[[str], bool] | None = None,
    note_unchecked: bool = False,
    solve: Callable[[int, FightRecord], tuple[FightRecord, TurnState]] | None = None,
    check: Callable[[int, TurnState], None] | None = None,
    pushes: bool = True,
    log: Callable[[str], None] = lambda message: None,
    clock: Callable[[], float] = time.monotonic,
) -> FightOutcome:
    """Play the saved turns until the end screen, or stop and hand over.

    ``last_turn`` stops after that turn's BATTLE (for tests of part of a
    fight); the fight is then left on the next planning screen.
    ``check_card`` says whose saved card to check (default: everyone's).
    ``note_unchecked`` also logs, before each BATTLE, every other unit whose
    card or 爆发 differs from the saved screenshot, without changing it.
    ``solve`` works out a turn the record lacks (fighting from screenshots
    alone, shots.py): it returns the record with that turn, and the screen
    as it left it.  ``check`` looks at the arranged turn once more before
    BATTLE; both raise TurnMismatch or ScreenReadError to stop.
    ``pushes``: the boss may move units, so every carried-over cell is held
    before BATTLE (see prepare_turn).
    The outcome carries how long it took: a replay should stay under 5
    minutes (Leo), and the battles alone take about half of that.
    """
    played: list[int] = []
    arranged: list[tuple[int, float]] = []
    carried: TurnState | None = None
    start = clock()

    def outcome(finished: bool, turn: int | None = None, reason: str = "") -> FightOutcome:
        return FightOutcome(finished, tuple(played), turn, reason, clock() - start, tuple(arranged))

    def stop(turn: int | None, reason: str) -> FightOutcome:
        log(f"停下交给玩家：{reason}")
        return outcome(False, turn, reason)

    while True:
        turn_start = clock()
        turn = _read_turn(screen, played[-1] + 2 if played else None)
        if turn is None:
            return stop(None, "读不到回合数")
        if last_turn is not None and turn > last_turn:
            return outcome(False, turn, f"只打到第 {last_turn} 回合")
        saved = record.turns.get(turn)
        solved = False
        if saved is None and solve is not None:
            try:
                record, carried = solve(turn, record)
            except (TurnMismatch, ScreenReadError) as error:
                return stop(turn, str(error))
            saved = record.turns.get(turn)
            solved = True  # ``carried`` is this turn's screen, just arranged
        if saved is None:
            return stop(turn, f"存档里没有第 {turn} 回合")
        checked = [unit for unit in saved.order if check_card is None or check_card(unit)]
        # Units changed on the chart no longer look as in the screenshot:
        # their saved card is checked by its label (Leo 2026-10-06).
        edited = record.edited.get(turn, frozenset())
        if check_card is not None:
            saved = _cards_of(saved, check_card)
        try:
            carried = prepare_turn(
                screen,
                saved,
                log,
                carried,
                by_screenshot=(
                    [unit for unit in checked if unit not in edited]
                    if turn in record.screenshots
                    else ()
                ),
                loose_bursts=()
                if check_card is None
                else [u for u in saved.order if u not in checked],
                confirmed=solved,
                pushes=pushes,
            )
            if check is not None and not edited:
                check(turn, carried)
        except (TurnMismatch, ScreenReadError) as error:
            return stop(turn, str(error))
        if note_unchecked and check_card is not None and turn in record.screenshots:
            _note_unchecked(screen, record.turns[turn], carried, checked, log)
        seconds = clock() - turn_start
        try:
            screen.press_battle()
        except ScreenReadError as error:
            return stop(turn, f"没按 BATTLE：{error}")
        played.append(turn)
        arranged.append((turn, seconds))
        log(f"第 {turn} 回合已按 BATTLE（排位 {seconds:.1f} 秒）")
        try:
            after = screen.wait_after_battle()
        except ScreenReadError as error:
            return stop(turn, f"第 {turn} 回合战斗后读不清画面：{error}")
        if after == "end":
            finished = outcome(True)
            log(f"打完，共 {minutes_and_seconds(finished.seconds)}")
            return finished
        if after != "planning":
            return stop(turn, f"第 {turn} 回合战斗后没回到排位画面")


def _read_turn(screen: FightScreen, expected: int | None) -> int | None:
    """TURN as two reads agree, unless it is the turn expected next.

    The number decides which saved turn is arranged before BATTLE, so a
    surprising one is read again rather than trusted (认不准就不按).  The
    expected one (two after the last BATTLE) costs no extra read.
    """
    first = screen.read_turn()
    if first is not None and first == expected:
        return first
    for _ in range(TURN_READS):
        again = screen.read_turn()
        if again is not None and again == first:
            return again
        first = again
    return None


def prepare_turn(
    screen: FightScreen,
    saved: TurnState,
    log: Callable[[str], None] = lambda message: None,
    carried: TurnState | None = None,
    *,
    by_screenshot: Collection[str] = (),
    loose_bursts: Collection[str] = (),
    confirmed: bool = False,
    pushes: bool = True,
) -> TurnState:
    """Make the planning screen match ``saved``; raise instead of guessing.

    ``carried`` is how the previous turn was left at BATTLE; ``confirmed``:
    it was just seen on this turn's screen (a full read, or what this returned),
    so its cells aren't held again before a drag (fighting from screenshots
    calls this up to four times a turn: 4K PC, 45 s of 206 s arranging).
    ``by_screenshot`` are the units whose card is checked against the saved
    screenshot of this turn; the others' saved cards are checked by label.
    A 爆发 above the saved level is stepped down before the cards are
    changed and after each skill picked, as it holds SP; the saved levels
    are then set last, once every card is right (2K PC 2026-10-01).
    ``loose_bursts`` are units whose card the costume order picks: their
    saved 爆发 is set where their card allows it, else only logged.
    ``pushes`` False: the battle never moves anyone, so a carried-over
    unit's cell is held only before a drag touches it, not again before
    BATTLE (Leo 2026-10-06, about 0.4 s a unit each turn).
    Returns how this turn is left, confirmed on the screen, for the next turn.
    """
    live = _arrange(screen, saved, log, carried, by_screenshot, confirmed, pushes)
    _set_preempt(screen, live, saved, log)
    return _set_bursts(screen, live, saved, log, loose_bursts)


def _set_preempt(
    screen: FightScreen, live: TurnState, saved: TurnState, log: Callable[[str], None]
) -> None:
    """Turn on the saved 「先发制人」 switches (each holds 5 SP, so before the 爆发)."""
    if not saved.preempt:
        return
    set_preempt = getattr(screen, "set_preempt", None)
    if not callable(set_preempt):
        raise ScreenReadError("这个画面没法开先发制人")
    for unit in sorted(saved.preempt, key=saved.order.index):
        skill = saved.preempt[unit]
        if unit not in live.order:
            raise TurnMismatch(f"第 {saved.turn} 回合：{unit} 不在列表里，开不了先发制人")
        if not set_preempt(live.order.index(unit), skill):
            raise TurnMismatch(f"第 {saved.turn} 回合：{unit} {skill} 的「先发制人」开不起来")
        log(f"第 {saved.turn} 回合：{unit} {skill} 开了先发制人")


def _lower_bursts(
    screen: FightScreen,
    live: TurnState,
    saved: TurnState,
    log: Callable[[str], None],
    units: Collection[str] | None = None,
) -> None:
    """Step down each 爆发 the list shows above the saved level (of ``units``, or all).

    A burst costs SP (2K PC: BURST 1 ◆6, off ◆4), so one left too high can
    hold the SP another unit's saved skill needs: the costume order's (T19,
    2026-10-01), and the one the game puts on a skill card as it lights
    (Leo's T19 screenshot: BURST 3, SP 10 → 2).  So this runs before the
    cards change and after each skill picked.  Raising waits for
    _set_bursts, once every card is right.
    """
    shown = getattr(screen, "burst_shown", None)
    set_burst = getattr(screen, "set_burst", None)
    if not saved.bursts or not callable(shown) or not callable(set_burst):
        return
    lowered = []
    for unit, level in saved.bursts.items():
        if units is not None and unit not in units:
            continue
        if unit not in live.order:
            continue  # _set_bursts stops on it
        slot = live.order.index(unit)
        now = shown(slot)
        if now is not None and now > level and set_burst(slot, level):
            lowered.append(f"{unit} {now}→{level}")
    if lowered:
        log(f"第 {saved.turn} 回合：先把爆发降下来 {'、'.join(lowered)}")


def _set_bursts(
    screen: FightScreen,
    live: TurnState,
    saved: TurnState,
    log: Callable[[str], None],
    loose: Collection[str] = (),
) -> TurnState:
    """Step each saved 爆发 level the list doesn't already show.

    A level that needs SP another unit's change frees is tried again last.
    One of a ``loose`` unit (card left to the costume order, maybe not on
    the saved skill) that can't be set is logged instead of stopping.
    """
    if not saved.bursts:
        return live
    set_burst = getattr(screen, "set_burst", None)
    if not callable(set_burst):
        raise ScreenReadError("这个画面没法调爆发")
    shown = getattr(screen, "burst_shown", None)
    pending = []
    for unit, level in saved.bursts.items():
        if unit not in live.order:
            raise TurnMismatch(f"第 {saved.turn} 回合：{unit} 不在列表里，调不了爆发")
        if not callable(shown) or shown(live.order.index(unit)) != level:
            pending.append((unit, level))
    changed = list(pending)
    for _ in range(2):
        pending = [(u, lv) for u, lv in pending if not set_burst(live.order.index(u), lv)]
        if not pending:
            break
    missed = [(u, lv) for u, lv in pending if u in loose]
    pending = [(u, lv) for u, lv in pending if u not in loose]
    if pending:
        unit, level = pending[0]
        raise TurnMismatch(f"第 {saved.turn} 回合：{unit} 的爆发调不成 {level}")
    if missed:
        log(
            f"第 {saved.turn} 回合：{'、'.join(f'{u} {lv}' for u, lv in missed)} 的爆发调不成"
            "（卡由服装顺序决定），照常打"
        )
        changed = [item for item in changed if item not in missed]
    if changed:
        log(f"第 {saved.turn} 回合：爆发调成 {'、'.join(f'{u} {lv}' for u, lv in changed)}")
    kept = {u: lv for u, lv in saved.bursts.items() if (u, lv) not in missed}
    return replace(live, bursts=kept)


def _arrange(
    screen: FightScreen,
    saved: TurnState,
    log: Callable[[str], None],
    carried: TurnState | None,
    by_screenshot: Collection[str],
    confirmed: bool = False,
    pushes: bool = True,
) -> TurnState:
    same_card = getattr(screen, "same_card", None) if by_screenshot else None
    looks = callable(same_card)
    quick = _quick_checks(screen, saved, looks)
    live: TurnState | None = None
    unconfirmed: set[str] = set()  # living units not yet seen where ``live`` says
    # Of those, the ones only carried over from the last BATTLE: with a boss
    # that never pushes they stand where they were left.
    kept: set[str] = set()
    if quick is not None and carried is not None:
        guess = _carried_over(carried, saved.turn)
        if quick.glance() == glance_of(guess):
            live, unconfirmed = guess, set() if confirmed else set(guess.order)
            kept = set() if pushes else set(unconfirmed)
    if live is None:
        live = screen.read_state(saved.turn)
    rounds = 0
    switched = False
    while True:
        try:
            # Cards are checked once the grid is right, unless the screen can
            # only tell them from a full read.
            actions = plan_turn(live, saved, skills=quick is None and not looks)
        except TurnMismatch:
            if not unconfirmed:
                raise
            live, unconfirmed = screen.read_state(saved.turn), set()  # never stop on a guess
            continue
        if actions.ready:
            held = unconfirmed - kept
            if quick is not None and held and not _confirm(quick, live, held, log):
                live, unconfirmed = screen.read_state(saved.turn), set()
                continue
            if not looks:
                _lower_bursts(screen, live, saved, log)
            else:
                matched = _match_screenshot(screen, same_card, live, saved, by_screenshot, log)
                by_label = {u: c for u, c in saved.skills.items() if u not in by_screenshot}
                if not by_label:
                    return matched
                if quick is None:
                    raise ScreenReadError(
                        f"这个画面没法照排轴核对 {'、'.join(by_label)} 的攻击或技能"
                    )
                picked = _pick_cards(screen, quick, live, replace(saved, skills=by_label), log)
                return replace(matched, skills={**matched.skills, **picked.skills})
            unchecked = [unit for unit in by_screenshot if unit not in saved.skills]
            if unchecked:
                raise ScreenReadError(
                    f"这个画面没法跟存档截图比 {'、'.join(unchecked)} 的攻击或技能"
                )
            if quick is None:
                return live  # the cards were matched with the rest
            return _pick_cards(screen, quick, live, saved, log)
        if actions.switch_team:
            if switched:
                raise TurnMismatch(f"换队后还是 TEAM{live.team}，存档要 TEAM{saved.team}")
            log(f"第 {saved.turn} 回合换成 TEAM{saved.team}")
            if not screen.switch_team(saved.team):
                raise TurnMismatch(f"换不成 TEAM{saved.team}")
            switched = True
            live, unconfirmed = screen.read_state(saved.turn), set()
            continue
        # A drag that starts on an empty cell pans the camera (top-down view,
        # seen on the 2K PC), and every cell after it is off: hold the cells
        # a drag touches first when they are only carried over.
        dragged = _dragged_units(live, actions) & unconfirmed
        if dragged:
            if not _confirm(quick, live, dragged, log):
                live, unconfirmed = screen.read_state(saved.turn), set()
                continue
            unconfirmed -= dragged
        rounds += 1
        if rounds > FIX_ROUNDS:
            raise TurnMismatch(f"第 {saved.turn} 回合调整 {FIX_ROUNDS} 次后还是和存档对不上")
        for first, second in actions.order_swaps:
            screen.swap_order(first, second)
        for drag in actions.drags:
            screen.drag(drag)
        order = apply_order_swaps(live.order, actions.order_swaps)
        for unit, skill in pick_order(actions.skill_changes):
            if not screen.pick_skill(order.index(unit), skill):
                raise TurnMismatch(f"{unit} 选不了存档里的 {skill}{_pick_problem(screen)}")
        log(
            f"第 {saved.turn} 回合：换顺序 {len(actions.order_swaps)} 次，"
            f"拖动 {len(actions.drags)} 次，换卡 {len(actions.skill_changes)} 个"
        )
        if quick is not None:
            live, moved = _after(live, actions)
            unconfirmed |= moved
            kept -= moved
        else:
            live, unconfirmed = screen.read_state(saved.turn), set()


def _pick_problem(screen: FightScreen) -> str:
    """Why the last card couldn't be picked, as the screen saw it ('' when unknown)."""
    problem = getattr(screen, "pick_problem", "")
    return f"：{problem}" if isinstance(problem, str) and problem else ""


def _cards_by_costume(
    screen: FightScreen, live: TurnState, saved: TurnState, log: Callable[[str], None]
) -> TurnState:
    """``saved`` with each costume's card label as this PC has it (Leo 2026-10-06)."""
    resolve = getattr(screen, "label_for_costume", None)
    if not saved.costumes or not callable(resolve):
        return saved
    skills = dict(saved.skills)
    for unit, costume in saved.costumes.items():
        if unit not in skills or unit not in live.order:
            continue
        label = resolve(live.order.index(unit), unit, costume)
        if label == "":
            raise TurnMismatch(
                f"{unit} 没有「{_costume_name(costume)}」这件服装的技能卡（服装技能要跟录的时候一样）"
            )
        if label and label != skills[unit]:
            log(f"第 {saved.turn} 回合：{unit} 的「{_costume_name(costume)}」在这台电脑是 {label}")
            skills[unit] = label
    return replace(saved, skills=skills)


def _costume_name(costume_id: str) -> str:
    from src.tasks.fiend_hunt.costumes import book

    costume = book().costume(costume_id)
    return costume.name if costume is not None else costume_id


def _pick_cards(
    screen: FightScreen,
    quick: QuickChecks,
    live: TurnState,
    saved: TurnState,
    log: Callable[[str], None],
) -> TurnState:
    """Pick each unit's saved card where the screen shows another one.

    Runs once the grid and the order match, so list slot = saved order.
    A skill saved with its costume is looked up by the costume (costumes.py):
    its card's row on this PC may differ from the recording's.
    """
    if not saved.skills:
        return live
    saved = _cards_by_costume(screen, live, saved, log)
    shown: dict[str, str] = {}
    for unit in saved.skills:
        if unit not in live.order:
            raise TurnMismatch(f"{unit} 不在第 {saved.turn} 回合的顺序里")
        slot = live.order.index(unit)
        card = quick.skill_of(slot)
        if card is None:
            card = quick.skill_of(slot)  # one more look before giving up
        if card is None:
            raise ScreenReadError(f"读不到 {unit} 第 {saved.turn} 回合选的卡")
        shown[unit] = card
    changes = {
        unit: wanted
        for unit, wanted in saved.skills.items()
        if not action_matches(shown[unit], wanted)
    }
    for unit, wanted in pick_order(changes):
        if not screen.pick_skill(live.order.index(unit), wanted):
            raise TurnMismatch(
                f"{unit} 选不了存档里的 {wanted}（现在是 {shown[unit]}）{_pick_problem(screen)}"
            )
        log(f"第 {saved.turn} 回合：{unit} 从 {shown[unit]} 换成 {wanted}")
        shown[unit] = wanted
        if wanted.startswith(SKILL):
            _lower_bursts(screen, live, saved, log, (unit,))
    return TurnState(live.turn, live.team, live.order, live.cells, live.dead, shown)


def _match_screenshot(
    screen: FightScreen,
    same_card: Callable[[int, int], bool | None],
    live: TurnState,
    saved: TurnState,
    units: Collection[str],
    log: Callable[[str], None],
) -> TurnState:
    """Make each of ``units`` look as in the saved screenshot of this turn.

    Runs once the grid and the order match, so list slot = saved slot.  A
    unit that looks different is tried on the saved card first when the
    save has one, then on each card in CARD_TRIES, until it looks as saved.
    The attacks are tried on every such unit before any skill, so the SP
    they free is there for the skills.  After any pick, every unit is
    compared once more, in case a pick changed someone else's card.
    """
    turn = saved.turn
    picked: dict[str, str] = {}

    def looks_as_saved(unit: str) -> bool:
        slot = live.order.index(unit)
        same = same_card(turn, slot)
        if same is None:
            same = same_card(turn, slot)  # one more look before giving up
        if same is None:
            raise ScreenReadError(f"看不清 {unit} 的头像和技能图标，没法跟存档截图比")
        return same

    def fits(unit: str, card: str) -> bool:
        if not (screen.pick_skill(live.order.index(unit), card) and looks_as_saved(unit)):
            return False
        picked[unit] = card
        log(f"第 {turn} 回合：{unit} 换成 {card}，跟存档截图一样了")
        if card.startswith(SKILL):
            _lower_bursts(screen, live, saved, log, (unit,))
        return True

    wrong = [unit for unit in units if not looks_as_saved(unit)]
    # A 爆发 above the save holds SP: step it down before any card changes,
    # except on units fix_like re-picks anyway (it sets their level).
    one_go = callable(getattr(screen, "fix_like", None))
    _lower_bursts(screen, live, saved, log, [u for u in live.order if u not in wrong or not one_go])
    # One go (Leo 2026-10-01: "一次到位"): a screen that can tell the saved
    # card from the screenshot lights it straight away, attacks first.
    pick_like = getattr(screen, "pick_like", None)
    fix_like = getattr(screen, "fix_like", None)
    clear = getattr(screen, "clear_selection", None)
    saved_attack = getattr(screen, "saved_attack", None)
    attacks_first = sorted(
        wrong,
        key=lambda unit: (
            callable(saved_attack) and saved_attack(turn, live.order.index(unit)) is not True
        ),
    )
    if callable(fix_like) and callable(clear) and callable(saved_attack):
        # Faster (Leo 2026-10-01 "調速度"): each unit's card and 爆发 in one
        # selection, straight from one unit to the next, then one look at all.
        chosen = {}
        for unit in attacks_first:
            card = fix_like(turn, live.order.index(unit), saved.bursts.get(unit))
            if card is not None:
                chosen[unit] = card
        clear()
        for unit, card in chosen.items():
            if looks_as_saved(unit):
                picked[unit] = card
                log(f"第 {turn} 回合：{unit} 一次换成 {card}，跟存档截图一样了")
        wrong = [unit for unit in wrong if unit not in picked]
    elif callable(pick_like) and callable(saved_attack):
        for unit in attacks_first:
            card = pick_like(turn, live.order.index(unit))
            if card is not None and looks_as_saved(unit):
                picked[unit] = card
                log(f"第 {turn} 回合：{unit} 一次换成 {card}，跟存档截图一样了")
                if card.startswith(SKILL):
                    _lower_bursts(screen, live, saved, log, (unit,))
        wrong = [unit for unit in wrong if unit not in picked]
    saved_action = getattr(screen, "saved_action", None)
    tries = {}
    for unit in wrong:
        tries[unit] = _card_tries(saved.skills.get(unit))
        if callable(saved_action) and saved_action(turn, live.order.index(unit)) == KNOCKBACK:
            tries[unit] = _card_tries(KNOCKBACK)
    for unit in wrong:
        if tries[unit][0] in (ATTACK, KNOCKBACK):
            fits(unit, tries[unit][0])
            tries[unit] = tries[unit][1:]
    for unit in wrong:
        if unit not in picked and not any(fits(unit, card) for card in tries[unit]):
            raise TurnMismatch(f"{unit} 试过攻击和每张技能卡，都跟第 {turn} 回合的存档截图不一样")
    if picked:
        changed = [unit for unit in units if not looks_as_saved(unit)]
        if changed:
            raise TurnMismatch(f"换卡后 {'、'.join(changed)} 又跟第 {turn} 回合的存档截图不一样")
    return TurnState(live.turn, live.team, live.order, live.cells, live.dead, picked)


def _note_unchecked(
    screen: FightScreen,
    saved: TurnState,
    live: TurnState,
    checked: Collection[str],
    log: Callable[[str], None],
) -> None:
    """Log (never fix) each unchecked unit whose card or 爆发 differs from the save.

    只看召唤物 leaves the characters to the game's auto skills, yet both
    modes should deal the same damage (Leo 2026-10-01: 151億 against the
    save's 250億), so this shows on which turn and unit they part.
    """
    same_card = getattr(screen, "same_card", None)
    shown = getattr(screen, "burst_shown", None)
    if not callable(same_card):
        return
    notes = []
    for unit in saved.order:
        if unit in checked or unit in saved.dead or unit not in live.order:
            continue
        slot = live.order.index(unit)
        same = same_card(saved.turn, slot)
        if same is None:
            notes.append(f"{unit} 看不清")
        elif not same:
            notes.append(f"{unit} 的卡跟存档截图不一样")
        level = shown(slot) if callable(shown) else None
        wanted = saved.bursts.get(unit, 0)
        if level is not None and level != wanted:
            notes.append(f"{unit} 爆发 {level}，存档 {wanted}")
    if notes:
        log(f"第 {saved.turn} 回合（只记录，没改）：{'；'.join(notes)}")
    else:
        log(f"第 {saved.turn} 回合（只记录）：角色的卡和爆发都跟存档一样")


def _card_tries(saved_card: str | None) -> tuple[str, ...]:
    if saved_card is None:
        return CARD_TRIES
    return (saved_card, *(card for card in CARD_TRIES if card != saved_card))


def _cards_of(state: TurnState, check_card: Callable[[str], bool]) -> TurnState:
    """The saved turn with only the cards to check; every unit's 爆发 is kept.

    The costume order picks the characters' skills but leaves their 爆发 to
    the player: 只看召唤物 dealt 151.0億 against 250.5億 with every card
    checked, on the same save in practice and in a real fight (2K PC
    2026-10-01), the saved levels (马莫尼勒 3, 克蕾西亚 2, 黛安娜 3, 海伦娜 3 ...)
    not being set.  A unit left on attack shows no flame (0), so a saved 0
    costs nothing there.
    """
    cards = {unit: card for unit, card in state.skills.items() if check_card(unit)}
    return TurnState(
        state.turn, state.team, state.order, state.cells, state.dead, cards, dict(state.bursts)
    )


def _quick_checks(screen: FightScreen, saved: TurnState, looks: bool) -> QuickChecks | None:
    """The screen's quick checks, if it has them for this turn.

    A screen that can't ask a list slot for its card is read in full on the
    turns whose save has cards to check by label.
    """
    checks = ["glance", "lit_slot"]
    if saved.skills and not looks:
        checks.append("skill_of")
    if all(callable(getattr(screen, check, None)) for check in checks):
        return screen  # type: ignore[return-value]
    return None


def _carried_over(previous: TurnState, turn: int) -> TurnState:
    """The previous turn as left at BATTLE, as this turn's starting guess.

    Cards are left out: the costume order picks new ones every turn.
    """
    return TurnState(turn, previous.team, previous.order, previous.cells, previous.dead)


def _after(live: TurnState, actions: TurnActions) -> tuple[TurnState, set[str]]:
    """The screen the actions should leave, and the units they moved or re-ordered."""
    order = apply_order_swaps(live.order, actions.order_swaps)
    moved = {order[slot] for swap in actions.order_swaps for slot in swap}
    cells = dict(live.cells)
    for drag in actions.drags:
        occupant = {cell: unit for unit, cell in cells.items()}
        moved |= {occupant[drag.source]} | (
            {occupant[drag.target]} if drag.target in occupant else set()
        )
        cells = apply_drags(cells, [drag])
    state = TurnState(live.turn, live.team, order, cells, live.dead, live.skills)
    return state, moved - live.dead


def _dragged_units(live: TurnState, actions: TurnActions) -> set[str]:
    """The units the drags pick up or swap with, as ``live`` places them."""
    cells = dict(live.cells)
    units: set[str] = set()
    for drag in actions.drags:
        occupant = {cell: unit for unit, cell in cells.items()}
        units |= {occupant[cell] for cell in (drag.source, drag.target) if cell in occupant}
        cells = apply_drags(cells, [drag])
    return units - live.dead


def _confirm(
    quick: QuickChecks | None,
    state: TurnState,
    units: set[str],
    log: Callable[[str], None],
) -> bool:
    """Hold each unit's cell: its own list slot must light up.

    A hold that selects nobody is tried once more before the whole screen is
    read: on the 2K PC (2026-10-01) the first hold of a turn often missed
    a unit that stood where expected, which cost a full read nearly every turn.
    """
    if quick is None:
        return False
    for slot, unit in enumerate(state.order):
        if unit not in units:
            continue
        try:
            lit = quick.lit_slot(state.cells[unit])
            if lit is None:
                lit = quick.lit_slot(state.cells[unit])
        except ScreenReadError:
            lit = None
        if lit != slot:
            log(f"第 {state.turn} 回合：{unit} 不在预计的格子上，重新读整个画面")
            return False
    return True
