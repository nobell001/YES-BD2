"""Player report 2026-10-29 (v0.2.21, 1080p): 每周跑图 第16章 failed twice
with 「区域地图上找不到传送阵图标」 in 迪尔索特港口城市.

The character stood by 艾琳, away from the circle, so the circle had to be
found on the area map.  The game draws the 迪尔索特旅馆 icon over it (Leo's
2K frame 2026-10-30: frame 0.839, glyph 0.30); pressing that place opens
「魔法阵 / 旅馆」 (Leo: 「點擊後可以選擇」), and when the character is near
the press just walks there (Leo: 「距離近的時候他就是會用走的」).  Only the icon
the map lists in COVERED_CIRCLE_ICONS is pressed, found by its label; a walk
whose banner names another place is stopped at once (Leo: 「你有可能會點到
戰鬥區域」).
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision

try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships onnxocr
    ONNXPaddleOcr = None

FIXTURES = Path(__file__).resolve().parent / "fixtures/map_trade/map_pages"
MAP = FIXTURES / "port_city_inn_covers_circle_leo_2k_as_1080.jpg"
MENU = FIXTURES / "port_city_inn_menu_leo_2k_as_1080.jpg"
INN = (481, 469)


def _frame(path):
    frame = cv2.imread(str(path))
    assert frame is not None, path
    return frame


class CircleHiddenUnderInnTest(unittest.TestCase):
    def test_the_circle_itself_is_not_found_on_this_map(self):
        task = SimpleNamespace(config={}, info_set=lambda *_a: None)
        navigator = Navigator(task, Vision(task))
        navigator._status = lambda *_a: None

        self.assertIsNone(navigator._sandbox_navigation_teleport(_frame(MAP)))


class BattleExitNeverPressedTest(unittest.TestCase):
    """Leo 2026-10-30 「你有可能會點到戰鬥區域」: a battle area's exit icon
    (red crossed swords) is never one of the icons pressed."""

    def _navigator(self):
        task = SimpleNamespace(config={}, info_set=lambda *_a: None)
        return Navigator(task, Vision(task))

    def _icon_at(self, centre, size=40):
        return SimpleNamespace(
            position=(centre[0] - size // 2, centre[1] - size // 2), size=(size, size)
        )

    def test_battle_exits_are_told_from_the_other_icons(self):
        navigator = self._navigator()
        port = _frame(MAP)
        ground = _frame(FIXTURES / "hunting_ground_map_player_fhd.jpg")

        # 迪尔索特黑市 and 加尔顿山后段 (battle exits).
        self.assertTrue(navigator._battle_exit_icon(port, self._icon_at((719, 433))))
        self.assertTrue(navigator._battle_exit_icon(ground, self._icon_at((333, 742))))
        # The inn, the tavern, an NPC, a circle.
        for frame, centre in ((port, INN), (port, (577, 468)), (port, (609, 356)), (ground, (347, 533))):
            self.assertFalse(navigator._battle_exit_icon(frame, self._icon_at(centre)), centre)

    def test_a_cut_label_counts_but_the_shared_prefix_does_not(self):
        navigator = self._navigator()

        self.assertTrue(navigator._reads_as_label("迪尔索特旅馆", "迪尔索特旅馆"))
        self.assertTrue(navigator._reads_as_label("迪尔索特旅", "迪尔索特旅馆"))
        self.assertFalse(navigator._reads_as_label("迪尔索特", "迪尔索特旅馆"))
        self.assertFalse(navigator._reads_as_label("迪尔索特酒馆", "迪尔索特旅馆"))

    def test_only_a_walk_to_the_circle_or_that_icon_is_kept(self):
        navigator = self._navigator()
        navigator._status = lambda *_a: None
        navigator.vision.capture = lambda: None
        navigator._sandbox_navigation_menu_teleport_option = lambda _frame: None
        for text, want in (
            ("自动移动中:魔法阵", "walk"),
            ("自动移动中:迪尔索特旅馆", "walk"),
            ("自动移动中", "walk"),
            ("自动移动中:迪尔索特黑市", "other"),
            ("是否自动移动前往所选目的地?", "other"),
            ("已中止自动移动。", None),
            ("", None),
        ):
            navigator._walk_text = lambda _frame, text=text: text
            self.assertEqual(want, navigator._icon_press_outcome("迪尔索特旅馆"), text)


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class PressIconsForMagicCircleTest(unittest.TestCase):
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
        cls.map = _frame(MAP)
        cls.menu = _frame(MENU)

    def _navigator(self, after_press="menu"):
        """The game: pressing the inn opens the 魔法阵 menu (``after_press``
        "menu"), starts a walk whose banner reads ``after_press``, or does
        nothing (None)."""
        task = SimpleNamespace(
            config={}, ocr=self.ocr, info_set=lambda *_a: None,
            sleep=lambda *_a: None, log_info=lambda *_a: None,
        )
        vision = Vision(task)
        screen = {"frame": self.map, "walk": ""}
        presses = []

        def click(point, _shape, **_kwargs):
            presses.append(point)
            on_inn = abs(point[0] - INN[0]) < 25 and abs(point[1] - INN[1]) < 25
            if on_inn and after_press == "menu":
                screen["frame"] = self.menu
            elif on_inn and after_press:
                screen["walk"] = after_press

        vision.capture = lambda: screen["frame"]
        vision.click_client = click
        navigator = Navigator(task, vision)
        navigator._status = lambda *_a: None
        real_walk_text = navigator._walk_text
        navigator._walk_text = lambda frame: screen["walk"] or real_walk_text(frame)
        undone = []
        navigator._undo_map_icon_press = lambda: undone.append(True)
        return navigator, presses, undone

    def _pressed_the_inn_only(self, presses):
        self.assertEqual(1, len(presses), presses)
        self.assertLess(abs(presses[0][0] - INN[0]), 25)
        self.assertLess(abs(presses[0][1] - INN[1]), 25)

    def test_the_menu_entry_is_read(self):
        navigator, _presses, _undone = self._navigator()

        self.assertIsNotNone(navigator._sandbox_navigation_menu_teleport_option(self.menu))
        self.assertIsNone(navigator._sandbox_navigation_menu_teleport_option(self.map))

    def test_the_inn_is_found_by_its_label(self):
        navigator, _presses, _undone = self._navigator()

        icon = navigator._icon_under_label(self.map, "迪尔索特旅馆")

        self.assertIsNotNone(icon)
        self.assertLess(abs(icon.center[0] - INN[0]), 25)
        self.assertLess(abs(icon.center[1] - INN[1]), 25)

    def test_the_inn_is_pressed_and_its_magic_circle_followed(self):
        navigator, presses, undone = self._navigator()
        followed = []
        navigator._follow_teleport_icon_press = lambda: followed.append(True) or (True, False)

        self.assertEqual((True, False), navigator._circle_under_other_icon(self.map))

        self.assertEqual([True], followed)
        self._pressed_the_inn_only(presses)
        self.assertEqual([], undone)

    def test_near_the_inn_the_walk_there_is_kept(self):
        navigator, presses, undone = self._navigator(after_press="自动移动中:魔法阵")
        navigator._follow_teleport_icon_press = lambda: self.fail("no menu opened")

        self.assertEqual((True, False), navigator._circle_under_other_icon(self.map))
        self._pressed_the_inn_only(presses)
        self.assertEqual([], undone)

    def test_a_walk_elsewhere_is_stopped(self):
        navigator, presses, undone = self._navigator(after_press="自动移动中:迪尔索特黑市")

        self.assertIsNone(navigator._circle_under_other_icon(self.map))
        self._pressed_the_inn_only(presses)
        self.assertEqual([True], undone)

    def test_a_map_not_listed_presses_nothing(self):
        navigator, presses, _undone = self._navigator()
        navigator._area_map_title = lambda _frame: "安全华特波尔镇"

        self.assertIsNone(navigator._circle_under_other_icon(self.map))
        self.assertEqual([], presses)


if __name__ == "__main__":
    unittest.main()
