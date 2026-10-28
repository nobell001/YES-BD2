"""跑图 navigation steps that gave up after one press now go through the
remedies of docs/dev-notes/bug-prevention.md (Leo 2026-10-28 「失敗都要有補救機制」
「在不降低穩定性的前提下 去讓以後出現更少的出錯機會」).

Each remedy runs only where the step used to give up, and only while the
screen the press was made on is still shown, so a step that worked before
works the same way.  Every test says what the step did before.
"""

import unittest
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.tasks.map_trade.models import MatchResult, NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_constants import (
    CHARACTER_CATEGORY_HIGHLIGHT_REGION,
    CHARACTER_CATEGORY_POINT,
    STORY_CATEGORY_HIGHLIGHT_REGION,
)
from src.utils.cartridge_quick_switch import QUICK_SWITCH_PAGE_LABELS
from src.utils.press_confirm import press_and_confirm


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class CategoryTabTest(unittest.TestCase):
    """The quick-switch bar's tab (剧情/角色/活动…).  Before: one click and
    3 s; a dropped click failed the step, and after a card that ended the
    whole 跑图 run (「完成后无法打开快速切换页：点击后未确认…类别高亮」)."""

    def _navigator(self, lit_after, *, bar_after=None):
        """The character tab lights after click number ``lit_after`` (None:
        never); the bar's tab names show until click ``bar_after``."""
        clock = FakeClock()
        clicks = []

        def text(_frame, _name):
            if bar_after is not None and len(clicks) >= bar_after:
                return ""
            return " ".join(QUICK_SWITCH_PAGE_LABELS)

        def highlight(_frame, region):
            if region == CHARACTER_CATEGORY_HIGHLIGHT_REGION:
                lit = lit_after is not None and len(clicks) >= lit_after
                return 0.084 if lit else 0.01
            return 0.079 if region == STORY_CATEGORY_HIGHLIGHT_REGION else 0.0

        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
            ocr_text=text,
            simplify=lambda value: value,
            bright_neutral_ratio=highlight,
        )
        logs = []
        task = SimpleNamespace(
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y)),
            sleep=clock.sleep,
            log_info=logs.append,
            log_warning=logs.append,
        )
        return Navigator(task, vision), clicks, clock, logs

    def _select(self, navigator, clock):
        with patch("src.tasks.map_trade.navigator_story.monotonic", clock):
            return navigator._select_story_category("character")

    def test_a_tab_that_lights_is_clicked_once(self):
        navigator, clicks, clock, _logs = self._navigator(lit_after=1)

        self.assertTrue(self._select(navigator, clock))
        self.assertEqual([CHARACTER_CATEGORY_POINT], clicks)

    def test_a_dropped_tab_click_is_made_once_more(self):
        # Before: False after the first click.
        navigator, clicks, clock, logs = self._navigator(lit_after=2)

        self.assertTrue(self._select(navigator, clock))
        self.assertEqual([CHARACTER_CATEGORY_POINT] * 2, clicks)
        self.assertTrue(any("再点一次" in line for line in logs))

    def test_a_tab_never_lit_is_clicked_twice_at_most(self):
        navigator, clicks, clock, logs = self._navigator(lit_after=None)

        self.assertFalse(self._select(navigator, clock))
        self.assertEqual(2, len(clicks))
        self.assertTrue(any("未确认角色游戏卡类别高亮" in line for line in logs))

    def test_no_second_click_once_the_bar_is_gone(self):
        # Whatever is on screen now, a second click could land on it.
        navigator, clicks, clock, _logs = self._navigator(lit_after=None, bar_after=1)

        self.assertFalse(self._select(navigator, clock))
        self.assertEqual(1, len(clicks))


class AreaMapCloseTest(unittest.TestCase):
    """Closing the area map.  Before: its back arrow, once more, then a
    warning with the map still open; it covered the ≡ button and the next
    field steps (player 1080p 2026-10-23, 第9章)."""

    def _navigator(self, *, closes_on, esc_sent=True):
        """The map closes on ``closes_on``: "back" (the first press), "esc",
        or None (never)."""
        clock = FakeClock()
        presses = []

        def header():
            if closes_on == "back" and presses:
                return ""
            if closes_on == "esc" and "Esc" in presses:
                return ""
            return "卢戈森林 战斗区域"

        warnings = []
        task = SimpleNamespace(
            sleep=clock.sleep,
            operate_click=lambda x, y, after_sleep=0: presses.append("back"),
            tap_escape=lambda after_sleep=0: presses.append("Esc") or esc_sent,
            info_set=lambda *_a: None,
            log_info=lambda *_a: None,
            log_warning=warnings.append,
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator._field_map_header = header
        navigator._area_map_footer_shown = lambda: False
        return navigator, presses, clock, warnings

    def _close(self, navigator, clock):
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", clock):
            navigator._close_field_map()

    def test_a_map_the_back_arrow_leaves_open_is_closed_with_esc(self):
        # Before: ["back", "back"] and the map stayed open.
        navigator, presses, clock, warnings = self._navigator(closes_on="esc")

        self._close(navigator, clock)

        self.assertEqual(["back", "back", "Esc"], presses)
        self.assertEqual([], warnings)

    def test_no_esc_when_the_back_arrow_closed_it(self):
        navigator, presses, clock, _warnings = self._navigator(closes_on="back")

        self._close(navigator, clock)

        self.assertEqual(["back"], presses)

    def test_a_map_still_open_says_what_was_tried(self):
        for esc_sent, why in ((True, "按返回和 Esc 都没关掉"), (False, "按两次返回都没关掉")):
            with self.subTest(esc_sent=esc_sent):
                navigator, presses, clock, warnings = self._navigator(
                    closes_on=None, esc_sent=esc_sent
                )

                self._close(navigator, clock)

                self.assertEqual(["back", "back", "Esc"], presses)
                self.assertEqual(1, len(warnings))
                self.assertIn(why, warnings[0])


class AreaMapOpenTest(unittest.TestCase):
    """Opening the area map from the minimap (walks to a circle or an exit,
    and which of a card's maps the character is on).  Before: one press and
    4 s, then 「未能打开区域地图」; 跑商's copy already pressed M after it."""

    MAP = "战斗区域 卢戈森林"

    def _navigator(self, *, opens_on, keycaps=True, key_sent=True):
        """The map opens on ``opens_on``: "minimap" (its first press), "M",
        or None (never)."""
        clock = FakeClock()
        presses = []

        def header():
            return self.MAP if opens_on in presses else ""

        task = SimpleNamespace(
            sleep=clock.sleep,
            operate_click=lambda x, y, after_sleep=0: presses.append("minimap"),
            tap_key=lambda key, after_sleep=0: presses.append(key) or key_sent,
            info_set=lambda *_a: None,
            log_info=lambda *_a: None,
            log_warning=lambda *_a: None,
        )
        navigator = Navigator(task, SimpleNamespace())
        navigator._field_map_header = header
        navigator._area_map_footer_shown = lambda: False
        navigator._field_keycaps_shown = lambda *_a: keycaps
        return navigator, presses, clock

    def _open(self, navigator, clock):
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", clock):
            return navigator._open_field_map()

    def test_a_map_the_minimap_opens_gets_no_key(self):
        navigator, presses, clock = self._navigator(opens_on="minimap")

        self.assertEqual(self.MAP, self._open(navigator, clock))
        self.assertEqual(["minimap"], presses)

    def test_a_minimap_press_that_opened_nothing_is_followed_by_m(self):
        # Before: None after the press.
        navigator, presses, clock = self._navigator(opens_on="M")

        self.assertEqual(self.MAP, self._open(navigator, clock))
        self.assertEqual(["minimap", "M"], presses)

    def test_m_only_on_a_confirmed_field(self):
        for case, kwargs, keys in (
            ("no key caps (a page or 主页 is up)", {"keycaps": False}, []),
            ("key not sent", {"key_sent": False}, ["M"]),
            ("M opened nothing either", {}, ["M"]),
        ):
            with self.subTest(case):
                navigator, presses, clock = self._navigator(opens_on=None, **kwargs)

                self.assertIsNone(self._open(navigator, clock))
                self.assertEqual(["minimap", *keys], presses)


class NavMenuPressTest(unittest.TestCase):
    """The minimap's ≡ button before a trip (狩猎场 / 艾琳).  Before: one
    press; a press the game dropped left nothing to read and the trip failed
    「≡菜单里没读到狩猎场、艾琳，什么字都没读到」 (player 1080p 2026-10-19, 第3章:
    the ≡ trip failed three times, cause never read)."""

    def _navigator(self, *, opens_after, menu=("旅馆", "狩猎场", "艾琳")):
        """The menu lists ``menu`` after ≡ press number ``opens_after``
        (None: never) until a row is pressed."""
        clock = FakeClock()
        presses = []

        def menu_open():
            return opens_after is not None and presses.count("≡") >= opens_after

        def boxes(_frame, name, *_a, **_k):
            if name != "导航菜单" or not menu_open() or "row" in presses:
                return []
            return [
                SimpleNamespace(name=text, x=300, y=100 + 60 * row, width=80, height=30)
                for row, text in enumerate(menu)
            ]

        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
            ocr_boxes=boxes,
            ocr_text=lambda *_a, **_k: "",
            simplify=lambda value: value,
            click_template=lambda *_a, **_k: presses.append("≡") or True,
            click_client=lambda *_a, **_k: presses.append("row"),
        )
        logs = []
        task = SimpleNamespace(
            sleep=clock.sleep,
            info_set=lambda *_a: None,
            log_info=logs.append,
            log_warning=logs.append,
        )
        navigator = Navigator(task, vision)
        navigator._confirm_travel = lambda: "moving"
        navigator._wait_for_field_hud = lambda **_k: SimpleNamespace(success=True)
        navigator._wait_auto_move_finished = lambda _timeout: "done"
        navigator._loading_timeout = lambda: 1.0
        return navigator, presses, clock, logs

    def _travel(self, navigator, clock):
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", clock), patch(
            "src.tasks.map_trade.navigator_sandbox.press_and_confirm",
            partial(press_and_confirm, clock=clock),
        ):
            return navigator._travel_via_nav_menu("狩猎场", "艾琳")

    def test_a_menu_that_opens_is_pressed_once(self):
        navigator, presses, clock, _logs = self._navigator(opens_after=1)

        self.assertEqual("狩猎场", self._travel(navigator, clock))
        self.assertEqual(["≡", "row"], presses)

    def test_a_dropped_press_on_the_button_is_made_once_more(self):
        # Before: None after one press.
        navigator, presses, clock, logs = self._navigator(opens_after=2)

        self.assertEqual("狩猎场", self._travel(navigator, clock))
        self.assertEqual(["≡", "≡", "row"], presses)
        self.assertTrue(any("再按一次" in line for line in logs))

    def test_a_menu_that_never_opens_is_pressed_twice_at_most(self):
        navigator, presses, clock, _logs = self._navigator(opens_after=None)

        self.assertIsNone(self._travel(navigator, clock))
        self.assertEqual(["≡", "≡"], presses)
        self.assertIn("什么字都没读到", navigator._nav_failure)

    def test_an_open_menu_without_the_trip_is_not_pressed_again(self):
        # A second press would only close it.
        navigator, presses, clock, _logs = self._navigator(
            opens_after=1, menu=("旅馆", "招募", "商店")
        )

        self.assertIsNone(self._travel(navigator, clock))
        self.assertEqual(["≡"], presses)
        self.assertIn("读到：旅馆 招募 商店", navigator._nav_failure)


class CircleWalkTest(unittest.TestCase):
    """Walking to a circle picked on the area map, when the character is not
    on one.  Before: one press on the circle; a press the game dropped ended
    the walk 「箱庭大地图选择传送阵后未确认目的地按钮」.  At the circle, a hand
    that did not read ended it too 「徒步回退后仍未识别到传送阵交互按钮」 (the
    hand unread at a circle: player 1080p 125% 2026-10-17), and a town
    reached through 艾琳 had nothing after that."""

    TELEPORT = MatchResult(0.96, (500, 300), (40, 40), pixel_score=0.90, zncc_score=0.88)

    def _navigator(
        self, *, walks_after=1, walked="done", hand=True, keycaps=True, key_sent=True, opened=None
    ):
        """The walk starts on circle press number ``walks_after`` (None:
        never) and ends ``walked``; ``hand``: its hand reads at the circle.
        ``opened``: what the first press opened and never got further, the
        circle's 魔法阵 "menu" or the 自动移动 "question"."""
        clock = FakeClock()
        presses = []

        def walk_text(_frame):
            if walks_after is not None and presses.count("circle") >= walks_after:
                return "自动移动中魔法阵"
            return "是否自动移动前往所选目的地" if opened == "question" and presses else ""

        def boxes(_frame, name, *_a, **_k):
            if opened == "menu" and presses and name == "箱庭徒步导航传送阵菜单":
                return [SimpleNamespace(name="魔法阵", x=600, y=400, width=80, height=30)]
            return []

        def click(point, *_a, **_k):
            presses.append("circle" if point == self.TELEPORT.center else "menu row")

        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), np.uint8),
            ocr_boxes=boxes,
            simplify=lambda value: value,
            click_client=click,
        )
        logs = []
        task = SimpleNamespace(
            sleep=clock.sleep,
            info_set=lambda *_a: None,
            log_info=logs.append,
            log_warning=logs.append,
            tap_key=lambda key, after_sleep=0: presses.append(key) or key_sent,
        )
        navigator = Navigator(task, vision)
        navigator._open_field_map = lambda: "战斗Ⅱ剑之神殿左侧回廊"
        navigator._sandbox_navigation_page_has_keyword = lambda _frame: True
        navigator._sandbox_navigation_teleport = lambda _frame: self.TELEPORT
        navigator._walk_text = walk_text
        navigator._close_map_left_open_by_walk = lambda: False
        navigator._close_confirmed_map_page = lambda *_a, **_k: None
        navigator._close_field_map_if_open = lambda: None
        navigator._wait_auto_move_finished = lambda _timeout: walked
        navigator._loading_timeout = lambda: 1.0
        navigator._click_sandbox_teleport_interaction = lambda **_k: hand
        navigator._field_keycaps_shown = lambda: keycaps
        navigator._cancel_walk = lambda: False
        navigator._open_circle_page = lambda how: NavigationResult(
            True, ScreenState.SANDBOX_MAP, how
        )
        return navigator, presses, clock, logs

    def _walk(self, navigator, clock):
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", clock):
            return navigator._walk_to_sandbox_teleport_interaction()

    def test_a_circle_press_that_starts_the_walk_is_made_once(self):
        navigator, presses, clock, _logs = self._navigator()

        result = self._walk(navigator, clock)

        self.assertTrue(result.success, result.message)
        self.assertEqual("徒步回退交互", result.message)
        self.assertEqual(["circle"], presses)

    def test_a_circle_press_that_opened_nothing_is_made_once_more(self):
        # Before: failed after the first press.
        navigator, presses, clock, logs = self._navigator(walks_after=2)

        result = self._walk(navigator, clock)

        self.assertTrue(result.success, result.message)
        self.assertEqual(["circle", "circle"], presses)
        self.assertTrue(any("再点一次" in line for line in logs))

    def test_a_circle_press_that_never_takes_is_made_twice_at_most(self):
        navigator, presses, clock, _logs = self._navigator(walks_after=None)

        result = self._walk(navigator, clock)

        self.assertFalse(result.success)
        self.assertIn("未确认目的地按钮", result.message)
        self.assertEqual(["circle", "circle"], presses)

    def test_no_second_circle_press_once_the_press_opened_something(self):
        # A press on the map could land on what is up now.
        for opened in ("menu", "question"):
            with self.subTest(opened):
                navigator, presses, clock, _logs = self._navigator(
                    walks_after=None, opened=opened
                )

                result = self._walk(navigator, clock)

                self.assertFalse(result.success)
                self.assertEqual(1, presses.count("circle"))

    def test_an_unread_hand_at_the_end_of_the_walk_is_pressed_with_f(self):
        # Before: 「徒步回退后仍未识别到传送阵交互按钮」.
        navigator, presses, clock, logs = self._navigator(hand=False)

        result = self._walk(navigator, clock)

        self.assertTrue(result.success, result.message)
        self.assertEqual("走到传送阵后快捷键F", result.message)
        self.assertEqual(["circle", "F"], presses)
        self.assertTrue(any("改按快捷键 F" in line for line in logs))

    def test_no_f_unless_the_walk_ended_on_a_confirmed_field(self):
        for case, kwargs, keys in (
            ("walk never ended", {"walked": "timeout"}, []),
            ("no key caps (could be 主页)", {"keycaps": False}, []),
            ("key not sent", {"key_sent": False}, ["F"]),
        ):
            with self.subTest(case):
                navigator, presses, clock, _logs = self._navigator(hand=False, **kwargs)

                result = self._walk(navigator, clock)

                self.assertFalse(result.success)
                self.assertIn("徒步回退后仍未识别到传送阵交互按钮", result.message)
                self.assertEqual(["circle", *keys], presses)


if __name__ == "__main__":
    unittest.main()
