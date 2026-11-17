"""Opening the tool: the faster window build (Leo 2026-11-17
「啟動工具的速度可不可以再快一點」)."""

import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from src.compat import startup_speed


def _app():
    return QApplication.instance() or QApplication([])


class TouchGuardTest(unittest.TestCase):
    def setUp(self):
        _app()
        startup_speed.install_touch_guard_skip()
        self.addCleanup(setattr, startup_speed, "_building", True)

    def test_no_app_wide_guard_while_the_window_is_built(self):
        import ok.ui.qt.util.touch_scroll as touch_scroll

        startup_speed._building = True
        area = QScrollArea()
        touch_scroll.enable_touch_scrolling(area)
        self.assertIsNone(getattr(area, "_touch_scroll_click_guard", None))

    def test_guard_as_before_once_the_window_is_built(self):
        import ok.ui.qt.util.touch_scroll as touch_scroll

        startup_speed.finish_building()
        area = QScrollArea()
        touch_scroll.enable_touch_scrolling(area)
        guard = getattr(area, "_touch_scroll_click_guard", None)
        self.assertIsNotNone(guard)
        QApplication.instance().removeEventFilter(guard)

    def test_ok_modules_that_imported_the_name_get_it_too(self):
        import ok.ui.qt.MainWindow as main_window
        import ok.ui.qt.util.touch_scroll as touch_scroll
        import ok.ui.qt.widget.Tab as tab

        self.assertIs(main_window.enable_touch_scrolling, touch_scroll.enable_touch_scrolling)
        self.assertIs(tab.enable_touch_scrolling, touch_scroll.enable_touch_scrolling)


def _config(values):
    from ok.util.config import Config

    folder = tempfile.mkdtemp()
    return Config("card", dict(values), folder=os.path.abspath(folder))


class LazyConfigCardTest(unittest.TestCase):
    def setUp(self):
        _app()
        from ok import og

        self._saved_app = getattr(og, "app", None)
        og.app = SimpleNamespace(tr=lambda text: text)
        self.addCleanup(setattr, og, "app", self._saved_app)
        startup_speed.install_lazy_config_cards()

    def _card(self, config):
        from ok.ui.qt.tasks.ConfigCard import ConfigCard
        from qfluentwidgets import FluentIcon

        return ConfigCard(None, "任务", config, "说明", dict(config), {}, {}, FluentIcon.INFO)

    def test_settings_are_built_the_first_time_the_card_opens(self):
        config = _config({"次数": 3, "开关": True, "_hidden": 1})
        card = self._card(config)
        self.assertEqual(card.config_widgets, [])
        card.update_config()  # before opening: nothing to update, no error
        card.setExpand(True)
        self.assertEqual(card.config_keys, ["次数", "开关"])
        self.assertEqual(len(card.config_widgets), 2)
        card.setExpand(False)
        card.setExpand(True)  # built once
        self.assertEqual(len(card.config_widgets), 2)

    def test_opened_card_shows_the_current_values(self):
        config = _config({"次数": 3})
        card = self._card(config)
        config["次数"] = 7  # changed while the card was closed
        card.setExpand(True)
        widget = card.config_widget_by_key["次数"]
        self.assertEqual(widget.spin_box.value(), 7)

    def test_card_without_settings_keeps_oks_handling(self):
        from ok.ui.qt.tasks.ConfigCard import ConfigCard
        from qfluentwidgets import FluentIcon

        card = ConfigCard(None, "任务", _config({}), "说明", None, {}, None, FluentIcon.INFO)
        self.assertFalse(card._expand_enabled)
        self.assertIsNone(getattr(card, "_ok_bd2_pending_content", None))


if __name__ == "__main__":
    unittest.main()


class LaterPagesTest(unittest.TestCase):
    def setUp(self):
        from src.ui.shell.install import LaterPages

        self.added = []
        self.pages = LaterPages(self.added.append)
        self.pages["home"] = "首页"
        self.made = []

        def maker(name):
            def make():
                self.made.append(name)
                return name

            return make

        self.pages.later("report", maker("报表"))
        self.pages.later("settings", maker("设置"))

    def test_waiting_pages_are_not_made_before_asked(self):
        self.assertEqual(self.pages["home"], "首页")
        self.assertEqual(self.pages.get("home"), "首页")
        self.assertEqual(list(self.pages.values()), ["首页"])
        self.assertIn("settings", self.pages)
        self.assertEqual(self.made, [])

    def test_asking_for_one_makes_all_in_order(self):
        self.assertEqual(self.pages.get("settings"), "设置")
        self.assertEqual(self.made, ["报表", "设置"])
        self.assertEqual(self.added, ["报表", "设置"])
        self.assertEqual(list(self.pages), ["home", "report", "settings"])

    def test_build_waiting_makes_them_once(self):
        self.pages.build_waiting()
        self.pages.build_waiting()
        self.assertEqual(self.made, ["报表", "设置"])
        self.assertIsNone(self.pages.get("nothing"))

    def test_a_page_that_fails_does_not_stop_the_others(self):
        from src.ui.shell.install import LaterPages

        pages = LaterPages(lambda page: None)

        def broken():
            raise RuntimeError("boom")

        pages.later("bad", broken)
        pages.later("good", lambda: "ok")
        self.assertEqual(pages["good"], "ok")
        self.assertNotIn("bad", pages)
