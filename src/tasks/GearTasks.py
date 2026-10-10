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
from time import monotonic
from types import SimpleNamespace

from qfluentwidgets import FluentIcon

from src.tasks.claim_page import BACK_BUTTON_POINT
from src.tasks.enhance_dialog import crop_reference, yellow_ratio
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text

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

DETAIL_BUTTONS_ROI = (1150, 700, 320, 70)
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


def refine_candidate(cells: list[tuple[int, int, int]]) -> tuple[int, int, int] | None:
    """First cell (row-major) whose refine value is a real number below 24.

    Leo 2026-10-05: pick one below 24 on the first try.  A lone digit is
    often a cut-off 2x ("22" read as "2", "24" as "4"), so two-digit reads
    (10-23) come first and single digits only when none is left.
    """
    for low in (10, 1):
        for row, column, value in cells:
            if low <= value < MAX_REFINE:
                return row, column, value
    return None


# 精炼 followed only by its cost ("精炼80", "精炼●80"): rejects 连续精炼 and
# other labels that merely start with 精炼, such as 精炼痕迹.
# The refine page's bottom bar when the item is already at the cap.
MAXED_TEXT = "达到最大强化级别"
REFINE_CANDIDATE_ATTEMPTS = 3
SINGLE_REFINE_PATTERN = re.compile(r"^精炼[^一-鿿]*$")
# A 精炼 box this close after a 连续 box is part of 连续精炼 (1080 px).
REFINE_SPLIT_GAP = 60
REFINE_ROW_TOLERANCE = 30


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
        cells = self._wait_for_grid_cells()
        self.info_set("精炼值", " ".join(f"{r},{c}={v}" for r, c, v in cells) or "-")
        tried: set[tuple[int, int]] = set()
        outcome = "none"
        for _attempt in range(REFINE_CANDIDATE_ATTEMPTS):
            candidate = refine_candidate([cell for cell in cells if cell[:2] not in tried])
            if candidate is None:
                break
            row, column, value = candidate
            tried.add((row, column))
            self.info_set("精炼目标", f"第{row + 1}行第{column + 1}列，精炼值 {value}")
            outcome = self._refine_cell(row, column)
            if outcome == "no_button":
                # This item has no 精炼 (a player's 2560×1440 run, 2026-10-10,
                # stopped on the first one): its popup is closed, try the next.
                self.log_info(f"每日精炼：第{row + 1}行第{column + 1}列不能精炼，换下一件。")
                continue
            if outcome != "maxed":
                break
            # OCR can drop a digit ("24" read as "4", live 2026-09-27): the
            # item is already at the cap, so go back and try the next one.
            self.log_info(f"每日精炼：第{row + 1}行第{column + 1}列已达最大精炼，换下一件。")
        if outcome == "none":
            self.log_info("每日精炼：首屏没有可精炼的装备，跳过。")
        if outcome == "no_button":
            outcome = "failed"
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
        self._claim_fail(stage)
        why = getattr(self, "_why", "")
        text = f"{stage}失败：{why}" if why else f"{stage}失败"
        self.info_set("当前阶段", text)
        if why:
            self.info_set("状态", f"{self.name}：{text}。")
            self.log_warning(f"{self.name}：{text}。")
        return False

    def _wait_for_grid_cells(self, timeout: float = 3.0) -> list:
        """Refine badges of the first screen; empty only after ``timeout``.

        A single read right after the bag opened could come before the
        badges drew and silently skipped the daily refine.
        """
        end_at = monotonic() + timeout
        while True:
            cells = badge_cells(self._grid_boxes(self.capture_frame()))
            if cells or monotonic() >= end_at:
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
        (its popup closed, still in the bag) / unconfirmed / failed."""
        self._sleep_after_recognition()
        self._click_reference(GRID_COLUMNS[column], GRID_ROWS[row], after_sleep=1.0)
        detail = self._wait_boxes(
            DETAIL_BUTTONS_ROI, "装备详情按钮", lambda boxes: plain_refine_box(boxes) is not None
        )
        button = plain_refine_box(detail)
        if button is None:
            # A player's summary (2026-10-10) had only this line and the bag it
            # went back to: what the popup showed is kept for the 问题摘要.
            seen = self._boxes_text(detail) or "没读到字"
            self.log_info(
                f"每日精炼：第{row + 1}行第{column + 1}列的装备详情里没有精炼按钮，"
                f"按钮处读到「{seen}」。"
            )
            self._why = (
                f"第{row + 1}行第{column + 1}列的装备详情里没有精炼按钮（按钮处读到「{seen}」）"
            )
            self._save_flow_diagnostic("daily_refine_no_refine_button")
            return "no_button" if self._close_item_popup(detail) else "failed"
        self._click_box(button, after_sleep=1.5)
        if not self._wait_for_title("精炼", REFINE_PAGE_TITLE):
            self._why = "点了精炼后，精炼页没出来"
            return "failed"
        buttons = self._wait_boxes(
            REFINE_BUTTONS_ROI,
            "精炼按钮",
            lambda boxes: plain_refine_box(boxes) is not None
            or MAXED_TEXT in normalize_ocr_text(self._boxes_text(boxes)),
        )
        refine = plain_refine_box(buttons)
        button_text = self._boxes_text(buttons)
        self.info_set("精炼按钮 OCR", button_text or "-")
        if refine is None:
            if MAXED_TEXT in normalize_ocr_text(button_text):
                return self._back_to_bag("maxed")
            self.log_info("每日精炼：精炼页找不到单次精炼按钮。")
            self._why = f"精炼页找不到单次精炼按钮（读到「{button_text or '没读到字'}」）"
            return self._back_to_bag("failed")
        return self._back_to_bag(self._press_refine_once(refine))

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
