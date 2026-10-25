import unittest
from unittest import mock

from src.tasks import BaseBD2Task as base_module
from src.tasks.BaseBD2Task import BaseBD2Task


SIGNALS = dict(
    left_hits=2,
    required_left_hits=2,
    brightness=49.0,
    brightness_threshold=185.0,
    gacha_ocr_text="抽抽乐",
    context="回到主页",
)


class HomeAnnouncementEscapeTest(unittest.TestCase):
    """Live 2026-10-24: started on 通行证, whose dim backdrop shows 主页; the
    blank spot was clicked for a minute without leaving the page."""

    def _task(self):
        task = object.__new__(BaseBD2Task)
        task.info_set = lambda *_args: None
        task.logs = []
        task.log_info = lambda text, **_kwargs: task.logs.append(text)
        task._sleep_after_recognition = lambda: None
        task.actions = []
        task.operate_click = lambda x, y, **_kwargs: task.actions.append("click")
        task.tap_escape = lambda **_kwargs: task.actions.append("esc") or True
        return task

    def _clear_at(self, task, seconds):
        with mock.patch.object(base_module, "monotonic", return_value=seconds):
            return task.clear_temporary_home_announcement_if_needed(**SIGNALS)

    def test_every_third_clear_in_a_row_is_escape(self):
        task = self._task()
        for seconds in (10, 15, 20, 25, 30, 35):
            self.assertTrue(self._clear_at(task, seconds))
        self.assertEqual(["click", "click", "esc", "click", "click", "esc"], task.actions)
        self.assertTrue(any("Esc" in line for line in task.logs))

    def test_a_long_gap_starts_the_count_again(self):
        task = self._task()
        for seconds in (10, 15, 100, 105):
            self._clear_at(task, seconds)
        self.assertEqual(["click"] * 4, task.actions)

    def test_bright_home_does_nothing(self):
        task = self._task()
        with mock.patch.object(base_module, "monotonic", return_value=10):
            cleared = task.clear_temporary_home_announcement_if_needed(
                **{**SIGNALS, "brightness": 200.0}
            )
        self.assertFalse(cleared)
        self.assertEqual([], task.actions)


if __name__ == "__main__":
    unittest.main()
