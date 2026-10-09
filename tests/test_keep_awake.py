"""The PC stays awake while a run goes, and the request is given back after
(Leo 2026-10-09)."""

import ctypes
import unittest
from types import SimpleNamespace
from unittest import mock

from src.utils import keep_awake


class FakeKernel32:
    def __init__(self):
        self.calls = []

    def SetThreadExecutionState(self, flags):
        self.calls.append(flags.value if hasattr(flags, "value") else flags)
        return keep_awake.ES_CONTINUOUS


class KeepAwakeTest(unittest.TestCase):
    def setUp(self):
        self.kernel32 = FakeKernel32()
        windll = mock.Mock()
        windll.kernel32 = self.kernel32
        patcher = mock.patch.object(ctypes, "windll", windll, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, keep_awake, "_held", keep_awake.NONE)
        keep_awake._held = keep_awake.NONE

    def test_level_follows_what_runs(self):
        self.assertEqual(keep_awake.DISPLAY, keep_awake.level_for(True, False, False))
        # A paused run waits for the player, who is at the PC.
        self.assertEqual(keep_awake.NONE, keep_awake.level_for(True, True, False))
        # The clone's run: the PC stays on, the player's screen may turn off.
        self.assertEqual(keep_awake.SYSTEM, keep_awake.level_for(False, False, True))
        self.assertEqual(keep_awake.NONE, keep_awake.level_for(False, False, False))

    def test_asks_windows_only_when_the_level_changes(self):
        self.assertTrue(keep_awake.apply(keep_awake.DISPLAY))
        self.assertFalse(keep_awake.apply(keep_awake.DISPLAY))
        self.assertTrue(keep_awake.apply(keep_awake.NONE))
        self.assertEqual(
            [
                keep_awake.ES_CONTINUOUS
                | keep_awake.ES_SYSTEM_REQUIRED
                | keep_awake.ES_DISPLAY_REQUIRED,
                keep_awake.ES_CONTINUOUS,
            ],
            self.kernel32.calls,
        )
        self.assertEqual(keep_awake.NONE, keep_awake.held())

    def test_clone_run_keeps_only_the_system_on(self):
        keep_awake.apply(keep_awake.SYSTEM)
        self.assertEqual(
            [keep_awake.ES_CONTINUOUS | keep_awake.ES_SYSTEM_REQUIRED], self.kernel32.calls
        )

    def test_released_after_a_run_however_it_ends(self):
        with keep_awake.released_after(True):
            pass
        with self.assertRaises(RuntimeError):
            with keep_awake.released_after(True):
                raise RuntimeError("stop")
        with keep_awake.released_after(False):
            pass
        self.assertEqual([keep_awake.ES_CONTINUOUS] * 2, self.kernel32.calls)

    def test_not_windows_does_nothing(self):
        with mock.patch.object(ctypes, "windll", None, create=True):
            self.assertFalse(keep_awake.apply(keep_awake.DISPLAY))
        self.assertEqual(keep_awake.NONE, keep_awake.held())


class TopLevelRunReleaseTest(unittest.TestCase):
    """A run the executor started gives back ok-script's display request,
    which a Stop used to leave on; a child of 一键日常 leaves it to the batch."""

    def _task(self, result, top):
        from src.tasks.BaseBD2Task import BaseBD2Task

        class Task(BaseBD2Task):
            def __init__(self):
                self._action_interval_lock = None
                self._executor = SimpleNamespace(
                    current_task=self if top else object(), trigger_tasks=[]
                )

            def run(self):
                if isinstance(result, BaseException):
                    raise result
                return result

        return Task()

    def _released(self, task):
        with mock.patch.object(keep_awake, "release_this_thread") as release:
            try:
                task.run()
            except BaseException:
                pass
        return release.call_count

    def test_stopped_top_level_run_is_released(self):
        from ok.task.exceptions import TaskDisabledException

        self.assertEqual(1, self._released(self._task(TaskDisabledException(), top=True)))

    def test_finished_top_level_run_is_released(self):
        self.assertEqual(1, self._released(self._task(True, top=True)))

    def test_child_run_is_not(self):
        self.assertEqual(0, self._released(self._task(True, top=False)))


if __name__ == "__main__":
    unittest.main()
