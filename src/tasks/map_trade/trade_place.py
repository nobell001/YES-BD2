"""Where 跑商 meets the merchant (Leo 2026-11-18).

Since 2026-10-20 the run trades with 洛兹 in 梦幻广场 and story cartridge 1's
无聊收集狂大叔 was only the way out when the square failed.  Players said the
square gets stuck, so the player picks one; the other stays the way out
(Leo 「總有替代方案」).
"""

from __future__ import annotations

TRADE_PLACE_KEY = "跑商地点"
PLACE_SQUARE = "广场"
PLACE_CHAPTER1 = "第一章"
TRADE_PLACES = (PLACE_SQUARE, PLACE_CHAPTER1)
DEFAULT_TRADE_PLACE = PLACE_SQUARE


def trade_place(config) -> str:
    """The picked place; anything unknown (an old config, a typo) is the square."""
    try:
        value = str((config or {}).get(TRADE_PLACE_KEY) or "").strip()
    except AttributeError:
        return DEFAULT_TRADE_PLACE
    return value if value in TRADE_PLACES else DEFAULT_TRADE_PLACE
