"""推主线: a state that moves the main story on by itself (Leo 2026-11-06).

「其實很簡單他不是一個任務 而是定義成一個狀態」: the player turns it on
wherever they are in the story; it looks at the screen again and again and
answers each look with one press (main_story/screen.py says which).  It is
not a 主页 task: it neither goes home first nor goes home when it ends.

- 「這是一個狀態 用戶按鍵盤滑鼠 都不會中斷操作」: the player's own keyboard and
  mouse never stop it (``player_plays_along``); 停止 on the game's status
  bar or in the tool does.  The bar shows while it is on, whatever 设置 says.
- 「戰鬥那邊我決定不要按自動戰鬥 讓玩家去操作」: nothing is pressed in a battle.
- DEFEAT waits for the player (Leo 2026-11-07, was 「打輸就停下來」): nothing is
  pressed; once they retry or leave and a known screen shows, it goes on.
- 「偵測回主頁 就自動暫停」「回主頁或進商店頁面 他只是暫停」: on 主页 or a page
  with buying or spending words it pauses itself (继续 goes on); only 停止
  ends it.
- 「這是一個狀態 不要自己進下一章」: it never opens another chapter.
- 「顯示移動中但是卡住了」: a walk that stands still gets E, ✕ then E, the
  quest line, 快速進行任務, one each 8 s; then it pauses and says so.
- 「我希望程式可以就算被蓋住也能繼續運行」: it goes on behind other windows; each
  press borrows the front for a moment (main_story/borrow.py) and waits for
  the player's mouse first.
- 「无法自动进行的探索」: the step is the player's.  Nothing is pressed until the
  quest line changes or a story, battle or step list shows; then it goes on
  by itself (Leo 「程式有顯示已暫停 但我操作到完」 had to press 继续 before).
- 「用戶要做的就是選卡帶 然後 放開雙手 接著讓程式推完同卡帶的三個難度」: a
  cleared difficulty's 冒險指南 book leads to the shelf, the cartridge marked
  遊戲中 is pressed (no other one); the book with all three 完成 ends it.
- Leo 2026-11-07: a battle still on TURN 1 sixty seconds after it was first
  seen gets the game's auto battle pressed, once (a second way only if that
  press did nothing).  Otherwise battles stay the player's.

Every press has a second way when the game ignores it (another key, then
the mouse on the button the screen showed); a screen that stays the same
after all of them is left alone until it changes, with the reason on the
status bar.  「其他畫面就按 Enter」 is never pressed while the screen shows
buying or spending words.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from qfluentwidgets import FluentIcon

from src.tasks.BaseBD2Task import KEY_TAP_SECONDS, _set_foreground_attached
from src.tasks.main_story import borrow, screen
from src.tasks.main_story.screen import Kind
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.utils.ocr_utils import normalize_ocr_text
from src.utils.wait_limits import is_loading_dark

LABEL = "推剧情"
LOOK_GAP = 0.6  # between looks (one whole-screen OCR each)
PRESS_GAP = 1.6  # the same screen gets its next press after this long
STILL_FOR_E = 1.2  # E only once the field stood still this long (not walking)
BATTLE_HOLD = 10.0  # after a battle frame, its end animation gets no Enter
HOME_LOOK_EVERY = 3.0
ENTER, SPACE, ESC = 0x0D, 0x20, 0x1B
# 「其他畫面就按 Enter」 is held back on a screen with any of these (a shop or
# a spending dialog the player opened while the state is on).
SPEND_WORDS = (
    "購買", "购买", "消耗", "鑽石", "钻石", "付費", "付费", "支付", "花費", "花费",
    "確定購買", "确定购买", "結帳", "结账", "儲值", "储值", "抽取", "分解", "出售",
    # Legal and terms dialogs are never pressed (product rule).
    "條款", "条款", "同意", "隱私", "隐私",
    # Leaving the game: never Enter there either.
    *screen.EXIT_WORDS,
)
# Test runs (env BD2_MAIN_STORY_SHOTS = a folder): a 1080p picture each time
# the screen kind changes, named by time and kind, to learn screens not met yet.
SHOTS_ENV = "BD2_MAIN_STORY_SHOTS"
# Test runs only (never a setting): prove the E route on a chapter that has
# 快速进行任务 (Leo 「雪地待會還要不用快速任務做一次」).
NO_QUICK_ENV = "BD2_MAIN_STORY_NO_QUICK"
AUTO_AFTER = 60.0  # 「60 秒沒開始就按一次自動」
AUTO_RECHECK = 8.0  # the press gets this long before its second way
SP_SETTLE = 5.0  # a battle opens showing 15/20, then 0/20: that is no player (live 第13章)
TURN_GONE_LOOKS = 3  # 「TURN.1」 missing this many looks in a row: the turn ran
# 「你點畫面太快了 如果有人網路比較卡 可能你補點的時候他還在載入」: the first
# press on a screen goes at once, each further one waits longer, counted from
# the last press or the last loading look, whichever is later.
REMEDY_GAPS = (3.0, 5.0, 8.0)
DIALOG_GAP = 0.6  # story lines come fast, the next Enter does not wait 1.6 s
# Spending words that stay this long are a page, not a banner: 「消耗」 passed
# for 2 s on 2026-11-07 when 超困難 was cleared, a typing story line too.
SPEND_HOLD = 6.0
ARRIVED_E = 3
PLAIN_E = 6
# Fireflies keep a picture moving, so the ladder alone never runs out: this
# many presses on one kind of screen count as tried (not on dialog).
MANY_PRESSES = 8
ESC_WAIT = 8.0  # 「卡了一樣esc」: this long after the last-remedy Esc, then pause
WALK_STUCK = 8.0  # standing this long under 「自動移動中」: the next remedy
WALK_GONE = 4.0  # the banner away this long: a new walk (E brings it back in 1 s)
WALK_RUNGS = 4
STILL_PAUSE = 180.0  # the same picture this long, nothing it knows: pause and tell

# What each screen gets, press after press while it stays the same:
# ("key", code) / ("f2",) / ("e",) / ("click",) = the point the screen read gave.
LADDERS: dict[Kind, tuple[tuple, ...]] = {
    Kind.SKIP: (("f2",), ("f2",), ("click",)),
    Kind.SKIP_DIALOG: (("key", ENTER), ("key", SPACE), ("click",)),
    Kind.QUICK: (("click",), ("click",)),
    Kind.QUICK_ASK: (("click",), ("key", ENTER)),
    Kind.LIST_AUTO: (("click",), ("click",)),
    Kind.LIST_BATTLE: (("click",), ("click",)),
    Kind.REWARD: (("click",), ("key", ENTER)),
    # E, E again; a character that still stands: the quest line's text once.
    Kind.GUIDE: (("e",), ("e",), ("click",)),
    # F only with the prompt over the NPC showing; the last way is its pill.
    Kind.PROMPT: (("f",), ("f",), ("click",)),
    Kind.EXIT_MENU: (("key", ESC), ("key", ESC)),
    # A new line starts this over (see the look); only dialog repeats it.
    Kind.DIALOG: (("key", ENTER), ("key", SPACE), ("click",)),
    Kind.RESULT: (("key", ENTER), ("click",), ("key", SPACE)),
    Kind.BOOK: (("key", ENTER), ("key", SPACE), ("click",)),
    Kind.SHELF: (("click",), ("click",)),
    Kind.OTHER: (("key", ENTER), ("key", ENTER), ("key", SPACE)),
}
WAITS = {Kind.WALKING, Kind.LOADING, Kind.BATTLE, Kind.FIELD, Kind.MANUAL}


# While the player does a step by hand these screens say nothing yet: the
# field and whatever they open.
PLAYER_STEP_KINDS = {
    Kind.GUIDE, Kind.QUICK, Kind.MANUAL, Kind.PROMPT, Kind.WALKING, Kind.FIELD, Kind.OTHER, Kind.LOADING,
    Kind.EXIT_MENU,  # the step may be a talent, used from that very menu (「使用莎拉的炼金术」)
}


def new_quest(quest: str, at_start: str) -> bool:
    """Another quest, not the same line read cut short (it scrolls)."""
    return bool(quest and at_start and quest not in at_start and at_start not in quest)


class ArrivedWatch:
    """E presses that only said 「已完成自动移动」 on one quest: at the spot, nothing
    more for E to do, and the game does not call the step 无法自动进行."""

    def __init__(self):
        self.quest = ""
        self.count = 0  # E presses followed by the banner
        self.plain = 0  # E presses with nothing else on screen in between
        self.seen = False

    def look(self, kind: Kind, arrived: bool) -> None:
        """Each look: the banner stays 2 s, often gone by the next press."""
        self.seen = self.seen or arrived
        # Our own Esc's menu or an unknown screen is no progress: live 第5章 the
        # 「结束游戏」 menu started the count over every round.
        if kind not in (Kind.GUIDE, Kind.WALKING, Kind.QUICK, Kind.EXIT_MENU, Kind.OTHER):
            self.count = self.plain = 0  # something happened: a story, a load, a fight
            self.seen = False

    def pressed(self, quest: str) -> bool:
        """Tell one E press; True when the step is the player's."""
        if quest != self.quest:
            self.quest, self.count, self.plain = quest, 0, 0
        self.count += 1 if self.seen and quest else 0
        self.plain += 1 if quest else 0
        self.seen = False
        return self.count >= ARRIVED_E or self.plain >= PLAIN_E


def player_step_over(kind: Kind, quest: str, at_start: str, last_new: str = "") -> bool:
    """Whether the step the game would not do by itself is done.  The banner
    means it is not, and a new quest counts when read the same twice: live
    10:59 one odd read ended the wait with Leo still doing the step."""
    if kind == Kind.MANUAL:
        return False
    if kind not in PLAYER_STEP_KINDS:
        return True
    return new_quest(quest, at_start) and quest == last_new


def without_quick(reading: screen.Reading, boxes) -> screen.Reading:
    """The test run's reading: quick is seen but the E route goes on."""
    if os.environ.get(NO_QUICK_ENV) != "1":
        return reading
    if reading.kind == Kind.QUICK:
        no_auto = screen._find(boxes, screen.NO_AUTO_WORDS)
        if no_auto is not None:
            return screen.Reading(Kind.MANUAL, None, no_auto.name)
        return screen.Reading(Kind.GUIDE, screen.QUEST_LINE_POINT, "测试：不按快速")
    if reading.kind == Kind.QUICK_ASK:
        # Esc: Enter on this dialog is its 立刻前往.
        return screen.Reading(Kind.EXIT_MENU, None, "测试：取消")
    return reading


def remedy_gap(kind: Kind, presses: int) -> float:
    """How long after ``presses`` on this screen the next press may go.  Not
    on dialog: there a new line means the last press worked."""
    if kind == Kind.DIALOG or presses <= 0:
        return 0.0
    return REMEDY_GAPS[min(presses, len(REMEDY_GAPS)) - 1]


class WalkWatch:
    """How many remedies a stuck walk has had.  ``look`` hears each look at
    「自動移動中」 and answers the next remedy (1..WALK_RUNGS, then WALK_RUNGS + 1
    for giving up) or 0; real walking or a long time without the banner
    starts it over."""

    def __init__(self):
        self.still_since: float | None = None
        self.seen_at = 0.0
        self.rung = 0

    def look(self, now: float, walking: bool) -> int:
        if self.still_since is None or now - self.seen_at >= WALK_GONE or walking:
            self.still_since = now
            self.rung = 0
        self.seen_at = now
        if now - self.still_since < WALK_STUCK:
            return 0
        self.still_since = now
        self.rung += 1
        return self.rung


class BattleWait:
    """Whether a battle still waits on TURN 1 (Leo's 60 s rule).

    ``look`` hears each look at a battle and answers True when the auto
    toggle is to be pressed now.  The turn ran (「TURN.1」 gone for some looks
    after it was seen) or the player acted (SP moved): never again this battle.
    """

    def __init__(self, first_seen: float):
        self.first_seen = first_seen
        self.turn_seen = False
        self.gone = 0
        self.over = False
        self.sp = ""
        self.presses = 0
        self.pressed_at = 0.0

    def look(self, now: float, turn_one: bool, sp: str) -> bool:
        if self.over:
            return False
        if now - self.first_seen < SP_SETTLE:
            self.sp = sp or self.sp
        elif self.sp and sp and sp != self.sp:
            self.over = True  # the player is playing
            return False
        self.sp = self.sp or sp
        if turn_one:
            self.turn_seen = True
            self.gone = 0
        elif self.turn_seen:
            self.gone += 1
            self.over = self.gone >= TURN_GONE_LOOKS
        if not turn_one or now - self.first_seen < AUTO_AFTER:
            return False
        if self.presses >= 2 or (self.presses and now - self.pressed_at < AUTO_RECHECK):
            return False
        self.presses += 1
        self.pressed_at = now
        return True


def spend_words_on(boxes) -> str:
    text = "".join(normalize_ocr_text(getattr(box, "name", "")) for box in boxes or ())
    return next((word for word in SPEND_WORDS if normalize_ocr_text(word) in text), "")


class MainStoryTask(_ClaimTaskBase):
    claim_log_name = "main_story"
    # A state, not a 主页 task (see the module note).
    recover_home_on_failure = False
    start_from_home = False
    frozen_retry = False
    failure_retry = False
    # The game's status bar shows while this runs, even with it off in 设置.
    status_bar_always = True
    # Start leaves the player's window in front: it runs behind it.
    stays_behind = True
    # Leo 2026-11-07 「頂部欄不用顯示那麼多資訊 不要重複資訊 不要顯示參數」: the bar
    # says only which screen it is on; scores and points stay in the log.
    status_bar_plain = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = LABEL
        self.description = (
            "在剧情里打开：自动跳过对话、按 E 寻路、优先快速进行任务、按自动进行；"
            "战斗由你自己打，打完自动继续。按键盘鼠标不会停，按停止才停。"
        )
        self.icon = FluentIcon.PLAY
        self.group_name = "剧情"
        self.group_icon = FluentIcon.PLAY
        self.player_plays_along = False
        self.waiting_for_player = False  # the status bar lights up on this

    # -- presses ---------------------------------------------------------

    def _mouse_button_held(self) -> bool:
        import win32api

        return any(win32api.GetAsyncKeyState(button) & 0x8000 for button in borrow.VK_BUTTONS)

    def _mouse_quiet(self) -> None:
        import win32api

        waited = borrow.wait_mouse_quiet(win32api.GetCursorPos, self._mouse_button_held, self._mouse_wait)
        if waited > 2 * borrow.MOUSE_QUIET:
            self.log_info(f"{LABEL}：等鼠标停下 {waited:.1f} 秒。")

    def _borrowing(self, action) -> bool:
        """``action`` with the game taking keys for a moment, once the player's
        mouse is still; the window in front before gets the front back.  Keys
        only: pinned on top, that window would be under a real click."""
        import win32gui

        interaction = getattr(self.executor, "interaction", None)
        window = getattr(interaction, "hwnd_window", None)
        game = getattr(window, "top_hwnd", None) or getattr(window, "hwnd", None)
        if not game:
            return False
        self._mouse_quiet()
        ran, returned = borrow.borrow_foreground(
            game, action, win32gui.GetForegroundWindow, _set_foreground_attached, time.sleep, borrow.pin_on_top
        )
        if not ran:
            self.log_info(f"{LABEL}：游戏窗口没能到最前面，这一下没按。")
        elif not returned:
            self.log_warning(f"{LABEL}：按完没能把原来的窗口换回前面。")
        return ran

    def _mouse_wait(self, seconds: float) -> None:
        self.sleep(seconds)  # 「不要跳等鼠標停下」: the bar keeps its step

    def _send_game_key(self, code: int, seconds: float) -> bool:
        """The base one raises the game and leaves it in front."""
        def action():
            import win32api
            import win32con

            scan = win32api.MapVirtualKey(code, 0)
            win32api.keybd_event(code, scan, 0, 0)
            try:
                time.sleep(max(0.0, float(seconds)))
            finally:
                win32api.keybd_event(code, scan, win32con.KEYEVENTF_KEYUP, 0)

        return self._borrowing(lambda: self.operate(action, block=False, restore_cursor=False))

    def _click_reference(self, x: int, y: int, after_sleep: float = 0.0) -> None:
        """A click is posted to the game's window, so it needs no front and
        can land nowhere else; only the cursor moves for a moment, so the
        player's mouse is waited for and the cursor put back."""
        self._mouse_quiet()
        super()._click_reference(x, y, after_sleep=after_sleep)  # 不用确认：helper 本身，调用处检查

    def _key(self, code: int, label: str) -> bool:
        if not self._send_game_key(code, KEY_TAP_SECONDS):
            self.info_set("快捷键", f"{label} 未发送：游戏窗口不在最前面")
            return False
        self.info_set("快捷键", label)
        return True

    def _press_step(self, step: tuple, reading: screen.Reading, frame_size) -> str:
        """Press one ``step`` of a ladder; returns what was pressed ("" none)."""
        kind = step[0]
        if kind == "f2":
            return "F2" if self.tap_key("F2") else ""
        if kind == "e":
            return "E" if self.tap_key("E") else ""
        if kind == "f":
            return "F" if self.tap_key("F") else ""
        if kind == "key":
            code = step[1]
            label = {ENTER: "Enter", SPACE: "Space", ESC: "Esc"}.get(code, hex(code))
            return label if self._key(code, label) else ""
        if kind == "click" and reading.point is not None:
            x, y = reading.point
            self._click_reference(x, y)  # 不用确认：下一次看画面就是确认，没变会换下一招
            return f"点 {reading.kind.value} ({x},{y})"
        return ""

    # -- the state -------------------------------------------------------

    def run(self):
        self.info_set("状态", "开始")
        return self.run_state()

    def run_state(self) -> bool:
        self.player_plays_along = True
        self.log_info(f"{LABEL}：已开启。按键盘鼠标不会停，按停止才停；战斗请自己打。")
        last_small = None
        last_change = time.monotonic()
        last_kind: Kind | None = None
        step = 0  # presses so far on this screen
        last_press_at = 0.0
        battle_at = -BATTLE_HOLD
        home_look_at = 0.0
        idle_noted = ""
        battle_wait: BattleWait | None = None
        last_line = None
        spend_since: float | None = None
        walk_watch = WalkWatch()
        walked_at = 0.0
        player_step: str | None = None  # the quest line while the player does a step
        player_new = ""  # the last other quest read during it
        lost = False  # on the DEFEAT screen, or what follows until a known screen
        arrived_watch = ArrivedWatch()
        presses = 0  # on this kind of screen; a moving picture does not reset it
        esc_at: float | None = None  # the last-remedy Esc on this screen
        loading_at = -BATTLE_HOLD
        try:
            while True:
                frame = self.capture_frame()
                small = screen.to_1080(frame)
                # Pictures first (cheap, Leo 「最好是連 圖像的一起要可以辨識」),
                # the whole-screen OCR only when they do not tell.
                reading = screen.read_pictures(small)
                boxes = []
                if reading is None:
                    boxes = self._reference_boxes(frame, None, "推剧情画面")
                    reading = without_quick(screen.read(small, boxes), boxes)
                now = time.monotonic()
                before = last_small
                changed = screen.moved(last_small, small)
                if changed and reading.kind in (Kind.GUIDE, Kind.PROMPT):
                    # Fireflies or snow move the picture, only the party counts here.
                    changed = screen.party_walking(last_small, small)
                if changed:
                    last_change = now
                    step = 0
                    esc_at = None
                last_small = small
                if reading.kind == Kind.DIALOG:
                    line = screen.dialog_line(small, reading.point)
                    if screen.moved(last_line, line, 1.0):
                        last_change = now  # a new line, though the picture stands still
                        step = 0
                    last_line = line
                else:
                    last_line = None
                # A black picture is loading only when nothing on it is known:
                # black narration under the F2 row is a screen to answer.
                if reading.kind == Kind.LOADING or (reading.kind == Kind.OTHER and is_loading_dark(frame)):
                    loading_at = now
                if reading.kind != last_kind:
                    step = 0
                    presses = 0
                    esc_at = None
                    last_kind = reading.kind
                    self.info_set("当前画面", reading.kind.value)
                    self._test_shot(small, reading)
                kind = reading.kind
                if kind == Kind.BATTLE:
                    battle_at = now
                    if battle_wait is None:
                        battle_wait = BattleWait(now)
                    if battle_wait.look(now, screen.turn_one(small, boxes), screen.sp_text(boxes)):
                        self._press_auto(battle_wait.presses)  # 不用确认：BattleWait 再看 TURN 和 SP，没开始才按第二次
                elif kind not in (Kind.OTHER, Kind.LOADING):
                    battle_wait = None
                arrived_watch.look(kind, screen.arrived(boxes))
                if kind == Kind.MANUAL and player_step is None:
                    player_step = screen.quest_text(boxes)
                    self.log_warning(f"{LABEL}：游戏说这一步无法自动进行，要你自己做。做完会自动接着推。", notify=True)
                self.waiting_for_player = player_step is not None or lost
                if player_step is not None:
                    quest = screen.quest_text(boxes)
                    player_step = player_step or quest
                    # A test run has the tester pass this step in the step list.
                    tester = os.environ.get(NO_QUICK_ENV) == "1" and kind in (Kind.LIST_AUTO, Kind.LIST_BATTLE)
                    if tester or not player_step_over(kind, quest, player_step, player_new):
                        player_new = quest if new_quest(quest, player_step) else ""
                        self.info_set("状态", "等你做完这一步")
                        self.sleep(1.0)
                        continue
                    self.log_info(f"{LABEL}：这一步做完了（{kind.value}，{player_step} → {quest}），接着推。")
                    player_step = None
                    player_new = ""
                    self.waiting_for_player = False
                    last_change = now
                    step = 0
                if kind == Kind.CHAPTER_DONE:
                    self.info_set("状态", "这一章打完了")
                    self.log_info(f"{LABEL}：这一章打完了（{reading.why}），推剧情结束。", notify=True)
                    return True
                if kind == Kind.BOOK and reading.why == screen.ALL_DONE:
                    self.info_set("状态", "三个难度都完成了")
                    self.log_info(f"{LABEL}：这张卡带的三个难度都完成了，推剧情结束。", notify=True)
                    return True
                if kind == Kind.SHELF and reading.point is None:
                    note = "收藏集上没认出「遊戲中」的卡带，不按别的卡带，等画面变化"
                    if note != idle_noted:
                        self.log_info(f"{LABEL}：{note}。")
                        idle_noted = note
                    self.info_set("状态", "等画面变化")
                    self.sleep(LOOK_GAP)
                    continue
                if kind == Kind.DEFEAT or (lost and kind == Kind.OTHER):
                    # 重新挑战 may ask first: an unknown screen is theirs too.
                    if not lost:
                        lost = True
                        self.log_warning(f"{LABEL}：战斗输了，等你重新挑战，打赢会自动接着推。", notify=True)
                    self.waiting_for_player = True
                    self.info_set("状态", "战斗失败")
                    last_change = battle_at = now
                    step = 0
                    self.sleep(1.0)
                    continue
                if lost:
                    lost = False
                    self.waiting_for_player = False
                    self.log_info(f"{LABEL}：看到{kind.value}，接着推。")
                if kind in (Kind.OTHER, Kind.FIELD):
                    home = screen.home_seen(boxes)
                    if not home and now - home_look_at >= HOME_LOOK_EVERY:
                        home_look_at = now
                        home = self._home_confirmation_ok(frame, LABEL)
                    if home:
                        self._pause_on_home()
                        last_small, step = None, 0
                        continue
                if kind not in (Kind.BATTLE, Kind.LOADING) and now - last_change >= STILL_PAUSE:
                    if esc_at is None:
                        esc_at = now
                        self._key(ESC, "Esc")
                        self.log_info(f"{LABEL}：{kind.value}一直没变化，按 Esc。")
                        self.sleep(LOOK_GAP)
                        continue
                    if now - esc_at >= ESC_WAIT:
                        self._pause_stuck(kind)
                        last_small, step, last_change, esc_at = None, 0, time.monotonic(), None
                        continue
                if kind in (Kind.GUIDE, Kind.PROMPT) and screen.party_walking(before, small):
                    walked_at = now
                if kind == Kind.WALKING:
                    rung = walk_watch.look(now, screen.party_walking(before, small))
                    if rung > WALK_RUNGS:
                        self._pause_walk_stuck()
                        last_small, step, walk_watch = None, 0, WalkWatch()
                        continue
                    if rung:
                        self._walk_remedy(rung, reading, small, boxes)
                if kind in WAITS or (kind == Kind.OTHER and now - battle_at < BATTLE_HOLD):
                    self.info_set("状态", kind.value)
                    self.sleep(LOOK_GAP)
                    continue
                # The party, not the picture: falling snow never stands still.
                if kind in (Kind.GUIDE, Kind.PROMPT) and now - walked_at < STILL_FOR_E:
                    self.sleep(LOOK_GAP)  # still walking (the camera moves)
                    continue
                if kind == Kind.OTHER:
                    word = spend_words_on(boxes)
                    if word:
                        spend_since = now if spend_since is None else spend_since
                        if now - spend_since >= SPEND_HOLD:
                            self._pause_on_spend(word)
                            last_small, step, spend_since = None, 0, None
                            continue
                        self.info_set("状态", "等画面变化")
                        self.sleep(LOOK_GAP)
                        continue
                    spend_since = None
                ladder = LADDERS.get(kind, ())
                if now - last_press_at < (DIALOG_GAP if kind == Kind.DIALOG else PRESS_GAP) and step:
                    self.sleep(LOOK_GAP)
                    continue
                if now - max(last_press_at, loading_at) < remedy_gap(kind, presses):
                    self.sleep(LOOK_GAP)
                    continue
                if step >= len(ladder) and kind == Kind.DIALOG:
                    step = 0  # 「對話的時候」 the presses go on as long as it does
                if kind == Kind.GUIDE and step >= len(ladder):
                    # E, E and the quest line changed nothing: the player's step
                    # (第5章 「找来东西塞住凹槽」).  Esc on the field only opens 结束游戏.
                    player_step = screen.quest_text(boxes) or arrived_watch.quest
                    arrived_watch = ArrivedWatch()
                    self.log_warning(f"{LABEL}：「{player_step}」E 走不下去了，要你自己做。做完会自动接着推。", notify=True)
                    continue
                if step >= len(ladder) or (kind != Kind.DIALOG and presses >= MANY_PRESSES):
                    if esc_at is None:
                        esc_at = now
                        self._key(ESC, "Esc")
                        self.log_info(f"{LABEL}：{kind.value}按了 {len(ladder)} 种方法都没变化，按 Esc。")
                    elif now - esc_at >= ESC_WAIT:
                        self._pause_stuck(kind)
                        last_small, step, esc_at = None, 0, None
                        continue
                    self.info_set("状态", "等画面变化")
                    self.sleep(LOOK_GAP)
                    continue
                if ladder[step][0] == "e" and arrived_watch.pressed(screen.quest_text(boxes)):
                    player_step = arrived_watch.quest
                    arrived_watch = ArrivedWatch()
                    self.log_warning(f"{LABEL}：「{player_step}」E 走不下去了，要你自己做。做完会自动接着推。", notify=True)
                    continue
                pressed = self._press_step(ladder[step], reading, frame.shape[:2])  # 不用确认：下一次看画面就是确认，没变按下一招
                step += 1
                presses += 1
                last_press_at = time.monotonic()
                idle_noted = ""
                if pressed:
                    self.info_set("状态", kind.value)
                    self.log_info(
                        f"{LABEL}：{kind.value}（{reading.why or '-'}）→ {pressed}"
                        + (f"（第 {step} 次）" if step > 1 else "")
                    )
                self.sleep(LOOK_GAP)
        finally:
            self.player_plays_along = False
            self.waiting_for_player = False

    def _press_auto(self, nth: int) -> None:
        """Leo's 60 s rule: the top auto toggle; the second press is the second
        way, the same button a little to its side."""
        x, y = screen.AUTO_POINT
        self._click_reference(x + (0 if nth == 1 else 8), y)  # 不用确认：下一次看画面就是确认，TURN.1 还在才有第二次
        self.info_set("状态", "按了自动战斗")
        self.log_info(f"{LABEL}：TURN 1 过了 {int(AUTO_AFTER)} 秒没开始，按自动战斗（第 {nth} 次）。")

    def _test_shot(self, small, reading: screen.Reading) -> None:
        folder = os.environ.get(SHOTS_ENV, "")
        if not folder:
            return
        try:
            import cv2

            from src.utils import image_io

            Path(folder).mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
            image_io.write(Path(folder) / f"{stamp}-{reading.kind.name}.jpg", small, (cv2.IMWRITE_JPEG_QUALITY, 85))
        except Exception as exc:  # a test aid: never stops the state
            self.log_info(f"{LABEL}：测试截图没存下（{exc!r}）。")

    def _pause_stuck(self, kind: Kind) -> None:
        """Everything tried, Esc last: pause and say where."""
        self.info_set("状态", f"卡住了，停在：{kind.value}")
        self.log_warning(f"{LABEL}：卡住了，停在：{kind.value}。已暂停，按继续接着推。", notify=True)
        self.pause()

    def _walk_remedy(self, rung: int, reading: screen.Reading, small, boxes) -> None:
        """One way out of a stuck walk; the next look says whether it worked."""
        point = None
        if rung == 2:
            x, y = reading.point or screen.WALK_CANCEL_POINT
            self._click_reference(x, y)  # 不用确认：下一步紧接着按 E，还卡着就换下一招
            self.sleep(0.5)
        if rung in (1, 2):
            self.tap_key("E")
        elif rung == 3:
            point = screen.QUEST_LINE_POINT
        else:
            point = screen.quick_point(small, boxes)
        if point is not None:
            self._click_reference(*point)  # 不用确认：还卡着就换下一招，全试过就暂停
        self.info_set("状态", "自动寻路卡住了，换一招")
        self.log_info(f"{LABEL}：自动寻路卡住了，第 {rung} 招。")

    def _pause_walk_stuck(self) -> None:
        self.info_set("状态", "自动寻路卡住了")
        self.log_warning(f"{LABEL}：自动寻路卡住了，试过都不动，已暂停。按继续接着推。", notify=True)
        self.pause()

    def _pause_on_spend(self, word: str) -> None:
        """「進商店頁面 他只是暫停」: nothing is pressed; 继续 goes on."""
        self.info_set("状态", "商店或花费页面，已暂停")
        self.log_info(f"{LABEL}：画面上有「{word}」，自动暂停。按继续接着推。")
        self.pause()

    def _pause_on_home(self) -> None:
        """「偵測回主頁 就自動暫停」: nothing is pressed on 主页; 继续 goes on."""
        self.info_set("状态", "回到主页，已暂停")
        self.log_info(f"{LABEL}：看到主页，自动暂停。按继续接着推。")
        self.pause()
