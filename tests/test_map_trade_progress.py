"""Map-trade progress tests (split from test_map_trade.py)."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.tasks.map_trade.collector_constants import UNSUPPORTED_COLLECTION_CARD_NUMBERS
from src.tasks.map_trade.models import (
    CARD_BY_ID,
    COLLECTABLE_CARDS,
    DAILY_ABSORB_LIMIT,
    DAILY_SUMMON_LIMIT,
    DAILY_SUPPRESS_LIMIT,
    DEFAULT_RECIPES,
    CollectionActionState,
    CollectionMapRole,
)
from src.tasks.map_trade.progress import (
    READ_FAILED_MESSAGE,
    SAVE_FAILED_MESSAGE,
    STATE_SCHEMA_VERSION,
    UTC_PLUS_8,
    VALID_FAVORITE_SHOP_IDS,
    ProgressFileError,
    ProgressStore,
    daily_cycle_key,
    weekly_cycle_key,
)
from tests.helpers import held_open
from tests.helpers.map_trade import _seed_action_records


class ProgressTest(unittest.TestCase):
    def test_weekly_collection_completion_uses_verified_supported_cards(self):
        from src.tasks.map_trade.progress import ProgressState

        state = ProgressState(weekly_key="2026-08-17", daily_key="2026-08-18")
        self.assertFalse(state.weekly_collection_complete)

        for card in COLLECTABLE_CARDS:
            if card.number in UNSUPPORTED_COLLECTION_CARD_NUMBERS:
                continue
            state.cards[card.card_id] = [target.key for target in card.targets]
            state.verified_cards.append(card.card_id)

        self.assertTrue(state.weekly_collection_complete)

        supported = next(
            card
            for card in COLLECTABLE_CARDS
            if card.number not in UNSUPPORTED_COLLECTION_CARD_NUMBERS
        )
        state.verified_cards.remove(supported.card_id)
        self.assertFalse(state.weekly_collection_complete)

    def test_daily_cycle_changes_at_four_am(self):
        before = datetime(2026, 7, 13, 7, 59, tzinfo=UTC_PLUS_8)
        after = datetime(2026, 7, 13, 8, 0, tzinfo=UTC_PLUS_8)

        self.assertEqual("2026-07-12", daily_cycle_key(before))
        self.assertEqual("2026-07-13", daily_cycle_key(after))

    def test_weekly_cycle_changes_monday_at_four_am(self):
        sunday = datetime(2026, 7, 12, 8, 0, tzinfo=UTC_PLUS_8)
        monday_before = datetime(2026, 7, 13, 7, 59, tzinfo=UTC_PLUS_8)
        monday_after = datetime(2026, 7, 13, 8, 0, tzinfo=UTC_PLUS_8)

        self.assertEqual("2026-07-06", weekly_cycle_key(sunday))
        self.assertEqual("2026-07-06", weekly_cycle_key(monday_before))
        self.assertEqual("2026-07-13", weekly_cycle_key(monday_after))

    def test_favorite_cartridge_progress_saves_each_card_and_requires_all(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"

            def now():
                return datetime(2026, 7, 13, 12, tzinfo=UTC_PLUS_8)

            store = ProgressStore(path, now)
            store.load()

            self.assertTrue(store.should_rebuild_favorites())
            self.assertTrue(store.mark_favorite_card("S1"))
            self.assertFalse(store.mark_favorite_card("S1"))
            self.assertTrue(store.favorite_card_complete("S1"))
            with self.assertRaisesRegex(RuntimeError, "rebuild is incomplete"):
                store.mark_favorites_built()

            resumed = ProgressStore(path, now)
            resumed.load()
            self.assertTrue(resumed.favorite_card_complete("S1"))
            for shop_id in sorted(VALID_FAVORITE_SHOP_IDS - {"S1"}):
                self.assertTrue(resumed.mark_favorite_card(shop_id))
            resumed.mark_favorites_built()
            self.assertFalse(resumed.should_rebuild_favorites())

            resumed.clear_favorite_cards()
            self.assertTrue(resumed.should_rebuild_favorites())
            self.assertEqual(set(), resumed.state.completed_favorite_cards)

    def test_reset_card_forgets_its_maps_and_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"

            def now():
                return datetime(2026, 7, 13, 12, tzinfo=UTC_PLUS_8)

            store = ProgressStore(path, now)
            store.load()
            store.state.cards["Q_sp6"] = ["main_area", "battle_area_1"]
            store.state.verified_cards.append("Q_sp6")
            store.save()
            store.reset_card("Q_sp6")
            resumed = ProgressStore(path, now)
            resumed.load()
            self.assertEqual(set(), resumed.state.completed_targets("Q_sp6"))
            self.assertNotIn("Q_sp6", resumed.state.verified_cards)

    def test_grey_on_arrival_summon_that_cost_nothing_is_settled_on_the_next_map(self):
        # Live 2K 2026-10-06: 第8章 盗贼据点 召集 grey, next map read 0/21.
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"

            def now():
                return datetime(2026, 10, 6, 11, tzinfo=UTC_PLUS_8)

            store = ProgressStore(path, now)
            store.load()
            self.assertTrue(
                store.mark_action_preexisting_used(
                    "Q_sp8", "battle_area_2", "召集", baseline=(0, 21)
                )
            )
            self.assertEqual(1, store.pending_count("召集"))
            # Same map: not settled (the count may still be catching up).
            self.assertEqual(
                0,
                store.settle_unconsumed_preexisting(
                    "召集", (0, 21), card_id="Q_sp8", map_role="battle_area_2"
                ),
            )
            # Another map, count still at the baseline: it cost nothing.
            self.assertEqual(
                1,
                store.settle_unconsumed_preexisting(
                    "召集", (0, 21), card_id="Q_sp8", map_role="battle_area_1"
                ),
            )
            self.assertEqual(0, store.pending_count("召集"))

    def test_grey_summon_followed_by_a_count_rise_is_not_settled_as_unconsumed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            store = ProgressStore(path, lambda: datetime(2026, 10, 6, 11, tzinfo=UTC_PLUS_8))
            store.load()
            store.mark_action_preexisting_used("Q_sp8", "battle_area_2", "召集", baseline=(0, 21))
            self.assertEqual(
                0,
                store.settle_unconsumed_preexisting(
                    "召集", (1, 21), card_id="Q_sp8", map_role="battle_area_1"
                ),
            )
            self.assertEqual(1, store.pending_count("召集"))

    def test_only_absorb_is_budgeted(self):
        # Leo 2026-10-06: 「以吸收为准」 – 召集/压制 pending never blocks.
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 10, 6, 11, tzinfo=UTC_PLUS_8),
            )
            store.load()
            store.mark_action_preexisting_used("Q_sp8", "battle_area_2", "召集", baseline=(21, 21))
            self.assertTrue(store.can_reserve_action("召集"))
            self.assertTrue(store.can_reserve_action("压制", 80))
            self.assertTrue(store.can_plan_collection(["a", "b", "c"]))
            self.assertFalse(store.can_plan_collection(["x"] * 22))

    def test_progress_saves_each_submap_and_stops_at_twenty_one(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            store = ProgressStore(path, lambda: datetime(2026, 7, 12, 12, tzinfo=UTC_PLUS_8))
            store.load()
            # The 22nd absorb would exceed the daily limit; keep its durable
            # records ready so the limit check, not the readiness check, fires.
            _seed_action_records(
                store,
                COLLECTABLE_CARDS[7].card_id,
                COLLECTABLE_CARDS[7].targets[0].key,
            )
            for card in COLLECTABLE_CARDS[:7]:
                for target in card.targets:
                    _seed_action_records(store, card.card_id, target.key)
                    self.assertTrue(store.mark_target(card.card_id, target.key))
                    self.assertTrue(path.exists())
                    self.assertFalse(path.with_suffix(".json.tmp").exists())
                self.assertTrue(store.mark_card_verified(card.card_id))

            self.assertEqual(DAILY_ABSORB_LIMIT, store.state.daily_absorbs)
            self.assertEqual(14, store.state.daily_summons)
            self.assertEqual(14, store.state.daily_suppressions)
            self.assertTrue(store.state.depleted_today)
            self.assertEqual(21, store.state.weekly_submap_count)
            self.assertTrue(
                all(store.state.card_verified(card.card_id) for card in COLLECTABLE_CARDS[:7])
            )
            next_card = COLLECTABLE_CARDS[7]
            self.assertFalse(
                store.mark_target(
                    next_card.card_id,
                    next_card.targets[0].key,
                )
            )
            self.assertTrue(store.state.depleted_today)

    def test_collection_skill_limits_match_three_two_two_per_card(self):
        self.assertEqual(21, DAILY_ABSORB_LIMIT)
        self.assertEqual(21, DAILY_SUMMON_LIMIT)
        # The usual 压制 limit (Leo 2026-10-09: x/80); the HUD's own wins.
        self.assertEqual(80, DAILY_SUPPRESS_LIMIT)

    def test_progress_rejects_pinned_collection_cards(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 7, 12, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()

            with self.assertRaisesRegex(ValueError, "invalid collection card"):
                store.mark_target("Q_sp20", CollectionMapRole.MAIN_AREA.value)

    def test_card_visual_verification_requires_all_three_map_roles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()
            _seed_action_records(
                store,
                "Q_sp1",
                CollectionMapRole.MAIN_AREA.value,
            )
            store.mark_target("Q_sp1", CollectionMapRole.MAIN_AREA.value)

            with self.assertRaisesRegex(RuntimeError, "targets are incomplete"):
                store.mark_card_verified("Q_sp1")

            self.assertFalse(store.state.card_verified("Q_sp1"))

    def test_daily_reset_preserves_weekly_submaps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = [datetime(2026, 7, 12, 7, 59, tzinfo=UTC_PLUS_8)]
            store = ProgressStore(path, lambda: now[0])
            store.load()
            for target in CARD_BY_ID["Q_sp1"].targets:
                _seed_action_records(store, "Q_sp1", target.key)
                store.mark_target("Q_sp1", target.key)
            store.mark_card_verified("Q_sp1")
            now[0] = datetime(2026, 7, 12, 8, 0, tzinfo=UTC_PLUS_8)

            state = ProgressStore(path, lambda: now[0]).load()

            self.assertEqual(
                {target.key for target in CARD_BY_ID["Q_sp1"].targets},
                state.completed_targets("Q_sp1"),
            )
            self.assertEqual(0, state.daily_submaps)
            self.assertEqual(0, state.daily_summons)
            self.assertEqual(0, state.daily_suppressions)
            self.assertFalse(state.depleted_today)
            self.assertTrue(state.card_verified("Q_sp1"))

    def test_weekly_reset_clears_submaps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            store = ProgressStore(path, lambda: datetime(2026, 7, 13, 7, 59, tzinfo=UTC_PLUS_8))
            store.load()
            _seed_action_records(
                store,
                "Q_sp1",
                CollectionMapRole.MAIN_AREA.value,
            )
            store.mark_target("Q_sp1", CollectionMapRole.MAIN_AREA.value)

            state = ProgressStore(
                path, lambda: datetime(2026, 7, 13, 8, 0, tzinfo=UTC_PLUS_8)
            ).load()

            self.assertEqual({}, state.cards)
            self.assertEqual(0, state.weekly_submap_count)
            self.assertEqual([], state.verified_cards)

    def test_all_seventeen_cards_make_fifty_one_weekly_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            now = [datetime(2026, 7, 13, 12, tzinfo=UTC_PLUS_8)]
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: now[0],
            )
            store.load()
            for card_index, card in enumerate(COLLECTABLE_CARDS):
                if card_index and card_index % 7 == 0:  # 7 cards a day
                    now[0] = now[0].replace(day=now[0].day + 1)
                    store.load()
                for target in card.targets:
                    _seed_action_records(store, card.card_id, target.key)
                    store.mark_target(card.card_id, target.key)

            # 19 story cards x 3 (chapter 18 with its safe area since Leo
            # 2026-10-10), then character cards 1-7 (2 + 3 + 3 + 3 + 2 + 3 +
            # 2), then event cards 1/2/3/5/7 (2 + 3 + 2 + 2 + 2).
            self.assertEqual(86, store.state.weekly_submap_count)

    def test_schema_one_collection_progress_resets_without_losing_other_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = datetime(2026, 7, 13, 12, tzinfo=UTC_PLUS_8)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "weekly_key": weekly_cycle_key(now),
                        "daily_key": daily_cycle_key(now),
                        "cards": {"Q_sp1": [0, 1]},
                        "daily_submaps": 5,
                        "depleted_today": False,
                        "favorite_week": weekly_cycle_key(now),
                        "favorite_cards": ["S1"],
                        "cooking_week": weekly_cycle_key(now),
                    }
                ),
                encoding="utf-8",
            )

            state = ProgressStore(path, lambda: now).load()
            saved = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual({}, state.cards)
            self.assertEqual(0, state.daily_submaps)
            self.assertEqual(0, state.daily_summons)
            self.assertEqual(0, state.daily_suppressions)
            self.assertEqual({"S1"}, state.completed_favorite_cards)
            self.assertEqual(weekly_cycle_key(now), state.cooking_week)
            self.assertEqual(set(DEFAULT_RECIPES), state.completed_cooking_recipes)
            self.assertEqual(STATE_SCHEMA_VERSION, saved["schema_version"])

    def test_schema_two_collection_progress_resets_for_role_specific_flow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "weekly_key": weekly_cycle_key(now),
                        "daily_key": daily_cycle_key(now),
                        "cards": {
                            "Q_sp1": [
                                "main_area",
                                "battle_area_1",
                                "battle_area_2",
                            ]
                        },
                        "daily_submaps": 3,
                        "depleted_today": False,
                        "favorite_week": weekly_cycle_key(now),
                        "favorite_cards": ["S1"],
                        "cooking_week": weekly_cycle_key(now),
                    }
                ),
                encoding="utf-8",
            )

            state = ProgressStore(path, lambda: now).load()

            self.assertEqual({}, state.cards)
            self.assertEqual(0, state.daily_absorbs)
            self.assertEqual([], state.verified_cards)
            self.assertEqual({"S1"}, state.completed_favorite_cards)

    def test_corrupt_file_recovers_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            path.write_text("{broken", encoding="utf-8")

            state = ProgressStore(path, lambda: datetime(2026, 7, 12, 12, tzinfo=UTC_PLUS_8)).load()

            self.assertEqual({}, state.cards)
            self.assertEqual(1, len(list(path.parent.glob("progress.corrupt-*.json"))))

    # The UI, the 桌面分身 tool, an antivirus or OneDrive can hold the file
    # open; Windows then refuses the read or the swap-in (WinError 5).
    def _saved(self, temp_dir):
        path = Path(temp_dir) / "progress.json"
        now = datetime(2026, 7, 12, 12, tzinfo=UTC_PLUS_8)
        store = ProgressStore(path, lambda: now)
        state = store.load()
        state.cooking_week = state.weekly_key
        state.cooking_recipes = [DEFAULT_RECIPES[0]]
        store.save()
        return path, now

    def test_save_while_the_file_is_held_open_a_moment_still_lands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path, now = self._saved(temp_dir)
            store = ProgressStore(path, lambda: now)
            store.load()
            with held_open.replace_refused(path, 2), held_open.no_wait():
                store.mark_depleted_today()
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["depleted_today"])

    def test_save_held_open_too_long_stops_with_a_clear_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path, now = self._saved(temp_dir)
            before = path.read_bytes()
            store = ProgressStore(path, lambda: now)
            store.load()
            with held_open.replace_refused(path), held_open.no_wait():
                with self.assertRaises(ProgressFileError) as caught:
                    store.mark_depleted_today()
            self.assertIsInstance(caught.exception, RuntimeError)  # Collector stops on it
            self.assertEqual(SAVE_FAILED_MESSAGE, str(caught.exception))
            self.assertEqual(before, path.read_bytes())
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_read_held_open_a_moment_is_tried_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path, now = self._saved(temp_dir)
            with held_open.read_refused(path, 2), held_open.no_wait():
                state = ProgressStore(path, lambda: now).load()
            self.assertEqual({DEFAULT_RECIPES[0]}, state.completed_cooking_recipes)

    def test_file_held_open_is_never_taken_for_broken_and_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path, now = self._saved(temp_dir)
            before = path.read_bytes()
            with held_open.read_refused(path), held_open.no_wait():
                with self.assertRaises(ProgressFileError) as caught:
                    ProgressStore(path, lambda: now).load()
            self.assertEqual(READ_FAILED_MESSAGE, str(caught.exception))
            # Not reset to a fresh week, and no 跑商 record lost.
            self.assertEqual(before, path.read_bytes())
            self.assertEqual([], list(path.parent.glob("progress.corrupt-*.json")))

    def test_schema_three_migrates_without_losing_collection_or_trade_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8)
            week = weekly_cycle_key(now)
            day = daily_cycle_key(now)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "weekly_key": week,
                        "daily_key": day,
                        "cards": {"Q_sp1": ["main_area"]},
                        "daily_submaps": 4,
                        "daily_summons": 2,
                        "daily_suppressions": 2,
                        "depleted_today": False,
                        "verified_cards": [],
                        "favorite_week": week,
                        "favorite_cards": ["S1"],
                        "cooking_week": week,
                    }
                ),
                encoding="utf-8",
            )

            state = ProgressStore(path, lambda: now).load()
            saved = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(STATE_SCHEMA_VERSION, saved["schema_version"])
            self.assertEqual({"main_area"}, state.completed_targets("Q_sp1"))
            self.assertEqual(
                (4, 2, 2),
                (state.daily_submaps, state.daily_summons, state.daily_suppressions),
            )
            self.assertEqual({"S1"}, state.completed_favorite_cards)
            self.assertEqual(week, state.cooking_week)
            self.assertEqual(set(DEFAULT_RECIPES), state.completed_cooking_recipes)

    def test_cooking_progress_is_per_recipe_and_partial_runs_resume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8)
            first, second = DEFAULT_RECIPES[:2]
            store = ProgressStore(path, lambda: now)
            store.load()

            self.assertTrue(store.should_cook(recipes=(first, second)))
            self.assertTrue(store.mark_cooking_recipe_complete(first))
            self.assertFalse(store.mark_cooking_recipe_complete(first))
            self.assertTrue(store.cooking_recipe_complete(first))
            self.assertFalse(store.cooking_recipe_complete(second))
            self.assertTrue(store.should_cook(recipes=(first, second)))
            self.assertFalse(store.should_cook(recipes=(first,)))
            self.assertTrue(store.should_cook(every_run=True, recipes=(first,)))

            resumed = ProgressStore(path, lambda: now)
            state = resumed.load()
            self.assertEqual({first}, state.completed_cooking_recipes)
            self.assertTrue(resumed.should_cook(recipes=(first, second)))
            self.assertTrue(resumed.mark_cooking_recipe_complete(second))
            self.assertFalse(resumed.should_cook(recipes=(first, second)))

    def test_schema_four_whole_week_cooking_marker_migrates_to_all_recipes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8)
            week = weekly_cycle_key(now)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 4,
                        "weekly_key": week,
                        "daily_key": daily_cycle_key(now),
                        "cooking_week": week,
                    }
                ),
                encoding="utf-8",
            )

            store = ProgressStore(path, lambda: now)
            state = store.load()
            saved = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(set(DEFAULT_RECIPES), state.completed_cooking_recipes)
            self.assertFalse(store.should_cook(recipes=DEFAULT_RECIPES))
            self.assertEqual(list(DEFAULT_RECIPES), saved["cooking_recipes"])
            self.assertEqual(STATE_SCHEMA_VERSION, saved["schema_version"])

    def test_weekly_rollover_clears_per_recipe_cooking_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = [datetime(2026, 8, 16, 12, tzinfo=UTC_PLUS_8)]
            store = ProgressStore(path, lambda: now[0])
            store.load()
            store.mark_cooking_recipe_complete(DEFAULT_RECIPES[0])

            now[0] = datetime(2026, 8, 17, 8, 0, tzinfo=UTC_PLUS_8)
            state = ProgressStore(path, lambda: now[0]).load()

            self.assertEqual(set(), state.completed_cooking_recipes)

    def test_action_ledger_is_idempotent_and_archives_at_daily_rollover(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = [datetime(2026, 8, 11, 7, 59, tzinfo=UTC_PLUS_8)]
            store = ProgressStore(path, lambda: now[0])
            store.load()

            self.assertTrue(store.arm_action("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收"))
            self.assertFalse(store.arm_action("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收"))
            store.mark_action_clicked("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收")
            store.mark_action_local_done("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", pending=True)
            self.assertEqual(1, store.pending_count())

            now[0] = datetime(2026, 8, 11, 8, 0, tzinfo=UTC_PLUS_8)
            resumed = ProgressStore(path, lambda: now[0])
            state = resumed.load()

            self.assertEqual({}, state.action_records)
            self.assertEqual(1, len(state.archived_action_records))
            self.assertEqual(
                CollectionActionState.ARCHIVED.value,
                next(iter(state.archived_action_records.values()))["state"],
            )
            self.assertEqual(0, resumed.pending_count())

    def test_pending_reconciliation_rejects_stale_or_wrong_denominator_and_settles_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()
            store.arm_action("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", baseline=(0, 21))
            store.mark_action_local_done("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", pending=True)

            self.assertEqual(0, store.reconcile_pending("吸收", (0, 21)))
            self.assertEqual(0, store.reconcile_pending("吸收", (1, 20)))
            self.assertEqual(1, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual(0, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual(0, store.pending_count())

    def test_preexisting_baseline_rejects_equal_invalid_and_lower_observations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()
            self.assertTrue(
                store.mark_action_preexisting_used("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收")
            )
            record = store.get_action_record("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收")
            self.assertEqual([0, 21], record["baseline"])
            self.assertEqual({}, store.state.observed_counts)
            self.assertEqual(0, store.reconcile_pending("吸收", (0, 21)))
            self.assertEqual(0, store.reconcile_pending("吸收", (1, 20)))
            self.assertEqual({}, store.state.observed_counts)
            self.assertEqual(1, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual((1, 21), store.state.observed_counts["吸收"])
            self.assertEqual(0, store.reconcile_pending("吸收", (0, 21)))
            self.assertEqual(0, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual(CollectionActionState.SETTLED.value, record["state"])

    def test_daily_limit_follows_the_hud(self):
        # Leo 2026-10-09: limits differ per player (a 召集 at 19, his 压制
        # at 80) and grow with game updates; the HUD decides.
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            store = ProgressStore(path, lambda: datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8))
            store.load()
            self.assertEqual(21, store.limit_of("召集"))
            store.reconcile_pending("召集", (3, 19))
            self.assertEqual(21, store.limit_of("召集"))  # one read is not enough
            store.reconcile_pending("召集", (3, 19))
            self.assertEqual(19, store.limit_of("召集"))
            store.reconcile_pending("召集", (19, 19))
            self.assertTrue(store.state.depleted_today)
            store.reconcile_pending("压制", (5, 90))
            store.reconcile_pending("压制", (5, 90))
            self.assertEqual(90, store.limit_of("压制"))
            # Kept for the day, and gone on the next one.
            again = ProgressStore(path, lambda: datetime(2026, 8, 10, 13, tzinfo=UTC_PLUS_8))
            again.load()
            self.assertEqual(19, again.limit_of("召集"))
            tomorrow = ProgressStore(path, lambda: datetime(2026, 8, 11, 13, tzinfo=UTC_PLUS_8))
            tomorrow.load()
            self.assertEqual(21, tomorrow.limit_of("召集"))

    def test_absorb_limit_from_the_hud_plans_the_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()
            store.reconcile_pending("吸收", (20, 24))
            store.reconcile_pending("吸收", (20, 24))
            self.assertTrue(store.can_plan_collection(["a", "b", "c"]))
            self.assertFalse(store.can_plan_collection(["a", "b", "c", "d", "e"]))

    def test_target_commit_covers_reservation_without_double_counting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()
            store.arm_action("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", baseline=(0, 21))
            store.mark_action_local_done("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", pending=True)
            self.assertEqual(1, store.effective_daily_counts()["吸收"])
            self.assertTrue(store.mark_target("Q_sp1", CollectionMapRole.MAIN_AREA.value))
            self.assertEqual(1, store.state.daily_submaps)
            self.assertEqual(1, store.effective_daily_counts()["吸收"])
            self.assertFalse(store.mark_target("Q_sp1", CollectionMapRole.MAIN_AREA.value))

    def test_mark_target_requires_role_actions_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()

            with self.assertRaisesRegex(RuntimeError, "requires durable local action"):
                store.mark_target("Q_sp1", CollectionMapRole.MAIN_AREA.value)
            self.assertEqual(set(), store.state.completed_targets("Q_sp1"))

    def test_reconcile_pending_uses_positive_delta_deterministically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()
            for role in (
                CollectionMapRole.MAIN_AREA,
                CollectionMapRole.BATTLE_AREA_1,
            ):
                store.arm_action("Q_sp1", role, "吸收", baseline=(0, 21))
                store.mark_action_local_done("Q_sp1", role, "吸收", pending=True)

            self.assertEqual(1, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual(1, store.pending_count("吸收"))
            self.assertEqual(0, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual(1, store.reconcile_pending("吸收", (2, 21)))
            self.assertEqual(0, store.pending_count("吸收"))
            self.assertEqual((2, 21), store.state.observed_counts["吸收"])

    def test_reconcile_settles_record_covered_by_snapshot_taken_while_armed(self):
        """BUG-20260906-02 回归：快照在记录尚无结算资格时先持久化（点击后被
        判定失败、用户停止或崩溃打断），记录转挂账后等额读数必须按覆盖结算，
        否则该技能被守卫拒绝点击直到次日重置。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()
            store.arm_action("Q_sp2", CollectionMapRole.MAIN_AREA, "吸收", baseline=(0, 21))
            store.mark_action_clicked("Q_sp2", CollectionMapRole.MAIN_AREA, "吸收")
            # 点击后、判定前的稳定读数：记录仍为 CLICKED，结不清但快照已持久化。
            self.assertEqual(0, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual((1, 21), store.state.observed_counts["吸收"])
            store.mark_action_local_done("Q_sp2", CollectionMapRole.MAIN_AREA, "吸收", pending=True)
            # 恢复后的等额稳定读数按覆盖结算，解除死锁。
            self.assertEqual(1, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual(0, store.pending_count("吸收"))
            record = store.get_action_record("Q_sp2", CollectionMapRole.MAIN_AREA, "吸收")
            self.assertEqual(CollectionActionState.SETTLED.value, record["state"])
            self.assertFalse(record["pending"])
            self.assertFalse(record["reservation"])
            self.assertEqual([1, 21], record["observed"])
            # 结算幂等。
            self.assertEqual(0, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual((1, 21), store.state.observed_counts["吸收"])

    def test_reconcile_coverage_skips_record_already_offered_the_snapshot(self):
        """覆盖结算只针对快照持久化时尚无结算资格的记录；已按增量获得过
        机会的挂账不得被等额快照重复入账。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8),
            )
            store.load()
            for role in (
                CollectionMapRole.MAIN_AREA,
                CollectionMapRole.BATTLE_AREA_1,
            ):
                store.arm_action("Q_sp1", role, "吸收", baseline=(0, 21))
                store.mark_action_local_done("Q_sp1", role, "吸收", pending=True)

            self.assertEqual(1, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual(1, store.pending_count("吸收"))
            # 未发生新消耗：覆盖结算不得把第二条挂账一并结清。
            self.assertEqual(0, store.reconcile_pending("吸收", (1, 21)))
            self.assertEqual(1, store.pending_count("吸收"))
            self.assertEqual(1, store.reconcile_pending("吸收", (2, 21)))
            self.assertEqual(0, store.pending_count("吸收"))
            self.assertEqual((2, 21), store.state.observed_counts["吸收"])

    def test_delayed_pending_records_share_snapshot_budget_after_reload(self):
        for already_pending in (False, True):
            for next_used in (1, 2):
                with self.subTest(already_pending=already_pending, next_used=next_used):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        path = Path(temp_dir) / "progress.json"
                        def now():
                            return datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8)
                        store = ProgressStore(path, now)
                        store.load()
                        roles = (
                            CollectionMapRole.MAIN_AREA,
                            CollectionMapRole.BATTLE_AREA_1,
                            CollectionMapRole.BATTLE_AREA_2,
                        )
                        for role in roles:
                            store.arm_action("Q_sp1", role, "吸收", baseline=(0, 21))
                            store.mark_action_clicked("Q_sp1", role, "吸收")
                        if already_pending:
                            store.mark_action_local_done("Q_sp1", roles[0], "吸收")
                        self.assertEqual(
                            int(already_pending), store.reconcile_pending("吸收", (1, 21))
                        )
                        for role in roles:
                            store.mark_action_local_done("Q_sp1", role, "吸收")
                        store = ProgressStore(path, now)
                        store.load()
                        self.assertEqual(
                            next_used - int(already_pending),
                            store.reconcile_pending("吸收", (next_used, 21)),
                        )
                        self.assertEqual(3 - next_used, store.pending_count("吸收"))
                        store = ProgressStore(path, now)
                        store.load()
                        self.assertEqual(0, store.reconcile_pending("吸收", (next_used, 21)))
                        self.assertEqual(3 - next_used, store.pending_count("吸收"))

    def test_schema_four_sanitizes_action_keys_and_quarantines_stale_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = datetime(2026, 8, 10, 12, tzinfo=UTC_PLUS_8)
            day = daily_cycle_key(now)
            week = weekly_cycle_key(now)

            def record(daily, card, role, action, *, key=None):
                canonical = "|".join((daily, card, role, action))
                return key or canonical, {
                    "daily_key": daily,
                    "card_id": card,
                    "map_role": role,
                    "action": action,
                    "state": "pending",
                    "local_done": True,
                    "reservation": True,
                }

            valid_key, valid = record(day, "Q_sp1", CollectionMapRole.MAIN_AREA.value, "吸收")
            stale_key, stale = record(
                "2026-08-09", "Q_sp1", CollectionMapRole.MAIN_AREA.value, "吸收"
            )
            malformed_key, malformed = record(
                day, "Q_sp1", CollectionMapRole.MAIN_AREA.value, "吸收", key="not-canonical"
            )
            invalid_action_key, invalid_action = record(
                day, "Q_sp1", CollectionMapRole.MAIN_AREA.value, "探查"
            )
            invalid_role_key, invalid_role = record(day, "Q_sp1", "main", "吸收")
            path.write_text(
                json.dumps(
                    {
                        "schema_version": STATE_SCHEMA_VERSION,
                        "weekly_key": week,
                        "daily_key": day,
                        "action_records": {
                            valid_key: valid,
                            stale_key: stale,
                            malformed_key: malformed,
                            invalid_action_key: invalid_action,
                            invalid_role_key: invalid_role,
                            "broken-value": "not-a-record",
                        },
                        "observed_counts": {
                            "吸收": [1, 21],
                            "探查": [99, 99],
                        },
                    }
                ),
                encoding="utf-8",
            )

            state = ProgressStore(path, lambda: now).load()

            self.assertEqual({valid_key}, set(state.action_records))
            self.assertEqual((1, 21), state.observed_counts["吸收"])
            self.assertNotIn("探查", state.observed_counts)
            self.assertGreaterEqual(len(state.archived_action_records), 5)
            self.assertTrue(
                all(
                    record.get("state") == CollectionActionState.ARCHIVED.value
                    and record.get("reservation") is False
                    for record in state.archived_action_records.values()
                )
            )
            resumed_store = ProgressStore(path, lambda: now)
            resumed_store.load()
            self.assertEqual(2, resumed_store.effective_used("吸收"))

    def test_weekly_rollover_archives_unresolved_actions_and_resets_absolute_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "progress.json"
            now = [datetime(2026, 7, 13, 7, 59, tzinfo=UTC_PLUS_8)]
            store = ProgressStore(path, lambda: now[0])
            store.load()
            store.arm_action("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", baseline=(0, 21))
            store.mark_action_local_done("Q_sp1", CollectionMapRole.MAIN_AREA, "吸收", pending=True)
            now[0] = datetime(2026, 7, 13, 8, 0, tzinfo=UTC_PLUS_8)

            state = ProgressStore(path, lambda: now[0]).load()

            self.assertEqual("2026-07-13", state.weekly_key)
            self.assertEqual({}, state.action_records)
            self.assertEqual({}, state.observed_counts)
            self.assertEqual(
                (0, 0, 0),
                (state.daily_submaps, state.daily_summons, state.daily_suppressions),
            )
            archived = next(iter(state.archived_action_records.values()))
            self.assertEqual(CollectionActionState.ARCHIVED.value, archived["state"])
            self.assertFalse(archived["reservation"])


if __name__ == "__main__":
    unittest.main()


class BadgeCompleteTest(unittest.TestCase):
    """Live 2026-09-28: chapter 2 was finished during an interrupted run; the
    game's badge showed it complete, so it is recorded for the week."""

    def test_badge_complete_card_is_recorded_and_survives_a_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "progress.json"
            now = lambda: datetime(2026, 9, 28, 12, tzinfo=UTC_PLUS_8)  # noqa: E731
            store = ProgressStore(path, now)
            store.load()
            self.assertTrue(store.mark_card_complete_from_badge("Q_sp2"))
            self.assertFalse(store.mark_card_complete_from_badge("Q_sp2"))
            reloaded = ProgressStore(path, now)
            state = reloaded.load()
            self.assertTrue(state.card_verified("Q_sp2"))
            self.assertTrue(state.card_complete("Q_sp2"))

    def test_the_week_resets_on_monday_at_eight(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "progress.json"
            store = ProgressStore(path, lambda: datetime(2026, 9, 28, 12, tzinfo=UTC_PLUS_8))
            store.load()
            store.mark_card_complete_from_badge("Q_sp2")
            before = ProgressStore(path, lambda: datetime(2026, 10, 5, 7, 59, tzinfo=UTC_PLUS_8))
            self.assertTrue(before.load().card_verified("Q_sp2"))
            after = ProgressStore(path, lambda: datetime(2026, 10, 5, 8, 1, tzinfo=UTC_PLUS_8))
            self.assertFalse(after.load().card_verified("Q_sp2"))
