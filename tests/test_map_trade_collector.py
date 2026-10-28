"""Map-trade collector tests (split from test_map_trade.py)."""

import tempfile
import unittest
from datetime import datetime
from time import monotonic
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.tasks.map_trade.action_icons import (
    ABSORB_ICON,
    SEARCH_ICON,
    SUMMON_ICON,
    ActionIconDetection,
    ActionIconState,
)
from src.tasks.map_trade.card_status import (
    CollectionCardSelectionOutcome,
    CollectionCardSelectionResult,
)
from src.tasks.map_trade.collector import (
    Collector,
)
from src.tasks.map_trade.collector_constants import (
    ABSORB_ACTION,
    ACTION_FEEDBACK_CHARACTER_RATIO,
    ACTION_FEEDBACK_RELATIVE_ROI,
    ACTION_FEEDBACK_SUCCESS_DELAY_SECONDS,
    ACTION_FEEDBACK_TIMEOUT,
    ACTION_ICON_DETECTION_INTERVAL,
    ACTION_OCR_WINDOW_INTERVAL,
    BATTLE_ACTIONS,
    SEARCH_ACTION,
    SEARCH_COUNTDOWN_REFERENCE_ROI,
    SEARCH_COUNTDOWN_RELATIVE_ROI,
    SKILL_FAILURE_EVIDENCE_LIMIT,
    SKILL_FIXED_COUNT_REFERENCE_ROIS,
    SKILL_GROUP_REFERENCE_POINTS,
    SKILL_GROUP_RELATIVE_POINTS,
    SKILL_GROUP_SWITCH_SETTLE_SECONDS,
    SKILL_OCR_UPSCALE,
    SUMMON_ACTION,
    SUPPRESS_ACTION,
    SearchCountdownSession,
    SkillExecutionResult,
    SkillFeedbackObservation,
)
from src.tasks.map_trade.collector_skills import (
    PIPELINE_CLICK_INTERVAL,
)
from src.tasks.map_trade.models import (
    CARD_BY_ID,
    CollectionActionState,
    CollectionMapRole,
    MatchResult,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.progress import (
    UTC_PLUS_8,
    ProgressStore,
)
from src.utils import ocr_count
from src.utils.plain_text import DIAGNOSTIC_PREFIX
from tests.helpers.map_trade import _seed_action_records, _seed_battle_supplements


class CollectionRunTest(unittest.TestCase):
    def test_collection_retries_the_same_first_card_then_skips_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8),
            )
            attempts = []
            task = SimpleNamespace(
                config={"卡带单步重试次数": 3},
                log_warning=lambda *_args: None,
                info_set=lambda *_args: None,
            )

            def select(card_id, *, enter_visually_complete):
                attempts.append((card_id, enter_visually_complete))
                return CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.FAILED,
                    NavigationResult(False, ScreenState.UNKNOWN, "failed"),
                )

            navigator = SimpleNamespace(
                select_collection_card=select,
                return_home=lambda: NavigationResult(True, ScreenState.HOME),
            )
            result = Collector(task, object(), navigator, progress).run()

        self.assertFalse(result.success)
        self.assertIn("第1章", result.message)
        self.assertEqual([("Q_sp1", False)] * 3, attempts[:3])
        self.assertEqual("Q_sp2", attempts[3][0])

    def test_collector_run_converts_runtime_error_to_collection_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            task = SimpleNamespace(
                config={},
                log_error=lambda *_args, **_kwargs: None,
                log_warning=lambda *_args, **_kwargs: None,
                info_set=lambda *_args: None,
            )
            collector = Collector(task, object(), object(), progress)

            def boom(*_args, **_kwargs):
                raise RuntimeError("click interrupted")

            collector._run_collection = boom

            result = collector.run()

        self.assertFalse(result.success)
        self.assertIn("地图采集流程异常", result.message)
        self.assertIn("click interrupted", result.message)

    def test_formal_collection_runs_safe_battle_one_battle_two_then_verifies(self):
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
                log_warning=lambda *_args: None,
                info_set=lambda *_args: None,
            )

            def select(card_id, *, enter_visually_complete):
                events.append(("select", card_id, enter_visually_complete))
                return CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.ENTERED,
                    NavigationResult(True, ScreenState.SANDBOX),
                )

            navigator = SimpleNamespace(
                select_collection_card=select,
                current_collection_target=lambda _card: None,
                prepare_collection_main_area=lambda card_id, **_kwargs: (
                    events.append(("prepare", card_id))
                    or NavigationResult(True, ScreenState.SANDBOX)
                ),
                advance_collection_map=lambda card_id, current, target: (
                    events.append(("advance", card_id, current.key, target.key))
                    or NavigationResult(True, ScreenState.SANDBOX)
                ),
                open_story_quick_switcher_from_sandbox=lambda **_kwargs: (
                    events.append(("quick",)) or NavigationResult(True, ScreenState.CARD_MENU)
                ),
                inspect_collection_card_completion=lambda card_id: (
                    events.append(("inspect", card_id))
                    or CollectionCardSelectionResult(
                        CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                        NavigationResult(True, ScreenState.CARD_MENU),
                    )
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            search = SearchCountdownSession((0.1, 0.2, 0.3, 0.4), 87)
            collector._absorb_used_up = lambda **_kwargs: None
            collector._ensure_search = lambda **_kwargs: events.append(("search",)) or search
            collector._verify_search_countdown = lambda value: (
                events.append(("countdown", value.value)) or True
            )

            def fake_use_actions(actions, *, card_id, map_role):
                events.append(("actions", tuple(action.name for action in actions)))
                _seed_action_records(progress, card_id, map_role.value)
                absorbed[0] += 1
                # The game's count after the press (21/21 on the third map).
                progress.reconcile_pending("吸收", (absorbed[0], 21))
                return SkillExecutionResult(True, absorbed[0] >= 21)

            collector._use_actions = fake_use_actions

            result = collector.run()

        self.assertTrue(result.success)
        self.assertTrue(result.depleted)
        self.assertEqual(3, result.completed_submaps)
        self.assertEqual(
            [
                ("select", "Q_sp1", False),
                ("prepare", "Q_sp1"),
                ("search",),
                ("actions", ("吸收",)),
                ("advance", "Q_sp1", "main_area", "battle_area_1"),
                # 探查 is checked on every map (pressed only when not running).
                ("search",),
                ("actions", tuple(action.name for action in BATTLE_ACTIONS)),
                ("advance", "Q_sp1", "battle_area_1", "battle_area_2"),
                ("search",),
                ("actions", tuple(action.name for action in BATTLE_ACTIONS)),
                ("quick",),
                ("inspect", "Q_sp1"),
            ],
            events,
        )
        self.assertEqual(21, progress.state.daily_absorbs)
        self.assertEqual(14, progress.state.daily_summons)
        self.assertEqual(14, progress.state.daily_suppressions)
        self.assertTrue(progress.state.card_verified("Q_sp1"))

    def test_absorb_used_up_leaves_the_next_map_untouched(self):
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
                log_warning=lambda *_args: None,
                info_set=lambda *_args: None,
            )

            def select(card_id, *, enter_visually_complete):
                events.append(("select", card_id, enter_visually_complete))
                return CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.ENTERED,
                    NavigationResult(True, ScreenState.SANDBOX),
                )

            navigator = SimpleNamespace(
                select_collection_card=select,
                current_collection_target=lambda _card: None,
                prepare_collection_main_area=lambda card_id, **_kwargs: (
                    events.append(("prepare", card_id))
                    or NavigationResult(True, ScreenState.SANDBOX)
                ),
                advance_collection_map=lambda card_id, current, target: (
                    events.append(("advance", card_id, current.key, target.key))
                    or NavigationResult(True, ScreenState.SANDBOX)
                ),
                open_story_quick_switcher_from_sandbox=lambda **_kwargs: (
                    events.append(("quick",)) or NavigationResult(True, ScreenState.CARD_MENU)
                ),
                inspect_collection_card_completion=lambda card_id: (
                    events.append(("inspect", card_id))
                    or CollectionCardSelectionResult(
                        CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                        NavigationResult(True, ScreenState.CARD_MENU),
                    )
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            search = SearchCountdownSession((0.1, 0.2, 0.3, 0.4), 87)
            # Leo 2026-10-05: ch.8 battle 2 at 21/21 still got 探查/召集/压制.
            def absorb_used_up(*, card_id, map_role):
                events.append(("absorb-check", map_role.value))
                if map_role is CollectionMapRole.BATTLE_AREA_2:
                    return SkillExecutionResult(False, True, "吸收今日已用完（21/21）")
                return None

            collector._absorb_used_up = absorb_used_up
            collector._ensure_search = lambda **_kwargs: events.append(("search",)) or search
            collector._verify_search_countdown = lambda value: (
                events.append(("countdown", value.value)) or True
            )

            def fake_use_actions(actions, *, card_id, map_role):
                events.append(("actions", tuple(action.name for action in actions)))
                _seed_action_records(progress, card_id, map_role.value)
                absorbed[0] += 1
                # The game's count after the press (21/21 on the third map).
                progress.reconcile_pending("吸收", (absorbed[0], 21))
                return SkillExecutionResult(True, absorbed[0] >= 21)

            collector._use_actions = fake_use_actions

            result = collector.run()

        self.assertTrue(result.success)
        self.assertTrue(result.depleted)
        self.assertEqual(2, result.completed_submaps)
        self.assertEqual(
            [
                ("select", "Q_sp1", False),
                ("prepare", "Q_sp1"),
                ("absorb-check", "main_area"),
                ("search",),
                ("actions", ("吸收",)),
                ("advance", "Q_sp1", "main_area", "battle_area_1"),
                ("absorb-check", "battle_area_1"),
                ("search",),
                ("actions", tuple(action.name for action in BATTLE_ACTIONS)),
                ("advance", "Q_sp1", "battle_area_1", "battle_area_2"),
                ("absorb-check", "battle_area_2"),
            ],
            events,
        )
        self.assertTrue(progress.state.depleted_today)
        self.assertFalse(progress.state.card_verified("Q_sp1"))

    def test_collection_never_starts_a_card_that_cannot_fit_daily_absorbs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            # Only the game's count stops the day (Leo 2026-10-20): this PC's
            # tally alone no longer does.  And the count only with the game
            # agreeing earlier today (Leo 2026-10-28; a stored 21/21 alone
            # lets the run in: tests/test_map_count_never_blocks.py).
            progress.state.daily_submaps = 19
            progress.state.game_counts["吸收"] = (21, 21)
            progress.state.depleted_today = True
            progress.save()
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                log_warning=lambda *_args: None,
                info_set=lambda *_args: None,
            )
            navigator = SimpleNamespace(
                select_collection_card=lambda *_args, **_kwargs: self.fail(
                    "no card is started when the game shows 21/21"
                )
            )

            result = Collector(task, object(), navigator, progress).run()

        self.assertTrue(result.success)
        self.assertTrue(result.depleted)
        self.assertEqual(0, result.completed_submaps)
        self.assertTrue(progress.game_used_up("吸收"))

    def test_formal_collection_skips_unsupported_chapter_without_progress(self):
        # No chapter is unsupported since chapter 14 got its route; the skip
        # itself stays for the next chapter that needs a special flow.
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.state.daily_submaps = 18
            progress.state.daily_summons = 12
            progress.state.daily_suppressions = 12
            progress.save()
            selected = []
            warnings = []
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                log_warning=lambda value: warnings.append(value),
                info_set=lambda *_args: None,
            )

            def select(card_id, *, enter_visually_complete):
                selected.append((card_id, enter_visually_complete))
                return CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.ENTERED,
                    NavigationResult(True, ScreenState.SANDBOX),
                )

            navigator = SimpleNamespace(
                select_collection_card=select,
                current_collection_target=lambda _card: None,
                prepare_collection_main_area=lambda _card_id, **_kwargs: NavigationResult(
                    True,
                    ScreenState.SANDBOX,
                ),
                advance_collection_map=lambda *_args: NavigationResult(
                    True,
                    ScreenState.SANDBOX,
                ),
                open_story_quick_switcher_from_sandbox=lambda **_kwargs: NavigationResult(
                    True,
                    ScreenState.CARD_MENU,
                ),
                inspect_collection_card_completion=lambda _card_id: CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                    NavigationResult(True, ScreenState.CARD_MENU),
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            collector._absorb_used_up = lambda **_kwargs: None
            collector._ensure_search = lambda **_kwargs: SearchCountdownSession(
                (0.1, 0.2, 0.3, 0.4),
                80,
            )
            collector._verify_search_countdown = lambda _session: True

            def fake_use_actions(_actions, *, card_id, map_role):
                _seed_action_records(progress, card_id, map_role.value)
                return SkillExecutionResult(True)

            collector._use_actions = fake_use_actions
            with patch(
                "src.tasks.map_trade.collector.COLLECTABLE_CARDS",
                (CARD_BY_ID["Q_sp14"], CARD_BY_ID["Q_sp15"]),
            ), patch(
                "src.tasks.map_trade.collector.UNSUPPORTED_COLLECTION_CARD_NUMBERS",
                frozenset({14}),
            ):
                result = collector.run()

        self.assertTrue(result.success)
        self.assertEqual([("Q_sp15", False)], selected)
        self.assertEqual(set(), progress.state.completed_targets("Q_sp14"))
        self.assertTrue(progress.state.card_verified("Q_sp15"))
        self.assertTrue(any("第14章" in value for value in warnings))

    def test_observed_skill_limit_finishes_current_battle_actions_then_stops(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8),
            )
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                log_warning=lambda *_args: None,
                info_set=lambda *_args: None,
            )
            events = []
            navigator = SimpleNamespace(
                select_collection_card=lambda *_args, **_kwargs: CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.ENTERED,
                    NavigationResult(True, ScreenState.SANDBOX),
                ),
                current_collection_target=lambda _card: None,
                prepare_collection_main_area=lambda _card_id, **_kwargs: NavigationResult(
                    True,
                    ScreenState.SANDBOX,
                ),
                advance_collection_map=lambda _card_id, current, target: (
                    events.append(("advance", current.key, target.key))
                    or NavigationResult(True, ScreenState.SANDBOX)
                ),
                open_story_quick_switcher_from_sandbox=lambda **_kwargs: self.fail(
                    "battle two must be left for the next daily cycle"
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            collector._absorb_used_up = lambda **_kwargs: None
            collector._ensure_search = lambda **_kwargs: SearchCountdownSession(
                (0.1, 0.2, 0.3, 0.4),
                80,
            )
            collector._verify_search_countdown = lambda _session: True
            action_results = iter(
                (
                    SkillExecutionResult(True),
                    SkillExecutionResult(True, depleted=True),
                )
            )

            def fake_use_actions(_actions, *, card_id, map_role):
                _seed_action_records(progress, card_id, map_role.value)
                return next(action_results)

            collector._use_actions = fake_use_actions
            with patch(
                "src.tasks.map_trade.collector.COLLECTABLE_CARDS",
                (CARD_BY_ID["Q_sp1"],),
            ):
                result = collector.run()

        self.assertTrue(result.success)
        self.assertTrue(result.depleted)
        self.assertEqual(2, result.completed_submaps)
        self.assertEqual(
            {"main_area", "battle_area_1"},
            progress.state.completed_targets("Q_sp1"),
        )
        self.assertEqual(
            [("advance", "main_area", "battle_area_1")],
            events,
        )

    def test_an_ordinary_card_is_done_once_its_three_maps_are_done(self):
        # Leo 2026-10-21 「明明三張圖都有紀錄有吸收 就完成了」: badges read
        # open after all three maps no longer send the card round again.
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            cards = (CARD_BY_ID["Q_sp1"], CARD_BY_ID["Q_sp2"])
            warnings = []
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                info_set=lambda *_args: None,
                log_warning=warnings.append,
            )
            selected = []
            navigator = SimpleNamespace(
                select_collection_card=lambda card_id, **_kwargs: (
                    selected.append(card_id)
                    or CollectionCardSelectionResult(
                        CollectionCardSelectionOutcome.ENTERED,
                        NavigationResult(True, ScreenState.SANDBOX),
                    )
                ),
                current_collection_target=lambda _card: None,
                prepare_collection_main_area=lambda _card_id, **_kwargs: NavigationResult(
                    True, ScreenState.SANDBOX
                ),
                advance_collection_map=lambda *_args: NavigationResult(True, ScreenState.SANDBOX),
                open_story_quick_switcher_from_sandbox=lambda **_kwargs: NavigationResult(
                    True, ScreenState.CARD_MENU
                ),
                inspect_collection_card_completion=lambda card_id: NavigationResult(
                    card_id != "Q_sp1", ScreenState.CARD_MENU, "未同时确认吸取与压制完成"
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            collector._absorb_used_up = lambda **_kwargs: None
            collector._ensure_search = lambda **_kwargs: SearchCountdownSession(
                (0.1, 0.2, 0.3, 0.4), 80
            )
            collector._verify_search_countdown = lambda _session: True

            def use_actions(actions, *, card_id, map_role):
                for action in actions:
                    limit = {"吸收": 21, "召集": 21, "压制": 70}[action.name]
                    progress.arm_action(card_id, map_role, action.name, baseline=(0, limit))
                    progress.mark_action_local_done(card_id, map_role, action.name, pending=True)
                return SkillExecutionResult(
                    True, pending_actions=tuple(action.name for action in actions)
                )

            collector._use_actions = use_actions
            with patch("src.tasks.map_trade.collector.COLLECTABLE_CARDS", cards):
                result = collector.run()

            self.assertTrue(result.success)
            self.assertEqual(["Q_sp1", "Q_sp2"], selected)
            self.assertTrue(progress.state.card_verified("Q_sp1"))
            self.assertTrue(progress.state.card_verified("Q_sp2"))
            self.assertTrue(any("记为本周完成" in text for text in warnings))
            self.assertNotIn("不再跑", result.message)
            self.assertEqual(0, progress.pending_count())

            selected.clear()
            with patch("src.tasks.map_trade.collector.COLLECTABLE_CARDS", cards):
                again = Collector(task, object(), navigator, progress).run()
            self.assertTrue(again.success)
            self.assertEqual([], selected)

    def test_old_records_of_three_done_maps_count_as_done_without_entering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            cards = (CARD_BY_ID["Q_sp5"], CARD_BY_ID["Q_sp6"])
            for card in cards:
                progress.state.cards[card.card_id] = [target.key for target in card.targets]
            progress.save()
            checked = []
            navigator = SimpleNamespace(
                select_collection_card=lambda card_id, **_kwargs: self.fail("entered"),
                inspect_collection_card_completion=lambda card_id: (
                    checked.append(card_id) or self.fail("badges read")
                ),
            )
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                info_set=lambda *_args: None,
                log_warning=lambda *_args: None,
            )
            with patch("src.tasks.map_trade.collector.COLLECTABLE_CARDS", cards):
                result = Collector(task, object(), navigator, progress).run()
            self.assertTrue(result.success)
            # 第6章 too (Leo 2026-10-21 「第六章確認跑過一遍就算完成」).
            for card in cards:
                self.assertTrue(progress.state.card_verified(card.card_id))

    def test_final_map_pending_is_success_warning_and_completed_target_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            card = CARD_BY_ID["Q_sp1"]
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                info_set=lambda *_args: None,
                log_warning=lambda *_args: None,
            )
            selected = []
            navigator = SimpleNamespace(
                select_collection_card=lambda card_id, **_kwargs: (
                    selected.append(card_id)
                    or CollectionCardSelectionResult(
                        CollectionCardSelectionOutcome.ENTERED,
                        NavigationResult(True, ScreenState.SANDBOX),
                    )
                ),
                current_collection_target=lambda _card: None,
                prepare_collection_main_area=lambda _card_id, **_kwargs: NavigationResult(
                    True, ScreenState.SANDBOX
                ),
                advance_collection_map=lambda *_args: NavigationResult(True, ScreenState.SANDBOX),
                open_story_quick_switcher_from_sandbox=lambda **_kwargs: NavigationResult(
                    True, ScreenState.CARD_MENU
                ),
                inspect_collection_card_completion=lambda _card_id: NavigationResult(
                    True, ScreenState.CARD_MENU
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            collector._absorb_used_up = lambda **_kwargs: None
            collector._ensure_search = lambda **_kwargs: SearchCountdownSession(
                (0.1, 0.2, 0.3, 0.4), 80
            )
            collector._verify_search_countdown = lambda _session: True

            def use_actions(actions, *, card_id, map_role):
                for action in actions:
                    limit = {"吸收": 21, "召集": 21, "压制": 70}[action.name]
                    progress.arm_action(
                        card_id,
                        map_role,
                        action.name,
                        baseline=(0, limit),
                    )
                    progress.mark_action_local_done(
                        card_id,
                        map_role,
                        action.name,
                        pending=True,
                    )
                return SkillExecutionResult(
                    True,
                    pending_actions=tuple(action.name for action in actions),
                )

            collector._use_actions = use_actions
            with patch(
                "src.tasks.map_trade.collector.COLLECTABLE_CARDS",
                (card,),
            ):
                result = collector.run()

            self.assertTrue(result.success)
            self.assertTrue(progress.state.card_complete(card.card_id))
            # The completion badge settles the card's pending counts, so they
            # cannot block later cards (live 2026-09-28).
            self.assertEqual(0, progress.pending_count())

            # A rerun sees the durable verified target and must not select or
            # click it merely because count settlement remains pending.
            selected.clear()
            with patch(
                "src.tasks.map_trade.collector.COLLECTABLE_CARDS",
                (card,),
            ):
                resumed = Collector(task, object(), navigator, progress).run()
            self.assertTrue(resumed.success)
            self.assertEqual([], selected)


# The group search presses group buttons only where the skill bar is seen.
BAR_SHOWN = patch(
    "src.tasks.map_trade.collector_skills.selected_skill_group", new=lambda _frame: 1
)


class CollectorSkillTest(unittest.TestCase):
    @staticmethod
    def _skill_collector(states, counts):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        statuses = []
        task = SimpleNamespace(
            config={},
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda key, value: statuses.append((key, value)),
        )
        vision = SimpleNamespace(
            click_reference=lambda *_args, **_kwargs: None,
            wait_template=lambda *_args, **_kwargs: MatchResult(
                0.99,
                (100, 100),
                (40, 40),
                pixel_score=0.90,
                zncc_score=0.95,
            ),
            capture=lambda: frame,
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
            ocr_text=lambda _frame, name, **_kwargs: "87" if name == "探查倒计时" else "",
            click_client=lambda center, shape, after_sleep=0: clicks.append(
                (center, shape, after_sleep)
            ),
        )
        progress = ProgressStore(
            Path(tempfile.mkdtemp(prefix="ok-bd2-skill-")) / "progress.json",
            lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
        )
        progress.load()
        collector = Collector(task, vision, SimpleNamespace(), progress)
        executed_icons = set()

        def detect(_frame, icon):
            if icon.name in executed_icons:
                state = ActionIconState.ABSENT if icon is SEARCH_ICON else ActionIconState.USED
            else:
                state = states[icon.name]
            return ActionIconDetection(
                state,
                MatchResult(
                    0.98,
                    (100, 100),
                    (40, 40),
                    pixel_score=0.70 if state is ActionIconState.USED else 0.95,
                    zncc_score=0.90,
                ),
                0.65 if state is ActionIconState.USED else 1.0,
                stable=True,
                sample_count=2,
            )

        collector.action_icons = SimpleNamespace(detect=detect)
        count_iters = {name: iter(values) for name, values in counts.items()}
        collector._read_count_window = lambda action, _detection=None, **_kwargs: next(
            count_iters[action.name]
        )

        def feedback(action):
            executed_icons.add(action.icon.name)
            was_used = states[action.icon.name] is ActionIconState.USED
            return SkillFeedbackObservation(
                "失败反馈" if was_used else "成功反馈",
                "failure" if was_used else "success",
                1.0,
            )

        collector._read_action_feedback = feedback
        return collector, clicks, statuses, progress

    def test_skill_failure_evidence_is_bounded_and_replayable(self):
        warnings = []
        infos = []
        collector = Collector(
            SimpleNamespace(
                config={},
                log_warning=warnings.append,
                log_info=infos.append,
                info_set=lambda *_args: None,
            ),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
        )
        collector._last_skill_observations["召集"] = {
            "state": "unknown",
            "match": 0.9499,
            "pixel": 0.78,
            "zncc": 0.6387,
            "phase": "battle_area_1",
        }
        for index in range(SKILL_FAILURE_EVIDENCE_LIMIT + 5):
            collector._record_skill_failure(
                f"Q_sp{index + 1}",
                "战斗区域1",
                SkillExecutionResult(False, message="召集图标状态未知"),
            )

        evidence = collector.skill_failure_evidence
        self.assertEqual(SKILL_FAILURE_EVIDENCE_LIMIT, len(evidence))
        self.assertEqual("Q_sp6", evidence[0]["card"])
        self.assertEqual("战斗区域1", evidence[-1]["phase"])
        self.assertEqual(0.6387, evidence[-1]["observations"]["召集"]["zncc"])
        # The raw evidence goes to the log file only, never the player's
        # summary (a player 2026-10-26 got a dozen dumped dicts there).
        self.assertEqual(SKILL_FAILURE_EVIDENCE_LIMIT + 5, len(infos))
        self.assertTrue(all(line.startswith(DIAGNOSTIC_PREFIX) for line in infos))
        self.assertEqual([], warnings)

    def test_action_icon_detection_retries_a_transient_miss(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        missing = ActionIconDetection(
            ActionIconState.ABSENT,
            MatchResult(-1.0, (0, 0), (0, 0)),
        )
        available = ActionIconDetection(
            ActionIconState.AVAILABLE,
            MatchResult(0.969, (1500, 850), (50, 45), 0.87, 0.739),
            1.0,
        )
        sleeps = []
        detections = iter((missing, available))
        task = SimpleNamespace(
            config={},
            sleep=lambda seconds: sleeps.append(seconds),
            info_set=lambda *_args: None,
        )
        vision = SimpleNamespace(capture=lambda: frame)
        collector = Collector(task, vision, SimpleNamespace(), SimpleNamespace())
        collector.action_icons = SimpleNamespace(
            detect=lambda *_args: next(detections),
        )

        selected_frame, selected = collector._detect_action_icon(SUMMON_ICON)

        self.assertIs(frame, selected_frame)
        self.assertIs(available, selected)
        self.assertEqual([ACTION_ICON_DETECTION_INTERVAL], sleeps)

    def test_skill_menu_can_merge_each_icon_from_short_stable_window(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        available = ActionIconDetection(
            ActionIconState.AVAILABLE,
            MatchResult(0.969, (1500, 850), (50, 45), 0.87, 0.739),
            1.0,
        )
        missing = ActionIconDetection(
            ActionIconState.ABSENT,
            MatchResult(-1.0, (0, 0), (0, 0)),
        )
        sleeps = []
        call_number = [0]
        task = SimpleNamespace(
            config={},
            sleep=lambda seconds: sleeps.append(seconds),
            info_set=lambda *_args: None,
            log_warning=lambda *_args: None,
        )
        vision = SimpleNamespace(capture=lambda: frame)
        collector = Collector(task, vision, SimpleNamespace(), SimpleNamespace())

        def detect(_frame, icon):
            frame_number = call_number[0] // 2
            call_number[0] += 1
            if frame_number == 0:
                return available if icon is ABSORB_ICON else missing
            if frame_number == 1:
                return missing if icon is ABSORB_ICON else available
            return missing

        collector.action_icons = SimpleNamespace(detect=detect)

        self.assertTrue(collector._open_skill_menu((ABSORB_ICON, SUMMON_ICON)))
        self.assertEqual(6, call_number[0])
        self.assertEqual(
            [ACTION_ICON_DETECTION_INTERVAL] * 2,
            sleeps,
        )

    def test_action_feedback_region_and_character_threshold_follow_calibration(self):
        self.assertEqual(
            (735 / 1920, 165 / 1080, 1182 / 1920, 270 / 1080),
            ACTION_FEEDBACK_RELATIVE_ROI,
        )
        self.assertEqual(0.80, ACTION_FEEDBACK_CHARACTER_RATIO)
        self.assertEqual((1535, 960, 82, 60), SEARCH_COUNTDOWN_REFERENCE_ROI)
        self.assertEqual(
            {
                "吸收": (1498, 890, 66, 37),
                "召集": (1542, 790, 66, 33),
                "压制": (1645, 743, 75, 33),
            },
            SKILL_FIXED_COUNT_REFERENCE_ROIS,
        )
        self.assertEqual(
            {
                1: (1671, 1011),
                2: (1749, 1011),
                3: (1824, 1011),
            },
            SKILL_GROUP_REFERENCE_POINTS,
        )
        self.assertEqual(
            {group: (x / 1920, y / 1080) for group, (x, y) in SKILL_GROUP_REFERENCE_POINTS.items()},
            SKILL_GROUP_RELATIVE_POINTS,
        )
        self.assertEqual(0.8, SKILL_GROUP_SWITCH_SETTLE_SECONDS)
        self.assertEqual(
            1.0,
            Collector._feedback_character_ratio(
                "在74秒内确认隐藏物品的位置。",
                "在秒内确认隐藏物品的位置",
            ),
        )
        self.assertGreaterEqual(
            Collector._feedback_character_ratio(
                "周围没有可以吸收的拾取勿。",
                "周围没有可以吸收的拾取物",
            ),
            ACTION_FEEDBACK_CHARACTER_RATIO,
        )
        self.assertLess(
            Collector._feedback_character_ratio(
                "召集带奖励的战场怪物",
                "没有可制伏的怪物",
            ),
            ACTION_FEEDBACK_CHARACTER_RATIO,
        )

    def test_action_feedback_window_matches_absorb_failure(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        calls = []
        sleeps = []
        feedbacks = iter(("", "周围没有可以吸收的拾取物。"))
        collector = Collector(
            SimpleNamespace(
                config={},
                sleep=lambda seconds: sleeps.append(seconds),
                info_set=lambda *_args: None,
            ),
            SimpleNamespace(
                capture=lambda: frame,
                ocr_text=lambda _frame, name, **kwargs: (
                    calls.append((name, kwargs)) or next(feedbacks)
                ),
            ),
            SimpleNamespace(),
            SimpleNamespace(),
        )

        feedback = collector._read_action_feedback(ABSORB_ACTION)

        self.assertEqual("failure", feedback.outcome)
        self.assertEqual(1.0, feedback.ratio)
        self.assertEqual(2, len(calls))
        self.assertEqual([ACTION_OCR_WINDOW_INTERVAL], sleeps)
        self.assertTrue(all(name == "吸收执行反馈" for name, _kwargs in calls))
        self.assertTrue(
            all(
                kwargs["relative_roi"] == ACTION_FEEDBACK_RELATIVE_ROI
                and kwargs["target_height"] == 1080
                for _name, kwargs in calls
            )
        )

    def test_suppress_feedback_accepts_video_wording_with_or_without_de(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for text in (
            "已制伏地图内所有怪物。",
            "已制伏地图内所有的怪物。",
        ):
            with self.subTest(text=text):
                collector = Collector(
                    SimpleNamespace(
                        config={},
                        sleep=lambda *_args: None,
                        info_set=lambda *_args: None,
                    ),
                    SimpleNamespace(
                        capture=lambda: frame,
                        ocr_text=lambda *_args, **_kwargs: text,
                        simplify=lambda value: value,
                    ),
                    SimpleNamespace(),
                    SimpleNamespace(),
                )

                feedback = collector._read_action_feedback(SUPPRESS_ACTION)

                self.assertEqual("success", feedback.outcome)

    def test_success_toast_with_the_second_line_is_not_read_as_failure(self):
        # 2560x1440 player 2026-10-20: 「召集执行反馈明确失败：升星天赋技能后，
        # 可获得经验值。 召集带奖励的战场怪物。」, and the map was blocked.
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cases = (
            (SUMMON_ACTION, "升星天赋技能后，可获得经验值。 召集带奖励的战场怪物。", "success"),
            (SUPPRESS_ACTION, "升星天赋技能后，可获得经验值。 已制伏地图内所有怪物。", "success"),
            (ABSORB_ACTION, "升星天赋技能后，可获得经验值。 吸收周围的拾取物。", "success"),
            (SUMMON_ACTION, "升星天赋技能后，可获得经验值。 无可召集的战场怪物。", "failure"),
            (SUPPRESS_ACTION, "没有可制伏的怪物。", "failure"),
        )
        for action, text, outcome in cases:
            with self.subTest(text=text):
                collector = Collector(
                    SimpleNamespace(config={}, sleep=lambda *_a: None, info_set=lambda *_a: None),
                    SimpleNamespace(
                        capture=lambda: frame,
                        ocr_text=lambda *_a, _text=text, **_k: _text,
                        simplify=lambda value: value,
                    ),
                    SimpleNamespace(),
                    SimpleNamespace(),
                )

                self.assertEqual(outcome, collector._read_action_feedback(action).outcome)

    def test_absorb_failure_feedback_has_precedence_over_positive_text(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        collector = Collector(
            SimpleNamespace(config={}, sleep=lambda *_args: None, info_set=lambda *_args: None),
            SimpleNamespace(
                capture=lambda: frame,
                ocr_text=lambda *_args, **_kwargs: "吸收周围的拾取物 周围没有可以吸收的拾取物",
            ),
            SimpleNamespace(),
            SimpleNamespace(),
        )

        feedback = collector._read_action_feedback(ABSORB_ACTION)

        self.assertEqual("failure", feedback.outcome)

    def test_action_feedback_window_runs_until_timeout_when_ocr_stays_empty(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        calls = []
        sleeps = []
        clock = [0.0]
        collector = Collector(
            SimpleNamespace(
                config={},
                sleep=lambda seconds: (
                    sleeps.append(seconds),
                    clock.__setitem__(0, clock[0] + seconds),
                ),
                info_set=lambda *_args: None,
            ),
            SimpleNamespace(
                capture=lambda: frame,
                ocr_text=lambda _frame, name, **kwargs: calls.append((name, kwargs)) or "",
            ),
            SimpleNamespace(),
            SimpleNamespace(),
        )

        with patch(
            "src.tasks.map_trade.collector_skills.monotonic",
            side_effect=lambda: clock[0],
        ):
            feedback = collector._read_action_feedback(SEARCH_ACTION)

        self.assertIsNone(feedback.outcome)
        self.assertEqual(13, len(calls))
        self.assertEqual(ACTION_FEEDBACK_TIMEOUT, sum(sleeps))
        self.assertEqual(ACTION_FEEDBACK_TIMEOUT, clock[0])

    def test_search_waits_after_feedback_match_before_countdown(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        sleeps = []
        available = ActionIconDetection(
            ActionIconState.AVAILABLE,
            MatchResult(0.98, (1550, 969), (52, 44)),
        )
        absent = ActionIconDetection(
            ActionIconState.ABSENT,
            MatchResult(-1.0, (0, 0), (0, 0)),
        )
        detections = iter((available, available, absent))
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda seconds: sleeps.append(seconds),
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, name, **kwargs: (
                "在44秒内确认隐藏物品的位置。" if name == "探查执行反馈" else "44"
            ),
            click_client=lambda *_args, **_kwargs: None,
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        collector = Collector(task, vision, SimpleNamespace(), SimpleNamespace())
        collector._open_skill_menu = lambda *_args, **_kwargs: True
        collector.action_icons = SimpleNamespace(detect=lambda *_args: next(detections))

        result = collector._start_search(map_role=CollectionMapRole.MAIN_AREA)

        self.assertIsInstance(result, SearchCountdownSession)
        self.assertEqual(
            [ACTION_ICON_DETECTION_INTERVAL, ACTION_FEEDBACK_SUCCESS_DELAY_SECONDS],
            sleeps,
        )

    def test_search_countdown_uses_manual_region_after_icon_match(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        ocr_calls = []
        clicks = []
        available = ActionIconDetection(
            ActionIconState.AVAILABLE,
            MatchResult(0.98, (1550, 969), (52, 44), 0.95, 0.92),
            1.0,
        )
        absent = ActionIconDetection(
            ActionIconState.ABSENT,
            MatchResult(-1.0, (0, 0), (0, 0)),
        )
        detections = iter((available, available, absent))
        collector = Collector(
            SimpleNamespace(
                config={},
                sleep=lambda *_args: None,
                info_set=lambda *_args: None,
            ),
            SimpleNamespace(
                capture=lambda: frame,
                click_client=lambda *args, **kwargs: clicks.append((args, kwargs)),
                ocr_text=lambda _frame, name, **kwargs: (
                    ocr_calls.append((name, kwargs))
                    or ("在48秒内确认隐藏物品的位置。" if name == "探查执行反馈" else "48")
                ),
            ),
            SimpleNamespace(),
            SimpleNamespace(),
        )
        collector._open_skill_menu = lambda *_args, **_kwargs: True
        collector.action_icons = SimpleNamespace(detect=lambda *_args: next(detections))

        result = collector._start_search(map_role=CollectionMapRole.MAIN_AREA)

        self.assertEqual(SEARCH_COUNTDOWN_RELATIVE_ROI, result.relative_roi)
        self.assertEqual(available.match.center, clicks[0][0][0])
        countdown_kwargs = next(kwargs for name, kwargs in ocr_calls if name == "探查倒计时")
        self.assertEqual(SEARCH_COUNTDOWN_RELATIVE_ROI, countdown_kwargs["relative_roi"])
        self.assertEqual(SKILL_OCR_UPSCALE, countdown_kwargs["ocr_scale"])

    def test_dimmed_absorb_and_summon_are_preexisting_used_without_click(self):
        collector, clicks, _statuses, _progress = self._skill_collector(
            {
                # 探查 runs: its countdown covers the glyph.
                "探查": ActionIconState.ABSENT,
                "吸收": ActionIconState.USED,
                "召集": ActionIconState.USED,
            },
            {
                "探查": ((1, 40), (2, 40)),
                "吸收": ((2, 21), (2, 21)),
                "召集": ((1, 21), (1, 21)),
            },
        )

        result = collector._use_actions(
            (ABSORB_ACTION, SUMMON_ACTION),
            card_id="Q_sp1",
            map_role=CollectionMapRole.MAIN_AREA,
        )

        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)
        self.assertEqual(0, len(clicks))
        # Leo 2026-10-07: grey = done this week; nothing waits for a count.
        self.assertEqual((), tuple(result.pending_actions))

    def test_skill_ocr_failure_still_presses_by_the_icon(self):
        # Leo 2026-10-28 「除非你確定跑圖次數已經確實滿了」: an unread count no
        # longer leaves the skill unpressed; the icon greying decides.
        collector, clicks, _statuses, _progress = self._skill_collector(
            {
                "探查": ActionIconState.AVAILABLE,
                "吸收": ActionIconState.AVAILABLE,
                "召集": ActionIconState.AVAILABLE,
            },
            {"吸收": (None, None), "召集": ((2, 21), (3, 21))},
        )

        search = collector._start_search(map_role=CollectionMapRole.MAIN_AREA)
        self.assertIsInstance(search, SearchCountdownSession)
        result = collector._use_actions(
            (ABSORB_ACTION, SUMMON_ACTION),
            card_id="Q_sp1",
            map_role=CollectionMapRole.MAIN_AREA,
        )

        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)
        self.assertEqual(3, len(clicks))

    def test_full_read_on_a_pressable_skill_is_pressed_and_the_game_decides(self):
        # Read 21/21 while the game shows 吸收 pressable: pressed alone first;
        # the game took it (its icon greyed), so the count was misread and
        # 召集 follows (Leo 2026-10-28).
        collector, clicks, _statuses, _progress = self._skill_collector(
            {
                "探查": ActionIconState.AVAILABLE,
                "吸收": ActionIconState.AVAILABLE,
                "召集": ActionIconState.AVAILABLE,
            },
            {"吸收": ((21, 21), (21, 21)), "召集": ((2, 21), (3, 21))},
        )

        search = collector._start_search(map_role=CollectionMapRole.MAIN_AREA)
        self.assertIsInstance(search, SearchCountdownSession)
        result = collector._use_actions(
            (ABSORB_ACTION, SUMMON_ACTION),
            card_id="Q_sp1",
            map_role=CollectionMapRole.MAIN_AREA,
        )

        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)
        self.assertEqual(3, len(clicks))

    def test_exhausted_skill_the_game_refuses_stops_before_the_next_skill(self):
        collector, clicks, _statuses, _progress = self._skill_collector(
            {
                "探查": ActionIconState.AVAILABLE,
                "吸收": ActionIconState.AVAILABLE,
                "召集": ActionIconState.AVAILABLE,
            },
            {
                "吸收": ((21, 21),) * 4,
            },
        )

        search = collector._start_search(map_role=CollectionMapRole.MAIN_AREA)
        self.assertIsInstance(search, SearchCountdownSession)
        # The game takes no 吸收 press: no toast, its icon stays bright.
        collector._read_action_feedback = lambda _action: SkillFeedbackObservation("", None, 0.0)
        result = collector._use_actions(
            (ABSORB_ACTION, SUMMON_ACTION),
            card_id="Q_sp1",
            map_role=CollectionMapRole.MAIN_AREA,
        )

        self.assertFalse(result.completed)
        self.assertTrue(result.depleted)
        # 探查, then 吸收 twice (once more when nothing showed); 召集 never.
        self.assertEqual(3, len(clicks))

    def test_all_three_completed_can_report_depleted_after_completion(self):
        collector, clicks, _statuses, _progress = self._skill_collector(
            {
                "探查": ActionIconState.AVAILABLE,
                "吸收": ActionIconState.AVAILABLE,
                "召集": ActionIconState.AVAILABLE,
            },
            {
                "吸收": ((20, 21), (21, 21)),
                "召集": ((20, 21), (21, 21)),
            },
        )

        search = collector._start_search(map_role=CollectionMapRole.MAIN_AREA)
        self.assertIsInstance(search, SearchCountdownSession)
        result = collector._use_actions(
            (ABSORB_ACTION, SUMMON_ACTION),
            card_id="Q_sp1",
            map_role=CollectionMapRole.MAIN_AREA,
        )

        self.assertTrue(result.completed)
        self.assertTrue(result.depleted)
        self.assertEqual(3, len(clicks))

    def test_battle_flow_executes_absorb_summon_and_suppression(self):
        collector, clicks, _statuses, _progress = self._skill_collector(
            {
                "吸收": ActionIconState.AVAILABLE,
                "召集": ActionIconState.AVAILABLE,
                "制服": ActionIconState.AVAILABLE,
            },
            {
                "吸收": ((4, 21), (5, 21)),
                "召集": ((2, 21), (3, 21)),
                "压制": ((6, 60), (7, 60)),
            },
        )

        result = collector._use_actions(
            BATTLE_ACTIONS,
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)
        self.assertEqual(3, len(clicks))

    def _missed_press_collector(
        self, missed_presses, *, skill="召集", toast=None, steady=True
    ):
        """``skill`` ignores its first ``missed_presses`` presses: the icon
        stays bright and the count does not move.  ``toast`` is what the
        missed press shows; ``steady`` is whether its count reads steadily."""

        collector, clicks, statuses, progress = self._skill_collector(
            {
                "吸收": ActionIconState.AVAILABLE,
                "召集": ActionIconState.AVAILABLE,
                "制服": ActionIconState.AVAILABLE,
            },
            {},
        )
        taken = {"吸收": 0, "召集": 0, "压制": 0}
        base = {"吸收": (4, 21), "召集": (2, 21), "压制": (6, 60)}

        def read_count(action, _detection=None, **_kwargs):
            collector._last_count_window_stable = steady
            return (base[action.name][0] + taken[action.name], base[action.name][1])

        collector._read_count_window = read_count
        presses = {skill: 0}
        succeed = collector._read_action_feedback

        def feedback(action):
            if action.name == skill:
                presses[skill] += 1
                if presses[skill] <= missed_presses:
                    if toast is None:
                        return SkillFeedbackObservation("", None, 0.0)
                    return SkillFeedbackObservation(toast, "success", 1.0)
            taken[action.name] += 1
            return succeed(action)

        collector._read_action_feedback = feedback
        return collector, clicks, statuses, progress, taken

    def test_missed_summon_press_is_pressed_again(self):
        # A player 2026-10-09: 「跑图召集点的太快了经常点不上失败」.
        collector, clicks, statuses, _progress, taken = self._missed_press_collector(1)
        order = []
        feedback = collector._read_action_feedback
        collector._read_action_feedback = lambda action: (
            order.append(action.name) or feedback(action)
        )

        result = collector._use_actions(
            BATTLE_ACTIONS,
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        self.assertTrue(result.completed, result.message)
        # YES-BD2 #23: the still-bright 召集 is pressed again before 压制
        # (it used to come after 压制); nothing twice.
        self.assertEqual(["吸收", "召集", "召集", "压制"], order)
        self.assertEqual(4, len(clicks))
        self.assertEqual({"吸收": 1, "召集": 1, "压制": 1}, taken)
        self.assertTrue(any("补按" in str(value) for _key, value in statuses))

    def test_summon_is_pressed_again_once_and_then_left_alone(self):
        # Leo 2026-10-09: 「补按后 你就不要管了」.
        collector, clicks, _statuses, progress, taken = self._missed_press_collector(99)

        result = collector._use_actions(
            BATTLE_ACTIONS,
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        self.assertTrue(result.completed, result.message)
        self.assertEqual(4, len(clicks))
        self.assertEqual({"吸收": 1, "召集": 0, "压制": 1}, taken)
        record = progress.get_action_record("Q_sp1", CollectionMapRole.BATTLE_AREA_1, "召集")
        self.assertEqual(CollectionActionState.SETTLED.value, record["state"])

    def test_press_with_success_toast_is_not_pressed_again(self):
        # Leo 2026-10-09: a press that took must never be pressed again.
        # 压制 stays bright after it takes, so a misread count alone must
        # not bring a second press.
        collector, clicks, _statuses, _progress, _taken = self._missed_press_collector(
            1, skill="压制", toast="成功反馈"
        )

        result = collector._use_actions(
            BATTLE_ACTIONS,
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        self.assertFalse(result.completed)
        self.assertEqual(3, len(clicks))

    def test_summon_with_unsteady_count_is_still_pressed_again(self):
        # YES-BD2 #3 (2026-10-09): 召集 dropped on a slow PC, count 3/19 ->
        # 3/19 and the icon still bright; it greys once it takes, so it is
        # pressed again and the run goes on.
        collector, clicks, _statuses, _progress, taken = self._missed_press_collector(
            1, steady=False
        )

        result = collector._use_actions(
            BATTLE_ACTIONS,
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        self.assertTrue(result.completed, result.message)
        self.assertEqual(4, len(clicks))
        self.assertEqual({"吸收": 1, "召集": 1, "压制": 1}, taken)

    def test_press_with_unsteady_count_is_not_pressed_again(self):
        collector, clicks, _statuses, _progress, _taken = self._missed_press_collector(
            1, skill="压制", steady=False
        )

        result = collector._use_actions(
            BATTLE_ACTIONS,
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        self.assertFalse(result.completed)
        self.assertEqual(3, len(clicks))

    def test_missed_suppress_press_is_pressed_again(self):
        collector, clicks, _statuses, _progress, taken = self._missed_press_collector(
            1, skill="压制"
        )

        result = collector._use_actions(
            BATTLE_ACTIONS,
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        self.assertTrue(result.completed, result.message)
        self.assertEqual(4, len(clicks))
        self.assertEqual({"吸收": 1, "召集": 1, "压制": 1}, taken)

    def test_skill_presses_are_spaced_by_the_click_interval(self):
        collector, clicks, _statuses, _progress, _taken = self._missed_press_collector(0)
        events = []
        collector.task.sleep = lambda seconds: events.append(seconds)
        click = collector.vision.click_client
        collector.vision.click_client = lambda *args, **kwargs: (
            events.append("click"),
            click(*args, **kwargs),
        )

        collector._use_actions(
            BATTLE_ACTIONS,
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        self.assertEqual(1.2, PIPELINE_CLICK_INTERVAL)
        presses = [index for index, event in enumerate(events) if event == "click"]
        self.assertEqual(3, len(presses))
        for previous, current in zip(presses, presses[1:]):
            waits = [value for value in events[previous + 1:current] if value != "click"]
            self.assertGreater(sum(waits), 1.1)

    def test_suppression_count_roi_uses_manual_fixed_region(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        calls = []
        detection = ActionIconDetection(
            ActionIconState.AVAILABLE,
            MatchResult(0.98, (1440, 700), (80, 80), 0.95, 0.92),
            0.95,
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, name, **kwargs: calls.append((name, kwargs)) or "7/60",
        )
        collector = Collector(
            SimpleNamespace(config={}, sleep=lambda *_args: None),
            vision,
            SimpleNamespace(),
            SimpleNamespace(),
        )

        count = collector._read_count(SUPPRESS_ACTION, detection)

        self.assertEqual((7, 60), count)
        self.assertEqual("压制次数", calls[0][0])
        self.assertNotIn("roi", calls[0][1])
        self.assertEqual(1080, calls[0][1]["target_height"])
        self.assertEqual(
            SUPPRESS_ACTION.fixed_count_relative_roi,
            calls[0][1]["relative_roi"],
        )
        self.assertEqual(ocr_count.LOOKS[0].scale, calls[0][1]["ocr_scale"])

    def test_post_click_count_ocr_uses_manual_region_after_icon_refresh(self):
        before_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        after_frame = np.ones((1080, 1920, 3), dtype=np.uint8)
        before = ActionIconDetection(
            ActionIconState.AVAILABLE,
            MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
            0.95,
        )
        after = ActionIconDetection(
            ActionIconState.USED,
            MatchResult(0.98, (960, 420), (52, 48), 0.95, 0.92),
            0.65,
        )
        frames = iter((before_frame, before_frame, after_frame, after_frame))
        detections = iter((before, before, after, after))
        count_detections = []
        clicks = []
        progress = ProgressStore(
            Path(tempfile.mkdtemp(prefix="ok-bd2-post-click-")) / "progress.json",
            lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
        )
        progress.load()
        collector = Collector(
            SimpleNamespace(
                config={},
                sleep=lambda *_args: None,
                info_set=lambda *_args: None,
            ),
            SimpleNamespace(
                capture=lambda: next(frames),
                click_client=lambda *args, **kwargs: clicks.append((args, kwargs)),
            ),
            SimpleNamespace(),
            progress,
        )
        collector.action_icons = SimpleNamespace(detect=lambda *_args: next(detections))
        counts = iter(((0, 21), (1, 21)))
        collector._read_count_window = lambda _action, detection, **_kwargs: (
            count_detections.append(detection) or next(counts)
        )
        collector._read_action_feedback = lambda _action: SkillFeedbackObservation(
            "吸收周围的拾取物",
            "success",
            1.0,
        )

        result = collector._use_action(
            ABSORB_ACTION,
            card_id="Q_sp1",
            map_role=CollectionMapRole.MAIN_AREA,
        )

        self.assertTrue(result.completed)
        self.assertEqual(
            [before.state, after.state],
            [value.state for value in count_detections],
        )
        self.assertTrue(all(value.stable for value in count_detections))
        self.assertEqual(
            [before.match.center, after.match.center],
            [value.match.center for value in count_detections],
        )
        self.assertEqual(
            (before.match.center, before_frame.shape, 0.0),
            (clicks[0][0][0], clicks[0][0][1], clicks[0][1]["after_sleep"]),
        )

    def test_absorb_and_summon_count_rois_use_manual_fixed_regions(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        calls = []
        detection = ActionIconDetection(
            ActionIconState.AVAILABLE,
            MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
            0.95,
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, name, **kwargs: calls.append((name, kwargs)) or "7/21",
        )
        collector = Collector(
            SimpleNamespace(config={}, sleep=lambda *_args: None),
            vision,
            SimpleNamespace(),
            SimpleNamespace(),
        )

        for action in (ABSORB_ACTION, SUMMON_ACTION):
            with self.subTest(action=action.name):
                self.assertEqual((7, 21), collector._read_count(action, detection))

        self.assertEqual(2, len(calls))
        for name, kwargs in calls:
            self.assertIn(name, {"吸收次数", "召集次数"})
            self.assertNotIn("roi", kwargs)
            self.assertEqual(1080, kwargs["target_height"])
            self.assertEqual(
                next(
                    action.fixed_count_relative_roi
                    for action in (ABSORB_ACTION, SUMMON_ACTION)
                    if f"{action.name}次数" == name
                ),
                kwargs["relative_roi"],
            )
            self.assertEqual(ocr_count.LOOKS[0].scale, kwargs["ocr_scale"])

    def test_battle_arrival_checks_search_countdown_without_matching_search_icon(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        ocr_calls = []
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, name, **kwargs: ocr_calls.append((name, kwargs)) or "44",
        )
        collector = Collector(
            SimpleNamespace(
                config={},
                sleep=lambda *_args: None,
                log_warning=lambda *_args: None,
            ),
            vision,
            SimpleNamespace(),
            SimpleNamespace(),
        )
        collector.action_icons = SimpleNamespace(
            detect=lambda *_args: self.fail(
                "active search must not be template-matched after map travel"
            )
        )
        session = SearchCountdownSession((0.4, 0.5, 0.6, 0.7), 45)

        self.assertTrue(collector._verify_search_countdown(session))
        self.assertEqual(
            [
                (
                    "战斗区域1探查倒计时",
                    {
                        "relative_roi": session.relative_roi,
                        "target_height": 1080,
                        "ocr_scale": SKILL_OCR_UPSCALE,
                    },
                )
            ],
            ocr_calls,
        )

    @BAR_SHOWN
    def test_skill_menu_recovery_clicks_group_one_and_retries_icon_detection(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        group_clicks = []
        action_clicks = []
        missing = ActionIconDetection(
            ActionIconState.ABSENT,
            MatchResult(-1.0, (0, 0), (0, 0)),
        )
        available = ActionIconDetection(
            ActionIconState.AVAILABLE,
            MatchResult(0.98, (1550, 969), (52, 44), 0.95, 0.92),
            1.0,
        )
        detections = iter(
            [missing] * 6 + [available, available, available, available, missing]
        )
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: group_clicks.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, name, **kwargs: (
                "在44秒内确认隐藏物品的位置。" if name == "探查执行反馈" else "44"
            ),
            click_client=lambda center, shape, after_sleep=0: action_clicks.append(
                (center, shape, after_sleep)
            ),
            match=lambda *_args: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        collector = Collector(task, vision, SimpleNamespace(), SimpleNamespace())
        collector.action_icons = SimpleNamespace(detect=lambda *_args: next(detections))

        result = collector._start_search(map_role=CollectionMapRole.MAIN_AREA)

        self.assertIsInstance(result, SearchCountdownSession)
        self.assertEqual(
            [
                (
                    # group 1 is on screen (BAR_SHOWN) and shows nothing: 2 first
                    SKILL_GROUP_RELATIVE_POINTS[2][0],
                    SKILL_GROUP_RELATIVE_POINTS[2][1],
                    SKILL_GROUP_SWITCH_SETTLE_SECONDS,
                )
            ],
            group_clicks,
        )
        self.assertEqual([(available.match.center, frame.shape, 0.0)], action_clicks)
        self.assertEqual(SEARCH_COUNTDOWN_RELATIVE_ROI, result.relative_roi)

    @BAR_SHOWN
    def test_skill_menu_recovery_fails_after_one_group_one_click(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        missing = ActionIconDetection(
            ActionIconState.ABSENT,
            MatchResult(-1.0, (0, 0), (0, 0)),
        )
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
        )
        collector = Collector(task, vision, SimpleNamespace(), SimpleNamespace())
        collector.action_icons = SimpleNamespace(detect=lambda *_args: missing)

        result = collector._use_actions(
            (ABSORB_ACTION,),
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        # All three groups are tried, the one on screen (1) last.
        self.assertEqual(
            [
                (*SKILL_GROUP_RELATIVE_POINTS[group], SKILL_GROUP_SWITCH_SETTLE_SECONDS)
                for group in (2, 3, 1)
            ],
            clicks,
        )
        self.assertFalse(result.completed)
        self.assertIn("未确认采集技能栏", result.message)

    @BAR_SHOWN
    def test_skill_menu_stops_on_the_group_that_shows_the_icons(self):
        # User 2026-09-28: cooking in group 1, 探查/吸收/召集/压制 in group 2.
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        group = [1]
        found = ActionIconDetection(
            ActionIconState.AVAILABLE,
            MatchResult(0.99, (1500, 900), (60, 60)),
        )
        missing = ActionIconDetection(
            ActionIconState.ABSENT,
            MatchResult(-1.0, (0, 0), (0, 0)),
        )
        points = {point: number for number, point in SKILL_GROUP_RELATIVE_POINTS.items()}

        def click(x, y, after_sleep=0):
            clicks.append((x, y))
            group[0] = points[(x, y)]

        task = SimpleNamespace(
            config={},
            operate_click=click,
            sleep=lambda *_args: None,
            log_warning=lambda *_a: None,
            info_set=lambda *_args: None,
        )
        collector = Collector(
            task,
            SimpleNamespace(capture=lambda: frame),
            SimpleNamespace(),
            SimpleNamespace(),
        )
        collector.action_icons = SimpleNamespace(
            detect=lambda *_args: found if group[0] == 2 else missing
        )
        self.assertTrue(collector._open_skill_menu((ABSORB_ICON,), allow_group_one_recovery=True))
        # Group 1 is on screen and shows nothing: straight to group 2
        # (Leo 2026-10-13 「切我的工具列」: no flip through group 1).
        self.assertEqual([SKILL_GROUP_RELATIVE_POINTS[2]], clicks)

    @BAR_SHOWN
    def test_start_search_recovers_group_one_once_then_fails(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        missing = ActionIconDetection(
            ActionIconState.ABSENT,
            MatchResult(-1.0, (0, 0), (0, 0)),
        )
        task = SimpleNamespace(
            config={},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        collector = Collector(
            task,
            SimpleNamespace(capture=lambda: frame),
            SimpleNamespace(),
            SimpleNamespace(),
        )
        collector.action_icons = SimpleNamespace(detect=lambda *_args: missing)

        result = collector._start_search(map_role=CollectionMapRole.MAIN_AREA)

        self.assertFalse(result.completed)
        self.assertEqual(len(SKILL_GROUP_RELATIVE_POINTS), len(clicks))
        self.assertIn("未确认安全区技能栏", result.message)

    def test_missing_action_after_menu_confirmation_never_uses_fixed_action_point(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        missing = ActionIconDetection(
            ActionIconState.ABSENT,
            MatchResult(-1.0, (0, 0), (0, 0)),
        )
        task = SimpleNamespace(
            config={},
            operate_click=lambda *args, **kwargs: clicks.append((args, kwargs)),
            sleep=lambda *_args: None,
            log_warning=lambda *_args: None,
            info_set=lambda *_args: None,
        )
        progress = ProgressStore(
            Path(tempfile.mkdtemp(prefix="ok-bd2-missing-action-")) / "progress.json",
            lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
        )
        progress.load()
        collector = Collector(
            task,
            SimpleNamespace(capture=lambda: frame),
            SimpleNamespace(),
            progress,
        )
        collector._open_skill_menu = lambda *_args, **_kwargs: True
        collector.action_icons = SimpleNamespace(detect=lambda *_args: missing)

        result = collector._use_action(
            ABSORB_ACTION,
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )

        self.assertFalse(result.completed)
        self.assertIn("未识别到吸收图标", result.message)
        self.assertEqual([], clicks)

    def test_fixed_count_ocr_reads_again_inside_a_border(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        calls = []
        vision = SimpleNamespace(
            capture=lambda: frame,
            ocr_text=lambda _frame, name, **kwargs: (
                calls.append((name, kwargs))
                or ("1/21" if kwargs.get("bordered") else "2")
            ),
        )
        collector = Collector(
            SimpleNamespace(config={}, sleep=lambda *_args: None),
            vision,
            SimpleNamespace(),
            SimpleNamespace(),
        )

        self.assertEqual((1, 21), collector._read_count(ABSORB_ACTION))
        self.assertEqual(
            [(3.0, False), (3.0, True)],
            [(kwargs["ocr_scale"], bool(kwargs.get("bordered"))) for _name, kwargs in calls],
        )

    def test_formal_bare_post_count_keeps_local_success_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            clicks = []
            detections = iter(
                (
                    ActionIconDetection(
                        ActionIconState.AVAILABLE,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.95,
                    ),
                    ActionIconDetection(
                        ActionIconState.AVAILABLE,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.95,
                    ),
                    ActionIconDetection(
                        ActionIconState.USED,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.65,
                    ),
                    ActionIconDetection(
                        ActionIconState.USED,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.65,
                    ),
                    ActionIconDetection(
                        ActionIconState.USED,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.65,
                    ),
                )
            )
            task = SimpleNamespace(
                config={},
                sleep=lambda *_args: None,
                info_set=lambda *_args: None,
                log_warning=lambda *_args: None,
            )
            vision = SimpleNamespace(
                capture=lambda: frame,
                click_client=lambda center, _shape, after_sleep=0: clicks.append(center),
            )
            collector = Collector(task, vision, SimpleNamespace(), progress)
            collector.action_icons = SimpleNamespace(detect=lambda *_args: next(detections))
            count_values = iter(((0, 21), None))
            collector._read_count_window = lambda action, detection, **_kwargs: next(count_values)
            collector._read_action_feedback = lambda _action: SkillFeedbackObservation(
                "吸收周围的拾取物", "success", 1.0
            )

            result = collector._use_action(
                ABSORB_ACTION,
                card_id="Q_sp1",
                map_role=CollectionMapRole.MAIN_AREA,
            )

            self.assertTrue(result.completed)
            self.assertEqual(("吸收",), result.pending_actions)
            self.assertEqual(1, len(clicks))
            record = progress.get_action_record("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收")
            self.assertEqual(CollectionActionState.PENDING.value, record["state"])

    def test_formal_single_outlier_post_count_stays_pending_without_absolute_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            clicks = []
            detections = iter(
                (
                    ActionIconDetection(
                        ActionIconState.AVAILABLE,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.95,
                    ),
                    ActionIconDetection(
                        ActionIconState.AVAILABLE,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.95,
                    ),
                    ActionIconDetection(
                        ActionIconState.USED,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.65,
                    ),
                    ActionIconDetection(
                        ActionIconState.USED,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.65,
                    ),
                    ActionIconDetection(
                        ActionIconState.USED,
                        MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                        0.65,
                    ),
                )
            )
            collector = Collector(
                SimpleNamespace(
                    config={},
                    sleep=lambda *_args: None,
                    info_set=lambda *_args: None,
                ),
                SimpleNamespace(
                    capture=lambda: frame,
                    click_client=lambda center, _shape, after_sleep=0: clicks.append(center),
                ),
                SimpleNamespace(),
                progress,
            )
            collector.action_icons = SimpleNamespace(detect=lambda *_args: next(detections))
            count_values = iter(((0, 21), (17, 21)))
            collector._read_count_window = lambda _action, _detection=None, **_kwargs: next(
                count_values
            )
            collector._read_action_feedback = lambda _action: SkillFeedbackObservation(
                "吸收周围的拾取物", "success", 1.0
            )

            result = collector._use_action(
                ABSORB_ACTION,
                card_id="Q_sp1",
                map_role=CollectionMapRole.MAIN_AREA,
            )

            self.assertTrue(result.completed)
            self.assertEqual(1, len(clicks))
            self.assertEqual({}, progress.state.observed_counts)
            self.assertFalse(progress.state.depleted_today)
            self.assertEqual(1, progress.effective_used("吸收"))
            record = progress.get_action_record("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收")
            self.assertEqual(CollectionActionState.PENDING.value, record["state"])
            self.assertEqual([17, 21], record["observed"])

    def test_formal_used_icon_completes_without_click_or_count_ocr(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            clicks = []
            used = ActionIconDetection(
                ActionIconState.USED,
                MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                0.65,
            )
            collector = Collector(
                SimpleNamespace(
                    config={},
                    info_set=lambda *_args: None,
                    sleep=lambda *_args: None,
                ),
                SimpleNamespace(
                    capture=lambda: frame,
                    click_client=lambda *args, **kwargs: clicks.append((args, kwargs)),
                ),
                SimpleNamespace(),
                progress,
            )
            collector.action_icons = SimpleNamespace(detect=lambda *_args: used)
            # 探查 is running, so the grey icon means "done here this week".
            collector._search_running = lambda: True
            collector._read_count_window = lambda *_args, **_kwargs: self.fail(
                "pre-existing USED must not read or click"
            )

            result = collector._use_action(
                ABSORB_ACTION,
                card_id="Q_sp1",
                map_role=CollectionMapRole.MAIN_AREA,
            )

            self.assertTrue(result.completed)
            self.assertEqual([], clicks)
            self.assertEqual(
                CollectionActionState.SETTLED.value,
                progress.get_action_record("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收")["state"],
            )

    def test_restart_armed_intent_does_not_block_a_bright_icon(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", baseline=(0, 21))
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            available = ActionIconDetection(
                ActionIconState.AVAILABLE,
                MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                0.95,
            )
            clicks = []
            collector = Collector(
                SimpleNamespace(
                    config={},
                    info_set=lambda *_args: None,
                    sleep=lambda *_args: None,
                ),
                SimpleNamespace(
                    capture=lambda: frame,
                    click_client=lambda *args, **kwargs: clicks.append((args, kwargs)),
                    # The count cannot be read.
                    ocr_text=lambda *_a, **_k: "",
                ),
                SimpleNamespace(),
                progress,
            )
            collector.action_icons = SimpleNamespace(detect=lambda *_args: available)

            result = collector._use_action(
                ABSORB_ACTION,
                card_id="Q_sp1",
                map_role=CollectionMapRole.MAIN_AREA,
            )

            # Leo 2026-10-07: a bright icon is not blocked by an old record,
            # and since 2026-10-28 not by an unread count either: pressed,
            # and with the icon still bright and no toast it stays unproven.
            self.assertFalse(result.completed)
            self.assertFalse(result.depleted)
            self.assertNotIn("禁止重复点击", result.message)
            self.assertIn("按之前没读到次数", result.message)
            self.assertEqual(1, len(clicks))

    def test_battle_two_bright_checkpoint_settles_battle_one_before_click(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action(
                "Q_sp1",
                CollectionMapRole.BATTLE_AREA_1,
                "吸收",
                baseline=(0, 21),
            )
            progress.mark_action_local_done(
                "Q_sp1",
                CollectionMapRole.BATTLE_AREA_1,
                "吸收",
                pending=True,
            )
            _seed_battle_supplements(
                progress,
                "Q_sp1",
                CollectionMapRole.BATTLE_AREA_1,
            )
            progress.mark_target("Q_sp1", CollectionMapRole.BATTLE_AREA_1.value)

            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            available = ActionIconDetection(
                ActionIconState.AVAILABLE,
                MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                0.95,
            )
            used = ActionIconDetection(
                ActionIconState.USED,
                MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                0.65,
            )
            detections = iter((available, available, used, used))
            clicks = []
            collector = Collector(
                SimpleNamespace(
                    config={},
                    info_set=lambda *_args: None,
                    sleep=lambda *_args: None,
                ),
                SimpleNamespace(
                    capture=lambda: frame,
                    click_client=lambda center, _shape, after_sleep=0: clicks.append(center),
                ),
                SimpleNamespace(),
                progress,
            )
            collector.action_icons = SimpleNamespace(detect=lambda *_args: next(detections))
            count_values = iter(((1, 21), (2, 21)))

            def read_count_window(_action, _detection=None, **_kwargs):
                collector._last_count_window_stable = True
                return next(count_values)

            collector._read_count_window = read_count_window
            collector._read_action_feedback = lambda _action: SkillFeedbackObservation(
                "吸收周围的拾取物", "success", 1.0
            )

            result = collector._use_action(
                ABSORB_ACTION,
                card_id="Q_sp1",
                map_role=CollectionMapRole.BATTLE_AREA_2,
            )

            self.assertTrue(result.completed)
            self.assertEqual(1, len(clicks))
            self.assertEqual(
                "settled",
                progress.get_action_record("Q_sp1", CollectionMapRole.BATTLE_AREA_1, "吸收")[
                    "state"
                ],
            )
            self.assertEqual(
                "settled",
                progress.get_action_record("Q_sp1", CollectionMapRole.BATTLE_AREA_2, "吸收")[
                    "state"
                ],
            )

    def test_battle_two_stable_observed_after_local_lower_bound_allows_new_click(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", baseline=(0, 21))
            progress.mark_action_local_done(
                "Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", pending=True
            )
            self.assertEqual(1, progress.reconcile_pending("吸收", (1, 21)))
            progress.mark_target("Q_sp1", CollectionMapRole.MAIN_AREA.value)

            progress.arm_action("Q_sp1", CollectionMapRole.BATTLE_AREA_1, "吸收", baseline=(1, 21))
            progress.mark_action_local_done(
                "Q_sp1", CollectionMapRole.BATTLE_AREA_1, "吸收", pending=True
            )
            _seed_battle_supplements(
                progress,
                "Q_sp1",
                CollectionMapRole.BATTLE_AREA_1,
            )
            progress.mark_target("Q_sp1", CollectionMapRole.BATTLE_AREA_1.value)
            self.assertEqual(2, progress.state.daily_absorbs)

            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            available = ActionIconDetection(
                ActionIconState.AVAILABLE,
                MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                0.95,
            )
            used = ActionIconDetection(
                ActionIconState.USED,
                MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                0.65,
            )
            detections = iter((available, available, used, used))
            clicks = []
            collector = Collector(
                SimpleNamespace(
                    config={},
                    info_set=lambda *_args: None,
                    sleep=lambda *_args: None,
                ),
                SimpleNamespace(
                    capture=lambda: frame,
                    click_client=lambda center, _shape, after_sleep=0: clicks.append(center),
                ),
                SimpleNamespace(),
                progress,
            )
            collector.action_icons = SimpleNamespace(detect=lambda *_args: next(detections))
            count_values = iter(((2, 21), (3, 21)))

            def stable_count_window(_action, _detection=None, **_kwargs):
                collector._last_count_window_stable = True
                return next(count_values)

            collector._read_count_window = stable_count_window
            collector._read_action_feedback = lambda _action: SkillFeedbackObservation(
                "吸收周围的拾取物", "success", 1.0
            )

            result = collector._use_action(
                ABSORB_ACTION,
                card_id="Q_sp1",
                map_role=CollectionMapRole.BATTLE_AREA_2,
            )

            self.assertTrue(result.completed)
            self.assertEqual(1, len(clicks))
            self.assertEqual(
                CollectionActionState.SETTLED.value,
                progress.get_action_record("Q_sp1", CollectionMapRole.BATTLE_AREA_1, "吸收")[
                    "state"
                ],
            )
            self.assertEqual(
                CollectionActionState.SETTLED.value,
                progress.get_action_record("Q_sp1", CollectionMapRole.BATTLE_AREA_2, "吸收")[
                    "state"
                ],
            )
            self.assertEqual((3, 21), progress.state.observed_counts["吸收"])

    def test_battle_one_pending_does_not_block_battle_two(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action(
                "Q_sp1",
                CollectionMapRole.BATTLE_AREA_1,
                "吸收",
                baseline=(0, 21),
            )
            progress.mark_action_local_done(
                "Q_sp1", CollectionMapRole.BATTLE_AREA_1, "吸收", pending=True
            )
            _seed_battle_supplements(
                progress,
                "Q_sp1",
                CollectionMapRole.BATTLE_AREA_1,
            )
            progress.mark_target("Q_sp1", CollectionMapRole.BATTLE_AREA_1.value)
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            available = ActionIconDetection(
                ActionIconState.AVAILABLE,
                MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                0.95,
            )
            clicks = []
            collector = Collector(
                SimpleNamespace(
                    config={},
                    info_set=lambda *_args: None,
                    sleep=lambda *_args: None,
                ),
                SimpleNamespace(
                    capture=lambda: frame,
                    click_client=lambda *args, **kwargs: clicks.append((args, kwargs)),
                    ocr_text=lambda *_a, **_k: "",
                ),
                SimpleNamespace(),
                progress,
            )
            collector.action_icons = SimpleNamespace(detect=lambda *_args: available)
            collector._read_count_window = lambda *_args, **_kwargs: (0, 21)

            result = collector._use_action(
                ABSORB_ACTION,
                card_id="Q_sp1",
                map_role=CollectionMapRole.BATTLE_AREA_2,
            )

            # Leo 2026-10-07: an earlier map's unsettled count never holds a
            # pressable icon back (a used one greys out, no double charge).
            self.assertEqual(1, len(clicks))

    def test_unsteady_count_neither_settles_nor_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action(
                "Q_sp1",
                CollectionMapRole.BATTLE_AREA_1,
                "吸收",
                baseline=(0, 21),
            )
            progress.mark_action_local_done(
                "Q_sp1", CollectionMapRole.BATTLE_AREA_1, "吸收", pending=True
            )
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            available = ActionIconDetection(
                ActionIconState.AVAILABLE,
                MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                0.95,
            )
            clicks = []
            collector = Collector(
                SimpleNamespace(
                    config={},
                    info_set=lambda *_args: None,
                    sleep=lambda *_args: None,
                ),
                SimpleNamespace(
                    capture=lambda: frame,
                    click_client=lambda *args, **kwargs: clicks.append((args, kwargs)),
                    ocr_text=lambda *_a, **_k: "",
                ),
                SimpleNamespace(),
                progress,
            )
            collector.action_icons = SimpleNamespace(detect=lambda *_args: available)

            def single_checkpoint(_action, _detection=None, **_kwargs):
                collector._last_count_window_stable = False
                return (17, 21)

            collector._read_count_window = single_checkpoint

            result = collector._use_action(
                ABSORB_ACTION,
                card_id="Q_sp1",
                map_role=CollectionMapRole.BATTLE_AREA_2,
            )

            # An unsteady count tidies nothing up but no longer blocks.
            self.assertEqual(1, len(clicks))
            self.assertEqual({}, progress.state.observed_counts)
            self.assertEqual(1, progress.pending_count("吸收"))

    def test_previous_observed_delta_ignores_new_local_lower_bound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()

            progress.arm_action("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", baseline=(0, 21))
            progress.mark_action_local_done(
                "Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", pending=True
            )
            self.assertEqual(1, progress.reconcile_pending("吸收", (1, 21)))
            progress.mark_target("Q_sp1", CollectionMapRole.MAIN_AREA.value)

            progress.arm_action("Q_sp1", CollectionMapRole.BATTLE_AREA_1, "吸收", baseline=(1, 21))
            progress.mark_action_local_done(
                "Q_sp1", CollectionMapRole.BATTLE_AREA_1, "吸收", pending=True
            )
            _seed_battle_supplements(
                progress,
                "Q_sp1",
                CollectionMapRole.BATTLE_AREA_1,
            )
            progress.mark_target("Q_sp1", CollectionMapRole.BATTLE_AREA_1.value)

            self.assertEqual(2, progress.state.daily_absorbs)
            self.assertEqual(1, progress.reconcile_pending("吸收", (2, 21)))
            self.assertEqual(0, progress.pending_count("吸收"))
            self.assertEqual((2, 21), progress.state.observed_counts["吸收"])

    def test_click_exception_leaves_formal_action_armed_not_clicked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            available = ActionIconDetection(
                ActionIconState.AVAILABLE,
                MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92),
                0.95,
            )
            collector = Collector(
                SimpleNamespace(
                    config={},
                    info_set=lambda *_args: None,
                    sleep=lambda *_args: None,
                ),
                SimpleNamespace(
                    capture=lambda: frame,
                    click_client=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        RuntimeError("click interrupted")
                    ),
                ),
                SimpleNamespace(),
                progress,
            )
            collector.action_icons = SimpleNamespace(detect=lambda *_args: available)
            collector._read_count_window = lambda *_args, **_kwargs: (0, 21)

            with self.assertRaisesRegex(RuntimeError, "click interrupted"):
                collector._use_action(
                    ABSORB_ACTION,
                    card_id="Q_sp1",
                    map_role=CollectionMapRole.MAIN_AREA,
                )

            self.assertEqual(
                "armed",
                progress.get_action_record("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收")["state"],
            )


class AbsorbUsedUpTest(unittest.TestCase):
    """Leo 2026-10-05 「不開新章」: 吸收 at its limit -> the map is not started.
    Since 2026-10-28 the limit counts only with the game agreeing: 吸收 grey
    with 探查 running (tests/test_map_count_never_blocks.py)."""

    def _collector(self, count, record=None):
        collector = object.__new__(Collector)
        collector.progress = SimpleNamespace(get_action_record=lambda *_a: record)
        collector._open_skill_menu = lambda *a, **k: True
        collector._status = lambda *_a: None
        collector._search_running = lambda: True
        collector._detect_action_icon = lambda icon, **_k: (
            None,
            ActionIconDetection(
                ActionIconState.USED,
                MatchResult(0.98, (100, 100), (40, 40), 0.70, 0.90),
                0.65,
                stable=True,
                sample_count=2,
            ),
        )
        reads = []

        def read(action, *_a, **_k):
            reads.append(action.name)
            collector._last_count_window_stable = count is not None
            return count

        collector._read_count_window = read
        # The second way of reading (inside a border) agrees.
        collector._read_count_again = lambda _action: count
        return collector, reads

    def test_limit_reached_stops_the_map_as_depleted(self):
        collector, reads = self._collector((21, 21))
        result = collector._absorb_used_up(
            card_id="Q_sp1", map_role=CollectionMapRole.BATTLE_AREA_2
        )
        self.assertFalse(result.completed)
        self.assertTrue(result.depleted)
        self.assertIn("21/21", result.message)
        self.assertEqual(["吸收"], reads)

    def test_below_limit_or_unreadable_goes_on(self):
        for count in ((20, 21), None):
            with self.subTest(count=count):
                collector, _reads = self._collector(count)
                self.assertIsNone(
                    collector._absorb_used_up(
                        card_id="Q_sp1", map_role=CollectionMapRole.BATTLE_AREA_1
                    )
                )

    def test_map_whose_absorb_is_already_done_is_not_checked(self):
        collector, reads = self._collector((21, 21), record={"state": "local_done"})
        self.assertIsNone(
            collector._absorb_used_up(card_id="Q_sp1", map_role=CollectionMapRole.BATTLE_AREA_1)
        )
        self.assertEqual([], reads)


class EnsureSearchTest(unittest.TestCase):
    """Leo 2026-10-06: 探查 is decided by text.  A countdown means it runs;
    otherwise it is pressed (icon or fixed slot) and counts only when its
    toast or countdown proves it started."""

    def _collector(self, start_result):
        collector = object.__new__(Collector)
        collector.task = SimpleNamespace(info_set=lambda *a: None)
        collector._search_running = lambda: False
        collector._open_skill_menu = lambda *a, **k: True
        collector._status = lambda *a: None
        collector.pressed = []
        collector._start_search = lambda **k: collector.pressed.append(k) or start_result
        return collector

    def test_running_countdown_skips_everything(self):
        collector = self._collector("pressed")
        collector._search_running = lambda: True
        self.assertIsNone(collector._ensure_search(map_role=CollectionMapRole.MAIN_AREA))
        self.assertEqual([], collector.pressed)

    def test_no_countdown_presses_with_the_slot_as_fallback(self):
        collector = self._collector("pressed")
        self.assertEqual("pressed", collector._ensure_search(map_role=CollectionMapRole.MAIN_AREA))
        self.assertTrue(collector.pressed[0]["slot_fallback"])

    def test_an_unproven_search_is_pressed_again_then_stops_before_absorb(self):
        # Leo 2026-10-07: no 吸收 without a 探查.
        collector = self._collector(SkillExecutionResult(False, message="未确认倒计时"))
        collector.task.sleep = lambda *_a: None
        result = collector._ensure_search(map_role=CollectionMapRole.BATTLE_AREA_1)
        self.assertIsInstance(result, SkillExecutionResult)
        self.assertFalse(result.completed)
        self.assertEqual(2, len(collector.pressed))

    def test_a_late_countdown_counts_as_running(self):
        collector = self._collector(SkillExecutionResult(False, message="未确认倒计时"))
        collector.task.sleep = lambda *_a: None
        looks = iter([False, True])
        collector._search_running = lambda: next(looks)
        self.assertIsNone(collector._ensure_search(map_role=CollectionMapRole.MAIN_AREA))
        self.assertEqual(1, len(collector.pressed))


class SearchRunningTest(unittest.TestCase):
    """Leo 2026-10-19 第三章: 吸收 went first because digits misread over the
    idle 探查 slot counted as a running 探查."""

    def _collector(self, reads, icon_state):
        collector = object.__new__(Collector)
        texts = iter(reads)
        collector.sleeps = []
        collector.task = SimpleNamespace(
            sleep=collector.sleeps.append, log_info=lambda *_a: None
        )
        collector._status = lambda *a: None
        collector.vision = SimpleNamespace(
            capture=lambda: object(),
            ocr_text=lambda *_a, **_k: next(texts),
        )
        collector.action_icons = SimpleNamespace(
            detect=lambda *_a: ActionIconDetection(
                icon_state, MatchResult(0.98, (1, 1), (5, 5))
            )
        )
        return collector

    def test_no_digits_is_not_running(self):
        self.assertFalse(self._collector([""], ActionIconState.AVAILABLE)._search_running())

    def test_digits_over_a_covered_glyph_run_at_once(self):
        collector = self._collector(["231"], ActionIconState.ABSENT)
        self.assertTrue(collector._search_running())
        self.assertEqual([], collector.sleeps)

    def test_static_digits_over_the_idle_glyph_are_not_running(self):
        collector = self._collector(["0", "0"], ActionIconState.AVAILABLE)
        self.assertFalse(collector._search_running())
        collector = self._collector(["8", "8"], ActionIconState.AVAILABLE)
        self.assertFalse(collector._search_running())

    def test_ticking_digits_over_a_bright_glyph_still_run(self):
        collector = self._collector(["87", "86"], ActionIconState.AVAILABLE)
        self.assertTrue(collector._search_running())


class SlotSearchMenuTest(unittest.TestCase):
    """2K 2026-10-07 埃克夏城: the slot press must not demand the 探查 icon."""

    def test_slot_fallback_confirms_the_menu_by_absorb_only(self):
        from src.tasks.map_trade.collector_constants import ABSORB_ICON

        collector = object.__new__(Collector)
        asked = []
        collector._open_skill_menu = lambda icons, **k: asked.append(icons) or False
        result = collector._start_search(
            map_role=CollectionMapRole.MAIN_AREA, slot_fallback=True
        )
        self.assertFalse(result.completed)
        self.assertEqual([(ABSORB_ICON,)], asked)


class EarlierClickTest(unittest.TestCase):
    """2K 2026-10-07: a 吸收 that found nothing (0/21 stayed 0/21) blocked
    the map for the rest of the day."""

    def _collector(self, count):
        collector = object.__new__(Collector)
        collector._status = lambda *a: None
        voided = []
        collector.progress = SimpleNamespace(
            mark_action_void=lambda *a, **k: voided.append(a),
            mark_action_blocked=lambda *a, **k: None,
        )

        def read(action, detection=None, **_k):
            collector._last_count_window_stable = True
            return count

        collector._read_count_window = read
        return collector, voided

    def _detection(self, state):
        return ActionIconDetection(state, MatchResult(0.98, (1, 1), (5, 5)), stable=True)

    def test_unchanged_count_and_bright_icon_allow_another_press(self):
        collector, voided = self._collector((0, 21))
        result = collector._resume_pending_intent(
            ABSORB_ACTION,
            {"state": "blocked", "baseline": [0, 21]},
            self._detection(ActionIconState.AVAILABLE),
            card_id="Q_sp12",
            map_role=CollectionMapRole.MAIN_AREA,
        )
        self.assertIsNone(result)
        self.assertEqual(1, len(voided))


    def test_an_unread_icon_lets_the_old_press_go_instead_of_blocking(self):
        # Leo 2026-10-20 「以遊戲為準」: a 2560x1440 player had ch1-3, 5, 6 all
        # left 「上次按的技能今天确认不了，今天不再按这张图」.
        collector, voided = self._collector((3, 21))
        blocked = []
        collector.progress.mark_action_blocked = lambda *a, **k: blocked.append(a)
        result = collector._resume_pending_intent(
            SUMMON_ACTION,
            {"state": "blocked", "baseline": [3, 21]},
            self._detection(ActionIconState.ABSENT),
            card_id="Q_sp1",
            map_role=CollectionMapRole.BATTLE_AREA_1,
        )
        self.assertIsNone(result)
        self.assertEqual(1, len(voided))
        self.assertEqual([], blocked)



class GameIconOverRecordTest(unittest.TestCase):
    """Leo 2026-10-20 「以遊戲紀錄為主」: a record calling a skill done never
    keeps a press from a skill the game still shows bright."""

    def _prepare(self, state, *, second_pass=False):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 10, 20, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action("Q_sp7", CollectionMapRole.BATTLE_AREA_1, "召集", baseline=(5, 21))
            progress.mark_action_seen_done("Q_sp7", CollectionMapRole.BATTLE_AREA_1, "召集")
            collector = object.__new__(Collector)
            collector.progress = progress
            collector._status = lambda *a: None
            collector._report_icon_detection = lambda *a: None
            collector._records_from_this_visit = second_pass
            detection = ActionIconDetection(state, MatchResult(0.98, (1, 1), (5, 5)), stable=True)
            collector._detect_fresh_action_icon = lambda *_a: (None, detection)
            collector._prepare_before_click = lambda *_a, **_k: ((5, 21), None)
            early, prepared = collector._prepare_action(
                SUMMON_ACTION, card_id="Q_sp7", map_role=CollectionMapRole.BATTLE_AREA_1
            )
            record = progress.get_action_record("Q_sp7", CollectionMapRole.BATTLE_AREA_1, "召集")
        return early, prepared, record

    def test_a_bright_icon_is_pressed_although_the_record_says_done(self):
        early, prepared, record = self._prepare(ActionIconState.AVAILABLE)
        self.assertIsNone(early)
        self.assertIsNotNone(prepared)
        self.assertEqual("void", record["state"])

    def test_a_record_stands_when_the_icon_is_not_bright(self):
        early, prepared, record = self._prepare(ActionIconState.USED)
        self.assertTrue(early.completed)
        self.assertIsNone(prepared)

    def test_the_second_pass_on_the_same_map_keeps_what_it_just_recorded(self):
        early, _prepared, _record = self._prepare(ActionIconState.AVAILABLE, second_pass=True)
        self.assertTrue(early.completed)


class AlreadyDoneMapTest(unittest.TestCase):
    """Leo 2026-10-07 (two PCs, one account): "nothing to absorb" with an
    unchanged count means the map was already done, not a failure."""

    def _run(self, after):
        from src.tasks.map_trade.collector_constants import SkillFeedbackObservation

        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 10, 7, 9, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action("Q_sp12", CollectionMapRole.BATTLE_AREA_1, "吸收", baseline=(5, 21))
            progress.mark_action_clicked("Q_sp12", CollectionMapRole.BATTLE_AREA_1, "吸收")
            collector = object.__new__(Collector)
            collector.progress = progress
            collector._status = lambda *a: None

            def read(action, detection=None, **_k):
                collector._last_count_window_stable = True
                return after

            collector._read_count_window = read
            detection = ActionIconDetection(
                ActionIconState.AVAILABLE, MatchResult(0.98, (1, 1), (5, 5)), stable=True
            )
            result = collector._finish_after_click(
                ABSORB_ACTION,
                card_id="Q_sp12",
                map_role=CollectionMapRole.BATTLE_AREA_1,
                before=(5, 21),
                detection=detection,
                post_detection=detection,
                feedback=SkillFeedbackObservation(
                    "周围没有可以吸收的拾取物", "failure", 1.0
                ),
            )
            record = progress.get_action_record(
                "Q_sp12", CollectionMapRole.BATTLE_AREA_1, "吸收"
            )
            return result, record

    def test_nothing_to_absorb_and_same_count_is_done(self):
        result, record = self._run((5, 21))
        self.assertTrue(result.completed)
        self.assertFalse(record["pending"])

    def test_nothing_to_absorb_but_count_moved_stays_a_failure(self):
        result, _record = self._run((6, 21))
        self.assertFalse(result.completed)


class CountProvesPressTest(unittest.TestCase):
    """Player 2026-10-12 (Q_sp5 主城区, sand): 吸收 went 12/21 -> 13/21 while
    its icon still read bright and only 探查's toast showed; the run stopped
    as 「吸收执行证据不一致」."""

    def _run(self, after, stable=True, feedback_text="在180秒内确认隐藏物品的位置"):
        from src.tasks.map_trade.collector_constants import SkillFeedbackObservation

        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 10, 12, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action("Q_sp5", CollectionMapRole.MAIN_AREA, "吸收", baseline=(12, 21))
            progress.mark_action_clicked("Q_sp5", CollectionMapRole.MAIN_AREA, "吸收")
            collector = object.__new__(Collector)
            collector.progress = progress
            collector._status = lambda *a: None
            collector._note_missed_press = lambda *a, **k: False

            def read(action, detection=None, **_k):
                collector._last_count_window_stable = stable
                return after

            collector._read_count_window = read
            bright = ActionIconDetection(
                ActionIconState.AVAILABLE, MatchResult(0.98, (1, 1), (5, 5)), stable=True
            )
            result = collector._finish_after_click(
                ABSORB_ACTION,
                card_id="Q_sp5",
                map_role=CollectionMapRole.MAIN_AREA,
                before=(12, 21),
                detection=bright,
                post_detection=bright,
                feedback=SkillFeedbackObservation(feedback_text, None, 0.0),
            )
            record = progress.get_action_record("Q_sp5", CollectionMapRole.MAIN_AREA, "吸收")
            return result, record

    def test_a_steady_plus_one_proves_the_press_with_a_bright_icon(self):
        result, record = self._run((13, 21))
        self.assertTrue(result.completed)
        self.assertFalse(record["pending"])

    def test_an_unchanged_or_unsteady_count_still_proves_nothing(self):
        self.assertFalse(self._run((12, 21))[0].completed)
        self.assertFalse(self._run((14, 21))[0].completed)
        self.assertFalse(self._run((13, 21), stable=False)[0].completed)



class LowerCountMisreadTest(unittest.TestCase):
    """Player 2026-10-15 (1080p, 角色卡3 主城区): 吸收 16/21 read 7/21 after the
    press (17 without its leading 1) while the icon greyed; the card was
    skipped as 「吸收执行证据不一致」."""

    def _run(self, post_state, after=(7, 21)):
        from src.tasks.map_trade.collector_constants import SkillFeedbackObservation

        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 10, 15, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action("Q_sp3", CollectionMapRole.MAIN_AREA, "吸收", baseline=(16, 21))
            progress.mark_action_clicked("Q_sp3", CollectionMapRole.MAIN_AREA, "吸收")
            collector = object.__new__(Collector)
            collector.progress = progress
            collector._status = lambda *a: None
            collector._note_missed_press = lambda *a, **k: False

            def read(action, detection=None, **_k):
                collector._last_count_window_stable = True
                return after

            collector._read_count_window = read
            bright = ActionIconDetection(
                ActionIconState.AVAILABLE, MatchResult(0.98, (1, 1), (5, 5)), stable=True
            )
            post = ActionIconDetection(post_state, MatchResult(0.98, (1, 1), (5, 5)), stable=True)
            result = collector._finish_after_click(
                ABSORB_ACTION,
                card_id="Q_sp3",
                map_role=CollectionMapRole.MAIN_AREA,
                before=(16, 21),
                detection=bright,
                post_detection=post,
                feedback=SkillFeedbackObservation("在90秒内确认隐藏物品的位置。", None, 0.0),
            )
            record = progress.get_action_record("Q_sp3", CollectionMapRole.MAIN_AREA, "吸收")
            return result, record

    def test_lower_read_with_grey_icon_is_done_and_rechecked_later(self):
        result, record = self._run(ActionIconState.USED)
        self.assertTrue(result.completed)
        self.assertTrue(record["pending"])
        self.assertEqual(("吸收",), tuple(result.pending_actions))

    def test_icon_greyed_by_the_press_is_done_whatever_the_count_read(self):
        # Leo 2026-10-15: 「要以遊戲為主」.
        for after in (None, (16, 21)):
            result, record = self._run(ActionIconState.USED, after=after)
            self.assertTrue(result.completed, after)
            self.assertTrue(record["pending"], after)

    def test_lower_read_with_bright_icon_still_proves_nothing(self):
        result, _record = self._run(ActionIconState.AVAILABLE)
        self.assertFalse(result.completed)


class SuccessToastIconUnreadTest(unittest.TestCase):
    """Leo 2026-10-20 (v0.2.2, ch11 战斗区域1): 吸收 showed its success toast
    「吸收周围的拾取物」 but its icon read "absent" right after the press and
    the count did not read; the card was skipped as 「吸收执行证据不一致」."""

    def _run(self, post_state, feedback, after=None):
        from src.tasks.map_trade.collector_constants import SkillFeedbackObservation

        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 10, 20, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            role = CollectionMapRole.BATTLE_AREA_1
            progress.arm_action("Q_sp11", role, "吸收", baseline=(10, 21))
            progress.mark_action_clicked("Q_sp11", role, "吸收")
            collector = object.__new__(Collector)
            collector.progress = progress
            collector._status = lambda *a: None
            collector._note_missed_press = lambda *a, **k: False

            def read(action, detection=None, **_k):
                collector._last_count_window_stable = after is not None
                return after

            collector._read_count_window = read
            bright = ActionIconDetection(
                ActionIconState.AVAILABLE, MatchResult(0.98, (1, 1), (5, 5)), stable=True
            )
            post = ActionIconDetection(post_state, MatchResult(0.0, (1, 1), (5, 5)))
            result = collector._finish_after_click(
                ABSORB_ACTION,
                card_id="Q_sp11",
                map_role=role,
                before=(10, 21),
                detection=bright,
                post_detection=post,
                feedback=SkillFeedbackObservation(*feedback),
            )
            return result, progress.get_action_record("Q_sp11", role, "吸收")

    SUCCESS = ("吸收周围的拾取物。", "success", 1.0, "吸收周围的拾取物")

    def test_success_toast_with_unread_icon_is_done_and_count_checked_later(self):
        for state in (ActionIconState.ABSENT, ActionIconState.UNKNOWN):
            result, record = self._run(state, self.SUCCESS)
            self.assertTrue(result.completed, state)
            self.assertTrue(record["pending"], state)
            self.assertEqual(("吸收",), tuple(result.pending_actions))

    def test_still_bright_after_a_success_toast_is_not_done(self):
        result, _record = self._run(ActionIconState.AVAILABLE, self.SUCCESS)
        self.assertFalse(result.completed)

    def test_no_toast_and_unread_icon_is_not_done(self):
        result, _record = self._run(ActionIconState.ABSENT, ("", None, 0.0))
        self.assertFalse(result.completed)

    def test_failure_toast_is_never_done(self):
        result, _record = self._run(
            ActionIconState.ABSENT,
            ("周围没有可以吸收的拾取物", "failure", 1.0, "周围没有可以吸收的拾取物"),
        )
        self.assertFalse(result.completed)


class GreyIconTest(unittest.TestCase):
    """Leo 2026-10-07: a grey icon on arrival is done here this week; an old
    unsettled count never stops the map (2K 埃克夏森林深处 stopped the run)."""

    def test_grey_icon_with_an_older_pending_record_is_done(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 10, 7, 9, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.arm_action("Q_sp12", CollectionMapRole.MAIN_AREA, "吸收", baseline=(0, 21))
            progress.mark_action_local_done(
                "Q_sp12", CollectionMapRole.MAIN_AREA, "吸收", pending=True
            )
            collector = object.__new__(Collector)
            collector.progress = progress
            collector._status = lambda *a: None
            used = ActionIconDetection(
                ActionIconState.USED, MatchResult(0.98, (1, 1), (5, 5)), stable=True
            )
            result = collector._resolve_preexisting_used(
                ABSORB_ACTION,
                used,
                card_id="Q_sp12",
                map_role=CollectionMapRole.BATTLE_AREA_2,
            )
            self.assertTrue(result.completed)
            record = progress.get_action_record("Q_sp12", CollectionMapRole.BATTLE_AREA_2, "吸收")
            self.assertEqual(CollectionActionState.SETTLED.value, record["state"])
            self.assertFalse(record["pending"])


class GreyNeedsSearchTest(unittest.TestCase):
    """Leo 2026-10-07: grey means done only while 探查 runs."""

    def _collector(self, running, start_result, second_state):
        collector = object.__new__(Collector)
        collector._search_running = lambda: running
        collector.searched = []
        collector._ensure_search = lambda **k: collector.searched.append(k) or start_result
        collector._detect_action_icon = lambda *a, **k: (
            None,
            ActionIconDetection(second_state, MatchResult(0.98, (1, 1), (5, 5)), stable=True),
        )
        return collector

    def _used(self):
        return ActionIconDetection(
            ActionIconState.USED, MatchResult(0.98, (1, 1), (5, 5)), stable=True
        )

    def test_search_running_keeps_grey(self):
        collector = self._collector(True, None, ActionIconState.AVAILABLE)
        _frame, detection, failure = collector._grey_with_search_on(
            ABSORB_ACTION, None, self._used(), CollectionMapRole.MAIN_AREA
        )
        self.assertIsNone(failure)
        self.assertIs(ActionIconState.USED, detection.state)
        self.assertEqual([], collector.searched)

    def test_no_search_turns_it_on_and_looks_again(self):
        session = SearchCountdownSession((0.1, 0.2, 0.3, 0.4), 239)
        collector = self._collector(False, session, ActionIconState.AVAILABLE)
        _frame, detection, failure = collector._grey_with_search_on(
            ABSORB_ACTION, None, self._used(), CollectionMapRole.MAIN_AREA
        )
        self.assertIsNone(failure)
        self.assertIs(ActionIconState.AVAILABLE, detection.state)

    def test_search_that_will_not_start_stops_the_map(self):
        collector = self._collector(False, SkillExecutionResult(False, message="x"), ActionIconState.USED)
        _frame, _detection, failure = collector._grey_with_search_on(
            ABSORB_ACTION, None, self._used(), CollectionMapRole.MAIN_AREA
        )
        self.assertIsNotNone(failure)


class GreyAbsorbSkipsMapTest(unittest.TestCase):
    """Leo 2026-10-07: a grey 吸收 on a battle map skips 召集 when 召集 is grey
    too; 压制 is always judged on its own icon (Leo 2026-10-15/16)."""

    def _grey_absorb_run(self, summon_grey: bool, card_id: str = "Q_sp12"):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 10, 7, 9, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            collector = object.__new__(Collector)
            collector.progress = progress
            collector._status = lambda *a: None
            collector.task = SimpleNamespace(sleep=lambda *a: None)
            prepared = []

            def prepare(action, **_k):
                prepared.append(action.name)
                if action.name == "吸收" or (action.name == "召集" and summon_grey):
                    used = ActionIconDetection(
                        ActionIconState.USED, MatchResult(0.98, (1, 1), (5, 5)), stable=True
                    )
                    return collector._resolve_preexisting_used(
                        action, used, card_id=card_id, map_role=CollectionMapRole.BATTLE_AREA_1
                    ), None
                # A bright icon: stop here with a failure so nothing is clicked.
                return SkillExecutionResult(False, message=f"{action.name}可按"), None

            collector._prepare_action = prepare
            results = collector._use_actions_pipelined(
                BATTLE_ACTIONS, card_id=card_id, map_role=CollectionMapRole.BATTLE_AREA_1
            )
            states = {
                name: (progress.get_action_record(card_id, CollectionMapRole.BATTLE_AREA_1, name) or {}).get("state")
                for name in ("召集", "压制")
            }
            return prepared, results, states

    def test_grey_absorb_and_grey_summon_still_judge_suppress(self):
        # Leo 2026-10-16: 戏水女王 / 角色卡7 battle areas skipped 压制.
        prepared, results, _states = self._grey_absorb_run(summon_grey=True)
        self.assertEqual(["吸收", "召集", "压制"], prepared)
        self.assertEqual("压制可按", results[-1].message)

    def test_splash_queen_battle_area_presses_suppress(self):
        prepared, results, _states = self._grey_absorb_run(summon_grey=True, card_id="Q_ep7")
        self.assertEqual(["吸收", "召集", "压制"], prepared)
        self.assertEqual("压制可按", results[-1].message)

    def test_grey_absorb_with_bright_summon_goes_on(self):
        # Splash Queen's battle map (live 4K 2026-10-09): 吸收 done by hand,
        # 召集 and 压制 still to do.
        prepared, results, _states = self._grey_absorb_run(summon_grey=False)
        self.assertEqual(["吸收", "召集"], prepared)
        self.assertFalse(results[-1].completed)
        self.assertEqual("召集可按", results[-1].message)

    def test_memory_edge_battle_area_still_presses_suppress(self):
        # Leo 2026-10-15 「活動卡帶記憶邊緣 戰鬥區 就算沒資源能吸收 也要按壓制」.
        prepared, results, _states = self._grey_absorb_run(summon_grey=True, card_id="Q_ep5")
        self.assertEqual(["吸收", "召集", "压制"], prepared)
        self.assertEqual("压制可按", results[-1].message)


class DimWaitTest(unittest.TestCase):
    """Leo 2026-10-15 「按技能前都要罰站很久」: a grey icon is waited out only
    right after 探查 was pressed, and once per bar."""

    def _collector(self, pressed_ago, waited=False):
        collector = object.__new__(Collector)
        collector._status = lambda *a: None
        collector.sleeps = []
        collector.task = SimpleNamespace(sleep=collector.sleeps.append)
        collector._detect_action_icon = lambda *a, **k: (
            None,
            ActionIconDetection(ActionIconState.USED, MatchResult(0.98, (1, 1), (5, 5)), stable=True),
        )
        collector._search_pressed_at = None if pressed_ago is None else monotonic() - pressed_ago
        collector._dim_waited_at = monotonic() if waited else None
        return collector

    def test_no_wait_when_search_was_already_running(self):
        collector = self._collector(None)
        collector._detect_fresh_action_icon(SUMMON_ACTION, None)
        self.assertEqual([], collector.sleeps)

    def test_waits_right_after_search_was_pressed(self):
        collector = self._collector(1.0)
        collector._detect_fresh_action_icon(SUMMON_ACTION, None)
        self.assertTrue(collector.sleeps)

    def test_the_second_icon_does_not_wait_again(self):
        collector = self._collector(1.0, waited=True)
        collector._detect_fresh_action_icon(SUPPRESS_ACTION, None)
        self.assertEqual([], collector.sleeps)


class SlotPressTest(unittest.TestCase):
    """A washed-out 吸收/召集/压制 icon: the fixed slot, decided by its count."""

    def _collector(self, count, stable=True):
        collector = object.__new__(Collector)
        collector.task = SimpleNamespace(info_set=lambda *a: None, sleep=lambda *a: None)
        collector._status = lambda *a: None
        collector.vision = SimpleNamespace(capture=lambda: np.zeros((1440, 2560, 3), np.uint8))

        def read(action, detection=None, **_k):
            collector._last_count_window_stable = stable
            return count

        collector._read_count_window = read
        return collector

    def test_readable_count_gives_the_slot(self):
        collector = self._collector((12, 21))
        frame, detection = collector._slot_detection(ABSORB_ACTION)
        self.assertIs(ActionIconState.AVAILABLE, detection.state)
        left, top, right, _bottom = ABSORB_ACTION.fixed_count_relative_roi
        self.assertAlmostEqual((left + right) / 2 * 2560, detection.match.center[0], delta=2)
        self.assertLess(detection.match.center[1], top * 1440)

    def test_unsteady_count_gives_nothing(self):
        self.assertIsNone(self._collector((12, 21), stable=False)._slot_detection(ABSORB_ACTION))
        self.assertIsNone(self._collector(None)._slot_detection(ABSORB_ACTION))

class CountSkipReasonTest(unittest.TestCase):
    """A count that could not be read says what was read (Leo 2026-10-24
    「錯誤要寫原因」); it was 「吸收次数 OCR 失败」."""

    @staticmethod
    def _collector(reads):
        texts = iter(reads)
        vision = SimpleNamespace(
            capture=lambda: np.zeros((1080, 1920, 3), dtype=np.uint8),
            ocr_text=lambda _frame, _name, **_kwargs: next(texts),
        )
        task = SimpleNamespace(config={}, sleep=lambda *_args: None, info_set=lambda *_args: None)
        return Collector(task, vision, SimpleNamespace(), SimpleNamespace())

    def test_what_was_read_is_in_the_reason(self):
        collector = self._collector(["V21", ""] * 3)
        self.assertIsNone(collector._read_count_window(SUMMON_ACTION))
        self.assertEqual("读到「V21」，看不出是多少", collector._count_failure_reason())

    def test_reads_that_disagree_are_named(self):
        collector = self._collector(["1/21", "2/21", "3/21"])
        self.assertIsNone(collector._read_count_window(SUMMON_ACTION))
        self.assertEqual(
            "几次读到的不一样：1/21、2/21、3/21", collector._count_failure_reason()
        )

    def test_a_steady_read_leaves_no_old_reason(self):
        collector = self._collector(["1/21", "2/21", "3/21", "4/21", "4/21"])
        self.assertIsNone(collector._read_count_window(SUMMON_ACTION))
        self.assertEqual((4, 21), collector._read_count_window(SUMMON_ACTION))
        self.assertEqual((), collector._last_count_samples)


class SlashlessCountTest(unittest.TestCase):
    """Live 2026-09-28: the 压制 count 7/70 was read as "7170"."""

    def test_slash_read_as_one_is_split_by_the_known_limit(self):
        from src.tasks.map_trade.vision import parse_used_limit

        self.assertEqual((7, 70), parse_used_limit("7170", 70))
        self.assertEqual((12, 70), parse_used_limit("12170", 70))
        self.assertEqual((11, 21), parse_used_limit("11121", 21))
        self.assertEqual((7, 70), parse_used_limit("7/70", 70))

    def test_a_five_digit_read_splits_only_one_way(self):
        """Live 4K 2026-10-14: 压制 11/75 was read as "11775".  With its
        slash read as 7 it can only be 11/75; a read that fits no count is
        still refused."""
        from src.tasks.map_trade.vision import parse_used_limit

        self.assertEqual((11, 75), parse_used_limit("11775", 75))
        self.assertIsNone(parse_used_limit("80/75", 75))

    def test_without_a_known_limit_or_a_fit_nothing_is_guessed(self):
        from src.tasks.map_trade.vision import parse_used_limit

        self.assertIsNone(parse_used_limit("7170"))
        self.assertIsNone(parse_used_limit("9999", 70))
        self.assertIsNone(parse_used_limit("70", 70))
        # Real 0/21 boxes read "121" (its 0 lost, 2026-10-28): not 1/21.
        self.assertIsNone(parse_used_limit("121", 21))

    def test_a_limit_read_steadily_this_run_splits_a_slashless_read(self):
        """2K 2026-10-15: 压制 read 0/75 … 6/75 steadily, but its default 80
        stayed, so "7175" failed and Q_cp7 was skipped."""
        from src.tasks.map_trade.collector_skills import SkillExecutionMixin
        from src.tasks.map_trade.vision import parse_used_limit

        skills = object.__new__(SkillExecutionMixin)
        skills.progress = SimpleNamespace(limit_of=lambda _name: 80)
        self.assertEqual(80, skills._known_limit("压制"))
        self.assertIsNone(parse_used_limit("7175", skills._known_limit("压制")))
        skills._remember_limit("压制", 75)
        self.assertEqual(75, skills._known_limit("压制"))
        self.assertEqual((7, 75), parse_used_limit("7175", skills._known_limit("压制")))


class CollectionRouteTest(unittest.TestCase):
    """User 2026-09-28: on the last map go backwards, otherwise start from
    the town; a failed move restarts via the hunting ground."""

    def _run(self, here, *, fail_first_advance=False, card_id="Q_sp6"):
        card = CARD_BY_ID[card_id]
        events = []
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 9, 28, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                log_warning=lambda *_a: None,
                info_set=lambda *_a: None,
            )
            failed = [fail_first_advance]

            def advance(card_id, current, target):
                events.append(("go", current.key, target.key))
                if failed[0]:
                    failed[0] = False
                    return NavigationResult(False, ScreenState.SANDBOX, "走不过去")
                return NavigationResult(True, ScreenState.SANDBOX)

            navigator = SimpleNamespace(
                select_collection_card=lambda card_id, **_k: CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.ENTERED,
                    NavigationResult(True, ScreenState.SANDBOX),
                ),
                current_collection_target=lambda _card: here,
                prepare_collection_main_area=lambda card_id, via_hunting_ground=False: (
                    events.append(("hunting" if via_hunting_ground else "town",))
                    or NavigationResult(True, ScreenState.SANDBOX)
                ),
                advance_collection_map=advance,
                open_story_quick_switcher_from_sandbox=lambda **_kwargs: NavigationResult(
                    True, ScreenState.CARD_MENU
                ),
                inspect_collection_card_completion=lambda _card_id: NavigationResult(
                    True, ScreenState.CARD_MENU
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            collector._absorb_used_up = lambda **_kwargs: None
            collector._ensure_search = lambda **_k: None

            def use_actions(actions, *, card_id, map_role):
                events.append(("collect", map_role.value))
                _seed_action_records(progress, card_id, map_role.value)
                return SkillExecutionResult(True)

            collector._use_actions = use_actions
            with patch("src.tasks.map_trade.collector.COLLECTABLE_CARDS", (card,)):
                collector.run()
        return events

    def test_on_the_last_map_the_route_goes_backwards(self):
        self.assertEqual(
            [
                ("collect", "battle_area_2"),
                ("go", "battle_area_2", "battle_area_1"),
                ("collect", "battle_area_1"),
                ("go", "battle_area_1", "main_area"),
                ("collect", "main_area"),
            ],
            self._run("battle_area_2"),
        )

    def test_card_three_leaves_its_last_map_for_the_town(self):
        # 禁闭室's exit does not react when the character stands on it
        # (live 4K 2026-10-04): 禁闭室 -> town (艾琳) -> 拍卖场.
        self.assertEqual(
            [
                ("collect", "battle_area_2"),
                ("go", "battle_area_2", "main_area"),
                ("collect", "main_area"),
                ("go", "main_area", "battle_area_1"),
                ("collect", "battle_area_1"),
            ],
            self._run("battle_area_2", card_id="Q_cp3"),
        )

    def test_in_the_middle_the_town_comes_first(self):
        # Leo 2026-09-29: anywhere but the town or the last map -> hunting
        # ground -> the town, then the forward route.
        self.assertEqual(
            [
                ("hunting",),
                ("collect", "main_area"),
                ("go", "main_area", "battle_area_1"),
                ("collect", "battle_area_1"),
                ("go", "battle_area_1", "battle_area_2"),
                ("collect", "battle_area_2"),
            ],
            self._run("battle_area_1"),
        )

    def test_a_failed_move_restarts_from_the_town_via_the_hunting_ground(self):
        events = self._run("main_area", fail_first_advance=True)
        self.assertEqual(("collect", "main_area"), events[0])
        self.assertEqual(("go", "main_area", "battle_area_1"), events[1])
        self.assertEqual(("hunting",), events[2])
        self.assertEqual(
            ["main_area", "battle_area_1", "battle_area_2"],
            [event[1] for event in events if event[0] == "collect"],
        )
