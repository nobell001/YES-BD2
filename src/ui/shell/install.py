"""Puts the new sidebar and pages into ok's main window.

The old navigation is only hidden.  Its pages stay in the stacked widget
but no longer open from the new window: Leo (2026-10-03) wants none of the
old pages kept, and what he uses moved to the new 设置 and 首页.  Installed
from ``Globals.on_show_main_window``, after the other window hooks and
before the window is first shown.
"""

from __future__ import annotations

from ok import Logger
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from src.ui.shell import actions, data, theme
from src.ui.shell.motion import PageCover

logger = Logger.get_logger(__name__)

MIN_WIDTH = 940
MIN_HEIGHT = 600
# How often the keep-awake request follows the runs (well under any sleep timeout).
KEEP_AWAKE_CHECK_MS = 5000


class Shell(QObject):
    """Owns the sidebar and the new pages; keeps the sidebar on the shown page."""

    def __init__(self, window):
        super().__init__(window)
        from src.ui.shell.fiend_page import FiendPage
        from src.ui.shell.home import HomePage
        from src.ui.shell.map_page import MapPage
        from src.ui.shell.report_page import ReportPage
        from src.ui.shell.settings import SettingsPage
        from src.ui.shell.sidebar import Sidebar
        from src.ui.shell.task_page import TaskPage
        from src.ui.shell.trade import TradePage

        self.window = window
        self.pages: dict[str, QWidget] = {
            "home": HomePage(self.open_task, self.navigate),
            "report": ReportPage(),
            "daily": TaskPage(
                "shellDaily", "任务设定", batch_name=data.DAILY_BATCH, navigate=self.navigate
            ),
            "trade": TradePage(),
            "map": MapPage(),
            "fiend": FiendPage(),
            "settings": SettingsPage(window),
        }
        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self._sidebar_clicked)
        from src.ui.shell.about_page import AboutPage

        self.pages["about"] = AboutPage(window, self.sidebar)
        from src.ui.shell.guide_page import GuidePage

        self.pages["guide"] = GuidePage(self.navigate, self.sidebar)
        from src.ui.shell.problem_page import ProblemPage

        self.pages["problem"] = ProblemPage()

        # Everything above only builds widgets; from here on the window changes.
        stack = window.stackedWidget
        for page in self.pages.values():
            page.setProperty("isStackedTransparent", True)
            stack.addWidget(page)
        window.hBoxLayout.insertWidget(0, self.sidebar)
        _hide_old_navigation(window)
        _tidy_title_bar(window)
        _use_flat_background(window)
        if window.minimumWidth() < MIN_WIDTH or window.minimumHeight() < MIN_HEIGHT:
            window.setMinimumSize(
                max(window.minimumWidth(), MIN_WIDTH), max(window.minimumHeight(), MIN_HEIGHT)
            )

        self.cover = PageCover(stack)
        _drop_old_touch_guards(window)
        stack.currentChanged.connect(self._on_page_changed)
        self._take_over_start_switch()
        actions.on_started(self._after_start)
        window.switchTo(self.pages["home"])
        self._on_page_changed(stack.currentIndex())
        from src.ui.shell import clone_flow

        clone_flow.run_pending_job_soon()
        from src.ui.shell import sound_watch

        # 设置「跑的时候游戏静音」 (Leo 2026-10-09).
        self._sound_timer = sound_watch.start(self)
        self._start_hotkeys()
        from src.ui.shell import autorun

        # The player's 「打开工具就自动跑」 on 首页 (Leo 2026-10-09).
        QTimer.singleShot(1500, autorun.schedule)
        self._start_keep_awake()

    # ------------------------------------------------------------ keep awake

    def _start_keep_awake(self) -> None:
        """The PC does not sleep while a run goes (Leo 2026-10-09)."""
        from src.ui.shell.safe import guarded

        self._awake_timer = QTimer(self)
        self._awake_timer.timeout.connect(guarded("keep awake", self._keep_awake))
        self._awake_timer.start(KEEP_AWAKE_CHECK_MS)

    def _keep_awake(self) -> None:
        from src.ui.shell import clone_flow
        from src.utils import keep_awake

        task = data.current_task()
        here = (task is not None and task in data.onetime_tasks()) or data.waiting_for_login()
        paused = bool(getattr(task, "paused", False)) if task is not None else False
        level = keep_awake.level_for(here, paused, clone_flow.busy_in_clone())
        keep_awake.apply(level)

    # ------------------------------------------------------------ hotkeys

    hotkey_pressed = Signal(str)

    def _start_hotkeys(self) -> None:
        """暂停/停止 keys anywhere, even with the game in front (Leo 2026-10-09)."""
        from src.ui.shell import hotkeys

        self.hotkey_pressed.connect(self._on_hotkey)  # queued: pressed on the hotkey thread
        hotkeys.start(self.hotkey_pressed.emit)

    def _on_hotkey(self, action: str) -> None:
        from src.ui.shell import hotkeys

        home = self.pages["home"]
        if action == hotkeys.PAUSE:
            home._pause()
        elif action == hotkeys.STOP:
            home._stop()

    # ------------------------------------------------------------ navigation

    def navigate(self, key: str) -> None:
        page = self.pages.get(key)
        if page is not None:
            self.window.switchTo(page)

    def _sidebar_clicked(self, key: str) -> None:
        if key == "home":
            # Leo 2026-10-09: 首页 in the sidebar leaves a finished run's 结算.
            self.pages["home"].leave_summary()
        self.navigate(key)

    def _after_start(self) -> None:
        """A start goes to 首页, except from the 魔兽追踪者 page (Leo 2026-10-06:
        recording and replaying are watched there, with the save's turns)."""
        if self.window.stackedWidget.currentWidget() is self.pages.get("fiend"):
            return
        self.navigate("home")

    def open_task(self, page_key: str, task_key: str) -> None:
        page = self.pages.get(page_key)
        if page is None:
            return
        self.navigate(page_key)
        select = getattr(page, "select", None)
        if callable(select):
            select(task_key)

    def _on_page_changed(self, _index: int) -> None:
        current = self.window.stackedWidget.currentWidget()
        for key, page in self.pages.items():
            if page is current:
                self.sidebar.select(key)
                self.cover.play(page)
                return
        if current is getattr(self.window, "about_tab", None):
            # ok opens its old About page after an update or a copyright
            # notice; the new one has its update controls and notes.
            QTimer.singleShot(0, lambda: self.window.switchTo(self.pages["about"]))
        else:
            # An old page ok itself switched to.
            self.sidebar.select("settings")

    # ------------------------------------------------------------ start / pause

    def _take_over_start_switch(self) -> None:
        """ok jumps to its old task list on start; jump to 首页 instead."""
        from ok.core.events import communicate

        communicate.executor_paused.disconnect(self.window.executor_paused)
        communicate.executor_paused.connect(self._executor_paused)

    def _executor_paused(self, paused: bool) -> None:
        window = self.window
        if not paused and window.stackedWidget.currentWidget() is getattr(
            window, "start_tab", None
        ):
            self.navigate("home")
        window.show_notification(
            window.tr("Start Success.") if not paused else window.tr("Pause Success."), tray=False
        )


def _noop(*_args, **_kwargs) -> None:
    return None


def _drop_old_touch_guards(window) -> None:
    """Take the old pages' touch-scroll guards off the application.

    Every old ok page installs one app-wide Python event filter, so every
    paint, hover and timer event in the whole app ran through a dozen Python
    calls (about 40% of a repaint here).  The old pages no longer open from
    the new window, so their guards only cost time.
    """
    from PySide6.QtWidgets import QAbstractScrollArea, QApplication

    app = QApplication.instance()
    dropped = 0
    for area in window.findChildren(QAbstractScrollArea):
        guard = getattr(area, "_touch_scroll_click_guard", None)
        if guard is not None and app is not None:
            app.removeEventFilter(guard)
            dropped += 1
    logger.info(f"dropped {dropped} old touch-scroll guards")


def _hide_old_navigation(window) -> None:
    """Hide ok's navigation for good, including its pop-over menu mode."""
    nav = window.navigationInterface
    panel = nav.panel
    for target in (nav, panel):
        target.expand = _noop
        target.toggle = _noop
    # The panel watches window resizes to collapse/expand itself.
    window.removeEventFilter(panel)
    if panel.parent() is not nav:
        # A narrow window had already popped the panel over the pages.
        panel.hide()
        panel.setParent(nav)
        panel.move(0, 0)
    nav.hide()


def _tidy_title_bar(window) -> None:
    """The sidebar shows the name; keep the title bar for dragging and buttons."""
    bar = getattr(window, "titleBar", None)
    if bar is None:
        return
    for name in ("iconLabel", "titleLabel"):
        label = getattr(bar, name, None)
        if label is not None:
            label.hide()
    bar.raise_()


def _use_flat_background(window) -> None:
    """Plain ground colour instead of Windows 11 Mica, in both themes."""
    try:
        window.setMicaEffectEnabled(False)
    except Exception as exc:
        logger.warning(f"shell: mica off failed: {exc}")
    window.setCustomBackgroundColor(QColor(theme.LIGHT["bg"]), QColor(theme.DARK["bg"]))


def install_shell(window) -> Shell | None:
    if getattr(window, "_bd2_shell", None) is not None:
        return window._bd2_shell
    try:
        shell = Shell(window)
    except Exception as exc:
        logger.error("new main window pages failed, keeping the old ones", exc)
        return None
    window._bd2_shell = shell
    logger.info("new main window pages installed")
    return shell
