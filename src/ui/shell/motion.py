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

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from src.ui.shell import cover, theme

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


# 淡紫 <-> 深色: the new colours open as a circle from the pressed option
# (Leo 2026-11-10, measured from the video he linked: hard-edged circle, slow
# start then fast, a grey ring riding on the edge, 0.55 s both ways).
REVEAL_MS = 550
REVEAL_START_PX = 10
REVEAL_RING = QColor(154, 154, 154, 178)
REVEAL_RING_SHARE = 0.018  # ring width as a share of the window width
REVEAL_RING_MIN_PX = 6


class ThemeReveal(QWidget):
    """A picture of the window in its old colours with a growing round hole.

    The real window underneath already has the new colours, so each frame is
    one clipped blit and nothing is restyled during the motion.  Clicks pass
    through, and the cover deletes itself when the circle has left the window.
    """

    def __init__(self, window: QWidget, shot: QPixmap, origin: QPoint):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._shot = shot
        self._origin = QPointF(origin)
        self._progress = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(REVEAL_MS)
        self._anim.setEasingCurve(QEasingCurve.InQuart)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self.finish)
        cover.follow(self, window)
        self.raise_()
        self.show()

    def start(self) -> None:
        self._anim.start()

    def finish(self) -> None:
        self._anim.stop()
        self.hide()
        self._shot = QPixmap()
        self.deleteLater()

    def ring_width(self) -> float:
        return max(REVEAL_RING_MIN_PX, self.width() * REVEAL_RING_SHARE)

    def end_radius(self) -> float:
        """Far enough that the ring too has left the farthest corner."""
        x, y = self._origin.x(), self._origin.y()
        far_x = max(x, self.width() - x)
        far_y = max(y, self.height() - y)
        return (far_x * far_x + far_y * far_y) ** 0.5 + self.ring_width()

    def radius(self) -> float:
        return REVEAL_START_PX + (self.end_radius() - REVEAL_START_PX) * self._progress

    def _step(self, value) -> None:
        self._progress = float(value)
        self.update()

    def paintEvent(self, _event):
        if self._shot.isNull():
            return
        radius = self.radius()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        old = QPainterPath()
        old.addRect(QRectF(self.rect()))
        hole = QPainterPath()
        hole.addEllipse(self._origin, radius, radius)
        painter.setClipPath(old.subtracted(hole))
        painter.drawPixmap(0, 0, self._shot)
        painter.setClipping(False)
        ring = self.ring_width()
        painter.setPen(QPen(REVEAL_RING, ring))
        painter.setBrush(Qt.NoBrush)
        mid = radius - ring / 2
        if mid > 0:
            painter.drawEllipse(self._origin, mid, mid)


def switch_theme(mode: str, source: QWidget | None = None) -> ThemeReveal | None:
    """Switch 淡紫 / 深色 / 跟随系统, opening the new colours from ``source``.

    The switch itself never waits for or depends on the motion: when there is
    nothing to watch (window hidden or minimized, no source, the colours stay
    the same, or taking the picture fails) it is the plain instant switch.
    """
    window = source.window() if source is not None else None
    for stale in window.findChildren(ThemeReveal) if window is not None else ():
        stale.finish()
    reveal = None
    was_dark = theme.isDarkTheme()
    try:
        if (
            window is not None
            and source.isVisible()
            and window.isVisible()
            and not window.isMinimized()
            and window.width() > 0
        ):
            shot = window.grab()
            if not shot.isNull():
                origin = source.mapTo(window, source.rect().center())
                reveal = ThemeReveal(window, shot, origin)
    except Exception:  # the motion is decoration: never block the switch
        reveal = None
    theme.set_theme_mode(mode)
    if reveal is None:
        return None
    if theme.isDarkTheme() == was_dark:
        reveal.finish()
        return None
    reveal.start()
    return reveal
