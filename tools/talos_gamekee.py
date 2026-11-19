"""塔洛斯战术教材: the shipped records from GameKee's guide page.

    python tools/talos_gamekee.py            # fetch, write the records, print a report
    python tools/talos_gamekee.py --check    # fetch and report only, write nothing

Leo 2026-11-19 「我想把塔洛斯戰術教材做成自動化流程 只要這網站更新 這邊就
照著排軸」: https://www.gamekee.com/zsca2/697611.html (战术教材攻略) is
updated every season with one 阵容模拟器 chart per stage.  The charts are
data, not pictures: each round says who stands on which of the 12 cells,
who acts with 击退 / 技能 / 普攻 and the order of the left list.  This script
turns the page's newest season into one record per stage
(src/tasks/fiend_hunt/data/talos/塔洛斯-关卡N/record.json), the same format
TalosTask replays, and replaces the last season's records.

爆发 levels and 先发制人 are not in the chart (the page says its editor can't
show them); the author writes them in the stage's note, e.g.
「3回合，开紫色皮蛋（2号位）的3级爆发」, 「第7回合，拉菲娜2级，罗安3级」.
Those lines are read here; a line naming a 爆发 level or 先发制人 that can't
be tied to one unit and turn is listed in the report (``unsure``) for a
person to look at.

Dev tool only (tools/): the shipped tool never goes online.  It runs twice
a day from .github/workflows/talos-records.yml, which puts changed records
on a branch with a pull request; they are played once in the desktop clone
before Leo merges them (Leo 2026-11-19 「等以後抓到新的攻略 你要試跑 才更新」).  A page
still on the season the shipped records were made for by hand, or a new
season's heading without charts yet, changes nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tasks.fiend_hunt.record import record_from_dict  # noqa: E402
from src.tasks.fiend_hunt.recording import RECORD_FILE  # noqa: E402
from src.tasks.talos import stages  # noqa: E402

PAGE_ID = 697611
PAGE_URL = f"https://www.gamekee.com/zsca2/{PAGE_ID}.html"
DETAIL_URL = f"https://www.gamekee.com/v1/content/detail/{PAGE_ID}"
CHART_URL = "https://www.gamekee.com/v1/userBattleTemp/detail?id={}"
HEADERS = {
    "game-alias": "zsca2",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": PAGE_URL,
}
SOURCE_FILE = stages.SOURCE_FILE  # beside the stage folders: where this set came from
TAIWAN = timezone(timedelta(hours=8))

COLUMNS = 4  # the chart's 12 cells, row by row: cell k = (k // 4, k % 4); column 3 is the front
ACTIONS = {"repel": "击退", "skills": "技能1", "damage": "攻击"}
DEAD = "dead"


class ChartError(ValueError):
    """A chart that can't be turned into a record."""


# -- the page -------------------------------------------------------------------


def _text(node) -> str:
    if isinstance(node, dict):
        if "text" in node:
            return str(node["text"])
        return "".join(_text(child) for child in node.get("children") or [])
    if isinstance(node, list):
        return "".join(_text(child) for child in node)
    return ""


def season_stages(content) -> tuple[str, dict[int, int | None]]:
    """(season heading, stage -> chart id) of the page's last season.

    The page: a heading 「第九赛季攻略」, then tabs titled 1, 2, 3 ... each
    holding one 阵容模拟器 chart (``battle-array`` with data.tempId); a tab
    with no chart yet maps to None.  Tabs under an older heading are left
    out when a newer heading follows."""
    season, found = "", {}

    def walk(node) -> None:
        nonlocal season, found
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        kind = str(node.get("type") or "")
        if kind.startswith("header"):
            heading = _text(node).replace("﻿", "").strip()
            if "赛季" in heading:
                season, found = heading, {}
            return
        if kind == "tab-item":
            title = str(node.get("title") or "").replace("﻿", "").strip()
            chart = _chart_id(node)
            if title.isdigit():
                found[int(title)] = chart
            return
        walk(node.get("children") or [])

    walk(content)
    return season, found


def _chart_id(node) -> int | None:
    if isinstance(node, dict):
        if node.get("type") == "battle-array":
            value = (node.get("data") or {}).get("tempId")
            return int(value) if str(value).isdigit() else None
        return _chart_id(node.get("children") or [])
    if isinstance(node, list):
        for child in node:
            found = _chart_id(child)
            if found is not None:
                return found
    return None


# -- one chart --------------------------------------------------------------------


@dataclass
class Converted:
    stage: int
    chart: int
    title: str
    record: dict
    unsure: list[str] = field(default_factory=list)
    made: date | None = None  # when the chart was made (Taiwan time)


def _units(slots) -> list[dict]:
    return [slot for slot in slots or [] if isinstance(slot, dict) and slot.get("name")]


def _action(slot: dict) -> str:
    action = slot.get("actionType") or (slot.get("roleInfos") or {}).get("actionType")
    return str(action or "")


def _skin(slot: dict) -> str:
    return str((slot.get("roleInfos") or {}).get("choosedSkin") or "")


def chart_turns(content: dict) -> list[dict]:
    """The chart's rounds as record turns (round i = the game's TURN 2i+1)."""
    turns = []
    for index, round_info in enumerate(content.get("roundInfos") or []):
        number = 2 * index + 1
        cells, skills, dead, skins = {}, {}, [], {}
        for position, slot in enumerate(round_info.get("ourPositionData") or []):
            if not isinstance(slot, dict) or not slot.get("name"):
                continue
            name = str(slot["name"])
            if name in cells:
                raise ChartError(f"第 {number} 回合 {name} 站了两格")
            cells[name] = [position // COLUMNS, position % COLUMNS]
            skins[name] = _skin(slot)
            action = _action(slot)
            if action == DEAD:
                dead.append(name)
            elif action in ACTIONS:
                skills[name] = ACTIONS[action]
            else:
                raise ChartError(f"第 {number} 回合 {name} 的动作 {action!r} 认不得")
        sort = [str(slot["name"]) for slot in _units(round_info.get("ourSortData"))]
        order = [name for name in sort if name in cells and name not in dead]
        order += [name for name in cells if name not in dead and name not in order]
        turns.append(
            {
                "turn": number,
                "team": 1,
                "order": order,
                "cells": cells,
                "dead": sorted(dead),
                "skills": skills,
                "bursts": {name: 0 for name, card in skills.items() if card.startswith("技能")},
                "_sort": sort,  # the list with the dead (「N号位」 counts them), dropped on save
                "_skins": skins,
            }
        )
    if not turns:
        raise ChartError("没有回合")
    return turns


_TURN = re.compile(r"第?\s*(\d+)\s*(?:回合|t\b|T\b)")
_CLAUSE = re.compile(r"[，,。；;！!]")
_LEVEL = re.compile(r"(?<!\d)([1-3])\s*级(?:\s*的)?(?:\s*爆发)?")  # 「3级爆发」, 「拉菲娜2级」
_SEAT = re.compile(r"[（(]?\s*(\d)\s*号位\s*[)）]?")
_PREEMPT = re.compile(r"开([^，,。；;！!\n]*?)的?先发制人")
# what players call a unit in notes -> a part of its name (Ⅹ-1 「开神ut 3级爆发」
# = 神圣悠丝缇亚); 娅 and 亚 are written either way (莱维娅 / 莱维亚)
_NICKNAMES = {"ut": "悠丝缇亚"}
_SAME = str.maketrans({"娅": "亚"})


def _plain(text: str) -> str:
    text = text.translate(_SAME)
    for nickname, part in _NICKNAMES.items():
        text = re.sub(nickname, part, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", "", text)


def _in_order(words: str, name: str) -> bool:
    """Every character of ``words`` in ``name``, in order (莎拉 → 莎赫拉查德)."""
    rest = iter(name)
    return all(char in rest for char in words)


def _who(words: str, seat: str | None, turn: dict) -> str | None:
    """The unit a note means: 「N号位」 (place in the list), its name or a
    short form of it (莎拉, 神ut), or a word of its costume's name
    (「木乃伊」 for 白缕轻缠木乃伊).  None unless exactly one unit fits."""
    if seat is None:
        found = _SEAT.search(words)
        seat = found.group(1) if found else None
    if seat is not None:
        sort = turn["_sort"]
        index = int(seat) - 1
        return sort[index] if 0 <= index < len(sort) else None
    words = _plain(_SEAT.sub("", words)).removeprefix("开").removesuffix("开").removesuffix("的")
    words = re.sub(r"\d+$", "", words)  # 「达利安9」
    if not words:
        return None
    names = {name: _plain(name) for name in turn["cells"]}
    tries = (
        lambda name: names[name] == words,
        lambda name: len(words) >= 2 and _in_order(words, names[name]),
        # no 「name inside the words」: 神ut is not 悠丝缇亚 (a wrong unit plays
        # silently; a line left unplaced goes to a person)
        lambda name: len(words) >= 2 and bool(turn["_skins"].get(name)) and (
            words in _plain(turn["_skins"][name]) or _plain(turn["_skins"][name]) in words
        ),
    )
    for fits in tries:
        found = [name for name in names if fits(name)]
        if len(found) == 1:
            return found[0]
    return None


def apply_notes(turns: list[dict], note: str) -> list[str]:
    """爆发 and 先发制人 from the chart's note; returns the lines it couldn't place.

    A burst is a clause naming a level: 「开紫色皮蛋（2号位）的3级爆发」,
    「小狗（3号位）开3级爆发」, 「奥利维耶3级爆发」, 「拉菲娜2级」.  The unit
    must be on a skill in the turn the line names (or in exactly one turn)."""
    unsure: list[str] = []
    by_number = {turn["turn"]: turn for turn in turns}
    for line in (note or "").splitlines():
        line = line.strip()
        if not line:
            continue
        said = _TURN.search(line)
        numbers = [int(said.group(1))] if said else []
        for clause in _CLAUSE.split(line):
            clause = _TURN.sub("", clause)
            level = _LEVEL.search(clause)
            if level is None:
                continue
            words = clause[: level.start()]
            seat = _SEAT.search(clause)
            if not _place_burst(turns, by_number, numbers, words, seat.group(1) if seat else None, int(level.group(1))):
                unsure.append(line)
        for words in _PREEMPT.findall(line):
            if not _place_preempt(turns, by_number, numbers, words):
                unsure.append(line)
    return list(dict.fromkeys(unsure))


def _candidates(turns, by_number, numbers):
    if numbers:
        return [by_number[n] for n in numbers if n in by_number]
    return list(turns)


def _place_burst(turns, by_number, numbers, words, seat, level) -> bool:
    if numbers and not any(n in by_number for n in numbers):
        return False
    hits = []
    for turn in _candidates(turns, by_number, numbers):
        unit = _who(words, seat, turn)
        if unit is not None and turn["skills"].get(unit, "").startswith("技能"):
            hits.append((turn, unit))
    if len(hits) != 1:
        return False  # no turn said and the unit is on a skill in several: ask a person
    turn, unit = hits[0]
    turn["bursts"][unit] = level
    return True


def _place_preempt(turns, by_number, numbers, words) -> bool:
    pool = _candidates(turns, by_number, numbers)
    if not numbers:
        pool = pool[:1]  # 「开格兰希特的先发制人」: the opening turn (Ⅸ-7, won on the 2K PC)
    for turn in pool:
        unit = _who(words, None, turn)
        if unit is not None and unit not in turn["dead"]:
            turn.setdefault("preempt", {})[unit] = "技能1"
            return True
    return False


def convert(stage: int, chart_id: int, chart: dict) -> Converted:
    """One stage's chart (the detail API's data) as a record dict."""
    content = chart.get("content")
    if isinstance(content, str):
        content = json.loads(content)
    if not isinstance(content, dict):
        raise ChartError("图表内容读不了")
    turns = chart_turns(content)
    unsure = apply_notes(turns, str(content.get("remark") or ""))
    for turn in turns:
        turn.pop("_sort")
        turn.pop("_skins")
        if not turn.get("preempt"):
            turn.pop("preempt", None)
    record = {
        "version": 1,
        "title": f"塔洛斯-关卡{stage}",
        "source": f"gamekee:{chart_id}",
        "turns": turns,
    }
    record_from_dict(record)  # raises when the record doesn't hold together
    title = str(chart.get("title") or content.get("title") or "")
    stamp = chart.get("created_at") or chart.get("updated_at")  # an edit later on moves updated_at
    made = datetime.fromtimestamp(stamp, TAIWAN).date() if isinstance(stamp, (int, float)) else None
    return Converted(stage, chart_id, title, record, unsure, made)


# -- writing ------------------------------------------------------------------------


def write(
    converted: list[Converted], season: str, count: int = 0, root: Path = stages.RECORDS_DIR
) -> None:
    """Replace every stage folder with this season's records.

    source.json keeps ``stages`` (the page's stage count, stages without a
    chart yet included: the tool lays out the grid by it and skips them) and
    ``made`` (the earliest chart's date: TalosTask locks the task when the
    game's period ends long after it, stages.period_change)."""
    root.mkdir(parents=True, exist_ok=True)
    keep = {stages.record_folder(item.stage, root).name for item in converted}
    for old in root.iterdir():
        if old.is_dir() and old.name.startswith(stages.FOLDER_PREFIX) and old.name not in keep:
            shutil.rmtree(old)
    for item in converted:
        folder = stages.record_folder(item.stage, root)
        folder.mkdir(parents=True, exist_ok=True)
        text = json.dumps(item.record, ensure_ascii=False, indent=1) + "\n"
        (folder / RECORD_FILE).write_text(text, encoding="utf-8")
    dates = [item.made for item in converted if item.made]
    source = {
        "page": PAGE_URL,
        "season": season,
        "stages": max([count] + [item.stage for item in converted]),
        "made": min(dates).isoformat() if dates else None,
        "charts": {str(item.stage): item.chart for item in sorted(converted, key=lambda i: i.stage)},
        "unsure": {str(item.stage): item.unsure for item in converted if item.unsure},
    }
    (root / SOURCE_FILE).write_text(json.dumps(source, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def report(converted: list[Converted], season: str, missing: list[int]) -> str:
    lines = [f"塔洛斯战术教材：{season}，{len(converted)} 关（{PAGE_URL}）"]
    for item in sorted(converted, key=lambda i: i.stage):
        turns = len(item.record["turns"])
        bursts = [
            f"T{turn['turn']} {unit} {level}级"
            for turn in item.record["turns"]
            for unit, level in turn.get("bursts", {}).items()
            if level
        ]
        preempt = [
            f"T{turn['turn']} {unit}" for turn in item.record["turns"] for unit in turn.get("preempt", {})
        ]
        extra = (f"，爆发 {'、'.join(bursts)}" if bursts else "") + (
            f"，先发制人 {'、'.join(preempt)}" if preempt else ""
        )
        lines.append(f"- 第 {item.stage} 关（{item.title}）：{turns} 回合{extra}")
        for line in item.unsure:
            lines.append(f"  - 要人看：备注「{line}」对不上角色或回合")
    if missing:
        lines.append(f"- 网站还没有：第 {missing} 关")
    return "\n".join(lines)


# -- fetching -----------------------------------------------------------------------


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_page() -> list:
    detail = _get(DETAIL_URL)
    data = detail.get("data") or {}
    # the page itself in the answer when it is there (GitHub's machines get
    # 567 from api-cdn, 2026-11-19), else its copy on the CDN
    for key in ("content", "content_json"):
        content = data.get(key)
        if isinstance(content, str) and content.strip().startswith("["):
            print(f"（网页内容取自 detail.{key}）", file=sys.stderr)
            return json.loads(content)
        if isinstance(content, list) and content:
            return content
    cdn = str(data.get("content_cdn") or "")
    if not cdn:
        raise ChartError("网页没有内容")
    page = _get(("https:" + cdn) if cdn.startswith("//") else cdn)
    content = page.get("content")
    return json.loads(content) if isinstance(content, str) else content


def fetch_page_in_browser() -> list:
    """The page as a browser opens it (Leo 2026-11-19: GameKee's CDN turns
    GitHub's plain requests away with 567, a browser gets it): Chromium
    (playwright) opens the guide and the page's own request for its content
    is read; failing that, the page fetches its content file itself."""
    from playwright.sync_api import sync_playwright

    found: dict = {}

    def keep(response) -> None:
        if f"/content/{PAGE_ID}.json" in response.url and response.ok:
            try:
                found["page"] = response.json()
            except Exception:  # noqa: BLE001 - not the JSON after all
                pass

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.on("response", keep)
            page.goto(PAGE_URL, wait_until="networkidle", timeout=90_000)
            if "page" not in found:
                cdn = str((_get(DETAIL_URL).get("data") or {}).get("content_cdn") or "")
                if cdn:
                    url = ("https:" + cdn) if cdn.startswith("//") else cdn
                    found["page"] = json.loads(page.evaluate("url => fetch(url).then(r => r.text())", url))
        finally:
            browser.close()
    if "page" not in found:
        raise ChartError("浏览器打开攻略页，没拿到关卡内容")
    content = found["page"].get("content")
    return json.loads(content) if isinstance(content, str) else content


def fetch_chart(chart_id: int) -> dict:
    answer = _get(CHART_URL.format(chart_id))
    if answer.get("code") != 0 or not isinstance(answer.get("data"), dict):
        raise ChartError(f"图表 {chart_id} 拿不到：{answer.get('msg')}")
    return answer["data"]


def shipped_source(root: Path = stages.RECORDS_DIR) -> dict:
    try:
        data = json.loads((root / SOURCE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def season_name(text: str) -> str:
    """「第九赛季攻略」 and 「第九赛季（10-22 ~ 11-18）」 are the same season."""
    return re.sub(r"[（(].*?[)）]", "", text).replace("攻略", "").strip()


def commit_message(converted: list[Converted], season: str, missing: list[int]) -> str:
    """The commit's title and its 「玩家：」 line (scripts/sync_public.py: the update note)."""
    name = season.replace("攻略", "").strip() or "新一期"
    left = f"，第 {missing} 关攻略网站还没出" if missing else ""
    return (
        f"塔洛斯战术教材：{name}的轴（攻略网站 {PAGE_URL}）\n\n"
        f"玩家：塔洛斯战术教材换成{name}的轴（{len(converted)} 关{left}）\n"
    )


def main(argv: list[str] | None = None, root: Path = stages.RECORDS_DIR) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report only, write nothing")
    parser.add_argument("--message", type=Path, help="write the commit message here")
    parser.add_argument("--dump", type=Path, help="save the page and charts read (to look at a note)")
    args = parser.parse_args(argv)
    try:
        content = fetch_page()
    except urllib.error.HTTPError as error:
        print(f"攻略页直接读被挡（{error.code}），改用浏览器打开", file=sys.stderr)
        content = fetch_page_in_browser()
    season, charts = season_stages(content)
    shipped = shipped_source(root)
    if season and season_name(season) == season_name(str(shipped.get("season") or "")) and not shipped.get("charts"):
        # the shipped records were made by hand for this very season (10-22)
        print(f"{season}：工具里这期的轴是手工做的，网站还是同一期，不动")
        return 0
    if not season:
        print("网页上没找到「第N赛季」的标题：网站改版了，要改这个程序", file=sys.stderr)
        return 1
    if not any(charts.values()):
        # a new season's heading before its charts: keep the records we have
        print(f"{season}：网页上还没有关卡图表，工具里的轴不动")
        return 0
    converted, failed, fetched = [], [], {}
    for stage, chart_id in sorted(charts.items()):
        if chart_id is None:
            continue  # listed as missing below
        try:
            fetched[chart_id] = fetch_chart(chart_id)
            converted.append(convert(stage, chart_id, fetched[chart_id]))
        except (ChartError, ValueError, OSError) as error:
            failed.append(f"第 {stage} 关（图表 {chart_id}）：{error}")
    if args.dump:
        keep = ("id", "title", "created_at", "updated_at", "content")
        dump = {
            "season": season,
            "stages": charts,
            "charts": {key: {k: chart.get(k) for k in keep} for key, chart in fetched.items()},
        }
        args.dump.write_text(json.dumps(dump, ensure_ascii=False, default=str), encoding="utf-8")
    missing = [stage for stage in range(1, max(charts) + 1) if charts.get(stage) is None]
    print(report(converted, season, missing))
    for line in failed:
        print(f"- 转不了：{line}")
    if failed:
        return 1
    if not args.check:
        write(converted, season, max(charts), root)
        if args.message:
            args.message.write_text(commit_message(converted, season, missing), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
