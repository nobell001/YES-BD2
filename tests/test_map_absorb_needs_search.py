"""Player 2026-11-02, Leo 「要有探查在倒數才吸收」.

探查 ran on the first map and was still counting down when the second map
was reached, so it was not pressed again; it ended just before 吸收 was
pressed there and the items only 探查 shows were missed.  吸收 is now pressed
only with 探查's countdown live (at least ABSORB_MIN_SEARCH_SECONDS left);
otherwise 探查 is started again first.
"""

import unittest

from src.tasks.map_trade.action_icons import ActionIconState
from src.tasks.map_trade.collector_constants import BATTLE_ACTIONS, SkillExecutionResult
from src.tasks.map_trade import collector_skills
from src.tasks.map_trade.models import CollectionMapRole
from tests import test_map_trade_collector

ABSORB_MIN_SEARCH_SECONDS = getattr(collector_skills, "ABSORB_MIN_SEARCH_SECONDS", 3)

STATES = {
    "吸收": ActionIconState.AVAILABLE,
    "召集": ActionIconState.AVAILABLE,
    "制服": ActionIconState.AVAILABLE,
}
COUNTS = {
    "吸收": ((4, 21), (5, 21)),
    "召集": ((2, 21), (3, 21)),
    "压制": ((6, 60), (7, 60)),
}


class AbsorbNeedsSearchTest(unittest.TestCase):
    def _collector(self, seconds_left, *, search_starts=True):
        collector, clicks, _statuses, progress = test_map_trade_collector.CollectorSkillTest._skill_collector(
            STATES, COUNTS
        )
        looks = iter(seconds_left)
        last = [None]

        def left():
            last[0] = next(looks, last[0])
            return last[0]

        collector._search_seconds_left = left
        order = []
        collector.vision.click_client = (
            lambda center, shape, after_sleep=0, _c=clicks: order.append("click") or _c.append(center)
        )

        def ensure(**_kwargs):
            order.append("探查")
            if search_starts:
                last[0] = 240
                return None
            return SkillExecutionResult(False, message="游戏没有显示探查开始")

        collector._ensure_search = ensure
        self.progress = progress
        return collector, order

    def _run(self, collector):
        return collector._use_actions(
            BATTLE_ACTIONS, card_id="Q_sp1", map_role=CollectionMapRole.BATTLE_AREA_1
        )

    def test_a_long_countdown_presses_absorb_at_once(self):
        collector, order = self._collector([87])
        self.assertTrue(self._run(collector).completed)
        self.assertEqual(["click", "click", "click"], order)

    def test_a_countdown_about_to_end_is_waited_out_and_search_started_again(self):
        # Fails before the fix: 吸收 was pressed with 1 second left.
        collector, order = self._collector([ABSORB_MIN_SEARCH_SECONDS - 2, 1, None])
        self.assertTrue(self._run(collector).completed)
        self.assertEqual(["探查", "click", "click", "click"], order)

    def test_a_search_that_already_ended_is_started_again_first(self):
        collector, order = self._collector([None])
        self.assertTrue(self._run(collector).completed)
        self.assertEqual(["探查", "click", "click", "click"], order)

    def test_no_absorb_when_search_cannot_start_but_the_others_still_go(self):
        collector, order = self._collector([None], search_starts=False)
        result = self._run(collector)
        self.assertFalse(result.completed)
        self.assertFalse(result.depleted)
        self.assertIn("探查已经结束", result.message)
        # 召集 and 压制 only: 吸收 is never pressed without 探查.
        self.assertEqual(["探查", "click", "click"], order)
        record = self.progress.get_action_record(
            "Q_sp1", CollectionMapRole.BATTLE_AREA_1, "吸收"
        )
        self.assertNotIn(str((record or {}).get("state", "")), {"armed", "clicked", "local_done"})

    def test_a_small_misread_then_a_long_countdown_is_not_pressed_again(self):
        collector, order = self._collector([1, 200])
        self.assertTrue(self._run(collector).completed)
        self.assertEqual(["click", "click", "click"], order)


if __name__ == "__main__":
    unittest.main()
