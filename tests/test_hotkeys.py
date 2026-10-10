import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ui.shell import hotkeys


class FakeRecordTask:
    def __init__(self, key=None):
        self.config = {} if key is None else {"录制按键": key}


class HotkeysTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.file = Path(self.folder.name) / "configs" / "hotkeys.json"
        patcher = patch.object(hotkeys, "KEYS_FILE", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)

    def test_defaults(self):
        self.assertEqual(
            {"pause": "F9", "stop": "F10", "record": "F8"}, hotkeys.keys(FakeRecordTask())
        )

    def test_choices_are_f6_to_f12(self):
        self.assertEqual(("F6", "F7", "F8", "F9", "F10", "F11", "F12"), hotkeys.KEY_CHOICES)

    def test_record_key_comes_from_the_fiend_task(self):
        self.assertEqual("F7", hotkeys.keys(FakeRecordTask("F7"))["record"])

    def test_picking_a_used_key_swaps(self):
        task = FakeRecordTask("F8")
        current = hotkeys.set_key("pause", "F10", task)
        self.assertEqual({"pause": "F10", "stop": "F9", "record": "F8"}, current)
        self.assertEqual(current, hotkeys.keys(task))

    def test_record_key_swaps_with_pause_and_is_saved_on_the_task(self):
        task = FakeRecordTask("F8")
        current = hotkeys.set_key("record", "F9", task)
        self.assertEqual({"pause": "F8", "stop": "F10", "record": "F9"}, current)
        self.assertEqual("F9", task.config["录制按键"])

    def test_old_record_key_f9_never_shares_with_pause(self):
        # Before 10-09 the record key could already be F9 or F10.
        current = hotkeys.keys(FakeRecordTask("F9"))
        self.assertEqual("F9", current["record"])
        self.assertEqual(3, len(set(current.values())))

    def test_broken_file_falls_back(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text("{oops", encoding="utf-8")
        self.assertEqual("F9", hotkeys.keys(FakeRecordTask())["pause"])

    def test_unknown_key_is_ignored(self):
        task = FakeRecordTask()
        self.assertEqual(hotkeys.keys(task), hotkeys.set_key("pause", "F1", task))


class FakeUser32:
    """RegisterHotKey fails for keys in ``taken``; ``down`` is the keyboard."""

    def __init__(self, taken=()):
        self.taken = set(taken)
        self.down = set()
        self.tapped = set()  # pressed and let go since the last read
        self.registered = {}
        self.timers = 0

    def RegisterHotKey(self, _hwnd, hotkey_id, _mods, code):
        if code in self.taken:
            return 0
        self.registered[hotkey_id] = code
        return 1

    def UnregisterHotKey(self, _hwnd, hotkey_id):
        self.registered.pop(hotkey_id, None)
        return 1

    def GetAsyncKeyState(self, code):
        state = (-32768 if code in self.down else 0) | (1 if code in self.tapped else 0)
        self.tapped.discard(code)
        return state

    def SetTimer(self, *_args):
        self.timers += 1
        return 7

    def KillTimer(self, *_args):
        self.timers -= 1
        return 1


class TakenKeyTest(unittest.TestCase):
    """Leo 2026-10-10: F9/F10 did nothing mid-run; the log said another
    program held them, so the tool never heard them."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patcher = patch.object(hotkeys, "KEYS_FILE", Path(self.folder.name) / "hotkeys.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(hotkeys, "_record_task", lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pressed = []
        self.listener = hotkeys.HotkeyListener(self.pressed.append)
        self.f9, self.f10 = hotkeys.key_code("F9"), hotkeys.key_code("F10")

    def test_a_taken_key_is_read_directly(self):
        user32 = FakeUser32(taken={self.f9, self.f10})
        self.listener._bind(user32)
        self.assertEqual({"pause": self.f9, "stop": self.f10}, self.listener.watch.keys)
        self.assertEqual(1, user32.timers)
        user32.down.add(self.f10)
        self.listener._poll(user32)
        self.listener._poll(user32)  # held: still one press
        user32.down.clear()
        self.listener._poll(user32)
        user32.down.add(self.f9)
        self.listener._poll(user32)
        self.assertEqual(["stop", "pause"], self.pressed)

    def test_free_keys_need_no_reading(self):
        user32 = FakeUser32()
        self.listener._bind(user32)
        self.assertEqual({}, self.listener.watch.keys)
        self.assertEqual(0, user32.timers)

    def test_registered_again_once_the_other_program_lets_go(self):
        user32 = FakeUser32(taken={self.f10})
        self.listener._bind(user32)
        self.assertEqual({"stop": self.f10}, self.listener.watch.keys)
        user32.taken.clear()
        with patch.object(hotkeys.time, "monotonic", return_value=1e6):
            self.listener._poll(user32)
        self.assertEqual({}, self.listener.watch.keys)
        self.assertIn(self.f10, user32.registered.values())
        self.assertEqual(0, user32.timers)

    def test_a_tap_between_two_reads_still_counts(self):
        # 4K PC 10-10: 60 ms taps were missed 6 of 10 times at a 100 ms poll.
        self.assertLessEqual(hotkeys.POLL_MS, 30)
        user32 = FakeUser32(taken={self.f10})
        self.listener._bind(user32)
        user32.tapped.add(self.f10)  # down and up again before the next read
        self.listener._poll(user32)
        self.listener._poll(user32)
        self.assertEqual(["stop"], self.pressed)

    def test_a_key_held_when_watching_starts_is_not_a_press(self):
        watch = hotkeys.KeyWatch()
        watch.watch("stop", 1, is_down=True)
        self.assertEqual([], watch.tick(lambda _code: (True, False), 0)[0])
        self.assertEqual([], watch.tick(lambda _code: (False, False), 10)[0])
        self.assertEqual(["stop"], watch.tick(lambda _code: (True, True), 20)[0])

    def test_holding_a_key_with_auto_repeat_is_one_press(self):
        watch = hotkeys.KeyWatch()
        watch.watch("pause", 1)
        presses = [watch.tick(lambda _code: (True, True), t)[0] for t in range(0, 100, 25)]
        self.assertEqual([["pause"], [], [], []], presses)


if __name__ == "__main__":
    unittest.main()
