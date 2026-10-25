"""YES-BD2 #23 (1080p windowed, 225%): weekly map runs stopped after a card.

1. The quick-switch click went in but the page never opened, and nothing else
   was tried; now the P key gets its turn while the field key caps show.
2. The game added a pause after each skill, so 召集 pressed right after 吸收
   was dropped and 压制 went before it; now the next skill waits until the
   last one reads grey, and a still-bright one is pressed again first.
"""

import unittest
from types import SimpleNamespace

import numpy as np

from src.tasks.map_trade.action_icons import ActionIconDetection, ActionIconState
from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.collector_constants import (
    ABSORB_ACTION,
    SUMMON_ACTION,
    SUPPRESS_ACTION,
    SkillFeedbackObservation,
)
from src.tasks.map_trade.collector_skills import PRESS_TAKEN_POLL_SECONDS
from src.tasks.map_trade.models import MatchResult, NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_story import (
    FIELD_QUICK_SWITCH_KEY,
    FIELD_QUICK_SWITCH_KEY_PRESSES,
)


def _navigator(*, button_seen=True, keycaps=True, pages=()):
    """``pages``: what each quick-switch page check after a press reads."""
    keys = []
    page_reads = iter(pages)
    vision = SimpleNamespace(
        click_stable_template=lambda *_a, **_k: button_seen,
        capture=lambda: "frame",
        match=lambda _frame, spec: spec,
        passes=lambda _match, _spec: keycaps,
        click_reference=lambda *_a, **_k: None,
    )
    task = SimpleNamespace(
        operate_click=lambda *_a, **_k: None,
        tap_key=lambda key, after_sleep=0.0: keys.append(key) or True,
    )
    navigator = Navigator(task, vision)
    navigator._status = lambda *_a: None
    navigator._wait_for_current_sandbox = lambda: NavigationResult(True, ScreenState.SANDBOX)
    navigator._wait_for_quick_switch_page = lambda **_k: next(page_reads, False)
    navigator._select_story_category = lambda _category: True
    navigator.classify = lambda: ScreenState.UNKNOWN
    return navigator, keys


class FieldQuickSwitchKeyTest(unittest.TestCase):
    def test_click_that_opened_nothing_falls_back_to_p(self):
        navigator, keys = _navigator(pages=(False, True))

        result = navigator.open_story_quick_switcher_from_sandbox()

        self.assertTrue(result.success, result.message)
        self.assertEqual([FIELD_QUICK_SWITCH_KEY], keys)

    def test_p_is_pressed_twice_at_most(self):
        navigator, keys = _navigator(pages=())

        result = navigator.open_story_quick_switcher_from_sandbox()

        self.assertFalse(result.success)
        self.assertEqual("点击快速切换按钮后未确认卡带选择页", result.message)
        self.assertEqual([FIELD_QUICK_SWITCH_KEY] * FIELD_QUICK_SWITCH_KEY_PRESSES, keys)

    def test_no_p_without_the_field_key_caps(self):
        # On 主页 P opens the collection instead.
        navigator, keys = _navigator(keycaps=False, pages=())

        result = navigator.open_story_quick_switcher_from_sandbox()

        self.assertFalse(result.success)
        self.assertEqual([], keys)

    def test_unseen_button_also_tries_p(self):
        # Leo 2026-10-13 「p如果還沒按到 也可以點快捷鍵」.
        navigator, keys = _navigator(button_seen=False, pages=(True,))
        navigator._click_quick_switch = lambda *_a, **_k: False

        result = navigator.open_story_quick_switcher_from_sandbox()

        self.assertTrue(result.success, result.message)
        self.assertEqual([FIELD_QUICK_SWITCH_KEY], keys)


class HomeQuickSwitchKeyTest(unittest.TestCase):
    def test_press_without_the_page_hands_over_to_the_keys(self):
        from src.tasks.BaseBD2Task import BaseBD2Task, CartridgeSpecialPageResult

        handed = []
        task = SimpleNamespace(
            _recent_cartridge_is_pvp=lambda: False,
            _sleep_after_recognition=lambda: None,
            info_set=lambda *_a: None,
            operate_click=lambda *_a, **_k: None,
            _handle_recent_cartridge_special_pages=lambda **_k: CartridgeSpecialPageResult.ABSENT,
            _quick_switch_by_key=lambda *_a, **_k: handed.append(True) or True,
        )

        opened = BaseBD2Task.open_cartridge_quick_switcher(
            task,
            ensure_home=lambda: True,
            click_quick_switch=lambda: True,
            confirm_quick_switch_page=lambda: False,
        )

        self.assertTrue(opened)
        self.assertEqual([True], handed)

    def _task(self, handed):
        from src.tasks.BaseBD2Task import CartridgeSpecialPageResult

        return SimpleNamespace(
            _recent_cartridge_is_pvp=lambda: False,
            _sleep_after_recognition=lambda: None,
            info_set=lambda *_a: None,
            log_info=lambda *_a, **_k: None,
            operate_click=lambda *_a, **_k: None,
            _handle_recent_cartridge_special_pages=lambda **_k: CartridgeSpecialPageResult.ABSENT,
            _quick_switch_by_key=lambda *_a, **k: handed.append(k) or False,
        )

    def test_dropped_press_is_made_again_at_once(self):
        # Player via Leo 2026-10-17 「切换卡带的时候可以点两下」: 广场 and
        # 竞技场 drop the quick-switch press.
        from src.tasks.BaseBD2Task import (
            QUICK_SWITCH_REPRESS_AFTER_SECONDS,
            BaseBD2Task,
        )

        presses, looks, handed = [], [], []
        opened = BaseBD2Task.open_cartridge_quick_switcher(
            self._task(handed),
            ensure_home=lambda: True,
            click_quick_switch=lambda: presses.append("first") or True,
            confirm_quick_switch_page=lambda: presses == ["first", "again"],
            quick_switch_page_shown=lambda seconds: looks.append(seconds) or False,
            repress_quick_switch=lambda: presses.append("again") or True,
            home_shown=lambda: False,
        )

        self.assertTrue(opened)
        self.assertEqual(["first", "again"], presses)
        self.assertEqual([QUICK_SWITCH_REPRESS_AFTER_SECONDS], looks)
        self.assertEqual([], handed)

    def test_no_second_press_once_the_page_shows(self):
        from src.tasks.BaseBD2Task import BaseBD2Task

        handed = []
        opened = BaseBD2Task.open_cartridge_quick_switcher(
            self._task(handed),
            ensure_home=lambda: True,
            click_quick_switch=lambda: True,
            confirm_quick_switch_page=lambda: True,
            quick_switch_page_shown=lambda _s: True,
            repress_quick_switch=lambda: self.fail("the page opened: no second press"),
        )

        self.assertTrue(opened)

    def test_keys_get_the_short_home_look(self):
        from src.tasks.BaseBD2Task import BaseBD2Task

        handed = []
        home_look = lambda: False  # noqa: E731
        BaseBD2Task.open_cartridge_quick_switcher(
            self._task(handed),
            ensure_home=lambda: True,
            click_quick_switch=lambda: True,
            confirm_quick_switch_page=lambda: False,
            quick_switch_page_shown=lambda _s: False,
            repress_quick_switch=lambda: False,
            home_shown=home_look,
        )

        self.assertEqual([{"home_shown": home_look}], handed)

    def test_key_fallback_uses_the_short_home_look(self):
        from src.tasks.BaseBD2Task import BaseBD2Task

        sent = []
        task = SimpleNamespace(
            log_info=lambda *_a, **_k: None,
            tap_key=lambda key, after_sleep=0.0: sent.append(key) or True,
            _save_flow_diagnostic=lambda _n: None,
        )
        opened = BaseBD2Task._quick_switch_by_key(
            task,
            lambda: self.fail("the long home wait is not used"),
            lambda: True,
            home_shown=lambda: False,
        )

        self.assertTrue(opened)
        self.assertEqual(["P"], sent)


    def test_key_fallback_runs_from_a_field_battle_before_pressing_p(self):
        from src.tasks.BaseBD2Task import BaseBD2Task

        sent = []
        task = SimpleNamespace(
            log_info=lambda *_a, **_k: None,
            log_warning=lambda *_a, **_k: None,
            tap_key=lambda key, after_sleep=0.0: sent.append(key) or True,
            _save_flow_diagnostic=lambda _n: None,
            leave_field_battle=lambda label: sent.append("逃跑") or "left",
        )
        self.assertTrue(
            BaseBD2Task._quick_switch_by_key(
                task, lambda: False, lambda: True, home_shown=lambda: False
            )
        )
        self.assertEqual(["逃跑", "P"], sent)

        sent.clear()
        task.leave_field_battle = lambda label: "按了4次 Esc 都没看到「逃跑」"
        self.assertFalse(
            BaseBD2Task._quick_switch_by_key(
                task, lambda: False, lambda: True, home_shown=lambda: False
            )
        )
        self.assertEqual([], sent)

def _skill_collector(script):
    """``script[icon name]``: icon states read one per look; the last repeats.
    Every press is taken (its count moves) unless the icon still reads
    bright afterwards in the script."""
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    clicks = []
    statuses = []
    sleeps = []
    task = SimpleNamespace(
        config={},
        sleep=sleeps.append,
        log_warning=lambda *_a: None,
        info_set=lambda key, value: statuses.append((key, value)),
    )
    vision = SimpleNamespace(
        capture=lambda: frame,
        click_client=lambda center, shape, after_sleep=0: clicks.append(center),
    )
    collector = Collector(task, vision, SimpleNamespace(), SimpleNamespace())
    looks = {name: list(states) for name, states in script.items()}

    def detect(_frame, icon):
        states = looks[icon.name]
        state = states.pop(0) if len(states) > 1 else states[0]
        return ActionIconDetection(
            state,
            MatchResult(0.98, (100, 100), (40, 40), pixel_score=0.95, zncc_score=0.90),
            1.0,
            stable=True,
            sample_count=2,
        )

    collector.action_icons = SimpleNamespace(detect=detect)
    collector._read_action_feedback = lambda action: SkillFeedbackObservation("", None, 0.0)
    return collector, clicks, statuses, sleeps


def _clicked(action):
    return (action, None, None, SkillFeedbackObservation("", None, 0.0))


class SettleBeforeNextPressTest(unittest.TestCase):
    def test_next_skill_waits_until_the_last_reads_grey_and_it_is_bright(self):
        collector, clicks, _statuses, sleeps = _skill_collector(
            {
                "吸收": [ActionIconState.AVAILABLE] * 3 + [ActionIconState.USED],
                "召集": [ActionIconState.USED] * 2 + [ActionIconState.AVAILABLE],
            }
        )

        collector._settle_before_next_press([_clicked(ABSORB_ACTION)], SUMMON_ACTION, 0.0)

        self.assertEqual([], clicks)
        self.assertEqual([PRESS_TAKEN_POLL_SECONDS] * 5, sleeps)

    def test_still_bright_summon_is_pressed_again_before_suppress(self):
        collector, clicks, statuses, _sleeps = _skill_collector(
            {
                "召集": [ActionIconState.AVAILABLE] * 16 + [ActionIconState.USED],
                "制服": [ActionIconState.AVAILABLE],
            }
        )
        clicked = [_clicked(SUMMON_ACTION)]

        collector._settle_before_next_press(clicked, SUPPRESS_ACTION, 0.0)

        self.assertEqual(1, len(clicks))
        self.assertIn("召集", collector._pressed_again)
        self.assertTrue(any("补按" in str(value) for _key, value in statuses))

    def test_a_skill_pressed_again_is_not_pressed_a_third_time(self):
        collector, clicks, _statuses, _sleeps = _skill_collector(
            {"召集": [ActionIconState.AVAILABLE], "制服": [ActionIconState.AVAILABLE]}
        )
        collector._pressed_again = {"召集"}

        collector._settle_before_next_press([_clicked(SUMMON_ACTION)], SUPPRESS_ACTION, 0.0)

        self.assertEqual([], clicks)

    def test_unreadable_icon_is_not_pressed_blind(self):
        # A washed-out icon (fixed-slot fallback) proves by its count later.
        collector, clicks, _statuses, _sleeps = _skill_collector(
            {"吸收": [ActionIconState.UNKNOWN], "召集": [ActionIconState.AVAILABLE]}
        )

        collector._settle_before_next_press([_clicked(ABSORB_ACTION)], SUMMON_ACTION, 0.0)

        self.assertEqual([], clicks)

    def test_suppress_is_never_pressed_again_here(self):
        # 压制 can stay bright after it took.
        collector, clicks, _statuses, sleeps = _skill_collector(
            {"制服": [ActionIconState.AVAILABLE], "召集": [ActionIconState.AVAILABLE]}
        )

        collector._settle_before_next_press([_clicked(SUPPRESS_ACTION)], SUMMON_ACTION, 0.0)

        self.assertEqual([], clicks)
        self.assertEqual([], sleeps)


if __name__ == "__main__":
    unittest.main()
