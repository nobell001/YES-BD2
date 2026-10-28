"""Which costumes the 亲密度谈心 task opens (Leo 2026-10-21).

- LV20, not remembered as finished: talked until 谈心记录 15/15 (no daily
  limit at LV20), then remembered and never opened again.
- Below LV20: one talk per costume a day, 「今日剩余谈心次数」 (3) in all.
  Costumes whose answers are in the bank come first (souseha lags behind
  new costumes; Leo agreed 02:11Z), costumes found locked at LV15 last (no
  affinity until the costume's potential is released).
- A card whose level is not read is not owned (Leo 02:12Z): never opened.
- A card marked 「未拥有」 (greyed, still 「LV.1 (0%)」) is never opened
  either (Leo 2026-10-28 「看到未擁有就不要點 純浪費時間」).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.tasks.affinity.answers import find_costume
from src.tasks.affinity.record import TalkRecord
from src.tasks.affinity.screen import MAX_LEVEL, Card


@dataclass(frozen=True)
class Plan:
    finish: list[Card]  # LV20 to talk up to 15/15
    daily: list[Card]  # below LV20, best first
    talks_left: int | None  # 今日剩余谈心次数, None when not read


def make_plan(cards: list[Card], record: TalkRecord, today: str, talks_left: int | None) -> Plan:
    seen = set()
    unique = []
    for card in cards:
        if card.key not in seen and card.level is not None and card.owned:
            seen.add(card.key)
            unique.append(card)
    finish = [c for c in unique if c.level >= MAX_LEVEL and c.key not in record.done]
    talked = record.talked_today(today)
    daily = []
    if talks_left is None or talks_left > 0:
        below = [c for c in unique if c.level < MAX_LEVEL and c.key not in talked]
        daily = sorted(
            below,
            key=lambda c: (
                c.key in record.locked,
                find_costume(c.costume, c.character) is None,
            ),
        )
    return Plan(finish=finish, daily=daily, talks_left=talks_left)
