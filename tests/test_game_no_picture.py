"""The game runs but draws nothing (Leo's 4K 桌面分身 2026-11-20, v0.4.9).

The game opened by Google Play Games after its first start failed had a
picture size of 0: its Player.log wrote 「RenderTexture.Create failed: width &
height must be larger than 0」 160,633 times, the window only flashed flat
colours, and 一键完成日常 waited 21 minutes for a login page that never
showed.  Now the auto-login proves it (the log line plus flat captures),
closes the game and opens it again once, then gives the run up with the
reason.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks.trigger import AutoLoginTask as module
from src.tasks.trigger.AutoLoginTask import AutoLoginTask
from src.utils import game_no_picture
from src.utils.game_no_picture import (
    NO_PICTURE_FALLBACK_SECONDS,
    NO_PICTURE_SECONDS,
    ZERO_SIZE_LINE,
    NoPictureWatch,
    ZeroSizeLog,
    flat_picture,
)

FIXTURES = Path(__file__).parent / "fixtures"
# The clone's last frame (960x540 viewer picture, scaled back to 1080p): a
# flat dark-red square between black bars.
PLAYER_FRAME = FIXTURES / "title" / "no_picture_flat_4k_clone_1120.jpg"


def _read(path: Path):
    frame = cv2.imread(str(path))
    assert frame is not None, path
    return frame


def _flat_grey():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[:, 420:1500] = (209, 211, 211)
    return frame


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeLog:
    """new_lines() answers in turn; None = the log cannot be read."""

    def __init__(self, lines):
        self.lines = lines

    def new_lines(self):
        return self.lines


class FlatPictureTest(unittest.TestCase):
    def test_the_players_frames_are_flat(self):
        self.assertTrue(flat_picture(_read(PLAYER_FRAME)))
        self.assertTrue(flat_picture(_flat_grey()))

    def test_real_pages_are_not_flat(self):
        for name in (
            "title/title_touch_2k_clone.jpg",
            "title/title_starting_2k_clone.jpg",
            "pvp/home_bright_skin_cues_fhd.png",
            "map_trade/home_return/update_notice.png",
        ):
            with self.subTest(name):
                self.assertFalse(flat_picture(_read(FIXTURES / name)))

    def test_nothing_captured_is_not_flat(self):
        self.assertFalse(flat_picture(None))
        self.assertFalse(flat_picture(np.zeros((0, 0, 3), dtype=np.uint8)))


class ZeroSizeLogTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "Player.log"

    def tearDown(self):
        self.dir.cleanup()

    def _append(self, text: bytes):
        with open(self.path, "ab") as log:
            log.write(text)

    def test_counts_only_what_was_added(self):
        self._append(b"IntroUI::Intro\n" + (ZERO_SIZE_LINE + b"\n") * 5)
        log = ZeroSizeLog(self.path)
        self.assertEqual(5, log.new_lines())
        self.assertEqual(0, log.new_lines())
        self._append((ZERO_SIZE_LINE + b"\n") * 3 + b"IntroUI::Enter\n")
        self.assertEqual(3, log.new_lines())

    def test_a_new_game_run_starts_the_count_over(self):
        self._append((ZERO_SIZE_LINE + b"\n") * 50)
        log = ZeroSizeLog(self.path)
        log.new_lines()
        self.path.write_bytes(b"IntroUI::Intro\n")  # the game rewrites it on start
        self.assertEqual(0, log.new_lines())

    def test_no_log_is_none(self):
        self.assertIsNone(ZeroSizeLog(self.path).new_lines())
        self.assertIsNone(ZeroSizeLog(None).new_lines())


class NoPictureWatchTest(unittest.TestCase):
    def _run(self, watch, clock, frame, seconds):
        """Looks once a second; the first second it said yes, else None."""
        for second in range(int(seconds) + 1):
            clock.now = 100.0 + second
            if watch.look(frame):
                return second
        return None

    def test_log_proof_and_flat_frames_call_it_past_the_stuck_limit(self):
        clock = Clock()
        watch = NoPictureWatch(FakeLog(130), clock)
        self.assertEqual(NO_PICTURE_SECONDS, self._run(watch, clock, _read(PLAYER_FRAME), 30))
        self.assertIn("画面大小为 0", watch.proof)

    def test_flat_frames_with_a_quiet_log_are_the_game_working(self):
        # A black loading screen: flat, but the game's log says nothing wrong.
        clock = Clock()
        watch = NoPictureWatch(FakeLog(0), clock)
        self.assertIsNone(self._run(watch, clock, _read(PLAYER_FRAME), 300))

    def test_a_drawn_page_resets_it(self):
        clock = Clock()
        watch = NoPictureWatch(FakeLog(130), clock)
        self._run(watch, clock, _read(PLAYER_FRAME), NO_PICTURE_SECONDS - 2)
        self.assertFalse(watch.look(_read(FIXTURES / "title/title_touch_2k_clone.jpg")))
        self.assertIsNone(watch.since)

    def test_unreadable_log_waits_past_the_loading_limit(self):
        clock = Clock()
        watch = NoPictureWatch(FakeLog(None), clock)
        self.assertEqual(NO_PICTURE_FALLBACK_SECONDS, self._run(watch, clock, _flat_grey(), 120))
        self.assertGreater(NO_PICTURE_FALLBACK_SECONDS, 45.0)


class _SaysNoPicture:
    """A watch that has just proven it."""

    since = 1.0
    proof = "游戏日志一直写画面大小为 0，截图一直是纯色"

    def __init__(self, answer=True):
        self.answer = answer
        self.resets = 0

    def look(self, _frame):
        return self.answer

    def held_for(self):
        return 16.0

    def reset(self):
        self.resets += 1


def _login_task(batch_waiting=True):
    task = object.__new__(AutoLoginTask)
    task.config = {}
    task.info = {}
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    task.warnings = []
    task.log_warning = lambda message, **_k: task.warnings.append(message)
    task.log_info = lambda *_a, **_k: None
    task.log_error = lambda *_a, **_k: None
    task._state = "waiting"
    task._finished = False
    task._no_picture_reopens = 0
    task._title_held = mock.Mock()
    batch = SimpleNamespace(_start_after_login=batch_waiting)
    task.batch = batch
    task._executor = SimpleNamespace(
        get_task_by_class=lambda _cls: batch if batch_waiting else None
    )
    task.cancelled = []
    task._cancel_login_gated_batches = lambda: task.cancelled.append(1) or True
    task.reopened = []
    task._open_game_again = lambda: task.reopened.append(1)
    return task


class AutoLoginNoPictureTest(unittest.TestCase):
    def test_first_time_closes_and_reopens_the_game(self):
        task = _login_task()
        task._no_picture = _SaysNoPicture()
        with mock.patch.object(module.game_process, "close_game", return_value=True) as close:
            self.assertTrue(task._game_draws_nothing(_read(PLAYER_FRAME)))
        close.assert_called_once()
        self.assertEqual([1], task.reopened)
        self.assertEqual([], task.cancelled)
        self.assertEqual(1, task._no_picture_reopens)
        self.assertEqual("waiting", task._state)
        self.assertIn("关掉游戏重开一次", task.warnings[-1])
        self.assertIn("画面大小为 0", task.warnings[-1])

    def test_still_no_picture_after_the_reopen_cancels_the_run(self):
        task = _login_task()
        task._no_picture = _SaysNoPicture()
        task._no_picture_reopens = 1
        with mock.patch.object(module.game_process, "close_game") as close:
            self.assertTrue(task._game_draws_nothing(_read(PLAYER_FRAME)))
        close.assert_not_called()
        self.assertEqual([], task.reopened)
        self.assertEqual([1], task.cancelled)
        self.assertIn("一键日常/周常已取消", task.warnings[-1])

    def test_a_game_that_will_not_close_cancels_the_run(self):
        task = _login_task()
        task._no_picture = _SaysNoPicture()
        with mock.patch.object(module.game_process, "close_game", return_value=False):
            self.assertTrue(task._game_draws_nothing(_read(PLAYER_FRAME)))
        self.assertEqual([], task.reopened)
        self.assertEqual([1], task.cancelled)
        self.assertIn("关不掉", task.warnings[-1])

    def test_without_a_waiting_run_the_players_game_is_left_alone(self):
        task = _login_task(batch_waiting=False)
        task._no_picture = _SaysNoPicture()
        with mock.patch.object(module.game_process, "close_game") as close:
            self.assertFalse(task._game_draws_nothing(_read(PLAYER_FRAME)))
        close.assert_not_called()
        self.assertEqual(1, task._no_picture.resets)

    def test_not_proven_yet_goes_on_looking(self):
        task = _login_task()
        task._no_picture = _SaysNoPicture(answer=False)
        with mock.patch.object(module.game_process, "close_game") as close:
            self.assertFalse(task._game_draws_nothing(_read(PLAYER_FRAME)))
        close.assert_not_called()
        self.assertIn("纯色", task.info["画面"])

    def test_a_login_resets_the_reopen_count(self):
        task = _login_task()
        task._no_picture_reopens = 1
        task.scene = None
        task.mark_logged_in()
        self.assertEqual(0, task._no_picture_reopens)

    def test_the_players_case_end_to_end(self):
        """18:45 the game came up drawing nothing; the log kept failing."""
        task = _login_task()
        clock = Clock()
        task._no_picture = NoPictureWatch(FakeLog(130), clock)
        frame = _read(PLAYER_FRAME)
        with mock.patch.object(module.game_process, "close_game", return_value=True):
            for second in range(60):
                clock.now = 100.0 + second
                if task._game_draws_nothing(frame):
                    break
        self.assertEqual(NO_PICTURE_SECONDS, second)
        self.assertEqual([1], task.reopened)


class PlayerLogPathTest(unittest.TestCase):
    def test_path_under_the_users_locallow(self):
        with mock.patch.dict(game_no_picture.os.environ, {"USERPROFILE": "C:/Users/p"}):
            path = game_no_picture.player_log_path()
        self.assertEqual(
            Path("C:/Users/p/AppData/LocalLow/Gamfs/BrownDust II/Player.log"), path
        )


if __name__ == "__main__":
    unittest.main()
