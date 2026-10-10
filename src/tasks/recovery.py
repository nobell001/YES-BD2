"""Best-effort return to the home screen after a failed daily-batch child.

A failed child used to stop the whole batch, so one flaky page skipped every
later daily.  Recovery first lets the map navigator handle the screens it
knows (sandbox, shop, map pages, loading), then closes dialogs through their
own cancel/close text, and finally presses the top-left back arrow, which
closes every home sub-page.  All steps are bounded; when home cannot be
confirmed the batch stops as before.
"""

from __future__ import annotations

import re
from time import monotonic

import numpy as np
from ok.task.exceptions import FinishedException, TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.claim_page import OVERLAY_DISMISS_KEYWORDS, REWARD_DIALOG_TITLES
from src.tasks.map_trade.models import ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils.home_confirmation import HOME_LEFT_COLUMN_REQUIRED_HITS
from src.utils.ocr_utils import fuzzy_substring_match, normalize_ocr_text

RECOVERY_ATTEMPTS = 6
UNKNOWN_SETTLE_SECONDS = 1.0
# After a back press, poll the cheap home check this long.
BACK_HOME_POLL_SECONDS = 1.5
# A slow PC showed home after 1.5 s; the next back press then landed on home
# and opened the field map.  Wait up to this long, unless the screen has
# already settled on another page.
BACK_HOME_WAIT_SECONDS = 4.5
# Mean grey difference (on a 1/8 thumbnail) that counts as a new screen.
FRAME_CHANGE_MIN_DIFF = 8.0
BACK_BUTTON_POINT = (150 / REFERENCE_WIDTH, 50 / REFERENCE_HEIGHT)
# Loading between pages is black with a faint logo (p99 grey ~40 live);
# every real page has bright UI text.
TRANSITION_P99_MAX = 70.0
TRANSITION_WAIT_SECONDS = 20.0
# Top-left page title beside the back arrow ("活动", "通行证", "装备"...).
PAGE_TITLE_RELATIVE_ROI = (225 / REFERENCE_WIDTH, 15 / REFERENCE_HEIGHT, 650 / REFERENCE_WIDTH, 85 / REFERENCE_HEIGHT)
NAVIGATOR_STATES = frozenset(
    {
        ScreenState.SANDBOX,
        ScreenState.SHOP,
        ScreenState.AREA_MAP,
        ScreenState.SANDBOX_MAP,
        ScreenState.LOADING,
    }
)
# Buttons that only ever close a dialog, never confirm a spend.
DISMISS_TEXTS = ("点击画面即可返回", "取消", "关闭")
# Info-only dialogs whose 确认 just closes them: 确认 is pressed only while
# one of these titles is on the same frame (never a purchase confirm).
CONFIRM_ONLY_TITLES = REWARD_DIALOG_TITLES + (
    "恭喜晋级",
    "段位下滑",
    "奖励已发放至背包",
    "奖励已通过邮件发放",
)
CONFIRM_TEXT = "确认"
# The game went back to its title screen (08:00 reset, disconnect, restart).
TITLE_SCREEN_TEXTS = ("touchtostart",)
# OCR misreads like "T0UCH TO STAR" missed the title: tolerant match.
TITLE_SCREEN_FUZZY_RATIO = 0.8


def _handle_dialog(task, vision: Vision) -> str:
    """Close one known dialog: "dismissed", "title" (title screen) or "none"."""

    frame = task.capture_frame()
    height, width = frame.shape[:2]
    boxes = vision.ocr_boxes(frame, "恢复主页弹窗")
    named = [(normalize_ocr_text(getattr(box, "name", "")), box) for box in boxes]
    text = "".join(name for name, _box in named)
    alnum = normalize_ocr_text(text, alnum_only=True)
    if any(
        fuzzy_substring_match(alnum, title, TITLE_SCREEN_FUZZY_RATIO)
        for title in TITLE_SCREEN_TEXTS
    ):
        return "title"

    target, label = None, ""
    for keyword in DISMISS_TEXTS:
        wanted = normalize_ocr_text(keyword)
        target = next((box for name, box in named if name == wanted), None)
        if target is not None:
            label = keyword
            break
    if target is None:
        overlays = tuple(normalize_ocr_text(keyword) for keyword in OVERLAY_DISMISS_KEYWORDS)
        target = next(
            (box for name, box in named if any(keyword in name for keyword in overlays)), None
        )
        label = "点击画面返回"
    if target is None and any(normalize_ocr_text(title) in text for title in CONFIRM_ONLY_TITLES):
        target = next((box for name, box in named if name == CONFIRM_TEXT), None)
        label = CONFIRM_TEXT
    if target is None:
        return "none"
    center = task._ocr_box_center(target)
    if center is None:
        return "none"
    task.log_info(f"恢复主页：点击「{label}」关闭弹窗。")
    task.operate_click(center[0] / width, center[1] / height, after_sleep=1.0)
    return "dismissed"


def _rearm_auto_login(task) -> bool:
    """Let the login trigger run again; True when it is enabled."""

    try:
        from src.tasks.trigger.AutoLoginTask import AutoLoginTask

        login = task.executor.get_task_by_class(AutoLoginTask)
    except Exception:
        return False
    if login is None or not bool(getattr(login, "_enabled", False)):
        return False
    if getattr(login, "_finished", False):
        login._reset_login_state("游戏回到了标题画面，重新自动登录。")
    return True


def _home_now(navigator) -> bool:
    """The left-column home check (~0.06 s), not the ~0.8 s classification."""

    signals = getattr(navigator, "_home_confirmation_signals", None)
    vision = getattr(navigator, "vision", None)
    if signals is None or vision is None:
        return False
    return bool(signals(vision.capture())[0])


def _wait_home_briefly(task, navigator, timeout: float) -> bool:
    end_at = monotonic() + timeout
    while True:
        if _home_now(navigator):
            return True
        if monotonic() >= end_at:
            return False
        task.sleep(0.3)


def _thumb(frame):
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    return frame[::8, ::8, :3].mean(axis=2)


def _frames_differ(first, second) -> bool:
    if first is None or second is None or first.shape != second.shape:
        return False
    return float(np.abs(first - second).mean()) >= FRAME_CHANGE_MIN_DIFF


def _wait_after_back(task, navigator, before) -> bool:
    """After a back press: True on home; False once another page has settled.

    Returns as soon as home shows; a screen that changed from the pre-press
    frame and then held still for 2 looks is a sub-page, so the next press
    need not wait the full time.
    """

    before_thumb = _thumb(before)
    end_at = monotonic() + BACK_HOME_WAIT_SECONDS
    last = None
    settled = 0
    while True:
        if _home_now(navigator):
            return True
        if monotonic() >= end_at:
            return False
        current = _thumb(navigator.vision.capture())
        changed = (
            _frames_differ(before_thumb, current)
            and float(np.percentile(current, 99)) >= TRANSITION_P99_MAX
        )
        still = last is not None and current is not None and not _frames_differ(last, current)
        settled = settled + 1 if changed and still else 0
        if settled >= 2:
            return False
        last = current
        task.sleep(0.3)


def _transition_frame(frame) -> bool:
    """Nearly black: the loading screen between pages (only a faint logo)."""

    if frame is None or frame.size == 0:
        return False
    gray = frame[:, :, :3].mean(axis=2)
    return float(np.percentile(gray, 99)) < TRANSITION_P99_MAX


def _wait_transition(task, navigator) -> bool:
    """Wait out a black transition; True once it ended (any screen)."""

    end_at = monotonic() + TRANSITION_WAIT_SECONDS
    task.info_set("恢复主页", "等待画面切换")
    while monotonic() < end_at:
        task.sleep(0.5)
        if not _transition_frame(navigator.vision.capture()):
            return True
    return False


def in_game_page(task) -> bool:
    """The game is past login: home, a field/shop/map, or a titled page.

    Starting the daily batch on, say, the event page left it waiting for an
    auto-login that never came (live 2026-09-29): login screens have none of
    these, so recovery may take such a frame home instead.
    """

    vision = Vision(task)
    navigator = Navigator(task, vision)
    frame = vision.capture()
    if frame is None or _transition_frame(frame):
        return False
    confirmed, left_hits, _p95, _gacha = navigator._home_confirmation_signals(frame)
    # Home itself, or home dimmed under a dialog (一键收菜 left open by a
    # stopped run): the left-column labels still read through the dimming.
    if confirmed or left_hits >= HOME_LEFT_COLUMN_REQUIRED_HITS:
        return True
    if navigator.classify(frame) in NAVIGATOR_STATES - {ScreenState.LOADING}:
        return True
    title = vision.ocr_text(frame, "页面标题", relative_roi=PAGE_TITLE_RELATIVE_ROI)
    task.info_set("页面标题 OCR", title or "-")
    return bool(re.search(r"[一-鿿]{2,}", str(title)))


def recover_to_home(task, attempts: int = RECOVERY_ATTEMPTS) -> bool:
    """Try to bring the game back to the confirmed home screen."""
    vision = Vision(task)
    navigator = Navigator(task, vision)
    task._recovery_saw_title = False
    for attempt in range(1, attempts + 1):
        if _home_now(navigator):
            return True
        if attempt == 1:
            _note_leaving_step(task, navigator)
        state = navigator.classify()
        task.info_set("恢复主页", f"第{attempt}次：{state.value}")
        if state == ScreenState.HOME:
            return True
        if state in NAVIGATOR_STATES:
            try:
                if navigator.return_home().success:
                    return True
            except (TaskDisabledException, FinishedException):
                raise
            except Exception as exc:  # navigator paths assume trade context
                task.log_warning(f"恢复主页：导航返回失败：{exc}")
            continue
        outcome = _handle_dialog(task, vision)
        if outcome == "title":
            # Clicking here does nothing useful; auto-login takes over.
            task._recovery_saw_title = True
            rearmed = _rearm_auto_login(task)
            task.log_warning(
                "恢复主页：游戏回到了标题画面"
                + ("，交给自动登录。" if rearmed else "，请手动登录。"),
                notify=True,
            )
            return False
        if outcome == "dismissed":
            continue
        frame = navigator.vision.capture()
        if navigator.clear_home_announcement(frame):
            _wait_home_briefly(task, navigator, BACK_HOME_POLL_SECONDS)
            continue
        if _transition_frame(frame) and _wait_transition(task, navigator):
            # A near-black frame is a page change still loading (leaving the
            # event takes ~8 s at 2K): back presses there landed on home and
            # would open the field map (live 2026-09-29).
            continue
        # One unclassified frame may just be an animation over the home
        # screen; the back arrow on home would open the field map instead.
        # After our own back press the settle is already covered below.
        if attempt == 1 and _wait_home_briefly(task, navigator, UNKNOWN_SETTLE_SECONDS):
            return True
        # Look again (2 frames) before a further press: home that showed late
        # after the last press must not get another back press.
        if attempt > 1 and _wait_home_briefly(task, navigator, 0.3):
            return True
        task.log_info("恢复主页：点击左上角返回。")
        task.operate_click(*BACK_BUTTON_POINT, after_sleep=0.5)
        # Live 2026-09-27: a fixed 1.5 s sleep plus a full classification per
        # press made leaving the event take 15 s.
        if _wait_after_back(task, navigator, frame):
            return True
    if navigator.classify() == ScreenState.HOME:
        return True
    _keep_failure_picture(task, navigator)
    return False


def _note_leaving_step(task, navigator) -> None:
    """The screen the task is leaving, for its 问题摘要 if it fails."""
    try:
        from src.tasks import problem_report

        problem_report.note_leaving_step(task, navigator.vision.capture())
    except (TaskDisabledException, FinishedException):
        raise
    except Exception:
        pass  # the record must never break the way home


def _keep_failure_picture(task, navigator) -> None:
    """Keep the screen recovery could not leave (kept 7 days with the report
    pictures): unknown dialogs (network retry, day change, maintenance) can
    only be handled once a real one has been seen."""
    try:
        from src.tasks import run_report

        path = run_report.save_picture(navigator.vision.capture(), "recovery")
    except (TaskDisabledException, FinishedException):
        raise
    except Exception:
        return
    if path:
        task.log_info(f"恢复主页：回不到主页，已保存当时画面：{path}")


class ReturnHomeTask(BaseBD2Task):
    """One-click recovery: bring the game back to the home screen."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "回到主页"
        self.description = "关闭弹窗、按返回或从地图回城，把游戏带回主页。卡住时可手动执行。"
        self.icon = FluentIcon.HOME
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.visible = True

    def run(self):
        if recover_to_home(self):
            self.info_set("状态", "已回到主页。")
            return True
        self.info_set("状态", "回到主页失败。")
        return False
