"""每日精炼 that finds no 精炼 in the item popup says what it saw.

A player's 问题摘要 (v0.1.17, 2560×1440 windowed, 2026-10-10) had only
「每日精炼：装备详情里没有精炼按钮。」 and the screen after it went back to
主页, so the cause could not be told.
"""

import unittest
from types import SimpleNamespace


def _task(detail, popup_closes=True):
    from src.tasks.GearTasks import DailyRefineTask

    task = object.__new__(DailyRefineTask)
    task.logs, task.diagnostics, task.presses = [], [], []
    task.log_info = lambda message, *_a, **_k: task.logs.append(message)
    task._sleep_after_recognition = lambda: None
    task._click_reference = lambda x, y, **_k: task.presses.append((x, y))
    task._wait_boxes = lambda *_a, **_k: detail
    task._save_flow_diagnostic = task.diagnostics.append
    # After the back press: still in the bag, the popup's buttons gone or not.
    task._wait_for_title = lambda *_a, **_k: True
    task.capture_frame = lambda: None
    task._roi_boxes = lambda *_a, **_k: [] if popup_closes else detail
    return task


POPUP = [SimpleNamespace(name="分解", x=1200, y=720, width=60, height=30)]


class NoRefineButtonTest(unittest.TestCase):
    def test_the_popup_text_and_screen_are_kept(self):
        task = _task(POPUP)
        self.assertEqual("no_button", task._refine_cell(0, 1))
        self.assertIn("第1行第2列", task.logs[-1])
        self.assertIn("读到「分解」", task.logs[-1])
        self.assertEqual(["daily_refine_no_refine_button"], task.diagnostics)

    def test_nothing_read_says_so(self):
        task = _task([])
        self.assertEqual("no_button", task._refine_cell(2, 0))
        self.assertIn("读到「没读到字」", task.logs[-1])

    def test_the_popup_is_closed_with_one_back_press(self):
        from src.tasks.claim_page import BACK_BUTTON_POINT
        from src.tasks.GearTasks import GRID_COLUMNS, GRID_ROWS

        task = _task(POPUP)
        task._refine_cell(0, 1)
        self.assertEqual([(GRID_COLUMNS[1], GRID_ROWS[0]), BACK_BUTTON_POINT], task.presses)

    def test_a_popup_still_open_stops_there(self):
        task = _task(POPUP, popup_closes=False)
        self.assertEqual("failed", task._refine_cell(0, 1))

    def test_leaving_the_bag_stops_there(self):
        task = _task(POPUP)
        task._wait_for_title = lambda *_a, **_k: False
        self.assertEqual("failed", task._refine_cell(0, 1))


class NextItemTest(unittest.TestCase):
    """An item without 精炼 no longer ends the daily refine: the next one is
    tried, as for an item already at the cap."""

    def _run(self, outcomes, cells):
        task = _task([])
        task.name = "每日精炼一次"
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_warning = lambda *_a, **_k: None
        task._open_equipment_bag = lambda: True
        task._restore_bag_detail_view = lambda: None
        task._leave_to_home = lambda *_a: True
        task.tried = []
        results = iter(outcomes)
        task._refine_cell = lambda row, column: task.tried.append((row, column)) or next(results)
        task._wait_for_grid_cells = lambda: cells
        return task, task.run_claim()

    def test_the_next_item_is_refined(self):
        task, done = self._run(["no_button", "refined"], [(0, 1, 12), (0, 2, 15)])
        self.assertTrue(done)
        self.assertEqual([(0, 1), (0, 2)], task.tried)

    def test_no_item_with_refine_fails_after_three(self):
        cells = [(0, 1, 12), (0, 2, 15), (0, 3, 16), (0, 4, 17)]
        task, done = self._run(["no_button"] * 3, cells)
        self.assertFalse(done)
        self.assertEqual(3, len(task.tried))
        self.assertEqual("每日精炼一次：精炼失败。", task.info["状态"])


class FailureReasonTest(unittest.TestCase):
    """The same summary said it stopped at 「背包：返回主页」, the step that
    went home after the failure, though going home had worked."""

    def _run(self, detail):
        from src.tasks import problem_report

        task = _task(detail)
        task.name = "每日精炼一次"
        task.info, task.warnings = {}, []
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.info_snapshot = lambda: dict(task.info)
        task.log_warning = lambda message, *_a, **_k: task.warnings.append(message)
        task._open_equipment_bag = lambda: True
        task._wait_for_grid_cells = lambda: [(0, 1, 12)]
        task._restore_bag_detail_view = lambda: None

        def leave(label, _keywords):
            task.info_set("当前阶段", f"{label}：返回主页")
            return True

        task._leave_to_home = leave
        self.assertFalse(task.run_claim())
        return task, problem_report._stage(task)

    def test_the_summary_names_the_missing_button(self):
        task, stage = self._run(POPUP)
        reason = "精炼失败：第1行第2列的装备详情里没有精炼按钮（按钮处读到「分解」）"
        self.assertEqual(reason, stage)
        self.assertEqual(f"每日精炼一次：{reason}。", task.info["状态"])
        self.assertEqual([f"每日精炼一次：{reason}。"], task.warnings)

    def test_a_failure_without_a_reason_still_says_refine_failed(self):
        task, stage = self._run([])
        task._why = ""
        task._refine_fail("精炼")
        self.assertEqual("精炼失败", task.info["当前阶段"])
        self.assertEqual("每日精炼一次：精炼失败。", task.info["状态"])


if __name__ == "__main__":
    unittest.main()
