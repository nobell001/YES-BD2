"""任务设定: tasks on the left, the picked one's state and settings on the right."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.ui.shell import actions, data, motion, theme
from src.ui.shell.config_form import ConfigForm
from src.ui.shell.page import Page
from src.ui.shell.widgets import (
    Button,
    Card,
    IconTile,
    Inset,
    Separator,
    StateIcon,
    Text,
    Toggle,
    WeekDots,
    clear_layout,
    fmt_duration,
    hbox,
    t,
    tf,
    vbox,
)

# Tasks whose settings live on their own page; the list only points there.
OWN_PAGES = {
    "MapTradeTask": ("trade", "跑商", "买什么、做哪些料理、每天卖什么都在那里设定"),
    "MapCollectionTask": ("map", "跑图", "跑哪些卡带、每次最多跑几张都在那里设定"),
}
# Settings of an OWN_PAGES task that are also changed right here (Leo
# 2026-10-20: 跑图's 技能间隔 「任務設定裡也要可以讓用戶調整」).
OWN_PAGE_KEYS = {
    "MapCollectionTask": ("技能间隔秒数",),
}

BATCH_OPTION_LABELS = {
    "失败后继续": "一项失败后继续跑后面的",
    # Leo 2026-10-25: players who auto-run on open never see the confirm
    # window, so 关闭游戏 sits next to 关机 here too (same config key).
    "完成日常后关闭游戏": "全部做完且没有失败后关闭游戏",
    "完成日常后自动关机": "全部做完后自动关机",
    "启用": "允许一键运行",
}


class TaskRow(QWidget):
    """One task in the left list: icon, name, today's state."""

    def __init__(self, key: str, icon_name: str, kind: str, name: str, on_click, parent=None):
        super().__init__(parent)
        self.key = key
        self._selected = False
        self._hover = motion.HoverFade(self, self.update)
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        layout = hbox(self, (8, 6, 10, 6), 10)
        self.tile = IconTile(icon_name, 26, 15, kind=kind)
        self.tile.follow_hover(self)
        layout.addWidget(self.tile)
        self.name = Text(name, "h3", elide=True)
        layout.addWidget(self.name, 1)
        self.mark = StateIcon("done", 13)
        self.state = Text("", "muted")
        layout.addWidget(self.mark)
        layout.addWidget(self.state)
        self.setFixedHeight(40)

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    def set_state(self, kind: str, text: str) -> None:
        self.mark.setVisible(kind == "done")
        self.state.set_text(text)
        self.state.set_role("ok" if kind == "done" else "muted")
        self.tile.set_off(kind == "off")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_click(self.key)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        hover = self._hover.value
        if not (self._selected or hover > 0):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(
            theme.color("row_on") if self._selected else theme.color("ink", 0.04 * hover)
        )
        painter.drawRoundedRect(QRectF(self.rect()), theme.corner(5), theme.corner(5))
        if self._selected:
            painter.setBrush(theme.color("row_on_bar"))
            painter.drawRoundedRect(QRectF(0, 8, 3, self.height() - 16), 1.5, 1.5)


class _Item:
    """A task shown on the page (a batch child or a standalone task)."""

    def __init__(self, key: str, task, name: str, icon: str, kind: str, included: bool | None):
        self.key = key
        self.task = task
        self.name = name
        self.icon = icon
        self.kind = kind
        self.included = included  # None: not part of a batch


class TaskPage(Page):
    """Master-detail page over a batch's children, or over a plain task list."""

    interval = 2000

    def __init__(
        self,
        object_name: str,
        title: str,
        batch_name: str | None = None,
        weekly: bool = False,
        navigate=None,
    ):
        super().__init__(object_name, title)
        self._navigate = navigate
        self.batch_name = batch_name
        self.weekly = weekly
        self._weekly_names: set[str] = set()  # 周常 inside 一键日常
        self._selected: str | None = None
        self._rows: dict[str, TaskRow] = {}
        self._row_keys: list = []
        self._detail_key = None

        if batch_name:
            self.start_button = self.add_action(
                Button(batch_name, "primary", "play", on_click=self._start_batch)
            )
            self.more_button = self.add_action(
                Button("", "icon", "ellipsis", on_click=self._toggle_options)
            )
            self.more_button.setToolTip(data.tr("一键运行的设定"))
            self.options = Card()
            self.options.hide()
            self.body.addWidget(self.options)
            self._options_built = False

        columns = hbox(None, (0, 0, 0, 0), 16)
        self.list_card = Card()
        self.list_card.setFixedWidth(312)
        self.list_layout = vbox(self.list_card, (10, 12, 10, 12), 2)
        self.list_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        left = vbox(None, (0, 0, 0, 0), 0)
        left.addWidget(self.list_card)
        left.addStretch(1)
        columns.addLayout(left)
        self.detail = Card()
        self.detail_layout = vbox(self.detail, (22, 20, 22, 20), 16)
        self.detail.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        right = vbox(None, (0, 0, 0, 0), 0)
        right.addWidget(self.detail)
        right.addStretch(1)
        columns.addLayout(right, 1)
        self.body.addLayout(columns)
        self.body.addStretch(1)

    # ---------------------------------------------------------------- data

    def batch(self):
        return data.task_by_name(self.batch_name) if self.batch_name else None

    def items(self) -> list[_Item]:
        if not self.batch_name:
            return []
        children = [child for child in data.batch_children(self.batch()) if child.task is not None]
        self._weekly_names = {child.name for child in children if child.weekly}
        return [
            _Item(child.key, child.task, child.name, child.icon, child.kind, child.included)
            for child in children
        ]

    def _done(self, name: str) -> bool:
        weekly = self.weekly or name in self._weekly_names
        return data.done_this_week(name) if weekly else data.done_today(name)

    def select(self, key: str | None) -> None:
        self._selected = key
        self.refresh()

    # ---------------------------------------------------------------- refresh

    def refresh(self) -> None:
        items = self.items()
        included = [item for item in items if item.included]
        batch = self.batch()
        if self.batch_name:
            done = sum(1 for item in included if self._done(item.name))
            self.set_sub(
                tf(
                    "一键运行会照左边的顺序跑 {n} 项 · 本周做完 {done} 项"
                    if self.weekly
                    else "一键运行会照左边的顺序跑 {n} 项 · 今天做完 {done} 项",
                    n=len(included),
                    done=done,
                )
            )
            self.start_button.setEnabled(actions.can_start() and batch is not None)
        else:
            self.set_sub("选一项，设定好后按开始")
        keys = [(item.key, item.included) for item in items]
        if keys != self._row_keys:
            self._build_list(items)
            self._row_keys = keys
        if self._selected not in {item.key for item in items}:
            self._selected = items[0].key if items else None
        for item in items:
            row = self._rows.get(item.key)
            if row is None:
                continue
            row.set_selected(item.key == self._selected)
            weekly = self.weekly or item.name in self._weekly_names
            if self._done(item.name):
                record = data.last_run(item.name) or {}
                stamp = data.clock_text(record.get("finished"))
                if weekly and data.day_text(record.get("finished")) != "今天":
                    stamp = data.day_text(record.get("finished")) or stamp
                row.set_state("done", stamp)
            elif item.included is False:
                row.set_state("off", "不跑")
            else:
                row.set_state("wait", "本周未完成" if weekly else "未完成")
        selected = next((item for item in items if item.key == self._selected), None)
        if selected is not None and selected.key != self._detail_key:
            self._build_detail(selected)
        if selected is not None:
            self._refresh_detail(selected)

    def _build_list(self, items: list[_Item]) -> None:
        clear_layout(self.list_layout)
        self._rows = {}
        if self.batch_name:
            head = hbox(None, (8, 0, 8, 6), 6)
            head.addWidget(Text("一键运行的顺序", "eyebrow"), 1)
            self.list_layout.addLayout(head)
        for item in [item for item in items if item.included is not False]:
            self._add_row(item)
        excluded = [item for item in items if item.included is False]
        if excluded:
            self.list_layout.addSpacing(8)
            self.list_layout.addWidget(Separator())
            self.list_layout.addSpacing(4)
            label = Text("不在一键运行里", "eyebrow")
            label.setContentsMargins(8, 4, 8, 4)
            self.list_layout.addWidget(label)
            for item in excluded:
                self._add_row(item)

    def _add_row(self, item: _Item) -> None:
        row = TaskRow(item.key, item.icon, item.kind, item.name, self.select)
        self.list_layout.addWidget(row)
        self._rows[item.key] = row

    # ---------------------------------------------------------------- detail

    def _build_detail(self, item: _Item) -> None:
        self._detail_key = item.key
        clear_layout(self.detail_layout)
        task = item.task
        head = hbox(None, (0, 0, 0, 0), 14)
        head.addWidget(IconTile(item.icon, 46, 24, kind=item.kind), 0, Qt.AlignTop)
        titles = vbox(None, (0, 0, 0, 0), 3)
        titles.addWidget(Text(item.name, "h2"))
        description = str(getattr(task, "description", "") or "")
        if description:
            titles.addWidget(Text(description, "sub", wrap=True))
        head.addLayout(titles, 1)
        self.run_one = Button(
            "开始" if item.included is None else "单独跑一次",
            "secondary",
            "play",
            on_click=lambda t=task: self._start_one(t),
        )
        head.addWidget(self.run_one, 0, Qt.AlignTop)
        self.detail_layout.addLayout(head)

        stats = Inset()
        stats_row = hbox(stats, (16, 12, 16, 12), 24)
        first = vbox(None, (0, 0, 0, 0), 4)
        weekly = self.weekly or item.name in self._weekly_names
        first.addWidget(Text("本周" if weekly else "今天", "muted"))
        self.stat_state = Text("", "h3")
        first.addWidget(self.stat_state)
        stats_row.addLayout(first, 1)
        second = vbox(None, (0, 0, 0, 0), 4)
        second.addWidget(Text("上次用时", "muted"))
        self.stat_time = Text("", "h3")
        second.addWidget(self.stat_time)
        stats_row.addLayout(second, 1)
        third = vbox(None, (0, 0, 0, 0), 4)
        third.addWidget(Text("最近 7 天", "muted"))
        self.stat_week = WeekDots()
        # The dots sit on the values' line, not lower (2026-10-22 check).
        dots = QWidget()
        dots.setFixedHeight(self.stat_state.sizeHint().height())
        hbox(dots).addWidget(self.stat_week, 0, Qt.AlignLeft | Qt.AlignVCenter)
        third.addWidget(dots)
        stats_row.addLayout(third, 1)
        for column in (first, second, third):
            column.addStretch(1)
        self.detail_layout.addWidget(stats)

        self.include_toggle = None
        if item.included is not None:
            include = Inset()
            include_row = hbox(include, (16, 10, 16, 10), 12)
            texts = vbox(None, (0, 0, 0, 0), 2)
            texts.addWidget(Text(tf("加入{batch}", batch=t(self.batch_name)), "h3"))
            texts.addWidget(Text("关掉后只能在这里单独跑", "muted"))
            include_row.addLayout(texts, 1)
            self.include_toggle = Toggle(bool(item.included))
            self.include_toggle.toggled.connect(
                lambda on, key=item.key: self._set_included(key, on)
            )
            include_row.addWidget(self.include_toggle)
            self.detail_layout.addWidget(include)

        self.disabled_note = None
        if task is not None and "启用" in task.config:
            note = Inset()
            note_row = hbox(note, (16, 10, 16, 10), 12)
            texts = vbox(None, (0, 0, 0, 0), 2)
            texts.addWidget(Text("这一项被关掉了", "warn"))
            texts.addWidget(Text("单独跑时不会做事；一键运行不受影响", "muted"))
            note_row.addLayout(texts, 1)
            enable = Toggle(False)
            enable.toggled.connect(lambda on, t=task: self._enable_task(t, on))
            note_row.addWidget(enable)
            self.detail_layout.addWidget(note)
            self.disabled_note = note

        self.form = None
        own = OWN_PAGES.get(type(task).__name__) if task is not None else None
        if own is not None and self._navigate is not None:
            page_key, page_name, hint = own
            pointer = Inset()
            pointer_row = hbox(pointer, (16, 10, 16, 10), 12)
            texts = vbox(None, (0, 0, 0, 0), 2)
            texts.addWidget(Text(tf("设定在「{page}」页", page=t(page_name)), "h3"))
            texts.addWidget(Text(hint, "muted", wrap=True))
            pointer_row.addLayout(texts, 1)
            pointer_row.addWidget(
                Button(
                    tf("打开{page}页", page=t(page_name)),
                    "secondary",
                    size="sm",
                    on_click=lambda k=page_key: self._navigate(k),
                )
            )
            self.detail_layout.addWidget(pointer)
            keys = [
                key for key in OWN_PAGE_KEYS.get(type(task).__name__, ()) if key in task.config
            ]
            if keys:
                box = Inset()
                box_row = hbox(box, (16, 10, 16, 10), 12)
                form = ConfigForm(task, keys=keys)
                box_row.addWidget(form)
                self.detail_layout.addWidget(box)
                self.form = form
        elif task is not None:
            # Same right edge as the 加入一键… switch above, which sits in a
            # box with a 16 px inner margin (Leo, 2026-10-04: 開關沒有對齊).
            form = ConfigForm(task, skip=("启用",), right_inset=16)
            if not form.is_empty():
                self.detail_layout.addWidget(Separator())
                self.detail_layout.addWidget(Text("设定", "h3"))
                self.detail_layout.addWidget(form)
                foot = hbox(None, (0, 4, 0, 0), 12)
                foot.addWidget(Button("恢复默认", "ghost", size="sm", on_click=form.reset))
                foot.addWidget(Text("改了马上生效", "muted"))
                foot.addStretch(1)
                self.detail_layout.addLayout(foot)
                self.form = form
            else:
                form.deleteLater()

    def _refresh_detail(self, item: _Item) -> None:
        name = item.name
        record = data.last_run(name) or {}
        if self._done(name):
            when = data.clock_text(record.get("finished"))
            if self.weekly or name in self._weekly_names:
                when = f"{data.day_text(record.get('finished'))} {when}".strip()
            self.stat_state.set_text(tf("✓ {when} 完成", when=when))
            self.stat_state.set_role("ok")
        elif (
            record.get("finished")
            and record.get("ok") is False
            and data.day_text(record["finished"]) == "今天"
        ):
            self.stat_state.set_text("今天没做完")
            self.stat_state.set_role("bad")
        else:
            self.stat_state.set_text("还没做")
            self.stat_state.set_role("h3")
        duration = record.get("duration")
        self.stat_time.set_text(fmt_duration(duration) if duration else "-")
        self.stat_week.set_days(data.recent_days(name))
        self.run_one.setEnabled(actions.can_start() and item.task is not None)
        if self.include_toggle is not None:
            self.include_toggle.set_checked_quietly(bool(item.included))
        if self.disabled_note is not None and item.task is not None:
            self.disabled_note.setVisible(not bool(item.task.config.get("启用", True)))

    def _set_included(self, key: str, on: bool) -> None:
        batch = self.batch()
        if batch is not None:
            batch.config[key] = bool(on)
        self.refresh()

    def _enable_task(self, task, on: bool) -> None:
        if on:
            task.config["启用"] = True
        self.refresh()

    def _start_one(self, task) -> None:
        actions.start(task, self.window())
        self.refresh()

    def _start_batch(self) -> None:
        from src.tasks.DailyBatchTask import RUN_MODE_ALL

        actions.start(self.batch(), self.window(), RUN_MODE_ALL)
        self.refresh()

    # ---------------------------------------------------------------- batch options

    def _toggle_options(self) -> None:
        if not self._options_built:
            batch = self.batch()
            if batch is None:
                return
            column = vbox(self.options, (20, 16, 20, 16), 12)
            column.addWidget(Text("一键运行的设定", "h3"))
            keys = [
                key for key in BATCH_OPTION_LABELS if key in batch.config
            ]
            self._options_form = ConfigForm(batch, keys=keys, labels=BATCH_OPTION_LABELS)
            column.addWidget(self._options_form)
            self._options_built = True
        elif not self.options.isVisible():
            # 关闭游戏 can also change in the 一键日常 confirm window.
            self._options_form.sync()
        self.options.setVisible(not self.options.isVisible())
