"""爛装强化分解: a fully enhanced item is never picked (Leo 2026-10-11, real run
on his 4K PC: 「我那件SR右下有標誌 你怎麼去點他」「那件裝備都強化滿了」).

His 顶级英雄盔甲 SR shows its refine level 「15」 in a diamond on the grid and
in the popup.  The grid OCR read nothing there and the popup name has no
「+N」, so the item was taken as +0, opened and picked.  The older tests fed
OCR boxes only and had no frame with a diamond the OCR misses.  Frames: the
real bag and popups of that run, 2026-10-11.
"""

import unittest
from pathlib import Path

import cv2
import numpy as np

from src.tasks.GearTasks import GRID_COLUMNS, GRID_ROWS
from src.tasks.JunkGearTask import JunkGearTask, popup_level_shown
from src.utils.junk_gear import badge_shown

FIXTURES = Path(__file__).parent / "fixtures" / "junk_gear"
GRID_AT = (700, 150)
POPUP_AT = (1300, 580)


def _frame(name, at):
    crop = cv2.imread(str(FIXTURES / name))
    frame = np.zeros((1080, 1920, 3), np.uint8)
    x, y = at
    frame[y : y + crop.shape[0], x : x + crop.shape[1]] = crop
    return frame


def _centre(cell):
    row, column = cell
    return GRID_COLUMNS[column], GRID_ROWS[row]


class GridBadgeTest(unittest.TestCase):
    def test_every_number_on_the_sr_grid_is_seen(self):
        frame = _frame("grid_sr_badges_leo_4k_at_1080.jpg", GRID_AT)
        # Row 1: 14 15 14 18 10 13 +7, then a sword with no number.
        shown = [badge_shown(frame, _centre((0, column))) for column in range(8)]
        self.assertEqual([True] * 7 + [False], shown)
        # Row 2: locked 翼角头盔, 劲弩, 猎人之弓, none with a number.
        self.assertEqual(
            [False, False, False], [badge_shown(frame, _centre((1, c))) for c in range(3)]
        )

    def test_plain_r_items_show_no_number(self):
        frame = _frame("grid_r_no_badges_leo_4k_at_1080.jpg", GRID_AT)
        self.assertFalse(any(badge_shown(frame, _centre((0, c))) for c in range(8)))

    def test_the_15_armour_is_kept_even_when_the_ocr_read_nothing(self):
        frame = _frame("grid_sr_badges_leo_4k_at_1080.jpg", GRID_AT)
        self.assertEqual("已强化", JunkGearTask._older_cell_kept(frame, (0, 1), set()))
        # A new item (「!」) is never enhanced: its badge spot is not read
        # (live 2K 2026-10-22, a new R kept as 已强化).
        self.assertEqual("", JunkGearTask._older_cell_kept(frame, (0, 1), set(), fresh=True))


class WhiteArtIsNotABadgeTest(unittest.TestCase):
    """Leo 2026-10-28 (4K, 一键日常, R filter): his 冰雪红宝石 R ring, never
    enhanced, was kept as 已强化.  The ring's silver band runs through the
    badge spot: 0.035 white, more than the old 0.02 bar and close to a real
    「+7」 (0.044).  His frame has the item popup open, which dims the bag to
    about a quarter (the R labels 59 against 241 undimmed), so the grid is
    brightened back here."""

    def _leo_bag(self):
        frame = cv2.imread(str(FIXTURES / "detail_r_ring_over_bag_leo_4k_at_1080.jpg"))
        return np.clip(frame.astype(float) * 241 / 59, 0, 255).astype(np.uint8)

    def test_the_silver_ring_is_not_enhanced(self):
        frame = self._leo_bag()
        # Row 1: worn 外套, the two rings, worn 手套; none has a number.
        self.assertEqual([False] * 4, [badge_shown(frame, _centre((0, c))) for c in range(4)])

    def test_the_rings_on_the_live_bag(self):
        # The live dry run on Leo's 4K main screen, 2026-10-28 17:17Z (R
        # filter, bag not dimmed): the two rings read 0.063 white, above the
        # first fix's 0.06 「sure」 share, and were still kept as 已强化.
        frame = _frame("grid_r_silver_rings_leo_4k_at_1080.jpg", GRID_AT)
        self.assertEqual([False] * 3, [badge_shown(frame, _centre((0, c))) for c in range(3)])
        self.assertEqual("", JunkGearTask._older_cell_kept(frame, (0, 0), set()))
        self.assertEqual("", JunkGearTask._older_cell_kept(frame, (0, 1), set()))

    def test_every_cell_of_leos_full_bags(self):
        # Leo's 4K bags 2026-10-11, row by row; False = no number on the cell.
        plain = {
            "grid_ur_no_marks_leo_4k_at_1080.jpg": {(1, 2)},
            "grid_new_marked_leo_4k_at_1080.jpg": {(0, c) for c in range(8)}
            | {(1, 0), (4, 0), (4, 1)},
            "grid_one_new_r_after_gacha_leo_4k_at_1080.jpg": {(0, c) for c in range(8)}
            | {(1, 0), (1, 1), (4, 1), (4, 2)},
        }
        for name, without in plain.items():
            frame = _frame(name, (700, 140))
            for row in range(6):
                for column in range(8):
                    with self.subTest(name=name, cell=(row, column)):
                        self.assertEqual(
                            (row, column) not in without,
                            badge_shown(frame, _centre((row, column))),
                        )


class PopupLevelTest(unittest.TestCase):
    def test_the_refine_level_in_the_popup_diamond(self):
        self.assertTrue(popup_level_shown(_frame("popup_level_15_leo_4k_at_1080.png", POPUP_AT)))

    def test_an_empty_diamond_is_plus_0(self):
        self.assertFalse(
            popup_level_shown(_frame("popup_level_empty_leo_4k_at_1080.png", POPUP_AT))
        )


if __name__ == "__main__":
    unittest.main()
