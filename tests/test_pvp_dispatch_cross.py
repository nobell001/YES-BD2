"""镜中之战 with the 派遣 crowd in front of the stage's red ✕ (player via Leo
2026-11-27): 「派遣没领取挡住入口的标志就会不动了」 and 「进去后会自动往右上角跑」.

When the ✕ (PVP_LOC_RESET_TEMPLATE, the 定位修正 press) was not matched, the
old fallback clicked people of the hub by their pictures.  On Leo's crowd frame
the seated man right of the bar matched (0.778/0.930) at 1080p ~(1295, 385),
up and right of the character, far from the stage: the character ran to the
top right.  Now the crowd is sent away and the ✕ looked for again; no hub
person is ever clicked.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2

from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.PVPTask import PVPTask, TEMPLATE_DIR
from src.utils import task_vision
from src.utils.field_followers import (
    FOLLOWERS_ABSENT,
    FOLLOWERS_DISMISSED,
    KEY_PRESSED_BLIND,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CROWD_HUB = FIXTURES / "pvp" / "hub_dispatch_crowd_leo_1080.jpg"
# The ✕ over the stage on that frame (1080p), and the stage under it.
CROSS_BOX = (460, 400, 540, 470)
CHARACTER = (960, 540)


def crowd_hub(cross_hidden: bool):
    frame = cv2.imread(str(CROWD_HUB))
    if cross_hidden:
        # What the crowd's heads and "!" balloons do when they stand in
        # front of it: the ✕ is not seen.
        x0, y0, x1, y1 = CROSS_BOX
        frame[y0:y1, x0:x1] = (60, 20, 40)
    return frame


def pvp_task(frames):
    task = object.__new__(PVPTask)
    task.config = {}
    task.info_set = lambda *_args, **_kwargs: None
    task.log_info = lambda *_args, **_kwargs: None
    task.sleep = lambda *_args, **_kwargs: None
    frames = list(frames)
    task.capture_frame = lambda: frames[0] if len(frames) == 1 else frames.pop(0)
    cache = {}
    task._match = lambda frame, spec: task_vision.match_template(
        frame, spec, {}, TEMPLATE_DIR, cache=cache, min_size=5
    )
    task.clicks = []
    task._click_client = lambda x, y, width, height, after_sleep=0.0: task.clicks.append((x, y))
    task._watch_stage_reset = mock.Mock(return_value="moved")
    task.clear_followers_in_way = mock.Mock(return_value=False)
    return task


class HiddenCrossTest(unittest.TestCase):
    def test_hidden_cross_clicks_nobody(self):
        """Before the fix: the seated man up-right was clicked."""
        task = pvp_task([crowd_hub(cross_hidden=True)])
        with mock.patch("src.tasks.PVPTask.monotonic", side_effect=_clock()):
            self.assertFalse(PVPTask._recover_stage_position(task))
        self.assertEqual([], task.clicks)
        task._watch_stage_reset.assert_not_called()
        task.clear_followers_in_way.assert_called_once_with()

    def test_crowd_sent_away_then_cross_pressed(self):
        task = pvp_task([crowd_hub(cross_hidden=True)])
        # Hidden until the crowd was sent away.
        frames = [crowd_hub(cross_hidden=True), crowd_hub(cross_hidden=False)]
        state = {"cleared": False}

        def clear():
            state["cleared"] = True
            return True

        task.capture_frame = lambda: frames[1] if state["cleared"] else frames[0]
        task.clear_followers_in_way = mock.Mock(side_effect=clear)
        with mock.patch("src.tasks.PVPTask.monotonic", side_effect=_clock()):
            self.assertTrue(PVPTask._recover_stage_position(task))
        task.clear_followers_in_way.assert_called_once_with()
        self.assertEqual(1, len(task.clicks))
        x, y = task.clicks[0]
        # Below the ✕, on the stage: down-left of the character, never up-right.
        self.assertLess(x, CHARACTER[0])
        self.assertGreater(y, CHARACTER[1] - 60)
        self.assertTrue(CROSS_BOX[0] <= x <= CROSS_BOX[2])

    def test_seen_cross_needs_no_crowd_check(self):
        task = pvp_task([crowd_hub(cross_hidden=False)])
        self.assertTrue(PVPTask._recover_stage_position(task))
        task.clear_followers_in_way.assert_not_called()
        self.assertEqual(1, len(task.clicks))

    def test_crowd_that_will_not_go_is_not_looked_for_twice(self):
        task = pvp_task([crowd_hub(cross_hidden=True)])
        task.clear_followers_in_way = mock.Mock(return_value=True)
        with mock.patch("src.tasks.PVPTask.monotonic", side_effect=_clock()):
            self.assertFalse(PVPTask._recover_stage_position(task))
        task.clear_followers_in_way.assert_called_once_with()
        self.assertEqual([], task.clicks)


def _clock(step=0.5):
    now = [0.0]

    def tick():
        now[0] += step
        return now[0]

    return tick


class FollowersInTheWayTest(unittest.TestCase):
    def base_task(self, outcome, frame):
        task = object.__new__(BaseBD2Task)
        task.dismiss_field_followers = mock.Mock(return_value=outcome)
        task.capture_frame = lambda: frame
        task.sleep = mock.Mock()
        task.log_info = mock.Mock()
        task.tap_key = mock.Mock(return_value=True)
        task.note_dispatch = mock.Mock()
        return task

    def test_f_slot_exclamation_is_pressed(self):
        task = self.base_task(FOLLOWERS_DISMISSED, crowd_hub(cross_hidden=False))
        self.assertTrue(BaseBD2Task.clear_followers_in_way(task))
        kwargs = task.dismiss_field_followers.call_args.kwargs
        self.assertTrue(kwargs["even_if_done_today"])
        self.assertTrue(kwargs["use_key"])
        task.tap_key.assert_not_called()

    def test_balloons_without_f_exclamation_get_the_f_key(self):
        task = self.base_task(FOLLOWERS_ABSENT, crowd_hub(cross_hidden=False))
        self.assertTrue(BaseBD2Task.clear_followers_in_way(task))
        task.tap_key.assert_called_once()
        self.assertEqual("F", task.tap_key.call_args.args[0])
        task.note_dispatch.assert_called_once_with(KEY_PRESSED_BLIND)

    def test_no_crowd_presses_nothing(self):
        frame = cv2.imread(str(FIXTURES / "pvp" / "stage_curtain_player_1080.jpg"))
        task = self.base_task(FOLLOWERS_ABSENT, frame)
        self.assertFalse(BaseBD2Task.clear_followers_in_way(task))
        task.tap_key.assert_not_called()


class PortalHandUnderDispatchTest(unittest.TestCase):
    """跑图: the F slot shows the 派遣 "!" instead of the circle's hand."""

    def nav(self, clear_result):
        from src.tasks.map_trade.navigator import Navigator
        from src.utils.vision_models import MatchResult

        state = {"hand": False}

        def clear():
            state["hand"] = clear_result
            return clear_result

        task = SimpleNamespace(
            info_set=lambda *_a: None,
            sleep=lambda *_a: None,
            log_info=lambda *_a: None,
            clear_followers_in_way=mock.Mock(side_effect=clear),
        )
        nav = Navigator(task, SimpleNamespace())
        nav.task = task
        nav._status = lambda *_a: None
        nav.clicks = []
        nav.vision = SimpleNamespace(
            capture=lambda: SimpleNamespace(shape=(1080, 1920, 3)),
            match=lambda *_a: MatchResult(0.99 if state["hand"] else 0.1, (1500, 900), (60, 60), 0.99, 0.99),
            passes=lambda result, _spec: result.score > 0.9,
            click_client=lambda *_a, **_k: (nav.clicks.append(1), state.update(hand=False)),
        )
        return nav, task

    def test_hand_pressed_after_the_crowd_went(self):
        nav, task = self.nav(clear_result=True)
        self.assertTrue(nav._click_sandbox_teleport_interaction(timeout=0.0))
        task.clear_followers_in_way.assert_called_once_with()
        self.assertEqual(1, len(nav.clicks))

    def test_no_crowd_no_second_look(self):
        nav, task = self.nav(clear_result=False)
        self.assertFalse(nav._click_sandbox_teleport_interaction(timeout=0.0))
        task.clear_followers_in_way.assert_called_once_with()
        self.assertEqual([], nav.clicks)


if __name__ == "__main__":
    unittest.main()
