"""塔洛斯战术教材 in one click (Leo 2026-10-28).

「塔洛斯戰術教材是每個月固定9關 敵人 和 自己的角色 服裝 每關都是每個玩家固定
一樣的」: one record per stage, shipped with the tool (fiend_hunt/data/talos),
plays it for every player.  The run: 主页 → 塔洛斯战术教材 → every stage not
cleared yet, in the list's order (1 2 3 / 4 5 6 / 7 8 9): open it, 战斗,
replay its record (the 魔兽追踪者 replay, every card checked), VICTORY →
返回 → the next one; then 任务 → 全部获得; the end says which of 1-9 are
cleared and whether the rewards were claimed.

Leo's floor for anything going wrong: 「出錯的話最少你要把那關停掉 然後去打下
一關」.  A stage that stops (a read it is not sure of, a lost fight) is left
(the textbook costs nothing and can be played again), opened once more, and
then skipped with its reason.  Buttons are found by their text first, then
pressed at their fixed place, then Esc (all harmless here).

Cleared stages are kept per account (talos/stages.py) next to the list's own
red ✕, so a run stopped halfway goes on with the rest next time.  While the
run is paused the in-game status bar can pick another stage (stage_picker).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from qfluentwidgets import FluentIcon

from src.tasks.claim_page import ClaimButton
from src.tasks.fiend_hunt import vision as fight_vision
from src.tasks.fiend_hunt.fight import ScreenReadError, minutes_and_seconds, replay_fight
from src.tasks.fiend_hunt.record import TurnStateError, load_record
from src.tasks.fiend_hunt.recording import RECORD_FILE
from src.tasks.fiend_hunt.screen import TALOS_GRID_SCALES, GameFightScreen, record_names
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.tasks.talos import stages
from src.utils import accounts
from src.utils.image_utils import template_match_response
from src.utils.ocr_utils import keyword_match_count
from src.utils.press_confirm import wait_for
from src.utils.wait_limits import STUCK_SECONDS

LABEL = "塔洛斯战术教材"
TITLE_KEYWORDS = ("塔洛斯战术教材", "塔洛斯戰術教材", "战术教材", "戰術教材")

# 1920x1080 reference.  The stage list (2K PC 2026-10-28): nine tiles on
# the right, row by row; a cleared one has a big ✕ over its round picture
# (Leo 「打完的關卡中間會有大大的叉」「你要看第幾格有叉」).  Each tile is
# matched with the ✕ of stage 2: 0.89-1.00 on the three cleared tiles, at
# most 0.46 on the six others (orange and blue frames, red monsters).
TILE_X = (1221, 1445, 1670)
TILE_Y = (313, 537, 762)
TILE_HALF = 70
CLEARED_X = Path(__file__).resolve().parent / "talos" / "data" / "cleared_x.png"
CLEARED_MIN, NOT_CLEARED_MAX = 0.7, 0.55
MARKS_SETTLE = 1.2  # the ✕ fades in after the list shows

# The stage's popup (2K PC 2026-10-28): 「关卡N 普通」 top left, 战斗 bottom
# right, ✕ top right.
POPUP_TITLE_ROI = (500, 290, 260, 60)
POPUP_BATTLE_ROI = (1100, 735, 300, 75)
POPUP_BATTLE_POINT = (1243, 770)
POPUP_CLOSE_POINT = (1407, 280)
BATTLE_KEYWORDS = ("战斗", "戰鬥")

# The result screen's 返回 pill, bottom right (2K PC, stages 1-3).
RESULT_BACK_ROI = (1640, 975, 210, 65)
RESULT_BACK_POINT = (1757, 1008)
BACK_KEYWORDS = ("返回",)
# A lost fight (DEFEAT on a red band, 2K PC stage 7): 返回 / 重新挑战 bottom middle.
DEFEAT_BACK_ROI = (770, 970, 190, 50)
DEFEAT_BACK_POINT = (864, 994)

# 任务 bottom left of the list page (a red ! while there is something to
# claim), and its 全部获得 (not seen yet: looked for by its text).
MISSION_ROI = (150, 970, 220, 70)
MISSION_POINT = (262, 1005)
MISSION_KEYWORDS = ("任务", "任務")
# 任务 popup (2K clone 2026-10-28): 「塔洛斯战术教材任务」, 全部获得 at 960,801.
MISSION_CLAIM = ClaimButton((780, 765, 360, 72), ("全部获得", "全部獲得", "全部領取", "全部获取"))

STAGE_TRIES = 2  # a stage that stops is opened once more, then skipped
PLANNING_WAIT = 45.0  # 战斗 → the planning screen (a load)
# The game's own auto battle (4K PC clone 2026-10-28, stage 7): with it on,
# 战斗 goes straight into a fight the game plays by itself, no planning
# screen: 「自动战斗中」 bottom left, the pill 「✕ 结束自动战斗 / ESC」 bottom
# right.  That fight lost; the record's turn 1 can't be placed in it.
AUTO_BATTLE_ROI = (40, 915, 300, 55)
AUTO_BATTLE_STOP_ROI = (1650, 975, 215, 50)
AUTO_BATTLE_STOP_POINT = (1757, 999)
AUTO_BATTLE_WORDS = ("自动战斗中", "自動戰鬥中", "结束自动战斗", "結束自動戰鬥")
AUTO_BATTLE_STOP_WORDS = ("结束自动战斗", "結束自動戰鬥")
OPEN_TRIES = 2  # a stage the game fought by itself is left and opened once more


class StageSwitch(Exception):
    """The player picked another stage on the status bar while paused."""

    def __init__(self, stage: int):
        super().__init__(stage)
        self.stage = stage


class TalosTask(_ClaimTaskBase):
    claim_log_name = "talos"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = LABEL
        self.description = (
            "主页 → 塔洛斯战术教材 → 没打过的关卡照内建的轴自动打（第 1~9 关）"
            " → 任务全部获得。出错的关会退出、再打一次，还不行就跳过打下一关。"
        )
        self.icon = FluentIcon.GAME
        self.group_name = "活动"
        self.group_icon = FluentIcon.GAME
        self.stage_picker = stages.StagePicker()
        # The stages ticked on the 塔洛斯教材 page for the next run (taken once);
        # None: the stages not cleared (a run from 一键 or the task list).
        self.chosen_stages: list[int] | None = None
        self._results: dict[int, str] = {}
        # The stage whose fight is on screen (None on the list and between
        # stages): where 继续 after the player used the game has to leave from.
        self._fighting: int | None = None
        # A stage picked on the bar while the player used the paused game:
        # the run starts again from 主页 and plays it first.
        self._resume_pick: int | None = None
        # The stages this run was asked for (None: the ones not cleared), so a
        # run again after the player used the game plays what is left of them.
        self._plan: list[int] | None = None

    # -- the run ------------------------------------------------------------------

    def run_claim(self) -> bool:
        self._why = ""
        self._fighting = None
        chosen, self.chosen_stages = self.chosen_stages, None
        picked, self._resume_pick = self._resume_pick, None
        self._plan = list(chosen) if chosen is not None else None
        self.stage_picker.chosen = None  # a pick left by a stopped run is not this run's
        missing = stages.missing_records()
        if missing:
            self._note_why(f"工具里少了第 {missing} 关的轴（请更新工具）")
            return self._claim_fail("准备")
        path = accounts.path(stages.PROGRESS_FILE)
        progress = stages.Progress.load(path, stages.edition())
        if not self._open_page_from_home(LABEL, self._entry_point, TITLE_KEYWORDS):
            return self._claim_fail(f"打开{LABEL}")
        marks = self._read_marks()
        progress.merge_screen(marks)
        progress.save(path)
        self.stage_picker.cleared = set(progress.cleared)
        queue = sorted(set(chosen)) if chosen is not None else stages.to_play(progress.cleared)
        if picked is not None:
            queue = stages.next_order(picked, progress.cleared)
        self.log_info(
            f"{LABEL}：已打过 {sorted(progress.cleared) or '无'}，这次要打 {queue or '无'}"
        )
        self._results = {}
        while queue:
            stage = queue.pop(0)
            try:
                won = self._play_stage(stage)
            except StageSwitch as switch:
                self._leave_fight(f"改打第 {switch.stage} 关")
                queue = stages.next_order(switch.stage, progress.cleared)
                self._plan = None  # from the picked one on, the stages not cleared
                continue
            if won:
                progress.cleared.add(stage)
                progress.failed.pop(stage, None)
                self.stage_picker.cleared = set(progress.cleared)
            else:
                progress.failed[stage] = self._results.get(stage, "没打下来")
            progress.save(path)
        claimed = self._claim_missions()
        self._leave_to_home(LABEL, TITLE_KEYWORDS)  # the next task starts from 主页
        return self._report(progress.cleared, claimed)

    def _report(self, cleared: set[int], claimed: bool | None) -> bool:
        failed = {stage: why for stage, why in self._results.items() if why != "won"}
        done = sorted(cleared)
        parts = [f"已通关 {len(done)}/{stages.STAGE_COUNT}：{done or '无'}"]
        for stage, why in sorted(failed.items()):
            parts.append(f"第 {stage} 关没打下来（{why}）")
        if claimed is True:
            parts.append("任务奖励已全部领取")
        elif claimed is False:
            parts.append("任务奖励没领到")
        else:
            parts.append("任务奖励没有可领的")
        message = "；".join(parts)
        self.info_set("结果", message)
        self.log_info(f"{LABEL}：{message}", notify=True)
        if failed:
            self._note_why("；".join(f"第 {s} 关：{w}" for s, w in sorted(failed.items())))
            return self._claim_fail("打关")
        return True

    # -- one stage ----------------------------------------------------------------

    def _play_stage(self, stage: int) -> bool:
        self.stage_picker.current = stage
        why = ""
        for attempt in range(1, STAGE_TRIES + 1):
            self._set_step(stage, None)
            again = "（再打一次）" if attempt > 1 else ""
            self.log_info(f"{LABEL}：第 {stage} 关开始{again}")
            if not self._to_list():
                why = "回不到关卡列表"
                break
            if not self._open_stage(stage):
                why = self._take_why() or "关卡打不开"
                continue
            won, why = self._fight(stage)
            if won:
                self._results[stage] = "won"
                self._back_to_list()
                return True
            self.log_info(f"{LABEL}：第 {stage} 关停下：{why}，退出这关")
            self._leave_fight(why)
        self._results[stage] = why or "没打下来"
        self.log_warning(f"{LABEL}：第 {stage} 关跳过：{why}")
        return False

    def _fight(self, stage: int) -> tuple[bool, str]:
        # Left set when a pause or a stage switch leaves through an exception.
        self._fighting = stage
        won, why = self._replay(stage)
        self._fighting = None
        return won, why

    def _replay(self, stage: int) -> tuple[bool, str]:
        folder = stages.record_folder(stage)
        try:
            record = load_record(folder / RECORD_FILE)
        except (OSError, TurnStateError) as error:
            return False, f"轴读不了：{error}"
        screen = TalosScreen(
            self,
            stage,
            record_names(record),
            record=record,
            folder=folder,
            log=self._fight_log,
            grid_scales=TALOS_GRID_SCALES,
        )
        try:
            if not screen.set_auto_skill(False):
                return False, "关不掉自动技能（右上角菱形）"
        except ScreenReadError as error:
            return False, f"自动技能：{error}"
        try:
            outcome = replay_fight(screen, record, pushes=True, log=self._fight_log)
        except ScreenReadError as error:
            return False, str(error)
        if outcome.finished and screen.end_word == "victory":
            self.log_info(
                f"{LABEL}：第 {stage} 关赢了（{len(outcome.turns_played)} 个回合，"
                f"{minutes_and_seconds(outcome.seconds)}）"
            )
            return True, ""
        if outcome.finished:
            return False, "打输了" if screen.end_word == "lost" else "战斗结束但没看到 VICTORY"
        where = f"第 {outcome.stopped_at} 回合" if outcome.stopped_at else "开始时"
        return False, f"{where}：{outcome.reason}"

    def _fight_log(self, message: str) -> None:
        self.info_set("当前回合", message)
        self.log_info(f"{LABEL}：{message}")

    def _set_step(self, stage: int, turn: int | None) -> None:
        text = f"第 {stage} 关" + (f" · 第 {turn} 回合" if turn else "")
        self.info_set("当前阶段", text)

    def _take_why(self) -> str:
        why, self._why = str(getattr(self, "_why", "") or ""), ""
        return why

    # -- pausing: another stage picked on the status bar ---------------------------

    def check_switch(self) -> None:
        """Called where leaving is safe (a turn's start, before each move or
        BATTLE press, between pages); a pause holds the run in a sleep, so
        this runs after 继续."""
        chosen = self.stage_picker.take()
        if chosen is not None:
            self.log_info(f"{LABEL}：暂停时选了第 {chosen} 关，退出这关改打它")
            raise StageSwitch(chosen)

    # -- pages --------------------------------------------------------------------

    def _entry_point(self) -> tuple[int, int]:
        """The 战术教材 icon above its label on 主页; the fixed place if unread."""
        boxes = self._reference_boxes(self.capture_frame(), HOME_ENTRY_ROI, "主页战术教材入口")
        for box in boxes:
            x = word_centre(box, HOME_ENTRY_WORDS)
            if x is not None:
                return round(x), round(box.y - HOME_ICON_ABOVE_LABEL)
        return HOME_ENTRY_POINT

    def _list_visible(self, frame=None) -> bool:
        frame = self.capture_frame() if frame is None else frame
        return self._title_visible(frame, TITLE_KEYWORDS, LABEL) and not self._popup_visible(frame)

    def _popup_visible(self, frame=None, stage: int | None = None) -> bool:
        frame = self.capture_frame() if frame is None else frame
        text = self._text_in(frame, POPUP_TITLE_ROI, "关卡标题")
        found = re.search(r"关卡\s*(\d)", text.replace("關", "关"))
        if found is None:
            return False
        return stage is None or int(found.group(1)) == stage

    def _to_list(self) -> bool:
        """Back on the stage list from wherever the last stage left off."""
        for _ in range(3):
            frame = self.capture_frame()
            if self._list_visible(frame):
                return True
            if self._popup_visible(frame):
                self._click_reference(*POPUP_CLOSE_POINT, after_sleep=1.0)  # 不用确认：下面再看
                continue
            if self._press_back_on_result(frame):
                continue
            self.tap_escape(after_sleep=1.5)
        if self._wait_for_title(LABEL, TITLE_KEYWORDS, timeout=STUCK_SECONDS, quiet=True):
            return True
        # Last way back: home and in again.
        self.log_info(f"{LABEL}：回不到关卡列表，回主页重新进去")
        return self._open_page_from_home(LABEL, self._entry_point, TITLE_KEYWORDS)

    def _read_marks(self) -> dict[int, bool]:
        """Stage -> cleared, from the ✕ on each tile (stages it can't tell are left out).

        A ✕ fades in about a second after the list shows (2K PC 2026-10-28:
        a stage just won had none yet), so the list is read twice, a moment
        apart, and a ✕ seen in either read counts."""
        self.sleep(MARKS_SETTLE)
        first = tile_marks(self.capture_frame())
        self.sleep(MARKS_SETTLE)
        marks = merge_marks(first, tile_marks(self.capture_frame()))
        unsure = [stage for stage in range(1, stages.STAGE_COUNT + 1) if stage not in marks]
        note = f"，认不准的照记录：{unsure}" if unsure else ""
        self.log_info(
            f"{LABEL}：关卡列表上打过的：{[s for s, c in marks.items() if c] or '无'}{note}"
        )
        return marks

    def _open_stage(self, stage: int) -> bool:
        for entry in range(OPEN_TRIES):
            if entry and not self._to_list():
                break
            fight = self._enter_stage(stage)
            if fight is not True:
                return False
            if not self._auto_battle_visible():
                return True
            self._stop_auto_battle(stage)
            self._leave_fight("游戏自己在自动战斗")
        self._note_why(
            f"第 {stage} 关一进去游戏就在自动战斗，关掉后再进还是一样"
            "（战斗画面右上角 ⟳ 的自动战斗请先关掉）"
        )
        return False

    def _enter_stage(self, stage: int) -> bool:
        """Stage popup → 战斗 → the fight (planning screen, or the game's own auto battle)."""
        self.check_switch()
        x, y = TILE_X[(stage - 1) % 3], TILE_Y[(stage - 1) // 3]
        if not self.press_and_confirm(
            f"第 {stage} 关",
            lambda: self._click_reference(x, y, after_sleep=1.0),
            lambda: self._popup_visible(stage=stage),
            still_before=lambda: self._list_visible(),
            timeout=4.0,
        ):
            self._note_why(f"点了第 {stage} 关，没出现「关卡{stage}」的窗口")
            return False
        button = self._box_with(
            self._reference_boxes(self.capture_frame(), POPUP_BATTLE_ROI, "战斗按钮"),
            BATTLE_KEYWORDS,
        )
        point = (
            (round(button.x + button.width / 2), round(button.y + button.height / 2))
            if button
            else POPUP_BATTLE_POINT
        )
        if button is None:
            self.log_info(f"{LABEL}：没读到「战斗」字，点它的固定位置。")
        if not self.press_and_confirm(
            f"第 {stage} 关「战斗」",
            lambda: self._click_reference(*point, after_sleep=1.5),
            lambda: self._fight_shown(self.capture_frame()),
            still_before=lambda: self._popup_visible(stage=stage),
            timeout=PLANNING_WAIT,
        ):
            self._note_why(f"按了第 {stage} 关的「战斗」，没进到排位画面")
            return False
        return True

    def _fight_shown(self, frame) -> bool:
        return fight_vision.planning_visible(frame) or self._auto_battle_visible(frame)

    def _auto_battle_visible(self, frame=None) -> bool:
        frame = self.capture_frame() if frame is None else frame
        text = self._text_in(frame, AUTO_BATTLE_ROI, "自动战斗中") + self._text_in(
            frame, AUTO_BATTLE_STOP_ROI, "结束自动战斗"
        )
        return keyword_match_count(text, AUTO_BATTLE_WORDS, fuzzy_ratio=0.8) >= 1

    def _stop_auto_battle(self, stage: int) -> None:
        """End the game's auto battle (it stays off for the next fights); the
        turn being fought plays out, then the planning screen or the result."""
        self.log_info(
            f"{LABEL}：第 {stage} 关一进去游戏就在自己打（左下「自动战斗中」），"
            "按右下「结束自动战斗」关掉，退出这关重进，照轴从第 1 回合打"
        )
        self._press_text(
            "结束自动战斗", AUTO_BATTLE_STOP_ROI, AUTO_BATTLE_STOP_WORDS, AUTO_BATTLE_STOP_POINT
        )
        if not self._wait_for(lambda: not self._auto_battle_visible(), timeout=STUCK_SECONDS):
            self.log_info(f"{LABEL}：「结束自动战斗」点了还在，按它下面写的 Esc")
            self.tap_escape(after_sleep=1.0)
        if not self._wait_for(self._turn_or_result, timeout=PLANNING_WAIT):
            self.log_info(f"{LABEL}：关掉自动战斗后没等到排位画面或结算")

    def _turn_or_result(self) -> bool:
        frame = self.capture_frame()
        return (
            fight_vision.planning_visible(frame)
            or fight_vision.defeat_band(frame)
            or fight_vision.victory_visible(frame)
            or fight_vision.battle_end_visible(frame)
        )

    def _press_back_on_result(self, frame) -> bool:
        if fight_vision.defeat_band(frame):
            boxes = self._reference_boxes(frame, DEFEAT_BACK_ROI, "返回")
            box = self._box_with(boxes, BACK_KEYWORDS)
            if box is not None:
                self._click_reference_box(box, after_sleep=2.0)  # 不用确认：接着等关卡列表
            else:
                self._click_reference(
                    *DEFEAT_BACK_POINT, after_sleep=2.0
                )  # 不用确认：接着等关卡列表
            return True
        if not (fight_vision.victory_visible(frame) or fight_vision.battle_end_visible(frame)):
            boxes = self._reference_boxes(frame, RESULT_BACK_ROI, "返回")
            if self._box_with(boxes, BACK_KEYWORDS) is None:
                return False
        self._click_reference(*RESULT_BACK_POINT, after_sleep=2.0)  # 不用确认：接着等关卡列表
        return True

    def _back_to_list(self) -> bool:
        self._set_step(self.stage_picker.current, None)
        for _ in range(3):
            if self._wait_for(self._list_visible, timeout=1.5):
                return True
            self._press_back_on_result(self.capture_frame())
        return self._wait_for(self._list_visible, timeout=STUCK_SECONDS)

    def _leave_fight(self, why: str) -> None:
        """Out of the stage, back to the list (Leo: 「最少你要把那關停掉」).

        The game's own way out (2K PC 2026-10-28, stage 5): ‖ top right →
        暂停 → 离开 → 「是否中断当前进行中的战斗？」 确认.  Esc does nothing
        in a fight; it is only the last try before going home and back in.
        Already on the list (a stage picked between stages): nothing to leave."""
        frame = self.capture_frame()
        if self._list_visible(frame):
            self._fighting = None
            return
        self._fighting = None
        if self._press_back_on_result(frame):
            if self._back_to_list():
                return
        if self._leave_by_pause():
            return
        for _ in range(2):
            if self._list_visible():
                return
            self.tap_escape(after_sleep=1.5)
        if not self._list_visible():
            self.log_warning(f"{LABEL}：退不出这关（{why}），回主页")
            from src.tasks.recovery import recover_to_home

            recover_to_home(self)

    def leave_after_step_in(self) -> None:
        """继续 after the player used the paused game, before the way home:
        out of the fight the game's own way (‖ → 离开 → 确认).  The way home
        presses back, H and Esc, which do nothing in a fight (Leo's 4K
        2026-10-28 「他也沒有第一時間點esc或這右上角的暫停圖示 而是嘗試點左上角
        甚麼都沒有的返回」).  The run then starts again from 主页 with what
        was left of it: the stage picked on the bar first, else the ticked
        stages not won yet."""
        from src.tasks.recovery import home_now

        self._resume_pick, self.stage_picker.chosen = self.stage_picker.chosen, None
        if self._plan is not None and self.chosen_stages is None:
            self.chosen_stages = [s for s in self._plan if self._results.get(s) != "won"]
        if self._fighting is None and not self._pause_visible():
            return
        if home_now(self):
            self._fighting = None
            return
        self.log_info(f"{LABEL}：暂停时你动了游戏，先按右上角暂停 → 离开退出这关")
        self._leave_fight("暂停时你动了游戏")

    def _pause_visible(self) -> bool:
        text = self._text_in(self.capture_frame(), PAUSE_TITLE_ROI, "暂停")
        return keyword_match_count(text, PAUSE_KEYWORDS, fuzzy_ratio=0.8) >= 1

    def _leave_dialog_visible(self) -> bool:
        text = self._text_in(self.capture_frame(), LEAVE_DIALOG_ROI, "离开确认")
        return keyword_match_count(text, LEAVE_QUESTION_KEYWORDS, fuzzy_ratio=0.8) >= 1

    def _leave_by_pause(self) -> bool:
        if not self._pause_visible():
            self._click_reference(*PAUSE_POINT, after_sleep=1.0)  # 不用确认：下面等暂停画面
            if not self._wait_for(self._pause_visible, timeout=4.0):
                self.log_info(f"{LABEL}：按了右上角暂停，没出现暂停画面")
                return False
        self._press_text("离开", PAUSE_LEAVE_ROI, LEAVE_WORDS, PAUSE_LEAVE_POINT)
        if not self._wait_for(self._leave_dialog_visible, timeout=4.0):
            self.log_info(f"{LABEL}：按了离开，没出现「是否中断」")
            return False
        self._press_text("确认", LEAVE_DIALOG_ROI, CONFIRM_WORDS, LEAVE_CONFIRM_POINT)
        if self._wait_for(self._list_visible, timeout=PLANNING_WAIT):
            return True
        self.log_info(f"{LABEL}：确认离开后没回到关卡列表")
        return False

    def _press_text(self, label: str, roi, words: tuple[str, ...], point: tuple[int, int]) -> None:
        """A harmless button by its text, else at its fixed place."""
        box = self._box_with(self._reference_boxes(self.capture_frame(), roi, label), words)
        if box is None:
            self.log_info(f"{LABEL}：没读到「{label}」，点它的固定位置。")
            self._click_reference(*point, after_sleep=1.0)  # 不用确认：调用处等下一个画面
        else:
            self._click_reference_box(box, after_sleep=1.0)

    def _claim_missions(self) -> bool | None:
        if not self._to_list():
            self._note_why("回不到关卡列表，没领任务奖励")
            return False
        box = self._box_with(
            self._reference_boxes(self.capture_frame(), MISSION_ROI, "任务"), MISSION_KEYWORDS
        )
        point = (
            (round(box.x + box.width / 2), round(box.y + box.height / 2)) if box else MISSION_POINT
        )
        self._click_reference(*point, after_sleep=1.5)  # 不用确认：下面找全部获得
        if not self._claim_all("任务", MISSION_CLAIM, TITLE_KEYWORDS):
            return False
        from src.tasks.claim_page import CLAIM_PRESSED

        claimed = getattr(self, "_claim_outcome", None) == CLAIM_PRESSED
        self.tap_escape(after_sleep=1.0)
        return True if claimed else None

    def _text_in(self, frame, roi, name: str) -> str:
        return self._boxes_text(self._reference_boxes(frame, roi, name))

    def _wait_for(self, check, timeout: float, interval: float = 0.5) -> bool:
        # The shared wait (looks at least once), not one of its own (test_press_guard).
        return bool(wait_for(check, timeout, sleep=self.sleep, poll=interval))


# Leaving a fight (2K PC 2026-10-28): ‖ top right, the 暂停 screen's 离开
# (beside 重新挑战 and 点击继续), then 「是否中断当前进行中的战斗？」 取消 / 确认.
PAUSE_POINT = (1791, 53)
PAUSE_TITLE_ROI = (840, 190, 240, 70)
PAUSE_KEYWORDS = ("暂停", "暫停")
PAUSE_LEAVE_ROI = (690, 975, 220, 60)
PAUSE_LEAVE_POINT = (797, 1005)
LEAVE_WORDS = ("离开", "離開")
LEAVE_DIALOG_ROI = (700, 430, 520, 220)
LEAVE_QUESTION_KEYWORDS = ("是否中断", "是否中斷", "进行中的战斗", "進行中的戰鬥")
LEAVE_CONFIRM_POINT = (1044, 611)
CONFIRM_WORDS = ("确认", "確認")
# 主页's way in: the event banner on the right (to be measured).
# 主页: the 战术教材 icon in the top-right row (战术教材 / 通行证 / 快速狩猎 on
# the 2K clone 2026-10-28, icon at 1562,262 over its label).  Event icons
# come and go in that row, so its label is read first and the icon above it
# pressed; the fixed place is the fallback.
HOME_ENTRY_POINT = (1562, 262)
HOME_ENTRY_ROI = (1300, 280, 610, 52)
HOME_ENTRY_WORDS = ("战术教材", "戰術教材")
HOME_ICON_ABOVE_LABEL = 43


def word_centre(box, words: tuple[str, ...]) -> float | None:
    """x of one of ``words`` inside an OCR box, which may hold the labels of
    neighbouring icons too (主页 2K clone: 「战术教材通行证快速狩猎」 as one
    box): the share of the text before the word, of the box's width."""
    text = str(getattr(box, "name", "") or "")
    for word in words:
        start = text.find(word)
        if start >= 0:
            return box.x + box.width * (start + len(word) / 2) / len(text)
    return None


@lru_cache(maxsize=1)
def _cleared_x() -> np.ndarray:
    return cv2.imdecode(np.fromfile(CLEARED_X, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)


def cleared_tile(tile: np.ndarray) -> bool | None:
    """A tile (reference px, TILE_HALF each way) crossed out with the big ✕;
    None when it can't tell."""
    template = _cleared_x()
    if tile.shape[0] < template.shape[0] or tile.shape[1] < template.shape[1]:
        return None
    gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY) if tile.ndim == 3 else tile
    score = float(template_match_response(gray, template, zero_mean=True).max())
    if score >= CLEARED_MIN:
        return True
    if score <= NOT_CLEARED_MAX:
        return False
    return None


def merge_marks(*reads: dict[int, bool]) -> dict[int, bool]:
    """A ✕ in any read is cleared; not cleared only when a read says so and none saw a ✕."""
    marks: dict[int, bool] = {}
    for read in reads:
        for stage, cleared in read.items():
            marks[stage] = marks.get(stage, False) or cleared
    return marks


def tile_marks(frame: np.ndarray) -> dict[int, bool]:
    """Stage -> cleared, read from each tile of the list (unsure ones left out)."""
    reference = cv2.resize(frame[:, :, :3], (1920, 1080), interpolation=cv2.INTER_AREA)
    marks = {}
    for index in range(stages.STAGE_COUNT):
        x, y = TILE_X[index % 3], TILE_Y[index // 3]
        seen = cleared_tile(reference[y - TILE_HALF : y + TILE_HALF, x - TILE_HALF : x + TILE_HALF])
        if seen is not None:
            marks[index + 1] = seen
    return marks


class TalosScreen(GameFightScreen):
    """The fight screen that tells the task which turn it is on (status bar)
    and lets a stage picked while paused take over at a turn's start or
    before the next move (Leo paused while the cells were being placed,
    2026-10-28): never in the middle of a drag."""

    def __init__(self, task: TalosTask, stage: int, *args, **kwargs):
        super().__init__(task, *args, **kwargs)
        self.stage = stage

    def read_turn(self) -> int | None:
        self.task.check_switch()
        turn = super().read_turn()
        if turn is not None:
            self.task._set_step(self.stage, turn)
        return turn

    def drag(self, drag) -> None:
        self.task.check_switch()
        super().drag(drag)

    def pick_skill(self, slot: int, skill: str) -> bool:
        self.task.check_switch()
        return super().pick_skill(slot, skill)

    def press_battle(self) -> None:
        self.task.check_switch()
        super().press_battle()
