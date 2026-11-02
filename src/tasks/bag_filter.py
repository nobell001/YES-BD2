"""The bag's 装备筛选 menu: show one grade only, then put the player's
filter back (Leo 2026-10-11 「篩選 r sr 出來」).

Live 4K 2026-10-11 (frames junk-filter-1011-*): the 级别 row is
single-select and applies at once; a grade button reads V≈42 off and
V≈93-98 on.  「查看穿戴中的装备」 is a yellow tick when on.  The filter
stays after the bag closes, so whatever is changed is changed back, also
after a run that stopped half way (saved state file).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from time import monotonic

import cv2

from src.tasks.enhance_dialog import crop_reference
from src.utils import accounts
from src.utils.ocr_utils import normalize_ocr_text

# 1920x1080 reference.
FILTER_BUTTON_POINT = (1710, 100)
FILTER_TITLE_ROI = (840, 240, 240, 60)
FILTER_TITLE_KEYWORDS = ("筛选", "篩選")
GRADE_POINTS = {"N": (529, 608), "R": (647, 608), "SR": (764, 608), "UR": (880, 608)}
# A patch left of each grade letter (the letter itself is coloured).
GRADE_PATCH = (-48, -15, 20, 30)
GRADE_ON_MIN_VALUE = 68
# 分类 row: 专用 / 魔兽 / 制作, the same dark-off / light-on buttons (Leo's 4K
# menu 2026-10-11: off V≈42, 专用 on V≈92).
CATEGORY_POINTS = {"专用": (549, 493), "魔兽": (705, 493), "制作": (860, 493)}
CATEGORY_PATCH = (-62, -15, 20, 30)
# A 分类 tap counts when the button reads the wanted way, or visibly turned
# lighter / darker (as when a filter or HDR moves the on brightness).  Two taps per
# button, then the caller goes on without it (Leo 「你不會又點一次沒點到 或者
# 沒辨識到 又整個失敗吧」).
CATEGORY_TAPS = 2
CATEGORY_SHIFT_MIN = 20.0
WORN_TICK_POINT = (910, 784)
WORN_TICK_BOX = (-12, -12, 24, 24)
WORN_TICK_MIN_YELLOW = 0.30
FILTER_CONFIRM_POINT = (1375, 810)
FILTER_CLOSE_POINT = (1459, 240)
FILTER_WAIT_SECONDS = 3.0
FILTER_STATE_FILE = Path("configs") / "junk_gear_filter.json"
FILTER_STATE_MAX_AGE_SECONDS = 2 * 24 * 3600


def _filter_state_file() -> Path:
    return Path(accounts.scoped(FILTER_STATE_FILE))


def _patch(frame, centre, box):
    dx, dy, w, h = box
    return crop_reference(frame, (centre[0] + dx, centre[1] + dy, w, h))[:, :, :3]


def selected_grade(frame) -> str | None:
    """The one grade the menu shows on, None for none (or unclear)."""
    on = [
        grade for grade, point in GRADE_POINTS.items()
        if (patch := _patch(frame, point, GRADE_PATCH)).size
        and float(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 2].mean()) >= GRADE_ON_MIN_VALUE
    ]
    return on[0] if len(on) == 1 else None


def grade_count(frame) -> int:
    return sum(
        1 for point in GRADE_POINTS.values()
        if (patch := _patch(frame, point, GRADE_PATCH)).size
        and float(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 2].mean()) >= GRADE_ON_MIN_VALUE
    )


def selected_categories(frame) -> list[str]:
    """The 分类 buttons shown on, in menu order."""
    return [
        name for name, point in CATEGORY_POINTS.items()
        if (patch := _patch(frame, point, CATEGORY_PATCH)).size
        and float(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 2].mean()) >= GRADE_ON_MIN_VALUE
    ]


def category_value(frame, name: str) -> float | None:
    """The brightness (V) of one 分类 button, None off screen."""
    patch = _patch(frame, CATEGORY_POINTS[name], CATEGORY_PATCH)
    if patch.size == 0:
        return None
    return float(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 2].mean())


def filter_matches(state: dict | None, wanted: dict) -> bool:
    """``state`` shows ``wanted``; keys ``wanted`` leaves out are not compared
    (a filter saved before 分类 was read has no "categories")."""
    return state is not None and all(state.get(key) == value for key, value in wanted.items())


def worn_shown(frame) -> bool:
    patch = _patch(frame, WORN_TICK_POINT, WORN_TICK_BOX)
    if patch.size == 0:
        return True
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    yellow = (hue >= 15) & (hue <= 35) & (saturation >= 120) & (value >= 150)
    return float(yellow.mean()) >= WORN_TICK_MIN_YELLOW


class BagFilterMixin:
    """Needs capture_frame, sleep, _click_reference and _reference_boxes."""

    # Test hook: never tap a 分类 button, as when 专用 cannot be seen lit.
    category_tick_disabled = False

    def _ticked_categories(self) -> set[str]:
        """分类 buttons this run turned on with a tap that visibly changed
        them, and has not turned off since."""
        return self.__dict__.setdefault("_ticked_category_names", set())

    def _with_ticked_categories(self, state: dict | None) -> dict | None:
        """A button the tool visibly turned on is on, even if its brightness
        stays under the on threshold."""
        if state is None or "categories" not in state:
            return state
        ticked = self._ticked_categories()
        shown = [
            name for name in CATEGORY_POINTS
            if name in state["categories"] or name in ticked
        ]
        return {**state, "categories": shown}

    def _category_value(self, name: str) -> float | None:
        return category_value(self.capture_frame(), name)

    def _tap_category(self, name: str, shown_on: bool) -> None:
        """Tap one 分类 button; a visible change turns ``name`` on in the
        tool's own record when it was not shown on, off when it was."""
        before = self._category_value(name)
        self._click_reference(*CATEGORY_POINTS[name], after_sleep=0.8)  # 不用确认：看按钮变化
        for look in range(3):
            if look:
                self.sleep(0.5)  # a slow PC redraws late
            after = self._category_value(name)
            if before is None or after is None:
                return
            if abs(after - before) >= CATEGORY_SHIFT_MIN:
                ticked = self._ticked_categories()
                if name in ticked or shown_on:
                    ticked.discard(name)
                else:
                    ticked.add(name)
                return

    def _filter_menu_open(self) -> bool:
        boxes = self._reference_boxes(self.capture_frame(), FILTER_TITLE_ROI, "装备筛选")
        text = normalize_ocr_text(" ".join(str(getattr(b, "name", "")) for b in boxes))
        return any(keyword in text for keyword in FILTER_TITLE_KEYWORDS)

    def _wait_filter_menu(self, open_: bool, timeout: float = FILTER_WAIT_SECONDS) -> bool:
        end_at = monotonic() + timeout
        while True:
            if self._filter_menu_open() == open_:
                return True
            if monotonic() >= end_at:
                return False
            self.sleep(0.4)

    def _open_filter_menu(self) -> bool:
        # The button toggles the menu: click again only after a full wait.
        for attempt in range(3):
            if attempt:
                # Another menu may lie over the button.
                close_covering = getattr(self, "_close_covering_menu", None)
                if callable(close_covering):
                    close_covering()
            self._click_reference(*FILTER_BUTTON_POINT, after_sleep=0.8)  # 不用确认：等菜单开
            if self._wait_filter_menu(True):
                self.sleep(0.4)  # the buttons fade in after the title
                return True
        return False

    def _filter_state_now(self) -> dict | None:
        """Two reads in a row that agree, or None."""
        first = self._read_filter_state()
        for _read in range(3):
            self.sleep(0.4)
            again = self._read_filter_state()
            if again is not None and again == first:
                return self._with_ticked_categories(again)
            first = again
        return None

    def _read_filter_state(self) -> dict | None:
        frame = self.capture_frame()
        if grade_count(frame) > 1:
            return None
        return {
            "grade": selected_grade(frame),
            "worn": worn_shown(frame),
            "categories": selected_categories(frame),
        }

    def _close_filter_menu(self, changed: bool) -> bool:
        if changed:
            self._click_reference(*FILTER_CONFIRM_POINT, after_sleep=1.0)  # 不用确认：等菜单关
            if self._wait_filter_menu(False):
                return True
        # ✕ only while the menu shows: under it lies the bag grid.
        if self._filter_menu_open():
            self._click_reference(*FILTER_CLOSE_POINT, after_sleep=1.0)  # 不用确认：等菜单关
        return self._wait_filter_menu(False)

    def _apply_filter(self, wanted: dict) -> bool:
        """With the menu open, tap until the state reads ``wanted``."""
        changed = False
        taps_left = dict.fromkeys(CATEGORY_POINTS, CATEGORY_TAPS)
        for _attempt in range(5):
            state = self._filter_state_now()
            if state is None:
                return False
            if filter_matches(state, wanted):
                return True
            if state["grade"] != wanted["grade"]:
                # Tapping the shown grade turns it off; another switches to it.
                tap = wanted["grade"] or state["grade"]
                self._click_reference(*GRADE_POINTS[tap], after_sleep=0.8)  # 不用确认：重读
                changed = True
            elif state["worn"] != wanted["worn"]:
                self._click_reference(*WORN_TICK_POINT, after_sleep=0.8)  # 不用确认：重读
                changed = True
            elif "categories" in wanted:
                # One differing 分类 button per look: tapping toggles it.
                tap = next(
                    name for name in CATEGORY_POINTS
                    if (name in wanted["categories"]) != (name in state.get("categories", []))
                )
                if self.category_tick_disabled or taps_left[tap] <= 0:
                    return False  # not confirmed: the caller goes on without it
                taps_left[tap] -= 1
                self._tap_category(tap, tap in state.get("categories", []))  # 不用确认：循环里勾选没对上会再点（taps_left 次数内）
                changed = True
        return changed and filter_matches(self._filter_state_now(), wanted)

    def _set_bag_filter(self, wanted: dict) -> bool:
        """Open the menu, set ``wanted`` and close it; False if not sure."""
        if not self._open_filter_menu():
            return False
        before = self._filter_state_now()
        ok = self._apply_filter(wanted)
        closed = self._close_filter_menu(changed=not filter_matches(before, wanted))
        return ok and closed

    def _read_bag_filter(self) -> dict | None:
        """The player's filter, read with the menu opened and closed again."""
        if not self._open_filter_menu():
            return None
        state = self._filter_state_now()
        if not self._close_filter_menu(changed=False):
            return None
        return state

    # -- interrupted runs -----------------------------------------------------

    @staticmethod
    def _saved_filter() -> dict | None:
        try:
            saved = json.loads(_filter_state_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(saved, dict) or not isinstance(saved.get("original"), dict):
            return None
        try:
            if time.time() - float(saved.get("saved", 0)) > FILTER_STATE_MAX_AGE_SECONDS:
                return None
        except (TypeError, ValueError):
            return None
        return saved["original"]

    @staticmethod
    def _save_filter(original: dict) -> None:
        try:
            _filter_state_file().parent.mkdir(parents=True, exist_ok=True)
            _filter_state_file().write_text(
                json.dumps({"original": original, "saved": time.time()}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    @staticmethod
    def _clear_saved_filter() -> None:
        try:
            _filter_state_file().unlink()
        except OSError:
            pass
