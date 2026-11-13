"""Report notes with numbers, in the app's language (Leo 2026-11-13:
「已掃蕩救贖之塔LV7 9場」 in all five languages)."""

import gettext
import unittest
from pathlib import Path

from src.tasks.RedemptionTowerTask import swept_note
from src.ui.note_templates import TEMPLATES, translate
from src.ui.traditional import to_traditional

I18N = Path(__file__).resolve().parents[1] / "i18n"


def catalog(code):
    with open(I18N / code / "LC_MESSAGES" / "ok.mo", "rb") as file:
        return gettext.GNUTranslations(file).gettext


class NoteTemplateTest(unittest.TestCase):
    def test_every_template_in_every_catalog(self):
        for code in ("en_US", "ja_JP", "ko_KR"):
            tr = catalog(code)
            for template in TEMPLATES:
                with self.subTest(code=code, template=template):
                    self.assertNotEqual(template, tr(template))

    def test_numbers_are_put_back(self):
        self.assertEqual(
            "Swept Tower of Redemption LV7 ×9", translate(swept_note(7, 9), catalog("en_US"))
        )
        self.assertIn("LV7", translate(swept_note(7, 9), catalog("ko_KR")))
        self.assertIn("9", translate(swept_note(7, 9), catalog("ja_JP")))

    def test_chinese_stays_and_traditional_converts(self):
        self.assertEqual("已扫荡救赎之塔LV7 9场", translate(swept_note(7, 9), lambda s: s))
        self.assertEqual("已掃蕩救贖之塔LV7 9場", to_traditional(swept_note(7, 9)))

    def test_other_text_is_left_alone(self):
        self.assertIsNone(translate("已扫荡救赎之塔LVx 9场", lambda s: s))
        self.assertIsNone(translate("今天已经做完", lambda s: s))


if __name__ == "__main__":
    unittest.main()
