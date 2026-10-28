"""Closing an idle 桌面分身 from outside waits until its sign-out is done.

Live 4K 2026-10-28: the clone (game and tool in it) took 20.9 s from
`logoff` to 「Session logoff succeeded」; the 20 s wait gave up 0.9 s before
it, so the run on the main screen said the clone would not close and never
started.
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from src.utils import clone_desktop
from src.utils.wait_limits import LOADING_MAX_SECONDS

CHILD = 15
# Measured on the 4K (TerminalServices-LocalSessionManager, 20:39:23.2 -> 20:39:44.1).
LIVE_LOGOFF_SECONDS = 20.9


class _Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Viewer:
    def __init__(self, steps: list):
        self.info = {"name": "CloneDesktop.exe"}
        self.steps = steps

    def terminate(self) -> None:
        self.steps.append("viewer closed")

    def wait(self, _timeout) -> None:
        return None


class EndCloneTest(unittest.TestCase):
    def _end(self, gone_after: float | None):
        clock = _Clock()
        steps: list = []

        def run(command, **_kwargs):
            steps.append(command)

        def clone_open() -> bool:
            return gone_after is None or clock.now < gone_after

        psutil = types.SimpleNamespace(
            process_iter=lambda _attrs=None: [_Viewer(steps)],
            NoSuchProcess=type("NoSuchProcess", (Exception,), {}),
        )
        with (
            mock.patch.dict(sys.modules, {"psutil": psutil}),
            mock.patch.object(clone_desktop, "child_session_id", return_value=CHILD),
            mock.patch.object(clone_desktop, "in_clone", return_value=False),
            mock.patch.object(clone_desktop, "clone_open", side_effect=clone_open),
            mock.patch.object(clone_desktop.subprocess, "run", side_effect=run),
            mock.patch.object(clone_desktop, "time", clock),
        ):
            ended = clone_desktop.end_clone()
        return ended, clock.now, steps

    def test_a_sign_out_as_slow_as_the_live_one_counts_as_closed(self):
        ended, waited, _steps = self._end(LIVE_LOGOFF_SECONDS)
        self.assertTrue(ended)
        self.assertGreaterEqual(waited, LIVE_LOGOFF_SECONDS)
        self.assertLess(waited, LIVE_LOGOFF_SECONDS + 1)

    def test_the_viewer_closes_before_the_clone_is_signed_out(self):
        _ended, _waited, steps = self._end(1.0)
        self.assertEqual(steps, ["viewer closed", ["logoff", str(CHILD)]])

    def test_a_clone_that_never_signs_out_is_given_up_at_the_loading_cap(self):
        ended, waited, _steps = self._end(None)
        self.assertFalse(ended)
        self.assertGreaterEqual(waited, LOADING_MAX_SECONDS)
        self.assertLess(waited, LOADING_MAX_SECONDS + 1)


if __name__ == "__main__":
    unittest.main()
