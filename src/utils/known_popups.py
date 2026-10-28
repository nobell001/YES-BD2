"""Popups the game shows on top of any page, closed the same way everywhere.

Reward overlays, 获得道具 dialogs and season reward pages appear whenever the
game decides (after a battle, at the first visit of the day, at a season
change), not only at the step that expects them.  Each task used to close the
ones it had met itself, so a popup that showed up one step early or late
stopped a different task (赛季奖励 after a 镜中之战 battle, #238).  BetterGI
does it once for every task; this module is that one place (Leo 2026-10-12,
「共用彈窗處理」).

``pick`` only ever chooses a harmless press:

- a 「点击画面即可返回」 style line: tapping it closes an overlay;
- 「关闭」;
- 「确认」 only while an info-only title (获得道具, 奖励已发放至背包...) is on
  the same frame, never a purchase or spend confirm;
- 「取消」 only when the caller allows it (the way home), never mid-task,
  where it could cancel a dialog the task itself opened; except on a
  settings panel no task ever opens (战场角色设置), which only a stray press
  opens and whose 取消 changes nothing;
- a tap on the info line of an overlay that has no button (赛季奖励);
- Esc for the game's 公告 list, whose ✕ has no text;
- a tap on the dark backdrop left of a paid pass's 签到 panel (no ✕, no
  关闭; the only button on it is 购买, never pressed);
- 「离开」 on a field battle's result (VICTORY / DEFEAT), where Esc does
  nothing (src/utils/field_battle);
- 「点击继续」 on the battle's 暂停 menu, never its 「关闭」, which is the
  技能过场动画 setting.

The game's quit dialog (Esc pressed on a top page) is recognised so the way
home cancels it and stops pressing Esc (Leo 2026-10-12 「這遊戲按沒幾下就會變成
問你要不要關閉遊戲」).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.utils import field_battle
from src.utils.ocr_utils import normalize_ocr_text

OVERLAY_DISMISS_KEYWORDS = (
    "点击画面即可返回",
    "点击画面返回",
    "点击任意位置",
    "点击空白处",
    "点击屏幕",
    "轻触画面",
)
# A "确认" button is only pressed when one of these reward titles is on screen.
REWARD_DIALOG_TITLES = ("获得道具", "获得奖励", "领取奖励", "奖励领取", "领取成功", "获得物品")
# Info-only dialogs whose 确认 just closes them.
CONFIRM_ONLY_TITLES = REWARD_DIALOG_TITLES + (
    "恭喜晋级",
    "段位下滑",
    "奖励已发放至背包",
    "奖励已通过邮件发放",
)
CONFIRM_TEXT = "确认"
CLOSE_TEXT = "关闭"
CANCEL_TEXT = "取消"
# The quit dialog: one of these verbs next to 游戏 (exact wording not yet
# captured; any of them with 游戏 on a dialog that has 取消 is the quit one).
QUIT_VERBS = ("退出", "结束", "关闭", "离开")
QUIT_OBJECT = "游戏"
# Overlays with no button at all: a tap anywhere closes them.  魔兽追踪者赛季
# 奖励 shows on the first cartridge entered after the season ends, with only
# 「奖励已发放至背包。」 under it (live 2K 2026-10-22, it stopped 一键日常).
TAP_ANYWHERE_LINES = ("奖励已发放至背包", "奖励已通过邮件发放")
TAP_ANYWHERE_TITLES = ("赛季奖励",)
# The game's notice list (公告事项) that opens by itself on 主页 after a
# maintenance: rows tagged 公告/更新/活动… each with a date, closed only by
# its ✕ icon, which has no text; Esc closes it (live 2K 2026-10-22).
NOTICE_LIST_TAGS = ("公告", "更新", "活动", "维护", "公告事项", "重要")
NOTICE_LIST_DATE = re.compile(r"20\d\d年\d{1,2}月\d{1,2}日")
NOTICE_LIST_MIN_ROWS = 2
ESC_LABEL = "Esc"
# A paid pass's daily 签到 panel over 主页 at the first login of the day
# (「午夜装扮之选通行证」, live 4K 2026-10-22): three day cards, 「签到成功」,
# 「购买后可获得额外奖励！」 and a 「购买 JP¥1,140」 button, but no ✕ or 关闭.
# A tap outside the panel closes it (公会签到's blank tap at x 338 did, the
# panel text starting at x 688 of 3840).  Its lines:
PASS_SIGNIN_LINES = ("购买后可获得额外奖励", "各账号可购买")
PASS_SIGNIN_WORD = "签到"
# The tap: this share of the panel text's left x, on the text's row (the
# backdrop left of the panel; the panel starts just left of its text).
PASS_SIGNIN_TAP_X_SHARE = 0.45
PASS_SIGNIN_LABEL = "签到弹窗外的空白处"
# Settings panels no task opens: a stray press opened it (live 4K clone
# 2026-10-23: a second 确认 press on a fading 恭喜晋级 hit the PVP field's
# 战场角色设置 button), and it hides the page behind it.  取消 keeps the
# settings as they were.
STRAY_PANEL_TITLES = ("战场角色设置",)
# The menu Esc or ‖ opens in a battle: 暂停 over the fight, 离开 (逃跑 in a
# field battle), 重新挑战 and 点击继续 along the bottom, and the battle
# settings: 技能过场动画 with its choices 每次观看 / 1天观看1次 / 仅观看新技能 /
# 关闭, the volumes.  That 「关闭」 is a setting, not a close button: the way
# home pressed it 11 times in a 塔洛斯 fight (Leo's 4K 2026-10-28 16:02, 「判斷
# 完全不對」).  Only 「点击继续」 is pressed there; it closes the menu and changes
# nothing.
BATTLE_MENU_CONTINUE = ("点击继续", "點擊繼續")
BATTLE_MENU_WORDS = (
    "离开", "離開", "逃跑", "重新挑战", "重新挑戰",
    "技能过场动画", "技能過場動畫", "整体音量", "整體音量",
)


@dataclass(frozen=True)
class _Spot:
    """A place to tap that no OCR box covers (shaped like one)."""

    name: str
    x: float
    y: float
    width: float = 0.0
    height: float = 0.0


@dataclass(frozen=True)
class PopupPress:
    label: str
    box: object
    # A key instead of a click (the notice list's ✕ has no text to find).
    key: str = ""
    # 取消 on a panel no task opens (STRAY_PANEL_TITLES): allowed mid-task.
    stray: bool = False


def _named(boxes) -> list[tuple[str, object]]:
    return [(normalize_ocr_text(getattr(box, "name", "")), box) for box in boxes or ()]


def _exact(named, text: str):
    wanted = normalize_ocr_text(text)
    return next((box for name, box in named if name == wanted), None)


def is_quit_dialog(boxes) -> bool:
    """The game asks whether to quit: 游戏 with a quit verb, and a 取消 button."""
    named = _named(boxes)
    if _exact(named, CANCEL_TEXT) is None:
        return False
    for name, _box in named:
        if QUIT_OBJECT in name and any(verb in name for verb in QUIT_VERBS):
            return True
    return False


def battle_menu_continue(boxes):
    """The 「点击继续」 box of a battle's 暂停 menu, or None when that menu is
    not on screen (two cues: 点击继续 and a button or setting of the menu)."""
    named = _named(boxes)
    words = tuple(normalize_ocr_text(word) for word in BATTLE_MENU_CONTINUE)
    box = next((box for name, box in named if any(word in name for word in words)), None)
    if box is None:
        return None
    text = "".join(name for name, _box in named)
    if not any(normalize_ocr_text(word) in text for word in BATTLE_MENU_WORDS):
        return None
    return box


def is_battle_menu(boxes) -> bool:
    return battle_menu_continue(boxes) is not None


def is_notice_list(boxes) -> bool:
    """The game's 公告 list: at least two tagged rows and two dated rows."""
    named = _named(boxes)
    tags = sum(1 for name, _box in named if name in NOTICE_LIST_TAGS)
    dates = sum(1 for name, _box in named if NOTICE_LIST_DATE.search(name))
    return tags >= NOTICE_LIST_MIN_ROWS and dates >= NOTICE_LIST_MIN_ROWS


def pass_signin_spot(boxes):
    """The backdrop left of a paid pass's 签到 panel, or None when no such
    panel is on screen.  Never on or near its 购买 button: the tap is left of
    the panel's text, which starts left of the button."""
    named = _named(boxes)
    lines = tuple(normalize_ocr_text(line) for line in PASS_SIGNIN_LINES)
    anchor = next((box for name, box in named if any(k in name for k in lines)), None)
    if anchor is None or not any(PASS_SIGNIN_WORD in name for name, _box in named):
        return None
    left = min(
        float(getattr(box, "x", 0) or 0) for name, box in named if any(k in name for k in lines)
    )
    x = left * PASS_SIGNIN_TAP_X_SHARE
    if x <= 0:
        return None
    y = float(getattr(anchor, "y", 0) or 0) + float(getattr(anchor, "height", 0) or 0) / 2
    return _Spot(PASS_SIGNIN_LABEL, x, y)


def pick(boxes, *, allow_cancel: bool = False) -> PopupPress | None:
    """The harmless press that closes the popup on screen, or None."""
    named = _named(boxes)
    if not named:
        return None
    if is_quit_dialog(boxes):
        # Never 确认 here; 取消 keeps the game open (allowed even mid-task).
        return PopupPress(CANCEL_TEXT, _exact(named, CANCEL_TEXT))
    box = battle_menu_continue(boxes)
    if box is not None:
        return PopupPress(BATTLE_MENU_CONTINUE[0], box)
    box = _exact(named, OVERLAY_DISMISS_KEYWORDS[0])
    if box is not None:
        return PopupPress(OVERLAY_DISMISS_KEYWORDS[0], box)
    if any(_exact(named, title) is not None for title in STRAY_PANEL_TITLES):
        box = _exact(named, CANCEL_TEXT)
        if box is not None:
            return PopupPress(CANCEL_TEXT, box, stray=True)
    if allow_cancel:
        box = _exact(named, CANCEL_TEXT)
        if box is not None:
            return PopupPress(CANCEL_TEXT, box)
    box = _exact(named, CLOSE_TEXT)
    if box is not None:
        return PopupPress(CLOSE_TEXT, box)
    overlays = tuple(normalize_ocr_text(keyword) for keyword in OVERLAY_DISMISS_KEYWORDS)
    box = next((box for name, box in named if any(k in name for k in overlays)), None)
    if box is not None:
        return PopupPress("点击画面返回", box)
    text = "".join(name for name, _box in named)
    if any(normalize_ocr_text(title) in text for title in CONFIRM_ONLY_TITLES):
        box = _exact(named, CONFIRM_TEXT)
        if box is not None:
            return PopupPress(CONFIRM_TEXT, box)
    lines = tuple(normalize_ocr_text(line) for line in TAP_ANYWHERE_LINES)
    titles = tuple(normalize_ocr_text(title) for title in TAP_ANYWHERE_TITLES)
    if _exact(named, CONFIRM_TEXT) is None and any(t in text for t in lines + titles):
        # No button on it: tap its own info line (any spot closes it).
        box = next((box for name, box in named if any(k in name for k in lines)), None)
        if box is None:
            box = next((box for name, box in named if any(k in name for k in titles)), None)
        if box is not None:
            return PopupPress("点击画面返回", box)
    spot = pass_signin_spot(boxes)
    if spot is not None:
        return PopupPress(PASS_SIGNIN_LABEL, spot)
    box = field_battle.leave_button(boxes)
    if box is not None:
        return PopupPress(field_battle.LEAVE_TEXTS[0], box)
    if is_notice_list(boxes):
        return PopupPress(ESC_LABEL, None, key=ESC_LABEL)
    return None
