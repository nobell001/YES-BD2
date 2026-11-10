"""Player v0.3.8 1080p 2026-11-10, 每周跑图 第14章 skipped: standing a few
steps from the town's teleport circle, 「区域地图上找不到传送阵图标」.

The character's own marker draws over the circle on the area map.  Leo's
frame of that map (阿爾卡迪亞居住區域, 2026-11-10) finds the circle; the same
frame with the marker laid on the circle does not.  A short step with the
movement keys moves the marker off, then the map is read again."""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision

FIXTURES = Path(__file__).resolve().parent / "fixtures/map_trade/map_pages"
CIRCLE = (405, 504)  # the circle's centre on the 1080p frame
MARKER_CENTRE, MARKER_RADIUS = (27, 37), 14


def _frame(marker_offset=None):
    frame = cv2.imread(str(FIXTURES / "ch14_town_map_leo_tw_fhd.jpg"))
    if marker_offset is not None:
        marker = cv2.imread(str(FIXTURES / "ch14_town_map_own_marker.png"))
        r = MARKER_RADIUS
        yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
        disc = xx * xx + yy * yy <= r * r
        cx, cy = CIRCLE[0] + marker_offset[0], CIRCLE[1] + marker_offset[1]
        mx, my = MARKER_CENTRE
        frame[cy - r : cy + r + 1, cx - r : cx + r + 1][disc] = marker[
            my - r : my + r + 1, mx - r : mx + r + 1
        ][disc]
    return frame


def _navigator(frame):
    task = SimpleNamespace(config={}, ocr=lambda **_k: [], info_set=lambda *_a: None)
    vision = Vision(task)
    vision.capture = lambda: frame
    navigator = Navigator(task, vision)
    navigator._status = lambda *_args: None
    return navigator


class CircleUnderOwnMarkerTest(unittest.TestCase):
    def test_circle_is_found_on_the_plain_map(self):
        frame = _frame()
        teleport = _navigator(frame)._sandbox_navigation_teleport(frame)
        self.assertIsNotNone(teleport)
        self.assertLess(abs(teleport.center[0] - CIRCLE[0]), 6)
        self.assertLess(abs(teleport.center[1] - CIRCLE[1]), 6)

    def test_real_marker_touching_the_circle_is_still_found(self):
        # Leo's frame 2026-11-10 (亞拉里克城市): the marker overlaps the
        # circle's edge; glyph 0.75 against 0.90 uncovered, still over 0.70.
        frame = cv2.imread(str(FIXTURES / "town_map_marker_beside_circle_leo_tw_fhd.jpg"))
        teleport = _navigator(frame)._sandbox_navigation_teleport(frame)
        self.assertIsNotNone(teleport)
        self.assertLess(abs(teleport.center[0] - 491), 6)
        self.assertLess(abs(teleport.center[1] - 343), 6)

    def test_own_marker_on_the_circle_hides_it(self):
        for offset in ((0, 0), (10, -8), (-10, 8), (14, 0), (0, 14)):
            with self.subTest(offset=offset):
                frame = _frame(offset)
                self.assertIsNone(_navigator(frame)._sandbox_navigation_teleport(frame))

    def test_marker_a_step_away_shows_it_again(self):
        frame = _frame((20, -15))
        self.assertIsNotNone(_navigator(frame)._sandbox_navigation_teleport(frame))


if __name__ == "__main__":
    unittest.main()
