"""Character cards (角色游戏卡) found wherever they sit on the row
(YES-BD2 #41, v0.2.19, 1920x1080 fullscreen, 桌面分身).

The player had pinned (置顶) character cards 2-5, so the row read
2(cut off), 3, 4, 5, 1, 6, 7 ... 11 and was slid left.  v0.2.19 looked for
card n only in its fixed slot (93 + 180 x (n - 1)), found no badge there and
skipped cards 1-5 with 「角标不够确定…领先0.000」.

The fixture is the last game frame of the player's 问题摘要 (1488x837, as the
summary carried it).
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

from src.tasks.map_trade import story_card_art
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision

FRAME = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "quick_switch"
    / "character_tab_pinned_2to5_issue41_1488x837.png"
)
# Badge centre x of each character card on that frame (client pixels).
CARD_X = {3: 119, 4: 258, 5: 398, 1: 537, 6: 677, 7: 816}


def _navigator(frame):
    task = SimpleNamespace(config={}, info_set=lambda *_a: None, ocr=lambda **_k: [])
    navigator = Navigator(task, Vision(task))
    navigator.vision.capture = lambda: frame
    navigator._status = lambda *_a: None
    navigator._badge_category = "character"
    # The digit read only vetoes; keep the test off the OCR model.
    navigator._story_badge_ocr_number = lambda _frame, _result: (None, "")
    return navigator


class PinnedCharacterRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(FRAME), cv2.IMREAD_COLOR)

    def test_each_card_is_found_where_it_sits(self):
        navigator = _navigator(self.frame)
        for number, x in CARD_X.items():
            with self.subTest(card=number):
                detection, reason = navigator._find_story_card(self.frame, number)
                self.assertIsNotNone(detection, reason)
                self.assertEqual(number, detection.best.number)
                self.assertLess(abs(detection.best.result.center[0] - x), 8)

    def test_the_badge_alone_also_finds_them(self):
        # The fallback when the art cannot settle it (a card without a
        # picture yet, or the 游玩中 cover).
        navigator = _navigator(self.frame)
        for number, x in CARD_X.items():
            with self.subTest(card=number):
                detection, reason = navigator._find_character_badge(self.frame, number)
                self.assertIsNotNone(detection, reason)
                self.assertEqual(number, detection.best.number)
                self.assertLess(abs(detection.best.result.center[0] - x), 8)

    def test_a_card_cut_off_at_the_edge_is_left_to_the_bar_scroll(self):
        # Card 2 is the half card at the left edge: not clicked, the bar
        # scroll brings it in.
        navigator = _navigator(self.frame)

        detection, reason = navigator._find_story_card(self.frame, 2)

        self.assertIsNone(detection)
        self.assertIn("不在画面内", reason)

    def test_the_bar_search_takes_card_one_without_scrolling(self):
        # The whole lookup the run uses: card 1 is in view after the pinned
        # cards, so it is taken as it stands.
        navigator = _navigator(self.frame)
        navigator._visible_story_reads = lambda _frame: []
        navigator._wheel_story_bar = lambda *_a, **_k: self.fail("scrolled")

        found = navigator._wait_for_story_badge_with_scroll(1)

        self.assertIsNotNone(found)
        self.assertLess(abs(found[1].best.result.center[0] - CARD_X[1]), 8)

    def test_the_art_of_another_card_never_wins_a_spot(self):
        for number in CARD_X:
            with self.subTest(card=number):
                check = story_card_art.find_card(self.frame, number, "character")
                self.assertTrue(check.ok, check.reason)
                self.assertGreaterEqual(check.target.score - check.other.score, 0.2)

    def test_story_cards_keep_their_own_pictures(self):
        self.assertTrue(story_card_art.has_art(19))
        self.assertFalse(story_card_art.has_art(8, "character"))
        self.assertTrue(story_card_art.has_art(7, "character"))
        self.assertFalse(story_card_art.has_art(1, "event"))


if __name__ == "__main__":
    unittest.main()
