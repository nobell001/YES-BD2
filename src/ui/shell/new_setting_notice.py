"""A one-time walk-through after an update that changed a player's setting.

Leo 2026-10-12: the 快速狩猎 update turns 双倍策略/资源倾向 into four rows of
switches, 「所以這次更新完第一次開工具 指引用戶去點這個設定」, shaped like a
web site's first-visit tour (「有點像這種樣子」): the window dims, the real
control stays lit with a ring, and a small card beside it says what it is,
with 跳过 / 上一步 / 下一步.  The lit part can be clicked, so the switches can
be changed during the tour.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QFrame, QWidget

from src.ui.shell import cover, data, theme
from src.ui.shell.safe import guarded
from src.ui.shell.widgets import Button, Text, hbox, vbox

CARD_WIDTH = 300
HOLE_PAD = 8  # air between the lit control and the ring
GAP = 14  # between the ring and the card
RING = 3
FOLLOW_MS = 120  # the lit part follows page moves and window resizes
RETRY_MS = 30_000


@dataclass
class Step:
    target: Callable[[], QWidget | None]
    title: str
    body: str
    before: Callable[[], None] | None = None


class _Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(CARD_WIDTH)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        corner = float(theme.radius()) + 4
        painter.setPen(QPen(theme.color("line2"), 1))
        painter.setBrush(theme.color("card"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), corner, corner)


class CoachMarks(QWidget):
    """Covers ``window``; dims all but the current step's control."""

    def __init__(self, window: QWidget, steps: list[Step], on_done: Callable[[], None]):
        super().__init__(window)
        self._window = window
        self._steps = steps
        self._on_done = on_done
        self._index = 0
        self._hole = QRect()
        self._area = QRect()
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet(theme.style_sheet())

        self.card = _Card(self)
        column = vbox(self.card, (18, 14, 18, 14), 8)
        self.count = Text("", "muted")
        column.addWidget(self.count)
        self.title = Text("", "h2", wrap=True)
        column.addWidget(self.title)
        self.body = Text("", "sub", wrap=True)
        column.addWidget(self.body)
        row = hbox(None, (0, 6, 0, 0), 8)
        self.skip = Button("跳过", "ghost", size="sm", on_click=self.finish)
        row.addWidget(self.skip)
        row.addStretch(1)
        self.back = Button("上一步", "secondary", size="sm", on_click=lambda: self.go(-1))
        row.addWidget(self.back)
        self.next = Button("下一步", "primary", size="sm", on_click=lambda: self.go(1))
        row.addWidget(self.next)
        column.addLayout(row)

        self._follow = QTimer(self)
        self._follow.timeout.connect(guarded("coach marks", self._tick))
        self._cover = None

    # ------------------------------------------------------------ steps

    def start(self) -> None:
        self._cover = cover.follow(self, self._window, guarded("coach marks", self._place))
        self.show()
        self.raise_()
        self._show_step()
        self._follow.start(FOLLOW_MS)

    def go(self, delta: int) -> None:
        index = self._index + delta
        if index >= len(self._steps):
            self.finish()
            return
        self._index = max(0, index)
        self._show_step()

    def _show_step(self) -> None:
        step = self._steps[self._index]
        if step.before is not None:
            step.before()
        last = self._index == len(self._steps) - 1
        self.count.set_text(f"{self._index + 1} / {len(self._steps)}")
        self.title.set_text(step.title)
        self.body.set_text(step.body)
        self.back.setVisible(self._index > 0)
        self.next.set_label("知道了" if last else "下一步")
        self.skip.setVisible(not last)
        self._place()

    def finish(self) -> None:
        self._follow.stop()
        self.hide()
        self.deleteLater()
        self._on_done()

    # ------------------------------------------------------------ look

    def _tick(self) -> None:
        # Besides the window's own resize events, in case one was missed.
        if self._cover is None or not self._cover.sync():
            self._place()

    def _target_rect(self) -> QRect:
        target = self._steps[self._index].target()
        if target is None or not target.isVisible():
            return QRect()
        top_left = target.mapTo(self._window, QPoint(0, 0))
        return QRect(top_left, target.size()).adjusted(-HOLE_PAD, -HOLE_PAD, HOLE_PAD, HOLE_PAD)

    def _place(self) -> None:
        hole = self._target_rect()
        self.card.layout().activate()
        height = self.card.layout().heightForWidth(CARD_WIDTH)
        self.card.setFixedHeight(height if height > 0 else self.card.sizeHint().height())
        card = self.card.size()
        area = self.rect()
        if hole.isNull():
            x, y = (area.width() - card.width()) // 2, (area.height() - card.height()) // 2
        elif hole.right() + GAP + card.width() <= area.right() - GAP:
            x, y = hole.right() + GAP, hole.top()  # beside, like the web tour
        else:
            x, y = hole.left(), hole.bottom() + GAP
            if y + card.height() > area.bottom() - GAP:
                y = hole.top() - GAP - card.height()
        x = min(max(GAP, x), area.width() - card.width() - GAP)
        y = min(max(GAP, y), area.height() - card.height() - GAP)
        self.card.move(x, y)
        if hole != self._hole or area != self._area:
            # A new window size needs a new mask too, or the dimmed part
            # stays the old size (Leo 2026-10-21, after 最大化).
            self._hole = hole
            self._area = QRect(area)
            # Clicks in the lit part reach the control under it.
            mask = QRegion(area)
            if not hole.isNull():
                mask = mask.subtracted(QRegion(hole, QRegion.RegionType.Rectangle))
            self.setMask(mask)
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        dark = theme.tokens() is theme.DARK
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        corner = 8.0  # small enough to cover the square lit part's corners
        # The ring sits just outside the lit part (which this widget does not
        # cover, so the control under it stays clickable).
        ring = QRectF(self._hole).adjusted(-RING, -RING, RING, RING)
        if not self._hole.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(ring, corner, corner)
            shade = shade.subtracted(hole)
        painter.fillPath(shade, theme.color("shot", 0.62 if dark else 0.42))
        if not self._hole.isNull():
            painter.setPen(QPen(theme.color("primary"), RING))
            painter.setBrush(Qt.NoBrush)
            half = RING / 2
            painter.drawRoundedRect(ring.adjusted(half, half, -half, -half), corner, corner)

    def mousePressEvent(self, event):
        event.accept()  # the dimmed part does nothing; the card has the buttons


def quick_hunt_steps(shell) -> list[Step]:
    def daily_item():
        return shell.sidebar.items.get("daily")

    def rows():
        page = shell.pages.get("daily")
        return getattr(page, "form", None)

    return [
        Step(
            daily_item,
            "快速狩猎有新设定",
            "双倍时米饭打哪里，现在可以自己选，也能打狩猎场。设定在「任务设定」里。",
        ),
        Step(
            rows,
            "双倍时米饭打哪里",
            "每行选一个：金币、史莱姆或狩猎场，都用 MAX。已照你原本的设定开好，确认一下就好。",
            before=lambda: shell.open_task("daily", "快速狩猎"),
        ),
    ]


def event_battle_steps(shell) -> list[Step]:
    """Leo 2026-10-14: 只刷普通难度 back off, shown once 「和之前更新快速狩獵時一樣」."""

    def daily_item():
        return shell.sidebar.items.get("daily")

    def rows():
        page = shell.pages.get("daily")
        return getattr(page, "form", None)

    return [
        Step(
            daily_item,
            "活动战斗设定有更新",
            "「只刷普通难度」改成默认不勾，挑战战斗会推到你选的最高关卡。设定在「任务设定」里。",
        ),
        Step(
            rows,
            "活动战斗设定",
            "「只刷普通难度」已关掉，想只打普通战斗再打开。"
            "「挑战战斗最高关卡」可选第5、10、15关，推到后剩下的AP用快速战斗刷这一关。",
            before=lambda: shell.open_task("daily", "活动每日战斗"),
        ),
    ]


def stone_steps(shell) -> list[Step]:
    """Leo 2026-10-20: the 圣石 element can be picked; the tool still picks the
    least held one until the player changes it, and says so once."""
    from src.tasks.quick_hunt import QUICK_HUNT_STONE_KEY

    def daily_item():
        return shell.sidebar.items.get("daily")

    def stone_row():
        form = getattr(shell.pages.get("daily"), "form", None)
        row = (getattr(form, "_rows", None) or {}).get(QUICK_HUNT_STONE_KEY)
        return row[1] if row else form

    return [
        Step(
            daily_item,
            "快速狩猎有新设定",
            "火把打哪个属性的圣石，现在可以自己选。设定在「任务设定」里。",
        ),
        Step(
            stone_row,
            "圣石属性",
            "默认还是「最少」，自动打目前最少的属性。想固定刷某个属性就点它。",
            before=lambda: shell.open_task("daily", "快速狩猎"),
        ),
    ]


def skill_interval_steps(shell) -> list[Step]:
    """Leo 2026-10-20 「更新好後也要提示用戶這邊有更新」."""

    def map_item():
        return shell.sidebar.items.get("map")

    def interval():
        page = shell.pages.get("map")
        return getattr(page, "interval_button", None)

    return [
        Step(
            map_item,
            "跑图技能间隔换位置了",
            "吸收、召集、压制之间隔几秒，现在在「跑图」页就能改。",
        ),
        Step(
            interval,
            "技能间隔",
            "点这里调整，0.5 到 2 秒。电脑或网络较慢、技能常常没按上时调大。",
            before=lambda: shell.navigate("map"),
        ),
    ]


def close_game_steps(shell) -> list[Step]:
    """Leo 2026-10-20 「更新後提醒用戶有改動」: 关闭游戏 sits in the window that
    opens on 一键完成日常 (Leo 2026-10-21 「改放這裡」), off by default."""

    def start_button():
        return getattr(shell.pages.get("home"), "start_all", None)

    return [
        Step(
            start_button,
            "做完后可以关闭游戏",
            "按「一键完成日常」后，确认视窗左下角可以勾「全部做完且没有失败后关闭游戏」。默认不勾。",
            before=lambda: shell.navigate("home"),
        ),
    ]


def new_dailies_steps(shell) -> list[Step]:
    """Leo 2026-10-21 「這次新增兩個功能 更新上去和以前一樣 要跳窗告訴用戶」:
    救赎之塔 and 亲密度谈心 joined 一键完成日常 (on unless switched off)."""

    def daily_item():
        return shell.sidebar.items.get("daily")

    def row(key):
        def target():
            page = shell.pages.get("daily")
            return (getattr(page, "_rows", None) or {}).get(key) or getattr(page, "list_card", None)

        return target

    return [
        Step(
            daily_item,
            "新增两个每日项目",
            "「救赎之塔」和「亲密度谈心」加进一键完成日常了，会跟其他日常一起跑。",
        ),
        Step(
            row("救赎之塔"),
            "救赎之塔",
            "每天到恶魔城的救赎之塔按快速战斗，次数选 MAX。"
            "不想跑就点它，关掉右边的「加入一键完成日常」。",
            before=lambda: shell.open_task("daily", "救赎之塔"),
        ),
        Step(
            row("亲密度谈心"),
            "亲密度谈心",
            "每天在主页的亲密度和服装谈心，按题库选答案。"
            "不想跑就点它，关掉右边的「加入一键完成日常」。",
            before=lambda: shell.open_task("daily", "亲密度谈心"),
        ),
    ]


def run_notify_steps(shell) -> list[Step]:
    """Leo 2026-10-22 「用戶引導甚麼的 都要做好」: 跑完通知 is new on 设置, off by
    default."""

    def settings_item():
        return shell.sidebar.items.get("settings")

    def row():
        return getattr(shell.pages.get("settings"), "wechat_row", None)

    return [
        Step(
            settings_item,
            "跑完可以发到微信",
            "一键完成日常跑完，可以把结果发到你自己的微信。默认关闭，设定在「设置」里。",
        ),
        Step(
            row,
            "跑完发到微信",
            "打开右边的开关，照着步骤用微信扫码拿到 SendKey，贴上就好。",
            before=lambda: shell.navigate("settings"),
        ),
    ]


def schedule_steps(shell) -> list[Step]:
    """定时启动 is new on 首页, off by default (Leo 2026-10-22)."""

    def card():
        return getattr(shell.pages.get("home"), "schedule_card", None)

    return [
        Step(
            card,
            "可以定时自动跑日常",
            "在首页设定几点，时间到了就自动跑一键完成日常，工具没开也会自己打开。"
            "默认关闭，点这张卡片设定。",
            before=lambda: shell.navigate("home"),
        ),
    ]


def status_bar_steps(shell) -> list[Step]:
    """游戏里显示执行状态 is new on 设置, off by default (Leo 2026-10-28 「預設關閉
    但是更新後要提示用戶這裡可以開啟」)."""

    def settings_item():
        return shell.sidebar.items.get("settings")

    def row():
        return getattr(shell.pages.get("settings"), "status_bar_row", None)

    return [
        Step(
            settings_item,
            "游戏里可以显示执行状态",
            "跑的时候在游戏画面上方显示正在跑什么、跑到第几项，还有暂停、停止按钮。"
            "默认关闭，在「设置」里打开。",
        ),
        Step(
            row,
            "游戏里显示执行状态",
            "打开右边的开关就好。它不挡点击、截图拍不到，不会影响辨识。",
            before=lambda: shell.navigate("settings"),
        ),
    ]


def _show_once(shell, class_name: str, key: str, steps, on_done: Callable[[], None]) -> bool:
    task = data.task_by_class_name(class_name)
    config = getattr(task, "config", None)
    if config is None or not config.get(key):
        return False
    # Shown once, however it is closed.
    config[key] = False
    tour = CoachMarks(shell.window, steps(shell), on_done)
    shell._coach_marks = tour
    tour.start()
    return True


def show_quick_hunt_notice(shell, on_done: Callable[[], None] = lambda: None) -> bool:
    """Walk the player to the 快速狩猎 rows once, when the update moved old settings."""
    from src.tasks.QuickHuntTask import QUICK_HUNT_NOTICE_KEY

    return _show_once(shell, "QuickHuntTask", QUICK_HUNT_NOTICE_KEY, quick_hunt_steps, on_done)


def show_event_battle_notice(shell, on_done: Callable[[], None] = lambda: None) -> bool:
    """Walk the player to the 活动每日战斗 settings once after this update."""
    from src.tasks.EventBattleTask import EVENT_NOTICE_KEY

    return _show_once(shell, "EventBattleTask", EVENT_NOTICE_KEY, event_battle_steps, on_done)


def show_stone_notice(shell, on_done: Callable[[], None] = lambda: None) -> bool:
    """Walk the player to the 快速狩猎 圣石属性 row once after this update."""
    from src.tasks.QuickHuntTask import STONE_NOTICE_KEY

    return _show_once(shell, "QuickHuntTask", STONE_NOTICE_KEY, stone_steps, on_done)


def show_skill_interval_notice(shell, on_done: Callable[[], None] = lambda: None) -> bool:
    """Show 跑图's 技能间隔 in its new place once after this update."""
    from src.tasks.MapCollectionTask import MAP_NOTICE_KEY

    return _show_once(shell, "MapCollectionTask", MAP_NOTICE_KEY, skill_interval_steps, on_done)


def show_close_game_notice(shell, on_done: Callable[[], None] = lambda: None) -> bool:
    """Show 一键日常's new 关闭游戏 option once after this update."""
    from src.tasks.DailyBatchTask import CLOSE_GAME_NOTICE_KEY

    return _show_once(shell, "DailyBatchTask", CLOSE_GAME_NOTICE_KEY, close_game_steps, on_done)


def show_new_dailies_notice(shell, on_done: Callable[[], None] = lambda: None) -> bool:
    """Show the two new 每日 items once after this update."""
    from src.tasks.DailyBatchTask import NEW_DAILIES_NOTICE_KEY

    return _show_once(shell, "DailyBatchTask", NEW_DAILIES_NOTICE_KEY, new_dailies_steps, on_done)


def show_run_notify_notice(shell, on_done: Callable[[], None] = lambda: None) -> bool:
    """Show 设置's new 跑完发到微信 once after this update."""
    from src.tasks.DailyBatchTask import RUN_NOTIFY_NOTICE_KEY

    return _show_once(shell, "DailyBatchTask", RUN_NOTIFY_NOTICE_KEY, run_notify_steps, on_done)


def show_schedule_notice(shell, on_done: Callable[[], None] = lambda: None) -> bool:
    """Show 首页's new 定时启动 card once after this update."""
    from src.tasks.DailyBatchTask import SCHEDULE_NOTICE_KEY

    return _show_once(shell, "DailyBatchTask", SCHEDULE_NOTICE_KEY, schedule_steps, on_done)


def show_status_bar_notice(shell, on_done: Callable[[], None] = lambda: None) -> bool:
    """Show 设置's new 游戏里显示执行状态 once after this update."""
    from src.tasks.DailyBatchTask import STATUS_BAR_NOTICE_KEY

    return _show_once(shell, "DailyBatchTask", STATUS_BAR_NOTICE_KEY, status_bar_steps, on_done)


NOTICES = (
    show_new_dailies_notice,
    show_quick_hunt_notice,
    show_event_battle_notice,
    show_stone_notice,
    show_skill_interval_notice,
    show_close_game_notice,
    show_run_notify_notice,
    show_schedule_notice,
    show_status_bar_notice,
)


def show_pending(shell, notices=None) -> bool:
    """Each pending walk-through, one after the other."""
    notices = list(NOTICES if notices is None else notices)
    while notices:
        show = notices.pop(0)
        if show(shell, on_done=lambda rest=list(notices): show_pending(shell, rest)):
            return True
    return False


def _ready() -> bool:
    """Not over a run, nor while 打开工具就自动跑 counts down (then it waits)."""
    from src.ui.shell import autorun

    return not data.busy() and autorun.seconds_left() is None


def schedule(shell, delay_ms: int = 2500) -> None:
    from src.compat.quiet_scheduled_open import scheduled

    if scheduled():
        return  # 定时启动 opened the tool: nobody to walk; the next open shows them

    def check() -> None:
        if not _ready():
            QTimer.singleShot(RETRY_MS, guarded("new setting notice", check))
            return
        show_pending(shell)

    QTimer.singleShot(delay_ms, guarded("new setting notice", check))
