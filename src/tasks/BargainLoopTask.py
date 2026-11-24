"""循环砍价: find the chapter-1 merchant, 砍价, close the shop, again.

Leo (2026-10-11): the daily trade's pre-buy steps on a loop, with the number
of rounds set on the 跑商 page.  Each 砍价 gives the skill experience; once
it is full the game refuses and asks for a manual star-up, so the loop stops
there.  Nothing is bought.
"""

from __future__ import annotations

from ok.task.exceptions import FinishedException, TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.MapTradeTask import (
    TRADE_OCR_THRESHOLD_KEY,
    TRADE_VISION_THRESHOLD_KEY,
    MapAutomationTaskBase,
)
from src.tasks.map_trade.models import ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_trade import (
    BARGAIN_LEGEND_MESSAGE,
    BARGAIN_UPGRADE_MESSAGE,
)
from src.tasks.map_trade.vision import Vision
from src.utils.wait_limits import LOADING_MAX_SECONDS

LOOP_COUNT_KEY = "循环次数"
DEFAULT_LOOPS = 10
MAX_LOOPS = 200  # Leo 2026-10-11: at most 200 rounds
FULL_SKILL_MESSAGE = "砍价技能经验满了，要先在游戏里手动升星才能继续砍价"


def loop_count(value) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_LOOPS
    return max(1, min(MAX_LOOPS, count))


class BargainLoopTask(MapAutomationTaskBase):
    """Bargain with 无聊收集狂大叔 a set number of times, buying nothing."""

    recover_home_on_failure = True
    start_from_home = True

    vision_threshold_key = TRADE_VISION_THRESHOLD_KEY
    ocr_threshold_key = TRADE_OCR_THRESHOLD_KEY
    task_log_name = "循环砍价"
    diagnostic_prefix = "bargain_loop"
    status_keys = [
        "状态",
        "当前阶段",
        "导航状态",
        "已砍价次数",
        "Log",
        "Warning",
        "Error",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "循环砍价"
        self.description = "前往第一章商人处反复砍价并关闭商店（不购买商品），用于练习或完成相关任务。"
        self.icon = FluentIcon.SHOPPING_CART
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.visible = False  # run from the 跑商 page
        self.default_config.update(
            {
                LOOP_COUNT_KEY: DEFAULT_LOOPS,
                TRADE_VISION_THRESHOLD_KEY: 0.72,
                TRADE_OCR_THRESHOLD_KEY: 0.20,
                "加载页面等待秒数": LOADING_MAX_SECONDS,
            }
        )
        self.config_description.update(
            {
                LOOP_COUNT_KEY: "完成一次「打开商店 → 砍价 → 关闭」记为 1 次；当砍价技能即将升星时会自动提前停止。",
            }
        )
        self.config_type.update(
            {
                LOOP_COUNT_KEY: {"min": 1, "max": MAX_LOOPS, "step": 1},
                "加载页面等待秒数": {"min": 10.0, "max": 120.0, "step": 1.0},
            }
        )

    def _go_home_before_run(self) -> None:
        # Leo 2026-10-11: a player already standing at 无聊收集狂大叔 (or in
        # his menu) starts bargaining right there, no 主页 and no cartridge.
        self._start_spot = self._merchant_spot()
        if self._start_spot:
            where = "商人菜单" if self._start_spot == "menu" else "商人旁"
            self.log_info(f"循环砍价：已经在{where}，直接开始砍价。")
            return
        super()._go_home_before_run()

    def _merchant_spot(self) -> str:
        """menu / prompt / "" — read before anything is pressed."""
        try:
            navigator = Navigator(self, Vision(self))
            if navigator._merchant_menu_shown() and navigator._menu_bargain_readable(1.0):
                return "menu"
            if navigator._wait_for_merchant_prompt(1.0):
                return "prompt"
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:
            pass  # not read: the usual route from 主页
        return ""

    def run(self):
        total = loop_count(self.config.get(LOOP_COUNT_KEY, DEFAULT_LOOPS))
        navigator = Navigator(self, Vision(self))
        self._done = 0
        self.info_set("已砍价次数", f"0/{total}")
        self.info_set("状态", f"循环砍价启动，共 {total} 次。")
        home = False
        try:
            ok, message = self._loop(navigator, total)
        finally:
            home = self._return_home_after_phases(navigator)
        if not home:
            ok = False
            message = f"{message}；砍完后回不到主页" if message else "砍完后回不到主页"
        done = self._done
        summary = f"循环砍价：完成 {done}/{total} 次。"
        if ok:
            self.info_set("状态", f"{summary}{message}")
            self.log_completion(f"{summary}{message}")
            return True
        self.info_set("状态", f"{summary}停下原因：{message}")
        self.log_warning(f"{summary}停下原因：{message}", notify=True)
        return False

    def _loop(self, navigator, total: int) -> tuple[bool, str]:
        self._done = 0
        # Started in his menu: the first 砍价 is pressed right there.  Started
        # beside him: the buy flow presses his prompt first.
        in_menu = getattr(self, "_start_spot", "") == "menu"
        for round_no in range(1, total + 1):
            # Leo 2026-10-11: after closing the discount shop the merchant
            # menu is still up; bargain again there, no leaving and re-talking.
            if in_menu:
                self.info_set("当前阶段", f"第 {round_no}/{total} 次：在商人菜单砍价")
                entered = navigator.bargain_in_menu(refuse_paid=True, stop_at_legend=True)
            else:
                self.info_set("当前阶段", f"第 {round_no}/{total} 次：找商人并砍价")
                entered = navigator.enter_q_sp6_buy_flow(
                    bargain=True, refuse_paid=True, stop_at_legend=True
                )
            if not entered.success and entered.message == BARGAIN_LEGEND_MESSAGE:
                # Leo 2026-10-11: the goal is 传说; nothing more to train.
                self.log_info(f"循环砍价：{BARGAIN_LEGEND_MESSAGE}。")
                return True, BARGAIN_LEGEND_MESSAGE
            if not entered.success and entered.message == BARGAIN_UPGRADE_MESSAGE:
                # Not a failure: the skill is full, more rounds cannot work.
                self.log_warning(f"循环砍价：{FULL_SKILL_MESSAGE}。", notify=True)
                return True, FULL_SKILL_MESSAGE
            if not entered.success:
                return self._stop_here("enter", f"第 {round_no} 次砍价没成功：{entered.message}")
            if entered.state != ScreenState.SHOP:
                return self._stop_here(
                    "enter", f"第 {round_no} 次砍价后没看到商店页（{entered.state.value}）"
                )
            self.info_set("当前阶段", f"第 {round_no}/{total} 次：关闭商店")
            closed = navigator.close_discount_shop_to_menu()
            # The bargain already counted once the shop opened.
            self._done = round_no
            self.info_set("已砍价次数", f"{round_no}/{total}")
            if closed.success:
                in_menu = True
                continue
            if closed.state == ScreenState.SHOP:
                return self._stop_here("close", f"第 {round_no} 次关闭商店没成功：{closed.message}")
            # The shop is gone but the menu was not read: find him again.
            in_menu = False
            self.log_info(f"循环砍价：{closed.message}，下一次重新找商人。")
        return True, ""

    def _stop_here(self, step: str, message: str) -> tuple[bool, str]:
        """Keep the 问题摘要 frame before going home: the step, why, the screen."""
        self._note_phase_problem("fail", message)
        self._save_diagnostic(f"{self.diagnostic_prefix}_{step}_failed")
        return False, message
