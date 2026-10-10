from time import monotonic

import cv2
import numpy as np
from ok.task.exceptions import FinishedException, TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.claim_page import CONFIRM_TEXT, OVERLAY_DISMISS_KEYWORDS, REWARD_DIALOG_TITLES
from src.tasks.map_trade.models import TemplateSpec
from src.tasks.quick_hunt import QuickHuntConfigMixin
from src.tasks.recovery import recover_to_home
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH, TaskVisionMixin
from src.utils.home_confirmation import HOME_DIMMED_P95_THRESHOLD_DEFAULT
from src.utils.ocr_utils import normalize_ocr_text

GUILD_TEMPLATE = TemplateSpec(
    name="guild",
    file_name="guild.png",
    threshold_key="公会入口阈值",
    default_threshold=0.78,
)

GUILD_MAIN_ACTIVE_TEMPLATE = TemplateSpec(
    name="guild_main_active",
    file_name="image/green/MainBotmUnionAcGE.png",
    threshold_key="公会入口阈值",
    default_threshold=0.78,
    green_mask=True,
)

GUILD_FINISHED_TEMPLATE = TemplateSpec(
    name="guild_finished",
    file_name="guild-finished.png",
    threshold_key="公会入口阈值",
    default_threshold=0.78,
)

GUILD_MAIN_FINISHED_TEMPLATE = TemplateSpec(
    name="guild_main_finished",
    file_name="image/green/MainBotmUnionGE.png",
    threshold_key="公会入口阈值",
    default_threshold=0.78,
    green_mask=True,
)

GUILD_ENTRY_TEMPLATES = (
    GUILD_TEMPLATE,
    GUILD_MAIN_ACTIVE_TEMPLATE,
    GUILD_FINISHED_TEMPLATE,
    GUILD_MAIN_FINISHED_TEMPLATE,
)

GUILD_SIGNUP_SUCCESS_TEMPLATE = TemplateSpec(
    name="guild_signup_success",
    file_name="guild-singup-success.png",
    threshold_key="公会签到成功阈值",
    default_threshold=0.76,
)

MY_HOME_TEMPLATE = TemplateSpec(
    name="my_home",
    file_name="my-home.png",
    threshold_key="小屋页面阈值",
    default_threshold=0.76,
)

# OCR 只识别简体中文（2026-08-29 用户决策，取消繁体识别），关键字按国服
# 简体客户端实际文案书写。公会签到第二词国服实测为「奖励已发放至邮箱」。
GUILD_SUCCESS_KEYWORDS = ["签到成功", "奖励已发放至邮箱"]

# 公会页面固定文案（左侧公告/按钮与右上商店，RPT-20260901-233554 实测整页
# OCR 均可读到），用于返回主页失败时判断是否仍滞留公会页。
GUILD_PAGE_KEYWORDS = ["公告事项", "进入公会联合战", "公会商店"]

# 经营管理弹窗实际文案（国服简体，BUG-20260829-011 实测转录）：
# 餐馆营业额现状/渔笼收获情况/助手工作情况/取消/一键获得。
BUSINESS_CLAIM_RECHECK_SECONDS = 2.5
BUSINESS_COLLECT_KEYWORDS = [
    "餐馆营业额现状",
    "渔笼收获情况",
    "助手工作情况",
    "取消",
    "一键获得",
]

# 以下点击点均为 1920×1080 参考（_click_reference 按当前客户区归一）。
GUILD_SIGN_IN_ENTRY_REFERENCE_POINT = (370, 155)
GUILD_SIGN_IN_SUCCESS_ACKNOWLEDGE_REFERENCE_POINT = (450, 650)
BACK_BUTTON_REFERENCE_POINT = (100, 50)
MY_HOME_ENTRY_REFERENCE_POINT = (166, 158)
MY_HOME_TITLE_RELATIVE_ROI = (0.11, 0.01, 0.25, 0.10)
MY_HOME_TITLE_OCR_RETRY_INTERVAL = 0.4
MY_HOME_ENTRY_CLICK_ATTEMPTS = 3
MY_HOME_ENTRY_RETRY_SECONDS = 4.0
BUSINESS_COLLECT_ENTRY_REFERENCE_POINT = (165, 260)
# Fallback only: closes the popup when 取消 is not read, and taps away an
# unrecognised reward overlay. 一键获得 itself is never clicked at a fixed
# point.
BUSINESS_COLLECT_CLOSE_REFERENCE_POINT = (832, 814)
# The popup's height grows with account progress, so its buttons move up and
# down: only the centre band is fixed, the vertical range stays generous.
BUSINESS_COLLECT_POPUP_ROI = (480, 80, 960, 980)
# The thin 一 is lost when the frame is read at 720p (live 1080p 2026-09-28:
# "键获得"), so the button is matched without it.
BUSINESS_COLLECT_CLAIM_TEXT = "键获得"
BUSINESS_COLLECT_CANCEL_TEXT = "取消"
# Bounded rounds for closing the reward overlay and the popup after claiming.
BUSINESS_COLLECT_SETTLE_ROUNDS = 8
BUSINESS_COLLECT_BLIND_TAPS = 2
# Only a reward overlay proves 一键获得 landed; looked for this long.
BUSINESS_CLAIM_CONFIRM_SECONDS = 4.0
# With nothing to collect the game still shows 一键获得, greyed out, and OCR
# reads its text about half the time (live clone 1080p 2026-10-10): pressing
# it gave no reward overlay and failed the step.  In that run's problem-summary
# thumbnails the grey button read brightness 84 / saturation 6-12 and the lit
# 取消 next to it 222 / 13.  A grey button is colourless and mid bright; a lit
# one is coloured or near white, and a black frame (no capture) is neither, so
# anything outside this band is pressed as before.
BUSINESS_CLAIM_GREY_VALUE = (50.0, 175.0)
BUSINESS_CLAIM_GREY_MAX_SATURATION = 45.0
# A popup still fading in is dim too, so grey counts only when a second frame
# this much later still shows it grey.
BUSINESS_CLAIM_GREY_RECHECK_SECONDS = 0.6
# The guild entry is looked for on a few frames before it counts as absent.
GUILD_ENTRY_LOOKS = 3
GUILD_ENTRY_LOOK_SECONDS = 0.5
# A swallowed entry click leaves home up: only then is it pressed again.
GUILD_ENTRY_RETRY_SECONDS = 4.0
# A sub-step that clicked nothing on a confirmed home (no guild entry) is
# skipped, not failed.
STEP_SKIPPED = "skipped"


class DailyTask(TaskVisionMixin, QuickHuntConfigMixin, BaseBD2Task):
    recover_home_on_failure = True
    start_from_home = True
    include_quick_hunt_config = False

    vision_threshold_key = "快速狩猎模板阈值"

    ocr_threshold_key = "日常 OCR 阈值"

    status_keys = [
        "启用",
        "状态",
        "当前任务",
        "执行公会签到",
        "公会判断",
        "公会入口",
        "公会入口模板",
        "公会入口阈值",
        "公会签到 loading 状态",
        "公会签到_loading_appear",
        "公会签到_loading_gone",
        "guild_sign_in_early 模板",
        "guild_sign_in 模板",
        "公会签到成功",
        "公会签到成功阈值",
        "公会签到 OCR",
        "公会签到返回主页 小屋按钮",
        "公会签到返回主页 亮度",
        "公会签到返回主页 抽抽乐 OCR",
        "公会签到返回主页结果",
        "执行小屋签到",
        "小屋签到 loading 状态",
        "小屋签到_loading_appear",
        "小屋签到_loading_gone",
        "my_home_early",
        "my_home",
        "小屋页面检测",
        "小屋页面阈值",
        "小屋签到返回主页 小屋按钮",
        "小屋签到返回主页 亮度",
        "小屋签到返回主页 抽抽乐 OCR",
        "小屋签到返回主页结果",
        "执行一键收菜",
        "business_collect 关键字",
        "一键收菜弹窗",
        "一键收菜 OCR",
        "一键收菜结果",
        "一键收菜结果 OCR",
        "一键收菜返回主页 小屋按钮",
        "一键收菜返回主页 亮度",
        "一键收菜返回主页 抽抽乐 OCR",
        "一键收菜返回主页结果",
        "加载页面阈值",
        "主页压暗阈值",
        "日常 OCR 阈值",
        "loading 出现等待秒数",
        "loading 消失等待秒数",
        "公会签到成功等待秒数",
        "小屋页面等待秒数",
        "一键收菜菜单等待秒数",
        "主页确认等待秒数",
        "完成",
        "失败",
        "跳过",
        "匹配错误",
        "Log",
        "Warning",
        "Error",
    ]

    status_key_labels = {
        "公会签到_loading_appear": "公会 loading 出现",
        "公会签到_loading_gone": "公会 loading 消失",
        "guild_sign_in_early 模板": "公会签到成功早期模板",
        "guild_sign_in 模板": "公会签到成功模板",
        "小屋签到_loading_appear": "小屋 loading 出现",
        "小屋签到_loading_gone": "小屋 loading 消失",
        "my_home_early": "小屋页面早期检测",
        "my_home": "小屋页面检测分数",
        "business_collect 关键字": "一键收菜关键字命中",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "公会、小屋、酒馆"
        self.description = "执行公会签到、小屋签到和酒馆一键收菜。"
        self.icon = FluentIcon.CAR
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.visible = True
        self._init_vision_state()
        self._install_quick_hunt_config()
        self.default_config.update(
            {
                '启用': True,
                '执行公会签到': True,
                '执行小屋签到': True,
                '执行一键收菜': True,
                '公会入口阈值': 0.78,
                '公会签到成功阈值': 0.76,
                '小屋页面阈值': 0.76,
                '加载页面阈值': 0.72,
                '主页压暗阈值': HOME_DIMMED_P95_THRESHOLD_DEFAULT,
                '日常 OCR 阈值': 0.2,
                'loading 出现等待秒数': 6.0,
                'loading 消失等待秒数': 35.0,
                '公会签到成功等待秒数': 8.0,
                '小屋页面等待秒数': 12.0,
                '一键收菜菜单等待秒数': 8.0,
                '主页确认等待秒数': 10.0,
            }
        )
        self.config_description.update(
            {
                '执行公会签到': "从主页进入公会，领取每日签到奖励。",
                '执行小屋签到': "从主页进入小屋，确认到达后返回主页。",
                '执行一键收菜': "打开经营管理弹窗并执行一键获得。",
            }
        )

    def run(self):
        if not bool(self.config.get("启用", True)):
            self.info_set("状态", "公会、小屋、酒馆已禁用。")
            self.log_info("公会、小屋、酒馆已禁用。")
            return True

        self.info_set("状态", "公会、小屋、酒馆启动。")
        steps = [
            ("公会签到", "执行公会签到", self.run_guild_sign_in),
            ("小屋签到", "执行小屋签到", self.run_my_home_sign_in),
            ("一键收菜", "执行一键收菜", self.run_business_collect),
        ]

        enabled = [name for name, key, _func in steps if bool(self.config.get(key, True))]
        success = []
        failed = []
        skipped = []
        stop_remaining = False
        for name, config_key, func in steps:
            if name not in enabled:
                skipped.append(name)
                continue
            if stop_remaining:
                skipped.append(name)
                continue

            self.info_set("当前任务", name)
            self.log_info(f"开始日常子任务：{name}")
            try:
                result = func()
            except (TaskDisabledException, FinishedException):
                raise
            except Exception as exc:
                result = False
                self.log_error(f"日常子任务失败：{name}", exc)
            if result == STEP_SKIPPED:
                skipped.append(name)
            elif result:
                success.append(name)
            else:
                failed.append(name)
                # The steps are independent: only a game that is not back
                # on home stops the rest (finding 24).
                if name != enabled[-1] and not self._home_after_failed_step(name):
                    stop_remaining = True
                    self.log_info(f"{name} 失败后未能确认回到主页，停止剩余子任务。")

        self.info_set("完成", str(success))
        self.info_set("失败", str(failed))
        self.info_set("跳过", str(skipped))
        self.info_set("状态", "公会、小屋、酒馆结束。")
        self.log_completion(
            f"公会、小屋、酒馆结束：完成={success}, 失败={failed}, 跳过={skipped}"
        )
        return not failed

    def _home_after_failed_step(self, name: str) -> bool:
        """True once home is confirmed again after a failed sub-step.

        A step that clicked nothing left home up; one that ended on another
        page (a player without a guild lands on a join page) goes home first.
        """
        if self._wait_for_home_confirmation(f"{name}失败后主页确认", timeout=3.0):
            return True
        self.log_info(f"{name}：失败后不在主页，先返回主页再继续。")
        return bool(recover_to_home(self))

    def _find_guild_entry(self):
        """Best guild entry match, looked for on a few frames."""
        for look in range(GUILD_ENTRY_LOOKS):
            if look:
                self.sleep(GUILD_ENTRY_LOOK_SECONDS)
            frame = self.capture_frame()
            guild, guild_spec = self._match_best(frame, GUILD_ENTRY_TEMPLATES)
            self.info_set("公会入口", f"{guild.score:.3f}")
            self.info_set("公会入口模板", guild_spec.file_name)
            if self._passes(guild, guild_spec):
                return True, frame
        return False, frame

    def run_guild_sign_in(self) -> bool | str:
        if not self._wait_for_home_confirmation("公会签到入口前主页确认"):
            return False

        guild_ready, frame = self._find_guild_entry()
        if not guild_ready:
            self._status_set("公会判断", "未识别到公会入口")
            self._status_set("公会签到成功", "否")
            if self._frame_confirms_home(frame, "公会入口"):
                self.log_info("公会签到：未找到公会入口（可能未加入公会），跳过公会签到。")
                return STEP_SKIPPED
            self.log_info("公会签到：未检测到公会入口模板，且画面已不是主页，不点击公会按钮。")
            return False

        self._status_set("公会判断", "已识别入口，进入公会")
        self._sleep_after_recognition()
        seen = [None, ""]

        def on_guild_page():
            seen[:] = self._wait_guild_page(0.0)
            return seen[0]

        # A click the game swallowed leaves home up: only then press again.
        entered = self.press_and_confirm(
            "公会签到：公会入口",
            lambda: self._click_reference(*GUILD_SIGN_IN_ENTRY_REFERENCE_POINT, after_sleep=0.5),
            on_guild_page,
            still_before=self._home_still_showing,
            timeout=GUILD_ENTRY_RETRY_SECONDS,
        )
        # Entering the guild page is the sign-in (user, 2026-09-27); the
        # 签到成功 toast only shows on the day's first visit, so waiting for it
        # cost ~15 s on every later run.  The page's fixed UI is the proof.
        state, text = seen if entered else self._wait_guild_page(
            float(self.config.get("loading 出现等待秒数", 6.0))
            + float(self.config.get("公会签到成功等待秒数", 8.0))
        )
        self.info_set("公会签到 OCR", text or "-")
        self._status_set("公会签到成功", "是" if state else "否")
        if state is None:
            self.log_info("公会签到：点了公会入口但没看到公会页面（可能未加入公会），未签到。")
            return False
        if state == "toast":
            self.log_info("公会签到：检测到签到成功提示。")
            self._sleep_after_recognition()
            self._click_reference(
                *GUILD_SIGN_IN_SUCCESS_ACKNOWLEDGE_REFERENCE_POINT, after_sleep=0.5
            )
        else:
            self.log_info("公会签到：已进入公会页面（今日签到提示已出现过或未弹出）。")
        return self._return_home_from_guild()

    def _wait_guild_page(self, timeout: float) -> tuple[str | None, str]:
        """"toast" (签到成功 shown), "page" (guild page UI) or None."""
        end_at = monotonic() + timeout
        text = ""
        while True:
            text = self._ocr_text(self.capture_frame(), name="公会页面")
            if self._keyword_match_count(text, GUILD_SUCCESS_KEYWORDS) >= 1:
                return "toast", text
            if self._keyword_match_count(text, GUILD_PAGE_KEYWORDS) >= 2:
                return "page", text
            if monotonic() >= end_at:
                return None, text
            self.sleep(0.5)

    def _return_home_from_guild(self) -> bool:
        """Leave the guild page with bounded back-click retries.

        返回键点击可能被切页动画吞掉（BUG-20260901-02：单击定胜负让游戏
        滞留公会页面，本批与后续批次的公会任务全部失败）；主页确认失败且
        全帧 OCR 仍能读到公会页面关键字时才补点返回键，最多 3 次。
        """
        home_ok = False
        for attempt in range(1, 4):
            self._click_reference(*BACK_BUTTON_REFERENCE_POINT, after_sleep=1.0)
            if self._wait_for_home_confirmation("公会签到返回主页", timeout=4.0):
                home_ok = True
                break
            if attempt >= 3:
                break
            text = self._ocr_text(self.capture_frame(), name="公会签到返回页面")
            if self._keyword_match_count(text, GUILD_PAGE_KEYWORDS) < 1:
                self.log_info("公会签到：返回后未见公会页面关键字，不再补点返回键。")
                break
            self.log_info(
                f"公会签到：第{attempt}次返回未生效（仍在公会页面），补点返回键。"
            )
        self._status_set("公会签到返回主页结果", "通过" if home_ok else "失败")
        return home_ok

    def _wait_my_home_page(self, timeout: float) -> bool:
        vision = self._quick_vision()
        end_at = monotonic() + timeout
        while True:
            frame = self.capture_frame()
            result = self._match(frame, MY_HOME_TEMPLATE)
            self.info_set("my_home", f"{result.score:.3f}")
            if self._passes(result, MY_HOME_TEMPLATE):
                return True
            title = vision.ocr_text(
                frame,
                "小屋页面标题",
                relative_roi=MY_HOME_TITLE_RELATIVE_ROI,
                target_height=0,
                ocr_scale=2.0,
            )
            if self._keyword_match_count(title, ["我的小屋"]) >= 1:
                return True
            if monotonic() >= end_at:
                return False
            self.sleep(MY_HOME_TITLE_OCR_RETRY_INTERVAL)

    def run_my_home_sign_in(self) -> bool:
        if not self._wait_for_home_confirmation("小屋签到入口前主页确认"):
            return False

        # The my-home.png template scores -1 at 4K, so waiting for it first
        # cost ~19 s per run (live 2026-09-27); the page title is read on
        # every poll instead, and whichever matches first ends the wait.
        found = False
        for attempt in range(1, MY_HOME_ENTRY_CLICK_ATTEMPTS + 1):
            self._click_reference(*MY_HOME_ENTRY_REFERENCE_POINT, after_sleep=0.5)
            found = self._wait_my_home_page(MY_HOME_ENTRY_RETRY_SECONDS)
            # A click the game swallowed leaves the home screen up: only then
            # click again; anything else (loading) gets the full wait below.
            if found or not self._home_still_showing():
                break
            if attempt < MY_HOME_ENTRY_CLICK_ATTEMPTS:
                self.log_info("小屋签到：入口点击后仍在主页，重试点击。")
        if not found:
            found = self._wait_my_home_page(
                float(self.config.get("loading 出现等待秒数", 6.0))
                + float(self.config.get("小屋页面等待秒数", 12.0))
                + float(self.config.get("loading 消失等待秒数", 35.0))
            )
        self._status_set("小屋页面检测", "是" if found else "否")
        if found:
            self.log_info("小屋签到：已进入小屋页面，返回主页。")
            self._sleep_after_recognition()
            self._click_reference(*BACK_BUTTON_REFERENCE_POINT, after_sleep=1.0)
        else:
            self.log_info("小屋签到：未确认小屋页面标题，不执行返回点击。")
            self._status_set("小屋签到返回主页结果", "未执行")
            return False

        home_ok = self._wait_for_home_confirmation("小屋签到返回主页")
        self._status_set("小屋签到返回主页结果", "通过" if home_ok else "失败")
        return home_ok

    def run_business_collect(self) -> bool:
        if not self._wait_for_home_confirmation("一键收菜入口前主页确认"):
            return False

        self._click_reference(*BUSINESS_COLLECT_ENTRY_REFERENCE_POINT, after_sleep=1.0)
        found, frame, boxes = self._wait_business_collect_popup(
            float(self.config.get("一键收菜菜单等待秒数", 8.0))
        )
        self.info_set("一键收菜 OCR", self._boxes_text(boxes) or "-")
        self._status_set("一键收菜弹窗", "是" if found else "否")
        if not found:
            self.log_info("一键收菜：未检测到经营管理弹窗关键字，跳过点击。")
            self._status_set("一键收菜返回主页结果", "未执行")
            return False

        claim = self._business_popup_box(boxes, frame, BUSINESS_COLLECT_CLAIM_TEXT)
        # The keyword gate can pass while the popup is still fading in (live
        # 1080p 2026-09-28: the read still showed the home screen), so look
        # again briefly before deciding there is nothing to collect.
        end_at = monotonic() + BUSINESS_CLAIM_RECHECK_SECONDS
        while claim is None and monotonic() < end_at:
            self.sleep(0.4)
            again = self.capture_frame()
            again_boxes = self._daily_ocr_boxes(again, "business_collect")
            if (
                self._keyword_match_count(self._boxes_text(again_boxes), BUSINESS_COLLECT_KEYWORDS)
                < 2
            ):
                continue
            frame, boxes = again, again_boxes
            claim = self._business_popup_box(boxes, frame, BUSINESS_COLLECT_CLAIM_TEXT)
        claimed = True
        if claim is not None and self._business_claim_greyed(frame, claim):
            self.sleep(BUSINESS_CLAIM_GREY_RECHECK_SECONDS)
            again = self.capture_frame()
            again_boxes = self._daily_ocr_boxes(again, "business_collect")
            again_claim = self._business_popup_box(again_boxes, again, BUSINESS_COLLECT_CLAIM_TEXT)
            # A missed read keeps the box: the button does not move.
            frame = again
            if again_claim is not None:
                boxes, claim = again_boxes, again_claim
        if claim is None:
            self.log_info("一键收菜：弹窗内未识别到「一键获得」按钮，视为无可收取，关闭弹窗。")
            self._status_set("一键收菜结果", "未找到一键获得")
            self._close_business_popup(boxes, frame)
        elif self._business_claim_greyed(frame, claim):
            self.log_info(
                "一键收菜：「一键获得」是灰的，视为无可收取，关闭弹窗。"
                f"（按钮亮度 {self._business_claim_colour(frame, claim)}）"
            )
            self._status_set("一键收菜结果", "按钮是灰的")
            self._close_business_popup(boxes, frame)
        else:
            self.sleep(0.5)
            self.log_info(
                "一键收菜：点击 OCR 识别到的「一键获得」。"
                f"（按钮亮度 {self._business_claim_colour(frame, claim)}）"
            )
            # A lost click leaves the popup up, and closing it then looked
            # like a claim: only the reward overlay counts.
            claimed = self.press_and_confirm(
                "一键收菜：一键获得",
                lambda: self._click_ocr_box(claim, frame, after_sleep=0.5),
                self._business_reward_shown,
                still_before=self._business_claim_still_offered,
                timeout=BUSINESS_CLAIM_CONFIRM_SECONDS,
            ).confirmed
            if claimed:
                self._status_set("一键收菜结果", "已领取")
            else:
                self._status_set("一键收菜结果", "未确认领取")
                self.log_info("一键收菜：按了「一键获得」没看到领取结果，本次不算完成。")
            self._settle_business_collect()
        home_ok = self._wait_for_home_confirmation("一键收菜返回主页")
        self._status_set("一键收菜返回主页结果", "通过" if home_ok else "失败")
        return home_ok and claimed

    @staticmethod
    def _business_claim_colour(frame, box) -> tuple[float, float] | None:
        """Median (brightness, saturation) of the button under an OCR box."""
        if frame is None or box is None or getattr(frame, "ndim", 0) != 3:
            return None
        height, width = frame.shape[:2]
        x0, y0 = max(0, int(box.x)), max(0, int(box.y))
        x1 = min(width, int(box.x + box.width))
        y1 = min(height, int(box.y + box.height))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:y1, x0:x1, :3]), cv2.COLOR_BGR2HSV)
        return round(float(np.median(hsv[..., 2])), 1), round(float(np.median(hsv[..., 1])), 1)

    def _business_claim_greyed(self, frame, box) -> bool:
        colour = self._business_claim_colour(frame, box)
        if colour is None:
            return False
        value, saturation = colour
        low, high = BUSINESS_CLAIM_GREY_VALUE
        return low <= value <= high and saturation <= BUSINESS_CLAIM_GREY_MAX_SATURATION

    def _business_reward_shown(self) -> bool:
        """The reward overlay that a landed 一键获得 opens."""
        boxes = self._daily_ocr_boxes(self.capture_frame(), "一键收菜结果")
        if self._first_box_with(boxes, OVERLAY_DISMISS_KEYWORDS) is not None:
            return True
        return self._keyword_match_count(self._boxes_text(boxes), list(REWARD_DIALOG_TITLES)) >= 1

    def _business_claim_still_offered(self) -> bool:
        """The popup with its 一键获得 still up and nothing over it."""
        frame = self.capture_frame()
        boxes = self._daily_ocr_boxes(frame, "business_collect")
        if self._first_box_with(boxes, OVERLAY_DISMISS_KEYWORDS) is not None:
            return False
        if self._keyword_match_count(self._boxes_text(boxes), BUSINESS_COLLECT_KEYWORDS) < 2:
            return False
        return self._business_popup_box(boxes, frame, BUSINESS_COLLECT_CLAIM_TEXT) is not None

    def _home_still_showing(self, looks: int = 2) -> bool:
        """Home on ``looks`` frames in a row, read only (never clicks)."""
        for look in range(looks):
            if look:
                self.sleep(0.35)
            if not self._home_confirmation_signals(self.capture_frame(), "入口重试 抽抽乐")[0]:
                return False
        return True

    def _daily_ocr_boxes(self, frame, name: str) -> list:
        """Full-frame OCR boxes (client coordinates) with the daily threshold."""
        try:
            boxes = self.ocr(
                frame=frame,
                threshold=float(self.config.get("日常 OCR 阈值", 0.2)),
                target_height=720,
                log=False,
                name=name,
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.info_set(f"{name} OCR 错误", str(exc))
            return []
        return list(boxes)

    @staticmethod
    def _boxes_text(boxes: list) -> str:
        return " ".join(str(getattr(box, "name", "")) for box in boxes if getattr(box, "name", ""))

    def _wait_business_collect_popup(self, timeout: float) -> tuple[bool, object, list]:
        # Same keyword gate as before, but keep the boxes so the buttons can
        # be clicked where OCR actually found them.
        end_at = monotonic() + max(0.0, timeout)
        while True:
            frame = self.capture_frame()
            boxes = self._daily_ocr_boxes(frame, "business_collect")
            count = self._keyword_match_count(self._boxes_text(boxes), BUSINESS_COLLECT_KEYWORDS)
            self.info_set("business_collect 关键字", f"{count}/{len(BUSINESS_COLLECT_KEYWORDS)}")
            if count >= 2:
                return True, frame, boxes
            if monotonic() >= end_at:
                return False, frame, boxes
            self.sleep(0.5)

    def _business_popup_box(self, boxes: list, frame, keyword: str):
        """First box containing ``keyword`` whose centre lies inside the popup."""
        height, width = frame.shape[:2]
        left, top, roi_width, roi_height = BUSINESS_COLLECT_POPUP_ROI
        wanted = normalize_ocr_text(keyword)
        for box in boxes:
            if wanted not in normalize_ocr_text(getattr(box, "name", "")):
                continue
            center = self._ocr_box_center(box)
            if center is None:
                continue
            x = center[0] * REFERENCE_WIDTH / max(1, width)
            y = center[1] * REFERENCE_HEIGHT / max(1, height)
            if left <= x <= left + roi_width and top <= y <= top + roi_height:
                return box
        return None

    def _click_ocr_box(self, box, frame, after_sleep: float = 0.0) -> None:
        # Boxes are in the pixels of the frame they were read from.
        center = self._ocr_box_center(box)
        if center is None:
            return
        height, width = frame.shape[:2]
        self.operate_click(
            max(0.0, min(1.0, center[0] / max(1, width))),
            max(0.0, min(1.0, center[1] / max(1, height))),
            after_sleep=after_sleep,
        )

    def _close_business_popup(self, boxes: list, frame) -> None:
        cancel = self._business_popup_box(boxes, frame, BUSINESS_COLLECT_CANCEL_TEXT)
        if cancel is not None:
            self._click_ocr_box(cancel, frame, after_sleep=1.0)
            return
        self.log_info("一键收菜：未识别到「取消」，点击原关闭位置。")
        self._click_reference(*BUSINESS_COLLECT_CLOSE_REFERENCE_POINT, after_sleep=1.0)

    @staticmethod
    def _first_box_with(boxes: list, keywords) -> object | None:
        for keyword in keywords:
            wanted = normalize_ocr_text(keyword)
            for box in boxes:
                if wanted and wanted in normalize_ocr_text(getattr(box, "name", "")):
                    return box
        return None

    def _settle_business_collect(self) -> None:
        """Dismiss the reward overlay, then close the popup, by OCR-found controls."""
        blind_taps = 0
        unknown_frames = 0
        for _round in range(BUSINESS_COLLECT_SETTLE_ROUNDS):
            frame = self.capture_frame()
            boxes = self._daily_ocr_boxes(frame, "一键收菜结果")
            text = self._boxes_text(boxes)
            self.info_set("一键收菜结果 OCR", text[:120] or "-")

            dismiss = self._first_box_with(boxes, OVERLAY_DISMISS_KEYWORDS)
            if dismiss is not None:
                self.log_info(f"一键收菜：关闭奖励弹窗（{getattr(dismiss, 'name', '')}）。")
                self._click_ocr_box(dismiss, frame, after_sleep=1.0)
                unknown_frames = 0
                continue
            if self._keyword_match_count(text, list(REWARD_DIALOG_TITLES)) >= 1:
                confirm = self._first_box_with(boxes, (CONFIRM_TEXT,))
                if confirm is not None:
                    self.log_info("一键收菜：确认奖励弹窗。")
                    self._click_ocr_box(confirm, frame, after_sleep=1.0)
                    unknown_frames = 0
                    continue
            if self._keyword_match_count(text, BUSINESS_COLLECT_KEYWORDS) >= 2:
                # Popup still open (or a reward overlay above it, which a tap
                # on 取消 closes as well): press its 取消.
                self.log_info("一键收菜：关闭经营管理弹窗。")
                self._close_business_popup(boxes, frame)
                unknown_frames = 0
                continue
            if self._frame_confirms_home(frame, "一键收菜结果"):
                return
            unknown_frames += 1
            if unknown_frames >= 2:
                if blind_taps >= BUSINESS_COLLECT_BLIND_TAPS:
                    return
                # Unrecognised overlay: fall back to the tap the old flow made.
                self.log_info("一键收菜：出现未识别弹窗，点击原关闭位置。")
                self._click_reference(*BUSINESS_COLLECT_CLOSE_REFERENCE_POINT, after_sleep=1.0)
                blind_taps += 1
                unknown_frames = 0
                continue
            self.sleep(0.5)
