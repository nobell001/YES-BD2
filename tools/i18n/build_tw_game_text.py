"""Build assets/game_text/zh_tw.json: 繁中 client words -> 简中 client words.

The tool reads the game with the 简中 client's words.  On the 繁中 client OCR
text is first simplified (OpenCC t2s) and then this table turns the words the
two clients name differently into the 简中 ones (src/utils/game_text.py).

Sources, 繁中 -> 简中:
- names: souseha BD2DB (Leo 2026-10-03: game words follow souseha), the
  cartridges, maps, hunting grounds, materials, collections, dishes
  (db-packs, db-items) and the characters, costumes and skills already in
  src/tasks/fiend_hunt/data/characters.json; plus tools/i18n/names.json and
  tw_terms.json.
- ui: tools/i18n/tw_client_ui.json, words read off the 繁中 client itself
  (buttons, page titles) that souseha does not have.

Only pairs whose simplified 繁中 differs from the 简中 word are kept.
Run: python tools/i18n/build_tw_game_text.py  (needs opencc and node).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from opencc import OpenCC

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "assets" / "game_text" / "zh_tw.json"
SITE = "https://browndust2-db.souseha.com"
t2s = OpenCC("t2s")

NODE_DUMP = """
const packs = await import(process.argv[2]);
const items = await import(process.argv[3]);
// loadPacks: maps_i18n = m, packs_i18n = p; loadItems: materials = m,
// collections = c, recipes = r (see loadPacks-*.js, loadItems-*.js)
console.log(JSON.stringify({
  maps: Object.values(packs.m), packs: Object.values(packs.p),
  materials: Object.values(items.m), collections: Object.values(items.c),
  recipes: Object.values(items.r),
}));
"""


def get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "bd2-auto game text"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def asset(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise SystemExit(f"souseha changed its pages: {pattern!r} not found")
    return match.group(1)


def souseha_pairs() -> list[tuple[str, str]]:
    main = asset(get(f"{SITE}/"), r'src="/assets/(main-[\w-]+\.js)"')
    main_js = get(f"{SITE}/assets/{main}")
    modules = []
    for loader, name in (("loadPacks", "packs"), ("loadItems", "items")):
        loader_js = get(f"{SITE}/assets/" + asset(main_js, r'"\./(' + loader + r'-[\w-]+\.js)"'))
        modules.append(asset(loader_js, r'"\./(db-' + name + r'-[\w-]+\.js)"'))
    with tempfile.TemporaryDirectory() as folder:
        paths = []
        for module in modules:
            path = Path(folder) / (module[:-3] + ".mjs")
            path.write_text(get(f"{SITE}/assets/{module}"), encoding="utf-8")
            paths.append(path.as_uri())
        script = Path(folder) / "dump.mjs"
        script.write_text(NODE_DUMP, encoding="utf-8")
        raw = json.loads(
            subprocess.run(
                ["node", str(script), *paths], check=True, capture_output=True, text=True
            ).stdout
        )
    pairs = []
    for row in raw["maps"]:
        pairs.append((row.get("name", ""), row.get("name_CN", "")))
    for row in raw["packs"]:
        pairs.append((row.get("packTitle", ""), row.get("packTitle_CN", "")))
        pairs.append((row.get("huntingGround", ""), row.get("huntingGround_CN", "")))
    for key in ("materials", "collections", "recipes"):
        for row in raw[key]:
            pairs.append((row.get("item", ""), row.get("item_CN", "")))
    return pairs


def character_pairs() -> list[tuple[str, str]]:
    data = json.loads(
        (REPO / "src" / "tasks" / "fiend_hunt" / "data" / "characters.json").read_text(encoding="utf-8")
    )
    pairs = []
    for character in data["characters"]:
        pairs.append((character.get("name_zh_tw", ""), character.get("name_zh_cn", "")))
        for costume in character.get("costumes") or []:
            pairs.append((costume.get("name_zh_tw", ""), costume.get("name_zh_cn", "")))
            pairs.append((costume.get("skill_zh_tw", ""), costume.get("skill_zh_cn", "")))
    return pairs


def term_pairs() -> list[tuple[str, str]]:
    pairs = []
    for cn, row in json.loads((HERE / "names.json").read_text(encoding="utf-8")).items():
        pairs.append((row.get("tw", ""), cn))
    # {cn: tw}; several tool short forms share one 繁中 word: the longest 简中
    # (the game's full name) wins below.
    for cn, tw in json.loads((HERE / "tw_terms.json").read_text(encoding="utf-8")).items():
        pairs.append((tw, cn))
    return pairs


def tool_words() -> set[str]:
    """The 简中 words the tool itself looks for (string literals in src)."""
    import ast

    found = set()
    for path in (REPO / "src").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.update(re.findall(r"[\u4e00-\u9fff]{2,8}", node.value))
    return found


def table(pairs: list[tuple[str, str]]) -> dict[str, str]:
    words: dict[str, str] = {}
    for tw, cn in pairs:
        tw, cn = str(tw or "").strip(), str(cn or "").strip()
        if not tw or not cn:
            continue
        key = t2s.convert(tw)
        if len(key) < 2 or key == cn:
            continue
        if key not in words or len(cn) > len(words[key]):
            words[key] = cn
    # A 简中 word that holds a shorter 繁中 word (草药猎人 holds 草药, which is
    # 繁中 for 香草) stays itself: the longest match wins, so it is kept as is.
    # A 繁中 word whose simplified form is itself a 简中 name stays itself:
    # 泳池派對 is the costume 泳池派对 and the map 泳池派对场 (2026-10-25 check).
    same = {t2s.convert(str(tw or "").strip()) for tw, cn in pairs if t2s.convert(str(tw or "").strip()) == str(cn or "").strip()}
    for key in list(words):
        if key in same:
            words[key] = key
    keys = list(words)
    names = {str(cn or "").strip() for _tw, cn in pairs} | tool_words()
    for name in names:
        if name and name not in words and any(key != name and key in name for key in keys):
            words[name] = name
    return dict(sorted(words.items()))


def main() -> int:
    ui = json.loads((HERE / "tw_client_ui.json").read_text(encoding="utf-8"))
    names = table(term_pairs() + character_pairs() + souseha_pairs())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "about": "繁中 game client word -> 简中 client word; built by tools/i18n/build_tw_game_text.py",
                "ui": ui,
                "names": names,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{OUT}: {len(ui)} ui words, {len(names)} names")
    return 0


if __name__ == "__main__":
    sys.exit(main())
