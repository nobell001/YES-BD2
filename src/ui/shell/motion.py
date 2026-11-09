"""Page switches for the new pages: the incoming page rises a little and fades in.

The old transition (removed 2026-10-04) animated the live page
through a ``QGraphicsOpacityEffect``, which redraws the whole page off screen
on every frame; on a 4K screen that ran at a low frame rate (Leo,
2026-10-03: 「整體系統操作感覺fps有點低」).  Here the page is drawn once into a
picture and an opaque cover moves and fades that picture, so each frame is a
single blit.  When the motion ends the cover hides and the real page, already
in place underneath with the same pixels, takes over.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from src.ui.shell import theme

DURATION_MS = 220
RISE_PX = 18


class PageCover(QWidget):
    """Opaque cover over the page stack that plays one page entrance."""

    def __init__(self, stack: QWidget):
        super().__init__(stack)
        self._stack = stack
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        # Clicks and wheel go to the real page underneath.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._shot = QPixmap()
        self._page: QWidget | None = None
        self._progress = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self._done)
        self.hide()

    def play(self, page: QWidget) -> None:
        self._anim.stop()
        if not self.window().isVisible() or page.width() <= 0:
            self._done()
            return
        # Cover the page with the plain ground at once, but take its picture
        # one turn of the event loop later: a page filled for the first time
        # (the 跑商 calendar, say) only shows its new parts after that turn.
        self._page = page
        self._shot = QPixmap()
        self._progress = 0.0
        self.setGeometry(page.geometry())
        self.raise_()
        self.show()
        QTimer.singleShot(0, self._start)

    def _start(self) -> None:
        page, self._page = self._page, None
        if page is None or not self.isVisible():
            return
        _settle_layout(page)
        self.setGeometry(page.geometry())
        self._shot = page.grab()
        self._anim.start()

    def _step(self, value) -> None:
        self._progress = float(value)
        self.update()

    def _done(self) -> None:
        self._page = None
        self.hide()
        self._shot = QPixmap()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.color("bg"))
        if self._shot.isNull():
            return
        painter.setOpacity(self._progress)
        painter.drawPixmap(0, round(RISE_PX * (1.0 - self._progress)), self._shot)


def _settle_layout(page: QWidget) -> None:
    """Lay the freshly shown page out before taking its picture."""
    QApplication.sendPostedEvents(None, QEvent.LayoutRequest)


HOVER_MS = 140


class HoverFade(QObject):
    """A 0..1 value that eases in while the mouse is over ``source``.

    Hover effects (an icon growing a little, a card edge tinting) read this
    instead of switching on and off, so they stay quiet (Leo, 2026-10-05:
    「多一些互動效果……但不要太花」).
    """

    def __init__(self, source: QWidget, on_change: Callable[[], None]):
        super().__init__(source)
        self.value = 0.0
        self._on_change = on_change
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(HOVER_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._step)
        source.installEventFilter(self)

    def eventFilter(self, _watched, event):
        kind = event.type()
        if kind == QEvent.Enter:
            self._fade(1.0)
        elif kind in (QEvent.Leave, QEvent.Hide):
            self._fade(0.0)
        return False

    def _fade(self, target: float) -> None:
        self._anim.stop()
        if self.value == target:
            return
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(target)
        self._anim.start()

    def _step(self, value) -> None:
        self.value = float(value)
        self._on_change()


class Tween(QObject):
    """A number that eases to each new target while its widget is on screen.

    Off screen (a page not showing, a widget not yet laid out) it jumps, so a
    page always opens looking settled and only changes you watch are animated.
    """

    def __init__(
        self,
        owner: QWidget,
        on_change: Callable[[], None],
        duration: int,
        value=0.0,
        easing: QEasingCurve.Type = QEasingCurve.OutCubic,
    ):
        super().__init__(owner)
        self._owner = owner
        self.value = value
        self.target = value
        self._on_change = on_change
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(easing)
        self._anim.valueChanged.connect(self._step)

    def running(self) -> bool:
        return self._anim.state() == QVariantAnimation.Running

    def go(self, target, animate: bool = True) -> None:
        self.target = target
        self._anim.stop()
        if not animate or not self._owner.isVisible() or self.value == target:
            self.value = target
            self._on_change()
            return
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(target)
        self._anim.start()

    def _step(self, value) -> None:
        self.value = value
        self._on_change()
