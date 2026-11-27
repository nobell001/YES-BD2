import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import win32con
from PySide6.QtWidgets import QApplication

from src.ui.manual_resolution import (
    MANUAL_RESOLUTIONS,
    ManualResolutionError,
    Win32WindowBackend,
    WindowResizeResult,
    _ResizeJob,
    format_resolution,
    resize_game_window,
    restore_game_window,
)


class _FakeHwndWindow:
    def __init__(self):
        self.hwnd = 101
        self.updates = 0

    def do_update_window_size(self):
        self.updates += 1


class _FakeDeviceManager:
    def __init__(self):
        self.hwnd_window = _FakeHwndWindow()

    @staticmethod
    def get_preferred_device():
        return {"device": "windows"}


class _FakeBackend:
    def __init__(
        self,
        *,
        style=win32con.WS_POPUP,
        rect=(100, 100, 1700, 1000),
        monitor_area=(0, 0, 2560, 1440),
        monitor_bounds=None,
        maximized=False,
        on_get_frame_size=None,
        position_failures=0,
    ):
        self.style = style | (win32con.WS_MAXIMIZE if maximized else 0)
        self.monitor_area = monitor_area
        self.monitor_bounds = monitor_bounds or monitor_area
        self.calls = []
        self.valid = True
        self.minimized = False
        self.maximized = maximized
        self.on_get_frame_size = on_get_frame_size
        self.position_failures = position_failures
        show_command = win32con.SW_SHOWMAXIMIZED if maximized else win32con.SW_SHOWNORMAL
        self.placement = (0, show_command, (0, 0), (0, 0), rect)
        self.rect = self.monitor_bounds if maximized else rect
        self._sync_client_size()

    def _sync_client_size(self):
        width = self.rect[2] - self.rect[0]
        height = self.rect[3] - self.rect[1]
        if self.style & win32con.WS_CAPTION:
            width -= 16
            height -= 39
        self.client_size = (width, height)

    def is_window(self, _hwnd):
        return self.valid

    def is_minimized(self, _hwnd):
        return self.minimized

    def is_maximized(self, _hwnd):
        return self.maximized

    def restore(self, _hwnd):
        self.calls.append(("restore",))
        self.maximized = False
        self.style &= ~win32con.WS_MAXIMIZE
        self.rect = tuple(self.placement[4])
        self._sync_client_size()

    def get_window_placement(self, _hwnd):
        return self.placement

    def set_window_placement(self, _hwnd, placement):
        self.calls.append(("placement", placement))
        self.placement = placement
        self.maximized = placement[1] == win32con.SW_SHOWMAXIMIZED
        if self.maximized:
            self.style |= win32con.WS_MAXIMIZE
            self.rect = self.monitor_bounds
        else:
            self.style &= ~win32con.WS_MAXIMIZE
            self.rect = tuple(placement[4])
        self._sync_client_size()

    def get_style(self, _hwnd):
        return self.style

    def set_style(self, _hwnd, style):
        self.calls.append(("style", style))
        self.style = style

    def get_window_rect(self, _hwnd):
        return self.rect

    def get_client_size(self, _hwnd):
        return self.client_size

    def get_monitor_area(self, _hwnd):
        return self.monitor_area

    def get_monitor_bounds(self, _hwnd):
        return self.monitor_bounds

    def get_frame_size(self, _hwnd, style, _target):
        if self.on_get_frame_size is not None:
            self.on_get_frame_size()
        return (16, 39) if style & win32con.WS_CAPTION else (0, 0)

    def set_window_pos(self, _hwnd, rect, *, frame_changed):
        self.calls.append(("position", rect, frame_changed))
        if self.position_failures > 0:
            self.position_failures -= 1
            raise OSError("SetWindowPos failed")
        self.rect = rect
        self._sync_client_size()


class ManualResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_resolution_catalog_contains_only_requested_common_sizes(self):
        self.assertEqual(
            (
                (3840, 2160),
                (2560, 1440),
                (1920, 1080),
                (1600, 900),
                (1366, 768),
                (1280, 720),
            ),
            MANUAL_RESOLUTIONS,
        )

    def test_win32_backend_reads_maximized_state_from_user32(self):
        is_zoomed = Mock(return_value=1)
        user32 = SimpleNamespace(IsZoomed=is_zoomed)

        with patch(
            "src.ui.manual_resolution.ctypes.WinDLL",
            return_value=user32,
        ) as win_dll:
            self.assertTrue(Win32WindowBackend.is_maximized(101))

        win_dll.assert_called_once_with("user32", use_last_error=True)
        is_zoomed.assert_called_once_with(101)

    def test_resize_converts_borderless_window_and_verifies_client_size(self):
        manager = _FakeDeviceManager()
        backend = _FakeBackend(maximized=True)

        result = resize_game_window(
            manager,
            (1280, 720),
            backend=backend,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )

        self.assertEqual(WindowResizeResult(1280, 720, True), result)
        self.assertIn(("restore",), backend.calls)
        self.assertFalse(backend.maximized)
        self.assertTrue(backend.style & win32con.WS_CAPTION)
        self.assertFalse(backend.style & win32con.WS_POPUP)
        self.assertEqual((1280, 720), backend.client_size)
        self.assertEqual((632, 340, 1928, 1099), backend.rect)
        self.assertGreaterEqual(manager.hwnd_window.updates, 2)

    def test_native_monitor_target_uses_borderless_without_caption_flicker(self):
        manager = _FakeDeviceManager()
        backend = _FakeBackend(
            monitor_area=(0, 0, 1920, 1040),
            monitor_bounds=(0, 0, 1920, 1080),
        )

        result = resize_game_window(
            manager,
            (1920, 1080),
            backend=backend,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )

        self.assertEqual(WindowResizeResult(1920, 1080, True), result)
        self.assertEqual(win32con.WS_POPUP, backend.style)
        self.assertEqual((0, 0, 1920, 1080), backend.rect)
        self.assertFalse(any(call[0] == "style" for call in backend.calls))

    def test_resize_centers_on_the_monitor_containing_the_game(self):
        manager = _FakeDeviceManager()
        backend = _FakeBackend(
            monitor_area=(1920, 0, 3286, 728),
            monitor_bounds=(1920, 0, 3286, 768),
        )

        result = resize_game_window(
            manager,
            (1280, 720),
            backend=backend,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )

        self.assertEqual(WindowResizeResult(1280, 720, True), result)
        self.assertEqual((1963, 4, 3243, 724), backend.rect)
        self.assertEqual(win32con.WS_POPUP, backend.style)

    def test_resize_noop_keeps_existing_window_style(self):
        manager = _FakeDeviceManager()
        backend = _FakeBackend(rect=(100, 100, 1380, 820))

        result = resize_game_window(manager, (1280, 720), backend=backend)

        self.assertEqual(WindowResizeResult(1280, 720, False), result)
        self.assertEqual([], backend.calls)
        self.assertEqual(win32con.WS_POPUP, backend.style)

    def test_failed_resize_preserves_style_geometry_and_maximized_placement(self):
        manager = _FakeDeviceManager()
        original_rect = (100, 100, 1700, 1000)
        backend = _FakeBackend(rect=original_rect, monitor_area=(0, 0, 1920, 1080))

        with self.assertRaisesRegex(ManualResolutionError, "无法容纳"):
            resize_game_window(manager, (3840, 2160), backend=backend)

        self.assertEqual(win32con.WS_POPUP, backend.style)
        self.assertEqual(original_rect, backend.rect)
        self.assertEqual([], backend.calls)

        backend = _FakeBackend(maximized=True, position_failures=1)
        original_placement = backend.placement
        with self.assertRaisesRegex(OSError, "SetWindowPos failed"):
            resize_game_window(manager, (1280, 720), backend=backend)
        self.assertTrue(backend.maximized)
        self.assertEqual(original_placement, backend.placement)
        self.assertEqual(
            win32con.WS_POPUP | win32con.WS_MAXIMIZE,
            backend.style,
        )

    def test_game_fullscreen_that_snaps_back_says_to_use_window_mode(self):
        # A 2560x1600 laptop with the game in its own 全屏 (2026-10-12): the
        # game puts the window back over the whole screen after every resize.
        manager = _FakeDeviceManager()
        screen = (0, 0, 2560, 1600)
        backend = _FakeBackend(
            rect=screen,
            monitor_area=(0, 0, 2560, 1552),
            monitor_bounds=screen,
        )

        def snap_back(_hwnd, rect, *, frame_changed):
            backend.calls.append(("position", rect, frame_changed))
            backend.rect = screen
            backend._sync_client_size()

        backend.set_window_pos = snap_back
        clock = iter([0.0, 0.0, 10.0])

        with self.assertRaisesRegex(ManualResolutionError, "窗口模式") as caught:
            resize_game_window(
                manager,
                (2560, 1440),
                backend=backend,
                monotonic=lambda: next(clock),
                sleep=lambda _seconds: None,
            )
        self.assertIn("2560 × 1600", str(caught.exception))
        self.assertIn("设置 → 图像 → 画面模式", str(caught.exception))

    def test_window_that_settles_at_another_size_keeps_the_plain_message(self):
        manager = _FakeDeviceManager()
        backend = _FakeBackend(monitor_area=(0, 0, 2560, 1440))

        def stuck(_hwnd, rect, *, frame_changed):
            backend.calls.append(("position", rect, frame_changed))
            backend.client_size = (1500, 844)

        backend.set_window_pos = stuck
        clock = iter([0.0, 0.0, 10.0])

        with self.assertRaisesRegex(ManualResolutionError, "没有稳定到目标分辨率"):
            resize_game_window(
                manager,
                (1920, 1080),
                backend=backend,
                monotonic=lambda: next(clock),
                sleep=lambda _seconds: None,
            )

    def _maximized_on_1080p(self):
        """The player's case (2026-11-27): a maximised framed game on a
        1920x1080 screen with a taskbar; its client is short of 1920x1080."""
        return _FakeBackend(
            style=win32con.WS_OVERLAPPEDWINDOW,
            rect=(200, 100, 1480, 859),
            monitor_area=(0, 0, 1920, 1040),
            monitor_bounds=(0, 0, 1920, 1080),
            maximized=True,
        )

    def test_1080p_screen_resize_covers_the_screen_and_remembers_the_window(self):
        manager = _FakeDeviceManager()
        backend = self._maximized_on_1080p()
        original_style = backend.style
        original_placement = backend.placement

        result = resize_game_window(
            manager, (1920, 1080), backend=backend,
            monotonic=lambda: 0.0, sleep=lambda _seconds: None,
        )

        # This is what the player saw as 「变成全屏」: no title bar, whole screen.
        self.assertEqual((0, 0, 1920, 1080), backend.rect)
        self.assertFalse(backend.style & win32con.WS_CAPTION)
        self.assertTrue(result.borderless)
        self.assertEqual(101, result.hwnd)
        self.assertEqual(original_style, result.original_style)
        self.assertEqual(original_placement, result.original_placement)

    def test_restore_gives_back_the_maximised_framed_window(self):
        manager = _FakeDeviceManager()
        backend = self._maximized_on_1080p()
        original_client = backend.client_size
        result = resize_game_window(
            manager, (1920, 1080), backend=backend,
            monotonic=lambda: 0.0, sleep=lambda _seconds: None,
        )
        updates = manager.hwnd_window.updates

        self.assertEqual("", restore_game_window(manager, result, backend=backend))

        self.assertTrue(backend.style & win32con.WS_CAPTION)
        self.assertFalse(backend.style & win32con.WS_POPUP)
        self.assertTrue(backend.maximized)
        self.assertEqual(original_client, backend.client_size)
        self.assertGreater(manager.hwnd_window.updates, updates)

    def test_restore_gives_back_a_small_framed_window_where_it_was(self):
        manager = _FakeDeviceManager()
        backend = _FakeBackend(
            style=win32con.WS_OVERLAPPEDWINDOW,
            rect=(300, 200, 1916, 1139),  # a 1600x900 client
            monitor_area=(0, 0, 1920, 1040),
            monitor_bounds=(0, 0, 1920, 1080),
        )
        result = resize_game_window(
            manager, (1920, 1080), backend=backend,
            monotonic=lambda: 0.0, sleep=lambda _seconds: None,
        )
        self.assertTrue(result.borderless)

        self.assertEqual("", restore_game_window(manager, result, backend=backend))

        self.assertEqual(win32con.WS_OVERLAPPEDWINDOW, backend.style)
        self.assertEqual((300, 200, 1916, 1139), backend.rect)
        self.assertEqual((1600, 900), backend.client_size)

    def test_restore_leaves_a_window_changed_or_gone_since(self):
        for case in ("resized", "gone", "minimised"):
            with self.subTest(case=case):
                manager = _FakeDeviceManager()
                backend = _FakeBackend(
                    style=win32con.WS_OVERLAPPEDWINDOW,
                    rect=(300, 200, 1916, 1139),
                    monitor_area=(0, 0, 1920, 1040),
                    monitor_bounds=(0, 0, 1920, 1080),
                )
                result = resize_game_window(
                    manager, (1920, 1080), backend=backend,
                    monotonic=lambda: 0.0, sleep=lambda _seconds: None,
                )
                if case == "resized":
                    backend.client_size = (2560, 1440)
                elif case == "gone":
                    backend.valid = False
                else:
                    backend.minimized = True
                backend.calls.clear()

                self.assertNotEqual("", restore_game_window(manager, result, backend=backend))
                self.assertEqual([], backend.calls)

    def test_nothing_to_restore_when_nothing_was_changed(self):
        manager = _FakeDeviceManager()
        backend = _FakeBackend(rect=(100, 100, 1380, 820))
        result = resize_game_window(manager, (1280, 720), backend=backend)
        self.assertNotEqual("", restore_game_window(manager, result, backend=backend))
        self.assertEqual([], backend.calls)

    def test_running_task_is_rejected_before_window_changes(self):
        manager = _FakeDeviceManager()
        backend = _FakeBackend()
        executor = SimpleNamespace(current_task=object(), paused=False)

        with self.assertRaisesRegex(ManualResolutionError, "请先暂停任务"):
            resize_game_window(
                manager,
                (1280, 720),
                executor=executor,
                backend=backend,
            )

        self.assertEqual([], backend.calls)

        executor.current_task = None
        backend = _FakeBackend(
            on_get_frame_size=lambda: setattr(executor, "current_task", object())
        )
        with self.assertRaisesRegex(ManualResolutionError, "请先暂停任务"):
            resize_game_window(
                manager,
                (1280, 720),
                executor=executor,
                backend=backend,
            )
        self.assertEqual([], backend.calls)

    def test_resize_job_reports_failures_without_touching_qt_widgets(self):
        def fail(_manager, target, *, executor, cancel_event):
            self.assertFalse(cancel_event.is_set())
            raise ManualResolutionError(f"拒绝 {format_resolution(target)}")

        job = _ResizeJob(object(), None, (1600, 900), fail)
        succeeded = []
        failed = []
        job.signals.succeeded.connect(succeeded.append)
        job.signals.failed.connect(failed.append)

        job.run()

        self.assertEqual([], succeeded)
        self.assertEqual(["拒绝 1600 × 900"], failed)


if __name__ == "__main__":
    unittest.main()
