"""One design language for the tool's pages (Leo 2026-11-09: 「統一的設計語言」,
pages that don't look 「拼裝」).

Colours come from theme.LIGHT / theme.DARK and sizes from theme.SIZES, so a
part added later sits in the same system.  These checks keep it that way:
the shared parts in widgets.py use no colour of their own, and no page gains
new hard-coded colours (the old ones are counted and may only go down).
"""

import re
import unittest
from pathlib import Path

SHELL = Path(__file__).resolve().parents[1] / "src" / "ui" / "shell"
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")

# Colours written in a page before 2026-11-09 (the game overlay, the report
# picture and a few fixed avatar / chart tints).  Only lower these.
KNOWN = {
    "accounts_ui.py": 2,
    "fiend_team.py": 5,
    "game_status.py": 9,
    "home.py": 1,
    "problem_image.py": 13,
    "run_confirm.py": 1,
    "schedule_week.py": 6,
}


class DesignLanguageTest(unittest.TestCase):
    def test_pages_take_their_colours_from_the_theme(self):
        for path in sorted(SHELL.glob("*.py")):
            if path.name == "theme.py":
                continue
            with self.subTest(file=path.name):
                found = len(HEX.findall(path.read_text(encoding="utf-8")))
                self.assertLessEqual(
                    found,
                    KNOWN.get(path.name, 0),
                    f"{path.name}: use a colour from theme.LIGHT / theme.DARK",
                )

    def test_both_looks_name_the_same_colours(self):
        from src.ui.shell import theme

        self.assertEqual(set(theme.LIGHT), set(theme.DARK))

    def test_side_by_side_controls_share_the_heights(self):
        from src.ui.shell import theme

        heights = [theme.size(f"control_{name}") for name in ("sm", "md", "lg")]
        self.assertEqual(sorted(heights), heights)
        self.assertTrue(all(height % 2 == 0 for height in heights))
        sheet = theme.style_sheet()
        for height in heights:
            self.assertIn(f"min-height: {height}px", sheet)


if __name__ == "__main__":
    unittest.main()
