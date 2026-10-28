"""塔洛斯战术教材: shipped records, cleared-stage memory, stage order, the bar's picker."""

import json
import tempfile
import unittest
from pathlib import Path

from src.tasks.fiend_hunt.record import load_record
from src.tasks.fiend_hunt.recording import RECORD_FILE
from src.tasks.talos import stages


class ShippedRecordsTest(unittest.TestCase):
    def test_every_stage_has_a_record_that_loads(self):
        self.assertEqual(stages.missing_records(), [])
        for stage in range(1, stages.STAGE_COUNT + 1):
            record = load_record(stages.record_folder(stage) / RECORD_FILE)
            self.assertTrue(record.turns, stage)
            self.assertEqual(min(record.turns), 1, stage)

    def test_edition_changes_with_any_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for stage in range(1, stages.STAGE_COUNT + 1):
                path = stages.record_folder(stage, root) / RECORD_FILE
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"stage": stage}), encoding="utf-8")
            first = stages.edition(root)
            self.assertEqual(stages.edition(root), first)
            (stages.record_folder(5, root) / RECORD_FILE).write_text("{}", encoding="utf-8")
            self.assertNotEqual(stages.edition(root), first)


class ProgressTest(unittest.TestCase):
    def test_saved_and_loaded_for_the_same_edition_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sub" / stages.PROGRESS_FILE
            progress = stages.Progress("abc", {1, 2})
            progress.save(path)
            self.assertEqual(stages.Progress.load(path, "abc").cleared, {1, 2})
            self.assertEqual(stages.Progress.load(path, "next-month").cleared, set())
            self.assertTrue(stages.Progress.load(path, "abc").known)
            self.assertFalse(stages.Progress.load(path, "next-month").known)

    def test_last_run_failures_kept_until_cleared(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / stages.PROGRESS_FILE
            stages.Progress("abc", {1}, {7: "输了", 1: "旧的"}).save(path)
            loaded = stages.Progress.load(path, "abc")
            self.assertEqual(loaded.failed, {7: "输了"})  # a cleared stage drops its old failure

    def test_broken_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / stages.PROGRESS_FILE
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(stages.Progress.load(path, "abc").cleared, set())
            path.write_text(
                json.dumps({"edition": "abc", "cleared": [0, 3, "x", 10]}), encoding="utf-8"
            )
            self.assertEqual(stages.Progress.load(path, "abc").cleared, {3})

    def test_screen_wins_where_it_was_read(self):
        progress = stages.Progress("abc", {1, 2, 3})
        progress.merge_screen({2: False, 4: True})
        self.assertEqual(progress.cleared, {1, 3, 4})


class OrderTest(unittest.TestCase):
    def test_uncleared_in_grid_order(self):
        self.assertEqual(stages.to_play({1, 2, 5}), [3, 4, 6, 7, 8, 9])

    def test_chosen_first_then_on_from_it(self):
        self.assertEqual(stages.next_order(6, {1, 2}), [6, 7, 8, 9, 3, 4, 5])
        # a cleared stage can be chosen again (replayed)
        self.assertEqual(stages.next_order(1, {1, 2, 3, 4, 5, 6, 7, 8}), [1, 9])


class PickerTest(unittest.TestCase):
    def test_take_only_another_stage(self):
        picker = stages.StagePicker()
        picker.current = 3
        picker.pick(3)
        self.assertIsNone(picker.take())
        picker.pick(7)
        self.assertEqual(picker.take(), 7)
        self.assertIsNone(picker.take())  # taken once

    def test_out_of_range_ignored(self):
        picker = stages.StagePicker()
        picker.pick(0)
        picker.pick(10)
        self.assertIsNone(picker.chosen)


if __name__ == "__main__":
    unittest.main()
