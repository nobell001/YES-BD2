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

from src.tasks.BaseBD2Task import HOME_KEY, BaseBD2Task
from src.tasks.map_trade.models import ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision
from src.tasks.task_vision_mixin import REFERENCE_HEIGHT, REFERENCE_WIDTH
from src.utils import field_battle, known_popups
from src.utils.home_confirmation import HOME_LEFT_COLUMN_REQUIRED_HITS
from src.utils.ocr_utils import fuzzy_substring_match, normalize_ocr_text
from src.utils.wait_limits import LOADING_MAX_SECONDS

# Room for the Esc steps after the back arrow and H.
RECOVERY_ATTEMPTS = 8
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
# Leo 2026-10-14 「頂多等8秒到10秒」: was 20 s.  The wait only lasts while
# the screen is the black loading screen, which may take longer (Leo
# 2026-10-15 「我說的10秒是卡死 或者辨識不到」「一定會超過10秒甚至15秒」).
TRANSITION_WAIT_SECONDS = LOADING_MAX_SECONDS
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
# Buttons that only ever close a dialog, never confirm a spend: chosen by
# src/utils/known_popups (取消 allowed on the way home).
CONFIRM_ONLY_TITLES = known_popups.CONFIRM_ONLY_TITLES
# After the back arrow and H, Esc one press at a time (Leo 2026-10-12 「建議
# 還是逐步回主頁」); the game's quit dialog means the top was reached.
ESCAPE_STEPS_MAX = 3
# A back press that moved to another page is followed by another back press;
# H only once back did nothing, or this many presses moved without reaching
# home (live 2K 2026-10-13: from the event stage page H did nothing on the
# event hub and cost ~10 s of the 40 s way home).
BACK_MOVES_BEFORE_HOME_KEY = 2
# The game went back to its title screen (08:00 reset, disconnect, restart).
TITLE_SCREEN_TEXTS = ("touchtostart",)
# OCR misreads like "T0UCH TO STAR" missed the title: tolerant match.
TITLE_SCREEN_FUZZY_RATIO = 0.8
# The login-time game-data download prompt (下载 185 MB, 取消/下载) is part of
# login: recovery pressed its 取消 and the prompt came back (bd2 session
# 2026-10-22, 每日跑商 started on it).  Auto-login presses 下载 instead.
LOGIN_DOWNLOAD_TEXTS = ("下载容量", "将下载游戏所需数据")


def _handle_dialog(task, vision: Vision) -> str:
    """Close one known dialog: "dismissed", "quit" (the game's quit dialog,
    cancelled), "title" (title screen or its data download prompt), "battle" (a field battle being
    fought) or "none"."""

    frame = task.capture_frame()
    height, width = frame.shape[:2]
    boxes = vision.ocr_boxes(frame, "恢复主页弹窗")
    text = "".join(normalize_ocr_text(getattr(box, "name", "")) for box in boxes)
    alnum = normalize_ocr_text(text, alnum_only=True)
    if any(
        fuzzy_substring_match(alnum, title, TITLE_SCREEN_FUZZY_RATIO)
        for title in TITLE_SCREEN_TEXTS
    ):
        return "title"
    if any(words in text for words in LOGIN_DOWNLOAD_TEXTS):
        return "title"
    if getattr(task, "FIELD_BATTLE_ESCAPE", False) and field_battle.in_battle(boxes):
        # Back, H and Esc do nothing in a battle; Esc even ends the auto
        # battle (live 2K 2026-10-22, 跑图 第14章).  每周跑图 only (Leo
        # 2026-10-23): other tasks recover as before v0.2.7.
        return "battle"
    press = known_popups.pick(boxes, allow_cancel=True)
    if press is None:
        return "none"
    if press.key == known_popups.ESC_LABEL:
        tap_escape = getattr(task, "tap_escape", None)
        if not callable(tap_escape):
            return "none"
        task.log_info("恢复主页：公告列表挡住了主页，按 Esc 关闭。")
        return "dismissed" if tap_escape(after_sleep=1.0) else "none"
    center = task._ocr_box_center(press.box)
    if center is None:
        return "none"
    quit_dialog = known_popups.is_quit_dialog(boxes)
    if quit_dialog:
        task.log_info("恢复主页：游戏问要不要关闭游戏，点击「取消」，不再按 Esc。")
    else:
        task.log_info(f"恢复主页：点击「{press.label}」关闭弹窗。")
    task.operate_click(center[0] / width, center[1] / height, after_sleep=1.0)
    return "quit" if quit_dialog else "dismissed"


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


def home_now(task) -> bool:
    """主页 shows right now (the cheap left-column check)."""
    vision = Vision(task)
    return _home_now(Navigator(task, vision))


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
    """Try to bring the game back to the confirmed home screen.

    The stuck-screen watch (frozen_screen.py) rests meanwhile: waiting out a
    loading screen or a dialog here is the way out, not being stuck.
    """
    watch = getattr(task, "_frozen_watch", None)
    if watch is None:
        return _recover_to_home(task, attempts)
    watch.paused += 1
    try:
        return _recover_to_home(task, attempts)
    finally:
        watch.paused -= 1
        watch.pressed()


def _recover_to_home(task, attempts: int) -> bool:
    vision = Vision(task)
    navigator = Navigator(task, vision)
    task._recovery_saw_title = False
    home_key_pressed = False
    back_did_nothing = False
    back_moved = 0
    escape_presses = 0
    escape_stopped = False
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
        if outcome == "quit":
            # Esc reached a top page: the game asked to quit, cancelled.
            escape_stopped = True
            continue
        if outcome == "dismissed":
            continue
        if outcome == "battle":
            leave = getattr(task, "leave_field_battle", None)
            left = leave("恢复主页") if callable(leave) else "none"
            if left not in ("left", "none"):
                task.log_warning(f"恢复主页：撞到怪进了战斗，{left}，回不到主页。", notify=True)
                _keep_failure_picture(task, navigator)
                return False
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
        if (
            attempt > 1
            and not home_key_pressed
            and (back_did_nothing or back_moved >= BACK_MOVES_BEFORE_HOME_KEY)
            and callable(getattr(task, "tap_key", None))
        ):
            # A back press did not bring 主页 and the screen reads as none
            # of the known pages (HDR, a field the navigator doesn't know,
            # 餐厅...): the game's own H once (Leo 2026-10-11 「在餐廳也可以按
            # H回主頁」「凡事總要有備用方案 不要失敗就卡死」).
            home_key_pressed = True
            task.log_info("恢复主页：返回没回到主页，改按快捷键 H。")
            if task.tap_key(HOME_KEY, after_sleep=0.5) and _wait_after_back(
                task, navigator, frame
            ):
                return True
            continue
        if (
            back_did_nothing
            and home_key_pressed
            and not escape_stopped
            and escape_presses < ESCAPE_STEPS_MAX
            and callable(getattr(task, "tap_escape", None))
        ):
            # The back arrow changed nothing (a page without one, a popup
            # without 取消/关闭): one Esc, then look again before the next
            # (Leo 2026-10-12 「建議還是逐步回主頁」).
            escape_presses += 1
            task.log_info(f"恢复主页：返回没有反应，按一次 Esc（第{escape_presses}次）。")
            if task.tap_escape(after_sleep=0.5) and _wait_after_back(task, navigator, frame):
                return True
            back_did_nothing = False
            continue
        task.log_info("恢复主页：点击左上角返回。")
        task.operate_click(*BACK_BUTTON_POINT, after_sleep=0.5)
        # Live 2026-09-27: a fixed 1.5 s sleep plus a full classification per
        # press made leaving the event take 15 s.
        if _wait_after_back(task, navigator, frame):
            return True
        back_did_nothing = not _frames_differ(
            _thumb(frame), _thumb(navigator.vision.capture())
        )
        if not back_did_nothing:
            back_moved += 1
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


class FieldBattleEscapeTestTask(BaseBD2Task):
    """Developer check of the field-battle escape (Leo 2026-10-22): walk into
    a monster by hand, then run this; it runs away (or presses 离开 on the
    result) once and says how it went.  Hidden from the tool's task list."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "野外战斗逃跑测试"
        self.FIELD_BATTLE_ESCAPE = True
        self.description = "在战斗画面执行一次：按 Esc 找「逃跑」并逃跑（开发用）。"
        self.visible = False

    def run(self):
        left = self.leave_field_battle("逃跑测试")
        self.log_info(f"逃跑测试结果：{left}")
        self.info_set("状态", left)
        return left == "left"
