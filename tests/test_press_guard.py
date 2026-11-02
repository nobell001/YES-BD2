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

A wait with a deadline of its own (``end_at = monotonic() + t``) also has
remedies of its own, which is how each task came to fail in its own way.  New
waits use the shared tools (Leo 2026-10-28 「能不能有個統一的標準」): after a
press ``press_next`` (src/utils/press_next.py: the screens that can follow,
then the remedies in order), otherwise ``wait_for`` or ``load_wait``.  A wait
that really needs its own deadline carries ``# 自己等：<reason>`` on that line.
The baseline counts the old ones under ``hand_waits``; a file may only go down.

A press wrapped in a helper of our own (``_click_shop_close_control``,
``_press_quick_slot``…) hid from the scan: the click inside the helper was
counted once, every place that used it was not.  Player 2026-11-02 (v0.2.27):
the 折扣商店 back went through such a helper, pressed once, no remedy, and
跑商 failed.  So a function named ``click_* / press_* / tap_*`` that presses
is a press too, at every call: through press_next / press_and_confirm, with
``# 不用确认：<reason>``, or counted under ``helper_presses`` (only goes down).
A helper that re-presses by itself carries ``# 会补点：<how>`` on its def line.
"""

import ast
import json
import re
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
CONFIRMED_BY = frozenset({"press_and_confirm", "press_next"})
REASON_MARK = "# 不用确认"
OWN_WAIT_MARK = "# 自己等"
# The shared wait tools themselves.
WAIT_TOOLS = frozenset(
    {
        ROOT / "src" / "utils" / "press_confirm.py",
        ROOT / "src" / "utils" / "press_next.py",
        ROOT / "src" / "utils" / "wait_limits.py",
    }
)


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def direct_presses(path: Path) -> list[int]:
    """Lines in ``path`` that press without press_and_confirm or a reason."""
    return _unconfirmed_calls(path, PRESS_CALLS)


# On a helper's ``def`` line: it looks after its own press and presses again
# when the game dropped it, so its callers need nothing more.
SELF_REMEDY_MARK = "# 会补点"
HELPER_NAME = re.compile(r"^_?(click|press|tap)(_|$)")
NOT_HELPERS = CONFIRMED_BY | PRESS_CALLS


def press_helpers(paths=None) -> frozenset[str]:
    """Names of our own functions that send a press (by the naming rule).

    A helper calling another helper (``_click_ocr_pattern_center`` →
    ``_click_client`` → ``operate_click``) is one too."""
    if paths is None:
        paths = [path for folder in SCANNED for path in sorted(folder.rglob("*.py"))]
    named = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name not in NOT_HELPERS
                and HELPER_NAME.match(node.name)
                and SELF_REMEDY_MARK not in lines[node.lineno - 1]
            ):
                # Presses made through press_next / press_and_confirm have
                # their remedy: they don't make a helper.  A 不用确认 mark
                # inside one does not count: callers are checked instead.
                confirmed: set[int] = set()
                for call in ast.walk(node):
                    if isinstance(call, ast.Call) and _call_name(call) in CONFIRMED_BY:
                        for argument in [*call.args, *(k.value for k in call.keywords)]:
                            confirmed.update(id(n) for n in ast.walk(argument))
                calls = {
                    _call_name(n)
                    for n in ast.walk(node)
                    if isinstance(n, ast.Call)
                    and id(n) not in confirmed
                }
                named.append((node.name, calls))
    names: set[str] = set()
    pressing = set(PRESS_CALLS)
    while True:
        found = {name for name, calls in named if calls & pressing} - names
        if not found:
            return frozenset(names)
        names |= found
        pressing |= found


_HELPERS: frozenset[str] | None = None


def helper_presses(path: Path, helpers: frozenset[str] | None = None) -> list[int]:
    """Lines in ``path`` that call a press helper without a remedy or reason."""
    global _HELPERS
    if path in WAIT_TOOLS:
        return []
    if helpers is None:
        if _HELPERS is None:
            _HELPERS = press_helpers()
        helpers = _HELPERS
    return _unconfirmed_calls(path, helpers)


def _unconfirmed_calls(path: Path, names) -> list[int]:
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
        if not isinstance(node, ast.Call) or _call_name(node) not in names:
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


def hand_waits(path: Path) -> list[int]:
    """Lines that set a deadline by hand (``end_at = monotonic() + t``)."""
    if path in WAIT_TOOLS:
        return []
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add)):
            continue
        if not (_is_clock_call(value.left) or _is_clock_call(value.right)):
            continue
        if OWN_WAIT_MARK not in lines[node.lineno - 1]:
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

    def test_no_file_uses_press_helpers_more_than_before(self):
        over = _over(self.allowed["helper_presses"], helper_presses)
        self.assertEqual(
            {},
            over,
            "New calls of a press helper (click_* / press_* / tap_*) with no remedy. "
            "Call it through press_next (src/utils/press_next.py) so a swallowed press "
            "is pressed again, or put `# 不用确认：<reason>` on the line.",
        )

    def test_no_file_has_more_waits_that_may_never_look(self):
        over = _over(self.allowed["waits"], deadline_waits)
        self.assertEqual(
            {},
            over,
            "New `while monotonic() <= end_at:` waits. Use wait_for "
            "(src/utils/press_confirm.py), which always looks at least once.",
        )

    def test_no_file_writes_more_waits_of_its_own(self):
        over = _over(self.allowed["hand_waits"], hand_waits)
        self.assertEqual(
            {},
            over,
            "New waits with a deadline of their own. After a press use press_next "
            "(src/utils/press_next.py: the screens that can follow, then the shared "
            "remedies), otherwise wait_for or load_wait; or put `# 自己等：<reason>` "
            "on the line.",
        )

    def test_the_allowance_goes_down_with_each_fix(self):
        # An old press given a remedy frees its place; left in the allowance,
        # a new press without a remedy could take it unseen (player
        # 2026-11-02: 白嫖抽抽乐 result back, one press, no remedy; Leo
        # 「我之前就說要有補救措施」).  Lower the baseline with the fix.
        for key, finder in (
            ("presses", direct_presses),
            ("helper_presses", helper_presses),
            ("waits", deadline_waits),
            ("hand_waits", hand_waits),
        ):
            with self.subTest(kind=key):
                current = current_counts(finder)
                slack = {
                    name: f"{count} allowed, {current.get(name, 0)} left"
                    for name, count in self.allowed[key].items()
                    if count > current.get(name, 0)
                }
                self.assertEqual(
                    {},
                    slack,
                    f"Lower tests/fixtures/direct_press_baseline.json [{key}] to what is left.",
                )

    def test_the_scan_sees_presses_reasons_and_waits(self):
        sample = ROOT / "tests" / "fixtures" / "press_guard_sample.py"
        self.assertEqual([7], direct_presses(sample))
        self.assertEqual([9], deadline_waits(sample))
        self.assertEqual([8], hand_waits(sample))
        helpers = press_helpers([sample])
        # _press_twice re-presses by itself; _click_via_helper presses through
        # another helper.
        self.assertEqual(frozenset({"_click_close", "_click_via_helper"}), helpers)
        self.assertEqual([20, 35], helper_presses(sample, helpers))


if __name__ == "__main__":
    unittest.main()
