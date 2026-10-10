"""关于: version and app update, a short notice, and the projects we thank.

Replaces ok's old About page (Leo, 2026-10-05): its links all pointed to
the upstream ok-bd2 and its "other projects" grid listed unrelated games.
The update controls are ok's own ``UpdateCard``, moved here from the old
page so the launcher's update check, badge and restart keep working; it only
exists in installs made by the PyAppify launcher, not in a source checkout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ok import Logger
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QWidget
from qfluentwidgets import ScrollArea

from src.ui.shell import update_notes
from src.ui.shell.page import Page, pill, set_pill
from src.ui.shell.widgets import (
    Card,
    IconLabel,
    IconTile,
    Picture,
    Separator,
    Text,
    clear_layout,
    hbox,
    t,
    tf,
    vbox,
)

logger = Logger.get_logger(__name__)

ICON_FILE = Path(__file__).resolve().parents[3] / "icons" / "icon.png"

# The public repository (YES-BD2, Leo 2026-10-08); empty hides the GitHub row.
PROJECT_URL = "https://github.com/nobell001/YES-BD2"

NOTICE = (
    "这个工具免费、开源，不收任何费用。",
    "不是游戏官方的工具，跟游戏公司没有关系。",
    "自动操作有帐号风险，请了解后自己决定要不要用。",
)

SOUSEHA = "https://browndust2-db.souseha.com/"
# souseha's page for each UI language (checked 2026-10-05).
SOUSEHA_PATHS = {"zh_TW": "tw", "zh_HK": "tw", "zh": "cn", "en": "en", "ja": "ja", "ko": "ko"}


@dataclass(frozen=True)
class Credit:
    name: str
    who: str
    what: str
    url: str


# Everything the tool is built on or learned from (code, docs/dev-notes and
# THIRD_PARTY_NOTICES.md checked 2026-10-05).  Names stay as their authors
# write them; ``what`` follows the UI language.
CREDITS = (
    Credit("ok-bd2", "GodRaymond233", "这个工具的起点", "https://github.com/GodRaymond233/ok-bd2"),
    Credit(
        "ok-script", "ok-oldking", "底层框架和一键更新", "https://github.com/ok-oldking/ok-script"
    ),
    Credit(
        "PyQt-Fluent-Widgets",
        "zhiyiYo",
        "界面元件",
        "https://github.com/zhiyiYo/PyQt-Fluent-Widgets",
    ),
    Credit(
        "BetterGI", "babalae", "桌面分身的做法", "https://github.com/babalae/better-genshin-impact"
    ),
    Credit(
        "ChildStream", "mattxslv", "桌面分身的画面窗口", "https://github.com/mattxslv/childstream"
    ),
    Credit("MaaBD2", "JZPPP", "跑图路线的想法", "https://github.com/JZPPP/MaaBD2"),
    Credit("BD2DB 图鉴", "souseha", "游戏名称、角色和装备资料", SOUSEHA),
    Credit(
        "跑商售卖物品表",
        "時樂淵 · bilibili",
        "跑商要卖哪些东西",
        "https://space.bilibili.com/14949646",
    ),
    Credit("OnnxOCR / PP-OCRv5", "ok-oldking", "文字辨识", "https://github.com/ok-oldking/OnnxOCR"),
    Credit("OpenCC", "BYVoid", "简繁转换", "https://github.com/BYVoid/OpenCC"),
    Credit(
        "思源黑体 Noto Sans",
        "Google",
        "界面字体（SIL OFL 1.1）",
        "https://fonts.google.com/noto/specimen/Noto+Sans+TC",
    ),
)


def _locale() -> str:
    try:
        from ok import og

        from src.ui.traditional import _locale_name

        return _locale_name(getattr(og, "app", None))
    except Exception:
        return ""


def souseha_url(locale_name: str | None = None) -> str:
    name = _locale() if locale_name is None else locale_name
    for prefix in (name, name.split("_")[0]):
        if prefix in SOUSEHA_PATHS:
            return f"{SOUSEHA}{SOUSEHA_PATHS[prefix]}/"
    return SOUSEHA


def open_url(url: str) -> None:
    if url == SOUSEHA:
        url = souseha_url()
    QDesktopServices.openUrl(QUrl(url))


class LinkRow(QWidget):
    """Icon, a title (with a quiet name beside it), one line, and an arrow."""

    def __init__(self, icon_name: str, title: str, who: str, sub: str, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        layout = hbox(self, (2, 8, 2, 8), 12)
        tile = IconTile(icon_name, 30, 15)
        tile.follow_hover(self)
        layout.addWidget(tile)
        texts = vbox(None, (0, 0, 0, 0), 1)
        top = hbox(None, (0, 0, 0, 0), 6)
        top.addWidget(Text(title, "h3"))
        if who:
            top.addWidget(Text(who, "muted"))
        top.addStretch(1)
        texts.addLayout(top)
        texts.addWidget(Text(sub, "muted", wrap=True))
        layout.addLayout(texts, 1)
        layout.addWidget(IconLabel("chevron-right", 16, "ink3"))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(url)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            open_url(self.url)
        super().mouseReleaseEvent(event)


class NotesBox(Card):
    """A version title over note lines that scroll inside a fixed height."""

    MAX_LIST_HEIGHT = 260

    def __init__(self, parent=None):
        super().__init__(parent)
        column = vbox(self, (16, 12, 8, 12), 8)
        self.title = Text("", "h3")
        column.addWidget(self.title)
        self.scroll = ScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(ScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.holder = QWidget()
        self.holder.setStyleSheet("background: transparent;")
        self.lines = vbox(self.holder, (0, 0, 8, 0), 4)
        self.scroll.setWidget(self.holder)
        column.addWidget(self.scroll)
        self.rows: list[Text] = []

    def set_notes(self, title: str, lines: list[str]) -> None:
        self.title.set_text(title)
        clear_layout(self.lines)
        self.rows = []
        for line in lines:
            row = hbox(None, (0, 0, 0, 0), 8)
            dot = Text("•")
            dot.setAlignment(Qt.AlignTop)
            row.addWidget(dot, 0, Qt.AlignTop)
            text = Text(line, wrap=True)
            row.addWidget(text, 1)
            self.lines.addLayout(row)
            self.rows.append(text)
        self._fit()

    def _fit(self) -> None:
        """As tall as the lines, up to MAX_LIST_HEIGHT; past that it scrolls."""
        width = self.scroll.viewport().width() or self.width()
        layout = self.lines
        wanted = (
            layout.heightForWidth(width) if layout.hasHeightForWidth() else -1
        )
        if wanted < 0:
            wanted = layout.sizeHint().height()
        self.scroll.setFixedHeight(max(1, min(wanted, self.MAX_LIST_HEIGHT)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class AboutPage(Page):
    interval = 5000

    def __init__(self, window, sidebar=None):
        super().__init__("shellAbout", "关于", "版本、更新和致谢")
        self._window = window
        self._sidebar = sidebar
        self.update_card = None
        self._build_version()
        self._build_version_change()
        self._build_notice()
        self._build_credits()
        self.body.addStretch(1)

    # ---------------------------------------------------------- 版本

    def _section(self, title: str):
        self.body.addWidget(Text(title, "eyebrow"))
        card = Card()
        column = vbox(card, (16, 8, 16, 8), 0)
        self.body.addWidget(card)
        return column

    def _build_version(self) -> None:
        from ok import og

        config = getattr(og, "config", None) or {}
        column = self._section("版本")
        row = QWidget()
        layout = hbox(row, (2, 8, 2, 8), 14)
        logo = Picture(str(ICON_FILE) if ICON_FILE.exists() else None, radius=10)
        logo.setFixedSize(44, 44)
        layout.addWidget(logo)
        texts = vbox(None, (0, 0, 0, 0), 1)
        texts.addWidget(Text(str(config.get("gui_title") or "YES-BD2"), "h3"))
        self.version_text = Text(tf("版本 {version}", version=config.get("version") or ""), "muted")
        texts.addWidget(self.version_text)
        layout.addLayout(texts, 1)
        self.update_pill = pill()
        self.update_pill.hide()
        layout.addWidget(self.update_pill)
        column.addWidget(row)

        card = getattr(getattr(self._window, "about_tab", None), "update_card", None)
        if card is not None:
            # ok's own controls (check, pick a version, update, notes): moved,
            # not copied, so MainWindow's scheduled check and badge still use it.
            column.addWidget(Separator())
            card.setParent(None)
            holder = QWidget()
            hbox(holder, (2, 8, 2, 8), 0).addWidget(card)
            column.addWidget(holder)
            self.update_card = card
            try:
                card.update_available_changed.connect(self._update_available)
            except Exception as exc:
                logger.warning(f"about page: no update signal ({exc})")

        if PROJECT_URL:
            column.addWidget(Separator())
            column.addWidget(LinkRow("code", "GitHub", "", "源代码、下载、回报问题", PROJECT_URL))

    def _update_available(self, available: bool) -> None:
        set_pill(self.update_pill, "有新版本" if available else "", "run" if available else None)
        if self._sidebar is not None and "about" in getattr(self._sidebar, "items", {}):
            self._sidebar.items["about"].set_badge(t("新") if available else "")

    def check_for_updates(self) -> None:
        if self.update_card is not None:
            self.update_card.check_for_updates()

    def _build_version_change(self) -> None:
        """更新内容: one scrolling list with a dot on every line (Leo 10-10).

        It shows what the last update brought (the launcher reopens the
        tool here after one), else what this version brought, and follows
        the version picked in the update controls.  The controls' own notes
        stay hidden so the list is never shown twice.
        """
        self._notes = update_notes.load()
        self._startup = None
        try:
            from ok.ui.qt.util.pyappify_startup import get_startup_version_change

            self._startup = get_startup_version_change()
        except Exception:
            self._startup = None
        self.notes_label = Text("更新内容", "eyebrow")
        self.body.addWidget(self.notes_label)
        self.notes_box = NotesBox()
        self.body.addWidget(self.notes_box)
        card = self.update_card
        if card is not None and hasattr(card, "_set_notes"):
            notes_edit = getattr(card, "notes_edit", None)
            if notes_edit is not None:
                notes_edit.hide()
                notes_edit.setMaximumHeight(0)
            card._set_notes = self._picked_version_notes
        self._show_default_notes()

    def _current_version(self) -> str:
        from ok import og

        config = getattr(og, "config", None) or {}
        card_version = getattr(self.update_card, "current_version", "") if self.update_card else ""
        return str(card_version or config.get("version") or "")

    def _show_notes(self, title: str, lines: list[str]) -> None:
        self.notes_box.set_notes(title, lines)
        self.notes_label.setVisible(bool(lines))
        self.notes_box.setVisible(bool(lines))

    def _show_default_notes(self) -> None:
        change = self._startup
        if change and getattr(change, "from_version", None):
            old, new = change.from_version, change.to_version
            lines = update_notes.notes_between(self._notes, old, new)
            if lines is None:
                lines = update_notes.split_lines(getattr(change, "content", "") or "")
            self._show_notes(f"{old} → {new}", lines)
            return
        current = self._current_version()
        lines = update_notes.notes_between(self._notes, None, current) or []
        if not lines and change:
            lines = update_notes.split_lines(getattr(change, "content", "") or "")
        self._show_notes(current, lines)

    def _picked_version_notes(self, text: str) -> None:
        """Stands in for the update controls' notes: they land in 更新内容."""
        card = self.update_card
        combo = getattr(card, "version_combo", None)
        target = combo.currentText() if combo is not None else ""
        current = self._current_version()
        same = update_notes.version_key(target) == update_notes.version_key(current)
        if not text or not target or same:
            self._show_default_notes()
            return
        lines = update_notes.notes_between(self._notes, current, target)
        if lines is None:
            lines = update_notes.split_lines(text)
        self._show_notes(f"{current} → {target}", lines)

    # ---------------------------------------------------------- 使用须知 / 致谢

    def _build_notice(self) -> None:
        column = self._section("使用须知")
        for line in NOTICE:
            column.addWidget(Text(f"•  {t(line)}", "sub", wrap=True))

    def _build_credits(self) -> None:
        column = self._section("致谢（参考或使用了这些项目）")
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.credit_rows: list[LinkRow] = []
        rows = (len(CREDITS) + 1) // 2
        for index, credit in enumerate(CREDITS):
            line, col = divmod(index, 2)
            row = LinkRow("star", credit.name, credit.who, credit.what, credit.url)
            self.credit_rows.append(row)
            grid.addWidget(row, line * 2, col)
            if line < rows - 1:
                grid.addWidget(Separator(), line * 2 + 1, col)
        column.addWidget(grid_host)
