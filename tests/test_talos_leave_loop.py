"""YES-BD2 #90 (player 2560x1440, 简中, 2026-11-20 11:07-11:18): 塔洛斯
stage 5 stopped while a card's skill was being chosen; ‖ top right showed no
暂停 menu on its one press, one Esc did nothing, and the way home went round
for eleven minutes: the blind house press (‖ sits there) opened 暂停, its
「点击继续」 was closed as a popup, back / H / Esc did nothing, again; then
stages 6-10 each started with the same way home until the player stopped it.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import TalosTask as talos_module
from src.tasks import recovery
from src.tasks.map_trade.models import ScreenState
from src.tasks.TalosTask import NO_LIST, PAUSE_POINT, PAUSE_PRESSES, TalosTask
from tests.helpers.recognition_fixtures import load_fhd_bgr
from src.tasks.talos import stages
from tests.test_talos_task import bare_task, needs_ocr, real_reference_boxes
from tests.test_talos_task import setUpModule, tearDownModule  # noqa: F401  nine stages


def run_task_with(play):
    """The run with every page faked and ``play(task, stage)`` for each stage."""
    import tempfile

    task = bare_task()
    played = []

    def play_stage(self, stage):
        played.append(stage)
        return play(self, stage)

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / stages.PROGRESS_FILE
        stages.Progress(stages.edition(), set()).save(path)
        with (
            mock.patch.object(talos_module.accounts, "path", lambda name: path),
            mock.patch.object(TalosTask, "_open_page_from_home", lambda *a: True),
            mock.patch.object(TalosTask, "_read_marks", lambda self: {}),
            mock.patch.object(TalosTask, "_other_period", lambda self, progress: ""),
            mock.patch.object(TalosTask, "_play_stage", play_stage),
            mock.patch.object(TalosTask, "_claim_missions", lambda self: self.fail_claim()),
            mock.patch.object(TalosTask, "_leave_to_home", lambda self, *a: task.lines.append("home")),
        ):
            task.fail_claim = lambda: (_ for _ in ()).throw(AssertionError("no claim after a lost list"))
            result = task.run_claim()
        kept = stages.Progress.load(path, stages.edition()).cleared
    return task, result, played, kept

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "talos"


class PausePressedAgainTest(unittest.TestCase):
    def leave(self, menu_after: int | None):
        """‖ shows the 暂停 menu on press ``menu_after`` (None: never)."""
        task = bare_task()
        presses = []
        state = {"pause": False, "question": False, "list": False}

        def click(x, y, after_sleep=0.0):
            presses.append((x, y))
            if (x, y) == PAUSE_POINT and menu_after is not None and len(presses) >= menu_after:
                state["pause"] = True

        def press_text(label, roi, words, point):
            presses.append(label)
            if label == "离开":
                state["pause"], state["question"] = False, True
            elif label == "确认":
                state["question"], state["list"] = False, True

        task.capture_frame = lambda: None
        task._click_reference = click
        task._press_text = press_text
        task._pause_visible = lambda frame=None: state["pause"]
        task._leave_dialog_visible = lambda frame=None: state["question"]
        task._list_visible = lambda frame=None: state["list"]
        task._wait_for = lambda check, timeout, interval=0.5: bool(check())
        return task, task._leave_by_pause(), presses

    def test_pause_not_taken_at_once_is_pressed_again(self):
        # before: one ‖, no menu → 「按了右上角暂停，没出现暂停画面」, gave up
        task, left, presses = self.leave(menu_after=2)
        self.assertTrue(left)
        self.assertEqual([PAUSE_POINT, PAUSE_POINT, "离开", "确认"], presses)
        self.assertIn(f"{talos_module.LABEL}：按了右上角暂停，没出现暂停画面（第 1 次）", task.lines)

    def test_pause_presses_are_capped(self):
        _, left, presses = self.leave(menu_after=None)
        self.assertFalse(left)
        self.assertEqual([PAUSE_POINT] * PAUSE_PRESSES, presses)

    def test_a_question_already_up_is_answered(self):
        task, _, _ = self.leave(menu_after=1)
        state_question = {"q": True}
        task._leave_dialog_visible = lambda frame=None: state_question["q"]
        pressed = []

        def press_text(label, *a):
            pressed.append(label)
            state_question["q"] = False
            task._list_visible = lambda frame=None: True

        task._press_text = press_text
        self.assertTrue(task._leave_by_pause())
        self.assertEqual(["确认"], pressed)


class OwnFightSeenTest(unittest.TestCase):
    """recovery asks the task first: 塔洛斯 knows its fight screens."""

    def task_on(self, name):
        task = bare_task()
        frame = load_fhd_bgr(FIXTURES / name)
        task.capture_frame = lambda: frame
        task._reference_boxes = real_reference_boxes
        task._leave_by_pause = lambda: True
        return task

    @needs_ocr
    def test_the_pause_menu_is_a_fight_both_clients(self):
        for name in ("pause_menu_leo_4k_as_1080.jpg", "pause_menu_tw_4k_as_1080.jpg"):
            with self.subTest(name=name):
                self.assertEqual("left", self.task_on(name).leave_own_fight())

    @needs_ocr
    def test_the_leave_question_is_a_fight(self):
        self.assertEqual("left", self.task_on("leave_confirm_tw_4k_720p_as_1080.jpg").leave_own_fight())

    def test_the_planning_screen_is_a_fight(self):
        task = bare_task()
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), np.uint8)
        task._pause_visible = lambda frame=None: False
        task._leave_dialog_visible = lambda frame=None: False
        task._leave_by_pause = lambda: False
        with mock.patch.object(talos_module.fight_vision, "planning_visible", lambda frame: True):
            self.assertEqual("stuck", task.leave_own_fight())

    @needs_ocr
    def test_the_stage_list_is_no_fight(self):
        task = self.task_on("list_2k_cleared_1_2_3.png")
        task._leave_by_pause = lambda: self.fail("nothing to leave on the list")
        self.assertEqual("none", task.leave_own_fight())


class RecoveryLeavesTheFightFirstTest(unittest.TestCase):
    def recover(self, answers):
        """``answers``: what leave_own_fight says, one per look; home comes
        with the back press after a "left"."""
        page = np.full((1080, 1920, 3), 60, np.uint8)
        home = np.full((1080, 1920, 3), 200, np.uint8)
        state = {"frame": page, "left": False}
        pressed = []

        class FakeNavigator:
            def __init__(self, task, _vision):
                self.vision = SimpleNamespace(capture=lambda: state["frame"])

            def _home_confirmation_signals(self, frame):
                return (frame is home, 0, 0.0, "")

            def classify(self, _frame=None):
                return ScreenState.HOME if state["frame"] is home else ScreenState.UNKNOWN

            def clear_home_announcement(self, _frame, clicks_so_far=0):
                return False

        looks = iter(answers)

        def leave_own_fight():
            answer = next(looks, "none")
            state["left"] = state["left"] or answer == "left"
            return answer

        def operate_click(*a, **_k):
            pressed.append(("click", a))
            if state["left"]:
                state["frame"] = home

        def dialog(*_a):
            pressed.append("dialog")  # the 暂停 menu's 点击继续 would be pressed here
            return "none"

        task = SimpleNamespace(
            info_set=lambda *a: None,
            log_info=lambda *a, **k: None,
            log_warning=lambda *a, **k: None,
            sleep=lambda *_a: None,
            operate_click=operate_click,
            tap_key=lambda key, after_sleep=0.0: pressed.append(("key", key)) or False,
            tap_escape=lambda after_sleep=0.0: pressed.append("esc") or False,
            leave_own_fight=leave_own_fight,
        )
        with (
            mock.patch.object(recovery, "Navigator", FakeNavigator),
            mock.patch.object(recovery, "Vision", lambda task: SimpleNamespace(ocr_boxes=lambda *a, **k: [])),
            mock.patch.object(recovery, "_handle_dialog", dialog),
            mock.patch.object(recovery, "_keep_failure_picture", lambda *_a: None),
            mock.patch.object(recovery, "_press_top_right_home", lambda *a, **k: pressed.append("house")),
            mock.patch.object(recovery, "channel_button_at_back", lambda *_a: False),
            mock.patch.object(recovery, "monotonic", iter(range(0, 100000)).__next__),
        ):
            reached = recovery.recover_to_home(task)
        return task, reached, pressed

    def test_out_of_the_fight_before_any_other_press(self):
        _, reached, pressed = self.recover(["left"])
        self.assertTrue(reached)
        self.assertNotIn("house", pressed[:1])
        self.assertEqual("dialog", pressed[0])  # only after the fight was left

    def test_a_fight_it_cannot_leave_stops_at_once(self):
        # before: house (‖) → 点击继续 → back → H → Esc, ten tries, every stage
        task, reached, pressed = self.recover(["stuck"])
        self.assertFalse(reached)
        self.assertEqual([], pressed)
        self.assertIn("退不出这场战斗", task._recovery_why)

    def test_other_tasks_recover_as_before(self):
        task = SimpleNamespace()
        self.assertEqual("none", recovery._leave_task_fight(task))


class LostListStopsTheRunTest(unittest.TestCase):
    def test_later_stages_are_not_tried_one_by_one(self):
        # before: stages 6-10 each spent ~2 minutes on the same way home
        def play(task, stage):
            if stage == 5:
                task._results[stage] = NO_LIST
                return False
            task._results[stage] = "won"
            return True

        task, result, played, _ = run_task_with(play)
        self.assertFalse(result)
        self.assertEqual([1, 2, 3, 4, 5], played)
        self.assertIn("第 9 关没打下来（前面回不到关卡列表，没打）", task.info["结果"])
        self.assertIn("任务奖励没领到", task.info["结果"])
        self.assertTrue(any("后面的第 [6, 7, 8, 9] 关这次先不打" in line for line in task.lines))


if __name__ == "__main__":
    unittest.main()
