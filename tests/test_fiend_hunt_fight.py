import unittest
from dataclasses import replace

from src.tasks.fiend_hunt import costumes
from src.tasks.fiend_hunt.fight import (
    ListGlance,
    ScreenReadError,
    minutes_and_seconds,
    replay_fight,
    summons_only,
)
from src.tasks.fiend_hunt.record import FightRecord, TurnState
from src.tasks.fiend_hunt.turn_plan import TurnMismatch

START = {
    "克蕾西亚": (2, 0),
    "马莫尼勒": (1, 3),
    "艾尼尔": (2, 1),
    "杰尼斯": (2, 2),
    "班塔纳": (2, 3),
}
ORDER = ("克蕾西亚", "马莫尼勒", "艾尼尔", "杰尼斯", "班塔纳")
TEAM_B = {"黛安娜": (1, 1), "魔法革新者": (0, 1), "海伦娜": (2, 3)}


class FakeBattle:
    """A planning screen that follows the game's rules (seen on the 4K PC)."""

    def __init__(
        self,
        *,
        end_after=5,
        deaths_after=None,
        preset_skills=None,
        skill_cards=None,
        ignore_drags=0,
        skill_pickable=True,
        unreadable=(),
        turn_unreadable=False,
        lost_after=None,
        teams=None,
        skill_room=None,
        burst_max=3,
        sp=None,
        burst_on_pick=None,
    ):
        self.teams = teams or {
            1: {"cells": dict(START), "order": list(ORDER)},
            2: {"cells": dict(TEAM_B), "order": ["黛安娜", "海伦娜"]},
        }
        self.team = 1
        self.turn = 1
        self.dead = set()
        self.end_after = end_after
        self.deaths_after = deaths_after or {}
        self.preset_skills = preset_skills or {}  # turn -> {unit: card} the game puts up
        self.skills = dict(self.preset_skills.get(1, {}))
        self.skill_cards = skill_cards or {}  # unit -> its skill cards, when not just 技能1
        self.skill_room = skill_room  # units that can have a skill up at once (SP)
        self.burst_max = burst_max  # highest 爆发 level ◀ ▶ reach
        # SP for the skills up: each costs 1 plus its 爆发 level (2K PC:
        # BURST 1 ◆6, off ◆4).
        self.sp = sp
        # The 爆发 the game puts on a skill card as it lights, as high as the
        # SP allows (Leo's T19 screenshot: BURST 3, SP 10 → 2).
        self.burst_on_pick = burst_on_pick
        self.bursts = {}  # unit -> 爆发 level set this turn
        self.ignore_drags = ignore_drags
        self.skill_pickable = skill_pickable
        self.unreadable = set(unreadable)
        self.turn_unreadable = turn_unreadable
        self.lost_after = lost_after
        self.actions = []  # (turn, action...)
        self.battles = {}  # turn -> state when BATTLE was pressed
        self.full_reads = []  # turn of each read_state

    def read_turn(self):
        return None if self.turn_unreadable else self.turn

    def read_state(self, turn):
        if self.turn in self.unreadable:
            raise ScreenReadError(f"第 {self.turn} 回合读不清")
        self.full_reads.append(self.turn)
        return self.snapshot()

    def snapshot(self):
        side = self.teams[self.team]
        return TurnState(
            turn=self.turn,
            team=self.team,
            order=tuple(side["order"]),
            cells=dict(side["cells"]),
            dead=self.dead & set(side["cells"]),
            skills={
                unit: skill
                for unit, skill in self.skills.items()
                if unit in side["cells"] and unit not in self.dead
            },
            bursts={unit: level for unit, level in self.bursts.items() if unit in side["order"]},
        )

    def switch_team(self, team):
        self.actions.append((self.turn, "team", team))
        if team <= self.team or team not in self.teams:
            return False
        self.team = team
        return True

    def swap_order(self, first, second):
        self.actions.append((self.turn, "order", first, second))
        order = self.teams[self.team]["order"]
        order[first], order[second] = order[second], order[first]

    def drag(self, drag):
        self.actions.append((self.turn, "drag", drag))
        if self.ignore_drags:
            self.ignore_drags -= 1
            return
        cells = self.teams[self.team]["cells"]
        occupant = {cell: unit for unit, cell in cells.items()}
        unit, other = occupant.get(drag.source), occupant.get(drag.target)
        if unit is None or unit in self.dead or other in self.dead:
            return  # tombstones don't move
        cells[unit] = drag.target
        if other is not None:
            cells[other] = drag.source

    def pick_skill(self, slot, skill):
        unit = self.teams[self.team]["order"][slot]
        self.actions.append((self.turn, "skill", unit, skill))
        if not self.skill_pickable:
            return False
        cards = self.skill_cards.get(unit, ("技能1",))
        if skill == "技能":  # a chart's bare 技能: the only skill card
            if len(cards) != 1:
                return False
            skill = cards[0]
        if skill.startswith("技能") and skill not in cards:
            return False  # the unit has no such card
        if skill.startswith("技能") and self.skill_room is not None:
            others = [u for u, card in self.skills.items() if u != unit and card.startswith("技能")]
            if len(others) >= self.skill_room:
                return False  # not enough SP
        needed = self.sp_used({**self.skills, unit: skill}, self.bursts)
        if self.sp is not None and needed > self.sp:
            return False  # not enough SP
        self.skills[unit] = skill
        if skill.startswith("技能") and self.burst_on_pick is not None:
            level = self.burst_on_pick
            while (
                self.sp is not None
                and self.sp_used(self.skills, {**self.bursts, unit: level}) > self.sp
            ):
                level -= 1
            self.bursts[unit] = level
        return True

    def sp_used(self, skills, bursts):
        up = [unit for unit, card in skills.items() if card.startswith("技能")]
        return sum(1 + bursts.get(unit, 0) for unit in up)

    def set_burst(self, slot, level):
        unit = self.teams[self.team]["order"][slot]
        self.actions.append((self.turn, "burst", unit, level))
        if not self.skills.get(unit, "").startswith("技能") or level > self.burst_max:
            return False
        needed = self.sp_used(self.skills, {**self.bursts, unit: level})
        if self.sp is not None and needed > self.sp:
            return False  # not enough SP
        self.bursts[unit] = level
        return True

    def press_battle(self):
        self.battles[self.turn] = self.snapshot()
        self.dead |= self.deaths_after.get(self.turn, set())
        order = self.teams[self.team]["order"]
        order[:] = [unit for unit in order if unit not in self.dead]

    def wait_after_battle(self):
        if self.lost_after == self.turn:
            return None
        if self.turn >= self.end_after:
            return "end"
        self.turn += 2
        self.skills = dict(self.preset_skills.get(self.turn, {}))
        self.bursts = {}
        return "planning"

    def drags_on(self, turn):
        return [action[2] for action in self.actions if action[:2] == (turn, "drag")]


class QuickBattle(FakeBattle):
    """Also offers the quick checks: a one-screenshot glance and holding a cell."""

    def __init__(
        self,
        *,
        moves_after=None,
        blurry_holds=0,
        auto_team_at=None,
        blurry_cards=0,
        saved_looks=None,
        card_looks=None,
        blurry_looks=0,
        **options,
    ):
        super().__init__(**options)
        self.moves_after = moves_after or {}  # turn -> {unit: empty cell} its battle moves to
        self.blurry_holds = blurry_holds
        self.auto_team_at = auto_team_at  # the game itself switches team on this turn
        self.blurry_cards = blurry_cards  # card reads that come back unsure
        # What each unit's list entry shows in a turn's saved screenshot, and
        # what each card looks like in the list now (by default its label).
        self.saved_looks = saved_looks or {}  # turn -> {unit: look}
        self.card_looks = card_looks or {}  # unit -> {card: look}
        self.blurry_looks = blurry_looks  # comparisons that come back unsure
        self.holds = []  # (turn, cell)
        self.card_reads = []  # (turn, unit)
        self.looks = []  # (turn, unit) compared with the saved screenshot

    def glance(self):
        if self.turn in self.unreadable:
            return None
        side = self.teams[self.team]
        dead = self.dead & set(side["cells"])
        return ListGlance(self.team, len(side["order"]) + len(dead), len(dead))

    def lit_slot(self, cell):
        self.holds.append((self.turn, cell))
        if self.blurry_holds:
            self.blurry_holds -= 1
            return None
        side = self.teams[self.team]
        for unit, at in side["cells"].items():
            if at == cell and unit not in self.dead:
                return side["order"].index(unit)
        return None

    def skill_of(self, slot):
        unit = self.teams[self.team]["order"][slot]
        self.card_reads.append((self.turn, unit))
        if self.blurry_cards:
            self.blurry_cards -= 1
            return None
        return self.skills.get(unit)

    def same_card(self, turn, slot):
        unit = self.teams[self.team]["order"][slot]
        self.looks.append((self.turn, unit))
        if self.blurry_looks:
            self.blurry_looks -= 1
            return None
        saved = self.saved_looks.get(turn, {}).get(unit)
        if saved is None:
            return None  # no screenshot of this turn
        card = self.skills.get(unit)
        return self.card_looks.get(unit, {}).get(card, card) == saved

    def burst_shown(self, slot):
        unit = self.teams[self.team]["order"][slot]
        on_skill = self.skills.get(unit, "").startswith("技能")
        return self.bursts.get(unit, 0) if on_skill else 0

    def press_battle(self):
        super().press_battle()
        self.teams[self.team]["cells"].update(self.moves_after.get(self.turn, {}))

    def wait_after_battle(self):
        after = super().wait_after_battle()
        if after == "planning" and self.turn == self.auto_team_at:
            self.team += 1
        return after

    def holds_on(self, turn):
        return [cell for number, cell in self.holds if number == turn]


def turn(number, cells, order, team=1, dead=(), skills=None):
    return TurnState(number, team, order, cells, dead=dead, skills=skills or {})


T1 = turn(1, dict(START, 克蕾西亚=(1, 0), 杰尼斯=(1, 1)), ORDER)
T3 = turn(
    3,
    dict(START, 班塔纳=(0, 3), 杰尼斯=(1, 1), 克蕾西亚=(1, 0)),
    ("克蕾西亚", "马莫尼勒", "班塔纳", "杰尼斯", "艾尼尔"),
)
T5 = turn(5, dict(START), ("马莫尼勒", "克蕾西亚", "艾尼尔", "杰尼斯", "班塔纳"))


def battle_bursts(battle):
    return [action for action in battle.actions if action[1] == "burst"]


def record_of(*turns):
    return FightRecord(turns={state.turn: state for state in turns})


def recorded(*turns):
    """A record as the tool saves it: every turn with a screenshot."""
    return FightRecord(
        turns={state.turn: state for state in turns},
        screenshots={state.turn: f"turn{state.turn:02d}.png" for state in turns},
    )


SUMMON = "魔法增幅器ET001"
SUMMON_CELLS = {
    "帕莱特": (1, 3),
    "黛安娜": (0, 3),
    "鲁": (2, 2),
    SUMMON: (0, 2),
    "海伦娜": (2, 3),
    "格兰希特": (1, 2),
}
SUMMON_ORDER = ("帕莱特", "黛安娜", "鲁", SUMMON, "海伦娜", "格兰希特")


def summon_fight(cards):
    """A team with a summon, saved with the summon's card on each turn."""
    teams = {1: {"cells": dict(SUMMON_CELLS), "order": list(SUMMON_ORDER)}}
    record = record_of(
        *(turn(number, SUMMON_CELLS, SUMMON_ORDER, skills={SUMMON: card}) for number, card in cards)
    )
    return teams, record


class ReplayFightTest(unittest.TestCase):
    Battle = FakeBattle  # a screen with read_state only

    def assert_battled_as_saved(self, battle, record):
        for number, saved in record.turns.items():
            pressed = battle.battles[number]
            self.assertEqual(saved.team, pressed.team, number)
            self.assertEqual(saved.cells, pressed.cells, number)
            self.assertEqual(saved.order, pressed.order, number)
            self.assertEqual(saved.dead, pressed.dead, number)

    def test_every_saved_turn_is_matched_before_battle(self):
        battle, record = self.Battle(), record_of(T1, T3, T5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assertEqual((1, 3, 5), outcome.turns_played)
        self.assert_battled_as_saved(battle, record)

    def test_team_switch_happens_once_on_the_saved_turn(self):
        t5 = turn(5, dict(TEAM_B, 黛安娜=(1, 2)), ("海伦娜", "黛安娜"), team=2)
        battle, record = self.Battle(), record_of(T1, T3, t5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        switches = [action for action in battle.actions if action[1] == "team"]
        self.assertEqual([(5, "team", 2)], switches)
        self.assert_battled_as_saved(battle, record)

    def test_team_switch_that_does_not_take_stops(self):
        class StuckSwitch(self.Battle):
            def switch_team(self, team):
                self.actions.append((self.turn, "team", team))
                return True  # says yes, but the grid still shows TEAM1

        t5 = turn(5, dict(TEAM_B), ("黛安娜", "海伦娜"), team=2)
        battle = StuckSwitch()

        outcome = replay_fight(battle, record_of(T1, T3, t5))

        self.assertEqual(5, outcome.stopped_at)
        self.assertEqual(1, sum(action[1] == "team" for action in battle.actions))
        self.assertNotIn(5, battle.battles)

    def test_death_the_save_does_not_have_stops_before_battle(self):
        battle = self.Battle(deaths_after={3: {"马莫尼勒"}})

        outcome = replay_fight(battle, record_of(T1, T3, T5))

        self.assertFalse(outcome.finished)
        self.assertEqual(5, outcome.stopped_at)
        self.assertIn("马莫尼勒 已阵亡", outcome.reason)
        self.assertNotIn(5, battle.battles)
        self.assertEqual([], battle.drags_on(5))

    def test_death_that_is_in_the_save_too_keeps_going(self):
        order = ("克蕾西亚", "艾尼尔", "杰尼斯", "班塔纳")
        t5 = turn(5, dict(T3.cells, 克蕾西亚=(0, 0)), order, dead=["马莫尼勒"])
        battle, record = self.Battle(deaths_after={3: {"马莫尼勒"}}), record_of(T1, T3, t5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        tombstone = T3.cells["马莫尼勒"]
        self.assertTrue(all(tombstone not in (d.source, d.target) for d in battle.drags_on(5)))

    def test_turn_missing_from_the_save_stops(self):
        battle = self.Battle()

        outcome = replay_fight(battle, record_of(T1, T5))

        self.assertEqual(3, outcome.stopped_at)
        self.assertIn("没有第 3 回合", outcome.reason)
        self.assertEqual({1}, set(battle.battles))

    def test_turn_missing_from_the_save_is_worked_out_by_the_solver(self):
        battle, asked = self.Battle(), []

        def solve(number, record):
            asked.append(number)
            return record_of(*record.turns.values(), T3), battle.read_state(number)

        outcome = replay_fight(battle, record_of(T1, T5), solve=solve)

        self.assertTrue(outcome.finished)
        self.assertEqual([3], asked)
        self.assert_battled_as_saved(battle, record_of(T1, T3, T5))

    def test_solver_that_cannot_tell_stops_before_battle(self):
        battle = self.Battle()

        def solve(number, record):
            raise TurnMismatch(f"第 {number} 回合：认不出截图列表第 2 位是谁")

        outcome = replay_fight(battle, record_of(T1, T5), solve=solve)

        self.assertEqual(3, outcome.stopped_at)
        self.assertIn("认不出", outcome.reason)
        self.assertEqual({1}, set(battle.battles))

    def test_check_before_battle_that_fails_stops(self):
        battle, checked = self.Battle(), []

        def check(number, state):
            checked.append((number, state.cells))
            if number == 3:
                raise TurnMismatch("第 3 回合排好后，杰尼斯 跟截图里那格的人不像，没按 BATTLE")

        outcome = replay_fight(battle, record_of(T1, T3, T5), check=check)

        self.assertEqual(3, outcome.stopped_at)
        self.assertEqual({1}, set(battle.battles))
        self.assertEqual([(1, T1.cells), (3, T3.cells)], checked)

    def test_drag_the_game_missed_is_redone(self):
        battle, record = self.Battle(ignore_drags=1), record_of(T1, T3, T5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        self.assertEqual(3, len(battle.drags_on(1)))  # 2 needed + 1 redone

    def test_fix_that_never_takes_stops_without_battle(self):
        battle = self.Battle(ignore_drags=100)

        outcome = replay_fight(battle, record_of(T1, T3, T5))

        self.assertEqual(1, outcome.stopped_at)
        self.assertIn("对不上", outcome.reason)
        self.assertEqual({}, battle.battles)

    def test_skill_card_is_picked_when_it_differs(self):
        t1 = turn(1, T1.cells, ORDER, skills={"克蕾西亚": "2", "马莫尼勒": "1"})
        battle = self.Battle(preset_skills={1: {"克蕾西亚": "1", "马莫尼勒": "1"}})

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertTrue(outcome.finished)
        picks = [action for action in battle.actions if action[1] == "skill"]
        self.assertEqual([(1, "skill", "克蕾西亚", "2")], picks)
        self.assertEqual("2", battle.battles[1].skills["克蕾西亚"])

    def test_skill_that_cannot_be_picked_stops(self):
        t1 = turn(1, T1.cells, ORDER, skills={"克蕾西亚": "2"})
        battle = self.Battle(preset_skills={1: {"克蕾西亚": "1"}}, skill_pickable=False)

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertEqual(1, outcome.stopped_at)
        self.assertEqual({}, battle.battles)

    def test_saved_burst_level_is_set_before_battle(self):
        # 2K PC 2026-10-01: 克蕾西亚's skill must be BURST 2; the costume order had 3.
        t1 = replace(turn(1, T1.cells, ORDER, skills={"克蕾西亚": "技能1"}), bursts={"克蕾西亚": 2})
        battle = self.Battle(preset_skills={1: {"克蕾西亚": "技能1"}})
        battle.bursts = {"克蕾西亚": 3}

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertTrue(outcome.finished)
        self.assertEqual({"克蕾西亚": 2}, battle.battles[1].bursts)
        self.assertEqual([(1, "burst", "克蕾西亚", 2)], battle_bursts(battle))

    def test_burst_the_save_has_off_is_turned_off(self):
        # 2K PC 2026-10-01: a scrambled costume order left 帕莱特 on BURST 1
        # where the save has her skill without one; the SP ran out at T19.
        t1 = replace(turn(1, T1.cells, ORDER, skills={"克蕾西亚": "技能1"}), bursts={"克蕾西亚": 0})
        battle = self.Battle(preset_skills={1: {"克蕾西亚": "技能1"}})
        battle.bursts = {"克蕾西亚": 1}

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertTrue(outcome.finished)
        self.assertEqual({"克蕾西亚": 0}, battle.battles[1].bursts)
        self.assertEqual([(1, "burst", "克蕾西亚", 0)], battle_bursts(battle))

    def test_burst_that_cannot_be_set_stops_before_battle(self):
        t1 = replace(turn(1, T1.cells, ORDER, skills={"克蕾西亚": "技能1"}), bursts={"克蕾西亚": 3})
        battle = self.Battle(preset_skills={1: {"克蕾西亚": "技能1"}}, burst_max=2)

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertEqual(1, outcome.stopped_at)
        self.assertIn("爆发", outcome.reason)
        self.assertEqual({}, battle.battles)

    def test_every_saved_burst_is_set_when_only_the_summons_card_is_checked(self):
        # The costume order sets the characters' skills, not their 爆发:
        # 只看召唤物 without them dealt 151.0億 against 250.5億 (2K PC 2026-10-01).
        characters = [unit for unit in SUMMON_ORDER if unit != SUMMON]
        teams = {1: {"cells": dict(SUMMON_CELLS), "order": list(SUMMON_ORDER)}}
        skills = {"帕莱特": "技能1", SUMMON: "技能1"}
        t1 = replace(
            turn(1, SUMMON_CELLS, SUMMON_ORDER, skills=skills), bursts={"帕莱特": 3, SUMMON: 2}
        )
        battle = self.Battle(teams=teams, end_after=1, preset_skills={1: skills})

        outcome = replay_fight(battle, record_of(t1), check_card=summons_only(characters))

        self.assertTrue(outcome.finished)
        self.assertEqual(
            sorted([(1, "burst", "帕莱特", 3), (1, "burst", SUMMON, 2)]),
            sorted(battle_bursts(battle)),
        )

    def test_summon_is_switched_to_attack_on_the_saved_turn(self):
        # Leo 2026-09-30: on the last turn the summon attacks, but the game had
        # put up its skill again; a summon can't be set in the costume order.
        teams, record = summon_fight(((1, "技能1"), (3, "技能1"), (5, "攻击")))
        battle = self.Battle(teams=teams, preset_skills={n: {SUMMON: "技能1"} for n in (1, 3, 5)})

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        picks = [action for action in battle.actions if action[1] == "skill"]
        self.assertEqual([(5, "skill", SUMMON, "攻击")], picks)
        self.assertEqual("攻击", battle.battles[5].skills[SUMMON])

    def test_only_the_summon_is_checked_when_the_player_asks(self):
        # The characters' cards come from the costume order: a saved card that
        # differs is left alone, only the summon's is fixed (Leo, 2026-09-30).
        characters = [unit for unit in SUMMON_ORDER if unit != SUMMON]
        teams = {1: {"cells": dict(SUMMON_CELLS), "order": list(SUMMON_ORDER)}}
        saved = {unit: "技能1" for unit in SUMMON_ORDER} | {SUMMON: "攻击"}
        record = record_of(
            turn(1, SUMMON_CELLS, SUMMON_ORDER, skills=saved),
            turn(3, SUMMON_CELLS, SUMMON_ORDER, skills=saved),
        )
        game = {unit: "攻击" for unit in characters} | {SUMMON: "技能1"}
        battle = self.Battle(teams=teams, end_after=3, preset_skills={1: game, 3: game})

        outcome = replay_fight(battle, record, check_card=summons_only(characters))

        self.assertTrue(outcome.finished)
        picks = [action for action in battle.actions if action[1] == "skill"]
        self.assertEqual([(1, "skill", SUMMON, "攻击"), (3, "skill", SUMMON, "攻击")], picks)
        self.assertEqual("攻击", battle.battles[1].skills["帕莱特"])

    def test_attack_is_picked_before_a_skill(self):
        # An attack frees the SP another unit's skill may need.
        t1 = turn(1, T1.cells, ORDER, skills={"克蕾西亚": "技能1", "马莫尼勒": "攻击"})
        battle = self.Battle(preset_skills={1: {"克蕾西亚": "攻击", "马莫尼勒": "技能1"}})

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertTrue(outcome.finished)
        picks = [action[2:] for action in battle.actions if action[1] == "skill"]
        self.assertEqual([("马莫尼勒", "攻击"), ("克蕾西亚", "技能1")], picks)

    def test_chart_skill_accepts_whichever_skill_card_is_up(self):
        t1 = turn(1, T1.cells, ORDER, skills={"马莫尼勒": "技能"})
        battle = self.Battle(preset_skills={1: {"马莫尼勒": "技能2"}})

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertTrue(outcome.finished)
        self.assertEqual([], [action for action in battle.actions if action[1] == "skill"])

    def test_chart_skill_on_a_unit_with_several_skill_cards_stops(self):
        t1 = turn(1, T1.cells, ORDER, skills={"马莫尼勒": "技能"})
        battle = self.Battle(
            preset_skills={1: {"马莫尼勒": "攻击"}}, skill_cards={"马莫尼勒": ("技能1", "技能2")}
        )

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertEqual(1, outcome.stopped_at)
        self.assertIn("马莫尼勒", outcome.reason)
        self.assertEqual({}, battle.battles)

    def test_unreadable_screen_stops(self):
        battle = self.Battle(unreadable={3})

        outcome = replay_fight(battle, record_of(T1, T3, T5))

        self.assertEqual(3, outcome.stopped_at)
        self.assertIn("读不清", outcome.reason)

    def test_unreadable_turn_number_stops(self):
        outcome = replay_fight(self.Battle(turn_unreadable=True), record_of(T1, T3, T5))
        self.assertFalse(outcome.finished)
        self.assertIsNone(outcome.stopped_at)

    def test_no_planning_screen_after_battle_stops(self):
        battle = self.Battle(lost_after=1)

        outcome = replay_fight(battle, record_of(T1, T3, T5))

        self.assertEqual(1, outcome.stopped_at)
        self.assertEqual((1,), outcome.turns_played)

    def test_last_turn_leaves_the_next_turn_alone(self):
        battle = self.Battle()

        outcome = replay_fight(battle, record_of(T1, T3, T5), last_turn=3)

        self.assertFalse(outcome.finished)
        self.assertEqual((1, 3), outcome.turns_played)
        self.assertEqual(5, outcome.stopped_at)
        self.assertEqual([], [action for action in battle.actions if action[0] == 5])

    def test_battle_that_cannot_be_pressed_stops(self):
        class NoBattle(self.Battle):
            def press_battle(self):
                if self.turn == 3:
                    raise ScreenReadError("按 BATTLE 前画面不对")
                super().press_battle()

        battle = NoBattle()

        outcome = replay_fight(battle, record_of(T1, T3, T5))

        self.assertEqual(3, outcome.stopped_at)
        self.assertIn("画面不对", outcome.reason)
        self.assertEqual((1,), outcome.turns_played)

    def test_unreadable_screen_after_battle_stops(self):
        class Blurry(self.Battle):
            def wait_after_battle(self):
                raise ScreenReadError("读不清")

        outcome = replay_fight(Blurry(), record_of(T1, T3, T5))

        self.assertEqual(1, outcome.stopped_at)
        self.assertEqual((1,), outcome.turns_played)


class QuickReplayFightTest(ReplayFightTest):
    """The same rules hold when the screen also offers the quick checks."""

    Battle = QuickBattle

    def test_only_the_first_turn_is_read_in_full(self):
        battle, record = QuickBattle(), record_of(T1, T3, T5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        self.assertEqual([1], battle.full_reads)
        self.assertEqual(2, len(battle.holds_on(1)))  # the two units T1 dragged
        # the unit T3 drags, before the drag, then every living unit before BATTLE
        self.assertEqual(6, len(battle.holds_on(3)))
        self.assertEqual(8, len(battle.holds_on(5)))  # T5 drags three units

    def test_unit_the_battle_moved_is_caught_before_battle(self):
        # T3 neither drags nor re-orders 马莫尼勒, so only the check before BATTLE sees it.
        battle = QuickBattle(moves_after={1: {"马莫尼勒": (0, 0)}})
        record = record_of(T1, T3, T5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        self.assertEqual([1, 3], battle.full_reads)

    def test_unit_the_battle_moved_is_found_before_dragging_it(self):
        # T3 drags 班塔纳 from (2, 3); the T1 battle moved it, so (2, 3) is
        # empty and a drag from there would pan the camera (2K PC, T23).
        class Panning(QuickBattle):
            empty_drags = []

            def drag(self, drag):
                if drag.source not in self.teams[self.team]["cells"].values():
                    self.empty_drags.append((self.turn, drag))
                super().drag(drag)

        battle = Panning(moves_after={1: {"班塔纳": (0, 0)}})
        record = record_of(T1, T3, T5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        self.assertEqual([], battle.empty_drags)
        self.assertEqual([1, 3], battle.full_reads)

    def test_boss_that_never_pushes_skips_the_holds_of_a_turn_left_as_is(self):
        # Leo 2026-10-06: his TEAM1 never moves, and few bosses push anyone.
        t5 = turn(5, dict(T3.cells), T3.order)
        record = record_of(T1, T3, t5)
        careful, quick = QuickBattle(), QuickBattle()

        replay_fight(careful, record)
        outcome = replay_fight(quick, record, pushes=False)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(quick, record)
        self.assertEqual([1], quick.full_reads)
        self.assertEqual(5, len(careful.holds_on(5)))
        self.assertEqual([], quick.holds_on(5))

    def test_boss_that_never_pushes_still_holds_what_the_tool_moves(self):
        battle, record = QuickBattle(), record_of(T1, T3, T5)

        outcome = replay_fight(battle, record, pushes=False)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        # T3 drags 班塔纳 (held before and after) and re-orders one more unit
        self.assertEqual([(2, 3), (0, 3), (2, 1)], battle.holds_on(3))

    def test_a_turn_number_that_isnt_the_next_is_read_again(self):
        # The number picks the saved turn to arrange: never trusted on one look.
        class Misread(self.Battle):
            misreads = {3: [5]}  # TURN 3 read as 5 once

            def read_turn(self):
                wrong = self.misreads.get(self.turn)
                if wrong:
                    return wrong.pop()
                return super().read_turn()

        battle, record = Misread(), record_of(T1, T3, T5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)

    def test_turn_numbers_that_never_agree_stop_the_fight(self):
        class Flicker(self.Battle):
            reads = 0

            def read_turn(self):
                if self.turn != 3:
                    return super().read_turn()
                self.reads += 1
                return 3 + 2 * (self.reads % 2)  # 5, 3, 5, 3 ...

        outcome = replay_fight(Flicker(), record_of(T1, T3, T5))

        self.assertFalse(outcome.finished)
        self.assertEqual("读不到回合数", outcome.reason)
        self.assertEqual((1,), outcome.turns_played)

    def test_burst_above_the_save_is_lowered_before_a_skill_needs_its_sp(self):
        # 2K PC 2026-10-01, T19: the scrambled costume order left 帕莱特 on
        # BURST 1 where the save has her skill without one, and that SP was
        # missing for 格兰希特's saved skill.
        skills = {"克蕾西亚": "技能1", "马莫尼勒": "技能1"}
        t1 = replace(turn(1, T1.cells, ORDER, skills=skills), bursts={"克蕾西亚": 0, "马莫尼勒": 0})
        battle = self.Battle(preset_skills={1: {"克蕾西亚": "技能1", "马莫尼勒": "攻击"}}, sp=2)
        battle.bursts = {"克蕾西亚": 1}

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertTrue(outcome.finished)
        self.assertEqual(skills, battle.battles[1].skills)
        self.assertEqual({"克蕾西亚": 0}, battle.battles[1].bursts)
        cards = [action[1:] for action in battle.actions if action[1] in ("burst", "skill")]
        self.assertEqual([("burst", "克蕾西亚", 0), ("skill", "马莫尼勒", "技能1")], cards)

    def test_burst_the_game_puts_on_a_picked_card_is_lowered_before_the_next_pick(self):
        skills = {"克蕾西亚": "技能1", "马莫尼勒": "技能1"}
        t1 = replace(turn(1, T1.cells, ORDER, skills=skills), bursts={"克蕾西亚": 0, "马莫尼勒": 0})
        battle = self.Battle(
            preset_skills={1: {"克蕾西亚": "攻击", "马莫尼勒": "攻击"}}, sp=2, burst_on_pick=3
        )

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertTrue(outcome.finished)
        self.assertEqual(skills, battle.battles[1].skills)
        self.assertEqual({"克蕾西亚": 0, "马莫尼勒": 0}, battle.battles[1].bursts)

    def test_burst_the_list_already_shows_is_left_alone(self):
        t1 = replace(turn(1, T1.cells, ORDER, skills={"克蕾西亚": "技能1"}), bursts={"克蕾西亚": 2})
        battle = self.Battle(preset_skills={1: {"克蕾西亚": "技能1"}})
        battle.bursts = {"克蕾西亚": 2}

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertTrue(outcome.finished)
        self.assertEqual([], battle_bursts(battle))
        self.assertEqual({"克蕾西亚": 2}, battle.battles[1].bursts)

    def test_hold_unclear_twice_reads_the_whole_screen(self):
        battle, record = QuickBattle(blurry_holds=2), record_of(T1, T3, T5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        self.assertEqual([1, 1], battle.full_reads)

    def test_hold_unclear_once_is_held_again(self):
        # 2K PC 2026-10-01: the first hold of a turn often selected nobody.
        battle, record = QuickBattle(blurry_holds=1), record_of(T1, T3, T5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        self.assertEqual([1], battle.full_reads)

    def test_hold_that_fails_to_read_reads_the_whole_screen(self):
        class Shaky(QuickBattle):
            failed = False

            def lit_slot(self, cell):
                if not self.failed:
                    self.failed = True
                    raise ScreenReadError("同时选中了 2 个角色")
                return super().lit_slot(cell)

        battle, record = Shaky(), record_of(T1, T3, T5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        self.assertEqual([1, 1], battle.full_reads)

    def test_team_the_game_switched_by_itself_is_seen_at_a_glance(self):
        t5 = turn(5, dict(TEAM_B, 黛安娜=(1, 2)), ("海伦娜", "黛安娜"), team=2)
        battle, record = QuickBattle(auto_team_at=5), record_of(T1, T3, t5)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assert_battled_as_saved(battle, record)
        self.assertEqual([1, 5], battle.full_reads)
        self.assertEqual([], [action for action in battle.actions if action[1] == "team"])

    def test_death_at_a_glance_is_read_in_full_before_stopping(self):
        battle = QuickBattle(deaths_after={3: {"马莫尼勒"}})

        outcome = replay_fight(battle, record_of(T1, T3, T5))

        self.assertEqual(5, outcome.stopped_at)
        self.assertEqual([1, 5], battle.full_reads)
        self.assertEqual([], battle.holds_on(5))

    def test_saved_death_that_did_not_happen_is_read_in_full_before_stopping(self):
        order = ("克蕾西亚", "艾尼尔", "杰尼斯", "班塔纳")
        t5 = turn(5, dict(T3.cells), order, dead=["马莫尼勒"])
        battle = QuickBattle()

        outcome = replay_fight(battle, record_of(T1, T3, t5))

        self.assertEqual(5, outcome.stopped_at)
        self.assertIn("马莫尼勒 还活着", outcome.reason)
        self.assertEqual([1, 5], battle.full_reads)

    def test_saved_cards_are_checked_without_reading_in_full(self):
        skills = {1: {"克蕾西亚": "1"}, 3: {"克蕾西亚": "1"}, 5: {"克蕾西亚": "1"}}
        record = record_of(
            *(turn(t.turn, t.cells, t.order, skills={"克蕾西亚": "1"}) for t in (T1, T3, T5))
        )
        battle = QuickBattle(preset_skills=skills)

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assertEqual([1], battle.full_reads)
        self.assertEqual([(1, "克蕾西亚"), (3, "克蕾西亚"), (5, "克蕾西亚")], battle.card_reads)

    def test_summon_card_is_one_look_a_turn(self):
        teams, record = summon_fight(((1, "技能1"), (3, "技能1"), (5, "攻击")))
        battle = QuickBattle(teams=teams, preset_skills={n: {SUMMON: "技能1"} for n in (1, 3, 5)})

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assertEqual([1], battle.full_reads)
        self.assertEqual([(1, SUMMON), (3, SUMMON), (5, SUMMON)], battle.card_reads)

    def test_screen_without_card_looks_reads_card_turns_in_full(self):
        class NoCardLooks(QuickBattle):
            skill_of = None

        teams = {1: {"cells": dict(SUMMON_CELLS), "order": list(SUMMON_ORDER)}}
        record = record_of(
            turn(1, SUMMON_CELLS, SUMMON_ORDER),
            turn(3, SUMMON_CELLS, SUMMON_ORDER),
            turn(5, SUMMON_CELLS, SUMMON_ORDER, skills={SUMMON: "攻击"}),
        )
        battle = NoCardLooks(teams=teams, preset_skills={n: {SUMMON: "技能1"} for n in (1, 3, 5)})

        outcome = replay_fight(battle, record)

        self.assertTrue(outcome.finished)
        self.assertEqual([1, 5, 5], battle.full_reads)  # T5: read, pick, read again
        self.assertEqual("攻击", battle.battles[5].skills[SUMMON])

    def test_only_the_summon_card_is_looked_at_when_the_player_asks(self):
        characters = [unit for unit in SUMMON_ORDER if unit != SUMMON]
        teams, record = summon_fight(((1, "技能1"), (3, "攻击")))
        record = record_of(
            *(
                turn(state.turn, state.cells, state.order, skills=dict(state.skills, 鲁="技能2"))
                for state in record.turns.values()
            )
        )
        battle = QuickBattle(
            teams=teams,
            end_after=3,
            preset_skills={n: {SUMMON: "技能1", "鲁": "技能1"} for n in (1, 3)},
        )

        outcome = replay_fight(battle, record, check_card=summons_only(characters))

        self.assertTrue(outcome.finished)
        self.assertEqual([(1, SUMMON), (3, SUMMON)], battle.card_reads)

    def test_card_read_once_unsure_is_looked_at_again(self):
        t1 = turn(1, T1.cells, ORDER, skills={"马莫尼勒": "技能1"})
        battle = QuickBattle(preset_skills={1: {"马莫尼勒": "技能1"}}, blurry_cards=1)

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertTrue(outcome.finished)
        self.assertEqual([(1, "马莫尼勒"), (1, "马莫尼勒")], battle.card_reads)

    def test_card_that_cannot_be_read_stops_before_battle(self):
        t1 = turn(1, T1.cells, ORDER, skills={"马莫尼勒": "技能1"})
        battle = QuickBattle(preset_skills={1: {"马莫尼勒": "技能1"}}, blurry_cards=2)

        outcome = replay_fight(battle, record_of(t1, T3, T5))

        self.assertEqual(1, outcome.stopped_at)
        self.assertIn("读不到 马莫尼勒", outcome.reason)
        self.assertEqual({}, battle.battles)


class ScreenshotCardsTest(unittest.TestCase):
    """A recorded turn's cards are checked against its screenshot (Leo's idea).

    The list portrait shows the costume whose skill is up, with a round
    skill icon; an attack has none.  So one look at the list tells whether
    a unit's card is the saved one, without selecting anybody.
    """

    CHARACTERS = [unit for unit in SUMMON_ORDER if unit != SUMMON]

    def summon_battle(self, saved_cards, game_cards, battle=QuickBattle, **options):
        """The summon saved on ``saved_cards[turn]``; the game puts up ``game_cards``."""
        teams = {1: {"cells": dict(SUMMON_CELLS), "order": list(SUMMON_ORDER)}}
        record = recorded(*(turn(number, SUMMON_CELLS, SUMMON_ORDER) for number in saved_cards))
        battle = battle(
            teams=teams,
            end_after=max(saved_cards),
            saved_looks={number: {SUMMON: card} for number, card in saved_cards.items()},
            preset_skills={number: {SUMMON: card} for number, card in game_cards.items()},
            **options,
        )
        return battle, record

    def picks(self, battle):
        return [(action[0], *action[2:]) for action in battle.actions if action[1] == "skill"]

    def test_card_that_looks_as_saved_is_left_alone(self):
        battle, record = self.summon_battle({1: "技能1", 3: "技能1"}, {1: "技能1", 3: "技能1"})

        outcome = replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertTrue(outcome.finished)
        self.assertEqual([], self.picks(battle))
        self.assertEqual([(1, SUMMON), (3, SUMMON)], battle.looks)
        self.assertEqual([], battle.card_reads)  # nobody selected to read a card
        self.assertEqual([1], battle.full_reads)

    def test_summon_that_looks_different_is_switched_to_attack(self):
        # Leo 2026-09-30: on the last turn the summon attacks, but the game
        # put up its skill again; a summon can't be set in the costume order.
        battle, record = self.summon_battle(
            {1: "技能1", 3: "技能1", 5: "攻击"}, {1: "技能1", 3: "技能1", 5: "技能1"}
        )
        lines = []

        outcome = replay_fight(
            battle, record, check_card=summons_only(self.CHARACTERS), log=lines.append
        )

        self.assertTrue(outcome.finished)
        self.assertEqual([(5, SUMMON, "攻击")], self.picks(battle))
        self.assertEqual("攻击", battle.battles[5].skills[SUMMON])
        self.assertIn(f"第 5 回合：{SUMMON} 换成 攻击，跟存档截图一样了", lines)

    def test_unit_changed_on_the_chart_follows_its_label_not_the_screenshot(self):
        # Leo 2026-10-06: after recording, the player sets the summon to attack
        # on turn 1 in the chart; its screenshot still shows the skill.
        battle, record = self.summon_battle({1: "技能1", 3: "技能1"}, {1: "技能1", 3: "技能1"})
        state = turn(1, SUMMON_CELLS, SUMMON_ORDER, skills={SUMMON: "攻击"})
        record = FightRecord(
            turns={**record.turns, 1: state},
            screenshots=dict(record.screenshots),
            edited={1: {SUMMON}},
        )
        lines = []

        outcome = replay_fight(
            battle, record, check_card=summons_only(self.CHARACTERS), log=lines.append
        )

        self.assertTrue(outcome.finished)
        self.assertEqual([(1, SUMMON, "攻击")], self.picks(battle))
        self.assertNotIn((1, SUMMON), battle.looks)  # not compared with turn 1's screenshot
        self.assertIn((1, SUMMON), battle.card_reads)
        self.assertIn((3, SUMMON), battle.looks)  # turn 3 wasn't changed

    def test_edited_and_unchanged_units_are_both_checked(self):
        # Everyone checked: the edited summon by label, the others by screenshot.
        battle, record = self.summon_battle({1: "技能1"}, {1: "技能1"})
        battle.saved_looks[1].update({unit: None for unit in self.CHARACTERS})
        battle.saved_looks[1].update({"帕莱特": "攻击"})
        state = turn(1, SUMMON_CELLS, SUMMON_ORDER, skills={SUMMON: "攻击"})
        record = FightRecord(
            turns={1: state}, screenshots=dict(record.screenshots), edited={1: {SUMMON}}
        )

        outcome = replay_fight(battle, record, check_card=lambda unit: unit in ("帕莱特", SUMMON))

        self.assertTrue(outcome.finished)
        self.assertEqual("攻击", battle.battles[1].skills[SUMMON])
        self.assertIn((1, "帕莱特"), battle.looks)
        self.assertNotIn((1, SUMMON), battle.looks)

    class OneGo(QuickBattle):
        """Also finds the saved card from its icon in the card column."""

        def saved_attack(self, turn, slot):
            unit = self.teams[self.team]["order"][slot]
            return self.saved_looks.get(turn, {}).get(unit) == "攻击"

        def pick_like(self, turn, slot):
            unit = self.teams[self.team]["order"][slot]
            card = self.saved_looks.get(turn, {}).get(unit)
            return card if card is not None and self.pick_skill(slot, card) else None

    def test_saved_card_is_picked_in_one_go(self):
        # Leo 2026-10-01: "一次到位" instead of trying the cards one by one.
        battle, record = self.summon_battle(
            {1: "技能3"},
            {1: "技能1"},
            battle=self.OneGo,
            skill_cards={SUMMON: ("技能1", "技能2", "技能3")},
        )
        lines = []

        outcome = replay_fight(
            battle, record, check_card=summons_only(self.CHARACTERS), log=lines.append
        )

        self.assertTrue(outcome.finished)
        self.assertEqual([(1, SUMMON, "技能3")], self.picks(battle))
        self.assertIn(f"第 1 回合：{SUMMON} 一次换成 技能3，跟存档截图一样了", lines)

    def test_card_and_burst_are_fixed_in_one_selection_then_looked_at_once(self):
        # Leo 2026-10-01 "調速度": no clear and look between units.
        class Chained(self.OneGo):
            cleared = 0

            def fix_like(self, turn, slot, burst=None):
                card = self.pick_like(turn, slot)
                if card is not None and burst is not None and card != "攻击":
                    self.set_burst(slot, burst)
                return card

            def clear_selection(self):
                self.cleared += 1

        battle, record = self.summon_battle(
            {1: "技能3"},
            {1: "技能1"},
            battle=Chained,
            skill_cards={SUMMON: ("技能1", "技能2", "技能3")},
        )
        record.turns[1] = replace(record.turns[1], bursts={SUMMON: 2})
        lines = []

        outcome = replay_fight(
            battle, record, check_card=summons_only(self.CHARACTERS), log=lines.append
        )

        self.assertTrue(outcome.finished, outcome.reason)
        self.assertEqual([(1, SUMMON, "技能3")], self.picks(battle))
        self.assertEqual({SUMMON: 2}, battle.battles[1].bursts)
        self.assertEqual(1, battle.cleared)
        self.assertIn(f"第 1 回合：{SUMMON} 一次换成 技能3，跟存档截图一样了", lines)

    def test_card_not_told_in_one_go_is_found_by_trying(self):
        class Unsure(self.OneGo):
            def pick_like(self, turn, slot):
                return None

        battle, record = self.summon_battle(
            {1: "技能3"},
            {1: "技能1"},
            battle=Unsure,
            skill_cards={SUMMON: ("技能1", "技能2", "技能3")},
        )

        outcome = replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertTrue(outcome.finished)
        self.assertEqual("技能3", battle.battles[1].skills[SUMMON])

    def test_only_the_summon_is_compared_when_the_player_asks(self):
        battle, record = self.summon_battle({1: "技能1"}, {1: "技能1"})

        replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertEqual([(1, SUMMON)], battle.looks)

    def test_characters_that_differ_are_only_logged_when_asked(self):
        # Leo 2026-10-01: 只看召唤物 dealt 151億 against the save's 250億;
        # log where the characters' cards and 爆发 part from the save.
        battle, record = self.summon_battle({1: "技能1", 3: "技能1"}, {1: "技能1", 3: "技能1"})
        other, steady = (unit for unit in self.CHARACTERS[:2])
        battle.saved_looks[3][other] = "技能2"
        battle.saved_looks[3][steady] = battle.skills.get(steady)
        record.turns[3] = replace(record.turns[3], bursts={steady: 1})
        lines = []

        outcome = replay_fight(
            battle,
            record,
            check_card=summons_only(self.CHARACTERS),
            note_unchecked=True,
            log=lines.append,
        )

        self.assertTrue(outcome.finished, outcome.reason)
        self.assertEqual([], self.picks(battle))  # nothing changed
        note = next(line for line in lines if line.startswith("第 3 回合（只记录"))
        self.assertIn(f"{other} 的卡跟存档截图不一样", note)
        self.assertIn(f"{steady} 爆发 0，存档 1", note)

    def test_every_unit_is_compared_by_default(self):
        cards = {unit: "攻击" for unit in SUMMON_ORDER}
        teams = {1: {"cells": dict(SUMMON_CELLS), "order": list(SUMMON_ORDER)}}
        battle = QuickBattle(
            teams=teams, end_after=1, saved_looks={1: cards}, preset_skills={1: cards}
        )

        outcome = replay_fight(battle, recorded(turn(1, SUMMON_CELLS, SUMMON_ORDER)))

        self.assertTrue(outcome.finished)
        self.assertEqual([(1, unit) for unit in SUMMON_ORDER], battle.looks)

    def test_saved_card_is_tried_first(self):
        t1 = turn(1, T1.cells, ORDER, skills={"马莫尼勒": "技能2"})
        battle = QuickBattle(
            end_after=1,
            saved_looks={1: {"马莫尼勒": "技能2"}},
            preset_skills={1: {"马莫尼勒": "技能1"}},
            skill_cards={"马莫尼勒": ("技能1", "技能2")},
        )

        outcome = replay_fight(battle, recorded(t1), check_card=lambda unit: unit == "马莫尼勒")

        self.assertTrue(outcome.finished)
        self.assertEqual([(1, "马莫尼勒", "技能2")], self.picks(battle))

    def test_card_is_found_by_its_look_after_the_costume_order_changed(self):
        # Recorded with costume B's skill as card 2; since then the costume
        # order was changed and B's skill is card 1.
        t1 = turn(1, T1.cells, ORDER, skills={"马莫尼勒": "技能2"})
        battle = QuickBattle(
            end_after=1,
            saved_looks={1: {"马莫尼勒": "B"}},
            card_looks={"马莫尼勒": {"技能1": "B", "技能2": "A"}},
            preset_skills={1: {"马莫尼勒": "技能2"}},
            skill_cards={"马莫尼勒": ("技能1", "技能2")},
        )

        outcome = replay_fight(battle, recorded(t1), check_card=lambda unit: unit == "马莫尼勒")

        self.assertTrue(outcome.finished)
        self.assertEqual(
            [(1, "马莫尼勒", "技能2"), (1, "马莫尼勒", "攻击"), (1, "马莫尼勒", "技能1")],
            self.picks(battle),
        )
        self.assertEqual("技能1", battle.battles[1].skills["马莫尼勒"])

    def test_attacks_are_tried_on_every_unit_before_any_skill(self):
        # Only one unit can have a skill up (SP): 马莫尼勒 has to drop hers
        # before 克蕾西亚, above her in the list, can take one.
        battle = QuickBattle(
            end_after=1,
            saved_looks={1: {"克蕾西亚": "技能1", "马莫尼勒": "攻击"}},
            preset_skills={1: {"克蕾西亚": "攻击", "马莫尼勒": "技能1"}},
            skill_room=1,
        )

        outcome = replay_fight(battle, recorded(T1), check_card=lambda unit: unit in ORDER[:2])

        self.assertTrue(outcome.finished)
        self.assertEqual(
            [(1, "克蕾西亚", "攻击"), (1, "马莫尼勒", "攻击"), (1, "克蕾西亚", "技能1")],
            self.picks(battle),
        )

    def test_burst_above_the_save_is_lowered_before_the_cards_change(self):
        # 2K PC 2026-10-01, T19: 帕莱特 on the saved costume but BURST 1
        # where the save has none; 格兰希特's saved skill needs that SP.
        saved = {"帕莱特": "技能1", "格兰希特": "技能1"}
        teams = {1: {"cells": dict(SUMMON_CELLS), "order": list(SUMMON_ORDER)}}
        t1 = replace(turn(1, SUMMON_CELLS, SUMMON_ORDER), bursts={"帕莱特": 0, "格兰希特": 0})
        battle = QuickBattle(
            teams=teams,
            end_after=1,
            saved_looks={1: saved},
            preset_skills={1: {"帕莱特": "技能1", "格兰希特": "攻击"}},
            sp=2,
        )
        battle.bursts = {"帕莱特": 1}
        lines = []

        outcome = replay_fight(
            battle, recorded(t1), check_card=lambda unit: unit in saved, log=lines.append
        )

        self.assertTrue(outcome.finished)
        self.assertEqual("技能1", battle.battles[1].skills["格兰希特"])
        self.assertEqual({"帕莱特": 0}, battle.battles[1].bursts)
        self.assertEqual((1, "burst", "帕莱特", 0), battle_bursts(battle)[0])
        self.assertLess(
            battle.actions.index((1, "burst", "帕莱特", 0)),
            battle.actions.index((1, "skill", "格兰希特", "技能1")),
        )
        self.assertIn("第 1 回合：先把爆发降下来 帕莱特 1→0", lines)

    def test_burst_the_game_puts_on_a_picked_card_is_lowered_before_the_next_pick(self):
        # Leo's T19 screenshot: lighting 帕莱特's skill card put it on BURST 3
        # (SP 10 → 2), which 格兰希特's saved skill would then lack.
        saved = {"帕莱特": "技能2", "格兰希特": "技能1"}
        teams = {1: {"cells": dict(SUMMON_CELLS), "order": list(SUMMON_ORDER)}}
        t1 = replace(turn(1, SUMMON_CELLS, SUMMON_ORDER), bursts={"帕莱特": 0, "格兰希特": 0})
        for battle_type in (QuickBattle, self.OneGo):
            with self.subTest(battle=battle_type.__name__):
                battle = battle_type(
                    teams=teams,
                    end_after=1,
                    saved_looks={1: saved},
                    preset_skills={1: {"帕莱特": "攻击", "格兰希特": "攻击"}},
                    skill_cards={"帕莱特": ("技能1", "技能2")},
                    sp=2,
                    burst_on_pick=3,
                )

                outcome = replay_fight(battle, recorded(t1), check_card=lambda unit: unit in saved)

                self.assertTrue(outcome.finished, outcome.reason)
                self.assertEqual(saved, {u: battle.battles[1].skills[u] for u in saved})
                self.assertEqual({"帕莱特": 0, "格兰希特": 0}, battle.battles[1].bursts)

    def test_unit_no_card_makes_look_as_saved_stops_before_battle(self):
        battle, record = self.summon_battle({1: "先发制人"}, {1: "技能1"})

        outcome = replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertEqual(1, outcome.stopped_at)
        self.assertIn(f"{SUMMON} 试过攻击和每张技能卡", outcome.reason)
        self.assertEqual({}, battle.battles)

    def test_pick_that_changes_another_card_stops_before_battle(self):
        class Knock(QuickBattle):
            def pick_skill(self, slot, skill):
                picked = super().pick_skill(slot, skill)
                self.skills["克蕾西亚"] = "攻击"  # the game dropped her skill
                return picked

        battle = Knock(
            end_after=1,
            saved_looks={1: {"克蕾西亚": "技能1", "马莫尼勒": "攻击"}},
            preset_skills={1: {"克蕾西亚": "技能1", "马莫尼勒": "技能1"}},
        )

        outcome = replay_fight(battle, recorded(T1), check_card=lambda unit: unit in ORDER[:2])

        self.assertEqual(1, outcome.stopped_at)
        self.assertIn("换卡后 克蕾西亚 又跟第 1 回合的存档截图不一样", outcome.reason)
        self.assertEqual({}, battle.battles)

    def test_every_unit_is_compared_again_after_a_pick(self):
        battle, record = self.summon_battle({1: "攻击"}, {1: "技能1"})

        replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertEqual([(1, SUMMON)] * 3, battle.looks)  # before, after the pick, once more

    def test_unsure_look_is_looked_at_again(self):
        battle, record = self.summon_battle({1: "技能1"}, {1: "技能1"}, blurry_looks=1)

        outcome = replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertTrue(outcome.finished)
        self.assertEqual([(1, SUMMON), (1, SUMMON)], battle.looks)

    def test_look_that_stays_unsure_stops_before_battle(self):
        battle, record = self.summon_battle({1: "技能1"}, {1: "技能1"}, blurry_looks=2)

        outcome = replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertEqual(1, outcome.stopped_at)
        self.assertIn(f"看不清 {SUMMON} 的头像和技能图标", outcome.reason)
        self.assertEqual({}, battle.battles)

    def test_turn_without_a_screenshot_is_checked_by_card_label(self):
        teams, record = summon_fight(((1, "攻击"),))
        battle = QuickBattle(
            teams=teams, end_after=1, preset_skills={1: {SUMMON: "技能1"}}, saved_looks={}
        )

        outcome = replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertTrue(outcome.finished)
        self.assertEqual([], battle.looks)
        self.assertEqual([(1, SUMMON)], battle.card_reads)
        self.assertEqual([(1, SUMMON, "攻击")], self.picks(battle))

    def test_screen_that_cannot_compare_uses_the_saved_card(self):
        class NoLooks(QuickBattle):
            same_card = None

        teams, _ = summon_fight(())
        record = recorded(turn(1, SUMMON_CELLS, SUMMON_ORDER, skills={SUMMON: "攻击"}))
        battle = NoLooks(teams=teams, end_after=1, preset_skills={1: {SUMMON: "技能1"}})

        outcome = replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertTrue(outcome.finished)
        self.assertEqual([(1, SUMMON, "攻击")], self.picks(battle))

    def test_screen_that_cannot_compare_stops_on_a_card_it_cannot_check(self):
        class NoLooks(QuickBattle):
            same_card = None

        battle, record = self.summon_battle({1: "攻击"}, {1: "技能1"}, battle=NoLooks)

        outcome = replay_fight(battle, record, check_card=summons_only(self.CHARACTERS))

        self.assertEqual(1, outcome.stopped_at)
        self.assertIn(f"没法跟存档截图比 {SUMMON}", outcome.reason)
        self.assertEqual({}, battle.battles)


class CostumeCardsTest(unittest.TestCase):
    """A skill saved with its costume is found by the costume (Leo 2026-10-06):
    the same costume can sit on another card row on another player's PC."""

    class Wardrobe(QuickBattle):
        wardrobe = {}  # unit -> {costume id: its card label on this PC}

        def label_for_costume(self, slot, name, costume):
            return self.wardrobe.get(name, {}).get(costume, "")

    def fight(self, saved_label, costume, wardrobe):
        state = TurnState(
            1,
            1,
            T1.order,
            T1.cells,
            skills={"克蕾西亚": saved_label},
            costumes={"克蕾西亚": costume},
        )
        battle = self.Wardrobe(
            end_after=1,
            skill_cards={"克蕾西亚": ("技能1", "技能2", "技能3")},
            preset_skills={1: {"克蕾西亚": "攻击"}},
        )
        battle.wardrobe = wardrobe
        lines = []
        outcome = replay_fight(battle, record_of(state), log=lines.append)
        return battle, outcome, lines

    def test_the_costumes_card_is_picked_wherever_it_is(self):
        # recorded as 技能2; on this PC 纠察队 is the 3rd skill card
        battle, outcome, lines = self.fight(
            "技能2", "Glacia_2", {"克蕾西亚": {"Glacia_2": "技能3"}}
        )

        self.assertTrue(outcome.finished)
        self.assertEqual("技能3", battle.battles[1].skills["克蕾西亚"])
        patrol = costumes.book().costume("Glacia_2").name  # souseha's wording changes
        self.assertIn(f"第 1 回合：克蕾西亚 的「{patrol}」在这台电脑是 技能3", lines)

    def test_a_missing_costume_stops_before_battle(self):
        battle, outcome, _ = self.fight("技能2", "Glacia_2", {"克蕾西亚": {"Glacia_1": "技能1"}})

        self.assertFalse(outcome.finished)
        self.assertEqual({}, battle.battles)
        patrol = costumes.book().costume("Glacia_2").name
        self.assertIn(f"没有「{patrol}」这件服装的技能卡", outcome.reason)

    def test_an_unknown_costume_falls_back_to_the_saved_card(self):
        class Unsure(self.Wardrobe):
            def label_for_costume(self, slot, name, costume):
                return None

        state = TurnState(
            1,
            1,
            T1.order,
            T1.cells,
            skills={"克蕾西亚": "技能2"},
            costumes={"克蕾西亚": "Glacia_2"},
        )
        battle = Unsure(
            end_after=1,
            skill_cards={"克蕾西亚": ("技能1", "技能2")},
            preset_skills={1: {"克蕾西亚": "攻击"}},
        )
        outcome = replay_fight(battle, record_of(state))

        self.assertTrue(outcome.finished)
        self.assertEqual("技能2", battle.battles[1].skills["克蕾西亚"])


class SummonsOnlyTest(unittest.TestCase):
    def test_checks_whoever_is_not_a_known_character(self):
        check = summons_only(["帕莱特", "黛安娜"])

        self.assertFalse(check("帕莱特"))
        self.assertTrue(check("魔法增幅器ET001"))
        self.assertTrue(check("新角色"))  # not in the list yet: may be a new summon


class ReplayTimingTest(unittest.TestCase):
    def test_times_each_turns_arranging_and_the_whole_fight(self):
        class TimedBattle(FakeBattle):
            """Reading the screen takes 5 s, a drag or ⇅ swap 1 s, a battle 12 s."""

            now = 0.0

            def read_state(self, turn):
                self.now += 5
                return super().read_state(turn)

            def drag(self, drag):
                self.now += 1
                super().drag(drag)

            def swap_order(self, first, second):
                self.now += 1
                super().swap_order(first, second)

            def wait_after_battle(self):
                self.now += 12
                return super().wait_after_battle()

        battle, lines = TimedBattle(), []

        outcome = replay_fight(
            battle, record_of(T1, T3, T5), log=lines.append, clock=lambda: battle.now
        )

        # T1: read, 2 drags, check. T3: read, 1 swap, 1 drag, check.
        # T5: read, 2 swaps, 3 drags, check.
        self.assertEqual(((1, 12.0), (3, 12.0), (5, 15.0)), outcome.arrange_seconds)
        self.assertEqual(12 + 12 + 15 + 3 * 12, outcome.seconds)
        self.assertIn("第 5 回合已按 BATTLE（排位 15.0 秒）", lines)
        self.assertEqual("打完，共 1 分 15 秒", lines[-1])

    def test_stopped_fight_still_says_how_long_it_ran(self):
        clock = iter(range(100))

        outcome = replay_fight(
            FakeBattle(unreadable={3}), record_of(T1, T3, T5), clock=lambda: next(clock)
        )

        self.assertEqual(3, outcome.stopped_at)
        self.assertEqual(1, len(outcome.arrange_seconds))
        self.assertGreater(outcome.seconds, 0)


class MinutesAndSecondsTest(unittest.TestCase):
    def test_rounds_to_whole_seconds(self):
        self.assertEqual("4 分 59 秒", minutes_and_seconds(299.4))
        self.assertEqual("5 分 0 秒", minutes_and_seconds(299.6))
        self.assertEqual("0 分 42 秒", minutes_and_seconds(42))


if __name__ == "__main__":
    unittest.main()


class PreemptTest(unittest.TestCase):
    """塔洛斯 stage 7 (2K PC 2026-10-28): lost with 「先发制人」 off, won with it on."""

    def test_saved_switches_are_turned_on(self):
        from types import SimpleNamespace

        from src.tasks.fiend_hunt.fight import _set_preempt

        cells = {"安娜塔西亚": (1, 1), "格兰希特": (1, 3)}
        saved = TurnState(1, 1, ("安娜塔西亚", "格兰希特"), cells, preempt={"格兰希特": "技能1"})
        live = TurnState(1, 1, ("安娜塔西亚", "格兰希特"), cells)
        calls, lines = [], []
        screen = SimpleNamespace(
            set_preempt=lambda slot, skill: calls.append((slot, skill)) or True
        )
        _set_preempt(screen, live, saved, lines.append)
        self.assertEqual([(1, "技能1")], calls)
        self.assertIn("先发制人", lines[0])

    def test_a_switch_that_stays_off_stops(self):
        from types import SimpleNamespace

        from src.tasks.fiend_hunt.fight import _set_preempt

        cells = {"格兰希特": (1, 3)}
        saved = TurnState(1, 1, ("格兰希特",), cells, preempt={"格兰希特": "技能1"})
        screen = SimpleNamespace(set_preempt=lambda slot, skill: False)
        with self.assertRaises(TurnMismatch):
            _set_preempt(screen, TurnState(1, 1, ("格兰希特",), cells), saved, print)
