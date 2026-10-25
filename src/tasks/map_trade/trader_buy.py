from __future__ import annotations

from time import monotonic

import numpy as np

from src.tasks.map_trade.calendar import (
    PURCHASE_STOCK_REFRESH_HOUR,
    purchase_stock_date,
)
from src.tasks.map_trade.models import (
    ScreenState,
)
from src.tasks.map_trade.navigator_trade import BARGAIN_UPGRADE_MESSAGE
from src.tasks.map_trade.phase_ledger import PhaseDeferred
from src.tasks.map_trade.trader_constants import (
    BUY_ALL_FAVORITES_INTERVAL,
    BUY_ALL_FAVORITES_KEYWORD,
    BUY_ALL_FAVORITES_POINT,
    BUY_ALL_FAVORITES_STABLE_HITS,
    BUY_ALL_FAVORITES_TIMEOUT,
    BUY_CONFIRM_CLOSE_TIMEOUT,
    BUY_CONFIRM_DIALOG_REGION,
    BUY_CONFIRM_FIRST_TIMEOUT,
    BUY_CONFIRM_INTERVAL,
    BUY_CONFIRM_KEYWORDS,
    BUY_CONFIRM_POINT,
    BUY_CONFIRM_POST_CLICK_DELAY,
    BUY_CONFIRM_PRE_CLICK_DELAY,
    BUY_CONFIRM_TIMEOUT,
    BUY_NO_FAVORITES_TOAST_KEYWORD,
    BUY_NO_FAVORITES_TOAST_REGION,
    BUY_TO_SELL_INTERVAL,
    BUY_TO_SELL_POST_CLICK_DELAY,
    BUY_TO_SELL_PRE_CLICK_DELAY,
    BUY_TO_SELL_SOLD_OUT_STABLE_HITS,
    BUY_TO_SELL_SOLD_OUT_TEMPLATE,
    BUY_TO_SELL_TIMEOUT,
    SELL_MODE_POINT,
)
from src.tasks.map_trade.vision import normalize_text

# 点击"购买全部收藏"后等待确认弹窗出现前的停顿。
BUY_ALL_FAVORITES_CLICK_AFTER_SLEEP = 0.3


class BuyFlowMixin:
    _no_favorites_seen = False

    def run_buy(self) -> bool:
        stock_date = purchase_stock_date(self._current_market_time())
        self._status("购买库存日期", stock_date.isoformat())
        self.task.log_info(
            f"买：按{stock_date.isoformat()}库存批次执行（每日"
            f"{PURCHASE_STOCK_REFRESH_HOUR:02d}:00刷新）。"
        )
        entered = self.navigator.enter_q_sp6_buy_flow()
        if not entered.success and entered.message == BARGAIN_UPGRADE_MESSAGE:
            self.task.log_warning(f"买：{entered.message}", notify=True)
            return PhaseDeferred(f"买：{entered.message}")
        if not entered.success:
            self.task.log_warning(f"买：{entered.message}")
            return False
        if entered.state != ScreenState.SHOP:
            self.task.log_warning(
                f"买：砍价后状态为{entered.state.value}，未确认商店页，停止购买。"
            )
            return False
        self._status("当前阶段", "一键购买全部收藏")
        purchase_state = self._wait_for_buy_all_favorites_state()
        if purchase_state is None:
            completed = self._buy_all_favorites_at_fixed_point()
            self._buy_completed_in_current_shop = completed is True
            return completed
        if purchase_state[0] is None:
            self._buy_completed_in_current_shop = True
            return True
        rebuild_cycle = str(self.task.config.get("收藏重建周期", "永不"))
        every_run = rebuild_cycle == "每次"
        if rebuild_cycle == "永不":
            self.task.log_info("买：收藏重建周期设为永不，跳过收藏调整。")
        elif not self.progress.should_rebuild_favorites(every_run=every_run):
            self.task.log_info("买：本周收藏已经按本地表重建，跳过收藏调整。")
        else:
            if every_run:
                self.progress.clear_favorite_cards()
            if not self.rebuild_favorites():
                return False
        # The button was just read twice: press it now.  Reading it again
        # took a slow 1080p PC past the 10 s stuck guard on the still page
        # (player 问题摘要 2026-10-16, two days in a row).
        completed = self.buy_all_favorites(located=purchase_state)
        self._buy_completed_in_current_shop = completed is True
        return completed

    def _switch_from_completed_buy_to_sell(
        self,
        timeout: float = BUY_TO_SELL_TIMEOUT,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        sold_out_hits = 0
        last_title = ""
        last_match = None
        while True:
            frame = self.vision.capture()
            title = self._shop_mode_title(frame)
            last_title = title or last_title
            normalized_title = normalize_text(self.vision.simplify(title))
            if "出售" in normalized_title:
                self._status("商店页面", "出售")
                self.task.log_info("卖：购买完成后已处于出售页，直接继续出售。")
                return True

            last_match = self.vision.match(frame, BUY_TO_SELL_SOLD_OUT_TEMPLATE)
            matched = self.vision.passes(last_match, BUY_TO_SELL_SOLD_OUT_TEMPLATE)
            sold_out_hits = sold_out_hits + 1 if matched else 0
            self._status(
                "买后售罄模板",
                (
                    f"{'命中' if matched else '未命中'} "
                    f"{sold_out_hits}/{BUY_TO_SELL_SOLD_OUT_STABLE_HITS}; "
                    f"m={last_match.score:.3f}, p={last_match.pixel_score:.3f}, "
                    f"z={last_match.zncc_score:.3f}"
                ),
            )
            if sold_out_hits >= BUY_TO_SELL_SOLD_OUT_STABLE_HITS:
                self.task.log_info(
                    "卖：售罄模板连续命中，等待0.5秒后点击出售入口。"
                )
                self.task.sleep(BUY_TO_SELL_PRE_CLICK_DELAY)
                self.task.operate_click(
                    *SELL_MODE_POINT,
                    after_sleep=BUY_TO_SELL_POST_CLICK_DELAY,
                )
                return self._ensure_sell_page()
            if monotonic() >= end_at:
                break
            self.task.sleep(BUY_TO_SELL_INTERVAL)
        score_text = (
            "-"
            if last_match is None
            else (
                f"m={last_match.score:.3f}, p={last_match.pixel_score:.3f}, "
                f"z={last_match.zncc_score:.3f}"
            )
        )
        self.task.log_warning(
            "卖：买后等待售罄模板稳定命中超时，未切换出售页，"
            f"title={last_title or '-'}, match={score_text}。"
        )
        return False

    def buy_all_favorites(self, located=None) -> bool | PhaseDeferred:
        self._no_favorites_seen = False
        if located is None:
            located = self._wait_for_buy_all_favorites_state()
        if located is None:
            self.task.log_warning("买：商店页面未稳定显示可购买按钮或售罄状态。")
            return False
        button_center, frame = located
        if button_center is None:
            return True
        self._status(
            "一键购买全部收藏按钮点击中心",
            f"center=({button_center[0]},{button_center[1]})",
        )
        self.vision.click_client(
            button_center, frame.shape, after_sleep=BUY_ALL_FAVORITES_CLICK_AFTER_SLEEP
        )
        if not self._wait_for_purchase_confirmation(
            BUY_CONFIRM_FIRST_TIMEOUT, log_timeout=False
        ):
            if self._no_favorites_seen:
                return self._nothing_favorited()
            # A swallowed press leaves the shop as it was: press the button
            # once more, only while it is still read and no part of the
            # dialog shows.  It only opens the confirm dialog; buying needs
            # that dialog's 确认.
            if self._purchase_dialog_partly_read():
                confirmed = self._wait_for_purchase_confirmation()
            else:
                again = self._wait_for_buy_all_favorites_state(BUY_CONFIRM_FIRST_TIMEOUT)
                if again is not None and again[0] is None:
                    return True
                if again is None:
                    self.task.log_info(
                        "买：点了一键购买全部收藏没有出现确认弹窗，也读不到按钮，改按它的固定位置。"
                    )
                    return self._buy_all_favorites_at_fixed_point()
                self.task.log_info("买：点了一键购买全部收藏没有出现确认弹窗，再点一次。")
                self.vision.click_client(  # 不用确认：the dialog is waited for below
                    again[0], again[1].shape, after_sleep=BUY_ALL_FAVORITES_CLICK_AFTER_SLEEP
                )
                confirmed = self._wait_for_purchase_confirmation(log_timeout=False)
            if not confirmed and self._no_favorites_seen:
                return self._nothing_favorited()
            if not confirmed:
                return self._confirm_unread_purchase_dialog()
        return self._press_purchase_confirm()

    def _buy_all_favorites_at_fixed_point(self) -> bool | PhaseDeferred:
        """The 一键购买全部收藏 words were not read: press where it sits."""
        self._no_favorites_seen = False
        self.task.log_info("买：读不到「一键购买全部收藏」，按它的固定位置。")
        self.task.operate_click(  # 不用确认：the dialog is waited for below
            *BUY_ALL_FAVORITES_POINT, after_sleep=BUY_ALL_FAVORITES_CLICK_AFTER_SLEEP
        )
        if self._wait_for_purchase_confirmation(
            BUY_CONFIRM_FIRST_TIMEOUT, log_timeout=False
        ) or self._purchase_dialog_partly_read():
            return self._press_purchase_confirm()
        if self._no_favorites_seen:
            return self._nothing_favorited()
        return self._confirm_unread_purchase_dialog()

    def _nothing_favorited(self) -> PhaseDeferred:
        """The game said nothing is starred: there is nothing to buy, and
        pressing 确认 or buying again from home cannot change that.  Not
        recorded, so the buy runs again once goods are starred."""
        message = (
            "游戏提示「收藏中没有加入的商品」：商店里没有收藏任何商品，"
            "一键购买全部收藏买不到东西。请先在游戏商店里给要买的商品点星收藏，本次跳过购买。"
        )
        self.task.log_warning(f"买：{message}", notify=True)
        return PhaseDeferred(message)

    def _no_favorites_toast_shown(self, frame) -> bool:
        text = normalize_text(self.vision.simplify(self.vision.ocr_text(
            frame, "收藏为空提示", relative_roi=BUY_NO_FAVORITES_TOAST_REGION
        )))
        return normalize_text(self.vision.simplify(BUY_NO_FAVORITES_TOAST_KEYWORD)) in text

    def _confirm_unread_purchase_dialog(self) -> bool:
        """No confirm dialog was read: press 确认 where it sits, then the
        sold-out labels on the bought favourites say whether it worked."""
        self.task.log_info("买：读不到购买确认弹窗，按确认的固定位置，再看商品是否售罄。")
        self.task.sleep(BUY_CONFIRM_PRE_CLICK_DELAY)
        self.task.operate_click(*BUY_CONFIRM_POINT, after_sleep=BUY_CONFIRM_POST_CLICK_DELAY)  # 不用确认：售罄 is checked below
        return self._sold_out_after_buy()

    def _press_purchase_confirm(self) -> bool:
        self.task.log_info(
            f"买：购买确认弹窗OCR完成，等待{BUY_CONFIRM_PRE_CLICK_DELAY:.1f}秒后点击确认。"
        )
        self.task.sleep(BUY_CONFIRM_PRE_CLICK_DELAY)
        for attempt in range(1, 3):
            # A second press only while the same dialog is still up: it is
            # the one purchase, never a repeat.
            self.task.operate_click(
                *BUY_CONFIRM_POINT,
                after_sleep=BUY_CONFIRM_POST_CLICK_DELAY,
            )
            if self._wait_purchase_dialog_closed():
                self.task.log_info("买：已确认购买全部收藏商品。")
                return True
            self.task.log_info(f"买：第{attempt}次点击确认后购买弹窗仍在。")
        return self._sold_out_after_buy()

    def _sold_out_after_buy(self, timeout: float = BUY_TO_SELL_TIMEOUT) -> bool:
        """The 售罄 labels on the favourites prove the purchase went through."""
        end_at = monotonic() + max(0.0, timeout)
        hits = 0
        while True:
            match = self.vision.match(self.vision.capture(), BUY_TO_SELL_SOLD_OUT_TEMPLATE)
            hits = hits + 1 if self.vision.passes(match, BUY_TO_SELL_SOLD_OUT_TEMPLATE) else 0
            if hits >= BUY_TO_SELL_SOLD_OUT_STABLE_HITS:
                self.task.log_info("买：收藏的商品已显示售罄，确认买到。")
                return True
            if monotonic() >= end_at:
                break
            self.task.sleep(BUY_TO_SELL_INTERVAL)
        self.task.log_warning("买：按了购买和确认，商品没有显示售罄，未确认买到。")
        return False

    def _wait_purchase_dialog_closed(self, timeout: float = BUY_CONFIRM_CLOSE_TIMEOUT) -> bool:
        """Two reads in a row without either confirm keyword."""
        end_at = monotonic() + max(0.0, timeout)
        clear_hits = 0
        while True:
            text = normalize_text(self.vision.simplify(self.vision.ocr_text(
                self.vision.capture(),
                "购买全部收藏确认关闭",
                relative_roi=BUY_CONFIRM_DIALOG_REGION,
            )))
            present = any(
                normalize_text(self.vision.simplify(keyword)) in text
                for keyword in BUY_CONFIRM_KEYWORDS
            )
            clear_hits = 0 if present else clear_hits + 1
            if clear_hits >= 2:
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(BUY_CONFIRM_INTERVAL)

    def _wait_for_buy_all_favorites_state(
        self,
        timeout: float = BUY_ALL_FAVORITES_TIMEOUT,
    ) -> tuple[tuple[int, int] | None, np.ndarray] | None:
        """返回按钮与当前帧；中心为 None 表示售罄，整体 None 表示超时。"""
        end_at = monotonic() + max(0.0, timeout)
        consecutive_hits = 0
        sold_out_hits = 0
        last_text = ""
        last_center: tuple[int, int] | None = None
        last_frame: np.ndarray | None = None
        expected = normalize_text(self.vision.simplify(BUY_ALL_FAVORITES_KEYWORD))
        while True:
            frame = self.vision.capture()
            boxes = self.vision.ocr_boxes(
                frame,
                "一键购买全部收藏按钮",
            )
            texts = [str(getattr(box, "name", "")) for box in boxes]
            text = " ".join(value for value in texts if value)
            self._status("一键购买全部收藏按钮 OCR", text or "-")
            last_text = text or last_text
            sold_out = self.vision.match(frame, BUY_TO_SELL_SOLD_OUT_TEMPLATE)
            sold_out_passed = self.vision.passes(sold_out, BUY_TO_SELL_SOLD_OUT_TEMPLATE)
            sold_out_hits = sold_out_hits + 1 if sold_out_passed else 0
            if sold_out_passed:
                self._note_progress()
            self._status(
                "买前售罄模板",
                (
                    f"{'命中' if sold_out_passed else '未命中'} "
                    f"{sold_out_hits}/{BUY_TO_SELL_SOLD_OUT_STABLE_HITS}; "
                    f"m={sold_out.score:.3f}, p={sold_out.pixel_score:.3f}, "
                    f"z={sold_out.zncc_score:.3f}"
                ),
            )
            if sold_out_hits >= BUY_TO_SELL_SOLD_OUT_STABLE_HITS:
                self.task.log_info("买：售罄模板连续命中，判定本日库存已购买，跳过购买。")
                return None, frame
            matched_center = next(
                (
                    center
                    for box in boxes
                    if expected
                    in normalize_text(
                        self.vision.simplify(str(getattr(box, "name", "")))
                    )
                    if (center := self._ocr_box_center(box)) is not None
                ),
                None,
            )
            # 售罄时按钮仍可能显示，任一售罄帧都必须阻止按钮点击。
            if matched_center is not None and not sold_out_passed:
                consecutive_hits += 1
                self._note_progress()
                last_center = matched_center
                last_frame = frame
            else:
                consecutive_hits = 0
                last_center = None
                last_frame = None
            self._status(
                "一键购买全部收藏按钮 OCR稳定",
                f"{consecutive_hits}/{BUY_ALL_FAVORITES_STABLE_HITS}",
            )
            if (
                consecutive_hits >= BUY_ALL_FAVORITES_STABLE_HITS
                and last_center is not None
                and last_frame is not None
            ):
                return last_center, last_frame
            if monotonic() >= end_at:
                break
            self.task.sleep(BUY_ALL_FAVORITES_INTERVAL)
        self.task.log_warning(
            f"买：购买按钮或售罄状态确认超时，OCR={last_text or '-'}。"
        )
        return None

    def _purchase_dialog_partly_read(self) -> bool:
        """Either confirm-dialog line is read: the dialog is up, only slow."""
        text = normalize_text(self.vision.simplify(self.vision.ocr_text(
            self.vision.capture(), "购买全部收藏确认", relative_roi=BUY_CONFIRM_DIALOG_REGION
        )))
        return any(
            normalize_text(self.vision.simplify(keyword)) in text
            for keyword in BUY_CONFIRM_KEYWORDS
        )

    def _wait_for_purchase_confirmation(
        self,
        timeout: float = BUY_CONFIRM_TIMEOUT,
        *,
        log_timeout: bool = True,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        while True:
            frame = self.vision.capture()
            text = self.vision.ocr_text(
                frame,
                "购买全部收藏确认",
                relative_roi=BUY_CONFIRM_DIALOG_REGION,
            )
            last_text = text or last_text
            normalized = normalize_text(self.vision.simplify(text))
            matched = sum(
                normalize_text(self.vision.simplify(keyword)) in normalized
                for keyword in BUY_CONFIRM_KEYWORDS
            )
            self._status(
                "购买全部收藏确认 OCR命中",
                f"{matched}/{len(BUY_CONFIRM_KEYWORDS)}",
            )
            if matched == len(BUY_CONFIRM_KEYWORDS):
                return True
            if not matched and self._no_favorites_toast_shown(frame):
                self._no_favorites_seen = True
                return False
            if monotonic() >= end_at:
                break
            self.task.sleep(BUY_CONFIRM_INTERVAL)
        if not log_timeout:
            return False
        self.task.log_warning(
            f"买：购买全部收藏确认OCR超时，OCR={last_text or '-'}。"
        )
        return False
