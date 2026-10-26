"""「网络慢时的等待」：打开游戏和登录等多久、重试几次（YES-BD2 #56）。

One row per number (src/utils/wait_settings.py), each with its range and
default under it; 恢复默认 / 取消 / 确定, kept only on 确定.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from qfluentwidgets import SpinBox

from src.ui.shell.floating import Floating, Panel
from src.ui.shell.run_confirm import HeroIcon
from src.ui.shell.widgets import Button, Text, hbox, t, tf, vbox
from src.utils import wait_settings

PANEL_WIDTH = 520
SPIN_WIDTH = 132


class WaitSettingsDialog(Floating):
    PANEL_WIDTH = PANEL_WIDTH - 2 * Panel.SHADOW
    MARGIN = 64
    PAD = (24, 20)

    def __init__(self, values: dict, parent: QWidget | None = None):
        super().__init__(parent)
        column = self.column

        head = hbox(None, (0, 0, 0, 0), 12)
        head.addWidget(HeroIcon("clock", 40), 0, Qt.AlignTop)
        titles = vbox(None, (0, 0, 0, 0), 2)
        titles.addWidget(Text("网络慢时的等待", "h2"))
        titles.addWidget(
            Text(
                "网络或电脑慢、常常等到超时的话调大。默认值已经偏保守，一般不用改。",
                "sub",
                wrap=True,
            )
        )
        head.addLayout(titles, 1)
        column.addLayout(head)

        self.spins: dict[wait_settings.Setting, SpinBox] = {}
        for setting in wait_settings.SETTINGS:
            row = hbox(None, (0, 4, 0, 4), 12)
            texts = vbox(None, (0, 0, 0, 0), 1)
            texts.addWidget(Text(setting.title, "h3"))
            texts.addWidget(
                Text(
                    tf(
                        "{sub}（{low}–{high} {unit}，默认 {default}）",
                        sub=t(setting.sub),
                        low=setting.low,
                        high=setting.high,
                        unit=t(setting.unit),
                        default=setting.default,
                    ),
                    "muted",
                    wrap=True,
                )
            )
            row.addLayout(texts, 1)
            spin = SpinBox()
            spin.setRange(setting.low, setting.high)
            spin.setFixedWidth(SPIN_WIDTH)  # the four boxes line up
            spin.setSingleStep(10 if setting.unit == "秒" else 1)
            spin.setValue(values.get(setting, setting.default))
            row.addWidget(spin, 0, Qt.AlignVCenter)
            column.addLayout(row)
            self.spins[setting] = spin

        buttons = hbox(None, (0, 6, 0, 0), 8)
        buttons.addWidget(Button("恢复默认", "ghost", size="sm", on_click=self._reset))
        buttons.addStretch(1)
        buttons.addWidget(Button("取消", "secondary", on_click=self.reject))
        buttons.addWidget(Button("确定", "primary", on_click=self.accept))
        column.addLayout(buttons)

    def values(self) -> dict:
        return {setting: spin.value() for setting, spin in self.spins.items()}

    def _reset(self) -> None:
        for setting, spin in self.spins.items():
            spin.setValue(setting.default)

    def mouseReleaseEvent(self, event):
        # A click on the dimmed part outside the panel is 取消.
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.reject()
        super().mouseReleaseEvent(event)


def ask(window: QWidget | None) -> bool:
    """Show the numbers; saved on 确定 (True), unchanged on 取消."""
    current = {setting: wait_settings.get(setting) for setting in wait_settings.SETTINGS}
    dialog = WaitSettingsDialog(current, window)
    if not dialog.exec():
        return False
    wait_settings.set_values(dialog.values())
    return True
