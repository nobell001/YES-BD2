from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from time import monotonic

from src.tasks.map_trade.action_icons import (
    ABSORB_ICON,
    SEARCH_ICON,
    ActionIconDetection,
    ActionIconSpec,
    ActionIconState,
)
from src.tasks.map_trade.collector_constants import (
    ABSORB_ACTION,
    SUMMON_ACTION,
    SUPPRESS_ACTION,
    ACTION_AFTER_CLICK_SECONDS,
    ACTION_FAILURE_FEEDBACK,
    ACTION_FEEDBACK_CHARACTER_RATIO,
    ACTION_FEEDBACK_RELATIVE_ROI,
    ACTION_FEEDBACK_SUCCESS_DELAY_SECONDS,
    ACTION_FEEDBACK_TIMEOUT,
    ACTION_ICON_DETECTION_INTERVAL,
    ACTION_USED_RECHECK_SECONDS,
    ACTION_USED_RECHECKS,
    ACTION_ICON_DETECTION_SAMPLES,
    ACTION_OCR_WINDOW_INTERVAL,
    ACTION_OCR_WINDOW_SAMPLES,
    ACTION_SUCCESS_FEEDBACK,
    SEARCH_ACTION,
    SEARCH_COUNTDOWN_INTERVAL,
    SEARCH_MISSED_FEEDBACK_COUNTDOWN_SECONDS,
    SEARCH_COUNTDOWN_PATTERN,
    SEARCH_COUNTDOWN_RELATIVE_ROI,
    SEARCH_COUNTDOWN_TIMEOUT,
    SKILL_FAILURE_TEXT_LIMIT,
    SKILL_GROUP_RELATIVE_POINTS,
    SKILL_GROUP_SWITCH_SETTLE_SECONDS,
    SKILL_OCR_FALLBACK_UPSCALE,
    SKILL_OCR_UPSCALE,
    SearchCountdownSession,
    SkillAction,
    SkillExecutionResult,
    SkillFeedbackObservation,
)
from src.tasks.map_trade.models import (
    DAILY_ABSORB_LIMIT,
    DAILY_SUMMON_LIMIT,
    DAILY_SUPPRESS_LIMIT,
    CollectionMapRole,
    MatchResult,
)
from src.tasks.map_trade.vision import parse_used_limit

# Used to split a count read without its slash ("7180" -> 7/80) until the
# HUD has shown today's limit (see ``_known_limit``).
SKILL_DAILY_LIMITS = {
    "吸收": DAILY_ABSORB_LIMIT,
    "召集": DAILY_SUMMON_LIMIT,
    "压制": DAILY_SUPPRESS_LIMIT,
}


# Pause between back-to-back skill presses (Leo 2026-09-29: 0.5 s; 10-09
# 0.8 s after a player's 「召集点的太快了经常点不上」 on a slower PC).
PIPELINE_CLICK_INTERVAL = 0.8
PIPELINE_RECHECK_SECONDS = 0.6
# A press the game did not take (a player 2026-10-09: 「召集点的太快了经常点
# 不上失败」) is pressed once more after a pause, and then taken as done
# (Leo: 「补按后 你就不要管了」).
PRESS_AGAIN_PAUSE_SECONDS = 1.5
# Slot count readers by icon name (the 压制 icon is named 制服).
COUNT_ACTIONS_BY_ICON = {
    ABSORB_ACTION.icon.name: ABSORB_ACTION,
    SUMMON_ACTION.icon.name: SUMMON_ACTION,
    SUPPRESS_ACTION.icon.name: SUPPRESS_ACTION,
}


# Action records that already count as done on their map.
LOCAL_DONE_STATES = frozenset({"local_done", "pending", "settled", "preexisting_used"})



# Fixed slots (Leo's layout, which the usage page asks players to copy): the
# button face is about 10 px (1080p) above its count, about 70 px across.
SLOT_ICON_ABOVE_COUNT = 10 / 1080
# Pause before looking for a late 探查 countdown and pressing it once more.
SEARCH_RETRY_PAUSE_SECONDS = 1.0
SLOT_ICON_SIZE = 70 / 1080


def relative_roi_center(
    relative_roi: tuple[float, float, float, float], frame_shape: tuple[int, ...]
) -> tuple[int, int]:
    """Client pixel at the middle of a (left, top, right, bottom) relative ROI."""
    height, width = frame_shape[:2]
    left, top, right, bottom = relative_roi
    return round((left + right) / 2 * width), round((top + bottom) / 2 * height)

class SkillExecutionMixin:
    @staticmethod
    def _action_detection_is_stable(
        previous: ActionIconDetection,
        current: ActionIconDetection,
    ) -> bool:
        """Require one state and physical slot identity across two frames."""

        if previous.state is not current.state:
            return False
        if previous.state not in {
            ActionIconState.AVAILABLE,
            ActionIconState.USED,
        }:
            return False
        if previous.semantic_state and current.semantic_state:
            if previous.semantic_state != current.semantic_state:
                return False
        first = previous.match
        second = current.match
        if min(*first.size, *second.size) <= 0:
            return False
        scale = max(
            0.2,
            min(
                abs(float(first.scale or 1.0)),
                abs(float(second.scale or 1.0)),
            ),
        )
        tolerance = max(2, round(6.0 * scale))
        return (
            abs(first.center[0] - second.center[0]) <= tolerance
            and abs(first.center[1] - second.center[1]) <= tolerance
            and abs(first.size[0] - second.size[0]) <= tolerance
            and abs(first.size[1] - second.size[1]) <= tolerance
        )

    @staticmethod
    def _stable_detection(
        detection: ActionIconDetection,
        sample_count: int,
    ) -> ActionIconDetection:
        reason = str(detection.reason or "")
        if "跨帧稳定" not in reason:
            reason = f"{reason}；跨帧稳定确认" if reason else "跨帧稳定确认"
        return replace(
            detection,
            reason=reason,
            stable=True,
            sample_count=max(2, int(sample_count)),
        )

    @staticmethod
    def _unstable_detection(
        detection: ActionIconDetection,
        sample_count: int,
    ) -> ActionIconDetection:
        reason = str(detection.reason or "")
        if "跨帧稳定" not in reason:
            reason = (
                f"{reason}；未达到跨帧稳定确认"
                if reason
                else "未达到跨帧稳定确认"
            )
        return replace(
            detection,
            reason=reason,
            stable=False,
            sample_count=max(1, int(sample_count)),
        )

    @staticmethod
    def _action_detection_rank(detection: ActionIconDetection) -> tuple:
        state_rank = {
            ActionIconState.AVAILABLE: 3,
            ActionIconState.USED: 2,
            ActionIconState.UNKNOWN: 1,
            ActionIconState.ABSENT: 0,
        }
        return (
            state_rank[detection.state],
            detection.match.score,
            detection.match.zncc_score,
            detection.match.pixel_score,
            detection.bright_core_ratio or -1.0,
        )

    def _detect_action_icon(
        self,
        icon: ActionIconSpec,
        *,
        require_stable: bool = False,
    ) -> tuple[object, ActionIconDetection]:
        """Capture a short window so a transient HUD frame cannot cause a miss."""

        stable_required = require_stable
        best_frame = None
        best_detection = None
        previous_detection = None
        observed_samples = 0
        for attempt in range(ACTION_ICON_DETECTION_SAMPLES):
            frame = self.vision.capture()
            detection = self.action_icons.detect(frame, icon)
            observed_samples += 1
            if (
                best_detection is None
                or self._action_detection_rank(detection)
                > self._action_detection_rank(best_detection)
            ):
                best_frame = frame
                best_detection = detection
            if stable_required:
                if (
                    detection.stable
                    and detection.sample_count >= 2
                    and detection.state
                    in {ActionIconState.AVAILABLE, ActionIconState.USED}
                ):
                    return frame, detection
                if (
                    previous_detection is not None
                    and self._action_detection_is_stable(previous_detection, detection)
                ):
                    return frame, self._stable_detection(
                        detection,
                        max(
                            2,
                            previous_detection.sample_count,
                            detection.sample_count,
                        ),
                    )
                if detection.state in {
                    ActionIconState.AVAILABLE,
                    ActionIconState.USED,
                }:
                    previous_detection = detection
                else:
                    previous_detection = None
                if attempt + 1 < ACTION_ICON_DETECTION_SAMPLES:
                    self.task.sleep(ACTION_ICON_DETECTION_INTERVAL)
                continue
            if detection.state not in {
                ActionIconState.ABSENT,
                ActionIconState.UNKNOWN,
            }:
                return frame, detection
            if attempt + 1 < ACTION_ICON_DETECTION_SAMPLES:
                self.task.sleep(ACTION_ICON_DETECTION_INTERVAL)
        if best_detection is None:
            best_detection = ActionIconDetection(
                ActionIconState.ABSENT,
                MatchResult(-1.0, (0, 0), (0, 0)),
                reason="未取得图标识别帧",
            )
        if stable_required and best_detection.state in {
            ActionIconState.AVAILABLE,
            ActionIconState.USED,
        }:
            best_detection = self._unstable_detection(
                best_detection,
                observed_samples,
            )
        return best_frame, best_detection

    def _open_skill_menu(
        self,
        expected_icons: tuple[ActionIconSpec, ...],
        *,
        allow_group_one_recovery: bool = False,
    ) -> bool:
        def inspect(frame):
            detections = tuple(self.action_icons.detect(frame, icon) for icon in expected_icons)
            return detections, all(
                value.state not in {ActionIconState.ABSENT, ActionIconState.UNKNOWN}
                for value in detections
            )

        def inspect_window():
            best_detections = None
            for attempt in range(ACTION_ICON_DETECTION_SAMPLES):
                frame = self.vision.capture()
                current, opened = inspect(frame)
                if opened:
                    return current, True
                if best_detections is None:
                    best_detections = current
                else:
                    best_detections = tuple(
                        max(
                            (previous, candidate),
                            key=self._action_detection_rank,
                        )
                        for previous, candidate in zip(
                            best_detections,
                            current,
                            strict=True,
                        )
                    )
                if attempt + 1 < ACTION_ICON_DETECTION_SAMPLES:
                    self.task.sleep(ACTION_ICON_DETECTION_INTERVAL)
            best_detections = best_detections or ()
            return best_detections, all(
                value.state not in {ActionIconState.ABSENT, ActionIconState.UNKNOWN}
                for value in best_detections
            )

        detections, opened = inspect_window()
        if opened or self._counts_prove_menu(expected_icons):
            return True

        states = ", ".join(
            f"{icon.name}={value.state.value}"
            for icon, value in zip(expected_icons, detections, strict=True)
        )
        if not allow_group_one_recovery:
            self.task.log_warning(f"地图采集：技能栏未确认：{states}。")
            return False

        # A partial match is not evidence that the wrong group is selected.
        # Never click a fixed group center merely because one action template
        # blinked; recovery is reserved for an all-missing menu in a confirmed
        # story-map context.
        if not all(
            value.state in {ActionIconState.ABSENT, ActionIconState.UNKNOWN}
            for value in detections
        ):
            self.task.log_warning(
                f"地图采集：技能栏部分识别但未确认，不执行技能组1回退：{states}。"
            )
            return False

        # The collection skills may sit in any group (the user keeps cooking
        # in group 1 and 探查/吸收/召集/压制 in group 2, 2026-09-28): try the
        # groups in turn and stay on the one that shows them.
        for group, point in sorted(SKILL_GROUP_RELATIVE_POINTS.items()):
            self._status("技能组切换", f"采集技能未显示，切换到技能组{group}")
            self.task.operate_click(*point, after_sleep=SKILL_GROUP_SWITCH_SETTLE_SECONDS)
            detections, opened = inspect_window()
            if opened or self._counts_prove_menu(expected_icons):
                return True
        states = ", ".join(
            f"{icon.name}={value.state.value}"
            for icon, value in zip(expected_icons, detections, strict=True)
        )
        self.task.log_warning(f"地图采集：三个技能组都没有找到采集技能：{states}。")
        return False

    def _counts_prove_menu(self, expected_icons: tuple[ActionIconSpec, ...]) -> bool:
        """The skill group shows when every expected slot reads "used/limit".

        On bright ground (埃克夏城 cobblestones, live 2K 2026-09-29) a greyed
        icon fails its template while its count stays readable; only the
        collection group has counts in those fixed slots.
        """
        actions = [COUNT_ACTIONS_BY_ICON.get(icon.name) for icon in expected_icons]
        if not actions or any(action is None for action in actions):
            return False
        try:
            readable = all(self._read_count(action) is not None for action in actions)
        except AttributeError:  # vision without OCR (tests, probes)
            return False
        if readable:
            self._status("技能组确认", "图标被背景干扰，以固定栏位次数确认技能栏")
            return True
        return False

    def _resume_by_count(
        self,
        action: SkillAction,
        existing: dict[str, object] | None,
        *,
        card_id: str,
        map_role: CollectionMapRole,
    ) -> SkillExecutionResult | None:
        """An ARMED/CLICKED action whose icon cannot be read: its count
        exactly one above the stored baseline proves it ran."""
        if existing is None or str(existing.get("state", "")) not in {"armed", "clicked"}:
            return None
        baseline = existing.get("baseline")
        if not baseline or len(baseline) != 2:
            return None
        self._last_count_window_stable = False
        now = self._read_count_window(action)
        if (
            now is None
            or not self._last_count_window_stable
            or tuple(now) != (int(baseline[0]) + 1, int(baseline[1]))
        ):
            return None
        self.progress.mark_action_local_done(
            card_id, map_role, action.name, pending=False, observed=tuple(now)
        )
        self._status(f"{action.name}状态", f"图标不可读，次数 {baseline[0]}->{now[0]} 证明已执行")
        return SkillExecutionResult(True, now[0] >= now[1])

    @staticmethod
    def _action_text_relative_roi(
        detection: ActionIconDetection,
        frame_shape: tuple[int, ...],
    ) -> tuple[float, float, float, float]:
        height, width = frame_shape[:2]
        left, top = detection.match.position
        icon_width, icon_height = detection.match.size
        return (
            max(0.0, (left - icon_width * 0.25) / max(1, width)),
            max(0.0, (top + icon_height * 0.65) / max(1, height)),
            min(1.0, (left + icon_width * 1.25) / max(1, width)),
            min(1.0, (top + icon_height * 2.15) / max(1, height)),
        )

    @staticmethod
    def _feedback_character_ratio(text: str, keyword: str) -> float:
        actual = Counter(character for character in text if character.isalnum())
        expected = Counter(character for character in keyword if character.isalnum())
        expected_count = sum(expected.values())
        if expected_count <= 0:
            return 0.0
        return sum((actual & expected).values()) / expected_count

    def _read_action_feedback(self, action: SkillAction) -> SkillFeedbackObservation:
        best = SkillFeedbackObservation("", None)
        keywords = (
            *(('success', value) for value in ACTION_SUCCESS_FEEDBACK[action.name]),
            *(('failure', value) for value in ACTION_FAILURE_FEEDBACK.get(action.name, ())),
        )
        end_at = monotonic() + ACTION_FEEDBACK_TIMEOUT
        while True:
            text = self.vision.ocr_text(
                self.vision.capture(),
                f"{action.name}执行反馈",
                relative_roi=ACTION_FEEDBACK_RELATIVE_ROI,
                target_height=1080,
            )
            # OCR 只输出简体中文（繁体转换已取消）；引擎可能粘连相邻文本，
            # 先归一再打分，并让显式失败关键字在平分（或更强正向词）时获胜，
            # 确保 ``没有可以吸收`` 不会被当成成功。
            try:
                normalized = self.vision.simplify(text)
            except AttributeError:
                normalized = str(text)
            failure_matches = [
                (self._feedback_character_ratio(normalized, keyword), keyword)
                for outcome, keyword in keywords
                if outcome == "failure"
            ]
            success_matches = [
                (self._feedback_character_ratio(normalized, keyword), keyword)
                for outcome, keyword in keywords
                if outcome == "success"
            ]
            best_failure = max(failure_matches, default=(0.0, ""))
            best_success = max(success_matches, default=(0.0, ""))
            if best_failure[0] >= ACTION_FEEDBACK_CHARACTER_RATIO:
                best = SkillFeedbackObservation(
                    text,
                    "failure",
                    best_failure[0],
                    best_failure[1],
                )
            elif best_success[0] > best.ratio:
                best = SkillFeedbackObservation(
                    text,
                    "success",
                    best_success[0],
                    best_success[1],
                )
            if text and not best.text:
                best = SkillFeedbackObservation(text, None)
            matched_outcome = (
                best.outcome
                if best.ratio >= ACTION_FEEDBACK_CHARACTER_RATIO
                else None
            )
            feedback_recognized = matched_outcome is not None or (
                action.name == "吸收" and bool(best.text)
            )
            if feedback_recognized:
                break
            remaining = end_at - monotonic()
            if remaining <= 0:
                break
            self.task.sleep(min(ACTION_OCR_WINDOW_INTERVAL, remaining))
        matched_outcome = (
            best.outcome
            if best.ratio >= ACTION_FEEDBACK_CHARACTER_RATIO
            else None
        )
        observation = SkillFeedbackObservation(
            best.text,
            matched_outcome,
            best.ratio,
            best.keyword,
        )
        self._status(
            f"{action.name}执行反馈",
            (
                f"outcome={observation.outcome or 'unknown'}; "
                f"ratio={observation.ratio:.3f}; "
                f"text={observation.text or '-'}"
            ),
        )
        return observation

    def _wait_after_feedback_match(
        self,
        action: SkillAction,
        feedback: SkillFeedbackObservation,
    ) -> None:
        if feedback.outcome is None and not (
            action.name == "吸收" and feedback.text
        ):
            return
        self._status(
            f"{action.name}下一步点击",
            f"反馈已识别，等待{ACTION_FEEDBACK_SUCCESS_DELAY_SECONDS:.1f}秒",
        )
        self.task.sleep(ACTION_FEEDBACK_SUCCESS_DELAY_SECONDS)

    def _read_count_window(
        self,
        action: SkillAction,
        detection: ActionIconDetection | None = None,
        *,
        allow_single: bool = False,
    ) -> tuple[int, int] | None:
        samples: list[tuple[int, int]] = []
        for attempt in range(ACTION_OCR_WINDOW_SAMPLES):
            count = self._read_count(action, detection)
            if count is not None:
                samples.append(count)
                # Two equal reads already make the window stable; the third
                # read only cost time (~0.3 s x 6 per battle map).
                if samples.count(count) >= 2:
                    break
            if attempt + 1 < ACTION_OCR_WINDOW_SAMPLES:
                self.task.sleep(ACTION_OCR_WINDOW_INTERVAL)
        if not samples:
            self._last_count_window_stable = False
            return None
        count, occurrences = Counter(samples).most_common(1)[0]
        self._last_count_window_stable = occurrences >= 2
        if occurrences < 2 and not allow_single:
            self._status(
                f"{action.name}次数窗口",
                f"不稳定：{samples}",
            )
            return None
        self._status(
            f"{action.name}次数窗口",
            (
                f"{'稳定' if self._last_count_window_stable else '单帧'}="
                f"{count[0]}/{count[1]}；samples={samples}"
            ),
        )
        return count

    def _start_search(
        self,
        *,
        map_role: CollectionMapRole,
        slot_fallback: bool = False,
    ) -> SearchCountdownSession | SkillExecutionResult:
        # With the slot fallback the menu was just confirmed by 吸收 (icon
        # or count).  Demanding the 探查 icon too failed on bright ground
        # (2K 2026-10-07 埃克夏城: both read "absent"), cycled all three
        # skill groups and 探查 was never pressed.
        expected = (ABSORB_ICON,) if slot_fallback else (SEARCH_ICON, ABSORB_ICON)
        menu_confirmed = self._open_skill_menu(expected, allow_group_one_recovery=True)
        if not menu_confirmed:
            return SkillExecutionResult(False, message="未确认安全区技能栏")
        search_action = SEARCH_ACTION
        frame, detection = self._detect_action_icon(
            search_action.icon,
            require_stable=True,
        )
        self._report_icon_detection(search_action, detection)
        clear = detection.state is ActionIconState.AVAILABLE and detection.stable
        if not clear and not slot_fallback:
            if detection.state is ActionIconState.ABSENT:
                message = "未识别到探查图标"
            elif not detection.stable:
                message = "探查图标未达到跨帧稳定确认"
            else:
                message = f"探查图标状态不可点击：{detection.state.value}"
            return SkillExecutionResult(False, message=message)
        countdown_roi = SEARCH_COUNTDOWN_RELATIVE_ROI
        if clear:
            center = detection.match.center
        else:
            # The icon is washed out by the ground (snow, bright stone): its
            # slot is fixed (the countdown appears over it), so the press goes
            # there and only the toast or countdown proves it started.
            frame = self.vision.capture()
            center = relative_roi_center(countdown_roi, frame.shape)
            self._status("探查", "图标看不清，按固定栏位并以提示/倒计时确认")
        self.vision.click_client(
            center,
            frame.shape,
            after_sleep=ACTION_AFTER_CLICK_SECONDS,
        )
        feedback = self._read_action_feedback(search_action)
        if feedback.outcome == "success":
            self._wait_after_feedback_match(search_action, feedback)
        elif not self._search_started_without_feedback():
            return SkillExecutionResult(
                False,
                message=(
                    "探查点击后未确认执行反馈："
                    f"ratio={feedback.ratio:.3f}, text={feedback.text or '-'}"
                ),
            )
        end_at = monotonic() + SEARCH_COUNTDOWN_TIMEOUT
        last_text = ""
        while monotonic() <= end_at:
            frame = self.vision.capture()
            # The normal search glyph is covered by the countdown digits as
            # soon as the action starts.  Its absence (or a transient
            # ``unknown`` state) is expected and must not veto the fixed OCR
            # countdown evidence.
            last_text = self.vision.ocr_text(
                frame,
                "探查倒计时",
                relative_roi=countdown_roi,
                target_height=1080,
                ocr_scale=SKILL_OCR_UPSCALE,
            )
            countdown = re.sub(r"\D", "", last_text)
            self._status("探查倒计时", countdown or "-")
            if SEARCH_COUNTDOWN_PATTERN.fullmatch(countdown):
                return SearchCountdownSession(countdown_roi, int(countdown))
            self.task.sleep(SEARCH_COUNTDOWN_INTERVAL)
        return SkillExecutionResult(
            False,
            message=f"探查点击后未确认倒计时：last_ocr={last_text or '-'}",
        )

    def _search_started_without_feedback(self) -> bool:
        """The short toast can be missed on a slow PC while 探查 did start:
        its countdown over the icon is the proof (never clicked again)."""
        end_at = monotonic() + SEARCH_MISSED_FEEDBACK_COUNTDOWN_SECONDS
        while True:
            if self._search_running():
                self.task.log_info("探查：没读到执行提示，但倒计时已出现，视为已开始。")
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(SEARCH_COUNTDOWN_INTERVAL)

    def _search_running(self) -> bool:
        text = self.vision.ocr_text(
            self.vision.capture(),
            "探查倒计时",
            relative_roi=SEARCH_COUNTDOWN_RELATIVE_ROI,
            target_height=1080,
            ocr_scale=SKILL_OCR_UPSCALE,
        )
        countdown = re.sub(r"\D", "", text)
        self._status("探查倒计时", countdown or "-")
        return bool(SEARCH_COUNTDOWN_PATTERN.fullmatch(countdown))

    def _absorb_used_up(
        self, *, card_id: str, map_role: CollectionMapRole
    ) -> SkillExecutionResult | None:
        """Leo 2026-10-05: with 吸收 already at its daily limit a map that
        still needs it is not started at all - no 探查, no 召集/压制 (ch.8
        battle 2 at 21/21 still got all three).  Only a stable count window
        stops the map; an unreadable one leaves the old per-action checks."""
        existing = self.progress.get_action_record(card_id, map_role, ABSORB_ACTION.name)
        if existing is not None and str(existing.get("state", "")) in LOCAL_DONE_STATES:
            return None
        if not self._open_skill_menu((ABSORB_ICON,), allow_group_one_recovery=True):
            return None
        self._last_count_window_stable = False
        count = self._read_count_window(ABSORB_ACTION)
        if count is None or count[0] < count[1]:
            return None
        return SkillExecutionResult(
            False,
            True,
            f"吸收今日已用完（{count[0]}/{count[1]}），{map_role.label}不探查、不按召集/压制，留待次日",
        )

    def _ensure_search(
        self, *, map_role: CollectionMapRole
    ) -> SearchCountdownSession | SkillExecutionResult | None:
        """探查 once per cartridge, before 吸收/召集/压制 (user rule 2026-09-28).

        Decided by text, not by the icon's look (Leo 2026-10-06: snow and
        bright stone wash the half-transparent icon out): a countdown over
        the slot means it is running; otherwise it is pressed (the icon's
        match when clear, else the fixed slot) and counts as started only
        when its toast or countdown appears.  Pressing a running or cooling
        探查 does nothing, and its length (240 s, 60 s…) is never assumed.
        """
        if self._search_running():
            self._status("采集进度", f"{map_role.label}：探查进行中，不重复按")
            return None
        if not self._open_skill_menu((ABSORB_ICON,), allow_group_one_recovery=True):
            return SkillExecutionResult(False, message="未确认采集技能栏")
        started = self._start_search(map_role=map_role, slot_fallback=True)
        if not isinstance(started, SkillExecutionResult):
            return started
        # Not proven started.  Leo 2026-10-07: never go on to 吸收 without a
        # 探查 (the hidden items stay unshown and the 吸收 finds nothing).
        # A late countdown is accepted, then one more press; else stop here.
        self.task.sleep(SEARCH_RETRY_PAUSE_SECONDS)
        if self._search_running():
            self._status("采集进度", f"{map_role.label}：探查倒计时出现，已在进行")
            return None
        retried = self._start_search(map_role=map_role, slot_fallback=True)
        if not isinstance(retried, SkillExecutionResult):
            return retried
        return SkillExecutionResult(
            False,
            message=f"探查没有开始（{retried.message}），不按吸收以免浪费次数",
        )

    def _verify_search_countdown(self, session: SearchCountdownSession) -> bool:
        end_at = monotonic() + SEARCH_COUNTDOWN_TIMEOUT
        last_text = ""
        while monotonic() <= end_at:
            last_text = self.vision.ocr_text(
                self.vision.capture(),
                "战斗区域1探查倒计时",
                relative_roi=session.relative_roi,
                target_height=1080,
                ocr_scale=SKILL_OCR_UPSCALE,
            )
            countdown = re.sub(r"\D", "", last_text)
            self._status("探查倒计时", countdown or "-")
            if SEARCH_COUNTDOWN_PATTERN.fullmatch(countdown):
                return True
            self.task.sleep(SEARCH_COUNTDOWN_INTERVAL)
        self.task.log_warning(
            f"地图采集：进入战斗区域1后未持续识别到探查倒计时，last_ocr={last_text or '-'}。"
        )
        return False

    def _use_actions(
        self,
        actions: tuple[SkillAction, ...],
        *,
        card_id: str,
        map_role: CollectionMapRole,
    ) -> SkillExecutionResult:
        menu_confirmed = self._open_skill_menu(
            tuple(action.icon for action in actions),
            allow_group_one_recovery=True,
        )
        if not menu_confirmed:
            return SkillExecutionResult(False, message="未确认采集技能栏")

        depleted = False
        pending_actions: list[str] = []
        # Leo 2026-09-29: the slots are fixed, so the three skills are
        # pressed back to back and verified afterwards (was detect / click /
        # wait / verify one at a time, ~10 s per battle map at 2K).
        self._missed_presses = set()
        self._pressed_again = set()
        results = self._use_actions_pipelined(actions, card_id=card_id, map_role=map_role)
        missed = next((result for result in results if not result.completed), None)
        if missed is not None and missed.press_again:
            # Done skills are skipped on the next pass by their records; the
            # bright one is pressed again (its record turns void first).
            self._status(
                "采集技能",
                f"{missed.message}；按钮还亮着，等{PRESS_AGAIN_PAUSE_SECONDS:.1f}秒补按一次",
            )
            self._pressed_again = set(self._missed_presses)
            self.task.sleep(PRESS_AGAIN_PAUSE_SECONDS)
            results = self._use_actions_pipelined(actions, card_id=card_id, map_role=map_role)
        for result in results:
            if not result.completed:
                return SkillExecutionResult(
                    False,
                    depleted or result.depleted,
                    result.message,
                    tuple(pending_actions) + result.pending_actions,
                )
            depleted = depleted or result.depleted
            pending_actions.extend(result.pending_actions)
        message = ""
        if pending_actions:
            message = "动作已完成；次数待后续明亮帧对账：" + "、".join(pending_actions)
        return SkillExecutionResult(
            True,
            depleted,
            message,
            tuple(pending_actions),
        )

    def _use_actions_pipelined(
        self,
        actions: tuple[SkillAction, ...],
        *,
        card_id: str,
        map_role: CollectionMapRole,
    ) -> list[SkillExecutionResult]:
        """Prepare every action, click them in a row, then verify each.

        The per-action safety is unchanged: the same stable icon detection,
        count baseline, ARMED/CLICKED records and post-click proof (icon
        used + feedback or an exact +1 count) as ``_use_action``.  Only the
        order differs, and the 0.8 s pause after each toast is gone (a
        hidden toast is covered by the +1 count proof).  The first action
        that cannot be prepared stops the batch before any later click.
        """
        results: list[SkillExecutionResult] = []
        armed: list[tuple[SkillAction, object, ActionIconDetection, tuple[int, int]]] = []
        map_done = False
        for action in actions:
            if map_done and action.name != SUMMON_ACTION.name:
                # Leo 2026-10-07: a grey 吸收 (with 探查 on) means the map was
                # done this week; 压制 stays pressable as monsters come back,
                # and pressing it again only spent a count.
                self.progress.mark_action_seen_done(card_id, map_role, action.name)
                results.append(
                    SkillExecutionResult(True, message="吸收已是灰色，这张图本周做过，跳过")
                )
                continue
            self._grey_done = False
            early, prepared = self._prepare_action(action, card_id=card_id, map_role=map_role)
            if action.name == ABSORB_ACTION.name and early is not None and self._grey_done:
                map_done = True
            elif action.name == SUMMON_ACTION.name and map_done and not (
                early is not None and self._grey_done
            ):
                # 吸收 grey but 召集 still bright: only 吸收 was done here by
                # hand (live 4K 2026-10-09: the run skipped 召集 and 压制 and
                # 💀4 stayed; YES-BD2 #10, E5/E7 marked done without 压制).
                # Leo's rule: grey 吸收 alone is not done, 召集 and 压制 go on.
                map_done = False
            if early is not None:
                results.append(early)
                if not early.completed:
                    break
                continue
            armed.append(prepared)
        stop_after = len(results) if results and not results[-1].completed else None
        clicked = []
        last_click_at = None
        for action, frame, detection, before in armed:
            if last_click_at is not None:
                # Slower PCs missed presses 0.5 s apart (player, 2026-10-09).
                self.task.sleep(max(0.0, PIPELINE_CLICK_INTERVAL - (monotonic() - last_click_at)))
            last_click_at = monotonic()
            self.vision.click_client(
                detection.match.center,
                frame.shape,
                after_sleep=ACTION_AFTER_CLICK_SECONDS,
            )
            self.progress.mark_action_clicked(card_id, map_role, action.name)
            feedback = self._read_action_feedback(action)
            clicked.append((action, detection, before, feedback))
        if clicked:
            # Let the last icon finish greying before it is judged (live 2K
            # 2026-09-29: a lone 吸收 read "absent" right after the click).
            self.task.sleep(ACTION_FEEDBACK_SUCCESS_DELAY_SECONDS)
        verified = []
        for action, detection, before, feedback in clicked:
            _post_frame, post_detection = self._detect_action_icon(
                action.icon,
                require_stable=True,
            )
            if post_detection.state in {ActionIconState.ABSENT, ActionIconState.UNKNOWN}:
                self.task.sleep(PIPELINE_RECHECK_SECONDS)
                _post_frame, post_detection = self._detect_action_icon(
                    action.icon,
                    require_stable=True,
                )
            self._report_icon_detection(action, post_detection)
            result = self._finish_after_click(
                action,
                card_id=card_id,
                map_role=map_role,
                before=before,
                detection=detection,
                post_detection=post_detection,
                feedback=feedback,
            )
            if not result.completed and action.name in getattr(self, "_pressed_again", ()):
                # Leo 2026-10-09: a missed press is almost always fixed by
                # the second one, so it is not checked again.
                self.progress.mark_action_seen_done(card_id, map_role, action.name)
                self._status(f"{action.name}状态", "已补按一次，不再检查")
                result = SkillExecutionResult(True, result.depleted, "已补按一次，不再检查")
            verified.append(result)
        if stop_after is not None:
            # Keep the order: verified clicks first, then the failure.
            return verified + results
        return results + verified

    def _prepare_action(
        self,
        action: SkillAction,
        *,
        card_id: str,
        map_role: CollectionMapRole,
    ):
        """(early result, None) or (None, (action, frame, detection, before))."""
        existing = self.progress.get_action_record(card_id, map_role, action.name)
        early = self._existing_record_outcome(action, existing)
        if early is not None:
            return early, None
        frame, detection = self._detect_fresh_action_icon(action, existing)
        self._report_icon_detection(action, detection)
        if (
            detection.state in {ActionIconState.AVAILABLE, ActionIconState.USED}
            and not detection.stable
        ):
            return SkillExecutionResult(False, message=f"{action.name}图标未达到跨帧稳定确认"), None
        # A pending ARMED/CLICKED record is settled by the count first (its
        # icon may read bright or not at all on some maps).
        by_count = self._resume_by_count(action, existing, card_id=card_id, map_role=map_role)
        if by_count is not None:
            return by_count, None
        resumed = self._resume_pending_intent(
            action, existing, detection, card_id=card_id, map_role=map_role
        )
        if resumed is not None:
            return resumed, None
        if detection.state in {ActionIconState.ABSENT, ActionIconState.UNKNOWN}:
            slot = self._slot_detection(action)
            if slot is None:
                if detection.state is ActionIconState.ABSENT:
                    return SkillExecutionResult(False, message=f"未识别到{action.name}图标"), None
                return SkillExecutionResult(False, message=f"{action.name}图标状态未知"), None
            frame, detection = slot
        if detection.state is ActionIconState.USED:
            frame, detection, failure = self._grey_with_search_on(
                action, frame, detection, map_role
            )
            if failure is not None:
                return failure, None
        if detection.state is ActionIconState.USED:
            return (
                self._resolve_preexisting_used(
                    action, detection, card_id=card_id, map_role=map_role
                ),
                None,
            )
        before, failure = self._prepare_before_click(
            action, detection, card_id=card_id, map_role=map_role
        )
        if failure is not None:
            return failure, None
        return None, (action, frame, detection, before)

    def _slot_detection(self, action: SkillAction):
        """(frame, detection) at the action's fixed slot when its icon is
        washed out but the count under it reads steadily (Leo 2026-10-06:
        decide by the text).  The press is then proven only by an exact +1
        on that count; a full count stops before any click."""
        if action.fixed_count_relative_roi is None:
            return None
        self._last_count_window_stable = False
        count = self._read_count_window(action)
        if count is None or not self._last_count_window_stable:
            return None
        frame = self.vision.capture()
        height, width = frame.shape[:2]
        left, top, right, _bottom = action.fixed_count_relative_roi
        # The button's face sits just above its count.
        x = round((left + right) / 2 * width)
        y = round((top - SLOT_ICON_ABOVE_COUNT) * height)
        side = max(4, round(SLOT_ICON_SIZE * height))
        match = MatchResult(0.0, (x - side // 2, y - side // 2), (side, side))
        self._status(
            f"{action.name}图标",
            f"看不清，按固定栏位，以次数 {count[0]}/{count[1]} 为准",
        )
        detection = ActionIconDetection(
            ActionIconState.AVAILABLE,
            match,
            reason="固定栏位：图标被背景干扰，以次数判断",
            stable=True,
        )
        return frame, detection

    def _detect_fresh_action_icon(self, action: SkillAction, existing):
        """The icon's state; a dark one with no record yet is read again after
        a pause (the bar dims for a moment after 探查)."""
        frame, detection = self._detect_action_icon(action.icon, require_stable=True)
        if existing is not None:
            return frame, detection
        for _attempt in range(ACTION_USED_RECHECKS):
            if detection.state is not ActionIconState.USED:
                break
            self._status(f"{action.name}图标", "看起来已使用，稍等再看一次")
            self.task.sleep(ACTION_USED_RECHECK_SECONDS)
            frame, detection = self._detect_action_icon(action.icon, require_stable=True)
        return frame, detection

    def _use_action(
        self,
        action: SkillAction,
        *,
        card_id: str,
        map_role: CollectionMapRole,
    ) -> SkillExecutionResult:
        existing = self.progress.get_action_record(card_id, map_role, action.name)
        # A process restart may leave an ARMED/CLICKED intent.  Even when the
        # icon is bright again we must not click a second time; a later USED
        # frame can safely reconcile the intent instead.
        early = self._existing_record_outcome(action, existing)
        if early is not None:
            return early
        frame, detection = self._detect_fresh_action_icon(action, existing)
        self._report_icon_detection(action, detection)
        if (
            detection.state in {ActionIconState.AVAILABLE, ActionIconState.USED}
            and not detection.stable
        ):
            return SkillExecutionResult(
                False,
                message=f"{action.name}图标未达到跨帧稳定确认",
            )
        resumed = self._resume_pending_intent(
            action,
            existing,
            detection,
            card_id=card_id,
            map_role=map_role,
        )
        if resumed is not None:
            return resumed
        if detection.state in {ActionIconState.ABSENT, ActionIconState.UNKNOWN}:
            if detection.state is ActionIconState.ABSENT:
                return SkillExecutionResult(
                    False,
                    message=f"未识别到{action.name}图标",
                )
            return SkillExecutionResult(False, message=f"{action.name}图标状态未知")
        if detection.state is ActionIconState.USED:
            frame, detection, failure = self._grey_with_search_on(
                action, frame, detection, map_role
            )
            if failure is not None:
                return failure
        if detection.state is ActionIconState.USED:
            return self._resolve_preexisting_used(
                action,
                detection,
                card_id=card_id,
                map_role=map_role,
            )
        before, failure = self._prepare_before_click(
            action,
            detection,
            card_id=card_id,
            map_role=map_role,
        )
        if failure is not None:
            return failure
        assert before is not None
        self.vision.click_client(
            detection.match.center,
            frame.shape,
            after_sleep=ACTION_AFTER_CLICK_SECONDS,
        )
        # CLICKED is durable only after the recognized-center click
        # returns successfully.  A crash/exception during the click
        # therefore leaves the pre-click ARMED intent for safe recovery.
        self.progress.mark_action_clicked(card_id, map_role, action.name)
        feedback = self._read_action_feedback(action)
        self._wait_after_feedback_match(action, feedback)
        post_frame, post_detection = self._detect_action_icon(
            action.icon,
            require_stable=True,
        )
        self._report_icon_detection(action, post_detection)
        return self._finish_after_click(
            action,
            card_id=card_id,
            map_role=map_role,
            before=before,
            detection=detection,
            post_detection=post_detection,
            feedback=feedback,
        )

    def _existing_record_outcome(
        self,
        action: SkillAction,
        existing: dict[str, object] | None,
    ) -> SkillExecutionResult | None:
        if existing is None:
            return None
        existing_state = str(existing.get("state", existing.get("status", "")))
        if existing_state in LOCAL_DONE_STATES:
            pending = bool(existing.get("pending", False))
            self._status(
                f"{action.name}状态",
                "已本地完成，待次数对账" if pending else "已本地完成",
            )
            return SkillExecutionResult(
                True,
                pending_actions=(action.name,) if pending else (),
                message=("次数待后续明亮帧对账" if pending else ""),
            )
        return None

    def _resume_pending_intent(
        self,
        action: SkillAction,
        existing: dict[str, object] | None,
        detection: ActionIconDetection,
        *,
        card_id: str,
        map_role: CollectionMapRole,
    ) -> SkillExecutionResult | None:
        if existing is None:
            return None
        existing_state = str(existing.get("state", existing.get("status", "")))
        if existing_state not in {"armed", "clicked", "blocked"}:
            return None
        if detection.state is ActionIconState.USED:
            self.progress.mark_action_local_done(
                card_id,
                map_role,
                action.name,
                pending=True,
            )
            return SkillExecutionResult(
                True,
                message="重启后由稳定已使用状态完成；次数待后续明亮帧对账",
                pending_actions=(action.name,),
            )
        if detection.state is ActionIconState.AVAILABLE:
            # The icon is bright again, so the earlier press did not take
            # (2K 2026-10-07 埃克夏城: a 吸收 without 探查 found nothing and its
            # record blocked the map for the day).  A used one greys out, so
            # pressing again cannot be charged twice (Leo 2026-10-07).
            self.progress.mark_action_void(
                card_id, map_role, action.name, "图标仍可按，上次点击没有生效"
            )
            self._status(f"{action.name}状态", "上次点击没有生效，图标仍可按，再按一次")
            return None
        self.progress.mark_action_blocked(
            card_id,
            map_role,
            action.name,
            "上次点击意图未决，禁止重复点击",
        )
        return SkillExecutionResult(
            False,
            message=f"{action.name}上次点击意图未决，禁止重复点击",
        )

    def _grey_with_search_on(self, action, frame, detection, map_role):
        """(frame, detection, failure): a grey icon means "done" only while
        探查 runs (Leo 2026-10-07).  With no countdown, 探查 is turned on
        first and the icon looked at again."""
        if self._search_running():
            return frame, detection, None
        started = self._ensure_search(map_role=map_role)
        if isinstance(started, SkillExecutionResult):
            return frame, detection, started
        frame, detection = self._detect_action_icon(action.icon, require_stable=True)
        return frame, detection, None

    def _resolve_preexisting_used(
        self,
        action: SkillAction,
        detection: ActionIconDetection,
        *,
        card_id: str,
        map_role: CollectionMapRole,
    ) -> SkillExecutionResult:
        """Grey on arrival: done on this map this week, by this PC or the
        other one (Leo 2026-10-07).  It is not pressed and never waits for
        a count: 2K 埃克夏森林深处's grey 吸收 waited for an old 待对账 record
        and stopped the run."""
        self.progress.mark_action_seen_done(card_id, map_role, action.name)
        self._grey_done = True
        self._status(f"{action.name}状态", "图标已是灰色：这张图本周已做过，跳过")
        return SkillExecutionResult(True, message="动作已使用，跳过点击")

    def _prepare_before_click(
        self,
        action: SkillAction,
        detection: ActionIconDetection,
        *,
        card_id: str,
        map_role: CollectionMapRole,
    ) -> tuple[tuple[int, int] | None, SkillExecutionResult | None]:
        self._last_count_window_stable = False
        before = self._read_count_window(action, detection)
        if before is None:
            return None, SkillExecutionResult(
                False,
                message=f"{action.name}次数 OCR 失败",
            )
        self._status(f"{action.name}次数", f"{before[0]}/{before[1]}")
        # Leo 2026-10-07: each map's 吸收/召集/压制 works once a week and a
        # used one greys out, so a press can never be charged twice.  With
        # 探查 running, a pressable icon is pressed; unsettled earlier counts
        # are only tidied up here, they never hold a press back.
        if self.progress.pending_count(action.name) and self._last_count_window_stable:
            self.progress.reconcile_pending(action.name, before)
            self.progress.settle_unconsumed_preexisting(
                action.name, before, card_id=card_id, map_role=map_role
            )
        if detection.state is ActionIconState.AVAILABLE and before[0] >= before[1]:
            return None, SkillExecutionResult(
                False,
                True,
                f"{action.name}次数已达到 {before[0]}/{before[1]}，当前地图未完成",
            )
        if not self.progress.arm_action(
            card_id,
            map_role,
            action.name,
            baseline=before,
        ):
            return None, SkillExecutionResult(
                False,
                True,
                f"{action.name}每日额度或未决动作已阻止新点击",
            )
        return before, None

    def _finish_after_click(
        self,
        action: SkillAction,
        *,
        card_id: str,
        map_role: CollectionMapRole,
        before: tuple[int, int],
        detection: ActionIconDetection,
        post_detection: ActionIconDetection,
        feedback: SkillFeedbackObservation,
    ) -> SkillExecutionResult:
        count_detection = post_detection if post_detection.present else detection
        self._last_count_window_stable = False
        after = self._read_count_window(
            action,
            count_detection,
            allow_single=True,
        )
        post_window_stable = bool(self._last_count_window_stable)
        icon_used = post_detection.state is ActionIconState.USED
        exact_single_increment = bool(
            after is not None
            and after[1] == before[1]
            and after[0] == before[0] + 1
        )
        if after is not None:
            self._status(f"{action.name}次数", f"{after[0]}/{after[1]}")
            if post_window_stable:
                self.progress.reconcile_pending(action.name, after)

        # Explicit failure wins over a stale/bright post frame.  Absorb's
        # positive token is accepted only with a stable USED post state; a
        # negative token is never converted into success.
        if (
            feedback.outcome == "failure"
            and after is not None
            and tuple(after) == tuple(before)
            and post_window_stable
        ):
            # "Nothing to absorb / summon / subdue here", with 探查 running
            # and the count unchanged: the map was already done, e.g. from
            # the other PC on the same account (Leo 2026-10-07: judge by the
            # game's result, not by this PC's records).  Done, nothing used.
            self.progress.mark_action_local_done(
                card_id, map_role, action.name, pending=False, observed=tuple(after)
            )
            self._status(f"{action.name}状态", f"这张图已经做过（{feedback.text}），不扣次数")
            return SkillExecutionResult(True, after[0] >= after[1], "这张图已经做过")
        if feedback.outcome == "failure":
            if post_detection.state is ActionIconState.AVAILABLE:
                self.progress.mark_action_void(
                    card_id,
                    map_role,
                    action.name,
                    feedback.text,
                )
            else:
                self.progress.mark_action_blocked(
                    card_id,
                    map_role,
                    action.name,
                    feedback.text or "失败反馈与图标状态冲突",
                )
            return SkillExecutionResult(
                False,
                (after[0] >= after[1]) if after is not None else False,
                f"{action.name}执行反馈明确失败：{feedback.text or '-'}",
            )

        feedback_success = feedback.outcome == "success"
        if action.name == "吸收" and feedback.outcome is None and feedback.text:
            # A meaningful positive-token overlap is still required when the
            # engine does not set ``outcome=success``.  The exact
            # ``吸收周围的拾取物`` token normally sets ``outcome=success``.
            overlap = self._feedback_character_ratio(
                feedback.text,
                ACTION_SUCCESS_FEEDBACK["吸收"][0],
            )
            feedback_success = overlap >= 0.50
            if feedback_success:
                self._status("吸收成功反馈待标定", feedback.text)
        # The count rising by exactly one on a trusted frame, with the icon
        # greyed, proves the action even when its toast was hidden behind
        # the previous one (live 2026-09-28: 吸收 3/21->4/21 while the toast
        # area still showed 探查's "在240秒内确认隐藏物品的位置").
        count_proves = (
            after is not None
            and after[1] == before[1]
            and after[0] == before[0] + 1
            and (post_window_stable or exact_single_increment)
        )
        # On bright ground (towns in snow or stone, live 2K 2026-09-29) the
        # greyed icon fails its template; an exact +1 on the count, with the
        # icon at least no longer reading "available", proves the press.
        icon_unreadable = post_detection.state in {ActionIconState.ABSENT, ActionIconState.UNKNOWN}
        # Its own success toast plus an exact +1 on a stable count is proof
        # even when the icon still reads bright (压制 on 记忆裂缝, live 2K).
        if (
            (icon_used and (feedback_success or count_proves))
            or (icon_unreadable and count_proves and post_window_stable)
            or (feedback_success and count_proves and post_window_stable)
        ):
            # A valid absolute snapshot is settled immediately; any
            # dim/bare/invalid post OCR remains a durable pending action.
            trusted_post = post_window_stable or exact_single_increment
            if (
                after is not None
                and after[1] == before[1]
                and after[0] >= before[0] + 1
                and trusted_post
            ):
                self.progress.mark_action_local_done(
                    card_id,
                    map_role,
                    action.name,
                    pending=False,
                    observed=after,
                )
                pending = False
            else:
                self.progress.mark_action_local_done(
                    card_id,
                    map_role,
                    action.name,
                    pending=True,
                    observed=after,
                )
                pending = True
            return SkillExecutionResult(
                True,
                (after[0] >= after[1]) if after is not None else False,
                "次数待后续明亮帧对账" if pending else "",
                (action.name,) if pending else (),
            )

        return SkillExecutionResult(
            False,
            (after[0] >= after[1]) if after is not None else False,
            (
                f"{action.name}执行证据不一致："
                f"count={before[0]}/{before[1]}->"
                f"{(f'{after[0]}/{after[1]}' if after is not None else '待对账')}, "
                f"icon={detection.state.value}->{post_detection.state.value}, "
                f"feedback={feedback.outcome or 'unknown'}, "
                f"text={feedback.text or '-'}"
            ),
            # Pressed again only when every sign says the game never got the
            # press: icon still bright, no toast, and the count read steadily
            # at exactly its value before.  压制 stays bright after a press
            # that took (Leo 2026-10-07), so its count decides; before the
            # next press the count is read once more (_resume_by_count).
            # 召集 is pressed again even when its count did not read
            # steadily: it greys out once it takes, so still bright means the
            # game dropped it (a slow PC, right after 吸收; two players
            # 2026-10-09).  压制 stays bright either way, so its count decides.
            press_again=self._note_missed_press(
                action,
                post_detection.state is ActionIconState.AVAILABLE
                and feedback.outcome is None
                and not feedback_success
                and (
                    (post_window_stable and after is not None and tuple(after) == tuple(before))
                    or (
                        action.name == SUMMON_ACTION.name
                        and (after is None or tuple(after) == tuple(before))
                    )
                ),
            ),
        )

    def _known_limit(self, action_name: str) -> int | None:
        """Today's limit as the HUD showed it, else the usual one."""
        try:
            return self.progress.limit_of(action_name)
        except Exception:
            return SKILL_DAILY_LIMITS.get(action_name)

    def _note_missed_press(self, action: SkillAction, missed: bool) -> bool:
        if missed:
            self._missed_presses = getattr(self, "_missed_presses", set()) | {action.name}
        return bool(missed)

    def _report_icon_detection(
        self,
        action: SkillAction,
        detection: ActionIconDetection,
    ) -> None:
        match = detection.match
        brightness = (
            "-" if detection.bright_core_ratio is None else f"{detection.bright_core_ratio:.3f}"
        )
        geometry = getattr(self.vision, "last_frame_geometry", None)
        frame_shape = getattr(self, "_last_skill_frame_shape", None)
        geometry_data = self._serialize_frame_geometry(geometry, frame_shape)
        candidates = detection.evidence_candidates
        if not candidates:
            evidence_by_name = getattr(self.vision, "last_candidate_evidence", {})
            try:
                candidates = tuple(evidence_by_name.get(action.template.name, ()))
            except AttributeError:
                candidates = ()
        candidate_data = tuple(
            self._serialize_candidate(candidate)
            for candidate in candidates[:8]
        )
        self._last_skill_geometry = geometry_data
        self._status(
            f"{action.name}图标",
            (
                f"{detection.state.value}; match={match.score:.3f}; "
                f"pixel={match.pixel_score:.3f}; zncc={match.zncc_score:.3f}; "
                f"gradient={match.gradient_zncc_score:.3f}; "
                f"edge={match.edge_score:.3f}; scale={match.scale:.3f}; "
                f"margin={detection.candidate_margin:.3f}; "
                f"stable={detection.stable}/{detection.sample_count}; "
                f"bright={brightness}; reason={detection.reason or '-'}"
            ),
        )
        self._last_skill_observations[action.name] = {
            "state": detection.state.value,
            "semantic_state": str(detection.semantic_state or ""),
            "stable": bool(detection.stable),
            "sample_count": int(max(1, detection.sample_count)),
            "match": round(float(match.score), 4),
            "pixel": round(float(match.pixel_score), 4),
            "zncc": round(float(match.zncc_score), 4),
            "gradient": round(float(match.gradient_zncc_score), 4),
            "edge": round(float(match.edge_score), 4),
            "scale": round(float(match.scale), 4),
            "position": [int(value) for value in match.position],
            "size": [int(value) for value in match.size],
            "center": [int(value) for value in match.center],
            "candidate_margin": round(float(detection.candidate_margin), 4),
            "geometry": geometry_data,
            "candidates": list(candidate_data),
            "bright": (
                None
                if detection.bright_core_ratio is None
                else round(float(detection.bright_core_ratio), 4)
            ),
            "reason": str(detection.reason or "")[:SKILL_FAILURE_TEXT_LIMIT],
        }

    @staticmethod
    def _finite_number(value, default: float = -1.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if number == number and abs(number) != float("inf") else default

    @classmethod
    def _serialize_frame_geometry(cls, geometry, frame_shape) -> dict[str, object]:
        if geometry is None:
            if frame_shape is None:
                return {}
            return {
                "frame_width": int(frame_shape[1]),
                "frame_height": int(frame_shape[0]),
            }
        return {
            "frame_width": int(geometry.frame_width),
            "frame_height": int(geometry.frame_height),
            "content": [
                int(geometry.content_left),
                int(geometry.content_top),
                int(geometry.content_width),
                int(geometry.content_height),
            ],
            "scale_x": round(cls._finite_number(geometry.scale_x), 4),
            "scale_y": round(cls._finite_number(geometry.scale_y), 4),
            "client_scale": round(cls._finite_number(geometry.client_scale), 4),
            "aspect_ratio": round(cls._finite_number(geometry.aspect_ratio), 4),
            "effective_aspect_ratio": round(
                cls._finite_number(geometry.effective_aspect_ratio),
                4,
            ),
            "accepted": bool(geometry.accepted),
            "rejection_reasons": [
                str(value)[:SKILL_FAILURE_TEXT_LIMIT]
                for value in tuple(geometry.rejection_reasons)[:8]
            ],
        }

    @classmethod
    def _serialize_candidate(cls, candidate) -> dict[str, object]:
        result = getattr(candidate, "result", candidate)
        return {
            "position": [int(value) for value in result.position],
            "size": [int(value) for value in result.size],
            "center": [int(value) for value in result.center],
            "scale": round(cls._finite_number(getattr(result, "scale", 1.0)), 4),
            "interpolation": str(getattr(candidate, "interpolation", ""))[:32],
            "m": round(cls._finite_number(result.score), 4),
            "p": round(cls._finite_number(result.pixel_score), 4),
            "z": round(cls._finite_number(result.zncc_score), 4),
            "gradient": round(cls._finite_number(result.gradient_zncc_score), 4),
            "edge": round(cls._finite_number(result.edge_score), 4),
            "rejection_reasons": [
                str(value)[:SKILL_FAILURE_TEXT_LIMIT]
                for value in tuple(getattr(candidate, "rejection_reasons", ()))[:8]
            ],
        }

    def _read_count(
        self,
        action: SkillAction,
        detection: ActionIconDetection | None = None,
    ) -> tuple[int, int] | None:
        # The calibrated fixed ROI is intentionally reused at 3x after a 2x
        # miss.  This catches the reproduced dark ``2`` without widening the
        # region into adjacent UI text.
        scales = (
            (SKILL_OCR_UPSCALE, SKILL_OCR_FALLBACK_UPSCALE)
            if action.fixed_count_relative_roi is not None
            else (SKILL_OCR_UPSCALE,)
        )
        for index, scale in enumerate(scales):
            frame = self.vision.capture()
            if action.fixed_count_relative_roi is not None:
                text = self.vision.ocr_text(
                    frame,
                    f"{action.name}次数",
                    relative_roi=action.fixed_count_relative_roi,
                    target_height=1080,
                    ocr_scale=scale,
                )
            elif detection is not None:
                text = self.vision.ocr_text(
                    frame,
                    f"{action.name}次数",
                    relative_roi=self._action_text_relative_roi(
                        detection,
                        frame.shape,
                    ),
                    target_height=1080,
                )
            else:
                return None
            count = parse_used_limit(text, self._known_limit(action.name))
            if count is not None:
                return count
            if index + 1 < len(scales):
                # No long stability wait before the fallback; it is a
                # same-frame/next-frame best-effort read.
                continue
        return None
