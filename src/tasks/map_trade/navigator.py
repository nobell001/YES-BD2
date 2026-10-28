from __future__ import annotations

from time import monotonic

import numpy as np

from src.tasks.map_trade.card_status import CardStatusDetector
from src.tasks.map_trade.models import COLLECTABLE_CARDS, MapPageMode, ScreenState
from src.tasks.map_trade.navigator_constants import (
    AREA_MAP_HEADER_TAGS,
    BARGAIN_CONFIRM_POINT,
    BARGAIN_POINT,
    CHAPTER_HOME_POINT,
    CLASSIFY_CARD_MENU_CATEGORY_RELATIVE_ROI,
    CLASSIFY_CARD_MENU_TITLE_RELATIVE_ROI,
    CLASSIFY_COOKING_MATERIALS_RELATIVE_ROI,
    CLASSIFY_COOKING_TITLE_RELATIVE_ROI,
    CLASSIFY_LOADING_RELATIVE_ROI,
    CLASSIFY_SHOP_TABS_RELATIVE_ROI,
    CLASSIFY_SHOP_TITLE_RELATIVE_ROI,
    DISCOUNT_SHOP_CLOSE_DIALOG_REGION,
    DISCOUNT_SHOP_CLOSE_KEYWORDS,
    DISCOUNT_SHOP_CLOSE_POINT,
    DISCOUNT_SHOP_CLOSE_TIMEOUT,
    FIRST_CARD_CONFIRM_REGION,
    FIRST_CARD_INSERT_REGION,
    FIRST_CARD_SKIP_TEMPLATE,
    HOME_DIMMED_P95_THRESHOLD,
    LOADING_TEMPLATE,
    MERCHANT_PROMPT_FAILURE_MESSAGE,
    MERCHANT_PROMPT_PATTERN,
    PROBE_QUICK_SWITCH_SCROLL_AMOUNT,
    PROBE_QUICK_SWITCH_SCROLL_COUNT,
    PROBE_QUICK_SWITCH_SCROLL_INTERVAL_SECONDS,
    PROBE_QUICK_SWITCH_SCROLL_POINT,
    PROBE_QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
    PROBE_QUICK_SWITCH_SCROLL_STEPS,
    PROBE_STORY_BADGE_CONFIRM_SECONDS,
    Q_SP6_BARGAIN_CLICK_DELAY,
    Q_SP6_BARGAIN_OCR_TIMEOUT,
    Q_SP6_BARGAIN_RECHECK_DELAY,
    Q_SP6_SHOP_PRIORITY_TIMEOUT,
    QUICK_SWITCH_CARTRIDGE_REGION,
    QUICK_SWITCH_PAGE_KEYWORDS,
    QUICK_SWITCH_SCROLL_FOCUS_POINT,
    QUICK_SWITCH_SCROLL_INTERVAL,
    QUICK_SWITCH_SCROLL_POINT,
    QUICK_SWITCH_SCROLL_RESET_AMOUNT,
    QUICK_SWITCH_SCROLL_RESET_COUNT,
    QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
    QUICK_SWITCH_SCROLL_UP_AMOUNT,
    QUICK_SWITCH_SCROLL_UP_COUNT,
    QUICK_SWITCH_TEMPLATE,
    RETURN_HOME_ANNOUNCEMENT_KEYWORD_GROUPS,
    RETURN_HOME_ANNOUNCEMENT_MAX_CLICKS,
    RETURN_HOME_ANNOUNCEMENT_OCR_INTERVAL,
    RETURN_HOME_ANNOUNCEMENT_OCR_REGION,
    RETURN_HOME_TIMEOUT,
    SANDBOX_CONFIRM_ACTION_TEMPLATES,
    SANDBOX_LARGE_MAP_FOOTER_OCR_RELATIVE_ROI,
    SANDBOX_LARGE_MAP_LEFT_TEMPLATE,
    SANDBOX_LARGE_MAP_RIGHT_TEMPLATE,
    SANDBOX_NAVIGATION_PAGE_KEYWORDS,
    SANDBOX_SKILL_GROUP_PIXEL_SCORE,
    SANDBOX_SKILL_GROUP_TEMPLATE_SCORE,
    SANDBOX_SKILL_SELECTED_YELLOW_MIN_RATIO,
    SANDBOX_SKILL_SLOT_1_CENTER_ROI,
    SANDBOX_SKILL_SLOT_1_REFERENCE_CENTER,
    SANDBOX_SKILL_SLOT_1_RELATIVE_POINT,
    SANDBOX_SKILL_SLOT_1_SELECTED_TEMPLATE,
    SANDBOX_SKILL_SLOT_1_UNSELECTED_TEMPLATE,
    SANDBOX_SKILL_SLOT_2_CENTER_ROI,
    SANDBOX_SKILL_SLOT_2_SELECTED_TEMPLATE,
    SANDBOX_SKILL_SLOT_2_UNSELECTED_TEMPLATE,
    SANDBOX_SKILL_STATE_TEMPLATES,
    SANDBOX_SKILL_UNSELECTED_YELLOW_MAX_RATIO,
    SANDBOX_TELEPORT_SKILL_TEMPLATE,
    SANDBOX_TEMPLATES,
    FIELD_ALL_KEYCAP_TEMPLATES,
    FIELD_KEYCAP_MIN_PASSES,
    SHOP_PAGE_OCR_KEYWORDS,
    STORY_BADGE_CANDIDATE_ZNCC_SCORE,
    STORY_BADGE_ENCODED_MIN_MARGIN,
    STORY_BADGE_ENCODED_OCR_MARGIN,
    STORY_BADGE_NATIVE_RUNNER_MAX_GAP,
    STORY_BADGE_ENCODED_PIXEL_SCORE,
    STORY_BADGE_ENCODED_TEMPLATE_SCORE,
    STORY_BADGE_ENCODED_ZNCC_SCORE,
    STORY_BADGE_MIN_MARGIN,
    STORY_BADGE_OCR_MIN_CONFIDENCE,
    STORY_BADGE_PIXEL_SCORE,
    STORY_BADGE_SPECS,
    STORY_BADGE_TEMPLATE_SCORE,
    STORY_CATEGORY_HIGHLIGHT_MIN_RATIO,
    STORY_CATEGORY_HIGHLIGHT_REGION,
    STORY_CATEGORY_POINT,
    STORY_SANDBOX_STABLE_HITS,
    STORY_SANDBOX_SWITCH_WINDOW,
    TELEPORT_MAP_BACKWARD_TEMPLATE,
    TELEPORT_MAP_DIRECT_HEADER_TEMPLATE,
    TELEPORT_MAP_FORWARD_TEMPLATE,
    TELEPORT_MAP_GENERATE_HEADER_TEMPLATE,
    TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI,
    TELEPORT_MAP_RETURN_RELATIVE_POINT,
    TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI,
    TRADE_MERCHANT_OPTIONS_REGION,
    TRADE_MERCHANT_TALENTS_REGION,
    TRADE_STORY_NUMBER,
    LocatedStoryCard,
    MapPageDetection,
    ProbedStoryCard,
    SandboxConfirmation,
    StoryBadgeCandidate,
    StoryBadgeDetection,
)
from src.tasks.map_trade.navigator_sandbox import SandboxNavigationMixin
from src.tasks.map_trade.navigator_story import StoryCardNavigationMixin
from src.tasks.map_trade.navigator_trade import TradeNavigationMixin
from src.tasks.map_trade.vision import Vision, normalize_text
from src.utils.home_confirmation import (
    HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT,
    HOME_GACHA_OCR_RELATIVE_ROI,
    HOME_LEFT_COLUMN_OCR_RELATIVE_ROI,
    HOME_LEFT_COLUMN_REQUIRED_HITS,
    home_confirmation_passes,
    home_gacha_ocr_with_fallback,
    home_left_column_hits,
    home_left_column_brightness,
)
from src.utils.ocr_utils import keyword_read
from src.utils.wait_limits import LOADING_MAX_SECONDS, STUCK_SECONDS, is_loading_dark, load_wait, scene_at_press

__all__ = [
    "BARGAIN_CONFIRM_POINT",
    "BARGAIN_POINT",
    "CHAPTER_HOME_POINT",
    "DISCOUNT_SHOP_CLOSE_DIALOG_REGION",
    "DISCOUNT_SHOP_CLOSE_KEYWORDS",
    "DISCOUNT_SHOP_CLOSE_POINT",
    "DISCOUNT_SHOP_CLOSE_TIMEOUT",
    "FIRST_CARD_CONFIRM_REGION",
    "FIRST_CARD_INSERT_REGION",
    "FIRST_CARD_SKIP_TEMPLATE",
    "LocatedStoryCard",
    "MERCHANT_PROMPT_FAILURE_MESSAGE",
    "MERCHANT_PROMPT_PATTERN",
    "PROBE_QUICK_SWITCH_SCROLL_AMOUNT",
    "PROBE_QUICK_SWITCH_SCROLL_COUNT",
    "PROBE_QUICK_SWITCH_SCROLL_INTERVAL_SECONDS",
    "PROBE_QUICK_SWITCH_SCROLL_POINT",
    "PROBE_QUICK_SWITCH_SCROLL_SETTLE_SECONDS",
    "PROBE_QUICK_SWITCH_SCROLL_STEPS",
    "PROBE_STORY_BADGE_CONFIRM_SECONDS",
    "ProbedStoryCard",
    "QUICK_SWITCH_CARTRIDGE_REGION",
    "QUICK_SWITCH_PAGE_KEYWORDS",
    "QUICK_SWITCH_SCROLL_FOCUS_POINT",
    "QUICK_SWITCH_SCROLL_INTERVAL",
    "QUICK_SWITCH_SCROLL_POINT",
    "QUICK_SWITCH_SCROLL_RESET_AMOUNT",
    "QUICK_SWITCH_SCROLL_RESET_COUNT",
    "QUICK_SWITCH_SCROLL_SETTLE_SECONDS",
    "QUICK_SWITCH_SCROLL_UP_AMOUNT",
    "QUICK_SWITCH_SCROLL_UP_COUNT",
    "QUICK_SWITCH_TEMPLATE",
    "Q_SP6_BARGAIN_CLICK_DELAY",
    "Q_SP6_BARGAIN_OCR_TIMEOUT",
    "Q_SP6_BARGAIN_RECHECK_DELAY",
    "Q_SP6_SHOP_PRIORITY_TIMEOUT",
    "TRADE_STORY_NUMBER",
    "RETURN_HOME_TIMEOUT",
    "SANDBOX_CONFIRM_ACTION_TEMPLATES",
    "SANDBOX_SKILL_GROUP_PIXEL_SCORE",
    "SANDBOX_SKILL_GROUP_TEMPLATE_SCORE",
    "SANDBOX_SKILL_SELECTED_YELLOW_MIN_RATIO",
    "SANDBOX_SKILL_SLOT_1_CENTER_ROI",
    "SANDBOX_SKILL_SLOT_1_REFERENCE_CENTER",
    "SANDBOX_SKILL_SLOT_1_RELATIVE_POINT",
    "SANDBOX_SKILL_SLOT_1_SELECTED_TEMPLATE",
    "SANDBOX_SKILL_SLOT_1_UNSELECTED_TEMPLATE",
    "SANDBOX_SKILL_SLOT_2_CENTER_ROI",
    "SANDBOX_SKILL_SLOT_2_SELECTED_TEMPLATE",
    "SANDBOX_SKILL_SLOT_2_UNSELECTED_TEMPLATE",
    "SANDBOX_SKILL_STATE_TEMPLATES",
    "SANDBOX_SKILL_UNSELECTED_YELLOW_MAX_RATIO",
    "SANDBOX_TELEPORT_SKILL_TEMPLATE",
    "STORY_BADGE_CANDIDATE_ZNCC_SCORE",
    "STORY_BADGE_ENCODED_MIN_MARGIN",
    "STORY_BADGE_ENCODED_OCR_MARGIN",
    "STORY_BADGE_NATIVE_RUNNER_MAX_GAP",
    "STORY_BADGE_ENCODED_PIXEL_SCORE",
    "STORY_BADGE_ENCODED_TEMPLATE_SCORE",
    "STORY_BADGE_ENCODED_ZNCC_SCORE",
    "STORY_BADGE_MIN_MARGIN",
    "STORY_BADGE_OCR_MIN_CONFIDENCE",
    "STORY_BADGE_PIXEL_SCORE",
    "STORY_BADGE_SPECS",
    "STORY_BADGE_TEMPLATE_SCORE",
    "STORY_CATEGORY_HIGHLIGHT_MIN_RATIO",
    "STORY_CATEGORY_HIGHLIGHT_REGION",
    "STORY_CATEGORY_POINT",
    "STORY_SANDBOX_STABLE_HITS",
    "STORY_SANDBOX_SWITCH_WINDOW",
    "SandboxConfirmation",
    "StoryBadgeCandidate",
    "StoryBadgeDetection",
    "TELEPORT_MAP_RETURN_RELATIVE_POINT",
    "TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI",
]




# Bottom label of a teleport-map page ("战斗Ⅰ 华特波尔雪山"), 1920x1080 fractions.
TELEPORT_MAP_PAGE_LABEL_RELATIVE_ROI = (640 / 1920, 950 / 1080, 1280 / 1920, 1030 / 1080)


class Navigator(StoryCardNavigationMixin, SandboxNavigationMixin, TradeNavigationMixin):
    def __init__(self, task, vision: Vision) -> None:
        self.task = task
        self.vision = vision
        self.card_status = CardStatusDetector(vision)

    def _map_page_template_signal(
        self,
        frame: np.ndarray,
        spec,
    ) -> tuple[bool, str]:
        result = self.vision.match(frame, spec)
        passed = self.vision.passes(result, spec)
        return passed, (
            f"{spec.name}={'pass' if passed else 'miss'}"
            f"(m={result.score:.3f},p={result.pixel_score:.3f},z={result.zncc_score:.3f})"
        )

    @staticmethod
    def _known_story_map_title_in_text(normalized_text: str) -> bool:
        return any(
            normalize_text(title) in normalized_text
            for card in COLLECTABLE_CARDS
            for target in card.targets
            for title in target.titles
        )

    def _detect_map_page_mode(self, frame: np.ndarray) -> MapPageDetection:
        """Identify the three visually distinct map pages from one frame."""

        try:
            header_text = self.vision.simplify(
                self.vision.ocr_text(
                    frame,
                    "地图页面左上标题",
                    relative_roi=TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI,
                )
            )
        except Exception as exc:
            self._status("地图页面左上标题 OCR错误", str(exc))
            return MapPageDetection(MapPageMode.UNKNOWN)

        normalized_header = normalize_text(header_text)
        evidence: list[str] = []
        mode = MapPageMode.UNKNOWN
        footer_text = ""
        if normalize_text("移动魔法阵") in normalized_header:
            direct, direct_evidence = self._map_page_template_signal(
                frame,
                TELEPORT_MAP_DIRECT_HEADER_TEMPLATE,
            )
            generated, generated_evidence = self._map_page_template_signal(
                frame,
                TELEPORT_MAP_GENERATE_HEADER_TEMPLATE,
            )
            left, left_evidence = self._map_page_template_signal(
                frame,
                TELEPORT_MAP_FORWARD_TEMPLATE,
            )
            right, right_evidence = self._map_page_template_signal(
                frame,
                TELEPORT_MAP_BACKWARD_TEMPLATE,
            )
            evidence.extend(
                (direct_evidence, generated_evidence, left_evidence, right_evidence)
            )
            has_legend = normalize_text("传说") in normalized_header
            has_teleport_structure = left or right
            if not has_teleport_structure and direct and not generated:
                # On bright pages (华特波尔雪山, snow) the white arrows fail
                # their templates (live 2K 2026-09-29); the page's own label
                # "战斗Ⅰ 华特波尔雪山" / "安全 …" proves the same structure.
                footer_text = self.vision.simplify(
                    self.vision.ocr_text(
                        frame,
                        "传送阵页面底部标签",
                        relative_roi=TELEPORT_MAP_PAGE_LABEL_RELATIVE_ROI,
                    )
                )
                page_label = normalize_text(footer_text)
                has_teleport_structure = "战斗" in page_label or "安全" in page_label
                evidence.append(f"页面标签={footer_text or '-'}")
            if direct and not generated and not has_legend and has_teleport_structure:
                mode = MapPageMode.DIRECT_TELEPORT
            elif generated and not direct and has_legend and has_teleport_structure:
                mode = MapPageMode.GENERATE_TELEPORT
        elif self._known_story_map_title_in_text(normalized_header) or any(
            tag in normalized_header for tag in AREA_MAP_HEADER_TAGS
        ):
            # A map outside the cards' own titles, such as a chapter's
            # hunting ground (player 1080p 2026-10-23, 第9章 「战斗 守山人休息处」):
            # its 战斗/安全 tag counts as well, the footer words and arrows
            # below still decide.  The page was never confirmed, so its
            # circle was not searched and the map was not closed.
            try:
                footer_text = self.vision.simplify(
                    self.vision.ocr_text(
                        frame,
                        "箱庭大地图底部控件",
                        relative_roi=SANDBOX_LARGE_MAP_FOOTER_OCR_RELATIVE_ROI,
                    )
                )
            except Exception as exc:
                self._status("箱庭大地图底部控件 OCR错误", str(exc))
                footer_text = ""
            normalized_footer = normalize_text(footer_text)
            keyword_hits = sum(
                normalize_text(keyword) in normalized_footer
                for keyword in SANDBOX_NAVIGATION_PAGE_KEYWORDS
            )
            evidence.append(f"箱庭大地图关键词={keyword_hits}/3")
            if keyword_hits >= 2:
                left, left_evidence = self._map_page_template_signal(
                    frame,
                    SANDBOX_LARGE_MAP_LEFT_TEMPLATE,
                )
                right, right_evidence = self._map_page_template_signal(
                    frame,
                    SANDBOX_LARGE_MAP_RIGHT_TEMPLATE,
                )
                evidence.extend((left_evidence, right_evidence))
                # The first page has no left arrow and the last no right one
                # (live 2K 2026-09-30, 科库托斯研究设施 page 1 of 3: "unknown", so
                # its teleport icon was never searched and the map never closed).
                if left or right:
                    mode = MapPageMode.SANDBOX_LARGE_MAP
                elif keyword_hits == len(SANDBOX_NAVIGATION_PAGE_KEYWORDS):
                    # On snow (华特波尔雪山, YES-BD2 #24 at 1080p) both white
                    # arrows miss their templates; the map's own title plus
                    # all three footer words prove the page as well.
                    evidence.append("箭头未命中，标题与底部三词确认")
                    mode = MapPageMode.SANDBOX_LARGE_MAP

        self._status(
            "地图页面模式",
            (
                f"mode={mode.value}; header={header_text or '-'}; "
                f"footer={footer_text or '-'}; {'; '.join(evidence) or 'no-evidence'}"
            ),
        )
        return MapPageDetection(
            mode,
            header_text=header_text,
            footer_text=footer_text,
            evidence=tuple(evidence),
        )

    def classify(self, frame=None) -> ScreenState:
        """Classify shared map states without trade- or PVP-specific templates."""

        started = monotonic()
        state = self._classify_frame(frame)
        self._status("界面分类耗时", f"{monotonic() - started:.3f}s")
        return state

    def _classify_frame(self, frame) -> ScreenState:
        frame = self.vision.capture() if frame is None else frame
        if self._home_confirmation_signals(frame)[0]:
            return ScreenState.HOME
        if self.vision.match(frame, LOADING_TEMPLATE).score >= self.vision.threshold_for(
            LOADING_TEMPLATE
        ):
            return ScreenState.LOADING
        sandbox_signals = []
        sandbox_confirmed = False
        for spec in SANDBOX_TEMPLATES:
            result = self.vision.match(frame, spec)
            passed = self.vision.passes(result, spec)
            sandbox_confirmed = sandbox_confirmed or passed
            sandbox_signals.append(
                (
                    f"{spec.name}={'pass' if passed else 'miss'}"
                    f"(m={result.score:.3f},p={result.pixel_score:.3f},"
                    f"z={result.zncc_score:.3f})"
                )
            )
        if not sandbox_confirmed:
            keycaps = [self.vision.match(frame, spec) for spec in FIELD_ALL_KEYCAP_TEMPLATES]
            sandbox_confirmed = (
                sum(
                    self.vision.passes(result, spec)
                    for result, spec in zip(keycaps, FIELD_ALL_KEYCAP_TEMPLATES)
                )
                >= FIELD_KEYCAP_MIN_PASSES
            )
            sandbox_signals.append(
                "按键CHMQ="
                + ("pass" if sandbox_confirmed else "miss")
                + "("
                + ",".join(f"{r.score:.2f}/{r.pixel_score:.2f}" for r in keycaps)
                + ")"
            )
        self._status("箱庭确认信号", "; ".join(sandbox_signals))
        if sandbox_confirmed:
            return ScreenState.SANDBOX

        loading_text = normalize_text(
            self.vision.simplify(
                self.vision.ocr_text(
                    frame,
                    "界面分类加载",
                    relative_roi=CLASSIFY_LOADING_RELATIVE_ROI,
                )
            )
        )
        if "browndust" in loading_text:
            return ScreenState.LOADING
        if loading_text:
            # The loading screen and the arrival banner name the new map in
            # this top-left area; kept so arrival needs no map page (Leo
            # 2026-09-29: the name is already shown while switching).
            self.last_loading_title = loading_text
        if getattr(self, "_field_wait_only", False):
            # Waiting for the field after a teleport or entry: only field /
            # loading matter there, so the shop, map-page, card and cooking
            # reads (~2 s a frame at 2K, 10-12) are left for a failure.
            self._field_wait_cut = True
            return ScreenState.UNKNOWN
        shop_text = normalize_text(
            self.vision.simplify(
                self.vision.ocr_text(
                    frame,
                    "界面分类商店页",
                    relative_roi=CLASSIFY_SHOP_TABS_RELATIVE_ROI,
                )
                + " "
                + self.vision.ocr_text(
                    frame,
                    "界面分类商店标题",
                    relative_roi=CLASSIFY_SHOP_TITLE_RELATIVE_ROI,
                )
            )
        )
        if self._shop_page_text(shop_text):
            return ScreenState.SHOP
        map_page = self._detect_map_page_mode(frame)
        if map_page.mode.is_teleport_map:
            return ScreenState.AREA_MAP
        if map_page.mode == MapPageMode.SANDBOX_LARGE_MAP:
            return ScreenState.SANDBOX_MAP
        card_text = normalize_text(
            self.vision.simplify(
                self.vision.ocr_text(
                    frame,
                    "界面分类卡带标题",
                    relative_roi=CLASSIFY_CARD_MENU_TITLE_RELATIVE_ROI,
                )
                + " "
                + self.vision.ocr_text(
                    frame,
                    "界面分类卡带页",
                    relative_roi=CLASSIFY_CARD_MENU_CATEGORY_RELATIVE_ROI,
                )
            )
        )
        if "游戏卡珍藏" in card_text or "剧情游戏卡" in card_text:
            return ScreenState.CARD_MENU
        cooking_text = normalize_text(
            self.vision.simplify(
                self.vision.ocr_text(
                    frame,
                    "界面分类料理标题",
                    relative_roi=CLASSIFY_COOKING_TITLE_RELATIVE_ROI,
                )
                + " "
                + self.vision.ocr_text(
                    frame,
                    "界面分类料理材料",
                    relative_roi=CLASSIFY_COOKING_MATERIALS_RELATIVE_ROI,
                )
            )
        )
        if "所需材料" in cooking_text and "料理" in cooking_text:
            return ScreenState.COOKING
        return ScreenState.UNKNOWN

    def classify_trade(self, frame=None) -> ScreenState:
        """Classify trade-only merchant context before falling back to shared states."""

        started = monotonic()
        state = self._classify_trade_frame(frame)
        self._status("跑商界面分类耗时", f"{monotonic() - started:.3f}s")
        return state

    def _classify_trade_frame(self, frame) -> ScreenState:
        frame = self.vision.capture() if frame is None else frame
        if self._home_confirmation_signals(frame)[0]:
            return ScreenState.HOME

        # 交互菜单也含仓库标题，直接落回共享分类会被商店分支命中；
        # 须先用同帧交互选项与技能卡确认商人身份。
        if self._merchant_menu_in_frame(frame):
            return ScreenState.MERCHANT_DIALOG
        return self.classify(frame)

    def _merchant_menu_in_frame(self, frame) -> bool:
        """The merchant's 对话/商店 menu: its option bubbles and talent cards."""
        options_passed, _ = self._ocr_keywords_in_frame(
            frame,
            ("对话", "商店"),
            "跑商商人交互选项",
            relative_roi=TRADE_MERCHANT_OPTIONS_REGION,
        )
        if not options_passed:
            return False
        talents_passed, _ = self._ocr_keywords_in_frame(
            frame,
            ("天赋技能", "选择"),
            "跑商商人天赋技能",
            relative_roi=TRADE_MERCHANT_TALENTS_REGION,
        )
        return bool(talents_passed)

    @staticmethod
    def _shop_page_text(text: str) -> bool:
        """Judge the discount shop page from one frame's normalized OCR text."""
        return all(keyword in text for keyword in SHOP_PAGE_OCR_KEYWORDS) or (
            "购买" in text and "出售" in text
        )

    def wait_state(self, wanted: set[ScreenState], timeout: float) -> ScreenState:
        end_at = monotonic() + max(0.0, timeout)
        # A full-length wait spans a loading screen: a load wait (Leo
        # 2026-10-15 「你單純等載入怎麼可以改成只等10秒」).  A shorter one is a
        # quick look and stays as given.
        wait = load_wait(monotonic(), timeout, before=scene_at_press(self.task)) if timeout >= STUCK_SECONDS else None
        last = ScreenState.UNKNOWN
        announcement_clicks = 0
        while True:
            frame = self.vision.capture()
            last = self.classify(frame)
            self._status("导航状态", last.value)
            if last in wanted:
                return last
            if wait is not None:
                loading = last == ScreenState.LOADING or is_loading_dark(frame)
                if wait.over(frame, monotonic(), loading=loading):
                    return last
            elif monotonic() > end_at:
                return last
            # A loading screen can end on home under an update notice, which
            # never classifies as HOME: the wait ran its full 45 s (live 2K
            # 2026-09-29, leaving the event).  Clear a verified notice.
            if (
                last == ScreenState.UNKNOWN
                and ScreenState.HOME in wanted
                and self.clear_home_announcement(frame, announcement_clicks)
            ):
                announcement_clicks += 1
            self.task.sleep(0.5)

    def clear_home_announcement(self, frame, clicks_so_far: int = 0) -> bool:
        """Click away a verified update notice over home; True when clicked."""

        if clicks_so_far >= RETURN_HOME_ANNOUNCEMENT_MAX_CLICKS:
            return False
        if self._clear_return_home_announcement_if_needed(
            frame, brightness=home_left_column_brightness(frame)
        ):
            return True
        # Posters change and can stack (Leo 2026-09-29), so a poster whose
        # text is unknown is judged by home itself: its labels and 抽抽乐 read
        # through the dimming.  Same rule as the login/claim home checks.
        _confirmed, left_hits, p95, gacha = self._home_confirmation_signals(frame)
        clear = getattr(self.task, "clear_temporary_home_announcement_if_needed", None)
        return bool(
            callable(clear)
            and clear(
                left_hits=left_hits,
                required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                brightness=p95,
                brightness_threshold=HOME_DIMMED_P95_THRESHOLD,
                gacha_ocr_text=gacha,
                context="回到主页",
            )
        )

    def _loading_timeout(self) -> float:
        # Leo 2026-10-15 「你單純等載入怎麼可以改成只等10秒」: a loading screen
        # gets at least LOADING_MAX_SECONDS; the saved setting only lengthens it.
        try:
            seconds = float(self.task.config.get("加载页面等待秒数", LOADING_MAX_SECONDS))
        except (TypeError, ValueError):
            seconds = LOADING_MAX_SECONDS
        return max(LOADING_MAX_SECONDS, seconds)

    def _wait_for_cartridge_home(
        self,
        timeout: float = 10.0,
        interval: float = 0.35,
        *,
        allow_return_announcement_cleanup: bool = False,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        # Leaving a field for home passes the loading screen: a full-length
        # wait is a load wait (Leo 2026-10-15 「一定會超過10秒甚至15秒」).
        wait = load_wait(monotonic(), timeout, before=scene_at_press(self.task)) if timeout >= STUCK_SECONDS else None
        last_left_hits = 0
        last_p95 = 0.0
        last_gacha_text = ""
        announcement_clicks = 0
        while wait is not None or monotonic() <= end_at:
            frame = self.vision.capture()
            if wait is not None and is_loading_dark(frame):
                if wait.over(frame, monotonic(), loading=True):
                    break
                self.task.sleep(interval)
                continue
            (
                confirmed,
                last_left_hits,
                last_p95,
                last_gacha_text,
            ) = self._home_confirmation_signals(
                frame,
                clear_context=(
                    None
                    if allow_return_announcement_cleanup
                    else "跑商/跑图确认主页"
                ),
            )
            if confirmed:
                return True
            if wait is not None and wait.over(frame, monotonic()):
                break
            return_announcement_detected = (
                allow_return_announcement_cleanup
                and self._clear_return_home_announcement_if_needed(
                    frame,
                    brightness=last_p95,
                    allow_click=(
                        announcement_clicks < RETURN_HOME_ANNOUNCEMENT_MAX_CLICKS
                    ),
                )
            )
            if return_announcement_detected:
                if announcement_clicks < RETURN_HOME_ANNOUNCEMENT_MAX_CLICKS:
                    announcement_clicks += 1
                self.task.sleep(RETURN_HOME_ANNOUNCEMENT_OCR_INTERVAL)
                continue
            if allow_return_announcement_cleanup:
                clear_announcement = getattr(
                    self.task,
                    "clear_temporary_home_announcement_if_needed",
                    None,
                )
                if callable(clear_announcement) and clear_announcement(
                    left_hits=last_left_hits,
                    required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                    brightness=last_p95,
                    brightness_threshold=HOME_DIMMED_P95_THRESHOLD,
                    gacha_ocr_text=last_gacha_text,
                    context="跑商/跑图确认主页",
                ):
                    self.task.sleep(interval)
                    continue
            self.task.sleep(interval)
        self.task.log_warning(
            "跑商：未同时确认左列关键词、亮度和抽抽乐文字，"
            f"left={last_left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}, "
            f"p95={last_p95:.0f}/{HOME_DIMMED_P95_THRESHOLD:.0f}, ocr={last_gacha_text or '-'}。"
        )
        return False

    def _clear_return_home_announcement_if_needed(
        self,
        frame: np.ndarray,
        *,
        brightness: float,
        allow_click: bool = True,
    ) -> bool:
        """Dismiss a verified update notice only inside an explicit home return."""

        if brightness >= HOME_DIMMED_P95_THRESHOLD:
            return False
        text = self.vision.ocr_text(
            frame,
            "返回主页公告",
            relative_roi=RETURN_HOME_ANNOUNCEMENT_OCR_REGION,
        )
        normalized = normalize_text(self.vision.simplify(text))
        matched_group = next(
            (
                keywords
                for keywords in RETURN_HOME_ANNOUNCEMENT_KEYWORD_GROUPS
                if all(
                    normalize_text(self.vision.simplify(keyword)) in normalized
                    for keyword in keywords
                )
            ),
            None,
        )
        self._status("返回主页公告 OCR", text or "-")
        if matched_group is None:
            return False
        if not allow_click:
            self._status(
                "返回主页公告清理",
                f"已达到{RETURN_HOME_ANNOUNCEMENT_MAX_CLICKS}次上限",
            )
            return True
        self.task.log_info(
            "跑商：返回主页时确认更新公告遮挡，点击公告清理位置后重新严格确认主页，"
            f"keywords={'+'.join(matched_group)}, p95={brightness:.0f}。"
        )
        self.task.operate_click(
            *HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT,
            after_sleep=0.2,
        )
        return True

    def _home_confirmation_signals(
        self,
        frame: np.ndarray,
        clear_context: str | None = None,
    ) -> tuple[bool, int, float, str]:
        left_text = self.vision.ocr_text(
            frame,
            "主页左列",
            relative_roi=HOME_LEFT_COLUMN_OCR_RELATIVE_ROI,
        )
        left_hits = home_left_column_hits(left_text)
        p95_brightness = home_left_column_brightness(frame)
        if clear_context is None and left_hits < HOME_LEFT_COLUMN_REQUIRED_HITS:
            # Home needs the left column too: without it the three 抽抽乐
            # reads (x1/x2/x3) cannot change the answer (163 of them in one
            # 跑图 at 4K 2026-10-14, each screen check 0.6-0.8 s).
            gacha_text = ""
        else:
            gacha_text = home_gacha_ocr_with_fallback(
                lambda scale: self.vision.ocr_text(
                    frame,
                    f"主页抽抽乐 x{scale:g}",
                    relative_roi=HOME_GACHA_OCR_RELATIVE_ROI,
                    ocr_scale=scale,
                )
            ).text
        self._status(
            "主页左列关键词",
            f"{left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}",
        )
        self._status("主页亮度p95", f"{p95_brightness:.0f}")
        self._status("主页抽抽乐 OCR", gacha_text or "-")
        confirmed = home_confirmation_passes(
            left_hits=left_hits,
            required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
            brightness=p95_brightness,
            brightness_threshold=HOME_DIMMED_P95_THRESHOLD,
            gacha_ocr_text=gacha_text,
        )
        clear_announcement = getattr(
            self.task,
            "clear_temporary_home_announcement_if_needed",
            None,
        )
        if clear_context is not None and not confirmed and callable(clear_announcement):
            clear_announcement(
                left_hits=left_hits,
                required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                brightness=p95_brightness,
                brightness_threshold=HOME_DIMMED_P95_THRESHOLD,
                gacha_ocr_text=gacha_text,
                context=clear_context,
            )
        return (
            confirmed,
            left_hits,
            p95_brightness,
            gacha_text,
        )

    def _wait_for_ocr_keywords(
        self,
        keywords: tuple[str, ...],
        timeout: float,
        name: str,
        interval: float = 0.5,
        relative_roi: tuple[float, float, float, float] | None = None,
        quiet: bool = False,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        while monotonic() <= end_at:
            frame = self.vision.capture()
            matched, text = self._ocr_keywords_in_frame(
                frame,
                keywords,
                name,
                relative_roi=relative_roi,
            )
            last_text = text or last_text
            if matched:
                return True
            self.task.sleep(interval)
        if not quiet:
            self.task.log_warning(f"跑商：{name} OCR确认超时，OCR={last_text or '-'}。")
        return False

    def _ocr_keywords_in_frame(
        self,
        frame: np.ndarray,
        keywords: tuple[str, ...],
        name: str,
        relative_roi: tuple[float, float, float, float] | None = None,
    ) -> tuple[bool, str]:
        required = tuple(normalize_text(self.vision.simplify(value)) for value in keywords)
        if relative_roi is None:
            text = self.vision.ocr_text(frame, name)
        else:
            text = self.vision.ocr_text(
                frame,
                name,
                relative_roi=relative_roi,
            )
        normalized = normalize_text(self.vision.simplify(text))
        matched = sum(keyword_read(value, normalized) for value in required)
        self._status(f"{name} OCR命中", f"{matched}/{len(required)}")
        return matched == len(required), text

    @staticmethod
    def _ocr_box_center(box) -> tuple[int, int] | None:
        values = [getattr(box, key, None) for key in ("x", "y", "width", "height")]
        raw_box = getattr(box, "box", None)
        if any(value is None for value in values) and raw_box is not None and len(raw_box) >= 4:
            values = list(raw_box[:4])
        if any(value is None for value in values):
            return None
        x, y, width, height = (float(value) for value in values)
        if width <= 0 or height <= 0:
            return None
        return round(x + width / 2), round(y + height / 2)

    def _status(self, key: str, value) -> None:
        try:
            self.task.info_set(key, value)
        except AttributeError:
            pass

    def _note_progress(self) -> None:
        """A wait read its target: not stuck (FrozenWatch.progress)."""
        note = getattr(self.task, "note_progress", None)
        if callable(note):
            note()
