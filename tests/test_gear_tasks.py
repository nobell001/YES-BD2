import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

from src.tasks.GearTasks import badge_cells, plain_refine_box, refine_candidate


def ocr(text, cx, cy, width=30, height=24, confidence=0.99):
    return SimpleNamespace(
        name=text,
        x=cx - width / 2,
        y=cy - height / 2,
        width=width,
        height=height,
        confidence=confidence,
    )


class RefineSelectionTest(unittest.TestCase):
    # OCR centres read from the live equipment grid, 2026-09-26.
    LIVE = [
        ocr("24", 814, 220), ocr("24", 942, 219), ocr("24", 1066, 216),
        ocr("22", 940, 348), ocr("20", 1318, 348), ocr("20", 1570, 349),
        ocr("2", 1283, 502, confidence=0.51),  # stat icon at a cell's foot
        ocr("4", 1033, 628, confidence=0.53),  # stat icon
        ocr("UR", 1318, 164),
    ]

    def test_badges_map_to_cells_and_icon_digits_are_ignored(self):
        cells = badge_cells(self.LIVE)
        self.assertEqual(
            [(0, 0, 24), (0, 1, 24), (0, 2, 24), (1, 1, 22), (1, 4, 20), (1, 6, 20)],
            cells,
        )

    def test_first_badge_below_24_is_chosen(self):
        self.assertEqual((1, 1, 22), refine_candidate(badge_cells(self.LIVE)))

    def test_split_badge_digits_are_joined(self):
        # Live 4K 2026-10-05: one 24 badge OCR'd as "2" and "4".
        cells = badge_cells([ocr("2", 1312, 222, width=14), ocr("4", 1323, 224, width=13)])
        self.assertEqual([(0, 4, 24)], cells)
        self.assertIsNone(refine_candidate(cells))

    def test_two_digit_value_beats_a_lone_digit(self):
        # Leo 2026-10-05: pick one below 24 at once; a lone "2" was really
        # a cut-off 22 or 24, so a two-digit read below 24 comes first.
        cells = [(0, 4, 2), (0, 7, 2), (1, 0, 20), (5, 1, 9)]
        self.assertEqual((1, 0, 20), refine_candidate(cells))
        self.assertEqual((0, 4, 2), refine_candidate([(0, 4, 2), (5, 1, 9)]))

    def test_maxed_or_blank_items_are_never_chosen(self):
        # Items without a badge cannot be refined; 24 is the cap.
        self.assertIsNone(refine_candidate(badge_cells([ocr("24", 814, 220)])))
        self.assertIsNone(refine_candidate([]))

    def test_only_the_single_refine_button_is_clicked(self):
        buttons = [ocr("连续精炼", 1298, 1002), ocr("精炼80", 1610, 1002)]
        self.assertEqual("精炼80", plain_refine_box(buttons).name)
        self.assertIsNone(plain_refine_box([ocr("连续精炼", 1298, 1002)]))
        self.assertIsNone(plain_refine_box([ocr("精炼痕迹8,943", 291, 1000)]))
        self.assertEqual("精炼●80", plain_refine_box([ocr("精炼●80", 1610, 1002)]).name)

    def test_continuous_refine_split_by_ocr_is_never_clicked(self):
        # 连续精炼 read as two boxes: the 精炼 half must not pass.
        split = [ocr("连续", 1270, 1002), ocr("精炼", 1320, 1002)]
        self.assertIsNone(plain_refine_box(split))
        # The real single button further right still passes.
        self.assertEqual(1610, plain_refine_box(split + [ocr("精炼80", 1610, 1002)]).x + 15)


class RefineRetryTest(unittest.TestCase):
    """Live 2026-09-27: "24" read as "4" opened a maxed item and stopped."""

    def _task(self, outcomes):
        from src.tasks.GearTasks import DailyRefineTask

        task = object.__new__(DailyRefineTask)
        task.name = "每日精炼一次"
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.log_warning = lambda *a, **k: None
        task._open_equipment_bag = lambda: True
        task.capture_frame = lambda: None
        task._grid_boxes = lambda frame: []
        task.tried = []
        results = iter(outcomes)
        task._refine_cell = lambda row, column: task.tried.append((row, column)) or next(results)
        task._leave_to_home = lambda *a: True
        return task

    def test_a_maxed_item_is_skipped_for_the_next_one(self):
        from unittest import mock

        task = self._task(["maxed", "refined"])
        # A misread "21" (really 24) is opened, found maxed, then skipped.
        cells = [(0, 1, 21), (0, 6, 18)]
        with mock.patch("src.tasks.GearTasks.badge_cells", return_value=cells):
            self.assertTrue(task.run_claim())
        self.assertEqual([(0, 1), (0, 6)], task.tried)

    def test_unconfirmed_refine_is_a_failure_that_still_goes_home(self):
        # Review: an unconfirmed refine was recorded as the daily refine done.
        from unittest import mock

        task = self._task(["unconfirmed"])
        home = []
        task._leave_to_home = lambda *a: home.append(1) or True
        task._claim_fail = lambda stage: task.tried.append(stage) or False
        with mock.patch("src.tasks.GearTasks.badge_cells", return_value=[(0, 1, 21)]):
            self.assertFalse(task.run_claim())
        self.assertEqual([(0, 1), "确认精炼结果"], task.tried)
        self.assertEqual([1], home)

    def test_all_maxed_fails_but_still_goes_home(self):
        from unittest import mock

        task = self._task(["maxed"] * 3)
        home = []
        task._leave_to_home = lambda *a: home.append(1) or True
        cells = [(0, 1, 4), (0, 2, 5), (0, 3, 6), (0, 4, 7)]
        with mock.patch("src.tasks.GearTasks.badge_cells", return_value=cells):
            self.assertFalse(task.run_claim())
        self.assertEqual(3, len(task.tried))
        self.assertEqual([1], home)


class BagDetailViewTest(unittest.TestCase):
    """Review 2026-09-27: grid offsets need the bag's 查看详情 switch off."""

    def _task(self, states):
        import numpy as np

        from src.tasks.GearTasks import DailyRefineTask

        fixtures = Path(__file__).resolve().parent / "fixtures"
        crops = {
            True: cv2.imread(str(fixtures / "bag_detail_on.png")),
            False: cv2.imread(str(fixtures / "bag_detail_off.png")),
        }
        task = object.__new__(DailyRefineTask)
        task.info_set = lambda *a: None
        task.log_warning = lambda *a, **k: None
        task.clicks = []
        task._click_reference = lambda x, y, after_sleep=0: task.clicks.append((x, y))
        sequence = iter(states)

        def frame():
            image = np.zeros((1080, 1920, 3), np.uint8)
            image[20:66, 800:870] = crops[next(sequence)]
            return image

        task.capture_frame = frame
        task.sleep = lambda *_a: None
        return task

    def test_on_is_switched_off_and_restored(self):
        # Before the switch is judged OFF it is looked at twice (not drawn yet
        # reads OFF); right after a click once.
        task = self._task([True, False, False, False])
        self.assertTrue(task._bag_grid_view())
        task._restore_bag_detail_view()
        self.assertEqual(2, len(task.clicks))  # off, then back on

    def test_off_is_left_alone(self):
        task = self._task([False, False])
        self.assertTrue(task._bag_grid_view())
        task._restore_bag_detail_view()
        self.assertEqual([], task.clicks)


class EquipmentTabTest(unittest.TestCase):
    """Live 2026-09-27: the tab click right after the bag opened was dropped."""

    def _task(self, titles):
        from src.tasks.GearTasks import DailyRefineTask

        task = object.__new__(DailyRefineTask)
        clicks = []
        shown = iter(titles)
        current = ["消耗品"]
        task._open_page_from_home = lambda *a: True
        task.capture_frame = lambda: None
        task._title_visible = lambda _f, keys, _l: current[0] in keys
        task._click_reference = lambda *a, **k: (
            clicks.append(a), current.__setitem__(0, next(shown))
        )
        task._wait_for_title = lambda _l, keys, **_k: current[0] in keys
        return task, clicks

    def test_tab_click_is_repeated_until_the_equipment_title_shows(self):
        task, clicks = self._task(["消耗品", "装备"])
        self.assertTrue(task._open_equipment_bag(grid_view=False))
        self.assertEqual(2, len(clicks))

    def test_gives_up_after_three_dropped_clicks(self):
        task, clicks = self._task(["消耗品"] * 3)
        self.assertFalse(task._open_equipment_bag(grid_view=False))
        self.assertEqual(3, len(clicks))


class RefinePressTest(unittest.TestCase):
    """The single refine press is confirmed, never repeated after a change.

    Leo 2026-10-05: 精炼痕迹 only moves after several refines; the proof is
    the material count in the top bar going down (live 4K: 430,934 ->
    430,904 with a floating -30)."""

    def _task(self, after_click, top="430,934 115"):
        """``after_click(clicks)`` -> (top bar text, page changed) once pressed."""
        from functools import partial
        from unittest import mock

        import numpy as np

        from src.tasks.GearTasks import MISSION_TOAST_ROI, REFINE_TRACE_ROI, DailyRefineTask
        from src.utils.press_confirm import press_and_confirm

        task = object.__new__(DailyRefineTask)
        clock = [0.0]
        patcher = mock.patch(
            "src.tasks.BaseBD2Task._press_and_confirm",
            partial(press_and_confirm, clock=lambda: clock[0]),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.warnings = []
        task.log_warning = lambda message, **k: task.warnings.append(message)
        task._save_flow_diagnostic = lambda *a: None
        task.clicks = []
        task._click_box = lambda *_a, **_k: task.clicks.append(1)
        state = {"top": top, "changed": False}

        def capture():
            if task.clicks:
                state["top"], state["changed"] = after_click(len(task.clicks))
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            if state["changed"]:
                frame[500:600, 800:1000] = 255
            return frame

        task.capture_frame = capture

        def boxes(_frame, roi, _name):
            if roi == REFINE_TRACE_ROI:
                return [SimpleNamespace(name="精炼痕迹8,784")]
            if roi == MISSION_TOAST_ROI:
                return [SimpleNamespace(name=state["top"])]
            return [SimpleNamespace(name="精炼80", x=1600, y=990, width=60, height=30)]

        task._roi_boxes = boxes
        return task

    def test_top_counts_skip_the_floating_cost(self):
        from src.tasks.GearTasks import DailyRefineTask

        self.assertEqual((430904, 115), DailyRefineTask._top_counts("430,904 -30 115"))
        self.assertTrue(DailyRefineTask._counts_spent((430934, 115), (430904, 115)))
        self.assertFalse(DailyRefineTask._counts_spent((430934, 115), (430934, 115)))
        # The gold after the material is cut by the ROI and may read longer.
        self.assertTrue(DailyRefineTask._counts_spent((430934, 116), (430904, 1168)))
        self.assertFalse(DailyRefineTask._counts_spent((430934, 115), ()))
        self.assertFalse(DailyRefineTask._counts_spent((), ()))

    def test_lower_material_count_confirms_the_refine(self):
        task = self._task(lambda _n: ("430,904 -30 115", True))
        self.assertEqual("refined", task._press_refine_once(object()))
        self.assertEqual(1, len(task.clicks))
        self.assertEqual([], task.warnings)

    def test_lost_press_on_an_unchanged_page_is_pressed_once_more(self):
        task = self._task(lambda n: ("430,934 115", False) if n < 2 else ("430,904 115", True))
        self.assertEqual("refined", task._press_refine_once(object()))
        self.assertEqual(2, len(task.clicks))
        self.assertEqual([], task.warnings)

    def test_changed_page_without_proof_is_not_pressed_again(self):
        # Only an animation, no lower count or toast: the press landed, so
        # it stays a warning, and the paid button is not pressed again (a
        # retry of a refine that did land would refine twice).
        task = self._task(lambda _n: ("430,934 115", True))
        self.assertEqual("refined", task._press_refine_once(object()))
        self.assertEqual(1, len(task.clicks))
        self.assertEqual(1, len(task.warnings))

    def test_two_lost_presses_are_not_done(self):
        task = self._task(lambda _n: ("430,934 115", False))
        self.assertEqual("unconfirmed", task._press_refine_once(object()))
        self.assertEqual(2, len(task.clicks))
        self.assertEqual(1, len(task.warnings))

    def test_unreadable_counts_never_get_a_second_press(self):
        # Without the material count nothing proves the press was lost.
        task = self._task(lambda _n: ("", False), top="")
        self.assertEqual("unconfirmed", task._press_refine_once(object()))
        self.assertEqual(1, len(task.clicks))


if __name__ == "__main__":
    unittest.main()
