"""No name in src is used without being defined or imported.

PR #526 live test (4K 繁中 2026-11-09): BaseBD2Task.dismiss_field_followers
used FOLLOWERS_ABSENT, missing from its function-local import, so every field
entry without the 派遣 crowd (跑图, 跑商, 末日之书, 救赎之塔) stopped with a
NameError.  The unit tests stubbed that method, so none reached the line.
This check reads every source file (standard library only, so it also runs in
the Windows build): a name a function reads as a global must be defined at the
module's top level or be a builtin.
"""

import builtins
import symtable
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__path__",
                                 "__builtins__", "__loader__", "__package__", "__annotations__"}


def _module_names(table: symtable.SymbolTable) -> set[str]:
    return {
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
    }


def _global_reads(table: symtable.SymbolTable):
    for child in table.get_children():
        for symbol in child.get_symbols():
            if symbol.is_referenced() and (symbol.is_global() or symbol.is_declared_global()):
                if not symbol.is_assigned() or symbol.is_global():
                    yield child.get_name(), child.get_lineno(), symbol.get_name()
        yield from _global_reads(child)


def undefined_names(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    table = symtable.symtable(source, str(path), "exec")
    if "import *" in source:
        return []  # a star import can bring any name
    known = _module_names(table) | BUILTINS
    return sorted(
        f"{path.relative_to(SRC.parent)}:{line} {scope}() uses {name}"
        for scope, line, name in set(_global_reads(table))
        if name not in known
    )


class UndefinedNamesTest(unittest.TestCase):
    def test_every_name_used_in_src_is_defined(self):
        found = []
        for path in sorted(SRC.rglob("*.py")):
            found += undefined_names(path)
        self.assertEqual([], found)

    def test_the_check_finds_a_name_missing_from_a_local_import(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "src" / "sample.py"
            path.parent.mkdir()
            path.write_text(
                "def look():\n"
                "    from os.path import join\n"
                "    return join, MISSING\n",
                encoding="utf-8",
            )
            global SRC
            saved, SRC = SRC, path.parent
            try:
                self.assertEqual(["src/sample.py:1 look() uses MISSING"], undefined_names(path))
            finally:
                SRC = saved


if __name__ == "__main__":
    unittest.main()
