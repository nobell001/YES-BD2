"""Map-trade collection tests (split from test_map_trade.py)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.tasks.BaseBD2Task import CartridgeSpecialPageResult
from src.tasks.map_trade.card_status import (
    CardActionDetection,
    CardActionState,
    CollectionCardSelectionOutcome,
    CollectionCardSelectionResult,
    StoryCardCompletion,
)
from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.models import (
    CARD_BY_ID,
    MatchResult,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator import (
    FIRST_CARD_CONFIRM_REGION,
    FIRST_CARD_INSERT_REGION,
    FIRST_CARD_SKIP_TEMPLATE,
    PROBE_QUICK_SWITCH_SCROLL_AMOUNT,
    PROBE_QUICK_SWITCH_SCROLL_COUNT,
    PROBE_QUICK_SWITCH_SCROLL_INTERVAL_SECONDS,
    PROBE_QUICK_SWITCH_SCROLL_POINT,
    PROBE_QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
    PROBE_STORY_BADGE_CONFIRM_SECONDS,
    QUICK_SWITCH_SCROLL_FOCUS_POINT,
    QUICK_SWITCH_SCROLL_INTERVAL,
    QUICK_SWITCH_SCROLL_POINT,
    QUICK_SWITCH_SCROLL_RESET_AMOUNT,
    QUICK_SWITCH_SCROLL_RESET_COUNT,
    QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
    QUICK_SWITCH_SCROLL_UP_AMOUNT,
    QUICK_SWITCH_SCROLL_UP_COUNT,
    QUICK_SWITCH_TEMPLATE,
    STORY_CATEGORY_POINT,
    STORY_SANDBOX_STABLE_HITS,
    LocatedStoryCard,
    Navigator,
    ProbedStoryCard,
    SandboxConfirmation,
    StoryBadgeCandidate,
    StoryBadgeDetection,
)
from src.tasks.map_trade.navigator_constants import (
    FIRST_CARD_DIALOG_REGION,
    FIRST_CARD_PAID_DIALOG_MESSAGE,
)
from src.tasks.map_trade.progress import (
    UTC_PLUS_8,
    ProgressStore,
)


class CollectionCardTest(unittest.TestCase):
    def test_story_entry_retries_after_late_fiend_reward(self):
        failure = NavigationResult(False, ScreenState.UNKNOWN, "入场确认超时")
        success = NavigationResult(True, ScreenState.SANDBOX, "Q_sp1")
        for reward_result, expected, calls in (
            (CartridgeSpecialPageResult.HANDLED, success, 2),
            (CartridgeSpecialPageResult.ABSENT, failure, 1),
        ):
            with self.subTest(reward_result=reward_result):
                task = SimpleNamespace(
                    _handle_recent_cartridge_special_pages=Mock(return_value=reward_result)
                )
                navigator = Navigator(task, SimpleNamespace())
                navigator._wait_for_field_hud = Mock(
                    side_effect=[failure, success]
                )

                self.assertIs(expected, navigator._wait_for_story_sandbox(1, timeout=1.0))
                self.assertEqual(calls, navigator._wait_for_field_hud.call_count)
                task._handle_recent_cartridge_special_pages.assert_called_once()
                reward_call = task._handle_recent_cartridge_special_pages.call_args
                self.assertFalse(reward_call.kwargs["allow_pvp_pages"])
                self.assertGreaterEqual(reward_call.kwargs["timeout"], 0.0)
                self.assertLessEqual(reward_call.kwargs["timeout"], 1.0)

    def test_collection_card_selection_uses_common_quick_switch_and_badge_center(self):
        clicks = []
        client_clicks = []
        template_clicks = []
        opened_callbacks = []
        badge_targets = []
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        badge = StoryBadgeDetection(
            best=StoryBadgeCandidate(
                1,
                MatchResult(0.99, (300, 930), (30, 28), pixel_score=0.98),
            ),
            runner_up=StoryBadgeCandidate(
                7,
                MatchResult(0.80, (301, 930), (31, 31), pixel_score=0.82),
            ),
        )

        def open_quick_switcher(**callbacks):
            opened_callbacks.append(tuple(callbacks))
            return (
                callbacks["ensure_home"]()
                and callbacks["click_quick_switch"]()
                and callbacks["confirm_quick_switch_page"]()
            )

        task = SimpleNamespace(
            config={"加载页面等待秒数": 45.0},
            operate_click=lambda x, y, after_sleep=0: clicks.append((x, y, after_sleep)),
            open_cartridge_quick_switcher=open_quick_switcher,
            log_warning=lambda *_args, **_kwargs: None,
        )
        vision = SimpleNamespace(
            capture=lambda: frame,
            click_stable_template=lambda spec, timeout, after_sleep, **_kw: (
                template_clicks.append((spec, timeout, after_sleep)) or True
            ),
            click_client=lambda point, shape, after_sleep=0: client_clicks.append(
                (point, shape, after_sleep)
            ),
        )
        navigator = Navigator(task, vision)
        navigator.classify = lambda: ScreenState.HOME
        navigator.return_home = lambda: NavigationResult(True, ScreenState.HOME)
        navigator._wait_for_cartridge_home = lambda: True
        navigator._wait_for_quick_switch_page = lambda: True
        navigator._wait_for_story_category = lambda **_kwargs: True
        navigator._wait_for_story_badge_with_scroll = lambda number: (
            badge_targets.append(number) or (frame, badge)
        )
        navigator._find_story_badge = lambda _frame, _number: (badge, "")
        navigator._wait_for_story_sandbox = lambda number: NavigationResult(
            True,
            ScreenState.SANDBOX,
            f"Q_sp{number}",
        )

        result = navigator.select_card("Q_sp1")

        self.assertTrue(result.success)
        self.assertEqual("Q_sp1", result.message)
        self.assertEqual([1], badge_targets)
        self.assertEqual(
            [("ensure_home", "click_quick_switch", "confirm_quick_switch_page")],
            opened_callbacks,
        )
        self.assertEqual([(QUICK_SWITCH_TEMPLATE, 3.0, 1.0)], template_clicks)
        self.assertEqual([(*STORY_CATEGORY_POINT, 0.5)], clicks)
        self.assertEqual([(badge.best.result.center, frame.shape, 1.0)], client_clicks)

    def test_collection_card_visual_completion_is_checked_before_clicking(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        badge = StoryBadgeDetection(
            best=StoryBadgeCandidate(
                1,
                MatchResult(
                    0.99,
                    (80, 921),
                    (29, 29),
                    pixel_score=0.98,
                    zncc_score=0.97,
                ),
            ),
            runner_up=StoryBadgeCandidate(
                7,
                MatchResult(
                    0.80,
                    (81, 921),
                    (29, 29),
                    pixel_score=0.82,
                    zncc_score=0.70,
                ),
            ),
        )
        located = LocatedStoryCard(CARD_BY_ID["Q_sp1"], frame, badge)
        completion = StoryCardCompletion(
            absorb=CardActionDetection(CardActionState.COMPLETED),
            suppress=CardActionDetection(CardActionState.COMPLETED),
            bounds=(78, 1015, 258, 1065),
            complete_region=True,
        )
        statuses = []
        navigator = Navigator(
            SimpleNamespace(
                info_set=lambda *values: statuses.append(values),
                log_warning=lambda *_args: None,
            ),
            SimpleNamespace(),
        )
        navigator._locate_story_card = lambda _card_id: located
        navigator.card_status = SimpleNamespace(
            detect=lambda detected_frame, center: (
                self.assertIs(frame, detected_frame)
                or self.assertEqual(badge.best.result.center, center)
                or completion
            )
        )
        navigator._enter_located_story_card = lambda _located: self.fail(
            "visually completed card must not be clicked"
        )

        result = navigator.select_collection_card("Q_sp1")

        self.assertTrue(result.success)
        self.assertEqual(
            CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
            result.outcome,
        )
        self.assertEqual(ScreenState.CARD_MENU, result.state)
        self.assertIs(completion, result.completion)
        self.assertIn(("卡带完成度", "completed"), statuses)

    def test_formal_collection_skips_card_when_preentry_status_is_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = ProgressStore(
                Path(temp_dir) / "progress.json",
                lambda: datetime(2026, 8, 3, 12, tzinfo=UTC_PLUS_8),
            )
            selected = []
            task = SimpleNamespace(
                config={"卡带单步重试次数": 1},
                log_warning=lambda *_args: None,
                info_set=lambda *_args: None,
            )

            def select(card_id, *, enter_visually_complete):
                selected.append((card_id, enter_visually_complete))
                return CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                    NavigationResult(True, ScreenState.CARD_MENU, "视觉完成"),
                )

            navigator = SimpleNamespace(
                select_collection_card=select,
                prepare_collection_main_area=lambda *_args: self.fail(
                    "preentry-complete card must not enter the sandbox"
                ),
            )
            collector = Collector(task, object(), navigator, progress)
            with patch(
                "src.tasks.map_trade.collector.COLLECTABLE_CARDS",
                (CARD_BY_ID["Q_sp1"],),
            ):
                result = collector.run()

        self.assertTrue(result.success)
        self.assertEqual([("Q_sp1", False)], selected)

    def test_collection_card_pending_or_unknown_status_still_enters(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        badge = StoryBadgeDetection(
            best=StoryBadgeCandidate(
                1,
                MatchResult(0.99, (80, 921), (29, 29), pixel_score=0.98),
            ),
            runner_up=None,
        )
        located = LocatedStoryCard(CARD_BY_ID["Q_sp1"], frame, badge)
        entered = []
        navigator = Navigator(
            SimpleNamespace(
                info_set=lambda *_args: None,
                log_warning=lambda *_args: None,
            ),
            SimpleNamespace(),
        )
        navigator._locate_story_card = lambda _card_id: located
        navigator._enter_located_story_card = lambda value: (
            entered.append(value) or NavigationResult(True, ScreenState.SANDBOX, "Q_sp1")
        )

        for state in (CardActionState.PENDING, CardActionState.UNKNOWN):
            with self.subTest(state=state):
                completion = StoryCardCompletion(
                    absorb=CardActionDetection(state),
                    suppress=CardActionDetection(CardActionState.COMPLETED),
                    bounds=(78, 1015, 258, 1065),
                    complete_region=True,
                )
                navigator.card_status = SimpleNamespace(
                    detect=lambda *_args, value=completion: value
                )

                result = navigator.select_collection_card("Q_sp1")

                self.assertEqual(
                    CollectionCardSelectionOutcome.ENTERED,
                    result.outcome,
                )
        self.assertEqual([located, located], entered)

    def test_collection_completion_api_rejects_non_collection_story_cards(self):
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        navigator._locate_story_card = lambda _card_id: self.fail(
            "non-collection card must not be located"
        )

        result = navigator.select_collection_card("Q_sp20")

        self.assertFalse(result.success)
        self.assertEqual(CollectionCardSelectionOutcome.FAILED, result.outcome)
        self.assertIn("非跑图剧情卡带", result.message)

    def test_collection_status_detection_error_continues_without_skipping(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        located = LocatedStoryCard(
            CARD_BY_ID["Q_sp1"],
            frame,
            StoryBadgeDetection(
                best=StoryBadgeCandidate(
                    1,
                    MatchResult(0.99, (80, 921), (29, 29), pixel_score=0.98),
                ),
                runner_up=None,
            ),
        )
        warnings = []
        navigator = Navigator(
            SimpleNamespace(
                info_set=lambda *_args: None,
                log_warning=lambda value: warnings.append(value),
            ),
            SimpleNamespace(),
        )
        navigator._locate_story_card = lambda _card_id: located
        navigator.card_status = SimpleNamespace(
            detect=lambda *_args: (_ for _ in ()).throw(RuntimeError("template missing"))
        )
        navigator._enter_located_story_card = lambda _located: NavigationResult(
            True,
            ScreenState.SANDBOX,
        )

        result = navigator.select_collection_card("Q_sp1")

        self.assertEqual(CollectionCardSelectionOutcome.ENTERED, result.outcome)
        self.assertIsNone(result.completion)
        self.assertTrue(any("按未知继续进入" in value for value in warnings))

    def test_collection_card_scroll_resets_down_then_scans_up_in_bottom_region(self):
        scrolls = []
        clicks = []
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        detection = StoryBadgeDetection(
            best=StoryBadgeCandidate(
                12,
                MatchResult(0.99, (500, 930), (30, 28), pixel_score=0.98),
            ),
            runner_up=StoryBadgeCandidate(
                2,
                MatchResult(0.80, (501, 930), (31, 31), pixel_score=0.82),
            ),
        )
        results = iter(
            (
                (None, "未达到双阈值，检测目标数=9"),
                (None, "未达到双阈值，检测目标数=9"),
                (detection, ""),
            )
        )
        task = SimpleNamespace(
            scroll_client=lambda *args, **kwargs: scrolls.append((args, kwargs)),
            operate_click=lambda *args, **kwargs: clicks.append((args, kwargs)),
            log_warning=lambda *_args, **_kwargs: None,
        )
        navigator = Navigator(task, SimpleNamespace(capture=lambda: frame))
        navigator._find_story_badge = lambda _frame, _number: next(results)
        # Legacy reset-and-scan path (the directional wheel is covered live).
        navigator._scan_story_bar_by_wheel = lambda *_a, **_k: None

        found = navigator._wait_for_story_badge_with_scroll(12, scan_steps=1)

        self.assertIsNotNone(found)
        self.assertEqual(detection, found[1])
        self.assertEqual(
            [
                (
                    (QUICK_SWITCH_SCROLL_POINT, QUICK_SWITCH_SCROLL_RESET_AMOUNT),
                    {
                        "count": QUICK_SWITCH_SCROLL_RESET_COUNT,
                        "interval": QUICK_SWITCH_SCROLL_INTERVAL,
                        "after_sleep": QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
                    },
                ),
                (
                    (QUICK_SWITCH_SCROLL_POINT, QUICK_SWITCH_SCROLL_UP_AMOUNT),
                    {
                        "count": QUICK_SWITCH_SCROLL_UP_COUNT,
                        "interval": QUICK_SWITCH_SCROLL_INTERVAL,
                        "after_sleep": QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
                    },
                ),
            ],
            scrolls,
        )
        self.assertEqual((43 / 1920, 974 / 1080), QUICK_SWITCH_SCROLL_POINT)
        self.assertEqual(
            [((QUICK_SWITCH_SCROLL_FOCUS_POINT), {"after_sleep": 0.0})],
            clicks,
        )
        self.assertEqual((43 / 1920, 974 / 1080), QUICK_SWITCH_SCROLL_FOCUS_POINT)
        self.assertEqual(1, QUICK_SWITCH_SCROLL_UP_AMOUNT)

    def test_collection_card_scroll_stops_on_badge_ambiguity(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        warnings = []
        task = SimpleNamespace(
            scroll_client=lambda *_args, **_kwargs: self.fail(
                "ambiguous badge must stop before scrolling"
            ),
            log_warning=warnings.append,
        )
        navigator = Navigator(task, SimpleNamespace(capture=lambda: frame))
        navigator._find_story_badge = lambda _frame, _number: (
            None,
            "候选分差不足：0.020<0.050",
        )

        found = navigator._wait_for_story_badge_with_scroll(12, scan_steps=1)

        self.assertIsNone(found)
        self.assertIn("存在歧义", warnings[0])

    def test_probe_story_card_scrolls_up_once_then_rechecks_same_frame_status(self):
        first_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        matched_frame = np.ones((1080, 1920, 3), dtype=np.uint8)
        confirmed_frame = np.full((1080, 1920, 3), 2, dtype=np.uint8)
        frames = iter((first_frame, matched_frame, confirmed_frame))
        detection = StoryBadgeDetection(
            best=StoryBadgeCandidate(
                10,
                MatchResult(
                    0.99,
                    (500, 930),
                    (30, 28),
                    pixel_score=0.98,
                    zncc_score=0.97,
                ),
            ),
            runner_up=StoryBadgeCandidate(
                12,
                MatchResult(
                    0.80,
                    (501, 930),
                    (31, 31),
                    pixel_score=0.82,
                    zncc_score=0.70,
                ),
            ),
        )
        completion = StoryCardCompletion(
            absorb=CardActionDetection(CardActionState.PENDING),
            suppress=CardActionDetection(CardActionState.COMPLETED),
            bounds=(485, 1010, 665, 1060),
            complete_region=True,
        )
        scrolls = []
        clicks = []
        sleeps = []
        task = SimpleNamespace(
            scroll_client=lambda *args, **kwargs: scrolls.append((args, kwargs)),
            operate_click=lambda *args, **kwargs: clicks.append((args, kwargs)),
            sleep=sleeps.append,
            info_set=lambda *_args: None,
            log_warning=lambda *_args: None,
        )
        navigator = Navigator(task, SimpleNamespace(capture=lambda: next(frames)))
        find_results = iter(
            (
                (None, "未达到角标双阈值"),
                (detection, ""),
                (detection, ""),
            )
        )
        navigator._find_story_badge = lambda *_args: next(find_results)
        detected_frames = []
        navigator.card_status = SimpleNamespace(
            detect=lambda frame, center: detected_frames.append((frame, center)) or completion
        )

        result = navigator.locate_probe_story_card("Q_sp10", scan_steps=5)

        self.assertIsNotNone(result)
        self.assertIs(confirmed_frame, result.located.frame)
        self.assertIs(completion, result.completion)
        self.assertEqual(
            [
                (
                    (PROBE_QUICK_SWITCH_SCROLL_POINT, PROBE_QUICK_SWITCH_SCROLL_AMOUNT),
                    {
                        "count": PROBE_QUICK_SWITCH_SCROLL_COUNT,
                        "interval": PROBE_QUICK_SWITCH_SCROLL_INTERVAL_SECONDS,
                        "after_sleep": PROBE_QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
                    },
                )
            ],
            scrolls,
        )
        self.assertEqual((43 / 1920, 974 / 1080), PROBE_QUICK_SWITCH_SCROLL_POINT)
        self.assertEqual(1, PROBE_QUICK_SWITCH_SCROLL_AMOUNT)
        self.assertEqual(5, PROBE_QUICK_SWITCH_SCROLL_COUNT)
        self.assertEqual(0.1, PROBE_QUICK_SWITCH_SCROLL_INTERVAL_SECONDS)
        self.assertEqual(0.5, PROBE_QUICK_SWITCH_SCROLL_SETTLE_SECONDS)
        self.assertEqual(
            [((QUICK_SWITCH_SCROLL_FOCUS_POINT), {"after_sleep": 0.0})],
            clicks,
        )
        self.assertEqual([PROBE_STORY_BADGE_CONFIRM_SECONDS], sleeps)
        self.assertEqual(
            [
                (matched_frame, detection.best.result.center),
                (confirmed_frame, detection.best.result.center),
            ],
            detected_frames,
        )

    def test_probe_story_card_scrolls_again_when_status_strip_is_clipped(self):
        edge_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        centered_frame = np.ones((1080, 1920, 3), dtype=np.uint8)
        confirmed_frame = np.full((1080, 1920, 3), 2, dtype=np.uint8)
        frames = iter((edge_frame, centered_frame, confirmed_frame))
        edge_badge = StoryBadgeDetection(
            StoryBadgeCandidate(
                10,
                MatchResult(0.99, (1850, 930), (30, 28), 0.98, 0.97),
            ),
            StoryBadgeCandidate(
                12,
                MatchResult(0.80, (1851, 930), (31, 31), 0.82, 0.70),
            ),
        )
        centered_badge = StoryBadgeDetection(
            StoryBadgeCandidate(
                10,
                MatchResult(0.99, (500, 930), (30, 28), 0.98, 0.97),
            ),
            StoryBadgeCandidate(
                12,
                MatchResult(0.80, (501, 930), (31, 31), 0.82, 0.70),
            ),
        )
        clipped = StoryCardCompletion(
            CardActionDetection(CardActionState.UNKNOWN),
            CardActionDetection(CardActionState.UNKNOWN),
            (1835, 1010, 1920, 1060),
            complete_region=False,
        )
        complete = StoryCardCompletion(
            CardActionDetection(CardActionState.COMPLETED),
            CardActionDetection(CardActionState.COMPLETED),
            (485, 1010, 665, 1060),
            complete_region=True,
        )
        scrolls = []
        clicks = []
        task = SimpleNamespace(
            scroll_client=lambda *args, **kwargs: scrolls.append((args, kwargs)),
            operate_click=lambda *args, **kwargs: clicks.append((args, kwargs)),
            sleep=lambda *_args: None,
            info_set=lambda *_args: None,
            log_warning=lambda *_args: None,
        )
        navigator = Navigator(task, SimpleNamespace(capture=lambda: next(frames)))
        badges = iter(((edge_badge, ""), (centered_badge, ""), (centered_badge, "")))
        navigator._find_story_badge = lambda *_args: next(badges)
        completions = iter((clipped, complete, complete))
        navigator.card_status = SimpleNamespace(detect=lambda *_args: next(completions))

        result = navigator.locate_probe_story_card("Q_sp10", scan_steps=1)

        self.assertIsNotNone(result)
        self.assertIs(centered_badge, result.located.badge)
        self.assertIs(complete, result.completion)
        self.assertEqual(1, len(scrolls))
        self.assertEqual(
            [((QUICK_SWITCH_SCROLL_FOCUS_POINT), {"after_sleep": 0.0})],
            clicks,
        )

    def test_probe_story_card_ambiguity_stops_without_scrolling(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        warnings = []
        task = SimpleNamespace(
            scroll_client=lambda *_args, **_kwargs: self.fail(
                "ambiguous probe badge must not scroll"
            ),
            sleep=lambda *_args: self.fail("ambiguous probe badge must not sleep"),
            info_set=lambda *_args: None,
            log_warning=warnings.append,
        )
        navigator = Navigator(task, SimpleNamespace(capture=lambda: frame))
        navigator._find_story_badge = lambda *_args: (
            None,
            "候选分差不足（ZNCC）：0.020<0.050",
        )
        navigator.card_status = SimpleNamespace(
            detect=lambda *_args: self.fail("ambiguous probe badge must not read status")
        )

        result = navigator.locate_probe_story_card("Q_sp10", scan_steps=3)

        self.assertIsNone(result)
        self.assertIn("存在歧义", warnings[0])

    def test_probe_story_card_recheck_failure_stops_without_scrolling_or_clicking(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        detection = StoryBadgeDetection(
            StoryBadgeCandidate(
                10,
                MatchResult(0.99, (500, 930), (30, 28), 0.98, 0.97),
            ),
            StoryBadgeCandidate(
                12,
                MatchResult(0.80, (501, 930), (31, 31), 0.82, 0.70),
            ),
        )
        completion = StoryCardCompletion(
            CardActionDetection(CardActionState.COMPLETED),
            CardActionDetection(CardActionState.COMPLETED),
            (485, 1010, 665, 1060),
            complete_region=True,
        )
        warnings = []
        task = SimpleNamespace(
            scroll_client=lambda *_args, **_kwargs: self.fail(
                "a vanished recheck must stop before scrolling"
            ),
            sleep=lambda *_args: None,
            info_set=lambda *_args: None,
            log_warning=warnings.append,
        )
        navigator = Navigator(task, SimpleNamespace(capture=lambda: frame))
        results = iter(((detection, ""), (None, "未识别")))
        navigator._find_story_badge = lambda *_args: next(results)
        navigator.card_status = SimpleNamespace(detect=lambda *_args: completion)

        result = navigator.locate_probe_story_card("Q_sp10", scan_steps=3)

        self.assertIsNone(result)
        self.assertIn("点击前复核失败", warnings[0])

    def test_probe_story_card_scan_limit_is_bounded_without_reset(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        scrolls = []
        clicks = []
        captures = []
        task = SimpleNamespace(
            scroll_client=lambda *args, **kwargs: scrolls.append((args, kwargs)),
            operate_click=lambda *args, **kwargs: clicks.append((args, kwargs)),
            sleep=lambda *_args: None,
            info_set=lambda *_args: None,
            log_warning=lambda *_args: None,
        )
        navigator = Navigator(
            task,
            SimpleNamespace(capture=lambda: captures.append(True) or frame),
        )
        navigator._find_story_badge = lambda *_args: (None, "未识别")

        result = navigator.locate_probe_story_card("Q_sp10", scan_steps=12)

        self.assertIsNone(result)
        self.assertEqual(4, len(captures))
        self.assertEqual(3, len(scrolls))
        self.assertEqual([5, 5, 2], [call[1]["count"] for call in scrolls])
        self.assertEqual(
            [((QUICK_SWITCH_SCROLL_FOCUS_POINT), {"after_sleep": 0.0})],
            clicks,
        )
        self.assertTrue(
            all(
                call[0] == (PROBE_QUICK_SWITCH_SCROLL_POINT, PROBE_QUICK_SWITCH_SCROLL_AMOUNT)
                for call in scrolls
            )
        )

    def test_enter_probe_story_card_uses_revalidated_located_card(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        badge = StoryBadgeDetection(
            StoryBadgeCandidate(
                10,
                MatchResult(0.99, (500, 930), (30, 28), 0.98, 0.97),
            ),
            StoryBadgeCandidate(
                12,
                MatchResult(0.80, (501, 930), (31, 31), 0.82, 0.70),
            ),
        )
        completion = StoryCardCompletion(
            CardActionDetection(CardActionState.COMPLETED),
            CardActionDetection(CardActionState.COMPLETED),
            (485, 1010, 665, 1060),
            complete_region=True,
        )
        located = LocatedStoryCard(CARD_BY_ID["Q_sp10"], frame, badge)
        probed = ProbedStoryCard(located, completion)
        entered = []
        navigator = Navigator(SimpleNamespace(), SimpleNamespace())
        expected = NavigationResult(True, ScreenState.SANDBOX, "Q_sp10")
        navigator._enter_located_story_card = lambda value: entered.append(value) or expected

        result = navigator.enter_probe_story_card(probed)

        self.assertIs(expected, result)
        self.assertEqual([located], entered)

    def test_collection_card_entry_handles_insert_prompt_then_reconfirms_sandbox(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        sleeps = []
        states = iter(
            (
                ScreenState.UNKNOWN,
                ScreenState.SANDBOX,
                ScreenState.SANDBOX,
            )
        )
        task = SimpleNamespace(
            config={"加载页面等待秒数": 45.0},
            sleep=lambda seconds: sleeps.append(seconds),
        )

        def ocr_text(_frame, name, roi=None):
            if name == "新卡带插入提示":
                self.assertEqual(FIRST_CARD_INSERT_REGION, roi)
                return "未插好游戏卡 插入"
            return ""

        vision = SimpleNamespace(
            capture=lambda: frame,
            simplify=lambda value: value,
            ocr_text=ocr_text,
            click_ocr=lambda patterns, roi, after_sleep, name: (
                clicks.append((tuple(patterns), roi, after_sleep, name)) or True
            ),
            match=lambda _frame, _spec: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda *_args: False,
        )
        navigator = Navigator(task, vision)
        navigator.classify = lambda _frame=None: next(states)
        navigator._match_story_sandbox_signals = lambda _frame: SandboxConfirmation(
            2,
            2,
            3,
            1,
        )

        result = navigator._wait_for_story_sandbox(12, timeout=2.0, interval=0.0)

        self.assertTrue(result.success)
        self.assertEqual("Q_sp12", result.message)
        self.assertEqual(
            [
                (
                    (r"插入", r"未插好游戏卡"),
                    FIRST_CARD_INSERT_REGION,
                    0.8,
                    "新卡带插入",
                )
            ],
            clicks,
        )
        self.assertEqual([], sleeps)

    def _first_card_vision(self, frame, buttons, dialog, client_clicks):
        """Vision for the card-entry wait: no insert prompt, no skip button."""

        def ocr_text(_frame, name, roi=None):
            if name == "首次卡带对话":
                self.assertIs(frame, _frame)
                self.assertEqual(FIRST_CARD_DIALOG_REGION, roi)
                return dialog
            return ""

        def ocr_boxes(_frame, name, roi=None):
            self.assertIs(frame, _frame)
            self.assertEqual(("首次卡带确认", FIRST_CARD_CONFIRM_REGION), (name, roi))
            return [
                SimpleNamespace(name=text, x=900 + 200 * index, y=800, width=120, height=40)
                for index, text in enumerate(buttons)
            ]

        return SimpleNamespace(
            capture=lambda: frame,
            simplify=lambda value: value,
            ocr_text=ocr_text,
            ocr_boxes=ocr_boxes,
            match=lambda _frame, _spec: MatchResult(-1.0, (0, 0), (0, 0)),
            passes=lambda result, _spec: result.score >= 0.72,
            click_client=lambda point, shape, after_sleep=0: client_clicks.append(
                (point, shape, after_sleep)
            ),
        )

    def test_first_card_confirm_presses_only_an_exact_button_of_the_same_frame(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        clicks = []
        vision = self._first_card_vision(frame, ["取消", "确认"], "剧情 跳过 取消 确认", clicks)
        navigator = Navigator(SimpleNamespace(config={}), vision)

        self.assertTrue(navigator._handle_story_card_intermediate(frame))
        self.assertEqual([((1160, 820), frame.shape, 0.8)], clicks)

        clicks.clear()
        vision = self._first_card_vision(frame, ["确认修改"], "确认修改", clicks)
        navigator = Navigator(SimpleNamespace(config={}), vision)
        self.assertFalse(navigator._handle_story_card_intermediate(frame))
        self.assertEqual([], clicks)

    def test_first_card_wait_never_confirms_a_dialog_that_may_spend(self):
        # Review #11: any box containing 确认 used to be pressed while
        # waiting to enter a card, a purchase or 钻石 prompt included.
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for buttons, dialog in (
            (["确认"], "是否消耗钻石购买该游戏卡 取消 确认"),
            (["确认"], "使用鲜血鸡尾酒 确认"),
            (["确认购买"], ""),
        ):
            with self.subTest(dialog=dialog or buttons):
                clicks = []
                saved = []
                warnings = []
                special_pages = []
                task = SimpleNamespace(
                    config={"加载页面等待秒数": 45.0},
                    sleep=lambda *_args: None,
                    save_frame=lambda name, image: (
                        saved.append((name, image)) or Path(f"{name}.png")
                    ),
                    log_warning=warnings.append,
                    _handle_recent_cartridge_special_pages=lambda **kwargs: (
                        special_pages.append(kwargs) or CartridgeSpecialPageResult.HANDLED
                    ),
                )
                navigator = Navigator(
                    task, self._first_card_vision(frame, buttons, dialog, clicks)
                )
                navigator.classify = lambda _frame=None: ScreenState.UNKNOWN
                navigator._black_frame = lambda _frame: False
                navigator._auto_moving = lambda _frame: False

                result = navigator._wait_for_story_sandbox(12, timeout=30.0, interval=0.0)

                self.assertFalse(result.success)
                self.assertEqual(FIRST_CARD_PAID_DIALOG_MESSAGE, result.message)
                self.assertEqual([], clicks)
                self.assertEqual([("map_card_paid_dialog_failed", frame)], saved)
                self.assertEqual([], special_pages)
                self.assertTrue(any("map_card_paid_dialog_failed.png" in w for w in warnings))

    def test_collection_card_entry_handles_skip_and_confirmation_with_mouse(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        client_clicks = []
        skip_result = MatchResult(0.99, (1500, 20), (100, 40), pixel_score=0.98)
        task = SimpleNamespace(config={}, sleep=lambda *_args: None)
        matches = iter(
            (
                skip_result,
                MatchResult(-1.0, (0, 0), (0, 0)),
                MatchResult(-1.0, (0, 0), (0, 0)),
            )
        )
        vision = self._first_card_vision(frame, ["确认"], "确认", client_clicks)
        vision.match = lambda _frame, spec: (
            self.assertEqual(FIRST_CARD_SKIP_TEMPLATE, spec) or next(matches)
        )
        navigator = Navigator(task, vision)
        states = iter(
            (
                ScreenState.UNKNOWN,
                ScreenState.UNKNOWN,
                ScreenState.SANDBOX,
                ScreenState.SANDBOX,
            )
        )
        navigator.classify = lambda _frame=None: next(states)
        navigator._match_story_sandbox_signals = lambda _frame: SandboxConfirmation(
            2,
            2,
            3,
            1,
        )

        result = navigator._wait_for_story_sandbox(12, timeout=2.0, interval=0.0)

        self.assertTrue(result.success)
        self.assertEqual(
            [(skip_result.center, frame.shape, 0.8), ((960, 820), frame.shape, 0.8)],
            client_clicks,
        )

    def test_collection_card_entry_requires_consecutive_stable_sandbox_frames(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        states = iter(
            (
                ScreenState.SANDBOX,
                ScreenState.LOADING,
                ScreenState.SANDBOX,
                ScreenState.UNKNOWN,
                ScreenState.SANDBOX,
                ScreenState.SANDBOX,
            )
        )
        captures = []
        task = SimpleNamespace(config={}, sleep=lambda *_args: None)
        vision = SimpleNamespace(capture=lambda: captures.append(frame) or frame)
        navigator = Navigator(task, vision)
        navigator.classify = lambda _frame=None: next(states)
        navigator._handle_story_card_intermediate = lambda _frame: False
        navigator._match_story_sandbox_signals = lambda _frame: SandboxConfirmation(
            2,
            2,
            3,
            1,
        )

        result = navigator._wait_for_story_sandbox(1, timeout=2.0, interval=0.0)

        self.assertTrue(result.success)
        self.assertEqual(STORY_SANDBOX_STABLE_HITS, 2)
        self.assertEqual(6, len(captures))
