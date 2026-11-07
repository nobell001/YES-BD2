"""Turn what OCR reads on the 繁中 game client into the 简中 client's words.

Every keyword the tool looks for is the 简中 client's text.  Leo 2026-10-09
asked for the 繁中 client to work too, so each OCR result passes through here
before any task compares it (BaseBD2Task.fix_texts):

1. Traditional characters become simplified ones (OpenCC t2s).  ok-script's
   own auto_simplify is not used (src/config.py).
2. Where the two clients use different words for the same thing (繁中 搜索 =
   简中 探查, 故事遊戲卡帶 = 剧情游戏卡带), the 繁中 word becomes the 简中 one.
   The table is assets/game_text/zh_tw.json: game names from souseha BD2DB
   (tools/i18n/build_tw_game_text.py) plus UI words read off the 繁中 client.

Step 2 runs only on text that is clearly 繁中: a box with traditional
characters, or any box while the game was last seen in 繁中 (game_language).
A 简中 client's text is never rewritten by the table.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from src.utils import game_language
from src.utils.chinese import to_simplified

TABLE_PATH = Path(__file__).resolve().parents[2] / "assets" / "game_text" / "zh_tw.json"

# Japanese forms OCR gives for 繁中 characters, which OpenCC t2s leaves as they
# are: 2K clone 2026-11-03 read the costume 惡作劇幽靈 as 恶作剧幽霊.
OCR_VARIANTS = str.maketrans({"霊": "灵"})


@lru_cache(maxsize=1)
def _table() -> tuple[dict[str, str], re.Pattern | None]:
    try:
        data = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    words: dict[str, str] = {}
    for section in ("ui", "names"):
        for tw_word, cn_word in (data.get(section) or {}).items():
            key = to_simplified(str(tw_word)).strip()
            value = str(cn_word).strip()
            # One-character words would rewrite too much of other text.  A word
            # that maps to itself guards a 简中 word holding a shorter 繁中 one.
            if len(key) >= 2 and value:
                words.setdefault(key, value)
    if not words:
        return {}, None
    # Longest first, so 故事游戏卡带 wins over a shorter word inside it.
    keys = sorted(words, key=len, reverse=True)
    return words, re.compile("|".join(re.escape(key) for key in keys))


def table_words() -> dict[str, str]:
    return dict(_table()[0])


def to_cn_words(text: str) -> str:
    """Only the word table (step 2), for text that is already simplified."""
    words, pattern = _table()
    if pattern is None or not text:
        return text

    def replace(match: re.Match) -> str:
        key = match.group(0)
        value = words[key]
        # Already the 简中 word around it (繁中 剑传 inside 御剑传): keep it.
        offset = value.find(key)
        start = match.start() - offset
        if offset > 0 and start >= 0 and text[start : start + len(value)] == value:
            return key
        return value

    return pattern.sub(replace, text)


def to_tool_text(text: object, traditional_client: bool | None = None) -> str:
    """One OCR result as the 简中 client would show it."""
    raw = str(text or "")
    if not raw:
        return raw
    simplified = to_simplified(raw).translate(OCR_VARIANTS)
    if traditional_client is None:
        traditional_client = game_language.client_is_traditional()
    if simplified != raw or traditional_client:
        simplified = to_cn_words(simplified)
    return simplified


def note_boxes(boxes) -> None:
    """Remember which client one OCR read came from (raw text)."""
    text = " ".join(str(getattr(box, "name", "") or "") for box in boxes)
    if text.strip():
        game_language.note_text(text)


def fix_boxes(boxes) -> None:
    """Rewrite each box's name in place."""
    traditional_client = game_language.client_is_traditional()
    for box in boxes:
        name = str(getattr(box, "name", "") or "")
        if name:
            box.name = to_tool_text(name, traditional_client)
