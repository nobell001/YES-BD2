"""跑图 skill bar in the wrong slots: stop once, say which slot (player 2026-10-26)."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2

from src.tasks.map_trade import skill_layout
from src.tasks.map_trade.action_icons import ActionIconDetector
from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.collector_constants import (
    SEARCH_ACTION,
    SkillFeedbackObservation,
)
from src.tasks.map_trade.collector_skills import SkillExecutionMixin
from src.tasks.map_trade.vision import Vision
from src.utils.plain_text import DIAGNOSTIC_PREFIX, plain
from tests.test_map_trade_video_regression import _VideoFixtureTask

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade"
# The player's bar (only the skill bar kept): 1 召集 (under a character),
# 2 吸收, 3 压制, 4 探查.
WRONG = FIXTURES / "skill_bar" / "layout_wrong_player_1080.png"
RIGHT = (
    FIXTURES / "video_fhd" / "story_sandbox_ready.png",
    FIXTURES / "video_fhd" / "story_sandbox_used.png",
)


def frame(path):
    image = cv2.imread(str(path))
    if image.shape[:2] != (1080, 1920):
        image = cv2.resize(image, (1920, 1080))
    return image


def detector():
    return ActionIconDetector(Vision(_VideoFixtureTask()))


class _Host(SkillExecutionMixin):
    def __init__(self, image):
        self.action_icons = detector()
        self.vision = SimpleNamespace(capture=lambda: image)
        self.task = SimpleNamespace(sleep=lambda *_args: None)


class ReadLayoutTest(unittest.TestCase):
    def test_the_players_bar_names_the_wrong_slots(self):
        layout = skill_layout.read_layout(detector(), frame(WRONG))
        self.assertTrue(skill_layout.conclusive(layout))
        wrong = skill_layout.wrong_slots(layout)
        self.assertEqual([(3, "压制", "召集"), (4, "探查", "压制")], wrong)
        text = skill_layout.message(wrong)
        self.assertIn("第3格是压制（要放召集）", text)
        self.assertIn("第4格是探查（要放压制）", text)
        self.assertIn("探查、吸收、召集、压制", text)

    def test_a_right_bar_has_no_wrong_slot(self):
        for path in RIGHT:
            with self.subTest(path.name):
                layout = skill_layout.read_layout(detector(), frame(path))
                self.assertTrue(skill_layout.conclusive(layout))
                self.assertEqual([], skill_layout.wrong_slots(layout))

    def test_no_bar_says_nothing(self):
        layout = skill_layout.read_layout(detector(), frame(WRONG) * 0)
        self.assertFalse(skill_layout.conclusive(layout))


class CheckTest(unittest.TestCase):
    def test_a_run_stops_on_the_wrong_bar(self):
        host = _Host(frame(WRONG))
        host._skill_layout_checked = False
        with self.assertRaises(skill_layout.SkillLayoutWrong) as caught:
            host._check_skill_layout()
        self.assertIn("第3格是压制", str(caught.exception))

    def test_a_right_bar_is_checked_once(self):
        host = _Host(frame(RIGHT[0]))
        host._skill_layout_checked = False
        host._check_skill_layout()
        self.assertTrue(host._skill_layout_checked)

    def test_an_unclear_bar_is_read_again_next_time(self):
        host = _Host(frame(WRONG) * 0)
        host._skill_layout_checked = False
        host._check_skill_layout()
        self.assertFalse(host._skill_layout_checked)

    def test_helpers_outside_a_run_skip_it(self):
        _Host(frame(WRONG))._check_skill_layout()  # no _skill_layout_checked: no raise

    def test_the_run_ends_with_the_plain_line(self):
        warnings = []
        task = SimpleNamespace(
            config={},
            log_warning=warnings.append,
            log_error=lambda *_args: self.fail("not a crash"),
            info_set=lambda *_args: None,
        )
        collector = Collector(task, object(), object(), object())
        text = skill_layout.message([(3, "压制", "召集")])
        with mock.patch.object(
            Collector, "_run_collection", side_effect=skill_layout.SkillLayoutWrong(text)
        ):
            result = collector.run()
        self.assertFalse(result.success)
        self.assertEqual(text, result.message)
        self.assertEqual([f"地图采集：{text}"], warnings)


class MessageTest(unittest.TestCase):
    def host(self):
        infos = []
        host = _Host(None)
        host.task = SimpleNamespace(log_info=infos.append)
        return host, infos

    def test_another_skills_toast_says_the_bar_is_wrong(self):
        host, infos = self.host()
        feedback = SkillFeedbackObservation("无可召集的战场怪物", None, 0.167)
        text = host._not_started_message(SEARCH_ACTION, feedback)
        self.assertIn("游戏却显示召集的提示「无可召集的战场怪物」", text)
        self.assertIn("探查、吸收、召集、压制", text)
        self.assertNotIn("ratio", text)
        self.assertTrue(infos[0].startswith(DIAGNOSTIC_PREFIX))
        self.assertIn("ratio=0.167", infos[0])

    def test_no_toast(self):
        host, _infos = self.host()
        text = host._not_started_message(SEARCH_ACTION, SkillFeedbackObservation("", None))
        self.assertEqual("按了探查，游戏没有显示探查开始，也没出现倒计时", text)


class PlainTest(unittest.TestCase):
    def test_cases(self):
        cases = {
            "探查没有开始（探查点击后未确认执行反馈：ratio=0.167, text=无可召集的战场怪物）":
                "探查没有开始（探查点击后未确认执行反馈）",
            "地图采集：技能识别失败证据（最近12条） {'card': 'x', 'phase': 'y'}":
                "地图采集：技能识别失败证据（最近12条）",
            "探查点击后未确认倒计时：last_ocr=-": "探查点击后未确认倒计时",
            "吸收执行证据不一致：count=3/21->3/21, icon=used->used, text=-": "吸收执行证据不一致",
            "第 12 章 1/3 完成": "第 12 章 1/3 完成",
            "": "",
        }
        for raw, want in cases.items():
            with self.subTest(raw):
                self.assertEqual(want, plain(raw))


if __name__ == "__main__":
    unittest.main()
