"""Sale-item icons (出售日曆, 今天賣, 跑商 log) all sit on a clear background.

Leo 2026-11-23: in the 出售日曆 the 额外料理 (巧克力麵包, 鮭魚芥末壽司 ...)
showed a tan recipe-card square while every other item was a bare icon.
They had been given the cooking-list card art; now they use the same kind
of transparent item icon as the rest.  The icons are keyed by the 简中
item name from the price calendar, so 繁中 and 简中 pages show the same one.
"""

import json
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "assets" / "ui" / "items"
CALENDARS = ROOT / "assets" / "map_trade"


def _index() -> dict:
    return json.loads((ITEMS / "index.json").read_text(encoding="utf-8"))


class TradeItemIconTests(unittest.TestCase):
    def test_every_icon_file_exists(self):
        for name, file in _index().items():
            with self.subTest(name=name):
                self.assertTrue((ITEMS / file).is_file(), file)

    def test_every_icon_has_a_clear_background(self):
        for name, file in _index().items():
            with self.subTest(name=name, file=file):
                image = Image.open(ITEMS / file).convert("RGBA")
                w, h = image.size
                corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
                alphas = [image.getpixel(point)[3] for point in corners]
                self.assertEqual(alphas, [0, 0, 0, 0], "icon has a filled background")

    def test_extra_dishes_use_item_icons_not_recipe_cards(self):
        index = _index()
        for dish in ("凯洛养身汤", "藏红花甜茶", "水果冰沙", "巧克力面包", "黑啤酒炖锅", "土豆汤", "三文鱼芥末寿司"):
            with self.subTest(dish=dish):
                self.assertIn(dish, index)
                self.assertTrue(index[dish].startswith("icon_food"), index[dish])

    def test_every_calendar_item_has_an_icon(self):
        index = _index()
        for path in sorted(CALENDARS.glob("price_calendar*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in sorted(_calendar_items(data)):
                with self.subTest(calendar=path.name, item=item):
                    self.assertIn(item, index)


def _calendar_items(data) -> set[str]:
    return {entry["item"] for entries in data["days"].values() for entry in entries}


if __name__ == "__main__":
    unittest.main()
