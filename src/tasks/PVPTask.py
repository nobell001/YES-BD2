import re
from pathlib import Path
from time import monotonic

import cv2
import numpy as np
from ok.task.exceptions import FinishedException, TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.BaseBD2Task import (
    FIEND_HUNT_REWARD_TITLE,
    RECENT_CARTRIDGE_SPECIAL_PAGE_MAX_ACTIONS,
    BaseBD2Task,
)
from src.tasks.map_trade.models import MatchResult, TemplateSpec
from src.utils import task_vision
from src.utils.calibration import FHD_1080, HD_720, QHD_1440
from src.utils.cartridge_quick_switch import (
    BATTLE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION,
    BATTLE_GAMEPLAY_CATEGORY_LABEL,
    BATTLE_GAMEPLAY_CATEGORY_OCR_ROI,
    BATTLE_GAMEPLAY_CATEGORY_POINT,
    FIXED_CARTRIDGE_SLOT_PRE_CLICK_DELAY_SECONDS,
    GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO,
    QUICK_SWITCH_SEARCH_REGIONS,
    RECENT_CATEGORY_LABEL,
    STORY_CATEGORY_LABEL,
    category_highlight_ratio,
)
from src.utils.colour_rules import switch_yellow_ratio
from src.utils.free_switch import ensure_free_switch_on
from src.utils.home_confirmation import (
    HOME_DIMMED_P95_THRESHOLD_DEFAULT,
    HOME_GACHA_OCR_REFERENCE_ROI,
    HOME_LEFT_COLUMN_OCR_REFERENCE_ROI,
    HOME_LEFT_COLUMN_REQUIRED_HITS,
    home_confirmation_passes,
    home_gacha_ocr_with_fallback,
    home_left_column_brightness,
    home_left_column_hits,
)
from src.utils.image_utils import (
    reference_roi_frame,
    stabilize_template_match,
)
from src.utils.ocr_utils import normalize_ocr_text
from src.utils.pvp_dialog import (
    MULTIPLIER_RANGE,
    adjust_step,
    parse_battle_count,
    parse_free_cocktails,
    parse_multiplier,
    parse_start_cost,
)
from src.utils.stage_walk import NUDGE_SEQUENCE, find_stage, plan_step

REFERENCE_WIDTH = FHD_1080.width
REFERENCE_HEIGHT = FHD_1080.height
HD720_REFERENCE_WIDTH = HD_720.width
HD720_REFERENCE_HEIGHT = HD_720.height
ENTRY_REFERENCE_WIDTH = QHD_1440.width
ENTRY_REFERENCE_HEIGHT = QHD_1440.height
# 参考系约定：*_SCREEN_* 常量与 *_CLICK_REFERENCE 由 _click_screen_reference /
# _screen_reference_* 按 2560×1440（QHD_1440）归一；带 OCR_REFERENCE_ROI 且经
# _mf_roi 消费的常量是 1280×720（HD_720）参考；其余 *_REFERENCE_* 为 1920×1080。
FREE_AP_SWITCH_SCREEN_ROI = (1680, 535, 120, 55)  # 2560×1440 参考
PVP_RESULT_SCREEN_ROI = (932, 368, 699, 704)  # 2560×1440 参考
PVP_RESULT_CLOSE_SCREEN_POINT = (1585, 410)  # 2560×1440 参考
PVP_FAILURE_LEAVE_REFERENCE_ROI = (696, 952, 535, 87)  # 1920×1080 参考
PVP_SUCCESS_LEAVE_REFERENCE_ROI = (1594, 987, 240, 66)  # 1920×1080 参考
# The PVP hub uses the same top-right sandbox home entry as the validated
# chapter-sandbox calibration.  The old (100, 54) point hovered the applied-
# effects status icon instead of leaving the hub.
PVP_BACK_HOME_REFERENCE_POINT = (1797, 63)  # 1920×1080 参考
# Top-left back arrow of the pre-battle stage screen (same as every page's).
PVP_STAGE_BACK_REFERENCE_POINT = (150, 50)
PVP_CARTRIDGE_SLOT_POINT = (152 / REFERENCE_WIDTH, 970 / REFERENCE_HEIGHT)
PVP_AUTO_BATTLE_SCREEN_ROI = (1470, 910, 170, 150)
# Reference ROI for the multiplier value in the main auto-battle popup. The value
# sits directly left of the settings gear (reference x ≈ 868 at 1280x720); the ROI
# must exclude the gear, otherwise the OCR det box merges it into the value and the
# anchored ^N$ match fails on artifacts such as "1倍a".
PVP_MULTIPLIER_OCR_REFERENCE_ROI = (800, 213, 65, 33)  # 1280×720 参考
PVP_AUTO_BATTLE_CLICK_REFERENCE = (2026, 1291)  # 2560×1440 参考
PVP_STAGE_CLICK_REFERENCE_OFFSET = (0, -75)  # 1920×1080 参考位移
PVP_BATTLE_START_SCREEN_POINT = (1381, 1061)  # 2560×1440 参考
PVP_FREE_AP_SWITCH_SCREEN_POINT = (1732, 557)  # 2560×1440 参考
PVP_FREE_AP_SWITCH_ON_RATIO = 0.05
PVP_FREE_AP_SWITCH_SETTLE_SECONDS = 2.0
PVP_MULTIPLIER_BUTTON_SCREEN_POINT = (1719, 465)  # 2560×1440 参考
PVP_MULTIPLIER_40_OPTION_SCREEN_POINT = (1584, 715)  # 2560×1440 参考
PVP_MULTIPLIER_1_OPTION_SCREEN_POINT = (980, 712)  # 2560×1440 参考
PVP_MULTIPLIER_CONFIRM_SCREEN_POINT = (1383, 1007)  # 2560×1440 参考
# The setting dialog's own 确认, read around the fixed point (1037, 755 at
# 1080p); the main popup underneath has 取消 and 战斗开始 there, no 确认.
PVP_SETTING_CONFIRM_REFERENCE_ROI = (700, 700, 600, 100)  # 1920×1080 参考
PVP_SETTING_CONFIRM_PATTERNS = [r"^确[认定]$"]
PVP_MAX_BATTLE_COUNT_SCREEN_POINT = (1650, 850)  # 2560×1440 参考
PVP_AUTO_BATTLE_MENU_OCR_REFERENCE_ROI = (327, 165, 417, 156)  # 1280×720 参考
PVP_BATTLE_ONGOING_OCR_REFERENCE_ROI = (50, 576, 203, 69)  # 1280×720 参考
PVP_MULTIPLIER_SETTING_OCR_REFERENCE_ROI = (451, 101, 379, 184)  # 1280×720 参考
PVP_MULTIPLIER_SETTING_VALUE_OCR_REFERENCE_ROI = (596, 372, 105, 50)  # 1280×720 参考
PVP_RESULT_BASE_MINUTES = 20.0
# The base covers 40 battles (30 s each), scaled by the count actually set;
# one battle used to get only 30 s and a slow one stopped 一键日常 (audit
# 2026-10-09).  While 正在进行 is read the battle is running, not stuck: the
# wait goes on until it is gone for the stuck time of non-魔兽 battles, up to
# CAP_FACTOR times the wait.
PVP_RESULT_MIN_WAIT_SECONDS = 90.0
PVP_BATTLE_STUCK_SECONDS = 15.0
PVP_RESULT_WAIT_CAP_FACTOR = 2.0
# After a timed-out wait, this many result labels read mean the result popup
# is up but misread: its ✕ is pressed before looking for 离开.
PVP_RESULT_PARTIAL_MATCHES = 2
PVP_RESULT_CLOSE_AFTER_SECONDS = 1.5
PVP_BATTLE_ONGOING_PATTERN = r"正在进行"
# Only the cocktail/AP shortage counts; a stray 不足 anywhere on screen
# while the battle starts must not end the run (review 2026-09-26).
PVP_AP_SHORTAGE_PATTERN = r"鸡尾酒.{0,8}不足|AP.{0,4}不足"
# The shortage popup's other button (补充/购买) spends paid resources: only a
# read 取消/关闭 is ever pressed there, never a fixed point.
PVP_AP_SHORTAGE_CLOSE_PATTERNS = [r"^取消$", r"^关闭$"]
PVP_AP_SHORTAGE_CLOSE_ATTEMPTS = 3
PVP_AP_SHORTAGE_VERIFY_SECONDS = 1.0
# After leaving the result, 确认 is pressed only on these rank pages (same
# frame pairing as BaseBD2Task._pvp_special_page_action); any other 确认
# dialog (e.g. a purchase prompt) is left alone.
PVP_RANK_PAGE_TITLES = ("恭喜晋级", "段位下滑")
PVP_SEASON_REWARD_AFTER_CLICK_SECONDS = 3.0
PVP_RANK_PAGE_AFTER_CLICK_SECONDS = 2.0
PVP_AUTO_BATTLE_MENU_VERIFY_SECONDS = 3.5
# BUG-20260906-01：网络波动会整枪吞掉点击，可验证的单发点击统一按该次数
# 做"点击→确认→失败重试"兜底，BUG-20260908-04 起舞台点击同样适用
# （使者不在台上时首击会被当作移动指令）；确认窗口见各调用点。
PVP_CLICK_VERIFY_ATTEMPTS = 3
# 舞台移动方式：鼠标点击舞台（游戏开启点击移动）或 WASD 走到舞台正中（关闭
# 点击移动的玩家，2026-09-26 实测：踩到红色舞台正中即进入战前画面）。
STAGE_MOVE_CLICK = "鼠标点击舞台"
STAGE_MOVE_WASD = "键盘WASD走到舞台"
STAGE_MOVE_OPTIONS = [STAGE_MOVE_CLICK, STAGE_MOVE_WASD]
STAGE_WALK_MAX_STEPS = 14
# 自动战斗弹窗（1920×1080 参考，2026-09-26 实测）。
PVP_MULTIPLIER_STEP_POINTS = {
    "big_plus": (1034, 534),
    "big_minus": (885, 534),
    "plus": (1242, 637),
    "minus": (677, 637),
}
PVP_COUNT_MIN_POINT = (695, 636)
PVP_COUNT_STEP_POINTS = {
    "big_plus": (1054, 636),
    "big_minus": (874, 636),
    "plus": (1305, 739),
    "minus": (625, 739),
}
PVP_COUNT_ROI = (700, 665, 530, 55)
# How long a 场数 press may take to change the number before it is pressed again.
PVP_COUNT_CONFIRM_SECONDS = 1.0
PVP_START_BUTTON_ROI = (880, 780, 340, 65)
PVP_FREE_COCKTAIL_ROI = (1560, 30, 330, 60)
PVP_DIALOG_CANCEL_POINT = (802, 811)
# A real promotion flow shows the confirm text while the page is still fading
# in. Waiting for a fresh frame avoids clicking a stale/transient OCR result.
PVP_RANK_CONFIRM_SETTLE_SECONDS = 1.5
# 战斗场数: MAX uses up the day's free cocktails (user, 2026-09-27); a number
# fixes the battle count.  The round cap only guards against a loop.
BATTLE_COUNT_MAX = "MAX"
BATTLE_COUNT_OPTIONS = [BATTLE_COUNT_MAX, *(str(count) for count in range(1, 41))]
PVP_MAX_ROUNDS = 12
# Free Blood Cocktails a day: 倍数 x 场数 never asks for more (Leo 2026-10-05:
# 預設40倍 1場，兩個值相乘不可以超出40，不可以花到付費雞尾酒).
FREE_COCKTAILS_PER_DAY = 40


def capped_battle_count(multiplier: int, count: int) -> int:
    """The set count lowered so 倍数 x 场数 <= 40 (0 = MAX stays MAX)."""
    if count <= 0:
        return count
    return max(1, min(count, FREE_COCKTAILS_PER_DAY // max(1, multiplier)))


def battle_count_setting(value) -> int:
    """0 for MAX, else the chosen count."""
    text = str(value).strip().upper()
    if text in ("", BATTLE_COUNT_MAX, "0"):
        return 0
    try:
        return max(0, int(text))
    except ValueError:
        return 0
PVP_HUB_SPECIAL_PAGE_GRACE_SECONDS = 2.0
QUICK_SWITCH_PAGE_PATTERNS = (
    RECENT_CATEGORY_LABEL,
    STORY_CATEGORY_LABEL,
    BATTLE_GAMEPLAY_CATEGORY_LABEL,
)
HOME_GACHA_OCR_ROI = HOME_GACHA_OCR_REFERENCE_ROI
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PROJECT_ROOT / "recognition-assets" / "template-assets"


class PVPTask(BaseBD2Task):
    recover_home_on_failure = True
    start_from_home = True
    status_keys = [
        "启用",
        "状态",
        "当前阶段",
        "目标倍率",
        "主页抽抽乐 OCR 尝试",
        "主页亮度p95",
        "主页抽抽乐 OCR",
        "快速切换按钮",
        "卡带选择页 OCR",
        "卡带选择页 OCR 命中",
        "战斗玩法游戏卡带 OCR",
        "战斗玩法类别高亮",
        "PVP 箱庭",
        "PVP 入场特殊页面模式",
        "PVP 入场特殊页面 OCR",
        "跟随角色按钮",
        "PVP 舞台",
        "PVP 自动战斗 OCR",
        "PVP 自动战斗点击",
        "PVP 免费AP",
        "PVP 倍率 OCR",
        "PVP 开始战斗 OCR",
        "PVP 战斗中 OCR",
        "PVP 结算 OCR",
        "PVP 结算命中",
        "PVP 离开 OCR",
        "PVP 离开点击",
        "PVP 升降级确认 OCR",
        "PVP 升降级确认",
        "PVP 升降级确认稳定",
        "PVP 返回主页",
        "PVP AP不足 OCR",
        "匹配错误",
        "Log",
        "Warning",
        "Error",
    ]

    status_key_labels = {
        "快速切换按钮": "快速切换按钮模板",
        "PVP 箱庭": "PVP 箱庭模板",
        "PVP 舞台": "PVP 舞台模板",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "镜中之战"
        self.description = "进行pvp自动战斗。"
        self.icon = FluentIcon.GAME
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.visible = True
        self._templates: dict[str, tuple[np.ndarray, np.ndarray | None]] = {}
        self._missing_template_names: set[str] = set()
        self._match_error_names: set[str] = set()
        self._match_pause_until = 0.0
        self.default_config.update(
            {
                "启用": True,
                "竞技场战斗倍数": 40,
                "加载页面阈值": 0.72,
                "主页压暗阈值": HOME_DIMMED_P95_THRESHOLD_DEFAULT,
                "PVP OCR 阈值": 0.2,
                "主页确认等待秒数": 10.0,
                "快速卡带等待秒数": 10.0,
                "卡带选择页确认等待秒数": 10.0,
                "玩法类别高亮确认秒数": 3.0,
                "玩法类别高亮像素比例": GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO,
                "PVP 入场等待秒数": 30.0,
                "PVP 菜单等待秒数": 12.0,
                "PVP 战斗开始等待秒数": 30.0,
                "PVP 结算基准等待分钟": PVP_RESULT_BASE_MINUTES,
                "PVP 离开等待秒数": 20.0,
                "PVP 返回箱庭等待秒数": 10.0,
                "PVP 返回主页等待秒数": 20.0,
                "快速切换按钮阈值": 0.88,
                "PVP 箱庭阈值": 0.78,
                "PVP 舞台阈值": 0.72,
                "舞台移动方式": STAGE_MOVE_CLICK,
                "战斗场数": "1",
                "PVP 定位修正阈值": 0.76,
                "loading 出现等待秒数": 6.0,
                "loading 消失等待秒数": 35.0,
            }
        )
        self.config_type.update(
            {
                "舞台移动方式": {"type": "drop_down", "options": STAGE_MOVE_OPTIONS},
                "战斗场数": {"type": "drop_down", "options": BATTLE_COUNT_OPTIONS},
            }
        )
        self.config_description.update(
            {
                "竞技场战斗倍数": (
                    "每场战斗消耗的免费鲜血鸡尾酒倍数，1~40（默认 40）。每天有 40 杯免费鸡尾酒，"
                    "倍数 × 场数不会超过 40，例如 10 倍最多 4 场。AP 不足时会临时降到 1。"
                ),
                "战斗场数": (
                    "自动战斗的场数（默认 1）；MAX 用完当天的免费鸡尾酒。倍数 × 场数超过 40 时自动减少场数。开打前会核对"
                    "「战斗开始」上的消耗 = 倍数 × 场数，且不超过顶部免费鸡尾酒数，"
                    "并确认「仅使用免费鲜血鸡尾酒」已开启，否则取消不打。"
                ),
                "舞台移动方式": (
                    "游戏设置为点击移动时选「鼠标点击舞台」；用 WASD 移动的玩家选"
                    "「键盘WASD走到舞台」，脚本会用键盘把角色走到红色舞台正中。"
                ),
                "PVP OCR 阈值": "镜中之战流程 OCR 使用的最低可信度。",
                "PVP 结算基准等待分钟": (
                    "打 40 场的结算等待时间，实际按场数折算（至少 90 秒）；"
                    "读到「正在进行」时继续等。"
                ),
                "PVP 返回箱庭等待秒数": "离开结算后等待回到 PVP 箱庭的最长时间。",
                "PVP 返回主页等待秒数": "从 PVP 箱庭返回主页后的主页确认最长时间。",
                "主页压暗阈值": "主页左列灰度 p99 低于该值视为被公告压暗（0-255）。",
                "快速切换按钮阈值": "识别 QuickSwitchPlayIco.png 快速切换按钮的模板匹配阈值。",
                "卡带选择页确认等待秒数": (
                    "点击快速切换按钮后，等待 OCR 同时识别最近、剧情游戏卡和"
                    "战斗玩法游戏卡带的时限。"
                ),
                "玩法类别高亮像素比例": (
                    "战斗玩法游戏卡带标签确认为高亮状态所需的最低亮色像素占比。"
                ),
            }
        )

    def run(self):
        if not bool(self.config.get("启用", True)):
            self.info_set("状态", "镜中之战已禁用。")
            self.log_info("镜中之战已禁用。")
            return True

        target_multiplier = self._target_multiplier()
        self.info_set("状态", "镜中之战启动。")
        self.info_set("目标倍率", target_multiplier)
        self.log_info(f"镜中之战：目标倍率 {target_multiplier}。")

        if not self._ensure_pvp_hub():
            self.info_set("状态", "镜中之战失败：未能进入 PVP 箱庭。")
            return False

        current_multiplier = target_multiplier
        self._battle_count_override = None
        max_rounds = PVP_MAX_ROUNDS
        for round_index in range(1, max_rounds + 1):
            self.info_set("当前阶段", f"第 {round_index} 轮")
            start_state = self._start_auto_battle(current_multiplier)
            if start_state == "free_short" and current_multiplier != 1:
                # Leo 2026-09-29: cocktails short of the multiplier -> fight
                # one battle at 1x with what is left.
                self.log_info(
                    f"镜中之战：免费鸡尾酒不够 {current_multiplier} 倍，改用 1 倍打 1 场。"
                )
                current_multiplier = 1
                self._battle_count_override = 1
                self.info_set("目标倍率", current_multiplier)
                continue
            if start_state in ("free_short", "free_empty"):
                self.info_set("状态", "免费鸡尾酒已用完。")
                self.log_completion("镜中之战：今日免费鸡尾酒已用完，流程结束。")
                # Cancelling leaves the pre-battle stage screen: its back
                # arrow returns to the hub (live 2026-09-29).
                self._click_reference(*PVP_STAGE_BACK_REFERENCE_POINT, after_sleep=1.0)
                # Leo 2026-10-05: going back can bring up the rank-down page
                # (段位下滑) here too; it sat on it until he moved the mouse.
                # Confirm it the same way as after a battle.
                self._ensure_pvp_hub_after_leave()
                return self._return_home_from_pvp_hub()
            if start_state in ("ap_depleted", "ap_shortage"):
                # Close the popup before any further stage click or return.
                if not self._close_ap_shortage_popup():
                    self.info_set("状态", "镜中之战失败：AP 不足弹窗未能关闭。")
                    return False
                self._close_auto_battle_dialogs()
            if start_state == "ap_depleted":
                self.info_set("状态", "免费 AP 已耗尽。")
                self.log_completion("镜中之战：免费 AP 已耗尽，流程结束。")
                return True
            if start_state == "ap_shortage":
                if current_multiplier != 1:
                    self.log_info("镜中之战：当前倍率 AP 不足，降到 1 倍打 1 场。")
                    current_multiplier = 1
                    self._battle_count_override = 1
                    self.info_set("目标倍率", current_multiplier)
                    continue
                self.info_set("状态", "1 倍仍 AP 不足。")
                self.log_completion("镜中之战：1 倍 AP 仍不足，流程结束。")
                return True
            if start_state != "started":
                self.info_set("状态", "镜中之战失败：未能开始战斗。")
                return False

            if not self._wait_result_and_leave(current_multiplier):
                self.info_set("状态", "战斗结算或离开失败。")
                return False

            self.info_set("状态", "镜中之战完成并返回主页。")
            self.log_completion("镜中之战：自动战斗完成并返回主页。")
            return True

        self.info_set("状态", "达到最多战斗轮次。")
        self.log_completion(f"镜中之战：达到最多战斗轮次 {max_rounds}，停止。")
        return True

    def _ensure_pvp_hub(self) -> bool:
        self.info_set("当前阶段", "确认镜中之战")
        if self._wait_for_template(
            PVP_MEDALS_TEMPLATE,
            timeout=2.0,
            name="PVP 箱庭",
        ):
            self._clear_pvp_hub_notice_if_present()
            return True

        return self._enter_pvp_from_home()

    def _enter_pvp_from_home(self) -> bool:
        self.info_set("当前阶段", "打开卡带快速切换")
        if not self.open_cartridge_quick_switcher(
            ensure_home=self._wait_for_cartridge_home,
            click_quick_switch=lambda: self._click_template_until(
                QUICK_PACK_TEMPLATE,
                timeout=float(self.config.get("快速卡带等待秒数", 10.0)),
                name="快速切换按钮",
                after_sleep=0.0,
                stabilize=True,
            ),
            confirm_quick_switch_page=self._wait_for_quick_switch_page,
        ):
            self.log_info("镜中之战：未能从主页打开卡带快速切换页面。")
            return False

        self.info_set("当前阶段", "选择战斗玩法游戏卡带")
        self.sleep(0.5)
        # 类别点击被吞时高亮不会变：仅在卡带选择页仍在、类别仍未高亮时重点（同末日之书）。
        for attempt in range(1, PVP_CLICK_VERIFY_ATTEMPTS + 1):
            self.operate_click(*BATTLE_GAMEPLAY_CATEGORY_POINT, after_sleep=0.0)
            if self._wait_for_battle_gameplay_category():
                break
            if attempt >= PVP_CLICK_VERIFY_ATTEMPTS or not self._quick_switch_still_shows(
                highlighted=False, seconds=1.0
            ):
                self.log_info("镜中之战：点击后未确认战斗玩法游戏卡带类别高亮。")
                return False
            self.log_info(f"镜中之战：第{attempt}次点击战斗玩法类别未生效，重试。")

        self.info_set("当前阶段", "选择 PVP 卡带1号位")
        self.sleep(FIXED_CARTRIDGE_SLOT_PRE_CLICK_DELAY_SECONDS)
        self.operate_click(*PVP_CARTRIDGE_SLOT_POINT, after_sleep=0.0)
        # 卡带格点击被吞时选择页原样停住；连续数秒仍是同一页（类别仍高亮）才重点，
        # 页面一变就不再点，避免载入中重复操作。
        for attempt in range(1, PVP_CLICK_VERIFY_ATTEMPTS):
            if not self._quick_switch_still_shows(highlighted=True, seconds=8.0):
                break
            self.log_info(f"镜中之战：第{attempt}次点击 PVP 卡带后选择页仍在，重试。")
            self.operate_click(*PVP_CARTRIDGE_SLOT_POINT, after_sleep=0.0)

        if self._wait_for_pvp_hub_after_cart(
            timeout=float(self.config.get("PVP 入场等待秒数", 30.0)),
        ):
            self._clear_pvp_hub_notice_if_present()
            return True

        return False

    def _wait_for_battle_gameplay_category(self, interval: float = 0.5) -> bool:
        end_at = monotonic() + float(self.config.get("玩法类别高亮确认秒数", 3.0))
        last_text = ""
        last_highlight_ratio = 0.0
        while monotonic() <= end_at:
            frame = self.capture_frame()
            text = self._ocr_text(
                frame,
                name="战斗玩法游戏卡带",
                roi=BATTLE_GAMEPLAY_CATEGORY_OCR_ROI,
            )
            last_text = text or last_text
            last_highlight_ratio = category_highlight_ratio(
                frame,
                BATTLE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION,
            )
            self.info_set("战斗玩法游戏卡带 OCR", text or "-")
            self.info_set("战斗玩法类别高亮", f"{last_highlight_ratio:.3f}")
            if (
                self._matches_any(text, [BATTLE_GAMEPLAY_CATEGORY_LABEL])
                and last_highlight_ratio
                >= float(
                    self.config.get(
                        "玩法类别高亮像素比例",
                        GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO,
                    )
                )
            ):
                return True
            self.sleep(interval)

        self.log_info(
            "镜中之战：未确认战斗玩法游戏卡带类别高亮，"
            f"highlight={last_highlight_ratio:.3f}, OCR={last_text or '-'}。"
        )
        return False

    def _quick_switch_still_shows(self, highlighted: bool, seconds: float) -> bool:
        """Re-click guard: every frame for ``seconds`` (two at least) must still
        show the battle category label with the given highlight state."""
        end_at = monotonic() + max(0.0, seconds)
        reads = 0
        threshold = float(
            self.config.get("玩法类别高亮像素比例", GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO)
        )
        while True:
            frame = self.capture_frame()
            text = self._ocr_text(
                frame, name="战斗玩法游戏卡带", roi=BATTLE_GAMEPLAY_CATEGORY_OCR_ROI
            )
            ratio = category_highlight_ratio(frame, BATTLE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION)
            if not self._matches_any(text, [BATTLE_GAMEPLAY_CATEGORY_LABEL]):
                return False
            if (ratio >= threshold) != highlighted:
                return False
            reads += 1
            if reads >= 2 and monotonic() >= end_at:
                return True
            self.sleep(0.5)

    def _wait_for_quick_switch_page(self, interval: float = 0.5) -> bool:
        self.info_set("当前阶段", "确认卡带选择页")
        end_at = monotonic() + float(self.config.get("卡带选择页确认等待秒数", 10.0))
        last_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            text = self._ocr_text(frame, name="卡带选择页")
            last_text = text or last_text
            match_count = self._ocr_pattern_match_count(text, list(QUICK_SWITCH_PAGE_PATTERNS))
            self.info_set("卡带选择页 OCR", text or "-")
            self.info_set(
                "卡带选择页 OCR 命中",
                f"{match_count}/{len(QUICK_SWITCH_PAGE_PATTERNS)}",
            )
            if match_count == len(QUICK_SWITCH_PAGE_PATTERNS):
                return True
            self.sleep(interval)

        self.info_set("卡带选择页 OCR", last_text or "-")
        self.log_info(
            "镜中之战：点击快速切换按钮后未确认卡带选择页，"
            f"OCR={last_text or '-'}。"
        )
        return False

    def _wait_for_cartridge_home(self, interval: float = 0.35) -> bool:
        self.info_set("当前阶段", "确认主页")
        end_at = monotonic() + float(self.config.get("主页确认等待秒数", 10.0))
        last_left_hits = 0
        last_p95 = 0.0
        last_gacha_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            home_ok, last_left_hits, last_p95, gacha_text = (
                self._home_confirmation_signals(frame)
            )
            last_gacha_text = gacha_text or last_gacha_text
            self.info_set(
                "主页左列关键词",
                f"{last_left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}",
            )
            self.info_set(
                "主页亮度p95",
                f"{last_p95:.0f}/{self._home_p95_threshold():.0f}",
            )
            self.info_set("主页抽抽乐 OCR", gacha_text or "-")
            if home_ok:
                return True
            self.clear_temporary_home_announcement_if_needed(
                left_hits=last_left_hits,
                required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                brightness=last_p95,
                brightness_threshold=self._home_p95_threshold(),
                gacha_ocr_text=gacha_text,
                context="镜中之战确认主页",
            )
            self.sleep(interval)

        self.log_info(
            "镜中之战：未联合确认左列关键词、亮度和抽抽乐文字，"
            f"left={last_left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}, "
            f"p95={last_p95:.0f}, ocr={last_gacha_text or '-'}。"
        )
        return False

    def _wait_for_pvp_hub_after_cart(
        self,
        timeout: float,
        interval: float = 0.5,
    ) -> bool:
        """Handle every PVP entry special page before accepting the PVP hub."""
        end_at = monotonic() + max(0.0, timeout)
        handled: set[str] = set()
        action_count = 0
        last_text = ""
        last_hub_score = -1.0
        hub_candidate_at: float | None = None
        # The season reward page blocks the hub on whatever day a player first
        # enters PVP after the reset, so its strict pair is dismissed any day.
        allow_season_reward = True
        self.info_set("PVP 入场特殊页面模式", "赛季奖励、魔兽奖励及升降级")

        while True:
            now = monotonic()
            if now > end_at:
                break
            frame = self.capture_frame()
            boxes = self._pvp_special_page_ocr_boxes(
                frame,
                name="PVP 入场特殊页面",
            )
            text, action_name, target_box = self._pvp_special_page_action(
                boxes,
                allow_season_reward=allow_season_reward,
            )
            last_text = text or last_text
            self.info_set("PVP 入场特殊页面 OCR", text or "-")
            if action_name:
                hub_candidate_at = None
                if (
                    action_name not in handled
                    and target_box is not None
                    and action_count < RECENT_CARTRIDGE_SPECIAL_PAGE_MAX_ACTIONS
                ):
                    point = self._ocr_box_center(target_box)
                    if point is not None:
                        frame_height, frame_width = frame.shape[:2]
                        self.info_set("当前阶段", f"处理 PVP 入场{action_name}")
                        after_sleep = (
                            PVP_SEASON_REWARD_AFTER_CLICK_SECONDS
                            if action_name in ("赛季奖励", FIEND_HUNT_REWARD_TITLE)
                            else PVP_RANK_PAGE_AFTER_CLICK_SECONDS
                        )
                        self.operate_click(
                            max(0.0, min(1.0, point[0] / max(1, frame_width))),
                            max(0.0, min(1.0, point[1] / max(1, frame_height))),
                            after_sleep=after_sleep,
                        )
                        handled.add(action_name)
                        action_count += 1
                        continue
                # The hub artwork can remain visible behind these overlays. Never
                # accept its template from a frame that contains a special page.
                self.sleep(interval)
                continue

            self.info_set("当前阶段", "确认 PVP 箱庭")
            hub = self._match(frame, PVP_MEDALS_TEMPLATE)
            last_hub_score = hub.score
            self.info_set("PVP 箱庭", f"{hub.score:.3f}")
            if self._passes(hub, PVP_MEDALS_TEMPLATE):
                if hub_candidate_at is None:
                    hub_candidate_at = now
                stable_seconds = now - hub_candidate_at
                self.info_set(
                    "当前阶段",
                    (
                        "确认 PVP 箱庭并观察特殊页面 "
                        f"{stable_seconds:.1f}/{PVP_HUB_SPECIAL_PAGE_GRACE_SECONDS:.1f}秒"
                    ),
                )
                if stable_seconds >= PVP_HUB_SPECIAL_PAGE_GRACE_SECONDS:
                    return True
            else:
                hub_candidate_at = None

            self.sleep(interval)

        self.info_set("PVP 入场特殊页面 OCR", last_text or "-")
        self.info_set("PVP 箱庭", f"{last_hub_score:.3f}")
        self.log_info(
            "镜中之战：点击 PVP 卡带后未确认进入 PVP 箱庭，"
            f"hub={last_hub_score:.3f}, special_page_ocr={last_text or '-'}, "
            f"handled={','.join(sorted(handled)) or '-'}。"
        )
        self._save_flow_diagnostic("pvp_hub_entry_failed")
        return False

    def _clear_pvp_hub_notice_if_present(self) -> None:
        # The hub "!" is the field F button: it shows while the characters
        # that follow the player after login are around, and they stand on
        # the stage until it is pressed (Leo, 2026-10-03).
        self.dismiss_field_followers()

    def _click_pvp_stage_once(self, timeout: float) -> bool:
        return self._click_template_until(
            PVP_STAGE_TEMPLATE,
            timeout=timeout,
            name="PVP 舞台",
            target_reference_offset=PVP_STAGE_CLICK_REFERENCE_OFFSET,
            after_sleep=3.0,
        )

    def _stage_move_mode(self) -> str:
        mode = str(self.config.get("舞台移动方式", STAGE_MOVE_CLICK))
        return mode if mode in STAGE_MOVE_OPTIONS else STAGE_MOVE_CLICK

    def _pre_battle_visible(self) -> bool:
        found, _text = self._wait_for_ocr_patterns(
            [r"自动战斗", r"自动"],
            timeout=0.6,
            name="PVP 战前画面",
            roi=PVP_AUTO_BATTLE_SCREEN_ROI,
        )
        return found

    def _stage_in_view(self) -> tuple[int, int] | None:
        frame = self.capture_frame()
        reference = cv2.resize(
            frame[:, :, :3],
            (FHD_1080.width, FHD_1080.height),
            interpolation=cv2.INTER_AREA,
        )
        return find_stage(reference)

    def _walk_onto_stage(self) -> bool:
        """WASD the character onto the red stage centre (closed loop).

        The camera keeps the character centred, so the stage's screen offset is
        the distance still to walk; each step is re-planned from a new frame.
        """
        self.info_set("当前阶段", "键盘走到 PVP 舞台")
        missing = 0
        for step_index in range(1, STAGE_WALK_MAX_STEPS + 1):
            if self._pre_battle_visible():
                self.info_set("PVP 舞台走位", f"第{step_index}步前已进入战前画面")
                return True
            stage = self._stage_in_view()
            self.info_set("PVP 舞台位置", str(stage))
            if stage is None:
                missing += 1
                if missing >= 3:
                    self.log_info("镜中之战：画面中找不到红色舞台。")
                    return False
                self.sleep(0.5)
                continue
            missing = 0
            step = plan_step(stage)
            if step is None:
                return self._nudge_until_pre_battle()
            if not self.hold_key(step.key, step.seconds, after_sleep=0.5):
                return False
        return self._nudge_until_pre_battle()

    def _nudge_until_pre_battle(self) -> bool:
        """Short taps around the centre; the stage centroid is biased when occluded."""
        for step in NUDGE_SEQUENCE:
            if self._pre_battle_visible():
                return True
            if not self.hold_key(step.key, step.seconds, after_sleep=0.6):
                return False
        return self._pre_battle_visible()

    def _start_auto_battle(self, multiplier: int) -> str:
        self.info_set("当前阶段", "寻找 PVP 舞台")
        walking = self._stage_move_mode() == STAGE_MOVE_WASD
        if walking:
            if not self._walk_onto_stage():
                self._save_flow_diagnostic("pvp_stage_walk_failed")
                self.log_info("镜中之战：键盘移动未能走到舞台正中。")
                return "failed"
        elif not self._click_pvp_stage_once(12.0):
            self._recover_stage_position()
            if not self._click_pvp_stage_once(8.0):
                # BUG-20260908-04：舞台纹理小条失配时无图可查，落帧留存用户
                # 箱庭实景以定位根因（对照 pvp_hub_entry_failed 等埋点）。
                self._save_flow_diagnostic("pvp_stage_not_found")
                self.log_info("镜中之战：未找到 PVP 舞台物件。")
                return "failed"

        self.info_set("当前阶段", "打开自动战斗")
        menu_timeout = float(self.config.get("PVP 菜单等待秒数", 12.0))
        found_auto = False
        text = ""
        for attempt in range(1, PVP_CLICK_VERIFY_ATTEMPTS + 1):
            found_auto, text = self._wait_for_ocr_patterns(
                [r"自动战斗", r"自动"],
                timeout=menu_timeout,
                name="PVP 自动战斗",
                roi=PVP_AUTO_BATTLE_SCREEN_ROI,
            )
            self.info_set("PVP 自动战斗 OCR", text or "-")
            if found_auto:
                break
            if attempt >= PVP_CLICK_VERIFY_ATTEMPTS:
                break
            # BUG-20260908-04：箱庭是可行走场景，使者不在台上时点台会被当作
            # 移动指令（RPT-20260908-183941 实证：模板与落点全对、台上无人、
            # 菜单不出）。等使者走位/游开后补击，模板再丢时仍走定位修正兜底。
            self.log_info(
                f"镜中之战：第{attempt}/{PVP_CLICK_VERIFY_ATTEMPTS}次点击舞台"
                "后未确认自动战斗菜单，重试。"
            )
            if walking:
                if not self._walk_onto_stage():
                    self._save_flow_diagnostic("pvp_stage_walk_failed")
                    self.log_info("镜中之战：重试时键盘移动未能走到舞台正中。")
                    return "failed"
            elif not self._click_pvp_stage_once(8.0):
                self._recover_stage_position()
                if not self._click_pvp_stage_once(8.0):
                    self._save_flow_diagnostic("pvp_stage_not_found")
                    self.log_info("镜中之战：重试点击时未找到 PVP 舞台物件。")
                    return "failed"
        if not found_auto:
            self.log_info("镜中之战：多次点击舞台后自动战斗菜单仍未出现。")
            self._save_flow_diagnostic("pvp_auto_battle_failed")
            return "failed"

        menu_roi = self._mf_roi(*PVP_AUTO_BATTLE_MENU_OCR_REFERENCE_ROI)
        # 2026-09 客户端改版把按钮热区收到图标/背板上（RPT-20260905-201103），
        # OCR 标签中心点击不再打开弹窗；先点校准图标位，未验证到弹窗再兜底
        # 标签中心。BUG-20260906-01：网络波动会整枪吞掉点击，两级各一枪仍
        # 可能全被吞，按 PVP_CLICK_VERIFY_ATTEMPTS 轮流用两种落点重试。
        auto_battle_clicks = (
            (
                "图标校准点",
                lambda: self._click_screen_reference(
                    *PVP_AUTO_BATTLE_CLICK_REFERENCE,
                    after_sleep=1.0,
                ),
            ),
            (
                "OCR标签中心",
                lambda: self._click_ocr_pattern_center(
                    [r"自动战斗", r"自动"],
                    name="PVP 自动战斗",
                    roi=PVP_AUTO_BATTLE_SCREEN_ROI,
                    after_sleep=1.0,
                ),
            ),
        )
        found_menu = False
        menu_text = ""
        for attempt in range(1, PVP_CLICK_VERIFY_ATTEMPTS + 1):
            click_label, click = auto_battle_clicks[
                (attempt - 1) % len(auto_battle_clicks)
            ]
            clicked = click()
            self.info_set(
                "PVP 自动战斗点击",
                (
                    f"第{attempt}次{click_label}"
                    if clicked
                    else f"第{attempt}次{click_label}（不可用）"
                ),
            )
            found_menu, menu_text = self._wait_for_ocr_patterns(
                [r"鲜血鸡尾酒"],
                timeout=PVP_AUTO_BATTLE_MENU_VERIFY_SECONDS,
                name="PVP 自动战斗菜单",
                roi=menu_roi,
            )
            if found_menu:
                break
            if attempt < PVP_CLICK_VERIFY_ATTEMPTS:
                self.log_info(
                    f"镜中之战：第{attempt}/{PVP_CLICK_VERIFY_ATTEMPTS}次点击"
                    "自动战斗后未确认菜单，重试。"
                )
        self.info_set("PVP 自动战斗 OCR", menu_text or "-")
        if not found_menu:
            self.log_info("镜中之战：多次点击后自动战斗菜单仍未出现。")
            self._save_flow_diagnostic("pvp_auto_battle_failed")
            return "failed"

        self._free_cocktails_short = False
        if not self._ensure_free_ap_enabled():
            self._close_auto_battle_dialogs()
            # No free cocktail at all: a 1x retry cannot help either.
            return "free_empty" if self._free_cocktails_short else "failed"
        if not self._ensure_multiplier(multiplier):
            self._close_auto_battle_dialogs()
            return "failed"
        if not self._select_battle_count(multiplier):
            self.info_set("当前阶段", "免费鸡尾酒核对失败，取消")
            self._click_reference(*PVP_DIALOG_CANCEL_POINT, after_sleep=1.0)
            if self._free_cocktails_short:
                # Today's free cocktails are spent at this multiplier: done,
                # not a failure (live 2026-09-29: 4 left at 18x).
                self._close_auto_battle_dialogs()
                return "free_short"
            self._save_flow_diagnostic("pvp_cost_check_failed")
            return "failed"

        self.info_set("当前阶段", "点击战斗开始")
        self.info_set("PVP 开始战斗 OCR", "跳过前置 OCR，按固定比例点击")
        return self._press_battle_start(multiplier)

    def _close_auto_battle_dialogs(self) -> None:
        """Press a read 取消 on up to two layers (倍率 setting, auto battle).

        Nothing is clicked blind: an unread button is left for recovery,
        which also only presses 取消/关闭.
        """
        menu_roi = self._mf_roi(*PVP_AUTO_BATTLE_MENU_OCR_REFERENCE_ROI)
        for _layer in range(2):
            open_, _text = self._wait_for_ocr_patterns(
                [r"鲜血鸡尾酒"], timeout=1.0, name="PVP 自动战斗菜单", roi=menu_roi
            )
            if not open_:
                return
            if not self._click_ocr_pattern_center(
                [r"^取消$"], name="PVP 取消", roi=None, after_sleep=1.0
            ):
                self.log_info("镜中之战：失败后未读到「取消」，弹窗留给回到主页处理。")
                return

    def _close_ap_shortage_popup(self) -> bool:
        """Close the 鸡尾酒/AP 不足 popup by a read 取消/关闭 only.

        Its other button (补充/购买) spends paid resources, so nothing else is
        pressed and nothing is clicked blind. True once the shortage text is
        gone for a whole verify window; False when it cannot be closed, and the
        caller must then stop without any further click.
        """
        self.info_set("当前阶段", "关闭 AP 不足弹窗（仅取消）")
        for attempt in range(1, PVP_AP_SHORTAGE_CLOSE_ATTEMPTS + 1):
            clicked = self._click_ocr_pattern_center(
                PVP_AP_SHORTAGE_CLOSE_PATTERNS,
                name="PVP AP不足取消",
                roi=None,
                after_sleep=1.0,
            )
            still_open, text = self._wait_for_ocr_patterns(
                [PVP_AP_SHORTAGE_PATTERN],
                timeout=PVP_AP_SHORTAGE_VERIFY_SECONDS,
                name="PVP AP不足弹窗",
            )
            if not still_open:
                self.info_set("PVP AP不足弹窗", "已关闭")
                return True
            self.info_set(
                "PVP AP不足弹窗",
                f"第{attempt}次{'点击取消后仍在' if clicked else '未读到取消/关闭'}：{text}",
            )
            if not clicked:
                self.sleep(0.5)

        self.log_warning(
            "镜中之战：AP 不足弹窗未能用「取消/关闭」关闭，停止，不点击其他按钮。"
        )
        self._save_flow_diagnostic("pvp_ap_shortage_close_failed")
        return False

    def _press_battle_start(self, multiplier: int) -> str:
        """Press 战斗开始 (spends cocktails) and confirm the battle began.

        A swallowed press used to count as started and then wait out the
        whole result time.  It is pressed again only while the dialog still
        shows the same button and free count (nothing spent yet).  With
        neither 正在进行 nor a shortage read, the dialog must be gone on two
        looks (loading or battle screen) to count as started.
        """
        seen = {"state": None}

        def started():
            seen["state"] = self._battle_start_state(multiplier)
            return seen["state"]

        outcome = self.press_and_confirm(
            "镜中之战「战斗开始」",
            lambda: self._click_screen_reference(
                *PVP_BATTLE_START_SCREEN_POINT, after_sleep=2.0
            ),
            started,
            still_before=lambda: self._start_dialog_unchanged(multiplier),
            timeout=float(self.config.get("PVP 战斗开始等待秒数", 30.0)),
            poll=0.5,
        )
        if outcome:
            return seen["state"]
        if self._start_dialog_gone():
            self.log_warning(
                "镜中之战：点击开始后未识别到战斗开始或 AP 不足信号，"
                "开战前画面已关闭，按结算等待继续。"
            )
            return "started"
        self.log_warning(
            "镜中之战：按了「战斗开始」后仍停在开战前画面（或认不准），没有开打，不再按，停止。",
            notify=True,
        )
        self._save_flow_diagnostic("pvp_battle_start_unconfirmed")
        self._close_auto_battle_dialogs()
        return "failed"

    def _battle_start_state(self, multiplier: int) -> str | None:
        """One look after 战斗开始: started / ap_shortage / ap_depleted, else None."""
        frame = self.capture_frame()
        if frame is None:
            return None
        battle_text = self._ocr_text(
            frame,
            name="PVP 战斗中",
            roi=self._mf_roi(*PVP_BATTLE_ONGOING_OCR_REFERENCE_ROI),
        )
        if self._matches_any(battle_text, [PVP_BATTLE_ONGOING_PATTERN]):
            self.info_set("PVP 战斗中 OCR", battle_text)
            return "started"

        ap_text = self._ocr_text(frame, name="PVP AP不足")
        if self._matches_any(ap_text, [PVP_AP_SHORTAGE_PATTERN]):
            self.info_set("PVP AP不足 OCR", ap_text)
            if multiplier > 1:
                return "ap_shortage"
            return "ap_depleted"
        return None

    def _start_dialog_unchanged(self, multiplier: int) -> bool:
        """Two looks still show the dialog, 战斗开始 at this cost and the free
        count read before the press: nothing was spent, a re-press is safe."""
        free_before = getattr(self, "_verified_free", None)
        if free_before is None:
            return False
        menu_roi = self._mf_roi(*PVP_AUTO_BATTLE_MENU_OCR_REFERENCE_ROI)
        for look in range(2):
            if look:
                self.sleep(0.5)
            frame = self.capture_frame()
            if frame is None:
                return False
            menu = self._ocr_text(frame, name="PVP 自动战斗菜单", roi=menu_roi)
            free = parse_free_cocktails(
                self._ocr_text(frame, name="PVP 免费鸡尾酒", roi=PVP_FREE_COCKTAIL_ROI)
            )
            if (
                not self._matches_any(menu, [r"鲜血鸡尾酒"])
                or self._start_cost_on(frame) != multiplier
                or free != free_before
            ):
                return False
        return True

    def _start_dialog_gone(self) -> bool:
        """Neither the dialog's 鲜血鸡尾酒 nor 战斗开始 is read on two looks."""
        menu_roi = self._mf_roi(*PVP_AUTO_BATTLE_MENU_OCR_REFERENCE_ROI)
        for look in range(2):
            if look:
                self.sleep(0.5)
            frame = self.capture_frame()
            if frame is None:
                return False
            menu = self._ocr_text(frame, name="PVP 自动战斗菜单", roi=menu_roi)
            button = self._ocr_text(frame, name="PVP 战斗开始", roi=PVP_START_BUTTON_ROI)
            if self._matches_any(menu, [r"鲜血鸡尾酒"]) or self._matches_any(
                button, [r"战斗开始"]
            ):
                return False
        return True

    def _ensure_free_ap_enabled(self) -> bool:
        self.info_set("当前阶段", "确认仅用免费鸡尾酒")
        # One press at most (review #28): a switch whose yellow is not
        # recognised reads as off, and pressing again would turn it off.  A
        # swallowed press (BUG-20260906-01) now stops this run instead.
        if ensure_free_switch_on(
            "镜中之战：免费AP开关",
            self._free_ap_switch_ratio,
            lambda: self._click_screen_reference(
                *PVP_FREE_AP_SWITCH_SCREEN_POINT,
                after_sleep=1.0,
            ),
            on_above=PVP_FREE_AP_SWITCH_ON_RATIO,
            settle=PVP_FREE_AP_SWITCH_SETTLE_SECONDS,
            sleep=self.sleep,
            log=self.log_info,
        ):
            self.info_set("PVP 免费AP", "已开启")
            return True

        # With no free cocktail left the game refuses the switch ("当前未拥有
        # 任何免费鲜血鸡尾酒", live 4K 2026-09-30, 0/40): the day is done.
        # A dropped digit (10/40 read as 0/40) must not end the day: only two
        # agreeing reads count; a disagreement stays "未确认" (no fight either way).
        def free_pool():
            return parse_free_cocktails(
                self._ocr_text(
                    self.capture_frame(), name="PVP 免费鸡尾酒", roi=PVP_FREE_COCKTAIL_ROI
                )
            )

        free = free_pool()
        if free == 0:
            free = self._confirm_read(free, free_pool)
        if free == 0:
            self._free_cocktails_short = True
            self.info_set("PVP 免费AP", "免费鸡尾酒 0")
            self.log_info("镜中之战：今天的免费鸡尾酒已用完，开关无法开启。")
            return False

        self.info_set("PVP 免费AP", "未确认")
        self.log_info("镜中之战：未能确认仅用免费鸡尾酒开关。")
        return False

    def _free_ap_switch_on(self) -> bool:
        return self._free_ap_switch_ratio() > PVP_FREE_AP_SWITCH_ON_RATIO

    def _free_ap_switch_ratio(self) -> float:
        frame = self.capture_frame()
        crop = self._crop_screen_reference(frame, FREE_AP_SWITCH_SCREEN_ROI)
        if crop.size == 0:
            return 0.0
        # Capture backends produce 3-channel (BGR) or 4-channel (BGRA) frames;
        # only the first three channels carry the switch colour, and any other
        # shape must fail closed instead of raising.
        if crop.ndim != 3 or crop.shape[2] < 3:
            self.log_info(f"镜中之战：免费AP开关区域帧形状异常 {crop.shape}。")
            return 0.0
        yellow_ratio = switch_yellow_ratio(crop)
        self.info_set("PVP 免费AP", f"开关黄色占比 {yellow_ratio:.3f}")
        return yellow_ratio

    def _ensure_multiplier(self, multiplier: int) -> bool:
        self.info_set("当前阶段", "确认战斗倍率")
        if self._multiplier_matches(multiplier):
            return True

        if not self._open_multiplier_setting():
            return False
        if not self._select_setting_multiplier(multiplier):
            return False

        return self._confirm_setting_multiplier(multiplier)

    def _open_multiplier_setting(self) -> bool:
        # BUG-20260906-01：倍率按钮点击被网络吞掉时设置弹窗不会出现，重试点击。
        for attempt in range(1, PVP_CLICK_VERIFY_ATTEMPTS + 1):
            self._click_screen_reference(
                *PVP_MULTIPLIER_BUTTON_SCREEN_POINT,
                after_sleep=0.8,
            )
            found, _text = self._wait_for_ocr_patterns(
                [r"设置.*鲜血鸡尾酒.*消耗量|鲜血鸡尾酒.*消耗量"],
                timeout=8.0,
                name="PVP 倍率设置",
                roi=self._mf_roi(*PVP_MULTIPLIER_SETTING_OCR_REFERENCE_ROI),
            )
            if found:
                return True
            self.log_info(
                f"镜中之战：第{attempt}/{PVP_CLICK_VERIFY_ATTEMPTS}次点击倍率"
                "按钮后未打开设置弹窗"
                + ("，重试。" if attempt < PVP_CLICK_VERIFY_ATTEMPTS else "。")
            )
        self.log_info("镜中之战：未能打开倍率设置。")
        return False

    def _select_setting_multiplier(self, multiplier: int) -> bool:
        # BUG-20260906-01：选项点击被吞时设置值不变，先重试点击同一选项直到
        # 回读匹配（重复点击同一选项无副作用），再按原逻辑用加号步进到目标。
        option_point = (
            PVP_MULTIPLIER_40_OPTION_SCREEN_POINT
            if multiplier == 40
            else PVP_MULTIPLIER_1_OPTION_SCREEN_POINT
        )
        option_value = 40 if multiplier == 40 else 1
        for attempt in range(1, PVP_CLICK_VERIFY_ATTEMPTS + 1):
            self._click_screen_reference(*option_point, after_sleep=0.5)
            if self._setting_multiplier_matches(option_value):
                break
            self.log_info(
                f"镜中之战：倍率选项第{attempt}/{PVP_CLICK_VERIFY_ATTEMPTS}"
                f"次点击后设置值未回读到 {option_value}"
                + ("，重试。" if attempt < PVP_CLICK_VERIFY_ATTEMPTS else "。")
            )
        else:
            self.info_set("PVP 倍率 OCR", "未确认")
            return False

        # From MIN (1) or MAX (40) step with -5/+5 and -/+ reading the value
        # back each time, so any multiplier 1~40 is reachable.
        for _ in range(24):
            if self._setting_multiplier_matches(multiplier):
                break
            # A dropped digit is retried instead of ending the stepping.
            current = self._read_until(self._setting_multiplier_value)
            step = adjust_step(current, multiplier, 5) if current is not None else None
            if step is None:
                break
            self._click_reference(*PVP_MULTIPLIER_STEP_POINTS[step], after_sleep=0.4)

        for look in range(3):
            if look:
                self.sleep(0.4)
            if self._setting_multiplier_matches(multiplier):
                return True
        self.info_set("PVP 倍率 OCR", "未确认")
        return False

    def _confirm_setting_multiplier(self, multiplier: int) -> bool:
        # BUG-20260906-01：确认点击被吞时设置弹窗不关、主弹窗回读不变；仅在
        # 设置弹窗仍开着时重试确认，弹窗已关则不盲重试（避免误点主弹窗）。
        # A player's run (v0.1.17, 1920×1080 windowed, 2026-10-10) pressed
        # three times and stopped twice with the dialog "still open".  The old
        # check read 鲜血鸡尾酒…消耗量, and the main popup's 鲜血鸡尾酒 row
        # sits in the same area (no frame of it yet, so inferred).  Now the
        # read 确认 is pressed (the fixed point when unread), the dialog counts
        # as open only by its own 设置 / 确认 / value, and a closed dialog
        # whose main value is not read is confirmed by the cost on 战斗开始
        # (checked again before the start in any case).
        for attempt in range(1, PVP_CLICK_VERIFY_ATTEMPTS + 1):
            if not self._click_ocr_pattern_center(
                PVP_SETTING_CONFIRM_PATTERNS,
                name="PVP 倍率确认",
                roi=PVP_SETTING_CONFIRM_REFERENCE_ROI,
                after_sleep=1.0,
            ):
                self._click_screen_reference(
                    *PVP_MULTIPLIER_CONFIRM_SCREEN_POINT,
                    after_sleep=1.0,
                )
            if self._multiplier_matches(multiplier, timeout=4.0):
                return True
            if not self._setting_dialog_open(multiplier):
                if self._start_cost_is(multiplier):
                    self.log_info(
                        f"镜中之战：倍率处没读到 {multiplier}，"
                        f"战斗开始上每场消耗是 {multiplier}，倍率已设好。"
                    )
                    return True
                break
            if attempt >= PVP_CLICK_VERIFY_ATTEMPTS:
                break
            self.log_info(f"镜中之战：倍率确认第{attempt}次点击未生效，重试。")

        self.info_set("PVP 倍率 OCR", "未确认")
        self.log_info(f"镜中之战：倍率没能设成 {multiplier}，{self._multiplier_seen()}")
        self._save_flow_diagnostic("pvp_multiplier_confirm_failed")
        return False

    def _setting_dialog_open(self, multiplier: int) -> bool:
        """The 倍率 setting dialog is still up: its title's 设置, its 确认 or its value."""
        found, _text = self._wait_for_ocr_patterns(
            [r"设置"],
            timeout=1.0,
            name="PVP 倍率设置",
            roi=self._mf_roi(*PVP_MULTIPLIER_SETTING_OCR_REFERENCE_ROI),
        )
        if found:
            return True
        # Read text is joined: the anchored pattern is for one box only.
        found, _text = self._wait_for_ocr_patterns(
            [r"确[认定]"],
            timeout=0.5,
            name="PVP 倍率确认",
            roi=PVP_SETTING_CONFIRM_REFERENCE_ROI,
        )
        return found or self._setting_multiplier_matches(multiplier)

    def _start_cost_is(self, multiplier: int) -> bool:
        """Two looks at 战斗开始 agree that one battle costs ``multiplier``."""

        def cost():
            return self._start_cost_on(self.capture_frame())

        first = self._read_until(cost)
        if first != multiplier:
            return False
        self.sleep(0.4)
        return self._read_until(cost) == multiplier

    def _multiplier_seen(self) -> str:
        """What the screen showed where the multiplier is set, for the log."""
        frame = self.capture_frame()
        value = self._ocr_text(
            frame, name="PVP 倍率", roi=self._mf_roi(*PVP_MULTIPLIER_OCR_REFERENCE_ROI)
        )
        title = self._ocr_text(
            frame,
            name="PVP 倍率设置",
            roi=self._mf_roi(*PVP_MULTIPLIER_SETTING_OCR_REFERENCE_ROI),
        )
        button = self._ocr_text(
            frame, name="PVP 倍率确认", roi=PVP_SETTING_CONFIRM_REFERENCE_ROI
        )
        return (
            f"当时倍率处读到「{value or '-'}」，标题处「{title[:20] or '-'}」，"
            f"确认处「{button[:12] or '-'}」。"
        )

    def _setting_multiplier_value(self) -> int | None:
        frame = self.capture_frame()
        text = self._ocr_text(
            frame,
            name="PVP 倍率设置值",
            roi=self._mf_roi(*PVP_MULTIPLIER_SETTING_VALUE_OCR_REFERENCE_ROI),
        )
        return parse_multiplier(text)

    def _battle_count_value(self) -> int | None:
        text = self._ocr_text(self.capture_frame(), name="PVP 战斗次数", roi=PVP_COUNT_ROI)
        self.info_set("PVP 战斗次数 OCR", text or "-")
        return parse_battle_count(text)

    def _set_battle_count(self, count: int) -> int | None:
        """Step the count toward ``count``; return where it ended (None: unread).

        With only free cocktails the game caps the count at what the free
        pool covers.  A press that leaves the count unchanged means that cap:
        stop there (live 2026-09-28: 30 presses against a cap of 2 froze the
        screen for 15 s and the run was cancelled).  A swallowed press leaves
        it unchanged too, so the cap is taken only after one more press.
        """
        self.info_set("当前阶段", f"设置战斗次数 {count}")
        self._click_reference(*PVP_COUNT_MIN_POINT, after_sleep=0.6)
        for _ in range(30):
            current = self._read_until(self._battle_count_value)
            if current is None:
                return None
            step = adjust_step(current, count, 10)
            if step is None:
                return current
            if self.press_and_confirm(
                "镜中之战「战斗次数」",
                lambda: self._click_reference(*PVP_COUNT_STEP_POINTS[step], after_sleep=0.4),
                lambda: self._battle_count_value() not in (None, current),
                still_before=lambda: self._battle_count_value() == current,
                timeout=PVP_COUNT_CONFIRM_SECONDS,
            ):
                continue
            after = self._read_until(self._battle_count_value)
            if after is None or after == current:
                # Unchanged after the second press too: the free cocktails' cap.
                return after
        return self._battle_count_value()

    def _select_battle_count(self, multiplier: int) -> bool:
        config = getattr(self, "config", None) or {}
        count = battle_count_setting(config.get("战斗场数", BATTLE_COUNT_MAX))
        override = getattr(self, "_battle_count_override", None)
        if override:
            count = override
        capped = capped_battle_count(multiplier, count)
        if capped != count:
            self.log_info(
                f"镜中之战：{multiplier} 倍 × {count} 场超过每天 {FREE_COCKTAILS_PER_DAY} 杯免费鸡尾酒，"
                f"改为 {capped} 场。"
            )
            count = capped
        if count <= 0:
            self._select_max_battle_count()
        else:
            reached = self._set_battle_count(count)
            if not reached or reached > count:
                self.log_info(f"镜中之战：未能把战斗次数设为 {count}。")
                return False
            if reached < count:
                self.log_info(f"镜中之战：免费鸡尾酒只够 {reached} 场（设定 {count} 场）。")
            count = reached
        return self._verify_free_cost(multiplier, count)

    def _read_until(self, reader, attempts: int = 3):
        """OCR drops digits now and then: retry a reader before giving up."""
        for attempt in range(attempts):
            value = reader()
            if value is not None:
                return value
            if attempt + 1 < attempts:
                self.sleep(0.4)
        return None

    def _confirm_read(self, first, reader):
        """A read that would stop the day is taken again: a dropped digit
        (40 -> 4) on one frame ended PVP early. Any disagreement is None,
        i.e. do not fight (and do not call the day done either)."""
        self.sleep(0.4)
        second = self._read_until(reader)
        if second != first:
            self.log_info(f"镜中之战：免费鸡尾酒两次读数不一致（{first} / {second}），不开打。")
            return None
        return first

    def _verify_free_cost(self, multiplier: int, count: int) -> bool:
        """Only start when every battle is paid from free cocktails.

        The start button shows the per-battle cost ("10倍战斗开始 🍹10"), so it
        must equal the multiplier; the whole run costs multiplier x the count
        shown in the dialog, which must not exceed the free pool (a/40).
        """

        def per_battle():
            return self._start_cost_on(self.capture_frame())

        def free_pool():
            text = self._ocr_text(
                self.capture_frame(), name="PVP 免费鸡尾酒", roi=PVP_FREE_COCKTAIL_ROI
            )
            return parse_free_cocktails(text)

        cost = self._read_until(per_battle)
        free = self._read_until(free_pool)
        battles = self._read_until(self._battle_count_value)
        if free is not None and battles is not None and multiplier * battles > free:
            free = self._confirm_read(free, free_pool)
        switch_on = self._free_ap_switch_on()
        total = multiplier * battles if battles is not None else None
        self.info_set(
            "PVP 消耗核对",
            f"每场 {cost} / 场数 {battles} / 合计 {total} / 免费 {free} / "
            f"免费开关 {'开' if switch_on else '关'}",
        )
        problems = []
        if not switch_on:
            problems.append("仅使用免费鲜血鸡尾酒未开启")
        if cost is None or free is None or battles is None:
            problems.append("读不到每场消耗、场数或免费鸡尾酒数")
        else:
            if cost != multiplier:
                problems.append(f"每场消耗 {cost} 不等于倍数 {multiplier}")
            if count > 0 and battles != count:
                problems.append(f"场数 {battles} 不是设定的 {count}")
            if total > free:
                problems.append(f"合计 {total} 超过免费鸡尾酒 {free}")
                if len(problems) == 1 and free < multiplier:
                    # Not even one battle is free: the day is simply done.
                    self._free_cocktails_short = True
                    self.log_info(
                        f"镜中之战：免费鸡尾酒只剩 {free}，不够 {multiplier} 倍打一场。"
                    )
                    return False
        if problems:
            self.log_warning(f"镜中之战：{'；'.join(problems)}，取消本次战斗。", notify=True)
            return False
        self._verified_battles = battles
        # 战斗开始 is pressed again only while this count is still shown.
        self._verified_free = free
        return True

    def _start_cost_on(self, frame) -> int | None:
        """The per-battle cost on 战斗开始 (None: unread)."""
        # A lone thin "1" after the cocktail icon is lost at 2K (live
        # 2026-09-29, 1x fallback): read the button enlarged as well.
        texts = []
        for scale in (1.0, 2.0):
            text = self._ocr_text(
                frame, name="PVP 战斗开始", roi=PVP_START_BUTTON_ROI, ocr_scale=scale
            )
            texts.append(text)
            cost = parse_start_cost(text)
            if cost is not None:
                return cost
        self.info_set("PVP 战斗开始 OCR", " | ".join(t or "-" for t in texts))
        return None

    def _select_max_battle_count(self) -> None:
        self.info_set("当前阶段", "选择最大战斗次数")
        self._click_screen_reference(*PVP_MAX_BATTLE_COUNT_SCREEN_POINT, after_sleep=0.8)

    def _multiplier_matches(self, multiplier: int, timeout: float = 2.0) -> bool:
        found, text = self._wait_for_ocr_patterns(
            [rf"^{multiplier}$", rf"^{multiplier}倍$"],
            timeout=timeout,
            name="PVP 倍率",
            roi=self._mf_roi(*PVP_MULTIPLIER_OCR_REFERENCE_ROI),
            normalize_multiplier=True,
        )
        self.info_set("PVP 倍率 OCR", text or "-")
        return found

    def _setting_multiplier_matches(self, multiplier: int) -> bool:
        found, text = self._wait_for_ocr_patterns(
            [rf"^{multiplier}$", rf"^{multiplier}倍$"],
            timeout=0.8,
            name="PVP 倍率设置值",
            roi=self._mf_roi(*PVP_MULTIPLIER_SETTING_VALUE_OCR_REFERENCE_ROI),
            normalize_multiplier=True,
        )
        self.info_set("PVP 倍率 OCR", text or "-")
        return found

    def _wait_result_and_leave(self, multiplier: int) -> bool:
        self.info_set("当前阶段", "等待战斗结算")
        # The count read in the dialog before 战斗开始; else the most the
        # multiplier allows.
        battles = getattr(self, "_verified_battles", None) or max(
            1, FREE_COCKTAILS_PER_DAY // max(1, int(multiplier))
        )
        result_timeout = self._result_wait_timeout(battles)
        patterns = self._pvp_result_patterns(battles)
        result_roi = self._screen_reference_roi_to_reference_roi(PVP_RESULT_SCREEN_ROI)
        result_found, result_text = self._wait_for_ocr_pattern_majority(
            patterns,
            min_matches=4,
            timeout=result_timeout,
            name="PVP 结算",
            roi=result_roi,
            extra_wait_patterns=[
                (
                    PVP_BATTLE_ONGOING_PATTERN,
                    self._mf_roi(*PVP_BATTLE_ONGOING_OCR_REFERENCE_ROI),
                    "PVP 战斗中 OCR",
                )
            ],
            max_timeout=result_timeout * PVP_RESULT_WAIT_CAP_FACTOR,
        )
        self.info_set("PVP 结算 OCR", result_text or "-")
        if not result_found:
            self.log_warning("镜中之战：等待战斗结算超时，尝试离开结算画面。")
            self._leave_result_after_timeout(patterns, result_roi)
            return False

        self._close_result_page()
        if not self._click_leave_button():
            return False
        if not self._ensure_pvp_hub_after_leave():
            return False
        return self._return_home_from_pvp_hub()

    def _close_result_page(self) -> None:
        self.info_set("当前阶段", "关闭战斗结算")
        self.sleep(1.0)
        self._click_screen_reference(
            *PVP_RESULT_CLOSE_SCREEN_POINT,
            after_sleep=PVP_RESULT_CLOSE_AFTER_SECONDS,
        )

    def _leave_result_after_timeout(self, patterns: list[str], roi) -> None:
        """Leave a result screen the wait did not confirm, the normal way.

        Recovery cannot press the result's ✕ or 离开, so a late or misread
        result used to stop 一键日常.  ✕ only when result labels are read
        now, 离开 only where it is read.
        """
        self.info_set("当前阶段", "结算超时，尝试离开")
        frame = self.capture_frame()
        text = self._ocr_text(frame, name="PVP 结算", roi=roi) if frame is not None else ""
        if self._ocr_pattern_match_count(text, patterns) >= PVP_RESULT_PARTIAL_MATCHES:
            self._close_result_page()
        if self._click_leave_button() and self._ensure_pvp_hub_after_leave():
            self._return_home_from_pvp_hub()

    def _result_wait_timeout(self, battles: int) -> float:
        base_minutes = float(
            self.config.get("PVP 结算基准等待分钟", PVP_RESULT_BASE_MINUTES)
        )
        per_battle = base_minutes * 60.0 / FREE_COCKTAILS_PER_DAY
        return max(PVP_RESULT_MIN_WAIT_SECONDS, per_battle * max(1, int(battles)))

    def _pvp_result_patterns(self, battles: int) -> list[str]:
        completed_count = max(1, int(battles))
        return [
            r"反复战斗结果",
            r"胜利分",
            rf"已完成.*{completed_count}.*次.*战斗",
            r"攻击成绩",
            r"积分变化",
            r"斗魂奖牌.*获得量",
        ]

    def _click_leave_button(self) -> bool:
        end_at = monotonic() + float(self.config.get("PVP 离开等待秒数", 20.0))
        last_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            combined_text, matched_point = self._leave_button_ocr(frame)
            last_text = combined_text or last_text
            self.info_set("PVP 离开 OCR", combined_text or "-")
            if matched_point is not None:
                self.info_set(
                    "PVP 离开点击",
                    f"OCR中心=({matched_point[0]:.0f},{matched_point[1]:.0f})",
                )
                self._click_frame_point(frame, matched_point, after_sleep=2.0)
                return True

            self.sleep(0.5)

        self.info_set("PVP 离开 OCR", last_text or "-")
        return False

    def _leave_button_ocr(
        self,
        frame,
    ) -> tuple[str, tuple[float, float] | None]:
        targets = (
            (
                "失败页",
                "pvp_leave_failure",
                PVP_FAILURE_LEAVE_REFERENCE_ROI,
            ),
            (
                "成功页",
                "pvp_leave_success",
                PVP_SUCCESS_LEAVE_REFERENCE_ROI,
            ),
        )
        ocr_results = []
        matched_point: tuple[float, float] | None = None
        for page_name, ocr_name, roi in targets:
            boxes = self._ocr_boxes(frame, ocr_name, roi=roi)
            text = " ".join(
                str(getattr(box, "name", ""))
                for box in boxes
                if getattr(box, "name", "")
            )
            ocr_results.append((page_name, text))
            leave_box = self._find_ocr_box(boxes, "离开")
            if matched_point is None and leave_box is not None:
                local_point = self._ocr_box_center(leave_box)
                if local_point is not None:
                    roi_left, roi_top, _roi_frame = self._roi_frame(frame, roi)
                    matched_point = (
                        roi_left + local_point[0],
                        roi_top + local_point[1],
                    )

        combined_text = " | ".join(
            f"{page_name}:{text or '-'}" for page_name, text in ocr_results
        )
        return combined_text, matched_point

    def _ensure_pvp_hub_after_leave(self) -> bool:
        self.info_set("当前阶段", "确认离开结果")
        timeout = float(self.config.get("PVP 返回箱庭等待秒数", 10.0))
        end_at = monotonic() + max(0.0, timeout)
        leave_retried = False
        passes = 0
        while True:
            passes += 1
            remaining = max(0.0, end_at - monotonic())
            if passes > 1 and remaining <= 0:
                # A flickering 确认 read used to loop here past the deadline.
                self.info_set("PVP 返回主页", "离开结算超时")
                return False
            state, text, point = self._wait_for_pvp_hub_or_confirm(
                timeout=remaining,
                return_on_leave=not leave_retried,
            )
            if state == "hub":
                return True

            if state == "leave" and point is not None and not leave_retried:
                frame = self.capture_frame()
                retry_text, retry_point = self._leave_button_ocr(frame)
                self.info_set("PVP 离开 OCR", retry_text or "-")
                leave_retried = True
                if retry_point is None:
                    self.info_set("PVP 离开点击", "重试前新帧未识别到离开，继续等待")
                    continue
                self.info_set(
                    "PVP 离开点击",
                    f"首次点击未生效，重试OCR中心=({retry_point[0]:.0f},"
                    f"{retry_point[1]:.0f})",
                )
                self._click_frame_point(frame, retry_point, after_sleep=2.0)
                continue

            if state == "leave":
                self.info_set("PVP 返回主页", "离开重试后仍停留在结算页")
                return False

            if state == "confirm":
                self.sleep(PVP_RANK_CONFIRM_SETTLE_SECONDS)
                frame = self.capture_frame()
                settled_text, settled_point = self._confirm_button_ocr(frame)
                text = settled_text or text
                self.info_set(
                    "PVP 升降级确认稳定",
                    (
                        f"{PVP_RANK_CONFIRM_SETTLE_SECONDS:.1f}秒后新帧"
                        + ("识别到确认"
                           if settled_point is not None
                           else "未再识别到确认")
                    ),
                )
                if settled_point is None:
                    self.info_set("PVP 升降级确认", "确认可能是动画瞬态，继续等待")
                    continue
                point = settled_point

                self.info_set(
                    "PVP 升降级确认",
                    f"稳定新帧OCR中心=({point[0]:.0f},{point[1]:.0f})",
                )
                self._click_frame_point(frame, point, after_sleep=1.0)
                return self._wait_for_template(
                    PVP_MEDALS_TEMPLATE,
                    timeout=timeout,
                    name="PVP 箱庭",
                )

            break

        # hub/leave/confirm 三种状态都在循环内返回，能到达这里只会是等待超时。
        self.info_set("PVP 升降级确认 OCR", text or "-")
        self.info_set("PVP 返回主页", "未检测到 PVP 箱庭或升降级确认按钮")
        return False

    def _wait_for_pvp_hub_or_confirm(
        self,
        timeout: float,
        interval: float = 0.5,
        return_on_leave: bool = True,
    ) -> tuple[str, str, tuple[float, float] | None]:
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        last_hub_score = -1.0
        last_leave_text = ""
        last_leave_point: tuple[float, float] | None = None
        while monotonic() <= end_at:
            frame = self.capture_frame()

            hub = self._match(frame, PVP_MEDALS_TEMPLATE)
            last_hub_score = hub.score
            self.info_set("PVP 箱庭", f"{hub.score:.3f}")
            if self._passes(hub, PVP_MEDALS_TEMPLATE):
                self.info_set("PVP 返回主页", "已回到 PVP 箱庭")
                return "hub", last_text, None

            text, point = self._confirm_button_ocr(frame)
            last_text = text or last_text
            if point is not None:
                return "confirm", text, point

            leave_text, leave_point = self._leave_button_ocr(frame)
            if leave_point is not None:
                self.info_set("PVP 离开 OCR", leave_text)
                last_text = leave_text or last_text
                last_leave_text = leave_text
                last_leave_point = leave_point
                if return_on_leave:
                    return "leave", leave_text, leave_point
            else:
                last_leave_text = ""
                last_leave_point = None

            self.sleep(interval)

        self.info_set("PVP 箱庭", f"{last_hub_score:.3f}")
        if last_leave_point is not None:
            return "leave", last_leave_text, last_leave_point
        return "timeout", last_text, None

    def _confirm_button_ocr(
        self,
        frame,
    ) -> tuple[str, tuple[float, float] | None]:
        boxes = self._ocr_boxes(frame, "PVP 升降级确认")
        text = " ".join(
            str(getattr(box, "name", ""))
            for box in boxes
            if getattr(box, "name", "")
        )
        self.info_set("PVP 升降级确认 OCR", text or "-")
        # Only a rank page (恭喜晋级/段位下滑 + 确认 in the same frame) is
        # confirmed; any other 确认/确定 dialog could be a purchase.
        _text, action_name, confirm_box = self._pvp_special_page_action(
            boxes,
            allow_season_reward=False,
        )
        if action_name not in PVP_RANK_PAGE_TITLES or confirm_box is None:
            if self._find_first_ocr_box(boxes, ("确认", "确定")) is not None:
                self.info_set("PVP 升降级确认", "确认弹窗不是升降级页面，不点击")
            return text, None
        return text, self._ocr_box_center(confirm_box)

    def _return_home_from_pvp_hub(self) -> bool:
        self.info_set("当前阶段", "返回主页")
        in_pvp_hub = self._wait_for_template(
            PVP_MEDALS_TEMPLATE,
            timeout=float(self.config.get("PVP 返回箱庭等待秒数", 10.0)),
            name="PVP 箱庭",
        )
        if not in_pvp_hub:
            self.info_set("PVP 返回主页", "未确认 PVP 箱庭")
            return self._wait_for_home(
                timeout=float(self.config.get("PVP 返回主页等待秒数", 20.0))
            )

        self.info_set("PVP 返回主页", "已确认 PVP 箱庭")
        home_timeout = max(
            0.0,
            float(self.config.get("PVP 返回主页等待秒数", 20.0)),
        )
        # The home wait below polls straight through any loading screen.  The
        # old "wait for loading to appear" step never matched (score -1 all
        # day, 2026-09-27) and froze the screen 6 s on every run.
        self._click_reference(*PVP_BACK_HOME_REFERENCE_POINT, after_sleep=1.0)
        home_deadline = monotonic() + home_timeout
        home_ok = self._wait_for_home(timeout=home_timeout / 2.0)
        if not home_ok:
            remaining = home_deadline - monotonic()
            if remaining > 0.0:
                second_home_timeout = min(
                    remaining,
                    max(0.0, home_timeout - home_timeout / 2.0),
                )
                frame = self.capture_frame()
                hub = self._match(frame, PVP_MEDALS_TEMPLATE)
                self.info_set("PVP 箱庭", f"{hub.score:.3f}")
                if self._passes(hub, PVP_MEDALS_TEMPLATE):
                    self.info_set("PVP 返回主页", "首次点击后仍在PVP箱庭，重试一次")
                    self._click_reference(
                        *PVP_BACK_HOME_REFERENCE_POINT,
                        after_sleep=1.0,
                    )
                    second_home_timeout = min(
                        second_home_timeout,
                        home_deadline - monotonic(),
                    )
                    home_ok = self._wait_for_home(timeout=second_home_timeout)
                else:
                    self.info_set("PVP 返回主页", "未确认主页且未确认仍处PVP箱庭")
                    home_ok = self._wait_for_home(timeout=second_home_timeout)

        self.info_set("PVP 返回主页", "通过" if home_ok else "失败")
        return home_ok

    def _wait_for_home(self, timeout: float, interval: float = 0.5) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        while monotonic() <= end_at:
            frame = self.capture_frame()
            home_ok, left_hits, p95_brightness, gacha_text = (
                self._home_confirmation_signals(frame)
            )
            self.info_set(
                "主页左列关键词",
                f"{left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}",
            )
            self.info_set(
                "主页亮度p95",
                f"{p95_brightness:.0f}/{self._home_p95_threshold():.0f}",
            )
            self.info_set("主页抽抽乐 OCR", gacha_text or "-")
            if home_ok:
                return True
            self.clear_temporary_home_announcement_if_needed(
                left_hits=left_hits,
                required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                brightness=p95_brightness,
                brightness_threshold=self._home_p95_threshold(),
                gacha_ocr_text=gacha_text,
                context="PVP 返回主页",
            )
            self.sleep(interval)
        return False

    def _home_confirmation_signals(self, frame) -> tuple[bool, int, float, str]:
        left_text = self._ocr_text(
            frame,
            name="主页左列",
            roi=HOME_LEFT_COLUMN_OCR_REFERENCE_ROI,
        )
        left_hits = home_left_column_hits(left_text)
        p95_brightness = home_left_column_brightness(frame)
        gacha_result = home_gacha_ocr_with_fallback(
            lambda scale: self._ocr_text(
                frame,
                name=f"主页抽抽乐 x{scale:g}",
                roi=HOME_GACHA_OCR_REFERENCE_ROI,
                ocr_scale=scale,
            )
        )
        gacha_text = gacha_result.text
        self.info_set("主页抽抽乐 OCR 尝试", gacha_result.trace)
        confirmed = home_confirmation_passes(
            left_hits=left_hits,
            required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
            brightness=p95_brightness,
            brightness_threshold=self._home_p95_threshold(),
            gacha_ocr_text=gacha_text,
        )
        return confirmed, left_hits, p95_brightness, gacha_text

    def _recover_stage_position(self) -> None:
        if self._click_template_until(
            PVP_LOC_RESET_TEMPLATE,
            timeout=2.0,
            name="PVP 定位修正",
            target_offset=(0, 100),
            after_sleep=6.0,
        ):
            return

        for spec in PVP_NO_FIND_TEMPLATES:
            if self._click_template_until(
                spec,
                timeout=0.8,
                name="PVP 舞台搜索",
                after_sleep=5.0,
            ):
                return

    def _click_template_until(
        self,
        spec: TemplateSpec,
        timeout: float,
        name: str,
        target: tuple[int, int] | None = None,
        target_offset: tuple[int, int] = (0, 0),
        target_reference_offset: tuple[int, int] = (0, 0),
        after_sleep: float = 0.0,
        interval: float = 0.35,
        stabilize: bool = False,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        last_score = -1.0
        while monotonic() <= end_at:
            frame = self.capture_frame()
            frame_height, frame_width = frame.shape[:2]
            result = self._match(frame, spec)
            last_score = result.score
            self.info_set(name, f"{result.score:.3f}/{result.pixel_score:.3f}")
            if self._passes(result, spec):
                stable_center = None
                if stabilize:

                    def sample_match():
                        sampled_frame = self.capture_frame()
                        return self._match(sampled_frame, spec), sampled_frame.shape

                    stabilized = stabilize_template_match(
                        result,
                        frame.shape,
                        sample_match=sample_match,
                        passes=lambda candidate: self._passes(candidate, spec),
                        sleep=self.sleep,
                        on_sample=lambda candidate: self.info_set(
                            name,
                            f"{candidate.score:.3f}/{candidate.pixel_score:.3f}",
                        ),
                    )
                    if stabilized is None:
                        self.info_set(f"{name}稳定识别", "未形成稳定位置")
                        return False
                    consensus, frame_shape = stabilized
                    frame_height, frame_width = frame_shape[:2]
                    stable_center = consensus.center
                    self.info_set(
                        f"{name}稳定识别",
                        (
                            f"center=({stable_center[0]},{stable_center[1]}), "
                            f"hits={consensus.hit_count}/{consensus.sample_count}, "
                            f"match={consensus.average_score:.3f}, "
                            f"pixel={consensus.average_pixel_score:.3f}, "
                            f"spread={consensus.center_spread:.1f}"
                        ),
                    )
                if target is not None:
                    self._click_reference(target[0], target[1], after_sleep=after_sleep)
                else:
                    reference_offset_x = round(
                        target_reference_offset[0] * frame_width / REFERENCE_WIDTH
                    )
                    reference_offset_y = round(
                        target_reference_offset[1] * frame_height / REFERENCE_HEIGHT
                    )
                    center_x, center_y = (
                        stable_center
                        if stable_center is not None
                        else (
                            result.position[0] + result.size[0] // 2,
                            result.position[1] + result.size[1] // 2,
                        )
                    )
                    x = (
                        center_x
                        + target_offset[0]
                        + reference_offset_x
                    )
                    y = (
                        center_y
                        + target_offset[1]
                        + reference_offset_y
                    )
                    self._click_client(x, y, frame_width, frame_height, after_sleep=after_sleep)
                return True
            self.sleep(interval)

        self.info_set(name, f"{last_score:.3f}")
        return False

    def _wait_for_template(
        self,
        spec: TemplateSpec,
        timeout: float,
        name: str,
        interval: float = 0.35,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        last_score = -1.0
        while monotonic() <= end_at:
            frame = self.capture_frame()
            result = self._match(frame, spec)
            last_score = result.score
            self.info_set(name, f"{result.score:.3f}")
            if self._passes(result, spec):
                return True
            self.sleep(interval)

        self.info_set(name, f"{last_score:.3f}")
        return False

    def _wait_for_ocr_patterns(
        self,
        patterns: list[str],
        timeout: float,
        name: str,
        roi: tuple[int, int, int, int] | None = None,
        interval: float = 0.5,
        normalize_multiplier: bool = False,
        extra_wait_patterns: list[tuple[str, tuple[int, int, int, int], str]] | None = None,
    ) -> tuple[bool, str]:
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            text = self._ocr_text(frame, name=name, roi=roi)
            if normalize_multiplier:
                text = self._normalize_multiplier_text(text)
            last_text = text or last_text
            self.info_set(f"{name} OCR", text or "-")
            if self._matches_any(text, patterns):
                return True, text

            for pattern, extra_roi, info_key in extra_wait_patterns or []:
                extra_text = self._ocr_text(frame, name=info_key, roi=extra_roi)
                if self._matches_any(extra_text, [pattern]):
                    self.info_set(info_key, extra_text)
                    break
            self.sleep(interval)

        return False, last_text

    def _wait_for_ocr_pattern_majority(
        self,
        patterns: list[str],
        min_matches: int,
        timeout: float,
        name: str,
        roi: tuple[int, int, int, int] | None = None,
        interval: float = 0.5,
        extra_wait_patterns: list[tuple[str, tuple[int, int, int, int], str]] | None = None,
        max_timeout: float | None = None,
    ) -> tuple[bool, str]:
        started = monotonic()
        end_at = started + max(0.0, timeout)
        # A read extra pattern is progress: it moves the end on (up to
        # max_timeout) until it is gone for PVP_BATTLE_STUCK_SECONDS.
        cap_at = started + max(timeout, max_timeout or 0.0)
        last_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            text = self._ocr_text(frame, name=name, roi=roi)
            last_text = text or last_text
            self.info_set(f"{name} OCR", text or "-")
            match_count = self._ocr_pattern_match_count(text, patterns)
            self.info_set("PVP 结算命中", f"{match_count}/{len(patterns)}")
            if match_count >= min_matches:
                return True, text

            for pattern, extra_roi, info_key in extra_wait_patterns or []:
                extra_text = self._ocr_text(frame, name=info_key, roi=extra_roi)
                if self._matches_any(extra_text, [pattern]):
                    self.info_set(info_key, extra_text)
                    end_at = min(cap_at, max(end_at, monotonic() + PVP_BATTLE_STUCK_SECONDS))
                    break
            self.sleep(interval)

        return False, last_text

    def _wait_loading_if_present(self, name: str, interval: float = 0.5) -> None:
        found_loading = self._wait_for_template(
            LOADING_TEMPLATE,
            timeout=float(self.config.get("loading 出现等待秒数", 6.0)),
            name=f"{name}_loading_appear",
            interval=interval,
        )
        if not found_loading:
            return

        end_at = monotonic() + float(self.config.get("loading 消失等待秒数", 35.0))
        while monotonic() <= end_at:
            frame = self.capture_frame()
            result = self._match(frame, LOADING_TEMPLATE)
            self.info_set(f"{name}_loading_gone", f"{result.score:.3f}")
            if not self._passes(result, LOADING_TEMPLATE):
                return
            self.sleep(interval)

    def _match(self, frame, spec: TemplateSpec) -> MatchResult:
        empty = MatchResult(-1.0, (0, 0), (0, 0))
        if monotonic() < self._match_pause_until:
            return empty

        try:
            return task_vision.match_template(
                frame,
                spec,
                self.config,
                TEMPLATE_DIR,
                cache=self._templates,
                min_size=5,
                loader=lambda _template_dir, spec: self._load_template(spec),
            )
        except RuntimeError as exc:
            if spec.name not in self._missing_template_names:
                self._missing_template_names.add(spec.name)
                self.log_warning(str(exc), notify=True)
            return empty
        except (cv2.error, MemoryError) as exc:
            self._match_pause_until = monotonic() + 2.0
            message = f"图像匹配内存不足，暂停识别2秒：{spec.name}"
            self.info_set("匹配错误", message)
            if spec.name not in self._match_error_names:
                self._match_error_names.add(spec.name)
                self.log_warning(f"{message}；{exc}", notify=True)
            return empty

    def _load_template(self, spec: TemplateSpec) -> tuple[np.ndarray, np.ndarray | None]:
        return task_vision.load_template(TEMPLATE_DIR, spec, cache=self._templates)

    def _passes(self, result: MatchResult, spec: TemplateSpec) -> bool:
        return task_vision.passes_match(result, spec, self.config)

    def _ocr_text(
        self,
        frame,
        name: str,
        roi: tuple[int, int, int, int] | None = None,
        ocr_scale: float = 1.0,
    ) -> str:
        return " ".join(
            label
            for label, _confidence in self._ocr_entries(
                frame,
                name,
                roi,
                ocr_scale=ocr_scale,
            )
        )

    def _ocr_entries(
        self,
        frame,
        name: str,
        roi: tuple[int, int, int, int] | None = None,
        ocr_scale: float = 1.0,
    ) -> list[tuple[str, float]]:
        boxes = self._ocr_boxes(
            frame,
            name=name,
            roi=roi,
            ocr_scale=ocr_scale,
        )
        entries = []
        for box in boxes:
            label = getattr(box, "name", "")
            if not label:
                continue
            confidence = float(getattr(box, "confidence", 1.0))
            if confidence > 1.0:
                confidence /= 100.0
            entries.append((label, confidence))
        return entries

    def _ocr_boxes(
        self,
        frame,
        name: str,
        roi: tuple[int, int, int, int] | None = None,
        ocr_scale: float = 1.0,
    ):
        ocr_frame = self._crop_reference(frame, roi) if roi is not None else frame
        try:
            if ocr_scale <= 0:
                raise ValueError("ocr_scale must be positive")
            if ocr_scale != 1.0:
                ocr_frame = cv2.resize(
                    ocr_frame,
                    None,
                    fx=ocr_scale,
                    fy=ocr_scale,
                    interpolation=cv2.INTER_CUBIC,
                )
            return self.ocr(
                frame=ocr_frame,
                threshold=float(self.config.get("PVP OCR 阈值", 0.2)),
                target_height=720,
                log=False,
                name=name,
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.info_set(f"{name} OCR 错误", str(exc))
            return []

    def _click_ocr_pattern_center(
        self,
        patterns: list[str],
        name: str,
        roi: tuple[int, int, int, int] | None = None,
        after_sleep: float = 0.0,
    ) -> bool:
        """Click the center of a matching OCR box in the current frame."""
        frame = self.capture_frame()
        boxes = self._ocr_boxes(frame, name=name, roi=roi)
        left, top, _ = self._roi_frame(frame, roi)
        frame_height, frame_width = frame.shape[:2]
        for box in boxes:
            label = str(getattr(box, "name", ""))
            if not self._matches_any(label, patterns):
                continue
            local_point = self._ocr_box_center(box)
            if local_point is None:
                continue
            point = (left + local_point[0], top + local_point[1])
            self.info_set(
                "PVP 自动战斗点击",
                f"OCR中心=({point[0]:.0f},{point[1]:.0f})",
            )
            self._click_client(
                int(round(point[0])),
                int(round(point[1])),
                frame_width,
                frame_height,
                after_sleep=after_sleep,
            )
            return True
        return False

    def _click_reference(self, x: int, y: int, after_sleep: float = 0.0):
        self.operate_click(
            max(0.0, min(1.0, x / REFERENCE_WIDTH)),
            max(0.0, min(1.0, y / REFERENCE_HEIGHT)),
            after_sleep=after_sleep,
        )

    def _click_frame_point(
        self,
        frame: np.ndarray,
        point: tuple[float, float],
        after_sleep: float = 0.0,
    ) -> None:
        frame_height, frame_width = frame.shape[:2]
        self.operate_click(
            max(0.0, min(1.0, point[0] / max(1, frame_width))),
            max(0.0, min(1.0, point[1] / max(1, frame_height))),
            after_sleep=after_sleep,
        )

    @classmethod
    def _find_first_ocr_box(cls, boxes: list, keywords: tuple[str, ...]):
        for keyword in keywords:
            box = cls._find_ocr_box(boxes, keyword)
            if box is not None:
                return box
        return None

    @staticmethod
    def _mf_point(x: int, y: int) -> tuple[int, int]:
        return (
            round(x * REFERENCE_WIDTH / HD720_REFERENCE_WIDTH),
            round(y * REFERENCE_HEIGHT / HD720_REFERENCE_HEIGHT),
        )

    @staticmethod
    def _mf_roi(x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
        left, top = PVPTask._mf_point(x, y)
        right, bottom = PVPTask._mf_point(x + width, y + height)
        return left, top, max(1, right - left), max(1, bottom - top)

    def _click_screen_reference(self, x: int, y: int, after_sleep: float = 0.0):
        self.operate_click(
            max(0.0, min(1.0, x / ENTRY_REFERENCE_WIDTH)),
            max(0.0, min(1.0, y / ENTRY_REFERENCE_HEIGHT)),
            after_sleep=after_sleep,
        )

    @staticmethod
    def _screen_roi_frame(
        frame: np.ndarray,
        roi: tuple[int, int, int, int] | None,
    ) -> tuple[int, int, np.ndarray]:
        if roi is None:
            return 0, 0, frame
        height, width = frame.shape[:2]
        x, y, w, h = roi
        scale_x = width / ENTRY_REFERENCE_WIDTH
        scale_y = height / ENTRY_REFERENCE_HEIGHT
        left = max(0, round(x * scale_x))
        top = max(0, round(y * scale_y))
        right = min(width, round((x + w) * scale_x))
        bottom = min(height, round((y + h) * scale_y))
        return left, top, frame[top:bottom, left:right]

    @staticmethod
    def _crop_screen_reference(frame, roi: tuple[int, int, int, int] | None):
        if roi is None:
            return frame
        _, _, crop = PVPTask._screen_roi_frame(frame, roi)
        return crop

    def _click_client(
        self,
        x: int,
        y: int,
        frame_width: int,
        frame_height: int,
        after_sleep: float = 0.0,
    ):
        self.operate_click(
            max(0.0, min(1.0, x / max(1, frame_width))),
            max(0.0, min(1.0, y / max(1, frame_height))),
            after_sleep=after_sleep,
        )

    def _home_p95_threshold(self) -> float:
        return float(self.config.get("主页压暗阈值", HOME_DIMMED_P95_THRESHOLD_DEFAULT))

    @staticmethod
    def _matches_any(text: str, patterns: list[str]) -> bool:
        normalized = PVPTask._normalize_text(text)
        for pattern in patterns:
            normalized_pattern = PVPTask._normalize_text(pattern)
            if re.search(normalized_pattern, normalized, flags=re.IGNORECASE):
                return True
        return False

    @staticmethod
    def _ocr_pattern_match_count(text: str, patterns: list[str]) -> int:
        return sum(1 for pattern in patterns if PVPTask._matches_any(text, [pattern]))

    _normalize_text = staticmethod(normalize_ocr_text)

    @staticmethod
    def _normalize_multiplier_text(text: str) -> str:
        normalized = PVPTask._normalize_text(text)
        return normalized.replace("倍", "").replace("o", "0")

    def _target_multiplier(self) -> int:
        raw = str(self.config.get("竞技场战斗倍数", 1)).replace("倍", "")
        try:
            multiplier = int(raw)
        except ValueError:
            multiplier = 1
        low, high = MULTIPLIER_RANGE
        return multiplier if low <= multiplier <= high else 1

    @staticmethod
    def _roi_frame(
        frame: np.ndarray,
        roi: tuple[int, int, int, int] | None,
    ) -> tuple[int, int, np.ndarray]:
        return reference_roi_frame(frame, roi, (REFERENCE_WIDTH, REFERENCE_HEIGHT))

    @staticmethod
    def _crop_reference(frame, roi: tuple[int, int, int, int] | None):
        return reference_roi_frame(frame, roi, (REFERENCE_WIDTH, REFERENCE_HEIGHT))[2]

    @staticmethod
    def _screen_reference_roi_to_reference_roi(
        roi: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        x, y, width, height = roi
        left = round(x * REFERENCE_WIDTH / ENTRY_REFERENCE_WIDTH)
        top = round(y * REFERENCE_HEIGHT / ENTRY_REFERENCE_HEIGHT)
        right = round((x + width) * REFERENCE_WIDTH / ENTRY_REFERENCE_WIDTH)
        bottom = round((y + height) * REFERENCE_HEIGHT / ENTRY_REFERENCE_HEIGHT)
        return left, top, max(1, right - left), max(1, bottom - top)

LOADING_TEMPLATE = TemplateSpec(
    name="loading",
    file_name="image/UI_loading_black.png",
    threshold_key="加载页面阈值",
    default_threshold=0.72,
)

QUICK_PACK_TEMPLATE = TemplateSpec(
    name="quick_pack",
    file_name="image/green/QuickSwitchPlayIco.png",
    threshold_key="快速切换按钮阈值",
    default_threshold=0.88,
    relative_rois=QUICK_SWITCH_SEARCH_REGIONS,
    green_mask=True,
    scale_ratios=(0.95, 0.975, 1.0, 1.025, 1.05),
    min_pixel_score=0.85,
    minimum_safe_threshold=0.88,
    # 与 SquareGoddessTask.QUICK_SWITCH_TEMPLATE 同一按钮：梦幻广场内暗色
    # 圆底样式在 1600x901 实机帧 zncc 最高 0.838（RPT-20260902-225925），
    # 0.85 门禁确定性误拒；同帧误检 zncc 最高 0.43，0.78 仍有足够余量。
    min_zncc_score=0.78,
)

PVP_MEDALS_TEMPLATE = TemplateSpec(
    name="pvp_medals",
    file_name="image/pvp-medals.png",
    threshold_key="PVP 箱庭阈值",
    default_threshold=0.78,
    # RPT-20260905-195025：实机箱庭顶栏比校准位置整体上移约 4px，旧 ROI
    # 上边界正卡在图标顶缘（零余量）致峰值 0.726<0.78 确认超时；上下各放
    # 10px 余量后同帧 0.962/pixel 0.936 通过。
    roi=(793, 29, 340, 55),
    scale_ratios=(0.944, 0.96, 0.976, 1.0, 1.04),
    min_pixel_score=0.88,
)

PVP_STAGE_TEMPLATE = TemplateSpec(
    name="pvp_stage",
    file_name="image/pvp-stage.png",
    threshold_key="PVP 舞台阈值",
    default_threshold=0.72,
    roi=(190, 238, 900, 620),
)

PVP_LOC_RESET_TEMPLATE = TemplateSpec(
    name="pvp_loc_reset",
    file_name="image/pvp-loc-reset.png",
    threshold_key="PVP 定位修正阈值",
    default_threshold=0.76,
)

PVP_NO_FIND_TEMPLATES = [
    TemplateSpec(
        name="pvp_nofind_UT_bk",
        file_name="image/pvp-nofind-UT-bk.png",
        threshold_key="PVP 定位修正阈值",
        default_threshold=0.76,
    ),
    TemplateSpec(
        name="pvp_nofind_ut_bk2",
        file_name="image/pvp-nofind-ut-bk2.png",
        threshold_key="PVP 定位修正阈值",
        default_threshold=0.76,
    ),
    TemplateSpec(
        name="pvp_nofind_UT_ft",
        file_name="image/pvp-nofind-UT-ft.png",
        threshold_key="PVP 定位修正阈值",
        default_threshold=0.76,
    ),
    TemplateSpec(
        name="pvp_nofind_UT_Rt",
        file_name="image/pvp-nofind-UT-Rt.png",
        threshold_key="PVP 定位修正阈值",
        default_threshold=0.76,
    ),
    TemplateSpec(
        name="pvp_nofind_twoaudience",
        file_name="image/pvp-nofind-twoaudience.png",
        threshold_key="PVP 定位修正阈值",
        default_threshold=0.76,
    ),
    TemplateSpec(
        name="pvp_nofind_waiter_fr",
        file_name="image/pvp-nofind-waiter-fr.png",
        threshold_key="PVP 定位修正阈值",
        default_threshold=0.76,
    ),
    TemplateSpec(
        name="pvp_nofind_aman_sit",
        file_name="image/pvp-nofind-aman-sit.png",
        threshold_key="PVP 定位修正阈值",
        default_threshold=0.76,
    ),
]
