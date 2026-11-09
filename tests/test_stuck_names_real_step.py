"""A stuck run says where it really stopped (Leo 2026-11-09 「報告要寫出真正卡在哪」).

Player v0.3.5 (1920x1080 window, 150%) 2026-11-09: 活动每日战斗 stopped with
「卡在「启动活动每日战斗」：在活动页 10 秒没走到下一步」 and 读到 only the
主页 brightness after the Esc and the trip home.  The step was the task's
start line, and the step's own wait (banner click 6 + 2 + 10 s) was cut off
by the 10 s page guard, so its own reason never showed.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks import BaseBD2Task as base_module
from src.tasks import EventBattleTask as event_module
from src.tasks import problem_report
from src.utils.frozen_screen import FrozenScreen
from tests.test_event_battle_flow import make_task


class StuckNamesTheCheckTest(unittest.TestCase):
    def setUp(self):
        self.task = type("Task", (), {"frozen_retry": False})()
        self.task.name = "测试卡住"
        self.task.info = {"状态": "启动测试卡住。"}
        self.task.info_snapshot = lambda: dict(self.task.info)
        self.task.log_warning = mock.Mock()
        self.task.log_info = mock.Mock()
        self.task.executor = None
        self.kept_before_esc = []
        self.task.tap_escape = lambda after_sleep=0: self.kept_before_esc.append(
            dict((problem_report._current or {}).get("give_up") or {})
        ) or True
        problem_report.begin(self.task)
        self.addCleanup(problem_report._drop)

    def _run_stuck(self):
        def run(_t):
            problem_report.note_read(self.task, "活动页 OCR", "领取 商店 剧情")
            raise FrozenScreen("在活动页 10 秒没走到下一步（点了没反应或认不出画面）")

        frame = SimpleNamespace(shape=(1080, 1920, 3), copy=lambda: "frame")
        with mock.patch("src.tasks.recovery.home_now", return_value=False), \
                mock.patch.object(problem_report, "_last_frame", return_value=frame):
            self.assertFalse(base_module._run_watched(self.task, run, (), {}, watched=True))

    def test_no_step_set_names_the_check_not_the_start_line(self):
        self._run_stuck()
        why = self.task._why
        self.assertTrue(why.startswith("卡在「认活动页」："), why)
        self.assertNotIn("启动测试卡住", why)
        self.assertIn("最后在认「活动页」，读到「领取 商店 剧情」", why)

    def test_the_record_keeps_the_moment_before_esc(self):
        self._run_stuck()
        self.assertEqual(1, len(self.kept_before_esc))
        kept = self.kept_before_esc[0]
        self.assertEqual("认活动页", kept.get("stage"))
        self.assertIn("活动页 OCR", [read["key"] for read in kept.get("reads") or []])

    def test_a_set_step_still_comes_first(self):
        self.task.info["当前阶段"] = "点了活动横幅，等活动页"
        self._run_stuck()
        self.assertTrue(self.task._why.startswith("卡在「点了活动横幅，等活动页」"), self.task._why)


class EventGuardLetsTheStepFinishTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        clock = mock.patch.object(event_module, "monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

        def capture(_task, _name=None):
            self.now += 1.0
            return None

        for target, value in (
            (mock.patch.object(event_module._ClaimTaskBase, "capture_frame", capture), None),
            (mock.patch.object(event_module, "is_loading_dark", return_value=False), None),
            (mock.patch.object(event_module, "sword_icon_points", return_value=[]), None),
            (mock.patch.object(event_module, "recover_to_home", return_value=True), None),
        ):
            target.start()
            self.addCleanup(target.stop)

    def test_hub_never_shows_after_the_banner_gives_the_step_reason(self):
        task = make_task()
        task._roi_boxes = lambda *args, **kwargs: []
        homes = iter([True] + [False] * 10)
        task._wait_for_home_confirmation = lambda *args, **kwargs: next(homes)
        task._find_stable_banner = lambda keywords: SimpleNamespace(name="活动", x=0, y=0, width=2, height=2)
        task._sleep_after_recognition = lambda: None
        task._click_box = lambda *args, **kwargs: task._progressed()
        task._resume_guard()
        task._hub_unsure = False
        result = task._enter_hub()  # before: _StuckOnEventPage at 10 s
        # The step ran its whole wait; home is gone, so the modes are tried
        # anyway (Leo 2026-11-09 「那程式一定得去普通戰鬥或挑戰戰鬥」).
        self.assertEqual("ok", result)
        self.assertTrue(task._hub_unsure)
        self.assertEqual("点了活动横幅，等活动页", task.info["当前阶段"])

    def test_the_guard_still_ends_a_step_with_no_wait_of_its_own(self):
        task = make_task()
        task.name = "活动每日战斗"
        task._resume_guard()
        task._page_wait(15.0)
        self.now += 15.0 + event_module.GUARD_MARGIN_SECONDS - 1.5
        task.capture_frame()
        self.now += event_module.PAGE_STUCK_SECONDS
        with self.assertRaises(event_module._StuckOnEventPage):
            task.capture_frame()


class StagePageWithoutItsNumberTest(unittest.TestCase):
    """Leo 2026-11-09: a stage number the art hides must not keep the run off the page."""

    def test_title_and_auto_button_are_enough(self):
        task = make_task()
        task._resume_guard = lambda: None
        task._page_deadline = None
        task.capture_frame = lambda *a, **k: None
        task._title_visible = lambda frame, words, name: True

        def boxes(frame, roi, name):
            if roi == event_module.AUTO_TOGGLE_ROI:
                return [SimpleNamespace(name="自动战斗", x=0, y=0, width=2, height=2)]
            return []

        task._roi_boxes = boxes
        with mock.patch.object(event_module, "is_loading_dark", return_value=False):
            self.assertTrue(task._wait_for_stage_page("普通战斗", timeout=0.0))

    def test_title_alone_is_not(self):
        task = make_task()
        task._page_deadline = None
        task.capture_frame = lambda *a, **k: None
        task._title_visible = lambda frame, words, name: True
        task._roi_boxes = lambda frame, roi, name: []
        with mock.patch.object(event_module, "is_loading_dark", return_value=False):
            self.assertFalse(task._wait_for_stage_page("普通战斗", timeout=0.0, quiet=True))


class PlayerQuickBattleAfterBothClearedTest(unittest.TestCase):
    """Player v0.3.5 2026-11-09 summary: 普通 and 挑战 read 全部通关 at 08:39:33/39,
    then 10 s on the 挑战 stage page with no press; the trip home (界面分类
    4.98 s) was running when the page guard fired."""

    def test_a_missed_first_look_is_looked_at_again(self):
        task = make_task()
        task._page_deadline = None
        task._wait_for_hub = lambda timeout=0.0: False
        looks = iter([False, False, False, True])  # 普通, 挑战 missed once; then 普通 no, 挑战 yes
        task._wait_for_stage_page = lambda mode, timeout=0.0, quiet=False: next(looks)
        with mock.patch.object(event_module, "monotonic", return_value=0.0):
            self.assertEqual("挑战战斗", task._where_in_event())

    def test_quick_battle_starts_from_the_page_it_is_on(self):
        task = make_task()
        task._page_deadline = None
        task._where_in_event = lambda grace=0: "挑战战斗"
        task._open_mode = lambda mode: self.fail("left the 挑战战斗 page to open it again")
        task._stable_stage_state = lambda mode: {
            "stage": 15, "free_ap": 0, "bonus_ap": 0, "auto": False, "quick": True,
        }
        self.assertEqual("no_ap", task._run_quick_battle("挑战战斗", 15))


class SettingsStillHoldTest(unittest.TestCase):
    """Leo 2026-11-09 「設定頁也有相關設定 不要出錯」: the new tries keep the settings."""

    def _task(self, config, page):
        task = make_task()
        task.config = dict(config)
        task._page_deadline = None
        task._open_mode = lambda mode: "ok"
        task._stable_stage_state = lambda mode: dict(page)
        fought = []
        task._auto_battle = lambda mode, wanted, read: fought.append(wanted) or 0
        return task, fought

    def test_cap_with_an_unread_stage_never_presses(self):
        page = {"stage": None, "free_ap": 5, "bonus_ap": 0, "auto": False, "quick": False}
        task, fought = self._task({event_module.CHALLENGE_CAP_KEY: "10"}, page)
        self.assertEqual("failed", task._run_mode(event_module.CHALLENGE_MODE))
        self.assertEqual([], fought)
        self.assertIn("为了不超过设定没开打", task._why)

    def test_cap_reached_stays_capped(self):
        page = {"stage": 10, "free_ap": 5, "bonus_ap": 0, "auto": False, "quick": True}
        task, fought = self._task({event_module.CHALLENGE_CAP_KEY: "10"}, page)
        self.assertEqual("capped", task._run_mode(event_module.CHALLENGE_MODE))
        self.assertEqual([], fought)

    def test_battle_count_setting_bounds_the_blind_press(self):
        page = {"stage": None, "free_ap": None, "bonus_ap": 0, "auto": False, "quick": False}
        task, fought = self._task({"每次最多战斗场数": 2}, page)
        task._run_mode(event_module.NORMAL_MODE)
        self.assertEqual([2], fought)

    def test_normal_only_never_tries_challenge(self):
        task = make_task()
        task.config = {event_module.NORMAL_ONLY_KEY: True}
        tried = []

        def run_mode(mode):
            tried.append(mode)
            task._mode_unopened = True
            task._why = "没打开"
            return "failed"

        task._run_mode = run_mode
        task._event_fail = lambda stage: False
        self.assertFalse(task._run_claim())
        self.assertEqual([event_module.NORMAL_MODE], tried)


class EveryStuckCatchNamesTheStepTest(unittest.TestCase):
    """Leo 2026-11-09 「同類型不要再出錯」: no place that catches the stuck
    watch may write its own reason without the step (stuck_reason)."""

    def test_every_catch_uses_stuck_reason(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1] / "src"
        missing = []
        for path in root.rglob("*.py"):
            lines = path.read_text(encoding="utf-8").splitlines()
            for at, line in enumerate(lines):
                if not re.search(r"except \(?[\w, ]*FrozenScreen", line):
                    continue
                block = "\n".join(lines[at + 1:at + 12])
                # Re-raised (the loading-word hold) or explained by stuck_reason.
                if "stuck_reason(" in block or re.search(r"^\s*raise\s*$", block, re.M):
                    continue
                missing.append(f"{path.relative_to(root)}:{at + 1}")
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
