"""镜中之战's 倍数 and 场数 as two sliders with the number shown (Leo
2026-10-14 steppers; 2026-11-09 「數字類可以用 SLIDER 加顯示數字」).

Only the look changes: the saved settings stay 竞技场战斗倍数 (int 1~40) and
战斗场数 (drop_down "MAX"/"1".."40"), so the run reads exactly what it read
before.  倍数 × 场数 never goes over the 40 free cocktails a day: 场数 can only
go up to 40 ÷ 倍数, and a bigger 倍数 lowers 场数.  The game's 仅使用免费 /
自动跳过战斗 switches are not shown (Leo: 鎖住的不要); the run checks 仅使用免费
itself.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget

from src.ui.shell import theme
from src.ui.shell.widgets import Button, Slider, Text, tf

MULTIPLIER_KEY = "竞技场战斗倍数"
COUNT_KEY = "战斗场数"
COUNT_MAX = "MAX"
FREE_COCKTAILS = 40
# The 倍数 slider's stops: the ones that use all 40 cocktails with whole 场数
# (any other 1~40 can still be typed in the number box).
MULTIPLIER_CHOICES = [1, 2, 4, 5, 8, 10, 20, 40]


def max_count(multiplier: int) -> int:
    return max(1, FREE_COCKTAILS // max(1, multiplier))


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

        # The two bars line up: label | slider + number | MAX (场数 only).
        self.multiplier = Slider(self)
        self.multiplier.setRange(1, FREE_COCKTAILS)
        self.multiplier.setSuffix("倍")
        self.multiplier.setStops(MULTIPLIER_CHOICES)
        self.multiplier.valueChanged.connect(self._set_multiplier)
        grid.addWidget(Text("战斗倍数", "sub"), 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.multiplier, 0, 1, Qt.AlignVCenter)

        self.count = Slider(self)
        self.count.setSuffix("场")
        self.count.valueChanged.connect(self._set_count)
        self.max_button = Button("MAX", "flat", parent=self)  # hover fade + press dip
        self.max_button.setCheckable(True)
        self.max_button.clicked.connect(self._toggle_max)
        grid.addWidget(Text("战斗场数", "sub"), 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.count, 1, 1, Qt.AlignVCenter)
        grid.addWidget(self.max_button, 1, 2, Qt.AlignVCenter)

        Slider.same_box_width((self.multiplier, self.count))
        # How many of the day's free cocktails this run uses (Leo: no bar, 狀態條不好看).
        self.cups_text = Text("", "h3")
        grid.addWidget(Text("免费鸡尾酒", "sub"), 2, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.cups_text, 2, 1, 1, 2, Qt.AlignRight | Qt.AlignVCenter)
        self._restyle()
        theme.on_theme_changed(self, self._restyle)
        self.sync()

    def _restyle(self) -> None:
        # The shared design language: a 32 px pill on the ``fill`` token, the
        # primary colour once on.
        tk = theme.tokens()
        height = theme.size("control_md")
        self.max_button.setStyleSheet(
            f"QPushButton {{ min-height: {height}px; max-height: {height}px;"
            f" border-radius: {height // 2}px; padding: 0px 14px;"
            f" font-size: {theme.size('text_md')}px;"
            f" background: {tk['fill']}; color: {tk['ink']}; border: none; }}"
            f"QPushButton:hover {{ background: {tk['fill_hover']}; }}"
            f"QPushButton:checked {{ background: {tk['primary']}; color: {tk['on_primary']}; }}"
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
        for slider, low, high, value in (
            (self.multiplier, 1, FREE_COCKTAILS, multiplier),
            (self.count, 1, top, count),
        ):
            slider.blockSignals(True)
            slider.setRange(low, high)
            slider.setValue(value)
            slider.blockSignals(False)
        # 倍数 40 leaves one 场.  With MAX on the knob sits at the top; moving
        # it picks that number and turns MAX off.
        self.count.setEnabled(top > 1)
        self.max_button.setChecked(is_max)
        used = multiplier * count
        self.cups_text.set_text(tf("{used} / {free} 杯", used=used, free=FREE_COCKTAILS))
