"""「查看战场奖励」 is turned on before reading card badges.

Player v0.2.31 2560x1440 (2026-11-05): the switch at the quick bar's right
end was off, the cards showed no 吸取/压制 badges, and 活动卡3/7 could never be
confirmed done.  Leo: 「工具要把她打開 也要提示用戶打開」.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import cv2

from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_story import (
    BATTLE_REWARDS_STILL_OFF_MESSAGE,
    BATTLE_REWARDS_TURNED_ON_MESSAGE,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "quick_switch"
# The player's last frame, cut out of the 问题摘要 picture (small).
OFF = cv2.imread(str(FIXTURES / "battle_rewards_off_player_summary_472x266.png"))
ON = cv2.imread(str(FIXTURES / "event_bar_card1_playing_fhd.png"))


class _Vision:
    def __init__(self, frames):
        self.frames = frames

    def capture(self):
        return self.frames[0]


class _Task:
    def __init__(self, vision, turns_on=True):
        self.vision = vision
        self.turns_on = turns_on
        self.clicks = []
        self.infos = []
        self.warnings = []

    def operate_click(self, x, y, after_sleep=0.0):
        self.clicks.append((x, y))
        if self.turns_on:
            self.vision.frames[0] = ON

    def log_info(self, text):
        self.infos.append(text)

    def sleep(self, _seconds):
        pass

    def log_warning(self, text):
        self.warnings.append(text)


def _navigator(frame, turns_on=True):
    navigator = object.__new__(Navigator)
    navigator.vision = _Vision([frame])
    navigator.task = _Task(navigator.vision, turns_on)
    navigator._status = lambda *_a: None
    return navigator


class BattleRewardsSwitchTest(unittest.TestCase):
    def test_real_frames_read(self):
        self.assertEqual("off", _navigator(OFF)._battle_rewards_switch())
        self.assertEqual("on", _navigator(ON)._battle_rewards_switch())

    def test_off_is_turned_on_and_player_told(self):
        navigator = _navigator(OFF)
        navigator._ensure_battle_rewards_shown()
        self.assertEqual(1, len(navigator.task.clicks))
        x, y = navigator.task.clicks[0]
        self.assertAlmostEqual(1760 / 1920, x, places=3)
        self.assertAlmostEqual(877 / 1080, y, places=3)
        self.assertEqual(BATTLE_REWARDS_TURNED_ON_MESSAGE, navigator.task.infos[-1])
        # Once on, later cards do not look again.
        navigator._ensure_battle_rewards_shown()
        self.assertEqual(1, len(navigator.task.clicks))

    def test_on_is_left_alone(self):
        navigator = _navigator(ON)
        navigator._ensure_battle_rewards_shown()
        self.assertEqual([], navigator.task.clicks)
        self.assertEqual([], navigator.task.infos)

    def test_press_ignored_twice_tells_player_how(self):
        navigator = _navigator(OFF, turns_on=False)
        navigator._ensure_battle_rewards_shown()
        self.assertEqual(2, len(navigator.task.clicks))
        self.assertEqual([BATTLE_REWARDS_STILL_OFF_MESSAGE], navigator.task.warnings)
        self.assertTrue(navigator._battle_rewards_still_off)

    def test_other_pages_are_never_pressed(self):
        home = cv2.imread(str(FIXTURES / "home_bottom_strip_1600x901.png"))
        navigator = _navigator(home)
        navigator._ensure_battle_rewards_shown()
        self.assertEqual([], navigator.task.clicks)


if __name__ == "__main__":
    unittest.main()
