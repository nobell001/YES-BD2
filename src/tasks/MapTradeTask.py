from __future__ import annotations

import json
from pathlib import Path

from ok import Config
from ok.task.exceptions import FinishedException, TaskDisabledException
from ok.util.file import get_relative_path
from qfluentwidgets import FluentIcon

from src.tasks import problem_report
from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.map_trade.models import OPTIONAL_COOKING_RECIPES
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.phase_ledger import ONLY_INCOMPLETE_KEY, PhaseLedger
from src.tasks.map_trade.progress import ProgressStore
from src.tasks.map_trade.sale_days import (
    bundled_sale_days,
    day_items,
    describe_entry,
    sale_day_key,
)
from src.tasks.map_trade.trader import Trader
from src.tasks.map_trade.trader_cooking import MAIN_COOKING_RECIPES
from src.tasks.map_trade.vision import Vision

LEGACY_VISION_THRESHOLD_KEY = "跑图跑商识图阈值"
LEGACY_OCR_THRESHOLD_KEY = "跑图跑商 OCR 阈值"
TRADE_VISION_THRESHOLD_KEY = "跑商识图阈值"
TRADE_OCR_THRESHOLD_KEY = "跑商 OCR 阈值"
MAP_VISION_THRESHOLD_KEY = "跑图识图阈值"
MAP_OCR_THRESHOLD_KEY = "跑图 OCR 阈值"

def _config_path(name: str) -> Path:
    return Path(get_relative_path(Config.config_folder, f"{name}.json"))


def _read_config(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _trade_section_migration_values(legacy: dict) -> dict[str, bool]:
    """Map the previous trade switches to the three top-level sections."""

    migrated: dict[str, bool] = {}
    trade_enabled = bool(legacy.get("执行跑商", True))
    if "买" not in legacy and ({"执行跑商", "低价进货"} & legacy.keys()):
        migrated["买"] = trade_enabled and bool(legacy.get("低价进货", True))
    if "卖" not in legacy and ({"执行跑商", "最高价出售"} & legacy.keys()):
        migrated["卖"] = trade_enabled and bool(legacy.get("最高价出售", True))
    return migrated


def _migrate_collection_config(legacy: dict) -> None:
    """Seed the new weekly card from the previous combined task config once."""

    target = _config_path("MapCollectionTask")
    if target.exists() or not legacy:
        return

    key_map = {
        "识别成功后等待秒数": "识别成功后等待秒数",
        "启用": "启用",
        "执行地图采集": "执行地图采集",
        LEGACY_VISION_THRESHOLD_KEY: MAP_VISION_THRESHOLD_KEY,
        LEGACY_OCR_THRESHOLD_KEY: MAP_OCR_THRESHOLD_KEY,
        "加载页面等待秒数": "加载页面等待秒数",
        "卡带单步重试次数": "卡带单步重试次数",
    }
    migrated = {
        new_key: legacy[old_key]
        for old_key, new_key in key_map.items()
        if old_key in legacy
    }
    if not migrated:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(migrated, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    temporary.replace(target)


class MapAutomationTaskBase(BaseBD2Task):
    """Shared mouse-only plumbing for the daily trade and weekly map cards."""

    vision_threshold_key = LEGACY_VISION_THRESHOLD_KEY
    ocr_threshold_key = LEGACY_OCR_THRESHOLD_KEY
    task_log_name = "跑图跑商"
    diagnostic_prefix = "map_trade"

    def validate_config(self, key, value):
        if key not in {self.vision_threshold_key, self.ocr_threshold_key}:
            return None
        try:
            if not 0.0 < float(value) <= 1.0:
                return "阈值必须大于 0 且不超过 1。"
        except (TypeError, ValueError):
            return "阈值必须是数字。"
        return None

    def _run_phases(self, navigator, phases) -> bool:
        completed: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        self.info_set("状态", f"{self.task_log_name}启动。")
        try:
            for name, config_key, action in phases:
                if isinstance(config_key, (tuple, list, set)):
                    enabled = any(bool(self.config.get(key, True)) for key in config_key)
                else:
                    enabled = bool(self.config.get(config_key, True))
                if not enabled:
                    skipped.append(name)
                    continue
                self.info_set("当前阶段", name)
                self.log_info(f"{self.task_log_name}：开始{name}。")
                try:
                    result = action()
                    success = bool(getattr(result, "success", result))
                    message = str(getattr(result, "message", ""))
                    if message:
                        self.log_info(f"{name}：{message}")
                    (completed if success else failed).append(name)
                    if not success:
                        self._note_phase_problem("fail", f"{name}：{message}" if message else name)
                        self._save_diagnostic(f"{self.diagnostic_prefix}_{name}_failed")
                        self.log_warning(
                            f"{self.task_log_name}：{name}失败，停止后续阶段。"
                        )
                        break
                except (TaskDisabledException, FinishedException):
                    raise
                except Exception as exc:
                    failed.append(name)
                    self._note_phase_problem("error", f"{name}：{exc}")
                    self.log_error(f"{self.task_log_name}子流程失败：{name}。", exc)
                    self._save_diagnostic(f"{self.diagnostic_prefix}_{name}_error")
                    self.log_warning(
                        f"{self.task_log_name}：{name}异常，停止后续阶段。"
                    )
                    break
        finally:
            self.info_set("当前阶段", "返回章节主页")
            try:
                returned = navigator.return_home()
            except (TaskDisabledException, FinishedException):
                raise
            except Exception as exc:
                self.log_error(f"{self.task_log_name}：返回章节主页异常。", exc)
                self._save_diagnostic(f"{self.diagnostic_prefix}_return_home_error")
                if not self._recover_home_after_trade():
                    failed.append("返回章节主页")
            else:
                if not returned.success:
                    self.log_warning(returned.message)
                    self._save_diagnostic(f"{self.diagnostic_prefix}_return_home_error")
                    if not self._recover_home_after_trade():
                        failed.append("返回章节主页")

        self.info_set("完成", "、".join(completed) or "-")
        self.info_set("失败", "、".join(failed) or "-")
        self.info_set("跳过", "、".join(skipped) or "-")
        if failed:
            self.info_set("状态", f"{self.task_log_name}部分流程未完成。")
            return False
        self.info_set("状态", f"{self.task_log_name}完成。")
        self.log_completion(f"{self.task_log_name}：所有已开启流程完成。")
        return True

    def _note_phase_problem(self, how: str, note: str) -> None:
        """Keep the 问题摘要 moment before going home: the step, the reason
        and the screen where it failed.  Noted later, the summary said
        「停在 返回章节主页」 with the home screen (YES-BD2 issue #5)."""
        problem_report.note_problem(self, how, note)

    def _recover_home_after_trade(self) -> bool:
        """Never leave the game off home: fall back to back arrows and dialogs.

        The trade navigator only clicks on screens it recognises (live
        2026-09-27 it left the merchant menu open and stopped).
        """

        from src.tasks.recovery import recover_to_home

        if recover_to_home(self):
            self.log_info(f"{self.task_log_name}：已用通用返回回到主页。")
            return True
        return False

    def _save_diagnostic(self, name: str) -> None:
        try:
            self.save_frame(name, self.capture_frame())
        except Exception as exc:
            self.log_warning(f"诊断截图保存失败：{exc}")

class MapTradeTask(MapAutomationTaskBase):
    """Daily merchant task, separated from weekly map collection."""
    recover_home_on_failure = True

    vision_threshold_key = TRADE_VISION_THRESHOLD_KEY
    ocr_threshold_key = TRADE_OCR_THRESHOLD_KEY
    task_log_name = "跑商"
    diagnostic_prefix = "map_trade"
    status_keys = [
        "启用",
        "状态",
        "当前阶段",
        "导航状态",
        "主页小屋按钮",
        "主页亮度",
        "主页抽抽乐 OCR",
        "剧情角标",
        "Q_sp6商店点击",
        "Q_sp6商人前确认",
        "料理状态",
        "料理进度",
        "商品卡带页",
        "商品卡带页确认",
        "收藏重建进度",
        "购买库存日期",
        "价表来源",
        "出售价表日期",
        "完成",
        "失败",
        "跳过",
        "Log",
        "Warning",
        "Error",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "每日跑商"
        self.description = "每日按配置依次执行购买、制作料理和出售。"
        self.icon = FluentIcon.SHOPPING_CART
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.visible = True

        self.default_config.update(
            {
                "启用": True,
                "制作料理": True,
                "料理清单": list(MAIN_COOKING_RECIPES),
                "5星料理": [],
                # 收藏重建周期 and 出售保险 were removed from the settings (Leo,
                # 2026-10-05: 「用處不大」); a saved value is dropped on load and
                # the trader falls back to never rebuilding / selling MAX.
                "买": True,
                "卖": True,
                TRADE_VISION_THRESHOLD_KEY: 0.72,
                TRADE_OCR_THRESHOLD_KEY: 0.20,
                "加载页面等待秒数": 45.0,
            }
        )
        self.config_description.update(
            {
                "制作料理": "购买后按优先级制作料理，全部选择 MAX；灰色料理跳过。",
                "料理清单": "要制作的料理（全部选择 MAX）；取消勾选的不做。街头烤鸡肉串总在最后。",
                "5星料理": "额外制作的白框五道料理，默认不选；街头烤鸡肉串始终最后制作。",
                "买": (
                    "按每日08:00库存批次到第一章商人无聊收集狂大叔处砍价，"
                    "然后直接按「一键购买全部收藏」，买游戏里已收藏的商品。"
                ),
                "卖": (
                    "按每日23:00刷新后的日期，出售出售日历里当天已勾选的商品"
                    "（见下方每日出售清单）。"
                ),
                TRADE_VISION_THRESHOLD_KEY: "商店、导航与料理模板的最低匹配可信度。",
                TRADE_OCR_THRESHOLD_KEY: "商店文字和按钮识别的最低可信度。",
                "加载页面等待秒数": "进入卡带或传送后等待加载完成的最长秒数。",
            }
        )
        # One checklist per date of the bundled price table, all ticked by
        # default; unticked items are not sold that day (user, 2026-09-26).
        self._sale_day_keys = []
        for day, entries in bundled_sale_days().items():
            key = sale_day_key(day)
            self._sale_day_keys.append(key)
            self.default_config[key] = day_items(entries)
            self.config_description[key] = (
                "、".join(describe_entry(entry) for entry in entries)
                + "。取消勾选的物品当天不卖。"
            )
        self.config_type.update(
            {
                "制作料理": {"sub_configs": {True: ["料理清单", "5星料理"]}},
                "料理清单": {"type": "multi_selection", "options": list(MAIN_COOKING_RECIPES)},
                "5星料理": {
                    "type": "multi_selection",
                    "options": list(OPTIONAL_COOKING_RECIPES),
                },
                "卖": {"sub_configs": {True: list(self._sale_day_keys)}},
                **{
                    sale_day_key(day): {"type": "multi_selection", "options": day_items(entries)}
                    for day, entries in bundled_sale_days().items()
                },
                TRADE_VISION_THRESHOLD_KEY: {"min": 0.50, "max": 0.95, "step": 0.01},
                TRADE_OCR_THRESHOLD_KEY: {"min": 0.05, "max": 0.95, "step": 0.01},
                "加载页面等待秒数": {"min": 10.0, "max": 120.0, "step": 1.0},
            }
        )
    def load_config(self):
        legacy = _read_config(_config_path(self.__class__.__name__))
        section_values = _trade_section_migration_values(legacy)
        _migrate_collection_config(legacy)
        super().load_config()
        for key, value in section_values.items():
            self.config[key] = value
        key_map = {
            LEGACY_VISION_THRESHOLD_KEY: TRADE_VISION_THRESHOLD_KEY,
            LEGACY_OCR_THRESHOLD_KEY: TRADE_OCR_THRESHOLD_KEY,
        }
        for old_key, new_key in key_map.items():
            if new_key not in legacy and old_key in legacy:
                self.config[new_key] = legacy[old_key]

    def run(self):
        if not bool(self.config.get("启用", True)):
            self.info_set("状态", "跑商已禁用。")
            return True

        vision = Vision(self)
        navigator = Navigator(self, vision)
        progress = ProgressStore()
        progress.load()
        trader = Trader(self, vision, navigator, progress)
        # A retry (or a second run) only redoes what has not succeeded in its
        # period: cooking/buying twice would spend the day's currency again.
        ledger = PhaseLedger()
        skip_done = bool(self.config.get(ONLY_INCOMPLETE_KEY, False))
        # Buy first so today's ingredients are cooked today (user, 2026-09-28).
        steps = (
            ("买", trader.run_buy),
            ("制作料理", trader.run_cooking),
            ("卖", trader.run_sell),
        )
        phases = tuple(
            (name, name, ledger.once(name, action, skip_done=skip_done)) for name, action in steps
        )
        return self._run_phases(navigator, phases)
