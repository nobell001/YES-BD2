"""A card that cannot be entered or travelled is skipped, not the whole run
(audit 2026-10-10 #1/#7, the plan's default for decision 6; the last
part of #2)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.tasks.map_trade.card_status import (
    CollectionCardSelectionOutcome,
    CollectionCardSelectionResult,
)
from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.collector_constants import SkillExecutionResult
from src.tasks.map_trade.models import (
    CARD_BY_ID,
    CollectionMapRole,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.progress import UTC_PLUS_8, ProgressStore
from tests.helpers.map_trade import _seed_action_records

ENTERED = CollectionCardSelectionResult(
    CollectionCardSelectionOutcome.ENTERED, NavigationResult(True, ScreenState.SANDBOX)
)
NOT_FOUND = CollectionCardSelectionResult(
    CollectionCardSelectionOutcome.FAILED,
    NavigationResult(False, ScreenState.CARD_MENU, "未唯一确认剧情游戏卡5角标"),
)


class SkipBrokenCardTest(unittest.TestCase):
    def _run(self, card_ids, *, select=None, advance=None, use_actions=None, home_ok=True):
        events = []
        warnings = []
        home = (
            NavigationResult(True, ScreenState.HOME)
            if home_ok
            else NavigationResult(False, ScreenState.UNKNOWN, "没有安全返回路径")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 10, 10, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            task = SimpleNamespace(
                config={"卡带单步重试次数": 2},
                log_warning=lambda message, *_a, **_k: warnings.append(message),
                info_set=lambda *_args: None,
            )

            def default_select(card_id, *, enter_visually_complete):
                events.append(("select", card_id))
                return ENTERED

            def default_advance(card_id, current, target):
                events.append(("go", card_id, target.key))
                return NavigationResult(True, ScreenState.SANDBOX)

            def default_use_actions(actions, *, card_id, map_role):
                events.append(("collect", card_id, map_role.value))
                _seed_action_records(progress, card_id, map_role.value)
                return SkillExecutionResult(True)

            navigator = SimpleNamespace(
                select_collection_card=select or default_select,
                current_collection_target=lambda _card: None,
                prepare_collection_main_area=lambda card_id, **_kwargs: NavigationResult(
                    True, ScreenState.SANDBOX
                ),
                advance_collection_map=advance or default_advance,
                open_story_quick_switcher_from_sandbox=lambda **_kwargs: NavigationResult(
                    True, ScreenState.CARD_MENU
                ),
                inspect_collection_card_completion=lambda card_id: CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                    NavigationResult(True, ScreenState.CARD_MENU),
                ),
                return_home=lambda: events.append(("home",)) or home,
            )
            collector = Collector(task, object(), navigator, progress)
            collector._absorb_used_up = lambda **_kwargs: None
            collector._ensure_search = lambda **_kwargs: None
            collector._use_actions = (
                (lambda actions, **kwargs: use_actions(progress, events, actions, **kwargs))
                if use_actions
                else default_use_actions
            )
            cards = tuple(CARD_BY_ID[card_id] for card_id in card_ids)
            with patch("src.tasks.map_trade.collector.COLLECTABLE_CARDS", cards):
                result = collector.run()
            state = progress.state
        return result, events, warnings, state

    def test_a_missing_card_is_skipped_and_the_next_one_still_runs(self):
        # A player without 活动卡5 stopped there every day; 活动卡7 never ran.
        def select(card_id, *, enter_visually_complete):
            return NOT_FOUND if card_id == "Q_ep5" else ENTERED

        result, events, warnings, state = self._run(("Q_ep5", "Q_ep7"), select=select)

        self.assertIn(("home",), events)
        self.assertIn(("collect", "Q_ep7", "main_area"), events)
        self.assertIn(("collect", "Q_ep7", "battle_area_1"), events)
        self.assertTrue(state.card_verified("Q_ep7"))
        # Not done and not green; nothing recorded for the missing card.
        self.assertFalse(result.success)
        self.assertEqual(set(), state.completed_targets("Q_ep5"))
        self.assertFalse(state.card_verified("Q_ep5"))
        self.assertFalse(state.weekly_collection_complete)
        self.assertTrue(result.message.startswith("活动卡5这次跳过，没有完成"))
        self.assertIn("「跑图章节」取消勾选", result.message)
        self.assertTrue(any("活动卡5进不去" in line for line in warnings))

    def test_every_missing_card_is_named_once(self):
        result, _events, _warnings, _state = self._run(
            ("Q_sp1", "Q_sp2"), select=lambda card_id, **_k: NOT_FOUND
        )
        self.assertFalse(result.success)
        self.assertTrue(result.message.startswith("第1章、第2章这次跳过"))

    def test_a_route_that_breaks_twice_skips_the_card(self):
        def advance(card_id, current, target):
            ok = card_id != "Q_sp1" or target.key != "battle_area_2"
            return NavigationResult(ok, ScreenState.SANDBOX, "" if ok else "走不过去")

        result, events, _warnings, state = self._run(("Q_sp1", "Q_sp2"), advance=advance)

        self.assertFalse(result.success)
        self.assertIn("第1章", result.message)
        # The maps really done stay recorded; the card is not finished.
        self.assertEqual({"main_area", "battle_area_1"}, state.completed_targets("Q_sp1"))
        self.assertFalse(state.card_verified("Q_sp1"))
        self.assertIn(("home",), events)
        self.assertTrue(state.card_verified("Q_sp2"))

    def test_no_known_screen_after_a_skip_stops_the_run(self):
        result, events, _warnings, _state = self._run(
            ("Q_sp1", "Q_sp2"),
            select=lambda card_id, **_k: NOT_FOUND,
            home_ok=False,
        )
        self.assertFalse(result.success)
        self.assertIn("回不到主页", result.message)
        self.assertNotIn(("collect", "Q_sp2", "main_area"), events)
        self.assertEqual(1, events.count(("home",)))

    def test_a_card_skipped_on_a_full_day_is_still_not_done(self):
        # The day's 吸收 runs out on the next card: the run says so, but the
        # skipped card keeps it from reading as complete.
        def select(card_id, *, enter_visually_complete):
            return NOT_FOUND if card_id == "Q_sp1" else ENTERED

        def use_actions(progress, events, actions, *, card_id, map_role):
            _seed_action_records(progress, card_id, map_role.value)
            return SkillExecutionResult(True, depleted=True)

        result, _events, _warnings, _state = self._run(
            ("Q_sp1", "Q_sp2"), select=select, use_actions=use_actions
        )
        self.assertTrue(result.depleted)
        self.assertFalse(result.success)
        self.assertTrue(result.message.startswith("第1章这次跳过"))

    def test_a_map_left_undecided_today_skips_only_that_card(self):
        # Audit #2: on bright ground an unconfirmed press blocked the map and
        # stopped the run on every retry until 08:00.
        def use_actions(progress, events, actions, *, card_id, map_role):
            events.append(("collect", card_id, map_role.value))
            if card_id == "Q_sp1" and map_role is CollectionMapRole.BATTLE_AREA_1:
                progress.arm_action(card_id, map_role, "召集")
                progress.mark_action_blocked(card_id, map_role, "召集", "上次点击意图未决")
                return SkillExecutionResult(False, message="召集上次点击意图未决，禁止重复点击")
            _seed_action_records(progress, card_id, map_role.value)
            return SkillExecutionResult(True)

        result, events, _warnings, state = self._run(("Q_sp1", "Q_sp2"), use_actions=use_actions)

        self.assertFalse(result.success)
        self.assertIn("第1章", result.message)
        self.assertNotIn(("collect", "Q_sp1", "battle_area_2"), events)
        self.assertEqual({"main_area"}, state.completed_targets("Q_sp1"))
        self.assertTrue(state.card_verified("Q_sp2"))

    def test_other_skill_failures_still_stop_the_run(self):
        # Unsure on a map with nothing pending: stop, as before.
        def use_actions(progress, events, actions, *, card_id, map_role):
            events.append(("collect", card_id, map_role.value))
            return SkillExecutionResult(False, message="未确认采集技能栏")

        result, events, _warnings, _state = self._run(("Q_sp1", "Q_sp2"), use_actions=use_actions)

        self.assertFalse(result.success)
        self.assertIn("技能操作失败", result.message)
        self.assertNotIn("Q_sp2", [event[1] for event in events if len(event) > 1])


if __name__ == "__main__":
    unittest.main()
