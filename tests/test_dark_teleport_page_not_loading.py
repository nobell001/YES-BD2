"""Player v0.3.9 2026-11-10 (简中 1080p): 每周跑图 ran for an hour, chapters
8-19 「回主城失败」 one after another, nothing shown until the end.

The report's own last picture is 第19章's teleport page 「战斗Ⅱ 通往神殿之路」,
still open, while the tool's state read 「loading」 for 50 s: the page is so
dark (95th percentile 35) that the "black loading screen" rule (under 40)
took it for the loading screen.  A press on its circle that started no
teleport was therefore never pressed again, the wait ran its whole length,
and the page left open hid the field from every step that followed.
"""

import contextlib
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.map_trade.models import (
    CARD_BY_ID,
    MapPageMode,
    MatchResult,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PLAYER_PAGE = "map_trade/map_pages/ch19_dark_teleport_page_player_summary.jpg"
# Leo's 4K clone 2026-11-11, 1080p, the names carry the live p95 / p99.
LIVE = "map_trade/loading_live/"
LIVE_LOADING = (
    LIVE + "teleport_loading_black_p95_0_p99_0.jpg",
    LIVE + "teleport_loading_circle_small_p95_0_p99_37.jpg",
    LIVE + "teleport_loading_circle_large_p95_33_p99_75.jpg",
    LIVE + "cartridge_loading_grey_p95_22_p99_22.jpg",
)
DARK_PAGES = (
    PLAYER_PAGE,
    LIVE + "teleport_page_ch8_p95_33_p99_136.jpg",
    LIVE + "teleport_page_ch19_p95_29_p99_140.jpg",
    "map_trade/map_pages/direct.png",
    "map_trade/map_pages/generate.png",
    "map_trade/map_pages/ch7_town_teleport_page_player_summary.jpg",
)


def _read(relative):
    frame = cv2.imread(str(FIXTURES / relative))
    assert frame is not None, relative
    if frame.shape[1] != 1920:
        frame = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_CUBIC)
    return frame


def _navigator(frames=()):
    logs = []
    task = SimpleNamespace(
        config={},
        ocr=lambda **_k: [],
        info_set=lambda *_a: None,
        log_info=lambda text, **_k: logs.append(text),
        sleep=lambda *_a: None,
    )
    vision = Vision(task)
    looks = {"n": 0}

    def capture():
        looks["n"] += 1
        return frames[min(looks["n"], len(frames)) - 1]

    vision.capture = capture
    clicks = []
    vision.click_client = lambda center, *_a, **_k: clicks.append(tuple(center))
    navigator = Navigator(task, vision)
    navigator._status = lambda *_a: None
    navigator.logs, navigator.clicks = logs, clicks
    return navigator


class DarkPageIsNotLoadingTest(unittest.TestCase):
    def test_the_dark_rule_alone_calls_these_pages_black(self):
        # What went wrong: this is the old check, kept as the first half.
        for name in DARK_PAGES:
            with self.subTest(name=name):
                self.assertTrue(Navigator._black_frame(_read(name)))

    def test_a_dark_teleport_page_is_not_the_loading_screen(self):
        navigator = _navigator()
        for name in DARK_PAGES:
            with self.subTest(name=name):
                frame = _read(name)
                self.assertTrue(navigator._map_page_marks(frame))
                self.assertFalse(navigator._loading_black(frame))

    def test_the_black_loading_screen_still_is(self):
        navigator = _navigator()
        for frame in (
            _read("title/loading_logo_2k_clone.jpg"),
            np.full((1080, 1920, 3), 6, np.uint8),
        ):
            self.assertFalse(navigator._map_page_marks(frame))
            self.assertTrue(navigator._loading_black(frame))

    def test_live_loading_screens_are_loading(self):
        # The teleport's own loading screen draws a big circle: as bright
        # (p95 33) as a teleport page, and still not one.
        navigator = _navigator()
        for name in LIVE_LOADING:
            with self.subTest(name=name):
                frame = _read(name)
                self.assertFalse(navigator._map_page_marks(frame))
                self.assertTrue(navigator._loading_black(frame))

    def test_the_marks_show_on_no_other_page(self):
        import json

        pages = json.loads((FIXTURES / "pages.json").read_text(encoding="utf-8"))["pages"]
        navigator = _navigator()
        for name, kind in pages.items():
            with self.subTest(name=name):
                self.assertEqual(
                    kind == "teleport_map", navigator._map_page_marks(_read(name)), kind
                )

    def test_no_wait_for_loading_passes_on_the_open_page(self):
        navigator = _navigator([_read(PLAYER_PAGE)])
        self.assertFalse(navigator._wait_for_loading_screen(0.2))


class TeleportThatNeverStartedTest(unittest.TestCase):
    def _press(self, navigator):
        teleport = MatchResult(0.99, (1062, 338), (40, 40), pixel_score=0.98)
        return navigator._click_teleport_map_destination(
            teleport, (1080, 1920, 3), page_mode=MapPageMode.DIRECT_TELEPORT
        )

    def _patched(self, settle=0.05, grace=0.3, after_page=0.2):
        from unittest import mock

        base = "src.tasks.map_trade.navigator_sandbox."
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch(base + "TELEPORT_MAP_TRAVEL_SETTLE_SECONDS", settle))
        stack.enter_context(mock.patch(base + "TELEPORT_START_GRACE_SECONDS", grace))
        stack.enter_context(mock.patch(base + "TELEPORT_LOADING_AFTER_PAGE_SECONDS", after_page))
        return stack

    def test_page_still_up_after_both_presses_is_told_apart(self):
        navigator = _navigator([_read(PLAYER_PAGE)])
        with self._patched():
            self.assertFalse(self._press(navigator))
        self.assertEqual(2, len(navigator.clicks))
        self.assertFalse(navigator._teleport_loading_seen)

    def test_page_gone_after_the_first_press_is_not_pressed_again(self):
        # Live 4K clone 2026-11-11, 8 of 8 teleports: the page closed 0.1 s
        # after the press, the camera zoomed onto the circle for 2 s, then
        # the black screen.  The old 1.5 s wait for black pressed again,
        # onto the field.
        page = _read(PLAYER_PAGE)
        field = _read("map_trade/ch14_town_field_leo_tw.jpg")
        black = _read(LIVE + "teleport_loading_black_p95_0_p99_0.jpg")
        navigator = _navigator([page] + [field] * 30 + [black])
        with self._patched(settle=1.5, after_page=5.0):
            self.assertTrue(self._press(navigator))
        self.assertEqual(1, len(navigator.clicks))
        self.assertTrue(navigator._teleport_loading_seen)

    def test_one_unread_look_is_not_the_page_gone(self):
        page = _read(PLAYER_PAGE)
        field = _read("map_trade/ch14_town_field_leo_tw.jpg")
        navigator = _navigator([page, field, page])
        with self._patched():
            self.assertFalse(self._press(navigator))
        self.assertEqual(2, len(navigator.clicks))

    def test_a_dropped_press_is_pressed_again_and_its_loading_counts(self):
        page = _read(PLAYER_PAGE)
        black = np.full((1080, 1920, 3), 6, np.uint8)
        navigator = _navigator([page] * 40 + [black])
        with self._patched(grace=10.0):
            self.assertTrue(self._press(navigator))
        self.assertEqual(2, len(navigator.clicks))
        self.assertTrue(navigator._teleport_loading_seen)

    def test_a_page_that_gives_way_to_the_field_counts_as_started(self):
        # No black screen at all: started, and the area map confirms after.
        page = _read(PLAYER_PAGE)
        navigator = _navigator([page] * 40 + [_read("map_trade/ch14_town_field_leo_tw.jpg")])
        with self._patched(grace=10.0):
            self.assertTrue(self._press(navigator))
        self.assertFalse(navigator._teleport_loading_seen)

    def test_a_bright_page_whose_marks_are_not_read_is_pressed_as_before(self):
        # Nothing to judge "gone" by: the old rule (black screen or once
        # more) stays, and the run goes on to the arrival check.
        navigator = _navigator([_read("map_trade/ch14_town_field_leo_tw.jpg")])
        with self._patched():
            self.assertTrue(self._press(navigator))
        self.assertEqual(2, len(navigator.clicks))
        self.assertFalse(navigator._teleport_loading_seen)

    def test_a_teleport_that_starts_goes_on_as_before(self):
        black = np.full((1080, 1920, 3), 6, np.uint8)
        navigator = _navigator([black])
        self.assertTrue(self._press(navigator))
        self.assertEqual(1, len(navigator.clicks))
        self.assertTrue(navigator._teleport_loading_seen)

    def test_no_circle_found_on_the_page_of_the_map_one_stands_on(self):
        # Live 4K clone 2026-11-11: the character's marker covers the circle
        # of the map it is on; the page was left open and the card failed.
        card = CARD_BY_ID["Q_sp19"]
        target = card.targets[2]
        for here, arrived in ((target.key, True), (card.targets[1].key, False)):
            with self.subTest(here=here):
                navigator = _navigator([_read(PLAYER_PAGE)])
                closed = []
                navigator._close_confirmed_map_page = lambda modes, closed=closed, **_k: (
                    closed.append(modes) or NavigationResult(True, ScreenState.SANDBOX, "关了")
                )
                navigator.current_collection_target = lambda _card, here=here: here
                context = SimpleNamespace(
                    map_page_mode=MapPageMode.DIRECT_TELEPORT,
                    resolved_target_key=target.key,
                    teleports=(),
                    raw_text="战斗Ⅱ通往神殿之路",
                )
                result = navigator._click_collection_destination(card, target, context)
                self.assertEqual(arrived, result.success)
                self.assertEqual(1, len(closed))
                self.assertEqual([], navigator.clicks)
                if not arrived:
                    self.assertIn("未识别到传送阵", result.message)

    def _after(self, here):
        card = CARD_BY_ID["Q_sp19"]
        target = card.targets[2]
        navigator = _navigator([_read(PLAYER_PAGE)])
        closed = []
        navigator._close_confirmed_map_page = lambda modes, **_k: (
            closed.append(modes) or NavigationResult(True, ScreenState.SANDBOX, "关了")
        )
        navigator.current_collection_target = lambda _card: here
        navigator._last_position_header = "战斗亡灵游地"
        context = SimpleNamespace(map_page_mode=MapPageMode.DIRECT_TELEPORT)
        return navigator._after_teleport_that_never_started(card, target, context), closed

    def test_already_standing_on_the_target_is_an_arrival(self):
        result, closed = self._after(CARD_BY_ID["Q_sp19"].targets[2].key)
        self.assertTrue(result.success)
        self.assertEqual(1, len(closed))  # the page is never left over the field

    def test_elsewhere_fails_at_once_with_the_page_closed_and_the_reason(self):
        result, closed = self._after(CARD_BY_ID["Q_sp19"].targets[1].key)
        self.assertFalse(result.success)
        self.assertEqual(1, len(closed))
        self.assertIn("没有开始传送", result.message)
        self.assertIn("通往神殿之路", result.message)


class PageLeftOpenTest(unittest.TestCase):
    def test_a_teleport_page_over_the_field_is_closed_before_a_field_step(self):
        navigator = _navigator([_read("map_trade/map_pages/direct.png")])
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.DIRECT_TELEPORT
        )
        closed = []
        navigator._close_confirmed_map_page = lambda modes, **_k: (
            closed.append(modes) or NavigationResult(True, ScreenState.SANDBOX, "关了")
        )
        self.assertTrue(navigator._close_teleport_page_left_open())
        self.assertEqual([{MapPageMode.DIRECT_TELEPORT}], closed)

    def test_a_page_whose_kind_is_not_told_is_closed_by_esc(self):
        # The player's own last picture: the arrows and the 「移动魔法阵」
        # title read, the header icon does not, so the page's kind is unknown.
        navigator = _navigator([_read(PLAYER_PAGE)])
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.UNKNOWN, header_text="移动魔法阵"
        )
        keys = []
        navigator.task.tap_escape = lambda after_sleep=0.0: keys.append("esc") or True
        self.assertTrue(navigator._close_teleport_page_left_open())
        self.assertEqual(["esc"], keys)

    def test_a_mark_without_the_page_title_presses_nothing(self):
        navigator = _navigator([_read(PLAYER_PAGE)])
        navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
            mode=MapPageMode.UNKNOWN, header_text="战斗"
        )
        keys = []
        navigator.task.tap_escape = lambda after_sleep=0.0: keys.append("esc") or True
        self.assertFalse(navigator._close_teleport_page_left_open())
        self.assertEqual([], keys)

    def test_a_plain_field_is_left_alone_without_any_ocr(self):
        navigator = _navigator([_read("map_trade/ch14_town_field_leo_tw.jpg")])

        def no_ocr(_frame):
            raise AssertionError("the page check must not run on a plain field")

        navigator._detect_map_page_mode = no_ocr
        self.assertFalse(navigator._close_teleport_page_left_open())


if __name__ == "__main__":
    unittest.main()
