"""How many 招募契约书 and 史莱姆 may be sold (Leo, 2026-11-10).

Both are real account assets that old players overflow on, so the game lets
them be sold.  The player says what must stay; only the surplus is sold.

契约书: three tiers, ten of one combine into one of the next, and one top
tier recruits one 5-star character.  The player sets "keep enough to recruit
N 5-star characters".  The top tier is kept first, then the middle, then the
lowest; when everything together is worth fewer than N, nothing is sold.

史莱姆: one keep amount per colour.  The sale slider is coarse on tens of
thousands, so what is left may be 5% under to 10% over the keep amount.
"""

from __future__ import annotations

from dataclasses import dataclass

# Worth of one book of each tier, counted in lowest-tier books.
CONTRACT_TOP_WORTH = 100
CONTRACT_MIDDLE_WORTH = 10

SLIME_KEEP_UNDER_RATIO = 0.05
SLIME_KEEP_OVER_RATIO = 0.10


@dataclass(frozen=True)
class ContractCounts:
    """Books per tier."""

    top: int = 0
    middle: int = 0
    low: int = 0

    def __post_init__(self) -> None:
        for value in (self.top, self.middle, self.low):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("契约书数量必须是非负整数")

    @property
    def worth(self) -> int:
        """Everything together, in lowest-tier books."""
        return self.top * CONTRACT_TOP_WORTH + self.middle * CONTRACT_MIDDLE_WORTH + self.low


def contracts_to_keep(owned: ContractCounts, recruits: int) -> ContractCounts:
    """Books that stay so ``recruits`` 5-star characters can still be recruited."""

    if isinstance(recruits, bool) or not isinstance(recruits, int) or recruits < 0:
        raise ValueError("要保留的5星招募次数必须是非负整数")
    need = recruits * CONTRACT_TOP_WORTH
    top = min(owned.top, recruits)
    need -= top * CONTRACT_TOP_WORTH
    middle = min(owned.middle, -(-need // CONTRACT_MIDDLE_WORTH))
    need = max(0, need - middle * CONTRACT_MIDDLE_WORTH)
    low = min(owned.low, need)
    return ContractCounts(top=top, middle=middle, low=low)


def contracts_to_sell(owned: ContractCounts, recruits: int) -> ContractCounts:
    """The surplus per tier; all zero when the books cannot cover ``recruits``."""

    keep = contracts_to_keep(owned, recruits)
    return ContractCounts(
        top=owned.top - keep.top,
        middle=owned.middle - keep.middle,
        low=owned.low - keep.low,
    )


def slime_keep_range(keep: int) -> tuple[int, int]:
    """Lowest and highest amount that may be left after selling."""

    if isinstance(keep, bool) or not isinstance(keep, int) or keep < 0:
        raise ValueError("史莱姆保留量必须是非负整数")
    lowest = keep - int(keep * SLIME_KEEP_UNDER_RATIO)
    highest = keep + int(keep * SLIME_KEEP_OVER_RATIO)
    return lowest, highest


def slime_left_is_fine(owned: int, selected: int, keep: int) -> bool:
    """True when selling ``selected`` of ``owned`` leaves an allowed amount."""

    if selected <= 0 or selected > owned:
        return False
    lowest, highest = slime_keep_range(keep)
    return lowest <= owned - selected <= highest


# ---------------------------------------------------------------- settings
# Where and when the game pays ↑120% for them (Leo's sheet, 2026-11-10; seen
# in the game's 行情表 the same day).  The day only decides whether the shop
# is visited: the ↑120% marker on the item is still read before any sale.
SLIME_SALE_DAY = 10
SLIME_SHOP = "S3"
SELL_SLIMES_KEY = "卖史莱姆"
# (item as the 简中 client names it, the 繁中 name once simplified is the
# same; the setting that holds how many to keep)
SLIMES = (
    ("黄色史莱姆", "黄色史莱姆保留"),
    ("蓝色史莱姆", "蓝色史莱姆保留"),
    ("红色史莱姆", "红色史莱姆保留"),
)
SLIME_KEEP_KEYS = tuple(key for _item, key in SLIMES)
SLIME_ALIASES = {
    "黄色史莱姆": ("黃色史萊姆", "Yellow Slime"),
    "蓝色史莱姆": ("藍色史萊姆", "Blue Slime"),
    "红色史莱姆": ("紅色史萊姆", "Red Slime"),
}


def parse_keep(value) -> int | None:
    """The keep amount the player typed, or None when nothing usable is there.

    Leo 2026-11-10: 「預設讓玩家自己填 就算打開介面 沒有填就當不賣」 - no
    default; an empty (or unreadable) box means that asset is not sold.
    """

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value == int(value) else None
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text.isdecimal():
        return None
    return int(text)


def slime_sale_plan(config, day: int) -> tuple[list[tuple[str, int]], list[str]]:
    """(slimes to sell with their keep amount, slimes left alone and why).

    Empty on any day but the slimes' ↑120% day and while the switch is off.
    """

    if day != SLIME_SALE_DAY or not bool(config.get(SELL_SLIMES_KEY, False)):
        return [], []
    plan: list[tuple[str, int]] = []
    skipped: list[str] = []
    for item, key in SLIMES:
        keep = parse_keep(config.get(key, ""))
        if keep is None:
            skipped.append(f"{item}（没填要留多少）")
        else:
            plan.append((item, keep))
    return plan, skipped


CONTRACT_SALE_DAY = 1
CONTRACT_SHOP = "S1"
SELL_CONTRACTS_KEY = "卖招募契约书"
# 「至少能招募 N 个 5 星」; empty = not sold, 0 = sell every book.
CONTRACT_KEEP_KEY = "招募契约书保留5星"
# Highest tier first (简中 client names, Leo's 2026-11-10 screenshots); the
# 繁中 client calls them 最高級 / 高級 / 一般契約書.
CONTRACT_TIERS = ("顶级招募契约书", "高级招募契约书", "普通招募契约书")
CONTRACT_ALIASES = {
    "顶级招募契约书": ("最高级契约书", "最高級契約書"),
    "高级招募契约书": ("高级契约书", "高級契約書"),
    "普通招募契约书": ("一般契约书", "一般契約書"),
}


def contract_recruits(config, day: int) -> tuple[int | None, str]:
    """(N to keep, why nothing is sold).  N is None when books are not sold.

    Only on the books' ↑120% day, with the switch on and N typed in.
    """

    if day != CONTRACT_SALE_DAY or not bool(config.get(SELL_CONTRACTS_KEY, False)):
        return None, ""
    recruits = parse_keep(config.get(CONTRACT_KEEP_KEY, ""))
    if recruits is None:
        return None, "招募契约书（没填要留能招募几个5星）"
    return recruits, ""


def contract_plan(
    counted: dict[str, int], recruits: int
) -> tuple[dict[str, tuple[int, int]], ContractCounts, ContractCounts]:
    """Per tier that has a surplus: (owned, keep).  Also the counts and the keep.

    A tier that could not be counted is taken as 0 books and never sold: the
    other tiers then keep more, never fewer.
    """

    owned = ContractCounts(*(counted.get(item, 0) for item in CONTRACT_TIERS))
    keep = contracts_to_keep(owned, recruits)
    plan = {}
    for item, have, stay in zip(
        CONTRACT_TIERS, (owned.top, owned.middle, owned.low), (keep.top, keep.middle, keep.low)
    ):
        if item in counted and have > stay:
            plan[item] = (have, stay)
    return plan, owned, keep


# ---------------------------------------------------------------- the page
# Leo 2026-11-10: 「像今天可以賣史萊姆 然後我又有設定最低數量的話 那我的
# 出售日曆也要列出來」.  The page lists what the settings as they are now
# will sell, with the same rules the sale itself uses.
CONTRACTS_NAME = "招募书"  # the three tiers as one line


@dataclass(frozen=True)
class AssetLine:
    """One asset on the sale calendar: what it is and how much stays."""

    item: str
    keep: int
    # True: ``keep`` counts 5-star recruits (招募书), not pieces.
    recruits: bool = False


def asset_sale_days(config) -> dict[int, list[AssetLine]]:
    """day of the month → the assets these settings sell on that day."""

    days: dict[int, list[AssetLine]] = {}
    recruits, _why = contract_recruits(config, CONTRACT_SALE_DAY)
    if recruits is not None:
        days.setdefault(CONTRACT_SALE_DAY, []).append(
            AssetLine(CONTRACTS_NAME, recruits, recruits=True)
        )
    plan, _skipped = slime_sale_plan(config, SLIME_SALE_DAY)
    for item, keep in plan:
        days.setdefault(SLIME_SALE_DAY, []).append(AssetLine(item, keep))
    return days
