"""Lines a player reads: the cause in words, the raw numbers in the log file only."""

from __future__ import annotations

import re

# A line for the log file only (raw numbers, evidence dumps): the summary a
# player sends skips it (Leo 2026-10-26 「log要有用」).
DIAGNOSTIC_PREFIX = "诊断："

# 「text=…」「ratio=0.167」 and a dumped dict: numbers for us, noise for a player.
_DUMP = re.compile(r"""\{['"].*""")
_KEY_VALUE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*=[^,，;；）)\s]*")
_EMPTY_BRACKETS = re.compile(r"[（(][\s,，;；:：\-]*[）)]")


def plain(text: str) -> str:
    """A line in player words: no key=value numbers, no dumped evidence.

    The summary of a player (2026-10-26) read 「探查点击后未确认执行反馈：
    ratio=0.167, text=无可召集的战场怪物」 and a dozen raw dicts; nobody could
    see the skills were in the wrong slots.  The raw line stays in the log file.
    """
    text = _DUMP.sub("", str(text or ""))
    text = _KEY_VALUE.sub("", text)
    text = _EMPTY_BRACKETS.sub("", text)
    text = re.sub(r"\s*([,，;；])(\s*[,，;；])+", r"\1", text)
    text = re.sub(r"([：:（(])\s*[,，;；]\s*", r"\1", text)
    text = re.sub(r"\s*[,，;；:：]\s*([。）)]|$)", r"\1", text)
    text = _EMPTY_BRACKETS.sub("", text)
    text = re.sub(r"[：:,，;；\s]+$", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()
