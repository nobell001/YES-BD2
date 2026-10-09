"""设置: colours and language first, then notifications, the game and folders.

Leo (2026-10-03) wanted no old pages here: only what he uses, with 颜色 and
语言 right on the page and notifications limited to Windows ones.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from qfluentwidgets import ComboBox

from src.ui.shell import actions, data, theme
from src.ui.shell.page import Page
from src.ui.shell.widgets import (
    Button,
    Card,
    IconLabel,
    IconTile,
    Segmented,
    Separator,
    Text,
    Toggle,
    hbox,
    t,
    vbox,
)
from src.utils import game_sound

THEME_LABELS = {"light": "淡紫", "dark": "深色", "auto": "跟随系统"}
# Each language in its own words.  The project's texts are written in
# Simplified Chinese (Traditional is converted); English, Japanese and Korean
# translate the framework's words and whatever the catalogs cover so far.
LANGUAGE_LABELS = {
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "en_US": "English",
    "ja_JP": "日本語",
    "ko_KR": "한국어",
    "auto": "跟随系统",
}


def _language_enum():
    from ok.ui.qt.common.config import Language

    return {
        "zh_CN": Language.CHINESE_SIMPLIFIED,
        "zh_TW": Language.CHINESE_TRADITIONAL,
        "en_US": Language.ENGLISH,
        "ja_JP": Language.JAPANESE,
        "ko_KR": Language.KOREAN,
        "auto": Language.AUTO,
    }


def language_mode() -> str | None:
    """The saved UI language as a LANGUAGE_LABELS key (None for others)."""
    try:
        from ok.ui.qt.common.config import cfg

        current = cfg.get(cfg.language)
    except Exception:
        return None
    for mode, language in _language_enum().items():
        if language == current:
            return mode
    return None


def set_language_mode(mode: str) -> None:
    from ok.ui.qt.common.config import cfg
    from qfluentwidgets import qconfig

    language = _language_enum().get(mode)
    if language is not None and cfg.get(cfg.language) != language:
        qconfig.set(cfg.language, language)


def _notification_config():
    from ok import og
    from ok.util.GlobalConfig import NOTIFICATION_OPTION_NAME

    global_config = getattr(getattr(og, "executor", None), "global_config", None)
    return global_config.get_config(NOTIFICATION_OPTION_NAME) if global_config else None


def system_notification_on() -> bool:
    from ok.util.GlobalConfig import SYSTEM_NOTIFICATION_ENABLED

    try:
        config = _notification_config()
    except Exception:
        return True
    return bool(config.get(SYSTEM_NOTIFICATION_ENABLED, True)) if config is not None else True


def set_system_notification(on: bool) -> None:
    from ok.util.GlobalConfig import SYSTEM_NOTIFICATION_ENABLED

    config = _notification_config()
    if config is not None:
        config[SYSTEM_NOTIFICATION_ENABLED] = bool(on)


class HubRow(QWidget):
    """Icon, title, one line under it, and a control or an arrow on the right."""

    def __init__(
        self,
        icon_name: str,
        title: str,
        sub: str = "",
        on_click: Callable | None = None,
        control: QWidget | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._on_click = on_click
        layout = hbox(self, (2, 8, 2, 8), 12)
        tile = IconTile(icon_name, 32, 17)
        if on_click is not None and control is None:
            tile.follow_hover(self)
        layout.addWidget(tile)
        texts = vbox(None, (0, 0, 0, 0), 1)
        texts.addWidget(Text(title, "h3"))
        self.sub = Text(sub, "muted", wrap=True)
        self.sub.setVisible(bool(sub))
        texts.addWidget(self.sub)
        layout.addLayout(texts, 1)
        if control is not None:
            layout.addWidget(control)
        elif on_click is not None:
            layout.addWidget(IconLabel("chevron-right", 16, "ink3"))
        if on_click is not None and control is None:
            self.setCursor(Qt.PointingHandCursor)

    def set_sub(self, text: str) -> None:
        self.sub.set_text(text)
        self.sub.setVisible(bool(text))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click is not None:
            self._on_click()
        super().mouseReleaseEvent(event)


class SettingsPage(Page):
    interval = 3000

    def __init__(self, window):
        super().__init__("shellSettings", "设置", "颜色、语言、通知和工具")
        self._window = window

        look = self._section("外观")
        self.theme_switch = Segmented(list(THEME_LABELS), theme.theme_mode(), labels=THEME_LABELS)
        self.theme_switch.changed.connect(theme.set_theme_mode)
        look.addWidget(
            HubRow(
                "sun-moon", "颜色", "淡紫、深色，或跟着 Windows 的设定", control=self.theme_switch
            )
        )
        look.addWidget(Separator())
        self.language_switch = ComboBox()
        for mode, label in LANGUAGE_LABELS.items():
            # Native names stay as written; only 跟随系统 follows the UI language.
            self.language_switch.addItem(t(label) if mode == "auto" else label, userData=mode)
        self.language_switch.setMinimumWidth(150)
        self._show_language()
        self.language_switch.currentIndexChanged.connect(self._language_picked)
        self.language_row = HubRow(
            "languages", "语言", "换了之后重新打开工具才会生效", control=self.language_switch
        )
        look.addWidget(self.language_row)

        notify = self._section("通知")
        self.notify_toggle = Toggle(system_notification_on())
        self.notify_toggle.toggled.connect(set_system_notification)
        notify.addWidget(
            HubRow(
                "bell",
                "系统通知",
                "跑完、出错时在 Windows 右下角跳出通知",
                control=self.notify_toggle,
            )
        )

        self._build_hotkeys()

        game = self._section("游戏")
        login = data.task_by_class_name("AutoLoginTask")
        self.login_toggle = None
        if login is not None:
            self.login_toggle = Toggle(bool(getattr(login, "enabled", False)))
            self.login_toggle.toggled.connect(self._set_login)
            game.addWidget(
                HubRow(
                    "log-in",
                    "自动登录游戏",
                    "游戏开着但还在登录画面时，自动点进主页",
                    control=self.login_toggle,
                )
            )
            game.addWidget(Separator())
        # Leo 2026-10-09: the player chooses; off unless ticked here.
        self.mute_toggle = Toggle(game_sound.enabled())
        self.mute_toggle.toggled.connect(game_sound.set_enabled)
        game.addWidget(
            HubRow(
                "volume-x",
                "跑的时候游戏静音",
                "开跑时关掉游戏声音，跑完恢复",
                control=self.mute_toggle,
            )
        )
        game.addWidget(Separator())
        home_task = data.task_by_name("回到主页")
        if home_task is not None:
            self.home_button = Button(
                "执行",
                "secondary",
                "play",
                size="sm",
                on_click=lambda: actions.start(home_task, self.window()),
            )
            game.addWidget(
                HubRow(
                    "undo-2",
                    "回到主页",
                    "关掉弹窗、按返回，把游戏带回主页（卡住时用）",
                    control=self.home_button,
                )
            )
        else:
            self.home_button = None
            if game.count():
                game.takeAt(game.count() - 1).widget().deleteLater()

        self._build_clone()

        tools = self._section("资料夹")
        tools.addWidget(
            HubRow(
                "scroll-text",
                "日志资料夹",
                "出问题时把这里的档案传给开发者",
                on_click=actions.open_logs,
            )
        )
        tools.addWidget(Separator())
        tools.addWidget(
            HubRow(
                "image",
                "截图资料夹",
                "结算页的图和诊断截图都在这里",
                on_click=lambda: actions.open_folder("screenshots"),
            )
        )
        self.body.addStretch(1)

    def _build_hotkeys(self) -> None:
        """暂停、停止、魔兽录制三个键（Leo 2026-10-09，F6~F12，不能重复）。"""
        from src.ui.shell import hotkeys

        column = self._section("快捷键")
        subs = {
            hotkeys.PAUSE: "跑的时候按一下暂停，再按一下继续",
            hotkeys.STOP: "跑的时候按一下停止",
            hotkeys.RECORD: "魔兽追踪者录制时，每回合排好后按这个键",
        }
        icons = {hotkeys.PAUSE: "pause", hotkeys.STOP: "square", hotkeys.RECORD: "circle-dot"}
        self.hotkey_boxes: dict[str, ComboBox] = {}
        current = hotkeys.keys()
        for index, action in enumerate(hotkeys.ACTIONS):
            if index:
                column.addWidget(Separator())
            box = ComboBox()
            box.addItems(list(hotkeys.KEY_CHOICES))
            box.setCurrentText(current[action])
            box.setFixedWidth(96)
            box.currentTextChanged.connect(
                lambda key, action=action: self._hotkey_picked(action, key)
            )
            self.hotkey_boxes[action] = box
            row = HubRow(icons[action], hotkeys.LABELS[action], subs[action], control=box)
            column.addWidget(row)
        hotkeys.on_changed(self._show_hotkeys)

    def _hotkey_picked(self, action: str, key: str) -> None:
        from src.ui.shell import hotkeys

        hotkeys.set_key(action, key)
        self._show_hotkeys()

    def _show_hotkeys(self) -> None:
        from src.ui.shell import hotkeys

        current = hotkeys.keys()
        for action, box in getattr(self, "hotkey_boxes", {}).items():
            if box.currentText() != current[action]:
                box.blockSignals(True)
                box.setCurrentText(current[action])
                box.blockSignals(False)

    def _build_clone(self) -> None:
        """Only 还原 lives here; 桌面分身 itself starts from 首页 (Leo, 2026-10-03)."""
        from src.utils import clone_desktop

        self._clone = clone_desktop
        self.clone_section = Text("桌面分身", "eyebrow")
        self.body.addWidget(self.clone_section)
        self.clone_card = Card()
        column = vbox(self.clone_card, (16, 8, 16, 8), 0)
        self.body.addWidget(self.clone_card)
        column.addWidget(
            HubRow(
                "rotate-ccw",
                "还原桌面分身",
                "把第一次设定改的 Windows 设定全部改回去",
                control=Button(
                    "还原", "secondary", "rotate-ccw", size="sm", on_click=self._clone_undo
                ),
            )
        )
        self._refresh_clone()

    def _refresh_clone(self) -> None:
        clone = self._clone
        show = clone.supported() and clone.ready() and not clone.in_clone()
        self.clone_section.setVisible(show)
        self.clone_card.setVisible(show)

    def _clone_undo(self) -> None:
        from qfluentwidgets import MessageBox

        box = MessageBox(
            t("还原桌面分身"),
            t("要把桌面分身的设定改回去吗？分身里的游戏和工具会被关掉。"),
            self.window(),
        )
        box.yesButton.setText(t("还原"))
        box.cancelButton.setText(t("取消"))
        if box.exec():
            self._clone.run_setup(undo=True)

    def _section(self, title: str):
        self.body.addWidget(Text(title, "eyebrow"))
        card = Card()
        column = vbox(card, (16, 8, 16, 8), 0)
        self.body.addWidget(card)
        return column

    def _show_language(self) -> None:
        index = list(LANGUAGE_LABELS).index(language_mode() or "auto")
        if self.language_switch.currentIndex() != index:
            self.language_switch.blockSignals(True)
            self.language_switch.setCurrentIndex(index)
            self.language_switch.blockSignals(False)

    def _language_picked(self, index: int) -> None:
        modes = list(LANGUAGE_LABELS)
        if 0 <= index < len(modes):
            set_language_mode(modes[index])
            self._offer_relaunch()

    def _offer_relaunch(self) -> None:
        """A language only loads at start: offer to reopen the tool now."""
        from qfluentwidgets import MessageBox

        if data.busy():
            self.language_row.set_sub("正在跑，跑完后重新打开工具就会换成新语言")
            return
        box = MessageBox(t("换语言"), t("要现在重新打开工具吗？"), self.window())
        box.yesButton.setText(t("现在重开"))
        box.cancelButton.setText(t("等一下"))
        if box.exec():
            from src.ui.shell.relaunch import relaunch

            app = getattr(data.og(), "app", None)
            if app is None or not relaunch(app):
                self.language_row.set_sub("没办法自动重开，请自己关掉工具再打开")

    def _set_login(self, on: bool) -> None:
        login = data.task_by_class_name("AutoLoginTask")
        if login is None:
            return
        if on:
            import threading

            threading.Thread(target=login.enable, name="TaskEnable", daemon=True).start()
        else:
            login.disable()

    def refresh(self) -> None:
        self.theme_switch.set_value(theme.theme_mode())
        self._show_language()
        self.notify_toggle.set_checked_quietly(system_notification_on())
        self.mute_toggle.set_checked_quietly(game_sound.enabled())
        login = data.task_by_class_name("AutoLoginTask")
        if self.login_toggle is not None and login is not None:
            self.login_toggle.set_checked_quietly(bool(getattr(login, "enabled", False)))
        if self.home_button is not None:
            self.home_button.setEnabled(actions.can_start())
        self._show_hotkeys()  # the 魔兽追踪者 page can change the record key
        self._refresh_clone()
