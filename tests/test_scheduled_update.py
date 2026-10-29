"""定时启动 updates the tool before the run (Leo 2026-10-22 「排程也先更新」)."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.utils import scheduled_start, scheduled_update

NOW = datetime(2026, 10, 22, 21, 0).astimezone()
VERSIONS = [{"version": "v0.2.10"}, {"version": "v0.2.9"}, {"version": "v0.3.0-beta"}]


class _Windows:
    """schtasks and the launcher, as seen from the tool."""

    def __init__(self):
        self.tasks = {}
        self.opened = []

    def run(self, command, **_kwargs):
        verb, name = command[1], command[3]
        if verb == "/Create":
            self.tasks[name] = Path(command[5]).read_text(encoding="utf-16")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if verb == "/Query":
            return SimpleNamespace(returncode=0 if name in self.tasks else 1, stdout="", stderr="")
        if verb == "/Delete":
            self.tasks.pop(name, None)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(command)

    def popen(self, command, **_kwargs):
        self.opened.append(command)


class UpdateTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.exe = root / "yes-bd2.exe"
        self.exe.write_bytes(b"")
        self.app_dir = root / "data" / "apps" / "yes-bd2"
        self.working = self.app_dir / "working"
        self.working.mkdir(parents=True)
        self.set_app(current_version="v0.2.9", update_state="idle")
        old = os.getcwd()
        os.chdir(self.working)
        self.addCleanup(os.chdir, old)
        self.windows = _Windows()
        self.launcher_open = False

    def set_app(self, **values):
        (self.app_dir / "app.json").write_text(json.dumps(values), encoding="utf-8")

    def hand(self, versions=VERSIONS, now=NOW):
        return scheduled_update.hand_to_launcher(
            str(self.working),
            now=now,
            versions=versions,
            run=self.windows.run,
            popen=self.windows.popen,
            running=lambda _exe: self.launcher_open,
        )

    def retry(self, now):
        return scheduled_update.on_retry(
            str(self.working),
            now=now,
            run=self.windows.run,
            running=lambda _exe: self.launcher_open,
        )

    def test_newest_release_only(self):
        self.assertEqual("v0.2.10", scheduled_update.newer_version(VERSIONS, "v0.2.9"))
        self.assertIsNone(scheduled_update.newer_version(VERSIONS, "v0.2.10"))
        self.assertIsNone(scheduled_update.newer_version(VERSIONS, None))
        self.assertIsNone(scheduled_update.newer_version([], "v0.2.9"))

    def test_a_newer_release_goes_through_the_launcher(self):
        self.assertTrue(self.hand())
        launcher = self.windows.opened[-1]
        self.assertEqual(str(self.exe), launcher[0])
        self.assertEqual(["--auto-start", "true", "--update-method", "auto"], launcher[1:])
        retry = self.windows.tasks[scheduled_update.retry_name()]
        self.assertIn("<TimeTrigger><StartBoundary>2026-10-22T21:10:00", retry)
        self.assertIn(scheduled_update.RETRY_FLAG, retry)
        # The launcher opens the tool after the update: a scheduled open.
        opened = NOW + timedelta(minutes=2)
        self.assertTrue(scheduled_update.take_pending(now=opened, run=self.windows.run))
        self.assertNotIn(scheduled_update.retry_name(), self.windows.tasks)
        self.assertFalse(scheduled_update.take_pending(now=NOW, run=self.windows.run))
        # The one-time look finds nothing left to do.
        self.assertFalse(self.retry(NOW + timedelta(minutes=10)))

    def test_the_run_after_the_update_is_the_slot_that_fired(self):
        # YES-BD2 #64: the slot (its 帳號) is the one at the first open.
        self.addCleanup(setattr, scheduled_update.scheduled_start, "opened_at", None)
        self.hand()
        scheduled_update.take_pending(now=NOW + timedelta(minutes=40), run=self.windows.run)
        self.assertEqual(NOW, scheduled_update.scheduled_start.opened_at)
        scheduled_update.scheduled_start.opened_at = None
        self.hand()
        self.assertTrue(self.retry(NOW + timedelta(minutes=10)))
        self.assertEqual(NOW, scheduled_update.scheduled_start.opened_at)

    def test_newest_already_runs_now(self):
        self.set_app(current_version="v0.2.10")
        self.assertFalse(self.hand())
        self.assertEqual([], self.windows.opened)
        self.assertEqual({}, self.windows.tasks)

    def test_launcher_open_or_no_network_runs_now(self):
        self.launcher_open = True
        self.assertFalse(self.hand())
        self.launcher_open = False

        def offline(*_a, **_k):
            raise TimeoutError("no network")

        launcher = SimpleNamespace(get_version_list=offline)
        with mock.patch.dict("sys.modules", {"pyappify": launcher}):
            self.assertFalse(self.hand(versions=None))
        self.assertEqual([], self.windows.opened)

    def test_a_source_checkout_never_hands_over(self):
        self.assertFalse(
            scheduled_update.hand_to_launcher(
                "/somewhere/else", now=NOW, versions=VERSIONS, run=self.windows.run,
                popen=self.windows.popen, running=lambda _exe: False,
            )
        )

    def test_failed_update_runs_the_old_version_at_the_retry(self):
        self.hand()
        self.assertTrue(self.retry(NOW + timedelta(minutes=10)))
        self.assertFalse(scheduled_update.PENDING_FILE.exists())
        self.assertNotIn(scheduled_update.retry_name(), self.windows.tasks)

    def test_still_updating_looks_again_then_gives_up_waiting(self):
        self.hand()
        self.launcher_open = True
        self.set_app(current_version="v0.2.9", update_state="updating")
        self.assertFalse(self.retry(NOW + timedelta(minutes=10)))
        self.assertIn("2026-10-22T21:20:00", self.windows.tasks[scheduled_update.retry_name()])
        self.assertTrue(self.retry(NOW + timedelta(minutes=55)))

    def test_a_stale_mark_does_not_start_a_run(self):
        self.hand()
        later = NOW + timedelta(minutes=scheduled_update.PENDING_MINUTES + 5)
        self.assertFalse(scheduled_update.take_pending(now=later, run=self.windows.run))
        self.assertFalse(scheduled_update.PENDING_FILE.exists())

    def test_retry_task_refused_runs_now(self):
        def refuse(command, **_kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="Access is denied.")

        self.windows.run = refuse
        self.assertFalse(self.hand())
        self.assertEqual([], self.windows.opened)

    def open_box(self, by_launcher=False, ticked=True, clone=False):
        scheduled_update.DAILY_CONFIG.parent.mkdir(exist_ok=True)
        scheduled_update.DAILY_CONFIG.write_text(
            json.dumps({scheduled_update.OPEN_BOX_KEY: ticked}), encoding="utf-8"
        )
        return scheduled_update.update_on_open(
            str(self.working),
            by_launcher,
            clone=lambda: clone,
            now=NOW,
            versions=VERSIONS,
            run=self.windows.run,
            popen=self.windows.popen,
            running=lambda _exe: self.launcher_open,
        )

    def test_the_home_box_updates_first_when_not_opened_by_the_launcher(self):
        # Player report 2026-10-25: opening the tool ran 一键日常 on the old version.
        self.assertTrue(self.open_box())
        launcher = self.windows.opened[-1]
        self.assertEqual(["--auto-start", "true", "--update-method", "auto"], launcher[1:])
        self.assertIn(scheduled_update.retry_name(), self.windows.tasks)
        # The launcher opens the new version: an ordinary open, the box runs it.
        self.assertFalse(scheduled_update.take_pending(now=NOW, run=self.windows.run))
        self.assertFalse(scheduled_update.PENDING_FILE.exists())
        self.assertNotIn(scheduled_update.retry_name(), self.windows.tasks)

    def test_the_home_box_failed_update_still_runs_at_the_retry(self):
        self.open_box()
        self.assertTrue(self.retry(NOW + timedelta(minutes=10)))

    def test_the_home_box_leaves_launcher_opens_unticked_and_clone_alone(self):
        self.assertFalse(self.open_box(by_launcher=True))  # the launcher just updated
        self.assertFalse(self.open_box(ticked=False))
        self.assertFalse(self.open_box(clone=True))
        self.set_app(current_version="v0.2.10")
        self.assertFalse(self.open_box())  # already the newest
        self.assertEqual([], self.windows.opened)

    def test_opened_by_launcher_and_box_reading(self):
        self.assertTrue(scheduled_update.opened_by_launcher({"PYAPPIFY_VERSION": "1.2.9"}))
        self.assertFalse(scheduled_update.opened_by_launcher({}))
        self.assertFalse(scheduled_update.auto_run_box_on("missing.json"))

    def test_flags(self):
        argv = ["main.py", scheduled_start.FLAG, scheduled_update.RETRY_FLAG]
        self.assertTrue(scheduled_update.take_retry_flag(argv))
        self.assertEqual(["main.py", scheduled_start.FLAG], argv)
        arguments = scheduled_start.tool_command(scheduled_update.RETRY_FLAG)[1]
        self.assertIn(scheduled_update.RETRY_FLAG, arguments)


if __name__ == "__main__":
    unittest.main()
