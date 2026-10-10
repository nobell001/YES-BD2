import sys
import types
import unittest
from unittest import mock

from src.utils import clone_desktop

SID = "S-1-5-21-1-2-3-1001"


class _Key:
    def __init__(self, subkeys):
        self.subkeys = subkeys

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _winreg(user_extended=None, error=None):
    """A fake winreg: ``user_extended`` = number of HKCU identity subkeys, or
    None when the key is missing; ``error`` raised on opening instead."""
    fake = types.SimpleNamespace(HKEY_CURRENT_USER="HKCU")

    def open_key(_root, _path):
        if error is not None:
            raise error
        if user_extended is None:
            raise FileNotFoundError(_path)
        return _Key(user_extended)

    fake.OpenKey = open_key
    fake.QueryInfoKey = lambda key: (key.subkeys, 0, 0)
    return fake


class HelloOnlyAccountTest(unittest.TestCase):
    """The Windows Hello-only setting only matters for a Microsoft account
    (clone thread 2026-10-10): a local account has no switch to turn off."""

    def _run(self, *, policy=2, provider=None, user_extended=None, sid=SID, error=None):
        def read_hklm(path, name):
            if name == "DevicePasswordLessBuildVersion":
                return policy
            if name == "ProviderName" and sid and sid in path:
                return provider
            return None

        with (
            mock.patch.dict(sys.modules, {"winreg": _winreg(user_extended, error)}),
            mock.patch.object(clone_desktop, "_read_hklm", side_effect=read_hklm),
            mock.patch.object(clone_desktop, "_current_user_sid", return_value=sid),
        ):
            return clone_desktop.microsoft_account(), clone_desktop.hello_only()

    def test_microsoft_account_with_the_setting_is_stopped(self):
        self.assertEqual((True, True), self._run(provider="MicrosoftAccount"))

    def test_local_account_is_not_stopped(self):
        self.assertEqual((False, False), self._run(provider=None, user_extended=None))

    def test_identity_store_says_local_wins_over_hkcu(self):
        self.assertEqual((False, False), self._run(provider="Local", user_extended=1))

    def test_hkcu_identity_counts_without_identity_store(self):
        self.assertEqual((True, True), self._run(provider=None, user_extended=1))
        self.assertEqual((True, True), self._run(sid=None, user_extended=2))

    def test_empty_hkcu_identity_is_local(self):
        self.assertEqual((False, False), self._run(user_extended=0))

    def test_cannot_tell_still_stops(self):
        self.assertEqual((None, True), self._run(error=PermissionError("denied")))

    def test_setting_off_never_stops(self):
        self.assertEqual((True, False), self._run(policy=0, provider="MicrosoftAccount"))
        self.assertEqual((True, False), self._run(policy=None, provider="MicrosoftAccount"))

    def test_sid_from_whoami(self):
        clone_desktop._current_user_sid.cache_clear()
        out = f'"desktop-abc\\nobel","{SID}"\n'
        result = types.SimpleNamespace(stdout=out)
        with mock.patch.object(clone_desktop.subprocess, "run", return_value=result):
            self.assertEqual(SID, clone_desktop._current_user_sid())
        clone_desktop._current_user_sid.cache_clear()
        with mock.patch.object(clone_desktop.subprocess, "run", side_effect=OSError("no")):
            self.assertIsNone(clone_desktop._current_user_sid())
        clone_desktop._current_user_sid.cache_clear()


if __name__ == "__main__":
    unittest.main()
