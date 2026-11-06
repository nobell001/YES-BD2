"""A run whose screen stops changing while the tool presses nothing is stuck.

Leo 2026-10-13, after a player's 活动每日战斗 stayed on the event page until
it was stopped: 「卡住卡個10秒就很怪了」「點擊沒反應 或者辨識不到卡住 那就回主頁
可以的話就重試沒辦法就下一步」「不要整個卡死」.  A daily task's frames are
watched: the same picture for FROZEN_SCREEN_SECONDS with no press or key from
the tool in between raises FrozenScreen; the run then goes home, tries once
more where that is safe, else ends as failed and 一键日常 goes on.

Game screens move (idle animation, particles, loading spinners), so a picture
that stays the same while the tool waits means nothing is coming.  Captures
further apart than FROZEN_GAP_SECONDS (a pause, a long sleep) start the count
over: only time spent looking counts.

Leo 2026-10-15 「我說的10秒是卡死 或者辨識不到」「注意其他等載入的地方不要只有
10秒」: a black loading screen is the game working, not stuck; it is watched
up to LOADING_MAX_SECONDS instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from time import monotonic

import cv2
import numpy as np

from src.utils.wait_limits import (
    CHANGED_LOAD_SECONDS,
    LOADING_MAX_SECONDS,
    STUCK_SECONDS,
    is_loading_dark,
    scene_moved,
)

# Leo 2026-10-14 「頂多等8秒到10秒」: was 15 s.  A slow-PC re-look
# (SLOW_PC_GRACE_SECONDS, 5 s) still fits.
FROZEN_SCREEN_SECONDS = STUCK_SECONDS
FROZEN_GAP_SECONDS = 5.0
THUMB_SIZE = (192, 108)
# A pixel this much brighter or darker counts as changed; this many changed
# pixels of the thumbnail make a changed screen (a small spinner is enough).
PIXEL_DIFF = 6
CHANGED_PIXELS = 4
# Presses in a row that left the screen exactly as it was (Leo 2026-10-14:
# the login's clear spot was pressed 29 times under a 恭喜晋级 page that only
# its 确认 closes).  From this many on, a known popup is looked for first.
INEFFECTIVE_PRESSES = 3
# Words of a loading or connecting screen that is not black (Leo 2026-10-18
# 「有人電腦比較卡」: a slow PC or network keeps it up past FROZEN_SCREEN_SECONDS
# without moving).  Such a still screen is waited for up to
# LOADING_WORDS_SECONDS (Leo 2026-10-18 「黑畫面一樣30秒 第二個20秒」).
# Not "BROWNDUST": the home announcement banner carries the logo too.
# Leo 2026-10-20 「改成45秒」: the same cap as the black loading screen.
LOADING_WORDS_SECONDS = LOADING_MAX_SECONDS
# Presses reset the still count above (a press may still be working), so a
# tool pressing on and on at a screen that never changes was never called
# stuck: a dead shop back button for 10 s (player 11-02), the login's clear
# spot pressed 29 times (10-14).  Leo 2026-11-05 「一直在按、但一直沒到下一個
# 畫面也算卡住」: the same picture this long, with at least this many presses
# that changed nothing, is stuck too.  Three still limits: a slow PC's late
# answer and a re-press fit well inside it.
PRESSED_STILL_SECONDS = 3 * FROZEN_SCREEN_SECONDS
PRESSED_STILL_MIN_PRESSES = 3
LOADING_WORDS = ("nowloading", "loading", "加载", "载入", "读取中", "连接中", "连线中", "通信中", "请稍候")


def loading_words(text: object) -> str:
    """The loading word the text shows ("" when none)."""
    flat = "".join(str(text or "").split()).lower()
    return next((word for word in LOADING_WORDS if word in flat), "")


# The game's loading ring sits in the bottom-right corner with its percent
# inside (1080p player 2026-10-20: 「MIRROR WARS 镜中之战」 at 94% was given up
# on after the 30 s cap; Leo 「10秒限制 不該在這種時候」).  A percent read
# there is a loading screen, whatever the picture above it (held like a
# loading word, up to LOADING_WORDS_SECONDS).
LOADING_PERCENT_CORNER = 0.75
_PERCENT = re.compile(r"^(\d{1,3})\s*[%％]$")


def loading_percent(boxes, width: int, height: int) -> str:
    """The loading ring's percent ("94%") among OCR ``boxes``, "" when none."""
    for box in boxes or ():
        match = _PERCENT.match("".join(str(getattr(box, "name", "") or "").split()))
        if not match or int(match.group(1)) > 100:
            continue
        try:
            cx = float(box.x) + float(box.width) / 2
            cy = float(box.y) + float(box.height) / 2
        except (AttributeError, TypeError, ValueError):
            continue
        if cx >= width * LOADING_PERCENT_CORNER and cy >= height * LOADING_PERCENT_CORNER:
            return f"{int(match.group(1))}%"
    return ""


# The loading ring itself, as a fraction of the frame (1920x1080: x 1770-1910,
# y 930-1070).  Measured on 15 scene loading screens (镜中之战 11, 餐厅 2,
# 广场 2; 4K PC clone 1080p 2026-11-05): an OCR of this crop read the percent
# on all 15, a whole-frame OCR on none of the 4 tried, and a wider corner
# crop missed one.  Over 272 saved frames this crop read a percent on those
# 15 only; the wider corner also holds the 跑商 price change (+112% read as
# 4112%).
LOADING_RING_ROI = (1770 / 1920, 930 / 1080, 1910 / 1920, 1070 / 1080)


def ring_crop(frame):
    """The loading ring's part of ``frame`` (LOADING_RING_ROI)."""
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = LOADING_RING_ROI
    return frame[int(y0 * height) : int(y1 * height), int(x0 * width) : int(x1 * width)]


def ring_percent(boxes) -> str:
    """A percent ("94%") read inside the ring crop, "" when none."""
    for box in boxes or ():
        match = _PERCENT.match("".join(str(getattr(box, "name", "") or "").split()))
        if match and int(match.group(1)) <= 100:
            return f"{int(match.group(1))}%"
    return ""


def loading_sign(boxes, width: int, height: int) -> str:
    """What marks the OCR'd frame as a loading screen: its ring's percent or
    a loading word ("" when neither)."""
    return loading_percent(boxes, width, height) or loading_words(
        " ".join(str(getattr(box, "name", "")) for box in boxes or ())
    )


class FrozenScreen(Exception):
    """The screen did not change for FROZEN_SCREEN_SECONDS without a press.

    A task's own stuck check raises it too, with the reason as its message.
    """


def thumbnail(frame) -> np.ndarray | None:
    if frame is None or getattr(frame, "size", 0) == 0 or frame.ndim not in (2, 3):
        return None
    image = frame if frame.ndim == 2 else cv2.cvtColor(
        np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2GRAY
    )
    return cv2.resize(image, THUMB_SIZE, interpolation=cv2.INTER_AREA)


def changed(a: np.ndarray, b: np.ndarray) -> bool:
    if a.shape != b.shape:
        return True
    diff = cv2.absdiff(a, b)
    return int(np.count_nonzero(diff > PIXEL_DIFF)) >= CHANGED_PIXELS


@dataclass
class FrozenWatch:
    """The picture the still time started from, when, and the last look."""

    seconds: float = FROZEN_SCREEN_SECONDS
    picture: np.ndarray | None = None
    since: float = 0.0
    seen: float = 0.0
    paused: int = 0
    fired: bool = False
    last: np.ndarray | None = None
    at_last_press: np.ndarray | None = None
    last_point: tuple | None = None
    ineffective: int = 0
    # A still screen that reads as loading (hold_for_loading): waited for up
    # to LOADING_WORDS_SECONDS until the picture changes.
    loading_hold: bool = False
    loading_word: str = ""
    # The same picture across presses (PRESSED_STILL_SECONDS): since when,
    # and how many presses it has stayed the same through.
    still_picture: np.ndarray | None = None
    still_from: float = 0.0
    presses_while_still: int = 0

    def hold_for_loading(self, word: str = "") -> None:
        """The still screen that just fired shows loading words: keep
        watching it up to LOADING_WORDS_SECONDS instead."""
        self.fired = False
        self.loading_hold = True
        self.loading_word = word

    def pressed(self, point: tuple | None = None) -> None:
        """The tool pressed or typed something: count from the next look.

        Also counts clicks in a row on the same spot whose screen before was
        the same as at the click before (nothing they did changed it)."""
        self.picture = None
        if (
            point is not None
            and point == self.last_point
            and self.last is not None
            and self.at_last_press is not None
            and not changed(self.last, self.at_last_press)
        ):
            self.ineffective += 1
        else:
            self.ineffective = 0
        self.at_last_press = self.last
        self.last_point = point
        if self.still_picture is not None:
            self.presses_while_still += 1

    def progress(self) -> None:
        """The tool just recognised what it was waiting for: count from the
        next look.  Leo 2026-10-15 「我說的10秒是卡死 或者辨識不到」: a still
        page that is being read is not stuck (a player's slow 1080p PC spent
        over 10 s reading the static buy page and was stopped, 2026-10-16)."""
        self.picture = None
        self.still_picture = None

    def look(self, frame, now: float | None = None) -> None:
        """Raise FrozenScreen once the screen has been still long enough."""
        if self.paused:
            return
        if self.fired:
            raise FrozenScreen()
        now = monotonic() if now is None else now
        picture = thumbnail(frame)
        if picture is None:
            return
        self.last = picture
        if (
            self.picture is None
            or now - self.seen > FROZEN_GAP_SECONDS
            or changed(picture, self.picture)
        ):
            self.picture, self.since = picture, now
            self.loading_hold = False
        if (
            self.still_picture is None
            or now - self.seen > FROZEN_GAP_SECONDS
            or changed(picture, self.still_picture)
        ):
            self.still_picture, self.still_from, self.presses_while_still = picture, now, 0
        self.seen = now
        # The black loading screen (a faint logo at most) may stand still
        # for longer than a stuck page (Leo 2026-10-15 「一定會超過10秒甚至15秒」).
        loading = is_loading_dark(picture[..., None])
        changed_by_press = not loading and scene_moved(self.at_last_press, picture)
        if loading:
            limit = max(self.seconds, LOADING_MAX_SECONDS)
        elif self.loading_hold:
            limit = max(self.seconds, LOADING_WORDS_SECONDS)
        elif changed_by_press:
            # The last press changed the screen: it is loading, not 按了没反应
            # (Leo 2026-10-19 「可以20秒」), whatever it looks like.
            limit = max(self.seconds, CHANGED_LOAD_SECONDS)
        else:
            limit = self.seconds
        if (
            not loading
            and not self.loading_hold
            and self.presses_while_still >= PRESSED_STILL_MIN_PRESSES
            and now - self.still_from >= PRESSED_STILL_SECONDS
        ):
            self.fired = True
            raise FrozenScreen(
                f"点了 {self.presses_while_still} 次，画面 {now - self.still_from:.0f} 秒都没有变化"
                "（点了没反应，或认不出这个画面）"
            )
        if now - self.since >= limit:
            self.fired = True
            # Leo 2026-10-18 「卡住要寫原因」: which screen, how long, why.
            if self.loading_hold:
                raise FrozenScreen(
                    f"画面停在「{self.loading_word or '加载'}」{limit:.0f} 秒没有结束"
                    "（可能网络或电脑比较慢）"
                )
            if loading:
                raise FrozenScreen(
                    f"黑色加载画面 {limit:.0f} 秒没有结束（可能网络或电脑比较慢）"
                )
            if changed_by_press:
                raise FrozenScreen(
                    f"点了之后画面换了，但停了 {limit:.0f} 秒没有往下走"
                    "（可能网络或电脑比较慢，或认不出这个画面）"
                )
            raise FrozenScreen()
