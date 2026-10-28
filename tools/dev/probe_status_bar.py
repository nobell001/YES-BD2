"""Check the in-game status bar on a real Windows PC with the game open
(YES-BD2 #60).  Presses nothing in the game and leaves the foreground alone.

    python tools/dev/probe_status_bar.py <out dir>

Shows the bar over the game for about 3 seconds and checks what Leo asked
(2026-10-28 「不要干擾到辨識和判定」):
- Windows keeps it out of screenshots (affinity 0x11) and a screen grab with
  the bar shown equals one without it;
- the mouse goes through it (WindowFromPoint at its middle finds the game);
- the window in front did not change.
Writes probe.json, screen-with-bar.png (what a screenshot sees: no bar) and
look.png (the bar drawn onto that screenshot, how the player sees it).
"""

import json
import os
import sys
import time

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, root)
os.chdir(root)

import ctypes  # noqa: E402

import numpy as np  # noqa: E402
import win32gui  # noqa: E402
from PIL import ImageGrab  # noqa: E402
from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "probe_status_bar")
os.makedirs(out, exist_ok=True)
app = QApplication([])

from src import HWND_CLASS  # noqa: E402
from src.ui.shell import game_status as g  # noqa: E402
from src.utils import game_status_bar  # noqa: E402

game = win32gui.FindWindow(HWND_CLASS, None)
if not game:
    sys.exit("game window not found")
left, top, right, bottom = win32gui.GetClientRect(game)
x, y = win32gui.ClientToScreen(game, (left, top))
native = QRect(x, y, right - left, bottom - top)
area = g.native_to_qt(native)
front_before = win32gui.GetForegroundWindow()


def grab(rect):
    box = (rect[0], rect[1], rect[2], rect[3])
    return np.asarray(ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")).astype(np.int16)


bar = g.StatusBar()
ok = bar.prepare()
bar.set_status(g.Status(g.RUN, "每日跑图 · 第 13 章", "战斗区域 2：压制", "12:48", "第 14 / 16 项", 13 / 16, "map"))
bar.place(area, g.font_px(area))
hwnd = int(bar.winId())
bar_rect = win32gui.GetWindowRect(hwnd)  # before show: where it will be
before = grab(bar_rect)
bar.show()
for _ in range(20):
    app.processEvents()
    time.sleep(0.05)
bar_rect = win32gui.GetWindowRect(hwnd)
with_bar = grab(bar_rect)
ImageGrab.grab(bbox=(native.x(), native.y(), native.right() + 1, native.bottom() + 1), all_screens=True).save(
    f"{out}/screen-with-bar.png"
)
middle = ((bar_rect[0] + bar_rect[2]) // 2, (bar_rect[1] + bar_rect[3]) // 2)
under = win32gui.WindowFromPoint(middle)
affinity = ctypes.c_uint(0)
ctypes.windll.user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
picture = bar.grab()
front_after = win32gui.GetForegroundWindow()
bar.hide()
app.processEvents()

look = QImage(f"{out}/screen-with-bar.png")
painter = QPainter(look)
ratio = (native.width() / area.width()) if area.width() else 1
painter.drawPixmap(
    round(bar_rect[0] - native.x()), round(bar_rect[1] - native.y()),
    picture.scaled(round(picture.width() * ratio), round(picture.height() * ratio)) if ratio != 1 else picture,
)
painter.end()
look.save(f"{out}/look.png")

result = {
    "prepared": ok,
    "game": game,
    "game_client_px": [native.x(), native.y(), native.width(), native.height()],
    "game_client_qt": [area.x(), area.y(), area.width(), area.height()],
    "bar_px": list(bar_rect),
    "affinity": hex(affinity.value),
    "exstyle": hex(style & 0xFFFFFFFF),
    "click_through": bool(style & 0x20) and bool(style & 0x80000),
    "no_activate": bool(style & 0x08000000),
    "under_bar_root_is_game": win32gui.GetAncestor(under, 2) == game,
    "window_at_is_game": win32gui.GetAncestor(game_status_bar.window_at(middle), 2) == game,
    "foreground_unchanged": front_before == front_after,
    "screenshot_diff_mean": float(np.abs(with_bar - before).mean()) if with_bar.shape == before.shape else None,
}
with open(f"{out}/probe.json", "w", encoding="utf-8") as file:
    json.dump(result, file, ensure_ascii=False, indent=1)
print(json.dumps(result, ensure_ascii=False, indent=1))
