"""Tell the player when the game itself is set to Traditional Chinese.

Every keyword the tool reads is the 简中 client's text (OCR 只识别简体中文,
2026-08-29).  A player on the 繁中 client (YES-BD2 issue #3, 2026-10-09)
saw the tool stop at the home check with no hint why.  Leo (2026-10-09)
chose to warn for now and support 繁中 later: the home checks note the text
they read, and a run that fails after 繁中 text was seen says to switch the
game to 简体中文.
"""

from __future__ import annotations

import threading
import time

# Characters only the 繁中 client shows (their 简中 forms differ), picked from
# common UI words: 抽抽樂 格魯 街機遊戲 經營 公會 圖鑑 戰鬥 裝備 領取 獎勵 ...
TRADITIONAL_ONLY = frozenset(
    "樂魯機遊戲經營會團隊圖鑑聖戰鬥裝備強關開門時間買賣廣場說設與從這個們來對點"
    "體當發現進還過選擇領獎勵貨幣購儲級轉換寶劍應聯絡務歡簽記錄類"
)
# Two different such characters in one read: a lone misread is not enough.
MIN_TRADITIONAL_CHARS = 2
# Home's own labels on the 繁中 client.  Other pages show players' own text
# in the same box: live 2K 10-10 a 繁中 guild description (申請請DC聯絡公會長)
# on the guild page of a 简中 client refused every start 76 times.
TRADITIONAL_HOME_LABELS = ("格魯", "街機遊戲", "抽抽樂", "經營管理")

NOTICE_KEY = "游戏语言提醒"
MESSAGE = (
    "游戏语言是繁体中文，工具目前只认得简体中文，所以认不出画面。"
    "请到游戏设置把语言改成简体中文，再重新执行。"
)
# One popup is enough while a batch's children fail one after another.
NOTIFY_GAP_SECONDS = 600.0

_lock = threading.Lock()
_state = {"seen_at": 0.0, "notified_at": 0.0}


def looks_traditional(text: object) -> bool:
    found = {character for character in str(text or "") if character in TRADITIONAL_ONLY}
    return len(found) >= MIN_TRADITIONAL_CHARS


def traditional_home_labels(text: object) -> int:
    """How many of home's 繁中 labels the read holds (a player's text has none)."""
    compact = "".join(str(text or "").split())
    return sum(1 for label in TRADITIONAL_HOME_LABELS if label in compact)


def note_text(text: object, now: float | None = None) -> bool:
    """Called with home-check OCR text; remembers when 繁中 home text was seen."""
    if not looks_traditional(text) or not traditional_home_labels(text):
        return False
    with _lock:
        _state["seen_at"] = time.monotonic() if now is None else now
    return True


def seen_since(started: float) -> bool:
    with _lock:
        seen_at = _state["seen_at"]
    return bool(seen_at) and seen_at >= started


def _should_notify(now: float) -> bool:
    with _lock:
        last = _state["notified_at"]
        if last and now - last < NOTIFY_GAP_SECONDS:
            return False
        _state["notified_at"] = now
        return True


def warn_after_failure(task, started: float, now: float | None = None) -> str:
    """After a failed run: the 繁中 hint when this run saw 繁中 text, else ""."""
    if not seen_since(started):
        return ""
    now = time.monotonic() if now is None else now
    try:
        task.info_set(NOTICE_KEY, MESSAGE)
    except Exception:
        pass
    # Never let the hint replace the real failure or skip going home.
    try:
        warn = getattr(task, "log_warning", None)
        if callable(warn):
            warn(MESSAGE, notify=_should_notify(now))
    except Exception:
        pass
    return MESSAGE


def reset() -> None:
    with _lock:
        _state.update(seen_at=0.0, notified_at=0.0)
