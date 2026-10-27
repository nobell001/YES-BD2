"""跑完通知's setup window: get a Server酱 SendKey and check it (Leo 2026-10-22
「用戶引導甚麼的 都要做好」).

Four short steps, a button that opens the Server酱 page in the browser, a box
for the SendKey and 发测试; 完成 keeps the key and switches the notice on.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import QLineEdit, QWidget

from src.ui.shell import theme
from src.ui.shell.floating import Floating, Panel
from src.ui.shell.run_confirm import HeroIcon
from src.ui.shell.widgets import Button, Text, hbox, set_prop, t, vbox
from src.utils import run_notify

PANEL_WIDTH = 460

STEPS = (
    "点下面的按钮，打开 Server酱 网站",
    "用微信扫码登录，照网页提示关注公众号",
    "复制 SCT 开头的那一串 SendKey",
    "贴到下面，按「发测试」，微信收到就好了",
)
PRIVACY = (
    "只发完成几项、失败原因和用时，不发账号名称和电脑名称。免费版每天 5 则，一天跑一次只用 1 则。"
)
SENT = "测试已送达，看看微信"
SENDING = "正在发…"
KEY_OK = "认出 SendKey 了"


class _Number(QWidget):
    """A small violet disc with the step's number."""

    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self._number = str(number)
        self.setFixedSize(22, 22)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("accent_soft"))
        painter.drawEllipse(self.rect())
        painter.setPen(theme.color("primary"))
        font = painter.font()
        font.setPixelSize(12)
        theme.strong(font, digits=True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, self._number)


class RunNotifyDialog(Floating):
    PANEL_WIDTH = PANEL_WIDTH - 2 * Panel.SHADOW
    MARGIN = 64
    PAD = (24, 20)
    SPACING = 12
    tested = Signal(str)

    def __init__(self, key: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._sending = False
        column = self.column

        head = hbox(None, (0, 0, 0, 0), 12)
        head.addWidget(HeroIcon("send", 40))
        titles = vbox(None, (0, 0, 0, 0), 2)
        titles.addWidget(Text("跑完发到微信", "h2"))
        titles.addWidget(Text("一键完成日常跑完，把结果发到你自己的微信", "sub", wrap=True))
        head.addLayout(titles, 1)
        column.addLayout(head)

        for number, step in enumerate(STEPS, 1):
            row = hbox(None, (0, 0, 0, 0), 10)
            row.addWidget(_Number(number), 0, Qt.AlignTop)
            row.addWidget(Text(step, None, wrap=True), 1)
            column.addLayout(row)

        self.site_button = Button(
            "打开 Server酱 网站", "secondary", "external-link", on_click=self._open_site
        )
        column.addWidget(self.site_button, 0, Qt.AlignLeft)

        self.edit = QLineEdit(self.panel)
        self.edit.setPlaceholderText(t("贴上 SendKey"))
        # Shown while typing, dots once the box is left (the key is a password).
        self.edit.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.edit.setText(key)
        self.edit.setMinimumHeight(38)
        tk = theme.tokens()
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: {tk['inset']}; color: {tk['ink']};"
            f" border: 1px solid {tk['line2']}; border-radius: 10px; padding: 0 12px;"
            f" font-size: 14px; selection-background-color: {tk['accent']};"
            f" selection-color: {tk['on_accent']}; }}"
            f"QLineEdit:focus {{ border: 2px solid {tk['primary']}; }}"
        )
        self.edit.textChanged.connect(lambda _text: self._show_key())
        column.addWidget(self.edit)
        self.status = Text("", "muted", wrap=True)
        column.addWidget(self.status)

        column.addWidget(Text(PRIVACY, "muted", wrap=True))

        buttons = hbox(None, (0, 6, 0, 0), 8)
        buttons.addStretch(1)
        buttons.addWidget(Button("取消", "secondary", on_click=self.reject))
        self.test_button = Button("发测试", "secondary", "send", on_click=self._test)
        buttons.addWidget(self.test_button)
        self.done_button = Button("完成", "primary", on_click=self._done)
        buttons.addWidget(self.done_button)
        column.addLayout(buttons)

        self.tested.connect(self._show_test)
        self._show_key()

    def key(self) -> str:
        return run_notify.clean(self.edit.text())

    # ---------------------------------------------------------------- steps

    def _open_site(self) -> None:
        QDesktopServices.openUrl(QUrl(run_notify.SITE))

    def _say(self, text: str, tone: str = "muted") -> None:
        self.status.set_text(text)
        self.status.setVisible(bool(text))
        set_prop(self.status, "role", tone)

    def _show_key(self) -> None:
        key = self.key()
        usable = run_notify.valid(key)
        self.test_button.setEnabled(usable and not self._sending)
        self.done_button.setEnabled(usable)
        if not key:
            self._say("")
        elif usable:
            self._say(f"✓ {t(KEY_OK)}", "ok")
        else:
            self._say(run_notify.BAD_SHAPE, "bad")

    def _test(self) -> None:
        key = self.key()
        if not run_notify.valid(key) or self._sending:
            return
        self._sending = True
        self.test_button.setEnabled(False)
        self._say(SENDING)
        threading.Thread(
            target=lambda: self.tested.emit(run_notify.send_test(key)),
            name="RunNotifyTest",
            daemon=True,
        ).start()

    def _show_test(self, error: str) -> None:
        self._sending = False
        self.test_button.setEnabled(run_notify.valid(self.key()))
        if error:
            self._say(f"✗ {t(error)}", "bad")
        else:
            self._say(f"✓ {t(SENT)}", "ok")

    def _done(self) -> None:
        if run_notify.valid(self.key()):
            self.accept()


def ask(window: QWidget | None, key: str = "") -> str | None:
    """The SendKey on 完成, ``None`` on 取消."""
    dialog = RunNotifyDialog(key, window)
    if not dialog.exec():
        return None
    return dialog.key()
