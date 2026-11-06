"""A greyed picture (HDR, dim filter) must not turn a lit skill icon into a used one.

Library check 2026-11-06: on 26 field frames darkened to 0.65x / 0.8x / a
lifted black level, every lit 吸收/召集/制服 icon was read as used (or
unknown); judged against the picture's whitest they read lit again, and no
dim icon turned lit.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.map_trade.action_icons import (
    ABSORB_ICON,
    SUBDUE_ICON,
    SUMMON_ICON,
    ActionIconDetector,
    ActionIconState,
)
from src.tasks.map_trade.vision import Vision

FRAME = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "field"
    / "bright_4k"
    / "nightmare_battle1_lights_full.jpg"
)


def _detector():
    task = SimpleNamespace(
        config={"跑图跑商识图阈值": 0.72},
        ocr=None,
        sleep=lambda *_a: None,
        info_set=lambda *_a: None,
        log_info=lambda *_a, **_k: None,
        log_debug=lambda *_a, **_k: None,
    )
    return ActionIconDetector(Vision(task))


class GreyPictureIconBrightnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imdecode(np.fromfile(str(FRAME), dtype=np.uint8), cv2.IMREAD_COLOR)
        cls.detector = _detector()

    def _states(self, frame):
        return {
            icon.name: self.detector.detect(frame, icon).state
            for icon in (ABSORB_ICON, SUMMON_ICON, SUBDUE_ICON)
        }

    def test_normal_picture_reads_lit_and_dim_icons(self):
        states = self._states(self.frame)
        self.assertEqual(states["吸收"], ActionIconState.AVAILABLE)
        self.assertEqual(states["召集"], ActionIconState.USED)
        self.assertEqual(states["制服"], ActionIconState.USED)

    def test_greyed_picture_keeps_the_lit_icon_lit(self):
        for name, grey in (
            ("0.65x", (self.frame.astype(np.float32) * 0.65).astype(np.uint8)),
            ("0.8x", (self.frame.astype(np.float32) * 0.8).astype(np.uint8)),
            ("lifted black", (35 + self.frame.astype(np.float32) * 0.6).astype(np.uint8)),
        ):
            with self.subTest(name):
                states = self._states(grey)
                self.assertEqual(states["吸收"], ActionIconState.AVAILABLE)
                self.assertNotEqual(states["召集"], ActionIconState.AVAILABLE)
                self.assertNotEqual(states["制服"], ActionIconState.AVAILABLE)


if __name__ == "__main__":
    unittest.main()
