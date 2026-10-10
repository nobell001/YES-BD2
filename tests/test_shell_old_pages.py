"""ok's old pages never show in the new window (Leo 2026-10-10).

Leo's v0.1.18 suddenly showed ok's start page: its window, capture and
interaction lists and the developer tools row, with 设置 lit in the sidebar
(「我剛剛跳出這個畫面 這畫面應該要移除掉」).  ok switches to it when the game
window is minimized during a run or the game did not start.  The shell only
lit 设置 for such a page and left it showing.
"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ui.shell import install
from src.ui.shell.install import Shell


class _StartTab:
    pass


def make_shell(current):
    window = SimpleNamespace(
        stackedWidget=SimpleNamespace(currentWidget=lambda: current),
        about_tab=object(),
        start_tab=current,
        shown=[],
    )
    window.switchTo = window.shown.append
    pages = {"home": object(), "settings": object(), "about": object()}
    shell = SimpleNamespace(
        window=window,
        pages=pages,
        sidebar=mock.Mock(),
        cover=mock.Mock(),
        history=mock.Mock(),
    )
    shell.navigate = lambda key: Shell.navigate(shell, key)
    return shell, window, pages


class OldPageTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(install.QTimer, "singleShot", lambda _ms, call: call())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_old_start_page_goes_to_home(self):
        shell, window, pages = make_shell(_StartTab())
        Shell._on_page_changed(shell, 0)
        self.assertEqual([pages["home"]], window.shown)
        shell.sidebar.select.assert_not_called()

    def test_the_old_about_page_still_goes_to_the_new_one(self):
        shell, window, pages = make_shell(None)
        window.stackedWidget.currentWidget = lambda: window.about_tab
        Shell._on_page_changed(shell, 0)
        self.assertEqual([pages["about"]], window.shown)

    def test_a_new_page_only_lights_its_sidebar_item(self):
        shell, window, pages = make_shell(None)
        window.stackedWidget.currentWidget = lambda: pages["settings"]
        Shell._on_page_changed(shell, 0)
        self.assertEqual([], window.shown)
        shell.sidebar.select.assert_called_once_with("settings")


if __name__ == "__main__":
    unittest.main()
