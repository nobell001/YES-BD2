"""Text is read at the captured size: nothing shrinks a frame to 720 first."""

import re
import unittest
from pathlib import Path

from src.utils import ocr_size

ROOT = Path(__file__).resolve().parents[1]


class ReadSizeTest(unittest.TestCase):
    def test_read_height_keeps_the_captured_size(self):
        self.assertEqual(0, ocr_size.READ_HEIGHT)

    def test_no_text_read_names_a_shrink_height(self):
        # 2560x1440 繁中 shrunk to 720 read 戰鬥 as 戰門 (4K PC 2026-11-06).
        found = [
            f"{path.relative_to(ROOT)}:{number}"
            for path in (ROOT / "src").rglob("*.py")
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if re.search(r"target_height(: int)?\s*=\s*[1-9]", line)
        ]
        self.assertEqual([], found)


if __name__ == "__main__":
    unittest.main()


class BaseOcrNeverShrinksTest(unittest.TestCase):
    def test_a_caller_asking_for_720_still_reads_the_captured_size(self):
        from unittest import mock

        import numpy as np
        from ok import BaseTask

        from src.tasks.BaseBD2Task import BaseBD2Task

        task = object.__new__(BaseBD2Task)
        seen = []
        with mock.patch.object(BaseTask, "ocr", lambda _self, *a, **k: seen.append(k) or [], create=True):
            task.ocr(frame=np.zeros((1440, 2560, 3), np.uint8), target_height=720, reread=False)
        self.assertEqual(0, seen[0]["target_height"])
