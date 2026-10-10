"""The left button never stays held when a click or swipe is cut off (audit #63)."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.interaction import BD2Interaction as module
from src.interaction.BD2Interaction import BD2Interaction

DOWN, UP, MOVE = "down", "up", "move"
WIN32CON = SimpleNamespace(WM_LBUTTONDOWN=DOWN, WM_LBUTTONUP=UP, WM_MOUSEMOVE=MOVE, MK_LBUTTON=1)
WIN32API = SimpleNamespace(MAKELONG=lambda x, y: (x, y))


class _Stop(Exception):
    pass


def _interaction():
    interaction = object.__new__(BD2Interaction)
    interaction._input_lock = threading.RLock()
    interaction._operating = False
    interaction.capture = SimpleNamespace(
        width=1920, height=1080, get_abs_cords=lambda x, y: (x, y)
    )
    interaction.try_activate = lambda: None
    posted = []
    interaction.post = lambda message, *_args: posted.append(message)
    return interaction, posted


class MouseUpAlwaysTest(unittest.TestCase):
    def test_a_click_cut_off_while_held_still_lets_go(self):
        interaction, posted = _interaction()

        def sleep(_seconds):
            if posted and posted[-1] == DOWN:
                raise _Stop()

        with (
            patch.object(module, "win32con", WIN32CON),
            patch.object(module, "win32api", WIN32API),
            patch.object(module.time, "sleep", sleep),
            patch.object(module, "SetCursorPos", lambda *_a: None),
            patch.object(module, "_in_clone", lambda: False),
        ):
            with self.assertRaises(_Stop):
                interaction.click(100, 100, move=True)
        self.assertEqual([DOWN, UP], posted)

    def test_a_swipe_cut_off_midway_still_lets_go(self):
        interaction, posted = _interaction()
        moves = []

        def set_cursor(position):
            moves.append(position)
            if len(moves) == 4:
                raise _Stop()

        with (
            patch.object(module, "win32con", WIN32CON),
            patch.object(module, "win32api", WIN32API),
            patch.object(module.time, "sleep", lambda *_a: None),
            patch.object(module, "SetCursorPos", set_cursor),
            patch.object(module, "GetCursorPos", lambda: (5, 5)),
        ):
            with self.assertRaises(_Stop):
                interaction.post_swipe(0, 0, 120, 0, steps=12)
        self.assertEqual(DOWN, posted[1])
        self.assertEqual(UP, posted[-1])
        self.assertEqual(1, posted.count(UP))

    def test_a_full_swipe_lets_go_once(self):
        interaction, posted = _interaction()
        with (
            patch.object(module, "win32con", WIN32CON),
            patch.object(module, "win32api", WIN32API),
            patch.object(module.time, "sleep", lambda *_a: None),
            patch.object(module, "SetCursorPos", lambda *_a: None),
            patch.object(module, "GetCursorPos", lambda: (5, 5)),
        ):
            interaction.post_swipe(0, 0, 120, 0, steps=4)
        self.assertEqual([MOVE, DOWN, MOVE, MOVE, MOVE, MOVE, UP], posted)


if __name__ == "__main__":
    unittest.main()
