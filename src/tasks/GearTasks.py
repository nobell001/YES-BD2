"""Equipment chores: one daily refine (for the 装备精炼 mission).

Calibrated on the 简体 client, 2026-09-26 (1920x1080 reference) from the
user's demonstration: bag → equipment tab → an item whose refine badge shows
a number below 24 → 精炼 in its detail popup → the 精炼装备分数 page →
精炼 once.  The page also has 连续精炼 (continuous refine), which is never
pressed: only a box whose text is exactly 精炼 (plus its cost) is clicked.
Items without a number badge cannot be refined and are never chosen.
"""

from __future__ import annotations

import re
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np
from qfluentwidgets import FluentIcon

from src.tasks.claim_page import BACK_BUTTON_POINT
from src.tasks.enhance_dialog import crop_reference, yellow_ratio
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils import image_io
from src.utils.image_utils import template_match_response
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text
from src.utils.press_confirm import SLOW_PC_GRACE_SECONDS

BAG_ENTRY_POINT = (369, 985)
# The equipment page's 查看详情 switch: live 4K off 0.00, on 0.41 yellow.
BAG_DETAIL_SWITCH_BOX = (812, 30, 46, 26)
BAG_DETAIL_SWITCH_POINT = (835, 42)
BAG_DETAIL_SWITCH_MIN_RATIO = 0.15
BAG_TITLE_KEYWORDS = ("装备", "消耗品")
EQUIPMENT_TAB_POINT = (174, 249)
EQUIPMENT_TAB_ATTEMPTS = 3
EQUIPMENT_TITLE_KEYWORDS = ("装备",)

# Item grid: 8 columns x 6 fully visible rows; the refine badge number sits
# right of and below each cell centre.
GRID_ROI = (720, 145, 1000, 830)
GRID_COLUMNS = (778, 904, 1030, 1156, 1282, 1408, 1534, 1660)
GRID_ROWS = (207, 333, 459, 585, 711, 837)
BADGE_OFFSET_X = (20, 56)
BADGE_OFFSET_Y = (0, 30)
MAX_REFINE = 24
REFINE_PREFERRED_VALUES = (18, 19, 20)
# The 18-20 badge star (HSV, OpenCV scale); a cell counts at this share.
PURPLE_STAR_LOW = (130, 70, 110)
PURPLE_STAR_HIGH = (158, 255, 255)
PURPLE_STAR_SHARE = 0.08
# The refine page's single 精炼 pill starts with a yellow lightning icon (Leo
# 2026-10-11 「第二張圖也可以認雷電圖案」); 连续精炼 has a white gear.  Used only
# to find the button when its text is not read; the press keeps its checks.
REFINE_LIGHTNING_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "recognition-assets" / "template-assets" / "gear" / "refine_lightning_yellow.png"
)
REFINE_LIGHTNING_SCORE = 0.75
REFINE_LIGHTNING_YELLOW_LOW = (12, 110, 140)
REFINE_LIGHTNING_YELLOW_HIGH = (40, 255, 255)

# Where the item popup's buttons are looked for: the whole popup, above the
# bag's own bottom row (一键强化 at y 1045).  The popup grows with its stat
# lines: on Leo's frames the buttons sit at y 717-752, on a player's (v0.1.19,
# 1080p, 2026-10-11, 基本能力 + three 属性 lines) at 762-796, below the old
# (1150, 700, 320, 70), which read nothing three times.  Leo: 「只要辨別到
# 精煉就可了吧」 - 精炼 is pressed wherever it is read (no other text in the
# popup is exactly 精炼; 7 frames checked).
DETAIL_BUTTONS_ROI = (450, 280, 1150, 620)
CONTINUOUS_REFINE_TEXT = "连续精炼"
REFINE_PAGE_TITLE = ("精炼装备分数",)
REFINE_BUTTONS_ROI = (1150, 965, 660, 80)
BACK_TO_BAG_ATTEMPTS = 3
MISSION_TOAST_ROI = (400, 0, 1300, 90)
# Bottom-left 精炼痕迹 counter ("精炼痕迹8,943").  Leo 2026-10-05: it only
# moves after a number of refines, so it is logged, never used as proof.
REFINE_TRACE_ROI = (0, 965, 1150, 80)
REFINE_TRACE_TEXT = "精炼痕迹"
REFINE_TOAST_KEYWORDS = ("精炼成功", "完成")
# Counts in the top bar (MISSION_TOAST_ROI): material, then gold, e.g. "430,922 116".
# A refine lowers one ("430,904", with a floating "-30" for a moment; live 4K
# 2026-10-05).  A number right after "-" is that floating cost, not a count.
TOP_COUNT_PATTERN = re.compile(r"(?<![\d,，.\-－−])\d[\d,，.]*")
# A refine is confirmed within this long, or the page counts as unchanged.
REFINE_RESULT_SECONDS = 5.0
# The whole page, for "nothing happened" (frame diff only, no OCR).
REFINE_PAGE_ROI = (0, 110, 1920, 970)


def badge_cells(boxes: list) -> list[tuple[int, int, int]]:
    """Return (row, column, value) for every refine badge read in the grid.

    ``boxes`` must be in 1920x1080 reference coordinates.

    Only one- or two-digit numbers in the badge position count; the small
    stat icons at the bottom of each cell also OCR as digits and are ignored.
    A badge read as two boxes ("2" and "4", live 4K 2026-10-05) is joined
    left to right.
    """
    parts: dict[tuple[int, int], list[tuple[float, str]]] = {}
    for box in boxes:
        text = str(getattr(box, "name", "")).strip()
        if not re.fullmatch(r"\d{1,2}", text):
            continue
        x = float(box.x) + float(box.width) / 2
        y = float(box.y) + float(box.height) / 2
        for row, cy in enumerate(GRID_ROWS):
            for column, cx in enumerate(GRID_COLUMNS):
                dx, dy = x - cx, y - cy
                if (
                    BADGE_OFFSET_X[0] <= dx <= BADGE_OFFSET_X[1]
                    and BADGE_OFFSET_Y[0] <= dy <= BADGE_OFFSET_Y[1]
                ):
                    parts.setdefault((row, column), []).append((x, text))
    cells = []
    for (row, column), pieces in parts.items():
        text = "".join(piece for _x, piece in sorted(pieces))
        if re.fullmatch(r"\d{1,2}", text):
            cells.append((row, column, int(text)))
    return sorted(cells)


def refine_candidate(
    cells: list[tuple[int, int, int]], purple: set[tuple[int, int]] | None = None
) -> tuple[int, int, int] | None:
    """First cell (row-major) whose refine value is a real number below 24.

    Leo 2026-10-05: pick one below 24 on the first try.  Leo 2026-10-11:
    「可以請程式先優先抓 18 19 20這三個」 - a number in the bottom-right badge
    means fully enhanced (refinable); blank or 「+N」 means not.  So 18-20
    come first, then other two-digit reads (10-23); a lone digit is often a
    cut-off 2x ("22" read as "2", "24" as "4") or a 「+N」 read without its
    plus, so single digits come only when none is left.  A purple star
    (``purple``, see ``purple_badges``) puts an 18-20 read first, and makes a
    cut-off read (「8」 of 18) count before other numbers.
    """
    purple = purple or set()
    tiers = (
        lambda cell: cell[2] in REFINE_PREFERRED_VALUES and cell[:2] in purple,
        lambda cell: cell[2] in REFINE_PREFERRED_VALUES,
        lambda cell: 1 <= cell[2] < MAX_REFINE and cell[:2] in purple,
        lambda cell: 10 <= cell[2] < MAX_REFINE,
        lambda cell: 1 <= cell[2] < 10,
    )
    for wanted in tiers:
        for cell in cells:
            if wanted(cell):
                return cell
    return None


def refine_pill_point(frame) -> tuple[int, int] | None:
    """1080 reference centre of the popup's right-hand pill (精炼), found as a
    light band in its column; None when no such band shows."""
    if frame is None or getattr(frame, "ndim", 0) != 3:
        return None
    small = cv2.resize(frame, (REFERENCE_WIDTH, REFERENCE_HEIGHT), interpolation=cv2.INTER_AREA)
    top, bottom = REFINE_PILL_ROWS
    left, right = REFINE_PILL_COLUMN
    hsv = cv2.cvtColor(small[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    light = ((hsv[..., 2] >= 190) & (hsv[..., 1] <= 45)).mean(axis=1) > REFINE_PILL_LIGHT_SHARE
    runs, start = [], None
    for row, on in enumerate([*light, False]):
        if on and start is None:
            start = row
        elif not on and start is not None:
            runs.append((start, row))
            start = None
    low, high = REFINE_PILL_HEIGHT
    bands = [(a, b) for a, b in runs if low <= b - a <= high]
    if len(bands) != 1:
        return None
    a, b = bands[0]
    return ((left + right) // 2, top + (a + b) // 2)


_LIGHTNING = None


def refine_lightning_point(frame) -> tuple[float, float] | None:
    """Client centre of the single 精炼 pill's lightning icon, when one shows."""
    global _LIGHTNING
    if _LIGHTNING is None:
        _LIGHTNING = image_io.read(REFINE_LIGHTNING_TEMPLATE, cv2.IMREAD_GRAYSCALE)
    if _LIGHTNING is None or frame is None or getattr(frame, "ndim", 0) != 3:
        return None
    height, width = frame.shape[:2]
    sx, sy = width / REFERENCE_WIDTH, height / REFERENCE_HEIGHT
    x, y, w, h = REFINE_BUTTONS_ROI
    crop = crop_reference(frame, REFINE_BUTTONS_ROI)
    if crop.size == 0:
        return None
    crop = cv2.resize(crop, (w, h), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, REFINE_LIGHTNING_YELLOW_LOW, REFINE_LIGHTNING_YELLOW_HIGH)
    th, tw = _LIGHTNING.shape[:2]
    if mask.shape[0] < th or mask.shape[1] < tw:
        return None
    scores = template_match_response(mask, _LIGHTNING)
    _low, best, _at, (bx, by) = cv2.minMaxLoc(scores)
    if best < REFINE_LIGHTNING_SCORE:
        return None
    scores[max(0, by - th) : by + th, max(0, bx - tw) : bx + tw] = -1.0
    if cv2.minMaxLoc(scores)[1] >= REFINE_LIGHTNING_SCORE:
        return None  # two of them: not the page we know
    return ((x + bx + tw / 2) * sx, (y + by + th / 2) * sy)


def purple_badges(frame) -> set[tuple[int, int]]:
    """Cells whose refine badge is the purple star of 18-20.

    Leo 2026-10-11: 「18 19 20 底都是紫色」「數字加上優先認紫色」.  Measured on
    his 4K bag (2026-10-11): the star's arms are about 0.2-0.35 purple on
    every 18/19/20 and 0.00 on 9, 12, 21, 22, 24 and on blank cells; the
    digits in the middle are left out.
    """
    if frame is None or getattr(frame, "ndim", 0) != 3:
        return set()
    small = cv2.resize(frame, (REFERENCE_WIDTH, REFERENCE_HEIGHT), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, PURPLE_STAR_LOW, PURPLE_STAR_HIGH) > 0
    found = set()
    for row, cy in enumerate(GRID_ROWS):
        for column, cx in enumerate(GRID_COLUMNS):
            arms = np.concatenate([
                mask[cy + 10 : cy + 19, cx + 18 : cx + 26].ravel(),
                mask[cy + 10 : cy + 19, cx + 44 : cx + 52].ravel(),
            ])
            if arms.size and arms.mean() >= PURPLE_STAR_SHARE:
                found.add((row, column))
    return found


# 精炼 followed only by its cost ("精炼80", "精炼●80"): rejects 连续精炼 and
# other labels that merely start with 精炼, such as 精炼痕迹.
# The refine page's bottom bar when the item is already at the cap.
MAXED_TEXT = "达到最大强化级别"
REFINE_CANDIDATE_ATTEMPTS = 3
# Items whose popup has no 精炼 (on Leo's PC: not yet fully enhanced, only
# 穿戴/强化) are opened and closed again, which costs nothing, so they do not
# use up the tries above; this many are looked at at most (YES-BD2 #12,
# 2026-10-10: it stopped on such an item).
REFINE_NO_BUTTON_PROBES = 10
# 强化 in the popup: the item is not fully enhanced and has no 精炼.
NOT_REFINABLE_TEXT = "强化"
# Last resort when the popup's buttons read as something else (YES-BD2 #12,
# 2K: 「兴」): the right-hand pill, where 精炼 sits (Leo's 4K and 1080p frames,
# 2026-10-10/11).  It only opens the 精炼装备分数 page, which must then show;
# 精炼 on that page keeps all its checks.
REFINE_BUTTON_USUAL_POINT = (1362, 734)
# The right pill itself: a light band this many rows high in this column
# (both heights above measured 33-36 rows; no band when no popup is open).
REFINE_PILL_COLUMN = (1330, 1395)
REFINE_PILL_ROWS = (600, 900)
REFINE_PILL_HEIGHT = (24, 48)
REFINE_PILL_LIGHT_SHARE = 0.45  # the dark 精炼 letters take up to half a row
SINGLE_REFINE_PATTERN = re.compile(r"^精炼[^一-鿿]*$")
# Text only the item popup shows (tall_popup_player_1080.jpg).  The popup read
# box (DETAIL_BUTTONS_ROI) lies over the bag grid, so with none of these read
# the popup did not open and the read is the bare grid: YES-BD2 #26 (v0.1.32,
# 1080p windowed at 125%) read 「JR 20 22 兴 IR UR 20 ...」, the grid's UR tags
# and badge numbers, and then pressed the usual 精炼 spot, which on the bare
# grid is another item (row 5, column 6).
POPUP_KEYWORDS = ("精炼", "强化", "穿戴", "卸除", "基本能力", "属性", "自定义标记")
# A cell press whose popup does not show is pressed once more (Leo
# 2026-10-13 「按東西沒反應一定要補按吧」); opening an item costs nothing.
CELL_PRESS_ATTEMPTS = 2
# Items whose popup would not open at all before 每日精炼 gives up (Leo
# 2026-10-14 「最多試3件 各點2次」).
REFINE_NO_POPUP_PROBES = 3
# Where an open popup covers the grid (1080 px; the popup spans x 470-1450,
# y 280-830), left of the character art that moves on its own.  A second
# cell press is made only while this part still looks as before the first:
# otherwise something opened that was not read, and a press there could land
# on its 强化 (开源前检查's review of #280, 2026-10-14).
POPUP_COVER_BOX = (720, 280, 730, 550)
POPUP_COVER_PIXEL_DIFF = 30
POPUP_COVER_SHARE = 0.25
# A 精炼 box this close after a 连续 box is part of 连续精炼 (1080 px).
REFINE_SPLIT_GAP = 60
REFINE_ROW_TOLERANCE = 30


def grid_covered(before, after) -> bool:
    """True when the grid part an open popup would cover changed a lot
    between the two frames (a popup or another page, not a glint)."""
    if before is None or after is None:
        return False
    first = crop_reference(before, POPUP_COVER_BOX)
    second = crop_reference(after, POPUP_COVER_BOX)
    if first is None or second is None or first.size == 0 or first.shape != second.shape:
        return False
    first = cv2.cvtColor(np.ascontiguousarray(first[..., :3]), cv2.COLOR_BGR2GRAY)
    second = cv2.cvtColor(np.ascontiguousarray(second[..., :3]), cv2.COLOR_BGR2GRAY)
    return float((cv2.absdiff(first, second) > POPUP_COVER_PIXEL_DIFF).mean()) >= POPUP_COVER_SHARE


def popup_shown(boxes: list) -> bool:
    """True when the read shows the item popup, not just the bag grid."""
    text = normalize_ocr_text(" ".join(str(getattr(box, "name", "")) for box in boxes))
    return any(keyword in text for keyword in POPUP_KEYWORDS)


def plain_refine_box(boxes: list):
    """The single-refine button; never 连续精炼 or 精炼痕迹.

    OCR can split 连续精炼 into 连续 + 精炼, so a 精炼 box is only accepted
    when it lies to the right of every 连续 box on its row (live refine page:
    连续精炼 at x 1298, 精炼 at x 1610).
    """

    continuous = [
        box for box in boxes if "连续" in normalize_ocr_text(getattr(box, "name", ""))
    ]
    for box in boxes:
        text = normalize_ocr_text(getattr(box, "name", ""))
        if CONTINUOUS_REFINE_TEXT in text or not SINGLE_REFINE_PATTERN.match(text):
            continue
        left = float(getattr(box, "x", 0))
        middle = float(getattr(box, "y", 0)) + float(getattr(box, "height", 0)) / 2
        if any(
            abs(float(getattr(other, "y", 0)) + float(getattr(other, "height", 0)) / 2 - middle)
            <= REFINE_ROW_TOLERANCE
            and left < float(getattr(other, "x", 0)) + float(getattr(other, "width", 0))
            + REFINE_SPLIT_GAP
            for other in continuous
        ):
            continue
        return box
    return None


class DailyRefineTask(_ClaimTaskBase):
    claim_log_name = "refine"
    # Refining, crafting and dismantling (the subclasses) are not run twice.
    frozen_retry = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "每日精炼一次"
        self.description = (
            "背包装备中挑一件精炼值低于24的装备精炼一次（活动任务：装备精炼）。"
            "只点「精炼」，绝不点「连续精炼」。"
        )
        self.icon = FluentIcon.SYNC

    def run_claim(self) -> bool:
        self._why = ""
        if not self._open_equipment_bag():
            return self._claim_fail("打开背包装备页")
        self._grid_frame = None
        cells = self._wait_for_grid_cells()
        purple = purple_badges(self._grid_frame)
        self.info_set("精炼值", " ".join(f"{r},{c}={v}" for r, c, v in cells) or "-")
        tried: set[tuple[int, int]] = set()
        outcome = "none"
        maxed = no_button = no_popup = 0
        while (
            maxed < REFINE_CANDIDATE_ATTEMPTS
            and no_button < REFINE_NO_BUTTON_PROBES
            and no_popup < REFINE_NO_POPUP_PROBES
        ):
            candidate = refine_candidate(
                [cell for cell in cells if cell[:2] not in tried], purple
            )
            if candidate is None:
                break
            row, column, value = candidate
            tried.add((row, column))
            self.info_set("精炼目标", f"第{row + 1}行第{column + 1}列，精炼值 {value}")
            outcome = self._refine_cell(row, column)
            if outcome == "no_popup":
                # Nothing opened, still in the bag (YES-BD2 #26): try the next.
                no_popup += 1
                continue
            if outcome == "no_button":
                # This item has no 精炼 (a player's 2560×1440 run, 2026-10-10,
                # stopped on the first one): its popup is closed, try the next.
                no_button += 1
                self.log_info(f"每日精炼：第{row + 1}行第{column + 1}列不能精炼，换下一件。")
                continue
            if outcome != "maxed":
                break
            maxed += 1
            # OCR can drop a digit ("24" read as "4", live 2026-09-27): the
            # item is already at the cap, so go back and try the next one.
            self.log_info(f"每日精炼：第{row + 1}行第{column + 1}列已达最大精炼，换下一件。")
        if outcome == "none":
            self.log_info("每日精炼：首屏没有可精炼的装备，跳过。")
        if outcome == "no_popup":
            outcome = "failed"
            if no_popup > 1:
                self._why = f"点了 {no_popup} 件装备，装备详情都没打开（{self._why}）"
        if outcome == "no_button":
            outcome = "failed"
            if no_button > 1:
                self._why = (
                    f"试了 {no_button} 件，装备详情里都没有精炼按钮"
                    f"（可能还没强化满；最后一件：{self._why}）"
                )
        if outcome == "maxed" and not self._why:
            self._why = "试了几件都已达最大精炼"
        self._restore_bag_detail_view()
        home = self._leave_to_home("背包", EQUIPMENT_TITLE_KEYWORDS)
        if outcome in ("maxed", "failed"):
            return self._refine_fail("精炼")
        if outcome == "unconfirmed":
            return self._refine_fail("确认精炼结果")
        if not home:
            return self._claim_fail("背包返回主页")
        return True

    def _refine_fail(self, stage: str) -> bool:
        """The failure with its reason, written after the bag was left.

        Leaving set 当前阶段 to 「背包：返回主页」, which the 问题摘要 showed as
        where it stopped, though the bag had been left fine (a player's
        summary, 2026-10-10).
        """
        return self._claim_fail(stage)

    def _wait_for_grid_cells(self, timeout: float = 3.0 + SLOW_PC_GRACE_SECONDS) -> list:
        """Refine badges of the first screen; empty only after ``timeout``.

        A single read right after the bag opened could come before the
        badges drew and silently skipped the daily refine.  Badges that are
        read end the wait at once.
        """
        end_at = monotonic() + timeout
        while True:
            frame = self.capture_frame()
            cells = badge_cells(self._grid_boxes(frame))
            if cells or monotonic() >= end_at:
                self._grid_frame = frame
                return cells
            self.sleep(0.5)

    def _grid_boxes(self, frame) -> list:
        """Grid OCR boxes converted to 1920x1080 reference coordinates."""
        height, width = frame.shape[:2]
        scale_x = REFERENCE_WIDTH / max(1, width)
        scale_y = REFERENCE_HEIGHT / max(1, height)
        return [
            SimpleNamespace(
                name=getattr(box, "name", ""),
                x=float(box.x) * scale_x,
                y=float(box.y) * scale_y,
                width=float(box.width) * scale_x,
                height=float(box.height) * scale_y,
            )
            for box in self._roi_boxes(frame, GRID_ROI, "装备格子")
            if getattr(box, "x", None) is not None
        ]

    def _open_equipment_bag(self, *, grid_view: bool = True) -> bool:
        """Open the bag's equipment page; ``grid_view`` also turns 查看详情 off."""

        self._bag_detail_view_restore = False
        if not self._open_page_from_home("背包", BAG_ENTRY_POINT, BAG_TITLE_KEYWORDS):
            return False
        # The bag reopens on the last tab.  A tab click sent while the bag is
        # still opening can be dropped (live 2026-09-27: it stayed on 消耗品
        # for 15 s), so it is repeated until the 装备 title shows.
        for _attempt in range(EQUIPMENT_TAB_ATTEMPTS):
            if self._title_visible(self.capture_frame(), EQUIPMENT_TITLE_KEYWORDS, "装备"):
                break
            self._click_reference(*EQUIPMENT_TAB_POINT, after_sleep=1.0)
            if self._wait_for_title("装备", EQUIPMENT_TITLE_KEYWORDS, timeout=3.0, quiet=True):
                break
        else:
            if not self._wait_for_title("装备", EQUIPMENT_TITLE_KEYWORDS, timeout=2.0):
                return False
        return self._bag_grid_view() if grid_view else True

    def _bag_detail_view_on(self, looks: int = 2) -> bool:
        # ON in any of a few looks counts: a switch not drawn yet reads OFF,
        # and OFF by mistake puts every grid cell in the wrong place.
        for look in range(looks):
            if look:
                self.sleep(0.4)
            ratio = yellow_ratio(crop_reference(self.capture_frame(), BAG_DETAIL_SWITCH_BOX))
            self.info_set("背包查看详情", f"黄色占比 {ratio:.2f}")
            if ratio >= BAG_DETAIL_SWITCH_MIN_RATIO:
                return True
        return False

    def _bag_grid_view(self) -> bool:
        """The grid offsets need 查看详情 off; a player's ON is restored later.

        With it on the bag shows 7 tall detail cards instead of the 8-column
        grid (live 2026-09-27), and every cell offset would be wrong.
        """

        if not self._bag_detail_view_on():
            return True
        for _attempt in range(2):
            self._click_reference(*BAG_DETAIL_SWITCH_POINT, after_sleep=1.5)
            # One look after the switch animation: a second ON look while it
            # fades would click it back on.
            if not self._bag_detail_view_on(looks=1):
                self._bag_detail_view_restore = True
                return True
        self.log_warning("背包：无法关闭「查看详情」，不处理装备。")
        return False

    def _restore_bag_detail_view(self) -> None:
        if getattr(self, "_bag_detail_view_restore", False) and not self._bag_detail_view_on():
            self._click_reference(*BAG_DETAIL_SWITCH_POINT, after_sleep=1.0)
        self._bag_detail_view_restore = False

    def _back_to_bag(self, outcome: str) -> str:
        for attempt in range(1, BACK_TO_BAG_ATTEMPTS + 1):
            self._click_reference(*BACK_BUTTON_POINT, after_sleep=1.5)
            if self._wait_for_title("装备", EQUIPMENT_TITLE_KEYWORDS, timeout=3.0, quiet=True):
                return outcome
            # A press during the refine animation is swallowed and the page
            # has no title to notice it (live 2K 2026-09-29: 15 s wait, then
            # the batch failed).  Press again only while still on the page.
            buttons = self._boxes_text(
                self._roi_boxes(self.capture_frame(), REFINE_BUTTONS_ROI, "精炼按钮")
            )
            if "精炼" not in normalize_ocr_text(buttons):
                break
            self.log_info(f"每日精炼：第{attempt}次返回背包未生效，重试。")
        if not self._wait_for_title("装备", EQUIPMENT_TITLE_KEYWORDS):
            # What went wrong on the page first, if anything, is the cause.
            self._why = getattr(self, "_why", "") or "从精炼页回不到背包"
            return "failed"
        return outcome

    def _close_item_popup(self, detail: list) -> bool:
        """One back press closes the item popup and stays in the bag (the
        player's log: after it, the bag still showed and a second press went
        home).  True only when the bag shows and the popup's buttons are gone."""
        self._click_reference(*BACK_BUTTON_POINT, after_sleep=1.0)  # 不用确认：下面读回背包
        if not self._wait_for_title("装备", EQUIPMENT_TITLE_KEYWORDS, timeout=3.0, quiet=True):
            return False
        before = self._boxes_text(detail)
        frame = self.capture_frame()
        after = self._boxes_text(self._roi_boxes(frame, DETAIL_BUTTONS_ROI, "装备详情按钮"))
        return not before or after != before

    def _refine_cell(self, row: int, column: int) -> str:
        """refined / maxed (already at the cap, back in the bag) / no_button
        (its popup closed, still in the bag) / no_popup (it never opened,
        still in the bag) / unconfirmed / failed."""
        state, detail = self._open_item_popup(row, column)
        if state == "none":
            return "no_popup"
        if state == "unread":
            # Left to the way home: its back press closes whatever opened.
            return "failed"
        button = plain_refine_box(detail)
        seen = self._boxes_text(detail) or "没读到字"
        if button is None and NOT_REFINABLE_TEXT not in normalize_ocr_text(seen):
            return self._refine_at_usual_spot(row, column, seen)
        if button is None:
            # A player's summary (2026-10-10) had only this line and the bag it
            # went back to: what the popup showed is kept for the 问题摘要.
            self.log_info(
                f"每日精炼：第{row + 1}行第{column + 1}列的装备详情里没有精炼按钮，"
                f"按钮处读到「{seen}」。"
            )
            self._why = (
                f"第{row + 1}行第{column + 1}列的装备详情里没有精炼按钮（按钮处读到「{seen}」）"
            )
            self._save_flow_diagnostic("daily_refine_no_refine_button")
            return "no_button" if self._close_item_popup(detail) else "failed"
        self._click_box(button, after_sleep=1.5)  # 不用确认：没进精炼页、详情还在会再按一次
        if not self._wait_for_title("精炼", REFINE_PAGE_TITLE):
            # 精炼 here only opens the refine page (nothing is spent yet): a
            # press the game dropped leaves the detail up, press it once more.
            again = plain_refine_box(
                self._wait_boxes(
                    DETAIL_BUTTONS_ROI,
                    "装备详情按钮",
                    lambda boxes: plain_refine_box(boxes) is not None,
                )
            )
            if again is None:
                self._why = "点了精炼后，精炼页没出来"
                return "failed"
            self.log_info("每日精炼：点了精炼还在装备详情，再按一次。")
            self._click_box(again, after_sleep=1.5)  # 不用确认：只补这一次
            if not self._wait_for_title("精炼", REFINE_PAGE_TITLE):
                self._why = "点了两次精炼，精炼页都没出来"
                return "failed"
        return self._refine_on_page()

    def _open_item_popup(self, row: int, column: int) -> tuple[str, list]:
        """Press the cell until its popup shows (twice at most).

        ("open", the popup's read) / ("none", ...) when only the bag grid
        shows (nothing to close) / ("unread", ...) when the screen changed
        after the press but no popup was read: never pressed again there."""
        self._sleep_after_recognition()
        detail: list = []
        before = self.capture_frame()
        for attempt in range(CELL_PRESS_ATTEMPTS):
            if attempt:
                if grid_covered(before, self.capture_frame()):
                    self.log_info(
                        f"每日精炼：点了第{row + 1}行第{column + 1}列后画面变了，"
                        "但认不出装备详情，不再补按。"
                    )
                    self._why = (
                        f"点了第{row + 1}行第{column + 1}列的装备后画面变了，但认不出装备详情"
                    )
                    self._save_flow_diagnostic("daily_refine_popup_unread")
                    return "unread", detail
                self.log_info(
                    f"每日精炼：点了第{row + 1}行第{column + 1}列，装备详情没打开，补按一次。"
                )
            self._click_reference(GRID_COLUMNS[column], GRID_ROWS[row], after_sleep=1.0)
            detail = self._wait_boxes(
                DETAIL_BUTTONS_ROI,
                "装备详情按钮",
                lambda boxes: plain_refine_box(boxes) is not None
                or NOT_REFINABLE_TEXT in normalize_ocr_text(self._boxes_text(boxes)),
            )
            # A popup whose text read as nothing still shows its light 精炼 pill.
            if popup_shown(detail) or refine_pill_point(self.capture_frame()) is not None:
                return "open", detail
        seen = self._boxes_text(detail) or "没读到字"
        self.log_info(
            f"每日精炼：点了第{row + 1}行第{column + 1}列{CELL_PRESS_ATTEMPTS}次，"
            f"装备详情都没打开（只看到背包格子：「{seen}」）。"
        )
        self._why = (
            f"点了第{row + 1}行第{column + 1}列的装备{CELL_PRESS_ATTEMPTS}次，装备详情都没打开"
        )
        self._save_flow_diagnostic("daily_refine_popup_not_opened")
        return "none", detail

    def _refine_at_usual_spot(self, row: int, column: int, seen: str) -> str:
        """Press where 精炼 usually sits, once; the refine page must follow."""
        self.log_info(
            f"每日精炼：第{row + 1}行第{column + 1}列的装备详情按钮读到「{seen}」，"
            "照精炼平常的位置点一下。"
        )
        self._save_flow_diagnostic("daily_refine_button_unread")
        point = refine_pill_point(self.capture_frame()) or REFINE_BUTTON_USUAL_POINT
        opened = self.press_and_confirm(
            "每日精炼：照平常位置点精炼",
            lambda: self._click_reference(*point, after_sleep=1.0),
            lambda: self._title_visible(self.capture_frame(), REFINE_PAGE_TITLE, "精炼"),
            timeout=REFINE_RESULT_SECONDS,
            poll=0.5,
        )
        if opened:
            return self._refine_on_page()
        self._why = (
            f"第{row + 1}行第{column + 1}列的装备详情里没认出精炼按钮（按钮处读到「{seen}」），"
            "照平常位置点了也没进精炼页"
        )
        return "failed"

    def _refine_on_page(self) -> str:
        """On the 精炼装备分数 page: refine once with all checks, back to the bag."""
        buttons = self._wait_boxes(
            REFINE_BUTTONS_ROI,
            "精炼按钮",
            lambda boxes: plain_refine_box(boxes) is not None
            or MAXED_TEXT in normalize_ocr_text(self._boxes_text(boxes)),
        )
        refine = plain_refine_box(buttons)
        button_text = self._boxes_text(buttons)
        self.info_set("精炼按钮 OCR", button_text or "-")
        if refine is None and MAXED_TEXT not in normalize_ocr_text(button_text):
            refine = self._lightning_refine_box()
        if refine is None:
            if MAXED_TEXT in normalize_ocr_text(button_text):
                return self._back_to_bag("maxed")
            self.log_info("每日精炼：精炼页找不到单次精炼按钮。")
            self._why = f"精炼页找不到单次精炼按钮（读到「{button_text or '没读到字'}」）"
            return self._back_to_bag("failed")
        return self._back_to_bag(self._press_refine_once(refine))

    def _lightning_refine_box(self):
        """The 精炼 pill found by its lightning icon (its text was not read)."""
        point = refine_lightning_point(self.capture_frame())
        if point is None:
            return None
        self.log_info("每日精炼：没读到「精炼」的字，按雷电图示认出单次精炼按钮。")
        return SimpleNamespace(name="精炼", x=point[0] - 1, y=point[1] - 1, width=2, height=2)

    def _refine_trace(self, frame) -> int | None:
        text = normalize_ocr_text(
            self._boxes_text(self._roi_boxes(frame, REFINE_TRACE_ROI, "精炼痕迹"))
        )
        match = re.search(REFINE_TRACE_TEXT + r"([\d,，.]+)", text)
        digits = re.sub(r"\D", "", match.group(1)) if match else ""
        return int(digits) if digits else None

    @staticmethod
    def _top_counts(text: str) -> tuple[int, ...]:
        return tuple(
            int(re.sub(r"\D", "", number)) for number in TOP_COUNT_PATTERN.findall(text or "")
        )

    @staticmethod
    def _counts_spent(before: tuple[int, ...], after: tuple[int, ...]) -> bool:
        """The material count (first number) went down.  The gold after it
        is cut by the ROI ("116" of 116,857,671), so it is not compared."""
        return bool(before) and bool(after) and after[0] < before[0]

    def _refine_signals(
        self, frame, trace_before, toast_before: str
    ) -> tuple[bool, tuple[int, ...]]:
        """(toast seen, counts in the top bar)."""
        trace = self._refine_trace(frame)
        toast = self._boxes_text(self._roi_boxes(frame, MISSION_TOAST_ROI, "精炼提示"))
        self.info_set("精炼提示 OCR", toast or "-")
        self.info_set("精炼痕迹", f"{trace_before} -> {trace}")
        toast_seen = (
            toast != toast_before and keyword_match_count(toast, REFINE_TOAST_KEYWORDS) >= 1
        )
        return toast_seen, self._top_counts(toast)

    def _press_refine_once(self, refine) -> str:
        """"refined" once the refine shows on screen, else "unconfirmed".

        Proof is the 精炼成功 toast or a lower material count (two agreeing
        reads).  精炼 spends materials and gold, so the second press is made
        only while nothing at all changed: the page, the counts and the
        button are as before the press.  A page that never changed is a
        failure, never "done" (a lost press left the daily mission undone);
        one that changed without proof stays "refined" with a warning, since
        a retry of a refine that did land would refine twice.
        """
        frame = self.capture_frame()
        trace_before = self._refine_trace(frame)
        if trace_before is None:
            # The counter may draw a moment after the buttons.
            self.sleep(0.5)
            frame = self.capture_frame()
            trace_before = self._refine_trace(frame)
        toast_before = self._boxes_text(self._roi_boxes(frame, MISSION_TOAST_ROI, "精炼提示"))
        counts_before = self._top_counts(toast_before)
        page_before = self._region_thumbs(frame, (REFINE_PAGE_ROI,))
        seen = {"spent": None, "changed": False}

        def refined() -> bool:
            frame = self.capture_frame()
            toast_seen, counts = self._refine_signals(frame, trace_before, toast_before)
            spent = counts if self._counts_spent(counts_before, counts) else None
            # Lower material/gold counts count once two reads agree.
            agreed = spent is not None and spent == seen["spent"]
            seen["spent"] = spent
            seen["changed"] = seen["changed"] or self._thumbs_changed(
                page_before, self._region_thumbs(frame, (REFINE_PAGE_ROI,))
            )
            if toast_seen or agreed:
                self.log_info(
                    "每日精炼：已精炼一次"
                    + (f"（材料 {counts_before} -> {spent}）。" if spent else "。")
                )
            return toast_seen or agreed

        def untouched() -> bool:
            # Any change while waiting (animation, counts) may be the refine.
            if seen["changed"]:
                return False
            frame = self.capture_frame()
            counts = self._top_counts(
                self._boxes_text(self._roi_boxes(frame, MISSION_TOAST_ROI, "精炼提示"))
            )
            return (
                bool(counts_before)
                and counts == counts_before
                and not self._thumbs_changed(
                    page_before, self._region_thumbs(frame, (REFINE_PAGE_ROI,))
                )
                and plain_refine_box(self._roi_boxes(frame, REFINE_BUTTONS_ROI, "精炼按钮"))
                is not None
            )

        self.info_set("当前阶段", "精炼一次")
        outcome = self.press_and_confirm(
            "每日精炼",
            lambda: self._click_box(refine, after_sleep=1.0),
            refined,
            still_before=untouched,
            timeout=REFINE_RESULT_SECONDS,
            poll=0.5,
        )
        if outcome:
            self.info_set("精炼结果", "已精炼")
            return "refined"
        if seen["changed"]:
            self.info_set("精炼结果", "已精炼（未确认）")
            self.log_warning(
                "每日精炼：点了精炼后画面有变化，但没看到精炼成功或材料减少，"
                "按已精炼处理，不再补按（以免精炼两次）。"
            )
            self._save_flow_diagnostic("refine_unconfirmed")
            return "refined"
        self.info_set("精炼结果", "未确认")
        self.log_warning(
            "每日精炼：点了精炼但没看到精炼成功（材料数没减少、没有提示），"
            "这次记为未完成，下次再做。"
        )
        self._why = "点了精炼但没看到精炼成功（材料数没减少、没有提示）"
        self._save_flow_diagnostic("refine_unconfirmed")
        return "unconfirmed"
