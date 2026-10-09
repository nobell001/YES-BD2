"""The left column: app name, the pages with icons, and the game/run status."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QFrame, QWidget

from src.ui.shell import clone_flow, data, icons, theme
from src.ui.shell.safe import guarded
from src.ui.shell.widgets import Bar, Spinner, StateIcon, Text, draw_fitted, hbox, t, tf, vbox

ICON_FILE = Path(__file__).resolve().parents[3] / "icons" / "icon.png"
SIDE_WIDTH = 204


class NavItem(QAbstractButton):
    """Icon + label (+ a small badge on the right).

    Selected: a soft violet pill in 淡紫, a quiet card with a blue icon in 深色.
    """

    def __init__(self, key: str, label: str, icon_name: str, parent=None, strong=False):
        super().__init__(parent)
        self.key = key
        self._label = t(label)
        self._strong = strong
        self._icon = icon_name
        self._selected = False
        self._hover = 0.0
        # The hover shade fades in and out instead of switching on and off.
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._set_hover)
        self._badge = ""
        self._badge_kind = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(36)
        self._spin = Spinner(12, self, colour="badge_run_ink")
        self._spin.hide()

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    def set_badge(self, text: str, kind: str = "") -> None:
        text = t(text)
        if (text, kind) != (self._badge, self._badge_kind):
            self._badge, self._badge_kind = text, kind
            self._place_spinner()
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(SIDE_WIDTH - 24, 36)

    def enterEvent(self, event):
        self._fade_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._fade_hover(0.0)
        super().leaveEvent(event)

    def _fade_hover(self, target: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def _set_hover(self, value) -> None:
        self._hover = float(value)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_spinner()

    def _badge_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setBold(True)
        return font

    def _badge_rect(self) -> QRectF:
        metrics = QFontMetrics(self._badge_font())
        text_w = metrics.horizontalAdvance(self._badge) if self._badge else 0
        spin_w = 14 if self._badge_kind == "run" else 0
        width = max(20, text_w + spin_w + 12)
        return QRectF(self.width() - 8 - width, (self.height() - 18) / 2, width, 18)

    def _place_spinner(self) -> None:
        running = self._badge_kind == "run"
        self._spin.setVisible(running)
        if running:
            rect = self._badge_rect()
            self._spin.move(round(rect.x() + 5), round(rect.y() + 3))
            self._spin.raise_()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        round_icons = theme.shape("round_icons")
        # 淡紫: a pill, and the icon sits in a circle (filled when selected).
        corner = box.height() / 2 if round_icons else theme.radius()
        if self._selected:
            painter.setPen(QPen(theme.color("nav_on_line"), 1))
            painter.setBrush(theme.color("nav_on"))
            painter.drawRoundedRect(box, corner, corner)
            fg, icon = theme.color("nav_on_ink"), theme.color("nav_on_icon")
        else:
            if self._hover > 0:
                painter.setPen(Qt.NoPen)
                painter.setBrush(theme.color("ink", 0.05 * self._hover))
                painter.drawRoundedRect(box, corner, corner)
            fg, icon = theme.color("ink"), theme.color("nav_icon")
        # Hovered: the icon grows a little (selected ones stay put).
        grow = 0.0 if self._selected else self._hover
        if round_icons:
            side = 28 + 1.5 * grow
            circle = QRectF(18 - side / 2, (self.height() - side) / 2, side, side)
            if self._selected:
                painter.setPen(Qt.NoPen)
                painter.setBrush(theme.color("nav_on_circle"))
            else:
                painter.setPen(QPen(theme.color("ring"), 1.2))
                painter.setBrush(theme.color("card"))
            painter.drawEllipse(circle.adjusted(0.6, 0.6, -0.6, -0.6))
            pad = 6.5 - 0.5 * grow
            icons.paint(painter, circle.adjusted(pad, pad, -pad, -pad), self._icon, icon, 1.9)
        else:
            side = 18 + 2.5 * grow
            icons.paint(
                painter,
                QRectF(21 - side / 2, (self.height() - side) / 2, side, side),
                self._icon,
                icon,
                1.9,
            )
        font = QFont(self.font())
        font.setPixelSize(13)
        if self._selected:
            font.setWeight(QFont.Weight.Bold)
        elif self._strong:
            font.setWeight(QFont.Weight.DemiBold)
        else:
            font.setWeight(theme.body_weight())
        painter.setFont(font)
        painter.setPen(fg)
        text_rect = QRectF(40, 0, self.width() - 48, self.height())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._label)
        if not self._badge and self._badge_kind != "run":
            return
        rect = self._badge_rect()
        # Counts sit in small soft chips, as in the draft.
        if self._badge_kind == "run":
            bg, ink = theme.color("badge_run"), theme.color("badge_run_ink")
        elif self._badge_kind == "ok":
            bg, ink = theme.color("badge_ok"), theme.color("ok")
        elif self._selected:
            bg, ink = theme.color("badge_on"), theme.color("badge_on_ink")
        else:
            bg, ink = theme.color("badge"), theme.color("badge_ink")
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, theme.corner(4, 9), theme.corner(4, 9))
        if self._badge_kind == "ok" and self._badge == "✓":
            icons.paint(
                painter, QRectF(rect.center().x() - 6, rect.y() + 3, 12, 12), "check", ink, 2.8
            )
            return
        painter.setPen(ink)
        painter.setFont(self._badge_font())
        offset = 14 if self._badge_kind == "run" else 0
        painter.drawText(rect.adjusted(offset, 0, 0, 0), Qt.AlignCenter, self._badge)


class Sidebar(QWidget):
    """Brand, page list, 设置/关于 and the game or run status at the bottom."""

    navigate = Signal(str)

    PAGES = (
        ("home", "首页", "house"),
        ("report", "今日报表", "list-checks"),
        # Leo 2026-10-09: 任务设定 (the 周常 are in it too).
        ("daily", "任务设定", "calendar-check"),
        ("trade", "跑商", "coins"),
        ("map", "跑图", "map"),
        # Leo 2026-10-06: 魔兽战 back, on a page of its own.
        ("fiend", "魔兽追踪者", "skull"),
    )
    BOTTOM = (
        # Leo 2026-10-09: players send what went wrong from here, always in reach.
        ("problem", "回报问题", "message-circle-warning"),
        # Leo (2026-10-05): the guide sits where new players see it.
        ("guide", "使用说明", "book-open"),
        ("settings", "设置", "settings"),
        ("about", "关于", "info"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("shellSide")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(SIDE_WIDTH)
        layout = vbox(self, (12, 14, 12, 12), 2)
        self._layout = layout

        brand = QWidget(self)
        brand_row = hbox(brand, (6, 0, 0, 0), 10)
        logo = QWidget(brand)
        logo.setFixedSize(30, 30)
        self._logo_pixmap = QPixmap(str(ICON_FILE)) if ICON_FILE.exists() else QPixmap()
        logo.paintEvent = lambda _e, w=logo: self._paint_logo(w)
        brand_row.addWidget(logo)
        names = vbox(None, (0, 0, 0, 0), 0)
        names.addWidget(Text("YES-BD2", "h3"))
        names.addWidget(Text("BD2 自动日常", "muted"))
        brand_row.addLayout(names, 1)
        brand.setFixedHeight(46)
        layout.addWidget(brand)
        layout.addSpacing(14)

        self.items: dict[str, NavItem] = {}
        for key, label, icon_name in self.PAGES:
            layout.addWidget(self._item(key, label, icon_name))
        layout.addStretch(1)
        for key, label, icon_name in self.BOTTOM:
            layout.addWidget(self._item(key, label, icon_name))
        layout.addSpacing(10)
        self.footer = _StatusFooter(self)
        layout.addWidget(self.footer)

        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._map_timer = QTimer(self)
        self._map_timer.setInterval(20000)
        # These run every few seconds for as long as the tool is open; a
        # failure is logged, never allowed to close the window.
        self.refresh = guarded("sidebar refresh", self._refresh_now, self._timer.stop)
        self._refresh_map = guarded(
            "sidebar map badge", self._refresh_map_now, self._map_timer.stop
        )
        self._timer.timeout.connect(self.refresh)
        self._map_timer.timeout.connect(self._refresh_map)
        self.apply_style()
        theme.on_theme_changed(self, self.apply_style)

    def _item(self, key: str, label: str, icon_name: str) -> NavItem:
        # Leo 2026-10-09: 使用说明 a little bolder, always marked 必看.
        item = NavItem(key, label, icon_name, self, strong=key == "guide")
        item.clicked.connect(lambda *_a, k=key: self.navigate.emit(k))
        self.items[key] = item
        return item

    def _paint_logo(self, widget: QWidget) -> None:
        painter = QPainter(widget)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self._logo_pixmap.isNull():
            draw_fitted(
                painter, QRectF(widget.rect()), self._logo_pixmap, widget.devicePixelRatioF()
            )

    def apply_style(self) -> None:
        self.setStyleSheet(theme.style_sheet())
        # 淡紫 draws the column as a rounded panel set in from the window edge.
        inset = int(theme.shape("side_inset"))
        self.setFixedWidth(SIDE_WIDTH + 2 * inset)
        self._layout.setContentsMargins(12 + inset, 14 + inset, 12 + inset, 12 + inset)
        for item in self.items.values():
            item.update()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        inset = theme.shape("side_inset")
        if not inset:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("side"))
        panel = QRectF(self.rect()).adjusted(inset, inset, -inset / 2, -inset)
        painter.drawRoundedRect(panel, 22, 22)

    def select(self, key: str | None) -> None:
        for item_key, item in self.items.items():
            item.set_selected(item_key == key)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self._refresh_map()
        self._timer.start()
        self._map_timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        self._map_timer.stop()
        super().hideEvent(event)

    def _refresh_now(self) -> None:
        self._refresh_badges()
        self.footer.refresh()

    def _refresh_badges(self) -> None:
        report, current = clone_flow.active_run()
        for key, batch_name in (("daily", data.DAILY_BATCH),):
            batch = data.task_by_name(batch_name)
            children = [child for child in data.batch_children(batch) if child.included]
            done = sum(1 for child in children if data.child_done(child))
            running = report is not None and report.get("label") == batch_name
            if running:
                rows = report.get("rows") or []
                finished = sum(1 for row in rows if row.get("state") in ("done", "skip", "fail"))
                self.items[key].set_badge(f"{finished}/{len(rows)}", "run")
            elif children:
                self.items[key].set_badge(
                    f"{done}/{len(children)}", "ok" if done == len(children) else ""
                )
            else:
                self.items[key].set_badge("")
        trade = data.task_by_name("每日跑商")
        trade_running = (
            current is trade
            and trade is not None
            or (report is not None and report.get("current") == "跑商")
        )
        if trade_running:
            self.items["trade"].set_badge("", "run")
        elif data.done_today("每日跑商"):
            self.items["trade"].set_badge("✓", "ok")
        else:
            self.items["trade"].set_badge("未跑")
        map_task = data.task_by_name("每周跑图")
        map_running = (
            current is map_task
            and map_task is not None
            or (report is not None and report.get("current") == "每周跑图")
        )
        if map_running:
            self.items["map"].set_badge("", "run")
        elif self._map_badge:
            from src.utils import accounts

            if self._map_badge_account != accounts.current_id():
                # Another account was picked: its own 跑图 count, not the last one's.
                self._refresh_map_now()
            self.items["map"].set_badge(*self._map_badge)

    _map_badge: tuple[str, str] | None = None
    _map_badge_account = ""

    def _refresh_map_now(self) -> None:
        from src.utils import accounts

        self._map_badge_account = accounts.current_id()
        progress = data.map_progress()
        if progress is None or not progress.cards:
            self._map_badge = ("", "")
            return
        done, total = progress.cards_done, len(progress.cards)
        self._map_badge = (f"{done}/{total}", "ok" if done == total else "")


class _StatusFooter(QFrame):
    """Game connection when idle; what is running (n/m, a thin bar) during a run."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("box", True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = vbox(self, (12, 10, 12, 10), 3)
        top = hbox(None, (0, 0, 0, 0), 7)
        self.dot = StateIcon("off", 12)
        self.spin = Spinner(13)
        self.spin.hide()
        self.headline = Text("", "h3", elide=True)
        top.addWidget(self.dot)
        top.addWidget(self.spin)
        top.addWidget(self.headline, 1)
        layout.addLayout(top)
        self.bar = Bar(height=4)
        self.bar.hide()
        layout.addWidget(self.bar)
        self.line1 = Text("", "muted", elide=True)
        self.line2 = Text("", "muted", elide=True)
        layout.addWidget(self.line1)
        layout.addWidget(self.line2)
        self.on_click: Callable[[], None] | None = None

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and callable(self.on_click):
            self.on_click()
        super().mouseReleaseEvent(event)

    def refresh(self) -> None:
        report, current = clone_flow.active_run()
        if report is not None and report.get("rows"):
            rows = report["rows"]
            finished = sum(1 for row in rows if row.get("state") in ("done", "skip", "fail"))
            paused = bool(getattr(current, "paused", False))
            self._running("已暂停" if paused else "正在跑")
            self.bar.set_value(finished / max(1, len(rows)), "run_bar")
            name = next(
                (row.get("name") for row in rows if row.get("key") == report.get("current")), ""
            )
            self.line1.set_text(name or report.get("label") or "")
            self.line2.set_text(tf("完成 {done} / {total} 项", done=finished, total=len(rows)))
            self.line2.show()
            return
        if current is not None:
            paused = bool(getattr(current, "paused", False))
            self._running("已暂停" if paused else "正在跑")
            self.bar.hide()
            self.line1.set_text(data.tr(str(getattr(current, "name", ""))))
            self.line2.hide()
            return
        self.spin.hide()
        self.dot.show()
        self.bar.hide()
        window = data.game_window()
        if window["connected"]:
            self.dot.set_state("done")
            self.headline.set_text("已连接游戏")
            self.line1.set_text(window["title"] or "BrownDust II")
            self.line2.set_text(window["size"])
            self.line2.setVisible(bool(window["size"]))
        else:
            self.dot.set_state("off")
            self.headline.set_text("未连接游戏")
            self.line1.set_text("开始时会自动连接")
            self.line2.hide()

    def _running(self, text: str) -> None:
        self.dot.hide()
        self.spin.show()
        self.headline.set_text(text)
        self.bar.show()
