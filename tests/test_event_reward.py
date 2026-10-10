import unittest
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks.EventRewardTask import (
    BADGE_STRIP,
    CURRENCY_ROI,
    DIALOG_ROI,
    DIAMOND_TEMPLATE,
    PANEL_ROI,
    button_lit,
    diamond_icon,
    find_badges,
    list_view,
    views_match,
    parse_token_count,
    red_share,
)


def _frame(width=1920, height=1080, color=(40, 40, 40)):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = color
    return frame


class FindBadgesTest(unittest.TestCase):
    def test_red_square_in_the_strip_is_a_badge(self):
        frame = _frame()
        x = BADGE_STRIP[0] + 8
        frame[400:418, x : x + 18] = (0, 0, 230)  # BGR red, 18 px like the live badge
        self.assertEqual(find_badges(frame), [409])

    def test_scales_with_the_frame(self):
        frame = _frame(3840, 2160)
        x = (BADGE_STRIP[0] + 8) * 2
        frame[800:836, x : x + 36] = (0, 0, 230)
        self.assertEqual(find_badges(frame), [409])

    def test_large_red_art_is_not_a_badge(self):
        frame = _frame()
        frame[300:500, BADGE_STRIP[0] : BADGE_STRIP[0] + 30] = (0, 0, 230)
        self.assertEqual(find_badges(frame), [])


class ButtonLitTest(unittest.TestCase):
    def _box(self):
        return SimpleNamespace(x=100, y=100, width=80, height=30)

    def _page(self, button, look=lambda image: image):
        """A dark page with white text (as every event page has) and the button."""
        frame = _frame()
        frame[20:60, 300:1600] = (255, 255, 255)
        frame[100:130, 100:180] = button
        return look(frame.astype(np.float32)).clip(0, 255).astype(np.uint8)

    def test_white_pill_is_lit_and_grey_is_not(self):
        self.assertTrue(button_lit(self._page((255, 255, 255)), self._box()))
        self.assertFalse(button_lit(self._page((128, 128, 128)), self._box()))

    def test_blue_claim_all_lit_and_dim(self):
        # 全部领取 live 4K 2026-10-04: lit BGR (231,134,107), dim (137,82,63).
        self.assertTrue(button_lit(self._page((231, 134, 107)), self._box()))
        self.assertFalse(button_lit(self._page((137, 82, 63)), self._box()))

    def test_a_darker_or_washed_out_screen_reads_the_same(self):
        # A fixed 185 skipped a lit 全部领取 under a filter darkening by a
        # quarter (lit 173); against the page's own white it stays lit.
        looks = {
            "darker": lambda image: image * 0.75,
            "much darker": lambda image: image * 0.6,
            "gamma": lambda image: 255 * (image / 255) ** 1.5,
            "washed out": lambda image: image * 0.7 + 60,
            "hdr": lambda image: image * 0.85 + 15,
        }
        for name, look in looks.items():
            with self.subTest(look=name):
                self.assertTrue(button_lit(self._page((231, 134, 107), look), self._box()))
                self.assertFalse(button_lit(self._page((137, 82, 63), look), self._box()))
                self.assertFalse(button_lit(self._page((128, 128, 128), look), self._box()))


class RedShareTest(unittest.TestCase):
    def test_red_cost_digits(self):
        frame = _frame()
        frame[10:20, 10:30] = (0, 0, 230)
        self.assertGreater(red_share(frame, (0, 0, 40, 40)), 0.08)
        self.assertEqual(red_share(_frame(), (0, 0, 40, 40)), 0.0)


class DiamondIconTest(unittest.TestCase):
    def test_gem_in_the_currency_bar_is_found(self):
        gem = cv2.imread(str(DIAMOND_TEMPLATE))
        frame = _frame()
        gh, gw = gem.shape[:2]
        frame[41 : 41 + gh, 1461 : 1461 + gw] = gem  # where 满月 shows it
        self.assertTrue(diamond_icon(frame, (CURRENCY_ROI,)))
        self.assertFalse(diamond_icon(frame, (DIALOG_ROI,)))

    def test_plain_frame_has_no_gem(self):
        self.assertFalse(diamond_icon(_frame(), (PANEL_ROI, CURRENCY_ROI, DIALOG_ROI)))


if __name__ == "__main__":
    unittest.main()


class TokenCountTest(unittest.TestCase):
    def test_narrow_ones_read_as_letters(self):
        self.assertEqual(parse_token_count("ll0"), 110)
        self.assertEqual(parse_token_count("I|O"), 110)

    def test_plain_digits_and_nothing(self):
        self.assertEqual(parse_token_count("210"), 210)
        self.assertEqual(parse_token_count("1,000"), 1000)
        self.assertIsNone(parse_token_count(""))


class DiamondRecheckTest(unittest.TestCase):
    """The 钻石 check runs again on the frame of every press."""

    def _task(self, diamond_checks):
        from src.tasks.EventRewardTask import EventRewardTask

        task = object.__new__(EventRewardTask)
        task.capture_frame = lambda: _frame()
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task._reference_boxes = lambda *a: []
        task._diamonds_now = lambda *_a: diamond_checks.pop(0)
        task._click_reference_box = lambda *a, **k: self.fail("pressed on a paid page")
        return task

    def test_paid_page_presses_nothing(self):
        self.assertFalse(self._task([True])._press_what_is_lit("钻石"))


class ListBottomTest(unittest.TestCase):
    def test_same_list_picture_is_the_bottom(self):
        frame = np.random.default_rng(3).integers(0, 255, (1440, 2560, 3), dtype=np.uint8)
        self.assertTrue(views_match(list_view(frame), list_view(frame.copy())))

    def test_moved_list_is_not(self):
        frame = np.random.default_rng(3).integers(0, 255, (1440, 2560, 3), dtype=np.uint8)
        moved = np.roll(frame, 120, axis=0)
        self.assertFalse(views_match(list_view(frame), list_view(moved)))


def _box(name, x, y, w=90, h=30):
    return SimpleNamespace(name=name, x=x, y=y, width=w, height=h)


class PressWhatIsLitTest(unittest.TestCase):
    """Leo 2026-10-08: every event page — press what is lit, 即刻刷新 first."""

    def _task(self, frames, boxes, pressed, confirm=True):
        from src.tasks.EventRewardTask import EventRewardTask

        task = object.__new__(EventRewardTask)
        task.capture_frame = lambda: frames[0]
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task._diamonds_now = lambda *_a: False
        task._reference_boxes = lambda *a: boxes
        task._hand_points = lambda *_a: []

        def press(box, **_k):
            pressed.append(box.name)
            if len(frames) > 1:
                frames.pop(0)

        task._click_reference_box = press
        task._confirm_dialog = lambda *_a: confirm
        task._settle = lambda *_a: None
        return task

    @staticmethod
    def _lit(frame, *boxes):
        frame = frame.copy()
        for box in boxes:
            frame[box.y : box.y + box.height, box.x : box.x + box.width] = 255
        return frame

    def test_refresh_first_then_unlock(self):
        refresh, unlock = _box("即刻刷新", 1290, 760), _box("全部解锁", 1500, 750)
        grey = _frame(color=(128, 128, 128))
        frames = [self._lit(grey, refresh, unlock), self._lit(grey, unlock), grey]
        pressed = []
        self.assertTrue(self._task(frames, [refresh, unlock], pressed)._press_what_is_lit("拼图"))
        self.assertEqual(pressed, ["即刻刷新", "全部解锁"])

    def test_grey_page_presses_nothing(self):
        boxes = [_box("即刻刷新", 1290, 760), _box("全部解锁", 1500, 750), _box("旋转1次", 1100, 740)]
        pressed = []
        self._task([_frame(color=(128, 128, 128))], boxes, pressed)._press_what_is_lit("x")
        self.assertEqual(pressed, [])

    def test_task_line_is_not_a_button(self):
        # A white task row that only mentions a button word is never pressed.
        rows = [_box("转盘旋转1次", 1100, 400, 300), _box("获得拼图用触控笔", 600, 700, 200)]
        frame = self._lit(_frame(), *rows)
        pressed = []
        self._task([frame], rows, pressed)._press_what_is_lit("任务")
        self.assertEqual(pressed, [])

    def test_claim_all_on_the_puzzle_task_page(self):
        claim = _box("全部领取", 1450, 760)
        boxes = [_box("获得拼图用触控笔", 600, 700, 200), _box("活动任务", 600, 740), claim]
        frames = [self._lit(_frame(), claim), _frame()]
        pressed = []
        self._task(frames, boxes, pressed)._press_what_is_lit("活动任务")
        self.assertEqual(pressed, ["全部领取"])

    def test_exchange_without_confirm_stops_exchanging(self):
        exchange = _box("兑换100次", 1300, 720)
        frame = self._lit(_frame(), exchange)
        pressed = []
        self._task([frame], [exchange], pressed, confirm=False)._press_what_is_lit("兑换所")
        self.assertEqual(pressed, ["兑换100次"])

    def test_traditional_ocr_reads_as_the_button(self):
        unlock = _box("全部解鎖", 1500, 750)
        frames = [self._lit(_frame(), unlock), _frame()]
        pressed = []
        self._task(frames, [unlock], pressed)._press_what_is_lit("拼图")
        self.assertEqual(pressed, ["全部解鎖"])


class SecondSweepTest(unittest.TestCase):
    def test_second_pass_closes_and_reopens_the_page(self):
        from src.tasks.EventRewardTask import EventRewardTask

        steps = []
        task = object.__new__(EventRewardTask)
        task.info_set = lambda *a, **k: None
        task._open_page_from_home = lambda *a: steps.append("open") or True
        task._leave_to_home = lambda *a: steps.append("home") or True
        sweeps = iter([1, 0])
        task._sweep_list = lambda _skipped: steps.append("sweep") or next(sweeps)
        self.assertTrue(task.run_claim())
        self.assertEqual(steps, ["open", "sweep", "home", "open", "sweep", "home"])

    def test_nothing_claimed_means_no_second_pass(self):
        from src.tasks.EventRewardTask import EventRewardTask

        steps = []
        task = object.__new__(EventRewardTask)
        task.info_set = lambda *a, **k: None
        task._open_page_from_home = lambda *a: steps.append("open") or True
        task._leave_to_home = lambda *a: steps.append("home") or True
        task._sweep_list = lambda _skipped: steps.append("sweep") or 0
        self.assertTrue(task.run_claim())
        self.assertEqual(steps, ["open", "sweep", "home"])


class LostScrollTest(unittest.TestCase):
    """A scroll the game dropped left the list still, which read as the bottom
    and ended the sweep above the badged events (press audit 10-09)."""

    def _task(self, positions, badge_at, lost_scrolls=(), login_card_at=()):
        from src.tasks.EventRewardTask import EventRewardTask

        base = np.random.default_rng(5).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        state = {"pos": 0, "scrolls": 0, "opened": [], "logs": [], "diagnostics": []}
        task = object.__new__(EventRewardTask)
        task.info_set = lambda *a, **k: None
        task.log_info = lambda message, *a, **k: state["logs"].append(message)
        task.sleep = lambda *_a: None
        task._save_flow_diagnostic = state["diagnostics"].append
        task._list_to_top = lambda: state.__setitem__("pos", 0)
        task.capture_frame = lambda: np.roll(base, 200 * state["pos"], axis=0)
        task._list_text = lambda _frame: (
            f"活动{state['pos']}" + (" 登录活动" if state["pos"] in login_card_at else "")
        )
        task._next_badge = lambda _frame, _skipped: (
            (400, "活动C") if state["pos"] == badge_at and not state["opened"] else None
        )
        task._click_reference = lambda *a, **k: None
        task._handle_page = lambda caption: state["opened"].append(caption) or True

        def scroll(*_a, **_k):
            state["scrolls"] += 1
            if state["scrolls"] not in lost_scrolls:
                state["pos"] = min(positions - 1, state["pos"] + 1)

        task.scroll_client = scroll
        return task, state

    def test_lost_scroll_is_scrolled_again_and_reaches_lower_events(self):
        task, state = self._task(positions=3, badge_at=2, lost_scrolls=(1,))
        self.assertEqual(1, task._sweep_list(set()))
        self.assertEqual(["活动C"], state["opened"])

    def test_bottom_is_a_list_that_stays_still_twice(self):
        task, state = self._task(positions=1, badge_at=None)
        self.assertEqual(0, task._sweep_list(set()))
        # The first scroll, then one more to confirm the bottom.
        self.assertEqual(2, state["scrolls"])

    def test_a_list_that_never_went_down_says_so(self):
        # YES-BD2 #11: the events below the first screen kept their badge and
        # the run said nothing about it.
        task, state = self._task(positions=1, badge_at=None)
        task._sweep_list(set())
        self.assertIn("往下滚两次都没动", "\n".join(state["logs"]))
        # Only a log line: the run goes on, so no give-up frame is kept.
        self.assertEqual([], state["diagnostics"])

    def test_the_login_event_card_does_not_end_the_list(self):
        # Live 10-10: 登录活动 shows on the first two screens, and 登录加成 and
        # two Pickup cards sit below it.  The sweep stopped on its second
        # sighting, so their badges were never looked at.
        task, state = self._task(positions=3, badge_at=2, login_card_at=(0, 1))
        self.assertEqual(1, task._sweep_list(set()))
        self.assertEqual(["活动C"], state["opened"])
        self.assertEqual("活动列表：这轮往下滚动了 2 次，处理 1 个。", state["logs"][-1])

    def test_a_lost_scroll_next_to_the_login_event_is_scrolled_again(self):
        # YES-BD2 #11: the one scroll down was lost, the list still showed
        # 登录活动, and the sweep ended there instead of scrolling again.
        task, state = self._task(positions=3, badge_at=2, lost_scrolls=(1,), login_card_at=(0, 1))
        self.assertEqual(1, task._sweep_list(set()))
        self.assertEqual(["活动C"], state["opened"])

    def test_the_log_says_how_far_the_list_went(self):
        task, state = self._task(positions=3, badge_at=2, lost_scrolls=(1,))
        task._sweep_list(set())
        self.assertEqual("活动列表：这轮往下滚动了 2 次，处理 1 个。", state["logs"][-1])
        self.assertEqual([], state["diagnostics"])


class BadgesLeftTest(unittest.TestCase):
    """YES-BD2 #11: the run ended fine with red dots left on some events, and
    nothing said which.  A fine run's 问题摘要 keeps only its last few lines,
    so the run ends on one line naming each event left and why."""

    def _page_task(self, panel_boxes):
        from src.tasks.EventRewardTask import EventRewardTask

        task = object.__new__(EventRewardTask)
        task.capture_frame = lambda: _frame()
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task.sleep = lambda *_a: None
        task._save_flow_diagnostic = lambda *_a: None
        task._reference_boxes = lambda _frame, roi, _name: panel_boxes if roi == PANEL_ROI else []
        task._hand_points = lambda *_a: []
        task._click_reference_box = lambda *a, **k: self.fail("pressed on a skipped page")
        return task

    def test_an_unknown_page_says_so(self):
        task = self._page_task([_box("每日签到", 700, 300)])
        task._page_skip_why = ""
        clock = iter(range(0, 100))
        with mock.patch("src.tasks.EventRewardTask.monotonic", lambda: next(clock)):
            self.assertFalse(task._handle_page("登录加成"))
        self.assertEqual("页面上没有认得的按钮", task._page_skip_why)

    def test_a_paid_page_says_so(self):
        task = self._page_task([_box("付费钻石兑换所", 700, 300, w=200)])
        task._page_skip_why = ""
        self.assertFalse(task._handle_page("满月兑换所"))
        self.assertEqual("有钻石，不碰", task._page_skip_why)

    def _sweep_task(self, handle):
        from src.tasks.EventRewardTask import EventRewardTask

        task = object.__new__(EventRewardTask)
        state = {"opened": 0}
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a, **k: None
        task.sleep = lambda *_a: None
        task._list_to_top = lambda: None
        task.capture_frame = lambda: _frame()
        task._list_text = lambda _frame: "活动列表"
        task._next_badge = lambda _frame, skipped: (
            None if "拼图活动" in skipped else (400, "拼图活动")
        )
        task._click_reference = lambda *a, **k: None
        task.scroll_client = lambda *a, **k: None

        def handle_page(caption):
            state["opened"] += 1
            return handle(task)

        task._handle_page = handle_page
        return task, state

    def test_the_sweep_keeps_why_each_event_was_left(self):
        def paid(task):
            task._page_skip_why = "有钻石，不碰"
            return False

        task, _state = self._sweep_task(paid)
        skipped = {}
        self.assertEqual(0, task._sweep_list(skipped))
        self.assertEqual({"拼图活动": "有钻石，不碰"}, skipped)

    def test_a_badge_still_there_after_two_claims(self):
        task, state = self._sweep_task(lambda _task: True)
        skipped = {}
        task._sweep_list(skipped)
        self.assertEqual(2, state["opened"])
        self.assertEqual({"拼图活动": "处理两次还在"}, skipped)

    def _run(self, left):
        from src.tasks.EventRewardTask import EventRewardTask

        logs = []
        task = object.__new__(EventRewardTask)
        task.info_set = lambda *a, **k: None
        task.log_info = lambda message, *a, **k: logs.append(message)
        task._open_page_from_home = lambda *a: True
        task._leave_to_home = lambda *a: logs.append("回到主页") or True
        task._sweep_list = lambda skipped: skipped.update(left) or 0
        self.assertTrue(task.run_claim())
        return logs

    def test_the_run_ends_naming_the_events_left(self):
        logs = self._run({"拼图活动": "页面上没有认得的按钮", "满月兑换所": "有钻石，不碰"})
        self.assertEqual(
            "活动：这些还有红点，没领：「拼图活动」页面上没有认得的按钮、「满月兑换所」有钻石，不碰。",
            logs[-1],
        )

    def test_nothing_left_says_nothing(self):
        self.assertEqual(["回到主页"], self._run({}))
