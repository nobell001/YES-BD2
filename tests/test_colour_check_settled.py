"""The colour check warns only on lasting distortion (10-10 false alarm: the
first frame after the capture started or the window was resized read
钻石154.4；金币109.5；银币152.2, the next ones 钻石2.8；金币0.9；银币5.3)."""

import unittest
from unittest import mock

import numpy as np

from src.utils import colour_check
from src.utils.colour_check import ColourCheck, check_settled

FIRST_FRAME = ColourCheck(152.2, "钻石154.4；金币109.5；银币152.2")
LATER = ColourCheck(2.8, "钻石2.8；金币0.9；银币5.3")
OFF = ColourCheck(40.0, "钻石40.0；金币38.0；银币41.0")


def _frame(width=1920):
    return np.zeros((width * 9 // 16, width, 3), np.uint8)


class SettledTest(unittest.TestCase):
    def setUp(self):
        colour_check.forget_capture()
        self.addCleanup(colour_check.forget_capture)
        self.sleeps = []

    def _check(self, reads, frames=None, first=None):
        reads = list(reads)
        frames = list(frames or [_frame()] * len(reads))
        with mock.patch.object(colour_check, "check_capture_colours", lambda _f: reads.pop(0)):
            return check_settled(
                first if first is not None else frames.pop(0),
                lambda: frames.pop(0),
                self.sleeps.append,
            )

    def test_the_live_false_alarm_is_not_a_warning(self):
        check = self._check([FIRST_FRAME, LATER])
        self.assertFalse(check.distorted)
        self.assertEqual(2.8, check.distance)
        self.assertEqual([colour_check.RECHECK_SECONDS], self.sleeps)

    def test_normal_colours_are_read_once(self):
        check = self._check([LATER])
        self.assertEqual(LATER, check)
        self.assertEqual([], self.sleeps)

    def test_lasting_distortion_still_warns(self):
        # First frame at this size does not count; the next two do.
        check = self._check([OFF, OFF, OFF])
        self.assertTrue(check.distorted)
        self.assertEqual(2, len(self.sleeps))

    def test_two_distorted_reads_at_a_known_size_warn(self):
        self._check([LATER])
        check = self._check([OFF, OFF])
        self.assertTrue(check.distorted)
        self.assertEqual(1, len(self.sleeps))

    def test_one_distorted_read_between_normal_ones_does_not_warn(self):
        self._check([LATER])
        check = self._check([OFF, LATER])
        self.assertFalse(check.distorted)

    def test_a_size_change_starts_over(self):
        self._check([LATER])
        # The first 2K frame does not count, so one more read decides.
        check = self._check([OFF, OFF, LATER], frames=[_frame(2560)] * 3)
        self.assertFalse(check.distorted)
        self.assertEqual(2, len(self.sleeps))

    def test_after_a_capture_restart_the_first_frame_does_not_count(self):
        self._check([LATER])
        colour_check.forget_capture()
        check = self._check([FIRST_FRAME, LATER])
        self.assertFalse(check.distorted)

    def test_off_now_and_then_never_warns(self):
        check = self._check([OFF, OFF, OFF], frames=[_frame(2560), _frame(1920), _frame(2560)])
        self.assertFalse(check.distorted)
        self.assertIn("不算", check.detail)

    def test_leaving_home_ends_the_check_without_a_warning(self):
        check = self._check([OFF, ColourCheck(None, "钻石未找到(0.10)")])
        self.assertFalse(check.distorted)


if __name__ == "__main__":
    unittest.main()
