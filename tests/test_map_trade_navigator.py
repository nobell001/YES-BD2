"""Map-trade navigator tests (split from test_map_trade.py)."""

import unittest
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from src.tasks.map_trade.models import (
    CARD_BY_ID,
    CollectionMapRole,
    MapPageMode,
    MatchResult,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator_sandbox import NOT_BY_CIRCLE_MESSAGE
from src.tasks.map_trade.navigator import (
    Navigator,
)
from src.tasks.map_trade.navigator_constants import (
    AREA_MAP_BACK_TEMPLATE,
    AREA_MAP_OPEN_RELATIVE_POINT,
    AREA_MAP_TELEPORT_BRIGHT_NEUTRAL_RATIO,
    HAND_TEMPLATE,
    QUICK_SWITCH_TEMPLATE,
    SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT,
    SANDBOX_MAP_SETTLE_SECONDS,
    SANDBOX_MAP_TELEPORT_TEMPLATE,
    SANDBOX_TELEPORT_SKILL_TEMPLATE,
    STORY_CATEGORY_POINT,
    TELEPORT_GENERATION_OCR_TIMEOUT,
    TELEPORT_INTERACTION_CLICK_DELAY,
    TELEPORT_MAP_BACKWARD_TEMPLATE,
    TELEPORT_MAP_FORWARD_TEMPLATE,
    TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI,
    TELEPORT_MAP_RETURN_RELATIVE_POINT,
    TELEPORT_MAP_SKILL_TEMPLATE,
    TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATE,
    TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATES,
    TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI,
    TELEPORT_MAP_TRAVEL_SETTLE_SECONDS,
    AreaMapContext,
    SandboxConfirmation,
)
from src.tasks.map_trade.vision import Vision
from src.utils.press_confirm import press_and_confirm
from src.utils.wait_limits import STUCK_SECONDS

ROOT = Path(__file__).resolve().parents[1]


class NavigatorTest(unittest.TestCase):
    @staticmethod
    def _area_context(
        text: str,
        target_key: str | None = None,
        *,
        left: bool = False,
        right: bool = False,
        candidate_keys: tuple[str, ...] | None = None,
        teleports: tuple[MatchResult, ...] = (),
        page_mode: MapPageMode = MapPageMode.DIRECT_TELEPORT,
    ) -> AreaMapContext:
        match = MatchResult(0.99, (100, 100), (30, 30), pixel_score=0.98)
        keys = (
            candidate_keys if candidate_keys is not None else ((target_key,) if target_key else ())
        )
        return AreaMapContext(
            frame_shape=(1080, 1920, 3),
            raw_text=text,
            normalized_text=text,
            map_page_mode=page_mode,
            candidate_target_keys=keys,
            resolved_target_key=target_key if len(keys) == 1 else None,
            left_arrow=match if left else None,
            right_arrow=match if right else None,
            teleports=teleports,
            overlap_arrow=None,
            back_button=match,
            confirmation_text=(
                "移动魔法阵 传说"
                if page_mode == MapPageMode.GENERATE_TELEPORT
                else "移动魔法阵"
            ),
        )

    def test_ensure_card_menu_home_fallback_uses_shared_recent_cartridge_guard(self):
        calls = []
        task = SimpleNamespace(
            open_cartridge_quick_switcher=lambda **kwargs: (
                calls.append(kwargs) or True
            )
        )
        vision = SimpleNamespace(
            click_stable_template=lambda *_args, **_kwargs: self.fail(
                "the shared entry owns quick-switch clicking"
            )
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        states = iter((ScreenState.UNKNOWN,))
        navigator.classify = lambda: next(states)
        navigator.return_home = lambda: NavigationResult(True, ScreenState.HOME)
        navigator._wait_for_cartridge_home = lambda: True
        navigator._wait_for_quick_switch_page = lambda: True

        result = navigator.ensure_card_menu()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.CARD_MENU, result.state)
        self.assertEqual(1, len(calls))
        self.assertIs(calls[0]["ensure_home"], navigator._wait_for_cartridge_home)
        self.assertIs(
            calls[0]["confirm_quick_switch_page"],
            navigator._wait_for_quick_switch_page,
        )

    def test_area_map_title_resolution_prefers_longest_nested_story_title(self):
        card = CARD_BY_ID["Q_sp1"]

        self.assertEqual(
            (CollectionMapRole.BATTLE_AREA_2.value,),
            Navigator._target_keys_in_text(
                card,
                "卢戈森林深处",
            ),
        )

    def test_real_map_page_fixtures_are_mutually_exclusive_across_resolutions(self):
        fixtures = ROOT / "tests/fixtures/map_trade/map_pages"
        cases = {
            "direct": (
                "移动魔法阵",
                "",
                MapPageMode.DIRECT_TELEPORT,
            ),
            "generate": (
                "移动魔法阵 传说",
                "",
                MapPageMode.GENERATE_TELEPORT,
            ),
            "sandbox_large": (
                "战斗Ⅱ 卢戈森林深处",
                "在战场中查看 探索 0 世界地图",
                MapPageMode.SANDBOX_LARGE_MAP,
            ),
        }
        for height in (720, 1080, 1440, 2160):
            width = height * 16 // 9
            for name, (header, footer, expected) in cases.items():
                with self.subTest(height=height, page=name):
                    source = cv2.imread(str(fixtures / f"{name}.png"), cv2.IMREAD_COLOR)
                    self.assertIsNotNone(source)
                    interpolation = cv2.INTER_AREA if height < 1080 else cv2.INTER_CUBIC
                    frame = cv2.resize(source, (width, height), interpolation=interpolation)
                    matcher = Vision(SimpleNamespace(config={}))
                    vision = SimpleNamespace(
                        match=matcher.match,
                        passes=matcher.passes,
                        simplify=lambda value: value,
                        ocr_text=lambda _frame, label, **_kwargs: (
                            footer if label == "箱庭大地图底部控件" else header
                        ),
                    )
                    navigator = Navigator(
                        SimpleNamespace(info_set=lambda *_args: None),
                        vision,
                    )

                    detection = navigator._detect_map_page_mode(frame)

                    self.assertEqual(expected, detection.mode)

    def test_map_page_identity_reads_the_dedicated_upper_left_roi(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        ocr_calls = []
        navigator = Navigator(
            SimpleNamespace(info_set=lambda *_args: None),
            SimpleNamespace(
                simplify=lambda value: value,
                ocr_text=lambda _frame, label, **kwargs: (
                    ocr_calls.append((label, kwargs.get("relative_roi")))
                    or "移动魔法阵"
                ),
            ),
        )
        navigator._map_page_template_signal = lambda _frame, spec: (
            spec.name in {"交互直传页图标", "传送阵地图向前"},
            spec.name,
        )

        detection = navigator._detect_map_page_mode(frame)

        self.assertEqual(MapPageMode.DIRECT_TELEPORT, detection.mode)
        self.assertEqual(
            [("地图页面左上标题", TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI)],
            ocr_calls,
        )

    def test_map_page_open_wait_rejects_trigger_visual_mode_conflict(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        task = SimpleNamespace(info_set=lambda *_args: None, sleep=lambda *_args: None)
        navigator = Navigator(task, SimpleNamespace(capture=lambda: frame))
        navigator.ensure_small_minimap = lambda: True
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.GENERATE_TELEPORT
        )

        result = navigator._wait_for_sandbox_map_open(
            "传送阵交互按钮",
            expected_mode=MapPageMode.DIRECT_TELEPORT,
        )

        self.assertFalse(result.success)
        self.assertEqual(MapPageMode.GENERATE_TELEPORT, result.map_page_mode)
        self.assertIn("不一致", result.message)

    def test_map_page_open_wait_requires_two_stable_visual_frames(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        captures = []
        sleeps = []
        task = SimpleNamespace(
            info_set=lambda *_args: None,
            sleep=sleeps.append,
        )
        navigator = Navigator(
            task,
            SimpleNamespace(capture=lambda: captures.append(frame) or frame),
        )
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.DIRECT_TELEPORT
        )

        result = navigator._wait_for_sandbox_map_open(
            "传送阵交互按钮",
            expected_mode=MapPageMode.DIRECT_TELEPORT,
        )

        self.assertTrue(result.success)
        self.assertEqual(MapPageMode.DIRECT_TELEPORT, result.map_page_mode)
        self.assertEqual(2, len(captures))
        self.assertEqual([0.15], sleeps)

    def test_header_and_icon_in_one_frame_open_the_direct_map_at_once(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        captures = []
        navigator = Navigator(
            SimpleNamespace(info_set=lambda *_args: None, sleep=lambda *_args: None),
            SimpleNamespace(capture=lambda: captures.append(frame) or frame),
        )
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.DIRECT_TELEPORT,
            header_text="移动魔法阵",
            evidence=("交互直传页图标=pass(m=0.996,p=0.962,z=0.955)",),
        )

        result = navigator._wait_for_sandbox_map_open(
            "传送阵交互按钮", expected_mode=MapPageMode.DIRECT_TELEPORT
        )

        self.assertTrue(result.success)
        self.assertEqual(1, len(captures))

    def test_sandbox_large_map_requires_two_footer_keywords_and_known_title(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        text = {
            "地图页面左上标题": "战斗Ⅱ 卢戈森林深处",
            "箱庭大地图底部控件": "探索 0",
        }
        navigator = Navigator(
            SimpleNamespace(info_set=lambda *_args: None),
            SimpleNamespace(
                simplify=lambda value: value,
                ocr_text=lambda _frame, label, **_kwargs: text[label],
            ),
        )
        navigator._map_page_template_signal = lambda _frame, spec: (
            True,
            f"{spec.name}=pass",
        )

        self.assertEqual(
            MapPageMode.UNKNOWN,
            navigator._detect_map_page_mode(frame).mode,
        )
        text["箱庭大地图底部控件"] = "在战场中查看 探索 0"
        self.assertEqual(
            MapPageMode.SANDBOX_LARGE_MAP,
            navigator._detect_map_page_mode(frame).mode,
        )
        text["地图页面左上标题"] = "未知区域"
        text["箱庭大地图底部控件"] = "在战场中查看 探索 0 世界地图"
        self.assertEqual(
            MapPageMode.UNKNOWN,
            navigator._detect_map_page_mode(frame).mode,
        )

    def test_ensure_area_map_recovers_existing_generate_mode(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        navigator = Navigator(SimpleNamespace(), SimpleNamespace(capture=lambda: frame))
        navigator.ensure_small_minimap = lambda: True
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.GENERATE_TELEPORT
        )

        result = navigator.ensure_area_map()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.AREA_MAP, result.state)
        self.assertEqual(MapPageMode.GENERATE_TELEPORT, result.map_page_mode)

    def test_unknown_page_mode_never_clicks_teleport_destination(self):
        navigator = Navigator(
            SimpleNamespace(info_set=lambda *_args: None),
            SimpleNamespace(
                click_client=lambda *_args, **_kwargs: self.fail(
                    "unknown map mode must never click"
                )
            ),
        )
        teleport = MatchResult(0.99, (100, 100), (40, 40), 0.95, 0.93)

        self.assertFalse(
            navigator._click_teleport_map_destination(
                teleport,
                (1080, 1920, 3),
                page_mode=MapPageMode.UNKNOWN,
            )
        )

    def test_sandbox_large_map_is_rejected_before_area_controls_are_scanned(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        vision = SimpleNamespace(
            ocr_text=lambda *_args, **_kwargs: self.fail(
                "large map must not enter teleport title OCR"
            ),
            match=lambda *_args, **_kwargs: self.fail(
                "large map must not scan teleport controls"
            ),
        )
        navigator = Navigator(
            SimpleNamespace(info_set=lambda *_args: None),
            vision,
        )
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.SANDBOX_LARGE_MAP,
            header_text="战斗Ⅱ 卢戈森林深处",
        )

        context = navigator._area_map_context(frame, CARD_BY_ID["Q_sp1"])

        self.assertFalse(context.is_area_map)
        self.assertEqual(MapPageMode.SANDBOX_LARGE_MAP, context.map_page_mode)
        self.assertEqual((), context.teleports)

    def test_area_map_back_template_uses_scoped_finite_scale_matching(self):
        self.assertEqual("image/green/BackButGe.png", AREA_MAP_BACK_TEMPLATE.file_name)
        self.assertIsNone(AREA_MAP_BACK_TEMPLATE.roi)
        self.assertIsNotNone(AREA_MAP_BACK_TEMPLATE.relative_roi)
        self.assertEqual((0.70, 0.75, 0.80), AREA_MAP_BACK_TEMPLATE.scale_ratios)
        self.assertEqual(0.88, AREA_MAP_BACK_TEMPLATE.threshold)
        self.assertEqual(0.85, AREA_MAP_BACK_TEMPLATE.min_pixel_score)

    def test_area_map_uses_user_confirmed_relative_geometry(self):
        self.assertEqual((289 / 1920, 253 / 1080), AREA_MAP_OPEN_RELATIVE_POINT)
        self.assertEqual(
            (654 / 1920, 946 / 1080, 1268 / 1920, 1021 / 1080),
            TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI,
        )
        self.assertEqual((136 / 1920, 52 / 1080), TELEPORT_MAP_RETURN_RELATIVE_POINT)

    def test_prepare_collection_main_closes_map_when_initial_title_is_main(self):
        card = CARD_BY_ID["Q_sp1"]
        events = []
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator.open_teleport_map_from_sandbox = lambda: NavigationResult(
            True,
            ScreenState.AREA_MAP,
            map_page_mode=MapPageMode.DIRECT_TELEPORT,
        )
        navigator._wait_for_collection_teleport_map = lambda _card: self._area_context(
            card.targets[0].title,
            card.targets[0].key,
            right=True,
        )
        navigator.return_teleport_map_to_sandbox = lambda number: (
            events.append(("return", number)) or NavigationResult(True, ScreenState.SANDBOX)
        )
        navigator._reset_collection_teleport_map_to_main = lambda *_args: self.fail(
            "already-main title must not be paged"
        )

        result = navigator.prepare_collection_main_area(card.card_id)

        self.assertTrue(result.success)
        self.assertEqual([("return", 1)], events)

    def test_prepare_collection_main_pages_to_first_title_then_teleports(self):
        card = CARD_BY_ID["Q_sp1"]
        teleport = MatchResult(0.99, (800, 400), (60, 60), 0.95, 0.93)
        contexts = iter(
            (
                self._area_context(
                    card.targets[1].title,
                    card.targets[1].key,
                    left=True,
                    right=True,
                ),
                self._area_context(
                    card.targets[0].title,
                    card.targets[0].key,
                    right=True,
                    teleports=(teleport,),
                ),
            )
        )
        moves = []
        clicks = []
        generation_calls = []
        vision = SimpleNamespace(
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            )
        )
        navigator = Navigator(SimpleNamespace(), vision)
        navigator.ensure_small_minimap = lambda: True
        navigator.open_teleport_map_from_sandbox = lambda: NavigationResult(
            True,
            ScreenState.AREA_MAP,
            map_page_mode=MapPageMode.DIRECT_TELEPORT,
        )
        navigator._click_teleport_generation = lambda received, shape: (
            generation_calls.append((received, shape)) or True
        )
        initial = self._area_context(
            card.targets[2].title,
            card.targets[2].key,
            left=True,
        )
        navigator._wait_for_collection_teleport_map = lambda _card: initial
        navigator._move_area_map = lambda _card, _context, direction, **_k: (
            moves.append(direction) or next(contexts)
        )
        navigator._wait_for_story_sandbox = lambda number: NavigationResult(
            True,
            ScreenState.SANDBOX,
            f"Q_sp{number}",
        )
        arrivals = []
        navigator._confirm_collection_arrival = lambda received_card, target: (
            arrivals.append((received_card.card_id, target.key))
            or NavigationResult(True, ScreenState.SANDBOX, target.title)
        )

        result = navigator.prepare_collection_main_area(card.card_id)

        self.assertTrue(result.success)
        self.assertEqual(["left", "left"], moves)
        self.assertEqual(
            [(teleport.center, (1080, 1920, 3), 0.0)],
            clicks,
        )
        self.assertEqual([], generation_calls)
        self.assertEqual([(card.card_id, card.targets[0].key)], arrivals)

    def test_advance_collection_map_moves_back_exactly_one_confirmed_page(self):
        card = CARD_BY_ID["Q_sp1"]
        current, target = card.targets[1:]
        teleport = MatchResult(0.99, (1000, 500), (60, 60), 0.95, 0.93)
        clicks = []
        moves = []
        vision = SimpleNamespace(
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(SimpleNamespace(), vision)
        navigator.ensure_small_minimap = lambda: True
        navigator.open_teleport_map_from_sandbox = lambda: NavigationResult(
            True,
            ScreenState.AREA_MAP,
            "已点击箱庭5号传送阵技能",
            map_page_mode=MapPageMode.GENERATE_TELEPORT,
        )
        generation_calls = []
        navigator._click_teleport_generation = lambda received, shape: (
            generation_calls.append((received, shape)) or True
        )
        navigator._wait_for_collection_teleport_map = lambda _card: self._area_context(
            current.title,
            current.key,
            left=True,
            right=True,
            page_mode=MapPageMode.GENERATE_TELEPORT,
        )
        navigator._move_area_map = lambda _card, _context, direction, **_k: (
            moves.append(direction)
            or self._area_context(
                target.title,
                target.key,
                left=True,
                teleports=(teleport,),
                page_mode=MapPageMode.GENERATE_TELEPORT,
            )
        )
        navigator._wait_for_story_sandbox = lambda number: NavigationResult(
            True,
            ScreenState.SANDBOX,
            f"Q_sp{number}",
        )
        arrivals = []
        navigator._confirm_collection_arrival = lambda received_card, received_target: (
            arrivals.append((received_card.card_id, received_target.key))
            or NavigationResult(True, ScreenState.SANDBOX, received_target.title)
        )

        result = navigator.advance_collection_map(card.card_id, current, target)

        self.assertTrue(result.success)
        self.assertEqual(["right"], moves)
        self.assertEqual([], clicks)
        self.assertEqual([(teleport, (1080, 1920, 3))], generation_calls)
        self.assertEqual([(card.card_id, target.key)], arrivals)

    def test_advance_to_town_uses_town_nav_entry(self):
        card = CARD_BY_ID["Q_sp14"]
        main, left_corridor, _central = card.targets
        trips = []
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator._travel_via_nav_menu = lambda *entries: trips.extend(entries) or entries[0]
        navigator.current_collection_target = lambda _card: main.key
        navigator._open_teleport_map_anywhere = lambda *_args: self.fail("teleport map opened")

        result = navigator.advance_collection_map(card.card_id, left_corridor, main)

        self.assertTrue(result.success)
        self.assertEqual(["艾琳"], trips)

    def test_advance_to_town_falls_back_to_teleport_map(self):
        card = CARD_BY_ID["Q_sp14"]
        main, left_corridor, _central = card.targets
        opened = []
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator._status = lambda *_args: None
        navigator._travel_via_nav_menu = lambda *_entries: None
        navigator._open_teleport_map_anywhere = lambda *_args: (
            opened.append(True) or NavigationResult(False, ScreenState.SANDBOX, "无传送阵")
        )

        result = navigator.advance_collection_map(card.card_id, left_corridor, main)

        self.assertFalse(result.success)
        self.assertEqual([True], opened)
        self.assertIn("无传送阵", result.message)

    def test_map_without_a_circle_is_reached_through_its_walk_neighbour(self):
        # Leo 2026-10-20: ch14 with 左侧回廊 already done went town -> 中央回廊
        # by the teleport map (「未识别到传送阵地图传送阵」) and was skipped.
        for card_id in ("Q_sp14", "Q_sp6", "Q_cp3"):
            with self.subTest(card=card_id):
                card = CARD_BY_ID[card_id]
                main, middle, last = card.targets
                legs = []
                navigator = Navigator(SimpleNamespace(), SimpleNamespace())
                navigator._status = lambda *_args: None
                navigator._travel_via_nav_menu = lambda *_entries: None

                def teleport(*_args, legs=legs):
                    legs.append("teleport")
                    return NavigationResult(False, ScreenState.SANDBOX, "stop")

                navigator._open_teleport_map_anywhere = teleport
                original = navigator.advance_collection_map

                def advance(cid, current, target, legs=legs, original=original):
                    if target.key == middle.key:
                        legs.append(("teleport", current.key, target.key))
                        return NavigationResult(True, ScreenState.SANDBOX, "")
                    return original(cid, current, target)

                navigator.advance_collection_map = advance
                navigator._walk_to_collection_map = lambda _card, here, there, legs=legs: (
                    legs.append(("walk", here.key, there.key))
                    or NavigationResult(True, ScreenState.SANDBOX, "")
                )

                result = navigator.advance_collection_map(card_id, main, last)

                self.assertTrue(result.success)
                self.assertEqual(
                    [
                        ("teleport", main.key, middle.key),
                        ("walk", middle.key, last.key),
                    ],
                    legs,
                )

    def test_failed_neighbour_leg_names_both_maps(self):
        card = CARD_BY_ID["Q_sp14"]
        main, middle, last = card.targets
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator._status = lambda *_args: None
        navigator._open_teleport_map_anywhere = lambda *_args: NavigationResult(
            False, ScreenState.SANDBOX, "无传送阵"
        )
        navigator._walk_to_collection_map = lambda *_a: self.fail("walked without arriving")

        result = navigator.advance_collection_map(card.card_id, main, last)

        self.assertFalse(result.success)
        self.assertIn(middle.title, result.message)
        self.assertIn(last.title, result.message)

    def test_map_with_a_circle_still_uses_the_teleport_map(self):
        card = CARD_BY_ID["Q_sp14"]
        main, middle, _last = card.targets
        self.assertIsNone(Navigator._walk_neighbour(card, main, middle))

    @staticmethod
    def _menu_navigator(reads):
        """A navigator whose ≡ menu OCR returns ``reads`` one after another."""

        reads = iter(reads)

        def boxes(_frame, _name, _roi, **_kwargs):
            return [
                SimpleNamespace(name=text, x=300, y=100 + 60 * row, width=80, height=30)
                for row, text in enumerate(next(reads))
            ]

        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
            ocr_boxes=boxes,
            simplify=lambda text: text,
        )
        return Navigator(SimpleNamespace(sleep=lambda *_a: None), vision)

    def test_nav_menu_prefers_hunting_ground(self):
        navigator = self._menu_navigator(
            [["旅馆", "狩猎场", "艾琳"], ["旅馆", "狩猎场", "艾琳"]]
        )

        entry, point, _shape = navigator._nav_menu_choice(("狩猎场", "艾琳"))

        self.assertEqual("狩猎场", entry)
        self.assertEqual((340, 175), point)

    def test_nav_menu_without_hunting_ground_takes_airin(self):
        # Leo 2026-09-30: "選單沒有狩獵場 就一律直接傳去艾琳" (chapter 15's menu).
        menu = ["旅馆", "招募", "商店", "艾琳"]
        navigator = self._menu_navigator([menu, menu])

        entry, point, _shape = navigator._nav_menu_choice(("狩猎场", "艾琳"))

        self.assertEqual("艾琳", entry)
        self.assertEqual((340, 295), point)

    def test_nav_menu_is_read_again_while_it_slides_in(self):
        navigator = self._menu_navigator([["艾琳"], ["狩猎场", "艾琳"]])

        entry, _point, _shape = navigator._nav_menu_choice(("狩猎场", "艾琳"))

        self.assertEqual("狩猎场", entry)

    def test_nav_menu_takes_hunting_ground_with_one_character_misread(self):
        menu = ["旅馆", "狩猎扬", "快速狩猎", "艾琳"]
        navigator = self._menu_navigator([menu, menu])

        entry, point, _shape = navigator._nav_menu_choice(("狩猎场", "艾琳"))

        self.assertEqual("狩猎场", entry)
        self.assertEqual((340, 175), point)

    def test_nav_menu_is_read_at_twice_the_size_before_giving_up(self):
        reads = []

        def boxes(_frame, _name, _roi, ocr_scale=1.0):
            reads.append(ocr_scale)
            text = "狩猎场" if ocr_scale == 2.0 else "狩"
            return [SimpleNamespace(name=text, x=300, y=100, width=80, height=30)]

        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
            ocr_boxes=boxes,
            simplify=lambda text: text,
        )
        navigator = Navigator(SimpleNamespace(sleep=lambda *_a: None), vision)
        with patch("src.tasks.map_trade.navigator_sandbox.MERCHANT_NAV_MENU_OCR_TIMEOUT", 0.0):
            entry, _point, _shape = navigator._nav_menu_choice(("狩猎场", "艾琳"))

        self.assertEqual("狩猎场", entry)
        self.assertEqual([1.0, 2.0], reads)

    def test_nav_menu_without_either_entry_gives_up(self):
        # Read at 1× and once more at 2×.
        navigator = self._menu_navigator([["旅馆", "商店"], ["旅馆", "商店"]])

        with patch("src.tasks.map_trade.navigator_sandbox.MERCHANT_NAV_MENU_OCR_TIMEOUT", 0.0):
            self.assertIsNone(navigator._nav_menu_choice(("狩猎场", "艾琳")))

    def test_restart_without_hunting_ground_starts_at_airin_in_town(self):
        card = CARD_BY_ID["Q_sp15"]
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator._click_sandbox_teleport_interaction = lambda *a, **k: False
        navigator._travel_to_hunting_ground = lambda: "艾琳"
        navigator.current_collection_target = lambda _card: card.targets[0].key
        navigator._open_teleport_map_anywhere = lambda *_args: self.fail("teleport map opened")

        result = navigator.prepare_collection_main_area(card.card_id, via_hunting_ground=True)

        self.assertTrue(result.success)
        self.assertIn("艾琳", result.message)

    def _circle_page_navigator(self, opens):
        """Hand always read; ``opens`` answers each wait for the 传送页."""
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator._status = lambda *_args: None
        keys, hands, looked = [], [], []
        navigator.task = SimpleNamespace(
            tap_key=lambda key, after_sleep=0.0: keys.append(key) or True,
            log_info=lambda *_a, **_k: None,
        )
        navigator.ensure_small_minimap = lambda: True
        navigator._click_sandbox_teleport_interaction = lambda *a, **k: hands.append(True) or True
        answers = iter(opens)
        navigator._wait_for_sandbox_map_open = lambda *a, **k: next(answers)
        navigator._wait_for_current_sandbox = lambda **_k: looked.append(True) or NavigationResult(
            True, ScreenState.SANDBOX
        )
        return navigator, keys, hands, looked

    def test_circle_page_not_opening_is_opened_again_then_falls_back(self):
        # Leo 2026-10-20 (v0.2.2, 第8章): on the circle, the hand was pressed
        # but no teleport page opened, and the card was skipped there.  「應該
        # 要確保他打開」: the hand once more, then F; the ≡ menu only after.
        card = CARD_BY_ID["Q_sp8"]
        missed = NavigationResult(
            False, ScreenState.UNKNOWN, "传送阵交互按钮后未稳定确认direct_teleport"
        )
        navigator, keys, hands, looked = self._circle_page_navigator([missed] * 3)
        trips = []
        navigator._travel_to_hunting_ground = lambda: trips.append(True) or "艾琳"
        navigator.current_collection_target = lambda _card: card.targets[0].key

        result = navigator.prepare_collection_main_area(card.card_id, via_hunting_ground=True)

        self.assertTrue(result.success, result.message)
        self.assertEqual(2, len(hands))
        self.assertEqual(["F"], keys)
        self.assertEqual(3, len(looked))
        self.assertEqual([True], trips)

    def test_circle_page_opens_on_the_second_hand_press(self):
        missed = NavigationResult(False, ScreenState.UNKNOWN, "未稳定确认direct_teleport")
        opened = NavigationResult(
            True, ScreenState.AREA_MAP, map_page_mode=MapPageMode.DIRECT_TELEPORT
        )
        navigator, keys, hands, _looked = self._circle_page_navigator([missed, opened])

        result = navigator.open_teleport_map_from_sandbox()

        self.assertTrue(result.success)
        self.assertEqual(2, len(hands))
        self.assertEqual([], keys)

    def test_circle_page_wrong_page_is_closed_before_f(self):
        wrong = NavigationResult(
            False,
            ScreenState.SANDBOX_MAP,
            "入口与实际地图页面不一致",
            map_page_mode=MapPageMode.SANDBOX_LARGE_MAP,
        )
        opened = NavigationResult(
            True, ScreenState.AREA_MAP, map_page_mode=MapPageMode.DIRECT_TELEPORT
        )
        navigator, keys, hands, _looked = self._circle_page_navigator([wrong, wrong, opened])
        closed = []
        navigator._close_confirmed_map_page = lambda modes, **_k: closed.append(modes) or (
            NavigationResult(True, ScreenState.SANDBOX)
        )

        result = navigator.open_teleport_map_from_sandbox()

        self.assertTrue(result.success)
        self.assertEqual([{MapPageMode.SANDBOX_LARGE_MAP}] * 2, closed)
        self.assertEqual(["F"], keys)

    def test_circle_page_f_is_never_sent_off_the_field(self):
        missed = NavigationResult(False, ScreenState.UNKNOWN, "未稳定确认direct_teleport")
        navigator, keys, hands, _looked = self._circle_page_navigator([missed])
        navigator._wait_for_current_sandbox = lambda **_k: NavigationResult(
            False, ScreenState.UNKNOWN
        )

        result = navigator.open_teleport_map_from_sandbox()

        self.assertFalse(result.success)
        self.assertEqual(1, len(hands))
        self.assertEqual([], keys)

    def test_teleport_map_after_airin_walks_to_the_town_circle(self):
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator._status = lambda *_args: None
        failed = NavigationResult(False, ScreenState.SANDBOX, "不在传送阵旁")
        walked = NavigationResult(
            True, ScreenState.AREA_MAP, map_page_mode=MapPageMode.DIRECT_TELEPORT
        )
        walks = iter((failed, walked))
        navigator.open_teleport_map_from_sandbox = lambda: failed
        navigator._walk_to_sandbox_teleport_interaction = lambda: next(walks)
        navigator._travel_to_hunting_ground = lambda: "艾琳"
        navigator._click_sandbox_teleport_interaction = lambda *a, **k: False

        result = navigator._open_teleport_map_anywhere()

        self.assertTrue(result.success)
        self.assertEqual(MapPageMode.DIRECT_TELEPORT, result.map_page_mode)

    def _hunting_ground_navigator(self, opened_after_key):
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator._status = lambda *_args: None
        keys = []
        navigator.task = SimpleNamespace(
            tap_key=lambda key, after_sleep=0.0: keys.append(key) or True,
            log_info=lambda *_a, **_k: None,
        )
        navigator.open_teleport_map_from_sandbox = lambda: NavigationResult(
            False, ScreenState.SANDBOX, NOT_BY_CIRCLE_MESSAGE
        )
        navigator._wait_for_sandbox_map_open = lambda *_a, **_k: opened_after_key
        return navigator, keys

    def test_hunting_ground_hand_not_read_presses_f(self):
        # Leo 2026-10-17 「傳到狩獵場一定會有手勢可以按 沒辨識到就按f」.
        opened = NavigationResult(
            True, ScreenState.AREA_MAP, map_page_mode=MapPageMode.DIRECT_TELEPORT
        )
        navigator, keys = self._hunting_ground_navigator(opened)

        result = navigator._open_teleport_map_at_hunting_ground()

        self.assertTrue(result.success)
        self.assertEqual(["F"], keys)

    def test_hunting_ground_f_without_map_names_the_step(self):
        navigator, keys = self._hunting_ground_navigator(
            NavigationResult(False, ScreenState.UNKNOWN, "没打开")
        )

        result = navigator._open_teleport_map_at_hunting_ground()

        self.assertFalse(result.success)
        self.assertEqual(["F"], keys)
        self.assertIn("按 F 后也没打开传送阵地图", result.message)

    def test_hunting_ground_hand_pressed_but_map_failed_sends_no_f(self):
        navigator, keys = self._hunting_ground_navigator(None)
        navigator.open_teleport_map_from_sandbox = lambda: NavigationResult(
            False, ScreenState.UNKNOWN, "点击传送阵交互按钮后未确认传送阵地图"
        )

        result = navigator._open_teleport_map_at_hunting_ground()

        self.assertFalse(result.success)
        self.assertEqual([], keys)

    def test_restart_via_hunting_ground_uses_the_f_fallback(self):
        card = CARD_BY_ID["Q_sp10"]
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator._click_sandbox_teleport_interaction = lambda *a, **k: False
        navigator._travel_to_hunting_ground = lambda: "狩猎场"
        failed = NavigationResult(False, ScreenState.SANDBOX, "按 F 后也没打开传送阵地图")
        calls = []
        navigator._open_teleport_map_at_hunting_ground = lambda: calls.append(1) or failed

        result = navigator.prepare_collection_main_area(card.card_id, via_hunting_ground=True)

        self.assertEqual([1], calls)
        self.assertIs(failed, result)

    def test_no_way_to_a_circle_names_the_last_failure(self):
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator._status = lambda *_args: None
        navigator.open_teleport_map_from_sandbox = lambda: NavigationResult(
            False, ScreenState.SANDBOX, NOT_BY_CIRCLE_MESSAGE
        )
        navigator._walk_to_sandbox_teleport_interaction = lambda: NavigationResult(
            False, ScreenState.SANDBOX, "地图上没找到传送门"
        )
        navigator._travel_to_hunting_ground = lambda: None

        result = navigator._open_teleport_map_anywhere()

        self.assertFalse(result.success)
        self.assertIn("地图上没找到传送门", result.message)
        self.assertIn("小地图导航也没能去狩猎场或艾琳", result.message)

    def test_teleport_map_page_arrows_are_strict_and_directional(self):
        self.assertEqual("image/green/TpMapLeft.png", TELEPORT_MAP_FORWARD_TEMPLATE.file_name)
        self.assertEqual("image/green/TpMapRight.png", TELEPORT_MAP_BACKWARD_TEMPLATE.file_name)
        for spec in (TELEPORT_MAP_FORWARD_TEMPLATE, TELEPORT_MAP_BACKWARD_TEMPLATE):
            with self.subTest(spec=spec.name):
                # 0.93: the 1080p 桌面分身 卡勒塔市 left arrow read 0.948.
                self.assertEqual(0.93, spec.threshold)
                self.assertEqual(0.85, spec.min_pixel_score)
                self.assertEqual(0.90, spec.min_zncc_score)
                self.assertEqual(0.93, spec.minimum_safe_threshold)
                self.assertIsNone(spec.roi)
                self.assertIsNone(spec.relative_roi)

    def test_sandbox_teleport_skill_is_separate_from_map_skill(self):
        self.assertEqual(
            "image/green/Skill3-4GE.png",
            SANDBOX_TELEPORT_SKILL_TEMPLATE.file_name,
        )
        self.assertEqual(0.95, SANDBOX_TELEPORT_SKILL_TEMPLATE.threshold)
        self.assertEqual(0.85, SANDBOX_TELEPORT_SKILL_TEMPLATE.min_pixel_score)
        self.assertEqual(0.85, SANDBOX_TELEPORT_SKILL_TEMPLATE.min_zncc_score)
        self.assertNotIn(
            SANDBOX_TELEPORT_SKILL_TEMPLATE,
            TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATES,
        )

    def test_sandbox_map_teleport_template_uses_sandbox_asset_name(self):
        self.assertEqual("箱庭地图传送阵模板", SANDBOX_MAP_TELEPORT_TEMPLATE.name)
        self.assertEqual(
            "image/green/SandboxNviTpCircleMapGE.png",
            SANDBOX_MAP_TELEPORT_TEMPLATE.file_name,
        )
        self.assertNotEqual(
            SANDBOX_MAP_TELEPORT_TEMPLATE.file_name,
            TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATE.file_name,
        )
        for file_name in (
            "image/SandboxTpCircleMap.png",
            "image/green/SandboxNviTpCircleMapGE.png",
            "image/green/SandboxTpCircleMapGE.png",
            "image/green/TpCircleMapNewGE.png",
        ):
            with self.subTest(file_name=file_name):
                self.assertTrue((ROOT / "recognition-assets/template-assets" / file_name).is_file())

    def test_teleport_map_route_prefers_interaction_center(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        hand = MatchResult(
            0.968,
            (820, 470),
            (44, 43),
            pixel_score=0.92,
            zncc_score=0.90,
        )
        clicks = []
        task = SimpleNamespace(
            info_set=lambda *_args: None,
            sleep=lambda *_args: self.fail("a passing interaction must click immediately"),
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            # The hand goes once the press lands (the map opens).
            match=lambda received, spec: (
                self.assertIs(received, frame)
                or self.assertIs(spec, HAND_TEMPLATE)
                or (MatchResult(0.1, (0, 0), (0, 0)) if clicks else hand)
            ),
            passes=lambda result, spec: result is hand and spec is HAND_TEMPLATE,
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._wait_for_sandbox_map_open = lambda *_args, **_kwargs: NavigationResult(
            True,
            ScreenState.AREA_MAP,
            "交互按钮已确认传送阵地图",
            map_page_mode=MapPageMode.DIRECT_TELEPORT,
        )
        navigator._click_sandbox_teleport_skill = lambda: self.fail(
            "interaction route must not click the fifth skill"
        )

        result = navigator.open_teleport_map_from_sandbox()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.AREA_MAP, result.state)
        self.assertEqual(MapPageMode.DIRECT_TELEPORT, result.map_page_mode)
        self.assertEqual(
            [(hand.center, frame.shape, TELEPORT_INTERACTION_CLICK_DELAY)],
            clicks,
        )

    def test_teleport_map_route_never_presses_the_portal_skill(self):
        # Leo 2026-10-10: 「我是說技能 不要傳送陣」.  Even a perfect portal skill
        # on the bar is not pressed; without the 交互 button the call fails so
        # the caller walks to a circle or uses the ≡ menu.
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        skill = MatchResult(0.99, (1760, 790), (44, 43), pixel_score=0.95, zncc_score=0.95)
        clicks = []
        task = SimpleNamespace(
            info_set=lambda *_args: None,
            sleep=lambda *_args: None,
            operate_click=lambda *args, **kwargs: clicks.append((args, kwargs)),
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            match=lambda _frame, _spec: skill,
            passes=lambda *_args: True,
            click_client=lambda *args, **kwargs: clicks.append((args, kwargs)),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._click_sandbox_teleport_interaction = lambda: False
        navigator._wait_for_sandbox_map_open = lambda *_args, **_kwargs: self.fail(
            "no portal map may open without the 交互 button"
        )

        result = navigator.open_teleport_map_from_sandbox()

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.SANDBOX, result.state)
        self.assertIn("不用传送阵技能", result.message)
        self.assertEqual([], clicks)
        self.assertFalse(hasattr(navigator, "_click_sandbox_teleport_skill"))

    def test_teleport_skill_failure_ocr_is_explicit_and_enters_walk_fallback(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        task = SimpleNamespace(info_set=lambda *_args: None, sleep=lambda *_args: None)
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda received, name: (
                self.assertIs(received, frame)
                or self.assertEqual("箱庭5号传送阵技能失败", name)
                or "无法在魔法阵附近使用天赋技能"
            ),
            simplify=lambda value: value,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator.classify = lambda _frame=None: ScreenState.SANDBOX

        result = navigator._wait_for_sandbox_map_open(
            "箱庭5号传送阵技能",
            expected_mode=MapPageMode.GENERATE_TELEPORT,
            detect_skill_failure=True,
        )

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.SANDBOX, result.state)
        self.assertIn("魔法阵附近", result.message)
        self.assertTrue(navigator._sandbox_teleport_skill_failure_matches(result.message))

    def test_walk_fallback_selects_unique_navigation_teleport_then_interacts(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        teleport = MatchResult(
            0.96,
            (500, 300),
            (40, 40),
            pixel_score=0.90,
            zncc_score=0.88,
        )
        hand = MatchResult(
            0.97,
            (820, 470),
            (44, 43),
            pixel_score=0.92,
            zncc_score=0.90,
        )
        clicks = []
        task = SimpleNamespace(
            info_set=lambda *_args: None,
            sleep=lambda *_args: None,
            config={"加载页面等待秒数": 15.0},
        )

        def match(received, spec):
            self.assertIs(received, frame)
            self.assertIs(spec, HAND_TEMPLATE)
            # The hand goes once its press lands (the map opens).
            pressed = any(point == hand.center for point, _shape, _sleep in clicks)
            return MatchResult(0.1, (0, 0), (0, 0)) if pressed else hand

        vision = SimpleNamespace(
            capture=lambda: frame,
            match=match,
            match_all=lambda received, spec, **_kwargs: (
                self.assertIs(received, frame)
                or self.assertIs(spec, SANDBOX_MAP_TELEPORT_TEMPLATE)
                or (teleport,)
            ),
            threshold_for=lambda spec: spec.threshold,
            passes=lambda result, spec: result in (hand, teleport),
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._open_field_map = lambda: "安全 测试镇"
        navigator._click_sandbox_navigation_map = lambda: self.fail("minimap opened the map")
        navigator._sandbox_navigation_page_has_keyword = lambda _frame: True
        menu_calls = []

        def click_menu(_frame):
            menu_calls.append(True)
            return len(menu_calls) == 1

        navigator._click_sandbox_navigation_menu_teleport = click_menu
        navigator._click_sandbox_navigation_destination_confirmation = lambda _frame: True
        navigator._wait_for_sandbox_map_open = lambda *_args, **_kwargs: NavigationResult(
            True,
            ScreenState.AREA_MAP,
            "徒步交互已确认传送阵地图",
            map_page_mode=MapPageMode.DIRECT_TELEPORT,
        )

        result = navigator._walk_to_sandbox_teleport_interaction()

        self.assertTrue(result.success)
        self.assertEqual(
            [
                (teleport.center, frame.shape, 3.0),
                (hand.center, frame.shape, TELEPORT_INTERACTION_CLICK_DELAY),
            ],
            clicks,
        )

    def test_walk_fallback_destination_confirmation_clicks_ocr_center(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        box = SimpleNamespace(name="确认", x=700, y=500, width=120, height=40)
        task = SimpleNamespace(
            info_set=lambda *_args: None, sleep=lambda *_args: None, log_info=lambda *_a: None
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda received, name: (
                self.assertIs(received, frame)
                or self.assertEqual("箱庭徒步导航传送阵确认", name)
                # the dialog closes once its button was pressed
                or ([] if clicks else [box])
            ),
            simplify=lambda value: value,
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertTrue(navigator._click_sandbox_navigation_destination_confirmation(frame))
        self.assertEqual([((760, 520), frame.shape, 0.25)], clicks)

    def test_teleport_generation_clicks_unique_white_center_then_generate_box_center(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        teleport = MatchResult(0.99, (800, 400), (60, 60), 0.95, 0.93)
        clicks = []
        ocr_frames = []
        boxes = [
            SimpleNamespace(name="生成魔法阵", x=880, y=430, width=120, height=40),
            SimpleNamespace(name="取消", x=740, y=620, width=220, height=48),
            SimpleNamespace(name="生成5", x=990, y=620, width=220, height=48),
        ]
        task = SimpleNamespace(info_set=lambda *_args: None, sleep=lambda *_args: None)
        vision = SimpleNamespace(
            capture=lambda: ocr_frames.append(frame) or frame,
            ocr_boxes=lambda received, name: (
                self.assertIs(received, frame) or self.assertEqual("传送阵生成确认", name) or boxes
            ),
            simplify=lambda value: value,
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        self.assertTrue(navigator._click_teleport_generation(teleport, frame.shape))
        self.assertEqual(
            [
                (teleport.center, frame.shape, 0.5),
                ((1100, 644), frame.shape, TELEPORT_MAP_TRAVEL_SETTLE_SECONDS),
            ],
            clicks,
        )
        self.assertEqual([frame], ocr_frames)

    def test_teleport_generation_rejects_missing_and_selects_strongest_multiple_candidate(self):
        weaker = MatchResult(0.989, (800, 400), (60, 60), 0.932, 0.947)
        stronger = MatchResult(0.994, (1038, 659), (60, 60), 0.949, 0.973)
        task = SimpleNamespace(info_set=lambda *_args: None)
        vision = SimpleNamespace(click_client=lambda *_args, **_kwargs: None)
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        card = CARD_BY_ID["Q_sp1"]
        missing = self._area_context(
            card.targets[1].title,
            card.targets[1].key,
            teleports=(),
        )
        result = navigator._click_collection_destination(card, card.targets[1], missing)
        self.assertFalse(result.success)
        self.assertIn("未识别到", result.message)

        selected = []
        navigator._click_teleport_map_destination = (
            lambda teleport, _shape, *, page_mode: (
                self.assertEqual(MapPageMode.DIRECT_TELEPORT, page_mode)
                or selected.append(teleport)
                or True
            )
        )
        navigator._wait_for_story_sandbox = lambda number: NavigationResult(
            True,
            ScreenState.SANDBOX,
            f"Q_sp{number}",
        )
        navigator._confirm_collection_arrival = lambda _card, _target: NavigationResult(
            True,
            ScreenState.SANDBOX,
        )
        multiple = self._area_context(
            card.targets[1].title,
            card.targets[1].key,
            teleports=(weaker, stronger),
        )
        result = navigator._click_collection_destination(card, card.targets[1], multiple)
        self.assertTrue(result.success)
        self.assertEqual([stronger], selected)

    def test_collection_destination_fails_when_arrival_map_does_not_match(self):
        card = CARD_BY_ID["Q_sp1"]
        target = card.targets[1]
        teleport = MatchResult(0.99, (800, 400), (60, 60), 0.95, 0.93)
        navigator = Navigator(
            SimpleNamespace(info_set=lambda *_args: None),
            SimpleNamespace(click_client=lambda *_args, **_kwargs: None),
        )
        navigator._click_teleport_map_destination = lambda *_args, **_kwargs: True
        navigator._wait_for_story_sandbox = lambda _number: NavigationResult(
            True,
            ScreenState.SANDBOX,
        )
        navigator._confirm_collection_arrival = lambda _card, _target: NavigationResult(
            False,
            ScreenState.AREA_MAP,
            "到达后地图不符：目标=卢戈森林，实际=battle_area_2",
        )

        result = navigator._click_collection_destination(
            card,
            target,
            self._area_context(
                target.title,
                target.key,
                teleports=(teleport,),
            ),
        )

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.AREA_MAP, result.state)
        self.assertIn("到达后地图不符", result.message)

    def test_confirm_collection_arrival_checks_actual_area_map_title(self):
        card = CARD_BY_ID["Q_sp1"]
        target = card.targets[1]
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        navigator._open_field_map = lambda: None  # teleport-map fallback path
        navigator.ensure_area_map = lambda: NavigationResult(
            True,
            ScreenState.AREA_MAP,
            map_page_mode=MapPageMode.DIRECT_TELEPORT,
        )
        navigator._capture_area_map_context = lambda _card: self._area_context(
            card.targets[2].title,
            card.targets[2].key,
        )
        navigator._close_area_map = lambda _context: self.fail(
            "a mismatched arrival map must remain open for failure handling"
        )

        result = navigator._confirm_collection_arrival(card, target)

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.AREA_MAP, result.state)
        self.assertIn(target.title, result.message)
        self.assertIn(card.targets[2].key, result.message)

    def test_confirm_collection_arrival_reads_the_field_map_first(self):
        card = CARD_BY_ID["Q_sp1"]
        target = card.targets[1]
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator.ensure_small_minimap = lambda: True
        closed = []
        navigator._close_field_map = lambda: closed.append(True)
        navigator.ensure_area_map = lambda: self.fail("the teleport map is not reopened")

        navigator._open_field_map = lambda: "战斗Ⅰ" + target.title
        self.assertTrue(navigator._confirm_collection_arrival(card, target).success)
        navigator._open_field_map = lambda: "战斗Ⅱ" + card.targets[2].title
        wrong = navigator._confirm_collection_arrival(card, target)
        self.assertFalse(wrong.success)
        self.assertIn(target.title, wrong.message)
        self.assertEqual([True, True], closed)

    def test_teleport_generation_rejects_missing_keyword_without_generate_click(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        teleport = MatchResult(0.99, (800, 400), (60, 60), 0.95, 0.93)
        clicks = []
        task = SimpleNamespace(info_set=lambda *_args: None, sleep=lambda *_args: None)
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda *_args: [
                SimpleNamespace(name="生成魔法阵", x=880, y=430, width=120, height=40),
                SimpleNamespace(name="取消", x=740, y=620, width=220, height=48),
            ],
            simplify=lambda value: value,
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        with patch(
            "src.tasks.map_trade.navigator_sandbox.monotonic",
            side_effect=(100.0, 100.0, 109.0),
        ):
            result = navigator._click_teleport_generation(
                teleport,
                frame.shape,
                timeout=TELEPORT_GENERATION_OCR_TIMEOUT,
            )

        self.assertFalse(result)
        self.assertEqual([(teleport.center, frame.shape, 0.5)], clicks)

    def test_teleport_generation_rejects_ambiguous_generate_button(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        teleport = MatchResult(0.99, (800, 400), (60, 60), 0.95, 0.93)
        clicks = []
        task = SimpleNamespace(info_set=lambda *_args: None, sleep=lambda *_args: None)
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda *_args: [
                SimpleNamespace(name="生成魔法阵", x=880, y=430, width=120, height=40),
                SimpleNamespace(name="取消", x=740, y=620, width=220, height=48),
                SimpleNamespace(name="生成5", x=990, y=620, width=220, height=48),
                SimpleNamespace(name="生成5", x=1230, y=620, width=220, height=48),
            ],
            simplify=lambda value: value,
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True

        with patch(
            "src.tasks.map_trade.navigator_sandbox.monotonic",
            side_effect=(100.0, 100.0, 109.0),
        ):
            result = navigator._click_teleport_generation(
                teleport,
                frame.shape,
                timeout=TELEPORT_GENERATION_OCR_TIMEOUT,
            )

        self.assertFalse(result)
        self.assertEqual([(teleport.center, frame.shape, 0.5)], clicks)

    def test_return_teleport_map_clicks_confirmed_point_and_reuses_stable_sandbox_wait(self):
        clicks = []
        confirmed_numbers = []
        task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
        )
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        vision = SimpleNamespace(
            capture=lambda: frame,
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.DIRECT_TELEPORT
        )
        navigator._wait_for_story_sandbox = lambda number, **_kwargs: (
            confirmed_numbers.append(number)
            or NavigationResult(True, ScreenState.SANDBOX, f"Q_sp{number}")
        )

        result = navigator.return_teleport_map_to_sandbox(1)

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.SANDBOX, result.state)
        self.assertEqual([1], confirmed_numbers)
        self.assertEqual(
            [(*TELEPORT_MAP_RETURN_RELATIVE_POINT, SANDBOX_MAP_SETTLE_SECONDS)],
            clicks,
        )

    def test_return_teleport_map_prefers_recognized_back_button_center(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        back = MatchResult(0.98, (110, 35), (40, 40), 0.95, 0.92)
        clicks = []
        task = SimpleNamespace(
            operate_click=lambda *_args, **_kwargs: self.fail(
                "recognized back button must win over the fallback point"
            )
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            match=lambda _frame, spec: (
                back if spec is AREA_MAP_BACK_TEMPLATE else MatchResult(-1.0, (0, 0), (0, 0))
            ),
            passes=lambda result, _spec: result is back,
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.GENERATE_TELEPORT
        )
        navigator._wait_for_story_sandbox = lambda number, **_kwargs: NavigationResult(
            True,
            ScreenState.SANDBOX,
            f"Q_sp{number}",
        )

        result = navigator.return_teleport_map_to_sandbox(1)

        self.assertTrue(result.success)
        self.assertEqual(
            [(back.center, frame.shape, SANDBOX_MAP_SETTLE_SECONDS)],
            clicks,
        )

    def test_close_sandbox_large_map_uses_its_own_confirmed_relative_point(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.SANDBOX_LARGE_MAP
        )
        navigator._wait_for_current_sandbox = lambda **_kwargs: NavigationResult(
            True,
            ScreenState.SANDBOX,
        )

        result = navigator._close_confirmed_map_page(
            {MapPageMode.SANDBOX_LARGE_MAP}
        )

        self.assertTrue(result.success)
        self.assertEqual(
            [(*SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT, SANDBOX_MAP_SETTLE_SECONDS)],
            clicks,
        )
        self.assertNotEqual(
            SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT,
            TELEPORT_MAP_RETURN_RELATIVE_POINT,
        )

    def test_close_map_page_unknown_mode_never_clicks(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        task = SimpleNamespace(
            operate_click=lambda *_args, **_kwargs: self.fail(
                "unknown page must not use a calibrated return point"
            ),
        )
        navigator = Navigator(task, SimpleNamespace(capture=lambda: frame))
        navigator.ensure_small_minimap = lambda: True
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.UNKNOWN
        )

        result = navigator._close_confirmed_map_page(
            {MapPageMode.DIRECT_TELEPORT}
        )

        self.assertFalse(result.success)
        self.assertEqual(ScreenState.UNKNOWN, result.state)

    def test_open_story_quick_switcher_from_sandbox_never_detours_through_home(self):
        fixed_clicks = []
        template_clicks = []
        task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: fixed_clicks.append((x, y, after_sleep)),
            open_cartridge_quick_switcher=lambda **_kwargs: self.fail(
                "sandbox route must not use the global-home entry"
            ),
        )
        vision = SimpleNamespace(
            click_stable_template=lambda spec, timeout, after_sleep, **_kw: (
                template_clicks.append((spec, timeout, after_sleep)) or True
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator.return_home = lambda: self.fail(
            "sandbox route must not return to the global home"
        )
        navigator._wait_for_current_sandbox = lambda: NavigationResult(
            True,
            ScreenState.SANDBOX,
        )
        navigator._wait_for_quick_switch_page = lambda: True
        navigator._wait_for_story_category = lambda **_kwargs: True

        result = navigator.open_story_quick_switcher_from_sandbox()

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.CARD_MENU, result.state)
        self.assertEqual([(QUICK_SWITCH_TEMPLATE, 3.0, 1.0)], template_clicks)
        self.assertEqual([(*STORY_CATEGORY_POINT, 0.5)], fixed_clicks)

    def test_open_story_quick_switcher_from_sandbox_stops_before_click_when_unconfirmed(self):
        task = SimpleNamespace(
            operate_click=lambda *_args, **_kwargs: self.fail(
                "unconfirmed sandbox must not be clicked"
            )
        )
        vision = SimpleNamespace(
            click_stable_template=lambda *_args, **_kwargs: self.fail(
                "unconfirmed sandbox must not scan quick switch"
            )
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._wait_for_current_sandbox = lambda: NavigationResult(
            False,
            ScreenState.UNKNOWN,
            "未稳定确认当前剧情卡带箱庭",
        )

        result = navigator.open_story_quick_switcher_from_sandbox()

        self.assertFalse(result.success)
        self.assertIn("未稳定确认", result.message)

    def test_open_story_quick_switcher_reuses_immediately_prior_sandbox_confirmation(self):
        template_clicks = []
        task = SimpleNamespace(
            operate_click=lambda *_args, **_kwargs: None,
        )
        vision = SimpleNamespace(
            click_stable_template=lambda spec, timeout, after_sleep, **_kw: (
                template_clicks.append((spec, timeout, after_sleep)) or True
            ),
        )
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._wait_for_current_sandbox = lambda: self.fail(
            "the caller already confirmed the same sandbox"
        )
        navigator._wait_for_quick_switch_page = lambda: True
        navigator._wait_for_story_category = lambda **_kwargs: True

        result = navigator.open_story_quick_switcher_from_sandbox(
            sandbox_already_confirmed=True,
        )

        self.assertTrue(result.success)
        self.assertEqual([(QUICK_SWITCH_TEMPLATE, 3.0, 1.0)], template_clicks)

    def test_current_sandbox_confirmation_requires_consecutive_frames(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        states = iter(
            (
                ScreenState.SANDBOX,
                ScreenState.UNKNOWN,
                ScreenState.SANDBOX,
                ScreenState.SANDBOX,
            )
        )
        captures = []
        navigator = Navigator(
            SimpleNamespace(sleep=lambda *_args: None),
            SimpleNamespace(capture=lambda: captures.append(frame) or frame),
        )
        navigator.classify = lambda _frame=None: next(states)
        navigator._match_story_sandbox_signals = lambda _frame: SandboxConfirmation(
            2,
            2,
            3,
            1,
        )

        result = navigator._wait_for_current_sandbox(timeout=2.0, interval=0.0)

        self.assertTrue(result.success)
        self.assertEqual(ScreenState.SANDBOX, result.state)
        self.assertEqual(4, len(captures))

    def test_interaction_button_template_uses_strict_three_score_gates(self):
        self.assertEqual("image/green/IcoHand.png", HAND_TEMPLATE.file_name)
        self.assertEqual(0.95, HAND_TEMPLATE.threshold)
        self.assertEqual(0.90, HAND_TEMPLATE.min_pixel_score)
        self.assertEqual(0.85, HAND_TEMPLATE.min_zncc_score)
        self.assertEqual(0.95, HAND_TEMPLATE.minimum_safe_threshold)

    def test_area_map_entry_never_presses_the_portal_skill(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        skill = MatchResult(0.97, (1760, 790), (44, 43), 0.88, 0.90)
        clicks = []
        navigator = object.__new__(Navigator)
        navigator.task = SimpleNamespace(
            info_set=lambda *_args: None,
            operate_click=lambda *args, **kwargs: self.fail(
                f"area-map entry must not use fixed point: {args}, {kwargs}"
            ),
        )
        navigator.vision = SimpleNamespace(
            capture=lambda: frame,
            match=lambda _frame, _spec: skill,
            passes=lambda result, spec: result is skill and spec is SANDBOX_TELEPORT_SKILL_TEMPLATE,
            click_client=lambda point, shape, after_sleep=0: clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.UNKNOWN
        )
        navigator.classify = lambda _frame=None: ScreenState.SANDBOX
        navigator._click_sandbox_teleport_interaction = lambda: False

        result = navigator.ensure_area_map()

        self.assertFalse(result.success)
        self.assertEqual([], clicks)

    def test_area_map_context_reads_title_roi_and_confirmation_from_same_frame(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        ocr_calls = []

        class FakeVision:
            @staticmethod
            def simplify(value):
                return value

            @staticmethod
            def ocr_text(received, name, **kwargs):
                ocr_calls.append((received, name, kwargs.get("relative_roi")))
                return "卢戈森林深处"

            @staticmethod
            def match(_frame, _spec):
                return MatchResult(-1.0, (0, 0), (0, 0))

            @staticmethod
            def passes(_result, _spec):
                return False

            @staticmethod
            def threshold_for(spec):
                return spec.threshold

            @staticmethod
            def match_all(*_args, **_kwargs):
                return ()

        navigator = Navigator(SimpleNamespace(), FakeVision())

        navigator.ensure_small_minimap = lambda: True
        navigator._detect_map_page_mode = lambda received: (
            self.assertIs(received, frame)
            or SimpleNamespace(
                mode=MapPageMode.DIRECT_TELEPORT,
                header_text="移动魔法阵",
            )
        )
        context = navigator._area_map_context(frame, CARD_BY_ID["Q_sp1"])

        self.assertTrue(context.is_area_map)
        self.assertEqual("卢戈森林深处", context.raw_text)
        self.assertEqual("移动魔法阵", context.confirmation_text)
        self.assertEqual(CollectionMapRole.BATTLE_AREA_2.value, context.resolved_target_key)
        self.assertEqual(1, len(ocr_calls))
        self.assertTrue(all(call[0] is frame for call in ocr_calls))
        self.assertEqual("传送阵地图名", ocr_calls[0][1])
        self.assertEqual(TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI, ocr_calls[0][2])

    def test_area_map_teleport_template_is_enabled_only_and_strict(self):
        self.assertIs(
            TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATES[0],
            TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATE,
        )
        self.assertEqual(1, len(TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATES))
        spec = TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATE
        self.assertEqual("传送阵地图传送阵", spec.name)
        self.assertEqual("image/green/TpCircleMapNewGE.png", spec.file_name)
        self.assertEqual(0.95, spec.threshold)
        self.assertEqual(0.90, spec.min_pixel_score)
        self.assertEqual(0.85, spec.min_zncc_score)
        self.assertEqual(0.95, spec.minimum_safe_threshold)

        path = ROOT / "recognition-assets/template-assets" / spec.file_name
        template = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(template)
        self.assertEqual((50, 54, 3), template.shape)
        green = (template[:, :, 0] == 0) & (template[:, :, 1] == 255) & (template[:, :, 2] == 0)
        self.assertGreater(np.count_nonzero(green), 0)
        self.assertLess(np.count_nonzero(green), template.shape[0] * template.shape[1])

        skill_spec = TELEPORT_MAP_SKILL_TEMPLATE
        self.assertEqual("传送阵地图传送技能", skill_spec.name)
        self.assertEqual("image/green/TpSkillMapGE.png", skill_spec.file_name)
        self.assertEqual(0.95, skill_spec.threshold)
        self.assertEqual(0.90, skill_spec.min_pixel_score)
        self.assertEqual(0.85, skill_spec.min_zncc_score)
        self.assertEqual(0.95, skill_spec.minimum_safe_threshold)
        self.assertNotIn(skill_spec, TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATES)

        skill_path = ROOT / "recognition-assets/template-assets" / skill_spec.file_name
        skill_template = cv2.imread(str(skill_path), cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(skill_template)
        self.assertEqual((43, 43, 4), skill_template.shape)
        self.assertGreater(np.count_nonzero(skill_template[:, :, 3]), 0)
        self.assertLess(
            np.count_nonzero(skill_template[:, :, 3]),
            skill_template.shape[0] * skill_template.shape[1],
        )

        sandbox_skill = SANDBOX_TELEPORT_SKILL_TEMPLATE
        self.assertEqual("image/green/Skill3-4GE.png", sandbox_skill.file_name)
        self.assertNotIn(sandbox_skill, TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATES)

    def test_teleport_map_teleports_reject_dim_candidate_before_click_context(self):
        frame = np.zeros((300, 500, 3), dtype=np.uint8)
        enabled = MatchResult(0.98, (80, 80), (52, 52), 0.94, 0.93)
        disabled = MatchResult(0.98, (280, 80), (52, 52), 0.94, 0.93)
        cv2.circle(frame, enabled.center, 16, (230, 230, 230), -1)
        cv2.circle(frame, disabled.center, 16, (100, 100, 100), -1)

        class FakeVision:
            @staticmethod
            def threshold_for(_spec):
                return 0.95

            @staticmethod
            def match_all(*_args, **_kwargs):
                return (enabled, disabled)

            @staticmethod
            def passes(_result, _spec):
                return True

        navigator = object.__new__(Navigator)
        navigator.task = SimpleNamespace(info_set=lambda *_args: None)
        navigator.vision = FakeVision()

        self.assertGreater(
            navigator._area_map_teleport_bright_neutral_ratio(frame, enabled),
            AREA_MAP_TELEPORT_BRIGHT_NEUTRAL_RATIO,
        )
        self.assertLess(
            navigator._area_map_teleport_bright_neutral_ratio(frame, disabled),
            AREA_MAP_TELEPORT_BRIGHT_NEUTRAL_RATIO,
        )
        self.assertEqual((enabled,), navigator._teleport_map_teleports(frame))


class ReturnHomeFromBattleTest(unittest.TestCase):
    """bd2 session 2026-10-22: a field battle left the trade way home with
    「没有已确认的安全返回路径」 three times in a row."""

    def _navigator(self, leave_result, states):
        from src.tasks.map_trade.navigator import Navigator

        navigator = object.__new__(Navigator)
        fled = []
        navigator.task = SimpleNamespace(
            leave_field_battle=lambda label: fled.append(label) or leave_result,
            operate_click=lambda *_a, **_k: None,
        )
        navigator._discount_close_dialog_shown = lambda: False
        navigator._cancel_auto_move_dialog = lambda: None
        navigator._merchant_menu_shown = lambda: False
        screens = iter(states)
        navigator.classify = lambda *_a, **_k: next(screens)
        return navigator, fled

    def test_battle_on_the_way_home_is_run_away_from(self):
        navigator, fled = self._navigator("left", (ScreenState.UNKNOWN, ScreenState.HOME))
        self.assertTrue(navigator._return_home_pass().success)
        self.assertEqual(["跑商返回主页"], fled)

    def test_a_known_screen_is_never_taken_for_a_battle(self):
        navigator, fled = self._navigator("left", (ScreenState.HOME,))
        self.assertTrue(navigator._return_home_pass().success)
        self.assertEqual([], fled)


class CollectionPageSeekTest(unittest.TestCase):
    """User demo 2026-09-28: the teleport map opens on the current map's
    page, which need not be the town, and the hunting ground can sit left
    of the town (chapter 2), so pages are found by name."""

    ctx = staticmethod(NavigatorTest._area_context)

    def _navigator(self, pages, start):
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        position = [start]
        moves = []

        def move(_card, _context, direction, force=False):
            step = 1 if direction == "right" else -1
            if not 0 <= position[0] + step < len(pages):
                return None
            position[0] += step
            moves.append(direction)
            return pages[position[0]]

        navigator._move_area_map = move
        return navigator, moves

    def test_from_the_hunting_ground_left_of_town(self):
        card = CARD_BY_ID["Q_sp2"]
        pages = [
            self.ctx("战斗 废弃矿山"),
            self.ctx("安全 达雷普镇", card.targets[0].key),
            self.ctx("战斗Ⅰ 封锁矿山", card.targets[1].key),
            self.ctx("战斗Ⅱ 禁地矿山", card.targets[2].key),
        ]
        navigator, moves = self._navigator(pages, 0)
        found = navigator._seek_collection_page(card, pages[0], card.targets[0])
        self.assertEqual(card.targets[0].key, found.resolved_target_key)
        self.assertEqual(["right"], moves)

    def test_from_battle_two_goes_left(self):
        card = CARD_BY_ID["Q_sp4"]
        pages = [
            self.ctx("安全 凯洛镇", card.targets[0].key),
            self.ctx("战斗Ⅰ 凯洛山", card.targets[1].key),
            self.ctx("战斗Ⅱ 凯洛山中心处", card.targets[2].key),
        ]
        navigator, moves = self._navigator(pages, 2)
        found = navigator._seek_collection_page(card, pages[2], card.targets[0])
        self.assertEqual(card.targets[0].key, found.resolved_target_key)
        self.assertEqual(["left", "left"], moves)

    def test_unknown_start_tries_right_then_left(self):
        card = CARD_BY_ID["Q_sp1"]
        pages = [
            self.ctx("安全 卢戈镇", card.targets[0].key),
            self.ctx("战斗 熊洞"),
        ]
        navigator, moves = self._navigator(pages, 1)
        found = navigator._seek_collection_page(card, pages[1], card.targets[0])
        self.assertEqual(card.targets[0].key, found.resolved_target_key)
        self.assertEqual(["left"], moves)

    def test_missing_target_fails_safely(self):
        card = CARD_BY_ID["Q_sp1"]
        pages = [self.ctx("战斗 熊洞"), self.ctx("战斗 草药田")]
        navigator, _moves = self._navigator(pages, 0)
        result = navigator._seek_collection_page(card, pages[0], card.targets[2])
        self.assertIsInstance(result, NavigationResult)
        self.assertFalse(result.success)

    def _q_ep2_pages(self):
        """Nightmare Winter's teleport pages, left to right: the safe zone
        雷瓦汀据点 is the LAST page (Leo 2026-10-15)."""
        card = CARD_BY_ID["Q_ep2"]
        by_key = {target.key: target for target in card.targets}
        main = CollectionMapRole.MAIN_AREA.value
        battle_1 = CollectionMapRole.BATTLE_AREA_1.value
        battle_2 = CollectionMapRole.BATTLE_AREA_2.value
        pages = [
            self.ctx("战斗Ⅰ 恶梦之城1", battle_1, right=True),
            self.ctx("战斗Ⅱ 恶梦之城2", battle_2, left=True, right=True),
            self.ctx("安全 雷瓦汀据点", main, left=True),
        ]
        return card, by_key, pages

    def _attempt_navigator(self, pages, start):
        """As ``_navigator``, but records every direction tried, also the
        ones that hit the end of the list."""
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        position = [start]
        attempts = []

        def move(_card, _context, direction, force=False):
            attempts.append(direction)
            step = 1 if direction == "right" else -1
            if not 0 <= position[0] + step < len(pages):
                return None
            position[0] += step
            return pages[position[0]]

        navigator._move_area_map = move
        return navigator, attempts

    def test_q_ep2_safe_zone_is_the_last_page_so_battle_maps_are_left(self):
        # Live 2K 2026-10-15: from 雷瓦汀据点 the right arrow was pressed
        # twice (~20 s) before going left (Leo 「活動卡帶第2的安全區是第三張地圖
        # 要切換的時候螢幕不要再點右邊箭頭了」).
        card, by_key, pages = self._q_ep2_pages()
        navigator, attempts = self._attempt_navigator(pages, 2)

        found = navigator._seek_collection_page(
            card, pages[2], by_key[CollectionMapRole.BATTLE_AREA_1.value]
        )

        self.assertEqual(CollectionMapRole.BATTLE_AREA_1.value, found.resolved_target_key)
        self.assertEqual(["left", "left"], attempts)

    def test_q_ep2_battle_two_is_one_page_left_of_the_safe_zone(self):
        card, by_key, pages = self._q_ep2_pages()
        navigator, attempts = self._attempt_navigator(pages, 2)

        found = navigator._seek_collection_page(
            card, pages[2], by_key[CollectionMapRole.BATTLE_AREA_2.value]
        )

        self.assertEqual(CollectionMapRole.BATTLE_AREA_2.value, found.resolved_target_key)
        self.assertEqual(["left"], attempts)

    def test_q_ep2_back_to_the_safe_zone_goes_right(self):
        card, by_key, pages = self._q_ep2_pages()
        navigator, attempts = self._attempt_navigator(pages, 0)

        found = navigator._seek_collection_page(
            card, pages[0], by_key[CollectionMapRole.MAIN_AREA.value]
        )

        self.assertEqual(CollectionMapRole.MAIN_AREA.value, found.resolved_target_key)
        self.assertEqual(["right", "right"], attempts)

    def test_story_cards_keep_the_safe_zone_as_the_first_page(self):
        card = CARD_BY_ID["Q_sp4"]
        self.assertEqual(
            tuple(target.key for target in card.targets),
            Navigator._collection_page_order(card),
        )
        self.assertEqual(
            (
                CollectionMapRole.BATTLE_AREA_1.value,
                CollectionMapRole.BATTLE_AREA_2.value,
                CollectionMapRole.MAIN_AREA.value,
            ),
            Navigator._collection_page_order(CARD_BY_ID["Q_ep2"]),
        )


class SmallMinimapTest(unittest.TestCase):
    def test_enlarged_minimap_is_switched_back(self):
        clicks = []
        states = iter(["small"])
        current = ["large"]
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
            click_client=lambda point, shape, after_sleep=0: (
                clicks.append(point), current.__setitem__(0, next(states))
            ),
        )
        navigator = Navigator(SimpleNamespace(log_warning=lambda *a: None), vision)
        match = MatchResult(0.99, (440, 380), (32, 32), pixel_score=0.98)
        navigator._optional_match = lambda _frame, spec: (
            match if ("减号" in spec.name) == (current[0] == "large") else None
        )
        self.assertTrue(navigator.ensure_small_minimap())
        self.assertEqual(1, len(clicks))

    def test_small_minimap_needs_no_click(self):
        clicks = []
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
            click_client=lambda *a, **k: clicks.append(a),
        )
        navigator = Navigator(SimpleNamespace(), vision)
        navigator._optional_match = lambda _frame, spec: None
        self.assertTrue(navigator.ensure_small_minimap())
        self.assertEqual([], clicks)


class WalkToCollectionMapTest(unittest.TestCase):
    """Chapter 6 (user demo 2026-09-28): 第5层 has no teleport page; it is
    walked to through an area map exit, trying its spots until one reacts."""

    def _navigator(self, open_headers, headers_after_clicks):
        clicks = []
        open_headers = iter(open_headers)
        after = iter(headers_after_clicks)
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
            click_client=lambda point, shape, after_sleep=0: clicks.append(point),
        )
        task = SimpleNamespace(operate_click=lambda *a, **k: None, sleep=lambda *a: None)
        navigator = Navigator(task, vision)
        navigator.ensure_small_minimap = lambda: True
        navigator._open_field_map = lambda: next(open_headers)
        navigator._field_map_header = lambda: next(after)
        navigator._close_field_map = lambda: None
        navigator._wait_for_field_hud = lambda **k: NavigationResult(True, ScreenState.SANDBOX)
        navigator._loading_timeout = lambda: 1.0
        return navigator, clicks

    def test_spots_are_tried_until_the_map_reacts(self):
        card = CARD_BY_ID["Q_sp6"]
        navigator, clicks = self._navigator(
            ["战斗Ⅰ施塔因之塔第6层", "战斗Ⅲ施塔因之塔第5层"],
            ["战斗Ⅰ施塔因之塔第6层", ""],  # first spot ignored, second loads
        )
        result = navigator._walk_to_collection_map(card, card.targets[1], card.targets[2])
        self.assertTrue(result.success)
        self.assertEqual([(610, 434), (607, 455)], clicks)

    def test_no_spot_reacting_fails_safely(self):
        card = CARD_BY_ID["Q_sp6"]
        navigator, clicks = self._navigator(
            ["战斗Ⅲ施塔因之塔第5层"], ["战斗Ⅲ施塔因之塔第5层"] * 3
        )
        result = navigator._walk_to_collection_map(card, card.targets[2], card.targets[1])
        self.assertFalse(result.success)
        self.assertEqual(3, len(clicks))

    def test_wrong_floor_is_never_clicked(self):
        card = CARD_BY_ID["Q_sp6"]
        navigator, clicks = self._navigator(["安全施塔因之塔第8层"], [])
        result = navigator._walk_to_collection_map(card, card.targets[1], card.targets[2])
        self.assertFalse(result.success)
        self.assertEqual([], clicks)

    def test_arrival_on_another_floor_fails(self):
        card = CARD_BY_ID["Q_sp6"]
        navigator, _clicks = self._navigator(
            ["战斗Ⅰ施塔因之塔第6层", "战斗Ⅰ施塔因之塔第7层"], [""]
        )
        result = navigator._walk_to_collection_map(card, card.targets[1], card.targets[2])
        self.assertFalse(result.success)

    def test_exit_labels_are_read_again_until_they_show(self):
        # Chapter 14 (live 2K 2026-09-30): right after a teleport the area
        # map's exit labels showed ~2 s after its header.
        card = CARD_BY_ID["Q_sp14"]
        _main, left_corridor, central = card.targets
        navigator, clicks = self._navigator(
            ["战斗Ⅱ剑之神殿左侧回廊", "战斗Ⅰ剑之神殿中央回廊"], [""]
        )
        reads = iter(([], [], [(810, 982), (810, 958)]))
        navigator._exit_label_points = lambda _frame, _target: next(reads)

        result = navigator._walk_to_collection_map(card, left_corridor, central)

        self.assertTrue(result.success)
        self.assertEqual([(810, 982)], clicks)


class FieldWaitTest(unittest.TestCase):
    """Leo 2026-09-30: a stall ends after 15 s, not 45; walking is no stall."""

    @staticmethod
    def _navigator(states, *, moving, still=False):
        clock = [0.0]
        states = iter(states)
        task = SimpleNamespace(sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        # A walk pans the field: every look differs (``still`` keeps it fixed).
        looks = iter(range(10**6))
        vision = SimpleNamespace(
            capture=lambda: np.full(
                (80, 80, 3), 0 if still else 60 * (next(looks) % 2), np.uint8
            )
        )
        navigator = Navigator(task, vision)
        navigator.classify = lambda _frame: next(states)
        navigator._auto_moving = lambda _frame: moving
        navigator._status = lambda *_args: None
        return navigator, clock

    def _wait(self, navigator, clock):
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", lambda: clock[0]):
            return navigator._wait_for_field_hud(
                timeout=15.0, interval=0.5, success_message="到了", failure_message="卡住"
            )

    def test_walking_does_not_count_toward_the_stall_limit(self):
        # 40 s of 自动移动中 (ch14's exit walk took 15 s with one expulsion).
        states = [ScreenState.UNKNOWN] * 80 + [ScreenState.SANDBOX] * 2
        navigator, clock = self._navigator(states, moving=True)

        self.assertTrue(self._wait(navigator, clock).success)

    def test_a_walk_whose_screen_stands_still_is_a_stall(self):
        # Leo 2026-10-14 「頂多等8秒到10秒」: the 自动移动中 banner up but the
        # field not moving no longer holds the wait.
        navigator, clock = self._navigator(
            [ScreenState.UNKNOWN] * 1000, moving=True, still=True
        )

        self.assertFalse(self._wait(navigator, clock).success)
        self.assertLessEqual(clock[0], 15.5 + STUCK_SECONDS)

    def test_a_stall_ends_at_the_limit(self):
        navigator, clock = self._navigator([ScreenState.UNKNOWN] * 200, moving=False)

        self.assertFalse(self._wait(navigator, clock).success)
        self.assertLessEqual(clock[0], 15.5)

    def test_endless_walking_is_capped(self):
        from src.tasks.map_trade.navigator_constants import SANDBOX_NAVIGATION_WALK_TIMEOUT

        navigator, clock = self._navigator([ScreenState.UNKNOWN] * 1000, moving=True)

        self.assertFalse(self._wait(navigator, clock).success)
        self.assertLessEqual(clock[0], 15.0 + SANDBOX_NAVIGATION_WALK_TIMEOUT + 0.5)


class PatrolCatchTest(unittest.TestCase):
    """Leo 2026-09-30: "寫程式時也要寫萬一被抓時要如何應對避免卡死" (ch14's 光明监视者)."""

    @staticmethod
    def _navigator(banner_reads):
        reads = iter(banner_reads)
        clicks = []
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
            ocr_text=lambda _frame, _name, relative_roi=None: next(reads),
            simplify=lambda text: text,
            click_client=lambda point, shape, after_sleep=0: clicks.append(point),
        )
        task = SimpleNamespace(sleep=lambda *_args: None, config={"加载页面等待秒数": 15.0})
        navigator = Navigator(task, vision)
        navigator._status = lambda *_args: None
        return navigator, clicks

    def test_a_catch_ends_the_walk_wait_at_once(self):
        navigator, _clicks = self._navigator(
            ["自动移动中：魔法阵", "光明监视者 凡入侵者，皆当驱除。当聆光之声，循其指引。"]
        )

        self.assertEqual("caught", navigator._wait_auto_move_finished(45.0))

    def test_a_walk_is_over_after_two_quiet_reads(self):
        navigator, _clicks = self._navigator(["自动移动中：魔法阵", "", ""])

        self.assertEqual("done", navigator._wait_auto_move_finished(45.0))

    def test_cancel_presses_the_x_only_under_the_banner(self):
        navigator, clicks = self._navigator(["自动移动中：魔法阵", ""])
        self.assertTrue(navigator._cancel_walk())
        self.assertEqual([(960, 985)], clicks)

        navigator, clicks = self._navigator([""])
        self.assertFalse(navigator._cancel_walk())
        self.assertEqual([], clicks)

    def test_after_a_catch_the_resumed_walk_is_stopped_at_once(self):
        navigator, clicks = self._navigator(
            [
                "光明监视者 凡入侵者，皆当驱除。",
                "",  # the map reloading
                # Live 2K: the toast is still up when the game walks on.
                "被光明监视者发现，已遭驱逐。 自动移动中：魔法阵",
                "被光明监视者发现，已遭驱逐。 自动移动中：魔法阵",
                "已中止自动移动。",
                "",
                "",
            ]
        )
        states = iter((ScreenState.LOADING, ScreenState.SANDBOX, ScreenState.SANDBOX))
        navigator.classify = lambda _frame: next(states)

        navigator._stop_caught_walk()

        self.assertEqual([(960, 985)], clicks)

    def _circle_walk_navigator(self, walk_text):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        teleport = MatchResult(0.96, (500, 300), (40, 40), pixel_score=0.90, zncc_score=0.88)
        vision = SimpleNamespace(capture=lambda: frame, click_client=lambda *_a, **_k: None)
        navigator = Navigator(SimpleNamespace(sleep=lambda *_a: None, config={}), vision)
        navigator._status = lambda *_args: None
        navigator._open_field_map = lambda: "战斗Ⅱ剑之神殿左侧回廊"
        navigator._sandbox_navigation_page_has_keyword = lambda _frame: True
        navigator._sandbox_navigation_teleport = lambda _frame: teleport
        navigator._walk_text = lambda _frame: walk_text
        stopped = []
        navigator._stop_caught_walk = lambda: stopped.append(True)
        navigator._click_sandbox_teleport_interaction = lambda **_k: self.fail(
            "waited for a prompt that never shows"
        )
        return navigator, stopped

    def test_caught_on_the_way_to_a_circle_gives_up_at_once(self):
        navigator, stopped = self._circle_walk_navigator("自动移动中魔法阵")
        navigator._wait_auto_move_finished = lambda _timeout: "caught"

        result = navigator._walk_to_sandbox_teleport_interaction()

        self.assertFalse(result.success)
        self.assertEqual([True], stopped)
        self.assertIn("驱逐", result.message)

    def test_caught_before_the_walk_banner_shows(self):
        # Live 2K: "被发现了！！" 3 s after the click, no "自动移动中" read yet.
        navigator, stopped = self._circle_walk_navigator("被发现了")

        result = navigator._walk_to_sandbox_teleport_interaction()

        self.assertFalse(result.success)
        self.assertEqual([True], stopped)
        self.assertIn("驱逐", result.message)


class AreaMapTeleportIconTest(unittest.TestCase):
    def _pick(self, pixels):
        results = [
            MatchResult(0.95, (300 + 60 * index, 500), (40, 40), pixel_score=pixel, zncc_score=0.9)
            for index, pixel in enumerate(pixels)
        ]
        vision = SimpleNamespace(
            match_all=lambda *_a, **_k: results,
            threshold_for=lambda _spec: 0.8,
            passes=lambda _result, _spec: True,
        )
        navigator = Navigator(SimpleNamespace(sleep=lambda *_a: None, config={}), vision)
        navigator._status = lambda *_args: None
        return navigator._sandbox_navigation_teleport(np.zeros((1080, 1920, 3), np.uint8))

    def test_two_real_circles_take_the_best(self):
        # 角色卡3 上流社会派对会场 at 4K: two circles, both 0.957.
        picked = self._pick([0.957, 0.957, 0.55])
        self.assertIsNotNone(picked)
        self.assertEqual((300, 500), picked.position)

    def test_a_lone_strong_icon_still_needs_its_margin(self):
        self.assertIsNone(self._pick([0.93, 0.88]))


class WalkExitRetryTest(unittest.TestCase):
    _navigator = WalkToCollectionMapTest._navigator

    def test_still_on_the_map_after_the_walk_clicks_the_exit_again(self):
        # ch14: the 光明监视者 puts the character back at 左侧回廊's entrance.
        card = CARD_BY_ID["Q_sp14"]
        _main, left_corridor, central = card.targets
        navigator, clicks = self._navigator(
            ["战斗Ⅱ剑之神殿左侧回廊", "战斗Ⅱ剑之神殿左侧回廊", "战斗Ⅰ剑之神殿中央回廊"],
            ["", ""],
        )
        navigator._exit_label_points = lambda _frame, _target: [(810, 982)]

        result = navigator._walk_to_collection_map(card, left_corridor, central)

        self.assertTrue(result.success)
        self.assertEqual([(810, 982), (810, 982)], clicks)

    def test_a_second_miss_fails(self):
        card = CARD_BY_ID["Q_sp14"]
        _main, left_corridor, central = card.targets
        navigator, clicks = self._navigator(["战斗Ⅱ剑之神殿左侧回廊"] * 3, ["", ""])
        navigator._exit_label_points = lambda _frame, _target: [(810, 982)]

        result = navigator._walk_to_collection_map(card, left_corridor, central)

        self.assertFalse(result.success)
        self.assertEqual(2, len(clicks))

    def test_a_covered_label_uses_its_known_place(self):
        # The character's icon covers the label when it stands at that exit.
        card = CARD_BY_ID["Q_sp14"]
        _main, left_corridor, central = card.targets
        navigator, clicks = self._navigator(
            ["战斗Ⅱ剑之神殿左侧回廊", "战斗Ⅰ剑之神殿中央回廊"], [""]
        )
        navigator._exit_label_points = lambda _frame, _target: []

        with patch("src.tasks.map_trade.navigator_sandbox.WALK_LABEL_READ_TIMEOUT", 0.0):
            result = navigator._walk_to_collection_map(card, left_corridor, central)

        self.assertTrue(result.success)
        self.assertEqual([(609, 737)], clicks)

    def test_a_covered_label_with_a_known_place_stops_at_the_shorter_wait(self):
        # 桌面分身 2026-10-18 角色卡3: 5 s of re-reads ended at the known place
        # anyway; the 5 s wait (patched to 0 above) no longer applies.
        card = CARD_BY_ID["Q_sp14"]
        _main, left_corridor, central = card.targets
        navigator, clicks = self._navigator(
            ["战斗Ⅱ剑之神殿左侧回廊", "战斗Ⅰ剑之神殿中央回廊"], [""]
        )
        reads = []
        navigator._exit_label_points = lambda _frame, _target: reads.append(1) or []

        with patch("src.tasks.map_trade.navigator_sandbox.WALK_LABEL_KNOWN_READ_TIMEOUT", 0.0):
            result = navigator._walk_to_collection_map(card, left_corridor, central)

        self.assertTrue(result.success)
        self.assertEqual(1, len(reads))
        self.assertEqual([(609, 737)], clicks)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class LostPressTest(unittest.TestCase):
    """A press the game swallowed must not end as done (review batch 2):
    pressed once more after 1.5 s while the screen is unchanged, and
    reported as not done when that one is lost too."""

    def _run(self, clock, call):
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", clock), patch(
            "src.tasks.map_trade.navigator_sandbox.press_and_confirm",
            partial(press_and_confirm, clock=clock),
            create=True,
        ):
            return call()

    def _destination_navigator(self, lands_on=None):
        """The dialog's 确认 stays up until press number ``lands_on``."""
        clock = FakeClock()
        frame = np.zeros((1080, 1920, 3), np.uint8)
        presses = []

        def boxes(_frame, _name):
            if lands_on is not None and len(presses) >= lands_on:
                return []
            return [SimpleNamespace(name="确认", x=700, y=500, width=120, height=40)]

        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=boxes,
            simplify=lambda text: text,
            click_client=lambda point, _shape, after_sleep=0: presses.append(point),
        )
        logs = []
        task = SimpleNamespace(sleep=clock.sleep, log_info=logs.append, info_set=lambda *_a: None)
        navigator = Navigator(task, vision)
        navigator._walk_text = lambda _frame: ""
        return navigator, frame, presses, clock, logs

    def test_a_lost_destination_confirm_is_pressed_once_more(self):
        navigator, frame, presses, clock, logs = self._destination_navigator(lands_on=2)

        confirmed = self._run(
            clock, lambda: navigator._click_sandbox_navigation_destination_confirmation(frame)
        )

        self.assertTrue(confirmed)
        self.assertEqual([(760, 520), (760, 520)], presses)
        self.assertTrue(any("补按" in line for line in logs))

    def test_a_destination_confirm_lost_twice_stops_the_walk_fallback(self):
        navigator, frame, presses, clock, _logs = self._destination_navigator()
        teleport = MatchResult(0.96, (500, 300), (40, 40), pixel_score=0.90, zncc_score=0.88)
        navigator._open_field_map = lambda: "安全 测试镇"
        navigator._sandbox_navigation_page_has_keyword = lambda _frame: True
        navigator._sandbox_navigation_teleport = lambda _frame: teleport
        navigator._click_sandbox_navigation_menu_teleport = lambda _frame: False
        closed = []
        navigator._close_confirmed_map_page = lambda *a, **k: closed.append(True)
        navigator._wait_auto_move_finished = lambda _timeout: self.fail("waited for a walk")
        navigator._click_sandbox_teleport_interaction = lambda **_k: self.fail(
            "waited for a prompt that never shows"
        )

        result = self._run(clock, navigator._walk_to_sandbox_teleport_interaction)

        self.assertFalse(result.success)
        self.assertIn("未确认目的地按钮", result.message)
        # The map icon, then 确认 twice; never a third time.
        self.assertEqual([teleport.center, (760, 520), (760, 520)], presses)
        self.assertEqual([True], closed)

    def _nav_menu_navigator(self, lands_on=None, dialog=False):
        """The ≡ menu stays open until press number ``lands_on``; with
        ``dialog`` the press opens 立即前往 over the still-listed menu."""
        clock = FakeClock()
        frame = np.zeros((1080, 1920, 3), np.uint8)
        presses = []

        def landed():
            return lands_on is not None and len(presses) >= lands_on

        def boxes(_frame, _name, _roi, **_kwargs):
            if landed() and not dialog:
                return []
            return [
                SimpleNamespace(name=text, x=300, y=100 + 60 * row, width=80, height=30)
                for row, text in enumerate(("旅馆", "狩猎场", "艾琳"))
            ]

        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=boxes,
            ocr_text=lambda _frame, name, **_k: (
                "立即前往" if dialog and landed() and name == "前往确认" else ""
            ),
            simplify=lambda text: text,
            click_template=lambda *_a, **_k: True,
            click_client=lambda point, _shape, after_sleep=0: presses.append(point),
        )
        warnings = []
        task = SimpleNamespace(
            sleep=clock.sleep,
            log_info=lambda *_a: None,
            log_warning=warnings.append,
            info_set=lambda *_a: None,
        )
        navigator = Navigator(task, vision)
        navigator._confirm_travel = lambda: "moving"
        trips = []
        navigator._wait_for_field_hud = lambda **_k: (
            trips.append(True) or NavigationResult(True, ScreenState.SANDBOX)
        )
        navigator._wait_auto_move_finished = lambda _timeout: "done"
        navigator._loading_timeout = lambda: 1.0
        return navigator, presses, clock, trips, warnings

    def test_a_lost_nav_menu_press_is_pressed_once_more(self):
        navigator, presses, clock, trips, _warnings = self._nav_menu_navigator(lands_on=2)

        entry = self._run(clock, lambda: navigator._travel_via_nav_menu("狩猎场", "艾琳"))

        self.assertEqual("狩猎场", entry)
        self.assertEqual([(340, 175), (340, 175)], presses)
        self.assertEqual([True], trips)

    def test_a_nav_menu_press_lost_twice_is_no_trip(self):
        # It used to pass the field check on the unchanged field and report
        # the character at 狩猎场.
        navigator, presses, clock, trips, warnings = self._nav_menu_navigator()

        entry = self._run(clock, lambda: navigator._travel_via_nav_menu("狩猎场", "艾琳"))

        self.assertIsNone(entry)
        self.assertEqual(2, len(presses))
        self.assertEqual([], trips)
        self.assertTrue(any("没有反应" in text for text in warnings))
        # The run's message can say which part of the ≡ trip failed.
        self.assertEqual("点了≡菜单的狩猎场没有反应", navigator._nav_failure)

    def test_the_travel_dialog_over_the_menu_counts_as_taken(self):
        navigator, presses, clock, trips, _warnings = self._nav_menu_navigator(
            lands_on=1, dialog=True
        )

        entry = self._run(clock, lambda: navigator._travel_via_nav_menu("狩猎场", "艾琳"))

        self.assertEqual("狩猎场", entry)
        self.assertEqual(1, len(presses))
        self.assertEqual([True], trips)

    def _page_navigator(self, pages):
        clock = FakeClock()
        presses = []
        navigator = Navigator(
            SimpleNamespace(sleep=clock.sleep, info_set=lambda *_a: None),
            SimpleNamespace(
                click_client=lambda point, _shape, after_sleep=0: presses.append(point)
            ),
        )
        navigator._capture_area_map_context = lambda _card: pages(len(presses))
        return navigator, presses, clock

    def test_a_dropped_page_arrow_press_is_pressed_again(self):
        card = CARD_BY_ID["Q_sp2"]
        town = NavigatorTest._area_context("安全 达雷普镇", card.targets[0].key, right=True)
        battle = NavigatorTest._area_context("战斗Ⅰ 封锁矿山", card.targets[1].key, left=True)
        navigator, presses, clock = self._page_navigator(
            lambda pressed: battle if pressed >= 2 else town
        )

        changed = self._run(clock, lambda: navigator._move_area_map(card, town, "right"))

        self.assertIs(battle, changed)
        self.assertEqual(2, len(presses))

    def test_a_page_that_never_turns_is_the_end_after_two_presses(self):
        card = CARD_BY_ID["Q_sp2"]
        town = NavigatorTest._area_context("安全 达雷普镇", card.targets[0].key, right=True)
        navigator, presses, clock = self._page_navigator(lambda _pressed: town)

        changed = self._run(clock, lambda: navigator._move_area_map(card, town, "right"))

        self.assertIsNone(changed)
        self.assertEqual(2, len(presses))


class TeleportPageEndTest(unittest.TestCase):
    """Q_ep2 live 2K 2026-10-15: on its last page (the safe zone 雷瓦汀据点)
    the read showed left=True, right=False, yet the right arrow was pressed
    twice (~20 s) before the seek went left (Leo 2026-10-15 「活動卡帶第2的
    安全區是第三張地圖 要切換的時候螢幕不要再點右邊箭頭了」)."""

    _run = LostPressTest._run
    _page_navigator = LostPressTest._page_navigator
    LEFT = MatchResult(0.99, (360, 500), (40, 40), pixel_score=0.98)
    RIGHT = MatchResult(0.99, (1520, 500), (40, 40), pixel_score=0.98)

    def _page(self, text, key, *, left, right):
        return replace(
            NavigatorTest._area_context(text, key),
            left_arrow=self.LEFT if left else None,
            right_arrow=self.RIGHT if right else None,
        )

    def _game(self, start, *, bare_reads=0):
        """A fake Q_ep2 teleport map: presses left of the screen centre turn
        one page left, right of it one page right (nothing past the ends).
        The first ``bare_reads`` reads show no arrows (not drawn yet)."""
        card = CARD_BY_ID["Q_ep2"]
        main = CollectionMapRole.MAIN_AREA.value
        battle_1 = CollectionMapRole.BATTLE_AREA_1.value
        battle_2 = CollectionMapRole.BATTLE_AREA_2.value
        pages = [
            ("战斗Ⅰ 恶梦之城1", battle_1),
            ("战斗Ⅱ 恶梦之城2", battle_2),
            ("安全 雷瓦汀据点", main),
        ]
        clock = FakeClock()
        position = [start]
        presses = []
        reads = [0]

        def read(_card):
            reads[0] += 1
            text, key = pages[position[0]]
            bare = reads[0] <= bare_reads
            return self._page(
                text,
                key,
                left=not bare and position[0] > 0,
                right=not bare and position[0] < len(pages) - 1,
            )

        def press(point, _shape, after_sleep=0):
            direction = "left" if point[0] < 960 else "right"
            presses.append(direction)
            step = 1 if direction == "right" else -1
            if 0 <= position[0] + step < len(pages):
                position[0] += step

        navigator = Navigator(
            SimpleNamespace(sleep=clock.sleep, info_set=lambda *_a: None),
            SimpleNamespace(click_client=press),
        )
        navigator._capture_area_map_context = read
        return card, navigator, presses, clock, read

    def test_the_missing_right_arrow_is_never_pressed(self):
        card, navigator, presses, clock, read = self._game(2)
        safe = read(card)
        self.assertIsNone(safe.right_arrow)
        self.assertIsNotNone(safe.left_arrow)

        changed = self._run(clock, lambda: navigator._move_area_map(card, safe, "right"))

        self.assertIsNone(changed)
        self.assertEqual([], presses)

    def test_an_arrow_still_fading_in_is_pressed_on_the_second_read(self):
        card, navigator, presses, clock, read = self._game(1)
        page = read(card)
        fading = replace(page, right_arrow=None)

        changed = self._run(clock, lambda: navigator._move_area_map(card, fading, "right"))

        self.assertEqual(CollectionMapRole.MAIN_AREA.value, changed.resolved_target_key)
        self.assertEqual(["right"], presses)

    def test_a_blind_press_stops_once_only_the_other_arrow_shows(self):
        # The 09:26:38 read: left=False and right=False (arrows not drawn
        # yet), so the right arrow's fixed place was pressed; the next reads
        # showed left only and it still waited out a second press.
        card, navigator, presses, clock, read = self._game(2, bare_reads=1)
        bare = read(card)
        self.assertIsNone(bare.left_arrow)
        self.assertIsNone(bare.right_arrow)

        changed = self._run(clock, lambda: navigator._move_area_map(card, bare, "right"))

        self.assertIsNone(changed)
        self.assertEqual(["right"], presses)
        self.assertLess(clock.now, 3.0)

    def test_q_ep2_from_the_safe_zone_presses_only_left(self):
        card, navigator, presses, clock, read = self._game(2, bare_reads=1)
        safe = read(card)  # both arrows missing, as at 09:26:38
        target = next(
            item for item in card.targets if item.key == CollectionMapRole.BATTLE_AREA_1.value
        )

        found = self._run(
            clock, lambda: navigator._seek_collection_page(card, safe, target)
        )

        self.assertEqual(CollectionMapRole.BATTLE_AREA_1.value, found.resolved_target_key)
        self.assertEqual(["left", "left"], presses)
        self.assertNotIn("right", presses)

    def test_story_card_safe_zone_still_pages_right(self):
        card = CARD_BY_ID["Q_sp2"]
        town = self._page("安全 达雷普镇", card.targets[0].key, left=False, right=True)
        battle = self._page("战斗Ⅰ 封锁矿山", card.targets[1].key, left=True, right=True)
        navigator, presses, clock = self._page_navigator(
            lambda pressed: battle if pressed else town
        )

        found = self._run(
            clock, lambda: navigator._seek_collection_page(card, town, card.targets[1])
        )

        self.assertIs(battle, found)
        self.assertEqual([self.RIGHT.center], presses)
