import unittest
from pathlib import Path

from src.tasks import problem_report
from src.utils import test_run


class TestRunScratchTest(unittest.TestCase):
    """Live 4K 2026-10-10: the suite left made-up problem records in the
    checkout the tool runs from."""

    def test_records_of_a_test_run_stay_out_of_the_checkout(self):
        self.assertTrue(test_run.active())
        root = problem_report.root().resolve()
        self.assertFalse(root.is_relative_to(Path.cwd().resolve()))
        self.assertTrue(root.is_relative_to(test_run.scratch().resolve()))
