"""每日跑商 买: no favourites on the page (player v0.2.13 2026-10-25).

The player pressed 一键购买全部收藏 with every star gray: no confirm dialog
came, the tool pressed the fixed 确认 and stopped after 10 s with 「买：。」.
Now the gray stars stop 买 with the reason and 料理/卖 go on.
"""

import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from src.tasks import run_log, run_report
from src.tasks.map_trade.models import NavigationResult, ScreenState
from src.tasks.map_trade.navigator_trade import BARGAIN_PAID_MESSAGE
from src.tasks.map_trade.phase_ledger import PhaseDeferred, PhaseLedger
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_buy import NO_FAVORITES_MESSAGE
from src.tasks.map_trade.trader_constants import (
    BUY_ALL_FAVORITES_POINT,
    BUY_CONFIRM_FIRST_TIMEOUT,
    BUY_CONFIRM_TIMEOUT,
)
from src.tasks.map_trade.vision import Vision
from src.tasks.MapTradeTask import MapTradeTask
from src.tasks.run_history import _log_single_run

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "map_trade" / "trade_shop"


def _frame(name):
    frame = cv2.imread(str(FIXTURES / name), cv2.IMREAD_COLOR)
    assert frame is not None, name
    return frame


class _ShopTrader:
    def _trader(self, frame, *, left_ok=True):
        self.clicks = []
        self.warnings = []
        self.left = []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            config={"跑商识图阈值": 0.72},
            vision_threshold_key="跑商识图阈值",
            operate_click=lambda x, y, after_sleep=0: self.clicks.append((x, y)),
            sleep=lambda *_a: None,
            log_info=lambda *_a, **_k: None,
            log_warning=lambda message, **_k: self.warnings.append(message),
        )
        vision = Vision(trader.task)
        vision.capture = lambda: frame
        vision.click_client = lambda point, shape, after_sleep=0: self.clicks.append(point)
        trader.vision = vision
        trader._status = lambda *_a: None
        trader._wait_for_buy_all_favorites_state = lambda *_a: ((969, 669), frame)
        trader._wait_for_purchase_confirmation = lambda *_a, **_k: False
        trader._purchase_dialog_partly_read = lambda: False
        trader._sold_out_after_buy = lambda: False

        def leave():
            self.left.append(True)
            return NavigationResult(left_ok, ScreenState.MERCHANT_DIALOG, "离开商店失败：测试")

        trader.navigator = SimpleNamespace(leave_shop_to_merchant=leave)
        return trader


class TradeBuyNoFavoritesTest(_ShopTrader, unittest.TestCase):
    def test_all_gray_stars_stop_buy_with_reason_and_go_on(self):
        trader = self._trader(_frame("no_favorites_fhd.png"))

        result = trader.buy_all_favorites()

        self.assertIsInstance(result, PhaseDeferred)
        self.assertTrue(result.success)
        # Only 买 is skipped (料理 and 卖 go on), and the player is told
        # where to click (Leo 2026-10-28).
        self.assertTrue(result.skipped)
        self.assertIn("全是灰星", result.message)
        self.assertIn("右上角的星星点成黄色", result.message)
        self.assertTrue(any("点成黄色" in w for w in self.warnings), self.warnings)
        # The button pressed twice (the first may be swallowed), no fixed 确认.
        self.assertEqual([(969, 669), (969, 669)], self.clicks)
        self.assertEqual([True], self.left)

    def test_fixed_point_path_also_stops_on_gray_stars(self):
        trader = self._trader(_frame("no_favorites_fhd.png"))

        result = trader._buy_all_favorites_at_fixed_point()

        self.assertIsInstance(result, PhaseDeferred)
        # Only the button's fixed place (twice), not 确认's.
        self.assertEqual([BUY_ALL_FAVORITES_POINT, BUY_ALL_FAVORITES_POINT], self.clicks)

    def test_leaving_the_shop_fails_says_so(self):
        trader = self._trader(_frame("no_favorites_fhd.png"), left_ok=False)

        self.assertIs(False, trader.buy_all_favorites())
        self.assertIn("买：离开商店失败：测试", self.warnings)

    def test_a_yellow_star_keeps_the_old_fallbacks(self):
        trader = self._trader(_frame("before_purchase.png"))

        self.assertFalse(trader.buy_all_favorites())
        self.assertEqual([], self.left)
        # Re-press, then the fixed 确认 as before.
        self.assertEqual(3, len(self.clicks))

    def test_unread_stars_keep_the_old_fallbacks(self):
        trader = self._trader(np.zeros((1080, 1920, 3), dtype=np.uint8))

        self.assertFalse(trader.buy_all_favorites())
        self.assertEqual([], self.left)
        self.assertEqual(3, len(self.clicks))

    def test_sold_out_page_is_not_no_favourites(self):
        # 售罄 hides the bought stars; only the rest's gray stars are read.
        trader = self._trader(_frame("after_purchase.png"))

        trader.buy_all_favorites()

        self.assertEqual([], self.left)


class SwallowedPressTest(_ShopTrader, unittest.TestCase):
    """Audit 2026-10-28: the gray stars were judged right after the first
    press, so a press the game swallowed skipped 买 even when favourites sat
    on another cartridge's page (一键购买全部收藏 buys them all).  The button
    is now pressed once more first.  Each test fails on that code."""

    def _dialog_on(self, trader, nth):
        """The confirm dialog shows after the ``nth`` press; the waits' time
        limits are kept."""
        self.waits = []
        self.confirmed = []

        def wait(timeout=BUY_CONFIRM_TIMEOUT, **_k):
            self.waits.append(timeout)
            return len(self.waits) >= nth

        trader._wait_for_purchase_confirmation = wait
        trader._press_purchase_confirm = lambda: self.confirmed.append(True) or True

    def test_a_swallowed_press_on_an_all_gray_page_is_pressed_again_and_buys(self):
        trader = self._trader(_frame("no_favorites_fhd.png"))
        self._dialog_on(trader, 2)

        self.assertIs(True, trader.buy_all_favorites())

        self.assertEqual([(969, 669), (969, 669)], self.clicks)
        self.assertEqual([True], self.confirmed)
        self.assertEqual([], self.left)

    def test_the_fixed_point_is_pressed_again_too(self):
        trader = self._trader(_frame("no_favorites_fhd.png"))
        self._dialog_on(trader, 2)

        self.assertIs(True, trader._buy_all_favorites_at_fixed_point())

        self.assertEqual([BUY_ALL_FAVORITES_POINT, BUY_ALL_FAVORITES_POINT], self.clicks)
        self.assertEqual([True], self.confirmed)

    def test_every_wait_ends_before_the_stuck_guard(self):
        # The still shop page after a press counts toward the 10 s stuck
        # stop; the second wait was 10 s.
        trader = self._trader(_frame("before_purchase.png"))
        self._dialog_on(trader, 99)

        trader.buy_all_favorites()

        self.assertEqual(2, len(self.waits))
        self.assertTrue(all(wait <= BUY_CONFIRM_FIRST_TIMEOUT for wait in self.waits), self.waits)


class PaidBargainTest(unittest.TestCase):
    def test_a_bargain_naming_paid_currency_is_not_confirmed(self):
        # 循环砍价 refused it already; 每日跑商's 砍价 pressed 确认 whatever
        # the popup said (Leo: never spend paid stamina, diamonds, cocktails).
        calls, warnings = [], []
        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(
            config={},
            log_info=lambda *_a, **_k: None,
            log_warning=lambda message, **_k: warnings.append(message),
        )
        trader._status = lambda *_a: None
        trader.now_provider = lambda: datetime(2026, 10, 28, 12)

        def enter(**kwargs):
            calls.append(kwargs)
            return NavigationResult(False, ScreenState.UNKNOWN, BARGAIN_PAID_MESSAGE)

        trader.navigator = SimpleNamespace(enter_q_sp6_buy_flow=enter)

        self.assertIs(False, trader.run_buy())
        self.assertTrue(calls[0].get("refuse_paid"))
        self.assertIn(f"买：{BARGAIN_PAID_MESSAGE}", warnings)


def _skipped_buy():
    return PhaseDeferred(NO_FAVORITES_MESSAGE, skipped=True)


class _ReportFolder(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        run_report.set_report_file(str(Path(self.folder.name, "run_reports.json")))
        # Another test's batch left open would take this run's notes.
        run_report.finish(run_report.ENDED_STOPPED)

    def tearDown(self):
        run_report.set_report_file(None)
        self.folder.cleanup()


class SkippedBuyReportTest(_ReportFolder):
    """Leo 2026-10-28 「買跳過 不要整個跑商跳過」「要在報告說 請玩家去設定」."""

    def _task(self, statuses, actions):
        task = object.__new__(MapTradeTask)
        task.config = {"买": True, "卖": True, "制作料理": True}
        task.info_set = statuses.__setitem__
        task.log_info = lambda *_a, **_k: None
        task.log_warning = lambda *_a, **_k: None
        task.log_error = lambda *_a, **_k: None
        self.completions = []
        task.log_completion = lambda message, **_k: self.completions.append(message)
        task._save_diagnostic = lambda *_a: None
        task._return_home_after_phases = lambda _navigator: actions.append("home") or True
        return task

    def test_a_skipped_buy_is_listed_as_skipped_and_the_report_says_where_to_click(self):
        actions, statuses = [], {}
        task = self._task(statuses, actions)
        phases = (
            ("买", "买", lambda: actions.append("buy") or _skipped_buy()),
            ("制作料理", "制作料理", lambda: actions.append("cook") or True),
            ("卖", "卖", lambda: actions.append("sell") or True),
        )
        run_report.begin("测试批次", "all", [("每日跑商", "每日跑商")])
        run_report.row_started("每日跑商")

        self.assertTrue(task._run_phases(SimpleNamespace(), phases))
        run_report.row_ended("每日跑商", run_report.DONE)
        report = run_report.finish(run_report.ENDED_DONE)

        # 料理 and 卖 still run; only 买 is skipped, and not as 完成.
        self.assertEqual(["buy", "cook", "sell", "home"], actions)
        self.assertEqual("买", statuses["跳过"])
        self.assertEqual("制作料理、卖", statuses["完成"])
        self.assertEqual("-", statuses["失败"])
        # Not 「所有已开启流程完成」: 买 was on and not done.
        self.assertEqual("跑商完成，买跳过。", statuses["状态"])
        self.assertTrue(any("买跳过" in line for line in self.completions), self.completions)
        note = report["rows"][0]["note"]
        self.assertTrue(note.startswith("买跳过：商店里的商品全是灰星"), note)
        self.assertIn("进入梦幻广场，找商人洛兹，点「商店」", note)
        self.assertIn("右上角的星星点成黄色", note)

    def test_a_buy_that_bought_is_still_listed_as_done(self):
        actions, statuses = [], {}
        task = self._task(statuses, actions)
        phases = (
            ("买", "买", lambda: True),
            ("制作料理", "制作料理", lambda: True),
            ("卖", "卖", lambda: True),
        )
        self.assertTrue(task._run_phases(SimpleNamespace(), phases))
        self.assertEqual("买、制作料理、卖", statuses["完成"])
        self.assertEqual("-", statuses["跳过"])

    def test_cooking_after_a_skipped_buy_is_done_again_once_favourites_are_set(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = PhaseLedger(Path(folder) / "phases.json")
            trader = object.__new__(Trader)
            trader.run_buy = _skipped_buy
            trader.run_cooking = lambda: True
            trader.run_sell = lambda: True
            trader.left_shop = lambda: None
            task = object.__new__(MapTradeTask)
            task.config = {"启用": True}
            task.log_info = lambda *_a, **_k: None
            task.log_warning = lambda *_a, **_k: None
            task._return_home_after_phases = lambda _navigator: True
            outcomes = {}

            def run_phases(_navigator, phases, after_home=None):
                for name, _key, action in phases:
                    outcomes[name] = action()
                return True

            task._run_phases = run_phases
            with (
                patch("src.tasks.MapTradeTask.Vision"),
                patch("src.tasks.MapTradeTask.Navigator"),
                patch("src.tasks.MapTradeTask.ProgressStore"),
                patch("src.tasks.MapTradeTask.PhaseLedger", return_value=ledger),
                patch("src.tasks.MapTradeTask.Trader", return_value=trader),
            ):
                task.run()
            self.assertTrue(outcomes["买"].skipped)
            # It cooked (完成, not 跳过) but is not recorded for today.
            self.assertIsInstance(outcomes["制作料理"], PhaseDeferred)
            self.assertFalse(outcomes["制作料理"].skipped)
            self.assertIn("买这次跳过了", outcomes["制作料理"].message)
            self.assertFalse(ledger.done("买"))
            self.assertFalse(ledger.done("制作料理"))
            self.assertTrue(ledger.done("卖"))


class SingleRunNoteTest(_ReportFolder):
    """每日跑商 started on its own (not from 一键完成日常) shows the note in
    今日报表 too."""

    def test_a_single_runs_note_reaches_its_run_log_entry(self):
        started = time.time()
        run_report.add_current_note("买跳过：测试")
        _log_single_run(
            SimpleNamespace(name="每日跑商"), {}, True, started, time.time(), self.folder.name
        )
        entry = run_log.entries(folder=self.folder.name)[0]
        self.assertEqual(run_log.DONE, entry["state"])
        self.assertEqual("买跳过：测试", entry["note"])

    def test_a_failed_single_run_keeps_its_note_before_the_reason(self):
        started = time.time()
        run_report.add_current_note("买跳过：测试")
        _log_single_run(
            SimpleNamespace(name="每日跑商"),
            {"状态": "跑商部分流程未完成。"},
            False,
            started,
            time.time(),
            self.folder.name,
        )
        entry = run_log.entries(folder=self.folder.name)[0]
        self.assertEqual("买跳过：测试，跑商部分流程未完成。", entry["note"])

    def test_an_earlier_runs_note_is_not_picked_up(self):
        run_report.add_current_note("上一次的说明")
        later = time.time() + 60
        self.assertEqual("", run_report.loose_note(later, later + 10))


if __name__ == "__main__":
    unittest.main()
