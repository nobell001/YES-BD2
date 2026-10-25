"""一键日常's 完成日常后关闭游戏 (Leo 2026-10-20 「全部完成無異常錯誤才關 讓用戶選擇
預設做完不關 更新後提醒用戶有改動」): the one-time notice and the close itself."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ok import BaseTask

from src.tasks import DailyBatchTask as batch_module
from src.tasks.DailyBatchTask import CLOSE_GAME_KEY, CLOSE_GAME_NOTICE_KEY, DailyBatchTask
from src.ui.shell import new_setting_notice
from src.utils import game_process


def _load(saved: dict | None) -> DailyBatchTask:
    task = DailyBatchTask(executor=SimpleNamespace(scene=None), app=SimpleNamespace())

    def load(_self):
        _self.config = {**_self.default_config, **(saved or {})}

    def read(path):
        return dict(saved or {}) if "DailyBatchTask" in str(path) else {}

    with (
        mock.patch.object(batch_module, "_read_json", side_effect=read),
        mock.patch.object(BaseTask, "load_config", load),
    ):
        task.load_config()
    return task


class NoticeTest(unittest.TestCase):
    def test_new_install_is_off_and_not_asked(self):
        config = _load(None).config
        self.assertIs(False, config[CLOSE_GAME_KEY])
        self.assertFalse(config[CLOSE_GAME_NOTICE_KEY])

    def test_player_from_before_is_asked_once_and_stays_off(self):
        config = _load({"启用": True, "完成日常后自动关机": False}).config
        self.assertIs(False, config[CLOSE_GAME_KEY])
        self.assertTrue(config[CLOSE_GAME_NOTICE_KEY])

    def test_not_asked_again_once_saved(self):
        config = _load({CLOSE_GAME_KEY: True, CLOSE_GAME_NOTICE_KEY: False}).config
        self.assertTrue(config[CLOSE_GAME_KEY])
        self.assertFalse(config[CLOSE_GAME_NOTICE_KEY])

    def test_walk_through_shows_once(self):
        batch = SimpleNamespace(config={CLOSE_GAME_NOTICE_KEY: True})
        tasks = {"DailyBatchTask": batch}
        with (
            mock.patch.object(new_setting_notice.data, "task_by_class_name", side_effect=tasks.get),
            mock.patch.object(new_setting_notice, "CoachMarks") as tour,
        ):
            self.assertTrue(new_setting_notice.show_pending(mock.Mock()))
            self.assertFalse(new_setting_notice.show_pending(mock.Mock()))
        self.assertEqual(1, tour.return_value.start.call_count)
        self.assertFalse(batch.config[CLOSE_GAME_NOTICE_KEY])

    def test_notice_points_at_the_start_button_on_home(self):
        button = object()
        shell = mock.Mock()
        shell.pages = {"home": SimpleNamespace(start_all=button)}
        (step,) = new_setting_notice.close_game_steps(shell)
        step.before()
        shell.navigate.assert_called_once_with("home")
        self.assertIs(button, step.target())


class ConfirmWindowTest(unittest.TestCase):
    """Leo 2026-10-21: the switch is in the window 一键完成日常 opens."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _ask(self, config, click=False):
        from src.ui.shell import run_confirm

        seen = {}

        def exec_(dialog):
            seen["box"] = dialog.close_game
            if click and dialog.close_game is not None:
                dialog.close_game.click()
            return 0

        batch = SimpleNamespace(config=config, child_tasks=())
        with (
            mock.patch.object(run_confirm.RunConfirm, "exec", exec_),
            mock.patch.object(run_confirm.data, "batch_children", return_value=[]),
        ):
            run_confirm.ask(None, batch)
        return seen["box"]

    def test_box_shows_the_saved_choice_and_keeps_a_click(self):
        config = {CLOSE_GAME_KEY: False}
        box = self._ask(config, click=True)
        self.assertIsNotNone(box)
        self.assertIs(True, config[CLOSE_GAME_KEY])

    def test_no_box_without_the_setting(self):
        self.assertIsNone(self._ask({}))


class TaskSettingsTest(unittest.TestCase):
    """Leo 2026-10-25: players who auto-run on open never see the confirm
    window, so the same switch is also in 任务设定, next to 关机."""

    def test_switch_sits_before_shutdown(self):
        from src.ui.shell.task_page import BATCH_OPTION_LABELS

        keys = list(BATCH_OPTION_LABELS)
        self.assertEqual(keys.index(CLOSE_GAME_KEY) + 1, keys.index("完成日常后自动关机"))
        self.assertEqual("全部做完且没有失败后关闭游戏", BATCH_OPTION_LABELS[CLOSE_GAME_KEY])


class CloseGameTest(unittest.TestCase):
    def test_nothing_running_counts_as_closed(self):
        with mock.patch.object(game_process, "_game_processes", return_value=[]):
            self.assertTrue(game_process.close_game())

    def test_cannot_tell_is_not_closed(self):
        with mock.patch.object(game_process, "_game_processes", return_value=None):
            self.assertFalse(game_process.close_game())

    def test_presses_alt_f4_and_waits_until_gone(self):
        import psutil

        game = mock.Mock(pid=42)
        with (
            mock.patch.object(game_process, "_game_processes", return_value=[game]),
            mock.patch.object(game_process, "_press_alt_f4", return_value=1) as press,
            mock.patch.object(psutil, "wait_procs", return_value=([game], [])),
        ):
            self.assertTrue(game_process.close_game(wait=0))
        press.assert_called_once_with({42})
        game.terminate.assert_not_called()
        game.kill.assert_not_called()

    def test_game_still_open_is_never_forced(self):
        import psutil

        game = mock.Mock(pid=42)
        with (
            mock.patch.object(game_process, "_game_processes", return_value=[game]),
            mock.patch.object(game_process, "_press_alt_f4", return_value=1),
            mock.patch.object(psutil, "wait_procs", return_value=([], [game])),
        ):
            self.assertFalse(game_process.close_game(wait=0))
        game.terminate.assert_not_called()
        game.kill.assert_not_called()

    def test_no_window_to_press_is_not_closed(self):
        with (
            mock.patch.object(game_process, "_game_processes", return_value=[mock.Mock(pid=42)]),
            mock.patch.object(game_process, "_press_alt_f4", return_value=0),
        ):
            self.assertFalse(game_process.close_game(wait=0))


if __name__ == "__main__":
    unittest.main()
