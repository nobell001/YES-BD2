"""The stuck-screen watch (Leo 2026-10-13 「點擊沒反應 或者辨識不到卡住 那就回主頁
可以的話就重試沒辦法就下一步」「不要整個卡死」)."""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import BaseBD2Task as base_module
from src.utils.frozen_screen import (
    FROZEN_GAP_SECONDS,
    FROZEN_SCREEN_SECONDS,
    FrozenScreen,
    FrozenWatch,
    LOADING_WORDS_SECONDS,
    loading_words,
)


def _screen(value=90):
    frame = np.full((1080, 1920, 3), value, np.uint8)
    frame[500:560, 900:1000] = 200
    return frame


class FrozenWatchTest(unittest.TestCase):
    def _look_every(self, watch, frames, step=1.0):
        now = 0.0
        for frame in frames:
            watch.look(frame, now)
            now += step
        return now

    def test_a_still_screen_raises_after_the_limit(self):
        watch = FrozenWatch()
        frame = _screen()
        looks = int(FROZEN_SCREEN_SECONDS)
        self._look_every(watch, [frame] * looks)  # up to just under the limit
        with self.assertRaises(FrozenScreen):
            watch.look(frame, FROZEN_SCREEN_SECONDS)
        with self.assertRaises(FrozenScreen):  # stays raised until the run ends
            watch.look(_screen(30), FROZEN_SCREEN_SECONDS + 1)

    def test_a_moving_screen_never_raises(self):
        watch = FrozenWatch()
        frames = []
        for i in range(60):
            frame = _screen()
            frame[100:104, 100 + 10 * i : 140 + 10 * i] = 255  # a spinner-sized change
            frames.append(frame)
        self._look_every(watch, frames)

    def test_a_press_starts_the_count_over(self):
        watch = FrozenWatch()
        frame = _screen()
        for second in range(int(FROZEN_SCREEN_SECONDS) - 1):
            watch.look(frame, float(second))
        watch.pressed()
        for second in range(int(FROZEN_SCREEN_SECONDS) - 1, 2 * int(FROZEN_SCREEN_SECONDS) - 2):
            watch.look(frame, float(second))

    def test_a_pause_between_looks_starts_the_count_over(self):
        # 暂停 holds the run in a sleep: no looks meanwhile.
        watch = FrozenWatch()
        frame = _screen()
        watch.look(frame, 0.0)
        watch.look(frame, FROZEN_SCREEN_SECONDS - 1)
        later = FROZEN_SCREEN_SECONDS - 1 + FROZEN_GAP_SECONDS + 1
        watch.look(frame, later)
        watch.look(frame, later + FROZEN_SCREEN_SECONDS - 1)

    def test_a_recognised_target_starts_the_count_over(self):
        # Leo 2026-10-15 「10秒是卡死 或者辨識不到」: a still page being read is
        # not stuck (a slow 1080p PC read the buy page for over 10 s).
        watch = FrozenWatch()
        frame = _screen()
        limit = int(FROZEN_SCREEN_SECONDS)
        for second in range(limit - 1):
            watch.look(frame, float(second))
        watch.progress()
        for second in range(limit - 1, 2 * limit - 2):
            watch.look(frame, float(second))
        self.assertEqual(0, watch.ineffective)

    def test_paused_while_going_home(self):
        watch = FrozenWatch()
        watch.paused = 1
        for second in range(3 * int(FROZEN_SCREEN_SECONDS)):
            watch.look(_screen(), float(second))


class LoadingWordsHoldTest(unittest.TestCase):
    """Leo 2026-10-18 「有人電腦比較卡」: a still loading screen that is not
    black is waited for like the black one."""

    def test_loading_words(self):
        self.assertEqual("nowloading", loading_words("NOW LOADING"))
        self.assertEqual("连接中", loading_words("正在 连接中…"))
        self.assertEqual("", loading_words("3rd ANNIVERSARY BROWNDUSTII 棕色尘埃2"))
        self.assertEqual("", loading_words("我的小屋 好友 公会"))

    def test_a_held_screen_waits_up_to_the_loading_cap(self):
        watch = FrozenWatch()
        frame = _screen()
        now = 0.0
        while now < FROZEN_SCREEN_SECONDS:
            watch.look(frame, now)
            now += 1.0
        with self.assertRaises(FrozenScreen) as first:
            watch.look(frame, now)
        self.assertEqual("", str(first.exception))
        watch.hold_for_loading("连接中")
        while now < LOADING_WORDS_SECONDS - 1.0:
            now += 1.0
            watch.look(frame, now)
        with self.assertRaises(FrozenScreen) as second:
            watch.look(frame, LOADING_WORDS_SECONDS)
        self.assertEqual(
            f"画面停在「连接中」{LOADING_WORDS_SECONDS:.0f} 秒没有结束（可能网络或电脑比较慢）", str(second.exception)
        )

    def test_a_new_picture_ends_the_hold(self):
        watch = FrozenWatch()
        watch.hold_for_loading()
        watch.look(_screen(), 0.0)
        watch.look(_screen(30), 1.0)
        self.assertFalse(watch.loading_hold)

    def test_capture_frame_holds_only_for_loading_words(self):
        for words, held in (("NOW LOADING", True), ("公会商店", False)):
            task = object.__new__(base_module.BaseBD2Task)
            task.next_frame = lambda: _screen()
            task.info_set = lambda *_a: None
            task.log_info = lambda *_a, **_k: None
            task.ocr = lambda **_k: [SimpleNamespace(name=words)]
            task._frozen_watch = watch = FrozenWatch()
            watch.fired = True
            with mock.patch.object(
                base_module.BaseBD2Task, "capture_method_name", new_callable=mock.PropertyMock, return_value="x"
            ):
                if held:
                    base_module.BaseBD2Task.capture_frame(task)
                    self.assertTrue(watch.loading_hold)
                else:
                    with self.assertRaises(FrozenScreen):
                        base_module.BaseBD2Task.capture_frame(task)


class RunWatchedTest(unittest.TestCase):
    def _task(self, retry):
        task_type = type("Task", (), {"frozen_retry": retry})
        task = task_type()
        task.name = "测试"
        task.log_warning = mock.Mock()
        task.log_info = mock.Mock()
        return task

    def test_a_frozen_run_goes_home_and_runs_once_more(self):
        task = self._task(retry=True)
        results = iter([FrozenScreen(), True])
        seen_watches = []

        def run(t):
            seen_watches.append(t._frozen_watch)
            result = next(results)
            if isinstance(result, Exception):
                raise result
            return result

        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True) as home:
            self.assertTrue(base_module._run_watched(task, run, (), {}, watched=True))
        home.assert_called_once_with(task)
        self.assertEqual(2, len(seen_watches))
        self.assertIsNot(seen_watches[0], seen_watches[1])  # a fresh watch
        self.assertIsNone(task._frozen_watch)
        self.assertIn("回主页再试一次", task.log_warning.call_args.args[0])

    def test_frozen_twice_ends_as_failed_with_the_reason(self):
        task = self._task(retry=True)

        def run(_t):
            raise FrozenScreen()

        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True) as home:
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual(1, home.call_count)  # the second time 失败后继续 goes home
        self.assertIn("秒没有变化", task._why)

    def test_a_task_that_may_spend_is_not_run_again(self):
        task = self._task(retry=False)
        calls = []

        def run(_t):
            calls.append(1)
            raise FrozenScreen()

        with mock.patch("src.tasks.recovery.recover_to_home", return_value=True) as home:
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual(1, len(calls))
        home.assert_not_called()

    def test_a_task_own_stuck_reason_is_kept(self):
        task = self._task(retry=False)

        def run(_t):
            raise FrozenScreen("在活动页 20 秒没走到下一步")

        self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))
        self.assertEqual("在活动页 20 秒没走到下一步", task._why)

    def test_not_watched_runs_as_before(self):
        task = self._task(retry=True)
        self.assertEqual("ok", base_module._run_watched(task, lambda t: "ok", (), {}))
        self.assertFalse(hasattr(task, "_frozen_watch"))

    def test_safe_tasks_run_again_and_spending_ones_do_not(self):
        from src.tasks.CraftGearTask import CraftGearTask
        from src.tasks.EventBattleTask import EventBattleTask
        from src.tasks.GearTasks import DailyRefineTask
        from src.tasks.JunkGearTask import JunkGearTask
        from src.tasks.MapTradeTask import MapTradeTask
        from src.tasks.PVPTask import PVPTask

        # Leo 2026-11-05: the gear tasks and 跑商 run once more too (tiny cost).
        for cls in (EventBattleTask, PVPTask, DailyRefineTask, JunkGearTask, CraftGearTask,
                    MapTradeTask):
            self.assertTrue(cls.frozen_retry, cls.__name__)


class StuckStepAndEscapeTest(unittest.TestCase):
    """Leo 2026-10-14 「一直沒有識別到那就按esc 而且要跟用戶說明是哪裡卡住觸發了這個」."""

    def _task(self, step="点击快速切换按钮"):
        task = RunWatchedTest._task(self, retry=False)
        task._last_step = f"测试：{step}。"
        task.tap_escape = mock.Mock(return_value=True)
        return task

    def _run_frozen(self, task, on_home=False):
        def run(_t):
            raise FrozenScreen()

        with mock.patch("src.tasks.recovery.home_now", return_value=on_home):
            self.assertFalse(base_module._run_watched(task, run, (), {}, watched=True))

    def test_the_reason_names_the_step_and_esc_is_pressed(self):
        task = self._task()
        self._run_frozen(task)
        task.tap_escape.assert_called_once()
        self.assertTrue(task._why.startswith("卡在「点击快速切换按钮」："), task._why)
        self.assertIn(f"画面 {FROZEN_SCREEN_SECONDS:.0f} 秒没有变化", task._why)
        self.assertTrue(task._why.endswith("已按 Esc"), task._why)

    def test_the_stage_shown_to_the_player_comes_first(self):
        task = self._task()
        with mock.patch.object(base_module.problem_report, "_stage", return_value="选择广场卡带2号位"):
            self._run_frozen(task)
        self.assertTrue(task._why.startswith("卡在「选择广场卡带2号位」"), task._why)

    def test_no_esc_on_home_where_it_opens_the_quit_dialog(self):
        task = self._task()
        self._run_frozen(task, on_home=True)
        task.tap_escape.assert_not_called()
        self.assertNotIn("Esc", task._why)

    def test_the_limit_is_ten_seconds(self):
        self.assertEqual(10.0, FROZEN_SCREEN_SECONDS)


class WaitLimitsTest(unittest.TestCase):
    def test_saved_long_waits_are_capped(self):
        from src.utils.wait_limits import STUCK_SECONDS, capped

        self.assertEqual(STUCK_SECONDS, capped(35.0))
        self.assertEqual(6.0, capped("6"))
        self.assertEqual(8.0, capped(15, 8.0))
        self.assertEqual(STUCK_SECONDS, capped(None))

    def test_still_timer_counts_from_the_last_movement(self):
        from src.utils.wait_limits import StillTimer

        timer = StillTimer()
        still = np.full((80, 80, 3), 40, np.uint8)
        moved = np.full((80, 80, 3), 90, np.uint8)
        self.assertEqual(0.0, timer.still_for(still, 0.0))
        self.assertEqual(4.0, timer.still_for(still, 4.0))
        self.assertEqual(0.0, timer.still_for(moved, 5.0))
        sparkle = moved.copy()
        sparkle[:8, :8] = 255  # a small change is not movement
        self.assertEqual(6.0, timer.still_for(sparkle, 11.0))


class RecoveryRestsTheWatchTest(unittest.TestCase):
    def test_going_home_does_not_count_as_stuck(self):
        from src.tasks import recovery

        watch = FrozenWatch()
        task = SimpleNamespace(_frozen_watch=watch)
        seen = []

        def inner(t, attempts):
            seen.append(t._frozen_watch.paused)
            return True

        with mock.patch.object(recovery, "_recover_to_home", inner):
            self.assertTrue(recovery.recover_to_home(task))
        self.assertEqual([1], seen)
        self.assertEqual(0, watch.paused)


if __name__ == "__main__":
    unittest.main()


class ProgressWaitTest(unittest.TestCase):
    def test_loading_and_movement_do_not_count_a_still_screen_does(self):
        from src.utils.wait_limits import STUCK_SECONDS, ProgressWait, is_loading_dark

        black = np.full((80, 80, 3), 10, np.uint8)
        still = np.full((80, 80, 3), 120, np.uint8)
        self.assertTrue(is_loading_dark(black))
        self.assertFalse(is_loading_dark(still))
        self.assertFalse(is_loading_dark(np.zeros((80, 80, 3), np.uint8)))
        wait = ProgressWait(0.0)
        for t in range(0, 20):
            self.assertFalse(wait.over(black, float(t), loading=True))
        self.assertFalse(wait.over(still, 20.0))
        self.assertFalse(wait.over(still, 20.0 + STUCK_SECONDS - 1))
        self.assertTrue(wait.over(still, 20.0 + STUCK_SECONDS))

    def test_the_cap_ends_even_a_loading_wait(self):
        from src.utils.wait_limits import LOADING_MAX_SECONDS, ProgressWait

        wait = ProgressWait(0.0)
        black = np.full((80, 80, 3), 10, np.uint8)
        self.assertTrue(wait.over(black, LOADING_MAX_SECONDS, loading=True))


class ChangedByPressTest(unittest.TestCase):
    """Leo 2026-10-19 「記得我說的10秒是什麼狀況」「可以20秒」: 10 s is for a press
    that did nothing; a screen the press changed is loading, whatever it
    looks like (the 2K clone's bright 「FANTASIA SQUARE」 splash, cut at 10 s)."""

    PAGE = np.full((90, 160, 3), 60, np.uint8)
    SPLASH = np.full((90, 160, 3), 230, np.uint8)

    def test_a_still_screen_the_press_changed_waits_twenty_seconds(self):
        from src.utils.wait_limits import CHANGED_LOAD_SECONDS, STUCK_SECONDS, load_wait, scene

        wait = load_wait(0.0, STUCK_SECONDS, before=scene(self.PAGE))
        self.assertFalse(wait.over(self.SPLASH, 0.0))
        self.assertFalse(wait.over(self.SPLASH, STUCK_SECONDS + 3))
        self.assertFalse(wait.over(self.SPLASH, CHANGED_LOAD_SECONDS - 1))
        self.assertTrue(wait.over(self.SPLASH, CHANGED_LOAD_SECONDS))

    def test_a_press_that_changed_nothing_is_stuck_after_ten_seconds(self):
        from src.utils.wait_limits import STUCK_SECONDS, load_wait, scene

        for before in (scene(self.PAGE), None):
            wait = load_wait(0.0, STUCK_SECONDS, before=before)
            self.assertFalse(wait.over(self.PAGE, 0.0))
            self.assertFalse(wait.over(self.PAGE, STUCK_SECONDS - 1))
            self.assertTrue(wait.over(self.PAGE, STUCK_SECONDS))

    def test_the_frozen_watch_follows_the_same_rule(self):
        from src.utils.wait_limits import CHANGED_LOAD_SECONDS

        watch = FrozenWatch()
        watch.look(_screen(60), 0.0)
        watch.pressed()
        for t in range(1, int(CHANGED_LOAD_SECONDS)):
            watch.look(_screen(230), float(t))
        with self.assertRaises(FrozenScreen) as raised:
            watch.look(_screen(230), CHANGED_LOAD_SECONDS + 1)
        self.assertIn("画面换了", str(raised.exception))

        watch = FrozenWatch()
        watch.look(_screen(60), 0.0)
        watch.pressed()
        with self.assertRaises(FrozenScreen):
            for t in range(1, int(FROZEN_SCREEN_SECONDS) + 2):
                watch.look(_screen(60), float(t))

    def test_capture_and_press_keep_the_screen_before_the_press(self):
        from src.utils.wait_limits import scene, scene_at_press

        task = object.__new__(base_module.BaseBD2Task)
        frames = iter([self.PAGE, self.SPLASH])
        task.next_frame = lambda: next(frames)
        task.info_set = lambda *_a, **_k: None
        cls = base_module.BaseBD2Task
        with mock.patch.object(
            cls, "capture_method_name", new_callable=mock.PropertyMock, return_value="x"
        ), mock.patch.object(
            cls, "executor", new_callable=mock.PropertyMock, return_value=SimpleNamespace()
        ):
            task.capture_frame()
            task.operate(lambda: None)
            task.capture_frame()
        self.assertTrue(np.array_equal(scene(self.PAGE), scene_at_press(task)))


class PressedButStillTest(unittest.TestCase):
    """Leo 2026-11-05 「一直在按、但一直沒到下一個畫面也算卡住」."""

    def setUp(self):
        from src.utils.frozen_screen import PRESSED_STILL_SECONDS

        self.limit = PRESSED_STILL_SECONDS

    def test_pressing_at_a_screen_that_never_changes_is_stuck(self):
        watch = FrozenWatch()
        frame = _screen()
        now = 0.0
        with self.assertRaises(FrozenScreen) as fired:
            while now <= self.limit + 5:
                watch.look(frame, now)
                if int(now) % 5 == 4:
                    watch.pressed((10, 10))
                now += 1.0
        self.assertIn("点了", str(fired.exception))
        self.assertGreaterEqual(now, self.limit)

    def test_presses_that_change_the_screen_are_not_stuck(self):
        watch = FrozenWatch()
        for second in range(int(self.limit) * 3):
            frame = _screen(60 + (second // 5) * 3)  # each press moves to another picture
            watch.look(frame, float(second))
            if second % 5 == 4:
                watch.pressed((10, 10))

    def test_recognising_the_target_starts_over(self):
        watch = FrozenWatch()
        frame = _screen()
        for second in range(int(self.limit) * 2):
            watch.look(frame, float(second))
            if second % 5 == 4:
                watch.pressed((10, 10))
            if second % 20 == 19:
                watch.progress()  # the task read what it waited for

    def test_a_black_loading_screen_is_not_stuck_while_pressing(self):
        watch = FrozenWatch()
        black = np.full((1080, 1920, 3), 8, np.uint8)  # all-zero is a blank test frame
        for second in range(int(self.limit) + 5):
            watch.look(black, float(second))
            if second % 5 == 4:
                watch.pressed()

    def test_two_presses_are_not_enough(self):
        # Only the plain still rule fires (10 s after the last press).
        watch = FrozenWatch()
        frame = _screen()
        with self.assertRaises(FrozenScreen) as fired:
            for second in range(int(self.limit) + 5):
                watch.look(frame, float(second))
                if second in (3, 8):
                    watch.pressed((10, 10))
        self.assertNotIn("点了", str(fired.exception))


class LoadingRingTest(unittest.TestCase):
    """The ring's percent is read from its own crop (4K PC clone 2026-11-05)."""

    def test_ring_percent(self):
        from types import SimpleNamespace

        from src.utils.frozen_screen import ring_percent

        box = lambda text: SimpleNamespace(name=text)  # noqa: E731
        self.assertEqual("94%", ring_percent([box("94 %")]))
        self.assertEqual("100%", ring_percent([box("x"), box("100%")]))
        for text in ("4112%", "+112%", "94", "loading"):
            self.assertEqual("", ring_percent([box(text)]))

    def test_ring_crop_is_the_bottom_right_corner(self):
        from src.utils.frozen_screen import ring_crop

        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.assertEqual((140, 140), ring_crop(frame).shape[:2])
        frame4k = np.zeros((2160, 3840, 3), dtype=np.uint8)
        self.assertEqual((280, 280), ring_crop(frame4k).shape[:2])

    def test_the_stuck_check_reads_the_ring_when_the_whole_frame_misses_it(self):
        # A whole-frame OCR read no percent on 4 of 4 ring screens tried.
        from types import SimpleNamespace

        from src.tasks.BaseBD2Task import BaseBD2Task

        task = object.__new__(BaseBD2Task)
        calls = []

        def ocr(frame, name, reread):
            calls.append(frame.shape[:2])
            return [] if len(calls) == 1 else [SimpleNamespace(name="94%")]

        task.ocr = ocr
        frame = np.full((1080, 1920, 3), 180, dtype=np.uint8)
        self.assertEqual("94%", task._loading_words_on(frame))
        self.assertEqual([(1080, 1920), (140, 140)], calls)
