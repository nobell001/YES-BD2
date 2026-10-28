"""Every file the tool ships under src/ is in git (2026-10-28: 塔洛斯's ✕
picture sat in an ignored data folder, so the branch ran without it and
crashed on the first read of the stage list)."""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ShippedFilesTrackedTest(unittest.TestCase):
    def test_nothing_under_src_is_ignored(self):
        if shutil.which("git") is None or not (ROOT / ".git").exists():
            self.skipTest("no git checkout")
        out = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "src"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        hidden = [p for p in out if "__pycache__" not in p and not p.endswith((".pyc", ".pyo"))]
        self.assertEqual([], hidden, "ignored by .gitignore but under src/ (would not ship)")


if __name__ == "__main__":
    unittest.main()
