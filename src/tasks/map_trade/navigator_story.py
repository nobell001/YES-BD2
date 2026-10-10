from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace
from math import ceil
from statistics import median
from time import monotonic

import cv2
import numpy as np

from src.tasks.map_trade import event_card_art, story_card_art
from src.tasks.map_trade.card_status import (
    CardActionState,
    CollectionCardSelectionOutcome,
    CollectionCardSelectionResult,
)
from src.tasks.map_trade.models import (
    CARD_BY_ID,
    SUPPRESS_ONLY_VERIFIED_CARD_IDS,
    MatchResult,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator_constants import (
    CHARACTER_BADGE_FIRST_X,
    CHARACTER_BADGE_MIN_MARGIN,
    CHARACTER_BADGE_MIN_SCORE,
    CHARACTER_BADGE_SPACING,
    CHARACTER_BADGE_SPECS,
    CHARACTER_BADGE_WINDOW,
    CHARACTER_BADGE_Y,
    CHARACTER_CATEGORY_HIGHLIGHT_REGION,
    CHARACTER_CATEGORY_POINT,
    EVENT_CARD_SCAN_SECONDS,
    EVENT_CATEGORY_HIGHLIGHT_REGION,
    EVENT_CATEGORY_POINT,
    FIRST_CARD_CONFIRM_REGION,
    FIRST_CARD_DIALOG_REGION,
    FIRST_CARD_INSERT_REGION,
    FIRST_CARD_PAID_DIALOG_MESSAGE,
    FIRST_CARD_PAID_WORDS,
    FIRST_CARD_SKIP_TEMPLATE,
    PROBE_QUICK_SWITCH_SCROLL_AMOUNT,
    PROBE_QUICK_SWITCH_SCROLL_COUNT,
    PROBE_QUICK_SWITCH_SCROLL_INTERVAL_SECONDS,
    PROBE_QUICK_SWITCH_SCROLL_POINT,
    PROBE_QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
    PROBE_STORY_BADGE_CONFIRM_SECONDS,
    QUICK_SWITCH_CARTRIDGE_REGION,
    QUICK_SWITCH_PAGE_KEYWORDS,
    QUICK_SWITCH_SCROLL_FOCUS_POINT,
    QUICK_SWITCH_SCROLL_INTERVAL,
    QUICK_SWITCH_SCROLL_POINT,
    QUICK_SWITCH_SCROLL_RESET_AMOUNT,
    QUICK_SWITCH_SCROLL_RESET_COUNT,
    QUICK_SWITCH_SCROLL_SCAN_STEPS,
    QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
    QUICK_SWITCH_SCROLL_UP_AMOUNT,
    QUICK_SWITCH_SCROLL_UP_COUNT,
    QUICK_SWITCH_TEMPLATE,
    FIELD_ALL_KEYCAP_TEMPLATES,
    FIELD_KEYCAP_MIN_PASSES,
    STORY_BADGE_CANDIDATE_SCORE,
    STORY_BADGE_CLUSTER_RADIUS,
    STORY_BADGE_ENCODED_MIN_MARGIN,
    STORY_BADGE_ENCODED_OCR_MARGIN,
    STORY_BADGE_ENCODED_PIXEL_SCORE,
    STORY_BADGE_ENCODED_TEMPLATE_SCORE,
    STORY_BADGE_ENCODED_ZNCC_SCORE,
    STORY_BADGE_GRID_ALIGNMENT_TOLERANCE_RATIO,
    STORY_BADGE_GRID_LOCAL_TOLERANCE_RATIO,
    STORY_BADGE_GRID_MAX_PAIR_GAP,
    STORY_BADGE_GRID_MAX_SPACING_RATIO,
    STORY_BADGE_GRID_MIN_ANCHORS,
    STORY_BADGE_GRID_MIN_COMBINED_MARGIN,
    STORY_BADGE_GRID_MIN_MARGIN,
    STORY_BADGE_GRID_MIN_SPACING_BADGE_RATIO,
    STORY_BADGE_GRID_MIN_SPACING_RATIO,
    STORY_BADGE_GRID_MIN_VISIBLE_FRACTION,
    STORY_BADGE_GRID_OCR_MARGIN,
    STORY_BADGE_GRID_PIXEL_SCORE,
    STORY_BADGE_GRID_REFERENCE_SCALE,
    STORY_BADGE_GRID_ROW_TOLERANCE_RATIO,
    STORY_BADGE_GRID_SPACING_RATIO,
    STORY_BADGE_GRID_STRONG_COMBINED_SCORE,
    STORY_BADGE_GRID_TEMPLATE_SCORE,
    STORY_BADGE_GRID_VERTICAL_TOLERANCE_RATIO,
    STORY_BADGE_GRID_ZNCC_SCORE,
    STORY_BADGE_MIN_MARGIN,
    STORY_BADGE_NATIVE_RUNNER_MAX_GAP,
    STORY_BADGE_OCR_BINARY_THRESHOLD,
    STORY_BADGE_OCR_HORIZONTAL_BORDER,
    STORY_BADGE_OCR_INNER_HEIGHT,
    STORY_BADGE_OCR_INNER_RADIUS_RATIO,
    STORY_BADGE_OCR_MIN_CONFIDENCE,
    STORY_BADGE_OCR_VERTICAL_BORDER,
    STORY_BADGE_PIXEL_SCORE,
    STORY_BADGE_SPECS,
    STORY_BADGE_TEMPLATE_SCORE,
    STORY_CATEGORY_HIGHLIGHT_MIN_RATIO,
    STORY_CATEGORY_HIGHLIGHT_REGION,
    STORY_CATEGORY_POINT,
    LocatedStoryCard,
    ProbedStoryCard,
    StoryBadgeCandidate,
    StoryBadgeDetection,
    StoryBadgeGrid,
)
from src.tasks.map_trade.vision import normalize_text
from src.utils.calibration import FHD_1080

# 从箱庭点击快速切换按钮的统一识别窗口与点击后停顿。
QUICK_SWITCH_CLICK_TIMEOUT = 10.0
# A confirmed quick-switch tab is trusted this long (checked lit again).
MENU_CONFIRM_REUSE_SECONDS = 8.0
# The badge's neighbourhood (badge sizes around it) must be this still
# (mean grey difference) to skip the second identification before a click.
BADGE_STILL_AREA_SCALE = 3.0
BADGE_STILL_MAX_DIFF = 4.0


def badge_area_unchanged(before, after, result) -> bool:
    if before is None or after is None or before.shape != after.shape:
        return False
    width, height = result.size
    if width <= 0 or height <= 0:
        return False
    cx, cy = (int(round(value)) for value in result.center)
    half_w = round(width * BADGE_STILL_AREA_SCALE / 2)
    half_h = round(height * BADGE_STILL_AREA_SCALE / 2)
    frame_h, frame_w = before.shape[:2]
    x0, x1 = max(0, cx - half_w), min(frame_w, cx + half_w)
    y0, y1 = max(0, cy - half_h), min(frame_h, cy + half_h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return False
    first = cv2.cvtColor(before[y0:y1, x0:x1, :3], cv2.COLOR_BGR2GRAY)
    second = cv2.cvtColor(after[y0:y1, x0:x1, :3], cv2.COLOR_BGR2GRAY)
    return float(cv2.absdiff(first, second).mean()) <= BADGE_STILL_MAX_DIFF
# Field P button (1080p 851,997) in the 1280x720 map-trade reference.
FIELD_QUICK_SWITCH_REFERENCE_POINT = (851 * 1280 / 1920, 997 * 720 / 1080)
QUICK_SWITCH_FALLBACK_AFTER = 3.0
QUICK_SWITCH_CLICK_AFTER_SLEEP = 1.0


# Wheel notches that move a card cut off at the quick bar's edge inward.
CARD_EDGE_SCROLL_ATTEMPTS = 2
# Quick-bar swipe (1920x1080 reference): hold the right half, slide left.
STORY_BAR_SWIPE_Y = 960
STORY_BAR_SWIPE_RIGHT_X = 1500
STORY_BAR_SWIPE_LEFT_X = 600
STORY_BAR_SWIPE_STEPS = 4
STORY_BAR_STILL_TIMEOUT = 2.5
STORY_BAR_STILL_DIFF = 2.0
# Wheel sign that shows larger card numbers.  Leo 2026-09-29 at 2K: the old -1
# reset went to the FRONT (card 1), so larger numbers are +1.
STORY_BAR_WHEEL_TOWARD_LARGER = 1
STORY_BAR_WHEEL_NOTCHES = 3
STORY_BAR_WHEEL_STEPS = 8
# Wheels or swipes in a row that leave the bar unmoved: that end is reached.
STORY_BAR_END_STILL_MOVES = 2
# Badge-number row of the quick bar (the card's own number, top-left of each
# card), below the 1..0 hotkey labels; 1080p rows.  Read at twice the 1080p
# size with a margin: the raw strip read nothing at any resolution, this read
# 7-9 of the ~10 badges on screen at 720p, 1080p, 2K and 4K (live 2K frame
# resized, 2026-09-30), in ~0.15 s against ~6 s for the badge templates.
STORY_BAR_NUMBER_TOP = 924
STORY_BAR_NUMBER_BOTTOM = 952
STORY_BAR_NUMBER_OCR_SCALE = 2.0
STORY_BAR_NUMBER_PAD = 16
STORY_CARD_COUNT = 20
# Badges sit 180 px apart (1080p); reads agreeing within 0.3 card are one bar
# position.  At least three must agree.
STORY_BAR_CARD_SPACING = 180.0
STORY_BAR_DIGIT_HALF_WIDTH = 6.0
STORY_BAR_OFFSET_TOLERANCE = 0.3
STORY_BAR_VISIBLE_MIN_READ = 3
# Badge x (1080p) where the whole card shows: card 1 at the start sits at 92,
# the half-cut card at the right edge at 1892.
STORY_BAR_VIEW_LEFT = 60.0
STORY_BAR_VIEW_RIGHT = 1720.0
STORY_BAR_VIEW_CENTER = 960.0
# Live 2K 2026-09-30: 3 notches moved the bar ~1.7 cards, 6 notches ~3.5.
STORY_BAR_NOTCHES_PER_CARD = 1.7
STORY_BAR_GUIDED_MAX_NOTCHES = 14
STORY_BAR_NUDGE_NOTCHES = 2
STORY_BAR_GUIDED_NUDGES = 2
STORY_BAR_GUIDED_STEPS = 8

class StoryCardNavigationMixin:
    def _wait_for_quick_switch_page(self, timeout: float = 10.0) -> bool:
        return self._wait_for_ocr_keywords(
            QUICK_SWITCH_PAGE_KEYWORDS,
            timeout,
            "卡带选择页",
        )

    def _badge_specs(self):
        """Number-badge templates of the tab being searched (set per card by
        _locate_story_card; story otherwise)."""
        if getattr(self, "_badge_category", "story") == "character":
            return CHARACTER_BADGE_SPECS
        return STORY_BADGE_SPECS

    @staticmethod
    def _card_category(category: str) -> tuple[str, tuple[float, float], tuple[float, ...]]:
        """(tab label, click point, highlight region) of a quick bar tab."""
        if category == "character":
            return "角色游戏卡", CHARACTER_CATEGORY_POINT, CHARACTER_CATEGORY_HIGHLIGHT_REGION
        if category == "event":
            return "活动游戏卡", EVENT_CATEGORY_POINT, EVENT_CATEGORY_HIGHLIGHT_REGION
        return "剧情游戏卡", STORY_CATEGORY_POINT, STORY_CATEGORY_HIGHLIGHT_REGION

    def _click_quick_switch(self, timeout: float, after_sleep: float) -> bool:
        """Press the field's quick-switch (P) button.

        The see-through button scores 0.69 on snow at 1080p (ch13 town, live
        2026-09-30) and the card could never be left.  When the template stays
        unseen but the opaque C/H key caps prove the field HUD, the button's
        calibrated place is pressed; the quick-switch page check that follows
        still has to pass.
        """
        first = min(QUICK_SWITCH_FALLBACK_AFTER, timeout)
        if self.vision.click_stable_template(
            QUICK_SWITCH_TEMPLATE, timeout=first, after_sleep=after_sleep
        ):
            return True
        frame = self.vision.capture()
        if (
            sum(
                self.vision.passes(self.vision.match(frame, spec), spec)
                for spec in FIELD_ALL_KEYCAP_TEMPLATES
            )
            >= FIELD_KEYCAP_MIN_PASSES
        ):
            self._status("快速切换按钮", "模板未命中，按键确认在箱庭，点击标定位置")
            self.vision.click_reference(*FIELD_QUICK_SWITCH_REFERENCE_POINT, after_sleep=after_sleep)
            return True
        return self.vision.click_stable_template(
            QUICK_SWITCH_TEMPLATE,
            timeout=max(0.0, timeout - first),
            after_sleep=after_sleep,
        )

    def _open_story_quick_switcher(self, category: str = "story") -> NavigationResult:
        opened = self.task.open_cartridge_quick_switcher(
            ensure_home=self._wait_for_cartridge_home,
            click_quick_switch=lambda: self._click_quick_switch(
                QUICK_SWITCH_CLICK_TIMEOUT, QUICK_SWITCH_CLICK_AFTER_SLEEP
            ),
            confirm_quick_switch_page=self._wait_for_quick_switch_page,
        )
        if not opened:
            return NavigationResult(
                False,
                self.classify(),
                "无法从主页打开快速切换卡带页面",
            )

        if not self._select_story_category(category):
            label = self._card_category(category)[0]
            return NavigationResult(
                False,
                self.classify(),
                f"点击后未确认{label}类别高亮",
            )
        return NavigationResult(
            True, ScreenState.CARD_MENU, f"{self._card_category(category)[0]}类别已确认"
        )

    def _wait_for_story_category(
        self,
        timeout: float = 3.0,
        interval: float = 0.5,
        *,
        category: str = "story",
        warn: bool = True,
    ) -> bool:
        label, _point, region = self._card_category(category)
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        last_highlight_ratio = 0.0
        wanted = normalize_text(label)
        while monotonic() <= end_at:
            frame = self.vision.capture()
            text = self.vision.simplify(self.vision.ocr_text(frame, f"{label}类别"))
            last_text = text or last_text
            last_highlight_ratio = self.vision.bright_neutral_ratio(frame, region)
            self._status(f"{label}类别高亮", f"{last_highlight_ratio:.3f}")
            if (
                wanted in normalize_text(text)
                and last_highlight_ratio >= STORY_CATEGORY_HIGHLIGHT_MIN_RATIO
            ):
                self._menu_confirmed = (monotonic(), category)
                return True
            self.task.sleep(interval)
        if warn:
            self.task.log_warning(
                f"跑商：未确认{label}类别高亮，"
                f"highlight={last_highlight_ratio:.3f}, OCR={last_text or '-'}。"
            )
        return False

    def _select_story_category(self, category: str = "story") -> bool:
        """Click and confirm the category before any quick-bar focus or scroll."""

        label, point, _region = self._card_category(category)
        self._status("导航状态", f"选择{label}")
        self.task.operate_click(*point, after_sleep=0.5)
        return self._wait_for_story_category(category=category)

    def _focus_quick_switch_for_scroll(self) -> None:
        """Focus the selected cartridge bar at the user-calibrated safe point."""

        self._status(
            "卡带滚轮聚焦",
            "已选择卡带类型，点击参考点(43,974)后开始滚动",
        )
        self.task.operate_click(*QUICK_SWITCH_SCROLL_FOCUS_POINT, after_sleep=0.0)

    def _story_badge_geometry(self, frame: np.ndarray):
        """Assess the quick-switch frame before using any badge as a target."""

        assess = getattr(self.vision, "assess_frame", None)
        self._last_story_badge_geometry = None
        self._last_story_badge_geometry_reason = ""
        if not callable(assess):
            return None
        try:
            geometry = assess(
                frame,
                required_relative_rois=(QUICK_SWITCH_CARTRIDGE_REGION,),
                purpose="剧情角标",
            )
        except (AttributeError, TypeError, ValueError) as exc:
            self._last_story_badge_geometry_reason = f"画面几何检查异常：{exc}"
            self._status("剧情角标几何", self._last_story_badge_geometry_reason)
            return False
        self._last_story_badge_geometry = geometry
        self._last_story_badge_geometry_reason = ""
        if not geometry.accepted:
            self._last_story_badge_geometry_reason = (
                "画面几何拒绝：" + "|".join(geometry.rejection_reasons)
            )
            self._status("剧情角标几何", self._last_story_badge_geometry_reason)
        return geometry

    def _story_badge_template_candidates(
        self,
        frame: np.ndarray,
        spec,
        *,
        peak_radius: int,
        geometry=None,
    ) -> tuple[MatchResult, ...]:
        """Collect weak response peaks while retaining the legacy adapter path."""

        evidence_matcher = getattr(self.vision, "match_evidence_all", None)
        if callable(evidence_matcher):
            try:
                candidates = tuple(
                    evidence_matcher(
                        frame,
                        spec,
                        minimum_score=0.25,
                        peak_radius=peak_radius,
                        max_results=12,
                        geometry=geometry,
                        purpose="剧情角标候选",
                    )
                )
            except (AttributeError, TypeError, ValueError):
                candidates = ()
            if candidates:
                return tuple(
                    getattr(candidate, "result", candidate)
                    for candidate in candidates
                )

        matcher = getattr(self.vision, "match_all", None)
        if not callable(matcher):
            return ()
        try:
            return tuple(
                matcher(
                    frame,
                    spec,
                    minimum_score=STORY_BADGE_CANDIDATE_SCORE,
                    peak_radius=peak_radius,
                    max_results=12,
                )
            )
        except (AttributeError, TypeError, ValueError):
            return ()

    def _story_badge_detections(
        self,
        frame: np.ndarray,
    ) -> tuple[StoryBadgeDetection, ...]:
        geometry = self._story_badge_geometry(frame)
        if geometry is False or (geometry is not None and not geometry.accepted):
            return ()
        height, width = frame.shape[:2]
        client_scale = (
            geometry.client_scale
            if geometry is not None
            else min(width / FHD_1080.width, height / FHD_1080.height)
        )
        peak_radius = max(2, round(5 * client_scale))
        cluster_radius = max(4, round(STORY_BADGE_CLUSTER_RADIUS * client_scale))
        candidates: list[StoryBadgeCandidate] = []
        for number, spec in self._badge_specs():
            matches = self._story_badge_template_candidates(
                frame,
                spec,
                peak_radius=peak_radius,
                geometry=geometry,
            )
            candidates.extend(
                StoryBadgeCandidate(number, result)
                for result in matches
                if result.size[0] > 0
                and result.size[1] > 0
                and 0 <= result.center[0] <= width
                and 0 <= result.center[1] <= height
            )

        if candidates:
            median_width = median(
                max(1, candidate.result.size[0]) for candidate in candidates
            )
            cluster_radius = max(
                cluster_radius,
                round(max(4.0, median_width * 0.70)),
            )

        clusters: list[list[StoryBadgeCandidate]] = []
        for candidate in sorted(
            candidates,
            key=lambda value: value.discrimination_score,
            reverse=True,
        ):
            for cluster in clusters:
                anchor = cluster[0].result.center
                center = candidate.result.center
                if (center[0] - anchor[0]) ** 2 + (center[1] - anchor[1]) ** 2 <= cluster_radius**2:
                    cluster.append(candidate)
                    break
            else:
                clusters.append([candidate])

        detections: list[StoryBadgeDetection] = []
        for cluster in clusters:
            best_by_number: dict[int, StoryBadgeCandidate] = {}
            for candidate in cluster:
                current = best_by_number.get(candidate.number)
                if current is None or (
                    candidate.combined_score,
                    candidate.discrimination_score,
                ) > (
                    current.combined_score,
                    current.discrimination_score,
                ):
                    best_by_number[candidate.number] = candidate
            ranked = sorted(
                best_by_number.values(),
                key=lambda value: (
                    value.combined_score,
                    value.discrimination_score,
                ),
                reverse=True,
            )
            if not ranked:
                continue
            detections.append(
                StoryBadgeDetection(
                    best=ranked[0],
                    runner_up=ranked[1] if len(ranked) > 1 else None,
                )
            )
        return tuple(sorted(detections, key=lambda value: value.best.result.center[0]))

    def _story_badge_grid(
        self,
        frame: np.ndarray,
        detections: tuple[StoryBadgeDetection, ...],
    ) -> StoryBadgeGrid | None:
        """Fit the low-resolution quick-bar lattice from independent badge peaks."""

        height, width = frame.shape[:2]
        if len(detections) < STORY_BADGE_GRID_MIN_ANCHORS:
            return None

        badge_width = median(
            max(1, value.best.result.size[0]) for value in detections
        )
        row_tolerance = max(
            3.0,
            min(8.0, badge_width * STORY_BADGE_GRID_ROW_TOLERANCE_RATIO),
        )

        # Matching every number deliberately retains weak peaks for diagnosis,
        # but those peaks often form parallel anti-aliasing rows.  Fit the
        # lattice only from the horizontal band with the strongest structural
        # evidence; a weak row cannot outvote a real row by sheer peak count.
        rows: list[list[StoryBadgeDetection]] = []
        for detection in sorted(
            detections,
            key=lambda value: value.best.result.center[1],
        ):
            center_y = float(detection.best.result.center[1])
            for row in rows:
                row_center = median(
                    float(value.best.result.center[1]) for value in row
                )
                if abs(center_y - row_center) <= row_tolerance:
                    row.append(detection)
                    break
            else:
                rows.append([detection])
        if not rows:
            return None

        def row_rank(row: list[StoryBadgeDetection]) -> tuple[float, ...]:
            strong = [
                value
                for value in row
                if value.best.combined_score >= STORY_BADGE_GRID_STRONG_COMBINED_SCORE
            ]
            quality = sum(max(0.0, value.best.combined_score) for value in row)
            strong_quality = sum(
                max(0.0, value.best.combined_score) for value in strong
            )
            return (
                float(len(strong)),
                strong_quality,
                float(len(row)),
                quality,
            )

        row = max(rows, key=row_rank)
        if len(row) < STORY_BADGE_GRID_MIN_ANCHORS:
            return None
        x_values = sorted(
            float(value.best.result.center[0]) for value in row
        )
        y_values = [float(value.best.result.center[1]) for value in row]
        minimum_spacing = max(
            8.0,
            badge_width * STORY_BADGE_GRID_MIN_SPACING_BADGE_RATIO,
            width * STORY_BADGE_GRID_MIN_SPACING_RATIO,
        )
        maximum_spacing = max(
            minimum_spacing + 1.0,
            width * STORY_BADGE_GRID_MAX_SPACING_RATIO,
        )
        differences = {
            round(x_values[right] - x_values[left], 3)
            for left in range(len(x_values))
            for right in range(left + 1, len(x_values))
            if x_values[right] > x_values[left]
        }
        spacing_candidates: set[float] = set()
        for difference in differences:
            for divisor in range(1, STORY_BADGE_GRID_MAX_PAIR_GAP + 1):
                spacing = difference / divisor
                if minimum_spacing <= spacing <= maximum_spacing:
                    spacing_candidates.add(round(spacing, 3))
        # The historical ratio is only a seed for sparse/noisy differences;
        # acceptance still requires the observed lattice to fit dynamically.
        prior = width * STORY_BADGE_GRID_SPACING_RATIO
        if minimum_spacing <= prior <= maximum_spacing:
            spacing_candidates.add(round(prior, 3))
        if not spacing_candidates:
            return None

        def circular_error(value: float, phase: float, spacing: float) -> float:
            remainder = (value - phase) % spacing
            return min(remainder, spacing - remainder)

        def fit_phase(spacing: float, seed: float):
            tolerance = max(
                2.0,
                min(
                    spacing * max(0.02, STORY_BADGE_GRID_ALIGNMENT_TOLERANCE_RATIO),
                    max(3.0, badge_width * 0.85),
                ),
            )
            phase = seed % spacing
            aligned: dict[int, StoryBadgeDetection] = {}
            for _ in range(3):
                aligned = {}
                for detection in row:
                    center_x = float(detection.best.result.center[0])
                    slot_index = round((center_x - phase) / spacing)
                    if circular_error(center_x, phase, spacing) > tolerance:
                        continue
                    current = aligned.get(slot_index)
                    if current is None or (
                        detection.best.combined_score,
                        detection.best.discrimination_score,
                    ) > (
                        current.best.combined_score,
                        current.best.discrimination_score,
                    ):
                        aligned[slot_index] = detection
                if not aligned:
                    break
                signed_errors = tuple(
                    ((
                        float(value.best.result.center[0])
                        - (phase + slot_index * spacing)
                        + spacing / 2
                    ) % spacing)
                    - spacing / 2
                    for slot_index, value in aligned.items()
                )
                phase = (phase + median(signed_errors)) % spacing
            return phase, aligned, tolerance

        trials = []
        for spacing in spacing_candidates:
            seeds = tuple(value % spacing for value in x_values)
            for seed in seeds:
                phase, aligned, tolerance = fit_phase(spacing, seed)
                if not aligned:
                    continue
                expected_visible_slots = max(1, ceil(width / spacing))
                required_anchors = max(
                    STORY_BADGE_GRID_MIN_ANCHORS,
                    ceil(expected_visible_slots * STORY_BADGE_GRID_MIN_VISIBLE_FRACTION),
                )
                residual = sum(
                    circular_error(
                        float(value.best.result.center[0]),
                        phase,
                        spacing,
                    )
                    for value in aligned.values()
                )
                quality = sum(
                    max(0.0, value.best.combined_score)
                    for value in aligned.values()
                )
                # Live 1080p 2026-10-09 (桌面分身): a weak "4" peak beside
                # every card formed a lattice 76 px left of the badges with one
                # more slot than the real row, won on count alone, and every
                # slot then read as 9/4.  Strong peaks decide the lattice first.
                strong = sum(
                    1
                    for value in aligned.values()
                    if value.best.combined_score >= STORY_BADGE_GRID_STRONG_COMBINED_SCORE
                )
                trials.append(
                    (
                        strong,
                        len(aligned),
                        len(aligned) / expected_visible_slots,
                        quality,
                        -residual,
                        -abs(spacing - prior),
                        spacing,
                        phase,
                        aligned,
                        tolerance,
                        required_anchors,
                    )
                )
        if not trials:
            return None
        (
            _strong,
            _count,
            _fraction,
            _quality,
            _residual,
            _prior_distance,
            spacing,
            phase,
            aligned,
            _tolerance,
            required,
        ) = max(
            trials,
            key=lambda value: value[:6],
        )
        if len(aligned) < required:
            return None

        center_y = float(median(y_values))
        vertical_tolerance = max(
            3.0,
            height * STORY_BADGE_GRID_VERTICAL_TOLERANCE_RATIO,
            badge_width * 0.85,
        )
        aligned = {
            slot_index: value
            for slot_index, value in aligned.items()
            if abs(value.best.result.center[1] - center_y) <= vertical_tolerance
        }
        if len(aligned) < required:
            return None
        center_y = float(median(value.best.result.center[1] for value in aligned.values()))
        return StoryBadgeGrid(
            spacing=float(spacing),
            phase=float(phase),
            center_y=center_y,
            anchors=len(aligned),
        )

    def _story_badge_grid_detections(
        self,
        frame: np.ndarray,
        anchor_detections: tuple[StoryBadgeDetection, ...],
        target_numbers: Iterable[int],
    ) -> tuple[StoryBadgeDetection, ...]:
        """Compare every number template only inside fitted visible slots."""

        grid = self._story_badge_grid(frame, anchor_detections)
        if grid is None:
            return ()

        height, width = frame.shape[:2]
        geometry = getattr(self, "_last_story_badge_geometry", None)
        client_scale = (
            geometry.client_scale
            if geometry is not None
            else min(width / FHD_1080.width, height / FHD_1080.height)
        )
        peak_radius = max(2, round(5 * client_scale))
        local_tolerance = max(
            4.0,
            grid.spacing * STORY_BADGE_GRID_LOCAL_TOLERANCE_RATIO,
        )
        vertical_tolerance = max(
            3.0,
            height * STORY_BADGE_GRID_VERTICAL_TOLERANCE_RATIO,
        )

        def aligned_slot(result: MatchResult) -> int | None:
            center_x, center_y = result.center
            slot_index = round((center_x - grid.phase) / grid.spacing)
            predicted_x = grid.phase + slot_index * grid.spacing
            if abs(center_x - predicted_x) > local_tolerance:
                return None
            if abs(center_y - grid.center_y) > vertical_tolerance:
                return None
            return slot_index

        anchor_slots = {
            slot_index
            for detection in anchor_detections
            if (slot_index := aligned_slot(detection.best.result)) is not None
        }
        if not anchor_slots:
            return ()

        specs_by_number = dict(self._badge_specs())
        radius_x = max(8, round(min(grid.spacing * 0.38, width * 0.08)))
        radius_y = max(
            8,
            round(
                min(
                    max(grid.spacing * 0.30, height * 0.025),
                    height * 0.08,
                )
            ),
        )

        def local_candidates(
            number: int,
            slot_index: int,
        ) -> tuple[MatchResult, ...]:
            spec = specs_by_number[number]
            grid_spec = replace(
                spec,
                reference_scale=STORY_BADGE_GRID_REFERENCE_SCALE,
                candidate_center_roi=None,
            )
            center = (
                round(grid.phase + slot_index * grid.spacing),
                round(grid.center_y),
            )
            slot_matcher = getattr(self.vision, "match_slot_evidence", None)
            if callable(slot_matcher):
                try:
                    candidates = tuple(
                        slot_matcher(
                            frame,
                            grid_spec,
                            center,
                            radius=(radius_x, radius_y),
                            geometry=geometry,
                            minimum_score=0.20,
                            max_results=4,
                            purpose="剧情角标槽位编号",
                        )
                    )
                except (AttributeError, TypeError, ValueError):
                    candidates = ()
                if candidates:
                    return tuple(
                        getattr(candidate, "result", candidate)
                        for candidate in candidates
                    )

            matcher = getattr(self.vision, "match_all", None)
            if not callable(matcher):
                return ()
            try:
                candidates = tuple(
                    matcher(
                        frame,
                        grid_spec,
                        minimum_score=0.20,
                        peak_radius=peak_radius,
                        max_results=4,
                        search_roi=(
                            center[0] - radius_x,
                            center[1] - radius_y,
                            radius_x * 2 + 1,
                            radius_y * 2 + 1,
                        ),
                    )
                )
            except (AttributeError, TypeError, ValueError):
                return ()
            return tuple(
                result
                for result in candidates
                if abs(result.center[0] - center[0]) <= local_tolerance
                and abs(result.center[1] - center[1]) <= vertical_tolerance
            )

        candidates_by_slot: dict[int, list[StoryBadgeCandidate]] = {}
        requested_numbers = tuple(
            dict.fromkeys(int(value) for value in target_numbers if int(value) in specs_by_number)
        )
        # The target number is always included, while all numbers are examined
        # for the runner-up margin at that same physical slot.
        numbers_to_compare = tuple(specs_by_number)
        for slot_index in sorted(anchor_slots):
            for number in numbers_to_compare:
                for result in local_candidates(number, slot_index):
                    if aligned_slot(result) != slot_index:
                        continue
                    candidates_by_slot.setdefault(slot_index, []).append(
                        StoryBadgeCandidate(number, result)
                    )

        detections: list[tuple[float, StoryBadgeDetection]] = []
        for slot_index, candidates in candidates_by_slot.items():
            best_by_number: dict[int, StoryBadgeCandidate] = {}
            for candidate in candidates:
                current = best_by_number.get(candidate.number)
                if current is None or (
                    candidate.combined_score,
                    candidate.discrimination_score,
                ) > (
                    current.combined_score,
                    current.discrimination_score,
                ):
                    best_by_number[candidate.number] = candidate
            ranked = sorted(
                best_by_number.values(),
                key=lambda value: (
                    value.combined_score,
                    value.discrimination_score,
                ),
                reverse=True,
            )
            if not ranked:
                continue
            detections.append(
                (
                    grid.phase + slot_index * grid.spacing,
                    StoryBadgeDetection(
                        best=ranked[0],
                        runner_up=ranked[1] if len(ranked) > 1 else None,
                        recovery_mode="slot_grid",
                    ),
                )
            )

        self._status(
            "剧情角标栅格",
            (
                f"anchors={grid.anchors}, spacing={grid.spacing:.1f}, "
                f"slots={len(anchor_slots)}, requested={requested_numbers}, "
                f"detections={len(detections)}"
            ),
        )
        return tuple(value for _center, value in sorted(detections))

    @staticmethod
    def _story_badge_ocr_frame(
        frame: np.ndarray,
        result: MatchResult,
        *,
        binary: bool = True,
    ) -> np.ndarray:
        """Prepare one tiny badge as a padded text line for the shared OCR engine."""

        height, width = frame.shape[:2]
        left = max(0, result.position[0])
        top = max(0, result.position[1])
        right = min(width, result.position[0] + result.size[0])
        bottom = min(height, result.position[1] + result.size[1])
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            return np.empty((0, 0, 3), dtype=np.uint8)
        if crop.ndim == 2:
            gray = crop.copy()
        elif crop.shape[2] == 4:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY)
        else:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        crop_height, crop_width = gray.shape[:2]
        # An even-sized crop puts the inner-circle mask on a half-pixel center,
        # which measurably breaks digit readability at tiny badge sizes (the
        # mask then clips asymmetrically before the upscale).  Trim to odd so
        # the mask stays centered on a real pixel; the trimmed edge is ring
        # pixels that the mask would suppress anyway.
        if crop_width > 1 and crop_width % 2 == 0:
            gray = gray[:, : crop_width - 1]
            crop_width -= 1
        if crop_height > 1 and crop_height % 2 == 0:
            gray = gray[: crop_height - 1, :]
            crop_height -= 1
        center_x = (crop_width - 1) / 2
        center_y = (crop_height - 1) / 2
        inner_radius = max(
            2.0,
            min(crop_width, crop_height) * STORY_BADGE_OCR_INNER_RADIUS_RATIO,
        )
        y, x = np.mgrid[:crop_height, :crop_width]
        gray[(x - center_x) ** 2 + (y - center_y) ** 2 > inner_radius**2] = 0
        if binary:
            _threshold, gray = cv2.threshold(
                gray,
                STORY_BADGE_OCR_BINARY_THRESHOLD,
                255,
                cv2.THRESH_BINARY,
            )

        target_height = STORY_BADGE_OCR_INNER_HEIGHT
        target_width = max(
            1,
            round(gray.shape[1] * target_height / max(1, gray.shape[0])),
        )
        enlarged = cv2.resize(
            gray,
            (target_width, target_height),
            interpolation=cv2.INTER_CUBIC,
        )
        enlarged = cv2.cvtColor(enlarged, cv2.COLOR_GRAY2BGR)
        return cv2.copyMakeBorder(
            enlarged,
            STORY_BADGE_OCR_VERTICAL_BORDER,
            STORY_BADGE_OCR_VERTICAL_BORDER,
            STORY_BADGE_OCR_HORIZONTAL_BORDER,
            STORY_BADGE_OCR_HORIZONTAL_BORDER,
            cv2.BORDER_CONSTANT,
            value=(20, 20, 20),
        )

    def _story_badge_ocr_number(
        self,
        frame: np.ndarray,
        result: MatchResult,
    ) -> tuple[int | None, str]:
        prepared = self._story_badge_ocr_frame(frame, result)
        text = ""
        if prepared.size:
            text = self.vision.ocr_text(
                prepared,
                "剧情角标数字辅助",
                target_height=0,
                minimum_threshold=STORY_BADGE_OCR_MIN_CONFIDENCE,
            )
        number = self._story_badge_ocr_text_number(text)
        if number is None:
            # Hard binarization can disconnect anti-aliased digits on small
            # clients (measured: 1280x720 badge 8).  One raw-grayscale retry
            # keeps the single-digit rec model in its trained contrast range.
            prepared = self._story_badge_ocr_frame(frame, result, binary=False)
            if prepared.size:
                text = self.vision.ocr_text(
                    prepared,
                    "剧情角标数字辅助",
                    target_height=0,
                    minimum_threshold=STORY_BADGE_OCR_MIN_CONFIDENCE,
                )
                number = self._story_badge_ocr_text_number(text)
        self._status(
            "剧情角标 OCR",
            f"number={number if number is not None else '-'}, text={text or '-'}",
        )
        return number, text

    @staticmethod
    def _story_badge_ocr_text_number(text: str) -> int | None:
        numbers = {
            int(value)
            for value in re.findall(r"(?<!\d)\d{1,2}(?!\d)", str(text))
            if 1 <= int(value) <= 20
        }
        return next(iter(numbers)) if len(numbers) == 1 else None

    def _find_character_badge(
        self,
        frame: np.ndarray,
        target_number: int,
    ) -> tuple[StoryBadgeDetection | None, str]:
        """The 角色游戏卡 tab: card n's number circle in its own fixed slot."""

        x = (CHARACTER_BADGE_FIRST_X + CHARACTER_BADGE_SPACING * (target_number - 1)) / FHD_1080.width
        y = CHARACTER_BADGE_Y / FHD_1080.height
        half_x = CHARACTER_BADGE_WINDOW / FHD_1080.width
        half_y = CHARACTER_BADGE_WINDOW / FHD_1080.height
        window = (max(0.0, x - half_x), max(0.0, y - half_y), min(1.0, x + half_x), min(1.0, y + half_y))
        ranked = sorted(
            (
                StoryBadgeCandidate(number, self.vision.match(frame, replace(spec, relative_roi=window)))
                for number, spec in CHARACTER_BADGE_SPECS
            ),
            key=lambda candidate: candidate.result.score,
            reverse=True,
        )
        best, runner_up = ranked[0], ranked[1]
        gap = best.result.score - runner_up.result.score
        self._status(
            "角色角标",
            (
                f"{target_number}: 最像{best.number} m={best.result.score:.3f}, "
                f"p={best.result.pixel_score:.3f}, z={best.result.zncc_score:.3f}; "
                f"次像{runner_up.number} m={runner_up.result.score:.3f}"
            ),
        )
        if best.number != target_number:
            return None, f"角色卡{target_number}位置上最像的是{best.number}"
        if best.result.score < CHARACTER_BADGE_MIN_SCORE or gap < CHARACTER_BADGE_MIN_MARGIN:
            return None, (
                f"角色卡{target_number}角标不够确定：m={best.result.score:.3f}"
                f"（需>={CHARACTER_BADGE_MIN_SCORE:.2f}），领先{gap:.3f}"
                f"（需>={CHARACTER_BADGE_MIN_MARGIN:.2f}）"
            )
        return StoryBadgeDetection(best, runner_up), ""

    def _find_story_card(
        self,
        frame: np.ndarray,
        target_number: int,
    ) -> tuple[StoryBadgeDetection | None, str]:
        """The card by its cover art first, else by its number badge.

        Leo 2026-10-09: look-alike badges (10/19, 15/18, 16/18) kept the bar
        sliding for minutes; the art tells the cards apart by a wide margin.
        A card the art cannot settle (e.g. 游玩中 covers it) goes through the
        badge tiers as before."""

        if getattr(self, "_badge_category", "story") == "event":
            return self._find_event_card_by_art(frame, target_number)
        if getattr(self, "_badge_category", "story") == "story":
            detection, reason = self._find_story_card_by_art(frame, target_number)
            if detection is not None:
                return detection, ""
            self._status("剧情卡带图片", f"{target_number}: {reason}，改用角标")
        return self._find_story_badge(frame, target_number)

    def _find_story_card_by_art(
        self,
        frame: np.ndarray,
        target_number: int,
    ) -> tuple[StoryBadgeDetection | None, str]:
        try:
            check = story_card_art.find_card(frame, target_number)
        except (cv2.error, ValueError) as exc:
            return None, f"图片比对异常：{exc}"
        if not check.ok or check.target is None:
            return None, check.reason
        art = check.target
        factor = frame.shape[0] / 1080.0
        badge_left = (art.left + story_card_art.BADGE_FROM_ART_1080[0]) * factor
        badge_top = (art.top + story_card_art.BADGE_FROM_ART_1080[1]) * factor
        side = max(1, round(story_card_art.BADGE_SIZE_1080 * factor))
        result = MatchResult(
            art.score,
            (round(badge_left), round(badge_top)),
            (side, side),
            scale=factor,
        )
        # Leo: the art and the bar already agree, so the digit only vetoes a
        # clear read of another number; nothing read, or a two-digit badge
        # read without its thin leading 1 (16 as 6, most misreads in his
        # 2026-10-09 log), passes.
        number, text = self._story_badge_ocr_number(frame, result)
        if (
            number is not None
            and number != target_number
            and not (target_number >= 10 and number == target_number - 10)
        ):
            return None, f"图片是卡带{target_number}，但数字读成{number}"
        other = check.other
        self._status(
            "剧情卡带图片",
            (
                f"{target_number}: 图片{art.score:.3f}"
                + (f"，次高卡带{other.number} {other.score:.3f}" if other else "")
                + f"，数字={number if number is not None else '-'}"
            ),
        )
        return (
            StoryBadgeDetection(
                best=StoryBadgeCandidate(target_number, result),
                runner_up=None,
                ocr_text=text,
                ocr_number=number,
                recovery_mode="card_art",
            ),
            "",
        )

    def _find_event_card_by_art(
        self,
        frame: np.ndarray,
        target_number: int,
    ) -> tuple[StoryBadgeDetection | None, str]:
        """An event card by its cover art alone: the tab numbers its slots by
        position, so a number never names a card (event_card_art)."""

        try:
            check = event_card_art.find_card(frame, target_number)
        except (cv2.error, ValueError) as exc:
            return None, f"图片比对异常：{exc}"
        if not check.ok or check.target is None:
            return None, check.reason
        art = check.target
        factor = frame.shape[0] / 1080.0
        center_x, center_y = art.badge_center
        side = max(1, round(event_card_art.BADGE_SIZE_1080 * factor))
        half = side / 2
        result = MatchResult(
            art.score,
            (round(center_x * factor - half), round(center_y * factor - half)),
            (side, side),
            scale=factor,
        )
        other = check.other
        self._status(
            "活动卡带图片",
            (
                f"{target_number}: 图片{art.score:.3f}"
                + (f"，次高卡带{other.number} {other.score:.3f}" if other else "")
            ),
        )
        return (
            StoryBadgeDetection(
                best=StoryBadgeCandidate(target_number, result),
                runner_up=None,
                recovery_mode="card_art",
            ),
            "",
        )

    def _find_story_badge(
        self,
        frame: np.ndarray,
        target_number: int,
    ) -> tuple[StoryBadgeDetection | None, str]:
        if getattr(self, "_badge_category", "story") == "character":
            return self._find_character_badge(frame, target_number)
        detections = self._story_badge_detections(frame)
        detection, reason = self._find_story_badge_from_detections(
            frame,
            target_number,
            detections,
        )
        strict_reason = reason
        if detection is not None:
            return detection, reason
        # Leo's clone 2026-10-09 13:30: badge 16 matched the 18 template a
        # hair better (z=0.878 vs 0.868) on every frame for two minutes.  A
        # close native runner-up gets the same OCR-decided promotion as the
        # slot-grid runner-up, before the slower grid pass.
        native_runners = self._story_badge_grid_runner_detections(
            target_number,
            detections,
            recovery_mode="native_runner",
            max_gap=STORY_BADGE_NATIVE_RUNNER_MAX_GAP,
        )
        if native_runners:
            runner_detection, _runner_reason = self._find_story_badge_from_detections(
                frame,
                target_number,
                native_runners,
            )
            if runner_detection is not None:
                return runner_detection, ""
        grid_detections = self._story_badge_grid_detections(
            frame,
            detections,
            (target_number,),
        )
        if grid_detections:
            grid_detection, grid_reason = self._find_story_badge_from_detections(
                frame,
                target_number,
                grid_detections,
            )
            if grid_detection is not None:
                return grid_detection, grid_reason
            if self._story_badge_reason_is_ambiguous(grid_reason):
                return None, grid_reason
            if any(
                value.best.number == target_number for value in grid_detections
            ):
                return None, grid_reason
            reason = strict_reason
            runner_detections = self._story_badge_grid_runner_detections(
                target_number,
                grid_detections,
            )
            if runner_detections:
                runner_detection, runner_reason = (
                    self._find_story_badge_from_detections(
                        frame,
                        target_number,
                        runner_detections,
                    )
                )
                if runner_detection is not None:
                    return runner_detection, runner_reason
                return None, runner_reason
        if not grid_detections and getattr(
            self,
            "_last_story_badge_geometry_reason",
            "",
        ):
            return None, self._last_story_badge_geometry_reason
        if grid_detections and not any(
            value.best.number == target_number for value in grid_detections
        ):
            # A fitted row is useful evidence that the selector is present, but
            # it does not prove that the requested number is visible.
            return None, strict_reason
        if self._story_badge_reason_is_ambiguous(reason):
            return None, reason
        return None, reason

    @staticmethod
    def _story_badge_grid_runner_detections(
        target_number: int,
        grid_detections: tuple[StoryBadgeDetection, ...],
        recovery_mode: str = "slot_grid_runner",
        max_gap: float | None = None,
    ) -> tuple[StoryBadgeDetection, ...]:
        """Promote grid runner-up slots whose full structural evidence holds.

        On heavily degraded small clients the target's template can lose its
        own slot by a hair to a visually adjacent digit.  The slot evidence of
        that runner-up is still complete; the digit OCR becomes the deciding
        independent vote inside the regular selector.
        """

        promoted: list[StoryBadgeDetection] = []
        for value in grid_detections:
            runner = value.runner_up
            if runner is None or runner.number != target_number:
                continue
            result = runner.result
            if (
                result.score < STORY_BADGE_GRID_TEMPLATE_SCORE
                or result.pixel_score < STORY_BADGE_GRID_PIXEL_SCORE
                or result.zncc_score < STORY_BADGE_GRID_ZNCC_SCORE
            ):
                continue
            if max_gap is not None and value.margin > max_gap:
                continue
            promoted.append(
                StoryBadgeDetection(
                    best=StoryBadgeCandidate(number=target_number, result=result),
                    runner_up=value.best,
                    recovery_mode=recovery_mode,
                )
            )
        return tuple(promoted)

    def inspect_story_badges(
        self,
        frame: np.ndarray,
        target_numbers: Iterable[int],
    ) -> dict[int, tuple[StoryBadgeDetection | None, str]]:
        """Strictly inspect several badge numbers with one shared template scan."""

        detections = self._story_badge_detections(frame)
        inspected = {
            int(number): self._find_story_badge_from_detections(
                frame,
                int(number),
                detections,
            )
            for number in dict.fromkeys(target_numbers)
        }
        recoverable = {
            number
            for number, (detection, reason) in inspected.items()
            if detection is None
            and not reason.startswith(("同一编号出现", "角标OCR数字冲突"))
        }
        if not recoverable:
            return inspected
        grid_detections = self._story_badge_grid_detections(
            frame,
            detections,
            recoverable,
        )
        if not grid_detections:
            return inspected
        for number in recoverable:
            inspected[number] = self._find_story_badge_from_detections(
                frame,
                number,
                grid_detections,
            )
        return inspected

    def _find_story_badge_from_detections(
        self,
        frame: np.ndarray,
        target_number: int,
        detections: tuple[StoryBadgeDetection, ...],
    ) -> tuple[StoryBadgeDetection | None, str]:
        def strict_identity(value: StoryBadgeDetection) -> bool:
            return (
                not value.recovery_mode
                and value.best.result.score >= STORY_BADGE_TEMPLATE_SCORE
                and value.best.result.pixel_score >= STORY_BADGE_PIXEL_SCORE
            )

        def encoded_identity(value: StoryBadgeDetection) -> bool:
            return (
                not value.recovery_mode
                and value.best.result.score >= STORY_BADGE_ENCODED_TEMPLATE_SCORE
                and value.best.result.pixel_score >= STORY_BADGE_ENCODED_PIXEL_SCORE
                and value.best.result.zncc_score >= STORY_BADGE_ENCODED_ZNCC_SCORE
            )

        def grid_identity(value: StoryBadgeDetection) -> bool:
            return (
                value.recovery_mode == "slot_grid"
                and value.best.result.score >= STORY_BADGE_GRID_TEMPLATE_SCORE
                and value.best.result.pixel_score >= STORY_BADGE_GRID_PIXEL_SCORE
                and value.best.result.zncc_score >= STORY_BADGE_GRID_ZNCC_SCORE
            )

        def runner_identity(value: StoryBadgeDetection) -> bool:
            # Structural floors were already enforced when the runner-up was
            # promoted; the digit OCR is the deciding vote for this tier.
            return value.recovery_mode in ("slot_grid_runner", "native_runner")

        def ocr_identity(value: StoryBadgeDetection) -> bool:
            # A native-scale badge that clears the slot-grid structural floors
            # but not the strict/encoded ones (Leo's 1920x1080 frame
            # 2026-10-09: badge 14 at m=0.979/p=0.933/z=0.882, 0.204 ahead of
            # 16).  It needs the grid's lead, and the digit OCR must read the
            # target number back.
            return (
                not value.recovery_mode
                and not strict_identity(value)
                and not encoded_identity(value)
                and value.best.result.score >= STORY_BADGE_GRID_TEMPLATE_SCORE
                and value.best.result.pixel_score >= STORY_BADGE_GRID_PIXEL_SCORE
                and value.best.result.zncc_score >= STORY_BADGE_GRID_ZNCC_SCORE
            )

        target_detections = [
            value
            for value in detections
            if value.best.number == target_number
            and (
                strict_identity(value)
                or encoded_identity(value)
                or grid_identity(value)
                or runner_identity(value)
                or ocr_identity(value)
            )
        ]
        if not target_detections:
            if any(value.recovery_mode == "slot_grid" for value in detections):
                return (
                    None,
                    (
                        "未达到角标栅格恢复门槛："
                        f"match>={STORY_BADGE_GRID_TEMPLATE_SCORE:.3f}, "
                        f"pixel>={STORY_BADGE_GRID_PIXEL_SCORE:.3f}, "
                        f"zncc>={STORY_BADGE_GRID_ZNCC_SCORE:.3f}, "
                        f"margin>={STORY_BADGE_GRID_MIN_MARGIN:.3f}, "
                        f"检测目标数={len(detections)}"
                    ),
                )
            return (
                None,
                (
                    "未达到角标严格或编码恢复门槛："
                    f"match>={STORY_BADGE_TEMPLATE_SCORE:.3f}, "
                    f"pixel>={STORY_BADGE_PIXEL_SCORE:.3f}, "
                    "或 "
                    f"match>={STORY_BADGE_ENCODED_TEMPLATE_SCORE:.3f}, "
                    f"pixel>={STORY_BADGE_ENCODED_PIXEL_SCORE:.3f}, "
                    f"zncc>={STORY_BADGE_ENCODED_ZNCC_SCORE:.3f}, "
                    f"margin>={STORY_BADGE_ENCODED_MIN_MARGIN:.3f}, "
                    f"检测目标数={len(detections)}"
                ),
            )
        if len(target_detections) > 1:
            # Several positions claim the target number (small clients can let
            # one number's template win on a neighbour's slot).  The digit OCR
            # is the independent discriminator: keep the selection only when
            # exactly one position reads back the target number.
            confirmed: list[StoryBadgeDetection] = []
            for value in target_detections:
                ocr_number, ocr_text = self._story_badge_ocr_number(
                    frame,
                    value.best.result,
                )
                if ocr_number == target_number:
                    confirmed.append(
                        replace(value, ocr_number=ocr_number, ocr_text=ocr_text)
                    )
            if len(confirmed) != 1:
                return None, f"同一编号出现{len(target_detections)}个有效位置"
            detection = confirmed[0]
        else:
            detection = target_detections[0]
        if detection.runner_up is None:
            return None, "缺少同位置次优编号，无法检查歧义"
        if runner_identity(detection):
            # The promoted runner-up lost its slot's template vote, so the
            # digit OCR is the deciding independent vote and is mandatory
            # regardless of how the symmetric ZNCC difference came out.
            if detection.ocr_number is not None:
                # Already digit-confirmed while resolving duplicate positions.
                ocr_number, ocr_text = detection.ocr_number, detection.ocr_text
            else:
                ocr_number, ocr_text = self._story_badge_ocr_number(
                    frame,
                    detection.best.result,
                )
                detection = replace(
                    detection,
                    ocr_text=ocr_text,
                    ocr_number=ocr_number,
                )
            if ocr_number == target_number:
                self._status(
                    "剧情角标",
                    (
                        f"栅格次优候选由OCR辅助确认：zncc={detection.margin:.3f}, "
                        f"number={ocr_number}"
                    ),
                )
                return detection, ""
            return (
                None,
                (
                    "角标次优候选OCR未确认："
                    f"模板={target_number}, OCR="
                    f"{ocr_number if ocr_number is not None else '-'}, "
                    f"text={ocr_text or '-'}"
                ),
            )
        if ocr_identity(detection):
            if detection.margin < STORY_BADGE_GRID_MIN_MARGIN:
                return (
                    None,
                    (
                        f"候选分差不足（ZNCC）：{detection.margin:.3f}"
                        f"<{STORY_BADGE_GRID_MIN_MARGIN:.3f}；"
                        f"combined={detection.combined_margin:.3f}"
                    ),
                )
            if detection.ocr_number is not None:
                ocr_number, ocr_text = detection.ocr_number, detection.ocr_text
            else:
                ocr_number, ocr_text = self._story_badge_ocr_number(
                    frame,
                    detection.best.result,
                )
                detection = replace(
                    detection,
                    ocr_text=ocr_text,
                    ocr_number=ocr_number,
                )
            if ocr_number == target_number:
                self._status(
                    "剧情角标",
                    (
                        f"原尺寸候选由OCR辅助确认：zncc={detection.margin:.3f}, "
                        f"number={ocr_number}"
                    ),
                )
                return detection, ""
            return (
                None,
                (
                    "角标原尺寸候选OCR未确认："
                    f"模板={target_number}, OCR="
                    f"{ocr_number if ocr_number is not None else '-'}, "
                    f"text={ocr_text or '-'}"
                ),
            )
        required_margin = min(
            threshold
            for passed, threshold in (
                (strict_identity(detection), STORY_BADGE_MIN_MARGIN),
                (encoded_identity(detection), STORY_BADGE_ENCODED_MIN_MARGIN),
                (grid_identity(detection), STORY_BADGE_GRID_MIN_MARGIN),
            )
            if passed
        )
        if detection.margin < required_margin:
            # OCR is an auxiliary discriminator only after a tier's structural
            # gates and a non-trivial score margin pass.
            ocr_tiebreak = (
                grid_identity(detection)
                and detection.margin >= STORY_BADGE_GRID_OCR_MARGIN
                and detection.combined_margin >= STORY_BADGE_GRID_MIN_COMBINED_MARGIN
            ) or (
                encoded_identity(detection)
                and detection.margin >= STORY_BADGE_ENCODED_OCR_MARGIN
                and detection.combined_margin > 0.0
            )
            if ocr_tiebreak:
                if detection.ocr_number is not None:
                    # Already digit-confirmed during duplicate selection.
                    ocr_number, ocr_text = (
                        detection.ocr_number,
                        detection.ocr_text,
                    )
                else:
                    ocr_number, ocr_text = self._story_badge_ocr_number(
                        frame,
                        detection.best.result,
                    )
                    detection = replace(
                        detection,
                        ocr_text=ocr_text,
                        ocr_number=ocr_number,
                    )
                if ocr_number == target_number:
                    self._status(
                        "剧情角标",
                        (
                            f"{'栅格' if detection.recovery_mode else '编码'}候选分差由OCR辅助确认："
                            f"zncc={detection.margin:.3f}, "
                            f"combined={detection.combined_margin:.3f}, number={ocr_number}"
                        ),
                    )
                    return detection, ""
                if ocr_number is not None:
                    return (
                        None,
                        (
                            "角标OCR数字冲突："
                            f"模板={target_number}, OCR={ocr_number}, "
                            f"text={ocr_text or '-'}"
                        ),
                    )
            return (
                None,
                (
                    f"候选分差不足（ZNCC）：{detection.margin:.3f}"
                    f"<{required_margin:.3f}；"
                    f"combined={detection.combined_margin:.3f}"
                ),
            )
        if detection.ocr_number is not None:
            # Digit already confirmed while resolving duplicate positions.
            ocr_number, ocr_text = detection.ocr_number, detection.ocr_text
        else:
            ocr_number, ocr_text = self._story_badge_ocr_number(
                frame,
                detection.best.result,
            )
            detection = replace(
                detection,
                ocr_text=ocr_text,
                ocr_number=ocr_number,
            )
        if ocr_number is not None and ocr_number != target_number:
            return (
                None,
                (
                    "角标OCR数字冲突："
                    f"模板={target_number}, OCR={ocr_number}, text={ocr_text or '-'}"
                ),
            )
        return detection, ""

    @staticmethod
    def _story_badge_reason_is_ambiguous(reason: str) -> bool:
        return reason.startswith(
            (
                "同一编号出现",
                "缺少同位置次优编号",
                "候选分差不足",
                "角标OCR数字冲突",
            )
        )

    @staticmethod
    def _story_bar_band(frame) -> np.ndarray | None:
        if frame is None:
            return None
        height = frame.shape[0]
        return frame[round(height * 0.80) :, :, :3].astype(np.int16)

    def _wait_story_bar_still(self) -> np.ndarray | None:
        """A slid bar glides on for a moment (live 2K 2026-09-29: the badge
        moved 1845 -> 1636 between two reads and the click was refused);
        wait until two frames of the bar agree.  Returns the bar as last
        seen."""
        end_at = monotonic() + STORY_BAR_STILL_TIMEOUT
        self.task.sleep(0.25)
        previous = None
        while monotonic() < end_at:
            band = self._story_bar_band(self.vision.capture())
            if band is not None and previous is not None and previous.shape == band.shape:
                if float(np.mean(np.abs(band - previous))) < STORY_BAR_STILL_DIFF:
                    return band
            previous = band
            self.task.sleep(0.15)
        return previous

    @staticmethod
    def _story_bar_moved(before: np.ndarray | None, after: np.ndarray | None) -> bool:
        """False only when the bar clearly stayed put (that end is reached)."""
        if before is None or after is None or before.shape != after.shape:
            return True
        return float(np.mean(np.abs(after - before))) >= STORY_BAR_STILL_DIFF

    def _wheel_story_bar(self, toward_larger: bool, notches: int) -> bool:
        """Wheel the bar; False when it did not move (that end is reached)."""
        before = self._story_bar_band(self.vision.capture())
        # No focus click: once the bar has moved, the old focus point (43,974)
        # sits on a card and the click entered it (live 2K 2026-09-29).
        self.task.scroll_client(
            QUICK_SWITCH_SCROLL_POINT,
            STORY_BAR_WHEEL_TOWARD_LARGER if toward_larger else -STORY_BAR_WHEEL_TOWARD_LARGER,
            count=notches,
            interval=QUICK_SWITCH_SCROLL_INTERVAL,
            after_sleep=0.0,
        )
        return self._story_bar_moved(before, self._wait_story_bar_still())

    def _visible_story_reads(self, frame) -> list[tuple[int, float]]:
        """(number, badge x in 1080p px) read off the badge row (one strip OCR).

        The full badge recognition matches twenty digit templates over the
        bar (1.5-9 s a look at 2K); reading the badge row first tells which
        way and how far to wheel, and skips the full look while the card is
        off screen.  The cassette icon beside each badge reads as 四/Ⅲ and is
        dropped with every other non-digit.
        """
        height = frame.shape[0]
        top = round(STORY_BAR_NUMBER_TOP * height / 1080)
        bottom = round(STORY_BAR_NUMBER_BOTTOM * height / 1080)
        strip = frame[top:bottom, :, :3]
        if strip.size == 0:
            return []
        strip = cv2.resize(
            strip,
            (
                round(1920 * STORY_BAR_NUMBER_OCR_SCALE),
                round((STORY_BAR_NUMBER_BOTTOM - STORY_BAR_NUMBER_TOP) * STORY_BAR_NUMBER_OCR_SCALE),
            ),
            interpolation=cv2.INTER_CUBIC,
        )
        pad = STORY_BAR_NUMBER_PAD
        strip = cv2.copyMakeBorder(strip, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
        try:
            boxes = self.vision.ocr_boxes(strip, "快速栏角标数字", target_height=0)
        except AttributeError:  # vision without OCR (tests)
            return []
        reads = []
        for box in boxes:
            text = re.sub(r"\D", "", str(getattr(box, "name", "")))
            if not (text and len(text) <= 2 and 1 <= int(text) <= STORY_CARD_COUNT):
                continue
            # A box often runs on over the cassette icon (widths 12-150 px
            # live), so the badge is placed from its left edge: live 2K, the
            # offsets agreed within 0.1 card this way, not 0.3 from centres.
            left = (float(getattr(box, "x", 0)) - pad) / STORY_BAR_NUMBER_OCR_SCALE
            reads.append((int(text), left + STORY_BAR_DIGIT_HALF_WIDTH * len(text)))
        self._status(
            "快速栏可见编号",
            ",".join(f"{number}@{x:.0f}" for number, x in sorted(reads, key=lambda r: r[1])) or "-",
        )
        return reads

    def _story_bar_offset(self, frame) -> float | None:
        """Where the bar stands: card number = offset + badge x / 180 (1080p),
        or None when the badge row cannot be read.

        Badges sit 180 px apart, so every read votes for one offset; the
        largest agreeing group wins and stray reads drop out (live: "1"
        among 8-17).  A lone digit may be a two-digit badge whose thin
        leading 1 was lost (live 2K: 13, 16, 19 read as 3, 6, 9), so it
        votes for both."""
        votes = []
        for index, (number, x) in enumerate(self._visible_story_reads(frame)):
            for candidate in (number, number + 10) if number < 10 else (number,):
                if candidate <= STORY_CARD_COUNT:
                    votes.append((candidate - x / STORY_BAR_CARD_SPACING, index))
        best: list[float] = []
        for offset, _index in votes:
            group = {index: other for other, index in votes if abs(other - offset) <= STORY_BAR_OFFSET_TOLERANCE}
            if len(group) > len(best):
                best = list(group.values())
        if len(best) < STORY_BAR_VISIBLE_MIN_READ:
            return None
        return float(np.median(best))

    def _story_card_x(self, offset: float, target_number: int) -> float:
        return (target_number - offset) * STORY_BAR_CARD_SPACING

    def _scan_story_bar_guided(self, target_number: int, scan_current_page, *, looked: bool = False):
        """Wheel straight to the card by the badge numbers on screen; the full
        badge recognition only runs once the card is in view, and a failed
        look nudges the bar a little and looks again (the playing card's
        badge scored too low at some positions, live 2K 2026-09-30).
        ``looked``: the caller's look at the current view already failed.
        None when the row cannot be read, the bar stops moving or the looks
        fail; the blind wheel scan then runs as before."""
        previous = None
        toward_larger = True
        nudges = 0
        for _step in range(STORY_BAR_GUIDED_STEPS):
            offset = self._story_bar_offset(self.vision.capture())
            if offset is None:
                return None
            moved = previous is None or abs(offset - previous) >= STORY_BAR_OFFSET_TOLERANCE
            x = self._story_card_x(offset, target_number)
            if STORY_BAR_VIEW_LEFT <= x <= STORY_BAR_VIEW_RIGHT:
                if moved and not looked:
                    found = scan_current_page()
                    if found is not None:
                        return found
                looked = False
                if nudges >= STORY_BAR_GUIDED_NUDGES:
                    # The numbers put it here and it is not: pinned (置顶)
                    # cards sit at the front out of number order (YES-BD2 #6).
                    self._story_bar_out_of_order = True
                    return None
                nudges += 1
                # Toward the middle; at an end the bar cannot move that way,
                # so the next nudge goes back the other way.
                toward_larger = x > STORY_BAR_VIEW_CENTER if moved else not toward_larger
                notches = STORY_BAR_NUDGE_NOTCHES
            else:
                if not moved:
                    return None
                cards = (x - STORY_BAR_VIEW_CENTER) / STORY_BAR_CARD_SPACING
                toward_larger = cards > 0
                notches = max(
                    STORY_BAR_NUDGE_NOTCHES,
                    min(STORY_BAR_GUIDED_MAX_NOTCHES, round(abs(cards) * STORY_BAR_NOTCHES_PER_CARD)),
                )
            self._status(
                "卡带滚轮",
                f"卡带{target_number}在 x={x:.0f}，往{'大' if toward_larger else '小'}编号滚 {notches} 格",
            )
            self._wheel_story_bar(toward_larger, notches)
            previous = offset
        return None

    def _story_bar_sweep_order(self, target_number: int) -> tuple[bool, bool]:
        """Which way to sweep first (True: toward larger numbers).  Cards run
        1..20 left to right, so by the number; but once the numbers on screen
        missed the card it is likely pinned (置顶), and pinned cards come
        first (YES-BD2 #6, fixture native_720_q6_visible: 6, 18, 20, 1, 2...)."""
        if getattr(self, "_story_bar_out_of_order", False):
            return (False, True)
        return (True, False) if target_number >= 10 else (False, True)

    def _scan_story_bar_by_wheel(
        self,
        target_number: int,
        scan_current_page,
        *,
        looked: bool = False,
        sweep_look=None,
    ):
        """Wheel straight toward the card (Leo 2026-09-29 prefers the wheel,
        in the right direction: the old reset wheeled to the front instead
        of the far end and every scan started over from card 1).
        ``sweep_look``: the look while sweeping blind (default the full one)."""
        self._story_bar_out_of_order = False
        found = self._scan_story_bar_guided(target_number, scan_current_page, looked=looked)
        if found is not None:
            return found
        look = sweep_look or scan_current_page
        for toward_larger in self._story_bar_sweep_order(target_number):
            still = 0
            looked_here = False
            for step in range(STORY_BAR_WHEEL_STEPS):
                self._status(
                    "卡带滚轮",
                    f"往{'大' if toward_larger else '小'}编号滚 {step + 1}/{STORY_BAR_WHEEL_STEPS}",
                )
                if self._wheel_story_bar(toward_larger, STORY_BAR_WHEEL_NOTCHES):
                    still = 0
                    looked_here = False
                else:
                    # That end of the bar: the same view was looked at up to
                    # eight more times (about a minute at 2K).
                    still += 1
                    if still >= STORY_BAR_END_STILL_MOVES:
                        break
                    if looked_here:
                        continue
                found = look()
                looked_here = True
                if found is not None:
                    return found
        return None

    def _scan_story_bar_by_swipe(self, target_number: int, scan_current_page):
        """Slide the quick bar like a player: hold its right half, drag left
        (larger numbers) or the reverse (Leo 2026-09-29; the wheel moved it a
        few pixels per notch).  None when the swipe is unavailable or the
        card never showed; the wheel scan then runs as before."""
        swipe = getattr(getattr(getattr(self.task, "executor", None), "interaction", None), "post_swipe", None)
        if swipe is None:
            return None
        frame = self.vision.capture()
        height, width = frame.shape[:2]
        y = round(STORY_BAR_SWIPE_Y * height / 1080)
        right = round(STORY_BAR_SWIPE_RIGHT_X * width / 1920)
        left = round(STORY_BAR_SWIPE_LEFT_X * width / 1920)
        # About ten cards fit on screen.
        for toward_larger in self._story_bar_sweep_order(target_number):
            still = 0
            looked_here = False
            for step in range(STORY_BAR_SWIPE_STEPS):
                self._status("卡带滑动", f"按住往{'左' if toward_larger else '右'}滑 {step + 1}")
                before = self._story_bar_band(self.vision.capture())
                if toward_larger:
                    swipe(right, y, left, y)
                else:
                    swipe(left, y, right, y)
                if self._story_bar_moved(before, self._wait_story_bar_still()):
                    still = 0
                    looked_here = False
                else:
                    still += 1
                    if still >= STORY_BAR_END_STILL_MOVES:
                        break
                    if looked_here:
                        continue
                found = scan_current_page()
                looked_here = True
                if found is not None:
                    return found
        return None

    def _wait_for_story_badge_with_scroll(
        self,
        target_number: int,
        scan_steps: int = QUICK_SWITCH_SCROLL_SCAN_STEPS,
    ) -> tuple[np.ndarray, StoryBadgeDetection] | None:
        """Find one story badge, using the quick bar's mouse-wheel direction."""

        last_reason = "未执行识别"

        def scan_current_page() -> tuple[np.ndarray, StoryBadgeDetection] | None:
            nonlocal last_reason
            frame = self.vision.capture()
            detection, last_reason = self._find_story_card(frame, target_number)
            if detection is None:
                self._status("剧情角标", f"{target_number}: {last_reason}")
                return None
            return seen(frame, detection)

        def look_by_art() -> tuple[np.ndarray, StoryBadgeDetection] | None:
            # The cover art alone: quick (0.1-0.4 s) and in any bar order,
            # unlike the badge templates (1.5-9 s a look at 2K).
            frame = self.vision.capture()
            detection, reason = self._find_story_card_by_art(frame, target_number)
            if detection is None:
                self._status("剧情卡带图片", f"{target_number}: {reason}")
                return None
            return seen(frame, detection)

        def seen(frame, detection) -> tuple[np.ndarray, StoryBadgeDetection]:
            self._status(
                "剧情角标",
                (
                    f"{target_number}: match={detection.best.result.score:.3f}, "
                    f"pixel={detection.best.result.pixel_score:.3f}, "
                    f"zncc={detection.best.result.zncc_score:.3f}, "
                    f"margin={detection.margin:.3f}, "
                    f"ocr={detection.ocr_number if detection.ocr_number is not None else '-'}"
                ),
            )
            return frame, detection

        if getattr(self, "_badge_category", "story") == "event":
            # Every owned event card shows at once: look, no scrolling.
            end_at = monotonic() + EVENT_CARD_SCAN_SECONDS
            while True:
                found = scan_current_page()
                if found is not None or monotonic() >= end_at:
                    break
                self.task.sleep(0.5)
            if found is None:
                self.task.log_warning(
                    f"跑图：活动游戏卡页没有认出活动卡带{target_number}：{last_reason}。"
                )
            return found

        by_art = (
            getattr(self, "_badge_category", "story") == "story"
            and story_card_art.has_art(target_number)
        )
        # A card clearly off screen skips the slow full look (1.5-9 s at 2K).
        offset = self._story_bar_offset(self.vision.capture())
        target_x = None if offset is None else self._story_card_x(offset, target_number)
        looked = target_x is None or STORY_BAR_VIEW_LEFT <= target_x <= STORY_BAR_VIEW_RIGHT
        if not looked and by_art:
            # The count from the numbers on screen is wrong for a pinned
            # (置顶) card: it sits at the front, out of number order, and
            # the cards after it leave gaps (Leo 2026-10-10, YES-BD2 #6).
            found = look_by_art()
            if found is not None:
                return found
        if looked:
            found = scan_current_page()
            if found is not None:
                return found
            if self._story_badge_reason_is_ambiguous(last_reason):
                self.task.log_warning(
                    f"跑图跑商：剧情游戏卡{target_number}角标存在歧义：{last_reason}。"
                )
                return None
        else:
            self._status("剧情角标", f"{target_number}: 不在画面内（x={target_x:.0f}），直接滚过去")

        wheeled = self._scan_story_bar_by_wheel(
            target_number,
            scan_current_page,
            looked=looked,
            # The badge templates only where the numbers put the card; the
            # swipe below still looks with them everywhere.
            sweep_look=look_by_art if by_art else None,
        )
        if wheeled is not None:
            return wheeled
        swiped = self._scan_story_bar_by_swipe(target_number, scan_current_page)
        if swiped is not None:
            return swiped
        if getattr(getattr(getattr(self.task, "executor", None), "interaction", None), "post_swipe", None):
            # Leo 2026-09-29: the wheel ran the wrong way and kept hitting the
            # front of the bar; with swiping available it is not used at all.
            self.task.log_warning(
                f"跑图跑商：左右滑动快速选择栏后仍未确认剧情游戏卡{target_number}角标：{last_reason}。"
            )
            return None

        self._focus_quick_switch_for_scroll()
        # The quick selector runs horizontally. A downward wheel moves toward
        # larger card numbers, so first reset to that edge. Scanning then uses
        # the user-calibrated upward wheel: cards move right, large to small.
        self._status("卡带滚轮", "向下复位到大编号端")
        self.task.scroll_client(
            QUICK_SWITCH_SCROLL_POINT,
            QUICK_SWITCH_SCROLL_RESET_AMOUNT,
            count=QUICK_SWITCH_SCROLL_RESET_COUNT,
            interval=QUICK_SWITCH_SCROLL_INTERVAL,
            after_sleep=QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
        )

        steps = max(0, int(scan_steps))
        for step in range(steps + 1):
            found = scan_current_page()
            if found is not None:
                return found
            if self._story_badge_reason_is_ambiguous(last_reason):
                self.task.log_warning(
                    f"跑图跑商：剧情游戏卡{target_number}角标存在歧义：{last_reason}。"
                )
                return None
            if step >= steps:
                break
            self._status("卡带滚轮", f"向上扫描 {step + 1}/{steps}")
            self.task.scroll_client(
                QUICK_SWITCH_SCROLL_POINT,
                QUICK_SWITCH_SCROLL_UP_AMOUNT,
                count=QUICK_SWITCH_SCROLL_UP_COUNT,
                interval=QUICK_SWITCH_SCROLL_INTERVAL,
                after_sleep=QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
            )

        self.task.log_warning(
            f"跑图跑商：滚动快速选择栏后仍未确认剧情游戏卡{target_number}角标：{last_reason}。"
        )
        return None

    def locate_probe_story_card(
        self,
        card_id: str,
        scan_steps: int = QUICK_SWITCH_SCROLL_SCAN_STEPS,
    ) -> ProbedStoryCard | None:
        """Locate and read one card in an already-open story quick selector.

        This probe-only path preserves the current horizontal viewport.  It
        advances toward later cards in short wheel batches, waits for the
        selector to settle, and never uses the formal selector's reset-to-edge
        operation. ``scan_steps`` is the total wheel-event limit, not the
        number of recognition attempts.
        """

        card = CARD_BY_ID.get(card_id)
        if card is None:
            self.task.log_warning(f"剧情卡带合并测试：未知卡带：{card_id}。")
            return None

        scroll_limit = max(0, int(scan_steps))
        scrolled = 0
        last_reason = "未执行识别"
        scroll_focused = False
        while True:
            frame = self.vision.capture()
            badge, last_reason = self._find_story_card(frame, card.number)
            if badge is None:
                self._status("剧情角标", f"{card.number}: {last_reason}")
                if self._story_badge_reason_is_ambiguous(last_reason):
                    self.task.log_warning(
                        f"剧情卡带合并测试：剧情游戏卡{card.number}角标存在歧义：{last_reason}。"
                    )
                    return None
            else:
                try:
                    completion = self.card_status.detect(
                        frame,
                        badge.best.result.center,
                    )
                except (RuntimeError, ValueError, cv2.error) as error:
                    self.task.log_warning(f"剧情卡带合并测试：{card_id}完成度识别异常：{error}。")
                    return None
                if completion.complete_region:
                    self.task.sleep(PROBE_STORY_BADGE_CONFIRM_SECONDS)
                    confirmed_frame = self.vision.capture()
                    confirmed_badge, confirmed_reason = self._find_story_card(
                        confirmed_frame,
                        card.number,
                    )
                    if confirmed_badge is None:
                        last_reason = f"等待0.4秒后角标复核失败：{confirmed_reason}"
                        self._status("剧情角标", f"{card.number}: {last_reason}")
                        self.task.log_warning(
                            f"剧情卡带合并测试：剧情游戏卡{card.number}"
                            f"角标在点击前复核失败：{confirmed_reason}。"
                        )
                        return None
                    else:
                        try:
                            confirmed_completion = self.card_status.detect(
                                confirmed_frame,
                                confirmed_badge.best.result.center,
                            )
                        except (RuntimeError, ValueError, cv2.error) as error:
                            self.task.log_warning(
                                f"剧情卡带合并测试：{card_id}复核帧完成度识别异常：{error}。"
                            )
                            return None
                        if confirmed_completion.complete_region:
                            located = LocatedStoryCard(
                                card,
                                confirmed_frame,
                                confirmed_badge,
                            )
                            self._status(
                                "目标卡带",
                                (
                                    f"{card_id}: center="
                                    f"({confirmed_badge.best.result.center[0]},"
                                    f"{confirmed_badge.best.result.center[1]}), "
                                    f"match={confirmed_badge.best.result.score:.3f}, "
                                    f"pixel={confirmed_badge.best.result.pixel_score:.3f}, "
                                    f"zncc={confirmed_badge.best.result.zncc_score:.3f}, "
                                    f"margin={confirmed_badge.margin:.3f}"
                                ),
                            )
                            return ProbedStoryCard(located, confirmed_completion)
                        last_reason = "角标复核帧的吸取/压制区域被客户区边缘截断"
                        self._status("卡带完成度", last_reason)
                else:
                    last_reason = "角标已命中，但吸取/压制区域被客户区边缘截断"
                    self._status("卡带完成度", last_reason)

            if scrolled >= scroll_limit:
                break
            if not scroll_focused:
                self._focus_quick_switch_for_scroll()
                scroll_focused = True
            batch_count = min(
                PROBE_QUICK_SWITCH_SCROLL_COUNT,
                scroll_limit - scrolled,
            )
            scrolled += batch_count
            self._status(
                "卡带滚轮",
                f"后续卡带滚动 {scrolled}/{scroll_limit}（本批{batch_count}次）",
            )
            self.task.scroll_client(
                PROBE_QUICK_SWITCH_SCROLL_POINT,
                PROBE_QUICK_SWITCH_SCROLL_AMOUNT,
                count=batch_count,
                interval=PROBE_QUICK_SWITCH_SCROLL_INTERVAL_SECONDS,
                after_sleep=PROBE_QUICK_SWITCH_SCROLL_SETTLE_SECONDS,
            )

        self.task.log_warning(
            f"剧情卡带合并测试：分批向上滚动后仍未确认剧情游戏卡{card.number}：{last_reason}。"
        )
        return None

    def enter_probe_story_card(self, probed: ProbedStoryCard) -> NavigationResult:
        """Click the revalidated probe center and confirm a stable sandbox."""

        return self._enter_located_story_card(probed.located)

    def _handle_story_card_intermediate(self, frame: np.ndarray) -> bool | NavigationResult:
        """True when a known prompt was handled; a failed result stops the wait."""

        prompt = normalize_text(
            self.vision.simplify(
                self.vision.ocr_text(
                    frame,
                    "新卡带插入提示",
                    roi=FIRST_CARD_INSERT_REGION,
                )
            )
        )
        if "未插好游戏卡" in prompt:
            clicked = self.vision.click_ocr(
                [r"插入", r"未插好游戏卡"],
                roi=FIRST_CARD_INSERT_REGION,
                after_sleep=0.8,
                name="新卡带插入",
            )
            if clicked:
                self._status("导航状态", "处理未插好游戏卡")
                return True

        skip = self.vision.match(frame, FIRST_CARD_SKIP_TEMPLATE)
        if self.vision.passes(skip, FIRST_CARD_SKIP_TEMPLATE):
            self.vision.click_client(skip.center, frame.shape, after_sleep=0.8)
            self._status("导航状态", "跳过首次卡带对话")
            return True

        boxes = self.vision.ocr_boxes(frame, "首次卡带确认", roi=FIRST_CARD_CONFIRM_REGION)
        texts = [normalize_text(self.vision.simplify(str(getattr(b, "name", "")))) for b in boxes]
        self._status("首次卡带确认 OCR", " ".join(texts) or "-")
        if not any("确认" in text for text in texts):
            return False
        # 确认 alone proves nothing: the same frame must not show a dialog that
        # buys or uses something up (review #11).
        dialog = normalize_text(
            self.vision.simplify(
                self.vision.ocr_text(frame, "首次卡带对话", roi=FIRST_CARD_DIALOG_REGION)
            )
        )
        paid = [
            word
            for word in FIRST_CARD_PAID_WORDS
            if word in dialog or any(word in text for text in texts)
        ]
        if paid:
            return self._refuse_story_card_dialog(frame, paid)
        for box, text in zip(boxes, texts):
            attrs = tuple(getattr(box, key, None) for key in ("x", "y", "width", "height"))
            if text != "确认" or any(value is None for value in attrs):
                continue
            x, y, width, height = (float(value) for value in attrs)
            self.vision.click_client(
                (round(x + width / 2), round(y + height / 2)), frame.shape, after_sleep=0.8
            )
            self._status("导航状态", "确认首次卡带对话")
            return True
        return False

    def _refuse_story_card_dialog(self, frame: np.ndarray, words: list[str]) -> NavigationResult:
        """Leave a dialog that may spend something untouched and stop."""

        evidence = "-"
        try:
            evidence = self.task.save_frame("map_card_paid_dialog_failed", frame).name
        except (OSError, ValueError) as exc:
            self.task.log_warning(f"诊断截图保存失败：{exc}")
        self.task.log_warning(
            f"{FIRST_CARD_PAID_DIALOG_MESSAGE}：确认框里有「{'、'.join(words)}」，"
            f"停止这一步（截图 {evidence}）。"
        )
        self._status("导航状态", "确认框可能花费资源，未按确认")
        return NavigationResult(False, ScreenState.UNKNOWN, FIRST_CARD_PAID_DIALOG_MESSAGE)

    def ensure_card_menu(self) -> NavigationResult:
        state = self.classify()
        if state == ScreenState.CARD_MENU:
            return NavigationResult(True, state)
        returned = self.return_home()
        if not returned.success:
            return returned
        opened = self.task.open_cartridge_quick_switcher(
            ensure_home=self._wait_for_cartridge_home,
            click_quick_switch=lambda: self._click_quick_switch(10.0, 1.0),
            confirm_quick_switch_page=self._wait_for_quick_switch_page,
        )
        if opened:
            return NavigationResult(True, ScreenState.CARD_MENU)
        return NavigationResult(False, self.classify(), "无法从主页打开快速切换卡带页面")

    def _locate_story_card(
        self,
        card_id: str,
    ) -> LocatedStoryCard | NavigationResult:
        card = CARD_BY_ID.get(card_id)
        if card is None:
            return NavigationResult(False, ScreenState.UNKNOWN, f"未知卡带：{card_id}")
        category = card.category
        label = self._card_category(category)[0]
        self._badge_category = category
        if self._menu_still_confirmed(category):
            # Just confirmed (or the last card was only looked at): the page,
            # its OCR and the tab OCR cost ~2.6 s per card (Leo 2026-10-05).
            self._status("导航状态", f"沿用已确认的{label}页")
        elif self.classify() == ScreenState.CARD_MENU:
            if not self._wait_for_quick_switch_page():
                return NavigationResult(
                    False,
                    ScreenState.CARD_MENU,
                    "当前快速切换卡带页面未通过三项 OCR 确认",
                )
            # The page may show another tab (the story tab after a story
            # card): a short look, then switch.
            if not self._wait_for_story_category(
                timeout=1.0 if category != "story" else 3.0,
                category=category,
                warn=category == "story",
            ) and not self._select_story_category(category):
                return NavigationResult(
                    False,
                    ScreenState.CARD_MENU,
                    f"当前快速切换页未确认{label}类别",
                )
        else:
            returned = self.return_home()
            if not returned.success:
                return returned
            menu = self._open_story_quick_switcher(category)
            if not menu.success:
                return menu

        self._status("导航状态", f"识别{label}{card.number}角标")
        badge_match = self._wait_for_story_badge_with_scroll(card.number)
        if badge_match is None:
            return NavigationResult(
                False,
                self.classify(),
                f"未唯一确认剧情游戏卡{card.number}角标",
            )
        badge_frame, badge = badge_match
        self._menu_confirmed = (monotonic(), category)
        self._status(
            "目标卡带",
            (
                f"{card_id}: match={badge.best.result.score:.3f}, "
                f"pixel={badge.best.result.pixel_score:.3f}, "
                f"zncc={badge.best.result.zncc_score:.3f}, "
                f"margin={badge.margin:.3f}, "
                f"ocr={badge.ocr_number if badge.ocr_number is not None else '-'}"
            ),
        )
        return LocatedStoryCard(card, badge_frame, badge)

    def _menu_still_confirmed(self, category: str) -> bool:
        """The quick-switch tab was confirmed moments ago and still shows lit."""

        confirmed = getattr(self, "_menu_confirmed", None)
        self._menu_confirmed = None
        if confirmed is None or confirmed[1] != category:
            return False
        if monotonic() - confirmed[0] > MENU_CONFIRM_REUSE_SECONDS:
            return False
        _label, _point, region = self._card_category(category)
        ratio = self.vision.bright_neutral_ratio(self.vision.capture(), region)
        return ratio >= STORY_CATEGORY_HIGHLIGHT_MIN_RATIO

    def _enter_located_story_card(
        self,
        located: LocatedStoryCard,
    ) -> NavigationResult:
        self._menu_confirmed = None
        card = located.card
        confirmed = self._confirm_story_badge_before_click(
            located.frame,
            located.badge,
        )
        if confirmed is None:
            return NavigationResult(
                False,
                ScreenState.CARD_MENU,
                f"剧情游戏卡{card.number}点击前角标复核失败，已停止点击",
            )
        badge_frame, badge = confirmed
        self._status(
            f"剧情游戏卡{card.number}角标点击中心",
            (
                f"center=({badge.best.result.center[0]},"
                f"{badge.best.result.center[1]}), "
                f"match={badge.best.result.score:.3f}, "
                f"pixel={badge.best.result.pixel_score:.3f}, "
                f"zncc={badge.best.result.zncc_score:.3f}, "
                f"margin={badge.margin:.3f}, "
                f"ocr={badge.ocr_number if badge.ocr_number is not None else '-'}"
            ),
        )
        self.vision.click_client(
            badge.best.result.center,
            badge_frame.shape,
            after_sleep=1.0,
        )
        arrival = self._wait_for_story_sandbox(card.number)
        if arrival.success:
            return NavigationResult(True, arrival.state, card.card_id)
        return arrival

    @staticmethod
    def _story_badge_identity_is_stable(
        previous: StoryBadgeDetection,
        current: StoryBadgeDetection,
    ) -> bool:
        """Require the same numbered slot before a card-selection click."""

        if previous.best.number != current.best.number:
            return False
        first = previous.best.result
        second = current.best.result
        if (
            first.size[0] <= 0
            or first.size[1] <= 0
            or second.size[0] <= 0
            or second.size[1] <= 0
        ):
            return False
        scale = max(0.2, min(float(first.scale), float(second.scale)))
        center_tolerance = max(
            3,
            round(8.0 * scale),
            round(max(first.size[0], second.size[0]) * 0.55),
        )
        size_tolerance = max(2, round(4.0 * scale))
        return (
            abs(first.center[0] - second.center[0]) <= center_tolerance
            and abs(first.center[1] - second.center[1]) <= center_tolerance
            and abs(first.size[0] - second.size[0]) <= size_tolerance
            and abs(first.size[1] - second.size[1]) <= size_tolerance
        )

    def _confirm_story_badge_before_click(
        self,
        frame: np.ndarray,
        detection: StoryBadgeDetection,
    ) -> tuple[np.ndarray, StoryBadgeDetection] | None:
        """Re-read the numbered slot immediately before sending a mouse click."""

        sleeper = getattr(self.task, "sleep", None)
        if callable(sleeper):
            sleeper(PROBE_STORY_BADGE_CONFIRM_SECONDS)
        capture = getattr(self.vision, "capture", None)
        if not callable(capture):
            reason = "视觉适配器不支持点击前复核捕获"
            self._status("剧情角标点击复核", reason)
            return None
        try:
            confirmed_frame = capture()
            if badge_area_unchanged(frame, confirmed_frame, detection.best.result):
                # Nothing moved since the full identification: re-running it
                # cost ~1.8 s per card (Leo 2026-10-05).
                self._status(
                    "剧情角标点击复核",
                    f"画面未变，沿用识别{detection.best.number}",
                )
                return confirmed_frame, detection
            confirmed, reason = self._find_story_card(
                confirmed_frame,
                detection.best.number,
            )
        except (AttributeError, TypeError, ValueError, cv2.error) as exc:
            reason = f"复核异常：{exc}"
            confirmed = None
            confirmed_frame = None
        if confirmed is None:
            self._status("剧情角标点击复核", reason or "未重新确认目标编号")
            warning = getattr(self.task, "log_warning", None)
            if callable(warning):
                warning(
                    f"跑图跑商：剧情游戏卡{detection.best.number}点击前角标复核失败："
                    f"{reason or '未命中'}。"
                )
            return None
        if not self._story_badge_identity_is_stable(detection, confirmed):
            first = detection.best.result
            second = confirmed.best.result
            reason = (
                "复核编号或槽位不稳定："
                f"first={detection.best.number}@{first.center}/{first.size}; "
                f"second={confirmed.best.number}@{second.center}/{second.size}"
            )
            self._status("剧情角标点击复核", reason)
            warning = getattr(self.task, "log_warning", None)
            if callable(warning):
                warning(f"跑图跑商：剧情游戏卡点击前{reason}，已停止点击。")
            return None
        self._status(
            "剧情角标点击复核",
            (
                f"稳定确认{confirmed.best.number}；"
                f"center={confirmed.best.result.center}; "
                f"size={confirmed.best.result.size}; "
                f"m={confirmed.best.result.score:.3f},"
                f"p={confirmed.best.result.pixel_score:.3f},"
                f"z={confirmed.best.result.zncc_score:.3f}"
            ),
        )
        assert confirmed_frame is not None
        return confirmed_frame, confirmed

    def select_card(self, card_id: str) -> NavigationResult:
        located = self._locate_story_card(card_id)
        if isinstance(located, NavigationResult):
            return located
        return self._enter_located_story_card(located)

    def select_collection_card(
        self,
        card_id: str,
        *,
        enter_visually_complete: bool = False,
    ) -> CollectionCardSelectionResult:
        card = CARD_BY_ID.get(card_id)
        if card is None or not card.collectable:
            navigation = NavigationResult(
                False,
                ScreenState.UNKNOWN,
                f"非跑图剧情卡带：{card_id}",
            )
            return CollectionCardSelectionResult(
                CollectionCardSelectionOutcome.FAILED,
                navigation,
            )

        located = self._locate_story_card(card_id)
        if isinstance(located, NavigationResult):
            return CollectionCardSelectionResult(
                CollectionCardSelectionOutcome.FAILED,
                located,
            )

        completion = None
        try:
            completion = self.card_status.detect(
                located.frame,
                located.badge.best.result.center,
            )
        except (RuntimeError, ValueError, cv2.error) as error:
            self.task.log_warning(f"地图采集：{card_id}完成度识别异常，按未知继续进入：{error}。")

        if completion is not None:
            self._status(
                "卡带吸取状态",
                f"{completion.absorb.state.value}: {completion.absorb.reason}",
            )
            self._status(
                "卡带压制状态",
                f"{completion.suppress.state.value}: {completion.suppress.reason}",
            )
            self._status("卡带完成度", completion.state.value)
            if completion.state == CardActionState.COMPLETED and not enter_visually_complete:
                navigation = NavigationResult(
                    True,
                    ScreenState.CARD_MENU,
                    f"{card_id}视觉确认吸取与压制均完成",
                )
                return CollectionCardSelectionResult(
                    CollectionCardSelectionOutcome.VISUALLY_COMPLETE,
                    navigation,
                    completion,
                )

        navigation = self._enter_located_story_card(located)
        outcome = (
            CollectionCardSelectionOutcome.ENTERED
            if navigation.success
            else CollectionCardSelectionOutcome.FAILED
        )
        return CollectionCardSelectionResult(
            outcome,
            navigation,
            completion,
        )

    def inspect_collection_card_completion(
        self,
        card_id: str,
    ) -> CollectionCardSelectionResult:
        """Read one card's absorb/suppress badges without entering the card."""

        card = CARD_BY_ID.get(card_id)
        if card is None or not card.collectable:
            navigation = NavigationResult(
                False,
                ScreenState.UNKNOWN,
                f"非跑图剧情卡带：{card_id}",
            )
            return CollectionCardSelectionResult(
                CollectionCardSelectionOutcome.FAILED,
                navigation,
            )
        try:
            for attempt in range(CARD_EDGE_SCROLL_ATTEMPTS + 1):
                located = self._locate_story_card(card_id)
                if isinstance(located, NavigationResult):
                    return CollectionCardSelectionResult(
                        CollectionCardSelectionOutcome.FAILED,
                        located,
                    )
                completion = self.card_status.detect(
                    located.frame,
                    located.badge.best.result.center,
                )
                if completion.complete_region or attempt >= CARD_EDGE_SCROLL_ATTEMPTS:
                    break
                # The card sits at the bar's edge and its badges are cut off
                # (live 2K 2026-09-29, 第11章 verification failed): wheel it
                # toward the middle and read again.
                at_right = located.badge.best.result.center[0] > located.frame.shape[1] / 2
                self._status("卡带滚轮", "卡带在快速栏边缘，滚到中间再复核")
                # Cards at the right edge move inward toward larger numbers.
                self._wheel_story_bar(at_right, STORY_BAR_WHEEL_NOTCHES)
        except (RuntimeError, ValueError, cv2.error) as error:
            navigation = NavigationResult(
                False,
                ScreenState.CARD_MENU,
                f"{card_id}完成度识别异常：{error}",
            )
            return CollectionCardSelectionResult(
                CollectionCardSelectionOutcome.FAILED,
                navigation,
            )
        self._status(
            "卡带吸取状态",
            f"{completion.absorb.state.value}: {completion.absorb.reason}",
        )
        self._status(
            "卡带压制状态",
            f"{completion.suppress.state.value}: {completion.suppress.reason}",
        )
        self._status("卡带完成度", completion.state.value)
        completed = completion.state == CardActionState.COMPLETED or (
            card_id in SUPPRESS_ONLY_VERIFIED_CARD_IDS
            and completion.suppress.state == CardActionState.COMPLETED
        )
        return CollectionCardSelectionResult(
            (
                CollectionCardSelectionOutcome.VISUALLY_COMPLETE
                if completed
                else CollectionCardSelectionOutcome.FAILED
            ),
            NavigationResult(
                completed,
                ScreenState.CARD_MENU,
                (
                    f"{card_id}视觉确认吸取与压制均完成"
                    if completed
                    else f"{card_id}未同时确认吸取与压制完成"
                ),
            ),
            completion,
        )

    def open_story_quick_switcher_from_sandbox(
        self,
        *,
        sandbox_already_confirmed: bool = False,
        category: str = "story",
    ) -> NavigationResult:
        """Open the story quick-switch page without detouring through the global home."""

        if not sandbox_already_confirmed:
            sandbox = self._wait_for_current_sandbox()
            if not sandbox.success:
                return sandbox

        self._status("导航状态", "从卡带箱庭识别快速切换按钮")
        # The field was just confirmed still, so three agreeing samples do
        # instead of six (~0.7 s per cartridge switch).
        if not self.vision.click_stable_template(
            QUICK_SWITCH_TEMPLATE,
            timeout=QUICK_SWITCH_CLICK_TIMEOUT,
            after_sleep=QUICK_SWITCH_CLICK_AFTER_SLEEP,
            window_samples=3,
        ):
            return NavigationResult(
                False,
                ScreenState.SANDBOX,
                "卡带箱庭内未稳定识别到快速切换按钮",
            )
        if not self._wait_for_quick_switch_page():
            return NavigationResult(
                False,
                self.classify(),
                "点击快速切换按钮后未确认卡带选择页",
            )

        if not self._select_story_category(category):
            label = self._card_category(category)[0]
            return NavigationResult(
                False,
                self.classify(),
                f"点击后未确认{label}类别高亮",
            )
        return NavigationResult(
            True, ScreenState.CARD_MENU, f"{self._card_category(category)[0]}类别已确认"
        )
