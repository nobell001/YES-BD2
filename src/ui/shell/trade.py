"""跑商: the three steps (买 → 做料理 → 卖) with pictures, and the sale calendar."""

from __future__ import annotations

import calendar as month_calendar
from datetime import date

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.ui.shell import actions, data, motion, theme
from src.ui.shell.config_form import ConfigForm
from src.ui.shell.page import Page, pill, set_pill
from src.ui.shell.widgets import (
    Button,
    Card,
    CheckBox,
    IconLabel,
    IconTile,
    Inset,
    Picture,
    Separator,
    Text,
    Toggle,
    attach_hint,
    clear_layout,
    draw_fitted,
    grid_container,
    hbox,
    t,
    tf,
    vbox,
)

TASK_NAME = "每日跑商"
BARGAIN_TASK = "循环砍价"
BATCH_KEY = "跑商"
LAST_DISH = "街头烤鸡肉串"


class DishTile(QWidget):
    """A dish picture; picked ones carry their cooking order, others are grey."""

    clicked = Signal()

    def __init__(self, name: str, size: int = 58, parent=None):
        super().__init__(parent)
        self.name = name
        self._pixmap = QPixmap(data.dish_picture(name) or "")
        self._picked = False
        self._label = ""
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(t(name))
        self._hover = motion.HoverFade(self, self.update)

    def set_state(self, picked: bool, label: str) -> None:
        if (picked, label) != (self._picked, self._label):
            self._picked, self._label = picked, label
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        if self._picked:
            painter.setPen(QPen(theme.color("dish_on_line"), 1.6))
        else:
            painter.setPen(QPen(theme.color("line"), 1))
        painter.setBrush(theme.color("inset"))
        # A small corner: the picture is square and must not poke out of a round frame.
        painter.drawRoundedRect(rect, theme.corner(6, 8), theme.corner(6, 8))
        if not self._pixmap.isNull():
            painter.setOpacity(1.0 if self._picked else 0.35)
            # Hovered: the picture grows a little into its frame.
            pad = 4 - 2.5 * self._hover.value
            inner = rect.adjusted(pad, pad, -pad, -pad)
            draw_fitted(painter, inner, self._pixmap, self.devicePixelRatioF())
            painter.setOpacity(1.0)
        if self._picked and self._label:
            font = QFont(self.font())
            font.setPixelSize(10)
            theme.strong(font)
            painter.setFont(font)
            badge = QRectF(
                3, 3, max(16, 8 + painter.fontMetrics().horizontalAdvance(self._label)), 16
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("dish_badge"))
            painter.drawRoundedRect(badge, theme.corner(4), theme.corner(4))
            painter.setPen(theme.color("dish_badge_ink"))
            painter.drawText(badge, Qt.AlignCenter, self._label)


class StickerButton(QWidget):
    """循环砍价's picture in the 买 card, a button.

    Leo 2026-10-11: hovered, her eye glints red; the mouse gone, the picture
    is as it was.
    """

    clicked = Signal()
    # Her visible (closed) eye in the sticker, as a share of its side.
    EYE = (0.51, 0.515)  # on the closed eyelid (Leo: start lower)

    def __init__(self, path: str, size: int = 96, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap(path)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = motion.HoverFade(self, self.update)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        self.update()

    def paintEvent(self, _event):
        # Only the sticker, no frame behind it (Leo 2026-10-11: 「去背乾淨」).
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(1.0 if self.isEnabled() else 0.4)
        inner = QRectF(self.rect())
        draw_fitted(painter, inner, self._pixmap, self.devicePixelRatioF())
        glow = self._hover.value if self.isEnabled() else 0.0
        if glow > 0.01:
            self._paint_glint(painter, inner, glow)

    def _paint_glint(self, painter: QPainter, inner: QRectF, glow: float) -> None:
        """A red glint and beam: stronger than a glint, short of scary (Leo 2026-10-11)."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QRadialGradient

        eye = QPointF(
            inner.x() + inner.width() * self.EYE[0], inner.y() + inner.height() * self.EYE[1]
        )
        side = inner.width()
        painter.save()
        end = QPointF(eye.x() + side * 0.45, eye.y() + side * 0.12)
        for width, alpha in ((side * 0.09, 70), (side * 0.04, 170), (side * 0.014, 255)):
            pen = QPen(QColor(255, 60, 70, int(alpha * glow)), width)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(eye, end)
        radius = side * 0.13
        gradient = QRadialGradient(eye, radius)
        gradient.setColorAt(0.0, QColor(255, 245, 245, int(255 * glow)))
        gradient.setColorAt(0.3, QColor(255, 50, 60, int(210 * glow)))
        gradient.setColorAt(1.0, QColor(255, 50, 60, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(eye, radius, radius)
        painter.restore()


class ItemIcon(QWidget):
    """A sale item's icon on a soft square."""

    def __init__(self, name: str, size: int = 30, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap(data.item_picture(name) or "")
        self.setFixedSize(size, size)
        self.setToolTip(t(name))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("inset"))
        painter.drawRoundedRect(QRectF(self.rect()), theme.corner(5), theme.corner(5))
        if not self._pixmap.isNull():
            inner = QRectF(self.rect().adjusted(2, 2, -2, -2))
            draw_fitted(painter, inner, self._pixmap, self.devicePixelRatioF())


class DayCell(QWidget):
    """One calendar day: the date and up to three item icons (+N)."""

    clicked = Signal(int)

    def __init__(self, day: int, items: list[str], parent=None):
        super().__init__(parent)
        self.day = day
        self.items = items
        self._pixmaps = [QPixmap(data.item_picture(name) or "") for name in items[:3]]
        self._today = False
        self._picked = False
        self._off = 0
        self.setMinimumSize(QSize(54, 54))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(58)
        self.setCursor(Qt.PointingHandCursor if items else Qt.ArrowCursor)
        if items:
            self.setToolTip(t("、").join(t(item) for item in items))

    def set_state(self, today: bool, picked: bool, unticked: int) -> None:
        if (today, picked, unticked) != (self._today, self._picked, self._off):
            self._today, self._picked, self._off = today, picked, unticked
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.items:
            self.clicked.emit(self.day)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("inset" if self.items else "card"))
        painter.drawRoundedRect(rect, theme.corner(5), theme.corner(5))
        if self._today:
            # 淡紫 fills today with a soft violet; 深色 only colours its number.
            painter.setBrush(theme.color("today"))
            painter.drawRoundedRect(rect, theme.corner(5), theme.corner(5))
        if self._picked:
            painter.setPen(QPen(theme.color("pick"), 2))
            painter.setBrush(theme.color("pick_bg"))
            painter.drawRoundedRect(
                rect.adjusted(0.5, 0.5, -0.5, -0.5), theme.corner(5), theme.corner(5)
            )
        font = QFont(self.font())
        font.setPixelSize(11)
        theme.strong(font, digits=True)
        painter.setFont(font)
        ink = (
            theme.color("today_ink")
            if self._today
            else theme.color("ink" if self.items else "ink3")
        )
        painter.setPen(ink)
        painter.drawText(QRectF(6, 3, 30, 16), Qt.AlignLeft | Qt.AlignVCenter, str(self.day))
        icon = 18
        x = 5.0
        y = self.height() - icon - 6
        # As many icons as the cell is wide (at most 3); "+N" takes one slot.
        fit = min(3, max(1, int((self.width() - 9) // (icon + 1))))
        shown = self._pixmaps[: len(self.items) if len(self.items) <= fit else max(1, fit - 1)]
        for pixmap in shown:
            if not pixmap.isNull():
                draw_fitted(painter, QRectF(x, y, icon, icon), pixmap, self.devicePixelRatioF())
            x += icon + 1
        if len(self.items) > len(shown):
            painter.setPen(ink)
            font.setPixelSize(10)
            painter.setFont(font)
            painter.drawText(
                QRectF(x, y, 24, icon),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"+{len(self.items) - len(shown)}",
            )
        if self._off:
            painter.setPen(theme.color("warn"))
            painter.setBrush(theme.color("warn"))
            painter.drawEllipse(QRectF(self.width() - 10, 6, 5, 5))


class TradePage(Page):
    interval = 2000

    def __init__(self):
        super().__init__("shellTrade", "跑商", "每天一次：买 → 做料理 → 卖")
        self._hints: list[tuple[QWidget, IconLabel, str]] = []
        self.status = self.add_action(pill(""))
        self.start_button = self.add_action(
            Button("开始跑商", "primary", "play", on_click=self._start)
        )
        self.more_button = self.add_action(
            Button("", "icon", "ellipsis", on_click=self._toggle_more)
        )
        self.more = Card()
        self.more.hide()
        self.body.addWidget(self.more)
        self._more_built = False

        steps, grid = grid_container(250, 14, 3)
        self.buy_card = self._step_card(grid, 1, "shopping-cart", "买", "买")
        self.cook_card = self._step_card(grid, 2, "chef-hat", "做料理", "制作料理", "每道做到最多")
        self.sell_card = self._step_card(grid, 3, "coins", "卖", "卖")
        self.body.addWidget(steps)
        self._build_buy()
        self._build_cook()
        self._build_sell()
        self._build_calendar()
        self.body.addStretch(1)
        self._picked_day: int | None = None

    def task(self):
        return data.task_by_name(TASK_NAME)

    def _hint_label(self, text: str, key: str) -> QWidget:
        """A setting's name with an ⓘ that shows only once its hint is known."""
        box = QWidget()
        row = hbox(box, (0, 0, 0, 0), 4)
        row.addWidget(Text(text, "sub"))
        info = IconLabel("info", 13, "ink3")
        info.hide()
        row.addWidget(info)
        self._hints.append((box, info, key))
        self._fill_hints()
        return box

    def _fill_hints(self) -> None:
        # The task can still be loading when the page is built: fill on refresh.
        task = self.task()
        if task is None:
            return
        descriptions = getattr(task, "config_description", None) or {}
        for box, info, key in self._hints:
            if box.toolTip():
                continue
            hint = str(descriptions.get(key) or "").strip()
            info.setVisible(attach_hint(box, t(hint)) if hint else False)

    # ---------------------------------------------------------------- steps

    def _step_card(self, grid, number: int, icon_name: str, title: str, key: str, hint: str = ""):
        card = Card()
        column = vbox(card, (16, 14, 16, 16), 12)
        head = hbox(None, (0, 0, 0, 0), 8)
        badge = Text(str(number), "tag")
        head.addWidget(badge)
        head.addWidget(IconTile(icon_name, 30, 17, kind="trade"))
        head.addWidget(Text(title, "h2"))
        if hint:
            # Long in some languages (Korean was cut, 2026-10-22 check): «…» and a tooltip.
            head.addWidget(Text(hint, "muted", elide=True), 1)
        else:
            head.addStretch(1)
        done = Text("", "pill")
        done.setProperty("tone", "ok")
        done.hide()
        head.addWidget(done)
        toggle = Toggle(True, small=True)
        toggle.toggled.connect(lambda on, k=key: self._set(k, bool(on)))
        head.addWidget(toggle)
        column.addLayout(head)
        card.column = column
        card.toggle = toggle
        card.key = key
        card.done = done
        grid.addWidget(card)
        return card

    def _set(self, key: str, value) -> None:
        task = self.task()
        if task is not None:
            task.config[key] = value
        self.refresh()

    def _build_buy(self) -> None:
        column = self.buy_card.column
        # The cartridge and the merchant on one line, the words under them
        # across the card: between the two pictures 「Chapter 1 Merchant」 was
        # cut, then one word a line (2026-10-22 check).
        row = hbox(None, (0, 0, 0, 0), 12)
        picture = Picture(data.cartridge_picture("S1"), fixed=QSize(84, 64))
        row.addWidget(picture, 0, Qt.AlignBottom)
        row.addStretch(1)
        self.bargain_button = StickerButton(data.bargain_picture(), 96)
        self.bargain_button.clicked.connect(self._open_bargain)
        attach_hint(self.bargain_button, t("练砍价技能"), below=True)
        row.addWidget(self.bargain_button, 0, Qt.AlignTop)
        column.addLayout(row)
        texts = vbox(None, (0, 0, 0, 0), 2)
        texts.addWidget(Text("第一章商人", "h3", wrap=True))
        texts.addWidget(Text("砍价，买下收藏的商品", "muted", wrap=True))
        column.addLayout(texts)
        self.bargain_running = QWidget()
        running = hbox(self.bargain_running, (0, 0, 0, 0), 8)
        running.addWidget(IconLabel("loader-circle", 15, "primary"))
        self.bargain_state = Text("砍价执行中", "sub")
        running.addWidget(self.bargain_state, 1)
        self.bargain_stop = Button("停止", "danger", "square", size="sm", on_click=self._stop_bargain)
        running.addWidget(self.bargain_stop)
        self.bargain_running.hide()
        column.addWidget(self.bargain_running)
        self.bargain_key = Text("", "muted")
        self.bargain_key.hide()
        column.addWidget(self.bargain_key)
        column.addStretch(1)
        # Leo (2026-10-05): the tool buys only the game's favourites.
        column.addWidget(self._tip(("先在游戏里把要买的商品加入收藏", "工具只买「收藏」里的商品")))

    @staticmethod
    def _tip(lines) -> QWidget:
        """A soft note at the bottom of a step card, with an info icon."""
        box = Inset()
        row = hbox(box, (12, 10, 12, 10), 8)
        row.addWidget(IconLabel("info", 15, "primary"), 0, Qt.AlignTop)
        texts = vbox(None, (0, 0, 0, 0), 3)
        for line in lines:
            texts.addWidget(Text(line, "sub", wrap=True))
        row.addLayout(texts, 1)
        return box

    def _build_cook(self) -> None:
        column = self.cook_card.column
        self.dish_box = QWidget()
        from qfluentwidgets import FlowLayout

        flow = FlowLayout(self.dish_box, needAni=False)
        flow.setContentsMargins(0, 0, 0, 0)
        flow.setHorizontalSpacing(6)
        flow.setVerticalSpacing(6)
        self.dishes: dict[str, DishTile] = {}
        task = self.task()
        options = list(
            ((task.config_type.get("料理清单") or {}).get("options") or []) if task else []
        )
        for name in options:
            tile = DishTile(name, 52)
            tile.clicked.connect(lambda n=name: self._toggle_dish("料理清单", n))
            flow.addWidget(tile)
            self.dishes[name] = tile
        column.addWidget(self.dish_box)
        column.addWidget(Separator())
        names = hbox(None, (0, 0, 0, 0), 8)
        names.addWidget(Text("5 星料理", "sub"))
        names.addWidget(Text("点选才做", "muted"), 1)
        column.addLayout(names)
        line = hbox(None, (0, 0, 0, 0), 6)
        self.five: dict[str, DishTile] = {}
        five_options = list(
            ((task.config_type.get("5星料理") or {}).get("options") or []) if task else []
        )
        for name in five_options:
            tile = DishTile(name, 40)
            tile.clicked.connect(lambda n=name: self._toggle_dish("5星料理", n))
            line.addWidget(tile)
            self.five[name] = tile
        line.addStretch(1)
        column.addLayout(line)

    def _toggle_dish(self, key: str, name: str) -> None:
        task = self.task()
        if task is None:
            return
        options = list((task.config_type.get(key) or {}).get("options") or [])
        selected = set(task.config.get(key) or [])
        selected ^= {name}
        task.config[key] = [option for option in options if option in selected]
        self.refresh()

    def _build_sell(self) -> None:
        column = self.sell_card.column
        self.today_items_box = QWidget()
        self.today_items = hbox(self.today_items_box, (0, 0, 0, 0), 6)
        column.addWidget(self.today_items_box)
        self.sell_title = Text("", "h3")
        self.sell_sub = Text("照下面的出售日历", "muted")
        column.addWidget(self.sell_title)
        column.addWidget(self.sell_sub)
        column.addStretch(1)
        column.addWidget(
            self._tip(("只卖出售日历里当天勾选的商品", "标「留」的商品会留下那个数量，其余卖掉"))
        )
        self._today_items_key = None

    # ---------------------------------------------------------------- bargain
    # 循环砍价 (Leo 2026-10-11): a small icon in the 买 card opens the loop
    # count; while it runs the card says so with a 停止 that works like
    # 首页's, and the page stays here.

    def _bargain_task(self):
        return data.task_by_name(BARGAIN_TASK)

    def _open_bargain(self) -> None:
        from src.tasks.BargainLoopTask import LOOP_COUNT_KEY, loop_count

        task = self._bargain_task()
        if task is None:
            actions.start(None, self.window())
            return
        box, spin = self._bargain_dialog(task)
        if not box.exec():
            return
        task.config[LOOP_COUNT_KEY] = loop_count(spin.value())
        self._stay_on_start = True
        try:
            actions.start(task, self.window())
        finally:
            self._stay_on_start = False
        self.refresh()

    def _bargain_dialog(self, task):
        from qfluentwidgets import MessageBoxBase, SpinBox

        from src.tasks.BargainLoopTask import DEFAULT_LOOPS, LOOP_COUNT_KEY, MAX_LOOPS, loop_count

        box = MessageBoxBase(self.window())
        # The box hangs on the main window, outside the page and its style
        # sheet (live 4K 2026-10-11: grey buttons, plain text), so the
        # content and the buttons carry the shell style themselves.
        body = QWidget()
        body.setStyleSheet(theme.style_sheet())
        box.viewLayout.addWidget(body)
        column = vbox(body, (0, 0, 0, 0), 12)
        head = hbox(None, (0, 0, 0, 0), 10)
        head.addWidget(Picture(data.bargain_picture(), fixed=QSize(40, 40)))
        texts = vbox(None, (0, 0, 0, 0), 2)
        texts.addWidget(Text("循环砍价", "h2"))
        texts.addWidget(Text("找商人 → 砍价 → 关商店", "muted"))
        head.addLayout(texts, 1)
        column.addLayout(head)
        row = hbox(None, (0, 8, 0, 0), 10)
        row.addWidget(Text("次数", "h3"))
        row.addStretch(1)
        spin = SpinBox()
        spin.setRange(1, MAX_LOOPS)
        spin.setValue(loop_count(task.config.get(LOOP_COUNT_KEY, DEFAULT_LOOPS)))
        row.addWidget(spin)
        column.addLayout(row)
        # Leo 2026-10-11: show the 停止 key as set in 设置, not changed here.
        column.addWidget(Text(self._stop_key_hint(), "sub", wrap=True))
        # Leo 2026-10-11: standing at the merchant skips 主页 and the
        # cartridge; the auto stop is not proven live yet, say so.
        column.addWidget(
            self._tip(
                (
                    "最好先站在第一章商人（无聊收集狂大叔）面前再开始，会直接砍价",
                    "砍价技能到传说或出现升星提示时会自动停下，但这点还没实测过，建议自己留意，以免浪费资源",
                )
            )
        )
        box.widget.setMinimumWidth(380)
        # The tool's own violet buttons, not the Fluent default teal.
        box.yesButton.hide()
        box.cancelButton.hide()
        start = Button("开始砍价", "primary", "play", on_click=box.accept)
        cancel = Button("取消", "secondary", on_click=box.reject)
        for button in (start, cancel):
            button.setStyleSheet(theme.style_sheet())
            box.buttonLayout.addWidget(button, 1)
        return box, spin

    @staticmethod
    def _stop_key_hint() -> str:
        from src.ui.shell import hotkeys

        stop = hotkeys.keys()[hotkeys.STOP]
        if stop == hotkeys.NONE:  # Leo 2026-10-20: the stop key can be off
            return t("停止键已关闭，可在首页按「停止」")
        return tf("按 {stop} 可随时停止，按键在设置里改", stop=stop)

    def keep_page_on_start(self) -> bool:
        """A start from here that stays on this page (循环砍价)."""
        return bool(getattr(self, "_stay_on_start", False))

    def _stop_bargain(self) -> None:
        from src.ui.shell import clone_flow

        self._bargain_stopping = True
        self._show_bargain_stopping(True)
        self.bargain_stop.repaint()
        if not data.busy() and clone_flow.remote_task() is not None:
            clone_flow.remote_control("stop")
        else:
            actions.stop(data.current_task())
        self.refresh()

    def _show_bargain_stopping(self, on: bool) -> None:
        self.bargain_stop.set_label("正在停止…" if on else "停止")
        self.bargain_stop.set_icon_name("loader-circle" if on else "square")
        self.bargain_stop.setEnabled(not on)

    def _refresh_bargain(self) -> None:
        from src.ui.shell import clone_flow

        task = self._bargain_task()
        current = data.current_task()
        if current is None:
            # A run handed to the 桌面分身 is shown here too.
            remote = clone_flow.remote_task()
            current = remote if getattr(remote, "name", "") == BARGAIN_TASK else None
        running = task is not None and (current is task or getattr(current, "remote", False))
        if running:
            done = str((getattr(current, "info", None) or {}).get("已砍价次数") or "")
            self.bargain_state.set_text(
                tf("砍价执行中 {done}", done=done) if done else "砍价执行中"
            )
            stopping = current is task and not getattr(task, "enabled", True)
            self._show_bargain_stopping(stopping or getattr(self, "_bargain_stopping", False))
        else:
            self._bargain_stopping = False
            self._show_bargain_stopping(False)
        self.bargain_running.setVisible(running)
        if running:
            self.bargain_key.set_text(self._stop_key_hint())
        self.bargain_key.setVisible(running)
        self.bargain_button.setVisible(not running)
        self.bargain_button.setEnabled(task is not None and actions.can_start())

    # ---------------------------------------------------------------- calendar

    def _build_calendar(self) -> None:
        card = Card()
        column = vbox(card, (18, 16, 18, 18), 12)
        head = hbox(None, (0, 0, 0, 0), 10)
        head.addWidget(Text("出售日历", "h2"))
        self.cal_sub = Text("", "muted")
        head.addWidget(self.cal_sub, 1)
        column.addLayout(head)
        body = hbox(None, (0, 0, 0, 0), 18)
        self.cal_box = QWidget()
        from PySide6.QtWidgets import QGridLayout

        self.cal_grid = QGridLayout(self.cal_box)
        self.cal_grid.setContentsMargins(0, 0, 0, 0)
        self.cal_grid.setSpacing(5)
        body.addWidget(self.cal_box, 3)
        self.day_panel = QWidget()
        self.day_layout = vbox(self.day_panel, (0, 0, 0, 0), 8)
        self.day_panel.setMinimumWidth(240)
        self.day_panel.setMaximumWidth(320)
        body.addWidget(self.day_panel, 2, Qt.AlignTop)
        column.addLayout(body)
        self.body.addWidget(card)
        self._cells: dict[int, DayCell] = {}
        self._cal_month: tuple[int, int] | None = None
        self._panel_key = None
        self._panel_checks: dict[str, CheckBox] = {}

    def _fill_calendar(self, today: date, days: dict) -> None:
        month = (today.year, today.month)
        if month == self._cal_month:
            return
        self._cal_month = month
        clear_layout(self.cal_grid)
        self._cells = {}
        for column, name in enumerate("一二三四五六日"):
            label = Text(name, "muted")
            label.setAlignment(Qt.AlignCenter)
            self.cal_grid.addWidget(label, 0, column)
        first_weekday, count = month_calendar.monthrange(today.year, today.month)
        for day in range(1, count + 1):
            position = first_weekday + day - 1
            items = [entry.item for entry in days.get(day, ())]
            items = list(dict.fromkeys(items))
            cell = DayCell(day, items)
            cell.clicked.connect(self._pick_day)
            self.cal_grid.addWidget(cell, 1 + position // 7, position % 7)
            self._cells[day] = cell
        self.cal_sub.set_text(tf(
                "{month} 月 · {time} 更新 · 点一天看要卖什么",
                month=today.month,
                time=data.sale_refresh_clock(),
            ))

    def _pick_day(self, day: int) -> None:
        self._picked_day = day
        self._panel_key = None
        self.refresh()

    def _fill_day_panel(self, today: date, day: int, entries, task) -> None:
        from src.tasks.map_trade.sale_days import day_items, sale_day_key

        key = sale_day_key(day)
        if task is None:
            selected = set()
        elif key in task.config:
            selected = set(task.config.get(key) or [])
        else:
            selected = set(day_items(entries))
        panel_key = (day, tuple(sorted(selected)), tuple(entry.item for entry in entries))
        if panel_key == self._panel_key:
            return
        same_day = self._panel_key is not None and (panel_key[0], panel_key[2]) == (
            self._panel_key[0],
            self._panel_key[2],
        )
        self._panel_key = panel_key
        if same_day:
            # Only the ticks changed (a click here): keep the boxes so the
            # one just clicked can play its tick instead of being rebuilt.
            for item, check in self._panel_checks.items():
                check.set_checked_quietly(item in selected)
            return
        self._panel_checks = {}
        clear_layout(self.day_layout)
        head = hbox(None, (0, 0, 0, 0), 8)
        head.addWidget(Text(tf("{month}月{day}日", month=today.month, day=day), "h3"))
        is_today = day == today.day
        head.addWidget(
            Text(tf("今天 · {n} 件" if is_today else "{n} 件", n=len(entries)), "muted"), 1
        )
        self.day_layout.addLayout(head)
        if not entries:
            self.day_layout.addWidget(Text("这天没有要卖的", "muted"))
            return
        for entry in entries:
            row = hbox(None, (0, 2, 0, 2), 10)
            row.addWidget(ItemIcon(entry.item, 34))
            row.addWidget(Text(entry.item, "h3", elide=True), 1)
            if entry.reserve:
                row.addWidget(Text(tf("留 {n}", n=f"{entry.reserve:,}"), "pill"))
            check = CheckBox("", entry.item in selected)
            check.toggled.connect(lambda on, d=day, item=entry.item: self._tick_item(d, item, on))
            self._panel_checks[entry.item] = check
            row.addWidget(check)
            self.day_layout.addLayout(row)

    def _tick_item(self, day: int, item: str, on: bool) -> None:
        from src.tasks.map_trade.sale_days import day_items, sale_day_key

        task = self.task()
        entries = data.sale_days().get(day, ())
        if task is None or not entries:
            return
        options = day_items(entries)
        key = sale_day_key(day)
        selected = set(task.config.get(key) or []) if key in task.config else set(options)
        if on:
            selected.add(item)
        else:
            selected.discard(item)
        task.config[key] = [option for option in options if option in selected]
        self.refresh()

    # ---------------------------------------------------------------- more

    def _toggle_more(self) -> None:
        if not self._more_built:
            column = vbox(self.more, (20, 16, 20, 16), 12)
            column.addWidget(Text("其他设定", "h3"))
            batch = data.task_by_name(data.DAILY_BATCH)
            if batch is not None and BATCH_KEY in batch.config:
                column.addWidget(
                    ConfigForm(batch, keys=[BATCH_KEY], labels={BATCH_KEY: "加入一键完成日常"})
                )
            task = self.task()
            if task is not None and "启用" in task.config:
                column.addWidget(ConfigForm(task, keys=["启用"], labels={"启用": "单独跑时启用"}))
            self._more_built = True
        self.more.setVisible(not self.more.isVisible())

    def _start(self) -> None:
        actions.start(self.task(), self.window())
        self.refresh()

    # ---------------------------------------------------------------- refresh

    def refresh(self) -> None:
        self._fill_hints()
        task = self.task()
        if task is None:
            self.start_button.setEnabled(False)
            return
        config = task.config
        current = data.current_task()
        phases = data.trade_phases_done()
        running = current is task
        if running:
            set_pill(self.status, "正在跑", "run")
        elif data.done_today(TASK_NAME):
            set_pill(self.status, "今天跑完了", "ok")
        elif any(phases.values()):
            set_pill(self.status, "今天跑了一部分", "warn")
        else:
            set_pill(self.status, "今天还没跑")
        self.start_button.setEnabled(actions.can_start())
        self._refresh_bargain()

        for card, phase in (
            (self.buy_card, "买"),
            (self.cook_card, "制作料理"),
            (self.sell_card, "卖"),
        ):
            card.toggle.set_checked_quietly(bool(config.get(card.key, True)))
            card.done.set_text("今天已做" if phases.get(phase) else "")
            card.done.setVisible(bool(phases.get(phase)))

        picked = [name for name in self.dishes if name in set(config.get("料理清单") or [])]
        order = [name for name in picked if name != LAST_DISH]
        for name, tile in self.dishes.items():
            if name == LAST_DISH:
                tile.set_state(name in picked, t("末"))
            else:
                tile.set_state(name in picked, str(order.index(name) + 1) if name in order else "")
        five = set(config.get("5星料理") or [])
        for name, tile in self.five.items():
            tile.set_state(name in five, "")
        cooking_on = bool(config.get("制作料理", True))
        self.dish_box.setEnabled(cooking_on)

        today = data.sale_date()
        days = data.sale_days()
        self._fill_calendar(today, days)
        from src.tasks.map_trade.sale_days import day_items, sale_day_key

        for day, cell in self._cells.items():
            entries = days.get(day, ())
            key = sale_day_key(day)
            unticked = 0
            if entries and key in config:
                unticked = len(set(day_items(entries)) - set(config.get(key) or []))
            cell.set_state(day == today.day, day == (self._picked_day or today.day), unticked)

        entries = days.get(today.day, ())
        key = sale_day_key(today.day)
        selling = [
            entry.item
            for entry in entries
            if key not in config or entry.item in set(config.get(key) or [])
        ]
        items_key = tuple(selling)
        if items_key != self._today_items_key:
            self._today_items_key = items_key
            clear_layout(self.today_items)
            for name in selling[:6]:
                self.today_items.addWidget(ItemIcon(name, 40))
            if len(selling) > 6:
                self.today_items.addWidget(Text(f"+{len(selling) - 6}", "muted"))
            self.today_items.addStretch(1)
        self.sell_title.set_text(
            tf("今天卖 {n} 件", n=len(selling)) if selling else "今天没有要卖的"
        )
        self._fill_day_panel(
            today, self._picked_day or today.day, days.get(self._picked_day or today.day, ()), task
        )
