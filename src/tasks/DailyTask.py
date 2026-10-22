from time import monotonic
from types import SimpleNamespace

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
from src.utils.home_confirmation import (
    HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT,
    HOME_DIMMED_P95_THRESHOLD_DEFAULT,
)
from src.utils.ocr_utils import normalize_ocr_text
from src.utils.press_confirm import wait_for
from src.utils.wait_limits import LOADING_MAX_SECONDS, is_loading_dark, load_wait, scene_at_press

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

# 未加入公会时公会入口打开的是加入/创建页（win4090 bd2 会话 2026-10-22 实测
# OCR「申请列表 创建公会」）：没有可签到的公会，跳过而不是记为失败。
GUILD_NOT_JOINED_KEYWORDS = ["申请列表", "创建公会"]

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
GUILD_BACK_ATTEMPTS = 4
GUILD_BACK_LOOK_SECONDS = 2.0
GUILD_BACK_LAST_LOOK_SECONDS = 4.0
MY_HOME_ENTRY_REFERENCE_POINT = (166, 158)
MY_HOME_TITLE_RELATIVE_ROI = (0.11, 0.01, 0.25, 0.10)
MY_HOME_TITLE_OCR_RETRY_INTERVAL = 0.4
MY_HOME_ENTRY_CLICK_ATTEMPTS = 3
MY_HOME_ENTRY_RETRY_SECONDS = 4.0
BUSINESS_COLLECT_ENTRY_REFERENCE_POINT = (165, 260)
# How long a 经营管理 press waits for the popup before a lost press is redone.
BUSINESS_ENTRY_RETRY_SECONDS = 4.0
# Fallback only: closes the popup when 取消 is not read, and taps away an
# unrecognised reward overlay.
BUSINESS_COLLECT_CLOSE_REFERENCE_POINT = (832, 814)
# 一键获得 when its text is not read: x from the 10-10 problem-summary frame,
# y from 取消's row when read (Leo 2026-10-11, the fixed spot as last resort).
BUSINESS_COLLECT_CLAIM_REFERENCE_POINT = (1090, 814)
# Inside the button (about 235×47 at 1080p), for the press and the grey check.
BUSINESS_COLLECT_CLAIM_SPOT_SIZE = (160, 30)
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
# one is coloured or near white, and a black frame (no capture) is neither.
# The button is pressed either way; grey after a press with no reward means it
# was already collected today (Leo 2026-10-11).
BUSINESS_CLAIM_GREY_VALUE = (50.0, 175.0)
BUSINESS_CLAIM_GREY_MAX_SATURATION = 45.0
# The guild entry is looked for on a few frames (about 2 s, slow PCs) before
# it counts as absent; a match ends the looks at once.
GUILD_ENTRY_LOOKS = 5
GUILD_ENTRY_LOOK_SECONDS = 0.5
# A swallowed entry click leaves home up: only then is it pressed again.
GUILD_ENTRY_RETRY_SECONDS = 4.0
# Leo 2026-10-15: a 1080p run pressed the entry twice and home never changed
# (the player's second run went in; a lag, likely).  「先做補按加長 然後 多給一次
# 機會」: re-presses are held longer and there is one more of them.
GUILD_ENTRY_RETRIES = 2
GUILD_ENTRY_LONG_PRESS_SECONDS = 0.15
# A sub-step that clicked nothing on a confirmed home (no guild entry) is
# skipped, not failed.
STEP_SKIPPED = "skipped"
# The guild entry on home carries a red 「!」 at its top-right corner until the
# day's sign-in is done (guild.png / MainBotmUnionAcGE.png; the *finished*
# templates have none).  Player 2026-10-21 (v0.2.3/v0.2.4): with many popups
# on entry the guild was never entered yet the step said done, so a 「!」 still
# on home after the visit sends the step in once more.  Box share of the corner, and
# the share of red pixels there that counts as the mark (6% in guild.png,
# 25% in MainBotmUnionAcGE.png, 0 in both finished templates).
GUILD_MARK_CORNER = (0.55, 0.0, 1.0, 0.45)
GUILD_MARK_MIN_RED_SHARE = 0.03
# The 「!」 can clear a moment after home shows again.
GUILD_MARK_CLEAR_SECONDS = 3.0
# The sign-in reward panel can show a moment after the guild page: a marked
# entry stays on the page this long for it before going back.
GUILD_TOAST_LINGER_SECONDS = 3.0
# Sign-in words over a screen that is not the guild page belong to another
# popup (event login rewards say the same): tapped away, never taken as the
# sign-in, at most this often.
GUILD_POPUP_TAP_SECONDS = 1.5


class DailyTask(TaskVisionMixin, QuickHuntConfigMixin, BaseBD2Task):
    recover_home_on_failure = True
    start_from_home = True
    frozen_retry = True
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
        "公会入口红点",
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
    # Per sub-step: why it failed, and whether home was lost after it was done.
    _step_why = ""
    _home_lost_after_done = False

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
                'loading 消失等待秒数': LOADING_MAX_SECONDS,
                '公会签到成功等待秒数': 8.0,
                '小屋页面等待秒数': LOADING_MAX_SECONDS,
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
        self._why = ""
        steps = [
            ("公会签到", "执行公会签到", self.run_guild_sign_in),
            ("小屋签到", "执行小屋签到", self.run_my_home_sign_in),
            ("一键收菜", "执行一键收菜", self.run_business_collect),
        ]

        enabled = [name for name, key, _func in steps if bool(self.config.get(key, True))]
        success = []
        failed = []
        skipped = []
        # Why each failed step failed, for the 问题摘要: without it the
        # summary took the run's last log line, which belonged to a later
        # step (player 2026-10-17: 「失败：一键收菜：关闭经营管理弹窗」 while
        # 一键收菜 was done and 公会签到 had failed).
        reasons = {}
        stuck_after = ""
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
            self._step_why = ""
            self._home_lost_after_done = False
            result = self._run_step(name, func)
            # A failed step is tried once more from home (player 2026-10-12,
            # v0.1.24: right after 08:00 the game's announcement board
            # covered home under 公会/小屋 and all three steps failed).
            home_lost = False
            if not result:
                if self._wait_for_home_confirmation(f"{name}失败后主页确认", timeout=3.0):
                    self.log_info(f"{name}：没成功，已回到主页，再试一次。")
                    self._step_why = ""
                    self._home_lost_after_done = False
                    result = self._run_step(name, func)
                else:
                    home_lost = True
            if result == STEP_SKIPPED:
                skipped.append(name)
            elif result:
                success.append(name)
                if self._home_lost_after_done:
                    stop_remaining = True
                    stuck_after = name
                    self.log_info(f"{name} 完成后未能确认回到主页，停止剩余子任务。")
            else:
                failed.append(name)
                reasons[name] = self._step_why or "原因没有记录到，请看摘要里的游戏画面"
                # The steps are independent: only a game that is not back
                # on home stops the rest (finding 24).
                if name == enabled[-1]:
                    continue
                back_home = (
                    self._recover_home_after_failed_step(name)
                    if home_lost
                    else self._home_after_failed_step(name)
                )
                if not back_home:
                    stop_remaining = True
                    self.log_info(f"{name} 失败后未能确认回到主页，停止剩余子任务。")

        self.info_set("完成", str(success))
        self.info_set("失败", str(failed))
        self.info_set("跳过", str(skipped))
        whys = [f"{name}：{reasons[name]}" for name in failed]
        if stuck_after:
            whys.append(f"{stuck_after}做完后没能回到主页，后面的没做")
        if whys:
            self._why = "；".join(whys)
            self.info_set("状态", f"公会、小屋、酒馆失败：{self._why}。")
        else:
            self.info_set("状态", "公会、小屋、酒馆结束。")
        self.log_completion(
            f"公会、小屋、酒馆结束：完成={success}, 失败={failed}, 跳过={skipped}"
        )
        return not whys

    def _run_step(self, name: str, func):
        try:
            return func()
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.log_error(f"日常子任务失败：{name}", exc)
            return self._step_failed(f"程序出错（{exc}）")

    def _step_failed(self, why: str) -> bool:
        """Note why the running sub-step failed; the first reason wins."""
        if not getattr(self, "_step_why", ""):
            self._step_why = why
        return False

    def _home_after_done(self, name: str) -> bool:
        """The step's work is done but the back press did not show home.

        A step is judged on its own work (2K 桌面分身 2026-10-16 and a player
        2026-10-17: the sign-in had worked, then an event popup over home
        failed the home check and 公会签到 was reported failed).  Home is
        reached through the recovery flow, which closes popups; only when
        that fails too do the remaining steps stop.
        """
        self.log_info(f"{name}：已完成，但回主页时没认出主页（可能被弹窗挡住），走回主页流程。")
        if not recover_to_home(self):
            self._home_lost_after_done = True
            self.log_info(f"{name}：已完成，但没能回到主页。")
        return True

    def _home_after_failed_step(self, name: str) -> bool:
        """True once home is confirmed again after a failed sub-step.

        A step that clicked nothing left home up; one that ended on another
        page (a player without a guild lands on a join page) goes home first.
        """
        if self._wait_for_home_confirmation(f"{name}失败后主页确认", timeout=3.0):
            return True
        return self._recover_home_after_failed_step(name)

    def _recover_home_after_failed_step(self, name: str) -> bool:
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
            return self._step_failed("开始前不在主页（可能被弹窗挡住）")

        guild_ready, frame = self._find_guild_entry()
        if not guild_ready:
            self._status_set("公会判断", "未识别到公会入口")
            self._status_set("公会签到成功", "否")
            if self._frame_confirms_home(frame, "公会入口"):
                self.log_info("公会签到：未找到公会入口（可能未加入公会），跳过公会签到。")
                return STEP_SKIPPED
            self.log_info("公会签到：未检测到公会入口模板，且画面已不是主页，不点击公会按钮。")
            return self._step_failed("没认出公会入口，画面也不是主页")

        marked = self._guild_entry_marked(frame)
        self._status_set("公会入口红点", "有" if marked else "无")
        result = self._visit_guild(linger=bool(marked))
        if result is not True or not marked or self._home_lost_after_done:
            return result
        # Entering the guild page is the sign-in (Leo 2026-10-21 「進到公會就會
        # 算簽到成功」).  The 「!」 still on home after the visit means the page
        # was not really reached (popups): the guild is entered once more,
        # and the step stands on that visit seeing the guild page.
        if not self._guild_mark_stays():
            self.log_info("公会签到：主页公会图标的红色「!」已消失，签到完成。")
            return True
        self.log_info("公会签到：回到主页后公会图标的红色「!」还在，再进一次公会。")
        if not self._find_guild_entry()[0]:
            return self._step_failed("回到主页后公会图标的红色「!」还在，也没认出公会入口")
        return self._visit_guild(linger=True)

    def _guild_entry_marked(self, frame) -> bool | None:
        """Whether the guild entry shows its red 「!」; None when not seen."""
        if getattr(frame, "ndim", 0) < 3:
            return None
        match, spec = self._match_best(frame, GUILD_ENTRY_TEMPLATES)
        if not self._passes(match, spec):
            return None
        (x, y), (w, h) = match.position, match.size
        left, top, right, bottom = GUILD_MARK_CORNER
        height, width = frame.shape[:2]
        x0, x1 = max(0, int(x + w * left)), min(width, int(x + w * right))
        y0, y1 = max(0, int(y + h * top)), min(height, int(y + h * bottom))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return False
        hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:y1, x0:x1, :3]), cv2.COLOR_BGR2HSV)
        red = ((hsv[..., 0] <= 8) | (hsv[..., 0] >= 172)) & (hsv[..., 1] >= 150) & (
            hsv[..., 2] >= 150
        )
        return float(red.mean()) >= GUILD_MARK_MIN_RED_SHARE

    def _guild_mark_stays(self) -> bool:
        """True while home's guild entry still shows the 「!」 (or is not seen)."""
        end_at = monotonic() + GUILD_MARK_CLEAR_SECONDS
        while True:
            marked = self._guild_entry_marked(self.capture_frame())
            if marked is False:
                return False
            if monotonic() >= end_at:
                if marked is None:
                    self.log_info("公会签到：回到主页后没认出公会图标，无法确认签到。")
                return True
            self.sleep(0.5)

    def _visit_guild(self, linger: bool) -> bool | str:
        """Enter the guild page from home and come back.

        ``linger``: the entry was marked, so the sign-in panel is waited for
        briefly when the page shows first."""
        self._status_set("公会判断", "已识别入口，进入公会")
        self._sleep_after_recognition()
        seen = [None, ""]

        def on_guild_page():
            seen[:] = self._wait_guild_page(0.0)
            return seen[0]

        presses = []

        def press_entry():
            if presses:  # a re-press, held longer: a short click can be lost
                x, y = GUILD_SIGN_IN_ENTRY_REFERENCE_POINT
                self.operate_click(  # 不用确认：press_and_confirm 看公会页面
                    x / REFERENCE_WIDTH,
                    y / REFERENCE_HEIGHT,
                    down_time=GUILD_ENTRY_LONG_PRESS_SECONDS,
                    after_sleep=0.5,
                )
            else:
                self._click_reference(*GUILD_SIGN_IN_ENTRY_REFERENCE_POINT, after_sleep=0.5)  # 不用确认：同上
            presses.append(1)

        # A click the game swallowed leaves home up: only then press again.
        entered = self.press_and_confirm(
            "公会签到：公会入口",
            press_entry,
            on_guild_page,
            still_before=self._home_still_showing,
            timeout=GUILD_ENTRY_RETRY_SECONDS,
            retries=GUILD_ENTRY_RETRIES,
        )
        # Entering the guild page is the sign-in (user, 2026-09-27); the
        # 签到成功 toast only shows on the day's first visit, so waiting for it
        # cost ~15 s on every later run.  The page's fixed UI is the proof.
        state, text = seen if entered else self._wait_guild_page(
            float(self.config.get("loading 出现等待秒数", 6.0))
            + float(self.config.get("公会签到成功等待秒数", 8.0)),
            load=True,
        )
        self.info_set("公会签到 OCR", text or "-")
        if state == "not_joined":
            self._status_set("公会判断", "未加入公会")
            self._status_set("公会签到成功", "否")
            self.log_info("公会签到：打开的是加入/创建公会页面（未加入公会），跳过公会签到。")
            if not self._return_home_from_guild():
                return self._home_after_done("公会签到")
            return STEP_SKIPPED
        self._status_set("公会签到成功", "是" if state else "否")
        if state is None:
            self.log_info(
                f"公会签到：公会入口按了{len(presses)}次都没看到公会页面"
                "（游戏没反应或可能未加入公会），未签到。"
            )
            return self._step_failed(f"公会入口按了{len(presses)}次都没进入公会页面")
        if state == "toast":
            self.log_info("公会签到：检测到签到成功提示。")
            self._sleep_after_recognition()
            self._click_reference(
                *GUILD_SIGN_IN_SUCCESS_ACKNOWLEDGE_REFERENCE_POINT, after_sleep=0.5
            )
        elif linger and self._wait_guild_toast(GUILD_TOAST_LINGER_SECONDS):
            self.log_info("公会签到：进入公会页面后出现签到成功提示。")
        else:
            self.log_info("公会签到：已进入公会页面（今日签到提示已出现过或未弹出）。")
        # Entering the guild page is the sign-in: a popup over home on the
        # way back does not undo it.
        if not self._return_home_from_guild():
            return self._home_after_done("公会签到")
        return True

    def _wait_guild_toast(self, timeout: float) -> bool:
        """Wait on the guild page for the sign-in panel; tap it away when shown."""
        if not wait_for(
            lambda: self._wait_guild_page(0.0)[0] == "toast", timeout, sleep=self.sleep, poll=0.5
        ):
            return False
        self._sleep_after_recognition()
        self._click_reference(  # 不用确认：之后返回主页并看公会图标的「!」
            *GUILD_SIGN_IN_SUCCESS_ACKNOWLEDGE_REFERENCE_POINT, after_sleep=0.5
        )
        return True

    def _wait_guild_page(self, timeout: float, load: bool = False) -> tuple[str | None, str]:
        """"toast" (签到成功 shown), "page" (guild page UI), "not_joined" (the
        join/create page of an account without a guild) or None.

        The sign-in words count only over the guild page itself: event login
        popups use the same words (player 2026-10-21, many popups on entry:
        the step said done and the guild was never entered).  Such a popup
        is tapped away on a blank spot.

        ``load``: the page comes after the guild loading screen (load_wait)."""
        end_at = monotonic() + timeout
        wait = load_wait(monotonic(), timeout, before=scene_at_press(self)) if load else None
        text = ""
        while True:
            frame = self.capture_frame()
            text = self._ocr_text(frame, name="公会页面")
            page_hits = self._keyword_match_count(text, GUILD_PAGE_KEYWORDS)
            toast = self._keyword_match_count(text, GUILD_SUCCESS_KEYWORDS) >= 1
            if not page_hits and self._keyword_match_count(text, GUILD_NOT_JOINED_KEYWORDS) >= 2:
                return "not_joined", text
            if toast and page_hits >= 1:
                return "toast", text
            if page_hits >= 2:
                return "page", text
            if toast:
                self._tap_away_popup()
            if wait is not None:
                if wait.over(frame, monotonic(), loading=is_loading_dark(frame)):
                    return None, text
            elif monotonic() >= end_at:
                return None, text
            self.sleep(0.5)

    def _tap_away_popup(self) -> None:
        """Tap the blank spot under a popup that is not the guild page."""
        now = monotonic()
        last = getattr(self, "_popup_tapped_at", None)
        if last is not None and now - last < GUILD_POPUP_TAP_SECONDS:
            return
        self._popup_tapped_at = now
        # A popup the shared closer knows first (live 2K 2026-10-22: the
        # 公告 list over 主页 carries 签到 words; the blank spot is outside it
        # and the run stood still until stopped).
        if self.close_known_popup("公会签到", info_only=True):
            return
        self.log_info("公会签到：看到「签到成功」类文字但不是公会页面（别的弹窗），点空白处关掉。")
        self.operate_click(  # 不用确认：调用方接着看公会页面或主页
            *HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT, after_sleep=0.5
        )

    def _return_home_from_guild(self) -> bool:
        """Leave the guild page with bounded back-click retries.

        返回键点击可能被切页动画吞掉（BUG-20260901-02：单击定胜负让游戏
        滞留公会页面，本批与后续批次的公会任务全部失败）；主页确认失败且
        全帧 OCR 仍能读到公会页面关键字时才补点返回键，最多 4 次。

        桌面分身 1080p 2026-10-18: the first two presses right after the
        sign-in were both swallowed and each waited 4 s for home (11 s in
        all).  Home shows within 2 s once a press works, so the look after
        a press is 2 s; the last press keeps the 4 s look.
        """
        home_ok = False
        for attempt in range(1, GUILD_BACK_ATTEMPTS + 1):
            self._click_reference(*BACK_BUTTON_REFERENCE_POINT, after_sleep=1.0)
            last = attempt >= GUILD_BACK_ATTEMPTS
            look = GUILD_BACK_LAST_LOOK_SECONDS if last else GUILD_BACK_LOOK_SECONDS
            if self._wait_for_home_confirmation("公会签到返回主页", timeout=look):
                home_ok = True
                break
            if last:
                break
            text = self._ocr_text(self.capture_frame(), name="公会签到返回页面")
            if self._keyword_match_count(text, GUILD_PAGE_KEYWORDS) < 1:
                # Off the guild page but home not confirmed: an event popup
                # dims home (2K 桌面分身 2026-10-16: 万圣节每日钻石通行证 7-day
                # login popup covered the left column; the sign-in itself
                # had worked).  Tap the blank spot once, as for the login
                # notices, and look again.
                if not self.close_known_popup("公会签到返回主页", info_only=True):
                    self.log_info("公会签到：已离开公会页面，但主页被弹窗挡住，点空白处关掉再确认。")
                    self.operate_click(  # 不用确认：下一行看主页
                        *HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT, after_sleep=1.0
                    )
                home_ok = self._wait_for_home_confirmation("公会签到返回主页", timeout=4.0)
                break
            self.log_info(
                f"公会签到：第{attempt}次返回未生效（仍在公会页面），补点返回键。"
            )
        self._status_set("公会签到返回主页结果", "通过" if home_ok else "失败")
        return home_ok

    def _wait_my_home_page(self, timeout: float, load: bool = False) -> bool:
        """``load``: the page comes after the my-home loading (load_wait)."""
        vision = self._quick_vision()
        end_at = monotonic() + timeout
        wait = load_wait(monotonic(), timeout, before=scene_at_press(self)) if load else None
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
            if wait is not None:
                if wait.over(frame, monotonic(), loading=is_loading_dark(frame)):
                    return False
            elif monotonic() >= end_at:
                return False
            self.sleep(MY_HOME_TITLE_OCR_RETRY_INTERVAL)

    def run_my_home_sign_in(self) -> bool:
        if not self._wait_for_home_confirmation("小屋签到入口前主页确认"):
            return self._step_failed("开始前不在主页（可能被弹窗挡住）")

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
            # Leo 2026-10-14 「頂多等8秒到10秒」: was loading 6 + page 12 +
            # loading 35 s.  Leo 2026-10-15 「你單純等載入怎麼可以改成只等10秒」:
            # a load wait again, given up early only on a still screen.
            found = self._wait_my_home_page(
                float(self.config.get("小屋页面等待秒数", LOADING_MAX_SECONDS)), load=True
            )
        self._status_set("小屋页面检测", "是" if found else "否")
        if found:
            self.log_info("小屋签到：已进入小屋页面，返回主页。")
            self._sleep_after_recognition()
            self._click_reference(*BACK_BUTTON_REFERENCE_POINT, after_sleep=1.0)
        else:
            self.log_info("小屋签到：未确认小屋页面标题，不执行返回点击。")
            self._status_set("小屋签到返回主页结果", "未执行")
            return self._step_failed("点了小屋入口，没认出小屋页面")

        home_ok = self._wait_for_home_confirmation("小屋签到返回主页")
        self._status_set("小屋签到返回主页结果", "通过" if home_ok else "失败")
        if not home_ok:
            return self._home_after_done("小屋签到")
        return True

    def run_business_collect(self) -> bool:
        if not self._wait_for_home_confirmation("一键收菜入口前主页确认"):
            return self._step_failed("开始前不在主页（可能被弹窗挡住）")

        wait = float(self.config.get("一键收菜菜单等待秒数", 8.0))
        first_wait = min(wait, BUSINESS_ENTRY_RETRY_SECONDS)
        self._click_reference(*BUSINESS_COLLECT_ENTRY_REFERENCE_POINT, after_sleep=1.0)
        found, frame, boxes = self._wait_business_collect_popup(first_wait)
        # A click the game swallowed leaves home up: only then press again
        # (player 2026-10-12: one lost press on 经营管理 failed 一键收菜).
        if not found and self._home_still_showing():
            self.log_info("一键收菜：点了经营管理还在主页，再点一次。")
            self._click_reference(*BUSINESS_COLLECT_ENTRY_REFERENCE_POINT, after_sleep=1.0)
            found, frame, boxes = self._wait_business_collect_popup(
                max(first_wait, wait - first_wait)
            )
        elif not found and wait > first_wait:
            found, frame, boxes = self._wait_business_collect_popup(wait - first_wait)
        self.info_set("一键收菜 OCR", self._boxes_text(boxes) or "-")
        self._status_set("一键收菜弹窗", "是" if found else "否")
        if not found:
            self.log_info("一键收菜：未检测到经营管理弹窗关键字，跳过点击。")
            self._status_set("一键收菜返回主页结果", "未执行")
            return self._step_failed("点了经营管理，没认出经营管理弹窗")

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
        # Lit or grey, read or not, 一键获得 is pressed (Leo 2026-10-11 「灰的
        # 亮的 都要按」): a player's run left it lit (B站 渐崩渐晰, 结算营业额
        # missed with no failure), and pressing does nothing when it is grey.
        read = claim is not None
        if not read:
            claim = self._business_claim_spot(boxes, frame)
            self.log_info("一键收菜：没认到「一键获得」的字，照平常位置按一下。")
        self.sleep(0.5)
        self.log_info(
            "一键收菜：点击「一键获得」。"
            f"（按钮亮度 {self._business_claim_colour(frame, claim)}）"
        )
        # A lost click leaves the popup up, and closing it then looked
        # like a claim: only the reward overlay counts.
        claimed = self.press_and_confirm(
            "一键收菜：一键获得",
            lambda: self._click_ocr_box(claim, frame, after_sleep=0.5),
            self._business_reward_shown,
            still_before=(
                self._business_claim_still_offered if read else self._business_popup_shown
            ),
            timeout=BUSINESS_CLAIM_CONFIRM_SECONDS,
        ).confirmed
        if claimed:
            self._status_set("一键收菜结果", "已领取")
        else:
            after = self.capture_frame()
            if self._business_claim_greyed(after, claim):
                # Grey only once collected (Leo: 「如果是灰的 代表一定有點到」).
                claimed = True
                self.log_info(
                    "一键收菜：「一键获得」是灰的，今天已经领过。"
                    f"（按钮亮度 {self._business_claim_colour(after, claim)}）"
                )
                self._status_set("一键收菜结果", "按钮是灰的")
            else:
                self._status_set("一键收菜结果", "未确认领取")
                self.log_info(
                    "一键收菜：按了「一键获得」没看到领取结果，按钮也不是灰的，本次不算完成。"
                    f"（按钮亮度 {self._business_claim_colour(after, claim)}）"
                )
        self._settle_business_collect()
        home_ok = self._wait_for_home_confirmation("一键收菜返回主页")
        self._status_set("一键收菜返回主页结果", "通过" if home_ok else "失败")
        if not claimed:
            return self._step_failed("按了「一键获得」，没看到领取结果")
        if not home_ok:
            return self._home_after_done("一键收菜")
        return True

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

    def _business_claim_spot(self, boxes: list, frame):
        """A box where 一键获得 sits: right of 取消, in its row.

        10-10 problem-summary frame (1080p): 取消 at x≈834 and 一键获得 at
        x≈1091 in the same row; the row moves with the popup height.
        """
        height, width = frame.shape[:2]
        cancel = self._business_popup_box(boxes, frame, BUSINESS_COLLECT_CANCEL_TEXT)
        centre = self._ocr_box_center(cancel) if cancel is not None else None
        if centre is not None:
            y = centre[1]
        else:
            y = BUSINESS_COLLECT_CLAIM_REFERENCE_POINT[1] * height / REFERENCE_HEIGHT
        x = BUSINESS_COLLECT_CLAIM_REFERENCE_POINT[0] * width / REFERENCE_WIDTH
        half_w = BUSINESS_COLLECT_CLAIM_SPOT_SIZE[0] / 2 * width / REFERENCE_WIDTH
        half_h = BUSINESS_COLLECT_CLAIM_SPOT_SIZE[1] / 2 * height / REFERENCE_HEIGHT
        return SimpleNamespace(
            name=BUSINESS_COLLECT_CLAIM_TEXT,
            x=x - half_w,
            y=y - half_h,
            width=2 * half_w,
            height=2 * half_h,
        )

    def _business_popup_shown(self) -> bool:
        """The 经营管理 popup with nothing over it."""
        boxes = self._daily_ocr_boxes(self.capture_frame(), "business_collect")
        if self._first_box_with(boxes, OVERLAY_DISMISS_KEYWORDS) is not None:
            return False
        return self._keyword_match_count(self._boxes_text(boxes), BUSINESS_COLLECT_KEYWORDS) >= 2

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
