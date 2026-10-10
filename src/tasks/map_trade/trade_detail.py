"""What one trade run sold and cooked, for the results page and 今日报表.

YES-BD2 #6 (2026-10-10): after a run players could not tell whether the
trade really sold anything or cooked the 5星 dishes, although the log had
it.  The run collects it here; at the end it goes under the 每日跑商 row as
item and dish pictures (Leo: the text with the item pictures, no screenshots).
"""

from __future__ import annotations

import re

from src.tasks import run_report
from src.tasks.map_trade.models import OPTIONAL_COOKING_RECIPES


class TradeDetail:
    def __init__(self) -> None:
        self.sold: dict[str, int | None] = {}
        self.cooked: dict[str, int | None] = {}

    def add_sale(self, item: str, quantity: int | None) -> None:
        if item not in self.sold:
            self.sold[item] = quantity
        elif quantity is not None:
            self.sold[item] = (self.sold[item] or 0) + quantity

    def add_dish(self, recipe: str, quantity: int | None = None) -> None:
        if recipe not in self.cooked or quantity is not None:
            self.cooked[recipe] = quantity

    def summary(self) -> dict:
        return {
            "sold": [[item, quantity] for item, quantity in self.sold.items()],
            "cooked": [[recipe, quantity] for recipe, quantity in self.cooked.items()],
        }

    def line(self) -> str:
        """For the log: 「卖了 兽肉 ×1980、红酒 ×600；做了 香草牛排、5星 透明沙拉」."""
        parts = []
        if self.sold:
            parts.append("卖了 " + "、".join(_counted(*pair) for pair in self.sold.items()))
        if self.cooked:
            parts.append(
                "做了 "
                + "、".join(
                    ("5星 " if recipe in OPTIONAL_COOKING_RECIPES else "")
                    + _counted(recipe, quantity)
                    for recipe, quantity in self.cooked.items()
                )
            )
        return "；".join(parts)


def _counted(name: str, quantity: int | None) -> str:
    return name if quantity is None else f"{name} ×{quantity}"


# 「香草牛排×98」: a name, ×, a count.  The bar can still show the dish made
# before (live 2026-10-10: 「冰镇甜点×50 香草牛排×98」 was counted as 98).
_RESULT_ENTRY = re.compile(r"([^\s×xX＊*\d]+)\s*[×xX＊*]\s*(\d+)")
# How much of the recipe's name an entry must share to be this dish's
# (OCR mixes 黄 and 黃).
_NAME_SHARE = 0.5


def _shared(recipe: str, name: str) -> float:
    letters = set(recipe)
    return len(letters & set(name)) / len(letters) if letters else 0.0


def result_quantity(text: str, recipe: str = "") -> int | None:
    """How many the cooking result bar says were made (「香草牛排×260」).

    With ``recipe``, the count after that dish's own name: the bar may still
    show the dish made just before it."""
    normalized = str(text or "").replace(",", "").replace("，", "")
    if recipe:
        best = None
        for name, value in _RESULT_ENTRY.findall(normalized):
            share = _shared(recipe, name)
            if share >= _NAME_SHARE and int(value) > 0 and (best is None or share > best[0]):
                best = (share, int(value))
        if best is not None:
            return best[1]
    marked = re.findall(r"[×xX＊*]\s*(\d+)", normalized)
    values = marked or re.findall(r"\d+", normalized)
    numbers = [int(value) for value in values if int(value) > 0]
    return max(numbers) if numbers else None


def note_sale(owner, item: str, quantity: int | None) -> None:
    detail = getattr(owner, "trade_detail", None)
    if detail is not None:
        detail.add_sale(item, quantity)


def note_dish(owner, recipe: str, result_text: str = "") -> None:
    detail = getattr(owner, "trade_detail", None)
    if detail is not None:
        detail.add_dish(recipe, result_quantity(result_text, recipe))


def publish(task, detail: TradeDetail | None) -> None:
    """Hand the run's sales and dishes to the report (once, at the end)."""
    if detail is None or not (detail.sold or detail.cooked):
        return
    task.log_info(f"跑商：{detail.line()}。")
    run_report.add_trade(detail.summary())
