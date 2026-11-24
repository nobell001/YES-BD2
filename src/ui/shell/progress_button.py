# Lucian UX/UI Prompt #438 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#438
"""A button that turns into a spinner and then a check (Leo 2026-11-24:
「這個給一些按鈕用 像是檢查更新」).

Pressed, the button squeezes, its label fades as it shrinks into a circle and
a ring starts to spin.  When the work is done a check draws itself in a green
circle, then the button stretches back to full width and the label returns.
If the work failed it stretches back without the check; the page says why.

Ported from the web element #438: the durations, curves and delays are the
element's own; its ``--ux-*`` colours map to theme tokens (accent →
``primary`` / the button's own colours, accent ink → its text colour, mint →
``ok``).  Two things a Qt widget does differently:

* The button keeps its full width in the layout, so nothing beside it moves;
  the shrinking pill is drawn centred in that box.
* The pop, the ring and a width overshoot reach past the button's box, so the
  motion is drawn on a see-through stage just above it, in the same parent.

When Windows has 「顯示動畫」 turned off, every motion jumps to its end (the
element's prefers-reduced-motion rule) and the waits are shorter.

Use ``start()`` when the work begins (or let a click do it with
``auto_start=True``), then ``finish(True)`` / ``finish(False)``.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from src.ui.shell import theme
from src.ui.shell.widgets import Button, mix


def _bezier(x1: float, y1: float, x2: float, y2: float) -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0))
    return curve


# The element's curves, as written there.
EASE = _bezier(0.2, 0.8, 0.2, 1.0)  # --ux-ease
SQUEEZE = _bezier(0.65, 0.0, 0.35, 1.0)  # width while shrinking
STRETCH = _bezier(0.34, 1.32, 0.5, 1.0)  # width while growing back (overshoots)
SPRING = _bezier(0.34, 1.7, 0.5, 1.0)  # scale, pop
SPRING_ICON = _bezier(0.34, 1.6, 0.5, 1.0)  # spinner / check scale

# Milliseconds, as in the element.
SHRINK_MS = 460
GROW_MS = 620
GROW_CLASS_MS = 700  # how long the growing curves stay on
PRESS_MS = 120
SCALE_MS = 500
COLOUR_MS = 350
LABEL_FADE_MS = 220
LABEL_SCALE_MS = 300
LABEL_BACK_DELAY_MS = 160
ICON_FADE_MS = 200
ICON_SCALE_MS = 400
SPINNER_DELAY_MS = 220
SPIN_MS = 750
CHECK_DRAW_MS = 380
CHECK_DRAW_DELAY_MS = 120
POP_MS = 500
RING_MS = 700
RING_DELAY_MS = 100
OK_HOLD_MS = 1000
OK_HOLD_REDUCED_MS = 600
# The element's demo spins 1.35 s before it says done; here the real work
# decides, but the circle is always reached and the spinner seen first.
MIN_BUSY_MS = 700
MIN_BUSY_REDUCED_MS = 400

HOVER_SCALE = 1.02
PRESS_SCALE = 0.93
POP_SCALE = 1.12
RING_SCALE = 1.7
RING_OPACITY = 0.7
LABEL_GONE_SCALE = 0.9
ICON_GONE_SCALE = 0.4
# Spinner / check box: 22 px in the element's 48 px circle.
ICON_SHARE = 22 / 48
SPINNER_STROKE_SHARE = 2.5 / 48
SPINNER_TRACK_ALPHA = 0.28
CHECK_STROKE = 2.8  # in the check's 24-unit box
CHECK_POINTS = ((5.5, 12.5), (10.0, 17.0), (18.5, 7.5))
FRAME_MS = 16

IDLE, BUSY, OK = "idle", "busy", "ok"

_SPI_GETCLIENTAREAANIMATION = 0x1042


def reduced_motion() -> bool:
    """True when Windows 「顯示動畫」 is off (the prefers-reduced-motion of a PC)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        on = ctypes.c_int(1)
        if not ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(on), 0
        ):
            return False
        return not on.value
    except Exception:
        return False


class _Move:
    """One value easing from where it is to a target, with a delay."""

    def __init__(self, value: float):
        self.start_value = value
        self.target = value
        self.begin = 0
        self.length = 0
        self.curve = EASE

    def to(
        self, target: float, now: int, ms: int, curve: QEasingCurve = EASE, delay: int = 0
    ) -> None:
        self.start_value = self.at(now)
        self.target = target
        self.begin = now + delay
        self.length = ms
        self.curve = curve

    def jump(self, value: float) -> None:
        self.start_value = self.target = value
        self.length = 0

    def at(self, now: int) -> float:
        if now < self.begin:
            return self.start_value
        if self.length <= 0 or now >= self.begin + self.length:
            return self.target
        progress = self.curve.valueForProgress((now - self.begin) / self.length)
        return self.start_value + (self.target - self.start_value) * progress

    def moving(self, now: int) -> bool:
        return self.start_value != self.target and now < self.begin + max(self.length, 0) + 1


class _Stage(QWidget):
    """See-through layer just above the button that draws its motion."""

    def __init__(self, button: ProgressButton):
        super().__init__(button.parentWidget())
        self._button = button
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._button.paint_on(painter, self)


class ProgressButton(Button):
    """A :class:`Button` that shows its work: circle and spinner, then a check."""

    def __init__(
        self,
        text: str = "",
        kind: str = "primary",
        icon_name: str | None = None,
        size: str | None = None,
        parent=None,
        on_click: Callable | None = None,
        auto_start: bool = False,
    ):
        super().__init__(text, kind, icon_name, size, parent, on_click=None)
        # The element's own press (93 %, quick) and spring replace Button's dip.
        try:
            self.pressed.disconnect()
            self.released.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.state = IDLE
        self._clock = QElapsedTimer()
        self._clock.start()
        self._reduced = reduced_motion()
        self._growing_until = -1
        self._busy_since = 0
        self._down = False
        self._hovered = False
        self._pop_at = -1
        self._ring_at = -1
        self.squeeze = _Move(0.0)  # 0 = full width, 1 = circle
        self.scale = _Move(1.0)
        self.done_colour = _Move(0.0)  # 0 = the button's colour, 1 = ok green
        self.label_alpha = _Move(1.0)
        self.label_scale = _Move(1.0)
        self.spinner_alpha = _Move(0.0)
        self.spinner_scale = _Move(ICON_GONE_SCALE)
        self.check_alpha = _Move(0.0)
        self.check_scale = _Move(ICON_GONE_SCALE)
        self.check_drawn = _Move(0.0)
        self._frame = QTimer(self)
        self._frame.setInterval(FRAME_MS)
        self._frame.timeout.connect(self._tick)
        self._finish_timer = QTimer(self)
        self._finish_timer.setSingleShot(True)
        self._pending: bool | None = None
        self._finish_timer.timeout.connect(self._finish_now)
        self._grow_timer = QTimer(self)
        self._grow_timer.setSingleShot(True)
        self._grow_timer.timeout.connect(self._grow_back)
        self._stage: _Stage | None = None
        self._auto_start = auto_start
        if on_click is not None:
            self.clicked.connect(lambda *_: self._clicked(on_click))
        self.installEventFilter(self)

    # ------------------------------------------------------------ public

    def working(self) -> bool:
        """Busy or showing its check: clicks are ignored until it is back."""
        return self.state != IDLE or self._grow_timer.isActive()

    def start(self) -> None:
        """The work began: shrink into a circle and spin."""
        if self.state == BUSY:
            return
        self._finish_timer.stop()
        self._grow_timer.stop()
        self._pending = None
        now = self._now()
        self.state = BUSY
        self._busy_since = now
        self._growing_until = -1
        self._down = False
        self.squeeze.to(1.0, now, self._ms(SHRINK_MS), SQUEEZE)
        self.scale.to(1.0, now, self._ms(SCALE_MS), SPRING)
        self.done_colour.to(0.0, now, self._ms(COLOUR_MS))
        self.label_alpha.to(0.0, now, self._ms(LABEL_FADE_MS))
        self.label_scale.to(LABEL_GONE_SCALE, now, self._ms(LABEL_SCALE_MS))
        self.spinner_alpha.to(1.0, now, self._ms(ICON_FADE_MS), EASE, SPINNER_DELAY_MS)
        self.spinner_scale.to(1.0, now, self._ms(ICON_SCALE_MS), SPRING_ICON, SPINNER_DELAY_MS)
        self._hide_check(now)
        self._run()

    def finish(self, ok: bool = True) -> None:
        """The work ended: a check when ``ok``, then back to the label."""
        if self.state != BUSY:
            return
        elapsed = self._now() - self._busy_since
        least = MIN_BUSY_REDUCED_MS if self._reduced else MIN_BUSY_MS
        self._pending = ok
        if elapsed < least:
            self._finish_timer.start(int(least - elapsed))
        else:
            self._finish_now()

    def reset(self) -> None:
        """Back to the plain button at once (a new record, a closed page)."""
        self._finish_timer.stop()
        self._grow_timer.stop()
        self._pending = None
        self.state = IDLE
        self._growing_until = -1
        for move, value in (
            (self.squeeze, 0.0),
            (self.scale, 1.0),
            (self.done_colour, 0.0),
            (self.label_alpha, 1.0),
            (self.label_scale, 1.0),
            (self.spinner_alpha, 0.0),
            (self.spinner_scale, ICON_GONE_SCALE),
            (self.check_alpha, 0.0),
            (self.check_scale, ICON_GONE_SCALE),
            (self.check_drawn, 0.0),
        ):
            move.jump(value)
        self._pop_at = self._ring_at = -1
        self._run()

    # ------------------------------------------------------------ steps

    def _clicked(self, on_click: Callable) -> None:
        if self.working():
            return
        if self._auto_start:
            self.start()
        on_click()

    def _finish_now(self) -> None:
        ok, self._pending = self._pending, None
        if self.state != BUSY or ok is None:
            return
        now = self._now()
        self.spinner_alpha.to(0.0, now, self._ms(ICON_FADE_MS))
        self.spinner_scale.to(ICON_GONE_SCALE, now, self._ms(ICON_SCALE_MS), SPRING_ICON)
        if not ok:
            self._grow_back()
            return
        self.state = OK
        self.done_colour.to(1.0, now, self._ms(COLOUR_MS))
        self.check_alpha.to(1.0, now, self._ms(ICON_FADE_MS))
        self.check_scale.to(1.0, now, self._ms(ICON_SCALE_MS), SPRING_ICON)
        self.check_drawn.to(1.0, now, self._ms(CHECK_DRAW_MS), EASE, CHECK_DRAW_DELAY_MS)
        self._pop_at = now if not self._reduced else -1
        self._ring_at = now + RING_DELAY_MS if not self._reduced else -1
        self._grow_timer.start(OK_HOLD_REDUCED_MS if self._reduced else OK_HOLD_MS)
        self._run()

    def _grow_back(self) -> None:
        now = self._now()
        self.state = IDLE
        self._growing_until = now + (0 if self._reduced else GROW_CLASS_MS)
        self.squeeze.to(0.0, now, self._ms(GROW_MS), STRETCH)
        self.scale.to(self._rest_scale(), now, self._ms(SCALE_MS), SPRING)
        self.done_colour.to(0.0, now, self._ms(COLOUR_MS))
        self.label_alpha.to(1.0, now, self._ms(LABEL_FADE_MS), EASE, LABEL_BACK_DELAY_MS)
        self.label_scale.to(1.0, now, self._ms(LABEL_SCALE_MS), EASE, LABEL_BACK_DELAY_MS)
        self.spinner_alpha.to(0.0, now, self._ms(ICON_FADE_MS))
        self.spinner_scale.to(ICON_GONE_SCALE, now, self._ms(ICON_SCALE_MS), SPRING_ICON)
        self._hide_check(now)
        self._run()

    def _hide_check(self, now: int) -> None:
        self.check_alpha.to(0.0, now, self._ms(ICON_FADE_MS))
        self.check_scale.to(ICON_GONE_SCALE, now, self._ms(ICON_SCALE_MS), SPRING_ICON)
        self.check_drawn.to(0.0, now, self._ms(CHECK_DRAW_MS), EASE, CHECK_DRAW_DELAY_MS)

    def _rest_scale(self) -> float:
        if self.state != IDLE:
            return 1.0
        if self._down:
            return PRESS_SCALE
        return HOVER_SCALE if self._hovered and self.isEnabled() else 1.0

    def _aim_scale(self) -> None:
        now = self._now()
        target = self._rest_scale()
        if self._down:
            self.scale.to(target, now, self._ms(PRESS_MS))
        else:
            self.scale.to(target, now, self._ms(SCALE_MS), SPRING)
        self._run()

    def _ms(self, ms: int) -> int:
        return 0 if self._reduced else ms

    def _now(self) -> int:
        return int(self._clock.elapsed())

    # ------------------------------------------------------------ events

    def eventFilter(self, watched, event):
        if watched is self:
            kind = event.type()
            if kind in (QEvent.Move, QEvent.Resize, QEvent.Show):
                self._place_stage()
            elif kind == QEvent.Hide:
                if self._stage is not None:
                    self._stage.hide()
            elif kind == QEvent.ParentChange:
                if self._stage is not None:
                    self._stage.deleteLater()
                    self._stage = None
                self._place_stage()
            elif kind == QEvent.Enter:
                self._hovered = True
                self._aim_scale()
            elif kind == QEvent.Leave:
                self._hovered = False
                self._down = False
                self._aim_scale()
            elif kind == QEvent.EnabledChange:
                self._aim_scale()
        return False

    def mousePressEvent(self, event):
        if self.working():
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._down = True
            self._aim_scale()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._down:
            self._down = False
            self._aim_scale()
        if self.working():
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        # The stage above draws the whole button; drawing here too would
        # show a second, still copy under the motion.
        if self._stage is None or not self._stage.isVisible():
            self._place_stage()
            if self._stage is None:
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing, True)
                self.paint_on(painter, self)

    # ------------------------------------------------------------ drawing

    def _margins(self) -> tuple[int, int]:
        height = self.height()
        ring = math.ceil(height * (RING_SCALE - 1) / 2) + 2
        overshoot = math.ceil(self.width() * 0.08) + 2
        return max(ring, overshoot), ring

    def _place_stage(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        if self._stage is None or self._stage.parentWidget() is not parent:
            self._stage = _Stage(self)
        side, top = self._margins()
        self._stage.setGeometry(self.geometry().adjusted(-side, -top, side, top))
        self._stage.setVisible(self.isVisible())
        self._stage.raise_()
        self._stage.update()

    def _run(self) -> None:
        if not self._frame.isActive():
            self._frame.start()
        self._tick()

    def _tick(self) -> None:
        if self._stage is not None:
            self._stage.update()
        else:
            self.update()
        now = self._now()
        moves = (
            self.squeeze,
            self.scale,
            self.done_colour,
            self.label_alpha,
            self.label_scale,
            self.spinner_alpha,
            self.spinner_scale,
            self.check_alpha,
            self.check_scale,
            self.check_drawn,
        )
        busy = any(move.moving(now) for move in moves)
        spinning = self.spinner_alpha.at(now) > 0 and not self._reduced
        effects = (self._pop_at >= 0 and now < self._pop_at + POP_MS) or (
            self._ring_at >= 0 and now < self._ring_at + RING_MS
        )
        if not (busy or spinning or effects):
            self._frame.stop()

    def _colours(self) -> tuple[QColor, QColor, QColor | None]:
        """Fill, ink and edge of the resting button, as its style draws it."""
        enabled = self.isEnabled() or self.state != IDLE
        if self._kind == "primary":
            if not enabled:
                return theme.color("line2"), theme.color("ink3"), None
            return theme.color("primary"), theme.color("on_primary"), None
        if self._kind == "danger":
            return (
                theme.color("card"),
                theme.color("bad" if enabled else "ink3"),
                theme.color("line2"),
            )
        pill = theme.shape("button") == 0
        fill = theme.color("fill") if pill else theme.color("card")
        edge = None if pill else theme.color("line2")
        return fill, theme.color("ink" if enabled else "ink3"), edge

    def _done_ink(self) -> QColor:
        ok = theme.color("ok")
        light = 0.2126 * ok.redF() + 0.7152 * ok.greenF() + 0.0722 * ok.blueF()
        return theme.color("bg") if light > 0.5 else theme.color("on_primary")

    def _scale_now(self, now: int) -> float:
        if self._pop_at >= 0 and now < self._pop_at + POP_MS:
            progress = (now - self._pop_at) / POP_MS
            if progress < 0.4:
                eased = SPRING.valueForProgress(progress / 0.4)
                return 1.0 + (POP_SCALE - 1.0) * eased
            eased = SPRING.valueForProgress((progress - 0.4) / 0.6)
            return POP_SCALE + (1.0 - POP_SCALE) * eased
        return self.scale.at(now)

    def paint_on(self, painter: QPainter, canvas: QWidget) -> None:
        now = self._now()
        # The stage is a sibling: the button sits at its own place minus the stage's.
        offset = self.pos() - canvas.pos() if canvas is not self else self.rect().topLeft()
        box = QRectF(self.rect()).translated(offset.x(), offset.y())
        height = box.height()
        full = box.width()
        squeeze = self.squeeze.at(now)
        width = max(height, full - squeeze * (full - height))
        centre = box.center()
        shape = QRectF(centre.x() - width / 2, centre.y() - height / 2, width, height)
        radius = height / 2
        fill, ink, edge = self._colours()
        ok_amount = self.done_colour.at(now)
        if ok_amount > 0:
            fill = mix(fill, theme.color("ok"), ok_amount)
            ink = mix(ink, self._done_ink(), ok_amount)
            if edge is not None:
                edge = mix(edge, theme.color("ok"), ok_amount)

        painter.save()
        scale = self._scale_now(now)
        painter.translate(centre)
        painter.scale(scale, scale)
        painter.translate(-centre)
        path = QPainterPath()
        path.addRoundedRect(shape, radius, radius)
        painter.fillPath(path, fill)
        if edge is not None:
            painter.setPen(QPen(edge, 1))
            painter.drawRoundedRect(
                shape.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5
            )
        painter.setClipPath(path)
        self._paint_label(painter, box, ink, now)
        painter.setClipping(False)
        self._paint_spinner(painter, centre, height, ink, now)
        self._paint_check(painter, centre, height, ink, now)
        painter.restore()
        self._paint_ring(painter, shape, centre, now)

    def _paint_label(self, painter: QPainter, box: QRectF, ink: QColor, now: int) -> None:
        alpha = self.label_alpha.at(now)
        text = self.text()
        if alpha <= 0.001 or not (text or not self.icon().isNull()):
            return
        painter.save()
        scale = self.label_scale.at(now)
        centre = box.center()
        painter.translate(centre)
        painter.scale(scale, scale)
        painter.translate(-centre)
        painter.setOpacity(painter.opacity() * alpha)
        icon = self.icon()
        icon_size = self.iconSize()
        metrics = self.fontMetrics()
        text_width = metrics.horizontalAdvance(text) if text else 0
        has_icon = not icon.isNull()
        gap = self.ICON_GAP if has_icon and text else 0
        icon_width = icon_size.width() if has_icon else 0
        left = box.left() + (box.width() - icon_width - gap - text_width) / 2
        if has_icon:
            mode = QIcon.Normal if self.isEnabled() or self.state != IDLE else QIcon.Disabled
            pixmap = icon.pixmap(icon_size, self.devicePixelRatioF(), mode)
            top = box.top() + (box.height() - icon_size.height()) / 2
            painter.drawPixmap(QPointF(left, top), pixmap)
        if text:
            painter.setFont(self.font())
            painter.setPen(ink)
            text_box = QRectF(left + icon_width + gap, box.top(), text_width + 2, box.height())
            painter.drawText(text_box, Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()

    def _icon_box(self, centre: QPointF, height: float, scale: float) -> QRectF:
        side = height * ICON_SHARE * scale
        return QRectF(centre.x() - side / 2, centre.y() - side / 2, side, side)

    def _paint_spinner(
        self, painter: QPainter, centre: QPointF, height: float, ink: QColor, now: int
    ) -> None:
        alpha = self.spinner_alpha.at(now)
        if alpha <= 0.001:
            return
        scale = self.spinner_scale.at(now)
        side = height * ICON_SHARE
        stroke = max(2.0, height * SPINNER_STROKE_SHARE)
        painter.save()
        painter.translate(centre)
        painter.scale(scale, scale)
        if not self._reduced:
            painter.rotate((now % SPIN_MS) / SPIN_MS * 360.0)
        painter.setOpacity(painter.opacity() * alpha)
        ring = QRectF(-side / 2 + stroke / 2, -side / 2 + stroke / 2, side - stroke, side - stroke)
        track = QColor(ink)
        track.setAlphaF(ink.alphaF() * SPINNER_TRACK_ALPHA)
        painter.setPen(QPen(track, stroke))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(ring)
        # border-top-color: a quarter of the ring, centred on the top.
        painter.setPen(QPen(ink, stroke))
        painter.drawArc(ring, 45 * 16, 90 * 16)
        painter.restore()

    def _paint_check(
        self, painter: QPainter, centre: QPointF, height: float, ink: QColor, now: int
    ) -> None:
        alpha = self.check_alpha.at(now)
        drawn = self.check_drawn.at(now)
        if alpha <= 0.001 or drawn <= 0.001:
            return
        box = self._icon_box(centre, height, self.check_scale.at(now))
        unit = box.width() / 24.0
        points = [QPointF(box.left() + x * unit, box.top() + y * unit) for x, y in CHECK_POINTS]
        lengths = [math.dist((a.x(), a.y()), (b.x(), b.y())) for a, b in zip(points, points[1:])]
        remaining = sum(lengths) * drawn
        path = QPainterPath(points[0])
        for (a, b), length in zip(zip(points, points[1:]), lengths):
            if remaining <= 0:
                break
            share = min(1.0, remaining / length) if length else 1.0
            path.lineTo(a + (b - a) * share)
            remaining -= length
        painter.save()
        painter.setOpacity(painter.opacity() * alpha)
        pen = QPen(ink, CHECK_STROKE * unit)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.restore()

    def _paint_ring(self, painter: QPainter, shape: QRectF, centre: QPointF, now: int) -> None:
        if self._ring_at < 0 or now < self._ring_at or now >= self._ring_at + RING_MS:
            return
        progress = EASE.valueForProgress((now - self._ring_at) / RING_MS)
        painter.save()
        painter.setOpacity(RING_OPACITY * (1.0 - progress))
        scale = 1.0 + (RING_SCALE - 1.0) * progress
        painter.translate(centre)
        painter.scale(scale, scale)
        painter.translate(-centre)
        painter.setPen(QPen(theme.color("ok"), 2))
        painter.setBrush(Qt.NoBrush)
        outer = shape.adjusted(-1, -1, 1, 1)
        painter.drawRoundedRect(outer, outer.height() / 2, outer.height() / 2)
        painter.restore()
