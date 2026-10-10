"""Slow PCs: a cue not seen yet gets 1-2 s more before it counts as absent.

Leo 2026-10-10 09:02-09:04Z, after a B站 player's 活动每日战斗 read its stage
page before the top bar drew: 「然後還有沒有其他有可能像這位用戶一樣 電腦比較慢就會
導致的錯誤」「都可以適當加個1~2秒等看看」「但不要有已經判斷到 又空等的情況」.

Each case is a screen that draws late.  The old code took the first empty
or dim read as final: it skipped and counted the daily as done, or sent an
item to auto-dismantle.  A cue that is read still ends the wait at once.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.tasks.map_trade.models import MatchResult
from src.utils.junk_gear import GearItem
from src.utils.press_confirm import SLOW_PC_GRACE_SECONDS, press_and_confirm


class Clock:
    """A fake monotonic clock that the task's sleep moves forward."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds, *_args, **_kwargs):
        self.sleeps.append(seconds)
        self.now += seconds


def gear(equipped=False, locked=False):
    return GearItem(name="破旧短剑", rarity="R", equipped=equipped, locked=locked, enhanced=False)


class JunkDetailTest(unittest.TestCase):
    """爛装: 穿戴中 or the lock drawn late must not send an item to dismantle."""

    def _task(self, reads):
        from src.tasks.JunkGearTask import JunkGearTask

        task = object.__new__(JunkGearTask)
        task.config = {}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *a, **k: None
        task.log_warning = lambda *a, **k: None
        task.clock = Clock()
        task.sleep = task.clock.sleep
        task._click_reference = lambda *a, **k: None
        task._grid_rarity = lambda frame, cell: None  # unsure on the grid: opened
        task._wait_detail = lambda open_, timeout=0: True
        task.press_and_confirm = lambda label, do, confirmed, **k: do() or True
        reads = iter(reads)
        task.reads = 0

        def read():
            task.reads += 1
            return next(reads), "详情"

        task._read_detail = read
        return task

    def _classify(self, task):
        with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False):
            return task._classify_cells([(0, 0)], {}, np.zeros((1080, 1920, 3)))

    def test_equipped_tag_drawn_late_keeps_the_item(self):
        task = self._task([gear(), gear(equipped=True)])
        self.assertEqual([], self._classify(task))
        self.assertIn("穿戴中", task.info["新装备识别"])

    def test_lock_drawn_late_keeps_the_item(self):
        task = self._task([gear(), gear(locked=True)])
        self.assertEqual([], self._classify(task))

    def test_two_agreeing_reads_are_junk(self):
        task = self._task([gear(), gear()])
        self.assertEqual([(0, 0)], self._classify(task))

    def test_a_kept_item_is_read_once(self):
        task = self._task([gear(equipped=True)])
        self.assertEqual([], self._classify(task))
        self.assertEqual(1, task.reads)
        self.assertEqual([], task.clock.sleeps)


class JunkBadgesTest(unittest.TestCase):
    """爛装: "!" badges drawn late; opening the bag clears them for good."""

    def test_badges_drawn_after_two_looks_are_handled(self):
        import tempfile
        from pathlib import Path

        from src.tasks.JunkGearTask import JunkGearTask

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        pending = mock.patch(
            "src.tasks.JunkGearTask._pending_file",
            return_value=Path(folder.name) / "junk_gear_pending.json",
        )
        pending.start()
        self.addCleanup(pending.stop)
        task = object.__new__(JunkGearTask)
        task.config = {}
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.log_warning = lambda *a, **k: None
        task.sleep = lambda *a: None
        frame = np.zeros((1080, 1920, 3), np.uint8)
        task._colours_distorted = lambda: False
        task._open_equipment_bag = lambda: True
        task._saved_sort = lambda: None
        task._clear_saved_sort = lambda: None
        task._switch_to_newest_first = lambda: "按获得时间从晚到早排序"
        task._restore_sort = lambda _sort: True
        task._restore_bag_detail_view = lambda: None
        task._still_grid_frame = lambda: frame
        task._claim_fail = lambda _stage: False
        task._leave_to_home = lambda *_a: True
        task._pending_cells = lambda _frame: []
        judged = []
        task._classify_cells = lambda cells, _stars, _frame: judged.append(list(cells))
        looks = iter([[], [], [(0, 0)]])
        with (
            mock.patch("src.tasks.JunkGearTask.load_exclusive_stars", return_value={}),
            mock.patch(
                "src.tasks.JunkGearTask.leading_new_cells",
                side_effect=lambda *a: next(looks, [(0, 0)]),
            ),
        ):
            task.run_claim()
        self.assertEqual([[(0, 0)]], judged)


class FreeGachaGraceTest(unittest.TestCase):
    def _task(self):
        from src.tasks.FreeGachaTask import FreeGachaTask

        task = object.__new__(FreeGachaTask)
        task.config = {}
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task.clock = Clock()
        task.sleep = task.clock.sleep
        return task

    def test_a_free_entry_drawn_late_is_still_pulled(self):
        task = self._task()
        looks = iter([(False, "装备抽抽乐 查看概率", True), (True, "所有免费抽抽乐", True)])
        timeouts = []
        task._wait_for_free_gacha = lambda name, timeout=None: timeouts.append(timeout) or next(
            looks
        )
        opened = []
        task._open_confirm_dialog_with_retry = lambda name: opened.append(name) or False
        task._fail_run = lambda stage: False
        self.assertFalse(task._run_free_section("服装抽抽乐", verify_finished=True))
        self.assertEqual(["服装抽抽乐"], opened)
        self.assertEqual([None, SLOW_PC_GRACE_SECONDS], timeouts)

    def test_no_free_entry_after_the_grace_is_still_a_skip(self):
        task = self._task()
        task._wait_for_free_gacha = lambda name, timeout=None: (False, "查看概率", True)
        task._open_confirm_dialog_with_retry = lambda name: self.fail("opened without a free pull")
        self.assertTrue(task._run_free_section("服装抽抽乐", verify_finished=True))

    def test_a_free_entry_read_at_once_has_no_second_look(self):
        task = self._task()
        timeouts = []
        task._wait_for_free_gacha = lambda name, timeout=None: timeouts.append(timeout) or (
            True,
            "所有免费抽抽乐",
            True,
        )
        task._open_confirm_dialog_with_retry = lambda name: False
        task._fail_run = lambda stage: False
        task._run_free_section("服装抽抽乐", verify_finished=True)
        self.assertEqual([None], timeouts)

    def _dialog_task(self, texts, loading=False):
        task = self._task()
        task.capture_frame = lambda: np.zeros((10, 10, 3), dtype=np.uint8)
        task._match = lambda _frame, _spec: MatchResult(-1.0, (0, 0), (0, 0))
        task._passes = lambda _result, _spec: loading
        texts = iter(texts)
        task._ocr_text = lambda _frame, name: next(texts)
        return task

    def test_a_dialog_missed_on_one_frame_is_still_open(self):
        # The skip presses that follow a "closed" dialog would land on it.
        task = self._dialog_task(["", "确认抽抽乐 是否全部进行"])
        self.assertTrue(task._confirm_dialog_still_open("服装抽抽乐"))

    def test_a_dialog_gone_on_two_frames_is_submitted(self):
        task = self._dialog_task(["", ""])
        self.assertFalse(task._confirm_dialog_still_open("服装抽抽乐"))

    def test_loading_is_believed_at_once(self):
        task = self._dialog_task([], loading=True)
        self.assertFalse(task._confirm_dialog_still_open("服装抽抽乐"))
        self.assertEqual([], task.clock.sleeps)


class RefineGraceTest(unittest.TestCase):
    """每日精炼: no badge after 3 s skipped the refine and counted it done."""

    def _wait(self, drawn_at):
        from src.tasks.GearTasks import DailyRefineTask

        task = object.__new__(DailyRefineTask)
        clock = Clock()
        task.sleep = clock.sleep
        task.capture_frame = lambda: None
        task._grid_boxes = lambda frame: []
        cells = [(0, 1, 12)]
        with (
            mock.patch("src.tasks.GearTasks.monotonic", clock),
            mock.patch(
                "src.tasks.GearTasks.badge_cells",
                side_effect=lambda boxes: cells if clock.now >= drawn_at else [],
            ),
        ):
            return task._wait_for_grid_cells(), clock

    def test_badges_drawn_at_4_seconds_are_refined(self):
        cells, _clock = self._wait(drawn_at=4.0)
        self.assertEqual([(0, 1, 12)], cells)

    def test_badges_read_at_once_end_the_wait(self):
        cells, clock = self._wait(drawn_at=0.0)
        self.assertEqual([(0, 1, 12)], cells)
        self.assertEqual([], clock.sleeps)


class ClaimGraceTest(unittest.TestCase):
    """信箱/任务/通行证: a claim button that draws or fades in late."""

    def _task(self, lit_from, shown_from=0.0):
        from src.tasks.claim_page import ClaimButton
        from src.tasks.RewardClaimTasks import MailRewardTask

        clock = Clock()
        game = {"presses": 0}
        box = SimpleNamespace(name="全部领取", x=1500, y=980, width=200, height=50)

        def capture():
            image = np.zeros((1080, 1920, 3), dtype=np.uint8)
            lit = clock.now >= lit_from and game["presses"] == 0
            image[980:1030, 1500:1700] = 252 if lit else 127
            return image

        def press(_target, **_kwargs):
            game["presses"] += 1

        task = object.__new__(MailRewardTask)
        task.claim_log_name = "test"
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_a, **_k: None
        task.sleep = clock.sleep
        task.capture_frame = capture
        task._roi_boxes = lambda *_a: [box] if clock.now >= shown_from else []
        task._click_box = press
        task._sleep_after_recognition = lambda: None
        task._save_flow_diagnostic = lambda *_a: None
        task._settle_after_claim = lambda *_a: True
        task.press_and_confirm = lambda label, do, confirmed, **options: press_and_confirm(
            label, do, confirmed, sleep=task.sleep, log=task.log_info, clock=clock, **options
        )
        button = ClaimButton((1200, 930, 720, 150), ("全部领取",))
        with mock.patch("src.tasks.claim_page.monotonic", clock):
            result = task._claim_all("普通邮箱", button, ("邮箱",))
        return result, game, task

    def test_a_button_still_fading_in_is_claimed(self):
        # Grey on two looks 0.6 s apart, lit on the third.
        result, game, _task = self._task(lit_from=1.0)
        self.assertTrue(result)
        self.assertEqual(1, game["presses"])

    def test_a_button_drawn_at_4_seconds_is_claimed(self):
        result, game, _task = self._task(lit_from=0.0, shown_from=4.0)
        self.assertTrue(result)
        self.assertEqual(1, game["presses"])

    def test_a_button_that_stays_grey_is_nothing_to_claim(self):
        result, game, task = self._task(lit_from=99.0)
        self.assertTrue(result)
        self.assertEqual(0, game["presses"])
        self.assertIn("无可领取", task.info["普通邮箱结果"])


class GuildGraceTest(unittest.TestCase):
    """公会签到: an entry that draws late was taken as "not in a guild"."""

    def test_an_entry_drawn_on_the_fourth_look_is_found(self):
        from src.tasks.DailyTask import DailyTask

        task = object.__new__(DailyTask)
        task.config = {"公会入口阈值": 0.78}
        task.info_set = lambda *a, **k: None
        task.sleep = lambda *a, **k: None
        frames = []
        task.capture_frame = lambda: frames.append(1) or np.zeros((10, 10, 3), dtype=np.uint8)
        task._match = lambda _frame, _spec: (
            MatchResult(0.99, (0, 0), (1, 1), pixel_score=0.99)
            if len(frames) >= 4
            else MatchResult(-1.0, (0, 0), (0, 0))
        )
        found, _frame = task._find_guild_entry()
        self.assertTrue(found)
        self.assertEqual(4, len(frames))


class BusinessGreyTest(unittest.TestCase):
    """一键收菜: 一键获得 still fading in reads grey for about a second."""

    def test_a_button_fading_in_for_1_second_is_pressed(self):
        from src.tasks.DailyTask import DailyTask

        def box(name, ref_x, ref_y):
            # OCR boxes are in client pixels; a 4K client.
            return SimpleNamespace(
                name=name, x=(ref_x - 40) * 2, y=(ref_y - 15) * 2, width=160, height=60
            )

        popup = [
            box("餐馆营业额现状", 700, 300),
            box("助手工作情况", 700, 500),
            box("取消", 832, 814),
            box("一键获得", 1090, 814),
        ]
        clock = Clock()
        first_look = []

        def greyed(_frame, _claim):
            first_look.append(clock.now) if not first_look else None
            return clock.now - first_look[0] < 1.0

        task = object.__new__(DailyTask)
        task.config = {"一键收菜菜单等待秒数": 8.0}
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task.capture_frame = lambda: np.zeros((2160, 3840, 3), dtype=np.uint8)
        task._daily_ocr_boxes = lambda *a, **k: popup
        task._frame_confirms_home = lambda *a, **k: True
        task._wait_for_home_confirmation = lambda *a, **k: True
        task.sleep = clock.sleep
        task._business_claim_greyed = greyed
        task._business_claim_colour = lambda *a: 100
        task._click_reference = lambda x, y, after_sleep=0.0: None
        clicks = []
        task.operate_click = lambda x, y, after_sleep=0.0: clicks.append(
            (round(x * 1920), round(y * 1080))
        )
        with mock.patch("src.tasks.DailyTask.BUSINESS_CLAIM_CONFIRM_SECONDS", 0.0):
            DailyTask.run_business_collect(task)
        self.assertIn((1090, 814), clicks)


if __name__ == "__main__":
    unittest.main()
