"""「額外料理」 and the 10000-per-batch cap (Leo 2026-11-10).

Six dishes the game's 2026-11-19 update starts selling: cooked after
everything else, from that date on, each one can be unticked.  A dish whose
card is still bright after a batch (one batch makes 10000 at most) is cooked
again until the card turns grey.
"""

import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2

from src.tasks.map_trade.calendar import UTC_PLUS_8
from src.tasks.map_trade.models import (
    COOKING_RECIPE_TEMPLATES,
    DEFAULT_COOKING_RECIPES,
    EXTRA_COOKING_KEY,
    EXTRA_COOKING_RECIPES,
    FINAL_COOKING_RECIPE,
    OPTIONAL_COOKING_RECIPES,
)
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_cooking import (
    COOKING_BATCH_LIMIT,
    COOKING_IDENTITY_SPECS,
    COOKING_TEMPLATE_DIR,
    CookingFlowMixin,
    CookingRecipeOutcome,
)
from src.tasks.map_trade.vision import Vision

try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships onnxocr
    ONNXPaddleOcr = None

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade"
# Where each dish sits in Leo's cooking list (row, column from 1), checked
# against the six detail pages he sent (the dish's name over the same art).
CELLS = {
    "巧克力面包": (1, 3),
    "土豆汤": (1, 4),
    "水果冰沙": (1, 6),
    "黑啤酒炖锅": (2, 7),
    "藏红花甜茶": (4, 4),
    "凯洛养身汤": (5, 1),
}
BEFORE = datetime(2026, 11, 18, 12, tzinfo=UTC_PLUS_8)
AFTER = datetime(2026, 11, 19, 12, tzinfo=UTC_PLUS_8)


def _cell(center, shape):
    """The list cell a point is in (cards are 104 wide, 126 apart at 1080p)."""

    scale = shape[0] / 1080
    column = int((center[0] / scale - 745) // 126) + 1
    row = int((center[1] / scale - 137) // 126) + 1
    return row, column


class ExtraDishCardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        task = SimpleNamespace(config={}, info_set=lambda *_a: None)
        cls.vision = Vision(task)
        cls.frames = {}
        for name in ("cooking_list_cn_2k_20261110.jpg", "cooking_list_tw_2k_20261110.jpg"):
            frame = cv2.imread(str(FIXTURES / name))
            assert frame is not None, name
            cls.frames[name, "2K"] = frame
            cls.frames[name, "1080p"] = cv2.resize(
                frame, (1920, 1080), interpolation=cv2.INTER_AREA
            )
            cls.frames[name, "4K"] = cv2.resize(
                frame, (3840, 2160), interpolation=cv2.INTER_CUBIC
            )

    def test_every_extra_dish_has_its_card_picture(self):
        self.assertEqual(set(CELLS), set(EXTRA_COOKING_RECIPES))
        for recipe in EXTRA_COOKING_RECIPES:
            path = COOKING_TEMPLATE_DIR / COOKING_RECIPE_TEMPLATES[recipe]
            with self.subTest(recipe=recipe):
                self.assertTrue(path.is_file(), path)
                self.assertEqual((80, 80), cv2.imread(str(path)).shape[:2])

    def test_each_card_is_found_in_its_own_cell_at_every_size(self):
        for (name, size), frame in self.frames.items():
            for recipe, cell in CELLS.items():
                spec = COOKING_IDENTITY_SPECS[recipe]
                match = self.vision.match(frame, spec)
                with self.subTest(frame=name, size=size, recipe=recipe):
                    self.assertTrue(self.vision.passes(match, spec), match.score)
                    self.assertEqual(cell, _cell(match.center, frame.shape))
                    # All six were cookable, except 凯洛养身汤 in the earlier
                    # (繁中) frame: its card was grey there and is still known.
                    grey = recipe == "凯洛养身汤" and "_tw_" in name
                    self.assertIs(
                        not grey, CookingFlowMixin._cooking_card_enabled(frame, match)
                    )

    def test_no_two_dishes_are_read_in_the_same_cell(self):
        frame = self.frames["cooking_list_cn_2k_20261110.jpg", "2K"]
        seen = {}
        for recipe, spec in COOKING_IDENTITY_SPECS.items():
            match = self.vision.match(frame, spec)
            if not self.vision.passes(match, spec):
                continue
            cell = _cell(match.center, frame.shape)
            self.assertNotIn(cell, seen, f"{recipe} and {seen.get(cell)} share {cell}")
            seen[cell] = recipe
        self.assertLessEqual(set(EXTRA_COOKING_RECIPES), set(seen.values()))


DETAIL_FRAMES = {
    "巧克力面包": "chocolate_bread",
    "土豆汤": "potato_soup",
    "水果冰沙": "fruit_smoothie",
    "黑啤酒炖锅": "dark_beer_stew",
    "藏红花甜茶": "saffron_sweet_tea",
    "凯洛养身汤": "kello_wellness_soup",
}


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class ExtraDishDetailPagesTest(unittest.TestCase):
    """Leo's six detail pages (简中 2560x1440, 2026-11-10): after the card is
    pressed the page must be read as that dish, with a usable 料理 button."""

    @classmethod
    def setUpClass(cls):
        engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True, use_npu=False)

        def ocr(*, frame, threshold=0.2, **_kwargs):
            boxes = []
            for points, (text, score) in engine.ocr(frame)[0] or []:
                if score < threshold:
                    continue
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                boxes.append(
                    SimpleNamespace(
                        name=text,
                        x=min(xs),
                        y=min(ys),
                        width=max(xs) - min(xs),
                        height=max(ys) - min(ys),
                        confidence=score,
                    )
                )
            return boxes

        cls.ocr = staticmethod(ocr)

    def _trader(self):
        task = SimpleNamespace(config={}, ocr=self.ocr, info_set=lambda *_a: None)
        trader = object.__new__(Trader)
        trader.task = task
        trader.vision = Vision(task)
        trader._status = lambda *_a: None
        return trader

    def test_each_page_is_read_as_its_own_dish_and_can_be_cooked(self):
        trader = self._trader()
        for recipe, name in DETAIL_FRAMES.items():
            frame = cv2.imread(str(FIXTURES / f"cooking_detail_cn_2k_{name}.jpg"))
            self.assertIsNotNone(frame, name)
            with self.subTest(recipe=recipe):
                detail = trader._cooking_detail_snapshot(recipe, frame)
                self.assertIsNotNone(detail)
                self.assertTrue(detail.enabled)

    def test_a_page_is_not_taken_for_another_dish(self):
        trader = self._trader()
        frame = cv2.imread(str(FIXTURES / "cooking_detail_cn_2k_potato_soup.jpg"))
        for recipe in ("凯洛养身汤", "巧克力面包", "香草牛排"):
            with self.subTest(recipe=recipe):
                self.assertIsNone(trader._cooking_detail_snapshot(recipe, frame))

    def test_the_traditional_chinese_page_is_read_too(self):
        trader = self._trader()
        frame = cv2.imread(str(FIXTURES / "cooking_detail_tw_2k_chocolate_bread_max.jpg"))
        self.assertIsNotNone(trader._cooking_detail_snapshot("巧克力面包", frame))


class ExtraDishChoiceTest(unittest.TestCase):
    def _trader(self, config, now):
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(config=config)
        trader.now_provider = lambda: now
        return trader

    def test_extras_are_cooked_after_everything_else(self):
        config = {
            "5星料理": list(OPTIONAL_COOKING_RECIPES),
            EXTRA_COOKING_KEY: list(EXTRA_COOKING_RECIPES),
        }
        recipes = self._trader(config, AFTER)._selected_cooking_recipes()
        self.assertEqual(
            (
                *DEFAULT_COOKING_RECIPES,
                *OPTIONAL_COOKING_RECIPES,
                FINAL_COOKING_RECIPE,
                *EXTRA_COOKING_RECIPES,
            ),
            recipes,
        )

    def test_not_cooked_before_the_19th(self):
        config = {EXTRA_COOKING_KEY: list(EXTRA_COOKING_RECIPES)}
        recipes = self._trader(config, BEFORE)._selected_cooking_recipes()
        self.assertEqual((*DEFAULT_COOKING_RECIPES, FINAL_COOKING_RECIPE), recipes)

    def test_they_start_with_the_sale_day_at_23_on_the_18th(self):
        config = {EXTRA_COOKING_KEY: ["土豆汤"]}
        evening = datetime(2026, 11, 18, 22, 59, tzinfo=UTC_PLUS_8)
        self.assertNotIn("土豆汤", self._trader(config, evening)._selected_cooking_recipes())
        night = datetime(2026, 11, 18, 23, 0, tzinfo=UTC_PLUS_8)
        self.assertEqual("土豆汤", self._trader(config, night)._selected_cooking_recipes()[-1])

    def test_unticked_extras_are_not_cooked(self):
        config = {EXTRA_COOKING_KEY: ["水果冰沙", "凯洛养身汤"]}
        recipes = self._trader(config, AFTER)._selected_cooking_recipes()
        self.assertEqual(("凯洛养身汤", "水果冰沙"), recipes[-2:])
        self.assertNotIn("巧克力面包", recipes)

    def test_all_unticked_cooks_none(self):
        recipes = self._trader({EXTRA_COOKING_KEY: []}, AFTER)._selected_cooking_recipes()
        self.assertEqual(FINAL_COOKING_RECIPE, recipes[-1])

    def test_all_six_are_ticked_by_default(self):
        from src.tasks.MapTradeTask import MapTradeTask

        task = MapTradeTask(SimpleNamespace(scene=None), SimpleNamespace())
        self.assertEqual(list(EXTRA_COOKING_RECIPES), task.default_config[EXTRA_COOKING_KEY])
        self.assertEqual(
            list(EXTRA_COOKING_RECIPES), task.config_type[EXTRA_COOKING_KEY]["options"]
        )


class RepeatBatchTest(unittest.TestCase):
    """One batch makes 10000 at most: the same dish again while it stays bright."""

    def _trader(self, outcomes):
        logs = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            config={},
            log_info=lambda message, **_k: logs.append(("info", message)),
            log_warning=lambda message, **_k: logs.append(("warning", message)),
            info_set=lambda *_a: None,
        )
        trader._status = lambda *_a: None
        calls = []
        pending = iter(outcomes)

        def cook(recipe, *, again=False):
            calls.append((recipe, again))
            return next(pending)

        trader._cook_one_recipe = cook
        return trader, calls, logs

    def test_cooked_again_until_the_card_turns_grey(self):
        cooked, grey = CookingRecipeOutcome.COOKED, CookingRecipeOutcome.UNAVAILABLE
        trader, calls, logs = self._trader([cooked, cooked, grey])
        self.assertTrue(trader._cook_remaining_batches("香草牛排"))
        self.assertEqual([("香草牛排", True)] * 3, calls)
        self.assertIn(("info", "料理：香草牛排 材料还够，已做第3次。"), logs)

    def test_a_grey_card_right_away_cooks_nothing_more(self):
        trader, calls, logs = self._trader([CookingRecipeOutcome.UNAVAILABLE])
        self.assertTrue(trader._cook_remaining_batches("香草牛排"))
        self.assertEqual(1, len(calls))
        self.assertEqual([], [m for kind, m in logs if kind == "warning"])

    def test_a_card_no_longer_read_ends_it_without_failing(self):
        trader, calls, _logs = self._trader([CookingRecipeOutcome.ABSENT])
        self.assertTrue(trader._cook_remaining_batches("香草牛排"))

    def test_a_batch_that_fails_halfway_is_a_failure(self):
        trader, _calls, _logs = self._trader(
            [CookingRecipeOutcome.COOKED, CookingRecipeOutcome.FAILED]
        )
        self.assertFalse(trader._cook_remaining_batches("香草牛排"))

    def test_a_card_that_never_turns_grey_stops_at_the_limit(self):
        trader, calls, logs = self._trader([CookingRecipeOutcome.COOKED] * 200)
        self.assertTrue(trader._cook_remaining_batches("香草牛排"))
        self.assertEqual(COOKING_BATCH_LIMIT - 1, len(calls))
        self.assertTrue(any(kind == "warning" and "还是亮的" in m for kind, m in logs))

    def test_the_run_goes_on_to_the_next_dish_after_the_batches(self):
        cooked, grey = CookingRecipeOutcome.COOKED, CookingRecipeOutcome.UNAVAILABLE
        # 香草牛排: 3 batches then grey; 冰镇甜点: grey from the start.
        trader, calls, logs = self._trader([cooked, cooked, cooked, grey, grey])
        trader._selected_cooking_recipes = lambda: ("香草牛排", "冰镇甜点")
        trader._enter_cooking_list = lambda: setattr(trader, "_cooking_opened", True) or True
        trader._leave_cooking_to_q_sp6 = lambda: True
        trader._restore_skill_group = lambda **_k: None
        self.assertTrue(trader.run_cooking())
        self.assertEqual(
            [("香草牛排", False), ("香草牛排", True), ("香草牛排", True), ("香草牛排", True),
             ("冰镇甜点", False)],
            calls,
        )
        infos = [m for kind, m in logs if kind == "info"]
        self.assertIn("料理：本次已完成 香草牛排。", infos)
        self.assertTrue(any("这次跳过：冰镇甜点" in m for m in infos))

    def test_a_failed_later_batch_stops_the_run(self):
        cooked, failed = CookingRecipeOutcome.COOKED, CookingRecipeOutcome.FAILED
        trader, calls, logs = self._trader([cooked, failed])
        trader._selected_cooking_recipes = lambda: ("香草牛排", "冰镇甜点")
        trader._enter_cooking_list = lambda: setattr(trader, "_cooking_opened", True) or True
        trader._leave_cooking_to_q_sp6 = lambda: True
        trader._restore_skill_group = lambda **_k: None
        self.assertFalse(trader.run_cooking())
        self.assertEqual([("香草牛排", False), ("香草牛排", True)], calls)


if __name__ == "__main__":
    unittest.main()
