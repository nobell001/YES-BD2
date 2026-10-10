from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from time import monotonic

from src.tasks.map_trade import trade_detail
from src.tasks.map_trade.action_icons import COOKING_ICON, SKILL_GROUP_CENTERS_REFERENCE
from src.tasks.map_trade.models import (
    COOKING_RECIPE_TEMPLATES,
    DEFAULT_COOKING_RECIPES,
    FINAL_COOKING_RECIPE,
    OPTIONAL_COOKING_RECIPES,
    MatchResult,
    TemplateSpec,
)
from src.tasks.map_trade.trader_constants import (
    COOK_SUBMENU_TEMPLATE,
    COOKING_BACK_POINT,
    split_items,
)
from src.tasks.map_trade.vision import normalize_text
from src.utils.calibration import FHD_1080
from src.utils.image_utils import to_gray

# The supplied 1920x1080 PC recording shows the complete recipe grid on one
# page.  Every fixed control below is stored as a ratio; recipe and action
# targets themselves are still clicked at their detected centers.
# The cooking skill sits in whichever skill group the player put it (the
# user keeps it in group 1, upstream assumed group 2), so every group is
# tried in turn.
COOKING_SKILL_GROUP_POINTS = tuple(
    (x / FHD_1080.width, y / FHD_1080.height)
    for _group, (x, y) in sorted(SKILL_GROUP_CENTERS_REFERENCE.items())
)
COOKING_LIST_GRID_ROI = (
    700 / FHD_1080.width,
    85 / FHD_1080.height,
    1795 / FHD_1080.width,
    1015 / FHD_1080.height,
)
COOKING_HEADER_ROI = (
    210 / FHD_1080.width,
    15 / FHD_1080.height,
    470 / FHD_1080.width,
    95 / FHD_1080.height,
)
COOKING_DETAIL_NAME_ROI = (
    210 / FHD_1080.width,
    80 / FHD_1080.height,
    680 / FHD_1080.width,
    175 / FHD_1080.height,
)
COOKING_QUANTITY_CHOICES_ROI = (
    205 / FHD_1080.width,
    825 / FHD_1080.height,
    820 / FHD_1080.width,
    930 / FHD_1080.height,
)
COOKING_START_SEARCH_ROI = (
    1000 / FHD_1080.width,
    890 / FHD_1080.height,
    1600 / FHD_1080.width,
    1.0,
)
COOKING_START_BRIGHT_ROI = (
    1090 / FHD_1080.width,
    970 / FHD_1080.height,
    1540 / FHD_1080.width,
    1035 / FHD_1080.height,
)
COOKING_RESULT_ROI = (
    20 / FHD_1080.width,
    420 / FHD_1080.height,
    660 / FHD_1080.width,
    575 / FHD_1080.height,
)
COOKING_BACK_ROI = (
    120 / FHD_1080.width,
    10 / FHD_1080.height,
    215 / FHD_1080.width,
    95 / FHD_1080.height,
)

COOKING_RECIPE_TEMPLATE_SCORE = 0.90
COOKING_RECIPE_PIXEL_SCORE = 0.65
COOKING_START_ENABLED_PIXEL_SCORE = 0.90
COOKING_START_ENABLED_BRIGHT_RATIO = 0.30
COOKING_TEXT_CHARACTER_COVERAGE = 0.75
COOKING_PAGE_TIMEOUT = 10.0
COOKING_START_TIMEOUT = 6.0
COOKING_COMPLETION_TIMEOUT = 40.0
# 切换技能组2后等待 UI 稳定、点击制作料理技能的识别窗口、
# 以及点击数量选项后的停顿。
COOKING_SKILL_GROUP_SWITCH_SETTLE_SECONDS = 0.5
# Per skill group: the icon is either there right after the switch or not.
COOKING_ICON_QUICK_TIMEOUT = 2.0
COOKING_QUANTITY_CLICK_SETTLE_SECONDS = 0.25
COOKING_EXIT_TIMEOUT = 12.0
COOKING_POLL_INTERVAL = 0.25
# Fresh looks at a grey / unclear recipe card before it counts as such.
COOKING_CARD_RELOOKS = 2
# Only the last matched recipe card is checked this long into a list wait.
COOKING_LIST_QUICK_SECONDS = 1.5
COOKING_MAX_CHOICE = "MAX"
COOKING_QUANTITY_ATTEMPTS = 3
COOKING_QUANTITY_VERIFY_SECONDS = 3.0
# A swallowed press (skill icon / recipe card / 开始制作) failed the whole
# phase; after this long with the pre-click screen still read on 2 frames
# the same press is repeated once.
COOKING_RECLICK_AFTER = 3.0
COOKING_RECLICK_HITS = 2

# The PC quantity slider fills white and places its handle at this endpoint
# after MAX takes effect. The template includes the handle and the track cap.
COOKING_MAX_QUANTITY_TEMPLATE = TemplateSpec(
    "料理数量最大值",
    "cooking-quantity-max.png",
    0.95,
    relative_roi=(660 / FHD_1080.width, 968 / FHD_1080.height,
                  730 / FHD_1080.width, 1035 / FHD_1080.height),
    minimum_safe_threshold=0.95,
    min_pixel_score=0.95,
    min_zncc_score=0.95,
)

COOKING_RECIPE_SPECS = {
    recipe: TemplateSpec(
        f"料理-{recipe}",
        COOKING_RECIPE_TEMPLATES[recipe],
        COOKING_RECIPE_TEMPLATE_SCORE,
        relative_roi=COOKING_LIST_GRID_ROI,
        scale_ratios=(0.95, 1.0, 1.05),
        min_pixel_score=COOKING_RECIPE_PIXEL_SCORE,
        minimum_safe_threshold=COOKING_RECIPE_TEMPLATE_SCORE,
    )
    for recipe in COOKING_RECIPE_TEMPLATES
}
# Identity must survive the disabled card's dark overlay.  Brightness is
# evaluated separately so a recognized disabled recipe can be skipped.
COOKING_IDENTITY_SPECS = {
    recipe: replace(spec, min_pixel_score=None, min_zncc_score=0.85)
    for recipe, spec in COOKING_RECIPE_SPECS.items()
}
COOKING_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[3] / "recognition-assets" / "template-assets"
)
COOKING_DETAIL_TEMPLATE = TemplateSpec(
    "料理详情开始控件",
    COOK_SUBMENU_TEMPLATE.file_name,
    COOKING_RECIPE_TEMPLATE_SCORE,
    relative_roi=COOKING_START_SEARCH_ROI,
    scale_ratios=(0.95, 1.0, 1.05),
    min_pixel_score=COOKING_RECIPE_PIXEL_SCORE,
    minimum_safe_threshold=COOKING_RECIPE_TEMPLATE_SCORE,
)
COOKING_BACK_TEMPLATE = TemplateSpec(
    "料理返回按钮",
    "image/green/BackButGe.png",
    0.90,
    relative_roi=COOKING_BACK_ROI,
    minimum_safe_threshold=0.90,
    min_zncc_score=0.80,
)


MAIN_COOKING_RECIPES = (*DEFAULT_COOKING_RECIPES, FINAL_COOKING_RECIPE)


class CookingRecipeOutcome(str, Enum):
    COOKED = "cooked"
    UNAVAILABLE = "unavailable"
    # 列表中未识别到该配方：保持原门禁不放宽，直接跳过制作下一个，
    # 结束时以警报汇总说明（BUG-20260913-04 维护者口径）。
    ABSENT = "absent"
    FAILED = "failed"


@dataclass(frozen=True)
class CookingListSnapshot:
    frame: object
    recipe_match: MatchResult


@dataclass(frozen=True)
class CookingDetailSnapshot:
    frame: object
    start_match: MatchResult
    enabled: bool
    bright_ratio: float


def _character_coverage(expected: str, observed: str) -> float:
    expected_text = normalize_text(expected)
    observed_text = normalize_text(observed)
    if not expected_text:
        return 0.0
    available = Counter(observed_text)
    matched = 0
    for character in expected_text:
        if available[character] <= 0:
            continue
        available[character] -= 1
        matched += 1
    return matched / len(expected_text)


def _has_positive_quantity(text: str) -> bool:
    return any(int(value) > 0 for value in re.findall(r"\d+", normalize_text(text)))


class CookingFlowMixin:
    """Mouse-only cooking flow next to the trade merchant, one proven step at a time."""

    def run_cooking(self) -> bool:
        selected = self._selected_cooking_recipes()
        if not selected:
            self.task.log_info("料理：未选择料理，跳过制作。")
            return True

        unsupported = tuple(
            recipe for recipe in selected if recipe not in COOKING_RECIPE_SPECS
        )
        if unsupported:
            self.task.log_warning(f"料理：配置包含不支持的料理：{'、'.join(unsupported)}。")
            return False

        missing_templates = tuple(
            recipe
            for recipe in selected
            if not (
                COOKING_TEMPLATE_DIR / COOKING_RECIPE_SPECS[recipe].file_name
            ).is_file()
        )
        if missing_templates:
            self.task.log_warning(
                "料理：缺少配方模板，暂不执行本轮："
                f"{'、'.join(missing_templates)}。"
            )
            return False

        # Buying now comes first (user, 2026-09-28: today's ingredients are
        # cooked the same day), and it leaves the shop open.
        if getattr(self, "_buy_completed_in_current_shop", False):
            left = self.navigator.leave_shop_to_merchant()
            self._buy_completed_in_current_shop = False
            if not left.success:
                self.task.log_warning(f"料理：{left.message}")
                return False

        pending = selected

        self._cooking_opened = False
        flow_success = False
        unavailable: list[str] = []
        absent: list[str] = []
        cooked: list[str] = []
        try:
            self._list_snapshot_cache = None
            if self._enter_cooking_list():
                flow_success = True
                for recipe in pending:
                    outcome = self._cook_one_recipe(recipe)
                    if outcome is CookingRecipeOutcome.COOKED:
                        cooked.append(recipe)
                        self._status("料理进度", f"已完成：{'、'.join(cooked)}")
                        continue
                    if outcome is CookingRecipeOutcome.UNAVAILABLE:
                        unavailable.append(recipe)
                        continue
                    if outcome is CookingRecipeOutcome.ABSENT:
                        absent.append(recipe)
                        continue
                    self.task.log_warning(f"料理：{recipe} 未完成，停止后续料理。")
                    flow_success = False
                    break
        finally:
            if self._cooking_opened:
                exited = self._leave_cooking_to_q_sp6()
                flow_success = flow_success and exited
            if unavailable:
                self.task.log_info(
                    "料理：材料不足或按钮不可用，保留为下次重试："
                    f"{'、'.join(unavailable)}。"
                )
            if absent:
                self.task.log_warning(
                    f"当前未识别到食谱：{'、'.join(absent)}",
                    notify=True,
                )
            if cooked:
                self.task.log_info(f"料理：本次已完成 {'、'.join(cooked)}。")
            if not flow_success:
                self._status("料理状态", "失败")
        return flow_success

    def _selected_cooking_recipes(self) -> tuple[str, ...]:
        raw = self.task.config.get("5星料理", [])
        values = (
            split_items(raw)
            if isinstance(raw, str)
            else split_items(tuple(raw or ()))
        )
        optional = tuple(recipe for recipe in OPTIONAL_COOKING_RECIPES if recipe in values)
        # Each regular dish can be unticked (review 2026-09-27: players keep
        # different ingredients); the priority order and 街头烤鸡肉串 last stay.
        raw_main = self.task.config.get("料理清单", list(MAIN_COOKING_RECIPES))
        if isinstance(raw_main, str):
            chosen = set(split_items(raw_main))
        else:
            chosen = set(split_items(tuple(raw_main or ())))
        main = tuple(recipe for recipe in DEFAULT_COOKING_RECIPES if recipe in chosen)
        final = (FINAL_COOKING_RECIPE,) if FINAL_COOKING_RECIPE in chosen else ()
        return (*main, *optional, *final)

    def _enter_cooking_list(self) -> bool:
        arrived = self.navigator.go_to_trade_merchant()
        if not arrived.success:
            self.task.log_warning(f"料理：{arrived.message}")
            return False
        if not self.navigator.wait_for_q_sp6_sandbox(COOKING_EXIT_TIMEOUT):
            self.task.log_warning("料理：未确认站在商人旁的箱庭。")
            return False
        if not self._open_cooking_skill():
            self.task.log_warning("料理：三个技能组中都未稳定识别到制作料理技能。")
            return False
        self._cooking_opened = True
        listed = self._wait_for_cooking_list(COOKING_RECLICK_AFTER)
        if listed is None:
            if self._reclick_cooking_skill():
                self._status("料理状态", "料理列表未出现，技能图标仍在，已补点一次")
            listed = self._wait_for_cooking_list(COOKING_PAGE_TIMEOUT - COOKING_RECLICK_AFTER)
        if listed is None:
            self.task.log_warning("料理：点击制作料理技能后未确认一页式料理列表。")
            return False
        self._status("料理状态", "料理列表已确认")
        return True

    def _open_cooking_skill(self) -> bool:
        """Click the cooking skill, switching skill groups until it shows."""

        if self.vision.click_stable_template(
            COOKING_ICON.template,
            timeout=COOKING_ICON_QUICK_TIMEOUT,
            after_sleep=0.0,
        ):
            return True
        for index, point in enumerate(COOKING_SKILL_GROUP_POINTS, start=1):
            self._status("料理状态", f"切换技能组{index}")
            self.task.operate_click(*point, after_sleep=0.0)
            self.task.sleep(COOKING_SKILL_GROUP_SWITCH_SETTLE_SECONDS)
            if self.vision.click_stable_template(
                COOKING_ICON.template,
                timeout=COOKING_ICON_QUICK_TIMEOUT,
                after_sleep=0.0,
            ):
                return True
        return False

    def _reclick_cooking_skill(self) -> bool:
        """Press the cooking skill again only while it is still stably shown."""

        # click_stable_template agrees over several frames before it clicks;
        # once the list covers the field the icon is gone and nothing is pressed.
        return bool(
            self.vision.click_stable_template(
                COOKING_ICON.template,
                timeout=0.5,
                after_sleep=0.0,
            )
        )

    def _recipe_card_still_listed(self, spec: TemplateSpec) -> tuple[object, MatchResult] | None:
        """The recipe card on 2 list reads in a row (its press was swallowed)."""

        found = None
        for look in range(COOKING_RECLICK_HITS):
            if look:
                self.task.sleep(COOKING_POLL_INTERVAL)
            snapshot = self._cooking_list_snapshot()
            if snapshot is None:
                return None
            match = self.vision.match(snapshot.frame, spec)
            if not self.vision.passes(match, spec):
                return None
            found = (snapshot.frame, match)
        return found

    def _cook_one_recipe(
        self,
        recipe: str,
    ) -> CookingRecipeOutcome:
        # Skipping a grey or absent recipe changes nothing on screen, so the
        # same list frame serves the next recipe: re-reading it for each one
        # matched all 15 recipe templates every time (~4 s per recipe at 4K,
        # live 2026-09-27).  Any click clears the cached frame.
        list_snapshot = getattr(self, "_list_snapshot_cache", None)
        self._list_snapshot_cache = None
        if list_snapshot is None:
            list_snapshot = self._wait_for_cooking_list(2.0)
        if list_snapshot is None:
            self.task.log_warning(f"料理：选择 {recipe} 前料理列表未确认。")
            return CookingRecipeOutcome.FAILED

        spec = COOKING_IDENTITY_SPECS[recipe]
        recipe_match = self.vision.match(list_snapshot.frame, spec)
        if not self.vision.passes(recipe_match, spec):
            # 维护者口径：保持原门禁不放宽，未识别到即跳过并制作下一个，
            # 不降低阈值、不做复扫，结束时的警报统一说明（BUG-20260913-04）。
            self.task.log_info(
                f"料理：一页料理列表中未识别到 {recipe}，跳过并继续后续料理。"
            )
            self._list_snapshot_cache = list_snapshot
            return CookingRecipeOutcome.ABSENT
        enabled = self._cooking_card_enabled(list_snapshot.frame, recipe_match)
        settled = getattr(self, "_settled_list_frame", None) is list_snapshot.frame
        for _look in range(0 if settled else COOKING_CARD_RELOOKS):
            if enabled:
                break
            # Grey or unclear may be a card still fading in (identity passes
            # on a dark card): look again on fresh frames before skipping
            # the dish or failing every later one.
            self.task.sleep(0.5)
            frame = self.vision.capture()
            fresh = self.vision.match(frame, spec)
            if not self.vision.passes(fresh, spec):
                continue
            list_snapshot = CookingListSnapshot(frame, fresh)
            recipe_match = fresh
            enabled = self._cooking_card_enabled(frame, fresh)
            # A frame taken after these waits is past any fade: later dishes
            # judged on the same cached list need no more looks.
            self._settled_list_frame = frame
        if enabled is None:
            # 亮度状态不明确仍是识别失败：退出前保存实际识别原帧供报告取证。
            self._record_recipe_list_evidence(
                list_snapshot.frame,
                recipe,
                spec,
                recipe_match,
            )
            self.task.log_warning(f"料理：{recipe} 图标亮度状态不明确。")
            return CookingRecipeOutcome.FAILED
        if not enabled:
            self.task.log_info(f"料理：{recipe} 列表图标变灰，跳过。")
            self._list_snapshot_cache = list_snapshot
            return CookingRecipeOutcome.UNAVAILABLE
        self._status(
            f"料理-{recipe}点击中心",
            (
                f"center={recipe_match.center}, match={recipe_match.score:.3f}, "
                f"pixel={recipe_match.pixel_score:.3f}"
            ),
        )
        self.vision.click_client(recipe_match.center, list_snapshot.frame.shape, after_sleep=0.0)

        detail = self._wait_for_cooking_detail(recipe, COOKING_RECLICK_AFTER)
        if detail is None:
            still = self._recipe_card_still_listed(spec)
            if still is not None:
                self._status("料理状态", f"{recipe} 详情未出现，列表仍在，补点一次")
                self.vision.click_client(still[1].center, still[0].shape, after_sleep=0.0)
            detail = self._wait_for_cooking_detail(
                recipe, COOKING_PAGE_TIMEOUT - COOKING_RECLICK_AFTER
            )
        if detail is None:
            self.task.log_warning(f"料理：点击 {recipe} 后未确认对应详情页。")
            self._recover_cooking_list()
            return CookingRecipeOutcome.FAILED
        if not detail.enabled:
            self.task.log_info(f"料理：{recipe} 当前材料不足或制作按钮不可用。")
            if not self._return_from_detail_to_list(recipe):
                return CookingRecipeOutcome.FAILED
            return CookingRecipeOutcome.UNAVAILABLE

        ready = self._select_max_cooking_quantity(recipe)
        if ready is None:
            self.task.log_warning(f"料理：{recipe} 未确认 MAX 数量，停止制作。")
            self._recover_cooking_list()
            return CookingRecipeOutcome.FAILED
        self._status(
            f"料理-{recipe}开始点击中心",
            (
                f"center={ready.start_match.center}, "
                f"match={ready.start_match.score:.3f}, "
                f"pixel={ready.start_match.pixel_score:.3f}"
            ),
        )
        self.vision.click_client(
            ready.start_match.center,
            ready.frame.shape,
            after_sleep=0.0,
        )
        if not self._wait_for_cooking_started(recipe, COOKING_START_TIMEOUT):
            self.task.log_warning(f"料理：{recipe} 点击后未确认制作按钮变灰。")
            self._recover_cooking_list()
            return CookingRecipeOutcome.FAILED
        if self._wait_for_cooking_result(recipe, COOKING_COMPLETION_TIMEOUT) is None:
            self.task.log_warning(f"料理：{recipe} 制作超时，未确认结果条。")
            self._recover_cooking_list()
            return CookingRecipeOutcome.FAILED
        trade_detail.note_dish(self, recipe, getattr(self, "_last_cooking_result_text", ""))
        if not self._return_from_detail_to_list(recipe):
            self.task.log_warning(f"料理：{recipe} 结果已确认，但未恢复料理列表。")
            return CookingRecipeOutcome.FAILED
        return CookingRecipeOutcome.COOKED

    def _wait_for_cooking_list(self, timeout: float) -> CookingListSnapshot | None:
        started = monotonic()
        end_at = started + max(0.0, timeout)
        while True:
            # The card that matched last time first; all fifteen only after a
            # moment.  A read while the cards were still fading in scanned all
            # fifteen and cost 3.5 s per dish (live 2K 2026-10-01).
            quick = monotonic() - started < COOKING_LIST_QUICK_SECONDS
            snapshot = self._cooking_list_snapshot(quick=quick)
            if snapshot is not None:
                return snapshot
            if monotonic() >= end_at:
                return None
            self.task.sleep(COOKING_POLL_INTERVAL)

    def _cooking_list_snapshot(self, frame=None, *, quick: bool = False) -> CookingListSnapshot | None:
        frame = self.vision.capture() if frame is None else frame
        # The cheap header read first, then stop at the first recipe card
        # that matches: matching all 15 recipes on every read froze each dish
        # 6-9 s at 2K (live 2026-09-29).  Only the frame is used afterwards.
        header = self.vision.ocr_text(
            frame,
            "料理列表标题",
            relative_roi=COOKING_HEADER_ROI,
            target_height=900,
        )
        if "料理" not in normalize_text(self.vision.simplify(header)):
            return None
        specs = list(COOKING_IDENTITY_SPECS.values())
        last = getattr(self, "_last_list_spec", None)
        if last in specs:
            specs.remove(last)
            specs.insert(0, last)
            if quick:
                specs = [last]
        for spec in specs:
            if not (COOKING_TEMPLATE_DIR / spec.file_name).is_file():
                continue
            result = self.vision.match(frame, spec)
            if self.vision.passes(result, spec):
                self._last_list_spec = spec
                return CookingListSnapshot(frame, result)
        return None

    def _record_recipe_list_evidence(
        self,
        frame,
        recipe: str,
        spec: TemplateSpec,
        recipe_match: MatchResult,
    ) -> None:
        """退出料理页之前保存身份识别失败原帧，报告按 *_failed 收录。"""
        try:
            evidence = self.task.save_frame(f"cooking_{recipe}_failed", frame)
        except Exception as exc:
            self.task.log_warning(f"料理：{recipe} 识别证据帧保存失败：{exc}")
            return
        zncc = getattr(recipe_match, "zncc_score", -1.0)
        self.task.log_warning(
            f"料理：{recipe} 识别证据已保存 {evidence.name}；"
            f"模板={spec.file_name}，"
            f"阈值={spec.threshold:.2f}，"
            f"match={recipe_match.score:.4f}，"
            f"pixel={recipe_match.pixel_score:.4f}，"
            f"zncc={zncc:.4f}。"
        )

    @staticmethod
    def _cooking_card_enabled(frame, match: MatchResult) -> bool | None:
        x, y = match.position
        width, height = match.size
        gray = to_gray(frame)
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            return None
        card = gray[y:y + height, x:x + width]
        if card.shape != (height, width):
            return None
        # The beige card background is shared across dishes, including dark
        # food icons.  Sample its left strip, outside the food and star art.
        strip = card[height // 4:3 * height // 4, :max(1, width // 12)]
        brightness = float(strip.mean())
        if brightness <= 85:
            return False
        if brightness >= 115:
            return True
        return None

    def _wait_for_cooking_detail(
        self,
        recipe: str,
        timeout: float,
    ) -> CookingDetailSnapshot | None:
        end_at = monotonic() + max(0.0, timeout)
        while True:
            snapshot = self._cooking_detail_snapshot(recipe)
            if snapshot is not None:
                return snapshot
            if monotonic() >= end_at:
                return None
            self.task.sleep(COOKING_POLL_INTERVAL)

    def _select_max_cooking_quantity(self, recipe: str) -> CookingDetailSnapshot | None:
        for attempt in range(1, COOKING_QUANTITY_ATTEMPTS + 1):
            if self._click_quantity_choice(recipe, COOKING_MAX_CHOICE):
                ready = self._wait_for_max_detail(recipe, COOKING_QUANTITY_VERIFY_SECONDS)
                if ready is not None:
                    return ready
            self.task.log_info(
                f"料理：{recipe} 第 {attempt}/{COOKING_QUANTITY_ATTEMPTS} 次"
                "未确认数量滑块到达 MAX。"
            )
            # The quantity bar may not have drawn yet: retries back to back
            # spent all three attempts within OCR time.
            self.task.sleep(0.5)
        return None

    def _wait_for_max_detail(
        self,
        recipe: str,
        timeout: float,
    ) -> CookingDetailSnapshot | None:
        end_at = monotonic() + max(0.0, timeout)
        while True:
            snapshot = self._cooking_detail_snapshot(recipe)
            if snapshot is not None and snapshot.enabled:
                quantity = self.vision.match(snapshot.frame, COOKING_MAX_QUANTITY_TEMPLATE)
                if self.vision.passes(quantity, COOKING_MAX_QUANTITY_TEMPLATE):
                    return snapshot
            if monotonic() >= end_at:
                return None
            self.task.sleep(COOKING_POLL_INTERVAL)

    def _cooking_detail_snapshot(
        self,
        recipe: str,
        frame=None,
    ) -> CookingDetailSnapshot | None:
        frame = self.vision.capture() if frame is None else frame
        start = self.vision.match(frame, COOKING_DETAIL_TEMPLATE)
        if not self.vision.passes(start, COOKING_DETAIL_TEMPLATE):
            return None
        header = self.vision.ocr_text(
            frame,
            "料理详情标题",
            relative_roi=COOKING_HEADER_ROI,
            target_height=900,
        )
        if "料理" not in normalize_text(self.vision.simplify(header)):
            return None
        name = self.vision.ocr_text(
            frame,
            f"料理详情-{recipe}",
            relative_roi=COOKING_DETAIL_NAME_ROI,
            target_height=900,
        )
        if (
            _character_coverage(recipe, self.vision.simplify(name))
            < COOKING_TEXT_CHARACTER_COVERAGE
        ):
            return None
        bright_ratio = self.vision.bright_neutral_ratio(
            frame,
            COOKING_START_BRIGHT_ROI,
        )
        enabled = (
            start.pixel_score >= COOKING_START_ENABLED_PIXEL_SCORE
            and bright_ratio >= COOKING_START_ENABLED_BRIGHT_RATIO
        )
        self._status(
            f"料理-{recipe}制作按钮",
            (
                f"{'可用' if enabled else '不可用'}; match={start.score:.3f}; "
                f"pixel={start.pixel_score:.3f}; bright={bright_ratio:.3f}"
            ),
        )
        return CookingDetailSnapshot(frame, start, enabled, bright_ratio)

    def _generic_cooking_detail_snapshot(self, frame=None) -> CookingDetailSnapshot | None:
        frame = self.vision.capture() if frame is None else frame
        start = self.vision.match(frame, COOKING_DETAIL_TEMPLATE)
        if not self.vision.passes(start, COOKING_DETAIL_TEMPLATE):
            return None
        header = self.vision.ocr_text(
            frame,
            "料理详情恢复标题",
            relative_roi=COOKING_HEADER_ROI,
            target_height=900,
        )
        if "料理" not in normalize_text(self.vision.simplify(header)):
            return None
        bright_ratio = self.vision.bright_neutral_ratio(frame, COOKING_START_BRIGHT_ROI)
        return CookingDetailSnapshot(
            frame,
            start,
            (
                start.pixel_score >= COOKING_START_ENABLED_PIXEL_SCORE
                and bright_ratio >= COOKING_START_ENABLED_BRIGHT_RATIO
            ),
            bright_ratio,
        )

    def _click_quantity_choice(self, recipe: str, choice: str) -> bool:
        detail = self._cooking_detail_snapshot(recipe)
        if detail is None or not detail.enabled:
            return False
        wanted = normalize_text(choice)
        boxes = self.vision.ocr_boxes(
            detail.frame,
            f"料理-{recipe}数量选项",
            relative_roi=COOKING_QUANTITY_CHOICES_ROI,
            target_height=900,
        )
        for box in boxes:
            text = normalize_text(self.vision.simplify(str(getattr(box, "name", ""))))
            if text != wanted:
                continue
            attrs = tuple(getattr(box, key, None) for key in ("x", "y", "width", "height"))
            if any(value is None for value in attrs):
                continue
            x, y, width, height = (float(value) for value in attrs)
            center = (round(x + width / 2), round(y + height / 2))
            self._status(f"料理-{recipe}数量点击中心", f"{choice}: center={center}")
            self.vision.click_client(center, detail.frame.shape, after_sleep=0.0)
            self.task.sleep(COOKING_QUANTITY_CLICK_SETTLE_SECONDS)
            return True
        return False

    def _wait_for_cooking_started(self, recipe: str, timeout: float) -> bool:
        started = monotonic()
        end_at = started + max(0.0, timeout)
        bright_hits = 0
        reclicked = False
        while True:
            detail = self._cooking_detail_snapshot(recipe)
            if detail is not None and detail.bright_ratio < COOKING_START_ENABLED_BRIGHT_RATIO:
                self._status("料理状态", f"{recipe} 制作按钮已变灰")
                return True
            if monotonic() >= end_at:
                return False
            # A swallowed 开始 press leaves the button bright at MAX; press it
            # once more only then (a started cook greys it, so never twice).
            bright_hits = bright_hits + 1 if detail is not None and detail.enabled else 0
            if (
                not reclicked
                and bright_hits >= COOKING_RECLICK_HITS
                and monotonic() - started >= COOKING_RECLICK_AFTER
                and self.vision.passes(
                    self.vision.match(detail.frame, COOKING_MAX_QUANTITY_TEMPLATE),
                    COOKING_MAX_QUANTITY_TEMPLATE,
                )
            ):
                reclicked = True
                bright_hits = 0
                self._status("料理状态", f"{recipe} 制作按钮仍亮，补点一次开始")
                self.vision.click_client(
                    detail.start_match.center, detail.frame.shape, after_sleep=0.0
                )
            self.task.sleep(COOKING_POLL_INTERVAL)

    def _wait_for_cooking_result(self, recipe: str, timeout: float):
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        while True:
            frame = self.vision.capture()
            text = self.vision.ocr_text(
                frame,
                f"料理-{recipe}结果",
                relative_roi=COOKING_RESULT_ROI,
                target_height=900,
            )
            last_text = text or last_text
            simplified = self.vision.simplify(text)
            result_confirmed = (
                _has_positive_quantity(simplified)
                and _character_coverage(recipe, simplified)
                >= COOKING_TEXT_CHARACTER_COVERAGE
            )
            if result_confirmed and self._cooking_detail_snapshot(recipe, frame) is not None:
                self._status("料理状态", f"{recipe} 结果已确认：{text}")
                self._last_cooking_result_text = text
                return frame
            if monotonic() >= end_at:
                self.task.log_warning(
                    f"料理：{recipe} 未识别到含料理名和数量的结果条，OCR={last_text or '-'}。"
                )
                return None
            self.task.sleep(COOKING_POLL_INTERVAL)

    def _return_from_detail_to_list(self, recipe: str) -> bool:
        detail = self._wait_for_cooking_detail(recipe, 2.0)
        if detail is None:
            return False
        self._click_cooking_back(detail.frame, context=f"{recipe}详情")
        return self._wait_for_cooking_list(COOKING_PAGE_TIMEOUT) is not None

    def _recover_cooking_list(self) -> bool:
        if self._wait_for_cooking_list(1.0) is not None:
            return True
        detail = self._generic_cooking_detail_snapshot()
        if detail is None:
            return False
        self._click_cooking_back(detail.frame, context="料理详情恢复")
        return self._wait_for_cooking_list(COOKING_PAGE_TIMEOUT) is not None

    def _click_cooking_back(self, frame, *, context: str) -> None:
        back = self.vision.match(frame, COOKING_BACK_TEMPLATE)
        if self.vision.passes(back, COOKING_BACK_TEMPLATE):
            self._status(
                "料理返回按钮",
                (
                    f"{context}: center={back.center}, match={back.score:.3f}, "
                    f"pixel={back.pixel_score:.3f}, zncc={back.zncc_score:.3f}"
                ),
            )
            self.vision.click_client(back.center, frame.shape, after_sleep=0.0)
            return
        self._status("料理返回按钮", f"{context}: 模板未通过，使用已标定相对点")
        self.task.operate_click(*COOKING_BACK_POINT, after_sleep=0.0)

    def _leave_cooking_to_q_sp6(self) -> bool:
        if self.navigator.wait_for_q_sp6_sandbox(0.0):
            self._cooking_opened = False
            return True
        if not self._recover_cooking_list():
            self.task.log_warning("料理：未确认详情页或列表页，未执行盲目返回点击。")
            return False
        list_snapshot = self._wait_for_cooking_list(1.0)
        if list_snapshot is None:
            return False
        self._click_cooking_back(list_snapshot.frame, context="料理列表")
        if not self.navigator.wait_for_q_sp6_sandbox(COOKING_EXIT_TIMEOUT):
            self.task.log_warning("料理：退出后未确认回到商人旁的箱庭。")
            return False
        self._cooking_opened = False
        self._status("料理状态", "已退出到商人旁")
        return True
