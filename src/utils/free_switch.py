"""Turn on a 仅使用免费… switch with at most one press (review #28).

PVP, quick hunt and event battles judge the switch by its yellow colour only.
When that yellow is not recognised (a colour filter, a recoloured switch) a
switch that is already on reads as off, and pressing until it reads on left
the player's own safety switch off.  So a second press is made only when the
first one changed nothing at all (a press the network swallowed,
BUG-20260906-01); a press that made the switch less yellow is pressed back
and the step stops.
"""

from __future__ import annotations

from typing import Callable

from src.utils.colour_check import last_check
from src.utils.press_confirm import press_and_confirm

# A press that left the switch this much less yellow turned it off: it was on.
LESS_YELLOW_MARGIN = 0.01
# A dialog still drawing reads as off: look once more before pressing.
SECOND_LOOK_SECONDS = 0.5


def ensure_free_switch_on(
    label: str,
    yellow_ratio: Callable[[], float],
    press: Callable[[], object],
    *,
    on_above: float,
    settle: float,
    sleep: Callable[[float], object],
    log: Callable[[str], object],
) -> bool:
    """True once the switch reads on; False (and stopped) otherwise."""

    before = yellow_ratio()
    if before <= on_above:
        sleep(SECOND_LOOK_SECONDS)
        before = max(before, yellow_ratio())
    if before > on_above:
        return True
    check = last_check()
    if check is not None and check.distorted:
        log(f"{label}：画面颜色异常，认不准「仅使用免费」开关，不去按它，取消。")
        return False
    def unchanged() -> bool:
        return abs(yellow_ratio() - before) <= LESS_YELLOW_MARGIN

    outcome = press_and_confirm(
        label,
        press,
        lambda: yellow_ratio() > on_above,
        sleep=sleep,
        log=log,
        still_before=unchanged,
        timeout=settle,
        retries=1,
    )
    if outcome:
        return True
    after = yellow_ratio()
    if after < before - LESS_YELLOW_MARGIN:
        log(
            f"{label}：按了之后开关反而变暗（黄色 {before:.3f}→{after:.3f}），"
            "原本应该是开着的，按回去后取消。"
        )
        press_and_confirm(
            f"{label}（按回去）",
            press,
            lambda: yellow_ratio() >= before - LESS_YELLOW_MARGIN,
            sleep=sleep,
            log=log,
            still_before=lambda: yellow_ratio() < before - LESS_YELLOW_MARGIN,
            timeout=settle,
            retries=1,
        )
        return False
    log(f"{label}：按了仍认不出已开启（黄色 {before:.3f}→{after:.3f}），不再按，取消。")
    return False
