import json
import tempfile
import time
import unittest
from pathlib import Path

from src.tasks import run_log, run_report
from src.tasks.run_history import week_start_ts
from src.ui.shell.report_page import header_line, run_line, task_state


class RunLogTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = self.folder.name

    def tearDown(self):
        run_report.set_report_file(None)
        self.folder.cleanup()

    def test_re_runs_are_kept_and_grouped(self):
        now = time.time()
        run_log.add("每周制作装备", run_log.FAIL, started=now - 100, finished=now - 90,
                    note="打开装备制作失败", via="一键完成周常", folder=self.path)
        run_log.add("末日之书", run_log.DONE, started=now - 80, finished=now - 40,
                    via="一键完成周常", folder=self.path)
        run_log.add("每周制作装备", run_log.DONE, started=now - 30, finished=now - 5,
                    folder=self.path)
        groups = run_log.group_by_task(run_log.entries(folder=self.path))
        self.assertEqual(["每周制作装备", "末日之书"], [name for name, _ in groups])
        runs = dict(groups)["每周制作装备"]
        self.assertEqual([run_log.FAIL, run_log.DONE], [run["state"] for run in runs])
        self.assertEqual(run_log.DONE, task_state(runs))
        self.assertIn("单独执行", run_line(runs[1]))

    def test_the_day_starts_from_the_saved_batch_reports(self):
        now = time.time()
        Path(self.path, "run_reports.json").write_text(json.dumps({
            "一键完成日常": {
                "label": "一键完成日常", "finished": now,
                "rows": [
                    {"key": "a", "name": "白嫖抽抽乐", "state": "done",
                     "started": now - 50, "finished": now - 10, "duration": 40, "note": ""},
                    {"key": "b", "name": "每周跑图", "state": "skip",
                     "started": None, "finished": None, "note": "本周已完成"},
                ],
            }
        }), encoding="utf-8")
        entries = run_log.entries(folder=self.path)
        self.assertEqual(["白嫖抽抽乐"], [entry["name"] for entry in entries])
        self.assertEqual("一键完成日常", entries[0]["via"])

    def test_batch_rows_log_next_to_their_report(self):
        run_report.set_report_file(str(Path(self.path, "reports.json")))
        run_report.begin("一键完成日常", "all", [("k", "领取邮件"), ("w", "每周跑图")])
        run_report.row_started("k")
        run_report.row_ended("k", run_report.DONE)
        run_report.row_ended("w", run_report.SKIP, "本周已完成")  # never started
        run_report.finish(run_report.ENDED_DONE)
        entries = run_log.entries(folder=self.path)
        self.assertEqual(["领取邮件"], [entry["name"] for entry in entries])

    def test_week_seconds_counts_this_game_week_only(self):
        start = week_start_ts(time.time())
        # Sunday night, before Monday's reset: last week.
        run_log.add("每日跑商", run_log.DONE, started=start - 600, finished=start - 60,
                    folder=self.path)
        run_log.add("领取邮件", run_log.DONE, started=start + 60, finished=start + 120,
                    folder=self.path)
        run_log.add("镜中之战", run_log.FAIL, started=start + 3600, finished=start + 3900,
                    folder=self.path)
        # Wednesday
        run_log.add("每周跑图", run_log.DONE, started=start + 2 * 86400,
                    finished=start + 2 * 86400 + 1200, folder=self.path)
        now = start + 3 * 86400
        self.assertEqual(60 + 300 + 1200, run_log.week_seconds(now=now, folder=self.path))
        self.assertEqual(360, run_log.week_seconds(now=start + 4000, folder=self.path))

    def test_header_shows_the_week_from_one_minute(self):
        self.assertNotIn("本周代跑", header_line(59))
        self.assertTrue(header_line(3 * 3600 + 20 * 60 + 29).endswith(" · 本周代跑 3 小时 20 分"))
        self.assertTrue(header_line(45 * 60 + 40).endswith(" · 本周代跑 46 分"))
