"""A card taken as done from its badges alone is read again on a later game
day (players 2026-11-16 and 2026-11-23: 「到周一了图不会重置，即使我手动重置了，
他跑图的时候还是会识别成已跑图状态跳过」).

On Monday morning the game can still show last week's done badges.  Read
then, every card was written down as done for the whole week, and even
「重新开始」 read the same picture again.  Now such a card is only done for
that game day; the next day its badges are read once more: still done, it
stays done for the week; open, it is run.  Cards the tool walked itself are
never read again (Leo 2026-10-21)."""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.tasks.map_trade import account_check
from src.tasks.map_trade.card_status import (
    CardActionDetection,
    CardActionState,
    CollectionCardSelectionOutcome,
    CollectionCardSelectionResult,
    StoryCardCompletion,
)
from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.models import CARD_BY_ID, NavigationResult, ScreenState
from src.tasks.map_trade.progress import UTC_PLUS_8, ProgressStore
from src.utils import accounts

MONDAY = datetime(2026, 11, 23, 9, 39, tzinfo=UTC_PLUS_8)  # the second report
TUESDAY = datetime(2026, 11, 24, 9, 0, tzinfo=UTC_PLUS_8)
CARDS = (CARD_BY_ID["Q_sp1"], CARD_BY_ID["Q_sp2"])
DONE = CollectionCardSelectionOutcome.VISUALLY_COMPLETE
OPEN = CollectionCardSelectionOutcome.ENTERED


def _badges(outcome):
    """What reading the card's badges without entering returns."""
    state = CardActionState.PENDING if outcome is OPEN else CardActionState.COMPLETED
    action = CardActionDetection(state)
    completion = StoryCardCompletion(action, action, (0, 0, 1, 1), True)
    return CollectionCardSelectionResult(
        CollectionCardSelectionOutcome.FAILED if outcome is OPEN else DONE,
        NavigationResult(True, ScreenState.CARD_MENU),
        completion,
    )


class WalkStarted(Exception):
    """Stands for the walk through the card's maps."""


def _run(path: Path, now: datetime, badges: dict[str, CollectionCardSelectionOutcome]):
    progress = ProgressStore(path, lambda: now)
    selected = []
    inspected = []
    warnings = []

    def select(card_id, *, enter_visually_complete):
        selected.append(card_id)
        state = ScreenState.SANDBOX if badges[card_id] is OPEN else ScreenState.CARD_MENU
        return CollectionCardSelectionResult(badges[card_id], NavigationResult(True, state))

    def walk(card):
        raise WalkStarted(card.card_id)

    navigator = SimpleNamespace(
        select_collection_card=select,
        current_collection_target=walk,
        inspect_collection_card_completion=lambda card_id: (
            inspected.append(card_id) or _badges(badges[card_id])
        ),
    )
    task = SimpleNamespace(
        config={"卡带单步重试次数": 1},
        log_warning=lambda message, *_args, **_kwargs: warnings.append(message),
        log_info=lambda *_args, **_kwargs: None,
        info_set=lambda *_args: None,
    )
    collector = Collector(task, object(), navigator, progress)
    collector._restore_on_last_field = lambda: None
    collector._restore_skill_group = lambda **_kwargs: None
    walked = None
    with patch("src.tasks.map_trade.collector.COLLECTABLE_CARDS", CARDS), patch(
        "src.tasks.map_trade.account_check.COLLECTABLE_CARDS", CARDS
    ):
        try:
            result = collector.run()
        except WalkStarted as started:
            result, walked = None, str(started)
    return SimpleNamespace(
        result=result,
        walked=walked,
        selected=selected,
        inspected=inspected,
        warnings=warnings,
        progress=progress,
    )


class BadgeReadAgainTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "map_trade_progress.json"
        # The 换账号 flag file is written under the working folder.
        old = os.getcwd()
        os.chdir(folder.name)
        self.addCleanup(os.chdir, old)
        accounts.reset_cache()
        self.addCleanup(accounts.reset_cache)

    def test_monday_read_is_only_for_that_day(self):
        # Monday 09:39: the game still shows last week's done badges.
        monday = _run(self.path, MONDAY, {"Q_sp1": DONE, "Q_sp2": DONE})
        self.assertTrue(monday.result.success)
        self.assertIn("之后的游戏日会再看一次图示", monday.result.message)
        state = monday.progress.state
        self.assertTrue(state.card_verified("Q_sp1"))
        self.assertEqual({"Q_sp1": "2026-11-23", "Q_sp2": "2026-11-23"}, state.badge_days)

        # The same day again (e.g. after 「重新开始」 or a second run): the
        # cards are not entered or read a third time.
        again = _run(self.path, MONDAY, {"Q_sp1": DONE, "Q_sp2": DONE})
        self.assertEqual([], again.selected)

        # Tuesday: the game has reset.  The card is read again and run.
        tuesday = _run(self.path, TUESDAY, {"Q_sp1": OPEN, "Q_sp2": DONE})
        self.assertEqual("Q_sp1", tuesday.walked)
        self.assertFalse(account_check.pending_flag())
        self.assertEqual(["Q_sp1"], tuesday.selected)
        state = ProgressStore(self.path, lambda: TUESDAY).load()
        self.assertEqual(set(), state.completed_targets("Q_sp1"))
        self.assertTrue(any("今天图示显示还没完成" in line for line in tuesday.warnings))

    def test_still_done_next_day_stays_done_for_the_week(self):
        _run(self.path, MONDAY, {"Q_sp1": DONE, "Q_sp2": DONE})
        tuesday = _run(self.path, TUESDAY, {"Q_sp1": DONE, "Q_sp2": DONE})
        self.assertEqual(["Q_sp1", "Q_sp2"], tuesday.selected)
        self.assertTrue(tuesday.result.success)
        state = tuesday.progress.state
        self.assertEqual({}, state.badge_days)
        self.assertTrue(all(state.card_verified(card.card_id) for card in CARDS))
        # Wednesday: nothing is read any more.
        wednesday = _run(
            self.path, datetime(2026, 11, 25, 9, tzinfo=UTC_PLUS_8), {"Q_sp1": OPEN, "Q_sp2": OPEN}
        )
        self.assertEqual([], wednesday.selected)

    def test_cards_the_tool_walked_are_never_read_again(self):
        progress = ProgressStore(self.path, lambda: MONDAY)
        progress.load()
        for card in CARDS:
            progress.state.cards[card.card_id] = [t.key for t in card.targets]
            progress.mark_card_verified(card.card_id)
        tuesday = _run(self.path, TUESDAY, {"Q_sp1": OPEN, "Q_sp2": OPEN})
        self.assertEqual([], tuesday.selected)
        self.assertIsNone(tuesday.walked)

    def test_badge_cards_do_not_trip_the_other_account_check(self):
        # On Tuesday the reset game shows the Monday cards untouched; that is
        # not another account.
        _run(self.path, MONDAY, {"Q_sp1": DONE, "Q_sp2": DONE})
        state = ProgressStore(self.path, lambda: TUESDAY).load()
        with patch("src.tasks.map_trade.account_check.COLLECTABLE_CARDS", CARDS):
            self.assertEqual([], account_check.card_ids_to_check(state, None))

    def test_read_later_in_the_week_then_open_is_another_account(self):
        # Read done on Wednesday: the game had reset long before, so the
        # same account can never show the card open again this week.
        wednesday = datetime(2026, 11, 25, 9, tzinfo=UTC_PLUS_8)
        _run(self.path, wednesday, {"Q_sp1": DONE, "Q_sp2": DONE})
        thursday = _run(
            self.path, datetime(2026, 11, 26, 9, tzinfo=UTC_PLUS_8), {"Q_sp1": OPEN, "Q_sp2": OPEN}
        )
        self.assertFalse(thursday.result.success)
        self.assertEqual(account_check.MESSAGE, thursday.result.message)
        self.assertTrue(account_check.pending_flag())
        self.assertIsNone(thursday.walked)
        self.assertEqual([], thursday.selected)  # nothing entered, nothing pressed
        self.assertEqual(["Q_sp1"] * account_check.READS_PER_CARD, thursday.inspected)
        # The records are kept for the player's answer on 首页.
        state = ProgressStore(self.path, lambda: wednesday).load()
        self.assertTrue(state.card_verified("Q_sp1"))

    def test_read_later_in_the_week_still_done_stays_done(self):
        wednesday = datetime(2026, 11, 25, 9, tzinfo=UTC_PLUS_8)
        _run(self.path, wednesday, {"Q_sp1": DONE, "Q_sp2": DONE})
        thursday = _run(
            self.path, datetime(2026, 11, 26, 9, tzinfo=UTC_PLUS_8), {"Q_sp1": DONE, "Q_sp2": DONE}
        )
        self.assertTrue(thursday.result.success)
        self.assertFalse(account_check.pending_flag())
        self.assertEqual({}, thursday.progress.state.badge_days)

    def test_restart_week_forgets_badge_days(self):
        _run(self.path, MONDAY, {"Q_sp1": DONE, "Q_sp2": DONE})
        ProgressStore(self.path, lambda: MONDAY).restart_collection_week()
        self.assertEqual({}, ProgressStore(self.path, lambda: MONDAY).load().badge_days)

    def test_new_week_starts_without_badge_days(self):
        _run(self.path, MONDAY, {"Q_sp1": DONE, "Q_sp2": DONE})
        next_week = datetime(2026, 11, 30, 9, tzinfo=UTC_PLUS_8)
        self.assertEqual({}, ProgressStore(self.path, lambda: next_week).load().badge_days)


class PlayerWordsTest(unittest.TestCase):
    """The new lines reach 简中 players as written and 繁中 players converted
    (the tool's 繁中 is OpenCC s2twp over the 简中 text)."""

    def test_both_chinese_versions(self):
        from src.ui.traditional import to_traditional

        collector = Collector.__new__(Collector)
        collector._badge_only = ["Q_sp1", "Q_sp2"]
        note = collector._badge_only_note()
        self.assertIn("2张卡带游戏图示显示本周已完成", note)
        self.assertIn("之后的游戏日会再看一次图示，还没完成就会跑", note)
        traditional = to_traditional(note)
        self.assertIn("2張卡帶遊戲圖示顯示本週已完成", traditional)
        self.assertIn("之後的遊戲日會再看一次圖示，還沒完成就會跑", traditional)
        collector._badge_only = []
        self.assertEqual("", collector._badge_only_note())


if __name__ == "__main__":
    unittest.main()
