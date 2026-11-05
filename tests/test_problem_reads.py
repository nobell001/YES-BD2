"""问题摘要 keeps what each check read before the problem (Leo 2026-11-05
「常常用戶log發過來也找不到原因」: a record said where it stopped, never
what the ways of checking read)."""

import logging
import tempfile
import time
import unittest

import numpy as np

from src.tasks import problem_report
from src.ui.shell import problem_image
from tests.test_problem_report import Task



def setUpModule():
    # The picture is drawn with Qt fonts: a QApplication must exist.
    from PySide6.QtWidgets import QApplication

    global _APP
    _APP = QApplication.instance() or QApplication([])

class ProblemReadsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        problem_report.set_root(self.folder.name)
        problem_report.install_log_ring()
        problem_report._reads.clear()

    def tearDown(self):
        logging.getLogger("ok").removeHandler(problem_report._ring)
        problem_report._ring = None
        problem_report._drop()
        problem_report._last_written.clear()
        problem_report._reads.clear()
        problem_report.set_root(None)
        self.folder.cleanup()

    def test_the_failure_keeps_the_last_value_of_each_check(self):
        task = Task("广场女神像")
        with problem_report.run_scope(task) as scope:
            now = time.time()
            problem_report._current["started"] = now - 3 * problem_report.READ_WINDOW
            problem_report.note_read(task, "梦幻广场", "0.412", now=now - 3)
            problem_report.note_read(task, "卡带选择页 OCR", "生活玩法", now=now - 2)
            problem_report.note_read(task, "梦幻广场", "0.538", now=now - 1)
            problem_report.note_read(task, "当前阶段", "选择广场卡带", now=now - 1)
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        reads = problem_report.reads_of(record)
        self.assertEqual(["卡带选择页 OCR", "梦幻广场"], [r["key"] for r in reads])
        self.assertEqual("0.538", reads[-1]["text"])
        line = problem_image.summary_text(record).splitlines()[-1]
        self.assertEqual("读到：卡带选择页 OCR=生活玩法；梦幻广场=0.538", line)

    def test_reads_of_another_task_or_long_before_are_left_out(self):
        task, other = Task("广场女神像"), Task("亲密度")
        with problem_report.run_scope(task) as scope:
            now = time.time()
            problem_report._current["started"] = now - 3 * problem_report.READ_WINDOW
            problem_report.note_read(other, "谈心面板", "Lv5", now=now - 1)
            problem_report.note_read(
                task, "梦幻广场", "0.1", now=now - problem_report.READ_WINDOW - 5
            )
            problem_report.note_read(task, "女神像许愿 OCR", "向女神像许愿", now=now - 1)
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        self.assertEqual(["女神像许愿 OCR"], [r["key"] for r in problem_report.reads_of(record)])

    def test_a_give_up_keeps_the_reads_of_its_own_moment(self):
        task = Task("快速狩猎")
        with problem_report.run_scope(task) as scope:
            now = time.time()
            problem_report._current["started"] = now - 3 * problem_report.READ_WINDOW
            problem_report.note_read(task, "圣石洞穴 OCR", "未读到", now=now - 2)
            problem_report.note_give_up(task, np.zeros((1080, 1920, 3), np.uint8), now=now - 1)
            # Going home afterwards writes other readings.
            problem_report.note_read(task, "主页确认", "通过", now=now)
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        self.assertEqual(["圣石洞穴 OCR"], [r["key"] for r in problem_report.reads_of(record)])

    def test_a_problem_keeps_more_lines_than_a_good_run(self):
        self.assertGreater(problem_report.PROBLEM_LOG_LINES, problem_report.LOG_LINES)

    def test_nothing_is_kept_outside_a_run(self):
        problem_report.note_read(Task("亲密度"), "谈心面板", "Lv5")
        self.assertEqual({}, problem_report._reads)

    def test_long_values_are_cut(self):
        task = Task("亲密度")
        with problem_report.run_scope(task):
            problem_report.note_read(task, "服装列表", "甲" * 500)
            [(_at, text)] = list(problem_report._reads.values())
        self.assertEqual(problem_report.READ_CHARS, len(text))


class FullLogTest(unittest.TestCase):
    """Every log line of the run beside its record (Leo 2026-11-05
    「LOG應該要有更好的方式可以看完整的」)."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        problem_report.set_root(self.folder.name)
        problem_report.install_log_ring()

    def tearDown(self):
        logging.getLogger("ok").removeHandler(problem_report._ring)
        problem_report._ring = None
        problem_report._drop()
        problem_report._last_written.clear()
        problem_report.set_root(None)
        self.folder.cleanup()

    def test_every_line_of_the_run_is_kept_past_the_ring(self):
        log = logging.getLogger("ok")
        count = problem_report.RING_SIZE + 50
        task = Task("一键完成日常")
        with problem_report.run_scope(task) as scope:
            for index in range(count):
                log.info(f"第 {index} 步")
            log.warning("C:" + r"\Users\小明\AppData 没读到")
            scope.result = False
        [record] = problem_report.records()
        text = open(record["log_path"], encoding="utf-8").read()
        lines = text.splitlines()
        self.assertEqual(count + 1, len(lines))
        self.assertIn("第 0 步", lines[0])
        self.assertIn("!", lines[-1][:9])  # a warning is marked
        self.assertNotIn("小明", text)

    def test_the_saved_file_starts_with_the_summary(self):
        log = logging.getLogger("ok")
        task = Task("广场女神像")
        with problem_report.run_scope(task) as scope:
            log.info("广场女神像：开始")
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        with tempfile.TemporaryDirectory() as desk:
            from pathlib import Path

            path = problem_image.save_full_log(record, Path(desk))
            text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("【YES-BD2"))
        self.assertIn("广场女神像：开始", text)
        self.assertTrue(path.name.startswith("YES-BD2-完整记录-"))

    def test_the_full_log_keeps_diagnostics_reads_and_steps(self):
        log = logging.getLogger("ok")
        task = Task("每周跑图")
        with problem_report.run_scope(task) as scope:
            log.info("诊断：地图采集：技能识别失败证据 slot=3")
            problem_report.note_stage(task, "每周跑图：选择第 12 章卡带")
            problem_report.note_read(task, "卡带选择页 OCR", "生活玩法")
            problem_report.note_read(task, "卡带选择页 OCR", "生活玩法")  # same: once
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        text = open(record["log_path"], encoding="utf-8").read()
        self.assertIn("技能识别失败证据", text)
        self.assertIn("步骤 每周跑图：选择第 12 章卡带", text)
        self.assertEqual(1, text.count("读到 卡带选择页 OCR：生活玩法"))


    def test_a_record_without_a_log_file_saves_nothing(self):
        self.assertIsNone(problem_image.save_full_log({"label": "x", "finished": time.time()}))


class StepTrailTest(unittest.TestCase):
    """The record keeps how the run got where it stopped, not only the last step."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        problem_report.set_root(self.folder.name)
        problem_report.install_log_ring()

    def tearDown(self):
        logging.getLogger("ok").removeHandler(problem_report._ring)
        problem_report._ring = None
        problem_report._drop()
        problem_report._last_written.clear()
        problem_report.set_root(None)
        self.folder.cleanup()

    def test_the_problem_keeps_the_last_steps_in_order(self):
        task = Task("每周跑图")
        with problem_report.run_scope(task) as scope:
            now = time.time()
            count = problem_report.STEP_LINES + 5
            for index in range(count):
                problem_report.note_stage(task, f"每周跑图：第 {index} 步", now=now - count + index)
            problem_report.note_stage(task, f"每周跑图：第 {count - 1} 步")  # repeat: once
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        steps = problem_report.steps_of(record)
        self.assertEqual(problem_report.STEP_LINES, len(steps))
        self.assertEqual(f"第 {count - 1} 步", steps[-1]["text"])  # run name dropped
        self.assertEqual("第 5 步", steps[0]["text"])

    def test_the_picture_and_saved_file_show_the_steps(self):
        task = Task("广场女神像")
        with problem_report.run_scope(task) as scope:
            problem_report.note_stage(task, "广场女神像：进入梦幻广场")
            problem_report.note_stage(task, "广场女神像：向女神像许愿")
            problem_report.note_problem(task, "fail")
            scope.result = False
        [record] = problem_report.records()
        with_steps = problem_image.render(record)
        without = dict(record, problem=dict(record["problem"], steps=[]))
        self.assertGreater(with_steps.height(), problem_image.render(without).height())
        text = problem_image.full_log_text(record)
        self.assertIn("停下前走过的步骤", text)
        self.assertIn("向女神像许愿", text)

    def test_a_good_run_has_no_steps_card(self):
        self.assertEqual([], problem_report.steps_of({"problem": None}))


if __name__ == "__main__":
    unittest.main()
