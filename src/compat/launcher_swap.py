"""把已安装的旧启动器换成我们的新版，玩家不用重新安装（Leo, 2026-10-09）。

旧启动器只会更新工具，换不了自己的 exe。ok-script 原本的 update_pyappify
在工具里开背景线程下载，工具一关就取消（4K 实测：工具开 4 秒就关，
下载被取消，没换成）。这里改成工具一打开就交给一个独立的小程序，
关掉工具也会换完，下次打开就是新启动器。

换法：下载 zip → 取出 exe 核对 sha256 → 存成 <exe>.new → 旧的改名成
<exe>.old → .new 改名成 <exe>。Windows 允许改名正在执行的 exe，所以
启动器还开着也换得了；任何一步失败都把旧的放回去，下次开工具再试。

本文件只用标准库：工具用 ``python -I launcher_swap.py ...`` 单独跑它。
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import time
import urllib.request
import zipfile

# v0.1.18 发布的启动器（1.2.5：连不上 GitHub 也能用装好的版本启动；检查更新时
# 按「启动应用」也会先更新再启动；启动器日志改叫 app.<日期>.txt）。钉在那个发布
# 和它的检查码：更新仓库比发布附件先出来，用 latest 可能拿到旧启动器。启动器
# 再改时，指向第一次带它的发布（tag + win32_sha256.txt），并调高
# LAUNCHER_VERSION（要跟 scripts/prepare_pyappify_launcher.ps1 的
# $LauncherVersion 一样）。
LAUNCHER_VERSION = "1.2.5"
LAUNCHER_RELEASE = "v0.1.18"
LAUNCHER_SHA256 = "a6100bfab748595f2ae430e3e76127fa6ce247523efa86dc361b0b1d575834a9"
LAUNCHER_ZIP_URL = "https://github.com/nobell001/YES-BD2/releases/download/{tag}/yes-bd2-win32.zip"

DOWNLOAD_TIMEOUT = 60
DOWNLOAD_TRIES = 3
# 上一个换启动器的小程序还在跑（或刚死掉没清锁）时，这么久内不再开第二个。
LOCK_STALE_SECONDS = 600


def launcher_zip_url(tag: str = LAUNCHER_RELEASE) -> str:
    return LAUNCHER_ZIP_URL.format(tag=tag)


def version_parts(version: str | None) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in str(version).strip().lstrip("v").split("."))
    except (TypeError, ValueError):
        return None


def needs_swap(installed: str | None, target: str = LAUNCHER_VERSION) -> bool:
    """只有读得到装着的版本、而且比目标低才换；读不到就不动。"""
    current, wanted = version_parts(installed), version_parts(target)
    return current is not None and wanted is not None and current < wanted


def _log(log_path: str | None, message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} launcher swap: {message}\n"
    if not log_path:
        sys.stderr.write(line)
        return
    try:
        with open(log_path, "a", encoding="utf-8") as file:
            file.write(line)
    except OSError:
        pass


def _remove(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _take_lock(lock: str) -> bool:
    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock)
            except OSError:
                continue
            if age < LOCK_STALE_SECONDS or not _remove(lock):
                return False
        except OSError:
            return False
    return False


def download(url: str, opener=urllib.request.urlopen, sleep=time.sleep) -> bytes:
    last_error: Exception | None = None
    for attempt in range(DOWNLOAD_TRIES):
        try:
            with opener(url, timeout=DOWNLOAD_TIMEOUT) as response:
                return response.read()
        except Exception as exc:  # 网络断、GitHub 忙：等一下再试
            last_error = exc
            if attempt + 1 < DOWNLOAD_TRIES:
                sleep(2 * (attempt + 1))
    raise RuntimeError(f"download failed: {last_error}")


def exe_from_zip(data: bytes, exe_name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            if os.path.basename(member.filename).casefold() == exe_name.casefold():
                return archive.read(member)
    raise RuntimeError(f"{exe_name} not in zip")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_leftovers(exe: str) -> None:
    """上次换完、当时还在跑的旧启动器（<exe>.old）现在通常删得掉了。"""
    folder, name = os.path.split(exe)
    try:
        entries = os.listdir(folder or ".")
    except OSError:
        return
    for entry in entries:
        if (
            entry.casefold().startswith((name + ".old").casefold())
            or entry.casefold() == (name + ".new").casefold()
        ):
            _remove(os.path.join(folder, entry))


def swap(
    exe: str,
    url: str,
    expected_sha256: str,
    log_path: str | None = None,
    fetch=download,
) -> bool:
    """换成功回 True；失败时 exe 保持原样。"""
    lock = exe + ".updating"
    if not _take_lock(lock):
        _log(log_path, "another swap is running, skipped")
        return False
    new, old = exe + ".new", exe + ".old"
    try:
        _log(log_path, f"downloading {url}")
        data = exe_from_zip(fetch(url), os.path.basename(exe))
        actual = sha256(data)
        if actual != expected_sha256:
            _log(log_path, f"checksum mismatch {actual}, launcher left as is")
            return False
        with open(new, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if not _remove(old):
            # 上一个旧启动器还在跑删不掉，换个名字放
            old = f"{exe}.old{int(time.time())}"
        os.replace(exe, old)
        try:
            os.replace(new, exe)
        except OSError:
            os.replace(old, exe)
            raise
        with open(exe, "rb") as file:
            if sha256(file.read()) != expected_sha256:
                os.replace(exe, new)
                os.replace(old, exe)
                _log(log_path, "written launcher differs, old launcher restored")
                return False
        _remove(old)
        _log(log_path, f"success, launcher is now {expected_sha256[:12]}")
        return True
    except Exception as exc:
        _log(log_path, f"failed, launcher left as is: {exc}")
        return False
    finally:
        _remove(new)
        _remove(lock)


def main(argv: list[str]) -> int:
    exe, url, expected, log_path = argv[1:5]
    return 0 if swap(exe, url, expected, log_path or None) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
