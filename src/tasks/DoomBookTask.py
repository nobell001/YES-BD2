"""Weekly 末日之书 (LAST NIGHT cartridge): one boss attack run.

Flow from the user's demonstration on the 简体 client, 2026-09-26: home →
cartridge slot at the bottom right (游戏中) → 游戏卡珍藏集 → 末日之书 card →
field → walk onto the red crossed-swords marker → 末日之书 page →
去战斗 → battle, skipped once the skip button turns from grey to white →
RESULT → 离开 → field → home.

The character spawns at a fixed spot when switching in from another
cartridge, but keeps its last position when coming back from home (user,
2026-09-26), so the marker is searched on the whole screen.

The battle costs nothing; it only records the damage.  It moves the way
镜中之战's 「舞台移动方式」 says (Leo, 2026-10-09: one setting for both):
clicking the marker for click-to-move players, or WASD, the keyboard
exception approved for WASD players (see docs/architecture.md).  When the
chosen way does not get there, the other one is tried.
"""

from __future__ import annotations

from pathlib import Path
from time import monotonic

import cv2
import numpy as np
from qfluentwidgets import FluentIcon

from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.tasks.task_vision_mixin import BACK_LOOK_SECONDS, REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils import image_io
from src.utils.cartridge_quick_switch import (
    BATTLE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION,
    BATTLE_GAMEPLAY_CATEGORY_LABEL,
    BATTLE_GAMEPLAY_CATEGORY_POINT,
    GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO,
    category_highlight_ratio,
)
from src.utils.image_utils import template_match_response
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text
from src.utils.press_next import Next, press_next
from src.utils.stage_walk import (
    MARKER_TARGET,
    NUDGE_SEQUENCE,
    find_marker,
    plan_step,
    predict_after_step,
)
from src.utils.wait_limits import (
    STUCK_SECONDS,
    StillTimer,
    is_loading_dark,
    load_wait,
    scene_at_press,
)

# Click-to-move: clicks on the marker, each followed by a wait for the
# character to walk onto it and the 末日之书 page to open.
CLICK_MAX_TRIES = 3
CLICK_ARRIVE_SECONDS = 6.0

# 1920x1080 reference coordinates / ROIs.
CARTRIDGE_SLOT_POINT = (1693, 975)
COLLECTION_TITLE_KEYWORDS = ("游戏卡珍藏集",)
# The LAST NIGHT cover (1080 reference), unique on the page (next best 0.57).
CARD_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "recognition-assets" / "template-assets" / "doom" / "last_night_card.png"
)
CARD_MIN_SCORE = 0.8
# Width of each logo end matched (the middle may hold the ▶ icon).
CARD_SIDE_WIDTH = 55
# A card centre above this sits under the page title bar.
CARD_MIN_Y = 150
FIELD_HUD_ROI = (250, 70, 450, 100)
FIELD_HUD_KEYWORDS = ("最高伤害", "战斗分布")
DOOM_TITLE_KEYWORDS = ("末日之书",)
GO_BATTLE_ROI = (1470, 955, 300, 70)
GO_BATTLE_TEXT = "去战斗"
BATTLE_TEXT_ROI = (60, 950, 330, 90)
BATTLE_KEYWORDS = ("攻击中", "还剩")
# Skip button: grey (p95 ~128) while the battle loads, white (255) once it
# can be pressed.
SKIP_ICON_ROI = (1570, 30, 45, 45)
SKIP_POINT = (1592, 52)
SKIP_READY_P95 = 220
RESULT_BUTTONS_ROI = (1420, 980, 440, 60)
LEAVE_TEXT = "离开"
# 创造新纪录 / 最高伤害 screen after a battle that beats the week's best
# (Leo, 2026-10-08 2K screenshot); both texts sit in the middle right.
NEW_RECORD_ROI = (1080, 360, 420, 230)
NEW_RECORD_TITLES = ("创造新纪录", "創造新紀錄")
NEW_RECORD_DAMAGE = ("最高伤害", "最高傷害")
NEW_RECORD_POINT = (1282, 410)
# The red emblem between the two texts, the same in every client language
# (Leo, 2026-10-08).  Alpha = the emblem's mask, so the animated gold glow
# around it does not count.
NEW_RECORD_ICON_TEMPLATE = CARD_TEMPLATE.parent / "new_record_icon.png"
NEW_RECORD_ICON_ROI = (1210, 412, 140, 142)
NEW_RECORD_ICON_MIN_SCORE = 0.8
NEW_RECORD_GONE_SECONDS = 5.0
FIELD_HOME_POINT = (1797, 57)
# The 末日之书 page's back arrow (top left) returns to the field.
DOOM_PAGE_BACK_POINT = (172, 50)
# Every cartridge field has the P icon (quick switch) at the bottom centre
# and the skill HUD (SPACE / TAB labels) at the bottom right.
FIELD_QUICK_SWITCH_POINT = (851, 997)
FIELD_SKILL_HUD_ROI = (1640, 940, 120, 125)
QUICK_BAR_ROI = (0, 840, 1920, 70)
QUICK_SLOTS_ROI = (60, 920, 1800, 110)
QUICK_SLOT_XS = (150, 330, 510, 690, 870, 1050)
QUICK_SLOT_Y = 970
PLAYING_TEXT = "游戏中"
# The cartridge in use also carries a yellow ▶ on its art; on the battle
# cards a SEASON badge hides 「游戏中」, so only the ▶ shows (Evil Castle, 2K
# clone 10-21).  Mask cut from that slot: 0.73-1.00 on the card in use
# (battle and event bars), at most 0.36 on any other card.
PLAYING_MARK_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "recognition-assets" / "template-assets" / "quick_switch_cartridges" / "playing_mark.png"
)
PLAYING_MARK_CENTRE_Y = 968
PLAYING_MARK_SEARCH = 30
PLAYING_MARK_MIN_SCORE = 0.6
PLAYING_MARK_MIN_LEAD = 0.2
WALK_MAX_STEPS = 25
# Steps walked on a predicted marker position before giving up on it.
MAX_PREDICTED_STEPS = 4
# The longest a battle may run while its screen keeps moving; one whose
# screen stands still for STUCK_SECONDS is stuck (Leo 2026-10-14 「頂多等8秒
# 到10秒」).
BATTLE_TIMEOUT_SECONDS = 120.0
# After a failed battle: how long to look for 离开 or the field. A battle
# that timed out may still be running, so give it a full battle length
# (again only while the screen moves).
RESULT_CLEANUP_SECONDS = BATTLE_TIMEOUT_SECONDS
# Waits for the field, a page or 主页 after a press (were 20-40 s); one that
# spans a loading screen runs up to LOADING_MAX_SECONDS (see _wait_for).
PAGE_WAIT_SECONDS = STUCK_SECONDS
# After 去战斗: how long the page may stay before the click counts as lost.
GO_BATTLE_LEAVE_SECONDS = 9.0
LABEL = "末日之书"


def skip_ready(frame_1080: np.ndarray) -> bool:
    x, y, w, h = SKIP_ICON_ROI
    patch = frame_1080[y : y + h, x : x + w]
    if patch.size == 0:
        return False
    grey = cv2.cvtColor(patch[:, :, :3], cv2.COLOR_BGR2GRAY)
    return float(np.percentile(grey, 95)) >= SKIP_READY_P95


_new_record_icon_cache: list = []


def new_record_icon_score(frame_1080: np.ndarray) -> float:
    """How well the 创造新纪录 emblem matches at its usual spot (0..1)."""
    if not _new_record_icon_cache:
        icon = image_io.read(NEW_RECORD_ICON_TEMPLATE, cv2.IMREAD_UNCHANGED)
        if icon is None or icon.ndim != 3 or icon.shape[2] != 4:
            return 0.0
        _new_record_icon_cache.append(
            (cv2.cvtColor(icon[:, :, :3], cv2.COLOR_BGR2GRAY), icon[:, :, 3])
        )
    template, mask = _new_record_icon_cache[0]
    x, y, w, h = NEW_RECORD_ICON_ROI
    patch = frame_1080[y : y + h, x : x + w]
    if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
        return 0.0
    grey = cv2.cvtColor(patch[:, :, :3], cv2.COLOR_BGR2GRAY)
    return float(template_match_response(grey, template, mask, zero_mean=True).max())


def neighbour_slot(slot_x: int) -> int:
    """An adjacent quick-switch slot, left first.

    Any other cartridge resets the spawn; the neighbour (冒险航线 for
    末日之书, tried live) avoids slot 1, the PVP hub, which can open with
    season notices.
    """
    index = QUICK_SLOT_XS.index(slot_x)
    return QUICK_SLOT_XS[index - 1] if index > 1 else QUICK_SLOT_XS[index + 1]


_playing_mark_cache: list = []


def yellow_mask(patch: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(patch[:, :, :3], cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(hsv)
    return ((hue >= 18) & (hue <= 38) & (sat >= 120) & (val >= 170)).astype(np.float32)


def playing_mark_slot(frame_1080: np.ndarray) -> int | None:
    """The quick-switch slot whose card carries the yellow ▶ (in use)."""
    if not _playing_mark_cache:
        mark = image_io.read(PLAYING_MARK_TEMPLATE, cv2.IMREAD_GRAYSCALE)
        if mark is None:
            return None
        _playing_mark_cache.append((mark > 127).astype(np.float32))
    mark = _playing_mark_cache[0]
    height, width = mark.shape[0] + 2 * PLAYING_MARK_SEARCH, mark.shape[1] + 2 * PLAYING_MARK_SEARCH
    top = PLAYING_MARK_CENTRE_Y - height // 2
    scores = []
    for slot_x in QUICK_SLOT_XS:
        left = slot_x - width // 2
        patch = frame_1080[top : top + height, left : left + width]
        if patch.shape[0] < mark.shape[0] or patch.shape[1] < mark.shape[1]:
            scores.append(0.0)
            continue
        scores.append(float(template_match_response(yellow_mask(patch), mark).max()))
    ranked = sorted(scores, reverse=True)
    if ranked[0] < PLAYING_MARK_MIN_SCORE or ranked[0] - ranked[1] < PLAYING_MARK_MIN_LEAD:
        return None
    return QUICK_SLOT_XS[scores.index(ranked[0])]


def card_cover_match(
    grey, template, side_width: int = CARD_SIDE_WIDTH
) -> tuple[float, tuple[int, int]]:
    """Match the LAST NIGHT logo by its two ends, leaving its middle out.

    When 末日之书 is the cartridge in use the page draws a yellow ▶ over the
    middle of its cover (review 2026-09-27); the logo's left and right ends
    stay clear, so both must match at their usual distance.
    """

    width = template.shape[1]
    left, right = template[:, :side_width], template[:, width - side_width :]
    response = template_match_response(grey, left)
    _low, left_score, _where, (x, y) = cv2.minMaxLoc(response)
    right_x = x + width - side_width
    patch = grey[y : y + right.shape[0], right_x : right_x + right.shape[1]]
    if patch.shape != right.shape:
        return 0.0, (0, 0)
    right_score = float(template_match_response(patch, right).max())
    return min(float(left_score), right_score), (x + width // 2, y + template.shape[0] // 2)


class CartridgeFieldTask(_ClaimTaskBase):
    """Walk from a cartridge's field onto its red crossed-swords marker.

    Shared by 末日之书 and 救赎之塔 (恶魔城).  Not a task itself: the executor
    finds tasks by class (isinstance), so neither subclasses the other.
    """

    # What each cartridge sets.
    label = LABEL
    card_template = CARD_TEMPLATE
    card_side_width = CARD_SIDE_WIDTH
    # The 战斗玩法 quick-switch slot the cartridge normally sits in, clicked
    # only when the card in use is not recognised; None = never guessed.
    quick_slot_guess: int | None = None

    # -- helpers -------------------------------------------------------------------

    def _text_in(self, frame, roi, name: str) -> str:
        return normalize_ocr_text(self._boxes_text(self._roi_boxes(frame, roi, name)))

    def _field_visible(self, frame) -> bool:
        text = self._text_in(frame, FIELD_HUD_ROI, "末日之书地图")
        return keyword_match_count(text, FIELD_HUD_KEYWORDS, fuzzy_ratio=0.8) >= 1

    def _doom_page_visible(self, frame) -> bool:
        return self._title_visible(frame, DOOM_TITLE_KEYWORDS, LABEL)

    def _new_record_visible(self, frame) -> bool:
        """The red emblem (any language), or both texts on the 简中/繁中 client."""
        reference = cv2.resize(
            frame[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT), interpolation=cv2.INTER_AREA
        )
        if new_record_icon_score(reference) >= NEW_RECORD_ICON_MIN_SCORE:
            return True
        text = self._text_in(frame, NEW_RECORD_ROI, "创造新纪录")
        return (
            keyword_match_count(text, NEW_RECORD_TITLES, fuzzy_ratio=0.8) >= 1
            and keyword_match_count(text, NEW_RECORD_DAMAGE, fuzzy_ratio=0.8) >= 1
        )

    def _dismiss_new_record(self, frame) -> bool:
        """Click the 创造新纪录 screen away; False when it is not up.

        Pressed only when a second frame still shows it.
        """
        if not self._new_record_visible(frame):
            return False
        self.sleep(0.3)
        if not self._new_record_visible(self.capture_frame()):
            return False
        for _attempt in range(3):
            self.info_set("当前阶段", "关闭创造新纪录")
            self._click_reference(*NEW_RECORD_POINT, after_sleep=1.0)
            if self._wait_for(
                lambda shown: not self._new_record_visible(shown),
                timeout=NEW_RECORD_GONE_SECONDS,
                interval=0.5,
            ):
                self.log_info(f"{self.label}：已关闭「创造新纪录」画面。")
                return True
        self.log_info(f"{self.label}：「创造新纪录」画面点不掉。")
        return True

    def _back_to_field_from_page(self) -> bool:
        """After a battle the game can land on the 末日之书 page instead of the
        field (4K 桌面分身 2026-10-09, after 创造新纪录): press its back arrow."""
        for _attempt in range(3):
            self.info_set("当前阶段", "末日之书页返回地图")
            self._click_reference(*DOOM_PAGE_BACK_POINT, after_sleep=1.5)
            if self._wait_for(self._field_after_result, timeout=10.0):
                return True
            if not self._doom_page_visible(self.capture_frame()):
                return self._wait_for(self._field_after_result, timeout=PAGE_WAIT_SECONDS)
        self.log_info(f"{self.label}：末日之书页按返回后没有回到地图。")
        return False

    def _field_or_doom_page(self, frame) -> bool:
        """After 离开: the field, or the 末日之书 page (logged) for the caller's
        loop to leave with its back arrow; a new-record screen is clicked away."""
        if self._field_after_result(frame):
            return True
        if self._doom_page_visible(frame):
            self.log_info(f"{self.label}：按离开后回到末日之书页。")
            return True
        return False

    def _field_after_result(self, frame) -> bool:
        """The field is back; a new-record screen on the way is clicked away."""
        if self._field_visible(frame):
            return True
        self._dismiss_new_record(frame)
        return False

    def _wait_for(self, check, timeout: float, interval: float = 0.6) -> bool:
        # A full-length wait follows a press that loads (a cartridge, the
        # field after 离开, 主页): a load wait (Leo 2026-10-15 「你單純等載入
        # 怎麼可以改成只等10秒」).  A shorter one is a quick look.
        end_at = monotonic() + timeout
        wait = load_wait(monotonic(), timeout, before=scene_at_press(self)) if timeout >= STUCK_SECONDS else None
        while True:
            frame = self.capture_frame()
            if check(frame):
                return True
            if wait is not None:
                if wait.over(frame, monotonic(), loading=is_loading_dark(frame)):
                    return False
            elif monotonic() > end_at:
                return False
            self.sleep(interval)

    # -- steps ---------------------------------------------------------------------

    def _find_card(self) -> tuple[int, int] | None:
        """Centre of the 末日之书 card (1080 reference) on the settled page.

        The page scrolls itself to the current cartridge after opening, and
        with 查看战场奖励 on the cards carry reward icons instead of their
        names (live 2026-09-27), so the card is found by its LAST NIGHT
        cover, the same for every player.
        """

        template = image_io.read(self.card_template, cv2.IMREAD_GRAYSCALE)
        if template is None:
            return None
        previous = None
        for _read in range(4):
            frame = cv2.resize(self.capture_frame()[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT))
            grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            score, here = card_cover_match(grey, template, self.card_side_width)
            self.info_set(f"{self.label}卡带", f"{score:.2f} @ {here}")
            if score >= CARD_MIN_SCORE:
                # Same spot twice: the page has stopped scrolling.
                moved = abs(previous[0] - here[0]) + abs(previous[1] - here[1]) if previous else 99
                if moved <= 6:
                    return here
                previous = here
            else:
                previous = None
            self.sleep(0.6)
        return None

    def _enter_cartridge(self) -> bool:
        for notches in (0, 5, -10):
            if notches:
                self.scroll_client((0.5, 0.55), notches, count=1, after_sleep=1.0)
            card = self._find_card()
            if card is None or not CARD_MIN_Y <= card[1] <= REFERENCE_HEIGHT - 60:
                continue
            self.info_set("当前阶段", f"进入{self.label}卡带")
            self._click_reference(*card, after_sleep=2.0)
            # Loading the cartridge takes a few seconds.
            if self._wait_for(self._field_visible, timeout=PAGE_WAIT_SECONDS):
                return True
            self.log_info(f"{self.label}：点击卡带后未进入{self.label}地图。")
            return False
        self.log_info(f"{self.label}：游戏卡珍藏集里找不到{self.label}卡带。")
        return False

    def _move_mode(self) -> str:
        """镜中之战's 「舞台移动方式」: one setting for both tasks."""
        from src.tasks.PVPTask import STAGE_MOVE_CLICK, STAGE_MOVE_OPTIONS, PVPTask

        try:
            pvp = self.executor.get_task_by_class(PVPTask)
            mode = str(pvp.config.get("舞台移动方式", STAGE_MOVE_CLICK))
        except Exception:
            mode = STAGE_MOVE_CLICK
        return mode if mode in STAGE_MOVE_OPTIONS else STAGE_MOVE_CLICK

    def _reach_marker(self) -> bool:
        """Onto the marker the chosen way; the other way when that fails."""
        from src.tasks.PVPTask import (
            STAGE_MOVE_CLICK,
            STAGE_MOVE_WASD,
            clicks_moved_nothing,
            move_mode_note,
        )

        first = self._move_mode()
        ways = [first, STAGE_MOVE_WASD if first == STAGE_MOVE_CLICK else STAGE_MOVE_CLICK]
        # The last click left the screen as it was: clicking does nothing in
        # this game; the report then says the setting looks wrong (Leo 11-06).
        first_still = False
        for index, way in enumerate(ways):
            if index:
                first_still = first == STAGE_MOVE_CLICK and clicks_moved_nothing(self)
                self.log_info(f"{self.label}：{ways[0]}没走到战斗标记，改用{way}再试。")
            arrived = self._click_to_marker() if way == STAGE_MOVE_CLICK else self._walk_to_marker()  # 不用确认：没走到会换另一种走法
            if arrived:
                if index:
                    move_mode_note(self, way, first_still)
                return True
            if self._keys_refused or not self.look_again(
                lambda: self._field_visible(self.capture_frame())
            ):
                return False
        return False

    def _click_to_marker(self) -> bool:
        """Click-to-move: click the marker and let the character walk onto it."""
        self.info_set("当前阶段", "鼠标点击战斗标记")
        missing, clicks = 0, 0
        while clicks < CLICK_MAX_TRIES:
            frame = self.capture_frame()
            if self._doom_page_visible(frame):
                return True
            marker = None
            if self._field_visible(frame):
                marker = find_marker(
                    cv2.resize(frame[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT))
                )
            if marker is None:
                missing += 1
                if missing >= 5:
                    self.log_info(f"{self.label}：点击走位时画面中找不到红色战斗标记。")
                    return False
                self.sleep(0.5)
                continue
            missing = 0
            clicks += 1
            self.info_set("战斗标记位置", f"第{clicks}次点击 {marker}")
            self._click_reference(*marker, after_sleep=0.5)
            if self._wait_for(self._doom_page_visible, timeout=CLICK_ARRIVE_SECONDS):
                return True
        return False

    def _walk_to_marker(self) -> bool:
        """WASD onto the battle marker; the camera keeps the character centred.

        While the marker hides behind a masked HUD area its position is
        predicted from the steps walked since it was last seen.
        """
        self.info_set("当前阶段", "键盘走到战斗标记")
        missing, estimate, predicted = 0, None, 0
        for step_index in range(1, WALK_MAX_STEPS + 1):
            frame = self.capture_frame()
            if self._doom_page_visible(frame):
                return True
            if not self._field_visible(frame):
                missing += 1
                if missing >= 5:
                    self.log_info(f"{self.label}：走位途中离开了末日之书地图。")
                    return False
                self.sleep(0.6)
                continue
            marker = find_marker(cv2.resize(frame[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT)))
            if marker is not None:
                estimate, predicted, missing = marker, 0, 0
            elif estimate is not None and predicted < MAX_PREDICTED_STEPS:
                predicted += 1
            else:
                missing += 1
                if missing >= 5:
                    self.log_info(f"{self.label}：画面中找不到红色战斗标记。")
                    return False
                self.sleep(0.5)
                continue
            source = "看到" if marker is not None else "推算"
            self.info_set("战斗标记位置", f"第{step_index}步 {source} {estimate}")
            step = plan_step(estimate, MARKER_TARGET)
            if step is None:
                if marker is None:
                    # Predicted arrival only: look again before nudging.
                    estimate = None
                    continue
                break
            if not self.hold_key(step.key, step.seconds, after_sleep=0.6):
                self._keys_refused = True
                return False
            estimate = predict_after_step(estimate, step)
        for step in NUDGE_SEQUENCE:
            if self._wait_for(self._doom_page_visible, timeout=1.0):
                return True
            if not self.hold_key(step.key, step.seconds, after_sleep=0.6):
                self._keys_refused = True
                return False
        return self._wait_for(self._doom_page_visible, timeout=3.0)

    def _open_quick_bar(self, on_doom_field: bool = True) -> bool:
        """Field P icon → quick-switch bar with the battle category selected.

        ``on_doom_field`` False: standing on the other cartridge during the
        spawn reset, already proven a field by ``_wait_for_any_field`` (the
        末日之书 check could never pass there).
        """
        if on_doom_field and not self.look_again(
            lambda: self._field_visible(self.capture_frame())
        ):
            self.log_info(f"{self.label}：不在{self.label}地图上，不点卡带切换。")
            return False
        self._click_reference(*FIELD_QUICK_SWITCH_POINT, after_sleep=1.5)  # 不用确认：下面看快速切换栏，没开补点、按 P
        # A press the game dropped leaves the field up: press the icon once
        # more, then the key P (Leo 2026-10-31 「點了沒反應 … 補點」).
        remedies = [
            ("补点卡带切换图标", lambda: self._click_reference(*FIELD_QUICK_SWITCH_POINT, after_sleep=1.5)),  # 不用确认：接着看快速切换栏
            ("按 P", lambda: self.tap_key("P", after_sleep=1.5)),
        ]
        while True:
            for _attempt in range(3):
                frame = self.capture_frame()
                if self._quick_bar_shown(frame):
                    if (
                        category_highlight_ratio(frame, BATTLE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION)
                        >= GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO
                    ):
                        return True
                    self.operate_click(*BATTLE_GAMEPLAY_CATEGORY_POINT, after_sleep=1.0)
                    continue
                self.sleep(1.0)
            if not remedies or not self._wait_for_any_field(timeout=0.0):
                return False  # only on a field is another press safe
            remedy, press = remedies.pop(0)
            self.log_info(f"{self.label}：点了卡带切换没看到快速切换栏，改用{remedy}。")
            press()  # 不用确认：这就是补救

    def _quick_bar_shown(self, frame) -> bool:
        text = self._text_in(frame, QUICK_BAR_ROI, "卡带快速切换")
        return normalize_ocr_text(BATTLE_GAMEPLAY_CATEGORY_LABEL) in text

    def _press_quick_slot(self, x: int, field_seen, label: str) -> bool:
        """A cartridge slot on the quick-switch bar → that cartridge's field.

        A slot press the game dropped leaves the bar up, and the field wait
        gave up after it stood still (Leo 「其他地方也要套用」 補點): while the
        bar still shows, the slot is pressed once more."""
        outcome = press_next(
            label,
            lambda: self._click_reference(x, QUICK_SLOT_Y, after_sleep=3.0),
            [
                Next("地图", field_seen, goal=True),
                Next("加载画面", is_loading_dark, loading=True),
                Next("卡带快速切换", self._quick_bar_shown, before=True),
            ],
            capture=self.capture_frame,
            sleep=self.sleep,
            log=self.log_info,
            timeout=BACK_LOOK_SECONDS,
            retry_after=0.5,
        )
        if outcome.reached:
            return True
        if outcome.screen == "卡带快速切换":
            return False
        return self._wait_for(field_seen, timeout=PAGE_WAIT_SECONDS)

    def _playing_slot_x(self) -> int | None:
        """The slot of the cartridge in use: its ▶, else 「游戏中」, else the
        cartridge's usual slot (``quick_slot_guess``)."""
        slot = self.look_again(
            lambda: playing_mark_slot(
                cv2.resize(self.capture_frame()[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT))
            ),
            popups=False,
        )
        if slot is not None:
            return slot
        slot = self._playing_slot_by_text()
        if slot is None and self.quick_slot_guess is not None:
            slot = self.quick_slot_guess
            self.log_info(
                f"{self.label}：快速切换里认不出正在玩的卡带（▶ 和「游戏中」都没有），"
                f"改点{self.label}平常的位置（第 {QUICK_SLOT_XS.index(slot) + 1} 张）。"
            )
        return slot

    def _playing_slot_by_text(self) -> int | None:
        # The slots draw after the category bar that _open_quick_bar proved.
        boxes = self._wait_boxes(
            QUICK_SLOTS_ROI,
            "卡带格",
            lambda found: self._box_with(found, (PLAYING_TEXT,)) is not None,
            timeout=3.0,
            reference=True,
        )
        playing = self._box_with(boxes, (PLAYING_TEXT,))
        if playing is None:
            return None
        cx = playing.x + playing.width / 2
        return min(QUICK_SLOT_XS, key=lambda x: abs(x - cx))

    def _wait_for_any_field(self, timeout: float) -> bool:
        """Any cartridge field: the skill HUD labels SPACE / TAB are shown."""

        return self._wait_for(self._any_field_in, timeout=timeout)

    def _any_field_in(self, frame) -> bool:
        text = self._text_in(frame, FIELD_SKILL_HUD_ROI, "技能栏")
        return "space" in text or "tab" in text

    def _reset_to_spawn(self) -> bool:
        if not self._open_quick_bar():
            self.log_info(f"{self.label}：打不开卡带快速切换。")
            return False
        doom_x = self._playing_slot_x()
        if doom_x is None:
            self.log_info(f"{self.label}：快速切换里认不出正在玩的{self.label}卡带。")
            return False
        other_x = neighbour_slot(doom_x)
        self.info_set("当前阶段", "临时切换到其他卡带")
        if not self._press_quick_slot(
            other_x, self._any_field_in, f"{self.label}：临时切换卡带"
        ):
            self.log_info(f"{self.label}：临时卡带未载入。")
            return False
        self.sleep(1.5)
        if not self._open_quick_bar(on_doom_field=False):
            self.log_info(f"{self.label}：临时卡带上打不开卡带快速切换。")
            return False
        self.info_set("当前阶段", f"切回{self.label}")
        return self._press_quick_slot(doom_x, self._field_visible, f"{self.label}：切回卡带")

    def _fight(self) -> bool:
        self.info_set("当前阶段", "去战斗")
        button = None
        for _attempt in range(3):
            button = self._go_battle_button(self.capture_frame())
            if button is not None:
                break
            self.sleep(1.0)
        if button is None:
            self.log_info(f"{self.label}：找不到「去战斗」。")
            return False
        # 1.5 秒就重点会在战斗载入中重复点击；页面持续约 9 秒仍在才算点击被吞。
        if not self.press_and_confirm(
            f"{self.label}「去战斗」",
            lambda: self._click_reference_box(button, after_sleep=2.0),
            self._left_doom_page,
            still_before=self._go_battle_still_shown,
            timeout=GO_BATTLE_LEAVE_SECONDS,
            poll=0.5,
            retries=2,
        ):
            self.log_info(f"{self.label}：点了「去战斗」没有进入战斗。")
            return False

        self.info_set("当前阶段", "战斗中")
        end_at = monotonic() + BATTLE_TIMEOUT_SECONDS
        doom_page_reads = 0
        still = StillTimer()
        while monotonic() <= end_at:
            frame = self.capture_frame()
            if still.still_for(frame, monotonic()) >= STUCK_SECONDS:
                self.log_info(
                    f"{self.label}：战斗画面 {STUCK_SECONDS:.0f} 秒没动，没看到「离开」，当作卡住。"
                )
                return False
            # The battle already left this page, so seeing it again (two
            # reads) means the battle is over and the game came back here.
            doom_page_reads = doom_page_reads + 1 if self._doom_page_visible(frame) else 0
            if doom_page_reads >= 2:
                self.log_info(f"{self.label}：战斗结束后回到末日之书页。")
                return self._back_to_field_from_page()
            buttons = self._reference_boxes(frame, RESULT_BUTTONS_ROI, "结算按钮")
            leave = self._box_with(buttons, (LEAVE_TEXT,))
            if leave is not None:
                self.info_set("当前阶段", "离开结算")
                self._click_reference_box(leave, after_sleep=2.0)  # 不用确认：循环里结算还在就再按离开
                # Stop waiting as soon as the 末日之书 page shows instead of
                # the field; the next loop presses its back arrow.
                if self._wait_for(
                    self._field_or_doom_page, timeout=PAGE_WAIT_SECONDS
                ) and self._field_visible(
                    self.capture_frame()
                ):
                    return True
                continue
            reference = cv2.resize(frame[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT))
            if skip_ready(reference):
                text = self._text_in(frame, BATTLE_TEXT_ROI, "战斗进度")
                if keyword_match_count(text, BATTLE_KEYWORDS, fuzzy_ratio=0.8) >= 1:
                    self.info_set("当前阶段", "跳过战斗")
                    self._click_reference(*SKIP_POINT, after_sleep=1.5)
                    continue
            if self._dismiss_new_record(frame):
                continue
            self.sleep(0.8)
        self.log_info(f"{self.label}：战斗结算超时。")
        return False

    def _go_battle_button(self, frame):
        return self._box_with(
            self._reference_boxes(frame, GO_BATTLE_ROI, "去战斗"), (GO_BATTLE_TEXT,)
        )

    def _left_doom_page(self) -> bool:
        """Neither the page title nor 去战斗 on two looks in a row.

        One missed title read used to count as leaving; a swallowed click
        then ended as 「已完成一次战斗」.
        """
        for look in range(2):
            if look:
                self.sleep(0.5)
            frame = self.capture_frame()
            if (
                frame is None
                or self._doom_page_visible(frame)
                or self._go_battle_button(frame) is not None
            ):
                return False
        return True

    def _go_battle_still_shown(self) -> bool:
        """The page and its 去战斗 on two looks: the click did nothing."""
        for look in range(2):
            if look:
                self.sleep(0.5)
            frame = self.capture_frame()
            if (
                frame is None
                or not self._doom_page_visible(frame)
                or self._go_battle_button(frame) is None
            ):
                return False
        return True

    def _leave_result_after_failure(self) -> None:
        """Press 离开 if the result screen is up, then go home from the field."""

        end_at = monotonic() + RESULT_CLEANUP_SECONDS
        doom_page_reads = 0
        still = StillTimer()
        while monotonic() <= end_at:
            frame = self.capture_frame()
            if still.still_for(frame, monotonic()) >= STUCK_SECONDS:
                self.log_info(f"{self.label}：画面 {STUCK_SECONDS:.0f} 秒没动，不再等结算，交给回主页。")
                return
            if self._field_visible(frame):
                self._field_to_home()
                return
            buttons = self._reference_boxes(frame, RESULT_BUTTONS_ROI, "结算按钮")
            leave = self._box_with(buttons, (LEAVE_TEXT,))
            if leave is not None:
                self._click_reference_box(leave, after_sleep=2.0)  # 不用确认：循环里结算还在就再按离开
                if self._wait_for(
                    self._field_or_doom_page, timeout=PAGE_WAIT_SECONDS
                ) and self._field_visible(
                    self.capture_frame()
                ):
                    self._field_to_home()
                    return
                # On the 末日之书 page: the two-read check below leaves it.
                continue
            if self._dismiss_new_record(frame):
                continue
            # On the 末日之书 page (two reads): 去战斗 never took, or the
            # battle ended back here.  No battle to wait out; leave the page.
            doom_page_reads = doom_page_reads + 1 if self._doom_page_visible(frame) else 0
            if doom_page_reads >= 2:
                if self._back_to_field_from_page():
                    self._field_to_home()
                return
            self.sleep(1.0)

    def _field_to_home(self) -> bool:
        self._dismiss_new_record(self.capture_frame())
        for _attempt in range(3):
            self.info_set("当前阶段", "返回主页")
            self._click_reference(*FIELD_HOME_POINT, after_sleep=1.5)
            if self._wait_for_home_confirmation(f"{self.label}返回主页", timeout=PAGE_WAIT_SECONDS):
                return True
            if not self._field_visible(self.capture_frame()):
                break
        if self._wait_for_home_confirmation(f"{self.label}返回主页", timeout=10.0):
            return True
        return self.home_by_key(
            lambda seconds: self._wait_for_home_confirmation(f"{self.label}返回主页", timeout=seconds),
            f"{self.label}返回主页",
        )


class DoomBookTask(CartridgeFieldTask):
    claim_log_name = "doom_book"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "末日之书"
        self.description = (
            "主页卡带 → 末日之书 → 走到红色交叉剑标记 → 去战斗 → 跳过 → 离开 → 回主页"
            "（每周任务：参与末日之书）。战斗不消耗资源。走法跟镜中之战的「舞台移动方式」一样。"
        )
        self.icon = FluentIcon.FLAG

    # -- entry --------------------------------------------------------------------

    def run_claim(self) -> bool:
        if not self._open_page_from_home(
            "游戏卡珍藏集", CARTRIDGE_SLOT_POINT, COLLECTION_TITLE_KEYWORDS
        ):
            return self._claim_fail("打开游戏卡珍藏集")
        if not self._enter_cartridge():
            return self._claim_fail("进入末日之书")
        self.dismiss_field_followers()
        self._keys_refused = False
        if not self._reach_marker():
            if self._keys_refused:
                # Switching cartridges cannot help while another window has
                # the keyboard; leave the field for the next run.
                self._field_to_home()
                return self._claim_fail("键盘走位（游戏窗口不在最前面）")
            # The field keeps the last position when re-entered from home;
            # switching to another cartridge and back resets it to the spawn
            # (user, 2026-09-26).
            self.log_info(f"{self.label}：切换卡带后回到出生点重试。")
            if not (self._reset_to_spawn() and self._reach_marker()):
                self._save_flow_diagnostic("doom_book_walk_failed")
                return self._claim_fail("走到战斗标记")
        if not self._fight():
            # Recovery cannot press 离开 on the result screen; do it here.
            self._leave_result_after_failure()
            return self._claim_fail("战斗")
        if not self._field_to_home():
            return self._claim_fail("返回主页")
        self.log_info(f"{self.label}：已完成一次战斗。")
        return True
