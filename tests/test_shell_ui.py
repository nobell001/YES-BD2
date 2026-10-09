import os
import re
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QElapsedTimer, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from src.tasks.map_trade.collector import chapter_filter
from src.ui.shell import actions, config_form, data, theme, widgets
from src.ui.shell.map_page import range_text
from src.ui.shell.motion import PageCover
from src.ui.shell.page import Page

STORY = list(range(1, 20))
CHARACTER = [1, 2, 3, 4, 5, 6, 7]


class RangeTextTest(unittest.TestCase):
    def test_everything_selected_is_all(self):
        self.assertEqual(range_text(STORY, CHARACTER, STORY, CHARACTER), "全部")

    def test_neighbouring_cards_become_ranges(self):
        self.assertEqual(range_text([1, 2, 3, 9], [], STORY, CHARACTER), "1-3,9")
        self.assertEqual(range_text([], [1, 2, 5], STORY, CHARACTER), "R1-R2,R5")

    def test_text_reads_back_as_the_same_cards(self):
        for story, character in (([8, 9, 10, 13], [2]), ([19], CHARACTER), (STORY, [7])):
            text = range_text(story, character, STORY, CHARACTER)
            self.assertEqual(chapter_filter(text), set(story) | {f"R{n}" for n in character})


class ConfigFormHintTest(unittest.TestCase):
    """Leo 2026-10-04: an ⓘ whose hover shows nothing is confusing."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_info_mark_only_where_a_hint_exists(self):
        task = SimpleNamespace(
            config={"有说明": True, "没说明": 3, "空说明": False},
            default_config={"有说明": True, "没说明": 3, "空说明": False},
            config_type={},
            config_description={"有说明": "看这里", "空说明": "  "},
        )
        form = config_form.ConfigForm(task)
        self.assertEqual(len(form.findChildren(widgets.IconLabel)), 1)
        label, _control, _sync = form._rows["有说明"]
        self.assertEqual(label.toolTip(), "看这里")
        self.assertIsNotNone(getattr(label, "_hint_filter", None))
        for key in ("没说明", "空说明"):
            self.assertEqual(form._rows[key][0].toolTip(), "")

    def test_listed_tasks_keep_only_the_chosen_hints(self):
        class JunkGearTask:
            config = {"分解R和SR": True, "分解3星4星角色的UR专用": True}
            default_config = dict(config)
            config_type = {}
            config_description = {"分解R和SR": "说明一", "分解3星4星角色的UR专用": "说明二"}

        form = config_form.ConfigForm(JunkGearTask())
        self.assertEqual(form._rows["分解R和SR"][0].toolTip(), "")
        self.assertEqual(form._rows["分解3星4星角色的UR专用"][0].toolTip(), "说明二")
        self.assertIn("分解R和SR", JunkGearTask.config)

    def test_long_hints_are_broken_into_lines(self):
        text = "字" * 60
        lines = widgets.wrap_hint(text).split("\n")
        self.assertEqual("".join(lines), text)
        self.assertTrue(all(len(line) <= widgets.HINT_LINE_CHARS for line in lines))
        english = " ".join(["word"] * 40)
        self.assertTrue(
            all(
                len(line) <= widgets.HINT_LINE_WIDTH
                for line in widgets.wrap_hint(english).split("\n")
            )
        )


class ConfigFormRulesTest(unittest.TestCase):
    def test_sub_settings_follow_their_switch(self):
        task = SimpleNamespace(
            config={"制作料理": True, "料理清单": []},
            config_type={"制作料理": {"sub_configs": {True: ["料理清单"]}}},
        )
        rules = config_form.parents(task)
        self.assertEqual(rules, {"料理清单": ("制作料理", True)})
        self.assertTrue(config_form.condition_met(task, "料理清单", rules))
        task.config["制作料理"] = False
        self.assertFalse(config_form.condition_met(task, "料理清单", rules))

    def test_string_rule_matches_a_bool_switch(self):
        task = SimpleNamespace(
            config={"卖": False},
            config_type={"卖": {"sub_configs": {"true": "出售保险"}}},
        )
        rules = config_form.parents(task)
        self.assertFalse(config_form.condition_met(task, "出售保险", rules))
        task.config["卖"] = True
        self.assertTrue(config_form.condition_met(task, "出售保险", rules))


class TimeTextTest(unittest.TestCase):
    def test_clock_is_the_players_own_time(self):
        # Leo 2026-10-05: times follow the player's PC clock, not UTC+8.
        moment = datetime(2026, 10, 3, 0, 30, tzinfo=timezone.utc).timestamp()
        self.assertEqual(data.clock_text(moment), datetime.fromtimestamp(moment).strftime("%H:%M"))
        self.assertEqual(data.clock_text(None), "")


class StartHookTest(unittest.TestCase):
    def test_resuming_a_paused_task_runs_the_hook(self):
        calls = []
        actions.on_started(lambda: calls.append("started"))
        self.addCleanup(actions._started.clear)
        task = SimpleNamespace(enabled=True, paused=True, unpaused=False)
        task.unpause = lambda: setattr(task, "unpaused", True)
        self.assertTrue(actions.start(task))
        self.assertTrue(task.unpaused)
        self.assertEqual(calls, ["started"])


class GameToFrontTest(unittest.TestCase):
    """Leo 2026-10-06: pressing start shows the game, not the tool."""

    def test_start_brings_the_game_to_front(self):
        task = SimpleNamespace(enabled=True, paused=True)
        task.unpause = lambda: None
        with mock.patch.object(actions, "bring_game_to_front") as front:
            self.assertTrue(actions.start(task))
        front.assert_called_once_with()

    def test_minimised_game_is_restored_first(self):
        import win32con
        import win32gui

        from src.ui.shell import clone_flow

        with (
            mock.patch.object(clone_flow, "_game_window", return_value=42),
            mock.patch.object(win32gui, "IsIconic", return_value=True),
            mock.patch.object(win32gui, "ShowWindow") as show,
            mock.patch("src.tasks.BaseBD2Task._set_foreground_attached") as front,
        ):
            self.assertTrue(actions.bring_game_to_front())
        show.assert_called_once_with(42, win32con.SW_RESTORE)
        front.assert_called_once_with(42)

    def test_no_game_window_does_nothing(self):
        from src.ui.shell import clone_flow

        with (
            mock.patch.object(clone_flow, "_game_window", return_value=None),
            mock.patch("src.tasks.BaseBD2Task._set_foreground_attached") as front,
        ):
            self.assertFalse(actions.bring_game_to_front())
        front.assert_not_called()

    def test_a_failure_never_blocks_the_start(self):
        from src.ui.shell import clone_flow

        with mock.patch.object(clone_flow, "_game_window", side_effect=OSError("denied")):
            self.assertFalse(actions.bring_game_to_front())


class CloneJobLoginTest(unittest.TestCase):
    """Live 4K 2026-10-09: a single task handed to the 桌面分身 with the game
    closed waited ten minutes for a login nothing could start, then ran on
    the title screen."""

    def _run(self, game_running: bool):
        from src.ui.shell import clone_flow
        from src.utils import clone_desktop

        task = SimpleNamespace(name="跑图路线测试")
        clone_flow._waiting_job.clear()
        with (
            mock.patch.object(clone_flow.data, "busy", return_value=False),
            mock.patch.object(clone_flow.data, "task_by_name", return_value=task),
            mock.patch.object(clone_desktop, "JOB_FILE", mock.Mock(exists=lambda: True)),
            mock.patch.object(clone_desktop, "take_job", return_value={"task": task.name}),
            mock.patch.object(clone_flow, "_reload_settings"),
            mock.patch.object(clone_flow, "log_in_this_run"),
            mock.patch.object(clone_flow, "_login_pending", return_value=True),
            mock.patch.object(actions, "game_running", return_value=game_running),
            mock.patch.object(clone_flow, "_open_game_only") as opened,
            mock.patch.object(actions, "start") as started,
        ):
            clone_flow._run_pending_job()
        waiting = bool(clone_flow._waiting_job)
        clone_flow._waiting_job.clear()
        return opened.call_count, started.call_count, waiting

    def test_closed_game_is_opened_before_waiting_for_the_login(self):
        self.assertEqual((1, 0, True), self._run(game_running=False))

    def test_an_open_game_just_waits_for_the_login(self):
        self.assertEqual((0, 0, True), self._run(game_running=True))


class CloneStartTest(unittest.TestCase):
    """Leo 2026-10-07: 继续 was refused after he stopped the run in the 桌面分身."""

    def setUp(self):
        from src.ui.shell import clone_flow
        from src.utils import clone_desktop

        self.app = QApplication.instance() or QApplication([])
        self.clone_flow = clone_flow
        self.status = None
        self.open = True
        self.tool = False
        self.answer = True
        self.ended = []
        self.controller = mock.Mock()
        app = SimpleNamespace(start_controller=self.controller)
        box = mock.Mock()
        box.return_value.exec.side_effect = lambda: self.answer
        self.box = box
        patches = [
            mock.patch.object(clone_desktop, "in_clone", return_value=False),
            mock.patch.object(
                clone_desktop, "read_status", side_effect=lambda max_age: self.status
            ),
            mock.patch.object(clone_desktop, "job_waiting", return_value=False),
            mock.patch.object(clone_desktop, "clone_open", side_effect=lambda: self.open),
            mock.patch.object(
                clone_desktop, "tool_running_in_clone", side_effect=lambda: self.tool
            ),
            mock.patch.object(clone_desktop, "request_job"),
            mock.patch.object(clone_desktop, "open_viewer", return_value=True),
            mock.patch.object(clone_desktop, "viewer_running", return_value=True),
            mock.patch.object(clone_desktop, "ready", return_value=True),
            mock.patch.object(
                clone_desktop, "end_clone", side_effect=lambda: self.ended.append(1) or True
            ),
            mock.patch.object(clone_flow, "_launch", None),
            mock.patch.object(clone_flow, "message"),
            mock.patch("qfluentwidgets.MessageBox", box),
            mock.patch.object(data, "busy", return_value=False),
            mock.patch.object(data, "og", return_value=SimpleNamespace(app=app)),
            mock.patch.object(actions, "game_running", return_value=True),
            mock.patch.object(actions, "bring_game_to_front"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.task = SimpleNamespace(enabled=False, paused=False, name="一键完成日常")

    def _start(self):
        return actions.start(self.task, window=object())

    def test_a_stopped_clone_run_does_not_block(self):
        self.status = {"at": 0, "running": False}
        self.assertFalse(self.clone_flow.busy_in_clone())

    def test_a_running_clone_still_blocks(self):
        import time

        self.status = {"at": time.time(), "running": True, "task": "一键完成日常"}
        self.assertTrue(self.clone_flow.busy_in_clone())
        self.assertFalse(self._start())
        self.controller.start.assert_not_called()
        self.box.assert_not_called()
        self.assertEqual(self.ended, [])

    def test_a_handed_over_task_blocks(self):
        from src.utils import clone_desktop

        with mock.patch.object(clone_desktop, "job_waiting", return_value=True):
            self.assertTrue(self.clone_flow.busy_in_clone())

    def test_an_idle_clone_is_closed_after_asking(self):
        self.assertTrue(self._start())
        self.box.assert_called_once()
        self.assertEqual(self.ended, [1])
        self.controller.start.assert_called_once_with(self.task)

    def test_saying_no_keeps_the_clone(self):
        self.answer = False
        self.assertFalse(self._start())
        self.assertEqual(self.ended, [])
        self.controller.start.assert_not_called()

    def test_continue_goes_to_the_free_tool_in_the_clone(self):
        # Leo 2026-10-07: 继续 after a clone run stopped goes on there, no question.
        from src.utils import clone_desktop

        self.tool = True
        self.assertTrue(actions.start(self.task, window=object(), run_mode="incomplete"))
        clone_desktop.request_job.assert_called_once_with("一键完成日常", "incomplete")
        self.box.assert_not_called()
        self.assertEqual(self.ended, [])
        self.controller.start.assert_not_called()

    def test_clone_button_with_the_clone_open_does_not_reopen_it(self):
        from src.utils import clone_desktop

        self.tool = True
        self.assertTrue(self.clone_flow.open_clone(object(), self.task, "all"))
        clone_desktop.request_job.assert_called_once_with("一键完成日常", "all")
        clone_desktop.open_viewer.assert_not_called()

    def test_clone_button_without_the_tool_in_it_opens_the_viewer(self):
        from src.utils import clone_desktop

        self.assertTrue(self.clone_flow.open_clone(object(), self.task, "all"))
        clone_desktop.open_viewer.assert_called_once_with()
        self.clone_flow._launch.timer.stop()

    def _idle_clone_of_version(self, version):
        import time

        self.tool = True
        self.status = {"at": time.time(), "running": False, "version": version}
        patch = mock.patch.object(self.clone_flow, "own_version", return_value="v2")
        patch.start()
        self.addCleanup(patch.stop)

    def test_an_older_tool_in_the_clone_is_reopened_before_a_start(self):
        # 2026-10-09 review: the tool here updated itself, the one in the clone did not.
        from src.utils import clone_desktop

        self._idle_clone_of_version("v1")
        self.assertTrue(actions.start(self.task, window=object(), run_mode="incomplete"))
        self.assertEqual(self.ended, [1])
        clone_desktop.request_job.assert_called_once_with("一键完成日常", "incomplete")
        clone_desktop.open_viewer.assert_called_once_with()
        self.box.assert_not_called()
        self.controller.start.assert_not_called()
        self.clone_flow._launch.timer.stop()

    def test_the_same_version_in_the_clone_takes_the_task(self):
        from src.utils import clone_desktop

        self._idle_clone_of_version("v2")
        self.assertTrue(actions.start(self.task, window=object(), run_mode="incomplete"))
        self.assertEqual(self.ended, [])
        clone_desktop.open_viewer.assert_not_called()

    def test_a_running_older_clone_is_left_alone(self):
        import time

        self._idle_clone_of_version("v1")
        self.status = {"at": time.time(), "running": True, "task": "x", "version": "v1"}
        self.assertFalse(self._start())
        self.assertEqual(self.ended, [])

    def test_without_a_clone_the_start_is_as_before(self):
        self.open = False
        self.assertTrue(self._start())
        self.box.assert_not_called()
        self.controller.start.assert_called_once_with(self.task)


class CloneFrontTest(unittest.TestCase):
    """In the clone, whatever pops up over the game during a run is put back."""

    def _check(self, front, front_pid=2, name="steam.exe", login=False):
        from src.ui.shell import clone_flow

        clone_flow._front_check.update(at=0.0, seen=None)
        process = mock.Mock()
        process.name.return_value = name
        with (
            mock.patch.object(clone_flow, "_game_window", return_value=10),
            mock.patch.object(clone_flow, "_login_pending", return_value=login),
            mock.patch("win32gui.GetForegroundWindow", return_value=front),
            mock.patch("win32gui.GetAncestor", side_effect=lambda h, _flag: h),
            mock.patch("win32gui.GetWindowText", return_value="x"),
            mock.patch(
                "win32process.GetWindowThreadProcessId",
                side_effect=lambda h: (0, 1 if h == 10 else front_pid),
            ),
            mock.patch("psutil.Process", return_value=process),
            mock.patch("src.tasks.BaseBD2Task._set_foreground_attached") as bring,
        ):
            clone_flow._keep_game_in_front()
        return bring

    def test_a_window_over_the_game_is_put_back(self):
        self._check(20).assert_called_once_with(10)

    def test_the_game_in_front_is_left_alone(self):
        self._check(10).assert_not_called()

    def test_the_games_own_dialog_and_launcher_are_left_alone(self):
        self._check(20, front_pid=1).assert_not_called()
        self._check(20, name="BrownDust2Starter.exe").assert_not_called()

    def test_not_while_signing_in(self):
        self._check(20, login=True).assert_not_called()


class ThemeTest(unittest.TestCase):
    def test_both_looks_name_the_same_colours(self):
        self.assertEqual(set(theme.LIGHT), set(theme.DARK))

    def test_light_is_lavender_and_dark_is_its_night_twin(self):
        with mock.patch.object(theme, "isDarkTheme", return_value=False):
            self.assertIs(theme.tokens(), theme.LIGHT)
        with mock.patch.object(theme, "isDarkTheme", return_value=True):
            self.assertIs(theme.tokens(), theme.DARK)
            self.assertEqual(theme.DARK["primary"], "#7467C4")
        # one set of shapes for both
        self.assertEqual(theme.radius(), 20)
        self.assertAlmostEqual(theme.corner(5), 13.0)

    def test_theme_switch_has_no_old_light_option(self):
        from src.ui.shell import settings

        self.assertEqual(list(settings.THEME_LABELS), ["light", "dark", "auto"])
        self.assertEqual(settings.THEME_LABELS["light"], "淡紫")

    def test_every_colour_parses(self):
        for palette in (theme.LIGHT, theme.DARK):
            for name, value in palette.items():
                self.assertTrue(QColor(value).isValid(), f"{name}: {value}")

    def test_every_task_kind_has_colours(self):
        kinds = {kind for _short, _icon, kind in data.CHILD_META.values()}
        kinds |= {kind for _icon, kind in data.TASK_ICONS.values()}
        self.assertLessEqual(kinds, set(theme.KINDS))
        for kind in theme.KINDS:
            self.assertIn(f"kind_{kind}", theme.LIGHT)
            self.assertIn(f"kind_{kind}_bg", theme.LIGHT)

    def test_style_sheet_builds_in_both_themes(self):
        for palette in (theme.LIGHT, theme.DARK):
            with mock.patch.object(theme, "tokens", return_value=palette):
                sheet = theme.style_sheet()
            # Style sheets get plain #RRGGBB; colours with alpha are for painting only.
            self.assertIsNone(re.search(r"#[0-9A-Fa-f]{8}\b", sheet))


class _BrokenPage(Page):
    def refresh(self):
        raise ValueError("boom")


class PageRefreshGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_failing_refresh_stays_inside_the_page(self):
        # An exception escaping showEvent crashes this PySide build outright.
        page = _BrokenPage("shellTestBroken", "测试")
        page.show()
        self.app.processEvents()
        self.assertTrue(page._failed)
        page.close()
        page.deleteLater()


class PageCoverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait(self, done, limit_ms=2000):
        timer = QElapsedTimer()
        timer.start()
        while not done() and timer.elapsed() < limit_ms:
            self.app.processEvents()

    def test_entrance_plays_then_gets_out_of_the_way(self):
        stack = QStackedWidget()
        stack.resize(400, 300)
        page = QWidget()
        stack.addWidget(page)
        stack.show()
        self.app.processEvents()
        cover = PageCover(stack)
        cover.play(page)
        self.assertTrue(cover.isVisible())
        self._wait(lambda: not cover._shot.isNull())
        self.assertEqual(cover.geometry(), page.geometry())
        self._wait(lambda: not cover.isVisible())
        self.assertFalse(cover.isVisible())
        self.assertTrue(cover._shot.isNull())
        stack.close()
        stack.deleteLater()

    def test_hidden_window_skips_the_entrance(self):
        stack = QStackedWidget()
        page = QWidget()
        stack.addWidget(page)
        cover = PageCover(stack)
        cover.play(page)
        self.assertFalse(cover.isVisible())
        stack.deleteLater()


class FittedPictureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scaled_once_per_size_and_keeps_aspect(self):
        pixmap = QPixmap(200, 100)
        first = widgets.fitted(pixmap, 50, 50, 2.0)
        self.assertEqual((first.width(), first.height()), (100, 50))
        self.assertEqual(first.devicePixelRatio(), 2.0)
        self.assertEqual(widgets.fitted(pixmap, 50, 50, 2.0).cacheKey(), first.cacheKey())
        self.assertNotEqual(widgets.fitted(pixmap, 80, 80, 2.0).cacheKey(), first.cacheKey())

    def test_drawn_centred(self):
        pixmap = QPixmap(20, 10)
        pixmap.fill(QColor("red"))
        image = QImage(40, 40, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        widgets.draw_fitted(painter, QRectF(0, 0, 40, 40), pixmap, 1.0)
        painter.end()
        self.assertEqual(image.pixelColor(20, 20), QColor("red"))
        self.assertEqual(image.pixelColor(20, 5), QColor("white"))


class GameSizeCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card(self, width, height):
        import ok

        from src.ui.shell import home

        window = SimpleNamespace(exists=True, width=width, height=height)
        patcher = mock.patch.object(
            ok, "og", SimpleNamespace(device_manager=SimpleNamespace(hwnd_window=window))
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        card = home.GameSizeCard()
        self.addCleanup(card.deleteLater)
        return card, window, home

    def test_old_adjust_result_gives_way_to_the_live_size(self):
        # Leo 2026-10-03: an old 「1920 × 1080」 result stayed next to a 4K window.
        card, window, home = self._card(1920, 1080)
        card.set_status("当前游戏窗口：1920 × 1080")
        window.width, window.height = 3840, 2160
        card.refresh()
        self.assertIn("1920", card.status.text())
        card._message_at -= home.MESSAGE_SECONDS + 1
        card.refresh()
        self.assertIn("3840", card.status.text())
        self.assertNotIn("1920", card.status.text())

    def test_list_follows_the_window_until_someone_picks(self):
        card, window, _home = self._card(3840, 2160)
        card.refresh()
        self.assertEqual(card.selected_resolution, (3840, 2160))
        card.combo.setCurrentIndex(card._sizes.index((2560, 1440)))
        card.refresh()
        self.assertEqual(card.selected_resolution, (2560, 1440))


class SaleDayTickTest(unittest.TestCase):
    """Leo 2026-10-06: the sale calendar's ticks did not play the tick animation."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ticking_keeps_the_boxes_so_the_tick_can_play(self):
        from datetime import date

        from src.tasks.map_trade.sale_days import sale_day_key
        from src.ui.shell import trade

        page = trade.TradePage()
        self.addCleanup(page.deleteLater)
        entries = [
            SimpleNamespace(item="苹果", shop="S1:村", reserve=0),
            SimpleNamespace(item="面包", shop="S1:村", reserve=0),
        ]
        task = SimpleNamespace(config={})
        today = date(2026, 10, 6)
        page._fill_day_panel(today, 6, entries, task)
        boxes = dict(page._panel_checks)
        self.assertTrue(all(box.isChecked() for box in boxes.values()))
        page.show()
        with (
            mock.patch.object(page, "task", return_value=task),
            mock.patch.object(data, "sale_days", return_value={6: entries}),
            mock.patch.object(
                page, "refresh", lambda: page._fill_day_panel(today, 6, entries, task)
            ),
        ):
            boxes["面包"].click()
        self.assertEqual(task.config[sale_day_key(6)], ["苹果"])
        self.assertIs(page._panel_checks["面包"], boxes["面包"])
        self.assertFalse(boxes["面包"].isChecked())
        self.assertTrue(boxes["面包"]._on.running())
        # another day still builds its own boxes
        page._fill_day_panel(today, 7, entries, task)
        self.assertIsNot(page._panel_checks["面包"], boxes["面包"])


class StartStaysOnFiendPageTest(unittest.TestCase):
    """Leo 2026-10-06: 录制/开始打 on the 魔兽追踪者 page don't jump to 首页."""

    def shell(self, current):
        from types import SimpleNamespace

        pages = {"home": object(), "fiend": object(), "map": object()}
        shown = []
        stack = SimpleNamespace(currentWidget=lambda: pages[current])
        window = SimpleNamespace(stackedWidget=stack, switchTo=shown.append)
        shell = SimpleNamespace(window=window, pages=pages, navigate=shown.append)
        return shell, shown

    def test_fiend_page_stays(self):
        from src.ui.shell.install import Shell

        shell, shown = self.shell("fiend")
        Shell._after_start(shell)
        self.assertEqual([], shown)

    def test_other_pages_go_home(self):
        from src.ui.shell.install import Shell

        shell, shown = self.shell("map")
        Shell._after_start(shell)
        self.assertEqual(["home"], shown)


class SidebarHomeLeavesSummaryTest(unittest.TestCase):
    """Leo 2026-10-09: 首页 in the sidebar on a finished run's 结算 goes home."""

    def shell(self):
        from types import SimpleNamespace

        left = []
        home = SimpleNamespace(leave_summary=lambda: left.append(True))
        shown = []
        shell = SimpleNamespace(pages={"home": home, "map": object()}, navigate=shown.append)
        return shell, shown, left

    def test_home_leaves_the_summary(self):
        from src.ui.shell.install import Shell

        shell, shown, left = self.shell()
        Shell._sidebar_clicked(shell, "home")
        self.assertEqual(([True], ["home"]), (left, shown))

    def test_other_pages_keep_it(self):
        from src.ui.shell.install import Shell

        shell, shown, left = self.shell()
        Shell._sidebar_clicked(shell, "map")
        self.assertEqual(([], ["map"]), (left, shown))


if __name__ == "__main__":
    unittest.main()
