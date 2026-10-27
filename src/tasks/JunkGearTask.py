"""Enhance freshly acquired junk gear to +7 with auto-dismantle (爛装处理).

Flow calibrated on the 简体 client, 2026-09-26, from the user's demonstration:
bag → equipment → sort by acquisition time (newest first) → open each new
item's detail to classify it → 一键强化 selection mode → select the junk
cells → ✓ → 强化设置: target 7, 自动分解 ON → 强化 → result → restore the
user's original sort.

Only items carrying the yellow "!" new-item badge are considered (the game
shows it on gear acquired since the bag was last opened); with the bag sorted
newest first they sit at the top, and the scan stops at the first unmarked
cell.  If the bag was already opened by hand that day nothing is processed.
Classification rules live in src/utils/junk_gear.py.
"""

from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np
from ok.task.exceptions import FinishedException, TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks import run_report
from src.tasks.bag_filter import BagFilterMixin
from src.tasks.CraftGearTask import NGearCraftMixin
from src.tasks.enhance_dialog import (
    COUNT_DIGIT_ROI,
    ENHANCE_CANCEL_POINT,
    RESULT_ROI,
    YELLOW_ON_RATIO,
    EnhanceDialogMixin,
    crop_reference,
    yellow_ratio,
)
from src.tasks.GearTasks import (
    BADGE_OFFSET_X,
    BADGE_OFFSET_Y,
    EQUIPMENT_TITLE_KEYWORDS,
    GRID_COLUMNS,
    GRID_ROWS,
    DailyRefineTask,
)
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils import accounts, image_io
from src.utils.colour_check import (
    check_settled,
    distorted_colour_warning,
    last_check,
    remember,
)
from src.utils.image_utils import template_match_response
from src.utils.junk_gear import (
    POPUP_CLOSE_REFERENCE_Y,
    GearItem,
    agreed_rarity,
    badge_shown,
    classify,
    classify_low_grade,
    grid_label_colour_certain,
    grid_label_rarity,
    hue_share,
    label_hues,
    label_text_looks_ur,
    leading_new_cells,
    load_exclusive_owners,
    load_exclusive_stars,
    occupied_cells,
    ocr_rarity,
    popup_close_point,
    slot_icon_shown,
)
from src.utils.ocr_utils import normalize_ocr_text
from src.utils.press_confirm import SLOW_PC_GRACE_SECONDS, wait_for
from src.utils.wait_limits import STUCK_SECONDS

# 1920x1080 reference coordinates / ROIs.
SORT_BUTTON_POINT = (1777, 100)
SORT_MENU_ROI = (1385, 85, 415, 345)
# Outside the menu: a click inside it would pick an option (learned live).
SORT_MENU_CLOSE_POINT = (1200, 40)
SORT_MENU_SCROLL_POINT = (1590 / 1920, 250 / 1080)
SORT_MENU_STEP_NOTCHES = 2
SORT_MENU_MAX_STEPS = 10
SORT_MENU_WAIT_SECONDS = 3.0
TIME_SORT_TEXT = "按获得时间"
NEWEST_FIRST_TEXT = "从晚到早"
DETAIL_ROI = (470, 300, 1000, 480)
# Every height the popup can have (Leo 2026-10-12 「本來裝備詳情欄就有高有低」
# 「不要視窗抓那麼緊」): the open check and the detail read look at all of it.
DETAIL_WIDE_ROI = (470, 40, 1000, 1000)
DETAIL_NAME_ROW = (480, 325, 520, 60)
NAME_LINE_Y = (335, 372)
# Boxes on the title line: centres this close to the rarity letter's.
NAME_LINE_TOLERANCE = 20
DETAIL_CLOSE_POINT = (1419, 325)
# Blank space left of the detail popup: a tap there also closes it (Leo
# 2026-10-12 「點空白處也可以關」), clear of the bag menu and the grid.
DETAIL_BLANK_TAP_POINT = (280, 620)
# The diamond right of the item art holds the refine level once the item is
# fully enhanced (Leo's 顶级英雄盔甲 「15」, 4K 2026-10-11); +0 items show an
# empty outline.  52 popups: a number 0.068-0.113 white, empty 0.000.  A
# fully enhanced item also shows 精炼 instead of 强化.
POPUP_LEVEL_BOX = (1376, 622, 40, 40)
POPUP_LEVEL_WHITE_MIN = 0.03
POPUP_REFINE_WORDS = ("精炼", "精煉")
LOCK_SWITCH_ROI = (495, 405, 60, 35)
# The owner line sits above 「专用装备」 (real R popup 2026-10-10, 首席勋章:
# "艾玛" centre 40 px above it).  Offsets of its centre from that line's.
OWNER_LINE_DY = (-70, -15)
EXCLUSIVE_LINE_KEYWORDS = ("专用装备", "專用裝備")
ONE_CLICK_ENHANCE_POINT = (1486, 1004)
SELECTION_ROI = (700, 965, 560, 95)
SELECTION_CANCEL_POINT = (1697, 1005)
SELECTION_CONFIRM_POINT = (1777, 1005)
# 一键分解 on the bag, 取消 in selection mode (Leo's 4K bag reads 「键分解」).
BOTTOM_RIGHT_BUTTON_ROI = (1590, 970, 220, 70)
# Character art on the left: closes the result overlay without hitting a cell.
NEUTRAL_TAP_POINT = (560, 140)
# No result text read this long after 开始强化: one tap on blank space
# (Leo 2026-10-14 「頂多等8秒到10秒」: was 12 s, with 30 s in all; now each
# step without progress ends after STUCK_SECONDS).
RESULT_BLIND_TAP_SECONDS = 8.0
DETAIL_READ_RETRIES = 3
# A junk verdict is read twice this far apart: a 穿戴中 tag or lock drawn late
# on a slow PC would otherwise send the item to auto-dismantle.
DETAIL_CONFIRM_SECONDS = 1.0
# The task's own name (self.name) stays 爛装强化分解: it keys the saved
# settings and the 一键日常 tick.  Texts players read say 烂装.
LABEL = "烂装强化分解"
# The weekly 制作装备 default: +5 dismantles the crafted N item.
CRAFT_N_TARGET_LEVEL = 5
# Every item detail popup shows this line; the plain bag grid never does.
DETAIL_OPEN_KEYWORD = "自定义标记"
DETAIL_STATE_TIMEOUT = 3.0
# Icon area of a grid cell (offsets from its centre, 1080 reference), clear
# of the "!" badge at the top right; compared before each selection click.
CELL_ICON_BOX = (-45, -40, 75, 85)
# The rarity letters at a cell's top right (offsets from its centre).
GRID_LABEL_BOX = (18, -60, 46, 32)
# The padlock at a cell's left edge.  A locked item is never opened and
# never dismantled (user, 2026-09-27).  Live 4K: locked cells scored
# 0.90-1.00 against the padlock template, an unlocked one 0.57; 4K
# 2026-10-11 bag frames: locked 0.90-0.99, unlocked at most 0.47.  Loose,
# since a padlock read as none could dismantle (Leo 「寧願不拆也不要誤拆」).
GRID_LOCK_SEARCH_BOX = (-56, -28, 28, 38)
GRID_LOCK_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "recognition-assets" / "template-assets" / "junk" / "grid_lock.png"
)
GRID_LOCK_MIN_SCORE = 0.7
MAX_ITEMS_PER_RUN = 10
# The bag filter shows one grade at a time (single-select 级别 row).
FILTER_GRADES = ("R", "SR")
# Opened before dismantling: SR comes as 5★ exclusives (翼角头盔 SR of
# 格兰希特 in Leo's bag); R is not opened (Leo 2026-10-11 「r不點開 5星sr不拆」).
OPENED_GRADES = ("SR",)
# Live 2026-09-26, bag grid vs 一键强化 selection mode: the same cell scored
# 0.85-1.0, a different item 0.14-0.47.
SELECTION_MATCH_MIN = 0.75
# Set by 一键日常 when this runs right after a finished 免费抽抽乐.
AFTER_GACHA_KEY = "_紧接抽抽乐"
# Leo 2026-10-11: the player chooses whether 5★ characters' SR exclusives go
# too (the R/SR switch is gone: R and SR are always the junk grades).
FIVE_STAR_SR_KEY = "分解5★角色的SR专用装备"
# Picks that came out another count than planned: cancel and pick again once.
SELECTION_ATTEMPTS = 2
# Mean grey change of the counter bar that shows a tap did something.
BAR_CHANGE_MIN = 12.0
# The user's bag sort, saved before switching so a crash or Stop mid-run can
# be undone on the next run.
SORT_STATE_FILE = Path("configs") / "junk_gear_sort.json"
# The active option ends in a direction arrow (Leo's 4K menu: 「按强化从高到低
# 排序↓」); some options have no 从…到… at all (player 2026-10-11, v0.1.23:
# 「有自定义标记优先▼」 was read but not taken as active).
SORT_ARROWS = "▼▲↓↑"
# A kind or direction one character off (OCR at 1080p) still matches.
SORT_MATCH_RATIO = 0.75
# Extra menu reads to get two in a row that agree on the active label.
SORT_SETTLE_READS = 3
# A saved sort that failed to restore this often, or this old, is dropped.
SORT_RESTORE_MAX_FAILURES = 2
SORT_STATE_MAX_AGE_SECONDS = 2 * 24 * 3600
# Junk a failed run judged but did not dismantle (their "!" badges are gone once
# the bag was opened): icon snapshots matched against the next run's grid.
PENDING_FILE = Path("configs") / "junk_gear_pending.json"


@lru_cache(maxsize=1)
def _exclusive_owners() -> dict[str, frozenset[str]]:
    return load_exclusive_owners()


def _pending_file() -> Path:
    """Each game account has its own bag (GitHub issue #4)."""
    return Path(accounts.scoped(PENDING_FILE))


def _sort_state_file() -> Path:
    return Path(accounts.scoped(SORT_STATE_FILE))


# A rarity glued to the end of a Chinese name: "冰雪红宝石R" -> "冰雪红宝石 R".
GLUED_RARITY = re.compile(r"([^\x00-\x7f])(UR|SR|R|N)(?=\s|$)")
NON_ASCII = re.compile(r"[^\x00-\x7f]")


def _part_box(box, text: str):
    """A copy of an OCR box that reads ``text`` (same position)."""
    return SimpleNamespace(
        name=text,
        x=box.x,
        y=box.y,
        width=box.width,
        height=box.height,
        confidence=getattr(box, "confidence", 1.0),
    )


def grid_label_text_matches(text: str, rarity: str) -> bool:
    """OCR of the label reads ``rarity``; the "!" badge beside it may add a
    trailing I / 1 / L / ! (e.g. "R!" read as "RI")."""

    letters = re.sub(r"[^A-Za-z0-9]", "", str(text)).upper()
    if ocr_rarity(letters) == rarity:
        return True
    trimmed = letters.rstrip("1IL")
    return bool(trimmed) and ocr_rarity(trimmed) == rarity


def filter_for(grade: str) -> dict:
    """The bag filter of one pass: worn gear hidden; SR with 分类 专用 only, so
    nothing but exclusives can show (Leo 2026-10-11 「分類 點選專用 就不會拆到
    其他裝了」); R with no 分类."""
    return {"grade": grade, "worn": False, "categories": ["专用"] if grade == "SR" else []}


def popup_level_shown(reference) -> bool:
    """The detail popup's diamond shows a level number (1080-reference frame)."""
    x, y, width, height = POPUP_LEVEL_BOX
    patch = reference[y : y + height, x : x + width, :3]
    if patch.size == 0:
        return True
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return float(((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 200)).mean()) >= POPUP_LEVEL_WHITE_MIN


def grid_cell_locked(frame, cell: tuple[int, int], template=None) -> bool:
    """The cell shows the padlock (1080-reference frame)."""

    if template is None:
        template = image_io.read(GRID_LOCK_TEMPLATE, cv2.IMREAD_GRAYSCALE)
    if template is None:
        return True  # no template: treat every cell as locked, touch nothing
    row, column = cell
    dx, dy, width, height = GRID_LOCK_SEARCH_BOX
    x, y = GRID_COLUMNS[column] + dx, GRID_ROWS[row] + dy
    region = cv2.cvtColor(frame[y : y + height, x : x + width], cv2.COLOR_BGR2GRAY)
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return True
    return float(template_match_response(region, template).max()) >= GRID_LOCK_MIN_SCORE


def bar_changed(before, after) -> bool:
    """The 1080p counter-bar crops differ visibly (a tap took)."""
    if before is None or after is None or before.size == 0 or before.shape != after.shape:
        return True
    a = cv2.cvtColor(before[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.int16)
    b = cv2.cvtColor(after[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.int16)
    return float(np.abs(a - b).mean()) >= BAR_CHANGE_MIN


def cell_similarity(first, second, cell: tuple[int, int]) -> float:
    """Normalised correlation of one grid cell's icon in two 1080p frames."""

    row, column = cell
    dx, dy, width, height = CELL_ICON_BOX
    x, y = GRID_COLUMNS[column] + dx, GRID_ROWS[row] + dy
    a = cv2.cvtColor(first[y : y + height, x : x + width], cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(second[y : y + height, x : x + width], cv2.COLOR_BGR2GRAY)
    if a.size == 0 or a.shape != b.shape:
        return 0.0
    return float(template_match_response(a, b)[0][0])


def new_items_kept_note(count: int, kept_reasons, junk_left: str = "") -> str:
    """For the report: the new 「!」 items were looked at, none dismantled, and why."""
    tally: dict[str, int] = {}
    for reason in kept_reasons:
        tally[reason] = tally.get(reason, 0) + 1
    why = "、".join(f"{reason} {n} 件" for reason, n in tally.items())
    parts = [f"新装备 {count} 件都没拆"]
    if why:
        parts.append(f"保留：{why}")
    if junk_left:
        parts.append(junk_left)
    return "；".join(parts)


def sort_label_core(text: str) -> str:
    """The Chinese part of a sort label; OCR adds arrows such as ↓ or ▼."""
    return re.sub(r"[^一-鿿]", "", str(text))


def sort_category(label: str) -> str:
    """The sort kind of a label, e.g. 强化 for 按强化阶段从高到低排序.

    Inactive options read 按强化阶段排序 and the active one adds the
    direction; at 1080p the active one was read without 阶段 (live
    2026-09-28), so 按/阶段/排序 and the direction are all dropped.
    """
    core = sort_label_core(label)
    core = core.split("从", 1)[0]
    for noise in ("按", "阶段", "排序"):
        core = core.replace(noise, "")
    return core


def sort_direction(label: str) -> str:
    core = sort_label_core(label)
    return core.split("从", 1)[1].replace("排序", "") if "从" in core else ""


def similar_sort_text(a: str, b: str) -> bool:
    return a == b or bool(a and b and SequenceMatcher(None, a, b).ratio() >= SORT_MATCH_RATIO)


def same_sort(a: str | None, b: str | None) -> bool:
    """Same kind and direction; a saved label one character off still
    matches, or it could never be restored (review #22)."""
    if not a or not b:
        return False
    return similar_sort_text(sort_category(a), sort_category(b)) and similar_sort_text(
        sort_direction(a), sort_direction(b)
    )


def active_sort_label(boxes) -> str | None:
    """Only the active sort option shows its direction (…从高到低… / …从晚到早…)
    or, for options without one, an arrow at its end."""
    for box in boxes:
        text = sort_label_core(getattr(box, "name", ""))
        if "从" in text and text.endswith("排序"):
            return text
    for box in boxes:
        raw = str(getattr(box, "name", "")).strip()
        text = sort_label_core(raw)
        if text and raw[-1] in SORT_ARROWS:
            return text
    return None


def badge_text_cells(boxes) -> set[tuple[int, int]]:
    """Cells whose enhance badge spot shows a number or 「+N」.

    ``boxes`` are in 1920x1080 reference coordinates.  Leo's 4K bag
    (2026-10-11): 「15」 or 「+7」 there means enhanced; nothing means +0.
    """
    marked: set[tuple[int, int]] = set()
    for box in boxes:
        text = str(getattr(box, "name", ""))
        if not re.search(r"[\d+＋]", text):
            continue
        x = float(box.x) + float(box.width) / 2
        y = float(box.y) + float(box.height) / 2
        for row, cy in enumerate(GRID_ROWS):
            for column, cx in enumerate(GRID_COLUMNS):
                if (
                    BADGE_OFFSET_X[0] <= x - cx <= BADGE_OFFSET_X[1]
                    and BADGE_OFFSET_Y[0] <= y - cy <= BADGE_OFFSET_Y[1]
                ):
                    marked.add((row, column))
    return marked


class JunkGearTask(BagFilterMixin, NGearCraftMixin, EnhanceDialogMixin, DailyRefineTask):
    claim_log_name = "junk_gear"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "爛装强化分解"
        self.description = (
            "一键日常里紧接免费抽抽乐时，先只处理带黄色!的新装备，不动背包筛选和排序；"
            "没有拆到时，背包先筛选出 R、再筛选出 SR（按获得时间排序），看最前面几件："
            "强化到 +7 并自动分解；"
            "SR 会点开核对，只拆 3★/4★ 角色专用的；设定里开启 5★ 后，SR 不点开直接拆；"
            "上锁、穿戴中、已强化的一律保留，UR 不碰。"
            "背包筛选和排序会改回原样。"
            "没有可分解的烂装时，做一件 N 装备强化后分解（每日任务）。"
        )
        self.icon = FluentIcon.DELETE
        self.default_config.update(
            {
                "强化目标等级": 7,
                "最多处理件数": 10,
                FIVE_STAR_SR_KEY: False,
            }
        )
        self.config_description.update(
            {
                "强化目标等级": "烂装强化到的等级，达到后游戏自动分解。",
                "最多处理件数": (
                    "整次最多处理几件（黄色!新装备、R、SR 和 N 装备都算在内），1~10 件。"
                ),
                FIVE_STAR_SR_KEY: (
                    "开启后，SR 不点开，和 R 一样直接分解；"
                    "关闭时点开核对，5★ 角色的保留（默认）。"
                ),
            }
        )
        # 1-10 items per run (user, 2026-09-27).
        self.config_type.update({"最多处理件数": {"min": 1, "max": MAX_ITEMS_PER_RUN, "step": 1}})

    # -- entry ------------------------------------------------------------------

    def run_claim(self) -> bool:
        self._items_left_this_run = self._items_cap()
        stars = load_exclusive_stars()
        colours_distorted = self._colours_distorted()
        if not self._open_equipment_bag():
            return self._claim_fail("打开背包装备页")
        pending = self._saved_sort()
        if (
            pending
            and not self._restore_sort(pending)
            and not self._sort_restore_given_up(pending)
        ):
            self.log_warning(f"{LABEL}：上次中断的背包排序「{pending}」未能恢复，本次不处理。")
            return self._claim_fail("恢复上次的背包排序")
        self._clear_saved_sort()
        saved_filter = self._saved_filter()
        if saved_filter is not None:
            if not self._set_bag_filter(saved_filter):
                self.log_warning(f"{LABEL}：上次中断的背包筛选未能恢复，本次不处理。")
                return self._claim_fail("恢复上次的背包筛选")
            self._clear_saved_filter()
        if self.config.get(AFTER_GACHA_KEY, False):
            ok, failed_stage, dismantled = self._dismantle_new_marked(stars, colours_distorted)
            if not ok:
                return self._claim_fail(failed_stage)
            if dismantled:
                self._restore_bag_detail_view()
                return self._leave_to_home("背包", EQUIPMENT_TITLE_KEYWORDS)
            self.log_info(f"{LABEL}：带黄色!的新装备没有拆到，改用筛选 R / SR。")
        original_filter = self._read_bag_filter()
        if original_filter is None:
            if self._filter_menu_open() and not self._close_filter_menu(changed=False):
                return self._claim_fail("关闭背包筛选")
            # Leo 2026-10-11 「識別不到的話也要有替代方案」: the grid labels.
            self.log_info(f"{LABEL}：没读清楚背包筛选，改看背包最前面几格的稀有度。")
        original_sort = self._switch_to_newest_first()
        if original_sort is None:
            # The filter shows R/SR whatever the sort; the player's sort is
            # left as it is (Leo 「識別不到的話也要有替代方案」).
            self.log_info(f"{LABEL}：排序没切成按获得时间，照背包现在的排序继续。")
        ok = True
        failed_stage = "强化分解"
        stopped = False
        dismantled = False
        try:
            self._clear_pending()  # from the "!" version; nothing is carried now
            if original_filter is not None:
                ok, failed_stage, dismantled = self._dismantle_filtered(
                    stars, original_filter, colours_distorted
                )
                if not ok and failed_stage.startswith("筛选") and not dismantled:
                    # The filter did not switch: put it back, then the
                    # grid labels as without a filter.
                    if self._set_bag_filter(original_filter):
                        self._clear_saved_filter()
                        self.log_info(f"{LABEL}：背包筛选切不过去，改看最前面几格的稀有度。")
                        ok, failed_stage, dismantled = self._dismantle_unfiltered(
                            stars, colours_distorted
                        )
                    else:
                        failed_stage = "恢复背包筛选"
            else:
                ok, failed_stage, dismantled = self._dismantle_unfiltered(
                    stars, colours_distorted
                )
        except (TaskDisabledException, FinishedException):
            # Stop means no more clicks; the saved filter and sort are put
            # back next run.
            stopped = True
            raise
        finally:
            if not stopped:
                if (
                    original_filter is None
                    or self._saved_filter() is None
                    or self._set_bag_filter(original_filter)
                ):
                    self._clear_saved_filter()
                else:
                    ok, failed_stage = False, "恢复背包筛选"
                    self.log_warning(f"{LABEL}：未能把背包筛选改回原样。", notify=True)
                if original_sort is None:
                    pass  # not switched; a sort the switch saved stays for next run
                elif self._restore_sort(original_sort):
                    self._clear_saved_sort()
                else:
                    self.log_warning(
                        f"{LABEL}：未能把背包排序恢复为「{original_sort}」。", notify=True
                    )
        if not stopped:
            self._restore_bag_detail_view()
        if ok and not dismantled:
            if self._items_left() < 1:
                self.log_info(f"{LABEL}：已经看满最多处理件数，这次不再做 N 装备分解。")
            else:
                self._spend_items(1)
                if not self._dismantle_crafted_n():
                    ok, failed_stage = False, "制作 N 装备分解"
        if not ok:
            return self._claim_fail(failed_stage)
        return self._leave_to_home("背包", EQUIPMENT_TITLE_KEYWORDS)

    def _items_cap(self) -> int:
        return max(1, min(int(self.config.get("最多处理件数", 10)), MAX_ITEMS_PER_RUN))

    def _items_left(self) -> int:
        """最多处理件数 is for the whole run: the 「!」 pass, the R / SR filter,
        the unfiltered fallback and the N item all count against it (Leo
        2026-10-11 「不管你如何處理這些裝備，處理的件數都不可以超過設定裡面的件數」)."""
        return self.__dict__.get("_items_left_this_run", self._items_cap())

    def _spend_items(self, count: int) -> None:
        self._items_left_this_run = self._items_left() - count

    def _front_items(self, cap: int):
        """The grid frame and its leading occupied cells (at most ``cap``),
        looked at again on a slow PC before taking the bag as empty."""
        frame = self._still_grid_frame()
        cells = occupied_cells(frame, GRID_COLUMNS, GRID_ROWS, cap)
        if cells:
            return frame, cells
        looked = {"frame": frame}

        def items():
            looked["frame"] = self._still_grid_frame()
            return occupied_cells(looked["frame"], GRID_COLUMNS, GRID_ROWS, cap)

        cells = wait_for(items, SLOW_PC_GRACE_SECONDS, sleep=self.sleep, poll=0.8) or []
        return looked["frame"], cells

    def _dismantle_judged(self, cells, stars, frame, grade, colours_distorted, fresh=False):
        """Judge ``cells`` and dismantle the junk: (ok, failed stage, dismantled)."""
        junk = self._classify_cells(cells, stars, frame, grade=grade, fresh=fresh)
        if junk is None:
            return False, "识别装备", False
        self._junk_left = ""
        if junk and colours_distorted:
            self.log_info(f"{LABEL}：画面颜色异常，识别出 {len(junk)} 件烂装，未分解。")
            self._junk_left = f"认出 {len(junk)} 件烂装，画面颜色异常没拆"
            return True, "", False
        if junk:
            done = self._enhance_and_dismantle(junk, frame)
            if done is None:
                # Cancelled before enhancing: go on.
                self._junk_left = f"认出 {len(junk)} 件烂装，一键强化没选成没拆"
                return True, "", False
            if not done:
                return False, "强化分解", False
            return True, "", True
        return True, "", False

    def _dismantle_new_marked(self, stars, colours_distorted) -> tuple[bool, str, bool]:
        """Right after 抽抽乐 (Leo 2026-10-11): only the items with the yellow
        「!」, the bag's filter and sort as the player left them.  Fresh gear
        is always first in the bag (Leo 「它一定會在最前面」), so read from the
        top-left and stop at the first cell without 「!」.  Each is
        judged by its grid label as without a filter: R dismantled, SR opened
        (3★/4★ exclusive only), UR and the rest never touched."""
        cap = self._items_left()
        if cap < 1:
            return True, "", False
        frame = self._still_grid_frame()
        cells = leading_new_cells(frame, GRID_COLUMNS, GRID_ROWS, cap)
        if not cells:
            # The badges may draw late on a slow PC: look again first.
            looked = {"frame": frame}

            def badges():
                looked["frame"] = self._still_grid_frame()
                return leading_new_cells(looked["frame"], GRID_COLUMNS, GRID_ROWS, cap)

            cells = wait_for(badges, SLOW_PC_GRACE_SECONDS, sleep=self.sleep, poll=0.8) or []
            frame = looked["frame"]
        self.info_set("新装备（黄色!）", len(cells))
        if not cells:
            return True, "", False
        result = self._dismantle_judged(cells, stars, frame, None, colours_distorted, fresh=True)
        if result[2]:
            # Kept items only looked at do not count: ten new UR / exclusive
            # items used up the whole count, so the R / SR pass never ran and
            # 一键日常 showed 完成 with nothing dismantled (player 2026-10-13).
            self._spend_items(len(cells))
        elif result[0]:
            # Leo 2026-10-13 「如果真的有這種情況 報表要寫」.
            note = new_items_kept_note(
                len(cells),
                self.__dict__.get("_kept_reasons", []),
                self.__dict__.get("_junk_left", ""),
            )
            self.log_info(f"{LABEL}：{note}")
            run_report.add_current_note(note)
        return result

    def _dismantle_unfiltered(self, stars, colours_distorted) -> tuple[bool, str, bool]:
        """Without the filter: the first 最多处理件数 items of the newest-first
        bag, each by its grid label (R / SR; anything else is kept)."""
        cap = self._items_left()
        if cap < 1:
            return True, "", False
        frame, cells = self._front_items(cap)
        self.info_set("不筛选", len(cells))
        self._spend_items(len(cells))
        if not cells:
            return True, "", False
        return self._dismantle_judged(cells, stars, frame, None, colours_distorted)

    def _dismantle_filtered(
        self, stars: dict[str, int], original_filter: dict, colours_distorted: bool
    ) -> tuple[bool, str, bool]:
        """Filter R, then SR with 分类 专用 (worn gear hidden), and judge the first
        最多处理件数 items in all (Leo 2026-10-11 「篩選 r sr 出來」「五件那就
        只看前五件」).  Returns (ok, failed stage, dismantled any)."""
        left = self._items_left()
        dismantled = False
        self._save_filter(original_filter)
        for grade in FILTER_GRADES:
            if left <= 0:
                break
            if not self._set_grade_filter(grade):
                if dismantled:
                    # What is dismantled stays done; the rest waits for tomorrow.
                    self.log_warning(f"{LABEL}：背包筛选没切到 {grade}，{grade} 这次不分解。")
                    return True, "", dismantled
                self.log_warning(f"{LABEL}：背包筛选没切到 {grade}，这次不分解。")
                return False, f"筛选 {grade}", dismantled
            frame, cells = self._front_items(left)
            self.info_set(f"筛选 {grade}", len(cells))
            if not cells:
                continue
            self._spend_items(len(cells))
            left = self._items_left()
            ok, stage, done = self._dismantle_judged(
                cells, stars, frame, grade, colours_distorted
            )
            dismantled = dismantled or done
            if not ok:
                return False, stage, dismantled
        return True, "", dismantled

    def _set_grade_filter(self, grade: str) -> bool:
        """The grade's filter; when its 分类 cannot be confirmed (two taps, no
        visible change), the grade alone: SR is still opened one by one and
        only a 3★/4★ character exclusive dismantled (Leo 「你不會又點一次沒點到
        或者 沒辨識到 又整個失敗吧」)."""
        wanted = filter_for(grade)
        if self._set_bag_filter(wanted):
            return True
        if not wanted.get("categories"):
            return False
        grade_only = {key: value for key, value in wanted.items() if key != "categories"}
        if not self._set_bag_filter(grade_only):
            return False
        self.log_info(
            f"{LABEL}：分类「专用」没确认勾上，改为只筛 {grade}，逐件点开核对 3★/4★ 角色专用。"
        )
        self.info_set(f"筛选 {grade} 分类", "未确认，只筛级别")
        return True

    def _dismantle_crafted_n(self) -> bool:
        """No junk dismantled today: craft one N item, enhance and dismantle it,
        as the weekly 制作装备 does, so the daily 装备分解 mission is done (Leo
        2026-10-11 「沒有解到 就去像週常那樣 做一件n裝 強化後分解」)."""
        self.info_set("当前阶段", "制作 N 装备分解")
        self.log_info(
            f"{LABEL}：这次没有分解到烂装，做一件 N 装备强化后分解（每日任务「装备分解」）。"
        )
        if not self._open_craft_page():
            return False
        done = self._open_n_recipe() and self._craft(CRAFT_N_TARGET_LEVEL, 1)
        back = self._craft_back_to_bag()
        if not done:
            self.log_info(f"{LABEL}：N 装备没有做成（金币或材料不够时也会这样）。")
        return done and back

    def _colours_distorted(self) -> bool:
        """Dismantling cannot be undone: with colours visibly off (RTX HDR, a
        driver filter...) the new items are judged but kept (Leo 2026-09-30:
        HDR and the like must not break the judgement).  Read on home, before
        the bag opens; elsewhere this run's earlier home check is used."""

        try:
            frame = self.capture_frame()
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:  # the bag step captures again and reports a real failure
            frame = None
        check = check_settled(frame, self._frame_or_none, self.sleep)
        if check.distance is None:
            check = last_check() or check
        else:
            remember(check)
        self.info_set("画面颜色", check.detail)
        if check.distorted:
            self.log_warning(f"{LABEL}：{distorted_colour_warning(check)}", notify=True)
        return check.distorted

    def _frame_or_none(self):
        try:
            return self.capture_frame()
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:
            return None

    # -- carried-over junk (the "!" version) ----------------------------------------

    def _clear_pending(self) -> None:
        """Drop the list the "!" version kept: a filtered bag shows the same
        junk again next run, so nothing is carried any more."""
        try:
            _pending_file().unlink(missing_ok=True)
        except OSError:
            pass

    # -- sorting ------------------------------------------------------------------------

    def _sort_menu_boxes(self) -> list:
        return self._reference_boxes(self.capture_frame(), SORT_MENU_ROI, "排序菜单")

    def _wait_sort_menu(self, timeout: float) -> list:
        end_at = monotonic() + timeout
        while True:
            boxes = self._sort_menu_boxes()
            if any("排序" in str(getattr(b, "name", "")) for b in boxes):
                return boxes
            if monotonic() >= end_at:
                return []
            self.sleep(0.4)

    def _open_sort_menu(self) -> list:
        # The sort button toggles the menu: only click again once a full wait
        # proved the previous click did not open it (live: rapid re-clicks
        # opened and closed it in turn).
        for _attempt in range(3):
            self._click_reference(*SORT_BUTTON_POINT, after_sleep=0.6)
            boxes = self._wait_sort_menu(SORT_MENU_WAIT_SECONDS)
            if boxes:
                return boxes
        return []

    def _pick_sort_option(self, option) -> list:
        """Click an option and wait for the active label to change."""
        before = active_sort_label(self._sort_menu_boxes())
        self._click_reference_box(option, after_sleep=0.6)
        end_at = monotonic() + SORT_MENU_WAIT_SECONDS
        boxes = self._sort_menu_boxes()
        while active_sort_label(boxes) == before and monotonic() < end_at:
            self.sleep(0.4)
            boxes = self._sort_menu_boxes()
        return boxes

    def _find_sort_option(self, keyword: str) -> list:
        """The menu is a scrolling list that keeps the active option on top.

        A wheel notch scrolls the same pixels at any resolution, so at 1080p
        the old 6-notch jumps skipped the middle of the list (live
        2026-09-28).  Small steps down to the end, then up to the top.
        """
        boxes = self._sort_menu_boxes()
        if self._sort_option_shown(boxes, keyword):
            return boxes
        for direction in (1, -1):
            last_text = self._boxes_text(boxes)
            for _step in range(SORT_MENU_MAX_STEPS):
                self.scroll_client(
                    SORT_MENU_SCROLL_POINT,
                    direction * SORT_MENU_STEP_NOTCHES,
                    count=1,
                    after_sleep=0.5,
                )
                boxes = self._sort_menu_boxes()
                if self._sort_option_shown(boxes, keyword):
                    return boxes
                text = self._boxes_text(boxes)
                if text == last_text:
                    break  # this end of the list
                last_text = text
        return boxes

    @staticmethod
    def _sort_option_shown(boxes, keyword: str) -> bool:
        kind = sort_category(keyword)
        return JunkGearTask._box_with(boxes, (keyword,)) is not None or any(
            similar_sort_text(sort_category(getattr(box, "name", "")), kind) for box in boxes
        )

    @staticmethod
    def _inactive_option(boxes, keyword: str):
        """The option of that sort kind; clicking the active one flips it."""
        if not keyword:
            return None
        options = [
            box for box in boxes
            if similar_sort_text(sort_category(getattr(box, "name", "")), keyword)
        ]
        for box in options:
            if not sort_direction(getattr(box, "name", "")):
                return box
        return options[0] if options else JunkGearTask._box_with(boxes, (keyword,))

    def _sort_menu_open(self) -> bool:
        return any("排序" in str(getattr(b, "name", "")) for b in self._sort_menu_boxes())

    def _close_sort_menu(self) -> bool:
        """Close the menu and see it gone.  Left open it covers the 筛选
        button (a player's v0.2.4 run, 1920x1080 window 2026-10-21: every
        later 筛选 tap landed on the menu, R was never filtered and the
        player's filter could not be put back).  The sort button toggles the
        menu, so it is pressed only after a full wait shows the menu still
        there."""
        for point in (SORT_MENU_CLOSE_POINT, SORT_MENU_CLOSE_POINT, SORT_BUTTON_POINT):
            self._click_reference(*point, after_sleep=1.0)
            if wait_for(
                lambda: not self._sort_menu_open(),
                SORT_MENU_WAIT_SECONDS,
                sleep=self.sleep,
                poll=0.4,
            ):
                return True
        self.log_info(f"{LABEL}：排序菜单关不掉。")
        return False

    def _close_covering_menu(self) -> None:
        """The 筛选 button did not open its menu: a sort menu left open may
        lie over it."""
        if self._sort_menu_open():
            self._close_sort_menu()

    @staticmethod
    def _sort_state() -> dict:
        try:
            saved = json.loads(_sort_state_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return saved if isinstance(saved, dict) else {}

    @staticmethod
    def _saved_sort() -> str | None:
        return JunkGearTask._sort_state().get("original") or None

    @staticmethod
    def _write_sort_state(state: dict) -> None:
        try:
            _sort_state_file().parent.mkdir(parents=True, exist_ok=True)
            _sort_state_file().write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _save_sort(original: str) -> None:
        JunkGearTask._write_sort_state({"original": original, "saved": time.time()})

    def _sort_restore_given_up(self, label: str) -> bool:
        """Count a failed restore of the saved sort; True once it is dropped.

        A misread label may never be restored; kept, it failed every run
        until the file was deleted by hand (review #22).  Files from before
        the save date was written count as old.
        """
        state = self._sort_state()
        try:
            failures = int(state.get("failures", 0)) + 1
            age = time.time() - float(state.get("saved", 0))
        except (TypeError, ValueError):
            failures, age = SORT_RESTORE_MAX_FAILURES, 0.0
        if failures < SORT_RESTORE_MAX_FAILURES and age <= SORT_STATE_MAX_AGE_SECONDS:
            self._write_sort_state({**state, "failures": failures})
            return False
        self._clear_saved_sort()
        self.log_warning(
            f"{LABEL}：上次中断的背包排序「{label}」一直没能恢复，已不再恢复，继续处理；"
            "背包排序请自行调回。",
            notify=True,
        )
        return True

    @staticmethod
    def _clear_saved_sort() -> None:
        try:
            _sort_state_file().unlink()
        except OSError:
            pass

    def _settled_sort_boxes(self, boxes: list) -> tuple[list, bool]:
        """Menu boxes, and whether two reads in a row agreed on the active
        label.  A read while the menu fades in can drop a character (1080p),
        and a label saved from one such read was never found again."""
        label = active_sort_label(boxes)
        for _read in range(SORT_SETTLE_READS):
            self.sleep(0.4)
            again = self._sort_menu_boxes()
            again_label = active_sort_label(again)
            if label is not None and again_label == label:
                return again, True
            if again_label is not None:
                boxes, label = again, again_label
        return boxes, False

    def _switch_to_newest_first(self) -> str | None:
        boxes = self._open_sort_menu()
        settled = False
        if boxes:
            boxes, settled = self._settled_sort_boxes(boxes)
        original = active_sort_label(boxes)
        if not boxes or original is None:
            self.log_info(
                f"{LABEL}：排序菜单没有读到当前排序，OCR="
                + (" | ".join(str(getattr(b, "name", "")) for b in boxes) or "-")
            )
            if boxes:
                self._close_sort_menu()
            return None
        # Any kind read the same twice is saved: the menu has many stat sorts
        # (Leo's 「按攻击力从高到低排序」 was not on a fixed list, 2026-10-11).
        if settled:
            self._save_sort(original)
        else:
            self.log_info(
                f"{LABEL}：当前排序「{original}」没读稳，不记下"
                "（这次中途停止的话，下次不会自动改回）。"
            )
        for _attempt in range(3):
            active = active_sort_label(boxes)
            if active and TIME_SORT_TEXT in active and NEWEST_FIRST_TEXT in active:
                self._close_sort_menu()
                self.scroll_client((0.64, 0.52), 1, count=40, interval=0.03, after_sleep=1.0)
                self.info_set("背包排序", f"{original} -> {active}")
                return original
            boxes = self._find_sort_option(TIME_SORT_TEXT)
            option = self._box_with(boxes, (TIME_SORT_TEXT,))
            if option is None:
                break
            boxes = self._pick_sort_option(option)
        self._close_sort_menu()
        # The switch may have changed the sort before failing: put it back.
        if self._restore_sort(original):
            self._clear_saved_sort()
        return None

    def _restore_sort(self, original: str) -> bool:
        boxes = self._open_sort_menu()
        keyword = sort_category(original)
        for _attempt in range(3):
            if same_sort(active_sort_label(boxes), original):
                self._close_sort_menu()
                return True
            boxes = self._find_sort_option(keyword)
            if same_sort(active_sort_label(boxes), original):
                self._close_sort_menu()
                return True
            option = self._inactive_option(boxes, keyword)
            if option is None:
                break
            boxes = self._pick_sort_option(option)
        restored = same_sort(active_sort_label(boxes), original)
        if boxes:
            self._close_sort_menu()
        return restored

    # -- inspection -----------------------------------------------------------------------

    @staticmethod
    def _popup_rois(shift: int) -> dict[str, tuple[int, int, int, int]]:
        """Popup rows moved for a taller or shorter popup (see ``popup_shift``):
        the name row and lock switch move with its top."""
        name_x, name_y, name_w, name_h = DETAIL_NAME_ROW
        lock_x, lock_y, lock_w, lock_h = LOCK_SWITCH_ROI
        return {
            "name": (name_x, name_y + shift, name_w, name_h),
            "lock": (lock_x, lock_y + shift, lock_w, lock_h),
        }

    def _top_title_line(self, detail):
        """Name and rarity from the popup's top line that carries a rarity
        letter: found anywhere in the wide read, whatever the popup's height."""
        rarity_boxes = sorted(
            (b for b in detail
             if ocr_rarity(b.name) is not None or self._name_and_rarity([b])[1] is not None),
            key=lambda b: b.y,
        )
        for candidate in rarity_boxes:
            centre = candidate.y + candidate.height / 2
            line = [b for b in detail if abs(b.y + b.height / 2 - centre) <= NAME_LINE_TOLERANCE]
            name_box, rarity_box = self._name_and_rarity(line)
            if name_box is not None and rarity_box is not None:
                return name_box, rarity_box
        return None, None

    def _read_detail(self) -> tuple[GearItem | None, str]:
        frame = self.capture_frame()
        reference = cv2.resize(frame[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT))
        cross = popup_close_point(reference)
        shift = 0 if cross is None else cross[1] - POPUP_CLOSE_REFERENCE_Y
        row = self._reference_boxes(frame, self._popup_rois(shift)["name"], "装备名称")
        detail = self._reference_boxes(frame, DETAIL_WIDE_ROI, "装备详情")
        whole = self._boxes_text(detail)
        name_box, rarity_box = self._name_and_rarity(row)
        if name_box is None or rarity_box is None:
            # A tight crop can miss the italic rarity letter (live: 掠夺之手 R);
            # the wide detail read has both on the title line.
            name_box, rarity_box = self._top_title_line(detail)
        if name_box is None or rarity_box is None:
            return None, whole
        if cross is None:
            # No ✕ found: the title line found tells how far the popup moved.
            shift = round(name_box.y + name_box.height / 2 - sum(NAME_LINE_Y) / 2)
        rois = self._popup_rois(shift)
        x, y = round(rarity_box.x), round(rarity_box.y)
        w, h = round(rarity_box.width), round(rarity_box.height)
        label = reference[max(0, y - 6) : y + h + 6, max(0, x - 6) : x + w + 6]
        normalized = normalize_ocr_text(whole)
        item = GearItem(
            owner_line=self._owner_line(detail),
            name=str(name_box.name),
            rarity=agreed_rarity(rarity_box.name, label),
            equipped="穿戴中" in normalized or "卸除" in normalized,
            locked=yellow_ratio(crop_reference(frame, rois["lock"])) > YELLOW_ON_RATIO,
            enhanced=bool(re.search(r"\+\d", str(name_box.name)))
            or popup_level_shown(reference)
            or any(word in normalized for word in POPUP_REFINE_WORDS),
        )
        return item, whole

    @staticmethod
    def _owner_line(boxes) -> str | None:
        """Text of the line above 「专用装备」 ("☆艾玛"), None without that line."""
        exclusive = next(
            (b for b in boxes
             if any(k in normalize_ocr_text(b.name) for k in EXCLUSIVE_LINE_KEYWORDS)),
            None,
        )
        if exclusive is None:
            return None
        centre = exclusive.y + exclusive.height / 2
        low, high = OWNER_LINE_DY
        line = sorted(
            (b for b in boxes if low <= b.y + b.height / 2 - centre <= high),
            key=lambda b: b.x,
        )
        return " ".join(str(b.name) for b in line)

    def _classify_detail(self, item: GearItem, stars: dict[str, int]) -> tuple[bool, str]:
        return classify(
            item,
            stars,
            dismantle_r_sr=True,
            # UR is no longer dismantled (Leo 2026-10-11 「只拆 R/SR」); this
            # verdict only serves tools/dev/junk_observe.py.
            dismantle_low_star_ur=False,
            exclusive_owners=_exclusive_owners(),
        )

    def _detail_open(self) -> bool:
        boxes = self._reference_boxes(self.capture_frame(), DETAIL_WIDE_ROI, "详情是否打开")
        return DETAIL_OPEN_KEYWORD in normalize_ocr_text(self._boxes_text(boxes))

    def _wait_detail(self, open_: bool, timeout: float = DETAIL_STATE_TIMEOUT) -> bool:
        end_at = monotonic() + timeout
        while True:
            if self._detail_open() == open_:
                return True
            if monotonic() >= end_at:
                return False
            self.sleep(0.4)

    @staticmethod
    def _name_and_rarity(boxes):
        """The item name box and the rarity box of the title line.

        OCR can glue the rarity to the name ("E.P.G SR") or add a stray mark
        after it ("SR X"), live 2026-09-27 on 拉菲娜's E.P.G: such a box is
        split into its name part and its rarity part.
        """

        ordered = sorted(boxes, key=lambda b: b.x)
        rarity_box = next(
            (
                b for b in ordered
                if ocr_rarity(b.name) is not None and not NON_ASCII.search(str(b.name))
            ),
            None,
        )
        name_box = None
        if rarity_box is None:
            for box in ordered:
                # At 2K the italic letter can touch a Chinese name with no
                # space ("冰雪红宝石R X", live 2026-09-29): split it off.
                parts = GLUED_RARITY.sub(r"\1 \2", str(box.name)).split()
                hit = next((i for i, part in enumerate(parts) if ocr_rarity(part)), None)
                if hit is None:
                    continue
                rarity_box = _part_box(box, parts[hit])
                if hit > 0:
                    name_box = _part_box(box, " ".join(parts[:hit]))
                break
        if name_box is None:
            name_box = next(
                (b for b in ordered if b is not rarity_box and str(b.name).strip()
                 and ocr_rarity(str(b.name).split()[0]) is None),
                None,
            )
        return name_box, rarity_box

    def _grid_rarity(self, frame, cell: tuple[int, int]) -> str | None:
        """R/SR read from the cell label (colour and OCR must agree), else None."""

        row, column = cell
        dx, dy, width, height = GRID_LABEL_BOX
        x, y = GRID_COLUMNS[column] + dx, GRID_ROWS[row] + dy
        label = frame[y : y + height, x : x + width]
        rarity = grid_label_rarity(label)
        if rarity not in ("R", "SR"):
            hues = label_hues(label)
            self.info_set(
                "格子颜色",
                f"{row + 1}-{column + 1} {rarity or '?'} n{hues.size} 绿{hue_share(hues, 35, 84):.2f}"
                f" 青蓝{hue_share(hues, 85, 124):.2f} 紫{hue_share(hues, 125, 165):.2f}",
            )
            return None
        text = self._grid_label_text((x, y, width, height))
        if grid_label_text_matches(text, rarity):
            return rarity
        # Leo 2026-09-30: R/SR should not need opening.  At 2K the letters
        # often read as nothing; an unmistakable blue/purple label with no
        # green (every UR label has green) and no "U" in the read is enough.
        if grid_label_colour_certain(label, rarity) and not label_text_looks_ur(text):
            return rarity
        return None

    def _grid_label_text(self, roi: tuple[int, int, int, int]) -> str:
        """OCR a grid rarity label from the full-resolution frame, enlarged
        to 4K detail with a margin (the 1080p-downscaled crop lost the thin
        italic letters at 2K)."""
        x, y, width, height = roi
        frame = self.capture_frame()
        crop = crop_reference(frame, (x - 4, y - 4, width + 8, height + 8))
        if crop.size == 0:
            return ""
        scale = max(1.0, 2160 / max(1, frame.shape[0]))
        if scale != 1.0:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        padded = cv2.copyMakeBorder(crop[:, :, :3], 20, 20, 20, 20, cv2.BORDER_REPLICATE)
        try:
            boxes = self.ocr(frame=padded, threshold=0.3, target_height=0, log=False, name="格子稀有度", reread=False)
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.info_set("格子稀有度 OCR 错误", str(exc))
            return ""
        text = self._boxes_text(boxes)
        self.info_set("格子稀有度 OCR", text or "-")
        return text

    def _classify_cells(
        self,
        cells: list[tuple[int, int]],
        stars: dict[str, int],
        frame=None,
        grade: str | None = "R",
        fresh: bool = False,
    ) -> list[tuple[int, int]] | None:
        """The junk cells of a bag filtered to ``grade``, or None when a
        detail popup did not open or close.

        The grid rules out locked (never opened), worn and enhanced items
        and any label that is not ``grade``.  R is junk from there; SR is
        opened, because it comes as 5★ exclusives too (classify_low_grade).
        ``grade=None`` (no filter): each cell's own R / SR label, others kept.
        ``fresh``: the cells carry the new-item 「!」 (just drawn, never
        enhanced): the enhance-badge spot is not read (live 2K 2026-10-22,
        a new R next to its 「!」 was kept as 已强化).
        """
        junk: list[tuple[int, int]] = []
        report = []
        self._kept_reasons = []
        badged = self._badged_cells()
        owners = _exclusive_owners()
        five_star_sr = bool(self.config.get(FIVE_STAR_SR_KEY, False))
        for row, column in cells:
            where = f"第{row + 1}行第{column + 1}列"
            if frame is not None and grid_cell_locked(frame, (row, column)):
                report.append(f"{where}:保留[已上锁，不点开]")
                self._kept_reasons.append("上锁")
                continue
            kept = self._older_cell_kept(frame, (row, column), badged, fresh=fresh)
            if kept:
                report.append(f"{where}:保留[{kept}]")
                self._kept_reasons.append(kept)
                continue
            rarity = self._grid_rarity(frame, (row, column)) if frame is not None else None
            wanted = grade or (rarity if rarity in FILTER_GRADES else None)
            if wanted is None or rarity != wanted:
                report.append(f"{where}:保留[格子稀有度{rarity or '认不出'}]")
                self._kept_reasons.append(rarity or "稀有度认不出")
                continue
            if wanted not in OPENED_GRADES or five_star_sr:
                # R is junk off the grid (Leo 2026-10-11 「r不點開」); SR too
                # with 5★ let go (Leo 2026-10-15 「我的意思就是你直接拆sr」).
                report.append(f"{where}:烂装[格子{wanted}]")
                junk.append((row, column))
                continue
            # A stale popup (swallowed close) would make the next click hit
            # it and give this cell the previous item's verdict.
            if not self._wait_detail(False):
                self.log_warning(f"{LABEL}：点击前装备详情未关闭，这次不分解，下次再处理。")
                return None
            opened = self.press_and_confirm(
                f"{LABEL}：打开{where}",
                lambda: self._click_reference(
                    GRID_COLUMNS[column], GRID_ROWS[row], after_sleep=1.3
                ),
                lambda: self._wait_detail(True, timeout=0),
                still_before=lambda: self._wait_detail(False, timeout=0),
                timeout=DETAIL_STATE_TIMEOUT,
                poll=0.4,
            )
            if not opened:
                self.log_warning(f"{LABEL}：{where}的详情没有打开，这次不分解，下次再处理。")
                return None
            item, text = self._read_detail()
            for _retry in range(DETAIL_READ_RETRIES):
                # The popup animates in; the first frame can miss the name row.
                if item is not None:
                    break
                self.sleep(0.7)
                item, text = self._read_detail()
            if item is None:
                verdict, reason, label = False, "详情读取失败", (text[:30] or "-")
            else:
                verdict, reason = classify_low_grade(
                    item, wanted, stars, owners, text, five_star_sr=five_star_sr
                )
                label = f"{item.name}({item.rarity or '?'})"
                if verdict:
                    # Dismantling cannot be undone: a second read must agree.
                    self.sleep(DETAIL_CONFIRM_SECONDS)
                    again, again_text = self._read_detail()
                    verdict, reason = (
                        classify_low_grade(
                            again, wanted, stars, owners, again_text, five_star_sr=five_star_sr
                        )
                        if again is not None
                        else (False, "第二次没读到详情")
                    )
            report.append(f"{label}:{'烂装' if verdict else '保留'}[{reason}]")
            if verdict:
                junk.append((row, column))
            else:
                self._kept_reasons.append(f"{wanted}{reason}")
            if not self._close_detail():
                self.log_warning(f"{LABEL}：装备详情关闭失败，这次不分解，下次再处理。")
                return None
        summary = "；".join(report)
        self.info_set(f"{grade or '不筛选'} 识别", summary)
        self.log_info(f"{LABEL}（{grade or '不筛选'}）：{summary}")
        return junk

    def _close_detail(self) -> bool:
        """Close the item popup: its ✕ where this popup has it, then a tap on
        blank space (Leo 2026-10-12 「點空白處也可以關」), then Esc."""

        def press_close() -> None:
            frame = self.capture_frame()
            point = None
            if frame is not None:
                point = popup_close_point(
                    cv2.resize(frame[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT))
                )
            self._click_reference(*(point or DETAIL_CLOSE_POINT), after_sleep=1.0)

        for label, press in (
            ("关闭装备详情", press_close),
            (
                "点空白处关闭装备详情",
                lambda: self._click_reference(*DETAIL_BLANK_TAP_POINT, after_sleep=1.0),
            ),
            # Leo 2026-10-12 「關不掉 就按ESC做備案」.
            ("按 Esc 关闭装备详情", lambda: self.tap_escape(after_sleep=1.0)),
        ):
            if self.press_and_confirm(
                f"{LABEL}：{label}",
                press,
                lambda: self._wait_detail(False, timeout=0),
                # Only while the popup still shows: without it the ✕ point is
                # the cell at row 2, column 6 and would open another item.
                still_before=lambda: self._wait_detail(True, timeout=0),
                timeout=DETAIL_STATE_TIMEOUT,
                poll=0.4,
            ):
                return True
            if not self._wait_detail(True, timeout=0):
                return True  # gone by now; the next click checks again
        return False

    def _badged_cells(self) -> set[tuple[int, int]] | None:
        """Cells with any number or 「+N」 in the enhance badge spot; None when
        the grid read nothing at all (then no older cell counts as unenhanced)."""
        try:
            boxes = self._grid_boxes(self.capture_frame())
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.info_set("格子强化标记 OCR 错误", str(exc))
            return None
        if not boxes:
            return None
        return badge_text_cells(boxes)

    @staticmethod
    def _older_cell_kept(frame, cell: tuple[int, int], badged, fresh: bool = False) -> str:
        """Why a cell without "!" is kept, or "" when it may be judged
        (``fresh``: a new item, which cannot be enhanced yet)."""
        if frame is None:
            return "没有画面"
        row, column = cell
        if not slot_icon_shown(frame, (GRID_COLUMNS[column], GRID_ROWS[row])):
            return "穿戴中或认不出"
        if fresh:
            return ""
        if badged is None:
            return "格子读不到字"
        if cell in badged or badge_shown(frame, (GRID_COLUMNS[column], GRID_ROWS[row])):
            return "已强化"
        return ""

    # -- enhance ------------------------------------------------------------------------

    def _still_grid_frame(self, timeout: float = 3.0):
        """A reference-size frame once the grid stopped moving (re-sort, scroll)."""
        previous = None
        end_at = monotonic() + timeout
        while True:
            frame = cv2.resize(
                self.capture_frame()[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT)
            )
            small = cv2.resize(frame, (192, 108), interpolation=cv2.INTER_AREA).astype(np.int16)
            if previous is not None and float(np.abs(small - previous).mean()) < 2.0:
                return frame
            if monotonic() >= end_at:
                return frame
            previous = small
            self.sleep(0.3)

    def _selection_count(self) -> int | None:
        text = self._boxes_text(self._roi_boxes(self.capture_frame(), SELECTION_ROI, "已选装备"))
        match = re.search(r"(\d{1,4})\s*/\s*2000", text)
        return int(match.group(1)) if match else None

    def _wait_selection_count(self, wanted: int, timeout: float = 3.0) -> int | None:
        """The N/2000 counter once it shows ``wanted`` (it lags the clicks)."""
        value = None
        end_at = monotonic() + timeout
        while True:
            value = self._selection_count()
            if value == wanted or monotonic() >= end_at:
                return value
            self.sleep(0.4)

    def _enhance_and_dismantle(
        self, cells: list[tuple[int, int]], classified_frame
    ) -> bool | None:
        """True: dismantled.  None: nothing enhanced and back on the bag, so
        the run goes on (Leo 「你不會又點一次沒點到 或者 沒辨識到 又整個失敗吧」).
        False: the screen is not known any more."""
        for attempt in range(SELECTION_ATTEMPTS):
            picked = self._pick_selection(cells, classified_frame, slow=attempt > 0)
            if picked == "picked":
                break
            if picked == "missed":
                return None  # never left the bag
            if picked == "lost" or not self._cancel_selection():
                return False
            if picked != "retry":
                return None
        else:
            self.log_info(f"{LABEL}：选了 {SELECTION_ATTEMPTS} 次件数都不对，这批不分解。")
            return None
        self._click_reference(*SELECTION_CONFIRM_POINT, after_sleep=1.5)
        start = self._enhance_start_box() if self._prepare_enhance_dialog(len(cells)) else None
        if start is None:
            self._click_reference(*ENHANCE_CANCEL_POINT, after_sleep=1.0)
            return None if self._cancel_selection() else False
        self.info_set("当前阶段", "强化并自动分解")
        self._click_reference_box(start, after_sleep=2.5)
        return self._settle_enhance_result(len(cells))

    def _pick_selection(self, cells, classified_frame, slow: bool) -> str:
        """Tap the planned cells.  "picked": N/2000 shows the plan.  "retry":
        another count (cancel and pick again).  "stop": cancel, this batch is
        not dismantled.  "missed": 一键强化 did not open, still on the bag.
        "lost": the screen is neither the bag nor selection mode."""
        self.info_set("当前阶段", f"一键强化：选择 {len(cells)} 件")
        entered = self._enter_selection()
        if entered == "missed":
            self.log_info(f"{LABEL}：一键强化点了两次都没反应，这批不分解。")
            return "missed"
        if entered == "unread":
            self.log_info(f"{LABEL}：选择模式下读不到已选件数，不选，这批不分解。")
            return "stop"
        if entered != "entered":
            return entered  # "retry" or "lost"
        for look in range(3):
            if look:
                self.sleep(0.5)  # the selection overlay may still be fading in
            selection_frame = cv2.resize(
                self.capture_frame()[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT)
            )
            scores = [
                cell_similarity(classified_frame, selection_frame, cell) for cell in cells
            ]
            if min(scores) >= SELECTION_MATCH_MIN:
                break
        self.info_set("选择前格子比对", " ".join(f"{score:.2f}" for score in scores))
        if min(scores) < SELECTION_MATCH_MIN:
            # Selection mode would pick other items than the classified ones
            # (e.g. hidden locked/equipped gear shifting the grid).
            self.log_warning(f"{LABEL}：选择模式下格子与识别时不一致，取消，不分解。")
            return "stop"
        for row, column in cells:
            self._click_reference(
                GRID_COLUMNS[column], GRID_ROWS[row], after_sleep=0.9 if slow else 0.5
            )
        selected = self._wait_selection_count(
            len(cells), timeout=3.0 + (SLOW_PC_GRACE_SECONDS if slow else 0.0)
        )
        if selected == len(cells):
            return "picked"
        self.log_info(f"{LABEL}：已选 {selected} 件，与计划 {len(cells)} 件不符，取消。")
        return "retry"

    def _enter_selection(self) -> str:
        """一键强化 into selection mode.  "entered": N/2000 shows 0.  "retry":
        it shows another count.  "unread": selection mode (一键分解 gone, the
        bar changed) but no count read.  "missed": still the bag after two
        taps.  "lost": anything else."""
        for _tap in range(2):
            before = self._selection_bar()
            self._click_reference(*ONE_CLICK_ENHANCE_POINT, after_sleep=1.0)
            count = self._wait_selection_count(0, timeout=3.0 + SLOW_PC_GRACE_SECONDS)
            if count == 0:
                return "entered"
            if count is not None:
                return "retry"
            text = self._bottom_right_text()
            if "分解" in text:
                continue  # 一键分解 still shows: the tap did not take
            if "取消" in text or bar_changed(before, self._selection_bar()):
                return "unread"
            return "lost"
        return "missed"

    def _selection_bar(self):
        return crop_reference(self.capture_frame(), SELECTION_ROI)

    def _bottom_right_text(self) -> str:
        """一键分解 on the bag; 取消 there in selection mode (same place)."""
        boxes = self._roi_boxes(self.capture_frame(), BOTTOM_RIGHT_BUTTON_ROI, "右下按钮")
        return normalize_ocr_text(self._boxes_text(boxes))

    def _cancel_selection(self) -> bool:
        """取消 out of selection mode; True once the bag shows 一键分解 again.

        Called only when the tool itself opened selection mode: the 取消 spot
        is 一键分解 on the bag, so it is never tapped once 一键分解 reads."""
        if "分解" in self._bottom_right_text():
            return True
        self._click_reference(*SELECTION_CANCEL_POINT, after_sleep=1.0)
        end_at = monotonic() + 3.0 + SLOW_PC_GRACE_SECONDS
        while True:
            if "分解" in self._bottom_right_text():
                return True
            if monotonic() >= end_at:
                return False
            self.sleep(0.4)

    def _prepare_enhance_dialog(self, planned: int) -> bool:
        text = ""

        def dialog_ready() -> bool:
            nonlocal text
            text = normalize_ocr_text(self._dialog_text())
            return "强化设置" in text and re.search(r"总计(\d+)件装备", text) is not None

        self._wait_until(dialog_ready, 5.0)
        match = re.search(r"总计(\d+)件装备", text)
        if "强化设置" not in text or not match or int(match.group(1)) != planned:
            found = match.group(1) if match else "?"
            self.log_info(f"{LABEL}：强化设置件数 {found} 与计划 {planned} 不符。")
            return False
        if not self._enable_auto_dismantle(LABEL):
            return False
        if not self._set_target_level(int(self.config.get("强化目标等级", 7)), LABEL):
            return False
        # The selected count under 已选择装备 must still be the plan.  The
        # header's 总计N件装备 already proved it; an unreadable digit alone
        # (the "4" read "a" at 2K) no longer cancels the run, a different
        # number still does.
        selected = self._lone_number(COUNT_DIGIT_ROI, "已选择装备")
        if selected is None:
            self.info_set("已选择装备", f"读不到，按总计{planned}件继续")
        elif selected != planned:
            self.log_info(f"{LABEL}：已选择装备 {selected} 与计划 {planned} 不符。")
            return False
        return True

    def _settle_enhance_result(self, planned: int) -> bool:
        started = monotonic()
        progress_at = started  # the last result read or tap
        seen_result = False
        blind_tap = False
        # A result that keeps coming back after its tap is still bounded.
        while monotonic() - progress_at <= STUCK_SECONDS and monotonic() - started <= 30.0:
            boxes = self._roi_boxes(self.capture_frame(), RESULT_ROI, "强化结果")
            text = normalize_ocr_text(self._boxes_text(boxes))
            if "分解" in text and ("结果" in text or "已分解" in text):
                seen_result = True
                self.info_set("强化分解结果", text[:80])
                match = re.search(r"已分解共(\d+)个装备", text)
                if match and int(match.group(1)) != planned:
                    self.log_warning(
                        f"{LABEL}：结果显示分解 {match.group(1)} 件，计划 {planned} 件。"
                    )
                self._click_reference(*NEUTRAL_TAP_POINT, after_sleep=1.2)
                progress_at = monotonic()
                continue
            frame = self.capture_frame()
            if (seen_result or blind_tap) and self._title_visible(
                frame, EQUIPMENT_TITLE_KEYWORDS, "背包"
            ):
                if seen_result:
                    self.log_info(f"{LABEL}：已强化并分解 {planned} 件。")
                else:
                    self.log_info(f"{LABEL}：没读到强化结果，点一下空白处后已回到背包。")
                return True
            waited = monotonic() - started
            if not seen_result and not blind_tap and waited >= RESULT_BLIND_TAP_SECONDS:
                # Leo 10-11 fixed-position last resort: the result overlay
                # closes on a tap on blank space; on the bag it is the art.
                blind_tap = True
                self._click_reference(*NEUTRAL_TAP_POINT, after_sleep=1.2)
                progress_at = monotonic()
                continue
            self.sleep(0.8)
        self.log_info(f"{LABEL}：未确认强化分解结果。")
        return False
