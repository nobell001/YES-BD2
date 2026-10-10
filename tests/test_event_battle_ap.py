"""活动每日战斗 went into the stage page and straight back out (2026-10-10).

A B站 player's v0.1.18 问题摘要 (1920x1080 windowed on a 2560x1440 screen at
150%) stopped at 「普通战斗失败：关卡页上方的活动AP没读到」.  Its frames show the
loading screen 3 s before and the stage page only 1 s before: the AP was
read twice while the top bar was still drawing, both reads were empty, and
two equal reads counted as settled.  The stop frame itself reads 5/5.

Leo's frames of the same event (普通战斗10 cleared, 11 open) gave the other
cases here: a cleared stage shows no 自动战斗, and scaled to 1080p the AP icon
can read as a 2 in front of the pool ("25/5").  Leo 08:52Z: 「應該雙重保險 還是
可以點開自動戰鬥看看的」; 08:58Z: 「超過上限 一樣點開來打 不要去前面字 大於0 就是點開來
打就對了」 — any AP above 0 opens the dialog, whose MAX decides the count.

The older tests stubbed _stable_stage_state with finished reads, so how the
page was read right after loading was never tested.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2

from src.tasks import EventBattleTask as event_module
from src.tasks.EventBattleTask import EventBattleTask, parse_ap, parse_stage_number
from src.utils.ocr_utils import keyword_match_count

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "event_battle"


def state(stage=11, free_ap=5, auto=True, quick=False):
    return {"stage": stage, "free_ap": free_ap, "bonus_ap": 0, "auto": auto, "quick": quick}


def make_task():
    task = object.__new__(EventBattleTask)
    task.name = "活动每日战斗"
    task.config = {}
    task.info = {}
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    task.lines = []
    task.log_info = lambda message, *a, **k: task.lines.append(message)
    task.log_warning = mock.Mock()
    task.sleep = lambda *_args: None
    task._sleep_after_recognition = lambda: None
    task._battles_done = 0
    task._why = ""
    task.capture_frame = lambda: None
    return task


class ParseApTest(unittest.TestCase):
    def test_a_pool_above_its_top_stays_as_read(self):
        self.assertEqual((25, 0), parse_ap("8,400 25/5"))

    def test_a_dot_for_the_currency_comma(self):
        self.assertEqual((5, 0), parse_ap("5.650 5/5"))
        self.assertEqual((5, 0), parse_ap("5.6505/5"))

    def test_earlier_reads_still_hold(self):
        self.assertEqual((0, 0), parse_ap("8,5000/5"))
        self.assertEqual((5, 0), parse_ap("5,9005/5"))
        self.assertEqual((3, 2), parse_ap("12,3453/5 +2"))
        self.assertEqual((5, 0), parse_ap("8,400 + %5/5"))


class StableReadTest(unittest.TestCase):
    def _task(self, reads):
        task = make_task()
        reads = iter(reads)
        task._stage_state = lambda mode: next(reads)
        return task

    def test_empty_ap_reads_while_the_page_draws_are_not_settled(self):
        # The player's run: two empty AP reads in a row, then the top bar.
        none = state(free_ap=None)
        task = self._task([none, none, state(), state()])
        self.assertEqual(5, task._stable_stage_state("普通战斗")["free_ap"])

    def test_two_agreeing_reads_with_the_ap_still_settle_at_once(self):
        task = self._task([state(), state(), self.fail])
        self.assertEqual(5, task._stable_stage_state("普通战斗")["free_ap"])

    def test_a_page_without_its_buttons_is_not_settled(self):
        # Leo 09:00Z: AP and 自动战斗 are on one page; one late, both late.
        blank = state(auto=False, quick=False)
        task = self._task([blank, blank, state(), state()])
        self.assertTrue(task._stable_stage_state("普通战斗")["auto"])

    def test_a_page_never_drawn_fails_with_its_reason(self):
        task = make_task()
        task._open_mode = lambda mode: "ok"
        task._stable_stage_state = lambda mode: state(free_ap=None, auto=False, quick=False)
        task._auto_battle = lambda *a: self.fail("dialog opened on a page not drawn")
        self.assertEqual("failed", task._run_mode("普通战斗"))
        self.assertIn("没看到「自动战斗」或「快速战斗」", task._why)

    def test_an_ap_never_read_ends_with_the_last_read(self):
        none = state(free_ap=None)
        task = self._task([none] * 50)
        with mock.patch.object(event_module, "AP_READ_SECONDS", 0.0):
            self.assertIsNone(task._stable_stage_state("普通战斗")["free_ap"])


class DoubleCheckTest(unittest.TestCase):
    """AP not read but 自动战斗 shown: the dialog decides (Leo 08:52Z)."""

    def _asked(self, free_ap):
        task = make_task()
        task._open_mode = lambda mode: "ok"
        task._stable_stage_state = lambda mode: state(free_ap=free_ap)
        asked = []
        task._auto_battle = lambda mode, wanted, read: asked.append(wanted) or 0
        result = task._run_mode("普通战斗")
        return result, asked

    def test_unread_ap_opens_the_dialog_for_the_run_budget(self):
        self.assertEqual(("no_ap", [5]), self._asked(None))

    def test_ap_above_its_top_opens_the_dialog(self):
        self.assertEqual(("no_ap", [5]), self._asked(25))

    def test_zero_ap_does_not_open_the_dialog(self):
        self.assertEqual(("no_ap", []), self._asked(0))

    def _dialog_task(self, switch_on=True, costs=(5,)):
        task = make_task()
        task.clicks = []
        task._click_reference = lambda x, y, after_sleep=0: task.clicks.append((x, y))
        task._ensure_free_ap_switch_on = lambda *a: switch_on
        reads = iter(costs)
        task._settled_cost = lambda read: next(reads)
        return task

    def test_switch_on_and_max_within_the_budget_is_played(self):
        task = self._dialog_task()
        self.assertEqual(5, task._set_dialog_count(5, state(free_ap=None)))

    def test_switch_not_on_is_not_played(self):
        task = self._dialog_task(switch_on=False)
        self.assertIsNone(task._set_dialog_count(5, state(free_ap=None)))
        self.assertIn("仅使用免费活动AP", task._why)

    def test_a_read_ap_still_caps_the_count(self):
        task = self._dialog_task(costs=(5, 5))
        self.assertIsNone(task._set_dialog_count(5, state(free_ap=3)))
        self.assertIn("免费AP 3", task._why)

    def test_quick_battle_still_needs_the_ap(self):
        task = make_task()
        task._open_mode = lambda mode: "ok"
        task._stable_stage_state = lambda mode: state(15, free_ap=None, auto=False, quick=True)
        task._open_quick_dialog = lambda: self.fail("quick dialog opened without the AP")
        self.assertEqual("failed", task._run_quick_battle())
        self.assertEqual("挑战战斗关卡页上方的活动AP没读到", task._why)


class CountFromTheDialogTest(unittest.TestCase):
    """Battles are counted from the dialog, never from the top-bar AP.

    Windows OCR read Leo's 5/5 as "8,400 25/5" (the AP icon as a 2, 4K PC
    2026-10-10).  25 before and 0 after once counted 25 battles: the summary
    said 25 and 挑战战斗 lost the rest of the run's 5.
    """

    def _task(self, reads, fought):
        task = make_task()
        task._open_mode = lambda mode: "ok"
        reads = iter(reads)
        task._stable_stage_state = lambda mode: next(reads)
        task._auto_battle = lambda mode, wanted, read: fought
        task._wait_for_stage_page = lambda mode: True
        return task

    def test_a_misread_ap_does_not_add_battles(self):
        before = state(free_ap=parse_ap("8,400 25/5")[0])
        after = state(12, free_ap=parse_ap("8,400 0/5")[0])
        task = self._task([before, after], fought=5)
        self.assertEqual("progressed", task._run_mode("普通战斗"))
        self.assertEqual(5, task._battles_done)

    def test_the_rest_of_the_run_stays_for_the_next_mode(self):
        before = state(free_ap=parse_ap("8,400 23/5")[0])
        after = state(12, free_ap=parse_ap("8,400 0/5")[0])
        task = self._task([before, after, after], fought=3)
        self.assertEqual("no_ap", task._run_mode("普通战斗"))
        self.assertEqual(3, task._battles_done)
        self.assertEqual(2, task._battle_budget())


class NoFreeApLeftTest(unittest.TestCase):
    """MAX 0 in the dialog: today's free AP is gone, which is not a failure.

    Windows can read the top bar's 0/5 as "8,400 20/5" (the AP icon as a 2),
    so the dialog opens after the day's AP is spent (Leo's own run at 16:35
    local, 2026-10-10).  The count read 0 and the run failed with
    「场数对不上（读到 0…）」.
    """

    def _task(self, costs, free_ap=None):
        task = make_task()
        task.clicks = []
        task._click_reference = lambda x, y, after_sleep=0: task.clicks.append((x, y))
        task._ensure_free_ap_switch_on = lambda *a: True
        reads = iter(costs)
        task._settled_cost = lambda read: next(reads)
        task._open_mode = lambda mode: "ok"
        task._stable_stage_state = lambda mode: state(free_ap=free_ap)
        task._dismiss_ap_shortage = lambda: False
        task._wait_for_dialog = lambda: True
        task._start_auto_battle = lambda: self.fail("a battle was started with MAX 0")
        return task

    def test_max_0_twice_is_no_ap_left(self):
        task = self._task([0, 0])
        self.assertEqual(0, task._set_dialog_count(5, state(free_ap=20)))
        self.assertEqual(2, task.clicks.count(event_module.DIALOG_MAX_POINT))
        self.assertEqual("", task._why)

    def test_a_slow_count_gets_a_second_look(self):
        task = self._task([0, 5])
        self.assertEqual(5, task._set_dialog_count(5, state(free_ap=None)))

    def test_the_dialog_is_closed_and_the_mode_ends_as_no_ap(self):
        task = self._task([0, 0], free_ap=parse_ap("8,400 20/5")[0])
        self.assertEqual("no_ap", task._run_mode("普通战斗"))
        self.assertEqual(event_module.DIALOG_CANCEL_POINT, task.clicks[-1])
        self.assertEqual("", task._why)

    def test_the_run_ends_as_done(self):
        task = self._task([0, 0], free_ap=20)
        task._event_fail = lambda stage: self.fail(f"{stage}失败：{task._why}")
        with mock.patch.object(event_module, "recover_to_home", return_value=True):
            self.assertTrue(task.run_claim())
        self.assertEqual("今天的免费活动AP已用完，本次战斗 0 场", task.info["活动战斗结果"])

    def test_quick_battle_max_0_is_no_ap_left(self):
        task = self._task([0, 0])
        task._stable_stage_state = lambda mode: state(15, free_ap=20, auto=False, quick=True)
        task._open_quick_dialog = lambda: True
        task._click_box = lambda box, after_sleep=0: self.fail("快速战斗 started with MAX 0")
        self.assertEqual("no_ap", task._run_quick_battle())
        self.assertEqual(event_module.QUICK_DIALOG_CANCEL_POINT, task.clicks[-1])
        self.assertEqual("", task._why)


def list_boxes(rows):
    """OCR boxes of the stage list in reference coordinates: {text: centre y}."""
    return [
        SimpleNamespace(name=text, x=255.0, y=y - 18, width=50.0, height=36.0)
        for text, y in rows.items()
    ]


# What OCR read in Leo's 普通战斗10 frame (2026-10-10), reference coordinates.
LEO_STAGE10_LIST = {"5": 441, "8": 738, "10": 936, "11🙌": 1036}


class StageListTest(unittest.TestCase):
    def _task(self, rows):
        task = make_task()
        task._reference_boxes = lambda frame, roi, name: list_boxes(rows)
        return task

    def test_a_read_number_is_clicked_where_it_was_read(self):
        self.assertEqual((280, 1036), self._task(LEO_STAGE10_LIST)._stage_list_point(11))

    def test_a_number_not_read_is_placed_between_read_ones(self):
        x, y = self._task(LEO_STAGE10_LIST)._stage_list_point(9)
        self.assertAlmostEqual(837, y, delta=6)

    def test_below_the_list_is_none(self):
        self.assertIsNone(self._task(LEO_STAGE10_LIST)._stage_list_point(12))

    def test_a_misread_number_off_the_line_is_none(self):
        self.assertIsNone(self._task({"5": 441, "3": 738, "10": 936})._stage_list_point(11))

    def test_one_read_number_is_not_enough(self):
        self.assertIsNone(self._task({"8": 738})._stage_list_point(11))


class ClearedStageSelectedTest(unittest.TestCase):
    """普通战斗10 cleared and selected: no 自动战斗, yet 11 is still open."""

    def _task(self, after_click):
        task = make_task()
        task._open_mode = lambda mode: "ok"
        task.panel = 10
        task.clicks = []

        def click(x, y, after_sleep=0):
            task.clicks.append((x, y))
            task.panel = after_click

        task._click_reference = click
        task._panel_stage = lambda mode: task.panel
        task._reference_boxes = lambda frame, roi, name: list_boxes(LEO_STAGE10_LIST)
        task._stable_stage_state = lambda mode: (
            state(10, auto=False, quick=True) if task.panel == 10 else state(task.panel)
        )
        task.press_and_confirm = lambda label, press, confirmed, **k: (press(), confirmed())[1]
        task.fought = []
        task._auto_battle = lambda mode, wanted, read: task.fought.append(read["stage"]) or 0
        return task

    def test_the_next_stage_is_selected_and_played(self):
        task = self._task(after_click=11)
        self.assertEqual("no_ap", task._run_mode("普通战斗"))
        self.assertEqual([(280, 1036)], task.clicks)
        self.assertEqual([11], task.fought)

    def test_a_next_stage_that_does_not_open_reads_as_before(self):
        # A locked stage: the click changes nothing, the mode counts as cleared.
        task = self._task(after_click=10)
        self.assertEqual("cleared", task._run_mode("普通战斗"))
        self.assertEqual([], task.fought)

    def test_stage_15_cleared_is_all_cleared_without_a_click(self):
        task = self._task(after_click=16)
        task._stable_stage_state = lambda mode: state(15, auto=False, quick=True)
        self.assertEqual("cleared", task._run_mode("普通战斗"))
        self.assertEqual([], task.clicks)


try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships onnxocr
    ONNXPaddleOcr = None


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class RealFrameTest(unittest.TestCase):
    """The reads on crops of the real frames, at the 1080p scale the ROIs use."""

    @classmethod
    def setUpClass(cls):
        engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True)

        def read(name):
            image = cv2.imread(str(FIXTURES / name))
            lines = engine.ocr(image)[0] or []
            return " ".join(text for _box, (text, score) in lines if score >= 0.2)

        cls.read = staticmethod(read)

    def test_the_players_stop_frame_reads_5_of_5(self):
        self.assertEqual(5, parse_ap(self.read("ap_player_stop_frame.png"))[0])

    def test_the_icon_read_as_2_still_opens_the_dialog(self):
        # Read "25/5" here and "8,4005/5" on another machine's OCR build: either
        # way some AP above 0, which opens the dialog.
        text = self.read("ap_icon_read_as_2.png")
        self.assertIn("5/5", text.replace(" ", ""))
        self.assertGreater(parse_ap(text)[0], 0)

    def _page(self, name):
        return (
            parse_stage_number(self.read(f"{name}_panel.png"), "普通战斗"),
            keyword_match_count(self.read(f"{name}_toggle.png"), ("自动战斗",)) >= 1,
            keyword_match_count(self.read(f"{name}_buttons.png"), ("快速战斗",)) >= 1,
        )

    def test_a_cleared_stage_shows_quick_battle_and_no_auto_battle(self):
        self.assertEqual((10, False, True), self._page("stage10_cleared"))

    def test_the_open_stage_shows_auto_battle(self):
        self.assertEqual((11, True, False), self._page("stage11_open"))


if __name__ == "__main__":
    unittest.main()
