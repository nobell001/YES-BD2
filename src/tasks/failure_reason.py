"""Every failure says why (Leo 2026-10-10).

Leo 05:52Z: 「以後有失敗 盡量原因要寫」.  At 08:39Z he added 「你應該確保你的log是有用的了吧
很多次用戶傳過來都沒有用」, after a player's 问题摘要 said only 「普通战斗失败」.

Many tasks end a failed step with 「<task>：<step>失败。」.  That names the step
but not what went wrong.  When such a run returns False, ``ensure`` adds the
reason before the 问题摘要 keeps the moment.  The reason is the one the task
noted (``task._why``), else its last log line of this run, which says what it
waited for or read.  The 状态 line, the 当前阶段 the summary shows as 「停在」
and the 结算 page's note then all carry it.
"""

from __future__ import annotations

import logging
import re
import threading

from src.tasks import problem_report

# Nothing written at all: the frame in the summary is all there is.
NO_REASON = "原因没有记录到，请看摘要里的游戏画面"
REASON_LIMIT = 60
# Going home after the failure is not why it failed.
_AFTER_FAILURE = ("恢复主页", "失败后")
_EMPTY_STATUS = {"", "-", "启动", "开始", "运行中"}
_PUNCTUATION = "：:。.，, "


def _strip_name(text: str, name: str) -> str:
    text = str(text or "").strip()
    if name and text.startswith(name):
        text = text[len(name):].lstrip(_PUNCTUATION)
    return text


def has_reason(status: str, name: str = "") -> bool:
    """「打开邮箱失败：等了15秒…」 has one; 「打开邮箱失败。」 does not."""
    text = _strip_name(status, name).rstrip(_PUNCTUATION)
    if "失败" not in text:
        return False
    after = text.rsplit("失败", 1)[1].strip(_PUNCTUATION)
    return bool(re.search(r"[一-鿿A-Za-z0-9]", after))


def _cause_line(task, since: float, status: str) -> str:
    """The task's last log line of this run that is not the failure line itself."""
    name = str(getattr(task, "name", "") or "")
    plain = _strip_name(status, name).rstrip(_PUNCTUATION)
    for _at, _level, text in reversed(
        problem_report.recent_lines(since, threading.get_ident())
    ):
        line = _strip_name(text, name).rstrip(_PUNCTUATION)
        if not line or line.startswith(_AFTER_FAILURE):
            continue
        if plain and (line == plain or line.startswith(plain)):
            continue
        return line
    return ""


def reason_for(task, since: float, status: str) -> str:
    why = str(getattr(task, "_why", "") or "").strip().rstrip(_PUNCTUATION)
    if why:
        return why[:REASON_LIMIT]
    line = _cause_line(task, since, status)
    return line[:REASON_LIMIT] if line else NO_REASON


def ensure(task, since: float, status_before: str | None = None) -> str:
    """Give a failed run's 状态 a reason; return the failure text, without the name.

    ``since`` is the run's start (time.time()); ``status_before`` its 状态
    before the run, so an old line is not taken for this run's failure.
    Only a 状态 that already says 失败 is rewritten: run_history reads that
    word, and a run it counts as done must stay so.  Otherwise the reason
    goes to 当前阶段 alone, which the summary shows as 「停在」.  Never raises:
    the reason must not break the run it explains.
    """
    try:
        return _ensure(task, since, status_before)
    except Exception:
        logging.getLogger("ok").exception("失败原因整理出错")
        return ""


def _ensure(task, since: float, status_before: str | None) -> str:
    from src.tasks.BaseBD2Task import task_info_snapshot

    name = str(getattr(task, "name", "") or "")
    status = str(task_info_snapshot(task).get("状态") or "").strip()
    if status_before is not None and status == str(status_before or "").strip():
        status = ""
    plain = _strip_name(status, name).rstrip(_PUNCTUATION)
    if has_reason(status, name):
        text = plain
    elif "失败" in plain:
        text = f"{plain}：{reason_for(task, since, status)}"
        task.info_set("状态", f"{name}：{text}。" if name else f"{text}。")
        warn = getattr(task, "log_warning", None)
        if callable(warn):
            warn(f"{name}：{text}。" if name else f"{text}。")
    elif plain in _EMPTY_STATUS:
        text = f"失败：{reason_for(task, since, status)}"
    else:
        text = f"{plain}，失败：{reason_for(task, since, status)}"
    task.info_set("当前阶段", text)
    return text
