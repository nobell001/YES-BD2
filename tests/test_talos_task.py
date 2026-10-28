"""塔洛斯战术教材 one-click task: reading the stage list (2K PC pictures, 2026-10-28)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2

from src.tasks import TalosTask as talos_module
from src.tasks.talos import stages
from src.tasks.TalosTask import StageSwitch, TalosTask, merge_marks, tile_marks, word_centre
from tests.helpers.recognition_fixtures import load_fhd_bgr

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "talos"
SIZES = ((1920, 1080), (2560, 1440), (3840, 2160))


def frames(name):
    base = load_fhd_bgr(FIXTURES / name)
    for size in SIZES:
        yield (
            size,
            base if size == SIZES[0] else cv2.resize(base, size, interpolation=cv2.INTER_CUBIC),
        )


class StageListTest(unittest.TestCase):
    def test_each_tile_says_whether_its_stage_is_cleared(self):
        # Leo 「你要看第幾格有叉代表那關打完 不是只看有幾個叉」
        expected = {
            1: True,
            2: True,
            3: True,
            4: False,
            5: False,
            6: False,
            7: False,
            8: False,
            9: False,
        }
        for size, frame in frames("list_2k_cleared_1_2_3.png"):
            with self.subTest(size=size):
                self.assertEqual(expected, tile_marks(frame))

    def test_a_gap_is_read_tile_by_tile(self):
        # 2K PC 2026-10-28: 1-4 and 6 crossed, 5 not (counting ✕ would say 6 next)
        expected = {stage: stage in (1, 2, 3, 4, 6) for stage in range(1, 10)}
        for size, frame in frames("list_2k_cleared_1_2_3_4_6.png"):
            with self.subTest(size=size):
                self.assertEqual(expected, tile_marks(frame))

    def test_a_cross_seen_in_either_read_counts(self):
        # the ✕ of a stage just won fades in: the first read can miss it
        self.assertEqual(
            {4: True, 5: False, 6: True},
            merge_marks({4: False, 5: False, 6: True}, {4: True, 5: False}),
        )

    def test_home_entry_found_inside_a_merged_label(self):
        # 2K clone 2026-10-28: the three top-right labels came as one OCR box;
        # the 战术教材 icon is at x 1562 over the first of them
        from types import SimpleNamespace

        box = SimpleNamespace(name="战术教材通行证快速狩猎", x=1519.0, y=291.0, width=281.0)
        self.assertAlmostEqual(1562, word_centre(box, ("战术教材",)), delta=12)
        self.assertIsNone(word_centre(box, ("亲密度",)))

    def test_a_dimmed_list_is_still_read(self):
        # a screen filter / HDR: the whole picture darker and flatter
        for size, frame in frames("list_2k_cleared_1_2_3.png"):
            with self.subTest(size=size):
                dim = cv2.convertScaleAbs(frame, alpha=0.6, beta=20)
                marks = tile_marks(dim)
                self.assertEqual([1, 2, 3], [stage for stage, cleared in marks.items() if cleared])


def bare_task():
    task = object.__new__(TalosTask)
    task.default_config, task.config_description, task.config_type = {}, {}, {}
    with mock.patch("src.tasks.RewardClaimTasks._ClaimTaskBase.__init__", return_value=None):
        TalosTask.__init__(task)
    task.info, task.lines = {}, []
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    task.log_info = lambda message, notify=False: task.lines.append(message)
    task.log_warning = lambda message, notify=False: task.lines.append(message)
    return task


class AutoBattleTest(unittest.TestCase):
    """4K PC clone 2026-10-28, stage 7: the game's own auto battle was on, so
    战斗 went straight into a fight it played (and lost) by itself."""

    def open_stage(self, auto):
        task = bare_task()
        steps = []
        auto = list(auto)  # per entry: whether the fight came up as auto battle
        shown = []

        def enter(self, stage):
            steps.append("enter")
            shown.append(auto.pop(0))
            return True

        with (
            mock.patch.object(TalosTask, "_enter_stage", enter),
            mock.patch.object(TalosTask, "_auto_battle_visible", lambda self: shown[-1]),
            mock.patch.object(TalosTask, "_stop_auto_battle", lambda self, s: steps.append("stop")),
            mock.patch.object(TalosTask, "_leave_fight", lambda self, why: steps.append("leave")),
            mock.patch.object(TalosTask, "_to_list", lambda self: steps.append("list") or True),
            mock.patch.object(TalosTask, "_note_why", lambda self, why: steps.append(why)),
        ):
            return task._open_stage(7), steps

    def test_planning_screen_is_the_fight(self):
        self.assertEqual((True, ["enter"]), self.open_stage([False]))

    def test_auto_battle_is_ended_left_and_the_stage_opened_again(self):
        opened, steps = self.open_stage([True, False])
        self.assertTrue(opened)
        self.assertEqual(["enter", "stop", "leave", "list", "enter"], steps)

    def test_auto_battle_that_comes_back_stops_the_stage_with_why(self):
        opened, steps = self.open_stage([True, True])
        self.assertFalse(opened)
        self.assertEqual(["enter", "stop", "leave", "list", "enter", "stop", "leave"], steps[:-1])
        self.assertIn("自动战斗", steps[-1])


class FlowTest(unittest.TestCase):
    """The run with the pages faked: which stages are played, retried, skipped."""

    def run_task(
        self, fights, marks=None, saved=(), claimed=True, chosen=None, resume=None, left_pick=None
    ):
        """``fights``: stage -> list of (won, why) for each try."""
        task = bare_task()
        task.chosen_stages = chosen
        task._resume_pick = resume
        if left_pick is not None:
            task.stage_picker.pick(left_pick)
        played = []

        def fight(stage):
            played.append(stage)
            return fights[stage].pop(0)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / stages.PROGRESS_FILE
            stages.Progress(stages.edition(), set(saved)).save(path)
            with (
                mock.patch.object(talos_module.accounts, "path", lambda name: path),
                mock.patch.object(TalosTask, "_open_page_from_home", lambda *a: True),
                mock.patch.object(TalosTask, "_read_marks", lambda self: dict(marks or {})),
                mock.patch.object(TalosTask, "_to_list", lambda self: True),
                mock.patch.object(TalosTask, "_open_stage", lambda self, stage: True),
                mock.patch.object(TalosTask, "_fight", lambda self, stage: fight(stage)),
                mock.patch.object(TalosTask, "_back_to_list", lambda self: True),
                mock.patch.object(
                    TalosTask, "_leave_fight", lambda self, why: task.lines.append(f"leave {why}")
                ),
                mock.patch.object(TalosTask, "_claim_missions", lambda self: claimed),
                mock.patch.object(
                    TalosTask, "_leave_to_home", lambda self, *a: task.lines.append("home")
                ),
            ):
                result = task.run_claim()
            kept = stages.Progress.load(path, stages.edition()).cleared
        return task, result, played, kept

    def test_plays_the_uncleared_stages_in_order_and_remembers_them(self):
        fights = {stage: [(True, "")] for stage in range(1, 10)}
        task, result, played, kept = self.run_task(fights, marks={1: True, 2: True, 3: False})
        self.assertTrue(result)
        self.assertEqual([3, 4, 5, 6, 7, 8, 9], played)
        self.assertEqual(set(range(1, 10)), kept)
        self.assertIn("已通关 9/9", task.info["结果"])

    def test_only_the_ticked_stages_even_a_cleared_one(self):
        # Leo 「要可以選擇關卡 預設全選排除打過的」: a cleared one ticked is replayed
        fights = {stage: [(True, "")] for stage in range(1, 10)}
        task, _, played, _ = self.run_task(fights, saved={1, 2}, chosen=[7, 2, 5])
        self.assertEqual([2, 5, 7], played)
        self.assertIsNone(task.chosen_stages)  # taken once: the next run is the usual one

    def test_the_list_wins_over_the_file_where_it_was_read(self):
        fights = {stage: [(True, "")] for stage in range(1, 10)}
        # the file says 1-4; the list shows 4 not crossed (read) and 5 unsure
        _, _, played, _ = self.run_task(
            fights, marks={1: True, 2: True, 3: True, 4: False}, saved={1, 2, 3, 4}
        )
        self.assertEqual([4, 5, 6, 7, 8, 9], played)

    def test_a_stopped_stage_is_left_tried_again_then_skipped(self):
        # Leo 「出錯的話最少你要把那關停掉 然後去打下一關」
        fights = {stage: [(True, "")] for stage in range(1, 10)}
        fights[5] = [(False, "第 3 回合：读不到回合数"), (False, "第 3 回合：读不到回合数")]
        task, result, played, kept = self.run_task(fights)
        self.assertFalse(result)
        self.assertEqual([1, 2, 3, 4, 5, 5, 6, 7, 8, 9], played)
        self.assertEqual(set(range(1, 10)) - {5}, kept)
        self.assertEqual(2, sum(line.startswith("leave") for line in task.lines))
        self.assertIn("第 5 关没打下来（第 3 回合：读不到回合数）", task.info["结果"])

    def test_a_second_try_that_wins_counts(self):
        fights = {stage: [(True, "")] for stage in range(1, 10)}
        fights[2] = [(False, "打输了"), (True, "")]
        _, result, played, kept = self.run_task(fights)
        self.assertTrue(result)
        self.assertEqual(set(range(1, 10)), kept)

    def test_another_stage_picked_while_paused(self):
        # Leo: 換了關再按繼續 → 先退出現在這場，打選的那關，再照順序往後打沒打過的
        fights = {stage: [(True, "")] for stage in range(1, 10)}

        class SwitchOnce(list):
            def pop(self, index=-1):
                if not getattr(self, "done", False):
                    self.done = True
                    raise StageSwitch(7)
                return super().pop(index)

        fights[3] = SwitchOnce([(True, "")])
        task, _, played, kept = self.run_task(fights)
        self.assertEqual([1, 2, 3, 7, 8, 9, 3, 4, 5, 6], played)
        self.assertEqual(set(range(1, 10)), kept)
        self.assertIn("leave 改打第 7 关", task.lines)

    def test_a_stage_picked_before_the_player_used_the_game_comes_first(self):
        # the run starts again from 主页 after 继续; the pick is not lost
        fights = {stage: [(True, "")] for stage in range(1, 10)}
        _, _, played, _ = self.run_task(fights, saved={1, 2}, resume=7)
        self.assertEqual([7, 8, 9, 3, 4, 5, 6], played)

    def test_a_pick_left_by_a_stopped_run_is_forgotten(self):
        fights = {stage: [(True, "")] for stage in range(1, 10)}
        _, _, played, _ = self.run_task(fights, saved={1, 2}, left_pick=7)
        self.assertEqual([3, 4, 5, 6, 7, 8, 9], played)

    def test_nothing_left_still_claims_and_reports(self):
        task, result, played, _ = self.run_task({}, marks={s: True for s in range(1, 10)})
        self.assertTrue(result)
        self.assertEqual([], played)
        self.assertIn("任务奖励已全部领取", task.info["结果"])
        self.assertIn("home", task.lines)  # ends on 主页, for the next task


class StepInTest(unittest.TestCase):
    """Leo's 4K 2026-10-28 16:02: paused mid-fight, the way home after 继续
    pressed the empty back corner, H and Esc, which do nothing in a fight
    (「他也沒有第一時間點esc或這右上角的暫停圖示」)."""

    def leave(self, fighting, home=False, pause=False, picked=None):
        task = bare_task()
        task._fighting = fighting
        task.stage_picker.current = fighting or 1
        if picked is not None:
            task.stage_picker.pick(picked)
        left = []
        with (
            mock.patch("src.tasks.recovery.home_now", return_value=home),
            mock.patch.object(TalosTask, "_pause_visible", lambda self: pause),
            mock.patch.object(TalosTask, "_leave_fight", lambda self, why: left.append(why)),
        ):
            task.leave_after_step_in()
        return task, left

    def test_a_fight_is_left_by_its_own_pause_menu(self):
        _, left = self.leave(5)
        self.assertEqual(["暂停时你动了游戏"], left)

    def test_the_game_pause_menu_open_is_left_too(self):
        _, left = self.leave(None, pause=True)
        self.assertEqual(["暂停时你动了游戏"], left)

    def test_the_player_went_home_nothing_to_leave(self):
        task, left = self.leave(5, home=True)
        self.assertEqual([], left)
        self.assertIsNone(task._fighting)

    def test_off_a_fight_nothing_is_pressed(self):
        _, left = self.leave(None)
        self.assertEqual([], left)

    def test_the_stage_picked_is_kept_for_the_run_again(self):
        task, _ = self.leave(5, picked=8)
        self.assertEqual(8, task._resume_pick)
        self.assertIsNone(task.stage_picker.chosen)  # no switch out of the new run's first stage

    def test_the_ticked_stages_not_won_yet_are_played_again(self):
        task = bare_task()
        task._plan, task._results = [2, 5, 7], {2: "won", 5: "打输了"}
        task._fighting = 5
        with (
            mock.patch("src.tasks.recovery.home_now", return_value=False),
            mock.patch.object(TalosTask, "_leave_fight", lambda self, why: None),
        ):
            task.leave_after_step_in()
        self.assertEqual([5, 7], task.chosen_stages)

    def test_all_ticked_won_plays_none_again(self):
        fights = {stage: [(True, "")] for stage in range(1, 10)}
        _, _, played, _ = FlowTest().run_task(fights, chosen=[])
        self.assertEqual([], played)

    def test_leaving_from_the_list_presses_nothing(self):
        task = bare_task()
        task._fighting = 4
        presses = mock.Mock()
        with (
            mock.patch.object(TalosTask, "capture_frame", lambda self: "list", create=True),
            mock.patch.object(TalosTask, "_list_visible", lambda self, frame=None: True),
            mock.patch.object(TalosTask, "_press_back_on_result", presses),
            mock.patch.object(TalosTask, "_leave_by_pause", presses),
            mock.patch.object(TalosTask, "tap_escape", presses, create=True),
        ):
            task._leave_fight("改打第 7 关")
        presses.assert_not_called()
        self.assertIsNone(task._fighting)


class ScreenSwitchTest(unittest.TestCase):
    """A stage picked while paused takes over before the next move or BATTLE
    (Leo paused while the cells were being placed), never mid-drag."""

    def screen(self):
        from src.tasks.TalosTask import TalosScreen

        task = bare_task()
        task.stage_picker.current = 3
        task.stage_picker.pick(7)
        screen = object.__new__(TalosScreen)
        screen.task, screen.stage = task, 3
        return screen

    def test_each_move_and_battle_looks_first(self):
        from src.tasks.fiend_hunt.screen import GameFightScreen

        moves = (("drag", (object(),)), ("pick_skill", (0, "技能")), ("press_battle", ()))
        for name, args in moves:
            with self.subTest(name), mock.patch.object(GameFightScreen, name) as move:
                with self.assertRaises(StageSwitch) as switch:
                    getattr(self.screen(), name)(*args)
                self.assertEqual(7, switch.exception.stage)
                move.assert_not_called()

    def test_no_pick_the_move_goes_on(self):
        from src.tasks.fiend_hunt.screen import GameFightScreen

        screen = self.screen()
        screen.task.stage_picker.chosen = None
        with mock.patch.object(GameFightScreen, "press_battle") as press:
            screen.press_battle()
        press.assert_called_once()


if __name__ == "__main__":
    unittest.main()
