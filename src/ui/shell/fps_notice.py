"""「开着 FPS 工具」: a short note before a run the player starts (Leo 2026-11-04).

「偵測到玩家開啟 fps 工具的時候提醒可能會導致失敗 然後3秒後開始 自動排程的不受影響」

Shown only for a start the player pressed: the run then starts by itself
after 3 seconds, the note never holds it up.  定时启动 and 「打开就自动跑」
start without a window and never see it.  取消 is there for a player who
wants to close the tool first.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from src.ui.shell import icons, theme
from src.ui.shell.floating import Floating, Panel
from src.ui.shell.widgets import Bar, Button, Text, hbox, tf, vbox
from src.utils import fps_tools

COUNT_DOWN_S = 3
PANEL_WIDTH = 440

TITLE = "开着 FPS 工具"
BODY = "{names} 会在游戏画面上画字或改帧数，可能让工具认错画面而失败。"
HINT = "跑之前关掉它最稳"
STARTS_IN = "{n} 秒后开始"


class WarnIcon(QWidget):
    """A soft amber disc with the alert line icon."""

    def __init__(self, size: int = 40, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = float(self.width())
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("warn_soft"))
        painter.drawEllipse(QRectF(0, 0, side, side))
        pad = side * 0.24
        icons.paint(
            painter,
            QRectF(pad, pad, side - 2 * pad, side - 2 * pad),
            "circle-alert",
            theme.color("warn"),
            2.1,
        )


class FpsNotice(Floating):
    PANEL_WIDTH = PANEL_WIDTH - 2 * Panel.SHADOW
    MARGIN = 64
    PAD = (24, 20)

    def __init__(self, labels: list[str], parent: QWidget | None = None, seconds: int = COUNT_DOWN_S):
        super().__init__(parent)
        self._left = max(0, int(seconds))
        self._total = max(1, int(seconds))
        column = self.column

        head = hbox(None, (0, 0, 0, 0), 12)
        head.addWidget(WarnIcon(40), 0, Qt.AlignTop)
        titles = vbox(None, (0, 0, 0, 0), 4)
        titles.addWidget(Text(TITLE, "h2"))
        self.body = Text(tf(BODY, names=fps_tools.joined(labels)), "sub", wrap=True)
        titles.addWidget(self.body)
        titles.addWidget(Text(HINT, "muted", wrap=True))
        head.addLayout(titles, 1)
        column.addLayout(head)

        self.bar = Bar(height=6, colour="warn")
        self.bar.set_value(1.0)
        column.addWidget(self.bar)

        buttons = hbox(None, (0, 4, 0, 0), 8)
        self.count = Text("", "muted")
        buttons.addWidget(self.count, 1, Qt.AlignVCenter)
        self.cancel_button = Button("取消", "secondary", on_click=self.reject)
        buttons.addWidget(self.cancel_button)
        self.go_button = Button("现在开始", "primary", on_click=self.accept)
        buttons.addWidget(self.go_button)
        column.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._show_left()

    def _show_left(self) -> None:
        self.count.set_text(tf(STARTS_IN, n=self._left))
        self.bar.set_value(self._left / self._total)

    def _tick(self) -> None:
        self._left -= 1
        if self._left <= 0:
            self._timer.stop()
            self.accept()
            return
        self._show_left()

    def showEvent(self, event):
        super().showEvent(event)
        if self._left <= 0:
            QTimer.singleShot(0, self.accept)
        elif not self._timer.isActive():
            self._timer.start()

    def done(self, result):
        self._timer.stop()
        super().done(result)


def go_ahead(window: QWidget | None, labels: list[str] | None = None) -> bool:
    """True to start: no FPS tool, no window (定时启动), 现在开始 or the count
    down ran out.  False only on 取消.  Never raises: a note must not stop a run."""
    if window is None:
        return True
    try:
        labels = fps_tools.running() if labels is None else labels
        if not labels:
            return True
        from ok import Logger

        Logger.get_logger(__name__).info(f"FPS tool running before start: {fps_tools.joined(labels)}")
        return bool(FpsNotice(labels, window).exec())
    except Exception:
        return True
