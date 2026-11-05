"""Parsing and stepping helpers for the mirror-battle auto-battle dialog.

Layout observed 2026-09-26 (简体 client, 1920x1080 reference): the dialog
shows "N倍 ⚙" (per-battle cocktail multiplier, 1~40, set in a sub-dialog with
MIN / -5 / +5 / MAX and -/+), the 仅使用免费鲜血鸡尾酒 switch, and the battle
count "自动战斗N次" with MIN / -10 / +10 / MAX and -/+.  The start button
reads "战斗开始 🍹C" where C is the per-battle cost (equal to the multiplier,
live 2026-09-26; ``PVPTask._verify_free_cost`` relies on it); the top bar
shows the free cocktails as "36/40" followed by the paid pool.
"""

from __future__ import annotations

import re

from src.utils.ocr_numbers import pool_amount, within

MULTIPLIER_RANGE = (1, 40)

_MULTIPLIER = re.compile(r"(\d{1,2})\s*倍")
_BATTLE_COUNT = re.compile(r"自动战斗\s*(\d{1,3})\s*次")
_FREE_POOL = re.compile(r"(?<![\d,.])(\d{1,2})\s*[/／]\s*(\d{1,2})(?!\d)")


def parse_multiplier(text: object) -> int | None:
    match = _MULTIPLIER.search(str(text))
    return within(int(match.group(1)), *MULTIPLIER_RANGE) if match else None


def parse_battle_count(text: object) -> int | None:
    match = _BATTLE_COUNT.search(str(text).replace(" ", ""))
    return int(match.group(1)) if match else None


def parse_start_cost(text: object) -> int | None:
    """Cost C from the start button text '战斗开始🍹C' (icon may OCR as noise)."""
    raw = str(text)
    index = raw.find("战斗开始")
    if index < 0:
        return None
    digits = re.findall(r"\d+", raw[index + len("战斗开始") :])
    return int(digits[-1]) if digits else None


def parse_free_cocktails(text: object) -> int | None:
    """Free cocktails a from 'a/40' in the top bar; the paid pool follows it.

    a may be above 40 ("50/40", player 2026-10-18: rewards pile free
    cocktails past the daily refill); 倍数 x 场数 stays capped at 40 anyway."""
    match = _FREE_POOL.search(str(text))
    if not match:
        return None
    return pool_amount(
        int(match.group(1)), int(match.group(2)), top_range=(1, 99), amount_max=99
    )


def free_cocktails_problem(text: object) -> str:
    """Why parse_free_cocktails gave nothing for ``text``, in the player's words."""
    raw = " ".join(str(text or "").split())
    if not raw:
        return "右上角一个字都没读到"
    match = re.search(r"(\d+)\s*[/／]\s*(\d+)", raw)
    if not match:
        return f"右上角读到「{raw[:30]}」，里面没有「数字/40」"
    amount, top = match.group(1), match.group(2)
    if len(amount) > 2:
        # 273/40 (player v0.2.11 2026-10-24): left as is by Leo, said plainly.
        return (
            f"右上角读到 {amount}/{top}，免费鸡尾酒超过 99 个，"
            "工具只认得 99 个以内，为免读错不开打"
        )
    return f"右上角读到 {amount}/{top}，后面的上限不是正常的数字"


def adjust_step(current: int, target: int, big_step: int) -> str | None:
    """Button to press next: big_plus / big_minus / plus / minus (None: done)."""
    difference = target - current
    if difference == 0:
        return None
    if difference >= big_step:
        return "big_plus"
    if difference <= -big_step:
        return "big_minus"
    return "plus" if difference > 0 else "minus"


def step_moves(step: str, big_step: int) -> int:
    """How far one press of ``step`` moves the value."""
    return {"big_plus": big_step, "big_minus": -big_step, "plus": 1, "minus": -1}[step]


def steps_between(start: int, target: int, big_step: int) -> list[str]:
    """The presses that take the value from ``start`` to ``target``."""
    presses = []
    current = start
    while (step := adjust_step(current, target, big_step)) is not None:
        presses.append(step)
        current += step_moves(step, big_step)
    return presses


# The 倍率 setting dialog's buttons, pressed in the game (2K clone, 2026-11-05,
# every value 1~40 walked by +5 / -5): +1 / -1 move by one and stop at 40 / 1,
# -5 moves down five and stops at 1, +5 moves up five and stops at 40 — except
# from 1, where +5 gives 5, not 6.  Counting 1 +5 as 6 left every target from
# 6 to 39 one short (a player v0.2.31 2026-11-05: 10 wanted, 9倍 set).
MULTIPLIER_MIN_STEPS = ("big_plus", "plus")
MULTIPLIER_MAX_STEPS = ("big_minus", "minus")


def multiplier_after(value: int, step: str) -> int:
    """The setting dialog's value after one press of ``step`` on ``value``."""
    low, high = MULTIPLIER_RANGE
    if step == "big_plus":
        return 5 if value == low else min(high, value + 5)
    if step == "big_minus":
        return max(low, value - 5)
    if step == "plus":
        return min(high, value + 1)
    if step == "minus":
        return max(low, value - 1)
    raise ValueError(step)


def multiplier_presses(start: int, target: int) -> list[str]:
    """Fewest presses from ``start`` to ``target`` in the setting dialog.

    One way only (up with +5 / +1, down with -5 / -1) and never past the
    target, so a value read on the far side of the target is a misread, not
    an overshoot to step back from (a player 2026-10-21: 「一直点右边+1 和-5
    死循环了」)."""
    if start == target:
        return []
    upward = target > start
    steps = MULTIPLIER_MIN_STEPS if upward else MULTIPLIER_MAX_STEPS
    paths = {start: []}
    frontier = [start]
    while frontier and target not in paths:
        reached = []
        for value in frontier:
            for step in steps:
                after = multiplier_after(value, step)
                between = value < after <= target if upward else target <= after < value
                if between and after not in paths:
                    paths[after] = paths[value] + [step]
                    reached.append(after)
        frontier = reached
    return paths.get(target, [])


def multiplier_plan(target: int) -> tuple[int, list[str]]:
    """Where to start (MIN 1 or MAX 40) and the presses from there: the
    shorter of the two, MIN on a tie."""
    low, high = MULTIPLIER_RANGE
    up, down = multiplier_presses(low, target), multiplier_presses(high, target)
    if target == high or len(down) < len(up):
        return high, down
    return low, up
