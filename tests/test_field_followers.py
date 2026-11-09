import unittest
from pathlib import Path

import cv2
import numpy as np

from src.utils import task_vision
from src.utils.field_followers import (
    FIELD_TALK_ICON_TEMPLATE,
    FOLLOWERS_ABSENT,
    FOLLOWERS_DISMISSED,
    FOLLOWERS_STILL_VISIBLE,
    TalkIconSighting,
    dismiss_field_followers,
    dismiss_once_per_run,
    dismissed_today,
    is_exclamation_glyph,
    mark_dismissed,
    reset_dismissed,
)

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "recognition-assets" / "template-assets"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "field"
# The fixtures are 400x320 crops of a 3840x2160 frame (Leo, PVP hub with the
# follower crowd, 2026-10-03) taken at 4K (2600, 1640); the other buttons are
# cut so that their centre lands where the F button's is.
CROP_ORIGIN_4K = (2600, 1640)
SIZES = ((1920, 1080), (2560, 1440), (3840, 2160))


def _frame(crop_name, size, transform=None):
    width, height = size
    rng = np.random.default_rng(7)
    frame = rng.integers(20, 90, size=(height, width, 3), dtype=np.uint8)
    crop = cv2.imread(str(FIXTURES / crop_name))
    factor = width / 3840
    crop = cv2.resize(
        crop,
        (round(crop.shape[1] * factor), round(crop.shape[0] * factor)),
        interpolation=cv2.INTER_AREA,
    )
    x, y = round(CROP_ORIGIN_4K[0] * factor), round(CROP_ORIGIN_4K[1] * factor)
    frame[y : y + crop.shape[0], x : x + crop.shape[1]] = crop
    return transform(frame) if transform else frame


def _passes(frame):
    result = task_vision.match_template(
        frame, FIELD_TALK_ICON_TEMPLATE, {}, TEMPLATE_DIR, {}, min_size=5
    )
    return task_vision.passes_match(result, FIELD_TALK_ICON_TEMPLATE, {}), result


def _hdr_like(frame):
    # Washed-out highlights and boosted saturation, as RTX HDR / 鲜艳度 do.
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.4, 0, 255)
    hsv[:, :, 2] = np.clip(255 * (hsv[:, :, 2] / 255) ** 0.8, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


class TalkIconRecognitionTest(unittest.TestCase):
    def test_follower_icon_found_at_every_resolution_and_with_hdr(self):
        for size in SIZES:
            for transform in (None, _hdr_like):
                with self.subTest(size=size, hdr=transform is not None):
                    passed, result = _passes(_frame("f_slot_followers_4k.png", size, transform))
                    self.assertTrue(passed, result)
                    center_x = (result.position[0] + result.size[0] / 2) / size[0]
                    center_y = (result.position[1] + result.size[1] / 2) / size[1]
                    # The F button centre, 1080p (1411, 885).
                    self.assertAlmostEqual(1411 / 1920, center_x, delta=0.006)
                    self.assertAlmostEqual(885 / 1080, center_y, delta=0.01)

    def test_other_buttons_in_the_f_place_are_not_the_icon(self):
        for name in ("slot2_button_4k.png", "slot3_button_4k.png"):
            for size in SIZES:
                with self.subTest(name=name, size=size):
                    passed, result = _passes(_frame(name, size))
                    self.assertFalse(passed, result)

    def test_only_the_exclamation_glyph_counts(self):
        # cp3 at 4K, 2026-10-04: the talk "…" beside 艾琳 and the teleport
        # circle's hand pass the masked template; the press opened them.
        cases = (
            ("f_slot_followers_4k.png", True),
            ("f_slot_talk_4k.png", False),
            ("f_slot_circle_hand_4k.png", False),
        )
        for name, expected in cases:
            for size in SIZES:
                for transform in (None, _hdr_like):
                    with self.subTest(name=name, size=size, hdr=transform is not None):
                        frame = _frame(name, size, transform)
                        passed, result = _passes(frame)
                        if not passed:
                            self.assertFalse(expected, result)
                            continue
                        x, y = result.position
                        w, h = result.size
                        self.assertEqual(expected, is_exclamation_glyph(frame[y : y + h, x : x + w]))

    def test_empty_f_slot_over_white_stairs_is_not_the_icon(self):
        # 4K PC live daily 2026-11-08 (2560x1440 game): beside the goddess the
        # F slot was empty; the stairs scored 0.958 and a crack passed as the
        # bar, so the square and 跑商 pressed 4 times and F twice.  The crop
        # is cut at the 2K equivalent of CROP_ORIGIN_4K.
        crop = cv2.imread(str(FIXTURES / "f_slot_empty_stairs_2k.png"))
        for size in SIZES:
            for transform in (None, _hdr_like):
                with self.subTest(size=size, hdr=transform is not None):
                    width, height = size
                    factor = width / 2560
                    frame = np.random.default_rng(7).integers(
                        20, 90, size=(height, width, 3), dtype=np.uint8
                    )
                    scaled = cv2.resize(
                        crop,
                        (round(crop.shape[1] * factor), round(crop.shape[0] * factor)),
                        interpolation=cv2.INTER_AREA,
                    )
                    x = round(CROP_ORIGIN_4K[0] * width / 3840)
                    y = round(CROP_ORIGIN_4K[1] * height / 2160)
                    frame[y : y + scaled.shape[0], x : x + scaled.shape[1]] = scaled
                    frame = transform(frame) if transform else frame
                    passed, result = _passes(frame)
                    if not passed:
                        continue
                    left, top = result.position
                    w, h = result.size
                    self.assertFalse(is_exclamation_glyph(frame[top : top + h, left : left + w]), result)

    def test_dimmed_icon_is_not_pressed(self):
        frame = _frame("f_slot_followers_4k.png", (1920, 1080))
        passed, _result = _passes((frame * 0.35).astype(np.uint8))
        self.assertFalse(passed)


class DismissFlowTest(unittest.TestCase):
    CENTER = (0.735, 0.82)

    def _run(self, sightings, **kwargs):
        frames = iter(sightings)
        clicks, sleeps = [], []
        now = [0.0]

        def observe():
            return next(frames, TalkIconSighting(False))

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        outcome = dismiss_field_followers(
            observe, lambda x, y: clicks.append((x, y)), sleep, clock=lambda: now[0], **kwargs
        )
        return outcome, clicks

    def seen(self, center=None):
        return TalkIconSighting(True, 0.99, center or self.CENTER)

    def test_gather_wait_then_press_and_the_f_key_when_the_click_did_nothing(self):
        # Leo 2026-10-20: wait 5 s in place once the "!" shows, press it, and
        # press F when the click left it up.
        keys = []
        seen = self.seen()
        frames = [seen] * 7  # 2 + gather, 2 + click, 1 still up, 2 + F key
        outcome, clicks = self._run(
            frames, gather_seconds=5.0, press_key=lambda: keys.append("F")
        )
        self.assertEqual(FOLLOWERS_DISMISSED, outcome)
        self.assertEqual([self.CENTER], clicks)
        self.assertEqual(["F"], keys)

    def test_icon_gone_after_the_gather_wait_is_not_pressed(self):
        outcome, clicks = self._run([self.seen(), self.seen()], gather_seconds=5.0)
        self.assertEqual(FOLLOWERS_ABSENT, outcome)
        self.assertEqual([], clicks)

    def test_two_matching_frames_then_press_then_gone(self):
        outcome, clicks = self._run([self.seen(), self.seen()])
        self.assertEqual(FOLLOWERS_DISMISSED, outcome)
        self.assertEqual([self.CENTER], clicks)

    def test_single_frame_or_moving_match_is_never_pressed(self):
        outcome, clicks = self._run([self.seen()])
        self.assertEqual((FOLLOWERS_ABSENT, []), (outcome, clicks))
        outcome, clicks = self._run([self.seen(), self.seen((0.2, 0.3))])
        self.assertEqual((FOLLOWERS_ABSENT, []), (outcome, clicks))

    def test_late_crowd_is_waited_for(self):
        quiet = [TalkIconSighting(False)] * 4
        outcome, clicks = self._run(quiet + [self.seen(), self.seen()], appear_seconds=3.0)
        self.assertEqual(FOLLOWERS_DISMISSED, outcome)
        self.assertEqual(1, len(clicks))

    def test_lost_press_is_retried_once_then_given_up(self):
        outcome, clicks = self._run([self.seen()] * 30, max_clicks=2)
        self.assertEqual(FOLLOWERS_STILL_VISIBLE, outcome)
        self.assertEqual(2, len(clicks))

    def test_lost_press_then_success(self):
        frames = [self.seen(), self.seen(), self.seen(), self.seen(), self.seen()]
        outcome, clicks = self._run(frames)
        self.assertEqual(FOLLOWERS_DISMISSED, outcome)
        self.assertEqual(2, len(clicks))


class CrowdBalloonTest(unittest.TestCase):
    """The "!" balloons over the 派遣 crowd (Leo's 1080p 镜中之战 frame,
    2026-11-09) only add waiting, never shorten a look."""

    CENTER = (0.735, 0.82)

    def _run(self, sightings, crowd_frames, **kwargs):
        frames = iter(sightings)
        crowds = iter(crowd_frames)
        clicks, keys = [], []
        now = [0.0]

        def sleep(seconds):
            now[0] += seconds

        outcome = dismiss_field_followers(
            lambda: next(frames, TalkIconSighting(False)),
            lambda x, y: clicks.append((x, y)),
            sleep,
            clock=lambda: now[0],
            crowd=lambda: next(crowds, False),
            press_key=lambda: keys.append("F"),
            **kwargs,
        )
        return outcome, clicks, keys, now[0]

    def seen(self):
        return TalkIconSighting(True, 0.99, self.CENTER)

    def test_crowd_still_walking_over_is_waited_for_past_the_look(self):
        # A slow PC: the F "!" shows only after the 5 s look (15 frames at
        # 0.35 s); the balloons on screen keep the look going.
        quiet = [TalkIconSighting(False)] * 20
        outcome, clicks, _keys, _t = self._run(
            quiet + [self.seen(), self.seen()], [True] * 40 + [False] * 10,
            appear_seconds=5.0,
        )
        self.assertEqual(FOLLOWERS_DISMISSED, outcome)
        self.assertEqual(1, len(clicks))

    def test_without_balloons_the_look_is_as_before(self):
        quiet = [TalkIconSighting(False)] * 20
        outcome, clicks, _keys, waited = self._run(
            quiet + [self.seen(), self.seen()], [False] * 50, appear_seconds=5.0
        )
        self.assertEqual((FOLLOWERS_ABSENT, []), (outcome, clicks))
        self.assertLess(waited, 6.0)

    def test_crowd_wait_has_a_cap(self):
        outcome, clicks, _keys, waited = self._run(
            [], [True] * 500, appear_seconds=5.0, crowd_wait_seconds=15.0
        )
        self.assertEqual((FOLLOWERS_ABSENT, []), (outcome, clicks))
        self.assertLess(waited, 17.0)

    def test_balloons_left_after_the_press_get_the_f_key(self):
        # The F "!" went (the HUD hides while moving) but the crowd stays.
        outcome, clicks, keys, _t = self._run(
            [self.seen(), self.seen()], [True] * 50, appear_seconds=3.0
        )
        self.assertEqual(FOLLOWERS_DISMISSED, outcome)
        self.assertEqual((1, ["F"]), (len(clicks), keys))

    def test_balloons_gone_with_the_press_need_no_key(self):
        outcome, clicks, keys, _t = self._run(
            [self.seen(), self.seen()], [False] * 50, appear_seconds=3.0
        )
        self.assertEqual((FOLLOWERS_DISMISSED, 1, []), (outcome, len(clicks), keys))


class BalloonRecognitionTest(unittest.TestCase):
    PAGES = Path(__file__).resolve().parent / "fixtures"
    # Saved frames that show the crowd: Leo's hub, the square, 救赎之塔.
    CROWD = {
        "pvp/hub_dispatch_crowd_leo_1080.jpg",
        "square/square_field_nav_menu_2k.jpg",
        "redemption_tower/field_spawn_2k.jpg",
        "redemption_tower/field_altar_marker_2k.jpg",
    }

    def test_crowd_found_at_every_resolution_and_with_hdr(self):
        from src.utils.follower_balloons import crowd_seen

        hub = cv2.imread(str(self.PAGES / "pvp/hub_dispatch_crowd_leo_1080.jpg"))
        for size in SIZES:
            for transform in (None, _hdr_like):
                with self.subTest(size=size, hdr=transform is not None):
                    frame = cv2.resize(hub, size, interpolation=cv2.INTER_CUBIC)
                    self.assertTrue(crowd_seen(transform(frame) if transform else frame))

    def test_crowd_only_on_the_frames_that_show_it(self):
        import json

        from src.utils.follower_balloons import crowd_seen

        pages = json.loads((self.PAGES / "pages.json").read_text(encoding="utf-8"))["pages"]
        paths = set(pages) | self.CROWD
        for path in sorted(paths):
            with self.subTest(picture=path):
                frame = cv2.imread(str(self.PAGES / path))
                self.assertEqual(path in self.CROWD, crowd_seen(frame))


class DayRecordTest(unittest.TestCase):
    """Leo 2026-11-09 「當天有沒有派遣 要記錄下來」 / 「如果有紀錄派遣成功，就不用等」."""

    def setUp(self):
        reset_dismissed()
        self.addCleanup(reset_dismissed)

    def test_the_day_keeps_its_best_outcome_and_every_look(self):
        from src.utils.field_followers import note_look, record_text, today_record

        note_look("absent", "自动PVP", waited=5.0)
        note_look("dismissed", "广场女神像", waited=11.2)
        note_look("absent", "跑商", waited=0.5)
        record = today_record()
        self.assertEqual(("dismissed", "广场女神像"), (record["state"], record["where"]))
        self.assertEqual(3, len(record["looks"]))
        self.assertTrue(record_text(record).startswith("已领（广场女神像"))

    def test_not_claimed_says_where_it_looked(self):
        from src.utils.field_followers import note_look, record_text, today_record

        note_look("key_pressed_blind", "自动PVP", waited=5.0)
        note_look("absent", "广场女神像", waited=10.0)
        self.assertEqual(
            "没看到「!」，照样按了一次 F（找过：自动PVP 5 秒 按了 F、广场女神像 10 秒）",
            record_text(today_record()),
        )

    def test_a_saved_claim_is_remembered_after_a_restart(self):
        from src.utils import field_followers

        field_followers.note_look("dismissed", "自动PVP")
        field_followers.mark_dismissed()
        # A new tool life: memory gone, the file stays.
        field_followers._dismissed_game_day.clear()
        field_followers._day_records.clear()
        self.assertTrue(dismissed_today())

    def test_each_account_has_its_own_day(self):
        from unittest import mock

        from src.utils import accounts

        with mock.patch.object(accounts, "current_id", return_value="1"):
            mark_dismissed()
            self.assertTrue(dismissed_today())
        with mock.patch.object(accounts, "current_id", return_value="2"):
            self.assertFalse(dismissed_today())


class DispatchReportTest(unittest.TestCase):
    """Today's 派遣 reaches the run report, the 问题摘要 and the results page.
    Those callers swallow errors, so each is run for real here."""

    def setUp(self):
        reset_dismissed()
        self.addCleanup(reset_dismissed)

    def test_batch_marks_todays_dispatch_on_its_report(self):
        from unittest import mock

        from src.tasks import run_report
        from src.tasks.DailyBatchTask import DailyBatchTask
        from src.utils.field_followers import note_look

        note_look("dismissed", "自动PVP", waited=6.0)
        with mock.patch.object(run_report, "mark") as mark:
            DailyBatchTask._mark_dispatch()
        key, value = mark.call_args.args
        self.assertEqual("dispatch", key)
        self.assertEqual("dismissed", value["state"])
        self.assertTrue(value["text"].startswith("已领（自动PVP"))

    def test_problem_summary_and_results_page_say_it(self):
        from src.tasks import problem_report
        from src.ui.shell.home import dispatch_line
        from src.utils.field_followers import note_look

        self.assertIsNone(problem_report._dispatch_today())
        note_look("absent", "广场女神像", waited=5.0)
        dispatch = problem_report._dispatch_today()
        self.assertEqual("absent", dispatch["state"])
        self.assertIn("广场女神像 5 秒", dispatch["text"])
        self.assertTrue(dispatch_line(dispatch))
        self.assertEqual("", dispatch_line(None))


class OncePerDayTest(unittest.TestCase):
    def setUp(self):
        reset_dismissed()
        self.addCleanup(reset_dismissed)

    def test_dismissal_lasts_until_the_0800_game_day_change(self):
        from datetime import datetime, timedelta, timezone

        tz = timezone(timedelta(hours=8))
        mark_dismissed(datetime(2026, 10, 3, 9, 0, tzinfo=tz))
        self.assertTrue(dismissed_today(datetime(2026, 10, 4, 7, 59, tzinfo=tz)))
        self.assertFalse(dismissed_today(datetime(2026, 10, 4, 8, 0, tzinfo=tz)))

    def test_navigator_looks_once_per_run(self):
        from types import SimpleNamespace

        calls = []
        navigator = SimpleNamespace(
            task=SimpleNamespace(dismiss_field_followers=lambda: calls.append(1))
        )
        dismiss_once_per_run(navigator)
        dismiss_once_per_run(navigator)
        self.assertEqual([1], calls)
        # A task without the helper (test doubles) is left alone.
        dismiss_once_per_run(SimpleNamespace(task=SimpleNamespace()))


if __name__ == "__main__":
    unittest.main()
