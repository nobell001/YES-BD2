"""Costumes the official maintenance notice announces before souseha lists
them (Leo 2026-10-07: players in a hurry for 魔兽 can plan with them).

Reads the last few zh-tw maintenance notices from the official site's API
(https://webapi.browndust2.com/api, the same the news page loads), and the
same maintenance's notice in the other four languages for the names.  What
is found is marked temporary: names only (no portrait, skill or SP); the
list's own entry replaces it once souseha has the costume.  The sentence
logic is in character_pool.py.

Used by tools/fetch_official_costumes.py only: the shipped tool never reads
the official site (Leo 2026-10-07).  The API turns GitHub's machines away
(403, 2026-10-07), so the daily job takes the notices from an issue Leo's
Grok bot opens with their text (``from_issue``, .github/workflows/official-notice.yml).
"""

from __future__ import annotations

import copy
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from src.tasks.fiend_hunt import character_pool

API = "https://webapi.browndust2.com/api"
TIMEOUT = 20  # s per request
SAME_MAINTENANCE_DAYS = 3  # the languages' notices go up within a day or two of each other


def get_json(path: str, **params) -> dict:
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "bd2-auto character list"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = json.load(response)
    time.sleep(0.3)  # politely
    return data if isinstance(data, dict) else {}


def text_of(notice: dict) -> str:
    content = notice.get("content") or ""
    if content:
        return content
    return html.unescape(re.sub(r"<[^>]+>", "\n", notice.get("contentHtml") or ""))


def published(item: dict) -> date:
    return datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00")).date()


def notices(locale: str, get=get_json, limit: int = 10) -> list[dict]:
    items = get("/notices", locale=locale, category="inspection", page=0, limit=limit)
    return [item for item in items.get("items") or [] if isinstance(item, dict)]


def simplify(text: str) -> str:
    try:
        from src.utils.chinese import to_simplified
    except ImportError:
        return text
    return to_simplified(text)


ISSUE_SECTION = re.compile(r"^=+\s*(zh-tw|zh-cn|en-us|ja-jp|ko-kr)\s*=*\s*$", re.M | re.I)
# 不是次数：公告日期 2026/10/28
ISSUE_DATE = re.compile(r"(?:日期|date)\s*[:：]\s*(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})", re.I)
ISSUE_ID = re.compile(r"[?&]id=([0-9A-Za-z]{10,40})")


def parse_issue(body: str, today: date) -> tuple[str, date, str, dict[str, str]]:
    """(notice id, date, zh-tw text, other languages' texts) from an issue
    body: a link and ``日期：YYYY-MM-DD``, then each language's text under a line
    ``=== zh-tw`` (``zh-cn``, ``en-us``, ``ja-jp``, ``ko-kr``).  Without such
    lines the whole body is taken as zh-tw.  Only text: nothing is run."""
    body = (body or "").replace("\r\n", "\n")
    marks = list(ISSUE_SECTION.finditer(body))
    head = body[: marks[0].start()] if marks else body
    texts: dict[str, str] = {}
    for mark, after in zip(marks, marks[1:] + [None]):
        end = after.start() if after else len(body)
        lang = {v: k for k, v in character_pool.LOCALES.items()}[mark.group(1).lower()]
        texts[lang] = body[mark.end() : end]
    found = ISSUE_ID.search(head)
    when = ISSUE_DATE.search(head)
    try:
        announced = date(*map(int, when.groups())) if when else today
    except ValueError:
        announced = today
    zh_tw = texts.pop("zh_tw", "" if marks else body)
    return (found.group(1) if found else "issue"), announced, zh_tw, texts


def from_issue(data: dict, body: str, today: date, report=print) -> list[tuple[str, dict]]:
    """Like ``find``, with the notice text an issue carries."""
    notice_id, announced, zh_tw, texts = parse_issue(body, today)
    return _added(data, [(notice_id, announced, zh_tw, texts)], report)


def _added(data: dict, notices_read, report) -> list[tuple[str, dict]]:
    work = copy.deepcopy(data)
    before = {
        entry.get("id"): {c.get("id") for c in entry.get("costumes") or []}
        for entry in work.get("characters") or []
    }
    for notice_id, announced, zh_tw, texts in notices_read:
        for line in character_pool.add_from_notice(
            work, notice_id, announced, zh_tw, texts, simplify
        ):
            report(
                ("名单里没有这个角色：" + line[1:])
                if line.startswith("?")
                else f"新增（暂时）：{line}"
            )
    found = []
    for entry in work.get("characters") or []:
        known = before.get(entry.get("id"), set())
        for costume in entry.get("costumes") or []:
            if costume.get("id") not in known:
                found.append((entry["id"], costume))
    return found


def find(data: dict, today: date, get=get_json, report=print) -> list[tuple[str, dict]]:
    """(character id, temporary costume) for each costume the recent notices
    announce and ``data`` (the character list) lacks.  ``data`` is not
    changed.  Network errors are raised."""
    recent = [
        item
        for item in notices("zh-tw", get)
        if character_pool.is_maintenance(item.get("subject", ""))
        and today - published(item) <= timedelta(days=character_pool.NOTICE_DAYS)
    ]
    if not recent:
        return []
    others = {
        lang: notices(locale, get)
        for lang, locale in character_pool.LOCALES.items()
        if lang != "zh_tw"
    }
    read = []
    for item in recent:
        when = published(item)
        content = text_of(get(f"/notices/{item['id']}", locale="zh-tw"))
        texts = {}
        for lang, items in others.items():
            near = [
                other
                for other in items
                if abs((published(other) - when).days) <= SAME_MAINTENANCE_DAYS
            ]
            texts[lang] = "\n".join(
                text_of(get(f"/notices/{other['id']}", locale=character_pool.LOCALES[lang]))
                for other in near
            )
        read.append((item["id"], when, content, texts))
    return _added(data, read, report)
