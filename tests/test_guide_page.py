import gettext
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.shell import guide_page
from src.ui.shell.guide_page import GuidePage, GuidePicture
from src.ui.shell.sidebar import Sidebar

CATALOG_ROOT = Path(__file__).resolve().parents[1] / "i18n"
PICTURES = ("skills", "minimap_small", "minimap_big", "battle_button", "battle_dialog")
SOURCE = Path(guide_page.__file__).read_text(encoding="utf-8")


class _Item:
    def __init__(self):
        self.badge = ""
        self.kind = ""

    def set_badge(self, text, kind=""):
        self.badge = text
        self.kind = kind


class GuidePageTest(unittest.TestCase):
    """Leo 2026-10-05: a picture guide in the sidebar for new players."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.mkdtemp()
        patcher = mock.patch.object(guide_page, "SEEN_FILE", Path(folder) / "ui_guide.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sidebar_lists_the_guide_above_settings(self):
        keys = [key for key, _label, _icon in Sidebar.BOTTOM]
        # Leo 2026-10-14: 桌面分身 has its own guide page under 使用说明;
        # 2026-10-22: 使用说明 first of these.
        self.assertEqual(["guide", "problem", "clone", "settings", "about"], keys)

    def test_guide_is_grouped_in_cards_wechat_first(self):
        # Leo 2026-10-22: cards by topic, the 微信通知 steps on top.
        page = GuidePage()
        cards = page.slides.cards
        self.assertEqual(5, len(cards))
        self.assertIn("微信通知", cards[0].title.text())
        self.assertEqual(["wechat", "start", "map", "map", "map"], page._topic_of)
        page.close()

    def test_cards_turn_left_and_right_without_scrolling(self):
        # Leo 2026-10-22 「不要下拉 每個卡片左右切」.
        page = GuidePage()
        page.resize(1000, 760)
        page.show()
        self.app.processEvents()
        self.assertEqual(0, page.verticalScrollBar().maximum())
        self.assertFalse(page.back.isEnabled())
        page.go(1)
        self.assertEqual(1, page.slides.index)
        self.assertEqual("start", page.tabs.value())
        page._show_topic("map")
        self.assertEqual(2, page.slides.index)
        page.show_card(99)
        self.assertEqual(4, page.slides.index)
        self.assertFalse(page.next.isEnabled())
        self.assertEqual("5 / 5", page.count.text())
        page.close()

    def test_every_picture_exists_and_loads(self):
        for name in PICTURES:
            with self.subTest(name=name):
                self.assertTrue(Path(guide_page.picture_path(name)).exists())
                self.assertTrue(GuidePicture(name, 300).has_picture())

    def test_badge_always_says_must_read(self):
        # Leo 2026-10-09: always marked 必看 (it used to go once opened).
        sidebar = SimpleNamespace(items={"guide": _Item()})
        navigated = []
        page = GuidePage(navigated.append, sidebar)
        self.assertEqual("必看", sidebar.items["guide"].badge)
        # Leo 2026-10-22: in the soft rose, not the plain grey chip.
        self.assertEqual("must", sidebar.items["guide"].kind)
        page.show()
        self.app.processEvents()
        self.assertEqual("必看", sidebar.items["guide"].badge)
        self.assertTrue(guide_page.seen())
        GuidePage(navigated.append, sidebar)
        self.assertEqual("必看", sidebar.items["guide"].badge)
        page.close()

    def test_settings_buttons_open_their_pages(self):
        navigated = []
        page = GuidePage(navigated.append)
        page._go("trade")
        self.assertEqual(["trade"], navigated)

    def test_guide_text_is_translated(self):
        # Every quoted Chinese line in the page has an English entry.
        import re

        catalog = gettext.translation("ok", CATALOG_ROOT, languages=["en_US"])
        texts = set(re.findall(r'"([^"\n]*[一-鿿][^"\n]*)"', SOURCE))
        texts = {text for text in texts if not text[:1].isascii()}  # docstrings
        missing = [text for text in texts if catalog.gettext(text) == text]
        self.assertEqual([], sorted(missing))

    def test_map_skills_card_says_where_the_cooking_skill_goes(self):
        # Leo 2026-11-28: 跑商 kept failing with no cooking skill on the
        # bottom-right bar; the 跑图 skills card now says to put it there.
        from src.ui.traditional import to_traditional

        line = "跑商要做料理：料理技能也要放在右下角（哪一组、哪一格都可以）"
        self.assertIn(f'"{line}"', SOURCE)
        self.assertLess(SOURCE.index("技能按顺序放"), SOURCE.index(line))
        self.assertLess(SOURCE.index(line), SOURCE.index("左上角保持小地图"))
        self.assertEqual(
            "跑商要做料理：料理技能也要放在右下角（哪一組、哪一格都可以）",
            to_traditional(line),
        )
        for lang in ("en_US", "ja_JP", "ko_KR"):
            with self.subTest(lang=lang):
                catalog = gettext.translation("ok", CATALOG_ROOT, languages=[lang])
                self.assertNotEqual(line, catalog.gettext(line))


if __name__ == "__main__":
    unittest.main()
