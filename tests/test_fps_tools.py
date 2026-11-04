"""Leo 2026-11-04: 「偵測到玩家開啟fps工具的時候提醒可能會導致失敗 然後3秒後開始
自動排呈的不受影響」「且報表要說明清楚」.

An FPS tool (RTSS, the counter MSI Afterburner draws with) puts numbers on the
picture the tool reads: 2026-10-12 a player's 「MHz」 was read into a recipe
name.  A start the player presses shows a note and starts by itself after
3 s; 定时启动 (no window) never sees it; reports name the tool.
"""

import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from src.tasks import run_log, run_report
from src.utils import fps_tools

_app = QApplication.instance() or QApplication([])


class _Proc(SimpleNamespace):
    pass


def _fake_psutil(names):
    procs = [_Proc(info={"pid": 100 + i, "name": name}) for i, name in enumerate(names)]
    return SimpleNamespace(process_iter=lambda _fields: iter(procs))


class NamesTest(unittest.TestCase):
    def test_known_names_any_case_each_once(self):
        self.assertEqual(
            ["RivaTuner (RTSS)", "Bandicam"],
            fps_tools.names_of(["RTSS.exe", "chrome.exe", "rtss.exe", "bdcam.exe", None]),
        )

    def test_always_running_vendor_apps_are_not_counted(self):
        # On most PCs whether the counter is on or not: warning would warn everyone.
        self.assertEqual(
            [],
            fps_tools.names_of(["NVIDIA Share.exe", "GameBar.exe", "RadeonSoftware.exe", "steam.exe"]),
        )

    def test_running_reads_this_session(self):
        # The made-up pids are not real processes: on Windows the real
        # ProcessIdToSessionId fails for them (YES-BD2 Build v0.2.30), so
        # every pid answers session 1 here, Bandicam (pid 101) another session.
        def session_of(pid, ref):
            ref._obj.value = 2 if pid == 101 else 1
            return 1

        kernel32 = SimpleNamespace(ProcessIdToSessionId=session_of)
        with mock.patch.dict(
            "sys.modules", {"psutil": _fake_psutil(["RTSS.exe", "bdcam.exe", "explorer.exe"])}
        ), mock.patch.object(fps_tools.ctypes, "windll", SimpleNamespace(kernel32=kernel32), create=True):
            self.assertEqual(["RivaTuner (RTSS)"], fps_tools.running())

    def test_running_never_raises(self):
        broken = SimpleNamespace(process_iter=mock.Mock(side_effect=OSError("denied")))
        with mock.patch.dict("sys.modules", {"psutil": broken}):
            self.assertEqual([], fps_tools.running())


class NoticeTest(unittest.TestCase):
    def setUp(self):
        self.window = QWidget()
        self.window.resize(900, 700)

    def tearDown(self):
        self.window.deleteLater()

    def test_no_window_means_no_note(self):
        # 定时启动 and 「打开就自动跑」 start without a window.
        from src.ui.shell import fps_notice

        with mock.patch.object(fps_tools, "running", side_effect=AssertionError("looked")):
            self.assertTrue(fps_notice.go_ahead(None))

    def test_no_fps_tool_starts_at_once(self):
        from src.ui.shell import fps_notice

        with mock.patch.object(fps_notice.FpsNotice, "exec", side_effect=AssertionError("shown")):
            self.assertTrue(fps_notice.go_ahead(self.window, []))

    def test_count_down_starts_by_itself(self):
        from src.ui.shell import fps_notice

        dialog = fps_notice.FpsNotice(["RivaTuner (RTSS)"], self.window, seconds=1)
        began = time.monotonic()
        self.assertEqual(1, dialog.exec())
        self.assertLess(time.monotonic() - began, 3.0)

    def test_three_seconds_by_default(self):
        from src.ui.shell import fps_notice

        self.assertEqual(3, fps_notice.COUNT_DOWN_S)
        dialog = fps_notice.FpsNotice(["Fraps"], self.window)
        self.assertIn("3", dialog.count.text())
        self.assertIn("Fraps", dialog.body.text())

    def test_cancel_stops_the_start(self):
        from src.ui.shell import fps_notice

        def press_cancel():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, fps_notice.FpsNotice) and widget.isVisible():
                    widget.cancel_button.click()

        QTimer.singleShot(200, press_cancel)
        self.assertFalse(fps_notice.go_ahead(self.window, ["Fraps"]))

    def test_a_broken_note_never_stops_a_run(self):
        from src.ui.shell import fps_notice

        with mock.patch.object(fps_notice, "FpsNotice", side_effect=RuntimeError("boom")):
            self.assertTrue(fps_notice.go_ahead(self.window, ["Fraps"]))


class StartTest(unittest.TestCase):
    """actions.start shows the note for a player's start only."""

    def _start(self, window, go_ahead):
        from src.ui.shell import actions, data

        task = SimpleNamespace(name="快速狩猎", enabled=False, paused=False, config={})
        started = []
        controller = SimpleNamespace(start=lambda t: started.append(t))
        og = SimpleNamespace(app=SimpleNamespace(start_controller=controller))
        asked = []

        def note(win):
            asked.append(win)
            return go_ahead

        with (
            mock.patch.object(data, "busy", lambda: False),
            mock.patch.object(data, "og", lambda: og),
            mock.patch("src.ui.shell.clone_flow.busy_in_clone", lambda: False),
            mock.patch("src.ui.shell.clone_flow.restart_outdated_clone", lambda *a: False),
            mock.patch("src.ui.shell.clone_flow.hand_to_clone", lambda *a: False),
            mock.patch("src.ui.shell.clone_flow.end_idle_clone", lambda *a: True),
            mock.patch("src.ui.shell.fps_notice.go_ahead", note),
            mock.patch.object(actions, "rearm_login_for_closed_game", lambda: None),
            mock.patch.object(actions, "bring_game_to_front", lambda: True),
        ):
            result = actions.start(task, window)
        return result, started, asked

    def test_player_start_goes_on_after_the_note(self):
        window = QWidget()
        result, started, asked = self._start(window, True)
        self.assertTrue(result)
        self.assertEqual(1, len(started))
        self.assertEqual([window], asked)

    def test_player_cancel_starts_nothing(self):
        result, started, _asked = self._start(QWidget(), False)
        self.assertFalse(result)
        self.assertEqual([], started)

    def test_scheduled_start_never_asks(self):
        result, started, asked = self._start(None, False)
        self.assertTrue(result)
        self.assertEqual(1, len(started))
        self.assertEqual([], asked)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        run_report.set_report_file(None)
        self.folder.cleanup()

    def test_a_failed_run_names_the_tool_in_todays_report(self):
        from src.ui.shell.report_page import fps_line

        now = time.time()
        with mock.patch.object(fps_tools, "running", lambda: ["RivaTuner (RTSS)"]):
            run_log.add("跑图", run_log.FAIL, started=now - 60, finished=now, folder=self.folder.name)
            run_log.add("跑商", run_log.DONE, started=now - 30, finished=now, folder=self.folder.name)
        runs = {entry["name"]: entry for entry in run_log.entries(folder=self.folder.name)}
        self.assertEqual(["RivaTuner (RTSS)"], runs["跑图"]["fps_tools"])
        self.assertNotIn("fps_tools", runs["跑商"])
        self.assertIn("RivaTuner (RTSS)", fps_line(runs["跑图"]["fps_tools"]))

    def test_the_batch_report_keeps_what_was_open(self):
        run_report.set_report_file(os.path.join(self.folder.name, "run_reports.json"))
        with mock.patch.object(fps_tools, "running", lambda: ["Bandicam"]):
            run_report.begin("一键完成日常", "all", [("a", "A")])
        self.assertEqual(["Bandicam"], run_report.active()["fps_tools"])
        run_report.finish(run_report.ENDED_DONE)

    def test_problem_report_shows_the_tool(self):
        from src.ui.shell import problem_image

        parts = problem_image.screen_parts({"fps_tools": ["RivaTuner (RTSS)"]})
        self.assertTrue(any("RivaTuner (RTSS)" in part for part in parts))


if __name__ == "__main__":
    unittest.main()
