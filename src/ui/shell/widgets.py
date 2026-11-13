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
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
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
    shown = ui_text(text)
    if shown == text and text:
        # A report note with numbers in it (note_templates).
        from src.ui.note_templates import translate

        return translate(text, ui_text) or shown
    return shown


def tf(template: str, **values) -> str:
    """Translate a sentence with blanks, then fill them (``{n} 项`` -> ``3 items``)."""
    return t(template).format(**values)


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    # A re-polish alone keeps the old padding (the contents margins) of a
    # sheet set on a parent: a toned pill kept 10 px on the left, so its dot
    # sat on the first word (2026-11-09 跑图 「一键日常里会跑」).  Setting the
    # widget's own sheet again makes Qt work the padding out anew.
    own = widget.styleSheet()
    widget.setStyleSheet(own + " ")
    widget.setStyleSheet(own)
    widget.updateGeometry()
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
    """A hairline.  ``indent`` starts it that far in from the left, so rows
    with an icon are split under their text only (oink-ui Group, 2026-11-09)."""

    def __init__(self, parent=None, indent: int = 0):
        super().__init__(parent)
        self._indent = indent
        if indent:
            self.setFixedHeight(1)
        else:
            self.setProperty("sep", True)
            self.setFixedHeight(1)

    def paintEvent(self, event):
        if not self._indent:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.fillRect(
            QRectF(self._indent, 0, self.width() - self._indent, 1), theme.color("line")
        )


class Alert(QFrame):
    """A soft coloured box for a notice: ``tone`` is warn, bad, ok or info
    (oink-ui Alert, Leo 2026-11-09)."""

    def __init__(self, tone: str = "info", parent=None):
        super().__init__(parent)
        self.setProperty("alert", tone)
        self.setAttribute(Qt.WA_StyledBackground, True)


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

    _DOT = {"ok": "ok", "run": "pill_run_ink", "warn": "warn", "bad": "bad"}

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.property("role") != "pill":
            return
        colour = self._DOT.get(str(self.property("tone") or ""))
        if colour is None or not self.text():
            return
        # oink-ui Badge: a small dot before the words (2026-11-09).
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color(colour))
        painter.drawEllipse(QPointF(11.5, self.height() / 2), 3.5, 3.5)

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
    "chip": "ink2",
    "stepper": "ink",
    "select": "ink2",
}


class Button(QPushButton):
    # Space between the icon and the text.  Qt's own is 4 px, which looks
    # glued with the line icons, whose strokes reach their box edge.
    ICON_GAP = 7
    QT_ICON_GAP = 4

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
        # The hover colour eases in and out; a press dips the button to 95.5 %
        # and it springs back a little past its size (oink-ui, 2026-11-09).
        self._hover = motion.HoverFade(self, self.update)
        self._press = motion.Tween(self, self.update, 260, 0.0, QEasingCurve.OutBack)
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
        if press != 0:
            centre = QRectF(self.rect()).center()
            scale = 1.0 - 0.045 * press
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
        label = hot if hover >= 0.5 else rest
        # The icon, text, size and box come from the button, the same values
        # initStyleOption copied into the option: reading them back from the
        # option's fields can return a stale object of another type (UI check
        # 2026-10-28: label.rect was a QWidgetItem, and the paint failed).
        icon, text = self.icon(), self.text()
        if icon.isNull() or not text:
            painter.drawControl(QStyle.CE_PushButtonLabel, label)
            return
        # 2026-10-22 check: 「▷一键完成日常」 looked glued, so the icon and
        # the text are placed here with ICON_GAP, centred together as Qt would.
        icon_size = self.iconSize()
        text_width = self.fontMetrics().horizontalAdvance(text)
        shift = (icon_size.width() + self.ICON_GAP) / 2
        left = (self.width() - icon_size.width() - self.ICON_GAP - text_width) / 2
        mode = QIcon.Normal if self.isEnabled() else QIcon.Disabled
        pixmap = icon.pixmap(icon_size, self.devicePixelRatioF(), mode)
        top = (self.height() - icon_size.height()) / 2
        painter.drawPixmap(QPointF(left, top), pixmap)
        label.icon = QIcon()
        label.rect = self.rect().translated(round(shift), 0)
        painter.drawControl(QStyle.CE_PushButtonLabel, label)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        if not self.icon().isNull() and self.text():
            hint.setWidth(hint.width() + self.ICON_GAP - self.QT_ICON_GAP)
        return hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        if not self.icon().isNull() and self.text():
            hint.setWidth(hint.width() + self.ICON_GAP - self.QT_ICON_GAP)
        return hint

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


def shell_buttons(box) -> None:
    """Put the tool's own buttons on a Fluent ``MessageBox``/``MessageBoxBase``
    in place of its teal and grey ones (2026-10-22 check: they matched
    nothing else in the tool).  Call after setting the buttons' texts; a
    button hidden by then stays away.  A press clicks the Fluent button, so
    the box's own checks and answers stay as they were."""
    for fluent, kind in ((box.yesButton, "primary"), (box.cancelButton, "secondary")):
        if fluent.isHidden():
            continue
        own = Button(fluent.text(), kind, on_click=fluent.click)
        own.setStyleSheet(theme.style_sheet())
        box.buttonLayout.addWidget(own, 1)
        fluent.hide()


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


def attach_hint(widget: QWidget, text: str, below: bool = False) -> bool:
    """Show ``text`` while the mouse rests on ``widget``; False when there is none.

    Uses the Fluent hover box (a real widget) instead of the system tooltip,
    which did not show on Leo's PC (2026-10-04: hovering the ⓘ showed nothing).
    """
    from qfluentwidgets import ToolTipFilter, ToolTipPosition

    text = str(text or "").strip()
    widget.setToolTip(wrap_hint(text) if text else "")
    if text and not getattr(widget, "_hint_filter", None):
        position = ToolTipPosition.BOTTOM if below else ToolTipPosition.TOP
        widget._hint_filter = ToolTipFilter(widget, 250, position)
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

    PAD = 1

    def __init__(self, checked: bool = False, parent=None, small: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        # oink-ui switch (Leo 2026-11-09): a wider track, a pill thumb that
        # stretches while held, and a small spring when it lands.
        prefix = "toggle_sm" if small else "toggle"
        self._w, self._h = theme.size(f"{prefix}_w"), theme.size(f"{prefix}_h")
        # One spare pixel on every side: at 125 % / 150 % the track's
        # rounded ends fell on a part pixel and its left edge looked cut
        # (Leo 2026-11-09 「膠囊開關外側最左邊 也統一都被切到」).
        self.setFixedSize(self._w + 2 * self.PAD, self._h + 2 * self.PAD)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(300)
        spring = QEasingCurve(QEasingCurve.OutBack)
        spring.setOvershoot(1.2)
        self._anim.setEasingCurve(spring)
        self.toggled.connect(self._animate)
        self._held = motion.Tween(self, self.update, 120, 0.0)
        self.pressed.connect(lambda: self._held.go(1.0))
        self.released.connect(lambda: self._held.go(0.0))

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
        return QSize(self._w + 2 * self.PAD, self._h + 2 * self.PAD)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self.PAD, self.PAD)
        on = theme.color("primary")
        off = theme.color("well2")
        mix = max(0.0, min(1.0, self._pos))
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
        # A thumb with room around it (Leo 2026-11-09: the first one, 3 px in
        # from the edge, 「裡面那顆太大」).
        inset = 4
        knob_h = self._h - inset * 2
        knob_w = knob_h  # round at rest, stretches into a pill while held
        held = float(self._held.value) * 4
        travel = self._w - knob_w - inset * 2 - held
        x = inset + travel * self._pos
        painter.setBrush(theme.color("knob" if self.isEnabled() else "raised"))
        painter.drawRoundedRect(QRectF(x, inset, knob_w + held, knob_h), knob_h / 2, knob_h / 2)


class OptionSwitch(Button):
    """A small button that says the current choice; a click switches to the
    other one (Leo 2026-11-06 「ui小一點 然後用切換的」「文字要包含在按鈕裡」).
    Same calls as :class:`Segmented`: ``value``, ``set_value``, ``changed``.
    ``labels`` maps a stored value to the shorter words on the button."""

    changed = Signal(str)

    def __init__(
        self,
        off: str,
        on: str,
        current: str | None = None,
        parent=None,
        labels: dict[str, str] | None = None,
    ):
        self._options = (off, on)
        self._labels = dict(labels or {})
        self._value = on if current == on else off
        super().__init__(self._label(self._value), "secondary", "arrow-left-right", "sm", parent)
        self.clicked.connect(self._flip)

    def _label(self, value: str) -> str:
        return self._labels.get(value, value)

    def _flip(self) -> None:
        self.set_value(self._options[0] if self._value == self._options[1] else self._options[1])

    def value(self) -> str:
        return self._value

    def set_value(self, value: str | None, quiet: bool = False) -> None:
        value = value if value in self._options else self._options[0]
        if value == self._value:
            return
        self._value = value
        self.setText(t(self._label(value)))
        if not quiet:
            self.changed.emit(value)

    def _clicked(self, value: str) -> None:
        self.set_value(value)


class KeyCap(QAbstractButton):
    """A key drawn as a keyboard key (oink-ui Kbd, Leo 2026-11-09); a click
    opens a menu of ``options``.  Same calls as a ComboBox picker:
    ``value``, ``set_value`` and ``changed``.  ``labels`` maps a stored value
    to the words shown (e.g. 「无」 in the UI language)."""

    changed = Signal(str)

    def __init__(self, options: Iterable[str], current: str, parent=None, labels=None):
        super().__init__(parent)
        self._options = list(options)
        self._labels = dict(labels or {})
        self._value = current if current in self._options else self._options[0]
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self._press = motion.Tween(self, self.update, 160, 0.0)
        self.pressed.connect(lambda: self._press.go(1.0))
        self.released.connect(lambda: self._press.go(0.0))
        self.clicked.connect(self._open_menu)
        font = QFont(self.font())
        font.setPixelSize(theme.size("text_lg"))
        self.setFont(font)
        self._refresh()

    def _label(self, value: str) -> str:
        return t(self._labels.get(value, value))

    def _refresh(self) -> None:
        self.setText(self._label(self._value))
        self.setFixedSize(self.sizeHint())
        self.update()

    def value(self) -> str:
        return self._value

    def options(self) -> list[str]:
        return list(self._options)

    def set_value(self, value: str, quiet: bool = True) -> None:
        if value not in self._options or value == self._value:
            return
        self._value = value
        self._refresh()
        if not quiet:
            self.changed.emit(value)

    def _open_menu(self) -> None:
        from qfluentwidgets import Action, RoundMenu

        menu = RoundMenu(parent=self)
        for option in self._options:
            action = Action(self._label(option), menu)
            action.setCheckable(True)
            action.setChecked(option == self._value)
            action.triggered.connect(lambda _on=False, o=option: self.set_value(o, quiet=False))
            menu.addAction(action)
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self.font())
        widest = max(metrics.horizontalAdvance(self._label(o)) for o in self._options)
        height = theme.size("control_sm")
        return QSize(max(height + 6, widest + 22), height)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -1.5)
        drop = 1.0 * float(self._press.value)
        rect.translate(0, drop)
        corner = float(theme.size("corner_small"))
        # The key's lower edge: a darker line under it, gone while pressed.
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("hair2"))
        painter.drawRoundedRect(rect.translated(0, 1.5 - drop), corner, corner)
        hot = self.underMouse() and self.isEnabled()
        painter.setPen(QPen(theme.color("primary" if hot else "hair"), 1))
        painter.setBrush(theme.color("well"))
        painter.drawRoundedRect(rect, corner, corner)
        painter.setPen(theme.color("ink" if self.isEnabled() else "ink3"))
        painter.setFont(theme.body_font(self.font()))
        painter.drawText(rect, Qt.AlignCenter, self.text())


class Stepper(QFrame):
    """A number between a − and a + on one rounded well (oink-ui NumberInput,
    Leo 2026-11-09); the number itself can also be typed.  Takes the calls
    the pages used on Fluent's SpinBox: ``setRange``, ``setSingleStep``,
    ``setValue``, ``value``, ``setSpecialValueText`` and ``valueChanged``."""

    valueChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("stepper", True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._low, self._high, self._step, self._value = 0, 99, 1, 0
        self._special = ""
        layout = hbox(self, (3, 3, 3, 3), 0)
        self._minus = Button("", "stepper", "minus", "sm", self, on_click=lambda: self._nudge(-1))
        self._plus = Button("", "stepper", "plus", "sm", self, on_click=lambda: self._nudge(1))
        from PySide6.QtWidgets import QLineEdit

        self._edit = QLineEdit(self)
        self._edit.setObjectName("stepperEdit")
        self._edit.setAlignment(Qt.AlignCenter)
        self._edit.setFrame(False)
        self._edit.editingFinished.connect(self._typed)
        layout.addWidget(self._minus)
        layout.addWidget(self._edit, 1)
        layout.addWidget(self._plus)
        self.setFixedHeight(theme.size("control_md"))
        self.setFixedWidth(theme.size("control_md") * 4)
        self._show()

    def setRange(self, low: int, high: int) -> None:
        self._low, self._high = int(low), int(high)
        self.setValue(self._value)

    def setMinimum(self, low: int) -> None:
        self.setRange(low, self._high)

    def setMaximum(self, high: int) -> None:
        self.setRange(self._low, high)

    def setSingleStep(self, step: int) -> None:
        self._step = max(1, int(step))

    def setSpecialValueText(self, text: str) -> None:
        self._special = text
        self._show()

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        value = max(self._low, min(self._high, int(value)))
        changed = value != self._value
        self._value = value
        self._show()
        if changed and not self.signalsBlocked():
            self.valueChanged.emit(value)

    def _nudge(self, direction: int) -> None:
        self.setValue(self._value + direction * self._step)

    def _typed(self) -> None:
        text = self._edit.text().strip()
        if self._special and text == self._special:
            self.setValue(self._low)
            return
        try:
            self.setValue(int(text))
        except ValueError:
            self._show()

    def _show(self) -> None:
        shown = self._special if self._special and self._value == self._low else str(self._value)
        if self._edit.text() != shown:
            self._edit.setText(shown)
        self._minus.setEnabled(self._value > self._low)
        self._plus.setEnabled(self._value < self._high)


class _SliderTrack(QWidget):
    """The bar of ``Slider``: a well with the primary colour up to a round
    knob.  Click anywhere to jump there, drag, arrow keys step; the wheel
    only moves it once it has focus, so scrolling a page never changes a
    setting by accident."""

    def __init__(self, owner: "Slider"):
        super().__init__(owner)
        self._owner = owner
        knob = theme.size("slider_knob")
        # Room for the knob (and its grown, hovered size) at both ends.
        self.PAD = knob // 2 + 3
        self.setMinimumWidth(120)
        self.setFixedHeight(theme.size("control_md"))
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self._hover = motion.HoverFade(self, self.update)
        self._held = motion.Tween(self, self.update, 260, 0.0, QEasingCurve.OutBack)
        self._pos = motion.Tween(self, self.update, 180, 0.0)
        self._drag = False
        self._key_focus = False  # the ring shows for Tab focus, not a click

    def sizeHint(self) -> QSize:
        return QSize(180, theme.size("control_md"))

    def _span(self) -> tuple[float, float]:
        return self.PAD, max(1.0, self.width() - 2 * self.PAD)

    def _fraction_at(self, x: float) -> float:
        left, width = self._span()
        return max(0.0, min(1.0, (x - left) / width))

    def show_fraction(self, fraction: float, animate: bool) -> None:
        self._pos.go(fraction, animate=animate and not self._drag)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self._drag = True
        self._held.go(1.0)
        self._owner._slide_to(self._fraction_at(event.position().x()), jump=True)

    def mouseMoveEvent(self, event):
        if self._drag:
            self._owner._slide_to(self._fraction_at(event.position().x()), jump=False)

    def mouseReleaseEvent(self, event):
        if self._drag:
            self._drag = False
            self._held.go(0.0)
            self._owner._settle()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()  # let the page scroll
            return
        steps = 1 if event.angleDelta().y() > 0 else -1 if event.angleDelta().y() < 0 else 0
        self._owner._nudge(steps)

    def keyPressEvent(self, event):
        key = event.key()
        moves = {
            Qt.Key_Left: -1,
            Qt.Key_Down: -1,
            Qt.Key_Right: 1,
            Qt.Key_Up: 1,
            Qt.Key_PageDown: -10,
            Qt.Key_PageUp: 10,
        }
        if key in moves:
            self._owner._nudge(moves[key])
        elif key == Qt.Key_Home:
            self._owner.setValue(self._owner.minimum())
        elif key == Qt.Key_End:
            self._owner.setValue(self._owner.maximum())
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._key_focus = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        left, width = self._span()
        mid = self.height() / 2
        bar = theme.size("slider_track")
        fraction = max(0.0, min(1.0, float(self._pos.value)))
        x = left + width * fraction
        well = theme.color("well2")
        on = theme.color("primary")
        if not enabled:
            well.setAlphaF(0.6)
            on = theme.color("ink3")
        painter.setPen(Qt.NoPen)
        painter.setBrush(well)
        top = mid - bar / 2
        painter.drawRoundedRect(QRectF(left - bar / 2, top, width + bar, bar), bar / 2, bar / 2)
        painter.setBrush(on)
        painter.drawRoundedRect(QRectF(left - bar / 2, top, x - left + bar, bar), bar / 2, bar / 2)
        # The fixed stops (倍数's 1 2 4 5 8 10 20 40) as small dots.
        stops = self._owner._stop_fractions()
        if len(stops) > 1:
            for stop in stops:
                dot = theme.color("on_accent" if stop <= fraction else "ink3")
                dot.setAlphaF(0.55)
                painter.setBrush(dot)
                painter.drawEllipse(QPointF(left + width * stop, mid), 1.5, 1.5)
        knob = theme.size("slider_knob")
        hover = 0.5 * float(self._hover.value) if enabled else 0.0
        grow = 1.0 + 0.12 * max(float(self._held.value), hover)
        radius = knob / 2 * grow
        centre = QPointF(x, mid)
        if self.hasFocus() and self._key_focus and enabled:
            ring = theme.color("primary")
            ring.setAlphaF(0.28)
            painter.setBrush(ring)
            painter.drawEllipse(centre, radius + 4, radius + 4)
        shade = QColor(0, 0, 0, 46 if enabled else 20)
        painter.setBrush(shade)
        painter.drawEllipse(QPointF(x, mid + 1), radius, radius)
        painter.setBrush(theme.color("knob" if enabled else "raised"))
        painter.setPen(QPen(theme.color("hair2"), 1))
        painter.drawEllipse(centre, radius - 0.5, radius - 0.5)


class Slider(QWidget):
    """A number set by sliding, with the number shown (and typeable) in a
    small box at the right (oink-ui Slider, Leo 2026-11-09 「數字類可以用
    SLIDER 加顯示數字」).  Takes the calls of ``Stepper``: ``setRange``,
    ``setSingleStep``, ``setValue``, ``value``, ``setSpecialValueText`` and
    ``valueChanged``; plus ``setSuffix`` (the unit after the number),
    ``setStops`` (the knob snaps to these values only) and ``setDecimals``
    (a float setting).  ``valueChanged`` carries an int unless decimals > 0.
    """

    valueChanged = Signal(object)

    def __init__(self, parent=None, decimals: int = 0):
        super().__init__(parent)
        self._decimals = max(0, int(decimals))
        self._low, self._high = 0, 99
        self._step = 1 if not self._decimals else 10 ** -self._decimals
        self._value = self._low
        self._special = ""
        self._suffix = ""
        self._stops: list = []
        self._box_width = 0
        self._box_floor = 0  # same_box_width()
        layout = hbox(self, (0, 0, 0, 0), theme.size("gap_sm"))
        self.track = _SliderTrack(self)
        layout.addWidget(self.track, 1)
        self.box = QFrame(self)
        self.box.setProperty("stepper", True)
        self.box.setAttribute(Qt.WA_StyledBackground, True)
        self.box.setFixedHeight(theme.size("control_md"))
        inner = hbox(self.box, (10, 0, 10, 0), theme.size("gap_xs"))
        from PySide6.QtWidgets import QLineEdit

        self._edit = QLineEdit(self.box)
        self._edit.setObjectName("stepperEdit")
        self._edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._edit.setFrame(False)
        self._edit.setFocusPolicy(Qt.ClickFocus)
        self._edit.editingFinished.connect(self._typed)
        self.edit = self._edit  # the number box, typeable
        self._unit = Text("", "muted", self.box)
        self._unit.hide()
        inner.addWidget(self._edit, 1)
        inner.addWidget(self._unit)
        layout.addWidget(self.box)
        self.setFixedHeight(theme.size("control_md"))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._fit_box()
        self._show(animate=False)

    # ---------------------------------------------------------------- API
    def setRange(self, low, high) -> None:
        self._low, self._high = self._cast(low), self._cast(max(low, high))
        self._fit_box()
        self.setValue(self._value)
        self._show(animate=False)

    def setMinimum(self, low) -> None:
        self.setRange(low, self._high)

    def setMaximum(self, high) -> None:
        self.setRange(self._low, high)

    def minimum(self):
        return self._low

    def maximum(self):
        return self._high

    def setSingleStep(self, step) -> None:
        if self._decimals:
            self._step = max(float(step), 10**-self._decimals)
        else:
            self._step = max(1, int(step))

    def setDecimals(self, decimals: int) -> None:
        self._decimals = max(0, int(decimals))
        self._fit_box()
        self._show(animate=False)

    def setSpecialValueText(self, text: str) -> None:
        self._special = t(text) if text else ""
        self._fit_box()
        self._show(animate=False)

    def setSuffix(self, unit: str) -> None:
        self._suffix = unit
        self._unit.set_text(unit)
        self._unit.setVisible(bool(unit))
        self._fit_box()
        self._show(animate=False)

    def setStops(self, values) -> None:
        self._stops = sorted({self._cast(v) for v in values if self._low <= v <= self._high})
        self.track.update()

    def value(self):
        return self._value

    @staticmethod
    def same_box_width(sliders) -> None:
        """Sliders stacked in one panel get one number-box width, so their
        bars start and end on the same lines."""
        sliders = list(sliders)
        if not sliders:
            return
        widest = max(slider._box_width for slider in sliders)
        for slider in sliders:
            slider._box_floor = widest
            slider._fit_box()

    def setValue(self, value) -> None:
        value = self._cast(max(self._low, min(self._high, value)))
        changed = value != self._value
        self._value = value
        self._show(animate=True)
        if changed and not self.signalsBlocked():
            self.valueChanged.emit(value)

    # ------------------------------------------------------------ inside
    def _cast(self, value):
        if self._decimals:
            return round(float(value), self._decimals)
        return int(round(float(value)))

    def _text(self, value) -> str:
        if self._special and value == self._low:
            return self._special
        if self._decimals:
            return f"{value:.{self._decimals}f}"
        return str(value)

    def _fit_box(self) -> None:
        """Wide enough for the longest value, so the box never jumps or cuts."""
        font = QFont(self.font())
        font.setPixelSize(theme.size("text_lg"))
        metrics = QFontMetrics(font)
        samples = [self._text(self._low), self._text(self._high)]
        if self._special:
            samples.append(self._special)
        widest = max(metrics.horizontalAdvance(sample) for sample in samples) + 6
        self._edit.setMinimumWidth(widest)
        unit = 0
        if self._suffix:
            unit_font = QFont(self.font())
            unit_font.setPixelSize(theme.size("text_sm"))
            unit = QFontMetrics(unit_font).horizontalAdvance(t(self._suffix))
            unit += theme.size("gap_xs") + 2
        self._box_width = max(theme.size("control_md") + 8, widest + unit + 20 + 2)
        self.box.setFixedWidth(max(self._box_width, self._box_floor))

    def _range(self) -> float:
        return float(self._high - self._low) or 1.0

    def _fraction_of(self, value) -> float:
        stops = self._stops
        if len(stops) > 1:
            if value <= stops[0]:
                return 0.0
            for index in range(1, len(stops)):
                if value <= stops[index]:
                    a, b = stops[index - 1], stops[index]
                    part = (value - a) / (b - a) if b != a else 0.0
                    return (index - 1 + part) / (len(stops) - 1)
            return 1.0
        return (value - self._low) / self._range()

    def _stop_fractions(self) -> list[float]:
        stops = self._stops
        if len(stops) > 1:
            return [index / (len(stops) - 1) for index in range(len(stops))]
        return []

    def _value_at(self, fraction: float):
        stops = self._stops
        if len(stops) > 1:
            return stops[round(fraction * (len(stops) - 1))]
        raw = self._low + fraction * self._range()
        steps = round((raw - self._low) / self._step)
        return self._low + steps * self._step

    def _slide_to(self, fraction: float, jump: bool) -> None:
        self.setValue(self._value_at(fraction))
        if not jump:
            self.track.show_fraction(self._fraction_of(self._value), animate=False)

    def _settle(self) -> None:
        self.track.show_fraction(self._fraction_of(self._value), animate=True)

    def _nudge(self, steps: int) -> None:
        if not steps:
            return
        stops = self._stops
        if len(stops) > 1:
            if steps > 0:
                ahead = [v for v in stops if v > self._value]
                target = ahead[min(len(ahead), steps) - 1] if ahead else stops[-1]
            else:
                behind = [v for v in stops if v < self._value]
                target = behind[max(-len(behind), steps)] if behind else stops[0]
            self.setValue(target)
            return
        if abs(steps) >= 10:
            size = max(self._step, self._range() / 10)
            if not self._decimals:
                size = max(self._step, int(round(size / self._step)) * self._step)
            self.setValue(self._value + (1 if steps > 0 else -1) * size)
            return
        self.setValue(self._value + steps * self._step)

    def _typed(self) -> None:
        text = self._edit.text().strip()
        if self._special and text == self._special:
            self.setValue(self._low)
            return
        try:
            self.setValue(float(text) if self._decimals else int(float(text)))
        except ValueError:
            pass
        # Too big, too small or not a number: show what was kept.
        self._edit.setText(self._text(self._value))

    def _show(self, animate: bool) -> None:
        shown = self._text(self._value)
        if self._edit.text() != shown and not self._edit.hasFocus():
            self._edit.setText(shown)
        elif self._edit.hasFocus() and self._edit.text() != shown and not self._edit.isModified():
            self._edit.setText(shown)
        special = bool(self._special) and self._value == self._low
        self._unit.setVisible(bool(self._suffix) and not special)
        self.track.show_fraction(self._fraction_of(self._value), animate=animate)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange:
            self.track.update()


class Select(Button):
    """A rounded button that shows the chosen option with a chevron; a click
    opens the list (oink-ui Select, Leo 2026-11-09).  Takes the calls the
    pages used on Fluent's ComboBox: ``addItem``, ``currentIndex``,
    ``setCurrentIndex``, ``currentText``, ``itemData`` and
    ``currentIndexChanged``."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__("", "select", None, None, parent)
        self._items: list[tuple[str, object]] = []
        self._index = -1
        self.setAttribute(Qt.WA_Hover, True)
        self.clicked.connect(self._open_menu)

    def paintEvent(self, _event):
        # Drawn here: the words at the left, the chevron at the right end.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hot = self.underMouse() and self.isEnabled()
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("fill_hover" if hot else "fill"))
        body = QRectF(self.rect())
        painter.drawRoundedRect(body, body.height() / 2, body.height() / 2)
        painter.setPen(theme.color("ink" if self.isEnabled() else "ink3"))
        painter.setFont(theme.body_font(self.font()))
        painter.drawText(
            body.adjusted(14, 0, -36, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text()
        )
        size = 14
        rect = QRectF(self.width() - size - 14, (self.height() - size) / 2, size, size)
        icons.paint(painter, rect, "chevron-down", theme.color("ink2"), 2.2)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        metrics = self.fontMetrics()
        widest = max((metrics.horizontalAdvance(text) for text, _ in self._items), default=0)
        return QSize(max(hint.width(), widest + 14 + 40), hint.height())

    def addItem(self, text: str, userData=None) -> None:
        self._items.append((text, userData))
        if self._index < 0:
            self.setCurrentIndex(0)

    def addItems(self, texts) -> None:
        for text in texts:
            self.addItem(text)

    def count(self) -> int:
        return len(self._items)

    def itemData(self, index: int):
        return self._items[index][1] if 0 <= index < len(self._items) else None

    def currentIndex(self) -> int:
        return self._index

    def currentText(self) -> str:
        return self._items[self._index][0] if 0 <= self._index < len(self._items) else ""

    def currentData(self):
        return self.itemData(self._index)

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._items) or index == self._index:
            return
        self._index = index
        self.setText(self._items[index][0])
        if not self.signalsBlocked():
            self.currentIndexChanged.emit(index)

    def _open_menu(self) -> None:
        from qfluentwidgets import Action, RoundMenu

        menu = RoundMenu(parent=self)
        for index, (text, _data) in enumerate(self._items):
            action = Action(text, menu)
            action.setCheckable(True)
            action.setChecked(index == self._index)
            action.triggered.connect(lambda _on=False, i=index: self.setCurrentIndex(i))
            menu.addAction(action)
        menu.setMinimumWidth(self.width())
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))


def empty_state(card: QWidget, icon_name: str, title: str, desc: str = "") -> None:
    """Fill ``card`` with an empty page's look: a large round icon, a title
    and one line, centred (oink-ui EmptyState, Leo 2026-11-09)."""
    layout = vbox(card, (20, 26, 20, 26), 6)
    tile = IconTile(icon_name, 56, 24)
    layout.addWidget(tile, 0, Qt.AlignHCenter)
    layout.addSpacing(4)
    head = Text(title, "h3")
    head.setAlignment(Qt.AlignCenter)
    layout.addWidget(head)
    if desc:
        line = Text(desc, "muted", wrap=True)
        line.setAlignment(Qt.AlignCenter)
        layout.addWidget(line)


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
            if accent:
                # White text on violet: Windows' ClearType colours the edges
                # for a light ground and the right side of 「10」 looked cut
                # (Leo 2026-11-09), so these use plain grey smoothing.
                font = QFont(button.font())
                font.setStyleStrategy(QFont.NoSubpixelAntialias)
                button.setFont(font)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _checked=False, value=option: self._clicked(value))
            self._group.addButton(button)
            layout.addWidget(button)
            self._buttons[option] = button
            button.toggled.connect(lambda on, b=button: on and self._slide_to(b))
        # The chosen option's pill is painted here and slides between options.
        self._pill = motion.Tween(self, self.update, 380, QRectF(), QEasingCurve.OutBack)
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
            painter.setPen(QPen(theme.color("hair"), 1))
            painter.setBrush(theme.color("raised"))
        corner = theme.seg_item_radius(rect.height())
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), corner, corner)

    def _clicked(self, value: str) -> None:
        self.changed.emit(value)

    def button(self, option: str) -> QPushButton | None:
        """The button of one option (where a motion that follows the press starts)."""
        return self._buttons.get(option)

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

    def __init__(self, text: str = "", checked: bool = False, parent=None, box: int | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setText(t(text))
        self._box = box or theme.size("check")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        # Checking fills the box and draws the tick in from the left.
        self._on = motion.Tween(self, self.update, 200, 1.0 if checked else 0.0)
        self.toggled.connect(lambda on: self._on.go(1.0 if on else 0.0))
        # oink-ui (2026-11-09): the box dips while pressed and its edge turns
        # violet under the mouse.
        self._press = motion.Tween(self, self.update, 220, 0.0, QEasingCurve.OutBack)
        self.pressed.connect(lambda: self._press.go(1.0))
        self.released.connect(lambda: self._press.go(0.0))
        self.setAttribute(Qt.WA_Hover, True)

    def set_checked_quietly(self, checked: bool) -> None:
        if self.isChecked() != checked:
            self.blockSignals(True)
            self.setChecked(checked)
            self.blockSignals(False)
            self._on.go(1.0 if checked else 0.0, animate=False)

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self.font())
        width = self._box + (8 + metrics.horizontalAdvance(self.text()) if self.text() else 0)
        return QSize(width + 2, max(self._box, metrics.height() + 4))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - self._box) / 2
        rect = QRectF(0.75, y + 0.75, self._box - 1.5, self._box - 1.5)
        corner = min(float(theme.size("corner_small")), self._box * 0.32)
        on = float(self._on.value)
        painter.save()
        press = float(self._press.value)
        if press:
            centre = rect.center()
            scale = 1.0 - 0.14 * press
            painter.translate(centre)
            painter.scale(scale, scale)
            painter.translate(-centre)
        if on < 1.0:
            hot = self.underMouse() and self.isEnabled()
            painter.setPen(QPen(theme.color("primary" if hot else "hair2"), 1.5))
            painter.setBrush(theme.color("raised"))
            painter.drawRoundedRect(rect, corner, corner)
        if on > 0.0:
            painter.save()
            painter.setOpacity(min(1.0, on * 1.6))
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("primary"))
            painter.drawRoundedRect(rect, corner, corner)
            inner = self._box - 4
            if self._on.target == 1.0 and on < 1.0:
                # Being checked: the tick is drawn in from the left.
                painter.setOpacity(1.0)
                reveal = max(0.0, (on - 0.25) / 0.75)
                painter.setClipRect(QRectF(0, 0, 2 + inner * reveal, self.height()))
            else:
                painter.setOpacity(on)
            # The tick is one stroked path drawn at screen resolution, so its
            # corner stays as thick as its arms (Leo 2026-11-09: the scaled
            # icon's tick 「感覺像斷掉」 at its corner).
            box = rect.width()
            tick = QPainterPath(QPointF(rect.x() + box * 0.25, rect.y() + box * 0.52))
            tick.lineTo(rect.x() + box * 0.43, rect.y() + box * 0.70)
            tick.lineTo(rect.x() + box * 0.76, rect.y() + box * 0.32)
            pen = QPen(theme.color("on_primary"), max(1.6, box * 0.12))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(tick)
            painter.restore()
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
        theme.strong(big, digits=True)
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

    def __init__(self, parent=None, height: int = 8, colour: str = "primary"):
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
        painter.setBrush(theme.color("well2"))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        shown = float(self._shown.value)
        if shown > 0:
            # oink-ui (2026-11-09): a violet bar turns green once it is full.
            full = self._colour == "primary" and self._value >= 1.0 and shown >= 0.999
            painter.setBrush(theme.color("ok" if full else self._colour))
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

    def move_widget(self, widget: QWidget, index: int) -> bool:
        """Put ``widget`` at ``index`` (negative counts from the end) and lay out again."""
        for position, item in enumerate(self._items):
            if item.widget() is widget:
                self._items.pop(position)
                if index < 0:
                    index = len(self._items) + 1 + index
                self._items.insert(max(0, min(index, len(self._items))), item)
                self.invalidate()
                return True
        return False

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
                    # Never shorter than the card needs: a fixed row cut the
                    # names' lower edge in English (2026-10-22 check).
                    heights.append(max(self._row_height, item.minimumSize().height()))
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
