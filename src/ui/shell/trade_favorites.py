"""跑商's 收藏清单: a chart of which shop goods to favourite, for the player to
copy into the game (Leo 2026-11-13: 「只是讓玩家去看而已」).

The 买 card shows one row with an expand tile; pressed, a card under the three
steps opens with every shop cartridge drawn as a grid of cells, four to a row
as in the game's shop.  A violet cell is a product to favourite.  Nothing here
is clickable but the row: the tool buys whatever is favourited in the game.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.tasks.map_trade.data import SHOP_PRODUCT_COUNTS, SHOP_UNFAVORITED_POINTS
from src.ui.shell import icons, motion, theme
from src.ui.shell.widgets import (
    Card,
    IconTile,
    Inset,
    Picture,
    Text,
    hbox,
    t,
    vbox,
)

COLUMNS = 4  # the shop lists its goods four to a row
# The chart's columns, as on the chart players pass around: 剧情卡带 in three
# columns, then 角色卡带 and 活动卡带.  (kind word, cartridge codes)
KINDS = {"S": "剧情卡", "R": "角色卡", "E": "活动卡"}
SHEET = (
    tuple(f"S{n}" for n in range(1, 8)),
    tuple(f"S{n}" for n in range(8, 14)),
    tuple(f"S{n}" for n in range(14, 20)),
    tuple(code for code in SHOP_PRODUCT_COUNTS if code.startswith("R")),
    tuple(code for code in SHOP_PRODUCT_COUNTS if code.startswith("E")),
)


def chart_cells(code: str) -> list[bool]:
    """One flag per product of the cartridge, in shop order: favourite it or not."""
    skipped = SHOP_UNFAVORITED_POINTS.get(code, frozenset())
    return [slot not in skipped for slot in range(1, SHOP_PRODUCT_COUNTS.get(code, 0) + 1)]


def chart_label(code: str) -> str:
    return f"{t(KINDS[code[0]])} {code[1:]}"


def _paint_cell(painter: QPainter, rect: QRectF, lit: bool) -> None:
    """A plain square: violet = favourite it, empty = leave it (Leo 2026-11-13:
    「不要用星星 用紫色格子就好」, no rounded cards)."""
    painter.setPen(QPen(theme.color("ink3"), 1))
    painter.setBrush(theme.color("primary") if lit else theme.color("card"))
    painter.drawRect(rect)


class ExpandTile(QWidget):
    """The filled arrow on the 收藏清单 row.  Its ring pulses until the chart
    has been opened once (Leo 2026-11-13: 「要做個圖示提醒用戶展開」)."""

    TILE = 30
    MARGIN = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        side = self.TILE + 2 * self.MARGIN
        self.setFixedSize(side, side)
        self._open = False
        self._turn = motion.Tween(self, self.update, 220)
        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(0.0)
        self._pulse.setEndValue(1.0)
        self._pulse.setDuration(1800)
        self._pulse.setEasingCurve(QEasingCurve.OutCubic)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(lambda _value: self.update())
        self._reminding = True

    def set_open(self, on: bool) -> None:
        self._open = on
        if on:
            self._reminding = False
            self._pulse.stop()
        self._turn.go(1.0 if on else 0.0)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._reminding:
            self._pulse.start()

    def hideEvent(self, event):
        self._pulse.stop()
        super().hideEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        tile = QRectF(self.MARGIN, self.MARGIN, self.TILE, self.TILE)
        corner = theme.corner(9, 10)
        if self._reminding and self._pulse.state() == QVariantAnimation.Running:
            beat = float(self._pulse.currentValue() or 0.0)
            grow = (self.MARGIN - 1) * beat
            painter.setPen(QPen(theme.color("primary", 0.7 * (1.0 - beat)), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(
                tile.adjusted(-grow, -grow, grow, grow), corner + grow, corner + grow
            )
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("primary"))
        painter.drawRoundedRect(tile, corner, corner)
        # The arrow turns over as the chart opens.
        painter.translate(tile.center())
        painter.rotate(180 * float(self._turn.value))
        icons.paint(painter, QRectF(-9, -9, 18, 18), "chevron-down", theme.color("on_primary"), 2.2)


class FavoritesRow(QWidget):
    """收藏清单 inside the 买 card: the shop's cartridge, the name, and the
    expand tile.  The whole row is the button."""

    clicked = Signal()

    def __init__(self, picture: str | None, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self._hover = motion.HoverFade(self, self.update)
        self._open = False
        gap = theme.size("gap_sm")
        row = hbox(self, (gap + 4, gap, gap - 2, gap), theme.size("gap_md"))
        row.addWidget(Picture(picture, fixed=QSize(52, 44), radius=6))
        texts = vbox(None, (0, 0, 0, 0), 1)
        texts.addStretch(1)
        texts.addWidget(Text("收藏清单", "h3", elide=True))
        texts.addWidget(Text("看要收藏哪些商品", "muted", wrap=True))
        texts.addStretch(1)
        row.addLayout(texts, 1)
        self.arrow = ExpandTile()
        row.addWidget(self.arrow)

    def set_open(self, on: bool) -> None:
        self._open = on
        self.arrow.set_open(on)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        corner = theme.size("corner_small") + 4
        body = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._open:
            painter.setBrush(theme.color("accent_soft"))
            painter.setPen(QPen(theme.color("primary"), 1.5))
        else:
            painter.setBrush(theme.color("fill", self._hover.value))
            painter.setPen(QPen(theme.color("hair2"), 1))
        painter.drawRoundedRect(body, corner, corner)


class CartridgeChart(QWidget):
    """One cartridge: its name on the left, its goods as a grid of squares."""

    CELL = 16
    GAP = 8  # between the name and the grid

    def __init__(self, code: str, label_width: int, parent=None):
        super().__init__(parent)
        self._cells = chart_cells(code)
        self._label = chart_label(code)
        self._label_width = label_width
        rows = max(1, math.ceil(len(self._cells) / COLUMNS))
        self.setFixedSize(label_width + self.GAP + COLUMNS * self.CELL + 1, rows * self.CELL + 1)

    @classmethod
    def label_font(cls, base: QFont) -> QFont:
        font = QFont(base)
        font.setPixelSize(12)
        return theme.strong(font, digits=True)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setFont(self.label_font(self.font()))
        painter.setPen(theme.color("ink2"))
        painter.drawText(
            QRectF(0, 0, self._label_width, self.CELL + 1),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._label,
        )
        left = self._label_width + self.GAP + 0.5
        for index, lit in enumerate(self._cells):
            x = left + (index % COLUMNS) * self.CELL
            y = 0.5 + (index // COLUMNS) * self.CELL
            _paint_cell(painter, QRectF(x, y, self.CELL, self.CELL), lit)


class LegendCell(QWidget):
    def __init__(self, lit: bool, parent=None):
        super().__init__(parent)
        self._lit = lit
        self.setFixedSize(15, 15)

    def paintEvent(self, _event):
        painter = QPainter(self)
        _paint_cell(painter, QRectF(0.5, 0.5, 14, 14), self._lit)


class FavoritesCard(Card):
    """The opened 收藏清单: a reminder about the cooking skill, then the charts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        column = vbox(self, (18, 16, 18, 18), 12)
        head = hbox(None, (0, 0, 0, 0), 10)
        head.addWidget(IconTile("star", 30, 17, kind="trade"))
        head.addWidget(Text("收藏清单", "h2"))
        head.addWidget(Text("照着在游戏商店里点星星", "muted", elide=True), 1)
        for lit, words in ((True, "要收藏"), (False, "不用收藏")):
            head.addWidget(LegendCell(lit))
            head.addWidget(Text(words, "muted"))
        column.addLayout(head)
        # Leo 2026-11-13: 「裡面也要提醒用戶把料理技能放在任一個格子上」.
        remind = Inset()
        line = hbox(remind, (12, 9, 12, 9), 10)
        line.addWidget(IconTile("chef-hat", 28, 16, kind="trade"))
        line.addWidget(Text("出发前请把料理技能放在任一个技能格上", "sub", wrap=True), 1)
        column.addWidget(remind)
        from qfluentwidgets import FlowLayout

        metrics = QFontMetrics(CartridgeChart.label_font(self.font()))
        sheet = QWidget()
        flow = FlowLayout(sheet, needAni=False)
        flow.setContentsMargins(0, 0, 0, 0)
        flow.setHorizontalSpacing(26)
        flow.setVerticalSpacing(16)
        for codes in SHEET:
            if not codes:
                continue
            width = max(metrics.horizontalAdvance(chart_label(code)) for code in codes) + 2
            strip = QWidget()
            charts = vbox(strip, (0, 0, 0, 0), 10)
            for code in codes:
                charts.addWidget(CartridgeChart(code, width))
            charts.addStretch(1)
            flow.addWidget(strip)
        column.addWidget(sheet)
