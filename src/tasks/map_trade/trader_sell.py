from __future__ import annotations

import re
from dataclasses import replace
from difflib import SequenceMatcher
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np

from src.tasks.map_trade import trade_detail
from src.tasks.map_trade.calendar import (
    SALE_PRICE_REFRESH_HOUR,
    parse_calendar_payload,
    sale_price_calendar_date,
)
from src.tasks.map_trade.data import (
    ITEM_ALIASES,
    SHOP_CARTRIDGE_ROW_INDEX,
    shop_purchase_reference,
)
from src.tasks.map_trade.models import (
    CalendarEntry,
    ScreenState,
)
from src.tasks.map_trade.phase_ledger import PhaseDeferred
from src.tasks.map_trade.sale_days import (
    apply_sale_checklist,
    bundled_sale_days,
    describe_entry,
)
from src.tasks.map_trade.trader_constants import (
    CALENDAR_DIR,
    OWNED_NAME_FUZZY_MIN_CHARS,
    OWNED_NAME_FUZZY_RATIO,
    SALE_120_PERCENT_MARKER_MAX_RESULTS,
    SALE_120_PERCENT_MARKER_PEAK_RADIUS,
    SALE_120_PERCENT_MARKER_TEMPLATE,
    SALE_AVAILABLE_PATTERN,
    SALE_CANDIDATE_SETTLE_RETRIES,
    SALE_CANDIDATE_STILL_MIN,
    SALE_CLOSE_POINT,
    SALE_COMPLETION_INTERVAL,
    SALE_COMPLETION_STABLE_HITS,
    SALE_COMPLETION_TIMEOUT,
    SALE_CONFIRM_POINT,
    SALE_DIALOG_OPEN_MAX_CLICKS,
    SALE_DIALOG_REGION,
    SALE_DIALOG_TIMEOUT,
    SALE_DIALOG_TITLE_REGION,
    SALE_DIALOG_TITLE_STABLE_HITS,
    SALE_EMPTY_NAME_STABLE_HITS,
    SALE_FULL_PAGE_OCR_TARGET_HEIGHT,
    SALE_FULL_PAGE_OCR_TARGET_HEIGHTS,
    SALE_ITEM_LIST_REGION,
    SALE_LIST_DRAG_BOTTOM,
    SALE_LIST_DRAG_SECONDS,
    SALE_LIST_DRAG_TOP,
    SALE_LIST_DRAG_X,
    SALE_LIST_END_DIFF,
    SALE_LIST_MAX_SCROLLS,
    SALE_LIST_SCROLL_WAIT_TIMEOUT,
    SALE_LIST_SETTLE_SECONDS,
    SALE_LIST_TOP_ATTEMPTS,
    SALE_MARKER_MIN_MARGIN,
    SALE_MARKER_OCR_DIGITS,
    SALE_MARKER_RELAXED_PIXEL_SCORE,
    SALE_MARKER_SEARCH_WIDTH,
    SALE_MARKER_VERTICAL_PADDING,
    SALE_MAX_POINT,
    SALE_MIN_POINT,
    SALE_NAME_FRAGMENT_MIN_CHARS,
    SALE_OCR_INTERVAL,
    SALE_OWNED_PATTERN,
    SALE_RESERVE_ADJUST_ATTEMPTS,
    SALE_RESERVE_MIN_SLACK,
    SALE_RESERVE_SLACK_RATIO,
    SALE_SLIDER_REGION,
    SALE_TOAST_ID_PATTERN,
    SELL_MODE_POINT,
    SHOP_MODE_INTERVAL,
    SHOP_MODE_SWITCH_MAX_CLICKS,
    SHOP_MODE_TIMEOUT,
    SHOP_MODE_TITLE_REGION,
    SaleItemCandidate,
)
from src.tasks.map_trade.vision import normalize_text
from src.utils.calibration import FHD_1080
from src.utils.image_utils import relative_roi_frame, template_match_response, to_gray

# 等待单个日历条目全部可售卡片 OCR 确认的总时长与轮询间隔。
SALE_ITEM_CANDIDATES_WAIT_TIMEOUT = 8.0
SALE_ITEM_CANDIDATES_POLL_INTERVAL = 0.5

# The reason a planned item is left unsold because its marker went unread.
UNCONFIRMED_MARKER_REASON = "未确认↑120%标志"


def _with_one_extra_digit(longer: int, shorter: int) -> bool:
    """``longer`` reads as ``shorter`` with one digit added (40245 -> 140245)."""

    a, b = str(longer), str(shorter)
    return len(a) == len(b) + 1 and any(a[:i] + a[i + 1 :] == b for i in range(len(a)))


def owned_name_score(owned_name: str, names: tuple[str, ...]) -> float:
    """How loosely a 价目表 name read by OCR fits one good's names (0.0 is
    no fit).  It fits when it holds a name, is a fragment of at least half a
    name, or (4+ characters) is one character off; the score is similarity,
    so the closest good wins."""

    if not owned_name:
        return 0.0
    best = 0.0
    for name in names:
        if not name:
            continue
        if name == owned_name:
            return 1.0
        ratio = SequenceMatcher(None, name, owned_name).ratio()
        if (
            (len(name) >= SALE_NAME_FRAGMENT_MIN_CHARS and name in owned_name)
            or (
                len(owned_name) >= max(SALE_NAME_FRAGMENT_MIN_CHARS, (len(name) + 1) // 2)
                and owned_name in name
            )
            or (
                min(len(name), len(owned_name)) >= OWNED_NAME_FUZZY_MIN_CHARS
                and ratio >= OWNED_NAME_FUZZY_RATIO
            )
        ):
            best = max(best, ratio)
    return best


def confusable_goods(goods: dict[str, tuple[str, ...]]) -> frozenset[str]:
    """Goods whose own name loosely fits another good (铜块 and 黄铜块,
    巧克力 and 巧克力鸡尾酒, 三文鱼 and 炸三文鱼便当...): only an exact read
    may name them."""

    confusable = set()
    for good, names in goods.items():
        for other, other_names in goods.items():
            if other != good and any(owned_name_score(name, other_names) for name in names):
                confusable.update((good, other))
    return frozenset(confusable)


def owned_name_owner(
    owned_name: str,
    goods: dict[str, tuple[str, ...]],
    exact_only: frozenset[str] = frozenset(),
) -> str | None:
    """The one known good a 价目表 name stands for, or None.  An exact name
    always wins.  A loose read (OCR slip or cut name) counts only for its
    single closest good, and never when it also fits a confusable good:
    dropping it leaves a 120% item unsold, a wrong keep costs one shop visit
    that sells nothing (the shop still checks the name, the ↑120% mark and
    the sale dialog title)."""

    if not owned_name:
        return None
    for good, names in goods.items():
        if owned_name in names:
            return good
    scores = sorted(
        (
            (score, good)
            for good, names in goods.items()
            if (score := owned_name_score(owned_name, names)) > 0.0
        ),
        reverse=True,
    )
    if not scores or any(good in exact_only for _score, good in scores):
        return None
    if len(scores) > 1 and scores[1][0] >= scores[0][0]:
        return None
    return scores[0][1]


class SellFlowMixin:
    # 以下实例状态由 Trader.__init__ 初始化；类级默认值保证裸构造的 mixin（含测试）
    # 也能直接属性访问，替代原先散落的 getattr 兜底。
    _buy_completed_in_current_shop = False
    _last_sale_unavailable = False
    _last_sale_reason = ""
    _last_sale_name_seen = False
    _last_sale_ocr_output = False
    _last_sale_page_empty = False
    _sale_entries_override: list[CalendarEntry] | None = None
    _last_sale_toast_id: int | None = None
    _sale_title_entries: tuple[CalendarEntry, ...] = ()
    _sale_dialog_rejected = False
    _sale_title_catalog_cache: dict[str, set[str]] | None = None

    def run_sell(self) -> bool | PhaseDeferred:
        entries = self._resolve_sale_entries()
        if entries is None:
            self._buy_completed_in_current_shop = False
            return False
        if not entries:
            self._buy_completed_in_current_shop = False
            self._status("未出售商品", "无（当前价表没有可出售商品）")
            self.task.log_info("卖：当前价表没有可出售商品，跳过进入出售页面。")
            return True

        if self._buy_completed_in_current_shop:
            self.task.log_info("卖：买卖同时执行，继续使用当前商店并等待购买结果。")
            if not self._switch_from_completed_buy_to_sell():
                return False
        else:
            # Selling needs no discount: no 砍价 (user, 2026-09-27).
            entered = self.navigator.enter_q_sp6_buy_flow(bargain=False)
            if not entered.success:
                self.task.log_warning(f"卖：{entered.message}")
                return False
            if entered.state != ScreenState.SHOP:
                self.task.log_warning(
                    f"卖：进入商店后状态为{entered.state.value}，未确认商店页，停止出售。"
                )
                return False
            if not self._ensure_sell_page():
                return False
        self._buy_completed_in_current_shop = False
        entries = self._keep_owned_at_max_rate(entries)
        if not entries:
            self._status("未出售商品", "无（背包里没有今天120%的清单商品）")
            self.task.log_info("卖：价目表显示背包里没有今天120%的清单商品，直接结束出售。")
            return True
        self._sale_entries_override = entries
        try:
            return self.sell_max_price_items()
        finally:
            self._sale_entries_override = None

    def _keep_owned_at_max_rate(self, entries: list[CalendarEntry]) -> list[CalendarEntry]:
        """Drop planned items the 价目表 does not show at ↑120% in the bag."""

        owned = self.owned_items_at_max_rate()
        if owned is None:
            return entries  # unreadable list: search the shops as before
        owned_names = {self._normal(name) for name in owned}
        goods = self._known_goods(entries)
        exact_only = confusable_goods(goods)
        owners = {name: owned_name_owner(name, goods, exact_only) for name in owned_names}
        planned = {self._normal(entry.item) for entry in entries}
        keep, missing = [], []
        for entry in entries:
            if self._normal(entry.item) in owners.values():
                keep.append(entry)
            else:
                missing.append(entry.item)
        if missing:
            self._status("价目表未见", "、".join(missing))
            self.task.log_info(f"卖：背包里没有今天120%的{'、'.join(missing)}，不去它们的商店。")
        extra = sorted(name for name, owner in owners.items() if owner not in planned)
        if extra:
            self.task.log_info(f"卖：价目表另有120%但不在今日清单的：{'、'.join(extra)}（不卖）。")
        return keep

    def _known_goods(self, entries: list[CalendarEntry]) -> dict[str, tuple[str, ...]]:
        """Every good's names (bundled 价表, aliases, today's plan), so a
        价目表 name is matched against all goods, not only the planned ones."""

        bundled = parse_calendar_payload(
            (CALENDAR_DIR / "price_calendar.v1.json").read_text(encoding="utf-8")
        )
        sources = [item for items in bundled.days.values() for item in items]
        sources.extend(CalendarEntry(item, "") for item in ITEM_ALIASES)
        sources.extend(self._sale_title_entries)
        sources.extend(entries)
        goods: dict[str, set[str]] = {}
        for item in sources:
            names = goods.setdefault(self._normal(item.item), set())
            for name in (item.item, *item.aliases, *ITEM_ALIASES.get(item.item, ())):
                normalized = self._normal(name)
                if normalized:
                    names.add(normalized)
        return {good: tuple(sorted(names)) for good, names in goods.items() if good}

    def _ensure_sell_page(
        self,
        timeout: float = SHOP_MODE_TIMEOUT,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        switch_clicks = 0
        last_text = ""
        while True:
            frame = self.vision.capture()
            text = self.vision.ocr_text(
                frame,
                "商店买卖页标题",
                relative_roi=SHOP_MODE_TITLE_REGION,
            )
            last_text = text or last_text
            normalized = normalize_text(self.vision.simplify(text))
            if "出售" in normalized:
                self._status("商店页面", "出售")
                return True
            if (
                "购买" in normalized
                and switch_clicks < SHOP_MODE_SWITCH_MAX_CLICKS
            ):
                switch_clicks += 1
                self._status(
                    "商店页面",
                    f"购买→出售 {switch_clicks}/{SHOP_MODE_SWITCH_MAX_CLICKS}",
                )
                self.task.operate_click(*SELL_MODE_POINT, after_sleep=0.5)
                continue
            if monotonic() >= end_at:
                break
            self.task.sleep(SHOP_MODE_INTERVAL)
        self.task.log_warning(
            f"卖：未能通过标题区域确认已切换到出售页面，OCR={last_text or '-'}。"
        )
        return False

    def sell_max_price_items(self) -> bool | PhaseDeferred:
        entries = self._sale_entries_override
        if entries is None:
            entries = self._resolve_sale_entries()
        if entries is None:
            return False
        if not entries:
            self._status("未出售商品", "无（当前价表没有可出售商品）")
            self.task.log_info("卖：当前价表没有可出售商品，跳过出售。")
            return True
        return self._sell_resolved_entries(entries)

    def _resolve_sale_entries(self) -> list[CalendarEntry] | None:
        try:
            market_now = self._current_market_time()
            calendar_date = sale_price_calendar_date(market_now)
            calendar = self.calendar_client.load(
                use_bundled=bool(
                    self.task.config.get("使用程序默认价表", True)
                ),
                use_online=bool(self.task.config.get("使用在线价表", True)),
                manual_text=str(self.task.config.get("自定义最高价表", "")),
            )
            self._status("价表来源", calendar.source)
            self._status("出售价表日期", calendar_date.isoformat())
            self.task.log_info(
                f"卖：当前北京时间{market_now.strftime('%Y-%m-%d %H:%M:%S')}，"
                f"按{calendar_date.isoformat()}最高价表执行（每日"
                f"{SALE_PRICE_REFRESH_HOUR:02d}:00刷新）。"
            )
            entries = list(calendar.entries_for(calendar_date.day))
            self._sale_calendar_date = calendar_date
            self._sale_title_entries = tuple(entries)
            self._sale_title_catalog_cache = None
        except Exception as exc:
            self.task.log_warning(f"价表加载失败，为避免误卖已停止出售：{exc}")
            return None

        sellable = []
        for entry in entries:
            if not entry.sell:
                self.task.log_info(f"卖：{entry.item}标记为不出售，跳过。")
                continue
            sellable.append(entry)

        use_whitelist = bool(self.task.config.get("使用出售白名单", False))
        self._status("出售白名单", "开启" if use_whitelist else "关闭")
        if use_whitelist:
            whitelist = self._sale_whitelist()
            entries = [entry for entry in sellable if self._entry_allowed(entry, whitelist)]
        else:
            entries = sellable
            self.task.log_info("卖：出售白名单已关闭，执行价表中全部允许出售的商品。")

        use_blacklist = bool(self.task.config.get("使用出售黑名单", False))
        self._status("出售黑名单", "开启" if use_blacklist else "关闭")
        if use_blacklist:
            blacklist = self._sale_blacklist()
            allowed_entries = []
            for entry in entries:
                if self._entry_allowed(entry, blacklist):
                    self.task.log_info(f"卖：{entry.item}命中出售黑名单，跳过。")
                    continue
                allowed_entries.append(entry)
            entries = allowed_entries
        entries = self._apply_day_checklist(calendar_date.day, entries)
        if not entries:
            if use_blacklist:
                self.task.log_info("跑商：筛选后没有可出售的最高价物品。")
            elif use_whitelist:
                self.task.log_info("跑商：今天没有白名单内的最高价物品。")
            else:
                self.task.log_info("跑商：今天没有允许出售的最高价物品。")
            return []

        return entries

    def _apply_day_checklist(
        self, day: int, entries: list[CalendarEntry]
    ) -> list[CalendarEntry]:
        """Drop what the user unticked for this date and say what will be sold."""

        bundled = bundled_sale_days().get(day, ())
        keep, dropped = apply_sale_checklist(self.task.config, day, entries, bundled)
        for entry in dropped:
            self.task.log_info(f"卖：{entry.item}在{day}号出售清单中未勾选，不卖。")
        planned = "、".join(describe_entry(entry) for entry in keep) or "无"
        self._status("今日出售", planned)
        self.task.log_info(f"卖：{day}号要卖：{planned}。")
        return keep

    @staticmethod
    def _sell_entry_cartridge_order(entry: CalendarEntry) -> int:
        try:
            return SHOP_CARTRIDGE_ROW_INDEX[
                shop_purchase_reference(entry.shop).shop_id
            ]
        except KeyError:
            return len(SHOP_CARTRIDGE_ROW_INDEX)

    def _sell_resolved_entries(self, entries: list[CalendarEntry]) -> bool | PhaseDeferred:

        failed = []
        unavailable: list[str] = []
        not_sold_details: list[str] = []
        selected_shop = ""
        # 出售会话内卡带列表只向下滚：按卡带全局顺序排序，不依赖价表书写顺序。
        entries = sorted(entries, key=self._sell_entry_cartridge_order)
        self._sell_cartridge_page = None
        for index, entry in enumerate(entries):
            if self._sale_date_changed():
                # Prices refresh daily: later items would use the wrong day's
                # reserve, so they are left for the new day's run.
                rest = "、".join(later.item for later in entries[index:])
                not_sold_details.append(f"{rest}（价表日期已变更）")
                self._status("未出售商品", "、".join(not_sold_details))
                self.task.log_warning(f"卖：出售途中价表已刷新，剩余商品不再出售：{rest}。")
                break
            if entry.shop != selected_shop:
                if not self.select_shop_tab(entry.shop):
                    failed.append(entry)
                    not_sold_details.append(f"{entry.item}（商店卡带选择失败）")
                    self._status("未出售商品", "、".join(not_sold_details))
                    selected_shop = ""
                    continue
                selected_shop = entry.shop
            if not self._sell_entry_with_retry(entry):
                if self._last_sale_unavailable:
                    detail = f"{entry.item}（{self._last_sale_reason}）"
                    unavailable.append(detail)
                    not_sold_details.append(detail)
                    self._status("未出售商品", "、".join(not_sold_details))
                    continue
                failed.append(entry)
                not_sold_details.append(f"{entry.item}（出售执行失败）")
                self._status("未出售商品", "、".join(not_sold_details))
                self.task.log_warning(
                    f"卖：{entry.item}执行过程中断，停止继续处理后续价表商品。"
                )
                break
        if unavailable:
            message = "未出售商品：" + "、".join(unavailable)
            if not failed and len(unavailable) == len(entries):
                # Nothing sold at all is worth a notification: the list, the
                # marker check or the calendar may need attention.
                self.task.log_warning(message, notify=True)
            else:
                self.task.log_warning(message)
        if not not_sold_details:
            self._status("未出售商品", "无")
        if failed:
            self.task.log_warning("最高价出售失败：" + "、".join(entry.item for entry in failed))
            return False
        unconfirmed = [
            detail for detail in unavailable if UNCONFIRMED_MARKER_REASON in detail
        ]
        if unconfirmed:
            # Audit #18: an unread ↑120% marker sold nothing for that item;
            # recorded as sold, it waited for the next day.  Not recorded, the
            # next run tries again (the 价目表 drops what was sold meanwhile).
            return PhaseDeferred(
                "未确认↑120%标志，不记为今日已卖，下次再试：" + "、".join(unconfirmed)
            )
        return True

    def _sell_entry_with_retry(self, entry: CalendarEntry) -> bool:
        """Sell one entry; after a failure, retry it once on the spot.

        A hiccup (a swallowed click, a slow dialog) should cost seconds, not
        the whole day's selling.  No retry when the list cannot be dragged or
        a dialog cannot be proven closed.
        """

        if self._sell_selected_entry(entry):
            return True
        if self._last_sale_unavailable or getattr(self, "_sale_drag_refused", False):
            return False  # skipped, or the retry could not move the list either
        if self._sale_dialog_shown() and not self._close_sale_dialog():
            return False
        self.task.log_info(f"卖：{entry.item}出错，已关闭弹窗，当场重试一次。")
        return self._sell_selected_entry(entry)

    def _sell_selected_entry(self, entry: CalendarEntry) -> bool:
        self._last_sale_unavailable = False
        self._last_sale_reason = ""
        self._last_sale_page_empty = False
        sold_count = 0
        settle_retries = 0
        previous_owned: int | None = None
        self._sale_drag_refused = False
        self._scroll_sale_list_to_top()
        while True:
            located = None if self._sale_drag_refused else self._find_sale_item_candidates(entry)
            if located is None and self._sale_drag_refused:
                # Not "item missing": the list could not be moved, and every
                # later item needs it too, so the sell stops as a failure.
                self._last_sale_unavailable = False
                self._last_sale_reason = "游戏窗口不在最前面，无法拖动出售列表"
                self.task.log_warning(
                    f"卖：{entry.item}需要拖动出售列表，但游戏窗口不在最前面，停止出售。",
                    notify=True,
                )
                return False
            if located is None:
                if sold_count and self._last_sale_page_empty:
                    self._last_sale_unavailable = False
                    self._last_sale_reason = ""
                    self._status(
                        "出售完成确认",
                        f"{entry.item}:已出售{sold_count}组，商品名连续消失",
                    )
                    self.task.log_info(
                        f"卖：{entry.item}商品名连续{SALE_EMPTY_NAME_STABLE_HITS}次未识别到，"
                        f"当前商店页已无剩余可出售组，共出售{sold_count}组。"
                    )
                    return True
                if sold_count:
                    # Already sold at ↑120%; a leftover name without the marker
                    # is never sold at a worse rate, so move on (live
                    # 2026-09-26: a name read right after a drag stopped the day).
                    self.task.log_warning(
                        f"卖：{entry.item}出售后仍可见商品名但120%标志未确认"
                        f"（{self._last_sale_reason or '未知原因'}），"
                        f"已出售{sold_count}组，继续下一项。"
                    )
                    return True
                if not self._last_sale_unavailable:
                    self.task.log_warning(
                        f"卖：{entry.item}商品名与左侧120%局部定位失败："
                        f"{self._last_sale_reason or '未知原因'}，跳过此项。"
                    )
                    # Nothing was clicked for this item: skip it instead of
                    # stopping every later sale.
                    self._last_sale_unavailable = True
                    self._last_sale_reason = (
                        f"{UNCONFIRMED_MARKER_REASON}：{self._last_sale_reason or '未知原因'}"
                    )
                return False

            candidates, frame = located
            candidate = candidates[0]
            if not self._candidate_unmoved(candidate, frame):
                settle_retries += 1
                if settle_retries > SALE_CANDIDATE_SETTLE_RETRIES:
                    self.task.log_warning(f"卖：{entry.item}的位置一直在变化，停止出售。")
                    return False
                self.task.sleep(SALE_LIST_SETTLE_SECONDS)
                continue
            settle_retries = 0
            outcome = self._sell_one_candidate(
                entry,
                candidate,
                frame,
                previous_owned=previous_owned,
            )
            if outcome is None:
                return False
            owned, sold = outcome
            if not sold:
                return True
            sold_count += 1
            previous_owned = owned
            if getattr(self, "_reserve_reached", False):
                # The slider sold down to the reserve: this item is done.
                self._status("出售完成确认", f"{entry.item}:已出售{sold_count}组，留到保留量")
                self.task.log_info(
                    f"卖：{entry.item}已卖到保留量{entry.reserve}附近，共出售{sold_count}组。"
                )
                return True
            if getattr(self, "_last_sale_cleared", False) and not bool(
                self.task.config.get("出售保险", False)
            ):
                self._status("出售完成确认", f"{entry.item}:已出售{sold_count}组，库存已全部卖出")
                self.task.log_info(f"卖：{entry.item}库存已全部卖出，共出售{sold_count}组。")
                return True
            if entry.reserve <= 0 and bool(self.task.config.get("出售保险", False)):
                # 出售保险 sells the minimum once; looping would sell one
                # unit at a time for hours.
                self.task.log_info(f"卖：出售保险开启，{entry.item}只出售一次。")
                return True

    def _sell_one_candidate(
        self,
        entry: CalendarEntry,
        candidate: SaleItemCandidate,
        frame: np.ndarray,
        *,
        previous_owned: int | None,
    ) -> tuple[int, bool] | None:
        """Sell one currently visible card and verify that the page advanced."""

        before_signature = self._sale_name_signature(entry, frame)
        before_toast_id = self._sale_toast_id(frame)
        known_toast_id = self._last_sale_toast_id
        if known_toast_id is not None:
            before_toast_id = max(before_toast_id or 0, known_toast_id)
        dialog_opened = False
        self._sale_dialog_rejected = False
        self._last_sale_cleared = False
        for click_number in range(1, SALE_DIALOG_OPEN_MAX_CLICKS + 1):
            if click_number > 1 and self._sale_dialog_shown():
                # A dialog is up without a confirmed title: the list point may
                # now sit on 出售/MAX, so close it before clicking again.
                if not self._close_sale_dialog():
                    self.task.log_warning(f"卖：{entry.item}出售弹窗无法关闭，停止出售。")
                    return None
            self.vision.click_client(candidate.center, frame.shape, after_sleep=0.5)
            if self._wait_sale_dialog_item(entry):
                dialog_opened = True
                break
            if self._sale_dialog_rejected:
                return None
            if click_number < SALE_DIALOG_OPEN_MAX_CLICKS:
                self.task.log_info(
                    f"卖：{entry.item}第{click_number}次点击后等待"
                    f"{SALE_DIALOG_TIMEOUT:g}秒仍未确认出售弹窗，补点重试。"
                )
        if not dialog_opened:
            self.task.log_warning(f"卖：{entry.item}出售弹窗商品标题未确认。")
            if self._sale_dialog_shown():
                self._close_sale_dialog()
            return None
        owned = self._wait_owned_quantity()
        if owned is None:
            self.task.log_warning(f"卖：{entry.item}出售弹窗未识别到拥有数量。")
            return None
        available = self._wait_available_quantity()
        if available is None:
            self.task.log_warning(f"卖：{entry.item}出售弹窗未识别到可购买数量。")
            return None
        if previous_owned is not None and owned >= previous_owned:
            self.task.log_warning(
                f"卖：{entry.item}出售后拥有数量未下降（当前{owned}，上次{previous_owned}），停止以避免重复出售。"
            )
            return None

        self._status("出售弹窗库存", f"{entry.item}:{owned}")
        self._status("出售当前组上限", f"{entry.item}:{available}")
        self.task.log_info(
            f"卖：{entry.item}出售弹窗记录库存{owned}个，当前组可购买{available}个。"
        )
        self._reserve_reached = False
        if entry.reserve and owned <= entry.reserve + self._reserve_slack(entry.reserve):
            # Within the slack the slider would sell one at a time, over and
            # over (live 2026-10-07: 10137 -> 10136 -> 10135 ... of 兽肉).
            self.task.log_info(
                f"卖：{entry.item}弹窗库存{owned}已在保留量{entry.reserve}附近，关闭弹窗并跳过。"
            )
            if not self._close_sale_dialog():
                self.task.log_warning(f"卖：{entry.item}出售弹窗关闭失败，停止出售。")
                return None
            return owned, False
        if not self._choose_sale_quantity(entry, owned, available):
            return None
        expected_selected = None
        if entry.reserve <= 0:
            expected_selected = (
                1
                if bool(self.task.config.get("出售保险", False))
                else available
            )
        elif owned - available >= entry.reserve:
            expected_selected = available
        if not self._wait_selected_sale_quantity(expected_selected):
            self.task.log_warning(
                f"卖：{entry.item}出售数量未确认（期望{expected_selected or '正数'}，"
                f"当前组上限{available}），停止确认。"
            )
            return None
        self.task.operate_click(*SALE_CONFIRM_POINT, after_sleep=0.5)
        # MAX of a group that covers everything owned leaves nothing to sell;
        # searching the list for more cost ~25 s of drags (live 2026-09-27).
        self._last_sale_cleared = expected_selected == available and available >= owned > 0
        self.task.log_info(
            f"卖：{entry.item}已点击出售，本组最大可出售{available}个，等待交易完成。"
        )
        if not self._wait_sale_completion(
            entry,
            frame,
            before_signature,
            before_toast_id=before_toast_id,
        ):
            return None
        trade_detail.note_sale(
            self, entry.item, getattr(self, "_last_selected_sale_quantity", None)
        )
        return owned, True

    @staticmethod
    def _in_sale_item_list(box, frame_shape) -> bool:
        attrs = tuple(getattr(box, key, None) for key in ("x", "y", "width", "height"))
        if any(value is None for value in attrs):
            return True
        x, y, width, height = (float(value) for value in attrs)
        frame_height, frame_width = frame_shape[:2]
        cx = (x + width / 2) / max(1, frame_width)
        cy = (y + height / 2) / max(1, frame_height)
        left, top, right, bottom = SALE_ITEM_LIST_REGION
        return left <= cx <= right and top <= cy <= bottom

    def _sale_list_view(self) -> np.ndarray:
        frame = self.vision.capture()
        height, width = frame.shape[:2]
        left, top, right, bottom = SALE_ITEM_LIST_REGION
        crop = frame[
            round(top * height) : round(bottom * height),
            round(left * width) : round(right * width),
        ]
        grey = cv2.cvtColor(crop[:, :, :3], cv2.COLOR_BGR2GRAY)
        return cv2.resize(grey, (96, 64), interpolation=cv2.INTER_AREA).astype(np.int16)

    def _move_sale_list(self, direction: int) -> bool:
        """Drag the list: direction < 0 shows lower items, > 0 higher ones.

        The drag uses the real mouse, so it only happens with the game in
        front (returns False otherwise).
        """

        frame = self.vision.capture()
        height, width = frame.shape[:2]
        x = round(SALE_LIST_DRAG_X * width)
        top = round(SALE_LIST_DRAG_TOP * height)
        bottom = round(SALE_LIST_DRAG_BOTTOM * height)
        start, end = ((x, bottom), (x, top)) if direction < 0 else ((x, top), (x, bottom))
        if self.task.drag_client(
            start,
            end,
            duration=SALE_LIST_DRAG_SECONDS,
            after_sleep=SALE_LIST_SETTLE_SECONDS,
        ):
            return True
        self._sale_drag_refused = True
        self._status("出售列表滚动", "游戏窗口不在最前面，未拖动列表")
        return False

    def _scroll_sale_list_to_top(self) -> None:
        """Scroll up until the list stops moving.

        A freshly selected shop tab keeps the previous tab's offset (live
        2026-09-26: the next shop was searched from the bottom).
        """

        for _attempt in range(SALE_LIST_TOP_ATTEMPTS):
            before = self._sale_list_view()
            if not self._move_sale_list(1):
                return
            if float(np.mean(np.abs(self._sale_list_view() - before))) < SALE_LIST_END_DIFF:
                return

    def _find_sale_item_candidates(
        self, entry: CalendarEntry
    ) -> tuple[list[SaleItemCandidate], np.ndarray] | None:
        """Look for the item on the current view, then scroll down the list.

        The name only counts as absent once the list stops moving; a name that
        is on screen but fails the marker check stays a recognition failure.
        """

        located = self._wait_sale_item_candidates(entry)
        if located is not None or self._last_sale_name_seen or not self._last_sale_ocr_output:
            return located
        for page in range(1, SALE_LIST_MAX_SCROLLS + 1):
            before = self._sale_list_view()
            if not self._move_sale_list(-1):
                break
            moved = float(np.mean(np.abs(self._sale_list_view() - before)))
            self._status("出售列表滚动", f"{entry.item}：第{page}次，变化={moved:.1f}")
            if moved < SALE_LIST_END_DIFF:
                break
            # After a drag the list has settled: one read without the name is
            # enough to move on (two cost ~6.5 s a page, live 2K 2026-10-01).
            located = self._wait_sale_item_candidates(
                entry, timeout=SALE_LIST_SCROLL_WAIT_TIMEOUT, empty_hits=1
            )
            if located is not None or self._last_sale_name_seen:
                return located
        return None

    def _wait_sale_item_candidates(
        self,
        entry: CalendarEntry,
        timeout: float = SALE_ITEM_CANDIDATES_WAIT_TIMEOUT,
        interval: float = SALE_ITEM_CANDIDATES_POLL_INTERVAL,
        empty_hits: int = SALE_EMPTY_NAME_STABLE_HITS,
    ) -> tuple[list[SaleItemCandidate], np.ndarray] | None:
        """Wait for all OCR-confirmed sale cards for one calendar entry."""

        end_at = monotonic() + max(0.0, timeout)
        last_reason = ""
        empty_name_hits = 0
        while True:
            frame = self.vision.capture()
            candidates = self._locate_sale_items(entry, frame)
            if candidates:
                self._last_sale_page_empty = False
                return candidates, frame
            last_reason = self._last_sale_reason or ""
            if self._last_sale_name_seen:
                empty_name_hits = 0
            elif self._last_sale_ocr_output:
                empty_name_hits += 1
            else:
                empty_name_hits = 0
            if empty_name_hits >= empty_hits:
                self._last_sale_page_empty = True
                self._last_sale_reason = last_reason
                return None
            if monotonic() >= end_at:
                break
            self.task.sleep(interval)
        self._last_sale_page_empty = empty_name_hits >= empty_hits
        self._last_sale_reason = last_reason
        return None

    @staticmethod
    def _sale_name_matches(
        normalized: str,
        normalized_names: tuple[str, ...],
    ) -> bool:
        if not normalized:
            return False
        return any(
            name
            and (
                name in normalized
                or (
                    len(normalized) >= SALE_NAME_FRAGMENT_MIN_CHARS
                    and normalized in name
                )
            )
            for name in normalized_names
        )

    @classmethod
    def _sale_marker_search_roi(
        cls,
        name_box: object,
        frame_shape: tuple[int, ...],
    ) -> tuple[int, int, int, int] | None:
        geometry = cls._ocr_box_geometry(name_box)
        if geometry is None:
            return None
        x, y, width, height = geometry
        frame_height, frame_width = frame_shape[:2]
        scale_x = frame_width / FHD_1080.width
        scale_y = frame_height / FHD_1080.height
        search_width = round(SALE_MARKER_SEARCH_WIDTH * scale_x)
        padding = round(SALE_MARKER_VERTICAL_PADDING * scale_y)
        left = max(0, round(x) - search_width)
        top = max(0, round(y) - padding)
        right = min(frame_width, round(x))
        bottom = min(frame_height, round(y + height) + padding)
        if right <= left or bottom <= top:
            return None
        return left, top, right - left, bottom - top

    @staticmethod
    def _sale_roi_overlap_ratio(
        first: tuple[int, int, int, int],
        second: tuple[int, int, int, int],
    ) -> float:
        first_left, first_top, first_width, first_height = first
        second_left, second_top, second_width, second_height = second
        intersection_width = max(
            0,
            min(first_left + first_width, second_left + second_width)
            - max(first_left, second_left),
        )
        intersection_height = max(
            0,
            min(first_top + first_height, second_top + second_height)
            - max(first_top, second_top),
        )
        smaller_area = min(
            first_width * first_height,
            second_width * second_height,
        )
        if smaller_area <= 0:
            return 0.0
        return (intersection_width * intersection_height) / smaller_area

    def _sale_template_percent_boxes(
        self,
        frame: np.ndarray,
        search_roi: tuple[int, int, int, int],
        gray_frame: np.ndarray,
        ocr_boxes: list[object] = (),
    ) -> list[object]:
        """Return ↑120% markers only from one item-name-driven ROI."""

        matches = self.vision.match_all(
            frame,
            SALE_120_PERCENT_MARKER_TEMPLATE,
            minimum_score=self.vision.threshold_for(SALE_120_PERCENT_MARKER_TEMPLATE),
            peak_radius=SALE_120_PERCENT_MARKER_PEAK_RADIUS,
            max_results=SALE_120_PERCENT_MARKER_MAX_RESULTS,
            search_roi=search_roi,
            gray_frame=gray_frame,
        )
        if not matches and ocr_boxes:
            relaxed = replace(
                SALE_120_PERCENT_MARKER_TEMPLATE,
                min_pixel_score=SALE_MARKER_RELAXED_PIXEL_SCORE,
            )
            matches = tuple(
                result
                for result in self.vision.match_all(
                    frame,
                    relaxed,
                    minimum_score=self.vision.threshold_for(SALE_120_PERCENT_MARKER_TEMPLATE),
                    peak_radius=SALE_120_PERCENT_MARKER_PEAK_RADIUS,
                    max_results=SALE_120_PERCENT_MARKER_MAX_RESULTS,
                    search_roi=search_roi,
                    gray_frame=gray_frame,
                )
                if self._marker_reads_120(result, ocr_boxes)
            )
        boxes = [
            SimpleNamespace(
                name="↑120%",
                confidence=result.score,
                x=result.position[0],
                y=result.position[1],
                width=result.size[0],
                height=result.size[1],
            )
            for result in matches
        ]
        boxes.sort(key=lambda box: float(box.confidence), reverse=True)
        return boxes

    @classmethod
    def _marker_digits(cls, result, ocr_boxes) -> list[str]:
        """Digits of every OCR box centred on the matched badge."""

        x, y = result.position
        width, height = result.size
        found = []
        for box in ocr_boxes or ():
            center = cls._ocr_box_center(box)
            if center is None:
                continue
            if x <= center[0] <= x + width and y <= center[1] <= y + height:
                found.append(re.sub(r"\D", "", str(getattr(box, "name", ""))))
        return found

    @classmethod
    def _marker_reads_120(cls, result, ocr_boxes) -> bool:
        """OCR over the matched badge contains the digits 120."""

        return any(
            SALE_MARKER_OCR_DIGITS in digits for digits in cls._marker_digits(result, ocr_boxes)
        )

    def _candidate_unmoved(self, candidate: SaleItemCandidate, frame: np.ndarray) -> bool:
        """The name and badge still look as read, just before the click."""

        current = self.vision.capture()
        if current.shape != frame.shape:
            return False
        for box in (candidate.name_box, candidate.percent_box):
            geometry = self._ocr_box_geometry(box)
            if geometry is None:
                return False
            x, y, width, height = (max(0, round(value)) for value in geometry)
            before = to_gray(frame[y : y + height, x : x + width])
            after = to_gray(current[y : y + height, x : x + width])
            if before.size == 0 or before.shape != after.shape:
                return False
            if float(template_match_response(after, before)[0][0]) < SALE_CANDIDATE_STILL_MIN:
                return False
        return True

    def _sale_dialog_text(self, frame: np.ndarray | None = None) -> str:
        if frame is None:
            frame = self.vision.capture()
        return normalize_text(self.vision.simplify(
            self.vision.ocr_text(frame, "出售弹窗", relative_roi=SALE_DIALOG_REGION)
        ))

    def _sale_dialog_shown(self, frame: np.ndarray | None = None) -> bool:
        text = self._sale_dialog_text(frame)
        return "拥有" in text or "可购买" in text

    def _close_sale_dialog(self) -> bool:
        """Close the quantity dialog and prove it closed on two reads."""

        self.task.operate_click(*SALE_CLOSE_POINT, after_sleep=0.5)
        end_at = monotonic() + SALE_DIALOG_TIMEOUT
        closed_hits = 0
        while True:
            text = self._sale_dialog_text()
            closed = bool(text) and "拥有" not in text and "可购买" not in text
            closed_hits = closed_hits + 1 if closed else 0
            if closed_hits >= 2:
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(SALE_OCR_INTERVAL)

    def _sale_date_changed(self) -> bool:
        started = getattr(self, "_sale_calendar_date", None)
        if started is None:
            return False
        return sale_price_calendar_date(self._current_market_time()) != started

    def _locate_sale_items(
        self,
        entry: CalendarEntry,
        frame: np.ndarray,
    ) -> list[SaleItemCandidate]:
        """Return sale cards confirmed by OCR names and marker templates.

        OCR is used only to find candidate item names. The left-side ↑120%
        marker must come from the real rendered template and is paired
        one-to-one with that name. This avoids treating a corrupted numeric OCR
        string such as ``4120%`` as a premium marker.
        """

        names = (entry.item, *entry.aliases, *ITEM_ALIASES.get(entry.item, ()))
        normalized_names = tuple(self._normal(value) for value in names if value)
        saw_item_name = False
        saw_ocr_output = False
        specific_local_failure = False
        last_reason = ""
        gray_frame: np.ndarray | None = None
        searched_roi_results: list[
            tuple[tuple[int, int, int, int], list[object]]
        ] = []
        roi_searches = 0
        reused_rois = 0
        marker_hits = 0
        self._last_sale_name_seen = False
        self._last_sale_ocr_output = False

        for target_height in SALE_FULL_PAGE_OCR_TARGET_HEIGHTS:
            name_boxes: list[object] = []
            ocr_boxes = self.vision.ocr_boxes(
                frame,
                "出售商品列表",
                target_height=target_height,
            )
            if target_height == SALE_FULL_PAGE_OCR_TARGET_HEIGHT:
                self._sale_page_boxes_cache = (frame, list(ocr_boxes))
            saw_ocr_output = saw_ocr_output or bool(ocr_boxes)
            for box in ocr_boxes:
                if not self._in_sale_item_list(box, frame.shape):
                    continue
                text = str(getattr(box, "name", ""))
                normalized = self._normal(text)
                if self._sale_name_matches(normalized, normalized_names):
                    name_boxes.append(box)

            if not name_boxes:
                if not saw_item_name:
                    last_reason = "全画面OCR未识别到商品名"
                continue
            saw_item_name = True

            name_boxes = self._deduplicate_ocr_boxes(name_boxes)
            if not name_boxes:
                last_reason = "全画面OCR商品名框几何无效"
                specific_local_failure = True
                continue

            ordered_names = sorted(
                name_boxes,
                key=lambda box: (
                    self._ocr_box_center(box) or (10**9, 10**9)
                )[1:],
            )
            candidates: list[SaleItemCandidate] = []
            for name_box in ordered_names:
                center = self._ocr_box_center(name_box)
                if center is None:
                    continue
                search_roi = self._sale_marker_search_roi(name_box, frame.shape)
                if search_roi is None:
                    last_reason = "商品名或局部模板框几何无效"
                    specific_local_failure = True
                    continue

                cached_boxes = next(
                    (
                        boxes
                        for searched_roi, boxes in searched_roi_results
                        if self._sale_roi_overlap_ratio(search_roi, searched_roi) >= 0.90
                    ),
                    None,
                )
                if cached_boxes is None:
                    if gray_frame is None:
                        gray_frame = to_gray(frame)
                    percent_boxes = self._deduplicate_ocr_boxes(
                        self._sale_template_percent_boxes(
                            frame,
                            search_roi,
                            gray_frame,
                            ocr_boxes,
                        )
                    )
                    searched_roi_results.append((search_roi, percent_boxes))
                    roi_searches += 1
                    marker_hits += len(percent_boxes)
                else:
                    roi_left, roi_top, roi_width, roi_height = search_roi
                    roi_right = roi_left + roi_width
                    roi_bottom = roi_top + roi_height
                    percent_boxes = [
                        box
                        for box in cached_boxes
                        if roi_left <= box.x
                        and roi_top <= box.y
                        and box.x + box.width <= roi_right
                        and box.y + box.height <= roi_bottom
                    ]
                    reused_rois += 1

                if not percent_boxes:
                    if not specific_local_failure:
                        last_reason = "商品名左侧局部ROI未命中↑120%模板"
                    continue
                if len(percent_boxes) > 1 and (
                    percent_boxes[0].confidence - percent_boxes[1].confidence
                    < SALE_MARKER_MIN_MARGIN
                ):
                    last_reason = "商品名左侧局部ROI模板候选不唯一"
                    specific_local_failure = True
                    continue

                percent_box = percent_boxes[0]
                _, name_y, _, name_height = self._ocr_box_geometry(name_box)
                _, marker_y, _, marker_height = self._ocr_box_geometry(percent_box)
                vertical_overlap = min(
                    name_y + name_height,
                    marker_y + marker_height,
                ) - max(name_y, marker_y)
                # At non-16:9 sizes independent axis scaling can leave a marker
                # inside the padded ROI without overlapping the item-name row.
                if vertical_overlap <= 0:
                    last_reason = "局部↑120%模板与商品名框几何关系非法"
                    specific_local_failure = True
                    continue
                candidates.append(
                    SaleItemCandidate(
                        center=center,
                        name_box=name_box,
                        percent_box=percent_box,
                    )
                )

            if candidates:
                self._last_sale_name_seen = True
                self._last_sale_ocr_output = saw_ocr_output
                self._last_sale_page_empty = False
                self._last_sale_unavailable = False
                self._last_sale_reason = ""
                candidates.sort(
                    key=lambda candidate: (candidate.center[1], candidate.center[0])
                )
                self._status(
                    "出售120%局部模板",
                    f"{entry.item}搜索{roi_searches}个ROI，复用{reused_rois}个，"
                    f"命中{marker_hits}个模板。",
                )
                self._status(
                    "出售商品定位",
                    f"{entry.item}候选{len(candidates)}组："
                    + "、".join(str(candidate.center) for candidate in candidates),
                )
                return candidates

        self._status(
            "出售120%局部模板",
            f"{entry.item}搜索{roi_searches}个ROI，复用{reused_rois}个，"
            f"命中{marker_hits}个模板。",
        )
        self._last_sale_name_seen = saw_item_name
        self._last_sale_ocr_output = saw_ocr_output
        self._last_sale_page_empty = False
        if not saw_ocr_output:
            self._last_sale_unavailable = False
            self._last_sale_reason = "全画面OCR未返回任何文本"
        else:
            # OCR returned page text, but every height missed this item name: the
            # caller may treat the entry as unavailable. Once the name is seen,
            # any local template or geometry miss remains a recognition failure.
            self._last_sale_unavailable = not saw_item_name
            self._last_sale_reason = last_reason or "全画面OCR未形成可用商品候选"
        return []

    def _sale_page_boxes(self, frame: np.ndarray) -> list[object]:
        """Full-page OCR of the sale list, read once per frame.

        The name signature and the transaction toast both come from this one
        read (Leo 2026-10-05: each sale waited ~9 s on three full-page OCRs
        per poll; the list locator's read of the same frame is reused too).
        """

        cached = getattr(self, "_sale_page_boxes_cache", None)
        if cached is not None and cached[0] is frame:
            return cached[1]
        boxes = list(
            self.vision.ocr_boxes(
                frame,
                "出售商品列表",
                target_height=SALE_FULL_PAGE_OCR_TARGET_HEIGHT,
            )
        )
        self._sale_page_boxes_cache = (frame, boxes)
        return boxes

    def _sale_name_signature(
        self,
        entry: CalendarEntry,
        frame: np.ndarray,
    ) -> tuple[tuple[str, int, int, int, int], ...]:
        """Return a page signature independent of 120% OCR success.

        The card list can reflow after a sale.  Including all matching name
        boxes lets completion detection notice that a card disappeared even
        when OCR temporarily misses one or more 120% markers.
        """

        names = (entry.item, *entry.aliases, *ITEM_ALIASES.get(entry.item, ()))
        normalized_names = tuple(self._normal(value) for value in names if value)
        signature = []
        matching_boxes = []
        for box in self._sale_page_boxes(frame):
            text = str(getattr(box, "name", ""))
            normalized = self._normal(text)
            if not self._sale_name_matches(normalized, normalized_names):
                continue
            matching_boxes.append(box)
        for box in self._deduplicate_ocr_boxes(matching_boxes):
            normalized = self._normal(str(getattr(box, "name", "")))
            geometry = self._ocr_box_geometry(box)
            if geometry is None:
                continue
            x, y, box_width, box_height = geometry
            signature.append(
                (
                    normalized,
                    round(x),
                    round(y),
                    round(box_width),
                    round(box_height),
                )
            )
        return tuple(sorted(signature, key=lambda value: value[1:]))

    def _wait_sale_completion(
        self,
        entry: CalendarEntry,
        before_frame: np.ndarray,
        before_signature: tuple[tuple[str, int, int, int, int], ...],
        timeout: float = SALE_COMPLETION_TIMEOUT,
        *,
        before_toast_id: int | None = None,
    ) -> bool:
        """Wait until the sale dialog closes and the page advances.

        A transaction toast is preferred.  If it is missed, two consecutive
        post-sale OCR signatures that differ from the pre-sale page are an
        equivalent reflow confirmation.  A still-open sale dialog never
        counts as completion.
        """

        if before_toast_id is None:
            before_toast_id = self._sale_toast_id(before_frame)
        end_at = monotonic() + max(0.0, timeout)
        changed_signature: tuple[tuple[str, int, int, int, int], ...] | None = None
        stable_hits = 0
        last_text = ""
        dialog_closed = False
        while True:
            frame = self.vision.capture()
            if not dialog_closed:
                # The dialog never reopens by itself, so once it is gone only
                # the page needs reading.
                dialog_text = self.vision.ocr_text(
                    frame,
                    "出售弹窗完成确认",
                    relative_roi=SALE_DIALOG_REGION,
                )
                normalized_dialog = self._normal(dialog_text)
                last_text = dialog_text or last_text
                dialog_closed = (
                    "拥有" not in normalized_dialog and "可购买" not in normalized_dialog
                )
            if dialog_closed:
                full_text = self._sale_page_text(frame)
                normalized_full = self._normal(full_text)
                last_text = full_text or last_text
                toast_match = SALE_TOAST_ID_PATTERN.search(normalized_full)
                if toast_match is not None:
                    toast_id = self._quantity_from_text(toast_match.group(1))
                    if before_toast_id is None or (
                        toast_id is not None and toast_id > before_toast_id
                    ):
                        self._last_sale_toast_id = toast_id
                        self._status(
                            "出售完成确认",
                            f"{entry.item}:交易提示{toast_id or '-'}",
                        )
                        return True
                current_signature = self._sale_name_signature(entry, frame)
                if current_signature != before_signature:
                    if current_signature == changed_signature:
                        stable_hits += 1
                    else:
                        changed_signature = current_signature
                        stable_hits = 1
                    if stable_hits >= SALE_COMPLETION_STABLE_HITS:
                        self._status("出售完成确认", f"{entry.item}:页面重排")
                        return True
            if monotonic() >= end_at:
                break
            self.task.sleep(SALE_COMPLETION_INTERVAL)
        self.task.log_warning(
            f"卖：{entry.item}点击出售后未确认交易完成，OCR={last_text or '-'}。"
        )
        return False

    def _sale_page_text(self, frame: np.ndarray) -> str:
        text = " ".join(
            str(getattr(box, "name", ""))
            for box in self._sale_page_boxes(frame)
            if getattr(box, "name", "")
        )
        self._status("出售交易完成 OCR", text or "-")
        return text

    def _sale_toast_id(self, frame: np.ndarray) -> int | None:
        """Read the currently visible transaction toast sequence number."""

        try:
            text = self._sale_page_text(frame)
        except AttributeError:
            return None
        normalized = self._normal(text)
        matched = SALE_TOAST_ID_PATTERN.search(normalized)
        if matched is None:
            return None
        return self._quantity_from_text(matched.group(1))

    @staticmethod
    def _ocr_box_geometry(box) -> tuple[float, float, float, float] | None:
        x = getattr(box, "x", None)
        y = getattr(box, "y", None)
        width = getattr(box, "width", None)
        height = getattr(box, "height", None)
        if any(value is None for value in (x, y, width, height)):
            raw_box = getattr(box, "box", None)
            if raw_box is not None and len(raw_box) >= 4:
                x, y, width, height = raw_box[:4]
        if any(value is None for value in (x, y, width, height)):
            return None
        return float(x), float(y), float(width), float(height)

    @classmethod
    def _ocr_box_center(cls, box) -> tuple[int, int] | None:
        geometry = cls._ocr_box_geometry(box)
        if geometry is None:
            return None
        x, y, width, height = geometry
        return round(x + width / 2), round(y + height / 2)

    @classmethod
    def _deduplicate_ocr_boxes(cls, boxes: list[object]) -> list[object]:
        unique = []
        seen: set[tuple[int, int, int, int]] = set()
        for box in boxes:
            geometry = cls._ocr_box_geometry(box)
            if geometry is None:
                continue
            x, y, width, height = geometry
            if width <= 0 or height <= 0:
                continue
            key = round(x), round(y), round(width), round(height)
            if key in seen:
                continue
            seen.add(key)
            unique.append(box)
        return unique

    def _sale_title_catalog(self, entry: CalendarEntry) -> dict[str, set[str]]:
        if self._sale_title_catalog_cache is not None:
            return self._sale_title_catalog_cache
        bundled = parse_calendar_payload(
            (CALENDAR_DIR / "price_calendar.v1.json").read_text(encoding="utf-8")
        )
        entries = [item for items in bundled.days.values() for item in items]
        entries.extend(CalendarEntry(item, "") for item in ITEM_ALIASES)
        entries.extend(self._sale_title_entries)
        entries.append(entry)
        catalog: dict[str, set[str]] = {}
        for item in entries:
            identity = self._normal(item.item)
            for name in (item.item, *item.aliases, *ITEM_ALIASES.get(item.item, ())):
                normalized = self._normal(name)
                if normalized:
                    catalog.setdefault(normalized, set()).add(identity)
        self._sale_title_catalog_cache = catalog
        return catalog

    def _sale_dialog_title_identity(
        self, frame: np.ndarray, catalog: dict[str, set[str]], expected: str,
    ) -> bool | None:
        """Resolve one complete title; None is unknown, False is a conflicting item."""
        _left, _top, original = relative_roi_frame(frame, SALE_DIALOG_TITLE_REGION)
        if original.size == 0:
            return None
        for mode in ("原图", "灰度", "CLAHE"):
            target = original
            if mode != "原图":
                gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
                if mode == "CLAHE":
                    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
                target = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            boxes = self.vision.ocr_boxes(
                target, f"出售弹窗商品标题/{mode}", target_height=0,
            )
            texts = [str(box.name) for box in boxes]
            self._status(
                f"出售弹窗商品标题/{mode}",
                [(box.name, box.confidence) for box in boxes],
            )
            full_name = self._normal(" ".join(texts))
            full_ids = catalog.get(full_name, set())
            seen_ids = set(full_ids)
            for text in texts:
                seen_ids.update(catalog.get(self._normal(text), set()))
            if seen_ids - {expected}:
                self.task.log_warning(
                    f"卖：弹窗标题识别到其他或歧义商品：{' '.join(texts)}，停止出售。"
                )
                return False
            if full_ids == {expected}:
                return True
        return None

    def _wait_sale_dialog_item(
        self,
        entry: CalendarEntry,
        timeout: float = SALE_DIALOG_TIMEOUT,
    ) -> bool:
        catalog = self._sale_title_catalog(entry)
        expected = self._normal(entry.item)
        stable_hits = 0
        end_at = monotonic() + max(0.0, timeout)
        while True:
            frame = self.vision.capture()
            # Before the dialog draws, the title area shows the item list, and
            # a card there would read as "another item" (review 2026-09-26).
            matched = (
                self._sale_dialog_title_identity(frame, catalog, expected)
                if self._sale_dialog_shown(frame)
                else None
            )
            if matched is False:
                self._sale_dialog_rejected = True
                return False
            stable_hits = stable_hits + 1 if matched else 0
            if stable_hits >= SALE_DIALOG_TITLE_STABLE_HITS:
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(SALE_OCR_INTERVAL)

    def _wait_owned_quantity(self, timeout: float = SALE_DIALOG_TIMEOUT) -> int | None:
        """The owned count once two reads agree.

        The kept amount is worked out from it: one read with an extra digit
        (40245 read as 140245) would make selling everything look like
        keeping the reserve.
        """
        previous = None
        end_at = monotonic() + max(0.0, timeout)
        while True:
            text = self.vision.ocr_text(
                self.vision.capture(),
                "出售弹窗库存",
                relative_roi=SALE_DIALOG_REGION,
            )
            normalized = self.vision.simplify(text)
            matched = SALE_OWNED_PATTERN.search(normalized)
            quantity = None
            if matched is not None:
                quantity = self._quantity_from_text(matched.group(1))
                if quantity is not None and quantity == previous:
                    return quantity
            if monotonic() >= end_at and previous is not None:
                return None
            previous = -1 if quantity is None else quantity
            self.task.sleep(SALE_OCR_INTERVAL)

    def _wait_available_quantity(
        self,
        timeout: float = SALE_DIALOG_TIMEOUT,
    ) -> int | None:
        previous = None
        end_at = monotonic() + max(0.0, timeout)
        while True:
            text = self.vision.ocr_text(
                self.vision.capture(),
                "出售弹窗可购买数量",
                relative_roi=SALE_DIALOG_REGION,
            )
            normalized = self.vision.simplify(text)
            matched = SALE_AVAILABLE_PATTERN.search(normalized)
            quantity = None
            if matched is not None:
                quantity = self._quantity_from_text(matched.group(1))
                if quantity is not None and quantity > 0 and quantity == previous:
                    return quantity
            if monotonic() >= end_at and previous is not None:
                return None
            previous = -1 if quantity is None else quantity
            self.task.sleep(SALE_OCR_INTERVAL)

    def _wait_selected_sale_quantity(
        self,
        expected: int | None,
        timeout: float = SALE_DIALOG_TIMEOUT,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        # How many this sale sells, for the run's 卖了 line (YES-BD2 #6).
        self._last_selected_sale_quantity = None
        while True:
            text = self.vision.ocr_text(
                self.vision.capture(),
                "出售弹窗已选数量",
                relative_roi=SALE_DIALOG_REGION,
            )
            selected = self._selected_quantity_from_text(text)
            if selected is not None and selected > 0:
                if expected is None or selected == expected:
                    self._status("出售已选数量", str(selected))
                    self._last_selected_sale_quantity = selected
                    return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(SALE_OCR_INTERVAL)

    @staticmethod
    def _selected_quantity_from_text(text: str) -> int | None:
        normalized = str(text).replace("，", ",")
        values = []
        for matched in re.finditer(r"([0-9][0-9,.]*)\s*个", normalized):
            prefix = normalized[max(0, matched.start() - 4) : matched.start()]
            if "拥有" in prefix or "可购买" in prefix:
                continue
            quantity = SellFlowMixin._quantity_from_text(matched.group(1))
            if quantity is not None:
                values.append(quantity)
        return max(values, default=None)

    @staticmethod
    def _quantity_from_text(text: str) -> int | None:
        values = []
        for matched in re.findall(r"[0-9][0-9,，.]*", str(text)):
            digits = re.sub(r"\D", "", matched)
            if digits:
                values.append(int(digits))
        return max(values, default=None)

    def _choose_sale_quantity(
        self, entry: CalendarEntry, owned: int, available: int | None = None
    ) -> bool:
        if entry.reserve > 0:
            if not self._owned_matches_sale_max(entry, owned, available):
                return False
            if available is not None and owned - available >= entry.reserve:
                # A whole group still keeps the reserve: MAX (pressed by the
                # check above), not the slider (live 2026-10-07: 兽肉 684771,
                # keep 10000, groups of 99999 - seven slider clicks per group,
                # every one clamped at 99999).
                self.task.log_info(
                    f"卖：{entry.item}拥有{owned}个，这组最多{available}个，按MAX后"
                    f"还保留{owned - available}个（目标至少{entry.reserve}个）。"
                )
                return True
            return self._choose_reserved_quantity(entry, owned, available)
        if bool(self.task.config.get("出售保险", False)):
            self.task.operate_click(*SALE_MIN_POINT, after_sleep=0.5)
        else:
            self.task.operate_click(*SALE_MAX_POINT, after_sleep=0.5)
        return True

    def _owned_matches_sale_max(
        self, entry: CalendarEntry, owned: int, available: int | None
    ) -> bool:
        """MAX selects what the slider really reaches, min(owned, group).

        The kept amount is worked out from the owned count alone: a count read
        with an extra digit every time (40245 as 140245) sold the whole stock
        while the log said the reserve was kept (review #15).  MAX selecting
        another count, or the owned count minus one digit, means owned was
        misread, and nothing is sold.
        """

        most = min(owned, available) if available else owned
        self.task.operate_click(*SALE_MAX_POINT, after_sleep=0.5)  # 不用确认：下面读回已选数量
        selected = self._read_selected_quantity()
        if selected == most and not _with_one_extra_digit(owned, selected):
            return True
        self.task.log_warning(
            f"卖：{entry.item}按MAX选到{'?' if selected is None else selected}个，"
            f"和认到的拥有{owned}个（这组最多{available}个）对不上，可能把拥有数量认错了，"
            f"这一组不出售，以免卖掉要保留的{entry.reserve}个。"
        )
        return False

    def _choose_reserved_quantity(
        self, entry: CalendarEntry, owned: int, available: int | None = None
    ) -> bool:
        """Sell all but about ``entry.reserve``, never keeping fewer.

        One slider click landed 1634 short of the target (40245 owned, keep
        2000: 39879 were sold and 366 kept, Leo 2026-10-05).  The selected
        count is read back after each click and the next click corrected
        from the clicks so far, until the kept amount lies in
        [reserve, reserve + slack]; otherwise nothing is sold.
        """

        reserve = entry.reserve
        slack = self._reserve_slack(reserve)
        if owned <= reserve:
            return False
        target = max(1, owned - reserve - slack // 2)  # amount to sell
        left, top, right, bottom = SALE_SLIDER_REGION
        y = (top + bottom) / 2
        # (x, selected) pairs; the right end sells the whole group.
        most = min(owned, available) if available else owned
        observed: list[tuple[float, int]] = [(right, most)]
        x = left + (right - left) * max(0.0, min(1.0, (target - 1) / max(1, most - 1)))
        self._status("出售保留量", f"{entry.item}:约{reserve}")
        for attempt in range(1, SALE_RESERVE_ADJUST_ATTEMPTS + 1):
            self.task.operate_click(x, y, after_sleep=0.4)
            selected = self._read_selected_quantity()
            if selected is None:
                self.task.log_warning(f"卖：{entry.item}滑条点击后读不到已选数量，不出售。")
                return False
            kept = owned - selected
            self._status("出售已选数量", f"{selected}（保留{kept}）")
            if reserve <= kept <= reserve + slack:
                self.task.log_info(
                    f"卖：{entry.item}拥有{owned}个，选择出售{selected}个，"
                    f"保留{kept}个（目标至少{reserve}个）。"
                )
                self._reserve_reached = True
                return True
            observed.append((x, selected))
            x = self._next_slider_x(observed, target, left, right)
            self.task.log_info(
                f"卖：{entry.item}第{attempt}次滑条选了{selected}个（保留{kept}个），修正位置再选。"
            )
        # Not within the slack: the click that kept the least, still at
        # least the reserve, is good enough (keeping more is safe).
        safe = [(x_, s_) for x_, s_ in observed[1:] if owned - s_ >= reserve]
        if safe:
            best_x, _best = max(safe, key=lambda point: point[1])
            self.task.operate_click(best_x, y, after_sleep=0.4)
            selected = self._read_selected_quantity()
            if selected is not None and owned - selected >= reserve:
                self.task.log_info(
                    f"卖：{entry.item}拥有{owned}个，选择出售{selected}个，"
                    f"保留{owned - selected}个（目标至少{reserve}个）。"
                )
                self._reserve_reached = True
                return True
        self.task.log_warning(
            f"卖：{entry.item}滑条{SALE_RESERVE_ADJUST_ATTEMPTS}次都没能保留约{reserve}个，"
            "这一组不出售。"
        )
        return False

    @staticmethod
    def _reserve_slack(reserve: int) -> int:
        """How much more than the reserve may be kept."""
        return max(SALE_RESERVE_MIN_SLACK, round(reserve * SALE_RESERVE_SLACK_RATIO))

    @staticmethod
    def _next_slider_x(
        observed: list[tuple[float, int]], target: int, left: float, right: float
    ) -> float:
        """Where ``target`` lies: between the closest clicks on either side of
        it when there are both, else from the two closest (secant)."""

        below = [point for point in observed if point[1] < target]
        above = [point for point in observed if point[1] >= target]
        if below and above:
            nearest = [
                max(below, key=lambda point: point[1]),
                min(above, key=lambda point: point[1]),
            ]
        else:
            nearest = sorted(observed, key=lambda point: abs(point[1] - target))[:2]
        (x1, s1), (x2, s2) = nearest if len(nearest) == 2 else (nearest[0], (left, 1))
        if s1 == s2:
            # Flat (the clamped right end): step left until the count moves.
            flat_x = min(x for x, value in observed if value == s1)
            return max(left, min(right, flat_x - (right - left) * 0.03))
        x = x1 + (target - s1) * (x2 - x1) / (s2 - s1)
        return max(left, min(right, x))

    def _read_selected_quantity(self, timeout: float = SALE_DIALOG_TIMEOUT) -> int | None:
        """The dialog's selected count once two reads agree."""

        previous = None
        end_at = monotonic() + max(0.0, timeout)
        while True:
            text = self.vision.ocr_text(
                self.vision.capture(),
                "出售弹窗已选数量",
                relative_roi=SALE_DIALOG_REGION,
            )
            selected = self._selected_quantity_from_text(text)
            if selected is not None and selected > 0 and selected == previous:
                return selected
            if monotonic() >= end_at:
                return None
            previous = selected
            self.task.sleep(SALE_OCR_INTERVAL)

    @staticmethod
    def _sale_slider_point(
        owned: int, reserve: int
    ) -> tuple[float, float] | None:
        """Map the desired sale amount onto the one-to-all sale slider."""

        if owned <= reserve or owned <= 0:
            return None
        amount = owned - reserve
        ratio = 0.0 if owned == 1 else (amount - 1) / (owned - 1)
        ratio = max(0.0, min(1.0, ratio))
        left, top, right, bottom = SALE_SLIDER_REGION
        return left + ((right - left) * ratio), (top + bottom) / 2
