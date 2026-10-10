"""领取活动奖励: claim the 活动 page's red-badged events (Leo, 2026-10-03/04).

Calibrated live at 4K on 2026-10-04: the 活动 page lists event cards on the
left (scrolls, about 106 px a card at 1080p); a card to visit carries a red
diamond 「!」 at its top-right corner.

Leo 2026-10-08: every event page (tasks, 兑换所, 转盘, 骰子, 拼图) is the same
thing: press whatever is lit, 「即刻刷新」 first, then 全部领取 / 全部解锁 /
兑换N次 / 旋转 / 掷骰子, then the per-row hand icons.  A button counts only
when its own text is the label, so a task line mentioning it is never pressed.

HARD RULE (Leo 2026-10-03 15:28): any 钻石/付费 text on a page (buttons,
currency bar) means the whole page is skipped and nothing on it is pressed.
Unknown pages are skipped too, with a diagnostic picture.
"""

from __future__ import annotations

import re
from time import monotonic

import cv2
import numpy as np
from qfluentwidgets import FluentIcon

from src.tasks.BaseBD2Task import TEMPLATE_DIR
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.utils.chinese import to_simplified
from src.utils.image_utils import template_match_response
from src.utils.ocr_utils import normalize_ocr_text

EVENT_ENTRY_POINT = (889, 985)  # 主页 bottom bar 「活动」
EVENT_TITLE_KEYWORDS = ("活动",)

# Left card list (1920x1080 reference).
LIST_CARD_X = 422
LIST_SCROLL_POINT = (422 / 1920, 540 / 1080)
LIST_CAPTION_ROI = (322, 262, 202, 545)
# The red badge sits in this strip at each card's top-right corner.
BADGE_STRIP = (496, 265, 30, 545)
BADGE_MIN_AREA, BADGE_MAX_AREA = 80, 400  # 17-18 px squares measured
BADGE_TO_CARD_CENTER = 34
LIST_SCROLL_NOTCHES = 3  # about 2.5 cards; the list overshoots, so wait
LIST_SETTLE_SECONDS = 1.5
LIST_MAX_STEPS = 12

PANEL_ROI = (545, 250, 1100, 585)
CURRENCY_ROI = (1440, 20, 460, 80)
TOKEN_ROI = (1700, 35, 110, 45)

DIAMOND_WORDS = ("钻石", "鑽石", "付费", "付費")
# Leo 2026-10-08: every event page is the same thing: press whatever is lit,
# 「即刻刷新」 first, then claim / unlock / exchange / spin / roll.
EXCHANGE_WORD = "兑换"
LIT_BUTTON_ORDER = ("即刻刷新", "全部领取", "全部解锁", EXCHANGE_WORD, "旋转10次", "旋转1次", "掷骰子")
# These ask 「确认」 before acting (the 钻石 check runs on that box too).
CONFIRM_BUTTONS = ("即刻刷新", "全部解锁")
# A button's own text may carry a little more (e.g. 「旋转1次1次免费」).
BUTTON_TEXT_SLACK = 4
EXCHANGE_PATTERN = re.compile(r"兑换(\d+)次")

# A lit button's brightest channel: white pills 255 / grey 128, blue
# 「全部领取」 231 / 137 (live 4K 2026-10-04).
BUTTON_LIT_MIN_VALUE = 185.0
# An unaffordable exchange shows its cost in red (18% red pixels vs 0%).
RED_COST_SHARE = 0.08

HAND_TEMPLATE = TEMPLATE_DIR / "event" / "reward_hand.png"
HAND_MATCH = 0.8
HAND_ROI = (1450, 255, 170, 575)

# The paid-diamond gem (from 满月付费钻石兑换所's currency bar). Scores 1.0
# there and ≤0.80 on every free event page (tasks, 兑换所, wheel, dice).
DIAMOND_TEMPLATE = TEMPLATE_DIR / "event" / "diamond.png"
DIAMOND_MATCH = 0.9
DIALOG_ROI = (640, 380, 640, 300)

MAX_PAGE_ACTIONS = 25
# A card's page is read this long for its type before it counts as unknown.
PAGE_LOAD_SECONDS = 4.0

_diamond_template = None


def button_lit(frame, box) -> bool:
    """A button's own colour: lit when its brightest channel is high."""
    if frame is None or box is None:
        return False
    height, width = frame.shape[:2]
    x0, y0 = max(0, int(box.x)), max(0, int(box.y))
    x1, y1 = min(width, int(box.x + box.width)), min(height, int(box.y + box.height))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return False
    value = frame[y0:y1, x0:x1, :3].max(axis=2)
    return float(np.median(value)) >= BUTTON_LIT_MIN_VALUE


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


def views_match(first, second) -> bool:
    if first is None or second is None or first.shape != second.shape:
        return False
    return float(np.abs(first - second).mean()) <= LIST_STILL_MAX_DIFF


def find_badges(frame) -> list[int]:
    """Reference y of each red ◆! badge in the card list, top to bottom."""
    height, width = frame.shape[:2]
    scale = width / 1920
    x, y, w, h = BADGE_STRIP
    crop = frame[int(y * scale) : int((y + h) * scale), int(x * scale) : int((x + w) * scale), :3]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = (
        ((hsv[..., 0] <= 8) | (hsv[..., 0] >= 172)) & (hsv[..., 1] >= 150) & (hsv[..., 2] >= 150)
    ).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(red, 8)
    found = []
    for index in range(1, count):
        _cx, cy, _cw, ch, area = stats[index]
        area_ref = area / scale / scale
        if BADGE_MIN_AREA <= area_ref <= BADGE_MAX_AREA:
            found.append(round(y + (cy + ch / 2) / scale))
    return sorted(found)


def diamond_icon(frame, rois) -> bool:
    """True when the paid-diamond gem shows inside any reference ROI."""
    global _diamond_template
    if _diamond_template is None:
        _diamond_template = cv2.imread(str(DIAMOND_TEMPLATE))
    if frame is None or _diamond_template is None:
        return False
    reference = cv2.resize(frame[:, :, :3], (1920, 1080), interpolation=cv2.INTER_AREA)
    for x, y, w, h in rois:
        result = template_match_response(reference[y : y + h, x : x + w], _diamond_template)
        if result is not None and result.size and float(result.max()) >= DIAMOND_MATCH:
            return True
    return False


class EventRewardTask(_ClaimTaskBase):
    claim_log_name = "event_reward"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "领取活动奖励"
        self.description = (
            "打开活动页，依序进入有红点的活动，哪里亮了按哪里（即刻刷新优先）。"
            "有钻石或付费字样的页面一律不碰。"
        )
        self.icon = FluentIcon.SHOPPING_CART

    # -- flow -------------------------------------------------------------

    def run_claim(self) -> bool:
        if not self._open_page_from_home("活动", EVENT_ENTRY_POINT, EVENT_TITLE_KEYWORDS):
            return self._claim_fail("打开活动页")
        skipped: set[str] = set()
        claimed = 0
        # Leo 10-04: a second pass from the top, since a claim can badge
        # another card; skipped pages (diamonds, unknown) do not count.
        for sweep in (1, 2):
            if sweep == 2 and not self._reopen_event_page():
                return self._claim_fail("重新打开活动页")
            done = self._sweep_list(skipped)
            claimed += done
            self.info_set("活动领取轮次", f"第{sweep}轮处理 {done} 个")
            if sweep == 1 and done == 0:
                break
        self.info_set("活动领取结果", f"处理 {claimed} 个，跳过 {len(skipped)} 个")
        if not self._leave_to_home("活动", EVENT_TITLE_KEYWORDS):
            return self._claim_fail("活动页返回主页")
        return True

    def _reopen_event_page(self) -> bool:
        """Leave to 主页 and open 活动 again before the second pass (Leo
        2026-10-08): the red badges only refresh when the page is reopened."""
        self.info_set("当前阶段", "活动：关闭后重新打开，再看一轮")
        if not self._leave_to_home("活动", EVENT_TITLE_KEYWORDS):
            return False
        return self._open_page_from_home("活动", EVENT_ENTRY_POINT, EVENT_TITLE_KEYWORDS)

    def _sweep_list(self, skipped: set[str]) -> int:
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
                    skipped.add(key)
                    continue
                self.info_set("当前阶段", f"打开活动：{key}")
                self._click_reference(LIST_CARD_X, badge_y + BADGE_TO_CARD_CENTER, after_sleep=1.2)
                if self._handle_page(caption):
                    handled += 1
                else:
                    skipped.add(key)
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

    def _next_badge(self, frame, skipped: set[str]):
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
        The 钻石 check runs on every look and once more on a later frame
        before anything is pressed, so a currency bar drawn after the panel
        buttons still stops the page (HARD RULE).
        """
        label = caption or "活动"
        self.sleep(0.6)
        end_at = monotonic() + PAGE_LOAD_SECONDS
        known = False
        while True:
            frame = self.capture_frame()
            panel = self._reference_boxes(frame, PANEL_ROI, "活动内容")
            if self._page_has_diamonds(frame, panel, caption, label):
                return False
            known = bool(self._page_buttons(frame, panel, set()) or self._hand_points(frame))
            if known or monotonic() >= end_at:
                break
            self.sleep(0.5)
        if not known:
            self.log_info(f"活动「{label}」：页面上没有认得的按钮，跳过。")
            self._save_flow_diagnostic(f"event_reward_unknown_{label}")
            return False
        self.sleep(0.4)
        frame = self.capture_frame()
        panel = self._reference_boxes(frame, PANEL_ROI, "活动内容")
        if self._page_has_diamonds(frame, panel, caption, label):
            return False
        return self._press_what_is_lit(label)

    def _page_has_diamonds(self, frame, panel, caption: str, label: str) -> bool:
        currency = self._reference_boxes(frame, CURRENCY_ROI, "活动货币")
        text = caption + " " + self._boxes_text(panel) + " " + self._boxes_text(currency)
        self.info_set("活动页 OCR", text[:160] or "-")
        if any(word in text for word in DIAMOND_WORDS):
            self.log_info(f"活动「{label}」：页面有钻石／付费字样，整页跳过。")
            return True
        if diamond_icon(frame, (PANEL_ROI, CURRENCY_ROI)):
            self.log_info(f"活动「{label}」：页面有钻石图案，整页跳过。")
            return True
        return False

    def _diamonds_now(self, frame, panel, label: str) -> bool:
        """钻石 re-check on the frame about to be pressed: the page check ran once
        before the loop, but a later press (next spin, next 兑换) can show a
        paid cost that was not there at first."""
        return self._page_has_diamonds(frame, panel, "", label)

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

    def _press_what_is_lit(self, label: str) -> bool:
        """Leo 2026-10-08: on a badged page press whatever is lit (哪裡亮了點哪裡),
        即刻刷新 first.  False when the page was skipped for 钻石."""
        skip: set[str] = set()
        for _ in range(MAX_PAGE_ACTIONS):
            frame = self.capture_frame()
            panel = self._reference_boxes(frame, PANEL_ROI, f"{label}按钮")
            if self._diamonds_now(frame, panel, label):
                return False
            lit = [(word, box) for word, box, on in self._page_buttons(frame, panel, skip) if on]
            if lit:
                word, box = lit[0]
                self.log_info(f"活动「{label}」：{word}。")
                self._click_reference_box(box, after_sleep=1.2)
                if word in CONFIRM_BUTTONS or word.startswith(EXCHANGE_WORD):
                    if not self._confirm_dialog(label) and word.startswith(EXCHANGE_WORD):
                        # No confirm box: the tokens ran out (Leo 10-05).
                        skip.add(word)
                        continue
                self._settle(label, frame)
                continue
            points = self._hand_points(frame)
            if not points:
                break
            self.log_info(f"活动「{label}」：领取一行任务奖励。")
            self._click_reference(*points[0], after_sleep=1.0)
            self._settle(label, frame)
        return True

    def _hand_points(self, frame) -> list[tuple[int, int]]:
        template = getattr(self, "_hand_template", None)
        if template is None:
            template = cv2.imread(str(HAND_TEMPLATE))
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

    def _tokens(self, frame) -> int | None:
        """The event-token count, for the log only (see ``_press_what_is_lit``)."""
        text = self._boxes_text(self._reference_boxes(frame, TOKEN_ROI, "活动代币"))
        tokens = parse_token_count(text)
        self.info_set("活动代币", "-" if tokens is None else str(tokens))
        return tokens

    def _confirm_dialog(self, label: str) -> bool:
        """Press 确认 on the 兑换／即刻刷新 dialog; False when none appeared."""
        end_at = monotonic() + 4.0
        while monotonic() < end_at:
            frame = self.capture_frame()
            boxes = self._reference_boxes(frame, DIALOG_ROI, f"{label}确认")
            text = self._boxes_text(boxes)
            if any(word in text for word in DIAMOND_WORDS) or diamond_icon(frame, (DIALOG_ROI,)):
                self.log_info(f"活动「{label}」：确认框有钻石图案或字样，取消。")
                cancel = self._box_with(boxes, ("取消",))
                if cancel is not None:
                    self._click_reference_box(cancel, after_sleep=0.8)
                return False
            confirm = self._box_with(boxes, ("确认",))
            if confirm is not None:
                self._click_reference_box(confirm, after_sleep=1.5)
                return True
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
