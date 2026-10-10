"""Catch 跑图 records that belong to another game account (GitHub issue #4).

A player with several accounts may switch accounts in the game and forget to
switch in the tool.  The records then say a card was finished this week while
the game shows it untouched, and 跑图 would skip it.  Before trusting those
records the card's own badges are read (no skill is pressed): when every
checked card the records call finished shows both badges still open, twice
each, the records are not this account's.  The run stops and the home page
asks the player (Leo 2026-10-09).

Playing by hand, or starting the tool mid-week, only ever puts more progress
on screen than in the records, so it never trips this check.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.tasks.map_trade.card_status import CardActionState
from src.tasks.map_trade.collector_constants import UNSUPPORTED_COLLECTION_CARD_NUMBERS
from src.tasks.map_trade.models import (
    ABSORB_ONLY_VERIFIED_CARD_IDS,
    COLLECTABLE_CARDS,
    SUPPRESS_ONLY_VERIFIED_CARD_IDS,
)
from src.utils import accounts

CARDS_TO_CHECK = 2
READS_PER_CARD = 2
FLAG_FILE = Path("configs") / "account_mismatch.json"
MESSAGE = "跑图记录和游戏画面对不上，可能换了账号：已停下，没有按任何技能"


def _untouched(result) -> bool | None:
    """True: both badges clearly open; False: something done; None: unsure."""
    completion = getattr(result, "completion", None)
    if completion is None or not completion.complete_region:
        return None
    suppress = completion.suppress.state
    absorb = completion.absorb.state
    if CardActionState.COMPLETED in (suppress, absorb):
        return False
    if suppress != CardActionState.PENDING:
        return None
    if absorb == CardActionState.PENDING:
        return True
    return None


def card_ids_to_check(state, allowed) -> list[str]:
    """The last finished cards in run order: two accounts that both ran this
    week share the front cards, so checking the first two missed the switch
    (audit #3); the cards run last are the ones the other account lacks."""
    picked = []
    for card in reversed(COLLECTABLE_CARDS):
        if card.number in UNSUPPORTED_COLLECTION_CARD_NUMBERS:
            continue
        if card.card_id in SUPPRESS_ONLY_VERIFIED_CARD_IDS:
            continue  # their 吸取 badge never settles; not clear enough
        if card.card_id in ABSORB_ONLY_VERIFIED_CARD_IDS:
            continue  # no 压制 badge to read; not clear enough
        if allowed is not None and card.filter_key not in allowed:
            continue
        if state.card_verified(card.card_id):
            picked.append(card.card_id)
        if len(picked) >= CARDS_TO_CHECK:
            break
    return picked


def records_from_other_account(navigator, state, allowed=None) -> bool:
    """Whether the cards recorded as finished are all untouched in the game."""
    card_ids = card_ids_to_check(state, allowed)
    if not card_ids:
        return False
    for card_id in card_ids:
        for _read in range(READS_PER_CARD):
            seen = _untouched(navigator.inspect_collection_card_completion(card_id))
            if seen is not True:
                return False
    return True


def _flag_path() -> Path:
    return Path(accounts.scoped(FLAG_FILE))


def raise_flag(week: str) -> None:
    path = _flag_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"week": week, "at": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass  # the run's own failure text still says what happened


def pending_flag() -> dict | None:
    try:
        value = json.loads(_flag_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def clear_flag() -> None:
    try:
        _flag_path().unlink(missing_ok=True)
    except OSError:
        pass
