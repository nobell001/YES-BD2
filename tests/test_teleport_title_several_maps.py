"""第7章 back to the town: the teleport map's title read named two maps.

Player v0.2.25, 2560x1440 fullscreen at 150% (2026-10-31): 地图采集 第7章
回主城失败 「传送阵地图左右翻页都未找到拉勒凯镇：last=… 拉勒凯镇」 while page 1
(安全 拉勒凯镇) was on screen for 9 s.  A read naming 拉勒凯镇 alone always
resolves (the fixture below reads 「安全 拉勒凯镇」 with the app's recognizer),
so the failing read also named 洞穴神殿 or 隐藏神殿: a tie of equal-length
names, so no page at all, and the seek could never stop on the town.
"""

import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.map_trade.models import CARD_BY_ID, MapPageMode, NavigationResult
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_constants import AreaMapContext
from src.tasks.map_trade.vision import normalize_text

CARD = CARD_BY_ID["Q_sp7"]
FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures/map_trade/map_pages/ch7_town_teleport_page_player_summary.jpg"
)
# The title bar's middle at 1920 wide: (654 + 1268) / 2.
MIDDLE = 961


def _box(text, centre_x, width=120):
    return SimpleNamespace(name=text, x=centre_x - width / 2, y=960, width=width, height=40)


def _navigator(boxes):
    vision = SimpleNamespace(
        ocr_text=lambda *_a, **_k: " ".join(box.name for box in boxes),
        ocr_boxes=lambda *_a, **_k: list(boxes),
        simplify=lambda text: text,
        match=lambda *_a, **_k: SimpleNamespace(score=0.0),
    )
    navigator = Navigator(
        SimpleNamespace(info_set=lambda *_a: None, log_info=lambda *_a: None, config={}), vision
    )
    navigator._detect_map_page_mode = lambda _frame: SimpleNamespace(
        mode=MapPageMode.DIRECT_TELEPORT, header_text="移动魔法阵"
    )
    navigator._optional_match = lambda *_a, **_k: None
    navigator._teleport_map_teleports = lambda _frame: ()
    navigator._status = lambda *_a: None
    return navigator


class TitleNamingSeveralMapsTest(unittest.TestCase):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    def test_the_centred_label_decides(self):
        navigator = _navigator(
            [_box("战斗Ｉ洞穴神殿", 520), _box("安全", MIDDLE - 70, 60), _box("拉勒凯镇", MIDDLE + 40)]
        )

        context = navigator._area_map_context(self.frame, CARD)

        self.assertEqual("main_area", context.resolved_target_key)

    def test_a_glued_box_takes_the_name_read_last(self):
        navigator = _navigator([_box("洞穴神殿安全", MIDDLE - 90), _box("拉勒凯镇", MIDDLE + 60)])

        context = navigator._area_map_context(self.frame, CARD)

        self.assertEqual("main_area", context.resolved_target_key)

        one_box = _navigator([_box("战斗Ｉ洞穴神殿安全拉勒凯镇", MIDDLE)])
        self.assertEqual(
            "main_area", one_box._area_map_context(self.frame, CARD).resolved_target_key
        )

    def test_a_single_name_is_untouched(self):
        boxes = [_box("战斗Ⅱ", MIDDLE - 80, 60), _box("隐藏神殿", MIDDLE + 40)]
        navigator = _navigator(boxes)
        navigator.vision.ocr_boxes = lambda *_a, **_k: self.fail("no second read")

        self.assertEqual(
            "battle_area_2", navigator._area_map_context(self.frame, CARD).resolved_target_key
        )

    def test_without_box_reads_the_tie_stays_unresolved(self):
        navigator = _navigator([_box("洞穴神殿", 520), _box("拉勒凯镇", MIDDLE)])
        del navigator.vision.ocr_boxes

        context = navigator._area_map_context(self.frame, CARD)

        self.assertIsNone(context.resolved_target_key)

    def test_the_seek_now_stops_on_the_town(self):
        """Before the fix the tie left page 1 unresolved: every left press
        there changed nothing and the card was skipped."""
        pages = [
            [_box("洞穴神殿", 520), _box("安全", MIDDLE - 70, 60), _box("拉勒凯镇", MIDDLE + 40)],
            [_box("战斗Ｉ洞穴神殿", MIDDLE)],
            [_box("战斗Ⅱ", MIDDLE - 80, 60), _box("隐藏神殿", MIDDLE + 40)],
        ]
        state = {"page": 2}
        current = lambda: pages[state["page"]]  # noqa: E731
        vision = SimpleNamespace(
            ocr_text=lambda *_a, **_k: " ".join(box.name for box in current()),
            ocr_boxes=lambda *_a, **_k: list(current()),
            simplify=lambda text: text,
        )
        navigator = _navigator([])
        navigator.vision = vision
        arrow = SimpleNamespace(center=(380, 519))

        def capture(card):
            context = navigator._area_map_context(self.frame, card)
            page = state["page"]
            return AreaMapContext(
                **{
                    **context.__dict__,
                    "left_arrow": arrow if page > 0 else None,
                    "right_arrow": SimpleNamespace(center=(1540, 519)) if page < 2 else None,
                }
            )

        def click(center, _shape, after_sleep=0):
            if center[0] < MIDDLE:
                state["page"] = max(0, state["page"] - 1)
            else:
                state["page"] = min(2, state["page"] + 1)

        vision.click_client = click
        navigator._capture_area_map_context = capture
        navigator.task.sleep = lambda _s: None

        found = navigator._seek_collection_page(CARD, capture(CARD), CARD.targets[0])

        self.assertNotIsInstance(found, NavigationResult)
        self.assertEqual("main_area", found.resolved_target_key)
        self.assertEqual(0, state["page"])


def _page(raw, *, left=True, right=True, others=()):
    text = normalize_text(raw)
    keys = Navigator._target_keys_in_text(CARD, text)
    return AreaMapContext(
        frame_shape=(1080, 1920, 3),
        raw_text=raw,
        normalized_text=text,
        map_page_mode=MapPageMode.DIRECT_TELEPORT,
        candidate_target_keys=keys,
        resolved_target_key=keys[0] if len(keys) == 1 else None,
        left_arrow=SimpleNamespace(center=(380, 519)) if left else None,
        right_arrow=SimpleNamespace(center=(1540, 519)) if right else None,
        teleports=(),
        overlap_arrow=None,
        back_button=None,
    )


class CloseNameTest(unittest.TestCase):
    """Leo 2026-10-31 「字接近就判定成功」: a page read a little wrong still
    counts as the map it is close to, never as a look-alike map."""

    def _is(self, raw, target=0, card=CARD):
        navigator = _navigator([])
        return navigator._page_is(card, _page(raw) if card is CARD else _page_for(card, raw),
                                  card.targets[target])

    def test_a_close_read_is_the_town(self):
        for raw in ("安全 拉勤凯镇", "安全 勒凯镇", "安全拉勒凯填"):
            with self.subTest(raw=raw):
                page = self._is(raw)
                self.assertIsNotNone(page)
                self.assertEqual("main_area", page.resolved_target_key)
                self.assertTrue(page.guessed)

    def test_look_alikes_are_not_the_town(self):
        # The town's inn shares 拉勒凯; other pages and other maps' names.
        for raw in ("安全 拉勒凯旅馆", "战斗蜥蜴人祭坛", "战斗Ⅱ 隐藏神殿", ""):
            with self.subTest(raw=raw):
                self.assertIsNone(self._is(raw))

    def test_a_misread_floor_number_is_no_floor(self):
        card = CARD_BY_ID["Q_sp6"]
        for target in range(3):
            with self.subTest(target=target):
                self.assertIsNone(self._is("安全 施塔因之塔第7层", target, card))

    def test_the_seek_takes_page_one_read_a_little_wrong(self):
        reads = ["安全 拉勤凯镇", "战斗Ｉ洞穴神殿", "战斗Ⅱ 隐藏神殿"]
        state = {"page": 2}
        navigator = _navigator([])

        def capture(_card):
            page = state["page"]
            return _page(reads[page], left=page > 0, right=page < 2)

        def click(center, _shape, after_sleep=0):
            step = -1 if center[0] < MIDDLE else 1
            state["page"] = min(2, max(0, state["page"] + step))

        navigator.vision.click_client = click
        navigator._capture_area_map_context = capture
        navigator.task.sleep = lambda _s: None

        found = navigator._seek_collection_page(CARD, capture(CARD), CARD.targets[0])

        self.assertNotIsInstance(found, NavigationResult)
        self.assertEqual(0, state["page"])
        self.assertEqual("main_area", found.resolved_target_key)
        self.assertTrue(found.guessed)


def _page_for(card, raw):
    text = normalize_text(raw)
    keys = Navigator._target_keys_in_text(card, text)
    return replace(_page(""), raw_text=raw, normalized_text=text,
                   candidate_target_keys=keys,
                   resolved_target_key=keys[0] if len(keys) == 1 else None)


class RereadTest(unittest.TestCase):
    """A page read that may be a misread map name is read again enlarged."""

    def _navigator(self, first, enlarged):
        calls = []

        def ocr_text(_frame, name, **kwargs):
            calls.append(kwargs.get("ocr_scale", 1.0))
            return enlarged if kwargs.get("ocr_scale", 1.0) > 1 else first

        navigator = _navigator([])
        navigator.vision.ocr_text = ocr_text
        return navigator, calls

    def test_a_misread_is_read_again_enlarged(self):
        navigator, calls = self._navigator("安全 拉勒", "安全 拉勒凯镇")

        context = navigator._area_map_context(TitleNamingSeveralMapsTest.frame, CARD)

        self.assertEqual("main_area", context.resolved_target_key)
        self.assertFalse(context.guessed)
        self.assertEqual([1.0, 2.0], calls)

    def test_a_clean_unrelated_page_is_not_read_again(self):
        navigator, calls = self._navigator("战斗 蜥蜴人祭坛", "安全 拉勒凯镇")

        context = navigator._area_map_context(TitleNamingSeveralMapsTest.frame, CARD)

        self.assertIsNone(context.resolved_target_key)
        self.assertEqual([1.0], calls)


class FailedSeekTest(unittest.TestCase):
    def _seek(self, reads):
        state = {"page": 0}
        navigator = _navigator([])

        def capture(_card):
            page = state["page"]
            return _page(reads[page], left=page > 0, right=page < len(reads) - 1)

        def click(center, _shape, after_sleep=0):
            step = -1 if center[0] < MIDDLE else 1
            state["page"] = min(len(reads) - 1, max(0, state["page"] + step))

        navigator.vision.click_client = click
        navigator._capture_area_map_context = capture
        navigator.task.sleep = lambda _s: None
        return navigator, capture

    def test_the_message_lists_every_page_read(self):
        navigator, capture = self._seek(["安全 某某", "战斗Ｉ洞穴神殿", "战斗Ⅱ 隐藏神殿"])

        failed = navigator._seek_collection_page(CARD, capture(CARD), CARD.targets[0])

        self.assertIsInstance(failed, NavigationResult)
        for text in ("「安全 某某」", "「战斗Ｉ洞穴神殿」", "「战斗Ⅱ 隐藏神殿」"):
            self.assertIn(text, failed.message)
        self.assertNotIn("=", failed.message)

    def test_town_by_aileen_after_a_failed_seek(self):
        navigator = _navigator([])
        closed, travelled = [], []
        navigator._close_area_map = lambda context: closed.append(True)
        navigator._travel_via_nav_menu = lambda *entries: travelled.append(entries) or entries[0]
        navigator.current_collection_target = lambda card: "main_area"
        failed = NavigationResult(False, None, "传送阵地图左右翻页都未找到拉勒凯镇（…）")

        result = navigator._town_by_npc_after_failed_seek(CARD, _page("安全 某某"), failed)

        self.assertTrue(result.success)
        self.assertEqual([True], closed)
        self.assertEqual([("艾琳",)], travelled)

    def test_aileen_missing_keeps_both_reasons(self):
        navigator = _navigator([])
        navigator._close_area_map = lambda context: None
        navigator._travel_via_nav_menu = lambda *entries: None
        navigator._nav_failure = "≡选单里没有艾琳"
        failed = NavigationResult(False, None, "传送阵地图左右翻页都未找到拉勒凯镇（…）")

        result = navigator._town_by_npc_after_failed_seek(CARD, _page("安全 某某"), failed)

        self.assertFalse(result.success)
        self.assertIn("左右翻页都未找到拉勒凯镇", result.message)
        self.assertIn("≡选单里没有艾琳", result.message)


class PlayerFrameReadsTheTownTest(unittest.TestCase):
    """The player's page-1 frame (from the 问题摘要, downscaled) read with the
    app's recognizer names 拉勒凯镇 and nothing else."""

    def test_title_names_the_town(self):
        try:
            import src  # noqa: F401  (v6 recognizer, as the app)
            from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        except ImportError:  # pragma: no cover
            self.skipTest("onnxocr not installed")
        from src.tasks.map_trade.navigator_constants import TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI
        from src.tasks.map_trade.vision import Vision

        engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True, use_npu=False)

        def ocr(*, frame, threshold=0.2, **_kwargs):
            found = []
            for points, (text, score) in engine.ocr(frame)[0] or []:
                if score >= threshold:
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    found.append(
                        SimpleNamespace(
                            name=text, x=min(xs), y=min(ys),
                            width=max(xs) - min(xs), height=max(ys) - min(ys),
                        )
                    )
            return found

        frame = cv2.imread(str(FIXTURE))
        self.assertIsNotNone(frame)
        frame = cv2.resize(frame, (2560, 1440), interpolation=cv2.INTER_CUBIC)
        vision = Vision(SimpleNamespace(config={}, ocr=ocr, info_set=lambda *_a: None))
        text = vision.ocr_text(frame, "传送阵地图名", relative_roi=TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI)

        self.assertEqual(("main_area",), Navigator._target_keys_in_text(CARD, normalize_text(text)))


if __name__ == "__main__":
    unittest.main()
