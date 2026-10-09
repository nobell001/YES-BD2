"""Small building blocks of the new pages (cards, buttons, switches, rings…).

Painted widgets read the colours from :mod:`theme` at paint time, so a theme
switch only needs a repaint.
"""

from __future__ import annotations

import math
import re
import textwrap
from collections import OrderedDict
from collections.abc import Callable, Iterable

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGraphicsEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from src.ui.shell import icons, motion, theme
from src.ui.traditional import ui_text


def t(text: str) -> str:
    """Display text (Traditional Chinese when the app language asks for it)."""
    return ui_text(text)


def tf(template: str, **values) -> str:
    """Translate a sentence with blanks, then fill them (``{n} 项`` -> ``3 items``)."""
    return t(template).format(**values)


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_prop(widget: QWidget, name: str, value) -> None:
    if widget.property(name) != value:
        widget.setProperty(name, value)
        repolish(widget)


# ---------------------------------------------------------------- frames


# Room around a card's body for its soft shadow (left, top, right, bottom).
SHADOW_MARGINS = (6, 3, 6, 10)


class Card(QFrame):
    """A rounded card that paints its own soft shadow.

    The shadow is a few stacked translucent rounded rectangles drawn in a thin
    margin around the body, so it costs no more than the card itself (a
    QGraphicsDropShadowEffect would re-render every child on each update).
    """

    def __init__(self, parent=None, tone: str | None = None):
        super().__init__(parent)
        self.setProperty("card", True)
        if tone:
            self.setProperty("tone", tone)
        self.setContentsMargins(*SHADOW_MARGINS)

    def set_tone(self, tone: str | None) -> None:
        set_prop(self, "tone", tone or "")
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        left, top, right, bottom = SHADOW_MARGINS
        body = QRectF(self.rect()).adjusted(left, top, -right, -bottom)
        corner = float(theme.radius())
        painter.setPen(Qt.NoPen)
        # Soft and low: many faint layers, each a little wider and further
        # down, so the edge fades out instead of drawing a grey outline.
        strength = float(theme.shape("shadow"))
        layers = 8
        for step in range(layers, 0, -1):
            fade = 1 - (step - 1) / layers
            painter.setBrush(theme.color("shadow", strength * 0.25 * fade))
            grow = step * 0.6
            painter.drawRoundedRect(
                body.adjusted(-grow, -grow * 0.3 + 1, grow, grow * 1.1 + 1),
                corner + grow,
                corner + grow,
            )
        painter.setPen(QPen(self.edge_colour(), 1))
        painter.setBrush(theme.color("card"))
        painter.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), corner, corner)

    def edge_colour(self) -> QColor:
        line = "done_line" if self.property("tone") == "done" else "card_line"
        return theme.color(line)


def mix(a: QColor, b: QColor, amount: float) -> QColor:
    """``a`` moved ``amount`` (0..1) of the way towards ``b``."""
    amount = max(0.0, min(1.0, amount))
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * amount,
        a.greenF() + (b.greenF() - a.greenF()) * amount,
        a.blueF() + (b.blueF() - a.blueF()) * amount,
        a.alphaF() + (b.alphaF() - a.alphaF()) * amount,
    )


class Inset(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("inset", True)
        self.setAttribute(Qt.WA_StyledBackground, True)


class Separator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("sep", True)
        self.setFixedHeight(1)


def vbox(widget: QWidget | None = None, margins=(0, 0, 0, 0), spacing: int = 0) -> QVBoxLayout:
    layout = QVBoxLayout(widget) if widget is not None else QVBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def hbox(widget: QWidget | None = None, margins=(0, 0, 0, 0), spacing: int = 0) -> QHBoxLayout:
    layout = QHBoxLayout(widget) if widget is not None else QHBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


# ---------------------------------------------------------------- text


class Text(QLabel):
    """A label with a style role; long single-line text is cut with an ellipsis."""

    def __init__(
        self,
        text: str = "",
        role: str | None = None,
        parent=None,
        wrap: bool = False,
        elide: bool = False,
    ):
        super().__init__(parent)
        self._elide = elide and not wrap
        self._full = ""
        if role:
            self.setProperty("role", role)
        self.setWordWrap(wrap)
        self.setTextFormat(Qt.PlainText)
        self._rise: motion.Tween | None = None
        self.set_text(text)

    def animate_changes(self) -> None:
        """A new value fades in from a little below (big counts, not clocks)."""
        self._rise = motion.Tween(self, self._rise_step, 260, 1.0)

    def set_text(self, text: str) -> None:
        text = t(str(text))
        if text == self._full and self.text() in (text, ""):
            if self.text() == text or not self._elide:
                return
        if self._rise is not None and self._full and text != self._full and self.isVisible():
            self.setGraphicsEffect(_Rise(self))
            self._rise.go(0.0, animate=False)
            self._rise.go(1.0)
        self._full = text
        if self._elide:
            self.setToolTip(text if text else "")
            self._apply_elide()
        elif self.text() != text:
            self.setText(text)

    def full_text(self) -> str:
        return self._full

    def set_role(self, role: str) -> None:
        set_prop(self, "role", role)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        if self._elide:
            return QSize(0, hint.height())
        return hint

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        if self._elide:
            width = QFontMetrics(self.font()).horizontalAdvance(self._full) + 2
            return QSize(width, hint.height())
        return hint

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._elide:
            self._apply_elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if self._elide and event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._apply_elide()

    def _rise_step(self) -> None:
        effect = self.graphicsEffect()
        if not isinstance(effect, _Rise):
            return
        if self._rise.value >= 1.0:
            # Settled: drop the effect so the label draws exactly as before.
            self.setGraphicsEffect(None)
            return
        effect.progress = float(self._rise.value)
        effect.update()

    def _apply_elide(self) -> None:
        metrics = QFontMetrics(self.font())
        width = max(0, self.width())
        shown = self._full
        if width > 0 and metrics.horizontalAdvance(shown) > width:
            shown = metrics.elidedText(shown, Qt.ElideRight, width)
        if self.text() != shown:
            self.setText(shown)


class _Rise(QGraphicsEffect):
    """Draws its label faded and a few px low while a new value comes in."""

    RISE_PX = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0.0

    def draw(self, painter):
        painter.save()
        painter.setOpacity(self.progress)
        painter.translate(0, self.RISE_PX * (1 - self.progress))
        self.drawSource(painter)
        painter.restore()


# ---------------------------------------------------------------- buttons

_ICON_COLOUR = {
    "primary": "on_primary",
    "secondary": "ink",
    "ghost": "ghost_ink",
    "danger": "bad",
    "icon": "ink2",
    "flat": "ink2",
}


class Button(QPushButton):
    def __init__(
        self,
        text: str = "",
        kind: str = "secondary",
        icon_name: str | None = None,
        size: str | None = None,
        parent=None,
        on_click: Callable | None = None,
    ):
        super().__init__(t(text), parent)
        self._icon_name = icon_name
        self._kind = kind
        self.setProperty("kind", kind)
        if size:
            self.setProperty("size", size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        # The hover colour eases in and out; a press dips the button to 97 %.
        self._hover = motion.HoverFade(self, self.update)
        self._press = motion.Tween(self, self.update, 110, 0.0)
        self.pressed.connect(lambda: self._press.go(1.0))
        self.released.connect(lambda: self._press.go(0.0))
        self._refresh_icon()
        if on_click is not None:
            self.clicked.connect(lambda *_: on_click())

    def paintEvent(self, _event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rest = QStyleOptionButton(option)
        rest.state &= ~QStyle.State_MouseOver
        hot = QStyleOptionButton(option)
        hot.state |= QStyle.State_MouseOver
        hover = self._hover.value if self.isEnabled() else 0.0
        painter = QStylePainter(self)
        press = float(self._press.value)
        if press > 0:
            centre = QRectF(self.rect()).center()
            scale = 1.0 - 0.03 * press
            painter.translate(centre)
            painter.scale(scale, scale)
            painter.translate(-centre)
        if hover <= 0.0:
            painter.drawControl(QStyle.CE_PushButtonBevel, rest)
        elif hover >= 1.0:
            painter.drawControl(QStyle.CE_PushButtonBevel, hot)
        else:
            # Opaque hover colours lie over the resting look; the see-through
            # ones (ghost, icon) cross-fade so they end exactly as styled.
            crossfade = self._kind in ("ghost", "icon")
            painter.setOpacity(1.0 - hover if crossfade else 1.0)
            painter.drawControl(QStyle.CE_PushButtonBevel, rest)
            painter.setOpacity(hover)
            painter.drawControl(QStyle.CE_PushButtonBevel, hot)
            painter.setOpacity(1.0)
        painter.drawControl(QStyle.CE_PushButtonLabel, hot if hover >= 0.5 else rest)

    def set_label(self, text: str) -> None:
        text = t(text)
        if self.text() != text:
            self.setText(text)

    def set_icon_name(self, name: str | None) -> None:
        if name != self._icon_name:
            self._icon_name = name
            self._refresh_icon()

    def set_kind(self, kind: str) -> None:
        if kind != self._kind:
            self._kind = kind
            set_prop(self, "kind", kind)
            self._refresh_icon()

    def _refresh_icon(self) -> None:
        if not self._icon_name:
            self.setIcon(icons.QIcon())
            return
        name = _ICON_COLOUR.get(self._kind, "ink")
        colour = theme.color("ink3") if not self.isEnabled() else theme.color(name)
        size = 16 if self.property("size") != "sm" else 14
        self.setIcon(icons.icon(self._icon_name, colour, size, 2.1))
        self.setIconSize(QSize(size, size))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.EnabledChange, QEvent.StyleChange, QEvent.PaletteChange):
            self._refresh_icon()


# ---------------------------------------------------------------- icons


class IconTile(QWidget):
    """A small rounded square with a line icon (task icons in lists).

    ``kind`` is one of :data:`theme.KINDS`; every kind is violet in the round look.
    """

    def __init__(
        self,
        icon_name: str,
        size: int = 30,
        icon_size: int | None = None,
        parent=None,
        kind: str = "plain",
    ):
        super().__init__(parent)
        self._icon = icon_name
        self._size = size
        self._icon_size = icon_size or max(12, round(size * 0.56))
        self._kind = kind
        self._off = False
        self._hover: motion.HoverFade | None = None
        self.setFixedSize(size, size)

    def follow_hover(self, source: QWidget) -> None:
        """Let the icon grow a little while the mouse is over ``source`` (its row or card)."""
        self._hover = motion.HoverFade(source, self.update)

    def set_icon(self, name: str, kind: str | None = None) -> None:
        kind = kind or self._kind
        if (name, kind) != (self._icon, self._kind):
            self._icon, self._kind = name, kind
            self.update()

    def set_off(self, off: bool) -> None:
        """Greyed out (a task left out of the one-click run)."""
        if off != self._off:
            self._off = off
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._off:
            bg, fg = theme.color("inset"), theme.color("ink3")
        else:
            fg, bg = theme.kind_colours(self._kind)
        if theme.shape("round_icons"):
            # 淡紫 / 深色: a violet line icon on a soft violet circle.
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawEllipse(QRectF(0, 0, self._size, self._size))
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            radius = 5 if self._size >= 30 else 4
            painter.drawRoundedRect(QRectF(0, 0, self._size, self._size), radius, radius)
        # Hovered: the line icon grows by up to 16 % inside its tile.
        grow = 1.0 + 0.16 * (self._hover.value if self._hover else 0.0)
        side = self._icon_size * grow
        offset = (self._size - side) / 2
        box = QRectF(offset, offset, side, side)
        icons.paint(painter, box, self._icon, fg, 1.9)


class IconLabel(QWidget):
    """Just a tinted line icon."""

    def __init__(
        self, icon_name: str, size: int = 16, colour: str = "ink2", stroke: float = 2.0, parent=None
    ):
        super().__init__(parent)
        self._icon = icon_name
        self._colour = colour
        self._stroke = stroke
        self._size = size
        self.setFixedSize(size, size)

    def set_icon(self, name: str, colour: str | None = None) -> None:
        changed = name != self._icon or (colour is not None and colour != self._colour)
        self._icon = name
        if colour is not None:
            self._colour = colour
        if changed:
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        icons.paint(
            painter,
            QRectF(0, 0, self._size, self._size),
            self._icon,
            theme.color(self._colour),
            self._stroke,
        )


HINT_LINE_CHARS = 26  # Chinese/Japanese characters per hover-hint line
HINT_LINE_WIDTH = 52  # letters per line for space-separated languages
HINT_LINE_WIDTH_WIDE = 30  # Korean: words with spaces, but wide letters
_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")


def wrap_hint(text: str) -> str:
    """Break a long hint into short lines (the hover box does not wrap)."""
    lines = []
    for paragraph in str(text).strip().splitlines():
        if not _CJK.search(paragraph):
            width = HINT_LINE_WIDTH_WIDE if _HANGUL.search(paragraph) else HINT_LINE_WIDTH
            lines += textwrap.wrap(paragraph, width) or [""]
            continue
        while len(paragraph) > HINT_LINE_CHARS:
            lines.append(paragraph[:HINT_LINE_CHARS])
            paragraph = paragraph[HINT_LINE_CHARS:]
        lines.append(paragraph)
    return "\n".join(lines)


def attach_hint(widget: QWidget, text: str) -> bool:
    """Show ``text`` while the mouse rests on ``widget``; False when there is none.

    Uses the Fluent hover box (a real widget) instead of the system tooltip,
    which did not show on Leo's PC (2026-10-04: hovering the ⓘ showed nothing).
    """
    from qfluentwidgets import ToolTipFilter, ToolTipPosition

    text = str(text or "").strip()
    widget.setToolTip(wrap_hint(text) if text else "")
    if text and not getattr(widget, "_hint_filter", None):
        widget._hint_filter = ToolTipFilter(widget, 250, ToolTipPosition.TOP)
        widget.installEventFilter(widget._hint_filter)
    return bool(text)


class _Spin:
    """Shared 60 fps-ish timer for every spinning icon (one timer, many widgets)."""

    timer: QTimer | None = None
    angle = 0.0
    widgets: set = set()

    @classmethod
    def add(cls, widget) -> None:
        cls.widgets.add(widget)
        if cls.timer is None:
            cls.timer = QTimer()
            cls.timer.setInterval(33)
            cls.timer.timeout.connect(cls._tick)
        if not cls.timer.isActive():
            cls.timer.start()

    @classmethod
    def remove(cls, widget) -> None:
        cls.widgets.discard(widget)
        if not cls.widgets and cls.timer is not None:
            cls.timer.stop()

    @classmethod
    def _tick(cls) -> None:
        cls.angle = (cls.angle + 12.0) % 360.0
        for widget in list(cls.widgets):
            try:
                widget.update()
            except RuntimeError:
                cls.widgets.discard(widget)


class StateIcon(QWidget):
    """done / skip / fail / wait / run (spinning) marker for a task row."""

    ICONS = {
        "done": ("circle-check", "ok"),
        "skip": ("circle-minus", "skip"),
        "fail": ("circle-x", "bad"),
        "wait": ("circle-dashed", "ink3"),
        "run": ("loader-circle", "run"),
        "off": ("circle-dashed", "line2"),
    }

    def __init__(self, state: str = "wait", size: int = 17, parent=None, colour: str | None = None):
        super().__init__(parent)
        self._state = state
        self._size = size
        self._colour = colour
        self.setFixedSize(size, size)
        self._sync_spin()

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self._sync_spin()
            self.update()

    def _sync_spin(self) -> None:
        if self._state == "run" and self.isVisible():
            _Spin.add(self)
        else:
            _Spin.remove(self)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_spin()

    def hideEvent(self, event):
        _Spin.remove(self)
        super().hideEvent(event)

    def paintEvent(self, _event):
        name, colour = self.ICONS.get(self._state, self.ICONS["wait"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._state == "run":
            painter.translate(self._size / 2, self._size / 2)
            painter.rotate(_Spin.angle)
            painter.translate(-self._size / 2, -self._size / 2)
        colour = self._colour or colour
        icons.paint(painter, QRectF(0, 0, self._size, self._size), name, theme.color(colour), 2.2)


class Spinner(StateIcon):
    def __init__(self, size: int = 14, parent=None, colour: str | None = None):
        super().__init__("run", size, parent, colour)


# ---------------------------------------------------------------- toggle


class Toggle(QAbstractButton):
    """An on/off switch (the primary colour when on)."""

    def __init__(self, checked: bool = False, parent=None, small: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._w, self._h = (32, 18) if small else (38, 22)
        self.setFixedSize(self._w, self._h)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def set_checked_quietly(self, checked: bool) -> None:
        if self.isChecked() == checked:
            return
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._anim.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:
        return QSize(self._w, self._h)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        on = theme.color("primary")
        off = theme.color("line2")
        mix = self._pos
        track = QColor(
            round(off.red() + (on.red() - off.red()) * mix),
            round(off.green() + (on.green() - off.green()) * mix),
            round(off.blue() + (on.blue() - off.blue()) * mix),
        )
        if not self.isEnabled():
            track.setAlphaF(0.45)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        radius = self._h / 2
        painter.drawRoundedRect(QRectF(0, 0, self._w, self._h), radius, radius)
        knob = self._h - 6
        x = 3 + (self._w - knob - 6) * self._pos
        painter.setBrush(theme.color("on_primary") if mix > 0.5 else QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, 3, knob, knob))


# ---------------------------------------------------------------- segmented


class Segmented(QFrame):
    """A row of options, one selected (for short drop-down settings)."""

    changed = Signal(str)

    def __init__(
        self,
        options: Iterable[str],
        current: str | None = None,
        parent=None,
        labels: dict[str, str] | None = None,
        accent: bool = False,
    ):
        super().__init__(parent)
        self.setProperty("segmented", True)
        # accent: the chosen option is filled violet, for a choice that
        # changes how a run plays (Leo 2026-10-06, 服装技能).
        self._accent = accent
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = hbox(self, (3, 3, 3, 3), 2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for option in options:
            button = QPushButton(t((labels or {}).get(option, option)), self)
            button.setProperty("seg", True)
            button.setProperty("segAccent", accent)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _checked=False, value=option: self._clicked(value))
            self._group.addButton(button)
            layout.addWidget(button)
            self._buttons[option] = button
            button.toggled.connect(lambda on, b=button: on and self._slide_to(b))
        # The chosen option's pill is painted here and slides between options.
        self._pill = motion.Tween(self, self.update, 220, QRectF())
        self.set_value(current)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def _checked(self) -> QPushButton | None:
        return next((b for b in self._buttons.values() if b.isChecked()), None)

    def _slide_to(self, button: QPushButton) -> None:
        # Slide from where the pill is drawn now: mid-slide, or on the option it left.
        if not self._pill.running():
            self._pill.value = QRectF(self._last.geometry()) if self._last else QRectF()
        self._last = button
        start = self._pill.value
        self._pill.go(QRectF(button.geometry()), animate=not start.isEmpty())

    _last: QPushButton | None = None

    def paintEvent(self, event):
        super().paintEvent(event)
        button = self._checked()
        if button is None:
            return
        rect = self._pill.value if self._pill.running() else QRectF(button.geometry())
        if rect.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._accent:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("accent"))
        else:
            painter.setPen(QPen(theme.color("line"), 1))
            painter.setBrush(theme.color("card"))
        corner = theme.seg_item_radius(rect.height())
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), corner, corner)

    def _clicked(self, value: str) -> None:
        self.changed.emit(value)

    def set_value(self, value: str | None) -> None:
        button = self._buttons.get(value) if value is not None else None
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_label(self, option: str, text: str) -> None:
        """New text for one option (already translated), e.g. with a count."""
        button = self._buttons.get(option)
        if button is not None and button.text() != text:
            button.setText(text)
            self.update()

    def value(self) -> str | None:
        for option, button in self._buttons.items():
            if button.isChecked():
                return option
        return None


# ---------------------------------------------------------------- check chip


class CheckBox(QAbstractButton):
    """A square check box with an optional text label to its right."""

    def __init__(self, text: str = "", checked: bool = False, parent=None, box: int = 16):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setText(t(text))
        self._box = box
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        # Checking fills the box and draws the tick in from the left.
        self._on = motion.Tween(self, self.update, 200, 1.0 if checked else 0.0)
        self.toggled.connect(lambda on: self._on.go(1.0 if on else 0.0))

    def set_checked_quietly(self, checked: bool) -> None:
        if self.isChecked() != checked:
            self.blockSignals(True)
            self.setChecked(checked)
            self.blockSignals(False)
            self._on.go(1.0 if checked else 0.0, animate=False)

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self.font())
        width = self._box + (8 + metrics.horizontalAdvance(self.text()) if self.text() else 0)
        return QSize(width + 2, max(self._box, metrics.height()) + 4)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - self._box) / 2
        rect = QRectF(0.5, y + 0.5, self._box - 1, self._box - 1)
        on = float(self._on.value)
        if on < 1.0:
            painter.setPen(QPen(theme.color("line2"), 1.2))
            painter.setBrush(theme.color("card"))
            painter.drawRoundedRect(rect, theme.corner(4, 6), theme.corner(4, 6))
        if on > 0.0:
            painter.save()
            painter.setOpacity(min(1.0, on * 1.6))
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("primary"))
            painter.drawRoundedRect(rect, theme.corner(4, 6), theme.corner(4, 6))
            inner = self._box - 4
            if self._on.target == 1.0 and on < 1.0:
                # Being checked: the tick is drawn in from the left.
                painter.setOpacity(1.0)
                reveal = max(0.0, (on - 0.25) / 0.75)
                painter.setClipRect(QRectF(0, 0, 2 + inner * reveal, self.height()))
            else:
                painter.setOpacity(on)
            icons.paint(
                painter, QRectF(2, y + 2, inner, inner), "check", theme.color("on_primary"), 3.2
            )
            painter.restore()
        if self.text():
            painter.setPen(theme.color("ink" if self.isEnabled() else "ink3"))
            painter.setFont(theme.body_font(self.font()))
            text_rect = QRectF(self._box + 8, 0, self.width() - self._box - 8, self.height())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())


# ---------------------------------------------------------------- progress


class Ring(QWidget):
    """Donut progress with 'done / total' in the middle."""

    def __init__(self, size: int = 112, width: int = 10, parent=None):
        super().__init__(parent)
        self._done = 0
        self._total = 0
        self._size = size
        self._width = width
        self._arc = motion.Tween(self, self.update, 320, 0.0)
        self.setFixedSize(size, size)

    def set_progress(self, done: int, total: int) -> None:
        if (done, total) != (self._done, self._total):
            self._done, self._total = done, total
            # The numbers change at once; the arc grows or shrinks to them.
            self._arc.go(min(1.0, done / total) if total > 0 and done > 0 else 0.0)
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        inset = self._width / 2 + 1
        rect = QRectF(inset, inset, self._size - 2 * inset, self._size - 2 * inset)
        full = self._total and self._done >= self._total
        arc = theme.color("ok") if full else theme.color("primary")
        pen = QPen(theme.color("track"), self._width)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        if self._arc.value > 0:
            span = -360.0 * float(self._arc.value)
            pen = QPen(arc, self._width)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, int(span * 16))
        big = QFont(self.font())
        big.setPixelSize(round(self._size * 0.27))
        big.setBold(True)
        small = theme.body_font(self.font())
        small.setPixelSize(max(11, round(self._size * 0.12)))
        done_text = str(self._done)
        total_text = f"/ {self._total}"
        big_w = QFontMetrics(big).horizontalAdvance(done_text)
        small_w = QFontMetrics(small).horizontalAdvance(total_text)
        x = (self._size - big_w - small_w - 4) / 2
        base = self._size / 2 + QFontMetrics(big).capHeight() / 2
        painter.setPen(theme.color("ink"))
        painter.setFont(big)
        painter.drawText(QPointF(x, base), done_text)
        painter.setPen(theme.color("ink3"))
        painter.setFont(small)
        painter.drawText(QPointF(x + big_w + 4, base), total_text)


class SegBar(QWidget):
    """One segment per task: done green, skip grey, fail red, run accent, wait track."""

    def __init__(self, parent=None, height: int = 8):
        super().__init__(parent)
        self._states: list[str] = []
        self._before: list[str] = []
        # A segment that changes state fades to its new colour.
        self._fade = motion.Tween(self, self.update, 260, 1.0)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_states(self, states: list[str]) -> None:
        if states != self._states:
            same_count = len(states) == len(self._states)
            self._before = self._states if same_count else list(states)
            self._states = list(states)
            self._fade.go(0.0, animate=False)
            self._fade.go(1.0, animate=same_count)

    def paintEvent(self, _event):
        if not self._states:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gap = 3.0
        count = len(self._states)
        width = (self.width() - gap * (count - 1)) / count
        colours = {
            "done": theme.color("ok"),
            "skip": theme.color("skip"),
            "fail": theme.color("bad"),
            "run": theme.color("accent"),
            "wait": theme.color("track"),
        }
        painter.setPen(Qt.NoPen)
        fade = float(self._fade.value)
        for index, state in enumerate(self._states):
            colour = colours.get(state, colours["wait"])
            before = self._before[index] if index < len(self._before) else state
            if fade < 1.0 and before != state:
                colour = mix(colours.get(before, colours["wait"]), colour, fade)
            painter.setBrush(colour)
            x = index * (width + gap)
            painter.drawRoundedRect(
                QRectF(x, 0, width, self.height()), theme.corner(2), theme.corner(2)
            )


class Bar(QWidget):
    """A thin progress bar."""

    def __init__(self, parent=None, height: int = 6, colour: str = "primary"):
        super().__init__(parent)
        self._value = 0.0
        self._colour = colour
        # What is drawn: eases to each new value while the bar is on screen.
        self._shown = motion.Tween(self, self.update, 320, 0.0)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: float, colour: str | None = None) -> None:
        value = max(0.0, min(1.0, float(value)))
        if value != self._value or (colour and colour != self._colour):
            self._value = value
            if colour:
                self._colour = colour
            self._shown.go(value)
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        radius = self.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("track"))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        shown = float(self._shown.value)
        if shown > 0:
            painter.setBrush(theme.color(self._colour))
            width = max(self.height(), self.width() * shown)
            painter.drawRoundedRect(QRectF(0, 0, width, self.height()), radius, radius)


class WeekDots(QWidget):
    """Seven squares, oldest first: done (green), failed (red) or no run."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._days: list = [None] * 7
        self.setFixedSize(7 * 12 + 6 * 4, 12)

    def set_days(self, days: list) -> None:
        if days != self._days:
            self._days = list(days)
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for index, day in enumerate(self._days[-7:]):
            if day is True:
                painter.setBrush(theme.color("ok"))
            elif day is False:
                painter.setBrush(theme.color("bad"))
            else:
                painter.setBrush(theme.color("track"))
            painter.drawRoundedRect(QRectF(index * 16, 0, 12, 12), theme.corner(3), theme.corner(3))


# ---------------------------------------------------------------- pictures


_FITTED: OrderedDict = OrderedDict()
_FITTED_MAX = 600


def fitted(pixmap: QPixmap, width: float, height: float, ratio: float) -> QPixmap:
    """``pixmap`` scaled smoothly to fit ``width`` x ``height`` (logical px), cached.

    Smooth scaling inside paint events redid the work on every repaint, which
    made pages with many pictures slow at 4K; the cache keeps the result per
    picture, size and screen scale.
    """
    size = pixmap.size().scaled(
        QSize(max(1, round(width)), max(1, round(height))), Qt.KeepAspectRatio
    )
    key = (pixmap.cacheKey(), size.width(), size.height(), ratio)
    hit = _FITTED.get(key)
    if hit is not None:
        _FITTED.move_to_end(key)
        return hit
    scaled = pixmap.scaled(
        max(1, round(size.width() * ratio)),
        max(1, round(size.height() * ratio)),
        Qt.IgnoreAspectRatio,
        Qt.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(ratio)
    _FITTED[key] = scaled
    if len(_FITTED) > _FITTED_MAX:
        _FITTED.popitem(last=False)
    return scaled


def draw_fitted(painter: QPainter, rect: QRectF, pixmap: QPixmap, ratio: float) -> None:
    """Draw ``pixmap`` centred in ``rect``, keeping its aspect (cached scaling)."""
    scaled = fitted(pixmap, rect.width(), rect.height(), ratio)
    w = scaled.width() / ratio
    h = scaled.height() / ratio
    painter.drawPixmap(
        QPointF(rect.x() + (rect.width() - w) / 2, rect.y() + (rect.height() - h) / 2), scaled
    )


def _grey(image: QImage) -> QImage:
    grey = image.convertToFormat(QImage.Format_ARGB32)
    for y in range(grey.height()):
        for x in range(grey.width()):
            pixel = grey.pixelColor(x, y)
            value = round(pixel.red() * 0.3 + pixel.green() * 0.59 + pixel.blue() * 0.11)
            grey.setPixelColor(x, y, QColor(value, value, value, pixel.alpha()))
    return grey


class Picture(QWidget):
    """A picture scaled to fit (keeps its aspect), optionally dimmed."""

    clicked = Signal()

    def __init__(
        self,
        path: str | None = None,
        parent=None,
        dim: bool = False,
        fixed: QSize | None = None,
        radius: float = 0,
        background: str | None = None,
    ):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._grey = QPixmap()
        # The picture scaled to the widget, kept until the size or look changes:
        # scaling in every paint made the 跑图/跑商 pages slow to scroll at 4K.
        self._scaled: tuple[tuple, QPixmap] | None = None
        self._dim = dim
        self._radius = radius
        self._background = background
        if fixed is not None:
            self.setFixedSize(fixed)
        if path:
            self.set_path(path)

    def set_path(self, path: str | None) -> None:
        self._pixmap = QPixmap(path) if path else QPixmap()
        self._grey = QPixmap()
        self._scaled = None
        self.update()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._grey = QPixmap()
        self._scaled = None
        self.update()

    def set_dim(self, dim: bool) -> None:
        if dim != self._dim:
            self._dim = dim
            self.update()

    def has_picture(self) -> bool:
        return not self._pixmap.isNull()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._radius:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
            painter.setClipPath(path)
        if self._background:
            painter.fillRect(self.rect(), theme.color(self._background))
        if self._pixmap.isNull():
            return
        source = self._pixmap
        if self._dim:
            if self._grey.isNull():
                self._grey = QPixmap.fromImage(_grey(self._pixmap.toImage()))
            source = self._grey
            painter.setOpacity(0.5)
        size = source.size().scaled(self.size(), Qt.KeepAspectRatio)
        if size.isEmpty():
            return
        ratio = self.devicePixelRatioF()
        key = (size.width(), size.height(), ratio, self._dim)
        if self._scaled is None or self._scaled[0] != key:
            scaled = source.scaled(
                round(size.width() * ratio),
                round(size.height() * ratio),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(ratio)
            self._scaled = (key, scaled)
        x = (self.width() - size.width()) / 2
        y = (self.height() - size.height()) / 2
        painter.drawPixmap(round(x), round(y), self._scaled[1])


# ---------------------------------------------------------------- layouts


class TileGrid(QLayout):
    """Equal-width columns, as many as fit (CSS ``repeat(auto-fill, minmax())``)."""

    def __init__(
        self,
        parent=None,
        min_width: int = 120,
        spacing: int = 10,
        max_columns: int | None = None,
        row_height: int | None = None,
    ):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._min = min_width
        self._space = spacing
        self._max = max_columns
        self._row_height = row_height
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

    def sizeHint(self) -> QSize:
        width = self._min * 3 + self._space * 2
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self) -> QSize:
        margins = self.contentsMargins()
        return QSize(self._min + margins.left() + margins.right(), 0)

    def columns_for(self, width: int) -> int:
        columns = max(1, (width + self._space) // (self._min + self._space))
        if self._max:
            columns = min(columns, self._max)
        return columns

    def _visible(self) -> list[QLayoutItem]:
        return [item for item in self._items if not (item.widget() and item.widget().isHidden())]

    def _layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        items = self._visible()
        if not items:
            return margins.top() + margins.bottom()
        columns = self.columns_for(area.width())
        width = (area.width() - self._space * (columns - 1)) / columns
        y = area.y()
        for start in range(0, len(items), columns):
            row = items[start : start + columns]
            heights = []
            for item in row:
                if self._row_height:
                    heights.append(self._row_height)
                elif item.hasHeightForWidth():
                    heights.append(item.heightForWidth(int(width)))
                else:
                    heights.append(item.sizeHint().height())
            height = max(heights)
            if not test_only:
                for index, item in enumerate(row):
                    x = area.x() + index * (width + self._space)
                    item.setGeometry(QRect(round(x), y, round(width), height))
            y += height + self._space
        return y - self._space - rect.y() + margins.bottom()


def grid_container(
    min_width: int, spacing: int = 10, max_columns: int | None = None, row_height: int | None = None
) -> tuple[QWidget, TileGrid]:
    container = QWidget()
    grid = TileGrid(container, min_width, spacing, max_columns, row_height)
    policy = container.sizePolicy()
    policy.setHeightForWidth(True)
    container.setSizePolicy(policy)
    return container, grid


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def fmt_duration(seconds: float | None) -> str:
    """'41 秒' / '3 分 12 秒' / '1 小时 5 分'."""
    if seconds is None:
        return "-"
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return tf("{n} 秒", n=seconds)
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return tf("{m} 分 {s} 秒", m=minutes, s=sec) if sec else tf("{m} 分", m=minutes)
    hours, minutes = divmod(minutes, 60)
    return tf("{h} 小时 {m} 分", h=hours, m=minutes)


def fmt_clock(seconds: float | None) -> str:
    """'0:41' / '3:12' / '1:05:00' for running timers."""
    if seconds is None:
        return ""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, sec = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"


def fmt_minutes(seconds: float | None) -> str:
    """Rough 'about N minutes' for estimates."""
    if seconds is None:
        return ""
    minutes = max(1, math.ceil(seconds / 60))
    return tf("{n} 分钟", n=minutes)
