"""Linux test runs only (tools/linux_tests): make Windows-only imports load.

Not part of the product. Mirrors CPython 3.12 on Windows where
time.monotonic() ticks every ~15.6 ms (GetTickCount64)."""
import ctypes
import sys
import time
from unittest.mock import MagicMock

if sys.platform != "win32":
    for _name in (
        "WinDLL",
        "OleDLL",
        "windll",
        "oledll",
        "WINFUNCTYPE",
        "WinError",
        "FormatError",
        "GetLastError",
        "get_last_error",
        "set_last_error",
    ):
        if not hasattr(ctypes, _name):
            setattr(ctypes, _name, MagicMock(name=_name))
    _real_monotonic = time.monotonic
    _TICK = 1 / 64

    def _coarse_monotonic():
        return int(_real_monotonic() / _TICK) * _TICK

    time.monotonic = _coarse_monotonic
