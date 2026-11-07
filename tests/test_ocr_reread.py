"""A small box that read nothing is read again, bordered and enlarged.

Leo 2026-10-11 「先做放大再讀」: every read goes through BaseBD2Task.ocr, so
the extra reads reach every small box, not one place at a time.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np
from ok import BaseTask

from src.tasks.BaseBD2Task import BaseBD2Task
from src.utils import ocr_reread

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade"


def _box(x, y, width, height, name="购买"):
    return SimpleNamespace(x=x, y=y, width=width, height=height, name=name, confidence=0.99)


class RereadImagesTest(unittest.TestCase):
    def test_small_boxes_qualify_pages_do_not(self):
        self.assertTrue(ocr_reread.qualifies(np.zeros((56, 133, 3), np.uint8)))
        self.assertTrue(ocr_reread.qualifies(np.zeros((360, 1400, 3), np.uint8)))
        self.assertFalse(ocr_reread.qualifies(np.zeros((1080, 1920, 3), np.uint8)))
        self.assertFalse(ocr_reread.qualifies(np.zeros((361, 200, 3), np.uint8)))
        self.assertFalse(ocr_reread.qualifies(np.zeros((40, 1401, 3), np.uint8)))
        self.assertFalse(ocr_reread.qualifies(None))

    def test_bordered_first_then_2x_then_3x(self):
        crop = np.full((50, 100, 3), 40, np.uint8)
        images = list(ocr_reread.reread_images(crop))
        self.assertEqual([image.scale for image in images], [1.0, 2.0, 3.0])
        for image in images:
            height = int(50 * image.scale)
            self.assertEqual(image.border, max(ocr_reread.REREAD_MIN_BORDER, height // 2))
            self.assertEqual(image.image.shape[0], height + 2 * image.border)
            # The border takes the box's own colour: no new edge to read.
            self.assertTrue((image.image[0, 0] == 40).all())

    def test_a_big_box_is_not_enlarged_past_the_cap(self):
        crop = np.zeros((300, 1000, 3), np.uint8)
        self.assertEqual([image.scale for image in ocr_reread.reread_images(crop)], [1.0, 2.0])

    def test_boxes_are_moved_back_onto_the_original_box(self):
        reread = ocr_reread.RereadImage(np.zeros((1, 1)), scale=2.0, border=50)
        (box,) = ocr_reread.map_back([_box(50 + 20, 50 + 10, 60, 40)], reread, 133, 56)
        self.assertEqual((box.x, box.y, box.width, box.height), (10, 5, 30, 20))

    def test_moved_boxes_stay_inside_the_box(self):
        reread = ocr_reread.RereadImage(np.zeros((1, 1)), scale=1.0, border=20)
        (box,) = ocr_reread.map_back([_box(5, 5, 200, 100)], reread, 133, 56)
        self.assertEqual((box.x, box.y), (0, 0))
        self.assertLessEqual(box.x + box.width, 133)
        self.assertLessEqual(box.y + box.height, 56)


class TrustedTest(unittest.TestCase):
    def test_stray_marks_are_left_out(self):
        boxes = [
            _box(0, 0, 1, 1, "-"),
            _box(0, 0, 1, 1, "X"),
            _box(0, 0, 1, 1, "3"),
            _box(0, 0, 1, 1, "购买"),
            _box(0, 0, 1, 1, "9"),
            _box(0, 0, 1, 1, "LIV"),
        ]
        boxes[0].confidence = 0.99  # a dash on a coloured bar
        boxes[1].confidence = 0.87
        boxes[2].confidence = 0.8  # a lone digit needs 0.9
        boxes[3].confidence = 0.97
        boxes[4].confidence = 0.97
        boxes[5].confidence = 0.65
        self.assertEqual([box.name for box in ocr_reread.trusted(boxes)], ["购买", "9"])

    def test_confidence_in_percent_is_understood(self):
        box = _box(0, 0, 1, 1, "40倍")
        box.confidence = 95
        self.assertEqual(ocr_reread.trusted([box]), [box])


class OcrOverrideTest(unittest.TestCase):
    def setUp(self):
        self.task = object.__new__(BaseBD2Task)
        self.calls = []

    def _ocr(self, results):
        """ok's OCR stand-in: answers in order, records the image heights."""

        def fake(_task, **kwargs):
            self.calls.append(kwargs)
            return results.pop(0) if results else []

        return mock.patch.object(BaseTask, "ocr", fake, create=True)

    def test_a_box_that_reads_is_read_once(self):
        with self._ocr([[_box(1, 2, 3, 4)]]):
            boxes = self.task.ocr(frame=np.zeros((56, 133, 3), np.uint8), name="t")
        self.assertEqual(len(boxes), 1)
        self.assertEqual(len(self.calls), 1)

    def test_an_empty_small_box_is_read_bordered_then_enlarged(self):
        crop = np.zeros((56, 133, 3), np.uint8)
        border_2x = 56  # 112 // 2
        found = [_box(border_2x + 20, border_2x + 10, 60, 40)]
        with self._ocr([[], [], found]):
            boxes = self.task.ocr(frame=crop, name="标题", target_height=720)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.calls[1]["frame"].shape[0], 56 + 2 * 28)
        self.assertEqual(self.calls[2]["frame"].shape[0], 112 + 2 * border_2x)
        # Enlarged reads are never shrunk back by ok's target height.
        self.assertEqual(self.calls[2]["target_height"], 0)
        self.assertEqual((boxes[0].x, boxes[0].y, boxes[0].width, boxes[0].height), (10, 5, 30, 20))

    def test_a_read_of_only_stray_marks_is_read_again(self):
        crop = np.zeros((56, 133, 3), np.uint8)
        stray = _box(1, 2, 3, 4, "4")
        stray.confidence = 0.77
        found = [_box(28 + 20, 28 + 10, 60, 40)]
        with self._ocr([[stray], found]):
            boxes = self.task.ocr(frame=crop, name="标题")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([box.name for box in boxes], ["购买"])

    def _read(self, text, confidence):
        box = _box(100, 40, 60, 30, text)
        box.confidence = confidence
        return [box]

    def test_a_reread_that_lost_the_digit_does_not_replace_it(self):
        # 活动每日战斗 button, Leo's 1080p 繁中 frame 2026-11-07.
        crop = np.zeros((70, 330, 3), np.uint8)
        reads = [
            self._read("战斗。5", 0.792),
            self._read("战斗：5", 0.793),
            self._read("战斗。", 0.86),
            self._read("战斗。5", 0.802),
        ]
        with self._ocr(reads):
            boxes = self.task.ocr(frame=crop, name="自动战斗开始")
        self.assertEqual([box.name for box in boxes], ["战斗。5"])
        self.assertEqual(len(self.calls), 4)

    def test_a_reread_that_lost_words_does_not_replace_them(self):
        crop = np.zeros((70, 330, 3), np.uint8)
        reads = [
            self._read("今日剩余次数", 0.75),
            self._read("今日", 0.95),
            self._read("今日剩余次数", 0.9),
        ]
        with self._ocr(reads):
            boxes = self.task.ocr(frame=crop, name="标题")
        self.assertEqual([box.name for box in boxes], ["今日剩余次数"])

    def test_a_sure_read_without_the_digit_is_the_last_resort(self):
        crop = np.zeros((70, 330, 3), np.uint8)
        reads = [self._read("战斗。5", 0.792), [], self._read("战斗。", 0.86), []]
        with self._ocr(reads):
            boxes = self.task.ocr(frame=crop, name="自动战斗开始")
        self.assertEqual([box.name for box in boxes], ["战斗。"])

    def test_stray_marks_are_kept_when_the_rereads_find_nothing(self):
        stray = _box(1, 2, 3, 4, "-")
        with self._ocr([[stray]]):
            boxes = self.task.ocr(frame=np.zeros((56, 133, 3), np.uint8), name="t")
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(boxes, [stray])

    def test_nothing_anywhere_returns_empty_after_three_more_reads(self):
        with self._ocr([]):
            self.assertEqual(self.task.ocr(frame=np.zeros((56, 133, 3), np.uint8), name="t"), [])
        self.assertEqual(len(self.calls), 4)

    def test_a_box_that_stays_empty_is_not_enlarged_again_within_a_second(self):
        crop = np.zeros((56, 133, 3), np.uint8)
        with self._ocr([]):
            self.task.ocr(frame=crop, name="等待中")
            self.task.ocr(frame=crop, name="等待中")
            self.task.ocr(frame=crop, name="别的框")
        self.assertEqual(len(self.calls), 4 + 1 + 4)

    def test_full_frames_and_opt_outs_are_read_once(self):
        with self._ocr([]):
            self.task.ocr(frame=np.zeros((1080, 1920, 3), np.uint8), name="全屏")
            self.task.ocr(frame=np.zeros((56, 133, 3), np.uint8), name="已放大", reread=False)
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("reread", self.calls[1])


class LookAgainTest(unittest.TestCase):
    """Slow PCs: nothing seen is looked at again for 5 s; something seen returns at once."""

    def setUp(self):
        self.task = object.__new__(BaseBD2Task)
        self.slept = []
        self.task.sleep = self.slept.append
        self.task.log_info = lambda *_args, **_kwargs: None

    def test_a_cue_seen_at_once_never_waits(self):
        self.assertEqual(self.task.look_again(lambda: "购买"), "购买")
        self.assertEqual(self.slept, [])

    def test_a_cue_drawn_late_is_found(self):
        looks = iter([None, None, None, "战斗"])
        self.assertEqual(self.task.look_again(lambda: next(looks)), "战斗")
        self.assertEqual(len(self.slept), 3)

    def test_nothing_after_the_grace_returns_the_last_look(self):
        self.assertIsNone(self.task.look_again(lambda: None))
        self.assertAlmostEqual(sum(self.slept), 5.0)

    def test_a_popup_over_the_page_is_closed_and_the_page_looked_at_again(self):
        closed = []
        self.task.close_known_popup = lambda label="": closed.append(label) or len(closed) == 1
        looks = iter([None] * 21 + ["战斗"])
        self.assertEqual(self.task.look_again(lambda: next(looks), "战斗按钮"), "战斗")
        self.assertEqual(closed, ["战斗按钮"])

    def test_no_popup_means_one_popup_look_only(self):
        closed = []
        self.task.close_known_popup = lambda label="": closed.append(label) and False
        self.assertIsNone(self.task.look_again(lambda: None, "战斗按钮"))
        self.assertEqual(len(closed), 1)


try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships onnxocr
    ONNXPaddleOcr = None


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class PlayerTitleTest(unittest.TestCase):
    """The player's 跑商 title box (v0.1.21, 2026-10-11, 1080p window at 250%).

    On a fixed-size OCR input (how an NPU reads) the box as cut reads nothing
    or only a stray mark, also enlarged 2× and 3×; with a border it reads 购买.
    """

    def test_the_bordered_read_finds_购买(self):
        from src.tasks.map_trade.trader_constants import SHOP_MODE_TITLE_REGION
        from src.utils.image_utils import relative_roi_frame

        image = cv2.imread(str(FIXTURES / "shop_title_buy_player_1080.png"))
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[4 : 4 + image.shape[0], 186 : 186 + image.shape[1]] = image
        _left, _top, crop = relative_roi_frame(frame, SHOP_MODE_TITLE_REGION)
        engine = ONNXPaddleOcr(
            use_angle_cls=False, use_openvino=True, use_npu=False, force_static_shape=True
        )

        def text(img):
            return " ".join(t for _box, (t, score) in (engine.ocr(img)[0] or []) if score >= 0.2)

        def trusted_text(img):
            boxes = [
                SimpleNamespace(name=t, confidence=score)
                for _box, (t, score) in (engine.ocr(img)[0] or [])
            ]
            return " ".join(box.name for box in ocr_reread.trusted(boxes))

        # As cut: nothing (v5) or a stray mark such as 「4」 at 0.77 (v6 on
        # some runtimes); either way BaseBD2Task.ocr reads it again.
        self.assertNotIn("购买", text(crop))
        self.assertEqual(trusted_text(crop), "")
        first = next(ocr_reread.reread_images(crop))
        self.assertEqual(first.scale, 1.0)
        self.assertIn("购买", text(first.image))


if __name__ == "__main__":
    unittest.main()
