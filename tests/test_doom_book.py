import unittest
from pathlib import Path

import cv2
import numpy as np

from src.tasks.DoomBookTask import SKIP_ICON_ROI, skip_ready
from src.utils.stage_walk import MARKER_TARGET, find_marker, plan_step


def load(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


def field_with_marker(centre):
    frame = np.full((1080, 1920, 3), (70, 80, 90), dtype=np.uint8)
    x, y = centre
    cv2.line(frame, (x - 14, y - 13), (x + 14, y + 13), (20, 20, 220), 6)
    cv2.line(frame, (x + 14, y - 13), (x - 14, y + 13), (20, 20, 220), 6)
    return frame


class MarkerTest(unittest.TestCase):
    def test_crossed_swords_found(self):
        found = find_marker(field_with_marker((1477, 346)))
        self.assertIsNotNone(found)
        self.assertLess(abs(found[0] - 1477) + abs(found[1] - 346), 4)

    def test_small_red_props_and_the_minimap_are_ignored(self):
        frame = field_with_marker((1477, 346))
        frame[:] = (70, 80, 90)
        cv2.rectangle(frame, (700, 290), (707, 308), (20, 20, 220), -1)  # table prop
        cv2.line(frame, (240, 115), (260, 135), (20, 20, 220), 6)  # minimap marker
        self.assertIsNone(find_marker(frame))

    def test_walk_heads_for_the_marker(self):
        # Spawn: marker up-right of the character, so walk right first.
        self.assertEqual("d", plan_step((1477, 346), MARKER_TARGET).key)
        self.assertIsNone(plan_step(MARKER_TARGET, MARKER_TARGET))

    def test_prediction_follows_the_view(self):
        from src.utils.stage_walk import WalkStep, predict_after_step

        # Live: one D 0.35 s step slid the marker from (1875, 133) under the logo.
        x, y = predict_after_step((1875, 133), WalkStep("d", 0.35))
        self.assertLess(x, 1875)
        self.assertEqual(133, y)
        self.assertGreater(predict_after_step((900, 300), WalkStep("w", 0.3))[1], 300)
        self.assertLess(predict_after_step((900, 300), WalkStep("s", 0.3))[1], 300)
        self.assertGreater(predict_after_step((900, 300), WalkStep("a", 0.3))[0], 900)

    def test_live_field_frames_if_available(self):
        cases = {
            ".local-dev/shots/f1.png": (1477, 346),  # spawn
            ".local-dev/shots/f2.png": (1195, 321),  # after D 0.5 s
            ".local-dev/demo/012_134318.png": (1016, 323),
            ".local-dev/shots/w2.png": (1875, 133),  # kept position, marker at the edge
        }
        if not all(Path(p).exists() for p in cases):
            self.skipTest("live field frames not present")
        for path, expected in cases.items():
            found = find_marker(load(path))
            self.assertIsNotNone(found, path)
            self.assertLess(abs(found[0] - expected[0]) + abs(found[1] - expected[1]), 4, path)


class NeighbourSlotTest(unittest.TestCase):
    def test_left_neighbour_first(self):
        from src.tasks.DoomBookTask import neighbour_slot

        self.assertEqual(510, neighbour_slot(690))  # 末日之书 -> 冒险航线
        self.assertEqual(330, neighbour_slot(150))
        # Slot 1 (x 150) is the PVP hub: never picked as the neighbour.
        self.assertEqual(510, neighbour_slot(330))


class SkipButtonTest(unittest.TestCase):
    def test_grey_then_white(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        x, y, w, h = SKIP_ICON_ROI
        frame[y + 10 : y + 35, x + 5 : x + 40] = 128
        self.assertFalse(skip_ready(frame))
        frame[y + 10 : y + 35, x + 5 : x + 40] = 255
        self.assertTrue(skip_ready(frame))

    def test_live_battle_frames_if_available(self):
        grey, white = Path(".local-dev/demo/017_134325.png"), Path(".local-dev/demo/018_134326.png")
        if not (grey.exists() and white.exists()):
            self.skipTest("live battle frames not present")
        self.assertFalse(skip_ready(load(grey)))
        self.assertTrue(skip_ready(load(white)))


class HoldKeyForegroundTest(unittest.TestCase):
    def fake_task(self, foreground):
        from types import SimpleNamespace

        info = {}
        return SimpleNamespace(
            operate=lambda fun, **_kwargs: fun(),
            _bring_game_to_foreground=lambda: foreground,
            info_set=info.__setitem__,
            log_warning=lambda *_args, **_kwargs: None,
            sleep=lambda _seconds: None,
            info=info,
        )

    def test_no_key_when_the_game_is_behind_another_window(self):
        from unittest import mock

        from src.tasks.BaseBD2Task import BaseBD2Task

        task = self.fake_task(foreground=False)
        with mock.patch("win32api.keybd_event") as keybd:
            self.assertFalse(BaseBD2Task.hold_key(task, "d", 0.01))
        keybd.assert_not_called()
        self.assertIn("未发送", task.info["按键移动"])

    def test_key_pressed_and_released_when_in_front(self):
        from unittest import mock

        from src.tasks.BaseBD2Task import BaseBD2Task

        task = self.fake_task(foreground=True)
        with mock.patch("win32api.keybd_event") as keybd:
            self.assertTrue(BaseBD2Task.hold_key(task, "d", 0.01))
        self.assertEqual(2, keybd.call_count)


if __name__ == "__main__":
    unittest.main()


class DoomBookFailureTest(unittest.TestCase):
    """Review 2026-09-26: failures leave the game somewhere recovery can handle."""

    def _task(self):
        from unittest import mock

        from src.tasks.DoomBookTask import DoomBookTask

        task = object.__new__(DoomBookTask)
        task.name = "末日之书"
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task._open_page_from_home = lambda *a: True
        task._enter_cartridge = lambda: True
        task.dismiss_field_followers = mock.Mock(return_value="absent")
        task._field_to_home = mock.Mock(return_value=True)
        task._reset_to_spawn = mock.Mock(return_value=True)
        task._save_flow_diagnostic = lambda *a: None
        task._move_mode = lambda: "键盘WASD走到舞台"
        return task

    def test_refused_keys_skip_the_cartridge_reset(self):
        task = self._task()

        def walk():
            task._keys_refused = True
            return False

        task._walk_to_marker = walk
        self.assertFalse(task.run_claim())
        task._reset_to_spawn.assert_not_called()
        task._field_to_home.assert_called_once()

    def test_a_failed_battle_leaves_the_result_screen(self):
        from unittest import mock

        task = self._task()
        task._walk_to_marker = lambda: True
        task._fight = lambda: False
        task._leave_result_after_failure = mock.Mock()
        self.assertFalse(task.run_claim())
        task._leave_result_after_failure.assert_called_once()


class CardSearchTest(unittest.TestCase):
    """Live 2026-09-27: with 查看战场奖励 on, the cards show no names."""

    def test_card_found_by_its_cover(self):
        from pathlib import Path

        from src.tasks.DoomBookTask import DoomBookTask

        path = Path(__file__).resolve().parent / "fixtures" / "doom_collection_rewards_on.jpg"
        frame = cv2.resize(cv2.imread(str(path)), (1920, 1080))
        task = object.__new__(DoomBookTask)
        task.info_set = lambda *a: None
        task.sleep = lambda *a: None
        task.capture_frame = lambda: frame
        x, y = task._find_card()
        self.assertLess(abs(x - 1110) + abs(y - 480), 20)

    def test_no_card_on_an_unrelated_page(self):
        from src.tasks.DoomBookTask import DoomBookTask

        task = object.__new__(DoomBookTask)
        task.info_set = lambda *a: None
        task.sleep = lambda *a: None
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), np.uint8)
        self.assertIsNone(task._find_card())


class CurrentCartridgeCoverTest(unittest.TestCase):
    def test_cover_still_found_under_the_play_icon(self):
        from pathlib import Path

        from src.tasks.DoomBookTask import CARD_TEMPLATE, card_cover_match

        path = Path(__file__).resolve().parent / "fixtures" / "doom_collection_rewards_on.jpg"
        grey = cv2.cvtColor(cv2.resize(cv2.imread(str(path)), (1920, 1080)), cv2.COLOR_BGR2GRAY)
        # Copy the ▶ icon of the card in use (Mirror Wars) over LAST NIGHT's middle.
        grey[425:475, 1085:1135] = grey[425:475, 245:295]
        template = cv2.imread(str(CARD_TEMPLATE), cv2.IMREAD_GRAYSCALE)
        score, (x, y) = card_cover_match(grey, template)
        self.assertGreater(score, 0.8)
        self.assertLess(abs(x - 1110) + abs(y - 480), 20)


class GoBattleTimingTest(unittest.TestCase):
    """去战斗 is re-clicked only when the page stayed ~9 s; cleanup covers a battle."""

    def _task(self):
        from src.tasks.DoomBookTask import DoomBookTask

        task = object.__new__(DoomBookTask)
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task.sleep = lambda *a: None
        task.capture_frame = lambda: None
        task._reference_boxes = lambda *a: ["button"]
        task._box_with = lambda boxes, _texts: boxes[0] if boxes else None
        return task

    def test_go_battle_waits_for_the_page_to_leave_before_reclicking(self):
        from src.tasks import DoomBookTask as module

        task = self._task()
        task.capture_frame = lambda: np.zeros((108, 192, 3), np.uint8)
        clicks = []
        task._click_reference_box = lambda box, after_sleep=0: clicks.append(box)
        # The page and its button are gone after the click: the battle is loading.
        task._doom_page_visible = lambda _frame: not clicks
        task._reference_boxes = lambda *a: [] if clicks else ["button"]
        options = {}
        press_and_confirm = task.press_and_confirm

        def spy(label, press, confirmed, **kwargs):
            options.update(kwargs)
            return press_and_confirm(label, press, confirmed, **kwargs)

        task.press_and_confirm = spy
        # Stop right after the go-battle step.
        module_end = module.BATTLE_TIMEOUT_SECONDS
        try:
            module.BATTLE_TIMEOUT_SECONDS = -1.0
            self.assertFalse(task._fight())
        finally:
            module.BATTLE_TIMEOUT_SECONDS = module_end
        self.assertEqual(["button"], clicks)
        self.assertEqual(module.GO_BATTLE_LEAVE_SECONDS, options["timeout"])
        self.assertGreaterEqual(module.GO_BATTLE_LEAVE_SECONDS, 8.0)

    def test_cleanup_waits_a_full_battle_but_not_on_the_doom_page(self):
        from src.tasks import DoomBookTask as module

        self.assertGreaterEqual(module.RESULT_CLEANUP_SECONDS, module.BATTLE_TIMEOUT_SECONDS)
        task = self._task()
        task._reference_boxes = lambda *a: []
        task._field_visible = lambda _frame: False
        task._new_record_visible = lambda _frame: False
        reads = []
        task._doom_page_visible = lambda _frame: reads.append(1) or True
        task._back_to_field_from_page = lambda: False
        task._field_to_home = lambda: self.fail("not on the field")
        task._leave_result_after_failure()
        self.assertEqual(2, len(reads))

    def test_cleanup_leaves_the_doom_page_for_home(self):
        from unittest import mock

        task = self._task()
        task._reference_boxes = lambda *a: []
        task._field_visible = lambda _frame: False
        task._new_record_visible = lambda _frame: False
        task._doom_page_visible = lambda _frame: True
        task._back_to_field_from_page = mock.Mock(return_value=True)
        task._field_to_home = mock.Mock(return_value=True)
        task._leave_result_after_failure()
        task._back_to_field_from_page.assert_called_once()
        task._field_to_home.assert_called_once()


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _real_ocr_vision():
    """ocr_boxes like the tool's: crop the relative ROI, read at 1080 scale."""
    from types import SimpleNamespace

    from onnxocr.onnx_paddleocr import ONNXPaddleOcr

    # The tool runs onnxocr on OpenVINO (src/config.py); players' PCs may
    # not have onnxruntime at all (2K PC 2026-10-08), so try that first.
    try:
        engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True)
    except ImportError:
        engine = ONNXPaddleOcr(use_angle_cls=False)

    def ocr_boxes(frame, name, relative_roi, target_height, ocr_scale):
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = relative_roi
        crop = frame[int(y1 * h) : int(y2 * h), int(x1 * w) : int(x2 * w)]
        crop = cv2.resize(crop, None, fx=ocr_scale, fy=ocr_scale)
        found = engine.ocr(crop)[0] or []
        return [SimpleNamespace(name=text) for _box, (text, _score) in found]

    return SimpleNamespace(ocr_boxes=ocr_boxes)


class NewRecordScreenTest(unittest.TestCase):
    """Leo 2026-10-08: a 创造新纪录 screen can follow the 末日之书 battle."""

    def _task(self, frames):
        from unittest import mock

        from src.tasks.DoomBookTask import DoomBookTask

        task = object.__new__(DoomBookTask)
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.sleep = lambda *a: None
        frames = list(frames)
        task.capture_frame = lambda: frames.pop(0) if len(frames) > 1 else frames[0]
        task._click_reference = mock.Mock()
        return task

    def test_screen_shown_is_clicked_away(self):
        task = self._task(["record", "record", "gone"])
        task._new_record_visible = lambda frame: frame == "record"
        self.assertTrue(task._dismiss_new_record("record"))
        task._click_reference.assert_called_once()

    def test_single_frame_is_not_pressed(self):
        task = self._task(["gone"])
        task._new_record_visible = lambda frame: frame == "record"
        self.assertFalse(task._dismiss_new_record("record"))
        task._click_reference.assert_not_called()

    def test_without_the_emblem_needs_both_texts(self):
        task = self._task(["x"])
        blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for text, expected in (
            ("创造新纪录 最高伤害 18,124,279,421", True),
            ("創造新紀錄 最高傷害", True),
            ("最高伤害 18,124,279,421", False),
            ("创造新纪录", False),
        ):
            task._text_in = lambda frame, roi, name, text=text: text
            self.assertEqual(expected, task._new_record_visible(blank), text)

    def test_emblem_alone_is_enough_in_any_language(self):
        task = self._task(["x"])
        task._text_in = lambda *a: "new record"
        record = load(FIXTURES / "doom" / "new_record_2k.jpg")
        self.assertTrue(task._new_record_visible(record))

    def test_emblem_all_resolutions_and_picture_settings(self):
        from src.tasks.DoomBookTask import NEW_RECORD_ICON_MIN_SCORE, new_record_icon_score

        def score(shot):
            return new_record_icon_score(cv2.resize(shot, (1920, 1080), interpolation=cv2.INTER_AREA))

        record = load(FIXTURES / "doom" / "new_record_2k.jpg")
        for size in ((1920, 1080), (2560, 1440), (3840, 2160)):
            native = cv2.resize(record, size, interpolation=cv2.INTER_AREA)
            w, h = size
            shifted = cv2.warpAffine(native, np.float32([[1, 0, 8 * w / 1920], [0, 1, -6 * h / 1080]]), size)
            for name, shot in (
                ("plain", native),
                ("brighter", cv2.convertScaleAbs(native, alpha=1.0, beta=40)),
                ("darker", cv2.convertScaleAbs(native, alpha=0.8, beta=-20)),
                ("contrast", cv2.convertScaleAbs(native, alpha=1.3, beta=-40)),
                ("blur", cv2.GaussianBlur(native, (7, 7), 0)),
                ("shifted", shifted),
            ):
                self.assertGreaterEqual(score(shot), NEW_RECORD_ICON_MIN_SCORE, (size, name))
        checked = 0
        for path in sorted(FIXTURES.rglob("*")):
            if path.suffix not in (".png", ".jpg") or path.name == "new_record_2k.jpg":
                continue
            shot = load(path)
            if shot is None or shot.ndim != 3 or abs(shot.shape[1] / shot.shape[0] - 16 / 9) > 0.02:
                continue
            checked += 1
            self.assertLess(score(shot), NEW_RECORD_ICON_MIN_SCORE, path.name)
        self.assertGreater(checked, 5)

    def test_field_wait_dismisses_the_record_on_the_way(self):
        task = self._task(["x"])
        task._field_visible = lambda frame: frame == "field"
        task._dismiss_new_record = __import__("unittest").mock.Mock(return_value=True)
        self.assertFalse(task._field_after_result("record"))
        task._dismiss_new_record.assert_called_once_with("record")
        self.assertTrue(task._field_after_result("field"))

    def test_real_screens_all_resolutions(self):
        try:
            vision = _real_ocr_vision()
        except ImportError as missing:
            self.skipTest(f"OCR engine unavailable: {missing}")
        from unittest import mock

        task = self._task(["x"])
        task._quick_vision = lambda: vision
        # Text path on its own: the emblem is tested separately.
        mock.patch("src.tasks.DoomBookTask.new_record_icon_score", return_value=0.0).start()
        self.addCleanup(mock.patch.stopall)
        record = load(FIXTURES / "doom" / "new_record_2k.jpg")
        for size in ((1920, 1080), (2560, 1440), (3840, 2160)):
            self.assertTrue(task._new_record_visible(cv2.resize(record, size)), size)
        others = [FIXTURES / "doom_collection_rewards_on.jpg", *sorted((FIXTURES / "field").glob("*.png"))]
        for path in others:
            frame = load(path)
            if frame is None or abs(frame.shape[1] / frame.shape[0] - 16 / 9) > 0.02:
                continue
            self.assertFalse(task._new_record_visible(frame), path.name)


class NewRecordFlowTest(unittest.TestCase):
    """The battle ends on the field whether or not 创造新纪录 shows up."""

    def _run(self, screens, cleanup=False):
        from types import SimpleNamespace
        from unittest import mock

        from src.tasks.DoomBookTask import DoomBookTask

        def frame(tag):
            shot = np.zeros((108, 192, 3), dtype=np.uint8)
            shot[0, 0, 0] = tag
            return shot

        tags = {"page": 1, "battle": 2, "record": 3, "result": 4, "field": 5}
        names = {v: k for k, v in tags.items()}
        state = {"i": 0}
        task = object.__new__(DoomBookTask)
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.sleep = lambda *a: None
        clicks = []

        def capture():
            return frame(tags[screens[min(state["i"], len(screens) - 1)]])

        def click(*a, **k):
            clicks.append(screens[min(state["i"], len(screens) - 1)])
            state["i"] += 1

        name = lambda shot: names[int(shot[0, 0, 0])]
        task.capture_frame = capture
        task._click_reference = click
        task._click_reference_box = click
        task._doom_page_visible = lambda shot: name(shot) == "page"
        task._field_visible = lambda shot: name(shot) == "field"
        task._new_record_visible = lambda shot: name(shot) == "record"
        task._text_in = lambda *a: ""

        def boxes(shot, roi, label):
            wanted = {"page": "去战斗", "result": "离开"}.get(name(shot))
            return [SimpleNamespace(name=wanted, x=0, y=0, width=10, height=10)] if wanted else []

        task._reference_boxes = boxes
        if cleanup:
            homes = []
            task._field_to_home = lambda: homes.append(1) or True
            task._leave_result_after_failure()
            self.assertEqual([1], homes)
        else:
            self.assertTrue(task._fight())
        return clicks

    def test_without_record(self):
        self.assertEqual(["page", "result"], self._run(["page", "result", "field"]))

    def test_record_before_the_result(self):
        self.assertEqual(
            ["page", "record", "result"], self._run(["page", "record", "result", "field"])
        )

    def test_record_then_back_on_the_doom_page(self):
        # 4K 桌面分身 2026-10-09: after 创造新纪录 the game showed the
        # 末日之书 page again; its back arrow leads to the field.
        self.assertEqual(
            ["page", "record", "page"], self._run(["page", "record", "page", "field"])
        )

    def test_leaving_onto_the_doom_page(self):
        self.assertEqual(
            ["page", "result", "record", "page"],
            self._run(["page", "result", "record", "page", "field"]),
        )

    def test_failure_cleanup_leaving_onto_the_doom_page(self):
        # Leo's 4K log 10-09: 离开 led to the 末日之书 page, not the field.
        self.assertEqual(["result", "page"], self._run(["result", "page", "field"], cleanup=True))

    def test_record_after_leaving(self):
        self.assertEqual(
            ["page", "result", "record"], self._run(["page", "result", "record", "field"])
        )


class DoomPageAfterRecordTest(unittest.TestCase):
    """Leo's 10-09 screens (1080 clone, 4K desktop) after 创造新纪录."""

    def test_read_as_the_doom_page_not_the_record_or_field(self):
        try:
            vision = _real_ocr_vision()
        except ImportError as missing:
            self.skipTest(f"OCR engine unavailable: {missing}")
        from src.tasks.DoomBookTask import DoomBookTask

        task = object.__new__(DoomBookTask)
        task.info_set = lambda *a: None
        task._quick_vision = lambda: vision
        for name in ("doom_page_after_record_1080.jpg", "doom_page_after_record_4k.jpg"):
            frame = load(FIXTURES / "doom" / name)
            self.assertTrue(task._doom_page_visible(frame), name)
            self.assertFalse(task._new_record_visible(frame), name)
            self.assertFalse(task._field_visible(frame), name)


class ClickToMoveTest(unittest.TestCase):
    """Leo 2026-10-09: 末日之书 follows 镜中之战's 「舞台移动方式」; with click-to-move
    it clicks the red crossed-swords marker (player gghot2001: 「不往门里走」)."""

    def _task(self, frames, page_after_clicks=1):
        from types import SimpleNamespace
        from unittest import mock

        from src.tasks.DoomBookTask import DoomBookTask

        task = object.__new__(DoomBookTask)
        task.info_set = lambda *a: None
        task.log_info = mock.Mock()
        task.sleep = lambda *a: None
        task.clicks = []
        task.operate_click = lambda x, y, after_sleep=0.0: task.clicks.append((x, y))
        frames = iter(frames)
        task.capture_frame = lambda: next(frames, None)
        task._field_visible = lambda frame: frame is not None
        task._doom_page_visible = lambda frame: len(task.clicks) >= page_after_clicks
        task._wait_for = lambda check, timeout, interval=0.6: check(task.capture_frame())
        task._keys_refused = False
        task._executor = SimpleNamespace(get_task_by_class=lambda cls: None)
        return task

    def test_marker_is_found_at_every_resolution(self):
        # The marker drawn at 2K and 4K size lands on the same 1080 point.
        for scale in (1.0, 4 / 3, 2.0):
            with self.subTest(scale=scale):
                width, height = round(1920 * scale), round(1080 * scale)
                frame = np.full((height, width, 3), (70, 80, 90), dtype=np.uint8)
                x, y, r = round(1561 * scale), round(313 * scale), round(14 * scale)
                thick = max(1, round(6 * scale))
                cv2.line(frame, (x - r, y - r), (x + r, y + r), (20, 20, 220), thick)
                cv2.line(frame, (x + r, y - r), (x - r, y + r), (20, 20, 220), thick)
                found = find_marker(cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA))
                self.assertIsNotNone(found)
                self.assertLess(abs(found[0] - 1561) + abs(found[1] - 313), 4)

    def test_click_lands_on_the_marker(self):
        task = self._task([field_with_marker((1561, 313))] * 3)
        self.assertTrue(task._click_to_marker())
        (x, y), = task.clicks
        # Relative to the window, so any resolution and the clone get the same spot.
        self.assertAlmostEqual(1561 / 1920, x, delta=0.003)
        self.assertAlmostEqual(313 / 1080, y, delta=0.003)

    def test_no_click_without_a_marker(self):
        empty = np.full((1080, 1920, 3), (70, 80, 90), dtype=np.uint8)
        task = self._task([empty] * 8)
        self.assertFalse(task._click_to_marker())
        self.assertEqual([], task.clicks)

    def test_gives_up_after_a_few_clicks_that_go_nowhere(self):
        from src.tasks.DoomBookTask import CLICK_MAX_TRIES

        task = self._task([field_with_marker((1561, 313))] * 20, page_after_clicks=99)
        self.assertFalse(task._click_to_marker())
        self.assertEqual(CLICK_MAX_TRIES, len(task.clicks))

    def test_the_other_way_is_tried_when_the_setting_does_not_work(self):
        from unittest import mock

        task = self._task([field_with_marker((1561, 313))] * 5)
        task._move_mode = lambda: "鼠标点击舞台"
        task._click_to_marker = mock.Mock(return_value=False)
        task._walk_to_marker = mock.Mock(return_value=True)
        self.assertTrue(task._reach_marker())
        task._click_to_marker.assert_called_once()
        task._walk_to_marker.assert_called_once()

        task._move_mode = lambda: "键盘WASD走到舞台"
        task._click_to_marker = mock.Mock(return_value=True)
        task._walk_to_marker = mock.Mock(return_value=False)
        self.assertTrue(task._reach_marker())
        task._walk_to_marker.assert_called_once()

    def test_setting_is_read_from_mirror_wars(self):
        from types import SimpleNamespace

        task = self._task([])
        pvp = SimpleNamespace(config={"舞台移动方式": "键盘WASD走到舞台"})
        task._executor = SimpleNamespace(get_task_by_class=lambda cls: pvp)
        self.assertEqual("键盘WASD走到舞台", task._move_mode())
        task._executor = SimpleNamespace(get_task_by_class=lambda cls: None)
        self.assertEqual("鼠标点击舞台", task._move_mode())
