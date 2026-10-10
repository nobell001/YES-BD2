"""Chapter 18: 科库托斯暗黑神殿 has no teleport circle (live 4K 2026-10-10).

The quick switch and 艾琳 both put the character there and its ≡ menu has no
狩猎场, so without a portal skill the only way to a circle is its
科库托斯圣域 exit.
"""

import unittest
from types import SimpleNamespace

from src.tasks.map_trade.models import (
    CARD_BY_ID,
    CIRCLE_EXIT_WALKS,
    MapPageMode,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator import Navigator

OK_MAP = NavigationResult(
    True, ScreenState.AREA_MAP, "传送阵地图", map_page_mode=MapPageMode.DIRECT_TELEPORT
)
NO = NavigationResult(False, ScreenState.SANDBOX, "没有")


def navigator(calls, *, walk_result, in_sanctum_circle=True):
    nav = Navigator(SimpleNamespace(info_set=lambda *_args: None), SimpleNamespace())
    state = {"moved": False}

    def open_from_sandbox():
        calls.append("open")
        return OK_MAP if state["moved"] and in_sanctum_circle else NO

    def walk_to_collection_map(card, here, there):
        calls.append(("walk", card.card_id, here.title, there.title, there.key))
        if walk_result.success:
            state["moved"] = True
        return walk_result

    nav.open_teleport_map_from_sandbox = open_from_sandbox
    nav._walk_to_sandbox_teleport_interaction = lambda: calls.append("circle-walk") or NO
    nav._walk_to_collection_map = walk_to_collection_map
    nav._travel_to_hunting_ground = lambda: calls.append("nav-menu") or "艾琳"
    nav._click_sandbox_teleport_interaction = lambda: False
    return nav


class CircleExitWalkTest(unittest.TestCase):
    def test_chapter_18_walks_out_of_the_dark_temple(self):
        self.assertEqual(("科库托斯暗黑神殿", "科库托斯圣域"), CIRCLE_EXIT_WALKS["Q_sp18"])
        card = CARD_BY_ID["Q_sp18"]
        self.assertIn("科库托斯圣域", [target.title for target in card.targets])
        for card_id, (here, there) in CIRCLE_EXIT_WALKS.items():
            with self.subTest(card=card_id):
                titles = [target.title for target in CARD_BY_ID[card_id].targets]
                self.assertIn(there, titles)

    def test_exit_walk_comes_before_the_nav_menu(self):
        calls = []
        nav = navigator(calls, walk_result=NavigationResult(True, ScreenState.SANDBOX, "已走到"))

        result = nav._open_teleport_map_anywhere(CARD_BY_ID["Q_sp18"])

        self.assertTrue(result.success)
        self.assertEqual(
            [
                "open",
                "circle-walk",
                ("walk", "Q_sp18", "科库托斯暗黑神殿", "科库托斯圣域", "battle_area_1"),
                "open",
            ],
            calls,
        )

    def test_elsewhere_goes_to_ailin_then_walks_out(self):
        # In 圣域 with the circle hidden under the character: the first exit
        # walk does not apply, 艾琳 brings the character to 暗黑神殿, and the
        # exit walk runs there.
        calls = []
        nav = navigator(calls, walk_result=NO)
        attempts = []

        def walk_to_collection_map(card, here, there):
            attempts.append(here.title)
            if len(attempts) == 1:
                return NavigationResult(
                    False, ScreenState.SANDBOX, "区域地图不是科库托斯暗黑神殿：x"
                )
            return NavigationResult(True, ScreenState.SANDBOX, "已走到科库托斯圣域")

        nav._walk_to_collection_map = walk_to_collection_map
        nav.open_teleport_map_from_sandbox = (
            lambda: calls.append("open") or (OK_MAP if len(attempts) == 2 else NO)
        )

        result = nav._open_teleport_map_anywhere(CARD_BY_ID["Q_sp18"])

        self.assertTrue(result.success)
        self.assertEqual(2, len(attempts))
        self.assertEqual(["open", "circle-walk", "nav-menu", "circle-walk", "open"], calls)

    def test_a_failed_walk_from_the_dark_temple_is_reported(self):
        calls = []
        failed = NavigationResult(
            False, ScreenState.SANDBOX, "区域地图上点科库托斯圣域出口没有反应"
        )
        nav = navigator(calls, walk_result=failed)

        result = nav._open_teleport_map_anywhere(CARD_BY_ID["Q_sp18"])

        self.assertFalse(result.success)
        self.assertIn("科库托斯圣域出口没有反应", result.message)
        self.assertNotIn("nav-menu", calls)

    def test_other_cards_keep_the_old_chain(self):
        calls = []
        nav = navigator(calls, walk_result=NO)
        nav._walk_to_collection_map = lambda *_args: self.fail("no exit walk for this card")

        result = nav._open_teleport_map_anywhere(CARD_BY_ID["Q_sp14"])

        self.assertFalse(result.success)
        self.assertEqual(["open", "circle-walk", "nav-menu", "circle-walk"], calls)
        self.assertIsNone(nav._walk_to_circle_neighbour(None))


if __name__ == "__main__":
    unittest.main()
