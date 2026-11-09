"""跑图: one collection icon not recognised no longer stops the other two.

A player's run (2560x1440, 2026-11-09, Q_sp1 战斗区域1/2, 问题摘要 photo)
logged on every battle map:

    地图采集：技能栏部分识别但未确认，不执行技能组1回退：吸收=available,
    召集=available, 制服=absent。
    地图采集：第1章战斗区域2技能操作失败：未确认采集技能栏，继续下一张图。

探查 ran (its own check needs only 吸收), but 吸收 and 召集, both seen bright
in their slots, were never pressed because 压制's icon was not taken: a
third of each card done.  The same stop came on 2026-10-11 with 召集=absent.

Now two collection icons seen (or one plus a readable count) prove the bar;
each skill goes by its own icon, the unseen one is pressed at its fixed slot
and the game's answer decides.  An action that cannot be prepared no longer
stops the map's others either; only a day the game showed used up does.
Four of these fail on bd2-auto-dev 2abb8c1 (the others guard what stays).
"""

import unittest
from dataclasses import replace
from types import SimpleNamespace

from src.tasks.map_trade.action_icons import (
    ABSORB_ICON,
    SUBDUE_ICON,
    SUMMON_ICON,
    ActionIconState,
)
from src.tasks.map_trade.collector_constants import BATTLE_ACTIONS, SkillExecutionResult
from src.tasks.map_trade.models import CollectionMapRole
from src.tasks.map_trade.skill_layout import SkillLayoutWrong
from src.utils.ocr_count import CountRead
from tests.test_map_count_never_blocks import AVAILABLE, CARD, _collector, _Game

ABSENT = ActionIconState.ABSENT
BATTLE = CollectionMapRole.BATTLE_AREA_1
BAR = (ABSORB_ICON, SUMMON_ICON, SUBDUE_ICON)
PLAYER_ICONS = {"吸收": AVAILABLE, "召集": AVAILABLE, "制服": ABSENT}


def _player_collector(reads):
    game = _Game(
        dict(PLAYER_ICONS),
        reads,
        {"吸收": True, "召集": True, "压制": True},
    )
    collector = _collector(game)
    collector._skill_layout_checked = True
    collector._read_count = lambda action, *_a, **_k: game.read(action.name)
    collector.task.operate_click = lambda *_a, **_k: game.presses.append("技能组")
    return game, collector


class PartialBarTest(unittest.TestCase):
    def test_the_players_bar_is_confirmed(self):
        _game, collector = _player_collector({"吸收": [None], "召集": [None], "压制": [None]})
        self.assertTrue(collector._open_skill_menu(BAR, allow_group_one_recovery=True))
        self.assertEqual(frozenset({"制服"}), collector._menu_missing_icons)

    def test_the_players_battle_map_presses_all_three(self):
        game, collector = _player_collector(
            {"吸收": [(7, 21), (8, 21)], "召集": [(1, 21), (2, 21)], "压制": [(0, 30), (1, 30)]}
        )
        clicks = []
        collector.vision.click_client = lambda point, _shape, **_k: clicks.append(point)
        result = collector._use_actions(BATTLE_ACTIONS, card_id=CARD, map_role=BATTLE)
        self.assertEqual(["吸收", "召集", "压制"], game.presses)
        self.assertTrue(result.completed, result.message)
        self.assertNotIn("技能组", game.presses)  # no group switch

    def test_suppress_unseen_with_digits_under_it_is_pressed_at_its_slot(self):
        # The count shows but does not read as one (「0/3O」): still a number.
        game, collector = _player_collector({"吸收": [None], "召集": [None], "压制": [None]})

        def read(action, *_a, **_k):
            collector._last_count_read = CountRead(None, ("0/3O",) if action.name == "压制" else ())
            return None

        collector._read_count = read
        collector._use_actions(BATTLE_ACTIONS, card_id=CARD, map_role=BATTLE)
        self.assertEqual(["吸收", "召集", "压制"], game.presses)

    def test_suppress_unseen_with_no_number_under_it_stops_and_says_how_to_set_it(self):
        # Leo 2026-11-09 「沒數字 代表根本不是 吸收召集壓制這三個」「玩家根本設定錯
        # 那程式也要停下來 然後說玩家設定錯 應該設定成怎麼樣 然後重試」.
        game, collector = _player_collector({"吸收": [None], "召集": [None], "压制": [None]})
        with self.assertRaises(SkillLayoutWrong) as caught:
            collector._use_actions(BATTLE_ACTIONS, card_id=CARD, map_role=BATTLE)
        self.assertNotIn("压制", game.presses)
        self.assertIn("第4格不是压制", str(caught.exception))
        self.assertIn("探查、吸收、召集、压制", str(caught.exception))

    def test_one_icon_alone_without_any_count_is_not_enough(self):
        game = _Game(
            {"吸收": AVAILABLE, "召集": ABSENT, "制服": ABSENT},
            {"吸收": [None], "召集": [None], "压制": [None]},
            {},
        )
        collector = _collector(game)
        collector._read_count = lambda action, *_a, **_k: None
        self.assertFalse(collector._open_skill_menu(BAR))

    def test_one_icon_with_a_readable_count_is_enough(self):
        game = _Game(
            {"吸收": AVAILABLE, "召集": ABSENT, "制服": ABSENT},
            {"吸收": [(3, 21)], "召集": [None], "压制": [None]},
            {},
        )
        collector = _collector(game)
        collector._skill_layout_checked = True
        collector._read_count = lambda action, *_a, **_k: game.read(action.name)
        self.assertTrue(collector._open_skill_menu(BAR))
        self.assertEqual(frozenset({"召集", "制服"}), collector._menu_missing_icons)


class OneSkillDoesNotStopTheOthersTest(unittest.TestCase):
    def _run(self, early):
        game = _Game(
            {"吸收": AVAILABLE, "召集": AVAILABLE, "制服": AVAILABLE},
            {"吸收": [(1, 21)], "召集": [(1, 21), (2, 21)], "压制": [(1, 80), (2, 80)]},
            {"召集": True, "压制": True},
        )
        collector = _collector(game)
        real = collector._prepare_action

        def prepare(action, **kwargs):
            if action.name == "吸收":
                return early, None
            return real(action, **kwargs)

        collector._prepare_action = prepare
        collector._open_skill_menu = lambda *_a, **_k: True
        result = collector._use_actions(BATTLE_ACTIONS, card_id=CARD, map_role=BATTLE)
        return game, result

    def test_absorb_not_pressable_still_presses_summon_and_suppress(self):
        game, result = self._run(SkillExecutionResult(False, message="未识别到吸收图标"))
        self.assertEqual(["召集", "压制"], game.presses)
        self.assertFalse(result.completed)  # 吸收 is still reported
        self.assertIn("吸收", result.message)

    def test_a_day_used_up_still_holds_the_others_back(self):
        game, result = self._run(SkillExecutionResult(False, True, "吸收今日已用完"))
        self.assertEqual([], game.presses)
        self.assertTrue(result.depleted)


class ProvenPointTest(unittest.TestCase):
    """Leo 2026-11-09 「有成功了 後面就不用再檢查 就點那個位置」, but only with a
    number under the skill (「沒數字 代表根本不是 吸收召集壓制這三個」)."""

    def _two_maps(self, number_on_second_map):
        game = _Game(
            {"吸收": AVAILABLE, "召集": AVAILABLE, "制服": AVAILABLE},
            {"吸收": [(1, 21), (2, 21)], "召集": [(1, 21), (2, 21)], "压制": [(1, 30), (2, 30)]},
            {"吸收": True, "召集": True, "压制": True},
        )
        collector = _collector(game)
        collector._skill_layout_checked = True
        numbers = [True]
        collector._read_count = lambda action, *_a, **_k: (1, 21) if numbers[0] else None
        collector.task.operate_click = lambda *_a, **_k: game.presses.append("技能组")
        clicks = []
        collector.vision.click_client = lambda point, _shape, **_k: clicks.append(point)
        first = collector._use_actions(BATTLE_ACTIONS, card_id=CARD, map_role=BATTLE)
        self.assertTrue(first.completed, first.message)
        first_clicks = list(clicks)
        # Next map: the matcher takes none of the three.
        game.icons.update({"吸收": ABSENT, "召集": ABSENT, "制服": ABSENT})
        game.presses.clear()
        clicks.clear()
        numbers[0] = number_on_second_map
        collector._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_2
        )
        return game, first_clicks, clicks

    def test_pressed_at_the_points_that_worked(self):
        game, first_clicks, clicks = self._two_maps(number_on_second_map=True)
        self.assertEqual(["吸收", "召集", "压制"], game.presses)
        self.assertEqual(first_clicks, clicks)

    def test_no_number_under_the_skills_is_not_pressed_blind(self):
        game, _first, clicks = self._two_maps(number_on_second_map=False)
        self.assertNotIn("压制", game.presses)
        self.assertEqual([], clicks)



class WrongPageAfterBlindPressTest(unittest.TestCase):
    """Live 4K 2026-11-09 (before the number rule): a potion skill in slot 4
    was pressed as 压制 and opened 炼金术.  Should a blind press ever open a
    page again: Esc, report the slot, never press it blind again this run."""

    def test_escape_report_and_never_again(self):
        game, collector = _player_collector({"吸收": [None], "召集": [None], "压制": [None]})

        def read(action, *_a, **_k):
            collector._last_count_read = CountRead(None, ("12",) if action.name == "压制" else ())
            return None

        collector._read_count = read
        escapes = []
        collector.task.tap_escape = lambda **_k: escapes.append(1) or True
        real_press = game.press

        def press(action):
            feedback = real_press(action)
            if action.name == "压制":  # a page covers the whole field
                game.icons.update({"吸收": ABSENT, "召集": ABSENT, "制服": ABSENT, "探查": ABSENT})
            return feedback

        collector._read_action_feedback = press
        result = collector._use_actions(BATTLE_ACTIONS, card_id=CARD, map_role=BATTLE)
        self.assertEqual([1], escapes)
        self.assertFalse(result.completed)
        self.assertIn("第4格按下去打开了别的页面", result.message)
        self.assertIn("压制", collector._bad_slots)
        # The next map: 压制 still unseen with digits under it, not pressed.
        game.icons.update({"吸收": AVAILABLE, "召集": AVAILABLE, "探查": AVAILABLE})
        game.presses.clear()
        collector._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_2
        )
        self.assertNotIn("压制", game.presses)



class SkillInAnotherSlotTest(unittest.TestCase):
    """Leo 2026-11-09 (option A): 「1～5 格都找，找到就在那格按」; stop only
    when a skill is found nowhere."""

    def test_placement_rules(self):
        from src.tasks.map_trade import skill_layout

        # Live 4K test: a potion skill in slot 4, 压制 in slot 5.
        five = {1: "探查", 2: "吸收", 3: "召集", 4: None, 5: "压制"}
        self.assertEqual(({"压制": "teleport"}, []), skill_layout.placement([five, five]))
        # 召集 and 压制 swapped: both pressed where they are.
        swapped = {1: "探查", 2: "吸收", 3: "压制", 4: "召集", 5: None}
        self.assertEqual(
            ({"压制": "summon", "召集": "subdue"}, []), skill_layout.placement([swapped, swapped])
        )
        # 压制 in 召集's slot and 召集 nowhere: stop, 召集 is missing.
        lost = {1: "探查", 2: "吸收", 3: "压制", 4: None, 5: None}
        moved, wrong = skill_layout.placement([lost, lost])
        self.assertEqual([(3, "压制", "召集")], wrong)
        # Seen in another slot on one look only: not moved.
        self.assertEqual(({}, []), skill_layout.placement([five, {**five, 5: None}]))

    def test_count_box_moves_with_the_icon(self):
        from src.tasks.map_trade import skill_layout
        from src.tasks.map_trade.collector_constants import SUPPRESS_ACTION

        home = SUPPRESS_ACTION.fixed_count_relative_roi
        moved = skill_layout.count_roi_at(home, "压制", "teleport")
        # slot 5 centre is (1795, 788) against 压制's (1682, 729) at 1080p.
        self.assertAlmostEqual((1795 - 1682) / 1920, moved[0] - home[0])
        self.assertAlmostEqual((788 - 729) / 1080, moved[1] - home[1])

    def test_suppress_in_slot_five_is_pressed_there(self):
        game = _Game(
            {"吸收": AVAILABLE, "召集": AVAILABLE, "制服": ABSENT},
            {"吸收": [None], "召集": [None], "压制": [None]},
            {"吸收": True, "召集": True, "压制": True},
        )
        real_detect = game.detect

        def detect(frame, icon):
            if icon.name == "制服":
                state = game.icons["制服@5"] if icon.slot_name == "teleport" else ABSENT
                return replace(real_detect(frame, icon), state=state)
            return real_detect(frame, icon)

        game.icons["制服@5"] = AVAILABLE
        real_press = game.press

        def press(action):
            feedback = real_press(action)
            if action.name == "压制":
                game.icons["制服@5"] = ActionIconState.USED
            return feedback

        collector = _collector(game)
        collector._skill_layout_checked = True
        collector.action_icons = SimpleNamespace(detect=detect)
        collector._read_count = lambda action, *_a, **_k: None
        collector._read_action_feedback = press
        result = collector._use_actions(BATTLE_ACTIONS, card_id=CARD, map_role=BATTLE)
        self.assertEqual(["吸收", "召集", "压制"], game.presses)
        self.assertEqual({"压制": "teleport"}, collector._placement)
        self.assertTrue(result.completed, result.message)


class TwSuppressToastTest(unittest.TestCase):
    def test_tw_toast_is_a_success(self):
        from src.tasks.map_trade.collector_constants import ACTION_SUCCESS_FEEDBACK

        # live 4K 繁中 2026-11-09 「已消滅地圖內所有怪獸」, read simplified.
        self.assertIn("已消灭地图内所有怪兽", ACTION_SUCCESS_FEEDBACK["压制"])



class CountUpUnderAnotherToastTest(unittest.TestCase):
    def test_absorb_count_up_by_one_is_success_with_the_search_toast_showing(self):
        # Live 4K 2026-11-09: 吸收 6/21 -> 7/21, the toast area still showing
        # 探查's line, the icon not read after the press.
        from src.tasks.map_trade.collector_constants import ABSORB_ACTION, SkillFeedbackObservation
        from src.tasks.map_trade.action_icons import ActionIconDetection
        from src.utils.vision_models import MatchResult

        game = _Game({"吸收": AVAILABLE}, {"吸收": [(7, 21)]}, {})
        collector = _collector(game)

        def one_read(action, *_a, **_k):
            collector._last_count_window_stable = False
            return (7, 21)

        collector._read_count_window = one_read
        bright = ActionIconDetection(
            AVAILABLE, MatchResult(0.98, (1, 1), (5, 5)), stable=True
        )
        unread = ActionIconDetection(ABSENT, MatchResult(-1.0, (0, 0), (0, 0)))
        result = collector._finish_after_click(
            ABSORB_ACTION,
            card_id=CARD,
            map_role=BATTLE,
            before=(6, 21),
            detection=bright,
            post_detection=unread,
            feedback=SkillFeedbackObservation("在240秒内确认隐藏物品的位置", None, 0.2),
        )
        self.assertTrue(result.completed, result.message)


if __name__ == "__main__":
    unittest.main()
