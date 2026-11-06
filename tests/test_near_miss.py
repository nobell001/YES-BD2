import unittest

from src.utils import near_miss


class NearMissTest(unittest.TestCase):
    def setUp(self):
        near_miss.reset()
        self.lines = []

    def test_one_word_short_is_logged_with_what_was_read(self):
        # 4K/2K 繁中 2026-11-03: the cartridge bar read 戰門 for 戰鬥 (6/7).
        words = ["最近", "店长游戏卡带", "战斗玩法游戏卡带"]
        text = "最近店长游戏卡带战门游戏卡带"
        self.assertTrue(near_miss.note(self.lines.append, "卡带选择页", words, text, 2, 3))
        self.assertIn("差一点对上", self.lines[0])
        self.assertIn("缺「战斗玩法游戏卡带」", self.lines[0])
        self.assertIn("战门游戏卡带", self.lines[0])

    def test_logged_once_per_missing_word_even_as_numbers_change(self):
        words = ["在战场中查看", "探索", "世界地图"]
        near_miss.note(self.lines.append, "箱庭大地图底部控件", words, "剩下5日 在场域中查看 世界地图", 1, 2)
        near_miss.note(self.lines.append, "箱庭大地图底部控件", words, "剩下4日 在场域中查看 世界地图", 1, 2)
        self.assertEqual(1, len(self.lines))

    def test_nothing_or_far_off_or_enough_is_not_logged(self):
        words = ["甲乙", "丙丁", "戊己", "庚辛"]
        self.assertFalse(near_miss.note(self.lines.append, "x", words, "", 0, 4))
        self.assertFalse(near_miss.note(self.lines.append, "x", words, "甲乙", 1, 4))
        self.assertFalse(near_miss.note(self.lines.append, "x", words, "甲乙丙丁戊己庚辛", 4, 4))
        self.assertEqual([], self.lines)

    def test_a_failing_log_never_breaks_the_check(self):
        def broken(_line):
            raise RuntimeError("log closed")

        self.assertFalse(near_miss.note(broken, "x", ["甲乙", "丙丁"], "甲乙", 1, 2))


if __name__ == "__main__":
    unittest.main()
