"""A unit-test run keeps what the tool writes in a temporary folder.

Leo's 4K checkout runs the tests in the folder he also runs the tool from:
task tests left problem records with made-up dates in its
``screenshots/problem_report`` (they showed in the 问题回报 page) and a
女神祈愿 day in ``configs`` (live 2026-10-10).  Paths that would land there
come here instead while ``python -m unittest`` runs.
"""

from __future__ import annotations

import atexit
import shutil
import sys
import tempfile
from pathlib import Path

_scratch: list[Path] = []


def active() -> bool:
    """True inside ``python -m unittest`` (never in the tool itself)."""
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    return getattr(spec, "name", "") == "unittest.__main__"


def scratch() -> Path:
    """This test run's temporary folder, removed when the run ends."""
    if not _scratch:
        path = Path(tempfile.mkdtemp(prefix="bd2-tests-"))
        atexit.register(shutil.rmtree, path, True)
        _scratch.append(path)
    return _scratch[0]
