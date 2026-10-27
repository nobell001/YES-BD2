"""Read the sell page's 价目表 to learn what is worth selling today.

The user's method (demo 2026-09-27): on the 出售 page press 价目表 and tick
仅显示已拥有的道具.  Every listed item is in the bag; its 当前 row shows
today's rate.  Items at ↑120% today are the only ones worth selling, so the
shops of the other planned items need not be searched at all, and with no
120% row the sell step can stop at once.  The list is sorted by today's rate,
so reading stops at the first row below 120%.

Coordinates are 1920x1080 references measured on the 4K client.
"""

from __future__ import annotations

import re
from time import monotonic

import cv2
import numpy as np

from src.tasks.map_trade.vision import normalize_text
from src.utils.image_utils import relative_roi_frame
from src.utils.press_confirm import press_and_confirm

REF_W, REF_H = 1920, 1080
PRICE_LIST_BUTTON_REGION = (1300, 975, 1560, 1040)  # 价目表 (never 一键出售)
PRICE_LIST_TITLE_REGION = (430, 250, 700, 300)
PRICE_LIST_OPEN_SECONDS = 4.0  # the list's title after a press
PRICE_LIST_ROWS_REGION = (660, 350, 1490, 790)
OWNED_ONLY_CHECKBOX_POINT = (1468, 814)
OWNED_ONLY_CHECKBOX_BOX = (1452, 800, 1484, 830)
PRICE_LIST_CLOSE_POINT = (1480, 252)
PRICE_LIST_SCROLL_X = 1000
# One row is 110 px and 4 rows show.  The list keeps gliding after the
# button is let go: on Leo's 2K PC (2026-10-12) a 300 px drag in 0.5 s moved
# it about 630 px (5.7 rows) and the 5th row (巧克力 at 120%) was never read.
# A shorter, slower drag leaves rows in common with the page before, and a
# page with no row in common is dragged back once (see owned_items_at_max_rate).
PRICE_LIST_SCROLL_FROM_Y = 720
PRICE_LIST_SCROLL_TO_Y = 560
PRICE_LIST_SCROLL_SECONDS = 0.8
PRICE_LIST_BACK_FROM_Y = 450
PRICE_LIST_BACK_TO_Y = 560
# Small steps: more pages before the list runs out of 120% rows.
PRICE_LIST_MAX_PAGES = 6
# Parts of the 价目表 are read this long before a miss counts.
PRICE_LIST_READ_SECONDS = 3.0
CURRENT_LABEL = "当前"
# Columns (1080 reference x): item name, 当前 label, the ↑% badge.
NAME_COLUMN = (740, 1000)
RATE_COLUMN = (1240, 1380)
ROW_TOLERANCE = 30
MAX_RATE_TEXT = "120"
CHECKBOX_GOLD_MIN_RATIO = 0.15


def _center(box) -> tuple[float, float]:
    return (
        float(box.x) + float(box.width) / 2,
        float(box.y) + float(box.height) / 2,
    )


def owned_rates(boxes) -> list[tuple[str, bool]]:
    """(item name, at 120% today) for each 当前 row, top to bottom.

    ``boxes`` are OCR boxes in 1080-reference coordinates.
    """

    currents = sorted(
        (_center(box)[1] for box in boxes if CURRENT_LABEL in normalize_text(box.name)),
    )
    rows = []
    for y in currents:
        rate = [
            normalize_text(box.name)
            for box in boxes
            if RATE_COLUMN[0] <= _center(box)[0] <= RATE_COLUMN[1]
            and abs(_center(box)[1] - y) <= ROW_TOLERANCE / 2
        ]
        names = [
            box
            for box in boxes
            if NAME_COLUMN[0] <= _center(box)[0] <= NAME_COLUMN[1]
            and abs(_center(box)[1] - y) <= ROW_TOLERANCE
            and not re.fullmatch(r"[\d,.]+", normalize_text(box.name))
        ]
        if not names:
            continue
        name = min(names, key=lambda box: abs(_center(box)[1] - y)).name
        at_max = any(MAX_RATE_TEXT in re.sub(r"\D", "", text) for text in rate)
        rows.append((str(name), at_max))
    return rows


def _shares_row(rows: list[tuple[str, bool]], seen: list[str]) -> bool:
    known = {normalize_text(name) for name in seen}
    return any(normalize_text(name) in known for name, _max in rows)


class PriceListMixin:
    def _ref_point(self, x: float, y: float) -> tuple[float, float]:
        return x / REF_W, y / REF_H

    def _ref_boxes(self, frame, region, name: str) -> list:
        height, width = frame.shape[:2]
        left, top, right, bottom = region
        x0, y0, crop = relative_roi_frame(
            frame, (left / REF_W, top / REF_H, right / REF_W, bottom / REF_H)
        )
        scale_x, scale_y = REF_W / width, REF_H / height
        boxes = []
        for box in self.vision.ocr_boxes(crop, name, target_height=0):
            boxes.append(
                type(
                    "RefBox",
                    (),
                    {
                        "name": str(getattr(box, "name", "")),
                        "x": (float(box.x) + x0) * scale_x,
                        "y": (float(box.y) + y0) * scale_y,
                        "width": float(box.width) * scale_x,
                        "height": float(box.height) * scale_y,
                    },
                )()
            )
        return boxes

    def _price_list_open(self) -> bool:
        boxes = self._ref_boxes(self.vision.capture(), PRICE_LIST_TITLE_REGION, "价目表标题")
        return any("价目表" in normalize_text(box.name) for box in boxes)

    def _wait_price_list(self, open_: bool, timeout: float = 4.0) -> bool:
        end_at = monotonic() + timeout
        while True:
            if self._price_list_open() == open_:
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(0.3)

    def _owned_only_ticked(self) -> bool:
        frame = self.vision.capture()
        height, width = frame.shape[:2]
        left, top, right, bottom = OWNED_ONLY_CHECKBOX_BOX
        patch = frame[
            round(top / REF_H * height) : round(bottom / REF_H * height),
            round(left / REF_W * width) : round(right / REF_W * width),
        ]
        if patch.size == 0:
            return False
        hsv = cv2.cvtColor(patch[:, :, :3], cv2.COLOR_BGR2HSV)
        gold = cv2.inRange(hsv, np.array((15, 90, 140)), np.array((35, 255, 255)))
        return float(np.count_nonzero(gold)) / gold.size >= CHECKBOX_GOLD_MIN_RATIO

    def _price_list_button(self):
        boxes = self._ref_boxes(self.vision.capture(), PRICE_LIST_BUTTON_REGION, "价目表按钮")
        return next(
            (
                box
                for box in boxes
                if "价目表" in normalize_text(box.name)
                and "出售" not in normalize_text(box.name)
            ),
            None,
        )

    def _open_price_list(self) -> bool:
        end_at = monotonic() + PRICE_LIST_READ_SECONDS
        while True:
            button = self._price_list_button()
            if button is not None or monotonic() >= end_at:
                break
            self.task.sleep(0.4)
        if button is None:
            return False
        point = self._ref_point(*_center(button))
        # A swallowed press left the shop as it was and the shop search ran
        # instead (YES-BD2 #60): pressed once more while the button shows (an
        # opened list whose title went unread covers it).
        return bool(
            press_and_confirm(
                "卖：价目表",
                lambda: self.task.operate_click(*point, after_sleep=0.8),
                self._price_list_open,
                sleep=self.task.sleep,
                log=self.task.log_info,
                still_before=lambda: self._price_list_button() is not None,
                timeout=PRICE_LIST_OPEN_SECONDS,
            )
        )

    def _close_price_list(self) -> bool:
        self.task.operate_click(*self._ref_point(*PRICE_LIST_CLOSE_POINT), after_sleep=0.6)
        return self._wait_price_list(False)

    def _drag_price_list(self, back: bool = False) -> bool:
        """Show later rows, or with ``back`` a little of the rows above."""

        height, width = self.vision.capture().shape[:2]
        x = round(PRICE_LIST_SCROLL_X / REF_W * width)
        from_y, to_y = (
            (PRICE_LIST_BACK_FROM_Y, PRICE_LIST_BACK_TO_Y)
            if back
            else (PRICE_LIST_SCROLL_FROM_Y, PRICE_LIST_SCROLL_TO_Y)
        )
        return bool(
            self.task.drag_client(
                (x, round(from_y / REF_H * height)),
                (x, round(to_y / REF_H * height)),
                duration=PRICE_LIST_SCROLL_SECONDS,
                after_sleep=0.8,
            )
        )

    def _ticked_within(self, seconds: float) -> bool:
        end_at = monotonic() + seconds
        while True:
            if self._owned_only_ticked():
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(0.3)

    def _settled_rows(self) -> list[tuple[str, bool]]:
        """Rows once two reads agree: the list re-filters after the tick and
        moves after a drag, and one early read decided the whole sale."""

        previous = None
        rows: list[tuple[str, bool]] = []
        end_at = monotonic() + PRICE_LIST_READ_SECONDS
        while True:
            rows = owned_rates(
                self._ref_boxes(self.vision.capture(), PRICE_LIST_ROWS_REGION, "价目表内容")
            )
            if (rows and rows == previous) or monotonic() >= end_at:
                return rows
            previous = rows
            self.task.sleep(0.4)

    def owned_items_at_max_rate(self) -> set[str] | None:
        """Names of bag items at ↑120% today, or None when the list is unreadable."""

        if not self._open_price_list():
            self.task.log_warning("卖：价目表没有打开，改为逐个商店查找。")
            return None
        try:
            # Looked at twice before clicking: a box not drawn yet reads
            # unticked, and the click would untick a ticked one.
            if not self._ticked_within(0.6):
                self.task.operate_click(
                    *self._ref_point(*OWNED_ONLY_CHECKBOX_POINT), after_sleep=0.5
                )
                if not self._ticked_within(2.0):
                    self.task.log_warning("卖：未能勾选「仅显示已拥有的道具」，改为逐个商店查找。")
                    return None
            found: set[str] = set()
            seen: list[str] = []
            for page in range(PRICE_LIST_MAX_PAGES):
                rows = self._settled_rows()
                if page and not rows:
                    # Every row so far was at 120%: the rows below may be too.
                    self.task.log_warning("卖：价目表翻页后没读到内容，改为逐个商店查找。")
                    return None
                if page and not _shares_row(rows, seen):
                    # No row in common with the page before: the list may have
                    # glided past a row, and a row never read is never sold.
                    if not self._drag_price_list(back=True):
                        self.task.log_warning("卖：无法拖动价目表，改为逐个商店查找。")
                        return None
                    rows = self._settled_rows()
                    if rows and not _shares_row(rows, seen):
                        self.task.log_warning("卖：价目表翻页可能漏看了几行，改为逐个商店查找。")
                        return None
                new_rows = [row for row in rows if row[0] not in seen]
                seen.extend(name for name, _max in new_rows)
                found.update(name for name, at_max in rows if at_max)
                listed = "、".join(f"{n}{'↑120' if m else ''}" for n, m in rows)
                self._status("价目表已拥有", listed)
                # Sorted by today's rate: a row below 120% ends the search.
                if not rows or not all(at_max for _name, at_max in rows) or not new_rows:
                    break
                if page + 1 >= PRICE_LIST_MAX_PAGES:
                    # Still all at 120% on the last page: rows below unread.
                    self.task.log_warning("卖：价目表 120% 的商品太多，没看完，改为逐个商店查找。")
                    return None
                if not self._drag_price_list():
                    self.task.log_warning("卖：无法拖动价目表，改为逐个商店查找。")
                    return None
            if not seen:
                # An empty owned list is possible (nothing in the bag), but an
                # unread one is not proof: fall back to the shop search.
                self.task.log_warning("卖：价目表内容未读到，改为逐个商店查找。")
                return None
            return found
        finally:
            if not self._close_price_list():
                self.task.log_warning("卖：价目表关闭失败。")
