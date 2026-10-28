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
