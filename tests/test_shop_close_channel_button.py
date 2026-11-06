"""The shop close control's fixed-place fallback (82, 36) is never pressed
once the menu is closed: on the field that spot is the channel button
「Ch.<n>」 and opens 选择频道 (4K 桌面分身 probe 2026-11-06)."""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks import recovery
from src.tasks.map_trade.navigator import Navigator


def _navigator(top_left_text):
    navigator = object.__new__(Navigator)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    clicks = []
    miss = SimpleNamespace(score=0.0, pixel_score=0.0, zncc_score=0.0, center=(0, 0))
    navigator.vision = SimpleNamespace(
        capture=lambda: frame,
        match=lambda *_a, **_k: miss,
        passes=lambda *_a, **_k: False,
        click_client=lambda *a, **k: clicks.append(("template", a)),
        click_reference=lambda *a, **k: clicks.append(("fixed", a)),
        ocr_boxes=lambda *_a, **_k: (
            [SimpleNamespace(name=top_left_text, x=70, y=38, width=180, height=33)]
            if top_left_text
            else []
        ),
    )
    navigator.task = SimpleNamespace(sleep=lambda *_a: None, info_set=lambda *a: None)
    navigator._status = lambda *a: None
    return navigator, clicks


class ShopCloseFixedPlaceTest(unittest.TestCase):
    def test_channel_button_read_skips_the_fixed_place(self):
        navigator, clicks = _navigator("Ch.137")
        navigator._click_shop_close_control(after_sleep=0.0)
        self.assertEqual([], clicks)

    def test_menu_still_open_presses_the_fixed_place(self):
        navigator, clicks = _navigator(None)
        navigator._click_shop_close_control(after_sleep=0.0)
        self.assertEqual(["fixed"], [kind for kind, _ in clicks])


if __name__ == "__main__":
    unittest.main()
