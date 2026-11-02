"""Weekly 制作装备: craft one N item, enhance it and let the game dismantle it.

Flow from the user's demonstration on the 简体 client, 2026-09-26: bag →
equipment → 装备制作 → first N recipe (佣兵剑) → 强化设置: 自动分解 ON, target
+5, 装备制作数量 1 → 强化.  With 自动分解 on, 强化 crafts, enhances and
dismantles in one go (135 gold, 3 crafting stones and 3 of each ore for one
N weapon); the result dialog closes with 确认.
"""

from __future__ import annotations

import re
from time import monotonic

from qfluentwidgets import FluentIcon

from src.tasks.claim_page import BACK_BUTTON_POINT, PAGE_TITLE_ROI
from src.tasks.enhance_dialog import (
    ENHANCE_CANCEL_POINT,
    RESULT_ROI,
    EnhanceDialogMixin,
)
from src.tasks.GearTasks import EQUIPMENT_TITLE_KEYWORDS, DailyRefineTask
from src.utils.ocr_utils import normalize_ocr_text
from src.utils.wait_limits import STUCK_SECONDS, StillTimer

# 1920x1080 reference coordinates / ROIs.
BAG_BUTTONS_ROI = (1170, 975, 640, 60)
CRAFT_BUTTON_TEXT = "装备制作"
CRAFT_BUTTON_WAIT_SECONDS = 5.0
CRAFT_TITLE_KEYWORDS = ("装备制作",)
CRAFT_LIST_SCROLL_POINT = (1250 / 1920, 600 / 1080)
# Rarity section headers (SR / R / N) sit in the list's left margin; the
# cells' own rarity letters start at x≈815, outside this strip.
SECTION_HEADER_ROI = (700, 90, 90, 980)
# Live: N header centre (735, 779), first N cell (780, 864).
N_FIRST_CELL_X = 780
N_FIRST_CELL_DY = 85
LIST_VISIBLE_BOTTOM = 1040
# Keep context around the title: a tight crop dropped the lone "N" (live).
RECIPE_TITLE_ROI = (200, 75, 700, 125)
RECIPE_TITLE_LINE_Y = (85, 122)
RECIPE_BUTTONS_ROI = (1000, 975, 650, 70)
ENHANCE_SETTINGS_TEXT = "强化设置"
CRAFT_COUNT_ROW = "装备制作数量"
CRAFT_COST_ROI = (628, 630, 112, 34)
RESULT_CONFIRM_ROI = (820, 770, 280, 60)
RESULT_CONFIRM_POINT = (958, 799)
LABEL = "制作装备"

_CJK = "一-鿿"
CRAFT_RESULT_PATTERN = re.compile(r"已分解在制作的(\d+)个装备中.*?目标强化值的(\d+)个装备")


def n_first_cell(boxes) -> tuple[int, int] | None:
    """First cell of the N section, from the section header's position."""
    headers = [b for b in boxes if normalize_ocr_text(b.name) == "n"]
    if not headers:
        return None
    header = max(headers, key=lambda b: b.y)
    cy = round(header.y + header.height / 2 + N_FIRST_CELL_DY)
    if cy > LIST_VISIBLE_BOTTOM:
        return None
    return N_FIRST_CELL_X, cy


def is_n_recipe(boxes) -> bool:
    """The recipe title line starts with the N rarity letter ("N 佣兵剑")."""
    low, high = RECIPE_TITLE_LINE_Y
    title_line = [b for b in boxes if low <= b.y + b.height / 2 <= high]
    if not title_line:
        return False
    first = normalize_ocr_text(min(title_line, key=lambda b: b.x).name)
    return re.fullmatch(rf"n(?:[{_CJK}].*)?", first) is not None


def parse_craft_result(text: str) -> tuple[int, int] | None:
    """(crafted, dismantled) from the 强化结果 dialog."""
    match = CRAFT_RESULT_PATTERN.search(normalize_ocr_text(text))
    return (int(match.group(1)), int(match.group(2))) if match else None


class NGearCraftMixin:
    """Bag → 装备制作 → first N recipe → 强化 with 自动分解: one N item is
    crafted, enhanced and dismantled.  Shared by the weekly 制作装备 and by
    爛装强化分解 on a day without junk (Leo 2026-10-11)."""

    # -- navigation -----------------------------------------------------------------

    def _title_text(self) -> str:
        boxes = self._roi_boxes(self.capture_frame(), PAGE_TITLE_ROI, "页面标题")
        return normalize_ocr_text(self._boxes_text(boxes))

    def _find_craft_button(self, timeout: float = CRAFT_BUTTON_WAIT_SECONDS):
        """The bag's 「装备制作」 button, waiting for the bottom bar to draw.

        Live 2K 2026-10-05: the 装备 title read 70 ms before the bottom
        buttons were drawn, and a single look failed the weekly craft.
        """

        end_at = monotonic() + timeout
        text = ""
        while True:
            boxes = self._reference_boxes(self.capture_frame(), BAG_BUTTONS_ROI, "背包按钮")
            button = self._box_with(boxes, (CRAFT_BUTTON_TEXT,))
            if button is not None:
                return button
            text = self._boxes_text(boxes) or text
            if monotonic() >= end_at:
                self.info_set("背包按钮 OCR", text or "-")
                return None
            self.sleep(0.4)

    def _open_craft_page(self) -> bool:
        for _attempt in range(3):
            button = self._find_craft_button()
            if button is None:
                self.log_info(f"{LABEL}：背包里找不到「装备制作」按钮。")
                return False
            self._click_reference_box(button, after_sleep=1.5)  # 不用确认：循环三次，没进制作页再点
            if self._wait_for_title("装备制作", CRAFT_TITLE_KEYWORDS, timeout=6.0, quiet=True):
                return True
        return False

    def _open_n_recipe(self) -> bool:
        # N is the last section of the list: scroll to the end first (the
        # page keeps its last position).
        for _attempt in range(2):
            self.scroll_client(
                CRAFT_LIST_SCROLL_POINT, -1, count=30, interval=0.03, after_sleep=1.2
            )
            boxes = self._reference_boxes(self.capture_frame(), SECTION_HEADER_ROI, "装备分区")
            cell = n_first_cell(boxes)
            if cell is not None:
                break
        else:
            self.log_info(f"{LABEL}：装备制作列表里找不到 N 装备分区。")
            return False
        for _attempt in range(3):
            # Click the list cell again only while the recipe page is not
            # open, so a retry never lands on the recipe page's controls.
            self._click_reference(*cell, after_sleep=1.5)
            state = self._recipe_page_state()
            if state == "n":
                return True
            if state == "other":
                return False
        self.log_info(f"{LABEL}：未能打开 N 装备的制作页。")
        return False

    def _recipe_page_state(self) -> str:
        """ "n" (N recipe open), "other" (another recipe open) or "closed"."""
        page_open, title_text = False, ""
        end_at = monotonic() + 4.0
        while monotonic() <= end_at:
            frame = self.capture_frame()
            buttons = self._reference_boxes(frame, RECIPE_BUTTONS_ROI, "制作按钮")
            if self._box_with(buttons, (ENHANCE_SETTINGS_TEXT,)) is not None:
                # The title can lag behind the buttons: give OCR a few reads.
                page_open = True
                title = self._reference_boxes(frame, RECIPE_TITLE_ROI, "制作装备名称")
                title_text = self._boxes_text(title)
                self.info_set("制作装备", title_text or "-")
                if is_n_recipe(title):
                    return "n"
            self.sleep(0.5)
        if page_open:
            self.log_info(f"{LABEL}：选中的不是 N 装备（{title_text or '?'}），不制作。")
            return "other"
        return "closed"

    def _craft_back_to_bag(self) -> bool:
        """Back out of the recipe / list pages until the bag's equipment page."""
        for _attempt in range(4):
            if self._bag_title_within(0.0):
                return True
            self._click_reference(*BACK_BUTTON_POINT, after_sleep=1.0)
            # The bag reloads after a back press: a blank title mid-way is not
            # "still on the recipe", and another press would overshoot to home.
            if self._bag_title_within(3.0):
                return True
        return self._bag_title_within(2.0)

    def _bag_title_within(self, seconds: float) -> bool:
        end_at = monotonic() + seconds
        while True:
            text = self._title_text()
            if "装备" in text and "制作" not in text:
                return True
            if monotonic() >= end_at:
                return False
            self.sleep(0.4)

    # -- craft ------------------------------------------------------------------------

    def _craft(self, target: int, count: int) -> bool:
        settings = self.look_again(
            lambda: self._box_with(
                self._reference_boxes(self.capture_frame(), RECIPE_BUTTONS_ROI, "制作按钮"),
                (ENHANCE_SETTINGS_TEXT,),
            ),
            f"{LABEL}：找「{ENHANCE_SETTINGS_TEXT}」",
        )
        if settings is None:
            return False
        self._click_reference_box(settings, after_sleep=1.5)  # 不用确认：没打开且按钮还在会再按一次
        if not self._wait_dialog():
            # A press the game dropped: 强化设置 only opens a dialog, so it is
            # pressed once more while its button still shows (Leo 2026-11-02).
            again = self._box_with(
                self._reference_boxes(self.capture_frame(), RECIPE_BUTTONS_ROI, "制作按钮"),
                (ENHANCE_SETTINGS_TEXT,),
            )
            if again is None:
                self.log_info(f"{LABEL}：强化设置没有打开。")
                return False
            self.log_info(f"{LABEL}：点了「{ENHANCE_SETTINGS_TEXT}」没打开，再点一次。")
            self._click_reference_box(again, after_sleep=1.5)  # 不用确认：只补这一次
            if not self._wait_dialog():
                self.log_info(f"{LABEL}：强化设置点了两次都没有打开。")
                return False
        ready = (
            self._enable_auto_dismantle(LABEL, CRAFT_COUNT_ROW)
            and self._set_target_level(target, LABEL)
            and self._set_item_count(count, CRAFT_COUNT_ROW, LABEL)
        )
        cost_text = self._boxes_text(
            self._roi_boxes(self.capture_frame(), CRAFT_COST_ROI, "制作费用")
        )
        # The coin icon in front of the amount sometimes reads as a digit.
        cost = (re.findall(r"\d[\d,]*", cost_text) or [""])[-1]
        self.info_set("制作金币", cost or "-")
        if not ready:
            self._cancel_settings()
            return False
        start = self._enhance_start_box()
        if start is None:
            self._cancel_settings()
            return False
        self.info_set("当前阶段", "制作、强化并自动分解")
        self._click_reference_box(start, after_sleep=2.5)  # 不用确认：开始制作会花素材、分解，不重按
        return self._settle_result(count)

    def _cancel_settings(self) -> bool:
        """Cancel 强化设置 and prove it closed; the second click only if still open."""
        for _attempt in range(2):
            self._click_reference(*ENHANCE_CANCEL_POINT, after_sleep=1.0)
            if "强化设置" not in normalize_ocr_text(self._dialog_text()):
                return True
        self.log_warning(f"{LABEL}：强化设置未能关闭。")
        return False

    def _wait_dialog(self) -> bool:
        end_at = monotonic() + 5.0
        while monotonic() <= end_at:
            text = normalize_ocr_text(self._dialog_text())
            if "强化设置" in text and "单个目标强化值" in text:
                return True
            self.sleep(0.5)
        return False

    def _settle_result(self, count: int) -> bool:
        # Up to 30 s while the craft animation moves; a screen still for
        # STUCK_SECONDS is stuck (Leo 2026-10-14 「頂多等8秒到10秒」).
        end_at = monotonic() + 30.0
        seen_result = False
        unread_confirm = 0
        still = StillTimer()
        while monotonic() <= end_at:
            frame = self.capture_frame()
            if still.still_for(frame, monotonic()) >= STUCK_SECONDS:
                self.log_info(f"{LABEL}：画面 {STUCK_SECONDS:.0f} 秒没有变化，没等到制作结果。")
                return False
            text = self._boxes_text(self._roi_boxes(frame, RESULT_ROI, "强化结果"))
            if "强化结果" in text or "分解结果" in text:
                seen_result = True
                self.info_set("制作结果", normalize_ocr_text(text)[:80])
                result = parse_craft_result(text)
                if result is not None and result != (count, count):
                    crafted, dismantled = result
                    self.log_warning(
                        f"{LABEL}：结果显示制作 {crafted} 件、分解 {dismantled} 件，"
                        f"计划 {count} 件。"
                    )
                boxes = self._reference_boxes(frame, RESULT_CONFIRM_ROI, "确认按钮")
                confirm = self._box_with(boxes, ("确认",))
                if confirm is not None:
                    unread_confirm = 0
                    self._click_reference_box(confirm, after_sleep=1.5)  # 不用确认：循环里结果还在就再按确认
                else:
                    # The fixed point only after the result showed twice
                    # without a readable 确认 (not a frame mid-transition).
                    unread_confirm += 1
                    if unread_confirm >= 2:
                        self._click_reference(*RESULT_CONFIRM_POINT, after_sleep=1.5)
                    else:
                        self.sleep(0.8)
                continue
            if seen_result and "制作" in self._title_text():
                self.log_info(f"{LABEL}：已制作、强化并分解 {count} 件 N 装备。")
                return True
            self.sleep(0.8)
        self.log_info(f"{LABEL}：未确认制作结果。")
        return False


class CraftGearTask(NGearCraftMixin, EnhanceDialogMixin, DailyRefineTask):
    claim_log_name = "craft_gear"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "每周制作装备"
        self.description = (
            "背包 → 装备制作 → 第一件 N 装备，开启自动分解、强化到 +5 后按「强化」："
            "制作、强化、分解一次完成（每周任务：制作装备）。只做 N 装备。"
        )
        self.icon = FluentIcon.DEVELOPER_TOOLS
        self.default_config.update(
            {
                "强化目标等级": 5,
                "制作数量": 1,
            }
        )
        self.config_description.update(
            {
                "强化目标等级": "制作后强化到的等级，达到后游戏自动分解。",
                "制作数量": "制作几件 N 装备（1~10）。",
            }
        )
        # The settings box refuses numbers the task would reject anyway.
        self.config_type["强化目标等级"] = {"min": 1, "max": 9}
        self.config_type["制作数量"] = {"min": 1, "max": 10}

    # -- entry ------------------------------------------------------------------

    def run_claim(self) -> bool:
        target = self._setting_in_range("强化目标等级", 5)
        count = self._setting_in_range("制作数量", 1)
        if not self._open_equipment_bag(grid_view=False):
            return self._claim_fail("打开背包装备页")
        if not self._open_craft_page():
            return self._claim_fail("打开装备制作")
        failed_stage = None
        if not self._open_n_recipe():
            failed_stage = "选择 N 装备"
        elif not self._craft(target, count):
            failed_stage = "制作强化"
        if not self._craft_back_to_bag():
            return self._claim_fail(failed_stage or "返回背包")
        home = self._leave_to_home("背包", EQUIPMENT_TITLE_KEYWORDS)
        if failed_stage:
            return self._claim_fail(failed_stage)
        return home

    def _setting_in_range(self, key: str, default: int) -> int:
        """The saved setting, pulled back into the settings box's range.

        Live 4K 2026-10-06: a saved value outside the box's range failed the
        weekly craft at once with 「检查设置失败」, although the box showed a
        value in range. The box can only save values in range, so a stray
        saved value is fixed here and written back instead.
        """

        limits = self.config_type[key]
        low, high = int(limits["min"]), int(limits["max"])
        raw = self.config.get(key, default)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
        fixed = min(max(value, low), high)
        if fixed != raw:
            self.log_info(f"{LABEL}：设置「{key}」为 {raw!r}，超出 {low}~{high}，改用 {fixed}。")
            self.config[key] = fixed
        return fixed
