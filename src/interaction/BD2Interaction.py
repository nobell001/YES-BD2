import ctypes
import threading
import time
from typing import Callable

import win32api
import win32con
import win32gui
from ok.device.intercation import INPUT, MOUSEINPUT, PostMessageInteraction, SendInput
from ok.util.logger import Logger
from win32api import GetCursorPos, SetCursorPos

logger = Logger.get_logger(__name__)

# On the 桌面分身 the game samples the cursor at a lower frame rate (Remote
# Desktop): with a 10 ms press and the cursor put back 25 ms later, the release
# landed after the cursor had left the button, so buttons lit up but did not
# fire (Leo watched it live, 2026-10-03).  Nobody else uses that cursor, so it
# stays on the target, the press is held longer and the release gets a frame.
CLONE_DOWN_SECONDS = 0.08
CLONE_AFTER_UP_SECONDS = 0.06
# The real desktop has the same per-frame cursor sampling: a 20 ms press with
# the cursor put back 25 ms after the release could drop clicks below ~40 fps.
# 50 ms each way covers ~20 fps for ~0.05 s per click (Leo OK, 2026-10-05).
DESKTOP_DOWN_SECONDS = 0.05
# Added to the 25 ms wait in _restore_cursor: 50 ms on target after release.
DESKTOP_AFTER_UP_SECONDS = 0.025


def _in_clone() -> bool:
    if _in_clone.value is None:
        try:
            from src.utils.clone_desktop import in_clone

            _in_clone.value = in_clone()
        except Exception:
            _in_clone.value = False
    return _in_clone.value


_in_clone.value = None


class BD2Interaction(PostMessageInteraction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cursor_position = None
        self._operating = False
        self._input_lock = threading.RLock()
        self.user32 = ctypes.windll.user32
        self._activate_required = True
        self.hwnd_window.visible_monitors.append(self)

    def on_visible(self, visible):
        self._activate_required = not visible

    def scroll(self, x, y, scroll_amount):
        with self._input_lock:
            self.try_activate()
            logger.debug(f"scroll {x}, {y}, {scroll_amount}")

            base_hwnd = self.hwnd_window.top_hwnd or self.hwnd_window.hwnd
            if x > 0 and y > 0:
                top_x, top_y = self.hwnd_window.get_top_window_cords(x, y)
                abs_x, abs_y = win32gui.ClientToScreen(base_hwnd, (int(top_x), int(top_y)))
                self.bg_mouse_pos = (top_x, top_y)
                self._dynamic_target_hwnd = self._target_hwnd_at(abs_x, abs_y, base_hwnd)
                long_position = win32api.MAKELONG(abs_x, abs_y)
            else:
                self._dynamic_target_hwnd = base_hwnd
                long_position = 0

            w_param = win32api.MAKELONG(0, win32con.WHEEL_DELTA * scroll_amount)
            self.post(win32con.WM_MOUSEWHEEL, w_param, long_position)

    def post_swipe(self, x1, y1, x2, y2, duration=0.4, steps=12):
        """Hold the left button and slide, the way the click is sent: the
        cursor follows the posted messages (the game samples it), no real
        button press, cursor restored afterwards.  Client coordinates."""
        with self._input_lock:
            old = GetCursorPos()
            held = None  # where the button went down and is not up yet
            try:
                self.post(win32con.WM_MOUSEMOVE, 0, win32api.MAKELONG(x1, y1))
                SetCursorPos(self.capture.get_abs_cords(x1, y1))
                time.sleep(0.03)
                self.post(win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, win32api.MAKELONG(x1, y1))
                held = (x1, y1)
                time.sleep(0.05)
                for index in range(1, steps + 1):
                    x = round(x1 + (x2 - x1) * index / steps)
                    y = round(y1 + (y2 - y1) * index / steps)
                    SetCursorPos(self.capture.get_abs_cords(x, y))
                    self.post(win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, win32api.MAKELONG(x, y))
                    held = (x, y)
                    time.sleep(duration / steps)
                time.sleep(0.05)
                self.post(win32con.WM_LBUTTONUP, 0, win32api.MAKELONG(x2, y2))
                held = None
            finally:
                if held is not None:
                    # Stopped mid-swipe (audit #63): never leave the game's
                    # left button held down.
                    try:
                        self.post(win32con.WM_LBUTTONUP, 0, win32api.MAKELONG(*held))
                    except Exception:
                        pass
                time.sleep(0.03)
                try:
                    SetCursorPos(old)
                except Exception:
                    pass

    def _target_hwnd_at(self, abs_x, abs_y, fallback_hwnd):
        for hwnd_info in getattr(self.hwnd_window, "hwnds", []):
            candidate = hwnd_info[0]
            if not win32gui.IsWindow(candidate):
                continue
            try:
                left = hwnd_info[4]
                top = hwnd_info[5]
                right = left + hwnd_info[2]
                bottom = top + hwnd_info[3]
                if left <= abs_x < right and top <= abs_y < bottom:
                    return candidate
            except Exception:
                continue
        return fallback_hwnd

    def click(
        self,
        x=-1,
        y=-1,
        move_back=False,
        name=None,
        down_time=0.01,
        move=True,
        key="left",
    ):
        with self._input_lock:
            self.try_activate()
            if x < 0:
                x, y = round(self.capture.width * 0.5), round(self.capture.height * 0.5)

            should_restore = move and move_back and not self._operating
            if move:
                if should_restore:
                    self.cursor_position = GetCursorPos()
                abs_x, abs_y = self.capture.get_abs_cords(x, y)
                SetCursorPos((abs_x, abs_y))
                time.sleep(0.025)

            click_pos = win32api.MAKELONG(x, y)
            if key == "left":
                btn_down = win32con.WM_LBUTTONDOWN
                btn_mk = win32con.MK_LBUTTON
                btn_up = win32con.WM_LBUTTONUP
            elif key == "middle":
                btn_down = win32con.WM_MBUTTONDOWN
                btn_mk = win32con.MK_MBUTTON
                btn_up = win32con.WM_MBUTTONUP
            else:
                btn_down = win32con.WM_RBUTTONDOWN
                btn_mk = win32con.MK_RBUTTON
                btn_up = win32con.WM_RBUTTONUP
            clone = _in_clone()
            self.post(btn_down, btn_mk, click_pos)
            try:
                time.sleep(max(down_time, CLONE_DOWN_SECONDS if clone else DESKTOP_DOWN_SECONDS))
            finally:
                # The up always follows the down, even when the run stops
                # in between (audit #63).
                self.post(btn_up, 0, click_pos)
            time.sleep(CLONE_AFTER_UP_SECONDS if clone else DESKTOP_AFTER_UP_SECONDS)

            if should_restore and not clone:
                self._restore_cursor()

    def operate(self, fun: Callable, block=False, restore_cursor=True):
        with self._input_lock:
            result = None
            is_outer_operate = False
            if not self._operating:
                self.cursor_position = GetCursorPos()
                self._operating = True
                is_outer_operate = True

            if block:
                self.block_input()
            try:
                result = fun()
            except Exception as e:
                logger.error("operate exception", e)
                raise
            finally:
                if is_outer_operate:
                    self._operating = False
                    if restore_cursor:
                        self._restore_cursor()
                if block:
                    self.unblock_input()
            return result

    def wait_until_idle(self, timeout: float = 2.0) -> bool:
        """Wait until the current mouse operation releases the interaction lock."""
        acquired = self._input_lock.acquire(timeout=max(0.0, timeout))
        if acquired:
            self._input_lock.release()
        return acquired

    def move(self, x, y, down_btn=0):
        with self._input_lock:
            return super().move(x, y, down_btn=down_btn)

    def swipe(self, x1, y1, x2, y2, duration=3, settle_time=0):
        with self._input_lock:
            return super().swipe(
                x1,
                y1,
                x2,
                y2,
                duration=duration,
                settle_time=settle_time,
            )

    def right_click(self, x=-1, y=-1, move_back=False, name=None):
        with self._input_lock:
            return super().right_click(x, y, move_back=move_back, name=name)

    def mouse_down(self, x=-1, y=-1, name=None, key="left"):
        with self._input_lock:
            return super().mouse_down(x, y, name=name, key=key)

    def update_mouse_pos(self, x, y, activate=True):
        with self._input_lock:
            return super().update_mouse_pos(x, y, activate=activate)

    def mouse_up(self, key="left"):
        with self._input_lock:
            return super().mouse_up(key=key)

    def _restore_cursor(self):
        if _in_clone():
            return  # nobody else uses the clone's cursor; leave it on the target
        time.sleep(0.025)
        try:
            SetCursorPos(self.cursor_position)
        except Exception as e:
            logger.error("restore cursor exception", e)

    def block_input(self):
        self.user32.BlockInput(True)

    def unblock_input(self):
        self.user32.BlockInput(False)

    def move_mouse_relative(self, dx, dy):
        with self._input_lock:
            mi = MOUSEINPUT(dx, dy, 0, 1, 0, None)
            i = INPUT(0, mi)
            SendInput(1, ctypes.pointer(i), ctypes.sizeof(INPUT))

    def try_activate(self):
        if self._activate_required:
            if not self.hwnd_window.is_foreground():
                super().try_activate()
            self._activate_required = False
