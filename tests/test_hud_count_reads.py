"""吸收/召集/压制 counts on 95 real count boxes, read the way the run reads them.

The boxes were cut at the run's fixed count regions from 32 pictures that
players and Leo sent (1280×720 to 3840×2160, 2026-10-28) and labelled by eye
(``fixtures/hud_counts/counts.json``).  The reads before the shared count
rules (src/utils/ocr_count.py: 2x, then 3x, the old split) got 92 right, 1
not at all, and 2 wrong: 0/21 read "121" at 2x and was taken as 1/21.  In
runs 11/75 read "11775" (4K 2026-10-14) and 7/75 "7175" (2K 2026-10-15)
skipped cards.
"""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.collector_constants import BATTLE_ACTIONS
from src.tasks.map_trade.vision import Vision
from src.utils.image_utils import relative_roi_frame

try:
    from ok.feature.Box import Box, sort_boxes
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships both
    ONNXPaddleOcr = None

FIXTURES = Path(__file__).parent / "fixtures" / "hud_counts"
ACTIONS = {action.name: action for action in BATTLE_ACTIONS}


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class HudCountReadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True, use_npu=False)
        cls.boxes = json.loads((FIXTURES / "counts.json").read_text(encoding="utf-8"))

    def _ocr(self, frame, threshold=0.2, **_kwargs):
        """ok-script's onnx read: boxes at the threshold, top to bottom."""
        lines = self.engine.ocr(frame)[0] or []
        boxes = []
        for pos, (text, confidence) in lines:
            width = round(pos[2][0] - pos[0][0])
            height = round(pos[2][1] - pos[0][1])
            if width > 0 and height > 0 and confidence >= threshold:
                boxes.append(Box(pos[0][0], pos[0][1], width, height, confidence, text.strip()))
        return sort_boxes(boxes)

    def _read(self, box, *, limit_seen):
        """The box on a frame of its picture's size, read by the run's reader."""
        action = ACTIONS[box["skill"]]
        width, height = box["frame"]
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        left, top, region = relative_roi_frame(frame, action.fixed_count_relative_roi)
        crop = cv2.imread(str(FIXTURES / box["file"]))
        self.assertEqual(region.shape[:2], crop.shape[:2], box["file"])
        frame[top : top + crop.shape[0], left : left + crop.shape[1]] = crop
        task = SimpleNamespace(
            config={}, ocr=self._ocr, sleep=lambda *_a: None, info_set=lambda *_a: None
        )
        vision = Vision(task)
        vision.capture = lambda: frame
        collector = Collector(task, vision, SimpleNamespace(), SimpleNamespace())
        if limit_seen:
            collector._remember_limit(action.name, int(box["count"].split("/")[1]))
        return collector._read_count(action)

    def test_every_box_reads_right(self):
        """Before today's limit was seen the usual one splits a read without
        its slash; after a steady read, the limit on screen does."""
        for limit_seen in (False, True):
            with self.subTest(limit_seen=limit_seen):
                wrong = []
                for box in self.boxes:
                    count = self._read(box, limit_seen=limit_seen)
                    if count is None or "%d/%d" % count != box["count"]:
                        wrong.append((box["file"], box["count"], count))
                self.assertEqual([], wrong)


if __name__ == "__main__":
    unittest.main()
