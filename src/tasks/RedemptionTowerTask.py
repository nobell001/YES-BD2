"""Daily 救赎之塔 快速战斗 on the 恶魔城 (Evil Castle) cartridge.

Flow from Leo's 2K screenshots, 2026-10-21: 主页 → 游戏卡珍藏集 → Evil Castle
card → field → walk straight up (W) to the altar → the red crossed-swords
marker on top opens the 恶魔城 page → 救赎之塔 → 快速战斗 (no level picked) →
MAX → 战斗 → back home.

Leo 2026-10-21: 「不用選關 點快速戰鬥 不用僅免費」, then 「就直接max 不管那麼多
不用對數字」: the 「仅使用免费救赎之钥匙」 switch is left as the player has it,
and MAX is whatever the game allows.  The keys at the top right only stop a
run at 0/10.

The field: 「剛切到卡帶大概是圖5的位置 鍵盤移動直直往上按住w就會走到」, the
mouse cannot reach the marker until it is on screen, and the map has nothing
to interact with (no teleport, no icon).  Like 末日之书, coming back from
主页 keeps the last position; 「你不要明明位置對 判定錯」: the start is never
guessed, the walk up is always tried first, and only when it does not reach
the 恶魔城 page is the spawn reset (another cartridge and back) and the walk
tried once more.
"""

from __future__ import annotations

import re
from pathlib import Path
from time import monotonic

import cv2
import numpy as np
from qfluentwidgets import FluentIcon

from src.tasks.DoomBookTask import (
    CARTRIDGE_SLOT_POINT,
    COLLECTION_TITLE_KEYWORDS,
    DOOM_PAGE_BACK_POINT,
    FIELD_SKILL_HUD_ROI,
    QUICK_SLOT_XS,
    CartridgeFieldTask,
)
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils import image_io
from src.utils.image_utils import template_match_response
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text
from src.utils.stage_walk import MARKER_TARGET, NUDGE_SEQUENCE, plan_step
from src.utils.wait_limits import STUCK_SECONDS, HeldFor, StillTimer

LABEL = "救赎之塔"
ASSET_DIR = (
    Path(__file__).resolve().parents[2] / "recognition-assets" / "template-assets" / "evil_castle"
)
# The Evil Castle logo on its 游戏卡珍藏集 card, cut from Leo's 4K frame of
# 10-11 at 1080 reference.  When it is the cartridge in use a yellow ▶ sits
# on the middle of the logo, so only its two 40 px ends are matched: 1.00 on
# the page (selected or not), next best 0.50.
CARD_TEMPLATE = ASSET_DIR / "evil_castle_card.png"
CARD_SIDE_WIDTH = 40

# The red crossed-swords marker on the altar (Leo's 2K frame, 1080 reference);
# alpha = its red pixels.  The whole map is red and orange, so the colour
# alone finds torches and leaves: the shape is matched, and the match must
# still be mostly marker red.  1.00 on the marker, at most 0.50 elsewhere.
MARKER_TEMPLATE = ASSET_DIR / "castle_marker.png"
MARKER_MIN_SCORE = 0.8
MARKER_MIN_RED = 0.6
# Top-right icons and their red badges, the minimap.
MARKER_HUD_MASKS = ((1540, 0, 380, 110), (115, 85, 220, 200))

# The level list's ✓ (grey for cleared, white for the selected one) on the
# 救赎之塔 page, Leo's 2K frame of 10-21.  Leo 2026-10-21: no ✓ at all = not
# played this season, 快速战斗 cannot be used: leave, not a failure.  Ticks
# 0.78-1.00, other pages at most 0.55.
LEVEL_TICK_TEMPLATE = ASSET_DIR / "level_tick.png"
LEVEL_LIST_ROI = (230, 100, 210, 980)
LEVEL_TICK_MIN_SCORE = 0.7

# Walking up (W): one hold at a time, each followed by a look.  From the
# spawn the altar is a few seconds up; the cap only ends a walk that can
# never get there (another spot, a wall).
WALK_HOLD_SECONDS = 0.6
WALK_MAX_SECONDS = 12.0
# Click-to-move: a point straight above the character.
CLICK_UP_POINT = (955, 250)
CLICK_UP_MAX = 12
CLICK_SETTLE_SECONDS = 1.2
# Standing on the altar circle (left there by the last run) the page does not
# open again and W is blocked by the wall behind (2K clone 10-21, runs 2-3):
# one step down off the circle, then up onto it again.
STEP_BACK_SECONDS = 1.2
# On the circle the character hides the marker and the fires keep the picture
# moving, so the "picture still" check never fires (4K clone 10-21 run b: 12 s
# of W plus the nudges, ~55 s).  From the spawn the marker shows after two
# holds, so the first walk steps down after this many holds with no marker.
WALK_UNSEEN_HOLDS = 4
CLICK_DOWN_POINT = (955, 820)
STEP_BACK_SETTLE_SECONDS = 1.5

CASTLE_TITLE_KEYWORDS = ("恶魔城", "惡魔城")
TOWER_KEYWORDS = ("救赎之塔", "救贖之塔")
# The 救赎之塔 card in the middle of the 恶魔城 page (its name, 2K 10-21).
TOWER_CARD_ROI = (780, 590, 360, 90)
TOWER_CARD_POINT = (960, 540)
# 救赎之塔 page.
QUICK_BATTLE_KEYWORDS = ("快速战斗", "快速戰鬥")
QUICK_BATTLE_ROI = (1310, 940, 280, 90)
QUICK_BATTLE_POINT = (1445, 985)
# Between two seasons the 救赎之塔 card opens the 排名 page instead, with
# 「赛季结算中 / 离结算结束还有…」 in the middle (繁中 4K 2026-11-05: 賽季結算中,
# 7 小时 56 分 before the 08:00 reset).  Nothing to fight until it ends.
SETTLING_ROI = (1080, 440, 420, 110)
SETTLING_KEYWORDS = ("赛季结算中", "結算中", "结算中")
SETTLING_NOTE = "救赎之塔赛季结算中，这期结束了，新一期开始前打不了"
# Keys at the top right: 「10/10」.
KEYS_ROI = (1690, 25, 200, 60)
# The 快速战斗 dialog.
DIALOG_TITLE_ROI = (700, 250, 520, 70)
REWARD_LINE_ROI = (640, 322, 300, 44)
BATTLE_BUTTON_ROI = (885, 778, 315, 56)
BATTLE_BUTTON_POINT = (1042, 806)
BATTLE_KEYWORDS = ("战斗", "戰鬥")
MAX_POINT = (1169, 543)
DIALOG_CANCEL_POINT = (804, 805)
# The 「攻略完毕」 result screen (Leo's 2K frame, 10-21): 「点击画面继续」 at
# the bottom; Leo 「點空白處就好」.  The blank spot is the floor bottom left.
RESULT_TITLE_ROI = (1000, 105, 560, 95)
RESULT_TITLE_KEYWORDS = ("攻略完毕", "攻略完畢")
RESULT_CONTINUE_ROI = (1060, 915, 440, 75)
RESULT_CONTINUE_KEYWORDS = ("点击画面继续", "點擊畫面繼續")
RESULT_BLANK_POINT = (300, 1000)
RESULT_TAPS_MAX = 5
# The result screen glows (never still): the whole wait is capped.
AFTER_BATTLE_MAX_SECONDS = 60.0
TOWER_PAGE_SETTLE_SECONDS = 3.0

DRY_RUN_KEY = "_试跑不按战斗"
# Test runs only: skip each first way so the fallback runs instead (P key,
# the row's second card, a spawn reset, the tower's fixed point, keys unread).
# Leo 2026-10-21 「注意都要有備用方案 包含進卡帶這些」.
FALLBACK_TEST_KEY = "_试跑走备用方案"


def keys_empty(names) -> bool:
    """One OCR box in the corner starts with 「0/10」.

    Leo 2026-10-21 「常讀錯就不要讀鑰匙」「不要0/10就好」: the count itself is
    never used (the 4K clone read 69/10, 29/10 and 9/102 for 9/10).  After
    「/10」 a 「+」 or small text for paid keys may follow; the refill timer
    「+19:06」 above is its own box.
    """
    return any(re.match(r"0[/／]\d", normalize_ocr_text(name or "")) for name in names)


def parse_reward_count(text: str) -> int | None:
    """「战斗10次奖励」 → 10."""
    match = re.search(r"[战戰][斗鬥]\s*(\d+)\s*次", normalize_ocr_text(text or ""))
    return int(match.group(1)) if match else None


_marker_cache: list = []


def find_castle_marker(frame_1080: np.ndarray) -> tuple[int, int] | None:
    """Centre of the altar's crossed-swords marker, or None."""
    if not _marker_cache:
        marker = image_io.read(MARKER_TEMPLATE, cv2.IMREAD_UNCHANGED)
        if marker is None or marker.ndim != 3 or marker.shape[2] != 4:
            return None
        _marker_cache.append((cv2.cvtColor(marker[:, :, :3], cv2.COLOR_BGR2GRAY), marker[:, :, 3]))
    template, mask = _marker_cache[0]
    grey = cv2.cvtColor(frame_1080[:, :, :3], cv2.COLOR_BGR2GRAY)
    response = np.nan_to_num(
        template_match_response(grey, template, mask, zero_mean=True),
        nan=-1.0,
        posinf=-1.0,
        neginf=-1.0,
    )
    height, width = template.shape
    for x, y, w, h in MARKER_HUD_MASKS:
        response[max(0, y - height) : y + h, max(0, x - width) : x + w] = -1.0
    for _candidate in range(3):
        _low, score, _where, (x, y) = cv2.minMaxLoc(response)
        if score < MARKER_MIN_SCORE:
            return None
        patch = frame_1080[y : y + height, x : x + width, :3]
        if marker_red_ratio(patch, mask) >= MARKER_MIN_RED:
            return x + width // 2, y + height // 2
        response[max(0, y - 10) : y + 10, max(0, x - 10) : x + 10] = -1.0
    return None


_tick_cache: list = []


def level_ticks(frame_1080: np.ndarray) -> int:
    """How many level rows carry a ✓ on the 救赎之塔 page."""
    if not _tick_cache:
        tick = image_io.read(LEVEL_TICK_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        if tick is None:
            return 0
        _tick_cache.append(tick)
    tick = _tick_cache[0]
    x, y, w, h = LEVEL_LIST_ROI
    grey = cv2.cvtColor(frame_1080[y : y + h, x : x + w, :3], cv2.COLOR_BGR2GRAY)
    response = np.nan_to_num(template_match_response(grey, tick, zero_mean=True), nan=-1.0)
    found = 0
    for _row in range(12):
        _low, score, _where, (px, py) = cv2.minMaxLoc(response)
        if score < LEVEL_TICK_MIN_SCORE:
            break
        found += 1
        response[max(0, py - 30) : py + 30, max(0, px - 30) : px + 30] = -1.0
    return found


def marker_red_ratio(patch: np.ndarray, mask: np.ndarray) -> float:
    """Share of the marker's own pixels that are marker red in ``patch``."""
    if patch.shape[:2] != mask.shape:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    red = ((hue <= 8) | (hue >= 170)) & (saturation >= 100) & (value >= 130)
    inside = mask > 0
    return float(red[inside].mean()) if inside.any() else 0.0


class RedemptionTowerTask(CartridgeFieldTask):
    claim_log_name = "redemption_tower"
    label = LABEL
    card_template = CARD_TEMPLATE
    card_side_width = CARD_SIDE_WIDTH
    # Evil Castle is the 战斗玩法 bar's second card, as on 游戏卡珍藏集.
    quick_slot_guess = QUICK_SLOT_XS[1]
    # Leo 2026-11-05 「精煉 製作 爛裝跑商 救贖之塔 這些你就重作沒關係 資源量微乎其微」:
    # a failed or frozen run goes home and runs once more, like the others.
    frozen_retry = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "救赎之塔"
        self.description = (
            "主页卡带 → 恶魔城 → 往上走到祭坛 → 救赎之塔 → 快速战斗（不选关）→ MAX"
            " → 战斗 → 回主页。走法跟镜中之战的「舞台移动方式」一样。"
        )
        self.icon = FluentIcon.FLAG
        self.default_config.update({DRY_RUN_KEY: False, FALLBACK_TEST_KEY: False})

    # -- entry --------------------------------------------------------------------

    def run_claim(self) -> bool:
        self._why = ""
        self.done_already_note = ""
        forced = self._fallback_test()
        if forced:
            self.log_info(f"{LABEL}：试跑备用方案，每步跳过第一种做法。")
        if (
            forced
            or not self._open_page_from_home(
                "游戏卡珍藏集", CARTRIDGE_SLOT_POINT, COLLECTION_TITLE_KEYWORDS
            )
        ) and not self._collection_by_key():
            return self._claim_fail("打开游戏卡珍藏集")
        if (forced or not self._enter_cartridge()) and not self._enter_by_row():
            return self._claim_fail("进入恶魔城")
        self.clear_field_followers()  # 没有派遣记录就等跟随角色靠过来
        self._keys_refused = False
        if forced or not self._reach_marker():
            if self._keys_refused:
                self._field_to_home()
                return self._claim_fail("键盘走位（游戏窗口不在最前面）")
            # Only now: the walk up did not get there, so the start was not
            # the spawn (left here last time).  Another cartridge and back.
            self.log_info(f"{LABEL}：往上走没到祭坛，切换卡带回到出生点再走一次。")
            if not (self._reset_to_spawn() and self._reach_marker()):
                self._save_flow_diagnostic("redemption_tower_walk_failed")
                self._note_why("往上走没走到恶魔城祭坛")
                self._field_to_home()
                return self._claim_fail("走到祭坛")
        done = self._quick_battle()
        if not self._castle_pages_to_home():
            return self._claim_fail("返回主页")
        if not done:
            return self._claim_fail("快速战斗")
        return True

    # -- what the screen shows -----------------------------------------------------

    def _field_visible(self, frame) -> bool:
        """A cartridge field: the skill HUD's SPACE / TAB labels."""
        text = self._text_in(frame, FIELD_SKILL_HUD_ROI, "技能栏")
        return "space" in text or "tab" in text

    def _castle_page_visible(self, frame) -> bool:
        """The 恶魔城 title, or else the 救赎之塔 card's name in the middle."""
        if self._title_visible(frame, CASTLE_TITLE_KEYWORDS, "恶魔城"):
            return True
        if self._title_visible(frame, TOWER_KEYWORDS, LABEL):
            return False
        text = self._text_in(frame, TOWER_CARD_ROI, "救赎之塔卡")
        return keyword_match_count(text, TOWER_KEYWORDS, fuzzy_ratio=0.8) >= 1

    def _settling_page_visible(self, frame) -> bool:
        """The 排名 page with 赛季结算中: the season is over."""
        text = self._text_in(frame, SETTLING_ROI, "赛季结算中")
        return keyword_match_count(text, SETTLING_KEYWORDS, fuzzy_ratio=0.8) >= 1

    def _tower_page_visible(self, frame) -> bool:
        """The 救赎之塔 title, or else its 快速战斗 button (no dialog over it)."""
        if self._title_visible(frame, TOWER_KEYWORDS, LABEL):
            return True
        text = self._text_in(frame, QUICK_BATTLE_ROI, "快速战斗按钮")
        return keyword_match_count(text, QUICK_BATTLE_KEYWORDS, fuzzy_ratio=0.8) >= 1 and not (
            self._dialog_visible(frame)
        )

    def _dialog_visible(self, frame) -> bool:
        """The 快速战斗 dialog: its title, or else its 「战斗N次奖励」 line."""
        text = self._text_in(frame, DIALOG_TITLE_ROI, "快速战斗弹窗")
        if keyword_match_count(text, QUICK_BATTLE_KEYWORDS, fuzzy_ratio=0.8) >= 1:
            return True
        return parse_reward_count(self._text_in(frame, REWARD_LINE_ROI, "快速战斗奖励")) is not None

    # -- fallbacks for the way in -------------------------------------------------

    def _fallback_test(self) -> bool:
        """A dry run that takes every fallback (never with a real 战斗)."""
        config = getattr(self, "config", None) or {}
        return bool(config.get(FALLBACK_TEST_KEY, False)) and bool(config.get(DRY_RUN_KEY, False))

    def _collection_by_key(self) -> bool:
        """主页's own key P opens 游戏卡珍藏集 when the click did not."""
        if not self._wait_for_home_confirmation(f"{LABEL}按 P 前主页确认", timeout=3.0):
            return False
        self.log_info(f"{LABEL}：点卡带机没打开游戏卡珍藏集，改按快捷键 P。")
        if not self.tap_key("P", after_sleep=1.5):
            return False
        return bool(self._wait_for_title("游戏卡珍藏集", COLLECTION_TITLE_KEYWORDS))

    def _enter_by_row(self) -> bool:
        """The cover was not matched: the 战斗玩法 row's second card, where
        Evil Castle sits (Leo's 4K 10-11), by the row header's place."""
        from src.utils.cartridge_collection import (
            BATTLE_ROW_PATTERNS,
            find_row_header,
            row_card_point,
        )

        if not self._title_visible(self.capture_frame(), COLLECTION_TITLE_KEYWORDS, "游戏卡珍藏集"):
            return False
        for notches in (0, 5, -3):
            if notches:
                self.scroll_client((0.5, 0.55), notches, count=1, after_sleep=1.0)
            frame = self.capture_frame()
            height, width = frame.shape[:2]
            header = find_row_header(
                self._roi_boxes(frame, None, "游戏卡珍藏集"), BATTLE_ROW_PATTERNS, (width, height)
            )
            point = row_card_point(header, column=1) if header is not None else None
            if point is None:
                continue
            self.log_info(f"{LABEL}：没认出 Evil Castle 卡带图，点战斗玩法第二张卡 {point}。")
            self._click_reference(*point, after_sleep=2.0)  # 不用确认：下面等地图
            return self._wait_for(self._field_visible, timeout=STUCK_SECONDS)
        self._note_why("游戏卡珍藏集里认不出恶魔城卡带，也找不到战斗玩法那一排")
        return False

    def _reference(self, frame):
        return cv2.resize(
            frame[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT), interpolation=cv2.INTER_AREA
        )

    # -- the walk ------------------------------------------------------------------

    def _field_left(self) -> bool | None:
        """The field went away mid-walk: the 恶魔城 page opening (it fades in)
        or a passing frame.  True = the page, False = the field again,
        None = neither (logged)."""
        seen = []

        def check(frame) -> bool:
            if self._castle_page_visible(frame):
                seen.append(True)
                return True
            return self._field_visible(frame)

        if not self._wait_for(check, timeout=STUCK_SECONDS):
            self.log_info(f"{LABEL}：走位途中离开了恶魔城地图，也没看到恶魔城页面。")
            return None
        return bool(seen)

    def _click_to_marker(self) -> bool:
        """Click-to-move up; standing on the circle, one step down and again."""
        if self._click_up():
            return True
        if self._keys_refused or not self._field_visible(self.capture_frame()):
            return False
        self.log_info(f"{LABEL}：点往上没开恶魔城页，可能站在祭坛上，先往下点一步再往上。")
        down = CLICK_DOWN_POINT
        self._click_reference(*down, after_sleep=STEP_BACK_SETTLE_SECONDS)  # 不用确认：再往上走
        return self._click_up()

    def _click_up(self) -> bool:  # 会补点：循环往上点到看见标记
        """Click straight up until the marker shows, then on it."""
        self.info_set("当前阶段", "鼠标往上走到祭坛")
        for click in range(1, CLICK_UP_MAX + 1):
            frame = self.capture_frame()
            if self._castle_page_visible(frame):
                return True
            if not self._field_visible(frame):
                left = self._field_left()
                if left is None:
                    return False
                if left:
                    return True
                continue
            marker = find_castle_marker(self._reference(frame))
            point = marker or CLICK_UP_POINT
            self.info_set("战斗标记位置", f"第{click}次点击 {'标记' if marker else '往上'} {point}")
            self._click_reference(*point, after_sleep=0.3)  # 不用确认：下面等恶魔城页
            if self._wait_for(
                self._castle_page_visible, timeout=CLICK_SETTLE_SECONDS if not marker else 6.0
            ):
                return True
        return False

    def _walk_to_marker(self) -> bool:
        """WASD up; standing on the circle, one step down (S) and again."""
        if self._walk_up(WALK_UNSEEN_HOLDS):
            return True
        if self._keys_refused or not self._field_visible(self.capture_frame()):
            return False
        self.log_info(f"{LABEL}：往上走没开恶魔城页，可能站在祭坛上，先往下退一步再往上。")
        if not self.hold_key("s", STEP_BACK_SECONDS, after_sleep=0.6):
            self._keys_refused = True
            return False
        return self._walk_up()

    def _walk_up(self, unseen_holds: int | None = None) -> bool:
        """Hold W; once the marker shows, steer onto it.  With `unseen_holds`,
        give up after that many holds without ever seeing the marker."""
        self.info_set("当前阶段", "键盘往上走到祭坛")
        walked = 0.0
        holds = 0
        seen = False
        still = StillTimer()
        while walked < WALK_MAX_SECONDS:
            frame = self.capture_frame()
            if self._castle_page_visible(frame):
                return True
            if not self._field_visible(frame):
                left = self._field_left()
                if left is None:
                    return False
                if left:
                    return True
                continue
            marker = find_castle_marker(self._reference(frame))
            seen = seen or marker is not None
            if not seen and unseen_holds is not None and holds >= unseen_holds:
                self.log_info(f"{LABEL}：往上走了 {holds} 下还没看到祭坛标记。")
                return False
            step = plan_step(marker, MARKER_TARGET) if marker is not None else None
            if marker is not None and step is None:
                break  # on the marker; the page should open
            key, seconds = (
                (step.key, step.seconds) if step is not None else ("w", WALK_HOLD_SECONDS)
            )
            self.info_set(
                "战斗标记位置", f"{'看到 ' + str(marker) if marker else '还没看到，往上走'}"
            )
            if not self.hold_key(key, seconds, after_sleep=0.4):
                self._keys_refused = True
                return False
            walked += seconds
            holds += 1
            # Holding W against a wall leaves the picture still.
            if (
                marker is None
                and still.still_for(self.capture_frame(), monotonic())
                >= 2 * WALK_HOLD_SECONDS + 1.0
            ):
                self.log_info(f"{LABEL}：一直往上走画面不动，没看到祭坛。")
                return False
        for step in NUDGE_SEQUENCE:
            if self._wait_for(self._castle_page_visible, timeout=1.0):
                return True
            if not self.hold_key(step.key, step.seconds, after_sleep=0.6):
                self._keys_refused = True
                return False
        return self._wait_for(self._castle_page_visible, timeout=3.0)

    # -- the battle ----------------------------------------------------------------

    def _open_tower(self) -> bool:
        self.info_set("当前阶段", "选择救赎之塔")
        boxes = self._wait_boxes(
            TOWER_CARD_ROI,
            "救赎之塔卡",
            lambda found: self._box_with(found, TOWER_KEYWORDS) is not None,
            timeout=3.0,
            reference=True,
        )
        box = None if self._fallback_test() else self._box_with(boxes, TOWER_KEYWORDS)
        point = (
            (round(box.x + box.width / 2), round(box.y + box.height / 2))
            if box
            else TOWER_CARD_POINT
        )
        if box is None:
            why = "试跑备用方案" if self._fallback_test() else "没读到「救赎之塔」字"
            self.log_info(f"{LABEL}：{why}，点它的固定位置。")
        if self.press_and_confirm(
            f"{LABEL}卡",
            lambda: self._click_reference(*point, after_sleep=1.0),
            lambda: self._tower_page_visible(self.capture_frame()),
            still_before=lambda: self._castle_page_visible(self.capture_frame()),
            timeout=4.0,
        ) or self._wait_for(
            lambda shown: self._tower_page_visible(shown) or self._settling_page_visible(shown),
            timeout=STUCK_SECONDS,
        ):
            if self._settling_page_visible(self.capture_frame()):
                self.log_info(f"{LABEL}：{SETTLING_NOTE}，跳过。")
                self.done_already(SETTLING_NOTE)
            return True
        self._note_why("点了救赎之塔没有进入")
        return False

    def _no_keys_left(self) -> bool:
        """0/10 at the top right on two frames in a row."""

        def empty() -> bool:
            boxes = self._roi_boxes(self.capture_frame(), KEYS_ROI, "救赎之钥匙")
            return keys_empty(box.name for box in boxes)

        if not empty():
            return False
        self.sleep(0.3)
        return empty()

    def _quick_battle(self) -> bool:
        if not self._open_tower():
            return False
        if getattr(self, "done_already_note", "") == SETTLING_NOTE:
            return True
        if not self.look_again(lambda: level_ticks(self._reference(self.capture_frame()))):
            self.log_info(f"{LABEL}：左边关卡一个勾都没有，这一期还没打过，不能快速战斗，退出。")
            return True
        if not self._fallback_test() and self._no_keys_left():
            self.log_info(f"{LABEL}：钥匙 0/10，今天不用打了。")
            return True

        self.info_set("当前阶段", "快速战斗")
        quick = self._box_with(
            self._reference_boxes(self.capture_frame(), QUICK_BATTLE_ROI, "快速战斗"),
            QUICK_BATTLE_KEYWORDS,
        )
        point = (
            (round(quick.x + quick.width / 2), round(quick.y + quick.height / 2))
            if quick
            else QUICK_BATTLE_POINT
        )
        if not self.press_and_confirm(
            f"{LABEL}「快速战斗」",
            lambda: self._click_reference(*point, after_sleep=1.0),
            lambda: self._dialog_visible(self.capture_frame()),
            still_before=lambda: not self._dialog_visible(self.capture_frame()),
            timeout=4.0,
        ):
            self._note_why("点了快速战斗没有出现场数窗口")
            return False

        # Leo 2026-10-21 「就直接max 不管那麼多 不用對數字」「目標是完成任務」:
        # MAX, then 战斗; the game itself caps MAX at the keys there are.
        self.info_set("当前阶段", "场数 MAX")
        self._click_reference(*MAX_POINT, after_sleep=0.8)  # 不用确认：MAX 只改场数
        if bool(self.config.get(DRY_RUN_KEY, False)):
            self.log_info(f"{LABEL}：试跑，已按 MAX，不按战斗，取消。")
            self._cancel_dialog()
            return True

        button = self._box_with(
            self._reference_boxes(self.capture_frame(), BATTLE_BUTTON_ROI, "快速战斗按钮"),
            BATTLE_KEYWORDS,
        )
        if button is not None:
            point = (round(button.x + button.width / 2), round(button.y + button.height / 2))
        elif self._dialog_visible(self.capture_frame()):
            # Still the dialog: its 战斗 button sits at its fixed place.
            self.log_info(f"{LABEL}：没读到「战斗」字，点它的固定位置。")
            point = BATTLE_BUTTON_POINT
        else:
            self._note_why("场数窗口不见了，没按战斗")
            return False
        self.info_set("当前阶段", "战斗 MAX")
        # Spends keys: pressed once, never again (retries=0).
        if not self.press_and_confirm(
            f"{LABEL}「战斗」",
            lambda: self._click_reference(*point, after_sleep=1.5),
            self._dialog_gone,
            retries=0,
            timeout=STUCK_SECONDS,
        ):
            self._note_why("按了战斗，场数窗口没有关（可能钥匙用完了）")
            if self._dialog_visible(self.capture_frame()):
                self._cancel_dialog()
            return False
        return self._after_battle()

    def _after_battle(self) -> bool:
        """Tap the 「攻略完毕」 screen away until the 救赎之塔 page is back.

        The dialog closed on 战斗, so the battles ran: done once the result
        screen was seen or the 救赎之塔 page is back.  A result screen that
        taps do not close gets Esc.
        """
        still = StillTimer()
        taps = 0
        seen_result = False
        # One misread look does not start the settle over (HeldFor).
        page_held = HeldFor()
        end_at = monotonic() + AFTER_BATTLE_MAX_SECONDS
        while True:
            frame = self.capture_frame()
            if self._result_visible(frame) and taps < RESULT_TAPS_MAX:
                seen_result = True
                taps += 1
                self.info_set("当前阶段", "攻略完毕，点空白处继续")
                if taps <= 3:
                    self._click_reference(*RESULT_BLANK_POINT, after_sleep=1.2)  # 不用确认：重看
                else:
                    self.log_info(f"{LABEL}：「攻略完毕」点空白处关不掉，改按 Esc。")
                    self.tap_escape(after_sleep=1.2)
                still.reset()
                continue
            # Without the result screen, the page must stay a moment: the
            # result may still be on its way.
            page_visible = self._tower_page_visible(frame)
            page_for = page_held.look(page_visible, monotonic())
            if page_visible and (seen_result or page_for >= TOWER_PAGE_SETTLE_SECONDS):
                self.log_info(f"{LABEL}：快速战斗完成。")
                return True
            if self.close_known_popup(LABEL):
                still.reset()
                continue
            if still.still_for(frame, monotonic()) >= STUCK_SECONDS or monotonic() > end_at:
                if seen_result:
                    self.log_info(f"{LABEL}：快速战斗完成，但没回到救赎之塔页。")
                    return True
                self._save_flow_diagnostic("redemption_tower_after_battle")
                self._note_why(
                    f"按了战斗后 {STUCK_SECONDS:.0f} 秒没看到「攻略完毕」，也没回到救赎之塔页"
                )
                return False
            self.sleep(0.6)

    def _result_visible(self, frame) -> bool:
        """The 「攻略完毕」 result screen: its title or 「点击画面继续」."""
        for roi, keywords in (
            (RESULT_TITLE_ROI, RESULT_TITLE_KEYWORDS),
            (RESULT_CONTINUE_ROI, RESULT_CONTINUE_KEYWORDS),
        ):
            text = self._text_in(frame, roi, "攻略完毕")
            if keyword_match_count(text, keywords, fuzzy_ratio=0.8) >= 1:
                return True
        return False

    def _dialog_gone(self) -> bool:
        """No dialog title on two looks (one missed read is not enough)."""
        if self._dialog_visible(self.capture_frame()):
            return False
        self.sleep(0.4)
        return not self._dialog_visible(self.capture_frame())

    def _cancel_dialog(self) -> None:
        for _attempt in range(2):
            if not self._dialog_visible(self.capture_frame()):
                return
            self._click_reference(*DIALOG_CANCEL_POINT, after_sleep=1.0)  # 不用确认：循环重看窗口
        if self._dialog_visible(self.capture_frame()):
            self.log_info(f"{LABEL}：点取消没关掉快速战斗窗口，改按 Esc。")
            self.tap_escape(after_sleep=1.0)

    # -- leaving -------------------------------------------------------------------

    def _castle_pages_to_home(self) -> bool:
        """救赎之塔 page → 恶魔城 page → field (back arrows) → 主页."""
        for _attempt in range(4):
            frame = self.capture_frame()
            if self._field_visible(frame):
                return self._field_to_home()
            if self._dialog_visible(frame):
                self._cancel_dialog()
                continue
            if (
                self._tower_page_visible(frame)
                or self._castle_page_visible(frame)
                or self._settling_page_visible(frame)
            ):
                self.info_set("当前阶段", "返回恶魔城地图")
                self._click_reference(*DOOM_PAGE_BACK_POINT, after_sleep=1.5)  # 不用确认：等地图
                self._wait_for(
                    lambda shown: self._field_visible(shown) or self._castle_page_visible(shown),
                    timeout=STUCK_SECONDS,
                )
                continue
            if self._wait_for_home_confirmation(f"{LABEL}返回主页", timeout=3.0):
                return True
            if not self.close_known_popup(LABEL):
                self.tap_escape(after_sleep=1.0)
        from src.tasks.recovery import recover_to_home

        return bool(recover_to_home(self))
