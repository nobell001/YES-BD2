"""跑完通知 to Server酱 (Leo 2026-10-22): the key, the send, the summary's
privacy, when it is sent, the setting and the one-time walk-through."""

import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ok import BaseTask

from src.tasks import DailyBatchTask as batch_module
from src.tasks import run_report
from src.tasks.DailyBatchTask import RUN_NOTIFY_NOTICE_KEY, DailyBatchTask, WeeklyBatchTask
from src.ui.shell import new_setting_notice
from src.utils import run_notify

TURBO_KEY = "SCT123456TabcdefGHIJ"
SC3_KEY = "sctp4321tAbCdEf"


class _Reply:
    def __init__(self, body: dict):
        self._raw = json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Opener:
    def __init__(self, body=None, error=None):
        self.body = body if body is not None else {"code": 0}
        self.error = error
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return _Reply(self.body)


def _report(**overrides) -> dict:
    report = {
        "label": "一键完成日常",
        "started": 1_000_000.0,
        "finished": 1_000_000.0 + 38 * 60,
        "ended": run_report.ENDED_FAILED,
        "notice": "",
        "rows": [
            {"key": "快速狩猎", "name": "快速狩猎", "state": run_report.DONE, "note": ""},
            {
                "key": "女神像",
                "name": "广场女神像",
                "state": run_report.SKIP,
                "note": "今天已经做完",
            },
            {
                "key": "每周跑图",
                "name": "每周跑图",
                "state": run_report.FAIL,
                "note": r"第三章卡住，图存在 D:\Users\Leo\yes-bd2\shot.png",
            },
        ],
    }
    report.update(overrides)
    return report


class SettingsFileCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(run_notify, "SETTINGS_FILE", Path(folder.name) / "n.json")
        patcher.start()
        self.addCleanup(patcher.stop)


class KeyTest(unittest.TestCase):
    def test_turbo_and_sc3_go_to_their_own_hosts(self):
        self.assertEqual(
            f"https://sctapi.ftqq.com/{TURBO_KEY}.send", run_notify.endpoint(TURBO_KEY)
        )
        self.assertEqual(
            f"https://4321.push.ft07.com/send/{SC3_KEY}.send", run_notify.endpoint(SC3_KEY)
        )

    def test_pasted_extras_are_cleaned(self):
        for pasted in (
            f"  {TURBO_KEY}\n",
            f"“{TURBO_KEY}”",
            f"https://sctapi.ftqq.com/{TURBO_KEY}.send?title=hi",
        ):
            self.assertEqual(TURBO_KEY, run_notify.clean(pasted), pasted)

    def test_other_text_is_not_a_key(self):
        for text in ("", "hello", "SCT", "1234567890", "sctp12"):
            self.assertFalse(run_notify.valid(text), text)

    def test_masked_hides_the_middle(self):
        shown = run_notify.masked(TURBO_KEY)
        self.assertTrue(shown.startswith("SCT12") and shown.endswith("HIJ"))
        self.assertNotIn("abcdef", shown)


class SendTest(unittest.TestCase):
    def test_posts_title_and_body(self):
        opener = _Opener()
        self.assertEqual("", run_notify.send(TURBO_KEY, "标题", "内容", opener))
        (request,) = opener.requests
        self.assertEqual("POST", request.get_method())
        sent = urllib.parse.parse_qs(request.data.decode())
        self.assertEqual(["标题"], sent["title"])
        self.assertEqual(["内容"], sent["desp"])

    def test_title_is_cut_to_server_limit(self):
        opener = _Opener()
        run_notify.send(TURBO_KEY, "长" * 50, "", opener)
        sent = urllib.parse.parse_qs(opener.requests[0].data.decode())
        self.assertEqual(run_notify.TITLE_MAX, len(sent["title"][0]))

    def test_each_failure_says_why(self):
        cases = (
            (_Opener(error=urllib.error.URLError("down")), run_notify.NO_NETWORK),
            (
                _Opener({"code": 40001, "message": "超过当天的发送次数限制"}),
                run_notify.OUT_OF_QUOTA,
            ),
            (_Opener({"code": 40001, "message": "bad pushkey"}), run_notify.BAD_KEY),
        )
        for opener, why in cases:
            self.assertEqual(why, run_notify.send(TURBO_KEY, "t", "b", opener))
        self.assertEqual(run_notify.BAD_SHAPE, run_notify.send("nope", "t", "b", _Opener()))

    def test_other_server_words_are_passed_on(self):
        error = run_notify.send(TURBO_KEY, "t", "b", _Opener({"code": 9, "message": "维护中"}))
        self.assertIn("维护中", error)

    def test_http_error_without_body(self):
        error = urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b""))
        self.assertEqual(
            run_notify.BAD_KEY, run_notify.send(TURBO_KEY, "t", "b", _Opener(error=error))
        )


class SummaryTest(unittest.TestCase):
    def test_counts_and_failed_reason(self):
        with mock.patch.object(run_notify, "_account_line", return_value=""):
            title, body = run_notify.summary(_report())
        self.assertTrue(title.startswith("YES-BD2 日常"))
        self.assertIn("1 项失败", title)
        self.assertLessEqual(len(title), run_notify.TITLE_MAX)
        self.assertIn("完成 1 项", body)
        self.assertIn("跳过 1 项", body)
        self.assertIn("每周跑图", body)
        self.assertIn("第三章卡住", body)
        self.assertIn("用时 38 分钟", body)

    def test_no_pc_user_name(self):
        _title, body = run_notify.summary(_report())
        self.assertNotIn("Leo", body)

    def test_account_number_never_its_name(self):
        account = SimpleNamespace(number=2, name="我的大号")
        with (
            mock.patch("src.utils.accounts.has_several", return_value=True),
            mock.patch("src.utils.accounts.current", return_value=account),
        ):
            _title, body = run_notify.summary(_report())
        self.assertIn("账号 2", body)
        self.assertNotIn("我的大号", body)

    def test_titles_by_ending(self):
        for ended, words in (
            (run_report.ENDED_DONE, "全部完成"),
            (run_report.ENDED_ABORTED, "中途停了"),
            (run_report.ENDED_SETUP, "没有开始跑"),
        ):
            report = _report(ended=ended)
            if ended == run_report.ENDED_DONE:
                report["rows"] = report["rows"][:2]
            self.assertIn(words, run_notify.summary(report)[0], ended)


class AfterRunTest(SettingsFileCase):
    def _run(self, report):
        jobs = []
        started = run_notify.after_run(report, start=jobs.append)
        return started, jobs

    def test_off_by_default(self):
        self.assertFalse(run_notify.enabled())
        self.assertEqual((False, []), self._run(_report()))

    def test_sends_and_remembers_the_result(self):
        run_notify.set_sendkey(TURBO_KEY)
        run_notify.set_enabled(True)
        started, jobs = self._run(_report())
        self.assertTrue(started)
        with mock.patch.object(run_notify, "send", return_value="") as send:
            jobs[0]()
        send.assert_called_once()
        self.assertEqual(TURBO_KEY, send.call_args.args[0])
        at, error = run_notify.last_result()
        self.assertIsNotNone(at)
        self.assertEqual("", error)

    def test_failure_is_remembered_with_why(self):
        run_notify.set_sendkey(TURBO_KEY)
        run_notify.set_enabled(True)
        _started, jobs = self._run(_report())
        with mock.patch.object(run_notify, "send", return_value=run_notify.NO_NETWORK):
            jobs[0]()
        self.assertEqual(run_notify.NO_NETWORK, run_notify.last_result()[1])

    def test_manual_stop_is_not_sent(self):
        run_notify.set_sendkey(TURBO_KEY)
        run_notify.set_enabled(True)
        self.assertFalse(self._run(_report(ended=run_report.ENDED_STOPPED))[0])

    def test_on_without_a_key_is_not_sent(self):
        run_notify.set_enabled(True)
        self.assertFalse(self._run(_report())[0])

    def test_new_key_forgets_the_old_result(self):
        run_notify.set_sendkey(TURBO_KEY)
        run_notify._record("x")
        run_notify.set_sendkey(SC3_KEY)
        self.assertEqual((None, ""), run_notify.last_result())


class ProblemTest(SettingsFileCase):
    def setUp(self):
        super().setUp()
        run_notify._problem_day = None
        self.addCleanup(setattr, run_notify, "_problem_day", None)

    def test_login_stuck_is_sent_once_a_day(self):
        run_notify.set_sendkey(TURBO_KEY)
        run_notify.set_enabled(True)
        jobs = []
        self.assertTrue(run_notify.after_problem(run_notify.LOGIN_STUCK, start=jobs.append))
        self.assertFalse(run_notify.after_problem(run_notify.LOGIN_STUCK, start=jobs.append))
        with mock.patch.object(run_notify, "send", return_value="") as send:
            jobs[0]()
        title, body = send.call_args.args[1:3]
        self.assertIn("没有开始跑", title)
        self.assertIn("登录卡住", body)

    def test_off_sends_nothing(self):
        self.assertFalse(run_notify.after_problem(run_notify.LOGIN_STUCK, start=lambda _go: None))


class FinishHookTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        run_report.set_report_file(str(Path(folder.name) / "reports.json"))
        self.addCleanup(run_report.set_report_file, None)

    def _finish(self, label, ended=run_report.ENDED_DONE):
        run_report.begin(label, "全部已启用子任务", [("快速狩猎", "快速狩猎")])
        with mock.patch.object(run_notify, "after_run") as after_run:
            run_report.finish(ended)
        return after_run

    def test_daily_report_is_handed_over_however_it_ends(self):
        for ended in (run_report.ENDED_DONE, run_report.ENDED_ERROR, run_report.ENDED_STOPPED):
            self.assertEqual(1, self._finish(DailyBatchTask.batch_label, ended).call_count)

    def test_weekly_report_is_not(self):
        self.assertEqual(0, self._finish(WeeklyBatchTask.batch_label).call_count)

    def test_label_matches_the_daily_batch(self):
        self.assertEqual(DailyBatchTask.batch_label, run_report.DAILY_LABEL)


class NeverStartedTest(SettingsFileCase):
    """定时启动 writes a report with no rows when the run never got going."""

    def _report(self):
        return _report(rows=[], ended=run_report.ENDED_ERROR, notice="电脑锁屏了，没办法开始")

    def test_says_why_it_did_not_start(self):
        title, body = run_notify.summary(self._report())
        self.assertIn("没有开始跑", title)
        self.assertIn("电脑锁屏了", body)
        self.assertNotIn("完成 0 项", body)

    def test_not_twice_after_the_login_message(self):
        run_notify.set_sendkey(TURBO_KEY)
        run_notify.set_enabled(True)
        self.addCleanup(setattr, run_notify, "_problem_day", None)
        run_notify._problem_day = run_report.game_day_key()
        self.assertFalse(run_notify.after_run(self._report(), start=lambda _go: None))
        self.assertTrue(run_notify.after_run(_report(), start=lambda _go: None))

    def test_not_twice_when_the_tool_in_the_clone_said_it(self):
        # Leo 2026-11-16 「微信通知 一樣要通知」: the tool in the 桌面分身 is
        # another process; its login message must still stop the desktop
        # tool's 定时启动 watchdog from saying the same again.
        run_notify.set_sendkey(TURBO_KEY)
        run_notify.set_enabled(True)
        self.addCleanup(setattr, run_notify, "_problem_day", None)
        run_notify._problem_day = None
        self.assertTrue(run_notify.after_problem(run_notify.LOGIN_STUCK, start=lambda _go: None))
        run_notify._problem_day = None  # the other process
        self.assertFalse(run_notify.after_problem(run_notify.LOGIN_STUCK, start=lambda _go: None))
        self.assertFalse(run_notify.after_run(self._report(), start=lambda _go: None))
        self.assertTrue(run_notify.after_run(_report(), start=lambda _go: None))

    def test_maintenance_is_its_own_message(self):
        run_notify.set_sendkey(TURBO_KEY)
        run_notify.set_enabled(True)
        self.addCleanup(setattr, run_notify, "_problem_day", None)
        run_notify._problem_day = run_report.game_day_key()
        report = _report(
            rows=[],
            ended=run_report.ENDED_SETUP,
            maintenance=True,
            notice="游戏正在维护（到 10/22 11:00），已关闭游戏，这次没有跑。",
        )
        self.assertTrue(run_notify.after_run(report, start=lambda _go: None))
        title, body = run_notify.summary(report)
        self.assertIn("没有开始跑", title)
        self.assertIn("游戏正在维护", body)


def _load(saved: dict | None) -> DailyBatchTask:
    task = DailyBatchTask(executor=SimpleNamespace(scene=None), app=SimpleNamespace())

    def load(_self):
        _self.config = {**_self.default_config, **(saved or {})}

    def read(path):
        return dict(saved or {}) if "DailyBatchTask" in str(path) else {}

    with (
        mock.patch.object(batch_module, "_read_json", side_effect=read),
        mock.patch.object(BaseTask, "load_config", load),
    ):
        task.load_config()
    return task


class NoticeTest(unittest.TestCase):
    def test_new_install_is_not_asked(self):
        self.assertFalse(_load(None).config[RUN_NOTIFY_NOTICE_KEY])

    def test_player_from_before_is_asked_once(self):
        self.assertTrue(_load({"启用": True}).config[RUN_NOTIFY_NOTICE_KEY])
        self.assertFalse(
            _load({"启用": True, RUN_NOTIFY_NOTICE_KEY: False}).config[RUN_NOTIFY_NOTICE_KEY]
        )

    def test_steps_point_at_settings_row(self):
        row, item = object(), object()
        shell = mock.Mock()
        shell.sidebar.items = {"settings": item}
        shell.pages = {"settings": SimpleNamespace(wechat_row=row)}
        first, second = new_setting_notice.run_notify_steps(shell)
        self.assertIs(item, first.target())
        second.before()
        shell.navigate.assert_called_with("settings")
        self.assertIs(row, second.target())

    def test_is_in_the_notice_list(self):
        self.assertIn(new_setting_notice.show_run_notify_notice, new_setting_notice.NOTICES)


class TranslationTest(unittest.TestCase):
    def test_every_new_text_is_in_the_catalogs(self):
        import gettext

        from src.ui.shell import run_notify_dialog

        root = Path(__file__).resolve().parents[1] / "i18n"
        shell = mock.Mock()
        shell.pages = {}
        texts = {
            run_notify.NO_NETWORK,
            run_notify.BAD_KEY,
            run_notify.BAD_SHAPE,
            run_notify.OUT_OF_QUOTA,
            run_notify.SERVER_SAID,
            run_notify.TEST_TITLE,
            run_notify.TEST_BODY,
            run_notify.LOGIN_STUCK,
            run_notify_dialog.PRIVACY,
            run_notify_dialog.SENT,
            run_notify_dialog.SENDING,
            run_notify_dialog.KEY_OK,
            *run_notify_dialog.STEPS,
            "日常 {day}：{n} 项失败",
            "用时 {n} 分钟",
            "{when} 已送达",
            "{when} 没送出：{why}",
        }
        for step in new_setting_notice.run_notify_steps(shell):
            texts |= {step.title, step.body}
        for language in ("en_US", "ja_JP", "ko_KR"):
            catalog = gettext.translation("ok", root, languages=[language])
            for text in texts:
                self.assertNotEqual(text, catalog.gettext(text), (language, text))


if __name__ == "__main__":
    unittest.main()
