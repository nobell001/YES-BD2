"""2K 桌面分身 2026-11-18, 繁中 client, 跑商地点 = 第一章: beside the chapter 1
merchant his prompt reads 「無聊的收藏狂大叔」, but the name check only knew
收集狂大叔.  Cooking then failed 「关闭商店后未回到商人旁」 and the next
entry, spawned right beside him, gave up on 第一章 and went to the square.
Frames: diag/place1118-2k full-run/shots E_rec_124747 / 124717 (960x540,
scaled back to 1920x1080).
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - CI without OCR
    ONNXPaddleOcr = None

from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade"
FRAMES = (
    # Spawned beside him on entering 剧情游戏卡1 (「現在無法移動的區域」 toast).
    "merchant_prompt_tw_ch1_2k_clone_as_1080.jpg",
    # Back on the field after closing his shop, before cooking.
    "merchant_prompt_tw_ch1_after_shop_2k_clone_as_1080.jpg",
)


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class TraditionalChapter1MerchantPromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True, use_npu=False)

    def _navigator(self):
        engine = self.engine

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

        task = SimpleNamespace(
            config={},
            vision_threshold_key="跑图跑商识图阈值",
            info_set=lambda *_a: None,
            log_info=lambda *_a, **_k: None,
            log_warning=lambda *_a, **_k: None,
            sleep=lambda *_a: None,
            ocr=ocr,
        )
        navigator = Navigator(task, Vision(task))
        navigator._status = lambda *_a: None
        return navigator

    def test_his_traditional_name_is_the_merchant_prompt(self):
        navigator = self._navigator()
        for name in FRAMES:
            with self.subTest(frame=name):
                frame = cv2.imread(str(FIXTURES / name))
                self.assertIsNotNone(frame)
                box = navigator._merchant_prompt_box(frame)
                self.assertIsNotNone(box, name)
                self.assertIn("狂", box.name)


if __name__ == "__main__":
    unittest.main()
