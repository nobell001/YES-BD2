"""Quick hunt only spends the free pool (review 2026-09-27)."""

import unittest

from src.tasks.quick_hunt import quick_hunt_cost, quick_hunt_free_pool


class ParseTest(unittest.TestCase):
    def test_cost_and_pool(self):
        self.assertEqual(6, quick_hunt_cost("狩猎●6"))
        self.assertEqual(84, quick_hunt_cost("狩猎 84"))
        self.assertIsNone(quick_hunt_cost("取消"))
        self.assertEqual(90, quick_hunt_free_pool("90/90 +5.6K"))
        self.assertEqual(0, quick_hunt_free_pool("0/60 +2.55K"))
        self.assertIsNone(quick_hunt_free_pool("+5.6K"))


class GuardTest(unittest.TestCase):
    def _task(self, cost_text, pool_text, label="仅使用免费米饭", switch=0.37, after_click=None):
        """``switch`` is the yellow share; each click applies ``after_click``."""
        from unittest import mock

        from src.tasks.QuickHuntTask import QuickHuntTask

        task = object.__new__(QuickHuntTask)
        task.config = {}
        task.warnings, task.clicks = [], []
        task.log_warning = lambda message, **k: task.warnings.append(message)
        task.log_info = lambda *a, **k: None
        task._status_set = lambda *a: None
        task.sleep = lambda *a: None
        task.capture_frame = lambda: None
        reads = {"消耗": cost_text, "免费量": pool_text, "仅使用免费": label}
        task._quick_hunt_ocr_text = lambda frame, roi, name, small_text=False: next(
            value for key, value in reads.items() if name.endswith(key)
        )
        task.switch = switch

        def click(x, y, after_sleep=0):
            task.clicks.append((x, y))
            if after_click is not None:
                task.switch = after_click(task.switch)

        task._quick_hunt_free_switch_ratio = lambda: task.switch
        task._click_reference = click
        settle = mock.patch("src.tasks.quick_hunt.QUICK_HUNT_FREE_SWITCH_SETTLE_SECONDS", 0.0)
        settle.start()
        self.addCleanup(settle.stop)
        return task

    def test_cost_above_the_free_pool_is_refused(self):
        task = self._task("狩猎●84", "10/90 +5.6K")
        self.assertFalse(task._quick_hunt_cost_within_free("冒险航线"))

    def test_cost_within_the_free_pool_passes(self):
        self.assertTrue(self._task("狩猎●84", "84/90 +5.6K")._quick_hunt_cost_within_free("x"))

    def test_unreadable_values_are_refused(self):
        self.assertFalse(self._task("", "84/90")._quick_hunt_cost_within_free("x"))

    def test_switch_off_is_turned_on(self):
        task = self._task("", "", switch=0.0, after_click=lambda _ratio: 0.37)
        self.assertTrue(task._quick_hunt_ensure_free_only("冒险航线"))
        self.assertEqual(1, len(task.clicks))

    def test_missing_switch_label_refuses(self):
        task = self._task("", "", label="将进行5次一般怪物")
        self.assertFalse(task._quick_hunt_ensure_free_only("冒险航线"))
        self.assertEqual([], task.clicks)

    def test_switch_that_never_turns_on_refuses_after_two_clicks(self):
        # Review #28: a second click only when the first changed nothing (an
        # invisible toggle is then back where it started); never a third.
        task = self._task("", "", switch=0.0, after_click=lambda ratio: ratio)
        self.assertFalse(task._quick_hunt_ensure_free_only("冒险航线"))
        self.assertEqual(2, len(task.clicks))

    def test_a_swallowed_click_is_pressed_once_more(self):
        # BUG-20260906-01: the first click did nothing, the second turns it on.
        results = iter((0.0, 0.37))
        task = self._task("", "", switch=0.0, after_click=lambda _ratio: next(results))
        self.assertTrue(task._quick_hunt_ensure_free_only("冒险航线"))
        self.assertEqual(2, len(task.clicks))

    def test_a_click_that_dims_the_switch_is_pressed_back(self):
        # On but too faint to count (0.03): the click turned it off.
        task = self._task("", "", switch=0.03, after_click=lambda r: 0.0 if r else 0.03)
        self.assertFalse(task._quick_hunt_ensure_free_only("冒险航线"))
        self.assertEqual(2, len(task.clicks))
        self.assertEqual(0.03, task.switch)


if __name__ == "__main__":
    unittest.main()


class SmallTextScaleTest(unittest.TestCase):
    """Live 2026-09-28: at native 1080p "84/90" was read as "84"."""

    def test_small_counters_are_enlarged_below_4k(self):
        import numpy as np

        from src.tasks.QuickHuntTask import QuickHuntTask

        scales = []
        task = object.__new__(QuickHuntTask)
        vision = type("V", (), {})()
        vision.ocr_text = lambda frame, name, relative_roi, ocr_scale=1.0: (
            scales.append(ocr_scale) or ""
        )
        task._quick_vision = lambda: vision
        frame_1080 = np.zeros((1080, 1920, 3), np.uint8)
        frame_4k = np.zeros((2160, 3840, 3), np.uint8)
        task._quick_hunt_ocr_text(frame_1080, (0, 0, 1, 1), "x", small_text=True)
        task._quick_hunt_ocr_text(frame_4k, (0, 0, 1, 1), "x", small_text=True)
        task._quick_hunt_ocr_text(frame_1080, (0, 0, 1, 1), "x")
        self.assertEqual([2.0, 1.0, 1.0], scales)
