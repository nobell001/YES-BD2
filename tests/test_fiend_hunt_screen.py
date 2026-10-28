"""GameFightScreen's reading and fixing logic against a simulated game.

The simulated game follows what was seen on the 4K PC (2026-09-30):
holding a unit's cell selects it (brackets on its list slot, name
top-left) and it stays selected; tapping the selected slot's ⇅ clears the
selection; dragging a unit onto a cell moves it (swapping with whoever is
there) and leaves it selected; dragging one ⇅ onto another swaps the two
list entries; dead units lie on tombstones and drop to the bottom of the
list marked OUT.  The pixel readers are replaced by lookups into that state
(they have their own tests on real frames).
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks.fiend_hunt import layout, vision
from src.tasks.fiend_hunt import screen as screen_module
from src.tasks.fiend_hunt.fight import ScreenReadError, replay_fight
from src.tasks.fiend_hunt.planner import Drag
from src.tasks.fiend_hunt.record import FightRecord, TurnState
from src.tasks.fiend_hunt.screen import GameFightScreen

START = {
    "克蕾西亚": (2, 0),
    "马莫尼勒": (1, 3),
    "艾尼尔": (2, 1),
    "杰尼斯": (2, 2),
    "班塔纳": (2, 3),
}
ORDER = ["克蕾西亚", "马莫尼勒", "艾尼尔", "杰尼斯", "班塔纳"]


def _near(a, b):
    return abs(a[0] - b[0]) < 1 and abs(a[1] - b[1]) < 1


class FakeGame:
    def __init__(
        self, *, cells=None, order=None, dead=None, empty_hold_clears=False, stone_selects=False
    ):
        self.turn = 1
        self.team = 1
        self.teams = 1  # teams the fight has (更换队伍 goes to the next)
        self.dialog = ""
        self.topdown = False
        self.cells = dict(cells or START)
        self.order = list(order or ORDER)
        self.dead = list(dead or [])  # list order of the OUT slots
        self.selected = None
        self.empty_hold_clears = empty_hold_clears
        self.stone_selects = stone_selects  # holding a tombstone selects its OUT slot
        self.misread = set()
        self.holds = []
        self.battles = []
        self.ending_turn = 99
        self.end = False
        self.fighting = 0  # captures left showing the battle, not the planning screen
        self.fade = []  # floor levels of the next captures while the screen fades in
        # card column per unit: [cards, lit row]; attack, 击退 and two skills by default
        self.cards = {unit: [4, 2] for unit in self.cells}
        self.skins = {}  # unit -> skin: another face on the same card
        self.stuck_cards = set()  # (unit, row) a tap doesn't light
        self.card_taps = []
        self.captures = 0
        self.sweep = 0  # captures left with the glow sweeping the list (after a pick or ⇅ tap)
        self.offset = (0.0, 0.0)  # top-down camera dragged off its place
        self.grid = None  # vision.Grid the cells are drawn at, when not layout's
        self.zoom_stays = False  # the grid stays zoomed when the view is toggled

    def selected_unit(self):
        if self.selected is None or self.selected >= len(self.order):
            return None
        return self.order[self.selected]

    # --- what the screen shows ------------------------------------------------------

    def list_names(self):
        return self.order + self.dead

    def capture(self):
        self.captures += 1
        swept = bool(self.sweep)
        if self.sweep:
            self.sweep -= 1
        if self.fighting:
            self.fighting -= 1
        fading = bool(self.fade)
        floor = self.fade.pop(0) if fading else (119 if self.topdown else 52)
        return SimpleNamespace(
            fighting=bool(self.fighting),
            turn=self.turn,
            team=self.team,
            topdown=self.topdown,
            floor=floor,
            fading=fading,
            cells=dict(self.cells),
            names=self.list_names(),
            living=len(self.order),
            selected=self.selected,
            end=self.end,
            cards=tuple(self.cards[self.selected_unit()]) if self.selected_unit() else None,
            # what each list entry shows of its card: the unit and its lit row
            entries=tuple(
                (unit, self.cards[unit][1], self.skins.get(unit, 0)) for unit in self.order
            )
            + tuple((unit, "OUT", 0) for unit in self.dead),
            swept=swept,
            offset=self.offset,
            grid=self.grid,
            dialog=self.dialog,
        )

    # --- input ----------------------------------------------------------------------

    def cell_at(self, point):
        for row in range(3):
            for col in range(4):
                drawn = layout.cell_press((row, col))
                if self.grid is not None:
                    drawn = self.grid.point(drawn)
                if _near(point, drawn):
                    return row, col
        return None

    def unit_at(self, cell):
        return next((unit for unit, where in self.cells.items() if where == cell), None)

    def tap(self, point):
        for slot in range(layout.MAX_SLOTS):
            if _near(point, layout.slot_swap(slot)) and self.selected == slot:
                self.selected = None
                return
            if _near(point, layout.slot_tap(slot)) and slot < len(self.list_names()):
                self.selected = slot
                return
        unit = self.selected_unit()
        for row in range(layout.MAX_SLOTS):
            if unit and _near(point, layout.card_tap(row)) and row < self.cards[unit][0]:
                self.card_taps.append((unit, row))
                if (unit, row) not in self.stuck_cards:
                    self.cards[unit][1] = row
                return
        if _near(point, layout.CHANGE_TEAM) and self.team < self.teams:
            self.dialog = "更换队伍"
            return
        if _near(point, layout.TEAM_DIALOG_CONFIRM) and self.dialog:
            self.dialog = ""
            self.team += 1  # the next team only, never back
            return
        if _near(point, layout.VIEW_TOGGLE):
            if not self.fade:  # the game ignores the toggle while it fades in
                self.topdown = not self.topdown
                self.offset = (0.0, 0.0)  # the camera goes back to its place
                if not self.zoom_stays:
                    self.grid = None
        elif _near(point, layout.BATTLE):
            self.battles.append((self.turn, dict(self.cells), tuple(self.order)))
            self.fighting = 3
            if self.turn >= self.ending_turn:
                self.end = True
            else:
                self.turn += 2
            self.topdown = False  # the view resets after each battle

    def hold(self, point, seconds):
        cell = self.cell_at(point)
        self.holds.append(cell)
        unit = self.unit_at(cell)
        if unit in self.order:
            self.selected = self.order.index(unit)
        elif unit in self.dead and self.stone_selects:
            self.selected = len(self.order) + self.dead.index(unit)
        elif self.empty_hold_clears:
            self.selected = None

    def drag(self, start, end, hold, seconds, steps):
        source, target = self.cell_at(start), self.cell_at(end)
        if source is not None:
            unit = self.unit_at(source)
            if unit is None or unit in self.dead:
                return
            other = self.unit_at(target)
            self.cells[unit] = target
            if other is not None:
                self.cells[other] = source
            self.selected = self.order.index(unit)
            return
        slots = [
            slot
            for slot in range(layout.MAX_SLOTS)
            for point in (start, end)
            if _near(point, layout.slot_swap(slot))
        ]
        first, second = slots
        self.order[first], self.order[second] = self.order[second], self.order[first]


class LateGame(FakeGame):
    """A selection that only shows ``lag`` captures after the hold."""

    def __init__(self, *, lag, **kwargs):
        super().__init__(**kwargs)
        self.lag = lag
        self.hidden = 0

    def hold(self, point, seconds):
        super().hold(point, seconds)
        self.hidden = self.lag

    def capture(self):
        shown = super().capture()
        if self.hidden:
            self.hidden -= 1
            shown.selected = None
        return shown


class SlowColumnGame(FakeGame):
    """A card column that is still sliding in ``lag`` captures after a hold."""

    def __init__(self, *, lag, **kwargs):
        super().__init__(**kwargs)
        self.lag = lag
        self.sliding = 0

    def hold(self, point, seconds):
        super().hold(point, seconds)
        self.sliding = self.lag

    def capture(self):
        shown = super().capture()
        if self.sliding:
            self.sliding -= 1
            shown.cards = None
        return shown


def fake_vision():
    """The readers of vision.py, answered from the simulated screen."""
    return SimpleNamespace(
        TEAMS=vision.TEAMS,
        Grid=vision.Grid,
        LAYOUT_GRID=vision.LAYOUT_GRID,
        # the brackets as drawn: layout's grid unless the game zoomed it
        grid_on_screen=lambda f: (f.grid or vision.LAYOUT_GRID) if f.topdown else None,
        planning_visible=lambda f: not (f.end or f.fighting),
        icons_lit=lambda f: getattr(f, "lit", True),
        battle_end_visible=lambda f: f.end,
        victory_visible=lambda f: False,
        lost_word=lambda f, ocr: None,
        # the fake battle never holds still
        still_picture=lambda f: object(),
        same_still=lambda earlier, now: False,
        is_topdown=lambda f: f.floor > 110,
        view_offset=lambda f: f.offset,
        view_toggle_point=lambda f: None,
        talos_layout=lambda f: False,
        floor_level=lambda f: f.floor,
        slot_count=lambda f: 0 if (f.end or f.fighting) else len(f.names),
        out_slots=lambda f, count: list(range(f.living, count)),
        selected_slots=lambda f, count=6: [] if f.selected is None else [f.selected],
        read_turn=lambda f, ocr: f.turn,
        read_team=lambda f, ocr: f.team if f.selected is None else None,
        single_team=lambda f, ocr: False,
        read_name=lambda f, ocr: (
            "" if f.selected is None else f"S{f.names[f.selected]}ET"  # icon/letters around it
        ),
        read_dialog_title=lambda f, ocr: f.dialog,
        cell_busy_score=lambda f, cell, grid=None: 60.0 if cell in f.cells.values() else 10.0,
        card_count=lambda f: f.cards[0] if f.cards else 0,
        lit_card=lambda f: f.cards[1] if f.cards else None,
        card_label=vision.card_label,
        card_row=vision.card_row,
        _bgr=lambda f: f,
        same_card=lambda f, slot, saved, saved_slot: (
            None if f.swept else f.entries[slot] == saved.entries[saved_slot]
        ),
        has_skill_icon=lambda f, slot: f.entries[slot][1] >= layout.FIRST_SKILL_ROW,
        list_action=lambda f, slot: (
            vision.SKILL_LABEL
            if f.entries[slot][1] >= layout.FIRST_SKILL_ROW
            else vision.card_label(f.entries[slot][1])
        ),
        SKILL_LABEL=vision.SKILL_LABEL,
        card_with_icon=lambda f, cards, saved, saved_slot, lenient=False: (
            row if (row := saved.entries[saved_slot][1]) < cards else None
        ),
        card_like=lambda f, cards, saved, saved_slot, lenient=False: (
            row if (row := saved.entries[saved_slot][1]) < cards else None
        ),
        list_steady=lambda f, other, slots: (
            not (f.swept or other.swept) and f.entries[:slots] == other.entries[:slots]
        ),
        cells_by_busy=lambda f, grid=None: sorted(
            ((r, c) for r in range(3) for c in range(4)),
            key=lambda cell: cell not in f.cells.values(),
        ),
    )


def make_screen(
    game, known=None, record=None, learn_names=False, screenshots=None, read_cards=None
):
    """``screenshots``: saved frames by file name (the record's folder is then set)."""
    task = SimpleNamespace(_bring_game_to_foreground=lambda: True)
    return GameFightScreen(
        task,
        list(START) + ["魔法增幅器"] if known is None else known,
        learn_names=learn_names,
        record=record,
        folder=None if screenshots is None else "record",
        load_screenshot=lambda path: (screenshots or {}).get(path.name),
        screen_input=game,
        capture=game.capture,
        ocr=lambda image: [],
        sleep=lambda seconds: None,
        read_cards=read_cards,
    )


class SwitchTeamTest(unittest.TestCase):
    """Leo 2026-10-01: a fight can have a TEAM3; 更换队伍 goes one team on."""

    def setUp(self):
        patcher = mock.patch.object(screen_module, "vision", fake_vision())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_team_one_to_three_takes_two_switches(self):
        game = FakeGame()
        game.teams = 3
        self.assertTrue(make_screen(game).switch_team(3))
        self.assertEqual(3, game.team)

    def test_the_next_team(self):
        game = FakeGame()
        game.teams = 3
        self.assertTrue(make_screen(game).switch_team(2))
        self.assertEqual(2, game.team)

    def test_a_team_the_fight_lacks_fails(self):
        game = FakeGame()
        game.teams = 2
        self.assertFalse(make_screen(game).switch_team(3))
        self.assertEqual(2, game.team)

    def test_never_back(self):
        game = FakeGame()
        game.teams, game.team = 3, 3
        self.assertFalse(make_screen(game).switch_team(2))
        self.assertEqual(3, game.team)


class ReadStateTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(screen_module, "vision", fake_vision())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unit_whose_first_hold_missed_is_held_again(self):
        # 2K PC 2026-10-01: the first hold after the game came to the front
        # selected nobody on 克蕾西亚's cell, and the read gave up.
        class Missing(FakeGame):
            missed = 1

            def hold(self, point, seconds):
                if self.missed:
                    self.missed -= 1
                    self.holds.append(self.cell_at(point))
                    return
                super().hold(point, seconds)

        game = Missing()
        state = make_screen(game).read_state(1)

        self.assertEqual(START, state.cells)
        self.assertEqual(2, game.holds.count(game.holds[0]))  # the missed cell, held twice

    def test_a_missed_hold_over_card_like_floor_is_held_again(self):
        # 4K PC 2026-10-08 (水魔兽 T3): a hold selected nobody, TEAM1 still
        # showed top-left, but the floor passed for 2 cards; the read stopped
        # with 「认不出左边选中的是第几位」 instead of holding the cell again.
        class Missing(FakeGame):
            missed = 1

            def hold(self, point, seconds):
                if self.missed:
                    self.missed -= 1
                    self.holds.append(self.cell_at(point))
                    return
                super().hold(point, seconds)

        count = screen_module.vision.card_count
        screen_module.vision.card_count = lambda f: 2 if f.selected is None else count(f)
        game = Missing()
        screen = make_screen(game)
        screen._keep_picture = lambda frame, kind: self.fail("no report picture for a miss")
        state = screen.read_state(1)

        self.assertEqual(START, state.cells)
        self.assertEqual(2, game.holds.count(game.holds[0]))

    def test_a_missed_hold_in_a_fight_with_no_teams_is_held_again(self):
        # 2K PC 2026-10-22 (塔洛斯战术教材): no TEAMn ever shows and the floor's
        # grid lines passed for cards; a missed hold stopped the read with
        # 「认不出左边选中的是第几位」.
        class Missing(FakeGame):
            missed = 1

            def hold(self, point, seconds):
                if self.missed:
                    self.missed -= 1
                    self.holds.append(self.cell_at(point))
                    return
                super().hold(point, seconds)

        vision_now = screen_module.vision
        count = vision_now.card_count
        vision_now.card_count = lambda f: 5 if f.selected is None else count(f)
        vision_now.read_team = lambda f, ocr: None
        vision_now.single_team = lambda f, ocr: True
        game = Missing()
        screen = make_screen(game)
        screen._keep_picture = lambda frame, kind: self.fail("no report picture for a miss")
        state = screen.read_state(1)

        self.assertEqual(START, state.cells)
        self.assertEqual(2, game.holds.count(game.holds[0]))

    def test_unit_slow_to_select_on_a_bare_looking_cell_is_found(self):
        # 2K PC 2026-10-07: a unit's cell held nobody and, looking bare, was
        # never held again; the read stopped with 「找不到第 [2] 位」.
        slow = START["班塔纳"]

        class Slow(FakeGame):
            missed = 1

            def hold(self, point, seconds):
                if self.missed and self.cell_at(point) == slow:
                    self.missed -= 1
                    self.holds.append(slow)
                    return
                super().hold(point, seconds)

        busy = screen_module.vision.cell_busy_score
        screen_module.vision.cell_busy_score = lambda f, cell, grid=None: (
            10.0 if cell == slow else busy(f, cell)
        )
        game = Slow()
        state = make_screen(game).read_state(1)

        self.assertEqual(START, state.cells)
        self.assertEqual(2, game.holds.count(slow))

    def _hide_marks(self, *units):
        """The list shows no selection while one of ``units`` is held."""
        selected = screen_module.vision.selected_slots

        def hidden(f, count=6):
            shown = selected(f, count)
            return [] if shown and f.names[shown[0]] in units else shown

        screen_module.vision.selected_slots = hidden

    def test_a_unit_with_no_slot_marked_is_found_by_its_name(self):
        # Leo 2026-10-07: the name top-left shows who is held even when the
        # list's brackets aren't seen; one slot left over is that unit's.
        game = FakeGame()
        self._hide_marks("班塔纳")
        screen = make_screen(game)
        screen._keep_picture = lambda frame, kind: None
        state = screen.read_state(1)
        self.assertEqual(START, state.cells)
        self.assertEqual(tuple(ORDER), state.order)

    def test_two_units_with_no_slot_marked_stop_the_read(self):
        game = FakeGame()
        self._hide_marks("杰尼斯", "班塔纳")
        screen = make_screen(game)
        kept = []
        screen._keep_picture = lambda frame, kind: kept.append(kind)
        with self.assertRaisesRegex(ScreenReadError, r"找不到第 \[4, 5\] 位"):
            screen.read_state(1)
        self.assertEqual(["fiend-grid"], kept)

    def test_cards_without_a_marked_slot_or_a_name_stop_the_read(self):
        game = FakeGame()
        self._hide_marks(*ORDER)
        screen_module.vision.read_name = lambda f, ocr: ""
        screen = make_screen(game)
        kept = []
        screen._keep_picture = lambda frame, kind: kept.append(kind)
        with self.assertRaisesRegex(ScreenReadError, "认不出左边选中"):
            screen.read_state(1)
        self.assertEqual(1, len(game.holds))
        self.assertEqual(["fiend-grid"], kept)

    def test_a_unit_never_found_is_logged_with_the_holds(self):
        game = FakeGame()
        del game.cells["班塔纳"]
        screen = make_screen(game)
        logs = []
        screen.log = logs.append
        kept = []
        screen._keep_picture = lambda frame, kind: kept.append(kind)
        with self.assertRaises(ScreenReadError):
            screen.read_state(1)
        self.assertTrue(any(line.startswith("按过的格子") for line in logs))
        self.assertEqual(["fiend-grid"], kept)

    def test_portrait_tap_waits_after_a_selection_was_cleared(self):
        # 2K PC 2026-10-01: a portrait tap right after a ⇅ tap was ignored.
        game = FakeGame()
        screen = make_screen(game)
        now, waits = [100.0], []
        screen.clock = lambda: now[0]
        screen.sleep = lambda seconds: (waits.append(seconds), now.__setitem__(0, now[0] + seconds))

        screen._select_slot(0)
        screen._clear_selection(game.capture())
        screen._select_slot(1)

        long_waits = [wait for wait in waits if wait > 0.1]
        self.assertEqual(1, len(long_waits))
        self.assertAlmostEqual(screen_module.AFTER_CLEAR, long_waits[0])

    def test_reads_cells_order_and_team_one_hold_per_unit(self):
        game = FakeGame()
        state = make_screen(game).read_state(1)
        self.assertEqual(START, state.cells)
        self.assertEqual(tuple(ORDER), state.order)
        self.assertEqual(1, state.team)
        self.assertTrue(game.topdown)  # switched to the top-down view first
        self.assertEqual(5, len(game.holds))  # busy cells first, stop when all found
        self.assertIsNone(game.selected)  # nothing left selected

    def test_empty_cell_that_keeps_the_selection_is_not_mistaken(self):
        game = FakeGame()
        screen = make_screen(game)
        screen.last_cells[1] = {"克蕾西亚": (0, 0)}  # stale hint: she moved
        state = screen.read_state(1)
        self.assertEqual(START, state.cells)

    def test_unknown_name_stops(self):
        game = FakeGame()
        with self.assertRaises(ScreenReadError):
            make_screen(game, known=["海伦娜", "鲁"]).read_state(1)

    def test_dead_unit_and_its_tombstone(self):
        cells = dict(START)
        game = FakeGame(cells=cells, order=[u for u in ORDER if u != "艾尼尔"], dead=["艾尼尔"])
        state = make_screen(game).read_state(1)
        self.assertEqual(frozenset({"艾尼尔"}), state.dead)
        self.assertEqual((2, 1), state.cells["艾尼尔"])
        self.assertNotIn("艾尼尔", state.order)
        self.assertEqual(12, len(game.holds))  # with a tombstone every cell is checked

    def test_tombstone_that_selects_its_out_slot(self):
        living = [u for u in ORDER if u not in ("艾尼尔", "杰尼斯")]
        game = FakeGame(order=living, dead=["杰尼斯", "艾尼尔"], stone_selects=True)
        state = make_screen(game).read_state(1)
        self.assertEqual(frozenset({"艾尼尔", "杰尼斯"}), state.dead)
        self.assertEqual((2, 1), state.cells["艾尼尔"])
        self.assertEqual((2, 2), state.cells["杰尼斯"])
        self.assertEqual(tuple(living), state.order)
        self.assertIsNone(game.selected)

    def test_recording_learns_names_no_list_has(self):
        game = FakeGame()
        state = make_screen(game, known=[], learn_names=True).read_state(1)
        self.assertEqual(START, state.cells)
        self.assertEqual({}, state.skills)  # cards are only read when asked (read_cards)

    def test_recording_reads_the_cards_when_asked(self):
        # The recording task asks: 克蕾西亚's two skills have near-identical
        # icons, so a screenshot alone can't tell them (尤里光盾 T21, 2026-10-01).
        game = FakeGame()
        game.cards["班塔纳"] = [5, 4]
        state = make_screen(game, known=[], learn_names=True, read_cards=True).read_state(1)
        self.assertEqual(START, state.cells)
        self.assertEqual("技能3", state.skills["班塔纳"])
        self.assertEqual("技能1", state.skills["克蕾西亚"])
        self.assertEqual(set(ORDER), set(state.skills))
        self.assertIsNone(game.selected)

    def test_recording_waits_for_a_slow_card_column(self):
        # 2K PC 2026-10-07: the column slid in after the 3 captures the grid
        # read gave it, so 4 in 10 cards were left out and the chart showed
        # bare 「技能」.  Recording (costumes learned) waits the full column time.
        game = SlowColumnGame(lag=4)
        screen = make_screen(game, known=[], learn_names=True, read_cards=True)
        screen.learn_costumes = True
        screen._learn_costumes = lambda name, column: None
        state = screen.read_state(1)
        self.assertEqual(set(ORDER), set(state.skills))

    def test_recording_holds_a_unit_again_when_its_column_never_settled(self):
        game = SlowColumnGame(lag=0)
        stuck = {"班塔纳"}  # its column doesn't come in on the first hold
        hold = game.hold

        def first_hold_slides_forever(point, seconds):
            hold(point, seconds)
            unit = game.selected_unit()
            if unit in stuck:
                stuck.discard(unit)
                game.sliding = 999
            else:
                game.sliding = 0

        game.hold = first_hold_slides_forever
        screen = make_screen(game, known=[], learn_names=True, read_cards=True)
        screen.learn_costumes = True
        screen._learn_costumes = lambda name, column: None
        state = screen.read_state(1)
        self.assertEqual(set(ORDER), set(state.skills))
        self.assertEqual(2, game.holds.count(START["班塔纳"]))

    def test_a_turn_with_no_card_columns_holds_each_unit_once_more_at_most_once(self):
        # 2K PC 2026-10-07 T19: the game showed no card column to anyone.
        game = SlowColumnGame(lag=0)
        hold = game.hold

        def never_shows(point, seconds):
            hold(point, seconds)
            game.sliding = 999

        game.hold = never_shows
        screen = make_screen(game, known=[], learn_names=True, read_cards=True)
        screen.learn_costumes = True
        screen._learn_costumes = lambda name, column: None
        state = screen.read_state(1)
        self.assertEqual(START, state.cells)
        self.assertEqual({}, state.skills)
        held_twice = [cell for cell in set(game.holds) if game.holds.count(cell) > 1]
        self.assertEqual(1, len(held_twice))

    def test_recording_holds_unit_after_unit_and_an_empty_cell_is_not_mistaken(self):
        game = FakeGame()  # an empty cell keeps the last selection
        guess = dict(START, 艾尼尔=(0, 0))  # expected where nobody stands now
        record = FightRecord(turns={1: TurnState(1, 1, tuple(ORDER), guess)})
        screen = make_screen(game, known=[], learn_names=True, record=record)
        taps_before = len(game.card_taps)
        state = screen.read_state(1)
        self.assertEqual(START, state.cells)
        self.assertEqual(tuple(ORDER), state.order)
        self.assertIsNone(game.selected)
        self.assertEqual(taps_before, len(game.card_taps))
        self.assertEqual(5, len(game.holds))  # the guess on bare floor wasn't held

    def test_empty_cell_in_a_chained_read_is_cleared_and_held_again(self):
        game = FakeGame()
        screen = make_screen(game, known=[], learn_names=True)
        order = [(2, 0), (0, 0)] + [cell for cell in START.values() if cell != (2, 0)]
        with mock.patch.object(screen, "_hold_order", lambda *args: order):
            state = screen.read_state(1)
        self.assertEqual(START, state.cells)
        self.assertEqual((0, 0), game.holds[1])  # empty: kept 克蕾西亚 selected
        self.assertEqual((0, 0), game.holds[2])  # so cleared and held again

    def test_names_match_without_the_ascii_on_the_name_line(self):
        # the game shows 魔法增幅器ET001 (souseha's 简中 name too); stray icon letters
        for saved in ("魔法增幅器", "魔法增幅器ET001"):
            with self.subTest(saved=saved):
                cells = dict(START, **{saved: (0, 0)})
                game = FakeGame(cells=cells, order=ORDER + [saved])
                known = list(START) + [saved]
                state = make_screen(game, known=known).read_state(1)
                self.assertEqual((0, 0), state.cells[saved])

    def test_glance_and_lit_slot(self):
        game = FakeGame()
        screen = make_screen(game)
        glance = screen.glance()
        self.assertEqual((1, 5, 0), (glance.team, glance.slots, glance.out))
        self.assertEqual(3, screen.lit_slot((2, 2)))
        self.assertIsNone(screen.lit_slot((0, 0)))
        self.assertIsNone(game.selected)

    def test_waits_for_the_fade_in_before_reading(self):
        # floor levels logged on the 4K PC as TEAM2 took over at T13 (2026-10-01):
        # dark, a one-frame top-down-bright flash, then settling isometric
        game = FakeGame()
        game.fade = [29, 26, 26, 169, 99, 86, 94, 72, 62, 53, 50, 44, 44, 45, 48, 52]
        state = make_screen(game).read_state(1)
        self.assertEqual(START, state.cells)
        self.assertTrue(game.topdown)
        self.assertEqual(5, len(game.holds))

    def test_screen_that_never_settles_stops(self):
        game = FakeGame()
        game.fade = [30, 120] * 100
        with self.assertRaises(ScreenReadError):
            make_screen(game).read_state(1)
        self.assertEqual([], game.holds)

    def test_selection_that_shows_late_is_polled_for(self):
        game = LateGame(lag=3)  # brackets show on the 4th capture after a hold
        state = make_screen(game).read_state(1)
        self.assertEqual(START, state.cells)
        self.assertEqual(5, len(game.holds))

    def test_empty_cell_gives_up_after_a_few_captures(self):
        game = FakeGame()
        screen = make_screen(game)
        captures = []
        screen.capture = lambda: captures.append(1) or game.capture()
        self.assertIsNone(screen.lit_slot((0, 0)))
        self.assertEqual(screen_module.SELECT_POLLS, len(captures))

    def test_missing_unit_stops(self):
        game = FakeGame()
        del game.cells["班塔纳"]  # listed but on no cell
        with self.assertRaises(ScreenReadError):
            make_screen(game).read_state(1)


class SkillCardsTest(unittest.TestCase):
    """The card column: row 0 攻击, row 1 击退, then 技能1.. (one per costume)."""

    def setUp(self):
        patcher = mock.patch.object(screen_module, "vision", fake_vision())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_read_state_reads_every_units_lit_card_from_its_hold(self):
        game = FakeGame()
        game.cards["马莫尼勒"] = [4, 0]
        game.cards["班塔纳"] = [5, 4]
        state = make_screen(game).read_state(1)
        self.assertEqual("攻击", state.skills["马莫尼勒"])
        self.assertEqual("技能3", state.skills["班塔纳"])
        self.assertEqual("技能1", state.skills["克蕾西亚"])
        self.assertEqual(set(ORDER), set(state.skills))
        self.assertEqual(5, len(game.holds))  # no extra taps for the cards
        self.assertEqual([], game.card_taps)

    def test_unreadable_card_is_left_out_without_waiting(self):
        game = FakeGame()
        game.cards["艾尼尔"] = [4, None]
        game.captures = 0
        state = make_screen(game).read_state(1)
        self.assertNotIn("艾尼尔", state.skills)
        self.assertEqual("技能1", state.skills["克蕾西亚"])
        self.assertEqual(5, len(game.holds))
        self.assertLess(game.captures, 60)  # no long polling for the missing card

    def test_skill_of_answers_from_the_holds_until_something_moves(self):
        game = FakeGame()
        screen = make_screen(game)
        screen.read_state(1)
        taps = len(game.card_taps)
        self.assertEqual("技能1", screen.skill_of(1))
        self.assertIsNone(game.selected)
        game.cards["马莫尼勒"][1] = 0  # changed behind the tool's back
        screen.swap_order(0, 1)  # the list moved: the cache is dropped
        self.assertEqual("攻击", screen.skill_of(0))  # 马莫尼勒 is first now
        self.assertIsNone(game.selected)
        self.assertEqual(taps, len(game.card_taps))

    def test_pick_skill_lights_the_card_and_leaves_nobody_selected(self):
        game = FakeGame()
        screen = make_screen(game)
        self.assertTrue(screen.pick_skill(4, "攻击"))
        self.assertEqual(0, game.cards["班塔纳"][1])
        self.assertEqual([("班塔纳", 0)], game.card_taps)
        self.assertIsNone(game.selected)
        self.assertEqual("攻击", screen.skill_of(4))
        self.assertTrue(screen.pick_skill(4, "技能2"))
        self.assertEqual(3, game.cards["班塔纳"][1])
        self.assertTrue(screen.pick_skill(4, "击退"))
        self.assertEqual(1, game.cards["班塔纳"][1])

    def test_pick_skill_already_lit_taps_no_card(self):
        game = FakeGame()
        self.assertTrue(make_screen(game).pick_skill(0, "技能1"))
        self.assertEqual([], game.card_taps)
        self.assertIsNone(game.selected)

    def test_bare_skill_only_when_the_unit_has_one_skill_card(self):
        game = FakeGame()
        game.cards["班塔纳"] = [3, 0]  # like the summon: 攻击, 击退, one skill
        screen = make_screen(game)
        self.assertTrue(screen.pick_skill(4, "技能"))
        self.assertEqual(2, game.cards["班塔纳"][1])
        game.cards["克蕾西亚"] = [4, 0]
        self.assertFalse(screen.pick_skill(0, "技能"))  # two skill cards: which one?
        self.assertEqual(0, game.cards["克蕾西亚"][1])
        self.assertIsNone(game.selected)

    def test_pick_skill_fails_for_a_card_that_does_not_light_or_is_not_there(self):
        game = FakeGame()
        game.cards["艾尼尔"] = [4, 2]
        game.stuck_cards.add(("艾尼尔", 3))  # e.g. not enough SP
        screen = make_screen(game)
        self.assertFalse(screen.pick_skill(2, "技能2"))
        self.assertFalse(screen.pick_skill(2, "技能3"))  # only two skill cards
        self.assertFalse(screen.pick_skill(2, "技能1·B3"))
        self.assertEqual(2, game.cards["艾尼尔"][1])
        self.assertIsNone(game.selected)
        self.assertIsNone(screen.card_labels.get(2))


def recorded(game, turns=(1,)):
    """A record of the game as it stands, with a screenshot per turn."""
    shot = game.capture()
    record = FightRecord(
        turns={
            turn: TurnState(turn, game.team, tuple(game.order), dict(game.cells)) for turn in turns
        },
        screenshots={turn: f"turn{turn:02d}.png" for turn in turns},
    )
    return record, {f"turn{turn:02d}.png": shot for turn in turns}


class SameCardTest(unittest.TestCase):
    """Comparing the list with a turn's saved screenshot (the pixel side is in the vision tests)."""

    def setUp(self):
        patcher = mock.patch.object(screen_module, "vision", fake_vision())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_capture_answers_every_slot(self):
        game = FakeGame()
        record, shots = recorded(game)
        game.cards["班塔纳"][1] = 0  # on attack now, saved on 技能1
        screen = make_screen(game, record=record, screenshots=shots)
        self.assertTrue(screen.same_card(1, 0))
        captures = game.captures
        seen = [screen.same_card(1, slot) for slot in range(1, 5)]
        self.assertEqual([True, True, True, False], seen)
        self.assertEqual(captures, game.captures)

    def test_same_skill_in_another_skin_is_the_same_card(self):
        # Leo 2026-10-01: a skin changes the costume's art, not its skill or icon.
        game = FakeGame()
        record, shots = recorded(game)
        game.skins["杰尼斯"] = 1
        screen = make_screen(game, record=record, screenshots=shots)
        self.assertTrue(screen.same_card(1, 3))
        self.assertIsNone(game.selected)  # the column was closed again
        self.assertEqual([], game.card_taps)  # nothing picked

    def test_another_skill_in_another_skin_is_still_another_card(self):
        game = FakeGame()
        record, shots = recorded(game)
        game.skins["杰尼斯"] = 1
        game.cards["杰尼斯"][1] = 3
        self.assertFalse(make_screen(game, record=record, screenshots=shots).same_card(1, 3))

    def test_a_pick_drops_the_capture(self):
        game = FakeGame()
        record, shots = recorded(game)
        game.cards["班塔纳"][1] = 0
        screen = make_screen(game, record=record, screenshots=shots)
        self.assertFalse(screen.same_card(1, 4))
        self.assertTrue(screen.pick_skill(4, "技能1"))
        self.assertTrue(screen.same_card(1, 4))

    def test_waits_for_the_glow_to_pass_with_nobody_selected(self):
        game = FakeGame()
        record, shots = recorded(game)
        screen = make_screen(game, record=record, screenshots=shots)
        game.selected = 2
        game.sweep = 3
        self.assertTrue(screen.same_card(1, 2))
        self.assertIsNone(game.selected)

    def test_unsure_while_the_list_keeps_changing(self):
        game = FakeGame()
        record, shots = recorded(game)
        game.sweep = 100
        self.assertIsNone(make_screen(game, record=record, screenshots=shots).same_card(1, 0))

    def test_no_screenshot_no_answer(self):
        game = FakeGame()
        record, shots = recorded(game)
        self.assertIsNone(make_screen(game, record=record).same_card(1, 0))  # no folder
        screen = make_screen(game, record=record, screenshots=shots)
        self.assertIsNone(screen.same_card(3, 0))  # no such turn
        self.assertIsNone(make_screen(game, record=record, screenshots={}).same_card(1, 0))

    def test_next_screenshot_loads_ahead(self):
        game = FakeGame()
        record, shots = recorded(game, turns=(1, 3, 5))
        loaded = []

        def load(path):
            loaded.append(path.name)
            return shots.get(path.name)

        screen = make_screen(game, record=record, screenshots=shots)
        screen.load_screenshot = load
        self.assertTrue(screen.same_card(1, 0))
        screen._files.shutdown(wait=True)
        self.assertEqual(["turn01.png", "turn03.png"], loaded)

    def test_save_screenshot_waits_for_a_still_list_with_nobody_selected(self):
        game = FakeGame()
        screen = make_screen(game)
        game.selected = 1
        game.sweep = 2
        written = []
        with mock.patch.object(
            screen_module, "_write_png", lambda path, frame: written.append(frame)
        ):
            screen.save_screenshot(Path("turn01.png"))
            screen.wait_saved()
        self.assertEqual(1, len(written))
        self.assertIsNone(written[0].selected)
        self.assertFalse(written[0].swept)

    def test_png_goes_to_a_non_ascii_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "我的魔兽战" / "turn01.png"
            path.parent.mkdir()
            screen_module._write_png(path, np.zeros((4, 6, 3), np.uint8))
            self.assertEqual((4, 6, 3), screen_module.load_frame(path).shape)

    def test_replay_fixes_a_card_that_looks_different_then_battles(self):
        game = FakeGame()
        game.ending_turn = 1
        record, shots = recorded(game)
        game.cards["班塔纳"][1] = 0
        outcome = replay_fight(make_screen(game, record=record, screenshots=shots), record)
        self.assertTrue(outcome.finished, outcome.reason)
        self.assertEqual(2, game.cards["班塔纳"][1])  # back on 技能1, as saved
        self.assertEqual(1, len(game.battles))


class ReplayTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(screen_module, "vision", fake_vision())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_replays_moves_and_order_then_battles(self):
        turn3_cells = dict(START, 克蕾西亚=(0, 0), 班塔纳=(2, 0))
        turn3_order = ("班塔纳", "马莫尼勒", "艾尼尔", "杰尼斯", "克蕾西亚")
        record = FightRecord(
            turns={
                1: TurnState(1, 1, tuple(ORDER), START),
                3: TurnState(3, 1, turn3_order, turn3_cells),
            }
        )
        game = FakeGame(empty_hold_clears=False)
        game.ending_turn = 3
        outcome = replay_fight(make_screen(game, record=record), record)
        self.assertTrue(outcome.finished, outcome.reason)
        self.assertEqual((1, 3), outcome.turns_played)
        self.assertEqual(turn3_cells, game.battles[1][1])
        self.assertEqual(turn3_order, game.battles[1][2])

    def test_later_turns_are_confirmed_with_one_hold_per_unit(self):
        record = FightRecord(
            turns={turn: TurnState(turn, 1, tuple(ORDER), START) for turn in (1, 3, 5)}
        )
        game = FakeGame()
        game.ending_turn = 5
        outcome = replay_fight(make_screen(game, record=record), record)
        self.assertTrue(outcome.finished, outcome.reason)
        self.assertEqual(15, len(game.holds))  # 5 units x 3 turns

    def test_stops_before_battle_when_someone_died(self):
        record = FightRecord(turns={1: TurnState(1, 1, tuple(ORDER), START)})
        game = FakeGame(order=[u for u in ORDER if u != "杰尼斯"], dead=["杰尼斯"])
        outcome = replay_fight(make_screen(game, record=record), record)
        self.assertFalse(outcome.finished)
        self.assertEqual([], game.battles)
        self.assertIn("杰尼斯", outcome.reason)


if __name__ == "__main__":
    unittest.main()


class AutoSkillTest(unittest.TestCase):
    """The diamond top right is set by the replay's mode (Leo 2026-10-01)."""

    class Game:
        def __init__(self, on, stuck=False, spin=None):
            self.on, self.stuck, self.taps = on, stuck, []
            self.spin = spin  # what the ⟳ shows; None: spinning exactly while on

        def capture(self):
            spin = self.on if self.spin is None else self.spin
            return SimpleNamespace(auto=self.on, spin=spin, end=False, fighting=False)

        def tap(self, point):
            self.taps.append(point)
            if point == layout.AUTO_SKILL and not self.stuck:
                self.on = not self.on

    def setUp(self):
        readers = fake_vision()
        readers.auto_skill_on = lambda f: f.auto
        readers.auto_skill_turning = lambda first, second: second.spin
        patcher = mock.patch.object(screen_module, "vision", readers)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_switched_to_the_wanted_side_with_one_tap(self):
        for start, wanted in ((True, False), (False, True)):
            with self.subTest(start=start, wanted=wanted):
                game = self.Game(start)
                self.assertTrue(make_screen(game).set_auto_skill(wanted))
                self.assertEqual(wanted, game.on)
                self.assertEqual([layout.AUTO_SKILL], game.taps)

    def test_left_alone_when_already_right(self):
        game = self.Game(True)
        self.assertTrue(make_screen(game).set_auto_skill(True))
        self.assertEqual([], game.taps)

    def test_game_brought_to_front_before_the_tap(self):
        game = self.Game(False)
        screen = make_screen(game)
        fronted = []
        screen.task = SimpleNamespace(_bring_game_to_foreground=lambda: fronted.append(1) or True)
        self.assertTrue(screen.set_auto_skill(True))
        self.assertEqual([1], fronted)
        screen.task = SimpleNamespace(_bring_game_to_foreground=lambda: False)
        with self.assertRaises(ScreenReadError):
            screen.set_auto_skill(False)
        self.assertEqual([layout.AUTO_SKILL], game.taps)  # only the first call's

    def test_icon_still_fading_in_is_read_again(self):
        # 4K PC clone 2026-10-28: the planning screen's BATTLE shows while the
        # scenery and icons are still dark; the first read can't tell
        game = self.Game(True)
        screen = make_screen(game)
        dark = [None, None]
        real = screen.auto_skill_state
        screen.auto_skill_state = lambda: dark.pop() if dark else real()
        self.assertTrue(screen.set_auto_skill(False))
        self.assertFalse(game.on)
        self.assertEqual([layout.AUTO_SKILL], game.taps)

    def test_tap_that_does_not_take_is_reported(self):
        game = self.Game(False, stuck=True)
        self.assertFalse(make_screen(game).set_auto_skill(True))

    def test_colour_and_spin_disagreeing_is_not_guessed(self):
        # Blue scenery behind a still icon, or a spinning one the colour misses.
        for on, spin in ((True, False), (False, True)):
            with self.subTest(dot=on, spin=spin):
                game = self.Game(on, spin=spin)
                self.assertIsNone(make_screen(game).auto_skill_state())
                self.assertFalse(make_screen(game).set_auto_skill(not on))
                self.assertEqual([], game.taps)


class BossHpTest(unittest.TestCase):
    """The end screen's HP is taken once two captures agree."""

    def setUp(self):
        readers = fake_vision()
        readers.read_boss_hp = lambda frame, ocr: frame.hp
        patcher = mock.patch.object(screen_module, "vision", readers)
        patcher.start()
        self.addCleanup(patcher.stop)

    def screen(self, reads):
        game = FakeGame()
        game.end = True
        shown = iter(reads)

        def capture():
            frame = FakeGame.capture(game)
            frame.hp = next(shown)
            return frame

        game.capture = capture
        return make_screen(game)

    def test_two_equal_reads(self):
        hp = (49_399_316_779, 64_500_000_000)
        self.assertEqual(hp, self.screen([None, hp, hp]).boss_hp())

    def test_reads_that_never_agree_give_nothing(self):
        reads = [(1, 9), (2, 9), None, (3, 9), (1, 9), (2, 9)]
        self.assertIsNone(self.screen(reads).boss_hp())


class ViewOffsetTest(unittest.TestCase):
    """A camera dragged off its place is put back (2K PC 2026-10-01, T3)."""

    def setUp(self):
        patcher = mock.patch.object(screen_module, "vision", fake_vision())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dragged_camera_is_reset_by_toggling_twice(self):
        game = FakeGame()
        game.topdown = True
        game.offset = (-22.0, -75.0)
        screen = make_screen(game)
        frame = screen._ready_frame()
        self.assertEqual((0.0, 0.0), frame.offset)
        self.assertTrue(frame.topdown)

    def test_second_toggle_waits_for_the_fade(self):
        # The game ignores 切换视角 while the view fades (T19, 2026-10-01).
        class FadingGame(FakeGame):
            def tap(self, point):
                fading = bool(self.fade)
                super().tap(point)
                if _near(point, layout.VIEW_TOGGLE) and not fading:
                    self.fade = [20.0, 20.0, 20.0] + ([119.0] * 4 if self.topdown else [52.0] * 4)

        game = FadingGame()
        game.topdown = True
        game.offset = (-25.0, 89.0)
        frame = make_screen(game)._ready_frame()
        self.assertTrue(frame.topdown)
        self.assertEqual((0.0, 0.0), frame.offset)

    def test_a_zoomed_grid_is_put_back_by_toggling_twice(self):
        game = FakeGame()
        game.topdown = True
        game.grid = vision.Grid(0.9, 528.9, 442.4)  # 4K PC 2026-10-08, 水魔兽 T3
        screen = make_screen(game)
        frame = screen._ready_frame()
        self.assertIsNone(frame.grid)
        self.assertIsNone(screen._grid)

    def test_cells_are_pressed_where_a_grid_that_stays_zoomed_is_drawn(self):
        game = FakeGame()
        game.topdown = True
        game.zoom_stays = True
        game.grid = vision.Grid(0.9, 528.9, 442.4)
        screen = make_screen(game)
        state = screen.read_state(1)
        self.assertEqual(START, state.cells)
        self.assertEqual(game.grid, screen._grid)
        self.assertNotIn(None, game.holds)  # every press landed on a cell
        toggles = []
        game.tap = lambda point, tap=game.tap: toggles.append(point) or tap(point)
        screen.read_state(1)
        self.assertNotIn(layout.VIEW_TOGGLE, toggles)  # once known, not toggled again

    def test_frames_around_a_drag_that_panned_are_kept(self):
        # A drag that missed its unit panned the camera twice in real fights
        # (T3, T19 on 2026-10-01); keep what it started on to find out why.
        game = FakeGame()
        game.topdown = True
        screen = make_screen(game, screenshots={})
        saved = []
        screen._save_frame = lambda path, frame: saved.append((path.name, frame.offset))
        screen.drag(Drag((2, 3), (0, 0)))
        game.offset = (-25.0, 89.0)
        screen._ready_frame()
        self.assertEqual(2, len(saved))
        (before, at_drag), (after, panned) = saved
        self.assertTrue(before.endswith("_drag23-00_before.png"))
        self.assertTrue(after.endswith("_drag23-00_after.png"))
        self.assertEqual(((0.0, 0.0), (-25.0, 89.0)), (at_drag, panned))

    def test_only_the_newest_panned_frames_are_kept(self):
        import os
        import tempfile

        from src.tasks.fiend_hunt.screen import _keep_newest

        with tempfile.TemporaryDirectory() as folder:
            for number in range(25):
                path = Path(folder) / f"{number:02d}.png"
                path.write_bytes(b"png")
                os.utime(path, (1000 + number, 1000 + number))
            _keep_newest(Path(folder), 20)
            left = sorted(path.name for path in Path(folder).iterdir())
        self.assertEqual([f"{number:02d}.png" for number in range(5, 25)], left)

    def test_camera_in_place_is_left_alone(self):
        game = FakeGame()
        game.topdown = True
        game.offset = (2.0, -3.0)
        frame = make_screen(game)._ready_frame()
        self.assertEqual((2.0, -3.0), frame.offset)


class StillBattleTest(unittest.TestCase):
    """Leo 2026-10-06: a battle screen that doesn't move for 30 s is stuck."""

    def wait(self, frames, won=lambda f: False, lost=lambda f: False):
        import numpy as np

        from src.tasks.fiend_hunt import screen as screen_module

        clock = [0.0]
        shown = iter(frames)
        lines = []
        screen = GameFightScreen(
            SimpleNamespace(),
            ["克蕾西亚"],
            screen_input=SimpleNamespace(),
            capture=lambda: next(shown),
            ocr=lambda image: [],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            clock=lambda: clock[0],
            log=lines.append,
        )
        with (
            mock.patch.object(screen_module.vision, "planning_visible", lambda f: f is None),
            mock.patch.object(screen_module.vision, "battle_end_visible", lambda f: False),
            mock.patch.object(screen_module.vision, "victory_visible", won),
            mock.patch.object(
                screen_module.vision, "lost_word", lambda f, ocr: "DEFEAT" if lost(f) else None
            ),
            mock.patch.object(screen_module.vision, "end_word", lambda f, ocr: "DEFEAT"),
            mock.patch.object(screen_module.vision, "slot_count", lambda f: 1),
            mock.patch.object(screen_module.GameFightScreen, "_keep_stuck") as keep,
            mock.patch.object(screen_module.GameFightScreen, "_keep_picture"),
        ):
            result = screen.wait_after_battle()
        self.end_word = screen.end_word
        return result, clock[0], lines, keep, np

    def test_a_still_screen_stops_after_30_seconds(self):
        import numpy as np

        frozen = np.full((1080, 1920, 3), 90, np.uint8)
        result, seconds, lines, keep, _ = self.wait([frozen] * 1000)
        self.assertIsNone(result)
        self.assertLess(seconds, 35)
        self.assertTrue(any("没动" in line for line in lines))
        keep.assert_called_once()

    def test_a_moving_battle_is_waited_for(self):
        import numpy as np

        rng = np.random.default_rng(1)
        moving = [rng.integers(0, 255, (1080, 1920, 3), np.uint8) for _ in range(150)]
        planning = [None] * 10  # the planning screen comes back (None: planning here)
        result, seconds, _, keep, _ = self.wait(moving + planning)
        self.assertEqual("planning", result)
        self.assertGreater(seconds, 40)
        keep.assert_not_called()

    def test_talos_victory_ends_the_fight_as_won(self):
        # 塔洛斯战术教材 (2K PC 2026-10-28): VICTORY, not BATTLE END; the
        # tool waited on it until the player moved the mouse.
        import numpy as np

        rng = np.random.default_rng(2)
        moving = [rng.integers(0, 255, (1080, 1920, 3), np.uint8) for _ in range(20)]
        won = moving[-1]
        result, seconds, lines, keep, _ = self.wait(moving + [won] * 5, won=lambda f: f is won)
        self.assertEqual("end", result)
        self.assertEqual("victory", self.end_word)
        self.assertLess(seconds, 10)
        keep.assert_not_called()

    def test_a_lost_fight_is_read_as_text_and_ends(self):
        import numpy as np

        rng = np.random.default_rng(3)
        moving = [rng.integers(0, 255, (1080, 1920, 3), np.uint8) for _ in range(20)]
        lost = moving[-1]
        result, seconds, lines, _, _ = self.wait(moving + [lost] * 20, lost=lambda f: f is lost)
        self.assertEqual("end", result)
        self.assertEqual("lost", self.end_word)
        self.assertLess(seconds, 15)
        self.assertTrue(any("输了" in line for line in lines))

    def test_a_small_spinner_still_counts_as_still(self):
        import numpy as np

        frames = []
        for index in range(200):
            frame = np.full((1080, 1920, 3), 90, np.uint8)
            frame[500:520, 900 + index % 20 : 920 + index % 20] = 255  # a spinner
            frames.append(frame)
        result, seconds, _, keep, _ = self.wait(frames)
        self.assertIsNone(result)
        keep.assert_called_once()


class SizedGridTest(unittest.TestCase):
    """塔洛斯战术教材: the grid at its usual size is pressed where drawn; another
    size is zoomed back with the wheel (Leo 2026-10-28 「格子對就不動 … 有問題
    就用滾輪調整」)."""

    def screen(self, grids, percents=()):
        from src.tasks.fiend_hunt import screen as screen_module

        grids, percents = list(grids), list(percents)
        wheels, lines = [], []
        screen = GameFightScreen(
            SimpleNamespace(),
            ["克蕾西亚"],
            screen_input=SimpleNamespace(),
            capture=lambda: "frame",
            ocr=lambda image: [],
            sleep=lambda seconds: None,
            log=lines.append,
            grid_scales=screen_module.TALOS_GRID_SCALES,
            wheel=wheels.append,
        )
        patches = (
            mock.patch.object(screen_module.vision, "grid_on_screen", lambda f: grids.pop(0)),
            mock.patch.object(
                screen_module.vision,
                "zoom_percent",
                lambda f, ocr: percents.pop(0) if percents else None,
            ),
            mock.patch.object(GameFightScreen, "_settled_frame", lambda self: "frame"),
            mock.patch.object(screen_module.vision, "talos_layout", lambda f: True),
        )
        return screen, wheels, lines, patches

    def place(self, grids, percents=()):
        screen, wheels, lines, patches = self.screen(grids, percents)
        with patches[0], patches[1], patches[2], patches[3]:
            screen._place_grid("frame")
        return screen, wheels, lines

    def test_usual_size_needs_no_wheel_and_no_view_toggle(self):
        grid = vision.Grid(1.31, 499, 399)
        screen, wheels, lines = self.place([grid, grid])
        self.assertEqual(grid, screen._grid)
        self.assertEqual([], wheels)
        self.assertFalse(any("切换" in line for line in lines))

    def test_same_place_next_turn_is_read_once(self):
        grid = vision.Grid(1.31, 499, 399)
        screen, wheels, lines, patches = self.screen([grid, grid, grid])
        with patches[0], patches[1], patches[2], patches[3]:
            screen._place_grid("frame")
            screen._place_grid("frame")
        self.assertEqual(grid, screen._grid)

    def test_another_size_is_zoomed_back(self):
        small = vision.Grid(1.08, 581, 424)
        usual = vision.Grid(1.33, 492, 397)
        screen, wheels, lines = self.place([small, usual, usual], percents=[101])
        self.assertEqual([-8, 5], wheels)
        self.assertEqual(usual, screen._grid)
        self.assertTrue(any("101%" in line for line in lines))

    def test_zoom_nudged_when_the_percent_is_off(self):
        small = vision.Grid(1.08, 581, 424)
        usual = vision.Grid(1.28, 511, 403)
        screen, wheels, lines = self.place([small, usual, usual], percents=[92, 97])
        self.assertEqual([-8, 5, 1], wheels)

    def flips(self, grids, percents=()):
        screen, wheels, lines, patches = self.screen(grids, percents)
        taps = []
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            mock.patch.object(
                GameFightScreen, "_flip_view", lambda self: taps.append("flip") or "frame"
            ),
        ):
            screen._place_grid("frame")
        return screen, wheels, taps

    def test_no_grid_seen_tries_the_other_view_first(self):
        # 2K PC 2026-10-28 stages 5 and 8: the view was read wrong on a dark floor
        usual = vision.Grid(1.31, 499, 399)
        screen, wheels, taps = self.flips([None, usual, usual])
        self.assertEqual(["flip"], taps)
        self.assertEqual([], wheels)
        self.assertEqual(usual, screen._grid)

    def test_other_view_without_a_grid_goes_back_then_wheels(self):
        usual = vision.Grid(1.31, 499, 399)
        screen, wheels, taps = self.flips([None, None, usual, usual], percents=[101])
        self.assertEqual(["flip", "flip"], taps)
        self.assertEqual([-8, 5], wheels)

    def test_still_wrong_after_the_wheel_stops(self):
        small = vision.Grid(1.08, 581, 424)
        with self.assertRaises(ScreenReadError):
            self.place([small, small], percents=[80])

    def test_a_place_read_differently_each_time_stops(self):
        # 2K PC 2026-10-28 stage 2 T5: one read 100 px lower than the others
        reads = [
            vision.Grid(1.31, 499, 399),
            vision.Grid(1.31, 499, 498),
            vision.Grid(1.31, 499, 300),
        ]
        with self.assertRaises(ScreenReadError):
            self.place(reads)

    def test_two_agreeing_reads_win_over_one_odd_read(self):
        odd, good = vision.Grid(1.31, 499, 498), vision.Grid(1.31, 499, 399)
        screen, _, _ = self.place([odd, good, good])
        self.assertEqual(good, screen._grid)


class HoldOrderTest(unittest.TestCase):
    """Who stands where is held where the record put them last (Leo 2026-10-28
    「應該會記憶每個回合每個角色占哪個格子吧 我看你常常一格一格點 找角色」)."""

    def test_last_placed_cells_first_and_busy_read_on_the_drawn_grid(self):
        from src.tasks.fiend_hunt import screen as screen_module

        placed = {"甲": (1, 1), "乙": (1, 3)}
        record = FightRecord(
            turns={
                1: TurnState(1, 1, ("甲", "乙"), placed),
                3: TurnState(3, 1, ("甲", "乙"), {"甲": (0, 1), "乙": (2, 3)}),
            }
        )
        screen = make_screen(
            SimpleNamespace(capture=lambda: None), known=["甲", "乙"], record=record
        )
        screen._grid = vision.Grid(1.31, 499, 399)
        grids = []

        def busy(frame, cell, grid=None):
            grids.append(grid)
            return 60.0 if cell in placed.values() else 10.0

        with (
            mock.patch.object(screen_module.vision, "cell_busy_score", busy),
            mock.patch.object(screen_module.vision, "cells_by_busy", lambda frame, grid=None: []),
        ):
            order = screen._hold_order("frame", team=1, turn=3)
        self.assertEqual([(1, 1), (1, 3)], order)  # turn 1's places; turn 3's look empty
        self.assertTrue(grids and all(grid is screen._grid for grid in grids))


class PreemptSwitchTest(unittest.TestCase):
    def test_tapped_until_it_shows_on_then_deselected(self):
        from src.tasks.fiend_hunt import screen as screen_module

        taps, cleared = [], []
        shown = {"on": False}

        def tap(point):
            taps.append(point)
            shown["on"] = True

        screen = GameFightScreen(
            SimpleNamespace(),
            ["格兰希特"],
            screen_input=SimpleNamespace(tap=tap),
            capture=lambda: "frame",
            ocr=lambda image: [],
            sleep=lambda seconds: None,
        )
        with (
            mock.patch.object(GameFightScreen, "_select_slot", lambda self, slot: ("frame", 3, 1)),
            mock.patch.object(
                GameFightScreen, "_clear_selection", lambda self, frame: cleared.append(1)
            ),
            mock.patch.object(screen_module.vision, "preempt_beside", lambda f, ocr, row: row == 2),
            mock.patch.object(screen_module.vision, "preempt_on", lambda f, row: shown["on"]),
        ):
            self.assertTrue(screen.set_preempt(1, "技能1"))
            self.assertEqual([layout.preempt_switch(2)], taps)
            self.assertEqual([1], cleared)
            with self.assertRaises(ScreenReadError):
                screen.set_preempt(1, "技能2")  # no such card: nothing pressed
            self.assertEqual(1, len(taps))


class PostInputTest(unittest.TestCase):
    """The cursor stays on the cell after a release (2K PC 2026-10-07: put
    back 25 ms after it, the game selected the unit but opened no cards)."""

    def test_the_cursor_waits_on_the_cell_after_the_release(self):
        events = []
        win32api = SimpleNamespace(
            SetCursorPos=lambda pos: events.append(("cursor", pos)),
            MAKELONG=lambda x, y: (x, y),
        )
        win32con = SimpleNamespace(
            WM_MOUSEMOVE="move", WM_LBUTTONDOWN="down", WM_LBUTTONUP="up", MK_LBUTTON=1
        )
        interaction = SimpleNamespace(
            post=lambda message, *args: events.append((message,)),
            capture=SimpleNamespace(get_abs_cords=lambda x, y: (x, y)),
        )

        def operate(action, block, restore_cursor):
            action()
            events.append(("restore",))

        task = SimpleNamespace(
            executor=SimpleNamespace(interaction=interaction),
            width=1920,
            height=1080,
            operate=operate,
        )
        sleeps = []
        modules = {"win32api": win32api, "win32con": win32con}
        with (
            mock.patch.dict("sys.modules", modules),
            mock.patch.object(
                screen_module.time,
                "sleep",
                lambda seconds: (sleeps.append(seconds), events.append(("sleep", seconds))),
            ),
        ):
            for press in (
                lambda: screen_module.PostInput(task).hold((900.0, 600.0), 0.2),
                lambda: screen_module.PostInput(task).drag(
                    (900.0, 600.0), (1000.0, 600.0), 0.15, 0.3, 2
                ),
            ):
                events.clear()
                press()
                up = events.index(("up",))
                self.assertEqual(("sleep", screen_module.AFTER_RELEASE), events[up + 1])
                self.assertEqual(("restore",), events[up + 2])
