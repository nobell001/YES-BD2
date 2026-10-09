"""跑的时候游戏静音：每秒看一次有没有在跑，跟着把游戏静音或恢复（Leo 2026-10-09）.

The setting itself and the volume mixer live in ``src.utils.game_sound``.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.ui.shell import data
from src.ui.shell.safe import guarded
from src.utils import game_sound

CHECK_MS = 1000


def start(parent) -> QTimer:
    game_sound.restore_left_over()
    timer = QTimer(parent)
    timer.timeout.connect(guarded("game sound", tick))
    timer.start(CHECK_MS)
    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(game_sound.restore)
    return timer


def tick() -> None:
    task = data.current_task()
    onetime = data.onetime_tasks()
    # A run waiting for the login (the tool opened the game, or reopened it
    # after 闪退) is running too: the login screen's music stays off.
    running = (task is not None and task in onetime) or any(
        getattr(each, "_start_after_login", False) for each in onetime
    )
    manager = getattr(data.og(), "device_manager", None)
    window = getattr(manager, "hwnd_window", None)
    hwnd = int(getattr(window, "hwnd", 0) or 0) if window is not None else 0
    game_sound.follow(running, game_sound.pid_of(hwnd))
    if window is not None and hasattr(window, "to_handle_mute"):
        # ok-script's own 「后台静音」 would unmute a game in front every 2 s.
        window.to_handle_mute = not game_sound.holding()
