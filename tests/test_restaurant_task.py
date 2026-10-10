import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks import RestaurantTask as restaurant_module
from src.tasks.RestaurantTask import RestaurantStoneTask


def _box(name):
    return SimpleNamespace(name=name, x=1100, y=270, width=100, height=30)


class GoButtonTest(unittest.TestCase):
    """Live 2026-09-28 at 1080p: 立刻前往 was not read exactly."""

    def _task(self, reads):
        clock = [0.0]
        task = object.__new__(RestaurantStoneTask)
        reads = iter(reads)
        task.capture_frame = lambda: None
        task._roi_boxes = lambda *_a: next(reads)
        task.info_set = lambda *_a: None
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        patcher = mock.patch.object(restaurant_module, "monotonic", lambda: clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        return task

    def test_partial_read_still_finds_the_button(self):
        task = self._task([[_box("立到前往")]])
        self.assertEqual("立到前往", task._find_go_button().name)

    def test_button_that_appears_late_is_found(self):
        task = self._task([[], [], [_box("立刻前往")]])
        self.assertIsNotNone(task._find_go_button())

    def test_gives_up_when_nothing_shows(self):
        task = self._task([[]] * 20)
        self.assertIsNone(task._find_go_button())


class RegularsPressTest(unittest.TestCase):
    """常客 counts as nothing to collect only after a second press."""

    def _task(self, toast_after, in_restaurant=True):
        """``toast_after(presses)`` is the toast OCR read after that many presses."""
        task = object.__new__(RestaurantStoneTask)
        task.name = "领取常客圣石"
        task.config = {}
        task.capture_frame = lambda: None
        task.info_set = lambda *_a: None
        task.log_info = lambda *_a, **_k: None
        task.log_warning = lambda *_a, **_k: None
        task.sleep = lambda *_a: None
        task._sleep_after_recognition = lambda: None
        task._wait_for_home_confirmation = lambda *_a, **_k: True
        task._open_business_popup = lambda: True
        task._go_to_restaurant = lambda: True
        task._title_visible = lambda *_a: in_restaurant
        task.presses = []
        task._click_reference = lambda x, y, after_sleep=0: task.presses.append((x, y))
        task._roi_boxes = lambda *_a: [_box(toast_after(len(task.presses)))]
        for target, value in (
            ("STONE_TOAST_WAIT_SECONDS", 0.0),
            ("recover_to_home", lambda _task: True),
        ):
            patcher = mock.patch.object(restaurant_module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return task

    def test_toast_after_the_press_is_a_claim(self):
        task = self._task(lambda presses: "火圣石×30" if presses else "")
        self.assertTrue(task.run_claim())
        self.assertEqual([restaurant_module.REGULARS_POINT], task.presses)

    def test_lost_press_is_pressed_once_more(self):
        task = self._task(lambda presses: "火圣石×30" if presses >= 2 else "")
        self.assertTrue(task.run_claim())
        self.assertEqual(2, len(task.presses))

    def test_no_toast_after_two_presses_is_nothing_to_collect(self):
        task = self._task(lambda _presses: "")
        self.assertTrue(task.run_claim())
        self.assertEqual(2, len(task.presses))

    def test_no_toast_off_the_restaurant_is_not_done(self):
        task = self._task(lambda _presses: "", in_restaurant=False)
        self.assertFalse(task.run_claim())
        self.assertEqual(1, len(task.presses))


if __name__ == "__main__":
    unittest.main()


class BusinessPopupTest(unittest.TestCase):
    """Live 4K 2026-10-10 13:33: after 经营管理 was pressed the run ended on
    the 守山人休息处 hunt screen; the retry check's notice tap is the only
    press in that window."""

    def _task(self, narrow, wide, home):
        clock = [0.0]
        task = object.__new__(RestaurantStoneTask)
        task.capture_frame = lambda: None
        task.info_set = lambda *_a: None
        task.log_info = lambda *_a, **_k: None
        task._sleep_after_recognition = lambda: None
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        task.clicks = []
        task._click_reference = lambda x, y, after_sleep=0: task.clicks.append((x, y))
        task._roi_boxes = lambda _frame, roi, _name: [
            _box(narrow if roi == restaurant_module.BUSINESS_POPUP_ROI else wide)
        ]
        task._home_confirmation_signals = lambda *_a: (home, 0, 0.0, "")
        task._wait_for_home_confirmation = mock.Mock(side_effect=AssertionError("taps"))
        task.diagnostics = []
        task._save_flow_diagnostic = task.diagnostics.append
        patcher = mock.patch.object(restaurant_module, "monotonic", lambda: clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        return task

    def test_popup_read_anywhere_in_its_band_counts(self):
        task = self._task(narrow="", wide="渔笼收获情况 助手工作情况", home=False)
        self.assertTrue(task._open_business_popup())
        self.assertEqual([restaurant_module.BUSINESS_ENTRY_POINT], task.clicks)

    def test_neither_popup_nor_home_stops_without_another_tap(self):
        task = self._task(narrow="", wide="", home=False)
        self.assertFalse(task._open_business_popup())
        self.assertEqual([restaurant_module.BUSINESS_ENTRY_POINT], task.clicks)
        self.assertEqual(["restaurant_business_popup_not_open"], task.diagnostics)

    def test_still_home_presses_again(self):
        task = self._task(narrow="", wide="", home=True)
        self.assertFalse(task._open_business_popup())
        self.assertEqual(restaurant_module.POPUP_CLICK_ATTEMPTS, len(task.clicks))
