"""Mail, mission-reward and pass-reward claim tasks (日常收尾).

Entry points and page layouts were calibrated on the 简体 client, 2026-09-25;
see ``claim_page`` for the shared page flow.
"""

from __future__ import annotations

from qfluentwidgets import FluentIcon

from src.tasks import run_report
from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.claim_page import (
    CLAIM_GREY,
    CLAIM_NO_BUTTON,
    CLAIM_PRESSED,
    ClaimButton,
    ClaimPageMixin,
    find_red_badges,
)
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT
from src.utils.chinese import to_simplified
from src.utils.ocr_utils import keyword_match_count

# Shared left-hand tab positions on the mail and mission pages.
FIRST_TAB_POINT = (285, 151)
SECOND_TAB_POINT = (285, 221)
BOTTOM_CLAIM_ROI = (1200, 930, 720, 150)

MAIL_ENTRY_POINT = (1606, 57)
MAIL_TITLE_KEYWORDS = ("邮箱",)
MAIL_CLAIM_BUTTON = ClaimButton(BOTTOM_CLAIM_ROI, ("全部领取",))
# Both mail tabs keep the 邮箱 title, so the switch is confirmed by the
# second tab's highlight (or the claim button) changing.
MAIL_SECOND_TAB_ROI = (155, 186, 260, 70)

MISSION_ENTRY_POINT = (681, 985)
MISSION_TITLE_KEYWORDS = ("任务",)
DAILY_MISSION_TITLE = ("每日任务",)
WEEKLY_MISSION_TITLE = ("每周任务",)
MISSION_CLAIM_BUTTON = ClaimButton(BOTTOM_CLAIM_ROI, ("全部获得", "全部领取"))

PASS_ENTRY_POINT = (1659, 262)
PASS_TITLE_KEYWORDS = ("通行证",)
# Left column listing every active pass card (each caption ends in 通行证);
# three show at once, a fourth sits below them or after scrolling.
PASS_LIST_EXTENDED_ROI = (315, 265, 220, 440)
PASS_LIST_SCROLL_POINT = (425 / 1920, 430 / 1080)
PASS_LIST_SCROLL_ROUNDS = 2
# A caption containing this is a purchase control, never a pass card.
PASS_PURCHASE_KEYWORDS = ("购买",)
# Leo 2026-10-19: like 活动, a pass to claim carries a red ◆「!」 at its card's
# top-right corner.  The pass list is the 活动 list's widget (same x, ~107 px
# a card); the strip is a little wider and starts higher until a 4K frame of
# a badged pass pins it.
PASS_BADGE_STRIP = (490, 225, 50, 520)
PASS_BADGE_TO_CARD_CENTER = 34
PASS_CARD_X = 425
# Around the pressed card: its highlight changes when it is selected.
PASS_CARD_HALF_SIZE = (110, 50)
# Only the right half of the panel: the purchase button sits at (729, 765).
PASS_CLAIM_BUTTON = ClaimButton((1150, 700, 450, 130), ("全部获得", "全部领取"))
# Fallbacks for a badged pass whose 全部获得 was missing or grey (player
# 2026-10-26: 角色通行证 never claimed, the task still 完成): the panel right
# of 购买等级 (580-880), then the tabs on the panel's right edge that carry a
# red ◆!.  Tab badge measured on the 10-13 live 1080p pass page: y 658 over
# the 任务 tab (1593, 680).
PASS_CLAIM_BUTTON_WIDE = ClaimButton((930, 560, 700, 300), ("全部获得", "全部领取"))
PASS_TAB_BADGE_STRIP = (1596, 240, 44, 540)
PASS_TAB_POINTS = ((1593, 403), (1593, 680))
PASS_MISS_REASONS = {
    CLAIM_NO_BUTTON: "打开后没看到「全部获得」按钮",
    CLAIM_GREY: "「全部获得」是灰的，游戏里没有可领的",
}
PASS_MAX_CARDS = 6
# A pass opened this many times and still badged is left (its badge is for
# something 全部获得 does not claim).
PASS_MAX_VISITS = 2


class _ClaimTaskBase(ClaimPageMixin, BaseBD2Task):
    recover_home_on_failure = True
    frozen_retry = True
    start_from_home = True
    vision_threshold_key = "加载页面阈值"
    ocr_threshold_key = "日常 OCR 阈值"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.visible = True
        self._init_vision_state()
        self.default_config.update(self._claim_default_config())
        self.config_description.update(self._claim_config_description())

    def run(self):
        if not bool(self.config.get("启用", True)):
            self.info_set("状态", f"{self.name}已禁用。")
            return True
        self.info_set("状态", f"启动{self.name}。")
        if not self.run_claim():
            return False
        self.info_set("状态", f"{self.name}完成。")
        self.log_completion(f"{self.name}：流程完成。")
        return True

    def run_claim(self) -> bool:
        raise NotImplementedError


class MailRewardTask(_ClaimTaskBase):
    claim_log_name = "mail"
    # The reward popups go to the 跑完的结算 page's 邮件领到的.
    report_picture_kind = "mail"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "领取邮件"
        self.description = "打开邮箱，一键领取普通邮箱（可选商品邮箱）的全部邮件。"
        self.icon = FluentIcon.MAIL
        self.default_config["领取商品邮箱"] = True
        self.config_description["领取商品邮箱"] = (
            "同时领取商品邮箱（购买的礼包等）。"
        )

    def run_claim(self) -> bool:
        if not self._open_page_from_home("邮箱", MAIL_ENTRY_POINT, MAIL_TITLE_KEYWORDS):
            return self._claim_fail("打开邮箱")
        if not self._claim_all("普通邮箱", MAIL_CLAIM_BUTTON, MAIL_TITLE_KEYWORDS):
            return self._claim_fail("领取普通邮箱")
        if bool(self.config.get("领取商品邮箱", True)):
            switched = self._click_until_changed(
                "商品邮箱",
                lambda: self._click_reference(*SECOND_TAB_POINT, after_sleep=0.2),
                (MAIL_SECOND_TAB_ROI, MAIL_CLAIM_BUTTON.roi),
                wait=1.5,
            )
            if not switched:
                self.log_info("商品邮箱：分页点击后画面一直未变化，按已在商品邮箱处理。")
            if not self._claim_all("商品邮箱", MAIL_CLAIM_BUTTON, MAIL_TITLE_KEYWORDS):
                return self._claim_fail("领取商品邮箱")
        if not self._leave_to_home("邮箱", MAIL_TITLE_KEYWORDS):
            return self._claim_fail("邮箱返回主页")
        return True


class MissionRewardTask(_ClaimTaskBase):
    claim_log_name = "mission"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "领取任务奖励"
        self.description = "打开任务页，一键领取每日任务与每周任务的全部奖励。"
        self.icon = FluentIcon.ACCEPT
        self.default_config["领取每周任务"] = True
        self.config_description["领取每周任务"] = "领完每日任务后切到每周任务页再领取一次。"

    def run_claim(self) -> bool:
        if not self._open_page_from_home("任务", MISSION_ENTRY_POINT, MISSION_TITLE_KEYWORDS):
            return self._claim_fail("打开任务页")
        if not self._switch_tab("每日任务", FIRST_TAB_POINT, DAILY_MISSION_TITLE):
            return self._claim_fail("切换每日任务")
        if not self._claim_all("每日任务", MISSION_CLAIM_BUTTON, DAILY_MISSION_TITLE):
            return self._claim_fail("领取每日任务")
        if bool(self.config.get("领取每周任务", True)):
            if not self._switch_tab("每周任务", SECOND_TAB_POINT, WEEKLY_MISSION_TITLE):
                return self._claim_fail("切换每周任务")
            if not self._claim_all("每周任务", MISSION_CLAIM_BUTTON, WEEKLY_MISSION_TITLE):
                return self._claim_fail("领取每周任务")
        if not self._leave_to_home("任务", MISSION_TITLE_KEYWORDS):
            return self._claim_fail("任务页返回主页")
        return True


class PassRewardTask(_ClaimTaskBase):
    """Leo 2026-10-19: open only the passes with a red 「!」 on the left, press
    全部获得 once on each (one press now claims mission experience and level
    rewards together), and look at the list again after every claim.  No
    second round from the top like 活动."""

    claim_log_name = "pass"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "领取通行证"
        self.description = "依次打开左侧有红点的通行证，每张点一次全部获得（绝不点购买）。"
        self.icon = FluentIcon.TAG

    def run_claim(self) -> bool:
        if not self._open_page_from_home("通行证", PASS_ENTRY_POINT, PASS_TITLE_KEYWORDS):
            return self._claim_fail("打开通行证")
        self._pass_cards()  # the captions go to the run info
        skipped: dict[str, str] = {}
        visits: dict[str, int] = {}
        self._pass_misses: dict[str, str] = {}
        claimed = 0
        scrolls = 0
        for _step in range(PASS_MAX_CARDS * PASS_MAX_VISITS + PASS_LIST_SCROLL_ROUNDS + 1):
            frame = self.capture_frame()
            target = self._next_pass_badge(frame, skipped)
            if target is None:
                if scrolls >= PASS_LIST_SCROLL_ROUNDS:
                    break
                scrolls += 1
                self.info_set("当前阶段", "通行证：向下滚动列表查找更多红点")
                self.scroll_client(
                    PASS_LIST_SCROLL_POINT, -1, count=3, interval=0.05, after_sleep=0.8
                )
                continue
            badge_y, caption = target
            key = caption or f"y{badge_y}"
            visits[key] = visits.get(key, 0) + 1
            if visits[key] > PASS_MAX_VISITS:
                skipped[key] = self._pass_misses.get(key, "点了两次「全部获得」红点还在")
                self.log_info(f"通行证「{key}」：{skipped[key]}，跳过。")
                continue
            if not self._claim_badged_pass(key, badge_y):
                return self._claim_fail(f"领取{key}")
            claimed += 1
        self.info_set("通行证数量", claimed)
        if not claimed and not skipped:
            # Said in the run report too: a pass the game shows as claimable
            # but read without a badge is told, not a silent 完成.
            self.log_info("通行证：左侧通行证都没有红点（没有可领的）。")
            run_report.add_current_note("左侧通行证都没有红点，没有可领的")
        if skipped:
            left = "、".join(f"「{key}」{why}" for key, why in skipped.items())
            self.log_warning(f"通行证：这些有红点但没领到：{left}。")
            run_report.add_current_note(f"有红点但没领到：{left}")
        if not self._leave_to_home("通行证", PASS_TITLE_KEYWORDS):
            return self._claim_fail("通行证返回主页")
        return True

    @staticmethod
    def _pass_caption_boxes(boxes: list) -> list:
        return [
            box
            for box in boxes
            if keyword_match_count(getattr(box, "name", ""), PASS_TITLE_KEYWORDS) >= 1
            and keyword_match_count(getattr(box, "name", ""), PASS_PURCHASE_KEYWORDS) == 0
        ]

    def _pass_cards(
        self, roi: tuple[int, int, int, int] = PASS_LIST_EXTENDED_ROI, wait: float = 4.0
    ) -> list[str]:
        boxes = self._wait_boxes(
            roi, "通行证列表", lambda found: bool(self._pass_caption_boxes(found)), timeout=wait
        )
        captions = [str(getattr(box, "name", "")) for box in self._pass_caption_boxes(boxes)]
        self.info_set("通行证列表", "、".join(captions) or "-")
        return captions[:PASS_MAX_CARDS]

    def _next_pass_badge(self, frame, skipped: dict[str, str]):
        """(badge y, caption) of the first badged pass not skipped, or None."""
        badges = find_red_badges(frame, PASS_BADGE_STRIP)
        self.info_set("通行证红点", ",".join(str(y) for y in badges) or "-")
        if not badges:
            return None
        boxes = self._pass_caption_boxes(
            self._roi_boxes(frame, PASS_LIST_EXTENDED_ROI, "通行证列表")
        )
        for badge_y in badges:
            caption = self._pass_caption_near(frame, boxes, badge_y)
            if (caption or f"y{badge_y}") not in skipped:
                return badge_y, caption
        return None

    @staticmethod
    def _pass_caption_near(frame, boxes: list, badge_y: int) -> str:
        """Simplified caption of the card under the badge (its nearest below)."""
        height = frame.shape[0] if frame is not None else REFERENCE_HEIGHT
        sy = REFERENCE_HEIGHT / max(1, height)
        best, best_gap = "", None
        for box in boxes:
            center = (float(box.y) + float(box.height) / 2) * sy
            gap = center - badge_y
            if 0 <= gap <= 100 and (best_gap is None or gap < best_gap):
                best, best_gap = to_simplified(str(getattr(box, "name", ""))), gap
        return best

    def _claim_badged_pass(self, key: str, badge_y: int) -> bool:
        self.info_set("当前阶段", f"打开通行证：{key}")
        card_y = badge_y + PASS_BADGE_TO_CARD_CENTER
        half_w, half_h = PASS_CARD_HALF_SIZE
        card_roi = (PASS_CARD_X - half_w, max(0, card_y - half_h), 2 * half_w, 2 * half_h)
        changed = self._click_until_changed(
            f"通行证 {key}",
            lambda: self._click_reference(PASS_CARD_X, card_y, after_sleep=0.2),
            (card_roi, PASS_CLAIM_BUTTON.roi),
            attempts=2,
            wait=1.2,
        )
        if not changed:
            # The selected card (the top one on entry) changes nothing when
            # pressed.  If the press was lost instead, the previous pass's
            # button is grey and nothing is pressed; the badge stays and the
            # card is opened again on the next look.
            self.log_info(f"通行证「{key}」：点了画面没变化，按已打开处理。")
        self._claim_outcome = None
        if not self._claim_all(key, PASS_CLAIM_BUTTON, PASS_TITLE_KEYWORDS):
            return False
        return self._claim_pass_elsewhere(key)

    def _claim_pass_elsewhere(self, key: str) -> bool:
        """The badged pass's 全部获得 was missing or grey: look on the whole
        panel, then open each red-badged tab on its right and claim there.
        What still was not claimed is kept for the run's 没领到 line."""
        first = getattr(self, "_claim_outcome", None)
        if first in (None, CLAIM_PRESSED):
            return True
        if first == CLAIM_NO_BUTTON:
            claimed = self._claim_pass_at(key, ((PASS_CLAIM_BUTTON_WIDE, "整块面板"),), first)
            if claimed is not None:
                return claimed
        for tab in self._badged_pass_tabs(self.capture_frame()):
            self.info_set("当前阶段", f"通行证「{key}」：打开右侧有红点的分页")
            self._click_reference(*tab, after_sleep=1.0)  # 不用确认：分页，下面的按钮会再读
            claimed = self._claim_pass_at(
                key,
                ((PASS_CLAIM_BUTTON, "右侧分页"), (PASS_CLAIM_BUTTON_WIDE, "右侧分页整块面板")),
                first,
            )
            if claimed is not None:
                return claimed
        self._pass_misses[key] = PASS_MISS_REASONS[first]
        return True

    def _claim_pass_at(self, key: str, buttons, first: str) -> bool | None:
        """True = claimed, False = the claim failed, None = nothing to press here."""
        for button, where in buttons:
            self.log_info(f"通行证「{key}」：{PASS_MISS_REASONS[first]}，改在{where}找。")
            if not self._claim_all(f"{key}（{where}）", button, PASS_TITLE_KEYWORDS):
                return False
            if self._claim_outcome == CLAIM_PRESSED:
                self._pass_misses.pop(key, None)
                return True
            if self._claim_outcome == CLAIM_GREY:
                break  # found it, grey: the wider look adds nothing
        return None

    @staticmethod
    def _badged_pass_tabs(frame) -> list[tuple[int, int]]:
        """The tabs on the panel's right edge under a red ◆!, top first."""
        tabs: list[tuple[int, int]] = []
        for badge_y in find_red_badges(frame, PASS_TAB_BADGE_STRIP):
            tab = min(PASS_TAB_POINTS, key=lambda point: abs(point[1] - badge_y))
            if tab not in tabs:
                tabs.append(tab)
        return tabs
