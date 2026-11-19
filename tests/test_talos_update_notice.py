"""塔洛斯 after a records update (Leo 2026-11-19 「更新後提醒一下更新了塔洛斯」
「提醒用戶」).

A player who had the tool before is walked once to the 塔洛斯教材 page when
the shipped records are for another period than the one they were told
about; a fresh install is not.  The next period's records tell them again.
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

from src.tasks import TalosTask as talos_module
from src.tasks.fiend_hunt.recording import RECORD_FILE
from src.tasks.talos import stages
from src.tasks.TalosTask import SEASON_NOTICE_KEY, TalosTask
from src.ui.shell import new_setting_notice
from src.ui.traditional import to_traditional

app = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parent.parent


def _launch(temp_dir, saved):
    if saved is not None:
        (Path(temp_dir) / "TalosTask.json").write_text(
            json.dumps(saved, ensure_ascii=False), encoding="utf-8"
        )
    with mock.patch("ok.util.config.Config.config_folder", temp_dir):
        task = TalosTask(SimpleNamespace(scene=None), SimpleNamespace())
        task.load_config()
        return task


class SeasonTest(unittest.TestCase):
    def test_the_shipped_records_name_their_season(self):
        self.assertIn("第十赛季", stages.season())

    def test_without_a_season_name_the_records_edition_stands_in(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual("", stages.season(root))  # no records at all
            folder = stages.record_folder(1, root)
            folder.mkdir()
            (folder / RECORD_FILE).write_text("{}", encoding="utf-8")
            (root / stages.SOURCE_FILE).write_text('{"stages": 1}', encoding="utf-8")
            self.assertEqual(stages.edition(root), stages.season(root))
            (root / stages.SOURCE_FILE).write_text('{"season": " 第十一赛季 "}', encoding="utf-8")
            self.assertEqual("第十一赛季", stages.season(root))


class NoticeFlagTest(unittest.TestCase):
    def test_a_player_from_before_is_told(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task = _launch(temp_dir, {"领取任务奖励": True})
            self.assertTrue(task.season_news())

    def test_a_player_from_before_talos_is_told(self):
        """v0.3.x had no TalosTask.json, only the older tasks' files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "MapTradeTask.json").write_text('{"买": true}', encoding="utf-8")
            self.assertTrue(_launch(temp_dir, None).season_news())

    def test_a_fresh_install_is_not_told(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertFalse(_launch(temp_dir, None).season_news())

    def test_on_a_fresh_install_the_older_file_comes_after_talos(self):
        """ok-script loads the tasks in src/config.py's order, each writing its
        file: 跑商's must come after 塔洛斯 or a fresh install looks old."""
        from src.config import config
        from src.tasks.TalosTask import EARLIER_TASK_FILE

        names = [name for _module, name in config["onetime_tasks"]]
        self.assertLess(names.index("TalosTask"), names.index(EARLIER_TASK_FILE))

    def test_once_told_it_stays_quiet(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            saved = {SEASON_NOTICE_KEY: stages.season()}
            self.assertFalse(_launch(temp_dir, saved).season_news())

    def test_the_next_season_tells_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            saved = {SEASON_NOTICE_KEY: stages.season()}
            task = _launch(temp_dir, saved)
            with mock.patch.object(talos_module.stages, "season", return_value="第十一赛季"):
                self.assertTrue(task.season_news())
                task.season_told()
                self.assertFalse(task.season_news())

    def test_the_key_is_hidden_from_the_settings(self):
        self.assertTrue(SEASON_NOTICE_KEY.startswith("_"))


class WalkThroughTest(unittest.TestCase):
    def _task(self):
        task = TalosTask(SimpleNamespace(scene=None), SimpleNamespace())
        task.config = {SEASON_NOTICE_KEY: ""}
        return task

    def test_notice_shows_once_then_clears(self):
        task = self._task()
        shown = []
        shell = mock.Mock()
        with mock.patch.object(
            new_setting_notice.data, "task_by_class_name", return_value=task
        ), mock.patch.object(new_setting_notice, "CoachMarks") as tour:
            tour.return_value.start.side_effect = lambda: shown.append(1)
            self.assertTrue(new_setting_notice.show_talos_notice(shell))
            self.assertFalse(new_setting_notice.show_talos_notice(shell))
        self.assertEqual(1, len(shown))
        self.assertEqual(stages.season(), task.config[SEASON_NOTICE_KEY])

    def test_no_task_no_notice(self):
        with mock.patch.object(new_setting_notice.data, "task_by_class_name", return_value=None):
            self.assertFalse(new_setting_notice.show_talos_notice(mock.Mock()))

    def test_it_is_first_in_the_list_shown_after_an_update(self):
        self.assertIs(new_setting_notice.show_talos_notice, new_setting_notice.NOTICES[0])

    def test_tour_points_at_talos_then_at_the_start_button(self):
        shell = mock.Mock()
        first, second = new_setting_notice.talos_steps(shell)
        first.target()
        shell.sidebar.items.get.assert_called_with("talos")
        self.assertIn("塔洛斯", first.title)
        self.assertIn(f"共 {stages.STAGE_COUNT} 关", first.body)
        second.before()
        shell.navigate.assert_called_with("talos")
        self.assertIs(shell.pages.get.return_value.start_button, second.target())

    def test_the_talos_page_has_the_button_the_tour_lights(self):
        from src.ui.shell.talos_page import TalosPage

        self.assertIsNotNone(TalosPage().start_button)


class BothChineseTest(unittest.TestCase):
    """Leo 2026-11-19 「你繁中簡中都要設計好啊」: the walk-through reads right
    on a 简中 and on a 繁中 tool."""

    SOURCES = (
        "塔洛斯更新了",
        new_setting_notice.TALOS_NEWS,
        "在这里开始打",
        "勾选要打的关，游戏停在主页时按这里就会照顺序打，打过的关会自己跳过。",
    )

    def test_the_steps_use_these_lines(self):
        steps = new_setting_notice.talos_steps(mock.Mock())
        shown = [steps[0].title, steps[1].title, steps[1].body]
        for source in (self.SOURCES[0], self.SOURCES[2], self.SOURCES[3]):
            self.assertIn(source, shown)

    def test_the_simplified_lines_have_no_traditional_characters(self):
        from src.ui.traditional import to_simplified

        for source in self.SOURCES:
            self.assertEqual(source, to_simplified(source))

    def test_the_traditional_lines_read_traditional(self):
        text = (ROOT / "i18n" / "zh_TW" / "LC_MESSAGES" / "ok.po").read_text(encoding="utf-8")
        for source in self.SOURCES:
            with self.subTest(source=source):
                start = text.index(f'msgid "{source}"\n')
                shown = text[start:].split("\n")[1][len('msgstr "') : -1]
                self.assertEqual(to_traditional(source), shown)
        self.assertIn("塔洛斯戰術教材", to_traditional(new_setting_notice.TALOS_NEWS))
        self.assertIn("{n} 關", to_traditional(new_setting_notice.TALOS_NEWS))

    def test_every_new_line_is_translated(self):
        for lang in ("en_US", "ja_JP", "ko_KR", "zh_TW"):
            text = (ROOT / "i18n" / lang / "LC_MESSAGES" / "ok.po").read_text(encoding="utf-8")
            for source in self.SOURCES:
                with self.subTest(lang=lang, source=source):
                    start = text.index(f'msgid "{source}"\n')
                    msgstr = text[start:].split("\n")[1]
                    self.assertTrue(msgstr.startswith('msgstr "') and len(msgstr) > len('msgstr ""'))
                    if "{n}" in source:
                        self.assertIn("{n}", msgstr)


if __name__ == "__main__":
    unittest.main()
