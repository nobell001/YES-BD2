import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

from src.compat import launcher_self_update, launcher_swap
from src.compat.launcher_self_update import start_launcher_swap
from src.compat.launcher_swap import (
    LAUNCHER_SHA256,
    LAUNCHER_VERSION,
    clean_leftovers,
    launcher_zip_url,
    needs_swap,
    swap,
    version_parts,
)

NEW_EXE = b"new launcher"
OLD_EXE = b"old launcher"


def zipped(exe_name: str = "yes-bd2.exe", data: bytes = NEW_EXE) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"yes-bd2/{exe_name}", data)
    return buffer.getvalue()


class LauncherVersionTest(unittest.TestCase):
    def test_only_older_launchers_are_swapped(self):
        self.assertTrue(needs_swap("1.2.3"))
        self.assertTrue(needs_swap("v1.1.9"))
        self.assertFalse(needs_swap(LAUNCHER_VERSION))
        self.assertFalse(needs_swap("1.2.10"))

    def test_unreadable_version_leaves_the_launcher_alone(self):
        self.assertFalse(needs_swap(None))
        self.assertFalse(needs_swap("unknown"))

    def test_pinned_to_our_own_release(self):
        # Never "latest": the update repository is filled before a release's
        # assets go up.  Never the upstream zip (points installs at ok-bd2).
        self.assertEqual(
            "https://github.com/nobell001/YES-BD2/releases/download/v0.1.18/yes-bd2-win32.zip",
            launcher_zip_url(),
        )
        self.assertRegex(LAUNCHER_SHA256, r"^[0-9a-f]{64}$")

    def test_swap_target_is_never_ahead_of_the_built_launcher(self):
        # A new launcher ships in one release first; the swap points at it
        # only in a later one, once that release's zip and sha256 exist. So
        # the built launcher may be newer than the swap target, never older.
        import re

        script = Path(__file__).resolve().parents[1] / "scripts" / "prepare_pyappify_launcher.ps1"
        built = re.search(
            r'\$LauncherVersion = "([0-9.]+)"', script.read_text(encoding="utf-8-sig")
        ).group(1)
        self.assertGreaterEqual(version_parts(built), version_parts(LAUNCHER_VERSION))


class SwapTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.exe = os.path.join(self.folder.name, "yes-bd2.exe")
        Path(self.exe).write_bytes(OLD_EXE)
        self.log = os.path.join(self.folder.name, "swap.log")
        self.good_sha = hashlib.sha256(NEW_EXE).hexdigest()

    def files(self):
        return sorted(os.listdir(self.folder.name))

    def test_swaps_in_the_checked_launcher(self):
        self.assertTrue(swap(self.exe, "url", self.good_sha, self.log, fetch=lambda _: zipped()))
        self.assertEqual(NEW_EXE, Path(self.exe).read_bytes())
        self.assertEqual(["swap.log", "yes-bd2.exe"], self.files())
        self.assertIn("success", Path(self.log).read_text(encoding="utf-8"))

    def test_wrong_checksum_keeps_the_old_launcher(self):
        self.assertFalse(swap(self.exe, "url", "0" * 64, self.log, fetch=lambda _: zipped()))
        self.assertEqual(OLD_EXE, Path(self.exe).read_bytes())
        self.assertEqual(["swap.log", "yes-bd2.exe"], self.files())

    def test_failed_download_keeps_the_old_launcher(self):
        def offline(_):
            raise RuntimeError("download failed: offline")

        self.assertFalse(swap(self.exe, "url", self.good_sha, self.log, fetch=offline))
        self.assertEqual(OLD_EXE, Path(self.exe).read_bytes())
        self.assertIn("offline", Path(self.log).read_text(encoding="utf-8"))

    def test_zip_without_the_launcher_keeps_the_old_one(self):
        fetch = lambda _: zipped(exe_name="other.exe")  # noqa: E731
        self.assertFalse(swap(self.exe, "url", self.good_sha, self.log, fetch=fetch))
        self.assertEqual(OLD_EXE, Path(self.exe).read_bytes())

    def test_failed_rename_puts_the_old_launcher_back(self):
        real_replace = os.replace

        def replace(source, target):
            if source.endswith(".new"):
                raise PermissionError("in use")
            return real_replace(source, target)

        launcher_swap.os.replace = replace
        try:
            self.assertFalse(
                swap(self.exe, "url", self.good_sha, self.log, fetch=lambda _: zipped())
            )
        finally:
            launcher_swap.os.replace = real_replace
        self.assertEqual(OLD_EXE, Path(self.exe).read_bytes())
        self.assertEqual(["swap.log", "yes-bd2.exe"], self.files())

    def test_second_swap_waits_for_the_first(self):
        Path(self.exe + ".updating").touch()
        fetch = Mock(return_value=zipped())
        self.assertFalse(swap(self.exe, "url", self.good_sha, self.log, fetch=fetch))
        fetch.assert_not_called()
        self.assertEqual(OLD_EXE, Path(self.exe).read_bytes())

    def test_stale_lock_is_taken_over(self):
        lock = Path(self.exe + ".updating")
        lock.touch()
        os.utime(lock, (0, 0))
        self.assertTrue(swap(self.exe, "url", self.good_sha, self.log, fetch=lambda _: zipped()))
        self.assertFalse(lock.exists())

    def test_download_retries_then_succeeds(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"zip"
        opener = Mock(side_effect=[OSError("busy"), response])
        self.assertEqual(b"zip", launcher_swap.download("url", opener=opener, sleep=lambda _: None))
        self.assertEqual(2, opener.call_count)

    def test_leftover_old_launchers_are_cleaned(self):
        for name in ("yes-bd2.exe.old", "yes-bd2.exe.old1700000000", "yes-bd2.exe.new"):
            Path(self.folder.name, name).touch()
        clean_leftovers(self.exe)
        self.assertEqual(["yes-bd2.exe"], self.files())


class StartSwapTest(unittest.TestCase):
    def install(self, root: str) -> str:
        working = Path(root, "data", "apps", "yes-bd2", "working")
        working.mkdir(parents=True)
        Path(root, "yes-bd2.exe").write_bytes(OLD_EXE)
        return str(working)

    def test_old_launcher_starts_a_detached_swap(self):
        with tempfile.TemporaryDirectory() as root:
            working = self.install(root)
            popen = Mock()
            started = start_launcher_swap(
                working, read_version=lambda _: "1.2.3", popen=popen, platform="nt"
            )
        self.assertTrue(started)
        command = popen.call_args.args[0]
        self.assertEqual("-I", command[1])
        self.assertTrue(command[2].endswith("launcher_swap.py"))
        self.assertEqual(
            [str(Path(root, "yes-bd2.exe")), launcher_zip_url(), LAUNCHER_SHA256],
            command[3:6],
        )
        self.assertTrue(command[6].endswith(os.path.join("logs", "launcher-update.log")))
        self.assertTrue(popen.call_args.kwargs["close_fds"])
        self.assertTrue(launcher_self_update.swap_started)

    def test_new_launcher_is_left_alone(self):
        with tempfile.TemporaryDirectory() as root:
            popen = Mock()
            started = start_launcher_swap(
                self.install(root),
                read_version=lambda _: LAUNCHER_VERSION,
                popen=popen,
                platform="nt",
            )
        self.assertFalse(started)
        popen.assert_not_called()

    def test_source_checkout_is_left_alone(self):
        popen = Mock()
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(
                start_launcher_swap(
                    root, read_version=lambda _: "1.2.3", popen=popen, platform="nt"
                )
            )
        popen.assert_not_called()

    def test_a_failing_start_never_blocks_the_tool(self):
        with tempfile.TemporaryDirectory() as root:
            popen = Mock(side_effect=OSError("no python"))
            self.assertFalse(
                start_launcher_swap(
                    self.install(root), read_version=lambda _: "1.2.3", popen=popen, platform="nt"
                )
            )

    def _swap_after(self, log_text):
        with tempfile.TemporaryDirectory() as root:
            working = self.install(root)
            if log_text is not None:
                Path(working, "logs").mkdir()
                Path(working, "logs", "launcher-update.log").write_text(log_text, encoding="utf-8")
            popen = Mock()
            started = start_launcher_swap(
                working, read_version=lambda _: "1.2.3", popen=popen, platform="nt"
            )
        return started, popen

    def test_after_a_failed_swap_it_retries_without_saying_next_open(self):
        # Audit #61: offline, every open said 「下次打开生效」 and every swap failed.
        log = (
            "2026-10-10 09:00:00 launcher swap: downloading https://x\n"
            "2026-10-10 09:00:09 launcher swap: failed, launcher left as is: download failed\n"
        )
        started, popen = self._swap_after(log)
        self.assertTrue(started)
        popen.assert_called_once()
        self.assertFalse(launcher_self_update.swap_started)

    def test_after_a_success_or_a_first_try_it_says_so(self):
        for log in (None, "", "x launcher swap: success, launcher is now abc\n"):
            with self.subTest(log=log):
                started, _popen = self._swap_after(log)
                self.assertTrue(started)
                self.assertTrue(launcher_self_update.swap_started)

    def test_the_latest_result_decides(self):
        log = (
            "a launcher swap: checksum mismatch 00, launcher left as is\n"
            "b launcher swap: success, launcher is now abc\n"
            "c launcher swap: downloading https://x\n"
        )
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "launcher-update.log")
            path.write_text(log, encoding="utf-8")
            self.assertFalse(launcher_self_update.last_swap_failed(path))
            path.write_text(
                log + "d launcher swap: written launcher differs, old launcher restored\n"
            )
            self.assertTrue(launcher_self_update.last_swap_failed(path))
            self.assertFalse(launcher_self_update.last_swap_failed(Path(root, "missing.log")))


if __name__ == "__main__":
    unittest.main()
