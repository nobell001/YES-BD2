"""Behaviour tests for EventBattleTask safety paths (no game, stubbed I/O)."""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks import EventBattleTask as event_module
from src.tasks.EventBattleTask import (
    PROGRESS_ROI,
    RESULT_BUTTONS_ROI,
    EventBattleTask,
    ap_spent,
    parse_ap,
)


def box(name, x=0, y=0, width=40, height=20):
    return SimpleNamespace(name=name, x=x, y=y, width=width, height=height)


def make_task():
    task = object.__new__(EventBattleTask)
    task.config = {}
    task.info = {}
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    task.log_info = lambda *args, **kwargs: None
    task.log_warning = mock.Mock()
    task.sleep = lambda *_args: None
    task._battles_done = 0
    return task


class ApShortagePopupTest(unittest.TestCase):
    def _task_with_boxes(self, boxes):
        task = make_task()
        task.capture_frame = lambda: None
        task._roi_boxes = lambda frame, roi, name: boxes
        clicks = []
        task._click_box = lambda target, after_sleep=0: clicks.append(target.name)
        task._click_reference = lambda x, y, after_sleep=0: clicks.append((x, y))
        return task, clicks

    def test_cancels_and_never_presses_refill(self):
        # Live popup text 2026-09-25: 活动AP不足 / 取消 (875,690) / 补充 (1044,690).
        task, clicks = self._task_with_boxes(
            [box("活动AP不足"), box("活动AP不足，无法战斗。"), box("取消", 855), box("补充", 1024)]
        )
        self.assertTrue(task._dismiss_ap_shortage())
        self.assertEqual(["取消"], clicks)

    def test_never_clicks_blind_when_cancel_is_unreadable(self):
        # A fixed point sat next to 补充 (paid refill): no box, no click.
        task, clicks = self._task_with_boxes([box("活动AP不足"), box("补充", 1024)])
        self.assertTrue(task._dismiss_ap_shortage())
        self.assertEqual([], clicks)
        task.log_warning.assert_called_once()

    def test_no_popup_means_no_click(self):
        task, clicks = self._task_with_boxes([box("自动战斗"), box("取消")])
        self.assertFalse(task._dismiss_ap_shortage())
        self.assertEqual([], clicks)


class FailureSettleTest(unittest.TestCase):
    """Review 2026-09-26: a failure mid-chain leaves the result screen first."""

    def test_waits_for_the_battle_then_presses_back(self):
        task = make_task()
        frames = iter(["battle", "battle", "result", "result"])
        task.capture_frame = lambda: next(frames)
        task._in_battle = lambda frame: frame == "battle"
        task._roi_boxes = lambda frame, roi, name: [box("返回")] if frame == "result" else []
        task._leave_result_screen = mock.Mock(return_value=True)
        task._settle_before_recovery()
        task._leave_result_screen.assert_called_once()

    def test_nothing_to_do_outside_a_battle(self):
        task = make_task()
        task.capture_frame = lambda: "stage"
        task._in_battle = lambda frame: False
        task._roi_boxes = lambda frame, roi, name: [box("自动战斗")]
        task._leave_result_screen = mock.Mock()
        task._settle_before_recovery()
        task._leave_result_screen.assert_not_called()


class ApReadingTest(unittest.TestCase):
    def test_currency_glued_to_the_pool_is_not_read_as_ap(self):
        self.assertEqual((0, 0), parse_ap("8,5000/5"))
        self.assertEqual((0, 3), parse_ap("8,500 0/5 +3"))

    def test_currency_glued_to_a_full_pool(self):
        # Live 2026-10-09 (桌面分身, 1920x1080): OCR read 5,900 and 5/5 as one.
        self.assertEqual((5, 0), parse_ap("5,9005/5"))
        self.assertEqual((3, 2), parse_ap("12,3453/5 +2"))
        self.assertEqual((5, 0), parse_ap("21:59 10,000 5/5"))

    def test_ap_spent_counts_free_and_bonus(self):
        before = {"free_ap": 5, "bonus_ap": 3}
        self.assertEqual(4, ap_spent(before, {"free_ap": 1, "bonus_ap": 3}))
        self.assertEqual(6, ap_spent(before, {"free_ap": 0, "bonus_ap": 2}))
        self.assertEqual(0, ap_spent(before, {"free_ap": None, "bonus_ap": 0}))


class EventEntryTest(unittest.TestCase):
    def test_no_banner_on_a_confirmed_home_is_no_event(self):
        task = make_task()
        task._wait_for_home_confirmation = lambda *args, **kwargs: True
        task._find_stable_banner = lambda keywords: None
        task._wait_for_hub = lambda timeout=0: False
        task._wait_for_stage_page = lambda mode, timeout=0, quiet=False: False
        with mock.patch.object(event_module, "recover_to_home", return_value=True):
            self.assertEqual("no_event", task._enter_hub())

    def test_second_mode_backs_out_to_the_hub_instead_of_going_home(self):
        # User 2026-09-27: after 普通战斗 it went home and through the banner.
        task = make_task()
        hub = iter([False, True])
        task._wait_for_hub = lambda timeout=0: next(hub)
        task._wait_for_stage_page = lambda mode, timeout=0, quiet=False: mode == "普通战斗"
        clicks = []
        task._click_reference = lambda x, y, after_sleep=0: clicks.append((x, y))
        with mock.patch.object(
            event_module, "recover_to_home", side_effect=AssertionError("went home")
        ):
            self.assertEqual("ok", task._enter_hub())
        self.assertEqual([event_module.BACK_BUTTON_POINT], clicks)

    def test_no_event_finishes_successfully_with_a_warning(self):
        task = make_task()
        task._run_mode = lambda mode: "no_event"
        finished = []
        task._finish = lambda message: finished.append(message) or True
        self.assertTrue(task.run_claim())
        self.assertEqual(["未发现进行中的活动"], finished)
        task.log_warning.assert_called_once()

    def test_unexecuted_quick_battle_warns_instead_of_claiming_done(self):
        task = make_task()
        task._run_mode = lambda mode: "cleared"
        task._run_quick_battle = lambda: "skipped"
        finished = []
        task._finish = lambda message: finished.append(message) or True
        self.assertTrue(task.run_claim())
        self.assertEqual(["快速战斗未执行"], finished)
        task.log_warning.assert_called_once()


class WatchAutoBattleTest(unittest.TestCase):
    def _run(self, frames, planned):
        task = make_task()
        self.consumed = 0
        frames = iter(frames)

        def capture():
            self.consumed += 1
            return next(frames)

        task.capture_frame = capture

        def roi_boxes(frame, roi, name):
            if roi == PROGRESS_ROI:
                return [box(text) for text in frame.get("progress", [])]
            if roi == RESULT_BUTTONS_ROI:
                return [box(text) for text in frame.get("buttons", [])]
            return []

        task._roi_boxes = roi_boxes
        task._leave_result_screen = lambda: True
        task._dismiss_ap_shortage = lambda: False
        return task._watch_auto_battle(planned)

    def test_count_never_drops_below_the_planned_battles(self):
        battle = {"progress": ["自动战斗进行中：第1次／共3次"], "buttons": ["结束自动战斗"]}
        result = {"buttons": ["返回", "前往下一个战斗"]}
        self.assertEqual(3, self._run([battle, result, result], planned=3))

    def test_a_single_result_frame_is_not_enough(self):
        battle = {"progress": ["自动战斗进行中：第2次/共2次"], "buttons": ["结束自动战斗"]}
        result = {"buttons": ["返回"]}
        blank = {}
        # result, blank, result: never two calm frames in a row until the end.
        frames = [battle, result, blank, battle, result, result]
        self.assertEqual(2, self._run(frames, planned=2))
        self.assertEqual(len(frames), self.consumed)


if __name__ == "__main__":
    unittest.main()


class QuickBattleTest(unittest.TestCase):
    """Calibrated live at 1080p 2026-09-28: challenge 15 quick battle."""

    def _task(self, costs, free_ap=5, switch_on=True):
        from src.tasks.EventBattleTask import EventBattleTask

        task = object.__new__(EventBattleTask)
        task.config = {}
        task._battles_done = 0
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task._sleep_after_recognition = lambda: None
        task.clicks = []
        task._click_reference = lambda x, y, after_sleep=0: task.clicks.append((x, y))
        task._click_box = lambda box, after_sleep=0: task.clicks.append(box.name)
        task._open_mode = lambda mode: "ok"
        task._stable_stage_state = lambda mode: {
            "stage": 15, "free_ap": free_ap, "bonus_ap": 0, "auto": False, "quick": True
        }
        task._open_quick_dialog = lambda: True
        task._ensure_free_ap_switch_on = lambda *a: switch_on
        # Each value is read twice: a count counts once two reads agree.
        costs = iter([value for value in costs for _ in range(2)])
        task._quick_cost = lambda: next(costs)
        task.sleep = lambda *_a: None
        task.capture_frame = lambda: None
        task._roi_boxes = lambda *a: [SimpleNamespace(name="战斗5")]
        task._wait_quick_result = lambda: "done"
        return task

    def test_max_within_free_ap_is_started_and_counted(self):
        task = self._task([5])
        self.assertEqual("done", task._run_quick_battle())
        self.assertEqual(5, task._battles_done)
        self.assertIn("战斗5", task.clicks)

    def test_cost_above_free_ap_is_cancelled(self):
        # MAX read 8 and lowering failed to bring it under the free 5.
        task = self._task([8, 8])
        self.assertEqual("failed", task._run_quick_battle())
        self.assertNotIn("战斗5", task.clicks)
        self.assertEqual(0, task._battles_done)

    def test_switch_not_on_is_cancelled(self):
        task = self._task([5], switch_on=False)
        self.assertEqual("failed", task._run_quick_battle())
        self.assertNotIn("战斗5", task.clicks)

    def test_no_free_ap_does_not_open_the_dialog(self):
        task = self._task([5], free_ap=0)
        task._open_quick_dialog = lambda: self.fail("dialog opened without AP")
        self.assertEqual("no_ap", task._run_quick_battle())


class FreeApSwitchTest(unittest.TestCase):
    """Review #28: a second press only when the first changed nothing."""

    def _task(self, ratio, after_click):
        task = make_task()
        task.switch = ratio
        task.clicks = []

        def click(x, y, after_sleep=0):
            task.clicks.append((x, y))
            task.switch = after_click(task.switch)

        task._click_reference = click
        task._free_ap_switch_ratio = lambda roi: task.switch
        settle = mock.patch.object(event_module, "FREE_AP_SWITCH_SETTLE_SECONDS", 0.0)
        settle.start()
        self.addCleanup(settle.stop)
        return task

    def test_an_off_switch_is_turned_on_with_one_click(self):
        task = self._task(0.0, lambda _ratio: 0.4)
        self.assertTrue(
            task._ensure_free_ap_switch_on(
                event_module.QUICK_FREE_AP_SWITCH_POINT, event_module.QUICK_FREE_AP_SWITCH_ROI
            )
        )
        self.assertEqual([event_module.QUICK_FREE_AP_SWITCH_POINT], task.clicks)

    def test_a_switch_never_read_as_on_is_clicked_twice_at_most(self):
        task = self._task(0.0, lambda ratio: ratio)
        self.assertFalse(task._ensure_free_ap_switch_on())
        self.assertEqual([event_module.FREE_AP_SWITCH_POINT] * 2, task.clicks)


class FailReasonTest(unittest.TestCase):
    """A player's 问题摘要 said only 「普通战斗失败」 (2026-10-10): every
    failure now says why, in 停在 and in the last line."""

    def _task(self):
        task = make_task()
        task.name = "活动每日战斗"
        task._save_flow_diagnostic = lambda name: None
        task._settle_before_recovery = lambda: None
        task.info_snapshot = lambda: dict(task.info)
        patcher = mock.patch.object(event_module, "recover_to_home", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        return task

    def _summary_stage(self, task):
        from src.tasks import problem_report

        return problem_report._stage(task)

    def test_unread_ap_is_named(self):
        task = self._task()
        task._open_mode = lambda mode: "ok"
        task._stable_stage_state = lambda mode: {
            "stage": 3,
            "free_ap": None,
            "bonus_ap": 0,
            "auto": True,
            "quick": False,
        }
        self.assertFalse(task.run_claim())
        line = "活动每日战斗：普通战斗失败：关卡页上方的活动AP没读到。"
        self.assertEqual(line, task.info["状态"])
        self.assertEqual("普通战斗失败：关卡页上方的活动AP没读到", self._summary_stage(task))
        task.log_warning.assert_called_once_with(line)

    def test_event_page_that_never_opens_is_named(self):
        task = self._task()
        task._wait_for_hub = lambda timeout=0: False
        task._wait_for_stage_page = lambda mode, timeout=0, quiet=False: False
        homes = iter([True, False])
        task._wait_for_home_confirmation = lambda *a, **k: next(homes)
        task._find_stable_banner = lambda keywords: box("活动")
        task._sleep_after_recognition = lambda: None
        task._click_box = lambda *a, **k: None
        self.assertFalse(task.run_claim())
        self.assertEqual(
            "普通战斗失败：点了活动横幅后，活动页一直没出来", self._summary_stage(task)
        )

    def test_count_check_names_the_numbers(self):
        task = self._task()
        task._open_mode = lambda mode: "ok"
        task._stable_stage_state = lambda mode: {
            "stage": 3,
            "free_ap": 2,
            "bonus_ap": 0,
            "auto": True,
            "quick": False,
        }
        task._sleep_after_recognition = lambda: None
        task._click_reference = lambda *a, **k: None
        task._dismiss_ap_shortage = lambda: False
        task._wait_for_dialog = lambda: True
        task._ensure_free_ap_switch_on = lambda *a: True
        task._settled_cost = lambda read: 5
        self.assertFalse(task.run_claim())
        self.assertIn("场数对不上（读到 5，要打 2，免费AP 2），所以没开打", task.info["状态"])

    def test_a_failure_without_a_known_reason_keeps_the_old_line(self):
        task = self._task()
        task._why = "上次的原因"
        task._run_mode = lambda mode: "failed"
        self.assertFalse(task.run_claim())
        self.assertEqual("活动每日战斗：普通战斗失败。", task.info["状态"])
