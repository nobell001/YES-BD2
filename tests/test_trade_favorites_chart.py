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
        # 活动卡带 2 and 5: seven goods, the fourth is left alone (Leo 2026-11-14).
        self.assertEqual(chart_cells("E2"), [True, True, True, False, True, True, True])
        self.assertEqual(chart_cells("E5"), [True, True, True, False, True, True, True])
        for code in SHOP_PRODUCT_COUNTS:
            self.assertEqual(len(chart_cells(code)), SHOP_PRODUCT_COUNTS[code])


class SpareFavoritesNoteTest(unittest.TestCase):
    """Leo's trade sheet of 2026-11-19: high-price 蘑菇, 虾 and 袋装鸡胸肉 can be
    unfavourited once cooking leaves plenty; the 收藏清单 lists where they are."""

    def test_the_note_names_each_item(self):
        from src.ui.shell.trade_favorites import SPARE_FAVORITES_NOTE

        for words in ("蘑菇", "虾", "袋装鸡胸肉", "斜线"):
            self.assertIn(words, SPARE_FAVORITES_NOTE)

    def test_striped_cells_follow_leos_shop_screenshots(self):
        from src.tasks.map_trade.data import SHOP_SPARE_FAVORITE_POINTS
        from src.ui.shell.trade_favorites import chart_cells, chart_spare

        # 剧情卡带 3/13/16 淡水虾, 剧情卡带 3 蘑菇, 角色卡带 1 袋装鸡胸肉
        # (11-19 繁中 shop).  剧情卡带 13 蘑菇 and 角色卡带 7 袋装鸡胸肉 are
        # already left unfavourited, so they are not striped.
        self.assertEqual(
            {"S3": {3, 7}, "S13": {3}, "S16": {1}, "R1": {4}},
            {code: set(slots) for code, slots in SHOP_SPARE_FAVORITE_POINTS.items()},
        )
        for code in SHOP_SPARE_FAVORITE_POINTS:
            cells = chart_cells(code)
            with self.subTest(code=code):
                # Only favourited goods can be dropped.
                self.assertTrue(all(cells[index] for index in chart_spare(code)))
        self.assertFalse(chart_cells("S13")[6])  # 蘑菇
        self.assertFalse(chart_cells("R7")[3])  # 袋装鸡胸肉
        self.assertEqual(frozenset(), chart_spare("S1"))

    def test_it_is_translated(self):
        from pathlib import Path

        from src.ui.shell.trade_favorites import SPARE_FAVORITES_NOTE

        root = Path(__file__).resolve().parent.parent
        for lang in ("en_US", "ja_JP", "ko_KR", "zh_TW"):
            text = (root / "i18n" / lang / "LC_MESSAGES" / "ok.po").read_text(encoding="utf-8")
            for source in (SPARE_FAVORITES_NOTE, "有剩可取消"):
                with self.subTest(lang=lang, source=source):
                    start = text.index(f'msgid "{source}"\n')
                    msgstr = text[start:].split("\n")[1]
                    self.assertTrue(msgstr.startswith('msgstr "') and len(msgstr) > len('msgstr ""'))


if __name__ == "__main__":
    unittest.main()
