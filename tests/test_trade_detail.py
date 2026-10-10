"""What the trade sold and cooked shows under its row (YES-BD2 #6, 2026-10-10)."""

import os
import tempfile
import time
import unittest

from src.tasks import run_log, run_report
from src.tasks.map_trade import trade_detail
from src.tasks.map_trade.trade_detail import TradeDetail


class TradeDetailTest(unittest.TestCase):
    def test_sales_add_up_per_item_and_five_star_dishes_are_marked(self):
        detail = TradeDetail()
        detail.add_sale("兽肉", 990)
        detail.add_sale("兽肉", 990)
        detail.add_sale("红酒", None)
        detail.add_dish("香草牛排", 260)
        detail.add_dish("透明沙拉")
        detail.add_dish("香草牛排")
        self.assertEqual(
            {
                "sold": [["兽肉", 1980], ["红酒", None]],
                "cooked": [["香草牛排", 260], ["透明沙拉", None]],
            },
            detail.summary(),
        )
        self.assertEqual(
            "卖了 兽肉 ×1980、红酒；做了 香草牛排 ×260、5星 透明沙拉", detail.line()
        )

    def test_the_result_bar_gives_how_many_were_made(self):
        self.assertEqual(260, trade_detail.result_quantity("香草牛排×260"))
        self.assertEqual(1200, trade_detail.result_quantity("香草牛排 x 1,200"))
        self.assertEqual(12, trade_detail.result_quantity("香草牛排 12"))
        self.assertIsNone(trade_detail.result_quantity("香草牛排"))
        self.assertIsNone(trade_detail.result_quantity(""))

    def test_the_dish_made_before_on_the_bar_is_not_counted(self):
        # Live 2026-10-10 (1080p 桌面分身): the report said 冰镇甜点 ×98,
        # 鱼子酱蛋包饭 ×200 and 三明治便当 ×20.
        cases = (
            ("冰镇甜点", "冰镇甜点×50 香草牛排×98", 50),
            ("鱼子酱蛋包饭", "鱼子酱蛋包饭×150 蜂蜜黃油杏仁×200", 150),
            ("三明治便当", "三明治便当×7 橄榄油意面×20", 7),
            ("蜂蜜黄油杏仁", "鱼子酱蛋包饭×150 蜂蜜黃油杏仁×200", 200),
            ("街头烤鸡肉串", "街头烤鸡肉串×57", 57),
        )
        for recipe, text, expected in cases:
            with self.subTest(recipe=recipe):
                self.assertEqual(expected, trade_detail.result_quantity(text, recipe))
        # A bar whose names cannot be read still gives its number.
        self.assertEqual(12, trade_detail.result_quantity("12", "香草牛排"))

    def test_an_owner_without_a_detail_is_left_alone(self):
        owner = object()
        trade_detail.note_sale(owner, "兽肉", 1)
        trade_detail.note_dish(owner, "香草牛排")

    def test_nothing_done_publishes_nothing(self):
        logged = []
        task = type("T", (), {"log_info": lambda self, m: logged.append(m)})()
        trade_detail.publish(task, TradeDetail())
        trade_detail.publish(task, None)
        self.assertEqual([], logged)


class TradeInReportTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        run_report.set_report_file(os.path.join(self.folder.name, "run_reports.json"))

    def tearDown(self):
        run_report.set_report_file(None)
        self.folder.cleanup()

    def _publish(self, sold, cooked):
        detail = TradeDetail()
        for item, quantity in sold:
            detail.add_sale(item, quantity)
        for recipe, quantity in cooked:
            detail.add_dish(recipe, quantity)
        task = type("T", (), {"log_info": lambda self, m: None})()
        trade_detail.publish(task, detail)

    def test_a_batch_row_keeps_the_trade_and_the_day_log_gets_it(self):
        run_report.begin(
            "一键完成日常", "all", [("每日跑商", "每日跑商"), ("领取邮件", "领取邮件")]
        )
        run_report.row_started("每日跑商")
        self._publish([("兽肉", 1980)], [("香草牛排", 260)])
        run_report.row_ended("每日跑商", run_report.DONE)
        run_report.row_started("领取邮件")
        run_report.row_ended("领取邮件", run_report.DONE)
        report = run_report.finish(run_report.ENDED_DONE)
        rows = {row["key"]: row for row in report["rows"]}
        trade = {"sold": [["兽肉", 1980]], "cooked": [["香草牛排", 260]]}
        self.assertEqual(trade, rows["每日跑商"]["trade"])
        self.assertNotIn("trade", rows["领取邮件"])
        entries = {e["name"]: e for e in run_log.entries(folder=self.folder.name)}
        self.assertEqual(trade, entries["每日跑商"]["trade"])
        self.assertNotIn("trade", entries["领取邮件"])

    def test_a_rerun_row_starts_without_the_last_trade(self):
        run_report.begin("一键完成日常", "all", [("每日跑商", "每日跑商")])
        run_report.row_started("每日跑商")
        self._publish([("兽肉", 1)], [])
        run_report.row_started("每日跑商")
        run_report.row_ended("每日跑商", run_report.FAIL, "没有做完")
        report = run_report.finish(run_report.ENDED_FAILED)
        self.assertNotIn("trade", report["rows"][0])

    def test_a_single_run_picks_up_its_trade(self):
        started = time.time()
        self._publish([], [("透明沙拉", 30)])
        self.assertEqual(
            {"sold": [], "cooked": [["透明沙拉", 30]]},
            run_report.loose_trade(started, time.time()),
        )
        self.assertIsNone(run_report.loose_trade(time.time() + 60, time.time() + 120))


class TradeLineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_items_with_counts_and_dishes_with_five_star_after_the_label(self):
        from src.ui.shell.trade_line import GoodsIcon, TradeLine
        from src.ui.shell.widgets import Text

        line = TradeLine()
        line.set_trade(
            {"sold": [["兽肉", 1980]], "cooked": [["香草牛排", 260], ["透明沙拉", None]]}
        )
        self.assertFalse(line.isHidden())
        texts = [label.text() for label in line.findChildren(Text)]
        self.assertIn("×1,980", texts)
        self.assertIn("5星", texts)
        tips = [icon.toolTip() for icon in line.findChildren(GoodsIcon)]
        self.assertEqual(["兽肉 ×1,980", "香草牛排 ×260", "透明沙拉"], tips)

    def test_no_trade_hides_the_line(self):
        from src.ui.shell.trade_line import TradeLine

        line = TradeLine()
        line.set_trade(None)
        self.assertTrue(line.isHidden())
        line.set_trade({"sold": [], "cooked": []})
        self.assertTrue(line.isHidden())


if __name__ == "__main__":
    unittest.main()
