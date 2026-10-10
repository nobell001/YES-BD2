"""Weekly chores: browse the arcade menu and like other players' homes.

Layouts calibrated on the 简体 client, 2026-09-25 (1920x1080 reference).
"""

from __future__ import annotations

import re
from time import monotonic

from qfluentwidgets import FluentIcon

from src.tasks.RewardClaimTasks import _ClaimTaskBase

ARCADE_ENTRY_POINT = (459, 262)
ARCADE_TITLE_KEYWORDS = ("街机游戏",)

MY_HOME_ENTRY_POINT = (165, 160)
MY_HOME_TITLE_KEYWORDS = ("我的小屋",)
VISIT_TAB_POINT = (174, 249)
VISIT_TITLE_KEYWORDS = ("参观",)
VISIT_RANDOM_TAB_POINT = (266, 220)
LIKE_BUTTON_POINT = (1751, 115)
LIKE_COUNT_ROI = (1650, 130, 220, 60)
NEXT_HOME_POINT = (1219, 999)
# The random tab loads another home: confirmed by the page below the title
# bar changing.  Re-clicking a tab is harmless.
VISIT_PAGE_ROI = (0, 110, 1920, 970)
VISIT_RANDOM_WAIT_SECONDS = 2.5
# One read 1.5 s after the like missed a counter that updated late.
LIKE_RESULT_SECONDS = 4.0
# 下一间 counts once another home's like counter shows.
NEXT_HOME_WAIT_SECONDS = 5.0
HOME_PAGES_TITLE_KEYWORDS = VISIT_TITLE_KEYWORDS + MY_HOME_TITLE_KEYWORDS


class ArcadeBrowseTask(_ClaimTaskBase):
    claim_log_name = "arcade"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "浏览街机菜单"
        self.description = (
            "打开主页的街机游戏菜单再返回（每周任务：浏览街机游戏菜单）。不玩小游戏。"
        )
        self.icon = FluentIcon.GAME

    def run_claim(self) -> bool:
        if not self._open_page_from_home("街机游戏", ARCADE_ENTRY_POINT, ARCADE_TITLE_KEYWORDS):
            return self._claim_fail("打开街机游戏菜单")
        self.sleep(1.5)
        if not self._leave_to_home("街机游戏", ARCADE_TITLE_KEYWORDS):
            return self._claim_fail("街机游戏返回主页")
        return True


class HomePopularityTask(_ClaimTaskBase):
    claim_log_name = "home_like"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "小屋增加人气"
        self.description = (
            "我的小屋 → 参观 → 随机，给其他玩家的小屋点赞（每周任务：增加人气 3 次）。"
        )
        self.icon = FluentIcon.HEART
        self.default_config.update({"点赞次数": 3, "最多翻看小屋数": 8})
        self.config_description.update(
            {
                "点赞次数": "需要成功点赞的小屋数量。",
                "最多翻看小屋数": "点赞未生效（如已点过）时换下一间，最多翻看这么多间后停止。",
            }
        )

    def run_claim(self) -> bool:
        if not self._open_page_from_home("我的小屋", MY_HOME_ENTRY_POINT, MY_HOME_TITLE_KEYWORDS):
            return self._claim_fail("打开我的小屋")
        if not self._switch_tab("参观", VISIT_TAB_POINT, VISIT_TITLE_KEYWORDS, after_sleep=1.5):
            return self._claim_fail("打开参观")
        if not self._click_until_changed(
            "随机参观",
            lambda: self._click_reference(*VISIT_RANDOM_TAB_POINT, after_sleep=0.2),
            (VISIT_PAGE_ROI,),
            attempts=2,
            wait=VISIT_RANDOM_WAIT_SECONDS,
        ):
            # Like / next are still only pressed on a confirmed visit page.
            self.log_warning("小屋增加人气：点击「随机」后画面未变化，未确认。")

        wanted = max(0, int(self.config.get("点赞次数", 3)))
        budget = max(wanted, int(self.config.get("最多翻看小屋数", 8)))
        liked = 0
        self._home_counts = set()
        for visit in range(1, budget + 1):
            if liked >= wanted:
                break
            if not self._on_visited_home():
                # The fixed like / next points are only safe on this page.
                self.log_info(f"小屋增加人气：第{visit}间不在参观页或读不到人气数，停止点赞。")
                break
            if self._like_current_home(visit):
                liked += 1
            self.info_set("点赞进度", f"{liked}/{wanted}")
            if liked < wanted and not self._next_home(visit):
                break

        if not self._leave_to_home("小屋", HOME_PAGES_TITLE_KEYWORDS):
            return self._claim_fail("小屋返回主页")
        if liked < wanted:
            self.log_info(f"小屋增加人气：只完成 {liked}/{wanted} 次点赞。")
            return self._claim_fail("点赞")
        return True

    def _on_visited_home(self) -> bool:
        """The 参观 page with a readable like counter (waits for a load)."""
        for _read in range(3):
            frame = self.capture_frame()
            if self._title_visible(frame, HOME_PAGES_TITLE_KEYWORDS, "小屋") and (
                self._like_count() is not None
            ):
                return True
            self.sleep(1.5)
        return False

    def _like_count(self) -> int | None:
        boxes = self._roi_boxes(self.capture_frame(), LIKE_COUNT_ROI, "人气数")
        digits = re.sub(r"\D", "", self._boxes_text(boxes))
        return int(digits) if digits else None

    def _like_current_home(self, visit: int) -> bool:
        """Press the thumb once; success means the home's counter went up.

        Never pressed twice: a second press could take the like back.
        """
        before = self._like_count()
        self.info_set("当前阶段", f"第{visit}间小屋：点赞")
        self._click_reference(*LIKE_BUTTON_POINT, after_sleep=0.5)
        after = self._wait_like_count_above(before)
        # What this home showed, a +1 that lands late included.
        self._home_counts = {count for count in (before, after) if count is not None}
        if before is not None:
            self._home_counts.add(before + 1)
        self.info_set(f"第{visit}间人气", f"{before} -> {after}")
        if before is not None and after is not None and after > before:
            self.log_info(f"小屋增加人气：第{visit}间点赞成功（{before} -> {after}）。")
            return True
        self.log_info(f"小屋增加人气：第{visit}间点赞未生效（{before} -> {after}），换下一间。")
        return False

    def _next_home(self, visit: int) -> bool:
        """Press 下一间 until a home with another like count shows.

        A lost press leaves this home up, and a like on it again could take
        the like back: the next like waits for a count this home never had.
        """
        left = set(self._home_counts)
        current = self._like_count()
        if current is not None:
            left.add(current)
        if not left:
            self.log_info(f"小屋增加人气：第{visit}间读不到人气数，无法确认换了小屋，停止点赞。")
            return False
        last = [None]

        def other_home() -> bool:
            # Two agreeing reads: one misread number is not another home.
            count = self._like_count()
            agreed = count is not None and count not in left and count == last[0]
            last[0] = count
            return agreed

        outcome = self.press_and_confirm(
            f"小屋增加人气：第{visit}间「下一间」",
            lambda: self._click_reference(*NEXT_HOME_POINT, after_sleep=0.5),
            other_home,
            still_before=lambda: self._like_count() in left,
            timeout=NEXT_HOME_WAIT_SECONDS,
        )
        if not outcome:
            self.log_info("小屋增加人气：没确认换到另一间小屋，停止点赞（同一间不重复点赞）。")
        return outcome.confirmed

    def _wait_like_count_above(self, before: int | None) -> int | None:
        """The counter once two reads agree it went above ``before``.

        Gives up after ``LIKE_RESULT_SECONDS`` and returns the last read.
        """
        end_at = monotonic() + LIKE_RESULT_SECONDS
        last = None
        while True:
            count = self._like_count()
            if before is None:
                return count
            if count is not None and count > before and count == last:
                return count
            last = count
            if monotonic() >= end_at:
                return count
            self.sleep(0.3)
