"""A step must not end in failure on one check that did not see its screen
(Leo 2026-11-05 「你不要一個地方沒辨識到就出錯 明明有很多方法」「每有一個問題我
就要修一次 你要有系統性 方案性的方式確認」).

The shape that kept coming back::

    if not self._wait_for_title(...):     # one way of looking
        return False                       # the whole task fails

A page that did show, read badly once (HDR, a filter, another language, a
slow PC), ended the run, and a player sent a summary that said only where.
New code looks with more than one way (``press_next`` lists the screens
that can follow and runs the remedies; a check that reads two cues), or goes
on to a fallback before it gives up.  An ``if`` that still ends the step on
one check carries ``# 有备案：<the other way>`` on its line, when what comes
before it already tried the other ways.

Older code still has many; tests/fixtures/single_check_baseline.json holds
how many each file may keep.  A file may only go down: give an old one its
other ways, then lower the baseline.
"""

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "fixtures" / "single_check_baseline.json"
SCANNED = (ROOT / "src" / "tasks", ROOT / "src" / "utils")
FALLBACK_MARK = "# 有备案"
# A call that looks at the screen and answers yes/no (or None).
CHECK_NAME = re.compile(
    r"^_?("
    r"wait_for\w*|wait_\w+|look\w*|find\w*|locate\w*|read\w*|ocr\w*|match\w*"
    r"|\w*_(visible|shown|seen|present|showing|steady|confirmed|confirmation|passes)"
    r"|\w*_(title|page|dialog|popup|screen)"
    r")$"
)
FAIL_WORDS = ("失败", "没找到", "未找到", "没看到", "找不到", "认不出", "没读到", "没进", "打不开")


def _call_name(node) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _checked_call(test) -> ast.Call | None:
    """The call of ``not call(...)`` / ``call(...) is None``; else None."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        test = test.operand
    elif (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Is)
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value is None
    ):
        test = test.left
    else:
        return None
    return test if isinstance(test, ast.Call) else None


def _ends_in_failure(body) -> bool:
    """The branch gives the step up: returns False/None/a 失败 text, notes why, raises."""
    for statement in body[:6]:
        if isinstance(statement, ast.Raise):
            return True
        if isinstance(statement, ast.Return):
            value = statement.value
            if value is None or (isinstance(value, ast.Constant) and value.value in (False, None)):
                return True
            if any(word in ast.unparse(value) for word in FAIL_WORDS):
                return True
        text = ast.unparse(statement)
        if "_note_why" in text or "_claim_fail" in text or "_fail_run" in text:
            return True
        if "info_set" in text and "失败" in text:
            return True
    return False


def single_checks(path: Path) -> list[int]:
    """Lines of ``if not <one screen check>: <give the step up>`` with no mark."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found = set()
    for function in ast.walk(ast.parse(source)):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # A check made of checks (``_list_visible``: the title, then the
        # grid) answers no when a part is missing: that is not a step given up.
        if CHECK_NAME.match(function.name) or re.match(r"^_?(is|has)_", function.name):
            continue
        found.update(_in_function(function, lines))
    return sorted(found)


def _in_function(function, lines) -> list[int]:
    found = []
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        call = _checked_call(node.test)
        if call is None or not CHECK_NAME.match(_call_name(call)):
            continue
        if FALLBACK_MARK in lines[node.lineno - 1]:
            continue
        if _ends_in_failure(node.body):
            found.append(node.lineno)
    return found


def counts() -> dict[str, list[int]]:
    found = {}
    for folder in SCANNED:
        for path in sorted(folder.rglob("*.py")):
            lines = single_checks(path)
            if lines:
                found[path.relative_to(ROOT).as_posix()] = lines
    return found


class SingleCheckGuardTest(unittest.TestCase):
    def setUp(self):
        self.allowed = json.loads(BASELINE.read_text(encoding="utf-8"))["single_checks"]
        self.found = counts()

    def test_no_file_gives_up_on_one_check_more_than_before(self):
        over = {
            name: f"{len(lines)} > {self.allowed.get(name, 0)} (lines {lines})"
            for name, lines in self.found.items()
            if len(lines) > self.allowed.get(name, 0)
        }
        self.assertEqual(
            {},
            over,
            "A step fails on one check that did not see its screen. Look another way "
            "first (press_next, a second cue, a fallback), or mark the line "
            "「# 有备案：<the other way>」 when that is already done before it.",
        )

    def test_the_allowance_goes_down_with_each_fix(self):
        left = {
            name: f"{count} allowed, {len(self.found.get(name, []))} left"
            for name, count in self.allowed.items()
            if len(self.found.get(name, [])) < count
        }
        self.assertEqual(
            {}, left, "Lower tests/fixtures/single_check_baseline.json to what is left."
        )

    def test_the_scan_sees_the_shape(self):
        sample = ROOT / "tests" / "fixtures" / "_single_check_sample.py"
        sample.write_text(
            "def a(self):\n"
            "    if not self._wait_for_title('x'):\n"
            "        return False\n"
            "    if not self._wait_for_title('y'):  # 有备案：上面已按 Esc 再看\n"
            "        return False\n"
            "    if self._read_detail() is None:\n"
            "        self._note_why('没读到面板')\n"
            "    if not self.tap_key('h'):\n"
            "        return False\n"
            "    if not self._page_shown():\n"
            "        self.log_info('再看一次')\n"
            "def _list_visible(self):\n"
            "    if not self._title_visible('x'):\n"
            "        return False\n",
            encoding="utf-8",
        )
        try:
            self.assertEqual([2, 6], single_checks(sample))
        finally:
            sample.unlink()


if __name__ == "__main__":
    unittest.main()
