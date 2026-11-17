"""跑图 week: the automatic Monday 08:00 restart, and the player's own
「重新开始」 on the 跑图 page (a player 2026-11-16: 「跑图这周没重置，所有图都是
保留上周已跑状态。能不能出个按钮手动重置」)."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.tasks.map_trade.collector_constants import UNSUPPORTED_COLLECTION_CARD_NUMBERS
from src.tasks.map_trade.models import COLLECTABLE_CARDS
from src.tasks.map_trade.progress import (
    STATE_SCHEMA_VERSION,
    UTC_PLUS_8,
    VALID_FAVORITE_SHOP_IDS,
    ProgressFileError,
    ProgressStore,
)
from src.utils import accounts

SUPPORTED = [c for c in COLLECTABLE_CARDS if c.number not in UNSUPPORTED_COLLECTION_CARD_NUMBERS]


def _last_week_all_done(path: Path) -> None:
    """The shape of Leo's real file on 2026-11-15: every card of the week of
    11-09 done and verified, plus a pending record from that week."""
    cards = {c.card_id: sorted(t.key for t in c.targets) for c in SUPPORTED}
    pending_card = SUPPORTED[0].card_id
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "weekly_key": "2026-11-09",
        "daily_key": "2026-11-15",
        "cards": cards,
        "verified_cards": sorted(cards),
        "daily_submaps": 5,
        "daily_summons": 2,
        "daily_suppressions": 3,
        "depleted_today": False,
        "favorite_week": "2026-11-09",
        "favorite_cards": sorted(VALID_FAVORITE_SHOP_IDS),
        "cooking_week": "",
        "cooking_recipes": [],
        "action_records": {
            f"2026-11-15|{pending_card}|main_area|吸收": {
                "action": "吸收",
                "card_id": pending_card,
                "daily_key": "2026-11-15",
                "map_role": "main_area",
                "pending": True,
                "state": "pending",
                "status": "pending",
            }
        },
        "archived_action_records": {},
        "observed_counts": {},
        "observed_limits": {},
        "game_counts": {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class _InFolder(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd()
        self._dir = tempfile.TemporaryDirectory()
        os.chdir(self._dir.name)
        accounts.reset_cache()
        self.path = Path(self._dir.name) / "configs" / "map_trade_progress.json"
        self.path.parent.mkdir(parents=True)

    def tearDown(self):
        os.chdir(self._old)
        accounts.reset_cache()
        self._dir.cleanup()


class AutomaticWeekTest(_InFolder):
    def test_last_week_kept_until_monday_0800_then_cleared(self):
        _last_week_all_done(self.path)
        before = datetime(2026, 11, 16, 7, 59, tzinfo=UTC_PLUS_8)
        state = ProgressStore(self.path, now_provider=lambda: before).load()
        self.assertEqual("2026-11-09", state.weekly_key)
        self.assertTrue(state.weekly_collection_complete)

        after = datetime(2026, 11, 16, 8, 0, tzinfo=UTC_PLUS_8)
        state = ProgressStore(self.path, now_provider=lambda: after).load()
        self.assertEqual("2026-11-16", state.weekly_key)
        self.assertEqual({}, state.cards)
        self.assertFalse(state.weekly_collection_complete)

    def test_the_report_time_any_clock_zone(self):
        # Reported 2026-11-16 17:00 UTC (Tuesday 01:00 UTC+8); the PC's own
        # time zone does not matter, only its clock.
        _last_week_all_done(self.path)
        now = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)
        state = ProgressStore(self.path, now_provider=lambda: now).load()
        self.assertEqual("2026-11-16", state.weekly_key)
        self.assertEqual({}, state.cards)

    def test_page_shows_the_new_week_before_any_run(self):
        from src.ui.shell import data

        _last_week_all_done(self.path)
        now = datetime(2026, 11, 17, 9, tzinfo=UTC_PLUS_8)
        with mock.patch("src.tasks.map_trade.progress.datetime") as clock:
            clock.now.side_effect = lambda tz=None: now
            clock.side_effect = datetime
            progress = data.map_progress()
        self.assertIsNotNone(progress)
        self.assertEqual(0, progress.cards_done)
        # The page only reads: the file still says last week.
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual("2026-11-09", raw["weekly_key"])


class RestartWeekTest(_InFolder):
    NOW = datetime(2026, 11, 15, 12, tzinfo=UTC_PLUS_8)

    def _store(self):
        return ProgressStore(self.path, now_provider=lambda: self.NOW)

    def test_cards_forgotten_today_and_trade_kept(self):
        _last_week_all_done(self.path)
        backup = self._store().restart_collection_week()

        self.assertTrue(backup is not None and backup.exists())
        self.assertEqual(
            len(SUPPORTED), len(json.loads(backup.read_text(encoding="utf-8"))["cards"])
        )
        state = self._store().load()
        self.assertEqual({}, state.cards)
        self.assertEqual([], state.verified_cards)
        self.assertFalse(state.weekly_collection_complete)
        # Today's counts are what the game's daily counts were spent on.
        self.assertEqual(
            (5, 2, 3),
            (state.daily_submaps, state.daily_summons, state.daily_suppressions),
        )
        # 跑商 records stay.
        self.assertEqual(set(VALID_FAVORITE_SHOP_IDS), state.completed_favorite_cards)
        self.assertEqual("2026-11-09", state.weekly_key)
        # A pending press is settled, not left to block the next card.
        record = next(iter(state.action_records.values()))
        self.assertFalse(record["pending"])

    def test_empty_install(self):
        self.assertIsNone(self._store().restart_collection_week())
        self.assertEqual({}, self._store().load().cards)

    def test_dialog_cancel_touches_nothing(self):
        from src.ui.shell import map_week_reset

        _last_week_all_done(self.path)
        before = self.path.read_bytes()
        with mock.patch.object(map_week_reset, "WeekResetDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            self.assertIsNone(map_week_reset.ask(None))
        self.assertEqual(before, self.path.read_bytes())

    def test_dialog_restart_and_failure_said(self):
        from src.ui.shell import map_week_reset

        _last_week_all_done(self.path)
        said = []

        def say(_window, text, ok):
            said.append((text, ok))

        with mock.patch.object(map_week_reset, "WeekResetDialog") as dialog, \
                mock.patch.object(map_week_reset, "_say", say), \
                mock.patch("src.tasks.map_trade.progress.datetime") as clock:
            clock.now.side_effect = lambda tz=None: self.NOW
            dialog.return_value.exec.return_value = 1
            self.assertTrue(map_week_reset.ask(None))
            self.assertEqual([(map_week_reset.DONE, True)], said)
            with mock.patch.object(
                ProgressStore, "save", side_effect=ProgressFileError("held")
            ):
                self.assertFalse(map_week_reset.ask(None))
        self.assertEqual((map_week_reset.FAILED, False), said[-1])
        self.assertEqual({}, json.loads(self.path.read_text(encoding="utf-8"))["cards"])


if __name__ == "__main__":
    unittest.main()
