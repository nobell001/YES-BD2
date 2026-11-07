import unittest

from src.tasks.EventBattleTask import (
    BANNER_KEYWORDS,
    PROGRESS_PATTERN,
    parse_ap,
    parse_battle_cost,
    parse_stage_number,
)
from src.utils.ocr_utils import normalize_ocr_text


class EventBattleParsingTest(unittest.TestCase):
    def test_parse_ap_reads_free_and_bonus(self):
        self.assertEqual((0, 3), parse_ap("8,500 0/5 |+3"))
        self.assertEqual((5, 0), parse_ap("21:59 10,000 5/5"))
        self.assertEqual((2, 1), parse_ap("8,500 2／5 +1"))

    def test_parse_ap_ignores_numbers_before_the_pool(self):
        # The event currency and clock sit left of the pool in the same ROI.
        self.assertEqual((4, 0), parse_ap("22:01 8,500 4/5"))
        self.assertEqual((None, 0), parse_ap("8,500"))

    def test_parse_battle_cost_accepts_ocr_noise(self):
        self.assertEqual(3, parse_battle_cost("战斗●3"))
        self.assertEqual(1, parse_battle_cost("战斗の1"))
        self.assertEqual(5, parse_battle_cost("战斗 5"))
        self.assertIsNone(parse_battle_cost("取消"))

    def test_parse_stage_number(self):
        self.assertEqual(3, parse_stage_number("挑战战斗3", "挑战战斗"))
        self.assertEqual(15, parse_stage_number("普通战斗 15", "普通战斗"))
        self.assertIsNone(parse_stage_number("普通战斗15", "挑战战斗"))

    def test_progress_pattern_accepts_both_slashes(self):
        # Both forms were read from the same live battle (2026-09-25).
        for raw, expected in (
            ("自动战斗进行中：第1次/共3次", ("1", "3")),
            ("自动战斗进行中：第2次／共3次", ("2", "3")),
            ("自动战斗进行中：第 3 次 ／ 共 3 次", ("3", "3")),
        ):
            match = PROGRESS_PATTERN.search(normalize_ocr_text(raw))
            self.assertIsNotNone(match, raw)
            self.assertEqual(expected, match.groups())


if __name__ == "__main__":
    unittest.main()


class EventBannerKeywordsTest(unittest.TestCase):
    def test_keywords_are_fixed_in_code(self):
        # Leo 2026-10-04: the banner words are not a setting any more.
        for word in ("战斗解锁", "普通战斗", "挑战战斗", "追踪者"):
            self.assertIn(word, BANNER_KEYWORDS)

    def test_tw_client_banners_match(self):
        from src.utils import game_text

        for raw in ("一般戰鬥解鎖", "魔獸追蹤者解鎖"):
            text = game_text.to_tool_text(raw, traditional_client=True)
            self.assertTrue(any(word in text for word in BANNER_KEYWORDS), raw)
