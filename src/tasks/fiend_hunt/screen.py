"""The live 魔兽追踪者 planning screen, for replay_fight and record_fight.

Reading a turn (top-down view, nobody selected to start with):
  * TURN on the BATTLE pill, TEAM1/TEAM2 top-left, how many list slots
    are filled and which of them say OUT (dead units drop to the bottom);
  * who stands where: holding a unit's cell selects it, which puts white
    brackets round its list portrait (that is its slot in the 1-N order)
    and its name top-left, and opens its card column (the chosen card is
    lit).  One hold gives cell, slot, name and action together.
    Cells are held in a useful order (where the units were last seen or
    are expected, then busy-looking cells) and holding stops as soon as
    every living slot has been found, so a turn usually costs one hold
    per unit instead of twelve.  A slot found twice, a name that doesn't
    snap to a known unit, or slots left over after all twelve cells
    raise ScreenReadError: 认不准就不按.

Checking cards on a recorded turn (same_card): one capture of the list,
taken with nobody selected once no entry is being swept by the glow that
follows a pick, answers every slot against the same slot of the saved
screenshot; any mouse action drops it, so a comparison after a pick sees
the new card.

Moves are posted mouse messages with the cursor following them, the way
BD2Interaction.post_swipe does, because the game samples the cursor.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Literal, Protocol

import cv2
import numpy as np

from src.tasks.fiend_hunt import costumes, layout, vision
from src.tasks.fiend_hunt.fight import ListGlance, ScreenReadError
from src.tasks.fiend_hunt.names import settle_name, snap_name
from src.tasks.fiend_hunt.planner import Cell, Drag
from src.tasks.fiend_hunt.record import FightRecord, TurnState, TurnStateError
from src.utils.wait_limits import STUCK_SECONDS

# Timings measured on the 4K PC (2026-09-30, speed probe): a 0.15 s hold
# selected 20/20 and the brackets were on the first capture after release
# (about 0.05 s); a tap on ⇅ cleared them within 0.06 s; a 0.1/0.25 s ⇅ drag
# and a 0.05/0.15 s cell drag landed every time.  About twice those are used,
# and selections are polled for instead of waited for.  2026-10-01: a 0.2 s
# hold (the card column slides in after it anyway) and 4 polls; F8 with 6
# units 5.4 s -> 3.1 s, 14 repeat reads identical.
HOLD_SECONDS = 0.2
# The cursor stays on the cell this long after a release before it is put
# back: the game reads the cursor once a frame, and a release it reads after
# the cursor left selected the unit but opened no card column (2K PC
# 2026-10-07, T19 and T21; ordinary clicks wait 50 ms, these waited 25 ms).
AFTER_RELEASE = 0.12
SELECT_POLLS, POLL_STEP = 4, 0.05  # captures after a hold or tap before giving up
# A cell held again because its first hold selected nobody waits longer for
# the brackets (2K PC 2026-10-07: a unit's cell read as empty twice).
RETRY_SELECT_POLLS = 12
# Captures for the card column to show or a tapped card to light.  A skill
# card with a burst lights 5-6 captures after the column is in (its glow
# fades in): 13-14 captures in all on the 2K PC (2026-10-01), where 12
# made a selection look failed.
CARD_POLLS = 24
PANNED_FOLDER = "拖空截图"  # under the save's folder
PANNED_KEEP = 20  # newest frames kept there (10 drags), so the folder stays small
AUTO_SKILL_GAP = 0.1  # s between the two captures that see the ⟳ spin
AUTO_SKILL_POLLS = 8
# The planning screen fades in after a stage loads: its BATTLE button is there
# while the scenery and the top-right icons are still dark, and a tap then
# does nothing (4K PC 2026-10-28, 塔洛斯 stage 7 with auto skill on: read at
# once, tapped, never turned off; the same tap 8 s later turned it off in
# 0.7 s).  The state counts once two reads AUTO_SKILL_SETTLE_GAP apart agree.
AUTO_SKILL_SETTLE_READS, AUTO_SKILL_SETTLE_GAP = 12, 0.4
AUTO_SKILL_TAPS = 2  # a tap that didn't take is made once more, after a steady read
BOSS_HP_READS, BOSS_HP_GAP = 6, 0.5  # end-screen HP: two equal reads needed
# While reading the grid the lit card is only taken if the column is
# already steady on these captures; otherwise that unit's card is left out
# (a replay checks recorded cards against the screenshot, not this label).
# Recording waits the full CARD_POLLS: the chart shows each card's costume
# (2K PC 2026-10-07: 33 of 77 cards left out with 3, shown as bare 「技能」).
READ_CARD_POLLS = 3
# Captures of the left list until two in a row agree (an arc sweeps an
# entry for about 0.1 s after a pick or a tap on its ⇅): 4K PC 2026-10-01.
LIST_POLLS = 12
AFTER_TAP = 0.4
BURST_STEPS, AFTER_BURST = 4, 0.25  # ◀ ▶ presses per level change; wait after each
AFTER_CLEAR = 0.45  # from a ⇅ tap (clearing a selection) to the next portrait tap
DRAG_HOLD, DRAG_SECONDS, DRAG_STEPS, AFTER_DRAG = 0.15, 0.3, 10, 0.2
SWAP_HOLD, SWAP_SECONDS, SWAP_STEPS, AFTER_SWAP = 0.15, 0.3, 10, 0.25
VIEW_TOGGLE_POLLS, VIEW_SETTLE = 30, 0.15
VIEW_TOGGLE_TAPS = 2  # 切换视角 taps per view change: one more if the first was lost
# The floor must hold still (within FLOOR_STEADY_DIFF grey levels) for
# SETTLE_STEADY captures in a row (about 0.4 s) before the screen is read;
# isometric auras move it by 2 at most, the T13 fade-in by 4-140 after a
# dark start of about 0.17 s.
SETTLE_POLLS, SETTLE_STEADY, FLOOR_STEADY_DIFF = 60, 4, 3.0
AFTER_BATTLE = 1.5
BATTLE_GONE_SECONDS = 6.0
TURN_WAIT_SECONDS = 240.0
# Leo 2026-10-06: a battle screen that hasn't moved for this long is stuck
# (a disconnect dialog, a frozen game): stop instead of waiting the 240 s.
# Leo 2026-10-14 「頂多等8秒到10秒」: was 30 s.
STILL_SECONDS = STUCK_SECONDS
PLANNING_STEADY_SECONDS = 1.0
POLL = 0.3
# 塔洛斯战术教材 (grid_scales): the grid at 100% zoom is drawn 1.31-1.33
# times layout's size (2K PC 2026-10-28).  Leo 「格子對就不動 … 用戶格子導致
# 有問題就用滾輪調整」: a grid of another size is zoomed back, out to the far
# end (78-80%) and in five notches (about 101%), and checked on the 「N%」 bar.
# Below about 95% the bracket search can slip a column (91%: 1.10 for 1.20).
# Leo 2026-10-31 「應該要把格子調整到100 101%左右」: one notch is about 4%
# (97, 101, 105), so the usual size is the 101% notch, 1.29-1.37 (99-103%).
# After the coarse turn the wheel goes one notch at a time, each one checked
# on the 「N%」 bar or, when the bar isn't read, on the grid's own size: a
# player's run (v0.2.24, 1920x1080, 2026-10-31) stopped on 「格子大小还是 1.11」
# after the coarse turn alone.
TALOS_GRID_SCALES = (1.29, 1.37)
ZOOM_OUT_NOTCHES = 8
ZOOM_IN_NOTCHES = 5
ZOOM_OK = (99, 103)
ZOOM_STEPS = 6  # single notches after the coarse turn
WHEEL_POINT = (960 / 1920, 860 / 1080)  # the floor between the sides, above the SP bar
GRID_READS = 3
END_WORD_EVERY = 2.0  # seconds between reads of the end word as text (a lost fight)
# A tombstone makes its cell look busy; bare floor stays below this.
TOMBSTONE_BUSY_MIN = 40.0
# A cell a unit stands on scored 36 or more on the 36 saved top-down turns
# (2026-10-01); a guessed cell below this is held after the busy ones.
EMPTY_LOOKING_MAX = 30.0
NAME_READS = 4  # recording: fresh reads of a name no list has, until two agree
# Names are compared without ASCII: the element icon can read as a stray
# "S"/"C", and the summon's line is 魔法增幅器ET001 (so is its 简中 name on
# souseha) while a hand-made record may say 魔法增幅器.
_ASCII = re.compile(r"[A-Za-z0-9]")


def plain_name(text: str) -> str:
    return _ASCII.sub("", text)


class ScreenInput(Protocol):
    def tap(self, point: layout.Point) -> None: ...

    def hold(self, point: layout.Point, seconds: float) -> None: ...

    def drag(
        self, start: layout.Point, end: layout.Point, hold: float, seconds: float, steps: int
    ) -> None: ...


class _Watched:
    """A ScreenInput that reports every action (it may change the list)."""

    def __init__(self, screen_input: ScreenInput, touched: Callable[[], None]) -> None:
        self._input = screen_input
        self._touched = touched

    def tap(self, point: layout.Point) -> None:
        self._touched()
        self._input.tap(point)

    def hold(self, point: layout.Point, seconds: float) -> None:
        self._touched()
        self._input.hold(point, seconds)

    def drag(
        self, start: layout.Point, end: layout.Point, hold: float, seconds: float, steps: int
    ) -> None:
        self._touched()
        self._input.drag(start, end, hold, seconds, steps)


def load_frame(path: Path) -> np.ndarray | None:
    """A saved screenshot (BGR), or None if it can't be read."""
    try:
        data = np.fromfile(path, dtype=np.uint8)  # imread can't take non-ASCII paths
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def bursts_from_screenshots(
    record: FightRecord,
    folder: str | Path,
    load: Callable[[Path], np.ndarray | None] = load_frame,
) -> FightRecord:
    """The record with each turn's 爆发 levels read off its screenshot's flames.

    For saves made before the levels were stored (their screenshots show
    them); a turn that has levels, or no readable screenshot, is kept.
    """
    turns = dict(record.turns)
    for number, name in record.screenshots.items():
        state = turns[number]
        frame = None if state.bursts else load(Path(folder) / name)
        if frame is None:
            continue
        levels = {unit: _skill_burst(frame, slot) for slot, unit in enumerate(state.order)}
        bursts = {unit: level for unit, level in levels.items() if level is not None}
        turns[number] = replace(state, bursts=bursts)
    return FightRecord(
        turns, record.title, record.source, dict(record.screenshots), dict(record.edited)
    )


def _skill_burst(frame: np.ndarray, slot: int) -> int | None:
    """爆发 level of a list entry on a skill (0: burst off); None on attack or unsure."""
    if not vision.has_skill_icon(frame, slot):
        return None
    return vision.burst_flame(frame, slot)


def _keep_newest(folder: Path, keep: int) -> None:
    """Delete all but the ``keep`` newest PNGs in ``folder`` (Leo 2026-10-01:
    the tool mustn't pile up images)."""
    try:
        files = sorted(folder.glob("*.png"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files[keep:]:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_png(path: Path, frame: np.ndarray) -> None:
    ok, data = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise OSError("PNG 编码失败")
    path.write_bytes(data.tobytes())  # imwrite can't take non-ASCII paths


class PostInput:
    """Posted left-button messages to the game window, cursor following."""

    def __init__(self, task) -> None:
        self.task = task

    def _interaction(self):
        interaction = getattr(self.task.executor, "interaction", None)
        if interaction is None or not hasattr(interaction, "post"):
            raise ScreenReadError("没有可用的鼠标输入")
        return interaction

    def _client(self, point: layout.Point) -> tuple[int, int]:
        width, height = int(self.task.width), int(self.task.height)
        return layout.to_client(point, width, height)

    def _run(self, action: Callable[[], None]) -> None:
        self.task.operate(action, block=True, restore_cursor=True)

    def tap(self, point: layout.Point) -> None:
        self.hold(point, 0.05)

    def hold(self, point: layout.Point, seconds: float) -> None:
        import win32api
        import win32con

        interaction = self._interaction()
        x, y = self._client(point)

        def action() -> None:
            win32api.SetCursorPos(interaction.capture.get_abs_cords(x, y))
            interaction.post(win32con.WM_MOUSEMOVE, 0, win32api.MAKELONG(x, y))
            time.sleep(0.05)
            interaction.post(win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, win32api.MAKELONG(x, y))
            try:
                time.sleep(seconds)
            finally:
                interaction.post(win32con.WM_LBUTTONUP, 0, win32api.MAKELONG(x, y))
                time.sleep(AFTER_RELEASE)

        self._run(action)

    def drag(
        self, start: layout.Point, end: layout.Point, hold: float, seconds: float, steps: int
    ) -> None:
        import win32api
        import win32con

        interaction = self._interaction()
        (x1, y1), (x2, y2) = self._client(start), self._client(end)

        def action() -> None:
            win32api.SetCursorPos(interaction.capture.get_abs_cords(x1, y1))
            interaction.post(win32con.WM_MOUSEMOVE, 0, win32api.MAKELONG(x1, y1))
            time.sleep(0.05)
            interaction.post(
                win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, win32api.MAKELONG(x1, y1)
            )
            try:
                time.sleep(hold)
                for index in range(1, steps + 1):
                    x = round(x1 + (x2 - x1) * index / steps)
                    y = round(y1 + (y2 - y1) * index / steps)
                    win32api.SetCursorPos(interaction.capture.get_abs_cords(x, y))
                    interaction.post(
                        win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, win32api.MAKELONG(x, y)
                    )
                    time.sleep(seconds / steps)
                time.sleep(0.2)
            finally:
                interaction.post(win32con.WM_LBUTTONUP, 0, win32api.MAKELONG(x2, y2))
                time.sleep(AFTER_RELEASE)

        self._run(action)


def task_ocr(task) -> vision.Ocr:
    """The tool's own OCR engine on a small image."""

    def read(image: np.ndarray) -> list[str]:
        boxes = task.ocr(frame=image, threshold=0.3, target_height=0, log=False, name="魔兽站位")
        return [str(box.name) for box in boxes if getattr(box, "name", "")]

    return read


def record_names(record: FightRecord) -> set[str]:
    return {unit for state in record.turns.values() for unit in state.cells}


class GameFightScreen:
    """FightScreen with QuickChecks (and RecordingScreen) on the running game.

    ``known_names`` are the units the fight can contain.  Replay passes the
    saved fight's names and a name that doesn't snap to one of them stops
    the read.  Recording passes ``learn_names=True`` (and a character list
    if there is one, possibly empty): a name no list has is taken as the
    game shows it once two fresh reads agree (names.settle_name).
    ``record`` (optional) orders the holds: the saved cells of the turn
    being read are tried first.  With ``folder``, the record's folder, its
    turn screenshots are what same_card compares with (the next one is
    loaded in the background).  ``read_cards``: whether read_state also
    takes each unit's lit card from its hold (about 0.16 s a unit at 4K);
    off by default when names are learned (screenshot fights); the
    recording task turns it on, as a screenshot can't tell every card.
    """

    def __init__(
        self,
        task,
        known_names: Iterable[str],
        *,
        learn_names: bool = False,
        record: FightRecord | None = None,
        folder: str | Path | None = None,
        screen_input: ScreenInput | None = None,
        capture: Callable[[], np.ndarray] | None = None,
        ocr: vision.Ocr | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = lambda message: None,
        load_screenshot: Callable[[Path], np.ndarray | None] = load_frame,
        read_cards: bool | None = None,
        grid_scales: tuple[float, float] | None = None,
        wheel: Callable[[int], None] | None = None,
    ) -> None:
        self.task = task
        # The grid's usual size range (塔洛斯: TALOS_GRID_SCALES); None: 魔兽, layout's own.
        self.grid_scales = grid_scales
        self.wheel = wheel or self._wheel
        self.known = sorted(set(known_names))
        plain: dict[str, list[str]] = {}
        for name in self.known:
            plain.setdefault(plain_name(name), []).append(name)
        # plain spelling -> the known spelling (two names that only differ in ASCII: unusable)
        self._spelling = {key: names[0] for key, names in plain.items() if key and len(names) == 1}
        self.learn_names = learn_names
        self.read_cards = not learn_names if read_cards is None else read_cards
        if not self.known and not learn_names:
            raise ValueError("没有可对照的角色名")
        self.record = record
        self.folder = Path(folder) if folder is not None else None
        self.load_screenshot = load_screenshot
        self.input = _Watched(screen_input or PostInput(task), self._list_changed)
        self.capture = capture or task.capture_frame
        self.ocr = ocr or task_ocr(task)
        self.sleep = sleep or task.sleep
        self.clock = clock
        self.log = log
        self.last_cells: dict[int, dict[str, Cell]] = {}  # team -> where units were last seen
        self.holds = 0  # cells held in the last read_state
        # list slot -> label of its lit card, as last seen; dropped by anything
        # that can change a slot's unit or action (drag, ⇅, team, BATTLE)
        self.card_labels: dict[int, str] = {}
        self.pick_problem = ""  # why the last pick_skill failed, for the stop message
        # Recording keeps each unit's open card column here (Leo 2026-10-06:
        # to tell which costume each skill card is, for the character list).
        self.cards_folder: Path | None = None
        # unit -> card label -> costume id, as told from the card columns seen
        # on this PC (costumes.py); the lit costume of each slot in the last read.
        self.learn_costumes = False  # recording: tell each read card's costume
        self.unit_cards: dict[str, dict[str, str]] = {}
        self._read_costumes: dict[int, str] = {}
        self._list_frame: np.ndarray | None = None  # steady list for same_card
        self._saved_frames: dict[int, Future] = {}  # turn -> its screenshot, loading
        self._files = ThreadPoolExecutor(max_workers=1, thread_name_prefix="魔兽站位截图")
        self._writing: Future | None = None
        # The frame just before the last drag, kept to show what a drag that
        # panned the camera started on (twice in real fights, 2026-10-01).
        self._before_drag: tuple[np.ndarray, Drag] | None = None
        self._cleared_at = float("-inf")  # clock of the last ⇅ tap that cleared a selection
        # The grid as drawn when it isn't where layout has it (zoomed with the
        # mouse wheel or moved, 4K PC 2026-10-08): cells are pressed there.
        self._grid: vision.Grid | None = None
        # How the last fight ended: "battle_end" (魔兽追踪者), "victory" or
        # "lost" (塔洛斯战术教材); None while it goes on.
        self.end_word: str | None = None

    # --- FightScreen ------------------------------------------------------------------

    def read_turn(self) -> int | None:
        frame = self.capture()
        if not vision.planning_visible(frame):
            return None
        return vision.read_turn(frame, self.ocr)

    def team_of(self, frame: np.ndarray) -> int | None:
        """TEAMn top-left; 1 in a fight without teams (塔洛斯战术教材: no TEAMn,
        the button bottom-left reads 「更换」); None when unsure."""
        team = vision.read_team(frame, self.ocr)
        if team is None and vision.single_team(frame, self.ocr):
            return 1
        return team

    def read_state(self, turn: int) -> TurnState:
        frame = self._ready_frame()
        live_turn = vision.read_turn(frame, self.ocr)
        if live_turn is None:
            raise ScreenReadError("读不到回合数")
        team = self.team_of(frame)
        if team is None:
            raise ScreenReadError("读不到 TEAM1/TEAM2/TEAM3")
        count = vision.slot_count(frame)
        if count < 1:
            raise ScreenReadError("左侧列表读不清")
        out = vision.out_slots(frame, count)
        living = count - len(out)
        if out != list(range(living, count)):
            raise ScreenReadError(f"OUT 不在列表底部：{[slot + 1 for slot in out]}")

        self.card_labels.clear()
        self._read_costumes = {}
        slot_names, cells, empty, stones, labels = self._read_grid(
            frame, live_turn, team, living, need_all=bool(out)
        )
        dead_names = [self._read_dead_name(slot) for slot in out]
        cells.update({dead_names[out.index(slot)]: cell for slot, cell in stones.items()})
        unplaced = [name for slot, name in zip(out, dead_names) if slot not in stones]
        cells.update(self._tombstones(frame, live_turn, unplaced, empty))
        order = tuple(slot_names[slot] for slot in range(living))
        skills = {slot_names[slot]: label for slot, label in labels.items()}
        worn = {slot_names[slot]: costume for slot, costume in self._read_costumes.items()}
        try:
            state = TurnState(
                turn=live_turn,
                team=team,
                order=order,
                cells=cells,
                dead=frozenset(dead_names),
                skills=skills,
                costumes=worn,
            )
        except TurnStateError as error:
            raise ScreenReadError(str(error)) from error
        self.last_cells[team] = {unit: cells[unit] for unit in order}
        self.log(
            f"第 {live_turn} 回合 TEAM{team}：顺序 {'、'.join(order)}；"
            f"按住 {self.holds} 格；阵亡 {'、'.join(dead_names) or '无'}；"
            f"行动 {'、'.join(unit + skills.get(unit, '（没读）') for unit in order)}"
        )
        return state

    # --- QuickChecks ------------------------------------------------------------------

    def glance(self) -> ListGlance | None:
        """Team, list length and OUT marks from one screenshot.

        Also turns the view top-down and clears a selection, so lit_slot
        can follow; neither moves anyone.
        """
        try:
            frame = self._ready_frame()
        except ScreenReadError:
            return None
        team = self.team_of(frame)
        count = vision.slot_count(frame)
        if team is None or count < 1:
            return None
        out = vision.out_slots(frame, count)
        if out != list(range(count - len(out), count)):
            return None
        return ListGlance(team, count, len(out))

    def lit_slot(self, cell: Cell) -> int | None:
        """Hold ``cell``: the list slot its unit is selected in (then cleared)."""
        slot, unmarked, frame = self._hold_cell(cell, read_name=False)
        if slot is None and unmarked is not None:
            self._keep_picture(frame, "fiend-grid")
            raise ScreenReadError(f"按住 {unmarked} 后，认不出左边选中的是第几位")
        if slot is not None:
            row = vision.lit_card(frame)
            if row is not None:
                self.card_labels[slot] = vision.card_label(row)
            self._clear_selection(frame)
        return slot

    def skill_of(self, slot: int) -> str | None:
        """Label of the lit card of list slot ``slot`` (攻击/击退/技能n); None when unsure."""
        if slot in self.card_labels:
            return self.card_labels[slot]
        column = self._select_slot(slot)
        if column is None:
            return None
        frame, _, row = column
        self._clear_selection(frame)
        self.card_labels[slot] = vision.card_label(row)
        return self.card_labels[slot]

    def same_card(self, turn: int, slot: int) -> bool | None:
        """Whether list slot ``slot`` shows the card it has in turn ``turn``'s screenshot.

        None when unsure, or when the turn has no screenshot to compare with.
        """
        saved = self._saved_frame(turn)
        if saved is None:
            return None
        if self._list_frame is None:
            frame = self._steady_list()
            if frame is None:
                return None
            self._list_frame = frame
        if slot >= vision.slot_count(self._list_frame) or slot >= vision.slot_count(saved):
            return None
        answer = vision.same_card(self._list_frame, slot, saved, slot)
        # The screenshot on a skill and the entry on one too, or unclear (4K PC
        # 2026-10-01, 尤里光盾 TURN 21: 芮彼泰雅's white hair ornaments sit where
        # the icon would): the open card column tells.
        if answer is not True and vision.has_skill_icon(saved, slot) is True:
            if vision.has_skill_icon(self._list_frame, slot) is not False:
                return self._same_skill_in_column(slot, saved)
        if answer is None:
            self._list_frame = None  # a second look takes a new capture
        return answer

    def _same_skill_in_column(self, slot: int, saved: np.ndarray) -> bool | None:
        """Both entries on a skill, but the faces differ: same skill in another skin?

        A skin only changes the costume's art, not its skill or icon (Leo
        2026-10-01), so the face no longer tells.  The unit's column is opened
        and the card with the saved entry's icon looked for: lit, it is the
        same card.  Leaves nobody selected; None when unsure.
        """
        self._list_frame = None  # selecting changes the list
        column = self._select_slot(slot)
        if column is None:
            return None
        frame, count, lit = column
        if lit is not None and lit < layout.FIRST_SKILL_ROW:
            self._clear_selection(self.capture())
            return False  # attack or 击退 lit, the screenshot shows a skill
        row = vision.card_like(frame, count, saved, slot)
        self._clear_selection(self.capture())
        if row is None or lit is None:
            return None
        if row == lit:
            self.log(f"列表第 {slot + 1} 位头像跟存档不同，技能图标相同：换了皮肤，当作同一张卡")
        return row == lit

    def switch_team(self, team: int) -> bool:
        """Change to ``team``, one team at a time (更换队伍 is one-way; a fight
        may have a third team, Leo 2026-10-01).  False if a step doesn't move on."""
        frame = self._ready_frame()
        current = self.team_of(frame)
        for _ in range(len(vision.TEAMS)):
            if current == team:
                return True
            if current is None or current > team:
                return False
            self.card_labels.clear()
            self.input.tap(layout.CHANGE_TEAM)
            self.sleep(1.0)
            frame = self.capture()
            if "更换队伍" not in vision.read_dialog_title(frame, self.ocr).replace(" ", ""):
                return False
            self.input.tap(layout.TEAM_DIALOG_CONFIRM)
            self.sleep(2.0)
            try:
                frame = self._ready_frame()
            except ScreenReadError:
                return False
            after = vision.read_team(frame, self.ocr)
            if after is None or after <= current:
                return False
            current = after
        return current == team

    def swap_order(self, first: int, second: int) -> None:
        self.card_labels.clear()
        self.input.drag(
            layout.slot_swap(second), layout.slot_swap(first), SWAP_HOLD, SWAP_SECONDS, SWAP_STEPS
        )
        self.sleep(AFTER_SWAP)

    def drag(self, drag: Drag) -> None:
        self.card_labels.clear()
        self._before_drag = (self.capture(), drag)
        self.input.drag(
            self._press(drag.source),
            self._press(drag.target),
            DRAG_HOLD,
            DRAG_SECONDS,
            DRAG_STEPS,
        )
        self.sleep(AFTER_DRAG)
        self._clear_selection(self.capture())  # the dragged unit stays selected

    def pick_skill(self, slot: int, skill: str) -> bool:
        """Select list slot ``slot`` and light its card ``skill``; True once seen lit.

        A bare 技能 (a chart's "whichever skill the costume order put up")
        is only picked when the unit has one skill card.
        """
        self.card_labels.pop(slot, None)
        self.pick_problem = ""
        column = self._select_slot(slot)
        if column is None:
            return False
        frame, count, lit = column
        row = self._card_row(skill, count)
        done, frame = (False, frame) if row is None else self._light(slot, frame, lit, row)
        self._clear_selection(frame)
        if row is None:
            # Leo 2026-10-06: the player must own the costumes the save uses.
            skills = max(count - layout.FIRST_SKILL_ROW, 0)
            self.pick_problem = f"只有 {skills} 张技能卡，服装技能和录的时候不一样"
        elif not done:
            self.pick_problem = "点不亮，可能 SP 不够或技能还在冷却"
        if not done:
            self.log(f"列表第 {slot + 1} 位点不亮 {skill}：{self.pick_problem}")
            return False
        self.card_labels[slot] = vision.card_label(row)
        return True

    def _light(self, slot: int, frame: np.ndarray, lit: int, row: int) -> tuple[bool, np.ndarray]:
        """Tap card ``row`` of the open column until it is lit.  A card on cooldown
        just doesn't light; telling it by its grey look misread a dark costume
        art as greyed (杰尼斯 技能1, 2K PC 2026-10-01), so every card is tapped."""
        if lit == row:
            return True, frame
        self.input.tap(layout.card_tap(row))
        column = self._column(slot, row)
        return column is not None, self.capture() if column is None else column[0]

    def saved_attack(self, turn: int, slot: int) -> bool | None:
        """Whether turn ``turn``'s screenshot has list slot ``slot`` on attack or
        击退 (no skill icon, no SP)."""
        saved = self._saved_frame(turn)
        if saved is None:
            return None
        icon = vision.has_skill_icon(saved, slot)
        return None if icon is None else not icon

    def saved_action(self, turn: int, slot: int) -> str | None:
        """攻击 / 击退 / 技能 as turn ``turn``'s screenshot shows list slot ``slot``."""
        saved = self._saved_frame(turn)
        return None if saved is None else vision.list_action(saved, slot)

    def pick_like(self, turn: int, slot: int) -> str | None:
        """fix_like without a burst, leaving nobody selected."""
        card = self.fix_like(turn, slot)
        self.clear_selection()
        return card

    def fix_like(self, turn: int, slot: int, burst: int | None = None) -> str | None:
        """Light list slot ``slot``'s card that turn ``turn``'s screenshot shows, in
        one go: attack when the entry has no icon, 击退 when it shows the arrow,
        else the skill card with the same icon; on a skill, also step its 爆发 to ``burst`` while it is
        selected.  The unit is left selected, so the next unit is selected
        straight from it (no ⇅ tap and wait between units); clear_selection
        when done.  The card's label, or None when that can't be told."""
        saved = self._saved_frame(turn)
        action = None if saved is None else vision.list_action(saved, slot)
        if action is None:
            return None
        self.card_labels.pop(slot, None)
        column = self._select_slot(slot, chain=True)
        if column is None:
            return None
        frame, count, lit = column
        row = vision.card_row(action)
        if action == vision.SKILL_LABEL:
            row = vision.card_like(frame, count, saved, slot, lenient=True)
        if row is None:
            return None
        done, frame = self._light(slot, frame, lit, row)
        if not done:
            self.log(f"列表第 {slot + 1} 位点不亮 {vision.card_label(row)}")
            return None
        if burst is not None and row >= layout.FIRST_SKILL_ROW:
            self._step_burst(slot, frame, row, burst)  # a level left wrong: _set_bursts stops
        self.card_labels[slot] = vision.card_label(row)
        return self.card_labels[slot]

    def auto_skill_state(self) -> bool | None:
        """The auto-skill icon's state from two captures: on (blue dot, ⟳ spinning),
        off (neither), None off the planning screen or when the two disagree."""
        first = self.capture()
        self.sleep(AUTO_SKILL_GAP)
        second = self.capture()
        if not (vision.planning_visible(first) and vision.planning_visible(second)):
            return None
        if not vision.icons_lit(second):
            return None  # still fading in: dark icons read as off
        dot = vision.auto_skill_on(second)
        if dot != vision.auto_skill_turning(first, second):
            return None
        return dot

    def boss_hp(self) -> tuple[int, int] | None:
        """(HP left, full HP) under BATTLE END once two captures read the same."""
        last = None
        for _ in range(BOSS_HP_READS):
            frame = self.capture()
            hp = vision.read_boss_hp(frame, self.ocr) if vision.battle_end_visible(frame) else None
            if hp is not None and hp == last:
                return hp
            last = hp
            self.sleep(BOSS_HP_GAP)
        return None

    def steady_auto_skill_state(self) -> bool | None:
        """The auto-skill state once two reads in a row agree (None: never)."""
        last = None
        for _ in range(AUTO_SKILL_SETTLE_READS):
            state = self.auto_skill_state()
            if state is not None and state == last:
                return state
            last = state
            self.sleep(AUTO_SKILL_SETTLE_GAP)
        return None

    def set_auto_skill(self, on: bool) -> bool:
        """Switch the auto-skill icon (top right, the diamond) on or off with a
        tap where needed; True once both its colour and its spin show that way."""
        state = self.steady_auto_skill_state()
        for _ in range(AUTO_SKILL_TAPS):
            if state is None:
                return False
            if state == on:
                return True
            # Posted taps only reach the game while it is in front (a tap sent
            # with another window in front was lost, 2K PC 2026-10-01).
            bring = getattr(self.task, "_bring_game_to_foreground", None)
            if callable(bring) and not bring():
                raise ScreenReadError("游戏窗口不在最前面")
            self.input.tap(layout.AUTO_SKILL)
            for _ in range(AUTO_SKILL_POLLS):
                self.sleep(POLL_STEP)
                if self.auto_skill_state() == on:
                    return True
            # Read again before another tap: one that took late must not be undone.
            state = self.steady_auto_skill_state()
        return state == on

    def clear_selection(self) -> None:
        self._clear_selection(self.capture())

    # --- ShotScreen (shots.py: fighting from screenshots alone) ------------------------

    def list_frame(self) -> np.ndarray | None:
        return self._steady_list()

    def card_column(self, slot: int) -> tuple[np.ndarray, int, int] | None:
        return self._select_slot(slot)

    def grid_frame(self) -> np.ndarray:
        return self._ready_frame()

    def set_preempt(self, slot: int, skill: str) -> bool:
        """Select slot ``slot`` and turn on the 「先发制人」 beside its ``skill``
        card; True once the switch shows on."""
        column = self._select_slot(slot)
        if column is None:
            raise ScreenReadError(f"选不到第 {slot + 1} 个角色，开不了先发制人")
        frame, cards, _ = column
        row = vision.card_row(skill)
        if row is None or row >= cards or not vision.preempt_beside(frame, self.ocr, row):
            self._clear_selection(self.capture())
            raise ScreenReadError(f"第 {slot + 1} 个角色的{skill}旁边找不到「先发制人」")
        done = vision.preempt_on(frame, row)
        for _ in range(2):
            if done:
                break
            self.input.tap(layout.preempt_switch(row))
            frame = self._poll(lambda now: vision.preempt_on(now, row))
            done = vision.preempt_on(frame, row)
        self._clear_selection(self.capture())
        return done

    def set_burst(self, slot: int, level: int) -> bool:
        """Select list slot ``slot`` and step its lit skill card's 爆发 to ``level``."""
        column = self._select_slot(slot)
        if column is None:
            return False
        frame, _, row = column
        done = row >= layout.FIRST_SKILL_ROW and self._step_burst(slot, frame, row, level)
        self._clear_selection(self.capture())
        return done

    def _step_burst(self, slot: int, frame: np.ndarray, row: int, level: int) -> bool:
        """Press ◀ / ▶ on the lit skill card ``row`` until its BURST is ``level``."""
        now = self._burst(frame)
        for _ in range(BURST_STEPS):
            if now == level:
                break
            self.input.tap(layout.burst_tap(row, up=now < level))
            self.sleep(AFTER_BURST)
            now = self._burst(self.capture())
        if now != level:
            self.log(f"列表第 {slot + 1} 位爆发调不到 {level}（现在 {now}）")
        return now == level

    def burst_shown(self, slot: int) -> int | None:
        """爆发 level list slot ``slot``'s flame shows (0: none); None when unsure."""
        if self._list_frame is None:
            self._list_frame = self._steady_list()
        if self._list_frame is None:
            return None
        return vision.burst_flame(self._list_frame, slot)

    def read_bursts(self, state: TurnState) -> dict[str, int]:
        """爆发 level of each unit on a skill (recording): from the list's flames,
        and from the selected card's header where a flame is unclear."""
        frame = self._steady_list() if self._list_frame is None else self._list_frame
        frame = self.capture() if frame is None else frame
        bursts: dict[str, int] = {}
        for slot, unit in enumerate(state.order):
            icon = vision.has_skill_icon(frame, slot)
            if icon is False:
                continue  # on attack: no level
            flame = vision.burst_flame(frame, slot) if icon else None
            if flame is not None:
                bursts[unit] = flame
                continue
            column = self._select_slot(slot)
            if column is None:
                continue
            shown, _, row = column
            level = self._burst(shown) if row >= layout.FIRST_SKILL_ROW else None
            if level is not None:
                bursts[unit] = level
            self._clear_selection(self.capture())
        return bursts

    def _burst(self, frame: np.ndarray) -> int:
        """The lit skill card's BURST n; 0 when the header shows none (burst off:
        ◀ from BURST 1 removes it, 2K PC 2026-10-01).  Read twice before 0."""
        level = vision.read_burst(frame, self.ocr)
        if level is None:
            self.sleep(AFTER_BURST)
            level = vision.read_burst(self.capture(), self.ocr)
        return level or 0

    def press_battle(self) -> None:
        self.card_labels.clear()
        frame = self.capture()
        self._clear_selection(frame)
        frame = self.capture()
        if not vision.planning_visible(frame) or vision.selected_slots(frame):
            raise ScreenReadError("按 BATTLE 前画面不对")
        self.input.tap(layout.BATTLE)
        self.sleep(AFTER_BATTLE)

    def wait_after_battle(self) -> Literal["planning", "end"] | None:
        deadline = self.clock() + BATTLE_GONE_SECONDS
        while vision.planning_visible(self.capture()):
            if self.clock() > deadline:
                self.log("按了 BATTLE 但战斗没开始")
                return None
            self.sleep(POLL)
        deadline = self.clock() + TURN_WAIT_SECONDS
        steady_since = None
        still, still_since = None, self.clock()
        read_word_at = self.clock() + END_WORD_EVERY
        while self.clock() <= deadline:
            frame = self.capture()
            if vision.battle_end_visible(frame):
                self.end_word = "battle_end"
                return "end"
            if vision.victory_visible(frame):
                self.end_word = "victory"
                self.log("出现 VICTORY：这场赢了")
                return "end"
            if self.clock() >= read_word_at:
                read_word_at = self.clock() + END_WORD_EVERY
                word = None if vision.planning_visible(frame) else vision.lost_word(frame, self.ocr)
                if word is not None:
                    self.end_word = "lost"
                    self.log(f"出现「{word}」：这场输了")
                    self._keep_picture(frame, "fiend-lost")
                    return "end"
            if vision.planning_visible(frame) and vision.slot_count(frame) > 0:
                steady_since = steady_since if steady_since is not None else self.clock()
                if self.clock() - steady_since >= PLANNING_STEADY_SECONDS:
                    return "planning"
            else:
                steady_since = None
                picture = vision.still_picture(frame)
                if still is None or not vision.same_still(still, picture):
                    still, still_since = picture, self.clock()
                elif self.clock() - still_since >= STILL_SECONDS:
                    self.log(f"战斗画面 {STILL_SECONDS:.0f} 秒没动，可能卡住了（断线视窗之类）")
                    self._keep_stuck(frame)
                    return None
            self.sleep(POLL)
        return None

    def _keep_stuck(self, frame: np.ndarray) -> None:
        """Keep the stuck screen with the report pictures (7 days): a dialog
        the tool doesn't know can only be handled once one has been seen."""
        self._keep_picture(frame, "fiend-stuck")

    def _keep_picture(self, frame: np.ndarray, kind: str) -> None:
        """Keep ``frame`` with the report pictures (7 days), to see what went wrong."""
        try:
            from src.tasks import run_report

            path = run_report.save_picture(vision._bgr(frame), kind)
        except Exception:
            path = None
        if path:
            self.log(f"已保存当时画面：{path}")

    # --- RecordingScreen --------------------------------------------------------------

    def phase(self) -> Literal["planning", "battle", "end"] | None:
        frame = self.capture()
        if vision.battle_end_visible(frame):
            return "end"
        if vision.planning_visible(frame):
            return "planning" if vision.slot_count(frame) > 0 else None
        return "battle"

    def save_screenshot(self, path: Path) -> None:
        """The planning screen with nobody selected and the list steady, as same_card needs."""
        frame = self._steady_list()
        if frame is None:
            self.log("截图时左侧列表一直在变，照样存下这一张")
            frame = self.capture()
        self.wait_saved()
        # encoding a 4K PNG takes 0.25-0.4 s: written while the tool goes on to BATTLE
        self._writing = self._files.submit(_write_png, Path(path), vision._bgr(frame))

    def wait_saved(self) -> None:
        """Wait for the last screenshot to be on disk; raise if it couldn't be written."""
        writing, self._writing = self._writing, None
        if writing is not None:
            try:
                writing.result()
            except OSError as error:
                raise ScreenReadError(f"截图保存失败：{error}") from error

    # --- helpers ----------------------------------------------------------------------

    def _list_changed(self) -> None:
        self._list_frame = None

    def _saved_frame(self, turn: int) -> np.ndarray | None:
        """Turn ``turn``'s screenshot; starts loading the next turn's in the background."""
        if self.record is None or self.folder is None or turn not in self.record.screenshots:
            return None
        later = sorted(number for number in self.record.screenshots if number > turn)
        for number in [turn] + later[:1]:
            if number not in self._saved_frames:
                path = self.folder / self.record.screenshots[number]
                self._saved_frames[number] = self._files.submit(self.load_screenshot, path)
        for number in [number for number in self._saved_frames if number < turn]:
            del self._saved_frames[number]  # a replay only goes forward
        try:
            frame = self._saved_frames[turn].result()
        except (OSError, ValueError, cv2.error):
            frame = None
        if frame is None:
            self.log(f"读不了第 {turn} 回合的存档截图 {self.record.screenshots[turn]}")
        return frame

    def _steady_list(self) -> np.ndarray | None:
        """A capture of the planning screen, nobody selected, once the list holds still."""
        bring = getattr(self.task, "_bring_game_to_foreground", None)
        if callable(bring) and not bring():
            raise ScreenReadError("游戏窗口不在最前面")
        frame = self.capture()
        if not vision.planning_visible(frame):
            return None
        if vision.selected_slots(frame):
            frame = self._clear_selection(frame)
        count = vision.slot_count(frame)
        if count < 1:
            return None
        for _ in range(LIST_POLLS):
            self.sleep(POLL_STEP)
            now = self.capture()
            if vision.selected_slots(now) or vision.slot_count(now) != count:
                return None
            if vision.list_steady(frame, now, count):
                return now
            frame = now
        return None

    def _ready_frame(self) -> np.ndarray:
        """Planning screen in the top-down view with nobody selected."""
        bring = getattr(self.task, "_bring_game_to_foreground", None)
        if callable(bring) and not bring():
            raise ScreenReadError("游戏窗口不在最前面")
        frame = self._settled_frame()
        if not vision.planning_visible(frame) or vision.slot_count(frame) < 1:
            raise ScreenReadError("不在排位画面")
        if not vision.is_topdown(frame):
            frame = self._toggle_view(topdown=True)
        offset = vision.view_offset(frame)
        if (
            offset is not None
            and layout.VIEW_SHIFT_NOTE < max(map(abs, offset)) <= layout.VIEW_SHIFT_MAX
        ):
            self.log(f"视角偏了一点（{offset[0]:+.1f}, {offset[1]:+.1f}），还在容许范围内")
        if offset is not None and max(map(abs, offset)) > layout.VIEW_SHIFT_MAX:
            self.log(f"视角被拖偏了（{offset[0]:+.0f}, {offset[1]:+.0f}），切换两次放回原位")
            self._keep_panned(frame)
            self._toggle_view(topdown=False)
            frame = self._toggle_view(topdown=True)
            offset = vision.view_offset(frame)
            if offset is None or max(map(abs, offset)) > layout.VIEW_SHIFT_MAX:
                raise ScreenReadError("视角偏了，切换两次也回不到原位")
        frame = self._place_grid(frame)
        if vision.selected_slots(frame):
            frame = self._clear_selection(frame)
        return frame

    def _place_grid(self, frame: np.ndarray) -> np.ndarray:
        """Find the grid's cells as drawn; toggle the view twice once if they
        aren't where layout has them, and press them where they are if that
        didn't put them back (the mouse wheel zooms the top-down view)."""
        if self.grid_scales is None and vision.talos_layout(frame):
            self.grid_scales = TALOS_GRID_SCALES  # 塔洛斯's buttons: its grid sizes
        if self.grid_scales is not None:
            return self._place_sized_grid(frame)
        drawn = vision.grid_on_screen(frame)
        if drawn is None:
            return frame  # brackets not seen: keep pressing as before
        if not drawn.off(self._grid or vision.LAYOUT_GRID):
            return frame
        if drawn.off(vision.LAYOUT_GRID):
            self.log(
                f"格子不在原位（大小 {drawn.scale:.2f}，左上 {drawn.left:.0f},{drawn.top:.0f}），"
                "切换两次视角"
            )
            self._toggle_view(topdown=False)
            frame = self._toggle_view(topdown=True)
            again = vision.grid_on_screen(frame)
            if again is not None and not again.off(vision.LAYOUT_GRID):
                self._grid = None  # back in place
                return frame
            if again is None or again.off(drawn):
                # the two reads disagree: not sure enough to press anywhere else
                self.log("格子位置两次读的不一样，照原位按")
                self._grid = None
                return frame
            drawn = again
        if drawn.off(vision.LAYOUT_GRID):
            self._grid = drawn
            self.log(
                f"格子照画面上的位置按（大小 {drawn.scale:.2f}，"
                f"左上 {drawn.left:.0f},{drawn.top:.0f}）"
            )
        else:
            self._grid = None
        return frame

    def _place_sized_grid(self, frame: np.ndarray) -> np.ndarray:
        """塔洛斯: the grid at its usual size is pressed where it is drawn; any
        other size is zoomed back first.  The place must read the same
        twice (2K PC 2026-10-28 stage 2 T5: one read 100 px low)."""
        low, high = self.grid_scales

        def usual(grid: vision.Grid | None) -> bool:
            return grid is not None and low <= grid.scale <= high

        drawn = vision.grid_on_screen(frame)
        if drawn is None:
            # Not one bracket: maybe the view was read wrong (stages 5 and 8 on
            # the 2K PC 2026-10-28: dark floors).  切换视角 once and look again,
            # else back to where it was, before the wheel.
            self.log("看不到格子，先按一次切换视角再看")
            flipped = self._flip_view()
            drawn = vision.grid_on_screen(flipped)
            if drawn is None:
                frame = self._flip_view()
            else:
                frame = flipped
        if not usual(drawn):
            seen = "看不到格子" if drawn is None else f"格子大小 {drawn.scale:.2f}"
            self.log(f"{seen}，不是平常的大小，用滚轮调回 100%")
            frame, percent = self._zoom_back(usual)
            drawn = vision.grid_on_screen(frame)
            if not usual(drawn):
                shown = f"缩放停在 {percent}%，" if percent is not None else ""
                seen = "还是看不到格子" if drawn is None else f"格子大小还是 {drawn.scale:.2f}"
                raise ScreenReadError(f"用滚轮调过缩放，{shown}{seen}（平常是 100%、1.33 左右）")
        if self._grid is None or drawn.off(self._grid):
            # A new place: read once more and take it only when two reads agree.
            for _ in range(GRID_READS - 1):
                again = vision.grid_on_screen(self._settled_frame())
                if usual(again) and not again.off(drawn):
                    break
                drawn = again if usual(again) else drawn
            else:
                raise ScreenReadError("格子的位置每次读的都不一样")
            self.log(
                f"格子照画面上的位置按（大小 {drawn.scale:.2f}，"
                f"左上 {drawn.left:.0f},{drawn.top:.0f}）"
            )
        self._grid = drawn
        return frame

    def _zoom_back(self, usual) -> tuple[np.ndarray, int | None]:
        """Wheel out to the far end and in to about 101%, then one notch at a
        time until the grid is its usual size: each notch is read on the
        「N%」 bar, or on the grid's own size when the bar isn't read (a
        dropped notch or a slow game left it short before)."""
        self.wheel(-ZOOM_OUT_NOTCHES)
        self.wheel(ZOOM_IN_NOTCHES)
        low = self.grid_scales[0] if self.grid_scales is not None else 1.0
        percent, frame = None, None
        for turned in range(ZOOM_STEPS + 1):
            percent = vision.zoom_percent(self.capture(), self.ocr)
            frame = self._settled_frame()
            drawn = vision.grid_on_screen(frame)
            if usual(drawn):
                break
            if percent is not None:
                if ZOOM_OK[0] <= percent <= ZOOM_OK[1]:
                    break  # the game says 100%: the grid read decides
                step = 1 if percent < ZOOM_OK[0] else -1
                why = f"缩放 {percent}%"
            elif drawn is not None:
                step = 1 if drawn.scale < low else -1
                why = f"没读到百分比，格子大小 {drawn.scale:.2f}"
            else:
                self.log("没读到百分比，也看不到格子，不再转滚轮")
                break
            if turned == ZOOM_STEPS:
                self.log(f"滚轮一格一格调了 {ZOOM_STEPS} 次还没到 100%（{why}）")
                break
            self.log(f"{why}，滚轮{'放大' if step > 0 else '缩小'}一格")
            self.wheel(step)
        self.log(f"缩放调到 {percent}%" if percent is not None else "缩放调过了（没读到百分比）")
        return frame, percent

    def _wheel(self, notches: int) -> None:
        """The real wheel: the top-down zoom ignores posted wheel messages
        (4K PC clone 2026-10-31); posted only when the game isn't in front
        to take a real one."""
        real = getattr(self.task, "wheel_client_real", None)
        if callable(real) and real(WHEEL_POINT, notches, interval=0.12, after_sleep=0.8):
            return
        self.log("游戏不在最前面，滚轮改用后台方式（可能没反应）")
        self.task.scroll_client(
            WHEEL_POINT,
            1 if notches > 0 else -1,
            count=abs(notches),
            interval=0.12,
            after_sleep=0.8,
        )

    def _press(self, cell: Cell) -> layout.Point:
        point = layout.cell_press(cell)
        return point if self._grid is None else self._grid.point(point)

    def _keep_panned(self, frame: np.ndarray) -> None:
        """Save the frame before the last drag and the panned view, to find why it missed."""
        if self.folder is None or self._before_drag is None:
            return
        before, drag = self._before_drag
        self._before_drag = None
        stamp = time.strftime("%m%d_%H%M%S")
        (r1, c1), (r2, c2) = drag.source, drag.target
        name = f"{stamp}_drag{r1}{c1}-{r2}{c2}"
        folder = self.folder / PANNED_FOLDER
        self.log(f"拖空前后的截图存在 {folder}\\{name}_*.png")
        self._save_frame(folder / f"{name}_before.png", before)
        self._save_frame(folder / f"{name}_after.png", frame)
        self._files.submit(_keep_newest, folder, PANNED_KEEP)

    def _save_frame(self, path: Path, frame: np.ndarray) -> None:
        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_png(path, frame)

        self._files.submit(write)

    def _flip_view(self) -> np.ndarray:
        """Tap 切换视角 once without asking which view it is, and let it settle."""
        self.input.tap(vision.view_toggle_point(self.capture()) or layout.VIEW_TOGGLE)
        self.sleep(VIEW_SETTLE)
        self._settled_frame()
        self.sleep(VIEW_SETTLE)
        return self.capture()

    def _toggle_view(self, *, topdown: bool) -> np.ndarray:
        """Tap 切换视角 and wait until the view asked for has settled.

        The view fades through black and the game ignores the toggle until the
        fade is over (T19 of a real fight, 2026-10-01: a second tap sent as the
        fade began was lost), so each toggle waits for the floor to settle, and
        a tap that didn't take is sent once more.
        """
        for _ in range(VIEW_TOGGLE_TAPS):
            self.input.tap(vision.view_toggle_point(self.capture()) or layout.VIEW_TOGGLE)
            frame = self.capture()
            for _ in range(VIEW_TOGGLE_POLLS):  # top-down after ~0.7 s
                if vision.is_topdown(frame) == topdown:
                    break
                self.sleep(POLL_STEP)
                frame = self.capture()
            frame = self._settled_frame()
            if vision.is_topdown(frame) == topdown:
                self.sleep(VIEW_SETTLE)
                return self.capture()
        raise ScreenReadError("切换不到俯视视角" if topdown else "切换不回斜视角")

    def _settled_frame(self) -> np.ndarray:
        """A frame once the floor has stopped changing.

        When TEAM2 takes over (T13 of the test fight) the planning screen is
        reported while it still fades in: the floor flashes top-down bright
        for a frame, then settles isometric about 0.8 s later.  Deciding the
        view (or holding cells) during the fade reads the wrong cells.
        """
        frame = self.capture()
        level, steady = vision.floor_level(frame), 0
        for _ in range(SETTLE_POLLS):
            if steady >= SETTLE_STEADY:
                return frame
            self.sleep(POLL_STEP)
            frame = self.capture()
            now = vision.floor_level(frame)
            steady = steady + 1 if abs(now - level) <= FLOOR_STEADY_DIFF else 0
            level = now
        if steady >= SETTLE_STEADY:
            return frame
        raise ScreenReadError("排位画面一直在变")

    def _poll(self, done: Callable[[np.ndarray], bool], polls: int = SELECT_POLLS) -> np.ndarray:
        """Capture until ``done`` holds (at most ``polls`` captures); the last frame."""
        frame = self.capture()
        for _ in range(polls - 1):
            if done(frame):
                break
            self.sleep(POLL_STEP)
            frame = self.capture()
        return frame

    def _clear_selection(self, frame: np.ndarray) -> np.ndarray:
        """Tap the selected slot's ⇅ (a tap there only clears the selection)."""
        for _ in range(2):
            selected = vision.selected_slots(frame)
            if not selected:
                return frame
            for slot in selected:
                self.input.tap(layout.slot_swap(slot))
            self._cleared_at = self.clock()
            frame = self._poll(lambda shown: not vision.selected_slots(shown))
        if vision.selected_slots(frame):
            raise ScreenReadError("取消不了选中的角色")
        return frame

    def _hold_cell(
        self,
        cell: Cell,
        *,
        read_name: bool = True,
        previous: int | None = None,
        polls: int = SELECT_POLLS,
    ) -> tuple[int | None, str | None, np.ndarray]:
        """Hold ``cell``: (slot selected, its name, the frame).

        ``previous``: the slot still selected from the last hold; the brackets
        are waited for to leave it.  If they stay (an empty cell keeps the
        selection) that slot is returned, and the caller clears and holds again.
        """
        self.input.hold(self._press(cell), HOLD_SECONDS)
        self.holds += 1
        frame = self._poll(
            lambda shown: vision.selected_slots(shown) not in ([], [previous]), polls
        )
        selected = vision.selected_slots(frame)
        if len(selected) > 1:
            raise ScreenReadError(f"按住 {cell} 后同时选中了 {len(selected)} 个角色")
        if (
            not selected
            and previous is None
            and vision.card_count(frame) >= 2
            and vision.read_team(frame, self.ocr) is None
        ):
            # Leo 2026-10-07: holding a unit shows its cards and its name
            # top-left (TEAMn when nobody is held).  No slot marked then: the
            # list isn't read right, so the unit is kept by its name (no slot)
            # instead of taking its cell as empty.  TEAMn still showing: the
            # hold missed and the "cards" were the floor (4K 水魔兽 2026-10-08),
            # so the cell is held again like any other miss.
            found = snap_name(self._name_text(frame), self._spelling)
            if found is not None:
                return None, self._spelling[found], frame
            if vision.single_team(frame, self.ocr):
                # A fight with no teams (塔洛斯战术教材) never shows TEAMn, and
                # its floor's grid lines pass for a card column: no name means
                # the hold missed (2K PC 2026-10-22).
                return None, None, frame
            self._keep_picture(frame, "fiend-grid")
            row, col = cell
            raise ScreenReadError(
                f"按住第 {row + 1} 行第 {col + 1} 格有角色的卡片，但认不出左边选中的是第几位"
            )
        if not selected:
            return None, None, frame
        return selected[0], self._name(frame, selected[0]) if read_name else None, frame

    def _after_clear(self) -> None:
        """Let AFTER_CLEAR pass since the last ⇅ tap: the game ignored a portrait
        tap right after one (2K PC 2026-10-01: every other try at 0 s, 3/3 after
        0.5 s).  Cell holds right after one worked all along."""
        wait = self._cleared_at + AFTER_CLEAR - self.clock()
        if wait > 0:
            self.sleep(wait)

    def _select_slot(self, slot: int, *, chain: bool = False) -> tuple[np.ndarray, int, int] | None:
        """Tap slot ``slot``'s portrait: (frame, cards, lit row) once its column is steady.

        Only the list is used, so the view and a fading grid don't matter.
        ``chain``: with another unit selected, tap the portrait straight away
        (the selection moves to it) instead of clearing first.
        """
        bring = getattr(self.task, "_bring_game_to_foreground", None)
        if callable(bring) and not bring():
            raise ScreenReadError("游戏窗口不在最前面")
        frame = self.capture()
        if not vision.planning_visible(frame) or vision.slot_count(frame) <= slot:
            raise ScreenReadError("不在排位画面")
        selected = vision.selected_slots(frame)
        if chain and selected == [slot]:
            column = self._column(slot)
            if column is not None:
                return column
        elif chain and selected:
            self.input.tap(layout.slot_tap(slot))
            column = self._column(slot)
            if column is not None:
                return column
        self._clear_selection(self.capture())
        for _ in range(2):
            self._after_clear()
            self.input.tap(layout.slot_tap(slot))
            column = self._column(slot)
            if column is not None:
                return column
            self._clear_selection(self.capture())
        return None

    def _column(
        self, slot: int, lit: int | None = None, polls: int = CARD_POLLS
    ) -> tuple[np.ndarray, int, int] | None:
        """(frame, cards, lit row) of slot ``slot``'s card column, or None.

        The column slides in about 0.1-0.25 s after the brackets show, a few
        cards at a time, so it is only taken once two captures in a row agree
        (and, with ``lit``, once that row is the lit one).
        """
        seen = None
        for index in range(polls):
            if index:
                self.sleep(POLL_STEP)
            frame = self.capture()
            if vision.selected_slots(frame) != [slot]:
                seen = None
                continue
            now = (vision.card_count(frame), vision.lit_card(frame))
            if now[1] is not None and now == seen and lit in (None, now[1]):
                return frame, now[0], now[1]
            seen = now
        return None

    @staticmethod
    def _card_row(skill: str, count: int) -> int | None:
        if skill == "技能":  # the unit's only skill card
            return layout.FIRST_SKILL_ROW if count == layout.FIRST_SKILL_ROW + 1 else None
        row = vision.card_row(skill)
        return row if row is not None and row < count else None

    def _name_text(self, frame: np.ndarray) -> str:
        return plain_name(vision.read_name(frame, self.ocr))

    def _name(self, frame: np.ndarray, slot: int) -> str | None:
        """The selected unit's name, spelled as the known name it matches.

        Replay: snapped to a known name or None.  Recording: settled
        (names.settle_name), which also takes a name no list has.
        """
        text = self._name_text(frame)
        if not self.learn_names:
            found = snap_name(text, self._spelling)
            return None if found is None else self._spelling[found]

        def reads():
            yield text
            for _ in range(NAME_READS - 1):
                self.sleep(0.15)
                again = self.capture()
                if vision.selected_slots(again) != [slot]:
                    return
                yield self._name_text(again)

        found = settle_name(reads(), self._spelling)
        return None if found is None else self._spelling.get(found, found)

    def _hold_order(self, frame: np.ndarray, team: int, turn: int) -> list[Cell]:
        first: list[Cell] = []
        if self.record is not None:
            # where the last saved turn of this team put everyone: they mostly
            # still stand there (Leo 2026-10-28 「應該會記憶每個回合每個角色占哪個格子」)
            placed = [
                saved
                for number, saved in sorted(self.record.turns.items())
                if number < turn and saved.team == team
            ]
            if placed:
                first += [placed[-1].cells[unit] for unit in placed[-1].order]
            saved = self.record.turns.get(turn)
            if saved is not None and saved.team == team:
                first += [saved.cells[unit] for unit in saved.order]
        first += list(self.last_cells.get(team, {}).values())
        # where units were is only a guess once they may have moved: a guess
        # that looks like bare floor waits until the busy cells were held
        first = [
            cell
            for cell in first
            if vision.cell_busy_score(frame, cell, self._grid) >= EMPTY_LOOKING_MAX
        ]
        order: list[Cell] = []
        for cell in first + vision.cells_by_busy(frame, self._grid):
            if cell not in order:
                order.append(cell)
        return order

    def _read_grid(
        self, frame: np.ndarray, turn: int, team: int, living: int, *, need_all: bool
    ) -> tuple[dict[int, str], dict[str, Cell], list[Cell], dict[int, Cell], dict[int, str]]:
        """Holds cells: names by slot, cells by name, empty cells, tombstones by
        OUT slot, and the lit card of each living slot.

        Holding a tombstone may select its OUT slot (noted on the 4K PC in
        the first test fights) or nothing; both are handled.
        """
        self.holds = 0
        slot_names: dict[int, str] = {}
        cells: dict[str, Cell] = {}
        empty: list[Cell] = []
        stones: dict[int, Cell] = {}
        labels: dict[int, str] = {}
        # Holding the next unit's cell moves the selection without moving
        # anyone (6/6 on the 4K PC, 2026-10-01), so without cards to read the
        # selection isn't cleared between units (0.15 s a unit).  A card
        # column is only trusted once cleared, so it can't be the last unit's.
        chain = not self.read_cards
        previous: int | None = None
        queue, retried = self._hold_order(frame, team, turn), False
        seen: dict[Cell, int | None] = {}  # what each hold selected, for a failed read's log
        # Some turns the game shows no card column at all, even to a player's
        # click (2K PC 2026-10-07 T19, twice): after one unit's second hold
        # also shows none, the others aren't held a second time.
        columns_shown = True
        unmarked: dict[Cell, str] = {}  # a unit held (cards, name) with no slot marked
        while queue or not retried:
            if len(slot_names) == living and not need_all:
                break
            if not queue:
                if len(slot_names) == living:
                    break
                # A hold can miss: the first one after the game came to the
                # front selected nobody on a unit's cell (2K PC 2026-10-01,
                # twice), and a unit's cell read as empty with units still
                # missing (2K PC 2026-10-07).  Every cell that held nobody gets
                # one more, slower hold, busy-looking ones first.
                retried = True
                queue = sorted(
                    empty, key=lambda cell: -vision.cell_busy_score(frame, cell, self._grid)
                )
                empty = []
                continue
            cell = queue.pop(0)
            polls = RETRY_SELECT_POLLS if retried else SELECT_POLLS
            slot, held_name, held = self._hold_cell(
                cell, read_name=False, previous=previous, polls=polls
            )
            seen[cell] = slot
            previous = None
            # an empty cell can keep the last selection: a name found already is stale
            stale = held_name in cells or any(
                name == held_name and where != cell for where, name in unmarked.items()
            )
            if slot is None and held_name is not None and not stale:
                unmarked[cell] = held_name
                if not retried:
                    empty.append(cell)  # held once more, slower, with the cells that held nobody
                continue
            if slot is not None:
                unmarked.pop(cell, None)
            if slot is not None and (slot in slot_names or slot in stones):
                # the last selection may have stayed (an empty cell doesn't clear it)
                self._clear_selection(held)
                slot, _, held = self._hold_cell(cell, read_name=False)
                if slot is not None and (slot in slot_names or slot in stones):
                    raise ScreenReadError(f"第 {slot + 1} 位出现在两个格子上")
            if slot is None:
                empty.append(cell)
                continue
            if slot >= living:
                stones[slot] = cell
                self._clear_selection(held)
                continue
            name = self._name(held, slot)
            for _ in range(2):
                if not chain or name is None or name not in cells:
                    break
                self.sleep(POLL_STEP)  # the name line may lag a frame behind the brackets
                held = self.capture()
                if vision.selected_slots(held) != [slot]:
                    break
                name = self._name(held, slot)
            if name is None:
                raise ScreenReadError(f"第 {slot + 1} 位的名字读不清")
            if name in cells:
                raise ScreenReadError(f"{name} 出现在两个格子上")
            slot_names[slot] = name
            cells[name] = cell
            if chain:
                previous = slot
                continue
            column = self._column(
                slot, polls=CARD_POLLS if self.learn_costumes else READ_CARD_POLLS
            )
            if column is None and self.learn_costumes and columns_shown:
                column = self._column_again(cell, slot)
                columns_shown = column is not None
            if column is not None:
                labels[slot] = self.card_labels[slot] = vision.card_label(column[2])
                self._keep_card_column(turn, name, column)
                costume = self._learn_costumes(name, column) if self.learn_costumes else None
                if costume is not None:
                    self._read_costumes[slot] = costume
            self._clear_selection(self.capture() if column is None else column[0])
        if previous is not None:
            self._clear_selection(self.capture())
        empty = [cell for cell in empty if cell not in unmarked]
        missing = [slot for slot in range(living) if slot not in slot_names]
        left = {cell: name for cell, name in unmarked.items() if name not in cells}
        if len(missing) == 1 and len(left) == 1:
            # one slot unfound and one unit held without a mark: that's it
            (cell, name), slot = next(iter(left.items())), missing[0]
            slot_names[slot] = name
            cells[name] = cell
            row, col = cell
            self.log(f"第 {slot + 1} 位没认到选中框，按名字认作 {name}（{row + 1}-{col + 1} 格）")
        if len(slot_names) != living:
            missing = [slot + 1 for slot in range(living) if slot not in slot_names]
            holds = "，".join(
                f"{row + 1}-{col + 1}→"
                + (unmarked.get((row, col), "无") if slot is None else str(slot + 1))
                for (row, col), slot in seen.items()
            )
            self.log(f"按过的格子（行-列→选中第几位）：{holds}")
            self._keep_picture(frame, "fiend-grid")
            raise ScreenReadError(f"找不到第 {missing} 位角色站的格子")
        return slot_names, cells, empty, stones, labels

    def _column_again(self, cell: Cell, slot: int) -> tuple[np.ndarray, int, int] | None:
        """Recording: a card column that didn't settle is read once more, after
        clearing and holding the unit's cell again (Leo 2026-10-07: a card not
        read leaves the chart a bare 「技能」)."""
        self._clear_selection(self.capture())
        held, _, _ = self._hold_cell(cell, read_name=False, polls=RETRY_SELECT_POLLS)
        column = self._column(slot, polls=CARD_POLLS) if held == slot else None
        if column is None:
            row, col = cell
            frame = self.capture()
            count = vision.card_count(frame)
            lit = [round(vision.card_lit_score(frame, card)) for card in range(count)]
            self.log(
                f"第 {slot + 1} 位（{row + 1}-{col + 1} 格）的卡片栏两次都没读到"
                f"（选中 {[s + 1 for s in vision.selected_slots(frame)]}，"
                f"卡片 {count} 张，亮度 {lit}）"
            )
            self._keep_picture(frame, "fiend-cards")
        return column

    def _learn_costumes(self, name: str, column: tuple[np.ndarray, int, int]) -> str | None:
        """Tell the costumes of ``name``'s skill cards in an open column (costumes.py)
        and return the lit card's costume id, if it is a skill and can be told.

        Unlit cards are told by their art, once per unit and card; the lit one
        by the skill name in the header (its art changes when lit).
        """
        known = costumes.book().costumes(name)
        if not known:
            return None  # a summon, or a character newer than the list
        frame, count, lit = column
        learned = self.unit_cards.setdefault(name, {})
        rows = [
            row
            for row in range(layout.FIRST_SKILL_ROW, count)
            if row != lit and vision.card_label(row) not in learned
        ]
        if rows:
            for row, costume in costumes.column_costumes(frame, count, lit, known).items():
                if row in rows and costume.id not in learned.values():
                    learned[vision.card_label(row)] = costume.id
        if lit is None or lit < layout.FIRST_SKILL_ROW:
            return None
        label = vision.card_label(lit)
        costume = costumes.costume_by_skill(vision.read_skill_name(frame, self.ocr), known)
        if costume is None and label not in learned:
            # header unread: the costume no other card is, if that settles it
            by_id = {costume.id: costume for costume in known}
            others = {
                row: by_id[learned[vision.card_label(row)]]
                for row in range(layout.FIRST_SKILL_ROW, count)
                if row != lit and learned.get(vision.card_label(row)) in by_id
            }
            costume = costumes.last_costume(count, others, known)
        if costume is None:
            return learned.get(label)
        for other, worn in list(learned.items()):
            if worn == costume.id and other != label:
                del learned[other]  # a card can only be one costume
        learned[label] = costume.id
        return costume.id

    def label_for_costume(self, slot: int, name: str, costume_id: str) -> str | None:
        """The label of ``name``'s card for costume ``costume_id`` on this PC.

        '' when the unit's cards were all told and none is that costume (the
        player doesn't have it); None when it can't be told.
        """
        learned = self.unit_cards.get(name, {})
        for label, worn in learned.items():
            if worn == costume_id:
                return label
        column = self._select_slot(slot)
        if column is None:
            return None
        frame, count, _ = column
        try:
            self._learn_costumes(name, column)
        finally:
            self._clear_selection(frame)
        learned = self.unit_cards.get(name, {})
        for label, worn in learned.items():
            if worn == costume_id:
                return label
        skill_cards = max(count - layout.FIRST_SKILL_ROW, 0)
        return "" if skill_cards and len(learned) >= skill_cards else None

    def _keep_card_column(self, turn: int, name: str, column: tuple[np.ndarray, int, int]) -> None:
        """Save the unit's card column as seen, named by turn, unit and lit card."""
        if self.cards_folder is None:
            return
        frame, count, lit = column
        left, top, right, _ = layout.card_box(0)
        bottom = layout.card_box(max(count, 1) - 1)[3]
        part = layout.crop(frame, (left - 6, top - 6, right + 6, bottom + 6))
        label = vision.card_label(lit)
        path = self.cards_folder / f"T{turn:02d}_{plain_name(name) or 'unit'}_{label}.png"
        try:
            self.cards_folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        self._files.submit(_write_png, path, vision._bgr(part).copy())

    def _read_dead_name(self, slot: int) -> str:
        self.input.tap(layout.slot_tap(slot))
        self.sleep(AFTER_TAP + 0.4)
        frame = self.capture()
        name = None
        if vision.selected_slots(frame) == [slot]:
            name = self._name(frame, slot)
        self._clear_selection(frame)
        if name is None:
            raise ScreenReadError(f"读不出列表第 {slot + 1} 位阵亡角色的名字")
        return name

    def _tombstones(
        self, frame: np.ndarray, turn: int, dead: list[str], empty: list[Cell]
    ) -> Mapping[str, Cell]:
        """Tombstone cells of the dead: nobody selectable there but the cell is busy.

        One dead unit takes the one such cell.  With several, the saved turn
        decides who lies where, if its tombstone cells are exactly these.
        """
        if not dead:
            return {}
        stones = [
            cell
            for cell in empty
            if vision.cell_busy_score(frame, cell, self._grid) >= TOMBSTONE_BUSY_MIN
        ]
        if len(stones) == 1 and len(dead) == 1:
            return {dead[0]: stones[0]}
        saved = self.record.turns.get(turn) if self.record is not None else None
        if saved is not None and set(dead) <= set(saved.dead):
            wanted = {unit: saved.cells[unit] for unit in dead}
            if set(wanted.values()) == set(stones):
                return wanted
        raise ScreenReadError(f"分不清 {'、'.join(dead)} 的墓碑在哪一格")
