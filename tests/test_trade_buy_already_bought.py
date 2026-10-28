"""每日跑商 that bought or sold nothing says why on the report (Leo 4K 2026-10-28).

An earlier run that day had bought all favourites (205 items).  The next
一键完成日常 saw 售罄, rightly did not press 购买, but its report said only
「完成」, so Leo read it as 「沒有按購買」.  The same run sold nothing on the
29th (the price table has nothing to sell on days 29-31) and said nothing
either: Leo 「報表要寫清楚 例如 29號不販售」.
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2

from src.tasks import run_report
from src.tasks.map_trade.models import CalendarEntry, NavigationResult, ScreenState
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_buy import ALREADY_BOUGHT_NOTE
from src.tasks.map_trade.vision import Vision

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "map_trade" / "trade_shop"


class AlreadyBoughtNoteTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        run_report.set_report_file(str(Path(self.folder.name, "run_reports.json")))
        run_report.finish(run_report.ENDED_STOPPED)

    def tearDown(self):
        run_report.set_report_file(None)
        self.folder.cleanup()

    def _trader(self, frame):
        self.clicks = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            config={"跑商识图阈值": 0.72},
            vision_threshold_key="跑商识图阈值",
            operate_click=lambda x, y, after_sleep=0: self.clicks.append((x, y)),
            sleep=lambda *_a: None,
            log_info=lambda *_a, **_k: None,
            log_warning=lambda *_a, **_k: None,
        )
        vision = Vision(trader.task)
        vision.capture = lambda: frame
        vision.ocr_boxes = lambda *_a, **_k: []
        vision.click_client = lambda point, shape, after_sleep=0: self.clicks.append(point)
        trader.vision = vision
        trader._status = lambda *_a: None
        trader._note_progress = lambda: None
        trader.now_provider = lambda: datetime(2026, 10, 29, 0, 38)
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda **_k: NavigationResult(True, ScreenState.SHOP, "")
        )
        return trader

    def test_a_sold_out_shop_is_not_pressed_and_the_report_says_why(self):
        frame = cv2.imread(str(FIXTURES / "after_purchase.png"), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        trader = self._trader(frame)
        run_report.begin("测试批次", "all", [("每日跑商", "每日跑商")])
        run_report.row_started("每日跑商")

        self.assertIs(True, trader.run_buy())
        run_report.row_ended("每日跑商", run_report.DONE)
        report = run_report.finish(run_report.ENDED_DONE)

        self.assertEqual([], self.clicks)
        note = report["rows"][0]["note"]
        self.assertIn("今天的商品已经买过了", note)
        self.assertIn("08:00", note)
        self.assertEqual(ALREADY_BOUGHT_NOTE, note)



class NothingToSellNoteTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        run_report.set_report_file(str(Path(self.folder.name, "run_reports.json")))
        run_report.finish(run_report.ENDED_STOPPED)

    def tearDown(self):
        run_report.set_report_file(None)
        self.folder.cleanup()

    def _trader(self, entries, **config):
        trader = object.__new__(Trader)
        # 00:38 on the 29th, as Leo's run: the 29th's table is in force.
        trader.started_at = datetime(2026, 10, 29, 0, 38)
        trader.calendar_client = SimpleNamespace(
            load=lambda **_k: SimpleNamespace(source="bundled", entries_for=lambda _day: entries)
        )
        trader.task = SimpleNamespace(
            config={"使用程序默认价表": True, "使用在线价表": True, "自定义最高价表": "", **config},
            log_info=lambda *_a, **_k: None,
            log_warning=lambda *_a, **_k: None,
            info_set=lambda *_a: None,
        )
        trader.select_shop_tab = lambda _shop: self.fail("nothing to sell, no shop opened")
        return trader

    def _note(self, trader):
        run_report.begin("测试批次", "all", [("每日跑商", "每日跑商")])
        run_report.row_started("每日跑商")
        self.assertIs(True, trader.run_sell())
        # The empty table is read again by a later step: said once.
        self.assertIs(True, trader.sell_max_price_items())
        run_report.row_ended("每日跑商", run_report.DONE)
        return run_report.finish(run_report.ENDED_DONE)["rows"][0]["note"]

    def test_the_bundled_table_has_nothing_on_days_29_to_31(self):
        table = Path(__file__).resolve().parents[1] / "assets" / "map_trade" / "price_calendar.v1.json"
        days = json.loads(table.read_text(encoding="utf-8"))["days"]
        self.assertEqual([[], [], []], [days[str(day)] for day in (29, 30, 31)])

    def test_a_day_with_nothing_to_sell_says_so(self):
        self.assertEqual("卖：29号不贩售", self._note(self._trader([])))

    def test_a_day_whose_goods_are_all_unticked_says_the_settings_left_nothing(self):
        trader = self._trader(
            [CalendarEntry("大麦", "S18:救赎")], **{"使用出售黑名单": True, "出售黑名单": "大麦"}
        )
        trader._sale_blacklist = lambda: {"大麦"}
        trader._entry_allowed = lambda _entry, _names: True
        note = self._note(trader)
        self.assertIn("29号", note)
        self.assertIn("出售设定", note)


if __name__ == "__main__":
    unittest.main()
