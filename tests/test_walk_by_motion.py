"""YES-BD2 #62: a walk whose 「自动移动中」 banner goes unread still counts.

The player's 问题摘要 (v0.2.18, 3840×2160 at 150%, 1080p window): after 跑商
the walk from the merchant to the goddess was under way (the field kept
panning), but the banner was never read, so the tool logged 「按了 E 也没开始走」,
pressed the daily row's usual spot and the character walked off there.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks import SquareGoddessTask as goddess_module
from src.tasks.map_trade.models import ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.SquareGoddessTask import SquareGoddessTask
from src.utils.wait_limits import MotionWatch

FIXTURE = Path(__file__).parent / "fixtures" / "square" / "square_field_nav_menu_2k.jpg"


def square():
    frame = cv2.imread(str(FIXTURE))
    assert frame is not None, FIXTURE
    return frame


def panning(frame, looks, step=12):
    """The field as a walk pans it: shifted a little more on every look."""
    return [np.roll(frame, step * look, axis=1) for look in range(looks)]


def idling(frame, looks):
    """The field standing still: a little pixel jitter and a blinking patch
    (sparkles, a character blinking)."""
    rng = np.random.default_rng(0)
    frames = []
    for look in range(looks):
        noisy = np.clip(frame.astype(int) + rng.integers(-3, 4, frame.shape), 0, 255)
        noisy = noisy.astype(np.uint8)
        if look % 2:
            noisy[600:800, 1200:1400] = 255 - noisy[600:800, 1200:1400]
        frames.append(noisy)
    return frames


class MotionWatchTest(unittest.TestCase):
    def test_a_panning_field_is_moving_after_two_changes(self):
        watch = MotionWatch()
        seen = [watch.moving(frame) for frame in panning(square(), 4)]
        self.assertEqual([False, False, True, True], seen)

    def test_an_idle_field_is_not_moving(self):
        watch = MotionWatch()
        self.assertFalse(any(watch.moving(frame) for frame in idling(square(), 8)))

    def test_a_stop_ends_it(self):
        frame = square()
        watch = MotionWatch()
        for picture in panning(frame, 3):
            watch.moving(picture)
        last = panning(frame, 3)[-1]
        self.assertFalse(watch.moving(last))

    def test_no_picture_is_no_motion(self):
        watch = MotionWatch()
        self.assertFalse(watch.moving(None))
        self.assertFalse(watch.moving(SimpleNamespace()))


def goddess_task(frames):
    task = object.__new__(SquareGoddessTask)
    task.config = {}
    task.info_set = lambda *_a, **_k: None
    task.logs = []
    task.log_info = lambda message, **_k: task.logs.append(message)
    task.sleep = lambda *_a: None
    task.keys, task.clicks = [], []
    task.tap_key = lambda key, after_sleep=0.0: task.keys.append(key) or True
    task._click_client = lambda x, y, *_a, **_k: task.clicks.append((x, y))
    shown = list(frames)
    task.capture_frame = lambda: shown.pop(0) if len(shown) > 1 else shown[0]
    # Neither the prayer prompt nor the walk banner is ever read.
    task._ocr_pattern_click_point = lambda *_a, **_k: (None, "")
    return task


class GoddessWalkTest(unittest.TestCase):
    def test_e_with_an_unread_banner_still_counts_as_walking(self):
        task = goddess_task(panning(square(), 6))
        self.assertTrue(task._walk_by_key())
        self.assertEqual(["E"], task.keys)
        self.assertTrue(any("画面一直在动" in line for line in task.logs))

    def test_e_on_a_still_field_is_still_not_a_walk(self):
        task = goddess_task(idling(square(), 4))
        with mock.patch.object(goddess_module, "GODDESS_ROW_PRESS_CONFIRM_SECONDS", 0.0):
            self.assertFalse(task._walk_by_key())

    def test_no_usual_spot_press_while_the_field_pans(self):
        task = goddess_task(panning(square(), 6))
        task._click_square_notice_if_present = lambda **_k: False
        task._click_goddess_daily_navigation_until = lambda **_k: None
        task._prayer_prompt_steady = lambda: False
        task._wished_today = lambda: False
        task._wait_for_goddess_prayer_completion = lambda **_k: True
        self.assertTrue(task._pray_at_goddess())
        self.assertEqual([], task.clicks)

    def test_the_wait_presses_nothing_while_the_unread_walk_goes_on(self):
        frame = square()
        walk = panning(frame, 30)
        # 30 looks of walking (longer than the 10 s stuck limit), then the
        # character stands still.
        task = goddess_task(walk + [walk[-1]])
        looks = [0]
        capture = task.capture_frame
        task.capture_frame = lambda: looks.__setitem__(0, looks[0] + 1) or capture()
        presses = []
        task.tap_key = lambda key, after_sleep=0.0: presses.append(looks[0]) or True
        task._click_client = lambda *_a, **_k: presses.append(looks[0])
        task._observe_goddess_navigation = lambda _f: SimpleNamespace(
            navigation=SimpleNamespace(center=(1680, 314))
        )
        task._wait_for_daily_navigation_to_disappear = lambda **_k: False
        stops = []
        # Only the overall limit's clean-up at the very end may stop the walk.
        task._cancel_goddess_walk = lambda: stops.append(looks[0]) or True
        clock = iter(range(0, 100000))
        with mock.patch.object(goddess_module, "monotonic", side_effect=lambda: next(clock)):
            task._wait_for_goddess_prayer_completion(timeout=200)
        self.assertGreater(looks[0], len(walk))
        self.assertTrue(all(look > len(walk) for look in presses + stops), (presses, stops))


class FieldWalkTest(unittest.TestCase):
    """跑图 walks wait on the same banner (navigator_sandbox)."""

    def _navigator(self, frames):
        shown = list(frames)
        vision = SimpleNamespace(
            capture=lambda: shown.pop(0) if len(shown) > 1 else shown[0],
            # The banner is never read.
            ocr_text=lambda *_a, **_k: "",
            simplify=lambda text: text,
        )
        task = SimpleNamespace(sleep=lambda *_a: None, config={})
        navigator = Navigator(task, vision)
        navigator._status = lambda *_a: None
        navigator.classify = lambda _frame: ScreenState.SANDBOX
        return navigator, shown

    def test_an_unread_banner_over_a_panning_field_is_still_the_walk(self):
        frame = square()
        walk = panning(frame, 12)
        navigator, shown = self._navigator(walk + [walk[-1]])
        self.assertEqual("done", navigator._wait_auto_move_finished(45.0))
        # Over only once the field stood still, not after two quiet reads.
        self.assertEqual(1, len(shown))

    def test_the_games_arrival_word_ends_the_wait_at_once(self):
        frame = square()
        navigator, shown = self._navigator(panning(frame, 8))
        reads = iter(["自动移动中：魔法阵", "已完成自动移动"])
        navigator._walk_text = lambda _frame: next(reads, "")
        self.assertEqual("done", navigator._wait_auto_move_finished(45.0))
        # Over on the second look though the picture still pans.
        self.assertEqual(6, len(shown))

    def test_followers_settling_after_arrival_do_not_hold_the_wait(self):
        # Live 4K clone 2026-10-27: after arriving the picture still changed
        # by about 3 a look (followers walking up, the camera settling), and
        # the wait went on 21 s more.
        frame = square()
        settling = [
            np.clip(frame.astype(int) + (4 if look % 2 else 0), 0, 255).astype(np.uint8)
            for look in range(8)
        ]
        navigator, shown = self._navigator(settling)
        self.assertEqual("done", navigator._wait_auto_move_finished(45.0))
        self.assertGreater(len(shown), 4)

    def test_a_still_field_without_the_banner_is_over_at_once(self):
        navigator, shown = self._navigator(idling(square(), 6))
        self.assertEqual("done", navigator._wait_auto_move_finished(45.0))
        self.assertGreater(len(shown), 2)


class SearchBattleTest(unittest.TestCase):
    """YES-BD2 #61: a monster that touches the character while 探查 is
    pressed is run from and the map done again, as after the other presses
    (it used to skip the whole card)."""

    def test_battle_during_search_runs_away_and_redoes_the_map(self):
        import tempfile
        from datetime import datetime

        from src.tasks.map_trade.card_status import (
            CollectionCardSelectionOutcome,
            CollectionCardSelectionResult,
        )
        from src.tasks.map_trade.collector import Collector
        from src.tasks.map_trade.collector_constants import (
            BATTLE_ACTIONS,
            SearchCountdownSession,
            SkillExecutionResult,
        )
        from src.tasks.map_trade.models import NavigationResult, ScreenState
        from src.tasks.map_trade.progress import UTC_PLUS_8, ProgressStore
        from tests.helpers.map_trade import _seed_action_records

        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.state.daily_submaps = 18
            progress.state.daily_summons = 12
            progress.state.daily_suppressions = 12
            progress.state.game_counts["吸收"] = (18, 21)
            progress.save()
            events = []
            absorbed = [18]
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                log_warning=lambda *_a: None,
                info_set=lambda *_a: None,
                leave_field_battle=lambda label: events.append(("leave",)) or "left",
            )
            navigator = SimpleNamespace(
                select_collection_card=lambda card_id, **_k: (
                    events.append(("select", card_id))
                    or CollectionCardSelectionResult(
                        CollectionCardSelectionOutcome.ENTERED,
                        NavigationResult(True, ScreenState.SANDBOX),
                    )
                ),
                current_collection_target=lambda _card: None,
                prepare_collection_main_area=lambda card_id, **_k: NavigationResult(
                    True, ScreenState.SANDBOX
                ),
                advance_collection_map=lambda card_id, current, target: (
                    events.append(("advance", target.key))
                    or NavigationResult(True, ScreenState.SANDBOX)
                ),
                open_story_quick_switcher_from_sandbox=lambda **_k: NavigationResult(
                    True, ScreenState.CARD_MENU
                ),
                inspect_collection_card_completion=lambda card_id: CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                    NavigationResult(True, ScreenState.CARD_MENU),
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            started = SearchCountdownSession((0.1, 0.2, 0.3, 0.4), 87)
            # The second map's first 探查 is cut by a battle.
            searches = iter(
                [started, SkillExecutionResult(False, message="未确认倒计时"), started, started]
            )
            collector._absorb_used_up = lambda **_k: None
            collector._ensure_search = lambda **_k: events.append(("search",)) or next(searches)
            collector._verify_search_countdown = lambda _value: True

            def use_actions(actions, *, card_id, map_role):
                events.append(("actions", len(actions)))
                _seed_action_records(progress, card_id, map_role.value)
                absorbed[0] += 1
                progress.reconcile_pending("吸收", (absorbed[0], 21))
                return SkillExecutionResult(True, absorbed[0] >= 21)

            collector._use_actions = use_actions
            result = collector.run()

        self.assertTrue(result.success, result.message)
        self.assertEqual(3, result.completed_submaps)
        self.assertEqual(
            [
                ("select", "Q_sp1"),
                ("search",),
                ("actions", 1),
                ("advance", "battle_area_1"),
                ("search",),
                ("leave",),
                ("search",),
                # 压制 first after running away.
                ("actions", len(BATTLE_ACTIONS)),
                ("advance", "battle_area_2"),
                ("search",),
                ("actions", len(BATTLE_ACTIONS)),
            ],
            events,
        )


if __name__ == "__main__":
    unittest.main()
