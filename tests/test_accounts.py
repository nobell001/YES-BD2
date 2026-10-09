"""Several game accounts on one install (GitHub issue #4)."""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from src.tasks.map_trade import account_check
from src.tasks.map_trade.card_status import CardActionState
from src.tasks.map_trade.collector_constants import UNSUPPORTED_COLLECTION_CARD_NUMBERS
from src.tasks.map_trade.models import COLLECTABLE_CARDS, SUPPRESS_ONLY_VERIFIED_CARD_IDS
from src.tasks.map_trade.progress import UTC_PLUS_8, ProgressStore
from src.utils import accounts


class _InFolder(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd()
        self._dir = tempfile.TemporaryDirectory()
        os.chdir(self._dir.name)
        accounts.reset_cache()

    def tearDown(self):
        os.chdir(self._old)
        accounts.reset_cache()
        self._dir.cleanup()


class AccountsTest(_InFolder):
    def test_fresh_install_is_account_one_with_the_old_files(self):
        self.assertEqual(accounts.current_id(), "1")
        self.assertEqual([a.id for a in accounts.accounts()], ["1"])
        self.assertEqual(accounts.scoped(Path("configs") / "x.json"), Path("configs") / "x.json")
        self.assertEqual(accounts.scoped("configs/x.json"), "configs/x.json")

    def test_other_accounts_keep_files_in_their_own_folder(self):
        second = accounts.add("小号", {})
        accounts.switch(second.id)
        self.assertEqual(
            accounts.scoped(Path("configs") / "x.json"),
            Path("configs") / "accounts" / second.id / "x.json",
        )
        self.assertIsInstance(accounts.scoped("configs/x.json"), str)
        self.assertEqual(accounts.scoped(Path("configs") / "x.json", "1"), Path("configs/x.json"))

    def test_at_most_five_accounts(self):
        for _ in range(accounts.MAX_ACCOUNTS - 1):
            accounts.add()
        with self.assertRaises(accounts.AccountError):
            accounts.add()
        self.assertEqual(len(accounts.accounts()), accounts.MAX_ACCOUNTS)

    def test_switch_keeps_each_accounts_ticks(self):
        config = {"a": True, "b": True}
        second = accounts.add("", config)
        config["b"] = False  # account 1 unticks b
        accounts.switch(second.id, config, ("a", "b"))
        self.assertEqual(config, {"a": True, "b": True})  # account 2's copy
        config["a"] = False  # account 2 unticks a
        accounts.switch("1", config, ("a", "b"))
        self.assertEqual(config, {"a": True, "b": False})
        accounts.switch(second.id, config, ("a", "b"))
        self.assertEqual(config, {"a": False, "b": True})

    def test_first_and_current_accounts_cannot_be_deleted(self):
        second = accounts.add()
        with self.assertRaises(accounts.AccountError):
            accounts.delete("1")
        accounts.switch(second.id)
        with self.assertRaises(accounts.AccountError):
            accounts.delete(second.id)
        accounts.switch("1")
        folder = Path("configs") / "accounts" / second.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "map_trade_progress.json").write_text("{}", encoding="utf-8")
        accounts.delete(second.id)
        self.assertFalse(folder.exists())
        self.assertEqual([a.id for a in accounts.accounts()], ["1"])

    def test_avatar_over_8mb_is_refused(self):
        big = Path("big.png")
        with big.open("wb") as handle:
            handle.truncate(accounts.AVATAR_MAX_BYTES + 1)
        with self.assertRaises(accounts.AccountError):
            accounts.set_avatar("1", big)
        small = Path("small.png")
        small.write_bytes(b"\x89PNG")
        accounts.set_avatar("1", small)
        self.assertIsNotNone(accounts.avatar_path(accounts.current()))
        with self.assertRaises(accounts.AccountError):
            accounts.set_avatar("1", Path("notes.txt"))

    def test_progress_follows_the_account(self):
        now = lambda: datetime(2026, 10, 9, 12, tzinfo=UTC_PLUS_8)  # noqa: E731
        card = next(c for c in COLLECTABLE_CARDS if c.number not in UNSUPPORTED_COLLECTION_CARD_NUMBERS)
        store = ProgressStore(now_provider=now)
        store.load()
        for target in card.targets:
            store.state.cards.setdefault(card.card_id, []).append(target.key)
        store.state.verified_cards.append(card.card_id)
        store.save()
        second = accounts.add()
        accounts.switch(second.id)
        other = ProgressStore(now_provider=now).load()
        self.assertFalse(other.card_verified(card.card_id))
        accounts.switch("1")
        self.assertTrue(ProgressStore(now_provider=now).load().card_verified(card.card_id))

    def test_forget_collection_week_keeps_a_copy(self):
        now = lambda: datetime(2026, 10, 9, 12, tzinfo=UTC_PLUS_8)  # noqa: E731
        card = next(c for c in COLLECTABLE_CARDS if c.number not in UNSUPPORTED_COLLECTION_CARD_NUMBERS)
        store = ProgressStore(now_provider=now)
        store.load()
        store.state.cards[card.card_id] = [t.key for t in card.targets]
        store.state.verified_cards.append(card.card_id)
        store.state.depleted_today = True
        store.save()
        backup = store.forget_collection_week()
        self.assertTrue(backup is not None and backup.exists())
        state = ProgressStore(now_provider=now).load()
        self.assertEqual(state.cards, {})
        self.assertFalse(state.depleted_today)


def _reading(absorb, suppress, region=True):
    completion = SimpleNamespace(
        complete_region=region,
        absorb=SimpleNamespace(state=absorb),
        suppress=SimpleNamespace(state=suppress),
    )
    return SimpleNamespace(completion=completion)


class _Navigator:
    def __init__(self, readings):
        self.readings = list(readings)
        self.asked = []

    def inspect_collection_card_completion(self, card_id):
        self.asked.append(card_id)
        return self.readings.pop(0) if self.readings else _reading(None, None, False)


class AccountCheckTest(_InFolder):
    def _state(self, count=2):
        verified = [
            c.card_id
            for c in COLLECTABLE_CARDS
            if c.number not in UNSUPPORTED_COLLECTION_CARD_NUMBERS
            and c.card_id not in SUPPRESS_ONLY_VERIFIED_CARD_IDS
        ][:count]
        return SimpleNamespace(card_verified=lambda card_id: card_id in verified)

    def test_untouched_cards_mean_another_account(self):
        pending = _reading(CardActionState.PENDING, CardActionState.PENDING)
        nav = _Navigator([pending] * 4)
        self.assertTrue(account_check.records_from_other_account(nav, self._state()))
        self.assertEqual(len(nav.asked), 4)  # two cards, read twice each

    def test_any_done_badge_trusts_the_records(self):
        pending = _reading(CardActionState.PENDING, CardActionState.PENDING)
        done = _reading(CardActionState.COMPLETED, CardActionState.COMPLETED)
        nav = _Navigator([pending, pending, done])
        self.assertFalse(account_check.records_from_other_account(nav, self._state()))

    def test_unsure_reading_never_stops_the_run(self):
        nav = _Navigator([_reading(CardActionState.PENDING, CardActionState.PENDING, False)])
        self.assertFalse(account_check.records_from_other_account(nav, self._state()))
        nav = _Navigator([_reading(CardActionState.UNKNOWN, CardActionState.PENDING)])
        self.assertFalse(account_check.records_from_other_account(nav, self._state()))

    def test_no_finished_card_means_nothing_to_check(self):
        nav = _Navigator([])
        self.assertFalse(account_check.records_from_other_account(nav, self._state(0)))
        self.assertEqual(nav.asked, [])

    def test_flag_belongs_to_the_account(self):
        account_check.raise_flag("2026-10-05")
        self.assertIsNotNone(account_check.pending_flag())
        second = accounts.add()
        accounts.switch(second.id)
        self.assertIsNone(account_check.pending_flag())
        accounts.switch("1")
        account_check.clear_flag()
        self.assertIsNone(account_check.pending_flag())


if __name__ == "__main__":
    unittest.main()


class TaiwanWordingTest(unittest.TestCase):
    def test_account_reads_as_taiwan_writes_it(self):
        from src.ui.traditional import to_traditional

        # OpenCC s2twp alone gives 賬號 (live 2026-10-09).
        self.assertEqual("新增帳號", to_traditional("新增账号"))
        self.assertEqual("每個帳號各自記日常", to_traditional("每个账号各自记日常"))
