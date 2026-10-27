"""镜中之战's 倍数 and 场数 as two steppers (Leo 2026-10-14).

Only the look changes: the saved settings stay 竞技场战斗倍数 (int 1~40) and
战斗场数 (drop_down "MAX"/"1".."40"), so the run reads exactly what it read
before.  倍数 × 场数 never goes over the 40 free cocktails a day: 场数 can only
go up to 40 ÷ 倍数, and a bigger 倍数 lowers 场数.  The game's 仅使用免费 /
自动跳过战斗 switches are not shown (Leo: 鎖住的不要); the run checks 仅使用免费
itself.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAction, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QLineEdit, QWidget
from qfluentwidgets import RoundMenu, isDarkTheme

from src.ui.shell import motion, theme
from src.ui.shell.widgets import Button, Text, hbox, tf

MULTIPLIER_KEY = "竞技场战斗倍数"
COUNT_KEY = "战斗场数"
COUNT_MAX = "MAX"
FREE_COCKTAILS = 40
# The ▾ list of 倍数: the ones that use all 40 cocktails with whole 场数.
MULTIPLIER_CHOICES = [1, 2, 4, 5, 8, 10, 20, 40]


def max_count(multiplier: int) -> int:
    return max(1, FREE_COCKTAILS // max(1, multiplier))


class Stepper(QFrame):
    """[ − | value ▾ | + ] on one pill.  The number can be typed, picked from
    the ▾ list or stepped; − and + dip when pressed and repeat when held, and
    the pill's edge glows violet for a moment when the value changes."""

    picked = Signal(int)

    def __init__(self, unit: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stepper")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._value = 1
        self._choices: list[int] = []
        self._glow = motion.Tween(self, self.update, 600, 0.0)
        row = hbox(self, (3, 3, 3, 3), 0)
        self.minus = self._button("−", lambda: self.picked.emit(self._value - 1))
        self.edit = QLineEdit(self)
        self.edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.edit.setValidator(QIntValidator(0, 99, self.edit))
        self.edit.setFixedWidth(30)
        self.edit.setFocusPolicy(Qt.ClickFocus)
        self.edit.editingFinished.connect(self._typed)
        self.unit = Text(unit, "h3")
        self.drop = self._button("", self._open_menu)
        self.drop.set_icon_name("chevron-down")
        self.drop.setFixedWidth(22)
        self.plus = self._button("+", lambda: self.picked.emit(self._value + 1))
        row.addWidget(self.minus)
        row.addSpacing(4)
        row.addWidget(self.edit)
        row.addSpacing(2)
        row.addWidget(self.unit)
        row.addWidget(self.drop)
        row.addWidget(self.plus)
        self._restyle()
        theme.on_theme_changed(self, self._restyle)

    def _button(self, label: str, action) -> Button:
        button = Button(label, "flat", on_click=action)
        button.setProperty("stepper", True)
        button.setFixedWidth(30)
        if label:
            button.setAutoRepeat(True)  # hold to keep stepping
        return button

    def _restyle(self) -> None:
        tk = theme.tokens()
        dark = isDarkTheme()
        self.setStyleSheet(
            # 淡紫: a white pill with an edge, else it melts into the page
            # (Leo 2026-10-14: 紫色的沒有外框); 深色 keeps the plain dark pill.
            f"QFrame#stepper {{ background: {tk['inset'] if dark else tk['card']};"
            f" border: {'none' if dark else '1px solid ' + tk['line2']}; border-radius: 16px; }}"
            f"QFrame#stepper QPushButton {{ background: transparent; border: none;"
            f" border-radius: 13px; color: {tk['ink']}; font-size: 16px;"
            f" padding: 0px;"
            f" min-height: 26px; max-height: 26px; }}"
            f"QFrame#stepper QPushButton:hover {{ color: {tk['accent']};"
            f" background: {tk['card'] if dark else tk['accent_soft']}; }}"
            f"QFrame#stepper QPushButton:disabled {{ color: {theme.rgba('ink', 0.25)}; }}"
            f"QFrame#stepper QLineEdit {{ background: transparent; border: none; padding: 0px;"
            f" color: {tk['ink']}; font-size: 14px;"
            f" selection-background-color: {tk['accent']}; selection-color: {tk['on_accent']}; }}"
            f"QFrame#stepper QLineEdit:focus {{ border-bottom: 2px solid {tk['accent']}; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        glow = float(self._glow.value)
        if glow <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colour = theme.color("accent")
        colour.setAlphaF(glow)
        painter.setPen(QPen(colour, 1.5))
        painter.setBrush(Qt.NoBrush)
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

    def _typed(self) -> None:
        text = self.edit.text().strip()
        if text.isdigit():
            self.picked.emit(int(text))
        # Too big or not a number: show what was kept (the limit, or the old value).
        self.edit.setText(str(self._value))

    def _open_menu(self) -> None:
        menu = RoundMenu(parent=self)
        menu.setMaxVisibleItems(10)  # 场数 can list up to 40; scroll past 10
        for choice in self._choices:
            action = QAction(f"{choice} {self.unit.text()}", menu)
            action.triggered.connect(lambda _c=False, v=choice: self.picked.emit(v))
            menu.addAction(action)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def set_state(self, value: int, choices: list[int], can_down: bool, can_up: bool) -> None:
        changed = value != self._value
        self._value = value
        self._choices = choices
        if not self.edit.hasFocus() or changed:
            self.edit.setText(str(value))
        self.minus.setEnabled(can_down)
        self.plus.setEnabled(can_up)
        self.drop.setEnabled(len(choices) > 1)
        if changed:
            self._glow.go(1.0, animate=False)
            self._glow.go(0.0)


class PvpPanel(QWidget):
    def __init__(self, task, parent=None, on_change: Callable[[str], None] | None = None):
        super().__init__(parent)
        self.task = task
        self._on_change = on_change
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)

        self.multiplier = Stepper("倍", self)
        self.multiplier.picked.connect(self._set_multiplier)
        grid.addWidget(Text("战斗倍数", "sub"), 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.multiplier, 0, 1, Qt.AlignRight | Qt.AlignVCenter)

        count_box = QWidget(self)
        count_row = hbox(count_box, (0, 0, 0, 0), 8)
        self.max_button = Button("MAX", "flat", parent=count_box)  # hover fade + press dip
        self.max_button.setCheckable(True)
        self.max_button.clicked.connect(self._toggle_max)
        self.count = Stepper("场", count_box)
        self.count.picked.connect(self._set_count)
        count_row.addWidget(self.max_button)
        count_row.addWidget(self.count)
        grid.addWidget(Text("战斗场数", "sub"), 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(count_box, 1, 1, Qt.AlignRight | Qt.AlignVCenter)

        # How many of the day's free cocktails this run uses (Leo: no bar, 狀態條不好看).
        self.cups_text = Text("", "h3")
        grid.addWidget(Text("免费鸡尾酒", "sub"), 2, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.cups_text, 2, 1, Qt.AlignRight | Qt.AlignVCenter)
        self._restyle()
        theme.on_theme_changed(self, self._restyle)
        self.sync()

    def _restyle(self) -> None:
        tk = theme.tokens()
        dark = isDarkTheme()
        self.max_button.setStyleSheet(
            f"QPushButton {{ min-height: 32px; max-height: 32px; border-radius: 16px;"
            f" padding: 0px 14px; font-size: 13px;"
            f" background: {tk['inset'] if dark else tk['card']};"
            f" color: {tk['ink'] if dark else tk['accent']};"
            f" border: {'none' if dark else '1px solid ' + tk['line2']}; }}"
            f"QPushButton:hover {{ background: {tk['card'] if dark else tk['accent_soft']}; }}"
            f"QPushButton:checked {{ background: {tk['accent']}; color: {tk['on_accent']};"
            f" border-color: {tk['accent']}; }}"
        )

    # ------------------------------------------------------------ values

    def _multiplier(self) -> int:
        try:
            value = int(self.task.config.get(MULTIPLIER_KEY) or FREE_COCKTAILS)
        except (TypeError, ValueError):
            value = FREE_COCKTAILS
        return min(FREE_COCKTAILS, max(1, value))

    def _is_max(self) -> bool:
        return str(self.task.config.get(COUNT_KEY)) == COUNT_MAX

    def _count(self) -> int:
        top = max_count(self._multiplier())
        if self._is_max():
            return top
        try:
            value = int(self.task.config.get(COUNT_KEY) or 1)
        except (TypeError, ValueError):
            value = 1
        return min(top, max(1, value))

    def _write(self, key: str, value) -> None:
        if self.task.config.get(key) == value:
            return
        self.task.config[key] = value
        if self._on_change is not None:
            self._on_change(key)

    def _set_multiplier(self, value: int) -> None:
        multiplier = min(FREE_COCKTAILS, max(1, int(value)))
        self._write(MULTIPLIER_KEY, multiplier)
        if not self._is_max():
            # 倍数 × 场数 ≤ 40: a bigger 倍数 lowers 场数 (MAX follows by itself).
            self._write(COUNT_KEY, str(min(self._count(), max_count(multiplier))))
        self.sync()

    def _set_count(self, value: int) -> None:
        top = max_count(self._multiplier())
        self._write(COUNT_KEY, str(min(top, max(1, int(value)))))
        self.sync()

    def _toggle_max(self, on: bool) -> None:
        self._write(COUNT_KEY, COUNT_MAX if on else str(self._count()))
        self.sync()

    # ------------------------------------------------------------ state

    def sync(self) -> None:
        multiplier = self._multiplier()
        count = self._count()
        top = max_count(multiplier)
        is_max = self._is_max()
        self.multiplier.set_state(
            multiplier, MULTIPLIER_CHOICES, multiplier > 1, multiplier < FREE_COCKTAILS
        )
        self.count.set_state(
            count, list(range(1, top + 1)), not is_max and count > 1, not is_max and count < top
        )
        self.max_button.setChecked(is_max)
        used = multiplier * count
        self.cups_text.set_text(tf("{used} / {free} 杯", used=used, free=FREE_COCKTAILS))
