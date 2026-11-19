"""塔洛斯教材 page: nine tiles, the stages not cleared ticked to begin with
(Leo 2026-10-28 「要可以選擇關卡 預設全選排除打過的」), 开始打 plays the ticked."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.tasks.talos import stages
from src.ui.shell import actions, data, talos_page


# The flow and screen tests are written for a nine-stage period (3x3, records
# from 10-22), whatever period the shipped records are for now.
_NINE = []


def setUpModule():
    from datetime import date as _date

    for patch in (
        mock.patch.object(stages, "STAGE_COUNT", 9),
        mock.patch.object(stages, "missing_records", lambda root=None: []),
        mock.patch.object(stages, "records_made", lambda root=None: _date(2026, 10, 22)),
    ):
        patch.start()
        _NINE.append(patch)


def tearDownModule():
    while _NINE:
        _NINE.pop().stop()


class TalosPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.task = SimpleNamespace(
            enabled=False, stage_picker=stages.StagePicker(), chosen_stages=None
        )
        self.progress = stages.Progress("x", {1, 2, 4}, {7: "第 1 回合输了"})
        self.started = []
        for patch in (
            mock.patch.object(
                talos_page,
                "_progress",
                lambda: stages.Progress(
                    "x",
                    set(self.progress.cleared),
                    dict(self.progress.failed),
                    self.progress.known,
                ),
            ),
            mock.patch.object(data, "task_by_class_name", lambda name: self.task),
            mock.patch.object(data, "current_task", lambda: None),
            mock.patch.object(actions, "start", lambda task, window: self.started.append(task)),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.page = talos_page.TalosPage()
        self.page.refresh()

    def ticked(self):
        return {stage for stage, tile in self.page.tiles.items() if tile.check.isChecked()}

    def test_not_cleared_ticked_to_begin_with(self):
        self.assertEqual({3, 5, 6, 7, 8, 9}, self.ticked())
        self.assertIn("6", self.page.start_button.text())
        self.assertEqual("上次没打下来", self.page.tiles[7].word.text())
        self.assertIn("第 1 回合输了", self.page.tiles[7].toolTip())

    def test_untouched_ticks_leave_the_choice_to_the_list(self):
        self.page.start()
        self.assertIsNone(self.task.chosen_stages)  # the task reads the ✕ itself

    def test_a_new_install_says_it_has_not_looked_yet(self):
        self.progress = stages.Progress("x", known=False)
        self.page.refresh()
        self.assertEqual("还没看过", self.page.tiles[1].word.text())
        self.assertEqual(set(range(1, 10)), self.ticked())
        self.assertIn("先看", self.page.count.text())

    def test_the_count_follows_the_stages(self):
        self.progress = stages.Progress("x", {1})
        self.page.refresh()
        self.assertIn("已打完 1/9", self.page.count.text())

    def test_ticked_stages_are_the_run(self):
        self.page.tiles[1].check.toggle()  # replay a cleared one
        self.page.tiles[9].check.toggle()  # and leave 9 out
        self.page.refresh()
        self.assertEqual({1, 3, 5, 6, 7, 8}, self.ticked())
        self.page.start()
        self.assertEqual([self.task], self.started)
        self.assertEqual([1, 3, 5, 6, 7, 8], self.task.chosen_stages)

    def test_nothing_ticked_cannot_start(self):
        for stage in list(self.ticked()):
            self.page.tiles[stage].check.toggle()
        self.page.refresh()
        self.assertFalse(self.page.start_button.isEnabled())
        self.page.start()
        self.assertEqual([], self.started)

    def test_after_a_run_the_ticks_follow_what_is_cleared(self):
        self.page.tiles[1].check.toggle()
        with mock.patch.object(data, "current_task", lambda: self.task):
            self.task.enabled = True
            self.task.stage_picker.current = 3
            self.page.refresh()
            self.assertFalse(self.page.start_button.isEnabled())
            self.assertEqual("正在打", self.page.tiles[3].word.text())
        self.task.enabled = False
        self.progress.cleared |= {1, 3, 5}
        self.page.refresh()
        self.assertEqual({6, 7, 8, 9}, self.ticked())


if __name__ == "__main__":
    unittest.main()


class TalosInCloneTest(TalosPageTest):
    """Leo 2026-11-19 「這個也要能在桌面分身跑」: 「在桌面分身跑」 under 开始打,
    the ticks go with the job, a run there shows here."""

    def setUp(self):
        super().setUp()
        self.task.name = "塔洛斯战术教材"
        self.opened = []
        flow = talos_page.clone_flow
        for target, name, value in (
            (flow, "available", lambda: True),
            (flow, "busy_in_clone", lambda: False),
            (flow, "ready_to_go", lambda: True),
            (flow, "remote_task", lambda: None),
            (flow, "open_clone", lambda window, task, stages=None: self.opened.append((task, stages))),
            (actions, "can_start", lambda: True),
            (data, "busy", lambda: False),
        ):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.page.show()
        self.addCleanup(self.page.close)
        self.page.refresh()

    def test_the_clone_start_is_under_the_start(self):
        self.assertTrue(self.page.start_clone.isVisible())
        self.assertTrue(self.page.start_clone.isEnabled())
        self.assertIn("在桌面分身跑", self.page.start_clone.text())

    def test_untouched_ticks_go_as_the_list_choice(self):
        self.page.start_in_clone()
        self.assertEqual([(self.task, None)], self.opened)
        self.assertEqual([], self.started)  # nothing runs on this desktop

    def test_ticked_stages_go_to_the_clone(self):
        self.page.tiles[9].check.toggle()
        self.page.start_in_clone()
        self.assertEqual([(self.task, [3, 5, 6, 7, 8])], self.opened)

    def test_a_run_in_the_clone_shows_here(self):
        from src.ui.shell.clone_flow import RemoteTask

        remote = RemoteTask({"task": "塔洛斯战术教材", "running": True})
        with mock.patch.object(talos_page.clone_flow, "remote_task", lambda: remote):
            self.page.refresh()
            self.assertFalse(self.page.start_button.isEnabled())
            self.assertIn("桌面分身", self.page.start_button.text())
            self.assertFalse(self.page.start_clone.isVisible())

    def test_hidden_without_clone_support(self):
        with mock.patch.object(talos_page.clone_flow, "available", lambda: False):
            self.page.refresh()
            self.assertFalse(self.page.start_clone.isVisible())


class CloneJobStagesTest(unittest.TestCase):
    """The ticks reach the task in the clone through the job file."""

    def test_stages_ride_the_job(self):
        import json
        import tempfile
        from pathlib import Path

        from src.utils import clone_desktop

        with tempfile.TemporaryDirectory() as folder:
            job = Path(folder) / "job.json"
            with (
                mock.patch.object(clone_desktop, "DATA_DIR", Path(folder)),
                mock.patch.object(clone_desktop, "JOB_FILE", job),
            ):
                clone_desktop.request_job("塔洛斯战术教材", None, stages=[3, 5])
                self.assertEqual([3, 5], json.loads(job.read_text(encoding="utf-8"))["stages"])
                clone_desktop.request_job("塔洛斯战术教材", None)
                self.assertNotIn("stages", json.loads(job.read_text(encoding="utf-8")))

    def test_the_task_in_the_clone_takes_them(self):
        from src.ui.shell import clone_flow

        task = SimpleNamespace(chosen_stages=None)
        clone_flow._take_stages(task, [5, 3])
        self.assertEqual([3, 5], task.chosen_stages)
        clone_flow._take_stages(task, None)
        self.assertIsNone(task.chosen_stages)
        other = SimpleNamespace()
        clone_flow._take_stages(other, [1])  # a task without stages: untouched
        self.assertFalse(hasattr(other, "chosen_stages"))
