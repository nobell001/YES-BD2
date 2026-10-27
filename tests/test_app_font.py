import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from qfluentwidgets import BodyLabel, fontFamilies, setFontFamilies

from src.ui.quest_theme import APP_FONT_FAMILIES, apply_app_font, font_families


class AppFontTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ui_font_stack_is_applied_to_qfluent_and_qt(self):
        previous_families = fontFamilies()
        previous_app_font = QApplication.instance().font()
        self.addCleanup(setFontFamilies, previous_families, False)
        self.addCleanup(QApplication.instance().setFont, previous_app_font)

        apply_app_font()
        self.assertTrue(QApplication.instance().property("bd2_bundled_font_loaded"))
        families = list(font_families())
        self.assertEqual(fontFamilies(), families)
        self.assertEqual(QApplication.instance().font().families(), families)
        label = BodyLabel("中文 English")
        self.assertEqual(label.font().families(), families)
        label.close()

    def test_windows_ui_fonts_come_before_noto(self):
        # Noto has no pixel-fitting data: uneven strokes at small sizes (2026-10-27).
        self.assertEqual("Segoe UI", APP_FONT_FAMILIES[0])
        self.assertEqual("Microsoft JhengHei UI", font_families("zh_TW")[1])
        self.assertEqual("Microsoft JhengHei UI", font_families("en_US")[1])
        self.assertEqual("Microsoft YaHei UI", font_families("zh_CN")[1])
        self.assertEqual("Yu Gothic UI", font_families("ja_JP")[1])
        self.assertEqual("Malgun Gothic", font_families("ko_KR")[1])
        for name in ("zh_TW", "zh_CN", "en_US", "ja_JP", "ko_KR"):
            families = font_families(name)
            self.assertIn("Noto Sans TC", families)
            self.assertIn("Noto Sans SC", families)
            self.assertLess(families.index("Microsoft JhengHei UI"), families.index("Noto Sans TC"))

    def test_no_widget_asks_for_noto_by_name(self):
        """Uneven strokes (Leo 2026-10-27): only the font stack may name Noto,
        as the last fallback; a widget naming it directly would bring the
        two-pixel horizontal strokes back."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src"
        allowed = {"ui/quest_theme.py", "config.py", "ui/shell/about_page.py"}
        offenders = []
        for path in root.rglob("*.py"):
            name = path.relative_to(root).as_posix()
            if name in allowed:
                continue
            if re.search(r"Noto Sans|MiSans", path.read_text(encoding="utf-8")):
                offenders.append(name)
        self.assertEqual([], offenders)

    def test_small_chinese_is_never_bold(self):
        """精's three bars ran together in bold at 14 px (Leo 2026-10-27,
        「不行就不要粗體」): bold only from theme.BOLD_MIN_PX, digits aside."""
        import re
        from pathlib import Path

        from PySide6.QtGui import QFont

        from src.ui.shell import theme

        for mode in ("light", "dark"):
            from qfluentwidgets import Theme, setTheme

            setTheme(Theme.LIGHT if mode == "light" else Theme.DARK)
            for rule in re.findall(r"\{([^{}]*)\}", theme.style_sheet()):
                weight = re.search(r"font-weight:\s*(\d+)", rule)
                if weight and int(weight.group(1)) >= 600:
                    size = re.search(r"font-size:\s*(\d+)px", rule)
                    self.assertTrue(size and int(size.group(1)) >= theme.BOLD_MIN_PX, rule)

        small = QFont()
        small.setPixelSize(14)
        self.assertFalse(theme.strong(QFont(small)).bold())
        self.assertTrue(theme.strong(QFont(small), digits=True).bold())
        big = QFont()
        big.setPixelSize(theme.BOLD_MIN_PX)
        self.assertTrue(theme.strong(big).bold())

        root = Path(__file__).resolve().parents[1] / "src" / "ui"
        pattern = re.compile(
            r"setBold\(True\)|Weight\.(Bold|DemiBold|ExtraBold|Black)|font-weight:\s*([6-9]00|bold)"
        )
        offenders = [
            f"{path.relative_to(root).as_posix()}:{number}"
            for path in root.rglob("*.py")
            if path.name != "theme.py"
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if pattern.search(line)
        ]
        self.assertEqual([], offenders, "use theme.strong() instead")

    def test_bundled_fonts_cover_both_scripts(self):
        from PySide6.QtGui import QFontDatabase

        apply_app_font()
        families = set(QFontDatabase.families())
        self.assertIn("Noto Sans TC", families)
        self.assertIn("Noto Sans SC", families)


if __name__ == "__main__":
    unittest.main()
