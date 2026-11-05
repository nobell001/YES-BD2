"""快速狩猎 圣石属性: the player picks the element, 最少 by default, and the
one-time walk-through after the update (Leo 2026-10-20)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.tasks.quick_hunt import (
    QUICK_HUNT_STONE_CHOICES,
    QUICK_HUNT_STONE_KEY,
    QUICK_HUNT_STONE_LEAST,
)
from src.tasks.QuickHuntTask import QUICK_HUNT_NOTICE_KEY, STONE_NOTICE_KEY, QuickHuntTask
from src.ui.shell import new_setting_notice
from src.ui.shell.config_form import ConfigForm
from src.ui.shell.widgets import Segmented

app = QApplication.instance() or QApplication([])

COUNTS = {"火": 50, "水": 40, "风": 30, "光": 10, "暗": 20}


def _task() -> QuickHuntTask:
    task = object.__new__(QuickHuntTask)
    task.default_config = {}
    task.config_description = {}
    task.config_type = {}
    with mock.patch("src.tasks.DailyTask.BaseBD2Task.__init__", return_value=None):
        QuickHuntTask.__init__(task)
    task.config = dict(task.default_config)
    return task


class ElementTest(unittest.TestCase):
    def _run(self, setting):
        task = object.__new__(QuickHuntTask)
        task.config = {"快速狩猎界面等待秒数": 8.0}
        if setting is not None:
            task.config[QUICK_HUNT_STONE_KEY] = setting
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task._quick_hunt_enter_crystal_cave = lambda: True
        task._quick_hunt_resource_empty = lambda _resource: False
        reads = []
        task._quick_hunt_stone_counts = lambda: reads.append(1) or dict(COUNTS)
        picked = []
        task._quick_hunt_click_ocr = (
            lambda patterns, _roi, _timeout, name: picked.append(patterns[0]) or True
        )
        runs = []
        task._quick_hunt_execute_current_map = lambda mode, stage: runs.append(stage) or "done"
        self.assertTrue(task._quick_hunt_run_crystal_cave())
        return picked[0], runs, reads

    def test_default_is_least_held(self):
        self.assertEqual(QUICK_HUNT_STONE_LEAST, _task().config[QUICK_HUNT_STONE_KEY])
        pattern, runs, reads = self._run(None)
        self.assertIn("光", pattern)
        self.assertEqual(["光属性圣石"], runs)
        self.assertEqual([1], reads)

    def test_a_picked_element_is_farmed_without_reading_counts(self):
        pattern, runs, reads = self._run("火")
        self.assertIn("火", pattern)
        self.assertEqual(["火属性圣石"], runs)
        self.assertEqual([], reads)

    def test_an_unknown_value_falls_back_to_least(self):
        pattern, runs, _reads = self._run("雷")
        self.assertIn("光", pattern)

    def test_count_read_failure_still_stops_on_least(self):
        task = object.__new__(QuickHuntTask)
        task.config = {QUICK_HUNT_STONE_KEY: QUICK_HUNT_STONE_LEAST}
        task.log_info = lambda *_args, **_kwargs: None
        task._quick_hunt_stone_counts = lambda: None
        self.assertIsNone(task._quick_hunt_stone_element())


class FormTest(unittest.TestCase):
    def test_row_is_one_segmented_picker_with_six_options(self):
        task = _task()
        form = ConfigForm(task, keys=[QUICK_HUNT_STONE_KEY])
        _label, control, _sync = form._rows[QUICK_HUNT_STONE_KEY]
        self.assertIsInstance(control, Segmented)
        self.assertEqual(list(QUICK_HUNT_STONE_CHOICES), list(control._buttons))
        control._buttons["暗"].click()
        self.assertEqual("暗", task.config[QUICK_HUNT_STONE_KEY])

    def test_row_sits_under_the_rice_rows(self):
        keys = list(_task().default_config)
        self.assertEqual(keys.index("都双倍时") + 1, keys.index(QUICK_HUNT_STONE_KEY))


class NoticeTest(unittest.TestCase):
    def _load(self, saved):
        task = _task()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "QuickHuntTask.json"
            if saved is not None:
                path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")

            def load(_self):
                _self.config = {**_self.default_config, **(saved or {})}

            with mock.patch(
                "src.tasks.QuickHuntTask.get_relative_path", return_value=str(path)
            ), mock.patch("src.tasks.QuickHuntTask.BaseBD2Task.load_config", load):
                task.load_config()
        return task

    def test_players_from_before_keep_least_and_are_told_once(self):
        task = self._load({"启用": True, "金币双倍时": "金币"})
        self.assertTrue(task.config[STONE_NOTICE_KEY])
        self.assertEqual(QUICK_HUNT_STONE_LEAST, task.config[QUICK_HUNT_STONE_KEY])

    def test_new_install_and_later_starts_are_not_told(self):
        self.assertFalse(self._load(None).config[STONE_NOTICE_KEY])
        later = self._load({"金币双倍时": "金币", QUICK_HUNT_STONE_KEY: "水"})
        self.assertFalse(later.config[STONE_NOTICE_KEY])
        self.assertEqual("水", later.config[QUICK_HUNT_STONE_KEY])

    def test_shown_once_after_the_other_walk_throughs(self):
        quick = SimpleNamespace(config={QUICK_HUNT_NOTICE_KEY: True, STONE_NOTICE_KEY: True})
        tasks = {"QuickHuntTask": quick, "EventBattleTask": SimpleNamespace(config={})}
        with mock.patch.object(
            new_setting_notice.data, "task_by_class_name", side_effect=tasks.get
        ), mock.patch.object(new_setting_notice, "CoachMarks") as tour:
            self.assertTrue(new_setting_notice.show_pending(mock.Mock()))
            self.assertEqual(1, tour.call_count)
            self.assertTrue(quick.config[STONE_NOTICE_KEY])
            tour.call_args.args[2]()  # the rice walk-through closed
            self.assertEqual(2, tour.call_count)
            self.assertFalse(quick.config[STONE_NOTICE_KEY])
            tour.call_args.args[2]()
            self.assertEqual(2, tour.call_count)
            self.assertFalse(new_setting_notice.show_pending(mock.Mock()))

    def test_tour_lights_the_stone_row(self):
        shell = mock.Mock()
        control = object()
        shell.pages.get.return_value.form._rows = {QUICK_HUNT_STONE_KEY: (None, control, None)}
        first, second = new_setting_notice.stone_steps(shell)
        self.assertIs(shell.sidebar.items.get.return_value, first.target())
        second.before()
        shell.open_task.assert_called_once_with("daily", "快速狩猎")
        self.assertIs(control, second.target())


if __name__ == "__main__":
    unittest.main()
