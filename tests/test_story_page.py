"""推主线 page: the mockup Leo saw (cards, the switch on the hero card's right,
the 它会做 card of the step at work lit)."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.ui.shell import story_page  # noqa: E402
from src.ui.shell.story_page import DOES, NOTES, StoryPage, lit_card  # noqa: E402


class StoryPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_each_step_lights_its_card(self):
        self.assertEqual(lit_card("跳过对话"), 0)
        self.assertEqual(lit_card("自动进行"), 1)
        self.assertEqual(lit_card("自动移动中"), 2)
        self.assertEqual(lit_card("按 F 互动"), 3)
        self.assertIsNone(lit_card("战斗中"))
        self.assertIsNone(lit_card("等你做完这一步"))

    def test_four_cards_each(self):
        self.assertEqual(len(DOES), 4)
        self.assertEqual(len(NOTES), 4)

    def test_running_lights_the_card_and_turns_the_switch_into_stop(self):
        task = mock.Mock(paused=False)
        page = StoryPage()
        with mock.patch.object(story_page.data, "task_by_class_name", return_value=task), \
                mock.patch.object(story_page.data, "busy", return_value=True), \
                mock.patch.object(story_page.data, "current_task", return_value=task), \
                mock.patch("src.tasks.BaseBD2Task.task_info_snapshot", return_value={"状态": "主线引导"}):
            page.refresh()
        self.assertEqual([card.is_on() for card in page.features], [False, False, True, False])
        self.assertEqual(page.switch.property("kind"), "danger")
        self.assertIn("停止", page.switch.text())

    def test_off_nothing_lit_and_the_switch_starts_it(self):
        page = StoryPage()
        with mock.patch.object(story_page.data, "task_by_class_name", return_value=mock.Mock()), \
                mock.patch.object(story_page.data, "busy", return_value=False):
            page.refresh()
        self.assertFalse(any(card.is_on() for card in page.features))
        self.assertEqual(page.switch.property("kind"), "primary")


if __name__ == "__main__":
    unittest.main()
