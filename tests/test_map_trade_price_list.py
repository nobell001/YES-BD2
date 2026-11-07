"""The 价目表 (owned only) tells which planned items are worth a shop visit."""

import unittest
from unittest import mock
from types import SimpleNamespace

from src.tasks.map_trade.models import CalendarEntry
from src.tasks.map_trade.trader_price_list import owned_rates


def box(name, cx, cy, width=60, height=24):
    return SimpleNamespace(
        name=name, x=cx - width / 2, y=cy - height / 2, width=width, height=height
    )


def row(name, y, rate):
    # Positions from the user's demo (1080 reference, 2026-09-27).
    return [
        box(name, 830, y + 8),
        box("1,875", 800, y + 36),
        box("当前", 1110, y),
        box("2,250", 1220, y),
        box(f"↑{rate}%", 1320, y),
        box("剧情游戏卡16", 1440, y),
        box("每月27日", 1120, y + 42),
        box("↑120%", 1320, y + 42),
    ]


class OwnedRatesTest(unittest.TestCase):
    def test_only_todays_rate_counts_not_the_monthly_best(self):
        boxes = row("卢戈山参烤串", 394, 118) + row("火圣石", 504, 118)
        # Each row's 每月N日 line reads 120%; only 当前 matters.
        self.assertEqual([("卢戈山参烤串", False), ("火圣石", False)], owned_rates(boxes))

    def test_items_at_120_today(self):
        boxes = row("苹果", 394, 120) + row("穿山甲鳞片", 504, 120) + row("火圣石", 614, 118)
        self.assertEqual(
            [("苹果", True), ("穿山甲鳞片", True), ("火圣石", False)], owned_rates(boxes)
        )


class KeepOwnedTest(unittest.TestCase):
    def _trader(self, owned):
        from src.tasks.map_trade.trader import Trader

        trader = object.__new__(Trader)
        logs = []
        trader.task = SimpleNamespace(log_info=logs.append, log_warning=logs.append)
        trader.vision = SimpleNamespace(simplify=lambda value: value)
        trader.owned_items_at_max_rate = lambda: owned
        return trader, logs

    def test_planned_items_missing_from_the_bag_are_dropped(self):
        trader, logs = self._trader({"苹果"})
        entries = [CalendarEntry("苹果", "S6"), CalendarEntry("穿山甲鳞片", "S16")]
        self.assertEqual(["苹果"], [e.item for e in trader._keep_owned_at_max_rate(entries)])
        self.assertTrue(any("穿山甲鳞片" in message for message in logs))

    def test_nothing_at_120_means_nothing_to_sell(self):
        trader, _ = self._trader(set())
        self.assertEqual([], trader._keep_owned_at_max_rate([CalendarEntry("苹果", "S6")]))

    def test_an_unreadable_list_keeps_the_old_shop_search(self):
        trader, _ = self._trader(None)
        entries = [CalendarEntry("苹果", "S6")]
        self.assertEqual(entries, trader._keep_owned_at_max_rate(entries))

    def test_traditional_glyphs_still_match(self):
        trader, _ = self._trader({"蘋果"})
        kept = trader._keep_owned_at_max_rate([CalendarEntry("苹果", "S6")])
        self.assertEqual(["苹果"], [e.item for e in kept])

    def test_a_name_one_character_off_still_sells(self):
        # Audit #13: an OCR slip dropped a 120% item from the sale.
        trader, logs = self._trader({"穿山甲麟片"})
        kept = trader._keep_owned_at_max_rate([CalendarEntry("穿山甲鳞片", "S16")])
        self.assertEqual(["穿山甲鳞片"], [e.item for e in kept])
        self.assertFalse(any("不在今日清单" in message for message in logs))

    def test_a_cut_name_still_sells(self):
        trader, _ = self._trader({"山甲鳞片"})
        kept = trader._keep_owned_at_max_rate([CalendarEntry("穿山甲鳞片", "S16")])
        self.assertEqual(["穿山甲鳞片"], [e.item for e in kept])

    def test_a_different_item_is_not_taken_for_a_planned_one(self):
        trader, logs = self._trader({"火圣石"})
        kept = trader._keep_owned_at_max_rate([CalendarEntry("水圣石", "S6")])
        self.assertEqual([], kept)
        self.assertTrue(any("火圣石" in message and "不卖" in message for message in logs))

    def test_dropped_items_are_shown(self):
        statuses = {}
        trader, _ = self._trader({"苹果"})
        trader._status = statuses.__setitem__
        trader._keep_owned_at_max_rate([CalendarEntry("苹果", "S6"), CalendarEntry("火圣石", "S6")])
        self.assertEqual("火圣石", statuses["价目表未见"])

    def test_a_good_inside_another_goods_name_is_not_taken_for_it(self):
        # 铜块 sits inside 黄铜块, 巧克力 inside 巧克力鸡尾酒: exact names only.
        trader, logs = self._trader({"铜块", "巧克力"})
        kept = trader._keep_owned_at_max_rate(
            [CalendarEntry("黄铜块", "S6"), CalendarEntry("巧克力鸡尾酒", "S6")]
        )
        self.assertEqual([], kept)
        self.assertTrue(any("铜块" in message and "不卖" in message for message in logs))

    def test_a_loose_read_of_a_confusable_good_is_not_kept(self):
        trader, _ = self._trader({"炸三文鱼便"})
        self.assertEqual([], trader._keep_owned_at_max_rate([CalendarEntry("三文鱼", "S6")]))
        self.assertEqual(
            [], trader._keep_owned_at_max_rate([CalendarEntry("炸三文鱼便当", "S6")])
        )

    def test_the_exact_confusable_name_still_sells(self):
        trader, _ = self._trader({"黄铜块"})
        kept = trader._keep_owned_at_max_rate(
            [CalendarEntry("黄铜块", "S6"), CalendarEntry("铜块", "S6")]
        )
        self.assertEqual(["黄铜块"], [e.item for e in kept])


class KnownGoodsTest(unittest.TestCase):
    def test_every_known_name_names_only_its_own_good(self):
        from src.tasks.map_trade.trader import Trader
        from src.tasks.map_trade.trader_sell import confusable_goods, owned_name_owner

        trader = object.__new__(Trader)
        trader.vision = SimpleNamespace(simplify=lambda value: value)
        goods = trader._known_goods([])
        exact_only = confusable_goods(goods)
        self.assertIn("黄铜块", exact_only)
        self.assertIn("铜块", exact_only)
        self.assertNotIn("穿山甲鳞片", exact_only)
        for good, names in goods.items():
            for name in names:
                self.assertEqual(good, owned_name_owner(name, goods, exact_only), name)

    def test_traditional_one_character_sugar(self):
        from src.tasks.map_trade.trader_sell import SellFlowMixin

        names = ("白糖", "糖")
        # 繁中 shows 白糖 as 糖; a one-character name only as the whole box.
        self.assertTrue(SellFlowMixin._sale_name_matches("糖", names))
        self.assertTrue(SellFlowMixin._sale_name_matches("白糖", names))
        self.assertFalse(SellFlowMixin._sale_name_matches("红糖", ("糖",)))
        self.assertFalse(SellFlowMixin._sale_name_matches("棉花糖", ("糖",)))

    def test_a_short_fragment_of_a_long_name_does_not_count(self):
        from src.tasks.map_trade.trader_sell import owned_name_owner

        goods = {"维生素B浓缩液": ("vitaminbconcentrate",), "玉米": ("corn",)}
        self.assertIsNone(owned_name_owner("con", goods))


if __name__ == "__main__":
    unittest.main()


class PagingTest(unittest.TestCase):
    """The list glides on after a drag (Leo's 2K PC, 2026-10-12): a row
    skipped between two pages was taken as "not in the bag" and never sold."""

    ROWS = [
        ("卢戈山参烤串", True),
        ("钢铁块", True),
        ("普通布料", True),
        ("泥炭", True),
        ("巧克力", True),
        ("冰镇甜点", False),
        ("芥末", False),
    ]

    def _reader(self, forward_rows, back_rows=2):
        from src.tasks.map_trade.trader_price_list import PriceListMixin

        state = SimpleNamespace(top=0, drags=[])
        reader = object.__new__(PriceListMixin)
        logs = []
        reader.task = SimpleNamespace(
            log_warning=logs.append, operate_click=lambda *a, **k: None
        )
        reader._status = lambda *args: None
        reader._open_price_list = lambda: True
        reader._close_price_list = lambda: True
        reader._ticked_within = lambda seconds: True

        def settled():
            return list(self.ROWS[state.top : state.top + 4])

        def drag(back=False):
            state.drags.append("back" if back else "down")
            step = -back_rows if back else forward_rows
            state.top = max(0, min(len(self.ROWS) - 1, state.top + step))
            return True

        reader._settled_rows = settled
        reader._drag_price_list = drag
        return reader, state, logs

    def test_a_drag_that_overshoots_a_row_is_taken_back(self):
        reader, state, _ = self._reader(forward_rows=5)
        found = reader.owned_items_at_max_rate()
        self.assertIn("巧克力", found)
        self.assertEqual(["down", "back"], state.drags)

    def test_pages_sharing_a_row_need_no_drag_back(self):
        reader, state, _ = self._reader(forward_rows=3)
        found = reader.owned_items_at_max_rate()
        self.assertEqual({"卢戈山参烤串", "钢铁块", "普通布料", "泥炭", "巧克力"}, found)
        self.assertEqual(["down"], state.drags)

    def test_a_gap_that_stays_falls_back_to_the_shop_search(self):
        reader, _, logs = self._reader(forward_rows=6, back_rows=1)
        self.assertIsNone(reader.owned_items_at_max_rate())
        self.assertTrue(any("漏看" in message for message in logs))

    def test_still_all_at_120_on_the_last_page_falls_back(self):
        from src.tasks.map_trade import trader_price_list

        reader, _, logs = self._reader(forward_rows=1)
        with mock.patch.object(trader_price_list, "PRICE_LIST_MAX_PAGES", 2):
            self.assertIsNone(reader.owned_items_at_max_rate())
        self.assertTrue(any("没看完" in message for message in logs))

    def test_an_empty_page_after_a_drag_falls_back(self):
        reader, state, logs = self._reader(forward_rows=3)
        reader._settled_rows = lambda: [] if state.drags else list(self.ROWS[:4])
        self.assertIsNone(reader.owned_items_at_max_rate())
        self.assertTrue(any("没读到内容" in message for message in logs))
