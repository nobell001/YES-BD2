"""YES-BD2 #75 (2026-11-09): the title without TOUCH TO START.

A player: when the title loads slowly it goes into a standby that hides
TOUCH TO START for good, and the login waited forever (it only looked for
those words).  Live 2K 2026-11-09 (tests/fixtures/title/): any tap on the
title logs in.  Now the title is also known by its version + UID lines; once
「啟動遊戲中」 is gone and the words stay missing 10 s, the blank upper
middle is tapped (at most 3 times, 10 s apart), then the player is told.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks.trigger import AutoLoginTask as module
from src.tasks.trigger.AutoLoginTask import AutoLoginTask, MatchResult
from src.utils import title_screen

FRAME = np.zeros((1080, 1920, 3), dtype=np.uint8)
MISS = MatchResult(-1.0, (0, 0), (0, 0), pixel_score=-1.0)


def box(name, x, y):
    return SimpleNamespace(name=name, x=x, y=y, width=200, height=24)


CORNER = [box("v2.38.11(FHD-902:727)", 274, 50), box("UID:12345678", 278, 73)]
LOGO = [box("BROWN DUSTII", 1140, 317), box("棕色塵埃2", 1154, 435)]
TITLE_NO_TOUCH = CORNER + LOGO
TITLE_STARTING = CORNER + LOGO + [box("啟動遊戲中", 1336, 695)]
TITLE_TOUCH = CORNER + LOGO + [box("TOUCH TO START", 1190, 667)]


class TitleScreenTest(unittest.TestCase):
    def test_title_known_with_and_without_its_words(self):
        shape = FRAME.shape
        self.assertTrue(title_screen.shown(TITLE_TOUCH, shape))
        self.assertTrue(title_screen.shown(TITLE_NO_TOUCH, shape))
        self.assertTrue(title_screen.shown([box("T0UCH TO STAR", 1190, 667)], shape))

    def test_one_corner_line_or_the_logo_alone_is_not_the_title(self):
        shape = FRAME.shape
        # A profile page may show a UID; the loading logo shows the name.
        self.assertFalse(title_screen.shown([CORNER[1]], shape))
        self.assertFalse(title_screen.shown([CORNER[0]], shape))
        self.assertFalse(title_screen.shown(LOGO, shape))
        # The same lines away from the top-left corner.
        far = [box("v2.38.11", 1500, 900), box("UID:12345678", 1500, 930)]
        self.assertFalse(title_screen.shown(far, shape))

    def test_starting_words(self):
        self.assertTrue(title_screen.still_starting(TITLE_STARTING))
        self.assertFalse(title_screen.still_starting(TITLE_NO_TOUCH))


class TitleWakeTapTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        patcher = mock.patch.object(module, "monotonic", lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.boxes = TITLE_NO_TOUCH
        self.clicks = []
        self.warnings = []
        task = object.__new__(AutoLoginTask)
        task.config = {
            "BrownDustX 阈值": 0.82,
            "BrownDustX 像素阈值": 0.86,
            "BrownDustX Confirm 阈值": 0.82,
            "BrownDustX Confirm 像素阈值": 0.86,
            "TOUCH TO START 阈值": 0.78,
            "登录按钮点击 X 百分比": 72.2396,
            "登录按钮点击 Y 百分比": 65.0926,
        }
        task._state = "waiting"
        task._no_login_signal_since = None
        task._login_clicked_at = None
        task._login_clicks = 0
        task._touch_still_hits = 0
        task._title_held = module.HeldFor()
        task._wake_taps = 0
        task._wake_tapped_at = None
        task._wake_failed_warned = False
        task.info_set = lambda *_a, **_k: None
        task.log_info = lambda *_a, **_k: None
        task.log_warning = lambda message, **_k: self.warnings.append(message)
        task._sleep_after_recognition = lambda: None
        task.operate_click = lambda x, y, **_k: self.clicks.append((x, y))
        task._login_page_ocr = lambda _frame: (list(self.boxes), "")
        task._maintenance_blocks = lambda *_a: False
        task._terms_dialog_blocks = lambda *_a: False
        task._find_update_download_button = lambda *_a: None
        task._download_progress_text = lambda *_a: ""
        task._match = lambda _frame, _spec: MISS
        task._is_browndustx_confirm = lambda *_a: False
        task._find_browndustx_confirm_ocr_box = lambda *_a: None
        task._is_browndustx_present = lambda *_a: False
        task._gated_batch_waiting = lambda: False
        self.task = task

    def look(self, seconds_later=0.0):
        """Looks one second apart (the trigger's pace) until ``seconds_later``."""
        steps = max(1, int(seconds_later)) if seconds_later else 1
        for _ in range(steps):
            self.now += seconds_later / steps if seconds_later else 0.0
            AutoLoginTask._wait_browndustx_then_login(self.task, FRAME)

    def test_title_without_words_is_tapped_after_ten_seconds(self):
        self.look()
        self.look(5)
        self.assertEqual([], self.clicks)
        self.look(5)
        self.assertEqual([(title_screen.WAKE_TAP_X, title_screen.WAKE_TAP_Y)], self.clicks)

    def test_nothing_is_tapped_while_the_game_is_still_starting(self):
        self.boxes = TITLE_STARTING
        for _ in range(10):
            self.look(10)
        self.assertEqual([], self.clicks)
        # The spinner gone: 10 s more, then the tap.
        self.boxes = TITLE_NO_TOUCH
        self.look(1)
        self.look(10)
        self.assertEqual(1, len(self.clicks))

    def test_the_tap_that_starts_the_login_waits_for_home(self):
        self.look()
        self.look(10)
        self.assertEqual(1, len(self.clicks))
        self.boxes = []  # black loading screen
        for _ in range(4):
            self.look(1)
            self.assertEqual("waiting", self.task._state)  # a few misreads are no login
        self.look(1)
        self.assertEqual("waiting_loading", self.task._state)
        self.assertEqual(self.now, self.task._login_clicked_at)

    def test_misread_looks_do_not_start_the_wait_over(self):
        """#528 live 4K: 99 of 148 looks read both lines; the tap came after
        2 min 20 s.  Every third look reading nothing, the tap is at 10 s."""
        self.look()
        for second in range(1, 11):
            self.boxes = [] if second % 3 == 0 else TITLE_NO_TOUCH
            self.look(1)
        self.assertEqual(1, len(self.clicks))

    def test_misread_corner_lines_still_read_as_the_title(self):
        misread = [box("2.38.11(FHD-902:727)", 274, 50), box("JID:12345678", 278, 73)]
        slash = [box("/2.38.11", 274, 50), box("UID:12345678", 278, 73)]
        self.assertTrue(title_screen.shown(misread, FRAME.shape))
        self.assertTrue(title_screen.shown(slash, FRAME.shape))
        # Other digits after 「UID」: still exact digits, at least five.
        self.assertFalse(title_screen.shown([box("2.38.11", 274, 50), box("UID:12", 278, 73)], FRAME.shape))

    def test_a_tap_that_did_not_log_in_goes_back_to_waking(self):
        self.look()
        self.look(10)
        self.boxes = []
        self.look(5)
        self.assertEqual("waiting_loading", self.task._state)
        # The wordless title is back for longer than the miss grace.
        self.boxes = TITLE_NO_TOUCH
        self.task._login_page_ocr = lambda _frame: (list(self.boxes), "")
        self.assertFalse(AutoLoginTask._wordless_title_back(self.task, FRAME, list(self.boxes)))
        self.now += 2
        self.assertFalse(AutoLoginTask._wordless_title_back(self.task, FRAME, list(self.boxes)))
        self.now += 2
        self.assertTrue(AutoLoginTask._wordless_title_back(self.task, FRAME, list(self.boxes)))
        self.assertEqual("waiting", self.task._state)

    def test_the_title_with_its_words_after_a_press_is_not_sent_back(self):
        self.task._state = "waiting_loading"
        self.boxes = TITLE_TOUCH
        for _ in range(6):
            self.assertFalse(AutoLoginTask._wordless_title_back(self.task, FRAME, list(self.boxes)))
            self.now += 1

    def test_words_back_after_the_tap_press_login_as_usual(self):
        self.look()
        self.look(10)
        self.boxes = TITLE_TOUCH
        touch = MatchResult(0.85, (1190, 667), (400, 40), pixel_score=0.85)
        self.task._match = lambda _frame, spec: (
            touch if spec is module.TOUCH_TO_START_TEMPLATE else MISS
        )
        self.look(1)
        self.assertEqual(2, len(self.clicks))
        self.assertEqual("waiting_loading", self.task._state)

    def test_three_taps_ten_seconds_apart_then_the_player_is_told(self):
        self.look()
        self.look(40)
        self.assertEqual(3, len(self.clicks))
        self.assertEqual(1, len(self.warnings))
        self.assertIn("请自己点一下游戏画面", self.warnings[0])
        for _ in range(5):
            self.look(10)
        self.assertEqual(3, len(self.clicks))
        self.assertEqual(1, len(self.warnings))

    def test_a_screen_that_is_not_the_title_is_never_tapped(self):
        self.boxes = LOGO  # the loading logo
        for _ in range(10):
            self.look(10)
        self.assertEqual([], self.clicks)


class HeldForTest(unittest.TestCase):
    def test_short_misses_keep_the_count(self):
        held = module.HeldFor(grace=3.0)
        self.assertEqual(0.0, held.look(True, 0.0))
        self.assertEqual(1.0, held.look(False, 1.0))
        self.assertEqual(2.5, held.look(False, 2.5))
        self.assertEqual(3.0, held.look(True, 3.0))

    def test_a_long_miss_starts_over(self):
        held = module.HeldFor(grace=3.0)
        held.look(True, 0.0)
        self.assertEqual(0.0, held.look(False, 3.5))
        self.assertFalse(held.showing(3.5))
        self.assertEqual(0.0, held.look(True, 4.0))
        self.assertEqual(1.0, held.look(True, 5.0))


class RecoveryTitleTest(unittest.TestCase):
    def test_recovery_hands_the_wordless_title_to_the_login(self):
        from src.tasks import recovery

        task = SimpleNamespace(capture_frame=lambda: FRAME)
        vision = SimpleNamespace(ocr_boxes=lambda *_a, **_k: list(TITLE_NO_TOUCH))
        self.assertEqual("title", recovery._handle_dialog(task, vision))


if __name__ == "__main__":
    unittest.main()
