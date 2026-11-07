"""推主线: one switch that turns the main-story state on or off.

Leo 2026-11-06: 「這是一個狀態」 (src/tasks/MainStoryTask.py), 「放側邊欄」,
and while it is on 「浮在遊戲上的小條」 (the game status bar, shown for it
whatever 设置 says) carries its 停止.  「也要提醒用戶」: turning it on first
shows what it does and that the player's keyboard and mouse do not stop it.
Leo 2026-11-07 「介面特色用有質感的卡片 shadcn」: the mockup he saw
(/mnt/project-files/main-story-ui/推主線頁-卡片-v1.png): a hero card with the
switch on its right, four 它会做 cards with their key (the one at work lights
up), four 要知道 cards.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from src.ui.shell import actions, data, icons, theme
from src.ui.shell.floating import Floating, Panel
from src.ui.shell.page import Page, pill, set_pill
from src.ui.shell.run_confirm import HeroIcon
from src.ui.shell.widgets import Button, Card, Text, hbox, t, vbox

TASK = "MainStoryTask"
DIFFICULTIES = ("普通", "困难", "超困难")

# What it does (MainStoryTask / main_story/screen.py): icon, key, title, line,
# and the 「状态」 words (screen.Kind values) that light the card.
DOES = (
    ("skip-forward", "F2", "跳过剧情", "剧情、确认框一起按掉", ("跳过对话", "跳过对话确认")),
    ("zap", "", "快速探索", "有捷径就先走", ("快速进行任务", "前往快速探索", "自动进行", "战斗", "奖励")),
    ("map", "E", "自己寻路", "跟着任务走到下一站", ("主线引导", "自动移动中")),
    ("message-square", "F · Enter", "互动、对话", "只在对话时往下按", ("按 F 互动", "对话")),
)
# 「也要提醒用戶」: shown on the page and again before it turns on.
NOTES = (
    ("swords", "战斗你来打", "一分钟没开打才帮你点一次自动；打输会等你重打"),
    ("hand", "要手动的步骤", "停下来等你，做完自己接着跑"),
    ("copy", "被盖住也照跑", "可以看网页、看影片；打字可能会被干扰"),
    ("house", "回主页会暂停", "要停请按游戏上方小条的「停止」"),
)


def lit_card(status: str) -> int | None:
    """Which 它会做 card the current step belongs to (None: none of them)."""
    for index, (_icon, _key, _title, _line, steps) in enumerate(DOES):
        if status in steps:
            return index
    return None


class Tile(QWidget):
    """A rounded square with a line icon; filled violet while its card is at work."""

    def __init__(self, icon_name: str, size: int = 34, hero: bool = False, parent=None):
        super().__init__(parent)
        self._icon = icon_name
        self._hero = hero
        self._on = False
        self.setFixedSize(size, size)

    def set_on(self, on: bool) -> None:
        if on != self._on:
            self._on = on
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = box.width() * (0.26 if self._hero else 0.24)
        if self._hero or self._on:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("primary"))
            fg = theme.color("on_primary")
        else:
            painter.setPen(theme.color("line2"))
            painter.setBrush(theme.color("inset"))
            fg = theme.color("primary")
        painter.drawRoundedRect(box, radius, radius)
        side = box.width() * 0.5
        offset = (self.width() - side) / 2
        icons.paint(painter, QRectF(offset, offset, side, side), self._icon, fg, 1.9)


class OutlinedCard(Card):
    def edge_colour(self):
        return theme.color("line2")


class FeatureCard(Card):
    """One thing it does: tile, key chip top right, title, one line."""

    def __init__(self, icon_name: str, key: str, title: str, line: str):
        super().__init__()
        self._on = False
        column = vbox(self, (18, 16, 18, 16), 10)
        top = hbox(None, (0, 0, 0, 0), 8)
        self.tile = Tile(icon_name, 34)
        top.addWidget(self.tile, 0, Qt.AlignTop)
        top.addStretch(1)
        if key:
            top.addWidget(pill(key), 0, Qt.AlignTop)
        column.addLayout(top)
        texts = vbox(None, (0, 0, 0, 0), 2)
        texts.addWidget(Text(title, "h2"))
        texts.addWidget(Text(line, "card_desc", wrap=True))
        column.addLayout(texts)
        column.addStretch(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool) -> None:
        if on != self._on:
            self._on = on
            self.tile.set_on(on)
            self.update()

    def edge_colour(self):
        return theme.color("primary" if self._on else "line2")


class NoteCard(OutlinedCard):
    """One thing to know: small tile, title, one line."""

    def __init__(self, icon_name: str, title: str, line: str):
        super().__init__()
        row = hbox(self, (16, 14, 16, 14), 12)
        row.addWidget(Tile(icon_name, 30), 0, Qt.AlignTop)
        texts = vbox(None, (0, 0, 0, 0), 2)
        texts.addWidget(Text(title, "h3"))
        texts.addWidget(Text(line, "card_desc", wrap=True))
        row.addLayout(texts, 1)


def _grid(cards, columns: int) -> QWidget:
    host = QWidget()
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(12)
    for index, card in enumerate(cards):
        grid.addWidget(card, index // columns, index % columns)
    for column in range(columns):
        grid.setColumnStretch(column, 1)
    return host


class StartReminder(Floating):
    """「也要提醒用戶」: what changes while 推主线 is on, then 开启 / 取消."""

    PANEL_WIDTH = 460 - 2 * Panel.SHADOW
    MARGIN = 64
    PAD = (24, 20)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        column = self.column
        head = hbox(None, (0, 0, 0, 0), 12)
        head.addWidget(HeroIcon("scroll-text", 40), 0, Qt.AlignTop)
        titles = vbox(None, (0, 0, 0, 0), 2)
        titles.addWidget(Text("开启推剧情", "h2"))
        titles.addWidget(Text("请先进到剧情的场地或对话里再开", "sub", wrap=True))
        head.addLayout(titles, 1)
        column.addLayout(head)
        for icon_name, title, line in NOTES:
            row = hbox(None, (0, 0, 0, 0), 10)
            row.addWidget(Tile(icon_name, 26), 0, Qt.AlignTop)
            texts = vbox(None, (0, 0, 0, 0), 1)
            texts.addWidget(Text(title, "h3"))
            texts.addWidget(Text(line, "card_desc", wrap=True))
            row.addLayout(texts, 1)
            column.addLayout(row)
        buttons = hbox(None, (0, 6, 0, 0), 8)
        buttons.addStretch(1)
        buttons.addWidget(Button("取消", "secondary", on_click=self.reject))
        buttons.addWidget(Button("开启", "primary", "play", on_click=self.accept))
        column.addLayout(buttons)

    def mouseReleaseEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.reject()
        super().mouseReleaseEvent(event)


def confirm_start(window: QWidget | None) -> bool:
    return bool(StartReminder(window).exec())


def _section(text: str) -> Text:
    return Text(text, "eyebrow")


class StoryPage(Page):
    interval = 1000

    def __init__(self, parent=None):
        super().__init__("shellStory", "推剧情", "", parent)
        self.set_sub("选好卡带开启，普通、困难、超困难一路推完")

        hero = OutlinedCard()
        row = hbox(hero, (24, 22, 24, 22), 16)
        row.addWidget(Tile("scroll-text", 56, hero=True), 0, Qt.AlignVCenter)
        texts = vbox(None, (0, 0, 0, 0), 6)
        title_row = hbox(None, (0, 0, 0, 0), 10)
        title_row.addWidget(Text("推剧情", "card_title"))
        self.state = pill()
        title_row.addWidget(self.state, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        texts.addLayout(title_row)
        self.now = Text("", "card_desc", wrap=True)
        texts.addWidget(self.now)
        chips = hbox(None, (0, 2, 0, 0), 6)
        for name in DIFFICULTIES:
            chips.addWidget(pill(t(name)))
        chips.addStretch(1)
        texts.addLayout(chips)
        row.addLayout(texts, 1)
        # Leo 2026-11-06: a toggle says its current choice inside the button.
        self.switch = Button("开启推剧情", "primary", "play", "lg", on_click=self.toggle)
        row.addWidget(self.switch, 0, Qt.AlignVCenter)
        self.body.addWidget(hero)

        self.body.addWidget(_section("它会做"))
        self.features = [FeatureCard(icon, key, title, line) for icon, key, title, line, _steps in DOES]
        self.body.addWidget(_grid(self.features, 4))

        self.body.addWidget(_section("要知道"))
        self.body.addWidget(_grid([NoteCard(*note) for note in NOTES], 2))
        self.body.addStretch(1)

    def task(self):
        return data.task_by_class_name(TASK)

    def running(self) -> bool:
        task = self.task()
        return task is not None and data.busy() and data.current_task() is task

    def toggle(self) -> None:
        task = self.task()
        if task is None:
            return
        if self.running():
            actions.stop(task)
        elif confirm_start(self.window()):
            actions.start(task, self.window())
        self.refresh()

    def _set_switch(self, on: bool) -> None:
        self.switch.set_label("停止推剧情" if on else "开启推剧情")
        self.switch.set_kind("danger" if on else "primary")
        self.switch.set_icon_name("square" if on else "play")

    def refresh(self) -> None:
        task = self.task()
        on = self.running()
        paused = on and bool(getattr(task, "paused", False))
        status = ""
        if on:
            try:
                from src.tasks.BaseBD2Task import task_info_snapshot

                status = str(task_info_snapshot(task).get("状态") or "")
            except Exception:
                status = ""
            set_pill(self.state, t("已暂停" if paused else "推剧情中"), None if paused else "ok")
            self.now.set_text(t("现在：") + t(status) if status else t("推剧情中"))
        else:
            set_pill(self.state, t("关闭"))
            self.now.set_text(t("先进到剧情的场地或对话里，再按开启"))
        self._set_switch(on)
        lit = lit_card(status) if on and not paused else None
        for index, card in enumerate(self.features):
            card.set_on(index == lit)
        self.switch.setEnabled(task is not None and (on or actions.can_start()))
