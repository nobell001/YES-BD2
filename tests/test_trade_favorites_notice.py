"""收藏清单 after the 2026-11-19 跑商 change (Leo 2026-11-19 「更新後提醒用戶去打開
新的收藏清單 然後收藏清單 加個超連結連到我的新影片」).

Players who had the tool before are walked once to the updated chart; a
fresh install is not.  The chart links Leo's video.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.tasks.MapTradeTask import FAVORITES_NOTICE_KEY, MapTradeTask
from src.ui.shell import new_setting_notice

app = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parent.parent


def _launch(temp_dir, saved):
    if saved is not None:
        (Path(temp_dir) / "MapTradeTask.json").write_text(
            json.dumps(saved, ensure_ascii=False), encoding="utf-8"
        )
    with mock.patch("ok.util.config.Config.config_folder", temp_dir):
        task = MapTradeTask(SimpleNamespace(scene=None), SimpleNamespace())
        task.load_config()
        return task


class NoticeFlagTest(unittest.TestCase):
    def test_a_player_from_before_is_asked_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task = _launch(temp_dir, {"买": True, "卖": True})
            self.assertTrue(task.config[FAVORITES_NOTICE_KEY])

    def test_a_fresh_install_is_not_asked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertFalse(_launch(temp_dir, None).config[FAVORITES_NOTICE_KEY])

    def test_once_shown_it_stays_off(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            saved = {"买": True, FAVORITES_NOTICE_KEY: False}
            self.assertFalse(_launch(temp_dir, saved).config[FAVORITES_NOTICE_KEY])

    def test_the_key_is_hidden_from_the_settings(self):
        self.assertTrue(FAVORITES_NOTICE_KEY.startswith("_"))


class WalkThroughTest(unittest.TestCase):
    def test_notice_shows_once_then_clears(self):
        task = SimpleNamespace(config={FAVORITES_NOTICE_KEY: True})
        shown = []
        shell = mock.Mock()
        with mock.patch.object(
            new_setting_notice.data, "task_by_class_name", return_value=task
        ), mock.patch.object(new_setting_notice, "CoachMarks") as tour:
            tour.return_value.start.side_effect = lambda: shown.append(1)
            self.assertTrue(new_setting_notice.show_favorites_notice(shell))
            self.assertFalse(new_setting_notice.show_favorites_notice(shell))
        self.assertEqual(1, len(shown))
        self.assertFalse(task.config[FAVORITES_NOTICE_KEY])

    def test_it_is_in_the_list_shown_after_an_update(self):
        self.assertIn(new_setting_notice.show_favorites_notice, new_setting_notice.NOTICES)

    def test_tour_points_at_trade_then_at_the_favorites_row(self):
        shell = mock.Mock()
        first, second = new_setting_notice.favorites_steps(shell)
        first.target()
        shell.sidebar.items.get.assert_called_with("trade")
        self.assertIn("收藏清单", first.title)
        second.before()
        shell.navigate.assert_called_with("trade")
        self.assertIs(shell.pages.get.return_value.favorites_row, second.target())
        for words in ("斜线", "影片"):
            self.assertIn(words, second.body)


class VideoLinkTest(unittest.TestCase):
    def test_the_chart_links_leos_video(self):
        from src.ui.shell import trade_favorites

        self.assertEqual(
            "https://www.bilibili.com/video/BV1qQst6BE4e/", trade_favorites.TRADE_VIDEO_URL
        )
        card = trade_favorites.FavoritesCard()
        self.assertEqual(trade_favorites.TRADE_VIDEO_URL, card.video_button.toolTip())
        with mock.patch("PySide6.QtGui.QDesktopServices.openUrl") as opened:
            card.video_button.click()
        opened.assert_called_once()
        self.assertEqual(trade_favorites.TRADE_VIDEO_URL, opened.call_args[0][0].toString())


class TranslatedTest(unittest.TestCase):
    def test_every_new_line_is_translated(self):
        from src.ui.shell.trade_favorites import TRADE_VIDEO_LABEL

        steps = new_setting_notice.favorites_steps(mock.Mock())
        sources = [TRADE_VIDEO_LABEL] + [s.title for s in steps] + [s.body for s in steps]
        for lang in ("en_US", "ja_JP", "ko_KR", "zh_TW"):
            text = (ROOT / "i18n" / lang / "LC_MESSAGES" / "ok.po").read_text(encoding="utf-8")
            for source in sources:
                with self.subTest(lang=lang, source=source):
                    start = text.index(f'msgid "{source}"\n')
                    msgstr = text[start:].split("\n")[1]
                    self.assertTrue(msgstr.startswith('msgstr "') and len(msgstr) > len('msgstr ""'))


if __name__ == "__main__":
    unittest.main()
