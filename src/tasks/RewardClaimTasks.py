"""Mail, mission-reward and pass-reward claim tasks (日常收尾).

Entry points and page layouts were calibrated on the 简体 client, 2026-09-25;
see ``claim_page`` for the shared page flow.
"""

from __future__ import annotations

from qfluentwidgets import FluentIcon

from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.claim_page import ClaimButton, ClaimPageMixin
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils.chinese import to_simplified
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text

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
# Left column listing every active pass card (each caption ends in 通行证).
PASS_LIST_ROI = (315, 265, 220, 330)
# The list shows three cards (~107 px apart); a fourth pass sits in the slot
# below PASS_LIST_ROI or only appears after scrolling the list down.
PASS_LIST_EXTENDED_ROI = (315, 265, 220, 440)
PASS_LIST_SCROLL_POINT = (425 / 1920, 430 / 1080)
PASS_LIST_SCROLL_ROUNDS = 2
# A caption containing this is a purchase control, never a pass card.
PASS_PURCHASE_KEYWORDS = ("购买",)
PASS_REWARD_TAB_POINT = (1593, 403)
PASS_MISSION_TAB_POINT = (1593, 680)
# Area around a pass tab whose highlight changes when it is selected.
PASS_TAB_HALF_SIZE = (100, 40)
# Around a card's caption: the selected card's highlight.
PASS_CARD_MARGIN = (20, 35)
# Only the right half of the panel: the purchase button sits at (729, 765).
PASS_CLAIM_BUTTON = ClaimButton((1150, 700, 450, 130), ("全部获得", "全部领取"))
PASS_MAX_CARDS = 6


class _ClaimTaskBase(ClaimPageMixin, BaseBD2Task):
    recover_home_on_failure = True
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
        self.default_config["领取商品邮箱"] = False
        self.config_description["领取商品邮箱"] = (
            "同时领取商品邮箱（购买的礼包等）。默认只领普通邮箱。"
        )

    def run_claim(self) -> bool:
        if not self._open_page_from_home("邮箱", MAIL_ENTRY_POINT, MAIL_TITLE_KEYWORDS):
            return self._claim_fail("打开邮箱")
        if not self._claim_all("普通邮箱", MAIL_CLAIM_BUTTON, MAIL_TITLE_KEYWORDS):
            return self._claim_fail("领取普通邮箱")
        if bool(self.config.get("领取商品邮箱", False)):
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
    claim_log_name = "pass"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "领取通行证"
        self.description = (
            "依次打开每张通行证，领取通行证任务经验与等级奖励（只点全部获得，绝不点购买）。"
        )
        self.icon = FluentIcon.TAG

    def run_claim(self) -> bool:
        if not self._open_page_from_home("通行证", PASS_ENTRY_POINT, PASS_TITLE_KEYWORDS):
            return self._claim_fail("打开通行证")
        cards = self._pass_cards()
        self.info_set("通行证数量", len(cards))
        if not cards:
            self.log_info("通行证：左侧列表未识别到任何通行证。")
            return self._claim_fail("识别通行证列表")
        handled: list[str] = []
        failed = self._claim_passes(cards, handled, PASS_LIST_ROI)
        if failed is None:
            failed = self._claim_more_passes(handled)
        if failed is not None:
            return self._claim_fail(f"领取{failed}")
        self.info_set("通行证数量", len(handled))
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
        self, roi: tuple[int, int, int, int] = PASS_LIST_ROI, wait: float = 4.0
    ) -> list[str]:
        boxes = self._wait_boxes(
            roi, "通行证列表", lambda found: bool(self._pass_caption_boxes(found)), timeout=wait
        )
        captions = [str(getattr(box, "name", "")) for box in self._pass_caption_boxes(boxes)]
        self.info_set("通行证列表", "、".join(captions) or "-")
        return captions[:PASS_MAX_CARDS]

    @staticmethod
    def _pass_handled(caption: str, handled: list[str]) -> bool:
        # Exact match only: passes can differ by a single character (e.g. an
        # issue number), and re-claiming a pass is harmless while skipping a
        # new one is not.
        # OCR sometimes returns a Traditional glyph ("滿月" for 满月, live 2K
        # 2026-09-29), which claimed the same pass twice.
        wanted = normalize_ocr_text(to_simplified(caption))
        return any(normalize_ocr_text(to_simplified(done)) == wanted for done in handled)

    def _claim_passes(
        self,
        cards: list[str],
        handled: list[str],
        roi: tuple[int, int, int, int],
    ) -> str | None:
        """Claim every card not handled yet; returns the caption that failed."""
        for position, caption in enumerate(cards):
            if len(handled) >= PASS_MAX_CARDS:
                break
            if self._pass_handled(caption, handled):
                continue
            opened = self._claim_one_pass(len(handled) + 1, caption, roi=roi, position=position)
            if not opened:
                return caption
            # Only the card actually opened counts as handled: a misread
            # caption opened by position stays open for the next scan.
            if not self._pass_handled(opened, handled):
                handled.append(opened)
        return None

    def _claim_more_passes(self, handled: list[str]) -> str | None:
        """Look below the visible cards for more passes and claim them."""
        for round_index in range(PASS_LIST_SCROLL_ROUNDS + 1):
            if len(handled) >= PASS_MAX_CARDS:
                return None
            if round_index:
                self.info_set("当前阶段", "通行证：向下滚动列表查找更多通行证")
                self.scroll_client(
                    PASS_LIST_SCROLL_POINT, -1, count=3, interval=0.05, after_sleep=0.8
                )
            cards = self._pass_cards(PASS_LIST_EXTENDED_ROI, wait=1.5)
            new = [caption for caption in cards if not self._pass_handled(caption, handled)]
            if not new:
                if round_index:
                    # Scrolled and nothing new appeared: the list has ended.
                    return None
                continue
            self.log_info(f"通行证：发现更多通行证：{'、'.join(new)}。")
            failed = self._claim_passes(cards, handled, PASS_LIST_EXTENDED_ROI)
            if failed is not None:
                return failed
        return None

    def _claim_one_pass(
        self,
        index: int,
        caption: str,
        roi: tuple[int, int, int, int] = PASS_LIST_ROI,
        position: int | None = None,
    ) -> str | None:
        """Claim one card; returns the caption of the card opened, or None."""
        # Re-read the list each time: the highlighted card changes its layout.
        frame = self.capture_frame()
        boxes = self._roi_boxes(frame, roi, "通行证列表")
        cards = self._pass_caption_boxes(boxes)
        target = self._box_with(cards, (caption,))
        opened = caption
        if target is None:
            # OCR may read the caption slightly differently; fall back to order.
            order = index - 1 if position is None else position
            target = cards[order] if 0 <= order < len(cards) else None
            if target is not None:
                opened = str(getattr(target, "name", ""))
                self.log_info(f"通行证：按位置打开「{opened}」，未确认就是「{caption}」。")
        if target is None:
            self.log_info(f"通行证：列表中找不到「{caption}」。")
            return None
        self.info_set("当前阶段", f"通行证 {index}：{opened}")
        tab_rois = tuple(
            self._pass_tab_roi(point) for point in (PASS_MISSION_TAB_POINT, PASS_REWARD_TAB_POINT)
        )
        changed = self._click_until_changed(
            f"通行证 {opened}",
            lambda: self._click_box(target, after_sleep=0.2),
            (self._pass_card_roi(frame, target), PASS_CLAIM_BUTTON.roi) + tab_rois,
            attempts=2,
            wait=1.2,
        )
        # The top card is already selected on entry, so "unchanged" is normal
        # for the first card pressed.  Any other card that changed nothing was
        # not opened: claiming now would claim the previous pass again.
        if not changed and not (index == 1 and target is cards[0]):
            self.log_info(f"通行证：点了「{opened}」画面一直没变化，没有打开，不领取。")
            self._save_flow_diagnostic(f"{self.claim_log_name}_{opened}_card_failed")
            return None
        # Mission experience first so the level rewards it unlocks are claimed too.
        tabs = (("任务", PASS_MISSION_TAB_POINT), ("奖励", PASS_REWARD_TAB_POINT))
        for tab_name, tab_point in tabs:
            label = f"{opened}{tab_name}"
            switched = self._click_until_changed(
                label,
                lambda point=tab_point: self._click_reference(*point, after_sleep=0.2),
                (self._pass_tab_roi(tab_point), PASS_CLAIM_BUTTON.roi),
                attempts=2,
                wait=1.0,
            )
            if not switched:
                self.log_info(f"{label}：分页点击后画面未变化，按已在该分页处理。")
            if not self._claim_all(label, PASS_CLAIM_BUTTON, PASS_TITLE_KEYWORDS):
                return None
        return opened

    @staticmethod
    def _pass_tab_roi(point: tuple[int, int]) -> tuple[int, int, int, int]:
        half_w, half_h = PASS_TAB_HALF_SIZE
        return (point[0] - half_w, point[1] - half_h, 2 * half_w, 2 * half_h)

    @staticmethod
    def _pass_card_roi(frame, box) -> tuple[int, int, int, int]:
        """The caption box (full-frame pixels) grown to its card, in reference units."""
        height, width = frame.shape[:2]
        sx, sy = REFERENCE_WIDTH / max(1, width), REFERENCE_HEIGHT / max(1, height)
        margin_x, margin_y = PASS_CARD_MARGIN
        x = max(0, round(float(box.x) * sx) - margin_x)
        y = max(0, round(float(box.y) * sy) - margin_y)
        return (
            x,
            y,
            round(float(box.width) * sx) + 2 * margin_x,
            round(float(box.height) * sy) + 2 * margin_y,
        )
