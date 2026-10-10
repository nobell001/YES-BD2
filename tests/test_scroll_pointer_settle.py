"""The cursor stays on the scroll point around the wheel (YES-BD2 #11).

A player's 活动 list went up (six wheels, 0.15 s apart) but never down (one
wheel): the single wheel was sent the moment the cursor arrived and the
cursor was put back 25 ms later, before the game saw the pointer there.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.tasks.BaseBD2Task import SCROLL_POINTER_SETTLE_SECONDS, BaseBD2Task


def _task(events):
    class Interaction:
        capture = SimpleNamespace(get_abs_cords=lambda x, y: (x + 1000, y + 2000))

        def try_activate(self):
            pass

        def scroll(self, x, y, amount):
            events.append(("wheel", x, y, amount))

    task = object.__new__(BaseBD2Task)
    task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
    task.sleep = lambda seconds: events.append(("after", seconds))

    def operate(action, block=True, restore_cursor=True):
        action()
        events.append(("cursor back", restore_cursor))

    task.operate = operate
    return task, Interaction()


class ScrollPointerSettleTest(unittest.TestCase):
    def scroll(self, amount, **kwargs):
        events = []
        task, interaction = _task(events)
        with (
            patch.object(BaseBD2Task, "executor", SimpleNamespace(interaction=interaction)),
            patch("win32api.SetCursorPos", lambda pos: events.append(("cursor", pos))),
            patch("time.sleep", lambda seconds: events.append(("wait", seconds))),
        ):
            BaseBD2Task.scroll_client(task, (0.22, 0.5), amount, **kwargs)
        return events

    def test_one_wheel_waits_for_the_pointer_on_both_sides(self):
        settle = ("wait", SCROLL_POINTER_SETTLE_SECONDS)
        self.assertEqual(
            [
                ("cursor", (1422, 2540)),
                settle,
                ("wheel", 422, 540, -3),
                settle,
                ("cursor back", True),
                ("after", 1.5),
            ],
            self.scroll(-3, after_sleep=1.5),
        )

    def test_several_wheels_keep_their_interval(self):
        events = self.scroll(3, count=3, interval=0.15)
        waits = [event[1] for event in events if event[0] == "wait"]
        self.assertEqual(
            [SCROLL_POINTER_SETTLE_SECONDS, 0.15, 0.15, SCROLL_POINTER_SETTLE_SECONDS], waits
        )
        self.assertEqual(3, sum(1 for event in events if event[0] == "wheel"))

    def test_the_settle_is_long_enough_for_a_slow_game(self):
        # The six-wheel scroll up, 0.15 s apart, moved that player's list.
        self.assertGreaterEqual(SCROLL_POINTER_SETTLE_SECONDS, 0.15)


if __name__ == "__main__":
    unittest.main()
