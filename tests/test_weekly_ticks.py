import json
import tempfile
import unittest
from pathlib import Path

from src.tasks import weekly_ticks
from src.tasks.run_history import week_start_ts
from tests.helpers import held_open

WEEK = 7 * 86400


class WeeklyTicksTest(unittest.TestCase):
    # Leo 2026-10-09: done this week = tick taken away; next week it comes back.

    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "weekly_ticks.json"
        self.now = week_start_ts() + 3 * 86400
        self.runs = {}

    def sync(self, config, now=None):
        return weekly_ticks.sync(
            config,
            [("街机", "浏览街机菜单"), ("书", "末日之书")],
            self.runs.get,
            now=self.now if now is None else now,
            path=self.path,
        )

    def done(self, name, at, ok=True):
        self.runs[name] = {"finished": at, "ok": ok}

    def test_done_this_week_loses_its_tick(self):
        config = {"街机": True, "书": True}
        self.done("浏览街机菜单", self.now - 60)
        self.assertEqual(["街机"], self.sync(config))
        self.assertEqual({"街机": False, "书": True}, config)

    def test_failed_or_last_weeks_run_keeps_the_tick(self):
        config = {"街机": True, "书": True}
        self.done("浏览街机菜单", self.now - 60, ok=False)
        self.done("末日之书", week_start_ts(self.now) - 60)
        self.assertEqual([], self.sync(config))
        self.assertEqual({"街机": True, "书": True}, config)

    def test_comes_back_next_week(self):
        config = {"街机": True, "书": True}
        self.done("浏览街机菜单", self.now - 60)
        self.sync(config)
        self.assertEqual(["街机"], self.sync(config, now=self.now + WEEK))
        self.assertEqual({"街机": True, "书": True}, config)

    def test_ticked_again_by_the_player_stays_until_it_runs_again(self):
        config = {"街机": True, "书": True}
        self.done("浏览街机菜单", self.now - 60)
        self.sync(config)
        config["街机"] = True  # the player wants it once more
        self.assertEqual([], self.sync(config))
        self.assertIs(True, config["街机"])
        self.done("浏览街机菜单", self.now + 600)
        self.assertEqual(["街机"], self.sync(config, now=self.now + 700))
        self.assertIs(False, config["街机"])

    def test_the_players_own_untick_is_not_given_back(self):
        config = {"街机": True, "书": False}
        self.sync(config)
        self.assertEqual([], self.sync(config, now=self.now + WEEK))
        self.assertIs(False, config["书"])

    def test_mark_done_during_a_run(self):
        config = {"街机": True, "书": True}
        weekly_ticks.mark_done(config, "书", self.now, now=self.now, path=self.path)
        self.assertIs(False, config["书"])
        # run_history stamps the same run a moment later: not a new completion.
        self.done("末日之书", self.now + 1)
        config["书"] = True
        self.assertEqual([], self.sync(config))
        self.assertEqual(["书"], self.sync({"街机": True, "书": False}, now=self.now + WEEK))

    def test_mark_done_started_last_week_keeps_the_tick(self):
        # Started Monday 07:59, done 08:01: last week's, the new week still has it.
        week = week_start_ts(self.now)
        config = {"街机": True, "书": True}
        weekly_ticks.mark_done(
            config, "书", week + 60, now=week + 60, path=self.path, started=week - 60
        )
        self.assertIs(True, config["书"])
        self.done("末日之书", week - 60)  # run_history stamps it with its start
        self.assertEqual([], self.sync(config, now=week + 120))
        self.assertIs(True, config["书"])

    # 2026-10-09 review: the records are swapped in whole, and a lost one
    # never leaves a 周常 unticked for good.

    def test_held_open_a_moment_is_still_written(self):
        config = {"街机": True, "书": True}
        weekly_ticks.mark_done(config, "书", self.now, now=self.now, path=self.path)
        self.done("浏览街机菜单", self.now - 60)
        with held_open.replace_refused(self.path, 2), held_open.no_wait():
            self.assertEqual(["街机"], self.sync(config))
        self.assertIn("街机", json.loads(self.path.read_text(encoding="utf-8")))
        self.assertFalse(Path(f"{self.path}.tmp").exists())

    def test_a_tick_is_taken_only_with_its_record_kept(self):
        config = {"街机": True, "书": True}
        weekly_ticks.mark_done(config, "书", self.now, now=self.now, path=self.path)
        before = self.path.read_bytes()
        self.done("浏览街机菜单", self.now - 60)
        with held_open.replace_refused(self.path), held_open.no_wait():
            self.assertEqual([], self.sync(config))
            weekly_ticks.mark_done(config, "街机", self.now, now=self.now, path=self.path)
        self.assertIs(True, config["街机"])
        self.assertEqual(before, self.path.read_bytes())
        # Once the file is free, the completion is seen and the tick goes.
        self.assertEqual(["街机"], self.sync(config))

    def test_records_held_open_are_not_read_as_empty(self):
        config = {"街机": True, "书": True}
        weekly_ticks.mark_done(config, "书", self.now, now=self.now, path=self.path)
        before = self.path.read_bytes()
        later = self.now + WEEK
        self.done("浏览街机菜单", later - 60)
        with held_open.read_refused(self.path), held_open.no_wait():
            self.assertEqual([], self.sync(config, now=later))
        self.assertEqual(before, self.path.read_bytes())  # 书's record not lost
        # Read again next time: last week's untick comes back.
        self.assertEqual(["书", "街机"], sorted(self.sync(config, now=later)))
        self.assertEqual({"街机": False, "书": True}, config)

    def test_broken_records_give_every_untick_back_next_week(self):
        config = {"街机": True, "书": True}
        weekly_ticks.mark_done(config, "书", self.now, now=self.now, path=self.path)
        self.path.write_bytes('{"书": {"done'.encode("utf-8"))  # cut by a power loss
        self.assertEqual([], self.sync(config))
        self.assertEqual('{"书": {"done', Path(f"{self.path}.corrupt").read_text("utf-8"))
        self.assertIs(False, config["书"])  # still this week
        self.assertEqual(["书"], self.sync(config, now=self.now + WEEK))
        self.assertIs(True, config["书"])
        # Given back once; from then on the player's own untick stays.
        config["街机"] = False
        self.assertEqual([], self.sync(config, now=self.now + 2 * WEEK))


if __name__ == "__main__":
    unittest.main()
