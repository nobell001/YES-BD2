"""The shared "a/b" count rules (src/utils/ocr_count.py), on every misread
seen in runs and on the 95 real count boxes (tests/fixtures/hud_counts)."""

import unittest

import numpy as np

from src.utils import ocr_count
from src.utils.ocr_count import CountRead, count_values, parse_count, read_count


class CleanReadTest(unittest.TestCase):
    def test_a_count_with_its_slash(self):
        self.assertEqual((7, 70), parse_count("7/70"))
        self.assertEqual((21, 21), parse_count("21/21"))
        self.assertEqual((0, 75), parse_count("0/75", limit=75))
        self.assertEqual((3, 5), parse_count("3 / 5"))
        self.assertEqual((10, 10), parse_count("次数 10:10"))
        self.assertEqual((7, 21), parse_count("7／21"))

    def test_a_count_the_game_cannot_show_is_no_read(self):
        self.assertIsNone(parse_count("11/10"))
        self.assertIsNone(parse_count("80/75", limit=75))
        # A leading zero: the slash read twice ("0/75" as "07/75").
        self.assertIsNone(parse_count("07/75", limit=75))
        self.assertIsNone(parse_count("0/0"))

    def test_a_clean_read_keeps_its_own_limit(self):
        """A limit that changed today (an update) is read as it is; the
        collector decides what a new limit means."""
        self.assertEqual((3, 19), parse_count("3/19", limit=21))

    def test_a_letter_glued_to_the_count_may_be_a_lost_digit(self):
        # Two real boxes read 0/21 as "V21" (1080p, 2026-10-28).
        self.assertIsNone(parse_count("V21", limit=21))
        self.assertIsNone(parse_count("L0/75", limit=75))
        self.assertIsNone(parse_count("/21", limit=21))

    def test_a_stray_mark_beside_the_count_is_not_part_of_it(self):
        # Real boxes: 「0/21 A」, 「0/70 Y」, 「21/21 7」.
        self.assertEqual((0, 21), parse_count("0/21 A", limit=21))
        self.assertEqual((0, 70), parse_count("0/70 Y", limit=70))

    def test_two_counts_in_one_read_are_no_read(self):
        self.assertIsNone(parse_count("0/21 1/21", limit=21))

    def test_a_limit_cut_short_of_the_one_seen_on_screen_is_no_read(self):
        """Its last digits lost, a count looks full ("2/2" for 2/21): audit
        2026-10-28, a full read may end the day's 跑图."""
        for text, seen in (("2/2", 21), ("7/7", 75), ("8/8", 80), ("1/1", 19)):
            with self.subTest(text=text, seen=seen):
                self.assertIsNone(parse_count(text, limit=seen, seen_limit=seen))
        self.assertEqual((21, 21), parse_count("21/21", limit=21, seen_limit=21))
        self.assertEqual((7, 7), parse_count("7/7", limit=7, seen_limit=7))  # a player's 召集
        self.assertEqual((3, 19), parse_count("3/19", limit=21, seen_limit=21))

    def test_only_a_limit_seen_on_screen_cuts_a_read_short(self):
        """The code's usual limit (21) is not the player's: 召集 7, 吸收 17."""
        self.assertEqual((7, 7), parse_count("7/7", limit=21))
        self.assertEqual((2, 2), parse_count("2/2", limit=21))


class SlashReadAsDigitTest(unittest.TestCase):
    def test_every_slashless_misread_seen_splits_before_the_limit(self):
        cases = {
            ("7170", 70): (7, 70),  # 压制 live 2026-09-28
            ("11775", 75): (11, 75),  # 压制 live 4K 2026-10-14
            ("7175", 75): (7, 75),  # 压制 live 2K 2026-10-15
            ("0775", 75): (0, 75),  # real boxes 2026-10-28
            ("0175", 75): (0, 75),
            ("14775", 75): (14, 75),
            ("14175", 75): (14, 75),
            ("11780", 80): (11, 80),
            ("7121", 21): (7, 21),
            ("177", 7): (1, 7),
            ("12170", 70): (12, 70),
            ("11121", 21): (11, 21),
        }
        for (text, limit), count in cases.items():
            with self.subTest(text=text):
                self.assertEqual(count, parse_count(text, limit=limit))

    def test_without_the_limit_on_screen_nothing_is_split(self):
        self.assertIsNone(parse_count("7170"))
        self.assertIsNone(parse_count("11775"))

    def test_a_read_that_does_not_end_in_the_limit_is_no_read(self):
        self.assertIsNone(parse_count("9999", limit=70))
        self.assertIsNone(parse_count("0715", limit=75))  # 0/75 at 3x, v5
        self.assertIsNone(parse_count("70", limit=70))

    def test_a_slash_that_is_not_there_is_not_assumed(self):
        """Two real 0/21 boxes read "121" at 2x (2026-10-28): the 0 lost and
        the slash read as 1.  Taking the slash as lost made them 1/21."""
        self.assertIsNone(parse_count("121", limit=21))
        self.assertIsNone(parse_count("17", limit=7))
        self.assertIsNone(parse_count("77", limit=7))

    def test_a_read_is_one_value_or_none(self):
        for text in ("7175", "1121", "2121", "11775", "0775", "177", "121"):
            for limit in (7, 17, 21, 70, 75, 80):
                with self.subTest(text=text, limit=limit):
                    self.assertLessEqual(len(count_values(text, limit=limit)), 1)


class ReadAgainTest(unittest.TestCase):
    def test_the_next_look_is_taken_only_when_a_read_is_no_count(self):
        taken = []

        def look(text):
            return lambda: taken.append(text) or text

        result = read_count([look("121"), look("0/21"), look("9/21")], limit=21)
        self.assertEqual((0, 21), result.value)
        self.assertEqual(("121", "0/21"), result.texts)
        self.assertEqual(["121", "0/21"], taken)

    def test_a_read_cut_short_takes_the_next_look(self):
        result = read_count([lambda: "2/2", lambda: "2/21"], limit=21, seen_limit=21)
        self.assertEqual((2, 21), result.value)
        self.assertEqual(("2/2", "2/21"), result.texts)

    def test_no_look_reads_a_count(self):
        result = read_count([lambda: "", lambda: "V21"], limit=21)
        self.assertFalse(result)
        self.assertEqual("读到「V21」，看不出是多少", result.why())
        self.assertEqual("没读到数字", CountRead(None, ("", " ")).why())

    def test_the_looks_start_at_3x_then_add_a_border(self):
        self.assertEqual(
            [(3.0, False), (3.0, True)],
            [(look.scale, look.bordered) for look in ocr_count.LOOKS],
        )


class BorderedTest(unittest.TestCase):
    def test_the_box_sits_inside_a_border_of_its_own_colour(self):
        box = np.full((33, 66, 3), 40, dtype=np.uint8)
        box[10:20, 10:30] = 230
        framed, border = ocr_count.bordered(box)
        self.assertEqual(16, border)
        self.assertEqual((33 + 32, 66 + 32, 3), framed.shape)
        self.assertTrue((framed[:border] == 40).all())
        self.assertTrue((framed[border : border + 33, border : border + 66] == box).all())

    def test_a_small_box_gets_at_least_12_px(self):
        _framed, border = ocr_count.bordered(np.zeros((10, 20), dtype=np.uint8))
        self.assertEqual(12, border)


if __name__ == "__main__":
    unittest.main()
