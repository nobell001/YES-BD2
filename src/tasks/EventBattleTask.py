"""Daily event battles (活动每日战斗) for the rotating story events.

Every event exposes 普通战斗 and 挑战战斗 with 15 stages each and a daily
event-AP pool shown as "a/5" (plus a bonus "+b").  While a mode still has
uncleared stages its stage page shows an 自动战斗 toggle that opens a count
dialog; the game then clears consecutive stages on its own.  Once both modes
are cleared the toggle is gone and the remaining AP goes to 快速战斗 on
challenge stage 15.

Calibrated on the 简体 client, 2026-09-25 (Chained Soldier 2 event).  All
buttons are found by their text so a new event with the same template works.
Safety rules:
- the 活动AP不足 popup is always cancelled - its other button (补充) refills
  AP with paid resources and is never pressed;
- with 仅使用免费活动AP enabled, the dialog's switch must read yellow (on) and
  the battle cost must not exceed the free AP read from the top bar,
  otherwise the dialog is cancelled.
"""

from __future__ import annotations

import re
from time import monotonic

from qfluentwidgets import FluentIcon

from src.tasks.claim_page import BACK_BUTTON_POINT
from src.tasks.recovery import recover_to_home
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils.colour_rules import switch_yellow_ratio
from src.utils.free_switch import ensure_free_switch_on
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text
from src.utils.press_confirm import wait_for

# 1920x1080 reference coordinates / ROIs.
HOME_BANNER_ROI = (1400, 480, 520, 420)
HUB_BUTTON_ROI = (300, 900, 1320, 110)
PANEL_TITLE_ROI = (880, 110, 560, 70)
AP_ROI = (1560, 20, 360, 70)
AUTO_TOGGLE_ROI = (1620, 940, 300, 120)
AUTO_TOGGLE_POINT = (1700, 984)
BOTTOM_BUTTONS_ROI = (760, 950, 900, 90)
DIALOG_ROI = (600, 240, 720, 640)
DIALOG_START_ROI = (880, 790, 330, 70)
DIALOG_MAX_POINT = (1169, 461)
DIALOG_MIN_POINT = (750, 461)
DIALOG_PLUS_POINT = (1222, 527)
DIALOG_CANCEL_POINT = (804, 824)
FREE_AP_SWITCH_POINT = (1245, 366)
FREE_AP_SWITCH_ROI = (1205, 346, 80, 42)
# The 快速战斗 dialog (challenge 15 once both modes are cleared) is taller
# than the auto dialog: it adds a reward row.  Measured live 2026-09-28.
QUICK_DIALOG_ROI = (620, 250, 680, 610)
QUICK_DIALOG_KEYWORDS = ("快速战斗", "仅使用免费活动AP", "MAX")
QUICK_DIALOG_START_ROI = (880, 780, 330, 62)
QUICK_DIALOG_MAX_POINT = (1168, 592)
QUICK_DIALOG_MIN_POINT = (750, 592)
QUICK_DIALOG_PLUS_POINT = (1222, 660)
QUICK_DIALOG_CANCEL_POINT = (804, 811)
QUICK_FREE_AP_SWITCH_POINT = (1245, 378)
QUICK_FREE_AP_SWITCH_ROI = (1205, 357, 80, 42)
# Quick battles finish at once behind a REWARD overlay ("点击画面即可返回").
QUICK_RESULT_KEYWORDS = ("REWARD", "点击画面即可返回", "获得")
QUICK_RESULT_ROI = (560, 300, 800, 740)
QUICK_RESULT_DISMISS_POINT = (960, 900)
QUICK_RESULT_TIMEOUT = 12.0
FREE_AP_SWITCH_YELLOW_RATIO = 0.05
FREE_AP_SWITCH_SETTLE_SECONDS = 2.5
AP_SHORT_CANCEL_READS = 3
# After a failure: longest wait for a running chain to reach its result.
FAIL_SETTLE_SECONDS = 300.0
BANNER_CLICK_ATTEMPTS = 3
BANNER_POSITION_TOLERANCE = 24
HUB_RETRY_SECONDS = 6.0
MODE_CLICK_ATTEMPTS = 3
START_CLICK_ATTEMPTS = 3
START_CONFIRM_SECONDS = 15.0
RESULT_BACK_ATTEMPTS = 3
RESULT_BUTTONS_ROI = (1300, 960, 620, 100)
PROGRESS_ROI = (0, 880, 760, 190)
# The stage list on the left: its numbers (Leo's 普通战斗10/11 frames,
# 2026-10-10, numbers at x 250-310, rows about 99 apart).
STAGE_LIST_ROI = (220, 120, 140, 960)
# Read numbers off the line through the others by more than this: a misread.
STAGE_LIST_ROW_TOLERANCE = 24
# The page can draw its title and stage before the top bar's AP (a player's
# 1080p run, 2026-10-10): the AP is read for up to this long.
AP_READ_SECONDS = 5.0
STATE_KEYS = ("stage", "free_ap", "auto", "quick")

NORMAL_MODE = "普通战斗"
CHALLENGE_MODE = "挑战战斗"
MODES = (NORMAL_MODE, CHALLENGE_MODE)
HUB_KEYWORDS = MODES
# Leo 2026-10-01: once 魔兽 opens the banner reads 魔兽追踪者解锁 instead of
# 普通战斗解锁; both open the event.  Fixed in the code, not a setting (Leo
# 2026-10-04).
BANNER_KEYWORDS = ("战斗解锁", "普通战斗", "挑战战斗", "追踪者解锁")
AUTO_TOGGLE_TEXT = "自动战斗"
QUICK_BATTLE_TEXT = "快速战斗"
DIALOG_KEYWORDS = ("将按照指定次数", "自动进行战斗", "MAX")
IN_BATTLE_TEXT = "自动战斗进行中"
STOP_AUTO_TEXT = "结束自动战斗"
RESULT_BACK_TEXT = "返回"
AP_SHORT_TEXT = "AP不足"
CANCEL_TEXT = "取消"
LAST_STAGE = 15

# The pool may sit right after the event currency ("8,500 0/5"); refuse a
# match that starts inside another number so "8,5000/5" is not read as 5000.
# OCR often glues the two (live 2026-10-09: "5,9005/5" for 5,900 and 5/5), so
# the currency's three digits after its comma are split off first.  The comma
# can read as a dot (a player's 1080p frame, 2026-10-10: "5.650").
CURRENCY_GLUED_PATTERN = re.compile(r"(?<![\d,.])(\d{1,3}(?:[,.]\d{3})+)(?=\d)")
AP_PATTERN = re.compile(r"(?<![\d,.])(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")
BONUS_PATTERN = re.compile(r"\+\s*(\d+)")
COST_PATTERN = re.compile(r"(\d+)\s*$")
PROGRESS_PATTERN = re.compile(r"第(\d+)次[/／]共(\d+)次")


def parse_ap(text: str) -> tuple[int | None, int]:
    """Return (free AP, bonus AP) from the top-bar OCR text, e.g. '0/5 +3'."""
    normalized = str(text).replace("／", "/").replace("|", " ")
    normalized = CURRENCY_GLUED_PATTERN.sub(r"\1 ", normalized)
    free_match = AP_PATTERN.search(normalized)
    if free_match and int(free_match.group(2)) <= 0:
        free_match = None
    # A pool above its top ("25/5": the AP icon read as a 2, Leo's frame at
    # 1080p, 2026-10-10) stays as read: any AP above 0 opens the dialog, whose
    # MAX with 仅使用免费活动AP on decides the count (Leo 08:58Z 「超過上限 一樣
    # 點開來打 不要去前面字 大於0 就是點開來打就對了」).
    free = int(free_match.group(1)) if free_match else None
    tail = normalized[free_match.end():] if free_match else normalized
    bonus_match = BONUS_PATTERN.search(tail)
    return free, int(bonus_match.group(1)) if bonus_match else 0


def parse_battle_cost(text: str) -> int | None:
    """Return N from the dialog start button text '战斗 N' (OCR may add noise)."""
    cleaned = re.sub(r"[^\d战斗]", " ", str(text))
    if "战斗" not in cleaned:
        return None
    match = COST_PATTERN.search(cleaned.strip())
    return int(match.group(1)) if match else None


def parse_stage_number(text: str, mode: str) -> int | None:
    match = re.search(re.escape(mode) + r"\s*(\d{1,2})", normalize_ocr_text(text))
    return int(match.group(1)) if match else None


class EventBattleTask(_ClaimTaskBase):
    claim_log_name = "event_battle"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "活动每日战斗"
        self.description = (
            "进入当期活动：普通战斗→挑战战斗用自动战斗推进未通关关卡；"
            "两种都通关后对挑战战斗15快速战斗。绝不点击补充AP。"
        )
        self.icon = FluentIcon.PLAY
        self.default_config.update(
            {
                "仅使用免费活动AP": True,
                "每次最多战斗场数": 5,
                "全部通关后快速战斗": True,
                "横幅轮播等待秒数": 15.0,
                "单场战斗超时秒数": 240.0,
            }
        )
        self.config_description.update(
            {
                "仅使用免费活动AP": "只用每日免费活动AP（顶部 a/5），不动用额外的 +AP。",
                "每次最多战斗场数": "一次运行最多进行的战斗场数（0 表示用完可用AP）。",
                "全部通关后快速战斗": "普通与挑战都已通关时，对挑战战斗15使用快速战斗。",
                "横幅轮播等待秒数": "横幅轮播到别的活动时，最多等待多久让它转回来。",
                "单场战斗超时秒数": "自动战斗每一场允许的最长时间，超时视为失败。",
            }
        )
        self._battles_done = 0
        self._why = ""

    # -- task entry ---------------------------------------------------------

    def run_claim(self) -> bool:
        self._battles_done = 0
        self._why = ""
        for mode in MODES:
            if self._battle_budget() <= 0:
                break
            result = self._run_mode(mode)
            if result == "no_event":
                return self._no_event()
            if result == "failed":
                return self._event_fail(mode)
            if result == "no_ap":
                return self._finish(self._no_ap_text())
            if result != "cleared":
                return self._finish(f"{mode}已推进")
        if self._battle_budget() > 0 and bool(self.config.get("全部通关后快速战斗", True)):
            result = self._run_quick_battle()
            if result == "no_event":
                return self._no_event()
            if result == "failed":
                return self._event_fail("快速战斗")
            if result == "skipped":
                self.log_warning(
                    "活动每日战斗：普通和挑战已全部通关，但快速战斗尚未执行（挑战战斗未选中第15关"
                    "），今日活动AP未使用。",
                    notify=True,
                )
                return self._finish("快速战斗未执行")
            if result == "no_ap":
                return self._finish(self._no_ap_text())
        return self._finish("完成")

    def _no_ap_text(self) -> str:
        if bool(self.config.get("仅使用免费活动AP", True)):
            return "今天的免费活动AP已用完"
        return "今天的活动AP已用完"

    def _no_event(self) -> bool:
        # Between events there is simply nothing to fight: not a failure.
        self.log_warning(
            "活动每日战斗：主页右侧未发现活动横幅（关键词未命中），视为当前没有活动。",
            notify=True,
        )
        return self._finish("未发现进行中的活动")

    def _finish(self, message: str) -> bool:
        self.info_set("活动战斗结果", f"{message}，本次战斗 {self._battles_done} 场")
        self.log_info(f"活动每日战斗：{message}，本次战斗 {self._battles_done} 场。")
        if not recover_to_home(self):
            return self._claim_fail("返回主页")
        return True

    def _failed(self, why: str) -> str:
        """Keep why this step failed for the 问题摘要; returns "failed"."""
        self._why = why
        return "failed"

    def _event_fail(self, stage: str) -> bool:
        self._save_flow_diagnostic(f"{self.claim_log_name}_{stage}_failed")
        self._settle_before_recovery()
        recover_to_home(self)
        # A player's summary said only 「普通战斗失败」 (2026-10-10): _claim_fail
        # writes the reason _failed kept.
        return self._claim_fail(stage)

    def _settle_before_recovery(self) -> None:
        """Let a running chain end and leave its result screen first.

        Recovery only knows back arrows and 取消: it would click the battle UI
        and cannot press the result screen's 返回 (review 2026-09-26).
        """
        end_at = monotonic() + FAIL_SETTLE_SECONDS
        calm = 0
        while monotonic() <= end_at:
            frame = self.capture_frame()
            if self._in_battle(frame):
                calm = 0
                self.info_set("当前阶段", "失败后等待战斗结束")
                self.sleep(2.0)
                continue
            buttons = self._roi_boxes(frame, RESULT_BUTTONS_ROI, "战斗结果")
            if self._box_with(buttons, (RESULT_BACK_TEXT,)) is None:
                return
            # Two calm frames: the result screen, not a transition flash.
            calm += 1
            if calm >= 2:
                self._leave_result_screen()
                return
            self.sleep(1.0)

    def _battle_budget(self) -> int:
        cap = int(self.config.get("每次最多战斗场数", 5))
        return 999 if cap <= 0 else cap - self._battles_done

    # -- navigation ---------------------------------------------------------

    def _find_stable_banner(self, keywords: tuple[str, ...]):
        """Return the banner caption box once two reads agree on its position.

        The banners rotate; clicking a position read before the carousel
        moved could open a different banner.
        """
        end_at = monotonic() + float(self.config.get("横幅轮播等待秒数", 15.0))
        tolerance = BANNER_POSITION_TOLERANCE / REFERENCE_WIDTH * max(1, int(self.width))
        while monotonic() <= end_at:
            boxes = self._roi_boxes(self.capture_frame(), HOME_BANNER_ROI, "活动横幅")
            self.info_set("活动横幅 OCR", self._boxes_text(boxes) or "-")
            first = self._box_with(boxes, keywords)
            if first is None:
                self.sleep(1.0)
                continue
            self.sleep(0.6)
            again = self._box_with(
                self._roi_boxes(self.capture_frame(), HOME_BANNER_ROI, "活动横幅"),
                keywords,
            )
            if again is None:
                continue
            a = self._ocr_box_center(first)
            b = self._ocr_box_center(again)
            if a and b and abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance:
                return again
        return None

    def _enter_hub(self) -> str:
        """Open the event hub: ok / no_event / failed.

        After one mode the game is still inside the event: back out of its
        stage page to the hub instead of going home and through the banner
        again (user, 2026-09-27).
        """
        if self._wait_for_hub(timeout=0.0):
            return "ok"
        if any(self._wait_for_stage_page(mode, timeout=0.0, quiet=True) for mode in MODES):
            self._click_reference(*BACK_BUTTON_POINT, after_sleep=1.0)
            if self._wait_for_hub(timeout=HUB_RETRY_SECONDS):
                return "ok"
        if not recover_to_home(self):
            return self._failed("回不到主页，没能去点活动横幅")
        if not self._wait_for_home_confirmation("活动入口前主页确认"):
            return self._failed("没认出主页，没去点活动横幅")
        keywords = BANNER_KEYWORDS
        for attempt in range(1, BANNER_CLICK_ATTEMPTS + 1):
            banner = self._find_stable_banner(keywords)
            if banner is None:
                # Home confirmed yet no caption during a whole carousel cycle.
                if attempt == 1:
                    return "no_event"
                return self._failed("点了活动横幅没进去，之后横幅也找不到了")
            self._sleep_after_recognition()
            self._click_box(banner, after_sleep=1.0)
            if self._wait_for_hub(timeout=HUB_RETRY_SECONDS):
                return "ok"
            if self._wait_for_home_confirmation("活动横幅重试前主页确认", timeout=2.0):
                # Swallowed click: still on home, look for the banner again.
                self.log_info(f"活动每日战斗：第{attempt}次点击横幅未生效，重试。")
                continue
            # Left home (loading): give the hub its full time.
            if self._wait_for_hub(timeout=25.0):
                return "ok"
            return self._failed("点了活动横幅后，活动页一直没出来")
        return self._failed(f"活动横幅点了 {BANNER_CLICK_ATTEMPTS} 次都没进活动页")

    def _wait_for_hub(self, timeout: float = 20.0) -> bool:
        end_at = monotonic() + timeout
        while monotonic() <= end_at:
            boxes = self._roi_boxes(self.capture_frame(), HUB_BUTTON_ROI, "活动页")
            text = self._boxes_text(boxes)
            self.info_set("活动页 OCR", text or "-")
            if keyword_match_count(text, HUB_KEYWORDS) >= 2:
                return True
            self.sleep(0.8)
        return False

    def _open_mode(self, mode: str) -> str:
        """Open one mode's stage page from home: ok / no_event / failed."""
        entered = self._enter_hub()
        if entered != "ok":
            return entered
        for attempt in range(1, MODE_CLICK_ATTEMPTS + 1):
            boxes = self._roi_boxes(self.capture_frame(), HUB_BUTTON_ROI, "活动页")
            button = self._box_with(boxes, (mode,))
            if button is None:
                return self._failed(f"活动页里没找到「{mode}」")
            self._sleep_after_recognition()
            self._click_box(button, after_sleep=1.5)
            if self._wait_for_stage_page(mode, timeout=HUB_RETRY_SECONDS, quiet=True):
                return "ok"
            if self._wait_for_hub(timeout=2.0):
                self.log_info(f"活动每日战斗：第{attempt}次点击{mode}未生效，重试。")
                continue
            if self._wait_for_stage_page(mode):
                return "ok"
            return self._failed(f"点了「{mode}」后关卡页一直没出来")
        return self._failed(f"「{mode}」点了 {MODE_CLICK_ATTEMPTS} 次都没进关卡页")

    def _wait_for_stage_page(
        self,
        mode: str,
        timeout: float = 25.0,
        quiet: bool = False,
    ) -> bool:
        end_at = monotonic() + timeout
        while monotonic() <= end_at:
            frame = self.capture_frame()
            if self._title_visible(frame, (mode,), mode):
                panel = self._boxes_text(self._roi_boxes(frame, PANEL_TITLE_ROI, f"{mode}关卡"))
                if parse_stage_number(panel, mode) is not None:
                    return True
            self.sleep(0.8)
        if not quiet:
            self.log_info(f"活动每日战斗：未确认{mode}关卡页。")
        return False

    # -- stage page state ---------------------------------------------------

    def _stable_stage_state(self, mode: str) -> dict:
        """Read the stage page until two reads agree and the page is drawn.

        The page can show its title and stage before the top bar's AP: a
        player's 1080p run (2026-10-10) read the AP empty twice right after
        the loading screen and stopped with 「活动AP没读到」, while its frame a
        moment later showed 5/5.  Drawn means the AP and 自动战斗 or 快速战斗
        read (Leo 09:00Z: they are on the same page, one late means both
        late).  Up to AP_READ_SECONDS; then the last read.
        """
        reads = [self._stage_state(mode)]

        def agreed():
            self.sleep(0.8)
            current = self._stage_state(mode)
            previous = reads[-1]
            reads.append(current)
            same = all(current[key] == previous[key] for key in STATE_KEYS)
            drawn = current["free_ap"] is not None and (current["auto"] or current["quick"])
            return current if same and drawn else None

        return wait_for(agreed, AP_READ_SECONDS, sleep=self.sleep, poll=0.0) or reads[-1]

    def _panel_stage(self, mode: str) -> int | None:
        panel = self._boxes_text(
            self._roi_boxes(self.capture_frame(), PANEL_TITLE_ROI, f"{mode}关卡")
        )
        return parse_stage_number(panel, mode)

    def _stage_list_point(self, target: int) -> tuple[int, int] | None:
        """Where stage ``target`` sits in the left list (reference coordinates).

        The numbers' art reads about half the time (Leo's frames: 5, 6, 8, 10
        and 11 read, 2-4, 7 and 9 not), so a number not read is placed on the
        line through the read ones; rows are evenly spaced.  None when fewer
        than two read, or the read ones do not lie on one line (a misread).
        """
        boxes = self._reference_boxes(self.capture_frame(), STAGE_LIST_ROI, "关卡列表")
        rows: dict[int, tuple[float, float]] = {}
        for found in boxes:
            match = re.match(r"\s*(\d{1,2})", normalize_ocr_text(getattr(found, "name", "")))
            if match:
                centre = (found.x + found.width / 2, found.y + found.height / 2)
                rows.setdefault(int(match.group(1)), centre)
        self.info_set("关卡列表", " ".join(str(number) for number in sorted(rows)) or "-")
        if target in rows:
            x, y = rows[target]
            return round(x), round(y)
        if len(rows) < 2:
            return None
        numbers = sorted(rows)
        first, last = numbers[0], numbers[-1]
        pitch = (rows[last][1] - rows[first][1]) / (last - first)
        if pitch <= 0:
            return None
        for number in numbers:
            expected = rows[first][1] + (number - first) * pitch
            if abs(rows[number][1] - expected) > STAGE_LIST_ROW_TOLERANCE:
                return None
        y = rows[last][1] + (target - last) * pitch
        top, height = STAGE_LIST_ROI[1], STAGE_LIST_ROI[3]
        if not top <= y <= top + height:
            return None
        x = sum(rows[number][0] for number in numbers) / len(numbers)
        return round(x), round(y)

    def _select_unfinished_stage(self, mode: str, state: dict) -> dict:
        """With a cleared stage selected, select the next one until 自动战斗 shows.

        A cleared stage shows 快速战斗 and 战斗 but no 自动战斗 (Leo's frames
        of 普通战斗10 and 11, 2026-10-10), which used to read as "all
        cleared".  Up to stage 15; a next stage not found or not selected (a
        locked one) leaves it as before.
        """
        while state["stage"] is not None and state["stage"] < LAST_STAGE and not state["auto"]:
            current, target = state["stage"], state["stage"] + 1
            point = self._stage_list_point(target)
            if point is None:
                self.log_info(
                    f"活动每日战斗：{mode}选在已通关的第{current}关，左边列表里没认出第{target}关。"
                )
                return state
            self.info_set("当前阶段", f"{mode}：第{current}关已通关，选第{target}关")
            self._sleep_after_recognition()
            outcome = self.press_and_confirm(
                f"{mode}选第{target}关",
                lambda: self._click_reference(*point, after_sleep=0.8),
                lambda: self._panel_stage(mode) == target,
                still_before=lambda: self._panel_stage(mode) == current,
            )
            if not outcome:
                self.log_info(f"活动每日战斗：{mode}点了第{target}关，右边没换成第{target}关。")
                return state
            state = self._stable_stage_state(mode)
        return state

    def _stage_state(self, mode: str) -> dict:
        frame = self.capture_frame()
        panel = self._boxes_text(self._roi_boxes(frame, PANEL_TITLE_ROI, f"{mode}关卡"))
        ap_text = self._boxes_text(self._roi_boxes(frame, AP_ROI, "活动AP"))
        toggle = self._boxes_text(self._roi_boxes(frame, AUTO_TOGGLE_ROI, "自动战斗开关"))
        buttons = self._boxes_text(self._roi_boxes(frame, BOTTOM_BUTTONS_ROI, "关卡按钮"))
        free, bonus = parse_ap(ap_text)
        state = {
            "stage": parse_stage_number(panel, mode),
            "free_ap": free,
            "bonus_ap": bonus,
            "auto": keyword_match_count(toggle, (AUTO_TOGGLE_TEXT,)) >= 1,
            "quick": keyword_match_count(buttons, (QUICK_BATTLE_TEXT,)) >= 1,
        }
        self.info_set(f"{mode}状态", str(state))
        return state

    def _usable_ap(self, state: dict) -> int:
        free = state["free_ap"] or 0
        if bool(self.config.get("仅使用免费活动AP", True)):
            return free
        return free + state["bonus_ap"]

    # -- auto battle ----------------------------------------------------------

    def _run_mode(self, mode: str) -> str:
        """Return cleared / no_ap / progressed / no_event / failed for one mode."""
        opened = self._open_mode(mode)
        if opened != "ok":
            return opened
        for _round in range(3):
            state = self._stable_stage_state(mode)
            if not state["auto"] and not state["quick"]:
                # Cleared shows 快速战斗; neither is not a page to judge from.
                return self._failed(
                    f"{mode}关卡页右下 {AP_READ_SECONDS:g} 秒都没看到「自动战斗」或「快速战斗」"
                )
            if not state["auto"]:
                state = self._select_unfinished_stage(mode, state)
            if not state["auto"]:
                self.log_info(f"活动每日战斗：{mode}已全部通关。")
                return "cleared"
            if state["free_ap"] is None:
                # Double check (Leo 2026-10-10 「應該雙重保險 還是可以點開自動戰鬥看看的」):
                # the dialog's 仅使用免费活动AP switch and its MAX count decide.
                self.log_info(
                    f"活动每日战斗：{mode}关卡页上方的活动AP {AP_READ_SECONDS:g} 秒都没读到，"
                    "改看自动战斗窗口的场数。"
                )
                wanted = self._battle_budget()
            else:
                wanted = min(self._usable_ap(state), self._battle_budget())
            if wanted <= 0:
                return "no_ap"
            fought = self._auto_battle(mode, wanted, state)
            if fought is None:
                return "failed"
            if fought == 0:
                return "no_ap"
            if not self._wait_for_stage_page(mode):
                self._battles_done += fought
                return self._failed(f"打完后没回到{mode}的关卡页")
            after = self._stable_stage_state(mode)
            # Counted from the dialog (fought >= its 战斗 N), never from the top
            # bar: Windows read Leo's 5/5 as "8,400 25/5" (the AP icon as a 2,
            # 4K PC 2026-10-10), and 25 - 0 counted 25 battles.
            self._battles_done += fought
            if self._battle_budget() <= 0:
                return "progressed"
            if after["auto"] and after["stage"] == state["stage"]:
                self.log_warning(
                    f"活动每日战斗：{mode}第{state['stage']}关自动战斗后仍停在同一关，"
                    "可能战败，今天不再重试。",
                    notify=True,
                )
                return "progressed"
        return "progressed"

    def _auto_battle(self, mode: str, wanted: int, state: dict) -> int | None:
        """Open the auto dialog, start ``wanted`` battles, return how many ran."""
        self._sleep_after_recognition()
        opened = False
        for _attempt in range(2):
            self._click_reference(*AUTO_TOGGLE_POINT, after_sleep=1.2)
            if self._dismiss_ap_shortage():
                return 0
            if self._wait_for_dialog():
                opened = True
                break
            if self._dismiss_ap_shortage():
                return 0
            # A swallowed click leaves the stage page untouched; try once more.
            if not self._stage_state(mode)["auto"]:
                break
        if not opened:
            self._failed("按了自动战斗，选场数的窗口没出来")
            return None
        cost = self._set_dialog_count(wanted, state)
        if cost is None:
            self._click_reference(*DIALOG_CANCEL_POINT, after_sleep=1.0)
            return None
        if cost == 0:
            self.log_info(
                f"活动每日战斗：{mode}自动战斗窗口按 MAX 后是 0 场，"
                f"{self._no_ap_text()}，关掉窗口。"
            )
            self._click_reference(
                *DIALOG_CANCEL_POINT, after_sleep=1.0  # 不用确认：回主页会再确认
            )
            return 0
        self.info_set("当前阶段", f"{mode}：自动战斗 {cost} 场")
        self.log_info(f"活动每日战斗：{mode}第{state['stage']}关起自动战斗 {cost} 场。")
        started = self._start_auto_battle()
        if started == "no_ap":
            return 0
        if started != "started":
            self._failed("按了「战斗」后没开始打")
            return None
        return self._watch_auto_battle(cost)

    def _start_auto_battle(self) -> str:
        """Press 战斗 N and prove a battle began: started / no_ap / failed."""
        for attempt in range(1, START_CLICK_ATTEMPTS + 1):
            boxes = self._roi_boxes(self.capture_frame(), DIALOG_START_ROI, "自动战斗开始")
            start = self._box_with(boxes, ("战斗",))
            if start is None:
                break
            self._click_box(start, after_sleep=1.5)
            end_at = monotonic() + START_CONFIRM_SECONDS
            while monotonic() <= end_at:
                if self._dismiss_ap_shortage():
                    return "no_ap"
                if self._in_battle(self.capture_frame()):
                    return "started"
                self.sleep(1.0)
            if not self._dialog_open():
                # The dialog closed but no battle text yet: a long transition.
                return "started" if self._wait_in_battle(START_CONFIRM_SECONDS) else "failed"
            self.log_info(f"活动每日战斗：第{attempt}次点击战斗后未开始，重试。")
        if self._dialog_open():
            self._click_reference(*DIALOG_CANCEL_POINT, after_sleep=1.0)
        self.log_info("活动每日战斗：自动战斗未能开始。")
        return "failed"

    def _dialog_open(self) -> bool:
        boxes = self._roi_boxes(self.capture_frame(), DIALOG_ROI, "自动战斗窗口")
        return keyword_match_count(self._boxes_text(boxes), DIALOG_KEYWORDS) >= 2

    def _in_battle(self, frame) -> bool:
        progress = self._boxes_text(self._roi_boxes(frame, PROGRESS_ROI, "自动战斗进度"))
        buttons = self._boxes_text(self._roi_boxes(frame, RESULT_BUTTONS_ROI, "战斗结果"))
        return (
            keyword_match_count(progress, (IN_BATTLE_TEXT,)) >= 1
            or keyword_match_count(buttons, (STOP_AUTO_TEXT,)) >= 1
        )

    def _wait_in_battle(self, timeout: float) -> bool:
        end_at = monotonic() + timeout
        while monotonic() <= end_at:
            if self._in_battle(self.capture_frame()):
                return True
            self.sleep(1.0)
        return False

    def _wait_for_dialog(self, timeout: float = 6.0) -> bool:
        end_at = monotonic() + timeout
        while monotonic() <= end_at:
            if self._dialog_open():
                return True
            self.sleep(0.5)
        self.log_info("活动每日战斗：未出现自动战斗次数窗口。")
        return False

    def _dialog_cost(self) -> int | None:
        boxes = self._roi_boxes(self.capture_frame(), DIALOG_START_ROI, "自动战斗开始")
        cost = parse_battle_cost(self._boxes_text(boxes))
        self.info_set("自动战斗场数", cost if cost is not None else "-")
        return cost

    def _settled_cost(self, read, timeout: float = 3.0) -> int | None:
        """The start button's count once two reads agree.

        It updates a moment after MAX/MIN/+1; one read could be blank (the
        task failed) or the count before the last click.
        """
        previous = None
        end_at = monotonic() + timeout
        while True:
            cost = read()
            if (cost is not None and cost == previous) or monotonic() >= end_at:
                return cost
            previous = cost
            self.sleep(0.35)

    def _set_dialog_count(self, wanted: int, state: dict) -> int | None:
        """Select ``wanted`` battles and prove the cost respects the AP policy.

        With the top bar's AP not read, the switch read on and MAX within
        ``wanted`` are the checks left (the game caps MAX at the free AP).
        0: MAX stayed 0, nothing left to fight today.
        """
        free_only = bool(self.config.get("仅使用免费活动AP", True))
        free = state["free_ap"]
        if free_only and not self._ensure_free_ap_switch_on():
            self._failed("没能确认「仅使用免费活动AP」开着，所以没开打")
            return None
        cost = self._max_count(DIALOG_MAX_POINT, self._dialog_cost)
        if cost == 0:
            return 0
        if cost is not None and cost > wanted:
            self._click_reference(*DIALOG_MIN_POINT, after_sleep=0.6)
            for _ in range(wanted - 1):
                self._click_reference(*DIALOG_PLUS_POINT, after_sleep=0.3)
            cost = self._settled_cost(self._dialog_cost)
        # Second guard independent of the switch colour: never exceed the free
        # AP read from the top bar when only free AP may be used.
        over_free = free_only and free is not None and cost is not None and cost > free
        if cost is None or cost <= 0 or cost > wanted or over_free:
            shown = free if free is not None else "没读到"
            self.log_info(f"活动每日战斗：场数校验失败（{cost}/{wanted}，免费AP {shown}）。")
            self._failed(f"场数对不上（读到 {cost}，要打 {wanted}，免费AP {shown}），所以没开打")
            return None
        if free is None:
            self.log_info(f"活动每日战斗：免费AP开关开着，窗口场数 {cost}，按这个打。")
        return cost

    def _max_count(self, max_point, read) -> int | None:
        """Press MAX and read the count; a 0 gets one more look.

        MAX 0 means no free AP left today (Windows can read the top bar's 0/5
        as 20/5, so the dialog opens anyway).  A slow window may not have
        counted yet, so 0 is only believed on the second look.
        """
        self._click_reference(*max_point, after_sleep=0.8)
        cost = self._settled_cost(read)
        if cost == 0:
            self.sleep(1.0)
            self._click_reference(*max_point, after_sleep=0.8)  # 不用确认：下一行读场数
            cost = self._settled_cost(read)
        return cost

    def _free_ap_switch_ratio(self, roi=FREE_AP_SWITCH_ROI) -> float:
        """The 仅使用免费活动AP switch turns yellow when on (same widget as PVP)."""
        frame = self.capture_frame()
        height, width = frame.shape[:2]
        x, y, w, h = roi
        crop = frame[
            round(y / REFERENCE_HEIGHT * height) : round((y + h) / REFERENCE_HEIGHT * height),
            round(x / REFERENCE_WIDTH * width) : round((x + w) / REFERENCE_WIDTH * width),
        ]
        if crop.size == 0 or crop.ndim != 3 or crop.shape[2] < 3:
            return 0.0
        ratio = switch_yellow_ratio(crop)
        self.info_set("免费AP开关", f"黄色占比 {ratio:.3f}")
        return ratio

    def _ensure_free_ap_switch_on(
        self, point=FREE_AP_SWITCH_POINT, roi=FREE_AP_SWITCH_ROI
    ) -> bool:
        # One press at most: a second one would turn off a switch that was
        # on but not recognised as on (review #28).
        if ensure_free_switch_on(
            "活动每日战斗：仅用免费活动AP",
            lambda: self._free_ap_switch_ratio(roi),
            lambda: self._click_reference(*point, after_sleep=0.5),
            on_above=FREE_AP_SWITCH_YELLOW_RATIO,
            settle=FREE_AP_SWITCH_SETTLE_SECONDS,
            sleep=self.sleep,
            log=self.log_info,
        ):
            return True
        self.log_info("活动每日战斗：无法确认仅用免费活动AP已开启，取消。")
        return False

    def _watch_auto_battle(self, planned: int) -> int | None:
        """Follow the chain until its result screen; return battles counted.

        The count never goes below ``planned``: counting too many only means
        fewer battles later, counting too few could exceed the per-run cap.
        """
        per_battle = float(self.config.get("单场战斗超时秒数", 240.0))
        end_at = monotonic() + per_battle * planned + 60.0
        seen = 0
        calm = 0
        while monotonic() <= end_at:
            frame = self.capture_frame()
            progress_text = normalize_ocr_text(
                self._boxes_text(self._roi_boxes(frame, PROGRESS_ROI, "自动战斗进度"))
            )
            buttons = self._roi_boxes(frame, RESULT_BUTTONS_ROI, "战斗结果")
            progress = PROGRESS_PATTERN.search(progress_text)
            if progress:
                seen = max(seen, int(progress.group(1)))
                self.info_set("自动战斗进度", f"{progress.group(1)}/{progress.group(2)}")
            in_battle = (
                keyword_match_count(progress_text, (IN_BATTLE_TEXT,)) >= 1
                or keyword_match_count(self._boxes_text(buttons), (STOP_AUTO_TEXT,)) >= 1
            )
            back = self._box_with(buttons, (RESULT_BACK_TEXT,))
            if in_battle:
                calm = 0
            elif back is not None:
                # Two calm frames: the result screen, not a transition flash.
                calm += 1
                if calm >= 2:
                    if not self._leave_result_screen():
                        self._failed("战斗结果页按「返回」一直离不开")
                        return None
                    return max(seen, planned)
            else:
                calm = 0
                if self._dismiss_ap_shortage():
                    return max(seen, 1)
            self.sleep(1.5)
        self.log_info("活动每日战斗：自动战斗超时。")
        self._failed("自动战斗超过时间还没打完")
        return None

    def _leave_result_screen(self) -> bool:
        """Press 返回 until the result buttons are gone (click-verify-retry)."""
        for attempt in range(1, RESULT_BACK_ATTEMPTS + 1):
            buttons = self._roi_boxes(self.capture_frame(), RESULT_BUTTONS_ROI, "战斗结果")
            back = self._box_with(buttons, (RESULT_BACK_TEXT,))
            if back is None:
                return True
            if attempt > 1:
                self.log_info(f"活动每日战斗：第{attempt}次点击返回。")
            self._click_box(back, after_sleep=2.5)
        buttons = self._roi_boxes(self.capture_frame(), RESULT_BUTTONS_ROI, "战斗结果")
        if self._box_with(buttons, (RESULT_BACK_TEXT,)) is None:
            return True
        self.log_info("活动每日战斗：结果页多次点击返回仍未离开。")
        return False

    def _dismiss_ap_shortage(self) -> bool:
        """Cancel the 活动AP不足 popup; its other button (补充) spends paid resources."""
        boxes = self._roi_boxes(self.capture_frame(), DIALOG_ROI, "AP不足")
        if keyword_match_count(self._boxes_text(boxes), (AP_SHORT_TEXT,)) < 1:
            return False
        self.log_info("活动每日战斗：活动AP不足，取消（不补充）。")
        # Only a read 取消 box is clicked: a fixed point would sit next to
        # 补充, which spends paid resources.
        for _read in range(AP_SHORT_CANCEL_READS):
            cancel = self._box_with(boxes, (CANCEL_TEXT,))
            if cancel is not None:
                self._click_box(cancel, after_sleep=1.0)
                return True
            self.sleep(0.5)
            boxes = self._roi_boxes(self.capture_frame(), DIALOG_ROI, "AP不足")
        self.log_warning("活动每日战斗：AP不足弹窗读不到「取消」，不点击，留给回到主页处理。")
        return True

    # -- quick battle -------------------------------------------------------

    def _run_quick_battle(self) -> str:
        """Quick-battle challenge stage 15 once both modes are cleared.

        Calibrated live at 1080p, 2026-09-28: 快速战斗 opens a dialog with
        the 仅使用免费活动AP switch, MIN/-10/+10/MAX and 战斗 N; the battles
        finish at once behind a REWARD overlay.  The same free-AP guards as
        auto battle apply: the switch must read on and N may not exceed the
        free AP read from the top bar.
        """
        opened = self._open_mode(CHALLENGE_MODE)
        if opened != "ok":
            return opened
        state = self._stable_stage_state(CHALLENGE_MODE)
        if state["auto"] or not state["quick"]:
            return self._failed("挑战战斗的关卡页没看到「快速战斗」")
        if state["free_ap"] is None:
            return self._failed("挑战战斗关卡页上方的活动AP没读到")
        wanted = min(self._usable_ap(state), self._battle_budget())
        if wanted <= 0:
            return "no_ap"
        if state["stage"] != LAST_STAGE:
            self.log_info(f"活动每日战斗：挑战战斗选中第{state['stage']}关，不是第15关。")
            return "skipped"
        if not self._open_quick_dialog():
            return self._failed("按了「快速战斗」，窗口没打开")
        cost = self._set_quick_count(wanted, state)
        if cost is None:
            self._click_reference(*QUICK_DIALOG_CANCEL_POINT, after_sleep=1.0)
            return "failed"
        if cost == 0:
            self.log_info(
                f"活动每日战斗：快速战斗窗口按 MAX 后是 0 场，{self._no_ap_text()}，关掉窗口。"
            )
            self._click_reference(
                *QUICK_DIALOG_CANCEL_POINT, after_sleep=1.0  # 不用确认：回主页会再确认
            )
            return "no_ap"
        self.info_set("当前阶段", f"挑战战斗15：快速战斗 {cost} 场")
        self.log_info(f"活动每日战斗：挑战战斗第15关快速战斗 {cost} 场。")
        boxes = self._roi_boxes(self.capture_frame(), QUICK_DIALOG_START_ROI, "快速战斗开始")
        start = self._box_with(boxes, ("战斗",))
        if start is None:
            self._click_reference(*QUICK_DIALOG_CANCEL_POINT, after_sleep=1.0)
            return self._failed("快速战斗窗口里没找到「战斗」")
        self._click_box(start, after_sleep=1.0)
        result = self._wait_quick_result()
        if result == "no_ap":
            return "no_ap"
        if result != "done":
            return self._failed("快速战斗后没看到奖励画面")
        self._battles_done += cost
        return "done"

    def _quick_dialog_open(self) -> bool:
        boxes = self._roi_boxes(self.capture_frame(), QUICK_DIALOG_ROI, "快速战斗窗口")
        return keyword_match_count(self._boxes_text(boxes), QUICK_DIALOG_KEYWORDS) >= 2

    def _open_quick_dialog(self) -> bool:
        for attempt in range(1, START_CLICK_ATTEMPTS + 1):
            boxes = self._roi_boxes(self.capture_frame(), BOTTOM_BUTTONS_ROI, "关卡按钮")
            button = self._box_with(boxes, (QUICK_BATTLE_TEXT,))
            if button is None:
                return False
            self._sleep_after_recognition()
            self._click_box(button, after_sleep=1.0)
            end_at = monotonic() + 4.0
            while monotonic() <= end_at:
                if self._dismiss_ap_shortage():
                    return False
                if self._quick_dialog_open():
                    return True
                self.sleep(0.4)
            self.log_info(f"活动每日战斗：第{attempt}次点击快速战斗未打开窗口。")
        return False

    def _quick_cost(self) -> int | None:
        boxes = self._roi_boxes(self.capture_frame(), QUICK_DIALOG_START_ROI, "快速战斗开始")
        cost = parse_battle_cost(self._boxes_text(boxes))
        self.info_set("快速战斗场数", cost if cost is not None else "-")
        return cost

    def _set_quick_count(self, wanted: int, state: dict) -> int | None:
        free_only = bool(self.config.get("仅使用免费活动AP", True))
        free = state["free_ap"] or 0
        if free_only and not self._ensure_free_ap_switch_on(
            QUICK_FREE_AP_SWITCH_POINT, QUICK_FREE_AP_SWITCH_ROI
        ):
            self._failed("没能确认「仅使用免费活动AP」开着，所以没开打")
            return None
        cost = self._max_count(QUICK_DIALOG_MAX_POINT, self._quick_cost)
        if cost == 0:
            return 0
        if cost is not None and cost > wanted:
            self._click_reference(*QUICK_DIALOG_MIN_POINT, after_sleep=0.6)
            for _ in range(wanted - 1):
                self._click_reference(*QUICK_DIALOG_PLUS_POINT, after_sleep=0.3)
            cost = self._settled_cost(self._quick_cost)
        if cost is None or cost <= 0 or cost > wanted or (free_only and cost > free):
            self.log_info(
                f"活动每日战斗：快速战斗场数校验失败（{cost}/{wanted}，免费AP {free}）。"
            )
            self._failed(f"场数对不上（读到 {cost}，要打 {wanted}，免费AP {free}），所以没开打")
            return None
        return cost

    def _wait_quick_result(self) -> str:
        """done once the REWARD overlay showed and was closed; no_ap / failed."""
        end_at = monotonic() + QUICK_RESULT_TIMEOUT
        while monotonic() <= end_at:
            if self._dismiss_ap_shortage():
                return "no_ap"
            text = self._boxes_text(
                self._roi_boxes(self.capture_frame(), QUICK_RESULT_ROI, "快速战斗结果")
            )
            if keyword_match_count(text, QUICK_RESULT_KEYWORDS) >= 2:
                self.info_set("快速战斗结果", text)
                self._click_reference(*QUICK_RESULT_DISMISS_POINT, after_sleep=1.0)
                return "done"
            self.sleep(0.5)
        if self._quick_dialog_open():
            self._click_reference(*QUICK_DIALOG_CANCEL_POINT, after_sleep=1.0)
        self.log_info("活动每日战斗：快速战斗后没有看到奖励画面。")
        return "failed"
