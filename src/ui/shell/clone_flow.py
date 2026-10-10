"""桌面分身 from the buttons: one press runs a task on the clone desktop.

Leo (2026-10-03, 10:28) found it too many steps to open the tool, then the
tool in the clone, then the game, then leave fullscreen; at 10:37 he asked
for no mode switch, just a separate start button on 首页 that reminds first
and then goes in (前往).  前往 opens the clone, starts the tool there and
hands it that one task; the tool in the clone opens the game itself and runs
it.  The tool outside stays open to show progress, reports and settings
(13:04), but does not start tasks while the clone's tool runs.

The start button is the only trigger: the job is a one-shot file that the
tool in the clone reads, and deletes before starting, only within ten minutes
of the press.  A tool opened any other way never starts anything by itself (Leo
removed every auto-run on opening, 2026-10-03).
"""

from __future__ import annotations

import functools
import json
import time

from ok import Logger
from PySide6.QtCore import QObject, QTimer

from src.ui.shell import data
from src.ui.shell.safe import guarded
from src.ui.shell.widgets import t, tf
from src.utils import clone_desktop

logger = Logger.get_logger(__name__)

# Ten minutes to type the password; a job older than that is dropped.
WAIT_SECONDS = 600


class _Launch(QObject):
    def __init__(self):
        super().__init__()
        self.started_at = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(guarded("clone launch check", self._poll, self.timer.stop))
        self.window = None

    def start(self, window) -> None:
        self.window = window
        self.started_at = time.monotonic()
        self.timer.start(1000)

    def active(self) -> bool:
        return self.timer.isActive()

    def _poll(self) -> None:
        result = clone_desktop.launch_result()
        waited = time.monotonic() - self.started_at
        if result is None:
            if waited > WAIT_SECONDS or (waited > 30 and not clone_desktop.viewer_running()):
                self.timer.stop()
                clone_desktop.clear_job()
            return
        self.timer.stop()
        if result.startswith(("started", "running")):
            # Leo (2026-10-03, 13:04): this tool stays open to show progress,
            # reports and settings while the one in the clone runs.
            message(self.window, "工具已经在分身里开始跑，这里可以看进度和报告")
        else:
            clone_desktop.clear_job()
            reason = result.partition(" ")[2]
            message(
                self.window,
                tf("分身里没能自动打开工具（{reason}），请在分身里自己打开", reason=reason),
                error=True,
            )


_launch: _Launch | None = None


def launching() -> bool:
    return _launch is not None and _launch.active()


def available() -> bool:
    """首页 shows 「在桌面分身跑」 only outside the clone on Windows Pro and up."""
    return clone_desktop.supported() and not clone_desktop.in_clone()


def ready_to_go() -> bool:
    """Set up and signed-in ready: 前往 would go straight into the clone."""
    return (
        not clone_desktop.viewer_removed()
        and clone_desktop.ready()
        and not clone_desktop.hello_only()
    )


def ask_and_start(window, task, run_mode: str | None = None) -> bool:
    """Leo (2026-10-03, 10:37): remind first, then 前往 goes into the clone."""
    from qfluentwidgets import MessageBox

    if task is None or data.busy():
        return False
    # Leo (2026-10-03 14:35): short bullet points.
    intro = "• 纯后台执行：游戏在独立的分身窗口里跑，缩小也照跑\n• 照常用电脑，鼠标键盘不会被抢"
    hello = clone_desktop.hello_only()
    if clone_desktop.viewer_removed():
        steps = tf(
            "分身程序不见了，可能被防毒软件（例如 360、火绒）删掉了：\n"
            "• 在防毒软件把这个文件夹设为信任：{folder}\n"
            "• 再按「第一次设定」重新建立",
            folder=str(clone_desktop.DATA_DIR),
        )
        yes = "第一次设定"
    elif not clone_desktop.ready():
        steps = t((
            "第一次要先设定：\n"
            "• 会跳出 Windows 确认，请按「是」\n"
            "• 设定好后再按一次这个按钮"
        ))
        yes = "第一次设定"
    elif hello:
        # A player turned face recognition off and still got this (2026-10-09):
        # name the real switch, which is not face or PIN.
        steps = t((
            "要先改一个登录设定：\n"
            "• 分身要用帐户密码登录，现在只允许 Windows Hello\n"
            "• 在「登录选项」最下面的「其他设置」，"
            "关掉「仅允许对此设备上的 Microsoft 帐户使用 Windows Hello 登录」\n"
            "• 人脸和 PIN 不用关\n"
            "• 改好后再按一次这个按钮"
        ))
        yes = "打开登录选项"
    else:
        steps = t((
            "按「前往」后：\n"
            "• Windows 确认请按「是」\n"
            "• 第一次要打账户密码（不是 PIN），之后会记住\n"
            "• 游戏和日常自动开始，进度在这里看"
        ))
        yes = "前往"
    # Translated in parts: the catalogs hold each part, not the joined text.
    box = MessageBox(t("在桌面分身跑"), t(intro) + "\n\n" + steps, window)
    box.yesButton.setText(t(yes))
    box.cancelButton.setText(t("取消"))
    if not box.exec():
        return False
    if not clone_desktop.ready():
        clone_desktop.run_setup()
        return False
    if hello:
        clone_desktop.open_sign_in_options()
        return False
    return open_clone(window, task, run_mode)


def busy_in_clone() -> bool:
    """Outside the clone: a run is going, or about to start, in the clone.

    Only a run blocks a start here: the tool left open in the clone after its
    run stopped does not (Leo 2026-10-07, 继续 was refused after he stopped
    the run in the clone); ``end_idle_clone`` closes that clone instead.
    """
    if clone_desktop.in_clone():
        return False
    return (
        launching()
        or remote_task() is not None
        or clone_desktop.job_waiting(WAIT_SECONDS)
    )


def hand_to_clone(window, task, run_mode: str | None = None) -> bool:
    """Outside: the tool is open in the clone and free, so it runs ``task``.

    Leo 2026-10-07: 继续 after a run in the clone stopped should go on there,
    with no question; the game is there anyway.  The tool in the clone takes
    the job within five seconds (``_run_pending_job``).
    """
    if clone_desktop.in_clone() or not clone_desktop.tool_running_in_clone():
        return False
    if clone_outdated():
        return False
    _request_job(window, task, run_mode)
    logger.info(f"clone: handed {task.name} (mode {run_mode or '-'}) to the tool in the clone")
    if window is not None:
        message(window, "交给桌面分身里的工具跑，进度在这里看")
    return True


def end_idle_clone(window) -> bool:
    """Outside: close a clone that runs nothing before a run here; True to go on.

    The game may still be open in the clone, and a start here would open a
    second one, so the clone is closed first, after asking.
    """
    if clone_desktop.in_clone() or not clone_desktop.clone_open():
        return True
    if window is None:
        return False
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import MessageBox

    text = (
        "分身里现在没在跑任务，但分身还开着。\n"
        "要在这里跑，得先关掉分身（分身里的游戏和工具会一起关）。"
    )
    box = MessageBox(t("桌面分身还开着"), t(text), window)
    box.yesButton.setText(t("关掉分身并开始"))
    box.cancelButton.setText(t("取消"))
    if not box.exec():
        return False
    if busy_in_clone():
        message(window, "分身里刚开始跑任务，这里先不开始", error=True)
        return False
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        ended = clone_desktop.end_clone()
    finally:
        QApplication.restoreOverrideCursor()
    if not ended:
        logger.warning("clone: could not close the idle 桌面分身")
        message(window, "没能关掉分身，请在分身窗口按右上角的 X 关掉再开始", error=True)
        return False
    logger.info("clone: closed the idle 桌面分身 for a run on this desktop")
    return True


@functools.lru_cache(maxsize=1)
def own_version() -> str:
    try:
        from src.config import runtime_version

        return str(runtime_version())
    except Exception:
        return ""


def clone_outdated() -> bool:
    """Outside: the tool open in the clone is another version than this one.

    The tool updates itself when it is opened again, while the one already
    open in the clone keeps running the old code from the updated folder
    (2026-10-09 review).  An idle one is closed and opened again before a
    task is handed to it.
    """
    if clone_desktop.in_clone():
        return False
    status = clone_desktop.read_status(FRESH_SECONDS)
    theirs = str((status or {}).get("version") or "")
    if not theirs:
        return False  # a tool from before versions were published
    mine = own_version()
    return bool(mine) and theirs != mine


def _request_job(window, task, run_mode: str | None) -> None:
    """No window is 打开就自动跑 on the desktop: the clone must not take it
    for a press, which skips the wait after a failure (#153)."""
    if window is None:
        clone_desktop.request_job(str(task.name), run_mode, by_player=False)
    else:
        clone_desktop.request_job(str(task.name), run_mode)


def restart_outdated_clone(window, task, run_mode: str | None = None) -> bool:
    """Outside: an idle clone with an older tool is closed and opened again for ``task``."""
    if task is None or not clone_outdated() or busy_in_clone():
        return False
    return open_clone(window, task, run_mode)


def _end_outdated_clone(window) -> bool:
    logger.info("clone: the tool in the 桌面分身 is an older version, closing it")
    if clone_desktop.end_clone():
        return True
    message(window, "没能关掉分身，请在分身窗口按右上角的 X 关掉再开始", error=True)
    return False


def open_clone(window, task=None, run_mode: str | None = None) -> bool:
    """Open the clone and start the tool in it; with ``task``, it runs that task."""
    global _launch
    if not clone_desktop.ready():
        message(window, "桌面分身还没设定好，请先到「设置」按「第一次设定」", error=True)
        return False
    if clone_outdated() and not busy_in_clone() and not _end_outdated_clone(window):
        return False
    if (
        task is not None
        and clone_desktop.viewer_running()
        and hand_to_clone(window, task, run_mode)
    ):
        # Already open with the tool in it: opening the viewer again only
        # showed 「桌面分身已經開著了」 (Leo 2026-10-07).
        return True
    if task is not None:
        _request_job(window, task, run_mode)
    else:
        clone_desktop.clear_job()
    if not clone_desktop.open_viewer():
        clone_desktop.clear_job()
        if clone_desktop.open_failure.get("why") == "declined":
            message(window, "没有打开分身（Windows 的确认按了「否」）", error=True)
        else:
            message(
                window,
                tf(
                    "分身程序打不开，可能被防毒软件挡住了：请把 {folder} 设为信任，再到「设置」按「第一次设定」",
                    folder=str(clone_desktop.DATA_DIR),
                ),
                error=True,
            )
        return False
    if _launch is None:
        _launch = _Launch()
    _launch.start(window)
    return True


_job_timer: QTimer | None = None


def run_pending_job_soon() -> None:
    """In the clone, watch for a task a start button outside hands over."""
    global _job_timer, _startup_timer, _publish_timer, _live_timer
    if not clone_desktop.in_clone() or _job_timer is not None:
        return
    # Also covers a tool that was already open in the clone when the button was pressed.
    _job_timer = QTimer()
    _job_timer.timeout.connect(guarded("clone job check", _run_pending_job))
    _job_timer.start(5000)
    # Nothing is ever looked at or operated here: the tool outside shows and
    # controls the run (Leo, 2026-10-03 14:29: the window showed in the clone
    # when it was opened without a job).  Twice, for a slow first paint.
    QTimer.singleShot(1500, guarded("clone minimise", _get_out_of_the_way))
    QTimer.singleShot(5000, guarded("clone minimise", _get_out_of_the_way))
    # The tool outside shows this run and sends pause/stop (Leo, 2026-10-03 13:17).
    _publish_timer = QTimer()
    _publish_timer.timeout.connect(guarded("clone publish", _publish))
    _publish_timer.start(1000)
    _live_timer = QTimer()
    _live_timer.timeout.connect(guarded("clone live picture", _publish_live))
    _live_timer.start(LIVE_INTERVAL_MS)
    # Windows starts the user's startup programs (browser, Steam...) in the
    # clone too; close those there for the first few minutes (Leo, 2026-10-03).
    # Five minutes: live 2026-10-04 SoundSwitch started 125 s after sign-in.
    _startup_sweeps["left"] = 60
    _startup_timer = QTimer()
    _startup_timer.timeout.connect(guarded("clone startup sweep", _close_startup_programs))
    _startup_timer.start(5000)
    guarded("clone startup sweep", _close_startup_programs)()


_startup_timer: QTimer | None = None
_startup_sweeps = {"left": 0}


def _close_startup_programs() -> None:
    _startup_sweeps["left"] -= 1
    if _startup_sweeps["left"] <= 0 and _startup_timer is not None:
        _startup_timer.stop()
    closed = clone_desktop.close_startup_programs()
    if closed:
        logger.info(f"clone: closed startup programs {closed}")


_waiting_job: dict = {}
LOGIN_WAIT_SECONDS = 600
# A started job whose game never came up (live 2026-10-10 02:19: the game
# closed itself in the clone right after opening; the start timed out and the
# clone sat there with nothing running).  Past ok's start timeout (120 s) with
# no game and nothing run, the start is tried again, at most this many times.
_started_job: dict = {}
START_CHECK_SECONDS = 150
START_RETRIES = 2


# 停止 while ok's start_controller is still opening the game for a started
# job: it enables the task once the game is up, after the press (live 4K
# 2026-10-10: stopped 13:43:18, 领取常客圣石 started 13:43:42).  That task is
# stopped as soon as it shows up enabled, for as long as a start can take.
_cancelled_start: dict = {}


def drop_waiting_job() -> bool:
    """停止: forget the task waiting here for the login, and the start that
    would be tried again; True when a task was waiting."""
    waited = bool(_waiting_job)
    _waiting_job.clear()
    _started_job.clear()
    return waited


def _login_pending() -> bool:
    try:
        from src.tasks.trigger.AutoLoginTask import AutoLoginTask

        login = data.executor().get_task_by_class(AutoLoginTask)
    except Exception:
        return False
    if login is None or not getattr(login, "_enabled", False):
        return False
    return not getattr(login, "_finished", False)


def _run_pending_job() -> None:
    from src.ui.shell import actions

    if _check_started_job():
        return
    if data.busy():
        return
    if _waiting_job:
        task, run_mode = _waiting_job["task"], _waiting_job["run_mode"]
        by_player = _waiting_job.get("by_player", True)
        waiting = _login_pending() or not actions.game_running()
        if waiting and time.time() < _waiting_job["until"]:
            return
        _waiting_job.clear()
    else:
        if not clone_desktop.JOB_FILE.exists():
            return
        job = clone_desktop.take_job(WAIT_SECONDS)
        if job is None:
            return
        task = data.task_by_name(job.get("task", ""))
        if task is None:
            logger.warning(f"clone job: no task named {job.get('task')!r}")
            return
        run_mode = job.get("run_mode")
        by_player = job.get("by_player", True) is not False
        _reload_settings()
        log_in_this_run()
        actions.rearm_login_for_closed_game()
        # A batch waits for the login itself; a single task would start on the
        # title screen (live 2026-10-04: 跑图路线测试 failed 进入卡带失败).
        single = task.name not in (data.DAILY_BATCH, data.WEEKLY_BATCH)
        opening = single and not actions.game_running()
        if opening:
            # Nothing opens the game before the task starts, so the login
            # waited its full ten minutes and the task then started on the
            # title screen (live 4K 2026-10-09).  Open the game now; the
            # auto-login runs once it is up.  The task waits here, not in
            # ok's start, so 停止 meanwhile cancels it (finding 43).
            logger.info(f"clone job: opening the game before {task.name}")
            _open_game_only()
        if single and (opening or _login_pending()):
            _waiting_job.update(
                task=task,
                run_mode=run_mode,
                by_player=by_player,
                until=time.time() + LOGIN_WAIT_SECONDS,
            )
            logger.info(f"clone job: {task.name} waits for the game and the auto-login")
            return
    logger.info(f"clone job: starting {task.name}")
    _get_out_of_the_way()
    _cancelled_start.clear()
    _started_job.clear()
    _started_job.update(
        task=task, run_mode=run_mode, by_player=by_player, at=time.time(), tries=0, seen=False
    )
    # A press on the desktop, unless 打开就自动跑 there handed it over.
    actions.start(task, None, run_mode, by_player=by_player)


def _check_started_job() -> bool:
    """True when the started job was just tried again."""
    from src.ui.shell import actions

    if not _started_job:
        return False
    task = _started_job["task"]
    if data.busy() or data.waiting_for_login() or task in data.onetime_tasks() and task.enabled:
        _started_job["seen"] = True
        return False
    if _started_job["seen"]:
        _started_job.clear()  # it ran and ended
        return False
    if time.time() - _started_job["at"] < START_CHECK_SECONDS or actions.game_running():
        return False
    if _started_job["tries"] >= START_RETRIES:
        logger.warning(f"clone job: the game did not open, {task.name} not started")
        _started_job.clear()
        return False
    _started_job["tries"] += 1
    _started_job["at"] = time.time()
    logger.warning(
        f"clone job: the game did not open, trying again ({_started_job['tries']}) {task.name}"
    )
    log_in_this_run()
    actions.start(
        task, None, _started_job["run_mode"], by_player=_started_job.get("by_player", True)
    )
    return True


def _open_game_only() -> None:
    """Start the game (and the trigger tasks, the auto-login among them)
    without a one-time task."""
    try:
        data.og().app.start_controller.start(None)
    except Exception as error:
        logger.warning(f"clone job: opening the game failed: {error}")


def _reload_settings() -> None:
    """Take the settings the tool outside saved before running its job here."""
    configs = [getattr(task, "config", None) for task in data.onetime_tasks() + data.trigger_tasks()]
    global_config = getattr(data.executor(), "global_config", None)
    configs += list((getattr(global_config, "configs", None) or {}).values())
    for config in configs:
        if config is None:
            continue
        try:
            clone_desktop.reload_config(config)
        except Exception as error:
            logger.warning(f"clone job: reloading {getattr(config, 'config_file', '?')} failed: {error}")


def _get_out_of_the_way() -> None:
    """Minimise this tool's windows in the clone so the game is the front window.

    Live 2026-10-03: with the tool's window over the game in the clone, wheel,
    drag and key input went to the tool (爛装分解, 精炼, 镜中之战 and 跑商
    failed), and Leo wants to watch the run outside anyway.
    """
    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        if widget.isWindow() and widget.isVisible() and not widget.isMinimized():
            widget.showMinimized()


_publish_timer: QTimer | None = None
_live_timer: QTimer | None = None
_last_live = {"running": False}
LIVE_WIDTH = 960
LIVE_INTERVAL_MS = 250


_fullscreen_tries: dict[int, list[float]] = {}
FULLSCREEN_TRIES = 2


def _game_window() -> int | None:
    import win32gui

    found: list[int] = []

    def visit(hwnd, _):
        if not (
            win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == "UnityWndClass"
        ):
            return
        # By title, or by the game's exe for clients whose title differs
        # (Leo 2026-10-06: it must work on other players' PCs too).
        if win32gui.GetWindowText(hwnd) == "BrownDust II" or _is_game_process(hwnd):
            found.append(hwnd)

    win32gui.EnumWindows(visit, None)
    return found[0] if found else None


def _is_game_process(hwnd) -> bool:
    try:
        import psutil
        import win32process

        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name().lower() == "browndust ii.exe"
    except Exception:
        return False


def _make_game_fullscreen() -> None:
    """In the clone, switch a windowed game to fullscreen (Alt+Enter), as Leo plays it.

    Live 2026-10-03: windowed 1920x1080 on the 1920x1080 clone desktop put
    the title bar off the top and the clone's taskbar over the bottom of the
    game; fullscreen fills the clone exactly.  Twice per game window at most.
    """
    import ctypes

    import win32con
    import win32gui

    hwnd = _game_window()
    if hwnd is None:
        return
    if not win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & win32con.WS_CAPTION:
        return  # already fullscreen
    _left, _top, width, _height = win32gui.GetClientRect(hwnd)
    if width < 1280:
        return  # the small start-up splash
    tries = _fullscreen_tries.setdefault(hwnd, [])
    if len(tries) >= FULLSCREEN_TRIES or (tries and time.time() - tries[-1] < 8):
        return
    tries.append(time.time())
    from src.tasks.BaseBD2Task import _set_foreground_attached

    try:
        _set_foreground_attached(hwnd)
    except Exception as exc:
        logger.debug(f"clone: bring game to front failed: {exc}")
    time.sleep(0.3)
    keybd_event = ctypes.windll.user32.keybd_event
    keybd_event(win32con.VK_MENU, 0, 0, 0)
    keybd_event(win32con.VK_RETURN, 0, 0, 0)
    keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
    keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    logger.info("clone: game was windowed, sent Alt+Enter for fullscreen")


_play_games_check = {"at": 0.0}


def _close_play_games_error() -> None:
    """Once the game window is up, close Play Games' SE102 launcher in the clone."""
    if time.time() - _play_games_check["at"] < 5 or _game_window() is None:
        return
    _play_games_check["at"] = time.time()
    closed = clone_desktop.close_play_games_launcher()
    if closed:
        logger.info(f"clone: closed Google Play Games launcher (SE102) {closed}")


def _publish() -> None:
    """In the clone: write the run state and a small game picture for the tool outside."""
    try:
        _make_game_fullscreen()
    except Exception as exc:
        logger.debug(f"clone fullscreen check failed: {exc}")
    try:
        _close_play_games_error()
    except Exception as exc:
        logger.debug(f"clone Play Games check failed: {exc}")
    try:
        _apply_control()
        status = run_status()
        clone_desktop.write_atomic(
            clone_desktop.STATUS_FILE, json.dumps(status, ensure_ascii=False).encode("utf-8")
        )
        _last_live["running"] = status["running"]
    except Exception as exc:
        logger.debug(f"clone publish failed: {exc}")
    if _last_live.get("running"):
        try:
            _keep_game_in_front()
        except Exception as exc:
            logger.debug(f"clone front check failed: {exc}")


_front_check = {"at": 0.0}


def _keep_game_in_front() -> None:
    """In the clone during a run: nothing else stays in front of the game.

    Wheel, drag and key input are real input there and go to the front
    window; a window over the game (the tool itself, a startup program, an
    updater, Play Games' SE102) made them miss (live 2026-10-03/04).  Each of
    those was fixed one by one; this catches whatever comes next.  Nobody
    works inside the clone, so taking the front back is always safe.
    """
    if time.time() - _front_check["at"] < 2.0:
        return
    _front_check["at"] = time.time()
    if _login_pending():
        return  # signing in may need the launcher or a browser in front
    import win32gui
    import win32process

    game = _game_window()
    if game is None:
        return
    front = win32gui.GetForegroundWindow()
    root = win32gui.GetAncestor(front, 2) if front else 0  # GA_ROOT
    if root == game:
        return
    if front:
        _thread, pid = win32process.GetWindowThreadProcessId(front)
        _thread, game_pid = win32process.GetWindowThreadProcessId(game)
        if pid == game_pid:
            return  # the game's own window (a dialog of it)
        name = ""
        try:
            import psutil

            name = psutil.Process(pid).name()
        except Exception:
            pass
        if name.lower() == "browndust2starter.exe":
            return  # the game's launcher, e.g. while it updates
        seen = (name or pid, win32gui.GetWindowText(front))
        if _front_check.get("seen") != seen:
            _front_check["seen"] = seen
            logger.info(f"clone: {seen[0]} 「{seen[1]}」 was in front of the game, game brought back")
    from src.tasks.BaseBD2Task import _set_foreground_attached

    _set_foreground_attached(game)


def _publish_live() -> None:
    """In the clone: the game picture for the tool outside, four times a second.

    Once a second looked laggy and jerky outside (Leo 2026-10-07).
    """
    if _last_live.get("running"):
        _write_live_picture()


def run_status() -> dict:
    from src.tasks import run_report
    from src.tasks.BaseBD2Task import task_info_snapshot

    report = run_report.active()
    current = data.current_task()
    shown = current
    if report is not None:
        key = report.get("current")
        for child in data.batch_children(data.task_by_name(report.get("label") or "")):
            if child.key == key:
                shown = child.task
                break
    info = task_info_snapshot(shown) if shown is not None else {}
    stage = ""
    for key in ("当前阶段", "状态"):
        text = str(info.get(key) or "").strip()
        if text and text != "-":
            stage = text
            break
    # A started batch waits, not current, while the auto-login runs first;
    # the tool outside should already show the run then.
    queued = next((task for task in data.onetime_tasks() if task.enabled), None)
    if current is None and report is None and queued is not None:
        current = queued
    if current is None and report is None and _waiting_job:
        current = _waiting_job["task"]
        stage = stage or "等待自动登录完成"
    if current is None and report is None:
        # Between the auto-login's checks nothing is current: the run outside
        # went "ended" and back, and its PC was let sleep (live 2026-10-10).
        waiting = next(
            (task for task in data.onetime_tasks() if getattr(task, "_start_after_login", False)),
            None,
        )
        if waiting is not None:
            current = waiting
            stage = stage or "等待自动登录完成"
    if current is None and report is None and _started_job:
        # The game is opening (or opened again): the run is on its way.
        current = _started_job["task"]
        stage = stage or "正在打开游戏"
    return {
        "at": time.time(),
        "version": own_version(),
        "running": current is not None or report is not None,
        "report": report,
        "task": str(getattr(current, "name", "") or ""),
        "paused": bool(getattr(current, "paused", False)),
        "started": getattr(current, "start_time", 0) or None,
        "stage": stage,
        "log": str(info.get("Log") or "").strip(),
    }


LIVE_FRAME_AGE = 0.3
OWN_CAPTURE_GAP = 0.5


def _live_frame():
    """The running task's latest frame, or a capture of our own when the task
    has not taken one lately (it waits or sleeps), at most twice a second."""
    from src.ui.live_screenshot import LiveScreenshotWidget

    frame = LiveScreenshotWidget._recent_executor_frame(LIVE_FRAME_AGE)
    if frame is not None:
        return frame
    if time.time() - _last_live.get("own_at", 0.0) < OWN_CAPTURE_GAP:
        return None
    _last_live["own_at"] = time.time()
    try:
        from ok import og

        method = og.device_manager.capture_method
        if method is None or (hasattr(method, "connected") and not method.connected()):
            return None
        return method.get_frame()
    except Exception:
        return None


def _write_live_picture() -> None:
    import cv2

    frame = _live_frame()
    if frame is None or frame is _last_live.get("frame"):
        return
    _last_live["frame"] = frame
    height, width = frame.shape[:2]
    if width > LIVE_WIDTH:
        frame = cv2.resize(frame, (LIVE_WIDTH, round(height * LIVE_WIDTH / width)))
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return
    try:
        clone_desktop.write_atomic(clone_desktop.LIVE_FILE, encoded.tobytes())
    except OSError:
        # The tool outside is reading the old picture; the next tick writes it.
        _last_live["frame"] = None


def _stop_cancelled_start() -> None:
    from src.ui.shell import actions

    task = _cancelled_start.get("task")
    if task is None:
        return
    if time.time() > _cancelled_start["until"]:
        _cancelled_start.clear()
    elif task.enabled:
        logger.info(f"clone: {task.name} came up after 停止, stopped")
        _cancelled_start.clear()
        actions.stop(task)


def _apply_control() -> None:
    _stop_cancelled_start()
    command = clone_desktop.take_control()
    if command is None:
        return
    from src.ui.shell import actions

    logger.info(f"clone: {command} from the tool outside")
    current = data.current_task()
    if current not in data.onetime_tasks():
        # Nothing runs yet (the login wait), or only the auto-login check:
        # a stop cancels the waiting or queued run, never the saved 自动登录游戏,
        # and a trigger's pause would pause the whole executor.
        if command == "stop":
            starting = _started_job.get("task")
            actions.stop(next((task for task in data.onetime_tasks() if task.enabled), None))
            if starting is not None and not starting.enabled:
                _cancelled_start.update(task=starting, until=time.time() + START_CHECK_SECONDS)
        else:
            logger.info(f"clone: {command} ignored, nothing is running yet")
        return
    if command == "stop":
        actions.stop(current)
    elif command == "pause" and not current.paused:
        current.pause()
    elif command == "resume" and current.paused:
        current.unpause()


# ------------------------------------------------------------ outside the clone

FRESH_SECONDS = 5.0


class RemoteTask:
    """The task running in the clone, shaped like a task for the pages outside."""

    def __init__(self, status: dict):
        self.status = status
        self.name = status.get("task") or ""
        self.paused = bool(status.get("paused"))
        self.start_time = status.get("started") or 0
        self.info = {"状态": status.get("stage") or "", "Log": status.get("log") or ""}
        self.remote = True

    def info_snapshot(self) -> dict:
        return dict(self.info)


def remote_task() -> RemoteTask | None:
    """Outside the clone: the run in the clone while it is going, else None."""
    if clone_desktop.in_clone():
        return None
    status = clone_desktop.read_status(FRESH_SECONDS)
    if status is None or not status.get("running"):
        return None
    return RemoteTask(status)


def active_run() -> tuple[dict | None, object]:
    """(report, task) of the run in this tool, else of the run in the 桌面分身."""
    from src.tasks import run_report

    report, task = run_report.active(), data.current_task()
    if report is None and task is None:
        remote = remote_task()
        if remote is not None:
            return remote.status.get("report"), remote
    return report, task


def remote_control(command: str) -> None:
    clone_desktop.send_control(command)


def log_in_this_run() -> None:
    """The tool opens the game itself in the clone, so it must also log in.

    Turns 自动登录游戏 on for this run only; the saved setting stays as the
    user left it (live 2026-10-03: with it off, the run stopped on the title
    screen).
    """
    try:
        from src.tasks.trigger.AutoLoginTask import AutoLoginTask

        login = data.executor().get_task_by_class(AutoLoginTask)
    except Exception:
        return
    if login is None or getattr(login, "_enabled", False):
        return
    login._enabled = True
    if getattr(login, "_finished", False):
        login._reset_login_state("桌面分身：这次由工具自动登录。")
    logger.info("clone job: auto-login on for this run")


def message(window, text: str, error: bool = False) -> None:
    from qfluentwidgets import InfoBar, InfoBarPosition

    show = InfoBar.warning if error else InfoBar.success
    show(
        t("桌面分身"),
        t(text),
        parent=window,
        position=InfoBarPosition.TOP,
        duration=8000 if error else 3000,
    )
