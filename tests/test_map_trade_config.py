"""Map-trade config tests (split from test_map_trade.py)."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.tasks import MapCollectionTask as map_collection_task_module
from src.tasks import MapTradeTask as map_trade_task_module
from src.tasks.map_trade.models import (
    CollectionResult,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.progress import UTC_PLUS_8
from src.tasks.MapCollectionTask import MapCollectionTask
from src.tasks.MapTradeTask import (
    MAP_OCR_THRESHOLD_KEY,
    MAP_VISION_THRESHOLD_KEY,
    TRADE_OCR_THRESHOLD_KEY,
    TRADE_VISION_THRESHOLD_KEY,
    MapTradeTask,
    _migrate_collection_config,
    _trade_section_migration_values,
)


class MapTradeLegacyConfigTest(unittest.TestCase):
    def test_daily_trade_buys_then_cooks_then_sells_and_respects_switch(self):
        actions = []
        task = object.__new__(MapTradeTask)
        task.config = {
            "启用": True,
            "买": True,
            "卖": True,
        }
        task.info_set = lambda *_args: None
        task.log_info = lambda *_args, **_kwargs: None
        task.log_error = lambda *_args, **_kwargs: None
        task.log_warning = lambda *_args, **_kwargs: None
        task._save_diagnostic = lambda *_args: None

        class FakeProgress:
            def __init__(self):
                self.now_provider = lambda: datetime(2026, 7, 12, 12, tzinfo=UTC_PLUS_8)

            def load(self):
                return None

        class FakeNavigator:
            def __init__(self, *_args):
                pass

            def return_home(self):
                actions.append("home")
                return NavigationResult(True, ScreenState.HOME)

        class FakeTrader:
            def __init__(self, *_args):
                pass

            def run_cooking(self):
                actions.append("cook")
                return True

            def run_buy(self):
                actions.append("buy")
                return True

            def run_sell(self):
                actions.append("sell")
                return True

            def left_shop(self):
                actions.append("left shop")

        with (
            patch.object(map_trade_task_module, "Vision", lambda *_args: object()),
            patch.object(map_trade_task_module, "ProgressStore", FakeProgress),
            patch.object(map_trade_task_module, "Navigator", FakeNavigator),
            patch.object(map_trade_task_module, "Trader", FakeTrader),
            # Phase order and switches only; the per-period ledger has its own tests.
            patch.object(map_trade_task_module, "PhaseLedger", _NoLedger),
        ):
            self.assertTrue(MapTradeTask.run(task))
            # Buy first: today's ingredients are cooked today (user, 2026-09-28).
            self.assertEqual(["buy", "cook", "sell", "home"], actions)
            actions.clear()
            task.config["制作料理"] = False
            self.assertTrue(MapTradeTask.run(task))
            self.assertEqual(["buy", "sell", "home"], actions)
            actions.clear()
            task.config["制作料理"] = True
            with patch.object(FakeTrader, "run_cooking", lambda _: False):
                self.assertFalse(MapTradeTask.run(task))
            # Audit #14: a failed 料理 no longer costs the day's 卖.
            self.assertEqual(["buy", "home", "left shop", "sell", "home"], actions)


class _NoLedger:
    def once(self, _phase, action, **_kwargs):
        return action


class MapTradeConfigTest(unittest.TestCase):
    def test_weekly_map_task_runs_collection_without_trade(self):
        actions = []
        task = object.__new__(MapCollectionTask)
        task.config = {"启用": True, "执行地图采集": True}
        task.info_set = lambda *_args: None
        task.log_info = lambda *_args, **_kwargs: None
        task.log_error = lambda *_args, **_kwargs: None
        task.log_warning = lambda *_args, **_kwargs: None
        task._save_diagnostic = lambda *_args: None

        class FakeProgress:
            def load(self):
                return None

        class FakeNavigator:
            def __init__(self, *_args):
                pass

            def return_home(self):
                actions.append("home")
                return NavigationResult(True, ScreenState.HOME)

        class FakeCollector:
            def __init__(self, *_args):
                pass

            def run(self):
                actions.append("collection")
                return CollectionResult(True)

        with (
            patch.object(map_collection_task_module, "Vision", lambda *_args: object()),
            patch.object(map_collection_task_module, "ProgressStore", FakeProgress),
            patch.object(map_collection_task_module, "Navigator", FakeNavigator),
            patch.object(map_collection_task_module, "Collector", FakeCollector),
        ):
            self.assertTrue(MapCollectionTask.run(task))

        self.assertEqual(["collection", "home"], actions)

    def test_daily_and_weekly_cards_expose_separate_configurations(self):
        executor = SimpleNamespace(scene=None)
        app = SimpleNamespace()
        trade = MapTradeTask(executor, app)
        collection = MapCollectionTask(executor, app)

        self.assertEqual("每日跑商", trade.name)
        self.assertEqual("每周跑图", collection.name)
        self.assertIn("买", trade.default_config)
        self.assertIn("卖", trade.default_config)
        self.assertIn("料理", trade.description)
        for mapping_name in ("default_config", "config_description"):
            with self.subTest(mapping=mapping_name):
                self.assertIn("制作料理", getattr(trade, mapping_name))
                self.assertNotIn("料理制作周期", getattr(trade, mapping_name))
                self.assertNotIn("料理保险", getattr(trade, mapping_name))
                self.assertIn("5星料理", getattr(trade, mapping_name))
        self.assertTrue(trade.default_config["制作料理"])
        self.assertEqual([], trade.default_config["5星料理"])
        self.assertEqual(
            ["料理清单", "5星料理"], trade.config_type["制作料理"]["sub_configs"][True]
        )
        # Every regular dish is selectable and ticked by default (review 2026-09-27).
        self.assertIn("街头烤鸡肉串", trade.default_config["料理清单"])
        self.assertEqual(10, len(trade.default_config["料理清单"]))
        self.assertEqual("multi_selection", trade.config_type["5星料理"]["type"])
        keys = list(trade.default_config)
        self.assertLess(keys.index("制作料理"), keys.index("买"))
        self.assertLess(keys.index("买"), keys.index("卖"))
        self.assertNotIn("执行跑商", trade.default_config)
        self.assertNotIn("执行地图采集", trade.default_config)
        self.assertIn("执行地图采集", collection.default_config)
        self.assertNotIn("买", collection.default_config)
        self.assertNotIn("卖", collection.default_config)
        self.assertNotIn("制作料理", collection.default_config)
        self.assertIn(TRADE_VISION_THRESHOLD_KEY, trade.default_config)
        self.assertIn(TRADE_OCR_THRESHOLD_KEY, trade.default_config)
        self.assertIn(MAP_VISION_THRESHOLD_KEY, collection.default_config)
        self.assertIn(MAP_OCR_THRESHOLD_KEY, collection.default_config)

        # Leo 2026-10-05 removed 收藏重建周期 and 出售保险 from the settings:
        # the favourites are never rebuilt and every normal stack sells MAX.
        self.assertNotIn("收藏重建周期", trade.default_config)
        self.assertNotIn("出售保险", trade.default_config)
        self.assertNotIn("买", trade.config_type)
        # Only the user's sheet and its per-day checklist decide what is
        # sold; the whitelist, blacklist and other price tables are gone
        # (user, 2026-09-27).
        self.assertEqual(
            [f"出售{day}号" for day in range(1, 29)],
            trade.config_type["卖"]["sub_configs"][True],
        )
        self.assertEqual(["杏仁", "哈密瓜"], trade.default_config["出售19号"])
        self.assertEqual(
            {"type": "multi_selection", "options": ["杏仁", "哈密瓜"]},
            trade.config_type["出售19号"],
        )
        self.assertIn("杏仁→R1:杰登之门（保留5000）", trade.config_description["出售19号"])
        self.assertNotIn("出售29号", trade.default_config)
        for removed in (
            "使用程序默认价表", "使用在线价表", "自定义最高价表",
            "使用出售白名单", "出售白名单", "使用出售黑名单", "出售黑名单",
        ):
            self.assertNotIn(removed, trade.default_config)

    def test_legacy_trade_switches_migrate_to_three_sections(self):
        self.assertEqual(
            {"买": False, "卖": True},
            _trade_section_migration_values(
                {
                    "执行跑商": True,
                    "低价进货": False,
                    "最高价出售": True,
                    "制作利润料理": False,
                }
            ),
        )
        self.assertEqual(
            {"买": False, "卖": False},
            _trade_section_migration_values(
                {
                    "执行跑商": False,
                    "低价进货": True,
                    "最高价出售": True,
                    "制作利润料理": True,
                }
            ),
        )

    def test_legacy_combined_config_seeds_weekly_card(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "MapCollectionTask.json"
            legacy = {
                "启用": False,
                "执行地图采集": False,
                "跑图跑商识图阈值": 0.83,
                "跑图跑商 OCR 阈值": 0.31,
                "加载页面等待秒数": 61.0,
                "卡带单步重试次数": 4,
            }
            with patch.object(map_trade_task_module, "_config_path", return_value=target):
                _migrate_collection_config(legacy)

            migrated = json.loads(target.read_text(encoding="utf-8"))
            self.assertFalse(migrated["启用"])
            self.assertFalse(migrated["执行地图采集"])
            self.assertEqual(0.83, migrated[MAP_VISION_THRESHOLD_KEY])
            self.assertEqual(0.31, migrated[MAP_OCR_THRESHOLD_KEY])
            self.assertEqual(61.0, migrated["加载页面等待秒数"])
            self.assertEqual(4, migrated["卡带单步重试次数"])

    def test_unreadable_price_table_keeps_the_saved_unticks(self):
        # 2026-10-09 review: a price table that cannot be read at start (an
        # update cut short, an antivirus scan) must not wipe the 不卖 choices.
        from src.tasks.map_trade import sale_days

        with tempfile.TemporaryDirectory() as temp_dir:
            saved = Path(temp_dir) / "MapTradeTask.json"
            saved.write_text(json.dumps({"出售19号": ["杏仁"]}), encoding="utf-8")

            def launch():
                task = MapTradeTask(SimpleNamespace(scene=None), SimpleNamespace())
                task.load_config()
                return task

            with patch("ok.util.config.Config.config_folder", temp_dir):
                missing = Path(temp_dir) / "price_calendar.v1.json"
                with patch.object(sale_days, "BUNDLED_CALENDAR_FILE", missing):
                    self.assertEqual(["杏仁"], launch().config["出售19号"])
                stored = json.loads(saved.read_text(encoding="utf-8"))
                self.assertEqual(["杏仁"], stored["出售19号"])
                # Readable again: still not sold.
                self.assertEqual(["杏仁"], launch().config["出售19号"])
