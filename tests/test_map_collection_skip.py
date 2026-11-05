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
    def _run(
        self,
        card_ids,
        *,
        select=None,
        advance=None,
        use_actions=None,
        home_ok=True,
        recovered=None,
        unfinished=(),
        reopen=None,
    ):
        events = []
        warnings = []
        self.infos = []
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
                info_set=lambda *args: self.infos.append(args),
            )
            if recovered is not None:
                # A real task: the general way home is tried after a skip.
                task.capture_frame = lambda: None

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
                open_story_quick_switcher_from_sandbox=reopen
                or (lambda **_kwargs: NavigationResult(True, ScreenState.CARD_MENU)),
                inspect_collection_card_completion=lambda card_id: (
                    NavigationResult(False, ScreenState.CARD_MENU, "未同时确认吸取与压制完成")
                    if card_id in unfinished
                    else CollectionCardSelectionResult(
                        CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                        NavigationResult(True, ScreenState.CARD_MENU),
                    )
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
            recover = lambda _task: events.append(("recover",)) or bool(recovered)  # noqa: E731
            with (
                patch("src.tasks.map_trade.collector.COLLECTABLE_CARDS", cards),
                patch("src.tasks.recovery.recover_to_home", recover),
            ):
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
        # Leo 2026-10-20: no 「取消勾选」 hint in the skip message.
        self.assertNotIn("取消勾选", result.message)
        self.assertTrue(any("活动卡5进不去" in line for line in warnings))
        # The summary says why (player report 2026-10-17 said only 「这次跳过」).
        self.assertIn("（原因：活动卡5进不去", result.message)
        # 「停在」 names the skip, not the next card's step.
        stage = [value for key, value in self.infos if key == "当前阶段"][-1]
        self.assertEqual("地图采集：活动卡5跳过，没有完成", stage)

    def test_every_missing_card_is_named_once(self):
        result, _events, _warnings, _state = self._run(
            ("Q_sp1", "Q_sp2"), select=lambda card_id, **_k: NOT_FOUND
        )
        self.assertFalse(result.success)
        self.assertTrue(result.message.startswith("第1章、第2章这次跳过"))

    def test_cards_skipped_for_one_reason_share_it(self):
        # Player 2026-10-19: nine chapters skipped; the report cut off the
        # reasons after 第3章, so 第5–11章's were never seen.
        result, _events, _warnings, _state = self._run(
            ("Q_sp2", "Q_sp3", "Q_sp5", "Q_sp6", "Q_sp7"),
            select=lambda card_id, **_k: NOT_FOUND,
        )
        self.assertTrue(result.message.startswith("第2章、第3章、第5章至第7章这次跳过"))
        self.assertIn("（原因：第2章、第3章、第5章至第7章都进不去", result.message)
        self.assertEqual(1, result.message.count("进不去"))
        stage = [value for key, value in self.infos if key == "当前阶段"][-1]
        self.assertEqual("地图采集：第2章、第3章、第5章至第7章跳过，没有完成", stage)

    def test_a_route_that_breaks_twice_skips_the_card(self):
        def advance(card_id, current, target):
            ok = card_id != "Q_sp1" or target.key != "battle_area_2"
            return NavigationResult(ok, ScreenState.SANDBOX, "" if ok else "走不过去")

        result, events, _warnings, state = self._run(("Q_sp1", "Q_sp2"), advance=advance)

        self.assertFalse(result.success)
        self.assertIn("第1章", result.message)
        self.assertIn("走不过去", result.message)
        # The maps really done stay recorded; the card is not finished.
        self.assertEqual({"main_area", "battle_area_1"}, state.completed_targets("Q_sp1"))
        self.assertFalse(state.card_verified("Q_sp1"))
        self.assertIn(("home",), events)
        self.assertTrue(state.card_verified("Q_sp2"))

    def test_quick_switch_not_opened_after_the_card_skips_only_that_card(self):
        # Player v0.2.31 2026-11-05 (噩梦之冬): a patrol caught the character
        # right after the last map; 「Q_ep2完成后无法打开快速切换页：未稳定确认
        # 当前剧情卡带箱庭」 stopped the whole run.
        reopened = []

        def reopen(**_kwargs):
            reopened.append(len(reopened))
            if len(reopened) == 1:
                return NavigationResult(False, ScreenState.UNKNOWN, "未稳定确认当前剧情卡带箱庭")
            return NavigationResult(True, ScreenState.CARD_MENU)

        result, events, warnings, state = self._run(("Q_ep2", "Q_ep7"), reopen=reopen)

        self.assertNotIn("无法打开快速切换页", result.message)
        self.assertIn(("home",), events)
        # The next card still runs; the caught card's maps stay recorded and
        # it is judged again after the others.
        self.assertTrue(state.card_verified("Q_ep7"))
        self.assertTrue(state.card_verified("Q_ep2"))
        self.assertTrue(result.success, result.message)
        self.assertTrue(any("跑完后打不开快速切换页" in line for line in warnings))

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

    def test_general_way_home_after_a_skip_lets_the_next_card_run(self):
        # YES-BD2 #24: a map page left open after a skip stopped the whole
        # run; Leo 2026-10-13 「能不能直接esc 然后换下一张卡带」.
        def select(card_id, *, enter_visually_complete):
            return NOT_FOUND if card_id == "Q_sp1" else ENTERED

        result, events, warnings, state = self._run(
            ("Q_sp1", "Q_sp2"), select=select, home_ok=False, recovered=True
        )

        self.assertIn(("recover",), events)
        self.assertIn(("collect", "Q_sp2", "main_area"), events)
        self.assertNotIn("回不到主页", result.message)
        self.assertTrue(any("通用退出" in line for line in warnings))

    def test_general_way_home_failing_still_stops_the_run(self):
        result, events, _warnings, _state = self._run(
            ("Q_sp1", "Q_sp2"),
            select=lambda card_id, **_k: NOT_FOUND,
            home_ok=False,
            recovered=False,
        )
        self.assertIn(("recover",), events)
        self.assertIn("回不到主页", result.message)
        self.assertNotIn(("collect", "Q_sp2", "main_area"), events)

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

    def test_a_map_left_undecided_does_not_stop_the_card(self):
        # Leo 2026-10-20: the card's other maps still run, and no record
        # keeps a map from being pressed for the day.
        def use_actions(progress, events, actions, *, card_id, map_role):
            events.append(("collect", card_id, map_role.value))
            if card_id == "Q_sp1" and map_role is CollectionMapRole.BATTLE_AREA_1:
                progress.arm_action(card_id, map_role, "召集")
                progress.mark_action_blocked(card_id, map_role, "召集", "上次点击意图未决")
                return SkillExecutionResult(False, message="召集上次点击意图未决，禁止重复点击")
            _seed_action_records(progress, card_id, map_role.value)
            return SkillExecutionResult(True)

        result, events, _warnings, state = self._run(
            ("Q_sp1", "Q_sp2"), use_actions=use_actions, unfinished=("Q_sp1",)
        )

        self.assertFalse(result.success)
        self.assertIn("第1章", result.message)
        self.assertNotIn("今天不再按这张图", result.message)
        self.assertIn(("collect", "Q_sp1", "battle_area_2"), events)
        self.assertTrue(state.card_verified("Q_sp2"))

    def test_an_unconfirmed_map_goes_on_and_the_card_is_retried_once(self):
        # Leo 2026-10-20 「沒記錄到 那也是要跑下一章吧」「一個卡帶就三張地圖而以
        # 不要讓工具判斷錯誤導致沒有完成」.
        def use_actions(progress, events, actions, *, card_id, map_role):
            events.append(("collect", card_id, map_role.value))
            if card_id == "Q_sp1":
                return SkillExecutionResult(False, message="未确认采集技能栏")
            _seed_action_records(progress, card_id, map_role.value)
            return SkillExecutionResult(True)

        result, events, warnings, state = self._run(
            ("Q_sp1", "Q_sp2"), use_actions=use_actions, unfinished=("Q_sp1",)
        )

        collected = [event[2] for event in events if event[:2] == ("collect", "Q_sp1")]
        # Every map, twice: the first pass and the one retry.
        self.assertEqual(["main_area", "battle_area_1", "battle_area_2"] * 2, collected)
        self.assertEqual(2, events.count(("select", "Q_sp1")))
        self.assertTrue(state.card_verified("Q_sp2"))
        self.assertFalse(state.card_verified("Q_sp1"))
        self.assertFalse(result.success)
        self.assertTrue(result.message.startswith("第1章"), result.message)
        self.assertIn(CollectionMapRole.MAIN_AREA.label, result.message)
        self.assertIn("技能操作失败：未确认采集技能栏", result.message)
        self.assertIn("其余地图照跑", result.message)
        self.assertNotIn("取消勾选", result.message)
        self.assertTrue(any("继续下一张图" in line for line in warnings))

    def test_an_unconfirmed_press_the_game_shows_done_is_done(self):
        def use_actions(progress, events, actions, *, card_id, map_role):
            events.append(("collect", card_id, map_role.value))
            if card_id == "Q_sp1" and map_role is CollectionMapRole.MAIN_AREA:
                return SkillExecutionResult(False, message="吸收执行证据不一致")
            _seed_action_records(progress, card_id, map_role.value)
            return SkillExecutionResult(True)

        result, events, _warnings, state = self._run(("Q_sp1",), use_actions=use_actions)

        self.assertTrue(result.success, result.message)
        self.assertTrue(state.card_verified("Q_sp1"))
        self.assertEqual(1, events.count(("select", "Q_sp1")))

    def test_used_up_skills_still_end_the_run(self):
        def use_actions(progress, events, actions, *, card_id, map_role):
            events.append(("collect", card_id, map_role.value))
            return SkillExecutionResult(False, depleted=True, message="吸收今日已用完")

        result, events, _warnings, _state = self._run(("Q_sp1", "Q_sp2"), use_actions=use_actions)

        self.assertTrue(result.depleted)
        self.assertNotIn("Q_sp2", [event[1] for event in events if len(event) > 1])


if __name__ == "__main__":
    unittest.main()
