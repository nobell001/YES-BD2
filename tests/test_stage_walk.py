import unittest
import unittest.mock
from pathlib import Path

import cv2
import numpy as np

from src.utils.stage_walk import (
    STAGE_NO_PROGRESS_STEPS,
    STAGE_RESETS_PER_WALK,
    STAGE_TARGET,
    WalkStep,
    find_stage,
    find_stages,
    predict_after_step,
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
        task._stage_in_view = lambda *_a: next(seen, None)

        def hold_key(key, seconds, after_sleep=0.0):
            task.keys.append((key, seconds))
            return True

        task.hold_key = hold_key
        task.moves = []

        def hold_keys(steps, after_sleep=0.0):
            task.moves.append(tuple(step.key for step in steps))
            return all(hold_key(step.key, step.seconds) for step in steps)

        task.hold_keys = hold_keys
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
        # Since 2K clone 11-18 it is left out of the walk (not walked at
        # again) and, with nothing else red, the walk gives up.
        task = self._task([])
        task._stage_in_view = lambda near=None, ignore=(): (
            None if any(_distance((1430, 369), spot) <= 90 for spot in ignore) else (1430, 369)
        )
        self.assertFalse(task._walk_onto_stage())
        self.assertEqual(STAGE_RESETS_PER_WALK, task.resets)
        self.assertLessEqual(len(task.moves), 2 * STAGE_NO_PROGRESS_STEPS)

    def test_standing_on_a_red_patch_without_the_pre_battle_screen(self):
        task = self._task([(925, 535), (925, 535), (925, 535)])
        task._nudge_until_pre_battle = lambda: False
        self.assertFalse(task._walk_onto_stage())
        self.assertEqual(STAGE_RESETS_PER_WALK, task.resets)

    def test_a_near_patch_is_the_stage(self):
        # 0.35 s of S moves the stage ~137 px up; 60 px off is still the stage.
        task = self._task([(925, 800), (985, 663), (925, 535)])
        self.assertTrue(task._walk_onto_stage())
        self.assertEqual([("s",), ("d", "s")], task.moves[:2])  # walked on toward it


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
        task._stage_in_view = lambda *_a: stage
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


PLAYER_CURTAIN_FRAME = Path(__file__).parent / "fixtures" / "pvp" / "stage_curtain_player_1080.jpg"
# The report's small frame 2 s before the stop, scaled up to 1080.
# 2K clone 11-18: the character at the bar after walking off; the stage
# below the bottom-left corner, only its X at the edge (battle log blurred).
CLONE_BAR_FRAME = Path(__file__).parent / "fixtures" / "pvp" / "stage_offscreen_bar_2k_1080.jpg"
MARKER_ICON = (
    Path(__file__).resolve().parents[1]
    / "recognition-assets" / "template-assets" / "evil_castle" / "castle_marker.png"
)
PLAYER_PILLAR_FRAME = Path(__file__).parent / "fixtures" / "pvp" / "stage_pillar_cover_player_thumb_1080.jpg"


def hall_with_curtain(stage_center):
    """A PVP hall: the stage, plus the red curtain cut by the top-right
    screen corner, larger than the stage and with its shape (player 11-18)."""
    frame = np.full((1080, 1920, 3), (60, 20, 40), dtype=np.uint8)
    cv2.ellipse(frame, (1793, 30), (170, 80), 0, 0, 360, (30, 20, 200), -1)
    if 0 < stage_center[0] < 1920 and 0 < stage_center[1] < 1080:
        cv2.ellipse(frame, stage_center, (125, 58), 0, 0, 360, (30, 20, 200), -1)
    return frame


class CurtainNotStageTest(unittest.TestCase):
    """Player v0.3.24 1080p (11-18): 「镜中之战经常找不到位置」.  The red
    curtain in the top-right corner was larger than the stage and had its
    shape; it was taken as the stage, thrown away as too far, and the walk
    stepped back from the real stage again and again."""

    def test_player_frame_has_both_and_the_stage_is_taken(self):
        frame = cv2.imread(str(PLAYER_CURTAIN_FRAME))
        patches = find_stages(frame)
        self.assertEqual(2, len(patches))
        curtain, stage = patches
        self.assertGreater(curtain.area, stage.area)  # the old pick: the largest
        self.assertTrue(curtain.cut)
        self.assertFalse(stage.cut)
        self.assertLess(_distance(find_stage(frame), (1238, 409)), 15)
        # Where the walk expected it after a step (log: 预估位置 (1268, 446)).
        self.assertLess(_distance(find_stage(frame, near=(1268, 446)), (1238, 409)), 15)

    def test_a_stage_with_a_corner_covered_by_the_pillar(self):
        # Two seconds before the player's run stopped (small frame of the
        # report): the bar's pillar covered the stage's lower-left corner,
        # 254 x 88, flatter than the full shape allows.
        frame = cv2.imread(str(PLAYER_PILLAR_FRAME))
        self.assertLess(_distance(find_stage(frame, near=(1268, 446)), (1243, 445)), 15)
        self.assertLess(_distance(find_stage(frame), (1243, 445)), 15)  # the curtain is still not taken

    def test_the_full_shape_comes_before_a_covered_one(self):
        frame = np.full((1080, 1920, 3), (60, 20, 40), dtype=np.uint8)
        cv2.ellipse(frame, (500, 700), (140, 40), 0, 0, 360, (30, 20, 200), -1)  # flat: covered shape only
        cv2.ellipse(frame, (1200, 600), (110, 55), 0, 0, 360, (30, 20, 200), -1)
        self.assertLess(_distance(find_stage(frame), (1200, 600)), 8)
        self.assertLess(_distance(find_stage(frame, near=(520, 690)), (500, 700)), 8)

    def test_only_the_curtain_is_not_a_stage(self):
        self.assertIsNone(find_stage(hall_with_curtain((-500, -500))))

    def test_the_walk_reaches_the_stage_past_the_curtain(self):
        from src.tasks.PVPTask import PVPTask

        task = object.__new__(PVPTask)
        task.config = {}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_a, **_k: None
        task.sleep = lambda *_a: None
        stage = [(1248, 317)]  # first sighting in the player's log
        task.capture_frame = lambda: hall_with_curtain(stage[0])
        task._pre_battle_visible = lambda: _distance(stage[0], STAGE_TARGET) <= 40
        task._recover_stage_position = lambda: False  # 定位修正 did not help the player
        task.keys = []

        def hold_key(key, seconds, after_sleep=0.0):
            task.keys.append(key)
            stage[0] = predict_after_step(stage[0], WalkStep(key, seconds))
            return True

        task.hold_key = hold_key
        task.hold_keys = lambda steps, after_sleep=0.0: all(hold_key(s.key, s.seconds) for s in steps)
        self.assertTrue(task._walk_onto_stage())
        self.assertLessEqual(len(task.keys), 6)
        self.assertNotIn("s", task.keys)  # never stepped back from it

    def test_the_mouse_click_goes_to_the_stage_not_the_corner(self):
        # The curtain sits under the 主页 button: clicking it would go home.
        from src.tasks.PVPTask import PVPTask

        task = object.__new__(PVPTask)
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_a, **_k: None
        task._pre_battle_visible = lambda: False
        frame = cv2.imread(str(PLAYER_CURTAIN_FRAME))
        task.capture_frame = lambda: frame
        clicks = []
        task.operate_click = lambda x, y, after_sleep=0.0: clicks.append((x * 1920, y * 1080))
        self.assertTrue(task._click_stage_by_colour())
        self.assertEqual(1, len(clicks))
        self.assertLess(_distance(clicks[0], (1238, 409)), 15)


def _distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class StraightWalkTest(unittest.TestCase):
    """Leo 11-18 「能不能根據人物和舞台位置去調整方向鍵」: hold both keys
    toward the stage so the walk follows the straight line."""

    def test_both_keys_in_proportion(self):
        from src.utils.stage_walk import MAX_STEP_SECONDS, PIXELS_PER_SECOND, plan_move

        move = plan_move((1238, 409))  # up-right of the character
        self.assertEqual(["d", "w"], [step.key for step in move])
        x_time = (1238 - STAGE_TARGET[0]) / PIXELS_PER_SECOND["x"]
        y_time = (STAGE_TARGET[1] - 409) / PIXELS_PER_SECOND["y"]
        self.assertAlmostEqual(MAX_STEP_SECONDS, move[0].seconds, places=2)
        self.assertAlmostEqual(y_time / x_time, move[1].seconds / move[0].seconds, places=1)

    def test_straight_line_and_arrival(self):
        from src.utils.stage_walk import plan_move

        self.assertEqual(("s",), tuple(step.key for step in plan_move((STAGE_TARGET[0], 900))))
        self.assertEqual(("a",), tuple(step.key for step in plan_move((300, STAGE_TARGET[1] + 10))))
        self.assertIsNone(plan_move((STAGE_TARGET[0] + 10, STAGE_TARGET[1] + 10)))


class HallSim:
    """A PVP hall the camera moves over: a textured floor, the stage on it,
    the red curtain fixed at the top-right corner (player 11-18)."""

    def __init__(self, stage_screen, diagonal=True, wall_key=None, marker=False, carpet=None, edge_minimap=False):
        from src.utils.stage_walk import PIXELS_PER_SECOND

        rng = np.random.default_rng(7)
        noise = rng.integers(0, 120, (300, 400, 3), dtype=np.uint8)
        self.world = cv2.resize(noise, (4000, 3000), interpolation=cv2.INTER_CUBIC)
        self.world[:, :, 2] //= 3  # keep the floor out of the red mask
        self.camera = [1000.0, 1000.0]  # world point at the screen's top-left
        self.stage_world = (stage_screen[0] + 1000.0, stage_screen[1] + 1000.0)
        self.diagonal = diagonal
        self.wall_key = wall_key
        self.speed = PIXELS_PER_SECOND
        self.marker = marker  # the red X over the stage
        # Minimap with the floor on the lower-left side only (at the bar).
        self.edge_minimap = edge_minimap
        # A stage-shaped piece of the bar's carpet, out of reach (2K clone 11-18).
        self.carpet_world = None if carpet is None else (carpet[0] + 1000.0, carpet[1] + 1000.0)

    def stage_screen(self):
        return (int(self.stage_world[0] - self.camera[0]), int(self.stage_world[1] - self.camera[1]))

    def frame(self):
        x, y = int(self.camera[0]), int(self.camera[1])
        frame = self.world[y : y + 1080, x : x + 1920].copy()
        cv2.ellipse(frame, (1793, 30), (170, 80), 0, 0, 360, (30, 20, 200), -1)
        sx, sy = self.stage_screen()
        if -200 < sx < 2120 and -200 < sy < 1280:
            cv2.ellipse(frame, (sx, sy), (125, 58), 0, 0, 360, (30, 20, 200), -1)
        if self.carpet_world is not None:
            cx, cy = int(self.carpet_world[0] - self.camera[0]), int(self.carpet_world[1] - self.camera[1])
            cv2.ellipse(frame, (cx, cy), (120, 55), 0, 0, 360, (30, 20, 200), -1)
        if self.edge_minimap:
            from src.utils.stage_walk import MINIMAP_CENTRE, MINIMAP_RADIUS

            cv2.circle(frame, MINIMAP_CENTRE, MINIMAP_RADIUS, (20, 20, 20), -1)
            cv2.ellipse(frame, MINIMAP_CENTRE, (MINIMAP_RADIUS, MINIMAP_RADIUS), 0, 45, 225, (200, 200, 200), -1)
        if self.marker:
            from src.utils.stage_walk import STAGE_BELOW_MARKER, _marker_shape

            icon = cv2.imdecode(np.fromfile(str(MARKER_ICON), np.uint8), cv2.IMREAD_UNCHANGED)
            h, w = icon.shape[:2]
            x0, y0 = sx - w // 2, sy - STAGE_BELOW_MARKER - h // 2
            if 0 <= x0 and x0 + w <= 1920 and 0 <= y0 and y0 + h <= 1080:
                region = frame[y0 : y0 + h, x0 : x0 + w]
                alpha = icon[:, :, 3:4].astype(np.float32) / 255.0
                region[:] = (icon[:, :, :3] * alpha + region * (1 - alpha)).astype(np.uint8)
        return frame

    def walk(self, steps):
        steps = tuple(steps)
        if not self.diagonal:
            steps = steps[:1]  # this game takes one key only
        if self.blocked(steps):
            return
        for step in steps:
            if step.key == self.wall_key:
                continue
            if step.key in ("a", "d"):
                self.camera[0] += (-1 if step.key == "a" else 1) * self.speed["x"] * step.seconds
            else:
                self.camera[1] += (-1 if step.key == "w" else 1) * self.speed["y"] * step.seconds
        # The hub's walls: the view stays inside the world.
        self.camera[0] = min(max(self.camera[0], 0.0), 4000.0 - 1920)
        self.camera[1] = min(max(self.camera[1], 0.0), 3000.0 - 1080)

    def blocked(self, steps):
        """Walking toward the carpet runs into the bar counter."""
        if self.carpet_world is None:
            return False
        cx = self.carpet_world[0] - self.camera[0]
        cy = self.carpet_world[1] - self.camera[1]
        return _distance((cx, cy), STAGE_TARGET) < 260 and any(step.key in ("d", "w") for step in steps)

    def on_stage(self):
        return _distance(self.stage_screen(), STAGE_TARGET) <= 40


def sim_task(sim, resets=None):
    from src.tasks.PVPTask import PVPTask

    task = object.__new__(PVPTask)
    task.config = {}
    task.info = {}
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    task.logs = []
    task.log_info = lambda text, *_a, **_k: task.logs.append(text)
    task.sleep = lambda *_a: None
    task.capture_frame = sim.frame
    task._pre_battle_visible = sim.on_stage
    task._recover_stage_position = resets or (lambda: False)
    task.moves = []

    def hold_keys(steps, after_sleep=0.0):
        task.moves.append(tuple(step.key for step in steps))
        sim.walk(steps)
        return True

    task.hold_keys = hold_keys
    task.hold_key = lambda key, seconds, after_sleep=0.0: hold_keys((WalkStep(key, seconds),))
    return task


class WalkSimTest(unittest.TestCase):
    def test_walks_diagonally_to_the_stage(self):
        sim = HallSim((1238, 317))
        task = sim_task(sim)
        self.assertTrue(task._walk_onto_stage())
        self.assertIn(("d", "w"), task.moves)
        self.assertLessEqual(len(task.moves), 4)
        self.assertIn("PVP 走位记录", task.info)
        self.assertIn("←选", task.info["PVP 红色区块"])

    def test_a_game_that_does_not_walk_diagonally_goes_back_to_one_key(self):
        sim = HallSim((1238, 317), diagonal=False)
        task = sim_task(sim)
        self.assertTrue(task._walk_onto_stage())
        self.assertTrue(any("改回一次按一个方向键" in line for line in task.logs))
        self.assertEqual(1, len(task.moves[-1]))

    def test_a_step_that_did_not_move_the_view_is_written_down(self):
        sim = HallSim((925, 300), wall_key="w")  # straight up, W blocked
        task = sim_task(sim)
        self.assertFalse(task._walk_onto_stage())
        self.assertIn("画面没动", task.info["PVP 走位记录"])
        self.assertTrue(any("画面没动" in line for line in task.logs))


class StageResetWatchTest(unittest.TestCase):
    """定位修正 is watched, not waited for a fixed 6 s (Leo 11-18)."""

    def _task(self, frames, battle_after=None):
        from src.tasks import PVPTask as module

        clock = [0.0]
        task = object.__new__(module.PVPTask)
        task.config = {}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_a, **_k: None
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        shots = iter(frames)
        last = [None]

        def frame():
            last[0] = next(shots, last[0])
            return last[0]

        task._stage_frame = frame
        task._pre_battle_visible = lambda: battle_after is not None and clock[0] >= battle_after
        patcher = unittest.mock.patch.object(module, "monotonic", lambda: clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        return task, clock

    def test_nothing_moved(self):
        from src.tasks.PVPTask import STAGE_RESET_STILL

        sim = HallSim((925, 300))
        task, clock = self._task([sim.frame()] * 30)
        self.assertEqual(STAGE_RESET_STILL, task._watch_stage_reset())
        self.assertLess(clock[0], 6.0)

    def test_walked_then_stopped(self):
        from src.tasks.PVPTask import STAGE_RESET_MOVED

        sim = HallSim((925, 300))
        frames = []
        for _ in range(5):
            sim.walk((WalkStep("w", 0.2),))
            frames.append(sim.frame())
        task, _clock = self._task(frames)
        self.assertEqual(STAGE_RESET_MOVED, task._watch_stage_reset())

    def test_reached_the_stage(self):
        from src.tasks.PVPTask import STAGE_RESET_BATTLE

        sim = HallSim((925, 300))
        task, clock = self._task([sim.frame()] * 30, battle_after=1.0)
        self.assertEqual(STAGE_RESET_BATTLE, task._watch_stage_reset())

    def test_a_press_that_moved_nothing_is_not_repeated(self):
        from src.tasks.PVPTask import STAGE_RESET_STILL

        presses = []
        sim = HallSim((-900, -900))  # stage nowhere in view
        task = None

        def reset():
            presses.append(1)
            task._stage_reset_result = STAGE_RESET_STILL
            return True

        task = sim_task(sim, resets=reset)
        self.assertFalse(task._walk_onto_stage())
        self.assertEqual(1, len(presses))
        self.assertIn("角色没有动", task.info["PVP 定位修正"])


class HudAreaTest(unittest.TestCase):
    def test_a_red_patch_under_the_hud_is_not_taken_on_its_own(self):
        from src.utils.stage_walk import find_stages

        frame = np.full((1080, 1920, 3), (60, 20, 40), dtype=np.uint8)
        cv2.ellipse(frame, (1700, 860), (110, 55), 0, 0, 360, (30, 20, 200), -1)  # skill wheel area
        self.assertTrue(find_stages(frame)[0].cut)
        self.assertIsNone(find_stage(frame))
        self.assertIsNotNone(find_stage(frame, near=(1690, 850)))


class StageMarkerTest(unittest.TestCase):
    """2K clone 11-18 (Leo 「自己亂走，然後看看能不能走回去」): walked off, the
    stage left the screen and a cut piece of the bar's red carpet had its
    shape; the walk pushed into the bar for 60-100 s, five rounds of seven."""

    def test_the_x_over_the_stage(self):
        from src.utils.stage_walk import find_stage_marker, stage_from_marker

        frame = cv2.imread(str(PLAYER_CURTAIN_FRAME))
        marker = find_stage_marker(frame)
        self.assertLess(_distance(marker, (1238, 270)), 8)
        self.assertLess(_distance(stage_from_marker(marker), find_stage(frame)), 30)

    def test_at_the_bar_the_x_is_at_the_edge_and_the_red_is_the_carpet(self):
        from src.utils.stage_walk import MARKER_MATCH_PIXELS, find_stage_marker, stage_from_marker

        frame = cv2.imread(str(CLONE_BAR_FRAME))
        marker = find_stage_marker(frame)
        self.assertLess(_distance(marker, (234, 1056)), 8)
        carpet = find_stage(frame)
        self.assertIsNotNone(carpet)  # the carpet piece has the stage's shape
        self.assertGreater(_distance(carpet, stage_from_marker(marker)), MARKER_MATCH_PIXELS)

    def test_no_x_without_its_shape(self):
        from src.utils.stage_walk import find_stage_marker

        self.assertIsNone(find_stage_marker(cv2.imread(str(PLAYER_PILLAR_FRAME))))
        self.assertIsNone(find_stage_marker(synthetic_frame((790, 650))))

    def test_the_minimap_floor_lies_toward_the_stage(self):
        from src.utils.stage_walk import floor_direction

        dx, dy = floor_direction(cv2.imread(str(CLONE_BAR_FRAME)))
        self.assertLess(dx, 0)  # lower left
        self.assertGreater(dy, 0.5)
        # Next to the stage the floor is all around: no direction.
        self.assertIsNone(floor_direction(cv2.imread(str(PLAYER_CURTAIN_FRAME))))
        self.assertIsNone(floor_direction(np.zeros((1080, 1920, 3), np.uint8)))

    def test_the_walk_follows_the_x_not_the_carpet(self):
        sim = HallSim((300, 1180), marker=True, carpet=(1140, 400))
        task = sim_task(sim)
        self.assertTrue(task._walk_onto_stage())
        self.assertEqual(("a", "s"), task.moves[0])
        self.assertNotIn("d", [key for move in task.moves for key in move])

    def test_at_the_side_of_the_hub_the_minimap_beats_an_unmarked_red_patch(self):
        # 2K clone 11-18, behind the pillar right of the bar: no X in view,
        # pieces of the bar's carpet walked at for 64 s.
        sim = HallSim((-2000, 3000), carpet=(1140, 400), edge_minimap=True)
        task = sim_task(sim)
        task._walk_onto_stage()
        first = task.moves[0]
        self.assertIn("a", first)  # toward the floor (lower left), not the carpet
        self.assertIn("s", first)
        self.assertNotIn("d", first)
        self.assertNotIn("w", first)

    def test_a_red_patch_out_of_reach_is_left_out(self):
        # No X in view: the carpet is walked at, the view stands still, the
        # patch is left out and the walk does not keep pushing.
        sim = HallSim((-2000, 3000), carpet=(1140, 400))
        task = sim_task(sim)
        self.assertFalse(task._walk_onto_stage())
        self.assertTrue(any("走不过去" in line for line in task.logs))
        self.assertLessEqual(sum(1 for move in task.moves if "d" in move or "w" in move), 4)


class ViewShiftTest(unittest.TestCase):
    def test_the_still_hud_does_not_hide_the_scene_moving(self):
        # 2K clone 11-18, PVP hub: a 0.08 s W tap moved the scene ~38 px
        # down; over the whole screen the HUD won (0.5 px), and every step
        # of the walk was written down as 「画面没动」.
        from src.utils.stage_walk import VIEW_MOVED_PIXELS, scene_offset, view_shift

        folder = Path(__file__).parent / "fixtures" / "pvp"
        before, after = (
            cv2.resize(cv2.imread(str(folder / f"hub_tap_w_{name}_2k_960.jpg")), (1920, 1080))
            for name in ("before", "after")
        )
        self.assertGreaterEqual(view_shift(before, after), VIEW_MOVED_PIXELS)
        dx, dy = scene_offset(before, after)
        self.assertGreater(dy, 20)  # walking up moves the scene down
        self.assertLess(abs(dx), 15)
        self.assertLess(view_shift(after, after), 2)
