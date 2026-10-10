"""Quick-hunt configuration and feature mixins for daily-style tasks."""

from __future__ import annotations

import re
from dataclasses import replace
from time import monotonic

import cv2
import numpy as np

from src.tasks.map_trade.models import TemplateSpec
from src.tasks.task_vision_mixin import (
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
    TaskVisionMixin,
)
from src.utils.calibration import HD_720
from src.utils.colour_rules import switch_yellow_ratio
from src.utils.free_switch import ensure_free_switch_on
from src.utils.home_confirmation import HOME_LEFT_COLUMN_REQUIRED_HITS
from src.utils.press_confirm import wait_for

QUICK_HUNT_CHILD_CONFIG_KEYS = (
    "快速狩猎双倍策略",
    "快速狩猎资源倾向",
    "快速狩猎米饭分配",
    "快速狩猎模板阈值",
    "快速狩猎像素相似度阈值",
    "快速狩猎界面等待秒数",
    "快速狩猎结算等待秒数",
    "快速狩猎入口测试",
    "快速狩猎菜单测试",
    "快速狩猎圣石测试",
    "快速狩猎完整测试",
)

QUICK_HUNT_CONFIG_KEYS = ("执行快速狩猎", *QUICK_HUNT_CHILD_CONFIG_KEYS)

def quick_hunt_cost(text: str) -> int | None:
    """The cost on the start button ("狩猎●6", "狩猎 84")."""
    matched = re.search(r"狩猎\D{0,3}(\d{1,4})", str(text).replace(",", ""))
    return int(matched.group(1)) if matched else None


def quick_hunt_free_pool(text: str) -> int | None:
    """The free amount a of "a/b +5.6K"."""
    matched = re.search(r"(\d{1,4})\s*[/／]\s*\d{1,4}", str(text))
    return int(matched.group(1)) if matched else None


def quick_hunt_stone_value(text: str) -> int | None:
    """One stone count as shown ("300", "1,250", "1.2K", "1.5万")."""
    cleaned = re.sub(r"[,，\s]", "", str(text))
    matched = re.search(r"(\d+(?:\.\d+)?)([KkMm万]?)", cleaned)
    if not matched:
        return None
    number, unit = matched.groups()
    if not unit:
        return int(re.sub(r"\D", "", number))
    scale = {"k": 1_000, "m": 1_000_000, "万": 10_000}[unit.lower()]
    return round(float(number) * scale)


def _quick_hunt_relative_roi(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> tuple[float, float, float, float]:
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return (
        left / REFERENCE_WIDTH,
        top / REFERENCE_HEIGHT,
        right / REFERENCE_WIDTH,
        bottom / REFERENCE_HEIGHT,
    )


def quick_hunt_fold_button(frame) -> tuple[int, int] | None:
    """Centre (frame pixels) of the folded panel's ∨ button, or None.

    Language-free: a white ∨ (both ends high, the middle low) on a dark round
    button.  Measured on the player's frame at 1080p: the ∨ is 25×15 px and
    the button around it reads about 16 out of 255.
    """
    height, width = frame.shape[:2]
    if frame.ndim < 3 or frame.shape[2] < 3:
        return None
    left, top, right, bottom = QUICK_HUNT_FOLD_BUTTON_ROI
    x0, y0 = round(left * width), round(top * height)
    region = frame[y0 : round(bottom * height), x0 : round(right * width), :3]
    if region.size == 0:
        return None
    unit = height / REFERENCE_HEIGHT
    hsv = cv2.cvtColor(np.ascontiguousarray(region), cv2.COLOR_BGR2HSV)
    value = hsv[:, :, 2].astype(np.float32)
    white = ((hsv[:, :, 2] >= 190) & (hsv[:, :, 1] <= 70)).astype(np.uint8)
    count, labels, stats, _centres = cv2.connectedComponentsWithStats(white, connectivity=8)
    rows, cols = np.mgrid[0 : region.shape[0], 0 : region.shape[1]]
    for index in range(1, count):
        x, y, w, h = (int(v) for v in stats[index][:4])
        if not (14 * unit <= w <= 34 * unit and 7 * unit <= h <= 22 * unit):
            continue
        if not 1.3 <= w / h <= 3.2:
            continue
        piece = labels[y : y + h, x : x + w] == index
        band, side = max(1, h // 3), max(1, w // 3)
        top_band, bottom_band = piece[:band], piece[h - band :]
        top_ends = (top_band[:, :side].mean() + top_band[:, w - side :].mean()) / 2
        bottom_ends = (bottom_band[:, :side].mean() + bottom_band[:, w - side :].mean()) / 2
        if top_ends < top_band[:, side : w - side].mean() + 0.15:
            continue
        if bottom_band[:, side : w - side].mean() < bottom_ends + 0.15:
            continue  # not a ∨ (a ∧ folds the panel away again)
        cx, cy = x + w / 2, y + h / 2
        distance = np.hypot(cols - cx, rows - cy)
        ring = (distance >= w * 0.75) & (distance <= 24 * unit)
        if ring.sum() < 20 or float(value[ring].mean()) > 90:
            continue
        return x0 + round(cx), y0 + round(cy)
    return None


QUICK_HUNT_ENTRY_POINT = (1756 / REFERENCE_WIDTH, 262 / REFERENCE_HEIGHT)

QUICK_HUNT_RED_POINT = (1782 / REFERENCE_WIDTH, 237 / REFERENCE_HEIGHT)

# 红点判定（OpenCV HSV，H 0-179）：红色在 H 轴两端（<=10 或 >=170），
# 饱和度与明度需同时达到下限，避免把粉/暗色 UI 元素误判为红点。
RED_DOT_HUE_WRAPAROUND_MAXIMUM = 10
RED_DOT_HUE_WRAPAROUND_MINIMUM = 170
RED_DOT_SATURATION_MINIMUM = 140
RED_DOT_VALUE_MINIMUM = 150

# 菜单按钮可用态判定：灰度 >= 170 的"亮像素"占按钮区域至少 2%。
BUTTON_ENABLED_BRIGHT_GRAY_MINIMUM = 170
BUTTON_ENABLED_BRIGHT_MIN_RATIO = 0.02

QUICK_HUNT_RESOURCE_CAPACITIES = {"米饭": 90}

# The dialog's 仅使用免费米饭 / 仅使用免费火把 switch (1920x1080 reference).
# With it off, MAX also takes the stored stock ("+5.6K"), so it is always
# checked and turned on first, and the cost is compared with the free pool
# (review 2026-09-27: other players may have left it off).
QUICK_HUNT_FREE_SWITCH_BOX = (1222, 294, 44, 24)
QUICK_HUNT_FREE_SWITCH_POINT = (1244, 306)
QUICK_HUNT_FREE_LABEL_ROI = _quick_hunt_relative_roi(1040, 288, 1220, 324)
QUICK_HUNT_FREE_SWITCH_MIN_RATIO = 0.05  # live on: 0.37
QUICK_HUNT_FREE_SWITCH_SETTLE_SECONDS = 2.0
# Parts of the quick-hunt dialog / cave list are read for this long after
# a click before a miss counts (one look failed when they drew late).
QUICK_HUNT_DIALOG_DRAW_SECONDS = 3.0
# Words only the open quick-hunt dialog shows in its count row.
QUICK_HUNT_DIALOG_BUTTONS = re.compile(r"取消|MIN|MAX", re.IGNORECASE)
QUICK_HUNT_HOME_LAST_WAIT_SECONDS = 6.0

QUICK_HUNT_RESOURCE_ROI = _quick_hunt_relative_roi(1724, 80, 1602, 38)
# Small counters are read as if the frame were this tall (4K).
SMALL_TEXT_HEIGHT = 2160

QUICK_HUNT_BUTTON_ROI = _quick_hunt_relative_roi(1720, 1018, 1599, 963)

QUICK_HUNT_COUNT_ROI = _quick_hunt_relative_roi(1298, 826, 623, 257)

QUICK_HUNT_START_ROI = _quick_hunt_relative_roi(1136, 805, 963, 764)

QUICK_HUNT_REWARD_ROI = _quick_hunt_relative_roi(1055, 1019, 857, 965)
# After the 点击画面即可返回 tap: how long the reward page may take to go.
QUICK_HUNT_REWARD_GONE_SECONDS = 3.0

QUICK_HUNT_DIALOG_ROI = _quick_hunt_relative_roi(750, 630, 1200, 915)

QUICK_HUNT_MAP_SCAN_ROI = _quick_hunt_relative_roi(1528, 865, 330, 165)

QUICK_HUNT_CRYSTAL_TITLE_ROI = _quick_hunt_relative_roi(340, 452, 235, 128)

QUICK_HUNT_STONE_LIST_ROI = QUICK_HUNT_CRYSTAL_TITLE_ROI

# 狩猎菜单左列"圣石洞穴"入口（图标+文字）区域；识别点击优先于固定参考点。
QUICK_HUNT_CRYSTAL_CLICK_ROI = _quick_hunt_relative_roi(260, 520, 100, 400)

# 实机 OCR（RPT-20260901-233554 与 20260724 录屏帧复现）稳定把末字"穴"
# 读成"空/究"（圣石洞空/圣石洞究），四字全匹配从未命中；左列该三字前缀
# 唯一，放宽到"圣石洞"。
QUICK_HUNT_CRYSTAL_ENTRY_PATTERN = r"圣石洞"
# Looks (strip then whole screen, about 4 s each) for the entry before the
# screen counts as not showing the hunt menu.  A player's run (v0.1.17,
# 1080p, 2026-10-10) read neither the entry nor the cave list for 30 s and
# pressed the fixed point three times anyway.
QUICK_HUNT_CRYSTAL_ENTRY_LOOKS = 2
# The hunt menu's left column: the fixed point is pressed only under it.
QUICK_HUNT_MENU_PATTERN = r"圣石洞|狩猎场|冒险航线"

QUICK_HUNT_STONE_COUNT_ROI = _quick_hunt_relative_roi(1794, 288, 1689, 80)
# The top-right panel can be folded away: then it shows only 火把 with a round
# ∨ button under it and no stone counts at all (Bilibili 琴烟, v0.1.17, 1080p,
# 2026-10-10).  Leo: 「聖石如果偵測玩家收起來 就把它點開」.
QUICK_HUNT_FOLD_BUTTON_ROI = _quick_hunt_relative_roi(1650, 78, 1800, 170)

QUICK_HUNT_DOUBLE_ROI = _quick_hunt_relative_roi(168, 337, 135, 205)

QUICK_HUNT_ADVENTURE_LIST_ROI = _quick_hunt_relative_roi(228, 504, 128, 116)

QUICK_HUNT_ADVENTURE_LABEL_PATTERNS = {
    "金币": r"^金币$",
    "经验": r"^史莱姆$",
}

QUICK_HUNT_ADVENTURE_MAP_PATTERNS = {
    "金币": r"哥布林遗迹",
    "经验": r"史莱姆王国",
}

QUICK_HUNT_CRYSTAL_POINT = (177, 449)

QUICK_HUNT_RETURN_POINT = (101, 55)

QUICK_HUNT_STONE_ELEMENTS = ("火", "水", "风", "光", "暗")

QUICK_HUNT_RETURN_MAP_PATTERNS = (
    ("野猪洞穴", re.compile(r"野猪洞穴")),
    ("蜥蜴人祭坛", re.compile(r"蜥.?蜴.?人.?祭坛")),
    ("守山人休息处", re.compile(r"守山人休息处")),
    ("哥布林遗迹", re.compile(r"哥布林遗迹")),
    ("史莱姆王国", re.compile(r"史莱姆王国")),
    ("属性洞穴", re.compile(r"[火水风光暗].?之?.?洞穴")),
)

QUICK_HUNT_EXECUTION_MAP_PATTERNS = QUICK_HUNT_RETURN_MAP_PATTERNS

QUICK_HUNT_LIST_COLLAPSE_TEMPLATE = TemplateSpec(
    "快速狩猎资源列表收起",
    "image/green/Battle_ListCollapseGE.png",
    threshold=0.78,
    relative_roi=_quick_hunt_relative_roi(1600, 195, 1785, 579),
    green_mask=True,
    min_pixel_score=0.72,
)

QUICK_HUNT_DOUBLE_TEMPLATE = TemplateSpec(
    "当前航线双倍",
    "Double.png",
    threshold=0.8,
    relative_roi=QUICK_HUNT_DOUBLE_ROI,
    min_pixel_score=0.72,
)


class QuickHuntConfigMixin:
    include_quick_hunt_config = False

    quick_hunt_default_config = {
        '执行快速狩猎': True,
        '快速狩猎双倍策略': "优先双倍",
        '快速狩猎资源倾向': "金币",
        '快速狩猎米饭分配': "狩猎场x1 / 双倍图MAX",
        '快速狩猎模板阈值': 0.78,
        '快速狩猎像素相似度阈值': 0.72,
        '快速狩猎界面等待秒数': 8.0,
        '快速狩猎结算等待秒数': 15.0,
        '快速狩猎入口测试': "",
        '快速狩猎菜单测试': "",
        '快速狩猎圣石测试': "",
        '快速狩猎完整测试': "",
    }

    quick_hunt_config_description = {
        '执行快速狩猎': "消耗免费米饭和火把。",
        '快速狩猎双倍策略': "优先双倍：只打有双倍的冒险航线（都双倍时选金币，都没有就跳过）；"
        "强制双倍：按资源倾向先找双倍；"
        "忽视双倍：不看双倍，固定只打金币航线（适合史莱姆/经验已溢出的后期玩家）。",
        '快速狩猎资源倾向': "强制双倍策略下优先检查金币或经验。",
        '快速狩猎米饭分配': "狩猎场 MIN 时双倍冒险航线使用 MAX；"
        "狩猎场 MAX 时跳过冒险航线。",
        '快速狩猎模板阈值': "快速狩猎模板匹配最低分数。",
        '快速狩猎像素相似度阈值': "快速狩猎模板还必须达到的像素相似度。",
        '快速狩猎界面等待秒数': "等待狩猎菜单、地图和按钮出现的最长时间。",
        '快速狩猎结算等待秒数': "点击狩猎后等待奖励页或资源不足提示的最长时间。",
        '快速狩猎入口测试': "只读检查不会点击；打开菜单会先确认首页，再检查并点击"
        "1920×1080参考点(1782,237)。测试前停留在首页。",
        '快速狩猎菜单测试': "只读检查不会点击；执行米饭会按当前配置实际消耗米饭。"
        "测试前需要已经打开快速狩猎菜单。",
        '快速狩猎圣石测试': "执行圣石会按当前配置实际消耗火把；返回主页仅测试返回流程。"
        "测试前需要已经打开快速狩猎菜单。",
        '快速狩猎完整测试': "从首页执行完整快速狩猎流程，会实际消耗米饭和火把。",
    }

    def _quick_hunt_type_config(self) -> dict:
        return {
            '执行快速狩猎': {
                "sub_configs": {
                    True: [
                        "快速狩猎双倍策略",
                        "快速狩猎资源倾向",
                        "快速狩猎米饭分配",
                        "快速狩猎模板阈值",
                        "快速狩猎像素相似度阈值",
                        "快速狩猎界面等待秒数",
                        "快速狩猎结算等待秒数",
                        "快速狩猎入口测试",
                        "快速狩猎菜单测试",
                        "快速狩猎圣石测试",
                        "快速狩猎完整测试",
                    ]
                }
            },
            '快速狩猎双倍策略': {
                "type": "drop_down",
                "options": ["优先双倍", "强制双倍", "忽视双倍"],
            },
            '快速狩猎资源倾向': {
                "type": "drop_down",
                "options": ["金币", "经验"],
            },
            '快速狩猎米饭分配': {
                "type": "drop_down",
                "options": ["狩猎场x1 / 双倍图MAX", "狩猎场MAX / 跳过冒险航线"],
            },
            '快速狩猎模板阈值': {"min": 0.5, "max": 0.95, "step": 0.01},
            '快速狩猎像素相似度阈值': {
                "min": 0.5,
                "max": 0.95,
                "step": 0.01,
            },
            '快速狩猎界面等待秒数': {"min": 2.0, "max": 30.0, "step": 1.0},
            '快速狩猎结算等待秒数': {"min": 5.0, "max": 60.0, "step": 1.0},
            '快速狩猎入口测试': {
                "type": "button",
                "buttons": [
                    {
                        "text": "只读检查入口",
                        "callback": lambda _checked=False: self._queue_quick_hunt_test(
                            "inspect_entry"
                        ),
                    },
                    {
                        "text": "打开狩猎菜单",
                        "callback": lambda _checked=False: self._queue_quick_hunt_test(
                            "open_menu"
                        ),
                    },
                ],
            },
            '快速狩猎菜单测试': {
                "type": "button",
                "buttons": [
                    {
                        "text": "只读检查菜单",
                        "callback": lambda _checked=False: self._queue_quick_hunt_test(
                            "inspect_menu"
                        ),
                    },
                    {
                        "text": "执行米饭(消耗)",
                        "callback": lambda _checked=False: self._queue_quick_hunt_test(
                            "rice"
                        ),
                    },
                ],
            },
            '快速狩猎圣石测试': {
                "type": "button",
                "buttons": [
                    {
                        "text": "执行圣石(消耗)",
                        "callback": lambda _checked=False: self._queue_quick_hunt_test(
                            "crystal"
                        ),
                    },
                    {
                        "text": "返回主页",
                        "callback": lambda _checked=False: self._queue_quick_hunt_test(
                            "home"
                        ),
                    },
                ],
            },
            '快速狩猎完整测试': {
                "type": "button",
                "callback": lambda _checked=False: self._queue_quick_hunt_test("full"),
                "text": "完整执行(消耗)",
            },
        }

    def _install_quick_hunt_config(self) -> None:
        if self.include_quick_hunt_config:
            self._quick_hunt_vision = None
            self._quick_hunt_test_action = None
        self.default_config.update(self.quick_hunt_default_config)
        self.config_description.update(self.quick_hunt_config_description)
        self.config_type.update(self._quick_hunt_type_config())
        if not self.include_quick_hunt_config:
            for key in QUICK_HUNT_CONFIG_KEYS:
                self.default_config.pop(key, None)
                self.config_description.pop(key, None)
                self.config_type.pop(key, None)


class QuickHuntFeatureMixin:
    def _queue_quick_hunt_test(self, action: str) -> None:
        labels = {
            "inspect_entry": "只读检查入口",
            "open_menu": "打开狩猎菜单",
            "inspect_menu": "只读检查菜单",
            "rice": "执行米饭流程",
            "crystal": "执行圣石洞穴",
            "home": "返回主页",
            "full": "完整快速狩猎",
        }
        label = labels.get(action)
        if label is None:
            self.log_warning(f"不支持的快速狩猎测试动作：{action}", notify=True)
            return
        if self.enabled or self.running:
            self.log_warning("已有任务正在运行，请停止后再启动快速狩猎测试。", notify=True)
            return

        self._quick_hunt_test_action = action
        try:
            self.start()
            self._status_set("快速狩猎测试状态", f"已加入队列：{label}")
        except Exception as exc:
            self._quick_hunt_test_action = None
            self.log_error(f"无法启动快速狩猎测试：{label}", exc, notify=True)

    def _run_quick_hunt_test(self, action: str) -> bool:
        labels = {
            "inspect_entry": "只读检查入口",
            "open_menu": "打开狩猎菜单",
            "inspect_menu": "只读检查菜单",
            "rice": "执行米饭流程",
            "crystal": "执行圣石洞穴",
            "home": "返回主页",
            "full": "完整快速狩猎",
        }
        label = labels.get(action, action)
        self._status_set("当前任务", f"快速狩猎测试：{label}")
        self._status_set("快速狩猎测试状态", f"执行中：{label}")
        try:
            if action == "inspect_entry":
                success = self._quick_hunt_inspect_entry()
                detail = "识别完成"
            elif action == "open_menu":
                opened = self._quick_hunt_open_menu()
                success = opened == "opened"
                detail = {
                    "opened": "菜单已打开",
                    "failed": "入口识别或菜单确认失败",
                }.get(opened, opened)
            elif action == "inspect_menu":
                success = self._quick_hunt_inspect_menu()
                detail = "识别完成"
            elif action == "rice":
                success = self._quick_hunt_run_rice_scheduler()
                detail = "米饭流程完成" if success else "米饭流程失败"
            elif action == "crystal":
                success = self._quick_hunt_run_crystal_cave()
                detail = "圣石流程完成" if success else "圣石流程失败"
            elif action == "home":
                success = self._quick_hunt_return_home()
                detail = "已确认主页" if success else "返回主页失败"
            elif action == "full":
                success = self.run_quick_hunt()
                detail = "完整流程完成" if success else "完整流程失败"
            else:
                success = False
                detail = f"不支持的动作：{action}"

            result = "通过" if success else "失败"
            self._status_set("快速狩猎测试状态", f"{label}：{result}；{detail}")
            self.log_completion(f"快速狩猎测试结束：{label}，{result}，{detail}")
            return success
        except Exception as exc:
            self._status_set("快速狩猎测试状态", f"{label}：异常")
            self.log_error(f"快速狩猎测试异常：{label}", exc, notify=True)
            return False
        finally:
            self._quick_hunt_test_action = None

    def _quick_hunt_inspect_entry(self) -> bool:
        """Inspect entry signals without moving the mouse or clicking."""

        frame = self.capture_frame()
        home_ok, left_hits, p95_brightness, gacha_text = (
            self._quick_hunt_home_signals(frame)
        )
        self._status_set(
            "快速狩猎首页按钮",
            f"左列关键词 {left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}"
            f"({'通过' if home_ok else '未通过'})",
        )
        is_red, point, bgr, hsv = self._quick_hunt_entry_red_state(frame)
        self._status_set(
            "快速狩猎红点识别",
            f"point={point}, BGR={bgr}, HSV={hsv}, {'红色' if is_red else '非红色'}",
        )
        self._status_set(
            "快速狩猎主页亮度",
            f"p95={p95_brightness:.0f}/{self._home_p95_threshold():.0f}",
        )
        self._status_set("快速狩猎主页抽抽乐 OCR", gacha_text or "-")
        return True

    def _quick_hunt_inspect_menu(self) -> bool:
        """Inspect menu OCR and templates using one frame without clicking."""

        vision = self._quick_vision()
        frame = self.capture_frame()
        ocr_regions = (
            ("快速狩猎菜单 OCR", "测试-菜单标题", None),
            ("快速狩猎资源 OCR", "测试-资源数量", QUICK_HUNT_RESOURCE_ROI),
            ("快速狩猎按钮 OCR", "测试-快速狩猎按钮", QUICK_HUNT_BUTTON_ROI),
            ("快速狩猎次数 OCR", "测试-次数选择", QUICK_HUNT_COUNT_ROI),
            ("快速狩猎开始 OCR", "测试-开始狩猎", QUICK_HUNT_START_ROI),
            ("快速狩猎奖励 OCR", "测试-奖励页面", QUICK_HUNT_REWARD_ROI),
            ("快速狩猎异常 OCR", "测试-异常弹窗", QUICK_HUNT_DIALOG_ROI),
            ("快速狩猎地图 OCR", "测试-地图范围", QUICK_HUNT_MAP_SCAN_ROI),
            ("快速狩猎圣石 OCR", "测试-圣石列表", QUICK_HUNT_STONE_LIST_ROI),
            ("快速狩猎圣石数量", "测试-圣石数量", QUICK_HUNT_STONE_COUNT_ROI),
        )
        for status_key, name, roi in ocr_regions:
            text = vision.ocr_text(frame, name, relative_roi=roi)
            self._status_set(status_key, text or "-")

        collapse = self._quick_spec(QUICK_HUNT_LIST_COLLAPSE_TEMPLATE)
        collapse_match = vision.match(frame, collapse)
        self._status_set(
            "快速狩猎收起模板",
            f"{collapse_match.score:.3f}/{collapse_match.pixel_score:.3f}"
            f"({'通过' if vision.passes(collapse_match, collapse) else '未通过'})",
        )

        self._quick_hunt_double_states(frame)
        return True

    def run_quick_hunt(self) -> bool:
        """Run the quick-hunt scheduler using PC-safe mouse input."""

        opened = self._quick_hunt_open_menu()
        if opened != "opened":
            self._status_set("快速狩猎结果", "无法进入狩猎菜单")
            return False

        success = True
        try:
            rice_ok = self._quick_hunt_run_rice_scheduler()
            success = success and rice_ok
            # 狩猎场、冒险航线、圣石洞穴 always run (Leo 2026-10-04: removed the
            # three switches from the settings).
            if rice_ok:
                crystal_ok = self._quick_hunt_run_crystal_cave()
                success = success and crystal_ok
        finally:
            home_ok = self._quick_hunt_return_home()
            success = success and home_ok

        self._status_set("快速狩猎结果", "完成" if success else "失败")
        return success

    def _quick_hunt_home_signals(
        self,
        frame,
    ) -> tuple[bool, int, float, str]:
        return self._home_confirmation_signals(frame, "快速狩猎主页抽抽乐")

    def _wait_for_quick_hunt_home(self, interval: float = 0.35) -> bool:
        end_at = monotonic() + float(self.config.get("主页确认等待秒数", 10.0))
        last_left_hits = 0
        last_p95 = 0.0
        last_gacha_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            home_ok, last_left_hits, last_p95, last_gacha_text = (
                self._quick_hunt_home_signals(frame)
            )
            self._status_set(
                "快速狩猎首页按钮",
                f"左列关键词 {last_left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}",
            )
            self._status_set(
                "快速狩猎主页亮度",
                f"p95={last_p95:.0f}/{self._home_p95_threshold():.0f}",
            )
            self._status_set(
                "快速狩猎主页抽抽乐 OCR",
                last_gacha_text or "-",
            )
            if home_ok:
                return True
            self.clear_temporary_home_announcement_if_needed(
                left_hits=last_left_hits,
                required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                brightness=last_p95,
                brightness_threshold=self._home_p95_threshold(),
                gacha_ocr_text=last_gacha_text,
                context="快速狩猎确认主页",
            )
            self.sleep(interval)

        self.log_info(
            "快速狩猎：未同时确认左列关键词、亮度和抽抽乐文字，"
            f"left={last_left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}, "
            f"p95={last_p95:.0f}/{self._home_p95_threshold():.0f}, "
            f"ocr={last_gacha_text or '-'}。"
        )
        return False

    @staticmethod
    def _quick_hunt_entry_red_state(
        frame,
    ) -> tuple[bool, tuple[int, int], tuple[int, int, int], tuple[int, int, int]]:
        height, width = frame.shape[:2]
        x = max(0, min(width - 1, round(width * QUICK_HUNT_RED_POINT[0])))
        y = max(0, min(height - 1, round(height * QUICK_HUNT_RED_POINT[1])))
        if frame.ndim < 3 or frame.shape[2] < 3:
            return False, (x, y), (0, 0, 0), (0, 0, 0)

        bgr = tuple(int(value) for value in frame[y, x, :3])
        hsv_pixel = cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0, 0]
        hsv = tuple(int(value) for value in hsv_pixel)
        hue, saturation, value = hsv
        is_red = (
            (hue <= RED_DOT_HUE_WRAPAROUND_MAXIMUM or hue >= RED_DOT_HUE_WRAPAROUND_MINIMUM)
            and saturation >= RED_DOT_SATURATION_MINIMUM
            and value >= RED_DOT_VALUE_MINIMUM
        )
        return is_red, (x, y), bgr, hsv

    def _quick_hunt_menu_shown(self, timeout: float) -> bool:
        text, _box = self._quick_hunt_wait_ocr(
            [r"狩猎场"],
            None,
            timeout,
            name="快速狩猎菜单确认",
        )
        if not text:
            return False
        self._status_set("快速狩猎入口", "已进入")
        self._status_set("快速狩猎菜单", "狩猎场")
        return True

    def _quick_hunt_open_menu(self) -> str:
        self._status_set("快速狩猎当前阶段", "确认首页并打开狩猎菜单")
        if not self._wait_for_quick_hunt_home():
            self._status_set("快速狩猎入口", "未确认首页")
            return "failed"

        self._status_set("快速狩猎入口", "首页已确认")
        confirm_timeout = max(3.0, self._quick_hunt_ui_timeout() / 2.0)
        for attempt in range(1, 4):
            clicked_by_ocr = self._quick_hunt_click_ocr(
                [r"^快速狩猎$"],
                None,
                2.0,
                name="主页快速狩猎入口",
            )
            if clicked_by_ocr:
                self._status_set("快速狩猎入口", "已点击 OCR 文字框中心")
            else:
                self.operate_click(*QUICK_HUNT_ENTRY_POINT, after_sleep=1.0)
                self._status_set("快速狩猎入口", "OCR 未命中，已点击固定入口中心")

            # User requirement: external coordinates must not be inferred or converted.
            # The menu is confirmed by full-frame OCR unless an ok-bd2 ROI is supplied.
            if self._quick_hunt_menu_shown(confirm_timeout):
                return "opened"
            if attempt >= 3:
                break
            # 入口点击可能被主页动画吞掉（RPT-20260901-233554 23:32 一轮
            # 单击定胜负直接失败）；仍在主页才补点，避免在未知页面盲点。
            home_ok, *_rest = self._quick_hunt_home_signals(self.capture_frame())
            if not home_ok:
                # Neither 主页 nor the menu: most likely still loading (YES-BD2
                # #8: 「画面还在转圈卡顿」).  Wait for the menu, press nothing.
                self.log_info("快速狩猎：点了入口后画面还没出来，可能还在加载，再等一会。")
                if self._quick_hunt_menu_shown(self._quick_hunt_ui_timeout()):
                    return "opened"
                break
            self.log_info(f"快速狩猎：第{attempt}次点击入口后未确认狩猎菜单，重试。")

        self._status_set("快速狩猎入口", "点击后未确认菜单")
        return "failed"

    def _quick_hunt_run_rice_scheduler(self) -> bool:
        """Run hunting ground first, then an optional MAX adventure route."""

        self._status_set("快速狩猎当前阶段", "米饭调度")
        if self._quick_hunt_resource_empty("米饭"):
            self._status_set("快速狩猎米饭", "0，跳过")
            return True

        hunting_mode, adventure_mode = self._quick_hunt_count_modes()

        self.log_info("快速狩猎：狩猎场使用游戏当前默认关卡，不切换章节。")
        result = self._quick_hunt_execute_current_map(hunting_mode, "狩猎场")
        if result == "failed":
            return False
        if result == "depleted" or self._quick_hunt_resource_empty("米饭"):
            self._status_set("快速狩猎米饭", "已耗尽")
            return True

        if adventure_mode is not None:
            adventure_selected = self._quick_hunt_select_adventure_route()
            if adventure_selected:
                expected_map_pattern = QUICK_HUNT_ADVENTURE_MAP_PATTERNS[
                    adventure_selected
                ]
                result = self._quick_hunt_execute_current_map(
                    adventure_mode,
                    "冒险航线",
                    expected_map_pattern=expected_map_pattern,
                )
                if result == "wrong_map":
                    self.log_info(
                        f"快速狩猎：{adventure_selected}航线首次选择未生效，"
                        "重新 OCR 选择一次。"
                    )
                    if not self._quick_hunt_click_adventure(adventure_selected):
                        return False
                    result = self._quick_hunt_execute_current_map(
                        adventure_mode,
                        "冒险航线重试",
                        expected_map_pattern=expected_map_pattern,
                    )
                if result in {"failed", "wrong_map"}:
                    return False
                if result == "depleted" or self._quick_hunt_resource_empty("米饭"):
                    self._status_set("快速狩猎米饭", "已耗尽")
                    return True

        if adventure_mode is None:
            self.log_info("快速狩猎：狩猎场使用 MAX，按配置跳过金币和经验航线。")
        self._status_set("快速狩猎米饭", "调度结束")
        return True

    def _quick_hunt_run_crystal_cave(self) -> bool:
        self._status_set("快速狩猎当前阶段", "圣石洞穴")
        if not self._quick_hunt_enter_crystal_cave():
            return False
        if self._quick_hunt_resource_empty("火把"):
            self._status_set("快速狩猎火把", "0，跳过")
            return True

        stone_counts = self._quick_hunt_stone_counts()
        if stone_counts is None:
            return False
        element = min(QUICK_HUNT_STONE_ELEMENTS, key=stone_counts.__getitem__)
        self._status_set(
            "快速狩猎圣石数量",
            "、".join(f"{name}={stone_counts[name]}" for name in QUICK_HUNT_STONE_ELEMENTS)
            + f"；选择={element}",
        )
        clicked = self._quick_hunt_click_ocr(
            [rf"{re.escape(element)}.?之?.?洞穴"],
            QUICK_HUNT_STONE_LIST_ROI,
            self._quick_hunt_ui_timeout(),
            name=f"选择{element}属性洞穴",
        )
        if not clicked:
            return False
        result = self._quick_hunt_execute_current_map("MAX", f"{element}属性圣石")
        if result == "failed":
            return False
        self._status_set("快速狩猎火把", "已耗尽" if result == "depleted" else "完成")
        return True

    def _quick_hunt_enter_crystal_cave(self, attempts: int = 3) -> bool:
        """Open the crystal cave panel and confirm the attribute cave list.

        结算"点击画面即可返回"的关闭动画可能吞掉紧随其后的点击，单次盲点
        定胜负会让整个快速狩猎确定性失败；这里优先 OCR 识别左列"圣石洞穴"
        文字框点击其中心，识别不到再回退固定参考点，确认失败在有限次数内重试。
        The fixed point is pressed only while the hunt menu is read; a screen
        that is not the menu is not pressed at all, and what it showed goes
        in the log for the 问题摘要.
        """
        confirm_timeout = max(3.0, self._quick_hunt_ui_timeout() / 2.0)
        confirm_patterns = [r"[火水风光暗].?洞穴"]
        for attempt in range(1, max(1, attempts) + 1):
            if not self._quick_hunt_press_crystal_entry():
                break
            text, _box = self._quick_hunt_wait_ocr(
                confirm_patterns,
                QUICK_HUNT_CRYSTAL_TITLE_ROI,
                confirm_timeout,
                name="圣石洞穴确认",
            )
            if text:
                return True
            self.log_info(
                f"快速狩猎：圣石洞穴第{attempt}/{max(1, attempts)}次点击未确认"
                "属性洞穴列表"
                + ("，重试。" if attempt < max(1, attempts) else "。")
            )
        self.log_info("快速狩猎：点击圣石洞穴后未确认属性洞穴列表。")
        self._quick_hunt_log_screen("圣石洞穴没进去")
        self._save_flow_diagnostic("quick_hunt_crystal_entry_failed")
        return False

    def _quick_hunt_press_crystal_entry(self) -> bool:
        """Press the left column's 圣石洞穴; False when nothing was pressed."""
        for look in range(QUICK_HUNT_CRYSTAL_ENTRY_LOOKS):
            if look:
                self._quick_hunt_clear_crystal_cover()
            if self._quick_hunt_click_ocr(
                [QUICK_HUNT_CRYSTAL_ENTRY_PATTERN],
                QUICK_HUNT_CRYSTAL_CLICK_ROI,
                2.0,
                name="圣石洞穴入口",
            ):
                return True
            # RPT-20260902-225925：实机条带 OCR 连续 20 秒全空，但 6 秒前
            # 整屏 OCR 能读到"圣石洞穴"，该客户端入口可能偏移到条带外；
            # 条带未命中先整屏 OCR 兜底（"圣石洞"三字前缀在狩猎菜单内唯一）。
            if self._quick_hunt_click_ocr(
                [QUICK_HUNT_CRYSTAL_ENTRY_PATTERN],
                None,
                2.0,
                name="圣石洞穴入口整屏",
            ):
                return True
        frame = self.capture_frame()
        seen = self._quick_hunt_ocr_text(
            frame,
            QUICK_HUNT_CRYSTAL_CLICK_ROI,
            name="圣石洞穴入口区域",
        )
        self._status_set("圣石洞穴入口区域 OCR", seen or "-")
        menu = re.compile(QUICK_HUNT_MENU_PATTERN)
        if not menu.search(self._normalize_text(seen)):
            whole = self._quick_hunt_ocr_text(frame, None, name="圣石洞穴入口整屏文字")
            if not menu.search(self._normalize_text(whole)):
                self.log_info("快速狩猎：画面上没有狩猎菜单，没按圣石洞穴。")
                return False
        self._click_reference(*QUICK_HUNT_CRYSTAL_POINT, after_sleep=0.8)
        return True

    def _quick_hunt_clear_crystal_cover(self) -> None:
        """Put away what was read over the hunt menu (reward page, dialog, popup)."""
        stage = "圣石洞穴"
        if self._quick_hunt_reward_shown(stage):
            self.log_info("快速狩猎：结算画面还在，先点掉再找圣石洞穴。")
            self._quick_hunt_close_reward(stage)
            return
        if self._quick_hunt_dialog_visible(stage):
            self.log_info("快速狩猎：快速狩猎视窗还开着，先取消再找圣石洞穴。")
            self._quick_hunt_cancel_dialog(stage)
            return
        popup = self._quick_hunt_ocr_text(
            self.capture_frame(), QUICK_HUNT_DIALOG_ROI, name=f"{stage}-提示"
        )
        if any(word in self._normalize_text(popup) for word in ("不足", "无法", "耗尽")):
            # The same tap that puts the shortage popup away after a hunt.
            self.log_info("快速狩猎：资源不足提示还在，先点掉再找圣石洞穴。")
            self._click_mf_reference(1, 1, after_sleep=0.5)

    def _quick_hunt_log_screen(self, what: str) -> None:
        """One log line with the words on screen, so a 问题摘要 shows where it was."""
        text = self._quick_hunt_ocr_text(self.capture_frame(), None, name="快速狩猎当时画面")
        words = " ".join(str(text or "").split())
        self.log_info(f"快速狩猎：{what}，当时画面读到「{words[:50] or '没读到字'}」。")

    def _quick_hunt_select_adventure_route(self) -> str | None:
        preferred = str(self.config.get("快速狩猎资源倾向", "金币"))
        if preferred not in QUICK_HUNT_ADVENTURE_LABEL_PATTERNS:
            self.log_info(f"快速狩猎：不支持的冒险航线资源：{preferred}")
            return None
        strategy = str(self.config.get("快速狩猎双倍策略", "优先双倍"))
        if strategy == "忽视双倍":
            return "金币" if self._quick_hunt_click_adventure("金币") else None
        states = self._quick_hunt_double_states()
        if not any(states.values()):
            # The route list may still be drawing after the reward page
            # closed: one miss would skip the route without an error.
            self.sleep(0.8)
            states = self._quick_hunt_double_states()
        if strategy == "优先双倍":
            selected = "金币" if states["金币"] else "经验" if states["经验"] else None
            if selected is None:
                self.log_info("快速狩猎：金币和经验均未识别到双倍，跳过冒险航线。")
                return None
            return selected if self._quick_hunt_click_adventure(selected) else None
        if strategy == "强制双倍":
            alternate = "经验" if preferred == "金币" else "金币"
            for resource in (preferred, alternate):
                if states[resource]:
                    return resource if self._quick_hunt_click_adventure(resource) else None
            self.log_info("快速狩猎：首选和备选资源均未识别到双倍，跳过冒险航线。")
            return None
        self.log_info(f"快速狩猎：不支持的双倍策略：{strategy}")
        return None

    def _quick_hunt_click_adventure(self, resource: str) -> bool:
        pattern = QUICK_HUNT_ADVENTURE_LABEL_PATTERNS.get(resource)
        if pattern is None:
            return False
        return self._quick_hunt_click_ocr(
            [pattern],
            QUICK_HUNT_ADVENTURE_LIST_ROI,
            self._quick_hunt_ui_timeout(),
            name=f"选择{resource}航线",
        )

    def _quick_hunt_double_states(self, frame=None) -> dict[str, bool]:
        vision = self._quick_vision()
        if frame is None:
            frame = self.capture_frame()
        spec = self._quick_spec(QUICK_HUNT_DOUBLE_TEMPLATE)
        matches = vision.match_all(
            frame,
            spec,
            minimum_score=vision.threshold_for(spec),
        )
        split_y = frame.shape[0] * (
            QUICK_HUNT_DOUBLE_ROI[1] + QUICK_HUNT_DOUBLE_ROI[3]
        ) / 2
        states = {"金币": False, "经验": False}
        details = []
        for match in matches:
            resource = "金币" if match.center[1] < split_y else "经验"
            states[resource] = True
            details.append(
                f"{resource}@{match.center}={match.score:.3f}/{match.pixel_score:.3f}"
            )
        self._status_set(
            "快速狩猎双倍识别",
            f"金币={'双倍' if states['金币'] else '非双倍'}，"
            f"经验/史莱姆={'双倍' if states['经验'] else '非双倍'}；"
            + ("；".join(details) or "未命中Double.png"),
        )
        return states

    def _quick_hunt_execute_current_map(
        self,
        count_mode: str,
        stage: str,
        expected_map_pattern: str | None = None,
    ) -> str:
        self._status_set("快速狩猎当前阶段", stage)
        if not self._quick_hunt_open_dialog(stage):
            return "failed"
        if expected_map_pattern is not None:
            map_state, map_text, actual_map = self._quick_hunt_wait_map_confirmation(
                expected_map_pattern,
                name=f"{stage}-地图确认",
            )
            if map_state != "matched":
                self.log_info(
                    f"快速狩猎：{stage}未确认目标地图 {expected_map_pattern}，"
                    f"当前={actual_map or map_text or '-'}，取消本次快速狩猎。"
                )
                cancelled = self._quick_hunt_click_ocr(
                    [r"取消"],
                    QUICK_HUNT_COUNT_ROI,
                    min(2.0, self._quick_hunt_ui_timeout()),
                    name=f"{stage}-取消错误地图",
                )
                return "wrong_map" if cancelled else "failed"
        if count_mode not in {"MIN", "MAX"}:
            self.log_info(f"快速狩猎：不支持的次数模式：{count_mode}")
            return "failed"
        if not self._quick_hunt_ensure_free_only(stage):
            self._quick_hunt_cancel_dialog(stage)
            return "failed"
        if not self._quick_hunt_click_ocr(
            [rf"^{count_mode}$"],
            QUICK_HUNT_COUNT_ROI,
            self._quick_hunt_ui_timeout(),
            name=f"{stage}-{count_mode}",
        ):
            return "failed"
        if not self._quick_hunt_cost_within_free(stage):
            self._quick_hunt_cancel_dialog(stage)
            return "failed"
        if not self._quick_hunt_click_ocr(
            [r"狩猎"],
            QUICK_HUNT_START_ROI,
            self._quick_hunt_ui_timeout(),
            name=f"{stage}-开始狩猎",
            require_enabled=True,
        ):
            return "failed"
        return self._quick_hunt_wait_result(stage)

    def _quick_hunt_open_dialog(self, stage: str) -> bool:
        """Press 快速狩猎 and go on only once its dialog is on screen.

        A player's run (v0.1.17, 1080p) pressed the button, found neither
        「仅使用免费」 nor 「取消」 and stopped: the press had not opened the
        dialog.  Opening it spends nothing, so a lost press is pressed once
        more while the button is still shown.
        """
        button = f"{stage}-快速狩猎按钮"
        self._quick_hunt_dialog_last_read = None
        if not wait_for(
            lambda: self._quick_hunt_button_ready(stage),
            self._quick_hunt_ui_timeout(),
            sleep=self.sleep,
            poll=0.4,
        ):
            self.log_info(f"快速狩猎：未找到可点击 OCR 目标：{button}")
            return False
        outcome = self.press_and_confirm(
            f"快速狩猎：{stage}打开快速狩猎视窗",
            lambda: self._quick_hunt_click_ocr(
                [r"快速狩猎"],
                QUICK_HUNT_BUTTON_ROI,
                2.0,
                name=button,
                require_enabled=True,
            ),
            lambda: self._quick_hunt_dialog_visible(stage),
            still_before=lambda: self._quick_hunt_button_ready(stage),
            timeout=QUICK_HUNT_DIALOG_DRAW_SECONDS,
        )
        if not outcome:
            self.log_warning(
                f"快速狩猎：{stage}按了「快速狩猎」{outcome.presses}次都没看到快速狩猎视窗，"
                f"这一项先不做。{self._quick_hunt_dialog_seen()}"
            )
        return bool(outcome)

    def _quick_hunt_button_ready(self, stage: str) -> bool:
        """One look: the 快速狩猎 button is shown and lit (no dialog over it)."""

        frame = self.capture_frame()
        boxes = self._quick_vision().ocr_boxes(
            frame, f"{stage}-快速狩猎按钮", relative_roi=QUICK_HUNT_BUTTON_ROI
        )
        return any(
            "快速狩猎" in self._normalize_text(getattr(box, "name", ""))
            and self._quick_hunt_box_enabled(frame, box)
            for box in boxes
        )

    def _quick_hunt_dialog_visible(self, stage: str) -> bool:
        """One look: the quick-hunt dialog shows 仅使用免费 or 取消/MIN/MAX."""

        frame = self.capture_frame()
        label = self._quick_hunt_ocr_text(
            frame, QUICK_HUNT_FREE_LABEL_ROI, name=f"{stage}-视窗确认-仅使用免费"
        )
        if "仅使用免费" in self._normalize_text(label):
            return True
        buttons = self._quick_hunt_ocr_text(
            frame, QUICK_HUNT_COUNT_ROI, name=f"{stage}-视窗确认-次数"
        )
        # Kept for the failure line, so a player's log says what was shown.
        self._quick_hunt_dialog_last_read = (frame, label, buttons)
        return bool(QUICK_HUNT_DIALOG_BUTTONS.search(self._normalize_text(buttons)))

    def _quick_hunt_dialog_seen(self) -> str:
        """What the last dialog check read, for the failure line in the log."""

        last = getattr(self, "_quick_hunt_dialog_last_read", None)
        if last is None:
            return "当时画面没读到字。"
        frame, label, buttons = last
        place = self._quick_hunt_current_map_context(frame)
        return (
            f"当时画面：开关处读到「{label or '-'}」，按钮处读到「{buttons or '-'}」，"
            f"所在地图「{place or '-'}」。"
        )

    def _quick_hunt_cancel_dialog(self, stage: str) -> None:
        self._quick_hunt_click_ocr(
            [r"取消"],
            QUICK_HUNT_COUNT_ROI,
            min(2.0, self._quick_hunt_ui_timeout()),
            name=f"{stage}-取消",
        )

    def _quick_hunt_free_switch_ratio(self) -> float:
        frame = self.capture_frame()
        height, width = frame.shape[:2]
        x, y, w, h = QUICK_HUNT_FREE_SWITCH_BOX
        crop = frame[
            round(y / 1080 * height) : round((y + h) / 1080 * height),
            round(x / 1920 * width) : round((x + w) / 1920 * width),
        ]
        if crop.size == 0 or crop.ndim != 3:
            return 0.0
        ratio = switch_yellow_ratio(crop)
        self._status_set("快速狩猎免费开关", f"黄色占比 {ratio:.3f}")
        return ratio

    def _quick_hunt_ensure_free_only(self, stage: str) -> bool:
        """The dialog shows 仅使用免费… and its switch is on (turned on if needed)."""

        # The dialog may still be opening right after the 快速狩猎 click.
        end_at = monotonic() + QUICK_HUNT_DIALOG_DRAW_SECONDS
        while True:
            label = self._quick_hunt_ocr_text(
                self.capture_frame(), QUICK_HUNT_FREE_LABEL_ROI, name=f"{stage}-仅使用免费"
            )
            if "仅使用免费" in self._normalize_text(label) or monotonic() >= end_at:
                break
            self.sleep(0.4)
        if "仅使用免费" not in self._normalize_text(label):
            self.log_warning(
                f"快速狩猎：{stage}未找到「仅使用免费」开关，取消以免动用存量。"
                f"开关处读到「{label or '-'}」。"
            )
            return False
        # One press at most: a second one would turn off a switch that was
        # on but not recognised as on (review #28).
        if ensure_free_switch_on(
            f"快速狩猎：{stage}「仅使用免费」",
            self._quick_hunt_free_switch_ratio,
            lambda: self._click_reference(*QUICK_HUNT_FREE_SWITCH_POINT, after_sleep=0.5),
            on_above=QUICK_HUNT_FREE_SWITCH_MIN_RATIO,
            settle=QUICK_HUNT_FREE_SWITCH_SETTLE_SECONDS,
            sleep=self.sleep,
            log=self.log_info,
        ):
            return True
        self.log_warning(f"快速狩猎：{stage}无法确认「仅使用免费」已开启，取消。")
        return False

    def _quick_hunt_cost_within_free(self, stage: str) -> bool:
        """The start button's cost does not exceed the free pool (a in a/b)."""

        # The cost follows the MIN/MAX click a moment later: read until two
        # looks agree, so neither an unread nor a stale pre-MAX cost decides.
        end_at = monotonic() + QUICK_HUNT_DIALOG_DRAW_SECONDS
        previous = None
        while True:
            frame = self.capture_frame()
            # Small digits: at native 1080p "84/90" read as "84" (live
            # 2026-09-28), so these crops are enlarged to 4K-equivalent size.
            cost_text = self._quick_hunt_ocr_text(
                frame, QUICK_HUNT_START_ROI, name=f"{stage}-消耗", small_text=True
            )
            pool_text = self._quick_hunt_ocr_text(
                frame, QUICK_HUNT_RESOURCE_ROI, name=f"{stage}-免费量", small_text=True
            )
            cost = quick_hunt_cost(cost_text)
            free = quick_hunt_free_pool(pool_text)
            current = (cost, free)
            if (cost is not None and free is not None and current == previous) or (
                monotonic() >= end_at
            ):
                break
            previous = current
            self.sleep(0.4)
        self._status_set("快速狩猎消耗核对", f"消耗 {cost} / 免费 {free}")
        if cost is None or free is None or cost > free:
            self.log_warning(
                f"快速狩猎：{stage}消耗 {cost} 超过或无法核对免费数量 {free}，取消。"
            )
            return False
        return True

    def _quick_hunt_wait_result(self, stage: str) -> str:
        end_at = monotonic() + float(self.config.get("快速狩猎结算等待秒数", 15.0))
        while monotonic() <= end_at:
            frame = self.capture_frame()
            reward_text = self._quick_hunt_ocr_text(
                frame,
                QUICK_HUNT_REWARD_ROI,
                name=f"{stage}-奖励",
            )
            if self._quick_hunt_reward_text(reward_text):
                return "done" if self._quick_hunt_close_reward(stage) else "failed"

            dialog_text = self._quick_hunt_ocr_text(
                frame,
                QUICK_HUNT_DIALOG_ROI,
                name=f"{stage}-异常",
            )
            if any(
                keyword in self._normalize_text(dialog_text)
                for keyword in ("不足", "无法", "耗尽")
            ):
                self._click_mf_reference(1, 1, after_sleep=0.5)
                return "depleted"
            self.sleep(0.5)
        self.log_info(f"快速狩猎：{stage}等待结算超时。")
        return "failed"

    def _quick_hunt_reward_text(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        return ("点击" in normalized and "返回" in normalized) or (
            "画面" in normalized and "即可" in normalized
        )

    def _quick_hunt_reward_shown(self, stage: str) -> bool:
        return self._quick_hunt_reward_text(
            self._quick_hunt_ocr_text(
                self.capture_frame(), QUICK_HUNT_REWARD_ROI, name=f"{stage}-奖励"
            )
        )

    def _quick_hunt_close_reward(self, stage: str) -> bool:
        """Tap the reward page away; done only once it is gone on two looks.

        A lost tap left the page over the route list, where the double check
        then found nothing and skipped the route as if all were done.
        """

        def gone() -> bool:
            if self._quick_hunt_reward_shown(stage):
                return False
            self.sleep(0.3)
            return not self._quick_hunt_reward_shown(stage)

        if self.press_and_confirm(
            f"快速狩猎：{stage}结算「点击画面即可返回」",
            lambda: self._click_mf_reference(1, 1, after_sleep=0.8),
            gone,
            still_before=lambda: self._quick_hunt_reward_shown(stage),
            timeout=QUICK_HUNT_REWARD_GONE_SECONDS,
        ):
            return True
        self.log_warning(f"快速狩猎：{stage}结算画面点不掉，停止，下次再跑。")
        return False

    def _quick_hunt_stone_counts(self) -> dict[str, int] | None:
        counts = self._quick_hunt_wait_stone_counts()
        unfolded = False
        if counts is None and self._quick_hunt_unfold_stone_panel():
            unfolded = True
            counts = self._quick_hunt_wait_stone_counts()
            if counts is not None:
                self.log_info("快速狩猎：右上的圣石栏原本收起来了，已点开并读到数量。")
        if counts is None:
            seen = " / ".join(self._quick_hunt_stone_seen) or "没读到数字"
            if unfolded:
                why = "右上的圣石栏原本收起来了，点开后还是没读到。"
            elif not self._quick_hunt_stone_seen:
                why = "右上一个数字都没有，圣石栏可能收起来了。"
            else:
                why = ""
            self.log_info(
                "快速狩猎：圣石数量区域未从上到下识别出火、水、风、光、暗5个数字，"
                f"读到：{seen}。{why}"
            )
            self._save_flow_diagnostic("quick_hunt_stone_count_failed")
        return counts

    def _quick_hunt_wait_stone_counts(self) -> dict[str, int] | None:
        # The counts sit apart from the cave title that was waited for.
        end_at = monotonic() + QUICK_HUNT_DIALOG_DRAW_SECONDS
        self._quick_hunt_stone_seen = []
        while True:
            counts = self._quick_hunt_read_stone_counts()
            if counts is not None or monotonic() >= end_at:
                return counts
            self.sleep(0.5)

    def _quick_hunt_unfold_stone_panel(self) -> bool:
        """Press the folded panel's ∨ once, when two looks both find it."""
        first = quick_hunt_fold_button(self.capture_frame())
        if first is None:
            return False
        self.sleep(0.3)
        frame = self.capture_frame()
        second = quick_hunt_fold_button(frame)
        height, width = frame.shape[:2]
        near = max(3, round(4 * height / REFERENCE_HEIGHT))
        if second is None or max(abs(second[0] - first[0]), abs(second[1] - first[1])) > near:
            return False
        point = (
            round(second[0] * REFERENCE_WIDTH / width),
            round(second[1] * REFERENCE_HEIGHT / height),
        )

        def counts_show() -> bool:
            # Confirmed by the counts, not by the ∨ going: pressed again on an
            # open panel it could fold it away.
            return self._quick_hunt_read_stone_counts() is not None or bool(
                self._quick_hunt_stone_seen
            )

        self.log_info("快速狩猎：右上的圣石栏收起来了，点开它。")
        self.press_and_confirm(
            "快速狩猎：点开右上的圣石栏",
            lambda: self._click_reference(*point, after_sleep=0.8),
            counts_show,
            still_before=lambda: (
                quick_hunt_fold_button(self.capture_frame()) is not None
                and not self._quick_hunt_stone_seen
            ),
            timeout=2.0,
        )
        return True

    def _quick_hunt_read_stone_counts(self) -> dict[str, int] | None:
        """The five counts top to bottom, read as shown, then enlarged.

        A player's 1080p run (2026-10-10) stopped here.  The counts are small
        digits like the torch counter, which is read as if the frame were 4K
        for that reason; a count split into two boxes ("1," "250") is one row.
        """
        frame = self.capture_frame()
        scale = max(1.0, SMALL_TEXT_HEIGHT / max(1, frame.shape[0]))
        rows: list[tuple[float, str]] = []
        for enlarged in (False, True):
            if enlarged and scale == 1.0:
                break
            rows = self._quick_hunt_stone_rows(frame, scale if enlarged else None)
            if len(rows) == len(QUICK_HUNT_STONE_ELEMENTS):
                break
        values = [quick_hunt_stone_value(text) for _y, text in rows]
        self._quick_hunt_stone_seen = [text for _y, text in rows]
        if len(rows) != len(QUICK_HUNT_STONE_ELEMENTS) or None in values:
            self._status_set(
                "快速狩猎圣石数量",
                f"需要5个数字，实际识别{len(rows)}个",
            )
            return None
        return dict(zip(QUICK_HUNT_STONE_ELEMENTS, values))

    def _quick_hunt_stone_rows(self, frame, ocr_scale: float | None) -> list[tuple[float, str]]:
        """Digit boxes of the count column joined into rows, top to bottom."""
        extra = {} if ocr_scale is None else {"ocr_scale": ocr_scale}
        boxes = self._quick_vision().ocr_boxes(
            frame,
            "圣石属性数量",
            relative_roi=QUICK_HUNT_STONE_COUNT_ROI,
            **extra,
        )
        found: list[tuple[float, float, float, str]] = []
        for box in boxes:
            text = str(getattr(box, "name", ""))
            if not re.search(r"\d", text):
                continue
            center = self._quick_hunt_box_center(box)
            if center is None:
                continue
            height = float(getattr(box, "height", 0) or 0)
            found.append((center[1], center[0], height, text))
        found.sort()
        rows: list[list[tuple[float, float, float, str]]] = []
        for item in found:
            if rows:
                last = rows[-1]
                tall = max(entry[2] for entry in last + [item]) or 1.0
                if abs(item[0] - last[0][0]) < tall * 0.6:
                    last.append(item)
                    continue
            rows.append([item])
        return [
            (row[0][0], "".join(text for _y, _x, _h, text in sorted(row, key=lambda e: e[1])))
            for row in rows
        ]

    def _quick_hunt_resource_empty(self, resource: str) -> bool:
        # 单帧 OCR 曾把 30/90 读成 0/90（24 读成 4），误判已耗尽、跳过狩猎还报成功；
        # 必须隔一会儿再读一帧也判为 0 才算耗尽，不一致按未耗尽继续（消耗前另有免费数量核对）。
        if not self._quick_hunt_resource_empty_once(resource):
            return False
        self.sleep(0.6)
        if self._quick_hunt_resource_empty_once(resource):
            return True
        self.log_info(f"快速狩猎：{resource}两次读数不一致，不按耗尽处理。")
        return False

    def _quick_hunt_resource_empty_once(self, resource: str) -> bool:
        frame = self.capture_frame()
        text = self._quick_hunt_ocr_text(
            frame, QUICK_HUNT_RESOURCE_ROI, name=f"{resource}数量", small_text=True
        )
        normalized = self._normalize_text(text).replace("：", ":")
        expected_capacity = QUICK_HUNT_RESOURCE_CAPACITIES.get(resource)
        if expected_capacity is None:
            pattern = r"(?:^|\D)0[/：:|\-~][1-9]\d*(?:\D|$)"
        else:
            pattern = (
                rf"(?:^|\D)0[/：:|\-~]{expected_capacity}"
                rf"(?:\D|$)"
            )
        empty = re.search(pattern, normalized) is not None
        self._status_set(f"快速狩猎{resource}", text or "未识别")
        return empty

    def _quick_hunt_count_modes(self) -> tuple[str, str | None]:
        allocation = str(
            self.config.get("快速狩猎米饭分配", "狩猎场x1 / 双倍图MAX")
        )
        if allocation in {"狩猎场MAX / 跳过冒险航线", "狩猎场MAX / 双倍图x1"}:
            return "MAX", None
        return "MIN", "MAX"

    def _quick_hunt_wait_ocr(
        self,
        patterns: list[str],
        roi: tuple[float, float, float, float] | None,
        timeout: float,
        name: str,
    ) -> tuple[str, object | None]:
        compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            boxes = self._quick_vision().ocr_boxes(frame, name, relative_roi=roi)
            text = " ".join(str(getattr(box, "name", "")) for box in boxes)
            last_text = text
            self._status_set(f"{name} OCR", text or "-")
            normalized = self._normalize_text(text)
            for box in boxes:
                value = self._normalize_text(getattr(box, "name", ""))
                if any(pattern.search(value) for pattern in compiled):
                    return text, box
            if any(pattern.search(normalized) for pattern in compiled):
                return text, None
            self.sleep(0.4)
        self.log_info(
            f"快速狩猎：{name} 超时，最后一次 OCR={last_text or '-'}。"
        )
        return "", None

    def _quick_hunt_wait_map_confirmation(
        self,
        expected_pattern: str,
        name: str,
    ) -> tuple[str, str, str | None]:
        expected = re.compile(expected_pattern, re.IGNORECASE)
        end_at = monotonic() + self._quick_hunt_ui_timeout()
        last_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            boxes = self._quick_vision().ocr_boxes(
                frame,
                name,
                relative_roi=QUICK_HUNT_COUNT_ROI,
            )
            text = " ".join(str(getattr(box, "name", "")) for box in boxes)
            last_text = text
            self._status_set(f"{name} OCR", text or "-")
            normalized = self._normalize_text(text)
            if expected.search(normalized):
                return "matched", text, None
            actual_map = next(
                (
                    label
                    for label, pattern in QUICK_HUNT_EXECUTION_MAP_PATTERNS
                    if pattern.search(normalized)
                ),
                None,
            )
            if actual_map is not None:
                self.log_info(
                    f"快速狩猎：{name}明确识别到错误地图 {actual_map}。"
                )
                return "wrong", text, actual_map
            self.sleep(0.4)
        self.log_info(
            f"快速狩猎：{name}超时，最后一次 OCR={last_text or '-'}。"
        )
        return "timeout", last_text, None

    def _quick_hunt_click_ocr(
        self,
        patterns: list[str],
        roi: tuple[float, float, float, float] | None,
        timeout: float,
        name: str,
        require_enabled: bool = False,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        vision = self._quick_vision()
        while monotonic() <= end_at:
            frame = self.capture_frame()
            for box in vision.ocr_boxes(frame, name, relative_roi=roi):
                value = self._normalize_text(getattr(box, "name", ""))
                if not any(pattern.search(value) for pattern in compiled):
                    continue
                if require_enabled and not self._quick_hunt_box_enabled(frame, box):
                    continue
                point = self._quick_hunt_box_center(box)
                if point is None:
                    continue
                vision.click_client(point, frame.shape, after_sleep=0.8)
                return True
            self.sleep(0.4)
        self.log_info(f"快速狩猎：未找到可点击 OCR 目标：{name}")
        return False

    def _quick_hunt_ocr_text(
        self,
        frame,
        roi: tuple[float, float, float, float],
        name: str,
        small_text: bool = False,
    ) -> str:
        scale = max(1.0, SMALL_TEXT_HEIGHT / max(1, frame.shape[0])) if small_text else 1.0
        return self._quick_vision().ocr_text(frame, name, relative_roi=roi, ocr_scale=scale)

    @staticmethod
    def _quick_hunt_box_center(box) -> tuple[int, int] | None:
        values = tuple(getattr(box, key, None) for key in ("x", "y", "width", "height"))
        if any(value is None for value in values):
            return None
        x, y, width, height = (float(value) for value in values)
        return round(x + width / 2), round(y + height / 2)

    @staticmethod
    def _quick_hunt_box_enabled(frame, box) -> bool:
        values = tuple(getattr(box, key, None) for key in ("x", "y", "width", "height"))
        if any(value is None for value in values):
            return False
        x, y, width, height = (round(float(value)) for value in values)
        frame_height, frame_width = frame.shape[:2]
        left, top = max(0, x), max(0, y)
        right, bottom = min(frame_width, x + width), min(frame_height, y + height)
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            return False
        gray = TaskVisionMixin._to_gray(crop)
        bright_ratio = float(np.mean(gray >= BUTTON_ENABLED_BRIGHT_GRAY_MINIMUM))
        return bright_ratio >= BUTTON_ENABLED_BRIGHT_MIN_RATIO

    def _quick_hunt_return_home(self) -> bool:
        self._status_set("快速狩猎当前阶段", "返回主页")
        for _attempt in range(4):
            frame = self.capture_frame()
            self._status_set(
                "快速狩猎返回位置 OCR",
                self._quick_hunt_current_map_context(frame),
            )
            home_ok, left_hits, p95_brightness, gacha_text = self._quick_hunt_home_signals(frame)
            self._status_set(
                "快速狩猎首页按钮",
                f"左列关键词 {left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}",
            )
            self._status_set(
                "快速狩猎主页亮度",
                f"p95={p95_brightness:.0f}/{self._home_p95_threshold():.0f}",
            )
            self._status_set("快速狩猎主页抽抽乐 OCR", gacha_text or "-")
            if home_ok:
                return True
            if self.clear_temporary_home_announcement_if_needed(
                left_hits=left_hits,
                required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                brightness=p95_brightness,
                brightness_threshold=self._home_p95_threshold(),
                gacha_ocr_text=gacha_text,
                context="快速狩猎返回主页",
            ):
                self.sleep(0.35)
                continue
            self._click_reference(*QUICK_HUNT_RETURN_POINT, after_sleep=2.0)
        # A slow last transition: give home a few seconds before failing.
        end_at = monotonic() + QUICK_HUNT_HOME_LAST_WAIT_SECONDS
        while True:
            if self._quick_hunt_home_signals(self.capture_frame())[0]:
                return True
            if monotonic() >= end_at:
                return False
            self.sleep(0.5)

    def _quick_hunt_current_map_context(self, frame) -> str:
        boxes = self._quick_vision().ocr_boxes(
            frame,
            "快速狩猎返回位置",
            relative_roi=None,
        )
        matches: list[tuple[float, float, str]] = []
        for box in boxes:
            value = self._normalize_text(getattr(box, "name", ""))
            label = next(
                (
                    name
                    for name, pattern in QUICK_HUNT_RETURN_MAP_PATTERNS
                    if pattern.search(value)
                ),
                None,
            )
            if label is None:
                continue
            point = self._quick_hunt_box_center(box)
            if point is not None:
                matches.append((point[1], point[0], label))
        if not matches:
            return "-"
        _y, _x, label = min(matches)
        return label

    def _quick_spec(self, spec: TemplateSpec) -> TemplateSpec:
        return replace(
            spec,
            min_pixel_score=float(
                self.config.get("快速狩猎像素相似度阈值", spec.min_pixel_score or 0.72)
            ),
        )

    def _quick_hunt_ui_timeout(self) -> float:
        return float(self.config.get("快速狩猎界面等待秒数", 8.0))

    def _click_mf_reference(self, x: int, y: int, after_sleep: float = 0.0):
        self.operate_click(
            max(0.0, min(1.0, x / HD_720.width)),
            max(0.0, min(1.0, y / HD_720.height)),
            after_sleep=after_sleep,
        )
