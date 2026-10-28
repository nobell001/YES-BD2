"""After a press: the screens that can come next, and the remedies in order.

MaaEnd lists, for every press, each screen that can follow it and what to do
there (its ``next``; Leo 2026-10-28 「maaend的next可以效仿」).  ``press_next``
does that here.  When none of the screens that end the step shows, it goes
through the same remedies as every other step (Leo 2026-10-28 「能不能有個統一
的標準 為了穩定性 補救方案」):

1. look again: each look reads the listed screens on one fresh frame, in
   order; while a listed loading screen shows, the look goes on (up to
   LOADING_MAX_SECONDS) and does not count as stuck;
2. a listed popup is handled (its ``then``) and the list is looked at again;
3. the screen the press was made on is still shown (a ``before`` screen):
   press once more;
4. still there: the game's key for the button (``key``);
5. still there: the button's usual place (``fixed``).

3 to 5 run only while a ``before`` screen is what was last seen: on a screen
that moved on, or one nobody listed, a press could land on something else.

A press that can spend, dismantle or confirm passes ``harmless=False``: it
only looks (1, 2) and is never pressed again.  Steps 6 and 7 (from the start
once more; skip and say why) belong to the caller, which gets the last screen
seen, in player words, for its failure message.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable, Sequence

from src.utils.press_confirm import CONFIRM_TIMEOUT_SECONDS, POLL_SECONDS, RETRY_AFTER_SECONDS
from src.utils.wait_limits import LOADING_MAX_SECONDS

# A popup handled more often than this in one step is not closing: the step
# goes on to its next remedy instead of looping on it.
HANDLE_LIMIT = 2
NOTHING_LISTED = "认不出的画面"


@dataclass(frozen=True)
class Next:
    """One screen that can follow a press."""

    name: str  # player words: 「商店页」「商人菜单」
    seen: Callable[[Any], object]  # a page check, on one frame
    goal: bool = False  # the step is done on this screen
    then: Callable[[Any], object] | None = None  # handle it (a popup), look again
    before: bool = False  # the screen the press was made on
    loading: bool = False  # a loading screen: look on, not stuck


@dataclass(frozen=True)
class NextOutcome:
    reached: bool
    # The goal reached, else the last listed screen seen (NOTHING_LISTED: none).
    screen: str
    # The remedy that got there: "" (the press itself), 补按, 快捷键 Esc, 固定位置.
    remedy: str = ""

    def __bool__(self) -> bool:
        return self.reached


def per_frame(read: Callable[[Any], object]) -> Callable[[Any], object]:
    """``read`` once per frame: several Next checks share one classify."""
    last: dict[str, object] = {}

    def cached(frame):
        if frame is None or last.get("frame") is not frame:
            last["frame"] = frame
            last["value"] = read(frame)
        return last["value"]

    return cached


def press_next(
    label: str,
    press: Callable[[], object],
    nexts: Sequence[Next],
    *,
    capture: Callable[[], Any],
    sleep: Callable[[float], object],
    log: Callable[[str], object],
    key: tuple[str, Callable[[], object]] | None = None,
    fixed: Callable[[], object] | None = None,
    harmless: bool = True,
    timeout: float = CONFIRM_TIMEOUT_SECONDS,
    retry_after: float = RETRY_AFTER_SECONDS,
    poll: float = POLL_SECONDS,
    clock: Callable[[], float] = monotonic,
) -> NextOutcome:
    """Press, then follow ``nexts``; the remedies in order until a goal shows."""

    if not any(item.goal for item in nexts):
        raise ValueError(f"{label}: no goal screen listed")
    handled: Counter[str] = Counter()

    def look() -> tuple[bool, str]:
        return _look(label, nexts, capture, timeout, sleep, log, poll, clock, handled)

    press()
    reached, last = look()
    if reached:
        return NextOutcome(True, last)
    remedies: list[tuple[str, Callable[[], object]]] = []
    if harmless:
        remedies.append(("补按", press))
        if key is not None:
            remedies.append((f"快捷键 {key[0]}", key[1]))
        if fixed is not None:
            remedies.append(("固定位置", fixed))
    goals = "、".join(item.name for item in nexts if item.goal)
    before = {item.name for item in nexts if item.before}
    for remedy, act in remedies:
        if last not in before:
            break  # the screen moved on: a press could land on something else
        if remedy == "补按":
            # A slow game may still show the result while we wait.
            sleep(retry_after)
            reached, last = look()
            if reached:
                return NextOutcome(True, last)
            if last not in before:
                break
        log(f"{label}：按了没看到{goals}（还是{last}），改用{remedy}。")
        act()
        reached, last = look()
        if reached:
            return NextOutcome(True, last, remedy)
    log(f"{label}：没看到{goals}，最后看到的是{last}。")
    return NextOutcome(False, last)


def _look(label, nexts, capture, timeout, sleep, log, poll, clock, handled) -> tuple[bool, str]:
    """Look until a goal shows or ``timeout`` passes with nothing changing it."""
    started = clock()
    end_at = started + max(0.0, timeout)
    loading_cap = None
    last = NOTHING_LISTED
    while True:
        frame = capture()
        seen = next((item for item in nexts if item.seen(frame)), None)
        if seen is not None:
            last = seen.name
            if seen.goal:
                return True, last
            if seen.then is not None and handled[seen.name] < HANDLE_LIMIT:
                handled[seen.name] += 1
                log(f"{label}：看到{seen.name}，先处理再看。")
                seen.then(frame)
                end_at = max(end_at, clock() + timeout)  # a fresh look after it
                continue
            if seen.loading:
                if loading_cap is None:
                    loading_cap = clock() + LOADING_MAX_SECONDS
                end_at = max(end_at, min(loading_cap, clock() + timeout))
        if clock() >= end_at:
            return False, last
        sleep(poll)
