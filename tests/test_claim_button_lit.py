"""Grey claim buttons are not pressed (Leo 2026-09-29)."""

import unittest
from types import SimpleNamespace

import numpy as np

from src.tasks.claim_page import claim_button_dimmed


def _frame(pill_grey):
    frame = np.zeros((1440, 2560, 3), np.uint8)
    frame[1000:1060, 1800:2040] = pill_grey
    frame[1020:1040, 1850:1990] = 40  # the label
    return frame


BOX = SimpleNamespace(x=1810, y=1005, width=220, height=50)


class ClaimButtonLitTest(unittest.TestCase):
    def test_lit_pill_is_pressed(self):
        # Live 2K: pass 252, mission 213.
        self.assertFalse(claim_button_dimmed(_frame(252), BOX))
        self.assertFalse(claim_button_dimmed(_frame(213), BOX))

    def test_grey_pill_is_skipped(self):
        # Live 2K: pass 127, mission 82.
        self.assertTrue(claim_button_dimmed(_frame(127), BOX))
        self.assertTrue(claim_button_dimmed(_frame(82), BOX))

    def test_a_darker_or_washed_out_screen_reads_the_same(self):
        # A filter or HDR changes the whole screen; lit is still pressed.
        looks = {
            "darker": lambda value: value * 0.75,
            "gamma": lambda value: 255 * (value / 255) ** 1.5,
            "washed out": lambda value: value * 0.7 + 60,
            "hdr": lambda value: value * 0.85 + 15,
        }
        for name, look in looks.items():
            with self.subTest(look=name):
                for lit in (252, 213):
                    self.assertFalse(claim_button_dimmed(_frame(round(look(lit))), BOX))
                for grey in (127, 82):
                    self.assertTrue(claim_button_dimmed(_frame(round(look(grey))), BOX))

    def test_unreadable_box_counts_as_lit(self):
        self.assertFalse(claim_button_dimmed(_frame(127), SimpleNamespace(x=0, y=0, width=2, height=2)))
        self.assertFalse(claim_button_dimmed(None, BOX))


if __name__ == "__main__":
    unittest.main()
