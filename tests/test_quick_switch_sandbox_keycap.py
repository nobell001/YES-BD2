"""Quick switch from the field also has the key-cap fallback (audit #8).

The see-through quick-switch button scores 0.69 on snow; the home route
already pressed its calibrated place once the C/H key caps proved the field,
but the field route (every cartridge switch) ended the whole run instead.
"""

import unittest
from types import SimpleNamespace

from src.tasks.map_trade.models import NavigationResult, ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_story import (
    FIELD_QUICK_SWITCH_REFERENCE_POINT,
    QUICK_SWITCH_TEMPLATE,
)


def _navigator(keycaps_pass, page_opens=True):
    template_calls = []
    reference_clicks = []
    vision = SimpleNamespace(
        click_stable_template=lambda spec, timeout, after_sleep, window_samples=None: (
            template_calls.append((spec, window_samples)) and False
        ),
        capture=lambda: "frame",
        match=lambda _frame, spec: spec,
        passes=lambda _match, _spec: keycaps_pass,
        click_reference=lambda x, y, after_sleep=0: reference_clicks.append((x, y)),
    )
    task = SimpleNamespace(operate_click=lambda *_a, **_k: None)
    navigator = Navigator(task, vision)
    navigator.ensure_small_minimap = lambda: True
    navigator._wait_for_current_sandbox = lambda: NavigationResult(True, ScreenState.SANDBOX)
    navigator._wait_for_quick_switch_page = lambda: page_opens
    navigator._select_story_category = lambda _category: True
    navigator.classify = lambda: ScreenState.UNKNOWN
    return navigator, template_calls, reference_clicks


class SandboxQuickSwitchKeycapTest(unittest.TestCase):
    def test_unseen_button_with_key_caps_presses_its_place(self):
        navigator, template_calls, reference_clicks = _navigator(keycaps_pass=True)

        result = navigator.open_story_quick_switcher_from_sandbox()

        self.assertTrue(result.success)
        self.assertEqual([FIELD_QUICK_SWITCH_REFERENCE_POINT], reference_clicks)
        # Still three agreeing samples on the field.
        self.assertEqual([(QUICK_SWITCH_TEMPLATE, 3)], template_calls)

    def test_the_page_check_still_has_to_pass(self):
        navigator, _calls, reference_clicks = _navigator(keycaps_pass=True, page_opens=False)

        result = navigator.open_story_quick_switcher_from_sandbox()

        self.assertFalse(result.success)
        self.assertEqual("点击快速切换按钮后未确认卡带选择页", result.message)
        self.assertEqual(1, len(reference_clicks))

    def test_no_key_caps_presses_nothing_blind(self):
        navigator, template_calls, reference_clicks = _navigator(keycaps_pass=False)

        result = navigator.open_story_quick_switcher_from_sandbox()

        self.assertFalse(result.success)
        self.assertEqual("卡带箱庭内未稳定识别到快速切换按钮", result.message)
        self.assertEqual([], reference_clicks)
        self.assertEqual(2, len(template_calls))


if __name__ == "__main__":
    unittest.main()
