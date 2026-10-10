"""The 繁中 game client gets a hint to switch to 简体中文 (YES-BD2 issue #3)."""

import unittest

from src.tasks.BaseBD2Task import BaseBD2Task
from src.utils import game_language
from src.utils.home_confirmation import home_gacha_ocr_matches, home_left_column_hits


class _Task:
    def __init__(self):
        self.info = {}
        self.warnings = []

    def info_set(self, key, value):
        self.info[key] = value

    def log_warning(self, message, notify=False):
        self.warnings.append((message, notify))


class GameLanguageTest(unittest.TestCase):
    def setUp(self):
        game_language.reset()
        self.addCleanup(game_language.reset)

    def test_traditional_home_text_is_recognised(self):
        self.assertTrue(game_language.looks_traditional("我的小屋格魯TALK街機遊戲"))
        self.assertTrue(game_language.looks_traditional("抽抽樂 經營管理"))

    def test_simplified_home_text_is_not(self):
        self.assertFalse(game_language.looks_traditional("我的小屋格鲁TALK街机游戏"))
        self.assertFalse(game_language.looks_traditional("抽抽乐"))
        self.assertFalse(game_language.looks_traditional(""))
        self.assertFalse(game_language.looks_traditional(None))

    def test_a_broken_logger_never_hides_the_failure(self):
        class _NoLogger(_Task):
            def log_warning(self, message, notify=False):
                raise AttributeError("'Task' object has no attribute 'logger'")

        game_language.note_text("抽抽樂 經營管理", now=10.0)
        self.assertEqual(game_language.MESSAGE, game_language.warn_after_failure(_NoLogger(), 5.0))

    def test_one_stray_character_is_not_enough(self):
        self.assertFalse(game_language.looks_traditional("抽抽樂"))

    def test_home_checks_note_what_they_read(self):
        home_left_column_hits("我的小屋格魯TALK街機遊戲")
        self.assertTrue(game_language.seen_since(0.0))

    def test_a_players_traditional_text_leaves_no_trace(self):
        # A 繁中 guild description read where home's left column would be.
        home_left_column_hits("8 30/30 审核 申請請DC聯絡公 #zaga12022")
        home_gacha_ocr_matches("小尤里樂園Ⅱ 申請請DC聯絡公會長")
        self.assertFalse(game_language.seen_since(0.0))

    def test_simplified_home_leaves_no_trace(self):
        home_left_column_hits("我的小屋格鲁TALK街机游戏")
        home_gacha_ocr_matches("抽抽乐")
        self.assertFalse(game_language.seen_since(0.0))

    def test_failure_after_traditional_text_warns_once(self):
        game_language.note_text("街機遊戲", now=100.0)
        task = _Task()
        hint = game_language.warn_after_failure(task, 50.0, now=101.0)
        self.assertEqual(game_language.MESSAGE, hint)
        self.assertEqual(game_language.MESSAGE, task.info[game_language.NOTICE_KEY])
        self.assertEqual([(game_language.MESSAGE, True)], task.warnings)
        # The next child of the same batch fails too: logged, no second popup.
        game_language.warn_after_failure(task, 50.0, now=150.0)
        self.assertEqual((game_language.MESSAGE, False), task.warnings[-1])

    def test_text_from_an_earlier_run_does_not_count(self):
        game_language.note_text("街機遊戲", now=100.0)
        task = _Task()
        self.assertEqual("", game_language.warn_after_failure(task, 200.0, now=201.0))
        self.assertEqual([], task.warnings)


class FailedRunHintTest(unittest.TestCase):
    def setUp(self):
        game_language.reset()
        self.addCleanup(game_language.reset)

    def _task(self, result):
        class Task(BaseBD2Task):
            def __init__(self):
                self._action_interval_lock = None  # as BaseBD2Task.__init__ sets
                self.info = {}
                self.warnings = []

            def info_set(self, key, value):
                self.info[key] = value

            def log_warning(self, message, notify=False):
                self.warnings.append(message)

            def run(self):
                home_left_column_hits("我的小屋格魯TALK街機遊戲")
                return result

        return Task()

    def test_failed_run_on_the_traditional_client_says_to_switch(self):
        task = self._task(False)
        self.assertFalse(task.run())
        self.assertEqual([game_language.MESSAGE], task.warnings)

    def test_successful_run_says_nothing(self):
        task = self._task(True)
        self.assertTrue(task.run())
        self.assertEqual([], task.warnings)


if __name__ == "__main__":
    unittest.main()
