"""停止 shows at once and a second press does nothing (Leo 2026-10-10: 「終止
按下去要先有反饋 不然用戶會一直按」)."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.tasks import run_report
from src.ui.shell import actions, clone_flow, data, guide_page, hotkeys

_SEEN = mock.patch.object(guide_page, "SEEN_FILE", Path(tempfile.mkdtemp()) / "ui_guide.json")


def setUpModule():
    _SEEN.start()


def tearDownModule():
    _SEEN.stop()


class _Task(SimpleNamespace):
    def disable(self):
        self.enabled = False

    def unpause(self):
        self.paused = False


class HomeStopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.task = _Task(name="领取邮件", enabled=True, paused=False, info={}, config={})
        self.current = self.task
        self.remote = None
        self.stops: list = []
        self.sent: list = []
        real_stop = actions.stop

        def stop(task):
            self.stops.append(task)
            real_stop(task)

        for patch in (
            mock.patch.object(data, "current_task", lambda: self.current),
            mock.patch.object(data, "busy", lambda: self.current is not None),
            mock.patch.object(data, "executor", lambda: None),
            mock.patch.object(data, "onetime_tasks", lambda: []),
            mock.patch.object(data, "task_by_name", lambda _name: None),
            mock.patch.object(data, "last_run", lambda _name: None),
            mock.patch.object(run_report, "active", lambda: None),
            mock.patch.object(clone_flow, "remote_task", lambda: self.remote),
            mock.patch.object(clone_flow, "remote_control", self.sent.append),
            mock.patch.object(clone_flow, "drop_waiting_job", lambda: False),
            mock.patch.object(actions, "stop", stop),
            mock.patch.object(hotkeys, "KEYS_FILE", self.root / "hotkeys.json"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        from src.ui.shell.home import HomePage

        self.page = HomePage(lambda *_a: None, lambda *_a: None)
        self.page.refresh()
        self.assertEqual("run", self.page._mode)

    def _button(self):
        return self.page.stop_button

    def test_first_press_turns_the_button_grey_at_once(self):
        self.page._stop()
        self.assertFalse(self._button().isEnabled())
        self.assertEqual("正在停止…", self._button().text())
        self.assertFalse(self.page.pause_button.isEnabled())
        self.assertEqual("正在停止：领取邮件", self.page.title.text())

    def test_more_presses_do_nothing(self):
        for _ in range(5):
            self.page._stop()
        self.assertEqual([self.task], self.stops)

    def test_still_stopping_while_the_task_ends_its_step(self):
        self.page._stop()
        with mock.patch("src.ui.shell.home.time.monotonic", return_value=10**9):
            # Long after the press: the task is still the running one.
            self.page.refresh()
            self.assertEqual("正在停止…", self._button().text())
            self.page._stop()
        self.assertEqual(1, len(self.stops))

    def test_button_is_back_for_the_next_run(self):
        self.page._stop()
        self.current = None
        self.page.refresh()
        self.assertNotEqual("run", self.page._mode)
        self.task = self.current = _Task(name="领取邮件", enabled=True, paused=False, info={})
        self.page.refresh()
        self.assertTrue(self._button().isEnabled())
        self.assertEqual("停止", self._button().text())
        self.assertTrue(self.page.pause_button.isEnabled())

    def test_hotkey_stop_shows_the_same(self):
        from src.ui.shell.install import Shell

        shell = SimpleNamespace(pages={"home": self.page})
        Shell._on_hotkey(shell, hotkeys.STOP)
        Shell._on_hotkey(shell, hotkeys.STOP)
        self.assertEqual("正在停止…", self._button().text())
        self.assertEqual(1, len(self.stops))

    def test_clone_run_press_counts_for_a_while_then_can_be_pressed_again(self):
        self.current = None
        self.remote = _Task(
            name="一键完成日常", enabled=True, paused=False, remote=True, status={}, info={}
        )
        self.page.refresh()
        self.assertEqual("run", self.page._mode)
        self.page._stop()
        self.page._stop()
        self.assertEqual(["stop"], self.sent)
        self.assertEqual("正在停止…", self._button().text())
        from src.ui.shell import home

        later = home.time.monotonic() + home.STOP_GRACE_SECONDS + 1
        with mock.patch("src.ui.shell.home.time.monotonic", return_value=later):
            # The clone never ended the run: the button works again.
            self.page.refresh()
            self.assertTrue(self._button().isEnabled())
            self.page._stop()
        self.assertEqual(["stop", "stop"], self.sent)


if __name__ == "__main__":
    unittest.main()
