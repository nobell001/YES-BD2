"""Player report 2026-10-23 (v0.2.9, 1080p): 每周跑图 第9章 could not go home.

The character stood in the chapter's hunting ground 「战斗 守山人休息处」.
1. Its area map was never confirmed: the title is none of the cards' own
   maps, so its teleport circle was not searched and the map stayed open.
2. With the map open, the ≡ button's fixed place landed on the map's title
   row and opened the difficulty panel 「极难 更改 自动狩猎 离开」, read as a
   ≡ menu without 狩猎场; every later step clicked on the map.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

from src.tasks.map_trade.models import CARD_BY_ID, MapPageMode, NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_sandbox import NOT_BY_CIRCLE_MESSAGE
from src.tasks.map_trade.vision import Vision

try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships onnxocr
    ONNXPaddleOcr = None

FIXTURES = Path(__file__).resolve().parent / "fixtures/map_trade/map_pages"


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class HuntingGroundMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
                        name=text,
                        x=min(xs),
                        y=min(ys),
                        width=max(xs) - min(xs),
                        height=max(ys) - min(ys),
                        confidence=score,
                    )
                )
            return boxes

        cls.ocr = staticmethod(ocr)

    def _navigator(self):
        frame = cv2.imread(str(FIXTURES / "hunting_ground_map_player_fhd.jpg"))
        self.assertIsNotNone(frame)
        task = SimpleNamespace(config={}, ocr=self.ocr, info_set=lambda *_a: None)
        vision = Vision(task)
        vision.capture = lambda: frame
        return Navigator(task, vision), frame

    def test_hunting_ground_area_map_is_confirmed(self):
        navigator, frame = self._navigator()

        self.assertEqual(
            MapPageMode.SANDBOX_LARGE_MAP, navigator._detect_map_page_mode(frame).mode
        )

    def test_its_teleport_circle_is_found(self):
        navigator, frame = self._navigator()

        teleport = navigator._sandbox_navigation_teleport(frame)

        # The circle icon sits at ~(346, 532) on the 1080p map.
        self.assertIsNotNone(teleport)
        x, y = teleport.center
        self.assertLess(abs(x - 346), 20)
        self.assertLess(abs(y - 532), 20)

    def test_the_open_map_is_seen_and_closed(self):
        navigator, _frame = self._navigator()
        closed = []
        navigator._close_field_map = lambda: closed.append(True)

        self.assertTrue(navigator._area_map_open())
        navigator._close_field_map_if_open()

        self.assertEqual([True], closed)


class AreaMapTeleportGlyphTest(unittest.TestCase):
    """The circle is told from the inn and NPC icons by the glyph inside
    their shared round frame, not by how far its frame score leads."""

    def _navigator(self, path):
        frame = cv2.imread(str(path))
        self.assertIsNotNone(frame)
        if frame.shape[1] != 1920:
            frame = cv2.resize(frame, (1920, 1080))
        statuses = []
        task = SimpleNamespace(config={}, info_set=lambda *_a: None)
        navigator = Navigator(task, Vision(task))
        navigator._status = lambda *args: statuses.append(args)
        return navigator, frame, statuses

    def test_the_circle_glyph_is_far_from_the_portrait_beside_it(self):
        # 华特波尔雪山: the circle at ~(380, 445), a portrait icon at ~(690, 431).
        navigator, frame, _ = self._navigator(FIXTURES / "snow_large_map_player_fhd.jpg")

        teleport = navigator._sandbox_navigation_teleport(frame)

        self.assertIsNotNone(teleport)
        x, y = teleport.center
        self.assertLess(abs(x - 380), 20)
        self.assertLess(abs(y - 445), 20)
        self.assertGreaterEqual(navigator._teleport_glyph_score(frame, teleport), 0.85)

    def test_a_map_of_round_icons_without_a_circle_gives_none(self):
        # The square's area map: shop and NPC icons up to 0.867, no circle.
        navigator, frame, _ = self._navigator(
            FIXTURES.parent.parent / "square/square_area_map_2k.jpg"
        )

        self.assertIsNone(navigator._sandbox_navigation_teleport(frame))


class NavMenuWithMapOpenTest(unittest.TestCase):
    def test_fixed_place_is_not_pressed_on_an_open_area_map(self):
        clicks = []
        vision = SimpleNamespace(
            click_template=lambda *_a, **_k: False,
            click_reference=lambda *a, **_k: clicks.append(a),
        )
        task = SimpleNamespace(info_set=lambda *_a: None)
        navigator = Navigator(task, vision)
        closed = []
        navigator._area_map_open = lambda: True  # the map will not close
        navigator._close_field_map = lambda: closed.append(True)

        self.assertFalse(navigator._open_minimap_nav_menu())
        self.assertEqual([True], closed)
        self.assertEqual([], clicks)


class AlreadyInHuntingGroundTest(unittest.TestCase):
    """Leo's 第9章 picture: in 守山人休息处 there is no ≡ by the minimap; the
    ground's bar 「守山人休息处 | 极难 更改 / 自动狩猎 / 离开」 is always there."""

    BAR = ["守山人休息处丨极难", "更改", "自动狩猎", "离开"]

    def _navigator(self, texts):
        def boxes(_frame, _name, _roi, **_kwargs):
            return [
                SimpleNamespace(name=text, x=330, y=100 + 50 * row, width=120, height=30)
                for row, text in enumerate(texts)
            ]

        vision = SimpleNamespace(capture=lambda: None, ocr_boxes=boxes, simplify=lambda t: t)
        task = SimpleNamespace(info_set=lambda *_a: None, log_info=lambda *_a: None)
        navigator = Navigator(task, vision)
        navigator._open_minimap_nav_menu = lambda: self.fail("no ≡ in a hunting ground")
        return navigator

    def test_the_bar_means_already_there_and_nothing_is_pressed(self):
        navigator = self._navigator(self.BAR)

        self.assertEqual("狩猎场", navigator._travel_via_nav_menu("狩猎场", "艾琳"))
        self.assertTrue(navigator._already_in_hunting_ground)

    def test_a_town_menu_is_not_the_bar(self):
        self.assertFalse(Navigator._hunting_ground_panel(["旅馆", "商店", "探索告示板"]))
        self.assertTrue(Navigator._hunting_ground_panel(["更改", "离开"]))

    def test_already_there_walks_to_the_circle_before_f(self):
        navigator = self._navigator(self.BAR)
        navigator._already_in_hunting_ground = True
        navigator.open_teleport_map_from_sandbox = lambda: NavigationResult(
            False, ScreenState.SANDBOX, NOT_BY_CIRCLE_MESSAGE
        )
        walked = NavigationResult(True, ScreenState.AREA_MAP)
        navigator._walk_to_sandbox_teleport_interaction = lambda: walked
        navigator.task.tap_key = lambda *_a, **_k: self.fail("walk worked, no F")

        self.assertIs(walked, navigator._open_teleport_map_at_hunting_ground())

    def test_no_way_to_the_circle_says_to_stand_on_it(self):
        # Leo 2026-10-23 (第10章): skip the card and tell the player.
        navigator = self._navigator(self.BAR)
        navigator._already_in_hunting_ground = True
        navigator.open_teleport_map_from_sandbox = lambda: NavigationResult(
            False, ScreenState.SANDBOX, NOT_BY_CIRCLE_MESSAGE
        )
        navigator._walk_to_sandbox_teleport_interaction = lambda: NavigationResult(
            False, ScreenState.SANDBOX_MAP, "未确认目的地按钮"
        )
        navigator.task.tap_key = lambda *_a, **_k: True
        navigator._wait_for_sandbox_map_open = lambda *_a, **_k: NavigationResult(
            False, ScreenState.SANDBOX, "没打开"
        )

        result = navigator._open_teleport_map_at_hunting_ground()

        self.assertFalse(result.success)
        self.assertIn("请先让角色站到狩猎场的传送阵上再跑", result.message)
        # 第10章 says it is that chapter only (Leo 2026-10-23).
        result = navigator._open_teleport_map_at_hunting_ground(CARD_BY_ID["Q_sp10"])
        self.assertTrue(result.message.startswith("第10章"))
        self.assertIn("只有第10章", result.message)
        result = navigator._open_teleport_map_at_hunting_ground(CARD_BY_ID["Q_sp9"])
        self.assertNotIn("第10章", result.message)

    def test_after_a_real_trip_f_comes_without_a_walk(self):
        navigator = self._navigator(self.BAR)
        navigator._already_in_hunting_ground = False
        navigator.open_teleport_map_from_sandbox = lambda: NavigationResult(
            False, ScreenState.SANDBOX, NOT_BY_CIRCLE_MESSAGE
        )
        navigator._walk_to_sandbox_teleport_interaction = lambda: self.fail("trip lands on the circle")
        keys = []
        navigator.task.tap_key = lambda key, after_sleep=0: keys.append(key) or True
        navigator._wait_for_sandbox_map_open = lambda *_a, **_k: NavigationResult(
            True, ScreenState.AREA_MAP
        )

        self.assertTrue(navigator._open_teleport_map_at_hunting_ground().success)
        self.assertEqual(["F"], keys)


if __name__ == "__main__":
    unittest.main()
