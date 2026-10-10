"""Recovery closes only harmless dialogs and hands the title screen to login."""

import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import recovery, run_report, scheduler
from src.tasks.DailyBatchTask import (
    RUN_MODE_ALL,
    RUN_MODE_INCOMPLETE,
    DailyBatchChild,
    DailyBatchTask,
)
from src.tasks.run_history import RunHistoryStore, set_default_store

_report_dir = None


def setUpModule():
    # Batches save a run report; keep it out of the real configs folder.
    global _report_dir
    _report_dir = tempfile.TemporaryDirectory()
    run_report.set_report_file(f"{_report_dir.name}/run_reports.json")


def tearDownModule():
    run_report.set_report_file(None)
    _report_dir.cleanup()


def _box(name, x=100, y=100):
    return SimpleNamespace(name=name, x=x, y=y, width=40, height=20)


def _task(names):
    clicks = []
    task = SimpleNamespace(
        capture_frame=lambda: np.zeros((1080, 1920, 3), np.uint8),
        log_info=lambda *a, **k: None,
        operate_click=lambda x, y, after_sleep=0: clicks.append((x, y)),
        _ocr_box_center=lambda box: (box.x + 20, box.y + 10),
    )
    vision = SimpleNamespace(ocr_boxes=lambda frame, name: [_box(n) for n in names])
    return task, vision, clicks


class HandleDialogTest(unittest.TestCase):
    def test_title_screen_is_reported_not_clicked(self):
        task, vision, clicks = _task(["TOUCH TO START", "BrownDust2"])
        self.assertEqual("title", recovery._handle_dialog(task, vision))
        self.assertEqual([], clicks)

    def test_info_only_confirm_needs_its_title(self):
        task, vision, clicks = _task(["获得道具", "确认"])
        self.assertEqual("dismissed", recovery._handle_dialog(task, vision))
        self.assertEqual(1, len(clicks))

    def test_a_purchase_confirm_is_never_pressed(self):
        task, vision, clicks = _task(["是否购买", "消耗 100 钻石", "确认"])
        self.assertEqual("none", recovery._handle_dialog(task, vision))
        self.assertEqual([], clicks)

    def test_tap_anywhere_overlays_are_closed(self):
        task, vision, clicks = _task(["点击空白处关闭"])
        self.assertEqual("dismissed", recovery._handle_dialog(task, vision))

    def test_cancel_still_wins_over_confirm(self):
        task, vision, clicks = _task(["获得道具", "确认", "取消"])
        # 取消 is tried first; the click lands on the 取消 box.
        self.assertEqual("dismissed", recovery._handle_dialog(task, vision))


class TitleScreenBatchTest(unittest.TestCase):
    def _batch(self, calls):
        """第一项 done, then 失败项 lands on the title screen once, then 后续项."""

        class First:
            pass

        class Failed:
            pass

        class Later:
            pass

        def child(name, result=lambda: True):
            def run():
                calls.append(name)
                return result()

            return SimpleNamespace(name=name, config={}, info_clear=lambda: None, run=run)

        title = {"left": 1}

        def on_title():
            title["left"] -= 1
            return title["left"] < 0

        children = {
            First: child("公会、小屋、酒馆"),
            Failed: child("快速狩猎", on_title),
            Later: child("广场女神像"),
        }
        task = object.__new__(DailyBatchTask)
        task.child_tasks = (
            DailyBatchChild("第一项", First),
            DailyBatchChild("失败项", Failed),
            DailyBatchChild("后续项", Later),
        )
        task.config = {"启用": True, "第一项": True, "失败项": True, "后续项": True}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = task.log_warning = task.log_error = lambda *a, **k: None
        task._executor = SimpleNamespace(
            get_task_by_class=lambda cls: children.get(cls),
            reset_scene=lambda **k: None,
        )
        task._auto_login_pending = lambda: False

        def recover(child):
            child._recovery_saw_title = True
            task._auto_login_pending = lambda: True  # recovery re-armed login
            return False

        patcher = mock.patch.object(DailyBatchTask, "_recover_home", staticmethod(recover))
        patcher.start()
        self.addCleanup(patcher.stop)
        return task

    def _logged_in(self, task, calls):
        task._auto_login_pending = lambda: False
        calls.clear()

    def test_batch_waits_for_login_and_keeps_later_children_due(self):
        calls = []
        task = self._batch(calls)
        schedule = mock.Mock()
        with mock.patch("src.tasks.scheduler.default_store", return_value=schedule):
            self.assertFalse(DailyBatchTask.run(task, RUN_MODE_ALL))
        self.assertEqual(["公会、小屋、酒馆", "快速狩猎"], calls)
        self.assertTrue(task._start_after_login)
        # The mode the player picked (here 跑勾选的), not 跑没跑完的.
        self.assertEqual(RUN_MODE_ALL, task._take_run_mode(None))
        # Not their fault: neither the interrupted child nor the later ones
        # wait out a failure backoff in the run after login.
        waits = schedule.delay_after_run.call_args_list
        self.assertNotIn(mock.call("快速狩猎", ok=False), waits)
        self.assertNotIn(mock.call("广场女神像", ok=False), waits)

    def test_the_run_after_the_login_goes_on_from_where_it_was(self):
        # 跑勾选的: what this run did is not done again, the interrupted one is.
        calls = []
        task = self._batch(calls)
        with mock.patch("src.tasks.scheduler.default_store", return_value=mock.Mock()):
            DailyBatchTask.run(task, RUN_MODE_ALL)
            self._logged_in(task, calls)
            self.assertTrue(DailyBatchTask.run(task))
        self.assertEqual(["快速狩猎", "广场女神像"], calls)
        self.assertEqual(run_report.ENDED_DONE, task._report_ended)

    def test_a_left_items_run_does_the_interrupted_child_after_the_login(self):
        # It used to wait out a 5-minute failure backoff, so the run after
        # the login skipped it and still ended 完成.
        calls = []
        task = self._batch(calls)
        with tempfile.TemporaryDirectory() as folder:
            schedule = scheduler.TaskScheduleStore(f"{folder}/schedule.json")
            scheduler.set_default_store(schedule)
            set_default_store(RunHistoryStore(f"{folder}/history.json"))
            try:
                DailyBatchTask.run(task, RUN_MODE_INCOMPLETE)
                self.assertEqual(RUN_MODE_INCOMPLETE, task._requested_run_mode)
                self._logged_in(task, calls)
                self.assertTrue(DailyBatchTask.run(task))
            finally:
                scheduler.set_default_store(None)
                set_default_store(None)
        self.assertEqual(["快速狩猎", "广场女神像"], calls)


if __name__ == "__main__":
    unittest.main()


class FastRecoveryTest(unittest.TestCase):
    """Live 2026-09-27: leaving the event took 15 s of unchanged screens."""

    def test_home_after_a_back_press_is_seen_without_reclassifying(self):
        from src.tasks.map_trade.models import ScreenState

        presses, classified = [], []
        home = [False]

        class FakeNavigator:
            def __init__(self, task, vision):
                self.vision = SimpleNamespace(capture=lambda: None)

            def _home_confirmation_signals(self, _frame):
                return (home[0], 0, 0.0, "")

            def classify(self):
                classified.append(1)
                return ScreenState.UNKNOWN

            def clear_home_announcement(self, _frame, _clicks=0):
                return False

        def press(*_a, **_k):
            presses.append(1)
            home[0] = len(presses) == 2

        task = SimpleNamespace(
            info_set=lambda *a: None,
            log_info=lambda *a, **k: None,
            sleep=lambda *_a: None,
            operate_click=press,
        )
        with (
            mock.patch.object(recovery, "Navigator", FakeNavigator),
            mock.patch.object(recovery, "Vision", lambda task: None),
            mock.patch.object(recovery, "_handle_dialog", lambda *_a: "none"),
            mock.patch.object(recovery, "monotonic", iter(range(0, 1000)).__next__),
        ):
            self.assertTrue(recovery.recover_to_home(task))
        self.assertEqual(2, len(presses))
        self.assertEqual(2, len(classified))

    def _run(self, frames, announcement=lambda frame: False):
        """recover_to_home over a scripted frame list; returns back presses."""
        from src.tasks.map_trade.models import ScreenState

        presses = []
        state = {"frames": list(frames)}

        def capture():
            return state["frames"][0] if len(state["frames"]) == 1 else state["frames"].pop(0)

        class FakeNavigator:
            def __init__(self, task, vision):
                self.vision = SimpleNamespace(capture=capture)

            def _home_confirmation_signals(self, frame):
                return (frame is HOME, 0, 0.0, "")

            def classify(self):
                return ScreenState.UNKNOWN

            def clear_home_announcement(self, frame, _clicks=0):
                if announcement(frame):
                    state["frames"] = [HOME]
                    return True
                return False

        task = SimpleNamespace(
            info_set=lambda *a: None,
            log_info=lambda *a, **k: None,
            sleep=lambda *_a: None,
            operate_click=lambda *_a, **_k: presses.append(1),
        )
        with (
            mock.patch.object(recovery, "Navigator", FakeNavigator),
            mock.patch.object(recovery, "Vision", lambda task: None),
            mock.patch.object(recovery, "_handle_dialog", lambda *_a: "none"),
            mock.patch.object(recovery, "monotonic", iter(range(0, 1000)).__next__),
        ):
            reached = recovery.recover_to_home(task)
        return reached, presses

    def test_black_loading_screen_is_waited_out_not_pressed(self):
        # Live 2K 2026-09-29: back pressed 4 times into the event->home loading.
        black = np.zeros((1080, 1920, 3), np.uint8)
        reached, presses = self._run([black, black, black, black, HOME])
        self.assertTrue(reached)
        self.assertEqual([], presses)

    def test_update_notice_over_home_is_cleared(self):
        notice = np.full((1080, 1920, 3), 120, np.uint8)
        reached, presses = self._run([notice], announcement=lambda frame: frame is notice)
        self.assertTrue(reached)
        self.assertEqual([], presses)


HOME = np.full((1080, 1920, 3), 200, np.uint8)
