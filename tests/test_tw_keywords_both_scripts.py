"""Every screen word works on both game clients (Leo 2026-11-19: 「你繁中簡中都要
設計好啊」「不只這個 以後新功能 舊功能也都是」).

On the 繁中 client each OCR read goes through src/utils/game_text.to_tool_text
(OpenCC t2s, then the word table assets/game_text/zh_tw.json) before a task
compares it.  A test that hands the 繁中 text straight to a reader skips that
step, which is how 推主线 passed its tests and still missed three 繁中 screens:
the table turns 自动进行 into the battle toggle's 自动战斗, so 「無法自動進行的
探索」 and the list's 「自動進行」 pill came out as 无法自动战斗 / 自动战斗, and
「點擊畫面將回到上一個畫面」 came out as 「点击画面即可返回」.  These tests read
the 繁中 lines the way the live tool does.
"""

import unittest
from types import SimpleNamespace

import numpy as np

from src.tasks import MainStoryTask as story
from src.tasks.main_story import screen
from src.tasks.main_story.screen import Kind
from src.utils import game_text

BLACK = np.zeros((1080, 1920, 3), np.uint8)


def live(name: str, traditional: bool) -> str:
    """What a task sees for one OCR read on the 繁中 / 简中 client."""
    return game_text.to_tool_text(name, traditional)


def box(name, x, y, w=80, h=30, traditional=True):
    return SimpleNamespace(name=live(name, traditional), x=x, y=y, width=w, height=h)


class ToolWordsSurviveTheTableTest(unittest.TestCase):
    """A 简中 keyword holding a shorter word of the 繁中 table is rewritten on
    the 繁中 client (无法自动进行 -> 无法自动战斗) unless the table keeps it with
    a guard.  tools/i18n/build_tw_game_text.py adds the guards; after a new
    keyword run it (``--offline`` keeps the names, no souseha needed)."""

    def test_every_tool_word_reads_back_as_itself(self):
        from tools.i18n.build_tw_game_text import tool_words

        table = game_text.table_words()
        rewritten = {key for key, value in table.items() if key != value}
        broken = []
        for word in sorted(tool_words()):
            if word in rewritten:
                continue  # the 繁中 client words this one differently on purpose
            if word not in game_text.to_cn_words(word):
                broken.append(f"{word} -> {game_text.to_cn_words(word)}")
        self.assertEqual([], broken, "run python tools/i18n/build_tw_game_text.py --offline")


class MainStoryOnBothClientsTest(unittest.TestCase):
    def read(self, *boxes):
        return screen.read(BLACK, list(boxes)).kind

    def test_no_auto_banner(self):
        # Leo's 4K 繁中 recording 11-06 / 简中 live 11-07 (第1章 「使用新鲜食材烹饪」).
        for text, traditional in (("無法自動進行的探索。", True), ("无法自动进行的探索。", False)):
            with self.subTest(text=text):
                self.assertEqual(Kind.MANUAL, self.read(box(text, 850, 240, 300, 28, traditional)))

    def test_list_auto_pill(self):
        for listing, pill, traditional in (
            ("前往當前任務", "自動進行", True),  # Leo's 4K 繁中 recording
            ("前往当前探索", "自动进行", False),  # 简中 live 11-07
        ):
            with self.subTest(pill=pill, traditional=traditional):
                reading = screen.read(
                    BLACK,
                    [box(listing, 200, 1035, 130, traditional=traditional), box(pill, 1680, 1035, 100, traditional=traditional)],
                )
                self.assertEqual(Kind.LIST_AUTO, reading.kind)
                self.assertEqual((1730, 1050), reading.point)

    def test_list_battle_pill(self):
        for listing, pill, traditional in (("前往當前任務", "戰鬥", True), ("前往当前探索", "战斗", False)):
            with self.subTest(pill=pill):
                self.assertEqual(
                    Kind.LIST_BATTLE,
                    self.read(box(listing, 200, 1035, 130, traditional=traditional), box(pill, 1700, 1035, 50, traditional=traditional)),
                )

    def test_reward_popup(self):
        # 繁中: Leo's 4K recording.  简中: the game's common reward line, as
        # 快速狩猎 / 活动战斗 read it (「点击画面即可返回」).
        for line, traditional in (("點擊畫面將回到上一個畫面。", True), ("点击画面即可返回", False)):
            with self.subTest(line=line):
                self.assertEqual(
                    Kind.REWARD,
                    self.read(box("REWARD", 900, 330, traditional=traditional), box(line, 830, 1020, 260, traditional=traditional)),
                )

    def test_skip_dialog_and_quick(self):
        self.assertEqual(Kind.SKIP_DIALOG, self.read(box("跳過對話", 900, 300, 150), box("確認", 1020, 770, 50)))
        self.assertEqual(Kind.SKIP_DIALOG, self.read(box("跳过对话", 900, 300, 150, traditional=False)))
        self.assertEqual(Kind.QUICK, self.read(box("快速進行任務", 1700, 200, 150)))
        self.assertEqual(Kind.QUICK, self.read(box("进行快速探索", 1700, 200, 150, traditional=False)))

    def test_checkout_word_holds_enter(self):
        # OpenCC turns 結帳 into 结帐, not 结账.
        self.assertTrue(story.spend_words_on([box("結帳", 900, 500)]))
        self.assertTrue(story.spend_words_on([box("结账", 900, 500, traditional=False)]))


if __name__ == "__main__":
    unittest.main()
