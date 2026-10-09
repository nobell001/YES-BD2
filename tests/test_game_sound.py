import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.utils import game_sound


class FakeVolume:
    def __init__(self, muted=False):
        self.muted = muted
        self.calls = []

    def GetMute(self):
        return 1 if self.muted else 0

    def SetMute(self, mute, _context):
        self.calls.append(mute)
        self.muted = bool(mute)


class FakeMixer:
    def __init__(self):
        self.games = {}
        self.reads = 0

    def volumes(self, pid):
        self.reads += 1
        return list(self.games.get(pid, []))


class GameSoundTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / "game_sound.json"
        self.mixer = FakeMixer()
        for patch in (
            mock.patch.object(game_sound, "SETTINGS_FILE", self.file),
            mock.patch.object(game_sound, "mixer", self.mixer),
            mock.patch.object(game_sound, "_session_key", lambda: "1"),
            mock.patch.dict(game_sound._held, {"pid": 0, "was_muted": False}),
            mock.patch.dict(game_sound._retry, {"pid": 0, "at": 0.0}),
            mock.patch.dict(game_sound._owed, {"unmute": False, "at": 0.0}),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def saved(self):
        return json.loads(self.file.read_text(encoding="utf-8"))

    def test_off_by_default_and_saved(self):
        self.assertFalse(game_sound.enabled())
        game_sound.set_enabled(True)
        self.assertTrue(game_sound.enabled())
        self.assertTrue(self.saved()[game_sound.MUTE_KEY])

    def test_setting_off_never_mutes(self):
        volume = FakeVolume()
        self.mixer.games[100] = [volume]
        game_sound.follow(True, 100, now=0)
        self.assertEqual(volume.calls, [])
        self.assertEqual(self.mixer.reads, 0)

    def test_mutes_while_running_and_gives_the_sound_back(self):
        game_sound.set_enabled(True)
        volume = FakeVolume()
        self.mixer.games[100] = [volume]
        game_sound.follow(True, 100, now=0)
        self.assertTrue(volume.muted)
        self.assertTrue(game_sound.holding())
        marks = self.saved()[game_sound.MUTED_KEY]
        self.assertEqual(marks, {"1": {"pid": 100, "was_muted": False}})
        game_sound.follow(True, 100, now=1)
        self.assertEqual(volume.calls, [1])  # not set again every second
        game_sound.follow(False, 100, now=2)
        self.assertFalse(volume.muted)
        self.assertFalse(game_sound.holding())
        self.assertEqual(self.saved()[game_sound.MUTED_KEY], {})

    def test_a_game_muted_before_the_run_stays_muted(self):
        game_sound.set_enabled(True)
        volume = FakeVolume(muted=True)
        self.mixer.games[100] = [volume]
        game_sound.follow(True, 100, now=0)
        game_sound.follow(False, 100, now=1)
        self.assertTrue(volume.muted)

    def test_turning_the_setting_off_mid_run_gives_the_sound_back(self):
        game_sound.set_enabled(True)
        volume = FakeVolume()
        self.mixer.games[100] = [volume]
        game_sound.follow(True, 100, now=0)
        game_sound.set_enabled(False)
        game_sound.follow(True, 100, now=1)
        self.assertFalse(volume.muted)

    def test_a_reopened_game_is_muted_too(self):
        game_sound.set_enabled(True)
        old, new = FakeVolume(), FakeVolume()
        self.mixer.games[100] = [old]
        game_sound.follow(True, 100, now=0)
        del self.mixer.games[100]  # the game closed
        self.mixer.games[200] = [new]
        game_sound.follow(True, 200, now=1)
        self.assertTrue(new.muted)
        self.assertEqual(game_sound._held["pid"], 200)

    def test_a_game_closed_mid_run_gets_its_sound_back_when_reopened(self):
        # Live 2026-10-10: Windows kept the mute for the next start; the run
        # after the restart read "was muted" and never gave the sound back.
        game_sound.set_enabled(True)
        old, new = FakeVolume(), FakeVolume(muted=True)
        self.mixer.games[100] = [old]
        game_sound.follow(True, 100, now=0)
        del self.mixer.games[100]  # 闪退
        game_sound.follow(False, 0, now=1)
        self.mixer.games[200] = [new]
        game_sound.follow(True, 200, now=2)
        self.assertTrue(new.muted)
        game_sound.follow(False, 200, now=3)
        self.assertFalse(new.muted)
        self.assertEqual(self.saved()[game_sound.MUTED_KEY], {})

    def test_a_game_reopened_after_the_run_gets_its_sound_back(self):
        game_sound.set_enabled(True)
        old, new = FakeVolume(), FakeVolume(muted=True)
        self.mixer.games[100] = [old]
        game_sound.follow(True, 100, now=0)
        del self.mixer.games[100]
        game_sound.follow(False, 0, now=1)
        self.assertIn("1", self.saved()[game_sound.MUTED_KEY])  # kept until then
        game_sound.follow(False, 200, now=2)  # opened, no sound yet
        self.mixer.games[200] = [new]
        game_sound.follow(False, 200, now=2.5)
        self.assertTrue(new.muted)  # waits RETRY_SECONDS
        game_sound.follow(False, 200, now=2 + game_sound.RETRY_SECONDS + 0.1)
        self.assertFalse(new.muted)
        self.assertEqual(self.saved()[game_sound.MUTED_KEY], {})
        new.muted = True  # the player mutes it afterwards: left alone
        game_sound.follow(False, 200, now=20)
        self.assertTrue(new.muted)

    def test_left_over_mute_of_a_closed_game_is_undone_when_it_opens(self):
        self.file.write_text(
            json.dumps({game_sound.MUTED_KEY: {"1": {"pid": 100, "was_muted": False}}}),
            encoding="utf-8",
        )
        game_sound.restore_left_over()
        self.assertIn("1", self.saved()[game_sound.MUTED_KEY])
        volume = FakeVolume(muted=True)
        self.mixer.games[300] = [volume]
        game_sound.follow(False, 300, now=0)
        self.assertFalse(volume.muted)

    def test_a_game_without_sound_yet_is_tried_again_later(self):
        game_sound.set_enabled(True)
        game_sound.follow(True, 100, now=0)
        self.assertFalse(game_sound.holding())
        game_sound.follow(True, 100, now=1)
        self.assertEqual(self.mixer.reads, 1)  # waits RETRY_SECONDS
        volume = FakeVolume()
        self.mixer.games[100] = [volume]
        game_sound.follow(True, 100, now=game_sound.RETRY_SECONDS + 0.1)
        self.assertTrue(volume.muted)

    def test_every_sound_of_the_game_is_muted(self):
        game_sound.set_enabled(True)
        volumes = [FakeVolume(), FakeVolume()]
        self.mixer.games[100] = volumes
        game_sound.follow(True, 100, now=0)
        self.assertTrue(all(volume.muted for volume in volumes))

    def test_no_game_window_does_nothing(self):
        game_sound.set_enabled(True)
        game_sound.follow(True, 0, now=0)
        self.assertEqual(self.mixer.reads, 0)

    def test_mixer_errors_do_not_break_the_run(self):
        game_sound.set_enabled(True)

        def broken(_pid):
            raise OSError("no audio device")

        with mock.patch.object(self.mixer, "volumes", broken):
            game_sound.follow(True, 100, now=0)
        self.assertFalse(game_sound.holding())

    def test_left_over_mute_is_undone_at_start(self):
        volume = FakeVolume(muted=True)
        self.mixer.games[100] = [volume]
        self.file.write_text(
            json.dumps({game_sound.MUTED_KEY: {"1": {"pid": 100, "was_muted": False}, "2": {}}}),
            encoding="utf-8",
        )
        game_sound.restore_left_over()
        self.assertFalse(volume.muted)
        # The mark of the other Windows session (桌面分身) is left alone.
        self.assertEqual(self.saved()[game_sound.MUTED_KEY], {"2": {}})

    def test_left_over_mark_of_a_muted_game_keeps_it_muted(self):
        volume = FakeVolume(muted=True)
        self.mixer.games[100] = [volume]
        self.file.write_text(
            json.dumps({game_sound.MUTED_KEY: {"1": {"pid": 100, "was_muted": True}}}),
            encoding="utf-8",
        )
        game_sound.restore_left_over()
        self.assertTrue(volume.muted)
        self.assertEqual(volume.calls, [])


class SoundWatchTest(unittest.TestCase):
    """The shell's once-a-second check passes the run state and the game's process."""

    def test_tick_follows_the_running_task(self):
        from types import SimpleNamespace

        from src.ui.shell import data, sound_watch

        batch = object()
        window = SimpleNamespace(hwnd=55, to_handle_mute=True)
        og = SimpleNamespace(device_manager=SimpleNamespace(hwnd_window=window))
        seen = []

        def follow(running, pid):
            seen.append((running, pid))

        with (
            mock.patch.object(data, "current_task", lambda: batch),
            mock.patch.object(data, "onetime_tasks", lambda: [batch]),
            mock.patch.object(data, "og", lambda: og),
            mock.patch.object(game_sound, "pid_of", lambda hwnd: hwnd * 10),
            mock.patch.object(game_sound, "follow", follow),
            mock.patch.object(game_sound, "holding", lambda: True),
        ):
            sound_watch.tick()
        self.assertEqual(seen, [(True, 550)])
        self.assertFalse(window.to_handle_mute)

    def test_a_run_waiting_for_the_login_keeps_the_game_muted(self):
        from types import SimpleNamespace

        from src.ui.shell import data, sound_watch

        batch = SimpleNamespace(_start_after_login=True)
        login = object()
        seen = []
        with (
            mock.patch.object(data, "current_task", lambda: login),
            mock.patch.object(data, "onetime_tasks", lambda: [batch]),
            mock.patch.object(data, "og", lambda: SimpleNamespace()),
            mock.patch.object(game_sound, "follow", lambda running, pid: seen.append(running)),
        ):
            sound_watch.tick()
        self.assertEqual(seen, [True])

    def test_tick_without_a_run_or_game(self):
        from types import SimpleNamespace

        from src.ui.shell import data, sound_watch

        seen = []

        def follow(running, pid):
            seen.append((running, pid))

        with (
            mock.patch.object(data, "current_task", lambda: None),
            mock.patch.object(data, "onetime_tasks", lambda: []),
            mock.patch.object(data, "og", lambda: SimpleNamespace()),
            mock.patch.object(game_sound, "follow", follow),
        ):
            sound_watch.tick()
        self.assertEqual(seen, [(False, 0)])


if __name__ == "__main__":
    unittest.main()
