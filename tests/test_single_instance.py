import unittest
from pathlib import Path
from unittest import mock

from src.compat import single_instance

ROOT = Path(__file__).resolve().parents[1]


class SingleInstanceTest(unittest.TestCase):
    """Opening the tool again never closes the open one (review 2026-10-09)."""

    def setUp(self):
        patcher = mock.patch.object(single_instance, "_handle", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def acquire(self, results):
        results = list(results)
        names, closed, slept = [], [], []

        def create(name):
            names.append(name)
            return results.pop(0) if len(results) > 1 else results[0]

        taken = single_instance.acquire(create=create, close=closed.append, sleep=slept.append)
        return taken, names, closed, slept

    def test_first_copy_takes_the_lock_and_keeps_it(self):
        taken, names, closed, _slept = self.acquire([(11, 0)])
        self.assertTrue(taken)
        self.assertEqual(([single_instance.mutex_name()], []), (names, closed))
        self.assertEqual(11, single_instance._handle)

    def test_second_copy_gives_up_and_closes_only_its_own_handle(self):
        taken, names, closed, slept = self.acquire([(22, single_instance.ERROR_ALREADY_EXISTS)])
        self.assertFalse(taken)
        self.assertEqual(single_instance.WAIT_TRIES, len(names))
        self.assertEqual([22] * single_instance.WAIT_TRIES, closed)
        # About 5 s, as ok-script waited before killing the open copy.
        self.assertTrue(4.5 <= sum(slept) <= 5.0, slept)
        self.assertIsNone(single_instance._handle)

    def test_a_copy_that_is_closing_gets_its_time(self):
        busy = (22, single_instance.ERROR_ALREADY_EXISTS)
        taken, _names, closed, _slept = self.acquire([busy, busy, (33, 0)])
        self.assertTrue(taken)
        self.assertEqual([22, 22], closed)
        self.assertEqual(33, single_instance._handle)

    def test_administrator_copy_open_counts_as_open(self):
        taken, _names, _closed, _slept = self.acquire([(None, single_instance.ERROR_ACCESS_DENIED)])
        self.assertFalse(taken)

    def test_other_failures_let_the_tool_start(self):
        taken, _names, _closed, _slept = self.acquire([(None, 87)])
        self.assertTrue(taken)

    def test_lock_is_per_folder_and_per_windows_session(self):
        first = single_instance.mutex_name("C:\\Games\\yes-bd2")
        self.assertTrue(first.startswith("Local\\"))
        self.assertNotEqual(first, single_instance.mutex_name("D:\\yes-bd2"))

    def test_open_copy_comes_to_the_front_or_the_player_is_told(self):
        cases = ((True, False, False), (False, False, True), (False, True, False))
        for front, clone, told in cases:
            with self.subTest(front=front, clone=clone):
                boxes = []
                single_instance.show_existing(
                    front=lambda front=front: front,
                    in_clone=lambda clone=clone: clone,
                    message_box=boxes.append,
                )
                self.assertEqual([single_instance.ALREADY_OPEN] if told else [], boxes)

    def test_ok_script_check_is_off_and_entry_points_check_first(self):
        from src.config import config

        self.assertIs(False, config["check_mutex"])
        for name in ("main.py", "main_debug.py"):
            with self.subTest(name=name):
                source = (ROOT / name).read_text(encoding="utf-8")
                self.assertLess(
                    source.index("single_instance.acquire()"), source.index("import ok\n")
                )


if __name__ == "__main__":
    unittest.main()
