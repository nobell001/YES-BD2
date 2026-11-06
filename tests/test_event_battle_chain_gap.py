"""活动每日战斗: the gap between two battles of the game's own chain.

Player v0.2.31, 2026-11-05 (1080p window, HDR on): after 第3次／共5次 the
camera panned, VICTORY showed and the screen faded for longer than 8 s plus
the blank tap; the run failed with 「打完后停在认不出的画面」 while the game
was already fighting 第4次／共5次.  Once a battle was seen, VICTORY, the
loading screen or a moving picture is the game working, up to
LOADING_MAX_SECONDS after the last battle frame, also after the chain's last
battle; a still unknown screen is still caught after UNKNOWN_END_SECONDS.
"""

import unittest
from unittest import mock

from src.tasks import EventBattleTask as event_module
from src.tasks.EventBattleTask import CHALLENGE_MODE, DEFEAT_BLANK_POINT
from tests.test_event_battle_defeat import BATTLE, ScreenTask, box

BATTLE_4 = {"progress": ["自动战斗进行中：第4次／共5次"], "buttons": ["结束自动战斗"]}
LAST_BATTLE = {"progress": ["自动战斗进行中：第5次／共5次"], "buttons": ["结束自动战斗"]}
VICTORY = {"full": ["VICTORY", "覆灭敌人"]}
GAP = {}  # panning field, fade: no text read at all
RESULT = {"buttons": ["返回"]}


class _Moving:
    """A StillTimer whose picture keeps changing (or stands still)."""

    def __init__(self, moving=True):
        self.moving = moving

    def reset(self):
        pass

    def still_for(self, frame, now):
        return 0.0 if self.moving else 999.0


def _watch(frames, moving=True, step=1.0):
    now = [0.0]

    def clock():
        now[0] += step
        return now[0]

    task = ScreenTask([BATTLE]).task
    frames = iter(frames)
    task.capture_frame = lambda: next(frames)
    inner = task._roi_boxes
    task._roi_boxes = lambda frame, roi, name: (
        [box(t) for t in frame.get("full", [])] if roi is None else inner(frame, roi, name)
    )
    task._wait_for_stage_page = lambda mode, timeout=0, quiet=False: False
    task._click_box = lambda target, after_sleep=0: task.clicks.append(target.name)
    task.tap_escape = lambda after_sleep=0: (_ for _ in ()).throw(AssertionError("pressed Esc"))
    task._leave_result_screen = lambda: True
    with mock.patch.object(event_module, "monotonic", side_effect=clock), mock.patch.object(
        event_module, "StillTimer", lambda: _Moving(moving), create=True
    ):
        result = task._watch_auto_battle(5, CHALLENGE_MODE)
    task.elapsed = now[0]
    return task, result


class ChainGapTest(unittest.TestCase):
    def test_player_gap_pan_victory_fade_then_battle_4(self):
        # The player's frames: pan, VICTORY, fade (~16 s), then 第4次.
        frames = [BATTLE] + [GAP] * 3 + [VICTORY] * 4 + [GAP] * 4 + [BATTLE_4] + [RESULT] * 2
        task, result = _watch(frames)
        self.assertGreater(task.elapsed, 16.0)  # longer than the old 8 s + tap + 8 s
        self.assertEqual(5, result)
        self.assertEqual("", task._why)
        self.assertEqual([], task.clicks)  # no blank tap during the gap

    def test_victory_alone_keeps_watching_even_when_still(self):
        frames = [BATTLE] + [VICTORY] * 8 + [BATTLE_4] + [RESULT] * 2
        task, result = _watch(frames, moving=False)
        self.assertEqual(5, result)
        self.assertEqual([], task.clicks)

    def test_still_unknown_screen_between_battles_is_still_caught(self):
        task, result = _watch([BATTLE] + [GAP] * 60, moving=False)
        self.assertIsNone(result)
        self.assertEqual([DEFEAT_BLANK_POINT], task.clicks)
        self.assertIn("认不出的画面", task._why)

    def test_a_gap_that_keeps_moving_ends_at_the_loading_cap(self):
        task, result = _watch([BATTLE] + [GAP] * 200, moving=True)
        self.assertIsNone(result)
        self.assertEqual([DEFEAT_BLANK_POINT], task.clicks)
        self.assertIn("认不出的画面", task._why)

    def test_slow_pan_and_mvp_after_the_last_battle_reach_the_result(self):
        # Replay of the real chain 8x slower: 第5次 ends, ~24 s of pan and MVP
        # screen without text, then VICTORY with 返回.
        frames = [LAST_BATTLE] + [GAP] * 8 + [VICTORY] * 2 + [RESULT] * 2
        task, result = _watch(frames)
        self.assertGreater(task.elapsed, 16.0)  # longer than 8 s + tap + 8 s
        self.assertEqual(5, result)
        self.assertEqual("", task._why)
        self.assertEqual([], task.clicks)

    def test_still_unknown_screen_after_the_last_battle_is_still_caught(self):
        task, result = _watch([LAST_BATTLE] + [GAP] * 60, moving=False)
        self.assertIsNone(result)
        self.assertEqual([DEFEAT_BLANK_POINT], task.clicks)
        self.assertIn("认不出的画面", task._why)

    def test_a_moving_screen_after_the_last_battle_ends_at_the_loading_cap(self):
        task, result = _watch([LAST_BATTLE] + [GAP] * 200, moving=True)
        self.assertIsNone(result)
        self.assertEqual([DEFEAT_BLANK_POINT], task.clicks)


if __name__ == "__main__":
    unittest.main()
