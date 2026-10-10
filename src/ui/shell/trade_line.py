"""What a trade run sold and cooked, as item and dish pictures under its row.

YES-BD2 #6 (2026-10-10): players could not tell whether the trade really
sold and cooked.  Leo: the words with the item pictures, no screenshots
(a run cooks up to fifteen dishes).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from src.ui.shell import data, theme
from src.ui.shell.widgets import Text, draw_fitted, hbox, t, vbox

ICON_SIZE = 30


def five_star(recipe: str) -> bool:
    from src.tasks.map_trade.models import OPTIONAL_COOKING_RECIPES

    return recipe in OPTIONAL_COOKING_RECIPES


class GoodsIcon(QWidget):
    """An item or dish picture on a soft square; its name and count on hover
    (Leo 2026-10-10)."""

    def __init__(
        self,
        name: str,
        path: str | None,
        quantity: int | None = None,
        size: int = ICON_SIZE,
        parent=None,
    ):
        super().__init__(parent)
        self._pixmap = QPixmap(path or "")
        self.setFixedSize(size, size)
        self.setToolTip(t(name) + (f" ×{quantity:,}" if isinstance(quantity, int) else ""))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("inset"))
        painter.drawRoundedRect(QRectF(self.rect()), theme.corner(5), theme.corner(5))
        if not self._pixmap.isNull():
            inner = QRectF(self.rect().adjusted(2, 2, -2, -2))
            draw_fitted(painter, inner, self._pixmap, self.devicePixelRatioF())


class TradeLine(QWidget):
    """卖了 [兽肉] ×1,980 [红酒] ×600 / 做了 [dishes] 5星 [dishes]."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shown = None
        self.layout_ = vbox(self, (0, 4, 0, 2), 6)
        self.hide()

    def set_trade(self, trade: dict | None) -> None:
        trade = trade or {}
        key = repr(trade)
        if key == self._shown:
            return
        self._shown = key
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    child = layout.takeAt(0)
                    if child.widget() is not None:
                        child.widget().deleteLater()
            elif item.widget() is not None:
                item.widget().deleteLater()
        sold = [entry for entry in trade.get("sold") or [] if entry]
        cooked = [entry for entry in trade.get("cooked") or [] if entry]
        if sold:
            row = self._line("卖了")
            for item, quantity in sold:
                row.addWidget(GoodsIcon(item, data.item_picture(item), quantity))
                text = f"×{quantity:,}" if isinstance(quantity, int) else t(item)
                row.addWidget(Text(text, "muted"))
                row.addSpacing(6)
            row.addStretch(1)
        if cooked:
            row = self._line("做了")
            regular = [entry for entry in cooked if not five_star(entry[0])]
            special = [entry for entry in cooked if five_star(entry[0])]
            for recipe, quantity in regular:
                row.addWidget(GoodsIcon(recipe, data.dish_picture(recipe), quantity))
            if special:
                if regular:
                    row.addSpacing(6)
                row.addWidget(Text("5星", "muted"))
                for recipe, quantity in special:
                    row.addWidget(GoodsIcon(recipe, data.dish_picture(recipe), quantity))
            row.addStretch(1)
        self.setVisible(bool(sold or cooked))

    def _line(self, label: str):
        row = hbox(None, (0, 0, 0, 0), 4)
        row.addWidget(Text(label, "muted"))
        row.addSpacing(4)
        self.layout_.addLayout(row)
        return row
