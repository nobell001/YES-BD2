import unittest
from unittest import mock

from src.utils import clone_desktop


def _process(pid, name):
    return pid, name


class InCloneTest(unittest.TestCase):
    """A Remote Desktop session is not the 桌面分身 (2026-10-09 review)."""

    def setUp(self):
        clone_desktop.in_clone.cache_clear()
        self.addCleanup(clone_desktop.in_clone.cache_clear)

    def _in_clone(self, own, console, processes, sessions):
        with (
            mock.patch.object(
                clone_desktop, "_session_of", side_effect=lambda pid: sessions.get(pid, own)
            ),
            mock.patch.object(clone_desktop, "_console_session", return_value=console),
            mock.patch("src.utils.process_snapshot.process_names", return_value=processes),
        ):
            return clone_desktop.in_clone()

    def test_console_session_is_not_the_clone(self):
        viewer = [_process(10, "CloneDesktop.exe")]
        self.assertFalse(self._in_clone(1, 1, viewer, {10: 1}))

    def test_remote_desktop_without_the_clone_window_is_not_the_clone(self):
        others = [_process(10, "steam.exe"), _process(11, "explorer.exe")]
        self.assertFalse(self._in_clone(2, 1, others, {10: 2, 11: 2}))

    def test_clone_window_in_another_session_means_the_clone(self):
        viewer = [_process(10, "CloneDesktop.exe")]
        self.assertTrue(self._in_clone(3, 1, viewer, {10: 1}))

    def test_clone_window_in_the_same_session_is_not_the_clone(self):
        # The clone window opened inside a Remote Desktop session: that
        # session is the clone's parent, not the clone.
        viewer = [_process(10, "clonedesktop.exe")]
        self.assertFalse(self._in_clone(2, 1, viewer, {10: 2}))

    def test_unreadable_clone_window_session_still_counts(self):
        viewer = [_process(10, "CloneDesktop.exe")]
        self.assertTrue(self._in_clone(3, 1, viewer, {10: None}))

    def test_answer_is_kept_for_the_process(self):
        viewer = [_process(10, "CloneDesktop.exe")]
        self.assertTrue(self._in_clone(3, 1, viewer, {10: 1}))
        self.assertTrue(self._in_clone(3, 1, [], {}))


class ViewerRemovedTest(unittest.TestCase):
    """An antivirus may delete the clone program the tool built (2026-10-09 review)."""

    def _removed(self, state, viewer):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            if state:
                (folder / "setup-state.json").write_text("{}", encoding="utf-8")
            if viewer:
                (folder / "CloneDesktop.exe").write_bytes(b"")
            with (
                mock.patch.object(clone_desktop, "SETUP_STATE", folder / "setup-state.json"),
                mock.patch.object(clone_desktop, "VIEWER", folder / "CloneDesktop.exe"),
            ):
                return clone_desktop.viewer_removed()

    def test_set_up_and_still_there(self):
        self.assertFalse(self._removed(state=True, viewer=True))

    def test_set_up_but_gone(self):
        self.assertTrue(self._removed(state=True, viewer=False))

    def test_never_set_up(self):
        self.assertFalse(self._removed(state=False, viewer=False))


if __name__ == "__main__":
    unittest.main()
