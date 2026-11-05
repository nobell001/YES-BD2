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

import json
import re
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np
from ok import Config
from ok.util.file import get_relative_path
from qfluentwidgets import FluentIcon

from src.tasks import run_report
from src.tasks.claim_page import BACK_BUTTON_POINT
from src.tasks.recovery import recover_to_home
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils import field_battle, image_io
from src.utils.colour_rules import switch_yellow_ratio
from src.utils.free_switch import ensure_free_switch_on
from src.utils.frozen_screen import FrozenScreen
from src.utils.image_utils import template_match_response
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text
from src.utils.press_confirm import SLOW_PC_GRACE_SECONDS, wait_for
from src.utils.wait_limits import LOADING_MAX_SECONDS, ProgressWait, is_loading_dark

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
QUICK_RESULT_TIMEOUT = 10.0
# A lost battle (B站 players 界限突破神孙策 and 岩盐咸, 2026-10-14: a 挑战战斗 stage
# too hard for their team, e.g. 15, left the run on the defeat screen).  The
# chain was only ever followed to the win screen's bottom-right 返回; the
# defeat screen (Leo's 2560x1440 frame, 2026-10-14) has a red DEFEAT band in
# the middle and 返回 / 重新挑战 at the bottom centre (1080p x 850-1100, y 978),
# outside that box, so the watch waited 单场战斗超时秒数 x battles.  It is read
# wide; either DEFEAT or 重新挑战 tells it.  返回 leaves it; 重新挑战 (another
# battle) is never pressed.
DEFEAT_ROI = (160, 60, 1600, 1000)
DEFEAT_KEYWORDS = ("DEFEAT", "重新挑战", "失败", "战败", "败北")
DEFEAT_LEAVE_TEXTS = ("返回", "确认", "确定", "关闭")
# Leo 2026-10-14 「不會導致戰鬥到一半被終止吧」: nothing that could end a battle
# (a pause menu's 放弃/退出/撤退) or start one is ever pressed here.
DEFEAT_NEVER_PRESS = ("重新", "再次", "重试", "再战", "补充", "放弃", "退出", "撤退", "离开", "RETRY")
DEFEAT_LEAVE_ATTEMPTS = 3
DEFEAT_BLANK_POINT = (960, 140)
# Out of battle, with neither result screen read, this long: a screen the
# watch does not know (the chain normally moves on within a few seconds).
# Leo 2026-10-14 「認不出畫面要等30秒太久 8秒就可以了」.  Only one blank-area
# tap is tried there, never Esc or a button: a skill animation that hides the
# battle text must not get a pause menu, and the battle is never ended.  The
# battle text coming back counts as still fighting.
UNKNOWN_END_SECONDS = 8.0
# Leo 2026-10-14 「如果要等待不要再有20幾30秒這種這麼長的時間頂多等8秒10秒」: every
# wait for a page or a cue is 10 s at most (battles themselves are not waits).
MAX_WAIT_SECONDS = 10.0
AFTER_BATTLE_PAGE_SECONDS = MAX_WAIT_SECONDS
FREE_AP_SWITCH_YELLOW_RATIO = 0.05
FREE_AP_SWITCH_SETTLE_SECONDS = 2.5
AP_SHORT_CANCEL_READS = 3
# After a failure: longest wait for a running chain to reach its result.
FAIL_SETTLE_SECONDS = 300.0
BANNER_CLICK_ATTEMPTS = 3
BANNER_POSITION_TOLERANCE = 24
HUB_RETRY_SECONDS = 6.0
MODE_CLICK_ATTEMPTS = 3
# The hub check reads the row's boxes as one text, so OCR cutting a button in
# two (「挑战」「战斗」) passes it while a one-box lookup finds nothing.  A
# player's 2560x1440 run stopped 「活动页里没找到「挑战战斗」」 right after the
# hub check passed (2026-10-11): a cut button or a next frame without it, not
# proven which, so the lookup joins pieces and looks again for 2 s.  Pieces on
# one line closer than this many text heights are one button.
MODE_BUTTON_JOIN_GAP = 1.5
# OCR may drop or change one character of a mode's name (a 4K hub frame
# scaled to 1080 read 「挑战战」, 2026-10-11): the first two characters, which
# tell the modes apart, plus two of the other three are enough.
MODE_NAME_MIN_TAIL = 1
# The two modes' icons are the same white crossed swords: the left pair is
# 普通战斗, the right one 挑战战斗 (Leo 2026-10-11 「左邊都是普通戰鬥 右邊是挑戰戰鬥」
# 「白色部分」).  Matched on white pixels only, so the ornate frame and the
# event art behind it do not count.
SWORD_ICON_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "recognition-assets" / "template-assets" / "event" / "event_battle_swords_white.png"
)
SWORD_ICON_ROI = (300, 760, 1320, 200)
SWORD_ICON_SCORE = 0.7
# White = at least this share of the band's brightest value, little colour.
SWORD_WHITE_SHARE = 0.8
SWORD_WHITE_FLOOR = 90
SWORD_WHITE_MAX_SATURATION = 60
SWORD_ICON_LABEL_OFFSET = 150  # icon centre to its name label, 1080p pixels (847 -> 997)
# Last resort, where the labels sit on the Loyal Maid hub (4K, 2026-10-11).
MODE_USUAL_POINTS = {"普通战斗": (678, 997), "挑战战斗": (865, 997)}
START_CLICK_ATTEMPTS = 3
START_CONFIRM_SECONDS = MAX_WAIT_SECONDS
RESULT_BACK_ATTEMPTS = 3
RESULT_BUTTONS_ROI = (1300, 960, 620, 100)
PROGRESS_ROI = (0, 880, 760, 190)
# The stage list on the left: its numbers (Leo's 普通战斗10/11 frames,
# 2026-10-10, numbers at x 250-310, rows about 99 apart).
STAGE_LIST_ROI = (220, 120, 140, 960)
# Read numbers off the line through the others by more than this: a misread.
STAGE_LIST_ROW_TOLERANCE = 24
# Scrolling the list when a stage is not on it (centre of STAGE_LIST_ROI as a
# share of the client; one wheel notch is 120).  Not seen live yet.
STAGE_LIST_SCROLL_POINT = ((220 + 70) / 1920, (120 + 480) / 1080)
STAGE_LIST_SCROLL_AMOUNT = 120
STAGE_LIST_SCROLLS = 2
# The page can draw its title and stage before the top bar's AP (a player's
# 1080p run, 2026-10-10): the AP is read for up to this long.
AP_READ_SECONDS = 5.0
STATE_KEYS = ("stage", "free_ap", "auto", "quick")
# Stuck on the event page (a player's v0.1.30 run after clearing 挑战15 by
# hand stayed there until stopped; Leo 2026-10-13 「把保護機制加上就好」「3 分鐘
# 太久了 卡住卡個10秒就很怪了」).  The event art moves, so the frozen-screen
# watch (frozen_screen.py) cannot see it: this long without a press or a new
# page, stage or battle goes home and tries once more, then 一键日常 goes on.
# Paused while battles run.  10 s (Leo 2026-10-14 「頂多等8秒10秒」): the
# loading after the banner and mode presses is about 8 s at 2K, and the
# carousel wait on 主页 starts the count over.  The black loading screen
# does not count, up to LOADING_MAX_SECONDS of it (Leo 2026-10-15 「我說的10秒
# 是卡死 或者辨識不到」「你單純等載入怎麼可以改成只等10秒」).
PAGE_STUCK_SECONDS = MAX_WAIT_SECONDS

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
# Settings asked for by the same players (2026-10-14).
NORMAL_ONLY_KEY = "只刷普通难度"
CHALLENGE_CAP_KEY = "挑战战斗最高关卡"
# Set once by load_config for players who had the settings before (Leo
# 2026-10-14: 只刷普通难度 back off, then the one-time walk-through in
# src/ui/shell/new_setting_notice.py, like 快速狩猎's).
EVENT_NOTICE_KEY = "_活动战斗新设定提示"
# Quick battle only exists on stages 5, 10 and 15 of both modes (Leo
# 2026-10-14 「快速戰鬥只能選 5 10 15 普通挑戰都是」), so the cap is one of them.
CAP_STAGES = (5, 10, 15)
CAP_OPTIONS = [str(stage) for stage in CAP_STAGES]

# The pool may sit right after the event currency ("8,500 0/5"); refuse a
# match that starts inside another number so "8,5000/5" is not read as 5000.
# OCR often glues the two (live 2026-10-09: "5,9005/5" for 5,900 and 5/5), so
# the currency's three digits after its comma are split off first.  The comma
# can read as a dot (a player's 1080p frame, 2026-10-10: "5.650").
CURRENCY_GLUED_PATTERN = re.compile(r"(?<![\d,.])(\d{1,3}(?:[,.]\d{3})+)(?=\d)")
AP_PATTERN = re.compile(r"(?<![\d,.])(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")
BONUS_PATTERN = re.compile(r"\+\s*(\d+)")
# The bonus beside the pool is a few AP; more digits than this is a misread.
AP_BONUS_MAX = 99
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
    # 1080p, 2026-10-10) is not stripped to a guess: any AP above 0 opens the
    # dialog, whose MAX with 仅使用免费活动AP on decides the count (Leo 08:58Z
    # 「超過上限 一樣點開來打 不要去前面字 大於0 就是點開來打就對了」).  It counts
    # as the top itself, never more (Leo 2026-10-14: every value in a sane
    # range), so the free-AP cost check still holds.
    free = None
    if free_match:
        free = min(int(free_match.group(1)), int(free_match.group(2)))
    tail = normalized[free_match.end():] if free_match else normalized
    bonus_match = BONUS_PATTERN.search(tail)
    bonus = int(bonus_match.group(1)) if bonus_match else 0
    return free, bonus if bonus <= AP_BONUS_MAX else 0


def parse_battle_cost(text: str) -> int | None:
    """Return N from the dialog start button text '战斗 N' (OCR may add noise)."""
    cleaned = re.sub(r"[^\d战斗]", " ", str(text))
    if "战斗" not in cleaned:
        return None
    match = COST_PATTERN.search(cleaned.strip())
    return int(match.group(1)) if match else None


def mode_name_in(text: str, mode: str) -> bool:
    """``mode`` in ``text``, allowing one dropped or changed later character."""
    normalized = normalize_ocr_text(text)
    if mode in normalized:
        return True
    head, tail = mode[:2], mode[2:]
    for start in (m.start() for m in re.finditer(re.escape(head), normalized)):
        after = normalized[start + 2 : start + 2 + len(tail)]
        same = sum(a == b for a, b in zip(after, tail))
        if same >= len(tail) - 1 and same >= MODE_NAME_MIN_TAIL:
            return True
    return False


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
                NORMAL_ONLY_KEY: False,
                CHALLENGE_CAP_KEY: str(LAST_STAGE),
                "横幅轮播等待秒数": MAX_WAIT_SECONDS,
                "单场战斗超时秒数": 240.0,
                EVENT_NOTICE_KEY: False,
            }
        )
        self.config_description.update(
            {
                "仅使用免费活动AP": "只用每日免费活动AP（顶部 a/5），不动用额外的 +AP。",
                "每次最多战斗场数": "一次运行最多进行的战斗场数（0 表示用完可用AP）。",
                NORMAL_ONLY_KEY: "完全不打挑战战斗；普通战斗通关后，剩下的AP用快速战斗刷普通战斗15。",
                CHALLENGE_CAP_KEY: "挑战战斗只推到这一关（快速战斗只有第5、10、15关）；到了之后剩下的AP用快速战斗刷这一关。",
                "横幅轮播等待秒数": "横幅轮播到别的活动时，最多等待多久让它转回来。",
                "单场战斗超时秒数": "自动战斗每一场允许的最长时间，超时视为失败。",
            }
        )
        # Leo 2026-10-14: the remaining AP always goes to quick battle (no
        # setting to turn it off), and the cap row hides while only normal
        # is fought.
        self.config_type.update(
            {
                CHALLENGE_CAP_KEY: {"type": "drop_down", "options": CAP_OPTIONS},
                NORMAL_ONLY_KEY: {"sub_configs": {False: [CHALLENGE_CAP_KEY]}},
            }
        )
        self._battles_done = 0
        self._why = ""
        self._page_deadline = None

    def load_config(self):
        # Saved settings from before this update: 只刷普通难度 goes back off
        # and the cap back to 15 (Leo 2026-10-14 「把它改成不打勾」「預設要不勾而且
        # 挑戰關15」), and the tool shows the settings once.  A new install has no file and starts unticked anyway.
        path = Path(get_relative_path(Config.config_folder, f"{self.__class__.__name__}.json"))
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            saved = {}
        super().load_config()
        if isinstance(saved, dict) and saved and EVENT_NOTICE_KEY not in saved:
            self.config[NORMAL_ONLY_KEY] = False
            self.config[CHALLENGE_CAP_KEY] = str(LAST_STAGE)
            self.config[EVENT_NOTICE_KEY] = True

    # -- stuck-page guard ---------------------------------------------------

    def capture_frame(self, screenshot_name: str | None = None):
        deadline = getattr(self, "_page_deadline", None)
        if deadline is not None and monotonic() > deadline:
            # Raised again on every later frame until run_claim ends: a look
            # that swallows errors (the shared popup check) or a press after
            # it cannot turn the guard off.
            self._page_stuck = True
        if getattr(self, "_page_stuck", False):
            step = str((getattr(self, "info", None) or {}).get("当前阶段") or "").strip()
            where = f"在活动页（{step}）" if step else "在活动页"
            raise _StuckOnEventPage(
                f"{where} {PAGE_STUCK_SECONDS:.0f} 秒没走到下一步（点了没反应或认不出画面）"
            )
        frame = super().capture_frame(screenshot_name)
        if deadline is not None:
            self._loading_pushes_guard(frame)
        return frame

    def _loading_pushes_guard(self, frame) -> None:
        """A black loading frame pushes the guard back, up to
        LOADING_MAX_SECONDS from when the loading started."""
        now = monotonic()
        if not is_loading_dark(frame):
            self._loading_since = None
            return
        since = getattr(self, "_loading_since", None)
        if since is None:
            since = self._loading_since = now
        pushed = min(since + LOADING_MAX_SECONDS, now + PAGE_STUCK_SECONDS)
        self._page_deadline = max(self._page_deadline, pushed)

    @staticmethod
    def _page_wait(timeout: float) -> ProgressWait:
        """``timeout``, stretched only by the black loading screen (up to
        LOADING_MAX_SECONDS): the event art keeps moving, so movement does
        not count here (see ``_page_wait_over``)."""
        return ProgressWait(monotonic(), stuck=max(0.0, timeout), cap=max(timeout, LOADING_MAX_SECONDS))

    @staticmethod
    def _page_wait_over(wait: ProgressWait, frame) -> bool:
        # No picture to the still timer: only the loading screen resets it.
        return wait.over(None, monotonic(), loading=is_loading_dark(frame))

    def operate(self, func, block: bool = True, restore_cursor: bool = True):
        self._progressed()  # a press is a step too
        return super().operate(func, block=block, restore_cursor=restore_cursor)

    def _progressed(self) -> None:
        """A page, stage or battle was reached: the guard starts over."""
        if getattr(self, "_page_deadline", None) is not None:
            self._page_deadline = monotonic() + PAGE_STUCK_SECONDS

    def _pause_guard(self) -> None:
        self._page_deadline = None
        self._page_stuck = False

    def _resume_guard(self) -> None:
        self._page_deadline = monotonic() + PAGE_STUCK_SECONDS

    # -- task entry ---------------------------------------------------------

    def run_claim(self) -> bool:
        self._battles_done = 0
        self._why = ""
        self._resume_guard()
        try:
            # _StuckOnEventPage goes on up: the run goes home and tries again
            # once (BaseBD2Task._run_watched).
            return self._run_claim()
        finally:
            self._pause_guard()

    def _run_claim(self) -> bool:
        self._defeated = False
        self._lost_stage = None
        modes = self._modes()
        farm = None  # (mode, stage) for the AP left once nothing more can be pushed
        stuck: list[str] = []
        done_text = "完成"
        for mode in modes:
            if self._battle_budget() <= 0:
                break
            result = self._run_mode(mode)
            if result == "no_event":
                return self._no_event()
            if result == "failed":
                return self._event_fail(mode)
            if result == "no_ap":
                return self._finish(self._no_ap_text())
            if result == "defeated":
                return self._finish_defeated(mode)
            if result == "stuck":
                # The next stage may simply not be open yet (events unlock
                # stages over days): the next mode still gets its turn, but
                # nothing is quick-battled today.
                where = getattr(self, "_stuck_stage", None)
                where = f"第{where}关" if where else "已通关的关卡"
                stuck.append(f"{mode}停在{where}，下一关没认出来")
                continue
            if result == "capped":
                farm = (mode, self._stage_cap(mode))
                done_text = f"{mode}已推到设定的第{farm[1]}关"
                break
            if result != "cleared":
                return self._finish(f"{mode}已推进")
        else:
            farm = None if stuck else (modes[-1], self._stage_cap(modes[-1]))
        if stuck and farm is None:
            note = "；".join(stuck) + "。活动AP留着没用（不会拿去快速战斗还没推到的关卡）"
            self.log_warning(f"活动每日战斗：{note}", notify=True)
            run_report.add_current_note(note)
            return self._finish("没推到设定的关卡，没有快速战斗")
        if farm and self._battle_budget() > 0:
            mode, stage = farm
            label = f"{mode}{stage}快速战斗"
            result = self._run_quick_battle(mode, stage)
            if result == "no_event":
                return self._no_event()
            if result == "failed":
                return self._event_fail(label)
            if result == "skipped":
                note = (
                    f"{done_text}，但快速战斗没执行：{mode}左边列表里没选到第{stage}关，"
                    "今天剩下的活动AP没用掉"
                )
                self.log_warning(f"活动每日战斗：{note}。", notify=True)
                run_report.add_current_note(note)
                return self._finish("快速战斗未执行")
            if result == "no_ap":
                return self._finish(f"{done_text}，{self._no_ap_text()}")
            return self._finish(f"{done_text}，已用快速战斗刷{mode}{stage}")
        return self._finish(done_text)

    def _finish_defeated(self, mode: str) -> bool:
        """A lost battle ends today's event battles (Leo 2026-10-14 「挑戰失敗的話
        就直接回主畫面每日五場就不打了且要在報表跟玩家說明」)."""
        where = f"{mode}第{self._lost_stage}关" if self._lost_stage else mode
        note = (
            f"{where}打输了，今天的活动战斗不再继续，已回主页。"
            "可以把「挑战战斗最高关卡」设成打得过的关卡，或打开「只刷普通难度」"
        )
        run_report.add_current_note(note)
        return self._finish(f"{where}打输了，今天不再打")

    def _modes(self) -> tuple[str, ...]:
        if bool(self.config.get(NORMAL_ONLY_KEY, False)):
            return (NORMAL_MODE,)
        return MODES

    def _stage_cap(self, mode: str) -> int:
        """The last stage auto battle may push ``mode`` to (挑战战斗最高关卡)."""
        if mode != CHALLENGE_MODE:
            return LAST_STAGE
        try:
            cap = int(str(self.config.get(CHALLENGE_CAP_KEY, LAST_STAGE)).strip())
        except (TypeError, ValueError):
            cap = LAST_STAGE
        # A stage without quick battle is rounded down to one that has it.
        return max([stage for stage in CAP_STAGES if stage <= cap] or [CAP_STAGES[0]])

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
        self._pause_guard()
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
        self._pause_guard()
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
        looked = False  # 至少看一次：时间已到也先看一眼再说没看到
        while not looked or monotonic() <= end_at:
            looked = True
            frame = self.capture_frame()
            if self._in_battle(frame) or self._auto_battle_shown(frame):
                calm = 0
                self.info_set("当前阶段", "失败后等待战斗结束")
                self.sleep(2.0)
                continue
            buttons = self._roi_boxes(frame, RESULT_BUTTONS_ROI, "战斗结果")
            if self._box_with(buttons, (RESULT_BACK_TEXT,)) is None:
                if self._defeat_shown(frame):
                    self._leave_defeat_screen()
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
        self._progressed()  # the carousel wait has its own limit
        wait = float(self.config.get("横幅轮播等待秒数", MAX_WAIT_SECONDS))
        end_at = monotonic() + min(max(wait, 0.0), MAX_WAIT_SECONDS)
        tolerance = BANNER_POSITION_TOLERANCE / REFERENCE_WIDTH * max(1, int(self.width))
        looked = False  # 至少看一次：时间已到也先看一眼再说没看到
        while not looked or monotonic() <= end_at:
            looked = True
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
            self._click_reference(*BACK_BUTTON_POINT, after_sleep=1.0)  # 不用确认：下面等活动首页，没等到就回主页
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
            self._click_box(banner, after_sleep=1.0)  # 不用确认：循环里还在主页就再点横幅
            if self._wait_for_hub(timeout=HUB_RETRY_SECONDS):
                return "ok"
            if self._wait_for_home_confirmation("活动横幅重试前主页确认", timeout=2.0):
                # Swallowed click: still on home, look for the banner again.
                self.log_info(f"活动每日战斗：第{attempt}次点击横幅未生效，重试。")
                continue
            # Left home (loading): give the hub its full time.
            if self._wait_for_hub(timeout=MAX_WAIT_SECONDS):
                return "ok"
            return self._failed("点了活动横幅后，活动页一直没出来")
        return self._failed(f"活动横幅点了 {BANNER_CLICK_ATTEMPTS} 次都没进活动页")

    def _wait_for_hub(self, timeout: float = MAX_WAIT_SECONDS) -> bool:
        wait = self._page_wait(timeout)
        while True:
            frame = self.capture_frame()
            if not is_loading_dark(frame):
                boxes = self._roi_boxes(frame, HUB_BUTTON_ROI, "活动页")
                text = self._boxes_text(boxes)
                self.info_set("活动页 OCR", text or "-")
                if self._hub_shown(frame, text):
                    self._progressed()
                    return True
            if self._page_wait_over(wait, frame):
                return False
            self.sleep(0.8)

    @staticmethod
    def _hub_shown(frame, text: str) -> bool:
        """Both modes' names, or one name and the two crossed-swords icons."""
        named = sum(mode_name_in(text, mode) for mode in HUB_KEYWORDS)
        return named == len(HUB_KEYWORDS) or (named >= 1 and len(sword_icon_points(frame)) == 2)

    def _open_mode(self, mode: str) -> str:
        """Open one mode's stage page from home: ok / no_event / failed."""
        entered = self._enter_hub()
        if entered != "ok":
            return entered
        for attempt in range(1, MODE_CLICK_ATTEMPTS + 1):
            self._hub_read = ""
            button = wait_for(
                lambda: self._mode_button(mode), SLOW_PC_GRACE_SECONDS, sleep=self.sleep, poll=0.5
            )
            missed = f"活动页里没找到「{mode}」（下方读到：{self._hub_read[:40] or '-'}）"
            usual = button is None
            if usual:
                # Pressed once only: the hub was seen, a wrong spot opens nothing paid.
                button = self._usual_mode_button(self.capture_frame(), mode)
            if button is None:
                return self._failed(missed)
            self._sleep_after_recognition()
            self._click_box(button, after_sleep=1.5)  # 不用确认：循环里还在活动页就再点
            if self._wait_for_stage_page(mode, timeout=HUB_RETRY_SECONDS, quiet=True):
                return "ok"
            if usual:
                return self._failed(f"{missed}，照平常位置点了一下也没进关卡页")
            if self._wait_for_hub(timeout=2.0):
                self.log_info(f"活动每日战斗：第{attempt}次点击{mode}未生效，重试。")
                continue
            if self._wait_for_stage_page(mode):
                return "ok"
            return self._failed(f"点了「{mode}」后关卡页一直没出来")
        return self._failed(f"「{mode}」点了 {MODE_CLICK_ATTEMPTS} 次都没进关卡页")

    def _mode_button(self, mode: str):
        """The hub's ``mode`` button on a fresh frame, also when OCR cut it in two."""
        frame = self.capture_frame()
        boxes = self._roi_boxes(frame, HUB_BUTTON_ROI, "活动页")
        self._hub_read = self._boxes_text(boxes)
        whole = next((b for b in boxes if mode_name_in(getattr(b, "name", ""), mode)), None)
        return whole or self._joined_box(boxes, mode) or self._sword_button(frame, mode)

    def _sword_button(self, frame, mode: str):
        """The mode's label under its crossed-swords icon, when exactly two show."""
        points = sword_icon_points(frame)
        if len(points) != 2:
            return None
        x, y = points[0] if mode == NORMAL_MODE else points[1]
        scale = frame.shape[0] / REFERENCE_HEIGHT
        self.log_info(f"活动每日战斗：没读到「{mode}」的字，按双剑图示认出它的位置。")
        return SimpleNamespace(name=mode, x=x - 1, y=y + SWORD_ICON_LABEL_OFFSET * scale - 1,
                               width=2, height=2)

    def _usual_mode_button(self, frame, mode: str):
        """Last resort: where the mode's label usually sits (Leo 2026-10-11)."""
        point = MODE_USUAL_POINTS.get(mode)
        if point is None:
            return None
        sx = frame.shape[1] / REFERENCE_WIDTH
        sy = frame.shape[0] / REFERENCE_HEIGHT
        self.log_info(f"活动每日战斗：字和图示都没认出「{mode}」，照它平常的位置点一下。")
        return SimpleNamespace(name=mode, x=point[0] * sx - 1, y=point[1] * sy - 1,
                               width=2, height=2)

    @classmethod
    def _joined_box(cls, boxes: list, word: str):
        """Two or three neighbouring boxes on one line that only together read ``word``."""
        wanted = normalize_ocr_text(word)
        placed = []
        for box in boxes:
            values = tuple(getattr(box, key, None) for key in ("x", "y", "width", "height"))
            if wanted and None not in values:
                placed.append((tuple(float(v) for v in values), normalize_ocr_text(box.name)))
        for first in placed:
            line = sorted(
                (p for p in placed if p[0][0] >= first[0][0] and cls._same_line(first[0], p[0])),
                key=lambda p: p[0][0],
            )
            for count in (2, 3):
                parts = line[:count]
                if len(parts) < count or not cls._close_together(parts):
                    break
                texts = [text for _box, text in parts]
                joined = "".join(texts)
                at = joined.find(wanted)
                # The word must start in the first piece and end in the last.
                last_starts = len(joined) - len(texts[-1])
                if at < 0 or at >= len(texts[0]) or at + len(wanted) <= last_starts:
                    continue
                left = min(b[0] for b, _t in parts)
                top = min(b[1] for b, _t in parts)
                right = max(b[0] + b[2] for b, _t in parts)
                bottom = max(b[1] + b[3] for b, _t in parts)
                return SimpleNamespace(
                    name=joined, x=left, y=top, width=right - left, height=bottom - top
                )
        return None

    @staticmethod
    def _same_line(a: tuple, b: tuple) -> bool:
        height = max(a[3], b[3], 1.0)
        return abs((a[1] + a[3] / 2) - (b[1] + b[3] / 2)) <= height / 2

    @staticmethod
    def _close_together(parts: list) -> bool:
        """Left to right with gaps of at most MODE_BUTTON_JOIN_GAP text heights."""
        for (a, _ta), (b, _tb) in zip(parts, parts[1:]):
            height = max(a[3], b[3], 1.0)
            if b[0] - (a[0] + a[2]) > MODE_BUTTON_JOIN_GAP * height:
                return False
        return True

    def _wait_for_stage_page(
        self,
        mode: str,
        timeout: float = MAX_WAIT_SECONDS,
        quiet: bool = False,
    ) -> bool:
        wait = self._page_wait(timeout)
        while True:
            frame = self.capture_frame()
            if not is_loading_dark(frame) and self._title_visible(frame, (mode,), mode):
                panel = self._boxes_text(self._roi_boxes(frame, PANEL_TITLE_ROI, f"{mode}关卡"))
                if parse_stage_number(panel, mode) is not None:
                    self._progressed()
                    return True
            if self._page_wait_over(wait, frame):
                break
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
        limit = self._stage_cap(mode)
        while state["stage"] is not None and state["stage"] < limit and not state["auto"]:
            current, target = state["stage"], state["stage"] + 1
            if not self._select_stage(mode, current, target):
                return state
            state = self._stable_stage_state(mode)
        return state

    def _select_stage(
        self, mode: str, current: int, target: int, grace: float = SLOW_PC_GRACE_SECONDS
    ) -> bool:
        """Select stage ``target`` in the left list; True once the panel shows it."""
        point = self.look_again(
            lambda: self._stage_list_point(target),
            f"活动每日战斗：{mode}左边列表找第{target}关",
            grace=grace,
        )
        if point is None:
            self.log_info(
                f"活动每日战斗：{mode}选在第{current}关，左边列表里没认出第{target}关。"
            )
            return False
        self.info_set("当前阶段", f"{mode}：从第{current}关改选第{target}关")
        self._sleep_after_recognition()
        outcome = self.press_and_confirm(
            f"{mode}选第{target}关",
            lambda: self._click_reference(*point, after_sleep=0.8),
            lambda: self._panel_stage(mode) == target,
            still_before=lambda: self._panel_stage(mode) == current,
        )
        if not outcome:
            self.log_info(f"活动每日战斗：{mode}点了第{target}关，右边没换成第{target}关。")
            return False
        self._progressed()
        return True

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
        """Return cleared / capped / defeated / no_ap / progressed / no_event /
        failed for one mode.

        capped: every stage up to 挑战战斗最高关卡 is cleared.  defeated: a
        battle was lost; ``_lost_stage`` is the stage it stopped on.
        """
        opened = self._open_mode(mode)
        if opened != "ok":
            return opened
        cap = self._stage_cap(mode)
        for _round in range(3):
            state = self._stable_stage_state(mode)
            if not state["auto"] and not state["quick"]:
                # Cleared shows 快速战斗; neither is not a page to judge from.
                return self._failed(
                    f"{mode}关卡页右下 {AP_READ_SECONDS:g} 秒都没看到「自动战斗」或「快速战斗」"
                )
            if not state["auto"]:
                state = self._select_unfinished_stage(mode, state)
            if cap < LAST_STAGE and state["stage"] is not None and (
                state["stage"] > cap or (state["stage"] == cap and not state["auto"])
            ):
                self.log_info(f"活动每日战斗：{mode}已推到设定的第{cap}关，不再往后打。")
                return "capped"
            if not state["auto"] and state["stage"] != LAST_STAGE:
                # A cleared stage before the last whose next one could not be
                # selected is not "all cleared": no quick battle may spend the
                # AP before the set stage is reached (Leo 2026-10-14 「千萬不要
                # 他還沒有打到第15關就在第10關把體力拿去快速戰鬥了」).
                self._stuck_stage = state["stage"]
                return "stuck"
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
            if cap < LAST_STAGE and state["stage"] is not None:
                # The chain moves on a stage per win: stop it at the cap.
                wanted = min(wanted, cap - state["stage"] + 1)
            if wanted <= 0:
                return "no_ap"
            self._defeated = False
            fought = self._auto_battle(mode, wanted, state)
            if fought is None:
                return "failed"
            if fought == 0:
                return "no_ap"
            if not self._wait_for_stage_page(mode, timeout=AFTER_BATTLE_PAGE_SECONDS):
                self._battles_done += fought
                return self._failed(f"打完后 {AFTER_BATTLE_PAGE_SECONDS:g} 秒没回到{mode}的关卡页")
            after = self._stable_stage_state(mode)
            # Counted from the dialog (fought >= its 战斗 N), never from the top
            # bar: Windows read Leo's 5/5 as "8,400 25/5" (the AP icon as a 2,
            # 4K PC 2026-10-10), and 25 - 0 counted 25 battles.
            self._battles_done += fought
            lost = getattr(self, "_defeated", False) or (
                after["auto"] and after["stage"] == state["stage"]
            )
            if lost:
                self._lost_stage = after["stage"] if after["stage"] is not None else state["stage"]
                self.log_warning(
                    f"活动每日战斗：{mode}第{self._lost_stage or '?'}关打输了，"
                    "今天的活动战斗不再继续，回主页。",
                    notify=True,
                )
                return "defeated"
            if self._battle_budget() <= 0:
                return "progressed"
        return "progressed"

    def _auto_battle(self, mode: str, wanted: int, state: dict) -> int | None:
        """Open the auto dialog, start ``wanted`` battles, return how many ran."""
        self._sleep_after_recognition()
        opened = False
        for _attempt in range(2):
            self._click_reference(*AUTO_TOGGLE_POINT, after_sleep=1.2)  # 不用确认：循环两次，窗口没出来再按
            if self._dismiss_ap_shortage():
                return 0
            if self._wait_for_dialog():
                opened = True
                break
            if self._dismiss_ap_shortage():
                return 0
            # A swallowed click leaves the stage page untouched; try once more.
            if not self.look_again(lambda: self._stage_state(mode)["auto"]):
                break
        if not opened:
            self._failed("按了自动战斗，选场数的窗口没出来")
            return None
        cost = self._set_dialog_count(wanted, state)
        if cost is None:
            self._click_reference(*DIALOG_CANCEL_POINT, after_sleep=1.0)  # 不用确认：失败了，回主页会再确认
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
        # Battles take their own time (单场战斗超时秒数): no page guard meanwhile.
        self._pause_guard()
        try:
            started = self._start_auto_battle()
            if started == "no_ap":
                return 0
            if started != "started":
                self._failed("按了「战斗」后没开始打")
                return None
            return self._watch_auto_battle(cost, mode)
        finally:
            self._resume_guard()

    def _start_auto_battle(self) -> str:
        """Press 战斗 N and prove a battle began: started / no_ap / failed."""
        for attempt in range(1, START_CLICK_ATTEMPTS + 1):
            boxes = self._roi_boxes(self.capture_frame(), DIALOG_START_ROI, "自动战斗开始")
            start = self._box_with(boxes, ("战斗",))
            if start is None:
                break
            self._click_box(start, after_sleep=1.5)  # 不用确认：循环里没开打、窗口还在就再点
            end_at = monotonic() + START_CONFIRM_SECONDS
            looked = False  # 至少看一次：时间已到也先看一眼再说没看到
            while not looked or monotonic() <= end_at:
                looked = True
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
            self._click_reference(*DIALOG_CANCEL_POINT, after_sleep=1.0)  # 不用确认：失败了，回主页会再确认
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

    def _auto_battle_shown(self, frame) -> bool:
        """The game's own auto-battle line anywhere on screen (「自动战斗中」,
        「结束自动战斗」): still fighting, even when the chain's own text is
        not where the watch reads it (player 2026-10-23, v0.2.9: 「8 秒不在
        战斗中」 while recovery's whole-screen read found the battle).
        Nothing is pressed."""
        return field_battle.auto_on(self._roi_boxes(frame, None, "活动战斗画面"))

    def _wait_in_battle(self, timeout: float) -> bool:
        end_at = monotonic() + timeout
        looked = False  # 至少看一次：时间已到也先看一眼再说没看到
        while not looked or monotonic() <= end_at:
            looked = True
            if self._in_battle(self.capture_frame()):
                return True
            self.sleep(1.0)
        return False

    def _wait_for_dialog(self, timeout: float = 6.0) -> bool:
        end_at = monotonic() + timeout
        looked = False  # 至少看一次：时间已到也先看一眼再说没看到
        while not looked or monotonic() <= end_at:
            looked = True
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
            cost = self._count_from_min(DIALOG_MIN_POINT, DIALOG_PLUS_POINT, wanted, self._dialog_cost)
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

    def _count_from_min(self, min_point, plus_point, wanted: int, read) -> int | None:
        """MIN, then +1 up to ``wanted``; the count read.

        These presses only change the window's count (no AP is spent).  A
        count above ``wanted`` after them means a press was not taken: set
        it once more (Leo 2026-11-05 「所有地方都要有補救方案」).  The caller
        still refuses any count above ``wanted``.
        """
        cost = None
        for attempt in range(2):
            self._click_reference(*min_point, after_sleep=0.6)  # 不用确认：下面读场数，比要的多再设一次
            for _ in range(wanted - 1):
                self._click_reference(*plus_point, after_sleep=0.3)  # 不用确认：下面读场数
            cost = self._settled_cost(read)
            if cost is None or cost <= wanted or attempt:
                return cost
            self.log_info(f"活动每日战斗：场数设成 {wanted} 后读到 {cost}，比要的多，再设一次。")
        return cost

    def _max_count(self, max_point, read) -> int | None:
        """Press MAX and read the count; a 0 gets one more look.

        MAX 0 means no free AP left today (Windows can read the top bar's 0/5
        as 20/5, so the dialog opens anyway).  A slow window may not have
        counted yet, so 0 is only believed on the second look.
        """
        self._click_reference(*max_point, after_sleep=0.8)  # 不用确认：下一行读场数，0 场再按一次
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
            lambda: self._click_reference(*point, after_sleep=0.5),  # 不用确认：只按一次，再按会把认不出亮色的开关关掉（review #28）
            on_above=FREE_AP_SWITCH_YELLOW_RATIO,
            settle=FREE_AP_SWITCH_SETTLE_SECONDS,
            sleep=self.sleep,
            log=self.log_info,
        ):
            return True
        self.log_info("活动每日战斗：无法确认仅用免费活动AP已开启，取消。")
        return False

    def _watch_auto_battle(self, planned: int, mode: str | None = None) -> int | None:
        """Follow the chain until its result screen; return battles counted.

        The count never goes below ``planned``: counting too many only means
        fewer battles later, counting too few could exceed the per-run cap.
        """
        per_battle = float(self.config.get("单场战斗超时秒数", 240.0))
        end_at = monotonic() + per_battle * planned + 60.0
        seen = 0
        calm = 0
        defeat_calm = 0
        busy_at = monotonic()  # last frame in battle or on a known screen
        tapped = False
        looked = False  # 至少看一次：时间已到也先看一眼再说没看到
        while not looked or monotonic() <= end_at:
            looked = True
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
                defeat_calm = 0
                busy_at = monotonic()
                tapped = False
            elif self._defeat_shown(frame):
                # Two calm frames, as for the win screen.
                calm = 0
                defeat_calm += 1
                busy_at = monotonic()
                if defeat_calm >= 2:
                    return self._after_defeat(seen, planned)
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
                defeat_calm = 0
                if self._dismiss_ap_shortage():
                    return max(seen, 1)
                if self._auto_battle_shown(frame):
                    busy_at = monotonic()
                    tapped = False
                elif monotonic() - busy_at > UNKNOWN_END_SECONDS:
                    # Neither battle nor a result screen it knows.
                    if mode and self._wait_for_stage_page(mode, timeout=0.0, quiet=True):
                        return max(seen, planned)  # the chain came back by itself
                    if tapped:
                        self._save_flow_diagnostic(f"{self.claim_log_name}_unknown_end")
                        self._failed(
                            f"打完后停在认不出的画面，等了 {UNKNOWN_END_SECONDS:g} 秒、"
                            "点空白处也没离开"
                        )
                        return None
                    self.log_info(
                        f"活动每日战斗：{UNKNOWN_END_SECONDS:g} 秒不在战斗中也没认出结果画面，点空白处。"
                    )
                    self._click_reference(  # 不用确认：接着照常看画面
                        *DEFEAT_BLANK_POINT, after_sleep=1.0
                    )
                    tapped = True
                    busy_at = monotonic()
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
            self._click_box(back, after_sleep=2.5)  # 不用确认：循环里返回还在就再点
        buttons = self._roi_boxes(self.capture_frame(), RESULT_BUTTONS_ROI, "战斗结果")
        if self._box_with(buttons, (RESULT_BACK_TEXT,)) is None:
            return True
        self.log_info("活动每日战斗：结果页多次点击返回仍未离开。")
        return False

    # -- defeat ---------------------------------------------------------------

    def _defeat_boxes(self, frame=None) -> list:
        return self._roi_boxes(
            self.capture_frame() if frame is None else frame, DEFEAT_ROI, "战斗失败"
        )

    def _defeat_shown(self, frame=None) -> bool:
        text = self._boxes_text(self._defeat_boxes(frame))
        return keyword_match_count(text, DEFEAT_KEYWORDS) >= 1

    @staticmethod
    def _defeat_leave_box(boxes: list):
        """A leave button on the defeat screen; never a retry (another battle)."""
        for found in boxes:
            name = normalize_ocr_text(getattr(found, "name", "")).upper()
            if any(word in name for word in DEFEAT_NEVER_PRESS):
                continue
            if len(name) <= 6 and any(word in name for word in DEFEAT_LEAVE_TEXTS):
                return found
        return None

    def _after_defeat(self, seen: int, planned: int) -> int | None:
        """The chain lost a battle: leave its defeat screen, return battles counted."""
        self._defeated = True
        self.info_set("当前阶段", "战斗失败，离开失败画面")
        self.log_info("活动每日战斗：认出战斗失败画面，离开它。")
        self._save_flow_diagnostic(f"{self.claim_log_name}_defeat")
        if not self._leave_defeat_screen():
            self._failed("战斗打输了，失败画面点「返回」、空白处和 Esc 都离不开")
            return None
        # The chain stops at the lost battle: count it, never more than planned.
        return min(seen, planned) if seen else planned

    def _leave_defeat_screen(self) -> bool:
        """Leave a defeat (or unknown end) screen: a read leave button, else a
        blank-area tap, else Esc (Leo 2026-10-12 「不會點掉就點空白處」「關不掉 就
        按ESC做備案」).  True once neither it nor the win screen's 返回 shows."""

        def gone() -> bool:
            frame = self.capture_frame()
            if self._defeat_shown(frame):
                return False
            buttons = self._roi_boxes(frame, RESULT_BUTTONS_ROI, "战斗结果")
            return self._box_with(buttons, (RESULT_BACK_TEXT,)) is None

        for attempt in range(1, DEFEAT_LEAVE_ATTEMPTS + 1):
            leave = self._defeat_leave_box(self._defeat_boxes())
            if leave is None:
                buttons = self._roi_boxes(self.capture_frame(), RESULT_BUTTONS_ROI, "战斗结果")
                leave = self._box_with(buttons, (RESULT_BACK_TEXT,))
            if leave is not None:
                self.log_info(f"活动每日战斗：失败画面按「{leave.name}」。")
                self._click_box(leave, after_sleep=2.0)  # 不用确认：循环里没离开就点空白、按 Esc
            elif attempt == 1:
                self.log_info("活动每日战斗：失败画面没读到离开的按钮，点空白处。")
                self._click_reference(  # 不用确认：下面 wait_for 看画面有没有离开
                    *DEFEAT_BLANK_POINT, after_sleep=2.0
                )
            else:
                self.log_info("活动每日战斗：失败画面点空白处没离开，按 Esc。")
                tap = getattr(self, "tap_escape", None)
                if not callable(tap) or not tap(after_sleep=2.0):
                    self.sleep(2.0)
            if wait_for(gone, SLOW_PC_GRACE_SECONDS, sleep=self.sleep, poll=1.0):
                self._progressed()
                return True
        self.log_info("活动每日战斗：失败画面多次尝试仍未离开。")
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
                self._click_box(cancel, after_sleep=1.0)  # 不用确认：调用处循环，弹窗还在下一轮再按读到的取消；旁边是补充，不点固定位置
                return True
            self.sleep(0.5)
            boxes = self._roi_boxes(self.capture_frame(), DIALOG_ROI, "AP不足")
        self.log_warning("活动每日战斗：AP不足弹窗读不到「取消」，不点击，留给回到主页处理。")
        return True

    # -- quick battle -------------------------------------------------------

    def _run_quick_battle(self, mode: str = CHALLENGE_MODE, stage: int = LAST_STAGE) -> str:
        """Quick-battle a cleared stage with the AP left (done / no_ap /
        skipped / no_event / failed).

        Challenge 15 once both modes are cleared; the set 挑战战斗最高关卡;
        normal 15 with 只刷普通难度; the stage before a lost one.
        Calibrated live at 1080p, 2026-09-28 (challenge 15): 快速战斗 opens a
        dialog with the 仅使用免费活动AP switch, MIN/-10/+10/MAX and 战斗 N;
        the battles finish at once behind a REWARD overlay.  The same free-AP
        guards as auto battle apply: the switch must read on and N may not
        exceed the free AP read from the top bar.  Other stages and 普通战斗
        are assumed to use the same dialog (not seen live yet).
        """
        opened = self._open_mode(mode)
        if opened != "ok":
            return opened
        state = self._stable_stage_state(mode)
        if state["free_ap"] is not None and min(self._usable_ap(state), self._battle_budget()) <= 0:
            return "no_ap"
        picked = self._pick_quick_stage(mode, state, stage)
        if picked is None:
            return "skipped"
        state, stage = picked
        if state["free_ap"] is None:
            # A player's v0.1.32 run (1921x1080 window, 150%, 2026-10-14)
            # stopped 「挑战战斗关卡页上方的活动AP没读到」 with both modes
            # cleared.  As for auto battle (Leo 2026-10-10 「應該雙重保險」),
            # the dialog decides: its 仅使用免费活动AP switch on and MAX.
            self.log_info(
                f"活动每日战斗：{mode}关卡页上方的活动AP没读到，改看快速战斗窗口的场数。"
            )
            wanted = self._battle_budget()
        else:
            wanted = min(self._usable_ap(state), self._battle_budget())
        if wanted <= 0:
            return "no_ap"
        if not self._open_quick_dialog():
            return self._failed("按了「快速战斗」，窗口没打开")
        cost = self._set_quick_count(wanted, state)
        if cost is None:
            self._click_reference(*QUICK_DIALOG_CANCEL_POINT, after_sleep=1.0)  # 不用确认：失败了，回主页会再确认
            return "failed"
        if cost == 0:
            self.log_info(
                f"活动每日战斗：快速战斗窗口按 MAX 后是 0 场，{self._no_ap_text()}，关掉窗口。"
            )
            self._click_reference(
                *QUICK_DIALOG_CANCEL_POINT, after_sleep=1.0  # 不用确认：回主页会再确认
            )
            return "no_ap"
        self.info_set("当前阶段", f"{mode}{stage}：快速战斗 {cost} 场")
        self.log_info(f"活动每日战斗：{mode}第{stage}关快速战斗 {cost} 场。")
        start = self.look_again(
            lambda: self._box_with(
                self._roi_boxes(self.capture_frame(), QUICK_DIALOG_START_ROI, "快速战斗开始"),
                ("战斗",),
            ),
            "活动每日战斗：快速战斗窗口找「战斗」",
        )
        if start is None:
            self._click_reference(*QUICK_DIALOG_CANCEL_POINT, after_sleep=1.0)  # 不用确认：失败了，回主页会再确认
            return self._failed("快速战斗窗口里没找到「战斗」")
        self._pause_guard()
        try:
            self._click_box(start, after_sleep=1.0)  # 不用确认：开始快速战斗会花活动 AP，不重按
            result = self._wait_quick_result()
        finally:
            self._resume_guard()
        if result == "no_ap":
            return "no_ap"
        if result != "done":
            return self._failed("快速战斗后没看到奖励画面")
        self._battles_done += cost
        return "done"

    def _quick_ready(self, state: dict, stage: int) -> bool:
        return state["stage"] == stage and state["quick"] and not state["auto"]

    def _pick_quick_stage(self, mode: str, state: dict, stage: int):
        """Select ``stage`` for quick battle: (state, stage), or None.

        A player's run had both modes cleared and pressed no 快速战斗
        (2026-10-14, version unknown).  Up to v0.1.32 quick battle ran only
        when the page opened on stage 15; the game keeps the last stage
        picked, so any other stage skipped it (inferred).  Only the target
        stage is ever quick-battled (Leo 2026-10-14 「不能去改打第10第5」);
        the backup is looking again after scrolling the list.
        """
        if self._quick_ready(state, stage):
            return state, stage
        if self._select_stage_scrolling(mode, state["stage"], stage):
            state = self._stable_stage_state(mode)
            if self._quick_ready(state, stage):
                return state, stage
        self.log_info(f"活动每日战斗：{mode}选中第{state['stage']}关，没能改选第{stage}关。")
        return None

    def _select_stage_scrolling(self, mode: str, current, target: int) -> bool:
        """``_select_stage``; when the list does not show ``target``, scroll it
        toward that end (harmless mouse wheel) and look again."""
        if self._select_stage(mode, current, target):
            return True
        down = current is None or target > current
        for _ in range(STAGE_LIST_SCROLLS):
            self.info_set("当前阶段", f"{mode}：滚动左边列表找第{target}关")
            try:
                self.scroll_client(
                    STAGE_LIST_SCROLL_POINT,
                    -STAGE_LIST_SCROLL_AMOUNT if down else STAGE_LIST_SCROLL_AMOUNT,
                    count=3,
                    after_sleep=0.8,
                )
            except Exception as exc:  # no wheel on this input: nothing more to try
                self.log_info(f"活动每日战斗：滚动关卡列表失败（{exc}）。")
                return False
            self._progressed()
            if self._select_stage(mode, current, target, grace=2.0):
                return True
        return False

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
            self._click_box(button, after_sleep=1.0)  # 不用确认：循环里窗口没开就再点
            end_at = monotonic() + 4.0
            looked = False  # 至少看一次：时间已到也先看一眼再说没看到
            while not looked or monotonic() <= end_at:
                looked = True
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
        free = state["free_ap"]
        if free is None and not free_only:
            # Without the top bar's AP only the free-AP switch bounds MAX.
            self._failed("关卡页上方的活动AP没读到，又没开「仅使用免费活动AP」，所以没开打")
            return None
        if (free_only or free is None) and not self._ensure_free_ap_switch_on(
            QUICK_FREE_AP_SWITCH_POINT, QUICK_FREE_AP_SWITCH_ROI
        ):
            self._failed("没能确认「仅使用免费活动AP」开着，所以没开打")
            return None
        cost = self._max_count(QUICK_DIALOG_MAX_POINT, self._quick_cost)
        if cost == 0:
            return 0
        if cost is not None and cost > wanted:
            cost = self._count_from_min(
                QUICK_DIALOG_MIN_POINT, QUICK_DIALOG_PLUS_POINT, wanted, self._quick_cost
            )
        over_free = free_only and free is not None and cost is not None and cost > free
        if cost is None or cost <= 0 or cost > wanted or over_free:
            shown = free if free is not None else "没读到"
            self.log_info(
                f"活动每日战斗：快速战斗场数校验失败（{cost}/{wanted}，免费AP {shown}）。"
            )
            self._failed(f"场数对不上（读到 {cost}，要打 {wanted}，免费AP {shown}），所以没开打")
            return None
        if free is None:
            self.log_info(f"活动每日战斗：免费AP开关开着，快速战斗窗口场数 {cost}，按这个打。")
        return cost

    def _quick_result_still_shown(self) -> bool:
        text = self._boxes_text(
            self._roi_boxes(self.capture_frame(), QUICK_RESULT_ROI, "快速战斗结果")
        )
        return keyword_match_count(text, QUICK_RESULT_KEYWORDS) >= 2

    def _wait_quick_result(self) -> str:
        """done once the REWARD overlay showed and was closed; no_ap / failed."""
        end_at = monotonic() + QUICK_RESULT_TIMEOUT
        looked = False  # 至少看一次：时间已到也先看一眼再说没看到
        while not looked or monotonic() <= end_at:
            looked = True
            if self._dismiss_ap_shortage():
                return "no_ap"
            text = self._boxes_text(
                self._roi_boxes(self.capture_frame(), QUICK_RESULT_ROI, "快速战斗结果")
            )
            if keyword_match_count(text, QUICK_RESULT_KEYWORDS) >= 2:
                self.info_set("快速战斗结果", text)
                self._click_reference(*QUICK_RESULT_DISMISS_POINT, after_sleep=1.0)  # 不用确认：下面看奖励画面还在就再点
                if self._quick_result_still_shown():
                    self.log_info("活动每日战斗：点了奖励画面还在，再点一次。")
                    self._click_reference(*QUICK_RESULT_DISMISS_POINT, after_sleep=1.0)  # 不用确认：这就是补点，下一步会再确认画面
                return "done"
            self.sleep(0.5)
        if self._quick_dialog_open():
            self._click_reference(*QUICK_DIALOG_CANCEL_POINT, after_sleep=1.0)  # 不用确认：失败了，回主页会再确认
        self.log_info("活动每日战斗：快速战斗后没有看到奖励画面。")
        return "failed"


class _StuckOnEventPage(FrozenScreen):
    """PAGE_STUCK_SECONDS passed without a press or a new page or battle."""


_SWORD_TEMPLATE = None


def _white(image):
    """Near-white pixels, relative to the band's brightest (HDR, filters)."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    top = float(np.percentile(hsv[..., 2], 99.5))
    low = max(SWORD_WHITE_FLOOR, SWORD_WHITE_SHARE * top)
    return cv2.inRange(hsv, (0, 0, int(low)), (180, SWORD_WHITE_MAX_SATURATION, 255))


def sword_icon_points(frame) -> list[tuple[float, float]]:
    """Client centres of the hub's white crossed-swords icons, left to right."""
    global _SWORD_TEMPLATE
    if _SWORD_TEMPLATE is None:
        _SWORD_TEMPLATE = image_io.read(SWORD_ICON_TEMPLATE, cv2.IMREAD_GRAYSCALE)
    template = _SWORD_TEMPLATE
    if template is None or frame is None or getattr(frame, "ndim", 0) != 3:
        return []
    height, width = frame.shape[:2]
    scale = height / REFERENCE_HEIGHT
    x, y, w, h = SWORD_ICON_ROI
    left, top = int(x * width / REFERENCE_WIDTH), int(y * scale)
    crop = frame[top : top + int(h * scale), left : left + int(w * width / REFERENCE_WIDTH)]
    if crop.size == 0:
        return []
    if scale != 1:
        crop = cv2.resize(crop, None, fx=1 / scale, fy=1 / scale, interpolation=cv2.INTER_AREA)
    mask = _white(crop)
    if mask.shape[0] < template.shape[0] or mask.shape[1] < template.shape[1]:
        return []
    scores = template_match_response(mask, template)
    points = []
    th, tw = template.shape[:2]
    while True:
        _low, best, _at, (bx, by) = cv2.minMaxLoc(scores)
        if best < SWORD_ICON_SCORE:
            break
        points.append((left + (bx + tw / 2) * scale, top + (by + th / 2) * scale))
        scores[max(0, by - th) : by + th, max(0, bx - tw) : bx + tw] = -1.0
        if len(points) > 4:
            break
    return sorted(points)
