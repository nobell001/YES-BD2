"""救赎之塔 快速战斗 on the 恶魔城 cartridge (Leo 2026-10-21).

Frames: Leo's 2K screenshots of 10-21 (field at the spawn, at the altar, the
恶魔城 page) and his 4K 游戏卡珍藏集 frames of 10-11, all at 1080.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks.DoomBookTask import card_cover_match, playing_mark_slot
from src.tasks.RedemptionTowerTask import (
    BATTLE_BUTTON_POINT,
    CARD_SIDE_WIDTH,
    CARD_TEMPLATE,
    DRY_RUN_KEY,
    FALLBACK_TEST_KEY,
    MAX_POINT,
    SETTLING_NOTE,
    RedemptionTowerTask,
    find_castle_marker,
    keys_empty,
    level_ticks,
    parse_reward_count,
)

MODULE = "src.tasks.RedemptionTowerTask"
FIXTURES = Path(__file__).parent / "fixtures" / "redemption_tower"


def load(name):
    return cv2.imdecode(np.fromfile(str(FIXTURES / name), np.uint8), cv2.IMREAD_COLOR)


def bar_frame(name):
    """The bottom 200 rows of a 2K clone frame (1080) back in a full frame."""
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[880:] = load(name)
    return frame


class CardTest(unittest.TestCase):
    def match(self, name):
        grey = cv2.cvtColor(load(name), cv2.COLOR_BGR2GRAY)
        template = cv2.imread(str(CARD_TEMPLATE), cv2.IMREAD_GRAYSCALE)
        return card_cover_match(grey, template, CARD_SIDE_WIDTH)

    def test_card_found_while_in_use_with_the_play_mark(self):
        score, (x, y) = self.match("collection_evil_castle_playing_4k.jpg")
        self.assertGreater(score, 0.9)
        self.assertLess(abs(x - 550) + abs(y - 443), 6)

    def test_card_found_on_a_scrolled_page(self):
        score, (x, y) = self.match("collection_scrolled_4k.jpg")
        self.assertGreater(score, 0.9)
        self.assertLess(abs(x - 550) + abs(y - 283), 6)

    def test_no_card_on_a_field(self):
        score, _here = self.match("field_spawn_2k.jpg")
        self.assertLess(score, 0.8)


class MarkerTest(unittest.TestCase):
    def test_marker_on_the_altar(self):
        found = find_castle_marker(load("field_altar_marker_2k.jpg"))
        self.assertIsNotNone(found)
        self.assertLess(abs(found[0] - 970) + abs(found[1] - 169), 6)

    def test_red_map_has_no_marker_at_the_spawn(self):
        # Torches, leaves and the 「!」 bubbles are red too.
        self.assertIsNone(find_castle_marker(load("field_spawn_2k.jpg")))
        self.assertIsNone(find_castle_marker(load("castle_page_2k.jpg")))


class LevelTickTest(unittest.TestCase):
    """Leo 2026-10-21: no ✓ on the left = not played this season: leave."""

    def test_cleared_levels_are_seen(self):
        self.assertGreaterEqual(level_ticks(load("tower_page_ticks_2k.jpg")), 8)

    def test_no_ticks_without_the_list(self):
        frame = load("tower_page_ticks_2k.jpg")
        frame[100:1080, 230:440] = frame[150:151, 300:301]  # list painted over
        self.assertEqual(0, level_ticks(frame))
        self.assertEqual(0, level_ticks(load("castle_page_2k.jpg")))
        self.assertEqual(0, level_ticks(load("field_spawn_2k.jpg")))


class PlayingSlotTest(unittest.TestCase):
    """2K clone 10-21: the Evil Castle card in use shows only a yellow ▶ (its
    SEASON badge hides 「游戏中」), so the spawn reset could not find it."""

    def test_the_card_in_use_by_its_mark(self):
        for name in (
            "quick_bar_evil_castle_playing_2k.png",
            "quick_bar_evil_castle_playing_2k_b.jpg",
        ):
            with self.subTest(name):
                self.assertEqual(330, playing_mark_slot(bar_frame(name)))
        event = Path(__file__).parent / "fixtures" / "quick_switch"
        for name, slot in (
            ("event_bar_card1_playing_fhd.png", 150),
            ("event_bar_card2_playing_fhd.png", 330),
        ):
            with self.subTest(name):
                self.assertEqual(slot, playing_mark_slot(cv2.imread(str(event / name))))

    def test_no_mark_no_slot(self):
        event = Path(__file__).parent / "fixtures" / "quick_switch"
        for name in ("battle_gameplay_selected_fhd.png", "life_gameplay_selected_fhd.png"):
            with self.subTest(name):
                self.assertIsNone(playing_mark_slot(cv2.imread(str(event / name))))
        self.assertIsNone(playing_mark_slot(load("field_spawn_2k.jpg")))
        frame = bar_frame("quick_bar_evil_castle_playing_2k.png")
        frame[940:1000, 300:360] = 40  # the ▶ painted over
        self.assertIsNone(playing_mark_slot(frame))

    def test_unrecognised_slot_falls_back_to_the_second_card(self):
        task = RedemptionTowerTask(SimpleNamespace(scene=None), SimpleNamespace(debug=False))
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), np.uint8)
        task.look_again = lambda look, *a, **k: look()
        task._playing_slot_by_text = lambda: None
        task.log_info = lambda *a, **k: None
        self.assertEqual(330, task._playing_slot_x())


class WalkTest(unittest.TestCase):
    """2K clone 10-21 dry runs: run 1 reached the 恶魔城 page but called it
    「离开了恶魔城地图」; runs 2-3 started on the altar circle."""

    def task(self, screens):
        task = RedemptionTowerTask(SimpleNamespace(scene=None), SimpleNamespace(debug=False))
        screens = iter(screens)
        state = {"now": "field"}

        def capture():
            state["now"] = next(screens, state["now"])
            return state["now"]

        task.capture_frame = capture
        task._field_visible = lambda frame: frame == "field"
        task._castle_page_visible = lambda frame: frame == "page"
        task._reference = lambda frame: np.zeros((1080, 1920, 3), np.uint8)
        task.hold_key = mock.Mock(return_value=True)
        task._click_reference = mock.Mock()
        task.sleep = lambda *_: None
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task._keys_refused = False
        return task

    def test_page_after_a_fade_counts_as_arrived(self):
        task = self.task(["field", "fade", "fade", "page"])
        self.assertTrue(task._walk_up())
        task = self.task(["field", "field", "fade", "page"])
        self.assertTrue(task._click_up())

    def test_on_the_circle_steps_down_and_walks_up_again(self):
        task = self.task(["field"])
        results = iter([False, True])
        task._walk_up = lambda *a: next(results)
        self.assertTrue(task._walk_to_marker())
        task.hold_key.assert_called_once_with("s", mock.ANY, after_sleep=mock.ANY)

    def test_first_walk_steps_down_soon_when_no_marker_shows(self):
        task = self.task(["field"])
        with mock.patch(f"{MODULE}.find_castle_marker", return_value=None):
            self.assertFalse(task._walk_up(4))
        self.assertEqual(4, task.hold_key.call_count)

    def test_marker_seen_keeps_walking_past_the_unseen_limit(self):
        task = self.task(["field"] * 6 + ["page"])
        marks = iter([None, (958, 220)] + [(958, 300)] * 10)
        step = mock.Mock(key="w", seconds=0.35)
        with (
            mock.patch(f"{MODULE}.find_castle_marker", side_effect=lambda *_: next(marks)),
            mock.patch(f"{MODULE}.plan_step", return_value=step),
        ):
            self.assertTrue(task._walk_up(1))

    def test_on_the_circle_with_the_mouse_clicks_down_then_up(self):
        task = self.task(["field"])
        results = iter([False, True])
        task._click_up = lambda: next(results)
        self.assertTrue(task._click_to_marker())
        task._click_reference.assert_called_once()
        self.assertGreater(task._click_reference.call_args.args[1], 540)

    def test_no_step_back_off_the_field(self):
        task = self.task(["home"])
        task._walk_up = lambda *a: False
        self.assertFalse(task._walk_to_marker())
        task.hold_key.assert_not_called()


class ReadTest(unittest.TestCase):
    def test_only_zero_keys_count(self):
        # Leo 2026-10-21 「不要0/10就好」; paid keys may follow as 「+」 or small text.
        self.assertTrue(keys_empty(["+19:06", "0/10"]))
        self.assertTrue(keys_empty(["0/10+3"]))
        self.assertTrue(keys_empty(["0 / 10"]))
        # The 4K clone's misreads of 9/10 and the timer are not 0/10.
        for names in (["+19:06", "9/10", "10"], ["19:069/10"], ["69/10"], ["10/10"], []):
            with self.subTest(names):
                self.assertFalse(keys_empty(names))

    def test_dialog_reward_line(self):
        self.assertEqual(10, parse_reward_count("战斗10次奖励"))
        self.assertEqual(1, parse_reward_count("战斗1次奖励"))


class QuickBattleTest(unittest.TestCase):
    """Leo 2026-10-21 「就直接max 不管那麼多 不用對數字」: MAX, then 战斗 once;
    never 战斗 in a dry run, nothing at 0 keys."""

    def task(self, keys, dry=False):
        task = RedemptionTowerTask(SimpleNamespace(scene=None), SimpleNamespace(debug=False))
        task.config = {DRY_RUN_KEY: dry}
        task._open_tower = lambda: True
        task._no_keys_left = lambda: keys == (0, 10)
        task.look_again = lambda look, *a, **k: look()
        self.ticks = mock.patch("src.tasks.RedemptionTowerTask.level_ticks", return_value=9)
        self.ticks.start()
        self.addCleanup(self.ticks.stop)
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), np.uint8)
        task._reference_boxes = lambda *a: [
            SimpleNamespace(name="战斗", x=1000, y=790, width=60, height=30)
        ]
        task._dialog_visible = lambda frame: True
        task.press_and_confirm = mock.Mock(return_value=True)
        task._click_reference = mock.Mock()
        task._cancel_dialog = mock.Mock()
        task._after_battle = mock.Mock(return_value=True)
        task.sleep = lambda *_: None
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        return task

    def test_max_then_battle_once(self):
        task = self.task((9, 10))
        self.assertTrue(task._quick_battle())
        task._click_reference.assert_any_call(*MAX_POINT, after_sleep=mock.ANY)
        self.assertEqual(2, task.press_and_confirm.call_count)  # 快速战斗, 战斗
        self.assertEqual(0, task.press_and_confirm.call_args.kwargs["retries"])
        task._cancel_dialog.assert_not_called()
        task.press_and_confirm.call_args.args[1]()
        task._click_reference.assert_called_with(1030, 805, after_sleep=mock.ANY)
        task._after_battle.assert_called_once_with()

    def test_dry_run_presses_max_and_cancels(self):
        task = self.task((10, 10), dry=True)
        self.assertTrue(task._quick_battle())
        task._click_reference.assert_any_call(*MAX_POINT, after_sleep=mock.ANY)
        task._cancel_dialog.assert_called_once()
        self.assertEqual(1, task.press_and_confirm.call_count)  # 快速战斗 only
        task._after_battle.assert_not_called()

    def test_unread_keys_still_fight(self):
        # 「目標是完成任務 不要自斷手腳」: only 0/10 stops the run.
        task = self.task(None)
        self.assertTrue(task._quick_battle())
        task._after_battle.assert_called_once_with()

    def test_unread_battle_word_uses_its_fixed_place_while_the_dialog_shows(self):
        task = self.task((9, 10))
        task._reference_boxes = lambda *a: []
        self.assertTrue(task._quick_battle())
        press = task.press_and_confirm.call_args.args[1]
        press()
        task._click_reference.assert_called_with(*BATTLE_BUTTON_POINT, after_sleep=mock.ANY)

    def test_no_battle_press_once_the_dialog_is_gone(self):
        task = self.task((9, 10))
        task._reference_boxes = lambda *a: []
        task._dialog_visible = lambda frame: False
        self.assertFalse(task._quick_battle())
        self.assertEqual(1, task.press_and_confirm.call_count)

    def test_fallback_test_only_in_a_dry_run(self):
        task = self.task((10, 10), dry=False)
        task.config[FALLBACK_TEST_KEY] = True
        self.assertFalse(task._fallback_test())
        task.config[DRY_RUN_KEY] = True
        self.assertTrue(task._fallback_test())

    def test_no_keys_left_is_done_without_a_press(self):
        task = self.task((0, 10))
        self.assertTrue(task._quick_battle())
        task.press_and_confirm.assert_not_called()

    def test_not_played_this_season_leaves_without_a_press(self):
        task = self.task((10, 10))
        with mock.patch("src.tasks.RedemptionTowerTask.level_ticks", return_value=0):
            self.assertTrue(task._quick_battle())
        task.press_and_confirm.assert_not_called()


class SeasonSettlingTest(unittest.TestCase):
    """繁中 4K 2026-11-05: between seasons the card opens 排名 with 賽季結算中;
    the run is 跳过 (not 失败) and nothing is pressed there."""

    def task(self, text):
        task = RedemptionTowerTask(SimpleNamespace(scene=None), SimpleNamespace(debug=False))
        task.config = {DRY_RUN_KEY: False}
        task.capture_frame = lambda: np.zeros((1080, 1920, 3), np.uint8)
        task._wait_boxes = lambda *a, **k: []
        task._box_with = lambda *a: None
        task.press_and_confirm = mock.Mock(return_value=False)
        task._wait_for = lambda look, timeout=0: look(task.capture_frame())
        task._tower_page_visible = lambda frame: False
        task._text_in = lambda frame, roi, name: text
        task._click_reference = mock.Mock()
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        return task

    def test_settling_page_is_skipped_without_a_battle(self):
        task = self.task("賽季結算中 離結算結束還有7小時56分鐘")
        task.done_already_note = ""
        self.assertTrue(task._quick_battle())
        self.assertEqual(SETTLING_NOTE, task.done_already_note)
        self.assertEqual(1, task.press_and_confirm.call_count)  # the card only

    def test_other_page_still_fails(self):
        task = self.task("排名")
        task.done_already_note = ""
        self.assertFalse(task._open_tower())
        self.assertEqual("", task.done_already_note)


class AfterBattleTest(unittest.TestCase):
    def task(self, screens):
        task = RedemptionTowerTask(SimpleNamespace(scene=None), SimpleNamespace(debug=False))
        screens = iter(screens)
        task.capture_frame = lambda: next(screens)
        task._result_visible = lambda frame: frame == "result"
        task._tower_page_visible = lambda frame: frame == "page"
        task._click_reference = mock.Mock()
        task.close_known_popup = lambda *a: False
        task.sleep = lambda *_: None
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        return task

    def test_result_screen_tapped_then_done(self):
        task = self.task(["result", "page"])
        self.assertTrue(task._after_battle())
        task._click_reference.assert_called_once()

    def test_page_without_result_waits_for_it_to_stay(self):
        task = self.task(["page"] * 10)
        clock = iter(float(n) for n in range(100))
        with mock.patch(f"{MODULE}.monotonic", lambda: next(clock)):
            self.assertTrue(task._after_battle())
        task = self.task(["page", "result", "page"])
        self.assertTrue(task._after_battle())
        task._click_reference.assert_called_once()  # the late result is tapped


def _real_ocr_vision():
    """ocr_boxes like the tool's (v6 recognizer, ROI read at 1080 scale)."""
    from src.compat.ocr_models import install_v6_recognizer

    install_v6_recognizer()
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr

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


class RealKeysReadTest(unittest.TestCase):
    """The corner of the 4K clone frames of 10-21, where the tool read 69/10,
    29/10 and 9/102 for 9/10 (the refill timer above joined in)."""

    def test_nine_of_ten_is_not_empty_at_every_size(self):
        try:
            vision = _real_ocr_vision()
        except ImportError as missing:
            self.skipTest(f"OCR engine unavailable: {missing}")
        task = RedemptionTowerTask(SimpleNamespace(scene=None), SimpleNamespace(debug=False))
        task._quick_vision = lambda: vision
        task.sleep = lambda *_: None
        task.log_info = lambda *a, **k: None
        for name in ("corner_timer_keys_4k_a.png", "corner_timer_keys_4k_b.png"):
            frame = np.zeros((1080, 1920, 3), np.uint8)
            frame[0:110, 1600:1920] = load(name)
            for size in ((1920, 1080), (2560, 1440), (3840, 2160)):
                with self.subTest(name=name, size=size):
                    task.capture_frame = lambda f=cv2.resize(frame, size): f
                    self.assertFalse(task._no_keys_left())


if __name__ == "__main__":
    unittest.main()
