"""做完关闭分身 (Leo 2026-11-08 「桌面分身完成日常后自动关闭桌面分身」「選項是
完成後關閉遊戲 或是完成後在桌面重開」): a run in the 桌面分身 ends the clone when
done, as its X does, with the same 什么时候关 choice as 做完关闭游戏; the tool in
the clone asks the viewer outside to sign it out."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.tasks import DailyBatchTask as batch_module
from src.tasks.DailyBatchTask import (
    CLOSE_CLONE_HOW_KEY,
    CLOSE_CLONE_JUST,
    CLOSE_CLONE_KEY,
    CLOSE_CLONE_MOVE,
    CLOSE_CLONE_NOTE,
    CLOSE_GAME_KEY,
    CLOSE_GAME_WHEN_KEY,
    CLOSE_WHEN_ALWAYS,
    CLOSE_WHEN_CLEAN,
    DailyBatchTask,
)
from src.utils import clone_desktop

REPO = Path(__file__).resolve().parents[1]


def _task(config: dict) -> DailyBatchTask:
    task = DailyBatchTask(executor=SimpleNamespace(scene=None), app=SimpleNamespace())
    task.config = {**task.default_config, **config}
    task._end_clone_after_run = False
    task.log_info = mock.Mock()
    task.log_warning = mock.Mock()
    task.log_error = mock.Mock()
    return task


class PlanTest(unittest.TestCase):
    def _plan(self, config, clean, in_clone=True, all_done=True, resume=False, others=False):
        task = _task(config)
        with (
            mock.patch.object(clone_desktop, "in_clone", return_value=in_clone),
            mock.patch.object(task, "_all_done_today", return_value=all_done),
            mock.patch.object(task, "_resume_after_login_set", return_value=resume),
            mock.patch.object(task, "_others_in_line", return_value=others),
            mock.patch.object(batch_module.run_report, "set_notice") as notice,
        ):
            task._plan_close_clone(clean)
        return task._end_clone_after_run, notice

    def test_off_by_default(self):
        self.assertIs(False, _task({}).config[CLOSE_CLONE_KEY])
        planned, _ = self._plan({}, clean=True)
        self.assertFalse(planned)

    def test_clean_run_in_the_clone_ends_it(self):
        planned, notice = self._plan({CLOSE_CLONE_KEY: True}, clean=True)
        self.assertTrue(planned)
        notice.assert_called_once_with(CLOSE_CLONE_NOTE)

    def test_run_on_own_desktop_does_nothing(self):
        planned, _ = self._plan({CLOSE_CLONE_KEY: True}, clean=True, in_clone=False)
        self.assertFalse(planned)

    def test_clean_rule_needs_everything_done(self):
        planned, _ = self._plan({CLOSE_CLONE_KEY: True}, clean=True, all_done=False)
        self.assertFalse(planned)

    def test_failure_with_clean_rule_keeps_the_clone(self):
        config = {CLOSE_CLONE_KEY: True, CLOSE_GAME_WHEN_KEY: CLOSE_WHEN_CLEAN}
        planned, _ = self._plan(config, clean=False)
        self.assertFalse(planned)

    def test_failure_with_always_rule_ends_it(self):
        config = {CLOSE_CLONE_KEY: True, CLOSE_GAME_WHEN_KEY: CLOSE_WHEN_ALWAYS}
        planned, _ = self._plan(config, clean=False)
        self.assertTrue(planned)

    def test_not_before_a_re_login_that_runs_on(self):
        config = {CLOSE_CLONE_KEY: True, CLOSE_GAME_WHEN_KEY: CLOSE_WHEN_ALWAYS}
        planned, _ = self._plan(config, clean=False, resume=True)
        self.assertFalse(planned)

    def test_waits_for_the_last_account_in_line(self):
        planned, _ = self._plan({CLOSE_CLONE_KEY: True}, clean=True, others=True)
        self.assertFalse(planned)

    def test_does_not_need_close_game(self):
        planned, _ = self._plan({CLOSE_CLONE_KEY: True, CLOSE_GAME_KEY: False}, clean=True)
        self.assertTrue(planned)


class AfterReportTest(unittest.TestCase):
    def test_ends_the_clone_after_a_pause_once(self):
        task = _task({})
        task._end_clone_after_run = True
        with (
            mock.patch.object(batch_module.time, "sleep") as sleep,
            mock.patch.object(clone_desktop, "end_from_inside", return_value=True) as end,
            mock.patch("threading.Thread") as thread,
        ):
            thread.side_effect = lambda target, **_kw: SimpleNamespace(start=target)
            task._close_clone_if_planned()
            task._close_clone_if_planned()
        end.assert_called_once_with(clone_desktop.END_JUST_CLOSE)
        sleep.assert_called_once_with(batch_module.CLOSE_CLONE_DELAY_SECONDS)
        task.log_warning.assert_not_called()

    def test_move_to_desktop_is_passed_on(self):
        task = _task({CLOSE_CLONE_HOW_KEY: CLOSE_CLONE_MOVE})
        task._end_clone_after_run = True
        with (
            mock.patch.object(batch_module.time, "sleep"),
            mock.patch.object(clone_desktop, "end_from_inside", return_value=True) as end,
            mock.patch("threading.Thread") as thread,
        ):
            thread.side_effect = lambda target, **_kw: SimpleNamespace(start=target)
            task._close_clone_if_planned()
        end.assert_called_once_with(clone_desktop.END_MOVE_TO_DESKTOP)

    def test_just_close_is_the_default(self):
        self.assertEqual(CLOSE_CLONE_JUST, _task({}).config[CLOSE_CLONE_HOW_KEY])

    def test_says_how_when_it_could_not(self):
        task = _task({})
        task._end_clone_after_run = True
        with (
            mock.patch.object(batch_module.time, "sleep"),
            mock.patch.object(clone_desktop, "end_from_inside", return_value=False),
            mock.patch("threading.Thread") as thread,
        ):
            thread.side_effect = lambda target, **_kw: SimpleNamespace(start=target)
            task._close_clone_if_planned()
        self.assertIn("X", task.log_warning.call_args.args[0])


class EndFromInsideTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.request = Path(folder.name) / "end-request.txt"
        for name, value in (
            ("DATA_DIR", Path(folder.name)),
            ("END_REQUEST", self.request),
            ("LOGOFF_WAIT_SECONDS", 0),
        ):
            patcher = mock.patch.object(clone_desktop, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(clone_desktop.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_outside_the_clone_does_nothing(self):
        with (
            mock.patch.object(clone_desktop, "in_clone", return_value=False),
            mock.patch.object(clone_desktop.subprocess, "run") as run,
        ):
            self.assertFalse(clone_desktop.end_from_inside(wait=0))
        run.assert_not_called()
        self.assertFalse(self.request.exists())

    def test_viewer_takes_the_request(self):
        seen = []

        def viewer_takes(_seconds):
            if self.request.exists():
                seen.append(self.request.read_text(encoding="utf-8"))
                self.request.unlink()

        with (
            mock.patch.object(clone_desktop, "in_clone", return_value=True),
            mock.patch.object(clone_desktop.time, "sleep", side_effect=viewer_takes),
            mock.patch.object(clone_desktop.subprocess, "run") as run,
            mock.patch.object(clone_desktop, "_viewer_processes") as viewers,
        ):
            self.assertTrue(
                clone_desktop.end_from_inside(clone_desktop.END_MOVE_TO_DESKTOP, wait=5)
            )
        run.assert_not_called()
        viewers.assert_not_called()
        self.assertEqual(["move"], seen)

    def test_old_viewer_is_closed_then_the_clone_signs_out(self):
        viewer = mock.Mock()
        found = [[viewer], []]
        with (
            mock.patch.object(clone_desktop, "in_clone", return_value=True),
            mock.patch.object(clone_desktop, "_viewer_processes", side_effect=found),
            mock.patch.object(clone_desktop.subprocess, "run") as run,
        ):
            self.assertTrue(clone_desktop.end_from_inside(wait=0))
        viewer.terminate.assert_called_once_with()
        self.assertEqual(["logoff"], run.call_args.args[0])

    def test_viewer_that_stays_open_leaves_the_clone_alone(self):
        viewer = mock.Mock()
        with (
            mock.patch.object(clone_desktop, "in_clone", return_value=True),
            mock.patch.object(clone_desktop, "_viewer_processes", return_value=[viewer]),
            mock.patch.object(clone_desktop.subprocess, "run") as run,
        ):
            self.assertFalse(clone_desktop.end_from_inside(wait=0))
        run.assert_not_called()
        self.assertFalse(self.request.exists())


class ViewerSourceTest(unittest.TestCase):
    def test_viewer_reads_the_same_file_and_clears_an_old_one(self):
        source = (REPO / "tools" / "clone_desktop" / "CloneDesktop.cs").read_text(encoding="utf-8")
        self.assertIn(f'"{clone_desktop.END_REQUEST.name}"', source)
        self.assertIn("File.Exists(endRequestPath)", source)
        self.assertIn("File.Delete(endRequestPath)", source)
        self.assertIn(f'asked == "{clone_desktop.END_MOVE_TO_DESKTOP}"', source)
        self.assertIn("OpenOnDesktop(moveUri)", source)


class ConfirmWindowTest(unittest.TestCase):
    """Leo 2026-11-08 「選項是 完成後關閉遊戲 或是完成後在桌面重開」「用好看直覺的
    切換開關」: one sliding switch 不关 / 关闭游戏 / 在桌面重开."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _ask(self, config, clone, act=None):
        from src.ui.shell import run_confirm

        seen = {}

        def exec_(dialog):
            seen["dialog"] = dialog
            if act:
                act(dialog, seen)
            return 0

        batch = SimpleNamespace(config=config, child_tasks=())
        with (
            mock.patch.object(run_confirm.RunConfirm, "exec", exec_),
            mock.patch.object(run_confirm.data, "batch_children", return_value=[]),
        ):
            run_confirm.ask(None, batch, clone=clone)
        return seen

    def test_only_the_clone_window_has_the_switch(self):
        config = {CLOSE_GAME_KEY: False, CLOSE_CLONE_KEY: False}
        plain = self._ask(config, clone=False)["dialog"]
        self.assertIsNone(plain.close_clone)
        self.assertFalse(plain.close_game.isHidden())
        clone = self._ask(config, clone=True)["dialog"]
        self.assertTrue(clone.close_game.isHidden())
        self.assertEqual(
            ["不关", "关闭游戏", "在桌面重开"], list(clone.close_clone._buttons)
        )

    def test_switch_shows_the_saved_choice(self):
        off = self._ask({CLOSE_GAME_KEY: False, CLOSE_CLONE_KEY: False}, clone=True)
        self.assertEqual("不关", off["dialog"].close_clone.value())
        move = {CLOSE_GAME_KEY: False, CLOSE_CLONE_KEY: True, CLOSE_CLONE_HOW_KEY: CLOSE_CLONE_MOVE}
        self.assertEqual(CLOSE_CLONE_MOVE, self._ask(move, clone=True)["dialog"].close_clone.value())

    def test_choice_is_kept_and_shows_when_to_close(self):
        config = {CLOSE_GAME_KEY: False, CLOSE_CLONE_KEY: False}

        def act(dialog, seen):
            seen["hidden_at_first"] = dialog.close_when.isHidden()
            dialog.close_clone._buttons[CLOSE_CLONE_MOVE].click()
            seen["shown"] = not dialog.close_when.isHidden()
            seen["after_move"] = dict(config)
            dialog.close_clone._buttons["不关"].click()
            seen["hidden_again"] = dialog.close_when.isHidden()

        seen = self._ask(config, clone=True, act=act)
        self.assertTrue(seen["hidden_at_first"])
        self.assertTrue(seen["shown"])
        self.assertIs(True, seen["after_move"][CLOSE_CLONE_KEY])
        self.assertEqual(CLOSE_CLONE_MOVE, seen["after_move"][CLOSE_CLONE_HOW_KEY])
        self.assertTrue(seen["hidden_again"])
        self.assertIs(False, config[CLOSE_CLONE_KEY])
        self.assertEqual(CLOSE_CLONE_MOVE, config[CLOSE_CLONE_HOW_KEY])


class TaskSettingsTest(unittest.TestCase):
    def test_switch_sits_after_when_to_close(self):
        from src.ui.shell.task_page import BATCH_OPTION_LABELS

        keys = list(BATCH_OPTION_LABELS)
        self.assertEqual(keys.index(CLOSE_GAME_WHEN_KEY) + 1, keys.index(CLOSE_CLONE_KEY))
        self.assertEqual(keys.index(CLOSE_CLONE_KEY) + 1, keys.index(CLOSE_CLONE_HOW_KEY))
        self.assertLess(keys.index(CLOSE_CLONE_HOW_KEY), keys.index("完成日常后自动关机"))


if __name__ == "__main__":
    unittest.main()
