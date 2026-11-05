import json
from pathlib import Path

from ok import Config
from ok.util.file import get_relative_path
from qfluentwidgets import FluentIcon

from src.tasks import problem_report
from src.tasks.BaseBD2Task import RECOGNITION_SETTLE_KEY, BaseBD2Task
from src.tasks.quick_hunt import (
    QUICK_HUNT_CHILD_CONFIG_KEYS,
    QUICK_HUNT_STONE_KEY,
    QuickHuntConfigMixin,
    QuickHuntFeatureMixin,
    quick_hunt_targets_from_legacy,
)

# Set when an update moved old settings over; src/ui/shell/new_setting_notice.py.
QUICK_HUNT_NOTICE_KEY = "_米饭目标新设定提示"
# Set once for players who had the tool before 圣石属性 could be picked.
STONE_NOTICE_KEY = "_圣石属性新设定提示"
from src.tasks.task_vision_mixin import TaskVisionMixin
from src.utils.home_confirmation import HOME_DIMMED_P95_THRESHOLD_DEFAULT


class QuickHuntTask(
    QuickHuntFeatureMixin,
    QuickHuntConfigMixin,
    TaskVisionMixin,
    BaseBD2Task,
):
    """Standalone quick-hunt task backed by the migrated quick-hunt flow."""
    recover_home_on_failure = True
    start_from_home = True
    frozen_retry = True

    include_quick_hunt_config = True
    ocr_threshold_key = "快速狩猎 OCR 阈值"
    status_keys = [
        "状态",
        "当前任务",
        "快速狩猎入口",
        "快速狩猎菜单",
        "快速狩猎米饭",
        "快速狩猎火把",
        "快速狩猎当前阶段",
        "快速狩猎结果",
        "快速狩猎测试状态",
        "快速狩猎首页按钮",
        "快速狩猎红点识别",
        "快速狩猎主页亮度",
        "快速狩猎主页抽抽乐 OCR",
        "快速狩猎返回位置 OCR",
        "快速狩猎菜单 OCR",
        "快速狩猎资源 OCR",
        "快速狩猎按钮 OCR",
        "快速狩猎次数 OCR",
        "快速狩猎开始 OCR",
        "快速狩猎奖励 OCR",
        "快速狩猎异常 OCR",
        "快速狩猎地图 OCR",
        "快速狩猎圣石 OCR",
        "快速狩猎圣石数量",
        "快速狩猎收起模板",
        "快速狩猎双倍识别",
        "快速狩猎模板阈值",
        "快速狩猎像素相似度阈值",
        "快速狩猎 OCR 阈值",
        "主页压暗阈值",
        "主页确认等待秒数",
        "匹配错误",
        "Log",
        "Warning",
        "Error",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_vision_state()
        self._install_quick_hunt_config()
        self.visible = True
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.name = "快速狩猎"
        self.description = "从首页进入快速狩猎，调度米饭并补充数量最少的属性圣石。"
        self.icon = FluentIcon.GAME

        self.default_config.pop("执行快速狩猎", None)
        self.config_description.pop("执行快速狩猎", None)
        self.config_type.pop("执行快速狩猎", None)

        ocr_threshold = self.default_config.pop("日常 OCR 阈值", 0.2)
        self.config_description.pop("日常 OCR 阈值", None)
        self.config_type.pop("日常 OCR 阈值", None)
        self.default_config["快速狩猎 OCR 阈值"] = ocr_threshold
        self.config_description["快速狩猎 OCR 阈值"] = (
            "快速狩猎界面文字识别的最低置信度。"
        )
        self.config_type["快速狩猎 OCR 阈值"] = {
            "min": 0.05,
            "max": 0.95,
            "step": 0.01,
        }
        self.default_config.update(
            {
                "主页压暗阈值": HOME_DIMMED_P95_THRESHOLD_DEFAULT,
                "主页确认等待秒数": 10.0,
            }
        )
        self.config_description.update(
            {
                "主页压暗阈值": "主页左列灰度 p99 低于该值视为被公告压暗（0-255）。",
                "主页确认等待秒数": "点击主页按钮后确认已返回主页的最长等待时间。",
            }
        )
        self.config_type.update(
            {
                "主页压暗阈值": {"min": 100.0, "max": 250.0, "step": 5.0},
                "主页确认等待秒数": {"min": 2.0, "max": 30.0, "step": 1.0},
            }
        )

        visible_keys = [RECOGNITION_SETTLE_KEY, *QUICK_HUNT_CHILD_CONFIG_KEYS]
        ocr_index = visible_keys.index("快速狩猎像素相似度阈值") + 1
        visible_keys.insert(ocr_index, "快速狩猎 OCR 阈值")
        visible_keys.extend(("主页压暗阈值", "主页确认等待秒数"))
        self.default_config[QUICK_HUNT_NOTICE_KEY] = False
        self.default_config[STONE_NOTICE_KEY] = False
        ordered_keys = tuple(visible_keys)
        self.default_config = {
            **{
                key: self.default_config[key]
                for key in ordered_keys
                if key in self.default_config
            },
            **{
                key: value
                for key, value in self.default_config.items()
                if key not in ordered_keys
            },
        }

    def load_config(self):
        # A saved 双倍策略/资源倾向 becomes the per-case targets once, so the
        # rice goes where it went before (ok-script drops the old keys).
        path = Path(get_relative_path(Config.config_folder, f"{self.__class__.__name__}.json"))
        try:
            legacy = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            legacy = {}
        migrated = quick_hunt_targets_from_legacy(legacy if isinstance(legacy, dict) else {})
        super().load_config()
        for key, value in migrated.items():
            self.config[key] = value
        if migrated:
            # The tool shows the new rows once at the next start (Leo 2026-10-12:
            # 「更新完第一次開工具 指引用戶去點這個設定」).
            self.config[QUICK_HUNT_NOTICE_KEY] = True
        if isinstance(legacy, dict) and legacy and QUICK_HUNT_STONE_KEY not in legacy:
            # Leo 2026-10-20: the torches still go to the least held element
            # (the default), and the tool shows the new row once.
            self.config[STONE_NOTICE_KEY] = True

    def run(self):
        test_action = getattr(self, "_quick_hunt_test_action", None)
        if test_action:
            return self._run_quick_hunt_test(test_action)

        self.info_set("状态", "快速狩猎启动。")
        success = self.run_quick_hunt()
        if not success and self._wait_for_quick_hunt_home():
            # Leo's rule: a step that stays stuck is tried once more from 主页,
            # then the run stops there (YES-BD2 #8, 2026-10-10: 「卡住了建议
            # 设置成退出主界面从头再来」).  What was already used up is skipped.
            self.log_info("快速狩猎：这次没做完，已回到主页，从头再试一次。")
            problem_report.forget_give_up()
            success = self.run_quick_hunt()
        self.info_set("状态", "快速狩猎完成。" if success else "快速狩猎失败。")
        if success:
            self.log_completion("快速狩猎：流程完成并返回主页。")
        return success
