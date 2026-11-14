"""The sale table changes with the game's 2026-11-19 update.

Leo 2026-11-10: 「如果今天更新 賣的部分先維持舊的直到19號」 and
「19號之後我希望出售日曆可以自動換成新的」.  Both tables are bundled; the sale
date picks one, and the saved per-day ticks follow the table in use.
"""

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.tasks.map_trade import sale_days
from src.tasks.map_trade.calendar import UTC_PLUS_8, PriceCalendarClient
from src.tasks.map_trade.sale_days import (
    BUNDLED_CALENDAR_FILE,
    NEXT_CALENDAR_FILE,
    NEXT_TABLE,
    OLD_TABLE,
    SALE_TABLE_KEY,
    bundled_calendar_file,
    bundled_sale_days,
    carry_checklists_over,
    current_sale_date,
    day_items,
    every_bundled_entry,
    sale_day_key,
    table_for,
)
from src.tasks.map_trade.trader_sell import SellFlowMixin
from src.tasks.MapTradeTask import MapTradeTask

BEFORE = date(2026, 11, 18)
AFTER = date(2026, 11, 19)

REMOVED = {2: ["水果罐头"], 17: ["土豆"], 18: ["藏红花"], 22: ["凯洛药材"], 24: ["吐司", "啤酒花"]}
ADDED = {
    2: ["藏红花甜茶"],
    3: ["黑啤酒炖锅"],
    8: ["土豆汤"],
    17: ["凯洛养身汤", "水果冰沙"],
    25: ["巧克力面包"],
}


def _items(sale_date, day):
    return day_items(bundled_sale_days(sale_date).get(day, ()))


class TablePickedByDateTest(unittest.TestCase):
    def test_the_old_table_sells_until_the_18th(self):
        self.assertEqual(OLD_TABLE, table_for(date(2026, 11, 10)))
        self.assertEqual(OLD_TABLE, table_for(BEFORE))
        self.assertEqual(BUNDLED_CALENDAR_FILE, bundled_calendar_file(BEFORE))

    def test_the_new_table_sells_from_the_19th_on(self):
        self.assertEqual(NEXT_TABLE, table_for(AFTER))
        self.assertEqual(NEXT_TABLE, table_for(date(2027, 1, 2)))
        self.assertEqual(NEXT_CALENDAR_FILE, bundled_calendar_file(AFTER))

    def test_the_sale_day_starts_at_23_the_evening_before(self):
        evening = datetime(2026, 11, 18, 22, 59, tzinfo=UTC_PLUS_8)
        self.assertEqual(OLD_TABLE, table_for(current_sale_date(evening)))
        night = datetime(2026, 11, 18, 23, 0, tzinfo=UTC_PLUS_8)
        self.assertEqual(NEXT_TABLE, table_for(current_sale_date(night)))

    def test_what_the_update_removes_and_adds(self):
        for day in range(1, 32):
            old, new = _items(BEFORE, day), _items(AFTER, day)
            with self.subTest(day=day):
                self.assertEqual(sorted(REMOVED.get(day, [])), sorted(set(old) - set(new)))
                self.assertEqual(sorted(ADDED.get(day, [])), sorted(set(new) - set(old)))

    def test_the_19th_to_21st_are_the_same_in_both_tables(self):
        # So the exact switching moment cannot sell a wrong thing.
        for day in (19, 20, 21):
            self.assertEqual(
                bundled_sale_days(BEFORE)[day], bundled_sale_days(AFTER)[day]
            )

    def test_new_dishes_sell_in_their_shops(self):
        shops = {
            entry.item: entry.shop.split(":")[0]
            for entries in bundled_sale_days(AFTER).values()
            for entry in entries
        }
        want = {
            "藏红花甜茶": "S19",
            "黑啤酒炖锅": "R6",
            "土豆汤": "S8",
            "凯洛养身汤": "E1",
            "水果冰沙": "E1",
            "巧克力面包": "E1",
        }
        self.assertEqual(want, {item: shops[item] for item in want})

    def test_every_date_keeps_something_to_sell(self):
        self.assertEqual(set(bundled_sale_days(BEFORE)), set(bundled_sale_days(AFTER)))

    def test_names_of_both_tables_are_always_known(self):
        names = {entry.item for entry in every_bundled_entry()}
        self.assertLessEqual({"水果罐头", "啤酒花", "藏红花甜茶", "巧克力面包"}, names)

    def test_the_loader_reads_the_table_of_the_sale_date(self):
        client = PriceCalendarClient(
            bundled_path=bundled_calendar_file(BEFORE), bundled_for=bundled_calendar_file
        )
        client.use_table_for(BEFORE)
        self.assertEqual(["水果罐头"], day_items(client.load().entries_for(2)))
        client.use_table_for(AFTER)
        self.assertEqual(["藏红花甜茶"], day_items(client.load().entries_for(2)))

    def test_a_loader_with_one_table_keeps_it(self):
        client = PriceCalendarClient(bundled_path=BUNDLED_CALENDAR_FILE)
        client.use_table_for(AFTER)
        self.assertEqual(BUNDLED_CALENDAR_FILE, client.bundled_path)


class TicksCarriedOverTest(unittest.TestCase):
    def test_nothing_changes_before_the_19th(self):
        config = {sale_day_key(2): ["水果罐头"], sale_day_key(24): ["吐司"]}
        self.assertEqual([], carry_checklists_over(config, BEFORE))
        self.assertEqual({sale_day_key(2): ["水果罐头"], sale_day_key(24): ["吐司"]}, config)

    def test_new_items_are_ticked_and_unticked_ones_stay_unticked(self):
        config = {
            sale_day_key(2): ["水果罐头"],  # replaced by 藏红花甜茶
            sale_day_key(3): ["能量蘑菇", "橄榄油意面"],  # 火烤鱼板棒 unticked
            sale_day_key(17): [],  # everything unticked
            sale_day_key(24): ["袋装鸡胸肉", "吐司", "啤酒花", "辣椒"],
            sale_day_key(19): ["哈密瓜"],  # 杏仁 unticked, date unchanged
        }
        changed = carry_checklists_over(config, AFTER)
        self.assertEqual(["藏红花甜茶"], config[sale_day_key(2)])
        self.assertEqual(["能量蘑菇", "橄榄油意面", "黑啤酒炖锅"], config[sale_day_key(3)])
        self.assertEqual(["凯洛养身汤", "水果冰沙"], config[sale_day_key(17)])
        self.assertEqual(["袋装鸡胸肉", "辣椒"], config[sale_day_key(24)])
        self.assertEqual(["哈密瓜"], config[sale_day_key(19)])
        self.assertEqual(NEXT_TABLE, config[SALE_TABLE_KEY])
        self.assertIn(sale_day_key(2), changed)
        self.assertNotIn(sale_day_key(19), changed)

    def test_it_happens_only_once(self):
        config = {sale_day_key(17): ["米", "土豆", "泰瑞丝派"]}
        carry_checklists_over(config, AFTER)
        self.assertEqual(["米", "泰瑞丝派", "凯洛养身汤", "水果冰沙"], config[sale_day_key(17)])
        # The player then switches a new dish off: it stays off.
        config[sale_day_key(17)] = ["米", "泰瑞丝派", "水果冰沙"]
        self.assertEqual([], carry_checklists_over(config, AFTER))
        self.assertEqual(["米", "泰瑞丝派", "水果冰沙"], config[sale_day_key(17)])

    def test_dates_never_saved_get_everything_ticked(self):
        config = {}
        carry_checklists_over(config, AFTER)
        self.assertEqual(_items(AFTER, 25), config[sale_day_key(25)])

    def test_a_clock_set_back_goes_back_to_the_old_table(self):
        config = {sale_day_key(22): ["料酒"], SALE_TABLE_KEY: NEXT_TABLE}
        carry_checklists_over(config, BEFORE)
        self.assertEqual(["凯洛药材", "料酒"], config[sale_day_key(22)])
        self.assertEqual(OLD_TABLE, config[SALE_TABLE_KEY])

    def test_an_unreadable_new_table_changes_nothing(self):
        config = {sale_day_key(2): ["水果罐头"]}
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(sale_days, "NEXT_CALENDAR_FILE", Path(temp_dir) / "gone.json"):
                self.assertEqual([], carry_checklists_over(config, AFTER))
        self.assertEqual({sale_day_key(2): ["水果罐头"]}, config)

    def test_an_unreadable_old_table_never_ticks_what_was_off(self):
        config = {sale_day_key(3): ["能量蘑菇"]}
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(sale_days, "BUNDLED_CALENDAR_FILE", Path(temp_dir) / "gone.json"):
                carry_checklists_over(config, AFTER)
        self.assertEqual(["能量蘑菇"], config[sale_day_key(3)])


class SellFlowUsesTheTableOfTheDayTest(unittest.TestCase):
    def _trader(self, config, sale_date):
        logs = []
        trader = object.__new__(SellFlowMixin)
        trader.task = SimpleNamespace(config=config, log_info=logs.append)
        trader._status = lambda *_a: None
        trader._sale_calendar_date = sale_date
        return trader, logs

    def test_a_new_dish_is_sold_although_the_ticks_were_saved_before(self):
        # The app stayed open over the change: the ticks are carried at run time.
        config = {sale_day_key(2): ["水果罐头"]}
        sale_date = date(2026, 12, 2)
        trader, logs = self._trader(config, sale_date)
        entries = list(bundled_sale_days(sale_date)[2])
        keep = trader._apply_day_checklist(2, entries)
        self.assertEqual(["藏红花甜茶"], [entry.item for entry in keep])
        self.assertEqual(["藏红花甜茶"], config[sale_day_key(2)])

    def test_an_item_switched_off_before_is_still_not_sold_after(self):
        config = {sale_day_key(3): ["能量蘑菇", "橄榄油意面"]}
        sale_date = date(2026, 12, 3)
        trader, logs = self._trader(config, sale_date)
        keep = trader._apply_day_checklist(3, list(bundled_sale_days(sale_date)[3]))
        self.assertEqual(
            ["能量蘑菇", "橄榄油意面", "黑啤酒炖锅"], [entry.item for entry in keep]
        )
        self.assertIn("卖：火烤鱼板棒在3号出售清单中未勾选，不卖。", logs)

    def test_before_the_19th_the_old_items_are_sold(self):
        config = {sale_day_key(2): ["水果罐头"]}
        sale_date = date(2026, 11, 2)
        trader, _logs = self._trader(config, sale_date)
        keep = trader._apply_day_checklist(2, list(bundled_sale_days(sale_date)[2]))
        self.assertEqual(["水果罐头"], [entry.item for entry in keep])


class SettingsFollowTheTableTest(unittest.TestCase):
    def _launch(self, temp_dir, now):
        with patch("ok.util.config.Config.config_folder", temp_dir), patch.object(
            sale_days, "current_sale_date", lambda _now=None: now
        ):
            task = MapTradeTask(SimpleNamespace(scene=None), SimpleNamespace())
            task.load_config()
            return task

    def test_settings_saved_by_an_older_version_follow_the_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            saved = Path(temp_dir) / "MapTradeTask.json"
            saved.write_text(
                json.dumps({"出售3号": ["能量蘑菇", "橄榄油意面"], "出售2号": ["水果罐头"]}),
                encoding="utf-8",
            )
            # Updated on the 10th: nothing changes yet.
            task = self._launch(temp_dir, date(2026, 11, 10))
            self.assertEqual(["水果罐头"], task.config["出售2号"])
            self.assertEqual(OLD_TABLE, task.config[SALE_TABLE_KEY])
            # Opened again after the game's update.
            task = self._launch(temp_dir, date(2026, 11, 20))
            self.assertEqual(["藏红花甜茶"], task.config["出售2号"])
            self.assertEqual(["能量蘑菇", "橄榄油意面", "黑啤酒炖锅"], task.config["出售3号"])
            self.assertEqual(["鸡蛋", "透明沙拉", "巧克力面包"], task.config["出售25号"])
            stored = json.loads(saved.read_text(encoding="utf-8"))
            self.assertEqual(NEXT_TABLE, stored[SALE_TABLE_KEY])
            self.assertEqual(
                ["藏红花甜茶"], task.config_type["出售2号"]["options"]
            )

    def test_a_first_install_after_the_update_starts_with_the_new_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task = self._launch(temp_dir, date(2026, 11, 25))
            self.assertEqual(NEXT_TABLE, task.config[SALE_TABLE_KEY])
            self.assertEqual(["料酒"], task.config["出售22号"])

    def test_settings_first_saved_after_the_update_are_not_carried_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task = self._launch(temp_dir, date(2026, 11, 25))
            task.config["出售17号"] = ["米"]
            task = self._launch(temp_dir, date(2026, 11, 26))
            self.assertEqual(["米"], task.config["出售17号"])


if __name__ == "__main__":
    unittest.main()
