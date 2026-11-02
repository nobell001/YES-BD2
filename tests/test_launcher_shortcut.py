import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.compat.launcher_shortcut import (
    is_launcher_shortcut_name,
    long_path,
    needs_retarget,
    remove_extra_launcher_shortcuts,
    retarget,
    same_path,
    shortcut_paths,
)


class FakeShortcut:
    def __init__(self, target, icon="C:\\app\\icon.ico,0"):
        self.TargetPath = target
        self.Arguments = '"C:\\app\\data\\apps\\yes-bd2\\.pyappify-shortcut.py"'
        self.WorkingDirectory = "C:\\app\\data\\apps\\yes-bd2\\working"
        self.IconLocation = icon
        self.saved = False

    def Save(self):
        self.saved = True


class FakeShell:
    def __init__(self, shortcut):
        self.shortcut = shortcut

    def CreateShortcut(self, _path):
        return self.shortcut


class LauncherShortcutTest(unittest.TestCase):
    def test_paths_are_start_menu_and_desktop_with_the_app_name(self):
        paths = shortcut_paths("yes-bd2", Path("S"), Path("D"))
        self.assertEqual([Path("S/yes-bd2.lnk"), Path("D/yes-bd2.lnk")], paths)

    def test_python_shortcut_is_pointed_at_the_launcher_keeping_its_icon(self):
        with tempfile.TemporaryDirectory() as folder:
            link = Path(folder) / "yes-bd2.lnk"
            link.write_bytes(b"")
            launcher = Path(folder) / "yes-bd2.exe"
            shortcut = FakeShortcut(str(Path(folder) / "python" / "pythonw.exe"))
            self.assertTrue(retarget(link, launcher, FakeShell(shortcut)))
            self.assertTrue(shortcut.saved)
            self.assertEqual(str(launcher), shortcut.TargetPath)
            self.assertEqual("", shortcut.Arguments)
            self.assertEqual(str(launcher.parent), shortcut.WorkingDirectory)
            self.assertEqual("C:\\app\\icon.ico,0", shortcut.IconLocation)

    def test_shortcut_already_on_the_launcher_is_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            link = Path(folder) / "yes-bd2.lnk"
            link.write_bytes(b"")
            launcher = Path(folder) / "yes-bd2.exe"
            shortcut = FakeShortcut(str(launcher))
            self.assertFalse(retarget(link, launcher, FakeShell(shortcut)))
            self.assertFalse(shortcut.saved)

    def test_missing_shortcut_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = FakeShortcut("python")
            self.assertFalse(
                retarget(Path(folder) / "yes-bd2.lnk", Path(folder) / "x.exe", FakeShell(shortcut))
            )
            self.assertFalse(shortcut.saved)

    def test_needs_retarget(self):
        self.assertFalse(needs_retarget("", Path("C:/a/yes-bd2.exe")))
        self.assertTrue(needs_retarget("C:/a/python/pythonw.exe", Path("C:/a/yes-bd2.exe")))


class TargetShell:
    """Each .lnk path has its own target, like the real WScript.Shell."""

    def __init__(self, targets):
        self.targets = targets

    def CreateShortcut(self, path):
        return FakeShortcut(self.targets.get(Path(path).name, ""))


class DesktopDuplicateTest(unittest.TestCase):
    """玩家 11-02：启动器每次开都在桌面再写一个「yes-bd2 启动器」，看到三个捷径。"""

    def make(self, folder, names):
        desktop = Path(folder)
        for name in names:
            (desktop / name).write_bytes(b"")
        return desktop

    def test_launcher_duplicates_in_every_language_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / "app" / "yes-bd2.exe"
            names = [
                "yes-bd2.lnk",
                "yes-bd2 启动器.lnk",
                "yes-bd2 啟動器.lnk",
                "yes-bd2 Launcher.lnk",
                "yes-bd2 启动器 (2).lnk",
            ]
            desktop = self.make(folder, names)
            shell = TargetShell({name: str(launcher) for name in names})
            removed = remove_extra_launcher_shortcuts(desktop, launcher, "yes-bd2", shell)
            self.assertEqual(4, len(removed))
            self.assertEqual(["yes-bd2.lnk"], sorted(p.name for p in desktop.iterdir()))

    def test_kept_when_the_main_shortcut_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / "yes-bd2.exe"
            desktop = self.make(folder, ["yes-bd2 启动器.lnk"])
            shell = TargetShell({"yes-bd2 启动器.lnk": str(launcher)})
            self.assertEqual(
                [], remove_extra_launcher_shortcuts(desktop, launcher, "yes-bd2", shell)
            )
            self.assertTrue((desktop / "yes-bd2 启动器.lnk").exists())

    def test_kept_while_the_main_shortcut_still_skips_the_launcher(self):
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / "yes-bd2.exe"
            desktop = self.make(folder, ["yes-bd2.lnk", "yes-bd2 启动器.lnk"])
            shell = TargetShell(
                {"yes-bd2.lnk": "C:/x/python/pythonw.exe", "yes-bd2 启动器.lnk": str(launcher)}
            )
            self.assertEqual(
                [], remove_extra_launcher_shortcuts(desktop, launcher, "yes-bd2", shell)
            )

    def test_other_shortcuts_and_other_installs_are_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / "yes-bd2.exe"
            names = [
                "yes-bd2.lnk",
                "yes-bd2 启动器.lnk",
                "BrownDust II.lnk",
                "我的 yes-bd2 启动器.lnk",
            ]
            desktop = self.make(folder, names)
            shell = TargetShell(
                {
                    "yes-bd2.lnk": str(launcher),
                    "yes-bd2 启动器.lnk": "D:/other/yes-bd2.exe",
                    "BrownDust II.lnk": str(launcher),
                    "我的 yes-bd2 启动器.lnk": str(launcher),
                }
            )
            self.assertEqual(
                [], remove_extra_launcher_shortcuts(desktop, launcher, "yes-bd2", shell)
            )
            self.assertEqual(4, len(list(desktop.iterdir())))

    def test_launcher_names(self):
        self.assertTrue(is_launcher_shortcut_name("yes-bd2 启动器.lnk", "yes-bd2"))
        self.assertTrue(is_launcher_shortcut_name("Lanzador de yes-bd2.lnk", "yes-bd2"))
        self.assertTrue(is_launcher_shortcut_name("YES-BD2 Launcher (3).LNK", "yes-bd2"))
        self.assertFalse(is_launcher_shortcut_name("yes-bd2.lnk", "yes-bd2"))
        self.assertFalse(is_launcher_shortcut_name("yes-bd2 启动器.url", "yes-bd2"))


class ShortNameTest(unittest.TestCase):
    """A shortcut keeps the long name; the launcher can come as an 8.3 one
    (YES-BD2 Build v0.2.28: the RUNNER~1 temp folder)."""

    def test_short_and_long_names_of_one_launcher_are_the_same(self):
        folder = tempfile.gettempdir()
        short = str(Path(folder) / "RUNNER~1" / "yes-bd2.exe")
        long_ = str(Path(folder) / "runneradmin" / "yes-bd2.exe")
        with mock.patch(
            "src.compat.launcher_shortcut.long_path",
            side_effect=lambda path: path.replace("RUNNER~1", "runneradmin"),
        ):
            self.assertTrue(same_path(long_, Path(short)))
            self.assertTrue(same_path(short, Path(long_)))
            self.assertFalse(same_path(str(Path(folder) / "other" / "yes-bd2.exe"), Path(short)))

    def test_long_path_leaves_names_alone_off_windows(self):
        if sys.platform == "win32":
            self.skipTest("Windows expands the name")
        self.assertEqual("C:/Users/RUNNER~1/x.exe", long_path("C:/Users/RUNNER~1/x.exe"))


@unittest.skipUnless(sys.platform == "win32", "real .lnk files need Windows")
class RealShortcutFileTest(unittest.TestCase):
    """Real .lnk files: WScript.Shell reads a name outside the system code
    page (启 on a 繁中 Windows) as an empty shortcut (Leo 4K 11-02)."""

    def test_simplified_and_traditional_duplicates_are_both_removed(self):
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        with tempfile.TemporaryDirectory() as folder:
            desktop = Path(folder)
            launcher = Path(folder) / "yes-bd2.exe"
            launcher.write_bytes(b"")
            names = ["yes-bd2.lnk", "yes-bd2 启动器.lnk", "yes-bd2 啟動器 (2).lnk", "yes-bd2 Launcher.lnk"]
            for name in names:
                saved = desktop / "ascii.lnk"
                shortcut = shell.CreateShortcut(str(saved))  # ASCII name: WScript can save it
                shortcut.TargetPath = str(launcher)
                shortcut.Save()
                saved.rename(desktop / name)
            removed = remove_extra_launcher_shortcuts(desktop, launcher, "yes-bd2", shell)
            self.assertEqual(sorted(names[1:]), sorted(p.name for p in removed))
            self.assertTrue((desktop / "yes-bd2.lnk").is_file())


if __name__ == "__main__":
    unittest.main()
