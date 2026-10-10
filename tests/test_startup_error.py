import ctypes
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main

ROOT = Path(__file__).resolve().parents[1]


class StartupErrorTest(unittest.TestCase):
    """A start that fails before the window leaves a log and a message
    (pythonw has no console; review 2026-10-09)."""

    def test_failed_start_writes_logs_startup_error_log(self):
        # A module missing after a half-installed update.
        code = (
            "import ctypes, runpy, sys\n"
            # Windows: the real message box would pop up on the desktop of
            # whoever runs the tests and wait for 確定 (live 2026-10-10).
            "if hasattr(ctypes, 'windll'):\n"
            "    ctypes.windll.user32.MessageBoxW = lambda *args: 1\n"
            "sys.modules['src.compat.elevate'] = None\n"
            f"runpy.run_path({str(ROOT / 'main.py')!r}, run_name='__main__')\n"
        )
        path = os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")]))
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=folder,
                env={**os.environ, "PYTHONPATH": path},
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertNotEqual(0, result.returncode)
            log = Path(folder) / "logs" / main.STARTUP_ERROR_LOG
            self.assertIn("src.compat.elevate", log.read_text(encoding="utf-8"))

    def test_message_box_names_the_log(self):
        windll = mock.MagicMock()
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(ctypes, "windll", windll, create=True),
            mock.patch("src.utils.clone_desktop.in_clone", return_value=False),
        ):
            main._show_startup_error("C:\\yes-bd2\\logs\\startup-error.log")
        text = windll.user32.MessageBoxW.call_args.args[1]
        self.assertIn("C:\\yes-bd2\\logs\\startup-error.log", text)

    def test_no_message_box_on_the_clone_desktop_or_off_windows(self):
        windll = mock.MagicMock()
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(ctypes, "windll", windll, create=True),
            mock.patch("src.utils.clone_desktop.in_clone", return_value=True),
        ):
            main._show_startup_error("x")
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(ctypes, "windll", windll, create=True),
        ):
            main._show_startup_error("x")
        windll.user32.MessageBoxW.assert_not_called()


if __name__ == "__main__":
    unittest.main()
