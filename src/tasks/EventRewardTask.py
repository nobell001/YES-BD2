"""领取活动奖励: claim the 活动 page's red-badged events (Leo, 2026-10-03/04).

Calibrated live at 4K on 2026-10-04: the 活动 page lists event cards on the
left (scrolls, about 106 px a card at 1080p); a card to visit carries a red
diamond 「!」 at its top-right corner.

Leo 2026-10-08: every event page (tasks, 兑换所, 转盘, 骰子, 拼图) is the same
thing: press whatever is lit, 「即刻刷新」 first, then 全部领取 / 全部解锁 /
兑换N次 / 旋转 / 掷骰子, then the per-row hand icons.  A button counts only
when its own text is the label, so a task line mentioning it is never pressed.

Leo 2026-11-07: an event page never costs 钻石 (「活動不會讓你花鑽石」), so the
pages no longer look for 钻石 at all: the 11-05 wheel has a 钻石 prize slice
and was skipped whole.  Only 「付费」 still skips a page (the 10-03
「满月付费钻石兑换所」 carried it in its title; a prize never says 付费).
Unknown pages are skipped, with a diagnostic picture.
"""

from __future__ import annotations

import re
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np
from qfluentwidgets import FluentIcon

from src.tasks.BaseBD2Task import TEMPLATE_DIR
from src.tasks.claim_page import find_red_badges
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.utils import image_io
from src.utils.chinese import to_simplified
from src.utils.image_utils import template_match_response
from src.utils.known_popups import OVERLAY_DISMISS_KEYWORDS, REWARD_DIALOG_TITLES
from src.utils.ocr_utils import normalize_ocr_text
from src.utils.press_confirm import wait_for

NO_KNOWN_BUTTON = "页面上没有认得的按钮"

EVENT_ENTRY_POINT = (889, 985)  # 主页 bottom bar 「活动」
EVENT_TITLE_KEYWORDS = ("活动",)

# Left card list (1920x1080 reference).
LIST_CARD_X = 422
LIST_SCROLL_POINT = (422 / 1920, 540 / 1080)
LIST_CAPTION_ROI = (322, 262, 202, 545)
# The red badge sits in this strip at each card's top-right corner.
BADGE_STRIP = (496, 265, 30, 545)
BADGE_TO_CARD_CENTER = 34
LIST_SCROLL_NOTCHES = 3  # about 2.5 cards; the list overshoots, so wait
LIST_SETTLE_SECONDS = 1.5
LIST_MAX_STEPS = 12

PANEL_ROI = (545, 250, 1100, 585)
CURRENCY_ROI = (1440, 20, 460, 80)
TOKEN_ROI = (1700, 35, 110, 45)

# Leo 2026-11-07: only 付费 skips an event page (see the module notes).
PAID_WORDS = ("付费", "付費")
# 累积参与N次: how many spins so far (a spin that changed neither this nor
# the token count did not happen).
SPUN_PATTERN = re.compile(r"参与(\d+)次")
# The wheel turns about 5 s after a spin press (live 4K 11-07) and the
# reward box comes after it; 3 s of settling pressed the next spin into the
# animation.  Wait until the panel stands still (two calm looks in a row),
# at most the 10 s stuck limit.  A still page moves ≤0.11 (blinking lights,
# 4K 11-07); a wheel turning 0.5° in half a second already moves about 1.
# The reward box itself is the second cue (Leo 10-10: never wait on once
# a cue is read): its sparkles keep the panel moving 3-7 (4K 繁中 11-11),
# so stillness alone always ran the full 10 s after the box was already up.
SPIN_REWARD_WORDS = OVERLAY_DISMISS_KEYWORDS + REWARD_DIALOG_TITLES
SPIN_STILL_MAX_DIFF = 1.0
SPIN_STILL_LOOKS = 2
SPIN_WAIT_SECONDS = 10.0
SPIN_LOOK_SECONDS = 0.5
# Leo 2026-10-08: every event page is the same thing: press whatever is lit,
# 「即刻刷新」 first, then claim / unlock / exchange / spin / roll.
EXCHANGE_WORD = "兑换"
# The wheel's spin buttons, read by their own text so a new colour scheme
# changes nothing: 「旋转10次／旋转1次」 (简中) and 「轉10次／轉1次」 (繁中, the
# 11-05 wheel).  The biggest count is pressed first (a player saw the tool
# spin one at a time, 11-07).
SPIN_WORD = "转"
SPIN_PATTERN = re.compile(r"^(?:旋)?转(\d+)次")
# The dice button: 「掷骰子」 (简中 10-03) and 「丟骰子」 (繁中 11-19, Leo's 4K:
# never 擲骰子, so the 繁中 dice page had no known button and was skipped).
DICE_WORDS = ("掷骰子", "丢骰子")
LIT_BUTTON_ORDER = ("即刻刷新", "全部领取", "全部解锁", EXCHANGE_WORD, SPIN_WORD) + DICE_WORDS
# These ask 「确认」 before acting (the 付费 check runs on that box too).
CONFIRM_BUTTONS = ("即刻刷新", "全部解锁")
# A button's own text may carry a little more (e.g. 「旋转1次1次免费」).
BUTTON_TEXT_SLACK = 4
EXCHANGE_PATTERN = re.compile(r"兑换(\d+)次")

# A lit button's brightest channel against the page's own white (its text
# and card faces): white pills 255 / grey 128, blue 「全部领取」 231 / 137
# with the page white at 255 (live 4K 2026-10-04): 1.00 / 0.50, 0.91 / 0.54.
# A fixed 185 skipped a lit 全部领取 once a screen filter or HDR darkened
# the game by a quarter (173); the share stays 0.91 (0.86-0.93 under the
# darkening, gamma and washed-out looks tried on the 10-03 frame, dim at
# most 0.65).
BUTTON_LIT_MIN_SHARE = 0.75
# The page white: the brightest 1% of the page (every event page has white
# text), never under this, so a page with no white at all still leaves a
# grey 128 button unlit while a lit one dimmed to 0.6 (139) stays lit.
PAGE_WHITE_PERCENTILE = 99
PAGE_WHITE_FLOOR = 176.0
# An unaffordable exchange shows its cost in red (18% red pixels vs 0%).
RED_COST_SHARE = 0.08

HAND_TEMPLATE = TEMPLATE_DIR / "event" / "reward_hand.png"
HAND_MATCH = 0.8
HAND_ROI = (1450, 255, 170, 575)

DIALOG_ROI = (640, 380, 640, 300)

MAX_PAGE_ACTIONS = 25

# 骰子活动 (Leo 10-04 「骰子按自动进行」, 11-19 「他骰子沒有按自動運行」):
# the 「自动进行」 switch sits under its own label, on the 掷骰子 row (4K
# 简中 10-03 and 繁中 11-19 alike: label centre (1545, 722), switch
# (1545, 765), about 108 x 40, knob on the left = off).  The switch is turned on, then the dice roll by
# themselves until none are left.
# 「自動進行」 reaches the task as 自动战斗: the 繁中 word table maps it to
# the 简中 battle word (Leo's 4K log 11-19 18:33); only counts next to a dice
# button.
AUTO_ROLL_WORDS = ("自动进行", "自动运行", "自动战斗")
AUTO_SWITCH_BELOW_LABEL = 42  # label centre -> switch centre when 掷骰子 is not read
AUTO_SWITCH_RIGHT_OF_DICE = 167  # 掷骰子 text centre -> switch centre when the label is not read
AUTO_SWITCH_HALF = (50, 15)
# Off: grey track (saturation 2-5), knob 30 brighter than the track on the
# left.  On: a coloured track or the knob on the right.
AUTO_SWITCH_COLOUR_MIN = 40.0
AUTO_SWITCH_KNOB_MIN = 8.0
# A press the game took changes the switch picture (knob slides); a mean
# change under this is a press that was not taken.
AUTO_SWITCH_CHANGED_MIN = 6.0
# Rolling on auto: nothing moved for this long = done (or stuck: the 10 s
# limit); all dice gone and two calm looks = done.  The hard cap only
# guards a page that never stops moving.
DICE_LOOK_SECONDS = 1.0
DICE_STILL_SECONDS = 10.0
DICE_MAX_SECONDS = 600.0
# The badge of an event handled twice that keeps it (e.g. dice left).
STILL_BADGED = "处理两次还在"
# A card's page is read this long for its type before it counts as unknown.
PAGE_LOAD_SECONDS = 4.0

def page_white(frame) -> float:
    """How bright white text is on this screen (filters and HDR change it)."""
    value = frame[::4, ::4, :3].max(axis=2)
    return max(float(np.percentile(value, PAGE_WHITE_PERCENTILE)), PAGE_WHITE_FLOOR)


def button_lit(frame, box) -> bool:
    """A button's own colour: lit when its brightest channel is close to the
    page's white."""
    if frame is None or box is None:
        return False
    height, width = frame.shape[:2]
    x0, y0 = max(0, int(box.x)), max(0, int(box.y))
    x1, y1 = min(width, int(box.x + box.width)), min(height, int(box.y + box.height))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return False
    value = frame[y0:y1, x0:x1, :3].max(axis=2)
    return float(np.median(value)) >= BUTTON_LIT_MIN_SHARE * page_white(frame)


def red_share(frame, rect) -> float:
    x0, y0, x1, y1 = (int(v) for v in rect)
    crop = frame[max(0, y0) : y1, max(0, x0) : x1, :3]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = ((hsv[..., 0] <= 8) | (hsv[..., 0] >= 172)) & (hsv[..., 1] >= 120) & (hsv[..., 2] >= 120)
    return float(np.mean(red))


# OCR reads the narrow 1 of a currency count as l / I / |.
_TOKEN_DIGIT_FIXES = str.maketrans({"l": "1", "I": "1", "|": "1", "i": "1", "O": "0", "o": "0"})


def parse_token_count(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", str(text or "").translate(_TOKEN_DIGIT_FIXES))
    return int(digits) if digits else None


def _box_text(box) -> str:
    return normalize_ocr_text(to_simplified(getattr(box, "name", "")))


def spin_buttons(boxes: list) -> list[tuple[int, object]]:
    """(count, box) for each wheel spin button, the biggest count first.

    Only a box whose own text is the label counts (a little more is fine,
    e.g. 「旋转1次1次免费」); a task row 「转盘旋转1次」 does not."""
    found = []
    for box in boxes:
        name = _box_text(box)
        match = SPIN_PATTERN.match(name)
        if match and len(name) <= len(match.group(0)) + BUTTON_TEXT_SLACK:
            found.append((int(match.group(1)), box))
    return sorted(found, key=lambda item: item[0], reverse=True)


def spun_count(boxes: list) -> int | None:
    for box in boxes:
        match = SPUN_PATTERN.search(_box_text(box))
        if match:
            return int(match.group(1))
    return None


# The card list counts as not moved when its small grey picture changes this
# little (mean of 0..255) between two scrolls.
LIST_STILL_MAX_DIFF = 3.0


def list_view(frame):
    """A small grey picture of the card list (1920x1080 reference strip)."""
    height, width = frame.shape[:2]
    scale_x, scale_y = width / 1920, height / 1080
    x, y, w, h = LIST_CAPTION_ROI
    crop = frame[
        int(y * scale_y) : int((y + h) * scale_y), int(x * scale_x) : int((x + w) * scale_x), :3
    ]
    if crop.size == 0:
        return None
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, (48, 128), interpolation=cv2.INTER_AREA).astype(np.int16)


def panel_view(frame):
    """A small grey picture of the event panel (to see the wheel stop)."""
    if frame is None:
        return None
    reference = cv2.resize(frame[:, :, :3], (1920, 1080), interpolation=cv2.INTER_AREA)
    x, y, w, h = PANEL_ROI
    grey = cv2.cvtColor(reference[y : y + h, x : x + w], cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, (110, 58), interpolation=cv2.INTER_AREA).astype(np.int16)


def views_close(first, second, max_diff: float) -> bool:
    if first is None or second is None or first.shape != second.shape:
        return False
    return float(np.abs(first - second).mean()) <= max_diff


def views_match(first, second) -> bool:
    if first is None or second is None or first.shape != second.shape:
        return False
    return float(np.abs(first - second).mean()) <= LIST_STILL_MAX_DIFF


def find_badges(frame) -> list[int]:
    """Reference y of each red ◆! badge in the card list, top to bottom."""
    return find_red_badges(frame, BADGE_STRIP)


def _switch_crop(reference, box):
    if reference is None or box is None:
        return None
    x0, y0 = max(0, int(box.x)), max(0, int(box.y))
    x1, y1 = int(box.x + box.width), int(box.y + box.height)
    crop = reference[y0:y1, x0:x1, :3]
    return crop if crop.size else None


def auto_switch_state(reference, box) -> bool | None:
    """The 自动进行 switch on a 1920x1080 reference frame: True on, False off,
    None when it cannot be told (then it is never pressed).

    Off (4K 10-03): grey track, light knob on the left.  On: a coloured track,
    or the knob on the right."""
    crop = _switch_crop(reference, box)
    if crop is None:
        return None
    crop = crop.astype(np.int16)
    colour = float((crop.max(axis=2) - crop.min(axis=2)).mean())
    if colour >= AUTO_SWITCH_COLOUR_MIN:
        return True
    light = crop.max(axis=2).mean(axis=0)
    third = max(1, light.size // 3)
    left, right = float(light[:third].mean()), float(light[-third:].mean())
    if right - left >= AUTO_SWITCH_KNOB_MIN:
        return True
    if left - right >= AUTO_SWITCH_KNOB_MIN:
        return False
    return None


def switch_changed(before, after, box) -> bool:
    first, second = _switch_crop(before, box), _switch_crop(after, box)
    if first is None or second is None or first.shape != second.shape:
        return False
    diff = np.abs(first.astype(np.int16) - second.astype(np.int16)).mean()
    return float(diff) >= AUTO_SWITCH_CHANGED_MIN


# Two reads of one 确认 button land within a few reference pixels.
SAME_PLACE_PIXELS = 12


def _same_place(first, second) -> bool:
    return (
        abs((first.x + first.width / 2) - (second.x + second.width / 2)) <= SAME_PLACE_PIXELS
        and abs((first.y + first.height / 2) - (second.y + second.height / 2)) <= SAME_PLACE_PIXELS
    )


class EventRewardTask(_ClaimTaskBase):
    claim_log_name = "event_reward"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "领取活动奖励"
        self.description = (
            "打开活动页，依序进入有红点的活动，哪里亮了按哪里（即刻刷新优先）。"
            "有付费字样的页面不碰。"
        )
        self.icon = FluentIcon.SHOPPING_CART

    # -- flow -------------------------------------------------------------

    def run_claim(self) -> bool:
        if not self._open_page_from_home("活动", EVENT_ENTRY_POINT, EVENT_TITLE_KEYWORDS):
            return self._claim_fail("打开活动页")
        skipped: dict[str, str] = {}  # card -> why its badge was left
        claimed = 0
        # Leo 10-04: a second pass from the top, since a claim can badge
        # another card; skipped pages (付费, unknown) do not count.
        for sweep in (1, 2):
            if sweep == 2 and not self._reopen_event_page():
                return self._claim_fail("重新打开活动页")
            if sweep == 2:
                # Leo 11-19 「第二次打開活動頁檢查 他沒有去點紅色驚嘆號」: only
                # pages that must not be touched (付费, unknown) stay skipped;
                # one that kept its badge after two goes gets looked at again
                # (Leo 10-04: 「被跳過的頁面（鑽石、認不出）不算」).
                for key in [key for key, why in skipped.items() if why == STILL_BADGED]:
                    del skipped[key]
            done = self._sweep_list(skipped)
            claimed += done
            self.info_set("活动领取轮次", f"第{sweep}轮处理 {done} 个")
            if sweep == 1 and done == 0:
                break
        self.info_set("活动领取结果", f"处理 {claimed} 个，跳过 {len(skipped)} 个")
        if not self._leave_to_home("活动", EVENT_TITLE_KEYWORDS):
            return self._claim_fail("活动页返回主页")
        if skipped:
            # YES-BD2 #11: the run ends fine with badges left, and a fine run's
            # 问题摘要 keeps only its last lines; this says which and why.
            left = "、".join(f"「{key}」{why}" for key, why in skipped.items())
            self.log_info(f"活动：这些还有红点，没领：{left}。")
        return True

    def _reopen_event_page(self) -> bool:
        """Leave to 主页 and open 活动 again before the second pass (Leo
        2026-10-08): the red badges only refresh when the page is reopened."""
        self.info_set("当前阶段", "活动：关闭后重新打开，再看一轮")
        if not self._leave_to_home("活动", EVENT_TITLE_KEYWORDS):
            return False
        return self._open_page_from_home("活动", EVENT_ENTRY_POINT, EVENT_TITLE_KEYWORDS)

    def _sweep_list(self, skipped: dict[str, str]) -> int:
        self._list_to_top()
        handled = 0
        visits: dict[str, int] = {}
        last_list_text = None
        last_view = None
        empty_reads = 0
        rescrolled = False
        moved = 0  # scrolls down that moved the list
        for _step in range(LIST_MAX_STEPS + MAX_PAGE_ACTIONS):
            frame = self.capture_frame()
            target = self._next_badge(frame, skipped)
            if target is not None:
                badge_y, caption = target
                key = caption or f"y{badge_y}"
                visits[key] = visits.get(key, 0) + 1
                if visits[key] > 2:
                    # Handled twice and still badged: something on it is
                    # not claimable this way; do not loop on it.
                    self.log_info(f"活动「{key}」：处理两次后红点仍在，跳过。")
                    skipped[key] = STILL_BADGED
                    continue
                self.info_set("当前阶段", f"打开活动：{key}")
                self._click_reference(LIST_CARD_X, badge_y + BADGE_TO_CARD_CENTER, after_sleep=1.2)  # 不用确认：没打开就红点还在，下一轮再点（最多两次）
                self._page_skip_why = ""
                if self._handle_page(caption):
                    handled += 1
                elif self._page_skip_why == NO_KNOWN_BUTTON and visits[key] < 2:
                    # The card press may not have been taken: the old page,
                    # or none, is shown.  Its badge is still there; the next
                    # look presses the card once more (Leo 2026-11-05).
                    self.log_info(f"活动「{key}」：页面上没有认得的按钮，再点一次这个活动。")
                else:
                    skipped[key] = self._page_skip_why or "跳过"
                continue  # same scroll position: look again
            list_text = self._list_text(frame)
            if not list_text.strip() and empty_reads < 4:
                # The list has not drawn yet: two blank reads are not "the
                # bottom" (that ended the sweep with nothing handled).
                empty_reads += 1
                self.sleep(0.6)
                continue
            view = list_view(frame)
            # No card counts as the last one: 登录活动 was, until 登录加成 and
            # two Pickup cards came below it (live 10-10), and stopping on it
            # left them unchecked.  Only a list that stays still is the end.
            if last_list_text is not None and (
                list_text == last_list_text or views_match(view, last_view)
            ):
                # Bottom: the list did not move.  Compared as a picture too:
                # the captions' OCR varied a little at the bottom and the
                # sweep went on scrolling ~25 more times (Leo 2026-10-07).
                # A scroll the game dropped looks the same, so one more
                # scroll first; only a second still list is the bottom.
                if rescrolled:
                    if not moved:
                        # YES-BD2 #11: say so in the log.  Not a give-up frame:
                        # the run goes on, and a later failure of this task
                        # would show this screen instead of its own.
                        self.log_info(
                            "活动列表：往下滚两次都没动。可能活动只有一屏；"
                            "如果下面还有活动，就是游戏没收到滚动。"
                        )
                    break
                rescrolled = True
                self.log_info("活动列表：滚动后列表没动，再滚一次确认是否到底。")
            else:
                rescrolled = False
                if last_list_text is not None:
                    moved += 1
            last_list_text = list_text
            last_view = view
            self.scroll_client(
                LIST_SCROLL_POINT, -LIST_SCROLL_NOTCHES, after_sleep=LIST_SETTLE_SECONDS
            )
        self.log_info(f"活动列表：这轮往下滚动了 {moved} 次，处理 {handled} 个。")
        return handled

    def _list_to_top(self) -> None:
        self.scroll_client(
            LIST_SCROLL_POINT,
            LIST_SCROLL_NOTCHES,
            count=6,
            interval=0.15,
            after_sleep=LIST_SETTLE_SECONDS,
        )

    def _list_text(self, frame) -> str:
        return self._boxes_text(self._reference_boxes(frame, LIST_CAPTION_ROI, "活动列表"))

    def _next_badge(self, frame, skipped: dict[str, str]):
        badges = find_badges(frame)
        self.info_set("活动红点", ",".join(str(y) for y in badges) or "-")
        if not badges:
            return None
        boxes = self._reference_boxes(frame, LIST_CAPTION_ROI, "活动列表")
        for badge_y in badges:
            caption = self._card_caption(boxes, badge_y)
            if (caption or f"y{badge_y}") not in skipped:
                return badge_y, caption
        return None

    @staticmethod
    def _card_caption(boxes: list, badge_y: int) -> str:
        """The caption at the bottom of the badged card (about 60 px below)."""
        best = ""
        for box in boxes:
            center = box.y + box.height / 2
            if badge_y + 35 <= center <= badge_y + 85:
                name = normalize_ocr_text(getattr(box, "name", ""))
                if len(name) > len(best):
                    best = name
        return best

    # -- one page ---------------------------------------------------------

    def _handle_page(self, caption: str) -> bool:
        """True when the page was handled; False when it was skipped.

        The page is read until its type shows (up to PAGE_LOAD_SECONDS): one
        look right after the card click could come before the panel drew.
        The 付费 check runs on every look and once more on a later frame
        before anything is pressed, so a currency bar drawn after the panel
        buttons still stops the page.
        """
        label = caption or "活动"
        self.sleep(0.6)
        end_at = monotonic() + PAGE_LOAD_SECONDS
        known = False
        while True:
            frame = self.capture_frame()
            panel = self._reference_boxes(frame, PANEL_ROI, "活动内容")
            if self._page_is_paid(frame, panel, caption, label):
                return False
            known = bool(self._page_buttons(frame, panel, set()) or self._hand_points(frame))
            if known or monotonic() >= end_at:
                break
            self.sleep(0.5)
        if not known:
            self.log_info(f"活动「{label}」：页面上没有认得的按钮，跳过。")
            self._page_skip_why = NO_KNOWN_BUTTON
            self._save_flow_diagnostic(f"event_reward_unknown_{label}")
            return False
        self.sleep(0.4)
        frame = self.capture_frame()
        panel = self._reference_boxes(frame, PANEL_ROI, "活动内容")
        if self._page_is_paid(frame, panel, caption, label):
            return False
        return self._press_what_is_lit(label)

    def _page_is_paid(self, frame, panel, caption: str, label: str) -> bool:
        currency = self._reference_boxes(frame, CURRENCY_ROI, "活动货币")
        text = caption + " " + self._boxes_text(panel) + " " + self._boxes_text(currency)
        self.info_set("活动页 OCR", text[:160] or "-")
        if any(word in text for word in PAID_WORDS):
            self.log_info(f"活动「{label}」：页面有付费字样，整页跳过。")
            self._page_skip_why = "付费页面，不碰"
            return True
        return False

    def _paid_now(self, frame, panel, label: str) -> bool:
        """付费 re-check on the frame about to be pressed (a later press can
        bring up text that was not there at first)."""
        return self._page_is_paid(frame, panel, "", label)

    def _settle(self, label: str, frame) -> None:
        self._settle_after_claim(label, EVENT_TITLE_KEYWORDS, self._frame_brightness(frame))

    def _button(self, panel, word: str):
        """The box whose text IS the button label, not a task line mentioning it.

        A task row such as 「转盘旋转1次」 or a hint 「获得拼图用触控笔」 is
        longer than the label and does not count (Leo 2026-10-08: the 活动任务
        page was taken for the puzzle page).
        """
        wanted = normalize_ocr_text(word)
        for box in panel:
            name = normalize_ocr_text(to_simplified(getattr(box, "name", "")))
            if name.startswith(wanted) and len(name) <= len(wanted) + BUTTON_TEXT_SLACK:
                return box
        return None

    def _page_buttons(self, frame, panel, skip: set[str]) -> list[tuple[str, object, bool]]:
        """(word, box, lit) for every known button on the page, in press order."""
        found = []
        for word in LIT_BUTTON_ORDER:
            if word == EXCHANGE_WORD:
                for count, box in self._exchange_buttons(panel):
                    found.append((f"兑换{count}次", box, self._exchange_lit(frame, box)))
                continue
            if word == SPIN_WORD:
                for count, box in spin_buttons(panel):
                    found.append((f"转{count}次", box, button_lit(frame, self._to_frame(frame, box))))
                continue
            box = self._button(panel, word)
            if box is not None:
                found.append((word, box, button_lit(frame, self._to_frame(frame, box))))
        return [item for item in found if item[0] not in skip]

    def _exchange_lit(self, frame, button) -> bool:
        if not button_lit(frame, self._to_frame(frame, button)):
            return False
        # An unaffordable exchange shows its cost in red under the label.
        cost = (
            button.x,
            button.y + button.height,
            button.x + button.width,
            button.y + 2.4 * button.height,
        )
        return red_share(self._reference(frame), cost) < RED_COST_SHARE

    def _press_what_is_lit(self, label: str) -> bool:  # 会补点：循环里还亮着就再按
        """Leo 2026-10-08: on a badged page press whatever is lit (哪裡亮了點哪裡),
        即刻刷新 first.  False when the page was skipped for 付费."""
        skip: set[str] = set()
        auto_tried = False
        for _ in range(MAX_PAGE_ACTIONS):
            frame = self.capture_frame()
            panel = self._reference_boxes(frame, PANEL_ROI, f"{label}按钮")
            if self._paid_now(frame, panel, label):
                return False
            if (
                not auto_tried
                and self._dice_button(panel) is not None
            ):
                # 骰子: roll on 自动进行, never one press at a time first.
                auto_tried = True
                if self._roll_dice_on_auto(label, frame, panel):
                    # Auto rolls every die (Leo 11-19); a hand press could stop
                    # it.  Dice left later: the second pass comes back.
                    skip.update(DICE_WORDS)
                    continue
            lit = [(word, box) for word, box, on in self._page_buttons(frame, panel, skip) if on]
            if lit:
                word, box = lit[0]
                self.log_info(f"活动「{label}」：{word}。")
                spin = word.startswith(SPIN_WORD)
                before = (self._tokens(frame), spun_count(panel)) if spin else None
                self._click_reference_box(box, after_sleep=1.2)  # 不用确认：循环里还亮着就再按
                if word in CONFIRM_BUTTONS or word.startswith(EXCHANGE_WORD):
                    if not self._confirm_dialog(label) and word.startswith(EXCHANGE_WORD):
                        # No confirm box: the tokens ran out (Leo 10-05).
                        skip.add(word)
                        continue
                if spin:
                    self._wait_spin_stop(label)
                self._settle(label, frame)
                if spin and self._spin_did_nothing(before, label, word):
                    skip.add(word)
                continue
            points = self._hand_points(frame)
            if not points:
                break
            self.log_info(f"活动「{label}」：领取一行任务奖励。")
            self._click_reference(*points[0], after_sleep=1.0)  # 不用确认：循环里手还在就再按
            self._settle(label, frame)
        return True

    # -- 骰子 -------------------------------------------------------------

    def _auto_roll_label(self, panel):
        """The 「自动进行」 label box on a dice page (简中 / 繁中), or None."""
        wanted = [normalize_ocr_text(word) for word in AUTO_ROLL_WORDS]
        for box in panel:
            name = _box_text(box)
            if any(name.startswith(word) and len(name) <= len(word) + 2 for word in wanted):
                return box
        return None

    def _dice_button(self, panel):
        for word in DICE_WORDS:
            box = self._button(panel, word)
            if box is not None:
                return box
        return None

    def _auto_switch_box(self, panel):
        """Where the 自动进行 switch is: under its label, on the 掷骰子 row.

        The label may not be read (繁中 「自動進行」 came out 自动战斗, 11-19):
        then the switch is beside the dice button's text, same row."""
        label = self._auto_roll_label(panel)
        dice = self._dice_button(panel)
        if label is None:
            if dice is None:
                return None
            label = SimpleNamespace(
                x=dice.x + dice.width / 2 + AUTO_SWITCH_RIGHT_OF_DICE, y=dice.y - 60, width=0, height=20
            )
        x = label.x + label.width / 2
        if dice is not None and dice.y > label.y + label.height:
            y = dice.y + dice.height / 2
        else:
            y = label.y + label.height / 2 + AUTO_SWITCH_BELOW_LABEL
        half_w, half_h = AUTO_SWITCH_HALF
        return SimpleNamespace(
            name="自动进行开关", x=x - half_w, y=y - half_h, width=2 * half_w, height=2 * half_h
        )

    def _roll_dice_on_auto(self, label: str, frame, panel) -> bool:
        """Turn 自动进行 on and wait until the dice are used up.

        True when the dice rolled on auto (the page loop then looks again:
        掷骰子 is grey, the clear reward may be lit); False when the switch
        could not be turned on, so the loop rolls one press at a time as
        before (补救)."""
        dice = self._dice_button(panel)
        switch = self._auto_switch_box(panel)
        state = auto_switch_state(self._reference(frame), switch)
        self.info_set("骰子自动进行", {True: "开", False: "关", None: "看不出"}[state])
        if state:
            # Still rolling from an earlier visit (丢骰子 is grey while auto
            # runs, live 4K 11-19): wait for it, never press anything.
            self.log_info(f"活动「{label}」：自动进行已经开着，等它丢完。")
            self._wait_dice_used_up(label, switch)
            return True
        if dice is None or not button_lit(frame, self._to_frame(frame, dice)):
            self.log_info(f"活动「{label}」：骰子页，丢骰子是灰的（没有骰子），不开自动进行。")
            return False
        if state is None:
            # Never press a switch whose side is unknown: it may be on already.
            self.log_info(f"活动「{label}」：看不出自动进行开关是开是关，改成一次一次掷骰子。")
            self._save_flow_diagnostic(f"event_reward_dice_switch_{label}")
            return False
        if not state:
            for attempt in (1, 2):
                before = self._reference(self.capture_frame())
                self.log_info(f"活动「{label}」：打开自动进行（第{attempt}次）。")
                self._click_reference_box(switch, after_sleep=1.0)  # 不用确认：下一行看开关有没有动，没动就再按一次（最多两次）
                after = self._reference(self.capture_frame())
                if auto_switch_state(after, switch) or switch_changed(before, after, switch):
                    state = True
                    break
            if not state:
                self.log_info(f"活动「{label}」：自动进行按了两次开关都没动，改成一次一次掷骰子。")
                self._save_flow_diagnostic(f"event_reward_dice_switch_{label}")
                return False
        self._wait_dice_used_up(label, switch)
        return True

    def _wait_dice_used_up(self, label: str, switch) -> None:
        """Let the dice roll on auto until none are left.

        Leo 11-19: 「只要按自動運行他就會全部丟完」, so 丢骰子 is never
        pressed here (a press could stop the run).  Live 4K 繁中 11-19: 丢骰子
        turns grey as soon as auto runs, so a grey button says nothing; at 0
        dice the game turns 自动进行 off by itself (knob back left, grey).
        Done = the switch off again or a dice count of 0, on two looks in a
        row.  Progress = the count's own text or the switch changing (the
        count can read badly: the icon came out as 8, 「8l」), or a reward
        box.  No progress for DICE_STILL_SECONDS ends the wait (stuck: the
        second pass looks again)."""
        start = monotonic()
        frame = self.capture_frame()
        count_text = self._token_text(frame)
        state = auto_switch_state(self._reference(frame), switch)
        last_change = monotonic()
        done_looks = 0
        self.log_info(f"活动「{label}」：自动丢骰子中（骰子数读到「{count_text or '?'}」）。")
        while monotonic() - start < DICE_MAX_SECONDS:
            self.sleep(DICE_LOOK_SECONDS)
            frame = self.capture_frame()
            if self._spin_reward_shown(frame, label):
                self._settle(label, frame)
                last_change = monotonic()
                done_looks = 0
                continue
            now_text = self._token_text(frame)
            now_state = auto_switch_state(self._reference(frame), switch)
            if now_text != count_text or now_state != state:
                last_change = monotonic()
            count_text, state = now_text, now_state
            done = state is False or parse_token_count(count_text) == 0
            done_looks = done_looks + 1 if done else 0
            if done_looks >= 2:
                break
            if monotonic() - last_change >= DICE_STILL_SECONDS:
                self.log_info(
                    f"活动「{label}」：{DICE_STILL_SECONDS:.0f} 秒骰子数和自动进行开关都没变，不再等。"
                )
                break
        self._settle(label, frame)
        switch_now = {True: "还开着", False: "已关", None: "看不出"}[state]
        self.log_info(
            f"活动「{label}」：自动丢骰子结束（骰子数读到「{count_text or '?'}」，"
            f"自动进行{switch_now}），用了 {monotonic() - start:.0f} 秒。"
        )

    def _wait_spin_stop(self, label: str) -> None:
        """Wait for the wheel to stop before the reward box is looked for.

        Stopped = the reward box is on screen, or the panel stood still twice
        in a row (whichever comes first)."""
        state = {"last": panel_view(self.capture_frame()), "calm": 0}

        def stopped() -> bool:
            frame = self.capture_frame()
            if self._spin_reward_shown(frame, label):
                return True
            view = panel_view(frame)
            last = state["last"]
            if last is not None and view is not None:
                self.info_set("转盘画面变化", f"{float(np.abs(last - view).mean()):.1f}")
            calm = views_close(last, view, SPIN_STILL_MAX_DIFF)
            state["calm"] = state["calm"] + 1 if calm else 0
            state["last"] = view
            return state["calm"] >= SPIN_STILL_LOOKS

        self.sleep(SPIN_LOOK_SECONDS)
        if not wait_for(stopped, SPIN_WAIT_SECONDS, sleep=self.sleep, poll=SPIN_LOOK_SECONDS):
            self.log_info(f"活动「{label}」：转盘 {SPIN_WAIT_SECONDS:.0f} 秒还在动，先往下看奖励。")

    def _spin_reward_shown(self, frame, label: str) -> bool:
        """The spin's reward box (「點擊畫面即可返回」 / 獲得獎勵) is up."""
        text = " ".join(_box_text(box) for box in self._roi_boxes(frame, None, f"{label}转完"))
        if not any(normalize_ocr_text(word) in text for word in SPIN_REWARD_WORDS):
            return False
        self.info_set("转盘停止", "看到奖励视窗")
        return True

    def _spin_did_nothing(self, before: tuple, label: str, word: str) -> bool:
        """True when a spin changed neither the token count nor 累积参与N次.

        A spin button can stay white with too few tokens left; pressing it
        again would only repeat.  Unreadable counts never stop a spin (the
        page's press limit still ends the loop)."""
        frame = self.capture_frame()
        after = (
            self._tokens(frame),
            spun_count(self._reference_boxes(frame, PANEL_ROI, f"{label}次数")),
        )
        pairs = [(a, b) for a, b in zip(before, after) if a is not None and b is not None]
        if pairs and all(a == b for a, b in pairs):
            self.log_info(f"活动「{label}」：{word}按了没转（代币和次数都没变），不再按它。")
            return True
        return False

    def _hand_points(self, frame) -> list[tuple[int, int]]:
        template = getattr(self, "_hand_template", None)
        if template is None:
            template = image_io.read(HAND_TEMPLATE)
            self._hand_template = template
        if template is None:
            return []
        reference = cv2.resize(frame[:, :, :3], (1920, 1080), interpolation=cv2.INTER_AREA)
        x, y, w, h = HAND_ROI
        result = template_match_response(reference[y : y + h, x : x + w], template)
        points = []
        th, tw = template.shape[:2]
        while True:
            _min, score, _minloc, (mx, my) = cv2.minMaxLoc(result)
            if score < HAND_MATCH:
                break
            points.append((x + mx + tw // 2, y + my + th // 2))
            result[max(0, my - th // 2) : my + th // 2, max(0, mx - tw // 2) : mx + tw // 2] = -1
        return sorted(points, key=lambda point: point[1])

    def _exchange_buttons(self, boxes: list) -> list[tuple[int, object]]:
        found = []
        for box in boxes:
            match = EXCHANGE_PATTERN.search(normalize_ocr_text(getattr(box, "name", "")))
            if match:
                found.append((int(match.group(1)), box))
        return sorted(found, key=lambda item: item[0], reverse=True)

    def _token_text(self, frame) -> str:
        """The event-token count as read (dice: the icon reads as a digit)."""
        return self._boxes_text(self._reference_boxes(frame, TOKEN_ROI, "活动代币")).strip()

    def _tokens(self, frame) -> int | None:
        """The event-token count, for the log only (see ``_press_what_is_lit``)."""
        text = self._token_text(frame)
        tokens = parse_token_count(text)
        self.info_set("活动代币", "-" if tokens is None else str(tokens))
        return tokens

    def _confirm_dialog(self, label: str) -> bool:
        """Press 确认 on the 兑换／即刻刷新 dialog; False when none appeared.

        确认 is pressed only when two frames in a row show it at the same
        place with no 付费 word (audit #77: one frame was enough, so a
        dialog still drawing its cost could be confirmed)."""
        end_at = monotonic() + 4.0
        previous = None
        looked = False  # 至少看一次：时间已到也先看一眼再说没看到
        while not looked or monotonic() < end_at:
            looked = True
            frame = self.capture_frame()
            boxes = self._reference_boxes(frame, DIALOG_ROI, f"{label}确认")
            text = self._boxes_text(boxes)
            if any(word in text for word in PAID_WORDS):
                self.log_info(f"活动「{label}」：确认框有付费字样，取消。")
                cancel = self._box_with(boxes, ("取消",))
                if cancel is not None:
                    self._click_reference_box(cancel, after_sleep=0.8)  # 不用确认：有付费的确认框只按读到的取消，不碰别处；没关掉留给回主页
                return False
            confirm = self._box_with(boxes, ("确认",))
            if confirm is not None and previous is not None and _same_place(previous, confirm):
                self._click_reference_box(confirm, after_sleep=1.5)  # 不用确认：确认会花活动代币，不重按
                return True
            previous = confirm
            self.sleep(0.4)
        return False

    # -- coordinates ------------------------------------------------------

    @staticmethod
    def _reference(frame):
        return cv2.resize(frame[:, :, :3], (1920, 1080), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _to_frame(frame, box):
        """A 1920 reference box in the frame's own pixels (for colour checks)."""
        from types import SimpleNamespace

        scale = frame.shape[1] / 1920
        return SimpleNamespace(
            x=box.x * scale, y=box.y * scale, width=box.width * scale, height=box.height * scale
        )
