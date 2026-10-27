"""A long label read with its last character cut still counts (问题摘要 2026-10-27)."""

import unittest
from types import SimpleNamespace

from src.tasks.map_trade.navigator import QUICK_SWITCH_PAGE_KEYWORDS, Navigator
from src.utils.ocr_utils import keyword_read

# The 每周跑图 summary: the quick bar was open (on the frame too), yet the
# check timed out on this read and the run stopped after Q_sp13.
PLAYER_READ = (
    "最近 店长游戏卡 剧情游戏卡 角色游戏卡 战斗玩法游戏卡带 生活玩法游戏卡带 "
    "活动游戏 查看战场奖励 123 2 5 5 国 国 国"
)


class KeywordReadTest(unittest.TestCase):
    def test_cut_last_character(self):
        self.assertTrue(keyword_read("活动游戏卡", "活动游戏查看战场奖励"))
        self.assertTrue(keyword_read("活动游戏卡", "活动游戏卡"))

    def test_short_or_other_words_do_not(self):
        self.assertFalse(keyword_read("最近", "最"))
        self.assertFalse(keyword_read("活动游戏卡", "活动"))
        self.assertFalse(keyword_read("剧情游戏卡", "角色游戏卡"))

    def test_the_open_quick_bar_is_confirmed(self):
        navigator = Navigator.__new__(Navigator)
        navigator.task = SimpleNamespace(info_set=lambda *_args: None)
        navigator.vision = SimpleNamespace(
            simplify=lambda text: text, ocr_text=lambda frame, name, **_kwargs: PLAYER_READ
        )
        matched, _text = navigator._ocr_keywords_in_frame(
            None, QUICK_SWITCH_PAGE_KEYWORDS, "卡带选择页"
        )
        self.assertTrue(matched)


if __name__ == "__main__":
    unittest.main()
