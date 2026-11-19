"""2K 桌面分身 2026-11-19, 繁中 client: a dish with more than 10000 to cook
goes in two batches.  The bar 「水果冰沙×10000」 of batch 1 stays a few
seconds, also over batch 2's 「製作中.. 6%」, and was taken as batch 2's
result: 返回 pressed while it cooked (the game ignores it), twice, then Esc;
~12 s lost per dish and the summary said ×20000 (real 18,132).
Frames: diag/place1119-2k full-run-66217aa/shots rec_141412 / rec_141418
(960x540, scaled back to 1920x1080).
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - CI without OCR
    ONNXPaddleOcr = None

from src.tasks.map_trade import trade_detail
from src.tasks.map_trade.trade_detail import TradeDetail
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_cooking import COOKING_EARLIER_BAR_HOLD_SECONDS
from src.tasks.map_trade.vision import Vision

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade"
OLD_BAR = "cooking_second_batch_tw_old_toast_2k_clone_as_1080.jpg"
COOKING = "cooking_second_batch_tw_in_progress_2k_clone_as_1080.jpg"
IDLE_DETAILS = (
    "cooking_detail_tw_2k_chocolate_bread_max.jpg",
    "cooking_detail_cn_2k_fruit_smoothie.jpg",
    "cooking_detail_cn_2k_dark_beer_stew.jpg",
)
RECIPE = "水果冰沙"


class _Task:
    def __init__(self):
        self.logs = []
        self.infos = []

    def log_info(self, message, **_kwargs):
        self.logs.append(("info", message))

    def log_warning(self, message, **_kwargs):
        self.logs.append(("warning", message))

    def info_set(self, key, value):
        self.infos.append((key, value))

    def sleep(self, _seconds):
        pass


def _scripted_trader(screens):
    """Each screen: (result bar text, centre text); the last one repeats."""
    task = _Task()
    trader = object.__new__(Trader)
    trader.task = task
    state = {"index": -1}

    def capture():
        state["index"] = min(state["index"] + 1, len(screens) - 1)
        return np.full((1080, 1920, 3), state["index"] % 250, dtype=np.uint8)

    def ocr_text(_frame, name, **_kwargs):
        bar, centre = screens[state["index"]]
        return centre if name.endswith("制作中") else bar

    trader.vision = SimpleNamespace(capture=capture, ocr_text=ocr_text, simplify=str)
    trader._cooking_detail_snapshot = lambda *_args: object()
    return trader, task, state


class SecondBatchResultTest(unittest.TestCase):
    def test_earlier_bar_over_the_next_batch_is_not_its_result(self):
        trader, _task, state = _scripted_trader(
            [
                ("水果冰沙×10000", "製作中..6%"),
                ("水果冰沙×10000", "製作中..12%"),
                ("", "製作中..76%"),
                ("水果冰沙×8132", ""),
            ]
        )
        frame = trader._wait_for_cooking_result(RECIPE, 40.0, earlier_bar="水果冰沙×10000")
        self.assertIsNotNone(frame)
        self.assertEqual(3, state["index"])
        self.assertEqual("水果冰沙×8132", trader._last_cooking_result_text)

    def test_same_count_again_counts_once_the_earlier_bar_was_gone(self):
        # Three batches: batch 3 makes 10000 again, after batch 2's bar faded.
        trader, _task, state = _scripted_trader(
            [
                ("水果冰沙×10000", "製作中..6%"),
                ("", "製作中..50%"),
                ("水果冰沙×10000", ""),
            ]
        )
        self.assertIsNotNone(
            trader._wait_for_cooking_result(RECIPE, 40.0, earlier_bar="水果冰沙×10000")
        )
        self.assertEqual(2, state["index"])

    def test_cooking_text_keeps_waiting_even_when_the_earlier_bar_was_missed(self):
        # Second check on its own: no earlier bar read before 开始.
        trader, _task, state = _scripted_trader(
            [
                ("水果冰沙×10000", "製作中..6%"),
                ("水果冰沙×10000", "製作中..9%"),
                ("", "製作中..80%"),
                ("水果冰沙×8132", ""),
            ]
        )
        trader._wait_for_cooking_result(RECIPE, 40.0)
        self.assertEqual(3, state["index"])
        self.assertEqual("水果冰沙×8132", trader._last_cooking_result_text)

    def test_quick_small_batch_is_still_taken_at_once(self):
        trader, _task, state = _scripted_trader([("香草牛排×97", "")])
        self.assertIsNotNone(trader._wait_for_cooking_result("香草牛排", 40.0))
        self.assertEqual(0, state["index"])

    def test_earlier_bar_that_never_leaves_times_out(self):
        trader, task, _state = _scripted_trader([("水果冰沙×10000", "")])
        self.assertIsNone(
            trader._wait_for_cooking_result(RECIPE, 0.0, earlier_bar="水果冰沙×10000")
        )
        self.assertTrue(any(level == "warning" for level, _ in task.logs))

    def test_quick_batch_of_the_same_size_is_taken_after_the_hold(self):
        # The earlier bar's count, never gone, no 「製作中」: after the hold
        # it is this batch's bar, not a 40 s timeout and a failed dish.
        clock = {"now": 0.0}
        trader, _task, _state = _scripted_trader([("水果冰沙×100", "")])
        trader.task.sleep = lambda seconds: clock.__setitem__("now", clock["now"] + seconds)
        with patch("src.tasks.map_trade.trader_cooking.monotonic", lambda: clock["now"]):
            frame = trader._wait_for_cooking_result(RECIPE, 40.0, earlier_bar="水果冰沙×100")
        self.assertIsNotNone(frame)
        self.assertGreaterEqual(clock["now"], COOKING_EARLIER_BAR_HOLD_SECONDS)
        self.assertLess(clock["now"], COOKING_EARLIER_BAR_HOLD_SECONDS + 1.0)

    def test_two_batches_add_up_to_the_real_count(self):
        owner = SimpleNamespace(trade_detail=TradeDetail())
        trade_detail.note_dish(owner, RECIPE, "水果冰沙×10000")
        trade_detail.note_dish(owner, RECIPE, "水果冰沙×8132")
        self.assertEqual(18132, owner.trade_detail.cooked[RECIPE])

    def test_bar_read_before_start_is_handed_to_the_wait(self):
        source = Path(__file__).parents[1] / "src" / "tasks" / "map_trade" / "trader_cooking.py"
        text = source.read_text(encoding="utf-8")
        before_click = text.index("earlier_bar = self._cooking_result_bar(ready.frame")
        click = text.index("ready.start_match.center", before_click)
        wait = text.index("earlier_bar=earlier_bar", click)
        self.assertLess(before_click, click)
        self.assertLess(click, wait)


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class SecondBatchRealFramesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True, use_npu=False)

    def _trader(self):
        engine = self.engine

        def ocr(*, frame, threshold=0.2, **_kwargs):
            boxes = []
            for points, (text, score) in engine.ocr(frame)[0] or []:
                if score < threshold:
                    continue
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                boxes.append(
                    SimpleNamespace(
                        name=text, x=min(xs), y=min(ys),
                        width=max(xs) - min(xs), height=max(ys) - min(ys), confidence=score,
                    )
                )
            return boxes

        task = SimpleNamespace(
            config={},
            vision_threshold_key="跑图跑商识图阈值",
            info_set=lambda *_a: None,
            log_info=lambda *_a, **_k: None,
            log_warning=lambda *_a, **_k: None,
            sleep=lambda *_a: None,
            ocr=ocr,
        )
        trader = object.__new__(Trader)
        trader.task = task
        trader.vision = Vision(task)
        return trader

    def _frame(self, name):
        frame = cv2.imread(str(FIXTURES / name))
        self.assertIsNotNone(frame, name)
        return frame

    def test_batch_one_bar_is_read_over_batch_two_cooking(self):
        trader = self._trader()
        frame = self._frame(OLD_BAR)
        bar = trader._cooking_result_bar(frame, RECIPE, "bar")
        self.assertEqual(10000, trade_detail.result_quantity(bar, RECIPE))
        self.assertTrue(trader._cooking_in_progress(frame, RECIPE))

    def test_cooking_text_is_read_without_a_bar(self):
        trader = self._trader()
        frame = self._frame(COOKING)
        self.assertEqual("", trader._cooking_result_bar(frame, RECIPE, "bar"))
        self.assertTrue(trader._cooking_in_progress(frame, RECIPE))

    def test_idle_detail_pages_are_not_cooking(self):
        trader = self._trader()
        for name in IDLE_DETAILS:
            with self.subTest(frame=name):
                self.assertFalse(trader._cooking_in_progress(self._frame(name), RECIPE))

    def test_live_frame_is_not_taken_as_batch_two_result(self):
        trader = self._trader()
        frame = self._frame(OLD_BAR)
        trader.vision.capture = lambda: frame
        trader._cooking_detail_snapshot = lambda *_args: object()
        # Even without the bar read before 开始, 「製作中」 alone holds it.
        for earlier in ("水果冰沙×10000", ""):
            with self.subTest(earlier=earlier):
                self.assertIsNone(
                    trader._wait_for_cooking_result(RECIPE, 0.0, earlier_bar=earlier)
                )


if __name__ == "__main__":
    unittest.main()
