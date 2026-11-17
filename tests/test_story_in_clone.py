"""Leo 2026-11-17 「桌面分身也要可以跑劇情」: the 推剧情 page starts it in the
桌面分身 (首页's 「在桌面分身跑」 only ran 一键日常), shows the run there and
stops it from here."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.ui.shell import story_page  # noqa: E402
from src.ui.shell.clone_flow import RemoteTask  # noqa: E402
from src.ui.shell.story_page import StoryPage  # noqa: E402


def _task():
    task = mock.Mock(paused=False)
    task.name = "推剧情"
    return task


class StoryInCloneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.task = _task()
        self.flow = story_page.clone_flow
        for target, name, value in (
            (story_page.data, "task_by_class_name", self.task),
            (story_page.data, "busy", False),
            (story_page.data, "executor", object()),
            (self.flow, "available", True),
            (self.flow, "busy_in_clone", False),
            (self.flow, "remote_task", None),
        ):
            patch = mock.patch.object(target, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        self.page = StoryPage()
        self.page.show()
        self.addCleanup(self.page.close)

    def _remote(self, **status):
        status = {"task": "推剧情", "running": True, "stage": "主线引导", **status}
        self.flow.remote_task.return_value = RemoteTask(status)

    def test_clone_start_shown_under_the_switch(self):
        self.page.refresh()
        self.assertTrue(self.page.start_clone.isVisible())
        self.assertTrue(self.page.start_clone.isEnabled())
        self.assertIn("在桌面分身跑", self.page.start_clone.text())
        self.assertFalse(self.page.where.isVisible())

    def test_hidden_without_clone_support(self):
        self.flow.available.return_value = False
        self.page.refresh()
        self.assertFalse(self.page.start_clone.isVisible())

    def test_press_opens_the_clone_with_story_after_the_reminder(self):
        with mock.patch.object(self.flow, "ready_to_go", return_value=True), \
                mock.patch.object(story_page, "confirm_start", return_value=True) as remind, \
                mock.patch.object(self.flow, "open_clone") as open_clone, \
                mock.patch.object(story_page.actions, "start") as desktop_start:
            self.page.start_clone.click()
        remind.assert_called_once_with(self.page.window(), clone=True)
        open_clone.assert_called_once_with(self.page.window(), self.task)
        desktop_start.assert_not_called()

    def test_cancelled_reminder_opens_nothing(self):
        with mock.patch.object(self.flow, "ready_to_go", return_value=True), \
                mock.patch.object(story_page, "confirm_start", return_value=False), \
                mock.patch.object(self.flow, "open_clone") as open_clone:
            self.page.start_in_clone()
        open_clone.assert_not_called()

    def test_not_set_up_goes_through_the_setup_notes(self):
        with mock.patch.object(self.flow, "ready_to_go", return_value=False), \
                mock.patch.object(self.flow, "ask_and_start") as ask, \
                mock.patch.object(self.flow, "open_clone") as open_clone:
            self.page.start_in_clone()
        ask.assert_called_once_with(self.page.window(), self.task)
        open_clone.assert_not_called()

    def test_run_in_clone_shows_here_and_stop_goes_there(self):
        self._remote(stage="主线引导")
        self.page.refresh()
        self.assertTrue(self.page.running())
        self.assertTrue(self.page.where.isVisible())
        self.assertFalse(self.page.start_clone.isVisible())
        self.assertIn("停止", self.page.switch.text())
        self.assertTrue(self.page.switch.isEnabled())
        self.assertEqual([card.is_on() for card in self.page.features], [False, False, True, False])
        with mock.patch.object(self.flow, "remote_control") as control, \
                mock.patch.object(story_page.actions, "stop") as local_stop:
            self.page.switch.click()
        control.assert_called_once_with("stop")
        local_stop.assert_not_called()

    def test_paused_in_clone_says_so(self):
        self._remote(stage="回到主页，已暂停", paused=True)
        self.page.refresh()
        self.assertIn("暂停", self.page.state.text())
        self.assertIn("回到主页", self.page.now.text())
        self.assertFalse(any(card.is_on() for card in self.page.features))

    def test_page_continue_resumes_the_run_in_the_clone(self):
        """#567's 继续 on this page (for a hidden capsule) reaches the clone."""
        self._remote(stage="回到主页，已暂停", paused=True)
        self.page.refresh()
        self.assertTrue(self.page.resume.isVisibleTo(self.page))
        with mock.patch.object(self.flow, "remote_control") as control, \
                mock.patch.object(story_page.actions, "toggle_pause") as local_pause:
            self.page.resume.click()
        control.assert_called_once_with("resume")
        local_pause.assert_not_called()

    def test_another_task_in_clone_is_not_story(self):
        self._remote(task="一键完成日常")
        self.flow.busy_in_clone.return_value = True
        self.page.refresh()
        self.assertFalse(self.page.running())
        self.assertFalse(self.page.where.isVisible())
        self.assertFalse(self.page.start_clone.isEnabled())

    def test_desktop_run_hides_the_clone_start(self):
        story_page.data.busy.return_value = True
        with mock.patch.object(story_page.data, "current_task", return_value=self.task), \
                mock.patch("src.tasks.BaseBD2Task.task_info_snapshot", return_value={"状态": "对话"}):
            self.page.refresh()
        self.assertFalse(self.page.start_clone.isVisible())
        self.assertFalse(self.page.where.isVisible())


if __name__ == "__main__":
    unittest.main()
