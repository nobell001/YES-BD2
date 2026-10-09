"""Press a game button and only count it once the screen shows it worked.

Lost presses were the most common kind of failure: a slow or busy game drops
a click, the tool moves on as if it had worked, and either records a false
success or stops later somewhere unrelated.  Every press that matters goes
through ``press_and_confirm``:

1. press, then wait for ``confirmed()`` (always looked at at least once);
2. not confirmed, and the screen from before the press is still shown: wait
   ``retry_after`` (Leo: 1.5 s) and press once more;
3. still not confirmed: report it as not confirmed and let the caller decide
   (retry from home, stop, mark the item unfinished).

A second press is only made while ``still_before()`` says the screen has not
moved on, so a press that did work late is never repeated.  Presses that can
spend something (purchases, stamina, battles) pass ``retries=0``.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable, TypeVar

RETRY_AFTER_SECONDS = 1.5
CONFIRM_TIMEOUT_SECONDS = 3.0
POLL_SECONDS = 0.25

T = TypeVar("T")


def wait_for(
    check: Callable[[], T],
    timeout: float,
    *,
    sleep: Callable[[float], object],
    poll: float = POLL_SECONDS,
    clock: Callable[[], float] = monotonic,
) -> T | None:
    """First truthy ``check()`` within ``timeout`` seconds, else None.

    The check always runs at least once, also with ``timeout=0`` or when the
    previous step overran: a wait that never looks would report "not there"
    without having looked.
    """
    end_at = clock() + max(0.0, timeout)
    while True:
        result = check()
        if result:
            return result
        if clock() >= end_at:
            return None
        sleep(poll)


@dataclass(frozen=True)
class PressOutcome:
    confirmed: bool
    presses: int
    # confirmed | confirmed-after-retry | late | moved-on | not-confirmed
    reason: str

    def __bool__(self) -> bool:
        return self.confirmed


def press_and_confirm(
    label: str,
    press: Callable[[], object],
    confirmed: Callable[[], object],
    *,
    sleep: Callable[[float], object],
    log: Callable[[str], object],
    still_before: Callable[[], object] | None = None,
    timeout: float = CONFIRM_TIMEOUT_SECONDS,
    retry_after: float = RETRY_AFTER_SECONDS,
    retries: int = 1,
    poll: float = POLL_SECONDS,
    clock: Callable[[], float] = monotonic,
) -> PressOutcome:
    """Press, confirm on screen, re-press once while nothing changed.

    ``still_before`` must say whether the screen from before the press is
    still shown; without it no second press is made.
    """
    presses = 0
    for attempt in range(max(0, retries) + 1):
        if attempt:
            if still_before is None:
                break
            log(f"{label}：按了没看到结果，{retry_after:g}秒后补按一次。")
            sleep(retry_after)
            # a slow game may show the result while we waited
            if confirmed():
                return PressOutcome(True, presses, "late")
            if not still_before():
                log(f"{label}：画面已经不是按之前的样子，不再补按（未确认）。")
                return PressOutcome(False, presses, "moved-on")
        press()
        presses += 1
        if wait_for(confirmed, timeout, sleep=sleep, poll=poll, clock=clock):
            reason = "confirmed" if presses == 1 else "confirmed-after-retry"
            return PressOutcome(True, presses, reason)
    log(f"{label}：按了{presses}次都没看到结果（未确认）。")
    return PressOutcome(False, presses, "not-confirmed")
