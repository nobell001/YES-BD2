"""BitBlt capture on plain GDI handles, safe to use from any thread.

Why (YES-BD2 #77): ok-script's ``bitblt_utils`` builds its device contexts
with ``win32ui.CreateDCFromHandle`` / ``CreateCompatibleDC``.  In pywin32
both return MFC *temporary* ``CDC`` objects (``CDC::FromHandle``), which live
in the handle map of the thread that made them and are freed when that thread
ends.  ok keeps them on the capture object and the live preview, the task
thread and the start-up checks all capture through the same object.  When the
preview's capture took longer than 2 s it started a new worker and the old
worker thread ended, freeing the stored ``CDC`` objects.  The next capture
then failed with "Select bitmap object failed" and its clean-up called
``DeleteDC`` on the freed object: access violation in mfc140u.dll, and the
whole tool closed.

Here every handle is a plain GDI handle (an int), which belongs to the
process, not to a thread.  The window DC is taken and released inside one
call, so nothing thread-bound is ever stored.  Only the memory DC and the
bitmap are kept between frames (same speed as before); callers still hold the
capture object's lock, so they are never used by two threads at once.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import numpy as np
from ok.util.logger import Logger

logger = Logger.get_logger(__name__)

PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
BGRA_CHANNEL_COUNT = 4
_PATCH_MARKER = "_ok_bd2_plain_gdi_bitblt"


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class _Gdi:
    """Typed user32/gdi32 calls on our own WinDLL objects.

    Own objects so the argtypes set here never change ``ctypes.windll`` for
    the rest of the program.  Handles are pointer sized on 64-bit Windows.
    """

    def __init__(self, user32=None, gdi32=None):
        if user32 is None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
        if gdi32 is None:
            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        HANDLE = ctypes.c_void_p
        self._typed(user32, "GetWindowDC", HANDLE, [HANDLE])
        self._typed(user32, "GetDC", HANDLE, [HANDLE])
        self._typed(user32, "ReleaseDC", ctypes.c_int, [HANDLE, HANDLE])
        self._typed(user32, "PrintWindow", wintypes.BOOL, [HANDLE, HANDLE, wintypes.UINT])
        self._typed(gdi32, "CreateCompatibleDC", HANDLE, [HANDLE])
        self._typed(gdi32, "CreateCompatibleBitmap", HANDLE, [HANDLE, ctypes.c_int, ctypes.c_int])
        self._typed(gdi32, "SelectObject", HANDLE, [HANDLE, HANDLE])
        self._typed(gdi32, "DeleteObject", wintypes.BOOL, [HANDLE])
        self._typed(gdi32, "DeleteDC", wintypes.BOOL, [HANDLE])
        self._typed(
            gdi32,
            "BitBlt",
            wintypes.BOOL,
            [HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
             HANDLE, ctypes.c_int, ctypes.c_int, wintypes.DWORD],
        )
        self._typed(
            gdi32,
            "GetDIBits",
            ctypes.c_int,
            [HANDLE, HANDLE, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
             ctypes.POINTER(BITMAPINFO), wintypes.UINT],
        )

    def _typed(self, dll, name, restype, argtypes):
        function = getattr(dll, name)
        function.restype = restype
        function.argtypes = argtypes
        setattr(self, name, function)


_gdi: _Gdi | None = None


def _api() -> _Gdi:
    global _gdi
    if _gdi is None:
        _gdi = _Gdi()
    return _gdi


def _handle(value) -> int:
    """A raw handle from an int or an old pywin32 object (``GetHandle``)."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    getter = getattr(value, "GetHandle", None) or getattr(value, "GetSafeHdc", None)
    try:
        return int(getter()) if getter else 0
    except Exception:
        return 0


def _release_cached(context) -> None:
    gdi = _api()
    memory_dc = _handle(getattr(context, "compatible_dc", None))
    bitmap = _handle(getattr(context, "bitmap", None))
    if memory_dc:
        # The bitmap is never left selected into the memory DC (see
        # _copy_pixels), so both can be deleted directly.
        gdi.DeleteDC(memory_dc)
    if bitmap:
        gdi.DeleteObject(bitmap)
    # A window DC is never kept by this module; one left by an older code path
    # is released (never DeleteDC'd: a GetDC/GetWindowDC DC must be released).
    window_dc = _handle(getattr(context, "window_dc", None))
    if window_dc:
        gdi.ReleaseDC(getattr(context, "last_hwnd", 0) or 0, window_dc)
    context.window_dc = None
    context.dc_object = None
    context.compatible_dc = None
    context.bitmap = None
    context.last_width = 0
    context.last_height = 0


def clean_up_bitblt(context) -> None:
    try:
        _release_cached(context)
    except Exception as exc:  # clean-up must never take the tool down
        logger.warning(f"clean_up_bitblt: {exc}")
    context.last_hwnd = 0


def clean_up_desktop_bitblt(context) -> None:
    try:
        _release_cached(context)
    except Exception as exc:
        logger.warning(f"clean_up_desktop_bitblt: {exc}")


def _ensure_buffer(context, source_dc: int, width: int, height: int) -> None:
    if (
        context.compatible_dc
        and context.bitmap
        and context.last_width == width
        and context.last_height == height
    ):
        return
    _release_cached(context)
    gdi = _api()
    memory_dc = gdi.CreateCompatibleDC(source_dc)
    if not memory_dc:
        raise OSError("CreateCompatibleDC failed")
    bitmap = gdi.CreateCompatibleBitmap(source_dc, width, height)
    if not bitmap:
        gdi.DeleteDC(memory_dc)
        raise OSError("CreateCompatibleBitmap failed")
    context.compatible_dc = int(memory_dc)
    context.bitmap = int(bitmap)
    context.last_width = width
    context.last_height = height


def _copy_pixels(context, source_dc: int, width: int, height: int, x: int, y: int):
    gdi = _api()
    _ensure_buffer(context, source_dc, width, height)
    memory_dc = context.compatible_dc
    old_bitmap = gdi.SelectObject(memory_dc, context.bitmap)
    if not old_bitmap:
        raise OSError("Select bitmap object failed")
    try:
        if not gdi.BitBlt(memory_dc, 0, 0, width, height, source_dc, x, y, SRCCOPY):
            raise OSError(f"BitBlt failed ({ctypes.get_last_error()})")
    finally:
        # GetDIBits needs the bitmap out of the DC.
        gdi.SelectObject(memory_dc, old_bitmap)
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height  # top-down rows, like GetBitmapBits
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = BI_RGB
    image = np.empty((height, width, BGRA_CHANNEL_COUNT), dtype=np.uint8)
    lines = gdi.GetDIBits(
        memory_dc, context.bitmap, 0, height, image.ctypes.data, ctypes.byref(info), DIB_RGB_COLORS
    )
    if lines != height:
        raise OSError(f"GetDIBits read {lines}/{height} rows")
    return image


def capture_by_bitblt(context, hwnd, width, height, x, y, render_full_content):
    if hwnd <= 0 or width <= 0 or height <= 0:
        logger.error(f"capture_by_bitblt invalid params: hwnd={hwnd}, w={width}, h={height}")
        return None
    gdi = _api()
    if context.last_hwnd != hwnd:
        _release_cached(context)
        context.last_hwnd = hwnd
    # Two tries: a failed frame (window just resized or recreated) rebuilds
    # the buffer once before giving up on this frame.
    for attempt in range(2):
        window_dc = gdi.GetWindowDC(hwnd)
        if not window_dc:
            logger.error(f"capture_by_bitblt: GetWindowDC failed for hwnd={hwnd}")
            return None
        try:
            if render_full_content:
                gdi.PrintWindow(hwnd, window_dc, PW_RENDERFULLCONTENT)
            return _copy_pixels(context, window_dc, width, height, x, y)
        except Exception as exc:
            logger.error(f"capture_by_bitblt exception (try {attempt + 1}): {exc}")
            _release_cached(context)
        finally:
            gdi.ReleaseDC(hwnd, window_dc)
    return None


def capture_desktop_by_bitblt(context, width, height, x, y):
    if width <= 0 or height <= 0:
        logger.error(f"capture_desktop_by_bitblt invalid params: w={width}, h={height}")
        return None
    gdi = _api()
    for attempt in range(2):
        screen_dc = gdi.GetDC(None)
        if not screen_dc:
            logger.error("capture_desktop_by_bitblt: GetDC failed")
            return None
        try:
            return _copy_pixels(context, screen_dc, width, height, x, y)
        except Exception as exc:
            logger.error(f"capture_desktop_by_bitblt exception (try {attempt + 1}): {exc}")
            _release_cached(context)
        finally:
            gdi.ReleaseDC(None, screen_dc)
    return None


_REPLACED = {
    "capture_by_bitblt": capture_by_bitblt,
    "clean_up_bitblt": clean_up_bitblt,
    "capture_desktop_by_bitblt": capture_desktop_by_bitblt,
    "clean_up_desktop_bitblt": clean_up_desktop_bitblt,
}

# Every ok module that imported these names directly (``from ... import``).
_OK_MODULES = (
    "ok.device.capture_methods.bitblt_utils",
    "ok.device.capture_methods.bitblt",
    "ok.device.capture_methods.windows_graphics",
    "ok.device.capture_methods",
)


def install() -> bool:
    """Swap ok's win32ui BitBlt helpers for the plain-GDI ones (Windows only)."""
    if sys.platform != "win32":
        return False
    import importlib

    utils = importlib.import_module("ok.device.capture_methods.bitblt_utils")
    if getattr(utils, _PATCH_MARKER, False):
        return True
    for name in _OK_MODULES:
        module = importlib.import_module(name)
        for attr, replacement in _REPLACED.items():
            if hasattr(module, attr):
                setattr(module, attr, replacement)
    setattr(utils, _PATCH_MARKER, True)
    return True
