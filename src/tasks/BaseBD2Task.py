import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from time import monotonic
from typing import Any, Callable

import cv2
import numpy as np
from ok import BaseTask, Box, Config, Logger
from ok.task.exceptions import FinishedException, TaskDisabledException
from ok.util.file import get_relative_path
from PIL import Image

from src.scene.BD2Scene import BD2Scene
from src.scene.ScreenPosition import ScreenPosition
from src.tasks import failure_reason, problem_report
from src.tasks.task_notifications import log_task_completion
from src.utils import game_language, game_size, keep_awake
from src.utils.game_day import DAILY_REFRESH_HOUR
from src.utils.home_confirmation import (
    HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT,
    home_temporary_announcement_detected,
)
from src.utils.image_utils import (
    best_pixel_valid_match,
    green_mask_from_template,
    masked_zncc,
    pixel_similarity,
    resize_mask,
    resize_template,
    template_match_response,
    to_gray,
)
from src.utils import field_battle, frame_recorder, known_popups, ocr_reread
from src.utils.frozen_screen import (
    FROZEN_SCREEN_SECONDS,
    INEFFECTIVE_PRESSES,
    FrozenScreen,
    FrozenWatch,
    loading_sign,
)
from src.utils.ocr_utils import normalize_ocr_text
from src.utils.press_confirm import POLL_SECONDS as LOOK_AGAIN_POLL_SECONDS
from src.utils.press_confirm import SLOW_PC_GRACE_SECONDS, PressOutcome
from src.utils.press_confirm import press_and_confirm as _press_and_confirm
from src.utils.template_resolution import offline_template_scale
from src.utils.wait_limits import STUCK_SECONDS, scene, set_loading_reader, set_popup_closer

logger = Logger.get_logger(__name__)
PROBE_OUTPUT_DIR = Path("probe_outputs")
GREEN_MASK_TOLERANCE = 0
CARTRIDGE_RECENT_ENTRY_POINT = (0.7875, 0.9111111111111111)
RECENT_CARTRIDGE_SPECIAL_PAGE_SECONDS = 3.0
# The game scrolls whatever it last saw under the pointer.  One wheel sent the
# moment the cursor arrived, with the cursor put back 25 ms later, could land
# before the game saw the pointer there: a player's 活动 list never went down
# while the six-wheel scroll up did (YES-BD2 #11, 2026-10-10).  The cursor
# now stays on the point this long before the first wheel and after the last.
SCROLL_POINTER_SETTLE_SECONDS = 0.15
RECENT_CARTRIDGE_SPECIAL_PAGE_MAX_ACTIONS = 3
# Windows may refuse to raise the game while the user works elsewhere.
FOREGROUND_ATTEMPTS = 3
# A shortcut tap: long enough for the PC client to read it (WASD holds work live).
KEY_TAP_SECONDS = 0.08
# The game's own shortcuts, shown under its buttons: H 主页 in every field
# (广场、餐厅、箱庭、镜中之战...); F on 主页 goes back to the recent
# cartridge (Leo 「f上面是直接返回卡帶」); P in a field opens the quick switch.
# P on 主页 opens the 游戏卡珍藏集 instead, which H cannot leave (live 4K
# 2026-10-11), so P is never sent while 主页 shows.
HOME_KEY = "H"
RECENT_CARTRIDGE_KEY = "F"
# The field F button that sends the "!" followers away, and how 镜中之战 / the
# square look for them (Leo 2026-10-20 「先等5秒等這些靠過來」).
FIELD_FOLLOWERS_KEY = "F"
FIELD_FOLLOWERS_LOOK_SECONDS = 5.0
FIELD_FOLLOWERS_GATHER_SECONDS = 5.0
FIELD_FOLLOWERS_SETTLE_SECONDS = 1.5
# After today's press: two frames, no waiting.
FIELD_FOLLOWERS_QUICK_LOOK_SECONDS = 0.5
QUICK_SWITCH_KEY = "P"
# 广场 and 竞技场 are busy scenes where the game drops the quick-switch press
# (player via Leo 2026-10-17 「切换卡带的时候可以点两下」): with no 卡带选择页
# this long after the press, it is pressed once more while the button shows.
QUICK_SWITCH_REPRESS_AFTER_SECONDS = 1.5
# How long the button may take to read for that second press: on the open
# 卡带选择页 it is gone, so nothing is pressed.
QUICK_SWITCH_REPRESS_LOOK_SECONDS = 1.0
# Before the P key: a short look whether 主页 is still up (the long home wait
# also waits out loading and cost 10-30 s in a busy field).
QUICK_SWITCH_HOME_LOOK_SECONDS = 3.0
HOME_KEY_WAIT_SECONDS = 10.0
ESCAPE_KEY_CODE = 0x1B  # VK_ESCAPE
# The field's quick-switch (P) button, 1080p reference.
FIELD_QUICK_SWITCH_POINT = (851, 997)
FIEND_HUNT_REWARD_TITLE = "魔兽追踪者赛季奖励"
FIEND_HUNT_REWARD_DISMISS_TEXT = "奖励已发放至背包"
GOLDEN_ARENA_REWARD_TITLE = "黄金竞技场体验赛季"
GOLDEN_ARENA_REWARD_DISMISS_TEXT = "奖励已通过邮件发放"
BEIJING_TIMEZONE = timezone(timedelta(hours=8))
RECENT_PVP_CARTRIDGE_TEMPLATE_FILE = "cartridge-image2-left-lower-cutout.png"
RECENT_PVP_CARTRIDGE_TEMPLATE_THRESHOLD = 0.95
RECENT_PVP_CARTRIDGE_PIXEL_THRESHOLD = 0.95
RECENT_PVP_CARTRIDGE_ZNCC_THRESHOLD = 0.85
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PROJECT_ROOT / "recognition-assets" / "template-assets"
# Shared lock for task instances whose ``__init__`` never ran (object.__new__);
# see ``BaseBD2Task._task_info_lock``.
_INFO_FALLBACK_LOCK = threading.RLock()
# The pause after a cue is recognised and before the press.  Leo 2026-10-10
# 「不要有已經判斷到 又空等的情況」, 2026-10-13 「感覺每個按鍵都要等個2秒」: 1 s
# became 0.3 s (enough for a button still sliding in); presses that matter
# are confirmed and re-pressed (press_confirm.py).  The setting got a new name
# so the change applies once: a saved old value other than the old 1.0 default
# moves over, the old default becomes 0.3 (load_config).
RECOGNITION_SETTLE_SECONDS = 0.3
RECOGNITION_SETTLE_KEY = "识别后等待秒数"
OLD_RECOGNITION_SETTLE_KEY = "识别成功后等待秒数"
OLD_RECOGNITION_SETTLE_SECONDS = 1.0


def recognition_settle_from_old(saved: dict):
    """The new setting's value carried over from an old saved config, or
    None (nothing saved, the new key already saved, or the old default)."""
    if not isinstance(saved, dict) or RECOGNITION_SETTLE_KEY in saved:
        return None
    try:
        old = float(saved[OLD_RECOGNITION_SETTLE_KEY])
    except (KeyError, TypeError, ValueError):
        return None
    return None if old == OLD_RECOGNITION_SETTLE_SECONDS else old


class PlayerSteppedIn(TaskDisabledException):
    """继续 after the player used the paused game (src/tasks/takeover.py):
    where the run stood is unknown.  A kind of Stop, so the many handlers
    that pass Stop on pass it on too; the task's run takes it and starts
    again from home (decision 8 of the 10-10 plan, its default)."""


def _run_again_after_step_in(task, run, args, kwargs, stepped_in=False):
    """``run``, once more from home each time the player used the game while
    it was paused: its next press may no longer fit the screen."""
    while True:
        try:
            if stepped_in and not _home_after_step_in(task):
                return False
            return run(task, *args, **kwargs)
        except PlayerSteppedIn:
            stepped_in = True


def _run_watched(task, run, args, kwargs, stepped_in=False, watched=False):
    """``run`` with the stuck-screen watch on (frozen_screen.py).

    A run whose screen froze goes home; a task that is safe to run again
    (``frozen_retry``) runs once more from there, else it ends as failed and
    一键日常 goes on with the next item (Leo 2026-10-13 「可以的話就重試沒辦法
    就下一步」).
    """
    if not watched:
        return _run_again_after_step_in(task, run, args, kwargs, stepped_in)
    from src.tasks.recovery import recover_to_home

    name = getattr(task, "name", "")
    for attempt in (1, 2):
        task._frozen_watch = FrozenWatch()
        try:
            return _run_again_after_step_in(task, run, args, kwargs, stepped_in)
        except FrozenScreen as exc:
            why = str(exc) or (
                f"画面 {FROZEN_SCREEN_SECONDS:.0f} 秒没有变化（点了没反应或认不出画面）"
            )
        finally:
            task._frozen_watch = None
        stepped_in = False
        again = attempt == 1 and bool(getattr(type(task), "frozen_retry", False))
        # Leo 2026-10-14 「那就按esc 而且要跟用戶說明是哪裡卡住觸發了這個」:
        # the step it stuck on goes in front of the reason, Esc goes first.
        where = stuck_step(task)
        if where and where not in why:
            why = f"卡在「{where}」：{why}"
        if _escape_when_stuck(task):
            why += "，已按 Esc"
        task._why = why
        task.log_warning(f"{name}：{why}，" + ("回主页再试一次。" if again else "回主页。"))
        if not again or not recover_to_home(task):
            return False
        task.log_info(f"{name}：已回主页，再试一次。")
    return False


def stuck_step(task) -> str:
    """The step a run is on, in the player's words: its 当前阶段, else the
    last thing it logged (a short line, for the 问题摘要)."""
    try:
        stage = problem_report._stage(task)
    except Exception:
        stage = ""
    if stage:
        return stage
    last = str(getattr(task, "_last_step", "") or "").strip()
    if name := str(getattr(task, "name", "") or ""):
        if last.startswith(name):
            last = last[len(name):].lstrip("：: ")
    return last.rstrip("。.")[:60]


def _escape_when_stuck(task) -> bool:
    """One Esc for a stuck screen (Leo 2026-10-14 「一直沒有識別到那就按esc」):
    Esc only ever steps back or closes a dialog in BD2, never confirms.  Not
    on 主页, where it opens the quit dialog."""
    tap = getattr(task, "tap_escape", None)
    if not callable(tap):
        return False
    try:
        from src.tasks.recovery import home_now

        if home_now(task):
            return False
        task.log_info("卡住了：按一次 Esc 退一步。")
        return bool(tap(after_sleep=0.5))
    except (TaskDisabledException, FinishedException):
        raise
    except Exception:
        return False  # the way home after it still runs


def _home_after_step_in(task) -> bool:
    name = getattr(task, "name", "")
    cls = type(task)
    home_task = getattr(cls, "start_from_home", False) or getattr(
        cls, "recover_home_on_failure", False
    )
    if not home_task:
        reason = "暂停时你动了游戏，不知道跑到哪一步了，这次先停下"
    else:
        from src.tasks.recovery import recover_to_home

        if recover_to_home(task):
            task.log_info(f"{name}：暂停时你动了游戏，已回到主页，这一项从头再跑。")
            return True
        reason = "暂停时你动了游戏，回不到主页，这一项先停下"
    task.info_set("状态", f"{name}失败：{reason}。")
    task.log_warning(f"{name}：{reason}。")
    return False


class CartridgeSpecialPageResult(Enum):
    ABSENT = "absent"
    HANDLED = "handled"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RecentPvpCartridgeMatch:
    score: float = -1.0
    pixel_score: float = -1.0
    zncc_score: float = -1.0
    position: tuple[int, int] = (0, 0)
    size: tuple[int, int] = (0, 0)

    @property
    def passed(self) -> bool:
        return (
            self.score >= RECENT_PVP_CARTRIDGE_TEMPLATE_THRESHOLD
            and self.pixel_score >= RECENT_PVP_CARTRIDGE_PIXEL_THRESHOLD
            and self.zncc_score >= RECENT_PVP_CARTRIDGE_ZNCC_THRESHOLD
        )


def _set_foreground_attached(target: int) -> None:
    """SetForegroundWindow while attached to the foreground window's input queue.

    Windows' foreground lock can refuse a plain call from a background process
    (live 4K 2026-09-30: PVP's WASD walk stopped with the Claude window in
    front, a second run a minute later passed); sharing the foreground
    thread's input state lifts the lock.
    """
    import ctypes

    import win32api
    import win32gui
    import win32process

    foreground = win32gui.GetForegroundWindow()
    their_thread, _pid = win32process.GetWindowThreadProcessId(foreground)
    our_thread = win32api.GetCurrentThreadId()
    attached = bool(
        their_thread
        and their_thread != our_thread
        and ctypes.windll.user32.AttachThreadInput(our_thread, their_thread, True)
    )
    try:
        win32gui.BringWindowToTop(target)
        win32gui.SetForegroundWindow(target)
    finally:
        if attached:
            ctypes.windll.user32.AttachThreadInput(our_thread, their_thread, False)


class BaseBD2Task(BaseTask):
    DEFAULT_MOVE = False
    # Daily/weekly tasks set this: a run that returns False then brings the
    # game back home, so a failed task never leaves it on some other page
    # (live 2026-09-28: goddess stopped in the square, junk gear in the bag).
    # Not for trigger tasks, whose False only means "nothing to do".
    recover_home_on_failure = False
    # Tasks that begin on the home page: a run started on another page (a
    # task clicked while the bag or the square was open) goes home first.
    start_from_home = False
    # A run stopped by a frozen screen (frozen_screen.py) runs once more from
    # home.  Only for tasks whose second run cannot spend or dismantle twice.
    frozen_retry = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        run = cls.__dict__.get("run")
        if run is None or getattr(run, "_bd2_home_guard", False):
            return

        def guarded_run(self, *args, **run_kwargs):
            # Only fully constructed tasks (the executor's); bare test doubles
            # made with object.__new__ have no screen to recover.
            constructed = "_action_interval_lock" in getattr(self, "__dict__", {})
            wanted = getattr(type(self), "recover_home_on_failure", False)
            # A run started by the player keeps a 问题摘要 record; a problem
            # is noted before going home, while the game still shows it.
            keep = constructed and not problem_report.is_trigger(self)
            # A failure after the home checks read 繁中 text says to switch the
            # game to 简体中文 (Leo 2026-10-09: warn now, support 繁中 later).
            started = monotonic()
            # Where this run's log lines begin and its 状态 before it, for the
            # reason a failure is given (failure_reason).
            begun = time.time()
            status_before = task_info_snapshot(self).get("状态") if keep else None
            if keep:
                self._why = ""
            # The run the executor started (not a child of 一键日常): ok-script's
            # display request is given back however it ends (a Stop left it on).
            top = keep and getattr(getattr(self, "executor", None), "current_task", None) is self
            if top:
                self.player_stepped_in = False  # left by a run stopped while paused
            with problem_report.run_scope(self, keep) as scope, keep_awake.released_after(top):
                # An unreadable account list: whose records these are is unknown.
                if keep and self._accounts_stop():
                    scope.ended = problem_report.SETUP
                    return False
                # Daily and weekly tasks first set a game size the tool was not
                # tested on to 1920x1080, or say they could not (Leo 2026-10-09).
                if constructed and (wanted or getattr(type(self), "start_from_home", False)):
                    game_size.fix_or_warn(self)
                    # A task the player started itself looks at the game's
                    # settings first, as 一键日常 does (差異化點子 5): a reminder,
                    # and a game set to 繁中 does not start.
                    if keep and self._setup_stops():
                        scope.ended = problem_report.SETUP
                        return False
                stepped_in = False
                if constructed and getattr(type(self), "start_from_home", False):
                    try:
                        self._go_home_before_run()
                    except PlayerSteppedIn:
                        stepped_in = True  # on its way home: look again first
                # Daily and weekly tasks are watched for a frozen screen.
                watched = constructed and (wanted or getattr(type(self), "start_from_home", False))
                try:
                    result = _run_watched(self, run, args, run_kwargs, stepped_in, watched)
                except TaskDisabledException:
                    problem_report.note_problem(self, "stop")
                    raise
                except FinishedException:
                    raise
                except Exception as exc:
                    hint = game_language.warn_after_failure(self, started) if keep else ""
                    problem_report.note_problem(self, "error", hint or str(exc))
                    # A task that throws (a bug, a full disk) is a failure too:
                    # go home first, then let the error reach the log as before.
                    if wanted and constructed:
                        try:
                            self._leave_home_after_failed_run()
                        except (TaskDisabledException, FinishedException):
                            raise
                        except Exception:
                            pass
                    raise
                if result is False:
                    if keep and not getattr(self, "child_tasks", None):
                        failure_reason.ensure(self, begun, status_before)
                    hint = game_language.warn_after_failure(self, started) if keep else ""
                    problem_report.note_problem(self, "fail", hint)
                    if wanted and constructed:
                        self._leave_home_after_failed_run()
                scope.result = result
                return result

        guarded_run._bd2_home_guard = True
        guarded_run.__name__ = run.__name__
        guarded_run.__qualname__ = run.__qualname__
        guarded_run.__doc__ = run.__doc__
        cls.run = guarded_run

    def sleep(self, timeout):
        super().sleep(timeout)
        # A pause holds the run inside a sleep: after 继续, nothing more is
        # pressed when the player used the game meanwhile (takeover.py).
        runner = getattr(getattr(self, "executor", None), "current_task", None)
        stepped_in = getattr(runner, "player_stepped_in", False) is True
        if stepped_in and not getattr(runner, "paused", False):
            runner.player_stepped_in = False
            raise PlayerSteppedIn()
        return True

    def _accounts_stop(self) -> bool:
        from src.tasks import setup_check

        return bool(setup_check.accounts_stop(self))

    def _setup_stops(self) -> bool:
        from src.tasks import setup_check

        if not setup_check.started_alone(self):
            return False  # 一键日常 looked before its first item
        return bool(setup_check.look(self))

    def _go_home_before_run(self) -> None:
        try:
            from src.tasks.recovery import recover_to_home

            recover_to_home(self)  # returns at once when already home
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:
            pass  # the task's own home check still decides
        # The screen the player started on is not a step of this run.
        problem_report.forget_give_up()

    def _leave_home_after_failed_run(self) -> None:
        from src.tasks.recovery import recover_to_home

        message = None
        try:
            if not recover_to_home(self):
                message = "失败后未能回到主页。"
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            message = f"失败后返回主页出错：{exc}"
        warn = getattr(self, "log_warning", None)
        if message and callable(warn):
            warn(f"{getattr(self, 'name', '')}：{message}")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        frame_recorder.install()  # developer-only, off unless BD2_RECORD_FRAMES is set
        self.visible = False
        self.scene: BD2Scene | None = None
        self.default_box = ScreenPosition(self)
        self._last_interval_action_time = {}
        self._action_interval_lock = threading.Lock()
        # ``task.info`` is a plain dict shared between the TaskExecutor worker
        # thread (info_set/info_clear/log_* and DailyBatchTask child resets)
        # and UI/diagnostics readers.  All mutations go through the mutators
        # below, which serialize on this lock so readers can take a consistent
        # copy via ``info_snapshot``/``task_info_snapshot``.  ``run_task_by_class``
        # rebinds ``task.info`` as a raw attribute, so every locked section must
        # re-read the attribute instead of caching the dict.
        self._info_lock = threading.RLock()
        self._last_home_announcement_clear_at = 0.0
        self._recent_pvp_cartridge_template_cache: (
            tuple[np.ndarray, np.ndarray] | None
        ) = None
        self.default_config.update(
            {
                RECOGNITION_SETTLE_KEY: RECOGNITION_SETTLE_SECONDS,
            }
        )
        self.config_description.update(
            {
                RECOGNITION_SETTLE_KEY: "认出按钮后，点下去之前等多久（秒）。",
            }
        )

    def load_config(self):
        try:
            path = Path(get_relative_path(Config.config_folder, f"{self.__class__.__name__}.json"))
            saved = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            saved = {}
        carried = recognition_settle_from_old(saved)
        super().load_config()
        if carried is not None:
            self.config[RECOGNITION_SETTLE_KEY] = carried

    def log_completion(self, message: str) -> None:
        """Publish a completion popup unless this task is running as a batch child."""

        log_task_completion(self, message)

    def _task_info_lock(self) -> threading.RLock:
        """The per-instance info lock, or a shared fallback for odd instances.

        Tests routinely build tasks via ``object.__new__`` without running
        ``__init__``; those instances have no ``_info_lock`` yet still go through
        these overrides, so they fall back to one process-wide lock instead of
        raising ``AttributeError``.
        """
        lock = self.__dict__.get("_info_lock")
        return _INFO_FALLBACK_LOCK if lock is None else lock

    def info_clear(self) -> None:
        with self._task_info_lock():
            super().info_clear()

    def info_incr(self, key, inc=1):
        with self._task_info_lock():
            return super().info_incr(key, inc)

    def info_add_to_list(self, key, item):
        with self._task_info_lock():
            return super().info_add_to_list(key, item)

    def log_info(self, message, *args, **kwargs):
        # The last step logged, for where a stuck run stopped (stuck_step).
        self._last_step = str(message)
        return super().log_info(message, *args, **kwargs)

    def info_set(self, key, value):
        if key == "当前阶段":
            problem_report.note_stage(self)
        with self._task_info_lock():
            return super().info_set(key, value)

    def info_add(self, key, count=1):
        with self._task_info_lock():
            return super().info_add(key, count)

    def info_snapshot(self) -> dict:
        """A consistent point-in-time copy of ``self.info``.

        The copy is taken under the same lock as every mutator, so it can never
        observe a half-applied update or hit "dictionary changed size during
        iteration".  ``self.info`` is re-read inside the lock because
        ``run_task_by_class`` rebinds the attribute as a whole.
        """
        with self._task_info_lock():
            return dict(getattr(self, "info", None) or {})

    @property
    def main_viewport(self) -> Box:
        return self.box_of_screen(0.05, 0.05, 0.95, 0.95, name="main_viewport")

    @property
    def capture_method_name(self) -> str:
        capture_method = getattr(self.executor.device_manager, "capture_method", None)
        return str(capture_method) if capture_method is not None else "<none>"

    def capture_frame(self, screenshot_name: str | None = None):
        frame = self.next_frame()
        if frame is None:
            raise RuntimeError("未能从 BD2 截取画面。")

        # Every wait asks the task looking at the game whether a still screen
        # shows the loading ring or a loading word before calling it stuck.
        set_loading_reader(self._loading_words_on)
        # ...and closes a popup that covers the page it waits for.
        set_popup_closer(self._close_popup_in_wait)
        watch = getattr(self, "_frozen_watch", None)
        if watch is not None:
            try:
                watch.look(frame)
            except FrozenScreen as exc:
                # A still loading/connecting screen that is not black (slow
                # PC or network) is waited for like the black one.
                word = "" if watch.loading_hold else self._loading_words_on(frame)
                if not word:
                    raise
                watch.hold_for_loading(word)
                self.log_info(f"画面停着但写着「{word}」，当成加载继续等。")
        self._last_scene = scene(frame)
        height, width = frame.shape[:2]
        self.info_set("截图方式", self.capture_method_name)
        self.info_set("游戏分辨率", f"{width}x{height}")
        if screenshot_name:
            self.save_frame(screenshot_name, frame)
        return frame

    def save_frame(self, name: str, frame) -> Path:
        PROBE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = PROBE_OUTPUT_DIR / f"{name}.png"
        if frame.ndim == 2:
            image = Image.fromarray(frame)
        elif frame.ndim == 3 and frame.shape[2] == 4:
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGRA2RGBA))
        elif frame.ndim == 3 and frame.shape[2] == 3:
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        else:
            raise ValueError(f"Unsupported screenshot frame shape: {frame.shape}")
        image.save(output_path)
        self.info_set("截图文件", str(output_path))
        return output_path

    def ocr(self, *args, reread: bool = True, **kwargs):
        """ok-script's OCR; a small box that read nothing is read again.

        See ``src/utils/ocr_reread.py``: bordered, then enlarged 2× and 3×,
        stopping at the first read that finds text.  A read of only stray
        marks counts as nothing (the v6 recognizer on a fixed-size input read
        the player's 跑商 title as 「4」 at 0.77, where v5 read nothing and the
        bordered read found 购买).  Callers that already enlarge the box
        themselves pass ``reread=False``.
        """
        boxes = super().ocr(*args, **kwargs)
        if not reread or args or ocr_reread.trusted(boxes):
            return boxes
        frame = kwargs.get("frame")
        if frame is None or kwargs.get("box") is not None or not ocr_reread.qualifies(frame):
            return boxes
        name = kwargs.get("name") or ""
        cooldown = self.__dict__.setdefault("_ocr_reread_last_empty", {})
        now = monotonic()
        if now - cooldown.get(name, -1e9) < ocr_reread.REREAD_COOLDOWN_SECONDS:
            return boxes
        height, width = frame.shape[:2]
        for attempt in ocr_reread.reread_images(frame):
            retry = dict(kwargs, frame=attempt.image, target_height=0, screenshot=False)
            found = ocr_reread.trusted(super().ocr(**retry))
            if found:
                cooldown.pop(name, None)
                logger.info(f"OCR {name}：第一次没读到，加边放大 {attempt.scale:g} 倍后读到")
                return ocr_reread.map_back(found, attempt, width, height)
        cooldown[name] = now
        return boxes

    def ocr_frame(self, frame=None, threshold: float = 0.2, screenshot: bool = False):
        frame = frame if frame is not None else self.capture_frame()
        boxes = self.ocr(frame=frame, threshold=threshold, log=True, screenshot=screenshot)
        texts = [box.name for box in boxes if getattr(box, "name", "")]
        self.info_set("OCR 文本数量", len(texts))
        self.info_set("OCR 文本", ", ".join(texts[:30]))
        return boxes

    def write_probe_text(
        self,
        name: str,
        lines: list[str],
        info_label: str = "OCR 文本文件",
    ) -> Path:
        PROBE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = PROBE_OUTPUT_DIR / name
        output_path.write_text("\n".join(lines), encoding="utf-8")
        self.info_set(info_label, str(output_path))
        return output_path

    @staticmethod
    def green_mask(template: np.ndarray, tolerance: int = GREEN_MASK_TOLERANCE) -> np.ndarray:
        return green_mask_from_template(template, tolerance=tolerance)

    def click(
        self,
        x: int | float | Box | list[Box] = -1,
        y=-1,
        move_back=None,
        name=None,
        interval=-1,
        move=None,
        down_time=0.02,
        after_sleep=0,
        key="left",
        hcenter=False,
        vcenter=False,
        action_name=None,
    ) -> Any:
        if action_name is not None:
            if not self._check_action_interval(action_name, interval):
                return False
            interval = -1

        if move is None:
            move = self.DEFAULT_MOVE
        if move_back is None:
            move_back = move

        return super().click(
            x,
            y,
            move_back=move_back,
            name=name,
            interval=interval,
            move=move,
            down_time=down_time,
            after_sleep=after_sleep,
            key=key,
            hcenter=hcenter,
            vcenter=vcenter,
        )

    def note_progress(self) -> None:
        """A wait recognised its target: the stuck-screen watch counts again
        from the next look (FrozenWatch.progress)."""
        watch = getattr(self, "_frozen_watch", None)
        if watch is not None:
            watch.progress()

    def operate(self, func: Callable, block: bool = True, restore_cursor: bool = True):
        # What the screen was before this press: a load wait tells a press
        # that changed it (loading) from one that did nothing (wait_limits).
        self._scene_at_press = getattr(self, "_last_scene", None)
        watch = getattr(self, "_frozen_watch", None)
        if watch is not None:
            point, self._press_point = getattr(self, "_press_point", None), None
            watch.pressed(point)
            if watch.ineffective >= INEFFECTIVE_PRESSES and not getattr(self, "_closing_popup", False):
                # The same spot pressed on and on with nothing changing:
                # something sits on top that wants its own button (晋级/奖励
                # pages).  Only a 确认 on an info-only page or a tap-to-return
                # line is pressed here, never 关闭/取消 (Leo 2026-10-14: no
                # change may misjudge a page the task opened itself).
                watch.ineffective = 0
                self._closing_popup = True
                try:
                    if self.close_known_popup(
                        f"同一位置连续{INEFFECTIVE_PRESSES}次点了画面没变", info_only=True
                    ):
                        self.log_warning(
                            f"连续{INEFFECTIVE_PRESSES}次点击画面都没有变化，"
                            "发现弹窗挡住，已先关闭弹窗。"
                        )
                finally:
                    self._closing_popup = False
        interaction = getattr(self.executor, "interaction", None)
        if interaction is not None and hasattr(interaction, "operate"):
            return interaction.operate(func, block=block, restore_cursor=restore_cursor)
        return func()

    def operate_click(
        self,
        x: int | float | Box | list[Box] = -1,
        y=-1,
        restore_cursor=True,
        name=None,
        interval=-1,
        down_time=0.02,
        after_sleep=0,
        key="left",
        hcenter=False,
        vcenter=False,
        action_name=None,
    ) -> Any:
        action_name = action_name or "operate_click"
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            self._press_point = (round(float(x), 3), round(float(y), 3))
        if not self._check_action_interval(action_name, interval):
            return False
        try:
            click_log = self._click_log_message(
                x,
                y,
                int(self.width),
                int(self.height),
                str(name or action_name),
            )
        except Exception:
            click_log = f"{name or action_name}: target={x!r},{y!r}"
        interaction = getattr(self.executor, "interaction", None)
        background_click = bool(
            interaction is not None
            and hasattr(interaction, "background_click_enabled")
            and interaction.background_click_enabled()
        )
        result = self.operate(
            lambda: self.click(
                x,
                y,
                name=name,
                interval=-1,
                move=True,
                down_time=down_time,
                after_sleep=0,
                key=key,
                hcenter=hcenter,
                vcenter=vcenter,
            ),
            block=not background_click,
            restore_cursor=restore_cursor and not background_click,
        )
        self.info_set("鼠标点击", click_log)
        self.sleep(after_sleep)
        return result

    def press_and_confirm(
        self,
        label: str,
        press: Callable[[], object],
        confirmed: Callable[[], object],
        **options,
    ) -> PressOutcome:
        """Press and count it only once the screen shows it worked.

        See ``src.utils.press_confirm``: one more press after 1.5 s while the
        screen from before is still shown (``still_before``), never for
        presses that can spend something (``retries=0``).

        Not confirmed: a known popup that swallowed the press (the 公告 list,
        a season reward overlay) is closed and the press made once more,
        only while the screen from before is still shown.
        """
        outcome = _press_and_confirm(
            label,
            press,
            confirmed,
            sleep=self.sleep,
            log=self.log_info,
            **options,
        )
        still_before = options.get("still_before")
        if outcome or still_before is None or options.get("retries", 1) <= 0:
            return outcome
        if not self.close_known_popup(label, info_only=True):
            return outcome
        if confirmed():
            return PressOutcome(True, outcome.presses, "late")
        if not still_before():
            return outcome
        self.log_info(f"{label}：关掉挡住的弹窗后再按一次。")
        again = _press_and_confirm(
            label,
            press,
            confirmed,
            sleep=self.sleep,
            log=self.log_info,
            **{**options, "retries": 0},
        )
        reason = "confirmed-after-retry" if again else again.reason
        return PressOutcome(again.confirmed, outcome.presses + again.presses, reason)

    def look_again(
        self,
        look: Callable[[], object],
        label: str = "",
        grace: float = SLOW_PC_GRACE_SECONDS,
        popups: bool = True,
    ):
        """``look()`` on fresh frames until it finds something, for ``grace`` s.

        Slow PCs draw late (Leo 2026-10-10 「都可以適當加個1~2秒等看看」「但不要
        有已經判斷到 又空等的情況」): a read that finds nothing is looked at
        again before it counts as absent, and a read that finds something
        returns at once.  ``look`` must take its own new frame each call.
        Still nothing: a known popup covering the page is closed
        (``close_known_popup``) and the page looked at once more.
        Returns the first truthy result, else the last (falsy) one.
        """
        result = look()
        waited = 0.0
        while not result and waited < grace:
            step = min(LOOK_AGAIN_POLL_SECONDS, grace - waited)
            self.sleep(step)
            waited += step
            result = look()
        if result:
            return result
        if label:
            self.log_info(f"{label}：多看了 {grace:g} 秒仍没看到")
        if popups and self.close_known_popup(label or "多看一次"):
            # A popup covered the page (赛季奖励, 获得道具...): closed, look again.
            result = self.look_again(look, label, grace, popups=False)
        return result

    def _loading_words_on(self, frame) -> str:
        """The loading ring's percent or loading/connecting word the frame
        shows, "" when none (one OCR)."""
        try:
            boxes = list(self.ocr(frame=frame, name="卡住前看载入字样", reread=False) or [])
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:
            return ""
        height, width = frame.shape[:2]
        return loading_sign(boxes, width, height)

    def close_known_popup(self, label: str = "", *, info_only: bool = False) -> bool:
        """Close a popup that covers the page with its harmless press
        (src/utils/known_popups; never 取消 mid-task, never a spend).  True
        when one was pressed."""
        try:
            frame = self.capture_frame()
            if frame is None:
                return False
            boxes = list(self.ocr(frame=frame, name="共用弹窗", reread=False) or [])
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:  # a popup look must never break the step
            self.log_info(f"{label}：查看弹窗失败：{exc}")
            return False
        press = known_popups.pick(boxes)
        if info_only and press is not None and press.label in (
            known_popups.CLOSE_TEXT,
            known_popups.CANCEL_TEXT,
        ):
            press = None
        if press is not None and press.key == known_popups.ESC_LABEL:
            self.log_info(f"{label}：画面被公告列表挡住，按 Esc 关闭后再看。")
            return bool(self.tap_escape(after_sleep=1.0))
        center = self._ocr_box_center(press.box) if press is not None else None
        if center is None:
            return False
        height, width = frame.shape[:2]
        self.log_info(f"{label}：画面被弹窗挡住，点击「{press.label}」关闭后再看。")
        self.operate_click(center[0] / width, center[1] / height, after_sleep=1.0)  # 不用确认：调用方接着重看页面
        return True

    def leave_field_battle(self, label: str, boxes=None) -> str:
        """A field battle on screen (src/utils/field_battle): run away from
        it, or press 「离开」 on its result.  "none" (no battle here), "left"
        (back on the field) or why it could not be left.

        Leo 2026-10-22 「判定進戰鬥 就直接按esc 1秒按一下 最多按4下 看到有逃跑就
        不按」 (with auto battle on, the first Esc ends it, the next opens the
        menu)."""
        if boxes is None:
            boxes = self._battle_boxes()
        button = field_battle.leave_button(boxes)
        if button is not None:
            return self._press_battle_leave(label, button)
        if field_battle.flee_confirm_button(boxes) is not None:
            # The run-away dialog already open (a press before this look).
            self.log_info(f"{label}：逃跑确认框开着，按「逃跑」。")
            return self._confirm_flee(label, boxes)
        if not field_battle.in_battle(boxes):
            return "none"
        self.log_info(f"{label}：撞到怪进了战斗，按 Esc 叫出选单逃跑。")
        self.info_set("野外战斗", "逃跑")
        menu = boxes
        for _press in range(field_battle.ESC_PRESSES_MAX):
            if field_battle.flee_button(menu) is not None or field_battle.leave_button(menu) is not None:
                break
            if not self.tap_escape(after_sleep=field_battle.ESC_EVERY_SECONDS):
                return "Esc 没有送到游戏（游戏窗口不在最前面）"
            menu = self._battle_boxes()
        button = field_battle.leave_button(menu)
        if button is not None:  # it ended while we pressed
            return self._press_battle_leave(label, button)
        flee = field_battle.flee_button(menu)
        if flee is None:
            seen = "、".join(str(getattr(box, "name", "")) for box in menu[:8]) or "没读到字"
            return (
                f"按了{field_battle.ESC_PRESSES_MAX}次 Esc 都没看到「逃跑」（读到：{seen}）"
            )
        self._click_battle_box(flee, after_sleep=1.5)
        return self._confirm_flee(label, self._battle_boxes())

    def _confirm_flee(self, label: str, boxes) -> str:
        """After 「逃跑」: press the dialog's 逃跑 (once) and wait for the map."""
        end_at = monotonic() + STUCK_SECONDS
        confirmed = False
        while True:
            confirm = field_battle.flee_confirm_button(boxes)
            if confirm is not None and not confirmed:
                confirmed = True
                self.log_info(f"{label}：逃跑确认框，按「{getattr(confirm, 'name', '')}」。")
                self._click_battle_box(confirm, after_sleep=1.5)
                boxes = self._battle_boxes()
                continue
            if not field_battle.in_battle(boxes) and field_battle.flee_button(boxes) is None:
                self.log_info(f"{label}：已逃跑，回到地图继续。")
                return "left"
            if monotonic() >= end_at:
                return f"按了「逃跑」{STUCK_SECONDS:.0f}秒还在战斗画面"
            self.sleep(0.5)
            boxes = self._battle_boxes()

    def _battle_boxes(self):
        return list(self.ocr(frame=self.capture_frame(), name="野外战斗", reread=False) or [])

    def _click_battle_box(self, box, after_sleep: float) -> bool:
        center = self._ocr_box_center(box)
        if center is None:
            return False
        frame = self.capture_frame()
        height, width = frame.shape[:2]
        self.operate_click(center[0] / width, center[1] / height, after_sleep=after_sleep)  # 不用确认：调用方接着看画面
        return True

    def _press_battle_leave(self, label: str, button) -> str:
        self.log_info(f"{label}：野外战斗已结束，点击「离开」回到地图。")
        if not self._click_battle_box(button, after_sleep=2.0):
            return "战斗结算的「离开」位置读不到"
        return "left"

    def _close_popup_in_wait(self) -> bool:
        """A page wait (wait_limits.load_wait) that has not seen its page:
        close a popup covering it.  Info popups only (never 关闭/取消, which
        could belong to a dialog the step opened itself)."""
        if getattr(self, "_closing_popup_in_wait", False):
            return False
        self._closing_popup_in_wait = True
        try:
            return self.close_known_popup(getattr(self, "name", "") or "等待页面", info_only=True)
        finally:
            self._closing_popup_in_wait = False

    @staticmethod
    def _click_log_message(x, y, width: int, height: int, action_name: str) -> str:
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            if 0 < x < 1 or 0 < y < 1:
                client_x = int(width * x)
                client_y = int(height * y)
                return (
                    f"{action_name}: client=({client_x},{client_y}), "
                    f"relative=({float(x):.6f},{float(y):.6f})"
                )
            return f"{action_name}: client=({int(x)},{int(y)})"

        if isinstance(x, Box):
            return f"{action_name}: box={x.name or '-'} {x.box}"
        if isinstance(x, list):
            return f"{action_name}: boxes={len(x)}"
        return f"{action_name}: target={x!r},{y!r}"

    def drag_client(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration: float = 0.7,
        after_sleep: float = 0.0,
    ) -> bool:
        """Drag with the real mouse, only onto the game in the foreground.

        The drag presses the user's real left button, so it is skipped
        (returns False) unless the game is the foreground window and the
        start point is on it; otherwise it could drag in another program.
        """

        dragged = []

        def action():
            import win32api
            import win32con

            if not self._bring_game_to_foreground():
                return
            interaction = getattr(self.executor, "interaction", None)
            if interaction is not None and hasattr(interaction, "force_activate"):
                interaction.force_activate()
            elif interaction is not None and hasattr(interaction, "try_activate"):
                interaction.try_activate()
            capture = getattr(interaction, "capture", None)

            def to_screen(point: tuple[int, int]) -> tuple[int, int]:
                if capture is not None and hasattr(capture, "get_abs_cords"):
                    return capture.get_abs_cords(point[0], point[1])
                return point

            start_abs = to_screen(start)
            end_abs = to_screen(end)
            if not self._point_on_game(start_abs):
                return
            dragged.append(True)
            steps = max(6, round(duration / 0.03))
            win32api.SetCursorPos(start_abs)
            time.sleep(0.03)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            try:
                for index in range(1, steps + 1):
                    ratio = index / steps
                    x = round(start_abs[0] + (end_abs[0] - start_abs[0]) * ratio)
                    y = round(start_abs[1] + (end_abs[1] - start_abs[1]) * ratio)
                    win32api.SetCursorPos((x, y))
                    time.sleep(duration / steps)
            finally:
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

        self.operate(action, block=True, restore_cursor=True)
        if not dragged:
            self.info_set("拖动", "未拖动：游戏窗口不在最前面或被其他窗口遮住")
            self.log_warning(
                "游戏窗口不在最前面，已停止拖动，避免操作到其他窗口。"
                "运行需要拖动的任务时请让游戏保持在最前面。"
            )
            return False
        self.sleep(after_sleep)
        return True

    def _point_on_game(self, point: tuple[int, int]) -> bool:
        """The top-level window under a screen point is the game."""

        import win32gui

        handles = self._game_window_handles()
        try:
            hwnd = win32gui.WindowFromPoint(tuple(int(value) for value in point))
            root = win32gui.GetAncestor(hwnd, 2)  # GA_ROOT
        except Exception:
            return False
        return hwnd in handles or root in handles

    def _game_window_handles(self) -> set[int]:
        interaction = getattr(self.executor, "interaction", None)
        window = getattr(interaction, "hwnd_window", None)
        handles = {getattr(window, "hwnd", None), getattr(window, "top_hwnd", None)}
        handles.update(info[0] for info in (getattr(window, "hwnds", None) or []) if info)
        return {handle for handle in handles if handle}

    def _game_in_foreground(self) -> bool:
        import win32gui

        return win32gui.GetForegroundWindow() in self._game_window_handles()

    def _bring_game_to_foreground(self) -> bool:
        """Keys only reach the foreground window: make sure it is the game.

        Clicks are posted to the game window and never raise it, so the game
        can sit behind another window (live 2026-09-26: 25 D presses went
        elsewhere while the user typed in another app).  Windows may refuse
        SetForegroundWindow while the user is active in another program.
        """
        import win32gui

        if self._game_in_foreground():
            return True
        interaction = getattr(self.executor, "interaction", None)
        window = getattr(interaction, "hwnd_window", None)
        target = getattr(window, "top_hwnd", None) or getattr(window, "hwnd", None)
        if not target:
            return False
        for attempt in range(FOREGROUND_ATTEMPTS):
            try:
                if attempt == 0:
                    win32gui.SetForegroundWindow(target)
                else:
                    _set_foreground_attached(target)
            except Exception:
                pass
            time.sleep(0.4)
            if self._game_in_foreground():
                return True
        return False

    def hold_key(self, key: str, seconds: float, after_sleep: float = 0.0) -> bool:
        """Hold one movement key (w/a/s/d) with the game in the foreground.

        Exception to the project's mouse-only rule, approved by the user for
        WASD movement (click-to-move off): the PC client read these reliably
        in live tests on 2026-09-26.  Only used where a task opts in.  Nothing
        is sent unless the game is the foreground window (returns False), so
        a key can never land in another program.
        """
        codes = {"w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44}
        if not self._send_game_key(codes[key], seconds):
            self.info_set("按键移动", f"{key} 未发送：游戏窗口不在最前面")
            self.log_warning(
                "游戏窗口不在最前面，已停止键盘移动，避免按键打到其他窗口。"
                "运行需要走位的任务时请不要操作其他窗口。"
            )
            return False
        self.info_set("按键移动", f"{key} {seconds:.2f}s")
        self.sleep(after_sleep)
        return True

    def tap_key(self, key: str, after_sleep: float = 0.0) -> bool:
        """Tap one of the game's own shortcut keys (one letter, as the game
        shows it under a button, e.g. H 主页 / P 卡带) as the fallback when a
        mouse press or a read failed (Leo 2026-10-11 「不可以說認不到辨識不到就
        卡住 你可以用快捷鍵」).  Sent only with the game in the foreground."""
        letter = key.strip().upper()
        if len(letter) != 1 or not letter.isalnum():
            raise ValueError(f"not a single shortcut key: {key!r}")
        if not self._send_game_key(ord(letter), KEY_TAP_SECONDS):
            self.info_set("快捷键", f"{letter} 未发送：游戏窗口不在最前面")
            self.log_warning(f"游戏窗口不在最前面，快捷键 {letter} 没有发送。")
            return False
        self.info_set("快捷键", letter)
        self.sleep(after_sleep)
        return True

    def tap_escape(self, after_sleep: float = 0.0) -> bool:
        """Esc as the last way to close a popup that its ✕ and a blank-space
        tap did not close (Leo 2026-10-12 「關不掉 就按ESC做備案」).  Callers
        send it only while that popup is confirmed open."""
        if not self._send_game_key(ESCAPE_KEY_CODE, KEY_TAP_SECONDS):
            self.info_set("快捷键", "Esc 未发送：游戏窗口不在最前面")
            self.log_warning("游戏窗口不在最前面，Esc 没有发送。")
            return False
        self.info_set("快捷键", "Esc")
        self.sleep(after_sleep)
        return True

    def home_by_key(
        self,
        wait_home: Callable[[float], object],
        label: str,
        timeout: float = HOME_KEY_WAIT_SECONDS,
    ) -> bool:
        """Last resort once the usual way home did not confirm 主页: the
        game's H shortcut, then look again (Leo 2026-10-11 「在餐廳也可以按H回
        主頁」「凡事總要有備用方案 不要失敗就卡死」)."""
        self.log_info(f"{label}：没确认回到主页，改按快捷键 {HOME_KEY}。")
        if not self.tap_key(HOME_KEY, after_sleep=1.0):
            return False
        return bool(wait_home(timeout))

    def _send_game_key(self, code: int, seconds: float) -> bool:
        """Press ``code`` for ``seconds`` with the game in the foreground; the
        key is injected, so the takeover guard ignores it."""
        sent = []

        def action():
            import win32api
            import win32con

            if not self._bring_game_to_foreground():
                return
            scan = win32api.MapVirtualKey(code, 0)
            win32api.keybd_event(code, scan, 0, 0)
            sent.append(True)
            try:
                time.sleep(max(0.0, float(seconds)))
            finally:
                win32api.keybd_event(code, scan, win32con.KEYEVENTF_KEYUP, 0)

        self.operate(action, block=True, restore_cursor=True)
        return bool(sent)

    def scroll_client(
        self,
        relative_point: tuple[float, float],
        scroll_amount: int,
        count: int = 1,
        interval: float = 0.1,
        after_sleep: float = 0.0,
    ) -> None:
        """Send foreground mouse-wheel events at a relative client point."""

        frame = self.capture_frame()
        height, width = frame.shape[:2]
        x = round(max(0.0, min(1.0, relative_point[0])) * width)
        y = round(max(0.0, min(1.0, relative_point[1])) * height)
        wheel_count = max(1, int(count))
        wheel_interval = max(0.0, float(interval))
        interaction = getattr(self.executor, "interaction", None)
        if interaction is None or not hasattr(interaction, "scroll"):
            raise RuntimeError("当前交互对象不支持鼠标滚轮")

        def action():
            import win32api

            if hasattr(interaction, "force_activate"):
                interaction.force_activate()
            elif hasattr(interaction, "try_activate"):
                interaction.try_activate()
            capture = getattr(interaction, "capture", None)
            pointed = capture is not None and hasattr(capture, "get_abs_cords")
            if pointed:
                win32api.SetCursorPos(capture.get_abs_cords(x, y))
                time.sleep(SCROLL_POINTER_SETTLE_SECONDS)
            for index in range(wheel_count):
                interaction.scroll(x, y, int(scroll_amount))
                if index + 1 < wheel_count:
                    time.sleep(wheel_interval)
            if pointed:
                time.sleep(SCROLL_POINTER_SETTLE_SECONDS)

        self.operate(action, block=True, restore_cursor=True)
        self.sleep(after_sleep)

    def _sleep_after_recognition(self) -> None:
        seconds = float(self.config.get(RECOGNITION_SETTLE_KEY, RECOGNITION_SETTLE_SECONDS))
        if seconds > 0:
            self.sleep(seconds)

    def clear_temporary_home_announcement_if_needed(
        self,
        *,
        left_hits: int,
        required_left_hits: int,
        brightness: float,
        brightness_threshold: float,
        gacha_ocr_text: object,
        context: str,
    ) -> bool:
        """Clear a dimming announcement only when the other two home signals pass."""
        if not home_temporary_announcement_detected(
            left_hits=left_hits,
            required_left_hits=required_left_hits,
            brightness=brightness,
            brightness_threshold=brightness_threshold,
            gacha_ocr_text=gacha_ocr_text,
        ):
            return False

        now = monotonic()
        last_click_at = float(
            getattr(self, "_last_home_announcement_clear_at", 0.0)
        )
        if now - last_click_at < 1.0:
            return True
        self._last_home_announcement_clear_at = now

        clear_x, clear_y = HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT
        self.info_set(
            "主页临时公告",
            f"{context}：亮度 {brightness:.3f}/{brightness_threshold:.3f}",
        )
        self.log_info(
            f"{context}：左列关键词和抽抽乐 OCR 已命中但亮度不足，"
            f"按登录公告流程点击清理位置，brightness={brightness:.3f}, "
            f"x={clear_x:.2%}, y={clear_y:.2%}。"
        )
        self._sleep_after_recognition()
        self.operate_click(clear_x, clear_y, after_sleep=0.2)
        return True

    def open_cartridge_quick_switcher(
        self,
        ensure_home: Callable[[], bool],
        click_quick_switch: Callable[[], bool],
        confirm_quick_switch_page: Callable[[], bool],
        *,
        quick_switch_page_shown: Callable[[float], bool] | None = None,
        repress_quick_switch: Callable[[], bool] | None = None,
        home_shown: Callable[[], bool] | None = None,
    ) -> bool:
        """Open the recent cartridge, click quick-switch, and confirm its page.

        ``quick_switch_page_shown(seconds)`` looks for the page that long,
        ``repress_quick_switch`` presses the button only while it still reads
        and ``home_shown`` is a short 主页 look; with them a dropped press is
        made again at once instead of after the full page wait."""
        if not ensure_home():
            return False

        try:
            recent_cartridge_is_pvp = self._recent_cartridge_is_pvp()
        except RuntimeError as exc:
            self.info_set("最近卡带 PVP 模板错误", str(exc))
            self.log_warning(str(exc), notify=True)
            return False

        self._sleep_after_recognition()
        self.info_set("当前阶段", "点击最近卡带")
        self.operate_click(*CARTRIDGE_RECENT_ENTRY_POINT, after_sleep=0.0)
        special_pages = self._handle_recent_cartridge_special_pages(
            allow_pvp_pages=recent_cartridge_is_pvp,
        )
        if special_pages is CartridgeSpecialPageResult.BLOCKED:
            self._save_flow_diagnostic("cartridge_quick_switch_failed")
            return False
        self.info_set("当前阶段", "寻找快速切换按钮")
        quick_switch_opened = click_quick_switch()
        if not quick_switch_opened and self._press_field_quick_switch_by_keycaps():
            quick_switch_opened = True
        if not quick_switch_opened:
            special_pages = self._handle_recent_cartridge_special_pages(
                allow_pvp_pages=recent_cartridge_is_pvp,
            )
            if special_pages is CartridgeSpecialPageResult.BLOCKED:
                self._save_flow_diagnostic("cartridge_quick_switch_failed")
                return False
            if special_pages is CartridgeSpecialPageResult.HANDLED:
                self.info_set("当前阶段", "特殊页面后重试快速切换按钮")
                quick_switch_opened = click_quick_switch()
            elif not recent_cartridge_is_pvp:
                quick_switch_opened = self._retry_recent_cartridge_entry(
                    ensure_home=ensure_home,
                    click_quick_switch=click_quick_switch,
                )
        if (
            quick_switch_opened
            and quick_switch_page_shown is not None
            and repress_quick_switch is not None
            and not quick_switch_page_shown(QUICK_SWITCH_REPRESS_AFTER_SECONDS)
        ):
            self.info_set("当前阶段", "快速切换没反应，补点一次")
            if repress_quick_switch():
                self.log_info("点了快速切换按钮没看到卡带选择页，按钮还在，补点一次。")
        # Pressed but the page never showed (the game did not take the
        # click, YES-BD2 #23): the keys get their turn too.
        if quick_switch_opened and confirm_quick_switch_page():
            return True
        return self._quick_switch_by_key(
            ensure_home, confirm_quick_switch_page, home_shown=home_shown
        )

    def _quick_switch_by_key(
        self,
        ensure_home: Callable[[], bool],
        confirm_quick_switch_page: Callable[[], bool],
        home_shown: Callable[[], bool] | None = None,
    ) -> bool:
        """Last resort when the quick-switch button never read: the game's own
        keys (Leo 2026-10-11 「主頁進卡帶右下角那個P 也是快捷鍵」).  Still on 主页:
        F into the recent cartridge first.  Then P in the field, twice at most;
        P is never sent while 主页 shows (there it opens the collection)."""
        home_now = home_shown or ensure_home
        if home_now():
            self.log_info(f"还在主页，改按快捷键 {RECENT_CARTRIDGE_KEY} 进最近的卡带。")
            if not self.tap_key(RECENT_CARTRIDGE_KEY, after_sleep=2.0) or home_now():
                self._save_flow_diagnostic("cartridge_quick_switch_failed")
                return False
        for press in (1, 2):
            if press > 1 and home_now():
                break
            # A field battle over the field (a monster beside the spawn
            # point, bd2 session 2026-10-22 跑图): P does nothing there and
            # the battle went on under two presses.  Run away first.
            leave = getattr(self, "leave_field_battle", None)
            left = leave("切换卡带") if callable(leave) else "none"
            if left not in ("none", "left"):
                self.log_warning(f"切换卡带：撞到怪进了战斗，{left}。")
                break
            self.log_info(f"没认出快速切换按钮，第{press}次改按快捷键 {QUICK_SWITCH_KEY}。")
            if not self.tap_key(QUICK_SWITCH_KEY, after_sleep=1.5):
                break
            if confirm_quick_switch_page():
                return True
        self._save_flow_diagnostic("cartridge_quick_switch_failed")
        return False

    def _press_field_quick_switch_by_keycaps(self) -> bool:
        """Press the field P button at its place when only the key caps prove the field.

        The see-through P button fails its template on snow (1080p ch13 town,
        live 2026-09-30), so every task switching cards from there - PVP,
        goddess, map runs - stopped.  The opaque C/H key caps still show the
        field HUD; the quick-switch page check after this press decides.
        """
        from types import SimpleNamespace

        from src.tasks.map_trade.navigator_constants import (
            FIELD_ALL_KEYCAP_TEMPLATES,
            FIELD_KEYCAP_MIN_PASSES,
        )
        from src.tasks.map_trade.vision import Vision

        vision = Vision(
            SimpleNamespace(
                config=getattr(self, "config", None) or {},
                info_set=getattr(self, "info_set", lambda *_args, **_kwargs: None),
            )
        )
        try:
            frame = self.capture_frame()
        except AttributeError:  # no executor yet (bare test doubles)
            return False
        # Any two of the C / H / M / Q caps (bright sand hides C, live 4K
        # 2026-10-09).
        if (
            frame is None
            or sum(
                vision.passes(vision.match(frame, spec), spec)
                for spec in FIELD_ALL_KEYCAP_TEMPLATES
            )
            < FIELD_KEYCAP_MIN_PASSES
        ):
            return False
        self.info_set("快速切换按钮", "模板未命中，按键确认在箱庭，点击标定位置")
        x, y = FIELD_QUICK_SWITCH_POINT
        self.operate_click(x / 1920, y / 1080, after_sleep=1.0)
        return True

    def clear_field_followers(self) -> str:
        """The square (Leo 2026-10-20): wait 5 s in place once the "!" shows so
        the crowd has come over, press it, and fall back to the F key.  Once
        they were sent away today (镜中之战 runs first) there is no wait, only
        a quick look (「鏡中之戰趕走過 工具就記錄一下 廣場就不用等了」)."""
        from src.utils.field_followers import FOLLOWERS_DISMISSED, dismissed_today

        if dismissed_today():
            outcome = self.dismiss_field_followers(
                appear_seconds=FIELD_FOLLOWERS_QUICK_LOOK_SECONDS,
                use_key=True,
                even_if_done_today=True,
            )
        else:
            outcome = self.dismiss_field_followers(
                appear_seconds=FIELD_FOLLOWERS_LOOK_SECONDS,
                gather_seconds=FIELD_FOLLOWERS_GATHER_SECONDS,
                use_key=True,
            )
        if outcome == FOLLOWERS_DISMISSED:
            # 「點掉也要等個1.5秒 才走」 (Leo 2026-10-20).
            self.sleep(FIELD_FOLLOWERS_SETTLE_SECONDS)
        return outcome

    def dismiss_field_followers(
        self,
        appear_seconds: float = 3.0,
        *,
        gather_seconds: float = 0.0,
        use_key: bool = False,
        even_if_done_today: bool = False,
    ) -> str:
        """Send away the "!" characters that follow the player after login.

        Presses the field F button while it shows the "!" icon; see
        ``src/utils/field_followers.py``.  Never fails the task: a crowd that
        stays only gets logged, the caller carries on as before.
        """
        from src.utils import task_vision
        from src.utils.field_followers import (
            FIELD_TALK_ICON_TEMPLATE,
            FOLLOWERS_DISMISSED,
            FOLLOWERS_DONE_TODAY,
            FOLLOWERS_STILL_VISIBLE,
            TalkIconSighting,
            dismiss_field_followers,
            dismissed_today,
            is_exclamation_glyph,
            mark_dismissed,
        )

        if dismissed_today() and not even_if_done_today:
            self.info_set("跟随角色按钮", "今日已赶走")
            return FOLLOWERS_DONE_TODAY

        cache = getattr(self, "_field_follower_templates", None)
        if cache is None:
            cache = self._field_follower_templates = {}
        config = getattr(self, "config", None) or {}

        def observe() -> TalkIconSighting:
            frame = self.capture_frame()
            if frame is None:
                return TalkIconSighting(False)
            result = task_vision.match_template(
                frame, FIELD_TALK_ICON_TEMPLATE, config, TEMPLATE_DIR, cache, min_size=5
            )
            passed = task_vision.passes_match(result, FIELD_TALK_ICON_TEMPLATE, config)
            self.info_set("跟随角色按钮", f"{result.score:.3f}/{result.pixel_score:.3f}")
            if not passed:
                return TalkIconSighting(False, result.score)
            x, y = result.position
            box = frame[y : y + result.size[1], x : x + result.size[0]]
            if not is_exclamation_glyph(box):
                # The talk "…" or the circle's hand in the F slot.
                self.info_set("跟随角色按钮", f"{result.score:.3f}/{result.pixel_score:.3f} 非感叹号")
                return TalkIconSighting(False, result.score)
            height, width = frame.shape[:2]
            center = (
                (result.position[0] + result.size[0] / 2) / width,
                (result.position[1] + result.size[1] / 2) / height,
            )
            return TalkIconSighting(True, result.score, center)

        def click(x: float, y: float) -> None:
            self.info_set("当前阶段", "点击F键感叹号，赶走跟随角色")
            self.operate_click(x, y, after_sleep=0.0, name="跟随角色按钮")

        def press_key() -> None:
            self.info_set("当前阶段", "点击没赶走跟随角色，改按F键")
            self.log_info("箱庭：点了感叹号没赶走跟随角色，改按快捷键 F。")
            self.tap_key(FIELD_FOLLOWERS_KEY)

        if gather_seconds > 0:
            self.info_set("跟随角色按钮", "等待跟随角色靠过来")
        outcome = dismiss_field_followers(
            observe,
            click,
            self.sleep,
            appear_seconds=appear_seconds,
            gather_seconds=gather_seconds,
            press_key=press_key if use_key else None,
        )
        if outcome == FOLLOWERS_DISMISSED:
            mark_dismissed()
            self.log_info("箱庭：跟随角色已用F键感叹号赶走。")
        elif outcome == FOLLOWERS_STILL_VISIBLE:
            self.log_info("箱庭：按了两次F键感叹号，图标仍在，继续原流程。")
            self._save_flow_diagnostic("field_followers_still_visible")
        return outcome

    def _retry_recent_cartridge_entry(
        self,
        ensure_home: Callable[[], bool],
        click_quick_switch: Callable[[], bool],
    ) -> bool:
        """Re-click the recent cartridge once after a lost confirmed-home click.

        The first click can be dropped game-side without opening the panel
        (BUG-20260829-07: three identical clicks timed out for 10s each, the
        same click worked right after an app restart). Guarded by a fresh home
        confirmation so the entry point is never pressed over an open panel.
        """
        self.info_set("当前阶段", "重试点击最近卡带")
        if not ensure_home():
            return False
        self._sleep_after_recognition()
        self.info_set("当前阶段", "点击最近卡带")
        self.operate_click(*CARTRIDGE_RECENT_ENTRY_POINT, after_sleep=0.0)
        if self._handle_recent_cartridge_special_pages(
            allow_pvp_pages=False,
        ) is CartridgeSpecialPageResult.BLOCKED:
            return False
        return click_quick_switch()

    def _save_flow_diagnostic(self, name: str) -> None:
        """Persist a failure frame; report bundles pick up *_failed/_error stems.

        The frame is also what the 问题摘要 shows if this run fails.
        """
        try:
            frame = self.capture_frame()
            problem_report.note_give_up(self, frame)
            self.save_frame(name, frame)
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.log_warning(f"诊断截图保存失败：{exc}")

    def _recent_cartridge_is_pvp(self) -> bool:
        """Detect whether clicking the recent cartridge may open a PVP page."""
        frame = self.capture_frame()
        result = self._match_recent_pvp_cartridge(frame)
        verdict = "PVP" if result.passed else "非 PVP"
        self.info_set(
            "最近卡带 PVP 模板",
            (
                f"{verdict} m={result.score:.3f} p={result.pixel_score:.3f} "
                f"z={result.zncc_score:.3f} box={result.position}+{result.size}"
            ),
        )
        return result.passed

    def _match_recent_pvp_cartridge(
        self,
        frame: np.ndarray,
    ) -> RecentPvpCartridgeMatch:
        template, mask = self._load_recent_pvp_cartridge_template()
        frame_gray = to_gray(frame)
        frame_height, frame_width = frame_gray.shape[:2]
        scale = offline_template_scale(
            RECENT_PVP_CARTRIDGE_TEMPLATE_FILE,
            frame_width,
            frame_height,
        )
        scaled_template = resize_template(template, scale)
        scaled_mask = resize_mask(mask, scale)
        height, width = scaled_template.shape[:2]
        if (
            height < 5
            or width < 5
            or height > frame_height
            or width > frame_width
        ):
            return RecentPvpCartridgeMatch(size=(width, height))

        try:
            response = template_match_response(
                frame_gray,
                scaled_template,
                scaled_mask,
            )
        except cv2.error as exc:
            raise RuntimeError(f"最近卡带 PVP 模板匹配失败：{exc}") from exc

        candidate = best_pixel_valid_match(
            response,
            frame_gray,
            scaled_template,
            scaled_mask,
            template_threshold=RECENT_PVP_CARTRIDGE_TEMPLATE_THRESHOLD,
            pixel_threshold=RECENT_PVP_CARTRIDGE_PIXEL_THRESHOLD,
            zncc_threshold=RECENT_PVP_CARTRIDGE_ZNCC_THRESHOLD,
        )
        if candidate is not None:
            return RecentPvpCartridgeMatch(
                score=candidate.score,
                pixel_score=candidate.pixel_score,
                zncc_score=candidate.zncc_score,
                position=candidate.location,
                size=(width, height),
            )

        _minimum, score, _minimum_location, location = cv2.minMaxLoc(response)
        x, y = location
        region = frame_gray[y : y + height, x : x + width]
        return RecentPvpCartridgeMatch(
            score=float(score),
            pixel_score=pixel_similarity(region, scaled_template, scaled_mask),
            zncc_score=masked_zncc(region, scaled_template, scaled_mask),
            position=(int(x), int(y)),
            size=(width, height),
        )

    def _load_recent_pvp_cartridge_template(
        self,
    ) -> tuple[np.ndarray, np.ndarray]:
        cached = getattr(self, "_recent_pvp_cartridge_template_cache", None)
        if cached is not None:
            return cached

        path = TEMPLATE_DIR / RECENT_PVP_CARTRIDGE_TEMPLATE_FILE
        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is None:
            raise RuntimeError(f"最近卡带 PVP 模板不存在或无法读取：{path}")
        if raw.ndim != 3 or raw.shape[2] < 4:
            raise RuntimeError(f"最近卡带 PVP 模板缺少 Alpha 通道：{path}")

        mask = np.where(raw[:, :, 3] > 0, 255, 0).astype(np.uint8)
        active_pixels = int(np.count_nonzero(mask))
        if active_pixels <= 0 or active_pixels >= mask.size:
            raise RuntimeError(f"最近卡带 PVP 模板 Alpha 遮罩无效：{path}")

        cached = (to_gray(raw), mask)
        self._recent_pvp_cartridge_template_cache = cached
        return cached

    def _handle_recent_cartridge_special_pages(
        self,
        timeout: float = RECENT_CARTRIDGE_SPECIAL_PAGE_SECONDS,
        interval: float = 0.25,
        allow_season_reward: bool = True,
        *,
        allow_pvp_pages: bool = True,
    ) -> CartridgeSpecialPageResult:
        """Dismiss shared reward pages and PVP pages when enabled.

        The PVP season reward page (strict 赛季奖励 + 点击画面即可返回 pair) is
        dismissed on any weekday: a player who first enters PVP after Monday
        would otherwise stay stuck behind it.
        """
        end_at = monotonic() + max(0.0, float(timeout))
        handled: set[str] = set()
        action_count = 0
        reward_pending: str | None = None
        reward_clear_frames = 0

        while True:
            boxes = self._recent_cartridge_ocr_boxes()
            text = " ".join(
                str(getattr(box, "name", "")) for box in boxes
            )
            normalized = normalize_ocr_text(text)
            action_name, target_box = "", None
            for title, dismiss_text in (
                (FIEND_HUNT_REWARD_TITLE, FIEND_HUNT_REWARD_DISMISS_TEXT),
                (GOLDEN_ARENA_REWARD_TITLE, GOLDEN_ARENA_REWARD_DISMISS_TEXT),
            ):
                if title in normalized or dismiss_text in normalized:
                    reward_pending = title
                    reward_clear_frames = 0
                    if title in normalized:
                        action_name = title
                        target_box = self._find_ocr_box(boxes, dismiss_text)
                    break
            else:
                if reward_pending:
                    # An empty OCR result cannot prove that the overlay closed.
                    reward_clear_frames = reward_clear_frames + 1 if normalized else 0
                    if reward_clear_frames >= 2:
                        self.info_set(reward_pending, "已确认关闭")
                        reward_pending = None
            if allow_pvp_pages and not reward_pending:
                text, action_name, target_box = self._pvp_special_page_action(
                    boxes,
                    allow_season_reward=allow_season_reward,
                )
            self.info_set("最近卡带特殊页面 OCR", text or "-")

            if (
                action_name
                and action_name not in handled
                and target_box is not None
                and action_count < RECENT_CARTRIDGE_SPECIAL_PAGE_MAX_ACTIONS
            ):
                point = self._ocr_box_center(target_box)
                if point is not None:
                    frame_width = max(1, int(self.width))
                    frame_height = max(1, int(self.height))
                    self.info_set("当前阶段", f"处理最近卡带{action_name}")
                    self.operate_click(
                        max(0.0, min(1.0, point[0] / frame_width)),
                        max(0.0, min(1.0, point[1] / frame_height)),
                        after_sleep=0.5,
                    )
                    handled.add(action_name)
                    action_count += 1
                    if action_name in (FIEND_HUNT_REWARD_TITLE, GOLDEN_ARENA_REWARD_TITLE):
                        end_at = max(end_at, monotonic() + max(0.0, float(timeout)))

            if (
                monotonic() >= end_at
                or (
                    action_count >= RECENT_CARTRIDGE_SPECIAL_PAGE_MAX_ACTIONS
                    and not reward_pending
                )
            ):
                break
            self.sleep(max(0.0, float(interval)))

        if reward_pending:
            self.info_set(reward_pending, "关闭未确认，停止卡带切换")
            return CartridgeSpecialPageResult.BLOCKED
        return (
            CartridgeSpecialPageResult.HANDLED
            if handled else CartridgeSpecialPageResult.ABSENT
        )

    @classmethod
    def _pvp_special_page_action(
        cls,
        boxes: list,
        *,
        allow_season_reward: bool = True,
    ) -> tuple[str, str, object | None]:
        """Return a strict paired PVP special-page action from one OCR frame."""
        text = " ".join(
            str(getattr(box, "name", ""))
            for box in boxes
            if getattr(box, "name", "")
        )
        normalized = normalize_ocr_text(text)
        if (
            FIEND_HUNT_REWARD_TITLE in normalized
            and FIEND_HUNT_REWARD_DISMISS_TEXT in normalized
        ):
            return (
                text,
                FIEND_HUNT_REWARD_TITLE,
                cls._find_ocr_box(boxes, FIEND_HUNT_REWARD_DISMISS_TEXT),
            )
        if (
            allow_season_reward
            and "赛季奖励" in normalized
            and "点击画面即可返回" in normalized
        ):
            return text, "赛季奖励", cls._find_ocr_box(boxes, "点击画面即可返回")
        if "恭喜晋级" in normalized and "确认" in normalized:
            return text, "恭喜晋级", cls._find_ocr_box(boxes, "确认")
        if "段位下滑" in normalized and "确认" in normalized:
            return text, "段位下滑", cls._find_ocr_box(boxes, "确认")
        return text, "", None

    @staticmethod
    def _is_beijing_monday(now: datetime | None = None) -> bool:
        if now is None:
            now = datetime.now(timezone.utc)
        game_day = now.astimezone(BEIJING_TIMEZONE) - timedelta(hours=DAILY_REFRESH_HOUR)
        return game_day.weekday() == 0

    def _pvp_special_page_ocr_boxes(
        self,
        frame: np.ndarray | None = None,
        *,
        name: str = "PVP 特殊页面",
    ) -> list:
        try:
            if frame is None:
                frame = self.capture_frame()
            config = getattr(self, "config", {})
            threshold = next(
                (
                    float(config[key])
                    for key in (
                        "PVP OCR 阈值",
                        "广场 OCR 阈值",
                        "跑商 OCR 阈值",
                        "跑图 OCR 阈值",
                    )
                    if key in config
                ),
                0.2,
            )
            boxes = self.ocr(
                frame=frame,
                threshold=threshold,
                target_height=720,
                log=False,
                name=name,
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.info_set(f"{name} OCR 错误", str(exc))
            return []
        return list(boxes)

    def _recent_cartridge_ocr_boxes(self) -> list:
        return self._pvp_special_page_ocr_boxes(name="最近卡带特殊页面")

    @staticmethod
    def _find_ocr_box(boxes: list, keyword: str):
        normalized_keyword = normalize_ocr_text(keyword)
        for box in boxes:
            if normalized_keyword in normalize_ocr_text(getattr(box, "name", "")):
                return box
        return None

    @staticmethod
    def _ocr_box_center(box) -> tuple[float, float] | None:
        values = tuple(getattr(box, key, None) for key in ("x", "y", "width", "height"))
        if any(value is None for value in values):
            raw_box = getattr(box, "box", None)
            if raw_box is None or len(raw_box) < 4:
                return None
            values = tuple(raw_box[:4])
        x, y, width, height = (float(value) for value in values)
        return x + width / 2, y + height / 2

    def _check_action_interval(self, action_name: Any, interval: float) -> bool:
        if interval <= 0:
            return True
        with self._action_interval_lock:
            now = time.time()
            last_time = self._last_interval_action_time.get(action_name, 0)
            if now - last_time < interval:
                return False
            self._last_interval_action_time[action_name] = now
            return True

    def mark_logged_in(self) -> None:
        if self.scene is not None:
            self.scene.set_logged_in(True)


def task_info_snapshot(task) -> dict:
    """Best-effort thread-safe copy of ``task.info`` for any task object.

    ``BaseBD2Task`` (and subclasses) expose a locked ``info_snapshot``; tasks
    outside that hierarchy — ok-framework trigger tasks or
    plain stubs — only get an unlocked ``dict`` copy.  For those, a concurrent
    mutation can still surface as ``RuntimeError`` mid-copy, which is swallowed
    into an empty snapshot so UI/diagnostics readers stay alive.
    Callers that must know about snapshot failures (diagnostics) perform their
    own strict copy instead of relying on this fallback.
    """
    snapshot = getattr(task, "info_snapshot", None)
    if callable(snapshot):
        return snapshot()
    try:
        return dict(getattr(task, "info", None) or {})
    except RuntimeError:
        return {}
