"""活动每日战斗 after a lost battle, and the stage settings (2026-10-14).

B站 players 界限突破神孙策 and 岩盐咸: a 挑战战斗 stage too hard for their team
(e.g. 15) left the run on the defeat screen, never going on.  The watch only
knew the win screen's bottom-right 返回.  They also asked for 挑战战斗最高关卡
(push only to stage N, then quick-battle N) and 只刷普通难度.  Leo's real
defeat frame (2560x1440, 2026-10-14) is read at the end of this file.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2

from src.tasks import EventBattleTask as event_module
from src.tasks.EventBattleTask import (
    CHALLENGE_CAP_KEY,
    CHALLENGE_MODE,
    DEFEAT_BLANK_POINT,
    DEFEAT_ROI,
    NORMAL_MODE,
    NORMAL_ONLY_KEY,
    PROGRESS_ROI,
    RESULT_BUTTONS_ROI,
    EventBattleTask,
)


def box(name, x=0, y=0, width=40, height=20):
    return SimpleNamespace(name=name, x=x, y=y, width=width, height=height)


def state(stage=11, free_ap=5, auto=True, quick=False):
    return {"stage": stage, "free_ap": free_ap, "bonus_ap": 0, "auto": auto, "quick": quick}


def make_task(config=None):
    task = object.__new__(EventBattleTask)
    task.name = "活动每日战斗"
    task.claim_log_name = "event_battle"
    task.config = dict(config or {})
    task.info = {}
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    task.lines = []
    task.log_info = lambda message, *a, **k: task.lines.append(message)
    task.log_warning = mock.Mock()
    task.sleep = lambda *_args: None
    task._sleep_after_recognition = lambda: None
    task._save_flow_diagnostic = lambda name: None
    task._battles_done = 0
    task._why = ""
    task._defeated = False
    task._lost_stage = None
    task.clicks = []
    task._click_box = lambda target, after_sleep=0: task.clicks.append(target.name)
    task._click_reference = lambda x, y, after_sleep=0: task.clicks.append((x, y))
    return task


class ScreenTask:
    """A task whose screen is a dict of ROI texts; presses may change it."""

    def __init__(self, screens, config=None):
        self.task = make_task(config)
        self.screens = list(screens)
        self.task.capture_frame = lambda: self.screens[0]

        def roi_boxes(frame, roi, name):
            if roi == PROGRESS_ROI:
                return [box(t) for t in frame.get("progress", [])]
            if roi == RESULT_BUTTONS_ROI:
                return [box(t) for t in frame.get("buttons", [])]
            if roi == DEFEAT_ROI:
                return [box(t) for t in frame.get("wide", [])]
            return []

        self.task._roi_boxes = roi_boxes
        self.task._dismiss_ap_shortage = lambda: False

    def next_screen_on_press(self):
        """Any press moves to the next screen."""
        def press(*_a, **_k):
            if len(self.screens) > 1:
                self.screens.pop(0)
        return press


BATTLE = {"progress": ["自动战斗进行中：第3次／共5次"], "buttons": ["结束自动战斗"]}
DEFEAT = {"wide": ["战斗失败", "重新挑战", "返回"]}
STAGE = {"wide": ["挑战战斗 15", "自动战斗"]}


class DefeatScreenTest(unittest.TestCase):
    def test_a_lost_battle_leaves_the_defeat_screen_and_is_counted(self):
        screens = ScreenTask([BATTLE, DEFEAT, DEFEAT, STAGE])
        task = screens.task
        frames = iter([BATTLE, DEFEAT, DEFEAT])
        task.capture_frame = lambda: next(frames, screens.screens[-1])
        task._leave_defeat_screen = mock.Mock(return_value=True)
        self.assertEqual(3, task._watch_auto_battle(5))
        self.assertTrue(task._defeated)
        task._leave_defeat_screen.assert_called_once()

    def test_leave_presses_back_never_retry(self):
        screens = ScreenTask([DEFEAT, STAGE])
        task = screens.task
        press = screens.next_screen_on_press()
        task._click_box = lambda target, after_sleep=0: (task.clicks.append(target.name), press())
        self.assertTrue(task._leave_defeat_screen())
        self.assertEqual(["返回"], task.clicks)

    def test_retry_alone_is_never_pressed_blank_tap_then_esc(self):
        only_retry = {"wide": ["战斗失败", "重新挑战"]}
        screens = ScreenTask([only_retry, only_retry, STAGE])
        task = screens.task
        press = screens.next_screen_on_press()
        task._click_reference = lambda x, y, after_sleep=0: (task.clicks.append((x, y)), press())
        task.tap_escape = lambda after_sleep=0: (task.clicks.append("Esc"), press()) and True
        self.assertTrue(task._leave_defeat_screen())
        self.assertEqual([DEFEAT_BLANK_POINT, "Esc"], task.clicks)
        self.assertNotIn("重新挑战", task.clicks)

    def test_a_screen_that_never_goes_fails_with_its_reason(self):
        screens = ScreenTask([DEFEAT])
        task = screens.task
        task.tap_escape = lambda after_sleep=0: True
        with mock.patch.object(event_module, "SLOW_PC_GRACE_SECONDS", 0.0):
            self.assertIsNone(task._after_defeat(2, 5))
        self.assertIn("失败画面", task._why)

    def _unknown(self, frames, stage_page=lambda: False, leave=None):
        now = [0.0]

        def clock():
            now[0] += 2.0
            return now[0]

        screens = ScreenTask([BATTLE])
        task = screens.task
        frames = iter(frames)
        task.capture_frame = lambda: next(frames)
        task._wait_for_stage_page = lambda mode, timeout=0, quiet=False: stage_page()
        task._click_box = lambda target, after_sleep=0: self.fail("pressed a button")
        task.tap_escape = lambda after_sleep=0: self.fail("pressed Esc")
        if leave is not None:
            task._leave_result_screen = leave
        with mock.patch.object(event_module, "monotonic", side_effect=clock):
            result = task._watch_auto_battle(5, CHALLENGE_MODE)
        return task, result

    def test_unknown_screen_gets_one_blank_tap_then_fails_without_esc(self):
        # Leo 2026-10-14: 8 s, not 30; never end a battle half way.
        task, result = self._unknown([BATTLE] + [{}] * 50)
        self.assertIsNone(result)
        self.assertEqual([DEFEAT_BLANK_POINT], task.clicks)
        self.assertIn("认不出的画面", task._why)

    def test_battle_text_coming_back_keeps_watching(self):
        # A skill animation hid the battle text for a while: not an end.
        result_screen = {"buttons": ["返回"]}
        task, result = self._unknown(
            [BATTLE] + [{}] * 4 + [BATTLE] + [{}] * 2 + [result_screen] * 2, leave=lambda: True
        )
        self.assertEqual(5, result)
        self.assertEqual([DEFEAT_BLANK_POINT], task.clicks)

    def test_back_on_the_stage_page_is_an_end(self):
        task, result = self._unknown([BATTLE] + [{}] * 50, stage_page=lambda: True)
        self.assertEqual(5, result)
        self.assertEqual([], task.clicks)

    def test_failure_settle_leaves_a_defeat_screen(self):
        screens = ScreenTask([DEFEAT])
        task = screens.task
        task._in_battle = lambda frame: False
        task._leave_defeat_screen = mock.Mock(return_value=True)
        task._settle_before_recovery()
        task._leave_defeat_screen.assert_called_once()

    def test_defeat_with_back_as_leo_describes(self):
        # Leo 2026-10-14 「戰敗的話也有返回 defeat那些」.
        screens = ScreenTask([{"wide": ["DEFEAT", "返回"]}, STAGE])
        task = screens.task
        self.assertTrue(task._defeat_shown())
        press = screens.next_screen_on_press()
        task._click_box = lambda target, after_sleep=0: (task.clicks.append(target.name), press())
        self.assertTrue(task._leave_defeat_screen())
        self.assertEqual(["返回"], task.clicks)

    def test_close_on_a_screen_is_not_a_defeat(self):
        screens = ScreenTask([{"wide": ["CLOSE", "自动战斗"]}])
        self.assertFalse(screens.task._defeat_shown())


class AfterDefeatFlowTest(unittest.TestCase):
    def _mode_task(self, before, after, config=None, defeated=True):
        task = make_task(config)
        task._open_mode = lambda mode: "ok"
        task._where_in_event = lambda grace=0: ""  # not already on the page
        reads = iter([before, after])
        task._stable_stage_state = lambda mode: next(reads)
        task._wait_for_stage_page = lambda mode, timeout=25.0: True

        def fight(mode, wanted, read):
            task._defeated = defeated
            task.asked = wanted
            return 1

        task._auto_battle = fight
        return task

    def test_lost_battle_is_reported_with_its_stage(self):
        task = self._mode_task(state(stage=15), state(stage=15))
        self.assertEqual("defeated", task._run_mode(CHALLENGE_MODE))
        self.assertEqual(15, task._lost_stage)
        task.log_warning.assert_called_once()

    def test_a_loss_goes_home_and_tells_the_player_in_the_report(self):
        # Leo 2026-10-14 「挑戰失敗的話就直接回主畫面每日五場就不打了且要在報表跟玩家說明」.
        task = make_task()

        def run_mode(mode):
            if mode == NORMAL_MODE:
                return "cleared"
            task._lost_stage = 15
            return "defeated"

        task._run_mode = run_mode
        task._run_quick_battle = lambda *a: self.fail("fought on after a loss")
        finished = []
        task._finish = lambda message: finished.append(message) or True
        with mock.patch.object(event_module.run_report, "add_current_note") as note:
            self.assertTrue(task.run_claim())
        self.assertEqual(["挑战战斗第15关打输了，今天不再打"], finished)
        text = note.call_args.args[0]
        self.assertIn("挑战战斗第15关打输了", text)
        self.assertIn("挑战战斗最高关卡", text)
        self.assertIn("只刷普通难度", text)

    def test_a_normal_loss_never_opens_challenge(self):
        task = make_task()
        opened = []

        def run_mode(mode):
            opened.append(mode)
            task._lost_stage = 3
            return "defeated"

        task._run_mode = run_mode
        task._finish = lambda message: True
        with mock.patch.object(event_module.run_report, "add_current_note"):
            self.assertTrue(task.run_claim())
        self.assertEqual([NORMAL_MODE], opened)

    def test_the_stage_page_after_a_battle_is_waited_for_at_most_10_s(self):
        # Leo 2026-10-14 「頂多等8秒10秒」.
        task = self._mode_task(state(stage=15), state(stage=15))
        waits = []
        task._wait_for_stage_page = lambda mode, timeout=25.0: waits.append(timeout) or True
        task._run_mode(CHALLENGE_MODE)
        self.assertEqual([10.0], waits)


class ChallengeCapTest(unittest.TestCase):
    def test_cap_limits_the_chain(self):
        task = AfterDefeatFlowTest._mode_task(
            self, state(stage=8), state(stage=10), {CHALLENGE_CAP_KEY: "10"}, defeated=False
        )
        task._stable_stage_state = mock.Mock(
            side_effect=[state(stage=8), state(stage=11), state(stage=11)]
        )
        self.assertEqual("capped", task._run_mode(CHALLENGE_MODE))
        self.assertEqual(3, task.asked)  # stages 8, 9, 10

    def test_a_stage_past_the_cap_is_not_fought(self):
        task = make_task({CHALLENGE_CAP_KEY: "10"})
        task._open_mode = lambda mode: "ok"
        task._where_in_event = lambda grace=0: ""  # not already on the page
        task._stable_stage_state = lambda mode: state(stage=12)
        task._auto_battle = lambda *a: self.fail("fought past the cap")
        self.assertEqual("capped", task._run_mode(CHALLENGE_MODE))

    def test_cap_does_not_touch_normal(self):
        task = make_task({CHALLENGE_CAP_KEY: "5"})
        self.assertEqual(15, task._stage_cap(NORMAL_MODE))
        self.assertEqual(5, task._stage_cap(CHALLENGE_MODE))

    def test_cap_is_one_of_the_quick_battle_stages(self):
        # Leo 2026-10-14 「快速戰鬥只能選 5 10 15」.
        cap = lambda value: make_task({CHALLENGE_CAP_KEY: value})._stage_cap(CHALLENGE_MODE)
        self.assertEqual(10, cap("10"))
        self.assertEqual(10, cap(12))  # an older free number rounds down
        self.assertEqual(5, cap(3))
        self.assertEqual(15, cap(99))
        self.assertEqual(15, cap("x"))

    def test_capped_run_quick_battles_the_cap_stage(self):
        task = make_task({CHALLENGE_CAP_KEY: "10"})
        task._run_mode = lambda mode: "cleared" if mode == NORMAL_MODE else "capped"
        quick = []
        task._run_quick_battle = lambda mode, stage: quick.append((mode, stage)) or "done"
        task._finish = lambda message: True
        self.assertTrue(task.run_claim())
        self.assertEqual([(CHALLENGE_MODE, 10)], quick)

    def test_cleared_stage_at_the_cap_is_capped_not_walked_past(self):
        task = make_task({CHALLENGE_CAP_KEY: "10"})
        task._open_mode = lambda mode: "ok"
        task._where_in_event = lambda grace=0: ""  # not already on the page
        task._stable_stage_state = lambda mode: state(stage=10, auto=False, quick=True)
        task._select_stage = lambda *a: self.fail("selected a stage past the cap")
        self.assertEqual("capped", task._run_mode(CHALLENGE_MODE))


class NormalOnlyTest(unittest.TestCase):
    def test_challenge_is_never_opened_and_normal_15_is_quick_battled(self):
        task = make_task({NORMAL_ONLY_KEY: True})
        opened = []
        task._run_mode = lambda mode: opened.append(mode) or "cleared"
        quick = []
        task._run_quick_battle = lambda mode, stage: quick.append((mode, stage)) or "done"
        task._finish = lambda message: True
        self.assertTrue(task.run_claim())
        self.assertEqual([NORMAL_MODE], opened)
        self.assertEqual([(NORMAL_MODE, 15)], quick)

    def test_default_runs_both_modes(self):
        self.assertEqual((NORMAL_MODE, CHALLENGE_MODE), make_task()._modes())


class QuickBattleStageTest(unittest.TestCase):
    def test_another_selected_stage_is_changed_to_the_target_first(self):
        task = make_task()
        task._open_mode = lambda mode: "ok"
        task._where_in_event = lambda grace=0: ""  # not already on the page
        reads = iter([state(stage=11, auto=True), state(stage=10, auto=False, quick=True)])
        task._stable_stage_state = lambda mode: next(reads)
        selected = []
        task._select_stage = lambda mode, current, target: selected.append(target) or True
        task._open_quick_dialog = lambda: False
        self.assertEqual("failed", task._run_quick_battle(CHALLENGE_MODE, 10))
        self.assertEqual([10], selected)
        self.assertIn("快速战斗", task._why)

    def test_a_stage_that_cannot_be_selected_is_skipped(self):
        task = make_task()
        task._open_mode = lambda mode: "ok"
        task._where_in_event = lambda grace=0: ""  # not already on the page
        task._stable_stage_state = lambda mode: state(stage=11, auto=True)
        task._select_stage = lambda *a: False
        task._open_quick_dialog = lambda: self.fail("opened on the wrong stage")
        self.assertEqual("skipped", task._run_quick_battle(CHALLENGE_MODE, 10))


class QuickStageBackupTest(unittest.TestCase):
    """A player (2026-10-14, version unknown): both modes cleared, no 快速战斗
    pressed.  Inferred: stage 15 was not selected (another stage kept by the
    game, or 15 below the list's visible part)."""

    def _task(self, selectable, start=12):
        task = make_task()
        task.page = state(stage=start, auto=False, quick=False)
        task._stable_stage_state = lambda mode: dict(task.page)
        task.scrolls = 0
        task.tried = []

        def select(mode, current, target, grace=5.0):
            task.tried.append(target)
            if target in selectable(task.scrolls):
                task.page = state(stage=target, auto=False, quick=True)
                return True
            return False

        task._select_stage = select

        def scroll(point, amount, count=1, after_sleep=0):
            task.scrolls += 1

        task.scroll_client = scroll
        return task

    def test_the_list_is_scrolled_to_find_stage_15(self):
        task = self._task(lambda scrolls: {15} if scrolls >= 1 else set())
        picked = task._pick_quick_stage(CHALLENGE_MODE, task.page, 15)
        self.assertEqual(15, picked[1])
        self.assertEqual(1, task.scrolls)

    def test_never_another_stage_when_15_cannot_be_selected(self):
        # Leo 2026-10-14 「不能去改打第10第5」.
        task = self._task(lambda scrolls: {10, 5})
        self.assertIsNone(task._pick_quick_stage(CHALLENGE_MODE, task.page, 15))
        self.assertEqual([15, 15, 15], task.tried)

    def test_a_page_opened_on_another_stage_selects_15(self):
        # Up to v0.1.32 this skipped quick battle (inferred cause).
        task = self._task(lambda scrolls: {15}, start=10)
        task.page = state(stage=10, auto=False, quick=True)
        picked = task._pick_quick_stage(CHALLENGE_MODE, task.page, 15)
        self.assertEqual(15, picked[1])
        self.assertEqual(0, task.scrolls)

    def test_nothing_selectable_is_reported(self):
        task = make_task()
        task._run_mode = lambda mode: "cleared"
        task._run_quick_battle = lambda mode, stage: "skipped"
        task._finish = lambda message: True
        with mock.patch.object(event_module.run_report, "add_current_note") as note:
            self.assertTrue(task.run_claim())
        text = note.call_args.args[0]
        self.assertIn("没选到第15关", text)
        self.assertIn("活动AP没用掉", text)


class NoQuickBeforeTheTargetTest(unittest.TestCase):
    """Leo 2026-10-14: progress at 10, cap 15 -> never quick-battle 10."""

    def test_a_cleared_10_whose_next_stage_cannot_be_selected_is_not_all_cleared(self):
        task = make_task({CHALLENGE_CAP_KEY: "15"})
        task._open_mode = lambda mode: "ok"
        task._where_in_event = lambda grace=0: ""  # not already on the page
        task._stable_stage_state = lambda mode: state(stage=10, auto=False, quick=True)
        task._select_stage = lambda *a, **k: False
        task.scroll_client = lambda *a, **k: None
        self.assertEqual("stuck", task._run_mode(CHALLENGE_MODE))

    def test_stuck_ends_the_run_without_quick_battle_and_says_why(self):
        task = make_task()

        opened = []

        def run_mode(mode):
            opened.append(mode)
            task._stuck_stage = 10
            return "stuck"

        task._run_mode = run_mode
        task._run_quick_battle = lambda *a: self.fail("quick battle before stage 15")
        task._finish = lambda message: True
        with mock.patch.object(event_module.run_report, "add_current_note") as note:
            self.assertTrue(task.run_claim())
        self.assertEqual([NORMAL_MODE, CHALLENGE_MODE], opened)  # challenge still pushed
        self.assertIn("停在第10关", note.call_args.args[0])
        self.assertIn("活动AP留着没用", note.call_args.args[0])

    def test_quick_battle_never_runs_on_a_stage_still_to_clear(self):
        # Stage 15 selected but not cleared shows 自动战斗: not quick-battled.
        task = make_task()
        task._select_stage = lambda *a, **k: True
        task.scroll_client = lambda *a, **k: None
        task._stable_stage_state = lambda mode: state(stage=15, auto=True, quick=False)
        self.assertIsNone(
            task._pick_quick_stage(CHALLENGE_MODE, state(stage=10, auto=False, quick=True), 15)
        )


class ShortWaitsTest(unittest.TestCase):
    """Leo 2026-10-14 「頂多等8秒10秒」: no page or cue is waited for longer."""

    def test_every_page_wait_is_10_s_at_most(self):
        for name in (
            "PAGE_STUCK_SECONDS",
            "START_CONFIRM_SECONDS",
            "QUICK_RESULT_TIMEOUT",
            "AFTER_BATTLE_PAGE_SECONDS",
            "UNKNOWN_END_SECONDS",
            "HUB_RETRY_SECONDS",
            "AP_READ_SECONDS",
        ):
            self.assertLessEqual(getattr(event_module, name), 10.0, name)
        import inspect

        for method in ("_wait_for_hub", "_wait_for_stage_page"):
            timeout = inspect.signature(getattr(EventBattleTask, method)).parameters["timeout"]
            self.assertLessEqual(timeout.default, 10.0, method)

    def test_an_old_long_carousel_setting_is_cut_to_10_s(self):
        now = [0.0]

        def clock():
            now[0] += 1.0
            return now[0]

        task = make_task({"横幅轮播等待秒数": 15.0})
        width = mock.patch.object(
            EventBattleTask, "width", new_callable=mock.PropertyMock, return_value=1920
        )
        width.start()
        self.addCleanup(width.stop)
        task.capture_frame = lambda: None
        task._roi_boxes = lambda *a: []
        task._boxes_text = lambda boxes: ""
        with mock.patch.object(event_module, "monotonic", side_effect=clock):
            self.assertIsNone(task._find_stable_banner(("活动",)))
        self.assertLessEqual(now[0], 13.0)

    def test_the_stuck_message_says_where(self):
        task = make_task()
        task.info["当前阶段"] = "挑战战斗：自动战斗 5 场"
        task._page_stuck = True
        with self.assertRaises(event_module._StuckOnEventPage) as stuck:
            task.capture_frame()
        self.assertIn("挑战战斗：自动战斗 5 场", str(stuck.exception))


class SettingsTest(unittest.TestCase):
    def test_new_settings_have_defaults_and_choices(self):
        task = EventBattleTask(executor=SimpleNamespace(scene=None), app=SimpleNamespace())
        self.assertIs(False, task.default_config[NORMAL_ONLY_KEY])
        self.assertEqual("15", task.default_config[CHALLENGE_CAP_KEY])
        self.assertEqual(["5", "10", "15"], task.config_type[CHALLENGE_CAP_KEY]["options"])

    def test_quick_battle_cannot_be_turned_off(self):
        # Leo 2026-10-14 「全部通關後快速戰鬥這個關掉 不讓用戶取消」.
        task = EventBattleTask(executor=SimpleNamespace(scene=None), app=SimpleNamespace())
        self.assertNotIn("全部通关后快速战斗", task.default_config)

    def test_the_cap_row_hides_while_only_normal_is_fought(self):
        from src.ui.shell import config_form

        task = EventBattleTask(executor=SimpleNamespace(scene=None), app=SimpleNamespace())
        rules = config_form.parents(task)
        task.config = {NORMAL_ONLY_KEY: True, CHALLENGE_CAP_KEY: "10"}
        self.assertFalse(config_form.condition_met(task, CHALLENGE_CAP_KEY, rules))
        task.config = {NORMAL_ONLY_KEY: False, CHALLENGE_CAP_KEY: "10"}
        self.assertTrue(config_form.condition_met(task, CHALLENGE_CAP_KEY, rules))

    def test_normal_only_ignores_a_set_cap(self):
        task = make_task({NORMAL_ONLY_KEY: True, CHALLENGE_CAP_KEY: "10"})
        opened = []
        task._run_mode = lambda mode: opened.append(mode) or "cleared"
        quick = []
        task._run_quick_battle = lambda mode, stage: quick.append((mode, stage)) or "done"
        task._finish = lambda message: True
        self.assertTrue(task.run_claim())
        self.assertEqual([NORMAL_MODE], opened)
        self.assertEqual([(NORMAL_MODE, 15)], quick)


try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships onnxocr
    ONNXPaddleOcr = None

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "event_battle" / (
    "defeat_screen_leo_1440_as_1080.jpg"
)


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class LeoDefeatFrameTest(unittest.TestCase):
    """Leo's defeat screen (2026-10-14): DEFEAT, 返回, 重新挑战 at the bottom."""

    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(FIXTURE))
        cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True, use_npu=False)

    def _task(self):
        task = make_task()
        task.capture_frame = lambda: self.frame

        def roi_boxes(frame, roi, _name):
            x, y, w, h = roi
            boxes = []
            for points, (text, score) in self.engine.ocr(frame[y : y + h, x : x + w])[0] or []:
                if score < 0.2:
                    continue
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                boxes.append(box(text, x + min(xs), y + min(ys), max(xs) - min(xs), max(ys) - min(ys)))
            return boxes

        task._roi_boxes = roi_boxes
        return task

    def test_the_old_result_box_reads_nothing_there(self):
        # The cause: the watch only looked bottom-right for 返回.
        self.assertEqual([], self._task()._roi_boxes(self.frame, RESULT_BUTTONS_ROI, ""))

    def test_defeat_is_recognised(self):
        self.assertTrue(self._task()._defeat_shown(self.frame))

    def test_back_is_chosen_never_retry(self):
        task = self._task()
        leave = task._defeat_leave_box(task._defeat_boxes(self.frame))
        self.assertEqual("返回", leave.name)
        self.assertLess(leave.x, 960)  # the left button, 重新挑战 is right of it


if __name__ == "__main__":
    unittest.main()
