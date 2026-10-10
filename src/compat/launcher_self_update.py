"""工具一打开就把旧启动器换成新版（细节见 launcher_swap.py）。

换的工作交给独立的小程序，工具马上关掉也会换完；这里只决定要不要换。
源码版（找不到启动器）或启动器已经是新版时什么都不做。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.compat.launcher_env import file_version, find_install
from src.compat.launcher_swap import (
    LAUNCHER_SHA256,
    LAUNCHER_VERSION,
    clean_leftovers,
    launcher_zip_url,
    needs_swap,
)

LOG_NAME = "launcher-update.log"
# 这次打开有没有开始换：主视窗出来时据此提示玩家（launcher_update_notice）。
# 上一次已经换失败（例如连不上 GitHub）时照样再试，但不再说「下次生效」
# （审查 #61：每次打开都这样说，其实每次都失败）。
swap_started = False
# launcher_swap.py 写的结果行：成功一种，失败三种。
_SWAP_SUCCESS = "success"
_SWAP_FAILURES = ("failed", "checksum mismatch", "written launcher differs")
_LOG_TAIL_BYTES = 8192


def last_swap_failed(log_path: str | os.PathLike) -> bool:
    """日志里最后一次换的结果是失败时回 True；没有日志或没有结果都回 False。"""
    try:
        with open(log_path, "rb") as file:
            file.seek(0, os.SEEK_END)
            file.seek(max(0, file.tell() - _LOG_TAIL_BYTES))
            tail = file.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    for line in reversed(tail.splitlines()):
        _, marker, message = line.partition("launcher swap: ")
        if not marker:
            continue
        if message.startswith(_SWAP_SUCCESS):
            return False
        if message.startswith(_SWAP_FAILURES):
            return True
    return False


def helper_python(executable: str = sys.executable) -> str:
    """有 pythonw 就用它，换的时候不会跳出黑色视窗。"""
    pythonw = Path(executable).with_name("pythonw.exe")
    return str(pythonw) if pythonw.is_file() else executable


def start_launcher_swap(
    script_dir: str | os.PathLike,
    read_version=file_version,
    popen=subprocess.Popen,
    platform: str = os.name,
) -> bool:
    """需要换时开小程序去换，回 True；不用换或开不了回 False。"""
    global swap_started
    if platform != "nt":
        return False
    try:
        install = find_install(script_dir)
        if install is None:
            return False
        exe = str(install[0])
        clean_leftovers(exe)
        if not needs_swap(read_version(exe)):
            return False
        logs = Path(script_dir) / "logs"
        logs.mkdir(exist_ok=True)
        failed_before = last_swap_failed(logs / LOG_NAME)
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        popen(
            [
                helper_python(),
                "-I",
                str(Path(__file__).with_name("launcher_swap.py")),
                exe,
                launcher_zip_url(),
                LAUNCHER_SHA256,
                str(logs / LOG_NAME),
            ],
            cwd=os.path.dirname(exe),
            creationflags=flags,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        swap_started = not failed_before
        return True
    except Exception:
        # 换不了就照旧用旧启动器，下次开工具再试；绝不挡住工具打开。
        return False


__all__ = ["LAUNCHER_VERSION", "start_launcher_swap"]
