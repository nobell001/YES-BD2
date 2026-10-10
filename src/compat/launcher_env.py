"""工具不是从 yes-bd2 启动器打开时，补上启动器本来会传进来的版本资讯。

启动器开工具时会带 PYAPPIFY_VERSION、PYAPPIFY_EXECUTABLE 等环境变量；
「检查更新」靠它们去问启动器有哪些版本。从桌面分身、管理员重开或其他
方式打开的工具没有这些变量，pyappify 直接报
「does not support checking for updates for pyappify_version: None」，
所以永远看不到新版（YES-BD2 issue #2；4K 实测 10-09：启动器开的每次都
成功，分身开的每次都失败，而启动器本身 4.5 秒就答出全部版本）。

这里从安装文件夹找回启动器（<根>\\<名字>.exe）和 data\\apps\\<名字>\\app.json，
在任何地方 import pyappify 之前把变量补上。不补 PYAPPIFY_PID：那时没有
启动器在跑，补了反而会让 kill_pyappify 去关一个不相干的程序。源码版
（start.bat）找不到启动器，什么都不做。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

VERSION_ENV = "PYAPPIFY_VERSION"
PID_ENV = "PYAPPIFY_PID"


def find_install(script_dir: str | os.PathLike) -> tuple[Path, Path] | None:
    """(启动器 exe, app 文件夹)；工具不在 <根>\\data\\apps\\<名字>\\working 里时为 None。"""
    working = Path(script_dir)
    if working.name.casefold() != "working":
        return None
    app_dir = working.parent
    apps_dir = app_dir.parent
    data_dir = apps_dir.parent
    if apps_dir.name.casefold() != "apps" or data_dir.name.casefold() != "data":
        return None
    exe = data_dir.parent / f"{app_dir.name}.exe"
    if not exe.is_file():
        return None
    return exe, app_dir


def file_version(path: str | os.PathLike) -> str | None:
    """Windows 档案版本，例如 "1.2.3"；读不到时为 None。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        version = ctypes.WinDLL("version")
        name = str(path)
        size = version.GetFileVersionInfoSizeW(name, None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(name, 0, size, buffer):
            return None
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [
                (field, wintypes.DWORD)
                for field in (
                    "signature",
                    "struc_version",
                    "file_version_ms",
                    "file_version_ls",
                    "product_version_ms",
                    "product_version_ls",
                    "flags_mask",
                    "flags",
                    "os",
                    "type",
                    "subtype",
                    "date_ms",
                    "date_ls",
                )
            ]

        info = ctypes.cast(pointer, ctypes.POINTER(FixedFileInfo)).contents
        major, minor = info.file_version_ms >> 16, info.file_version_ms & 0xFFFF
        patch = info.file_version_ls >> 16
        return f"{major}.{minor}.{patch}"
    except Exception:
        return None


def read_app_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as file:
            document = json.load(file)
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def restore_launcher_env(
    script_dir: str | os.PathLike, environ=None, read_version=file_version
) -> bool:
    """补上缺少的启动器变量；True 表示补了。"""
    environ = os.environ if environ is None else environ
    if environ.get(VERSION_ENV):
        return False
    install = find_install(script_dir)
    if install is None:
        return False
    exe, app_dir = install
    launcher_version = read_version(exe)
    if not launcher_version:
        return False

    environ[VERSION_ENV] = launcher_version
    environ.setdefault("PYAPPIFY_EXECUTABLE", str(exe))
    app_json = app_dir / "app.json"
    if app_json.is_file():
        environ.setdefault("PYAPPIFY_APP_JSON_PATH", str(app_json))
    app = read_app_json(app_json)
    current = app.get("current_version")
    if isinstance(current, str) and current:
        environ.setdefault("PYAPPIFY_APP_VERSION", current)
        # 跟现在的版本一样：不是刚更新完，不显示「更新内容」。
        environ.setdefault("PYAPPIFY_APP_STARTING_VERSION", current)
    profile = app.get("current_profile")
    if isinstance(profile, str) and profile:
        environ.setdefault("PYAPPIFY_APP_PROFILE", profile)
    return True


def process_exe(pid: int) -> str | None:
    try:
        import psutil

        return psutil.Process(pid).exe()
    except Exception:
        return None


def _same_file(first, second) -> bool:
    try:
        return os.path.samefile(first, second)
    except (OSError, ValueError):
        return False


def drop_stale_launcher_pid(
    script_dir: str | os.PathLike, environ=None, exe_of=process_exe
) -> bool:
    """PYAPPIFY_PID 那个程序不是本工具的启动器时把变量拿掉；True 表示拿掉了。

    主视窗第一次出来时 ok-script 会把这个编号的程序缩小再强制关掉。编号
    若是之前那次打开留下的（例如换语言重开），启动器早就关了，同一个编号
    可能已经是游戏或别的程序（2026-10-09 检查）。
    """
    environ = os.environ if environ is None else environ
    value = environ.get(PID_ENV)
    if not value:
        return False
    try:
        exe = exe_of(int(value))
    except (TypeError, ValueError):
        exe = None
    launchers = [environ.get("PYAPPIFY_EXECUTABLE")]
    install = find_install(script_dir)
    if install is not None:
        launchers.append(install[0])
    if exe and any(launcher and _same_file(exe, launcher) for launcher in launchers):
        return False
    del environ[PID_ENV]
    return True


SHOWN_FILE = Path("configs") / "update_notice_shown.txt"


def show_update_notice_once(script_dir: str | os.PathLike, environ=None) -> bool:
    """更新内容每个版本只跳一次；True 表示这次要跳。

    启动器把 app.json 的 app_starting_version 留在更新前的版本，之后每次
    打开都传进来，工具就以为刚更新，每次都跳到「关于」（4K 实测 10-09：
    app_starting_version v0.1.11、current v0.1.13）。记下跳过的版本，
    同一个版本再打开时把起始版本当成现在的版本，不再跳。
    """
    environ = os.environ if environ is None else environ
    current = environ.get("PYAPPIFY_APP_VERSION")
    starting = environ.get("PYAPPIFY_APP_STARTING_VERSION")
    if not current or not starting or current == starting:
        return False
    shown_file = Path(script_dir) / SHOWN_FILE
    try:
        shown = shown_file.read_text(encoding="utf-8").strip()
    except OSError:
        shown = ""
    if shown == current:
        environ["PYAPPIFY_APP_STARTING_VERSION"] = current
        return False
    try:
        shown_file.parent.mkdir(exist_ok=True)
        shown_file.write_text(current, encoding="utf-8")
    except OSError:
        pass
    return True
