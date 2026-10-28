"""塔洛斯 planning screen: how the mouse wheel changes the grid size.

Run with the app's python from the repo root (or a worktree of it)
while the game sits on a 塔洛斯 stage's TURN 1 planning screen and no tool
run is going.  It only moves the mouse over the floor and turns the wheel
(zoom), then puts the zoom back where it was.  Pictures + table go to
..\\talos\\pics\\zoom\\.

    python zoom_probe.py [out_dir]
"""

import ctypes
import json
import sys
import time
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(2)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import win32api  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402
from PIL import ImageGrab  # noqa: E402

sys.path.insert(0, str(Path.cwd()))
from src.tasks.fiend_hunt import vision  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"..\talos\pics\zoom")
OUT.mkdir(parents=True, exist_ok=True)
SCALES = tuple(round(0.40 + 0.01 * step, 2) for step in range(181))  # 0.40-2.20
BOX = (60.0, 60.0, 1680.0, 1020.0)


def game():
    found = []

    def each(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd).strip() in ("BrownDust II", "BrownDust2"):
            found.append(hwnd)

    win32gui.EnumWindows(each, None)
    if not found:
        sys.exit("game window not found")
    return found[0]


def client(hwnd):
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    x, y = win32gui.ClientToScreen(hwnd, (left, top))
    return x, y, right - left, bottom - top


def grab(rect):
    x, y, w, h = rect
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def measure(frame):
    found = vision._find_grid(frame, BOX, SCALES)
    wide = vision._find_grid(frame, BOX, SCALES, every_column=True)
    usual = vision.grid_on_screen(frame)
    out = {}
    for key, grid in (("any", found), ("every_column", wide), ("app", usual)):
        out[key] = None if grid is None else [round(grid.scale, 2), round(grid.left), round(grid.top)]
    return out


def wheel(rect, point, clicks):
    x, y, w, h = rect
    sx, sy = x + round(point[0] / 1920 * w), y + round(point[1] / 1080 * h)
    win32api.SetCursorPos((sx, sy))
    time.sleep(0.25)
    for _ in range(abs(clicks)):
        win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, 120 if clicks > 0 else -120, 0)
        time.sleep(0.12)
    time.sleep(0.9)


def main():
    hwnd = game()
    if win32gui.GetForegroundWindow() != hwnd:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:
            print("could not bring the game to front:", exc)
        time.sleep(0.8)
    if win32gui.GetForegroundWindow() != hwnd:
        sys.exit("game is not the window in front; stop")
    rect = client(hwnd)
    rows = []

    def step(name, frame):
        row = {"step": name, **measure(frame)}
        cv2.imwrite(str(OUT / f"{len(rows):02d}_{name}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return row

    start = step("start", grab(rect))
    if not vision.planning_visible(grab(rect)):
        sys.exit("not on the planning screen; stop")
    # The floor between the two sides, a little below the middle: no card,
    # no unit list, no button.
    floor = (960, 860)
    for n in range(1, 13):
        wheel(rect, floor, -1)
        step(f"out{n}", grab(rect))
    for n in range(1, 25):
        wheel(rect, floor, +1)
        step(f"in{n}", grab(rect))
    # Back down to the start size.
    target = (start["any"] or [None])[0]
    for n in range(1, 25):
        now = rows[-1]["any"]
        if target is None or now is None or abs(now[0] - target) <= 0.02:
            break
        wheel(rect, floor, -1 if now[0] > target else +1)
        step(f"back{n}", grab(rect))
    (OUT / "zoom.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


main()
