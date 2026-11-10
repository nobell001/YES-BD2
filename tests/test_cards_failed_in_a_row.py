"""Player v0.3.9 2026-11-10: chapters 8-19 failed one after another, each
card was run a second time straight away, and the weekly 跑图 was still
going after an hour.  Once three different cards in a row were skipped with
no map done in between, later cards are still tried (Leo 2026-10-12: a stuck
card never stops the whole run) but not twice."""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks.map_trade import collector as collector_module
from src.tasks.map_trade.collector import CARDS_FAILED_IN_A_ROW_NO_RETRY, Collector
from src.tasks.map_trade.models import NavigationResult, ScreenState


def _collector():
    collector = object.__new__(Collector)
    warnings = []
    collector.task = SimpleNamespace(log_warning=lambda text, **_k: warnings.append(text))
    collector.warnings = warnings
    collector._status = lambda *_a: None
    collector._skipped_cards = []
    collector._skip_reasons = {}
    collector._skill_skips = {}
    collector._unconfirmed_cards = set()
    collector._badges_unfinished = set()
    collector._unfinished_cards = []
    collector._failed_in_a_row = []
    collector._done_at_last_skip = None
    collector._note_skip_screen = lambda: None
    collector._follow_args = None
    collector._restore_skill_group = lambda *a, **k: None
    collector.navigator = SimpleNamespace(
        return_home=lambda: NavigationResult(True, ScreenState.HOME, "主页")
    )
    return collector


def _card(number):
    return SimpleNamespace(card_id=f"Q_sp{number}", label=f"第{number}章")


WHY = "回主城失败（没按到小地图的≡按钮）"


class CardsFailedInARowTest(unittest.TestCase):
    def test_a_skipped_card_never_stops_the_run(self):
        collector = _collector()
        for number in range(8, 14):
            self.assertIsNone(collector._skip_card(_card(number), WHY, 0))

    def test_count_is_of_different_cards_with_no_map_done_in_between(self):
        collector = _collector()
        collector._skip_card(_card(8), WHY, 0)
        collector._skip_card(_card(8), WHY, 0)  # its own second try
        self.assertEqual(["Q_sp8"], collector._failed_in_a_row)
        collector._skip_card(_card(9), WHY, 0)
        self.assertEqual(2, len(collector._failed_in_a_row))
        # 第10章 ran two maps, then 第11章 failed: counted from one again.
        collector._skip_card(_card(11), WHY, 2)
        self.assertEqual(["Q_sp11"], collector._failed_in_a_row)

    def test_cards_the_account_cannot_enter_are_not_counted(self):
        collector = _collector()
        for number in (15, 16, 17, 18):
            collector._skip_card(_card(number), "进不去（没有这张卡带），可能还没有这张卡带", 0)
        self.assertEqual([], collector._failed_in_a_row)

    def _runs(self, done_after=None):
        """Card ids in the order they are run when every card fails
        (``done_after``: this card finishes a map instead)."""
        collector = _collector()
        cards = [_card(number) for number in range(8, 14)]
        ran = []
        done = 0
        with mock.patch.object(collector_module, "COLLECTABLE_CARDS", tuple(cards)), mock.patch(
            "src.tasks.problem_report.forget_skip", lambda: None
        ):
            for card in collector._cards_with_one_retry():
                ran.append(card.card_id)
                if card.card_id == done_after:
                    done += 1
                    continue
                collector._skip_card(card, WHY, done)
        return ran

    def test_first_cards_get_their_second_try_then_one_try_each(self):
        ran = self._runs()
        self.assertEqual(
            ["Q_sp8", "Q_sp8", "Q_sp9", "Q_sp9", "Q_sp10", "Q_sp11", "Q_sp12", "Q_sp13"], ran
        )
        self.assertEqual(3, CARDS_FAILED_IN_A_ROW_NO_RETRY)

    def test_second_tries_come_back_once_a_map_is_done(self):
        ran = self._runs(done_after="Q_sp11")
        self.assertEqual(
            ["Q_sp8", "Q_sp8", "Q_sp9", "Q_sp9", "Q_sp10", "Q_sp11", "Q_sp12", "Q_sp12", "Q_sp13", "Q_sp13"],
            ran,
        )


if __name__ == "__main__":
    unittest.main()
