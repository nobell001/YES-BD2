"""Before a run the player started: one look at the game's settings, and a
reminder when one is off (差異化點子 5).  Leo 2026-10-09: 「5提醒就好了」, a
reminder only, no page with steps and pictures.

- 游戏语言: home's labels read 繁中.  Until 2026-10-09 the run did not start
  then; the 繁中 client is supported now (game_text turns what OCR reads into
  the 简中 client's words), so the look only notes it for the report.
- 画面颜色: HDR or a colour filter changed the picture (colour_check).  The
  run goes on; the reminder says what to turn off.
- 游戏画面大小 is game_size.fix_or_warn's, just before this.
- 账号清单 (accounts_stop): a list that cannot be read cannot tell whose
  records the run would write, so no run starts, not even an item of
  一键日常 (认不准就不按; the tool does not guess account 1).

Only a clear reading counts: a screen that is not home, or OCR that reads
nothing, is no reminder (the run's own checks still decide).
"""

from __future__ import annotations

import time

from ok import Logger
from ok.task.exceptions import FinishedException, TaskDisabledException

from src.tasks.run_history import NOT_STARTED_KEY
from src.utils import accounts, colour_check, game_language
from src.utils.home_confirmation import (
    HOME_GACHA_OCR_RELATIVE_ROI,
    HOME_LEFT_COLUMN_OCR_RELATIVE_ROI,
    HOME_DIMMED_P95_THRESHOLD_DEFAULT,
    HOME_LEFT_COLUMN_REQUIRED_HITS,
    home_left_column_brightness,
    home_gacha_ocr_matches,
    home_left_column_hits,
)

logger = Logger.get_logger(__name__)

COLOUR_MESSAGE = (
    "画面颜色和游戏原本的差很多，可能开着 HDR 或显卡的颜色滤镜，有些判断可能不准。"
    "建议关掉后再跑，这次照常执行。"
)
COLOUR_KEY = "画面颜色"
# The popup and the log line; the shorter one under 「没有开始跑」.
ACCOUNTS_TEXTS = {
    accounts.BROKEN: (
        "账号清单文件坏了，工具分不出现在是哪个账号，为免把进度记到别的账号，这次没有开始跑。"
        "坏的文件已另存为 configs/accounts.json.corrupt。请删掉 configs 文件夹里的 "
        "accounts.json；有其他账号的话，到账号页按原来的顺序加回来，"
        "切到游戏里登录的账号，再按开始。",
        "账号清单文件坏了，分不出是哪个账号。删掉 configs/accounts.json，"
        "到账号页加回其他账号，再按开始。",
    ),
    accounts.BUSY: (
        "账号清单文件暂时打不开（可能被防毒软件占用），工具分不出现在是哪个账号，"
        "这次没有开始跑。请稍后再按开始。",
        "账号清单文件暂时打不开，稍后再按开始。",
    ),
}
# The colour reminder once in a while, not before every task of a long day.
NOTIFY_GAP_SECONDS = 600.0
# The gacha label is small at 1080p.
GACHA_OCR_SCALE = 2.0

_last_colour_notice = {"at": 0.0}


def started_alone(task) -> bool:
    """The player started this task itself, not 一键日常 as one of its items."""
    executor = getattr(task, "executor", None)
    return executor is not None and getattr(executor, "current_task", None) is task


def _home_traditional(task, frame) -> bool:
    """True only when home is on screen and its labels read 繁中.

    game_text turns 繁中 OCR into 简中 words and notes the raw text with
    game_language on the way, so home is recognised either way and the
    client comes from game_language (never from a player's name alone: two
    different 繁中-only characters in one read).
    """
    from src.tasks.map_trade.vision import Vision

    vision = Vision(task)
    left = vision.ocr_text(
        frame, "开跑前检查 左列", relative_roi=HOME_LEFT_COLUMN_OCR_RELATIVE_ROI
    )
    if home_left_column_hits(left) < HOME_LEFT_COLUMN_REQUIRED_HITS:
        gacha = vision.ocr_text(
            frame,
            "开跑前检查 抽抽乐",
            relative_roi=HOME_GACHA_OCR_RELATIVE_ROI,
            ocr_scale=GACHA_OCR_SCALE,
        )
        if not home_gacha_ocr_matches(gacha):
            return False  # not home
    return game_language.client_is_traditional()


def _remind(task, text: str, notify: bool = True) -> None:
    try:
        task.info_set("开跑前检查", text)
    except Exception:
        pass
    warn = getattr(task, "log_warning", None)
    if callable(warn):
        warn(text, notify=notify)


def _colour_notify(now: float) -> bool:
    last = _last_colour_notice["at"]
    if last and now - last < NOTIFY_GAP_SECONDS:
        return False
    _last_colour_notice["at"] = now
    return True


def _check_colours(task, frame, now: float, popup_closed: bool = False) -> None:
    # 桌面分身 2026-10-18: the login notice dimmed home (left column 56/185)
    # and the dimmed colours read as HDR; a dimmed home is no colour reading.
    if home_left_column_brightness(frame) < HOME_DIMMED_P95_THRESHOLD_DEFAULT:
        return
    check = colour_check.check_settled(frame, task.next_frame, task.sleep)
    if check.distance is None:
        return  # the home top bar is not on screen, or the colours were off only once
    if check.distorted and not popup_closed and _closed_popup(task):
        # Live 2K 2026-10-22: the 公告 list dimmed the top bar but not the
        # left column (钻石 154.6 against 1.0 once it was gone); colours are
        # read again on the bare home.
        second = task.next_frame()
        if second is not None:
            _check_colours(task, second, now, popup_closed=True)
        return
    colour_check.remember(check)
    try:
        task.info_set(COLOUR_KEY, check.detail)
    except Exception:
        pass
    if check.distorted:
        _remind(task, COLOUR_MESSAGE, notify=_colour_notify(now))


def _closed_popup(task) -> bool:
    close = getattr(task, "close_known_popup", None)
    return bool(callable(close) and close("开跑前检查", info_only=True))


def accounts_stop(task) -> str:
    """The notice when the account list cannot be read (nothing may start), else ""."""
    problem = accounts.unreadable()
    if not problem:
        return ""
    message, notice = ACCOUNTS_TEXTS[problem]
    _remind(task, message)
    try:
        task.info_set(NOT_STARTED_KEY, notice)
    except Exception:
        pass
    return notice


def look(task, now: float | None = None) -> str:
    """Look at the game before the run; the reminder that stops it, else "".

    Nothing stops a run now: 繁中 is noted for the report (two frames, so a
    misread never labels a 简中 game), and the colours get a reminder.
    """
    now = time.monotonic() if now is None else now
    try:
        frame = task.next_frame()
        if frame is None:
            return ""
        if _home_traditional(task, frame):
            second = task.next_frame()
            if second is not None and _home_traditional(task, second):
                try:
                    task.info_set(game_language.INFO_KEY, game_language.TRADITIONAL_LABEL)
                except Exception:
                    pass
        _check_colours(task, frame, now)
    except (TaskDisabledException, FinishedException):
        raise
    except Exception as exc:  # a check must never break the run itself
        logger.warning(f"setup check failed: {exc}")
    return ""


def reset() -> None:
    _last_colour_notice["at"] = 0.0
