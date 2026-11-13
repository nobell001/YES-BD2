"""Report notes with numbers in them, shown in the app's language.

A note such as 「已扫荡救赎之塔LV7 9场」 (Leo 2026-11-13) has its numbers
filled in by the task, so the catalogs cannot hold it word for word.  Each
template here is in the catalogs with ``{name}`` blanks; a note that matches
one is translated through the template and the numbers put back.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache

TEMPLATES = (
    "已扫荡救赎之塔LV{lv} {n}场",
    "已扫荡救赎之塔LV{lv}",
    "救赎之塔只剩 1 把钥匙，留着打 LV{lv} 以上，今天没扫荡",
)


@lru_cache(maxsize=None)
def _pattern(template: str) -> re.Pattern:
    parts = re.split(r"(\{[a-z]+\})", template)
    regex = "".join(
        f"(?P<{part[1:-1]}>\\d+)" if part.startswith("{") else re.escape(part) for part in parts
    )
    return re.compile(regex)


def translate(text: str, tr: Callable[[str], str]) -> str | None:
    """``text`` through its template's translation, or None when no template
    matches."""
    for template in TEMPLATES:
        match = _pattern(template).fullmatch(text)
        if match:
            try:
                return tr(template).format(**match.groupdict())
            except (KeyError, IndexError, ValueError):
                return None
    return None
