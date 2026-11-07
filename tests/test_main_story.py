"""推主线 (Leo 2026-11-06): which screen is which, and what each gets.

Pictures are parts of Leo's 4K recording (2560x1440 game, 繁中), scaled to
1080p and pasted back where they were on a black frame."""

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks import MainStoryTask as story
from src.tasks.main_story import borrow, screen
from src.tasks.main_story.screen import Kind

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "main_story"


def frame_with(name: str, at: tuple[int, int]) -> np.ndarray:
    frame = np.zeros((1080, 1920, 3), np.uint8)
    part = cv2.imread(str(FIXTURES / name))
    x, y = at
    frame[y : y + part.shape[0], x : x + part.shape[1]] = part
    return frame


def box(name, x, y, w=80, h=30):
    return SimpleNamespace(name=name, x=x, y=y, width=w, height=h)


BLACK = np.zeros((1080, 1920, 3), np.uint8)


class PicturesTest(unittest.TestCase):
    def test_story_row_is_skip(self):
        reading = screen.read_pictures(frame_with("story_row_043.jpg", (1450, 0)))
        self.assertEqual(Kind.SKIP, reading.kind)
        x, y = reading.point
        self.assertLess(abs(x - 1640), 15)  # the skip icon, over its F2 cap

    def test_skip_dialog_tall_and_short(self):
        for name, confirm_y in (("skip_dialog_tall_046.jpg", 780), ("skip_dialog_short_262.jpg", 628)):
            reading = screen.read_pictures(frame_with(name, (700, 560)))
            self.assertEqual(Kind.SKIP_DIALOG, reading.kind, name)
            self.assertLess(abs(reading.point[1] - confirm_y), 15, name)
            self.assertLess(abs(reading.point[0] - 1045), 15, name)

    def test_battle_pill_but_not_the_result_pill(self):
        self.assertEqual(Kind.BATTLE, screen.read_pictures(frame_with("battle_pill_268.jpg", (1550, 930))).kind)
        self.assertIsNone(screen.read_pictures(frame_with("result_pill_289.jpg", (1550, 930))))

    def test_field_tells_nothing_by_pictures_alone(self):
        self.assertIsNone(screen.read_pictures(frame_with("field_top_020.jpg", (1450, 0))))
        self.assertIsNone(screen.read_pictures(BLACK))

    def test_quick_pill_picture_when_its_text_is_not_read(self):
        frame = frame_with("field_quest_007.jpg", (1500, 110))
        reading = screen.read(frame, [])
        self.assertEqual(Kind.QUICK, reading.kind)
        x, y = reading.point
        self.assertLess(abs(y - 208), 15)


class QuestEPictureTest(unittest.TestCase):
    def test_e_cap_alone_is_the_guide(self):
        frame = BLACK.copy()
        frame[100:200, 1500:1900] = (120, 80, 140)
        cap = cv2.imread(str(screen.DATA / "quest_e.png"))
        frame[154:176, 1553:1573] = cap
        reading = screen.read(frame, [])
        self.assertEqual(Kind.GUIDE, reading.kind)
        x, y = reading.point
        self.assertLess(abs(x - 1633), 15)  # the quest line's text, right of the cap
        self.assertLess(abs(y - 165), 15)

    def test_no_cap_is_not_the_guide(self):
        self.assertEqual(Kind.OTHER, screen.read(BLACK, []).kind)

    def test_ocr_alone_still_is_the_guide(self):
        reading = screen.read(BLACK, [box("主線", 1640, 130)])
        self.assertEqual(Kind.GUIDE, reading.kind)
        self.assertEqual(screen.QUEST_LINE_POINT, reading.point)

    def test_e_then_e_then_the_quest_line(self):
        self.assertEqual((("e",), ("e",), ("click",)), story.LADDERS[Kind.GUIDE])


class PromptTest(unittest.TestCase):
    def test_both_samples_by_picture_come_before_quick(self):
        for name, gold in (("prompt_live.jpg", (1008, 402)), ("prompt2_live.jpg", (942, 346))):
            reading = screen.read(live(name), [box("快速進行任務", 1650, 195)])
            self.assertEqual(Kind.PROMPT, reading.kind, name)
            self.assertEqual(Kind.PROMPT, reading.kind, name)

    def test_any_npc_name_prompt_is_no_prompt(self):
        boxes = [box("F", 1030, 340, 18, 24), box("华特波尔长老", 1120, 335, 170, 28)]
        self.assertNotEqual(Kind.PROMPT, screen.read(live("npc_prompt_cn_live.jpg"), boxes).kind)

    def test_read_f_with_gold_beside_it(self):
        frame = live("prompt_live.jpg")
        frame[380:425, 990:1030] = frame[380:425, 990:1030]
        boxes = [box("F", 945, 390, 18, 24), box("聆聽口信", 1035, 388, 110, 28)]
        self.assertEqual("F 和金色图标", screen.prompt_point(frame, boxes)[1])

    def test_key_cap_with_another_gold_icon(self):
        # 第15章 「接受血刻印」: a gold box with a tick, not the diamond.
        frame = live("prompt3_cn_live.jpg")
        frame[855:915, 1385:1440] = 40  # no ❗ on the F button: the pill alone
        reading = screen.read(frame, [box("进行快速探索", 1650, 195)])
        self.assertEqual(Kind.PROMPT, reading.kind)
        self.assertLess(abs(reading.point[1] - 354), 15)

    def test_teleport_glow_behind_an_npc_name_is_no_prompt(self):
        frame = live("npc_prompt_glow_live.jpg")
        boxes = [box("F", 924, 326, 18, 24), box("好奇青年", 975, 324, 100, 28)]
        self.assertIsNone(screen.prompt_point(frame, boxes))

    def test_bang_on_the_f_button_alone(self):
        boxes = [box("进行快速探索", 1650, 195)]
        reading = screen.read(live("f_button_bang_live.jpg"), boxes)
        self.assertEqual(Kind.PROMPT, reading.kind)
        self.assertEqual(screen.F_BUTTON_POINT, reading.point)

    def test_speech_icon_on_the_f_button_is_no_prompt(self):
        self.assertIsNone(screen.prompt_point(live("npc_prompt_cn_live.jpg"), []))

    def test_no_action_word_is_stored(self):
        source = Path(screen.__file__).read_text(encoding="utf-8")
        code = [line for line in source.splitlines() if not line.lstrip().startswith("#")]
        self.assertNotIn("審問", "".join(code))

    def test_the_banner_alone_is_no_prompt(self):
        self.assertNotEqual(Kind.PROMPT, screen.read(BLACK, [box("已完成自動移動。", 870, 230)]).kind)

    def test_hud_f_button_is_no_prompt(self):
        boxes = [box("F", 1400, 930, 18, 24), box("SPACE", 1660, 960)]
        self.assertNotEqual(Kind.PROMPT, screen.read(BLACK, boxes).kind)

    def test_f_alone_or_far_text_is_no_prompt(self):
        self.assertNotEqual(Kind.PROMPT, screen.read(BLACK, [box("F", 945, 390, 18, 24)]).kind)
        far = [box("F", 945, 390, 18, 24), box("聆聽口信", 1200, 388, 110, 28)]
        self.assertNotEqual(Kind.PROMPT, screen.read(BLACK, far).kind)

    def test_ladders(self):
        self.assertEqual((("f",), ("f",), ("click",)), story.LADDERS[Kind.PROMPT])
        self.assertEqual((("click",), ("click",)), story.LADDERS[Kind.QUICK])


def live(name: str) -> np.ndarray:
    return cv2.imread(str(FIXTURES / name))


class DifficultySwitchTest(unittest.TestCase):
    """Real frames: 困難 cleared, the 冒險指南 book, then the shelf."""

    def test_book_by_its_button_picture_alone(self):
        reading = screen.read(live("book_live.jpg"), [])
        self.assertEqual(Kind.BOOK, reading.kind)
        self.assertLess(abs(reading.point[0] - 1650), 20)

    def test_book_by_text_alone(self):
        self.assertEqual(Kind.BOOK, screen.read(BLACK, [box("冒險指南", 960, 180)]).kind)
        go = box("前往遊戲卡帶收藏集", 1540, 975, 260, 30)
        self.assertEqual(Kind.BOOK, screen.read(BLACK, [go]).kind)

    def test_space_or_enter_is_no_field_on_the_book(self):
        boxes = [box("冒險指南", 960, 180), box("SPACE OR ENTER", 1600, 1030)]
        self.assertEqual(Kind.BOOK, screen.read(live("book_live.jpg"), boxes).kind)

    def test_book_all_done_only_with_three_done_and_nothing_next(self):
        done = [box("普通", 900, 410), box("完成", 900, 440), box("困難", 900, 500), box("完成", 900, 530)]
        frame = live("book_live.jpg")
        next_up = screen.read(frame, [*done, box("超困難", 900, 590), box("可進行", 900, 620)])
        self.assertNotEqual(screen.ALL_DONE, next_up.why)
        finished = screen.read(frame, [*done, box("超困難", 900, 590), box("完成", 900, 620)])
        self.assertEqual(screen.ALL_DONE, finished.why)

    def test_book_short_of_three_goes_on(self):
        self.assertNotEqual(screen.ALL_DONE, screen.read(live("book_live.jpg"), [box("完成", 900, 440)]).why)

    def test_shelf_presses_the_playing_cartridge_by_picture(self):
        reading = screen.read(live("shelf_live.jpg"), [])
        self.assertEqual(Kind.SHELF, reading.kind)
        x, y = reading.point
        self.assertLess(abs(x - 828), 30)
        self.assertLess(abs(y - 270), 30)

    def test_shelf_gold_bar_alone_finds_the_cartridge(self):
        frame = live("shelf_live.jpg")
        frame[270:320, 780:880] = 60  # the 遊戲中 label gone
        x, y = screen.playing_point(frame, [])
        self.assertLess(abs(x - 828), 15)
        self.assertLess(abs(y - 270), 15)

    def test_shelf_title_as_read_live(self):
        self.assertEqual(Kind.SHELF, screen.read(BLACK, [box("遊戲卡带收藏集？", 240, 35, 210, 30)]).kind)

    def test_shelf_by_text_with_the_playing_label_read(self):
        boxes = [box("遊戲卡帶收藏集", 240, 35, 210, 30), box("遊戲中", 800, 285, 60, 28)]
        reading = screen.read(BLACK, boxes)
        self.assertEqual(Kind.SHELF, reading.kind)
        self.assertLess(abs(reading.point[0] - 828), 30)

    def test_shelf_without_the_playing_label_has_no_point(self):
        reading = screen.read(BLACK, [box("遊戲卡帶收藏集", 240, 35, 210, 30)])
        self.assertEqual(Kind.SHELF, reading.kind)
        self.assertIsNone(reading.point)

    def test_ladders_have_a_second_way(self):
        self.assertEqual(3, len(story.LADDERS[Kind.BOOK]))
        self.assertEqual(("click",), story.LADDERS[Kind.SHELF][0])


class DialogTest(unittest.TestCase):
    def test_story_line_without_the_f2_row(self):
        self.assertEqual(Kind.DIALOG, screen.read_pictures(live("dialog_live.jpg")).kind)

    def test_f2_row_still_comes_first(self):
        frame = live("dialog_live.jpg")
        row = frame_with("story_row_043.jpg", (1450, 0))
        frame[0:170, 1450:1900] = row[0:170, 1450:1900]
        self.assertEqual(Kind.SKIP, screen.read_pictures(frame).kind)

    def test_cream_bubble_by_its_chevron(self):
        reading = screen.read_pictures(live("bubble_live.jpg"))
        self.assertEqual(Kind.DIALOG, reading.kind)
        self.assertLess(abs(reading.point[0] - 1291), 15)
        self.assertLess(abs(reading.point[1] - 447), 15)

    def test_band_by_text_alone(self):
        frame = live("dialog_live.jpg")
        frame[985:1020, 930:990] = 0  # no chevron yet: the line is still typing
        boxes = [box("威廉明娜", 900, 855, 120, 30), box("就算這個判斷的結果，是背叛了自己的信念", 570, 900, 780, 32)]
        self.assertEqual(Kind.DIALOG, screen.read(frame, boxes).kind)

    def test_bubble_by_text_on_cream(self):
        frame = live("bubble_live.jpg")
        frame[432:462, 1276:1306] = (225, 232, 238)  # no chevron yet
        boxes = [box("莎赫拉查德", 745, 322, 120, 28), box("…沒辦法，我沒辦法確認內部的狀態。", 745, 358, 390, 30)]
        self.assertEqual(Kind.DIALOG, screen.read(frame, boxes).kind)

    def test_name_and_line_on_a_field_are_no_dialog(self):
        boxes = [box("莎赫拉查德", 745, 322, 120, 28), box("…沒辦法，我沒辦法確認內部的狀態。", 745, 358, 390, 30)]
        self.assertNotEqual(Kind.DIALOG, screen.read(live("prompt_live.jpg"), boxes).kind)

    def test_presses_and_their_second_ways(self):
        self.assertEqual((("key", story.ENTER), ("key", story.SPACE), ("click",)), story.LADDERS[Kind.DIALOG])

    def test_other_keeps_its_ladder(self):
        self.assertEqual((("key", story.ENTER), ("key", story.ENTER), ("key", story.SPACE)), story.LADDERS[Kind.OTHER])


class SimplifiedQuickTest(unittest.TestCase):
    def test_pill_by_its_picture(self):
        self.assertEqual(Kind.QUICK, screen.read(live("npc_prompt_cn_live.jpg"), []).kind)

    def test_pill_by_its_words(self):
        self.assertEqual(Kind.QUICK, screen.read(BLACK, [box("进行快速探索", 1650, 195)]).kind)

    def test_step_list_words(self):
        for word in ("前往当前探索", "当前战斗力", "推荐战斗力"):
            boxes = [box(word, 200, 1000), box("自动进行", 1620, 1000)]
            self.assertEqual(Kind.LIST_AUTO, screen.read(BLACK, boxes).kind, word)

    def test_ask_goes_on(self):
        boxes = [box("进行快速探索", 900, 290, 120, 26), box("立刻前往", 1000, 410, 100, 28), box("取消", 790, 410, 60, 28)]
        reading = screen.read(live("quick_ask_cn_live.jpg"), boxes)
        self.assertEqual(Kind.QUICK_ASK, reading.kind)
        self.assertEqual((1050, 424), reading.point)

    def test_falling_snow_is_not_walking(self):
        before = live("npc_prompt_cn_live.jpg")
        after = before.copy()
        rng = np.random.default_rng(1)
        for _flake in range(100):
            x, y = int(rng.integers(0, 1900)), int(rng.integers(100, 1000))
            after[y : y + 6, x : x + 6] = 255
        self.assertFalse(screen.party_walking(before, after))


class HomeTest(unittest.TestCase):
    def test_two_groups_in_either_language(self):
        self.assertTrue(screen.home_seen([box("我的小屋", 20, 170), box("街機遊戲", 20, 300)]))
        self.assertTrue(screen.home_seen([box("格鲁TALK", 20, 240), box("抽抽乐", 1800, 800)]))

    def test_one_group_is_not_home(self):
        self.assertFalse(screen.home_seen([box("我的小屋", 20, 170)]))
        self.assertFalse(screen.home_seen([]))


class BothLanguagesTest(unittest.TestCase):
    def test_simplified_words_read_the_same_screens(self):
        cases = (
            (Kind.QUICK, [box("快速进行任务", 1650, 195)]),
            (Kind.LIST_AUTO, [box("前往当前任务", 190, 995), box("自动进行", 1620, 1000)]),
            (Kind.LIST_BATTLE, [box("可获得的奖励", 1200, 790), box("战斗", 1640, 1000)]),
            (Kind.REWARD, [box("点击画面将回到上一个画面", 700, 980)]),
            (Kind.BOOK, [box("冒险指南", 960, 180)]),
            (Kind.BOOK, [box("前往游戏卡带珍藏集", 1540, 975, 260, 30)]),
            (Kind.SHELF, [box("游戏卡带珍藏集", 240, 35, 210, 30)]),
            (Kind.GUIDE, [box("主线", 1640, 130)]),
            (Kind.WALKING, [box("自动移动中", 900, 200)]),
            (Kind.BATTLE, [box("自动战斗中", 60, 980)]),
            (Kind.SKIP_DIALOG, [box("跳过对话", 900, 300)]),
        )
        for kind, boxes in cases:
            self.assertEqual(kind, screen.read(BLACK, boxes).kind, boxes[0].name)


class WalkStuckTest(unittest.TestCase):
    def test_banner_gives_the_cancel_point_under_it(self):
        reading = screen.read(BLACK, [box("自動移動中：主線任務", 860, 898, 200, 30)])
        self.assertEqual(Kind.WALKING, reading.kind)
        self.assertLess(abs(reading.point[1] - 985), 15)

    def test_a_pan_is_walking(self):
        frame = live("walking_stuck_live.jpg")
        self.assertTrue(screen.party_walking(frame, np.roll(frame, 40, axis=1)))

    def test_a_scrolling_minimap_alone_is_walking(self):
        before = live("walking_stuck_live.jpg")
        after = before.copy()
        after[105:237, 140:272] = np.roll(after[105:237, 140:272], 25, axis=0)
        self.assertTrue(screen.party_walking(before, after))

    def test_a_trap_and_the_marquee_are_not_walking(self):
        before = live("walking_stuck_live.jpg")
        after = before.copy()
        after[350:600, 750:1250] = 255 - after[350:600, 750:1250]  # magic circle
        after[120:200, 1540:1880] = np.roll(after[120:200, 1540:1880], 60, axis=1)  # marquee
        self.assertFalse(screen.party_walking(before, after))

    def test_a_still_frame_is_not_walking(self):
        frame = live("walking_stuck_live.jpg")
        self.assertFalse(screen.party_walking(frame, frame.copy()))

    def test_rungs_one_each_eight_seconds_then_give_up(self):
        watch = story.WalkWatch()
        got = [watch.look(float(t), False) for t in range(0, 41)]
        self.assertEqual([1, 2, 3, 4, 5], [rung for rung in got if rung])
        self.assertEqual([8, 16, 24, 32, 40], [t for t, rung in enumerate(got) if rung])

    def test_walking_starts_it_over(self):
        watch = story.WalkWatch()
        for t in range(0, 9):
            watch.look(float(t), False)
        self.assertEqual(1, watch.rung)
        watch.look(9.0, True)
        self.assertEqual(0, watch.rung)
        got = [watch.look(float(t), False) for t in range(10, 18)]
        self.assertEqual([0, 0, 0, 0, 0, 0, 0, 1], got)

    def test_a_short_gap_keeps_the_rung_a_long_one_starts_over(self):
        watch = story.WalkWatch()
        for t in range(0, 9):
            watch.look(float(t), False)
        watch.look(10.0, False)  # ✕ then E: the banner away a moment
        self.assertEqual(1, watch.rung)
        watch.look(20.0, False)
        self.assertEqual(0, watch.rung)


class RemedyGapTest(unittest.TestCase):
    def test_first_press_at_once_then_longer(self):
        self.assertEqual(
            [0.0, 3.0, 5.0, 8.0, 8.0], [story.remedy_gap(Kind.QUICK, presses) for presses in range(5)]
        )

    def test_dialog_never_waits(self):
        self.assertEqual(0.0, story.remedy_gap(Kind.DIALOG, 9))


class PlayerStepTest(unittest.TestCase):
    def test_quest_line_without_its_mark_and_the_pill(self):
        boxes = [box("主线", 1640, 130), box("E", 1553, 155, 20, 22), box("依序拉动魔法装置", 1580, 160, 220, 26),
                 box("进行快速探索", 1650, 195)]
        self.assertEqual("依序拉动魔法装置", screen.quest_text(boxes))

    def test_waits_on_the_same_quest(self):
        for kind in (Kind.GUIDE, Kind.QUICK, Kind.MANUAL, Kind.PROMPT, Kind.WALKING, Kind.OTHER, Kind.LOADING, Kind.EXIT_MENU):
            self.assertFalse(story.player_step_over(kind, "拉动魔法装置", "拉动魔法装置"), kind)

    def test_an_unread_line_is_no_change(self):
        self.assertFalse(story.player_step_over(Kind.GUIDE, "", "拉动魔法装置"))
        self.assertFalse(story.player_step_over(Kind.GUIDE, "拉动魔法装置", ""))

    def test_done_when_another_quest_is_read_twice(self):
        self.assertFalse(story.player_step_over(Kind.GUIDE, "继续追踪黑魔法师", "拉动魔法装置"))
        self.assertTrue(story.player_step_over(Kind.GUIDE, "继续追踪黑魔法师", "拉动魔法装置", "继续追踪黑魔法师"))

    def test_the_banner_never_ends_it(self):
        self.assertFalse(story.player_step_over(Kind.MANUAL, "别的", "拉动魔法装置", "别的"))

    def test_the_same_line_read_cut_short_is_no_new_quest(self):
        self.assertFalse(story.new_quest("拉动魔法", "依序拉动魔法装置"))

    def test_the_banner_gets_no_press(self):
        self.assertIn(Kind.MANUAL, story.WAITS)

    def test_done_when_a_story_battle_or_list_shows(self):
        for kind in (Kind.SKIP, Kind.SKIP_DIALOG, Kind.DIALOG, Kind.BATTLE, Kind.RESULT, Kind.LIST_AUTO, Kind.LIST_BATTLE):
            self.assertTrue(story.player_step_over(kind, "", "拉动魔法装置"), kind)


class BorrowTest(unittest.TestCase):
    GAME, BROWSER = 10, 20

    def desk(self, front, refuse=()):
        state = {"front": front, "calls": []}

        def set_front(window):
            state["calls"].append(window)
            if window not in refuse:
                state["front"] = window

        return state, (lambda: state["front"]), set_front

    def test_press_then_the_front_goes_back(self):
        state, front, set_front = self.desk(self.BROWSER)
        seen = []
        result = borrow.borrow_foreground(self.GAME, lambda: seen.append(front()), front, set_front, lambda s: None)
        self.assertEqual((True, True), result)
        self.assertEqual([self.GAME], seen)
        self.assertEqual(self.BROWSER, state["front"])

    def test_game_already_in_front_is_left_alone(self):
        state, front, set_front = self.desk(self.GAME)
        self.assertEqual((True, True), borrow.borrow_foreground(self.GAME, lambda: None, front, set_front, lambda s: None))
        self.assertEqual([], state["calls"])

    def test_no_press_when_the_game_never_comes_to_the_front(self):
        state, front, set_front = self.desk(self.BROWSER, refuse=(self.GAME,))
        pressed = []
        result = borrow.borrow_foreground(self.GAME, lambda: pressed.append(1), front, set_front, lambda s: None)
        self.assertEqual((False, True), result)
        self.assertEqual([], pressed)

    def test_going_back_is_tried_twice_and_told(self):
        state, front, set_front = self.desk(self.BROWSER, refuse=(self.BROWSER,))
        result = borrow.borrow_foreground(self.GAME, lambda: None, front, set_front, lambda s: None)
        self.assertEqual((True, False), result)
        self.assertEqual([self.GAME, self.BROWSER, self.BROWSER], state["calls"])

    def test_the_front_goes_back_even_if_the_press_fails(self):
        state, front, set_front = self.desk(self.BROWSER)

        def boom():
            raise RuntimeError

        with self.assertRaises(RuntimeError):
            borrow.borrow_foreground(self.GAME, boom, front, set_front, lambda s: None)
        self.assertEqual(self.BROWSER, state["front"])

    def pinned(self, log):
        def pin(window):
            log.append(("pin", window))
            return lambda: log.append(("unpin", window))

        return pin

    def test_the_front_window_is_pinned_for_the_press_only(self):
        state, front, set_front = self.desk(self.BROWSER)
        log = []
        borrow.borrow_foreground(self.GAME, lambda: log.append("press"), front, set_front, lambda s: None, self.pinned(log))
        self.assertEqual([("pin", self.BROWSER), "press", ("unpin", self.BROWSER)], log)

    def test_unpinned_even_if_the_press_fails(self):
        state, front, set_front = self.desk(self.BROWSER)
        log = []

        def boom():
            raise RuntimeError

        with self.assertRaises(RuntimeError):
            borrow.borrow_foreground(self.GAME, boom, front, set_front, lambda s: None, self.pinned(log))
        self.assertEqual(("unpin", self.BROWSER), log[-1])

    def test_unpinned_when_the_game_never_comes(self):
        state, front, set_front = self.desk(self.BROWSER, refuse=(self.GAME,))
        log = []
        borrow.borrow_foreground(self.GAME, lambda: None, front, set_front, lambda s: None, self.pinned(log))
        self.assertEqual([("pin", self.BROWSER), ("unpin", self.BROWSER)], log)

    def test_nothing_pinned_with_the_game_in_front(self):
        state, front, set_front = self.desk(self.GAME)
        log = []
        borrow.borrow_foreground(self.GAME, lambda: None, front, set_front, lambda s: None, self.pinned(log))
        self.assertEqual([], log)

    def test_a_window_already_on_top_is_left_on_top(self):
        with mock.patch("win32gui.GetWindowLong", return_value=0x8), mock.patch("win32gui.SetWindowPos") as moved:
            borrow.pin_on_top(5)()
        moved.assert_not_called()

    def test_pin_and_unpin_a_normal_window(self):
        with mock.patch("win32gui.GetWindowLong", return_value=0), mock.patch("win32gui.SetWindowPos") as moved:
            borrow.pin_on_top(5)()
        self.assertEqual([-1, -2], [call.args[1] for call in moved.call_args_list])

    def test_mouse_moving_keeps_it_waiting(self):
        path = iter([(0, 0), (5, 0), (9, 0)] + [(9, 0)] * 50)
        waited = borrow.wait_mouse_quiet(lambda: next(path), lambda: False, lambda s: None)
        self.assertAlmostEqual(0.2 + borrow.MOUSE_QUIET, waited, places=5)

    def test_a_held_button_keeps_it_waiting_though_the_mouse_stands(self):
        held = iter([True] * 12 + [False] * 50)
        waited = borrow.wait_mouse_quiet(lambda: (1, 1), lambda: next(held), lambda s: None)
        self.assertAlmostEqual(1.2 + borrow.MOUSE_QUIET, waited, places=5)

    def test_a_still_mouse_waits_only_the_quiet_time(self):
        waited = borrow.wait_mouse_quiet(lambda: (1, 1), lambda: False, lambda s: None)
        self.assertAlmostEqual(borrow.MOUSE_QUIET, waited, places=5)


class Stop(Exception):
    pass


class WaitPressesNothingTest(unittest.TestCase):
    """The whole loop on a long wait: Leo 「這個狀態不要按」."""

    def run_on(self, kinds_after_banner, looks=900, first=Kind.MANUAL):
        task = story.MainStoryTask.__new__(story.MainStoryTask)
        clock = {"t": 0.0}
        seen = {"n": 0}
        pressed = []
        readings = [screen.Reading(first, (100, 100), "first")]
        boxes = [box("使用莎拉的炼金术", 1640, 165, 200, 26)]

        def sleep(seconds):
            clock["t"] += seconds

        def frame():
            seen["n"] += 1
            if seen["n"] > looks:
                raise Stop
            clock["t"] += 0.1
            return BLACK

        def read(_small, _boxes):
            at = seen["n"] - 1
            if at == 0:
                return readings[0]
            return screen.Reading(kinds_after_banner[at % len(kinds_after_banner)], (100, 100), "")

        for name, value in {
            "capture_frame": frame, "sleep": sleep, "_reference_boxes": lambda *a: boxes, "info_set": lambda *a: None,
            "log_info": lambda *a, **k: None, "log_warning": lambda *a, **k: None, "_test_shot": lambda *a: None,
            "_home_confirmation_ok": lambda *a: False, "pause": lambda: pressed.append("pause"),
            "tap_key": lambda key, *a: pressed.append(key) or True,
            "_key": lambda code, label: pressed.append(label) or True,
            "_click_reference": lambda *a, **k: pressed.append("click"),
        }.items():
            setattr(task, name, value)
        with mock.patch.object(screen, "read_pictures", return_value=None), mock.patch.object(screen, "read", read), \
                mock.patch.object(story.time, "monotonic", lambda: clock["t"]), \
                mock.patch.object(screen, "moved", return_value=False):
            with self.assertRaises(Stop):
                task.run_state()
        return pressed, clock["t"]

    def test_no_press_on_any_screen_of_the_step_for_many_minutes(self):
        for kind in sorted(story.PLAYER_STEP_KINDS, key=lambda each: each.name):
            pressed, seconds = self.run_on([kind])
            self.assertEqual([], pressed, kind)
            self.assertGreater(seconds, story.STILL_PAUSE * 2, kind)

    def test_a_quest_e_cannot_walk_gets_its_ladder_once_and_no_esc(self):
        pressed, _seconds = self.run_on([Kind.GUIDE], first=Kind.GUIDE)
        self.assertEqual(["E", "E", "click"], pressed)

    def test_the_exit_menu_does_not_start_the_count_over(self):
        watch = story.ArrivedWatch()
        watch.pressed("塞住凹槽")
        watch.look(Kind.EXIT_MENU, False)
        self.assertEqual(1, watch.plain)

    def test_defeat_waits_with_no_press_and_does_not_end(self):
        for kinds in ([Kind.DEFEAT], [Kind.OTHER], [Kind.DEFEAT, Kind.OTHER]):
            pressed, seconds = self.run_on(kinds, first=Kind.DEFEAT)
            self.assertEqual([], pressed, kinds)
            self.assertGreater(seconds, story.STILL_PAUSE * 2, kinds)

    def test_goes_on_by_itself_after_the_retry(self):
        pressed, _seconds = self.run_on([Kind.SKIP], looks=6, first=Kind.DEFEAT)
        self.assertIn("F2", pressed)

    def test_a_retried_battle_presses_nothing(self):
        pressed, _seconds = self.run_on([Kind.BATTLE], looks=30, first=Kind.DEFEAT)
        self.assertEqual([], pressed)

    def test_no_press_with_the_screens_changing(self):
        pressed, _seconds = self.run_on(sorted(story.PLAYER_STEP_KINDS, key=lambda each: each.name))
        self.assertEqual([], pressed)


class StartTest(unittest.TestCase):
    def test_start_does_not_raise_the_game(self):
        self.assertTrue(story.MainStoryTask.stays_behind)
        source = (Path(__file__).resolve().parents[1] / "src/ui/shell/actions.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("bring_game_to_front()") - 1, source.count('"stays_behind"'))


class ArrivedTest(unittest.TestCase):
    def press_after_banner(self, watch, quest):
        watch.look(Kind.GUIDE, True)
        watch.look(Kind.GUIDE, False)  # gone by the press (live 11:08)
        return watch.pressed(quest)

    def test_the_third_e_after_the_banner_hands_over(self):
        watch = story.ArrivedWatch()
        self.assertEqual([False, False, True], [self.press_after_banner(watch, "解除魔力屏障") for _ in range(3)])

    def test_six_plain_e_on_one_quest_hand_over(self):
        watch = story.ArrivedWatch()
        self.assertEqual([False] * 5 + [True], [watch.pressed("解除魔力屏障") for _ in range(6)])

    def test_anything_else_on_screen_starts_over(self):
        watch = story.ArrivedWatch()
        for _press in range(9):
            watch.look(Kind.LOADING, False)
            self.assertFalse(watch.pressed("前往矿山"))

    def test_a_new_quest_starts_over(self):
        watch = story.ArrivedWatch()
        self.press_after_banner(watch, "一")
        self.press_after_banner(watch, "一")
        self.assertFalse(self.press_after_banner(watch, "二"))

    def test_the_banner_read(self):
        self.assertTrue(screen.arrived([box("已完成自動移動。", 870, 230)]))
        self.assertFalse(screen.arrived([box("自动移动中", 870, 900)]))


class ClickNeverPinsTest(unittest.TestCase):
    def test_a_click_waits_for_the_mouse_and_borrows_nothing(self):
        task = story.MainStoryTask.__new__(story.MainStoryTask)
        order = []
        task._mouse_quiet = lambda: order.append("quiet")
        with mock.patch.object(story.borrow, "borrow_foreground") as borrowed, \
                mock.patch.object(story.borrow, "pin_on_top") as pinned, \
                mock.patch("src.tasks.task_vision_mixin.TaskVisionMixin._click_reference",
                           lambda self, x, y, after_sleep=0.0: order.append("click")):
            task._click_reference(10, 20)
        self.assertEqual(["quiet", "click"], order)
        borrowed.assert_not_called()
        pinned.assert_not_called()


class ChapterDoneTest(unittest.TestCase):
    def test_quest_line_and_its_dialog_end_the_state(self):
        for word in ("再次挑战主线任务", "再次挑戰主線任務"):
            self.assertEqual(Kind.CHAPTER_DONE, screen.read(BLACK, [box(word, 1640, 165)]).kind)
        boxes = [box("再次挑战任务", 860, 300, 200, 30), box("同意", 1060, 715, 60, 28)]
        self.assertEqual(Kind.CHAPTER_DONE, screen.read(live("replay_ask_cn_live.jpg"), boxes).kind)

    def test_it_is_never_pressed(self):
        self.assertNotIn(Kind.CHAPTER_DONE, story.LADDERS)


class NoQuickTest(unittest.TestCase):
    QUICK = screen.Reading(Kind.QUICK, (1716, 208), "pill")

    def test_quick_is_pressed_when_unset(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(story.NO_QUICK_ENV, None)
            self.assertEqual(Kind.QUICK, story.without_quick(self.QUICK, []).kind)

    def test_set_goes_the_e_way(self):
        with mock.patch.dict(os.environ, {story.NO_QUICK_ENV: "1"}):
            self.assertEqual(Kind.GUIDE, story.without_quick(self.QUICK, []).kind)
            ask = screen.Reading(Kind.QUICK_ASK, (1086, 635), "立刻前往")
            cancelled = story.without_quick(ask, [box("取消", 800, 635, 70, 28)])
            self.assertEqual(Kind.EXIT_MENU, cancelled.kind)
            self.assertNotIn(("key", story.ENTER), story.LADDERS[cancelled.kind])


class EscTest(unittest.TestCase):
    def test_exit_menu_gets_esc_only(self):
        for word in ("退出游戏", "結束遊戲", "返回标题", "回到標題"):
            self.assertEqual(Kind.EXIT_MENU, screen.read(BLACK, [box(word, 900, 500)]).kind)
        self.assertEqual((("key", story.ESC), ("key", story.ESC)), story.LADDERS[Kind.EXIT_MENU])

    def test_talent_menu_gets_esc_only(self):
        boxes = [box("天赋技能", 105, 690, 110, 26), box("偷窃", 190, 920, 60, 26), box("对话", 980, 395, 50, 24)]
        reading = screen.read(live("talent_menu_live.jpg"), boxes)
        self.assertEqual(Kind.EXIT_MENU, reading.kind)
        self.assertNotIn(("key", story.ENTER), story.LADDERS[reading.kind])

    def test_talent_words_in_a_story_line_are_no_menu(self):
        self.assertNotEqual(Kind.EXIT_MENU, screen.read(BLACK, [box("使用旅行者的天赋技能", 700, 200, 300, 28)]).kind)

    def test_leaving_words_hold_enter(self):
        self.assertTrue(story.spend_words_on([box("退出遊戲", 900, 500)]))


class ManualStepTest(unittest.TestCase):
    BANNER = box("无法自动进行的探索。", 850, 240, 300, 28)

    def test_banner_on_the_field_is_the_players_step(self):
        self.assertEqual(Kind.MANUAL, screen.read(BLACK, [box("主线", 1640, 130), self.BANNER]).kind)
        self.assertEqual(Kind.MANUAL, screen.read(BLACK, [box("無法自動進行的探索。", 850, 240, 300, 28)]).kind)

    def test_quick_still_comes_first(self):
        boxes = [box("进行快速探索", 1650, 195), self.BANNER]
        self.assertEqual(Kind.QUICK, screen.read(BLACK, boxes).kind)

    def test_no_quick_test_run_stops_there_too(self):
        boxes = [box("进行快速探索", 1650, 195), self.BANNER]
        with mock.patch.dict(os.environ, {story.NO_QUICK_ENV: "1"}):
            self.assertEqual(Kind.MANUAL, story.without_quick(screen.read(BLACK, boxes), boxes).kind)

    def test_it_is_never_pressed(self):
        self.assertNotIn(Kind.MANUAL, story.LADDERS)


class BattleWaitTest(unittest.TestCase):
    def test_turn_one_by_picture_or_text(self):
        self.assertTrue(screen.turn_one(frame_with("turn1_corner_live.jpg", (1550, 930)), []))
        self.assertTrue(screen.turn_one(BLACK, [box("TURN.1", 1620, 970), box("BATTLE", 1740, 970)]))
        self.assertFalse(screen.turn_one(BLACK, [box("TURN.2", 1620, 970)]))
        self.assertFalse(screen.turn_one(BLACK, [box("TURN.12", 1620, 970)]))

    def test_sp_read_with_or_without_its_icon(self):
        self.assertEqual("0/20", screen.sp_text([box("SP 0/20 ?", 840, 1045)]))
        self.assertEqual("0/20", screen.sp_text([box("0/20？", 880, 1045)]))
        self.assertEqual("", screen.sp_text([box("35,460/35,460", 1100, 90)]))

    def test_turn_one_alone_is_a_battle(self):
        self.assertEqual(Kind.BATTLE, screen.read(frame_with("turn1_corner_live.jpg", (1550, 930)), []).kind)

    def test_pressed_once_after_sixty_seconds(self):
        wait = story.BattleWait(0.0)
        self.assertFalse(wait.look(30.0, True, "sp0/20"))
        self.assertFalse(wait.look(59.0, True, "sp0/20"))
        self.assertTrue(wait.look(60.0, True, "sp0/20"))
        self.assertFalse(wait.look(61.0, True, "sp0/20"))

    def test_second_way_only_if_turn_one_stays_then_no_more(self):
        wait = story.BattleWait(0.0)
        self.assertTrue(wait.look(60.0, True, ""))
        self.assertFalse(wait.look(67.0, True, ""))
        self.assertTrue(wait.look(68.5, True, ""))
        self.assertFalse(wait.look(90.0, True, ""))

    def test_never_after_the_turn_ran(self):
        wait = story.BattleWait(0.0)
        wait.look(1.0, True, "")
        for at in (2.0, 3.0, 4.0):
            self.assertFalse(wait.look(at, False, ""))
        self.assertFalse(wait.look(70.0, True, ""))

    def test_one_missed_look_does_not_end_the_wait(self):
        wait = story.BattleWait(0.0)
        wait.look(1.0, True, "")
        wait.look(2.0, False, "")
        self.assertTrue(wait.look(60.0, True, ""))

    def test_never_after_the_player_acted(self):
        wait = story.BattleWait(0.0)
        wait.look(1.0, True, "0/20")
        wait.look(6.0, True, "0/20")
        self.assertFalse(wait.look(8.0, True, "3/20"))
        self.assertFalse(wait.look(70.0, True, "0/20"))

    def test_the_opening_sp_flash_is_no_player(self):
        # Live 第13章: 15/20 on the first look, 0/20 from then on.
        wait = story.BattleWait(0.0)
        wait.look(0.5, True, "15/20")
        wait.look(2.0, True, "0/20")
        wait.look(30.0, True, "0/20")
        self.assertTrue(wait.look(60.0, True, "0/20"))

    def test_auto_already_on_is_never_pressed(self):
        wait = story.BattleWait(0.0)
        self.assertFalse(wait.look(70.0, False, ""))


class TextTest(unittest.TestCase):
    def kind(self, *boxes):
        return screen.read(BLACK, list(boxes)).kind

    def test_quick_first_then_e(self):
        # 「如果有 就優先按這個」: 快速進行任務 before the E guide.
        self.assertEqual(
            Kind.QUICK, self.kind(box("主線", 1650, 135), box("E", 1620, 165, 20), box("快速進行任務", 1700, 200, 150))
        )
        self.assertEqual(Kind.GUIDE, self.kind(box("主线", 1650, 135), box("前往賭場入口", 1650, 165, 150)))
        self.assertEqual(Kind.GUIDE, self.kind(box("E", 1620, 165, 20), box("往賭場入", 1650, 165, 150)))

    def test_skip_dialog_text(self):
        reading = screen.read(BLACK, [box("跳過對話", 900, 300, 150), box("確認", 1020, 770, 50)])
        self.assertEqual(Kind.SKIP_DIALOG, reading.kind)
        self.assertEqual((1045, 785), reading.point)

    def test_f2_text_alone(self):
        self.assertEqual(Kind.SKIP, self.kind(box("F2", 1625, 95, 25, 18)))

    def test_quick_list_auto_then_battle(self):
        listing = box("前往當前任務", 200, 1035, 130)
        self.assertEqual(Kind.LIST_AUTO, self.kind(listing, box("自動進行", 1680, 1035, 100)))
        self.assertEqual(Kind.LIST_BATTLE, self.kind(listing, box("戰鬥", 1700, 1035, 50)))
        self.assertEqual(Kind.REWARD, self.kind(box("REWARD", 900, 330), box("點擊畫面將回到上一個畫面。", 830, 1020, 260)))

    def test_battle_result_defeat(self):
        self.assertEqual(Kind.BATTLE, self.kind(box("自動戰鬥中", 90, 970), box("SP 3/20 ?", 680, 1090)))
        self.assertEqual(Kind.BATTLE, self.kind(box("SP 0/20 ?", 680, 1050)))  # by hand: no 自動 words
        self.assertEqual(Kind.RESULT, self.kind(box("MISSION COMPLETED", 1400, 90), box("離開", 1700, 1040, 50)))
        self.assertEqual(Kind.DEFEAT, self.kind(box("DEFEAT", 800, 500)))

    def test_walking_loading_field_other(self):
        self.assertEqual(Kind.WALKING, self.kind(box("自動移動中：主線任務", 900, 950, 200)))
        self.assertEqual(Kind.LOADING, self.kind(box("NOW", 1800, 1030), box("LOADING", 1850, 1030)))
        self.assertEqual(Kind.FIELD, self.kind(box("SPACE", 1730, 1000), box("TAB", 1770, 1085)))
        self.assertEqual(Kind.OTHER, self.kind(box("黎維塔憑著神乎其技的賭技，接連", 780, 520, 450)))


class GuardsTest(unittest.TestCase):
    def test_spend_words_hold_enter(self):
        self.assertEqual("購買", story.spend_words_on([box("確定要購買嗎？", 800, 500)]))
        self.assertEqual("", story.spend_words_on([box("黎維塔憑著神乎其技的賭技", 800, 500)]))

    def test_every_press_has_a_second_way(self):
        # Leo 2026-11-02: every harmless press needs a remedy if ignored.
        for kind, ladder in story.LADDERS.items():
            self.assertGreaterEqual(len(ladder), 2, kind)

    def test_battle_is_never_pressed(self):
        # 「戰鬥那邊我決定不要按自動戰鬥 讓玩家去操作」
        self.assertNotIn(Kind.BATTLE, story.LADDERS)
        self.assertIn(Kind.BATTLE, story.WAITS)

    def test_state_settings(self):
        self.assertFalse(story.MainStoryTask.start_from_home)
        self.assertFalse(story.MainStoryTask.recover_home_on_failure)
        self.assertTrue(story.MainStoryTask.status_bar_always)


class MovedTest(unittest.TestCase):
    def test_moved(self):
        a = np.zeros((1080, 1920, 3), np.uint8)
        b = a.copy()
        self.assertFalse(screen.moved(a, b))
        b[:, :960] = 200
        self.assertTrue(screen.moved(a, b))
        self.assertTrue(screen.moved(None, a))


if __name__ == "__main__":
    unittest.main()
