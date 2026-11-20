"""塔洛斯战术教材 one-click task: reading the stage list (2K PC pictures, 2026-10-28)."""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2

from src.tasks import TalosTask as talos_module
from src.tasks.talos import stages
from src.tasks.TalosTask import (
    StageSwitch,
    TalosTask,
    list_columns,
    merge_marks,
    tile_marks,
    word_centre,
)
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


# The flow and screen tests are written for a nine-stage period (3x3, records
# from 10-22), whatever period the shipped records are for now.
_NINE = []


def setUpModule():
    from datetime import date as _date

    for patch in (
        mock.patch.object(stages, "STAGE_COUNT", 9),
        mock.patch.object(stages, "missing_records", lambda root=None: []),
        mock.patch.object(stages, "records_made", lambda root=None: _date(2026, 10, 22)),
    ):
        patch.start()
        _NINE.append(patch)


def tearDownModule():
    while _NINE:
        _NINE.pop().stop()


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
                self.assertEqual(expected, tile_marks(frame, 9))
                self.assertEqual(3, list_columns(frame))

    def test_sixteen_stages_on_a_4x4_list(self):
        # 2026-11-19 period: sixteen stages, 1-4 crossed out
        expected = {stage: stage <= 4 for stage in range(1, 17)}
        for size, frame in frames("list_4x4_1080_cleared_1_2_3_4.png"):
            with self.subTest(size=size):
                self.assertEqual(4, list_columns(frame))
                self.assertEqual(expected, tile_marks(frame, 16))

    def test_no_grid_on_a_blank_screen(self):
        self.assertIsNone(list_columns(load_fhd_bgr(FIXTURES / "list_2k_cleared_1_2_3.png") * 0))

    def test_a_gap_is_read_tile_by_tile(self):
        # 2K PC 2026-10-28: 1-4 and 6 crossed, 5 not (counting ✕ would say 6 next)
        expected = {stage: stage in (1, 2, 3, 4, 6) for stage in range(1, 10)}
        for size, frame in frames("list_2k_cleared_1_2_3_4_6.png"):
            with self.subTest(size=size):
                self.assertEqual(expected, tile_marks(frame, 9))

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
                marks = tile_marks(dim, 9)
                self.assertEqual(3, list_columns(dim))
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
            mock.patch.object(TalosTask, "_auto_battle_sure", lambda self, s: shown[-1]),
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


def real_reference_boxes(frame, roi, _label):
    """The task's reading of ``roi`` on a 1920x1080 picture of the 繁中 client:
    real OCR, then the 繁中 word table, in reference coordinates."""
    from src.utils import game_language
    from src.utils.game_text import fix_boxes
    from tests.test_page_lookalikes import navigator_with_real_ocr

    x, y, w, h = roi
    boxes = navigator_with_real_ocr().task.ocr(frame=frame[y : y + h, x : x + w])
    with mock.patch.object(game_language, "client_is_traditional", lambda: True):
        fix_boxes(boxes)
    for box in boxes:
        box.x, box.y = box.x + x, box.y + y
    return boxes


def needs_ocr(test):
    from tests.test_page_lookalikes import ONNXPaddleOcr

    return unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")(test)


class TwFightTest(unittest.TestCase):
    """Leo's 4K 2026-11-19 22:11, 繁中 client: stage 1 was taken for auto
    battle, then 离开's 「確定要停止當前戰鬥嗎？」 was not known, so the run
    went round the 暂停 menu (「一直暫停 然後循環」)."""

    def task_on(self, name):
        task = bare_task()
        frame = load_fhd_bgr(FIXTURES / name)
        task.capture_frame = lambda: frame
        task._reference_boxes = real_reference_boxes
        return task

    @needs_ocr
    def test_the_tw_leave_question_is_known(self):
        self.assertTrue(self.task_on("leave_confirm_tw_4k_720p_as_1080.jpg")._leave_dialog_visible())
        self.assertFalse(self.task_on("pause_menu_tw_4k_as_1080.jpg")._leave_dialog_visible())

    def test_both_clients_leave_questions(self):
        for words in ("是否中断当前进行中的战斗？", "确定要停止当前战斗吗？"):
            with self.subTest(words=words):
                task = bare_task()
                task.capture_frame = lambda: None
                task._reference_boxes = lambda frame, roi, label, words=words: [SimpleNamespace(name=words)]
                self.assertTrue(task._leave_dialog_visible())

    @needs_ocr
    def test_battle_ready_is_not_auto_battle(self):
        task = self.task_on("battle_ready_tw_4k_720p_as_1080.jpg")
        self.assertFalse(task._auto_battle_visible())

    def test_auto_battle_needs_two_looks(self):
        task = bare_task()
        task.capture_frame = lambda: None
        task.sleep = lambda seconds: None
        reads = ["自动战斗中", ""]
        with mock.patch.object(TalosTask, "_auto_battle_read", lambda self, frame: reads.pop(0)):
            self.assertFalse(task._auto_battle_sure(1))
        self.assertIn("再看一次不是", task.lines[-1])
        reads = ["自动战斗中", "结束自动战斗"]
        with (
            mock.patch.object(TalosTask, "_auto_battle_read", lambda self, frame: reads.pop(0)),
            mock.patch.object(TalosTask, "_keep_picture", lambda self, frame, kind: None),
        ):
            self.assertTrue(task._auto_battle_sure(1))
        self.assertIn("自动战斗中", task.lines[-1])  # what was read is in the log

    def test_the_planning_screen_is_never_auto_battle(self):
        task = bare_task()
        task._text_in = lambda frame, roi, name: "自动战斗中"
        with mock.patch.object(talos_module.fight_vision, "planning_visible", lambda frame: True):
            self.assertEqual("", task._auto_battle_read(None))
        with mock.patch.object(talos_module.fight_vision, "planning_visible", lambda frame: False):
            self.assertEqual("自动战斗中自动战斗中", task._auto_battle_read(None))


class BothClientsWordsTest(unittest.TestCase):
    """Leo 2026-11-19 「你繁中簡中都要設計好啊」: every 繁中 word the fight
    shows, as the task reads it (OCR text goes through the 繁中 word table
    first), meets the task's words."""

    SHOWN = {  # 繁中 on screen -> the task's words that must find it
        "塔洛斯戰術教材": talos_module.TITLE_KEYWORDS,
        "戰鬥": talos_module.BATTLE_KEYWORDS,
        "任務": talos_module.MISSION_KEYWORDS,
        "全部領取": talos_module.MISSION_CLAIM.keywords,
        "全部獲得": talos_module.MISSION_CLAIM.keywords,
        "自動戰鬥中": talos_module.AUTO_BATTLE_WORDS,
        "結束自動戰鬥": talos_module.AUTO_BATTLE_STOP_WORDS,
        "暫停": talos_module.PAUSE_KEYWORDS,
        "離開": talos_module.LEAVE_WORDS,
        "確定要停止當前戰鬥嗎？": talos_module.LEAVE_QUESTION_KEYWORDS,
        "確認": talos_module.CONFIRM_WORDS,
    }

    def test_tw_words_after_the_word_table(self):
        from src.utils.game_text import to_tool_text
        from src.utils.ocr_utils import keyword_match_count

        for shown, words in self.SHOWN.items():
            with self.subTest(shown=shown):
                self.assertGreaterEqual(keyword_match_count(to_tool_text(shown, True), words), 1)


class FlowTest(unittest.TestCase):
    """The run with the pages faked: which stages are played, retried, skipped."""

    def run_task(
        self,
        fights,
        marks=None,
        saved=(),
        claimed=True,
        chosen=None,
        resume=None,
        left_pick=None,
        other="",
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
                mock.patch.object(TalosTask, "_other_period", lambda self, progress: other),
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

    def test_another_period_stops_and_says_the_guide_is_not_updated(self):
        # Leo 2026-11-19 「如果週期沒對上 就先跳出 跟用戶說攻略尚未更新」
        fights = {stage: [(True, "")] for stage in range(1, 10)}
        task, result, played, _ = self.run_task(fights, other="游戏这期的关卡是 4x4")
        self.assertTrue(result)  # not a failure of the tool: nothing to play yet
        self.assertEqual([], played)
        self.assertIn("攻略尚未更新", task.info["结果"])
        self.assertIn("home", task.lines)  # back to 主页 for the next task


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


class PeriodLockTest(unittest.TestCase):
    """The list itself tells a new period (no update, no network)."""

    def check(self, name, words, today):
        task = bare_task()
        task.capture_frame = lambda: load_fhd_bgr(FIXTURES / name)
        task._reference_boxes = lambda frame, roi, label: [SimpleNamespace(name=words)]
        progress = stages.Progress("x")
        with mock.patch.object(talos_module, "game_date", lambda: today):
            why = task._other_period(progress)
        return why, progress

    def test_the_records_own_period(self):
        # 2K PC 10-28 with the shipped nine (made 10-22): 21 days left
        why, progress = self.check("list_2k_cleared_1_2_3.png", "活动还剩21天", date(2026, 10, 28))
        self.assertEqual("", why)
        self.assertEqual(date(2026, 11, 18), progress.period_end)  # remembered for next time

    def test_sixteen_stages_with_last_period_records(self):
        why, progress = self.check("list_4x4_1080_cleared_1_2_3_4.png", "活动还剩27天", date(2026, 11, 19))
        self.assertIn("4x4", why)
        self.assertIsNone(progress.period_end)


if __name__ == "__main__":
    unittest.main()


class ReplayChecksTest(unittest.TestCase):
    """Leo 2026-11-20 「有移動的人物再檢查就好」: before BATTLE only the units
    the tool dragged are held again, not every unit left where it stood."""

    def test_replay_holds_only_the_units_it_moved(self):
        calls = []

        class Screen:
            end_word = "victory"

            def __init__(self, *args, **kwargs):
                pass

            def set_auto_skill(self, on):
                return True

        def replay(screen, record, **options):
            calls.append(options)
            return SimpleNamespace(finished=True, turns_played=(1,), seconds=60.0)

        task = bare_task()
        with (
            mock.patch.object(talos_module, "TalosScreen", Screen),
            mock.patch.object(talos_module, "replay_fight", replay),
        ):
            won, why = task._replay(1)
        self.assertTrue(won, why)
        self.assertIs(False, calls[0]["pushes"])
