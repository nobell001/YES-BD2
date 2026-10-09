"""The window that pops up over the tool when 一键完成日常 or 在桌面分身跑 is
pressed (Leo 2026-10-09): pick 「跑勾选的」 or 「跑没跑完的」, see every 日常
and 周常 as a tile with its check, change the checks, then 开始.

The checks are the home tiles' checks: what is changed here is kept when the
run starts, and thrown away on 取消.  「跑没跑完的」 only greys out what is
already done; an unticked item never runs in either mode.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QScrollArea, QWidget

from src.ui.shell import data, icons, motion, theme
from src.ui.shell.widgets import (
    Button,
    CheckBox,
    IconTile,
    Inset,
    Segmented,
    StateIcon,
    Text,
    grid_container,
    hbox,
    mix,
    tf,
    vbox,
)
from src.utils import accounts

MODE_TICKED = "ticked"
MODE_LEFT = "left"

PANEL_WIDTH = 800
WINDOW_GAP = 32  # air between the panel and the tool window's edge


def default_mode(children: list[data.Child], done: dict[str, bool]) -> str:
    """「跑没跑完的」 while something ticked is left today, else 「跑勾选的」."""
    left = any(child.included and not done.get(child.key) for child in children)
    return MODE_LEFT if left else MODE_TICKED


def will_run(ticks: dict[str, bool], done: dict[str, bool], mode: str) -> list[str]:
    """Keys the run would do: the ticked ones, minus the done ones in 「跑没跑完的」."""
    return [key for key, on in ticks.items() if on and not (mode == MODE_LEFT and done.get(key))]


class HeroIcon(QWidget):
    """A violet disc with a white line icon: the window's badge."""

    def __init__(self, icon_name: str, size: int = 46, parent=None):
        super().__init__(parent)
        self._icon = icon_name
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = float(self.width())
        glow = theme.color("primary", 0.16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(0, 0, side, side))
        inner = QRectF(5, 5, side - 10, side - 10)
        gradient = QLinearGradient(inner.topLeft(), inner.bottomRight())
        gradient.setColorAt(0.0, mix(theme.color("primary"), QColor("#FFFFFF"), 0.18))
        gradient.setColorAt(1.0, theme.color("primary"))
        painter.setBrush(gradient)
        painter.drawEllipse(inner)
        pad = side * 0.3
        icons.paint(
            painter,
            QRectF(pad, pad, side - 2 * pad, side - 2 * pad),
            self._icon,
            theme.color("on_primary"),
            2.1,
        )


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


class PickTile(QWidget):
    """One 日常 / 周常: icon, name, today's state and the check in the corner.
    A click anywhere on it flips the check.  A ticked tile wears a violet edge
    and a faint violet wash, so what will run reads at a glance."""

    def __init__(self, child: data.Child, on_toggle: Callable[[str, bool], None], parent=None):
        super().__init__(parent)
        self.child = child
        self._on_toggle = on_toggle
        self._locked = False
        self._on = child.included
        self._done = False
        self.setCursor(Qt.PointingHandCursor)
        self._hover = motion.HoverFade(self, self.update)
        self._lit = motion.Tween(self, self.update, 180, 1.0 if child.included else 0.0)
        layout = vbox(self, (14, 13, 11, 12), 0)
        top = hbox(None, (0, 0, 0, 0), 0)
        self.tile = IconTile(child.icon, 32, 18, kind=child.kind)
        self.tile.follow_hover(self)
        top.addWidget(self.tile)
        top.addStretch(1)
        self.check = CheckBox("", child.included, box=20)
        self.check.setFixedSize(26, 26)
        self.check.toggled.connect(self._toggled)
        top.addWidget(self.check, 0, Qt.AlignTop)
        layout.addLayout(top)
        # Leo 2026-10-09: the name sat on the icon; give it room.
        layout.addSpacing(12)
        self.name = Text(child.short, "h3", elide=True)
        layout.addWidget(self.name)
        layout.addSpacing(3)
        state = hbox(None, (0, 0, 0, 0), 4)
        self.mark = StateIcon("done", 13)
        self.state = Text("", "muted", elide=True)
        state.addWidget(self.mark)
        state.addWidget(self.state, 1)
        layout.addLayout(state)
        layout.addStretch(1)

    def _toggled(self, on: bool) -> None:
        self._on = on
        self._lit.go(1.0 if on else 0.0)
        self._on_toggle(self.child.key, on)

    def show_state(self, ticked: bool, done: bool, done_text: str, locked: bool) -> None:
        """``locked``: done and 「跑没跑完的」 is chosen, so it will not run."""
        self._locked = locked
        self._done = done
        self._on = ticked and not locked
        self._lit.go(1.0 if self._on else 0.0)
        self.check.set_checked_quietly(self._on)
        self.check.setVisible(not locked)
        self.setCursor(Qt.ArrowCursor if locked else Qt.PointingHandCursor)
        self.mark.setVisible(done)
        if done:
            self.mark.set_state("done")
        self.state.set_text((done_text or "已完成") if done else "未完成")
        self.state.set_role("ok" if done else "muted")
        off = not self._on
        self.tile.set_off(off)
        self.name.set_role("muted" if off else "h3")
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        corner = float(theme.radius()) + 2
        lit = float(self._lit.value)
        hover = 0.0 if self._locked else float(self._hover.value)
        if self._locked:
            painter.setPen(QPen(theme.color("line"), 1))
            painter.setBrush(theme.color("inset"))
            painter.drawRoundedRect(body, corner, corner)
            return
        base = theme.color("card")
        wash = mix(base, theme.color("primary"), 0.07 * lit)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("shadow", 0.06 + 0.04 * hover))
        painter.drawRoundedRect(body.adjusted(0, 2, 0, 2), corner, corner)
        painter.setBrush(wash)
        edge = mix(theme.color("line2"), theme.color("primary"), max(lit, 0.5 * hover))
        painter.setPen(QPen(edge, 1.0 + 0.6 * lit))
        painter.drawRoundedRect(body, corner, corner)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self._locked:
            self.check.setChecked(not self.check.isChecked())
        super().mouseReleaseEvent(event)


class RunConfirm(QDialog):
    """Dims the tool window and floats the choice in the middle of it."""

    def __init__(
        self,
        children: list[data.Child],
        done: dict[str, bool],
        done_text: dict[str, str],
        clone: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet(theme.style_sheet())
        self._children = children
        self._done = done
        self._done_text = done_text
        self.ticks = {child.key: child.included for child in children}
        self.mode = default_mode(children, done)
        self._open = motion.Tween(self, self._place, 220, 0.0)

        self.panel = Panel(self)
        pad = Panel.SHADOW  # the shadow is drawn inside the panel's own rect
        column = vbox(self.panel, (pad + 28, pad - 6 + 24, pad + 28, pad + 6 + 24), 16)

        head = hbox(None, (0, 0, 0, 0), 14)
        head.addWidget(HeroIcon("monitor" if clone else "play"))
        titles = vbox(None, (0, 0, 0, 0), 2)
        titles.addWidget(Text("在桌面分身跑" if clone else "一键完成日常", "h1"))
        self.subtitle = Text("", "sub")
        titles.addWidget(self.subtitle)
        if accounts.has_several():
            # GitHub issue #4: which game account this run is for.
            from src.ui.shell.accounts_ui import display_name

            who = QLabel(tf("账号：{name}", name=display_name(accounts.current())))
            who.setTextFormat(Qt.PlainText)
            who.setProperty("role", "h3")
            titles.addWidget(who)
        head.addLayout(titles, 1)
        close = Button("", "ghost", "x", on_click=self.reject)
        close.setFixedSize(34, 34)
        head.addWidget(close, 0, Qt.AlignTop)
        column.addLayout(head)

        # Leo 2026-10-09: 跑勾选的 on the left, 全选 beside the switch.
        modes = hbox(None, (0, 0, 0, 0), 14)
        self.switch = Segmented(
            (MODE_TICKED, MODE_LEFT),
            self.mode,
            labels={MODE_LEFT: "跑没跑完的", MODE_TICKED: "跑勾选的"},
            accent=True,
        )
        self.switch.changed.connect(self._set_mode)
        self.switch.setStyleSheet(
            "QPushButton { min-height: 32px; padding: 0 18px; font-size: 14px; }"
        )
        modes.addWidget(self.switch)
        modes.addStretch(1)
        self.select_all = CheckBox("全选", False)
        self.select_all.toggled.connect(self._select_all)
        modes.addWidget(self.select_all)
        column.addLayout(modes)

        body = QWidget()
        lists = vbox(body, (2, 2, 8, 2), 12)
        self.tiles: dict[str, PickTile] = {}
        for weekly, title in ((False, "今日任务"), (True, "本周任务")):
            group = [child for child in children if child.weekly == weekly]
            if not group:
                continue
            lists.addWidget(Text(title, "h2"))
            box, grid = grid_container(128, 12, None, 104)
            for child in group:
                tile = PickTile(child, self._toggle)
                grid.addWidget(tile)
                self.tiles[child.key] = tile
            lists.addWidget(box)
        lists.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(body)
        line = theme.tokens()["line2"]
        self.scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
            " QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }"
            f" QScrollBar::handle:vertical {{ background: {line}; border-radius: 3px;"
            " min-height: 30px; }"
            " QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
            " QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }"
        )
        column.addWidget(self.scroll, 1)

        # Leo 2026-10-09: the keyboard / mouse warning moved here from home.
        hint = Inset()
        hint_row = hbox(hint, (14, 12, 16, 12), 12)
        hint_row.addWidget(IconTile("monitor" if clone else "mouse", 34, 18), 0, Qt.AlignVCenter)
        hint_text = vbox(None, (0, 0, 0, 0), 2)
        if clone:
            hint_text.addWidget(Text("游戏在分身窗口里跑，你照常用电脑", "h3", wrap=True))
            hint_text.addWidget(Text("会跳出 Windows 确认，请按「是」", "muted", wrap=True))
        else:
            hint_text.addWidget(Text("执行时请别动键盘和鼠标", "h3", wrap=True))
            hint_text.addWidget(
                Text("一动就会停下，想边跑边用电脑请用桌面分身", "muted", wrap=True)
            )
        hint_row.addLayout(hint_text, 1)
        column.addWidget(hint)

        buttons = hbox(None, (0, 2, 0, 0), 10)
        buttons.addStretch(1)
        buttons.addWidget(Button("取消", "secondary", on_click=self.reject))
        self.start = Button("", "primary", "play", "lg", on_click=self.accept)
        buttons.addWidget(self.start)
        column.addLayout(buttons)

        self._refresh()
        if parent is not None:
            self.setGeometry(parent.window().geometry())
        self._place()

    # ---------------------------------------------------------------- state

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self._refresh()

    def _toggle(self, key: str, on: bool) -> None:
        self.ticks[key] = on
        self._refresh()

    def _select_all(self, on: bool) -> None:
        for key, tile in self.tiles.items():
            if not tile._locked:
                self.ticks[key] = on
        self._refresh()

    def run_keys(self) -> list[str]:
        return will_run(self.ticks, self._done, self.mode)

    def _refresh(self) -> None:
        for child in self._children:
            done = bool(self._done.get(child.key))
            self.tiles[child.key].show_state(
                self.ticks[child.key],
                done,
                self._done_text.get(child.key, "已完成"),
                self.mode == MODE_LEFT and done,
            )
        count = len(self.run_keys())
        open_keys = [key for key, tile in self.tiles.items() if not tile._locked]
        self.select_all.set_checked_quietly(
            bool(open_keys) and all(self.ticks[key] for key in open_keys)
        )
        for mode, label in ((MODE_LEFT, "跑没跑完的 {n} 项"), (MODE_TICKED, "跑勾选的 {n} 项")):
            n = len(will_run(self.ticks, self._done, mode))
            self.switch.set_label(mode, tf(label, n=n))
        if self.mode == MODE_LEFT:
            self.subtitle.set_text("做完的会跳过，没勾的不跑")
        else:
            self.subtitle.set_text("勾到的都跑，做完的也会再跑一次")
        self.start.set_label(tf("开始 {n} 项", n=count))
        self.start.setEnabled(count > 0)

    # ---------------------------------------------------------------- look

    def _place(self) -> None:
        area = self.rect()
        width = min(PANEL_WIDTH, max(380, area.width() - 2 * WINDOW_GAP))
        self.panel.setFixedWidth(width)
        # Tall enough for every tile when the window has room, else the
        # tiles scroll (small screens) and the buttons stay in view.
        self.panel.layout().activate()
        inner = width - 2 * Panel.SHADOW - 56 - 10  # shadow, margins, list margin
        lists = self.scroll.widget().layout().heightForWidth(inner)
        need = self.panel.sizeHint().height() - self.scroll.sizeHint().height() + lists + 4
        height = min(need, max(320, area.height() - 2 * WINDOW_GAP))
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
        self._open.go(1.0)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(
            self.rect(),
            theme.color(
                "shot", (0.62 if theme.tokens() is theme.DARK else 0.42) * float(self._open.value)
            ),
        )

    def mouseReleaseEvent(self, event):
        # A click on the dimmed part outside the panel is 取消.
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.reject()
        super().mouseReleaseEvent(event)


def ask(window: QWidget | None, batch, clone: bool = False) -> tuple[str, dict[str, bool]] | None:
    """Show the window; returns (mode, checks) on 开始, ``None`` on 取消."""
    children = data.batch_children(batch)
    done, done_text = {}, {}
    for child in children:
        done[child.key] = data.child_done(child)
        if done[child.key]:
            record = data.last_run(child.name) or {}
            finished = record.get("finished")
            when = data.clock_text(finished)
            if child.weekly and data.day_text(finished) != "今天":
                when = data.day_text(finished) or when
            done_text[child.key] = when
    dialog = RunConfirm(children, done, done_text, clone, window)
    if not dialog.exec():
        return None
    return dialog.mode, dict(dialog.ticks)
