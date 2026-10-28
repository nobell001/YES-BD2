"""New "a/b" count reads go through the shared rules (src/utils/ocr_count.py).

Each task read its counts with a pattern of its own and mended it where a
misread showed up (7/70 read "7170", 11/75 "11775", 0/21 "121"), so the next
count failed the same way (Leo 2026-10-28 「11/75 這個問題很多次了 沒辦法解決嗎」).
A ``re`` pattern for "digits / digits" written outside ocr_count fails this
test.  The older ones are counted per file in ``ALLOWED`` and a file may only
go down: each moves to ocr_count once that is measured better on real frames
(Leo 2026-10-28 「你要評估 更穩定更好才做」).  A pattern that is not a count (a
date) carries ``# 不是次数：<reason>`` on its line or the line above.
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "src" / "utils" / "ocr_count.py"
NOT_A_COUNT = "# 不是次数"
RE_CALLS = frozenset(
    {"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"}
)
# A digit (\d, [0-9…], or a written one), then a slash, then a digit.
_DIGIT = r"(?:\\d|\[0-9|\[\\d|[0-9])"
COUNT_SHAPE = re.compile(rf"{_DIGIT}[^\n]{{0,24}}?[/／][^\n]{{0,24}}?{_DIGIT}")
ALLOWED = {
    "src/tasks/EventBattleTask.py": 2,  # 体力 a/b, 第N次/共M次
    "src/tasks/JunkGearTask.py": 1,  # 背包 a/2000
    "src/tasks/RedemptionTowerTask.py": 1,  # 钥匙 0/10
    "src/tasks/affinity/screen.py": 2,  # 谈心记录 a/b, 0/1
    "src/tasks/quick_hunt.py": 1,  # 快速狩猎次数 a/b
    "src/utils/pvp_dialog.py": 2,  # 免费鸡尾酒 a/40
}


def _pattern(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return None


def count_patterns(path: Path) -> list[int]:
    """Lines in ``path`` with a ``re`` pattern shaped like "digits/digits"."""
    if path == SHARED:
        return []
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in RE_CALLS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "re"
            and node.args
        ):
            continue
        pattern = _pattern(node.args[0])
        if not pattern or not COUNT_SHAPE.search(pattern):
            continue
        around = range(max(1, node.lineno - 1), (node.end_lineno or node.lineno) + 1)
        if not any(NOT_A_COUNT in lines[number - 1] for number in around):
            found.append(node.lineno)
    return sorted(found)


def current_counts() -> dict[str, int]:
    counts = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        count = len(count_patterns(path))
        if count:
            counts[path.relative_to(ROOT).as_posix()] = count
    return counts


class CountReadGuardTest(unittest.TestCase):
    def test_no_new_count_pattern_outside_ocr_count(self):
        over = {
            name: f"{count} > {ALLOWED.get(name, 0)}"
            for name, count in current_counts().items()
            if count > ALLOWED.get(name, 0)
        }
        self.assertEqual(
            {},
            over,
            "读「a/b」次数请用 src/utils/ocr_count.py（parse_count / read_count / LOOKS）；"
            "不是次数的（例如日期）在那一行或上一行写「# 不是次数：原因」",
        )

    def test_the_allowed_counts_only_go_down(self):
        """A file that moved its counts to ocr_count lowers its number here."""
        counts = current_counts()
        stale = {
            name: f"{allowed} -> {counts.get(name, 0)}"
            for name, allowed in ALLOWED.items()
            if counts.get(name, 0) < allowed
        }
        self.assertEqual({}, stale)

    def test_the_guard_sees_a_hand_written_count(self):
        sample = Path(__file__).parent / "fixtures" / "count_guard_sample.py"
        self.assertEqual([4, 9], count_patterns(sample))


if __name__ == "__main__":
    unittest.main()
