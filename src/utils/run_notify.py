"""跑完通知：一键完成日常跑完，把结果发到玩家自己的微信（Leo 2026-10-22）。

经 Server酱（sct.ftqq.com，Leo 选的）：玩家用微信扫码登录、复制自己的
SendKey，贴进「设置」。默认关闭；开着才会在跑完时送出一则，工具从不读网页。
免费版每人每天 5 则，一键日常跑一次只用 1 则；手动停止的不发（人就在电脑前）。

隐私：消息只有游戏日、完成/失败/跳过几项、失败的项目和原因、用时、账号编号
（有几个账号时）和版本号；没有账号名称、电脑用户名称、资料夹或截图。SendKey
只存在这台电脑的 configs/run_notify.json。
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ok import Logger

logger = Logger.get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
# Shared by every account and by the tool in 桌面分身 (same configs folder).
SETTINGS_FILE = ROOT / "configs" / "run_notify.json"
ON_KEY = "on"
SENDKEY_KEY = "sendkey"
LAST_AT_KEY = "last_at"
LAST_ERROR_KEY = "last_error"

SITE = "https://sct.ftqq.com/sendkey"
TIMEOUT = 15  # s; it runs beside the tool, never holds a run up
TITLE_MAX = 32  # Server酱: 标题最长 32 字
FREE_PER_DAY = 5

# Server酱 Turbo keys start with SCT; Server酱³ keys are sctp<uid>t… and go to
# their own host (the official SDKs do the same).
_TURBO = re.compile(r"^SCT[0-9A-Za-z]{6,}$")
_SC3 = re.compile(r"^sctp(\d+)t[0-9A-Za-z]{4,}$")

NO_NETWORK = "网络连不上 Server酱，看看电脑有没有连网"
BAD_KEY = "SendKey 不对，请重新复制贴上"
BAD_SHAPE = "SendKey 格式不对：要贴 SCT 开头的那一串"
OUT_OF_QUOTA = "今天的免费次数用完了（每天 5 则），明天会恢复"
SERVER_SAID = "Server酱 回复：{message}"

TEST_TITLE = "YES-BD2 测试"
TEST_BODY = "收到这则，跑完通知就设定好了。"


# ------------------------------------------------------------------ settings


def _read() -> dict:
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _write(saved: dict) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning(f"run notify: not saved ({exc})")


def enabled() -> bool:
    return bool(_read().get(ON_KEY, False))


def set_enabled(on: bool) -> None:
    saved = _read()
    saved[ON_KEY] = bool(on)
    _write(saved)


def sendkey() -> str:
    return str(_read().get(SENDKEY_KEY) or "")


def set_sendkey(key: str) -> None:
    saved = _read()
    key = clean(key)
    if key != saved.get(SENDKEY_KEY):
        saved[SENDKEY_KEY] = key
        saved.pop(LAST_AT_KEY, None)
        saved.pop(LAST_ERROR_KEY, None)
    _write(saved)


def last_result() -> tuple[float | None, str]:
    """When the last message went out (or was tried) and why it failed ("" = sent)."""
    saved = _read()
    at = saved.get(LAST_AT_KEY)
    return (float(at) if isinstance(at, (int, float)) else None), str(
        saved.get(LAST_ERROR_KEY) or ""
    )


def _record(error: str) -> None:
    saved = _read()
    saved[LAST_AT_KEY] = time.time()
    saved[LAST_ERROR_KEY] = error
    _write(saved)


# ------------------------------------------------------------------ the key


def clean(key: str) -> str:
    """What the player pasted, without spaces, quotes or a whole send address."""
    text = str(key or "").strip().strip("\"'“”‘’").strip()
    found = re.search(r"(sctp\d+t[0-9A-Za-z]+|SCT[0-9A-Za-z]+)", text)
    return found.group(1) if found else re.sub(r"\s+", "", text)


def valid(key: str) -> bool:
    return endpoint(key) is not None


def endpoint(key: str) -> str | None:
    key = clean(key)
    sc3 = _SC3.match(key)
    if sc3:
        return f"https://{sc3.group(1)}.push.ft07.com/send/{key}.send"
    if _TURBO.match(key):
        return f"https://sctapi.ftqq.com/{key}.send"
    return None


def masked(key: str) -> str:
    """SCT12…9xQ: enough to recognise it, not enough to use it."""
    key = clean(key)
    return f"{key[:5]}…{key[-3:]}" if len(key) > 10 else key


# ------------------------------------------------------------------ sending


def _text(template: str, **values) -> str:
    from src.ui.traditional import ui_text

    return ui_text(template).format(**values)


def send(key: str, title: str, body: str, opener=urllib.request.urlopen) -> str:
    """Send one message; "" when Server酱 took it, else why not (player words)."""
    url = endpoint(key)
    if url is None:
        return BAD_SHAPE
    data = urllib.parse.urlencode({"title": title[:TITLE_MAX], "desp": body, "noip": 1}).encode(
        "utf-8"
    )
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "YES-BD2",
        },
    )
    try:
        with opener(request, timeout=TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        if not raw:
            return BAD_KEY if exc.code in (401, 403, 404) else NO_NETWORK
    except (urllib.error.URLError, OSError, TimeoutError):
        return NO_NETWORK
    try:
        reply = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return NO_NETWORK
    if not isinstance(reply, dict):
        return NO_NETWORK
    code = reply.get("code", reply.get("errno"))
    if code in (0, "0"):
        return ""
    message = str(reply.get("message") or reply.get("info") or reply.get("error") or code)
    lowered = message.lower()
    if any(word in lowered for word in ("超过", "次数", "limit", "quota")):
        return OUT_OF_QUOTA
    if any(word in lowered for word in ("key", "token", "不存在", "无效", "错误")):
        return BAD_KEY
    return SERVER_SAID.replace("{message}", message[:80])


def send_test(key: str, opener=urllib.request.urlopen) -> str:
    """The 发测试 button: one short message, its result remembered like a run's."""
    error = send(key, _text(TEST_TITLE), _text(TEST_BODY), opener)
    _record(error)
    return error


# ------------------------------------------------------------------ summary


def _version() -> str:
    try:
        from src.config import runtime_version

        return str(runtime_version())
    except Exception:
        return ""


def _account_line() -> str:
    """The account's number when there are several; never its name."""
    try:
        from src.utils import accounts

        if accounts.has_several():
            return _text("账号 {n}", n=accounts.current().number)
    except Exception:
        pass
    return ""


def _scrub(text: str) -> str:
    from src.tasks.problem_report import scrub

    return scrub(text)


def _started(report: dict) -> bool:
    """False for a report 定时启动 wrote when the run never got going (no rows)."""
    return bool(report.get("rows"))


def summary(report: dict) -> tuple[str, str]:
    """(title, Markdown body) of a finished 一键完成日常 report."""
    from src.tasks import run_report

    rows = report.get("rows") or []
    done = [row for row in rows if row.get("state") == run_report.DONE]
    failed = [row for row in rows if row.get("state") == run_report.FAIL]
    skipped = [row for row in rows if row.get("state") in (run_report.SKIP, run_report.WAIT)]
    # The game day (08:00 game time), like the rest of the tool.
    day = run_report.game_day_key(report.get("started") or None)[5:].replace("-", "/")
    ended = report.get("ended")
    if ended == run_report.ENDED_SETUP or not _started(report):
        title = _text("日常 {day}：没有开始跑", day=day)
    elif ended in (run_report.ENDED_ABORTED, run_report.ENDED_ERROR):
        title = _text("日常 {day}：中途停了", day=day)
    elif failed:
        title = _text("日常 {day}：{n} 项失败", day=day, n=len(failed))
    else:
        title = _text("日常 {day}：全部完成", day=day)
    title = f"YES-BD2 {title}"[:TITLE_MAX]

    lines = []
    if rows:
        counts = [_text("完成 {n} 项", n=len(done))]
        if failed:
            counts.append(_text("失败 {n} 项", n=len(failed)))
        if skipped:
            counts.append(_text("跳过 {n} 项", n=len(skipped)))
        lines.append(" · ".join(counts))
    for row in failed:
        name = _text(str(row.get("name") or row.get("key") or ""))
        note = _scrub(_text(str(row.get("note") or "")))
        lines.append(f"- ✗ **{name}**" + (f"：{note}" if note else ""))
    notice = _scrub(_text(str(report.get("notice") or "")))
    if notice:
        lines.append(notice)
    minutes = 0
    if report.get("started") and report.get("finished"):
        minutes = max(1, round((float(report["finished"]) - float(report["started"])) / 60))
    tail = [_text("用时 {n} 分钟", n=minutes)] if minutes else []
    account = _account_line()
    if account:
        tail.append(account)
    version = _version()
    if version:
        tail.append(f"YES-BD2 {version}")
    if tail:
        lines.append(" · ".join(tail))
    return title, "\n\n".join(lines)


LOGIN_STUCK = "登录卡住了，游戏一直没进到主页，一键日常没有开始跑。请看一下游戏画面"
# Game day a problem before the run was already sent for (once a day is enough).
_problem_day: str | None = None
# The same, kept in the settings file: the tool in the 桌面分身 and the one on
# the desktop are two processes, and either may say it (Leo 2026-11-16 「微信
# 通知 一樣要通知」, without the same news twice).
PROBLEM_DAY_KEY = "problem_day"


def _problem_said(day_key: str) -> bool:
    return _problem_day == day_key or _read().get(PROBLEM_DAY_KEY) == day_key


def after_problem(why: str, start=None) -> bool:
    """Something kept 一键完成日常 from starting at all (login stuck, …): with no
    run there is no report, so say why on its own (Leo 2026-10-22 「有問題也要說」)."""
    global _problem_day
    from src.tasks import run_report

    day_key = run_report.game_day_key()
    if _problem_said(day_key) or not enabled():
        return False
    key = sendkey()
    if not valid(key):
        return False
    _problem_day = day_key
    saved = _read()
    saved[PROBLEM_DAY_KEY] = day_key
    _write(saved)
    day = day_key[5:].replace("-", "/")

    def go() -> None:
        try:
            title = f"YES-BD2 {_text('日常 {day}：没有开始跑', day=day)}"[:TITLE_MAX]
            tail = [part for part in (_account_line(), f"YES-BD2 {_version()}") if part]
            body = "\n\n".join([f"- ✗ {_scrub(_text(why))}", " · ".join(tail)])
            error = send(key, title, body)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        _record(error)
        if error:
            logger.warning(f"run notify: problem not sent ({error})")

    if start is None:
        threading.Thread(target=go, name="RunNotify", daemon=True).start()
    else:
        start(go)
    return True


def after_run(report: dict | None, start=None) -> bool:
    """Called when 一键完成日常 ends; sends beside the tool when it is switched on.

    Returns whether a message was started.  ``start`` runs the sending
    (tests pass one that runs it at once).
    """
    from src.tasks import run_report

    if not report or report.get("ended") == run_report.ENDED_STOPPED:
        return False
    if (
        not _started(report)
        and not report.get("maintenance")
        and _problem_said(run_report.game_day_key())
    ):
        # after_problem already said why today; 游戏维护 is its own news
        # (定时启动 writes that report when the login screen says 维护).
        return False
    if not enabled():
        return False
    key = sendkey()
    if not valid(key):
        logger.warning("run notify: on, but no usable SendKey")
        return False

    def go() -> None:
        try:
            title, body = summary(report)
            error = send(key, title, body)
        except Exception as exc:  # never let the message break anything
            error = str(exc) or type(exc).__name__
        _record(error)
        if error:
            logger.warning(f"run notify: not sent ({error})")
        else:
            logger.info("run notify: sent")

    if start is None:
        threading.Thread(target=go, name="RunNotify", daemon=True).start()
    else:
        start(go)
    return True
