"""打开游戏的等待窗不再卡在「加载中」（YES-BD2 #56，2026-10-26）。

玩家勾了「打开就自动跑日常」：游戏开到 TOUCH TO START、工具也显示已连接，
ok-script 的「正在启动，N 秒后超时」却一直不结束，倒数完只换成「加载中」，
工具不按标题、不开跑，也没有报错。ok 的每一段等待都有上限，到时会报超时
并关掉等待窗；一直不关，表示启动流程的某一步本身没有返回（是哪一步，要
玩家的 ok-bd2.log 才能确定）。这里不猜是哪一步，对整个启动流程做三件事：

1. 每一步记进日志（「启动：等游戏视窗出现…」），慢的步骤记耗时。
2. 看门狗：某一步超过它的上限还没结束，日志写下卡在哪一步和当时的调用
   栈；游戏已经连上、截得到画面，就照常开跑（不再等那一步）；连不上，
   关掉等待窗，并用玩家看得懂的话说卡在哪一步。卡住的那一步之后若又
   返回，它的通知不再显示，之后再按开始也不会排在它后面。
3. 等待时间和重试次数由玩家在「设置 → 网络慢时的等待」调（
   src/utils/wait_settings.py）；等太久时先自动再等一轮，游戏已经开着就
   不再开一次。超时的讯息说等了多久、在等什么。

另外，等待窗更新时出了错，「完成」也一定会把等待窗关掉。
"""

from __future__ import annotations

import sys
import threading
import traceback
from functools import wraps
from importlib import import_module
from time import monotonic

from ok import Logger

from src.utils import wait_settings

logger = Logger.get_logger(__name__)

_MARKER = "_ok_bd2_start_watchdog"

# Each step in the player's words.
STEP_REFRESH = "找游戏视窗"
STEP_LAUNCH = "打开游戏"
STEP_WINDOW = "等游戏视窗出现"
STEP_READY = "等游戏可以截图"
STEP_CHECK = "检查游戏画面"
STEP_CAPTURE = "截一张游戏画面"
STEP_RESIZE = "调整游戏视窗大小"
STEP_GPU = "检查显卡滤镜设定"
STEP_EXECUTOR = "开始执行任务"
WAIT_STEPS = (STEP_WINDOW, STEP_READY)
# How long one step may take before it counts as stuck.  The two waits stop
# themselves after the player's 打开游戏最长等多久; one look at the game takes
# well under a minute even on a slow PC (capture 5 s, frame check 8 s,
# resize 5 s).
WAIT_GRACE_SECONDS = 60.0
STEP_LIMIT_SECONDS = {
    STEP_REFRESH: 60.0,
    STEP_LAUNCH: 30.0,
    STEP_CHECK: 60.0,
    STEP_CAPTURE: 30.0,
    STEP_RESIZE: 30.0,
    STEP_GPU: 30.0,
    STEP_EXECUTOR: 30.0,
}
# Steps logged when they start; the others only when slow.
ANNOUNCED_STEPS = (STEP_LAUNCH, STEP_WINDOW, STEP_READY, STEP_GPU, STEP_EXECUTOR)
SLOW_STEP_SECONDS = 5.0
POLL_SECONDS = 1.0
READY_CHECK_SECONDS = 10.0

SETTING_HINT = "网络或电脑慢的话，可以在「设置 → 网络慢时的等待」把时间调长。"
TIMEOUT_MESSAGE = "打开游戏等了 {seconds} 秒，{what}。" + SETTING_HINT
STUCK_TAKEN_OVER = "打开游戏时「{step}」卡了 {seconds} 秒没反应；游戏已经连上，直接开始跑。"
STUCK_MESSAGE = (
    "打开游戏时「{step}」卡了 {seconds} 秒没反应，{state}，这次没有开始。"
    "请关掉游戏再按开始；还是一样的话，把「看日志」里的 ok-bd2.log 传给开发者。"
)
STATE_NOT_CONNECTED = "游戏也还没连上"
STATE_EXECUTOR = "任务没能开始执行"
WAITING_FOR = {
    STEP_WINDOW: "游戏视窗一直没出现",
    STEP_READY: "游戏还是截不到画面",
}


class StartRun:
    """One press of start, on the thread that runs it."""

    def __init__(self, controller, task, exit_after):
        self.controller = controller
        self.task = task
        self.exit_after = exit_after
        self.thread_ident = threading.get_ident()
        self.started_at = monotonic()
        self.lock = threading.Lock()
        self.steps: list[list] = []  # [name, since, limit]
        self.finished = False
        self.abandoned = False
        self.hold_timeouts = False
        self.held_timeout: str | None = None
        self.last_reason: str | None = None
        self.waited = 0.0

    # ------------------------------------------------------------- steps

    def enter(self, name: str) -> None:
        if name in WAIT_STEPS:
            limit = float(self.controller.start_timeout) + WAIT_GRACE_SECONDS
        else:
            limit = STEP_LIMIT_SECONDS.get(name, 60.0)
        with self.lock:
            self.steps.append([name, monotonic(), limit])
        if name in ANNOUNCED_STEPS:
            logger.info(f"启动：{name}…")

    def leave(self, name: str) -> None:
        with self.lock:
            for index in range(len(self.steps) - 1, -1, -1):
                if self.steps[index][0] == name:
                    _name, since, _limit = self.steps.pop(index)
                    break
            else:
                return
        took = monotonic() - since
        if name in WAIT_STEPS:
            self.waited = max(self.waited, took)
        if took >= SLOW_STEP_SECONDS:
            logger.info(f"启动：{name} 用了 {took:.0f} 秒")

    def stuck_step(self, now: float) -> tuple[str, float] | None:
        with self.lock:
            steps = list(self.steps)
        for name, since, limit in reversed(steps):  # the innermost first
            if now - since > limit:
                return name, now - since
        return None

    def current_wait(self) -> str | None:
        with self.lock:
            for name, _since, _limit in reversed(self.steps):
                if name in WAIT_STEPS:
                    return name
        return None

    # ------------------------------------------------------------ messages

    def timeout_message(self, step: str) -> str:
        what = WAITING_FOR.get(step, "还没准备好")
        if step == STEP_READY and self.last_reason:
            what = f"{what}（{self.last_reason}）"
        seconds = round(self.controller.start_timeout)
        return TIMEOUT_MESSAGE.format(seconds=seconds, what=what)


_runs: dict[int, StartRun] = {}
_runs_lock = threading.Lock()


def _run_here() -> StartRun | None:
    with _runs_lock:
        return _runs.get(threading.get_ident())


def _real_communicate():
    return import_module("ok.core.events").communicate


# ------------------------------------------------------------------ signals


class _StartingSignal:
    """``starting_emulator`` as the start thread sees it."""

    def __init__(self, signal):
        self._signal = signal

    def emit(self, done, error=None, seconds_left=0):
        run = _run_here()
        if run is not None:
            if run.abandoned:
                logger.info(f"启动：已经不等这次启动了，不再显示（{done}, {error}）")
                return
            wait = run.current_wait()
            if done and error and wait is not None:
                # The only error the two waits send: they timed out.
                if run.hold_timeouts:
                    run.held_timeout = wait
                    logger.info(f"启动：{wait} 超时（{run.last_reason or '-'}），先不报，再等一轮")
                    return
                error = run.timeout_message(wait)
                logger.warning(f"启动：{error}")
        self._signal.emit(done, error, seconds_left)

    def __getattr__(self, name):
        return getattr(self._signal, name)


class _StartSignals:
    def __init__(self, real):
        self._real = real
        self.starting_emulator = _StartingSignal(real.starting_emulator)

    def __getattr__(self, name):
        return getattr(self._real, name)


# ------------------------------------------------------------------ wrappers


class StartAbandoned(Exception):
    """A start the watchdog gave up on goes no further once its stuck step
    returns: no more resizing, frames or task start behind the run that
    took over.  ok catches it like any start error (the message is dropped)."""


def _step(name: str, method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        run = _run_here()
        if run is None:
            return method(*args, **kwargs)
        if run.abandoned:
            raise StartAbandoned(f"这次启动已经不等了（{name}）")
        run.enter(name)
        try:
            return method(*args, **kwargs)
        finally:
            run.leave(name)

    return wrapper


def _wrap_do_start(original):
    @wraps(original)
    def do_start_watched(self, task=None, exit_after=False):
        self.start_timeout = wait_settings.get(wait_settings.START_TIMEOUT)
        run = StartRun(self, task, exit_after)
        with _runs_lock:
            _runs[run.thread_ident] = run
        self._ok_bd2_start_run = run
        watchdog = threading.Thread(
            target=_watch, args=(run,), name="ok-bd2-start-watchdog", daemon=True
        )
        watchdog.start()
        try:
            return original(self, task, exit_after)
        finally:
            run.finished = True
            with _runs_lock:
                if _runs.get(run.thread_ident) is run:
                    del _runs[run.thread_ident]
            if run.abandoned:
                logger.info("启动：卡住的那一步后来返回了")

    return do_start_watched


def _wrap_start_device(original):
    @wraps(original)
    def start_device_with_retries(self, initial_refresh_done=False):
        run = _run_here()
        if run is None:
            return original(self, initial_refresh_done)
        retries = wait_settings.get(wait_settings.START_RETRIES)
        attempt = 0
        while True:
            last = attempt >= retries
            run.hold_timeouts = not last
            run.held_timeout = None
            try:
                if attempt == 0:
                    result = original(self, initial_refresh_done)
                else:
                    result = _wait_again(self, original)
            finally:
                run.hold_timeouts = False
            if result or run.held_timeout is None or run.abandoned or self.exit_event.is_set():
                return result
            attempt += 1
            logger.info(f"启动：第 {attempt} 次再等一轮（最多 {retries} 次）")
            _real_communicate().starting_emulator.emit(False, None, int(self.start_timeout))

    return start_device_with_retries


def _wait_again(controller, original):
    """A retry: wait once more, opening the game again only if it is not running."""
    from src.utils.game_process import game_running

    if game_running() is False:
        logger.info("启动：游戏没在跑，重新打开")
        return original(controller, False)
    device = import_module("ok").og.device_manager.get_preferred_device()
    if device and device.get("device") == "windows":
        if not controller._wait_until_started_window_stable():
            return False
    if not controller._wait_until_device_ready():
        return False
    _real_communicate().starting_emulator.emit(True, None, 0)
    return True


def _wrap_check_device_error(original):
    @wraps(original)
    def check_device_error_noted(self):
        error = original(self)
        run = _run_here()
        if run is not None:
            run.last_reason = str(error) if error else None
        return error

    return check_device_error_noted


# ------------------------------------------------------------------ watchdog


def _watch(run: StartRun) -> None:
    while not run.finished:
        if run.controller.exit_event.is_set():
            return
        stuck = run.stuck_step(monotonic())
        if stuck is not None:
            _give_up_waiting(run, *stuck)
            return
        threading.Event().wait(POLL_SECONDS)


def _give_up_waiting(run: StartRun, step: str, seconds: float) -> None:
    run.abandoned = True
    stack = ""
    frame = sys._current_frames().get(run.thread_ident)
    if frame is not None:
        stack = "".join(traceback.format_stack(frame))
    logger.error(f"启动卡住：「{step}」{seconds:.0f} 秒没有结束，当时在：\n{stack}")
    signal = _real_communicate().starting_emulator
    if step == STEP_EXECUTOR:
        state = STATE_EXECUTOR
    elif _game_ready():
        try:
            _start_without_waiting(run)
        except Exception as exc:
            logger.error("启动：直接开始失败", exc)
            state = STATE_EXECUTOR
        else:
            message = STUCK_TAKEN_OVER.format(step=step, seconds=round(seconds))
            logger.warning(message)
            signal.emit(True, None, 0)
            _real_communicate().notification.emit(
                message, "打开游戏", False, True, None, None, None
            )
            return
    else:
        state = STATE_NOT_CONNECTED
    message = STUCK_MESSAGE.format(step=step, seconds=round(seconds), state=state)
    logger.warning(message)
    signal.emit(True, message, 0)


def _game_ready() -> bool:
    """The game window is connected and gives a frame (looked at for at most 10 s)."""
    answer: list[bool] = []

    def look():
        try:
            device_manager = import_module("ok").og.device_manager
            capture = device_manager.capture_method
            answer.append(
                bool(
                    device_manager.device_connected()
                    and capture is not None
                    and capture.connected()
                    and capture.get_frame() is not None
                )
            )
        except Exception as exc:
            logger.info(f"启动：看不出游戏是否连上（{exc}）")
            answer.append(False)

    looker = threading.Thread(target=look, name="ok-bd2-start-ready", daemon=True)
    looker.start()
    looker.join(READY_CHECK_SECONDS)
    return bool(answer and answer[0])


def _start_without_waiting(run: StartRun) -> None:
    """What ok does after the game is ready: enable the tasks and start."""
    og = import_module("ok").og
    controller_class = type(run.controller)
    task = run.task
    if isinstance(task, int):
        task = og.executor.onetime_tasks[task]
    tasks = [t for t in og.executor.get_all_tasks() if getattr(t, "enable_after_start", False)]
    if task is not None and task not in tasks:
        tasks.append(task)
        if run.exit_after:
            task.exit_after_task = True
    for enable in tasks:
        controller_class._mark_task_enabled(enable)
    og.executor.start()


# ------------------------------------------------------------------ install


def _wrap_start(original):
    @wraps(original)
    def start_not_behind_stuck(self, task=None, exit_after=False):
        run = getattr(self, "_ok_bd2_start_run", None)
        if run is not None and run.abandoned and not run.finished:
            # The handler thread is still inside the stuck step: a new press
            # would wait behind it forever.
            logger.info("启动：上一次启动还卡着，这次另外开始")
            self.starting = True
            threading.Thread(
                target=self.do_start, args=(task, exit_after), name="ok-bd2-start", daemon=True
            ).start()
            return
        return original(self, task, exit_after)

    return start_not_behind_stuck


def _guard_dialog(original):
    @wraps(original)
    def starting_emulator_guarded(self, done, error, seconds_left):
        try:
            return original(self, done, error, seconds_left)
        except Exception as exc:
            logger.error("启动等待窗更新失败", exc)
            if done:
                dialog = getattr(self, "emulator_starting_dialog", None)
                if dialog is not None:
                    try:
                        dialog.close()
                    except Exception as close_exc:
                        logger.error("启动等待窗关不掉", close_exc)
            if error:
                try:
                    from ok.core.notifications import alert_error

                    alert_error(error, True)
                except Exception as alert_exc:
                    logger.error("启动错误没能显示", alert_exc)

    return starting_emulator_guarded


def install_start_watchdog() -> None:
    start_controller = import_module("ok.core.start_controller")
    controller = start_controller.StartController
    if getattr(controller, _MARKER, False):
        return
    setattr(controller, _MARKER, True)

    start_controller.communicate = _StartSignals(start_controller.communicate)
    start_controller.execute = _step(STEP_LAUNCH, start_controller.execute)

    controller.start = _wrap_start(controller.start)
    controller.do_start = _wrap_do_start(controller.do_start)
    controller.start_device = _wrap_start_device(controller.start_device)
    controller._wait_until_started_window_stable = _step(
        STEP_WINDOW, controller._wait_until_started_window_stable
    )
    controller._wait_until_device_ready = _step(STEP_READY, controller._wait_until_device_ready)
    controller.check_device_error = _step(
        STEP_CHECK, _wrap_check_device_error(controller.check_device_error)
    )
    controller.check_resolution = _step(STEP_RESIZE, controller.check_resolution)
    controller.try_capture_a_frame = staticmethod(
        _step(STEP_CAPTURE, controller.try_capture_a_frame)
    )
    controller.check_gpu_driver_post_processing = _step(
        STEP_GPU, controller.check_gpu_driver_post_processing
    )

    device_manager = import_module("ok.device.DeviceManager").DeviceManager
    device_manager.do_refresh = _step(STEP_REFRESH, device_manager.do_refresh)
    executor = import_module("ok.task.TaskExecutor").TaskExecutor
    executor.start = _step(STEP_EXECUTOR, executor.start)

    try:
        main_window = import_module("ok.ui.qt.MainWindow").MainWindow
    except Exception as exc:  # no Qt (tests without a display)
        logger.info(f"start watchdog: main window not guarded ({exc})")
    else:
        main_window.starting_emulator = _guard_dialog(main_window.starting_emulator)
