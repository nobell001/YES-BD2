"""匿名上传完整记录（Leo 2026-11-05「他要在那次的錯誤報告點匿名上傳」
「可以複製圖片 圖片裡面有代號 讓我能填就好」）。

玩家多半只在留言区贴截图，完整记录贴不进去；在回报页按复制图片／保存
图片／复制文字时，这一次的记录先打包送到作者的上传站，拿回一个 6 码代号。
代号写进问题摘要图片和文字，作者就能用代号看到全部内容。

只有玩家在回报页按下按钮才连网，一次只送那一笔，同一笔只送一次；跑的
时候从不上传。
包里有：问题摘要的资料（report.json）、这次运行的完整记录（log.txt）、
停下前的游戏画面和前几秒的小图、问题摘要图片。没有账号名称（换成
「账号 N」）、电脑用户名称、资料夹路径。
"""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# The upload station is not set up yet (Leo 2026-11-05 「上傳站下次再做了」).
# While URL is empty the report page's buttons work as before: no network,
# no code, the old note.  Set URL = STATION_URL once the station runs.
STATION_URL = "https://report.yesbd2.cc.cd/upload"
URL = ""
TIMEOUT = 30  # s; the player waits on it before the picture is copied
# The upload station takes at most this much; the summary picture is left
# out first, then the small frames, when a bundle is bigger.
MAX_BYTES = 4 * 1024 * 1024
CODE = re.compile(r"^[2-9A-HJ-NP-Z]{6}$")
CODE_KEY = "upload_code"

NO_NETWORK = "连不上上传站，请检查网络后再按一次"
TOO_BIG = "这次的记录太大，没能上传"
SERVER_SAID = "上传站没收下：{message}"
NOTHING = "这一次没有可以上传的记录"

# Paths in a loaded record that point into this PC; the bundle carries the
# files themselves instead.
_LOCAL_KEYS = ("path", "frame_path", "log_path", "before_paths")


# ------------------------------------------------------------------ privacy


def _account_names() -> list[tuple[str, str]]:
    """(name, 「账号 N」) for every account the player named."""
    try:
        from src.utils import accounts

        rows = accounts.accounts()
    except Exception:
        return []
    found = []
    for index, account in enumerate(rows, 1):
        name = str(getattr(account, "name", "") or "").strip()
        if len(name) >= 2:  # one letter would blank every word that has it
            found.append((name, f"账号 {index}"))
    found.sort(key=lambda pair: len(pair[0]), reverse=True)
    return found


def anonymize(text: str, names: list[tuple[str, str]] | None = None) -> str:
    """No Windows user name, no account name."""
    from src.tasks.problem_report import scrub

    text = scrub(text)
    for name, label in _account_names() if names is None else names:
        text = text.replace(name, label)
    return text


# ------------------------------------------------------------------ bundle


def _read(path) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except (OSError, TypeError):
        return None


def jpeg(image) -> bytes | None:
    """A QImage as JPEG bytes (a PNG with frames is several MB)."""
    try:
        from PySide6.QtCore import QBuffer, QIODevice

        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, "JPG", 85):
            return None
        return bytes(buffer.data())
    except Exception:
        return None


def _picture(record: dict) -> bytes | None:
    try:
        from src.ui.shell import problem_image

        return jpeg(problem_image.render(record))
    except Exception:
        return None


def bundle(record: dict, names: list[tuple[str, str]] | None = None, picture=_picture) -> bytes | None:
    """The zip that goes up: report.json, log.txt, frames, summary.jpg."""
    from src.ui.shell import problem_image

    names = _account_names() if names is None else names
    data = {key: value for key, value in record.items() if key not in _LOCAL_KEYS}
    data.pop(CODE_KEY, None)
    report = anonymize(json.dumps(data, ensure_ascii=False, indent=1), names).encode("utf-8")
    log = problem_image.full_log_text(record)
    if log is None:
        log = problem_image.summary_text(record) + "\n"
    files = [("report.json", report), ("log.txt", anonymize(log, names).encode("utf-8"))]
    frame = _read(record.get("frame_path")) if record.get("frame_path") else None
    if frame:
        files.append(("frame" + Path(record["frame_path"]).suffix, frame))
    small = []
    for index, item in enumerate(record.get("before_paths") or [], 1):
        raw = _read(item.get("path"))
        if raw:
            small.append((f"before-{index}{Path(item['path']).suffix}", raw))
    shot = picture(record)
    extra = [small, [("summary.jpg", shot)] if shot else []]
    # Biggest optional part first out until it fits.
    for keep in (2, 1, 0):
        parts = files + [entry for group in extra[:keep] for entry in group]
        packed = _zip(parts)
        if len(packed) <= MAX_BYTES:
            return packed
    return None


def _zip(parts) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in parts:  # report.json first: the station checks it
            archive.writestr(name, raw)
    return out.getvalue()


# ------------------------------------------------------------------ upload


def enabled() -> bool:
    """The upload station is set up (see URL)."""
    return bool(URL)


def upload(
    record: dict, opener=urllib.request.urlopen, version: str = "", picture=_picture
) -> tuple[str, str]:
    """(code, "") when the station took it, else ("", why not in player words).

    ``picture(record) -> bytes`` gives the summary picture; the page renders
    it on the window's thread and passes it in, since this runs beside it.
    """
    if not record or not enabled():
        return "", NOTHING
    try:
        packed = bundle(record, picture=picture)
    except Exception:
        return "", NOTHING
    if packed is None:
        return "", TOO_BIG
    # As base64 text: the station only checks and forwards it (tools/report-station).
    request = urllib.request.Request(
        URL,
        data=base64.b64encode(packed),
        method="POST",
        headers={
            "Content-Type": "text/plain; charset=ascii",
            "User-Agent": f"YES-BD2/{version or _version()}",
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
        if exc.code == 413:
            return "", TOO_BIG
        if not raw:
            return "", NO_NETWORK
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return "", NO_NETWORK
    try:
        reply = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return "", NO_NETWORK
    code = str((reply or {}).get("code") or "") if isinstance(reply, dict) else ""
    if CODE.match(code):
        remember(record, code)
        return code, ""
    message = str((reply or {}).get("error") or "") if isinstance(reply, dict) else ""
    return "", SERVER_SAID.replace("{message}", message[:60]) if message else NO_NETWORK


def remember(record: dict, code: str) -> None:
    """The code goes in the record (and its file), so the picture shows it later."""
    record[CODE_KEY] = code
    path = record.get("path")
    if not path:
        return
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        saved[CODE_KEY] = code
        Path(path).write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass


def _version() -> str:
    try:
        from src.config import config

        return str(config.get("version") or "")
    except Exception:
        return ""
