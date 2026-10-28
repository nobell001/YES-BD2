"""Leo 2026-10-28: a skill count read never stops or skips 跑图 unless the
game agrees the uses are gone.

「但你不要讓這個去影響到跑圖 這個我說過很多次了 之前就有玩家明明還有次數 但工具
讀錯導致沒辦法跑圖」「除非你確定跑圖次數已經確實滿了」 (10-15 「要以遊戲為主」,
10-20 「以遊戲為準」).

Up to v0.2.19 the count alone decided in six places: an unread count left
the map's skill unpressed; a count read full with the icon bright, a full
read before 探查, a full read after a press, and a full read kept from
earlier in the day each ended the day's run.  Every test here fails on that
code.  The game agrees when a press on a full count is refused (twice when
nothing showed), or when 吸收 stays grey with 探查 running on a full count.
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import numpy as np

from src.tasks.map_trade.action_icons import ActionIconDetection, ActionIconState
from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.collector_constants import (
    ABSORB_ACTION,
    BATTLE_ACTIONS,
    SUMMON_ACTION,
    SUPPRESS_ACTION,
    SkillFeedbackObservation,
)
from src.tasks.map_trade.models import CollectionMapRole, MatchResult
from src.tasks.map_trade.progress import UTC_PLUS_8, ProgressStore

AVAILABLE = ActionIconState.AVAILABLE
USED = ActionIconState.USED
CARD = "Q_sp1"
NOTHING_TO_ABSORB = "周围没有可以吸收的拾取物"


class _Game:
    """One map of the game.  ``reads`` is what the tool reads for each
    skill's count, in order (the last repeats; None = unreadable), which may
    differ from the truth; ``again`` the same for the second way of reading
    (inside a border; as ``reads`` when not given); ``takes`` says whether
    the game takes a press.  ``refusal`` is the toast for a press not taken
    (one text, or one per skill); ``silent`` skills show no toast when taken;
    ``vanish`` skills' icons cannot be read after a press; ``dim`` is how many
    looks an icon reads grey before its real state (the bar dims after 探查)."""

    def __init__(
        self,
        icons,
        reads,
        takes,
        *,
        refusal=None,
        stays_bright=(),
        search=True,
        again=None,
        silent=(),
        vanish=(),
        dim=None,
    ):
        self.icons = {"探查": ActionIconState.ABSENT if search else AVAILABLE, **icons}
        self.reads = {name: list(values) for name, values in reads.items()}
        self.again = {name: list(values) for name, values in (again or {}).items()}
        self.takes = dict(takes)
        self.refusal = refusal
        self.stays_bright = set(stays_bright)
        self.silent = set(silent)
        self.vanish = set(vanish)
        self.dim = dict(dim or {})
        self.search = search
        self.presses = []

    def detect(self, _frame, icon):
        state = self.icons[icon.name]
        if self.dim.get(icon.name, 0) > 0:
            self.dim[icon.name] -= 1
            state = USED
        return ActionIconDetection(
            state,
            MatchResult(0.98, (100, 100), (40, 40), pixel_score=0.95, zncc_score=0.90),
            0.65 if state is USED else 1.0,
            stable=True,
            sample_count=2,
        )

    def read(self, name):
        values = self.reads[name]
        return values.pop(0) if len(values) > 1 else values[0]

    def read_again(self, name):
        if name not in self.again:
            return self.read(name)
        values = self.again[name]
        return values.pop(0) if len(values) > 1 else values[0]

    def press(self, action):
        """What the game shows after ``action`` was pressed."""
        self.presses.append(action.name)
        taken = bool(self.takes.get(action.name))
        if taken and action.name not in self.stays_bright:
            self.icons[action.icon.name] = USED
        if action.name in self.vanish:
            self.icons[action.icon.name] = ActionIconState.ABSENT
        if not taken:
            refusal = self.refusal
            if isinstance(refusal, dict):
                refusal = refusal.get(action.name)
            if refusal is not None:
                return SkillFeedbackObservation(refusal, "failure", 1.0, refusal)
            return SkillFeedbackObservation("", None, 0.0)
        if action.name in self.silent:
            return SkillFeedbackObservation("", None, 0.0)
        return SkillFeedbackObservation("成功", "success", 1.0)


def _collector(game, *, progress=None):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    statuses = []
    task = SimpleNamespace(
        config={},
        sleep=lambda *_a: None,
        log_info=lambda *_a: None,
        log_warning=lambda *_a: None,
        info_set=lambda key, value: statuses.append((key, value)),
    )
    vision = SimpleNamespace(
        capture=lambda: frame,
        ocr_text=lambda _f, name, **_k: "87" if name == "探查倒计时" and game.search else "",
        click_client=lambda *_a, **_k: None,
    )
    if progress is None:
        progress = ProgressStore(
            Path(tempfile.mkdtemp(prefix="ok-bd2-count-")) / "progress.json",
            lambda: datetime(2026, 10, 28, 12, tzinfo=UTC_PLUS_8),
        )
        progress.load()
    collector = Collector(task, vision, SimpleNamespace(), progress)
    collector.action_icons = SimpleNamespace(detect=game.detect)

    def read_count(action, *_a, **_k):
        value = game.read(action.name)
        collector._last_count_window_stable = value is not None
        return value

    collector._read_count_window = read_count
    collector._read_count_again = lambda action: game.read_again(action.name)
    collector._read_action_feedback = game.press
    collector.statuses = statuses
    return collector


def _battle_icons(state=AVAILABLE):
    return {"吸收": state, "召集": state, "制服": state}


class UnreadCountTest(unittest.TestCase):
    def test_unread_count_with_a_bright_icon_is_pressed(self):
        game = _Game({"吸收": AVAILABLE}, {"吸收": [None]}, {"吸收": True})
        result = _collector(game)._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        self.assertEqual(["吸收"], game.presses)
        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)

    def test_unread_counts_on_a_battle_map_press_all_three(self):
        game = _Game(
            _battle_icons(),
            {"吸收": [None], "召集": [None], "压制": [None]},
            {"吸收": True, "召集": True, "压制": True},
        )
        result = _collector(game)._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        self.assertEqual(["吸收", "召集", "压制"], game.presses)
        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)

    def test_unread_count_and_a_dropped_press_never_ends_the_day(self):
        game = _Game({"吸收": AVAILABLE}, {"吸收": [None]}, {"吸收": False})
        result = _collector(game)._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        # Pressed again once (Leo 2026-10-13); never "used up" from no count.
        self.assertEqual(["吸收", "吸收"], game.presses)
        self.assertFalse(result.depleted)


class FullReadBrightIconTest(unittest.TestCase):
    def test_full_read_the_game_takes_is_a_misread_and_the_map_goes_on(self):
        game = _Game(
            _battle_icons(),
            {"吸收": [(21, 21)], "召集": [(3, 21), (4, 21)], "压制": [(6, 75), (7, 75)]},
            {"吸收": True, "召集": True, "压制": True},
        )
        result = _collector(game)._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        self.assertEqual(["吸收", "召集", "压制"], game.presses)
        self.assertTrue(result.completed)
        # 21/21 before and after the press that took: not proven to be the
        # last use, the next map's icon and press tell.
        self.assertFalse(result.depleted)

    def test_full_read_the_game_refuses_twice_is_the_day_used_up(self):
        game = _Game(_battle_icons(), {"吸收": [(21, 21)]}, {})
        collector = _collector(game)
        result = collector._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        # Pressed alone, once more when nothing showed; 召集/压制 untouched
        # (Leo 2026-10-05 「不開新章」).
        self.assertEqual(["吸收", "吸收"], game.presses)
        self.assertFalse(result.completed)
        self.assertTrue(result.depleted)
        self.assertIn("次数用完了", result.message)
        record = collector.progress.get_action_record(
            CARD, CollectionMapRole.BATTLE_AREA_1, ABSORB_ACTION.name
        )
        # Not "已补按一次，不再检查": the map is not recorded done.
        self.assertNotIn(record["state"], {"local_done", "pending", "settled", "preexisting_used"})

    def test_a_full_misread_corrected_on_the_second_press_is_not_used_up(self):
        game = _Game(
            {"吸收": AVAILABLE}, {"吸收": [(21, 21), (21, 21), (20, 21), (20, 21)]}, {}
        )
        result = _collector(game)._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        self.assertEqual(["吸收", "吸收"], game.presses)
        self.assertFalse(result.depleted)

    def test_full_read_answered_with_nothing_to_absorb_goes_on_to_the_next_map(self):
        # The toast speaks of this map (nothing around to take), not of the
        # day's uses: neither done nor used up, and 召集/压制 are judged on
        # their own icons (Leo 2026-10-15 「就算沒資源能吸收 也要按壓制」).
        game = _Game(
            _battle_icons(),
            {"吸收": [(21, 21)], "召集": [(3, 21), (4, 21)], "压制": [(6, 75), (7, 75)]},
            {"召集": True, "压制": True},
            refusal=NOTHING_TO_ABSORB,
        )
        collector = _collector(game)
        result = collector._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        self.assertEqual(["吸收", "召集", "压制"], game.presses)
        self.assertFalse(result.completed)
        self.assertFalse(result.depleted)
        self.assertIn(NOTHING_TO_ABSORB, result.message)
        record = collector.progress.get_action_record(
            CARD, CollectionMapRole.BATTLE_AREA_1, ABSORB_ACTION.name
        )
        self.assertNotIn(record["state"], {"local_done", "pending", "settled", "preexisting_used"})

    def test_suppress_staying_bright_with_its_success_toast_is_taken(self):
        game = _Game(
            {"制服": AVAILABLE}, {"压制": [(75, 75)]}, {"压制": True}, stays_bright={"压制"}
        )
        result = _collector(game)._use_actions(
            (SUPPRESS_ACTION,), card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        self.assertEqual(["压制"], game.presses)
        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)

    def test_a_full_summon_read_does_not_hold_back_absorb(self):
        game = _Game(
            _battle_icons(),
            {"吸收": [(4, 21), (5, 21)], "召集": [(21, 21)], "压制": [(6, 75), (7, 75)]},
            {"吸收": True, "召集": True, "压制": True},
        )
        result = _collector(game)._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        self.assertEqual(["吸收", "召集", "压制"], game.presses)
        self.assertTrue(result.completed)


class AfterPressTest(unittest.TestCase):
    def test_the_press_that_takes_the_last_use_ends_the_day(self):
        game = _Game({"吸收": AVAILABLE}, {"吸收": [(20, 21), (21, 21)]}, {"吸收": True})
        result = _collector(game)._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        self.assertTrue(result.completed)
        self.assertTrue(result.depleted)

    def test_a_full_read_after_a_press_without_the_step_up_does_not(self):
        game = _Game({"吸收": AVAILABLE}, {"吸收": [None, (21, 21)]}, {"吸收": True})
        result = _collector(game)._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)

    def test_an_unproven_press_with_a_full_read_after_is_not_used_up(self):
        # 19/21 before, 21/21 after a press nothing else proves (one press
        # cannot add two): a map problem, the route goes on and the next
        # map tells.
        game = _Game({"召集": AVAILABLE}, {"召集": [(19, 21), (21, 21)]}, {})
        result = _collector(game)._use_actions(
            (SUMMON_ACTION,), card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        self.assertFalse(result.depleted)


class AbsorbUsedUpNeedsTheGameTest(unittest.TestCase):
    def _check(self, game):
        collector = _collector(game)
        return collector, collector._absorb_used_up(
            card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_2
        )

    def test_full_count_and_grey_absorb_with_search_on_stops_the_map(self):
        _collector_, result = self._check(_Game({"吸收": USED}, {"吸收": [(21, 21)]}, {}))
        self.assertFalse(result.completed)
        self.assertTrue(result.depleted)

    def test_full_count_with_a_bright_absorb_goes_on(self):
        _collector_, result = self._check(_Game({"吸收": AVAILABLE}, {"吸收": [(21, 21)]}, {}))
        self.assertIsNone(result)

    def test_full_count_before_search_goes_on_to_search(self):
        # Before 探查 every 吸收 reads grey: its look cannot tell yet.
        game = _Game({"吸收": USED}, {"吸收": [(21, 21)]}, {}, search=False)
        _collector_, result = self._check(game)
        self.assertIsNone(result)

    def test_grey_absorb_after_search_on_that_full_count_stops_before_any_press(self):
        game = _Game(_battle_icons(), {"吸收": [(21, 21)]}, {}, search=False)
        game.icons["吸收"] = USED
        collector = _collector(game)
        self.assertIsNone(
            collector._absorb_used_up(card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1)
        )
        game.search = True  # 探查 was pressed (_ensure_search)
        game.icons["探查"] = ActionIconState.ABSENT
        result = collector._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        self.assertEqual([], game.presses)
        self.assertFalse(result.completed)
        self.assertTrue(result.depleted)

    def test_grey_absorb_on_a_count_not_full_is_a_map_done_this_week(self):
        game = _Game({"吸收": USED}, {"吸收": [(12, 21)]}, {})
        collector = _collector(game)
        self.assertIsNone(
            collector._absorb_used_up(card_id=CARD, map_role=CollectionMapRole.MAIN_AREA)
        )
        result = collector._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)


class KeptCountTest(unittest.TestCase):
    def _store(self, temp_dir):
        store = ProgressStore(
            Path(temp_dir) / "progress.json",
            lambda: datetime(2026, 10, 28, 12, tzinfo=UTC_PLUS_8),
        )
        store.load()
        return store

    def test_a_full_read_alone_never_ends_the_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.reconcile_pending("吸收", (21, 21))
            store.reconcile_pending("吸收", (21, 21))
            self.assertFalse(store.state.depleted_today)
            self.assertFalse(store.game_used_up("吸收"))
            self.assertTrue(store.can_plan_collection(["a"]))
            # The game agreed (a refused press, grey 吸收 with 探查 on, or the
            # press that took the last use): now the day is used up.
            store.mark_depleted_today()
            self.assertTrue(store.game_used_up("吸收"))
            self.assertFalse(store.can_plan_collection(["a"]))

    def _run_start(self, *, agreed):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.state.game_counts["吸收"] = (21, 21)
            store.state.depleted_today = agreed
            store.save()
            entered = []

            def select(card_id, **_k):
                entered.append(card_id)
                raise RuntimeError("entered")

            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                log_warning=lambda *_a: None,
                log_error=lambda *_a: None,
                info_set=lambda *_a: None,
            )
            navigator = SimpleNamespace(select_collection_card=select)
            result = Collector(task, object(), navigator, store).run()
            return entered, result

    def test_a_full_read_kept_from_earlier_still_lets_the_run_in(self):
        entered, _result = self._run_start(agreed=False)
        self.assertEqual(1, len(entered))

    def test_a_day_the_game_agreed_is_used_up_starts_no_card(self):
        entered, result = self._run_start(agreed=True)
        self.assertEqual([], entered)
        self.assertTrue(result.depleted)


def _done_or_pending(collector, role, action):
    record = collector.progress.get_action_record(CARD, role, action.name)
    return record is not None and record["state"] in {
        "local_done",
        "pending",
        "settled",
        "preexisting_used",
    }


class CertainUsedUpTest(unittest.TestCase):
    """Audit 2026-10-28 of the rules above: grey 吸收 with 探查 on and a full
    count is the day's limit only when the count reads full again another
    way, the icon is still grey once the dim after 探查 passed, and the map
    is not one recorded done this week (it greys for that).  Each test fails
    on the code before this check (one look and one glance decided)."""

    def _grey_full(self, **game_args):
        game = _Game({"吸收": USED}, {"吸收": [(21, 21)]}, {}, **game_args)
        collector = _collector(game)
        first = collector._absorb_used_up(card_id=CARD, map_role=CollectionMapRole.MAIN_AREA)
        result = collector._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        return game, collector, first, result

    def test_a_second_look_reading_another_count_is_not_the_limit(self):
        game, collector, first, result = self._grey_full(again={"吸收": [(20, 21)]})
        self.assertIsNone(first)
        self.assertEqual([], game.presses)  # grey: the game says not now
        self.assertFalse(result.completed)
        self.assertFalse(result.depleted)
        self.assertIn("不能确定", result.message)
        # Not recorded done either: the next visit decides.
        self.assertFalse(_done_or_pending(collector, CollectionMapRole.MAIN_AREA, ABSORB_ACTION))

    def test_a_second_look_reading_nothing_is_not_the_limit(self):
        _game, _collector_, first, result = self._grey_full(again={"吸收": [None]})
        self.assertIsNone(first)
        self.assertFalse(result.depleted)
        self.assertIn("再读一次没读出来", result.message)

    def test_both_looks_full_with_the_icon_grey_is_the_limit(self):
        _game, _collector_, first, _result = self._grey_full()
        self.assertTrue(first.depleted)

    def test_a_map_done_this_week_greys_for_that_and_is_never_the_limit(self):
        game = _Game({"吸收": USED}, {"吸收": [(21, 21)]}, {})
        collector = _collector(game)
        collector.progress.state.cards[CARD] = [CollectionMapRole.MAIN_AREA.value]
        self.assertIsNone(
            collector._absorb_used_up(card_id=CARD, map_role=CollectionMapRole.MAIN_AREA)
        )
        result = collector._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)

    def test_a_grey_look_right_after_search_is_waited_out(self):
        # The bar dims for a moment after 探查 (live 2K 2026-10-01); a count
        # read full then is pressed, and the game took it.
        game = _Game({"吸收": AVAILABLE}, {"吸收": [(21, 21)]}, {"吸收": True}, dim={"吸收": 1})
        collector = _collector(game)
        collector._open_skill_menu = lambda *_a, **_k: True  # the bar's first look is the check's
        collector._search_pressed_at = monotonic()
        first = collector._absorb_used_up(card_id=CARD, map_role=CollectionMapRole.MAIN_AREA)
        self.assertIsNone(first)
        result = collector._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        self.assertEqual(["吸收"], game.presses)
        self.assertTrue(result.completed)
        self.assertFalse(result.depleted)


class FullReadPressNotProvenTest(unittest.TestCase):
    """A press on a count read full ends the day only when the game answered
    nothing at all, twice: still steadily bright, no toast, the count as
    before.  Anything else proves nothing either way: the map is reported,
    not recorded done, and the route goes on (it ended the day before)."""

    def test_an_icon_unreadable_after_the_press_goes_on_with_the_map(self):
        game = _Game(
            _battle_icons(),
            {"吸收": [(21, 21)], "召集": [(3, 21), (4, 21)], "压制": [(6, 75), (7, 75)]},
            {"召集": True, "压制": True},
            vanish={"吸收"},
        )
        collector = _collector(game)
        result = collector._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        # 召集 and 压制 judged on their own icons (Leo 2026-10-15).
        self.assertEqual(["吸收", "召集", "压制"], game.presses)
        self.assertFalse(result.depleted)
        role = CollectionMapRole.BATTLE_AREA_1
        self.assertFalse(_done_or_pending(collector, role, ABSORB_ACTION))
        self.assertTrue(_done_or_pending(collector, role, SUMMON_ACTION))
        self.assertTrue(_done_or_pending(collector, role, SUPPRESS_ACTION))

    def test_a_count_that_moved_is_not_a_press_the_game_ignored(self):
        # 21/21 then 20/21: one of the reads is wrong, so the count was not
        # "as before"; the press is not recorded done unproven either.
        game = _Game({"吸收": AVAILABLE}, {"吸收": [(21, 21), (20, 21)]}, {})
        collector = _collector(game)
        result = collector._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        self.assertFalse(result.depleted)
        self.assertFalse(_done_or_pending(collector, CollectionMapRole.MAIN_AREA, ABSORB_ACTION))

    def test_suppress_staying_bright_with_no_count_after_is_not_used_up(self):
        # 压制 stays bright after a press that took: without its count after
        # the press nothing says the game ignored it.
        game = _Game({"制服": AVAILABLE}, {"压制": [(75, 75), None]}, {})
        result = _collector(game)._use_actions(
            (SUPPRESS_ACTION,), card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        self.assertFalse(result.depleted)

    def test_a_washed_out_icon_grey_after_the_press_is_not_used_up(self):
        # The icon was never seen bright (pressed at its fixed slot): its grey
        # after the press may be the press or the limit.
        game = _Game(
            {"吸收": ActionIconState.ABSENT}, {"吸收": [(21, 21)]}, {"吸收": True}, silent={"吸收"}
        )
        collector = _collector(game)
        collector._open_skill_menu = lambda *_a, **_k: True  # the bar shown by its counts
        result = collector._use_actions(
            (ABSORB_ACTION,), card_id=CARD, map_role=CollectionMapRole.MAIN_AREA
        )
        self.assertEqual(["吸收"], game.presses)
        self.assertFalse(result.depleted)

    def test_a_later_skill_the_game_ignores_twice_after_absorb_failed_is_used_up(self):
        # 吸收 refused with this map's own toast, then 召集 (read full) got no
        # answer to two presses: that is 召集's day used up.
        game = _Game(
            _battle_icons(),
            {"吸收": [(21, 21)], "召集": [(21, 21)], "压制": [(6, 75)]},
            {},
            refusal={"吸收": NOTHING_TO_ABSORB},
        )
        result = _collector(game)._use_actions(
            BATTLE_ACTIONS, card_id=CARD, map_role=CollectionMapRole.BATTLE_AREA_1
        )
        self.assertEqual(2, game.presses.count("召集"))
        self.assertTrue(result.depleted)
        self.assertIn("召集", result.message)


class CountCutShortTest(unittest.TestCase):
    """A count whose last digits were lost ("2/2" for 2/21) looks full; it
    is read again inside a border once today's limit was seen on screen."""

    def test_a_limit_cut_short_of_the_one_seen_is_read_again(self):
        game = _Game({}, {}, {})
        collector = _collector(game)
        looks = []

        def ocr_text(_frame, _name, *, bordered=False, **_k):
            looks.append(bordered)
            return "2/21" if bordered else "2/2"

        collector.vision = SimpleNamespace(capture=lambda: None, ocr_text=ocr_text)
        collector._remember_limit(ABSORB_ACTION.name, 21)
        self.assertEqual((2, 21), collector._read_count(ABSORB_ACTION))
        self.assertEqual([False, True], looks)

    def test_a_limit_seen_earlier_today_counts_too(self):
        game = _Game({}, {}, {})
        collector = _collector(game)
        collector.progress.state.observed_limits[ABSORB_ACTION.name] = 21
        collector.vision = SimpleNamespace(
            capture=lambda: None,
            ocr_text=lambda _f, _n, *, bordered=False, **_k: "2/21" if bordered else "2/2",
        )
        self.assertEqual((2, 21), collector._read_count(ABSORB_ACTION))


class UsedUpMessageTest(unittest.TestCase):
    def test_the_end_message_names_what_the_game_showed_used_up(self):
        # It said 「已完成今日7张卡带，达到每日21次吸取上限」 whatever happened.
        collector = _collector(_Game({}, {}, {}))
        collector.progress.state.game_counts["召集"] = (19, 19)
        collector.progress.state.depleted_today = True
        message = collector._used_up_today()
        self.assertIn("召集", message)
        self.assertNotIn("吸收", message)
        self.assertNotIn("7张卡带", message)


if __name__ == "__main__":
    unittest.main()
