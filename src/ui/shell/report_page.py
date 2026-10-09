"""今日报表: everything that ran this game day, re-runs side by side (Leo 2026-10-05).

One row per task in the order it first ran; under it every run of the day
(time, which start it came from, result, why it failed).  The pictures kept
today (what the free gacha drew, what the mail gave) sit underneath.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from src.tasks import run_log, run_report
from src.ui.shell import data, theme
from src.ui.shell.page import Page
from src.ui.shell.widgets import (
    Card,
    Picture,
    Separator,
    StateIcon,
    Text,
    clear_layout,
    fmt_clock,
    fmt_duration,
    grid_container,
    hbox,
    t,
    tf,
    vbox,
)
from src.utils import accounts

STATE_TEXT = {run_log.DONE: "完成", run_log.FAIL: "失败", run_log.SKIP: "跳过"}
PICTURE_KINDS = (("gacha", "抽到的", "白嫖抽抽乐"), ("mail", "邮件领到的", "领取邮件"))


def via_text(via: str) -> str:
    return t(str(via or run_log.SINGLE).removeprefix("一键完成"))


def run_line(entry: dict) -> str:
    """'08:39 · 日常 · 完成 · 0:21' for one run."""
    parts = [data.clock_text(entry.get("finished")), via_text(entry.get("via", ""))]
    parts.append(t(STATE_TEXT.get(entry.get("state"), "跳过")))
    if entry.get("duration") is not None:
        parts.append(fmt_clock(entry["duration"]))
    return " · ".join(part for part in parts if part)


def header_line(week_seconds: float) -> str:
    """'10月9日 周五 · 游戏日从 08:00 开始 · 本周代跑 3 小时 20 分'.

    Leo 2026-10-09: the week's run time stays small, in this line only.
    """
    line = tf(
        "{date} · 游戏日从 {time} 开始", date=data.today_title(), time=data.daily_reset_clock()
    )
    if week_seconds >= 60:
        week = tf("本周代跑 {time}", time=fmt_duration(round(week_seconds / 60) * 60))
        line = f"{line} · {week}"
    return line


def task_state(runs: list[dict]) -> str:
    """A task counts as done once any run of the day finished it."""
    states = [run.get("state") for run in runs]
    if run_log.DONE in states:
        return run_log.DONE
    return runs[-1].get("state") or run_log.SKIP


def today_pictures(day: str) -> dict[str, list[str]]:
    folder = Path(run_report._image_root()) / day
    found: dict[str, list[str]] = {}
    try:
        files = sorted(folder.glob("*.png"))
    except OSError:
        return found
    for path in files:
        kind = path.name.split("-", 1)[0]
        found.setdefault(kind, []).append(str(path))
    return found


class TaskRuns(QWidget):
    """A task: its overall state and name, then one line per run."""

    def __init__(self, name: str, runs: list[dict], parent=None):
        super().__init__(parent)
        layout = hbox(self, (8, 8, 8, 8), 10)
        layout.addWidget(StateIcon(task_state(runs), 17), 0, Qt.AlignTop)
        texts = vbox(None, (0, 0, 0, 0), 3)
        head = hbox(None, (0, 0, 0, 0), 8)
        head.addWidget(Text(name, "h3", elide=True), 1)
        if len(runs) > 1:
            head.addWidget(Text(tf("跑了 {n} 次", n=len(runs)), "muted"))
        texts.addLayout(head)
        for run in runs:
            line = hbox(None, (0, 0, 0, 0), 6)
            line.addWidget(StateIcon(run.get("state") or run_log.SKIP, 12), 0, Qt.AlignVCenter)
            line.addWidget(Text(run_line(run), "muted"), 1)
            texts.addLayout(line)
            note = str(run.get("note") or "")
            if note:
                texts.addWidget(
                    Text(note, "bad" if run.get("state") == run_log.FAIL else "muted", wrap=True)
                )
        layout.addLayout(texts, 1)


class ReportPage(Page):
    interval = 3000

    def __init__(self):
        super().__init__("shellReport", "今日报表")
        self._shown_key = None
        self._week_seconds = 0.0

        boxes, grid = grid_container(120, 12, 4, 78)
        self.stat_tasks = self._stat(grid, "跑过的项目", "")
        self.stat_done = self._stat(grid, "完成", "ok")
        self.stat_fail = self._stat(grid, "失败", "bad")
        self.stat_runs = self._stat(grid, "执行次数", "")
        self.body.addWidget(boxes)

        self.empty = Card()
        empty_layout = vbox(self.empty, (20, 18, 20, 18), 4)
        empty_layout.addWidget(Text("今天还没跑过任务", "h3"))
        empty_layout.addWidget(Text("每次跑完（一键日常、周常或单独执行）都会记在这里。", "muted"))
        self.body.addWidget(self.empty)

        # The runs on the left, today's pictures beside them (seen without
        # scrolling past every task).
        columns = hbox(None, (0, 0, 0, 0), 16)
        left = vbox(None, (0, 0, 0, 0), 0)
        self.list_card = Card()
        self.list_layout = vbox(self.list_card, (14, 8, 14, 8), 0)
        left.addWidget(self.list_card)
        left.addStretch(1)
        columns.addLayout(left, 3)
        self.side = QWidget()
        side = vbox(self.side, (0, 0, 0, 0), 16)
        columns.addWidget(self.side, 2)
        self.body.addLayout(columns)

        self.picture_cards = {}
        for kind, title, sub in PICTURE_KINDS:
            card = Card()
            column = vbox(card, (16, 14, 16, 16), 10)
            head = hbox(None, (0, 0, 0, 0), 8)
            head.addWidget(Text(title, "h2"))
            head.addWidget(Text(tf("{task} · 点图看大图", task=t(sub)), "muted"), 1)
            column.addLayout(head)
            box, picture_grid = grid_container(150, 10, 2, 96)
            column.addWidget(box)
            side.addWidget(card)
            self.picture_cards[kind] = (card, picture_grid)
        side.addStretch(1)
        self.body.addStretch(1)

    @staticmethod
    def _stat(grid, label: str, tone: str) -> Text:
        card = Card()
        column = vbox(card, (16, 12, 16, 12), 2)
        column.addWidget(Text(label, "muted"))
        value = Text("0", "big")
        value.animate_changes()
        if tone:
            value.setProperty("tone", tone)
        column.addWidget(value)
        grid.addWidget(card)
        return value

    def refresh(self) -> None:
        day = run_log.day_key()
        entries = run_log.entries(day)
        pictures = today_pictures(day)
        key = (
            accounts.current_id(),
            day,
            len(entries),
            entries[-1].get("finished") if entries else None,
            tuple((kind, len(paths)) for kind, paths in sorted(pictures.items())),
        )
        if key != self._shown_key:
            self._week_seconds = run_log.week_seconds()
        self.set_sub(header_line(self._week_seconds))
        if key == self._shown_key:
            return
        self._shown_key = key
        groups = run_log.group_by_task(entries)
        self.stat_tasks.set_text(str(len(groups)))
        self.stat_done.set_text(
            str(sum(1 for _name, runs in groups if task_state(runs) == run_log.DONE))
        )
        self.stat_fail.set_text(
            str(sum(1 for _name, runs in groups if task_state(runs) == run_log.FAIL))
        )
        self.stat_runs.set_text(str(len(entries)))
        self.empty.setVisible(not groups)
        self.list_card.setVisible(bool(groups))
        clear_layout(self.list_layout)
        for index, (name, runs) in enumerate(groups):
            if index:
                self.list_layout.addWidget(Separator())
            self.list_layout.addWidget(TaskRuns(name, runs))
        any_picture = False
        for kind, (card, grid) in self.picture_cards.items():
            shown = self._fill_pictures(grid, pictures.get(kind) or [])
            card.setVisible(shown)
            any_picture = any_picture or shown
        self.side.setVisible(any_picture)

    def _fill_pictures(self, grid, paths: list[str]) -> bool:
        from src.ui.shell.home import PictureDialog

        clear_layout(grid)
        shown = 0
        for path in paths:
            picture = Picture(path, radius=theme.radius(), background="shot")
            if not picture.has_picture():
                continue
            picture.setCursor(Qt.PointingHandCursor)
            picture.clicked.connect(lambda p=path: PictureDialog(p, self).exec())
            grid.addWidget(picture)
            shown += 1
        return shown > 0
