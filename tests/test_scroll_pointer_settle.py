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


class RealWheelTest(unittest.TestCase):
    """塔洛斯's zoom ignores posted wheel messages (4K PC clone 2026-10-31):
    wheel_client_real turns the real wheel, only onto the game in front."""

    def wheel(self, notches, *, front=True, on_game=True):
        events = []
        task, interaction = _task(events)
        task._bring_game_to_foreground = lambda: front
        task._point_on_game = lambda point: on_game
        with (
            patch.object(BaseBD2Task, "executor", SimpleNamespace(interaction=interaction)),
            patch("win32api.SetCursorPos", lambda pos: events.append(("cursor", pos))),
            patch(
                "win32api.mouse_event",
                lambda flags, dx, dy, data, extra: events.append(("real wheel", data)),
                create=True,
            ),
            patch("time.sleep", lambda seconds: None),
        ):
            done = BaseBD2Task.wheel_client_real(task, (0.5, 0.8), notches, after_sleep=0.8)
        return done, events

    def test_notches_turn_the_real_wheel_over_the_point(self):
        done, events = self.wheel(-3)
        self.assertTrue(done)
        self.assertEqual(("cursor", (1960, 2864)), events[0])
        self.assertEqual([("real wheel", -120)] * 3, [e for e in events if e[0] == "real wheel"])
        self.assertIn(("after", 0.8), events)

    def test_nothing_turned_when_the_game_is_not_in_front(self):
        for front, on_game in ((False, True), (True, False)):
            done, events = self.wheel(2, front=front, on_game=on_game)
            self.assertFalse(done)
            self.assertFalse([e for e in events if e[0] in ("real wheel", "cursor")])
