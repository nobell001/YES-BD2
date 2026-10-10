"""Collect the restaurant regulars' sacred stones (领常客圣石).

Calibrated on the 简体 client, 2026-09-26: home → 经营管理 popup → the
restaurant row's 立刻前往 → 格鲁菲餐厅 → 常客.  When regulars carry gifts,
pressing 常客 collects them all at once and toasts "火圣石×30", "暗圣石×8"…
on the left; without gifts it only pans the camera, which is harmless.
"""

from __future__ import annotations

from time import monotonic

from qfluentwidgets import FluentIcon

from src.tasks.recovery import recover_to_home
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.utils.ocr_utils import keyword_match_count

BUSINESS_ENTRY_POINT = (165, 262)
BUSINESS_POPUP_ROI = (650, 240, 640, 110)
BUSINESS_POPUP_KEYWORDS = ("餐馆营业额现状", "立刻前往")
# The whole popup, read when the restaurant row was not: the popup grows with
# account progress, so its rows move (see DailyTask's 一键收菜).
BUSINESS_POPUP_WIDE_ROI = (480, 80, 960, 980)
BUSINESS_POPUP_WIDE_KEYWORDS = ("餐馆营业额现状", "渔笼收获情况", "助手工作情况", "一键获得")
RESTAURANT_GO_ROI = (1040, 250, 240, 70)
RESTAURANT_TITLE = ("格鲁菲餐厅",)
REGULARS_POINT = (273, 285)
STONE_TOAST_ROI = (170, 440, 520, 260)
STONE_TEXT = "圣石"
POPUP_CLICK_ATTEMPTS = 3
GO_BUTTON_WAIT_SECONDS = 2.0
# Polled after the press's 0.8 s pause.  Logs 2026-09-27..10-04 (4K): the
# toast was first read 2.0-2.1 s after the press every time; with nothing to
# collect the old 5 s wait was what Leo saw as a stall (10-05).
STONE_TOAST_WAIT_SECONDS = 3.0


class RestaurantStoneTask(_ClaimTaskBase):
    claim_log_name = "restaurant"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "领取常客圣石"
        self.description = "经营管理 → 前往格鲁菲餐厅 → 点「常客」一次领取常客带来的圣石。"
        self.icon = FluentIcon.SHOPPING_CART

    def run_claim(self) -> bool:
        if not self._wait_for_home_confirmation("常客圣石入口前主页确认"):
            return self._claim_fail("确认主页")
        if not self._open_business_popup():
            return self._claim_fail("打开经营管理")
        if not self._go_to_restaurant():
            recover_to_home(self)
            return self._claim_fail("前往餐厅")
        self._sleep_after_recognition()
        self.info_set("当前阶段", "点击常客")
        toast = [""]

        def stone_toast() -> bool:
            toast[0] = self._stone_toast_text()
            return keyword_match_count(toast[0], (STONE_TEXT,)) >= 1

        # No toast is also what a lost press shows, so 常客 is pressed once
        # more while the restaurant is still up (harmless: without gifts it
        # only pans the camera) before it counts as nothing to collect.
        outcome = self.press_and_confirm(
            "领取常客圣石：常客",
            lambda: self._click_reference(*REGULARS_POINT, after_sleep=0.8),
            stone_toast,
            still_before=self._in_restaurant,
            timeout=STONE_TOAST_WAIT_SECONDS,
        )
        if outcome:
            self.info_set("常客圣石结果", "已领取")
            self.log_info(f"领取常客圣石：已领取（{toast[0]}）。")
        elif outcome.presses >= 2:
            self.info_set("常客圣石结果", "按了两次常客都没有圣石，今天没有可领的")
            self.log_info("领取常客圣石：按了两次「常客」都没有看到圣石提示，今天没有可领的圣石。")
        else:
            self.info_set("常客圣石结果", "未确认领取")
            self.log_warning("领取常客圣石：按了「常客」后不在餐厅画面，没确认领取，下次再试。")
            recover_to_home(self)
            return self._claim_fail("领取常客圣石")
        if not recover_to_home(self):
            return self._claim_fail("餐厅返回主页")
        return True

    def _in_restaurant(self) -> bool:
        return self._title_visible(self.capture_frame(), RESTAURANT_TITLE, "餐厅")

    def _stone_toast_text(self) -> str:
        toast = self._boxes_text(self._roi_boxes(self.capture_frame(), STONE_TOAST_ROI, "圣石"))
        self.info_set("常客圣石 OCR", toast or "-")
        return toast

    def _popup_text(self) -> str:
        boxes = self._roi_boxes(self.capture_frame(), BUSINESS_POPUP_ROI, "经营管理")
        return self._boxes_text(boxes)

    def _popup_open(self) -> bool:
        if keyword_match_count(self._popup_text(), BUSINESS_POPUP_KEYWORDS) >= 2:
            return True
        boxes = self._roi_boxes(self.capture_frame(), BUSINESS_POPUP_WIDE_ROI, "经营管理整窗")
        return keyword_match_count(self._boxes_text(boxes), BUSINESS_POPUP_WIDE_KEYWORDS) >= 2

    def _home_without_taps(self, timeout: float) -> bool:
        """Home on screen, only read.

        The shared home check taps the left column to clear a login notice
        when home reads dimmed, and an open 经营管理 popup dims home too: with
        the popup up but not read, that tap could open something else (live
        4K 2026-10-10 13:33: it ended on the 守山人休息处 hunt screen; the
        tap is the only press in that window, inferred, not seen).
        """
        end_at = monotonic() + timeout
        while True:
            if self._home_confirmation_signals(self.capture_frame(), "经营管理重试前主页确认")[0]:
                return True
            if monotonic() >= end_at:
                return False
            self.sleep(0.35)

    def _open_business_popup(self) -> bool:
        for attempt in range(1, POPUP_CLICK_ATTEMPTS + 1):
            self._sleep_after_recognition()
            self._click_reference(*BUSINESS_ENTRY_POINT, after_sleep=1.2)
            end_at = monotonic() + 4.0
            while monotonic() <= end_at:
                if self._popup_open():
                    return True
                self.sleep(0.5)
            if not self._home_without_taps(2.0):
                self.log_info("领取常客圣石：点了经营管理，弹窗没认到，也不在主页，停下不再点。")
                self._save_flow_diagnostic("restaurant_business_popup_not_open")
                return False
            self.log_info(f"领取常客圣石：第{attempt}次点击经营管理未打开，重试。")
        return False

    def _find_go_button(self):
        """The restaurant row's 立刻前往 (the ROI excludes the fishing row's).

        At native 1080p the exact text was not read (live 2026-09-28) while
        the popup check passed, so any read with 前往 counts, re-read briefly.
        """

        end_at = monotonic() + GO_BUTTON_WAIT_SECONDS
        while True:
            boxes = self._roi_boxes(self.capture_frame(), RESTAURANT_GO_ROI, "立刻前往")
            self.info_set("立刻前往 OCR", self._boxes_text(boxes) or "-")
            go = self._box_with(boxes, ("立刻前往", "前往"))
            if go is not None or monotonic() >= end_at:
                return go
            self.sleep(0.3)

    def _go_to_restaurant(self) -> bool:
        for attempt in range(1, POPUP_CLICK_ATTEMPTS + 1):
            go = self._find_go_button()
            if go is None:
                return False
            self._click_box(go, after_sleep=2.0)
            if self._wait_for_title("餐厅", RESTAURANT_TITLE, timeout=8.0, quiet=True):
                return True
            # A swallowed click leaves the popup open: press 立刻前往 again.
            if keyword_match_count(self._popup_text(), BUSINESS_POPUP_KEYWORDS) < 2:
                return self._wait_for_title("餐厅", RESTAURANT_TITLE, timeout=20.0)
            self.log_info(f"领取常客圣石：第{attempt}次点击立刻前往未生效，重试。")
        return False
