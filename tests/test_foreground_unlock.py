"""Player v0.3.2 2026-11-08 (定时启动, nobody at the PC): Windows refused to
put the game in front for two minutes, so H and every other key never went.
The front is asked for ever more strongly; what held it, or why nothing
did, goes to the log."""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks import BaseBD2Task as base

GAME, OTHER = 100, 200


class _Win:
    """Records the calls; the front moves to the game from ``wins_at`` on."""

    def __init__(self, wins_at):
        self.front = OTHER
        self.calls = []
        self.wins_at = wins_at
        self.gui = SimpleNamespace(
            IsIconic=lambda h: False,
            ShowWindow=lambda *a: self.calls.append("restore"),
            GetForegroundWindow=lambda: self.front,
            BringWindowToTop=lambda h: None,
            SetForegroundWindow=self._set,
            GetClassName=lambda h: "Notepad",
        )
        self.api = SimpleNamespace(
            GetCurrentThreadId=lambda: 1,
            MapVirtualKey=lambda code, kind: 56,
            keybd_event=lambda code, scan, flags, extra: self.calls.append(("key", code, flags)),
        )
        self.process = SimpleNamespace(GetWindowThreadProcessId=lambda h: (2, 3))
        self.user32 = SimpleNamespace(
            AttachThreadInput=lambda *a: True,
            SwitchToThisWindow=self._switch,
            OpenInputDesktop=lambda *a: 5,
            CloseDesktop=lambda *a: None,
        )

    def _set(self, h):
        held = any(c[0] == "key" and c[2] == 0 for c in self.calls if isinstance(c, tuple))
        self.calls.append(("set", "alt" if held else "plain"))
        if self.wins_at == "attach" or (self.wins_at == "alt" and held):
            self.front = h

    def _switch(self, h, _alt):
        self.calls.append("switch")
        if self.wins_at == "switch":
            self.front = h

    def patches(self):
        import win32con

        return (
            mock.patch.dict(
                "sys.modules",
                {"win32gui": self.gui, "win32api": self.api, "win32process": self.process},
            ),
            mock.patch("ctypes.windll", SimpleNamespace(user32=self.user32)),
            mock.patch.object(base, "FOREGROUND_SHOW_SECONDS", 0.0),
            mock.patch.object(win32con, "KEYEVENTF_KEYUP", 2, create=True),
            mock.patch.object(win32con, "VK_MENU", 18, create=True),
        )

    def run(self):
        a, b, c, d, e = self.patches()
        with a, b, c, d, e:
            return base._set_foreground_attached(GAME)


class StrongerWaysTest(unittest.TestCase):
    def test_plain_attach_is_enough_no_alt(self):
        win = _Win("attach")
        self.assertEqual("attach", win.run())
        self.assertFalse([c for c in win.calls if isinstance(c, tuple) and c[0] == "key"])

    def test_alt_is_held_while_asking_then_let_go(self):
        win = _Win("alt")
        self.assertEqual("alt", win.run())
        keys = [c for c in win.calls if isinstance(c, tuple) and c[0] == "key"]
        self.assertEqual([("key", 18, 0), ("key", 18, 2)], keys)
        self.assertIn(("set", "alt"), win.calls)
        self.assertNotIn("switch", win.calls)

    def test_switch_is_the_last_way(self):
        win = _Win("switch")
        self.assertEqual("switch", win.run())

    def test_nothing_holds(self):
        win = _Win("never")
        self.assertEqual("", win.run())
        # Alt let go even though the game never came to the front.
        keys = [c for c in win.calls if isinstance(c, tuple) and c[0] == "key"]
        self.assertEqual(2, len(keys))


class CaptionClickTest(unittest.TestCase):
    def _win(self, client_top, under):
        win = _Win("never")
        win.gui.GetWindowRect = lambda h: (0, 0, 1000, 600)
        win.gui.ClientToScreen = lambda h, p: (8, client_top)
        win.gui.WindowFromPoint = lambda p: under
        win.user32.GetAncestor = lambda h, kind: GAME if h == GAME else OTHER
        win.api.GetCursorPos = lambda: (5, 5)
        win.api.SetCursorPos = lambda p: win.calls.append(("cursor", p))

        def mouse(flags, *_a):
            win.calls.append(("mouse", flags))
            win.front = GAME

        win.api.mouse_event = mouse
        return win

    def _mouse(self, win):
        return [c for c in win.calls if isinstance(c, tuple) and c[0] == "mouse"]

    def test_windowed_game_title_bar_is_pressed_last(self):
        win = self._win(client_top=31, under=GAME)
        self.assertEqual("caption", win.run())
        self.assertEqual(2, len(self._mouse(win)))
        cursor = [c[1] for c in win.calls if isinstance(c, tuple) and c[0] == "cursor"]
        self.assertEqual((400, 15), cursor[0])
        self.assertEqual((5, 5), cursor[-1])  # put back

    def test_window_over_the_title_bar_is_never_pressed(self):
        win = self._win(client_top=31, under=OTHER)
        self.assertEqual("", win.run())
        self.assertEqual([], self._mouse(win))

    def test_borderless_game_has_no_title_bar_to_press(self):
        win = self._win(client_top=0, under=GAME)
        self.assertEqual("", win.run())
        self.assertEqual([], self._mouse(win))


class CloneFullscreenKeyTest(unittest.TestCase):
    """Same class of bug: the clone's Alt+Enter went out without looking
    whether the game had come to the front."""

    def test_alt_enter_not_sent_to_another_window(self):
        import win32con

        from src.ui.shell import clone_flow

        keys = []
        gui = SimpleNamespace(
            GetWindowLong=lambda h, i: 0xFFFFFFFF,
            GetClientRect=lambda h: (0, 0, 1920, 1080),
            GetForegroundWindow=lambda: OTHER,
        )
        with (
            mock.patch.dict("sys.modules", {"win32gui": gui}),
            mock.patch.object(clone_flow, "_game_window", lambda: GAME),
            mock.patch.dict(clone_flow._fullscreen_tries, {}, clear=True),
            mock.patch.object(base, "_set_foreground_attached", lambda h: ""),
            mock.patch.object(clone_flow.time, "sleep", lambda s: None),
            mock.patch("ctypes.windll", SimpleNamespace(user32=SimpleNamespace(keybd_event=lambda *a: keys.append(a)))),
            mock.patch.object(win32con, "WS_CAPTION", 1, create=True),
        ):
            clone_flow._make_game_fullscreen()
        self.assertEqual([], keys)


class WhyInFrontTest(unittest.TestCase):
    def test_locked_pc_is_named(self):
        win = _Win("never")
        a, b, c, d, e = win.patches()
        with a, b, c, d, e, mock.patch("src.utils.scheduled_start.screen_locked", lambda: True):
            self.assertIn("锁屏", base._what_is_in_front())

    def test_other_program_named_by_kind_not_title(self):
        win = _Win("never")
        a, b, c, d, e = win.patches()
        with a, b, c, d, e:
            why = base._what_is_in_front()
        self.assertIn("Notepad", why)


class KeyLostFrontTest(unittest.TestCase):
    def test_press_that_lost_the_front_is_pressed_again(self):
        keys, logs = [], []
        fronts = iter([False, True])
        task = SimpleNamespace(
            _wait_unlocked=lambda: True,
            _bring_game_to_foreground=lambda: True,
            _game_in_foreground=lambda: next(fronts),
            operate=lambda action, block=True, restore_cursor=True: action(),
            log_info=lambda text, **_k: logs.append(text),
        )
        api = SimpleNamespace(
            MapVirtualKey=lambda code, kind: 35,
            keybd_event=lambda code, scan, flags, extra: keys.append(flags),
        )
        with mock.patch.dict("sys.modules", {"win32api": api}):
            self.assertTrue(base.BaseBD2Task._send_game_key(task, 72, 0.0))
        self.assertEqual(4, len(keys))  # two presses, each let go
        self.assertEqual(1, len(logs))


class LockedPcTest(unittest.TestCase):
    def _task(self, warnings, sleeps):
        return SimpleNamespace(
            info_set=lambda *a: None,
            log_info=lambda *a, **k: None,
            log_warning=lambda text, **k: warnings.append((text, k.get("notify"))),
            sleep=lambda seconds: sleeps.append(seconds),
        )

    def test_waits_for_unlock_then_goes_on(self):
        warnings, sleeps = [], []
        opens = iter([False, False, False, True])
        with mock.patch.object(base, "_input_desktop_open", lambda: next(opens)):
            self.assertTrue(base.BaseBD2Task._wait_unlocked(self._task(warnings, sleeps)))
        self.assertEqual(1, len(warnings))
        self.assertTrue(warnings[0][1])  # the player is told

    def test_stuck_screen_watch_rests_while_waiting(self):
        warnings, sleeps = [], []
        task = self._task(warnings, sleeps)
        seen = []
        task._frozen_watch = SimpleNamespace(paused=0, pressed=lambda: seen.append("pressed"))
        opens = iter([False, False, True])

        def look():
            seen.append(task._frozen_watch.paused)
            return next(opens)

        with mock.patch.object(base, "_input_desktop_open", look):
            self.assertTrue(base.BaseBD2Task._wait_unlocked(task))
        self.assertEqual([0, 1, 1], seen[:3])  # paused during the wait
        self.assertEqual(0, task._frozen_watch.paused)
        self.assertIn("pressed", seen)
        self.assertIn("锁屏", warnings[0][0])

    def test_gives_up_after_the_limit(self):
        warnings, sleeps = [], []
        clock = iter(range(0, 10**6, 600))
        with (
            mock.patch.object(base, "_input_desktop_open", lambda: False),
            mock.patch.object(base.time, "monotonic", lambda: next(clock)),
        ):
            self.assertFalse(base.BaseBD2Task._wait_unlocked(self._task(warnings, sleeps)))

    def test_unlocked_pc_does_not_wait(self):
        warnings, sleeps = [], []
        with mock.patch.object(base, "_input_desktop_open", lambda: True):
            self.assertTrue(base.BaseBD2Task._wait_unlocked(self._task(warnings, sleeps)))
        self.assertEqual([], sleeps)


class KeyNotSentLogTest(unittest.TestCase):
    def test_reason_logged_once_per_cause(self):
        logs = []
        task = SimpleNamespace(
            _wait_unlocked=lambda: True,
            _bring_game_to_foreground=lambda: (setattr(task, "_foreground_why", "电脑锁屏了") or False),
            operate=lambda action, block=True, restore_cursor=True: action(),
            log_info=lambda text, **_k: logs.append(text),
        )
        for _ in range(3):
            self.assertFalse(base.BaseBD2Task._send_game_key(task, 72, 0.0))
        self.assertEqual(1, len([t for t in logs if "锁屏" in t]))


if __name__ == "__main__":
    unittest.main()
