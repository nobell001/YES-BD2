"""Shared flow for home-entry pages that only need a "claim all" press.

Mail, mission rewards and pass rewards share one shape: confirm the home
screen, open the page from a fixed home entry, confirm the page title by OCR,
press a claim button located by its own OCR text inside a narrow ROI (never a
blind fixed point: the pass page also carries a purchase button), dismiss the
reward overlay, and return home with bounded back-button retries.

A grey claim button means nothing to claim and is not pressed.  A lit one
counts as claimed only once it reads grey or is gone (under the reward popup)
after the press: a swallowed press leaves the page unchanged, which used to
read as 「无新奖励」.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.task_vision_mixin import (
    LOADING_TEMPLATE,
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
    TaskVisionMixin,
)
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text

# 1920x1080 reference coordinates, calibrated on the 简体 client 2026-09-25.
BACK_BUTTON_POINT = (150, 50)
# Whole top-left bar: the OCR detector drops characters on tight single-label
# crops (e.g. 每日任务 -> 日任务), so keep the back arrow and icon for context.
PAGE_TITLE_ROI = (0, 0, 760, 110)
# 日任务 vs 每日任务 = 0.86 passes, 每周任务 vs 每日任务 = 0.75 must not.
TITLE_FUZZY_RATIO = 0.8
# Neutral spot used only to close an unrecognised reward overlay: empty top
# bar on the mail, mission and pass pages.
OVERLAY_TAP_POINT = (960, 22)

# Text that closes a reward overlay when tapped.
OVERLAY_DISMISS_KEYWORDS = (
    "点击画面即可返回",
    "点击画面返回",
    "点击任意位置",
    "点击空白处",
    "点击屏幕",
    "轻触画面",
)
# A "确认" button is only pressed when one of these reward titles is on screen.
REWARD_DIALOG_TITLES = ("获得道具", "获得奖励", "领取奖励", "奖励领取", "领取成功", "获得物品")
CONFIRM_TEXT = "确认"
# Home entry clicks are occasionally swallowed; re-click while home persists.
ENTRY_CLICK_ATTEMPTS = 3
ENTRY_RETRY_SECONDS = 4.0
# A tab click sent while a page is still opening can be dropped (the bag's
# 装备 tab, live 2026-09-27), so tab switches are clicked again.
TAB_CLICK_ATTEMPTS = 3
TAB_RETRY_SECONDS = 3.0
# A different title unchanged this long ends a title wait early.
STUCK_TITLE_SECONDS = 3.0
# Reward overlays dim the whole screen; a settled page's title bar must be at
# least this bright relative to the frame captured before the claim press.
# Measured on the title bar only: claiming changes the page content (an
# emptied mailbox is darker, 42 -> 33 full-frame, 2026-09-26) but not the
# title bar (35.6 -> 35.6), while an overlay drops it about 5x (73.9 -> 14.5).
SETTLED_BRIGHTNESS_RATIO = 0.8
# Title-bar brightness before and after a blind tap counts as unchanged.
SAME_BRIGHTNESS_DELTA = 3.0
SETTLED_CALM_SECONDS = 1.2
CLAIM_BUTTON_GREY_MAX = 170.0
# Tab and card clicks are confirmed by the clicked area changing (frame diff,
# grey thumbnails): a tab that keeps the page title (邮箱's two tabs, the pass
# tabs) gave a stale grey button from the previous tab and "nothing to claim".
CHANGE_THUMB_SIZE = (32, 16)
CHANGE_CELL_DELTA = 18.0
CHANGE_WAIT_SECONDS = 2.0
CHANGE_SETTLE_SECONDS = 2.0
CHANGE_CLICK_ATTEMPTS = 3


def claim_button_dimmed(frame, box) -> bool:
    """True when a claim button reads grey (nothing to claim).

    Live 2K 2026-09-29, pass 全部获得: lit pill median grey 252, disabled 127.
    The OCR box covers the label on the pill, so its median is the pill
    colour.  Anything not clearly grey counts as lit and is pressed.
    """
    if frame is None or box is None:
        return False
    height, width = frame.shape[:2]
    x0 = max(0, int(box.x))
    y0 = max(0, int(box.y))
    x1 = min(width, int(box.x + box.width))
    y1 = min(height, int(box.y + box.height))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return False
    crop = frame[y0:y1, x0:x1, :3]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(np.median(gray)) < CLAIM_BUTTON_GREY_MAX


# Seconds a claim button is looked for before 「跳过」.
CLAIM_BUTTON_WAIT = 3.0


@dataclass(frozen=True)
class ClaimButton:
    """Where to look for a claim button and which text identifies it."""

    roi: tuple[int, int, int, int]
    keywords: tuple[str, ...]


class ClaimPageMixin(TaskVisionMixin):
    """Page helpers for the claim tasks; requires a BaseBD2Task host."""

    claim_log_name = "领取"

    def _claim_default_config(self) -> dict:
        return {
            "启用": True,
            "日常 OCR 阈值": 0.2,
            "主页确认等待秒数": 10.0,
            "页面等待秒数": 15.0,
            "领取结果等待秒数": 10.0,
        }

    def _claim_config_description(self) -> dict:
        return {
            "页面等待秒数": "点击入口后等待页面标题出现的最长时间（含加载）。",
            "领取结果等待秒数": "点击全部领取后，等待奖励弹窗关闭并回到原页面的最长时间。",
        }

    # -- OCR primitives -------------------------------------------------

    def _roi_boxes(self, frame, roi: tuple[int, int, int, int] | None, name: str) -> list:
        """OCR a 1920x1080-reference ROI (or the whole frame) at any 16:9 size.

        Crops are read at 1080p-equivalent scale, the scale the ROIs were
        calibrated at; returned boxes are in full-frame client coordinates.
        """
        vision = self._quick_vision()
        if roi is None:
            return vision.ocr_boxes(frame, name)
        x, y, w, h = roi
        relative = (
            x / REFERENCE_WIDTH,
            y / REFERENCE_HEIGHT,
            (x + w) / REFERENCE_WIDTH,
            (y + h) / REFERENCE_HEIGHT,
        )
        scale = min(1.0, REFERENCE_HEIGHT / max(1, frame.shape[0]))
        return vision.ocr_boxes(
            frame,
            name,
            relative_roi=relative,
            target_height=0,
            ocr_scale=scale,
        )

    def _reference_boxes(self, frame, roi, name) -> list:
        """Like _roi_boxes, but boxes in 1920x1080 reference coordinates."""
        height, width = frame.shape[:2]
        sx, sy = REFERENCE_WIDTH / max(1, width), REFERENCE_HEIGHT / max(1, height)
        return [
            SimpleNamespace(
                name=getattr(box, "name", ""),
                x=float(box.x) * sx,
                y=float(box.y) * sy,
                width=float(box.width) * sx,
                height=float(box.height) * sy,
            )
            for box in self._roi_boxes(frame, roi, name)
            if getattr(box, "x", None) is not None
        ]

    def _wait_boxes(
        self,
        roi,
        name: str,
        ready,
        timeout: float = 4.0,
        interval: float = 0.4,
        reference: bool = False,
    ) -> list:
        """Read ``roi`` until ``ready(boxes)`` holds or ``timeout`` ends.

        One read right after a click or page change failed whole tasks when
        the part read was drawn a moment after the title (live 2K 2026-10-05,
        the bag's 装备制作 button).  Returns the last read either way.
        """
        reader = self._reference_boxes if reference else self._roi_boxes
        end_at = monotonic() + max(0.0, timeout)
        while True:
            boxes = reader(self.capture_frame(), roi, name)
            if ready(boxes) or monotonic() >= end_at:
                return boxes
            self.sleep(interval)

    def _click_reference_box(self, box, after_sleep: float = 0.8) -> None:
        self._click_reference(
            round(box.x + box.width / 2), round(box.y + box.height / 2), after_sleep=after_sleep
        )

    @staticmethod
    def _boxes_text(boxes: list) -> str:
        return " ".join(str(getattr(box, "name", "")) for box in boxes if getattr(box, "name", ""))

    @staticmethod
    def _box_with(boxes: list, keywords: tuple[str, ...]):
        for keyword in keywords:
            wanted = normalize_ocr_text(keyword)
            for box in boxes:
                if wanted and wanted in normalize_ocr_text(getattr(box, "name", "")):
                    return box
        return None

    def _click_box(self, box, after_sleep: float = 0.8) -> None:
        center = self._ocr_box_center(box)
        if center is None:
            return
        width = max(1, int(self.width))
        height = max(1, int(self.height))
        self.operate_click(
            max(0.0, min(1.0, center[0] / width)),
            max(0.0, min(1.0, center[1] / height)),
            after_sleep=after_sleep,
        )

    @staticmethod
    def _frame_brightness(frame) -> float:
        """Mean grey level of the top-left title bar (PAGE_TITLE_ROI)."""
        height, width = frame.shape[:2]
        x, y, w, h = PAGE_TITLE_ROI
        crop = frame[
            round(y / REFERENCE_HEIGHT * height) : round((y + h) / REFERENCE_HEIGHT * height),
            round(x / REFERENCE_WIDTH * width) : round((x + w) / REFERENCE_WIDTH * width),
        ]
        if crop.size == 0:
            return 0.0
        small = cv2.resize(crop, (152, 22), interpolation=cv2.INTER_AREA)
        gray = small if small.ndim == 2 else cv2.cvtColor(small[:, :, :3], cv2.COLOR_BGR2GRAY)
        return float(np.mean(gray))

    @staticmethod
    def _region_thumbs(frame, rois) -> list:
        """Small grey thumbnails of 1920x1080-reference ``rois``."""
        height, width = frame.shape[:2]
        thumbs = []
        for x, y, w, h in rois:
            sx, sy = width / REFERENCE_WIDTH, height / REFERENCE_HEIGHT
            crop = frame[
                max(0, round(y * sy)) : round((y + h) * sy),
                max(0, round(x * sx)) : round((x + w) * sx),
            ]
            if crop.size == 0:
                thumbs.append(None)
                continue
            small = cv2.resize(crop, CHANGE_THUMB_SIZE, interpolation=cv2.INTER_AREA)
            gray = small if small.ndim == 2 else cv2.cvtColor(small[:, :, :3], cv2.COLOR_BGR2GRAY)
            thumbs.append(gray.astype(np.float32))
        return thumbs

    @staticmethod
    def _thumbs_changed(before: list, after: list) -> bool:
        return any(
            a is not None
            and b is not None
            and a.shape == b.shape
            and float(np.max(np.abs(a - b))) >= CHANGE_CELL_DELTA
            for a, b in zip(before, after)
        )

    def _click_until_changed(
        self,
        label: str,
        click,
        rois,
        attempts: int = CHANGE_CLICK_ATTEMPTS,
        wait: float = CHANGE_WAIT_SECONDS,
    ) -> bool:
        """Call ``click`` until one of ``rois`` changes, then let it settle.

        Only for clicks that are harmless to repeat (tabs, list cards): the
        click is repeated only while the frame from before it is still shown.
        False means nothing changed (already selected, or every click lost).
        """
        # Compared with the frame from before the first click: a click that
        # landed late made the retry's own "before" the new page, and the
        # retry then read as unchanged.
        before = self._region_thumbs(self.capture_frame(), rois)
        for attempt in range(1, attempts + 1):
            click()
            end_at = monotonic() + max(0.0, wait)
            while True:
                current = self._region_thumbs(self.capture_frame(), rois)
                if self._thumbs_changed(before, current):
                    self._wait_regions_settled(rois, current)
                    return True
                if monotonic() >= end_at:
                    break
                self.sleep(0.3)
            if attempt < attempts:
                self.log_info(f"{label}：点击后画面未变化，重试点击。")
        return False

    def _wait_regions_settled(self, rois, last: list) -> None:
        """Two agreeing frames, so a button is not read mid-redraw."""
        end_at = monotonic() + CHANGE_SETTLE_SECONDS
        while monotonic() < end_at:
            self.sleep(0.3)
            current = self._region_thumbs(self.capture_frame(), rois)
            if not self._thumbs_changed(last, current):
                return
            last = current

    def _page_title_text(self, frame, name: str) -> str:
        text = self._boxes_text(self._roi_boxes(frame, PAGE_TITLE_ROI, f"{name}标题"))
        self.info_set(f"{name}标题 OCR", text or "-")
        return text

    @staticmethod
    def _title_matches(text: str, title_keywords: tuple[str, ...]) -> bool:
        return keyword_match_count(text, title_keywords, fuzzy_ratio=TITLE_FUZZY_RATIO) >= 1

    def _title_visible(self, frame, title_keywords: tuple[str, ...], name: str) -> bool:
        return self._title_matches(self._page_title_text(frame, name), title_keywords)

    # -- page flow ------------------------------------------------------

    def _open_page_from_home(
        self,
        label: str,
        entry_point: tuple[int, int],
        title_keywords: tuple[str, ...],
    ) -> bool:
        if not self._wait_for_home_confirmation(f"{label}入口前主页确认", timeout=3.0):
            # Started from another page (e.g. a task clicked while the bag
            # was open): go home first instead of failing (2026-09-28).
            from src.tasks.recovery import recover_to_home

            self.log_info(f"{label}：不在主页，先返回主页。")
            if not recover_to_home(self) or not self._wait_for_home_confirmation(
                f"{label}入口前主页确认", timeout=3.0
            ):
                self.log_info(f"{label}：未确认主页，不点击入口。")
                return False
        self._sleep_after_recognition()
        for attempt in range(1, ENTRY_CLICK_ATTEMPTS + 1):
            self.info_set("当前阶段", f"打开{label}（第{attempt}次点击）")
            self._click_reference(*entry_point, after_sleep=0.8)
            if self._wait_for_title(label, title_keywords, timeout=ENTRY_RETRY_SECONDS, quiet=True):
                return True
            # The game sometimes swallows a click on a confirmed home screen;
            # only click again while the home screen is still showing.
            if attempt < ENTRY_CLICK_ATTEMPTS and not self._wait_for_home_confirmation(
                f"{label}重试前主页确认", timeout=2.0
            ):
                break
            self.log_info(f"{label}：入口点击后仍在主页，重试点击。")
        return self._wait_for_title(label, title_keywords)

    def _switch_tab(
        self,
        label: str,
        point: tuple[int, int],
        title_keywords: tuple[str, ...],
        after_sleep: float = 1.0,
    ) -> bool:
        """Click a page tab until its title shows (a re-click on the same tab is harmless)."""
        for _attempt in range(TAB_CLICK_ATTEMPTS):
            self._click_reference(*point, after_sleep=after_sleep)
            if self._wait_for_title(label, title_keywords, timeout=TAB_RETRY_SECONDS, quiet=True):
                return True
            self.log_info(f"{label}：分页点击后标题未出现，重试点击。")
        return self._wait_for_title(label, title_keywords, timeout=2.0)

    def _wait_for_title(
        self,
        label: str,
        title_keywords: tuple[str, ...],
        timeout: float | None = None,
        quiet: bool = False,
    ) -> bool:
        if timeout is None:
            timeout = float(self.config.get("页面等待秒数", 15.0))
        started = monotonic()
        end_at = started + timeout
        last_text, same_since = None, started
        while monotonic() <= end_at:
            frame = self.capture_frame()
            text = self._page_title_text(frame, label)
            if self._title_matches(text, title_keywords):
                return True
            loading = self._match(frame, LOADING_TEMPLATE)
            self.info_set(f"{label} loading", f"{loading.score:.3f}")
            now = monotonic()
            self.info_set("等待页面", f"{label} {now - started:.0f}/{timeout:.0f}秒")
            # Another page's title that stays unchanged means the click went
            # nowhere; waiting the full timeout only looks like a freeze
            # (live 2026-09-27: 17 s on 消耗品).  Loading screens show no title.
            if text != last_text:
                last_text, same_since = text, now
            elif text and now - same_since >= STUCK_TITLE_SECONDS:
                self.log_info(f"{label}：画面停在「{text}」{STUCK_TITLE_SECONDS:.0f}秒未变化，停止等待。")
                break
            self.sleep(0.5)
        if not quiet:
            self.log_info(f"{label}：等待页面标题 {'/'.join(title_keywords)} 超时。")
            self._save_flow_diagnostic(f"{self.claim_log_name}_{label}_title_failed")
        return False

    def _claim_all(
        self,
        label: str,
        button: ClaimButton,
        title_keywords: tuple[str, ...],
    ) -> bool:
        """Press the claim button found by OCR and settle any reward overlay.

        The button may draw (or fade in) a moment after the page or tab
        changed: a missing button is looked for up to ``CLAIM_BUTTON_WAIT``
        seconds, a grey one is looked at once more before it counts as grey.
        """
        end_at = monotonic() + CLAIM_BUTTON_WAIT
        grey_looks = 0
        while True:
            frame = self.capture_frame()
            boxes = self._roi_boxes(frame, button.roi, f"{label}按钮")
            target = self._box_with(boxes, button.keywords)
            if target is not None and claim_button_dimmed(frame, target):
                grey_looks += 1
                if grey_looks >= 2:
                    break
            elif target is not None or monotonic() >= end_at:
                break
            self.sleep(0.6)
        self.info_set(f"{label}按钮 OCR", self._boxes_text(boxes) or "-")
        if target is None:
            self.log_info(f"{label}：未找到 {'/'.join(button.keywords)} 按钮，跳过。")
            return True
        if claim_button_dimmed(frame, target):
            # Grey = nothing to claim (Leo 2026-09-29): pressing it and then
            # proving the page settled cost ~5 s per button.
            self.info_set(f"{label}结果", "按钮未亮起，无可领取")
            self.log_info(f"{label}：按钮未亮起，无可领取，跳过。")
            return True
        baseline = self._frame_brightness(frame)
        self._sleep_after_recognition()
        self.info_set("当前阶段", f"{label}：点击领取")

        def still_lit() -> bool:
            # A swallowed press leaves the page as it was; a claim greys the
            # button or covers it with the reward popup.
            now = self.capture_frame()
            boxes = self._roi_boxes(now, button.roi, f"{label}按钮")
            found = self._box_with(boxes, button.keywords)
            return found is not None and not claim_button_dimmed(now, found)

        outcome = self.press_and_confirm(
            label,
            lambda: self._click_box(target, after_sleep=1.0),
            lambda: not still_lit(),
            still_before=still_lit,
        )
        if not outcome:
            self.info_set(f"{label}结果", "按钮一直亮着，未领到")
            self.log_info(f"{label}：按了领取，按钮一直亮着，没有领到。")
            self._save_flow_diagnostic(f"{self.claim_log_name}_{label}_claim_unconfirmed")
            return False
        return self._settle_after_claim(label, title_keywords, baseline)

    def _save_reward_picture(self, frame) -> None:
        """Keep the reward popup for the 跑完的结算 page (mail only so far)."""
        kind = getattr(self, "report_picture_kind", None)
        if not kind:
            return
        from src.tasks import run_report

        run_report.save_picture(frame, kind)

    def _settle_after_claim(
        self,
        label: str,
        title_keywords: tuple[str, ...],
        baseline_brightness: float,
    ) -> bool:
        end_at = monotonic() + float(self.config.get("领取结果等待秒数", 10.0))
        stable_frames = 0
        unknown_frames = 0
        blind_taps = 0
        handled = 0
        tapped_brightness = None
        calm_since = monotonic()
        while monotonic() <= end_at:
            frame = self.capture_frame()
            boxes = self._roi_boxes(frame, None, f"{label}结果")
            text = self._boxes_text(boxes)
            self.info_set(f"{label}结果 OCR", text[:120] or "-")

            dismiss = self._box_with(boxes, OVERLAY_DISMISS_KEYWORDS)
            if dismiss is not None:
                self._save_reward_picture(frame)
                self.log_info(f"{label}：关闭奖励弹窗（{getattr(dismiss, 'name', '')}）。")
                self._click_box(dismiss, after_sleep=0.8)
                stable_frames = unknown_frames = 0
                handled += 1
                continue
            if keyword_match_count(text, REWARD_DIALOG_TITLES) >= 1:
                confirm = self._box_with(boxes, (CONFIRM_TEXT,))
                if confirm is not None:
                    self._save_reward_picture(frame)
                    self.log_info(f"{label}：确认奖励弹窗。")
                    self._click_box(confirm, after_sleep=0.8)
                    stable_frames = unknown_frames = 0
                    handled += 1
                    continue

            brightness = self._frame_brightness(frame)
            self.info_set(f"{label}亮度", f"{brightness:.0f}/{baseline_brightness:.0f}")
            dimmed = brightness < baseline_brightness * SETTLED_BRIGHTNESS_RATIO
            title_visible = self._title_visible(frame, title_keywords, label)
            if (
                dimmed
                and title_visible
                and tapped_brightness is not None
                and abs(brightness - tapped_brightness) <= SAME_BRIGHTNESS_DELTA
            ):
                # The blind tap changed nothing, so nothing covers the page:
                # the baseline was lit by a toast ("通行证达到10级！" over the
                # title bar, live 2K 2026-09-29) that has faded since.
                baseline_brightness = brightness
                dimmed = False
            if title_visible and not dimmed:
                unknown_frames = 0
                stable_frames += 1
                if stable_frames == 1:
                    calm_since = monotonic()
                # About 1.5 s of calm frames rules out an overlay still
                # animating in.  Counted in time, not frames: each full-frame
                # read takes ~1 s at 2K, so three frames took 4.5 s per claim.
                if stable_frames >= 2 and monotonic() - calm_since >= SETTLED_CALM_SECONDS:
                    result = "已领取" if handled else "无新奖励或已直接领取"
                    self.info_set(f"{label}结果", result)
                    self.log_info(f"{label}：{result}。")
                    return True
            else:
                stable_frames = 0
                unknown_frames += 1
                if unknown_frames >= 3 and blind_taps < 3:
                    # Unrecognised overlay: tap the empty top bar to close it.
                    self.log_info(f"{label}：出现未识别弹窗，点击空白处关闭。")
                    tapped_brightness = brightness
                    self._click_reference(*OVERLAY_TAP_POINT, after_sleep=0.8)
                    blind_taps += 1
                    handled += 1
                    unknown_frames = 0
                    continue
            self.sleep(0.5)

        self.log_info(f"{label}：领取后未能回到页面。")
        self._save_flow_diagnostic(f"{self.claim_log_name}_{label}_settle_failed")
        return False

    def _leave_to_home(self, label: str, title_keywords: tuple[str, ...]) -> bool:
        for attempt in range(1, 4):
            self.info_set("当前阶段", f"{label}：返回主页")
            self._click_reference(*BACK_BUTTON_POINT, after_sleep=1.0)
            if self._wait_for_home_confirmation(f"{label}返回主页", timeout=5.0):
                return True
            if not self._title_visible(self.capture_frame(), title_keywords, label):
                # Left the page but home is not confirmed yet: usually a
                # loading screen, so give it time instead of failing.
                if self._wait_for_home_confirmation(f"{label}返回主页", timeout=15.0):
                    return True
                break
            self.log_info(f"{label}：第{attempt}次返回未生效，重试。")
        self.log_info(f"{label}：未能确认返回主页。")
        self._save_flow_diagnostic(f"{self.claim_log_name}_{label}_home_failed")
        return False

    def _claim_fail(self, stage: str) -> bool:
        # 失败必须写进状态，否则 run_history 会把本次运行记成成功。
        self.info_set("状态", f"{self.name}：{stage}失败。")
        return False
