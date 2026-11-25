"""桌面分身: the startup programs are paused while the clone signs in.

Live 4K 2026-11-25 (Leo, player report 「启动桌面分身可能会导致steam退出」):
Windows started ``steam.exe -silent`` in the clone at sign-in, and Steam
allows one copy per PC, so the Steam on the real desktop logged off in the
same second, 28 of 28 times.  Closing it in the clone came too late; the
clone must not start it at all.
"""

import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from src.utils import clone_desktop

STEAM = r"E:\steam\steam.exe"


class _Key:
    def __init__(self, store, path):
        self.store = store
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _fake_winreg(values=None, refuse=()):
    """In-memory registry: ``values`` maps (root, path) -> {name: value};
    writes under a root in ``refuse`` fail like a missing Administrator."""
    store = {} if values is None else values
    fake = types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        HKEY_LOCAL_MACHINE="HKLM",
        KEY_SET_VALUE=2,
        KEY_QUERY_VALUE=1,
        REG_BINARY=3,
    )

    def open_key(root, path, *_args):
        if (root, path) not in store:
            raise FileNotFoundError(path)
        return _Key(store, (root, path))

    def create_key(root, path, *_args):
        if root in refuse:
            raise PermissionError(path)
        store.setdefault((root, path), {})
        return _Key(store, (root, path))

    def query(key, name):
        values = key.store[key.path]
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 3

    def set_value(key, name, _reserved, _kind, value):
        key.store[key.path][name] = value

    def delete_value(key, name):
        if name not in key.store[key.path]:
            raise FileNotFoundError(name)
        del key.store[key.path][name]

    def enum_value(key, index):
        items = list(key.store[key.path].items())
        if index >= len(items):
            raise OSError("no more")
        name, value = items[index]
        return name, value, 1

    fake.OpenKey = open_key
    fake.CreateKeyEx = create_key
    fake.QueryValueEx = query
    fake.SetValueEx = set_value
    fake.DeleteValue = delete_value
    fake.EnumValue = enum_value
    return fake, store


APPROVED_RUN = ("HKCU", clone_desktop._APPROVED + r"\Run")
APPROVED_HKLM_RUN = ("HKLM", clone_desktop._APPROVED + r"\Run")


class StartupPauseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name)
        for name, value in (
            ("DATA_DIR", data),
            ("STARTUP_PAUSE_FILE", data / "startup-paused.json"),
            ("LAUNCH_RESULT", data / "launch-result.txt"),
        ):
            patcher = mock.patch.object(clone_desktop, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.entries = [
            ("HKCU", "Run", "Steam", STEAM),
            ("HKCU", "Run", "Discord", r"D:\Apps\Discord\Update.exe"),
            ("HKCU", "Run", "SecurityHealth", r"C:\Windows\System32\SecurityHealthSystray.exe"),
            ("HKLM", "Run", "Riot", r"C:\Riot Games\RiotClientServices.exe"),
        ]
        patcher = mock.patch.object(
            clone_desktop, "_startup_entries", side_effect=lambda: list(self.entries)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"SystemRoot": r"C:\Windows"})
        env.start()
        self.addCleanup(env.stop)

    def _with(self, fake):
        return mock.patch.dict(sys.modules, {"winreg": fake})

    def test_steam_is_off_for_the_sign_in_and_back_after(self):
        fake, store = _fake_winreg()
        with self._with(fake):
            paused = clone_desktop.pause_startup_programs()
            self.assertIn("Steam", paused)
            off = store[APPROVED_RUN]["Steam"]
            self.assertFalse(clone_desktop.startup_on(off))
            # Windows' own programs are never touched.
            self.assertNotIn("SecurityHealth", store[APPROVED_RUN])
            restored = clone_desktop.restore_paused_startup()
        self.assertIn("Steam", restored)
        # It had no value before (= on): the value is removed again.
        self.assertNotIn("Steam", store[APPROVED_RUN])
        self.assertFalse(clone_desktop.STARTUP_PAUSE_FILE.exists())

    def test_old_value_comes_back_exactly(self):
        on = bytes([2] + [0] * 11)
        fake, store = _fake_winreg({APPROVED_RUN: {"Steam": on}})
        with self._with(fake):
            clone_desktop.pause_startup_programs()
            self.assertNotEqual(store[APPROVED_RUN]["Steam"], on)
            clone_desktop.restore_paused_startup()
        self.assertEqual(store[APPROVED_RUN]["Steam"], on)

    def test_one_the_player_turned_off_is_left_alone(self):
        off = bytes([3, 0, 0, 0, 9, 9, 9, 9, 9, 9, 9, 9])
        fake, store = _fake_winreg({APPROVED_RUN: {"Discord": off}})
        with self._with(fake):
            paused = clone_desktop.pause_startup_programs()
            self.assertNotIn("Discord", paused)
            clone_desktop.restore_paused_startup()
        self.assertEqual(store[APPROVED_RUN]["Discord"], off)

    def test_player_change_during_the_pause_is_kept(self):
        fake, store = _fake_winreg()
        with self._with(fake):
            clone_desktop.pause_startup_programs()
            theirs = bytes([3, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8])
            store[APPROVED_RUN]["Steam"] = theirs
            restored = clone_desktop.restore_paused_startup()
        self.assertNotIn("Steam", restored)
        self.assertEqual(store[APPROVED_RUN]["Steam"], theirs)

    def test_all_users_entry_without_administrator_is_skipped(self):
        fake, store = _fake_winreg(refuse=("HKLM",))
        with self._with(fake):
            paused = clone_desktop.pause_startup_programs()
        self.assertIn("Steam", paused)
        self.assertNotIn("Riot", paused)
        self.assertNotIn(APPROVED_HKLM_RUN, store)
        names = [e["name"] for e in clone_desktop._read_pause()["entries"]]
        self.assertNotIn("Riot", names)

    def test_tool_closed_halfway_puts_it_back_next_time(self):
        fake, store = _fake_winreg()
        with self._with(fake):
            clone_desktop.pause_startup_programs()
            # A new pause (next clone) first puts back what was left over.
            with mock.patch.object(clone_desktop, "_startup_entries", return_value=[]):
                clone_desktop.pause_startup_programs()
        self.assertNotIn("Steam", store[APPROVED_RUN])
        self.assertFalse(clone_desktop.STARTUP_PAUSE_FILE.exists())


class StartupPauseTimingTest(unittest.TestCase):
    """Put back 5 minutes after the clone signed in, at once when the viewer
    is not open, and never later than the longest sign-in wait."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name)
        self.pause = data / "startup-paused.json"
        self.result = data / "launch-result.txt"
        for name, value in (
            ("DATA_DIR", data),
            ("STARTUP_PAUSE_FILE", self.pause),
            ("LAUNCH_RESULT", self.result),
        ):
            patcher = mock.patch.object(clone_desktop, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = time.time()
        clone_desktop._save_pause(
            {"at": self.now, "entries": [{"hive": "HKCU", "key": "Run", "name": "Steam"}]}
        )

    def _done(self, after, viewer=True):
        with mock.patch.object(clone_desktop, "viewer_running", return_value=viewer):
            return clone_desktop.startup_pause_done(self.now + after)

    def test_waits_while_the_password_is_typed(self):
        self.assertFalse(self._done(400))

    def test_waits_five_minutes_after_sign_in(self):
        self.result.write_text("started", encoding="utf-8")
        signed_in = self.now + 20
        os.utime(self.result, (signed_in, signed_in))
        self.assertFalse(self._done(20 + 60))
        self.assertFalse(self._done(20 + clone_desktop.RESTORE_AFTER_SIGN_IN_SECONDS - 1))
        self.assertTrue(self._done(20 + clone_desktop.RESTORE_AFTER_SIGN_IN_SECONDS))

    def test_viewer_gone_puts_it_back(self):
        self.assertFalse(self._done(5, viewer=False))
        self.assertTrue(self._done(clone_desktop.RESTORE_NO_VIEWER_SECONDS, viewer=False))

    def test_never_longer_than_the_longest_wait(self):
        self.assertTrue(self._done(clone_desktop.PAUSE_MAX_SECONDS))

    def test_nothing_paused_nothing_to_do(self):
        self.pause.unlink()
        self.assertEqual(clone_desktop.restore_paused_startup_when_done(), [])


class StartupOnValueTest(unittest.TestCase):
    def test_values_task_manager_writes(self):
        self.assertTrue(clone_desktop.startup_on(None))
        self.assertTrue(clone_desktop.startup_on(bytes([2] + [0] * 11)))
        self.assertTrue(clone_desktop.startup_on(bytes([6] + [0] * 11)))
        self.assertFalse(clone_desktop.startup_on(bytes([3] + [0] * 11)))
        self.assertFalse(clone_desktop.startup_on(bytes([7] + [0] * 11)))
        self.assertFalse(clone_desktop.startup_on(clone_desktop._paused_off_value()))


if __name__ == "__main__":
    unittest.main()
