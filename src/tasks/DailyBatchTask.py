from __future__ import annotations

import os
import subprocess
import time
from collections import ChainMap
from dataclasses import dataclass

from ok import BaseTask
from ok.task.exceptions import FinishedException, TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks import problem_report, run_report, setup_check, weekly_ticks
from src.tasks.CraftGearTask import CraftGearTask
from src.tasks.DailyTask import DailyTask
from src.tasks.DoomBookTask import DoomBookTask
from src.tasks.EventBattleTask import EventBattleTask
from src.tasks.EventRewardTask import EventRewardTask
from src.tasks.FreeGachaTask import FreeGachaTask
from src.tasks.GearTasks import DailyRefineTask
from src.tasks.JunkGearTask import JunkGearTask
from src.tasks.map_trade.phase_ledger import ONLY_INCOMPLETE_KEY
from src.tasks.MapCollectionTask import MapCollectionTask
from src.tasks.MapTradeTask import MapTradeTask
from src.tasks.PVPTask import PVPTask
from src.tasks.QuickHuntTask import QuickHuntTask
from src.tasks.RestaurantTask import RestaurantStoneTask
from src.tasks.RewardClaimTasks import MailRewardTask, MissionRewardTask, PassRewardTask
from src.tasks.SquareGoddessTask import SquareGoddessTask
from src.tasks.task_notifications import (
    log_task_completion,
    suppress_task_completion_notifications,
)
from src.tasks.WeeklyTasks import ArcadeBrowseTask, HomePopularityTask
from src.utils import game_process, game_size, keep_awake

RUN_MODE_ALL = "all"
RUN_MODE_INCOMPLETE = "incomplete"
_VALID_RUN_MODES = frozenset({RUN_MODE_ALL, RUN_MODE_INCOMPLETE})
# 「执行剩余」等请求的 run_mode 有效期：覆盖冷启动拉起游戏到设备就绪的
# 常规耗时；超时未消费即作废，防止启动失败后的残留模式被手动点击继承。
REQUESTED_RUN_MODE_VALIDITY_SECONDS = 600.0
# 「完成日常后自动关机」的关机倒计时秒数：留出执行 shutdown /a 取消的窗口。
SHUTDOWN_COUNTDOWN_SECONDS = 60
# 游戏闪退后最多重开几次（同一次开始的一键日常里）；再闪退就停下。
CRASH_RESTARTS_MAX = 2
CRASH_NOTE = "游戏闪退了"
CRASH_DONE_NOTE = "闪退前已经做完"


def _schedule_system_shutdown(seconds: int) -> bool:
    """Schedule a Windows shutdown via System32 shutdown.exe.

    shutdown.exe 注册计划后立即退出，返回值即计划是否被系统接受；不等待
    倒计时。使用绝对路径防止安装目录内同名可执行文件顶替，并以
    CREATE_NO_WINDOW 避免在 GUI 进程里闪出控制台窗口。
    """
    command = [
        os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32",
            "shutdown.exe",
        ),
        "/s",
        "/t",
        str(int(seconds)),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        timeout=10,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.returncode == 0


def failure_note(task) -> str:
    """Why a child returned False, in a few words for the summary page.

    Tasks put their last stage into 状态, mostly as "<name>失败：<why>。" or
    "<name><stage>失败。"; the task name and the generic words are dropped.
    """
    from src.tasks.BaseBD2Task import task_info_snapshot

    info = task_info_snapshot(task)
    text = str(info.get("状态", "") or "").strip().rstrip("。.")
    name = str(getattr(task, "name", "") or "")
    if name and text.startswith(name):
        text = text[len(name):]
    for prefix in ("失败：", "失败:", "：", ":"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.strip()
    if text in {"", "失败", "结束", "完成", "中止", "启动"}:
        return "没有做完"
    return text[:40]


@dataclass(frozen=True)
class DailyBatchChild:
    config_key: str
    task_class: type[BaseTask]
    # 周常 in 一键日常 (Leo 2026-10-09): skipped once done this game week.
    weekly: bool = False


DAILY_BATCH_CHILDREN = (
    DailyBatchChild("公会、小屋、酒馆", DailyTask),
    DailyBatchChild("领取常客圣石", RestaurantStoneTask),
    DailyBatchChild("快速狩猎", QuickHuntTask),
    DailyBatchChild("免费抽抽乐", FreeGachaTask),
    DailyBatchChild("爛装强化分解", JunkGearTask),
    DailyBatchChild("每日精炼一次", DailyRefineTask),
    DailyBatchChild("广场女神像", SquareGoddessTask),
    DailyBatchChild("自动PVP", PVPTask),
    DailyBatchChild("跑商", MapTradeTask),
    DailyBatchChild("活动每日战斗", EventBattleTask),
    # 周常 run with the daily ones and are skipped once done this week (Leo
    # 2026-10-09, YES-BD2 issue #1: no separate 一键完成周常).  Before the
    # rewards, so the weekly missions they finish are claimed in the same run.
    DailyBatchChild("浏览街机菜单", ArcadeBrowseTask, weekly=True),
    DailyBatchChild("小屋增加人气", HomePopularityTask, weekly=True),
    DailyBatchChild("制作装备", CraftGearTask, weekly=True),
    DailyBatchChild("末日之书", DoomBookTask, weekly=True),
    # 收尾：先领任务奖励，再领通行证（通行证任务依赖每日任务完成数），再收邮件。
    DailyBatchChild("领取任务奖励", MissionRewardTask),
    DailyBatchChild("领取通行证", PassRewardTask),
    DailyBatchChild("领取邮件", MailRewardTask),
    # Red-badged 活动 pages after the mail (Leo 2026-10-03), before the long map run.
    DailyBatchChild("领取活动奖励", EventRewardTask),
    # Weekly progress, spread over the days: at most 7 cards a day.  Last of
    # all, after the mail (Leo 2026-10-03), so the long run never holds up
    # the daily rewards.
    DailyBatchChild("每周跑图", MapCollectionTask),
)


class ChildBatchTask(BaseTask):
    """Run selected home-to-home child tasks in a fixed safe order.

    Shared by the daily and weekly batches; neither inherits from the other so
    ``executor.get_task_by_class`` (an isinstance lookup) never confuses them.
    """

    batch_label = "一键完成日常"

    status_keys = [
        "启用",
        "状态",
        "运行模式",
        "当前子任务",
        "完成",
        "失败",
        "跳过",
        "Log",
        "Warning",
        "Error",
    ]
    child_tasks = DAILY_BATCH_CHILDREN

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = self.batch_label
        self.description = (
            "按顺序执行已开启的公会、小屋、酒馆、常客圣石、快速狩猎、抽抽乐、爛装分解、精炼、"
            "广场、PVP、跑商、活动战斗、本周还没做的周常，最后领取任务奖励、通行证和邮件。"
        )
        self.icon = FluentIcon.COMPLETED
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.visible = True
        self._requested_run_mode = RUN_MODE_ALL
        self._start_after_login = False

        child_keys = [child.config_key for child in self.child_tasks]
        self.default_config.update(
            {
                "启用": True,
                "失败后继续": True,
                "完成日常后自动关机": False,
                # Ticked on 首页 (src/ui/shell/autorun.py, Leo 2026-10-09).
                "打开工具时自动开始": False,
                **{key: True for key in child_keys},
            }
        )
        self.config_description.update(
            {
                "启用": f"是否允许{self.batch_label}按顺序执行已开启的子任务。",
                "失败后继续": (
                    "某个子任务失败时，先尝试回到主页（关闭弹窗、按返回、从地图回主页），"
                    "成功回到主页就继续执行后面的子任务；回不到主页才停止。"
                ),
                "完成日常后自动关机": (
                    "一键完成日常运行成功且全部已启用子任务今日均已完成"
                    "（含运行前就已完成的项目）后，60 秒倒计时自动关机；"
                    "期间在系统命令行执行 shutdown /a 可取消。"
                ),
                "打开工具时自动开始": (
                    "打开工具几秒后自动开始，只跑今天还没做的（周常是本周）；"
                    "游戏没开会自己打开并登录。"
                ),
                **{
                    key: f"是否在{self.batch_label}中执行{key}。"
                    for key in child_keys
                },
            }
        )
        self.config_type.update(
            {
                "启用": {
                    "sub_configs": {
                        True: child_keys,
                    }
                }
            }
        )

    def request_run_mode(self, run_mode: str) -> None:
        """Select the next executor-driven run without persisting UI config.

        请求带有效期（覆盖启动器拉起游戏到设备就绪的常规耗时）：启动失败
        （do_start 异步失败、设备无法就绪）时 run() 不会执行、请求无法被
        消费，过期后自动作废，避免残留的「仅执行今日未完成」被之后的
        手动点击静默继承。
        """
        self._requested_run_mode = self._validate_run_mode(run_mode)
        self._requested_run_mode_deadline = (
            time.monotonic() + REQUESTED_RUN_MODE_VALIDITY_SECONDS
        )

    @staticmethod
    def _validate_run_mode(run_mode: str) -> str:
        if run_mode not in _VALID_RUN_MODES:
            raise ValueError(f"unsupported daily batch run mode: {run_mode}")
        return run_mode

    def _take_run_mode(self, explicit_run_mode: str | None) -> str:
        requested = getattr(self, "_requested_run_mode", RUN_MODE_ALL)
        self._requested_run_mode = RUN_MODE_ALL
        if (
            requested != RUN_MODE_ALL
            and time.monotonic()
            > getattr(self, "_requested_run_mode_deadline", 0.0)
        ):
            requested = RUN_MODE_ALL
        return self._validate_run_mode(explicit_run_mode or requested)

    def _delay_child_schedule(self, schedule_store, child_name: str, ok: bool) -> None:
        """ALAS 式 task_delay：子任务结束后按策略推迟 next_run 并落盘。

        两种运行模式都记录；无调度策略的子任务由账本自行忽略。
        """
        if schedule_store is None:
            return
        try:
            schedule_store.delay_after_run(child_name, ok=ok)
        except Exception as exc:  # 调度账本失败不影响子任务结果
            self.log_error(f"{self.batch_label}：记录 {child_name} 的调度时间失败。", exc)

    def _auto_login_pending(self) -> bool:
        """自动登录启用且未完成时为 True。

        执行器中 onetime 出队优先于登录 trigger，且 onetime 运行期间 trigger
        不执行：手动点开始且游戏冷启动时立即跑子任务，只会在登录页/公告页上
        把主页确认烧超时并中止整批，登录完成后也没有任何机制重新拉起批次。
        """
        try:
            from src.tasks.trigger.AutoLoginTask import AutoLoginTask
        except ImportError:  # pragma: no cover - 任务注册表缺失时的极端场景
            return False
        login_task = self.executor.get_task_by_class(AutoLoginTask)
        if login_task is None:
            return False
        if not bool(getattr(login_task, "_enabled", True)):
            return False
        return not bool(getattr(login_task, "_finished", False))

    @classmethod
    def release_after_login(cls, executor) -> bool:
        """自动登录落定后放行被门控挂起的批次；返回是否有批次被放行。"""
        batch = executor.get_task_by_class(cls)
        if batch is None or not getattr(batch, "_start_after_login", False):
            return False
        batch._start_after_login = False
        batch._enabled = True
        if getattr(batch, "_requested_run_mode", RUN_MODE_ALL) != RUN_MODE_ALL:
            # A long login (patch download) must not expire "执行剩余" into
            # a full run that repeats purchases done today.
            batch._requested_run_mode_deadline = (
                time.monotonic() + REQUESTED_RUN_MODE_VALIDITY_SECONDS
            )
        if not executor.enqueue_onetime_task(batch):
            return False
        batch.log_info(f"{cls.batch_label}：自动登录已完成，开始执行。")
        return True

    def _settle_login_in_game(self) -> bool:
        """Started on an in-game page other than home: go home and let the
        pending auto-login count as done instead of waiting for a login
        screen that never comes (live 2026-09-29, started on the event page).
        """
        try:
            from src.tasks.recovery import in_game_page, recover_to_home
            from src.tasks.trigger.AutoLoginTask import AutoLoginTask
        except ImportError:  # pragma: no cover
            return False
        login_task = self.executor.get_task_by_class(AutoLoginTask)
        if login_task is None or getattr(login_task, "_state", "") not in (
            "waiting",
            "browndustx",  # also set by a pixel-only hit on dark in-game frames
        ):
            # A confirm/update/download step already seen: let login finish.
            return False
        try:
            if not in_game_page(login_task) or not recover_to_home(login_task):
                return False
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.log_error(f"{self.batch_label}：检查是否已在游戏内失败。", exc)
            return False
        return login_task.finish_in_game()

    def run(self, run_mode: str | None = None):
        if self._auto_login_pending() and not self._settle_login_in_game():
            # 门控期间不消费注入的 run_mode，放行后的正式运行再取。
            self._start_after_login = True
            self.info_set("状态", "等待自动登录完成，完成后自动开始。")
            self.log_info(f"{self.batch_label}：自动登录未完成，待登录完成后自动开始。")
            return True
        run_mode = self._take_run_mode(run_mode)
        if not getattr(self, "_resuming_after_crash", False):
            # A start by the player: the count of 闪退 restarts begins again.
            self._crash_restarts = 0
            self._done_before_crash = set()
        self._run_mode = run_mode
        self._resuming_after_crash = False
        if not bool(self.config.get("启用", True)):
            self.info_set("状态", f"{self.batch_label}已禁用。")
            return True

        # Once for the whole batch: the children then find a fixed size, or a
        # notice still within its gap.
        game_size.fix_or_warn(self)
        # The 问题摘要 record of the whole batch; its children's problems go in it.
        # ok-script's display request is given back however the run ends.
        with problem_report.run_scope(self), keep_awake.released_after(True):
            # The 跑完的结算 page reads this report; it is saved however the run
            # ends (Stop and errors included).
            self._begin_report(run_mode)
            self._report_ended = run_report.ENDED_ERROR
            try:
                if self._setup_stops():
                    return False
                return self._run_children(run_mode)
            except (TaskDisabledException, FinishedException):
                self._report_ended = run_report.ENDED_STOPPED
                self._record_stopped_progress()
                raise
            finally:
                run_report.finish(self._report_ended)

    def _setup_stops(self) -> bool:
        """One look at the game's settings before the first item (差異化點子 5).

        A reminder only (Leo 2026-10-09 「5提醒就好了」); a game set to 繁中
        cannot be read at all, so then nothing starts.
        """
        self.info_set("状态", f"{self.batch_label}：开跑前看一眼游戏设定。")
        notice = setup_check.look(self)
        if not notice:
            return False
        run_report.set_notice(notice)
        self.info_set("状态", f"{self.batch_label}中止：游戏语言要改成简体中文，没有开始跑。")
        self._report_ended = run_report.ENDED_SETUP
        return True

    def _record_stopped_progress(self) -> None:
        """Stop pressed: keep the children done so far so 继续 skips them."""
        from src.tasks.run_history import default_store

        try:
            default_store().record_stopped_batch(self)
        except Exception as exc:  # never let the record hide the Stop
            self.log_error(f"{self.batch_label}：记录停止前已完成的子任务失败。", exc)

    def _begin_report(self, run_mode: str) -> None:
        rows = []
        for child in self.child_tasks:
            if not bool(self.config.get(child.config_key, True)):
                continue
            task = self._child_task(child.task_class)
            rows.append((child.config_key, str(getattr(task, "name", None) or child.config_key)))
        run_report.begin(
            self.batch_label,
            "仅执行今日未完成" if run_mode == RUN_MODE_INCOMPLETE else "全部已启用子任务",
            rows,
        )

    # 一键日常 takes a 周常's tick away once it is done this week (weekly_ticks).
    untick_weekly_done = False

    def _sync_weekly_ticks(self, history) -> list[str]:
        if not self.untick_weekly_done:
            return []
        pairs = []
        for child in self.child_tasks:
            if child.weekly:
                task = self._child_task(child.task_class)
                name = str(getattr(task, "name", None) or child.config_key)
                pairs.append((child.config_key, name))
        if not pairs:
            return []
        changed = weekly_ticks.sync(self.config, pairs, history.last_run)
        for key in changed:
            if self.config.get(key, True):
                self.log_info(f"{self.batch_label}：{key} 新的一周，重新勾选。")
            else:
                self.log_info(f"{self.batch_label}：{key} 本周已做完，取消勾选。")
        return changed

    def _run_children(self, run_mode: str) -> bool:
        only_incomplete = run_mode == RUN_MODE_INCOMPLETE
        from src.tasks import scheduler as task_scheduler
        from src.tasks.run_history import default_store

        history = (
            default_store() if only_incomplete else None
        )
        # A 周常 done this week has had its tick taken away (and one from last
        # week gets it back); the ticks then decide, so a 周常 the player
        # ticks again runs again (Leo 2026-10-09).
        self._sync_weekly_ticks(default_store())
        schedule_store = task_scheduler.default_store()

        completed: list[str] = []
        # Read by _restart_after_crash: what the run after the restart skips.
        self._completed_keys = completed
        done_before_crash = set(getattr(self, "_done_before_crash", None) or ())
        # 运行前就已完成而跳过的子任务：关机判定不能依赖运行结束后的
        # is_completed_today 重算，否则运行跨过 08:00（UTC+8）日界后
        # 这些记录不再算「今日」，会漏关机。
        pre_completed: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        stop_remaining = False
        # Each child's own finish time: run_history stamps children with it,
        # not with the batch's end (a child done at 07:58 is yesterday's).
        self._child_finished: dict[str, float] = {}
        self._child_started: dict[str, float] = {}
        self._title_screen_hit = False
        self._game_crashed = False
        # 闪退 is only told when the game ran at the start: a game that was not
        # open (or a PC where this cannot be told) never counts as one.
        self._game_seen = game_process.game_running() is True

        def publish_outcome() -> None:
            # Live per-child progress feeds the run panel's segments and
            # cells during the run; the same keys are written once more with
            # the final values after the loop.
            self.info_set("完成", "、".join(completed) or "-")
            self.info_set("失败", "、".join(failed) or "-")
            self.info_set("跳过", "、".join(skipped) or "-")

        self.info_set("状态", f"{self.batch_label}启动。")
        self.info_set(
            "运行模式",
            "仅执行今日未完成" if only_incomplete else "全部已启用子任务",
        )

        for child in self.child_tasks:
            self._raise_if_stopped()
            if not bool(self.config.get(child.config_key, True)) or stop_remaining:
                skipped.append(child.config_key)
                publish_outcome()
                if stop_remaining:
                    run_report.row_ended(child.config_key, run_report.SKIP, self._stopped_note())
                if (
                    stop_remaining
                    and not self._resume_after_login_set()
                    and bool(self.config.get(child.config_key, True))
                ):
                    # Otherwise the auto-scheduler relaunches the aborted
                    # batch 8 s later onto the same stuck screen, over and over.
                    cut_off = self._child_task(child.task_class)
                    if cut_off is not None:
                        self._delay_child_schedule(schedule_store, str(cut_off.name), False)
                continue

            task = self._child_task(child.task_class)
            if task is None:
                failed.append(child.config_key)
                publish_outcome()
                run_report.row_ended(child.config_key, run_report.FAIL, "找不到这个任务")
                stop_remaining = True
                self.log_error(f"{self.batch_label}：未找到子任务 {child.config_key}。")
                continue

            if child.config_key in done_before_crash:
                # Done before the game closed: the run after the restart goes
                # on from where it was, in the mode the player picked.
                skipped.append(child.config_key)
                pre_completed.append(child.config_key)
                publish_outcome()
                run_report.row_ended(child.config_key, run_report.SKIP, CRASH_DONE_NOTE)
                self.log_info(f"{self.batch_label}：{child.config_key} 闪退前已做完，跳过。")
                continue

            if history is not None and self._completed_this_period(history, str(task.name)):
                skipped.append(child.config_key)
                pre_completed.append(child.config_key)
                publish_outcome()
                run_report.row_ended(child.config_key, run_report.SKIP, self.period_done_note)
                self.log_info(f"{self.batch_label}：{child.config_key} 本期已完成，跳过。")
                continue

            if only_incomplete and not schedule_store.is_due(str(task.name)):
                remaining = schedule_store.backoff_remaining_minutes(str(task.name))
                skipped.append(child.config_key)
                publish_outcome()
                run_report.row_ended(
                    child.config_key,
                    run_report.SKIP,
                    f"上次失败，约 {remaining:.0f} 分钟后再试",
                )
                self.log_info(
                    f"{self.batch_label}：{child.config_key} 调度未到期"
                    f"（约 {remaining:.0f} 分钟后可执行），跳过。"
                )
                continue

            if self._game_closed():
                # Closed after the last child ended: nothing to run it on.
                stop_remaining = True
                self._restart_after_crash()
                skipped.append(child.config_key)
                publish_outcome()
                run_report.row_ended(child.config_key, run_report.SKIP, self._stopped_note())
                continue

            self.info_set("当前子任务", child.config_key)
            self.log_info(f"{self.batch_label}：开始 {child.config_key}。")
            self._child_started[child.config_key] = time.time()
            run_report.row_started(child.config_key)
            original_config = task.config
            try:
                # The switches on this card are authoritative for this run. Keep
                # the child task's persisted configuration unchanged while making
                # its own top-level 启用 gate transparent to the batch runner.
                # 执行剩余 also tells the child to skip its own finished parts
                # (trade phases); a full run redoes everything (user,
                # 2026-09-27: "我選擇再點一次就應該再做一次").
                task.config = ChainMap(
                    {"启用": True, ONLY_INCOMPLETE_KEY: only_incomplete},
                    original_config or {},
                )
                task.info_clear()
                with suppress_task_completion_notifications(task):
                    child_ok = bool(task.run())
                    self._raise_if_stopped()
                    self._child_finished[child.config_key] = time.time()
                    if child_ok:
                        completed.append(child.config_key)
                        publish_outcome()
                        run_report.row_ended(child.config_key, run_report.DONE)
                        self.log_info(f"{self.batch_label}：{child.config_key} 完成。")
                        self._delay_child_schedule(schedule_store, str(task.name), True)
                        if child.weekly and self.untick_weekly_done:
                            weekly_ticks.mark_done(
                                self.config,
                                child.config_key,
                                self._child_finished[child.config_key],
                            )
                    else:
                        failed.append(child.config_key)
                        publish_outcome()
                        crashed = self._game_closed()
                        run_report.row_ended(
                            child.config_key,
                            run_report.FAIL,
                            CRASH_NOTE if crashed else failure_note(task),
                        )
                        stop_remaining = self._after_child_failed(
                            task, child, schedule_store, crashed
                        )
            except (TaskDisabledException, FinishedException):
                # Stop pressed (or the app finishing): never treat it as a
                # child failure, or 失败后继续 would recover and carry on.
                raise
            except Exception as exc:
                self._raise_if_stopped()
                self._child_finished[child.config_key] = time.time()
                failed.append(child.config_key)
                publish_outcome()
                crashed = self._game_closed()
                run_report.row_ended(
                    child.config_key, run_report.FAIL, CRASH_NOTE if crashed else "程序出错"
                )
                self.log_error(f"{self.batch_label}：{child.config_key} 异常。", exc)
                stop_remaining = self._after_child_failed(task, child, schedule_store, crashed)
            finally:
                task.config = original_config
                self.executor.reset_scene(check_enabled=False)

        self.info_set("当前子任务", "-")
        publish_outcome()
        if self._game_crashed:
            # The status says whether the game is being opened again.
            self._report_ended = run_report.ENDED_ABORTED
            return False
        if failed:
            # 中止 only when the batch really stopped early; with 失败后继续 it
            # ran to the end, and "中止" made users think it broke (2026-09-27).
            if stop_remaining:
                self.info_set("状态", f"{self.batch_label}中止。")
                self._report_ended = run_report.ENDED_ABORTED
            else:
                self.info_set("状态", f"{self.batch_label}完成（{len(failed)}项失败）。")
                self._report_ended = run_report.ENDED_FAILED
            return False

        self.info_set("状态", f"{self.batch_label}完成。")
        self._report_ended = run_report.ENDED_DONE
        log_task_completion(
            self,
            f"{self.batch_label}完成：已执行 {len(completed)} 项，跳过 {len(skipped)} 项。",
        )
        self._maybe_shutdown_after_daily(completed, pre_completed)
        return True

    period_done_note = "今天已经做完"

    @staticmethod
    def _completed_this_period(history, task_name: str) -> bool:
        return history.is_completed_today(task_name)

    def _stopped_note(self) -> str:
        if self._game_crashed:
            if self._resume_after_login_set():
                return "游戏闪退了，重新打开后再跑"
            return "游戏一直闪退，先停下来"
        if self._title_screen_hit:
            return "游戏回到了标题画面，登录后再跑"
        if not bool(self.config.get("失败后继续", True)):
            return "前面有一项失败，设定是失败就停"
        return "前面有一项失败且回不到主页，没有跑"

    def _note_recovery(self, child: DailyBatchChild, stopped: bool) -> None:
        if self._game_crashed:
            if self._resume_after_login_set():
                run_report.add_note(child.config_key, "重新打开游戏，登录后接着跑")
            else:
                run_report.add_note(child.config_key, "游戏一直闪退，先停下来")
        elif self._title_screen_hit:
            run_report.add_note(child.config_key, "游戏回到了标题画面")
        elif stopped and bool(self.config.get("失败后继续", True)):
            run_report.add_note(child.config_key, "回不到主页，后面的停了")
        elif not stopped:
            run_report.add_note(child.config_key, "已回主页")

    def _child_task(self, task_class):
        """The registered instance of exactly ``task_class``.

        ``get_task_by_class`` is an isinstance lookup: JunkGearTask and
        CraftGearTask subclass DailyRefineTask, so asking for the refine task
        could return one of them if the registration order changed.
        """

        executor = self.executor
        for task in (
            list(getattr(executor, "onetime_tasks", None) or [])
            + list(getattr(executor, "trigger_tasks", None) or [])
        ):
            if type(task) is task_class:
                return task
        return executor.get_task_by_class(task_class)

    def _raise_if_stopped(self) -> None:
        """Honour Stop even when a child swallowed it.

        ok-script clears the executor's current task before raising
        TaskDisabledException, so a child that catches it with a broad
        ``except Exception`` leaves later sleeps unaware of the Stop; the
        batch's own flag still records it (review 2026-09-26).
        """

        if not getattr(self, "_enabled", True):
            raise TaskDisabledException()

    def _resume_after_login_set(self) -> bool:
        """This run ends early and runs again (what is left) after a login."""
        return bool(getattr(self, "_start_after_login", False)) and (
            self._title_screen_hit or self._game_crashed
        )

    def _after_child_failed(self, task, child: DailyBatchChild, schedule_store, crashed) -> bool:
        """After a child failed: True when the children after it must stop."""
        if crashed:
            # Not the child's fault: no failure wait, so the run after the
            # restart does it again.
            stopped = True
            self._restart_after_crash()
        else:
            self._delay_child_schedule(schedule_store, str(task.name), False)
            stopped = not self._continue_after_failure(task, child)
        self._note_recovery(child, stopped)
        return stopped

    def _game_closed(self) -> bool:
        """The game ran when this run started and is gone now (闪退)."""
        if self._game_crashed or not getattr(self, "_game_seen", False):
            return self._game_crashed
        return game_process.game_running() is False

    def _restart_after_crash(self) -> bool:
        """The game closed by itself (Leo 2026-10-09): open it again, log in,
        then go on from where it was.  True when the restart is on its way.

        At most ``CRASH_RESTARTS_MAX`` times for one start by the player; the
        run after the login comes back here if the game closes again.
        """
        self._game_crashed = True
        restarts = int(getattr(self, "_crash_restarts", 0) or 0)
        if restarts >= CRASH_RESTARTS_MAX:
            self.info_set("状态", "游戏一直闪退，先停下来。")
            self.log_warning(
                f"{self.batch_label}：游戏又闪退了（已重新打开 {restarts} 次），先停下来。"
            )
            return False
        if not self._arm_login_after_crash():
            self.log_warning(f"{self.batch_label}：游戏闪退了，找不到自动登录，没有重新打开。")
            return False
        self._crash_restarts = restarts + 1
        self._resuming_after_crash = True
        self._start_after_login = True
        # The mode the player picked, not 跑没跑完的: a 跑勾选的 run must not
        # skip ticked items done earlier today (live 2026-10-10).  Only what
        # this run finished before the game closed is skipped.
        self._done_before_crash = set(getattr(self, "_done_before_crash", None) or ()) | set(
            getattr(self, "_completed_keys", None) or ()
        )
        self.request_run_mode(getattr(self, "_run_mode", None) or RUN_MODE_INCOMPLETE)
        self.info_set("状态", "游戏闪退了，重新打开游戏，登录后接着跑没做完的。")
        self.log_warning(
            f"{self.batch_label}：游戏闪退了，重新打开游戏，登录后接着跑没做完的"
            f"（第 {self._crash_restarts} 次）。"
        )
        self._open_game()
        return True

    def _arm_login_after_crash(self) -> bool:
        """Log in after the restart, even with 自动登录游戏 off: for this
        run only, as a run on the 桌面分身 does (the setting is not saved)."""
        try:
            from src.tasks.trigger.AutoLoginTask import AutoLoginTask
        except ImportError:  # pragma: no cover
            return False
        login = self.executor.get_task_by_class(AutoLoginTask)
        if login is None:
            return False
        login._enabled = True
        reset = getattr(login, "_reset_login_state", None)
        if callable(reset):
            reset("游戏闪退后重新打开，自动登录。")
        else:
            login._finished = False
        return True

    def _open_game(self) -> None:
        """Start the game the way a start does when it is closed; the
        auto-login then logs in and lets this batch run again."""
        try:
            from ok import og

            og.app.start_controller.start(None)
        except Exception as exc:
            self.log_error(f"{self.batch_label}：重新打开游戏失败。", exc)

    def _continue_after_failure(self, task, child: DailyBatchChild) -> bool:
        """Return True when the batch may go on after ``child`` failed."""
        if not bool(self.config.get("失败后继续", True)):
            self.log_warning(f"{self.batch_label}：{child.config_key} 失败，停止后续子任务。")
            return False
        if self._recover_home(task):
            self.log_warning(
                f"{self.batch_label}：{child.config_key} 失败，已回到主页，继续后续子任务。"
            )
            return True
        if getattr(task, "_recovery_saw_title", False) and self._auto_login_pending():
            # Back on the title screen: once auto-login reaches home it
            # re-queues this batch, which then runs only what is left.
            self._title_screen_hit = True
            self._start_after_login = True
            self.request_run_mode(RUN_MODE_INCOMPLETE)
            self.log_warning(
                f"{self.batch_label}：游戏回到了标题画面，自动登录后继续执行未完成的子任务。"
            )
            return False
        self.log_warning(
            f"{self.batch_label}：{child.config_key} 失败且无法确认回到主页，停止后续子任务。"
        )
        return False

    @staticmethod
    def _recover_home(task) -> bool:
        from src.tasks.BaseBD2Task import BaseBD2Task

        if not isinstance(task, BaseBD2Task):
            return False
        from src.tasks.recovery import recover_to_home

        try:
            return recover_to_home(task)
        except (TaskDisabledException, FinishedException):
            raise
        except Exception:
            return False

    def _maybe_shutdown_after_daily(
        self,
        completed: list[str],
        pre_completed: list[str] | tuple[str, ...] = (),
    ) -> None:
        """全部已启用子任务今日均已完成时按配置执行倒计时关机。

        「今日已完成」= 本轮运行完成（账本记录在 task_done 时才落盘，此刻
        还查不到，故并上 ``completed``）、运行前已有今日完成记录
        （``pre_completed``，由 run() 循环即时采集）或判定时刻的历史记录；
        任一已启用子任务两者皆不满足（含调度未到期跳过）时不关机。
        没有任何已启用子任务时不关机：全称判定对空集合为真，但一次没有
        执行任何日常的成功运行不应触发关机。
        """
        if not bool(self.config.get("完成日常后自动关机", False)):
            return
        enabled_children = [
            child
            for child in self.child_tasks
            if bool(self.config.get(child.config_key, True))
        ]
        if not enabled_children:
            self.log_info(f"{self.batch_label}：没有已启用子任务，不执行自动关机。")
            return
        from src.tasks.run_history import default_store

        history = default_store()
        for child in enabled_children:
            if child.config_key in completed or child.config_key in pre_completed:
                continue
            task = self._child_task(child.task_class)
            name = str(getattr(task, "name", None) or child.config_key)
            if child.weekly and history.is_completed_this_week(name):
                continue
            if not history.is_completed_today(name):
                self.log_info(
                    f"{self.batch_label}：{child.config_key} 今日未完成，不执行自动关机。"
                )
                return
        try:
            scheduled = _schedule_system_shutdown(SHUTDOWN_COUNTDOWN_SECONDS)
        except (OSError, subprocess.SubprocessError) as exc:
            self.log_error(f"{self.batch_label}：自动关机调用失败。", exc)
            return
        if not scheduled:
            self.log_error(f"{self.batch_label}：系统拒绝了自动关机计划，本次关机未执行。")
            return
        self.info_set(
            "状态", f"今日日常已全部完成，{SHUTDOWN_COUNTDOWN_SECONDS} 秒后自动关机。"
        )
        self.log_info(
            f"{self.batch_label}：今日日常已全部完成，{SHUTDOWN_COUNTDOWN_SECONDS} 秒后"
            "自动关机；取消请在命令行执行 shutdown /a。",
            notify=True,
        )


class DailyBatchTask(ChildBatchTask):
    """一键完成日常."""

    untick_weekly_done = True

    def load_config(self):
        # The 周常 switches used to live on 一键完成周常: keep what the player set.
        own = _read_json(_config_file(self.__class__.__name__))
        weekly = _read_json(_config_file(WeeklyBatchTask.__name__))
        super().load_config()
        for child in self.child_tasks:
            key = child.config_key
            if child.weekly and key not in own and isinstance(weekly.get(key), bool):
                self.config[key] = weekly[key]


def _config_file(name: str):
    from pathlib import Path

    from ok.util.config import Config
    from ok.util.file import get_relative_path

    return Path(get_relative_path(Config.config_folder, f"{name}.json"))


def _read_json(path) -> dict:
    import json

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


WEEKLY_BATCH_CHILDREN = tuple(child for child in DAILY_BATCH_CHILDREN if child.weekly)


class WeeklyBatchTask(ChildBatchTask):
    """一键完成周常: weekly chores, skipped once done in the current game week.

    No longer registered (Leo 2026-10-09: 一键日常 runs the 周常 too); kept so
    old saved runs, its config file and the auto-login gate still resolve.
    """

    batch_label = "一键完成周常"
    child_tasks = WEEKLY_BATCH_CHILDREN

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.description = (
            "按顺序执行已开启的周常：浏览街机菜单、小屋增加人气、制作装备、末日之书。"
        )
        self.icon = FluentIcon.DATE_TIME
        # Shutdown and auto-run on open are daily-batch features.
        for key in ("完成日常后自动关机", "打开工具时自动开始"):
            self.default_config.pop(key, None)
            self.config_description.pop(key, None)

    period_done_note = "本周已经做完"

    @staticmethod
    def _completed_this_period(history, task_name: str) -> bool:
        return history.is_completed_this_week(task_name)
