"""Nightmare Winter (Q_ep2) has only a 吸取 badge: ticked means done (Leo 2026-10-11)."""

import unittest
from types import SimpleNamespace

import numpy as np

from src.tasks.map_trade.card_status import (
    CardActionDetection,
    CardActionState,
    CollectionCardSelectionOutcome,
    StoryCardCompletion,
)
from src.tasks.map_trade.models import NavigationResult, ScreenState
from src.tasks.map_trade.navigator_story import StoryCardNavigationMixin

DONE = CardActionDetection(CardActionState.COMPLETED)
OPEN = CardActionDetection(CardActionState.PENDING)
NONE = CardActionDetection(CardActionState.UNKNOWN, reason="no badge")


def _inspect(card_id, absorb, suppress):
    nav = StoryCardNavigationMixin.__new__(StoryCardNavigationMixin)
    located = SimpleNamespace(
        frame=np.zeros((1080, 1920, 3), np.uint8),
        badge=SimpleNamespace(best=SimpleNamespace(result=SimpleNamespace(center=(530, 1000)))),
    )
    nav._locate_story_card = lambda _card_id: located
    nav.card_status = SimpleNamespace(
        detect=lambda _frame, _center: StoryCardCompletion(absorb, suppress, (0, 0, 1, 1), True)
    )
    nav._status = lambda *_args: None
    return nav.inspect_collection_card_completion(card_id).outcome


def _select(card_id, absorb, suppress):
    nav = StoryCardNavigationMixin.__new__(StoryCardNavigationMixin)
    located = SimpleNamespace(
        frame=np.zeros((1080, 1920, 3), np.uint8),
        badge=SimpleNamespace(best=SimpleNamespace(result=SimpleNamespace(center=(530, 1000)))),
    )
    entered = []
    nav._locate_story_card = lambda _card_id: located
    nav.card_status = SimpleNamespace(
        detect=lambda _frame, _center: StoryCardCompletion(absorb, suppress, (0, 0, 1, 1), True)
    )
    nav._status = lambda *_args: None

    def enter(_located):
        entered.append(card_id)
        return NavigationResult(True, ScreenState.SANDBOX, "entered")

    nav._enter_located_story_card = enter
    return nav.select_collection_card(card_id).outcome, entered


class AbsorbOnlyCardTest(unittest.TestCase):
    def test_weekly_run_skips_nightmare_winter_once_absorb_is_ticked(self):
        outcome, entered = _select("Q_ep2", DONE, NONE)
        self.assertEqual(CollectionCardSelectionOutcome.VISUALLY_COMPLETE, outcome)
        self.assertEqual([], entered)

    def test_weekly_run_enters_nightmare_winter_while_absorb_is_open(self):
        outcome, entered = _select("Q_ep2", OPEN, NONE)
        self.assertEqual(CollectionCardSelectionOutcome.ENTERED, outcome)
        self.assertEqual(["Q_ep2"], entered)

    def test_weekly_run_enters_other_cards_with_one_badge(self):
        for card_id in ("Q_ep1", "Q_sp12", "Q_sp18"):
            outcome, entered = _select(card_id, DONE, NONE)
            self.assertEqual(CollectionCardSelectionOutcome.ENTERED, outcome, card_id)
            self.assertEqual([card_id], entered)

    def test_nightmare_winter_ticked_absorb_is_done(self):
        self.assertEqual(
            CollectionCardSelectionOutcome.VISUALLY_COMPLETE, _inspect("Q_ep2", DONE, NONE)
        )

    def test_nightmare_winter_open_absorb_is_not_done(self):
        self.assertEqual(CollectionCardSelectionOutcome.FAILED, _inspect("Q_ep2", OPEN, NONE))

    def test_other_cards_still_need_both_badges(self):
        for card_id in ("Q_ep1", "Q_ep3", "Q_sp12"):
            self.assertEqual(
                CollectionCardSelectionOutcome.FAILED, _inspect(card_id, DONE, NONE), card_id
            )
            self.assertEqual(
                CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                _inspect(card_id, DONE, DONE),
                card_id,
            )


if __name__ == "__main__":
    unittest.main()
