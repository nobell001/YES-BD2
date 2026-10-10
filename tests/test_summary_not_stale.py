"""The 结算 after a watched run is that run's, never an older one (audit #50).

The 桌面分身 closed or the tool crashed before the run saved its report; the
home page then showed the previous run's 结算 as if this run had finished.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.tasks import run_report


class LoadRunTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        path = Path(self.folder.name) / "reports.json"
        path.write_text(
            json.dumps(
                {"一键完成日常": {"label": "一键完成日常", "started": 1000.25, "finished": 1100}}
            ),
            encoding="utf-8",
        )
        run_report.set_report_file(str(path))

    def tearDown(self):
        run_report.set_report_file(None)
        self.folder.cleanup()

    def test_the_watched_run_is_shown(self):
        self.assertEqual(1100, run_report.load_run("一键完成日常", 1000.25)["finished"])

    def test_an_older_run_is_not_taken_for_this_one(self):
        self.assertIsNone(run_report.load_run("一键完成日常", 2000.5))

    def test_without_a_start_time_it_loads_as_before(self):
        self.assertEqual(1100, run_report.load_run("一键完成日常", None)["finished"])
        self.assertIsNone(run_report.load_run("没有", 1000.25))


class HomeAfterRunTest(unittest.TestCase):
    def _page(self, loaded):
        from src.ui.shell import home

        page = mock.MagicMock()
        page._mode = "run"
        page._summary = {"label": "一键完成日常", "started": 10.0}  # the run before
        page._watching_label = "一键完成日常"
        page._watching_started = 2000.5
        page._asking_account = True
        with (
            mock.patch.object(home.run_report, "active", return_value=None),
            mock.patch.object(home.run_report, "load_run", return_value=loaded) as load_run,
            mock.patch.object(home.data, "current_task", return_value=None),
            mock.patch.object(home.clone_flow, "remote_task", return_value=None),
            mock.patch.object(home.clone_flow, "busy_in_clone", return_value=False),
        ):
            home.HomePage.refresh(page)
        load_run.assert_called_once_with("一键完成日常", 2000.5)
        return page

    def test_an_unsaved_run_leaves_the_home_page(self):
        page = self._page(None)
        self.assertIsNone(page._summary)
        self.assertEqual("idle", page._mode)

    def test_a_saved_run_opens_its_summary(self):
        finished = {"label": "一键完成日常", "started": 2000.5}
        page = self._page(finished)
        self.assertIs(finished, page._summary)
        self.assertEqual("summary", page._mode)


if __name__ == "__main__":
    unittest.main()
