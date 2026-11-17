"""Player v0.3.20 2026-11-17 (2560x1440 at 150%, no clone): every real-mouse
drag of the sale list was refused (「游戏窗口不在最前面或被其他窗口遮住」) while
clicks went on.  Each 卖 failed, went home and came back the same, so 单独运行
每日跑商 went round for 23 minutes, and the report never said which window
was in the way.

Now a refused real drag is posted to the game window instead (the way clicks
reach a game behind other windows); only when that cannot be made either does
the sell stop, with what was in front, and nothing redoes it from 主页.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import BaseBD2Task as base_module
from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.MapTradeTask import MapTradeTask
from src.tasks.map_trade.trader_sell import SellFlowMixin


class _Swipes:
    def __init__(self):
        self.calls = []

    def post_swipe(self, x1, y1, x2, y2, duration=0.4, steps=12):
        self.calls.append(((x1, y1), (x2, y2), duration))


def _task(interaction, *, front=False, on_game=True, foreground_why=""):
    class Task(BaseBD2Task):
        @property
        def executor(self):
            return SimpleNamespace(interaction=interaction)

    task = object.__new__(Task)
    task.operate = lambda func, block=True, restore_cursor=True: func()
    task.sleep = lambda _seconds: None
    task.info = {}
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    task.log_info = mock.Mock()
    task.log_warning = mock.Mock()

    def bring():
        task._foreground_why = "" if front else foreground_why
        return front

    task._bring_game_to_foreground = bring
    task._point_on_game = lambda _point: on_game
    task._game_window_handles = lambda: {101}
    return task


class RefusedDragFallsBackToPostedDragTest(unittest.TestCase):
    def test_game_kept_from_the_front_is_dragged_by_posted_messages(self):
        swipes = _Swipes()
        task = _task(swipes, foreground_why="最前面是 chrome.exe（Chrome_WidgetWin_1），Windows 拒绝把游戏换到前面")
        with (
            mock.patch("win32api.mouse_event") as mouse,
            mock.patch("win32api.SetCursorPos"),
            mock.patch("win32gui.IsIconic", return_value=False),
            mock.patch("time.sleep"),
        ):
            self.assertTrue(task.drag_client((620, 330), (620, 870), duration=0.5))
        mouse.assert_not_called()  # the player's real button is never pressed
        self.assertEqual([((620, 330), (620, 870), 0.5)], swipes.calls)
        self.assertEqual("", task.drag_refused_why)
        said = task.log_info.call_args.args[0]
        self.assertIn("chrome.exe", said)
        self.assertIn("后台方式拖动", said)
        task.log_warning.assert_not_called()

    def test_game_covered_by_another_window_names_that_window(self):
        swipes = _Swipes()
        task = _task(swipes, front=True, on_game=False)
        with (
            mock.patch("win32api.mouse_event") as mouse,
            mock.patch("win32api.SetCursorPos"),
            mock.patch("win32gui.IsIconic", return_value=False),
            mock.patch("time.sleep"),
            mock.patch.object(
                base_module, "_window_at_words", return_value=" StickyNotes.exe（ApplicationFrameWindow）的窗口"
            ),
        ):
            self.assertTrue(task.drag_client((620, 330), (620, 870)))
        mouse.assert_not_called()
        self.assertEqual(1, len(swipes.calls))
        self.assertIn("StickyNotes.exe", task.log_info.call_args.args[0])

    def test_the_cause_is_logged_once_not_on_every_drag(self):
        swipes = _Swipes()
        task = _task(swipes, foreground_why="最前面是 qq.exe（TXGuiFoundation）")
        with mock.patch("win32gui.IsIconic", return_value=False):
            for _ in range(3):
                self.assertTrue(task.drag_client((1, 2), (3, 4)))
        self.assertEqual(3, len(swipes.calls))
        self.assertEqual(1, task.log_info.call_count)

    def test_without_a_posted_way_the_refusal_says_why(self):
        task = _task(SimpleNamespace(), foreground_why="最前面是 qq.exe（TXGuiFoundation）")
        self.assertFalse(task.drag_client((1, 2), (3, 4)))
        self.assertIn("qq.exe", task.drag_refused_why)
        self.assertIn("qq.exe", task.log_warning.call_args.args[0])

    def test_a_minimized_game_is_not_dragged_at_all(self):
        swipes = _Swipes()
        task = _task(swipes)
        with mock.patch("win32gui.IsIconic", return_value=True):
            self.assertFalse(task.drag_client((1, 2), (3, 4)))
        self.assertEqual([], swipes.calls)

    def test_a_real_drag_still_comes_first(self):
        swipes = _Swipes()
        task = _task(swipes, front=True, on_game=True)
        with (
            mock.patch("win32api.mouse_event") as mouse,
            mock.patch("win32api.SetCursorPos"),
            mock.patch("time.sleep"),
        ):
            self.assertTrue(task.drag_client((1, 2), (3, 4), duration=0.0))
        self.assertEqual(2, mouse.call_count)
        self.assertEqual([], swipes.calls)


class PointOnGameTest(unittest.TestCase):
    def test_another_window_of_the_game_program_counts_as_the_game(self):
        task = object.__new__(BaseBD2Task)
        task._game_window_handles = lambda: {101}
        pids = {101: 7, 202: 7, 303: 9}
        with (
            mock.patch("src.utils.game_status_bar.window_at", side_effect=lambda p: p[0]),
            mock.patch("win32gui.GetAncestor", side_effect=lambda hwnd, _flag: hwnd),
            mock.patch(
                "win32process.GetWindowThreadProcessId",
                side_effect=lambda hwnd: (1, pids[hwnd]),
            ),
        ):
            self.assertTrue(task._point_on_game((101, 0)))
            self.assertTrue(task._point_on_game((202, 0)))  # the game's own popup
            self.assertFalse(task._point_on_game((303, 0)))  # another program


class RefusedSaleListStopsWithoutRedoTest(unittest.TestCase):
    def test_the_sell_says_why_and_asks_for_no_redo(self):
        no_redo = []
        warnings = []
        trader = object.__new__(SellFlowMixin)
        trader.task = SimpleNamespace(
            drag_client=lambda *a, **k: False,
            drag_refused_why="游戏画面被 StickyNotes.exe（ApplicationFrameWindow）的窗口盖住",
            log_warning=lambda message, **_k: warnings.append(message),
            log_info=lambda *a, **k: None,
            no_redo=no_redo.append,
        )
        trader.vision = SimpleNamespace(capture=lambda: np.zeros((1080, 1920, 3), np.uint8))
        trader._status = lambda *a: None
        trader._sale_list_view = lambda: np.zeros((64, 96), np.int16)
        entry = SimpleNamespace(item="米", asset=False)
        self.assertFalse(trader._sell_selected_entry(entry))
        self.assertIn("StickyNotes.exe", warnings[-1])
        self.assertIn("StickyNotes.exe", trader._last_sale_reason)
        self.assertEqual(1, len(no_redo))
        self.assertIn("出售列表拖不动", no_redo[0])


class NoRedoFromHomeTest(unittest.TestCase):
    def test_a_phase_that_asked_for_no_redo_is_not_done_again(self):
        task = object.__new__(MapTradeTask)
        task.log_info = mock.Mock()
        task.log_warning = mock.Mock()
        task._return_home_after_phases = mock.Mock(return_value=True)
        calls = []

        def sell():
            calls.append("sell")
            task.no_redo("卖：出售列表拖不动（游戏窗口没能换到最前面）")
            return False

        trader = SimpleNamespace(left_shop=mock.Mock())
        self.assertFalse(task._once_more_from_home(None, trader, "卖", sell, "再卖一次"))
        self.assertEqual(["sell"], calls)
        task._return_home_after_phases.assert_not_called()
        self.assertIn("不再重来", task.log_warning.call_args.args[0])

    def test_the_task_is_not_run_again_from_home(self):
        task_type = type("Task", (), {"frozen_retry": True, "failure_retry": None})
        task = task_type()
        task.name = "每日跑商"
        task._why = ""
        task.log_warning = mock.Mock()
        task.log_info = mock.Mock()
        calls = []

        def run(t):
            calls.append(1)
            t._no_redo_why = "卖：出售列表拖不动（游戏窗口没能换到最前面）"
            t._why = t._no_redo_why
            return False

        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True) as home:
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual(1, len(calls))
        home.assert_not_called()
        self.assertIn("不再重做", task.log_warning.call_args.args[0])
        self.assertIn("出售列表拖不动", task._why)

    def test_other_failures_are_still_redone_once(self):
        task_type = type("Task", (), {"frozen_retry": True, "failure_retry": None})
        task = task_type()
        task.name = "每日跑商"
        task._why = ""
        task.log_warning = mock.Mock()
        task.log_info = mock.Mock()
        results = iter([False, True])
        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True):
            self.assertTrue(
                base_module._run_watched(task, lambda t: next(results), (), {}, watched=True)
            )


if __name__ == "__main__":
    unittest.main()
