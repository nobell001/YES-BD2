"""Leo 2026-11-10 「可以控制人物走去主地圖上的傳送陣嗎」: the teleport circle
in plain view on the field is clicked and walked onto, before the area map
(whose circle icon the character's own marker can hide)."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src.tasks.map_trade.field_circle import find_field_circle
from src.tasks.map_trade.models import NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _read(relative, size=None):
    frame = cv2.imread(str(FIXTURES / relative))
    assert frame is not None, relative
    return cv2.resize(frame, size, interpolation=cv2.INTER_CUBIC) if size else frame


class FindFieldCircleTest(unittest.TestCase):
    def test_player_frame_beside_the_town_circle(self):
        # The report's own picture, shrunk to 670 px; back at 1080p size.
        frame = _read("map_trade/ch14_town_beside_circle_player_summary.png", (1920, 1080))
        circle = find_field_circle(frame)
        self.assertIsNotNone(circle)
        self.assertLess(abs(circle.center[0] - 783), 15)
        self.assertLess(abs(circle.center[1] - 782), 15)

    def test_live_frames_of_another_map(self):
        for name, centre in (
            ("main_story/npc_prompt_glow_live.jpg", (998, 829)),
            ("main_story/talent_menu_live.jpg", (966, 934)),
        ):
            with self.subTest(name=name):
                circle = find_field_circle(_read(name))
                self.assertIsNotNone(circle)
                self.assertLess(abs(circle.center[0] - centre[0]), 10)
                self.assertLess(abs(circle.center[1] - centre[1]), 10)

    def test_other_lights_and_things_in_front(self):
        # Leo's frames 2026-11-10 「傳送陣會隨著地圖光線而不同」: night map
        # behind a pillar, snow, a dungeon lit yellow, 第三章 with a rope across,
        # a dark subway, an office.
        for name, centre in (
            ("behind_pillar", (1488, 523)),
            ("snow", (486, 740)),
            ("dungeon", (1519, 546)),
            ("lava_rope", (1236, 572)),
            ("subway", (1419, 622)),
            ("office", (1218, 692)),
        ):
            with self.subTest(name=name):
                circle = find_field_circle(_read(f"map_trade/field_circle_{name}_leo_tw.jpg"))
                self.assertIsNotNone(circle)
                self.assertLess(abs(circle.center[0] - centre[0]), 12)
                self.assertLess(abs(circle.center[1] - centre[1]), 12)

    def test_other_sizes_give_the_same_place(self):
        frame = _read("main_story/npc_prompt_glow_live.jpg")
        for width, height in ((2560, 1440), (3840, 2160), (1280, 720)):
            with self.subTest(width=width):
                circle = find_field_circle(cv2.resize(frame, (width, height)))
                self.assertIsNotNone(circle)
                self.assertLess(abs(circle.center[0] / width - 998 / 1920), 0.01)
                self.assertLess(abs(circle.center[1] / height - 829 / 1080), 0.01)

    def test_teal_roofs_and_water_are_not_a_circle(self):
        # Leo's frame of the same town, no circle in view.
        self.assertIsNone(find_field_circle(_read("map_trade/ch14_town_field_leo_tw.jpg")))

    def test_no_other_picture_in_the_fixtures_shows_one_by_mistake(self):
        known = {"npc_prompt_glow_live.jpg", "talent_menu_live.jpg"}
        for path in sorted(FIXTURES.rglob("*")):
            if path.suffix.lower() not in (".png", ".jpg") or path.name in known:
                continue
            if "field_circle_" in path.name or "beside_circle" in path.name:
                continue
            if path.name.startswith("teleport_loading_circle_"):
                # The teleport's loading screen draws the circle itself; the
                # walk never looks there (no field HUD, see the walk tests).
                continue
            frame = cv2.imread(str(path))
            if frame is None or frame.shape[1] < 1200:
                continue
            if abs(frame.shape[1] / frame.shape[0] - 16 / 9) > 0.02:
                continue
            with self.subTest(name=path.name):
                self.assertIsNone(find_field_circle(frame))


@mock.patch("src.tasks.map_trade.navigator_sandbox.FIELD_CIRCLE_STILL_SECONDS", 0.05)
class WalkToCircleInViewTest(unittest.TestCase):
    def _navigator(self, frames, hand_at=None):
        """``frames``: what each look shows, the last one repeated.
        ``hand_at``: the hand shows once this many (clicks, key steps) were made."""
        calls = []
        looks = {"n": 0}
        task = SimpleNamespace(
            config={},
            ocr=lambda **_k: [],
            info_set=lambda *_a: None,
            log_info=lambda *_a: None,
            hold_key=lambda key, seconds, after_sleep=0.0: calls.append(("key", key)) or True,
        )
        vision = Vision(task)

        def capture():
            looks["n"] += 1
            return frames[min(looks["n"], len(frames)) - 1]

        vision.capture = capture
        vision.click_client = lambda center, *_a, **_k: calls.append(("click", tuple(center)))
        navigator = Navigator(task, vision)
        navigator._status = lambda *_args: None

        def hand(**_k):
            done = (
                sum(c[0] == "click" for c in calls),
                sum(c[0] == "key" for c in calls),
            )
            return hand_at is not None and done >= hand_at

        navigator._click_sandbox_teleport_interaction = hand
        navigator._open_circle_page = lambda trigger: (
            calls.append(("page", trigger))
            or NavigationResult(True, ScreenState.AREA_MAP, trigger)
        )
        return navigator, calls

    def test_click_walk_then_the_hand_is_used(self):
        navigator, calls = self._navigator(
            [_read("main_story/npc_prompt_glow_live.jpg")], hand_at=(1, 0)
        )
        result = navigator._walk_to_circle_in_view()
        self.assertTrue(result.success)
        self.assertEqual("click", calls[0][0])
        self.assertLess(abs(calls[0][1][0] - 998), 10)
        self.assertEqual([("page", "点画面上的传送阵走过去")], calls[1:])

    def test_view_moving_after_the_click_is_waited_for_not_walked_over(self):
        # The click started a walk: each look shows the view panned on, and
        # the hand shows at the end.  No key is pressed meanwhile.
        frame = _read("main_story/npc_prompt_glow_live.jpg")
        frames = [frame] + [np.roll(frame, -40 * i, axis=1) for i in range(1, 6)]
        navigator, calls = self._navigator(frames, hand_at=(1, 0))
        hand, looks = navigator._click_sandbox_teleport_interaction, {"n": 0}

        def late_hand(**kwargs):
            looks["n"] += 1
            return looks["n"] > 4 and hand(**kwargs)

        navigator._click_sandbox_teleport_interaction = late_hand
        result = navigator._walk_to_circle_in_view()
        self.assertTrue(result.success)
        self.assertEqual([], [c for c in calls if c[0] == "key"])
        self.assertEqual(("page", "点画面上的传送阵走过去"), calls[-1])

    def test_wasd_player_is_walked_there_by_keys(self):
        # The click moved nothing on screen (keyboard movement): the circle,
        # right of and below the character's place, is walked to with D and S.
        navigator, calls = self._navigator(
            [_read("main_story/npc_prompt_glow_live.jpg")], hand_at=(1, 2)
        )
        result = navigator._walk_to_circle_in_view()
        self.assertTrue(result.success)
        self.assertEqual(1, sum(c[0] == "click" for c in calls))
        keys = [c[1] for c in calls if c[0] == "key"]
        self.assertEqual(2, len(keys))
        self.assertTrue(set(keys) <= {"d", "s"}, keys)
        self.assertEqual(("page", "方向键走到画面上的传送阵"), calls[-1])

    def test_circle_never_nearer_gives_up_for_the_area_map(self):
        # The same frame on every look: the keys move nothing.
        navigator, calls = self._navigator(
            [_read("main_story/npc_prompt_glow_live.jpg")], hand_at=None
        )
        self.assertIsNone(navigator._walk_to_circle_in_view())
        self.assertLessEqual(sum(c[0] == "key" for c in calls), 5)
        self.assertNotIn("page", [c[0] for c in calls])

    def test_key_not_sent_gives_up(self):
        navigator, calls = self._navigator(
            [_read("main_story/npc_prompt_glow_live.jpg")], hand_at=None
        )
        navigator.task.hold_key = lambda *_a, **_k: False
        self.assertIsNone(navigator._walk_to_circle_in_view())
        self.assertNotIn("page", [c[0] for c in calls])

    def test_no_field_hud_means_no_click(self):
        # A menu over the field: the circle shows, the field's key caps do not.
        navigator, calls = self._navigator([_read("main_story/talent_menu_live.jpg")])
        self.assertIsNone(navigator._walk_to_circle_in_view())
        self.assertEqual([], calls)

    def test_no_circle_in_view_means_no_click(self):
        navigator, calls = self._navigator([_read("map_trade/ch14_town_field_leo_tw.jpg")])
        self.assertIsNone(navigator._walk_to_circle_in_view())
        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
