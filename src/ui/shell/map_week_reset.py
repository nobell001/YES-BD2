"""跑图's 「重新开始本周」 (a player 2026-11-16: 「跑图这周没重置，所有图都是
保留上周已跑状态。能不能出个按钮手动重置」).

A small window over the tool: what is forgotten, what stays, and 取消 /
重新开始.  Only 重新开始 touches the records (a copy of the file is kept).
"""

from __future__ import annotations

from ok import Logger
from PySide6.QtWidgets import QWidget

from src.ui.shell.floating import Floating, Panel
from src.ui.shell.run_confirm import HeroIcon
from src.ui.shell.widgets import Alert, Button, Text, hbox, t, vbox

logger = Logger.get_logger(__name__)

PANEL_WIDTH = 440
TITLE = "重新开始本周跑图？"
BODY = "清掉这周的卡带记录，下次跑图会从第一张卡带重新看。"
KEPT = (
    "今天的技能次数和跑商记录不会动。",
    "游戏里卡带图示已经是完成的，还是会记成完成，不会重跑。",
)
CONFIRM = "重新开始"
DONE = "本周跑图记录已清掉，下次跑图从第一张卡带开始"
# The file is held open elsewhere (antivirus, OneDrive, the 桌面分身's tool).
FAILED = "跑图记录现在存不进去（文件可能被占用），没有清掉，请稍后再按一次"


class WeekResetDialog(Floating):
    PANEL_WIDTH = PANEL_WIDTH - 2 * Panel.SHADOW
    MARGIN = 64
    PAD = (24, 20)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.column.addWidget(HeroIcon("rotate-ccw"))
        self.column.addWidget(Text(TITLE, "h1"))
        self.column.addWidget(Text(BODY, "sub", wrap=True))
        note = Alert("info")
        note_box = vbox(note, (14, 10, 14, 10), 2)
        for line in KEPT:
            note_box.addWidget(Text(line, "sub", wrap=True))
        self.column.addWidget(note)
        buttons = hbox(None, (0, 4, 0, 0), 10)
        buttons.addStretch(1)
        buttons.addWidget(Button("取消", "secondary", parent=self.panel, on_click=self.reject))
        buttons.addWidget(
            Button(CONFIRM, "primary", "rotate-ccw", parent=self.panel, on_click=self.accept)
        )
        self.column.addLayout(buttons)


def restart_week() -> bool:
    """Forget this week's 跑图 cards; False when the file could not be written."""
    from src.tasks.map_trade.progress import ProgressFileError, ProgressStore

    try:
        ProgressStore().restart_collection_week()
    except (ProgressFileError, OSError) as exc:
        logger.error(f"restart map week failed: {exc}")
        return False
    return True


def ask(window: QWidget | None) -> bool | None:
    """Ask, and restart the week on 重新开始.  None when the player cancelled,
    else whether the records were cleared; either answer is said on top."""
    if not WeekResetDialog(window).exec():
        return None
    done = restart_week()
    _say(window, DONE if done else FAILED, done)
    return done


def _say(window: QWidget | None, text: str, ok: bool) -> None:
    try:
        from qfluentwidgets import InfoBar, InfoBarPosition

        show = InfoBar.success if ok else InfoBar.error
        show("", t(text), parent=window, position=InfoBarPosition.TOP, duration=2400)
    except Exception:
        pass
