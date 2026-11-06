"""跑圖 speed-ups that keep the slow-PC waits (Leo 2026-10-12:
「穩定的前提下 再追求速度」): reads already settled are not repeated."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.tasks.map_trade.action_icons import ActionIconDetection, ActionIconState
from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.collector_constants import ABSORB_ACTION, SkillFeedbackObservation
from src.tasks.map_trade.models import CollectionMapRole, MatchResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_constants import SANDBOX_TEMPLATES
from src.tasks.map_trade.progress import UTC_PLUS_8, ProgressStore

PAGE_READS = (
    "界面分类商店页",
    "界面分类商店标题",
    "界面分类卡带标题",
    "界面分类卡带页",
    "界面分类料理标题",
    "界面分类料理材料",
)


def _navigator(texts, reads, *, sandbox):
    frame = np.full((1080, 1920, 3), 90, dtype=np.uint8)
    failed = MatchResult(-1.0, (0, 0), (0, 0))
    vision = SimpleNamespace(
        capture=lambda: frame,
        match=lambda *_args: failed,
        passes=lambda _result, spec: sandbox[0] and spec in SANDBOX_TEMPLATES,
        threshold_for=lambda spec: spec.threshold,
        template_brightness_ratio=lambda *_args: 0.0,
        ocr_text=lambda _frame, name, **_kwargs: reads.append(name) or texts.get(name, ""),
        ocr_boxes=lambda _frame, name, **_kwargs: reads.append(name) or [],
        simplify=lambda value: value,
    )
    task = SimpleNamespace(config={}, info_set=lambda *_args: None, sleep=lambda *_args: None)
    navigator = Navigator(task, vision)
    navigator._auto_moving = lambda _frame: False
    navigator._detect_map_page_mode = lambda _frame: reads.append("地图页面模式") or SimpleNamespace(
        mode=SimpleNamespace(is_teleport_map=False)
    )
    return navigator


class FieldWaitTest(unittest.TestCase):
    def test_field_wait_skips_page_reads_until_it_fails(self):
        reads = []
        texts = {"界面分类料理标题": "料理", "界面分类料理材料": "所需材料"}
        navigator = _navigator(texts, reads, sandbox=[False])

        result = navigator._wait_for_field_hud(
            timeout=0.05, interval=0.0, success_message="ok", failure_message="超时"
        )

        self.assertFalse(result.success)
        # The failure still names the page that was there.
        self.assertEqual(ScreenState.COOKING, result.state)
        # Every frame read the loading title; the page reads ran once, at the end.
        self.assertGreater(reads.count("界面分类加载"), 2)
        for name in PAGE_READS:
            self.assertEqual(1, reads.count(name), name)
        self.assertFalse(navigator._field_wait_only)
        # Outside the wait, classification is full again.
        self.assertEqual(ScreenState.COOKING, navigator.classify())

    def test_field_found_on_two_frames_without_page_reads(self):
        reads = []
        navigator = _navigator({}, reads, sandbox=[True])

        result = navigator._wait_for_field_hud(
            timeout=3.0, interval=0.0, success_message="ok", failure_message="超时"
        )

        self.assertTrue(result.success)
        self.assertEqual([], [name for name in reads if name in PAGE_READS])

    def test_loading_title_is_still_kept_for_arrival(self):
        reads = []
        navigator = _navigator({"界面分类加载": "卢戈森林深处"}, reads, sandbox=[False])

        navigator._wait_for_field_hud(
            timeout=0.02, interval=0.0, success_message="ok", failure_message="超时"
        )

        self.assertEqual("卢戈森林深处", navigator.last_loading_title)


def _collector(progress, counts):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    task = SimpleNamespace(config={}, sleep=lambda *_args: None, info_set=lambda *_args: None)
    vision = SimpleNamespace(capture=lambda: frame)
    collector = Collector(task, vision, SimpleNamespace(), progress)
    collector._read_count = lambda *_args, **_kwargs: next(counts)
    return collector


def _store(temp_dir):
    progress = ProgressStore(
        Path(temp_dir) / "progress.json",
        lambda: datetime(2026, 8, 11, 12, tzinfo=UTC_PLUS_8),
    )
    progress.load()
    return progress


ICON = MatchResult(0.98, (900, 420), (44, 43), 0.95, 0.92)


class PostPressCountTest(unittest.TestCase):
    def _finish(self, collector, *, feedback, post_state):
        return collector._finish_after_click(
            ABSORB_ACTION,
            card_id="Q_sp1",
            map_role=CollectionMapRole.MAIN_AREA,
            before=(4, 21),
            detection=ActionIconDetection(ActionIconState.AVAILABLE, ICON, 0.95, stable=True),
            post_detection=ActionIconDetection(post_state, ICON, 0.65, stable=True),
            feedback=feedback,
        )

    def test_toast_and_grey_icon_need_one_count_read(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = _store(temp_dir)
            counts = iter([(5, 21)])
            collector = _collector(progress, counts)

            result = self._finish(
                collector,
                feedback=SkillFeedbackObservation("吸收周围的拾取物", "success", 1.0),
                post_state=ActionIconState.USED,
            )

            self.assertTrue(result.completed)
            self.assertEqual((), result.pending_actions)
            self.assertEqual([], list(counts))

    def test_unexpected_first_read_still_reads_the_full_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = _store(temp_dir)
            counts = iter([(8, 21), (5, 21), (5, 21)])
            collector = _collector(progress, counts)

            result = self._finish(
                collector,
                feedback=SkillFeedbackObservation("吸收周围的拾取物", "success", 1.0),
                post_state=ActionIconState.USED,
            )

            self.assertTrue(result.completed)
            self.assertEqual([], list(counts))

    def test_without_toast_two_reads_are_still_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = _store(temp_dir)
            counts = iter([(5, 21), (5, 21), (5, 21)])
            collector = _collector(progress, counts)

            result = self._finish(
                collector,
                feedback=SkillFeedbackObservation("", None, 0.0),
                post_state=ActionIconState.USED,
            )

            self.assertTrue(result.completed)
            self.assertEqual([(5, 21)], list(counts))


class FieldWaitLastLookTest(unittest.TestCase):
    def _navigator(self, states, sleeps):
        frame = np.full((1080, 1920, 3), 90, dtype=np.uint8)
        task = SimpleNamespace(
            config={}, info_set=lambda *_args: None, sleep=lambda seconds: sleeps.append(seconds)
        )
        navigator = Navigator(task, SimpleNamespace(capture=lambda: frame))
        navigator._auto_moving = lambda _frame: False
        navigator.classify = lambda _frame=None: next(states)
        return navigator

    def test_field_on_the_last_frame_gets_one_more_look(self):
        # Q_sp4 凯洛镇 (2K 10-12): the field showed as time ran out.
        states = iter([ScreenState.UNKNOWN, ScreenState.SANDBOX, ScreenState.SANDBOX])
        navigator = self._navigator(states, [])
        clock = iter([0.0, 0.1, 0.2, 5.0, 5.1, 5.2, 5.3])
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", lambda: next(clock)):
            result = navigator._wait_for_field_hud(
                timeout=1.0, interval=0.5, success_message="ok", failure_message="超时"
            )
        self.assertTrue(result.success)

    def test_no_extra_look_without_the_field(self):
        states = iter([ScreenState.UNKNOWN] * 5)
        navigator = self._navigator(states, [])
        clock = iter([0.0, 0.1, 0.2, 5.0, 5.1, 5.2])
        with patch("src.tasks.map_trade.navigator_sandbox.monotonic", lambda: next(clock)):
            result = navigator._wait_for_field_hud(
                timeout=1.0, interval=0.5, success_message="ok", failure_message="超时"
            )
        self.assertFalse(result.success)

    def test_second_field_frame_is_taken_without_waiting(self):
        sleeps = []
        states = iter([ScreenState.SANDBOX, ScreenState.SANDBOX])
        navigator = self._navigator(states, sleeps)
        result = navigator._wait_for_field_hud(
            timeout=3.0, interval=0.5, success_message="ok", failure_message="超时"
        )
        self.assertTrue(result.success)
        self.assertEqual([], sleeps)


class AbsorbCountReuseTest(unittest.TestCase):
    def test_press_starts_from_the_count_read_on_arrival(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = _store(temp_dir)
            counts = iter([(4, 21), (4, 21)])
            collector = _collector(progress, counts)
            collector._open_skill_menu = lambda *_args, **_kwargs: True

            self.assertIsNone(
                collector._absorb_used_up(card_id="Q_sp1", map_role=CollectionMapRole.MAIN_AREA)
            )
            detection = ActionIconDetection(ActionIconState.AVAILABLE, ICON, 0.95, stable=True)
            before, failure = collector._prepare_before_click(
                ABSORB_ACTION, detection, card_id="Q_sp1", map_role=CollectionMapRole.MAIN_AREA
            )

            self.assertIsNone(failure)
            self.assertEqual((4, 21), before)
            self.assertEqual([], list(counts))
            # Used once: a second press reads the count again.
            self.assertIsNone(collector._map_absorb_count)

    def test_unsteady_arrival_read_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = _store(temp_dir)
            counts = iter([(4, 21), (7, 21), (9, 21), (4, 21), (4, 21)])
            collector = _collector(progress, counts)
            collector._open_skill_menu = lambda *_args, **_kwargs: True

            collector._absorb_used_up(card_id="Q_sp1", map_role=CollectionMapRole.MAIN_AREA)
            detection = ActionIconDetection(ActionIconState.AVAILABLE, ICON, 0.95, stable=True)
            before, _failure = collector._prepare_before_click(
                ABSORB_ACTION, detection, card_id="Q_sp1", map_role=CollectionMapRole.MAIN_AREA
            )

            self.assertEqual((4, 21), before)
            self.assertEqual([], list(counts))


if __name__ == "__main__":
    unittest.main()
