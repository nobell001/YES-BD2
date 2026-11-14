"""跑商's 收藏清单 chart: every shop cartridge has a product count that agrees
with the table of cells to leave unfavourited."""

import unittest

from src.tasks.map_trade.data import (
    SHOP_CARTRIDGE_LABELS,
    SHOP_FAVORITE_POINTS,
    SHOP_PRODUCT_COUNTS,
    SHOP_UNFAVORITED_POINTS,
)


class FavoritesChartDataTest(unittest.TestCase):
    def test_every_cartridge_has_a_count(self):
        self.assertEqual(set(SHOP_PRODUCT_COUNTS), set(SHOP_CARTRIDGE_LABELS))
        self.assertEqual(set(SHOP_PRODUCT_COUNTS), set(SHOP_UNFAVORITED_POINTS))

    def test_counts_fit_the_shop_page(self):
        for code, count in SHOP_PRODUCT_COUNTS.items():
            with self.subTest(code=code):
                self.assertGreaterEqual(count, 1)
                self.assertLessEqual(count, len(SHOP_FAVORITE_POINTS))

    def test_unfavourited_cells_are_products(self):
        for code, skipped in SHOP_UNFAVORITED_POINTS.items():
            with self.subTest(code=code):
                self.assertTrue(all(1 <= slot <= SHOP_PRODUCT_COUNTS[code] for slot in skipped))

    def test_chart_cells(self):
        from src.ui.shell.trade_favorites import chart_cells

        # 剧情卡带 1: seven goods, the sixth is left alone.
        self.assertEqual(chart_cells("S1"), [True, True, True, True, True, False, True])
        # 剧情卡带 9: nothing worth favouriting.
        self.assertEqual(chart_cells("S9"), [False] * 8)
        # 角色卡带 4: everything.
        self.assertEqual(chart_cells("R4"), [True] * 8)
        for code in SHOP_PRODUCT_COUNTS:
            self.assertEqual(len(chart_cells(code)), SHOP_PRODUCT_COUNTS[code])


if __name__ == "__main__":
    unittest.main()
