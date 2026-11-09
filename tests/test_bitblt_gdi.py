"""YES-BD2 #77: BitBlt capture must not keep thread-bound objects.

The crash: ok's BitBlt kept win32ui (MFC temporary) DC objects on the shared
capture object; when the thread that made them ended they were freed, the
next capture from another thread failed ("Select bitmap object failed") and
its clean-up crashed the tool in mfc140u.dll.
"""

import ctypes
import itertools
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.compat import bitblt_gdi


class FakeGdi:
    """Plain-handle GDI stand-in that records which handles are alive."""

    def __init__(self):
        self._ids = itertools.count(100)
        self.window_dcs = {}
        self.memory_dcs = set()
        self.bitmaps = {}
        self.selected = {}
        self.fail_select_once = False
        self.calls = []

    def GetWindowDC(self, hwnd):
        handle = next(self._ids)
        self.window_dcs[handle] = threading.get_ident()
        return handle

    GetDC = GetWindowDC

    def ReleaseDC(self, hwnd, dc):
        self.window_dcs.pop(dc)
        return 1

    def PrintWindow(self, hwnd, dc, flags):
        assert dc in self.window_dcs
        return 1

    def CreateCompatibleDC(self, dc):
        handle = next(self._ids)
        self.memory_dcs.add(handle)
        return handle

    def CreateCompatibleBitmap(self, dc, width, height):
        handle = next(self._ids)
        self.bitmaps[handle] = (width, height)
        return handle

    def SelectObject(self, dc, obj):
        if self.fail_select_once:
            self.fail_select_once = False
            return 0
        assert dc in self.memory_dcs
        old = self.selected.get(dc, 1)
        self.selected[dc] = obj
        return old

    def DeleteObject(self, obj):
        assert obj not in self.selected.values(), "bitmap still selected"
        self.bitmaps.pop(obj)
        return 1

    def DeleteDC(self, dc):
        assert dc not in self.window_dcs, "DeleteDC on a window DC"
        self.memory_dcs.remove(dc)
        return 1

    def BitBlt(self, dst, *args):
        assert args[4] in self.window_dcs
        return 1

    def GetDIBits(self, dc, bitmap, start, lines, buffer, info, usage):
        assert self.selected.get(dc) != bitmap, "bitmap still selected"
        width, height = self.bitmaps[bitmap]
        ctypes.memset(buffer, 7, width * height * 4)
        return height


def new_context():
    return SimpleNamespace(
        dc_object=None, bitmap=None, window_dc=None, compatible_dc=None,
        last_hwnd=0, last_width=0, last_height=0,
    )


class PlainGdiBitBltTest(unittest.TestCase):
    def setUp(self):
        self.gdi = FakeGdi()
        patcher = patch.object(bitblt_gdi, "_gdi", self.gdi)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_frame_is_bgra_and_window_dc_is_released_in_the_same_call(self):
        context = new_context()
        frame = bitblt_gdi.capture_by_bitblt(context, 5, 64, 36, 0, 0, True)
        self.assertEqual((36, 64, 4), frame.shape)
        self.assertTrue(np.all(frame == 7))
        self.assertEqual({}, self.gdi.window_dcs)
        self.assertIsNone(context.window_dc)
        self.assertIsNone(context.dc_object)
        # Only process-wide ints are kept between frames.
        self.assertIsInstance(context.compatible_dc, int)
        self.assertIsInstance(context.bitmap, int)

    def test_capture_works_after_the_thread_that_built_the_buffer_ended(self):
        context = new_context()
        first = threading.Thread(
            target=bitblt_gdi.capture_by_bitblt, args=(context, 5, 64, 36, 0, 0, False)
        )
        first.start()
        first.join()
        frame = bitblt_gdi.capture_by_bitblt(context, 5, 64, 36, 0, 0, False)
        self.assertIsNotNone(frame)
        self.assertEqual(1, len(self.gdi.memory_dcs))

    def test_failed_frame_rebuilds_once_and_frees_old_handles(self):
        context = new_context()
        bitblt_gdi.capture_by_bitblt(context, 5, 64, 36, 0, 0, False)
        old_dc, old_bitmap = context.compatible_dc, context.bitmap
        self.gdi.fail_select_once = True
        frame = bitblt_gdi.capture_by_bitblt(context, 5, 64, 36, 0, 0, False)
        self.assertIsNotNone(frame)
        self.assertNotIn(old_dc, self.gdi.memory_dcs)
        self.assertNotIn(old_bitmap, self.gdi.bitmaps)
        self.assertEqual(1, len(self.gdi.memory_dcs))
        self.assertEqual({}, self.gdi.window_dcs)

    def test_resize_and_new_window_rebuild_the_buffer(self):
        context = new_context()
        bitblt_gdi.capture_by_bitblt(context, 5, 304, 201, 0, 0, False)
        frame = bitblt_gdi.capture_by_bitblt(context, 5, 192, 108, 0, 0, False)
        self.assertEqual((108, 192, 4), frame.shape)
        bitblt_gdi.capture_by_bitblt(context, 9, 192, 108, 0, 0, False)
        self.assertEqual(9, context.last_hwnd)
        self.assertEqual(1, len(self.gdi.memory_dcs))
        self.assertEqual(1, len(self.gdi.bitmaps))

    def test_clean_up_frees_everything_and_never_raises(self):
        context = new_context()
        bitblt_gdi.capture_by_bitblt(context, 5, 64, 36, 0, 0, False)
        bitblt_gdi.clean_up_bitblt(context)
        self.assertEqual(set(), self.gdi.memory_dcs)
        self.assertEqual({}, self.gdi.bitmaps)
        self.assertEqual(0, context.last_hwnd)
        broken = new_context()
        broken.compatible_dc = 12345  # unknown handle: fake raises
        bitblt_gdi.clean_up_bitblt(broken)  # must not raise

    def test_desktop_capture_releases_screen_dc(self):
        context = new_context()
        frame = bitblt_gdi.capture_desktop_by_bitblt(context, 32, 16, 0, 0)
        self.assertEqual((16, 32, 4), frame.shape)
        self.assertEqual({}, self.gdi.window_dcs)


class InstallTest(unittest.TestCase):
    def test_every_ok_module_that_imported_the_helpers_gets_ours(self):
        import importlib

        names = list(bitblt_gdi._REPLACED)
        modules = [importlib.import_module(m) for m in bitblt_gdi._OK_MODULES]
        saved = [{n: getattr(m, n) for n in names if hasattr(m, n)} for m in modules]
        utils = modules[0]
        try:
            with patch.object(bitblt_gdi.sys, "platform", "win32"):
                self.assertTrue(bitblt_gdi.install())
            for module, before in zip(modules, saved):
                for name in before:
                    self.assertIs(bitblt_gdi._REPLACED[name], getattr(module, name), (module, name))
            # composite_hwnds looks the capture helper up in bitblt_utils.
            self.assertIs(bitblt_gdi.capture_by_bitblt, utils.capture_by_bitblt)
            self.assertIs(bitblt_gdi.clean_up_bitblt, importlib.import_module(
                "ok.device.capture_methods.windows_graphics").clean_up_bitblt)
        finally:
            for module, before in zip(modules, saved):
                for name, value in before.items():
                    setattr(module, name, value)
            if hasattr(utils, bitblt_gdi._PATCH_MARKER):
                delattr(utils, bitblt_gdi._PATCH_MARKER)

    def test_config_installs_it(self):
        from pathlib import Path

        source = Path(__file__).resolve().parents[1].joinpath("src", "config.py").read_text("utf-8")
        self.assertIn("install_plain_gdi_bitblt()", source)


if __name__ == "__main__":
    unittest.main()
