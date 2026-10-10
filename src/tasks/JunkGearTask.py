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

import base64
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np
from ok.task.exceptions import FinishedException, TaskDisabledException
from qfluentwidgets import FluentIcon

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
    EQUIPMENT_TITLE_KEYWORDS,
    GRID_COLUMNS,
    GRID_ROWS,
    DailyRefineTask,
)
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils import accounts
from src.utils.colour_check import (
    check_capture_colours,
    distorted_colour_warning,
    last_check,
    remember,
)
from src.utils.image_utils import template_match_response
from src.utils.junk_gear import (
    GearItem,
    agreed_rarity,
    classify,
    grid_label_colour_certain,
    grid_label_rarity,
    hue_share,
    label_hues,
    label_text_looks_ur,
    leading_new_cells,
    load_exclusive_stars,
    ocr_rarity,
)
from src.utils.ocr_utils import normalize_ocr_text
from src.utils.press_confirm import SLOW_PC_GRACE_SECONDS, wait_for

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
DETAIL_NAME_ROW = (480, 325, 520, 60)
NAME_LINE_Y = (335, 372)
DETAIL_CLOSE_POINT = (1419, 325)
LOCK_SWITCH_ROI = (495, 405, 60, 35)
ONE_CLICK_ENHANCE_POINT = (1486, 1004)
SELECTION_ROI = (700, 965, 560, 95)
SELECTION_CANCEL_POINT = (1697, 1005)
SELECTION_CONFIRM_POINT = (1777, 1005)
# Character art on the left: closes the result overlay without hitting a cell.
NEUTRAL_TAP_POINT = (560, 140)
DETAIL_READ_RETRIES = 3
# A junk verdict is read twice this far apart: a 穿戴中 tag or lock drawn late
# on a slow PC would otherwise send the item to auto-dismantle.
DETAIL_CONFIRM_SECONDS = 1.0
LABEL = "爛装强化分解"
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
# 0.90-1.00 against the padlock template, an unlocked one 0.57.
GRID_LOCK_SEARCH_BOX = (-56, -28, 28, 38)
GRID_LOCK_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "recognition-assets" / "template-assets" / "junk" / "grid_lock.png"
)
GRID_LOCK_MIN_SCORE = 0.8
MAX_ITEMS_PER_RUN = 10
# Live 2026-09-26, bag grid vs 一键强化 selection mode: the same cell scored
# 0.85-1.0, a different item 0.14-0.47.
SELECTION_MATCH_MIN = 0.75
# The user's bag sort, saved before switching so a crash or Stop mid-run can
# be undone on the next run.
SORT_STATE_FILE = Path("configs") / "junk_gear_sort.json"
# Sort kinds (sort_category) a label must match to be saved.  An unlisted kind
# still works for the run; only a crash or Stop is not undone next run.
KNOWN_SORT_KINDS = ("获得时间", "强化", "稀有度", "星级", "套装", "级别")
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
PENDING_MATCH_MIN = 0.85
PENDING_SEARCH_CELLS = 16
PENDING_MAX_AGE_SECONDS = 3 * 24 * 3600


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


def grid_cell_locked(frame, cell: tuple[int, int], template=None) -> bool:
    """The cell shows the padlock (1080-reference frame)."""

    if template is None:
        template = cv2.imread(str(GRID_LOCK_TEMPLATE), cv2.IMREAD_GRAYSCALE)
    if template is None:
        return True  # no template: treat every cell as locked, touch nothing
    row, column = cell
    dx, dy, width, height = GRID_LOCK_SEARCH_BOX
    x, y = GRID_COLUMNS[column] + dx, GRID_ROWS[row] + dy
    region = cv2.cvtColor(frame[y : y + height, x : x + width], cv2.COLOR_BGR2GRAY)
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return True
    return float(template_match_response(region, template).max()) >= GRID_LOCK_MIN_SCORE


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


def known_sort_kind(label: str) -> bool:
    return any(similar_sort_text(sort_category(label), kind) for kind in KNOWN_SORT_KINDS)


def active_sort_label(boxes) -> str | None:
    """Only the active sort option shows its direction (…从高到低… / …从晚到早…)."""
    for box in boxes:
        text = sort_label_core(getattr(box, "name", ""))
        if "从" in text and text.endswith("排序"):
            return text
    return None


class JunkGearTask(EnhanceDialogMixin, DailyRefineTask):
    claim_log_name = "junk_gear"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "爛装强化分解"
        self.description = (
            "只处理带黄色!新获得标记的装备：R/SR 与 3★/4★ 角色的 UR 专用装备强化到 +7 并自动分解；"
            "5★ 角色 UR 专用、上锁、穿戴中、已强化的一律保留。"
        )
        self.icon = FluentIcon.DELETE
        self.default_config.update(
            {
                "强化目标等级": 7,
                "最多处理件数": 10,
                "分解R和SR": True,
                "分解3星4星角色的UR专用": True,
            }
        )
        self.config_description.update(
            {
                "强化目标等级": "爛装强化到的等级，达到后游戏自动分解。",
                "最多处理件数": "一次最多处理的新装备件数（带黄色!新获得标记的装备），1~10 件。",
                "分解R和SR": "新获得的 R / SR 装备算爛装。",
                "分解3星4星角色的UR专用": "3★/4★ 角色的 UR 专用装备算爛装；5★ 角色的永远保留。",
            }
        )
        # 1-10 items per run (user, 2026-09-27).
        self.config_type.update({"最多处理件数": {"min": 1, "max": MAX_ITEMS_PER_RUN, "step": 1}})

    # -- entry ------------------------------------------------------------------

    def run_claim(self) -> bool:
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
        original_sort = self._switch_to_newest_first()
        if original_sort is None:
            return self._claim_fail("切换为按获得时间排序")
        ok = True
        failed_stage = "强化分解"
        stopped = False
        try:
            cap = max(1, min(int(self.config.get("最多处理件数", 10)), MAX_ITEMS_PER_RUN))
            frame = self._still_grid_frame()
            cells = leading_new_cells(frame, GRID_COLUMNS, GRID_ROWS, cap)
            if not cells:
                # Opening the bag clears the "!" badges, so a read before
                # they drew would lose those items for good: keep looking.
                looked = {"frame": frame}

                def badges():
                    looked["frame"] = self._still_grid_frame()
                    return leading_new_cells(looked["frame"], GRID_COLUMNS, GRID_ROWS, cap)

                cells = wait_for(badges, SLOW_PC_GRACE_SECONDS, sleep=self.sleep, poll=0.8) or []
                frame = looked["frame"]
            self.info_set("新装备", len(cells))
            # Junk a failed run already judged: opening the bag cleared their
            # "!" badges, so without this they were never handled (live 2K
            # 2026-09-30).
            carried = [cell for cell in self._pending_cells(frame) if cell not in cells]
            if carried:
                self.log_info(f"{LABEL}：接着处理上次未完成的 {len(carried)} 件爛装。")
                cells = sorted(cells + carried)[:cap]
            if not cells:
                self.log_info("爛装强化分解：没有带新获得标记（黄色!）的装备。")
            else:
                junk = self._classify_cells(cells, stars, frame)
                if junk is None:
                    # Their "!" badges are gone: kept for the next run, or a
                    # lost click would drop them for good.
                    ok, failed_stage = False, "识别新装备"
                    self._save_pending(
                        cells, frame, keep_date=any(cell in carried for cell in cells)
                    )
                elif junk and colours_distorted:
                    self.log_info(
                        f"爛装强化分解：画面颜色异常，识别出 {len(junk)} 件爛装，未分解。"
                    )
                elif junk:
                    ok = self._enhance_and_dismantle(junk, frame)
                    if not ok:
                        self._save_pending(
                            junk, frame, keep_date=any(cell in carried for cell in junk)
                        )
            if ok and not colours_distorted:
                self._clear_pending()
        except (TaskDisabledException, FinishedException):
            # Stop means no more clicks; the saved sort is restored next run.
            stopped = True
            raise
        finally:
            if not stopped:
                if self._restore_sort(original_sort):
                    self._clear_saved_sort()
                else:
                    self.log_warning(
                        f"爛装强化分解：未能把背包排序恢复为「{original_sort}」。", notify=True
                    )
        if not stopped:
            self._restore_bag_detail_view()
        if not ok:
            return self._claim_fail(failed_stage)
        return self._leave_to_home("背包", EQUIPMENT_TITLE_KEYWORDS)

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
        check = check_capture_colours(frame)
        if check.distance is None:
            check = last_check() or check
        else:
            remember(check)
        self.info_set("画面颜色", check.detail)
        if check.distorted:
            self.log_warning(f"{LABEL}：{distorted_colour_warning(check)}", notify=True)
        return check.distorted

    # -- carried-over junk ----------------------------------------------------------------

    @staticmethod
    def _cell_icon(frame, cell: tuple[int, int]):
        row, column = cell
        dx, dy, width, height = CELL_ICON_BOX
        x, y = GRID_COLUMNS[column] + dx, GRID_ROWS[row] + dy
        return cv2.cvtColor(frame[y : y + height, x : x + width], cv2.COLOR_BGR2GRAY)

    def _save_pending(
        self, cells: list[tuple[int, int]], frame, keep_date: bool = False
    ) -> None:
        icons = []
        for cell in cells:
            ok, png = cv2.imencode(".png", self._cell_icon(frame, cell))
            if ok:
                icons.append(base64.b64encode(png.tobytes()).decode("ascii"))
        saved = time.time()
        if keep_date:
            # Items carried over keep the date they were first saved: re-dated
            # on every failure, the age limit never ended a repeating failure.
            saved = min(saved, self._pending_saved_at())
        try:
            _pending_file().parent.mkdir(parents=True, exist_ok=True)
            _pending_file().write_text(
                json.dumps({"saved": saved, "icons": icons}), encoding="utf-8"
            )
            self.log_info(f"{LABEL}：{len(icons)} 件爛装这次没分解，已记下，下次接着处理。")
        except OSError as exc:
            self.log_warning(f"{LABEL}：记录未完成的爛装失败：{exc}")

    @staticmethod
    def _pending_saved_at() -> float:
        try:
            data = json.loads(_pending_file().read_text(encoding="utf-8"))
            return float(data.get("saved", time.time()))
        except (OSError, ValueError, TypeError, AttributeError):
            return time.time()

    def _clear_pending(self) -> None:
        try:
            _pending_file().unlink(missing_ok=True)
        except OSError:
            pass

    def _pending_cells(self, frame) -> list[tuple[int, int]]:
        """Cells showing the icons a failed run saved, or [] (all or none)."""
        try:
            data = json.loads(_pending_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if time.time() - float(data.get("saved", 0)) > PENDING_MAX_AGE_SECONDS:
            self._clear_pending()
            return []
        search = [
            (row, column)
            for row in range(len(GRID_ROWS))
            for column in range(len(GRID_COLUMNS))
        ][:PENDING_SEARCH_CELLS]
        found: list[tuple[int, int]] = []
        for encoded in data.get("icons", []):
            try:
                icon = cv2.imdecode(
                    np.frombuffer(base64.b64decode(encoded), np.uint8), cv2.IMREAD_GRAYSCALE
                )
            except (ValueError, cv2.error):
                icon = None
            best, best_cell = -1.0, None
            for cell in search:
                if cell in found:
                    continue
                current = self._cell_icon(frame, cell)
                if icon is None or current.shape != icon.shape:
                    continue
                score = float(template_match_response(current, icon)[0][0])
                if score > best:
                    best, best_cell = score, cell
            if best_cell is None or best < PENDING_MATCH_MIN:
                # The bag changed (sold, dismantled by hand, pushed away):
                # forget the list rather than guess.
                self.log_info(f"{LABEL}：上次记下的爛装已不在背包前列，不再接着处理。")
                self._clear_pending()
                return []
            found.append(best_cell)
        return sorted(found)

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

    def _close_sort_menu(self) -> None:
        self._click_reference(*SORT_MENU_CLOSE_POINT, after_sleep=1.0)

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
        if settled and known_sort_kind(original):
            self._save_sort(original)
        else:
            self.log_info(
                f"{LABEL}：当前排序「{original}」没读稳或不认识，不记下"
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

    def _read_detail(self) -> tuple[GearItem | None, str]:
        frame = self.capture_frame()
        reference = cv2.resize(frame[:, :, :3], (REFERENCE_WIDTH, REFERENCE_HEIGHT))
        row = self._reference_boxes(frame, DETAIL_NAME_ROW, "装备名称")
        detail = self._reference_boxes(frame, DETAIL_ROI, "装备详情")
        whole = self._boxes_text(detail)
        name_box, rarity_box = self._name_and_rarity(row)
        if name_box is None or rarity_box is None:
            # A tight crop can miss the italic rarity letter (live: 掠夺之手 R);
            # the wider detail read has both on the title line.
            low, high = NAME_LINE_Y
            title_line = [b for b in detail if low <= b.y + b.height / 2 <= high]
            name_box, rarity_box = self._name_and_rarity(title_line)
        if name_box is None or rarity_box is None:
            return None, whole
        x, y = round(rarity_box.x), round(rarity_box.y)
        w, h = round(rarity_box.width), round(rarity_box.height)
        label = reference[max(0, y - 6) : y + h + 6, max(0, x - 6) : x + w + 6]
        normalized = normalize_ocr_text(whole)
        item = GearItem(
            name=str(name_box.name),
            rarity=agreed_rarity(rarity_box.name, label),
            equipped="穿戴中" in normalized or "卸除" in normalized,
            locked=yellow_ratio(crop_reference(frame, LOCK_SWITCH_ROI)) > YELLOW_ON_RATIO,
            enhanced=bool(re.search(r"\+\d", str(name_box.name))),
        )
        return item, whole

    def _classify_detail(self, item: GearItem, stars: dict[str, int]) -> tuple[bool, str]:
        return classify(
            item,
            stars,
            dismantle_r_sr=bool(self.config.get("分解R和SR", True)),
            dismantle_low_star_ur=bool(self.config.get("分解3星4星角色的UR专用", True)),
        )

    def _detail_open(self) -> bool:
        boxes = self._reference_boxes(self.capture_frame(), DETAIL_ROI, "详情是否打开")
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
            boxes = self.ocr(frame=padded, threshold=0.3, target_height=0, log=False, name="格子稀有度")
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.info_set("格子稀有度 OCR 错误", str(exc))
            return ""
        text = self._boxes_text(boxes)
        self.info_set("格子稀有度 OCR", text or "-")
        return text

    def _classify_cells(
        self, cells: list[tuple[int, int]], stars: dict[str, int], frame=None
    ) -> list[tuple[int, int]] | None:
        """The junk cells, or None when a detail popup did not open or close."""
        junk: list[tuple[int, int]] = []
        report = []
        for row, column in cells:
            if frame is not None and grid_cell_locked(frame, (row, column)):
                report.append("格子有锁:保留[已上锁，不点开]")
                continue
            # R and SR are always junk (only 5★ UR exclusives are kept): read
            # them off the grid label instead of opening every detail (user,
            # 2026-09-27).  UR or anything unsure is opened as before.
            rarity = self._grid_rarity(frame, (row, column)) if frame is not None else None
            if rarity is not None:
                verdict, reason = classify(
                    GearItem(name="", rarity=rarity, equipped=False, locked=False, enhanced=False),
                    stars,
                    dismantle_r_sr=bool(self.config.get("分解R和SR", True)),
                    dismantle_low_star_ur=bool(self.config.get("分解3星4星角色的UR专用", True)),
                )
                report.append(f"格子{rarity}:{'爛装' if verdict else '保留'}[{reason}]")
                if verdict:
                    junk.append((row, column))
                continue
            # A stale popup (swallowed close) would make the next click hit
            # it and give this cell the previous item's verdict.
            if not self._wait_detail(False):
                self.log_warning(f"{LABEL}：点击前装备详情未关闭，这次不分解，下次再处理。")
                return None
            opened = self.press_and_confirm(
                f"{LABEL}：打开第{row + 1}行第{column + 1}列",
                lambda: self._click_reference(
                    GRID_COLUMNS[column], GRID_ROWS[row], after_sleep=1.3
                ),
                lambda: self._wait_detail(True, timeout=0),
                still_before=lambda: self._wait_detail(False, timeout=0),
                timeout=DETAIL_STATE_TIMEOUT,
                poll=0.4,
            )
            if not opened:
                self.log_warning(
                    f"{LABEL}：第{row + 1}行第{column + 1}列的详情没有打开，"
                    "这次不分解，下次再处理。"
                )
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
                verdict, reason = self._classify_detail(item, stars)
                label = f"{item.name}({item.rarity or '?'})"
                if verdict:
                    # Dismantling cannot be undone: a second read must agree.
                    self.sleep(DETAIL_CONFIRM_SECONDS)
                    again, _text = self._read_detail()
                    verdict, reason = (
                        self._classify_detail(again, stars)
                        if again is not None
                        else (False, "第二次没读到详情")
                    )
            report.append(f"{label}:{'爛装' if verdict else '保留'}[{reason}]")
            if verdict:
                junk.append((row, column))
            closed = self.press_and_confirm(
                f"{LABEL}：关闭装备详情",
                lambda: self._click_reference(*DETAIL_CLOSE_POINT, after_sleep=1.0),
                lambda: self._wait_detail(False, timeout=0),
                # Only while the popup still shows: without it the ✕ point is
                # the cell at row 2, column 6 and would open another item.
                still_before=lambda: self._wait_detail(True, timeout=0),
                timeout=DETAIL_STATE_TIMEOUT,
                poll=0.4,
            )
            if not closed:
                self.log_warning(f"{LABEL}：装备详情关闭失败，这次不分解，下次再处理。")
                return None
        summary = "；".join(report)
        self.info_set("新装备识别", summary)
        self.log_info(f"爛装强化分解：{summary}")
        return junk

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

    def _enhance_and_dismantle(self, cells: list[tuple[int, int]], classified_frame) -> bool:
        self.info_set("当前阶段", f"一键强化：选择 {len(cells)} 件")
        self._click_reference(*ONE_CLICK_ENHANCE_POINT, after_sleep=1.0)
        if self._wait_selection_count(0) != 0:
            self.log_info("爛装强化分解：未进入一键强化选择模式。")
            return False
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
            self._click_reference(*SELECTION_CANCEL_POINT, after_sleep=1.0)
            return False
        for row, column in cells:
            self._click_reference(GRID_COLUMNS[column], GRID_ROWS[row], after_sleep=0.5)
        selected = self._wait_selection_count(len(cells))
        if selected != len(cells):
            self.log_info(f"爛装强化分解：已选 {selected} 件，与计划 {len(cells)} 件不符，取消。")
            self._click_reference(*SELECTION_CANCEL_POINT, after_sleep=1.0)
            return False
        self._click_reference(*SELECTION_CONFIRM_POINT, after_sleep=1.5)
        if not self._prepare_enhance_dialog(len(cells)):
            self._click_reference(*ENHANCE_CANCEL_POINT, after_sleep=1.0)
            self._click_reference(*SELECTION_CANCEL_POINT, after_sleep=1.0)
            return False
        start = self._enhance_start_box()
        if start is None:
            self._click_reference(*ENHANCE_CANCEL_POINT, after_sleep=1.0)
            self._click_reference(*SELECTION_CANCEL_POINT, after_sleep=1.0)
            return False
        self.info_set("当前阶段", "强化并自动分解")
        self._click_reference_box(start, after_sleep=2.5)
        return self._settle_enhance_result(len(cells))

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
        end_at = monotonic() + 30.0
        seen_result = False
        while monotonic() <= end_at:
            boxes = self._roi_boxes(self.capture_frame(), RESULT_ROI, "强化结果")
            text = normalize_ocr_text(self._boxes_text(boxes))
            if "分解" in text and ("结果" in text or "已分解" in text):
                seen_result = True
                self.info_set("强化分解结果", text[:80])
                match = re.search(r"已分解共(\d+)个装备", text)
                if match and int(match.group(1)) != planned:
                    self.log_warning(
                        f"爛装强化分解：结果显示分解 {match.group(1)} 件，计划 {planned} 件。"
                    )
                self._click_reference(*NEUTRAL_TAP_POINT, after_sleep=1.2)
                continue
            frame = self.capture_frame()
            if seen_result and self._title_visible(frame, EQUIPMENT_TITLE_KEYWORDS, "背包"):
                self.log_info(f"爛装强化分解：已强化并分解 {planned} 件。")
                return True
            self.sleep(0.8)
        self.log_info("爛装强化分解：未确认强化分解结果。")
        return False
