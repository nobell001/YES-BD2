"""Look at and poke the game by hand from a remote session (dev only).

    python tools/dev/talos_look.py OUT_DIR shot NAME
    python tools/dev/talos_look.py OUT_DIR click X Y NAME   (X Y in 1920x1080 reference px)
    python tools/dev/talos_look.py OUT_DIR key esc|h|p|f NAME
    python tools/dev/talos_look.py OUT_DIR wheel N NAME    (N notches, + in / - out)

Each command brings the game to the front, does its one thing with the real
mouse or keyboard, waits a moment and saves the game window as
OUT_DIR/NAME.png (full size).  Only for harmless screens (no spending).
"""

import ctypes
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

KEYS = {"esc": win32con.VK_ESCAPE, "h": ord("H"), "p": ord("P"), "f": ord("F"), "m": ord("M")}


def game() -> int:
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


def to_screen(rect, point):
    x, y, w, h = rect
    return x + round(float(point[0]) / 1920 * w), y + round(float(point[1]) / 1080 * h)


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    command, args = sys.argv[2], sys.argv[3:]
    hwnd = game()
    if win32gui.GetForegroundWindow() != hwnd:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:
            print("could not bring the game to front:", exc)
        time.sleep(0.6)
    if win32gui.GetForegroundWindow() != hwnd:
        sys.exit("the game is not the window in front; nothing done")
    rect = client(hwnd)
    if command == "click":
        sx, sy = to_screen(rect, args[:2])
        win32api.SetCursorPos((sx, sy))
        time.sleep(0.15)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.08)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        args = args[2:]
    elif command == "key":
        code = KEYS[args[0].lower()]
        win32api.keybd_event(code, 0, 0, 0)
        time.sleep(0.08)
        win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)
        args = args[1:]
    elif command == "wheel":
        notches = int(args[0])
        win32api.SetCursorPos(to_screen(rect, (960, 860)))
        time.sleep(0.2)
        for _ in range(abs(notches)):
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, 120 if notches > 0 else -120, 0)
            time.sleep(0.12)
        args = args[1:]
    elif command != "shot":
        sys.exit(f"unknown command {command}")
    time.sleep(1.5 if command != "shot" else 0.0)
    name = args[0] if args else time.strftime("%H%M%S")
    x, y, w, h = rect
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    path = out / f"{name}.png"
    cv2.imwrite(str(path), cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
    print("saved", path, f"{w}x{h}")


main()
