"""The spinner-to-check button (Leo 2026-11-24: 「這個給一些按鈕用 像是檢查更新」).

Pressed, it shrinks into a spinning circle; when the work is done it shows a
check in green and grows back; when the work failed it grows back without
the check.  Clicks while it works do nothing, so the work never runs twice.
"""

import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from src.ui.shell import progress_button, theme
from src.ui.shell.progress_button import BUSY, IDLE, OK, ProgressButton


def _wait(ms: int) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def _holder(button: ProgressButton) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(30, 30, 30, 30)
    row.addWidget(button)
    holder.resize(320, 120)
    holder.show()
    QApplication.processEvents()
    return holder


class ProgressButtonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, kind="primary", **kwargs):
        presses = []
        button = ProgressButton(
            "检查更新", kind, "refresh-cw", on_click=lambda: presses.append(1), **kwargs
        )
        holder = _holder(button)
        self.addCleanup(holder.deleteLater)
        return button, presses

    def test_check_after_work_then_label_again(self):
        button, _ = self.make()
        button.start()
        self.assertEqual(button.state, BUSY)
        self.assertTrue(button.working())
        button.finish(True)
        # Fast work still shows the circle and spinner first.
        self.assertEqual(button.state, BUSY)
        _wait(progress_button.MIN_BUSY_MS + 80)
        self.assertEqual(button.state, OK)
        self.assertTrue(button.working())
        _wait(progress_button.OK_HOLD_MS + 80)
        self.assertEqual(button.state, IDLE)
        self.assertFalse(button.working())
        _wait(progress_button.GROW_MS + 200)
        now = button._now()
        self.assertEqual(button.squeeze.at(now), 0.0)
        self.assertEqual(button.label_alpha.at(now), 1.0)
        self.assertEqual(button.check_alpha.at(now), 0.0)

    def test_failed_work_grows_back_without_check(self):
        button, _ = self.make()
        button.start()
        _wait(progress_button.MIN_BUSY_MS + 50)
        button.finish(False)
        self.assertEqual(button.state, IDLE)
        self.assertEqual(button.check_drawn.target, 0.0)
        self.assertEqual(button.done_colour.target, 0.0)
        self.assertEqual(button.label_alpha.target, 1.0)

    def test_clicks_while_working_do_nothing(self):
        button, presses = self.make(auto_start=True)
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(presses, [1])
        self.assertEqual(button.state, BUSY)
        QTest.mouseClick(button, Qt.LeftButton)
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(presses, [1])

    def test_turned_off_animations_jump_to_the_end(self):
        with mock.patch.object(progress_button, "reduced_motion", return_value=True):
            button, _ = self.make()
        button.start()
        now = button._now()
        self.assertEqual(button.squeeze.at(now), 1.0)
        self.assertEqual(button.label_alpha.at(now), 0.0)
        button.finish(True)
        _wait(progress_button.MIN_BUSY_REDUCED_MS + progress_button.CHECK_DRAW_DELAY_MS + 80)
        self.assertEqual(button.state, OK)
        self.assertEqual(button.check_drawn.at(button._now()), 1.0)
        _wait(progress_button.OK_HOLD_REDUCED_MS + progress_button.LABEL_BACK_DELAY_MS + 80)
        self.assertEqual(button.state, IDLE)
        self.assertEqual(button.squeeze.at(button._now()), 0.0)
        self.assertEqual(button.label_alpha.at(button._now()), 1.0)

    def test_keeps_its_place_in_the_layout(self):
        button, _ = self.make()
        width = button.width()
        button.start()
        _wait(progress_button.SHRINK_MS + 50)
        self.assertEqual(button.width(), width)

    def test_every_state_paints_in_both_themes(self):
        errors = []

        def hook(kind, value, _tb):
            errors.append(f"{kind.__name__}: {value}")

        with mock.patch.object(sys, "excepthook", hook):
            for dark in (False, True):
                with mock.patch.object(theme, "isDarkTheme", return_value=dark):
                    for kind in ("primary", "secondary"):
                        button, _ = self.make(kind)
                        holder = button.parentWidget()
                        self.assertFalse(holder.grab().isNull())
                        button.start()
                        _wait(300)
                        self.assertFalse(holder.grab().isNull())
                        button.finish(True)
                        _wait(progress_button.MIN_BUSY_MS + 200)
                        self.assertFalse(holder.grab().isNull())
        self.assertEqual(errors, [])

    def test_check_reads_on_both_greens(self):
        button, _ = self.make()
        for dark in (False, True):
            with mock.patch.object(theme, "isDarkTheme", return_value=dark):
                ok, ink = theme.color("ok"), button._done_ink()
                self.assertGreater(abs(ok.lightnessF() - ink.lightnessF()), 0.4, dark)


class _UpdateCard(QWidget):
    update_available_changed = Signal(bool)
    check_started = Signal()

    def __init__(self):
        super().__init__()
        self._busy = False
        self.checks = 0

    def tr(self, text):
        return text

    def check_for_updates(self):
        self.checks += 1
        self._set_busy(True)
        self.check_started.emit()
        self._set_status("Checking for updates…")

    def _set_busy(self, busy, *args, **kwargs):
        self._busy = busy

    def _set_status(self, message, error=False):
        pass

    def _set_version_controls_visible(self, visible):
        pass

    def _selection_changed(self, *_args):
        pass


class AboutPageCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def page(self):
        from src.ui.shell.about_page import AboutPage

        card = _UpdateCard()
        page = AboutPage(SimpleNamespace(about_tab=SimpleNamespace(update_card=card)), None)
        self.addCleanup(page.deleteLater)
        return page, card

    def test_check_spins_then_shows_check(self):
        page, card = self.page()
        page.check_for_updates()
        self.assertEqual(page.check_button.state, BUSY)
        self.assertTrue(page.check_button.isEnabled())
        page.check_for_updates()  # a second press while checking does nothing
        self.assertEqual(card.checks, 1)
        card._set_busy(False)
        card._set_status("No updates available.")
        _wait(progress_button.MIN_BUSY_MS + 80)
        self.assertEqual(page.check_button.state, OK)

    def test_new_version_found_also_shows_check(self):
        page, card = self.page()
        page.check_for_updates()
        card._set_busy(False)
        card._set_status("")
        _wait(progress_button.MIN_BUSY_MS + 80)
        self.assertEqual(page.check_button.state, OK)

    def test_failed_check_grows_back_without_check(self):
        page, card = self.page()
        page.check_for_updates()
        _wait(progress_button.MIN_BUSY_MS + 50)
        card._set_busy(False)
        card._set_status("Failed to check for updates: offline", error=True)
        self.assertEqual(page.check_button.state, IDLE)
        self.assertEqual(page.check_button.check_drawn.target, 0.0)
        # Later words (update notes) never touch the button again.
        card._set_status("Failed to calculate update notes", error=True)
        self.assertEqual(page.check_button.state, IDLE)


class RunNotifyTestButtonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_test_message_spins_then_check_or_back(self):
        from src.ui.shell import run_notify_dialog

        dialog = run_notify_dialog.RunNotifyDialog("")
        self.addCleanup(dialog.deleteLater)
        with (
            mock.patch.object(run_notify_dialog.run_notify, "valid", return_value=True),
            mock.patch("threading.Thread"),
        ):
            dialog._test()
            self.assertEqual(dialog.test_button.state, BUSY)
            dialog._show_test("")
            _wait(progress_button.MIN_BUSY_MS + 80)
            self.assertEqual(dialog.test_button.state, OK)
            dialog.test_button.reset()
            dialog._test()
            _wait(progress_button.MIN_BUSY_MS + 50)
            dialog._show_test("发送失败")
            self.assertEqual(dialog.test_button.state, IDLE)


class ProblemButtonsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def card(self):
        from src.ui.shell import problem_page

        card = problem_page.ReportActions(120)
        self.addCleanup(card.deleteLater)
        return card

    def test_failed_save_grows_back_without_check(self):
        card = self.card()
        button = card.save_image
        with mock.patch.object(card, "_with_code", side_effect=lambda act: act("") or True):
            card._press(button, lambda why: False)
        _wait(progress_button.MIN_BUSY_MS + 80)
        self.assertEqual(button.state, IDLE)
        self.assertEqual(button.check_drawn.target, 0.0)

    def test_done_action_shows_check(self):
        card = self.card()
        button = card.copy_text
        with mock.patch.object(card, "_with_code", side_effect=lambda act: act("") or True):
            card._press(button, lambda why: None)
        _wait(progress_button.MIN_BUSY_MS + 80)
        self.assertEqual(button.state, OK)

    def test_no_record_never_leaves_a_spinner(self):
        card = self.card()
        card._copy_text()  # no record shown: nothing to copy
        self.assertEqual(card.copy_text.state, IDLE)
        self.assertFalse(card.copy_text.working())

    def test_upload_for_another_record_releases_the_button(self):
        card = self.card()
        card._record = {"path": "b"}
        card.copy_image.start()
        card._uploading = True
        card._upload_done("a", "", "")
        _wait(progress_button.MIN_BUSY_MS + 50)
        self.assertEqual(card.copy_image.state, IDLE)


if __name__ == "__main__":
    unittest.main()
