"""塔洛斯教材: this month's nine stages (cleared or not) and one start button.

Leo 2026-10-28 「放側邊欄 把放魔獸追蹤者上面」: its own page above 魔兽追踪者.
The nine tiles are laid out like the game's stage list (1 2 3 / 4 5 6 /
7 8 9); a tile says cleared, not played, failed last time (why on hover) or
being played now.  Leo 2026-10-28 「要可以選擇關卡 預設全選排除打過的」: a
tile is ticked by a click, the stages not cleared are ticked to begin with.
开始打 runs TalosTask (src/tasks/TalosTask.py) on the ticked stages: from
主页, those stages in order, then 任务 → 全部获得.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QSizePolicy

from src.ui.shell import actions, data
from src.ui.shell.page import Page, pill, set_pill
from src.ui.shell.widgets import (
    Button,
    Card,
    CheckBox,
    Inset,
    StateIcon,
    Text,
    hbox,
    t,
    tf,
    vbox,
)

TASK = "TalosTask"


def _stages():
    from src.tasks.talos import stages

    return stages


def _progress():
    """This account's cleared and failed stages (empty when unreadable)."""
    stages = _stages()
    try:
        from src.utils import accounts

        return stages.Progress.load(accounts.path(stages.PROGRESS_FILE), stages.edition())
    except Exception:
        return stages.Progress("")


class StageTile(Inset):
    STATES = {
        "done": ("done", "已打完"),
        "todo": ("wait", "没打"),
        "fail": ("fail", "上次没打下来"),
        "run": ("run", "正在打"),
        "unknown": ("wait", "还没看过"),
    }

    toggled = Signal(int, bool)

    def __init__(self, stage: int, parent=None):
        super().__init__(parent)
        self.stage = stage
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        column = vbox(self, (16, 12, 16, 12), 6)
        top = hbox(None, (0, 0, 0, 0), 8)
        self.name = Text(tf("第 {n} 关", n=stage), "h3")
        top.addWidget(self.name, 1)
        self.check = CheckBox()
        self.check.toggled.connect(lambda on: self.toggled.emit(self.stage, on))
        top.addWidget(self.check)
        column.addLayout(top)
        row = hbox(None, (0, 0, 0, 0), 6)
        self.icon = StateIcon("wait", 15)
        self.word = Text("", "muted")
        row.addWidget(self.icon)
        row.addWidget(self.word, 1)
        column.addLayout(row)
        self._key = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.check.isEnabled():
            self.check.toggle()
        super().mousePressEvent(event)

    def set_picked(self, picked: bool, enabled: bool) -> None:
        self.check.set_checked_quietly(picked)
        self.check.setEnabled(enabled)

    def set_state(self, state: str, why: str = "") -> None:
        if (state, why) == self._key:
            return
        self._key = (state, why)
        icon, word = self.STATES[state]
        self.icon.set_state(icon)
        self.word.set_text(t(word))
        self.setToolTip(t(why) if why else "")


class TalosPage(Page):
    interval = 1500

    def __init__(self, parent=None):
        super().__init__("shellTalos", "塔洛斯教材", "", parent)
        self.set_sub("每月 9 关，照内建的轴自动打；打过的跳过，打完去任务领奖")

        card = Card()
        column = vbox(card, (22, 20, 22, 20), 14)
        head = hbox(None, (0, 0, 0, 0), 10)
        head.addWidget(Text("本月关卡", "h2"))
        head.addStretch(1)
        self.count = pill()
        head.addWidget(self.count)
        column.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.tiles: dict[int, StageTile] = {}
        for stage in range(1, 10):
            tile = StageTile(stage)
            tile.toggled.connect(self._toggled)
            self.tiles[stage] = tile
            grid.addWidget(tile, (stage - 1) // 3, (stage - 1) % 3)
        column.addLayout(grid)

        self.start_button = Button("开始打", "primary", "play", "lg", on_click=self.start)
        self.start_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        column.addWidget(self.start_button)
        self.note = Text("游戏停在主页就能开始，打勾的关会照顺序打完", "muted", wrap=True)
        self.note.setAlignment(Qt.AlignHCenter)
        column.addWidget(self.note)
        self.body.addWidget(card)
        self.body.addStretch(1)
        # The ticked stages; None = the stages not cleared (until a tile is clicked).
        self._picked: set[int] | None = None
        self._cleared: set[int] = set()
        self._was_busy = False

    def task(self):
        return data.task_by_class_name(TASK)

    def picked(self) -> set[int]:
        if self._picked is None:
            return set(self.tiles) - self._cleared
        return set(self._picked)

    def _toggled(self, stage: int, on: bool) -> None:
        picked = self.picked()
        if on:
            picked.add(stage)
        else:
            picked.discard(stage)
        self._picked = picked
        self.refresh()

    def start(self) -> None:
        task = self.task()
        picked = sorted(self.picked())
        if task is None or not picked:
            return
        # Untouched ticks: the task reads the list's ✕ itself and plays what
        # is not cleared (a new install doesn't know yet which are).
        task.chosen_stages = None if self._picked is None else picked
        actions.start(task, self.window())

    def refresh(self) -> None:
        progress = _progress()
        task = self.task()
        playing = None
        if task is not None and task.enabled and data.current_task() is task:
            playing = task.stage_picker.current
            progress.cleared |= task.stage_picker.cleared
        busy = playing is not None
        if self._was_busy and not busy:
            self._picked = None  # a run ended: tick what is still not cleared
        self._was_busy = busy
        self._cleared = set(progress.cleared)
        picked = self.picked()
        for stage, tile in self.tiles.items():
            tile.set_picked(stage in picked, not busy)
            if stage == playing:
                tile.set_state("run")
            elif stage in progress.cleared:
                tile.set_state("done")
            elif stage in progress.failed:
                tile.set_state("fail", progress.failed[stage])
            elif not progress.known:
                tile.set_state("unknown")
            else:
                tile.set_state("todo")
        done = len(progress.cleared)
        if progress.known or done:
            set_pill(self.count, tf("已打完 {n}/9", n=done), "ok" if done == 9 else None)
        else:
            set_pill(self.count, t("开始后先看游戏里打过哪些"))
        self.start_button.setEnabled(not busy and bool(picked))
        if busy:
            self.start_button.setText(t("正在打"))
        elif not picked:
            self.start_button.setText(t("勾选要打的关"))
        else:
            self.start_button.setText(tf("开始打（{n} 关）", n=len(picked)))
