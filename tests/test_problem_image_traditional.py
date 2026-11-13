"""A 繁中 player's 问题摘要 is Traditional Chinese, all of it (Leo 2026-11-12, YES-BD2 #82)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication

from src.ui.shell import problem_image
from src.utils import game_language
from tests.test_problem_image import record

# Characters only Simplified Chinese writes; none may be left for a 繁中 player.
SIMPLIFIED_MARKS = "问题键调试带认图开页结择读这后录记为换动关画缩简戏没复"


def with_env(**env):
    found = record()
    found["problem"]["env"] = dict(found["problem"]["env"], **env)
    found["problem"]["reads"] = [
        {"at": found["finished"] - 2, "key": "卡带选择页 OCR", "text": "第12章 卡带"},
    ]
    found["problem"]["steps"] = [
        {"at": found["finished"] - 3, "task": "每周跑图", "text": "点开卡带选择页"},
    ]
    return found


class TraditionalCueTest(unittest.TestCase):
    def setUp(self):
        game_language.reset()
        self.addCleanup(game_language.reset)

    def test_simplified_player_stays_simplified(self):
        found = with_env()
        self.assertFalse(problem_image.traditional(found))
        self.assertIn("停在：每周跑图", problem_image.summary_text(found))

    def test_traditional_game_client(self):
        found = with_env(game_language=game_language.TRADITIONAL_LABEL)
        self.assertTrue(problem_image.traditional(found))

    def test_traditional_tool_language(self):
        self.assertTrue(problem_image.traditional(with_env(ui_language="繁體中文")))

    def test_tool_showing_traditional_now(self):
        with mock.patch.object(problem_image, "tool_shows_traditional", return_value=True):
            self.assertTrue(problem_image.traditional(with_env()))

    def test_client_seen_this_session(self):
        # A run that failed before home was read has no game_language saved.
        game_language.note_text("格魯 街機遊戲 抽抽樂 經營管理")
        self.assertTrue(problem_image.traditional(with_env()))


class TraditionalTextTest(unittest.TestCase):
    def setUp(self):
        game_language.reset()
        self.found = with_env(game_language=game_language.TRADITIONAL_LABEL)

    def assert_traditional(self, text):
        left = sorted({c for c in text if c in SIMPLIFIED_MARKS})
        self.assertEqual([], left, text)

    def test_copied_text_is_all_traditional(self):
        text = problem_image.summary_text(self.found)
        self.assert_traditional(text)
        # The task's own log line and the step name are converted too.
        self.assertIn("每週跑圖", text)
        self.assertIn("認不到卡帶編號", text)

    def test_taiwan_words(self):
        self.found["problem"]["env"]["window_mode"] = "全屏"
        self.assertIn("1467×824 全螢幕", problem_image.summary_text(self.found))

    def test_file_names(self):
        self.assertTrue(problem_image.file_name(self.found).startswith("YES-BD2-問題-"))
        self.assertIn("完整記錄", problem_image.full_log_name(self.found))

    def test_full_log(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "run.log"
            log.write_text("12:00:00 每周跑图：认不到卡带编号\n", encoding="utf-8")
            self.found["log_path"] = str(log)
            text = problem_image.full_log_text(self.found)
        self.assert_traditional(text)
        self.assertIn("每週跑圖：認不到卡帶編號", text)


class TraditionalPictureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def drawn(self, found):
        seen = []
        original = problem_image._Pen.say

        def say(pen, text):
            out = original(pen, text)
            seen.append(out)
            return out

        with mock.patch.object(problem_image._Pen, "say", say):
            image = problem_image.render(found)
        self.assertFalse(image.isNull())
        return "\n".join(seen)

    def test_every_drawn_word_is_traditional(self):
        game_language.reset()
        drawn = self.drawn(with_env(game_language=game_language.TRADITIONAL_LABEL))
        self.assertIn("問題摘要", drawn)
        self.assertIn("每週跑圖", drawn)
        self.assertIn("遊戲語言：繁體中文", drawn)
        left = sorted({c for c in drawn if c in SIMPLIFIED_MARKS})
        self.assertEqual([], left)

    def test_simplified_picture_unchanged(self):
        game_language.reset()
        drawn = self.drawn(with_env())
        self.assertIn("问题摘要", drawn)


if __name__ == "__main__":
    unittest.main()
