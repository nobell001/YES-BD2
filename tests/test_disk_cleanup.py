import os
import tempfile
import time
import unittest
from pathlib import Path

from src.utils import disk_cleanup


class DiskCleanupTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "logs").mkdir()
        (self.root / "probe_outputs").mkdir()

    def tearDown(self):
        self.folder.cleanup()

    def _file(self, relative: str, size: int, age_days: float = 0) -> Path:
        path = self.root / relative
        path.write_bytes(b"x" * size)
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_empty_crash_logs_go_and_the_current_one_stays(self):
        current = self._file("logs/crash-20261005-100219.log", 0)
        old_empty = self._file("logs/crash-20261005-083016.log", 0, 1)
        real = self._file("logs/crash-20261005-090935.log", 6501, 1)
        disk_cleanup.clean_up(self.root, current)
        self.assertTrue(current.exists())
        self.assertFalse(old_empty.exists())
        self.assertTrue(real.exists())

    def test_startup_error_log_stays(self):
        # main.py writes it when a start fails before the window; the next
        # start must not remove it (review 2026-10-09).
        log = self._file("logs/startup-error.log", 300, 30)
        disk_cleanup.clean_up(self.root)
        self.assertTrue(log.exists())

    def test_old_and_over_cap_failure_pictures_go(self):
        old = self._file("probe_outputs/old_failed.png", 10, 8)
        new = self._file("probe_outputs/new_failed.png", 10, 0)
        disk_cleanup.clean_up(self.root)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_long_guard_log_keeps_its_end(self):
        path = self._file("logs/dependency_guard.log", disk_cleanup.GUARD_LOG_MAX_BYTES + 10)
        disk_cleanup.clean_up(self.root)
        self.assertEqual(disk_cleanup.GUARD_LOG_MAX_BYTES // 2, path.stat().st_size)
