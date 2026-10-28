import itertools
import unittest
from pathlib import Path

from src.utils.cartridge_quick_switch import QUICK_SWITCH_STABLE_FRAMES
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.tasks.BaseBD2Task import CartridgeSpecialPageResult
from src.utils.fantasia_square import LIFE_SLOT_POINTS, square_card_point
from src.tasks.map_trade.models import MatchResult, TemplateSpec
from src.tasks.SquareGoddessTask import (
    GODDESS_NAVIGATION_ABSENT,
    GODDESS_WISHED_NOTE,
    FANTASIA_SQUARE_TEMPLATE,
    GODDESS_NAVIGATION_CLICKED,
    QUICK_SWITCH_PAGE_PATTERNS,
    QUICK_SWITCH_TEMPLATE,
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
    SQUARE_CARTRIDGE_SLOT_POINT,
    SQUARE_HOME_POINT,
    SquareGoddessTask,
)
from src.utils.cartridge_quick_switch import (
    FIXED_CARTRIDGE_SLOT_PRE_CLICK_DELAY_SECONDS,
    GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO,
    LIFE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION,
    LIFE_GAMEPLAY_CATEGORY_LABEL,
    LIFE_GAMEPLAY_CATEGORY_OCR_ROI,
    LIFE_GAMEPLAY_CATEGORY_POINT,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"

class SquareGoddessEntryTest(unittest.TestCase):
    def test_home_requires_keyword_votes_brightness_and_gacha_ocr(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {
            "主页确认等待秒数": 0.0,
            "主页压暗阈值": 185.0,
        }
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.sleep = lambda *_args, **_kwargs: None
        bright_frame = np.full((1080, 1920, 3), 255, dtype=np.uint8)
        dimmed_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame = {"value": bright_frame}
        task.capture_frame = lambda: frame["value"]
        left_text = {"value": "我的小屋 格鲁TALK 街机游戏"}
        gacha_text = {"value": ""}

        def fake_ocr(_frame, name, roi=None, **_kwargs):
            if name == "主页左列":
                return left_text["value"]
            return gacha_text["value"]

        task._ocr_text = fake_ocr
        task._sleep_after_recognition = lambda: None
        announcement_clicks = []
        task.operate_click = lambda x, y, after_sleep=0.0: announcement_clicks.append(
            (x, y, after_sleep)
        )

        self.assertFalse(SquareGoddessTask._wait_for_cartridge_home(task))
        gacha_text["value"] = "抽抽乐"
        self.assertTrue(SquareGoddessTask._wait_for_cartridge_home(task))
        frame["value"] = dimmed_frame
        self.assertFalse(SquareGoddessTask._wait_for_cartridge_home(task))
        frame["value"] = bright_frame
        left_text["value"] = "我的小屋"
        self.assertFalse(SquareGoddessTask._wait_for_cartridge_home(task))
        self.assertEqual([(169 / 1920, 615 / 1080, 0.2)], announcement_clicks)

    def test_entry_uses_quick_switch_life_gameplay_and_fixed_second_slot(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        stages = []

        task._wait_for_cartridge_home = lambda: stages.append("home") or True
        task._click_template_until = (
            lambda spec, **_kwargs: stages.append(("quick", spec)) or True
        )
        task._wait_for_quick_switch_page = lambda: stages.append("page") or True
        task._find_square_card = lambda: None

        def open_quick_switcher(**callbacks):
            return (
                callbacks["ensure_home"]()
                and callbacks["click_quick_switch"]()
                and callbacks["confirm_quick_switch_page"]()
            )

        task.open_cartridge_quick_switcher = open_quick_switcher
        sleeps = []
        task.sleep = lambda seconds: sleeps.append(seconds)
        clicks = []
        task.operate_click = (
            lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep))
        )
        task._wait_for_life_gameplay_category = lambda: stages.append("highlight") or True
        task._quick_switch_still_shows = lambda **_kwargs: False
        task._wait_for_template = (
            lambda spec, **_kwargs: stages.append(("square", spec)) or True
        )

        self.assertTrue(SquareGoddessTask._enter_square_from_home(task))
        self.assertEqual(["home", ("quick", QUICK_SWITCH_TEMPLATE), "page"], stages[:3])
        self.assertEqual(
            [0.5, FIXED_CARTRIDGE_SLOT_PRE_CLICK_DELAY_SECONDS],
            sleeps,
        )
        self.assertEqual(
            [
                (*LIFE_GAMEPLAY_CATEGORY_POINT, 0.0),
                (*SQUARE_CARTRIDGE_SLOT_POINT, 0.0),
            ],
            clicks,
        )
        self.assertIn("highlight", stages)
        self.assertIn(("square", FANTASIA_SQUARE_TEMPLATE), stages)

    def test_entry_retries_square_confirmation_after_late_fiend_reward(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {"广场入场等待秒数": 1.0}
        task.info_set = Mock()
        task.open_cartridge_quick_switcher = Mock(return_value=True)
        task._wait_for_life_gameplay_category = Mock(return_value=True)
        task._quick_switch_still_shows = lambda **_kwargs: False
        task.sleep = Mock()
        task.operate_click = Mock()
        task._wait_for_template = Mock(side_effect=[False, True])
        task._find_square_card = lambda: None
        task.log_info = Mock()
        task._handle_recent_cartridge_special_pages = Mock(
            return_value=CartridgeSpecialPageResult.HANDLED
        )

        self.assertTrue(SquareGoddessTask._enter_square_from_home(task))
        self.assertEqual(2, task._wait_for_template.call_count)
        task._handle_recent_cartridge_special_pages.assert_called_once_with(
            allow_pvp_pages=False
        )

    def test_fixed_points_are_relative_to_1920_by_1080(self):
        self.assertEqual(
            (1126 / REFERENCE_WIDTH, 875 / REFERENCE_HEIGHT),
            LIFE_GAMEPLAY_CATEGORY_POINT,
        )
        self.assertEqual(
            (331 / REFERENCE_WIDTH, 970 / REFERENCE_HEIGHT),
            SQUARE_CARTRIDGE_SLOT_POINT,
        )

    def test_entry_stops_before_slot_when_life_category_is_not_confirmed(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.open_cartridge_quick_switcher = lambda **_kwargs: True
        task.sleep = lambda *_args, **_kwargs: None
        task._wait_for_life_gameplay_category = lambda: False
        task._quick_switch_still_shows = lambda **_kwargs: False
        clicks = []
        task.operate_click = lambda x, y, after_sleep=0: clicks.append(
            (x, y, after_sleep)
        )
        task._wait_for_template = lambda *_args, **_kwargs: self.fail(
            "square slot must not be clicked before the life category is confirmed"
        )
        task._find_square_card = lambda: self.fail("no card look before the category")

        self.assertFalse(SquareGoddessTask._enter_square_from_home(task))
        self.assertEqual([(*LIFE_GAMEPLAY_CATEGORY_POINT, 0.0)], clicks)

    def test_entry_reclicks_only_while_switch_page_still_shown(self):
        # Swallowed clicks leave the switch page as it was: re-click the
        # category while it is still unlit, the slot while the page stays.
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.open_cartridge_quick_switcher = lambda **_kwargs: True
        task.sleep = lambda *_args, **_kwargs: None
        category = iter([False, True])
        task._wait_for_life_gameplay_category = lambda: next(category)
        still = {False: iter([True]), True: iter([True, False])}
        task._quick_switch_still_shows = lambda highlighted, seconds: next(still[highlighted])
        clicks = []
        task.operate_click = lambda x, y, after_sleep=0: clicks.append((x, y))
        task._wait_for_template = lambda *_args, **_kwargs: True
        task._find_square_card = lambda: None

        self.assertTrue(SquareGoddessTask._enter_square_from_home(task))
        self.assertEqual(
            [LIFE_GAMEPLAY_CATEGORY_POINT] * 2 + [SQUARE_CARTRIDGE_SLOT_POINT] * 2,
            clicks,
        )

    def _card_row_task(self, card_point, arrivals):
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = Mock()
        task.open_cartridge_quick_switcher = lambda **_kwargs: True
        task.sleep = lambda *_args, **_kwargs: None
        task._wait_for_life_gameplay_category = lambda: True
        task._quick_switch_still_shows = lambda **_kwargs: False
        task._find_square_card = lambda: card_point
        task._handle_recent_cartridge_special_pages = lambda **_kwargs: None
        task._return_home_from_square = Mock(return_value=True)
        task.clicks = []
        task.operate_click = lambda x, y, after_sleep=0: task.clicks.append((x, y))
        arrivals = iter(arrivals)
        task._wait_for_template = lambda *_args, **_kwargs: next(arrivals)
        return task

    def test_entry_clicks_the_square_card_where_its_picture_is(self):
        # v0.1.42 summary 2026-10-15: slot 2 of a player's row opened 格鲁菲餐厅.
        first_slot = LIFE_SLOT_POINTS[1]
        task = self._card_row_task(first_slot, [True])

        self.assertTrue(SquareGoddessTask._enter_square_from_home(task))
        self.assertEqual([LIFE_GAMEPLAY_CATEGORY_POINT, first_slot], task.clicks)
        task._return_home_from_square.assert_not_called()

    def test_unread_card_tries_the_next_slot_after_another_field_opens(self):
        task = self._card_row_task(None, [False, True])

        self.assertTrue(SquareGoddessTask._enter_square_from_home(task))
        self.assertEqual(
            [LIFE_GAMEPLAY_CATEGORY_POINT, LIFE_SLOT_POINTS[0]]
            + [LIFE_GAMEPLAY_CATEGORY_POINT, LIFE_SLOT_POINTS[1]],
            task.clicks,
        )
        self.assertEqual(SQUARE_CARTRIDGE_SLOT_POINT, LIFE_SLOT_POINTS[0])
        task._return_home_from_square.assert_called_once()
        task.log_info.assert_any_call("广场女神像：没认出广场卡带的图，改点生活玩法第2格。")
        task.log_info.assert_any_call("广场女神像：没认出广场卡带的图，改点生活玩法第1格。")

    def test_unread_card_stops_after_every_slot(self):
        task = self._card_row_task(None, [False] * len(LIFE_SLOT_POINTS))

        self.assertFalse(SquareGoddessTask._enter_square_from_home(task))
        self.assertEqual(list(LIFE_SLOT_POINTS), task.clicks[1::2])
        self.assertEqual(len(LIFE_SLOT_POINTS) - 1, task._return_home_from_square.call_count)

    def test_card_found_by_picture_is_not_retried_elsewhere(self):
        task = self._card_row_task(LIFE_SLOT_POINTS[0], [False])

        self.assertFalse(SquareGoddessTask._enter_square_from_home(task))
        task._return_home_from_square.assert_not_called()

    def test_square_card_picture_on_the_life_row(self):
        frame = cv2.imread(str(FIXTURES / "quick_switch" / "life_gameplay_selected_fhd.png"))
        point, score = square_card_point(frame, {}, {})
        self.assertGreater(score, 0.95)
        self.assertAlmostEqual(331 / 1920, point[0], delta=0.01)
        # The same row in another order: the square card first.
        swapped = frame.copy()
        swapped[920:1030, 80:220] = frame[920:1030, 260:400]
        swapped[920:1030, 260:400] = frame[920:1030, 80:220]
        point, _score = square_card_point(swapped, {}, {})
        self.assertAlmostEqual(149 / 1920, point[0], delta=0.01)
        for size in ((2560, 1440), (3840, 2160), (1280, 720)):
            with self.subTest(size=size):
                scaled = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
                point, _score = square_card_point(scaled, {}, {})
                self.assertAlmostEqual(331 / 1920, point[0], delta=0.01)
        battle = cv2.imread(str(FIXTURES / "quick_switch" / "battle_gameplay_selected_fhd.png"))
        self.assertIsNone(square_card_point(battle, {}, {})[0])

    def test_quick_switch_uses_green_template_and_pixel_threshold(self):
        self.assertEqual(
            "image/green/QuickSwitchPlayIco.png",
            QUICK_SWITCH_TEMPLATE.file_name,
        )
        self.assertTrue(QUICK_SWITCH_TEMPLATE.green_mask)
        self.assertEqual(0.85, QUICK_SWITCH_TEMPLATE.min_pixel_score)
        self.assertEqual(0.88, QUICK_SWITCH_TEMPLATE.minimum_safe_threshold)
        # BUG-20260902-06：广场内暗色圆底按钮 1600x901 实测 zncc 最高 0.838，
        # 误检位置最高 0.43；0.78 在两者之间有足够余量。
        self.assertEqual(0.78, QUICK_SWITCH_TEMPLATE.min_zncc_score)
        self.assertIn(0.975, QUICK_SWITCH_TEMPLATE.scale_ratios)
        self.assertNotIn(0.80, QUICK_SWITCH_TEMPLATE.scale_ratios)
        self.assertEqual(
            ((0.15, 0.85, 0.65, 1.0), (0.16, 0.08, 0.24, 0.19)),
            QUICK_SWITCH_TEMPLATE.relative_rois,
        )
        self.assertIsNone(QUICK_SWITCH_TEMPLATE.candidate_center_roi)

    def test_quick_switch_click_uses_two_frame_stable_center(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        task._match = lambda _frame, _spec: MatchResult(
            score=0.95,
            pixel_score=0.90,
            position=(760, 960),
            size=(64, 60),
            zncc_score=0.90,
        )
        task._passes = lambda *_args, **_kwargs: True
        task._mf_offset_for_frame = lambda *_args: (0, 0)
        sleeps = []
        task.sleep = sleeps.append
        clicks = []
        task._click_client = lambda x, y, width, height, after_sleep=0.0: clicks.append(
            (x, y, width, height, after_sleep)
        )

        self.assertTrue(
            SquareGoddessTask._click_template_until(
                task,
                QUICK_SWITCH_TEMPLATE,
                timeout=0.01,
                name="快速切换按钮",
                stabilize=True,
            )
        )
        self.assertEqual([(792, 990, 1920, 1080, 0.0)], clicks)
        # Two agreeing frames, one sample after the first (Leo 10-11).
        self.assertEqual(QUICK_SWITCH_STABLE_FRAMES - 1, len(sleeps))
        self.assertTrue(all(seconds == 0.1 for seconds in sleeps))

    def test_masked_match_ignores_non_finite_scores_from_black_regions(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {"masked-test-threshold": 0.7}
        task._match_pause_until = 0.0
        task._missing_template_names = set()
        task._match_error_names = set()
        task._templates = {}
        task._load_template = lambda _spec: (
            np.ones((5, 5), dtype=np.uint8),
            np.full((5, 5), 255, dtype=np.uint8),
        )
        spec = TemplateSpec(
            name="masked-test",
            file_name="masked-test.png",
            threshold_key="masked-test-threshold",
            default_threshold=0.7,
            roi=(0, 0, 6, 6),
        )
        response = np.array(
            [[np.inf, np.nan], [0.8, -np.inf]],
            dtype=np.float32,
        )

        with (
            patch(
                "src.utils.template_resolution.offline_template_uses_main_region",
                return_value=False,
            ),
            patch(
                "src.utils.template_resolution.offline_template_scale",
                return_value=1.0,
            ),
            patch(
                "src.utils.image_utils.reference_roi_frame",
                side_effect=lambda frame, _roi, _reference: (0, 0, frame),
            ),
            patch("src.utils.image_utils.candidate_scales", return_value=[1.0]),
            patch(
                "src.utils.image_utils.resize_template",
                side_effect=lambda template, _scale: template,
            ),
            patch(
                "src.utils.image_utils.resize_mask",
                side_effect=lambda mask, _scale: mask,
            ),
            patch("src.utils.image_utils.cv2.matchTemplate", return_value=response),
        ):
            result = SquareGoddessTask._match(
                task,
                np.zeros((6, 6), dtype=np.uint8),
                spec,
            )

        self.assertAlmostEqual(0.8, result.score)
        self.assertEqual((0, 1), result.position)
        self.assertTrue(np.isfinite(response).all())

    def test_quick_switch_page_requires_all_requested_labels_after_one_second(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {"卡带选择页确认等待秒数": 0.0}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        text = {"value": "店长游戏卡 角色游戏卡 生活玩法游戏卡带"}
        task._ocr_text = lambda *_args, **_kwargs: text["value"]
        sleeps = []
        task.sleep = lambda seconds: sleeps.append(seconds)

        self.assertFalse(SquareGoddessTask._wait_for_quick_switch_page(task))
        text["value"] += " 活动游戏卡"
        self.assertTrue(SquareGoddessTask._wait_for_quick_switch_page(task))
        self.assertEqual(
            ("店长游戏卡", "角色游戏卡", "生活玩法游戏卡带", "活动游戏卡"),
            QUICK_SWITCH_PAGE_PATTERNS,
        )
        self.assertEqual(2, sleeps.count(1.0))

    def test_quick_switch_page_label_with_its_last_character_cut(self):
        # 问题摘要 2026-10-27: the open bar read 「活动游戏」 for 活动游戏卡.
        task = object.__new__(SquareGoddessTask)
        task.config = {"卡带选择页确认等待秒数": 0.0}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        task._ocr_text = lambda *_args, **_kwargs: (
            "最近 店长游戏卡 剧情游戏卡 角色游戏卡 战斗玩法游戏卡带 生活玩法游戏卡带 "
            "活动游戏 查看战场奖励 123"
        )
        task.sleep = lambda seconds: None
        self.assertTrue(SquareGoddessTask._wait_for_quick_switch_page(task))

    def test_life_gameplay_category_requires_ocr_and_visual_highlight(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {"玩法类别高亮确认秒数": 0.0}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.sleep = lambda *_args, **_kwargs: None
        task._ocr_text = lambda *_args, **_kwargs: LIFE_GAMEPLAY_CATEGORY_LABEL
        frame = {"value": np.zeros((1080, 1920, 3), dtype=np.uint8)}
        task.capture_frame = lambda: frame["value"]

        self.assertFalse(SquareGoddessTask._wait_for_life_gameplay_category(task))

        left = round(LIFE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION[0] * REFERENCE_WIDTH)
        top = round(LIFE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION[1] * REFERENCE_HEIGHT)
        right = round(LIFE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION[2] * REFERENCE_WIDTH)
        bottom = round(LIFE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION[3] * REFERENCE_HEIGHT)
        frame["value"][top:bottom, left:right] = 255

        self.assertTrue(SquareGoddessTask._wait_for_life_gameplay_category(task))
        self.assertEqual((1025, 840, 204, 75), LIFE_GAMEPLAY_CATEGORY_OCR_ROI)
        self.assertEqual(0.05, GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO)

    def test_goddess_flow_uses_notice_joint_daily_signal_then_prayer(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        stages = []
        task._click_square_notice_if_present = lambda: stages.append("notice") or False
        task._click_goddess_daily_navigation_until = (
            lambda **_kwargs: stages.append("navigation") or GODDESS_NAVIGATION_CLICKED
        )
        task._wait_for_goddess_prayer_completion = (
            lambda **_kwargs: stages.append("pray") or True
        )

        self.assertTrue(SquareGoddessTask._pray_at_goddess(task))
        self.assertEqual(
            ["notice", "navigation", "pray", "notice"],
            stages,
        )

    def test_post_prayer_notice_hit_or_timeout_both_continue_to_home(self):
        for post_notice_found in (False, True):
            with self.subTest(post_notice_found=post_notice_found):
                task = object.__new__(SquareGoddessTask)
                task.config = {}
                task.info_set = lambda *_args, **_kwargs: None
                task.log_info = lambda *_args, **_kwargs: None
                notice_calls = []

                def click_notice():
                    notice_calls.append("look")
                    return len(notice_calls) == 2 and post_notice_found

                task._click_square_notice_if_present = click_notice
                task._click_goddess_daily_navigation_until = (
                    lambda **_kwargs: GODDESS_NAVIGATION_CLICKED
                )
                task._wait_for_goddess_prayer_completion = lambda **_kwargs: True

                self.assertTrue(SquareGoddessTask._pray_at_goddess(task))
                self.assertEqual(["look", "look"], notice_calls)

    def test_missing_navigation_fails_even_after_dispatch_notice(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        stages = []
        task._click_square_notice_if_present = lambda: stages.append("notice") or False
        task._click_goddess_daily_navigation_until = (
            lambda **_kwargs: stages.append("navigation") or False
        )
        task._wait_for_goddess_prayer_completion = (
            lambda **_kwargs: stages.append("pray") or True
        )
        task._wished_today = lambda: False
        task._prayer_prompt_steady = lambda: False
        task._press_row_where_it_usually_is = lambda: False
        task._walk_by_key = lambda: False

        self.assertFalse(SquareGoddessTask._pray_at_goddess(task))
        self.assertEqual(
            ["notice", "navigation"],
            stages,
        )
        # Already wished today: the missing hint means done, not failed.
        task._wished_today = lambda: True
        self.assertTrue(SquareGoddessTask._pray_at_goddess(task))
        self.assertNotIn("pray", stages)

    def _row_gone_task(self, navigation, square_shown):
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.done_already_note = ""
        stages = []
        task._click_square_notice_if_present = lambda: False
        task._click_goddess_daily_navigation_until = lambda **_kwargs: navigation
        task._wait_for_goddess_prayer_completion = (
            lambda **_kwargs: stages.append("pray") or True
        )
        task._wished_today = lambda: False
        task._prayer_prompt_steady = lambda: False
        task._walk_by_key = lambda: stages.append("E") or False
        task._press_row_where_it_usually_is = lambda: stages.append("spot") or False
        task._square_still_shown = lambda: square_shown
        return task, stages

    def test_no_wish_row_in_a_clear_square_means_wished_today(self):
        # 4K 2026-10-28 00:37 (game day 10-28): Leo had wished; every look read
        # the square's right side with no daily row, E and the row's spot
        # started no walk, the square was still up → was 失败, now 跳过.
        task, stages = self._row_gone_task(GODDESS_NAVIGATION_ABSENT, True)
        self.assertTrue(SquareGoddessTask._pray_at_goddess(task))
        self.assertEqual(["E", "spot"], stages)
        self.assertEqual(GODDESS_WISHED_NOTE, task.done_already_note)

    def test_no_wish_row_but_square_covered_is_still_a_failure(self):
        task, stages = self._row_gone_task(GODDESS_NAVIGATION_ABSENT, False)
        self.assertFalse(SquareGoddessTask._pray_at_goddess(task))
        self.assertEqual("", task.done_already_note)

    def test_task_text_seen_but_row_unread_is_still_a_failure(self):
        # Some look saw task words it could not pair: the row may be there.
        task, stages = self._row_gone_task(None, True)
        self.assertFalse(SquareGoddessTask._pray_at_goddess(task))
        self.assertEqual("", task.done_already_note)

    def test_navigation_is_absent_only_when_every_look_was_absent(self):
        for states, expected in (
            (["absent"] * 3, GODDESS_NAVIGATION_ABSENT),
            (["absent", "unknown", "absent"], None),
        ):
            with self.subTest(states=states):
                task = object.__new__(SquareGoddessTask)
                looks = iter(states)
                clock = iter(range(100))
                task.capture_frame = lambda: None
                task.sleep = lambda _seconds: None
                task._observe_goddess_navigation = lambda _frame: SimpleNamespace(
                    state=next(looks), navigation=None
                )
                with patch(
                    "src.tasks.SquareGoddessTask.monotonic",
                    side_effect=lambda: next(clock) * 0.5,
                ):
                    result = SquareGoddessTask._click_goddess_daily_navigation_until(
                        task, timeout=1.0
                    )
                self.assertEqual(expected, result)

    def test_wished_before_run_records_the_day_and_says_skipped(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {"启用": True}
        info = {}
        task.info_set = lambda key, value: info.__setitem__(key, value)
        messages = []
        task.log_info = lambda message, notify=False: messages.append(message)
        recorded = []
        task._record_wish = lambda: recorded.append(True)
        task._enter_square_from_home = lambda: True
        task._pray_at_goddess = lambda: task.done_already(GODDESS_WISHED_NOTE) or True
        task._return_home_from_square = lambda: True

        self.assertTrue(SquareGoddessTask.run(task))
        self.assertEqual([True], recorded)
        self.assertEqual("今天已许愿", info["女神像许愿结果"])
        self.assertEqual("今天已许愿，跳过并返回主页。", info["状态"])

    def test_successful_run_returns_home_after_prayer(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {"启用": True}
        task.info_set = lambda *_args, **_kwargs: None
        notifications = []
        task.log_info = lambda message, notify=False: notifications.append(
            (message, notify)
        )
        stages = []
        task._enter_square_from_home = lambda: stages.append("enter") or True
        task._pray_at_goddess = lambda: stages.append("pray") or True
        task._return_home_from_square = lambda: stages.append("home") or True

        self.assertTrue(SquareGoddessTask.run(task))
        self.assertEqual(["enter", "pray", "home"], stages)
        self.assertEqual(
            [
                ("广场女神像：开始从主页进入梦幻广场。", False),
                ("广场女神像：许愿完成并返回主页。", True),
            ],
            notifications,
        )

    def test_failed_wish_still_leaves_the_square(self):
        # Leo 2026-10-11 「哪怕我有沒有點到女神像 我都是要離開廣場進行下一步的」
        task = object.__new__(SquareGoddessTask)
        task.config = {"启用": True}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task._status_set = lambda *_args: None
        stages = []
        task._enter_square_from_home = lambda: stages.append("enter") or True
        task._pray_at_goddess = lambda: stages.append("pray") or False
        task._return_home_from_square = lambda: stages.append("home") or True
        task._record_wish = lambda: self.fail("no wish recorded")

        self.assertFalse(SquareGoddessTask.run(task))
        self.assertEqual(["enter", "pray", "home"], stages)

    def test_square_return_home_uses_relative_home_point_and_restores_timeout(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {
            "主页确认等待秒数": 10.0,
            "广场返回主页等待秒数": 15.0,
            "广场返回主页最多点击次数": 3,
            "广场返回主页重试间隔秒数": 2.0,
        }
        statuses = {}
        task.info_set = lambda key, value: statuses.__setitem__(key, value)
        clicks = []
        task.operate_click = lambda *args, **kwargs: clicks.append((args, kwargs))
        observed_waits = []
        task._wait_for_cartridge_home = (
            lambda **kwargs: observed_waits.append(kwargs) or True
        )

        self.assertTrue(SquareGoddessTask._return_home_from_square(task))
        self.assertEqual([((*SQUARE_HOME_POINT,), {"after_sleep": 1.0})], clicks)
        self.assertEqual(
            [
                {
                    "timeout": 15.0,  # Leo 2026-10-15: a load wait keeps its setting
                    "retry_home_clicks": 2,
                    "retry_interval": 2.0,
                    "total_home_clicks": 3,
                }
            ],
            observed_waits,
        )
        self.assertEqual("1/3", statuses["广场主页点击次数"])
        self.assertEqual(10.0, task.config["主页确认等待秒数"])

    def test_square_return_home_retries_when_quick_switch_confirms_still_in_square(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {"主页压暗阈值": 185.0}
        statuses = {}
        task.info_set = lambda key, value: statuses.__setitem__(key, value)
        logs = []
        task.log_info = logs.append
        task.sleep = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.full((1080, 1920, 3), 255, dtype=np.uint8)
        ocr_texts = iter(("", "", "", "抽抽乐"))

        def fake_ocr(_frame, name, roi=None, **_kwargs):
            if name == "主页左列":
                return "我的小屋 格鲁TALK 街机游戏"
            return next(ocr_texts)

        task._ocr_text = fake_ocr
        task.clear_temporary_home_announcement_if_needed = (
            lambda **_kwargs: False
        )
        task._match = lambda _frame, _spec: MatchResult(
            score=0.95,
            pixel_score=0.90,
            position=(760, 960),
            size=(64, 60),
            zncc_score=0.90,
        )
        task._passes = lambda *_args, **_kwargs: True
        clicks = []
        task.operate_click = lambda *args, **kwargs: clicks.append((args, kwargs))

        with patch(
            "src.tasks.SquareGoddessTask.monotonic",
            side_effect=[0.0] * 10,
        ):
            self.assertTrue(
                SquareGoddessTask._wait_for_cartridge_home(
                    task,
                    timeout=10.0,
                    retry_home_clicks=2,
                    retry_interval=0.0,
                    total_home_clicks=3,
                )
            )

        self.assertEqual(
            [((*SQUARE_HOME_POINT,), {"after_sleep": 1.0})],
            clicks,
        )
        self.assertEqual("2/3", statuses["广场主页点击次数"])
        self.assertTrue(any("执行第2次点击" in message for message in logs))

    def test_square_return_home_presses_h_without_quick_switch_signal(self):
        # Leo 2026-10-11 「不可以說認不到辨識不到就卡住 你可以用快捷鍵」: with
        # neither home nor the square's button read, the game's H key (no click
        # that could land on home's menu icon).
        task = object.__new__(SquareGoddessTask)
        task.config = {"主页压暗阈值": 185.0}
        task.info_set = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        task.sleep = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.full((1080, 1920, 3), 255, dtype=np.uint8)

        def fake_ocr(_frame, name, roi=None, **_kwargs):
            if name == "主页左列":
                return "我的小屋 格鲁TALK 街机游戏"
            return ""

        task._ocr_text = fake_ocr
        task.clear_temporary_home_announcement_if_needed = (
            lambda **_kwargs: False
        )
        task._match = lambda _frame, _spec: MatchResult(
            score=0.50,
            pixel_score=0.40,
            position=(760, 960),
            size=(64, 60),
            zncc_score=0.30,
        )
        task._passes = lambda *_args, **_kwargs: False
        clicks = []
        task.operate_click = lambda *args, **kwargs: clicks.append((args, kwargs))
        keys = []
        task.tap_key = lambda key, **kwargs: keys.append((key, kwargs)) or True
        clock = {"value": 0.0}

        def advance_clock():
            clock["value"] += 0.1
            return clock["value"]

        with patch(
            "src.tasks.SquareGoddessTask.monotonic",
            side_effect=advance_clock,
        ):
            self.assertFalse(
                SquareGoddessTask._wait_for_cartridge_home(
                    task,
                    timeout=0.5,
                    retry_home_clicks=2,
                    retry_interval=0.0,
                    total_home_clicks=3,
                )
            )

        self.assertEqual([], clicks)
        self.assertEqual([("H", {"after_sleep": 1.0})] * 2, keys)

    def test_square_return_home_stops_after_retry_budget_is_exhausted(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {"主页压暗阈值": 185.0}
        task.info_set = lambda *_args, **_kwargs: None
        logs = []
        task.log_info = logs.append
        task.sleep = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.full((1080, 1920, 3), 255, dtype=np.uint8)

        def fake_ocr(_frame, name, roi=None, **_kwargs):
            if name == "主页左列":
                return "我的小屋 格鲁TALK 街机游戏"
            return "输入"

        task._ocr_text = fake_ocr
        task.clear_temporary_home_announcement_if_needed = (
            lambda **_kwargs: False
        )
        task._match = lambda _frame, _spec: MatchResult(
            score=0.95,
            pixel_score=0.90,
            position=(760, 960),
            size=(64, 60),
            zncc_score=0.90,
        )
        task._passes = lambda *_args, **_kwargs: True
        clicks = []
        task.operate_click = lambda *args, **kwargs: clicks.append((args, kwargs))
        clock = {"value": 0.0}

        def advance_clock():
            clock["value"] += 0.1
            return clock["value"]

        with patch(
            "src.tasks.SquareGoddessTask.monotonic",
            side_effect=advance_clock,
        ):
            self.assertFalse(
                SquareGoddessTask._wait_for_cartridge_home(
                    task,
                    timeout=1.0,
                    retry_home_clicks=2,
                    retry_interval=0.0,
                    total_home_clicks=3,
                )
            )

        self.assertEqual(
            [
                ((*SQUARE_HOME_POINT,), {"after_sleep": 1.0}),
                ((*SQUARE_HOME_POINT,), {"after_sleep": 1.0}),
            ],
            clicks,
        )
        self.assertEqual(1, sum("执行第2次点击" in message for message in logs))
        self.assertEqual(1, sum("执行第3次点击" in message for message in logs))

    def test_square_notice_dismisses_field_followers(self):
        from src.utils.field_followers import reset_dismissed

        reset_dismissed()
        task = object.__new__(SquareGoddessTask)
        calls = []
        task.dismiss_field_followers = lambda **kwargs: calls.append(kwargs) or outcome
        task.sleep = lambda seconds: calls.append(("sleep", seconds))

        for outcome, expected in (
            ("dismissed", True),
            ("still_visible", True),
            ("absent", False),
            ("done_today", False),
        ):
            with self.subTest(outcome=outcome):
                self.assertEqual(
                    expected, SquareGoddessTask._click_square_notice_if_present(task)
                )
        # 5 s for the "!", 5 s for the crowd, then the F key; 1.5 s after a
        # press clears it (Leo 2026-10-20).
        look = {"appear_seconds": 5.0, "gather_seconds": 5.0, "use_key": True}
        self.assertEqual([look, ("sleep", 1.5), look, look, look], calls)

    def test_square_notice_after_todays_press_only_glances(self):
        # 「鏡中之戰趕走過 工具就記錄一下 廣場就不用等了」 (Leo 2026-10-20).
        from src.utils.field_followers import mark_dismissed, reset_dismissed

        task = object.__new__(SquareGoddessTask)
        calls = []
        task.dismiss_field_followers = lambda **kwargs: calls.append(kwargs) or "absent"
        task.sleep = lambda seconds: calls.append(("sleep", seconds))
        mark_dismissed()
        self.addCleanup(reset_dismissed)

        self.assertFalse(SquareGoddessTask._click_square_notice_if_present(task))
        self.assertEqual(
            [{"appear_seconds": 0.5, "use_key": True, "even_if_done_today": True}], calls
        )

    def test_prayer_prefers_ocr_center_and_confirms_navigation_disappeared(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {
            "女神像许愿等待秒数": 8.0,
            "女神像许愿最多点击次数": 3,
            "女神像完成确认等待秒数": 8.0,
        }
        task.info_set = lambda *_args, **_kwargs: None
        task.sleep = lambda *_args, **_kwargs: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        task._ocr_pattern_click_point = (
            lambda _frame, _patterns, name, roi: (
                ((1410, 880), "向女神像许愿") if name == "女神像许愿" else (None, "")
            )
        )
        clicks = []
        task._click_client = lambda *args, **kwargs: clicks.append((args, kwargs))
        task.operate_click = lambda *_args, **_kwargs: self.fail("不应使用固定点")
        task._wait_for_daily_navigation_to_disappear = (
            lambda **_kwargs: True
        )

        self.assertTrue(
            SquareGoddessTask._wait_for_goddess_prayer_completion(
                task,
                timeout=0.1,
            )
        )
        self.assertEqual(
            [((1410, 880, 1920, 1080), {"after_sleep": 2.0})],
            clicks,
        )

    def test_swallowed_navigation_is_reclicked_at_most_twice(self):
        # Live 2026-09-26: the navigation row stayed and no prompt appeared.
        task = object.__new__(SquareGoddessTask)
        task.config = {"女神像导航重试秒数": 35.0}
        task.info_set = lambda *args: None
        task.log_info = lambda *args: None
        task.sleep = lambda *args: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        task._ocr_pattern_click_point = lambda *args, **kwargs: (None, "")
        row = SimpleNamespace(center=(1680, 314))
        task._observe_goddess_navigation = lambda frame: SimpleNamespace(navigation=row)
        clicks = []
        task._click_client = lambda *args, **kwargs: clicks.append(args[:2])
        keys = []
        task.tap_key = lambda key, after_sleep=0.0: keys.append(key) or True
        task._wait_for_daily_navigation_to_disappear = lambda **_kwargs: False
        clock = iter(range(0, 1000, 10))
        with patch("src.tasks.SquareGoddessTask.monotonic", side_effect=lambda: next(clock)):
            self.assertFalse(task._wait_for_goddess_prayer_completion(timeout=300))
        self.assertEqual([(1680, 314), (1680, 314)], clicks)
        # Before giving up, the talk key F once (Leo 2026-10-20).
        self.assertEqual(["F"], keys)

    def test_unread_prompt_wishes_with_f_when_the_row_goes_away(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {"女神像导航重试秒数": 35.0}
        task.info_set = lambda *args: None
        task.log_info = lambda *args: None
        task.sleep = lambda *args: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        task._ocr_pattern_click_point = lambda *args, **kwargs: (None, "")
        task._observe_goddess_navigation = lambda frame: SimpleNamespace(navigation=None)
        task._click_client = lambda *args, **kwargs: None
        keys = []
        task.tap_key = lambda key, after_sleep=0.0: keys.append(key) or True
        task._wait_for_daily_navigation_to_disappear = lambda **_kwargs: True
        clock = iter(range(0, 1000, 10))
        with patch("src.tasks.SquareGoddessTask.monotonic", side_effect=lambda: next(clock)):
            self.assertTrue(task._wait_for_goddess_prayer_completion(timeout=300))
        self.assertIn("F", keys)

    def test_wish_made_leaves_within_seconds_without_pressing_e(self):
        # Player report 2026-10-20: wished, then the tool stood there for
        # minutes and called it unfinished.  A late done-read after the press
        # still ends the wait, and E (dead after the wish) is never pressed.
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *args: None
        task.log_info = lambda *args: None
        task.sleep = lambda *args: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        prompts = iter([((1410, 880), "向女神像许愿")])
        task._ocr_pattern_click_point = lambda *args, **kwargs: next(prompts, (None, ""))
        task._observe_goddess_navigation = lambda frame: SimpleNamespace(navigation=None)
        task._click_client = lambda *args, **kwargs: None
        task.tap_key = lambda key, after_sleep=0.0: self.fail(f"no key after the wish: {key}")
        checks = iter([False, True])
        task._wait_for_daily_navigation_to_disappear = lambda **_kwargs: next(checks)
        clock = iter(range(0, 1000))
        with patch("src.tasks.SquareGoddessTask.monotonic", side_effect=lambda: next(clock)):
            self.assertTrue(task._wait_for_goddess_prayer_completion(timeout=90))
            self.assertLess(next(clock), 15)

    def test_prayer_without_prompt_never_clicks_or_completes(self):
        task = object.__new__(SquareGoddessTask)
        task.config = {}
        task.info_set = lambda *args: None
        task.sleep = lambda *args: None
        task.capture_frame = lambda: np.zeros((720, 1280, 3), dtype=np.uint8)
        task._ocr_pattern_click_point = lambda *args, **kwargs: (None, "")
        task._click_client = lambda *args, **kwargs: self.fail("No prayer prompt")
        task.operate_click = lambda *args, **kwargs: self.fail("No fixed click")
        with patch("src.tasks.SquareGoddessTask.monotonic", side_effect=itertools.count(0, 2)):
            self.assertFalse(task._wait_for_goddess_prayer_completion(timeout=1))


class StuckGoddessWalkTest(unittest.TestCase):
    """Player report 2026-10-11: the walk to the goddess stopped on the way
    with "自动移动中" still up and the home button hidden."""

    BANNER = "自动移动中：艾力克史温女神像"
    CANCEL = (960 / REFERENCE_WIDTH, 985 / REFERENCE_HEIGHT)

    def _task(self, screens):
        """``screens`` yields the full-frame text of each look, in order."""
        task = object.__new__(SquareGoddessTask)
        task.config = {"女神像导航入口等待秒数": 8.0}
        task.info_set = lambda *args: None
        logs = []
        task.log_info = logs.append
        clock = [0.0]

        def sleep(seconds=0, *args):
            clock[0] += max(float(seconds), 0.5)

        task.sleep = sleep
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), dtype=np.uint8)
        state = {"text": ""}

        def look(*args, **kwargs):
            state["text"] = next(screens, state["text"])
            return state["text"]

        task._ocr_text = lambda frame, name, **kwargs: look()

        def prayer(frame, patterns, name, roi=None):
            text = look()
            if "许愿" in text and "移动中" not in text:
                return (1410, 880), text
            return None, text

        task._ocr_pattern_click_point = prayer
        clicks = []
        task.operate_click = lambda x, y, **kwargs: clicks.append((x, y))
        task._click_client = lambda *args, **kwargs: clicks.append(args[:2])
        navigations = []
        task._click_goddess_daily_navigation_until = (
            lambda timeout: navigations.append(timeout) or GODDESS_NAVIGATION_CLICKED
        )
        return task, clock, clicks, navigations, logs

    def _run(self, task, clock, timeout=90):
        with patch("src.tasks.SquareGoddessTask.monotonic", side_effect=lambda: clock[0]):
            return task._wait_for_goddess_prayer_completion(timeout=timeout)

    def test_a_stuck_walk_is_stopped_and_the_navigation_pressed_again(self):
        # The banner over a field that does not move for 10 s (Leo 2026-10-14:
        # was 20 s of banner), then the ✕ works and the prompt shows.
        screens = iter([self.BANNER] * 25 + ["", "", "", "向女神像许愿"])
        task, clock, clicks, navigations, logs = self._task(screens)
        task._wait_for_daily_navigation_to_disappear = lambda **kwargs: True
        self.assertTrue(self._run(task, clock))
        self.assertIn(self.CANCEL, clicks)
        self.assertEqual([8.0], navigations)
        self.assertEqual((1410, 880), clicks[-1])
        self.assertTrue(any("画面超过10秒没动" in line for line in logs))

    def test_a_long_walk_that_keeps_moving_is_not_stopped(self):
        # 30 s of banner over a field that pans: the game is walking.
        screens = iter([self.BANNER] * 120 + ["向女神像许愿"])
        task, clock, clicks, navigations, logs = self._task(screens)
        looks = itertools.count()
        task.capture_frame = lambda: np.full(
            (1080, 1920, 3), 60 * (next(looks) % 2), dtype=np.uint8
        )
        task._wait_for_daily_navigation_to_disappear = lambda **kwargs: True
        self.assertTrue(self._run(task, clock))
        self.assertNotIn(self.CANCEL, clicks)
        self.assertEqual([], navigations)
        self.assertGreater(clock[0], 20.0)

    def test_a_walk_stuck_every_time_ends_with_the_walk_stopped(self):
        # The banner goes when ✕ is pressed and comes back with each navigation.
        task, clock, clicks, navigations, logs = self._task(iter(()))
        walking = {"on": True}
        task._ocr_text = lambda frame, name, **kwargs: self.BANNER if walking["on"] else ""
        task._ocr_pattern_click_point = (
            lambda *args, **kwargs: (None, self.BANNER if walking["on"] else "")
        )

        def press(x, y, **kwargs):
            clicks.append((x, y))
            walking["on"] = False

        task.operate_click = press

        def navigate(timeout):
            navigations.append(timeout)
            walking["on"] = True
            return GODDESS_NAVIGATION_CLICKED

        task._click_goddess_daily_navigation_until = navigate
        self.assertFalse(self._run(task, clock))
        self.assertEqual(2, len(navigations))
        self.assertEqual([self.CANCEL] * 3, clicks)
        self.assertFalse(walking["on"])
        self.assertIn("这次没有许愿", logs[-1])

    def test_a_short_walk_is_left_alone(self):
        screens = iter([self.BANNER] * 10 + ["", "向女神像许愿"])
        task, clock, clicks, navigations, logs = self._task(screens)
        task._wait_for_daily_navigation_to_disappear = lambda **kwargs: True
        self.assertTrue(self._run(task, clock))
        self.assertEqual([(1410, 880)], clicks)
        self.assertEqual([], navigations)

    def test_the_cross_is_pressed_only_while_two_looks_show_the_banner(self):
        for screens, pressed in (
            ([self.BANNER, ""], False),
            (["", self.BANNER], False),
            ([self.BANNER, self.BANNER, "", "", ""], True),
        ):
            with self.subTest(screens=screens):
                task, clock, clicks, _navigations, _logs = self._task(iter(screens))
                task._cancel_goddess_walk()
                self.assertEqual([self.CANCEL] if pressed else [], clicks)

    def test_a_timeout_stops_a_walk_still_under_way(self):
        task, clock, clicks, _navigations, _logs = self._task(iter(()))
        task.config["女神像寻路卡住秒数"] = 1000.0
        task._ocr_text = lambda frame, name, **kwargs: self.BANNER
        task._ocr_pattern_click_point = lambda *args, **kwargs: (None, self.BANNER)
        self.assertFalse(self._run(task, clock, timeout=30))
        self.assertIn(self.CANCEL, clicks)

    def test_a_banner_naming_the_wish_is_not_the_prompt(self):
        task = object.__new__(SquareGoddessTask)
        boxes = [
            SimpleNamespace(name="自动移动中：向女神像许愿", x=800, y=950, width=300, height=30)
        ]
        task._ocr_boxes = lambda *args, **kwargs: boxes
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        point, _text = task._ocr_pattern_click_point(frame, ["许愿"], name="女神像许愿")
        self.assertIsNone(point)
        boxes.append(SimpleNamespace(name="向女神像许愿", x=1300, y=860, width=200, height=40))
        point, _text = task._ocr_pattern_click_point(frame, ["许愿"], name="女神像许愿")
        self.assertEqual((1400, 880), point)


if __name__ == "__main__":
    unittest.main()


class SquareArrivalWaitTest(unittest.TestCase):
    """Leo 2026-10-15 「我說的10秒是卡死 或者辨識不到」: loading is not stuck."""

    def _run(self, screen_at, prompt_at=None, before=None):
        from src.utils.wait_limits import STUCK_SECONDS  # noqa: F401

        task = object.__new__(SquareGoddessTask)
        task._scene_at_press = before
        task.config = {}
        task.info_set = lambda *_args, **_kwargs: None
        logs = []
        task.log_info = lambda message, **_kwargs: logs.append(message)
        clock = [0.0]
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + 1.0)
        task.capture_frame = lambda: screen_at(clock[0])
        task._match = lambda frame, spec: MatchResult(-1.0, (0, 0), (0, 0))
        task._passes = lambda result, spec: False
        task._ocr_pattern_click_point = lambda frame, patterns, name, roi=None: (
            ((900, 500), "向女神像许愿")
            if prompt_at is not None and clock[0] >= prompt_at
            else (None, "")
        )
        with patch("src.tasks.SquareGoddessTask.monotonic", side_effect=lambda: clock[0]):
            arrived = SquareGoddessTask._wait_for_template(
                task, FANTASIA_SQUARE_TEMPLATE, timeout=10.0, name="梦幻广场", arrival=True
            )
        return arrived, clock[0], logs

    BLACK = np.full((90, 160, 3), 8, np.uint8)
    SQUARE = np.full((90, 160, 3), 140, np.uint8)
    HOME = np.full((90, 160, 3), 200, np.uint8)

    def test_wish_prompt_after_a_long_load_counts_as_arrived(self):
        # 2K 10-15: square up 11 s after the click, its picture unmatched.
        arrived, now, logs = self._run(
            lambda t: self.BLACK if t < 11.0 else self.SQUARE, prompt_at=11.0
        )
        self.assertTrue(arrived)
        self.assertEqual(11.0, now)
        self.assertTrue(any("向女神像许愿" in line for line in logs))

    def test_a_still_screen_that_is_not_the_square_ends_after_stuck_seconds(self):
        from src.utils.wait_limits import STUCK_SECONDS

        arrived, now, _logs = self._run(lambda t: self.HOME)
        self.assertFalse(arrived)
        self.assertTrue(STUCK_SECONDS <= now <= STUCK_SECONDS + 1.0, now)

    def test_an_endless_loading_screen_stops_at_the_cap(self):
        from src.utils.wait_limits import LOADING_MAX_SECONDS

        arrived, now, _logs = self._run(lambda t: self.BLACK)
        self.assertFalse(arrived)
        self.assertTrue(LOADING_MAX_SECONDS <= now <= LOADING_MAX_SECONDS + 1.0, now)

    def test_the_bright_square_splash_after_the_press_is_loading(self):
        # 2K clone 2026-10-19: the bright 「FANTASIA SQUARE」 splash (its saved
        # frame) stood still from the card press until the square ~13 s later.
        from pathlib import Path

        import cv2

        from src.utils.wait_limits import scene

        splash = cv2.imread(
            str(Path(__file__).parent / "fixtures" / "goddess" / "square_splash_2k_clone_thumb.jpg")
        )
        quick_switch_page = np.full(splash.shape, 40, np.uint8)
        arrived, now, _logs = self._run(
            lambda t: splash if t < 13.0 else self.SQUARE,
            prompt_at=13.0,
            before=scene(quick_switch_page),
        )
        self.assertTrue(arrived)
        self.assertEqual(13.0, now)
