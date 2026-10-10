"""HomePopularityTask only clicks its fixed points on a confirmed visit page."""

import unittest
from unittest import mock

from src.tasks.WeeklyTasks import (
    LIKE_BUTTON_POINT,
    NEXT_HOME_POINT,
    HomePopularityTask,
)


def _task(on_page):
    task = object.__new__(HomePopularityTask)
    task.name = "小屋增加人气"
    task.config = {"点赞次数": 3, "最多翻看小屋数": 8}
    task.info_set = lambda *a: None
    task.log_info = lambda *a, **k: None
    task._open_page_from_home = lambda *a: True
    task._wait_for_title = lambda *a, **k: True
    task._leave_to_home = mock.Mock(return_value=True)
    task.clicks = []
    task._click_reference = lambda x, y, after_sleep=0: task.clicks.append((x, y))
    task._on_visited_home = on_page
    task.log_warning = lambda *a, **k: None
    task._click_until_changed = lambda _label, click, _rois, **_k: click() or True
    return task


class HomePopularityTest(unittest.TestCase):
    def test_no_like_or_next_click_off_the_visit_page(self):
        task = _task(lambda: False)
        self.assertFalse(task.run_claim())
        self.assertNotIn(LIKE_BUTTON_POINT, task.clicks)
        self.assertNotIn(NEXT_HOME_POINT, task.clicks)
        task._leave_to_home.assert_called_once()

    def test_likes_until_the_goal_on_the_visit_page(self):
        task = _task(lambda: True)
        task._like_current_home = lambda visit: True
        task._next_home = lambda visit: True
        self.assertTrue(task.run_claim())

    def test_like_counter_that_updates_late_still_counts(self):
        task = _task(lambda: True)
        reads = iter([10, 10, 10, 11, 11])
        task._like_count = lambda: next(reads)
        task.sleep = lambda _s: None
        clicks = []
        task._click_reference = lambda x, y, after_sleep=0: clicks.append((x, y))
        self.assertTrue(task._like_current_home(1))
        # Pressed once only: a second press could take the like back.
        self.assertEqual([LIKE_BUTTON_POINT], clicks)

    def test_like_without_counter_change_is_not_pressed_again(self):
        task = _task(lambda: True)
        task._like_count = lambda: 10
        task.sleep = lambda _s: None
        clicks = []
        task._click_reference = lambda x, y, after_sleep=0: clicks.append((x, y))
        with mock.patch("src.tasks.WeeklyTasks.monotonic", side_effect=[0, 1, 2, 5]):
            self.assertFalse(task._like_current_home(1))
        self.assertEqual([LIKE_BUTTON_POINT], clicks)



class NextHomeTest(unittest.TestCase):
    """下一间 counts only once a different home's counter shows."""

    def _task(self, count_after_next):
        """Home counter 10, 11 once liked; ``count_after_next(n)`` after n 下一间."""
        task = _task(lambda: True)
        clock = [0.0]
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        for target, value in (
            ("src.tasks.WeeklyTasks.monotonic", lambda: clock[0]),
            ("src.tasks.WeeklyTasks.NEXT_HOME_WAIT_SECONDS", 0.0),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        def like_count():
            nexts = task.clicks.count(NEXT_HOME_POINT)
            if nexts:
                return count_after_next(nexts)
            return 11 if LIKE_BUTTON_POINT in task.clicks else 10

        task._like_count = like_count
        task._home_counts = set()
        return task

    def test_lost_next_press_never_likes_the_same_home_twice(self):
        # Both 下一间 presses are lost: the liked home stays up.
        task = self._task(lambda _nexts: 11)

        self.assertFalse(task.run_claim())
        self.assertEqual(1, task.clicks.count(LIKE_BUTTON_POINT))
        self.assertEqual(2, task.clicks.count(NEXT_HOME_POINT))

    def test_another_home_counter_confirms_the_next_press(self):
        task = self._task(lambda _nexts: 523)
        task._like_current_home(1)

        self.assertTrue(task._next_home(1))
        self.assertEqual(1, task.clicks.count(NEXT_HOME_POINT))

    def test_one_odd_read_is_not_another_home(self):
        reads = iter([523, 11, 11, 11, 11])
        task = self._task(lambda _nexts: next(reads))
        task._home_counts = {10, 11}
        task.clicks.append(LIKE_BUTTON_POINT)

        self.assertFalse(task._next_home(1))


if __name__ == "__main__":
    unittest.main()
