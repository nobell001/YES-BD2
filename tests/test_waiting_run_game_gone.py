"""YES-BD2 #70 「偶尔会自动启动」: a 一键日常 left waiting for the login after
the game closed started by itself the next time the player opened the game.

The waiting run is now cancelled once the game has stayed closed longer than
its opening may take; a run whose game is still opening is never cancelled.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from ok import BaseTask

from src.tasks.DailyBatchTask import DailyBatchTask
from src.tasks.trigger import AutoLoginTask as login_module
from src.tasks.trigger.AutoLoginTask import AutoLoginTask


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _setup():
    enqueued = []
    daily = object.__new__(DailyBatchTask)
    daily._start_after_login = True  # waiting for the login
    daily._requested_run_mode = "incomplete"
    daily._enabled = False
    daily._scheduled_run = False
    daily.log_info = lambda *a, **k: None
    daily.disable = lambda: setattr(daily, "_enabled", False)
    executor = SimpleNamespace(
        get_task_by_class=lambda cls: {DailyBatchTask: daily}.get(cls),
        enqueue_onetime_task=lambda task: enqueued.append(task) or True,
    )
    daily._executor = executor
    login = object.__new__(AutoLoginTask)
    login._executor = executor
    login.config = {}
    login.info_set = lambda *a, **k: None
    login.log_info = lambda *a, **k: None
    login.warnings = []
    login.log_warning = lambda message, notify=False: login.warnings.append((message, notify))
    login._reset_login_state()
    login._login_retry_not_before = 0.0
    # The game reaches 主页 when it is opened again.
    login.capture_frame = lambda: object()
    login._home_confirmation_signals = lambda frame: (True, None, None, 0, "")
    login._check_capture_colours = lambda frame: None
    login.mark_logged_in = lambda: None
    return login, daily, enqueued


class WaitingRunGameGoneTest(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.running = False
        patches = [
            mock.patch.object(login_module, "monotonic", self.clock),
            mock.patch.object(login_module, "game_running", lambda: self.running),
            mock.patch.object(BaseTask, "should_trigger", return_value=True),
            mock.patch.object(
                login_module.wait_settings, "get", lambda setting: setting.default
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _tick(self, login, seconds):
        self.clock.now += seconds
        return login.should_trigger()

    def test_game_closed_long_cancels_so_a_later_opening_does_not_start_it(self):
        login, daily, enqueued = _setup()
        login._state = "clearing"  # mid-login when the player closes the game
        limit = login._game_gone_limit()
        self._tick(login, 1)
        self._tick(login, limit + 1)
        self.assertFalse(daily._start_after_login)
        self.assertIn("游戏关掉了", login.warnings[-1][0])
        self.assertTrue(login.warnings[-1][1])
        # Hours later the player opens the game: nothing starts.
        self.running = True
        self.clock.now += 3 * 3600
        self.assertTrue(login.should_trigger())
        login.run()
        self.assertEqual([], enqueued)

    def test_a_game_still_opening_is_never_cancelled(self):
        login, daily, enqueued = _setup()
        limit = login._game_gone_limit()
        self.assertGreaterEqual(limit, 180 * 2)  # 打开游戏最长等多久 × rounds
        self._tick(login, 1)
        self._tick(login, limit - 5)
        self.assertTrue(daily._start_after_login)
        self.assertEqual([], login.warnings)
        # The game comes up and logs in: the run starts as asked.
        self.running = True
        self._tick(login, 1)
        login.run()
        self.assertEqual([daily], enqueued)

    def test_the_game_coming_back_restarts_the_count(self):
        login, daily, _enqueued = _setup()
        limit = login._game_gone_limit()
        self._tick(login, 1)
        self._tick(login, limit - 10)
        self.running = True
        self._tick(login, 1)
        self.running = False
        self._tick(login, 1)
        self._tick(login, limit - 10)
        self.assertTrue(daily._start_after_login)

    def test_a_login_for_that_run_only_is_turned_off_again(self):
        login, daily, _enqueued = _setup()
        login.config = {"_enabled": False}  # 自动登录游戏 off; on for that run
        login._enabled = True
        self._tick(login, 1)
        self._tick(login, login._game_gone_limit() + 1)
        self.assertFalse(login._enabled)

    def test_nothing_waiting_nothing_cancelled(self):
        login, daily, _enqueued = _setup()
        daily._start_after_login = False
        self._tick(login, 1)
        self._tick(login, 10_000)
        self.assertEqual([], login.warnings)


if __name__ == "__main__":
    unittest.main()
