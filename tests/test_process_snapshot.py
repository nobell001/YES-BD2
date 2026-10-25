import os
import sys
import unittest
from unittest import mock

from src.utils import process_snapshot


class ProcessSnapshotTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Toolhelp32 is Windows only")
    def test_snapshot_holds_this_process(self):
        names = dict(process_snapshot._snapshot())
        self.assertIn(os.getpid(), names)
        self.assertTrue(names[os.getpid()].lower().startswith("python"))

    def test_pids_named_ignores_case(self):
        listed = [(10, "CloneDesktop.exe"), (11, "explorer.exe"), (12, "BrownDust II.exe")]
        with mock.patch.object(process_snapshot, "process_names", return_value=listed):
            self.assertEqual([10, 12], process_snapshot.pids_named({"clonedesktop.exe", "BROWNDUST II.EXE"}))
            self.assertEqual([], process_snapshot.pids_named(set()))


if __name__ == "__main__":
    unittest.main()
