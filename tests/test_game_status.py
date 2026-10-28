"""The status bar on top of the game (YES-BD2 #60, Leo 2026-10-28).

「不要干擾到辨識和判定」: the bar must never count as a window covering the
game, and it stays off unless the player turns it on.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.tasks import run_report
from src.ui.shell import game_status, hotkeys
from src.utils import game_status_bar


def _report(current="b", states=("done", "run", "wait")):
    rows = [
        {"key": key, "name": name, "state": state, "note": ""}
        for key, name, state in zip("abc", ("广场女神像", "每日跑图", "每日跑商"), states)
    ]
    return {"label": "一键完成日常", "started": 1000.0, "current": current, "rows": rows}


class _Task:
    name = "每日跑图"
    paused = False
    enabled = True

    def __init__(self, info=None):
        self.info = info or {}


class RunningLineTest(unittest.TestCase):
    def test_batch_shows_item_step_log_and_count(self):
        child = _Task({"当前阶段": "每日跑图：第 13 章", "Log": "战斗区域 2：压制"})
        status = game_status.running_status(_report(), None, child, False, False, 1000.0 + 768)
        self.assertEqual(status.tone, game_status.RUN)
        self.assertEqual(status.title, "每日跑图 · 第 13 章")
        self.assertEqual(status.detail, "战斗区域 2：压制")
        self.assertEqual(status.clock, "12:48")
        self.assertEqual(status.count, "第 2 / 3 项")
        self.assertAlmostEqual(status.progress, 1 / 3)

    def test_keys_come_from_the_settings(self):
        # Leo 2026-10-28: the keys set in 设置, 「无」 for one turned off.
        keys = {hotkeys.PAUSE: "F9", hotkeys.STOP: "F10"}
        with mock.patch.object(hotkeys, "keys", return_value=keys):
            status = game_status.running_status(_report(), None, _Task(), False, False, 1100.0)
        self.assertEqual(status.buttons, (("pause", "暂停", "F9"), ("stop", "停止", "F10")))
        keys = {hotkeys.PAUSE: hotkeys.NONE, hotkeys.STOP: "F12"}
        with mock.patch.object(hotkeys, "keys", return_value=keys):
            status = game_status.running_status(_report(), None, _Task(), False, False, 1100.0)
        self.assertEqual(status.buttons, (("pause", "暂停", "无"), ("stop", "停止", "F12")))

    def test_paused_says_the_keys(self):
        keys = {hotkeys.PAUSE: "F9", hotkeys.STOP: "F10"}
        with mock.patch.object(hotkeys, "keys", return_value=keys):
            status = game_status.running_status(_report(), None, _Task(), True, False, 1100.0)
        self.assertEqual(status.tone, game_status.PAUSE)
        self.assertEqual(status.title, "已暂停 · 每日跑图")
        self.assertEqual(status.buttons[0], ("pause", "继续", "F9"))

    def test_stopping(self):
        status = game_status.running_status(_report(), None, _Task(), False, True, 1100.0)
        self.assertEqual(status.tone, game_status.STOP)
        self.assertEqual(status.detail, "正在收尾，请稍等")


class EndLineTest(unittest.TestCase):
    def test_failed_item_gives_its_reason(self):
        report = _report(None, ("done", "fail", "done"))
        report["rows"][1]["note"] = "第 13 章找不到传送阵"
        report.update(finished=1000.0 + 2465, ended=run_report.ENDED_DONE)
        status = game_status.finished_status(report, "", None, 3500.0)
        self.assertEqual(status.tone, game_status.FAIL)
        self.assertEqual(status.title, "跑完：完成 2 · 失败 1")
        self.assertEqual(status.detail, "每日跑图 · 第 13 章找不到传送阵")
        self.assertEqual(status.clock, "41:05")
        self.assertEqual(status.count, "2 / 3 项")

    def test_all_done(self):
        report = _report(None, ("done", "done", "skip"))
        report.update(finished=1060.0, ended=run_report.ENDED_DONE)
        status = game_status.finished_status(report, "", None, 1100.0)
        self.assertEqual(status.tone, game_status.DONE)
        self.assertEqual(status.title, "跑完：完成 2 · 跳过 1")

    def test_one_task_alone(self):
        status = game_status.finished_status(None, "每日跑商", 1000.0, 1062.0)
        self.assertEqual((status.tone, status.title, status.clock), (game_status.DONE, "跑完 · 每日跑商", "1:02"))


class SettingTest(unittest.TestCase):
    def test_off_until_turned_on(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "configs" / "game_status_bar.json"
            with mock.patch.object(game_status_bar, "SETTINGS_FILE", path):
                self.assertFalse(game_status_bar.enabled())
                game_status_bar.set_enabled(True)
                self.assertTrue(game_status_bar.enabled())
                game_status_bar.set_enabled(False)
                self.assertFalse(game_status_bar.enabled())


class LooksThroughBarTest(unittest.TestCase):
    """「游戏被遮住」 and the takeover check never stop at the bar."""

    BAR, GAME, OTHER = 0xB0, 0x60, 0x70

    def _gui(self, under_point):
        gui = mock.MagicMock()
        gui.WindowFromPoint.return_value = under_point
        gui.GetAncestor.side_effect = lambda hwnd, _flag: hwnd
        below = {self.BAR: self.OTHER, self.OTHER: self.GAME, self.GAME: 0}
        gui.GetWindow.side_effect = lambda hwnd, _flag: below[hwnd]
        gui.IsWindowVisible.return_value = True
        rects = {self.OTHER: (5000, 0, 5100, 100), self.GAME: (0, 0, 1920, 1080)}
        gui.GetWindowRect.side_effect = lambda hwnd: rects[hwnd]
        return gui

    def test_bar_under_point_gives_the_window_below_it(self):
        game_status_bar.register(self.BAR)
        self.addCleanup(game_status_bar.unregister, self.BAR)
        gui = self._gui(self.BAR)
        with mock.patch.dict("sys.modules", {"win32gui": gui}):
            self.assertEqual(game_status_bar.window_at((960, 80)), self.GAME)

    def test_a_live_button_is_the_bar_not_the_game(self):
        # The player pressing 暂停 on the bar is not playing the game.
        game_status_bar.register(self.BAR)
        self.addCleanup(game_status_bar.unregister, self.BAR)
        game_status_bar.set_live(self.BAR, [(900, 60, 1000, 100)])
        gui = self._gui(self.BAR)
        with mock.patch.dict("sys.modules", {"win32gui": gui}):
            self.assertEqual(game_status_bar.window_at((950, 80)), self.BAR)
            self.assertEqual(game_status_bar.window_at((800, 80)), self.GAME)

    def test_buttons_stay_off_while_the_tool_presses(self):
        game_status_bar.register(self.BAR)
        self.addCleanup(game_status_bar.unregister, self.BAR)
        game_status_bar.set_live(self.BAR, [(900, 60, 1000, 100)])
        with game_status_bar.hold_clicks():
            self.assertEqual(game_status_bar.live_rects(self.BAR), [])
            self.assertFalse(game_status_bar.set_live(self.BAR, [(900, 60, 1000, 100)]))
        self.assertTrue(game_status_bar.set_live(self.BAR, [(900, 60, 1000, 100)]))

    def test_other_windows_are_left_alone(self):
        gui = self._gui(self.OTHER)
        with mock.patch.dict("sys.modules", {"win32gui": gui}):
            self.assertEqual(game_status_bar.window_at((960, 80)), self.OTHER)


class PlaceTest(unittest.TestCase):
    def test_font_follows_the_game_height(self):
        from PySide6.QtCore import QRect

        self.assertEqual(game_status.font_px(QRect(0, 0, 1920, 1080)), 19)
        self.assertEqual(game_status.font_px(QRect(0, 0, 1280, 720)), 13)
        self.assertEqual(game_status.font_px(QRect(0, 0, 3840, 2160)), 24)


class UpdateNoticeTest(unittest.TestCase):
    """Leo 2026-10-28: off by default, but after the update the player is
    shown once where to turn it on."""

    def _load(self, saved):
        from types import SimpleNamespace

        from ok import BaseTask

        from src.tasks import DailyBatchTask as batch_module

        task = batch_module.DailyBatchTask(executor=SimpleNamespace(scene=None), app=SimpleNamespace())

        def load(_self):
            _self.config = {**_self.default_config, **(saved or {})}

        def read(path):
            return dict(saved or {}) if "DailyBatchTask" in str(path) else {}

        with (
            mock.patch.object(batch_module, "_read_json", side_effect=read),
            mock.patch.object(BaseTask, "load_config", load),
        ):
            task.load_config()
        return task

    def test_shown_to_players_from_before_only(self):
        from src.tasks.DailyBatchTask import STATUS_BAR_NOTICE_KEY

        self.assertFalse(self._load(None).config[STATUS_BAR_NOTICE_KEY])
        self.assertTrue(self._load({"启用": True}).config[STATUS_BAR_NOTICE_KEY])
        saved = {"启用": True, STATUS_BAR_NOTICE_KEY: False}
        self.assertFalse(self._load(saved).config[STATUS_BAR_NOTICE_KEY])

    def test_points_at_the_switch_on_settings(self):
        from types import SimpleNamespace

        from src.ui.shell import new_setting_notice

        row, item = object(), object()
        shell = mock.Mock()
        shell.pages = {"settings": SimpleNamespace(status_bar_row=row)}
        shell.sidebar.items = {"settings": item}
        first, second = new_setting_notice.status_bar_steps(shell)
        self.assertIs(item, first.target())
        second.before()
        shell.navigate.assert_called_once_with("settings")
        self.assertIs(row, second.target())
        self.assertIn(new_setting_notice.show_status_bar_notice, new_setting_notice.NOTICES)

    def test_texts_are_translated(self):
        import gettext

        from src.ui.shell import new_setting_notice

        root = Path(__file__).resolve().parents[1] / "i18n"
        for language in ("en_US", "ja_JP", "ko_KR"):
            translation = gettext.translation("ok", root, languages=[language])
            for step in new_setting_notice.status_bar_steps(mock.Mock()):
                for text in (step.title, step.body):
                    self.assertNotEqual(text, translation.gettext(text), (language, text))


class StagePickerTest(unittest.TestCase):
    """塔洛斯教材 (Leo 2026-10-28 「暫停後可以在上面切換關卡」)."""

    class Picker:
        count, current, cleared, chosen = 9, 2, {1}, None

        def pick(self, n):
            self.chosen = n

    def _paused(self):
        keys = {hotkeys.PAUSE: "F9", hotkeys.STOP: "F10"}
        task = _Task({"当前阶段": "第 2 关 · 第 5 回合"})
        task.name = "塔洛斯教材"
        with mock.patch.object(hotkeys, "keys", return_value=keys):
            running = game_status.running_status(None, task, None, False, False, 1100.0)
            paused = game_status.running_status(None, task, None, True, False, 1100.0)
        return running, paused

    def test_title_has_stage_and_turn(self):
        running, _paused = self._paused()
        self.assertEqual(running.title, "塔洛斯教材 · 第 2 关 · 第 5 回合")
        self.assertIsNone(game_status.with_picker(running, self.Picker()).picker)

    def test_arrows_go_round_and_say_what_resume_does(self):
        _running, paused = self._paused()
        picker = self.Picker()
        self.assertEqual(game_status.with_picker(paused, picker).picker, (2, 9, False))
        game_status.step_stage(picker, game_status.PREV)
        status = game_status.with_picker(paused, picker)
        self.assertEqual(status.picker, (1, 9, True))
        self.assertEqual(status.detail, "按继续改打第 1 关")
        game_status.step_stage(picker, game_status.PREV)
        self.assertEqual(picker.chosen, 9)
        game_status.step_stage(picker, game_status.NEXT)
        self.assertEqual(picker.chosen, 1)

    def test_other_tasks_have_no_picker(self):
        _running, paused = self._paused()
        self.assertIsNone(game_status.with_picker(paused, None).picker)


class ButtonLookTest(unittest.TestCase):
    """Leo 2026-10-28 「暫停 停止 不用寫中文 用圖示即可」: the buttons show their
    icon and key, never the word."""

    def _drawn(self, paused: bool) -> tuple[list[str], list[str]]:
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])
        keys = {hotkeys.PAUSE: "F9", hotkeys.STOP: hotkeys.NONE}
        with mock.patch.object(hotkeys, "keys", return_value=keys):
            status = game_status.running_status(_report(), None, _Task(), paused, False, 1100.0)
        bar = game_status.StatusBar()
        self.addCleanup(bar.deleteLater)
        bar.place(QRect(0, 0, 2560, 1440), 24)
        bar.set_status(status)
        texts, icons = [], []
        real_paint = game_status.icons.paint

        def text(_painter, _font, _colour, words, _rect, *_align):
            texts.append(words)

        def paint(painter, rect, name, *rest):
            icons.append(name)
            real_paint(painter, rect, name, *rest)

        with (
            mock.patch.object(game_status.StatusBar, "_text", staticmethod(text)),
            mock.patch.object(game_status.icons, "paint", paint),
        ):
            bar.grab()
        shown = [action for action, _rect in bar._button_rects]
        self.assertEqual(shown, [hotkeys.PAUSE, hotkeys.STOP])
        return texts, icons

    def test_running_shows_pause_and_stop_icons_with_their_keys(self):
        texts, icons = self._drawn(paused=False)
        for word in ("暂停", "继续", "停止"):
            self.assertNotIn(word, texts)
        self.assertIn("F9", texts)
        self.assertIn("无", texts)  # a key turned off in 设置 still says so
        self.assertIn("pause", icons)
        self.assertIn("square", icons)

    def test_paused_shows_the_play_icon(self):
        texts, icons = self._drawn(paused=True)
        self.assertNotIn("继续", texts)
        self.assertIn("play", icons)
        self.assertNotIn("pause", icons)



class QuickPressTest(unittest.TestCase):
    """Leo's 4K 2026-10-28 16:02: a quick press on ▶ came before the cursor
    had rested on it, went through to the game and counted as playing it."""

    def _bar(self):
        from PySide6.QtCore import QRectF
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])
        bar = game_status.StatusBar()
        self.addCleanup(bar.deleteLater)
        bar.resize(400, 100)
        bar._button_rects = [(hotkeys.PAUSE, QRectF(100, 50, 50, 30))]
        hwnd = int(bar.winId())
        game_status_bar.register(hwnd)
        self.addCleanup(game_status_bar.unregister, hwnd)
        return bar, hwnd

    def _watch(self, bar, cursor):
        gui = mock.MagicMock()
        gui.GetWindowRect.return_value = (1000, 0, 1400, 100)
        api = mock.MagicMock()
        api.GetCursorPos.return_value = cursor
        with (
            mock.patch.dict("sys.modules", {"win32gui": gui, "win32api": api}),
            mock.patch.object(game_status_bar, "_set_click_through"),
        ):
            bar._watch_mouse()

    def test_the_first_look_with_the_cursor_on_a_button_takes_the_click(self):
        bar, hwnd = self._bar()
        self._watch(bar, (1120, 60))
        self.assertTrue(bar._live)
        self.assertEqual([(1100, 50, 1150, 80)], game_status_bar.live_rects(hwnd))

    def test_the_buttons_are_known_even_while_the_tool_presses(self):
        # a press there is the bar's, never the player using the game
        bar, _hwnd = self._bar()
        with game_status_bar.hold_clicks():
            self._watch(bar, (1120, 60))
            self.assertFalse(bar._live)
        self.assertTrue(game_status_bar.on_button((1120, 60)))
        self.assertFalse(game_status_bar.on_button((1050, 60)))

    def test_off_the_buttons_the_mouse_goes_through(self):
        bar, hwnd = self._bar()
        self._watch(bar, (1050, 60))
        self.assertFalse(bar._live)
        self.assertEqual([], game_status_bar.live_rects(hwnd))


if __name__ == "__main__":
    unittest.main()
