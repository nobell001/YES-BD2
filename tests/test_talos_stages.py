"""塔洛斯战术教材: shipped records, cleared-stage memory, stage order, the bar's picker."""

import json
import tempfile
import unittest
from datetime import date
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


class CountTest(unittest.TestCase):
    def folders(self, root, numbers):
        for stage in numbers:
            path = stages.record_folder(stage, root) / RECORD_FILE
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")

    def test_the_records_and_the_guide_say_how_many_stages(self):
        # 2026-11-19: sixteen stages; the guide may list some without a chart yet
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.folders(root, [1, 2, 3, 5])
            self.assertEqual(stages.stage_count(root), 5)
            self.assertEqual(stages.missing_records(root), [4])
            (root / stages.SOURCE_FILE).write_text(
                json.dumps({"stages": 16, "made": "2026-11-19"}), encoding="utf-8"
            )
            self.assertEqual(stages.stage_count(root), 16)
            self.assertEqual(stages.missing_records(root), [4, *range(6, 17)])
            self.assertEqual(stages.records_made(root), date(2026, 11, 19))

    def test_a_square_grid_for_the_count(self):
        self.assertEqual([stages.grid_columns(n) for n in (9, 10, 12, 16)], [3, 4, 4, 4])

    def test_shipped_records_say_when_they_were_made(self):
        self.assertIsNotNone(stages.records_made())


class PeriodTest(unittest.TestCase):
    """Leo 2026-11-19 「偵測到換賽季 就先把戰術教材鎖起來」「以後可以自動關 不用一直靠更新」."""

    TODAY = date(2026, 11, 19)

    def change(self, **given):
        values = dict(count=9, columns=3, end=None, made=date(2026, 10, 22), seen_end=None, today=self.TODAY)
        values.update(given)
        return stages.period_change(**values)

    def test_days_left_on_the_list(self):
        self.assertEqual(stages.period_end("活动还剩27天", self.TODAY), date(2026, 12, 16))
        self.assertEqual(stages.period_end("活動 還剩 3 天", self.TODAY), date(2026, 11, 22))
        self.assertEqual(stages.period_end("活动 还剩5小时", self.TODAY), self.TODAY)
        self.assertIsNone(stages.period_end("塔洛斯战术教材", self.TODAY))

    def test_the_records_own_period(self):
        # 2K PC 10-28: 21 days left with the records made 10-22
        self.assertEqual(self.change(end=date(2026, 11, 18), today=date(2026, 10, 28)), "")
        self.assertEqual(self.change(columns=None), "")  # nothing read: nothing to say

    def test_another_grid_is_another_period(self):
        self.assertIn("4x4", self.change(columns=4))

    def test_an_end_long_after_the_records_is_another_period(self):
        # 11-19: 4x4 list read as unsure, 27 days left, records from 10-22
        self.assertIn("12-16", self.change(columns=None, end=date(2026, 12, 16)))
        # the new period's records (made 11-19) fit it
        self.assertEqual(
            self.change(count=16, columns=4, end=date(2026, 12, 16), made=date(2026, 11, 19)), ""
        )

    def test_an_end_other_than_the_one_seen_is_another_period(self):
        # the same grid, records made late in the last period
        late = dict(count=16, columns=4, made=date(2026, 12, 8), seen_end=date(2026, 12, 16))
        self.assertEqual(self.change(end=date(2026, 12, 17), **late), "")  # read a day apart
        self.assertIn("01-13", self.change(end=date(2027, 1, 13), **late))
        # nothing read now: the end seen has long passed
        self.assertIn("已经结束", self.change(today=date(2026, 12, 19), **late))
        # Leo 「會不會卡到最後一天」: 10-28 read 21 days = 11-18, the period ran
        # until the 11-19 update; the last day(s) still play
        old = dict(seen_end=date(2026, 11, 18))
        self.assertEqual("", self.change(today=date(2026, 11, 19), **old))
        self.assertEqual("", self.change(today=date(2026, 11, 19), end=date(2026, 11, 19), **old))  # 「还剩5小时」


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

    def test_period_end_kept_for_the_edition(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / stages.PROGRESS_FILE
            stages.Progress("abc", {1}, period_end=date(2026, 12, 16)).save(path)
            self.assertEqual(stages.Progress.load(path, "abc").period_end, date(2026, 12, 16))
            # new records (a tool update): the end is read again
            self.assertIsNone(stages.Progress.load(path, "next-period").period_end)

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
                json.dumps({"edition": "abc", "cleared": [0, 3, "x", 99]}), encoding="utf-8"
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
