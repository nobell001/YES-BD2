import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_commit_attribution.py"


class CommitAttributionTest(unittest.TestCase):
    def run_checker(
        self, message: str, identity: str = "Player <player@example.com>"
    ) -> subprocess.CompletedProcess[str]:
        name, email = identity[:-1].split(" <")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            message_path = Path(temp_dir) / "COMMIT_EDITMSG"
            message_path.write_text(message, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(CHECKER), "--message-file", str(message_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=env,
            )

    def run_history_check(self, revision: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), "--revision", revision],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_accepts_regular_commit_message(self):
        result = self.run_checker("fix(ui): keep attribution local\n")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Commit attribution check passed.", result.stdout)

    def test_rejects_claude_coauthor_trailer(self):
        result = self.run_checker(
            "fix(ui): example\n\n"
            "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\n"
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("Prohibited commit attribution found", result.stderr)
        self.assertIn("Co-Authored-By: Claude Fable 5", result.stderr)


    def test_rejects_claude_identity_on_the_new_commit(self):
        result = self.run_checker("fix: example\n", identity="Claude <noreply@anthropic.com>")

        self.assertEqual(1, result.returncode)
        self.assertIn("Author: Claude", result.stderr)

    def test_old_dev_history_is_left_alone(self):
        # dev already holds commits with old trailers and is never rewritten;
        # if they still counted, every run would be red and hide new ones.
        start = self._checked_after()
        if self._git("rev-parse", "--is-shallow-repository") == "false":
            old = self._git("log", "--format=%B", start)
            self.assertRegex(old, r"(?im)^co-authored-by:.*claude")

        result = self.run_history_check(start)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_new_history_is_still_checked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Player",
                "GIT_AUTHOR_EMAIL": "player@example.com",
                "GIT_COMMITTER_NAME": "Player",
                "GIT_COMMITTER_EMAIL": "player@example.com",
            }
            for args in (
                ["init", "-q"],
                [
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "fix: x\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>",
                ],
            ):
                subprocess.run(["git", *args], cwd=temp_dir, env=env, check=True)
            result = subprocess.run(
                [sys.executable, str(CHECKER), "--revision", "HEAD"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("Co-Authored-By: Claude Fable 5", result.stderr)

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()

    def _checked_after(self) -> str:
        checker = CHECKER.read_text(encoding="utf-8")
        start = checker.split('CHECKED_AFTER = "', 1)[1].split('"', 1)[0]
        known = subprocess.run(
            ["git", "cat-file", "-e", f"{start}^{{commit}}"], cwd=ROOT, capture_output=True
        )
        if known.returncode != 0:
            self.skipTest("shallow clone without the commit the check starts after")
        return start


if __name__ == "__main__":
    unittest.main()
