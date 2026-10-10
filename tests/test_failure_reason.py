"""Every failure says why (Leo 2026-10-10).

Leo 05:52Z 「以後有失敗 盡量原因要寫」; 08:39Z 「你應該確保你的log是有用的了吧 很多次用戶傳
過來都沒有用」; 08:40Z 「像剛剛活動戰鬥失敗的那個只寫失敗 沒寫原因」.  A player's
问题摘要 said only 「普通战斗失败」, and mail, missions and pass ended the same
way: 「<task>：<step>失败。」 named the step and not what went wrong.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks import failure_reason, problem_report
from src.tasks.claim_page import ClaimPageMixin
from src.ui.shell import problem_image


def claim_task(name="普通邮箱领取"):
    task = object.__new__(ClaimPageMixin)
    task.name = name
    task.config = {}
    task.claim_log_name = "test"
    task.info = {}
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    task.log_info = lambda *_a, **_k: None
    task.log_warning = mock.Mock()
    task._save_flow_diagnostic = lambda *_a: None
    task._why = ""
    return task


class ClaimFailTest(unittest.TestCase):
    def test_a_title_never_read_is_the_reason(self):
        task = claim_task()
        clock = [0.0]
        task.capture_frame = lambda: None
        task._page_title_text = lambda _f, _l: "主页"
        task._match = lambda *_a: SimpleNamespace(score=-1.0)
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        with mock.patch("src.tasks.claim_page.monotonic", lambda: clock[0]):
            self.assertFalse(task._wait_for_title("邮箱", ("邮箱",)))
        self.assertFalse(task._claim_fail("打开邮箱"))
        status = task.info["状态"]
        self.assertTrue(status.startswith("普通邮箱领取：打开邮箱失败：没进到「邮箱」页面"), status)
        self.assertIn("「主页」", status)
        self.assertEqual(status[len("普通邮箱领取：") : -1], task.info["当前阶段"])

    def test_the_first_reason_of_a_run_stays(self):
        # Going home after the failure failing too is not why it failed.
        task = claim_task()
        task._note_why("按了「全部领取」，按钮一直亮着，没领到")
        task._note_why("从「邮箱」按了返回，没认出主页")
        task._claim_fail("领取")
        self.assertIn("按钮一直亮着", task.info["状态"])
        self.assertNotIn("返回", task.info["状态"])

    def test_no_reason_still_names_the_step(self):
        task = claim_task()
        task._claim_fail("打开邮箱")
        self.assertEqual("普通邮箱领取：打开邮箱失败。", task.info["状态"])
        task.log_warning.assert_not_called()


class HasReasonTest(unittest.TestCase):
    def test_reasons(self):
        self.assertFalse(failure_reason.has_reason("邮箱：打开邮箱失败。", "邮箱"))
        self.assertFalse(failure_reason.has_reason("白嫖抽抽乐确认服装池失败。", "白嫖抽抽乐"))
        self.assertTrue(failure_reason.has_reason("邮箱：打开邮箱失败：等了15秒。", "邮箱"))
        self.assertFalse(failure_reason.has_reason("完成", "邮箱"))


class EnsureTest(unittest.TestCase):
    """A run that returned False gets a reason before the 问题摘要 keeps it."""

    def _task(self, status, why=""):
        task = SimpleNamespace(name="白嫖抽抽乐", _why=why, info={"状态": status})
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_warning = mock.Mock()
        return task

    def _ensure(self, task, lines, status_before=None):
        with mock.patch.object(problem_report, "recent_lines", return_value=lines):
            return failure_reason.ensure(task, 0.0, status_before)

    def test_the_last_log_line_is_the_reason(self):
        task = self._task("白嫖抽抽乐确认服装池失败。")
        lines = [
            (1.0, 20, "白嫖抽抽乐：进入抽卡页"),
            (2.0, 20, "确认服装池：未确认服装抽抽乐页面，可能停留在装备池，不点击免费入口。"),
            (3.0, 20, "白嫖抽抽乐：恢复主页"),
        ]
        text = self._ensure(task, lines)
        self.assertEqual(
            "确认服装池失败：确认服装池：未确认服装抽抽乐页面，可能停留在装备池，不点击免费入口",
            text,
        )
        self.assertEqual(f"白嫖抽抽乐：{text}。", task.info["状态"])
        self.assertEqual(text, task.info["当前阶段"])
        task.log_warning.assert_called_once()

    def test_a_noted_reason_comes_first(self):
        task = self._task("白嫖抽抽乐：领取失败。", why="按钮一直亮着")
        self.assertEqual("领取失败：按钮一直亮着", self._ensure(task, [(1.0, 20, "别的")]))

    def test_nothing_logged_says_so(self):
        task = self._task("白嫖抽抽乐：领取失败。")
        self.assertEqual(f"领取失败：{failure_reason.NO_REASON}", self._ensure(task, []))

    def test_a_reason_already_written_is_kept(self):
        task = self._task("白嫖抽抽乐：领取失败：等了15秒。")
        self.assertEqual("领取失败：等了15秒", self._ensure(task, [(1.0, 20, "别的")]))
        self.assertEqual("白嫖抽抽乐：领取失败：等了15秒。", task.info["状态"])
        task.log_warning.assert_not_called()

    def test_a_status_without_failure_is_not_rewritten(self):
        # run_history reads 失败 in 状态: a run it counts as done stays done.
        task = self._task("白嫖抽抽乐：进入抽卡页")
        self._ensure(task, [(1.0, 20, "等待页面标题超时")])
        self.assertEqual("白嫖抽抽乐：进入抽卡页", task.info["状态"])
        self.assertEqual("进入抽卡页，失败：等待页面标题超时", task.info["当前阶段"])

    def test_an_old_status_from_before_the_run_is_not_this_failure(self):
        task = self._task("白嫖抽抽乐：领取失败。")
        self._ensure(task, [(1.0, 20, "等待页面标题超时")], status_before="白嫖抽抽乐：领取失败。")
        self.assertEqual("白嫖抽抽乐：领取失败。", task.info["状态"])
        self.assertEqual("失败：等待页面标题超时", task.info["当前阶段"])


    def test_it_never_breaks_the_run(self):
        task = self._task("白嫖抽抽乐：领取失败。")
        task.info_set = mock.Mock(side_effect=AttributeError("logger"))
        with self.assertLogs("ok", level="ERROR"):
            self.assertEqual("", self._ensure(task, []))

class FailedRunTest(unittest.TestCase):
    """The wrapper every task runs in adds the reason when a run returns False."""

    def _task(self, status):
        from src.tasks.BaseBD2Task import BaseBD2Task

        class Task(BaseBD2Task):
            def __init__(self):
                self._action_interval_lock = None  # as BaseBD2Task.__init__ sets
                self.name = "白嫖抽抽乐"
                self.info = {}
                self.warnings = []

            def info_set(self, key, value):
                self.info[key] = value

            def log_warning(self, message, notify=False):
                self.warnings.append(message)

            def run(self):
                self.info_set("状态", status)
                return False

        return Task()

    def test_a_step_failure_gets_its_last_log_line(self):
        task = self._task("白嫖抽抽乐确认服装池失败。")
        line = "确认服装池：未确认服装抽抽乐页面，可能停留在装备池，不点击免费入口。"
        with (
            mock.patch.object(problem_report, "recent_lines", return_value=[(1.0, 20, line)]),
            mock.patch.object(problem_report, "note_problem") as noted,
        ):
            self.assertFalse(task.run())
        self.assertEqual(f"白嫖抽抽乐：确认服装池失败：{line}", task.info["状态"])
        noted.assert_called_once()


class SummaryLastLineTest(unittest.TestCase):
    """「最后」 repeated the 停在 line once the reason went into both."""

    def test_a_line_repeating_where_it_stopped_is_passed_over(self):
        record = {
            "problem": {
                "task": "普通邮箱领取",
                "stage": "打开邮箱失败：没进到「邮箱」页面",
                "logs": [
                    {"level": 20, "text": "邮箱：等待页面标题 邮箱 超时。", "count": 1},
                    {
                        "level": 30,
                        "text": "普通邮箱领取：打开邮箱失败：没进到「邮箱」页面。",
                        "count": 1,
                    },
                ],
            }
        }
        self.assertEqual("邮箱：等待页面标题 邮箱 超时。", problem_image.last_line(record))


if __name__ == "__main__":
    unittest.main()
