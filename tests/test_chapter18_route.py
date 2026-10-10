"""Chapter 18 route (Leo 2026-10-10): "艾琳到安全區 走到戰鬥一 傳送到戰鬥二",
"戰鬥二開始就 傳送到戰鬥一 然後 傳回艾琳", "在其他地方就 先傳回艾琳".

The safe area 科库托斯暗黑神殿 has no teleport circle; its 科库托斯圣域 exit
is walked.  The battle maps are the two that hold resources."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.tasks.map_trade.models import (
    CARD_BY_ID,
    RESTART_NAV_ENTRIES,
    TOWN_NAV_ENTRIES,
    WALK_LABEL_EDGES,
    CollectionMapRole,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator import Navigator

# Modules, not classes: imported test classes would run twice.
from tests import test_map_trade_collector as collector_tests
from tests import test_map_trade_navigator as navigator_tests

CARD = CARD_BY_ID["Q_sp18"]


class Chapter18TargetsTest(unittest.TestCase):
    def test_safe_area_then_the_two_battle_maps_with_resources(self):
        self.assertEqual(
            [
                (CollectionMapRole.MAIN_AREA, "科库托斯暗黑神殿"),
                (CollectionMapRole.BATTLE_AREA_1, "科库托斯圣域"),
                (CollectionMapRole.BATTLE_AREA_2, "第一记忆空间"),
            ],
            [(target.role, target.title) for target in CARD.targets],
        )

    def test_airin_for_the_way_back_and_for_restarts(self):
        self.assertEqual("艾琳", TOWN_NAV_ENTRIES["Q_sp18"])
        self.assertEqual("艾琳", RESTART_NAV_ENTRIES["Q_sp18"])
        self.assertIn(("Q_sp18", "main_area", "battle_area_1"), WALK_LABEL_EDGES)
        # 圣域 -> 第一记忆空间 and back are teleports.
        self.assertNotIn(("Q_sp18", "battle_area_1", "battle_area_2"), WALK_LABEL_EDGES)
        self.assertNotIn(("Q_sp18", "battle_area_2", "battle_area_1"), WALK_LABEL_EDGES)


class Chapter18MovesTest(unittest.TestCase):
    def _navigator(self, calls):
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator._status = lambda *_args: None
        navigator._walk_to_collection_map = lambda card, here, there: (
            calls.append(("walk", here.key, there.key))
            or NavigationResult(True, ScreenState.SANDBOX, there.title)
        )
        navigator._travel_via_nav_menu = lambda *entries: (
            calls.append(("menu", *entries)) or entries[0]
        )
        navigator._open_teleport_map_anywhere = lambda *_args: (
            calls.append(("teleport-map",))
            or NavigationResult(False, ScreenState.SANDBOX, "停")
        )
        return navigator

    def test_safe_area_walks_into_the_sanctum(self):
        calls = []
        main, sanctum, _memory = CARD.targets

        result = self._navigator(calls).advance_collection_map(CARD.card_id, main, sanctum)

        self.assertTrue(result.success)
        self.assertEqual([("walk", "main_area", "battle_area_1")], calls)

    def test_battle_maps_teleport_both_ways(self):
        _main, sanctum, memory = CARD.targets
        for here, there in ((sanctum, memory), (memory, sanctum)):
            with self.subTest(here=here.title):
                calls = []
                self._navigator(calls).advance_collection_map(CARD.card_id, here, there)
                self.assertEqual([("teleport-map",)], calls)

    def test_sanctum_goes_back_by_airin(self):
        calls = []
        main, sanctum, _memory = CARD.targets
        navigator = self._navigator(calls)
        navigator.current_collection_target = lambda _card: main.key

        result = navigator.advance_collection_map(CARD.card_id, sanctum, main)

        self.assertTrue(result.success)
        self.assertEqual([("menu", "艾琳")], calls)

    def test_restart_goes_to_airin_first(self):
        calls = []
        navigator = self._navigator(calls)
        navigator.ensure_small_minimap = lambda: True
        navigator.current_collection_target = lambda _card: CARD.targets[0].key

        result = navigator.prepare_collection_main_area(CARD.card_id, via_hunting_ground=True)

        self.assertTrue(result.success)
        self.assertEqual([("menu", "艾琳")], calls)

    def test_covered_sanctum_label_uses_its_known_place(self):
        # The 4K clone clicked (525, 296) on the 1080p area map (10-10).
        main, sanctum, _memory = CARD.targets
        navigator, clicks = navigator_tests.WalkToCollectionMapTest._navigator(
            None, ["安全科库托斯暗黑神殿", "战斗Ⅰ科库托斯圣域"], [""]
        )
        navigator._exit_label_points = lambda _frame, _target: []

        with patch("src.tasks.map_trade.navigator_sandbox.WALK_LABEL_READ_TIMEOUT", 0.0):
            result = navigator._walk_to_collection_map(CARD, main, sanctum)

        self.assertTrue(result.success)
        self.assertEqual([(525, 296)], clicks)


class Chapter18RouteTest(unittest.TestCase):
    def _run(self, here):
        return collector_tests.CollectionRouteTest._run(None, here, card_id="Q_sp18")

    def test_from_the_safe_area_forward(self):
        self.assertEqual(
            [
                ("collect", "main_area"),
                ("go", "main_area", "battle_area_1"),
                ("collect", "battle_area_1"),
                ("go", "battle_area_1", "battle_area_2"),
                ("collect", "battle_area_2"),
            ],
            self._run("main_area"),
        )

    def test_from_the_second_battle_map_back_to_airin(self):
        self.assertEqual(
            [
                ("collect", "battle_area_2"),
                ("go", "battle_area_2", "battle_area_1"),
                ("collect", "battle_area_1"),
                ("go", "battle_area_1", "main_area"),
                ("collect", "main_area"),
            ],
            self._run("battle_area_2"),
        )

    def test_anywhere_else_airin_first(self):
        for here in ("battle_area_1", None):
            with self.subTest(here=here):
                events = self._run(here)
                self.assertEqual(("hunting",), events[0])
                self.assertEqual(
                    ["main_area", "battle_area_1", "battle_area_2"],
                    [event[1] for event in events if event[0] == "collect"],
                )


if __name__ == "__main__":
    unittest.main()
