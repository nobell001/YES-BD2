"""跑图: this week's cartridges as pictures, today's skill counts and the run range."""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.ui.shell import actions, data, icons, motion, theme
from src.ui.shell.config_form import ConfigForm
from src.ui.shell.page import Page, pill, set_pill
from src.ui.shell.widgets import (
    Bar,
    Button,
    Card,
    IconLabel,
    Segmented,
    Text,
    draw_fitted,
    grid_container,
    hbox,
    t,
    tf,
    vbox,
)

TASK_NAME = "每周跑图"
BATCH_KEY = "每周跑图"
RANGE_KEY = "跑图章节"
LIMIT_KEY = "本次最多卡带数"
SKILLS = (("吸收", "magnet"), ("召集", "users-round"), ("压制", "shield"))


def range_text(
    story: list[int],
    character: list[int],
    all_story: list[int],
    all_character: list[int],
    event: list[int] = (),
    all_event: list[int] = (),
) -> str:
    """Selected cards as the task's 跑图章节 text ("全部", "1-7,9", "R1-R2", "E1-E3")."""
    if (
        sorted(story) == sorted(all_story)
        and sorted(character) == sorted(all_character)
        and sorted(event) == sorted(all_event)
    ):
        return "全部"

    def runs(numbers: list[int], prefix: str) -> list[str]:
        parts = []
        numbers = sorted(set(numbers))
        start = previous = None
        for number in numbers + [None]:
            if start is None:
                start = previous = number
                continue
            if number is not None and number == previous + 1:
                previous = number
                continue
            parts.append(
                f"{prefix}{start}" if start == previous else f"{prefix}{start}-{prefix}{previous}"
            )
            start = previous = number
        return parts

    parts = runs(story, "") + runs(character, "R") + runs(list(event), "E")
    return ",".join(parts) if parts else "全部"


class CartridgeTile(QWidget):
    """Cartridge picture, its number and name, and one bar per map."""

    clicked = Signal(str)

    def __init__(self, card: data.CardProgress, parent=None):
        super().__init__(parent)
        self.card = card
        self._pixmap = QPixmap(data.cartridge_picture(card.code) or "")
        self._in_range = True
        self._hover = motion.HoverFade(self, self.update)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tf("{name} · 点一下设定跑不跑这张", name=t(card.name)))
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def set_card(self, card: data.CardProgress, in_range: bool) -> None:
        changed = (card.done_maps, card.complete, in_range) != (
            self.card.done_maps,
            self.card.complete,
            self._in_range,
        )
        self.card = card
        self._in_range = in_range
        if changed:
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.card.code)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        card = self.card
        width = self.width()
        cover = QRectF(0, 0, width, width * 0.72)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("inset"))
        painter.drawRoundedRect(cover, theme.corner(6), theme.corner(6))
        hover = self._hover.value
        if hover > 0:
            painter.setBrush(theme.color("ink", 0.05 * hover))
            painter.drawRoundedRect(cover, theme.corner(6), theme.corner(6))
        painter.setOpacity(1.0 if self._in_range else 0.3)
        if not self._pixmap.isNull():
            # Hovered: the picture grows a little into its frame.
            pad = 6 - 3 * hover
            inner = cover.adjusted(pad, pad, -pad, -pad)
            draw_fitted(painter, inner, self._pixmap, self.devicePixelRatioF())
        painter.setOpacity(1.0)
        if card.complete:
            badge = QRectF(width - 24, 6, 18, 18)
            painter.setBrush(theme.color("map_done"))
            painter.drawEllipse(badge)
            icons.paint(painter, badge.adjusted(3, 3, -3, -3), "check", theme.color("card"), 3.2)
        elif not self._in_range:
            off = QRectF(6, 6, 0, 18)
            font = theme.body_font(self.font())
            font.setPixelSize(10)
            painter.setFont(font)
            text = t("不跑")
            off.setWidth(painter.fontMetrics().horizontalAdvance(text) + 10)
            painter.setBrush(theme.color("card"))
            painter.drawRoundedRect(off, theme.corner(4), theme.corner(4))
            painter.setPen(theme.color("ink2"))
            painter.drawText(off, Qt.AlignCenter, text)
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        top = cover.bottom() + 6
        number = card.code if not card.story else str(card.number)
        painter.setPen(theme.color("ink3"))
        number_width = painter.fontMetrics().horizontalAdvance(number) + 5
        painter.drawText(QRectF(0, top, number_width, 18), Qt.AlignLeft | Qt.AlignVCenter, number)
        painter.setPen(theme.color("ink" if self._in_range else "ink3"))
        name = painter.fontMetrics().elidedText(
            t(card.name), Qt.ElideRight, int(width - number_width)
        )
        painter.drawText(
            QRectF(number_width, top, width - number_width, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            name,
        )
        bars_top = top + 24
        gap = 3.0
        maps = max(1, card.maps)
        bar_width = (width - 34 - gap * (maps - 1)) / maps
        painter.setPen(Qt.NoPen)
        for index in range(card.maps):
            painter.setBrush(
                theme.color("map_done") if index < card.done_maps else theme.color("track")
            )
            painter.drawRoundedRect(
                QRectF(index * (bar_width + gap), bars_top, bar_width, 5),
                theme.corner(2),
                theme.corner(2),
            )
        small = theme.body_font(self.font())
        small.setPixelSize(11)
        painter.setFont(small)
        painter.setPen(theme.color("ink3"))
        painter.drawText(
            QRectF(width - 30, bars_top - 6, 30, 16),
            Qt.AlignRight | Qt.AlignVCenter,
            f"{card.done_maps}/{card.maps}",
        )

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return round(width * 0.72) + 44


class MapPage(Page):
    interval = 5000

    def __init__(self):
        super().__init__(
            "shellMap",
            "跑图",
            tf("每周{weekday} {time} 重新开始 · 每张卡带一周跑一次", **data.weekly_reset_parts()),
        )
        self.status = self.add_action(pill(""))
        self.start_button = self.add_action(
            Button("开始跑图", "primary", "play", on_click=self._start)
        )
        self.more_button = self.add_action(
            Button("", "icon", "ellipsis", on_click=self._toggle_more)
        )
        self.more = Card()
        self.more.hide()
        self.body.addWidget(self.more)
        self._more_built = False

        top, grid = grid_container(300, 14, 2)
        week = Card()
        column = vbox(week, (18, 16, 18, 16), 8)
        column.addWidget(Text("本周进度", "eyebrow"))
        line = hbox(None, (0, 0, 0, 0), 6)
        self.week_value = Text("", "huge")
        self.week_unit = Text("", "muted")
        line.addWidget(self.week_value)
        line.addWidget(self.week_unit, 1, Qt.AlignBottom)
        column.addLayout(line)
        self.week_bar = Bar(height=8)
        column.addWidget(self.week_bar)
        self.week_foot = Text("", "muted")
        column.addWidget(self.week_foot)
        grid.addWidget(week)

        skills = Card()
        skill_column = vbox(skills, (18, 16, 18, 16), 10)
        head = hbox(None, (0, 0, 0, 0), 8)
        head.addWidget(Text("今天的技能次数", "eyebrow"), 1)
        self.skill_foot = Text("", "muted")
        head.addWidget(self.skill_foot)
        skill_column.addLayout(head)
        self.meters = {}
        for name, icon_name in SKILLS:
            row = hbox(None, (0, 0, 0, 0), 10)
            row.addWidget(IconLabel(icon_name, 15, "ink2"))
            label = Text(name, "sub")
            label.setFixedWidth(34)
            row.addWidget(label)
            bar = Bar(height=8)
            row.addWidget(bar, 1)
            value = Text("", "sub")
            value.setMinimumWidth(56)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(value)
            skill_column.addLayout(row)
            self.meters[name] = (bar, value)
        grid.addWidget(skills)
        self.body.addWidget(top)

        cards = Card()
        cards_column = vbox(cards, (18, 16, 18, 18), 12)
        head = hbox(None, (0, 0, 0, 0), 10)
        head.addWidget(Text("卡带", "h2"))
        head.addWidget(Text("点卡带设定这次跑不跑它", "muted"), 1)
        self.reset_range = Button("全部都跑", "ghost", size="sm", on_click=self._all_cards)
        head.addWidget(self.reset_range)
        head.addSpacing(8)
        head.addWidget(Text("每次最多", "sub"))
        self.limit = Segmented(
            [str(n) for n in range(0, 8)],
            None,
            labels={"0": "不限", **{str(n): str(n) for n in range(1, 8)}},
        )
        self.limit.changed.connect(self._set_limit)
        head.addWidget(self.limit)
        cards_column.addLayout(head)
        cards_column.addWidget(Text("剧情卡带", "eyebrow"))
        self.story_box, self.story_grid = grid_container(104, 12)
        cards_column.addWidget(self.story_box)
        cards_column.addWidget(Text("角色卡带", "eyebrow"))
        self.char_box, self.char_grid = grid_container(104, 12)
        cards_column.addWidget(self.char_box)
        cards_column.addWidget(Text("活动卡带", "eyebrow"))
        # Leo 2026-10-09: the event cards are still being tuned.
        cards_column.addWidget(Text("测试中，可能较不稳定", "muted"))
        self.event_box, self.event_grid = grid_container(104, 12)
        cards_column.addWidget(self.event_box)
        self.body.addWidget(cards)
        self.body.addStretch(1)
        self._tiles: dict[str, CartridgeTile] = {}
        self._progress = None
        self._progress_at = 0.0

    def task(self):
        return data.task_by_name(TASK_NAME)

    # ---------------------------------------------------------------- actions

    def _start(self) -> None:
        actions.start(self.task(), self.window())
        self.refresh()

    def _toggle_more(self) -> None:
        if not self._more_built:
            column = vbox(self.more, (20, 16, 20, 16), 12)
            column.addWidget(Text("其他设定", "h3"))
            batch = data.task_by_name(data.DAILY_BATCH)
            if batch is not None and BATCH_KEY in batch.config:
                column.addWidget(
                    ConfigForm(batch, keys=[BATCH_KEY], labels={BATCH_KEY: "加入一键完成日常"})
                )
            task = self.task()
            if task is not None:
                keys = [key for key in ("执行地图采集", "启用") if key in task.config]
                column.addWidget(ConfigForm(task, keys=keys, labels={"启用": "单独跑时启用"}))
            self._more_built = True
        self.more.setVisible(not self.more.isVisible())

    def _set_limit(self, value: str) -> None:
        task = self.task()
        if task is not None:
            task.config[LIMIT_KEY] = int(value)

    @staticmethod
    def _numbers(progress, category: str) -> list[int]:
        return [c.number for c in progress.cards if c.category == category]

    def _selected(self, progress) -> tuple[list[int], list[int], list[int]]:
        from src.tasks.map_trade.collector import chapter_filter

        task = self.task()
        allowed = chapter_filter(task.config.get(RANGE_KEY, "")) if task is not None else None
        story = [
            c.number
            for c in progress.cards
            if c.category == "story" and (allowed is None or c.number in allowed)
        ]
        character = [
            c.number
            for c in progress.cards
            if c.category == "character" and (allowed is None or f"R{c.number}" in allowed)
        ]
        event = [
            c.number
            for c in progress.cards
            if c.category == "event" and (allowed is None or f"E{c.number}" in allowed)
        ]
        return story, character, event

    def _toggle_card(self, code: str) -> None:
        task = self.task()
        progress = self._progress
        if task is None or progress is None:
            return
        story, character, event = self._selected(progress)
        number = int(code[1:])
        target = {"S": story, "R": character, "E": event}.get(code[:1], story)
        if number in target:
            target.remove(number)
        else:
            target.append(number)
        if not story and not character and not event:
            return  # keep at least one card
        task.config[RANGE_KEY] = range_text(
            story,
            character,
            self._numbers(progress, "story"),
            self._numbers(progress, "character"),
            event,
            self._numbers(progress, "event"),
        )
        self.refresh()

    def _all_cards(self) -> None:
        task = self.task()
        if task is not None:
            task.config[RANGE_KEY] = "全部"
        self.refresh()

    # ---------------------------------------------------------------- refresh

    def showEvent(self, event):
        self._progress_at = 0.0
        super().showEvent(event)

    def refresh(self) -> None:
        task = self.task()
        batch = data.task_by_name(data.DAILY_BATCH)
        if data.current_task() is task and task is not None:
            set_pill(self.status, "正在跑", "run")
        elif batch is not None and bool(batch.config.get(BATCH_KEY, False)):
            set_pill(self.status, "一键日常里会跑", "ok")
        else:
            set_pill(self.status, "一键日常里不跑")
        self.start_button.setEnabled(actions.can_start() and task is not None)
        if task is not None:
            self.limit.set_value(str(int(task.config.get(LIMIT_KEY, 0) or 0)))

        if time.time() - self._progress_at > 10 or self._progress is None:
            self._progress = data.map_progress()
            self._progress_at = time.time()
        progress = self._progress
        if progress is None:
            self.week_value.set_text("-")
            return
        cards = len(progress.cards)
        self.week_value.set_text(str(progress.cards_done))
        self.week_unit.set_text(tf("/ {n} 张卡带", n=cards))
        self.week_bar.set_value(progress.cards_done / max(1, cards), "map_done")
        self.week_foot.set_text(
            tf("地图跑了 {done} / {total} 张", done=progress.maps_done, total=progress.maps_total)
        )
        left = []
        for name, _icon in SKILLS:
            used = int(progress.used.get(name, 0))
            limit = int(progress.limits.get(name, 1))
            bar, value = self.meters[name]
            bar.set_value(used / max(1, limit), "warn" if used >= limit else "primary")
            value.set_text(f"{used} / {limit}")
            left.append(limit - used)
        self.skill_foot.set_text("今天的次数用完了" if min(left) <= 0 else tf("每天 {time} 重置", time=data.daily_reset_clock()))

        story, character, event = self._selected(progress)
        grids = {"story": self.story_grid, "character": self.char_grid, "event": self.event_grid}
        chosen = {"story": story, "character": character, "event": event}
        for card in progress.cards:
            tile = self._tiles.get(card.code)
            if tile is None:
                tile = CartridgeTile(card)
                tile.clicked.connect(self._toggle_card)
                grids.get(card.category, self.story_grid).addWidget(tile)
                self._tiles[card.code] = tile
            in_range = card.number in chosen.get(card.category, story)
            tile.set_card(card, in_range)
        everything = len(story) + len(character) + len(event) == cards
        self.reset_range.setVisible(not everything)
