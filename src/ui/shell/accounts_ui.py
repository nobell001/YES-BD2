"""The account button on 首页 and its windows (GitHub issue #4, Leo 2026-10-09).

The button sits at the top right of 首页 with the account's picture and
name.  Its menu lists up to five accounts with this week's 跑图 count; a
click switches.  「管理账号」 renames, deletes and sets each account's
picture (a file of at most 8 MB).  When 跑图 stopped because its records
looked like another account's, the home page shows :class:`MismatchDialog`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QWidget

from src.ui.shell import data, icons, motion, theme
from src.ui.shell.run_confirm import HeroIcon, Panel
from src.ui.shell.widgets import Button, Inset, Separator, Text, hbox, mix, t, tf, vbox
from src.utils import accounts

AVATAR_PIXELS = 256  # the picture is scaled down to this once, then cached


def display_name(account: accounts.Account) -> str:
    return account.name or tf("账号 {n}", n=account.id)


_pictures: dict[str, QPixmap] = {}


def _picture(account: accounts.Account) -> QPixmap | None:
    path = accounts.avatar_path(account)
    if path is None:
        return None
    key = str(path)
    if key not in _pictures:
        image = QImage(key)
        if image.isNull():
            return None
        side = min(image.width(), image.height())
        square = image.copy(
            (image.width() - side) // 2, (image.height() - side) // 2, side, side
        )
        _pictures[key] = QPixmap.fromImage(
            square.scaled(
                AVATAR_PIXELS, AVATAR_PIXELS, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
            )
        )
    return _pictures[key]


class Avatar(QWidget):
    """A round picture, or the name's first letter on a violet disc."""

    def __init__(self, size: int, parent=None, on_click: Callable | None = None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._account: accounts.Account | None = None
        self._on_click = on_click
        self._dim = False
        if on_click is not None:
            self.setCursor(Qt.PointingHandCursor)
            self._hover = motion.HoverFade(self, self.update)
        else:
            self._hover = None

    def set_account(self, account: accounts.Account) -> None:
        self._account = account
        self.update()

    def set_dim(self, dim: bool) -> None:
        self._dim = dim
        self.update()

    def mouseReleaseEvent(self, event):
        if self._on_click is not None and self.rect().contains(event.position().toPoint()):
            self._on_click()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        if self._account is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        side = float(self.width())
        rect = QRectF(0, 0, side, side)
        clip = QPainterPath()
        clip.addEllipse(rect)
        painter.setClipPath(clip)
        picture = _picture(self._account)
        if picture is not None:
            painter.drawPixmap(rect.toRect(), picture)
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, mix(theme.color("primary"), QColor("#FFFFFF"), 0.22))
            gradient.setColorAt(1.0, theme.color("primary"))
            painter.fillRect(rect, gradient)
            letter = self._account.name[:1] or self._account.id
            font = QFont(self.font())
            font.setPixelSize(max(10, round(side * 0.44)))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(theme.color("on_primary"))
            painter.drawText(rect, Qt.AlignCenter, letter.upper())
        if self._hover is not None and float(self._hover.value) > 0:
            painter.fillRect(rect, QColor(0, 0, 0, round(70 * float(self._hover.value))))
            pad = side * 0.32
            icons.paint(
                painter,
                QRectF(pad, pad, side - 2 * pad, side - 2 * pad),
                "image",
                QColor("#FFFFFF"),
                2.0,
            )
        if self._dim:
            painter.fillRect(rect, theme.color("card", 0.45))


def _plain(text: str, role: str) -> QLabel:
    """A label for the player's own words (names are never translated)."""
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setProperty("role", role)
    return label


# ---------------------------------------------------------------- button


class AccountChip(QWidget):
    """The pill at the top right of 首页: picture, name, a small arrow."""

    def __init__(self, on_switched: Callable[[], None], parent=None):
        super().__init__(parent)
        self._on_switched = on_switched
        self._enabled = True
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self._hover = motion.HoverFade(self, self.update)
        row = hbox(self, (6, 4, 12, 4), 8)
        self.avatar = Avatar(28)
        row.addWidget(self.avatar)
        self.name = _plain("", "h3")
        row.addWidget(self.name)
        self.arrow = QLabel()
        row.addWidget(self.arrow)
        self.setToolTip(t("切换账号：每个账号各自记日常、周常、跑图、跑商和勾选"))
        self.refresh()
        theme.on_theme_changed(self, self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        self.arrow.setPixmap(icons.pixmap("chevron-down", theme.color("ink2"), 16, 2.0))
        self.update()

    def refresh(self) -> None:
        account = accounts.current()
        self.avatar.set_account(account)
        name = display_name(account)
        if self.name.text() != name:
            self.name.setText(name)

    def set_switchable(self, on: bool) -> None:
        if on != self._enabled:
            self._enabled = on
            self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)
            self.arrow.setVisible(on)
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        hover = float(self._hover.value) if self._enabled else 0.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(mix(theme.color("card"), theme.color("primary"), 0.06 * hover))
        painter.drawRoundedRect(rect, radius, radius)
        edge = theme.color("primary") if self._enabled else theme.color("line2")
        pen = painter.pen()
        pen.setColor(edge)
        pen.setWidthF(1.6)
        pen.setStyle(Qt.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

    def mouseReleaseEvent(self, event):
        if self._enabled and self.rect().contains(event.position().toPoint()):
            self.open_menu()
        super().mouseReleaseEvent(event)

    def open_menu(self) -> None:
        menu = AccountMenu(self._switched, self.window())
        below = self.mapToGlobal(QPoint(self.width(), self.height() + 4))
        menu.show_at(below)

    def _switched(self) -> None:
        self.refresh()
        self._on_switched()


# ---------------------------------------------------------------- menu


class _MenuRow(QWidget):
    def __init__(self, on_click: Callable[[], None] | None, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self._current = False
        self.setFixedHeight(48)
        if on_click is not None:
            self.setCursor(Qt.PointingHandCursor)
        self._hover = motion.HoverFade(self, self.update)

    def set_current(self, on: bool) -> None:
        self._current = on
        self.update()

    def paintEvent(self, _event):
        amount = 1.0 if self._current else float(self._hover.value) * 0.6
        if self._on_click is None and not self._current:
            amount = 0.0
        if amount <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("primary", 0.10 * amount))
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)

    def mouseReleaseEvent(self, event):
        if self._on_click is not None and self.rect().contains(event.position().toPoint()):
            QTimer.singleShot(0, self._on_click)
        super().mouseReleaseEvent(event)


class AccountMenu(QWidget):
    WIDTH = 300

    def __init__(self, on_switched: Callable[[], None], window: QWidget):
        super().__init__(window, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet(theme.style_sheet())
        self._on_switched = on_switched
        self._window = window
        self.panel = Panel(self)
        pad = Panel.SHADOW
        column = vbox(self.panel, (pad + 8, pad - 6 + 8, pad + 8, pad + 6 + 8), 2)
        current = accounts.current_id()
        rows = accounts.accounts()
        for account in rows:
            row = _MenuRow(lambda account_id=account.id: self._switch(account_id))
            line = hbox(row, (10, 0, 12, 0), 12)
            avatar = Avatar(30)
            avatar.set_account(account)
            line.addWidget(avatar)
            line.addWidget(_plain(display_name(account), "h3"), 1)
            progress = data.map_progress(account.id)
            if progress is not None and progress.cards:
                line.addWidget(
                    Text(tf("跑图 {done}/{total}", done=progress.cards_done,
                            total=len(progress.cards)), "muted")
                )
            if account.id == current:
                row.set_current(True)
                tick = QLabel()
                tick.setPixmap(icons.pixmap("check", theme.color("primary"), 16, 2.4))
                line.addWidget(tick)
            column.addWidget(row)
        column.addSpacing(4)
        column.addWidget(Separator())
        column.addSpacing(4)
        full = len(rows) >= accounts.MAX_ACCOUNTS
        add = _MenuRow(None if full else self._add)
        line = hbox(add, (14, 0, 12, 0), 12)
        plus = QLabel()
        plus.setPixmap(icons.pixmap("plus", theme.color("ink3" if full else "primary"), 18, 2.2))
        line.addWidget(plus)
        line.addWidget(
            Text(tf("最多 {n} 个账号", n=accounts.MAX_ACCOUNTS) if full else "新增账号", "sub"),
            1,
        )
        column.addWidget(add)
        manage = _MenuRow(self._manage)
        line = hbox(manage, (14, 0, 12, 0), 12)
        pen = QLabel()
        pen.setPixmap(icons.pixmap("pencil", theme.color("ink2"), 18, 2.0))
        line.addWidget(pen)
        line.addWidget(Text("改名、换头像、删除", "sub"), 1)
        column.addWidget(manage)
        self.panel.adjustSize()
        self.panel.setFixedWidth(self.WIDTH + 2 * pad)
        self.resize(self.panel.width(), self.panel.sizeHint().height())
        self.panel.resize(self.size())

    def show_at(self, top_right: QPoint) -> None:
        self.move(top_right.x() - self.width() + Panel.SHADOW, top_right.y() - Panel.SHADOW + 6)
        self.show()

    def _switch(self, account_id: str) -> None:
        self.close()
        if data.busy():
            return
        if data.switch_account(account_id):
            self._on_switched()

    def _add(self) -> None:
        self.close()
        if data.busy():
            return
        account = data.add_account()
        if account is not None and data.switch_account(account.id):
            self._on_switched()
        ManageDialog(self._window, focus=account.id if account else None).exec()
        self._on_switched()

    def _manage(self) -> None:
        self.close()
        ManageDialog(self._window).exec()
        self._on_switched()


# ---------------------------------------------------------------- dialogs


class _Floating(QDialog):
    """A dimmed window over the tool with one :class:`Panel` in the middle."""

    PANEL_WIDTH = 520

    def __init__(self, parent: QWidget | None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet(theme.style_sheet())
        self._open = motion.Tween(self, self._place, 220, 0.0)
        self.panel = Panel(self)
        pad = Panel.SHADOW
        self.column = vbox(self.panel, (pad + 28, pad - 6 + 24, pad + 28, pad + 6 + 24), 14)
        if parent is not None:
            self.setGeometry(parent.window().geometry())

    def _place(self) -> None:
        area = self.rect()
        width = min(self.PANEL_WIDTH + 2 * Panel.SHADOW, area.width() - 32)
        self.panel.setFixedWidth(width)
        self.panel.layout().activate()
        height = min(self.panel.sizeHint().height(), area.height() - 32)
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
        self._place()
        self._open.go(1.0)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(
            self.rect(),
            theme.color(
                "shot", (0.62 if theme.tokens() is theme.DARK else 0.42) * float(self._open.value)
            ),
        )


class _ManageRow(QWidget):
    def __init__(self, account: accounts.Account, dialog: ManageDialog):
        super().__init__()
        from qfluentwidgets import LineEdit

        self.account = account
        self._dialog = dialog
        row = hbox(self, (0, 4, 0, 4), 12)
        self.avatar = Avatar(48, on_click=self._pick_picture)
        self.avatar.set_account(account)
        self.avatar.setToolTip(t("换头像（8MB 以内的图片）"))
        row.addWidget(self.avatar)
        self.edit = LineEdit(self)
        self.edit.setText(account.name)
        self.edit.setPlaceholderText(tf("账号 {n}", n=account.id))
        self.edit.setMaxLength(20)
        self.edit.setClearButtonEnabled(True)
        self.edit.editingFinished.connect(self._save_name)
        row.addWidget(self.edit, 1)
        self.delete = Button("", "ghost", "trash-2", on_click=self._delete)
        self.delete.setFixedSize(36, 36)
        if account.id == accounts.FIRST_ID:
            # The first account holds the original records and always stays.
            keep = self.delete.sizePolicy()
            keep.setRetainSizeWhenHidden(True)
            self.delete.setSizePolicy(keep)
            self.delete.hide()
        elif account.id == accounts.current_id():
            self.delete.setEnabled(False)
            self.delete.setToolTip(t("正在用的账号不能删除，先切到别的账号"))
        else:
            self.delete.setToolTip(t("删除这个账号和它的记录"))
        self._armed = False
        row.addWidget(self.delete)

    def _save_name(self) -> None:
        accounts.rename(self.account.id, self.edit.text())
        self._dialog.changed()

    def _pick_picture(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("选一张头像图片"),
            "",
            t("图片") + " (*.png *.jpg *.jpeg *.bmp *.webp *.gif)",
        )
        if not path:
            return
        source = Path(path)
        try:
            too_big = source.stat().st_size > accounts.AVATAR_MAX_BYTES
        except OSError:
            self._dialog.say("读不到这张图片")
            return
        if too_big:
            self._dialog.say("图片要在 8MB 以内")
            return
        if QImage(str(source)).isNull():
            self._dialog.say("看不懂这张图片，换一张 PNG 或 JPG 试试")
            return
        try:
            accounts.set_avatar(self.account.id, source)
        except (accounts.AccountError, OSError):
            self._dialog.say("头像没存好，再试一次")
            return
        self._dialog.say("")
        self._dialog.changed()

    def _delete(self) -> None:
        # Two presses: the first one asks, so a slip never deletes.
        if not self._armed:
            self._armed = True
            self.delete.set_label("确定删除？")
            self.delete.setFixedSize(self.delete.sizeHint().width() + 8, 36)
            QTimer.singleShot(4000, self._disarm)
            return
        try:
            accounts.delete(self.account.id)
        except accounts.AccountError:
            return
        self._dialog.changed(rebuild=True)

    def _disarm(self) -> None:
        if self._armed:
            self._armed = False
            self.delete.set_label("")
            self.delete.setFixedSize(36, 36)


class ManageDialog(_Floating):
    def __init__(self, parent: QWidget | None, focus: str | None = None):
        super().__init__(parent)
        head = hbox(None, (0, 0, 0, 0), 14)
        head.addWidget(HeroIcon("users-round"))
        titles = vbox(None, (0, 0, 0, 0), 2)
        titles.addWidget(Text("账号", "h1"))
        titles.addWidget(Text("每个账号各自记日常、周常、跑图、跑商和勾选", "sub", wrap=True))
        head.addLayout(titles, 1)
        close = Button("", "ghost", "x", on_click=self.accept)
        close.setFixedSize(34, 34)
        head.addWidget(close, 0, Qt.AlignTop)
        self.column.addLayout(head)
        self.rows_box = QWidget()
        self.rows = vbox(self.rows_box, (0, 0, 0, 0), 6)
        self.column.addWidget(self.rows_box)
        self.note = Text("", "muted", wrap=True)
        self.note.hide()
        self.column.addWidget(self.note)
        hint = Inset()
        hint_row = hbox(hint, (14, 10, 14, 10), 10)
        hint_row.addWidget(
            Text("点头像可以换图片（8MB 以内）。在游戏里换账号后，记得在这里也换。", "muted",
                 wrap=True),
            1,
        )
        self.column.addWidget(hint)
        buttons = hbox(None, (0, 2, 0, 0), 10)
        buttons.addStretch(1)
        buttons.addWidget(Button("完成", "primary", on_click=self.accept))
        self.column.addLayout(buttons)
        self._focus = focus
        self._build_rows()

    def _build_rows(self) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for account in accounts.accounts():
            row = _ManageRow(account, self)
            self.rows.addWidget(row)
            if account.id == self._focus:
                QTimer.singleShot(0, row.edit.setFocus)
        self._place()

    def say(self, text: str) -> None:
        self.note.set_text(text)
        self.note.setVisible(bool(text))
        self._place()

    def changed(self, rebuild: bool = False) -> None:
        if rebuild:
            self._focus = None
            self._build_rows()
            return
        for index in range(self.rows.count()):
            row = self.rows.itemAt(index).widget()
            if isinstance(row, _ManageRow):
                fresh = next((a for a in accounts.accounts() if a.id == row.account.id), None)
                if fresh is not None:
                    row.account = fresh
                    row.avatar.set_account(fresh)


class MismatchDialog(_Floating):
    """跑图 stopped: its records said done, the game showed the cards untouched."""

    SWITCH = 1
    SAME = 2

    def __init__(self, parent: QWidget | None):
        super().__init__(parent)
        self.choice = 0
        self.column.addWidget(HeroIcon("users-round"))
        self.column.addWidget(Text("是不是换了账号？", "h1"))
        name = display_name(accounts.current())
        body = QLabel(tf("「{name}」本周跑图的记录说已经跑完，但游戏里的卡带还没完成。", name=name))
        body.setProperty("role", "sub")
        body.setWordWrap(True)
        body.setTextFormat(Qt.PlainText)
        self.column.addWidget(body)
        warn = Inset()
        warn.setStyleSheet(
            f"background: {theme.tokens()['warn_soft']}; border-radius: 12px; border: none;"
        )
        warn_box = vbox(warn, (14, 10, 14, 10), 2)
        for line in ("跑图先停下了，没有按任何技能。", "请在右上角选对账号，再按开始。"):
            label = Text(line, None, wrap=True)
            label.setStyleSheet(f"color: {theme.tokens()['warn']};")
            warn_box.addWidget(label)
        self.column.addWidget(warn)
        buttons = hbox(None, (0, 4, 0, 0), 10)
        buttons.addStretch(1)
        buttons.addWidget(Button("就是这个账号，重新看画面", "secondary", on_click=self._same))
        buttons.addWidget(Button("切换账号", "primary", "users-round", on_click=self._switch))
        self.column.addLayout(buttons)

    def _same(self) -> None:
        self.choice = self.SAME
        self.accept()

    def _switch(self) -> None:
        self.choice = self.SWITCH
        self.accept()
