"""Every test module a workflow names must exist.

2026-11-22: #531 removed tests/test_fiend_hunt_souseha.py with the 魔兽
feature, but 角色名单更新 and 官网公告 still listed it.  Their check step only
runs when something new comes in, so the missing module went unnoticed until
the next new costume (贝那卡 折桂之姿, 11-19), and every run after failed."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = re.compile(r"\btests\.(test_\w+)")


class WorkflowTestListsTest(unittest.TestCase):
    def test_every_named_test_module_exists(self):
        missing = []
        for workflow in sorted((REPO / ".github" / "workflows").glob("*.yml")):
            for name in MODULE.findall(workflow.read_text(encoding="utf-8")):
                if not (REPO / "tests" / f"{name}.py").is_file():
                    missing.append(f"{workflow.name}: tests.{name}")
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
