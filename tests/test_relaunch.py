import unittest
from unittest import mock

from src.ui.shell import relaunch


class RelaunchEnvTest(unittest.TestCase):
    """The copy opened after a language change must not inherit the launcher's
    PYAPPIFY_PID: ok-script would close whatever program has that number now
    (review 2026-10-09)."""

    def test_launcher_pid_is_left_out(self):
        environ = {"PYAPPIFY_PID": "1234", "PYAPPIFY_VERSION": "1.2.3", "PATH": "x"}
        self.assertEqual(
            {"PYAPPIFY_VERSION": "1.2.3", "PATH": "x"}, relaunch.relaunch_env(environ)
        )
        self.assertIn("PYAPPIFY_PID", environ)

    def test_waiter_gets_the_environment_without_it(self):
        app = mock.Mock()
        with (
            mock.patch.object(relaunch.os, "name", "nt"),
            mock.patch.dict(relaunch.os.environ, {"PYAPPIFY_PID": "1234", "OK_BD2_X": "1"}),
            mock.patch.object(relaunch.subprocess, "Popen") as popen,
        ):
            self.assertTrue(relaunch.relaunch(app))
        env = popen.call_args.kwargs["env"]
        self.assertNotIn("PYAPPIFY_PID", env)
        self.assertEqual("1", env["OK_BD2_X"])
        app.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
