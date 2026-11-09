"""Player v0.3.2 2026-11-08 (scheduled start, game not in front): in
格鲁菲餐厅 the way home pressed the top-left page title five times and H
never reached the game, so the rest of the daily was skipped.  The page's
own way home is the house at the top right, pressed with the mouse."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks import recovery
from src.tasks.map_trade.models import ScreenState

FIXTURE = Path(__file__).parent / "fixtures" / "field" / "restaurant_1080.jpg"


class _Task:
    config = {}

    def info_set(self, *_a):
        pass

    def log_info(self, *_a, **_k):
        pass


class HouseReadTest(unittest.TestCase):
    def setUp(self):
        from src.tasks.map_trade.vision import Vision

        self.vision = Vision(_Task())
        self.frame = cv2.imread(str(FIXTURE))
        self.assertIsNotNone(self.frame)

    def test_restaurant_house_is_found_at_every_size(self):
        for width, height in ((1920, 1080), (1280, 720), (2560, 1440), (3840, 2160)):
            frame = cv2.resize(self.frame, (width, height), interpolation=cv2.INTER_AREA if width < 1920 else cv2.INTER_CUBIC)
            found = recovery.top_right_home_button(self.vision, frame)
            self.assertIsNotNone(found, width)
            x, y = found.center
            self.assertAlmostEqual(1798 / 1920, x / width, delta=0.01)
            self.assertAlmostEqual(60 / 1080, y / height, delta=0.015)

    def test_house_hidden_behind_guests_found_by_its_h_badge(self):
        # 4K live test 2026-11-09: guests and plates behind the see-through
        # house dropped its match under the bar on 43 of 61 frames; the solid
        # 「H」 badge under it does not change.
        rng = np.random.default_rng(7)
        for width, height in ((1920, 1080), (2560, 1440), (3840, 2160)):
            frame = cv2.resize(self.frame, (width, height), interpolation=cv2.INTER_CUBIC if width > 1920 else cv2.INTER_AREA)
            top, bottom = round(25 / 1080 * height), round(80 / 1080 * height)
            left, right = round(1770 / 1920 * width), round(1826 / 1920 * width)
            noise = rng.integers(0, 255, (bottom - top, right - left, 3), dtype=np.uint8)
            frame[top:bottom, left:right] = (frame[top:bottom, left:right] * 0.4 + noise * 0.6).astype(np.uint8)
            found = recovery.top_right_home_button(self.vision, frame)
            self.assertIsNotNone(found, width)
            self.assertEqual("H", found.cue)
            x, y = found.center
            self.assertAlmostEqual(1798 / 1920, x / width, delta=0.01)
            self.assertAlmostEqual(61 / 1080, y / height, delta=0.01)

    def test_no_house_no_press(self):
        plain = np.full_like(self.frame, 120)
        self.assertIsNone(recovery.top_right_home_button(self.vision, plain))


class RecoveryPressesHouseTest(unittest.TestCase):
    def _run(self, house_works, house_seen=True):
        restaurant = np.full((1080, 1920, 3), 120, np.uint8)
        home = np.full((1080, 1920, 3), 200, np.uint8)
        state = {"frame": restaurant}
        clicks, keys, back = [], [], []

        def click_client(point, shape, after_sleep=0.0):
            clicks.append(point)
            if house_works:
                state["frame"] = home

        house = SimpleNamespace(score=0.91, center=(1798, 61), cue="house")
        vision = SimpleNamespace(capture=lambda: state["frame"], click_client=click_client)

        class FakeNavigator:
            def __init__(self, task, _vision):
                self.vision = vision

            def _home_confirmation_signals(self, frame):
                return (frame is home, 0, 0.0, "")

            def classify(self):
                return ScreenState.HOME if state["frame"] is home else ScreenState.UNKNOWN

            def clear_home_announcement(self, _frame, _clicks=0):
                return False

        task = SimpleNamespace(
            info_set=lambda *a: None,
            log_info=lambda *a, **k: None,
            log_warning=lambda *a, **k: None,
            sleep=lambda *_a: None,
            operate_click=lambda *a, **_k: back.append(tuple(a) if a else 1),
            # Not in front: no key reaches the game.
            tap_key=lambda key, after_sleep=0.0: keys.append(key) and False,
            tap_escape=lambda after_sleep=0.0: keys.append("Esc") and False,
            release_move_keys=lambda after_sleep=0.0: keys.append("移动键") and False,
        )
        with (
            mock.patch.object(recovery, "Navigator", FakeNavigator),
            mock.patch.object(recovery, "Vision", lambda task: SimpleNamespace(ocr_boxes=lambda *a, **k: [])),
            mock.patch.object(recovery, "_handle_dialog", lambda *_a: "none"),
            mock.patch.object(recovery, "_keep_failure_picture", lambda *_a: None),
            mock.patch.object(
                recovery, "top_right_home_button", lambda _v, frame: house if house_seen and frame is restaurant else None
            ),
            mock.patch.object(recovery, "monotonic", iter(range(0, 100000)).__next__),
        ):
            reached = recovery.recover_to_home(task)
        return reached, clicks, keys, back

    def test_house_brings_home_without_keys(self):
        reached, clicks, keys, back = self._run(house_works=True)
        self.assertTrue(reached)
        self.assertEqual([(1798, 61)], clicks)
        self.assertEqual([], keys)
        self.assertEqual([], back)

    def test_house_that_does_nothing_is_pressed_twice_then_the_old_ways(self):
        reached, clicks, keys, back = self._run(house_works=False)
        self.assertFalse(reached)
        self.assertEqual(recovery.TOP_RIGHT_HOME_PRESSES_MAX, len(clicks))
        self.assertTrue(back or keys)

    def test_unread_house_pressed_at_its_place_after_back_did_nothing(self):
        # The page with no top-left back (餐厅): its house's own spot, before H.
        reached, clicks, keys, back = self._run(house_works=False, house_seen=False)
        self.assertFalse(reached)
        from src.tasks.map_trade.home_house import HOUSE_POINT

        self.assertIn(HOUSE_POINT, back)

    def test_no_house_keeps_the_old_order(self):
        reached, clicks, keys, back = self._run(house_works=False, house_seen=False)
        self.assertFalse(reached)
        self.assertEqual([], clicks)
        self.assertTrue(back)


if __name__ == "__main__":
    unittest.main()
