"""定时启动 as a week calendar (Leo 2026-10-29 「改成用行事曆的形式 …
以週為單位」「用的有點像timetree不同人協作那樣」「共享行事曆的感覺」).

Seven day columns (Mon … Sun, no dates: the slots repeat every week) over a
slim time axis, one block per slot on each day it runs, in its 帳號's
colour; the 帳號 row above switches a 帳號's slots off and on (「點帳號可以
讓該帳號變淺變深 變淺該帳號行程隱藏(失效)」); the ＋ at the top right or a
click on a free hour adds one, a click on a block edits it.
"""

from __future__ import annotations

import copy

from ok import Logger
from PySide6.QtCore import QMimeData, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication, QSizePolicy, QWidget
from qfluentwidgets import FlowLayout, ScrollArea

from src.ui.shell import icons, motion, theme
from src.ui.shell.floating import Floating, Panel
from src.ui.shell.run_confirm import HeroIcon
from src.ui.shell.schedule_ui import (
    DELETE_SIZE,
    HOURS,
    MINUTES,
    OPTION_GAP,
    DayChip,
    TaskPickDialog,
    _AccountPill,
    _batch_items,
    _number_box,
    account_ticks,
    settings,
    store,
)
from src.ui.shell.widgets import (
    Button,
    CheckBox,
    Separator,
    Text,
    Toggle,
    hbox,
    mix,
    t,
    tf,
    vbox,
)
from src.utils import accounts, scheduled_start
from src.utils.scheduled_start import KIND_TIME, MAX_SLOTS, Slot

logger = Logger.get_logger(__name__)

# Leo 2026-10-29 「週一到週日用英文」: in every language.
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# One colour per 帳號, in their order (5 at most), as on a shared calendar.
ACCOUNT_COLOURS = ("#7467C4", "#2E9E96", "#E07B5F", "#4A86E8", "#C9962E")
COLUMN_MIN = 76
AXIS = 46  # the time axis on the left
ROW = 40  # one hour
# A block is half an hour tall: two slots are half an hour apart or more.
BLOCK = ROW // 2 - 2
DISC = 14
SHOWN_HOURS = 13  # the hours the window shows before it scrolls
ADD_SIZE = 36


def known_accounts() -> list:
    try:
        return list(accounts.accounts())
    except Exception as exc:  # the list itself is checked before a run
        logger.warning(f"scheduled start: accounts not read ({exc})")
        return []


def current_id() -> str:
    try:
        return accounts.current_id()
    except Exception:
        return ""


def colour_of(account_id: str, known: list) -> QColor:
    ids = [account.id for account in known]
    index = ids.index(account_id) if account_id in ids else 0
    return QColor(ACCOUNT_COLOURS[index % len(ACCOUNT_COLOURS)])


def account_of(account_id: str, known: list):
    for account in known:
        if account.id == account_id:
            return account
    return None


def name_of(account_id: str, known: list) -> str:
    account = account_of(account_id, known)
    if account is None:
        return t("当前账号")
    from src.ui.shell.accounts_ui import display_name

    return display_name(account)


def tag_text(slot: Slot) -> str:
    """The card's small line: its own items and settings, if any."""
    parts = []
    if slot.tasks is not None:
        parts.append(tf("自选 {n} 项", n=len(slot.tasks)))
    if slot.settings:
        parts.append(t("有自己的设定"))
    return " · ".join(parts)


def _ink(colour: QColor) -> QColor:
    """Text on a card of ``colour``: darker in light mode, lighter in dark."""
    dark = theme.tokens() is theme.DARK
    return mix(colour, QColor("#FFFFFF") if dark else theme.color("ink"), 0.38 if dark else 0.42)


def _font(base: QFont, px: int, bold: bool = False) -> QFont:
    font = theme.body_font(base)
    font.setPixelSize(px)
    if bold:
        theme.strong(font, digits=True)
    return font


class _Disc(QWidget):
    """A 帳號's little round picture (or letter) in its colour."""

    def __init__(self, size: int, parent=None):
        super().__init__(parent)
        from src.ui.shell.accounts_ui import Avatar

        self.setFixedSize(size, size)
        self.avatar = Avatar(size, self)
        self.avatar.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def show_account(self, account, colour: QColor) -> None:
        account = account or accounts.current()
        self.avatar.set_colour(colour)
        # The 帳號's number: names often start alike (帳號 1, 帳號 2 …).
        self.avatar.set_letter(account.id)
        self.avatar.set_account(account)


ACCOUNT_MIME = "application/x-yes-bd2-account"


def _start_drag(source: QWidget, event, mime_type: str, data: str, action) -> None:
    """Drag ``source`` with its picture under the pointer."""
    drag = QDrag(source)
    mime = QMimeData()
    mime.setData(mime_type, data.encode("utf-8"))
    drag.setMimeData(mime)
    drag.setPixmap(source.grab())
    drag.setHotSpot(event.position().toPoint())
    drag.exec(action)


def _dragged(press, event) -> bool:
    return press is not None and (
        (event.position().toPoint() - press).manhattanLength() >= QApplication.startDragDistance()
    )


class LegendChip(QAbstractButton):
    """One 帳號 above the calendar: a click switches all its slots off (pale,
    dashed) or on again; dragged onto an hour it adds a slot for this 帳號
    there (Leo 2026-10-29 「上面帳號也要可以拖曳 到特定時間段」)."""

    HEIGHT = 34

    def __init__(self, account, colour: QColor, on: bool, on_toggle):
        super().__init__()
        self.account_id = account.id
        self.colour = colour
        self.setCheckable(True)
        self.setChecked(on)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._hover = motion.HoverFade(self, self.update)
        self._on = motion.Tween(self, self.update, 160, 1.0 if on else 0.0)
        row = hbox(self, (4, 4, 14, 4), 7)
        disc = _Disc(self.HEIGHT - 8)
        disc.show_account(account, colour)
        row.addWidget(disc)
        from src.ui.shell.accounts_ui import display_name

        self.label = Text(display_name(account), "body")
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.label)
        row.addSpacing(10)  # the colour dot
        self.setToolTip(t("点一下暂停或恢复这个账号的时段；拖到时间上新增一个"))
        self._press = None
        self.toggled.connect(
            lambda on: (self._on.go(1.0 if on else 0.0), on_toggle(self.account_id, on))
        )

    def sizeHint(self) -> QSize:
        return self.layout().sizeHint()

    def minimumSizeHint(self) -> QSize:
        return self.layout().minimumSize()

    def mousePressEvent(self, event):
        self._press = event.position().toPoint() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if _dragged(self._press, event):
            self._press = None
            self.setDown(False)  # a drag, not a click: the 帳號 stays as it is
            _start_drag(self, event, ACCOUNT_MIME, self.account_id, Qt.CopyAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        on = float(self._on.value)
        hover = float(self._hover.value)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(mix(theme.color("card"), self.colour, 0.10 * on + 0.05 * hover))
        painter.drawRoundedRect(rect, radius, radius)
        pen = QPen(mix(theme.color("line2"), self.colour, 0.55 * on))
        pen.setWidthF(1.2)
        if on < 0.5:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)
        dot = QRectF(rect.right() - 16, rect.center().y() - 4, 8, 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.colour)
        painter.drawEllipse(dot)
        if on < 1.0:
            # Pale while off: the whole chip under a veil of the card colour.
            painter.setBrush(theme.color("card", 0.62 * (1.0 - on)))
            painter.drawRoundedRect(rect, radius, radius)


class SlotBlock(QAbstractButton):
    """One slot on one day, as tall as half an hour on the grid: its 帳號's
    disc and the time; the name and what is its own when there is room.
    A click opens it; it is not dragged (Leo 2026-10-29 「不要開放拖曳」)."""

    RADIUS = 7

    def __init__(self, slot: Slot, account, colour: QColor, on_click):
        super().__init__()
        self.slot = slot
        self.colour = colour
        self.problem = False
        self._name = name_of(account.id, [account]) if account is not None else t("当前账号")
        self._tag = tag_text(slot)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = motion.HoverFade(self, self.update)
        self.disc = _Disc(DISC, self)
        self.disc.show_account(account, colour)
        self.clicked.connect(lambda *_: on_click(self.slot))
        tip = f"{slot.hour:02d}:{slot.minute:02d} · {self._name}"
        self.setToolTip(f"{tip} · {self._tag}" if self._tag else tip)
        self.day = 0

    def set_problem(self, problem: bool) -> None:
        if problem != self.problem:
            self.problem = problem
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.disc.move(6, (self.height() - DISC) // 2)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hover = float(self._hover.value)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        dark = theme.tokens() is theme.DARK
        fill = mix(theme.color("card"), self.colour, (0.26 if dark else 0.16) + 0.08 * hover)
        if not self.slot.on:
            fill.setAlphaF(0.5)
        painter.fillPath(path, fill)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(rect.left(), rect.top(), 3, rect.height()), self.colour)
        painter.restore()
        if self.problem:
            pen = QPen(theme.color("bad"))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self.RADIUS - 1, self.RADIUS - 1)
        ink = _ink(self.colour)
        x = 6 + DISC + 4
        room = rect.width() - x - 4
        painter.setPen(ink)
        font = _font(self.font(), 12, bold=True)
        painter.setFont(font)
        time = f"{self.slot.hour:02d}:{self.slot.minute:02d}"
        metrics = QFontMetrics(font)
        painter.drawText(QRectF(x, 0, room, rect.height()), Qt.AlignLeft | Qt.AlignVCenter, time)
        x += metrics.horizontalAdvance(time) + 5
        room = rect.right() - 4 - x
        if room <= 12:
            return
        font = _font(self.font(), 11)
        metrics = QFontMetrics(font)
        painter.setFont(font)
        rest = QColor(ink)
        rest.setAlphaF(0.85)
        painter.setPen(rest)
        extra = self._name if not self._tag else f"{self._name} · {self._tag}"
        painter.drawText(
            QRectF(x, 0, room, rect.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            metrics.elidedText(extra, Qt.ElideRight, round(room)),
        )


class _TimeBody(QWidget):
    """The hours, top to bottom: a slim time axis on the left, a click on a
    free hour adds a slot there (Leo 2026-10-29 「左邊要有時間 但不要顯得臃腫
    點該時間也可以新增」)."""

    def __init__(self, on_add, on_edit):
        super().__init__()
        self._on_add = on_add
        self._on_edit = on_edit
        self.today = scheduled_start.local_now().weekday()
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(24 * ROW)
        self.setMinimumWidth(AXIS + 7 * COLUMN_MIN)
        self.blocks: list[SlotBlock] = []
        self._hover_cell: tuple[int, int] | None = None
        self.room = True
        self.setAcceptDrops(True)

    def column_width(self) -> float:
        return (self.width() - AXIS) / 7

    def show_slots(self, slots: list[Slot], known: list, paused: list[str]) -> None:
        for block in self.blocks:
            block.setParent(None)
            block.deleteLater()
        self.blocks = []
        current = current_id()
        for slot in slots:
            runs = slot.runs(current)
            if runs in paused:
                continue
            for day in slot.days:
                block = SlotBlock(
                    slot, account_of(runs, known), colour_of(runs, known), self._on_edit
                )
                block.setParent(self)
                block.day = day
                block.show()
                self.blocks.append(block)
        self._place_blocks()

    def _place_blocks(self) -> None:
        width = self.column_width()
        for block in self.blocks:
            x = AXIS + width * block.day + 3
            y = (block.slot.hour + block.slot.minute / 60) * ROW + 1
            block.setGeometry(round(x), round(y), max(10, round(width - 6)), BLOCK)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_blocks()

    def first_hour(self, shown: int) -> int:
        """The top hour to show: the one that shows the most blocks (the
        earliest of those), with an hour free above them when it can."""
        hours = [block.slot.hour for block in self.blocks]
        if not hours:
            return 7
        starts = range(0, max(1, 25 - shown))
        best = max(starts, key=lambda top: (sum(top < h < top + shown - 1 for h in hours), -top))
        return best

    def _cell(self, pos) -> tuple[int, int] | None:
        if pos.x() < AXIS:
            return None
        day = int((pos.x() - AXIS) // self.column_width())
        hour = int(pos.y() // ROW)
        if 0 <= day < 7 and 0 <= hour < 24:
            return day, hour
        return None

    def mouseMoveEvent(self, event):
        cell = self._cell(event.position()) if self.room else None
        if cell != self._hover_cell:
            self._hover_cell = cell
            self.update()
        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(ACCOUNT_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        cell = self._cell(event.position())
        if cell is None:
            event.ignore()
        else:
            event.acceptProposedAction()
        if cell != self._hover_cell:
            self._hover_cell = cell
            self.update()

    def dragLeaveEvent(self, event):
        self._hover_cell = None
        self.update()

    def dropEvent(self, event):
        cell = self._cell(event.position())
        self._hover_cell = None
        self.update()
        if cell is None or not event.mimeData().hasFormat(ACCOUNT_MIME):
            return
        event.acceptProposedAction()
        account = bytes(event.mimeData().data(ACCOUNT_MIME)).decode("utf-8")
        self._on_add(*cell, account=account, dropped=True)

    def leaveEvent(self, event):
        self._hover_cell = None
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        cell = self._cell(event.position())
        if cell is not None and self.room and event.button() == Qt.LeftButton:
            self._on_add(*cell)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = self.column_width()
        painter.fillRect(self.rect(), theme.color("card"))
        painter.fillRect(
            QRectF(AXIS + width * self.today, 0, width, self.height()),
            theme.color("primary", 0.045),
        )
        line = theme.color("line")
        painter.setPen(QPen(line, 1.0))
        for day in range(8):
            x = AXIS + width * day
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        font = _font(self.font(), 11)
        painter.setFont(font)
        for hour in range(24):
            y = hour * ROW
            painter.setPen(QPen(line, 1.0))
            painter.drawLine(QPointF(AXIS, y), QPointF(self.width(), y))
            if hour:
                painter.setPen(theme.color("ink3"))
                painter.drawText(
                    QRectF(0, y - 8, AXIS - 8, 16),
                    Qt.AlignRight | Qt.AlignVCenter,
                    f"{hour:02d}:00",
                )
        if self._hover_cell is not None:
            day, hour = self._hover_cell
            box = QRectF(AXIS + width * day + 3, hour * ROW + 1, width - 6, BLOCK)
            painter.setBrush(theme.color("primary", 0.07))
            pen = QPen(theme.color("primary"), 1.3)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(box, 7, 7)
            painter.setPen(theme.color("primary"))
            painter.drawText(box, Qt.AlignCenter, f"+ {hour:02d}:00")
        now = scheduled_start.local_now()
        y = (now.hour + now.minute / 60) * ROW
        painter.setPen(QPen(theme.color("bad"), 2.0))
        x = AXIS + width * self.today
        painter.drawLine(QPointF(x, y), QPointF(x + width, y))
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("bad"))
        painter.drawEllipse(QPointF(x, y), 3.5, 3.5)


class _DayHeader(QWidget):
    HEIGHT = 38

    def __init__(self):
        super().__init__()
        self.today = scheduled_start.local_now().weekday()
        self.setFixedHeight(self.HEIGHT)

    def paintEvent(self, _event):
        painter = QPainter(self)
        width = (self.width() - AXIS) / 7
        font = _font(self.font(), 13)
        for day, name in enumerate(DAY_NAMES):
            today = day == self.today
            font.setBold(today)
            painter.setFont(font)
            painter.setPen(theme.color("primary") if today else theme.color("ink2"))
            painter.drawText(
                QRectF(AXIS + width * day, 0, width, self.HEIGHT), Qt.AlignCenter, name
            )


class _HourScroll(ScrollArea):
    """Down to one hour in a very short tool window; the rest scrolls."""

    def minimumSizeHint(self) -> QSize:
        return QSize(super().minimumSizeHint().width(), ROW)


class WeekView(QWidget):
    """The week: day names on top (they stay), the hours under them scroll."""

    RADIUS = 14

    def __init__(self, on_add, on_edit):
        super().__init__()
        box = vbox(self, (1, 1, 1, 1), 0)
        self.header = _DayHeader()
        box.addWidget(self.header)
        self.body = _TimeBody(on_add, on_edit)
        self.scroll = _HourScroll()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(ScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setObjectName("weekHours")
        self.scroll.viewport().setStyleSheet("QWidget#weekHours { background: transparent; }")
        self.scroll.setWidget(self.body)
        box.addWidget(self.scroll, 1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    @property
    def blocks(self) -> list[SlotBlock]:
        return self.body.blocks

    def sizeHint(self) -> QSize:
        return QSize(AXIS + 7 * COLUMN_MIN, _DayHeader.HEIGHT + SHOWN_HOURS * ROW + 2)

    def minimumSizeHint(self) -> QSize:
        return QSize(AXIS + 7 * COLUMN_MIN, _DayHeader.HEIGHT + ROW + 2)

    def show_slots(self, slots: list[Slot], known: list, paused: list[str], room: bool) -> None:
        self.body.room = room
        self.body.show_slots(slots, known, paused)

    def scroll_to_first(self) -> None:
        shown = max(1, self.scroll.viewport().height() // ROW)
        self.scroll.verticalScrollBar().setValue(self.body.first_hour(shown) * ROW)

    def mark(self, slots: list[Slot], bad: list[Slot]) -> None:
        """Red edges on the blocks that cannot be saved: only on the days
        where their slot is too close to another."""
        current = current_id()
        for block in self.body.blocks:
            slot = block.slot
            wrong = any(slot is each for each in bad) and (
                not slot.days
                or any(
                    Slot(
                        KIND_TIME, slot.hour, slot.minute, [block.day], account=slot.account
                    ).clashes_with(other, current)
                    for other in slots
                    if other is not slot
                )
            )
            block.set_problem(wrong)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        painter.fillPath(path, theme.color("card"))
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(
            QRectF(rect.left(), rect.top(), rect.width(), _DayHeader.HEIGHT), theme.color("inset")
        )
        painter.restore()
        painter.setPen(QPen(theme.color("line"), 1.0))
        y = rect.top() + _DayHeader.HEIGHT + 0.5
        painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)


class AddButton(QAbstractButton):
    """The round ＋ at the top right (Leo 2026-10-29 「加號挪到右上角」)."""

    def __init__(self, on_click):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(ADD_SIZE, ADD_SIZE)
        self.setToolTip(t("新增时段"))
        self._hover = motion.HoverFade(self, self.update)
        self.clicked.connect(lambda *_: on_click())

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hover = float(self._hover.value) if self.isEnabled() else 0.0
        colour = mix(theme.color("primary"), theme.color("primary_hover"), hover)
        if not self.isEnabled():
            colour = theme.color("line2")
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        side = 16
        centre = QRectF(self.rect()).center()
        icons.paint(
            painter,
            QRectF(centre.x() - side / 2, centre.y() - side / 2, side, side),
            "plus",
            theme.color("on_primary"),
            2.4,
        )


def why_not(slot: Slot, others: list[Slot], known: list) -> str:
    """Why ``slot`` cannot be saved next to ``others`` ("" = it can)."""
    if not slot.days:
        return t("没选星期，这个时段不会跑")
    current = current_id()
    mine = slot.runs(current)
    same = [other for other in others if other.runs(current) == mine]
    if len(same) >= MAX_SLOTS:
        return tf("每个账号最多 {n} 个时段", n=MAX_SLOTS)
    slot.on = True
    for other in others:
        if not slot.clashes_with(other, current):
            continue
        time = f"{other.hour:02d}:{other.minute:02d}"
        if other.runs(current) == mine:
            return tf(
                "{name} 在 {time} 已经有一个时段，同一个账号要隔 1 小时",
                name=name_of(mine, known),
                time=time,
            )
        return tf(
            "{name} 在 {time} 有一个时段，不同账号要隔半小时",
            name=name_of(other.runs(current), known),
            time=time,
        )
    return ""


class SlotEditor(Floating):
    """Add or change one slot (Leo's 「點卡片修改」): time, days, 帳號, items.

    ``others``: the other slots, for the same-帳號 clash check."""

    PANEL_WIDTH = 440

    def __init__(self, slot: Slot, others: list[Slot], known: list, parent, new: bool = False):
        super().__init__(parent)
        self.slot = copy.deepcopy(slot)
        self.deleted = False
        self._others = others
        self._known = known
        column = self.column

        head = hbox(None, (0, 0, 0, 0), 10)
        head.addWidget(HeroIcon("clock", 40))
        head.addWidget(Text("新增时段" if new else "修改这个时段", "h3"), 1)
        if not new:
            self.delete = Button("", "ghost", "trash-2", on_click=self._delete)
            self.delete.setFixedSize(DELETE_SIZE, DELETE_SIZE)
            self.delete.setToolTip(t("删除这个时段"))
            head.addWidget(self.delete, 0, Qt.AlignVCenter)
        column.addLayout(head)

        column.addWidget(Text("时间", "muted"))
        clock = hbox(None, (0, 0, 0, 0), 4)
        self.hour = _number_box(HOURS, self.slot.hour, self._changed)
        self.minute = _number_box(MINUTES, self.slot.minute, self._changed)
        clock.addWidget(self.hour)
        clock.addWidget(Text(":", "h3"))
        clock.addWidget(self.minute)
        clock.addStretch(1)
        column.addLayout(clock)

        column.addWidget(Text("每周哪几天", "muted"))
        chips = hbox(None, (0, 0, 0, 0), 6)
        self.days: list[DayChip] = []
        for day in range(7):
            chip = DayChip(day, day in self.slot.days)
            chip.toggled.connect(lambda _on: self._changed())
            chips.addWidget(chip)
            self.days.append(chip)
        chips.addStretch(1)
        column.addLayout(chips)

        self.pills: list[_AccountPill] = []
        if len(known) > 1:
            column.addWidget(Text("账号", "muted"))
            holder = QWidget()
            flow = FlowLayout(holder, needAni=False)
            flow.setContentsMargins(0, 0, 0, 0)
            flow.setHorizontalSpacing(8)
            flow.setVerticalSpacing(8)
            for account in known:
                pill = _AccountPill(account, self._pick_account, colour_of(account.id, known))
                self.pills.append(pill)
                flow.addWidget(pill)
            column.addWidget(holder)
            if not self.slot.account:
                self.slot.account = current_id()
            self._show_account()

        column.addWidget(Text("任务", "muted"))
        self.what = Button("", "secondary", "list-checks", on_click=self._pick_tasks)
        self.what.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        column.addWidget(self.what)
        self._show_tasks()

        self.problem = Text("", "bad", wrap=True)
        self.problem.hide()
        column.addWidget(self.problem)
        buttons = hbox(None, (0, 6, 0, 0), 8)
        buttons.addStretch(1)
        buttons.addWidget(Button("取消", "secondary", on_click=self.reject))
        self.ok = Button("确定", "primary", on_click=self.accept)
        buttons.addWidget(self.ok)
        column.addLayout(buttons)
        self._changed()

    def _pick_account(self, account_id: str) -> None:
        self.slot.account = account_id
        self._show_account()
        self._show_tasks()
        self._changed()

    def _show_account(self) -> None:
        for pill in self.pills:
            pill.setChecked(pill.account_id == self.slot.account)

    def _pick_tasks(self) -> None:
        dialog = TaskPickDialog(self.slot, self.window())
        if not dialog.exec():
            return
        self.slot.tasks = dialog.tasks()
        self.slot.settings = dialog.item_settings()
        self._show_tasks()

    def _show_tasks(self) -> None:
        if self.slot.tasks is None:  # not picked yet: that 帳號's ticks
            n = len(account_ticks(self.slot.account))
        else:
            n = len(self.slot.tasks)
        text = tf("{n} 项", n=n)
        if self.slot.settings:
            text = f"{text} · {t('有自己的设定')}"
        self.what.set_label(text)

    def _changed(self, _index: int = 0) -> None:
        self.slot.hour = HOURS[self.hour.currentIndex()]
        self.slot.minute = MINUTES[self.minute.currentIndex()]
        self.slot.days = [day for day, chip in enumerate(self.days) if chip.isChecked()]
        why = self.why_not()
        self.problem.set_text(why)
        self.problem.setVisible(bool(why))
        self.ok.setEnabled(not why)

    def why_not(self) -> str:
        return why_not(self.slot, self._others, self._known)

    def _delete(self) -> None:
        self.deleted = True
        self.accept()

    def mouseReleaseEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.reject()
        super().mouseReleaseEvent(event)


def _with_tasks(slot: Slot) -> Slot:
    """No 「照帳號勾選」 any more (Leo 2026-10-29): a slot saved without its
    own items keeps the ones its 帳號 has ticked now."""
    if slot.tasks is None:
        ticked = account_ticks(slot.account)
        slot.tasks = [item.key for item in _batch_items() if item.key in ticked]
    return slot


class ScheduleDialog(Floating):
    """定时启动: the week calendar, the 帳號 above it, the options below."""

    PANEL_WIDTH = 960

    def __init__(self, parent: QWidget | None):
        super().__init__(parent)
        self.working = copy.deepcopy(settings())
        self.known = known_accounts()
        column = self.column

        head = hbox(None, (0, 0, 0, 0), 12)
        head.addWidget(HeroIcon("clock", 44))
        titles = vbox(None, (0, 0, 0, 0), 2)
        titles.addWidget(Text("定时启动", "h2"))
        titles.addWidget(
            Text(
                "时间到自动打开游戏，跑今天还没做的。点空格或右上角 ＋ 新增，点色块修改",
                "sub",
                wrap=True,
            )
        )
        head.addLayout(titles, 1)
        self.master = Toggle(self.working.enabled)
        self.master.setToolTip(t("关掉就完全取消，Windows 里也不留"))
        self.master.toggled.connect(self._master_changed)
        head.addWidget(self.master, 0, Qt.AlignVCenter)
        column.addLayout(head)

        self.body = QWidget()
        body = vbox(self.body, (0, 2, 0, 0), 12)
        self.legend: list[LegendChip] = []
        legend = hbox(None, (0, 0, 0, 0), 8)
        if len(self.known) > 1:
            for account in self.known:
                chip = LegendChip(
                    account,
                    colour_of(account.id, self.known),
                    account.id not in self.working.paused,
                    self._toggle_account,
                )
                legend.addWidget(chip)
                self.legend.append(chip)
        legend.addStretch(1)
        if len(self.known) > 1:
            hint = Text("同一个账号隔 1 小时，不同账号隔半小时", "muted", wrap=True)
            hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            legend.addWidget(hint, 1)
        # Leo 2026-10-29 「加號挪到右上角」.
        self.add_button = AddButton(self._add_now)
        legend.addWidget(self.add_button, 0, Qt.AlignVCenter)
        body.addLayout(legend)
        self.week = WeekView(self._add, self._edit)
        body.addWidget(self.week, 1)
        self.problem = Text("", "bad", wrap=True)
        self.problem.hide()
        body.addWidget(self.problem)
        body.addWidget(Separator())
        self.wake = CheckBox("电脑睡着时叫醒它", self.working.wake)
        # Leo 2026-10-22 「要備註關機時不能使用」: on the box itself, so the
        # calendar keeps the room.
        self.wake.setToolTip(t("睡眠中会被叫醒；完全关机的电脑叫不醒"))
        self.close_game = CheckBox("做完关闭游戏", self.working.close_game)
        self.shutdown = CheckBox("做完关机", self.working.shutdown)
        for box in (self.close_game, self.shutdown):
            box.setToolTip(t("定时启动跑的那次，全部做完且没有失败时才会做"))
        options = hbox(None, (0, 2, 0, 0), OPTION_GAP)
        for box in (self.wake, self.close_game, self.shutdown):
            options.addWidget(box)
        options.addStretch(1)
        body.addLayout(options)
        column.addWidget(self.body, 1)

        self.message = Text("", "warn", wrap=True)
        self.message.hide()
        column.addWidget(self.message)
        buttons = hbox(None, (0, 6, 0, 0), 8)
        buttons.addStretch(1)
        buttons.addWidget(Button("取消", "secondary", on_click=self.reject))
        self.save_button = Button("保存", "primary", on_click=self._save)
        buttons.addWidget(self.save_button)
        column.addLayout(buttons)

        self._fill()
        self._master_changed(self.working.enabled)
        QTimer.singleShot(0, self.week.scroll_to_first)

    # -- the calendar

    def _room(self, account: str) -> bool:
        current = current_id()
        mine = [s for s in self.working.slots if s.runs(current) == (account or current)]
        return len(mine) < MAX_SLOTS

    def _fill(self) -> None:
        room = self._room(self._new_account())
        self.week.show_slots(self.working.slots, self.known, self.working.paused, room)
        self.add_button.setEnabled(room)
        self.add_button.setToolTip(
            t("新增时段") if room else tf("每个账号最多 {n} 个时段", n=MAX_SLOTS)
        )
        self._check()
        self._place()

    def _toggle_account(self, account_id: str, on: bool) -> None:
        paused = [each for each in self.working.paused if each != account_id]
        if not on:
            paused.append(account_id)
        self.working.paused = paused
        self._fill()

    def _new_account(self) -> str:
        return current_id() if len(self.known) > 1 else ""

    def _add_now(self) -> None:
        """The ＋ at the top right: today, at the first free hour from 21:00."""
        hour, minute = scheduled_start.free_time(self.working.slots)
        self._add(scheduled_start.local_now().weekday(), hour, minute)

    def _add(
        self,
        day: int,
        hour: int,
        minute: int = 0,
        account: str | None = None,
        dropped: bool = False,
    ) -> None:
        """A new slot on ``day`` at ``hour``.  A 帳號 dropped there asks
        what to run right away (Leo 2026-10-29 「從上面拖曳下來的時候就要選
        任務了」); when something is in its way the editor says why."""
        account = self._new_account() if account is None else account
        if not self._room(account):
            return
        slot = Slot(KIND_TIME, hour, minute, [day], account=account)
        if dropped and not why_not(slot, self.working.slots, self.known):
            picker = TaskPickDialog(slot, self.window())
            if not picker.exec():
                return
            slot.tasks = picker.tasks()
            slot.settings = picker.item_settings()
            self.working.slots.append(slot)
            self._fill()
            return
        editor = SlotEditor(slot, list(self.working.slots), self.known, self.window(), new=True)
        if editor.exec():
            self.working.slots.append(_with_tasks(editor.slot))
            self._fill()

    def _edit(self, slot: Slot) -> None:
        others = [other for other in self.working.slots if other is not slot]
        editor = SlotEditor(slot, others, self.known, self.window())
        if not editor.exec():
            return
        index = next(i for i, other in enumerate(self.working.slots) if other is slot)
        if editor.deleted:
            del self.working.slots[index]
        else:
            self.working.slots[index] = _with_tasks(editor.slot)
        self._fill()

    def _check(self) -> None:
        """Mark the cards that cannot be saved; 保存 waits until none is left."""
        problems = scheduled_start.slot_problems(self.working.slots)
        bad = [slot for slot, why in zip(self.working.slots, problems) if why]
        self.week.mark(self.working.slots, bad)
        why = next((why for why in problems if why), "")
        self.problem.set_text(t(why) if why else "")
        self.problem.setVisible(bool(why))
        self.save_button.setEnabled(not (self.working.enabled and why))

    def _master_changed(self, on: bool) -> None:
        self.working.enabled = on
        self.body.setEnabled(on)
        self._check()

    def least_width(self) -> int:
        margins = self.column.contentsMargins()
        week = AXIS + 7 * COLUMN_MIN + margins.left() + margins.right()
        return max(super().least_width(), week)

    def _save(self) -> None:
        self.working.wake = self.wake.isChecked()
        self.working.close_game = self.close_game.isChecked()
        self.working.shutdown = self.shutdown.isChecked()
        why = store(self.working)
        if why:
            self.message.set_text(why)
            self.message.show()
            self._place()
            return
        self.accept()

    def mouseReleaseEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.reject()
        super().mouseReleaseEvent(event)


__all__ = ["ScheduleDialog", "SlotEditor", "WeekView", "Panel"]
