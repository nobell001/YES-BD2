"""排轴: a saved fight drawn like a souseha formation page (Leo 2026-10-06).

Top: each team's members.  Then the turn numbers; under them the picked
turn: the 1-N order on the left (portrait, card, 爆发) and the 3x4 grid on
the right with each unit's portrait and order number, the boss side right.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from functools import lru_cache

import cv2
import numpy as np
from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    QSizeF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QAbstractButton, QGraphicsDropShadowEffect, QLabel, QWidget

from src.tasks.fiend_hunt.chart import ChartTurn, ChartUnit, team_members, timelines
from src.tasks.fiend_hunt.planner import COLS, ROWS
from src.tasks.fiend_hunt.record import FightRecord, TurnState
from src.ui.shell import icons, theme
from src.ui.shell.widgets import (
    Button,
    Inset,
    Segmented,
    Text,
    clear_layout,
    grid_container,
    hbox,
    t,
    tf,
    vbox,
)

CELL = 74
GAP = 6


def to_pixmap(image: np.ndarray | None) -> QPixmap:
    if image is None or image.size == 0:
        return QPixmap()
    if image.ndim == 3 and image.shape[2] == 4:  # a list portrait, see-through around
        rgba = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA))
        height, width = rgba.shape[:2]
        return QPixmap.fromImage(
            QImage(rgba.data, width, height, width * 4, QImage.Format_RGBA8888).copy()
        )
    rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    height, width = rgb.shape[:2]
    return QPixmap.fromImage(
        QImage(rgb.data, width, height, width * 3, QImage.Format_RGB888).copy()
    )


def action_text(unit: ChartUnit) -> str:
    if unit.dead:
        return t("阵亡")
    if not unit.action:
        return "?"
    text = t(unit.action)
    costume = costume_of(unit.costume) if unit.action.startswith("技能") else None
    if costume is not None:
        text = t("技能") + f" · {costume.skill or costume.name}"
    return text  # the 爆发 level is drawn as the card's flame badge (paint_burst)


def _face(
    painter: QPainter,
    rect: QRectF,
    pixmap: QPixmap,
    radius: float,
    dim: bool,
    back: QColor | None = None,
) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(path)
    painter.fillRect(rect, back if back is not None else theme.color("ink", 0.08))
    if not pixmap.isNull():
        # Scaled for the screen's own pixels: at 200 % a 48 px face is 96 px
        # (Leo 2026-10-06: blurry on the 4K PC otherwise).
        device = painter.device()
        ratio = device.devicePixelRatioF() if device is not None else 1.0
        scaled = smooth(pixmap, (rect.size() * ratio).toSize(), ratio)
        offset = (QSizeF(scaled.size()) / ratio - rect.size()) / 2
        painter.drawPixmap(
            QPointF(rect.left() - offset.width(), rect.top() - offset.height()), scaled
        )
    if dim:
        painter.fillRect(rect, QColor(0, 0, 0, 150))
    painter.restore()


def _badge(painter: QPainter, x: float, y: float, text: str) -> None:
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color("primary"))
    painter.drawEllipse(QRectF(x, y, 18, 18))
    font = QFont(painter.font())
    font.setPixelSize(11)
    theme.strong(font, digits=True)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(QRectF(x, y, 18, 18), Qt.AlignCenter, text)
    painter.restore()


DRAG_START = 6  # px the mouse moves before a press becomes a drag
SLIDE_MS = 150  # rows sliding aside for a dragged one, and its drop
CARD_CHOICES = ("攻击", "击退", "技能1", "技能2", "技能3", "技能4")
BURST_CHOICES = (0, 1, 2, 3)
NAME_WIDTH = 190


def costume_pixmap(costume_id: str | None) -> QPixmap:
    """A costume's portrait from the built-in list (costumes.py); empty when unknown.

    One pixmap per costume, so its scaled copies (smooth) are found again."""
    if not costume_id:
        return QPixmap()
    return _costume_pixmap(costume_id)


@lru_cache(maxsize=256)  # the list has under 200 costumes and summons
def _costume_pixmap(costume_id: str) -> QPixmap:
    from src.tasks.fiend_hunt import costumes

    return to_pixmap(costumes.picture_alpha(costume_id))


SCALED_KEPT = 256  # about 100 KB each at 200 %
_scaled: OrderedDict[tuple[int, int, int], QPixmap] = OrderedDict()


def smooth(pixmap: QPixmap, size: QSize, ratio: float) -> QPixmap:
    """``pixmap`` scaled to cover ``size`` device pixels, kept for the next paint.

    Smooth scaling a portrait on every paint made the team editor lag
    (Leo 2026-10-06): scrolling repaints every tile."""
    key = (pixmap.cacheKey(), size.width(), size.height())
    scaled = _scaled.get(key)
    if scaled is None:
        scaled = pixmap.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        _scaled[key] = scaled
        while len(_scaled) > SCALED_KEPT:
            _scaled.popitem(last=False)
    else:
        _scaled.move_to_end(key)
    scaled.setDevicePixelRatio(ratio)
    return scaled


def wardrobe_of(name: str) -> tuple:
    """A character's costumes in the built-in list (none for a summon)."""
    from src.tasks.fiend_hunt import costumes

    return costumes.book().costumes(name)


def costume_of(costume_id: str | None):
    if not costume_id:
        return None
    from src.tasks.fiend_hunt import costumes

    return costumes.book().costume(costume_id)


class OrderRow(QAbstractButton):
    """One line of the 1-N order: number, portrait, card.

    One picture only, the unit's on the left (Leo 2026-10-06: not a second
    one on the right); the card is named in the text under the name.

    With ``on_click`` (Leo 2026-10-06: the chart can be adjusted) a click
    opens the unit's editor under the row (UnitEditor).  With ``on_drag`` a
    row is dragged up or down the order (Leo 2026-10-06: drag, no arrows):
    ``on_drag(name, press_y, y, done)`` with both y in global coordinates;
    the chart moves the row with the mouse and slides the others aside.
    """

    def __init__(
        self,
        unit: ChartUnit,
        show_card: bool = True,
        parent=None,
        *,
        on_click: Callable[[str], None] | None = None,
        on_drag: Callable[[str, float, bool], None] | None = None,
        edited: bool = False,
        open_: bool = False,
    ):
        super().__init__(parent)
        self.unit = unit
        self.show_card = show_card or unit.dead
        self.edited = edited
        self.open = open_
        self._on_drag = on_drag if not unit.dead else None
        self._press_y: float | None = None
        self._dragging = False
        self._pixmap = to_pixmap(unit.portrait)
        self.setFixedHeight(56)
        self.setMinimumWidth(230)
        if on_click is not None and not unit.dead:
            self.setCursor(Qt.PointingHandCursor)
            self.clicked.connect(lambda: on_click(unit.name))
        if self._on_drag is not None:
            self.setToolTip(t("拖动改顺序"))

    def mousePressEvent(self, event):
        self._press_y = event.globalPosition().y()
        self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        y = event.globalPosition().y()
        if self._on_drag is not None and self._press_y is not None:
            if not self._dragging and abs(y - self._press_y) >= DRAG_START:
                self._dragging = True
                self.setDown(False)
                self.setCursor(Qt.ClosedHandCursor)
                self._lift(True)
            if self._dragging:
                self._on_drag(self.unit.name, self._press_y, y, False)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        press_y, self._press_y = self._press_y, None
        if self._dragging:
            self._dragging = False
            self.setDown(False)
            self.setCursor(Qt.PointingHandCursor)
            self._lift(False)
            self._on_drag(self.unit.name, press_y, event.globalPosition().y(), True)
            return  # a drag is not a click
        super().mouseReleaseEvent(event)

    def _lift(self, on: bool) -> None:
        """A dragged row is held above the others, with a soft shadow."""
        if on:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(18)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 70))
            self.setGraphicsEffect(shadow)
            self.raise_()
        else:
            self.setGraphicsEffect(None)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        skill = self.show_card and self.unit.action.startswith("技能")
        painter.setPen(
            QPen(theme.color("primary"), 1.4) if self.open or self._dragging else Qt.NoPen
        )
        if self._dragging:  # opaque: the rows it passes over don't show through
            painter.setBrush(theme.color("card"))
            painter.drawRoundedRect(box, 6, 6)
        painter.setBrush(theme.color("primary", 0.16) if skill else theme.color("ink", 0.05))
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(Qt.NoPen)
        if self.edited:
            painter.setBrush(theme.color("primary"))
            painter.drawRoundedRect(QRectF(0, 8, 3, box.height() - 16), 1.5, 1.5)
        number = "" if self.unit.slot is None else str(self.unit.slot + 1)
        painter.setPen(theme.color("ink2"))
        painter.drawText(QRectF(8, 0, 16, box.height()), Qt.AlignCenter, number)
        _face(painter, QRectF(30, 4, 48, 48), self._pixmap, 5, self.unit.dead)
        font = QFont(painter.font())
        font.setPixelSize(13)
        theme.strong(font)
        painter.setFont(font)
        painter.setPen(theme.color("ink"))
        right = 12.0
        if self.edited:
            small = QFont(font)
            small.setBold(False)
            small.setPixelSize(11)
            painter.setFont(small)
            painter.setPen(theme.color("ink3"))
            painter.drawText(
                QRectF(0, 0, box.width() - right, box.height()),
                Qt.AlignRight | Qt.AlignVCenter,
                t("已改"),
            )
            painter.setFont(font)
            painter.setPen(theme.color("ink"))
        width = max(40.0, box.width() - 92 - right - 40)
        if not self.show_card:
            # 只看召唤物: the costume order picks the cards; only order and cells count.
            painter.drawText(
                QRectF(88, 0, width, box.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                t(self.unit.name),
            )
            return
        painter.drawText(
            QRectF(88, 8, width, 20), Qt.AlignLeft | Qt.AlignVCenter, t(self.unit.name)
        )
        font.setBold(False)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(theme.color("primary") if skill else theme.color("ink3"))
        burst = self.unit.burst if skill else 0
        text = action_text(self.unit)
        if burst:
            # Leo 2026-10-06: the 爆发 as the cards show it, not 「爆发 L3」.
            text = painter.fontMetrics().elidedText(text, Qt.ElideRight, round(width) - 36)
        painter.drawText(QRectF(88, 28, width, 20), Qt.AlignLeft | Qt.AlignVCenter, text)
        if burst:
            left = 88 + painter.fontMetrics().horizontalAdvance(text) + 8
            paint_burst(painter, QRectF(left, 30, 27, 16), burst)


def paint_burst(painter: QPainter, badge: QRectF, level: int) -> None:
    """The 爆发 level as souseha and the game show it: a teal pill, a flame, the level."""
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(38, 166, 154))
    painter.drawRoundedRect(badge, 8, 8)
    flame = icons.pixmap("flame", QColor("white"), 11, 2.4)
    flame_ratio = flame.devicePixelRatio() or 1
    painter.drawPixmap(
        round(badge.left() + 4),
        round(badge.center().y() - flame.height() / flame_ratio / 2),
        flame,
    )
    font = QFont(painter.font())
    font.setPixelSize(10)
    theme.strong(font, digits=True)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(badge.adjusted(13, 0, -2, 0), Qt.AlignCenter, str(level))
    painter.restore()


CARD_BACK = QColor(24, 25, 34)  # souseha's / the game's dark tile, in both themes
CARD_INK = QColor(245, 245, 245)


def paint_card(
    painter: QPainter,
    rect: QRectF,
    kind: str,
    pixmap: QPixmap,
    *,
    chosen: bool = False,
    hover: bool = False,
    focus: float | None = None,
    burst: int = 0,
) -> None:
    """A turn's card as souseha draws it, which matches the game (Leo
    2026-10-06): a skill is its costume's portrait, square; 攻击 and 击退 a
    dark tile with a white mark; the 爆发 level in a pill top right.
    ``focus`` crops a face cut from a screenshot below its buff icons."""
    radius = 6.0
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(path)
    painter.fillRect(rect, CARD_BACK)
    if kind == "skill" and not pixmap.isNull():
        device = painter.device()
        ratio = device.devicePixelRatioF() if device is not None else 1.0
        zoom = 1.0 if focus is None else 1.45  # past the screenshot's buff icons
        scaled = smooth(pixmap, (rect.size() * ratio * zoom).toSize(), ratio)
        width, height = scaled.width() / ratio, scaled.height() / ratio
        top = rect.top() - (height - rect.height()) * (0.5 if focus is None else focus)
        painter.drawPixmap(QPointF(rect.left() - (width - rect.width()) / 2, top), scaled)
    elif kind in ("攻击", "击退"):
        side = round(min(rect.width(), rect.height()) * 0.56)
        mark = icons.pixmap("sword" if kind == "攻击" else "arrow-left", CARD_INK, side, 2.6)
        mark_ratio = mark.devicePixelRatio() or 1
        painter.drawPixmap(
            round(rect.center().x() - mark.width() / mark_ratio / 2),
            round(rect.center().y() - mark.height() / mark_ratio / 2),
            mark,
        )
    else:  # a card known only by its row (a summon, a character the list lacks),
        # or a costume only the official notice has so far: its name (Leo 2026-10-07)
        painter.setPen(CARD_INK)
        painter.drawText(rect.adjusted(4, 4, -4, -4), Qt.AlignCenter | Qt.TextWordWrap, t(kind))
    painter.restore()
    if burst:
        paint_burst(painter, QRectF(rect.right() - 30, rect.top() + 3, 27, 16), burst)
    painter.setBrush(Qt.NoBrush)
    if chosen:
        painter.setPen(QPen(theme.color("primary"), 2.6))
        painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)
        badge = QRectF(rect.left() + 4, rect.top() + 4, 16, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("primary"))
        painter.drawEllipse(badge)
        tick = icons.pixmap("check", QColor("white"), 12, 3)
        tick_ratio = tick.devicePixelRatio() or 1
        painter.drawPixmap(
            round(badge.center().x() - tick.width() / tick_ratio / 2),
            round(badge.center().y() - tick.height() / tick_ratio / 2),
            tick,
        )
    elif hover:
        painter.setPen(QPen(theme.color("primary", 0.6), 1.6))
        painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)


UNREAD_INK = QColor(232, 160, 60)  # amber: a skill whose card wasn't read


def paint_unread(painter: QPainter, rect: QRectF, burst: int) -> None:
    """A skill whose costume isn't known (Leo 2026-10-07: a default face read
    as the wrong costume): a dark tile with a question mark, dashed amber."""
    radius = 6.0
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(CARD_BACK)
    painter.drawRoundedRect(rect, radius, radius)
    pen = QPen(UNREAD_INK, 1.6, Qt.DashLine)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)
    font = QFont(painter.font())
    font.setPixelSize(round(rect.height() * 0.42))
    theme.strong(font, digits=True)
    painter.setFont(font)
    painter.setPen(UNREAD_INK)
    painter.drawText(rect, Qt.AlignCenter, "?")
    painter.restore()
    if burst:
        paint_burst(painter, QRectF(rect.right() - 30, rect.top() + 3, 27, 16), burst)


def paint_caption(painter: QPainter, rect: QRectF, text: str, colour: QColor) -> None:
    font = QFont(painter.font())
    font.setPixelSize(11)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(colour)
    painter.drawText(
        rect,
        Qt.AlignCenter,
        painter.fontMetrics().elidedText(text, Qt.ElideRight, round(rect.width())),
    )


class CardChip(QAbstractButton):
    """One choice in the unit editor, as souseha draws a turn's card: a
    costume's portrait with its name under it, or 攻击 / 击退 / 技能n."""

    SIZE = 88

    def __init__(
        self,
        text: str,
        pixmap: QPixmap | None,
        chosen: bool,
        tip: str,
        parent=None,
        *,
        title: str = "",
    ):
        super().__init__(parent)
        self._text = text
        self._pixmap = pixmap or QPixmap()
        self._title = title or t(text)
        self.chosen = chosen
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setFixedSize(self.SIZE + 4, self.SIZE + 22)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        kind = "skill" if not self._pixmap.isNull() else self._text
        rect = QRectF(2, 2, self.SIZE, self.SIZE)
        paint_card(painter, rect, kind, self._pixmap, chosen=self.chosen, hover=self._hover)
        paint_caption(
            painter,
            QRectF(-2, self.SIZE + 4, self.SIZE + 8, 16),
            self._title,
            theme.color("primary") if self.chosen else theme.color("ink2"),
        )


class OrderList(QWidget):
    """The order's rows (and an open editor), placed by hand rather than by a
    layout, so a dragged row stays where the mouse holds it.

    A row follows the mouse; the others slide aside to make room (Leo
    2026-10-06: the first drag felt like Excel).  On release it slides into
    its place and ``on_drop(name, index)`` gets the new place among the
    living units.
    """

    SPACING = 6

    def __init__(self, on_drop: Callable[[str, int], None], parent=None):
        super().__init__(parent)
        self._on_drop = on_drop
        self._items: list[QWidget] = []
        self._slides: dict[QWidget, QPropertyAnimation] = {}
        self._drag: dict | None = None
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def add(self, widget: QWidget, *, editor: bool = False) -> None:
        widget.setParent(self)
        widget.setProperty("orderEditor", editor)
        self._items.append(widget)
        widget.show()
        self.updateGeometry()

    def rows(self) -> list[OrderRow]:
        return [w for w in self._items if isinstance(w, OrderRow) and not w.unit.dead]

    # ------------------------------------------------------------ geometry

    def _height_of(self, widget: QWidget, width: int) -> int:
        if widget.hasHeightForWidth():
            return widget.heightForWidth(width)
        if widget.layout() is not None and widget.layout().hasHeightForWidth():
            return widget.layout().totalHeightForWidth(width)
        return max(widget.sizeHint().height(), widget.minimumHeight())

    def _tops(self, items: list[QWidget], width: int) -> tuple[dict[QWidget, int], int]:
        tops, y = {}, 0
        for widget in items:
            if widget.isHidden():
                continue
            tops[widget] = y
            y += self._height_of(widget, width) + self.SPACING
        return tops, max(0, y - self.SPACING)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._tops(self._items, width)[1]

    def sizeHint(self) -> QSize:
        width = max([230] + [w.sizeHint().width() for w in self._items if not w.isHidden()])
        return QSize(width, self.heightForWidth(max(self.width(), width)))

    def minimumSizeHint(self) -> QSize:
        return QSize(230, self.heightForWidth(max(self.width(), 230)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        width = self.width()
        tops, _height = self._tops(self._order(), width)
        held = self._drag["row"] if self._drag else None
        for widget, top in tops.items():
            height = self._height_of(widget, width)
            if widget is held:
                widget.setGeometry(0, widget.y(), width, height)
            elif widget in self._slides:
                widget.resize(width, height)
            else:
                widget.setGeometry(0, top, width, height)

    def _order(self) -> list[QWidget]:
        """The items as they stand, the dragged row at its target."""
        if self._drag is None:
            return self._items
        living = [row for row in self._drag["rows"] if row is not self._drag["row"]]
        living.insert(self._drag["to"], self._drag["row"])
        moved = iter(living)
        return [next(moved) if w in self._drag["rows"] else w for w in self._items]

    # ------------------------------------------------------------ dragging

    def drag(self, name: str, press_y: float, y: float, done: bool) -> None:
        state = self._drag
        if state is None:
            editor = next((w for w in self._items if w.property("orderEditor")), None)
            if editor is not None:  # rows keep one height while dragged
                editor.hide()
                self.updateGeometry()
            rows = self.rows()
            row = next(r for r in rows if r.unit.name == name)
            self._drag = state = {"rows": rows, "row": row, "from": rows.index(row), "to": 0}
            state["to"] = state["from"]
            self._place()
            state["start"] = row.y()
            row.raise_()
        row = state["row"]
        tops, _height = self._tops(self._order(), self.width())
        slots = sorted(tops[r] for r in state["rows"])
        top = min(max(state["start"] + round(y - press_y), slots[0]), slots[-1])
        target = min(range(len(slots)), key=lambda k: abs(slots[k] - top))
        if target != state["to"]:
            state["to"] = target
            tops, _height = self._tops(self._order(), self.width())
            for other in state["rows"]:
                if other is not row:
                    self._slide(other, tops[other])
        if not done:
            self._stop_slide(row)
            row.move(0, top)
            return
        start = state["from"]
        self._drag = None
        self._items = [w for w in self._order_after(state)]
        if target == start:
            self._slide(row, tops[row])
        else:
            self._slide(row, tops[row], lambda: self._on_drop(name, target))

    def _order_after(self, state: dict) -> list[QWidget]:
        self._drag = state
        try:
            return list(self._order())
        finally:
            self._drag = None

    def _slide(self, widget: QWidget, y: int, then: Callable[[], None] | None = None) -> None:
        self._stop_slide(widget)
        if widget.y() == y:
            if then is not None:
                then()
            return
        slide = QPropertyAnimation(widget, b"pos", self)
        slide.setDuration(SLIDE_MS)
        slide.setEasingCurve(QEasingCurve.OutCubic)
        slide.setEndValue(QPoint(0, y))
        slide.finished.connect(lambda: self._slides.pop(widget, None))
        if then is not None:
            slide.finished.connect(then)
        self._slides[widget] = slide
        slide.start()

    def _stop_slide(self, widget: QWidget) -> None:
        slide = self._slides.pop(widget, None)
        if slide is not None:
            slide.stop()


class UnitEditor(Inset):
    """Under an opened order row: pick the unit's card by its costume's
    picture (Leo 2026-10-06, like the game's card column) and its 爆发
    (the order is changed by dragging the rows).  ``on_edit(name, what,
    value)`` with what = card (攻击/击退/技能n) / costume (id) / burst (0-3).
    """

    def __init__(
        self,
        unit: ChartUnit,
        on_edit: Callable[[str, str, object], None],
        parent=None,
    ):
        super().__init__(parent)
        from src.tasks.fiend_hunt import costumes

        name = unit.name
        column = vbox(self, (14, 12, 14, 12), 10)
        container, row = grid_container(CardChip.SIZE + 4, spacing=8)
        column.addWidget(container)
        summon = costumes.book().summons.get(name)
        if summon is not None:
            # Leo 2026-10-06: a summon has only its attack and one skill, no 爆发.
            chip = CardChip("攻击", None, unit.action == "攻击", t("攻击"))
            chip.clicked.connect(lambda: on_edit(name, "card", "攻击"))
            row.addWidget(chip)
            skill = unit.action.startswith("技能")
            chip = CardChip("技能1", costume_pixmap(summon), skill, t("技能"), title=t("技能"))
            chip.clicked.connect(lambda: on_edit(name, "card", "技能1"))
            row.addWidget(chip)
            return
        for card in ("攻击", "击退"):
            chip = CardChip(card, None, unit.action == card, t(card))
            chip.clicked.connect(lambda _=False, card=card: on_edit(name, "card", card))
            row.addWidget(chip)
        wardrobe = costumes.book().costumes(name)
        if wardrobe:
            for costume in wardrobe:
                chosen = unit.action.startswith("技能") and unit.costume == costume.id
                tip = costume.name + (f"\n{costume.skill}" if costume.skill else "")
                chip = CardChip(
                    costume.name,
                    costume_pixmap(costume.id),
                    chosen,
                    tip,
                    title=costume.name,
                )
                chip.clicked.connect(
                    lambda _=False, costume=costume.id: on_edit(name, "costume", costume)
                )
                row.addWidget(chip)
        else:
            # A summon or a character newer than the list: cards by their row.
            for card in CARD_CHOICES[2:]:
                chip = CardChip(card, None, unit.action == card, t(card))
                chip.clicked.connect(lambda _=False, card=card: on_edit(name, "card", card))
                row.addWidget(chip)
        side = hbox(None, (0, 0, 0, 0), 10)
        flame = QLabel()  # 爆发, as the cards mark it (Leo 2026-10-06: icons, not words)
        flame.setPixmap(icons.pixmap("flame", QColor(38, 166, 154), 18, 2.2))
        flame.setToolTip(t("爆发"))
        side.addWidget(flame)
        labels = {str(level): (t("关") if level == 0 else str(level)) for level in BURST_CHOICES}
        burst = Segmented(
            list(labels), str(unit.burst if unit.burst in BURST_CHOICES else 0), labels=labels
        )
        burst.setEnabled(unit.action.startswith("技能"))
        burst.changed.connect(lambda value: on_edit(name, "burst", int(value)))
        side.addWidget(burst)
        side.addStretch(1)
        column.addLayout(side)


class Grid(QWidget):
    """The 3x4 grid of the player's side; the boss is to the right.

    With ``on_move`` a living unit can be dragged to another cell (Leo
    2026-10-06); ``on_move(name, (row, col))``.
    """

    def __init__(
        self,
        chart: ChartTurn,
        parent=None,
        *,
        on_move: Callable[[str, tuple[int, int]], None] | None = None,
    ):
        super().__init__(parent)
        self._cells = chart.by_cell()
        self._pixmaps = {cell: to_pixmap(unit.portrait) for cell, unit in self._cells.items()}
        self._on_move = on_move
        self._from: tuple[int, int] | None = None  # the cell a drag started on
        self._at: QPointF | None = None  # where the dragged face is drawn
        self.setFixedSize(COLS * CELL + (COLS - 1) * GAP + 18, ROWS * CELL + (ROWS - 1) * GAP)
        if on_move is not None:
            self.setMouseTracking(True)
            self.setToolTip(t("拖动头像换格子"))

    def cell_at(self, point) -> tuple[int, int] | None:
        col, row = int(point.x() // (CELL + GAP)), int(point.y() // (CELL + GAP))
        if 0 <= row < ROWS and 0 <= col < COLS:
            return row, col
        return None

    def _movable(self, cell) -> bool:
        unit = self._cells.get(cell) if cell is not None else None
        return unit is not None and not unit.dead

    def mousePressEvent(self, event):
        cell = self.cell_at(event.position())
        if self._on_move is not None and self._movable(cell):
            self._from = cell
            self._at = None
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._from is not None:
            self._at = event.position()
            self.update()
        elif self._on_move is not None:
            movable = self._movable(self.cell_at(event.position()))
            self.setCursor(Qt.OpenHandCursor if movable else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        start, self._from, self._at = self._from, None, None
        self.unsetCursor()
        self.update()
        if start is not None:
            target = self.cell_at(event.position())
            if target is not None and target != start:
                self._on_move(self._cells[start].name, target)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for row in range(ROWS):
            for col in range(COLS):
                rect = QRectF(col * (CELL + GAP), row * (CELL + GAP), CELL, CELL)
                unit = self._cells.get((row, col))
                if unit is None:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(theme.color("ink", 0.05))
                    painter.drawRoundedRect(rect, 6, 6)
                    continue
                if (row, col) == self._from and self._at is not None:
                    painter.setOpacity(0.35)
                _face(painter, rect, self._pixmaps[(row, col)], 6, unit.dead)
                painter.setOpacity(1.0)
                if unit.slot is not None:
                    _badge(painter, rect.right() - 21, rect.bottom() - 21, str(unit.slot + 1))
                elif unit.dead:
                    painter.setPen(QColor("white"))
                    painter.drawText(rect, Qt.AlignCenter, t("阵亡"))
        if self._from is not None and self._at is not None:
            target = self.cell_at(self._at)
            if target is not None:
                row, col = target
                drop = QRectF(col * (CELL + GAP), row * (CELL + GAP), CELL, CELL)
                painter.setPen(QPen(theme.color("primary"), 2.4))
                painter.setBrush(theme.color("primary", 0.12))
                painter.drawRoundedRect(drop.adjusted(1, 1, -1, -1), 6, 6)
            face = QRectF(
                self._at.x() - CELL * 0.4, self._at.y() - CELL * 0.4, CELL * 0.8, CELL * 0.8
            )
            _face(painter, face, self._pixmaps[self._from], 6, False)
        # The arrow towards the boss.
        x = COLS * (CELL + GAP) - GAP + 4
        middle = self.height() / 2
        path = QPainterPath()
        path.moveTo(x, middle - 16)
        path.lineTo(x + 12, middle)
        path.lineTo(x, middle + 16)
        painter.setPen(QPen(theme.color("primary"), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


class TurnChip(QAbstractButton):
    def __init__(self, turn: int, on_click: Callable[[int], None], parent=None):
        super().__init__(parent)
        self.turn = turn
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(34, 28)
        self.clicked.connect(lambda: on_click(turn))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("primary") if on else theme.color("ink", 0.06))
        painter.drawRoundedRect(QRectF(self.rect()), 6, 6)
        painter.setPen(QColor("white") if on else theme.color("ink2"))
        painter.drawText(QRectF(self.rect()), Qt.AlignCenter, str(self.turn))


class TeamStrip(QWidget):
    """A team's portraits in a row, like souseha's header."""

    SIZE = 34

    def __init__(self, faces: list[QPixmap], parent=None):
        super().__init__(parent)
        self._faces = faces
        self.setFixedSize(len(faces) * (self.SIZE - 6) + 6 + 8, self.SIZE + 8)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("ink", 0.06))
        painter.drawRoundedRect(QRectF(self.rect()), self.height() / 2, self.height() / 2)
        for index, face in enumerate(self._faces):
            rect = QRectF(4 + index * (self.SIZE - 6), 4, self.SIZE, self.SIZE)
            _face(painter, rect, face, self.SIZE / 2, False)
            painter.setPen(QPen(theme.color("card"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect)
            painter.setPen(Qt.NoPen)


class ActionCell(QWidget):
    """One turn of one unit, as souseha draws it (Leo 2026-10-06: like the
    game): the skill's costume portrait with its 爆发 and the costume's name,
    or 攻击 / 击退.  With ``on_pick`` a click opens a small window to change
    it (Leo 2026-10-06: not only in the order at the top)."""

    SIZE = 88

    def __init__(
        self,
        turn: int,
        unit: ChartUnit | None,
        show_card: bool,
        parent=None,
        *,
        on_pick: Callable[[int, ChartUnit, QWidget], None] | None = None,
    ):
        super().__init__(parent)
        self.turn = turn
        self.unit = unit
        self.show_card = show_card
        self._pixmap = QPixmap()
        self._face = QPixmap()
        self._hover = False
        if unit is not None:
            self._pixmap = costume_pixmap(unit.costume) if unit.costume else QPixmap()
            self._face = to_pixmap(unit.portrait)
        # a costume only the official notice has so far (no portrait yet)
        worn = costume_of(unit.costume) if unit is not None else None
        self._new = worn if worn is not None and worn.temporary else None
        # a character whose costumes the list knows, but not which one this skill was
        self._unread = unit is not None and not unit.costume and bool(wardrobe_of(unit.name))
        self._on_pick = on_pick if unit is not None and not unit.dead and show_card else None
        if self._on_pick is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(t("点一下改攻击、技能或爆发"))
        self.setFixedSize(self.SIZE, self.SIZE + 20)

    def enterEvent(self, event):
        if self._on_pick is not None:
            self._hover = True
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hover:
            self._hover = False
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            self._on_pick is not None
            and event.button() == Qt.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self._on_pick(self.turn, self.unit, self)
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(0.5, 0.5, self.SIZE - 1, self.SIZE - 1)
        unit = self.unit
        skill = unit is not None and self.show_card and unit.action.startswith("技能")
        burst = unit.burst if skill else 0
        if unit is None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("ink", 0.04))
            painter.drawRoundedRect(rect, 6, 6)
        elif unit.dead or not self.show_card:
            _face(painter, rect, self._face, 6, unit.dead)
        elif skill and not self._pixmap.isNull():
            paint_card(painter, rect, "skill", self._pixmap, burst=burst)
        elif skill and self._new is not None:  # no portrait yet: the costume's name
            paint_card(painter, rect, self._new.name, QPixmap(), burst=burst)
        elif skill and self._unread:  # the card wasn't read: a question mark to fill in
            paint_unread(painter, rect, burst)
        elif skill:  # a summon, or a character the list lacks: its picture
            focus = None if unit.listed else 0.8
            paint_card(painter, rect, "skill", self._face, focus=focus, burst=burst)
        else:
            paint_card(painter, rect, unit.action or "?", QPixmap())
        if self._hover:
            painter.setPen(QPen(theme.color("primary"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
        if unit is None:
            caption = f"T{self.turn}"
        elif unit.dead:
            caption = f"T{self.turn} {t('阵亡')}"
        elif not self.show_card:
            caption = f"T{self.turn}"
        else:
            costume = costume_of(unit.costume) if skill else None
            what = costume.name if costume else t(unit.action or "?")
            if skill and self._unread:
                what = t("待补")
            caption = f"T{self.turn} {what}"
        unread = skill and self._unread
        paint_caption(
            painter,
            QRectF(-4, self.SIZE + 3, self.SIZE + 8, 16),
            caption,
            UNREAD_INK if unread else theme.color("ink2"),
        )


class Face(QWidget):
    """A unit's portrait, rounded."""

    def __init__(self, pixmap: QPixmap, size: int, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        _face(painter, QRectF(0, 0, self.width(), self.height()), self._pixmap, 8, False)


class UnitTimeline(QWidget):
    """One row of the table: the unit, then what it did each turn of its team."""

    NAME_WIDTH = 150

    def __init__(self, name: str, line, show_card: bool, parent=None, *, on_pick=None):
        super().__init__(parent)
        row = hbox(self, (0, 0, 0, 0), 8)
        face = next(
            (
                unit.portrait
                for _turn, unit in line
                if unit is not None and unit.portrait is not None
            ),
            None,
        )
        who = QWidget()
        who.setFixedWidth(self.NAME_WIDTH)
        who_row = hbox(who, (0, 0, 0, 0), 8)
        who_row.addWidget(Face(to_pixmap(face), 36))
        label = Text(name, "body")
        label.setWordWrap(True)
        who_row.addWidget(label, 1)
        row.addWidget(who, 0, Qt.AlignVCenter)
        # the turns wrap onto a second line in a narrow window
        cells, grid = grid_container(ActionCell.SIZE, spacing=8)
        for turn, unit in line:
            grid.addWidget(ActionCell(turn, unit, show_card, on_pick=on_pick))
        row.addWidget(cells, 1)


class CardPopup(QWidget):
    """A small window by a turn's card in 每人每回合 (Leo 2026-10-06): pick
    攻击, 击退 or a costume's skill and its 爆发.  Each pick is saved at once;
    a click outside closes it."""

    WIDTH = 5 * (CardChip.SIZE + 4 + 8) + 16 * 2 + 14 * 2 + 8  # five cards a line

    def __init__(self, turn: int, unit: ChartUnit, on_edit, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.turn = turn
        self.unit = unit
        self._on_edit = on_edit
        self.setFixedWidth(self.WIDTH)
        self._column = vbox(self, (16, 14, 16, 14), 8)
        head = hbox(None, (0, 0, 0, 0), 8)
        head.addWidget(Face(to_pixmap(unit.portrait), 28))
        head.addWidget(Text(tf("第 {n} 回合 · {name}", n=turn, name=t(unit.name)), "h3"), 1)
        self._column.addLayout(head)
        self.editor: UnitEditor | None = None
        self._fill()

    def _fill(self) -> None:
        if self.editor is not None:
            self._column.removeWidget(self.editor)
            self.editor.deleteLater()
        self.editor = UnitEditor(self.unit, self._edit)
        self._column.addWidget(self.editor)
        inner = self.WIDTH - 32
        editor = self.editor.layout().totalHeightForWidth(inner)
        if editor < 0:
            editor = self.editor.sizeHint().height()
        self.setFixedHeight(14 + 28 + 8 + editor + 14)

    def _edit(self, name: str, what: str, value) -> None:
        self._on_edit(self.turn, name, what, value)
        # the unit was changed in place; show what is chosen now
        QTimer.singleShot(0, self._fill)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.color("ink", 0.14), 1))
        painter.setBrush(theme.color("card"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

    def show_by(self, anchor: QWidget) -> None:
        """Under the card, kept on its screen."""
        below = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        screen = anchor.screen().availableGeometry()
        x = min(max(below.x(), screen.left() + 8), screen.right() - self.width() - 8)
        y = below.y()
        if y + self.height() > screen.bottom() - 8:  # no room below: above it
            y = anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 6
        self.move(x, max(screen.top() + 8, y))
        self.show()


class FoldHead(QAbstractButton):
    """A team's name with a small arrow; a click folds its table away."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.folded = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(t("收起或展开这一队"))
        self.setFixedSize(96, 24)

    def set_folded(self, folded: bool) -> None:
        self.folded = folded
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colour = theme.color("primary") if self._hover else theme.color("ink3")
        arrow = icons.pixmap("chevron-right" if self.folded else "chevron-down", colour, 16, 2.2)
        ratio = arrow.devicePixelRatio() or 1
        painter.drawPixmap(0, round((self.height() - arrow.height() / ratio) / 2), arrow)
        font = QFont(painter.font())
        font.setPixelSize(12)
        theme.strong(font)
        painter.setFont(font)
        painter.setPen(colour)
        painter.drawText(
            QRectF(20, 0, self.width() - 20, self.height()), Qt.AlignVCenter, self._text
        )


class Timelines(QWidget):
    """每人每回合: per team, a table with a row per unit and a column per
    turn (souseha's character table)."""

    def __init__(
        self,
        turns: list[ChartTurn],
        show_card: Callable[[str], bool],
        parent=None,
        *,
        on_pick: Callable[[int, ChartUnit, QWidget], None] | None = None,
        folded: set[int] | None = None,
    ):
        super().__init__(parent)
        # Leo 2026-10-06: each team folds away with a small arrow; ``folded``
        # is shared with the chart so a rebuild keeps it.
        self.folded = folded if folded is not None else set()
        self.tables: dict[int, QWidget] = {}
        self.heads: dict[int, FoldHead] = {}
        column = vbox(self, (0, 0, 0, 0), 10)
        for team, units in sorted(timelines(turns).items()):
            head = hbox(None, (0, 0, 0, 0), 4)
            fold = FoldHead(f"TEAM{team}")
            head.addWidget(fold)
            head.addStretch(1)
            column.addLayout(head)
            shown = [(name, line) for name, line in units.items() if show_card(name)]
            if not shown:
                table = Text("这一队没有召唤物，技能交给游戏的服装顺序", "muted")
            else:
                table = Inset()
                rows = vbox(table, (14, 12, 14, 12), 8)
                for name, line in shown:
                    rows.addWidget(UnitTimeline(name, line, True, on_pick=on_pick))
            column.addWidget(table)
            self.tables[team] = table
            self.heads[team] = fold
            fold.clicked.connect(lambda _=False, team=team: self.toggle(team))
            self._show(team)

    def toggle(self, team: int) -> None:
        self.folded ^= {team}
        self._show(team)

    def _show(self, team: int) -> None:
        folded = team in self.folded
        self.tables[team].setHidden(folded)
        self.heads[team].set_folded(folded)


class ChartView(QWidget):
    """Team strips, turn chips and the picked turn's order and grid.

    With ``record`` and ``save`` the picked turn can be adjusted (Leo
    2026-10-06): each unit's card and 爆发, and its place in the order.
    ``save(state, changed)`` stores the turn and returns the updated record,
    or None when it wasn't saved.
    """

    def __init__(
        self,
        turns: list[ChartTurn],
        show_card: Callable[[str], bool] = lambda _name: True,
        parent=None,
        *,
        record: FightRecord | None = None,
        save: Callable[[TurnState, set[str]], FightRecord | None] | None = None,
        on_team: Callable[[int], None] | None = None,
        shown: int | None = None,
        opened: str | None = None,
        folded: set[int] | None = None,
    ):
        super().__init__(parent)
        self._show_card = show_card
        self._turns = {chart.turn: chart for chart in turns}
        self._record = record
        self._save = save
        self._shown: int | None = None
        self._open: str | None = opened  # the unit whose editor is open
        self._rows: list[OrderRow] = []  # the shown turn's living rows, in order
        self._list: OrderList | None = None
        self.popup: CardPopup | None = None  # 每人每回合's small edit window
        column = vbox(self, (0, 0, 0, 0), 12)
        self.faces: dict[str, QPixmap] = {}
        for chart in turns:
            for unit in chart.units:
                if unit.portrait is not None and unit.name not in self.faces:
                    self.faces[unit.name] = to_pixmap(unit.portrait)
        teams = hbox(None, (0, 0, 0, 0), 10)
        for team, members in sorted(team_members(turns).items()):
            teams.addWidget(Text(f"TEAM{team}", "muted"))
            teams.addWidget(TeamStrip([self.faces.get(name, QPixmap()) for name in members]))
            if on_team is not None and self.editable:
                # Leo 2026-10-06: add and remove characters after recording.
                edit = Button("编辑队伍", "ghost", "pencil", size="sm")
                edit.clicked.connect(lambda _=False, team=team: on_team(team))
                teams.addWidget(edit)
            teams.addSpacing(12)
        teams.addStretch(1)
        column.addLayout(teams)

        chips = hbox(None, (0, 0, 0, 0), 4)
        self._chips: dict[int, TurnChip] = {}
        for number in sorted(self._turns):
            chip = TurnChip(number, self.show_turn)
            chips.addWidget(chip)
            self._chips[number] = chip
        chips.addStretch(1)
        column.addLayout(chips)

        self.turn_area = hbox(None, (0, 4, 0, 0), 22)
        column.addLayout(self.turn_area)
        column.addSpacing(8)
        # Leo 2026-10-06: 不调整 (只看召唤物) hides the characters' skills and
        # 爆发; only the summons' are still picked by the tool.
        self._everyone = all(show_card(unit.name) for chart in turns for unit in chart.units)
        column.addWidget(Text("每人每回合" if self._everyone else "召唤物每回合", "h3"))
        self._folded: set[int] = set(folded or ())
        self._timelines = Timelines(turns, show_card, on_pick=self._pick, folded=self._folded)
        column.addWidget(self._timelines)
        self._column = column
        if self._turns:
            # Leo 2026-10-06: the page stays on what was shown when it is
            # rebuilt (a turn saved by F8, a change saved here).
            self.show_turn(shown if shown in self._turns else min(self._turns))

    @property
    def shown(self) -> int | None:
        return self._shown

    @property
    def opened(self) -> str | None:
        return self._open

    @property
    def folded(self) -> set[int]:
        return set(self._folded)

    @property
    def editable(self) -> bool:
        return self._record is not None and self._save is not None

    def show_turn(self, number: int) -> None:
        chart = self._turns.get(number)
        if chart is None:
            return
        self._shown = number
        for turn, chip in self._chips.items():
            chip.setChecked(turn == number)
        clear_layout(self.turn_area)
        order = vbox(None, (0, 0, 0, 0), 6)
        living = [unit for unit in chart.units if not unit.dead]
        line = hbox(None, (0, 0, 0, 0), 8)
        line.addWidget(
            Text(
                tf(
                    "第 {n} 回合 · TEAM{team} · 上场 {count} 人",
                    n=number,
                    team=chart.team,
                    count=len(living),
                ),
                "muted",
            )
        )
        line.addStretch(1)
        if self.editable:
            hint = (
                "点一个人改技能和爆发，拖动改顺序和站位，改完自动存"
                if self._everyone
                else "拖动改顺序和站位，点召唤物改技能，改完自动存"
            )
            line.addWidget(Text(hint, "muted"))
        order.addLayout(line)
        edited = self._record.edited.get(number, frozenset()) if self._record else frozenset()
        self._rows = []
        self._list = OrderList(self._drop)
        for unit in chart.units:
            skills = self._show_card(unit.name)
            opened = self.editable and skills and unit.name == self._open and not unit.dead
            row = OrderRow(
                unit,
                skills,
                on_click=self._toggle if self.editable and skills else None,
                on_drag=self._list.drag if self.editable and len(living) > 1 else None,
                # Leo 2026-10-06: no 「已改」 in 只看召唤物 (order and cells only)
                edited=self._everyone and unit.name in edited,
                open_=opened,
            )
            self._list.add(row)
            if not unit.dead:
                self._rows.append(row)
            if opened:
                self._list.add(
                    UnitEditor(
                        unit, lambda name, what, value: self._edit(number, name, what, value)
                    ),
                    editor=True,
                )
        order.addWidget(self._list)
        order.addStretch(1)
        self.turn_area.addLayout(order, 1)
        grid = Grid(
            chart,
            on_move=(lambda name, cell: self._edit(number, name, "cell", cell))
            if self.editable
            else None,
        )
        self.turn_area.addWidget(grid, 0, Qt.AlignTop)
        self.turn_area.addStretch(0)

    def _drop(self, name: str, index: int) -> None:
        number = self._shown
        before = self._record.turns[number].order
        self._edit(number, name, "move_to", index)
        if self._record.turns[number].order == before:  # not saved: rows back in place
            self.show_turn(number)

    def _pick(self, turn: int, unit: ChartUnit, cell: QWidget) -> None:
        """A card in 每人每回合 clicked: change it in a small window."""
        if not self.editable:
            return
        popup = CardPopup(
            turn,
            unit,
            lambda number, name, what, value: self._edit(number, name, what, value),
            self,
        )
        self.popup = popup
        popup.show_by(cell)

    def _toggle(self, name: str) -> None:
        self._open = None if self._open == name else name
        number = self._shown
        # Rebuilt after this click returns: the row that sent it goes away.
        QTimer.singleShot(0, lambda: self.show_turn(number))

    def _edit(self, number: int, name: str, what: str, value) -> None:
        """Apply one change to turn ``number`` and save it."""
        state = self._record.turns[number]
        chart = self._turns[number]
        units = {unit.name: unit for unit in chart.units}
        skills = dict(state.skills)
        bursts = dict(state.bursts)
        if not bursts:  # a save from before the levels were kept: as its screenshot shows
            bursts = {
                unit.name: unit.burst
                for unit in chart.units
                if not unit.dead and unit.action.startswith("技能")
            }
        worn = dict(state.costumes)
        order = list(state.order)
        changed = {name}
        if what == "card":
            skills[name] = value
            worn.pop(name, None)
            if value.startswith("技能"):
                bursts.setdefault(name, 0)
            else:
                bursts.pop(name, None)
        elif what == "costume":
            # The card label as recorded when that card was seen, else a bare
            # 技能: replay finds the costume's card either way (Leo 2026-10-06).
            cards = self._record.cards.get(name, {})
            skills[name] = next(
                (label for label, costume in cards.items() if costume == value), "技能"
            )
            worn[name] = value
            bursts.setdefault(name, 0)
        elif what == "burst":
            if not skills.get(name) and units[name].action:
                skills[name] = units[name].action
            bursts[name] = int(value)
        elif what == "move_to":
            order.remove(name)
            order.insert(max(0, min(int(value), len(order))), name)
            if tuple(order) == state.order:
                return
            changed = set(order)
            # Everyone is then checked by label: fill in what the screenshot showed.
            for unit in order:
                if unit not in skills and units[unit].action:
                    skills[unit] = units[unit].action
        elif what == "cell":
            # Leo 2026-10-06: drag on the grid; onto someone else, the two swap
            # (as in the game).  Tombstones stay put.
            cells = dict(state.cells)
            target = tuple(value)
            other = next((unit for unit, cell in cells.items() if cell == target), None)
            if other == name or other in state.dead or cells.get(name) == target:
                return
            if other is not None:
                cells[other] = cells[name]
            cells[name] = target
            changed = set()
        else:
            return
        try:
            new = TurnState(
                number,
                state.team,
                tuple(order),
                cells if what == "cell" else state.cells,
                state.dead,
                skills,
                bursts,
                worn,
            )
        except ValueError:
            return
        record = self._save(new, changed)
        if record is None:
            return
        self._record = record
        saved = record.turns[number]
        living = [units[unit] for unit in saved.order]
        for slot, unit in enumerate(living):
            unit.slot = slot
            unit.action = saved.skills.get(unit.name, unit.action)
            on_skill = unit.action.startswith("技能")
            unit.burst = saved.bursts.get(unit.name, unit.burst) if on_skill else 0
            unit.costume = saved.costumes.get(unit.name) if on_skill else None
        chart.units = living + [unit for unit in chart.units if unit.dead]
        for unit in chart.units:
            unit.cell = saved.cells.get(unit.name, unit.cell)
        # Rebuilt after this signal returns: the row that sent it goes away.
        QTimer.singleShot(0, lambda: self._redraw(number))

    def _redraw(self, number: int) -> None:
        # a card changed in 每人每回合 leaves the turn shown at the top as it was
        self.show_turn(self._shown if self._shown in self._turns else number)
        fresh = Timelines(
            list(self._turns.values()), self._show_card, on_pick=self._pick, folded=self._folded
        )
        self._column.replaceWidget(self._timelines, fresh)
        self._timelines.deleteLater()
        self._timelines = fresh
