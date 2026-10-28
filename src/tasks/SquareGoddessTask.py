import json
import re
from pathlib import Path
from time import monotonic

import cv2
import numpy as np
from ok.task.exceptions import FinishedException, TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.BaseBD2Task import (
    QUICK_SWITCH_HOME_LOOK_SECONDS,
    QUICK_SWITCH_REPRESS_LOOK_SECONDS,
    BaseBD2Task,
    CartridgeSpecialPageResult,
)
from src.tasks.map_trade.models import MatchResult, TemplateSpec
from src.tasks.map_trade.navigator_constants import (
    AUTO_MOVE_CANCEL_ATTEMPTS,
    AUTO_MOVE_CANCEL_REFERENCE_POINT,
    AUTO_MOVE_IDLE_READS,
)
from src.utils import task_vision
from src.utils.calibration import FHD_1080, HD_720
from src.utils.cartridge_quick_switch import (
    CHARACTER_CATEGORY_LABEL,
    EVENT_CATEGORY_LABEL,
    FIXED_CARTRIDGE_SLOT_PRE_CLICK_DELAY_SECONDS,
    GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO,
    LIFE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION,
    LIFE_GAMEPLAY_CATEGORY_LABEL,
    LIFE_GAMEPLAY_CATEGORY_OCR_ROI,
    LIFE_GAMEPLAY_CATEGORY_POINT,
    QUICK_SWITCH_SEARCH_REGIONS,
    QUICK_SWITCH_STABLE_FRAMES,
    SHOPKEEPER_CATEGORY_LABEL,
    category_highlight_ratio,
)
from src.utils.fantasia_square import (
    FANTASIA_SQUARE_TEMPLATE,
    LIFE_SLOT_NUMBERS,
    LIFE_SLOT_POINTS,
    SQUARE_CARTRIDGE_SLOT_POINT,
    square_card_point,
)
from src.utils.field_followers import FOLLOWERS_ABSENT, FOLLOWERS_DONE_TODAY
from src.utils.goddess_navigation import (
    NEW_DAILY_ICON,
    NavigationObservation,
    scan_navigation,
)
from src.utils.home_confirmation import (
    HOME_DIMMED_P95_THRESHOLD_DEFAULT,
    HOME_GACHA_OCR_REFERENCE_ROI,
    HOME_LEFT_COLUMN_OCR_REFERENCE_ROI,
    HOME_LEFT_COLUMN_REQUIRED_HITS,
    home_confirmation_passes,
    home_gacha_ocr_with_fallback,
    home_left_column_hits,
    home_left_column_brightness,
)
from src.utils.image_utils import (
    reference_roi_frame,
    stabilize_template_match,
)
from src.utils.ocr_utils import keyword_read, normalize_ocr_text
from src.utils.wait_limits import (
    STUCK_SECONDS,
    MotionWatch,
    StillTimer,
    capped,
    is_loading_dark,
    load_wait,
    scene_at_press,
)

REFERENCE_WIDTH = FHD_1080.width
REFERENCE_HEIGHT = FHD_1080.height
HD720_REFERENCE_WIDTH = HD_720.width
HD720_REFERENCE_HEIGHT = HD_720.height
# Swallowed quick-switch clicks: up to this many category / slot clicks.
SQUARE_CLICK_VERIFY_ATTEMPTS = 3
# The 广场 card press counts as dropped once the unchanged selection page has
# shown this long (was 8 s; Leo 2026-10-17 「切换卡带的时候可以点两下」).
SQUARE_CARD_REPRESS_SECONDS = 2.5
SQUARE_HOME_POINT = (1797 / REFERENCE_WIDTH, 63 / REFERENCE_HEIGHT)
# The game's shortcut shown under that button (Leo 2026-10-11 「我點H就回到主頁了」).
SQUARE_HOME_KEY = "H"
GODDESS_NAVIGATION_CLICKED = "navigation_clicked"
# Every look read the square's right side and found no daily row at all.
GODDESS_NAVIGATION_ABSENT = "navigation_absent"
# The wish row leaves the square once the day's wish is made, by the tool, by
# hand or on another PC (Leo 2026-10-28 「我明明是已經許願完的 但他卻判失敗」
# 「應該判定已跳過 已完成就好」): no row, its key E and its usual spot both
# start no walk, and the square still on screen = wished today.
GODDESS_WISHED_NOTE = "今天已经许愿过"
GODDESS_NAVIGATION_RETRIES = 2
# The key shown beside the daily row; it starts the walk to the goddess.
GODDESS_ROW_KEY = "E"
# The game's talk key: wishes when standing at the statue.
GODDESS_TALK_KEY = "F"
# The prayer prompt read twice may move this far (client pixels) and still count.
GODDESS_PROMPT_STEADY_PIXELS = 24
# Unread daily row: press where it sits as the first task (a player's 1080p
# frame, 2026-10-11) and go on only if a walk or the prayer prompt follows.
# Leo: 「讀不到 不是應該還是嘗試用滑鼠點一下嗎 點到就有 沒點到不會損失甚麼」.
GODDESS_ROW_USUAL_POINT = (1678 / REFERENCE_WIDTH, 228 / REFERENCE_HEIGHT)
GODDESS_ROW_PRESS_CONFIRM_SECONDS = 5.0
# The game's walk banner ("自动移动中：…", bottom centre, ✕ under it).  A player
# (2026-10-11) saw the walk to the goddess stop on the way with the banner
# still up and the home button hidden, so nothing could leave the square.
GODDESS_WALK_BANNER = "移动中"
# The walk counts as stuck once its banner is up and the field has not moved
# for this long (Leo 2026-10-14 「頂多等8秒到10秒」: was 20 s of banner,
# moving or not; a walk that keeps going is the game working).
GODDESS_WALK_STUCK_SECONDS = STUCK_SECONDS
QUICK_SWITCH_PAGE_PATTERNS = (
    SHOPKEEPER_CATEGORY_LABEL,
    CHARACTER_CATEGORY_LABEL,
    LIFE_GAMEPLAY_CATEGORY_LABEL,
    EVENT_CATEGORY_LABEL,
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PROJECT_ROOT / "recognition-assets" / "template-assets"


class SquareGoddessTask(BaseBD2Task):
    recover_home_on_failure = True
    start_from_home = True
    frozen_retry = True
    status_keys = [
        "启用",
        "状态",
        "当前阶段",
        "主页抽抽乐 OCR 尝试",
        "主页亮度p95",
        "主页抽抽乐 OCR",
        "广场主页点击次数",
        "快速切换按钮",
        "卡带选择页 OCR",
        "卡带选择页 OCR 命中",
        "生活玩法游戏卡带 OCR",
        "生活玩法类别高亮",
        "梦幻广场",
        "跟随角色按钮",
        "女神像许愿 OCR",
        "广场每日导航",
        "广场导航文本 OCR",
        "女神像许愿结果",
        "匹配错误",
        "Log",
        "Warning",
        "Error",
    ]

    status_key_labels = {
        "梦幻广场": "梦幻广场模板",
        "广场每日导航": "每日导航模板",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "广场女神像"
        self.description = (
            "从快速切换页的生活玩法游戏卡带里找到广场卡带进入梦幻广场并完成女神像许愿。"
        )
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
                "主页压暗阈值": HOME_DIMMED_P95_THRESHOLD_DEFAULT,
                "主页确认等待秒数": 10.0,
                "快速卡带等待秒数": 10.0,
                "快速切换按钮阈值": 0.88,
                "卡带选择页确认等待秒数": 10.0,
                "玩法类别高亮确认秒数": 3.0,
                "玩法类别高亮像素比例": GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO,
                "广场 OCR 阈值": 0.2,
                "广场入场等待秒数": STUCK_SECONDS,
                "女神像导航入口等待秒数": 8.0,
                "女神像导航最长等待秒数": 90.0,
                "女神像寻路卡住秒数": GODDESS_WALK_STUCK_SECONDS,
                "女神像完成确认等待秒数": 8.0,
                "女神像许愿最多点击次数": 3,
                "广场返回主页等待秒数": STUCK_SECONDS,
                "广场返回主页最多点击次数": 3,
                "广场返回主页重试间隔秒数": 2.0,
                "梦幻广场阈值": 0.78,
                "广场每日导航阈值": 0.76,
            }
        )
        self.config_description.update(
            {
                "广场 OCR 阈值": "广场入场流程 OCR 使用的最低可信度。",
                "主页压暗阈值": "主页左列灰度 p99 低于该值视为被公告压暗（0-255）。",
                "快速切换按钮阈值": "识别 QuickSwitchPlayIco.png 快速切换按钮的模板匹配阈值。",
                "玩法类别高亮像素比例": (
                    "生活玩法游戏卡带标签确认为高亮状态所需的最低亮色像素占比。"
                ),
                "广场入场等待秒数": "点击广场卡带后等待梦幻广场场景出现的最长时间。",
                "女神像导航最长等待秒数": (
                    "点击每日导航后，角色一直在走时最多等这么久；10 秒没进展就不再等。"
                ),
                "女神像寻路卡住秒数": (
                    "「自动移动中」一直显示超过这么久就算卡住：按掉它，再点一次每日导航。"
                ),
                "女神像完成确认等待秒数": "点击许愿后等待每日导航文字消失的最长时间。",
                "女神像许愿最多点击次数": "OCR 仍识别到许愿提示时最多重复点击几次。",
                "广场返回主页等待秒数": "许愿完成后点击主页按钮并确认回到主页的最长时间。",
                "广场返回主页最多点击次数": (
                    "返回主页点击未生效且仍明确识别到广场聊天输入时，允许的总点击次数。"
                ),
                "广场返回主页重试间隔秒数": (
                    "返回主页点击后仍停留在广场时，再次点击主页按钮前的最短等待时间。"
                ),
            }
        )

    def _status_set(self, key: str, value) -> None:
        try:
            self.info_set(key, value)
        except AttributeError:
            pass

    def run(self):
        if not bool(self.config.get("启用", True)):
            self.info_set("状态", "广场女神像已禁用。")
            self.log_info("广场女神像已禁用。")
            return True

        self.done_already_note = ""
        self.info_set("状态", "广场女神像启动。")
        self.log_info("广场女神像：开始从主页进入梦幻广场。")
        if not self._enter_square_from_home():
            self.info_set("状态", "广场女神像失败：未能进入梦幻广场。")
            return False

        self.info_set("状态", "已进入梦幻广场，开始寻找女神像。")
        if not self._pray_at_goddess():
            self._status_set("女神像许愿结果", "失败")
            # Leo 2026-10-11 「哪怕我有沒有點到女神像 我都是要離開廣場進行下一步的」
            self.log_info("广场女神像：许愿没有完成，照样离开广场，继续下一步。")
            left = self._return_home_from_square()
            self.info_set(
                "状态",
                "广场女神像失败：未能完成女神像许愿"
                + ("，已离开广场。" if left else "，也未能确认回到主页。"),
            )
            return False

        self._record_wish()
        if getattr(self, "done_already_note", ""):
            self.info_set("状态", "今天已许愿，跳过。")
            self._status_set("女神像许愿结果", "今天已许愿")
            if not self._return_home_from_square():
                self.info_set("状态", "广场女神像失败：今天已许愿，但未能返回主页。")
                return False
            self.info_set("状态", "今天已许愿，跳过并返回主页。")
            self.log_completion("广场女神像：今天已经许愿过，跳过并返回主页。")
            return True
        self.info_set("状态", "女神像许愿完成。")
        self._status_set("女神像许愿结果", "完成")
        if not self._return_home_from_square():
            self.info_set("状态", "广场女神像失败：许愿完成，但未能返回主页。")
            return False
        self.info_set("状态", "女神像许愿完成并返回主页。")
        self.log_completion("广场女神像：许愿完成并返回主页。")
        return True

    def _return_home_from_square(self) -> bool:
        self.info_set("当前阶段", "广场返回主页")
        max_clicks = max(
            1,
            int(self.config.get("广场返回主页最多点击次数", 3)),
        )
        retry_interval = max(
            0.0,
            float(self.config.get("广场返回主页重试间隔秒数", 2.0)),
        )
        self.info_set("广场主页点击次数", f"1/{max_clicks}")
        self.operate_click(*SQUARE_HOME_POINT, after_sleep=1.0)
        return self._wait_for_cartridge_home(
            timeout=float(self.config.get("广场返回主页等待秒数", STUCK_SECONDS)),
            retry_home_clicks=max_clicks - 1,
            retry_interval=retry_interval,
            total_home_clicks=max_clicks,
        )

    def _enter_square_from_home(self) -> bool:
        """The square card is clicked where its picture is.  When the picture
        can't be read, slot 2 is tried, and if that opens another field (a
        player's row in another order: v0.1.42 summary 2026-10-15 landed in
        格鲁菲餐厅), back to 主页 and the next slot."""
        blind_slots = list(LIFE_SLOT_POINTS)
        while True:
            entered, by_picture = self._enter_square_once(blind_slots)
            if entered:
                return True
            if by_picture is not False or not blind_slots:
                return False
            self.log_info("广场女神像：点的那格没进梦幻广场，回主页换下一格。")
            if not self._return_home_from_square():
                return False

    def _find_square_card(self):
        """Where the square cartridge is in the 生活玩法 row; a slow PC gets a
        second look a second later."""
        score = -1.0
        for look in range(2):
            if look:
                self.sleep(1.0)
            point, score = square_card_point(self.capture_frame(), self.config, self._templates)
            self.info_set("广场卡带图", f"{score:.3f}")
            if point is not None:
                return point
        return None

    def _enter_square_once(self, blind_slots: list) -> tuple[bool, bool | None]:
        """(entered, whether the card was found by its picture); None when
        the card row never came up."""
        self.info_set("当前阶段", "打开卡带快速切换")
        if not self.open_cartridge_quick_switcher(
            ensure_home=self._wait_for_cartridge_home,
            click_quick_switch=lambda: self._click_template_until(
                QUICK_SWITCH_TEMPLATE,
                timeout=float(self.config.get("快速卡带等待秒数", 10.0)),
                name="快速切换按钮",
                after_sleep=0.0,
                stabilize=True,
            ),
            confirm_quick_switch_page=self._wait_for_quick_switch_page,
            quick_switch_page_shown=lambda seconds: self._wait_for_quick_switch_page(
                timeout=seconds, quiet=True
            ),
            repress_quick_switch=lambda: self._click_template_until(
                QUICK_SWITCH_TEMPLATE,
                timeout=QUICK_SWITCH_REPRESS_LOOK_SECONDS,
                name="快速切换按钮",
                after_sleep=0.0,
                stabilize=True,
            ),
            home_shown=lambda: self._wait_for_cartridge_home(
                timeout=QUICK_SWITCH_HOME_LOOK_SECONDS
            ),
        ):
            self.log_info("广场女神像：未能从主页打开卡带快速切换页面。")
            return False, None

        self.info_set("当前阶段", "选择生活玩法游戏卡带")
        self.sleep(0.5)
        # 类别点击被吞时高亮不会变：仅在卡带选择页仍在、类别仍未高亮时重点（同末日之书）。
        for attempt in range(1, SQUARE_CLICK_VERIFY_ATTEMPTS + 1):
            self.operate_click(*LIFE_GAMEPLAY_CATEGORY_POINT, after_sleep=0.0)
            if self._wait_for_life_gameplay_category():
                break
            if attempt >= SQUARE_CLICK_VERIFY_ATTEMPTS or not self._quick_switch_still_shows(
                highlighted=False, seconds=1.0
            ):
                self.log_info("广场女神像：点击后未确认生活玩法游戏卡带类别高亮。")
                return False, None
            self.log_info(f"广场女神像：第{attempt}次点击生活玩法类别未生效，重试。")

        self.info_set("当前阶段", "选择广场卡带")
        self.sleep(FIXED_CARTRIDGE_SLOT_PRE_CLICK_DELAY_SECONDS)
        slot = self._find_square_card()
        by_picture = slot is not None
        if not by_picture:
            slot = blind_slots.pop(0)
            number = LIFE_SLOT_NUMBERS[LIFE_SLOT_POINTS.index(slot)]
            self.log_info(f"广场女神像：没认出广场卡带的图，改点生活玩法第{number}格。")
        self.operate_click(*slot, after_sleep=0.0)
        # 卡带格点击被吞时选择页原样停住；连续数秒仍是同一页（类别仍高亮）才重点，
        # 页面一变就不再点，避免载入中重复操作。
        for attempt in range(1, SQUARE_CLICK_VERIFY_ATTEMPTS):
            if not self._quick_switch_still_shows(
                highlighted=True, seconds=SQUARE_CARD_REPRESS_SECONDS
            ):
                break
            self.log_info(f"广场女神像：第{attempt}次点击广场卡带后选择页仍在，重试。")
            self.operate_click(*slot, after_sleep=0.0)

        if self._wait_for_template(
            FANTASIA_SQUARE_TEMPLATE,
            timeout=float(self.config.get("广场入场等待秒数", STUCK_SECONDS)),
            name="梦幻广场",
            arrival=True,
        ):
            return True, by_picture

        if self._handle_recent_cartridge_special_pages(
            allow_pvp_pages=False,
        ) is CartridgeSpecialPageResult.HANDLED:
            entered = self._wait_for_template(
                FANTASIA_SQUARE_TEMPLATE,
                timeout=float(self.config.get("广场入场等待秒数", STUCK_SECONDS)),
                name="梦幻广场",
                arrival=True,
            )
            return entered, by_picture

        return False, by_picture

    def _wait_for_cartridge_home(
        self,
        interval: float = 0.35,
        timeout: float | None = None,
        retry_home_clicks: int = 0,
        retry_interval: float = 2.0,
        total_home_clicks: int = 1,
    ) -> bool:
        self.info_set("当前阶段", "确认主页")
        wait_seconds = (
            float(self.config.get("主页确认等待秒数", 10.0))
            if timeout is None
            else max(0.0, float(timeout))
        )
        end_at = monotonic() + wait_seconds
        # Leaving the square loads (Leo 2026-10-15 「你單純等載入怎麼可以改成只等
        # 10秒」): a full wait does not end while the screen is loading.
        wait = load_wait(monotonic(), wait_seconds, before=scene_at_press(self)) if wait_seconds >= STUCK_SECONDS else None
        last_left_hits = 0
        last_p95 = 0.0
        last_gacha_text = ""
        remaining_home_clicks = max(0, int(retry_home_clicks))
        total_home_clicks = max(
            remaining_home_clicks + 1,
            int(total_home_clicks),
        )
        completed_home_clicks = total_home_clicks - remaining_home_clicks
        retry_interval = max(0.0, float(retry_interval))
        next_home_retry_at = (
            monotonic() + retry_interval
            if remaining_home_clicks > 0
            else float("inf")
        )
        while wait is not None or monotonic() <= end_at:
            frame = self.capture_frame()
            left_text = self._ocr_text(
                frame,
                name="主页左列",
                roi=HOME_LEFT_COLUMN_OCR_REFERENCE_ROI,
            )
            last_left_hits = home_left_column_hits(left_text)
            last_p95 = home_left_column_brightness(frame)
            gacha_result = home_gacha_ocr_with_fallback(
                lambda scale: self._ocr_text(
                    frame,
                    name=f"主页抽抽乐 x{scale:g}",
                    roi=HOME_GACHA_OCR_REFERENCE_ROI,
                    ocr_scale=scale,
                )
            )
            last_gacha_text = gacha_result.text
            self.info_set("主页抽抽乐 OCR 尝试", gacha_result.trace)
            self.info_set(
                "主页左列关键词",
                f"{last_left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}",
            )
            self.info_set(
                "主页亮度p95",
                f"{last_p95:.0f}/{self._home_p95_threshold():.0f}",
            )
            self.info_set("主页抽抽乐 OCR", last_gacha_text or "-")
            if home_confirmation_passes(
                left_hits=last_left_hits,
                required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                brightness=last_p95,
                brightness_threshold=self._home_p95_threshold(),
                gacha_ocr_text=last_gacha_text,
            ):
                return True
            self.clear_temporary_home_announcement_if_needed(
                left_hits=last_left_hits,
                required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                brightness=last_p95,
                brightness_threshold=self._home_p95_threshold(),
                gacha_ocr_text=last_gacha_text,
                context="广场女神像返回主页",
            )
            if remaining_home_clicks > 0 and monotonic() >= next_home_retry_at:
                quick_switch_result = self._match(frame, QUICK_SWITCH_TEMPLATE)
                self.info_set(
                    "快速切换按钮",
                    f"{quick_switch_result.score:.3f}/{quick_switch_result.pixel_score:.3f}",
                )
                still_in_square = self._passes(
                    quick_switch_result,
                    QUICK_SWITCH_TEMPLATE,
                )
                completed_home_clicks += 1
                remaining_home_clicks -= 1
                self.info_set(
                    "广场主页点击次数",
                    f"{completed_home_clicks}/{total_home_clicks}",
                )
                if still_in_square:
                    self.log_info(
                        "广场女神像：返回主页点击未生效，"
                        f"仍识别到快速切换卡带按钮，执行第{completed_home_clicks}次点击。"
                    )
                    self.operate_click(*SQUARE_HOME_POINT, after_sleep=1.0)
                else:
                    # Neither home nor the square's buttons read (HDR, a
                    # popup...): never stuck (Leo 2026-10-11 「不可以說認不到辨識
                    # 不到就卡住 你可以用快捷鍵」).  The game's own H key goes to
                    # 主页; a click could land on home's menu icon instead.
                    self.log_info(
                        "广场女神像：没认出主页，也没认出广场按钮，"
                        f"第{completed_home_clicks}次改按快捷键 H 回主页。"
                    )
                    self.tap_key(SQUARE_HOME_KEY, after_sleep=1.0)
                next_home_retry_at = monotonic() + retry_interval
                continue
            if wait is not None and wait.over(frame, monotonic(), loading=is_loading_dark(frame)):
                break
            self.sleep(interval)

        self.log_info(
            "广场女神像：未同时确认左列关键词、亮度和抽抽乐文字，"
            f"left={last_left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}, "
            f"p95={last_p95:.0f}, ocr={last_gacha_text or '-'}。"
        )
        return False

    def _wait_for_quick_switch_page(
        self,
        interval: float = 0.5,
        timeout: float | None = None,
        quiet: bool = False,
    ) -> bool:
        """``timeout`` set: a short look (no settle sleep, no log on a miss)."""
        self.info_set("当前阶段", "确认卡带选择页")
        if timeout is None:
            self.sleep(1.0)
            timeout = float(self.config.get("卡带选择页确认等待秒数", 10.0))
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            text = self._ocr_text(frame, name="卡带选择页")
            last_text = text or last_text
            normalized = self._normalize_text(text)
            match_count = sum(
                keyword_read(self._normalize_text(pattern), normalized)
                for pattern in QUICK_SWITCH_PAGE_PATTERNS
            )
            self.info_set("卡带选择页 OCR", text or "-")
            self.info_set(
                "卡带选择页 OCR 命中",
                f"{match_count}/{len(QUICK_SWITCH_PAGE_PATTERNS)}",
            )
            if match_count == len(QUICK_SWITCH_PAGE_PATTERNS):
                return True
            self.sleep(interval)

        if quiet:
            return False
        self.log_info(
            "广场女神像：点击快速切换后未确认卡带选择页，"
            f"OCR={last_text or '-'}。"
        )
        return False

    def _quick_switch_still_shows(self, highlighted: bool, seconds: float) -> bool:
        """Re-click guard: every frame for ``seconds`` (two at least) must still
        show the life category label with the given highlight state."""
        end_at = monotonic() + max(0.0, seconds)
        reads = 0
        threshold = float(
            self.config.get("玩法类别高亮像素比例", GAMEPLAY_CATEGORY_HIGHLIGHT_MIN_RATIO)
        )
        while True:
            frame = self.capture_frame()
            text = self._ocr_text(
                frame, name="生活玩法游戏卡带", roi=LIFE_GAMEPLAY_CATEGORY_OCR_ROI
            )
            ratio = category_highlight_ratio(frame, LIFE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION)
            if not self._matches_any(text, [LIFE_GAMEPLAY_CATEGORY_LABEL]):
                return False
            if (ratio >= threshold) != highlighted:
                return False
            reads += 1
            if reads >= 2 and monotonic() >= end_at:
                return True
            self.sleep(0.5)

    def _wait_for_life_gameplay_category(self, interval: float = 0.5) -> bool:
        end_at = monotonic() + float(self.config.get("玩法类别高亮确认秒数", 3.0))
        last_text = ""
        last_highlight_ratio = 0.0
        while monotonic() <= end_at:
            frame = self.capture_frame()
            text = self._ocr_text(
                frame,
                name="生活玩法游戏卡带",
                roi=LIFE_GAMEPLAY_CATEGORY_OCR_ROI,
            )
            last_text = text or last_text
            last_highlight_ratio = category_highlight_ratio(
                frame,
                LIFE_GAMEPLAY_CATEGORY_HIGHLIGHT_REGION,
            )
            self.info_set("生活玩法游戏卡带 OCR", text or "-")
            self.info_set("生活玩法类别高亮", f"{last_highlight_ratio:.3f}")
            if (
                self._matches_any(text, [LIFE_GAMEPLAY_CATEGORY_LABEL])
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
            "广场女神像：未确认生活玩法游戏卡带类别高亮，"
            f"highlight={last_highlight_ratio:.3f}, OCR={last_text or '-'}。"
        )
        return False

    # The run history keeps only the latest run, so a later failed run would
    # hide the morning's wish: the wish day is kept in its own file.
    WISH_RECORD_PATH = Path("configs") / "goddess_wish.json"

    def _wish_path(self) -> Path:
        from src.utils import accounts, test_run

        path = Path(accounts.scoped(self.WISH_RECORD_PATH))
        return test_run.scratch() / path if test_run.active() else path

    @staticmethod
    def _game_day() -> str:
        from datetime import datetime

        from src.tasks.map_trade.progress import UTC_PLUS_8, daily_cycle_key

        return daily_cycle_key(datetime.now(UTC_PLUS_8))

    def _wished_today(self) -> bool:
        try:
            data = json.loads(self._wish_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(data, dict) and data.get("day") == self._game_day()

    def _record_wish(self) -> None:
        try:
            path = self._wish_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"day": self._game_day()}), encoding="utf-8"
            )
        except OSError:
            pass

    def _pray_at_goddess(self) -> bool:
        self.info_set("当前阶段", "检查广场感叹号")
        self._click_square_notice_if_present()

        self.info_set("当前阶段", "检查女神像每日导航")
        navigation_result = self._click_goddess_daily_navigation_until(
            timeout=float(self.config.get("女神像导航入口等待秒数", 8.0))
        )
        if navigation_result != GODDESS_NAVIGATION_CLICKED and self._prayer_prompt_steady():
            # A player's 1080p frame (2026-10-11): standing at the goddess with
            # 「向女神像许愿」 up, the daily row over the pink food truck unread.
            self.log_info("广场女神像：没认出每日导航，但许愿提示已经在画面上，直接许愿。")
            navigation_result = GODDESS_NAVIGATION_CLICKED
        if navigation_result != GODDESS_NAVIGATION_CLICKED and self._wished_today():
            # The wish is once a day and its navigation hint disappears once
            # made: a second run the same day is not a failure (2026-09-28).
            self.info_set("女神像许愿 OCR", "今日已许愿（导航已消失）")
            self.log_info("广场女神像：今天已经许愿过，每日导航已消失。")
            self.done_already(GODDESS_WISHED_NOTE)
            return True
        row_absent = navigation_result == GODDESS_NAVIGATION_ABSENT
        if navigation_result != GODDESS_NAVIGATION_CLICKED and self._walk_by_key():
            navigation_result = GODDESS_NAVIGATION_CLICKED
        if navigation_result != GODDESS_NAVIGATION_CLICKED and (
            self._press_row_where_it_usually_is()
        ):
            navigation_result = GODDESS_NAVIGATION_CLICKED
        if navigation_result != GODDESS_NAVIGATION_CLICKED and row_absent and (
            self._square_still_shown()
        ):
            self.info_set("女神像许愿 OCR", "今日已许愿（没有每日导航）")
            self.log_info(
                "广场女神像：广场右边没有「移动至艾力克史温女神像」的每日导航，"
                f"按 {GODDESS_ROW_KEY} 和点它平常的位置都没开始走，广场画面也还在："
                "今天已经许愿过（自己许的或别的电脑许的），跳过。"
            )
            self.done_already(GODDESS_WISHED_NOTE)
            return True
        if navigation_result != GODDESS_NAVIGATION_CLICKED:
            self.info_set("女神像许愿 OCR", "未确认女神像每日导航，停止本次任务")
            self.log_info(
                "广场女神像：右边有任务列表的字但认不出女神像那一行，"
                f"按 {GODDESS_ROW_KEY} 和点它平常的位置都没开始走，这次没有许愿。"
                if not row_absent else
                "广场女神像：每日导航没出现，按了也没开始走，而且画面已经不是广场，这次没有许愿。"
            )
            return False
        self.info_set("当前阶段", "等待并完成女神像许愿")
        if not self._wait_for_goddess_prayer_completion(
            timeout=float(self.config.get("女神像导航最长等待秒数", 90.0))
        ):
            self.log_info("广场女神像：等待许愿或完成确认超时。")
            return False

        self.info_set("当前阶段", "祈祷完成后检查广场感叹号")
        self._click_square_notice_if_present()
        return True

    def _square_still_shown(self) -> bool:
        """The square's picture on two fresh frames: nothing covers the field,
        so the missing row is the game's own answer, not a popup over it."""
        for look in range(2):
            if look:
                self.sleep(0.35)
            frame = self.capture_frame()
            result = self._match(frame, FANTASIA_SQUARE_TEMPLATE)
            self.info_set("梦幻广场", f"{result.score:.3f}")
            if not self._passes(result, FANTASIA_SQUARE_TEMPLATE):
                return False
        return True

    def _prayer_prompt_steady(self) -> bool:
        """「向女神像许愿」 at the same spot on two fresh frames."""
        previous = None
        for look in range(2):
            if look:
                self.sleep(0.35)
            point, _text = self._ocr_pattern_click_point(
                self.capture_frame(), GODDESS_PRAY_PATTERNS, name="女神像许愿", roi=None
            )
            if point is None:
                return False
            if previous is not None and max(
                abs(a - b) for a, b in zip(point, previous)
            ) > GODDESS_PROMPT_STEADY_PIXELS:
                return False
            previous = point
        return True

    def _walk_by_key(self) -> bool:
        """The daily row's own key E walks to the goddess (Leo 2026-10-20
        「點 E 會走到女神像」); True once a walk or the prompt shows."""
        self.log_info(f"广场女神像：每日导航读不到，改按快捷键 {GODDESS_ROW_KEY} 走去女神像。")
        if not self.tap_key(GODDESS_ROW_KEY, after_sleep=1.0):
            return False
        if self._walk_or_prompt_within(GODDESS_ROW_PRESS_CONFIRM_SECONDS):
            self.log_info(f"广场女神像：按 {GODDESS_ROW_KEY} 以后开始走向女神像了。")
            return True
        self.log_info(f"广场女神像：按了 {GODDESS_ROW_KEY} 也没开始走。")
        return False

    def _tap_row_key(self) -> None:
        self.tap_key(GODDESS_ROW_KEY, after_sleep=2.0)

    def _walk_or_prompt_within(self, seconds: float) -> bool:
        """True once the prayer prompt, the walk banner or a field that keeps
        panning shows (YES-BD2 #62: the banner went unread while walking)."""
        end_at = monotonic() + seconds
        motion = MotionWatch()
        while True:
            frame = self.capture_frame()
            point, text = self._ocr_pattern_click_point(
                frame, GODDESS_PRAY_PATTERNS, name="女神像许愿", roi=None
            )
            if point is not None or self._walk_banner_shown(text):
                return True
            if motion.moving(frame):
                self.log_info("广场女神像：没读到「自动移动中」，但画面一直在动，当作已经在走。")
                return True
            if monotonic() >= end_at:
                return False
            self.sleep(0.5)

    def _press_row_where_it_usually_is(self) -> bool:
        """Press the daily row's usual spot; True once a walk or the prompt shows."""
        frame = self.capture_frame()
        height, width = frame.shape[:2]
        x, y = GODDESS_ROW_USUAL_POINT
        self.log_info("广场女神像：每日导航读不到，照它平常的位置点一下。")
        self._click_client(round(x * width), round(y * height), width, height, after_sleep=1.0)
        if self._walk_or_prompt_within(GODDESS_ROW_PRESS_CONFIRM_SECONDS):
            self.log_info("广场女神像：点了以后开始走向女神像了。")
            return True
        self.log_info("广场女神像：照平常位置点了也没开始走。")
        return False

    def _click_square_notice_if_present(self) -> bool:
        # The square "!" is the field F button: it shows while the characters
        # that follow the player after login are around (Leo, 2026-10-03).
        # Looked for every time, even after 镜中之战 sent them away (Leo
        # 2026-10-20 「廣場處還是要注意有沒有驚嘆號」).
        return self.clear_field_followers() not in (FOLLOWERS_ABSENT, FOLLOWERS_DONE_TODAY)

    def _click_goddess_daily_navigation_until(
        self,
        timeout: float,
        interval: float = 0.35,
    ) -> str | None:
        end_at = monotonic() + max(0.0, timeout)
        previous = None
        always_absent = None
        while monotonic() <= end_at:
            frame = self.capture_frame()
            observation = self._observe_goddess_navigation(frame)
            always_absent = always_absent is not False and observation.state == "absent"
            nav = observation.navigation
            if nav is not None and previous is not None:
                tolerance = max(nav.height, previous.height)
                if all(abs(a - b) <= tolerance for a, b in zip(nav.center, previous.center)):
                    self._click_client(*nav.center, frame.shape[1], frame.shape[0], after_sleep=2.0)
                    return GODDESS_NAVIGATION_CLICKED
            previous = nav
            self.sleep(interval)
        return GODDESS_NAVIGATION_ABSENT if always_absent else None

    def _wait_for_goddess_prayer_completion(
        self,
        timeout: float,
        interval: float = 0.5,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        max_clicks = max(1, int(self.config.get("女神像许愿最多点击次数", 3)))
        click_count = 0
        # 导航点击可能被吞（2026-09-26 实测：90 秒内导航行一直在、许愿提示从未出现）：
        # 超时未见许愿提示且导航行仍可点时补点导航（Leo 2026-10-14 最多等 10 秒，原 35 秒）。
        renav_seconds = capped(self.config.get("女神像导航重试秒数", STUCK_SECONDS))
        renav_left = GODDESS_NAVIGATION_RETRIES
        last_navigation_at = monotonic()
        stuck_seconds = capped(
            self.config.get("女神像寻路卡住秒数", GODDESS_WALK_STUCK_SECONDS)
        )
        walking_since = None
        walk_still = StillTimer()
        # The banner can go unread while the field pans (YES-BD2 #62): a
        # moving field is the walk too, and nothing is pressed during it.
        walk_motion = MotionWatch()
        talked = False
        # Nothing to read, no walk and no press: the screen is not getting
        # anywhere (the overall limit only holds a walk that keeps moving).
        idle_since = monotonic()

        while monotonic() <= end_at:
            frame = self.capture_frame()
            frame_height, frame_width = frame.shape[:2]
            point, text = self._ocr_pattern_click_point(
                frame,
                GODDESS_PRAY_PATTERNS,
                name="女神像许愿",
                roi=None,
            )
            self.info_set("女神像许愿 OCR", text or "-")

            banner = self._walk_banner_shown(text)
            # After a wish press the wish itself may move the picture.
            panning = walk_motion.moving(frame) and not (click_count or talked)
            if point is None and (banner or panning):
                now = monotonic()
                idle_since = now
                walking_since = now if walking_since is None else walking_since
                if walk_still.still_for(frame, now) < stuck_seconds:
                    self.sleep(interval)
                    continue
                walking_since = None
                walk_still.reset()
                stopped = self._cancel_goddess_walk()
                stuck = f"广场女神像：自动寻路停在半路，画面超过{stuck_seconds:.0f}秒没动"
                if renav_left <= 0:
                    self.log_info(
                        f"{stuck}，重新导航后还是一样，"
                        + ("已按掉自动移动，" if stopped else "")
                        + "这次没有许愿。"
                    )
                    return False
                if not stopped:
                    continue
                self.log_info(f"{stuck}，已按掉自动移动，重新点每日导航。")
                renav_left -= 1
                navigation = self._click_goddess_daily_navigation_until(
                    timeout=float(self.config.get("女神像导航入口等待秒数", 8.0))
                )
                if navigation != GODDESS_NAVIGATION_CLICKED:
                    self._tap_row_key()
                last_navigation_at = monotonic()
                idle_since = monotonic()
                continue
            walking_since = None
            walk_still.reset()

            if point is not None and click_count < max_clicks:
                self._click_client(
                    point[0],
                    point[1],
                    frame_width,
                    frame_height,
                    after_sleep=2.0,
                )
                click_count += 1
                idle_since = monotonic()
            else:
                if (
                    (click_count or talked)
                    and point is None
                    and self._wait_for_daily_navigation_to_disappear(timeout=2.5)
                ):
                    return True
                if (
                    monotonic() - idle_since >= STUCK_SECONDS
                    and (point is not None or renav_left <= 0)
                    and not talked
                ):
                    # The wish prompt unread or its press dropped (Leo
                    # 2026-10-20 「讀不到也要有備案」): the game's talk key F
                    # wishes next to the statue; the daily row going away
                    # proves it.
                    talked = True
                    self.log_info("广场女神像：许愿提示点不到也读不到，改按 F 键许愿。")
                    if self.tap_key(GODDESS_TALK_KEY, after_sleep=2.0) and (
                        self._wait_for_daily_navigation_to_disappear(
                            timeout=float(self.config.get("女神像完成确认等待秒数", 8.0))
                        )
                    ):
                        return True
                    idle_since = monotonic()
                    self.sleep(interval)
                    continue
                if monotonic() - idle_since >= STUCK_SECONDS and (
                    point is not None or renav_left <= 0
                ):
                    self.log_info(
                        f"广场女神像：{STUCK_SECONDS:.0f} 秒没走到下一步"
                        + (
                            "（许愿点了没反应）"
                            if point is not None
                            else "（没看到许愿提示、也没在走）"
                        )
                        + "，这次没有许愿。"
                    )
                    break
                if (
                    point is None
                    and renav_left > 0
                    and monotonic() - last_navigation_at >= renav_seconds
                ):
                    observation = self._observe_goddess_navigation(frame)
                    if observation.navigation is not None:
                        renav_left -= 1
                        self.log_info("广场女神像：许愿提示迟迟未出现，补点每日导航。")
                        self._click_client(
                            *observation.navigation.center,
                            frame_width,
                            frame_height,
                            after_sleep=2.0,
                        )
                        idle_since = monotonic()
                    elif click_count or talked:
                        # E only walks while the wish is still open (Leo
                        # 2026-10-20); after a wish press it does nothing.
                        renav_left -= 1
                    else:
                        renav_left -= 1
                        self.log_info("广场女神像：许愿提示迟迟未出现，每日导航读不到，改按 E。")
                        self._tap_row_key()
                        idle_since = monotonic()
                    last_navigation_at = monotonic()
                self.sleep(interval)
                continue

            if self._wait_for_daily_navigation_to_disappear(
                timeout=float(self.config.get("女神像完成确认等待秒数", 8.0))
            ):
                return True

        # A walk still under way hides the home button: stop it first.
        self._cancel_goddess_walk()
        return False

    @staticmethod
    def _walk_banner_shown(text: str) -> bool:
        return GODDESS_WALK_BANNER in SquareGoddessTask._normalize_text(text)

    def _walk_banner_now(self) -> bool:
        return self._walk_banner_shown(self._ocr_text(self.capture_frame(), name="自动移动"))

    def _cancel_goddess_walk(self) -> bool:
        """Press the ✕ under "自动移动中" while two frames in a row show that
        banner; True once two reads no longer show it.  Without the banner the
        spot holds nothing of the walk, so nothing is pressed then."""

        for _attempt in range(AUTO_MOVE_CANCEL_ATTEMPTS):
            if not (self._walk_banner_now() and self._walk_banner_now()):
                break
            self.info_set("当前阶段", "取消卡住的自动移动")
            x, y = AUTO_MOVE_CANCEL_REFERENCE_POINT
            point = (x / REFERENCE_WIDTH, y / REFERENCE_HEIGHT)
            self.operate_click(*point, after_sleep=0.8)  # 不用确认：下面读横幅消失没有
        for _read in range(AUTO_MOVE_IDLE_READS):
            if self._walk_banner_now():
                return False
            self.sleep(0.3)
        return True

    def _wait_for_daily_navigation_to_disappear(
        self,
        timeout: float,
        interval: float = 0.5,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        absent_since = None
        while monotonic() <= end_at:
            frame = self.capture_frame()
            observation = self._observe_goddess_navigation(frame)
            prayer, _ = self._ocr_pattern_click_point(
                frame, GODDESS_PRAY_PATTERNS, name="许愿完成复核", roi=None
            )
            # Only after a wish press: the prompt and the goddess row both gone
            # for 2 s.  The square's bottom bar, or the 每日奖励 title of other
            # rows, need not show (player report 2026-10-20: wished, then the
            # tool stood there minutes and called it unfinished).
            if (
                observation.state not in ("ready", "ambiguous")
                and prayer is None
                and not is_loading_dark(frame)
            ):
                now = monotonic()
                if absent_since is not None and now - absent_since >= 2.0:
                    return True
                if absent_since is None:
                    absent_since = now
            else:
                absent_since = None
            self.sleep(interval)
        return False

    def _click_template_until(
        self,
        spec: TemplateSpec,
        timeout: float,
        name: str,
        target_offset_mf: tuple[int, int] = (0, 0),
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
                        window_samples=QUICK_SWITCH_STABLE_FRAMES,
                        minimum_hits=QUICK_SWITCH_STABLE_FRAMES,
                        sample_match=sample_match,
                        passes=lambda candidate: self._passes(candidate, spec),
                        sleep=self.sleep,
                        on_sample=lambda candidate: self.info_set(
                            name,
                            f"{candidate.score:.3f}/{candidate.pixel_score:.3f}",
                        ),
                    )
                    if stabilized is None:
                        # A see-through button over moving scenery (the
                        # restaurant's chefs walk behind 立刻前往游戏卡, clone
                        # 10-11) can miss one window: look again until timeout.
                        self.info_set(f"{name}稳定识别", "未形成稳定位置")
                        continue
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
                offset_x, offset_y = self._mf_offset_for_frame(
                    target_offset_mf[0],
                    target_offset_mf[1],
                    frame_width,
                    frame_height,
                )
                center_x, center_y = (
                    stable_center
                    if stable_center is not None
                    else (
                        result.position[0] + result.size[0] // 2,
                        result.position[1] + result.size[1] // 2,
                    )
                )
                x = center_x + offset_x
                y = center_y + offset_y
                self._click_client(x, y, frame_width, frame_height, after_sleep=after_sleep)
                return True
            self.sleep(interval)

        self.info_set(name, f"{last_score:.3f}")
        return False

    def _ocr_pattern_click_point(
        self,
        frame,
        patterns: list[str],
        name: str,
        roi: tuple[int, int, int, int] | None = None,
    ) -> tuple[tuple[int, int] | None, str]:
        left, top, _crop = self._roi_frame(frame, roi)
        boxes = self._ocr_boxes(frame, name=name, roi=roi)
        text = " ".join(getattr(box, "name", "") for box in boxes if getattr(box, "name", ""))
        # The walk banner may name the goal; it is not a prompt to press.
        matched_boxes = [
            box
            for box in boxes
            if self._matches_any(getattr(box, "name", ""), patterns)
            and not self._walk_banner_shown(getattr(box, "name", ""))
        ]
        if not matched_boxes:
            return None, text

        box = min(
            matched_boxes,
            key=lambda item: (
                float(getattr(item, "y", 0)),
                float(getattr(item, "x", 0)),
            ),
        )
        x = getattr(box, "x", None)
        y = getattr(box, "y", None)
        width = getattr(box, "width", None)
        height = getattr(box, "height", None)
        if None in (x, y, width, height):
            return None, text

        center_x = int(round(left + float(x) + float(width) / 2))
        center_y = int(round(top + float(y) + float(height) / 2))
        return (center_x, center_y), text

    def _observe_goddess_navigation(self, frame):
        try:
            observation = scan_navigation(
                frame, ocr=self.ocr, normalize=self._normalize_text,
                match=self._match, passes=self._passes,
                icon_specs=(SQUARE_DAILY_ICON_TEMPLATE, NEW_DAILY_ICON),
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            observation = NavigationObservation("unknown", f"识别异常：{exc}")
        self.info_set("广场每日导航", observation.state)
        self.info_set("广场导航文本 OCR", observation.text or "-")
        return observation

    def _wait_for_template(
        self,
        spec: TemplateSpec,
        timeout: float,
        name: str,
        interval: float = 0.35,
        arrival: bool = False,
    ) -> bool:
        if arrival:
            return self._wait_for_square_arrival(spec, name, interval, timeout)
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

    def _wait_for_square_arrival(
        self, spec: TemplateSpec, name: str, interval: float, timeout: float = STUCK_SECONDS
    ) -> bool:
        """The square after its cartridge is clicked.  Loading does not count
        as stuck, only a still screen that is not the square does (Leo
        2026-10-15 「我說的10秒是卡死 或者辨識不到」).  2K 10-15: the square
        came 11 s after the click and 「向女神像许愿」 was already up while its
        picture had not matched yet, so the wish prompt counts as arrived."""
        wait = load_wait(monotonic(), timeout, before=scene_at_press(self))
        last_score = -1.0
        while True:
            frame = self.capture_frame()
            result = self._match(frame, spec)
            last_score = result.score
            self.info_set(name, f"{result.score:.3f}")
            if self._passes(result, spec):
                return True
            loading = is_loading_dark(frame)
            if not loading:
                point, _text = self._ocr_pattern_click_point(
                    frame, GODDESS_PRAY_PATTERNS, name="女神像许愿", roi=None
                )
                if point is not None:
                    self.log_info("广场女神像：广场图没对上，但「向女神像许愿」已经在画面上，算已进入广场。")
                    return True
            if wait.over(frame, monotonic(), loading=loading):
                break
            self.sleep(interval)
        self.info_set(name, f"{last_score:.3f}")
        return False

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
                threshold=float(self.config.get("广场 OCR 阈值", 0.2)),
                target_height=720,
                log=False,
                name=name,
                reread=ocr_scale == 1.0,
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.info_set(f"{name} OCR 错误", str(exc))
            return []

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
    def _mf_point(x: int, y: int) -> tuple[int, int]:
        return (
            round(x * REFERENCE_WIDTH / HD720_REFERENCE_WIDTH),
            round(y * REFERENCE_HEIGHT / HD720_REFERENCE_HEIGHT),
        )

    @staticmethod
    def _mf_roi(x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
        left, top = SquareGoddessTask._mf_point(x, y)
        right, bottom = SquareGoddessTask._mf_point(x + width, y + height)
        return left, top, max(1, right - left), max(1, bottom - top)

    @staticmethod
    def _mf_offset_for_frame(
        x: int,
        y: int,
        frame_width: int,
        frame_height: int,
    ) -> tuple[int, int]:
        return (
            round(x * frame_width / HD720_REFERENCE_WIDTH),
            round(y * frame_height / HD720_REFERENCE_HEIGHT),
        )

    @staticmethod
    def _matches_any(text: str, patterns: list[str]) -> bool:
        normalized = SquareGoddessTask._normalize_text(text)
        for pattern in patterns:
            normalized_pattern = SquareGoddessTask._normalize_text(pattern)
            if re.search(normalized_pattern, normalized, flags=re.IGNORECASE):
                return True
        return False

    _normalize_text = staticmethod(normalize_ocr_text)
    @staticmethod
    def _roi_frame(
        frame: np.ndarray,
        roi: tuple[int, int, int, int] | None,
    ) -> tuple[int, int, np.ndarray]:
        return reference_roi_frame(frame, roi, (REFERENCE_WIDTH, REFERENCE_HEIGHT))

    @staticmethod
    def _crop_reference(frame, roi: tuple[int, int, int, int] | None):
        return reference_roi_frame(frame, roi, (REFERENCE_WIDTH, REFERENCE_HEIGHT))[2]

QUICK_SWITCH_TEMPLATE = TemplateSpec(
    name="quick_switch",
    file_name="image/green/QuickSwitchPlayIco.png",
    threshold_key="快速切换按钮阈值",
    default_threshold=0.88,
    relative_rois=QUICK_SWITCH_SEARCH_REGIONS,
    green_mask=True,
    scale_ratios=(0.95, 0.975, 1.0, 1.025, 1.05),
    min_pixel_score=0.85,
    minimum_safe_threshold=0.88,
    # 梦幻广场内的快捷切换按钮是白图标+深色圆底样式，与模板采样的浅色
    # 样式存在结构差异：1600x901 实机帧 zncc 最高 0.838（RPT-20260902-225925），
    # 0.85 门禁会确定性误拒；同帧误检位置 zncc 最高 0.43，0.78 仍有足够余量。
    min_zncc_score=0.78,
    # 2026-10-11, same HDR player as YES-BD2 #16: shape 0.964 / zncc 0.83 but
    # pixel 0.81 in the square, so the home click was never repeated.
    brightness_tolerant=True,
)

SQUARE_DAILY_ICON_TEMPLATE = TemplateSpec(
    name="square_daily_icon",
    file_name="image/Square_DailyIco.png",
    threshold_key="广场每日导航阈值",
    default_threshold=0.76,
    min_pixel_score=0.72,
)

GODDESS_PRAY_PATTERNS = [r"向女神像许愿|女神像许愿|许愿"]
