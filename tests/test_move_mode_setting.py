"""设置 → 移动方式 (Leo 2026-11-06 「設定也要可以設定移動方式」「WASD 和點擊」
「鏡中之戰 末日之書 救贖之塔 都要照顧到」): one switch, the same setting the
three walking tasks read."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.tasks.PVPTask import STAGE_MOVE_CLICK, STAGE_MOVE_WASD
from src.ui.shell import settings
from src.ui.shell.widgets import OptionSwitch


class MoveModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _pvp(self, saved=None):
        pvp = SimpleNamespace(config={"舞台移动方式": saved} if saved else {})
        return mock.patch.object(settings.data, "task_by_class_name", return_value=pvp), pvp

    def test_reads_and_writes_the_pvp_setting(self):
        patch, pvp = self._pvp(STAGE_MOVE_WASD)
        with patch:
            self.assertEqual(STAGE_MOVE_WASD, settings.move_mode())
            settings.set_move_mode(STAGE_MOVE_CLICK)
            self.assertEqual(STAGE_MOVE_CLICK, pvp.config["舞台移动方式"])
            settings.set_move_mode("乱写")
            self.assertEqual(STAGE_MOVE_CLICK, pvp.config["舞台移动方式"])

    def test_unknown_or_missing_is_click(self):
        for saved in (None, "旧的值"):
            patch, _pvp = self._pvp(saved)
            with patch:
                self.assertEqual(STAGE_MOVE_CLICK, settings.move_mode())
        with mock.patch.object(settings.data, "task_by_class_name", return_value=None):
            self.assertEqual(STAGE_MOVE_CLICK, settings.move_mode())
            settings.set_move_mode(STAGE_MOVE_WASD)  # no task: nothing to write, no error

    def test_switch_shows_the_choice_and_flips(self):
        switch = OptionSwitch(
            STAGE_MOVE_CLICK, STAGE_MOVE_WASD, STAGE_MOVE_WASD, labels=settings.MOVE_LABELS
        )
        seen = []
        switch.changed.connect(seen.append)
        self.assertEqual("WASD", switch.text())
        switch.click()
        self.assertEqual(STAGE_MOVE_CLICK, switch.value())
        self.assertEqual([STAGE_MOVE_CLICK], seen)
        switch.set_value(STAGE_MOVE_WASD, quiet=True)
        self.assertEqual([STAGE_MOVE_CLICK], seen)
        self.assertEqual("WASD", switch.text())

    def test_doom_book_and_tower_read_the_same_key(self):
        from src.tasks.DoomBookTask import CartridgeFieldTask, DoomBookTask
        from src.tasks.RedemptionTowerTask import RedemptionTowerTask

        self.assertTrue(issubclass(DoomBookTask, CartridgeFieldTask))
        self.assertTrue(issubclass(RedemptionTowerTask, CartridgeFieldTask))
        pvp = SimpleNamespace(config={settings.MOVE_KEY: STAGE_MOVE_WASD})
        task = SimpleNamespace(executor=SimpleNamespace(get_task_by_class=lambda _cls: pvp))
        self.assertEqual(STAGE_MOVE_WASD, CartridgeFieldTask._move_mode(task))


class _Stop(Exception):
    pass


class WrongSettingTest(unittest.TestCase):
    """Leo 2026-11-06 「點了畫面沒動代表用戶設定錯誤 程式可以自動執行另外一種移動方式
    且在結算報表提醒」 / 「反過來不用」: clicks that leave the screen as it was
    → walk by WASD and say so in the report; never the other way round."""

    def _pvp(self, frames):
        import numpy as np

        from src.tasks.PVPTask import PVPTask

        task = object.__new__(PVPTask)
        task.config = {"舞台移动方式": STAGE_MOVE_CLICK}
        task.name = "镜中之战"
        task.info_set = lambda *_a, **_k: None
        task.log_info = lambda *_a, **_k: None
        task._save_flow_diagnostic = lambda *_a, **_k: None
        task._click_pvp_stage_once = mock.Mock(return_value=True)
        task._recover_stage_position = mock.Mock(return_value=True)
        task._walk_onto_stage = mock.Mock(return_value=True)
        task._wait_for_ocr_patterns = lambda *_a, **_k: (False, "")
        task._mf_roi = mock.Mock(side_effect=_Stop)  # the menu after the stage: not tested here
        from src.utils.wait_limits import scene

        before, now = frames
        task._scene_at_press = scene(np.full((1080, 1920, 3), before, dtype=np.uint8))
        task.capture_frame = lambda: np.full((1080, 1920, 3), now, dtype=np.uint8)
        return task

    def test_clicks_that_move_nothing_walk_by_wasd_and_tell_the_report(self):
        from src.tasks.PVPTask import MOVE_MODE_NOTES, PVPTask

        task = self._pvp((90, 90))
        with mock.patch("src.tasks.PVPTask.run_report.add_current_note") as note:
            with self.assertRaises(_Stop):
                PVPTask._start_auto_battle(task, 1)
        task._walk_onto_stage.assert_called_once()
        note.assert_called_once_with(MOVE_MODE_NOTES[STAGE_MOVE_WASD])

    def test_clicks_that_move_the_screen_say_nothing(self):
        from src.tasks.PVPTask import PVPTask

        task = self._pvp((90, 200))
        with mock.patch("src.tasks.PVPTask.run_report.add_current_note") as note:
            with self.assertRaises(_Stop):
                PVPTask._start_auto_battle(task, 1)
        task._walk_onto_stage.assert_called_once()  # still walked, as before
        note.assert_not_called()

    def test_wasd_setting_never_gets_the_note(self):
        from src.tasks.PVPTask import MOVE_MODE_NOTES

        self.assertNotIn(STAGE_MOVE_CLICK, MOVE_MODE_NOTES)

    def _field(self, first, frames):
        import numpy as np

        from src.tasks.DoomBookTask import CartridgeFieldTask
        from src.utils.wait_limits import scene

        before, now = frames
        task = SimpleNamespace(
            _scene_at_press=scene(np.full((1080, 1920, 3), before, dtype=np.uint8)),
            name="末日之书",
            label="末日之书",
            _keys_refused=False,
            log_info=lambda *_a, **_k: None,
            look_again=lambda check: True,
            capture_frame=lambda: np.full((1080, 1920, 3), now, dtype=np.uint8),
            _move_mode=lambda: first,
            _click_to_marker=mock.Mock(return_value=first == STAGE_MOVE_WASD),
            _walk_to_marker=mock.Mock(return_value=first == STAGE_MOVE_CLICK),
        )
        return CartridgeFieldTask._reach_marker, task

    def test_doom_book_and_tower_tell_the_report_too(self):
        reach, task = self._field(STAGE_MOVE_CLICK, [90, 90])
        with mock.patch("src.tasks.PVPTask.run_report.add_current_note") as note:
            self.assertTrue(reach(task))
        note.assert_called_once()

        reach, task = self._field(STAGE_MOVE_CLICK, [90, 200])
        with mock.patch("src.tasks.PVPTask.run_report.add_current_note") as note:
            self.assertTrue(reach(task))
        note.assert_not_called()

        reach, task = self._field(STAGE_MOVE_WASD, [90, 90])
        with mock.patch("src.tasks.PVPTask.run_report.add_current_note") as note:
            self.assertTrue(reach(task))
        note.assert_not_called()


if __name__ == "__main__":
    unittest.main()
