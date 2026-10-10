"""跑图 puts the player's skill group back after its group search switched it
(Leo's rule: the tool puts back what it switched; never picks a group for the
player).  The search itself is unchanged."""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from ok.task.exceptions import TaskDisabledException

from src.tasks.map_trade.action_icons import SEARCH_ICON, ActionIconDetection, ActionIconState
from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.collector_constants import SKILL_GROUP_RELATIVE_POINTS
from src.tasks.map_trade.models import CollectionResult, MatchResult
from src.tasks.map_trade.skill_group_keeper import SkillGroupKeeper

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade" / "skill_groups"


def _frame(name):
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[810:1080, 1440:1920] = cv2.imread(str(FIXTURES / f"{name}_br.png"))
    return frame


class _Game:
    """The selected group (None = off the field); a group click selects it."""

    def __init__(self, group):
        self.group = group
        self.clicks = []
        self.logs = []

    def capture(self):
        return _frame(f"group{self.group}") if self.group else _frame("bigmap")

    def operate_click(self, x, y, after_sleep=0.0):
        self.clicks.append((x, y))
        for group, point in SKILL_GROUP_RELATIVE_POINTS.items():
            if (x, y) == point and self.group:
                self.group = group

    def sleep(self, _seconds):
        pass

    def log_info(self, message, **_kwargs):
        self.logs.append(("info", message))

    def log_warning(self, message, **_kwargs):
        self.logs.append(("warning", message))

    def log_error(self, message, *_args, **_kwargs):
        self.logs.append(("error", message))


def _keeper(group):
    game = _Game(group)
    return game, SkillGroupKeeper(game, SimpleNamespace(capture=game.capture), "地图采集")


class KeeperTest(unittest.TestCase):
    def test_nothing_switched_means_nothing_pressed(self):
        game, keeper = _keeper(3)
        keeper.restore(final=True)
        self.assertEqual([], game.clicks)
        self.assertEqual([], game.logs)

    def test_the_group_before_the_search_is_put_back(self):
        game, keeper = _keeper(1)
        keeper.before_switch()
        game.operate_click(*SKILL_GROUP_RELATIVE_POINTS[2])
        keeper.before_switch()  # a second search keeps the first start group
        keeper.restore()
        self.assertEqual(1, game.group)
        self.assertIn(("info", "地图采集：技能组从第2组切回原本的第1组。"), game.logs)
        self.assertFalse(keeper.switched)

    def test_already_on_the_players_group_presses_nothing(self):
        game, keeper = _keeper(2)
        keeper.before_switch()
        keeper.restore()
        self.assertEqual([], game.clicks)

    def test_off_the_field_it_waits_then_gives_up_at_the_end(self):
        game, keeper = _keeper(1)
        keeper.before_switch()
        game.operate_click(*SKILL_GROUP_RELATIVE_POINTS[2])
        game.clicks.clear()
        game.group = None  # quick-switch page, home...
        keeper.restore()
        self.assertTrue(keeper.switched)
        self.assertEqual([], game.logs)
        keeper.restore(final=True)
        self.assertEqual([], game.clicks)
        self.assertIn("原本是第1组", game.logs[-1][1])
        self.assertFalse(keeper.switched)

    def test_an_unreadable_start_group_is_not_guessed(self):
        game, keeper = _keeper(None)
        keeper.before_switch()
        game.group = 2
        keeper.restore()
        self.assertEqual([], game.clicks)
        self.assertIn("没认出原本是第几组", game.logs[-1][1])

    def test_a_stop_presses_nothing(self):
        game, keeper = _keeper(1)
        keeper.before_switch()
        game.operate_click(*SKILL_GROUP_RELATIVE_POINTS[3])
        game.clicks.clear()
        keeper.restore(stopped=True)
        self.assertEqual([], game.clicks)
        self.assertIn("原本是第1组", game.logs[-1][1])


def _collector(group, skills_in=2):
    game = _Game(group)
    collector = object.__new__(Collector)
    collector.task = game
    collector.vision = SimpleNamespace(capture=game.capture)
    collector._status = lambda *_a: None
    collector._counts_prove_menu = lambda _icons: False
    absent = ActionIconDetection(ActionIconState.ABSENT, MatchResult(-1.0, (0, 0), (0, 0)))
    shown = ActionIconDetection(ActionIconState.AVAILABLE, MatchResult(0.99, (0, 0), (0, 0)))
    collector.action_icons = SimpleNamespace(
        detect=lambda _frame, _icon: shown if game.group == skills_in else absent
    )
    collector.skill_group_keeper = SkillGroupKeeper(game, collector.vision, "地图采集")
    return game, collector


class CollectorTest(unittest.TestCase):
    def test_the_search_remembers_the_start_group(self):
        game, collector = _collector(1)
        self.assertTrue(collector._open_skill_menu((SEARCH_ICON,), allow_group_one_recovery=True))
        self.assertEqual(2, game.group)
        self.assertEqual(1, collector.skill_group_keeper.before)

    def test_a_shown_skill_bar_switches_nothing(self):
        game, collector = _collector(2)
        self.assertTrue(collector._open_skill_menu((SEARCH_ICON,), allow_group_one_recovery=True))
        self.assertEqual([], game.clicks)
        self.assertFalse(collector.skill_group_keeper.switched)

    def _run(self, collector, body):
        collector._run_collection = body
        collector._with_skipped_cards = lambda result: result
        return Collector.run(collector)

    def test_a_failed_run_puts_the_group_back(self):
        game, collector = _collector(1)

        def body():
            collector._open_skill_menu((SEARCH_ICON,), allow_group_one_recovery=True)
            return CollectionResult(False, message="测试失败")

        self._run(collector, body)
        self.assertEqual(1, game.group)

    def test_a_stopped_run_presses_nothing_more(self):
        game, collector = _collector(1)

        def body():
            collector._open_skill_menu((SEARCH_ICON,), allow_group_one_recovery=True)
            game.clicks.clear()
            raise TaskDisabledException()

        with self.assertRaises(TaskDisabledException):
            self._run(collector, body)
        self.assertEqual([], game.clicks)
        self.assertEqual(2, game.group)
        self.assertIn("停止时技能组可能还在", game.logs[-1][1])


if __name__ == "__main__":
    unittest.main()
