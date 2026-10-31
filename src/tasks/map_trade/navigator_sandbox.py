from __future__ import annotations

import difflib
import re
from dataclasses import replace
from time import monotonic

import cv2
import numpy as np
from ok.task.exceptions import FinishedException, TaskDisabledException

from src.tasks.BaseBD2Task import CartridgeSpecialPageResult
from src.tasks.map_trade.action_icons import (
    ACTION_SLOT_CENTERS_REFERENCE,
    ACTION_SLOT_RELATIVE_ROIS,
    ACTION_SLOT_SEARCH_RADII_REFERENCE,
    SKILL_REFERENCE_HEIGHT,
    SKILL_REFERENCE_WIDTH,
    ActionIconDetection,
    ActionIconDetector,
    ActionIconState,
)
from src.tasks.map_trade.collector_constants import SEARCH_COUNTDOWN_RELATIVE_ROI
from src.tasks.map_trade.models import (
    COVERED_CIRCLE_ICONS,
    CARD_BY_ID,
    CIRCLE_EXIT_WALKS,
    EVENT_WALK_EDGES,
    RESTART_NAV_ENTRIES,
    RESUMING_WALK_CARD_IDS,
    RESUMING_WALK_TIMEOUT,
    TOWN_NAV_ENTRIES,
    WALK_EDGES,
    WALK_LABEL_EDGES,
    WALK_ONLY_TARGETS,
    WALKED_EVENT_CARD_IDS,
    CardSpec,
    CollectionMapRole,
    CollectionMapTarget,
    MapPageMode,
    MatchResult,
    NavigationResult,
    ScreenState,
    TemplateSpec,
)
from src.tasks.map_trade.navigator_constants import (
    AREA_MAP_BACK_TEMPLATE,
    AREA_MAP_FOOTER_KEYWORDS,
    AREA_MAP_FOOTER_RELATIVE_ROI,
    AREA_MAP_HEADER_TAGS,
    AREA_MAP_CHANGE_INTERVAL,
    AREA_MAP_CHANGE_TIMEOUT,
    AREA_MAP_CLICK_SETTLE_SECONDS,
    AREA_MAP_EXIT_ICON_OFFSETS,
    AREA_MAP_KEY,
    AUTO_MOVE_CANCEL_ATTEMPTS,
    AUTO_MOVE_CANCEL_REFERENCE_POINT,
    AUTO_MOVE_IDLE_READS,
    AREA_MAP_EXIT_LABEL_RELATIVE_ROI,
    BATTLE_RESULT_BUTTONS_RELATIVE_ROI,
    BATTLE_RESULT_LEAVE_TEXT,
    EXIT_PICKER_BATTLE,
    EXIT_PICKER_SAFE,
    FIRST_CARD_PAID_DIALOG_MESSAGE,
    AREA_MAP_TELEPORT_BRIGHT_MAXIMUM_SPREAD,
    AREA_MAP_TELEPORT_BRIGHT_MINIMUM_GRAY,
    AREA_MAP_TELEPORT_BRIGHT_NEUTRAL_RATIO,
    AREA_MAP_TELEPORT_BRIGHT_RADIUS_RATIO,
    AREA_MAP_TELEPORT_CLUSTER_RADIUS,
    FIELD_ALL_KEYCAP_TEMPLATES,
    FIELD_KEYCAP_MIN_PASSES,
    HAND_TEMPLATE,
    MAP_PAGE_MODE_STABLE_HITS,
    MERCHANT_NAV_GUIDE_REFERENCE_POINT,
    MERCHANT_NAV_GUIDE_TEMPLATE,
    HUNTING_GROUND_NAV_ENTRY,
    HUNTING_GROUND_PANEL_PAIR,
    HUNTING_GROUND_MUST_STAND_ON_CIRCLE,
    HUNTING_GROUND_PANEL_WORD,
    MERCHANT_NAV_TOAST_OCR_ROI,
    MERCHANT_NAV_UNREACHABLE_KEYWORD,
    MERCHANT_TRAVEL_DIALOG_KEYWORDS,
    MERCHANT_TRAVEL_DIALOG_OCR_ROI,
    MERCHANT_NAV_GUIDE_TIMEOUT,
    MERCHANT_NAV_MENU_OCR_INTERVAL,
    MERCHANT_NAV_MENU_OCR_ROI,
    MERCHANT_NAV_MENU_OCR_TIMEOUT,
    MINIMAP_CENTER_REFERENCE,
    MINIMAP_LARGE_TEMPLATE,
    MINIMAP_SHRINK_ATTEMPTS,
    MINIMAP_SMALL_TEMPLATE,
    OVERLAP_ARROW_TEMPLATE,
    SANDBOX_CONFIRM_ACTION_TEMPLATES,
    SANDBOX_EMPTY_SLOT_TEMPLATES,
    SANDBOX_INTERACTION_PROBE_INTERVAL,
    SANDBOX_INTERACTION_PROBE_TIMEOUT,
    SANDBOX_LARGE_MAP_RETURN_REFERENCE_POINT,
    SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT,
    SANDBOX_MAP_EVIDENCE_MIN_COMPOSITE,
    SANDBOX_MAP_EVIDENCE_MIN_EDGE,
    SANDBOX_MAP_EVIDENCE_MIN_GRADIENT,
    SANDBOX_MAP_EVIDENCE_MIN_PIXEL,
    SANDBOX_MAP_EVIDENCE_MIN_SCORE,
    SANDBOX_MAP_EVIDENCE_MIN_ZNCC,
    SANDBOX_MAP_SETTLE_SECONDS,
    SANDBOX_MAP_BATTLE_EXIT_MIN_RED,
    AREA_MAP_LABELS_RELATIVE_ROI,
    SANDBOX_MAP_LABEL_ICON_REACH,
    SANDBOX_MAP_TELEPORT_GLYPH_RADIUS,
    SANDBOX_MAP_TELEPORT_MIN_GLYPH,
    SANDBOX_MAP_TELEPORT_MIN_PIXEL,
    SANDBOX_MAP_TELEPORT_TEMPLATE,
    SANDBOX_NAVIGATION_CONFIRM_TIMEOUT,
    SANDBOX_NAVIGATION_MAP_TIMEOUT,
    SANDBOX_NAVIGATION_OCR_INTERVAL,
    SANDBOX_NAVIGATION_OPEN_SETTLE_SECONDS,
    SANDBOX_NAVIGATION_OPEN_TEMPLATES,
    SANDBOX_NAVIGATION_OPEN_TIMEOUT,
    SANDBOX_NAVIGATION_TELEPORT_SETTLE_SECONDS,
    SANDBOX_NAVIGATION_WALK_TIMEOUT,
    SANDBOX_SKILL_ACTION_ICONS,
    SANDBOX_SKILL_GROUP_SWITCH_SETTLE_SECONDS,
    SANDBOX_SKILL_SELECTED_YELLOW_MIN_RATIO,
    SANDBOX_SKILL_SLOT_1_REFERENCE_CENTER,
    SANDBOX_SKILL_SLOT_1_RELATIVE_POINT,
    SANDBOX_SKILL_SLOT_1_SELECTED_TEMPLATE,
    SANDBOX_SKILL_SLOT_1_UNSELECTED_TEMPLATE,
    SANDBOX_SKILL_SLOT_2_SELECTED_TEMPLATE,
    SANDBOX_SKILL_SLOT_2_UNSELECTED_TEMPLATE,
    SANDBOX_SKILL_STATE_TEMPLATES,
    SANDBOX_SKILL_UNSELECTED_YELLOW_MAX_RATIO,
    SANDBOX_TELEPORT_SKILL_FAILURE_GROUPS,
    SANDBOX_TEMPLATES,
    STORY_SANDBOX_STABLE_HITS,
    STORY_SANDBOX_SWITCH_WINDOW,
    STORY_SANDBOX_SWITCH_WINDOW_HITS,
    TELEPORT_GENERATION_OCR_INTERVAL,
    TELEPORT_GENERATION_OCR_TIMEOUT,
    TELEPORT_INTERACTION_CLICK_DELAY,
    TELEPORT_INTERACTION_PRESSES,
    TELEPORT_INTERACTION_RECLICK_AFTER,
    TELEPORT_MAP_BACKWARD_TEMPLATE,
    TELEPORT_MAP_FIRST_PAGE_LIMIT,
    TELEPORT_MAP_FORWARD_TEMPLATE,
    TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI,
    TELEPORT_MAP_OPEN_TIMEOUT,
    TELEPORT_MAP_RETURN_REFERENCE_POINT,
    TELEPORT_MAP_RETURN_RELATIVE_POINT,
    TELEPORT_MAP_SEEK_LIMIT,
    LOOSE_PAGE_NAME_MIN_RATIO,
    TELEPORT_MAP_TITLE_REREAD_MIN_RATIO,
    TELEPORT_MAP_TITLE_REREAD_SCALES,
    TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATES,
    TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI,
    TELEPORT_LOADING_DARK_P95,
    TELEPORT_MAP_TRAVEL_SETTLE_SECONDS,
    TELEPORT_PAGE_END_READS,
    TELEPORT_PAGE_ORDER,
    TOWN_NPC_NAV_ENTRY,
    TRADE_CARD_SANDBOX_HITS,
    WALK_CAUGHT_KEYWORDS,
    WALK_CLICK_SETTLE_SECONDS,
    WALK_EXIT_ATTEMPTS,
    WALK_LABEL_KNOWN_READ_TIMEOUT,
    WALK_LABEL_READ_INTERVAL,
    WALK_LABEL_READ_TIMEOUT,
    FIELD_MAP_CLOSE_TIMEOUT,
    WALK_MAP_OPEN_TIMEOUT,
    AreaMapContext,
    SandboxConfirmation,
)
from src.tasks.map_trade.vision import normalize_text
from src.utils.calibration import FHD_1080
from src.utils.field_followers import dismiss_once_per_run
from src.utils.press_confirm import press_and_confirm, wait_for
from src.utils.wait_limits import STUCK_SECONDS, MotionWatch, StillTimer


# Field status text after a map click: '自动移动中：魔法阵' (bottom centre) and
# '已完成自动移动' (top centre); 1920x1080 fractions.
AUTO_MOVE_TEXT_RELATIVE_ROI = (560 / 1920, 80 / 1080, 1360 / 1920, 980 / 1080)
# The game's own word that a walk ended.
WALK_ARRIVED_TEXT = "完成自动移动"
# The game's 自动移动 dialog after a map destination is picked (player 1080p,
# YES-BD2 #24): 「是否自动移动前往所选目的地？」 with 取消 / 确认; it does not
# show once the player ticked 不再显示.
AUTO_MOVE_QUESTION_KEYWORDS = ("是否自动移动", "前往所选目的地")
AUTO_MOVE_CANCEL_TEXT = "取消"
NOT_BY_CIRCLE_MESSAGE = "人不在可用的传送阵上（右下 F 键的手势没变绿）"
# ≡-menu entries also found by a part of the name when one character is
# misread (「狩猎扬」), on a box no longer than the name.
NAV_ENTRY_NAMES = {"狩猎场": ("狩猎场", "狩猎", "猎场")}
# Rows the ≡ menu lists besides the trips asked for (梦幻广场 at 2K
# 2026-10-17; story towns in the tests): one read means the menu is open.
NAV_MENU_WORDS = (
    "旅馆", "招募", "商店", "酒馆", "码头", "领地", "餐厅", "虚拟角色", "脱离当前场景"
)
NAV_MENU_ROW_CHARS = 8
# A ≡ press after which the menu lists nothing is made once more.
NAV_MENU_PRESSES = 2
# The game's interact key, as its hand prompt shows it in the field.
INTERACT_KEY = "F"
# A press on the area map's circle that opened nothing is made once more.
TELEPORT_ICON_PRESSES = 2
# Looks (0.5 s apart) for the large map to close by itself once a walk was
# confirmed, before it is closed by its back button.
MAP_SELF_CLOSE_LOOKS = 3
# Teleport-map page arrows (1920x1080 reference), measured on 华特波尔雪山 at 2K.
TELEPORT_PAGE_ARROW_REFERENCE = {"left": (380, 520), "right": (1540, 520)}


# A story entry keeps this much of its wait for a reward page (赛季奖励 and
# the like) that hides the field, and gives the field at least this long
# after such a page was dismissed.
STORY_ENTRY_PAGE_RESERVE_SECONDS = 5.0
STORY_ENTRY_AFTER_PAGE_SECONDS = 10.0
# One more look when the wait ends with the field on its last frame.
FIELD_HUD_LAST_LOOK_SECONDS = 1.5

# How long a field is looked for after a teleport page failed to open.
SANDBOX_MAP_CLOSE_TIMEOUT = 3.0
# What reopens a circle's 传送页 that did not open after its hand.
CIRCLE_PAGE_AGAIN = ("hand", "key")

class SandboxNavigationMixin:
    @staticmethod
    def _format_sandbox_matches(
        matches: tuple[tuple[str, MatchResult, bool], ...],
    ) -> str:
        return "; ".join(
            (
                f"{name}={'pass' if passed else 'miss'}"
                f"(m={result.score:.3f},p={result.pixel_score:.3f},"
                f"z={result.zncc_score:.3f})"
            )
            for name, result, passed in matches
        )

    @staticmethod
    def _sandbox_evidence_rank(candidate) -> tuple[float, ...]:
        result = getattr(candidate, "result", candidate)
        values = (
            float(getattr(result, "score", -1.0)),
            float(getattr(result, "pixel_score", -1.0)),
            float(getattr(result, "zncc_score", -1.0)),
            float(getattr(result, "gradient_zncc_score", -1.0)),
            float(getattr(result, "edge_score", -1.0)),
        )
        finite = tuple(value for value in values if np.isfinite(value) and value > -1.0)
        composite = sum(finite) / len(finite) if finite else -1.0
        return (composite, *values)

    def _sandbox_has_evidence_matcher(self) -> bool:
        return callable(getattr(self.vision, "match_evidence_all", None)) and callable(
            getattr(self.vision, "match_slot_evidence", None)
        )

    def _sandbox_frame_geometry(self, frame: np.ndarray):
        assess = getattr(self.vision, "assess_frame", None)
        if not callable(assess):
            return None
        try:
            return assess(
                frame,
                required_relative_rois=tuple(ACTION_SLOT_RELATIVE_ROIS.values()),
                purpose="箱庭技能栏",
            )
        except (AttributeError, TypeError, ValueError) as exc:
            self._status("箱庭画面几何", f"检查异常：{exc}")
            return False

    def _sandbox_evidence_spec_match(
        self,
        frame: np.ndarray,
        spec: TemplateSpec,
        *,
        purpose: str,
        geometry=None,
        allow_map_composite: bool = False,
    ) -> tuple[MatchResult, bool]:
        """Return the strongest retained candidate and apply the old spec gate."""

        matcher = getattr(self.vision, "match_evidence_all", None)
        candidates = ()
        if callable(matcher):
            try:
                candidates = tuple(
                    matcher(
                        frame,
                        spec,
                        minimum_score=0.30,
                        peak_radius=4,
                        max_results=6,
                        geometry=geometry,
                        purpose=purpose,
                    )
                )
            except (AttributeError, TypeError, ValueError):
                candidates = ()
        if candidates:
            selected = max(candidates, key=self._sandbox_evidence_rank)
            result = getattr(selected, "result", selected)
        else:
            try:
                result = self.vision.match(frame, spec)
            except (AttributeError, TypeError, ValueError):
                result = MatchResult(-1.0, (0, 0), (0, 0))
        try:
            passed = bool(self.vision.passes(result, spec))
        except (AttributeError, TypeError, ValueError):
            passed = False
        if not passed and allow_map_composite:
            values = (
                result.score,
                result.pixel_score,
                result.zncc_score,
                result.gradient_zncc_score,
                result.edge_score,
            )
            finite = all(np.isfinite(value) for value in values)
            composite = sum(values) / len(values) if finite else -1.0
            passed = bool(
                finite
                and result.score >= SANDBOX_MAP_EVIDENCE_MIN_SCORE
                and result.pixel_score >= SANDBOX_MAP_EVIDENCE_MIN_PIXEL
                and result.zncc_score >= SANDBOX_MAP_EVIDENCE_MIN_ZNCC
                and result.gradient_zncc_score >= SANDBOX_MAP_EVIDENCE_MIN_GRADIENT
                and result.edge_score >= SANDBOX_MAP_EVIDENCE_MIN_EDGE
                and composite >= SANDBOX_MAP_EVIDENCE_MIN_COMPOSITE
            )
        return result, passed

    def _sandbox_skill_group_evidence(self, frame: np.ndarray, geometry):
        skill_matches = tuple(
            (
                spec.name,
                *self._sandbox_evidence_spec_match(
                    frame,
                    spec,
                    purpose="箱庭技能组确认",
                    geometry=geometry,
                ),
            )
            for spec in SANDBOX_SKILL_STATE_TEMPLATES
        )
        skill_state_hits = sum(1 for _name, _result, passed in skill_matches if passed)
        slot_states = (
            self._sandbox_skill_slot_state(
                frame,
                SANDBOX_SKILL_SLOT_1_SELECTED_TEMPLATE,
                skill_matches[0][1],
                skill_matches[0][2],
                SANDBOX_SKILL_SLOT_1_UNSELECTED_TEMPLATE,
                skill_matches[3][1],
                skill_matches[3][2],
            ),
            self._sandbox_skill_slot_state(
                frame,
                SANDBOX_SKILL_SLOT_2_SELECTED_TEMPLATE,
                skill_matches[2][1],
                skill_matches[2][2],
                SANDBOX_SKILL_SLOT_2_UNSELECTED_TEMPLATE,
                skill_matches[1][1],
                skill_matches[1][2],
            ),
        )
        skill_group = None
        if slot_states == ("selected", "unselected"):
            skill_group = 1
        elif slot_states == ("unselected", "selected"):
            skill_group = 2
        self._status(
            "箱庭技能组状态",
            (
                f"命中={skill_state_hits}/4；颜色状态={slot_states}；"
                f"状态={'技能组' + str(skill_group) if skill_group else '未知/冲突'}；"
                f"{self._format_sandbox_matches(skill_matches)}"
            ),
        )
        return skill_matches, skill_state_hits, skill_group

    @staticmethod
    def _sandbox_action_state_is_hit(detection: ActionIconDetection) -> bool:
        return detection.state in {
            ActionIconState.AVAILABLE,
            ActionIconState.USED,
        } and detection.semantic_state not in {
            "countdown",
            "empty",
            "wrong_group",
        }

    def _sandbox_empty_slot_detected(
        self,
        frame: np.ndarray,
        icon,
        geometry,
    ) -> bool:
        if icon.slot_name is None:
            return False
        empty_spec = dict(SANDBOX_EMPTY_SLOT_TEMPLATES).get(icon.slot_name)
        if empty_spec is None:
            return False
        center_reference = ACTION_SLOT_CENTERS_REFERENCE[icon.slot_name]
        if geometry is None:
            height, width = frame.shape[:2]
            center = (
                round(width * center_reference[0] / SKILL_REFERENCE_WIDTH),
                round(height * center_reference[1] / SKILL_REFERENCE_HEIGHT),
            )
            scale = min(width / SKILL_REFERENCE_WIDTH, height / SKILL_REFERENCE_HEIGHT)
        else:
            center = (
                geometry.content_left
                + round(geometry.content_width * center_reference[0] / SKILL_REFERENCE_WIDTH),
                geometry.content_top
                + round(geometry.content_height * center_reference[1] / SKILL_REFERENCE_HEIGHT),
            )
            scale = geometry.client_scale
        radius = tuple(
            max(5, round(value * scale))
            for value in ACTION_SLOT_SEARCH_RADII_REFERENCE[icon.slot_name]
        )
        matcher = getattr(self.vision, "match_slot_evidence", None)
        if callable(matcher):
            try:
                candidates = tuple(
                    matcher(
                        frame,
                        empty_spec,
                        center,
                        radius=radius,
                        geometry=geometry,
                        minimum_score=0.35,
                        max_results=3,
                        purpose=f"{icon.name}空槽",
                    )
                )
            except (AttributeError, TypeError, ValueError):
                candidates = ()
            for candidate in candidates:
                result = getattr(candidate, "result", candidate)
                try:
                    if self.vision.passes(result, empty_spec):
                        return True
                except (AttributeError, TypeError, ValueError):
                    continue
        return False

    def _sandbox_action_semantic_state(
        self,
        frame: np.ndarray,
        icon,
        detection: ActionIconDetection,
        geometry,
    ) -> str:
        if icon.slot_name == "search":
            try:
                text = self.vision.simplify(
                    self.vision.ocr_text(
                        frame,
                        "箱庭探查倒计时",
                        relative_roi=SEARCH_COUNTDOWN_RELATIVE_ROI,
                    )
                )
            except (AttributeError, TypeError, ValueError):
                text = ""
            if re.fullmatch(r"\s*\d{1,3}\s*", str(text)):
                return "countdown"
        if self._sandbox_empty_slot_detected(frame, icon, geometry):
            return "empty"
        if detection.state is not ActionIconState.ABSENT:
            return detection.semantic_state or detection.state.value
        return "unknown"

    def _match_story_sandbox_signals_with_evidence(
        self,
        frame: np.ndarray,
        geometry,
    ) -> SandboxConfirmation:
        map_matches = tuple(
            (
                spec.name,
                *self._sandbox_evidence_spec_match(
                    frame,
                    spec,
                    purpose="箱庭地图确认",
                    geometry=geometry,
                    allow_map_composite=True,
                ),
            )
            for spec in SANDBOX_TEMPLATES
        )
        map_signal_hits = sum(1 for _name, _result, passed in map_matches if passed)
        self._status(
            "箱庭确认信号",
            f"命中={map_signal_hits}/2；{self._format_sandbox_matches(map_matches)}",
        )

        skill_matches, skill_state_hits, skill_group = self._sandbox_skill_group_evidence(
            frame,
            geometry,
        )

        action_states: list[tuple[str, str]] = []
        action_detections: list[ActionIconDetection] = []
        if skill_group != 1:
            action_hits = 0
            action_states = [
                (icon.name, "wrong_group") for icon in SANDBOX_SKILL_ACTION_ICONS
            ]
        else:
            detector = ActionIconDetector(self.vision)
            for icon in SANDBOX_SKILL_ACTION_ICONS:
                detection = detector.detect(frame, icon, geometry=geometry)
                semantic = self._sandbox_action_semantic_state(
                    frame,
                    icon,
                    detection,
                    geometry,
                )
                if semantic != detection.semantic_state:
                    detection = replace(
                        detection,
                        semantic_state=semantic,
                        reason=(
                            f"{detection.reason}；语义={semantic}"
                            if detection.reason
                            else f"语义={semantic}"
                        ),
                    )
                action_detections.append(detection)
                action_states.append((icon.name, semantic))
            action_hits = sum(
                self._sandbox_action_state_is_hit(detection)
                for detection in action_detections
            )

        self._status(
            "箱庭进一步确认",
            "动作图标命中="
            f"{action_hits}/{len(SANDBOX_SKILL_ACTION_ICONS)}；"
            + "; ".join(
                f"{name}={state}" for name, state in action_states
            ),
        )
        confirmation = SandboxConfirmation(
            map_signal_hits=map_signal_hits,
            skill_state_hits=skill_state_hits,
            action_hits=action_hits,
            skill_group=skill_group,
            geometry=geometry,
            action_states=tuple(action_states),
            reason=(
                "错误技能组：" + str(skill_group)
                if skill_group not in {None, 1}
                else ("技能组无法唯一确认" if skill_group is None else "")
            ),
        )
        self._status(
            "箱庭复合确认",
            (
                f"{'pass' if confirmation.passed else 'miss'}；"
                f"地图={map_signal_hits}/2(至少1)，"
                f"技能组={skill_state_hits}/4(至少2)，"
                f"动作={action_hits}/{len(SANDBOX_SKILL_ACTION_ICONS)}(至少3)"
            ),
        )
        return confirmation

    def _match_story_sandbox_signals(
        self,
        frame: np.ndarray,
    ) -> SandboxConfirmation:
        if not self._sandbox_has_evidence_matcher():
            return self._match_story_sandbox_signals_legacy(frame)
        geometry = self._sandbox_frame_geometry(frame)
        if geometry is False:
            return SandboxConfirmation(
                0,
                0,
                0,
                None,
                reason="画面几何检查异常",
            )
        if geometry is not None and not geometry.accepted:
            reason = "画面几何拒绝：" + "|".join(geometry.rejection_reasons)
            self._status("箱庭复合确认", reason)
            return SandboxConfirmation(
                0,
                0,
                0,
                None,
                geometry=geometry,
                reason=reason,
            )
        return self._match_story_sandbox_signals_with_evidence(frame, geometry)

    def _match_story_sandbox_signals_legacy(
        self,
        frame: np.ndarray,
    ) -> SandboxConfirmation:
        """Match all story-sandbox confirmation signals on one frame."""

        map_matches = tuple(
            (
                spec.name,
                result := self.vision.match(frame, spec),
                self.vision.passes(result, spec),
            )
            for spec in SANDBOX_TEMPLATES
        )
        map_signal_hits = sum(1 for _name, _result, passed in map_matches if passed)
        self._status(
            "箱庭确认信号",
            (
                f"命中={map_signal_hits}/2；"
                f"{self._format_sandbox_matches(map_matches)}"
            ),
        )

        skill_matches = tuple(
            (
                spec.name,
                result := self.vision.match(frame, spec),
                self.vision.passes(result, spec),
            )
            for spec in SANDBOX_SKILL_STATE_TEMPLATES
        )
        skill_state_hits = sum(1 for _name, _result, passed in skill_matches if passed)
        slot_states = (
            self._sandbox_skill_slot_state(
                frame,
                SANDBOX_SKILL_SLOT_1_SELECTED_TEMPLATE,
                skill_matches[0][1],
                skill_matches[0][2],
                SANDBOX_SKILL_SLOT_1_UNSELECTED_TEMPLATE,
                skill_matches[3][1],
                skill_matches[3][2],
            ),
            self._sandbox_skill_slot_state(
                frame,
                SANDBOX_SKILL_SLOT_2_SELECTED_TEMPLATE,
                skill_matches[2][1],
                skill_matches[2][2],
                SANDBOX_SKILL_SLOT_2_UNSELECTED_TEMPLATE,
                skill_matches[1][1],
                skill_matches[1][2],
            ),
        )
        skill_group = None
        if slot_states == ("selected", "unselected"):
            skill_group = 1
        elif slot_states == ("unselected", "selected"):
            skill_group = 2
        self._status(
            "箱庭技能组状态",
            (
                f"命中={skill_state_hits}/4；"
                f"颜色状态={slot_states}；"
                f"状态={'技能组' + str(skill_group) if skill_group else '未知/冲突'}；"
                f"{self._format_sandbox_matches(skill_matches)}"
            ),
        )

        if skill_group == 1:
            action_matches = tuple(
                (
                    name,
                    result := self.vision.match(frame, spec),
                    self.vision.passes(result, spec),
                )
                for name, spec in SANDBOX_CONFIRM_ACTION_TEMPLATES
            )
        else:
            action_matches = tuple(
                (
                    name,
                    MatchResult(-1.0, (0, 0), (0, 0)),
                    False,
                )
                for name, _spec in SANDBOX_CONFIRM_ACTION_TEMPLATES
            )
        action_hits = sum(1 for _name, _result, passed in action_matches if passed)
        self._status(
            "箱庭进一步确认",
            (
                f"动作图标命中={action_hits}/5；"
                f"{self._format_sandbox_matches(action_matches)}"
            ),
        )
        confirmation = SandboxConfirmation(
            map_signal_hits=map_signal_hits,
            skill_state_hits=skill_state_hits,
            action_hits=action_hits,
            skill_group=skill_group,
            action_states=tuple(
                (name, "available" if passed else "wrong_group")
                for name, _result, passed in action_matches
            ),
            reason=(
                "错误技能组：" + str(skill_group)
                if skill_group not in {None, 1}
                else ("技能组无法唯一确认" if skill_group is None else "")
            ),
        )
        self._status(
            "箱庭复合确认",
            (
                f"{'pass' if confirmation.passed else 'miss'}；"
                f"地图={map_signal_hits}/2(至少1)，"
                f"技能组={skill_state_hits}/4(至少2)，"
                f"动作={action_hits}/5(至少3)"
            ),
        )
        return confirmation

    def _sandbox_skill_slot_state(
        self,
        frame: np.ndarray,
        selected_spec: TemplateSpec,
        selected_result: MatchResult,
        selected_passed: bool,
        unselected_spec: TemplateSpec,
        unselected_result: MatchResult,
        unselected_passed: bool,
    ) -> str:
        """Classify one skill slot from structure plus masked HSV semantics."""

        color_ratios = self.vision.template_hsv_color_ratios
        candidates = (
            (
                selected_spec,
                selected_result,
                selected_passed,
            ),
            (
                unselected_spec,
                unselected_result,
                unselected_passed,
            ),
        )
        colors = tuple(
            (
                spec,
                color_ratios(frame, spec, result),
            )
            for spec, result, passed in candidates
            if passed
        )

        selected_colors = next(
            (values for spec, values in colors if spec is selected_spec),
            None,
        )
        unselected_colors = next(
            (values for spec, values in colors if spec is unselected_spec),
            None,
        )
        def format_colors(values: tuple[float, float, float] | None) -> str:
            if values is None:
                return "missing"
            return f"y={values[0]:.3f},n={values[1]:.3f},b={values[2]:.3f}"
        self._status(
            "箱庭技能槽颜色",
            (
                f"{selected_spec.name}[{format_colors(selected_colors)}]；"
                f"{unselected_spec.name}[{format_colors(unselected_colors)}]"
            ),
        )
        selected_is_yellow = any(
            values[0] >= SANDBOX_SKILL_SELECTED_YELLOW_MIN_RATIO
            for _spec, values in colors
            if values is not None
        )
        unselected_is_gray = any(
            values[0] <= SANDBOX_SKILL_UNSELECTED_YELLOW_MAX_RATIO
            and values[1] >= 0.20
            for _spec, values in colors
            if values is not None
        )
        if selected_is_yellow and not unselected_is_gray:
            return "selected"
        if unselected_is_gray and not selected_is_yellow:
            return "unselected"
        return "unknown"

    def _click_sandbox_skill_group_1(self) -> None:
        """Switch to the first sandbox skill group using its calibrated center."""

        self._status(
            "箱庭技能组切换",
            (
                "技能组2已选中，点击技能组1预设中心"
                f"({SANDBOX_SKILL_SLOT_1_REFERENCE_CENTER[0]}"
                f",{SANDBOX_SKILL_SLOT_1_REFERENCE_CENTER[1]})"
            ),
        )
        self.task.operate_click(
            *SANDBOX_SKILL_SLOT_1_RELATIVE_POINT,
            after_sleep=SANDBOX_SKILL_GROUP_SWITCH_SETTLE_SECONDS,
        )

    def _wait_for_confirmed_sandbox(
        self,
        *,
        timeout: float,
        interval: float,
        success_message: str,
        failure_message: str,
        handle_intermediate: bool = False,
    ) -> NavigationResult:
        end_at = monotonic() + max(0.0, timeout)
        last_state = ScreenState.UNKNOWN
        sandbox_hits = 0
        skill_group_switch_attempted = False
        switch_group_one_history: list[bool] = []
        group_two_streak = 0
        while monotonic() <= end_at:
            frame = self.vision.capture()
            last_state = self.classify(frame)
            self._status("导航状态", last_state.value)
            if last_state == ScreenState.SANDBOX:
                confirmation = self._match_story_sandbox_signals(frame)
                if (
                    confirmation.skill_group == 2
                    and not skill_group_switch_attempted
                ):
                    self._click_sandbox_skill_group_1()
                    skill_group_switch_attempted = True
                    sandbox_hits = 0
                    switch_group_one_history.clear()
                    continue
                if skill_group_switch_attempted and confirmation.skill_group != 1:
                    switch_group_one_history.append(False)
                    del switch_group_one_history[:-STORY_SANDBOX_SWITCH_WINDOW]
                    self._status(
                        "箱庭技能组切换",
                        (
                            "点击技能组1后仍未确认技能组1状态，"
                            f"切换窗口={sum(switch_group_one_history)}"
                            f"/{STORY_SANDBOX_SWITCH_WINDOW}"
                        ),
                    )
                    sandbox_hits = 0
                    if confirmation.skill_group == 2:
                        group_two_streak += 1
                        if group_two_streak >= STORY_SANDBOX_SWITCH_WINDOW:
                            self._status(
                                "箱庭技能组切换",
                                (
                                    f"点击技能组1后连续{group_two_streak}帧"
                                    "仍识别为技能组2，切换失败"
                                ),
                            )
                            return NavigationResult(
                                False,
                                last_state,
                                (
                                    f"点击技能组1后连续"
                                    f"{STORY_SANDBOX_SWITCH_WINDOW}"
                                    "帧仍识别为技能组2，切换失败"
                                ),
                            )
                    else:
                        group_two_streak = 0
                elif skill_group_switch_attempted:
                    group_two_streak = 0
                    switch_group_one_history.append(confirmation.passed)
                    del switch_group_one_history[:-STORY_SANDBOX_SWITCH_WINDOW]
                    window_hits = sum(switch_group_one_history)
                    self._status(
                        "箱庭稳定确认",
                        (
                            f"切换窗口={window_hits}"
                            f"/{STORY_SANDBOX_SWITCH_WINDOW_HITS}"
                            f"（{len(switch_group_one_history)}帧）"
                        ),
                    )
                    if (
                        len(switch_group_one_history) >= STORY_SANDBOX_SWITCH_WINDOW
                        and window_hits >= STORY_SANDBOX_SWITCH_WINDOW_HITS
                    ):
                        return NavigationResult(True, last_state, success_message)
                elif confirmation.passed:
                    sandbox_hits += 1
                    self._status(
                        "箱庭稳定确认",
                        f"{sandbox_hits}/{STORY_SANDBOX_STABLE_HITS}",
                    )
                    if sandbox_hits >= STORY_SANDBOX_STABLE_HITS:
                        return NavigationResult(True, last_state, success_message)
                else:
                    sandbox_hits = 0
            else:
                sandbox_hits = 0
            if handle_intermediate and last_state not in {
                ScreenState.LOADING,
                ScreenState.SANDBOX,
            }:
                handled = self._handle_story_card_intermediate(frame)
                if isinstance(handled, NavigationResult):
                    return handled
                if handled:
                    continue
            if interval > 0:
                self.task.sleep(interval)
        return NavigationResult(False, last_state, failure_message)

    def _wait_for_field_hud(
        self,
        *,
        timeout: float,
        interval: float,
        success_message: str,
        failure_message: str,
        handle_intermediate: bool = False,
    ) -> NavigationResult:
        """The story field on consecutive frames, whatever the skill layout.

        The stricter check demanded 探查/吸收/召集 in skill group 1; players
        keep them elsewhere (the user: cooking in group 1, collection in
        group 2), so entry is judged by the field HUD as trade does, and the
        skill step picks the group that holds the icons.
        """
        stall = max(0.0, timeout)
        end_at = monotonic() + stall
        # Walking is progress, not a stall (Leo 2026-09-30: a stall ends after
        # 15 s): time under "自动移动中" does not count, up to the walk cap.
        walk_cap = end_at + SANDBOX_NAVIGATION_WALK_TIMEOUT
        self._field_wait_only = True
        self._field_wait_cut = False
        try:
            result = self._wait_for_field_hud_loop(
                end_at=end_at,
                stall=stall,
                walk_cap=walk_cap,
                interval=interval,
                success_message=success_message,
                handle_intermediate=handle_intermediate,
            )
        finally:
            self._field_wait_only = False
        if isinstance(result, NavigationResult):
            return result
        last_state, last_frame = result
        if self._field_wait_cut and last_state == ScreenState.UNKNOWN and last_frame is not None:
            # Not the field in time: name the page fully for the failure.
            last_state = self.classify(last_frame)
        return NavigationResult(False, last_state, failure_message)

    def _wait_for_field_hud_loop(
        self,
        *,
        end_at: float,
        stall: float,
        walk_cap: float,
        interval: float,
        success_message: str,
        handle_intermediate: bool,
    ) -> NavigationResult | tuple[ScreenState, object]:
        hits = 0
        last_state = ScreenState.UNKNOWN
        frame = None
        grace_used = False
        # Loading and walking only hold the wait while the screen moves: one
        # still for STUCK_SECONDS is stuck (Leo 2026-10-14 「頂多等8秒到10秒」).
        still = StillTimer()
        while True:
            if monotonic() > end_at:
                if hits == 0 or grace_used:
                    break
                # The field was on the last frame when time ran out: look
                # once more instead of failing (2K 10-12 Q_sp4 凯洛镇: field
                # seen at 0.991, then 入场确认超时 and the teleport redone).
                grace_used = True
                end_at = monotonic() + FIELD_HUD_LAST_LOOK_SECONDS
            frame = self.vision.capture()
            # The black loading screen needs none of the home/field checks
            # (~0.6 s a read; Leo 2026-10-01: 換圖速度).
            last_state = (
                ScreenState.LOADING if self._black_frame(frame) else self.classify(frame)
            )
            self._status("导航状态", last_state.value)
            if last_state == ScreenState.SANDBOX:
                hits += 1
                if hits >= TRADE_CARD_SANDBOX_HITS:
                    return NavigationResult(True, last_state, success_message)
                # The second frame is taken at once: the field is already
                # read, there is nothing to wait for (2K 10-12: +1.2 s a map).
                continue
            else:
                hits = 0
                # A loading screen is progress too (audit #10: on a slow PC the
                # loading used up the stall and the entry was judged failed).
                if (
                    last_state == ScreenState.LOADING or self._auto_moving(frame)
                ) and still.still_for(frame, monotonic()) < STUCK_SECONDS:
                    end_at = min(max(end_at, monotonic() + stall), walk_cap)
                if handle_intermediate and last_state != ScreenState.LOADING:
                    handled = self._handle_story_card_intermediate(frame)
                    if isinstance(handled, NavigationResult):
                        return handled
                    if handled:
                        continue
            if interval > 0:
                self.task.sleep(interval)
        return last_state, frame

    def _wait_for_story_sandbox(
        self,
        target_number: int,
        timeout: float | None = None,
        interval: float = 0.5,
    ) -> NavigationResult:
        wait_seconds = max(0.0, self._loading_timeout() if timeout is None else float(timeout))
        deadline = monotonic() + wait_seconds
        for attempt in range(2):
            # Capped at the budget: deadline - now can round a hair above it.
            remaining = min(wait_seconds, max(0.0, deadline - monotonic()))
            if attempt:
                # The page was dismissed: the field shows in a moment.
                remaining = max(remaining, STORY_ENTRY_AFTER_PAGE_SECONDS)
            elif remaining > 2 * STORY_ENTRY_PAGE_RESERVE_SECONDS:
                # Audit #9: the first wait took the whole budget, so the
                # season-reward page check after it never ran.
                remaining -= STORY_ENTRY_PAGE_RESERVE_SECONDS
            result = self._wait_for_field_hud(
                timeout=remaining,
                interval=interval,
                success_message=f"Q_sp{target_number}",
                failure_message=f"剧情游戏卡{target_number}入场确认超时",
                handle_intermediate=True,
            )
            if result.success:
                dismiss_once_per_run(self)
            # A dialog that may spend something stops here, not retried.
            if result.success or attempt or result.message == FIRST_CARD_PAID_DIALOG_MESSAGE:
                return result
            remaining = min(wait_seconds, max(0.0, deadline - monotonic()))
            if remaining <= 0.0:
                return result
            if self.task._handle_recent_cartridge_special_pages(
                timeout=min(remaining, STORY_ENTRY_PAGE_RESERVE_SECONDS),
                allow_pvp_pages=False,
            ) is not CartridgeSpecialPageResult.HANDLED:
                return result

    def _wait_for_current_sandbox(
        self,
        timeout: float = 3.0,
        interval: float = 0.5,
    ) -> NavigationResult:
        """Confirm the current story field on consecutive frames (any skill layout)."""

        return self._wait_for_field_hud(
            timeout=timeout,
            interval=interval,
            success_message="已稳定确认剧情卡带箱庭",
            failure_message="未稳定确认当前剧情卡带箱庭",
        )

    @staticmethod
    def _sandbox_teleport_skill_failure_matches(text: str) -> bool:
        normalized = normalize_text(text)
        return any(
            all(normalize_text(keyword) in normalized for keyword in group)
            for group in SANDBOX_TELEPORT_SKILL_FAILURE_GROUPS
        )

    def _sandbox_teleport_skill_failure_text(self, frame: np.ndarray) -> str:
        try:
            text = self.vision.simplify(
                self.vision.ocr_text(frame, "箱庭5号传送阵技能失败")
            )
        except Exception as exc:
            self._status("箱庭5号传送阵技能失败 OCR错误", str(exc))
            return ""
        if not self._sandbox_teleport_skill_failure_matches(text):
            return ""
        self._status("箱庭5号传送阵技能失败 OCR", text)
        return text

    def _click_sandbox_teleport_interaction(
        self,
        timeout: float = SANDBOX_INTERACTION_PROBE_TIMEOUT,
    ) -> bool:
        """Click the portal interaction prompt when the character is already nearby."""

        end_at = monotonic() + max(0.0, timeout)
        last = MatchResult(-1.0, (0, 0), (0, 0))
        while monotonic() <= end_at:
            frame = self.vision.capture()
            last = self.vision.match(frame, HAND_TEMPLATE)
            passed = self.vision.passes(last, HAND_TEMPLATE)
            self._status(
                "传送阵交互按钮",
                (
                    f"{'pass' if passed else 'miss'}; center={last.center}, "
                    f"match={last.score:.3f}, pixel={last.pixel_score:.3f}, "
                    f"zncc={last.zncc_score:.3f}"
                ),
            )
            if passed:
                for press in range(TELEPORT_INTERACTION_PRESSES):
                    if press:
                        self.task.log_info("跑图：按了传送阵交互按钮后手还在，再按一次。")
                    self.vision.click_client(
                        last.center,
                        frame.shape,
                        after_sleep=TELEPORT_INTERACTION_CLICK_DELAY,
                    )
                    if press + 1 == TELEPORT_INTERACTION_PRESSES:
                        break
                    still = self._hand_still_shown()
                    if still is None:
                        break
                    last, frame = still
                return True
            self.task.sleep(SANDBOX_INTERACTION_PROBE_INTERVAL)
        self._status(
            "传送阵交互按钮",
            (
                "探测超时；"
                f"last_match={last.score:.3f}, pixel={last.pixel_score:.3f}, "
                f"zncc={last.zncc_score:.3f}"
            ),
        )
        return False

    def _hand_still_shown(self):
        """(match, frame) when the hand passes on every look for the re-press wait."""
        end_at = monotonic() + TELEPORT_INTERACTION_RECLICK_AFTER
        looks = 0
        while True:
            frame = self.vision.capture()
            match = self.vision.match(frame, HAND_TEMPLATE)
            if not self.vision.passes(match, HAND_TEMPLATE):
                return None
            looks += 1
            if looks >= 2 and monotonic() >= end_at:
                return match, frame
            self.task.sleep(SANDBOX_INTERACTION_PROBE_INTERVAL)

    def _wait_for_sandbox_map_open(
        self,
        trigger_name: str,
        *,
        expected_mode: MapPageMode,
        timeout: float = TELEPORT_MAP_OPEN_TIMEOUT,
        detect_skill_failure: bool = False,
    ) -> NavigationResult:
        """Confirm a stable visual mode and reject entry/page semantic conflicts."""

        end_at = monotonic() + max(0.0, timeout)
        last_state = ScreenState.UNKNOWN
        stable_hits = 0
        while monotonic() <= end_at:
            frame = self.vision.capture()
            detection = self._detect_map_page_mode(frame)
            if detection.mode.is_teleport_map:
                last_state = ScreenState.AREA_MAP
            elif detection.mode == MapPageMode.SANDBOX_LARGE_MAP:
                last_state = ScreenState.SANDBOX_MAP
            else:
                last_state = ScreenState.UNKNOWN
            if detection.mode == expected_mode:
                stable_hits += 1
            else:
                stable_hits = 0
            self._status(
                "传送阵地图确认",
                (
                    f"trigger={trigger_name}; expected={expected_mode.value}; "
                    f"observed={detection.mode.value}; "
                    f"stable={stable_hits}/{MAP_PAGE_MODE_STABLE_HITS}"
                ),
            )
            # Header 移动魔法阵 and its icon in one frame are two proofs already:
            # one read is enough (Leo 2026-10-01, ~1 s a move).
            sure_direct = (
                detection.mode == MapPageMode.DIRECT_TELEPORT
                and "移动魔法阵" in normalize_text(getattr(detection, "header_text", ""))
                and any(
                    "交互直传页图标=pass" in item for item in getattr(detection, "evidence", ())
                )
            )
            if stable_hits >= MAP_PAGE_MODE_STABLE_HITS or (stable_hits and sure_direct):
                return NavigationResult(
                    True,
                    ScreenState.AREA_MAP,
                    f"{trigger_name}后确认{expected_mode.value}",
                    map_page_mode=detection.mode,
                )
            if detection.mode != MapPageMode.UNKNOWN and detection.mode != expected_mode:
                return NavigationResult(
                    False,
                    last_state,
                    (
                        f"{trigger_name}入口与实际地图页面不一致："
                        f"expected={expected_mode.value}, observed={detection.mode.value}"
                    ),
                    map_page_mode=detection.mode,
                )
            if detect_skill_failure:
                failure_text = self._sandbox_teleport_skill_failure_text(frame)
                if failure_text:
                    return NavigationResult(
                        False,
                        ScreenState.SANDBOX,
                        f"{trigger_name}失败 OCR命中：{failure_text}",
                    )
            # The second confirming read comes sooner (0.5 s cost ~1 s per
            # move with the read itself, live 2K 2026-10-01).
            self.task.sleep(0.15 if stable_hits else 0.5)
        return NavigationResult(
            False,
            last_state,
            f"{trigger_name}后未稳定确认{expected_mode.value}",
        )

    def _click_sandbox_navigation_map(
        self,
        timeout: float = SANDBOX_NAVIGATION_OPEN_TIMEOUT,
    ) -> bool:
        """Open the upper-left sandbox navigation map from a recognized icon."""

        end_at = monotonic() + max(0.0, timeout)
        while monotonic() <= end_at:
            frame = self.vision.capture()
            for spec in SANDBOX_NAVIGATION_OPEN_TEMPLATES:
                result = self.vision.match(frame, spec)
                passed = self.vision.passes(result, spec)
                self._status(
                    spec.name,
                    (
                        f"{'pass' if passed else 'miss'}; center={result.center}, "
                        f"match={result.score:.3f}, pixel={result.pixel_score:.3f}, "
                        f"zncc={result.zncc_score:.3f}"
                    ),
                )
                if passed:
                    self.vision.click_client(
                        result.center,
                        frame.shape,
                        after_sleep=SANDBOX_NAVIGATION_OPEN_SETTLE_SECONDS,
                    )
                    return True
            self.task.sleep(SANDBOX_NAVIGATION_OCR_INTERVAL)
        return False

    def _sandbox_navigation_page_has_keyword(self, frame: np.ndarray) -> bool:
        return self._detect_map_page_mode(frame).mode == MapPageMode.SANDBOX_LARGE_MAP

    def _round_map_icons(self, frame: np.ndarray) -> list[MatchResult]:
        """Places on the area map that look like a round icon frame, the most
        alike first.  The circle, inn, shop and NPC icons share that frame."""
        try:
            candidates = self.vision.match_all(
                frame,
                SANDBOX_MAP_TELEPORT_TEMPLATE,
                minimum_score=self.vision.threshold_for(SANDBOX_MAP_TELEPORT_TEMPLATE),
                peak_radius=12,
            )
        except (AttributeError, TypeError, ValueError):
            candidates = ()
        # The masked template scores ~0.90 on any plain stretch of the map
        # (60 passes on 施塔因之塔第6层 at 2K, 2026-09-29) and "exactly one"
        # never held; the pixel similarity ranks them, the glyph decides.
        return sorted(
            (
                result
                for result in candidates
                if self.vision.passes(result, SANDBOX_MAP_TELEPORT_TEMPLATE)
            ),
            key=lambda result: result.pixel_score,
            reverse=True,
        )

    def _sandbox_navigation_teleport(
        self,
        frame: np.ndarray,
    ) -> MatchResult | None:
        passed = self._round_map_icons(frame)
        glyphs = [self._teleport_glyph_score(frame, result) for result in passed[:8]]
        best = passed[0].pixel_score if passed else -1.0
        second = passed[1].pixel_score if len(passed) > 1 else -1.0
        self._status(
            "箱庭徒步导航传送阵",
            f"candidates={len(passed)}, pixel best={best:.3f} second={second:.3f}, "
            "glyph="
            + ",".join(f"{glyph:.2f}" for glyph in glyphs[:3]),
        )
        if not passed:
            return None
        # Two real circles on one map (角色卡3 上流社会派对会场 at 4K,
        # 2026-10-04: both 0.957): either one opens the teleport map.
        for result, glyph in zip(passed, glyphs):
            if glyph >= SANDBOX_MAP_TELEPORT_MIN_GLYPH:
                return result
        if best >= SANDBOX_MAP_TELEPORT_MIN_PIXEL:
            self._status("箱庭徒步导航传送阵", "图案被盖住，按边框分数选最高的")
            return passed[0]
        return None

    def _teleport_glyph_score(self, frame: np.ndarray, result: MatchResult) -> float:
        """How well the glyph inside a candidate's round frame matches the
        circle's: zero-mean correlation over the inner disc, best of a few
        pixels' shift (the peak can sit a pixel or two off).  -1 when it
        cannot be measured."""

        try:
            template, _mask = self.vision._load(SANDBOX_MAP_TELEPORT_TEMPLATE)
        except Exception:
            return -1.0
        size = template.shape[0]
        yy, xx = np.mgrid[:size, :size]
        centre = (size - 1) / 2
        inner = np.hypot(xx - centre, yy - centre) < size * SANDBOX_MAP_TELEPORT_GLYPH_RADIUS
        want = template[inner].astype(np.float32)
        want -= want.mean()
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame[..., :3], cv2.COLOR_BGR2GRAY)
        width, height = result.size
        x, y = result.position
        best = -1.0
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                top, left = y + dy, x + dx
                if top < 0 or left < 0:
                    continue
                crop = gray[top : top + height, left : left + width]
                if crop.shape[:2] != (height, width):
                    continue
                got = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
                got = got[inner].astype(np.float32)
                got -= got.mean()
                norm = float(np.sqrt((got * got).sum() * (want * want).sum()))
                if norm > 0:
                    best = max(best, float((got * want).sum()) / norm)
        return best

    def _walk_text(self, frame: np.ndarray) -> str:
        """The field's walk banner area ("自动移动中" / "已完成自动移动", a
        patrol's words), normalized; "" when unreadable."""
        try:
            text = self.vision.ocr_text(frame, "箱庭自动移动", relative_roi=AUTO_MOVE_TEXT_RELATIVE_ROI)
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:
            return ""
        return normalize_text(self.vision.simplify(str(text)))

    def _close_map_left_open_by_walk(self) -> bool:
        """Close the large map when it stays up after the walk was confirmed.

        A player 2026-10-13 (v0.1.31, card 7): after 确认 on the 自动移动
        dialog the map stayed on screen, and the run waited behind it for a
        hand button the map covers.  The map gets a moment to close by
        itself; True when it had to be closed here."""
        for look in range(MAP_SELF_CLOSE_LOOKS):
            if not self._sandbox_navigation_page_has_keyword(self.vision.capture()):
                return False
            if look + 1 < MAP_SELF_CLOSE_LOOKS:
                self.task.sleep(SANDBOX_NAVIGATION_OCR_INTERVAL * 2)
        self._status("导航状态", "确认自动移动后大地图还开着，关掉地图等角色走到")
        self._close_confirmed_map_page(
            {MapPageMode.SANDBOX_LARGE_MAP},
            timeout=SANDBOX_NAVIGATION_CONFIRM_TIMEOUT,
        )
        return True

    @staticmethod
    def _auto_move_question_shown(walk_text: str) -> bool:
        """The 自动移动 dialog's question (「是否自动移动前往所选目的地？」)
        in normalized walk-area text."""
        return any(word in walk_text for word in AUTO_MOVE_QUESTION_KEYWORDS)

    def _cancel_auto_move_dialog(self, frame: np.ndarray | None = None) -> bool:
        """Press 取消 on a 自动移动 dialog left open over the map (YES-BD2
        #24: the run went home with it still up and stopped); True when
        pressed.  Nothing is pressed unless the question itself reads."""
        try:
            if frame is None:
                frame = self.vision.capture()
            boxes = self.vision.ocr_boxes(
                frame, "自动移动确认窗", relative_roi=AUTO_MOVE_TEXT_RELATIVE_ROI
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:
            return False
        texts = [
            (normalize_text(self.vision.simplify(str(getattr(box, "name", "")))), box)
            for box in boxes
        ]
        if not self._auto_move_question_shown("".join(text for text, _box in texts)):
            return False
        for text, box in texts:
            center = self._ocr_box_center(box)
            if text == AUTO_MOVE_CANCEL_TEXT and center is not None:
                self._status("导航状态", "关掉留着的自动移动确认窗（取消）")
                self.vision.click_client(center, frame.shape, after_sleep=0.8)
                return True
        return False

    def _walk_caught(self, text: str) -> bool:
        caught = any(word in text for word in WALK_CAUGHT_KEYWORDS)
        if caught:
            self._status("导航状态", "自动移动被巡逻发现，角色被驱逐回入口")
        return caught

    def _walk_flags(self, frame: np.ndarray) -> tuple[bool, bool]:
        """(walking, caught): "自动移动中" shows / a field patrol's words
        (WALK_CAUGHT_KEYWORDS) show.  Both at once right after an expulsion:
        the toast is still up while the game walks on."""
        text = self._walk_text(frame)
        return "移动中" in text, self._walk_caught(text)

    def _walk_state(self, frame: np.ndarray) -> str:
        """"caught" when a field patrol stopped the walk, "moving" while
        "自动移动中" shows, "arrived" once the game says 「已完成自动移动」,
        else "idle"."""
        text = self._walk_text(frame)
        if self._walk_caught(text):
            return "caught"
        if "移动中" in text:
            return "moving"
        return "arrived" if WALK_ARRIVED_TEXT in text else "idle"

    def _auto_moving(self, frame: np.ndarray) -> bool:
        """"自动移动中" shows: the game is walking the character somewhere."""
        return self._walk_flags(frame)[0]

    def _wait_auto_move_finished(self, timeout: float) -> str:
        """Wait while "自动移动中" shows: "done" once it is gone, "battle" when
        a monster met on the way was run from (the walk is to be made again),
        "timeout" when it never ends.

        Leo 2026-10-27 「被巡邏抓到就繼續 他會走到目的地」「有些被巡邏抓到只是被傳走
        但他會繼續走 有些會進入戰鬥」: a catch is waited out like
        _wait_resuming_walk, never stopped."""
        end_at = monotonic() + max(0.0, timeout)
        idle = 0
        still = StillTimer()
        # An unread banner over a panning field is still the walk (YES-BD2 #62);
        # one change holds the wait, it presses nothing.
        motion = MotionWatch(looks=1)
        while monotonic() <= end_at:
            frame = self.vision.capture()
            state = self._walk_state(frame)
            if state == "caught":
                self._status("导航状态", "被巡逻发现，等游戏自己继续走")
                return self._wait_resuming_walk(RESUMING_WALK_TIMEOUT)
            if state == "arrived":
                # The followers and the camera still settle after it (live
                # 4K 2026-10-27: waited 21 s more on a moving picture).
                return "done"
            if state == "idle" and not self._black_frame(frame):
                # A battle's own animation would read as a moving field.
                met = self._battle_on_the_way(frame)
                if met is not None:
                    return met
            if state == "idle" and motion.moving(frame):
                state = "moving"
            if state == "moving" and still.still_for(frame, monotonic()) >= STUCK_SECONDS:
                # The banner is up but nothing moves: the walk stopped.
                self._status(
                    "导航状态", f"自动移动中但画面 {STUCK_SECONDS:.0f} 秒没动，当作卡住"
                )
                return "timeout"
            if state == "idle":
                idle += 1
                if idle >= AUTO_MOVE_IDLE_READS:
                    return "done"
            else:
                idle = 0
                self._status("导航状态", "自动移动中，等待走到传送阵")
            self.task.sleep(0.5)
        return "timeout"

    def _battle_on_the_way(self, frame: np.ndarray) -> str | None:
        """A field battle met while walking (off the field): "battle" once it
        was left, "timeout" when it could not be, None when there is none."""
        if self.classify(frame) == ScreenState.SANDBOX:
            return None
        if self._leave_battle_result(frame):
            return "battle"
        leave = getattr(self.task, "leave_field_battle", None)
        if not callable(leave):
            return None
        left = leave("跑图路上")
        if left == "left":
            return "battle"
        if left == "none":
            return None
        self._status("导航状态", f"路上撞到怪进了战斗，{left}")
        return "timeout"

    def _wait_resuming_walk(self, timeout: float) -> str:
        """Wait until a walk has ended, patrol catches included: after a catch
        the game reloads the map and walks on by itself (Leo 2026-10-03:
        "放著總會過的"), so nothing is pressed.  Ends once the character
        stands still with no banner, loading screen or patrol words up:
        "done", or "battle" when a battle was run from on the way and no walk
        went on after it (the walk is to be made again), "timeout" else."""

        end_at = monotonic() + max(0.0, timeout)
        idle = 0
        fled = False
        still = StillTimer()
        motion = MotionWatch(looks=1)
        while monotonic() <= end_at:
            frame = self.vision.capture()
            panning = motion.moving(frame)
            if still.still_for(frame, monotonic()) >= STUCK_SECONDS:
                self._status(
                    "导航状态", f"画面 {STUCK_SECONDS:.0f} 秒没动，不再等自动移动，继续确认地图"
                )
                return "battle" if fled else "timeout"
            if self._black_frame(frame):
                idle = 0
                self._status("导航状态", "加载中，等待自动移动继续")
            else:
                walking, caught = self._walk_flags(frame)
                if walking or caught:
                    idle = 0
                    # A walk going on after the battle needs no new walk.
                    fled = fled and not walking
                    if caught:
                        self._status("导航状态", "被巡逻发现，等游戏自己继续走")
                elif panning:
                    # The banner unread while the field pans (YES-BD2 #62).
                    idle = 0
                elif self.classify(frame) == ScreenState.SANDBOX:
                    idle += 1
                    if idle >= AUTO_MOVE_IDLE_READS:
                        return "battle" if fled else "done"
                else:
                    # A loading screen with art (not black), a dialog, or
                    # a field battle met on the way (Memory Edge, live 4K
                    # 2026-10-09: VICTORY, 离开, then the walk goes on).
                    idle = 0
                    if self._leave_battle_result(frame):
                        fled = True
                    else:
                        # A battle still being fought: run away (Leo
                        # 2026-10-22, BaseBD2Task.leave_field_battle).
                        leave = getattr(self.task, "leave_field_battle", None)
                        if callable(leave) and leave("跑图路上") == "left":
                            fled = True
            self.task.sleep(0.5)
        self._status("导航状态", f"自动移动{timeout:.0f}秒仍未结束，继续确认地图")
        return "timeout"

    def _leave_battle_result(self, frame: np.ndarray) -> bool:
        """Press 离开 when a field battle's result shows; True when pressed."""

        try:
            boxes = self.vision.ocr_boxes(
                frame, "战斗结算按钮", relative_roi=BATTLE_RESULT_BUTTONS_RELATIVE_ROI
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:
            return False
        for box in boxes:
            text = normalize_text(self.vision.simplify(str(getattr(box, "name", ""))))
            center = self._ocr_box_center(box)
            if BATTLE_RESULT_LEAVE_TEXT in text and center is not None:
                self._status("导航状态", "路上遇到战斗，结算后按离开")
                self.vision.click_client(center, frame.shape, after_sleep=1.0)
                return True
        return False

    def _cancel_walk(self) -> bool:
        """Press the ✕ under "自动移动中" while the banner shows; True when a
        walk was stopped."""

        stopped = False
        for _attempt in range(AUTO_MOVE_CANCEL_ATTEMPTS):
            frame = self.vision.capture()
            if not self._walk_flags(frame)[0]:
                break
            self._status("导航状态", "取消自动移动")
            height, width = frame.shape[:2]
            x, y = AUTO_MOVE_CANCEL_REFERENCE_POINT
            self.vision.click_client(
                (round(x * width / 1920), round(y * height / 1080)),
                frame.shape,
                after_sleep=0.8,
            )
            stopped = True
        return stopped

    def _click_sandbox_navigation_menu_teleport(self, frame: np.ndarray) -> bool:
        """Select a stacked navigation-map teleport submenu by OCR center."""

        center = self._sandbox_navigation_menu_teleport_option(frame)
        if center is None:
            return False
        self.vision.click_client(
            center,
            frame.shape,
            after_sleep=SANDBOX_NAVIGATION_OCR_INTERVAL,
        )
        self._status("箱庭徒步导航传送阵菜单", f"点击魔法阵中心={center}")
        return True

    def _sandbox_navigation_menu_teleport_option(
        self, frame: np.ndarray
    ) -> tuple[int, int] | None:
        """The centre of the stacked menu's 魔法阵 row, or None."""
        try:
            boxes = self.vision.ocr_boxes(frame, "箱庭徒步导航传送阵菜单")
        except Exception as exc:
            self._status("箱庭徒步导航传送阵菜单 OCR错误", str(exc))
            return None
        for box in boxes:
            label = normalize_text(
                self.vision.simplify(str(getattr(box, "name", "")))
            )
            # "自动移动中：魔法阵" is the walk already under way (live 2K
            # 2026-09-29: clicked 4 times as if it were the menu entry).
            if "魔法阵" not in label or "自动移动" in label:
                continue
            center = self._ocr_box_center(box)
            if center is not None:
                return center
        return None

    def _click_sandbox_navigation_destination_confirmation(
        self,
        frame: np.ndarray,
    ) -> bool:
        """Confirm the selected navigation destination when its OCR button
        appears; True only once the button went away or the walk began."""

        try:
            button = self._sandbox_navigation_destination_button(frame)
        except Exception as exc:
            self._status("箱庭徒步导航传送阵确认 OCR错误", str(exc))
            return False
        if button is None:
            return False
        label, center = button
        near = max(8, round(frame.shape[0] * 0.01))

        def look() -> str:
            """"walk", "gone", "same" (this button still up) or "unknown"."""
            shown = self.vision.capture()
            if any(self._walk_flags(shown)):
                return "walk"
            try:
                again = self._sandbox_navigation_destination_button(shown)
            except (TaskDisabledException, FinishedException):
                raise
            except Exception:
                return "unknown"
            if again is None:
                return "gone"
            same = (
                again[0] == label
                and abs(again[1][0] - center[0]) <= near
                and abs(again[1][1] - center[1]) <= near
            )
            return "same" if same else "unknown"

        self._status("箱庭徒步导航传送阵确认", f"点击{label}中心={center}")
        # A lost press left the dialog up while the caller waited for a walk
        # that never came; it is pressed again only while the same button
        # is still there.
        return bool(
            press_and_confirm(
                f"导航目的地{label}",
                lambda: self.vision.click_client(
                    center,
                    frame.shape,
                    after_sleep=SANDBOX_NAVIGATION_OCR_INTERVAL,
                ),
                lambda: look() in ("walk", "gone"),
                still_before=lambda: look() == "same",
                sleep=self.task.sleep,
                log=self.task.log_info,
            )
        )

    def _sandbox_navigation_destination_button(
        self,
        frame: np.ndarray,
    ) -> tuple[str, tuple[int, int]] | None:
        """(label, center) of the destination dialog's 确认/生成 button."""

        for box in self.vision.ocr_boxes(frame, "箱庭徒步导航传送阵确认"):
            label = normalize_text(
                self.vision.simplify(str(getattr(box, "name", "")))
            )
            if "生成魔法阵" in label:
                continue
            if not (
                label == "确认"
                or label.startswith("确认")
                or label == "生成"
                or label.startswith("生成")
            ):
                continue
            center = self._ocr_box_center(box)
            if center is None:
                continue
            return label, center
        return None

    def _walk_to_sandbox_teleport_interaction(self, redo: bool = True) -> NavigationResult:
        """Use the sandbox navigation map to walk back to a portal interaction
        prompt; a battle met on the way is run from and the walk made once
        more (``redo``)."""

        self._status("导航状态", "改用导航/徒步前往传送阵")
        # The minimap itself opens the area map (as M does).  The icon
        # templates matched beside the ≡ button in 阿尔卡迪亚居住区域 and opened
        # the navigation menu instead (live 2K 2026-09-30).
        if self._open_field_map() is None and not self._click_sandbox_navigation_map():
            return NavigationResult(
                False,
                ScreenState.SANDBOX,
                "未识别到左上导航地图入口，无法转入徒步回退",
            )

        end_at = monotonic() + SANDBOX_NAVIGATION_MAP_TIMEOUT
        teleport = None
        teleport_frame = None
        ever_confirmed = False
        while monotonic() <= end_at:
            frame = self.vision.capture()
            page_confirmed = self._sandbox_navigation_page_has_keyword(frame)
            ever_confirmed = ever_confirmed or page_confirmed
            teleport = self._sandbox_navigation_teleport(frame) if page_confirmed else None
            if page_confirmed and teleport is not None:
                teleport_frame = frame
                break
            self.task.sleep(SANDBOX_NAVIGATION_OCR_INTERVAL)
        destination_confirmed = caught_early = False
        if teleport is None:
            # The circle drawn under another icon (第16章 迪尔索特港口城市: the
            # inn's icon covers it, player report 2026-10-29): pressing that
            # icon lists 「魔法阵 / 旅馆」.
            under = self._circle_under_other_icon(frame) if ever_confirmed else None
            if under is None:
                # Why, in the player's words (Leo 2026-10-24 「錯誤要寫原因 不要寫讀不到」).
                why = (
                    "区域地图上找不到传送阵图标（这张地图可能没有已开启的传送阵，"
                    "或被别的图示盖住）"
                    if ever_confirmed
                    else "点小地图后没看到区域地图（地图没打开，或标题和底栏都没对上）"
                )
                self._close_confirmed_map_page(
                    {MapPageMode.SANDBOX_LARGE_MAP},
                    timeout=SANDBOX_NAVIGATION_CONFIRM_TIMEOUT,
                )
                self._close_field_map_if_open()
                return NavigationResult(
                    False,
                    ScreenState.SANDBOX_MAP,
                    why,
                    map_page_mode=MapPageMode.SANDBOX_LARGE_MAP,
                )
            destination_confirmed, caught_early = under
        for press in range(1, TELEPORT_ICON_PRESSES + 1):
            if teleport is None:
                break
            self.vision.click_client(
                teleport.center,
                teleport_frame.shape,
                after_sleep=SANDBOX_NAVIGATION_TELEPORT_SETTLE_SECONDS,
            )
            destination_confirmed, caught_early = self._follow_teleport_icon_press()
            if destination_confirmed or press == TELEPORT_ICON_PRESSES:
                break
            # Nothing the press opens showed (remedy 3,
            # docs/dev-notes/bug-prevention.md): the circle once more, only
            # while the map still shows it and nothing else.
            teleport_frame = self.vision.capture()
            teleport = self._circle_press_left_nothing(teleport_frame)
            if teleport is None:
                break
            self._status("导航状态", "点了区域地图上的传送阵没反应，再点一次")
            self.task.log_info("跑图：点了区域地图上的传送阵没反应，再点一次。")
        if not destination_confirmed:
            frame = self.vision.capture()
            if self._sandbox_navigation_page_has_keyword(frame):
                self._close_confirmed_map_page(
                    {MapPageMode.SANDBOX_LARGE_MAP},
                    timeout=SANDBOX_NAVIGATION_CONFIRM_TIMEOUT,
                )
            self._close_field_map_if_open()
            return NavigationResult(
                False,
                ScreenState.UNKNOWN,
                "箱庭大地图选择传送阵后未确认目的地按钮，已停止等待交互",
            )

        self._status(
            "导航状态",
            "已选择导航地图传送阵，等待自动移动后重新识别交互按钮",
        )
        self._close_map_left_open_by_walk()
        # The hand prompt shows while the walk is still finishing; pressing
        # it then keeps the walk alive across the teleport and drags the
        # character back through the floors (live 2K 2026-09-29).
        walked = (
            self._wait_resuming_walk(RESUMING_WALK_TIMEOUT)
            if caught_early
            else self._wait_auto_move_finished(SANDBOX_NAVIGATION_WALK_TIMEOUT)
        )
        if walked == "battle":
            if redo:
                self._status("导航状态", "走向传送阵时撞到怪，逃跑后重新走一次")
                return self._walk_to_sandbox_teleport_interaction(redo=False)
            return NavigationResult(
                False,
                ScreenState.SANDBOX,
                "走向传送阵时两次撞到怪进了战斗，都已逃跑，没走到传送阵",
            )
        if not self._click_sandbox_teleport_interaction(timeout=self._loading_timeout()):
            if walked == "done" and self._press_interact_key_on_circle():
                # The walk ended on the circle: its hand may just not read
                # (player 1080p 125% 2026-10-17 at the hunting ground's).
                return self._open_circle_page(f"走到传送阵后快捷键{INTERACT_KEY}")
            # A walk still going (resumed after an unseen catch) would fight
            # the caller's next step (the ≡ menu).
            self._cancel_walk()
            return NavigationResult(
                False,
                ScreenState.SANDBOX,
                "徒步回退后仍未识别到传送阵交互按钮",
            )
        return self._open_circle_page("徒步回退交互")

    def _follow_teleport_icon_press(self) -> tuple[bool, bool]:
        """After the circle on the area map was pressed: its 魔法阵 menu, its
        确认, or the 自动移动 question, until the walk is confirmed.
        (confirmed, caught before the banner was read)."""
        menu_end_at = monotonic() + SANDBOX_NAVIGATION_CONFIRM_TIMEOUT
        while monotonic() <= menu_end_at:
            menu_frame = self.vision.capture()
            walk_text = self._walk_text(menu_frame)
            if self._walk_caught(walk_text):
                # Caught before the banner was ever read (live 2K: "被发现了！！"
                # 3 s after the click): the walk itself was under way.
                return True, True
            if self._auto_move_question_shown(walk_text):
                # 「是否自动移动前往所选目的地？」 (YES-BD2 #24): its title
                # 自动移动 is not the walk banner; its 确认 starts the walk.
                if self._click_sandbox_navigation_destination_confirmation(menu_frame):
                    return True, False
                self.task.sleep(SANDBOX_NAVIGATION_OCR_INTERVAL)
                continue
            if "自动移动" in walk_text:
                # One click on the map icon already started the walk: no
                # menu and no confirm button follow.
                return True, False
            if self._click_sandbox_navigation_menu_teleport(menu_frame):
                self.task.sleep(SANDBOX_NAVIGATION_OCR_INTERVAL)
                continue
            if self._click_sandbox_navigation_destination_confirmation(menu_frame):
                return True, False
            self.task.sleep(SANDBOX_NAVIGATION_OCR_INTERVAL)
        return False, False

    def _circle_under_other_icon(self, frame: np.ndarray) -> tuple[bool, bool] | None:
        """On a map whose circle the game draws under another icon
        (COVERED_CIRCLE_ICONS), press that icon, found by its label: a menu
        listing 「魔法阵」 is followed as a circle press, and a walk that
        starts at once (the character is near: Leo 2026-10-30 「距離近的時候
        他就是會用走的」) is kept while its banner names 魔法阵 or that icon.
        Any other walk is stopped at once.  No other icon is ever pressed
        (Leo 「你有可能會點到戰鬥區域」).  None when nothing came of it.

        第16章 迪尔索特港口城市: the inn hides the circle; its frame scored
        0.839 and glyph 0.30 (Leo's 2K frame 2026-10-30), and pressing the
        inn lists 「魔法阵 / 旅馆」 (Leo: 「點擊後可以選擇」)."""
        header = self._area_map_title(frame)
        label = next(
            (cover for title, cover in COVERED_CIRCLE_ICONS.items() if title in header),
            None,
        )
        if label is None:
            return None
        icon = self._icon_under_label(frame, label)
        if icon is None:
            self._status("导航状态", f"地图上没读到「{label}」，不点别的图示")
            return None
        self._status("导航状态", f"传送阵被「{label}」盖住，点它的图示")
        self.task.log_info(f"跑图：区域地图上的传送阵被「{label}」的图示盖住，点那个图示。")
        self.vision.click_client(
            icon.center,
            frame.shape,
            after_sleep=SANDBOX_NAVIGATION_OCR_INTERVAL,
        )
        outcome = wait_for(
            lambda: self._icon_press_outcome(label),
            SANDBOX_NAVIGATION_CONFIRM_TIMEOUT,
            sleep=self.task.sleep,
            poll=SANDBOX_NAVIGATION_OCR_INTERVAL,
        )
        if outcome == "menu":
            return self._follow_teleport_icon_press()
        if outcome == "walk":
            return True, False
        self._undo_map_icon_press()
        return None

    def _area_map_title(self, frame: np.ndarray) -> str:
        """The area map's title in ``frame``, normalized; "" when unread."""
        try:
            text = self.vision.ocr_text(
                frame, "区域地图标题", relative_roi=TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:
            return ""
        return normalize_text(self.vision.simplify(str(text)))

    def _icon_under_label(self, frame: np.ndarray, label: str) -> MatchResult | None:
        """The round icon nearest the map label ``label`` (read by OCR), within
        an icon's width of it; None when the label or an icon is not seen."""
        centre = None
        for scale in (1.0, 2.0):
            # Small words: read again at 2× (the remedy ladder's first step).
            try:
                boxes = self.vision.ocr_boxes(
                    frame,
                    "区域地图图示名",
                    relative_roi=AREA_MAP_LABELS_RELATIVE_ROI,
                    ocr_scale=scale,
                )
            except (TaskDisabledException, FinishedException):
                raise
            except Exception:
                return None
            centre = next(
                (
                    self._ocr_box_center(box)
                    for box in boxes
                    if self._reads_as_label(
                        normalize_text(self.vision.simplify(str(getattr(box, "name", "")))), label
                    )
                ),
                None,
            )
            if centre is not None:
                break
        if centre is None:
            return None
        reach = frame.shape[0] * SANDBOX_MAP_LABEL_ICON_REACH
        icons = [
            icon
            for icon in self._round_map_icons(frame)
            if not self._battle_exit_icon(frame, icon)
            and abs(icon.center[0] - centre[0]) <= reach
            and abs(icon.center[1] - centre[1]) <= reach
        ]
        return min(
            icons,
            key=lambda icon: (icon.center[0] - centre[0]) ** 2 + (icon.center[1] - centre[1]) ** 2,
            default=None,
        )

    def _icon_press_outcome(self, label: str) -> str | None:
        """After pressing the icon over the circle: "menu" when a menu lists
        魔法阵, "walk" when a walk began toward 魔法阵 or that icon (or its
        banner names no place), "other" at once for a walk anywhere else or
        the 自动移动 question, None while nothing showed yet."""
        frame = self.vision.capture()
        if self._sandbox_navigation_menu_teleport_option(frame) is not None:
            return "menu"
        walk_text = self._walk_text(frame)
        if self._auto_move_question_shown(walk_text):
            return "other"
        if "移动中" not in walk_text:
            # 「已中止自动移动」 and the like are no walk.
            return None
        place = walk_text.split("移动中", 1)[1].lstrip(":：")
        if not place or "魔法阵" in place or place in label or label in place:
            return "walk"
        self._status("导航状态", f"点图示后走向「{place}」，不是传送阵，马上停下")
        return "other"

    @staticmethod
    def _reads_as_label(text: str, label: str) -> bool:
        """``text`` is ``label`` read whole, or with at most its first or last
        character cut off (「迪尔索特旅」 at 1080p); 「迪尔索特」 alone, shared
        by every label on that map, is not."""
        if not text:
            return False
        if label in text:
            return True
        return len(text) >= len(label) - 1 and text in label

    @staticmethod
    def _battle_exit_icon(frame: np.ndarray, icon: MatchResult) -> bool:
        """The icon holds red crossed swords: a battle area's exit.  Its
        box is ~25 % strong red (迪尔索特黑市, 加尔顿山后段), the inn,
        tavern, NPC and circle icons 0 % (2026-10-30 frames)."""
        x, y = icon.position
        width, height = icon.size
        crop = frame[max(0, y) : y + height, max(0, x) : x + width]
        if crop.size == 0 or crop.ndim != 3:
            return False
        hsv = cv2.cvtColor(crop[..., :3], cv2.COLOR_BGR2HSV)
        red = ((hsv[..., 0] < 10) | (hsv[..., 0] > 170)) & (hsv[..., 1] > 120) & (hsv[..., 2] > 90)
        return float(red.mean()) >= SANDBOX_MAP_BATTLE_EXIT_MIN_RED

    def _undo_map_icon_press(self) -> np.ndarray | None:
        """After pressing an icon that was not the circle: cancel the
        自动移动 question or a walk it started, then close the area map and
        open it again (closes any icon menu too).  The reopened map's frame,
        or None when it did not open."""
        self._cancel_auto_move_dialog()
        self._cancel_walk()
        self._close_field_map_if_open()
        if self._open_field_map() is None:
            return None
        frame = self.vision.capture()
        return frame if self._sandbox_navigation_page_has_keyword(frame) else None

    def _circle_press_left_nothing(self, frame: np.ndarray) -> MatchResult | None:
        """The circle to press again: the area map still shows it, and none of
        what its press opens (the 魔法阵 menu, 确认, the 自动移动 question).
        None once anything else shows; a press could land on it."""
        if not self._sandbox_navigation_page_has_keyword(frame):
            return None
        if self._sandbox_navigation_destination_button(frame) is not None:
            return None
        if self._auto_move_question_shown(self._walk_text(frame)):
            return None
        if self._sandbox_navigation_menu_teleport_option(frame) is not None:
            return None
        return self._sandbox_navigation_teleport(frame)

    def _press_interact_key_on_circle(self) -> bool:
        """The game's interact key F, sent only on a confirmed field (on 主页
        it opens the recent cartridge).  True when it was sent."""
        tap_key = getattr(self.task, "tap_key", None)
        if not callable(tap_key) or not self._field_keycaps_shown():
            return False
        self._status("导航状态", f"走到传送阵后没认出交互手势，改按快捷键 {INTERACT_KEY}")
        self.task.log_info(f"跑图：走到传送阵后没认出交互手势，改按快捷键 {INTERACT_KEY}。")
        return bool(tap_key(INTERACT_KEY, after_sleep=TELEPORT_INTERACTION_CLICK_DELAY))

    def open_teleport_map_from_sandbox(self) -> NavigationResult:
        """Open the teleport map through the circle's 交互 button."""

        self._status("导航状态", "优先识别箱庭传送阵交互按钮")
        if self._click_sandbox_teleport_interaction():
            opened = self._open_circle_page("传送阵交互按钮")
            if opened.success:
                return opened
            return NavigationResult(
                False,
                opened.state,
                f"点击传送阵交互按钮后未确认传送阵地图：{opened.message}",
                map_page_mode=opened.map_page_mode,
            )

        # The portal skill is never pressed (Leo 2026-10-10: 「我是說技能 不要
        # 傳送陣」): only the 交互 button opens the map here; callers walk to
        # a circle on the area map or go through the ≡ menu.
        return NavigationResult(False, ScreenState.SANDBOX, NOT_BY_CIRCLE_MESSAGE)

    def _open_teleport_map_at_hunting_ground(
        self, card: CardSpec | None = None
    ) -> NavigationResult:
        """The teleport map right after the ≡ menu's 狩猎场 trip.  The trip
        always lands on the hunting ground's circle, so its hand is there
        even when it is not read (player 1080p 125% 2026-10-17, 第10章 回主城
        failed here); then the game's interact key F (Leo 「傳到狩獵場一定會有
        手勢可以按 沒辨識到就按f」).  The field is confirmed, so F is never
        sent on 主页 (where it opens the recent cartridge)."""
        opened = self.open_teleport_map_from_sandbox()
        if opened.success or opened.message != NOT_BY_CIRCLE_MESSAGE:
            return opened
        if getattr(self, "_already_in_hunting_ground", False):
            # No trip was made: the character stands anywhere in the ground,
            # so walk to its circle on the area map first.
            walked = self._walk_to_sandbox_teleport_interaction()
            if walked.success:
                return walked
            self._status("导航状态", f"走去狩猎场传送阵没成功（{walked.message}），改按 {INTERACT_KEY}")
        tap_key = getattr(self.task, "tap_key", None)
        if tap_key is None:
            return opened
        self._status("导航状态", f"狩猎场没认出交互手势，改按快捷键 {INTERACT_KEY}")
        self.task.log_info(f"跑图：狩猎场没认出传送阵交互手势，改按快捷键 {INTERACT_KEY}。")
        if not tap_key(INTERACT_KEY, after_sleep=TELEPORT_INTERACTION_CLICK_DELAY):
            return NavigationResult(
                False,
                ScreenState.SANDBOX,
                f"狩猎场没认出交互手势，快捷键 {INTERACT_KEY} 没能发送（游戏窗口不在最前面）",
            )
        pressed = self._wait_for_sandbox_map_open(
            f"快捷键{INTERACT_KEY}",
            expected_mode=MapPageMode.DIRECT_TELEPORT,
            detect_skill_failure=False,
        )
        if pressed.success:
            return pressed
        if getattr(self, "_already_in_hunting_ground", False):
            # 第10章 伯爵家宝库 (live clone 2026-10-23): circle and exit icons
            # overlap, and beside the circle the area map does not start a
            # walk.  Leo chose to skip the card and say what to do.
            message = (
                HUNTING_GROUND_MUST_STAND_ON_CIRCLE.get(card.card_id)
                if card is not None
                else None
            ) or (
                f"人在狩猎场里，点地图没能走到传送阵，按 {INTERACT_KEY} 也没打开传送阵地图"
                "（请先让角色站到狩猎场的传送阵上再跑）"
            )
            return NavigationResult(
                False, pressed.state, message, map_page_mode=pressed.map_page_mode
            )
        return NavigationResult(
            False,
            pressed.state,
            f"狩猎场没认出交互手势，按 {INTERACT_KEY} 后也没打开传送阵地图：{pressed.message}",
            map_page_mode=pressed.map_page_mode,
        )

    def _teleport_generation_boxes(
        self,
        frame: np.ndarray,
    ) -> tuple[tuple[int, int] | None, frozenset[str], str]:
        boxes = self.vision.ocr_boxes(frame, "传送阵生成确认")
        generate_centers: list[tuple[int, int]] = []
        matched: set[str] = set()
        labels = []
        for box in boxes:
            label = normalize_text(self.vision.simplify(str(getattr(box, "name", ""))))
            if not label:
                continue
            labels.append(label)
            center = self._ocr_box_center(box)
            if "生成魔法阵" in label:
                matched.add("生成魔法阵")
            if "取消" in label:
                matched.add("取消")
            if label == "生成" or (label.startswith("生成") and "魔法阵" not in label):
                matched.add("生成")
                if center is not None:
                    generate_centers.append(center)
        return (
            generate_centers[0] if len(matched) == 3 and len(generate_centers) == 1 else None,
            frozenset(matched),
            "|".join(labels),
        )

    def _click_teleport_generation(
        self,
        teleport: MatchResult,
        frame_shape: tuple[int, ...],
        timeout: float = TELEPORT_GENERATION_OCR_TIMEOUT,
    ) -> bool:
        """Select one white map teleport and confirm its three-keyword dialog."""

        self.vision.click_client(
            teleport.center,
            frame_shape,
            after_sleep=AREA_MAP_CLICK_SETTLE_SECONDS,
        )
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        while monotonic() <= end_at:
            frame = self.vision.capture()
            try:
                generate_center, matched_keywords, last_text = self._teleport_generation_boxes(
                    frame
                )
            except Exception as exc:
                self._status("传送阵生成弹窗 OCR错误", str(exc))
                return False
            self._status(
                "传送阵生成弹窗",
                f"matched={len(matched_keywords)}/3, text={last_text or '-'}",
            )
            if generate_center is not None:
                self.vision.click_client(
                    generate_center,
                    frame.shape,
                    after_sleep=TELEPORT_MAP_TRAVEL_SETTLE_SECONDS,
                )
                return True
            self.task.sleep(TELEPORT_GENERATION_OCR_INTERVAL)
        self._status(
            "传送阵生成弹窗",
            f"超时未同时命中三关键词，OCR={last_text or '-'}",
        )
        return False

    def _click_teleport_map_destination(
        self,
        teleport: MatchResult,
        frame_shape: tuple[int, ...],
        *,
        page_mode: MapPageMode,
    ) -> bool:
        """Click a teleport-map destination using the correct entry semantics."""

        self.last_loading_title = ""  # only the coming loading screen counts
        self._teleport_loading_seen = False

        if page_mode == MapPageMode.GENERATE_TELEPORT:
            return self._click_teleport_generation(teleport, frame_shape)
        if page_mode != MapPageMode.DIRECT_TELEPORT:
            self._status("传送阵地图传送阵", f"拒绝未知页面模式={page_mode.value}")
            return False
        self.vision.click_client(teleport.center, frame_shape, after_sleep=0.0)
        self._teleport_loading_seen = self._wait_for_loading_screen(
            TELEPORT_MAP_TRAVEL_SETTLE_SECONDS
        )
        self._status(
            "传送阵地图传送阵",
            f"交互入口直接点击中心={teleport.center}，等待传送完成",
        )
        return True

    @staticmethod
    def _black_frame(frame) -> bool:
        try:
            if not frame.any():
                return False  # a blank test frame, not the game
            return float(np.percentile(frame[..., :3], 95)) < TELEPORT_LOADING_DARK_P95
        except (AttributeError, TypeError, IndexError, ValueError):
            return False

    def _wait_for_loading_screen(self, timeout: float) -> bool:
        """Until the black loading screen shows (at most ``timeout``): the
        field must not be read before the teleport has started.  A fixed
        1.5 s wait before (live 2K 2026-10-01: loading began ~0.5 s in)."""
        end_at = monotonic() + max(0.0, timeout)
        while monotonic() < end_at:
            try:
                frame = self.vision.capture()
            except (TaskDisabledException, FinishedException):
                raise
            except Exception:
                return False
            if self._black_frame(frame):
                return True
            self.task.sleep(0.1)
        return False

    @staticmethod
    def _screen_state_for_map_page_mode(mode: MapPageMode) -> ScreenState:
        if mode.is_teleport_map:
            return ScreenState.AREA_MAP
        if mode == MapPageMode.SANDBOX_LARGE_MAP:
            return ScreenState.SANDBOX_MAP
        return ScreenState.UNKNOWN

    def _close_confirmed_map_page(
        self,
        expected_modes: set[MapPageMode],
        *,
        card_number: int | None = None,
        timeout: float | None = 8.0,
    ) -> NavigationResult:
        """Close one strictly identified map page, then re-confirm the sandbox."""

        frame = self.vision.capture()
        if self._cancel_auto_move_dialog(frame):
            frame = self.vision.capture()
        detection = self._detect_map_page_mode(frame)
        if detection.mode not in expected_modes:
            expected = ",".join(sorted(mode.value for mode in expected_modes))
            return NavigationResult(
                False,
                self._screen_state_for_map_page_mode(detection.mode),
                (
                    "关闭前地图页面身份不符，未执行点击："
                    f"expected={expected}, observed={detection.mode.value}"
                ),
                map_page_mode=detection.mode,
            )

        back = self.vision.match(frame, AREA_MAP_BACK_TEMPLATE)
        if self.vision.passes(back, AREA_MAP_BACK_TEMPLATE):
            self._status(
                "地图页面返回按钮",
                (
                    f"mode={detection.mode.value}; center={back.center}; "
                    f"match={back.score:.3f}, pixel={back.pixel_score:.3f}, "
                    f"zncc={back.zncc_score:.3f}"
                ),
            )
            self.vision.click_client(
                back.center,
                frame.shape,
                after_sleep=SANDBOX_MAP_SETTLE_SECONDS,
            )
        else:
            if detection.mode == MapPageMode.SANDBOX_LARGE_MAP:
                reference = SANDBOX_LARGE_MAP_RETURN_REFERENCE_POINT
                relative = SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT
            else:
                reference = TELEPORT_MAP_RETURN_REFERENCE_POINT
                relative = TELEPORT_MAP_RETURN_RELATIVE_POINT
            self._status(
                "地图页面返回按钮",
                (
                    f"mode={detection.mode.value}; 模板未通过，仅在严格身份确认后使用"
                    f"标定点({reference[0]},{reference[1]})"
                ),
            )
            self.task.operate_click(
                *relative,
                after_sleep=SANDBOX_MAP_SETTLE_SECONDS,
            )

        if card_number is None:
            confirmed = self._wait_for_current_sandbox(timeout=float(timeout or 8.0))
        elif timeout is None:
            confirmed = self._wait_for_story_sandbox(int(card_number))
        else:
            confirmed = self._wait_for_story_sandbox(int(card_number), timeout=timeout)
        if confirmed.success:
            return NavigationResult(True, ScreenState.SANDBOX, "地图页面已关闭并稳定确认箱庭")
        return NavigationResult(
            False,
            confirmed.state,
            f"关闭地图页面后未确认箱庭：{confirmed.message}",
            map_page_mode=detection.mode,
        )

    def return_teleport_map_to_sandbox(self, card_number: int) -> NavigationResult:
        """Close a confirmed teleport page and re-confirm the requested story sandbox."""

        self._status("导航状态", "从传送阵地图返回卡带箱庭")
        return self._close_confirmed_map_page(
            {
                MapPageMode.DIRECT_TELEPORT,
                MapPageMode.GENERATE_TELEPORT,
            },
            card_number=int(card_number),
            timeout=None,
        )

    def ensure_area_map(self) -> NavigationResult:
        frame = self.vision.capture()
        detection = self._detect_map_page_mode(frame)
        if detection.mode.is_teleport_map:
            return NavigationResult(
                True,
                ScreenState.AREA_MAP,
                "当前传送阵地图已按视觉模式确认",
                map_page_mode=detection.mode,
            )
        state = self.classify(frame)
        if state != ScreenState.SANDBOX:
            return NavigationResult(False, state, "不在箱庭，无法打开传送地图")
        opened = self.open_teleport_map_from_sandbox()
        if not opened.success:
            return opened
        if opened.state == ScreenState.AREA_MAP and opened.map_page_mode.is_teleport_map:
            return opened
        return NavigationResult(False, opened.state, "打开后未得到严格传送地图视觉模式")

    def _optional_match(self, frame: np.ndarray, spec: TemplateSpec) -> MatchResult | None:
        result = self.vision.match(frame, spec)
        return result if self.vision.passes(result, spec) else None

    @staticmethod
    def _area_map_teleport_bright_neutral_ratio(
        frame: np.ndarray,
        result: MatchResult,
    ) -> float:
        left, top = result.position
        width, height = result.size
        right = left + width
        bottom = top + height
        if (
            width <= 0
            or height <= 0
            or left < 0
            or top < 0
            or right > frame.shape[1]
            or bottom > frame.shape[0]
        ):
            return 0.0
        crop = frame[top:bottom, left:right]
        if crop.ndim == 2:
            color = np.repeat(crop[:, :, None], 3, axis=2)
        else:
            color = crop[:, :, :3]
        pixels = color.astype(np.int16)
        channel_min = np.min(pixels, axis=2)
        channel_spread = np.max(pixels, axis=2) - channel_min
        center_x = (width - 1) / 2
        center_y = (height - 1) / 2
        radius = min(width, height) * AREA_MAP_TELEPORT_BRIGHT_RADIUS_RATIO
        y, x = np.ogrid[:height, :width]
        circle = (x - center_x) ** 2 + (y - center_y) ** 2 < radius**2
        if not np.any(circle):
            return 0.0
        bright_neutral = (channel_min >= AREA_MAP_TELEPORT_BRIGHT_MINIMUM_GRAY) & (
            channel_spread <= AREA_MAP_TELEPORT_BRIGHT_MAXIMUM_SPREAD
        )
        return float(np.mean(bright_neutral[circle]))

    def _map_teleports(
        self,
        frame: np.ndarray,
        templates: tuple[TemplateSpec, ...],
        *,
        status_name: str,
    ) -> tuple[MatchResult, ...]:
        height, width = frame.shape[:2]
        cluster_radius = max(
            6,
            round(
                AREA_MAP_TELEPORT_CLUSTER_RADIUS
                * min(width / FHD_1080.width, height / FHD_1080.height)
            ),
        )
        candidates: list[MatchResult] = []
        for spec in templates:
            for result in self.vision.match_all(
                frame,
                spec,
                minimum_score=self.vision.threshold_for(spec),
                peak_radius=cluster_radius,
            ):
                bright_ratio = self._area_map_teleport_bright_neutral_ratio(
                    frame,
                    result,
                )
                accepted = (
                    self.vision.passes(result, spec)
                    and bright_ratio >= AREA_MAP_TELEPORT_BRIGHT_NEUTRAL_RATIO
                )
                self._status(
                    status_name,
                    (
                        f"center={result.center}, match={result.score:.3f}, "
                        f"pixel={result.pixel_score:.3f}, "
                        f"zncc={result.zncc_score:.3f}, "
                        f"bright={bright_ratio:.3f}, "
                        f"accepted={accepted}"
                    ),
                )
                if accepted:
                    candidates.append(result)
        independent: list[MatchResult] = []
        for candidate in sorted(candidates, key=lambda value: value.score, reverse=True):
            if any(
                (candidate.center[0] - kept.center[0]) ** 2
                + (candidate.center[1] - kept.center[1]) ** 2
                <= cluster_radius**2
                for kept in independent
            ):
                continue
            independent.append(candidate)
        return tuple(sorted(independent, key=lambda value: value.center))

    def _teleport_map_teleports(self, frame: np.ndarray) -> tuple[MatchResult, ...]:
        return self._map_teleports(
            frame,
            TELEPORT_MAP_TELEPORT_CIRCLE_TEMPLATES,
            status_name="传送阵地图传送阵候选",
        )

    @staticmethod
    def _select_map_teleport(teleports: tuple[MatchResult, ...]) -> MatchResult | None:
        """Choose the strongest already-validated teleport when several are visible."""
        if not teleports:
            return None
        return max(
            teleports,
            key=lambda value: (value.score, value.pixel_score, value.zncc_score),
        )

    @staticmethod
    def _target_keys_in_text(card: CardSpec, normalized_text: str) -> tuple[str, ...]:
        matches: list[tuple[int, str]] = []
        for target in card.targets:
            if any(
                (excluded := normalize_text(title)) and excluded in normalized_text
                for title in target.excludes
            ):
                continue
            title_lengths = [
                len(normalized_title)
                for title in target.titles
                if (normalized_title := normalize_text(title))
                and normalized_title in normalized_text
            ]
            if title_lengths:
                matches.append((max(title_lengths), target.key))
        if not matches:
            return ()
        longest = max(length for length, _key in matches)
        return tuple(sorted({key for length, key in matches if length == longest}))

    def _centered_title_keys(
        self, frame: np.ndarray, card: CardSpec, keys: tuple[str, ...]
    ) -> tuple[str, ...]:
        """The page whose name sits in the middle of the label bar, when the
        title read named several maps.

        Player v0.2.25 2560x1440 fullscreen 150% (2026-10-31): 第7章 back to
        the town failed with 「左右翻页都未找到拉勒凯镇：last=… 拉勒凯镇」 while
        page 1 (安全 拉勒凯镇) was on screen for 9 s.  Every page read that
        names 拉勒凯镇 alone is taken, so that read also named 洞穴神殿 or
        隐藏神殿 (same length, a tie -> no page at all).  The bar shows one
        centred label; another map's name (the next label sliding by, a map
        label) lies off the middle.  Per OCR box, the box nearest the bar's
        centre that names one map decides; inside one box, the name read last
        (the label is 「战斗Ⅰ 洞穴神殿」/「安全 拉勒凯镇」: tag, then name).
        """
        ocr_boxes = getattr(self.vision, "ocr_boxes", None)
        if ocr_boxes is None:
            return keys
        try:
            boxes = list(
                ocr_boxes(frame, "传送阵地图名分框", relative_roi=TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI)
                or []
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:  # the joined read still stands
            self._status("区域地图", f"传送阵地图名分框读取失败：{exc}")
            return keys
        width = frame.shape[1]
        middle = width * (
            TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI[0] + TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI[2]
        ) / 2
        named: list[tuple[float, str, str]] = []
        for box in boxes:
            text = normalize_text(self.vision.simplify(str(getattr(box, "name", "") or "")))
            box_keys = self._target_keys_in_text(card, text) if text else ()
            if not box_keys:
                continue
            if len(box_keys) > 1:
                box_keys = (self._last_named_key(card, text, box_keys),)
            x = getattr(box, "x", None)
            box_width = getattr(box, "width", None)
            distance = (
                abs(float(x) + float(box_width) / 2 - middle)
                if x is not None and box_width is not None
                else float("inf")
            )
            named.append((distance, box_keys[0], text))
        if not named:
            return keys
        _distance, key, text = min(named, key=lambda item: item[0])
        self._status(
            "区域地图",
            f"传送阵地图名读到多个地图（{','.join(keys)}），取中间的「{text}」-> {key}",
        )
        return (key,)

    @staticmethod
    def _last_named_key(card: CardSpec, text: str, keys: tuple[str, ...]) -> str:
        """Of ``keys`` all named in ``text``, the one whose name ends last."""
        ends: list[tuple[int, str]] = []
        for target in card.targets:
            if target.key not in keys:
                continue
            for title in target.titles:
                name = normalize_text(title)
                if name and name in text:
                    ends.append((text.rindex(name) + len(name), target.key))
        return max(ends)[1] if ends else keys[0]

    def _area_map_context(self, frame: np.ndarray, card: CardSpec) -> AreaMapContext:
        detection = self._detect_map_page_mode(frame)
        if not detection.mode.is_teleport_map:
            context = AreaMapContext(
                frame_shape=frame.shape,
                raw_text="",
                normalized_text="",
                map_page_mode=detection.mode,
                candidate_target_keys=(),
                resolved_target_key=None,
                left_arrow=None,
                right_arrow=None,
                teleports=(),
                overlap_arrow=None,
                back_button=None,
                confirmation_text=detection.header_text,
            )
            self._status(
                "区域地图",
                f"拒绝非传送页面模式={detection.mode.value}",
            )
            return context
        raw_text = self.vision.simplify(
            self.vision.ocr_text(
                frame,
                "传送阵地图名",
                relative_roi=TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI,
            )
        )
        normalized_text = normalize_text(raw_text)
        target_keys = self._target_keys_in_text(card, normalized_text)
        if len(target_keys) > 1:
            target_keys = self._centered_title_keys(frame, card, target_keys)
        if len(target_keys) != 1 and self._title_worth_rereading(card, normalized_text):
            # Read again bordered and enlarged before the page counts as
            # another map (Leo 2026-10-31 「還有沒有辦法不會再出錯」).
            for scale in TELEPORT_MAP_TITLE_REREAD_SCALES:
                again = self.vision.simplify(
                    self.vision.ocr_text(
                        frame,
                        "传送阵地图名放大重读",
                        relative_roi=TELEPORT_MAP_TITLE_OCR_RELATIVE_ROI,
                        ocr_scale=scale,
                        bordered=True,
                    )
                )
                again_keys = self._target_keys_in_text(card, normalize_text(again))
                if len(again_keys) == 1:
                    self._status(
                        "区域地图",
                        f"传送阵地图名「{raw_text or '-'}」放大{scale:g}倍重读为「{again}」",
                    )
                    raw_text, normalized_text, target_keys = (
                        again, normalize_text(again), again_keys
                    )
                    break
        context = AreaMapContext(
            frame_shape=frame.shape,
            raw_text=raw_text,
            normalized_text=normalized_text,
            map_page_mode=detection.mode,
            candidate_target_keys=target_keys,
            resolved_target_key=target_keys[0] if len(target_keys) == 1 else None,
            left_arrow=self._optional_match(frame, TELEPORT_MAP_FORWARD_TEMPLATE),
            right_arrow=self._optional_match(frame, TELEPORT_MAP_BACKWARD_TEMPLATE),
            teleports=self._teleport_map_teleports(frame),
            overlap_arrow=self._optional_match(frame, OVERLAP_ARROW_TEMPLATE),
            back_button=self._optional_match(frame, AREA_MAP_BACK_TEMPLATE),
            confirmation_text=detection.header_text,
        )
        self._status(
            "区域地图",
            (
                f"target={context.resolved_target_key or '-'}, "
                f"candidates={','.join(context.candidate_target_keys) or '-'}, "
                f"left={context.left_arrow is not None}, "
                f"right={context.right_arrow is not None}, "
                f"teleports={len(context.teleports)}, "
                f"mode={context.map_page_mode.value}, "
                f"title_ocr={context.raw_text or '-'}, "
                f"confirmation_ocr={context.confirmation_text or '-'}"
            ),
        )
        return context

    def _capture_area_map_context(self, card: CardSpec) -> AreaMapContext:
        return self._area_map_context(self.vision.capture(), card)

    def _wait_for_collection_teleport_map(
        self,
        card: CardSpec,
        timeout: float = TELEPORT_MAP_OPEN_TIMEOUT,
    ) -> AreaMapContext | NavigationResult:
        end_at = monotonic() + max(0.0, timeout)
        last = None
        previous_text = None
        while monotonic() <= end_at:
            last = self._capture_area_map_context(card)
            if last.is_area_map:
                if len(last.candidate_target_keys) > 1:
                    return NavigationResult(
                        False,
                        ScreenState.AREA_MAP,
                        "传送阵地图标题同时命中多个目标",
                    )
                if last.resolved_target_key is not None:
                    return last
                # Opened elsewhere (the hunting ground, an unrelated map):
                # a page read the same twice is enough to start seeking.
                if last.normalized_text and last.normalized_text == previous_text:
                    return last
                previous_text = last.normalized_text
            self.task.sleep(AREA_MAP_CHANGE_INTERVAL)
        return NavigationResult(
            False,
            ScreenState.UNKNOWN,
            (
                "未在限定时间内通过移动魔法阵与地图名 OCR 确认传送阵地图："
                f"last_title={last.raw_text if last is not None else '-'}"
            ),
        )

    def _seek_collection_page(
        self,
        card: CardSpec,
        context: AreaMapContext,
        target: CollectionMapTarget,
    ) -> AreaMapContext | NavigationResult:
        """Flip the teleport map to ``target`` by its page label.

        The map opens on the page of the current location, which may be any
        of the three maps, the hunting ground (left of the town in chapter
        2) or an unrelated map (user demo 2026-09-28), so neither "left to
        the first page" nor "one page right" holds: the target's side is
        taken from the known page order, else both sides are tried.
        """

        if (found := self._page_is(card, context, target)) is not None:
            return found
        # Page order, not collection order: Q_ep2's safe zone is the last
        # page, so its battle maps are to the left (Leo 2026-10-15).
        keys = list(self._collection_page_order(card))
        if context.resolved_target_key in keys:
            ahead = keys.index(target.key) > keys.index(context.resolved_target_key)
            directions = ("right", "left") if ahead else ("left", "right")
        elif target.key == keys[0]:
            # Off the card's maps: the town has been the first page in every
            # chapter so far (ch18 opened on page 6 of 10 and went right first,
            # live 2K 2026-09-30).
            directions = ("left", "right")
        else:
            directions = ("right", "left")
        start = context
        seen: list[str] = []

        def note(page: AreaMapContext) -> None:
            if page.raw_text and page.raw_text not in seen:
                seen.append(page.raw_text)

        note(context)
        for direction in directions:
            current = start
            for _ in range(TELEPORT_MAP_SEEK_LIMIT):
                changed = self._move_area_map(card, current, direction)
                if changed is None:
                    break  # no arrow or no change: this end of the list
                current = changed
                note(current)
                if (found := self._page_is(card, current, target)) is not None:
                    return found
            start = current
        # Last resort (Leo: every read needs a fallback): an arrow misread
        # as missing ended the first side unpressed (2K 桌面分身 2026-10-16,
        # 卡勒塔市's left arrow at 0.948).  Press that side's fixed place,
        # even where the page seemed to end, and keep going while it moves.
        current = start
        for _ in range(TELEPORT_MAP_SEEK_LIMIT):
            changed = self._move_area_map(card, current, directions[0], force=True)
            if changed is None:
                break
            current = changed
            note(current)
            if (found := self._page_is(card, current, target)) is not None:
                return found
        start = current
        return NavigationResult(
            False,
            ScreenState.AREA_MAP,
            # The page read in words, not 「last=…」: the 问题摘要 drops
            # key=value text, so the player's summary showed 「： 拉勒凯镇」 and
            # hid what was really read (2026-10-31).
            (
                f"传送阵地图左右翻页都未找到{target.title}（各页读到："
                + ("、".join(f"「{text}」" for text in seen) or "没读到字")
                + "）"
            ),
        )

    def _page_is(
        self, card: CardSpec, page: AreaMapContext, target: CollectionMapTarget
    ) -> AreaMapContext | None:
        """``page`` when it is ``target``'s page, else None.

        The name under the map decides.  A read of it that came out a little
        wrong still counts (Leo 2026-10-31 「字接近就判定成功」): the player's
        第7章 sat 9 s on page 1 「安全 拉勒凯镇」 and every read there missed
        the clean name, so the card was skipped.  A loose match must be close
        to this name and closer to it than to any other map of the card, so
        「安全 拉勒凯旅馆」 (the town's inn, same first three characters) is
        never the town.  The map after the teleport still checks.
        """
        if page.resolved_target_key == target.key:
            return page
        if not page.is_area_map or not page.normalized_text:
            return None
        if page.resolved_target_key is not None:
            return None  # the read names another map alone
        score = self._name_closeness(page.normalized_text, target)
        if score < LOOSE_PAGE_NAME_MIN_RATIO:
            return None
        if any(
            self._name_closeness(page.normalized_text, other) >= score
            for other in card.targets
            if other.key != target.key
        ):
            return None
        self._status(
            "区域地图",
            f"传送阵地图名「{page.raw_text}」接近{target.title}（{score:.2f}），当作这一页",
        )
        return replace(
            page,
            candidate_target_keys=(target.key,),
            resolved_target_key=target.key,
            guessed=True,
        )

    def _title_worth_rereading(self, card: CardSpec, text: str) -> bool:
        """An unresolved page read that may be one of the card's maps misread:
        nothing read, or something sharing a character run with a map name.
        A clean read of a page that is none of them (狩猎场, 旅馆) is left as
        it is, so the seek stays quick."""
        if not text:
            return True
        return any(
            self._name_closeness(text, target) >= TELEPORT_MAP_TITLE_REREAD_MIN_RATIO
            for target in card.targets
        )

    @staticmethod
    def _name_closeness(text: str, target: CollectionMapTarget) -> float:
        """How close the page read is to ``target``'s name, 0..1: the read
        without its 安全/战斗 tag, compared character by character; a read
        holding the whole name next to another map's name counts as 1."""
        bare = re.sub(r"^(安全|战斗)?[ⅠⅡⅢⅣⅤⅥⅦⅰⅱⅲiIＩ1-7]*", "", text)
        best = 0.0
        for title in target.titles:
            name = normalize_text(title)
            if not name:
                continue
            if name in text:
                return 1.0
            best = max(best, difflib.SequenceMatcher(None, name, bare).ratio())
        return best

    @staticmethod
    def _collection_page_order(card: CardSpec) -> tuple[str, ...]:
        """The card's target keys in teleport-map page order (left to right):
        ``card.targets`` (safe zone first) unless TELEPORT_PAGE_ORDER says
        otherwise (Q_ep2's safe zone is the last page, Leo 2026-10-15)."""
        keys = tuple(item.key for item in card.targets)
        order = TELEPORT_PAGE_ORDER.get(card.card_id)
        if order and sorted(order) == sorted(keys):
            return order
        return keys

    def _reset_collection_teleport_map_to_main(
        self,
        card: CardSpec,
        context: AreaMapContext,
    ) -> AreaMapContext | NavigationResult:
        current = context
        clicks = 0
        while current.left_arrow is not None:
            if clicks >= TELEPORT_MAP_FIRST_PAGE_LIMIT:
                return NavigationResult(
                    False,
                    ScreenState.AREA_MAP,
                    (f"向前点击{TELEPORT_MAP_FIRST_PAGE_LIMIT}次后仍未确认到达安全区第一页"),
                )
            changed = self._move_area_map(card, current, "left")
            if changed is None:
                return NavigationResult(
                    False,
                    ScreenState.AREA_MAP,
                    "向前翻页后未确认地图名发生变化",
                )
            current = changed
            clicks += 1
        expected = CollectionMapRole.MAIN_AREA.value
        if current.resolved_target_key != expected:
            return NavigationResult(
                False,
                ScreenState.AREA_MAP,
                (
                    "已到达传送阵地图最前页，但 OCR 未确认安全区："
                    f"expected={card.targets[0].title}, actual={current.raw_text or '-'}"
                ),
            )
        return current

    def _click_collection_destination(
        self,
        card: CardSpec,
        target: CollectionMapTarget,
        context: AreaMapContext,
    ) -> NavigationResult:
        if not context.map_page_mode.is_teleport_map:
            return NavigationResult(
                False,
                self._screen_state_for_map_page_mode(context.map_page_mode),
                f"页面模式{context.map_page_mode.value}不允许传送点击",
                map_page_mode=context.map_page_mode,
            )
        if context.resolved_target_key != target.key:
            return NavigationResult(
                False,
                ScreenState.AREA_MAP,
                (f"传送前地图名不符：expected={target.title}, actual={context.raw_text or '-'}"),
            )
        teleport = self._select_map_teleport(context.teleports)
        if teleport is None:
            return NavigationResult(
                False,
                ScreenState.AREA_MAP,
                (
                    f"{target.title}未识别到传送阵地图传送阵，"
                    "无法安全传送"
                ),
            )
        self._status(
            "传送阵地图传送阵点击中心",
            (
                f"target={target.title}, candidates={len(context.teleports)}, "
                f"selected=center={teleport.center}, "
                f"match={teleport.score:.3f}, pixel={teleport.pixel_score:.3f}, "
                f"zncc={teleport.zncc_score:.3f}"
            ),
        )
        if not self._click_teleport_map_destination(
            teleport,
            context.frame_shape,
            page_mode=context.map_page_mode,
        ):
            return NavigationResult(
                False,
                ScreenState.AREA_MAP,
                (
                    f"传送到{target.title}前未可靠确认生成魔法阵弹窗"
                    if context.map_page_mode == MapPageMode.GENERATE_TELEPORT
                    else f"传送到{target.title}前未完成传送阵地图传送"
                ),
            )
        arrived = self._wait_for_story_sandbox(card.number)
        if not arrived.success:
            return NavigationResult(
                False,
                arrived.state,
                f"传送到{target.title}后未确认剧情箱庭：{arrived.message}",
            )
        if getattr(self, "_teleport_loading_seen", False) and not context.guessed:
            # The page was this target by name and the teleport's loading
            # screen came: no area-map check after it (Leo 2026-10-01, ~2 s
            # a move).  Without the loading seen, the area map still decides.
            self._status("区域地图", f"按传送页名确认到达 {target.title}")
            return NavigationResult(
                True, ScreenState.SANDBOX, f"{card.card_id}/{target.key}/{target.title}"
            )
        return self._confirm_collection_arrival(card, target)

    def current_collection_target(self, card: CardSpec) -> str | None:
        """Which of the card's three maps the character is on (area map title).

        Works anywhere in the field, not only on a teleport circle, so the
        route can start from the current map (user 2026-09-28).
        """
        if not self.ensure_small_minimap():
            return None
        header = self._open_field_map()
        if header is None:
            return None
        self._close_field_map()
        keys = self._target_keys_in_text(card, header)
        self._status("区域地图", f"当前位置 {header} -> {keys[0] if len(keys) == 1 else '-'}")
        return keys[0] if len(keys) == 1 else None

    def _open_teleport_map_anywhere(self, card: CardSpec | None = None) -> NavigationResult:
        """The teleport map, going to the hunting ground's circle if needed.

        The user's way when not standing on a teleport circle (2026-09-28):
        the minimap's ≡ menu -> 狩猎场 -> 立即前往, then its circle.  An area
        without a circle (CIRCLE_EXIT_WALKS) is left through its exit first.
        """
        opened = self.open_teleport_map_from_sandbox()
        if opened.success:
            return opened
        # Not on a circle: click the teleport gate on the area map and walk
        # there (user's first choice, 2026-09-28).
        self._status("导航状态", "不在传送阵旁，点地图上的传送门走过去")
        walked = self._walk_to_sandbox_teleport_interaction()
        if walked.success:
            return walked
        neighbour = self._walk_to_circle_neighbour(card)
        if neighbour is not None:
            return neighbour
        self._status("导航状态", "地图传送门不可用，前往狩猎场的传送阵")
        entry = self._travel_to_hunting_ground()
        if entry is None:
            # Name the last step that failed, not only the first (player
            # report 2026-10-17 showed just 「不在传送阵旁」).
            return NavigationResult(
                False,
                walked.state,
                f"{opened.message}；走去地图传送门失败（{walked.message}）；"
                "小地图导航也没能去狩猎场或艾琳"
                + (f"（{why}）" if (why := getattr(self, "_nav_failure", "")) else ""),
            )
        if entry == HUNTING_GROUND_NAV_ENTRY:
            return self._open_teleport_map_at_hunting_ground(card)
        # 艾琳 stands in the town: its circle, walking there if needed.
        if self._click_sandbox_teleport_interaction():
            return self._open_circle_page("传送阵交互按钮")
        walked = self._walk_to_sandbox_teleport_interaction()
        if walked.success:
            return walked
        return self._walk_to_circle_neighbour(card) or walked

    def _walk_to_circle_neighbour(self, card: CardSpec | None) -> NavigationResult | None:
        """From an area without a teleport circle, walk out through its exit
        to the neighbour that has one and open the teleport map there.
        None when ``card`` has no such area or the character is elsewhere."""

        walk = CIRCLE_EXIT_WALKS.get(card.card_id) if card is not None else None
        if walk is None:
            return None
        here_title, there_title = walk
        there = next(
            (target for target in card.targets if target.title == there_title),
            CollectionMapTarget(CollectionMapRole.BATTLE_AREA_1, there_title),
        )
        here = CollectionMapTarget(CollectionMapRole.MAIN_AREA, here_title)
        self._status("导航状态", f"{here_title}没有传送阵，走出口到{there_title}再找传送阵")
        moved = self._walk_to_collection_map(card, here, there)
        if not moved.success:
            self._status("导航状态", f"没能从{here_title}走到{there_title}：{moved.message}")
            return None if "区域地图不是" in moved.message else moved
        opened = self.open_teleport_map_from_sandbox()
        if opened.success:
            return opened
        return self._walk_to_sandbox_teleport_interaction()

    def _travel_to_hunting_ground(self) -> str | None:
        """≡ menu -> 狩猎场, or the town NPC 艾琳 when the menu lists no 狩猎场
        (Leo 2026-09-30: "選單沒有狩獵場 就一律直接傳去艾琳").  The entry
        travelled to, or None."""
        return self._travel_via_nav_menu(HUNTING_GROUND_NAV_ENTRY, TOWN_NPC_NAV_ENTRY)

    def _open_minimap_nav_menu(self) -> bool:
        """Press the minimap's ≡ button: its template, else its fixed place
        once the field is confirmed (the menu read that follows checks it).

        2K 桌面分身 2026-10-16: the game drew the button glowing with an
        orange 「!」 badge, so the plain-icon template read -1.000 on every
        field frame while the quick-switch button passed 0.97; 跑商 could not
        reach the merchant and 跑图 could not go home.  Any field signal now
        allows the fixed-place press (was the C/H/M/Q key caps only)."""
        self._nav_button_miss = ""
        if self.vision.click_template(
            MERCHANT_NAV_GUIDE_TEMPLATE, timeout=MERCHANT_NAV_GUIDE_TIMEOUT, after_sleep=0.8
        ):
            return True
        # The area map left open covers the ≡ button, and the fixed place
        # lands on the map's own title row (player 1080p 2026-10-23, 第9章:
        # the map stayed open and every later field press hit it).  Close
        # the map first.
        if self._area_map_open():
            self._status("小地图导航", "区域地图还开着，先关掉再找≡按钮")
            self._close_field_map()
            if self.vision.click_template(
                MERCHANT_NAV_GUIDE_TEMPLATE, timeout=MERCHANT_NAV_GUIDE_TIMEOUT, after_sleep=0.8
            ):
                return True
            if self._area_map_open():
                self._nav_button_miss = "区域地图按返回也关不掉，挡住了≡按钮"
                return False
        frame = self.vision.capture()
        # Two key caps, as the field check: on the same sand the C cap
        # found nothing while H, M and Q passed.
        in_field = (
            sum(
                self.vision.passes(self.vision.match(frame, spec), spec)
                for spec in FIELD_ALL_KEYCAP_TEMPLATES
            )
            >= FIELD_KEYCAP_MIN_PASSES
        ) or self.classify(frame) == ScreenState.SANDBOX
        if not in_field:
            self._nav_button_miss = (
                "画面上看不到地图界面的按键提示（C、H、M、Q 至少要看到两个），"
                "可能被别的画面或视窗盖住"
            )
            return False
        self._status("小地图导航", "模板未命中，已确认在箱庭，点击标定位置")
        self.vision.click_reference(*MERCHANT_NAV_GUIDE_REFERENCE_POINT, after_sleep=0.8)
        return True

    def _travel_via_nav_menu(self, *entries: str) -> str | None:
        """The minimap's ≡ menu -> the first of ``entries`` it lists (狩猎场,
        or a town NPC such as 艾琳) -> 确认, then the field once the trip (and
        any walk after it) ends.  The entry travelled to, or None."""

        wanted = "、".join(entries)
        # Which part failed goes into the run's message, not only the log
        # (player 1080p 2026-10-19: 第3章 tried the ≡ menu three times and
        # the report could not say why).
        self._nav_failure = ""
        self._already_in_hunting_ground = False
        if HUNTING_GROUND_NAV_ENTRY in entries and self._in_hunting_ground():
            # Already in the hunting ground: no ≡ to press, its circle is
            # here (Leo's rule 「不在三張圖 → 狩獵場 → 按傳送陣」, 2026-10-23).
            self._status("导航状态", "已在狩猎场（小地图旁是狩猎场的栏），直接去按传送阵")
            self.task.log_info("跑图：人已经在狩猎场，直接去按传送阵。")
            self._already_in_hunting_ground = True
            return HUNTING_GROUND_NAV_ENTRY
        if not self._open_minimap_nav_menu():
            why = getattr(self, "_nav_button_miss", "") or "≡按钮的样子和位置都没对上"
            self._nav_failure = f"没按到小地图的≡按钮：{why}"
            self.task.log_warning(f"跑图：未识别到小地图导航按钮，无法前往{wanted}。")
            return None
        for press in range(1, NAV_MENU_PRESSES + 1):
            choice = self._nav_menu_choice(entries)
            texts = getattr(self, "_nav_menu_texts", ())
            if choice is None and HUNTING_GROUND_NAV_ENTRY in entries and (
                self._hunting_ground_panel(texts)
            ):
                # The bar showed up only after the press (read too early above).
                self._status("导航状态", "读到狩猎场的栏，人已在狩猎场，直接去按传送阵")
                self.task.log_info("跑图：人已经在狩猎场，直接去按传送阵。")
                self._already_in_hunting_ground = True
                return HUNTING_GROUND_NAV_ENTRY
            on_map = self._area_map_title_in(getattr(self, "_nav_menu_frame", None))
            if choice is not None or press == NAV_MENU_PRESSES or (
                self._nav_menu_listed(texts) and not on_map
            ):
                break
            # Nothing the menu lists was read: the ≡ press may not have taken
            # (remedy 3, docs/dev-notes/bug-prevention.md).  On a menu that was
            # open after all, the press closes it and the read below says so.
            self._status("导航状态", "按了≡按钮没看到菜单，再按一次")
            self.task.log_info("跑图：按了≡按钮没看到菜单，再按一次。")
            if not self._open_minimap_nav_menu():
                break
        if choice is None:
            seen = getattr(self, "_nav_menu_seen", "")
            self._nav_failure = f"≡菜单里没读到{wanted}" + (f"，读到：{seen}" if seen else "，什么字都没读到")
            self.task.log_warning(f"跑图：导航菜单里没有{wanted}（读到：{seen or '-'}）。")
            return None
        entry, point, shape = choice
        # A lost press left the menu open, and the field check below then
        # passed on the unchanged field as if the trip had been made.
        if not press_and_confirm(
            f"导航菜单{entry}",
            lambda: self.vision.click_client(point, shape, after_sleep=0.8),
            lambda: self._nav_entry_taken(entry),
            still_before=lambda: not self._nav_entry_taken(entry),
            sleep=self.task.sleep,
            log=self.task.log_info,
        ):
            self._nav_failure = f"点了≡菜单的{entry}没有反应"
            self.task.log_warning(f"跑图：点了导航菜单的{entry}没有反应。")
            return None
        if self._confirm_travel() == "stuck":
            self._nav_failure = "前往确认窗的「确认」读不到"
            return None
        arrived = self._wait_for_field_hud(
            timeout=self._loading_timeout(),
            interval=0.5,
            success_message=entry,
            failure_message=f"前往{entry}后未确认箱庭",
        ).success
        if not arrived:
            self._nav_failure = f"前往{entry}后没认出地图画面"
            return None
        # An NPC entry walks on to the NPC after the loading screen.
        self._wait_auto_move_finished(SANDBOX_NAVIGATION_WALK_TIMEOUT)
        return entry

    def _nav_menu_choice(
        self, entries: tuple[str, ...]
    ) -> tuple[str, tuple[int, int], tuple[int, ...]] | None:
        """The first of ``entries`` (in their order) the open ≡ menu lists,
        with its click point and the frame's shape.  Read again once an
        entry shows, so a menu still sliding in cannot hide 狩猎场."""

        end_at = monotonic() + MERCHANT_NAV_MENU_OCR_TIMEOUT
        seen = False
        self._nav_menu_seen = ""
        while True:
            frame = self.vision.capture()
            listed, texts = self._nav_menu_entries(frame, entries)
            self._status("导航菜单", " ".join(texts) or "-")
            timed_out = monotonic() >= end_at
            if not listed and timed_out:
                # Last read before giving up (Leo's ladder: read again 2×):
                # small menu words a model misreads at 1× (v6 rec, 2026-10-19).
                listed, more = self._nav_menu_entries(frame, entries, ocr_scale=2.0)
                texts = texts or more
                if listed:
                    self._status("导航菜单", "放大两倍后读到 " + " ".join(more))
            if listed and (seen or timed_out):
                entry = next(item for item in entries if item in listed)
                return entry, listed[entry], frame.shape
            if timed_out:
                self._nav_menu_frame = frame
                self._nav_menu_texts = tuple(texts)
                self._nav_menu_seen = " ".join(texts)[:40]
                return None
            seen = bool(listed)
            self.task.sleep(MERCHANT_NAV_MENU_OCR_INTERVAL)

    @staticmethod
    def _nav_menu_listed(texts) -> bool:
        """The texts read where the ≡ menu opens hold a row it lists.  A row
        is short: the 珍藏集 page's 「可体验广场钓鱼领地等…」 is not 领地."""
        return any(
            len(text) <= NAV_MENU_ROW_CHARS and word in text
            for text in texts
            for word in NAV_MENU_WORDS
        )

    def _nav_menu_shown(self, frame) -> bool:
        """The ≡ menu is open: a row it lists reads, and no area map is up.
        The area map's place labels 「迪尔索特旅馆」「…酒馆」 sit where the menu
        opens and carry its words (Leo's 2K frame of 第16章 2026-10-30)."""
        return self._nav_menu_listed(self._nav_menu_entries(frame, ())[1]) and not (
            self._area_map_title_in(frame)
        )

    def _area_map_title_in(self, frame) -> bool:
        """The area map's 「战斗 …」/「安全 …」 title reads in ``frame``."""
        if frame is None:
            return False
        header = normalize_text(
            self.vision.simplify(
                self.vision.ocr_text(
                    frame, "区域地图标题", relative_roi=TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI
                )
            )
        )
        return any(tag in header for tag in AREA_MAP_HEADER_TAGS)

    @staticmethod
    def _hunting_ground_panel(texts) -> bool:
        """The texts are the hunting ground's own bar, not a ≡ menu."""
        joined = "".join(texts)
        return HUNTING_GROUND_PANEL_WORD in joined or all(
            word in joined for word in HUNTING_GROUND_PANEL_PAIR
        )

    def _in_hunting_ground(self) -> bool:
        """The hunting ground's bar is read where the ≡ menu would be."""
        frame = self.vision.capture()
        texts = [
            normalize_text(self.vision.simplify(str(getattr(box, "name", ""))))
            for box in self.vision.ocr_boxes(frame, "狩猎场栏", MERCHANT_NAV_MENU_OCR_ROI)
        ]
        return self._hunting_ground_panel(texts)

    def _nav_menu_entries(self, frame, entries: tuple[str, ...], **kwargs):
        """The wanted ``entries`` the ≡ menu shows (with click points), and
        every text read.  An entry also counts by a part of its name that no
        other entry carries (「狩猎」/「猎场」 for one character misread)."""

        listed: dict[str, tuple[int, int]] = {}
        texts = []
        for box in self.vision.ocr_boxes(frame, "导航菜单", MERCHANT_NAV_MENU_OCR_ROI, **kwargs):
            text = normalize_text(self.vision.simplify(str(getattr(box, "name", ""))))
            center = self._ocr_box_center(box)
            if not text or center is None:
                continue
            texts.append(text)
            for entry in entries:
                if entry in text or (
                    # A part only on a box no longer than the name itself,
                    # so a longer entry carrying it (快速狩猎…) never counts.
                    len(text) <= len(entry)
                    and any(name in text for name in NAV_ENTRY_NAMES.get(entry, ()))
                ):
                    listed.setdefault(entry, center)
        return listed, texts

    def _nav_entry_taken(self, entry: str) -> bool:
        """After pressing ``entry`` in the ≡ menu: the menu no longer lists
        it, or the 立即前往 dialog or the 无法移动 toast is up."""

        def listed(frame) -> bool:
            return any(
                entry in normalize_text(self.vision.simplify(str(getattr(box, "name", ""))))
                for box in self.vision.ocr_boxes(frame, "导航菜单", MERCHANT_NAV_MENU_OCR_ROI)
            )

        frame = self.vision.capture()
        if not listed(frame):
            # Gone on two frames: one OCR miss is not a trip.
            frame = self.vision.capture()
            if not listed(frame):
                return True
        title = self.vision.ocr_text(frame, "前往确认", roi=MERCHANT_TRAVEL_DIALOG_OCR_ROI)
        if any(
            word in normalize_text(self.vision.simplify(str(title)))
            for word in MERCHANT_TRAVEL_DIALOG_KEYWORDS
        ):
            return True
        toast = self.vision.ocr_text(frame, "导航提示", roi=MERCHANT_NAV_TOAST_OCR_ROI)
        return MERCHANT_NAV_UNREACHABLE_KEYWORD in normalize_text(
            self.vision.simplify(str(toast))
        )

    def _field_map_header(self) -> str:
        return normalize_text(
            self.vision.simplify(
                self.vision.ocr_text(
                    self.vision.capture(),
                    "区域地图标题",
                    relative_roi=TELEPORT_MAP_HEADER_OCR_RELATIVE_ROI,
                )
            )
        )

    def _area_map_open(self) -> bool:
        """The area map's 「战斗 …」/「安全 …」 title is read top left, or its
        footer (世界地图 / 探索) bottom right.

        The title alone missed a map left open (player v0.2.11 2026-10-23,
        第11章 回主城: 「没认出小地图的≡按钮」 after the area-map walk): the map
        covered the ≡ button and the key caps, and was never closed."""
        header = self._field_map_header()
        if any(tag in header for tag in AREA_MAP_HEADER_TAGS):
            return True
        return self._area_map_footer_shown()

    def _area_map_footer_shown(self) -> bool:
        footer = normalize_text(
            self.vision.simplify(
                self.vision.ocr_text(
                    self.vision.capture(), "地图底栏", relative_roi=AREA_MAP_FOOTER_RELATIVE_ROI
                )
            )
        )
        return any(word in footer for word in AREA_MAP_FOOTER_KEYWORDS)

    def _close_field_map_if_open(self) -> None:
        """Close the area map when its title still shows.  A page not
        confirmed by the strict check was left open, and the next field step
        clicked on the map (player 1080p 2026-10-23, 第9章 守山人休息处)."""
        if self._area_map_open():
            self._status("区域地图", "地图页没认准但标题还在，按返回关掉")
            self._close_field_map()

    def _open_field_map(self) -> str | None:
        """Open the field's area map (as M does); return its header text.

        A minimap press that opened nothing is followed by the game's own
        key M, only on a confirmed field (remedy 4,
        docs/dev-notes/bug-prevention.md); 跑商's walk to the merchant does
        the same (Leo 2026-10-20: every step has a second way)."""
        self.task.operate_click(
            MINIMAP_CENTER_REFERENCE[0] / 1920,
            MINIMAP_CENTER_REFERENCE[1] / 1080,
            after_sleep=1.0,
        )
        header = self._field_map_opened()
        if header is None and self._press_area_map_key():
            header = self._field_map_opened()
        return header

    def _press_area_map_key(self) -> bool:
        """M, sent only while the field's key caps show (the map, a page or
        主页 is not up).  True when it was sent."""
        tap_key = getattr(self.task, "tap_key", None)
        if not callable(tap_key) or not self._field_keycaps_shown():
            return False
        self._status("区域地图", f"点小地图没打开地图，改按快捷键 {AREA_MAP_KEY}")
        self.task.log_info(f"跑图：点小地图没打开区域地图，改按快捷键 {AREA_MAP_KEY}。")
        return bool(tap_key(AREA_MAP_KEY, after_sleep=1.0))

    def _field_map_opened(self) -> str | None:
        """The area map's header once it shows, within WALK_MAP_OPEN_TIMEOUT."""
        end_at = monotonic() + WALK_MAP_OPEN_TIMEOUT
        while True:
            header = self._field_map_header()
            if "战斗" in header or "安全" in header:
                return header
            if monotonic() >= end_at:
                # The map opened with its title unread: still the map, so the
                # caller closes it (None left it covering the field).
                return header if self._area_map_footer_shown() else None
            self.task.sleep(0.4)

    def _close_field_map(self) -> None:
        """Close the area map; press again only while its header is still read,
        then the game's back key Esc.

        One blind press assumed the field was back: a swallowed press left the
        map open and the next field step clicked on the map instead.  A map
        still open after both presses covered the ≡ button and the rest of the
        card failed behind it (player 1080p 2026-10-23, 第9章); Esc is the next
        remedy (docs/dev-notes/bug-prevention.md; Leo 「關不掉 就按ESC做備案」).
        """
        self.task.operate_click(*SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT, after_sleep=1.0)
        end_at = monotonic() + FIELD_MAP_CLOSE_TIMEOUT
        open_hits = 0
        reclicked = False
        while True:
            header = self._field_map_header()
            if not any(tag in header for tag in AREA_MAP_HEADER_TAGS) and not (
                self._area_map_footer_shown()
            ):
                return
            open_hits += 1
            if monotonic() >= end_at:
                break
            if not reclicked and open_hits >= 2:
                reclicked = True
                open_hits = 0
                self._status("区域地图", "关闭后标题仍在，补点一次返回")
                self.task.operate_click(*SANDBOX_LARGE_MAP_RETURN_RELATIVE_POINT, after_sleep=0.5)
                continue
            self.task.sleep(0.4)
        escaped = False
        tap_escape = getattr(self.task, "tap_escape", None)
        if callable(tap_escape):
            self._status("区域地图", "按两次返回都没关，改按 Esc")
            self.task.log_info("跑图：区域地图按两次返回都没关，改按 Esc。")
            escaped = bool(tap_escape(after_sleep=0.5))
            if escaped and wait_for(
                lambda: not self._area_map_open(),
                FIELD_MAP_CLOSE_TIMEOUT,
                sleep=self.task.sleep,
                clock=monotonic,
            ):
                return
        how = "按返回和 Esc 都没关掉" if escaped else "按两次返回都没关掉"
        self.task.log_warning(f"跑图：区域地图{how}，标题还在：{header}。")

    def _walk_to_collection_map(
        self,
        card: CardSpec,
        current: CollectionMapTarget,
        target: CollectionMapTarget,
    ) -> NavigationResult:
        """Walk to a map without a teleport page (chapter 6's 第5层).

        User demo 2026-09-28: on the area map, clicking the exit to the next
        floor walks there and loads it without a dialog.  Which spot reacts
        depends on where the character stands, so the calibrated spots are
        tried in turn until the area map closes (user: "多點幾下或者點不同位
        置"); the header must name the expected floor before any click, and
        arrival is confirmed by the header.
        """
        if not self.ensure_small_minimap():
            return NavigationResult(False, ScreenState.SANDBOX, "小地图放大状态未能切回")
        wanted = normalize_text(target.title)
        here = normalize_text(current.title)
        edge = (card.card_id, current.key, target.key)
        header = self._open_field_map()
        for attempt in range(WALK_EXIT_ATTEMPTS):
            if header is None:
                return NavigationResult(False, ScreenState.UNKNOWN, "未能打开区域地图")
            if here not in header:
                self._close_field_map()
                return NavigationResult(
                    False, ScreenState.SANDBOX, f"区域地图不是{current.title}：{header}"
                )
            self.last_loading_title = ""
            if not self._click_walk_exit(edge, target, here):
                self._close_field_map()
                header = self._retry_walk_from_town(card, current, target)
                if header is None:
                    return NavigationResult(
                        False, ScreenState.SANDBOX, f"区域地图上点{target.title}出口没有反应"
                    )
                if not self._click_walk_exit(edge, target, here):
                    self._close_field_map()
                    return NavigationResult(
                        False,
                        ScreenState.SANDBOX,
                        f"经艾琳后区域地图上点{target.title}出口仍没有反应",
                    )
            if card.card_id in RESUMING_WALK_CARD_IDS:
                self._wait_resuming_walk(RESUMING_WALK_TIMEOUT)
            arrived = self._wait_for_field_hud(
                timeout=self._loading_timeout(),
                interval=0.5,
                success_message=target.title,
                failure_message=f"前往{target.title}后未确认箱庭",
            )
            if not arrived.success:
                return arrived
            seen = getattr(self, "last_loading_title", "") or ""
            if seen and tuple(self._target_keys_in_text(card, seen)) == (target.key,):
                return NavigationResult(True, ScreenState.SANDBOX, f"已走到{target.title}")
            header = self._open_field_map()
            if header is not None and wanted in header:
                self._close_field_map()
                return NavigationResult(True, ScreenState.SANDBOX, f"已走到{target.title}")
            if header is None or here not in header or attempt + 1 >= WALK_EXIT_ATTEMPTS:
                break
            # Still on this map with its area map open: a patrol expelled the
            # walk (ch14's 光明监视者 puts the character back at the entrance,
            # Leo: 萬一被抓要應對，避免卡死) or it stopped short.  Click again.
            self._status("导航状态", f"仍在{current.title}（可能被巡逻驱逐），再点一次{target.title}出口")
        if header is not None:
            self._close_field_map()
        return NavigationResult(
            False, ScreenState.SANDBOX, f"走到后地图不符：{header or '-'}（目标{target.title}）"
        )

    def _click_walk_exit(self, edge, target: CollectionMapTarget, here: str) -> bool:
        """Click the open area map's exit to ``target`` (calibrated spots or its
        OCR label) until the map closes; True once it did."""

        frame = self.vision.capture()
        spots = WALK_EDGES.get(edge) or EVENT_WALK_EDGES.get(edge)
        if spots:
            points = [
                (round(x * frame.shape[1] / 1920), round(y * frame.shape[0] / 1080))
                for x, y in spots
            ]
        else:
            known = WALK_LABEL_EDGES.get(edge)
            # With a recorded label place the reads stop sooner (桌面分身
            # 2026-10-18: 角色卡3 禁闭室's label was under the character's
            # icon and 5 s of re-reads ended at the recorded place anyway);
            # 2.5 s still covers labels that show ~2 s after the header (ch14).
            end_at = monotonic() + (
                WALK_LABEL_KNOWN_READ_TIMEOUT if known is not None else WALK_LABEL_READ_TIMEOUT
            )
            points = self._exit_label_points(frame, target)
            while not points and monotonic() < end_at:
                self.task.sleep(WALK_LABEL_READ_INTERVAL)
                frame = self.vision.capture()
                points = self._exit_label_points(frame, target)
            if not points and known is not None:
                # The character's icon covers the label when it stands at
                # that exit (after an expulsion, ch14 live): use where the
                # label always is.
                scale = frame.shape[0] / 1080
                x = round(known[0] * frame.shape[1] / 1920)
                y = round(known[1] * scale)
                points = [(x, y + round(dy * scale)) for dy in AREA_MAP_EXIT_ICON_OFFSETS]
                self._status("区域地图出口", f"{target.title}: 标签被遮住，用记录位置 {points}")
        picker = edge in EVENT_WALK_EDGES
        for point in points:
            self._status("导航状态", f"区域地图点击{target.title}出口 {point}")
            self.vision.click_client(point, frame.shape, after_sleep=WALK_CLICK_SETTLE_SECONDS)
            if here not in self._field_map_header() or self._confirm_exit_walk_question(here):
                return True
            if picker and self._click_exit_picker(target) and (
                here not in self._field_map_header() or self._confirm_exit_walk_question(here)
            ):
                return True
        return False

    def _confirm_exit_walk_question(self, here: str) -> bool:
        """Press 确认 on the 自动移动 dialog an area-map exit click opened;
        True once the walk started.

        A player 2026-10-17 (v0.1.44, 1080p): without 不再显示 ticked the
        game asks 「是否自动移动前往所选目的地？」 after the exit click too.
        The header stays readable above the dialog, so the click looked
        ignored and the next spot landed on the dialog's 不再显示 box; every
        walked card was skipped.  An unconfirmed dialog is cancelled so the
        next spot is not clicked onto it."""
        frame = self.vision.capture()
        if not self._auto_move_question_shown(self._walk_text(frame)):
            return False
        self._status("导航状态", "点出口后弹出自动移动确认窗，点确认")
        if not self._click_sandbox_navigation_destination_confirmation(frame):
            self._cancel_auto_move_dialog()
            return False
        for look in range(MAP_SELF_CLOSE_LOOKS):
            if here not in self._field_map_header():
                return True
            if look + 1 < MAP_SELF_CLOSE_LOOKS:
                self.task.sleep(SANDBOX_NAVIGATION_OCR_INTERVAL * 2)
        # The walk goes on with the map closed (as after a large-map 确认).
        self._close_field_map()
        return True

    def _click_exit_picker(self, target: CollectionMapTarget) -> bool:
        """The small list an area-map spot opens when several things stand
        there (战斗区 / 旅馆 / 艾琳..., event cards live 4K 2026-10-09):
        click the row of the target's kind (战斗区, or 安全区 for the
        town).  True when a row was clicked."""

        wanted = (
            EXIT_PICKER_SAFE if target.role is CollectionMapRole.MAIN_AREA else EXIT_PICKER_BATTLE
        )
        frame = self.vision.capture()
        try:
            boxes = self.vision.ocr_boxes(
                frame, "区域地图出口列表", relative_roi=AREA_MAP_EXIT_LABEL_RELATIVE_ROI
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self._status("区域地图出口列表 OCR错误", str(exc))
            return False
        for box in boxes:
            text = normalize_text(self.vision.simplify(str(getattr(box, "name", ""))))
            center = self._ocr_box_center(box)
            if wanted in text and center is not None:
                self._status("区域地图出口列表", f"点击{text} {center}")
                self.vision.click_client(center, frame.shape, after_sleep=WALK_CLICK_SETTLE_SECONDS)
                return True
        return False

    def _retry_walk_from_town(
        self,
        card: CardSpec,
        current: CollectionMapTarget,
        target: CollectionMapTarget,
    ) -> str | None:
        """An event card's exit did not react, as when the character stands
        right on it (Leo 2026-10-09: 太近不好點, 傳送回艾琳): from the town,
        go to 艾琳 and open the area map again.  Its header, or None when
        this does not apply or failed."""

        npc = RESTART_NAV_ENTRIES.get(card.card_id)
        if (
            card.card_id not in WALKED_EVENT_CARD_IDS
            or npc is None
            or current.key != card.targets[0].key
        ):
            return None
        self._status("导航状态", f"{target.title}出口点不动，先传到{npc}再点")
        if not self._travel_via_nav_menu(npc):
            return None
        header = self._open_field_map()
        if header is None or normalize_text(current.title) not in header:
            if header is not None:
                self._close_field_map()
            return None
        return header

    def _exit_label_points(self, frame, target: CollectionMapTarget) -> list[tuple[int, int]]:
        """Client points for the exit to ``target`` on the open area map: its
        label (OCR), then the exit icon drawn under it (the label or the ring
        below reacts, depending on where the character stands; ch6 demo)."""

        try:
            boxes = self.vision.ocr_boxes(
                frame, "区域地图出口", relative_roi=AREA_MAP_EXIT_LABEL_RELATIVE_ROI
            )
        except Exception as exc:
            self._status("区域地图出口 OCR错误", str(exc))
            return []
        wanted = normalize_text(target.title)
        scale = frame.shape[0] / 1080
        points = []
        for box in boxes:
            text = normalize_text(self.vision.simplify(str(getattr(box, "name", ""))))
            if not text or wanted not in text:
                continue
            center = self._ocr_box_center(box)
            if center is None:
                continue
            for dy in AREA_MAP_EXIT_ICON_OFFSETS:
                points.append((center[0], center[1] + round(dy * scale)))
        self._status(
            "区域地图出口",
            f"{target.title}: " + (", ".join(str(p) for p in points) or "未找到标签"),
        )
        return points

    def ensure_small_minimap(self) -> bool:
        """Switch an enlarged field minimap (⊖) back to small (⊕).

        True when the small minimap is confirmed or neither button shows
        (not in a field; nothing to do).  Only a matched ⊖ is clicked.
        """

        for _attempt in range(MINIMAP_SHRINK_ATTEMPTS):
            frame = self.vision.capture()
            large = self._optional_match(frame, MINIMAP_LARGE_TEMPLATE)
            if large is None:
                return True
            self._status("导航状态", "小地图为放大状态，切回小地图")
            self.vision.click_client(large.center, frame.shape, after_sleep=1.0)
            if self._optional_match(self.vision.capture(), MINIMAP_SMALL_TEMPLATE) is not None:
                return True
        self.task.log_warning("跑图：小地图放大状态未能切回。")
        return False

    def _back_to_field_after_failed_open(self, opened: NavigationResult) -> bool:
        """A map page that opened in the wrong mode is closed; otherwise the
        field is looked at once more before the next way is tried.  True
        when the story field is confirmed again."""
        mode = getattr(opened, "map_page_mode", None)
        if mode is not None and mode != MapPageMode.UNKNOWN:
            return self._close_confirmed_map_page(
                {mode}, timeout=SANDBOX_MAP_CLOSE_TIMEOUT
            ).success
        return self._wait_for_current_sandbox(timeout=SANDBOX_MAP_CLOSE_TIMEOUT).success

    def _open_circle_page(self, trigger_name: str) -> NavigationResult:
        """After the hand on a teleport circle was pressed: make sure the
        circle's 传送页 really opens (Leo 2026-10-20 「在傳送陣上 有互動可以點
        為什麼會打不開 應該要確保他打開」, v0.2.2 第8章 on a 2560x1440
        monitor: 「传送阵交互按钮后未稳定确认direct_teleport」).

        When the page is not confirmed, whatever opened instead is closed,
        the field is confirmed, and the circle is opened again: its hand
        once more, then the game's interact key F.  F is sent only on a
        confirmed field (on 主页 it opens the recent cartridge)."""
        opened = self._wait_for_sandbox_map_open(
            trigger_name,
            expected_mode=MapPageMode.DIRECT_TELEPORT,
            detect_skill_failure=False,
        )
        tries = []
        for again in CIRCLE_PAGE_AGAIN:
            if opened.success:
                return opened
            if not self._back_to_field_after_failed_open(opened):
                break
            if again == "hand":
                if not self._click_sandbox_teleport_interaction():
                    continue
                how = "再按一次交互手势"
            else:
                tap_key = getattr(self.task, "tap_key", None)
                if tap_key is None or not tap_key(
                    INTERACT_KEY, after_sleep=TELEPORT_INTERACTION_CLICK_DELAY
                ):
                    continue
                how = f"改按快捷键 {INTERACT_KEY}"
            tries.append(how)
            self._status("导航状态", f"传送页没打开（{opened.message}），{how}")
            self.task.log_info(f"跑图：按了传送阵交互后传送页没打开，{how}。")
            opened = self._wait_for_sandbox_map_open(
                f"{trigger_name}（{how}）",
                expected_mode=MapPageMode.DIRECT_TELEPORT,
                detect_skill_failure=False,
            )
        if opened.success or not tries:
            return opened
        return NavigationResult(
            False,
            opened.state,
            f"{opened.message}（已{'、'.join(tries)}）",
            map_page_mode=opened.map_page_mode,
        )

    def prepare_collection_main_area(
        self, card_id: str, *, via_hunting_ground: bool = False
    ) -> NavigationResult:
        """Normalize a newly entered story card to its safe/main area.

        ``via_hunting_ground`` is the safe restart after a failed route
        (user 2026-09-28): hunting ground -> its circle -> the town.
        """

        card = CARD_BY_ID.get(card_id)
        if card is None or not card.collectable:
            return NavigationResult(False, ScreenState.UNKNOWN, f"非跑图剧情卡带：{card_id}")
        if not self.ensure_small_minimap():
            return NavigationResult(False, ScreenState.SANDBOX, "小地图放大状态未能切回")
        if via_hunting_ground and (npc := RESTART_NAV_ENTRIES.get(card.card_id)):
            # Card 3: 艾琳 first, wherever the character stands (Leo).
            if (
                self._travel_via_nav_menu(npc)
                and self.current_collection_target(card) == card.targets[0].key
            ):
                return NavigationResult(
                    True, ScreenState.SANDBOX, f"经{npc}到达{card.targets[0].title}"
                )
            self._status("导航状态", f"经{npc}未到{card.targets[0].title}，改用原来的回城方式")
        if via_hunting_ground:
            opened = None
            if self._click_sandbox_teleport_interaction():
                # Already on a teleport circle: its map reaches the town
                # directly, no need for the hunting ground.
                opened = self._open_circle_page("传送阵交互按钮")
                if not opened.success:
                    # Hand again and F did not open it either: the ≡ menu
                    # way below is the last fallback, never the end of the
                    # card (Leo 2026-10-20, v0.2.2 第8章).
                    self._status(
                        "导航状态",
                        f"传送阵交互后没打开传送页（{opened.message}），改走小地图导航",
                    )
                    self._back_to_field_after_failed_open(opened)
                    opened = None
            if opened is None:
                entry = self._travel_to_hunting_ground()
                if entry == HUNTING_GROUND_NAV_ENTRY:
                    opened = self._open_teleport_map_at_hunting_ground(card)
                elif entry is not None:
                    # No 狩猎场 in the ≡ menu -> 艾琳 (Leo 2026-09-30).  She
                    # stands in the town, so the route starts right there.
                    if self.current_collection_target(card) == card.targets[0].key:
                        return NavigationResult(
                            True, ScreenState.SANDBOX, f"经{entry}到达{card.targets[0].title}"
                        )
                    opened = self._open_teleport_map_anywhere(card)
                else:
                    # Neither in the ≡ menu (ch13 had no 狩猎场, live
                    # 2026-09-29): walk to this map's own teleport circle.
                    opened = self._open_teleport_map_anywhere(card)
        else:
            opened = self._open_teleport_map_anywhere(card)
        if not opened.success:
            return opened
        context = self._wait_for_collection_teleport_map(card)
        if isinstance(context, NavigationResult):
            return context
        if context.map_page_mode != opened.map_page_mode:
            return NavigationResult(
                False,
                ScreenState.AREA_MAP,
                (
                    "打开入口与后续传送页模式不一致："
                    f"opened={opened.map_page_mode.value}, current={context.map_page_mode.value}"
                ),
                map_page_mode=context.map_page_mode,
            )
        main_target = card.targets[0]
        if context.resolved_target_key == main_target.key:
            return self.return_teleport_map_to_sandbox(card.number)
        first = self._seek_collection_page(card, context, main_target)
        if isinstance(first, NavigationResult):
            return self._town_by_npc_after_failed_seek(card, context, first)
        return self._click_collection_destination(
            card,
            main_target,
            first,
        )

    def _town_by_npc_after_failed_seek(
        self,
        card: CardSpec,
        context: AreaMapContext,
        failed: NavigationResult,
    ) -> NavigationResult:
        """The teleport map never showed the town by name: close it and take
        the ≡ menu's 艾琳 (she stands in the town) before the card is skipped
        (Leo 2026-10-31 「還有沒有辦法不會再出錯」)."""
        town = card.targets[0]
        self._status("导航状态", f"{failed.message}，关掉传送阵地图，改用≡选单的{TOWN_NPC_NAV_ENTRY}回{town.title}")
        self.task.log_info(
            f"跑图：传送阵地图没认出{town.title}，改用小地图≡选单找{TOWN_NPC_NAV_ENTRY}回主城。"
        )
        self._close_area_map(context)
        if (
            self._travel_via_nav_menu(TOWN_NPC_NAV_ENTRY)
            and self.current_collection_target(card) == town.key
        ):
            return NavigationResult(
                True, ScreenState.SANDBOX, f"经{TOWN_NPC_NAV_ENTRY}到达{town.title}"
            )
        why = getattr(self, "_nav_failure", "") or f"经{TOWN_NPC_NAV_ENTRY}也没到{town.title}"
        return NavigationResult(
            False,
            failed.state,
            f"{failed.message}；改用≡选单的{TOWN_NPC_NAV_ENTRY}也没回到{town.title}（{why}）",
            map_page_mode=failed.map_page_mode,
        )

    def advance_collection_map(
        self,
        card_id: str,
        current_target: CollectionMapTarget,
        next_target: CollectionMapTarget,
    ) -> NavigationResult:
        """Open the current teleport, move backward exactly one page, and travel."""

        card = CARD_BY_ID.get(card_id)
        if card is None or not card.collectable:
            return NavigationResult(False, ScreenState.UNKNOWN, f"非跑图剧情卡带：{card_id}")
        edge = (card_id, current_target.key, next_target.key)
        town_npc = TOWN_NAV_ENTRIES.get(card.card_id)
        if (
            card.card_id in WALKED_EVENT_CARD_IDS
            and town_npc
            and next_target.key == card.targets[0].key
        ):
            # Event cards without a circle: 艾琳 stands in the town, so the
            # ≡ menu reaches it from anywhere (Leo 2026-10-09); the walk is
            # the fallback.
            if (
                self._travel_via_nav_menu(town_npc)
                and self.current_collection_target(card) == next_target.key
            ):
                return NavigationResult(
                    True, ScreenState.SANDBOX, f"经{town_npc}到达{next_target.title}"
                )
            self._status("导航状态", f"经{town_npc}未到{next_target.title}，改为走过去")
        if edge in WALK_EDGES or edge in WALK_LABEL_EDGES or edge in EVENT_WALK_EDGES:
            return self._walk_to_collection_map(card, current_target, next_target)
        via = self._walk_neighbour(card, current_target, next_target)
        if via is not None:
            self._status(
                "导航状态",
                f"{next_target.title}没有传送阵，先到{via.title}再走过去",
            )
            step = self.advance_collection_map(card_id, current_target, via)
            if not step.success:
                return NavigationResult(
                    False,
                    step.state,
                    f"去{next_target.title}要先到{via.title}，但没到（{step.message}）",
                    map_page_mode=step.map_page_mode,
                )
            return self._walk_to_collection_map(card, via, next_target)
        if town_npc and next_target.key == card.targets[0].key:
            # Chapter 14 back to the town: the ≡ menu's 艾琳 (11 s, live 2K
            # 2026-09-30).  Without 压制 the walk to 左侧回廊's circle from the
            # 中央回廊 side is caught by the 光明监视者 (route test); after 压制
            # it is not (Leo), so the teleport map below stays the fallback.
            if (
                self._travel_via_nav_menu(town_npc)
                and self.current_collection_target(card) == next_target.key
            ):
                return NavigationResult(
                    True, ScreenState.SANDBOX, f"经{town_npc}到达{next_target.title}"
                )
            self._status("导航状态", f"经{town_npc}未到{next_target.title}，改用传送阵地图")
        opened = self._open_teleport_map_anywhere(card)
        if not opened.success:
            return NavigationResult(
                False,
                opened.state,
                f"{current_target.title}无法打开传送阵地图：{opened.message}",
                map_page_mode=opened.map_page_mode,
            )
        context = self._wait_for_collection_teleport_map(card)
        if isinstance(context, NavigationResult):
            return context
        if context.map_page_mode != opened.map_page_mode:
            return NavigationResult(
                False,
                ScreenState.AREA_MAP,
                (
                    "打开入口与后续传送页模式不一致："
                    f"opened={opened.map_page_mode.value}, current={context.map_page_mode.value}"
                ),
                map_page_mode=context.map_page_mode,
            )
        if context.resolved_target_key != current_target.key:
            self._status(
                "区域地图",
                f"传送阵地图停在{context.raw_text or '-'}"
                f"（预期{current_target.title}），按名称查找",
            )
        changed = self._seek_collection_page(card, context, next_target)
        if isinstance(changed, NavigationResult):
            return changed
        return self._click_collection_destination(
            card,
            next_target,
            changed,
        )

    @staticmethod
    def _walk_neighbour(
        card: CardSpec,
        current_target: CollectionMapTarget,
        next_target: CollectionMapTarget,
    ) -> CollectionMapTarget | None:
        """The map ``next_target`` is walked to from, when it has no circle
        and the character is not standing there."""
        if (card.card_id, next_target.key) not in WALK_ONLY_TARGETS:
            return None
        return next(
            (
                target
                for target in card.targets
                if target.key not in (current_target.key, next_target.key)
                and (
                    (card.card_id, target.key, next_target.key) in WALK_EDGES
                    or (card.card_id, target.key, next_target.key) in WALK_LABEL_EDGES
                )
            ),
            None,
        )

    def _area_map_page_state(
        self,
        card: CardSpec,
        previous: AreaMapContext,
    ) -> tuple[str, AreaMapContext]:
        """("moved" | "same" | "unknown", the page now) against ``previous``;
        "unknown" while no area map of the same mode reads."""
        current = self._capture_area_map_context(card)
        if not current.is_area_map or current.map_page_mode != previous.map_page_mode:
            return "unknown", current
        if (
            current.normalized_text != previous.normalized_text
            or current.candidate_target_keys != previous.candidate_target_keys
        ):
            return "moved", current
        return "same", current

    def _move_area_map(
        self,
        card: CardSpec,
        context: AreaMapContext,
        direction: str,
        *,
        force: bool = False,
    ) -> AreaMapContext | None:
        """``force``: the seek's last resort - no end-of-list skip, and the
        arrow's fixed place is pressed when the arrow is not read."""
        label = f"区域地图{'向右' if direction == 'right' else '向左'}翻页"
        if not force and self._area_map_page_end(context, direction):
            # Only the other arrow shows: this is the end of the list, and
            # pressing the missing arrow's place cost ~20 s on Q_ep2's last
            # page (Leo 2026-10-15 「活動卡帶第2的安全區是第三張地圖 要切換的時候
            # 螢幕不要再點右邊箭頭了」).  One more read first, as an arrow can
            # still be fading in right after a page turn.
            state, fresh = self._area_map_page_state(card, context)
            if state == "unknown":
                return None
            if state == "moved":
                return fresh  # a late turn landed meanwhile: that is the move
            if self._area_map_page_end(fresh, direction):
                self._status("区域地图", f"{label}：这一侧没有箭头，已是尽头，不按")
                return None
            context = fresh
        arrow = context.right_arrow if direction == "right" else context.left_arrow
        if arrow is not None:
            center = arrow.center
        elif context.map_page_mode.is_teleport_map:
            # Bright pages (snow, 华特波尔雪山) hide the white arrows from the
            # template (live 2K 2026-09-29): press the arrow's fixed place;
            # an unchanged page still means this end of the list.
            x, y = TELEPORT_PAGE_ARROW_REFERENCE[direction]
            height, width = context.frame_shape[:2]
            center = (round(x * width / 1920), round(y * height / 1080))
        else:
            return None
        blind = arrow is None
        pages: list[AreaMapContext] = []
        end_reads: list[AreaMapContext] = []

        def moved() -> bool:
            state, current = self._area_map_page_state(card, context)
            if state == "moved":
                pages.append(current)
                return True
            # A blind press (no arrow seen, e.g. read before the arrows were
            # drawn, live 2K 2026-10-15) ends early once the unchanged page
            # shows only the other arrow, instead of waiting out two presses.
            if (
                blind
                and not force
                and state == "same"
                and self._area_map_page_end(current, direction)
            ):
                end_reads.append(current)
                return len(end_reads) >= TELEPORT_PAGE_END_READS
            end_reads.clear()
            return False

        # One dropped press read as the end of the list and turned the seek
        # round (or failed it): pressed once more while the page stays.
        flipped = press_and_confirm(
            label,
            lambda: self.vision.click_client(
                center,
                context.frame_shape,
                after_sleep=AREA_MAP_CLICK_SETTLE_SECONDS,
            ),
            moved,
            still_before=lambda: self._area_map_page_state(card, context)[0] == "same",
            timeout=AREA_MAP_CHANGE_TIMEOUT,
            poll=AREA_MAP_CHANGE_INTERVAL,
            sleep=self.task.sleep,
            log=lambda message: self._status("区域地图", message),
        )
        if flipped and not pages:
            self._status("区域地图", f"{label}：页面没变且这一侧没有箭头，已是尽头")
            return None
        return pages[-1] if flipped else None

    @staticmethod
    def _area_map_page_end(context: AreaMapContext, direction: str) -> bool:
        """The page shows the other arrow but not ``direction``'s: the end of
        the list that way (both missing says nothing: bright pages hide them)."""
        if direction == "right":
            return context.right_arrow is None and context.left_arrow is not None
        return context.left_arrow is None and context.right_arrow is not None

    def _close_area_map(self, context: AreaMapContext) -> NavigationResult:
        if not context.map_page_mode.is_teleport_map:
            return NavigationResult(
                False,
                self._screen_state_for_map_page_mode(context.map_page_mode),
                f"非传送页面模式{context.map_page_mode.value}不允许关闭区域地图",
                map_page_mode=context.map_page_mode,
            )
        return self._close_confirmed_map_page(
            {context.map_page_mode},
            timeout=8.0,
        )

    def _confirm_collection_arrival(
        self,
        card: CardSpec,
        target: CollectionMapTarget,
    ) -> NavigationResult:
        # The loading screen already named the new map (Leo 2026-09-29): no
        # map page is opened when that name is exactly this target.
        seen = getattr(self, "last_loading_title", "") or ""
        if seen and tuple(self._target_keys_in_text(card, seen)) == (target.key,):
            self._status("区域地图", f"读取画面地图名 {seen} -> {target.key}")
            return NavigationResult(
                True, ScreenState.SANDBOX, f"{card.card_id}/{target.key}/{target.title}"
            )
        # Else the field's own area map (M) names the map in ~2 s; reopening
        # the teleport map through the hand prompt took ~12 s per move at 2K.
        if self.ensure_small_minimap():
            header = self._open_field_map()
            if header is not None:
                self._close_field_map()
                # By card key, not substring: 卢戈森林 is inside 卢戈森林深处.
                if tuple(self._target_keys_in_text(card, header)) == (target.key,):
                    return NavigationResult(
                        True, ScreenState.SANDBOX, f"{card.card_id}/{target.key}/{target.title}"
                    )
                return NavigationResult(
                    False, ScreenState.SANDBOX, f"到达后地图不符：目标={target.title}，实际={header}"
                )
        area = self.ensure_area_map()
        if not area.success:
            return NavigationResult(False, area.state, f"到达后无法复核区域地图：{area.message}")
        context = self._capture_area_map_context(card)
        if context.map_page_mode != area.map_page_mode:
            return NavigationResult(
                False,
                ScreenState.AREA_MAP,
                (
                    "到达复核时页面模式发生变化："
                    f"opened={area.map_page_mode.value}, current={context.map_page_mode.value}"
                ),
                map_page_mode=context.map_page_mode,
            )
        if context.resolved_target_key != target.key:
            actual = context.resolved_target_key or context.raw_text or "未知"
            return NavigationResult(
                False,
                ScreenState.AREA_MAP,
                f"到达后地图不符：目标={target.title}，实际={actual}",
            )
        closed = self._close_area_map(context)
        if not closed.success:
            return closed
        return NavigationResult(
            True,
            ScreenState.SANDBOX,
            f"{card.card_id}/{target.key}/{target.title}",
        )
