"""首页: today at a glance; while a run goes, the run; after it, the 结算."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QSizePolicy, QWidget

from src.tasks import problem_report, run_report
from src.tasks.BaseBD2Task import task_info_snapshot
from src.tasks.map_trade import account_check
from src.ui.shell import (
    accounts_ui,
    actions,
    autorun,
    clone_flow,
    data,
    hotkeys,
    motion,
    run_confirm,
    theme,
)
from src.ui.shell.page import Page
from src.ui.shell.problem_page import ProblemCard
from src.utils import accounts
from src.ui.shell.safe import guarded
from src.ui.shell.trade_line import TradeLine
from src.ui.shell.widgets import (
    Bar,
    Button,
    Card,
    CheckBox,
    IconTile,
    Picture,
    Ring,
    SegBar,
    Segmented,
    Separator,
    StateIcon,
    Text,
    clear_layout,
    draw_fitted,
    fmt_clock,
    fmt_duration,
    fmt_minutes,
    grid_container,
    hbox,
    mix,
    t,
    tf,
    vbox,
)
from src.utils import clone_desktop

ENDED_TEXT = {
    run_report.ENDED_DONE: "全部完成",
    run_report.ENDED_FAILED: "有项目失败",
    run_report.ENDED_ABORTED: "中途停了",
    run_report.ENDED_STOPPED: "手动停止",
    run_report.ENDED_ERROR: "出错停了",
    run_report.ENDED_SETUP: "没有开始跑",
}
SUMMARY_TITLE = {
    run_report.ENDED_DONE: "跑完了",
    run_report.ENDED_FAILED: "跑完了，有项目失败",
    run_report.ENDED_ABORTED: "中途停了",
    run_report.ENDED_STOPPED: "手动停止了",
    run_report.ENDED_ERROR: "出错停了",
    run_report.ENDED_SETUP: "没有开始跑",
}


def stopped_name(row: dict) -> str:
    """Short name of the item a stopped run will continue from."""
    key = str(row.get("key") or "")
    short = data.CHILD_META.get(key, ("",))[0]
    return t(short or str(row.get("name") or key))


def summary_switch_text(label: str) -> str:
    """「一键完成日常」 -> 「日常的结果」 for the summary's run switch."""
    short = label.removeprefix("一键完成") or label
    return f"{short}的结果"


class ClickableCard(Card):
    def __init__(self, parent=None, tone: str | None = None, on_click: Callable | None = None):
        super().__init__(parent, tone)
        self._on_click = on_click
        self.hover = None
        if on_click is not None:
            self.setCursor(Qt.PointingHandCursor)
            # Hovered: the edge tints violet (the icon inside grows, see follow_hover).
            self.hover = motion.HoverFade(self, self.update)

    def edge_colour(self):
        base = super().edge_colour()
        if self.hover is None or self.hover.value <= 0:
            return base
        return mix(base, theme.color("primary"), 0.45 * self.hover.value)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click is not None:
            self._on_click()
        super().mouseReleaseEvent(event)


class StatCard(ClickableCard):
    """Icon + label, a big number, a thin bar and one line under it."""

    def __init__(self, icon_name: str, label: str, kind: str, on_click=None, parent=None):
        super().__init__(parent, on_click=on_click)
        self.kind = kind
        layout = vbox(self, (16, 14, 16, 14), 8)
        head = hbox(None, (0, 0, 0, 0), 8)
        tile = IconTile(icon_name, 28, 16, kind=kind)
        tile.follow_hover(self)
        head.addWidget(tile)
        head.addWidget(Text(label, "sub"), 1)
        layout.addLayout(head)
        value_row = hbox(None, (0, 0, 0, 0), 6)
        self.value = Text("", "big")
        self.value.animate_changes()
        self.unit = Text("", "muted")
        value_row.addWidget(self.value)
        value_row.addWidget(self.unit, 1, Qt.AlignBottom)
        layout.addLayout(value_row)
        self.bar = Bar(height=6)
        layout.addWidget(self.bar)
        self.foot = Text("", "muted", elide=True)
        layout.addWidget(self.foot)

    def set(self, value: str, unit: str, fraction: float, foot: str, full: bool = False) -> None:
        self.value.set_text(value)
        self.unit.set_text(unit)
        # Violet even when full (Leo's draft, 2026-10-05).
        self.bar.set_value(fraction, "primary")
        self.foot.set_text(foot)


class BoardTile(ClickableCard):
    """One daily item: the check in the corner decides whether 一键完成日常 runs it,
    a click anywhere else opens its settings (Leo, 2026-10-08)."""

    def __init__(self, child: data.Child, on_click=None, on_include=None, parent=None):
        super().__init__(parent, on_click=on_click)
        self.child = child
        layout = vbox(self, (12, 12, 12, 10), 6)
        top = hbox(None, (0, 0, 0, 0), 0)
        self.tile = IconTile(child.icon, 30, 17, kind=child.kind)
        self.tile.follow_hover(self)
        top.addWidget(self.tile)
        top.addStretch(1)
        self.include = CheckBox("", child.included, box=20)
        self.include.setFixedSize(26, 26)
        self.include.setToolTip(t("勾选：一键完成日常会跑这项"))
        if on_include is not None:
            self.include.toggled.connect(lambda on, key=child.key: on_include(key, on))
        top.addWidget(self.include, 0, Qt.AlignTop)
        layout.addLayout(top)
        # a little air between the icon and the name (Leo, 2026-10-05)
        layout.addSpacing(10)
        self.name = Text(child.short, "h3", elide=True)
        layout.addWidget(self.name)
        state = hbox(None, (0, 0, 0, 0), 4)
        self.mark = StateIcon("done", 13)
        self.state = Text("", "muted", elide=True)
        state.addWidget(self.mark)
        state.addWidget(self.state, 1)
        layout.addLayout(state)
        layout.addStretch(1)

    def set_included(self, included: bool) -> None:
        self.include.set_checked_quietly(included)

    def set_state(self, kind: str, text: str) -> None:
        self.mark.setVisible(kind in ("done", "fail"))
        if kind in ("done", "fail"):
            self.mark.set_state(kind)
        self.state.set_text(text)
        self.state.set_role("ok" if kind == "done" else "muted")
        self.tile.set_off(kind == "off")
        self.name.set_role("muted" if kind == "off" else "h3")
        self.set_tone("done" if kind == "done" else "")


class RunRow(QWidget):
    """State icon, task name with a short reason under it, and its time."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._state = "wait"
        layout = hbox(self, (8, 7, 8, 7), 10)
        self.icon = StateIcon("wait", 17)
        layout.addWidget(self.icon, 0, Qt.AlignTop)
        texts = vbox(None, (0, 0, 0, 0), 1)
        self.name = Text(name, "h3", elide=True)
        self.note = Text("", "muted", wrap=True)
        self.note.hide()
        texts.addWidget(self.name)
        texts.addWidget(self.note)
        self.trade = TradeLine()
        texts.addWidget(self.trade)
        layout.addLayout(texts, 1)
        self.time = Text("", "muted")
        layout.addWidget(self.time, 0, Qt.AlignTop)

    def set(self, state: str, note: str, time_text: str, trade: dict | None = None) -> None:
        if state != self._state:
            self._state = state
            self.update()
        self.icon.set_state(state)
        self.name.set_role("muted" if state == "wait" else "h3")
        self.note.set_text(note)
        self.note.setVisible(bool(note))
        self.note.set_role("bad" if state == "fail" else "muted")
        self.trade.set_trade(trade)
        self.time.set_text(time_text)

    def paintEvent(self, _event):
        # The row that is running now stands out, like a selected list row.
        if self._state != "run":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("row_on"))
        painter.drawRoundedRect(QRectF(self.rect()), theme.corner(5), theme.corner(5))


class Timeline(Card):
    """All rows of a run, top to bottom."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = vbox(self, (14, 8, 14, 8), 0)
        self._keys: list[str] = []
        self._rows: dict[str, RunRow] = {}

    def set_rows(self, rows: list[dict], now: float | None = None) -> None:
        keys = [str(row.get("key")) for row in rows]
        if keys != self._keys:
            clear_layout(self.layout_)
            self._rows = {}
            for index, row in enumerate(rows):
                if index:
                    self.layout_.addWidget(Separator())
                widget = RunRow(str(row.get("name") or row.get("key")))
                self._rows[str(row.get("key"))] = widget
                self.layout_.addWidget(widget)
            self._keys = keys
        now = time.time() if now is None else now
        for row in rows:
            widget = self._rows.get(str(row.get("key")))
            if widget is None:
                continue
            state = row.get("state") or "wait"
            if state == "run" and row.get("started"):
                time_text = fmt_clock(now - row["started"])
            elif row.get("duration") is not None:
                time_text = fmt_clock(row["duration"])
            else:
                time_text = ""
            widget.set(state, str(row.get("note") or ""), time_text, row.get("trade"))


class PictureDialog(QDialog):
    """A picture filling most of the window; any click closes it."""

    def __init__(self, path: str, parent=None, pixmap: QPixmap | None = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self._pixmap = pixmap if pixmap is not None else QPixmap(path)
        # Opens with a short fade, the picture rising a little into place.
        self._open = motion.Tween(self, self.update, 200, 0.0)
        if parent is not None:
            window = parent.window()
            self.setGeometry(window.geometry())

    def showEvent(self, event):
        super().showEvent(event)
        self._open.go(1.0)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        shown = float(self._open.value)
        painter.fillRect(self.rect(), theme.color("shot", 0.86 * shown))
        if self._pixmap.isNull():
            return
        painter.setOpacity(shown)
        area = QRectF(self.rect().adjusted(40, 40, -40, -40)).translated(0, 12 * (1 - shown))
        draw_fitted(painter, area, self._pixmap, self.devicePixelRatioF())

    def mouseReleaseEvent(self, event):
        self.accept()

    def keyPressEvent(self, event):
        self.accept()


class LiveView(QWidget):
    """The game picture during a run (the start page's live preview, slower)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from src.ui.live_screenshot import LiveScreenshotWidget

        layout = vbox(self, (0, 0, 0, 0), 0)
        self.live = LiveScreenshotWidget()
        # Twice a second, reusing the running task's own frames; while the task
        # waits, one extra screenshot a second at most (each costs more with
        # Windows HDR on).
        self.live.timer.setInterval(500)
        self.live.reuse_frame_age = 0.6
        self.live.own_capture_gap = 1.0
        self.live.status_label.hide()
        layout.addWidget(self.live)
        self.tag = QLabel(self.live.preview)
        self.tag.move(10, 10)
        self._remote_path = None
        self._remote_timer = QTimer(self)
        self._remote_timer.timeout.connect(guarded("clone live picture", self._load_remote))
        self.apply_style()
        theme.on_theme_changed(self, self.apply_style)

    def apply_style(self) -> None:
        shot = theme.tokens()["shot"]
        self.live.preview.setStyleSheet(
            f"QLabel {{ background-color: {shot}; border-radius: {theme.radius()}px;"
            " color: rgba(255, 255, 255, 150); }"
        )
        self.tag.setText(data.tr("实时画面"))
        self.tag.setStyleSheet(
            "QLabel { color: #FFFFFF; background: rgba(0, 0, 0, 0.55); border-radius: 4px;"
            " padding: 2px 8px; font-size: 11px; }"
        )
        self.tag.adjustSize()

    def set_remote(self, path) -> None:
        """Show the picture the tool in the 桌面分身 writes instead of capturing here.

        This tool cannot see a game window on another Windows session.  The
        picture is read four times a second, as often as the clone writes it
        (once a second with the page looked laggy, Leo 2026-10-07).
        """
        if path is None:
            self._remote_timer.stop()
            self._remote_path = None
            if self._remote_stamp is not None:
                self._remote_stamp = None
                if self.isVisible():
                    self.live.start_preview()
            return
        if self.live.timer.isActive():
            # Shown again: the local preview restarted and drew over the picture.
            self._remote_stamp = None
        self.live.stop_preview()
        self._remote_path = path
        if not self._remote_timer.isActive():
            self._remote_timer.start(250)
        self._load_remote()

    def _load_remote(self) -> None:
        path = self._remote_path
        if path is None or not self.isVisible():
            return
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return
        if stamp == self._remote_stamp:
            return
        image = QImage(str(path))
        if not image.isNull():
            self._remote_stamp = stamp
            self.live.preview.set_image(image)

    _remote_stamp: float | None = None


# How long a 「调整」 result stays before the live window size shows again.
MESSAGE_SECONDS = 8.0
GAME_SIZES = {(1920, 1080): "1080p", (2560, 1440): "2K", (3840, 2160): "4K"}


class GameSizeCard(Card):
    """Resize the game window to a common size (moved here from the old 开始 page).

    Gives ``ManualResolutionController`` the three things it drives:
    ``apply_button``, ``selected_resolution`` and ``set_status``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from qfluentwidgets import ComboBox

        from src.ui.manual_resolution import (
            DEFAULT_MANUAL_RESOLUTION,
            MANUAL_RESOLUTIONS,
            ManualResolutionController,
            format_resolution,
        )

        self._format = format_resolution
        # Only the three sizes the tool is built and tested for (Leo, 2026-10-03).
        self._sizes = tuple(size for size in GAME_SIZES if size in MANUAL_RESOLUTIONS)
        row = hbox(self, (18, 12, 18, 12), 12)
        row.addWidget(IconTile("monitor", 32, 17))
        texts = vbox(None, (0, 0, 0, 0), 1)
        texts.addWidget(Text("游戏视窗大小", "h3"))
        self.status = Text("", "muted", wrap=True)
        texts.addWidget(self.status)
        row.addLayout(texts, 1)
        self.combo = ComboBox(self)
        for size in self._sizes:
            self.combo.addItem(f"{GAME_SIZES[size]} · {format_resolution(size)}", userData=size)
        self.combo.setCurrentIndex(self._sizes.index(DEFAULT_MANUAL_RESOLUTION))
        self.combo.setMinimumWidth(150)
        row.addWidget(self.combo)
        self.apply_button = Button("调整", "secondary", size="sm")
        row.addWidget(self.apply_button)
        self.controller = ManualResolutionController(self)
        self.apply_button.clicked.connect(self.controller.apply_selected_resolution)
        self.combo.currentIndexChanged.connect(self._picked)
        self._message = ""
        self._message_at = 0.0
        # Until someone picks a size, the list follows the game window.
        self._user_picked = False

    @property
    def selected_resolution(self) -> tuple[int, int]:
        value = self.combo.currentData()
        return int(value[0]), int(value[1])

    def _picked(self, _index: int) -> None:
        self._user_picked = True

    def set_status(self, status: str) -> None:
        self._message = status
        self._message_at = time.monotonic()
        self.status.set_text(status)

    def _live_size(self) -> tuple[int, int] | None:
        """The game window's size right now, as the sidebar shows it."""
        from ok import og

        window = getattr(getattr(og, "device_manager", None), "hwnd_window", None)
        width = int(getattr(window, "width", 0) or 0)
        height = int(getattr(window, "height", 0) or 0)
        if window is not None and getattr(window, "exists", False) and width and height:
            return width, height
        return None

    def refresh(self) -> None:
        # A result from 「调整」 stays a few seconds, then the live size takes
        # over: the window can change size later (Leo 2026-10-03 saw an old
        # "1920 × 1080" result next to a 4K window).
        if self._message:
            if self.controller.busy or time.monotonic() - self._message_at < MESSAGE_SECONDS:
                return
            self._message = ""
        size = self._live_size()
        if size is None:
            self.status.set_text("游戏开着时，选好大小按「调整」")
            return
        self.status.set_text(tf("现在 {size}，选好大小按「调整」", size=self._format(size)))
        if not self._user_picked and size in self._sizes:
            index = self._sizes.index(size)
            if self.combo.currentIndex() != index:
                self.combo.blockSignals(True)
                self.combo.setCurrentIndex(index)
                self.combo.blockSignals(False)


# 停止 with nothing to see here (桌面分身, login wait): how long the
# 「正在停止…」 button stays grey before it can be pressed again.
STOP_GRACE_SECONDS = 20


class HomePage(Page):
    interval = 1000

    def __init__(self, open_task: Callable[[str, str], None], navigate: Callable[[str], None]):
        super().__init__("shellHome", "今天")
        self._open_task = open_task
        self._navigate = navigate
        self._mode = ""
        self._summary: dict | None = None
        self._watching_label: str | None = None
        self._watching_started: float | None = None
        self._logs: deque = deque(maxlen=3)
        self._last_log = ""

        # GitHub issue #4: which game account the records and ticks belong to.
        self.account_chip = self.add_action(accounts_ui.AccountChip(self._account_switched))
        self._asking_account = False
        self.pause_button = self.add_action(
            Button("暂停", "secondary", "pause", on_click=self._pause)
        )
        self.stop_button = self.add_action(Button("停止", "danger", "square", on_click=self._stop))
        # Leo 2026-10-10: a press shows at once, or the player keeps pressing.
        self._stop_pressed_at: float | None = None
        self.logs_button = self.add_action(
            Button("看日志", "secondary", "scroll-text", on_click=actions.open_logs)
        )
        # Leo 2026-10-06: after a manual Stop, pick up where it stopped.
        self.resume_summary_button = self.add_action(
            Button("", "primary", "play", on_click=self._resume_summary)
        )
        self.home_button = self.add_action(
            Button("回首页", "primary", "house", on_click=self._close_summary)
        )

        self.idle = QWidget(self.view)
        self.running = QWidget(self.view)
        self.summary = QWidget(self.view)
        for view in (self.idle, self.running, self.summary):
            self.body.addWidget(view)
            view.hide()
        self.body.addStretch(1)
        self._build_idle()
        self._build_running()
        self._build_summary()

    # ================================================================ idle

    def _build_idle(self) -> None:
        layout = vbox(self.idle, (0, 0, 0, 0), 16)
        # A plain card like the rest: filled with lime it was too loud.
        self.hero = Card()
        hero = hbox(self.hero, (24, 20, 24, 20), 24)
        self.ring = Ring(118, 11)
        hero.addWidget(self.ring)
        texts = vbox(None, (0, 0, 0, 0), 4)
        texts.addStretch(1)
        texts.addWidget(Text("今日日常", "eyebrow"))
        self.hero_title = Text("", "huge")
        self.hero_sub = Text("", "sub", wrap=True)
        texts.addWidget(self.hero_title)
        texts.addWidget(self.hero_sub)
        # Leo 2026-10-05: the report right under the day's state, as a button.
        report_row = hbox(None, (0, 8, 0, 0), 0)
        self.report_button = Button(
            "看今日报表",
            "secondary",
            "list-checks",
            on_click=lambda: self._navigate("report"),
        )
        report_row.addWidget(self.report_button)
        report_row.addStretch(1)
        texts.addLayout(report_row)
        texts.addStretch(1)
        hero.addLayout(texts, 1)
        buttons = vbox(None, (0, 0, 0, 0), 6)
        self.resume = Button(
            "", "primary", "play", "lg", on_click=lambda: self._start_batch(data.DAILY_BATCH, False)
        )
        # Leo 2026-10-09: both starts open a window to pick 跑勾选的 or
        # 跑没跑完的 and confirm the ticks (it replaced 「只跑剩下的 N 项」).
        self.start_all = Button(
            "一键完成日常", "primary", "play", "lg", on_click=self._confirm_and_start
        )
        # Leo (2026-10-03): a separate start for 桌面分身, no mode switch.
        self.start_clone = Button(
            "在桌面分身跑",
            "secondary",
            "monitor",
            on_click=self._start_in_clone,
        )
        self.start_clone.setToolTip(
            t("纯后台执行：游戏在独立的分身窗口里跑，缩小也照跑；你照常用电脑，鼠标键盘不会被抢")
        )
        self.start_clone.setVisible(clone_flow.available())
        # Shown while 「打开就自动跑日常」 counts down (Leo 2026-10-09).
        self.cancel_autorun = Button("取消自动开始", "secondary", on_click=self._cancel_autorun)
        self.cancel_autorun.hide()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_autorun)
        buttons.addWidget(self.resume)
        buttons.addWidget(self.start_all)
        buttons.addWidget(self.start_clone)
        # The 「别动键盘和鼠标」 line moved into that window (Leo 2026-10-09).
        # Leo 2026-10-09: the player chooses here whether opening the tool runs it.
        self.autorun_box = CheckBox("打开就自动跑日常", autorun.enabled())
        self.autorun_box.setToolTip(
            t("打开启动器或工具后自动开始一键日常，只跑今天还没做的；游戏没开会自己打开并登录")
        )
        self.autorun_box.toggled.connect(autorun.set_enabled)
        buttons.addWidget(self.autorun_box, 0, Qt.AlignHCenter)
        buttons.addStretch(1)
        hero.addLayout(buttons)
        layout.addWidget(self.hero)

        stats, grid = grid_container(200, 12, 3)
        # 本周周常 is gone: the 周常 are tiles of 一键日常 now (Leo 2026-10-09).
        self.map_card = StatCard("map", "本周跑图", "map", lambda: self._navigate("map"))
        # Leo 2026-10-05: not only the last run; the card opens 今日报表.
        self.last_card = StatCard(
            "list-checks", "今日报表", "plain", lambda: self._navigate("report")
        )
        for card in (self.map_card, self.last_card):
            grid.addWidget(card)
        layout.addWidget(stats)

        head = hbox(None, (2, 6, 2, 0), 14)
        head.addWidget(Text("今日任务", "h2"))
        head.addStretch(1)
        for state, label in (("done", "已完成"), ("wait", "未完成"), ("off", "不在一键日常里")):
            head.addWidget(StateIcon(state, 13))
            head.addWidget(Text(label, "muted"))
        layout.addLayout(head)
        self.tiles_box, self.tiles = grid_container(118, 10, None, 104)
        layout.addWidget(self.tiles_box)
        # Leo 2026-10-09: the 周常 in a row of their own; 一键日常 still runs them.
        self.week_head = QWidget()
        week_head = hbox(self.week_head, (2, 6, 2, 0), 14)
        week_head.addWidget(Text("本周任务", "h2"))
        self.week_note = Text("", "muted")
        week_head.addWidget(self.week_note)
        week_head.addStretch(1)
        layout.addWidget(self.week_head)
        self.week_box, self.week_tiles = grid_container(118, 10, None, 104)
        layout.addWidget(self.week_box)
        self.game_size = GameSizeCard()
        layout.addWidget(self.game_size)
        self._tile_keys: list[str] = []
        self._tiles: dict[str, BoardTile] = {}
        # (when, account id, progress): a switched account reads its own.
        self._map_cache: tuple[float, str, object] = (0.0, "", None)

    def _refresh_idle(self) -> None:
        self.set_eyebrow("")
        self.set_title("今天")
        self.set_sub(
            tf("{today} · 下次刷新 {next}", today=data.today_title(), next=data.next_refresh_text())
        )
        self.game_size.refresh()
        batch = data.task_by_name(data.DAILY_BATCH)
        data.sync_weekly_ticks(batch)
        children = data.batch_children(batch)
        included = [child for child in children if child.included]
        done = [child for child in included if data.child_done(child)]
        remaining = [child for child in included if not data.child_done(child)]
        self.ring.set_progress(len(done), len(included))
        busy = data.busy()
        if not included:
            self.hero_title.set_text("一键日常里没有项目")
            self.hero_sub.set_text("到「任务设定」把要跑的项目加进一键日常")
        elif remaining:
            self.hero_title.set_text(tf("还剩 {n} 项", n=len(remaining)))
            estimate = data.estimate_seconds(child.name for child in remaining)
            self.hero_sub.set_text(
                tf("预计 {time}（照上次的用时估算）", time=fmt_minutes(estimate))
                if estimate
                else "第一次跑，跑完就知道要多久"
            )
        else:
            self.hero_title.set_text("今天的日常都做完了")
            self.hero_sub.set_text(tf("下次刷新 {next}", next=data.next_refresh_text()))
        stopped = (
            run_report.stopped_row(run_report.load(data.DAILY_BATCH)) if remaining else None
        )
        self.resume.setVisible(stopped is not None)
        self.start_all.set_kind("secondary" if stopped else "primary")
        if stopped is not None:
            name = stopped_name(stopped)
            self.hero_sub.set_text(tf("上次在「{name}」手动停止，做完的不会再跑", name=name))
            self.resume.set_label(tf("从「{name}」继续", name=name))
        if clone_flow.busy_in_clone():
            # The tool on the 桌面分身 is running; this one shows its progress.
            self.hero_sub.set_text("工具正在桌面分身里跑，这里会跟着更新")
            busy = True
        self.start_all.setEnabled(not busy and batch is not None)
        self.resume.setEnabled(not busy and batch is not None)
        # Still usable then: the tool in the clone takes the run when it is free.
        self.start_clone.setEnabled(not data.busy())
        self.autorun_box.set_checked_quietly(autorun.enabled())
        # Leo 2026-10-09: players must see that it is about to start by itself.
        left = autorun.seconds_left()
        self.cancel_autorun.setVisible(left is not None)
        if left is not None:
            self.hero_title.set_text("马上自动开始一键日常")
            self.hero_sub.set_text(tf("{n} 秒后开始，不想跑就按「取消自动开始」", n=left))

        stamp, cached_for, progress = self._map_cache
        account_id = accounts.current_id()
        if time.time() - stamp > 15 or cached_for != account_id:
            progress = data.map_progress()
            self._map_cache = (time.time(), account_id, progress)
        if progress is not None and progress.cards:
            cards = len(progress.cards)
            self.map_card.set(
                str(progress.cards_done),
                tf("/ {n} 张卡带", n=cards),
                progress.cards_done / cards,
                tf("地图 {done} / {total} 张", done=progress.maps_done, total=progress.maps_total),
                progress.cards_done == cards,
            )
        else:
            self.map_card.set("-", "", 0, "还没有跑图记录")

        from src.tasks import run_log

        groups = run_log.group_by_task(run_log.entries())
        if groups:
            done = sum(
                1 for _name, runs in groups if any(r.get("state") == run_log.DONE for r in runs)
            )
            failed = sum(
                1
                for _name, runs in groups
                if not any(r.get("state") == run_log.DONE for r in runs)
                and runs[-1].get("state") == run_log.FAIL
            )
            last = max((r.get("finished") or 0) for _name, runs in groups for r in runs)
            self.last_card.set(
                str(len(groups)),
                tf("项 · 最后 {time}", time=data.clock_text(last)),
                done / max(1, len(groups)),
                tf("完成 {done} 项 · 失败 {failed} 项 · 点这里看全部", done=done, failed=failed),
                failed == 0,
            )
        else:
            self.last_card.set("-", "今天还没跑", 0, "跑完会在这里看到今天的结果")

        keys = [child.key for child in children]
        if keys != self._tile_keys:
            for tile in self._tiles.values():
                tile.setParent(None)
                tile.deleteLater()
            self._tiles = {}
            for child in children:
                tile = BoardTile(
                    child,
                    on_click=lambda key=child.key: self._open_task("daily", key),
                    on_include=self._set_included,
                )
                (self.week_tiles if child.weekly else self.tiles).addWidget(tile)
                self._tiles[child.key] = tile
            self._tile_keys = keys
        has_week = any(child.weekly for child in children)
        self.week_head.setVisible(has_week)
        self.week_box.setVisible(has_week)
        self.week_note.set_text(
            tf("跑过会自动取消勾选，每周{weekday} {time} 自动勾回来", **data.weekly_reset_parts())
        )
        for child in children:
            tile = self._tiles[child.key]
            tile.set_included(child.included)
            if data.child_done(child):
                record = data.last_run(child.name) or {}
                finished = record.get("finished")
                when = data.clock_text(finished)
                if child.weekly and data.day_text(finished) != "今天":
                    when = data.day_text(finished) or when  # done earlier this week
                tile.set_state("done", when)
            elif not child.included:
                tile.set_state("off", "不在一键日常里")
            else:
                tile.set_state("wait", "本周未完成" if child.weekly else "未完成")

    def _cancel_autorun(self) -> None:
        autorun.cancel()
        self.refresh()

    def _set_included(self, key: str, on: bool) -> None:
        """Same switch as 「加入一键完成日常」 on the item's settings page."""
        batch = data.task_by_name(data.DAILY_BATCH)
        if batch is not None:
            batch.config[key] = bool(on)
        self.refresh()

    def _confirm(self, batch, clone: bool) -> str | None:
        """The pick-and-confirm window; the run mode on 开始, else ``None``.
        Changed checks are kept, like the home tiles' checks."""
        from src.tasks.DailyBatchTask import RUN_MODE_ALL, RUN_MODE_INCOMPLETE

        if batch is None:
            return None
        picked = run_confirm.ask(self.window(), batch, clone)
        if picked is None:
            return None
        mode, ticks = picked
        for key, on in ticks.items():
            if bool(batch.config.get(key, True)) != on:
                batch.config[key] = on
        return RUN_MODE_INCOMPLETE if mode == run_confirm.MODE_LEFT else RUN_MODE_ALL

    def _confirm_and_start(self) -> None:
        batch = data.task_by_name(data.DAILY_BATCH)
        if data.busy():
            # actions.start says what is running.
            actions.start(batch, self.window())
            return
        run_mode = self._confirm(batch, clone=False)
        self.refresh()
        if run_mode is not None:
            actions.start(batch, self.window(), run_mode)
            self.refresh()

    def _start_in_clone(self) -> None:
        batch = data.task_by_name(data.DAILY_BATCH)
        if batch is None or data.busy():
            return
        if not clone_flow.ready_to_go():
            # First-time setup and sign-in fixes still go through their notes.
            clone_flow.ask_and_start(self.window(), batch)
            self.refresh()
            return
        run_mode = self._confirm(batch, clone=True)
        self.refresh()
        if run_mode is not None:
            clone_flow.open_clone(self.window(), batch, run_mode)
            self.refresh()

    def _start_batch(self, name: str, all_items: bool) -> None:
        from src.tasks.DailyBatchTask import RUN_MODE_ALL, RUN_MODE_INCOMPLETE

        actions.start(
            data.task_by_name(name),
            self.window(),
            RUN_MODE_ALL if all_items else RUN_MODE_INCOMPLETE,
        )
        self.refresh()

    # ================================================================ accounts

    def _account_switched(self) -> None:
        # Another account's day: its own done items, ticks and last report.
        self._summary = None
        self._mode = ""
        self.refresh()

    def _ask_account(self) -> None:
        """跑图 stopped because its records looked like another account's."""
        try:
            if not account_check.pending_flag():
                return
            account_check.clear_flag()
            dialog = accounts_ui.MismatchDialog(self.window())
            dialog.exec()
            if dialog.choice == dialog.SAME:
                # The player says this is the account: forget this week's
                # 跑图 records (a copy is kept) and go by the screen.
                from src.tasks.map_trade.progress import ProgressStore

                ProgressStore().forget_collection_week()
            elif dialog.choice == dialog.SWITCH:
                self.account_chip.open_menu()
        finally:
            self._asking_account = False
        self.refresh()

    # ================================================================ running

    def _build_running(self) -> None:
        layout = vbox(self.running, (0, 0, 0, 0), 16)
        progress = Card()
        column = vbox(progress, (18, 16, 18, 14), 10)
        self.segs = SegBar(height=10)
        column.addWidget(self.segs)
        line = hbox(None, (0, 0, 0, 0), 10)
        self.run_count = Text("", "sub")
        self.run_time = Text("", "sub")
        line.addWidget(self.run_count, 1)
        line.addWidget(self.run_time)
        column.addLayout(line)
        layout.addWidget(progress)

        body = hbox(None, (0, 0, 0, 0), 16)
        live = Card()
        live_layout = vbox(live, (14, 14, 14, 14), 12)
        self.live = LiveView()
        live_layout.addWidget(self.live)
        now = hbox(None, (2, 0, 2, 0), 12)
        self.now_icon = IconTile("circle-dashed", 40, 21)
        now.addWidget(self.now_icon)
        now_texts = vbox(None, (0, 0, 0, 0), 2)
        self.now_name = Text("", "h2", elide=True)
        self.now_stage = Text("", "sub", elide=True)
        now_texts.addWidget(self.now_name)
        now_texts.addWidget(self.now_stage)
        now.addLayout(now_texts, 1)
        self.now_clock = Text("", "big")
        self.now_clock.setProperty("tone", "run")
        now.addWidget(self.now_clock)
        live_layout.addLayout(now)
        live_layout.addWidget(Separator())
        self.log_lines = [Text("", "muted", elide=True) for _ in range(3)]
        for label in self.log_lines:
            live_layout.addWidget(label)
        body.addWidget(live, 3)
        self.run_timeline = Timeline()
        self.run_timeline.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        right = vbox(None, (0, 0, 0, 0), 0)
        right.addWidget(self.run_timeline)
        right.addStretch(1)
        body.addLayout(right, 2)
        layout.addLayout(body)

    def _refresh_running(self, report: dict | None, task) -> None:
        now = time.time()
        if report is not None:
            rows = report.get("rows") or []
            current_key = report.get("current")
            current_row = next((row for row in rows if row.get("key") == current_key), None)
            child_task = self._child_task(report.get("label"), current_key)
            name = current_row.get("name") if current_row else ""
            self.set_eyebrow(report.get("label") or "")
            self.segs.set_states([row.get("state") or "wait" for row in rows])
            self.segs.show()
            done = sum(1 for row in rows if row.get("state") == run_report.DONE)
            skipped = sum(1 for row in rows if row.get("state") == run_report.SKIP)
            failed = sum(1 for row in rows if row.get("state") == run_report.FAIL)
            parts = [tf("{done} / {total} 完成", done=done, total=len(rows))]
            if skipped:
                parts.append(tf("{n} 项跳过", n=skipped))
            if failed:
                parts.append(tf("{n} 项失败", n=failed))
            self.run_count.set_text(" · ".join(parts))
            left = self._remaining_estimate(rows, now)
            elapsed = tf("已运行 {time}", time=fmt_clock(now - (report.get("started") or now)))
            self.run_time.set_text(
                tf("{elapsed} · 预计还要 {time}", elapsed=elapsed, time=fmt_minutes(left))
                if left
                else elapsed
            )
            self.run_timeline.set_rows(rows, now)
            started = current_row.get("started") if current_row else None
            _short, icon, kind = data.CHILD_META.get(
                current_key or "", ("", "loader-circle", "plain")
            )
        else:
            child_task = task
            name = data.tr(str(getattr(task, "name", "")))
            self.set_eyebrow("单独运行")
            self.segs.hide()
            started = getattr(task, "start_time", 0) or None
            self.run_count.set_text(name)
            self.run_time.set_text(
                tf("已运行 {time}", time=fmt_clock(now - started)) if started else ""
            )
            self.run_timeline.set_rows(
                [{"key": name, "name": name, "state": "run", "started": started}], now
            )
            icon, kind = data.task_look(task)
        runner = data.current_task()
        if getattr(task, "remote", False):
            # Stage and log lines come from the tool in the clone.
            runner = child_task = task
        paused = bool(getattr(runner, "paused", False))
        stopping = self.stopping()
        self._show_stopping(stopping)
        if stopping:
            self.set_title(tf("正在停止：{name}", name=name) if name else "正在停止…")
            self.set_sub("正在收尾，请稍等")
        else:
            self.set_title(
                tf("已暂停：{name}" if paused else "正在跑：{name}", name=name)
                if name
                else "正在准备"
            )
            # Leo 2026-10-09: say the keys, and that 设置 changes them.
            self.set_sub(hotkeys.hint())
        self.pause_button.set_label("继续" if paused else "暂停")
        self.pause_button.set_icon_name("play" if paused else "pause")
        self.now_icon.set_icon(icon, kind)
        self.now_name.set_text(name or "正在准备")
        self.now_clock.set_text(fmt_clock(now - started) if started else "")
        self.now_stage.set_text(self._stage_text(child_task))
        self._update_logs(child_task)

    @staticmethod
    def _child_task(label: str | None, key: str | None):
        if not key:
            return None
        for child in data.batch_children(data.task_by_name(label or "")):
            if child.key == key:
                return child.task
        return None

    @staticmethod
    def _stage_text(task) -> str:
        if task is None:
            return ""
        info = task_info_snapshot(task)
        for key in ("当前阶段", "状态"):
            text = str(info.get(key) or "").strip()
            if text and text != "-":
                name = str(getattr(task, "name", ""))
                return text[len(name) :].lstrip("：: ") if name and text.startswith(name) else text
        return ""

    def _update_logs(self, task) -> None:
        if task is not None:
            text = str(task_info_snapshot(task).get("Log") or "").strip()
            if text and text != self._last_log:
                self._last_log = text
                self._logs.appendleft((data.clock_text(time.time()) + time.strftime(":%S"), text))
        for label, entry in zip(self.log_lines, list(self._logs) + [None] * 3):
            label.set_text(f"{entry[0]}  {entry[1]}" if entry else "")

    @staticmethod
    def _remaining_estimate(rows: list[dict], now: float) -> float | None:
        total = 0.0
        known = False
        for row in rows:
            state = row.get("state")
            if state not in (run_report.WAIT, run_report.RUN):
                continue
            record = data.last_run(str(row.get("name") or "")) or {}
            duration = record.get("duration")
            if not isinstance(duration, (int, float)) or duration <= 0:
                continue
            known = True
            if state == run_report.RUN and row.get("started"):
                total += max(0.0, duration - (now - row["started"]))
            else:
                total += duration
        return total if known else None

    def _pause(self) -> None:
        remote = None if data.busy() else clone_flow.remote_task()
        if remote is not None:
            clone_flow.remote_control("resume" if remote.paused else "pause")
        else:
            actions.toggle_pause(data.current_task())
        self.refresh()

    def _stop(self) -> None:
        """The 停止 button and the hotkey.  The button turns into a greyed
        「正在停止…」 before the stop is sent; more presses do nothing until
        the run has ended (or the press got nowhere, see ``stopping``)."""
        if self.stopping():
            return
        if self._mode == "run":
            self._stop_pressed_at = time.monotonic()
            self._show_stopping(True)
            self.stop_button.repaint()  # before the stop, which may take a moment
        if not data.busy() and clone_flow.remote_task() is not None:
            clone_flow.remote_control("stop")
        else:
            actions.stop(data.current_task())
        self.refresh()

    def stopping(self) -> bool:
        """停止 was pressed and the run has not ended yet.

        A task here that is still running but no longer enabled is finishing
        its step.  A press with nothing to see (a run in the 桌面分身, or
        waiting for the login) counts for STOP_GRACE_SECONDS: if the run still
        goes on after that, the button can be pressed again."""
        if self._mode != "run":
            return False
        task = data.current_task()
        if task is not None and not getattr(task, "remote", False):
            if not getattr(task, "enabled", True):
                return True
        pressed = self._stop_pressed_at
        return pressed is not None and time.monotonic() - pressed < STOP_GRACE_SECONDS

    def _show_stopping(self, on: bool) -> None:
        self.stop_button.set_label("正在停止…" if on else "停止")
        self.stop_button.set_icon_name("loader-circle" if on else "square")
        self.stop_button.setEnabled(not on)
        self.pause_button.setEnabled(not on)

    # ================================================================ summary

    def _build_summary(self) -> None:
        layout = vbox(self.summary, (0, 0, 0, 0), 16)
        # Leo 2026-10-05: after 周常 the 日常 summary (its 抽到的 / 邮件领到的
        # pictures) was out of reach; each saved run gets a switch here.
        self.sum_switch_row = hbox(None, (0, 0, 0, 0), 0)
        self.sum_switch: Segmented | None = None
        self._sum_switch_labels: tuple[str, ...] = ()
        layout.addLayout(self.sum_switch_row)
        self.sum_boxes, grid = grid_container(120, 12, 4, 78)
        self.sum_time = self._sum_box(grid, "用时", "")
        self.sum_done = self._sum_box(grid, "完成", "ok")
        self.sum_skip = self._sum_box(grid, "跳过", "")
        self.sum_fail = self._sum_box(grid, "失败", "bad")
        layout.addWidget(self.sum_boxes)
        # A run the 开跑前检查 stopped shows only its reminder (Leo 10-09
        # 「5提醒就好了」): nothing ran, so no numbers and no list.
        self.sum_body = QWidget()
        body = hbox(self.sum_body, (0, 0, 0, 0), 16)
        self.sum_timeline = Timeline()
        left = vbox(None, (0, 0, 0, 0), 0)
        left.addWidget(self.sum_timeline)
        left.addStretch(1)
        body.addLayout(left, 3)
        self.sum_side = QWidget()
        side = vbox(self.sum_side, (0, 0, 0, 0), 16)
        # Leo 2026-10-09: a run that did not fully finish offers its 问题摘要 here.
        self.problem_card = ProblemCard()
        self.problem_card.hide()
        side.addWidget(self.problem_card)
        self.gacha_card, self.gacha_grid = self._picture_card("抽到的", "白嫖抽抽乐 · 点图看大图")
        self.mail_card, self.mail_grid = self._picture_card("邮件领到的", "领取邮件 · 点图看大图")
        side.addWidget(self.gacha_card)
        side.addWidget(self.mail_card)
        side.addStretch(1)
        body.addWidget(self.sum_side, 2)
        layout.addWidget(self.sum_body)
        self._shown_summary_key = None
        self._summary_pictures = False
        self._problem_found = False
        self._problem_looked = False

    @staticmethod
    def _sum_box(grid, label: str, tone: str) -> Text:
        card = Card()
        column = vbox(card, (16, 12, 16, 12), 2)
        column.addWidget(Text(label, "muted"))
        value = Text("", "big")
        value.animate_changes()
        if tone:
            value.setProperty("tone", tone)
        column.addWidget(value)
        grid.addWidget(card)
        return value

    def _picture_card(self, title: str, sub: str):
        card = Card()
        column = vbox(card, (16, 14, 16, 16), 10)
        head = hbox(None, (0, 0, 0, 0), 8)
        head.addWidget(Text(title, "h2"))
        head.addWidget(Text(sub, "muted"), 1)
        column.addLayout(head)
        box, grid = grid_container(150, 10, 2, 96)
        column.addWidget(box)
        return card, grid

    def _refresh_summary(self) -> None:
        report = self._summary or {}
        ended = report.get("ended")
        finished = report.get("finished") or 0
        when = f"{data.day_text(finished)} {data.clock_text(finished)}"
        self.set_eyebrow(tf("{label} · {when} 结束", label=t(report.get("label") or ""), when=when))
        self.set_title(SUMMARY_TITLE.get(ended, "跑完了"))
        self.set_sub("")
        stopped = run_report.stopped_row(report)
        self.resume_summary_button.setVisible(stopped is not None)
        self.home_button.set_kind("secondary" if stopped else "primary")
        if stopped is not None:
            name = stopped_name(stopped)
            self.resume_summary_button.set_label(tf("从「{name}」继续", name=name))
            self.set_sub(tf("按继续会从「{name}」接着跑，做完的不会再跑", name=name))
        setup = ended == run_report.ENDED_SETUP
        # Also a finished run's word, e.g. why the PC was not shut down.
        if setup or (stopped is None and report.get("notice")):
            self.set_sub(report.get("notice") or "")
        self.sum_boxes.setVisible(not setup)
        self.sum_body.setVisible(not setup)
        rows = report.get("rows") or []
        self.sum_time.set_text(fmt_clock(finished - (report.get("started") or finished)))
        self.sum_done.set_text(str(sum(1 for row in rows if row.get("state") == run_report.DONE)))
        self.sum_skip.set_text(str(sum(1 for row in rows if row.get("state") == run_report.SKIP)))
        self.sum_fail.set_text(str(sum(1 for row in rows if row.get("state") == run_report.FAIL)))
        self.sum_timeline.set_rows(rows, finished)
        self._refresh_summary_switch(report.get("label"))
        key = (report.get("label"), finished)
        if key != self._shown_summary_key:
            self._shown_summary_key = key
            images = report.get("images") or {}
            has_gacha = self._fill_pictures(self.gacha_grid, images.get("gacha") or [])
            has_mail = self._fill_pictures(self.mail_grid, images.get("mail") or [])
            self.gacha_card.setVisible(has_gacha)
            self.mail_card.setVisible(has_mail)
            self._summary_pictures = has_gacha or has_mail
            self._problem_found = False
            self._problem_looked = False
        # A stop the player pressed is not a problem to report: the run stays
        # in the 回报问题 page, but the results page shows no card (Leo 10-09).
        reportable = ended not in (
            run_report.ENDED_DONE, run_report.ENDED_STOPPED, run_report.ENDED_SETUP
        )
        if reportable and not self._problem_found and (
            not self._problem_looked or time.time() - finished < 60
        ):
            # The record is written just after the batch's report; look again
            # until it is there (a few seconds at most).
            self._problem_looked = True
            record = problem_report.find(report.get("label"), finished)
            self._problem_found = record is not None
            self.problem_card.set_record(record)
        problem = reportable and self._problem_found
        self.problem_card.setVisible(problem)
        self.sum_side.setVisible(self._summary_pictures or problem)

    def _refresh_summary_switch(self, current: str | None) -> None:
        labels = tuple(str(r.get("label") or "") for r in run_report.saved() if r.get("label"))
        if labels != self._sum_switch_labels:
            self._sum_switch_labels = labels
            if self.sum_switch is not None:
                self.sum_switch.setParent(None)
                self.sum_switch.deleteLater()
                self.sum_switch = None
            if len(labels) > 1:
                self.sum_switch = Segmented(
                    labels,
                    current,
                    labels={label: summary_switch_text(label) for label in labels},
                )
                self.sum_switch.changed.connect(self._show_saved_report)
                self.sum_switch_row.addWidget(self.sum_switch)
                self.sum_switch_row.addStretch(1)
        if self.sum_switch is not None:
            self.sum_switch.set_value(current)

    def _show_saved_report(self, label: str) -> None:
        report = run_report.load(label)
        if report:
            self._summary = report
            self.refresh()

    def _fill_pictures(self, grid, paths: list[str]) -> bool:
        while grid.count():
            item = grid.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        shown = 0
        for path in paths:
            picture = Picture(path, radius=theme.radius(), background="shot")
            if not picture.has_picture():
                continue
            picture.setCursor(Qt.PointingHandCursor)
            picture.clicked.connect(lambda p=path: PictureDialog(p, self).exec())
            grid.addWidget(picture)
            shown += 1
        return shown > 0

    def _resume_summary(self) -> None:
        label = (self._summary or {}).get("label")
        self._summary = None
        if label:
            self._start_batch(label, all_items=False)
        else:
            self.refresh()

    def _close_summary(self) -> None:
        self._summary = None
        self.refresh()

    def leave_summary(self) -> None:
        """Back to the home page proper; a run in progress stays on screen."""
        if self._summary is not None:
            self._close_summary()

    # ================================================================ state

    def refresh(self) -> None:
        report = run_report.active()
        task = data.current_task()
        if report is None and task is None:
            # Leo (2026-10-03 13:17): a run on the 桌面分身 is watched and
            # operated here, as if it ran in this tool.
            remote = clone_flow.remote_task()
            if remote is not None:
                report, task = remote.status.get("report"), remote
        self._remote = getattr(task, "remote", False)
        self.live.set_remote(clone_desktop.LIVE_FILE if self._remote else None)
        if report is not None:
            self._watching_label = report.get("label")
            self._watching_started = report.get("started")
        elif self._watching_label is not None:
            # The batch just ended: open its 结算 once, never an older run's.
            finished = run_report.load_run(
                self._watching_label, getattr(self, "_watching_started", None)
            )
            # Not saved (closed or crashed mid-run): the home page, not the
            # summary from before.
            self._summary = finished
            self._watching_label = None
            self._watching_started = None
        if report is not None or task is not None:
            mode = "run"
        elif self._summary is not None:
            mode = "summary"
        else:
            mode = "idle"
        if mode != self._mode:
            self._mode = mode
            self._stop_pressed_at = None
            self.idle.setVisible(mode == "idle")
            self.running.setVisible(mode == "run")
            self.summary.setVisible(mode == "summary")
            self.pause_button.setVisible(mode == "run")
            self.stop_button.setVisible(mode == "run")
            self.logs_button.setVisible(mode == "summary")
            self.home_button.setVisible(mode == "summary")
            self.resume_summary_button.setVisible(False)
            if mode == "run":
                self._logs.clear()
                self._last_log = ""
        self.account_chip.refresh()
        self.account_chip.set_switchable(mode != "run" and not clone_flow.busy_in_clone())
        if mode == "idle":
            self._refresh_idle()
        elif mode == "run":
            self._refresh_running(report, task)
        else:
            self._refresh_summary()
        if mode != "run" and not self._asking_account and account_check.pending_flag():
            self._asking_account = True
            QTimer.singleShot(0, guarded("ask account", self._ask_account))
