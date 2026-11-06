"""Collect the restaurant regulars' sacred stones (领常客圣石).

Calibrated on the 简体 client, 2026-09-26: home → 经营管理 popup → the
restaurant row's 立刻前往 → 格鲁菲餐厅 → 常客.  When regulars carry gifts,
pressing 常客 collects them all at once and toasts "火圣石×30", "暗圣石×8"…
on the left; without gifts it only pans the camera, which is harmless.
"""

from __future__ import annotations

from time import monotonic

from qfluentwidgets import FluentIcon

from ok.task.exceptions import FinishedException, TaskDisabledException

from src.tasks import business_entry
from src.tasks.recovery import recover_to_home
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.utils.ocr_utils import keyword_match_count
from src.utils.press_next import Next, press_next
from src.utils import ocr_size

BUSINESS_ENTRY_POINT = business_entry.ENTRY_POINT
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

    def _popup_open(self, frame=None) -> bool:
        frame = self.capture_frame() if frame is None else frame
        # The whole picture first, read like 一键收菜 reads it: that read
        # found the popup on the HDR screen where this task's cut-outs did
        # not open it (player summary v0.2.26 2026-11-01, see business_entry).
        if business_entry.popup_seen(self._whole_frame_text(frame)):
            return True
        boxes = self._roi_boxes(frame, BUSINESS_POPUP_ROI, "经营管理")
        if keyword_match_count(self._boxes_text(boxes), BUSINESS_POPUP_KEYWORDS) >= 2:
            return True
        boxes = self._roi_boxes(frame, BUSINESS_POPUP_WIDE_ROI, "经营管理整窗")
        return keyword_match_count(self._boxes_text(boxes), BUSINESS_POPUP_WIDE_KEYWORDS) >= 2

    def _whole_frame_text(self, frame) -> str:
        try:
            boxes = self.ocr(
                frame=frame,
                threshold=float(self.config.get("日常 OCR 阈值", 0.2)),
                target_height=ocr_size.READ_HEIGHT,
                log=False,
                name="经营管理弹窗",
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.info_set("经营管理弹窗 OCR 错误", str(exc))
            return ""
        return self._boxes_text(list(boxes or []))

    def _home_only_read(self, frame) -> bool:
        """主页 on this frame, only read: the shared check that taps the
        left column on a dimmed home could open something else under an
        unread popup (live 4K 2026-10-10 13:33, 守山人休息处)."""
        return bool(self._home_confirmation_signals(frame, "经营管理重试前主页确认")[0])

    def _open_business_popup(self) -> bool:
        """Press 经营管理 until its popup shows, with the shared remedies.

        Still 主页 after a press: the icon once more, then the 「经营管理」
        word under it.  A screen that is neither (something opened) is never
        pressed: a press there could land on something else.
        """
        self._sleep_after_recognition()
        outcome = press_next(
            "领取常客圣石：经营管理",
            lambda: self._click_reference(*BUSINESS_ENTRY_POINT, after_sleep=1.2),
            [
                Next("经营管理弹窗", self._popup_open, goal=True),
                Next("主页", self._home_only_read, before=True),
            ],
            capture=self.capture_frame,
            sleep=self.sleep,
            log=self.log_info,
            fixed=lambda: self._click_reference(*business_entry.LABEL_POINT, after_sleep=1.2),
            timeout=business_entry.POPUP_LOOK_SECONDS,
            clock=lambda: monotonic(),
        )
        if outcome:
            return True
        if outcome.screen == "主页":
            self.log_info(
                "领取常客圣石：点了经营管理图标两次、再点下面的「经营管理」字，"
                "游戏都没打开经营管理，画面还在主页。"
            )
        else:
            self.log_info(
                f"领取常客圣石：点了经营管理，没认出经营管理弹窗，画面是{outcome.screen}，停下不再点。"
            )
        self._save_flow_diagnostic("restaurant_business_popup_not_open")
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
            self._click_box(go, after_sleep=2.0)  # 不用确认：循环里弹窗还在就再点立刻前往
            if self._wait_for_title("餐厅", RESTAURANT_TITLE, timeout=8.0, quiet=True):
                return True
            # A swallowed click leaves the popup open: press 立刻前往 again.
            if keyword_match_count(self._popup_text(), BUSINESS_POPUP_KEYWORDS) < 2:
                # The popup closed: the restaurant is loading, a load wait
                # (Leo 2026-10-15 「你單純等載入怎麼可以改成只等10秒」).
                return self._wait_for_title("餐厅", RESTAURANT_TITLE)
            self.log_info(f"领取常客圣石：第{attempt}次点击立刻前往未生效，重试。")
        return False
