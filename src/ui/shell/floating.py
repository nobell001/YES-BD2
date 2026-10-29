"""The dimmed window over the tool with one floating panel in the middle
(一键完成日常, 账号, 定时启动, 技能间隔, 跑完发到微信 ...).

Every one of them measures its panel again whenever its content asks for
more room: Leo's v0.2.7 (2026-10-22) showed 定时启动 squashed because its
height was taken once, and the same check then found 跑完发到微信's title cut.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QFrame, QLayout, QWidget

from src.ui.shell import cover, motion, theme
from src.ui.shell.widgets import vbox


class Panel(QFrame):
    """The floating window body: rounded, a deep soft shadow, a faint violet
    glow along the top."""

    SHADOW = 18

    def __init__(self, parent=None):
        super().__init__(parent)

    def body(self) -> QRectF:
        pad = self.SHADOW
        return QRectF(self.rect()).adjusted(pad, pad - 6, -pad, -pad - 6)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        body = self.body()
        corner = float(theme.radius()) + 8
        painter.setPen(Qt.NoPen)
        layers = 12
        for step in range(layers, 0, -1):
            fade = 1 - (step - 1) / layers
            painter.setBrush(theme.color("shadow", 0.05 * fade))
            grow = step * 1.4
            painter.drawRoundedRect(
                body.adjusted(-grow, -grow * 0.4 + 2, grow, grow * 1.2 + 2),
                corner + grow,
                corner + grow,
            )
        path = QPainterPath()
        path.addRoundedRect(body, corner, corner)
        painter.fillPath(path, theme.color("card"))
        painter.save()
        painter.setClipPath(path)
        top = QLinearGradient(body.topLeft(), body.topLeft() + QPointF(0, 150))
        top.setColorAt(0.0, theme.color("primary", 0.10))
        top.setColorAt(1.0, theme.color("primary", 0.0))
        painter.fillRect(QRectF(body.left(), body.top(), body.width(), 150), top)
        painter.restore()
        painter.setPen(QPen(theme.color("line2"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


class Floating(QDialog):
    """A dimmed window over the tool with one :class:`Panel` in the middle.

    The panel is as tall as its content needs, measured again whenever
    anything inside asks for more room (a row added, text set, fonts or the
    style applied late): Leo's v0.2.7 (2026-10-22) showed the 定时启动 rows
    squashed and cut because the height was taken once, too early.
    """

    PANEL_WIDTH = 520  # without the shadow
    MARGIN = 32  # free space kept around the panel inside the tool window
    PAD = (28, 24)  # inside the panel's card: sides, top and bottom
    SPACING = 14

    def __init__(self, parent: QWidget | None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet(theme.style_sheet())
        self._open = motion.Tween(self, self._place, 220, 0.0)
        self.panel = Panel(self)
        pad = Panel.SHADOW
        side, top = self.PAD
        self.column = vbox(
            self.panel, (pad + side, pad - 6 + top, pad + side, pad + 6 + top), self.SPACING
        )
        self._place_queued = False
        self.panel.installEventFilter(self)
        if parent is not None:
            cover.follow(self, parent.window())

    def eventFilter(self, watched, event):
        if watched is self.panel and event.type() == QEvent.LayoutRequest:
            self._queue_place()
        return super().eventFilter(watched, event)

    def _queue_place(self) -> None:
        if not self._place_queued:
            self._place_queued = True
            QTimer.singleShot(0, self._place)

    def content_height(self, width: int) -> int:
        """What the panel needs at ``width``: never less than its least size."""
        # Sizes just changed (a row added, the rows' view shortened) are
        # still cached in the inner layouts until the next event loop pass.
        for inner in self.panel.findChildren(QLayout):
            inner.invalidate()
        layout = self.panel.layout()
        layout.invalidate()
        layout.activate()
        need = layout.totalSizeHint().height()
        if layout.hasHeightForWidth():
            need = max(need, layout.totalHeightForWidth(width))
        return max(need, layout.totalMinimumSize().height())

    def least_width(self) -> int:
        """The panel's width (shadow included) below which something is cut."""
        return self.panel.layout().totalMinimumSize().width()

    def _place(self) -> None:
        # A place queued for the next pass can come after the window is gone
        # (2K test 2026-10-29: 29 「SlotEditor already deleted」 errors).
        if not shiboken6.isValid(self):
            return
        self._place_queued = False
        area = self.rect()
        # Wider than usual when the words need it (English day names).
        width = max(self.PANEL_WIDTH + 2 * Panel.SHADOW, self.least_width())
        width = min(width, area.width() - self.MARGIN)
        self.panel.setFixedWidth(width)
        height = min(self.content_height(width), area.height() - self.MARGIN)
        self.panel.setFixedHeight(height)
        shown = float(self._open.value)
        x = (area.width() - width) // 2
        y = (area.height() - height) // 2 + round(14 * (1 - shown))
        self.panel.move(x, y)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def showEvent(self, event):
        super().showEvent(event)
        self._place()
        self._open.go(1.0)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(
            self.rect(),
            theme.color(
                "shot", (0.62 if theme.tokens() is theme.DARK else 0.42) * float(self._open.value)
            ),
        )
