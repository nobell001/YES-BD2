"""Every floating window over the tool, opened and used the way a player does:
nothing squashed or cut, also after something inside changes.

The 定时启动 window was squashed in v0.2.7 (Leo 2026-10-22) because its height
was taken once.  The same check then found 跑完发到微信's title and subtitle
squashed, and a deleted account's row still drawn below 账号's list.  Each
window here opens with only events processed: nothing placed by hand.
"""

import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from src.utils import accounts
from tests.test_schedule_dialog_fit import LANGUAGES, _translator
from tests.ui_fit_audit import problems

SHELL = Path(__file__).resolve().parents[1] / "src" / "ui" / "shell"


class FloatingFitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from src.ui.quest_theme import apply_app_font

        apply_app_font()

    def setUp(self):
        from ok import og

        from src.ui.shell import theme

        self.theme = theme
        patch = mock.patch.object(og, "app", SimpleNamespace(tr=lambda text: text), create=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(theme.set_theme_mode, theme.theme_mode())
        old = os.getcwd()
        folder = tempfile.TemporaryDirectory()
        os.chdir(folder.name)
        accounts.reset_cache()
        self.addCleanup(folder.cleanup)
        self.addCleanup(accounts.reset_cache)
        self.addCleanup(os.chdir, old)

    def settle(self):
        for _ in range(30):
            self.app.processEvents()

    def _open(self, make, size=(1100, 760)):
        host = QWidget()
        host.resize(*size)
        host.setStyleSheet(self.theme.style_sheet())
        host.show()
        self.addCleanup(host.close)
        dialog = make(host)
        dialog.resize(*size)
        dialog.show()
        self.addCleanup(dialog.close)
        self.settle()
        dialog._open.go(1.0, animate=False)
        self.settle()
        return dialog

    def _each_look(self):
        from ok import og

        for language in LANGUAGES:
            for mode in ("light", "dark"):
                with self.subTest(language=language, mode=mode):
                    og.app.tr = _translator(language)
                    self.theme.set_theme_mode(mode)
                    yield

    def test_run_notify_with_each_message(self):
        from src.ui.shell.run_notify_dialog import SENDING, RunNotifyDialog

        for _ in self._each_look():
            dialog = self._open(lambda host: RunNotifyDialog("", host))
            self.assertEqual([], problems(dialog.panel))
            for step in (
                lambda: dialog.edit.setText("abc"),
                lambda: dialog.edit.setText("SCT1234567890abcdef"),
                lambda: dialog._say(SENDING),
                lambda: dialog._show_test("发不出去：连不上 Server酱，看看网络，或者过几分钟再试"),
            ):
                step()
                self.settle()
                self.assertEqual([], problems(dialog.panel))
            dialog.close()

    def test_skill_interval(self):
        from src.ui.shell.skill_interval_dialog import SkillIntervalDialog

        for _ in self._each_look():
            dialog = self._open(lambda host: SkillIntervalDialog(1.0, (0.5, 2.0), 1.0, host))
            dialog.slider.setValue(dialog.slider.maximum())
            self.settle()
            self.assertEqual([], problems(dialog.panel))
            dialog.close()

    def test_map_week_restart(self):
        from src.ui.shell.map_week_reset import WeekResetDialog

        for _ in self._each_look():
            dialog = self._open(WeekResetDialog)
            self.assertEqual([], problems(dialog.panel))
            dialog.close()

    def test_accounts_list_with_five_then_one_deleted(self):
        from src.ui.shell.accounts_ui import ManageDialog, _ManageRow

        while len(accounts.accounts()) < accounts.MAX_ACCOUNTS:
            accounts.add("很长很长的账号名字二十个字")
        for _ in self._each_look():
            dialog = self._open(ManageDialog)
            self.assertEqual([], problems(dialog.panel))
            dialog.say("看不懂这张图片，换一张 PNG 或 JPG 试试")
            self.settle()
            self.assertEqual([], problems(dialog.panel))
            dialog.say("")
            self.settle()
            self.assertEqual([], problems(dialog.panel))
            dialog.close()
        dialog = self._open(ManageDialog)
        last = dialog.rows.itemAt(dialog.rows.count() - 1).widget()
        last._delete()  # asks
        self.settle()
        self.assertEqual([], problems(dialog.panel))
        last._delete()  # deletes
        # The old rows are gone from the list at once, not only after the
        # event loop gets round to deleting them.
        self.assertEqual(accounts.MAX_ACCOUNTS - 1, len(dialog.rows_box.findChildren(_ManageRow)))
        self.settle()
        self.assertEqual([], problems(dialog.panel))

    def test_account_mismatch(self):
        from src.ui.shell.accounts_ui import MismatchDialog

        for _ in self._each_look():
            dialog = self._open(MismatchDialog)
            self.assertEqual([], problems(dialog.panel))
            dialog.close()

    def test_every_floating_panel_measures_itself_again(self):
        """A dialog with its own Panel and its own one-time sizing is how
        定时启动 and 跑完发到微信 got squashed: they all go through Floating."""
        for path in SHELL.glob("*.py"):
            if path.name == "floating.py":
                continue
            text = path.read_text(encoding="utf-8")
            for found in re.finditer(r"class (\w+)\(QDialog\)", text):
                body = text[found.end():]
                self.assertNotIn("Panel(self)", body.split("\nclass ")[0], f"{path.name} {found[1]}")


if __name__ == "__main__":
    unittest.main()
