"""A field battle on screen before a 跑图 map step is run from first.

Player summary v0.3.20 2026-11-17 (1080p window, 4K 150%, no 桌面分身):
第14章 回主城失败 — the circle's hand, the minimap's area map and the ≡ menu
all failed, then 「跳过后回不到主页（当前页面没有已确认的安全返回路径）」 and the
rest of the daily was skipped.  The last frames (13 s to 7 s before) all show
a field battle standing at TURN.1 waiting for 「BATTLE」: a monster met the
character after a press had already counted as done.  Only the presses, the
walk waits and the general way home looked for a battle; 前往下一张图, 回主城
and the map pages' way home did not.  The run-away itself needed Esc, which
the game takes only while it is in front.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import cv2

from src.tasks.map_trade.models import CARD_BY_ID, NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.utils import field_battle
from tests.test_field_battle import FIELD, GAME_FLEE_DIALOG, GAME_MENU, IN_BATTLE_MANUAL, _boxes, _Clock, _Task

try:
    from tests.test_page_lookalikes import FIXTURES, ONNXPaddleOcr, load_pages, navigator_with_real_ocr
except ImportError:  # pragma: no cover
    ONNXPaddleOcr = None

PLAYER_BATTLE = "field/battle_turn1_player_summary_as_1080.jpg"
# Pages where a battle word in the bottom strip is right (a battle, its menu,
# its result, a dialog over one): the full look runs there and finds out.
BATTLE_PAGES = {"field_battle", "fiend_hunt", "battle_result", "server_error", "battle_pause_menu"}


class PauseButtonWhenEscCannotReachTest(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.patch = mock.patch("src.tasks.BaseBD2Task.monotonic", self.clock)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_game_not_in_front_pause_button_opens_the_menu(self):
        task = _Task([GAME_MENU, GAME_FLEE_DIALOG, FIELD], self.clock)
        task.tap_escape = lambda after_sleep=0.0: False
        self.assertEqual("left", task.leave_field_battle("跑图", _boxes(*IN_BATTLE_MANUAL)))
        pause = tuple(round(v, 3) for v in field_battle.PAUSE_RELATIVE_POINT)
        self.assertEqual(pause, task.clicks[0])
        self.assertEqual(3, len(task.clicks))  # pause, menu 逃跑, dialog 逃跑

    def test_esc_did_nothing_pause_button_once(self):
        battle = IN_BATTLE_MANUAL
        task = _Task([battle] * field_battle.ESC_PRESSES_MAX + [GAME_MENU, GAME_FLEE_DIALOG, FIELD], self.clock)
        self.assertEqual("left", task.leave_field_battle("跑图", _boxes(*battle)))
        self.assertEqual(field_battle.ESC_PRESSES_MAX, len(task.escapes))
        self.assertEqual(tuple(round(v, 3) for v in field_battle.PAUSE_RELATIVE_POINT), task.clicks[0])

    def test_still_no_menu_says_both_were_tried(self):
        task = _Task([IN_BATTLE_MANUAL], self.clock)
        task.tap_escape = lambda after_sleep=0.0: False
        why = task.leave_field_battle("跑图", _boxes(*IN_BATTLE_MANUAL))
        self.assertIn("游戏窗口不在最前面", why)
        self.assertIn("暂停键", why)
        self.assertEqual(1, len(task.clicks))  # the pause button only, once

    def test_open_menu_is_never_pressed_at_the_pause_spot(self):
        # 4 Escs, the menu showed but its 逃跑 unread: no press over it.
        task = _Task([("继续", "设置")], self.clock)
        task.leave_field_battle("跑图", _boxes(*IN_BATTLE_MANUAL))
        self.assertEqual([], task.clicks)


def _navigator(strip_names, leave_answer="left", escape=True):
    task = SimpleNamespace(FIELD_BATTLE_ESCAPE=escape, left=[])

    def leave(label, boxes=None):
        task.left.append(label)
        return leave_answer

    task.leave_field_battle = leave
    vision = SimpleNamespace(
        capture=lambda: None,
        ocr_boxes=lambda frame, name, relative_roi=None: _boxes(*strip_names),
    )
    navigator = object.__new__(Navigator)
    navigator.task, navigator.vision = task, vision
    navigator._status = lambda *_a: None
    return navigator


class LookBeforeMapStepTest(unittest.TestCase):
    def test_field_reads_no_battle_word_nothing_pressed(self):
        navigator = _navigator(("吸收", "召集", "压制", "探查"))
        self.assertIsNone(navigator.leave_field_battle_first("回主城"))
        self.assertEqual([], navigator.task.left)

    def test_battle_is_run_from_then_the_step_goes_on(self):
        navigator = _navigator(("更换", "预设", "TURN.1", "BATTLE"))
        self.assertIsNone(navigator.leave_field_battle_first("回主城"))
        self.assertEqual(["跑图回主城"], navigator.task.left)

    def test_battle_not_left_fails_the_step_saying_why(self):
        navigator = _navigator(("TURN.1", "BATTLE"), leave_answer="按了4次 Esc，都没看到「逃跑」")
        result = navigator.leave_field_battle_first("回主城")
        self.assertFalse(result.success)
        self.assertIn("撞到怪进了战斗", result.message)
        self.assertIn("逃跑", result.message)

    def test_flee_before_next_map_stops_the_step(self):
        navigator = _navigator(("TURN.1", "BATTLE"))
        result = navigator.leave_field_battle_first("前往下一张图", stop_after_flee=True)
        self.assertFalse(result.success)
        self.assertTrue(result.fled_battle)

    def test_result_screen_closed_is_no_flee(self):
        navigator = _navigator(("VICTORY", "REWARD", "离开"))

        def leave(label, boxes=None):
            navigator.task.field_battle_ended_by_result = True
            return "left"

        navigator.task.leave_field_battle = leave
        self.assertIsNone(navigator.leave_field_battle_first("前往下一张图", stop_after_flee=True))
        self.assertEqual(0, getattr(navigator, "fled_battles", 0))

    def test_other_tasks_never_look(self):
        navigator = _navigator(("TURN.1", "BATTLE"), escape=False)
        self.assertIsNone(navigator.leave_field_battle_first("回主页"))
        self.assertEqual([], navigator.task.left)

    def test_every_map_step_looks_first(self):
        failed = NavigationResult(False, ScreenState.UNKNOWN, "撞到怪进了战斗，x")
        card = CARD_BY_ID["Q_sp14"]
        for name, call in (
            ("回主城", lambda nav: nav.prepare_collection_main_area("Q_sp14", via_hunting_ground=True)),
            ("前往下一张图", lambda nav: nav.advance_collection_map("Q_sp14", card.targets[0], card.targets[1])),
            ("回主页", lambda nav: nav._return_home_pass()),
        ):
            with self.subTest(step=name):
                navigator = _navigator(())
                seen = []
                navigator.leave_field_battle_first = lambda step, **_k: seen.append(step) or failed
                self.assertIs(failed, call(navigator))
                self.assertEqual([name], seen)


class BattleInsideTheStepTest(unittest.TestCase):
    """Live 2K 2026-11-18 (PR #574, 第8章): caught on the walk to the
    circle, run from, caught again 8 s later; 回主城 then tried ≡ and pressed
    the minimap spot on the battle screen."""

    def test_nav_menu_runs_from_a_battle_before_the_button(self):
        navigator = _navigator(())
        clicks = []
        navigator.vision.click_template = lambda *_a, **_k: clicks.append(1) or True
        navigator.leave_field_battle_first = lambda step, **_k: NavigationResult(
            False, ScreenState.UNKNOWN, "撞到怪进了战斗，按了4次 Esc，都没看到「逃跑」"
        )
        self.assertFalse(navigator._open_minimap_nav_menu())
        self.assertEqual([], clicks)
        self.assertIn("撞到怪进了战斗", navigator._nav_button_miss)

    def test_walk_to_circle_runs_from_a_battle_before_the_minimap(self):
        navigator = _navigator(())
        opened = []
        navigator._open_field_map = lambda *_a, **_k: opened.append(1)
        failed = NavigationResult(False, ScreenState.UNKNOWN, "撞到怪进了战斗，x")
        navigator.leave_field_battle_first = lambda step, **_k: failed
        self.assertIs(failed, navigator._walk_to_sandbox_teleport_interaction())
        self.assertEqual([], opened)

    def test_battle_begun_as_the_map_opened_is_run_from_then_the_map_reopened(self):
        navigator = _navigator(())
        opens, second_entry = [], []
        navigator._open_field_map = lambda: opens.append(1) or None
        navigator._click_sandbox_navigation_map = lambda: second_entry.append(1) or False
        looks = iter([None, None])

        def look(step, **_k):
            answer = next(looks)
            if len(opens) == 1:
                navigator.fled_battles = getattr(navigator, "fled_battles", 0) + 1
            return answer

        navigator.leave_field_battle_first = look
        navigator._walk_to_sandbox_teleport_interaction()
        # Run from after the first open, the map opened again before the
        # second entry was tried.
        self.assertEqual(2, len(opens))
        self.assertEqual(1, len(second_entry))

    def test_move_failed_after_a_flee_on_the_way_asks_to_clear_the_map(self):
        card = CARD_BY_ID["Q_sp14"]
        for fled, success in ((True, False), (False, False), (True, True)):
            with self.subTest(fled=fled, success=success):
                navigator = _navigator(())

                def inner(*_a, fled=fled, success=success, nav=navigator):
                    if fled:
                        nav.fled_battles = getattr(nav, "fled_battles", 0) + 1
                    return NavigationResult(success, ScreenState.SANDBOX, "x")

                navigator._advance_collection_map = inner
                result = navigator.advance_collection_map("Q_sp14", card.targets[1], card.targets[2])
                self.assertEqual(success, result.success)
                self.assertEqual(fled and not success, result.fled_battle)


class ClearMapAfterFleeTest(unittest.TestCase):
    """Leo 2026-11-18 「撞怪後 逃跑 然後清怪」: a battle met as the run leaves
    a map is run from, that map is done again 压制 first, then the route
    goes on."""

    def test_flee_before_next_map_clears_this_map_first(self):
        import tempfile
        from datetime import datetime
        from pathlib import Path

        from src.tasks.map_trade.card_status import (
            CollectionCardSelectionOutcome,
            CollectionCardSelectionResult,
        )
        from src.tasks.map_trade.collector import AFTER_ESCAPE_ACTIONS, Collector
        from src.tasks.map_trade.collector_constants import (
            BATTLE_ACTIONS,
            SearchCountdownSession,
            SkillExecutionResult,
        )
        from src.tasks.map_trade.progress import UTC_PLUS_8, ProgressStore
        from tests.helpers.map_trade import _seed_action_records

        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8),
            )
            progress.load()
            progress.state.daily_submaps = 18
            progress.state.daily_summons = 12
            progress.state.daily_suppressions = 12
            progress.state.game_counts["吸收"] = (18, 21)
            progress.save()
            events = []
            absorbed = [18]
            where = {"key": None}
            fled = [False]
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                log_warning=lambda *_a: None,
                info_set=lambda *_a: None,
                leave_field_battle=lambda label: "none",
            )

            def advance(card_id, current, target):
                if target.key == "battle_area_2" and not fled[0]:
                    # A monster met on the way out of 战斗区域1.
                    fled[0] = True
                    where["key"] = "battle_area_1"
                    events.append(("fled",))
                    return NavigationResult(
                        False, ScreenState.SANDBOX, "撞到怪进了战斗，已逃跑", fled_battle=True
                    )
                events.append(("advance", target.key))
                where["key"] = target.key
                return NavigationResult(True, ScreenState.SANDBOX)

            navigator = SimpleNamespace(
                select_collection_card=lambda card_id, **_k: (
                    events.append(("select", card_id))
                    or CollectionCardSelectionResult(
                        CollectionCardSelectionOutcome.ENTERED,
                        NavigationResult(True, ScreenState.SANDBOX),
                    )
                ),
                current_collection_target=lambda _card: where["key"],
                prepare_collection_main_area=lambda card_id, **_k: NavigationResult(True, ScreenState.SANDBOX),
                advance_collection_map=advance,
                open_story_quick_switcher_from_sandbox=lambda **_k: NavigationResult(True, ScreenState.CARD_MENU),
                inspect_collection_card_completion=lambda card_id: CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                    NavigationResult(True, ScreenState.CARD_MENU),
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            started = SearchCountdownSession((0.1, 0.2, 0.3, 0.4), 87)
            collector._absorb_used_up = lambda **_k: None
            collector._ensure_search = lambda **_k: started
            collector._verify_search_countdown = lambda _value: True

            def use_actions(actions, *, card_id, map_role):
                events.append(("actions", map_role.value, actions[0].name))
                _seed_action_records(progress, card_id, map_role.value)
                absorbed[0] += 1
                progress.reconcile_pending("吸收", (absorbed[0], 21))
                return SkillExecutionResult(True, absorbed[0] >= 21)

            collector._use_actions = use_actions
            result = collector.run()

        self.assertTrue(result.success, result.message)
        first = BATTLE_ACTIONS[0].name
        self.assertEqual(
            [
                ("select", "Q_sp1"),
                ("actions", "main_area", first),
                ("advance", "battle_area_1"),
                ("actions", "battle_area_1", first),
                ("fled",),
                # 压制 first on the map it was met on, then on as planned.
                ("actions", "battle_area_1", AFTER_ESCAPE_ACTIONS[0].name),
                ("advance", "battle_area_2"),
                ("actions", "battle_area_2", first),
            ],
            events,
        )


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class PlayerBattleFrameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.navigator = navigator_with_real_ocr()

    def frame(self, path):
        image = cv2.imread(str(FIXTURES / path))
        self.assertIsNotNone(image, path)
        if image.shape[1] != 1920:
            shrink = image.shape[1] > 1920
            image = cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA if shrink else cv2.INTER_CUBIC)
        return image

    def strip(self, frame):
        return self.navigator.vision.ocr_boxes(
            frame, "野外战斗底栏", relative_roi=field_battle.BOTTOM_STRIP_RELATIVE_ROI
        )

    def test_player_battle_is_seen(self):
        frame = self.frame(PLAYER_BATTLE)
        self.assertTrue(field_battle.bottom_strip_cue(self.strip(frame)))
        self.assertTrue(field_battle.in_battle(self.navigator.task.ocr(frame=frame)))
        # Not the field: the circle's hand, the minimap and ≡ cannot work here.
        self.assertEqual(ScreenState.UNKNOWN, self.navigator.classify(frame))

    def test_no_battle_word_on_any_other_page(self):
        for path, page in load_pages().items():
            if page in BATTLE_PAGES:
                continue
            with self.subTest(picture=path, page=page):
                self.assertFalse(field_battle.bottom_strip_cue(self.strip(self.frame(path))))


if __name__ == "__main__":
    unittest.main()
