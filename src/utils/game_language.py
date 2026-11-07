"""Which Chinese client the game is: 繁中 or 简中.

Every keyword the tool reads is the 简中 client's text.  A player on the 繁中
client (YES-BD2 issue #3, 2026-10-09) saw the tool stop at the home check.
Leo (2026-10-09) then asked for the 繁中 client to work: OCR results are turned
into the 简中 client's words (game_text), and this module remembers which
client the latest text came from, so game_text also rewrites words both
clients spell the same but use differently (繁中 搜索 = 简中 探查).

Problem reports note the client, so a failure on 繁中 is easy to spot.
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
# Their 简中 forms, the same words on the 简中 client.
SIMPLIFIED_ONLY = frozenset(
    "乐鲁机游戏经营会团队图鉴圣战斗装备强关开门时间买卖广场说设与从这个们来对点"
    "体当发现进还过选择领奖励货币购储级转换宝剑应联络务欢签记录类"
)
# Two different such characters in one read: a lone misread is not enough.
MIN_CLIENT_CHARS = 2
MIN_TRADITIONAL_CHARS = MIN_CLIENT_CHARS

# Home's own labels on each client.  Other pages show players' own text: live
# 2K 10-10 a 繁中 guild description (申請請DC聯絡公會長) on the guild page of a
# 简中 client read as 繁中.  So only a read holding one of home's labels says
# which client it is (every task starts from home, so that read comes often).
TRADITIONAL_HOME_LABELS = ("格魯", "街機遊戲", "抽抽樂", "經營管理")
SIMPLIFIED_HOME_LABELS = ("格鲁", "街机游戏", "抽抽乐", "经营管理")

INFO_KEY = "游戏语言"
TRADITIONAL_LABEL = "繁体中文"

_lock = threading.Lock()
_state = {"seen_at": 0.0, "simplified_at": 0.0}


def _count(text: object, characters: frozenset) -> int:
    return len({character for character in str(text or "") if character in characters})


def looks_traditional(text: object) -> bool:
    return _count(text, TRADITIONAL_ONLY) >= MIN_CLIENT_CHARS


def looks_simplified(text: object) -> bool:
    return _count(text, SIMPLIFIED_ONLY) >= MIN_CLIENT_CHARS


def _labels(text: object, labels: tuple[str, ...]) -> int:
    compact = "".join(str(text or "").split())
    return sum(1 for label in labels if label in compact)


def traditional_home_labels(text: object) -> int:
    """How many of home's 繁中 labels the read holds (a player's text has none)."""
    return _labels(text, TRADITIONAL_HOME_LABELS)


def note_text(text: object, now: float | None = None) -> bool:
    """Called with raw OCR text; remembers which client home's labels read."""
    traditional = looks_traditional(text) and traditional_home_labels(text) > 0
    simplified = (
        not traditional
        and looks_simplified(text)
        and _labels(text, SIMPLIFIED_HOME_LABELS) > 0
    )
    if not traditional and not simplified:
        return False
    with _lock:
        stamp = time.monotonic() if now is None else now
        _state["seen_at" if traditional else "simplified_at"] = stamp
    return traditional


def client_is_traditional() -> bool:
    """The latest clear reading was 繁中 text."""
    with _lock:
        return bool(_state["seen_at"]) and _state["seen_at"] > _state["simplified_at"]


def seen_since(started: float) -> bool:
    with _lock:
        seen_at = _state["seen_at"]
    return bool(seen_at) and seen_at >= started


def warn_after_failure(task, started: float, now: float | None = None) -> str:
    """After a failed run on the 繁中 client: notes the client for the report.

    The 繁中 client is supported now, so there is nothing to tell the player
    to change; the note only helps whoever reads the problem report.
    """
    if not seen_since(started):
        return ""
    try:
        task.info_set(INFO_KEY, TRADITIONAL_LABEL)
    except Exception:
        pass
    return ""


def reset() -> None:
    with _lock:
        _state.update(seen_at=0.0, simplified_at=0.0)
