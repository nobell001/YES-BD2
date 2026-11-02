"""A field battle the character walked into, and its result screen.

Live 2K 2026-10-22, 跑图 第14章 战斗区域2: a monster touched the character
right after 吸收, the game fought it by itself (「TURN.1」 at the top, the
「TURN.1 BATTLE」 button bottom right) and stopped on the result screen
(VICTORY, REWARD, 「离开」 bottom right; Esc does nothing there).  No task
knew either screen: the way home pressed back, H and Esc for two minutes,
and the confetti kept the screen moving, so the still-screen guard never
fired (Leo 「我說的10秒沒反應就退出或esc 這時候竟然沒有用上」).

Leo 2026-10-22: run away from such a battle 「判定進戰鬥 就直接按esc 1秒按一下
最多按4下 看到有逃跑就不按」「逃跑完一樣繼續該圖的跑圖流程」
(``BaseBD2Task.leave_field_battle``).  The result screen is closed by
``known_popups.pick`` (「离开」) wherever a popup is closed.
"""

from __future__ import annotations

import re

from src.utils.ocr_utils import normalize_ocr_text

RESULT_TITLES = ("victory", "defeat")
RESULT_REWARD = "reward"
LEAVE_TEXTS = ("离开", "離開")
LEAVE_TEXT_MAX = 4
# The battle menu Esc opens (暂停: 逃跑 / 重新挑战 / 点击继续 along the
# bottom) and the dialog its 逃跑 opens (live 4K 2026-10-22, 角色卡7 卡勒塔市):
# title 逃跑, 「从战斗中逃跑后重新挑战时，敌人的生命力初始化为100%。是否放弃
# 战斗逃跑?」, buttons 取消 and 逃跑 side by side.
FLEE_TEXTS = ("逃跑", "逃離", "逃离", "撤退")
FLEE_TEXT_MAX = 6
CONFIRM_TEXTS = ("确认", "確認", "确定", "確定")
CANCEL_TEXTS = ("取消",)
FLEE_DIALOG_TEXTS = ("放弃战斗", "放棄戰鬥", "敌人的生命力", "敵人的生命力")
# Leo 2026-10-22: Esc once a second, at most 4 presses, none once 逃跑 shows
# (auto battle on: the first press ends it, the next opens the menu).
ESC_PRESSES_MAX = 4
ESC_EVERY_SECONDS = 1.0
# The game's own auto battle: 「自动战斗中」 bottom left, 「结束自动战斗 ESC」
# bottom right.  Esc there ends the auto battle: never pressed in a battle.
AUTO_TEXTS = ("自动战斗中", "結束自動戰鬥", "结束自动战斗", "自動戰鬥中")
# 「TURN.1」 at the top centre / in the bottom-right button, read as
# "TURN.1", "TURN.2", "TURN1"...
TURN_PATTERN = re.compile(r"turn\.?\d{1,2}")
BATTLE_TEXT = "battle"
# The battle's Esc menu: 「暂停」 over the cut-scene and volume settings, with
# 逃跑 / 重新挑战 / 点击继续 at the bottom.  Its settings rows hold a 「关闭」
# option that recovery took for a close button and pressed ten times (bd2
# session 2026-10-22, 跑图 第3章): the menu is the battle, left by 逃跑.
# (重新挑战 is left out: the run-away dialog's text says it too.)
PAUSE_MENU_TEXTS = ("暂停", "暫停", "点击继续", "點擊繼續")


def _names(boxes) -> list[str]:
    return [normalize_ocr_text(getattr(box, "name", "")) for box in boxes or ()]


def leave_button(boxes):
    """The result screen's 「离开」 box, or None when this is no battle result."""
    names = _names(boxes)
    text = "".join(names)
    if not any(title in text for title in RESULT_TITLES) and RESULT_REWARD not in text:
        return None
    for name, box in zip(names, boxes or ()):
        # The pill's power icon is sometimes read as a letter before it.
        if any(leave in name for leave in LEAVE_TEXTS) and len(name) <= LEAVE_TEXT_MAX:
            return box
    return None


def in_battle(boxes) -> bool:
    """The battle itself: the auto-battle line, or a 「TURN.n」 turn counter
    with the 「BATTLE」 button."""
    names = _names(boxes)
    if leave_button(boxes) is not None:
        return False
    text = "".join(names)
    if any(normalize_ocr_text(word) in text for word in AUTO_TEXTS):
        return True
    if pause_menu(boxes):
        return True
    return bool(TURN_PATTERN.search(text)) and BATTLE_TEXT in text


def pause_menu(boxes) -> bool:
    """The battle's Esc menu (「暂停」 with its 逃跑 entry) is open."""
    if flee_button(boxes) is None:
        return False
    text = "".join(_names(boxes))
    return any(normalize_ocr_text(word) in text for word in PAUSE_MENU_TEXTS)


def auto_on(boxes) -> bool:
    """The game is fighting by itself (「自动战斗中」)."""
    text = "".join(_names(boxes))
    return any(normalize_ocr_text(word) in text for word in AUTO_TEXTS)


def flee_button(boxes):
    """The battle menu's 「逃跑」 entry, or None."""
    for name, box in zip(_names(boxes), boxes or ()):
        if any(word in name for word in FLEE_TEXTS) and len(name) <= FLEE_TEXT_MAX:
            return box
    return None


def flee_confirm_button(boxes):
    """The button that confirms running away, or None: the dialog's 逃跑
    beside its 取消 (the title and the menu's own 逃跑 read the same
    word, so only the one on 取消's row counts), else a 「确认」."""
    names = _names(boxes)
    text = "".join(names)
    if not any(word in text for word in FLEE_TEXTS):
        return None
    if any(normalize_ocr_text(word) in text for word in FLEE_DIALOG_TEXTS):
        cancel = next(
            (box for name, box in zip(names, boxes or ()) if name in CANCEL_TEXTS), None
        )
        if cancel is not None:
            row = _centre_y(cancel)
            for name, box in zip(names, boxes or ()):
                if (
                    box is not cancel
                    and any(word in name for word in FLEE_TEXTS)
                    and len(name) <= FLEE_TEXT_MAX
                    and abs(_centre_y(box) - row) <= max(_height(cancel), 1)
                ):
                    return box
    for name, box in zip(names, boxes or ()):
        if name in CONFIRM_TEXTS:
            return box
    return None


def _height(box) -> float:
    return float(getattr(box, "height", 0) or 0)


def _centre_y(box) -> float:
    return float(getattr(box, "y", 0) or 0) + _height(box) / 2


def turn_text(boxes) -> str:
    """The turn counter read (「turn.2」), "" when none."""
    match = TURN_PATTERN.search("".join(_names(boxes)))
    return match.group(0) if match else ""
