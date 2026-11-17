# ruff: noqa: E402
"""Time YES-BD2's startup step by step on Windows, without showing a window.

Usage (from any folder):
  <python.exe> tools/dev/startup_profile.py <working folder copy> <out folder> [--cprofile]

Runs the same steps main.py runs after the single-instance check, builds the
main window (ok's pages + YES-BD2's own shell) but never shows it and never
starts the runtime or an event loop, then exits.  Prints one line per step
with the time since the process started.
"""

import os
import sys
import time

T_WALL0 = time.time()
try:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    c, e, k, u = (wintypes.FILETIME() for _ in range(4))
    k32.GetProcessTimes(
        k32.GetCurrentProcess(), ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)
    )
    created = ((c.dwHighDateTime << 32) | c.dwLowDateTime) / 1e7 - 11644473600
except Exception:
    created = T_WALL0

work, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
use_cprofile = "--cprofile" in sys.argv
os.makedirs(out, exist_ok=True)
lines = []


def mark(step):
    line = f"{time.time() - created:7.2f}s  {step}"
    lines.append(line)
    print(line, flush=True)


mark("python running")
os.chdir(work)
sys.path.insert(0, work)
sys.argv = [os.path.join(work, "main.py")]
profiler = None
if use_cprofile:
    import cProfile

    profiler = cProfile.Profile()
    profiler.enable()

from src.compat.taskbar_icon import set_process_app_id  # noqa: E402

set_process_app_id()
from src.compat import single_instance  # noqa: E402,F401
from src.compat.launcher_env import restore_launcher_env  # noqa: E402,F401
from src.utils import scheduled_start, scheduled_update  # noqa: E402,F401

mark("main.py early imports")
from src.compat.launcher_env import show_update_notice_once  # noqa: E402,F401
from src.compat.launcher_self_update import start_launcher_swap  # noqa: E402,F401

mark("launcher helpers imported")
from src.tasks.fiend_hunt.character_files import refresh_in_background  # noqa: E402,F401
from src.utils.disk_cleanup import clean_up  # noqa: E402,F401

mark("cleanup + character files imported")
from src.compat.dependency_guard import ensure_core_dependencies  # noqa: E402

ensure_core_dependencies()
mark("dependency check")
import ok  # noqa: E402

mark("import ok")
from src.compat.safe_json import install_safe_json  # noqa: E402

install_safe_json()
from src.config import config  # noqa: E402

mark("import src.config")
ok_instance = ok.OK(config)
mark("ok.OK(config)")
app = ok_instance.app
mark("QApplication + App")
from ok.ui.qt import MainWindow as _mw  # noqa: E402

mark("import ok MainWindow")
_mw.MainWindow.show = lambda self: None
_mw.MainWindow.bring_to_front = lambda self: None
_orig_init = _mw.MainWindow.__init__


def _timed_init(self, *a, **kw):
    _orig_init(self, *a, **kw)
    mark("ok MainWindow.__init__ done")


_mw.MainWindow.__init__ = _timed_init
app.do_show_main()
mark("main window built (YES-BD2 shell installed)")
if profiler is not None:
    profiler.disable()
    import pstats

    profiler.dump_stats(os.path.join(out, "startup.prof"))
    with open(os.path.join(out, "startup-top.txt"), "w", encoding="utf-8") as f:
        stats = pstats.Stats(profiler, stream=f)
        stats.sort_stats("cumulative").print_stats(120)
        stats.sort_stats("tottime").print_stats(60)
with open(os.path.join(out, "startup-steps.txt"), "a", encoding="utf-8") as f:
    f.write(
        f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} cprofile={use_cprofile}\n"
        + "\n".join(lines)
        + "\n"
    )
os._exit(0)
