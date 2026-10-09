"""New game presses must go through press_and_confirm (Leo 2026-10-09).

Most failures came from a press that the game dropped while the tool moved
on as if it had worked.  ``src.utils.press_confirm.press_and_confirm`` checks
the screen after each press and presses once more while nothing changed.

Older code still presses directly in many places; tests/fixtures/
direct_press_baseline.json holds how many each file may keep.  A file may
only go down.  A press that really needs no check (closing a popup that the
next step looks for anyway, a key whose result the caller reads) carries the
comment ``# 不用确认：<reason>`` on its line.

Waits written as ``while monotonic() <= end_at:`` never look when the time is
already up (timeout 0, or the step before overran) and then report "not
there".  New waits use ``wait_for``, which always looks once; the same file
counts how many old ones each file may keep.
"""

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "fixtures" / "direct_press_baseline.json"
SCANNED = (ROOT / "src" / "tasks", ROOT / "src" / "utils")
# Calls that send a click or key to the game.
PRESS_CALLS = frozenset(
    {
        "click",
        "operate_click",
        "_click_reference",
        "click_reference",
        "click_client",
        "click_template",
        "click_stable_template",
        "click_ocr",
        "click_box",
        "click_relative",
        "send_key",
    }
)
CONFIRMED_BY = frozenset({"press_and_confirm"})
REASON_MARK = "# 不用确认"


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def direct_presses(path: Path) -> list[int]:
    """Lines in ``path`` that press without press_and_confirm or a reason."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    inside_confirm: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in CONFIRMED_BY:
            for argument in [*node.args, *(k.value for k in node.keywords)]:
                inside_confirm.update(id(n) for n in ast.walk(argument))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) not in PRESS_CALLS:
            continue
        if id(node) in inside_confirm:
            continue
        marked = any(
            REASON_MARK in lines[number - 1]
            for number in range(node.lineno, (node.end_lineno or node.lineno) + 1)
        )
        if not marked:
            found.append(node.lineno)
    return sorted(found)


def _is_clock_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _call_name(node) in {"monotonic", "time", "perf_counter"}


def deadline_waits(path: Path) -> list[int]:
    """Lines of ``while <clock>() < / <= deadline:`` loops (may never look)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        test = getattr(node, "test", None) if isinstance(node, ast.While) else None
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.Lt, ast.LtE))
            and _is_clock_call(test.left)
        ):
            found.append(node.lineno)
    return sorted(found)


def current_counts(finder=direct_presses) -> dict[str, int]:
    counts = {}
    for folder in SCANNED:
        for path in sorted(folder.rglob("*.py")):
            count = len(finder(path))
            if count:
                counts[path.relative_to(ROOT).as_posix()] = count
    return counts


def _over(allowed: dict[str, int], finder) -> dict[str, str]:
    over = {}
    for name, count in current_counts(finder).items():
        if count > allowed.get(name, 0):
            lines = finder(ROOT / name)
            over[name] = f"{count} > {allowed.get(name, 0)} (lines {lines})"
    return over


class PressGuardTest(unittest.TestCase):
    def setUp(self):
        self.allowed = json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_no_file_presses_directly_more_than_before(self):
        over = _over(self.allowed["presses"], direct_presses)
        self.assertEqual(
            {},
            over,
            "New direct game presses. Use press_and_confirm (src/utils/press_confirm.py), "
            "or put `# 不用确认：<reason>` on the line when the result is checked elsewhere.",
        )

    def test_no_file_has_more_waits_that_may_never_look(self):
        over = _over(self.allowed["waits"], deadline_waits)
        self.assertEqual(
            {},
            over,
            "New `while monotonic() <= end_at:` waits. Use wait_for "
            "(src/utils/press_confirm.py), which always looks at least once.",
        )

    def test_the_scan_sees_presses_reasons_and_waits(self):
        sample = ROOT / "tests" / "fixtures" / "press_guard_sample.py"
        self.assertEqual([7], direct_presses(sample))
        self.assertEqual([9], deadline_waits(sample))


if __name__ == "__main__":
    unittest.main()
