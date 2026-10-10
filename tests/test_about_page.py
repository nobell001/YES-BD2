import gettext
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from src.ui.shell import about_page, update_notes
from src.ui.shell.about_page import CREDITS, NOTICE, AboutPage, souseha_url
from src.ui.shell.widgets import Text

CATALOG_ROOT = Path(__file__).resolve().parents[1] / "i18n"


class _FakeUpdateCard(QWidget):
    update_available_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.checks = 0

    def check_for_updates(self):
        self.checks += 1


class _FakeCombo:
    def __init__(self, text):
        self.text = text

    def currentText(self):
        return self.text


class _NotesUpdateCard(_FakeUpdateCard):
    """The parts of ok's UpdateCard that show release notes."""

    def __init__(self):
        super().__init__()
        self.current_version = "v0.1.18"
        self.version_combo = _FakeCombo("v0.1.18")
        self.notes_edit = QWidget(self)

    def _set_notes(self, text):
        self.notes_edit.setVisible(bool(text))


class _FakeItem(QObject):
    def __init__(self):
        super().__init__()
        self.badge = ""

    def set_badge(self, text, kind=""):
        self.badge = text


class AboutPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_credits_name_what_the_tool_uses(self):
        # Leo (2026-10-05): BetterGI, souseha's 图鉴 and 時樂淵's 跑商 sheet.
        names = {credit.name for credit in CREDITS}
        for name in ("ok-bd2", "ok-script", "BetterGI", "ChildStream", "MaaBD2", "BD2DB 图鉴"):
            self.assertIn(name, names)
        sheet = next(credit for credit in CREDITS if credit.name == "跑商售卖物品表")
        self.assertIn("時樂淵", sheet.who)
        self.assertEqual(sheet.url, "https://space.bilibili.com/14949646")

    def test_souseha_opens_in_the_ui_language(self):
        self.assertEqual(souseha_url("zh_TW"), "https://browndust2-db.souseha.com/tw/")
        self.assertEqual(souseha_url("zh_CN"), "https://browndust2-db.souseha.com/cn/")
        self.assertEqual(souseha_url("en_US"), "https://browndust2-db.souseha.com/en/")
        self.assertEqual(souseha_url("ja_JP"), "https://browndust2-db.souseha.com/ja/")
        self.assertEqual(souseha_url("ko_KR"), "https://browndust2-db.souseha.com/ko/")
        self.assertEqual(souseha_url("fr_FR"), "https://browndust2-db.souseha.com/")

    def test_notice_and_credits_follow_every_language(self):
        texts = list(NOTICE) + [credit.what for credit in CREDITS]
        texts += ["关于", "版本、更新和致谢", "使用须知", "致谢（参考或使用了这些项目）"]
        texts += ["BD2DB 图鉴", "跑商售卖物品表", "思源黑体 Noto Sans", "版本 {version}"]
        for language in ("en_US", "ja_JP", "ko_KR"):
            catalog = gettext.translation("ok", CATALOG_ROOT, languages=[language])
            for text in texts:
                self.assertNotEqual(catalog.gettext(text), text, (language, text))

    def test_update_controls_move_to_the_new_page(self):
        card = _FakeUpdateCard()
        window = SimpleNamespace(about_tab=SimpleNamespace(update_card=card))
        item = _FakeItem()
        sidebar = SimpleNamespace(items={"about": item})
        page = AboutPage(window, sidebar)
        self.assertIs(page.update_card, card)
        self.assertTrue(page.isAncestorOf(card))
        page.check_for_updates()
        self.assertEqual(card.checks, 1)
        card.update_available_changed.emit(True)
        self.assertTrue(item.badge)
        self.assertTrue(page.update_pill.text())
        card.update_available_changed.emit(False)
        self.assertEqual(item.badge, "")

    def _notes_file(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "update_notes.json"
        path.write_text(
            json.dumps(
                {
                    "versions": [
                        {"version": "v0.1.18", "notes": [f"改动{i}" for i in range(65)]},
                        {"version": "v0.1.17", "notes": ["甲"]},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_update_notes_show_once_scroll_and_list_every_line(self):
        # Leo 2026-10-10: 「更新內容 要可以滾動 然後每行前面要有 小圓點 不要重複」
        path = self._notes_file()
        card = _NotesUpdateCard()
        window = SimpleNamespace(about_tab=SimpleNamespace(update_card=card))
        change = SimpleNamespace(
            from_version="v0.1.17", to_version="v0.1.18", content="\n".join("abcdefghij")
        )
        with mock.patch.object(update_notes, "NOTES_FILE", path), mock.patch(
            "ok.ui.qt.util.pyappify_startup.get_startup_version_change", return_value=change
        ):
            page = AboutPage(window)
        page.resize(1200, 900)
        page.show()
        self.app.processEvents()
        box = page.notes_box
        self.assertEqual("v0.1.17 → v0.1.18", box.title.text())
        self.assertEqual(65, len(box.rows))
        self.assertEqual("改动0", box.rows[0].text())
        # every line has its own dot; the list scrolls inside a fixed height
        dots = [label for label in box.findChildren(Text) if label.text() == "•"]
        self.assertEqual(65, len(dots))
        self.assertLessEqual(box.scroll.height(), box.MAX_LIST_HEIGHT)
        self.assertGreater(box.scroll.verticalScrollBar().maximum(), 0)

        # Checking for updates lands its notes in the same box, not a second list.
        card.version_combo.text = "v0.1.19"
        card._set_notes("• 新一\n• 新二")
        self.assertFalse(card.notes_edit.isVisible())
        self.assertEqual("v0.1.18 → v0.1.19", box.title.text())
        self.assertEqual(["新一", "新二"], [row.text() for row in box.rows])
        card.version_combo.text = "v0.1.17"
        card._set_notes("• 甲")
        self.assertEqual("v0.1.18 → v0.1.17", box.title.text())
        self.assertEqual(65, len(box.rows))
        card._set_notes("")
        self.assertEqual("v0.1.17 → v0.1.18", box.title.text())
        page.close()

    def test_without_an_update_the_box_shows_this_version(self):
        path = self._notes_file()
        card = _NotesUpdateCard()
        window = SimpleNamespace(about_tab=SimpleNamespace(update_card=card))
        with mock.patch.object(update_notes, "NOTES_FILE", path), mock.patch(
            "ok.ui.qt.util.pyappify_startup.get_startup_version_change", return_value=None
        ):
            page = AboutPage(window)
        self.assertEqual("v0.1.18", page.notes_box.title.text())
        self.assertEqual(65, len(page.notes_box.rows))

    def test_source_checkout_has_no_update_controls_but_a_github_row(self):
        page = AboutPage(SimpleNamespace(about_tab=None))
        self.assertIsNone(page.update_card)
        self.assertEqual(about_page.PROJECT_URL, "https://github.com/nobell001/YES-BD2")
        urls = [row.url for row in page.findChildren(about_page.LinkRow)]
        self.assertEqual(len(urls), len(CREDITS) + 1)
        self.assertIn(about_page.PROJECT_URL, urls)
        self.assertNotIn("", urls)


if __name__ == "__main__":
    unittest.main()
