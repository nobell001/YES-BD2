"""Live 4K 2026-10-10: the tool opened with the game on a menu (其他).  The
auto-login check kept waiting for a login screen, and 开始 was refused with
"start refused: 自动登录游戏 is running" until the game was back on 主页."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ui.shell import actions, data


class StartDuringLoginCheckTest(unittest.TestCase):
    def _executor(self, current):
        login = SimpleNamespace(name="自动登录游戏")
        batch = SimpleNamespace(name="一键日常", enabled=False, paused=False)
        executor = SimpleNamespace(
            current_task=login if current == "login" else batch if current == "batch" else None,
            trigger_tasks=[login],
            onetime_tasks=[batch],
        )
        patch = mock.patch.object(data, "executor", lambda: executor)
        patch.start()
        self.addCleanup(patch.stop)
        return login, batch

    def test_the_login_check_is_not_a_run(self):
        self._executor("login")
        self.assertFalse(data.busy())

    def test_a_started_task_is_a_run(self):
        self._executor("batch")
        self.assertTrue(data.busy())

    def test_nothing_running(self):
        self._executor(None)
        self.assertFalse(data.busy())

    def test_start_is_not_refused_while_the_login_check_runs(self):
        _login, batch = self._executor("login")
        warned = []
        # Everything after the busy check is the normal start path; stop at
        # its next step so the test does not need the app.
        with (
            mock.patch.object(actions, "_warn", lambda _window, text: warned.append(text)),
            mock.patch(
                "src.ui.shell.clone_flow.busy_in_clone", side_effect=RuntimeError("reached")
            ),
            self.assertRaisesRegex(RuntimeError, "reached"),
        ):
            actions.start(batch)
        self.assertEqual([], warned)

    def test_start_is_still_refused_during_a_run(self):
        self._executor("batch")
        other = SimpleNamespace(name="快速狩猎", enabled=False, paused=False)
        warned = []
        with mock.patch.object(actions, "_warn", lambda _window, text: warned.append(text)):
            self.assertFalse(actions.start(other))
        self.assertEqual(1, len(warned))


if __name__ == "__main__":
    unittest.main()
