"""Parts of the 跑商 page: the card layouts and the 招募书 / 史莱姆 rows.

Leo 2026-11-10: the 卖 card says how many 招募书 and 史莱姆 to keep.  Typed
numbers, no sliders; nothing is filled in for the player and an empty box
means "not sold"; a 0 means "sell all" and gets a warning.  Each row has its
own switch, and its boxes slide away when the switch is off.  Leo 2026-11-14:
a switched-off row still shows the pictures of what it sells, beside the
switch, the way the intro video draws the page.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QSizePolicy,
    QWidget,
)

from src.ui.shell import icons, motion, theme
from src.ui.shell.widgets import (
    SHADOW_MARGINS,
    Button,
    Card,
    IconLabel,
    Inset,
    Text,
    Toggle,
    attach_hint,
    draw_fitted,
    hbox,
    set_prop,
    t,
    vbox,
)


def _height_of(item: QLayoutItem, width: int) -> int:
    if item.hasHeightForWidth():
        return max(item.heightForWidth(width), item.minimumSize().height())
    return max(item.sizeHint().height(), item.minimumSize().height())


class _ItemsLayout(QLayout):
    """The list handling every layout here shares."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout(rect, False)

    def _layout(self, rect: QRect, test_only: bool) -> int:
        raise NotImplementedError


def hold(layout_class, *args, **kwargs) -> tuple[QWidget, QLayout]:
    """A plain widget laid out by ``layout_class`` whose height follows its width."""
    box = QWidget()
    layout = layout_class(box, *args, **kwargs)
    policy = box.sizePolicy()
    policy.setHeightForWidth(True)
    box.setSizePolicy(policy)
    return box, layout


class BalancedFlow(_ItemsLayout):
    """Same-size tiles in as few rows as fit, with the rows equally full
    (ten dishes are 10, or 5 + 5, never 7 + 3)."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._space = spacing

    def _tile(self) -> QSize:
        return self._items[0].sizeHint() if self._items else QSize(0, 0)

    def per_row(self, width: int) -> int:
        count = len(self._items)
        if not count:
            return 1
        tile = self._tile().width()
        fit = max(1, (width + self._space) // (tile + self._space))
        rows = -(-count // fit)
        return -(-count // rows)

    def row_width(self, count: int | None = None) -> int:
        """The width ``count`` tiles (all of them by default) need in one row."""
        count = len(self._items) if count is None else count
        return count * self._tile().width() + max(0, count - 1) * self._space

    def sizeHint(self) -> QSize:
        return QSize(self.row_width(), self._tile().height())

    def minimumSize(self) -> QSize:
        return self._tile()

    def _layout(self, rect: QRect, test_only: bool) -> int:
        if not self._items:
            return 0
        tile = self._tile()
        per_row = self.per_row(rect.width())
        rows = -(-len(self._items) // per_row)
        if not test_only:
            for index, item in enumerate(self._items):
                row, column = divmod(index, per_row)
                item.setGeometry(
                    QRect(
                        rect.x() + column * (tile.width() + self._space),
                        rect.y() + row * (tile.height() + self._space),
                        tile.width(),
                        tile.height(),
                    )
                )
        return rows * tile.height() + (rows - 1) * self._space


class StepRow(_ItemsLayout):
    """买 / 做料理 / 卖 next to each other, all as tall as the tallest (Leo
    2026-11-10 「卡片看起來不等高 要等高」); one under the other when the
    window is too narrow for the three.

    ``least`` is each card's narrowest width, ``share`` how the width beyond
    that is split (做料理 and 卖 hold more than 买)."""

    def __init__(self, parent=None, least=(230, 340, 350), share=(1.0, 3.0, 2.4), spacing=14):
        super().__init__(parent)
        self._least = tuple(least)
        self._share = tuple(share)
        self._space = spacing

    def minimumSize(self) -> QSize:
        return QSize(max(self._least), 0)

    def sizeHint(self) -> QSize:
        width = sum(self._least) + self._space * (len(self._least) - 1)
        return QSize(width, self.heightForWidth(width))

    def widths(self, width: int) -> list[int] | None:
        """Each card's width in one row, or None when they do not fit side by side."""
        count = len(self._items)
        least = self._least[:count]
        spare = width - sum(least) - self._space * (count - 1)
        if count == 0 or spare < 0:
            return None
        total = sum(self._share[:count])
        widths = [int(low + spare * part / total) for low, part in zip(least, self._share)]
        widths[-1] += width - self._space * (count - 1) - sum(widths)
        return widths

    def _layout(self, rect: QRect, test_only: bool) -> int:
        if not self._items:
            return 0
        widths = self.widths(rect.width())
        if widths is None:
            y = rect.y()
            for item in self._items:
                height = _height_of(item, rect.width())
                if not test_only:
                    item.setGeometry(QRect(rect.x(), y, rect.width(), height))
                y += height + self._space
            return y - self._space - rect.y()
        height = max(_height_of(item, width) for item, width in zip(self._items, widths))
        if not test_only:
            x = rect.x()
            for item, width in zip(self._items, widths):
                item.setGeometry(QRect(x, rect.y(), width, height))
                x += width + self._space
        return height


class SideOrStack(_ItemsLayout):
    """Two groups side by side with a hairline between them (Leo 2026-11-10:
    额外料理 「放在5星料理的右邊 中間稍微隔開」), or the second under the
    first when one row is too narrow for both.  Takes exactly: first group,
    the hairline, second group."""

    def __init__(self, parent=None, gap: int = 16, row_gap: int = 12):
        super().__init__(parent)
        self._gap = gap
        self._row_gap = row_gap

    def side_by_side(self, width: int) -> bool:
        if len(self._items) < 3:
            return False
        first, _line, second = self._items[:3]
        need = first.sizeHint().width() + second.sizeHint().width() + 2 * self._gap + 1
        return width >= need

    def minimumSize(self) -> QSize:
        widths = [item.minimumSize().width() for item in self._items] or [0]
        return QSize(max(widths), 0)

    def sizeHint(self) -> QSize:
        widths = [item.sizeHint().width() for item in self._items] or [0]
        return QSize(max(widths), self.heightForWidth(max(widths)))

    def _layout(self, rect: QRect, test_only: bool) -> int:
        if len(self._items) < 3:
            return 0
        first, line, second = self._items[:3]
        if self.side_by_side(rect.width()):
            left = first.sizeHint().width()
            right_x = rect.x() + left + 2 * self._gap + 1
            right = rect.right() + 1 - right_x
            height = max(_height_of(first, left), _height_of(second, right))
            if not test_only:
                first.setGeometry(QRect(rect.x(), rect.y(), left, height))
                line.setGeometry(QRect(rect.x() + left + self._gap, rect.y() + 2, 1, height - 4))
                second.setGeometry(QRect(right_x, rect.y(), right, height))
            return height
        top = _height_of(first, rect.width())
        bottom = _height_of(second, rect.width())
        if not test_only:
            first.setGeometry(QRect(rect.x(), rect.y(), rect.width(), top))
            line.setGeometry(QRect(rect.x(), rect.y(), 0, 0))
            second.setGeometry(
                QRect(rect.x(), rect.y() + top + self._row_gap, rect.width(), bottom)
            )
        return top + self._row_gap + bottom


class VLine(QWidget):
    """A vertical hairline."""

    def sizeHint(self) -> QSize:
        return QSize(1, 1)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), theme.color("line2"))


# ---------------------------------------------------------------- keep box


class KeepBox(QFrame):
    """How many to keep: a typed whole number, or empty (= not sold).

    ``text()`` is exactly what the player typed, digits only.  A 0 turns the
    edge rose: the row says why and a note pops up (see ``ZeroNote``)."""

    changed = Signal(str)  # every edit, by typing or by − / +
    settled = Signal()  # typing paused, or the box was left

    def __init__(
        self,
        picture: str | None = None,
        name: str = "",
        accent: str | None = None,
        steppers: bool = False,
        digits: int = 7,
        parent=None,
    ):
        super().__init__(parent)
        self._pixmap = QPixmap(picture) if picture else QPixmap()
        self._accent = accent
        self._digits = digits
        self.setFixedHeight(theme.size("control_md"))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row = hbox(self, (4 if steppers else 8, 3, 4 if steppers else 10, 3), 2)
        self._icon_room = 0
        if not self._pixmap.isNull():
            self._icon_room = theme.size("control_md") - 6
            row.addSpacing(self._icon_room + 2)
        self._minus = self._plus = None
        if steppers:
            self._minus = Button(
                "", "stepper", "minus", "sm", self, on_click=lambda: self._nudge(-1)
            )
            row.addWidget(self._minus)
        self.edit = QLineEdit(self)
        self.edit.setObjectName("stepperEdit")
        self.edit.setFrame(False)
        self.edit.setAlignment((Qt.AlignCenter if steppers else Qt.AlignRight) | Qt.AlignVCenter)
        self.edit.setMaxLength(digits)
        self.edit.setPlaceholderText(t("不卖"))
        self.edit.setFocusPolicy(Qt.ClickFocus)
        self.edit.textEdited.connect(self._typed)
        self.edit.editingFinished.connect(self._left)
        self.edit.installEventFilter(self)
        row.addWidget(self.edit, 1)
        if steppers:
            self._plus = Button("", "stepper", "plus", "sm", self, on_click=lambda: self._nudge(1))
            row.addWidget(self._plus)
        if name:
            self.setToolTip(t(name))
        self._pause = QTimer(self)
        self._pause.setSingleShot(True)
        self._pause.setInterval(600)
        self._pause.timeout.connect(self.settled.emit)
        self._ring = motion.Tween(self, self.update, 180, 0.0)
        self._tint()
        theme.on_theme_changed(self, self._tint)
        self._sync()

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self.edit.font())
        room = max(
            metrics.horizontalAdvance("0" * self._digits),
            metrics.horizontalAdvance(self.edit.placeholderText()),
        )
        width = room + 26 + self._icon_room
        if self._minus is not None:
            width += 2 * (theme.size("control_md") - 6)
        return QSize(width, theme.size("control_md"))

    def minimumSizeHint(self) -> QSize:
        return QSize(self.sizeHint().width() - 18, theme.size("control_md"))

    # ---------------------------------------------------------------- value

    def text(self) -> str:
        return self.edit.text()

    def is_zero(self) -> bool:
        text = self.edit.text()
        return bool(text) and int(text) == 0

    def set_text(self, text: str) -> None:
        """Show a saved value (not while the player is typing in the box)."""
        text = "".join(ch for ch in str(text or "") if ch in "0123456789")[: self._digits]
        if self.edit.hasFocus() or text == self.edit.text():
            return
        self.edit.setText(text)
        self._sync()

    def _typed(self, text: str) -> None:
        digits = "".join(ch for ch in text if ch in "0123456789")
        if digits != text:
            self.edit.setText(digits)
        self._sync()
        self._pause.start()
        self.changed.emit(digits)

    def _left(self) -> None:
        text = self.edit.text()
        if text and str(int(text)) != text:  # 007 → 7
            self.edit.setText(str(int(text)))
            self.changed.emit(self.edit.text())
        self._sync()
        if self._pause.isActive():
            self._pause.stop()
            self.settled.emit()

    def _nudge(self, step: int) -> None:
        text = self.edit.text()
        value = (int(text) if text else 0) + step
        value = max(0, min(10**self._digits - 1, value))
        self.edit.setText(str(value))
        self._sync()
        self.changed.emit(self.edit.text())
        self.settled.emit()

    def _sync(self) -> None:
        text = self.edit.text()
        if self._minus is not None:
            self._minus.setEnabled(bool(text) and int(text) > 0)
        self._ring.go(1.0 if self.is_zero() else 0.0)
        self.update()

    def _tint(self) -> None:
        palette = self.edit.palette()
        palette.setColor(palette.ColorRole.PlaceholderText, theme.color("ink3"))
        self.edit.setPalette(palette)
        self.update()

    def eventFilter(self, watched, event):
        if watched is self.edit and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.update()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        # Anywhere on the box (the picture too) starts typing.
        self.edit.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        body = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        corner = min(theme.corner(4), body.height() / 2)
        zero = float(self._ring.value)
        if zero > 0.01:
            edge = QPen(theme.color("bad"), 1.0 + 0.6 * zero)
        elif self.edit.hasFocus():
            edge = QPen(theme.color("primary"), 1.6)
        else:
            edge = QPen(theme.color("hair2"), 1)
        painter.setPen(edge)
        painter.setBrush(theme.color("card"))
        painter.drawRoundedRect(body, corner, corner)
        if self._accent and zero <= 0.01 and not self.edit.hasFocus():
            # The slime's own colour along the bottom edge, inside the corners.
            clip = QPainterPath()
            clip.addRoundedRect(body, corner, corner)
            painter.save()
            painter.setClipPath(clip)
            painter.fillRect(
                QRectF(body.x() + self._icon_room + 8, body.bottom() - 1.5, body.width(), 2),
                theme.color(self._accent),
            )
            painter.restore()
        if not self._pixmap.isNull():
            side = self._icon_room
            draw_fitted(
                painter,
                QRectF(5, (self.height() - side) / 2, side, side),
                self._pixmap,
                self.devicePixelRatioF(),
            )


class ZeroNote(QWidget):
    """The warning under a box that holds 0 (Leo 2026-11-10 「當玩家填0時 跳出
    提示用戶:填0代表全賣，請謹慎設置」).  A part of the page, not a window:
    it never covers the game, and goes away by itself or with a click."""

    TEXT = "填 0 代表全卖，请谨慎设置"
    ARROW = 7
    SHOWN_MS = 6000

    def __init__(self, host: QWidget):
        super().__init__(host)
        self._host = host
        self._anchor: QWidget | None = None
        self._tip_x = 0.0
        self._above = False
        self._fade = motion.Tween(self, self._faded, 200, 0.0)
        self._gone = QTimer(self)
        self._gone.setSingleShot(True)
        self._gone.setInterval(self.SHOWN_MS)
        self._gone.timeout.connect(self.dismiss)
        self.setCursor(Qt.PointingHandCursor)
        self.hide()

    def _words(self) -> str:
        return t(self.TEXT)

    def anchor(self) -> QWidget | None:
        return self._anchor if self.isVisible() else None

    def show_under(self, anchor: QWidget) -> None:
        self._anchor = anchor
        self.place()
        self.show()
        self.raise_()
        self._fade.go(1.0)
        self._gone.start()

    def dismiss(self) -> None:
        self._gone.stop()
        if not self.isVisible():
            return
        self._fade.go(0.0)

    def place(self) -> None:
        """Under the box, its arrow on the box's middle; above when the page ends there."""
        anchor = self._anchor
        if anchor is None:
            return
        metrics = QFontMetrics(self.font())
        width = metrics.horizontalAdvance(self._words()) + 16 + 8 + 24
        height = max(30, metrics.height() + 14) + self.ARROW
        # Inside the card that holds the box (live 2560x1440 2026-11-10: it
        # stuck 12 px out of the 卖 card's right edge), else inside the page.
        left, right = 4, self._host.width() - 4
        card = anchor.parentWidget()
        while card is not None and card is not self._host and not isinstance(card, Card):
            card = card.parentWidget()
        if isinstance(card, Card):
            body = card.rect().adjusted(*SHADOW_MARGINS[:2], -SHADOW_MARGINS[2], -SHADOW_MARGINS[3])
            corner = card.mapTo(self._host, body.topLeft())
            if body.width() - 8 >= width:
                left, right = corner.x() + 4, corner.x() + body.width() - 4
        width = min(width, max(120, right - left))
        origin = anchor.mapTo(self._host, anchor.rect().bottomLeft())
        middle = origin.x() + anchor.width() / 2
        x = int(max(left, min(right - width, middle - width / 2)))
        y = origin.y() + 3
        self._above = y + height > self._host.height() - 4
        if self._above:
            y = origin.y() - anchor.height() - height - 3
        self._tip_x = max(14.0, min(width - 14.0, middle - x))
        self.setGeometry(x, y, int(width), int(height))

    def _faded(self) -> None:
        if self._fade.value <= 0.0 and self._fade.target <= 0.0:
            self.hide()
        self.update()

    def mousePressEvent(self, _event):
        self.dismiss()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(max(0.0, min(1.0, float(self._fade.value))))
        arrow = self.ARROW
        body = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._above:
            body.setBottom(body.bottom() - arrow)
            tip = [
                QPointF(self._tip_x - arrow, body.bottom()),
                QPointF(self._tip_x, body.bottom() + arrow),
                QPointF(self._tip_x + arrow, body.bottom()),
            ]
        else:
            body.setTop(body.top() + arrow)
            tip = [
                QPointF(self._tip_x - arrow, body.top()),
                QPointF(self._tip_x, body.top() - arrow),
                QPointF(self._tip_x + arrow, body.top()),
            ]
        shape = QPainterPath()
        shape.addRoundedRect(body, 9, 9)
        point = QPainterPath()
        point.addPolygon(QPolygonF(tip))
        point.closeSubpath()
        shape = shape.united(point)
        painter.setPen(QPen(theme.color("bad"), 1.2))
        painter.setBrush(theme.color("bad_soft"))
        painter.drawPath(shape)
        icons.paint(
            painter,
            QRectF(body.x() + 10, body.center().y() - 8, 16, 16),
            "circle-alert",
            theme.color("badge_must_ink"),
            2.0,
        )
        painter.setPen(theme.color("ink"))
        painter.drawText(
            body.adjusted(10 + 16 + 8, 0, -10, 0), Qt.AlignLeft | Qt.AlignVCenter, self._words()
        )


# ---------------------------------------------------------------- asset rows


class ContractPile(QWidget):
    """Item pictures overlapped: the three 招募书 one box covers, and the
    pictures a switched-off row shows beside its switch.  ``fade`` (0..1) is
    how much of it shows."""

    SIDE = 26
    STEP = 17

    def __init__(self, pictures: list[str | None], parent=None):
        super().__init__(parent)
        self._pixmaps = [QPixmap(path) for path in pictures if path]
        self.fade = 1.0
        count = max(1, len(self._pixmaps))
        self.setFixedSize(self.SIDE + self.STEP * (count - 1), self.SIDE + 2)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(
            max(0.0, min(1.0, float(self.fade))) * (1.0 if self.isEnabled() else 0.5)
        )
        for index, pixmap in enumerate(self._pixmaps):
            box = QRectF(index * self.STEP, 1, self.SIDE, self.SIDE)
            draw_fitted(painter, box, pixmap, self.devicePixelRatioF())


class _AssetRow(_ItemsLayout):
    """Name and state, the boxes, the switch, and (optional, fourth) the
    pictures shown while the switch is off.  One line when there is room;
    otherwise the boxes go under the name.  ``reveal`` (0..1) is how much of
    the boxes shows: they slide shut when the switch goes off.  The pictures
    sit just left of the switch and take room from the name only while they
    show (``reveal`` below 1)."""

    def __init__(self, parent=None, gap: int = 10):
        super().__init__(parent)
        self._gap = gap
        self.reveal = 1.0

    def minimumSize(self) -> QSize:
        if len(self._items) < 3:
            return QSize(0, 0)
        margins = self.contentsMargins()
        _head, controls, toggle = self._items[:3]
        width = max(controls.minimumSize().width(), 90 + self._gap + toggle.sizeHint().width())
        return QSize(width + margins.left() + margins.right(), 0)

    def sizeHint(self) -> QSize:
        width = self.minimumSize().width()
        return QSize(width, self.heightForWidth(width))

    def one_line(self, width: int) -> bool:
        head, controls, toggle = self._items[:3]
        need = (
            head.sizeHint().width()
            + controls.sizeHint().width()
            + toggle.sizeHint().width()
            + 2 * self._gap
        )
        return width >= need

    def _layout(self, rect: QRect, test_only: bool) -> int:
        if len(self._items) < 3:
            return 0
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        head, controls, toggle = self._items[:3]
        switch = toggle.sizeHint()
        reveal = max(0.0, min(1.0, float(self.reveal)))
        pile = self._items[3] if len(self._items) > 3 else None
        pile_size = pile.sizeHint() if pile is not None else QSize(0, 0)
        # Room the pictures take beside the switch (none once the boxes are open).
        beside = pile_size.width() + self._gap if pile is not None and reveal < 1.0 else 0

        def place_pile(row_height: int) -> None:
            if pile is not None:
                pile.setGeometry(
                    QRect(
                        area.right() + 1 - switch.width() - self._gap - pile_size.width(),
                        area.y() + (row_height - pile_size.height()) // 2,
                        pile_size.width(),
                        pile_size.height(),
                    )
                )

        head_height = head.sizeHint().height()
        boxes = controls.sizeHint()
        extra = margins.top() + margins.bottom()
        if self.one_line(area.width()):
            height = max(head_height, boxes.height(), switch.height())
            if not test_only:
                switch_x = area.right() + 1 - switch.width()
                boxes_x = switch_x - self._gap - boxes.width()
                toggle.setGeometry(
                    QRect(
                        switch_x,
                        area.y() + (height - switch.height()) // 2,
                        switch.width(),
                        switch.height(),
                    )
                )
                controls.setGeometry(
                    QRect(
                        boxes_x,
                        area.y() + (height - boxes.height()) // 2,
                        boxes.width(),
                        boxes.height(),
                    )
                )
                # Closed, the pictures stand where the boxes will open (hidden
                # boxes have no width, so the name must stop before them).
                head.setGeometry(
                    QRect(
                        area.x(),
                        area.y() + (height - head_height) // 2,
                        min(boxes_x, switch_x - beside) - self._gap - area.x(),
                        head_height,
                    )
                )
                place_pile(height)
            return height + extra
        top = max(head_height, switch.height())
        shown = round((boxes.height() + self._gap) * reveal)
        if not test_only:
            toggle.setGeometry(
                QRect(
                    area.right() + 1 - switch.width(),
                    area.y() + (top - switch.height()) // 2,
                    switch.width(),
                    switch.height(),
                )
            )
            head.setGeometry(
                QRect(
                    area.x(),
                    area.y() + (top - head_height) // 2,
                    area.width() - switch.width() - self._gap - beside,
                    head_height,
                )
            )
            place_pile(top)
            controls.setGeometry(
                QRect(area.x(), area.y() + top + self._gap, area.width(), max(0, shown - self._gap))
            )
        return top + shown + extra


class AssetBlock(Inset):
    """One asset the 卖 step may sell: its name, a line saying what will
    happen, the keep boxes, and its own switch."""

    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        controls: QWidget,
        hint: str = "",
        parent=None,
        pictures: list[str | None] | None = None,
    ):
        super().__init__(parent)
        self._row = _AssetRow(self)
        self._row.setContentsMargins(12, 9, 10, 9)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        head = QWidget(self)
        texts = vbox(head, (0, 0, 0, 0), 1)
        name = hbox(None, (0, 0, 0, 0), 5)
        name.addWidget(Text(title, "h3"))
        if hint:
            # Leo 2026-11-10: the ⓘ beside 招募书 says the tool does the sums.
            info = IconLabel("info", 14, "ink3")
            attach_hint(info, t(hint))
            info.setCursor(Qt.WhatsThisCursor)
            name.addWidget(info)
            self.info = info
        name.addStretch(1)
        texts.addLayout(name)
        self.state = Text("", "muted", elide=True)
        texts.addWidget(self.state)
        self.controls = controls
        controls.setParent(self)
        self.toggle = Toggle(False, small=True)
        self.toggle.toggled.connect(self._switched)
        self._row.addWidget(head)
        self._row.addWidget(controls)
        self._row.addWidget(self.toggle)
        # What the row sells, shown while its switch is off.
        self.pile = ContractPile(pictures, self) if pictures and any(pictures) else None
        if self.pile is not None:
            self._row.addWidget(self.pile)
        self._open = motion.Tween(self, self._opened, 240, 0.0)
        self._opened()

    def is_on(self) -> bool:
        return self.toggle.isChecked()

    def set_on(self, on: bool) -> None:
        """The saved switch (no animation: nothing was pressed)."""
        if self.toggle.isChecked() != on:
            self.toggle.set_checked_quietly(on)
        if self._open.target != (1.0 if on else 0.0):
            self._open.go(1.0 if on else 0.0, animate=False)

    def set_state(self, text: str, alarm: bool = False) -> None:
        """The line under the name; ``alarm`` writes it in rose."""
        set_prop(self.state, "tone", "bad" if alarm else "")
        self.state.set_text(text)

    def _switched(self, on: bool) -> None:
        self._open.go(1.0 if on else 0.0)
        self.toggled.emit(bool(on))

    def _opened(self) -> None:
        value = max(0.0, min(1.0, float(self._open.value)))
        self._row.reveal = value
        settled = value in (0.0, 1.0)
        self.controls.setVisible(value > 0.0)
        if self.pile is not None:
            self.pile.fade = 1.0 - value
            self.pile.setVisible(value < 1.0)
            self.pile.update()
        if settled:
            # No effect at rest: the boxes draw exactly as they are.
            self.controls.setGraphicsEffect(None)
        else:
            effect = self.controls.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(self.controls)
                self.controls.setGraphicsEffect(effect)
            effect.setOpacity(value)
        self._row.invalidate()
        self.updateGeometry()
