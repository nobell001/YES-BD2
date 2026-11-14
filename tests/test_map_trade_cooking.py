"""Regression coverage for the cooking-before-trade flow at the trade merchant."""

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from src.tasks.map_trade.action_icons import COOKING_ICON
from src.tasks.map_trade.models import (
    DEFAULT_COOKING_RECIPES,
    DEFAULT_RECIPES,
    FINAL_COOKING_RECIPE,
    MAP_TRADE_REFERENCE,
    MatchResult,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_constants import MERCHANT_PROMPT_OCR_ROI
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_cooking import (
    COOKING_MAX_FIXED_POINT,
    COOKING_BACK_POINT,
    COOKING_BACK_TEMPLATE,
    COOKING_DETAIL_TEMPLATE,
    COOKING_EXIT_TIMEOUT,
    COOKING_ICON_QUICK_TIMEOUT,
    COOKING_LIST_GRID_ROI,
    COOKING_QUANTITY_ATTEMPTS,
    COOKING_QUANTITY_CHOICES_ROI,
    COOKING_RECIPE_SPECS,
    COOKING_SKILL_GROUP_POINTS,
    COOKING_SKILL_GROUP_SWITCH_SETTLE_SECONDS,
    CookingDetailSnapshot,
    CookingFlowMixin,
    CookingListSnapshot,
    CookingRecipeOutcome,
    _character_coverage,
)


class CookingTask:
    def __init__(self, **config):
        self.config = {
            "料理制作周期": "每周",
            "料理保险": True,
            "5星料理": list(DEFAULT_RECIPES),
            **config,
        }
        self.clicks = []
        self.sleeps = []
        self.logs = []
        self.infos = []
        self.saved_frames = []

    def operate_click(self, x, y, after_sleep=0.0):
        self.clicks.append((x, y, after_sleep))

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def save_frame(self, name, frame):
        self.saved_frames.append((name, frame))
        return Path("probe_outputs") / f"{name}.png"

    def log_info(self, message):
        self.logs.append(("info", message))

    def log_warning(self, message, **_kwargs):
        self.logs.append(("warning", message))

    def info_set(self, key, value):
        self.infos.append((key, value))


class CookingProgress:
    def __init__(self, completed=()):
        self.completed = set(completed)
        self.marked = []

    def should_cook(self, *, every_run=False, recipes=None):
        return every_run or any(recipe not in self.completed for recipe in recipes or ())

    def cooking_recipe_complete(self, recipe):
        return recipe in self.completed

    def mark_cooking_recipe_complete(self, recipe):
        if recipe in self.completed:
            return False
        self.completed.add(recipe)
        self.marked.append(recipe)
        return True


class CookingFlowTest(unittest.TestCase):
    def _orchestrated_trader(self, *, selected, completed=(), outcomes=(), exit_ok=True):
        task = CookingTask(**{"5星料理": list(selected)})
        progress = CookingProgress(completed)
        trader = object.__new__(Trader)
        trader.task = task
        trader.progress = progress
        trader._selected_cooking_recipes = lambda: tuple(selected)
        calls = []

        def enter():
            calls.append("enter")
            trader._cooking_opened = True
            return True

        pending_outcomes = iter(outcomes)
        trader._enter_cooking_list = enter
        trader._cook_one_recipe = lambda recipe: (
            calls.append(("cook", recipe)) or next(pending_outcomes)
        )
        # One batch per dish here; the repeat has its own tests
        # (tests/test_trade_extra_dishes.py).
        trader._cook_remaining_batches = lambda recipe: True
        trader._leave_cooking_to_q_sp6 = lambda: calls.append("exit") or exit_ok
        return trader, progress, calls

    def test_each_run_cooks_again_and_keeps_unavailable_retryable(self):
        first, second, third = DEFAULT_RECIPES[:3]
        trader, progress, calls = self._orchestrated_trader(
            selected=(first, second, third),
            completed=(first,),
            outcomes=(CookingRecipeOutcome.COOKED, CookingRecipeOutcome.COOKED,
                      CookingRecipeOutcome.UNAVAILABLE),
        )

        self.assertTrue(trader.run_cooking())
        self.assertEqual([], progress.marked)
        self.assertEqual(
            [
                "enter",
                ("cook", first),
                ("cook", second),
                ("cook", third),
                "exit",
            ],
            calls,
        )
        self.assertNotIn(third, progress.completed)

    def test_partial_failure_stops_later_recipes(self):
        first, second, third = DEFAULT_RECIPES[:3]
        trader, progress, calls = self._orchestrated_trader(
            selected=(first, second, third),
            outcomes=(CookingRecipeOutcome.COOKED, CookingRecipeOutcome.FAILED),
        )

        self.assertFalse(trader.run_cooking())
        self.assertEqual([], progress.marked)
        self.assertEqual(
            [
                "enter",
                ("cook", first),
                ("cook", second),
                "exit",
            ],
            calls,
        )

    def test_absent_recipe_alerts_and_does_not_stop_flow(self):
        first, second, third = DEFAULT_RECIPES[:3]
        trader, progress, calls = self._orchestrated_trader(
            selected=(first, second, third),
            outcomes=(
                CookingRecipeOutcome.ABSENT,
                CookingRecipeOutcome.COOKED,
                CookingRecipeOutcome.UNAVAILABLE,
            ),
        )

        self.assertTrue(trader.run_cooking())
        self.assertEqual(
            [
                "enter",
                ("cook", first),
                ("cook", second),
                ("cook", third),
                "exit",
            ],
            calls,
        )
        self.assertEqual([], progress.marked)
        alerts = [
            message
            for kind, message in trader.task.logs
            if kind == "warning" and "当前未识别到食谱" in message
        ]
        self.assertEqual(1, len(alerts))
        self.assertIn(first, alerts[0])

    def test_exit_to_q_sp6_is_required_for_success(self):
        trader, progress, calls = self._orchestrated_trader(
            selected=(DEFAULT_RECIPES[0],),
            outcomes=(CookingRecipeOutcome.COOKED,),
            exit_ok=False,
        )

        self.assertFalse(trader.run_cooking())
        self.assertEqual([], progress.marked)
        self.assertEqual("exit", calls[-1])

    def test_default_order_optional_selection_and_chicken_last(self):
        trader = object.__new__(Trader)
        trader.task = CookingTask(**{"5星料理": []})
        self.assertEqual((*DEFAULT_COOKING_RECIPES, FINAL_COOKING_RECIPE),
                         trader._selected_cooking_recipes())
        trader.task.config["5星料理"] = [DEFAULT_RECIPES[1], DEFAULT_RECIPES[0]]
        self.assertEqual((*DEFAULT_COOKING_RECIPES, *DEFAULT_RECIPES[:2],
                          FINAL_COOKING_RECIPE), trader._selected_cooking_recipes())

    def test_missing_templates_stop_before_navigation(self):
        trader = object.__new__(Trader)
        trader.task = CookingTask(**{"5星料理": []})
        trader._enter_cooking_list = lambda: self.fail("missing assets must stop navigation")
        from unittest.mock import patch
        with patch("pathlib.Path.is_file", return_value=False):
            self.assertFalse(trader.run_cooking())

    def _entry_trader(self, *, arrived=None, sandbox=True, icon_results=(True,)):
        task = CookingTask()
        events = []
        pending_icons = iter(icon_results)
        navigator = SimpleNamespace(
            go_to_trade_merchant=lambda: (
                events.append("go_to_trade_merchant")
                or arrived
                or NavigationResult(True, ScreenState.SANDBOX, "已在商人旁")
            ),
            wait_for_q_sp6_sandbox=lambda timeout: (
                events.append(("sandbox", timeout)) or sandbox
            ),
        )
        vision = SimpleNamespace(
            click_stable_template=lambda spec, timeout, after_sleep, **_kw: (
                events.append(("icon", spec, timeout, after_sleep)) or next(pending_icons)
            )
        )
        trader = object.__new__(Trader)
        trader.task = task
        trader.navigator = navigator
        trader.vision = vision
        trader._cooking_opened = False
        trader._wait_for_cooking_list = lambda timeout: events.append("list") or object()
        return trader, task, events

    def test_entry_goes_to_merchant_confirms_field_then_opens_cooking_skill(self):
        trader, task, events = self._entry_trader()

        self.assertTrue(trader._enter_cooking_list())
        self.assertEqual(
            [
                "go_to_trade_merchant",
                ("sandbox", COOKING_EXIT_TIMEOUT),
                ("icon", COOKING_ICON.template, COOKING_ICON_QUICK_TIMEOUT, 0.0),
                "list",
            ],
            events,
        )
        # The icon was already on the bar: no skill group was switched.
        self.assertEqual([], task.clicks)
        self.assertTrue(trader._cooking_opened)

    def test_entry_fails_cleanly_when_merchant_is_not_reached(self):
        failure = NavigationResult(False, ScreenState.HOME, "未唯一确认剧情游戏卡1角标")
        trader, task, events = self._entry_trader(arrived=failure)

        self.assertFalse(trader._enter_cooking_list())
        self.assertEqual(["go_to_trade_merchant"], events)
        self.assertEqual([], task.clicks)
        self.assertFalse(trader._cooking_opened)
        warnings = [message for kind, message in task.logs if kind == "warning"]
        self.assertEqual(1, len(warnings))
        self.assertIn(failure.message, warnings[0])

    def test_entry_fails_without_clicking_when_field_is_not_confirmed(self):
        trader, task, events = self._entry_trader(sandbox=False)

        self.assertFalse(trader._enter_cooking_list())
        self.assertEqual(["go_to_trade_merchant", ("sandbox", COOKING_EXIT_TIMEOUT)], events)
        self.assertEqual([], task.clicks)
        self.assertFalse(trader._cooking_opened)

    def test_entry_fails_when_no_skill_group_has_the_cooking_skill(self):
        trader, task, events = self._entry_trader(
            icon_results=(False,) * (1 + len(COOKING_SKILL_GROUP_POINTS))
        )

        self.assertFalse(trader._enter_cooking_list())
        self.assertNotIn("list", events)
        self.assertFalse(trader._cooking_opened)
        self.assertTrue(any(kind == "warning" for kind, _message in task.logs))

    def test_open_cooking_skill_tries_current_bar_then_groups_in_order(self):
        self.assertEqual(3, len(COOKING_SKILL_GROUP_POINTS))
        cases = (
            # (icon results, expected group clicks, expected result)
            ((True,), 0, True),
            ((False, True), 1, True),
            ((False, False, True), 2, True),
            ((False, False, False, True), 3, True),
            ((False, False, False, False), 3, False),
        )
        for icon_results, group_clicks, expected in cases:
            with self.subTest(icon_results=icon_results):
                trader, task, events = self._entry_trader(icon_results=icon_results)

                self.assertIs(expected, trader._open_cooking_skill())
                self.assertEqual(
                    [(*point, 0.0) for point in COOKING_SKILL_GROUP_POINTS[:group_clicks]],
                    task.clicks,
                )
                self.assertEqual(
                    [COOKING_SKILL_GROUP_SWITCH_SETTLE_SECONDS] * group_clicks,
                    task.sleeps,
                )
                self.assertEqual(
                    [("icon", COOKING_ICON.template, COOKING_ICON_QUICK_TIMEOUT, 0.0)]
                    * len(icon_results),
                    events,
                )

    def test_recipe_state_machine_requires_result_and_list_restoration(self):
        recipe = DEFAULT_RECIPES[0]
        task = CookingTask(**{"料理保险": False})
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        recipe_match = MatchResult(0.97, (1000, 650), (80, 80), pixel_score=0.94)
        start_match = MatchResult(0.98, (1110, 975), (40, 40), pixel_score=0.96)
        detail = CookingDetailSnapshot(frame, start_match, True, 0.72)
        events = []
        vision = SimpleNamespace(
            match=lambda _frame, _spec: events.append("recipe recognized") or recipe_match,
            passes=lambda *_args: True,
            click_client=lambda point, _shape, after_sleep=0.0: events.append(
                ("click", point, after_sleep)
            ),
        )
        trader = object.__new__(Trader)
        trader.task = task
        trader.vision = vision
        trader._cooking_card_enabled = lambda *_args: True
        trader._wait_for_cooking_list = lambda _timeout: (
            events.append("list confirmed") or CookingListSnapshot(frame, recipe_match)
        )
        trader._wait_for_cooking_detail = lambda _recipe, _timeout: (
            events.append("detail confirmed") or detail
        )
        trader._click_quantity_choice = lambda _recipe, choice: (
            events.append(f"quantity {choice}") or True
        )
        trader._wait_for_cooking_started = lambda _recipe, _timeout: (
            events.append("button turned gray") or True
        )
        trader._wait_for_cooking_result = lambda _recipe, _timeout: (
            events.append("result confirmed") or frame
        )
        trader._return_from_detail_to_list = lambda _recipe: (
            events.append("list restored") or True
        )

        self.assertIs(
            CookingRecipeOutcome.COOKED,
            trader._cook_one_recipe(recipe),
        )
        self.assertLess(events.index("quantity MAX"), events.index("button turned gray"))
        self.assertLess(events.index("button turned gray"), events.index("result confirmed"))
        self.assertLess(events.index("result confirmed"), events.index("list restored"))

    def test_disabled_recipe_is_nonfatal_and_never_starts(self):
        recipe = DEFAULT_RECIPES[0]
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        recipe_match = MatchResult(0.97, (1000, 650), (80, 80), pixel_score=0.94)
        detail = CookingDetailSnapshot(
            frame,
            MatchResult(0.96, (1110, 975), (40, 40), pixel_score=0.74),
            False,
            0.004,
        )
        trader = object.__new__(Trader)
        trader.task = CookingTask()
        trader._cooking_card_enabled = lambda *_args: True
        trader.vision = SimpleNamespace(
            match=lambda *_args: recipe_match,
            passes=lambda *_args: True,
            click_client=lambda *_args, **_kwargs: None,
        )
        trader._wait_for_cooking_list = lambda _timeout: CookingListSnapshot(
            frame,
            recipe_match,
        )
        trader._wait_for_cooking_detail = lambda *_args: detail
        trader._return_from_detail_to_list = lambda _recipe: True
        trader._click_quantity_choice = lambda *_args: self.fail(
            "disabled recipe must not select quantity"
        )

        self.assertIs(
            CookingRecipeOutcome.UNAVAILABLE,
            trader._cook_one_recipe(recipe),
        )

    def test_result_timeout_is_failure_not_success(self):
        recipe = DEFAULT_RECIPES[0]
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        match = MatchResult(0.97, (1000, 650), (80, 80), pixel_score=0.94)
        detail = CookingDetailSnapshot(frame, match, True, 0.72)
        recovered = []
        trader = object.__new__(Trader)
        trader.task = CookingTask()
        trader._cooking_card_enabled = lambda *_args: True
        trader.vision = SimpleNamespace(
            match=lambda *_args: match,
            passes=lambda *_args: True,
            click_client=lambda *_args, **_kwargs: None,
        )
        trader._wait_for_cooking_list = lambda _timeout: CookingListSnapshot(frame, match)
        trader._wait_for_cooking_detail = lambda *_args: detail
        trader._select_max_cooking_quantity = lambda *_args: detail
        trader._wait_for_cooking_started = lambda *_args: True
        trader._wait_for_cooking_result = lambda *_args: None
        trader._recover_cooking_list = lambda: recovered.append(True) or True

        self.assertIs(
            CookingRecipeOutcome.FAILED,
            trader._cook_one_recipe(recipe),
        )
        self.assertEqual([True], recovered)

    def test_max_press_then_start_without_slider_check(self):
        # Leo 2026-10-15: pressed MAX + pressed 制作 is enough; the slider is
        # never compared.  MAX that cannot be read is pressed at its fixed spot.
        recipe = DEFAULT_COOKING_RECIPES[0]
        frame = np.full((1080, 1920, 3), 145, dtype=np.uint8)
        card = MatchResult(0.99, (1000, 600), (100, 100), pixel_score=0.99)
        start = MatchResult(0.99, (1100, 970), (400, 60), pixel_score=0.99)
        detail = CookingDetailSnapshot(frame, start, True, 0.7)
        for missing, expected_clicks, expected in (
            (0, 1, CookingRecipeOutcome.COOKED),
            (1, 1, CookingRecipeOutcome.COOKED),
            (COOKING_QUANTITY_ATTEMPTS, 0, CookingRecipeOutcome.COOKED),
        ):
            with self.subTest(missing=missing):
                state = {"reads": 0, "clicks": 0, "fixed": [], "started": False}
                trader = object.__new__(Trader)
                trader.task = CookingTask()

                def click(point, _shape, after_sleep=0.0):
                    if point == (690, 875):
                        state["clicks"] += 1
                    elif point == start.center:
                        state["started"] = True

                def boxes(*_args, **_kwargs):
                    state["reads"] += 1
                    if state["reads"] <= missing:
                        return []
                    return [SimpleNamespace(name="MAX", x=650, y=850, width=80, height=50)]

                trader.vision = SimpleNamespace(
                    match=lambda *_args: card,
                    passes=lambda *_args: True,
                    click_client=click,
                    simplify=lambda value: value,
                    ocr_boxes=boxes,
                    click_reference=lambda x, y, after_sleep=0.0: state["fixed"].append((x, y)),
                )
                trader._wait_for_cooking_list = lambda _: CookingListSnapshot(frame, card)
                trader._wait_for_cooking_detail = lambda *_args: detail
                trader._cooking_detail_snapshot = lambda *_args: detail
                trader._wait_for_cooking_started = lambda *_args: True
                trader._wait_for_cooking_result = lambda *_args: frame
                trader._return_from_detail_to_list = lambda *_args: True
                trader._recover_cooking_list = lambda: True
                self.assertIs(expected, trader._cook_one_recipe(recipe))
                self.assertEqual(expected_clicks, state["clicks"])
                self.assertEqual(
                    [COOKING_MAX_FIXED_POINT] if expected_clicks == 0 else [], state["fixed"]
                )
                self.assertEqual(expected is CookingRecipeOutcome.COOKED, state["started"])

    def test_gray_card_skips_without_clicking_or_opening_detail(self):
        recipe = DEFAULT_RECIPES[0]
        frame = np.full((1080, 1920, 3), 60, dtype=np.uint8)
        match = MatchResult(0.97, (1000, 650), (96, 96), zncc_score=0.97)
        trader = object.__new__(Trader)
        trader.task = CookingTask()
        trader.vision = SimpleNamespace(
            match=lambda *_args: match,
            passes=lambda *_args: True,
            capture=lambda: frame,
            click_client=lambda *_args, **_kwargs: self.fail("gray card must not be clicked"),
        )
        trader._wait_for_cooking_list = lambda _: CookingListSnapshot(frame, match)
        self.assertIs(CookingRecipeOutcome.UNAVAILABLE, trader._cook_one_recipe(recipe))

    def test_start_requires_recognized_detail_with_gray_button(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        trader = object.__new__(Trader)
        trader.task = CookingTask()
        match = MatchResult(0.97, (1110, 975), (40, 40), pixel_score=0.96)
        for detail, expected in (
            (None, False),
            (CookingDetailSnapshot(frame, match, True, 0.73), False),
            (CookingDetailSnapshot(frame, match, False, 0.73), False),
            (CookingDetailSnapshot(frame, match, False, 0.004), True),
        ):
            with self.subTest(detail=detail):
                trader._cooking_detail_snapshot = lambda _recipe: detail
                self.assertEqual(
                    expected, trader._wait_for_cooking_started(DEFAULT_RECIPES[0], 0.0)
                )

    def test_max_fixed_point_lands_on_max_text(self):
        # click_reference scales from MAP_TRADE_REFERENCE (1280x720); the point
        # must land inside the MAX text box of Leo's 2560x1440 frame
        # (926-995 x 1165-1187).
        x = COOKING_MAX_FIXED_POINT[0] / MAP_TRADE_REFERENCE.width * 2560
        y = COOKING_MAX_FIXED_POINT[1] / MAP_TRADE_REFERENCE.height * 1440
        self.assertTrue(926 <= x <= 995, x)
        self.assertTrue(1165 <= y <= 1187, y)

    def test_cooking_implementation_has_no_scroll_or_resolution_pixel_clicks(self):
        source = inspect.getsource(CookingFlowMixin)

        self.assertNotIn("drag_reference", source)
        # The one fixed-position press: MAX when its text cannot be read
        # (Leo 2026-10-15 「你總是要有補救方案」).
        self.assertEqual(1, source.count("click_reference"))
        self.assertIn("click_reference(*COOKING_MAX_FIXED_POINT", source)
        self.assertNotIn("1203", source)
        self.assertEqual(
            (
                (1671 / 1920, 1011 / 1080),
                (1749 / 1920, 1011 / 1080),
                (1824 / 1920, 1011 / 1080),
            ),
            COOKING_SKILL_GROUP_POINTS,
        )
        for spec in COOKING_RECIPE_SPECS.values():
            self.assertEqual(COOKING_LIST_GRID_ROI, spec.relative_roi)
            self.assertIsNone(spec.roi)


class CookingRecognitionTest(unittest.TestCase):
    def test_card_background_distinguishes_gray_bright_and_uncertain(self):
        for size in (64, 96):
            match = MatchResult(0.97, (0, 0), (size, size))
            for value, expected in ((60, False), (145, True), (100, None)):
                frame = np.full((size, size, 3), value, dtype=np.uint8)
                # Dark food art does not make an available beige card disabled.
                frame[size // 4:3 * size // 4, size // 4:3 * size // 4] = 0
                self.assertIs(expected, CookingFlowMixin._cooking_card_enabled(frame, match))

    def test_detail_enabled_gate_separates_video_bright_and_disabled_states(self):
        recipe = DEFAULT_RECIPES[0]
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        current = {
            "match": MatchResult(0.995, (1110, 975), (40, 40), pixel_score=0.966),
            "bright": 0.73,
        }
        vision = SimpleNamespace(
            capture=lambda: frame,
            match=lambda *_args: current["match"],
            passes=lambda *_args: True,
            ocr_text=lambda _frame, name, **_kwargs: (
                "料理" if "标题" in name else recipe
            ),
            simplify=lambda value: value,
            bright_neutral_ratio=lambda *_args: current["bright"],
        )
        trader = object.__new__(Trader)
        trader.task = CookingTask()
        trader.vision = vision

        self.assertTrue(trader._cooking_detail_snapshot(recipe).enabled)
        current["match"] = MatchResult(
            0.956,
            (1110, 975),
            (40, 40),
            pixel_score=0.747,
        )
        current["bright"] = 0.004
        self.assertFalse(trader._cooking_detail_snapshot(recipe).enabled)

    def test_result_requires_recipe_name_and_positive_quantity_evidence(self):
        recipe = DEFAULT_RECIPES[0]
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        text = {"value": f"{recipe}×260"}
        trader = object.__new__(Trader)
        trader.task = CookingTask()
        trader.vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda *_args, **_kwargs: text["value"],
            simplify=lambda value: value,
        )
        trader._cooking_detail_snapshot = lambda *_args: object()

        self.assertIs(frame, trader._wait_for_cooking_result(recipe, 0.0))
        text["value"] = recipe
        self.assertIsNone(trader._wait_for_cooking_result(recipe, 0.0))
        text["value"] = "其他料理×60"
        self.assertIsNone(trader._wait_for_cooking_result(recipe, 0.0))

    def test_quantity_choice_clicks_ocr_box_center(self):
        recipe = DEFAULT_RECIPES[0]
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicked = []
        detail = CookingDetailSnapshot(
            frame,
            MatchResult(0.98, (1110, 975), (40, 40), pixel_score=0.96),
            True,
            0.72,
        )
        trader = object.__new__(Trader)
        trader.task = CookingTask()
        trader.vision = SimpleNamespace(
            ocr_boxes=lambda _frame, _name, **kwargs: [
                SimpleNamespace(name="MAX", x=650, y=850, width=80, height=50)
            ],
            simplify=lambda value: value,
            click_client=lambda point, shape, after_sleep: clicked.append(
                (point, shape, after_sleep)
            ),
        )
        trader._cooking_detail_snapshot = lambda _recipe: detail

        self.assertTrue(trader._click_quantity_choice(recipe, "MAX"))
        self.assertEqual(((690, 875), frame.shape, 0.0), clicked[0])

    def test_back_button_prefers_detected_center_then_relative_fallback(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        detected = MatchResult(
            0.96,
            (160, 35),
            (30, 30),
            pixel_score=0.94,
            zncc_score=0.90,
        )
        task = CookingTask()
        clicked = []
        passed = {"value": True}
        trader = object.__new__(Trader)
        trader.task = task
        trader.vision = SimpleNamespace(
            match=lambda _frame, spec: (
                detected if spec is COOKING_BACK_TEMPLATE else self.fail(spec.name)
            ),
            passes=lambda *_args: passed["value"],
            click_client=lambda point, _shape, after_sleep: clicked.append(
                (point, after_sleep)
            ),
        )

        trader._click_cooking_back(frame, context="test")
        self.assertEqual([(detected.center, 0.0)], clicked)
        passed["value"] = False
        trader._click_cooking_back(frame, context="test")
        self.assertEqual([(*COOKING_BACK_POINT, 0.0)], task.clicks)

    def test_character_coverage_tolerates_one_ocr_character_but_not_wrong_recipe(self):
        self.assertGreaterEqual(_character_coverage("地狱火紫菜包饭", "地狱火紫菜包反260"), 0.75)
        self.assertLess(_character_coverage("地狱火紫菜包饭", "透明沙拉60"), 0.75)

    def test_all_cooking_geometry_is_fractional_and_detail_template_is_scoped(self):
        for point in (*(value for group in COOKING_SKILL_GROUP_POINTS for value in group),
                      *COOKING_BACK_POINT):
            self.assertGreaterEqual(point, 0.0)
            self.assertLessEqual(point, 1.0)
        for roi in (COOKING_LIST_GRID_ROI, COOKING_QUANTITY_CHOICES_ROI):
            self.assertTrue(all(0.0 <= value <= 1.0 for value in roi))
            self.assertLess(roi[0], roi[2])
            self.assertLess(roi[1], roi[3])
        self.assertIsNotNone(COOKING_DETAIL_TEMPLATE.relative_roi)
        self.assertIsNone(COOKING_DETAIL_TEMPLATE.roi)


class CookingAbsentRecipeTest(unittest.TestCase):
    """配方未识别分支：保持原门禁，跳过制作下一个，结尾警报不报错。"""

    def _trader_with_snapshot(self, *, identity):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        task = CookingTask()
        trader = object.__new__(Trader)
        trader.task = task
        trader.vision = SimpleNamespace(
            match=lambda _frame, _spec: identity,
            passes=lambda _result, _spec: False,
        )
        trader._wait_for_cooking_list = lambda _timeout: CookingListSnapshot(
            frame,
            identity,
        )
        return trader, task, frame

    def _logs_of(self, task, kind):
        return [message for log_kind, message in task.logs if log_kind == kind]

    def test_identity_miss_skips_to_next_recipe_without_error(self):
        trader, task, _frame = self._trader_with_snapshot(
            identity=MatchResult(-1.0, (0, 0), (0, 0)),
        )

        outcome = trader._cook_one_recipe("香草牛排")

        self.assertIs(CookingRecipeOutcome.ABSENT, outcome)
        self.assertEqual([], task.saved_frames)
        self.assertEqual([], self._logs_of(task, "warning"))
        self.assertTrue(
            any(
                "未识别到 香草牛排" in message and "跳过" in message
                for message in self._logs_of(task, "info")
            )
        )

    def test_unknown_brightness_saves_evidence_and_fails(self):
        frame = np.full((64, 64, 3), 100, dtype=np.uint8)
        task = CookingTask()
        trader = object.__new__(Trader)
        trader.task = task
        trader.vision = SimpleNamespace(
            match=lambda _frame, _spec: MatchResult(0.97, (0, 0), (64, 64)),
            passes=lambda _result, _spec: True,
            capture=lambda: frame,
        )
        trader._wait_for_cooking_list = lambda _timeout: CookingListSnapshot(
            frame,
            MatchResult(0.97, (0, 0), (64, 64)),
        )

        outcome = trader._cook_one_recipe("香草牛排")

        self.assertIs(CookingRecipeOutcome.FAILED, outcome)
        self.assertEqual(
            [("cooking_香草牛排_failed", frame)],
            task.saved_frames,
        )


class CookingSandboxConfirmationTest(unittest.TestCase):
    def _navigator(self, boxes):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        task = CookingTask()
        ocr_frames = []
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_boxes=lambda captured, name, roi: (
                ocr_frames.append((captured, name, roi)) or boxes["value"]
            ),
            simplify=lambda value: value,
            match=lambda *_args: self.fail("merchant confirmation must not match templates"),
        )
        navigator = Navigator(task, vision)
        return navigator, task, frame, ocr_frames

    def test_merchant_confirmation_requires_sandbox_and_prompt_in_same_frame(self):
        prompt = SimpleNamespace(name="F 无聊收集狂大叔", x=1000, y=380, width=100, height=40)
        boxes = {"value": [prompt]}
        navigator, task, frame, ocr_frames = self._navigator(boxes)
        classified = []
        navigator._classify_trade_frame = lambda captured: (
            classified.append(captured) or ScreenState.SANDBOX
        )

        self.assertTrue(navigator.wait_for_q_sp6_sandbox(0.0))
        self.assertEqual([(frame, "商人互动按钮", MERCHANT_PROMPT_OCR_ROI)], ocr_frames)
        self.assertEqual(1, len(classified))
        self.assertIs(frame, classified[0])

        navigator._classify_trade_frame = lambda _frame: ScreenState.HOME
        self.assertFalse(navigator.wait_for_q_sp6_sandbox(0.0))

        navigator._classify_trade_frame = lambda _frame: ScreenState.SANDBOX
        boxes["value"] = [
            SimpleNamespace(name="F 对话", x=1000, y=380, width=100, height=40)
        ]
        self.assertFalse(navigator.wait_for_q_sp6_sandbox(0.0))
        # A zero timeout is a single probe, not a failure worth a warning.
        self.assertEqual([], [message for kind, message in task.logs if kind == "warning"])

    def test_merchant_confirmation_timeout_logs_warning(self):
        navigator, task, _frame, ocr_frames = self._navigator({"value": []})
        navigator._classify_trade_frame = lambda _frame: ScreenState.SANDBOX

        with patch(
            "src.tasks.map_trade.navigator_trade.monotonic",
            side_effect=(0.0, 1.0, 20.0),
        ):
            self.assertFalse(navigator.wait_for_q_sp6_sandbox(COOKING_EXIT_TIMEOUT))
        self.assertEqual(2, len(ocr_frames))
        self.assertEqual(1, len(task.sleeps))
        warnings = [message for kind, message in task.logs if kind == "warning"]
        self.assertEqual(1, len(warnings))
        self.assertIn(f"state={ScreenState.SANDBOX.value}", warnings[0])


if __name__ == "__main__":
    unittest.main()


class CookingListCacheTest(unittest.TestCase):
    """Grey recipes reuse one list frame (live 2026-09-27: ~4 s per recipe)."""

    def test_grey_recipes_read_the_list_once(self):
        from src.tasks.map_trade.trader_cooking import (
            CookingFlowMixin,
            CookingListSnapshot,
            CookingRecipeOutcome,
        )

        trader = object.__new__(CookingFlowMixin)
        reads = []
        snapshot = CookingListSnapshot(np.zeros((1080, 1920, 3), np.uint8), None)
        trader._wait_for_cooking_list = lambda timeout: reads.append(1) or snapshot
        later = np.zeros((1080, 1920, 3), np.uint8)
        captures = []
        trader.vision = SimpleNamespace(
            match=lambda frame, spec: SimpleNamespace(score=0.99),
            passes=lambda result, spec: True,
            capture=lambda: captures.append(1) or later,
        )
        trader._cooking_card_enabled = lambda frame, match: False
        trader.task = SimpleNamespace(log_info=lambda *a, **k: None, sleep=lambda *_a: None)
        trader._list_snapshot_cache = None
        from src.tasks.map_trade.trader_cooking import COOKING_IDENTITY_SPECS

        recipes = list(COOKING_IDENTITY_SPECS)[:3]
        for recipe in recipes:
            self.assertIs(CookingRecipeOutcome.UNAVAILABLE, trader._cook_one_recipe(recipe))
        self.assertEqual(1, len(reads))
        # Only the first grey card is looked at again (cards may still fade in).
        self.assertEqual(2, len(captures))



class RecipeChoiceTest(unittest.TestCase):
    def _trader(self, config):
        from src.tasks.map_trade.trader_cooking import CookingFlowMixin

        trader = object.__new__(CookingFlowMixin)
        trader.task = SimpleNamespace(config=config)
        return trader

    def test_default_cooks_every_regular_dish_with_chicken_last(self):
        recipes = self._trader({})._selected_cooking_recipes()
        self.assertEqual(10, len(recipes))
        self.assertEqual("街头烤鸡肉串", recipes[-1])

    def test_unticked_dishes_are_skipped(self):
        trader = self._trader({"料理清单": ["冰镇甜点", "街头烤鸡肉串"]})
        recipes = trader._selected_cooking_recipes()
        self.assertEqual(("冰镇甜点", "街头烤鸡肉串"), recipes)
