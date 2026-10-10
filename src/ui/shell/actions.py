"""Start, pause and stop tasks the way the old task cards do."""

from __future__ import annotations

from collections.abc import Callable

from ok import Logger

from src.ui.shell import data

logger = Logger.get_logger(__name__)

_started: list[Callable[[], None]] = []


def on_started(callback: Callable[[], None]) -> None:
    """Run ``callback`` after a start button here starts or resumes a task."""
    _started.append(callback)


def _notify_started() -> None:
    for callback in list(_started):
        try:
            callback()
        except Exception as exc:
            logger.error("start callback failed", exc)


def can_start() -> bool:
    return not data.busy() and data.executor() is not None


def start(task, window=None, run_mode: str | None = None, by_player: bool | None = None) -> bool:
    """Start ``task``; a batch can be asked to run only what is left.

    ``by_player``: pressed by the player (default: a window was given).
    """
    if task is None:
        logger.info("start pressed but the task was not found")
        _warn(window, "找不到这个任务，请重开工具再试")
        return False
    logger.info(f"start pressed: {getattr(task, 'name', task)} (mode {run_mode or '-'})")
    if task.enabled and task.paused:
        task.unpause()
        bring_game_to_front()
        _notify_started()
        return True
    if data.busy():
        # Leo 2026-10-06: a press that started nothing said nothing.
        running = getattr(data.current_task(), "name", "") or "其他任务"
        logger.info(f"start refused: {running} is running")
        busy = data.tr("「{name}」还在执行，等它结束或先按停止再开始")
        _warn(window, busy.format(name=data.tr(running)))
        return False
    alert = getattr(task, "first_run_alert", None)
    if alert and not task.config.get("_first_run_alert"):
        from qfluentwidgets import Dialog

        dialog = Dialog(data.tr("Alert"), data.tr(alert), window)
        dialog.yesButton.setText(data.tr("Confirm"))
        dialog.cancelButton.setText(data.tr("Cancel"))
        dialog.setContentCopyable(True)
        if not dialog.exec():
            return False
        task.config["_first_run_alert"] = alert
    from src.ui.shell import clone_flow

    if clone_flow.busy_in_clone():
        # The game is on the 桌面分身; starting here would open a second one.
        logger.info("start refused: a run is going in the 桌面分身")
        clone_flow.message(window, "工具正在桌面分身里跑，要在这里跑请先按停止", error=True)
        return False
    if clone_flow.restart_outdated_clone(window, task, run_mode):
        _notify_started()
        return True
    if clone_flow.hand_to_clone(window, task, run_mode):
        _notify_started()
        return True
    if not clone_flow.end_idle_clone(window):
        return False
    if window is not None and task.name in (data.DAILY_BATCH, data.WEEKLY_BATCH):
        if not game_running() and not _ask_to_open_game(window):
            return False
    if hasattr(task, "cancel_resume"):
        # A start by the player, never the run after 闪退 or the title screen.
        task.cancel_resume()
    rearm_login_for_closed_game()
    if run_mode is not None and hasattr(task, "request_run_mode"):
        task.request_run_mode(
            run_mode, by_player=window is not None if by_player is None else by_player
        )
    try:
        data.og().app.start_controller.start(task)
    except Exception as exc:
        logger.error(f"start {task.name} failed", exc)
        _warn(window, data.tr("开始失败：{error}").format(error=exc))
        return False
    bring_game_to_front()
    _notify_started()
    return True


def _warn(window, text: str) -> None:
    if window is None:
        return
    try:
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.warning(
            data.tr("没有开始"),
            data.tr(text),
            parent=window,
            position=InfoBarPosition.TOP,
            duration=6000,
        )
    except Exception as exc:
        logger.error("start warning failed", exc)


def bring_game_to_front() -> bool:
    """Leo 2026-10-06: after pressing start, show the game, not the tool.

    Done right at the click, while the tool still owns the foreground, so
    Windows lets it hand the foreground over.  A game that is not open yet
    comes up in front by itself when the start opens it.
    """
    try:
        import win32con
        import win32gui

        from src.tasks.BaseBD2Task import _set_foreground_attached
        from src.ui.shell.clone_flow import _game_window

        hwnd = _game_window()
        if hwnd is None:
            return False
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        _set_foreground_attached(hwnd)
        return True
    except Exception as exc:  # never let this block a start
        logger.error(f"bring game to front failed: {exc}")
        return False


def game_running() -> bool:
    """BrownDust II runs on this Windows session (not only on a 桌面分身)."""
    from src.utils.game_process import game_running as running

    found = running()
    return True if found is None else found  # cannot tell: start as before


def rearm_login_for_closed_game() -> None:
    """The game is closed, so the start that opens it must log in again.

    The auto-login stays finished after its first login in a tool session;
    with the game closed later, the next start counted it as logged in and
    ran on the title screen (live 4K clone 2026-10-10 14:36, step 57).
    """
    if game_running():
        return
    login = _login_task()
    if login is not None and getattr(login, "_finished", False):
        login._reset_login_state("游戏关着，打开后重新自动登录。")
        logger.info("game closed: auto-login armed again for the next opening")


def _ask_to_open_game(window) -> bool:
    """Leo (2026-10-03 14:37): the game is not open, offer to open it and run.

    Yes: the start below opens the game (as it always does when it is not
    running) and the batch waits for the login, done by auto-login for this
    run only; the saved 自动登录游戏 setting stays as the user left it.
    """
    from qfluentwidgets import MessageBox

    from src.ui.shell import clone_flow

    box = MessageBox(data.tr("游戏还没开"), data.tr("要帮你打开游戏并开始跑吗？"), window)
    box.yesButton.setText(data.tr("打开并开始"))
    box.cancelButton.setText(data.tr("取消"))
    if not box.exec():
        return False
    clone_flow.log_in_this_run()
    return True


def toggle_pause(task) -> None:
    if task is None:
        return
    if task.paused:
        task.unpause()
    else:
        task.pause()


def stop(task) -> None:
    if _cancel_login_wait(task):
        return
    if task is None:
        return
    task.disable()
    task.unpause()


def _cancel_login_wait(task) -> bool:
    """停止 while 一键日常 waits for the login (the tool opened the game, or
    reopened it after 闪退): stop that run.

    Live 2026-10-10: the press stopped 自动登录 instead, whose disable() saves
    the setting off and lets the waiting batch go, so it started on the title
    screen.  Between login checks nothing runs at all and the press did nothing.
    A single task handed to the 桌面分身 waits there instead (finding 43).
    """
    from src.ui.shell import clone_flow

    waiting = [each for each in data.onetime_tasks() if getattr(each, "_start_after_login", False)]
    if not clone_flow.drop_waiting_job() and not waiting:
        return False
    for batch in waiting:
        # The 闪退 resume too, or the next start skips what it had done.
        batch.cancel_resume()
        batch.disable()
    login = _login_task()
    if login is not None and not bool(login.config.get("_enabled", False)):
        # It logged in for this run only; the saved setting stays as it is.
        login._enabled = False
    if task is not None and task is not login:
        task.disable()
        task.unpause()
    logger.info("stop pressed while the run waited for the login: run cancelled")
    return True


def _login_task():
    try:
        from src.tasks.trigger.AutoLoginTask import AutoLoginTask

        return data.executor().get_task_by_class(AutoLoginTask)
    except Exception:
        return None


def open_logs() -> None:
    try:
        from src.ui.log_folder import open_log_folder

        open_log_folder()
    except Exception as exc:
        logger.error(f"open log folder failed: {exc}")


def open_folder(path: str) -> None:
    import os
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - opening the user's own folder
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        logger.error(f"open folder failed: {exc}")
