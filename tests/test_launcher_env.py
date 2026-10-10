import json
import tempfile
import unittest
from pathlib import Path

from src.compat.launcher_env import (
    drop_stale_launcher_pid,
    find_install,
    restore_launcher_env,
    show_update_notice_once,
)


class LauncherEnvTest(unittest.TestCase):
    def make_install(self, root: Path, app_json: dict | None = None) -> Path:
        working = root / "data" / "apps" / "yes-bd2" / "working"
        working.mkdir(parents=True)
        (root / "yes-bd2.exe").write_bytes(b"")
        if app_json is not None:
            (working.parent / "app.json").write_text(json.dumps(app_json), encoding="utf-8")
        return working

    def test_fills_launcher_variables_when_not_started_by_launcher(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            working = self.make_install(
                root, {"current_version": "v0.1.6", "current_profile": "Full"}
            )
            environ = {}
            self.assertTrue(restore_launcher_env(working, environ, read_version=lambda _: "1.2.3"))
            self.assertEqual("1.2.3", environ["PYAPPIFY_VERSION"])
            self.assertEqual(str(root / "yes-bd2.exe"), environ["PYAPPIFY_EXECUTABLE"])
            self.assertEqual("v0.1.6", environ["PYAPPIFY_APP_VERSION"])
            self.assertEqual("v0.1.6", environ["PYAPPIFY_APP_STARTING_VERSION"])
            self.assertEqual("Full", environ["PYAPPIFY_APP_PROFILE"])
            self.assertEqual(str(working.parent / "app.json"), environ["PYAPPIFY_APP_JSON_PATH"])
            # 没有启动器在跑：不能补 PID，否则 kill_pyappify 会关错程序。
            self.assertNotIn("PYAPPIFY_PID", environ)

    def test_keeps_what_the_launcher_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            working = self.make_install(Path(folder), {"current_version": "v0.1.6"})
            environ = {"PYAPPIFY_VERSION": "1.2.3", "PYAPPIFY_APP_VERSION": "v0.1.7"}
            self.assertFalse(restore_launcher_env(working, environ, read_version=lambda _: "9.9.9"))
            self.assertEqual(
                {"PYAPPIFY_VERSION": "1.2.3", "PYAPPIFY_APP_VERSION": "v0.1.7"}, environ
            )

    def test_source_checkout_is_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            environ = {}
            self.assertIsNone(find_install(folder))
            self.assertFalse(restore_launcher_env(folder, environ, read_version=lambda _: "1.2.3"))
            self.assertEqual({}, environ)

    def test_unreadable_launcher_version_changes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            working = self.make_install(Path(folder))
            environ = {}
            self.assertFalse(restore_launcher_env(working, environ, read_version=lambda _: None))
            self.assertEqual({}, environ)

    def test_missing_app_json_still_enables_update_check(self):
        with tempfile.TemporaryDirectory() as folder:
            working = self.make_install(Path(folder))
            environ = {}
            self.assertTrue(restore_launcher_env(working, environ, read_version=lambda _: "1.2.3"))
            self.assertEqual("1.2.3", environ["PYAPPIFY_VERSION"])
            self.assertNotIn("PYAPPIFY_APP_VERSION", environ)


if __name__ == "__main__":
    unittest.main()


class UpdateNoticeOnceTest(unittest.TestCase):
    def env(self, starting="v0.1.11", current="v0.1.13"):
        return {"PYAPPIFY_APP_STARTING_VERSION": starting, "PYAPPIFY_APP_VERSION": current}

    def test_shows_once_then_never_again_for_that_version(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self.env()
            self.assertTrue(show_update_notice_once(folder, first))
            self.assertEqual("v0.1.11", first["PYAPPIFY_APP_STARTING_VERSION"])
            again = self.env()
            self.assertFalse(show_update_notice_once(folder, again))
            # 起始版本跟现在一样：ok 的 get_startup_version_change 回 None
            self.assertEqual("v0.1.13", again["PYAPPIFY_APP_STARTING_VERSION"])

    def test_next_update_shows_again(self):
        with tempfile.TemporaryDirectory() as folder:
            show_update_notice_once(folder, self.env())
            self.assertTrue(show_update_notice_once(folder, self.env(current="v0.1.14")))

    def test_nothing_to_do_without_an_update(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(show_update_notice_once(folder, self.env("v0.1.13", "v0.1.13")))
            self.assertFalse(show_update_notice_once(folder, {}))
            self.assertFalse((Path(folder) / "configs").exists())


class StaleLauncherPidTest(unittest.TestCase):
    """ok-script closes the PYAPPIFY_PID program at the first window: only the
    launcher may stay there (language-change relaunch, review 2026-10-09)."""

    def make_install(self, root: Path) -> Path:
        working = root / "data" / "apps" / "yes-bd2" / "working"
        working.mkdir(parents=True)
        (root / "yes-bd2.exe").write_bytes(b"")
        return working

    def test_launcher_keeps_its_pid(self):
        with tempfile.TemporaryDirectory() as folder:
            working = self.make_install(Path(folder))
            environ = {"PYAPPIFY_PID": "1234"}
            launcher = str(Path(folder) / "yes-bd2.exe")
            self.assertFalse(drop_stale_launcher_pid(working, environ, lambda _pid: launcher))
            self.assertEqual({"PYAPPIFY_PID": "1234"}, environ)

    def test_launcher_seen_through_the_english_link(self):
        with tempfile.TemporaryDirectory() as folder:
            real = Path(folder) / "real"
            real.mkdir()
            self.make_install(real)
            link = Path(folder) / "link"
            link.symlink_to(real, target_is_directory=True)
            working = link / "data" / "apps" / "yes-bd2" / "working"
            environ = {"PYAPPIFY_PID": "1234"}
            launcher = str(real / "yes-bd2.exe")
            self.assertFalse(drop_stale_launcher_pid(working, environ, lambda _pid: launcher))
            self.assertIn("PYAPPIFY_PID", environ)

    def test_any_other_program_loses_it(self):
        with tempfile.TemporaryDirectory() as folder:
            working = self.make_install(Path(folder))
            game = Path(folder) / "BrownDust II.exe"
            game.write_bytes(b"")
            for exe in (str(game), None):
                with self.subTest(exe=exe):
                    environ = {"PYAPPIFY_PID": "1234", "PYAPPIFY_VERSION": "1.2.3"}
                    self.assertTrue(drop_stale_launcher_pid(working, environ, lambda _pid: exe))
                    self.assertEqual({"PYAPPIFY_VERSION": "1.2.3"}, environ)

    def test_unreadable_pid_or_no_launcher_loses_it(self):
        with tempfile.TemporaryDirectory() as folder:
            working = self.make_install(Path(folder))
            environ = {"PYAPPIFY_PID": "abc"}
            self.assertTrue(drop_stale_launcher_pid(working, environ, lambda _pid: "x"))
            self.assertEqual({}, environ)
            # Source checkout: there is no launcher at all.
            environ = {"PYAPPIFY_PID": "1234"}
            self.assertTrue(drop_stale_launcher_pid(folder, environ, lambda _pid: "x"))
            self.assertEqual({}, environ)

    def test_nothing_to_do_without_a_pid(self):
        environ = {"PYAPPIFY_VERSION": "1.2.3"}
        self.assertFalse(drop_stale_launcher_pid(".", environ, lambda _pid: None))
        self.assertEqual({"PYAPPIFY_VERSION": "1.2.3"}, environ)
