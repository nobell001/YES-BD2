import unittest
from pathlib import Path

import cv2
import numpy as np

from src.utils.stage_walk import (
    STAGE_NO_PROGRESS_STEPS,
    STAGE_RESETS_PER_WALK,
    STAGE_TARGET,
    WalkStep,
    find_stage,
    plan_step,
)


def synthetic_frame(stage_center, occluder=None):
    frame = np.full((1080, 1920, 3), (60, 20, 40), dtype=np.uint8)  # purple floor
    cv2.ellipse(frame, stage_center, (140, 70), 0, 0, 360, (30, 20, 200), -1)
    cv2.rectangle(frame, (1500, 20), (1900, 250), (30, 20, 200), -1)  # red bar carpet
    if occluder:
        x, y = occluder
        cv2.rectangle(frame, (x - 30, y - 80), (x + 30, y + 20), (200, 200, 200), -1)
    return frame


class StageDetectionTest(unittest.TestCase):
    def test_finds_the_stage_and_ignores_the_carpet(self):
        center = find_stage(synthetic_frame((790, 650)))
        self.assertIsNotNone(center)
        self.assertLess(abs(center[0] - 790), 8)
        self.assertLess(abs(center[1] - 650), 8)

    def test_no_stage_in_view(self):
        frame = np.full((1080, 1920, 3), (60, 20, 40), dtype=np.uint8)
        self.assertIsNone(find_stage(frame))

    def test_live_spawn_frame_if_available(self):
        # Spawn frame from 2026-09-26: stage down-left of the character.
        path = Path(".local-dev/shots/pvp_fail.png")
        if not path.exists():
            self.skipTest("live calibration frame not present")
        center = find_stage(cv2.imread(str(path)))
        self.assertIsNotNone(center)
        self.assertLess(center[0], STAGE_TARGET[0])
        self.assertGreater(center[1], STAGE_TARGET[1])


class WalkPlanTest(unittest.TestCase):
    def test_spawn_offset_walks_the_longer_axis_first(self):
        # From spawn the stage is 135 px left (0.25 s) and 115 px down (0.29 s).
        step = plan_step((790, 650))
        self.assertEqual("s", step.key)
        self.assertGreater(step.seconds, 0.25)

    def test_directions(self):
        self.assertEqual("d", plan_step((STAGE_TARGET[0] + 200, STAGE_TARGET[1])).key)
        self.assertEqual("w", plan_step((STAGE_TARGET[0], STAGE_TARGET[1] - 200)).key)
        self.assertEqual("s", plan_step((STAGE_TARGET[0], STAGE_TARGET[1] + 200)).key)

    def test_steps_are_bounded_and_arrival_stops(self):
        far = plan_step((STAGE_TARGET[0] - 900, STAGE_TARGET[1]))
        self.assertEqual(WalkStep("a", 0.35), far)
        self.assertIsNone(plan_step((STAGE_TARGET[0] + 10, STAGE_TARGET[1] - 10)))


if __name__ == "__main__":
    unittest.main()


class WalkLoopLostStageTest(unittest.TestCase):
    """The stage walked out of the search area (4K PC 1080p clone 2026-11-05)."""

    def _task(self, sightings):
        from src.tasks.PVPTask import PVPTask

        task = object.__new__(PVPTask)
        task.config = {}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_a, **_k: None
        task.sleep = lambda *_a: None
        task.keys = []
        seen = iter(sightings)
        task._pre_battle_visible = lambda: False
        task._stage_in_view = lambda: next(seen, None)

        def hold_key(key, seconds, after_sleep=0.0):
            task.keys.append((key, seconds))
            return True

        task.hold_key = hold_key
        task._nudge_until_pre_battle = lambda: True
        task.resets = 0

        def reset():
            task.resets += 1
            return True

        task._recover_stage_position = reset
        return task

    def keys(self, task):
        return [key for key, _seconds in task.keys]

    def test_the_game_reset_is_pressed_before_walking(self):
        # 4K PC clone 11-05: 定位修正 walked the character onto the stage.
        task = self._task([])
        task._pre_battle_visible = lambda: task.resets > 0
        self.assertTrue(task._walk_onto_stage())
        self.assertEqual(1, task.resets)
        self.assertEqual([], task.keys)

    def test_already_on_the_stage_presses_nothing(self):
        task = self._task([])
        task._pre_battle_visible = lambda: True
        self.assertTrue(task._walk_onto_stage())
        self.assertEqual((0, []), (task.resets, task.keys))

    def test_the_red_carpet_far_from_the_stage_is_not_walked_to(self):
        # Stage far below -> S; then only the carpet at the top right.
        task = self._task([(925, 1000), (1360, 366), (925, 1000), (925, 870), (925, 740), (925, 610), (925, 535)])
        self.assertTrue(task._walk_onto_stage())
        self.assertEqual(["s", "w"], self.keys(task)[:2])  # walked back, not toward the carpet
        self.assertNotIn("d", self.keys(task))

    def test_nothing_red_after_a_step_walks_it_back(self):
        task = self._task([(925, 900), None, (925, 890), (925, 760), (925, 625), (925, 540)])
        self.assertTrue(task._walk_onto_stage())
        self.assertEqual(["s", "w"], self.keys(task)[:2])

    def test_nothing_red_where_the_stage_should_be_is_the_line_up(self):
        # Clone 11-05: stepping onto the stage hid it, and the walk stepped back.
        task = self._task([(925, 620), None])
        self.assertTrue(task._walk_onto_stage())
        self.assertEqual(["s"], self.keys(task))

    def test_no_stage_at_all_still_gives_up(self):
        task = self._task([None] * 6)
        self.assertFalse(task._walk_onto_stage())
        self.assertEqual([], task.keys)
        self.assertEqual(STAGE_RESETS_PER_WALK, task.resets)

    def test_out_of_view_presses_the_game_reset_again(self):
        task = self._task([None, (925, 560)])
        self.assertTrue(task._walk_onto_stage())
        self.assertEqual(2, task.resets)
        self.assertEqual([], task.keys)

    def test_a_red_patch_that_never_comes_nearer_is_given_up(self):
        # Clone 11-05 W 1.2 s: a cut-off piece of the carpet, (1430, 369),
        # was walked at for 55 s.
        task = self._task([(1430, 369)] * 20)
        self.assertFalse(task._walk_onto_stage())
        self.assertEqual(STAGE_RESETS_PER_WALK, task.resets)
        self.assertLessEqual(len(task.keys), 2 * STAGE_NO_PROGRESS_STEPS)

    def test_standing_on_a_red_patch_without_the_pre_battle_screen(self):
        task = self._task([(925, 535), (925, 535), (925, 535)])
        task._nudge_until_pre_battle = lambda: False
        self.assertFalse(task._walk_onto_stage())
        self.assertEqual(STAGE_RESETS_PER_WALK, task.resets)

    def test_a_near_patch_is_the_stage(self):
        # 0.35 s of S moves the stage ~137 px up; 60 px off is still the stage.
        task = self._task([(925, 800), (985, 663), (925, 535)])
        self.assertTrue(task._walk_onto_stage())
        self.assertEqual(["s", "s"], self.keys(task)[:2])


class StageShapeTest(unittest.TestCase):
    """The stage is told from the carpet by its shape, not by where it is."""

    def test_a_stage_far_from_the_character_is_found_not_the_carpet(self):
        # Screen library b3f20b3bac46: stage at (319, 683), outside the old
        # search area; the carpet was then the largest red patch inside it.
        frame = np.full((1080, 1920, 3), (60, 20, 40), dtype=np.uint8)
        cv2.ellipse(frame, (320, 683), (108, 52), 0, 0, 360, (30, 20, 200), -1)
        carpet = np.array([[820, 85], [1260, 85], [1260, 380], [1100, 380]], np.int32)
        cv2.fillPoly(frame, [carpet], (30, 20, 200))
        center = find_stage(frame)
        self.assertIsNotNone(center)
        self.assertLess(abs(center[0] - 320), 8)
        self.assertLess(abs(center[1] - 683), 8)

    def test_the_carpet_alone_is_not_the_stage(self):
        frame = np.full((1080, 1920, 3), (60, 20, 40), dtype=np.uint8)
        cv2.rectangle(frame, (1230, 60), (1750, 370), (30, 20, 200), -1)
        self.assertIsNone(find_stage(frame))

    def test_measured_sizes(self):
        from src.utils.stage_walk import stage_shaped

        # Six PVP hall frames (1080p/2K/4K): stage parts, then carpet parts.
        for area, width, height in ((24966, 259, 133), (13295, 217, 103), (15950, 259, 147), (13852, 185, 112)):
            self.assertTrue(stage_shaped(area, width, height))
        for area, width, height in ((67080, 525, 315), (59288, 444, 299), (4091, 94, 78), (3081, 168, 81)):
            self.assertFalse(stage_shaped(area, width, height))


class MouseStageClickTest(unittest.TestCase):
    """Players who move by mouse (Leo 2026-11-05 「記得滑鼠移動的也要做好」)."""

    def _task(self, template_found, stage):
        from src.tasks.PVPTask import PVPTask

        task = object.__new__(PVPTask)
        task.config = {}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_a, **_k: None
        task.clicks = []
        task._pre_battle_visible = lambda: False
        task._click_template_until = lambda *_a, **_k: template_found
        task._stage_in_view = lambda: stage
        task.operate_click = lambda x, y, after_sleep=0.0: task.clicks.append((round(x, 3), round(y, 3)))
        return task

    def test_the_stage_picture_first(self):
        task = self._task(True, (300, 700))
        self.assertTrue(task._click_pvp_stage_once(1.0))
        self.assertEqual([], task.clicks)

    def test_the_red_shape_when_the_picture_is_not_matched(self):
        task = self._task(False, (960, 540))
        self.assertFalse(task._click_pvp_stage_once(1.0))  # not before 定位修正
        self.assertEqual([], task.clicks)
        self.assertTrue(task._click_pvp_stage_once(1.0, by_colour=True))
        self.assertEqual([(0.5, 0.5)], task.clicks)

    def test_neither_way_finds_it(self):
        task = self._task(False, None)
        self.assertFalse(task._click_pvp_stage_once(1.0, by_colour=True))
        self.assertEqual([], task.clicks)
