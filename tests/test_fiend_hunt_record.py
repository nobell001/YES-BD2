import json
import tempfile
import unittest
from pathlib import Path

from src.tasks.fiend_hunt.record import (
    FightRecord,
    TurnState,
    TurnStateError,
    load_record,
    record_from_dict,
    record_to_dict,
    save_record,
)

CELLS = {"克蕾西亚": (2, 0), "马莫尼勒": (1, 3), "艾尼尔": (2, 1)}
ORDER = ("克蕾西亚", "马莫尼勒", "艾尼尔")


def sample_record():
    turn_1 = TurnState(1, 1, ORDER, CELLS, skills={"克蕾西亚": "2"}, bursts={"克蕾西亚": 2})
    turn_3 = TurnState(
        3,
        1,
        ("克蕾西亚", "艾尼尔"),
        dict(CELLS, 克蕾西亚=(1, 0)),
        dead=["马莫尼勒"],
    )
    turn_5 = TurnState(5, 2, ("黛安娜",), {"黛安娜": (1, 1), "魔法革新者": (0, 1)})
    return FightRecord(
        turns={1: turn_1, 3: turn_3, 5: turn_5},
        title="模拟战斗 Lv25",
        screenshots={1: "turn01.png", 3: "turn03.png"},
    )


class TurnStateTest(unittest.TestCase):
    def test_inputs_are_normalised(self):
        state = TurnState(
            1, 1, list(ORDER), {"克蕾西亚": [2, 0], "马莫尼勒": (1, 3), "艾尼尔": (2, 1)}
        )
        self.assertEqual(ORDER, state.order)
        self.assertEqual((2, 0), state.cells["克蕾西亚"])
        self.assertEqual(set(CELLS), state.living)

    def test_broken_states_are_refused(self):
        broken = {
            "turn below 1": dict(turn=0),
            "team below 1": dict(team=0),
            "two units on one cell": dict(cells=dict(CELLS, 艾尼尔=(2, 0))),
            "cell off the grid": dict(cells=dict(CELLS, 艾尼尔=(3, 0))),
            "order repeats a unit": dict(order=("克蕾西亚", "克蕾西亚", "艾尼尔")),
            "order unit not on the grid": dict(order=ORDER + ("杰尼斯",)),
            "dead unit in the order": dict(dead=["艾尼尔"]),
            "dead unit without a cell": dict(dead=["杰尼斯"]),
            "skill for a dead unit": dict(
                order=("克蕾西亚", "马莫尼勒"), dead=["艾尼尔"], skills={"艾尼尔": "1"}
            ),
            "burst for a unit not on the grid": dict(bursts={"杰尼斯": 2}),
            "burst below 0": dict(bursts={"克蕾西亚": -1}),
            "burst not a number": dict(bursts={"克蕾西亚": "2"}),
        }
        for reason, changes in broken.items():
            fields = dict(turn=1, team=1, order=ORDER, cells=CELLS) | changes
            with self.subTest(reason), self.assertRaises(TurnStateError):
                TurnState(**fields)


class FightRecordTest(unittest.TestCase):
    def test_a_temporary_costume_follows_the_entry_that_replaced_it(self):
        # Leo 2026-10-07: a save made with a costume from the official notice
        # still finds it once souseha's entry replaced it (costumes.py aliases)
        from unittest import mock

        from src.tasks.fiend_hunt import costumes

        record = FightRecord(
            turns={
                1: TurnState(
                    1,
                    1,
                    ORDER,
                    CELLS,
                    skills={"克蕾西亚": "2"},
                    costumes={"克蕾西亚": "official_x"},
                )
            },
            cards={"克蕾西亚": {"技能2": "official_x"}},
        )
        book = costumes.CharacterBook(aliases={"official_x": "Claasia_9"})
        with mock.patch.object(costumes, "book", return_value=book):
            loaded = record_from_dict(record_to_dict(record))
        self.assertEqual({"克蕾西亚": "Claasia_9"}, loaded.turns[1].costumes)
        self.assertEqual({"克蕾西亚": {"技能2": "Claasia_9"}}, loaded.cards)

    def test_preempt_kept_per_skill_card(self):
        state = TurnState(1, 1, ("甲", "乙"), {"甲": (1, 1), "乙": (1, 3)}, preempt={"乙": "技能1"})
        record = FightRecord(turns={1: state})
        data = record_to_dict(record)
        self.assertEqual({"乙": "技能1"}, data["turns"][0]["preempt"])
        self.assertEqual({"乙": "技能1"}, record_from_dict(data).turns[1].preempt)
        self.assertNotIn("preempt", record_to_dict(sample_record())["turns"][0])
        with self.assertRaises(TurnStateError):
            TurnState(1, 1, ("甲",), {"甲": (1, 1)}, preempt={"甲": "攻击"})

    def test_save_and_load_give_the_same_record(self):
        record = sample_record()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "record.json"
            save_record(record, path)
            text = path.read_text(encoding="utf-8")
            loaded = load_record(path)
        self.assertIn("克蕾西亚", text)  # readable, not \u escapes
        self.assertEqual(record, loaded)
        self.assertEqual(frozenset({"马莫尼勒"}), loaded.turns[3].dead)
        self.assertEqual("turn03.png", loaded.screenshots[3])

    def test_json_layout(self):
        data = record_to_dict(sample_record())
        self.assertEqual(1, data["version"])
        first = data["turns"][0]
        self.assertEqual([2, 0], first["cells"]["克蕾西亚"])
        self.assertEqual(list(ORDER), first["order"])
        self.assertEqual("turn01.png", first["screenshot"])
        self.assertNotIn("screenshot", data["turns"][2])
        self.assertEqual({"克蕾西亚": 2}, first["bursts"])
        self.assertNotIn("bursts", data["turns"][1])  # saves from before 爆发 still load

    def test_a_save_without_bursts_loads(self):
        data = record_to_dict(sample_record())
        del data["turns"][0]["bursts"]
        self.assertEqual({}, record_from_dict(data).turns[1].bursts)

    def test_switching_back_to_an_earlier_team_is_refused(self):
        turns = {
            1: TurnState(1, 2, ("黛安娜",), {"黛安娜": (1, 1)}),
            3: TurnState(3, 1, ORDER, CELLS),
        }
        with self.assertRaisesRegex(TurnStateError, "换不回去"):
            FightRecord(turns=turns)

    def test_turn_key_must_match_the_turn(self):
        with self.assertRaises(TurnStateError):
            FightRecord(turns={3: TurnState(1, 1, ORDER, CELLS)})

    def test_screenshot_needs_a_saved_turn(self):
        with self.assertRaises(TurnStateError):
            FightRecord(turns={1: TurnState(1, 1, ORDER, CELLS)}, screenshots={3: "turn03.png"})

    def test_bad_files_are_refused(self):
        good = record_to_dict(sample_record())

        def changed(**turn_changes):
            data = json.loads(json.dumps(good))
            data["turns"][0].update(turn_changes)
            return data

        duplicate = json.loads(json.dumps(good))
        duplicate["turns"].append(duplicate["turns"][0])
        broken = {
            "not an object": [],
            "unknown version": dict(good, version=2),
            "turns missing": {"version": 1},
            "turn as text": changed(turn="1"),
            "team as bool": changed(team=True),
            "cell with three numbers": changed(cells={"克蕾西亚": [2, 0, 1]}),
            "order not a list": changed(order="克蕾西亚"),
            "empty name": changed(order=[""]),
            "duplicate turn": duplicate,
        }
        for reason, data in broken.items():
            with self.subTest(reason), self.assertRaises(TurnStateError):
                record_from_dict(data)

    def test_invalid_json_file_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "record.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(TurnStateError):
                load_record(path)


if __name__ == "__main__":
    unittest.main()


class ChartEditTest(unittest.TestCase):
    """Turns the player changed on the chart (Leo 2026-10-06)."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        save_record(sample_record(), self.folder / "record.json")

    def test_edited_units_are_saved_and_loaded(self):
        record = FightRecord(
            turns=sample_record().turns,
            screenshots={1: "turn01.png"},
            edited={1: {"艾尼尔"}},
        )
        data = record_to_dict(record)
        self.assertEqual(["艾尼尔"], data["turns"][0]["edited"])
        self.assertNotIn("edited", data["turns"][1])
        self.assertEqual({1: frozenset({"艾尼尔"})}, record_from_dict(data).edited)

    def test_an_edited_unit_must_be_alive_on_that_turn(self):
        with self.assertRaises(TurnStateError):
            FightRecord(turns=sample_record().turns, edited={3: {"马莫尼勒"}})

    def test_a_changed_card_marks_only_that_unit(self):
        from src.tasks.fiend_hunt.saves import edit_turn

        before = sample_record().turns[1]
        state = TurnState(1, 1, ORDER, CELLS, skills={"克蕾西亚": "攻击"}, bursts={})
        edit_turn(self.folder, state, ["克蕾西亚"])

        record = load_record(self.folder / "record.json")
        self.assertEqual("攻击", record.turns[1].skills["克蕾西亚"])
        self.assertEqual({1: frozenset({"克蕾西亚"})}, record.edited)
        self.assertEqual(before.cells, record.turns[1].cells)

    def test_a_changed_order_marks_everyone(self):
        from src.tasks.fiend_hunt.saves import edit_turn

        order = ("马莫尼勒", "克蕾西亚", "艾尼尔")
        edit_turn(self.folder, TurnState(1, 1, order, CELLS), [])

        record = load_record(self.folder / "record.json")
        self.assertEqual(order, record.turns[1].order)
        self.assertEqual(frozenset(ORDER), record.edited[1])

    def test_a_moved_cell_is_saved_without_marking_a_card(self):
        from src.tasks.fiend_hunt.saves import edit_turn

        moved = dict(CELLS, 克蕾西亚=(0, 0))
        edit_turn(self.folder, TurnState(1, 1, ORDER, moved), [])

        record = load_record(self.folder / "record.json")
        self.assertEqual((0, 0), record.turns[1].cells["克蕾西亚"])
        self.assertEqual(frozenset(), record.edited.get(1, frozenset()))

    def test_team_and_units_cannot_be_changed_here(self):
        from src.tasks.fiend_hunt.saves import edit_turn

        with self.assertRaises(TurnStateError):
            edit_turn(self.folder, TurnState(1, 2, ORDER, CELLS), [])
        fewer = {unit: cell for unit, cell in CELLS.items() if unit != "艾尼尔"}
        with self.assertRaises(TurnStateError):
            edit_turn(self.folder, TurnState(1, 1, ORDER[:2], fewer), [])

    def test_a_unit_added_to_a_team_joins_each_of_its_turns(self):
        from src.tasks.fiend_hunt.saves import set_team

        set_team(self.folder, 1, [*ORDER, "黛安娜"])

        record = load_record(self.folder / "record.json")
        for number in (1, 3):
            state = record.turns[number]
            self.assertEqual("黛安娜", state.order[-1])
            self.assertEqual("攻击", state.skills["黛安娜"])
            self.assertEqual((0, 3), state.cells["黛安娜"])  # front column, first free
            self.assertEqual(frozenset({"黛安娜"}), record.edited[number])
        self.assertEqual(("黛安娜",), record.turns[5].order)  # TEAM2 untouched

    def test_a_unit_removed_from_a_team_leaves_its_turns_dead_or_alive(self):
        from src.tasks.fiend_hunt.saves import set_team

        set_team(self.folder, 1, ["克蕾西亚", "艾尼尔"])

        record = load_record(self.folder / "record.json")
        self.assertEqual(("克蕾西亚", "艾尼尔"), record.turns[1].order)
        self.assertNotIn("马莫尼勒", record.turns[3].cells)  # its tombstone too
        self.assertEqual(frozenset(), record.turns[3].dead)
        self.assertEqual(frozenset({"克蕾西亚", "艾尼尔"}), record.edited[1])

    def test_a_team_keeps_one_living_unit(self):
        from src.tasks.fiend_hunt.saves import set_team

        with self.assertRaises(TurnStateError):
            set_team(self.folder, 2, ["魔法革新者"])

    def test_deleting_an_edited_turn_drops_its_edit(self):
        from src.tasks.fiend_hunt.saves import delete_turn, edit_turn

        edit_turn(self.folder, TurnState(1, 1, ORDER, CELLS), ["艾尼尔"])
        self.assertTrue(delete_turn(self.folder, 1))
        self.assertEqual({}, load_record(self.folder / "record.json").edited)
