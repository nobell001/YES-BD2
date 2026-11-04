"""YES-BD2 #69 (v0.2.29, 1080p window, 2026-11-03): 每周跑图 could not page
any teleport map.  The player's FPS overlay (RivaTuner/Afterburner
「GPU / CPU / D3D11 120 FPS」) sits in the game's top-left corner; its orange
「24%」 covers 移 of the map's 移动魔法阵 title, so the title read
「44 24动魔法阵 PS」.  The page check wanted the whole word, called every
teleport map an unknown page, never paged it and never closed it, and every
later way home (minimap, ≡ menu) was tried with the map still open.

- teleport_map_fps_overlay_player_summary.jpg: the player's frame, cut from
  the 问题摘要 and scaled back to 1920x1080 (too soft for the header icon).
- teleport_map_fps_overlay_on_direct.jpg: the same overlay pixels laid over
  direct.png, so the whole page check runs on a sharp frame.
- hunting_ground_fps_overlay_composite.jpg: the overlay over the 第9章
  hunting ground's area map; it hides the 战斗 tag, so only the battle
  area's 「出现…属性怪物」 is left in the title.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

from src.tasks.map_trade.models import MapPageMode
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_constants import (
    TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI,
    area_map_header_named,
    teleport_map_header_read,
)
from src.tasks.map_trade.vision import Vision, normalize_text

try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships onnxocr
    ONNXPaddleOcr = None

FIXTURES = Path(__file__).resolve().parent / "fixtures/map_trade/map_pages"


class HeaderReadTest(unittest.TestCase):
    def test_one_hidden_character_still_reads(self):
        for read in ("移动魔法阵", "4424动魔法阵PS", "44%4动魔法阵", "移动魔法"):
            with self.subTest(read=read):
                self.assertTrue(teleport_map_header_read(normalize_text(read)))

    def test_other_titles_do_not(self):
        for read in ("生成魔法阵", "魔法阵", "移动", "战斗恶梦之城1", ""):
            with self.subTest(read=read):
                self.assertFalse(teleport_map_header_read(normalize_text(read)))


class AreaMapHeaderTest(unittest.TestCase):
    def test_tag_or_monster_hint(self):
        for read in ("战斗守山人休息处", "安全拉勒凯镇", "44起4守山人休息处出现暗属性怪物"):
            with self.subTest(read=read):
                self.assertTrue(area_map_header_named(normalize_text(read)))
        for read in ("44起4守山人休息处", "移动魔法阵", ""):
            with self.subTest(read=read):
                self.assertFalse(area_map_header_named(normalize_text(read)))


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class FpsOverlayTeleportMapTest(unittest.TestCase):
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

    def _navigator(self, name):
        frame = cv2.imread(str(FIXTURES / name))
        self.assertIsNotNone(frame)
        task = SimpleNamespace(config={}, ocr=self.ocr, info_set=lambda *_a: None)
        vision = Vision(task)
        vision.capture = lambda: frame
        return Navigator(task, vision), vision, frame

    def test_player_frame_title_reads_as_the_teleport_map(self):
        _navigator, vision, frame = self._navigator("teleport_map_fps_overlay_player_summary.jpg")

        read = normalize_text(
            vision.simplify(
                vision.ocr_text(
                    frame, "地图页面左上标题", relative_roi=TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI
                )
            )
        )

        self.assertNotIn("移动魔法阵", read)  # the overlay hides 移
        self.assertTrue(teleport_map_header_read(read), read)

    def test_page_under_the_overlay_is_the_teleport_map(self):
        navigator, _vision, frame = self._navigator("teleport_map_fps_overlay_on_direct.jpg")

        self.assertEqual(
            MapPageMode.DIRECT_TELEPORT, navigator._detect_map_page_mode(frame).mode
        )

    def test_hunting_ground_under_the_overlay_is_the_area_map(self):
        navigator, _vision, frame = self._navigator("hunting_ground_fps_overlay_composite.jpg")

        self.assertEqual(
            MapPageMode.SANDBOX_LARGE_MAP, navigator._detect_map_page_mode(frame).mode
        )


if __name__ == "__main__":
    unittest.main()
