"""YES-BD2 #82 (v0.3.12, 繁中 1080p 125%): 角色卡3 上流社会派对会场 ended
「箱庭大地图选择传送阵后未确认目的地按钮」 and the card was skipped.

Reproduced on Leo's 2K 桌面分身 2026-11-12 (12 presses of 12, frames on
diag/issue82-cp3-1112): from beside 艾琳 the walk to the circle is over
2.1-2.9 s after the press, the area map closed at 0.2-0.5 s.  The press is
first looked at 3.2 s later; only 「已完成自动移动」 and the circle's hand
are left, and since v0.3.11 only 「移动中」 counted as the walk.  The map
closing by itself plus one more sign (the game's 已完成, the circle's hand,
a panning field) is the walk."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.tasks.map_trade.navigator import Navigator

MODULE = "src.tasks.map_trade.navigator_sandbox"


def _field(shade):
    return np.full((1080, 1920, 3), shade, np.uint8)


class UnreadWalkAfterCirclePressTest(unittest.TestCase):
    def _press(self, frames, walk_texts, *, map_open=False, hand=False):
        frames = iter(frames)
        texts = iter(walk_texts)
        last = {"frame": _field(100)}

        def capture():
            last["frame"] = next(frames, last["frame"])
            return last["frame"]

        vision = SimpleNamespace(
            capture=capture,
            match=lambda *_a, **_k: "hand",
            passes=lambda *_a, **_k: hand,
        )
        navigator = Navigator(SimpleNamespace(sleep=lambda *_a: None, log_info=lambda *_a: None), vision)
        navigator._status = lambda *_a: None
        navigator._log_info = lambda *_a: None
        navigator._walk_text = lambda _frame: next(texts, "")
        navigator._sandbox_navigation_page_has_keyword = lambda _frame: map_open
        navigator._loading_black = lambda _frame: False
        navigator._click_sandbox_navigation_menu_teleport = lambda _frame: False
        navigator._click_sandbox_navigation_destination_confirmation = lambda _frame: False
        with patch(f"{MODULE}.SANDBOX_NAVIGATION_CONFIRM_TIMEOUT", 0.3):
            return navigator._follow_teleport_icon_press()

    def test_a_short_walk_already_over_counts(self):
        self.assertEqual((True, False), self._press([], ["已完成自动移动"]))

    def test_the_circles_hand_on_a_closed_map_counts(self):
        self.assertEqual((True, False), self._press([], [""], hand=True))

    def test_a_panning_field_counts_without_the_banner(self):
        frames = [_field(40), _field(120), _field(200), _field(40)]
        self.assertEqual((True, False), self._press(frames, [""] * 4))

    def test_a_still_field_with_no_sign_is_no_walk(self):
        self.assertEqual((False, False), self._press([_field(90)] * 3, [""] * 50))

    def test_a_banner_cut_to_the_dialog_title_still_counts(self):
        # 「自动移动中」 read without 中 looks like the 自动移动 question.
        self.assertEqual((True, False), self._press([], ["自动移动"], hand=True))

    def test_nothing_counts_while_the_map_is_still_open(self):
        frames = [_field(40), _field(120), _field(200), _field(40)]
        self.assertEqual(
            (False, False),
            self._press(frames, ["已完成自动移动"] * 50, map_open=True, hand=True),
        )


if __name__ == "__main__":
    unittest.main()
