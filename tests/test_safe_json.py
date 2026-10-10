import os
import tempfile
import unittest
from unittest import mock

from src.compat import safe_json
from tests.helpers import held_open


class SafeJsonTest(unittest.TestCase):
    """A settings file cut by a power cut must not stop the tool (2026-10-09 review)."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = os.path.join(self.folder.name, "configs", "PVPTask.json")

    def test_round_trip_keeps_chinese_keys(self):
        safe_json.write_json_file(self.path, {"舞台移动方式": "键盘WASD走到舞台"})
        self.assertEqual(safe_json.read_json_file(self.path), {"舞台移动方式": "键盘WASD走到舞台"})
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_missing_file_reads_as_none(self):
        self.assertIsNone(safe_json.read_json_file(self.path))

    def test_file_cut_inside_a_character_reads_as_none_and_is_kept(self):
        os.makedirs(os.path.dirname(self.path))
        whole = '{"舞台移动方式": "键盘"}'.encode("utf-8")
        with open(self.path, "wb") as file:
            file.write(whole[:4])  # inside 舞
        self.assertIsNone(safe_json.read_json_file(self.path))
        with open(self.path + ".corrupt", "rb") as file:
            self.assertEqual(file.read(), whole[:4])

    def test_broken_json_reads_as_none(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as file:
            file.write('{"a": ')
        self.assertIsNone(safe_json.read_json_file(self.path))

    def test_file_held_open_elsewhere_is_still_written(self):
        safe_json.write_json_file(self.path, {"a": 1})
        with (
            mock.patch.object(safe_json.os, "replace", side_effect=PermissionError),
            mock.patch.object(safe_json.time, "sleep"),
        ):
            safe_json.write_json_file(self.path, {"a": 2})
        self.assertEqual(safe_json.read_json_file(self.path), {"a": 2})
        self.assertFalse(os.path.exists(self.path + ".tmp"))


class RecordFileTest(unittest.TestCase):
    """The tool's own record files: swapped in whole, and a file held open a
    moment is tried again; held longer, the caller is told and nothing is lost."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = os.path.join(self.folder.name, "record.json")
        safe_json.write_text_atomic(self.path, "旧")

    def _text(self):
        with open(self.path, encoding="utf-8") as file:
            return file.read()

    def test_held_open_a_moment_is_still_swapped_in(self):
        with held_open.replace_refused(self.path, 2), held_open.no_wait():
            safe_json.write_text_atomic(self.path, "新")
        self.assertEqual("新", self._text())
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_held_open_too_long_raises_and_keeps_the_old_file(self):
        with held_open.replace_refused(self.path), held_open.no_wait():
            with self.assertRaises(PermissionError):
                safe_json.write_text_atomic(self.path, "新")
        self.assertEqual("旧", self._text())
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_read_held_open_a_moment_is_tried_again(self):
        with held_open.read_refused(self.path, 2), held_open.no_wait():
            self.assertEqual("旧", safe_json.read_text_retrying(self.path))

    def test_read_held_open_too_long_raises(self):
        with held_open.read_refused(self.path), held_open.no_wait():
            with self.assertRaises(PermissionError):
                safe_json.read_text_retrying(self.path)

    def test_missing_file_is_not_waited_for(self):
        with mock.patch.object(safe_json.time, "sleep") as sleep:
            with self.assertRaises(FileNotFoundError):
                safe_json.read_text_retrying(self.path + ".missing")
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
