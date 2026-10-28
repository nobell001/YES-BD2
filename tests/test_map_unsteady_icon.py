"""4K clone live 2026-10-28 (第13章主城区 华特波尔镇): 吸收 was bright and its
shape confirmed, but no two looks in a row agreed - its bright core read
0.852 against the 0.85 line between bright and the buffer, and the last
look's edge score 0.717 against the 0.72 shape line (``stable=False/3``) -
while its count read 0/21 steadily.  The map was left unpressed as
「吸收图标未达到跨帧稳定确认」 (v0.2.19 and the 10-28 batch alike); on a battle
map the same stopped 召集 and 压制 too.

Leo: bright = press, the game decides (10-15 「要以遊戲為主」), and a skill
is never left unpressed on a misread (10-28 「之前就有玩家明明還有次數 但工具
讀錯導致沒辦法跑圖」, 「除非你確定跑圖次數已經確實滿了」).  A bright icon that
does not hold still is pressed at its fixed slot, as a washed-out one is,
but whatever its count reads, and proven by the game as there (an exact +1,
the icon greying, its toast)."""

import unittest
from dataclasses import replace

from src.tasks.map_trade.action_icons import ActionIconState
from src.tasks.map_trade.collector_constants import (
    ABSORB_ACTION,
    BATTLE_ACTIONS,
    SUMMON_ACTION,
    SUPPRESS_ACTION,
)
from src.tasks.map_trade.models import CollectionMapRole
from tests.test_map_count_never_blocks import (
    AVAILABLE,
    CARD,
    USED,
    _battle_icons,
    _collector,
    _done_or_pending,
    _Game,
)

UNKNOWN = ActionIconState.UNKNOWN
ABSENT = ActionIconState.ABSENT
MAIN = CollectionMapRole.MAIN_AREA
BATTLE = CollectionMapRole.BATTLE_AREA_1
# The live looks in a row: brightness in the buffer, bright, shape not
# confirmed.
LIVE_LOOKS = (UNKNOWN, AVAILABLE, ABSENT)


class _Flicker(_Game):
    """``flicker`` icons read one of ``looks`` in turn, each look on its own,
    while their real state is ``real`` (once pressed they read as usual)."""

    def __init__(self, *args, flicker=("吸收",), looks=LIVE_LOOKS, real=AVAILABLE, **kwargs):
        super().__init__(*args, **kwargs)
        self.flicker = set(flicker)
        self.looks = tuple(looks)
        self.real = real
        self.look = 0
        self.clicks = []

    def detect(self, frame, icon):
        detection = super().detect(frame, icon)
        if icon.name not in self.flicker or detection.state is not self.real:
            return detection
        state = self.looks[self.look % len(self.looks)]
        self.look += 1
        return replace(
            detection,
            state=state,
            bright_core_ratio=0.852 if state is AVAILABLE else 0.83,
            stable=False,
            sample_count=1,
        )


def _run(game, actions, role):
    collector = _collector(game)
    # The bar was confirmed by its counts on that map (「以固定栏位次数确认技能栏」).
    collector._open_skill_menu = lambda *_a, **_k: True
    collector.vision.click_client = lambda point, _shape, **_k: game.clicks.append(point)
    result = collector._use_actions(actions, card_id=CARD, map_role=role)
    return collector, result


class UnsteadyBrightIconTest(unittest.TestCase):
    def test_the_live_absorb_is_pressed_at_its_slot_and_proven_by_the_count(self):
        game = _Flicker({"吸收": AVAILABLE}, {"吸收": [(0, 21), (0, 21), (1, 21)]}, {"吸收": True})
        collector, result = _run(game, (ABSORB_ACTION,), MAIN)
        self.assertEqual(["吸收"], game.presses)
        # 1080p: the face above 吸收's count, where the live icon was seen.
        self.assertEqual([(1531, 880)], game.clicks)
        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)
        self.assertTrue(_done_or_pending(collector, MAIN, ABSORB_ACTION))
        record = collector.progress.get_action_record(CARD, MAIN, ABSORB_ACTION.name)
        self.assertFalse(record["pending"])  # the +1 settled it

    def test_on_a_battle_map_summon_and_suppress_are_no_longer_held_back(self):
        game = _Flicker(
            _battle_icons(),
            {
                "吸收": [(0, 21), (0, 21), (1, 21)],
                "召集": [(3, 21), (4, 21)],
                "压制": [(6, 75), (7, 75)],
            },
            {"吸收": True, "召集": True, "压制": True},
        )
        collector, result = _run(game, BATTLE_ACTIONS, BATTLE)
        self.assertEqual(["吸收", "召集", "压制"], game.presses)
        self.assertTrue(result.completed)
        for action in BATTLE_ACTIONS:
            self.assertTrue(_done_or_pending(collector, BATTLE, action), action.name)

    def test_any_of_the_three_skills_flickering_is_pressed(self):
        for action, icon, reads in (
            (SUMMON_ACTION, "召集", [(3, 21), (3, 21), (4, 21)]),
            (SUPPRESS_ACTION, "制服", [(6, 75), (6, 75), (7, 75)]),
        ):
            with self.subTest(action.name):
                game = _Flicker(
                    {icon: AVAILABLE}, {action.name: reads}, {action.name: True}, flicker=(icon,)
                )
                _collector_, result = _run(game, (action,), BATTLE)
                self.assertEqual([action.name], game.presses)
                self.assertTrue(result.completed)

    def test_a_press_the_game_does_not_answer_is_pressed_once_more_as_usual(self):
        # No +1, no toast, still bright: the same as for a steady icon (Leo
        # 2026-10-13 「按東西沒反應一定要補按吧」), and never the day used up.
        game = _Flicker({"吸收": AVAILABLE}, {"吸收": [(0, 21)]}, {})
        _collector_, result = _run(game, (ABSORB_ACTION,), MAIN)
        self.assertEqual(["吸收", "吸收"], game.presses)
        self.assertEqual([(1531, 880), (1531, 880)], game.clicks)
        self.assertFalse(result.depleted)

    def test_a_count_that_does_not_read_steadily_does_not_stop_the_press(self):
        # The game's answer decides: the icon greys on the press.
        game = _Flicker({"吸收": AVAILABLE}, {"吸收": [None]}, {"吸收": True})
        collector, result = _run(game, (ABSORB_ACTION,), MAIN)
        self.assertEqual(["吸收"], game.presses)
        self.assertEqual([(1531, 880)], game.clicks)
        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)
        self.assertTrue(_done_or_pending(collector, MAIN, ABSORB_ACTION))


class UnsteadyIconNotPressedTest(unittest.TestCase):
    """Where it is still not pressed: the map is recorded done, or the icon
    was never seen bright."""

    def test_a_map_recorded_done_stays_done(self):
        game = _Flicker({"吸收": AVAILABLE}, {"吸收": [(5, 21)]}, {"吸收": True})
        collector = _collector(game)
        collector.progress.mark_action_seen_done(CARD, MAIN, ABSORB_ACTION.name)
        collector._open_skill_menu = lambda *_a, **_k: True
        result = collector._use_actions((ABSORB_ACTION,), card_id=CARD, map_role=MAIN)
        self.assertEqual([], game.presses)
        self.assertTrue(result.completed)

    def test_a_grey_icon_that_flickers_is_left_as_before(self):
        # Grey on and off (around the 0.78 line) is the dim after 探查 or a
        # used skill: it is not pressed, the next visit looks again.
        game = _Flicker(
            {"吸收": USED},
            {"吸收": [(0, 21)]},
            {"吸收": True},
            looks=(USED, UNKNOWN, ABSENT),
            real=USED,
        )
        _collector_, result = _run(game, (ABSORB_ACTION,), MAIN)
        self.assertEqual([], game.presses)
        self.assertFalse(result.completed)
        self.assertFalse(result.depleted)
        self.assertIn("吸收图标", result.message)
        self.assertNotIn("跨帧", result.message)


if __name__ == "__main__":
    unittest.main()
