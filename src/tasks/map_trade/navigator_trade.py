from __future__ import annotations

import re
from time import monotonic

from src.tasks.BaseBD2Task import CARTRIDGE_RECENT_ENTRY_POINT
from src.tasks.map_trade.models import (
    MERCHANT_CARD_ID,
    MapPageMode,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator_constants import (
    AREA_MAP_BACK_TEMPLATE,
    AREA_MAP_FOOTER_KEYWORDS,
    AREA_MAP_FOOTER_RELATIVE_ROI,
    AREA_MAP_KEY,
    AREA_MAP_OPEN_SECONDS,
    AREA_MAP_TITLE_RELATIVE_ROI,
    BARGAIN_CONFIRM_POINT,
    BARGAIN_POINT,
    BARGAIN_SHOP_CONFIRM_POPUP_KEYWORD,
    BARGAIN_SHOP_CONFIRM_STABLE_HITS,
    CHAPTER_HOME_POINT,
    CHAPTER_HOME_TEMPLATES,
    DISCOUNT_SHOP_CLOSE_CONTROL_REFERENCE_POINT,
    DISCOUNT_SHOP_CLOSE_CONTROL_TEMPLATES,
    DISCOUNT_SHOP_CLOSE_DIALOG_REGION,
    DISCOUNT_SHOP_CLOSE_KEYWORDS,
    DISCOUNT_SHOP_CLOSE_POINT,
    DISCOUNT_SHOP_CLOSE_TIMEOUT,
    MAP_MERCHANT_ICON_TEMPLATE,
    MAP_MERCHANT_ICON_TIMEOUT,
    MERCHANT_ARRIVAL_TIMEOUT,
    MERCHANT_MENU_RECHECK_SECONDS,
    MERCHANT_MENU_REPRESSES,
    MERCHANT_NAV_CONFIRM_OCR_ROI,
    MERCHANT_NAV_LANDMARK_TIMEOUT,
    MERCHANT_NAV_MENU_OCR_INTERVAL,
    MERCHANT_NAV_MENU_OCR_ROI,
    MERCHANT_NAV_MENU_OCR_TIMEOUT,
    MERCHANT_NAV_OUTCOME_TIMEOUT,
    MERCHANT_NAV_TOAST_OCR_ROI,
    MERCHANT_NAV_UNREACHABLE_KEYWORD,
    MERCHANT_PROMPT_FAILURE_MESSAGE,
    MERCHANT_PROMPT_OCR_ROI,
    MERCHANT_PROMPT_PATTERN,
    MERCHANT_QUICK_ARRIVAL_TIMEOUT,
    MERCHANT_TALK_KEY,
    MERCHANT_TRAVEL_DIALOG_KEYWORDS,
    MERCHANT_TRAVEL_DIALOG_OCR_ROI,
    MINIMAP_CENTER_REFERENCE,
    PLAIN_SHOP_OPTION_TIMEOUT,
    Q_SP6_BARGAIN_CLICK_DELAY,
    Q_SP6_BARGAIN_OCR_TIMEOUT,
    Q_SP6_BARGAIN_RECHECK_DELAY,
    Q_SP6_SHOP_PAGE_KEYWORDS,
    Q_SP6_SHOP_PAGE_OCR_INTERVAL,
    Q_SP6_SHOP_PRIORITY_TIMEOUT,
    QUICK_SWITCH_BACK_RELATIVE_POINT,
    QUICK_SWITCH_PAGE_KEYWORDS,
    RETURN_HOME_PASSES,
    RETURN_HOME_STEP_TIMEOUT,
    RETURN_HOME_TIMEOUT,
    SHOP_CLOSE_CLICK_INTERVAL,
    SHOP_CLOSE_CLICK_RETRIES,
    SHOP_ENTRY_RECLICK_AFTER,
    SHOP_ENTRY_RECLICK_HITS,
    SQUARE_MAP_MERCHANT_ICON_TEMPLATE,
    SQUARE_MAP_MERCHANT_POINT,
    TRADE_CARD_SANDBOX_HITS,
    TRADE_MERCHANT_OPTIONS_REGION,
    TRADE_MERCHANT_TALENTS_REGION,
)
from src.tasks.map_trade.trader_constants import (
    BUY_TO_SELL_SOLD_OUT_STABLE_HITS,
    BUY_TO_SELL_SOLD_OUT_TEMPLATE,
    COOKING_BACK_POINT,
    SALE_AVAILABLE_PATTERN,
    SALE_CLOSE_POINT,
    SALE_DIALOG_REGION,
    SALE_DIALOG_TIMEOUT,
    SALE_OCR_INTERVAL,
    SALE_OWNED_PATTERN,
)
from src.tasks.map_trade.vision import normalize_text
from src.utils.cartridge_quick_switch import FIXED_CARTRIDGE_SLOT_PRE_CLICK_DELAY_SECONDS
from src.utils.fantasia_square import (
    SQUARE_CARTRIDGE_SLOT_POINT,
    square_card_point,
    square_shown,
)
from src.utils.field_followers import dismiss_once_per_run
from src.utils.press_confirm import wait_for
from src.utils.wait_limits import STUCK_SECONDS, ProgressWait, StillTimer, scene_at_press

# After closing a shop with no discount-close dialog, how long the merchant
# menu (or the field) is looked for.
MERCHANT_BACK_LOOK_SECONDS = 2.0

# The skill is full and must be starred up by the player (user choice,
# 2026-09-28: skip buying and say so, never buy at full price).
BARGAIN_UPGRADE_HINT = "强化砍价"
BARGAIN_UPGRADE_MESSAGE = "砍价技能可以升星了，请先在游戏里手动升星；本次跳过购买。"
# 循环砍价 refuses a 砍价 popup that names a paid currency (never spend paid
# resources); today's popup only shows the field currency icon and its cost.
BARGAIN_PAID_WORDS = ("钻石", "付费", "鸡尾酒")
BARGAIN_PAID_MESSAGE = "砍价弹窗提到付费货币，为了不花钱没有按砍价"
# 循环砍价 trains the skill up to 传说 (Leo 2026-10-11: the best buying
# discount comes at 传说); once the 砍价 card reads 传说 it stops pressing.
BARGAIN_LEGEND_RANK = "传说"
BARGAIN_LEGEND_MESSAGE = "砍价技能已经是传说等级，不用再砍了"
BARGAIN_LEGEND_READS = 2


MERCHANT_STAGE = "找商人无聊收集狂大叔"
# The merchant in 梦幻广场, where 跑商 now runs first (Leo 2026-10-20).
SQUARE_MERCHANT_STAGE = "找商人洛兹"
SQUARE_ARRIVED = "square"
SQUARE_OTHER_FIELD = "other_field"
# A field without the square's icon for this long is another cartridge.
SQUARE_ICON_GRACE_SECONDS = 3.0
# A dropped 广场 card press: the unchanged page after this long is pressed again.
SQUARE_CARD_REPRESS_SECONDS = 2.5
SQUARE_CARD_REPRESSES = 2
SHOP_ENTRY_STAGE = "进入商店"


class TradeNavigationMixin:
    """Trade at the merchant 无聊收集狂大叔 of story cartridge 1 血骑士.

    Upstream traded at chapter 6 and recognised the merchant by a scene crop;
    the user trades in chapter 1 (2026-09-26), where the merchant is found by
    the name on his interaction prompt.  Method names keep the upstream
    ``q_sp6`` wording.
    """

    def enter_q_sp6_buy_flow(
        self, *, bargain: bool = True, refuse_paid: bool = False, stop_at_legend: bool = False
    ) -> NavigationResult:
        """Reach the merchant and open his shop, bargaining only to buy.

        砍价 (costs currency) only discounts purchases; selling goes through
        the menu's plain 商店 option instead (user, 2026-09-27).
        """

        # The 问题摘要 shows 当前阶段; the story-card entry leaves its own
        # (寻找快速切换按钮) behind, which read as the failing step (Leo's 2K
        # and a player's report, 2026-10-16/17).
        self._status("当前阶段", self._merchant_stage())
        self._status("导航状态", "识别商人互动按钮")
        shop_opened = self._enter_q_sp6_shop(
            Q_SP6_SHOP_PRIORITY_TIMEOUT,
            log_timeout=False,
        )
        if not shop_opened:
            arrived = self.go_to_trade_merchant()
            if not arrived.success:
                return arrived
            self._status("当前阶段", self._merchant_stage())
            shop_opened = self._enter_q_sp6_shop(
                MERCHANT_NAV_LANDMARK_TIMEOUT,
                log_timeout=True,
            )
            if not shop_opened:
                return NavigationResult(False, self.classify(), MERCHANT_PROMPT_FAILURE_MESSAGE)

        self.task.sleep(Q_SP6_BARGAIN_RECHECK_DELAY)
        self._status("当前阶段", SHOP_ENTRY_STAGE)
        self._status("导航状态", "确认砍价入口")
        if not self._confirm_merchant_menu():
            return NavigationResult(False, self.classify(), "商店页面未识别到砍价入口")
        # The plain shop never asks 是否关闭折扣商店; remember so leaving it
        # does not wait for that dialog.
        self.shop_bargained = bargain
        if not bargain:
            if not self._click_plain_shop_option():
                return NavigationResult(False, self.classify(), "商人菜单未找到「商店」选项")
            if not self._wait_for_bargain_shop_confirmation(reclick_plain_option=True):
                return NavigationResult(False, self.classify(), "进入商店后未通过OCR确认商店页面")
            return NavigationResult(True, ScreenState.SHOP, "已进入商店（未砍价）")
        return self.bargain_in_menu(refuse_paid=refuse_paid, stop_at_legend=stop_at_legend)

    def bargain_in_menu(
        self, *, refuse_paid: bool = False, stop_at_legend: bool = False
    ) -> NavigationResult:
        """From the open merchant menu: press 砍价, confirm, reach the discount shop."""

        self.shop_bargained = True
        self.task.sleep(Q_SP6_BARGAIN_CLICK_DELAY)
        if stop_at_legend and self._bargain_card_is_legend():
            return NavigationResult(False, ScreenState.MERCHANT_DIALOG, BARGAIN_LEGEND_MESSAGE)
        self.task.operate_click(*BARGAIN_POINT, after_sleep=0.0)

        bargain_tip = "使用砍价技能后可享受商店折扣价"
        tip = self._wait_for_bargain_tip(bargain_tip)
        if tip == "upgrade":
            return NavigationResult(False, self.classify(), BARGAIN_UPGRADE_MESSAGE)
        if tip != "tip":
            return NavigationResult(False, self.classify(), "未识别到砍价技能折扣说明")
        if refuse_paid and self._bargain_popup_names_paid_currency():
            return NavigationResult(False, self.classify(), BARGAIN_PAID_MESSAGE)
        self.task.operate_click(*BARGAIN_CONFIRM_POINT, after_sleep=0.0)
        if not self._wait_for_bargain_shop_confirmation():
            return NavigationResult(
                False,
                self.classify(),
                "砍价确认后未通过OCR确认商店页面",
            )
        return NavigationResult(True, ScreenState.SHOP, "已通过OCR确认商店页面")

    def _bargain_card_is_legend(self) -> bool:
        """The 砍价 talent card shows 传说 under it (any of two reads)."""
        for read in range(BARGAIN_LEGEND_READS):
            if read:
                self.task.sleep(0.3)
            if self._legend_under_bargain_card(self.vision.capture()):
                self._status("砍价技能等级", "传说")
                return True
        self._status("砍价技能等级", "未到传说")
        return False

    def _legend_under_bargain_card(self, frame) -> bool:
        height, width = frame.shape[:2]
        boxes = []
        for box in self.vision.ocr_boxes(
            frame, "砍价技能卡等级", relative_roi=TRADE_MERCHANT_TALENTS_REGION
        ):
            center = self._ocr_box_center(box)
            if center is None:
                continue
            text = normalize_text(self.vision.simplify(getattr(box, "name", "")))
            boxes.append((text, center))
        # The card is about 120 px wide at 1080p (6.4 % of the width); its rank
        # sits about 70 px below the skill name (live 4K 2026-10-11).
        half_card = width * 0.032
        below = height * 0.12
        for text, (x, y) in boxes:
            if "砍价" not in text or "天赋" in text:
                continue
            if BARGAIN_LEGEND_RANK in text:
                return True
            for other, (ox, oy) in boxes:
                if (
                    BARGAIN_LEGEND_RANK in other
                    and abs(ox - x) <= half_card
                    and 0 < oy - y <= below
                ):
                    return True
        return False

    def _bargain_popup_names_paid_currency(self) -> bool:
        popup = getattr(self, "bargain_popup_text", "") or ""
        popup = normalize_text(self.vision.simplify(popup))
        return any(word in popup for word in BARGAIN_PAID_WORDS)

    def _enter_q_sp6_shop(
        self,
        timeout: float,
        *,
        log_timeout: bool,
        interval: float = 0.5,
    ) -> bool:
        if not self._click_merchant_interaction(
            timeout,
            after_sleep=0.0,
            interval=interval,
        ):
            if getattr(self, "_merchant_prompt_unread", False) and self.task.tap_key(
                MERCHANT_TALK_KEY, after_sleep=0.0
            ):
                # 砍价 read next (_confirm_merchant_menu) proves the menu opened.
                self._status("商店进入", f"商人互动按钮读不到，已按 {MERCHANT_TALK_KEY} 键")
                return True
            if log_timeout:
                self.task.log_warning(f"跑商：{MERCHANT_PROMPT_FAILURE_MESSAGE}。")
            return False
        self._status("商店进入", "成功，已点击商人互动按钮")
        return True

    def _wait_for_bargain_tip(self, bargain_tip: str, timeout: float = 10.0) -> str:
        """tip / upgrade / none after pressing the 砍价 card.

        Once the skill has enough experience the game refuses to bargain, the
        menu closes and the character says 可以强化砍价了 until the player stars
        the skill up (live 2026-09-28).
        """
        started = monotonic()
        end_at = started + timeout
        menu_hits = 0
        reclicked = False
        while True:
            passed, text = self._ocr_keywords_in_frame(
                self.vision.capture(), (bargain_tip,), "砍价说明"
            )
            self.bargain_popup_text = text or ""
            if passed:
                return "tip"
            if BARGAIN_UPGRADE_HINT in normalize_text(text):
                return "upgrade"
            if monotonic() >= end_at:
                return "none"
            # A swallowed 砍价 press leaves the menu up with no tip; press it
            # once more only while that menu is still read.
            menu_hits = menu_hits + 1 if "砍价" in normalize_text(text) else 0
            if (
                not reclicked
                and menu_hits >= SHOP_ENTRY_RECLICK_HITS
                and monotonic() - started >= SHOP_ENTRY_RECLICK_AFTER
            ):
                reclicked = True
                menu_hits = 0
                self._status("商店进入", "砍价说明未出现，菜单仍在，补点一次砍价")
                self.task.operate_click(*BARGAIN_POINT, after_sleep=0.0)
            self.task.sleep(0.5)

    def _click_plain_shop_option(self, timeout: float = PLAIN_SHOP_OPTION_TIMEOUT) -> bool:
        """Press the merchant menu's 商店 option (no bargain).

        The 对话/商店 bubbles pop up about a second after the talent cards
        (live 2026-09-27: read empty at once, readable a second later), so
        they are polled.
        """

        end_at = monotonic() + timeout
        while True:
            frame = self.vision.capture()
            center = self._plain_shop_option_center(frame)
            if center is not None:
                self._status("商店进入", "点击「商店」（卖东西不砍价）")
                self.vision.click_client(center, frame.shape, after_sleep=1.0)
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(0.3)

    def _plain_shop_option_center(self, frame) -> tuple[int, int] | None:
        for box in self.vision.ocr_boxes(
            frame, "商人菜单商店选项", relative_roi=TRADE_MERCHANT_OPTIONS_REGION
        ):
            if normalize_text(self.vision.simplify(getattr(box, "name", ""))) != "商店":
                continue
            return (round(box.x + box.width / 2), round(box.y + box.height / 2))
        return None

    def _confirm_merchant_menu(self) -> bool:
        """Wait for the merchant menu (砍价); re-press his prompt if it stayed.

        A press while the character is still auto-walking to him is ignored
        (live 2026-09-27: the prompt was pressed a second before 已完成自动
        移动 and the menu never opened), so the prompt is pressed again while
        it is still on screen.
        """

        end_at = monotonic() + Q_SP6_BARGAIN_OCR_TIMEOUT
        presses = 0
        while True:
            matched, _text = self._ocr_keywords_in_frame(
                self.vision.capture(), ("砍价",), "砍价入口"
            )
            if matched:
                return True
            if monotonic() >= end_at:
                break
            self.task.sleep(MERCHANT_MENU_RECHECK_SECONDS)
            if presses < MERCHANT_MENU_REPRESSES and self._click_merchant_interaction(
                0.0, after_sleep=0.0
            ):
                presses += 1
                self._status("商店进入", f"菜单未打开，第{presses}次补点商人互动按钮")
        self.task.log_warning("跑商：点击商人后未打开对话/商店菜单（未识别到砍价）。")
        return False

    def _merchant_prompt_box(self, frame):
        """The merchant's interaction prompt, visible only right next to him."""

        pattern = re.compile(MERCHANT_PROMPT_PATTERN)
        for box in self.vision.ocr_boxes(frame, "商人互动按钮", MERCHANT_PROMPT_OCR_ROI):
            text = normalize_text(self.vision.simplify(getattr(box, "name", "")))
            if pattern.search(text):
                return box
        return None

    def _click_merchant_interaction(
        self,
        timeout: float,
        *,
        after_sleep: float,
        interval: float = 0.25,
    ) -> bool:
        """Click the merchant's interaction prompt once it is on screen."""

        end_at = monotonic() + max(0.0, timeout)
        while True:
            frame = self.vision.capture()
            box = self._merchant_prompt_box(frame)
            if box is not None:
                center = (round(box.x + box.width / 2), round(box.y + box.height / 2))
                self._status("商人交互点击位置", f"center=({center[0]},{center[1]})")
                self.vision.click_client(center, frame.shape, after_sleep=after_sleep)
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(interval)

    def go_to_trade_merchant(self) -> NavigationResult:
        """Stand next to the merchant in the square.

        Already next to him: done.  Otherwise enter 梦幻广场 from 主页 (Leo
        2026-10-20: trade there, no cartridge switch after 广场女神像) and send
        away the "!" followers.  Then teleport with the minimap navigation
        menu's 商店 destination, or walk there from the area map's merchant
        icon.  When the square cannot be entered or he cannot be reached in
        it, story cartridge 1 is the other way (Leo 「總有替代方案」).
        """

        self._merchant_prompt_unread = False
        if self._merchant_prompt_box(self.vision.capture()) is not None:
            return NavigationResult(True, ScreenState.SANDBOX, "已在商人旁")
        self._status("导航状态", "进入梦幻广场")
        self._merchant_stage_text = SQUARE_MERCHANT_STAGE
        entered = self._enter_square()
        if entered.success:
            clear = getattr(self.task, "clear_field_followers", None)
            if callable(clear):
                clear()
            if self._reach_merchant_in_field():
                return NavigationResult(True, ScreenState.SANDBOX, "已到达商人旁")
            reason = "广场里没走到商人旁"
            returned = self.return_home()
            if not returned.success:
                return NavigationResult(False, self.classify(), MERCHANT_PROMPT_FAILURE_MESSAGE)
        else:
            reason = f"没能进入梦幻广场（{entered.message}）"
        self.task.log_info(f"跑商：{reason}，改去剧情游戏卡1找商人。")
        self._status("导航状态", "进入剧情游戏卡1")
        self._merchant_stage_text = MERCHANT_STAGE
        entered = self._enter_trade_card()
        if not entered.success:
            return entered
        if not self._reach_merchant_in_field():
            return NavigationResult(False, self.classify(), MERCHANT_PROMPT_FAILURE_MESSAGE)
        return NavigationResult(True, ScreenState.SANDBOX, "已到达商人旁")

    def _merchant_stage(self) -> str:
        return self.__dict__.get("_merchant_stage_text", SQUARE_MERCHANT_STAGE)

    def _reach_merchant_in_field(self) -> bool:
        self._status("当前阶段", self._merchant_stage())
        # The merchant route uses the minimap's ≡ menu (user 2026-09-28).
        self.ensure_small_minimap()
        if self._wait_for_merchant_prompt(2.0):
            return True
        return self._walk_to_merchant()

    def _enter_square(self) -> NavigationResult:
        """From 主页 into 梦幻广场.

        Right after 广场女神像 the recent cartridge is the square, so the
        recent-cartridge press lands there with no quick switch.  Any other
        field: back home, then the 生活玩法 tab's slot 2, as 广场女神像 does.
        """

        returned = self.return_home()
        if not returned.success:
            return returned
        try:
            recent_is_pvp = self.task._recent_cartridge_is_pvp()
        except (AttributeError, RuntimeError):
            recent_is_pvp = True
        if not recent_is_pvp:
            self._status("导航状态", "点最近卡带进梦幻广场")
            recent = CARTRIDGE_RECENT_ENTRY_POINT
            self.task.operate_click(*recent, after_sleep=1.0)  # 不用确认：下面等进场
            landed = self._wait_for_field_or_square()
            if landed == SQUARE_ARRIVED:
                return NavigationResult(True, ScreenState.SANDBOX, "梦幻广场（最近卡带）")
            returned = self.return_home()
            if not returned.success:
                return returned
        menu = self._open_story_quick_switcher("life")
        if not menu.success:
            return menu
        self._status("导航状态", "选择广场卡带")
        self.task.sleep(FIXED_CARTRIDGE_SLOT_PRE_CLICK_DELAY_SECONDS)
        slot = self._square_card_slot()
        self.task.operate_click(*slot, after_sleep=0.0)  # 不用确认：页还在就重点
        for _repress in range(SQUARE_CARD_REPRESSES):
            # A dropped press leaves the selection page as it was.
            self.task.sleep(SQUARE_CARD_REPRESS_SECONDS)
            if not self._wait_for_ocr_keywords(
                QUICK_SWITCH_PAGE_KEYWORDS, 0.5, "卡带选择页", quiet=True
            ):
                break
            self._status("导航状态", "广场卡带点击没反应，再点一次")
            self.task.operate_click(*slot, after_sleep=0.0)  # 不用确认：下面等广场
        if self._wait_for_field_or_square() == SQUARE_ARRIVED:
            return NavigationResult(True, ScreenState.SANDBOX, "梦幻广场")
        return NavigationResult(False, self.classify(), "点广场卡带后没认出梦幻广场")

    def _square_card_slot(self):
        """The square card where its picture is in the 生活玩法 row (a
        player's row can be in another order); slot 2 when it can't be read."""
        cache = self.__dict__.setdefault("_square_templates", {})
        config = getattr(self.task, "config", None)
        score = -1.0
        for look in range(2):
            if look:
                self.task.sleep(1.0)
            point, score = square_card_point(self.vision.capture(), config, cache)
            if point is not None:
                return point
        self._status("导航状态", f"没认出广场卡带的图（{score:.2f}），点第2格")
        return SQUARE_CARTRIDGE_SLOT_POINT

    def _wait_for_field_or_square(self) -> str | None:
        """SQUARE_ARRIVED on two square frames, SQUARE_OTHER_FIELD once a field
        that is not the square has shown for a while, None when the screen
        stopped getting anywhere (loading does not count, Leo 2026-10-15)."""

        cache = self.__dict__.setdefault("_square_templates", {})
        config = getattr(self.task, "config", None)
        wait = ProgressWait(monotonic(), before=scene_at_press(self.task))
        square_hits = 0
        field_since = None
        while True:
            frame = self.vision.capture()
            if square_shown(frame, config, cache):
                square_hits += 1
                if square_hits >= TRADE_CARD_SANDBOX_HITS:
                    return SQUARE_ARRIVED
                continue
            square_hits = 0
            loading = self._black_frame(frame)
            state = ScreenState.LOADING if loading else self.classify(frame)
            now = monotonic()
            if state == ScreenState.SANDBOX:
                field_since = now if field_since is None else field_since
                if now - field_since >= SQUARE_ICON_GRACE_SECONDS:
                    return SQUARE_OTHER_FIELD
            else:
                field_since = None
            if wait.over(frame, now, loading=loading):
                return None
            self.task.sleep(0.5)

    def _enter_trade_card(self) -> NavigationResult:
        """Click story card 1 and wait for its field.

        The shared story entry (select_card) also demands the map-collection
        skill icons in skill group 1, which trade players need not have (the
        user keeps cooking there); the field HUD is enough here.
        """

        located = self._locate_story_card(MERCHANT_CARD_ID)
        if isinstance(located, NavigationResult):
            return located
        confirmed = self._confirm_story_badge_before_click(located.frame, located.badge)
        if confirmed is None:
            return NavigationResult(
                False, ScreenState.CARD_MENU, "剧情游戏卡1点击前角标复核失败，已停止点击"
            )
        badge_frame, badge = confirmed
        self.vision.click_client(badge.best.result.center, badge_frame.shape, after_sleep=1.0)
        # Loading does not count as stuck (Leo 2026-10-15 「我說的10秒是卡死
        # 或者辨識不到」): 2K 10-15 the field came 13 s after the click and was
        # given up on at 10 s.
        wait = ProgressWait(monotonic(), before=scene_at_press(self.task))
        hits = 0
        while True:
            frame = self.vision.capture()
            # The black loading screen needs no full classify: each pass took
            # ~3 s there, so only 3 looks fit.
            state = ScreenState.LOADING if self._black_frame(frame) else self.classify(frame)
            if state == ScreenState.SANDBOX:
                hits += 1
                if hits >= TRADE_CARD_SANDBOX_HITS:
                    dismiss_once_per_run(self)
                    return NavigationResult(True, ScreenState.SANDBOX, MERCHANT_CARD_ID)
                continue  # the field is read: take the second frame at once
            hits = 0
            if wait.over(frame, monotonic(), loading=state == ScreenState.LOADING):
                break
            self.task.sleep(0.5)
        return NavigationResult(False, self.classify(), "剧情游戏卡1入场确认超时")

    def _wait_for_merchant_prompt(self, timeout: float, interval: float = 0.5) -> bool:
        """The merchant's prompt within ``timeout``; a walk there keeps the
        screen moving, one still for STUCK_SECONDS is not getting there."""
        end_at = monotonic() + max(0.0, timeout)
        still = StillTimer()
        while True:
            frame = self.vision.capture()
            if self._merchant_prompt_box(frame) is not None:
                return True
            now = monotonic()
            if now >= end_at or still.still_for(frame, now) >= STUCK_SECONDS:
                return False
            self.task.sleep(interval)

    def _walk_to_merchant(self) -> bool:
        self._status("导航状态", "小地图导航到商店")
        if not self._open_minimap_nav_menu():
            # Second way there (Leo 「每個辨識都要有備案」): the area map's
            # merchant icon.  The ≡ button drew an orange 「!」 on the 2K PC
            # (10-16) and v0.1.42 had no fallback for it; Leo's 2K 一键日常
            # failed 跑商 买 here on 10-17 (cause not proven: no log).
            self._status("导航状态", "未识别到小地图导航按钮，改点地图商人图标")
            if not self._walk_via_area_map():
                self.task.log_warning("跑商：小地图导航按钮和地图商人图标都没找到，无法前往商店。")
                return False
            outcome = "walked"
        elif not self._click_merchant_nav_destination():
            # 商店 unread in the ≡ list (Leo 2026-10-20 「讀不到也要有備案」).
            self._status("导航状态", "导航菜单读不到商店，改点地图商人图标")
            if not self._walk_via_area_map():
                return False
            outcome = "walked"
        else:
            outcome = self._confirm_travel()
        if outcome == "stuck":
            return False
        if outcome == "unreachable":
            self._status("导航状态", "已在商店区域，改点地图商人图标")
            if not self._walk_via_area_map():
                return False
        elif (
            outcome != "walked"
            and not self._wait_for_merchant_prompt(MERCHANT_QUICK_ARRIVAL_TIMEOUT)
            and self.classify() == ScreenState.SANDBOX
        ):
            # Inside the shop but away from the merchant, 立即前往 moves
            # nothing and no toast says so (live 2026-09-27): walk there via
            # the area map's merchant icon, as the user does.
            if self._in_square_now():
                # 梦幻广场: 立即前往 always ends next to 洛兹, but another
                # player's name can sit over his prompt (live 1080p
                # 2026-10-20), and the square's map has no merchant icon.
                # The talk key F reaches him; the menu read decides.
                self._merchant_prompt_unread = True
                self.task.log_info("跑商：广场前往商店后读不到商人名字，改用 F 键和他说话。")
                return True
            self._status("导航状态", "前往后未到商人旁，改点地图商人图标")
            if not self._walk_via_area_map():
                return False
        if self._wait_for_merchant_prompt(MERCHANT_ARRIVAL_TIMEOUT):
            return True
        if self.classify() == ScreenState.SANDBOX:
            # The trip ended in the field but his name over the prompt never
            # read (Leo 2026-10-20 「點不到商人怎麼辦」): the game's own talk
            # key F reaches him; the menu read that follows decides.
            self._merchant_prompt_unread = True
            self.task.log_info(
                f"跑商：前往商店后{MERCHANT_PROMPT_FAILURE_MESSAGE}，改用 F 键和他说话。"
            )
            return True
        self.task.log_warning(f"跑商：前往商店后{MERCHANT_PROMPT_FAILURE_MESSAGE}。")
        return False

    def _in_square_now(self) -> bool:
        return square_shown(
            self.vision.capture(),
            getattr(self.task, "config", None),
            self.__dict__.setdefault("_square_templates", {}),
        )

    def _click_merchant_nav_destination(self) -> bool:
        """在导航菜单中 OCR 点击"商店"目的地。"""

        end_at = monotonic() + MERCHANT_NAV_MENU_OCR_TIMEOUT
        while monotonic() <= end_at:
            if self.vision.click_ocr(
                [r"商店"],
                roi=MERCHANT_NAV_MENU_OCR_ROI,
                after_sleep=0.8,
                name="商店导航",
            ):
                return True
            self.task.sleep(MERCHANT_NAV_MENU_OCR_INTERVAL)
        self.task.log_warning("跑商：小地图导航菜单未识别到商店目的地。")
        return False

    def _confirm_travel(self) -> str:
        """Handle what follows a travel choice.

        Returns "moving" after pressing the optional 确认 (hidden when the
        user ticked 不再显示, then travel starts at once), "unreachable"
        when the game says the destination is the current area, and "stuck"
        when the dialog stayed up (it is cancelled, never left open).
        """

        end_at = monotonic() + MERCHANT_NAV_OUTCOME_TIMEOUT
        dialog_up = False
        while monotonic() <= end_at:
            frame = self.vision.capture()
            toast = self.vision.ocr_text(frame, "导航提示", roi=MERCHANT_NAV_TOAST_OCR_ROI)
            if MERCHANT_NAV_UNREACHABLE_KEYWORD in normalize_text(toast):
                return "unreachable"
            title = normalize_text(
                self.vision.ocr_text(frame, "前往确认", roi=MERCHANT_TRAVEL_DIALOG_OCR_ROI)
            )
            dialog_up = any(keyword in title for keyword in MERCHANT_TRAVEL_DIALOG_KEYWORDS)
            if dialog_up:
                if self.vision.click_ocr(
                    [r"确认"],
                    roi=MERCHANT_NAV_CONFIRM_OCR_ROI,
                    after_sleep=0.8,
                    name="前往确认按钮",
                ):
                    return "moving"
            self.task.sleep(MERCHANT_NAV_MENU_OCR_INTERVAL)
        if dialog_up:
            self.vision.click_ocr(
                [r"^取消$"], roi=MERCHANT_NAV_CONFIRM_OCR_ROI, after_sleep=0.8, name="前往取消按钮"
            )
            self.task.log_warning("跑商：前往确认弹窗的「确认」读不到，已取消。")
            return "stuck"
        return "moving"

    def _walk_via_area_map(self) -> bool:
        """Area map → the merchant's money-bag icon → the trip there.

        Every read has a second way (Leo 2026-10-20): the map opens from the
        minimap, else its key M; the icon is the 卢戈商店 or the square crop,
        else, on the square's map, its remembered place."""
        self.task.operate_click(
            MINIMAP_CENTER_REFERENCE[0] / 1920,
            MINIMAP_CENTER_REFERENCE[1] / 1080,
            after_sleep=1.5,
        )
        map_open = self._area_map_open(AREA_MAP_OPEN_SECONDS)
        if not map_open:
            self._status("导航状态", f"点小地图没打开地图，改按 {AREA_MAP_KEY} 键")
            tap_key = getattr(self.task, "tap_key", None)
            if callable(tap_key) and tap_key(AREA_MAP_KEY, after_sleep=1.5):
                map_open = self._area_map_open(AREA_MAP_OPEN_SECONDS)
        icon_timeout = MAP_MERCHANT_ICON_TIMEOUT
        for spec in (MAP_MERCHANT_ICON_TEMPLATE, SQUARE_MAP_MERCHANT_ICON_TEMPLATE):
            if self.vision.click_template(spec, timeout=icon_timeout, after_sleep=0.8):
                return self._confirm_travel() != "stuck"
            icon_timeout = 1.0  # the first look already waited for the map
        if map_open == "square":
            self._status("导航状态", "地图上读不到商人图标，点它在广场地图上的固定位置")
            self.task.log_info("跑商：广场地图上读不到商人图标，点它平常的位置。")
            x, y = SQUARE_MAP_MERCHANT_POINT
            self.task.operate_click(x / 1920, y / 1080, after_sleep=0.8)  # 不用确认：等前往
            return self._confirm_travel() != "stuck"
        self.task.log_warning("跑商：区域地图上未识别到商人图标。")
        if map_open:
            self._close_area_map_quietly()
        return False

    def _area_map_open(self, seconds: float) -> str | None:
        """"square" for the square's map, "map" for another, None when
        neither the map's title nor its footer read within ``seconds``."""
        end_at = monotonic() + seconds
        while True:
            frame = self.vision.capture()
            title = normalize_text(
                self.vision.ocr_text(frame, "地图标题", relative_roi=AREA_MAP_TITLE_RELATIVE_ROI)
            )
            footer = normalize_text(
                self.vision.ocr_text(frame, "地图底栏", relative_roi=AREA_MAP_FOOTER_RELATIVE_ROI)
            )
            if "广场" in title:
                return "square"
            if any(word in footer for word in AREA_MAP_FOOTER_KEYWORDS):
                return "map"
            if monotonic() >= end_at:
                return None
            self.task.sleep(0.5)

    def _close_area_map_quietly(self) -> None:
        # Its back arrow; anything left open is closed by the trip home.
        self.vision.click_template(AREA_MAP_BACK_TEMPLATE, timeout=1.0, after_sleep=0.8)

    def wait_for_q_sp6_sandbox(
        self,
        timeout: float,
        *,
        interval: float = 0.25,
    ) -> bool:
        """Confirm the field with the merchant's interaction prompt on screen."""

        self._status("导航状态", "等待商人旁确认")
        end_at = monotonic() + max(0.0, timeout)
        last_state = ScreenState.UNKNOWN
        while True:
            frame = self.vision.capture()
            last_state = self._classify_trade_frame(frame)
            at_merchant = self._merchant_prompt_box(frame) is not None
            self._status(
                "商人旁确认",
                f"state={last_state.value}; merchant={'pass' if at_merchant else 'miss'}",
            )
            if last_state == ScreenState.SANDBOX and (
                at_merchant or getattr(self, "_merchant_prompt_unread", False)
            ):
                # Cooking needs only the field; an unread prompt after the
                # trip there is not a reason to skip it.
                return True
            if monotonic() >= end_at:
                break
            self.task.sleep(interval)
        if timeout > 0:
            # A zero timeout is a single probe (e.g. "already out of the
            # cooking page?"), not a failure worth a warning.
            self.task.log_warning(f"跑商：未同时确认箱庭与商人互动按钮，state={last_state.value}。")
        return False

    def _wait_for_bargain_shop_confirmation(
        self,
        timeout: float | None = None,
        *,
        reclick_plain_option: bool = False,
    ) -> bool:
        """Wait until the discounted shop page is confirmed by stable OCR.

        The bargain popup itself still exposes the shop keywords, so a frame only
        counts when the shop keywords are present and the popup-specific marker is
        absent on consecutive captures. When the daily stock is already sold out
        the purchase-button keyword never appears; the stable sold-out template
        then confirms the page under the same popup exclusion.
        """

        timeout = self._loading_timeout() if timeout is None else float(timeout)
        started = monotonic()
        end_at = started + max(0.0, timeout)
        consecutive_hits = 0
        # A swallowed 确认 / 商店 press leaves the bargain popup or the merchant
        # menu up; it is pressed once more only while that screen is still read.
        before_hits = 0
        reclicked = False
        sold_out_hits = 0
        last_text = ""
        popup_marker = normalize_text(self.vision.simplify(BARGAIN_SHOP_CONFIRM_POPUP_KEYWORD))
        while True:
            frame = self.vision.capture()
            matched, text = self._ocr_keywords_in_frame(
                frame,
                Q_SP6_SHOP_PAGE_KEYWORDS,
                "砍价后商店页面",
            )
            last_text = text or last_text
            normalized = normalize_text(self.vision.simplify(text))
            popup_present = popup_marker in normalized
            if matched and not popup_present:
                consecutive_hits += 1
                self._note_progress()
                sold_out_hits = 0
            else:
                consecutive_hits = 0
                sold_out = self.vision.match(frame, BUY_TO_SELL_SOLD_OUT_TEMPLATE)
                sold_out_passed = not popup_present and self.vision.passes(
                    sold_out,
                    BUY_TO_SELL_SOLD_OUT_TEMPLATE,
                )
                sold_out_hits = sold_out_hits + 1 if sold_out_passed else 0
                self._status(
                    "砍价后商店页面 售罄模板",
                    (
                        f"{'命中' if sold_out_passed else '未命中'} "
                        f"{sold_out_hits}/{BUY_TO_SELL_SOLD_OUT_STABLE_HITS}; "
                        f"popup={'yes' if popup_present else 'no'}; "
                        f"m={sold_out.score:.3f}, p={sold_out.pixel_score:.3f}, "
                        f"z={sold_out.zncc_score:.3f}"
                    ),
                )
            self._status(
                "砍价后商店页面 OCR稳定",
                f"{consecutive_hits}/{BARGAIN_SHOP_CONFIRM_STABLE_HITS}",
            )
            if consecutive_hits >= BARGAIN_SHOP_CONFIRM_STABLE_HITS:
                return True
            if sold_out_hits >= BUY_TO_SELL_SOLD_OUT_STABLE_HITS:
                self.task.log_info(
                    "跑商：未显示一键购买全部收藏，售罄模板已稳定命中，确认当天已购买完。"
                )
                return True
            if monotonic() >= end_at:
                break
            if not reclicked and consecutive_hits == 0:
                before_hits = self._shop_entry_reclick(
                    frame,
                    popup_present,
                    before_hits,
                    reclick_plain_option=reclick_plain_option,
                    may_click=monotonic() - started >= SHOP_ENTRY_RECLICK_AFTER,
                )
                if before_hits < 0:
                    reclicked = True
                    before_hits = 0
            self.task.sleep(Q_SP6_SHOP_PAGE_OCR_INTERVAL)
        self.task.log_warning(f"跑商：砍价确认后未通过OCR确认商店页面，OCR={last_text or '-'}。")
        return False

    def _shop_entry_reclick(
        self,
        frame,
        popup_present: bool,
        hits: int,
        *,
        reclick_plain_option: bool,
        may_click: bool,
    ) -> int:
        """Count frames still showing the pre-click screen; -1 once re-pressed."""

        center = None
        if reclick_plain_option:
            # Only probe the menu once a re-press could follow (keeps the
            # normal path to one OCR per frame).
            center = self._plain_shop_option_center(frame) if may_click else None
            still_before = center is not None
        else:
            still_before = popup_present
        hits = hits + 1 if still_before else 0
        if not may_click or hits < SHOP_ENTRY_RECLICK_HITS:
            return hits
        if reclick_plain_option:
            self._status("商店进入", "商店页面未出现，菜单仍在，补点一次「商店」")
            self.vision.click_client(center, frame.shape, after_sleep=0.0)
        else:
            self._status("商店进入", "砍价弹窗仍在，补点一次确认")
            self.task.operate_click(*BARGAIN_CONFIRM_POINT, after_sleep=0.0)
        return -1

    def _click_shop_close_control(self, after_sleep: float = 0.0) -> None:
        """Click the discount shop close control, template-first with a calibrated fallback."""

        for attempt in range(1, SHOP_CLOSE_CLICK_RETRIES + 1):
            frame = self.vision.capture()
            for spec in DISCOUNT_SHOP_CLOSE_CONTROL_TEMPLATES:
                result = self.vision.match(frame, spec)
                passed = self.vision.passes(result, spec)
                self._status(
                    spec.name,
                    (
                        f"{'pass' if passed else 'miss'}; "
                        f"match={result.score:.3f}; pixel={result.pixel_score:.3f}; "
                        f"zncc={result.zncc_score:.3f}"
                    ),
                )
                if passed:
                    self._status(
                        "折扣商店关闭按钮",
                        f"center=({result.center[0]},{result.center[1]})",
                    )
                    self.vision.click_client(
                        result.center,
                        frame.shape,
                        after_sleep=after_sleep,
                    )
                    return
            if attempt < SHOP_CLOSE_CLICK_RETRIES:
                self.task.sleep(SHOP_CLOSE_CLICK_INTERVAL)
        self._status("折扣商店关闭按钮", "模板未命中，回退到标定相对点(82,36)")
        self.vision.click_reference(
            *DISCOUNT_SHOP_CLOSE_CONTROL_REFERENCE_POINT,
            after_sleep=after_sleep,
        )

    def _click_chapter_home_button(self, after_sleep: float = 0.0) -> None:
        """Click the chapter home button, template-first with a calibrated fallback."""

        for attempt in range(1, SHOP_CLOSE_CLICK_RETRIES + 1):
            frame = self.vision.capture()
            for spec in CHAPTER_HOME_TEMPLATES:
                result = self.vision.match(frame, spec)
                passed = self.vision.passes(result, spec)
                self._status(
                    spec.name,
                    (
                        f"{'pass' if passed else 'miss'}; "
                        f"match={result.score:.3f}; pixel={result.pixel_score:.3f}; "
                        f"zncc={result.zncc_score:.3f}"
                    ),
                )
                if passed:
                    self._status(
                        "箱庭主页按钮",
                        f"center=({result.center[0]},{result.center[1]})",
                    )
                    self.vision.click_client(
                        result.center,
                        frame.shape,
                        after_sleep=after_sleep,
                    )
                    return
            if attempt < SHOP_CLOSE_CLICK_RETRIES:
                self.task.sleep(SHOP_CLOSE_CLICK_INTERVAL)
        self._status("箱庭主页按钮", "模板未命中，回退到标定相对点(1797,63)")
        self.task.operate_click(*CHAPTER_HOME_POINT, after_sleep=after_sleep)

    def return_home(self) -> NavigationResult:
        """Go home from whatever trade screen is left, in up to three passes."""

        result = NavigationResult(False, ScreenState.UNKNOWN, "未尝试返回主页")
        for attempt in range(1, RETURN_HOME_PASSES + 1):
            result = self._return_home_pass()
            if result.success:
                return result
            if attempt < RETURN_HOME_PASSES:
                self.task.log_info(f"跑商：第{attempt}次返回主页未完成（{result.message}），再试。")
                self.task.sleep(1.0)
        return result

    def _discount_close_dialog_shown(self) -> bool:
        shown, _ = self._ocr_keywords_in_frame(
            self.vision.capture(),
            DISCOUNT_SHOP_CLOSE_KEYWORDS,
            "返回前折扣商店关闭确认",
            relative_roi=DISCOUNT_SHOP_CLOSE_DIALOG_REGION,
        )
        return shown

    def _merchant_menu_shown(self) -> bool:
        # The shared classify reads the merchant's 对话/商店 menu as SHOP.
        return self.classify_trade() == ScreenState.MERCHANT_DIALOG

    def _return_home_pass(self) -> NavigationResult:
        if self._discount_close_dialog_shown():
            # Answer an already-open 折扣商店结束 dialog first: a click
            # outside it could cancel it instead.
            self.task.operate_click(*DISCOUNT_SHOP_CLOSE_POINT, after_sleep=0.8)
        cancel_auto_move = getattr(self, "_cancel_auto_move_dialog", None)
        if callable(cancel_auto_move):
            # A 自动移动 dialog over the map hides it from classify (YES-BD2 #24).
            cancel_auto_move()
        state = self.classify()
        if state == ScreenState.UNKNOWN:
            # A field battle (a monster beside the spawn point) has no way
            # home of its own: run away, then go on from the field (bd2
            # session 2026-10-22, 循环砍价 and 跑图 stopped in one).
            leave = getattr(self.task, "leave_field_battle", None)
            if callable(leave) and leave("跑商返回主页") == "left":
                state = self.classify()
        # The merchant menu can classify as SHOP (its 商店 bubble) or as
        # UNKNOWN (live 2026-09-27, a failed sell left it open).
        if state in {ScreenState.SHOP, ScreenState.UNKNOWN} and self._merchant_menu_shown():
            state = ScreenState.MERCHANT_DIALOG
        if state == ScreenState.HOME:
            return NavigationResult(True, state)
        if state in {ScreenState.MERCHANT_DIALOG, ScreenState.COOKING}:
            if state == ScreenState.MERCHANT_DIALOG:
                # The merchant's 对话/商店 menu closes with the shop's
                # top-left control, back to the field.
                self._click_shop_close_control(after_sleep=0.8)
            else:
                # Confirmed cooking page: its back arrow goes from the detail
                # to the list, and from the list to the field.
                self.task.operate_click(*COOKING_BACK_POINT, after_sleep=0.8)
            left = state
            state = self.wait_state(
                {ScreenState.HOME, ScreenState.SANDBOX}, RETURN_HOME_STEP_TIMEOUT
            )
            if state == ScreenState.HOME:
                return NavigationResult(True, state)
            if state != ScreenState.SANDBOX:
                return NavigationResult(False, state, f"离开{left.value}后尚未回到箱庭")
        if state == ScreenState.SHOP:
            return self._return_home_from_discount_shop()
        if state == ScreenState.CARD_MENU:
            # The quick bar left open after reading the last card's badges
            # (live 2K 2026-09-30: three passes found no path, then generic
            # recovery pressed this same back arrow ~13 s later).
            self.task.operate_click(*QUICK_SWITCH_BACK_RELATIVE_POINT, after_sleep=0.8)
            state = self.wait_state(
                {ScreenState.HOME, ScreenState.SANDBOX}, RETURN_HOME_STEP_TIMEOUT
            )
            if state == ScreenState.HOME:
                return NavigationResult(True, state)
        if state in {ScreenState.AREA_MAP, ScreenState.SANDBOX_MAP}:
            expected_modes = (
                {
                    MapPageMode.DIRECT_TELEPORT,
                    MapPageMode.GENERATE_TELEPORT,
                }
                if state == ScreenState.AREA_MAP
                else {MapPageMode.SANDBOX_LARGE_MAP}
            )
            closed = self._close_confirmed_map_page(
                expected_modes,
                timeout=self._loading_timeout(),
            )
            if not closed.success:
                return NavigationResult(
                    False,
                    closed.state,
                    f"返回主页前关闭地图页面失败：{closed.message}",
                    map_page_mode=closed.map_page_mode,
                )
            state = ScreenState.SANDBOX
        if state == ScreenState.LOADING:
            state = self.wait_state(
                {ScreenState.HOME, ScreenState.SANDBOX},
                self._loading_timeout(),
            )
            if state == ScreenState.HOME:
                return NavigationResult(True, state)
        if state != ScreenState.SANDBOX:
            return NavigationResult(
                False,
                state,
                "当前页面没有已确认的安全返回路径，未执行点击",
            )

        self._click_chapter_home_button()
        if self._wait_for_cartridge_home(
            timeout=RETURN_HOME_TIMEOUT,
            allow_return_announcement_cleanup=True,
        ):
            return NavigationResult(True, ScreenState.HOME, "已从箱庭返回主页")
        home_by_key = getattr(self.task, "home_by_key", None)
        if callable(home_by_key) and home_by_key(
            lambda seconds: self._wait_for_cartridge_home(
                timeout=seconds, allow_return_announcement_cleanup=True
            ),
            "箱庭返回主页",
        ):
            return NavigationResult(True, ScreenState.HOME, "已用快捷键 H 从箱庭返回主页")
        return NavigationResult(
            False,
            self.classify(),
            "点击一次箱庭主页按钮后未在10秒内确认主页",
        )

    def _close_shop_to_field(self) -> NavigationResult:
        """Close the shop and the merchant menu, back to the field beside him."""

        if not self._close_sale_dialog_before_return():
            return NavigationResult(False, ScreenState.SHOP, "返回前未确认出售弹窗已关闭")
        self._click_shop_close_control()
        # Only the bargained (discount) shop asks 是否关闭折扣商店; the plain
        # shop used for selling closes straight back to the merchant menu.
        if getattr(self, "shop_bargained", True) and self._wait_for_ocr_keywords(
            DISCOUNT_SHOP_CLOSE_KEYWORDS,
            DISCOUNT_SHOP_CLOSE_TIMEOUT,
            "折扣商店关闭确认",
            interval=0.25,
            relative_roi=DISCOUNT_SHOP_CLOSE_DIALOG_REGION,
            quiet=True,
        ):
            self.task.operate_click(*DISCOUNT_SHOP_CLOSE_POINT, after_sleep=0.8)
        elif not wait_for(
            # The discount shop closed earlier this visit asks nothing: the
            # merchant menu comes straight back, a moment later (live 2K
            # 2026-10-22: read once mid-change, a whole return pass redone).
            lambda: self.classify_trade() in (ScreenState.MERCHANT_DIALOG, ScreenState.SANDBOX),
            MERCHANT_BACK_LOOK_SECONDS,
            sleep=self.task.sleep,
            poll=0.4,
            clock=monotonic,
        ):
            return NavigationResult(
                False,
                self.classify(),
                "点击返回后未识别到折扣商店关闭确认",
            )
        self._click_shop_close_control(after_sleep=0.8)
        return NavigationResult(True, ScreenState.SANDBOX, "已关闭商店")

    def close_discount_shop_to_menu(self) -> NavigationResult:
        """Close only the discount shop; stay in the merchant's 砍价 menu.

        Leo (2026-10-11): the bargain loop must not leave and talk to the
        merchant again; closing the discount shop lands back on his menu.
        """

        if not self._close_sale_dialog_before_return():
            return NavigationResult(False, ScreenState.SHOP, "关闭前未确认出售弹窗已关闭")
        self._click_shop_close_control()
        if not self._wait_for_ocr_keywords(
            DISCOUNT_SHOP_CLOSE_KEYWORDS,
            DISCOUNT_SHOP_CLOSE_TIMEOUT,
            "折扣商店关闭确认",
            interval=0.25,
            relative_roi=DISCOUNT_SHOP_CLOSE_DIALOG_REGION,
            quiet=True,
        ):
            if self._menu_bargain_readable():
                return NavigationResult(True, ScreenState.MERCHANT_DIALOG, "已回到商人菜单")
            return NavigationResult(
                False, self.classify(), "点击返回后未识别到折扣商店关闭确认"
            )
        self.task.operate_click(*DISCOUNT_SHOP_CLOSE_POINT, after_sleep=0.8)  # 不用确认：下一行读商人菜单
        if self._menu_bargain_readable():
            return NavigationResult(True, ScreenState.MERCHANT_DIALOG, "已回到商人菜单")
        return NavigationResult(False, self.classify(), "关闭折扣商店后没看到商人菜单（砍价）")

    def _menu_bargain_readable(self, timeout: float = Q_SP6_BARGAIN_OCR_TIMEOUT) -> bool:
        end_at = monotonic() + timeout
        while True:
            # Read the 砍价 talent card itself, not anywhere on screen: the
            # discount shop page must not pass for the menu.
            matched, _text = self._ocr_keywords_in_frame(
                self.vision.capture(),
                ("砍价",),
                "商人菜单砍价",
                relative_roi=TRADE_MERCHANT_TALENTS_REGION,
            )
            if matched:
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(0.5)

    def leave_shop_to_merchant(self) -> NavigationResult:
        """After buying, stand beside the merchant again (cooking follows)."""

        closed = self._close_shop_to_field()
        if not closed.success:
            return closed
        if self._wait_for_merchant_prompt(MERCHANT_NAV_LANDMARK_TIMEOUT):
            return NavigationResult(True, ScreenState.SANDBOX, "已关闭商店，回到商人旁")
        return NavigationResult(False, self.classify(), "关闭商店后未回到商人旁")

    def _return_home_from_discount_shop(self) -> NavigationResult:
        closed = self._close_shop_to_field()
        if not closed.success:
            return closed
        self._click_chapter_home_button()
        if self._wait_for_cartridge_home(
            timeout=RETURN_HOME_TIMEOUT,
            allow_return_announcement_cleanup=True,
        ):
            return NavigationResult(True, ScreenState.HOME, "已关闭折扣商店并返回主页")
        return NavigationResult(False, self.classify(), "关闭折扣商店后未在10秒内返回主页")

    def _close_sale_dialog_before_return(self) -> bool:
        def read_dialog() -> str:
            return normalize_text(self.vision.ocr_text(
                self.vision.capture(), "返回前出售弹窗", relative_roi=SALE_DIALOG_REGION,
            ))

        text = read_dialog()
        if "拥有" not in text and "可购买" not in text:
            return True
        if not (
            SALE_OWNED_PATTERN.search(text)
            and SALE_AVAILABLE_PATTERN.search(text)
            and "出售" in text
        ):
            return False
        self.task.operate_click(*SALE_CLOSE_POINT, after_sleep=0.5)
        end_at = monotonic() + SALE_DIALOG_TIMEOUT
        stable_hits = 0
        while True:
            text = read_dialog()
            closed = bool(text) and "拥有" not in text and "可购买" not in text
            stable_hits = stable_hits + 1 if closed else 0
            if stable_hits >= 2:
                return True
            if monotonic() >= end_at:
                return False
            self.task.sleep(SALE_OCR_INTERVAL)
