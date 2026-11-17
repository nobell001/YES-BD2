"""Time how long a copy of YES-BD2 takes to show something, and to show its window.

Windows only, for a COPY of the tool's working folder (never the installed
one: this edits the copy's settings).  Usage:

    <python.exe> tools/dev/startup_timing.py <working folder copy> [runs]

Before the first run the copy's 「打开工具时自动开始」 and 「Auto Start Game When
App Starts」 are switched off, so opening it never starts a run or the game.
Each run starts ``pythonw main.py`` in the copy, watches its windows, prints
when the first window showed and when the main window
showed, then closes the copy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

OFF_KEYS = ("打开工具时自动开始", "Auto Start Game When App Starts")
MAIN_WINDOW_MIN_WIDTH = 500
TIMEOUT_S = 90


def switch_off_auto_starts(work: Path) -> None:
    for path in (work / "configs").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        changed = False
        for key in OFF_KEYS:
            if data.get(key) is True:
                data[key] = False
                changed = True
        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
            print(f"switched off auto start in {path.name}")


def visible_windows(pid: int) -> list[tuple[int, int, str]]:
    import win32gui
    import win32process

    found = []

    def each(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if win32process.GetWindowThreadProcessId(hwnd)[1] != pid:
            return True
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        found.append((right - left, bottom - top, win32gui.GetWindowText(hwnd)))
        return True

    win32gui.EnumWindows(each, None)
    return found


def one_run(work: Path) -> tuple[float | None, float | None]:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    started = time.perf_counter()
    process = subprocess.Popen([str(pythonw), str(work / "main.py")], cwd=str(work))
    first = main = None
    try:
        while time.perf_counter() - started < TIMEOUT_S:
            windows = visible_windows(process.pid)
            now = time.perf_counter() - started
            if windows and first is None:
                first = now
                print(f"  {now:6.2f}s first window {windows}")
            if any(width >= MAIN_WINDOW_MIN_WIDTH for width, _, _ in windows):
                main = now
                print(f"  {now:6.2f}s main window {windows}")
                break
            if process.poll() is not None:
                print(f"  the tool exited with {process.returncode}")
                break
            time.sleep(0.05)
        time.sleep(2)
    finally:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        time.sleep(2)
    return first, main


def main() -> None:
    work = Path(sys.argv[1]).resolve()
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    switch_off_auto_starts(work)
    results = []
    for number in range(1, runs + 1):
        print(f"run {number}")
        results.append(one_run(work))
    for number, (first, main_shown) in enumerate(results, 1):
        print(
            f"run {number}: first window {first if first is None else round(first, 2)} s, "
            f"main window {main_shown if main_shown is None else round(main_shown, 2)} s"
        )


if __name__ == "__main__":
    os.environ.pop("PYAPPIFY_PID", None)
    main()
