"""Player summary v0.2.15 2026-10-28 (4096×2160 at 175%, game 1920×1080
windowed): after 买 the merchant's 对话/商店 menu stayed open.  Its
「洛兹 欢迎光临!」 sits where the prompt beside him is read, so 「beside the
merchant」 passed on the menu, and 制作料理 then waited 10 s for the field
and failed: 「未同时确认箱庭与商人互动按钮，state=merchant_dialog」.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2

try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - CI without OCR
    ONNXPaddleOcr = None

from src.tasks.map_trade.models import NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision

FIXTURE = Path(__file__).parent / "fixtures" / "map_trade" / "merchant_menu_after_buy_summary.jpg"


def task_stub():
    logs = []
    return SimpleNamespace(
        config={},
        vision_threshold_key="跑图跑商识图阈值",
        info_set=lambda *_a: None,
        log_info=lambda message, **_k: logs.append(("info", message)),
        log_warning=lambda message, **_k: logs.append(("warning", message)),
        sleep=lambda *_a: None,
        logs=logs,
    )


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class MenuOnThePlayerFrameTest(unittest.TestCase):
    def test_the_open_menu_reads_as_the_menu_and_also_as_the_prompt(self):
        # The game picture of that summary, scaled back to 1920x1080.
        frame = cv2.imread(str(FIXTURE))
        self.assertIsNotNone(frame)
        engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True, use_npu=False)

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

        task = task_stub()
        task.ocr = ocr
        navigator = Navigator(task, Vision(task))
        navigator._status = lambda *_a: None
        navigator._home_confirmation_signals = lambda _frame: (False,)
        self.assertEqual(ScreenState.MERCHANT_DIALOG, navigator._classify_trade_frame(frame))
        # The cause: the prompt check alone is fooled by the menu.
        self.assertIsNotNone(navigator._merchant_prompt_box(frame))


def menu_navigator(closes_after):
    """The menu open until ``closes_after`` presses of its top-left control."""
    task = task_stub()
    navigator = Navigator(task, SimpleNamespace(capture=lambda: None))
    navigator._status = lambda *_a: None
    presses = []

    def state(*_a):
        return ScreenState.MERCHANT_DIALOG if len(presses) < closes_after else ScreenState.SANDBOX

    navigator._classify_trade_frame = state
    navigator.classify_trade = state
    navigator.classify = state
    navigator._merchant_prompt_box = lambda _frame: object()
    navigator._click_shop_close_control = lambda after_sleep=0.0: presses.append(after_sleep)
    return navigator, task, presses


class CookingWaitTest(unittest.TestCase):
    def test_the_wait_closes_the_menu_and_finds_the_field(self):
        navigator, task, presses = menu_navigator(closes_after=1)
        clock = iter(range(0, 1000))
        with mock.patch("src.tasks.map_trade.navigator_trade.monotonic", lambda: next(clock)):
            self.assertTrue(navigator.wait_for_q_sp6_sandbox(10.0))
        self.assertEqual(1, len(presses))
        self.assertTrue(any("对话/商店菜单还开着" in m for _k, m in task.logs))

    def test_a_probe_presses_nothing(self):
        navigator, _task, presses = menu_navigator(closes_after=1)
        self.assertFalse(navigator.wait_for_q_sp6_sandbox(0.0))
        self.assertEqual([], presses)


class LeaveShopTest(unittest.TestCase):
    def test_leaving_the_shop_closes_the_menu_before_the_prompt_counts(self):
        navigator, _task, presses = menu_navigator(closes_after=1)
        navigator._close_shop_to_field = lambda: NavigationResult(True, ScreenState.SANDBOX)
        navigator._wait_for_merchant_prompt = lambda _t: True
        self.assertTrue(navigator.leave_shop_to_merchant().success)
        self.assertEqual(1, len(presses))

    def test_a_menu_that_will_not_close_says_so(self):
        navigator, _task, presses = menu_navigator(closes_after=99)
        navigator._close_shop_to_field = lambda: NavigationResult(True, ScreenState.SANDBOX)
        navigator._wait_for_merchant_prompt = lambda _t: self.fail("prompt read on the menu")
        clock = iter(range(0, 1000))
        with mock.patch("src.tasks.map_trade.navigator_trade.monotonic", lambda: next(clock)):
            result = navigator.leave_shop_to_merchant()
        self.assertFalse(result.success)
        self.assertIn("对话/商店菜单关不掉", result.message)
        # The standard order (press_next): the control, once more, then Esc
        # (this task stub has none).
        self.assertEqual(2, len(presses))

    def test_esc_is_the_last_try(self):
        navigator, task, presses = menu_navigator(closes_after=99)
        escapes = []
        task.tap_escape = lambda after_sleep=0.0: escapes.append(after_sleep) or True
        clock = iter(range(0, 1000))
        with mock.patch("src.tasks.map_trade.navigator_trade.monotonic", lambda: next(clock)):
            self.assertFalse(navigator.close_merchant_menu())
        self.assertEqual((2, 1), (len(presses), len(escapes)))

    def test_no_menu_no_press(self):
        navigator, _task, presses = menu_navigator(closes_after=0)
        navigator._close_shop_to_field = lambda: NavigationResult(True, ScreenState.SANDBOX)
        navigator._wait_for_merchant_prompt = lambda _t: True
        self.assertTrue(navigator.leave_shop_to_merchant().success)
        self.assertEqual([], presses)


class ShopEntryTest(unittest.TestCase):
    """The same menu before 买/卖: the shop is entered from it, not by
    pressing 「洛兹」 in it as if it were the prompt beside him."""

    def test_an_open_menu_is_used_as_it_is(self):
        navigator, _task, _presses = menu_navigator(closes_after=99)
        navigator._merchant_menu_in_frame = lambda _frame: True
        navigator.vision.click_client = lambda *_a, **_k: self.fail("pressed the menu")
        self.assertTrue(navigator._enter_q_sp6_shop(1.0, log_timeout=True))

    def test_f2_when_the_shop_bubble_is_unread(self):
        navigator, task, _presses = menu_navigator(closes_after=99)
        navigator._plain_shop_option_center = lambda _frame: None
        keys = []
        task.tap_key = lambda key, after_sleep=0.0: keys.append(key) or True
        clock = iter(range(0, 1000))
        with mock.patch("src.tasks.map_trade.navigator_trade.monotonic", lambda: next(clock)):
            self.assertTrue(navigator._click_plain_shop_option(2.0))
        self.assertEqual(["F2"], keys)


class FunctionKeyTest(unittest.TestCase):
    def test_tap_key_sends_f2(self):
        from src.tasks.BaseBD2Task import BaseBD2Task

        task = BaseBD2Task.__new__(BaseBD2Task)
        sent = []
        task._send_game_key = lambda code, _seconds: sent.append(code) or True
        task.info_set = lambda *_a: None
        task.sleep = lambda *_a: None
        self.assertTrue(task.tap_key("F2"))
        self.assertTrue(task.tap_key("h"))
        self.assertEqual([0x71, ord("H")], sent)
        with self.assertRaises(ValueError):
            task.tap_key("F13")


if __name__ == "__main__":
    unittest.main()
