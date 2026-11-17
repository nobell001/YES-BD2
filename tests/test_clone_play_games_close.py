"""Closing Play Games in a 桌面分身 never closes the game (live 2026-11-17).

Leo's 4K clone: the Neowiz starter handed the start to Google Play Games,
whose Service.exe ran Browndust2Starter.exe, which ran the game.  Closing
Service.exe with everything under it closed the game twice.  While the
starter or the game is under Play Games it is left open; once the starter
is done it is closed as before (SE102, live 2026-10-04).
"""

import ctypes
import sys
import types
import unittest
from unittest import mock

from src.utils import clone_desktop

SERVICE = r"C:\Program Files\Google\Play Games\current\service\Service.exe"


class _Process:
    def __init__(self, pid, name, exe="", children=()):
        self.info = {"pid": pid, "exe": exe, "name": name}
        self._name = name
        self._children = list(children)
        self.terminated = False

    def name(self):
        return self._name

    def children(self, recursive=False):
        found = []
        for child in self._children:
            found.append(child)
            if recursive:
                found.extend(child.children(recursive=True))
        return found

    def terminate(self):
        self.terminated = True


class ClosePlayGamesTest(unittest.TestCase):
    def _close(self, processes):
        windll = mock.MagicMock()
        windll.kernel32.ProcessIdToSessionId.return_value = 1  # every process: same session
        psutil = types.SimpleNamespace(process_iter=lambda attrs: list(processes))
        with (
            mock.patch.object(clone_desktop, "in_clone", lambda: True),
            mock.patch.object(ctypes, "windll", windll, create=True),
            mock.patch.dict(sys.modules, {"psutil": psutil}),
        ):
            return clone_desktop.close_play_games_launcher()

    def test_play_games_starting_the_game_is_left_open(self):
        game = _Process(30, "BrownDust II.exe")
        starter = _Process(20, "Browndust2Starter.exe", children=[game])
        service = _Process(10, "Service.exe", SERVICE, children=[starter])
        self.assertEqual([], self._close([service, starter, game]))
        self.assertFalse(game.terminated)
        self.assertFalse(starter.terminated)
        self.assertFalse(service.terminated)
        self.assertTrue(clone_desktop.play_games_waiting)

    def test_the_starter_alone_under_play_games_is_left_open(self):
        starter = _Process(20, "Browndust2Starter.exe")
        service = _Process(10, "Service.exe", SERVICE, children=[starter])
        self.assertEqual([], self._close([service, starter]))
        self.assertFalse(starter.terminated)
        self.assertFalse(service.terminated)

    def test_play_games_is_closed_once_the_starter_is_done(self):
        helper = _Process(40, "crosvm.exe")
        service = _Process(10, "Service.exe", SERVICE, children=[helper])
        game = _Process(30, "BrownDust II.exe")  # its starter has ended: not under Play Games
        self.assertEqual([10], self._close([service, game]))
        self.assertTrue(service.terminated)
        self.assertTrue(helper.terminated)
        self.assertFalse(game.terminated)
        self.assertFalse(clone_desktop.play_games_waiting)

    def test_nothing_is_closed_outside_a_clone(self):
        service = _Process(10, "Service.exe", SERVICE)
        with mock.patch.object(clone_desktop, "in_clone", lambda: False):
            self.assertEqual([], clone_desktop.close_play_games_launcher())
        self.assertFalse(service.terminated)


if __name__ == "__main__":
    unittest.main()
