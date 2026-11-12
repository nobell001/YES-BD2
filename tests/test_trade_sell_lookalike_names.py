"""Selling one good never clicks a card of another good whose name holds it.

Player report 2026-11-12 (v0.3.11, 1920x1080): selling 巧克力 at ↑120%, the
list had 巧克力鸡尾酒 ↑110% top right.  Its name held 巧克力, the digit-free
↑ template fitted its ↑110% badge, it was the first card in reading order
(1656,182), so it was clicked; the dialog check saw 巧克力鸡尾酒 and the whole
day's selling stopped.
"""

import unittest
from types import SimpleNamespace

import numpy as np

from src.tasks.map_trade.models import CalendarEntry, MatchResult
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_sell import SaleItemCandidate


def text_box(name, x, y, width, height):
    return SimpleNamespace(name=name, confidence=0.99, x=x, y=y, width=width, height=height)


def marker(x, y):
    return MatchResult(0.99, (x, y), (52, 14), pixel_score=0.98, zncc_score=0.97)


def sale_trader(page_boxes, markers, crop_text=""):
    trader = object.__new__(Trader)
    trader._sale_title_catalog_cache = None
    crop_calls = []

    def ocr_boxes(_frame, name, **_kwargs):
        if name == "出售↑120%标志":
            crop_calls.append(name)
            return [text_box(crop_text, 5, 5, 50, 14)] if crop_text else []
        return page_boxes

    def match_all(_frame, _spec, search_roi=None, **_kwargs):
        left, top, width, height = search_roi
        return tuple(
            item
            for item in markers
            if left <= item.position[0]
            and top <= item.position[1]
            and item.position[0] + item.size[0] <= left + width
            and item.position[1] + item.size[1] <= top + height
        )

    trader.vision = SimpleNamespace(
        ocr_boxes=ocr_boxes,
        simplify=lambda value: value,
        match_all=match_all,
        threshold_for=lambda spec: spec.threshold,
    )
    trader.task = SimpleNamespace(info_set=lambda *_args: None)
    return trader, crop_calls


# The player's page at 1920x1080: 巧克力鸡尾酒 top right, 巧克力 further down.
PLAYER_PAGE = [
    text_box("4110%", 1491, 175, 52, 14),
    text_box("巧克力鸡尾酒", 1606, 171, 100, 23),
    text_box("4120%", 493, 555, 52, 14),
    text_box("巧克力", 604, 551, 50, 23),
]
PLAYER_MARKERS = (marker(1491, 175), marker(493, 555))


class LookalikeNameTests(unittest.TestCase):
    def test_player_page_never_offers_the_cocktail_for_chocolate(self):
        trader, _ = sale_trader(PLAYER_PAGE, PLAYER_MARKERS)
        found = trader._locate_sale_items(
            CalendarEntry("巧克力", "S4:眼镜与猫"), np.zeros((1080, 1920, 3), np.uint8)
        )
        self.assertEqual([(629, 562)], [item.center for item in found])

    def test_cocktail_name_alone_is_not_chocolate_even_with_a_120_badge(self):
        page = [text_box("4120%", 1491, 175, 52, 14), text_box("巧克力鸡尾酒", 1606, 171, 100, 23)]
        trader, _ = sale_trader(page, (marker(1491, 175),))
        self.assertEqual(
            [],
            trader._locate_sale_items(
                CalendarEntry("巧克力", "S4"), np.zeros((1080, 1920, 3), np.uint8)
            ),
        )

    def test_other_good_names_are_recognised_both_ways(self):
        trader, _ = sale_trader([], ())
        chocolate = CalendarEntry("巧克力", "S4")
        cocktail = CalendarEntry("巧克力鸡尾酒", "S4")
        self.assertTrue(trader._is_another_goods_name(chocolate, "巧克力鸡尾酒"))
        self.assertTrue(trader._is_another_goods_name(chocolate, "巧克力鸡尾"))  # cut read
        self.assertTrue(trader._is_another_goods_name(chocolate, "巧克力鸡尾酒食物"))
        self.assertFalse(trader._is_another_goods_name(chocolate, "巧克力"))
        self.assertFalse(trader._is_another_goods_name(chocolate, "巧克力食物"))
        self.assertTrue(trader._is_another_goods_name(cocktail, "巧克力"))
        self.assertFalse(trader._is_another_goods_name(cocktail, "巧克力鸡尾酒"))
        self.assertFalse(trader._is_another_goods_name(cocktail, "克力鸡尾酒"))

    def test_one_wrong_character_in_the_longer_name_is_still_another_good(self):
        trader, _ = sale_trader([], ())
        chocolate = CalendarEntry("巧克力", "S4")
        for misread in ("巧克力鸡尾洒", "巧克力鳮尾酒", "巧克力鸡屋酒", "巧克力鸡尾"):
            self.assertTrue(trader._is_another_goods_name(chocolate, misread), misread)
        self.assertTrue(trader._is_another_goods_name(CalendarEntry("铜块", "S1"), "苋铜块"))
        # Extra text that is not another good keeps the card.
        self.assertFalse(trader._is_another_goods_name(CalendarEntry("铜块", "S1"), "1铜块"))
        for extra in ("巧克力", "巧克力食物", "巧克力1633"):
            self.assertFalse(trader._is_another_goods_name(chocolate, extra), extra)

    def test_whole_class_of_lookalike_names_in_the_bundled_calendar(self):
        trader, _ = sale_trader([], ())
        catalog = trader._sale_title_catalog(CalendarEntry("巧克力", "S4"))
        pairs = [
            (short, long)
            for short in catalog
            for long in catalog
            if len(short) >= 2 and short != long and short in long
            and not catalog[short] & catalog[long]
        ]
        self.assertTrue(pairs)  # 巧克力/巧克力鸡尾酒, 土豆/土豆汤 ...
        for short, long in pairs:
            for good in catalog[short]:
                self.assertTrue(
                    trader._is_another_goods_name(CalendarEntry(good, "S1"), long),
                    f"{long} read as {good}",
                )
            for good in catalog[long]:
                self.assertFalse(
                    trader._is_another_goods_name(CalendarEntry(good, "S1"), long), long
                )


class BadgeRateTests(unittest.TestCase):
    def test_template_hit_on_a_badge_read_as_110_is_refused(self):
        page = [text_box("4110%", 493, 555, 52, 14), text_box("巧克力", 604, 551, 50, 23)]
        trader, crop_calls = sale_trader(page, (marker(493, 555),), crop_text="4110%")
        self.assertEqual(
            [],
            trader._locate_sale_items(
                CalendarEntry("巧克力", "S4"), np.zeros((1080, 1920, 3), np.uint8)
            ),
        )
        self.assertTrue(crop_calls)

    def test_badge_page_misread_but_crop_reads_120_is_kept(self):
        page = [text_box("4110%", 493, 555, 52, 14), text_box("巧克力", 604, 551, 50, 23)]
        trader, _ = sale_trader(page, (marker(493, 555),), crop_text="4120%")
        found = trader._locate_sale_items(
            CalendarEntry("巧克力", "S4"), np.zeros((1080, 1920, 3), np.uint8)
        )
        self.assertEqual(1, len(found))

    def test_unclear_badge_reads_keep_the_template_answer(self):
        for text in ("4129", "", "%", "12"):
            page = [text_box(text, 493, 555, 52, 14), text_box("巧克力", 604, 551, 50, 23)]
            trader, crop_calls = sale_trader(page, (marker(493, 555),))
            found = trader._locate_sale_items(
                CalendarEntry("巧克力", "S4"), np.zeros((1080, 1920, 3), np.uint8)
            )
            self.assertEqual(1, len(found), text)
            self.assertEqual([], crop_calls, text)


class WrongDialogTests(unittest.TestCase):
    def _trader(self, outcomes):
        trader = object.__new__(Trader)
        frame = np.zeros((1080, 1920, 3), np.uint8)
        logs, warnings, clicked = [], [], []
        trader.task = SimpleNamespace(
            config={},
            log_info=logs.append,
            log_warning=lambda message, **_kw: warnings.append(message),
            info_set=lambda *_args: None,
            sleep=lambda *_args: None,
        )
        trader._scroll_sale_list_to_top = lambda: None
        cards = [
            SaleItemCandidate(center=(1656, 182), name_box=None, percent_box=None),
            SaleItemCandidate(center=(629, 562), name_box=None, percent_box=None),
        ]
        trader._find_sale_item_candidates = lambda _entry: (list(cards), frame)
        trader._candidate_unmoved = lambda *_args: True
        trader._sale_dialog_shown = lambda *_args: True
        trader._close_sale_dialog = lambda: True
        remaining = list(outcomes)

        def sell(_entry, candidate, _frame, **_kw):
            clicked.append(candidate.center)
            outcome = remaining.pop(0)
            if outcome == "wrong":
                trader._sale_dialog_rejected = True
                return None
            trader._last_sale_cleared = True
            return outcome

        trader._sell_one_candidate = sell
        return trader, clicked, logs, warnings

    def test_wrong_item_dialog_tries_the_next_card(self):
        trader, clicked, logs, _ = self._trader(["wrong", (1633, True)])
        self.assertTrue(trader._sell_selected_entry(CalendarEntry("巧克力", "S4")))
        self.assertEqual([(1656, 182), (629, 562)], clicked)
        self.assertTrue(any("试下一张卡片" in line for line in logs))

    def test_every_card_wrong_skips_the_item_without_stopping_the_day(self):
        trader, clicked, _, warnings = self._trader(["wrong", "wrong"])
        self.assertFalse(trader._sell_selected_entry(CalendarEntry("巧克力", "S4")))
        self.assertEqual([(1656, 182), (629, 562)], clicked)
        self.assertTrue(trader._last_sale_unavailable)  # later items still sold
        self.assertTrue(any("别的商品" in line for line in warnings))


if __name__ == "__main__":
    unittest.main()
