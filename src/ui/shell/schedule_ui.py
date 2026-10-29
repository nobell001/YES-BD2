"""定时启动 on 首页: its window and the watch while the tool is open (Leo 2026-10-22).

The card on 首页 (home.ScheduleCard) shows the next start and has the one
switch that turns it all off; a click opens :class:`ScheduleDialog`.  Each
time slot has its own time and weekdays (Leo: not only one fixed time a
day), plus 「游戏每天重置后」.  保存 writes the settings and the Windows task
(src/utils/scheduled_start.py); the switch at the top off deletes the task.
"""

from __future__ import annotations

import copy
from datetime import datetime

from ok import Logger
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QGraphicsEffect,
    QGridLayout,
    QSizePolicy,
    QWidget,
)
from qfluentwidgets import ComboBox, FlowLayout, ScrollArea

from src.ui.shell import icons, motion, theme
from src.ui.shell.floating import Floating
from src.ui.shell.run_confirm import HeroIcon
from src.ui.shell.safe import guarded
from src.ui.shell.widgets import (
    Button,
    CheckBox,
    Text,
    hbox,
    mix,
    t,
    tf,
    vbox,
)
from src.utils import accounts, scheduled_start
from src.utils.scheduled_start import Settings, Slot

logger = Logger.get_logger(__name__)

WATCH_MS = 20_000
WEEKDAYS = "一二三四五六日"

_settings: Settings | None = None
# Why the last change did not fully take, for the card (empty when fine).
problem = ""


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = scheduled_start.load()
    return _settings


def store(new: Settings) -> str:
    """Save ``new`` and make the Windows task match; the reason when Windows refused."""
    global _settings, problem
    try:
        scheduled_start.apply(new)
    except scheduled_start.TaskError as exc:
        logger.error(f"scheduled start: Windows task not changed ({exc})")
        return tf("Windows 没有接受这个设定：{why}", why=str(exc) or t("原因不明"))
    scheduled_start.save(new)
    _settings = new
    problem = ""
    if new.active_slots() and new.wake and scheduled_start.ensure_wake_timers() is False:
        problem = "电脑睡着时叫不醒：Windows 不让打开唤醒定时器"
        logger.warning("scheduled start: wake timers could not be turned on")
    logger.info(f"scheduled start: saved {new.to_json()}")
    return ""


def set_enabled(on: bool) -> str:
    new = copy.deepcopy(settings())
    new.enabled = on
    return store(new)


def next_text(now: datetime | None = None) -> tuple[str, str]:
    """(time, 「下次 · 今天」) of the next start on the player's clock, or ('', '')."""
    now = now or scheduled_start.local_now()
    moment = scheduled_start.next_run(settings(), now)
    if moment is None:
        return "", ""
    days = (moment.date() - now.date()).days
    if days == 0:
        word = t("下次 · 今天")
    elif days == 1:
        word = t("下次 · 明天")
    else:
        word = tf("下次 · 周{weekday}", weekday=t(WEEKDAYS[moment.weekday()]))
    names = [_account_name(slot.account) for slot in scheduled_start.slots_at(settings(), moment)]
    who = "、".join(dict.fromkeys(name for name in names if name))
    if who:
        word = f"{word} · {who}"
    return moment.strftime("%H:%M"), word


def account_label(account_id: str) -> str:
    """A 帳號's name for a report, 「当前账号」 when unknown."""
    return _account_name(account_id) or t("当前账号")


def _account_name(account_id: str) -> str:
    """The name of the 帳號 a slot runs ('' for the current one or one gone)."""
    if not account_id:
        return ""
    from src.ui.shell.accounts_ui import display_name

    try:
        known = {account.id: account for account in accounts.accounts()}
    except Exception:
        return ""
    return display_name(known[account_id]) if account_id in known else ""


# ---------------------------------------------------------------- the run

LOCKED_NOTE = (
    "电脑停在锁屏画面，工具没办法操作游戏，这次没有跑。"
    "要让定时启动能跑，Windows 睡醒后不能要求输入密码。"
)
NOT_STARTED_NOTE = "一键日常没能开始（可能有别的任务正在跑），这次没有跑。"
NO_LOGIN_NOTE = "等了 {m} 分钟，游戏还是没打开或没登录进去，这次没有跑。"
# Opening the game and logging in (a patch download included) is done well
# within this; AutoLoginTask gives a stuck login up after 3 x 5 minutes.
WATCHDOG_MINUTES = 25
WATCHDOG_RECHECK_MINUTES = 5
WATCHDOG_RECHECKS = 3
_watch_started: float | None = None


def report_failure(note: str) -> None:
    """A scheduled start that never became a run still ends in a report.

    Leo 2026-10-22: 「設定好定時就不管他 … 有問題也要說」: the 跑完通知
    (run_report.finish) and the 结算 page read it like any other run.
    """
    from src.tasks import run_report
    from src.ui.shell import data

    if run_report.active() is not None:
        return  # a run is going; it reports for itself
    batch = data.task_by_name(data.DAILY_BATCH)
    label = getattr(batch, "batch_label", None) or "一键完成日常"
    logger.warning(f"scheduled start: no run ({note})")
    run_report.begin(label, "定时启动", [])
    run_report.mark("scheduled", True)
    run_report.set_notice(note)
    run_report.finish(run_report.ENDED_ERROR)


def before_start(tasks: list[str] | None = None, item_settings: dict | None = None) -> bool:
    """Checks before a scheduled 一键日常; False when it cannot run (reported).

    ``tasks``: the slot's own items (None = the 帳號's ticks);
    ``item_settings``: their settings for this run only."""
    if scheduled_start.screen_locked():
        report_failure(LOCKED_NOTE)
        return False
    scheduled_start.mark_run_pending(tasks=tasks, settings=item_settings)
    return True


def after_start(started: bool) -> None:
    """The run was asked for; make sure it really begins (or say why not)."""
    global _watch_started
    import time

    if not started:
        scheduled_start.mark_run_pending(False)
        report_failure(NOT_STARTED_NOTE)
        return
    _watch_started = time.time()
    QTimer.singleShot(WATCHDOG_MINUTES * 60_000, guarded("scheduled start check", _check_begun))


def begun_since(since: float) -> bool:
    from src.tasks import run_report
    from src.ui.shell import data

    batch = data.task_by_name(data.DAILY_BATCH)
    label = getattr(batch, "batch_label", None) or "一键完成日常"
    for report in (run_report.active(), run_report.load(label)):
        if report and report.get("label") == label and (report.get("started") or 0) >= since:
            return True
    return False


def _check_begun(rechecks: int = 0) -> None:
    from src.ui.shell import data

    since = _watch_started
    if since is None or begun_since(since):
        return
    if data.busy() and rechecks < WATCHDOG_RECHECKS:
        QTimer.singleShot(
            WATCHDOG_RECHECK_MINUTES * 60_000,
            guarded("scheduled start check", lambda: _check_begun(rechecks + 1)),
        )
        return
    scheduled_start.mark_run_pending(False)
    waited = WATCHDOG_MINUTES + rechecks * WATCHDOG_RECHECK_MINUTES
    report_failure(NO_LOGIN_NOTE.format(m=waited))


# ---------------------------------------------------------------- watch


class _Watch(QObject):
    """While the tool is open, start the run when a slot comes.

    The Windows task's own copy of the tool exits at once then (main.py), so
    this is what starts it; a slot noticed more than a few minutes late (the
    PC slept through it) does not start.
    """

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self._last = scheduled_start.local_now()
        self._timer = QTimer(self)
        self._timer.timeout.connect(guarded("scheduled start watch", self._tick))
        self._timer.start(WATCH_MS)

    def _tick(self) -> None:
        from src.ui.shell import autorun

        now = scheduled_start.local_now()
        last, self._last = self._last, now
        due = scheduled_start.due_between(settings(), last, now)
        if due is None:
            return
        logger.info(f"scheduled start: slot {due:%H:%M} came while the tool is open")
        autorun.schedule_jobs(scheduled_start.jobs_at(settings(), due))


def start_watch(parent: QObject) -> _Watch:
    current = settings()
    if current.migrated:
        # An older save (「游戏每天重置后」, minutes off the quarter): the
        # Windows task still holds the old times until it is written again.
        why = store(copy.deepcopy(current))
        if why:
            logger.warning(f"scheduled start: old settings not rewritten ({why})")
    return _Watch(parent)


# ---------------------------------------------------------------- window


class DayChip(QAbstractButton):
    """A weekday to tick: a circle, or one even pill when the names are
    longer (Mon, 月曜 …); all seven share one width so the row stays straight."""

    SIZE = 30

    def __init__(self, day: int, on: bool, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(on)
        self.setText(t(WEEKDAYS[day]))
        self.setFixedSize(self.chip_width(self.font()), self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        # The colour slides between off and on (Leo 2026-10-22 「加一點小動效」).
        self._fill = motion.Tween(self, self.update, 160, 1.0 if on else 0.0)
        self.toggled.connect(lambda checked: self._fill.go(1.0 if checked else 0.0))

    @classmethod
    def _label_font(cls, base: QFont) -> QFont:
        font = theme.body_font(base)
        font.setPixelSize(13)
        return font

    @classmethod
    def chip_width(cls, base: QFont) -> int:
        metrics = QFontMetrics(cls._label_font(base))
        widest = max(metrics.horizontalAdvance(t(day)) for day in WEEKDAYS)
        return max(cls.SIZE, widest + 16)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        fill = float(self._fill.value)
        painter.setPen(Qt.NoPen)
        colour = mix(theme.color("pill"), theme.color("primary"), fill)
        if not self.isEnabled():
            colour.setAlphaF(0.45)
        painter.setBrush(colour)
        # A little pop while it turns on: from 90 % up to full size.
        grow = 1.0 - 0.1 * (1.0 - fill) if self.isChecked() else 1.0
        box = QRectF(0, 0, self.width(), self.SIZE)
        inset_x, inset_y = box.width() * (1 - grow) / 2, box.height() * (1 - grow) / 2
        box.adjust(inset_x, inset_y, -inset_x, -inset_y)
        radius = box.height() / 2
        painter.drawRoundedRect(box, radius, radius)
        painter.setFont(self._label_font(self.font()))
        painter.setPen(mix(theme.color("ink2"), theme.color("on_primary"), fill))
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())


class _Slide(QGraphicsEffect):
    """Draws its widget faded and a few px low; ``progress`` 1 is as is."""

    RISE_PX = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0.0

    def draw(self, painter):
        painter.save()
        painter.setOpacity(self.progress)
        painter.translate(0, self.RISE_PX * (1 - self.progress))
        self.drawSource(painter)
        painter.restore()


def slide(widget: QWidget, out: bool = False, done=None, duration: int = 220) -> None:
    """Fade ``widget`` in from a little below (or out, then call ``done``)."""
    effect = _Slide(widget)
    effect.progress = 1.0 if out else 0.0
    widget.setGraphicsEffect(effect)
    anim = QVariantAnimation(widget)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.OutCubic if not out else QEasingCurve.InCubic)
    anim.setStartValue(effect.progress)
    anim.setEndValue(0.0 if out else 1.0)

    def step(value) -> None:
        effect.progress = float(value)
        effect.update()

    def finished() -> None:
        if not out:
            widget.setGraphicsEffect(None)  # nothing left to draw differently
        if done is not None:
            done()

    anim.valueChanged.connect(step)
    anim.finished.connect(finished)
    anim.start(QVariantAnimation.DeleteWhenStopped)


DELETE_SIZE = 34
OPTION_GAP = 24


def _delete_button(on_click) -> Button:
    button = Button("", "ghost", "trash-2", on_click=on_click)
    button.setFixedSize(DELETE_SIZE, DELETE_SIZE)
    button.setToolTip(t("删除这个时段"))
    return button


TIME_BOX_WIDTH = 76
HOURS = range(24)
MINUTES = range(0, 60, scheduled_start.MINUTE_STEP)


class _RowsView(ScrollArea):
    """Asks for all its rows' height, makes do with one: when the tool window
    is too short (5 slots at 175 % on a 1080p screen) the rows scroll
    instead of being squashed."""

    def setWidget(self, widget: QWidget) -> None:
        super().setWidget(widget)
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        # The rows changed: this view's own wish changed with them, and the
        # window must hear of it (a scroll area does not pass it on).
        if watched is self.widget() and event.type() == QEvent.LayoutRequest:
            self.updateGeometry()
        return super().eventFilter(watched, event)

    def sizeHint(self) -> QSize:
        content = self.widget()
        hint = content.sizeHint() if content is not None else QSize(0, 0)
        return QSize(hint.width(), hint.height())

    def minimumSizeHint(self) -> QSize:
        content = self.widget()
        layout = content.layout() if content is not None else None
        first = layout.itemAt(0) if layout is not None and layout.count() else None
        return QSize(0, first.sizeHint().height() if first is not None else 0)


def _number_box(values: range, value: int, on_change) -> ComboBox:
    box = ComboBox()
    box.addItems([f"{n:02d}" for n in values])
    box.setCurrentIndex(min(range(len(values)), key=lambda i: abs(values[i] - value)))
    box.setMaxVisibleItems(8)
    box.setFixedWidth(TIME_BOX_WIDTH)
    box.currentIndexChanged.connect(on_change)
    return box


def _batch_items() -> list:
    """一键日常's items in its order (data.Child)."""
    from src.ui.shell import data

    return data.batch_children(data.task_by_name(data.DAILY_BATCH))


def account_ticks(account_id: str) -> set[str]:
    """What the 帳號 has ticked: the current one's from 一键日常 itself."""
    items = _batch_items()
    if not account_id or account_id == accounts.current_id():
        return {item.key for item in items if item.included}
    saved = accounts.saved_ticks(account_id)
    return {item.key for item in items if saved.get(item.key, True)}


class _AccountPill(QAbstractButton):
    """One 帳號 to pick in :class:`TaskPickDialog`: picture and name in a
    pill; ``None`` is 「当前账号」."""

    HEIGHT = 36

    def __init__(self, account, on_click, colour=None):
        from src.ui.shell.accounts_ui import Avatar

        super().__init__()
        self.account_id = account.id if account is not None else ""
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._hover = motion.HoverFade(self, self.update)
        row = hbox(self, (5, 4, 14, 4), 8)
        avatar = Avatar(self.HEIGHT - 10)
        shown = account or accounts.current()
        if colour is not None:
            # On the week calendar: the 帳號's own colour and number.
            avatar.set_colour(colour)
            avatar.set_letter(shown.id)
        avatar.set_account(shown)
        avatar.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(avatar)
        label = Text(display_name(account) if account is not None else "当前账号", "body")
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(label)
        self.clicked.connect(lambda *_: on_click(self.account_id))

    def sizeHint(self) -> QSize:
        return self.layout().sizeHint()

    def minimumSizeHint(self) -> QSize:
        return self.layout().minimumSize()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        on = self.isChecked()
        hover = float(self._hover.value)
        fill = 0.14 if on else 0.06 * hover
        painter.setPen(Qt.NoPen)
        painter.setBrush(mix(theme.color("card"), theme.color("primary"), fill))
        painter.drawRoundedRect(rect, radius, radius)
        pen = painter.pen()
        pen.setColor(theme.color("primary") if on else theme.color("line2"))
        pen.setWidthF(1.6 if on else 1.0)
        pen.setStyle(Qt.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)


class _Gear(QAbstractButton):
    """A small settings gear beside a task (Leo 2026-10-29 「齒輪太大沒質感」):
    a thin grey icon, a soft circle on hover, violet with a dot once the
    slot has its own settings for the task."""

    SIZE = 24
    ICON = 15

    def __init__(self, on_click):
        super().__init__()
        self.own = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._hover = motion.HoverFade(self, self.update)
        self.clicked.connect(lambda *_: on_click())

    def set_own(self, own: bool) -> None:
        if own != self.own:
            self.own = own
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        hover = float(self._hover.value)
        if hover > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(mix(theme.color("card"), theme.color("primary"), 0.10 * hover))
            painter.drawEllipse(rect)
        if self.own:
            colour = theme.color("primary")
        else:
            colour = mix(theme.color("ink3"), theme.color("ink2"), hover)
        inset = (self.SIZE - self.ICON) / 2
        icons.paint(painter, rect.adjusted(inset, inset, -inset, -inset), "settings", colour, 1.7)
        if self.own:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("primary"))
            painter.drawEllipse(QRectF(self.SIZE - 7, 1, 5, 5))


class TaskPickDialog(Floating):
    """What one slot runs, in a window of its own (Leo 2026-10-29 「也要選擇
    該時段進行的任務」「跳出視窗 選擇」): which 帳號 (YES-BD2 #64, only with
    two or more), and the slot's own ticks, starting from that 帳號's (Leo
    2026-10-29 「按帳號勾選不要 全選全不選用打勾的 放上面」)."""

    PANEL_WIDTH = 560
    COLUMNS = 2

    def __init__(self, slot: Slot, parent: QWidget | None, known: list | None = None):
        super().__init__(parent)
        self._known = list(known or [])
        ids = [account.id for account in self._known]
        # A 帳號 deleted since runs the current one, and shows so here.
        self._account = slot.account if slot.account in ids else ""
        column = self.column
        head = hbox(None, (0, 0, 0, 0), 12)
        head.addWidget(HeroIcon("list-checks", 40), 0, Qt.AlignTop)
        titles = vbox(None, (0, 0, 0, 0), 2)
        titles.addWidget(Text("这个时段要跑什么", "h2"))
        when = f"{slot.hour:02d}:{slot.minute:02d}"
        titles.addWidget(
            Text(tf("{time} 到了只跑勾的任务，今天做完的不会再跑", time=when), "sub", wrap=True)
        )
        head.addLayout(titles, 1)
        column.addLayout(head)

        # Two parts, each under its own heading (Leo 2026-10-29 「帳號那邊
        # 排的不好」): which 帳號, as pills like the 帳號 switch; then items.
        self.pills: list[_AccountPill] = []
        if self._known:
            column.addWidget(Text("账号", "h3"))
            # Packed side by side, onto a new line when the names are long.
            holder = QWidget()
            pills = FlowLayout(holder, needAni=False)
            pills.setContentsMargins(0, 0, 0, 0)
            pills.setHorizontalSpacing(8)
            pills.setVerticalSpacing(8)
            for account in [None, *self._known]:
                pill = _AccountPill(account, on_click=self._account_changed)
                pill.setToolTip(t("时间到先切到这个账号再跑"))
                pills.addWidget(pill)
                self.pills.append(pill)
            column.addWidget(holder)
            self._show_account()
            column.addWidget(Text("任务", "h3"))

        # One box on top ticks or clears them all.
        self.every = CheckBox("全选")
        self.every.toggled.connect(self._tick_all)
        column.addWidget(self.every)
        # Until a box is touched, the ticks follow the 帳號 picked above.
        self._follow = slot.tasks is None

        self.items = _batch_items()
        self._settings = {k: dict(v) for k, v in slot.settings.items()}
        chosen = account_ticks(self._account) if slot.tasks is None else set(slot.tasks)
        # Each item: its box, then its ⚙ in a column of their own so they
        # line up; a gap between the two halves.
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(10)
        grid.setColumnMinimumWidth(2, 16)
        grid.setColumnStretch(3 * self.COLUMNS - 1, 1)  # the boxes stay on the left
        self.boxes: list[CheckBox] = []
        self.gears: dict[str, _Gear] = {}
        rows = max(1, (len(self.items) + self.COLUMNS - 1) // self.COLUMNS)
        for index, item in enumerate(self.items):
            row, half = index % rows, index // rows
            box = CheckBox(item.name, item.key in chosen)
            box.toggled.connect(self._ticked)
            grid.addWidget(box, row, 3 * half, Qt.AlignVCenter)
            if item_setting_keys(item.task):
                # Its own settings for this slot only (镜中之战's 倍数 ...).
                gear = _Gear(lambda i=item: self._edit_item(i))
                grid.addWidget(gear, row, 3 * half + 1, Qt.AlignVCenter)
                self.gears[item.key] = gear
            self.boxes.append(box)
        self.list = QWidget()
        self.list.setObjectName("taskList")
        self.list.setStyleSheet("QWidget#taskList { background: transparent; }")
        self.list.setLayout(grid)
        # Many items in a short tool window scroll instead of being cut.
        self.scroll = _RowsView()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(ScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setObjectName("taskView")
        self.scroll.viewport().setStyleSheet("QWidget#taskView { background: transparent; }")
        self.scroll.setWidget(self.list)
        column.addWidget(self.scroll, 1)
        self._show_gears()

        buttons = hbox(None, (0, 6, 0, 0), 8)
        buttons.addStretch(1)
        buttons.addWidget(Button("取消", "secondary", on_click=self.reject))
        self.ok = Button("确定", "primary", on_click=self.accept)
        buttons.addWidget(self.ok)
        column.addLayout(buttons)
        self._count()

    def _account_changed(self, account_id: str) -> None:
        self._account = account_id
        self._show_account()
        if self._follow:
            ticked = account_ticks(account_id)  # that 帳號's own ticks
            for item, box in zip(self.items, self.boxes):
                box.set_checked_quietly(item.key in ticked)
            self._count()

    def _show_account(self) -> None:
        for pill in self.pills:
            pill.setChecked(pill.account_id == self._account)

    def _edit_item(self, item) -> None:
        dialog = ItemSettingsDialog(item, self._settings.get(item.key, {}), self)
        if dialog.exec():
            own = dialog.changed()
            if own:
                self._settings[item.key] = own
            else:
                self._settings.pop(item.key, None)
            self._show_gears()

    def _show_gears(self) -> None:
        # Violet where this slot has its own settings for the item.
        for key, gear in self.gears.items():
            own = bool(self._settings.get(key))
            gear.set_own(own)
            gear.setToolTip(t("这个时段自己的设定（已改）") if own else t("这个时段自己的设定"))

    def _tick_all(self, on: bool) -> None:
        for box in self.boxes:
            box.set_checked_quietly(on)
        self._ticked()

    def _ticked(self, _on: bool = False) -> None:
        self._follow = False
        self._count()

    def _count(self) -> None:
        self.every.set_checked_quietly(all(box.isChecked() for box in self.boxes))
        # Nothing ticked would be a slot that never runs anything.
        self.ok.setEnabled(any(box.isChecked() for box in self.boxes))

    def account(self) -> str:
        """The 帳號 picked ("" = the current one)."""
        return self._account

    def item_settings(self) -> dict[str, dict]:
        """Item -> its settings for this slot ({} = the items' own)."""
        return {k: dict(v) for k, v in self._settings.items() if v}

    def tasks(self) -> list[str]:
        """The items ticked here."""
        return [item.key for item, box in zip(self.items, self.boxes) if box.isChecked()]

    def mouseReleaseEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.reject()
        super().mouseReleaseEvent(event)


def item_setting_keys(task) -> list[str]:
    """The settings an item shows on its own page (none: no ⚙)."""
    if task is None:
        return []
    from src.ui.shell.config_form import visible_keys

    try:
        return visible_keys(task, skip=("启用",))
    except Exception:
        return []


class _SlotConfig(dict):
    """An item's settings as one slot sees them: its own saved settings with
    the slot's changes on top.  Writes stay here (``changed``); the item's
    own settings are never written."""

    def __init__(self, base, own: dict):
        super().__init__({**dict(base.items()), **own})
        self._base = base
        self.changed = dict(own)

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        if self._base.get(key) == value:
            self.changed.pop(key, None)  # back to the item's own
        else:
            self.changed[key] = value

    def get_default(self, key):
        getter = getattr(self._base, "get_default", None)
        return getter(key) if getter is not None else self._base.get(key)


def slot_task(task, own: dict):
    """A stand-in for ``task`` that config_form draws exactly like its page
    (same class name for its panel, same types and hints), on a
    :class:`_SlotConfig`."""
    stand_in = type(type(task).__name__, (), {})()
    stand_in.name = getattr(task, "name", "")
    stand_in.config = _SlotConfig(task.config, own)
    for attribute in ("config_type", "config_description", "default_config"):
        setattr(stand_in, attribute, getattr(task, attribute, None))
    return stand_in


class ItemSettingsDialog(Floating):
    """One item's settings for one 定时启动 slot (Leo 2026-10-29 「鏡中之戰也
    可以選倍數那些」): the same form as its own page, kept with the slot."""

    PANEL_WIDTH = 520

    def __init__(self, item, own: dict, parent: QWidget | None):
        from src.ui.shell.config_form import ConfigForm

        super().__init__(parent)
        self.task = slot_task(item.task, own)
        column = self.column
        head = hbox(None, (0, 0, 0, 0), 12)
        head.addWidget(HeroIcon("settings", 40), 0, Qt.AlignTop)
        titles = vbox(None, (0, 0, 0, 0), 2)
        titles.addWidget(Text(item.name, "h2"))
        titles.addWidget(Text("只在这个时段这样跑，任务本身的设定不变", "sub", wrap=True))
        head.addLayout(titles, 1)
        column.addLayout(head)
        self.form = ConfigForm(self.task, keys=item_setting_keys(item.task))
        column.addWidget(self.form)
        buttons = hbox(None, (0, 6, 0, 0), 8)
        self.back = Button("", "ghost", "rotate-ccw", on_click=self._same_as_item)
        self.back.setFixedSize(DELETE_SIZE, DELETE_SIZE)
        self.back.setToolTip(t("改回和任务本身一样"))
        buttons.addWidget(self.back)
        buttons.addStretch(1)
        buttons.addWidget(Button("取消", "secondary", on_click=self.reject))
        buttons.addWidget(Button("确定", "primary", on_click=self.accept))
        column.addLayout(buttons)

    def _same_as_item(self) -> None:
        for key in list(self.task.config.changed):
            self.task.config[key] = self.task.config._base.get(key)
        self.form.sync()

    def changed(self) -> dict:
        """The settings this slot runs differently from the item's own."""
        return dict(self.task.config.changed)

    def mouseReleaseEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.reject()
        super().mouseReleaseEvent(event)


def display_name(account) -> str:
    from src.ui.shell.accounts_ui import display_name as name

    return name(account)


def __getattr__(name):
    # The week calendar (Leo 2026-10-29) lives in its own module, which
    # imports this one; loading it lazily keeps either import order working.
    if name == "ScheduleDialog":
        from src.ui.shell.schedule_week import ScheduleDialog

        return ScheduleDialog
    raise AttributeError(name)
