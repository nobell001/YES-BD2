import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.shell import config_form
from src.ui.shell.pvp_panel import PvpPanel, max_count


class _Config(dict):
    def get_default(self, key):
        return {"竞技场战斗倍数": 40, "战斗场数": "1"}.get(key)


class _Task:
    def __init__(self, multiplier=40, count="1"):
        self.config = _Config(
            {"竞技场战斗倍数": multiplier, "战斗场数": count, "舞台移动方式": "鼠标"}
        )
        self.default_config = dict(self.config)
        self.config_type = {}
        self.config_description = {}


class PVPTask(_Task):
    """Same class name as the real task, so ConfigForm picks its panel."""


class PvpPanelTest(unittest.TestCase):
    """Leo 2026-10-14: 倍数 × 场数 never over 40 free cocktails."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_max_count_is_40_over_multiplier(self):
        self.assertEqual([max_count(m) for m in (1, 10, 13, 20, 40)], [40, 4, 3, 2, 1])

    def test_bigger_multiplier_lowers_the_count(self):
        task = _Task(5, "8")
        panel = PvpPanel(task)
        panel.multiplier.setValue(10)
        self.assertEqual(task.config, {**task.config, "竞技场战斗倍数": 10, "战斗场数": "4"})
        panel.multiplier.setValue(99)
        self.assertEqual((task.config["竞技场战斗倍数"], task.config["战斗场数"]), (40, "1"))
        panel.multiplier.setValue(0)
        self.assertEqual(task.config["竞技场战斗倍数"], 1)
        self.assertEqual(panel.count.maximum(), 40)

    def test_typed_count_is_kept_within_the_limit(self):
        task = _Task(10, "3")
        panel = PvpPanel(task)
        panel.count.edit.setText("6")
        panel.count.edit.editingFinished.emit()
        self.assertEqual(task.config["战斗场数"], "4")
        self.assertEqual(panel.count.edit.text(), "4")
        panel.count.edit.setText("")
        panel.count.edit.editingFinished.emit()
        self.assertEqual((task.config["战斗场数"], panel.count.edit.text()), ("4", "4"))

    def test_sliders_stop_at_the_ends(self):
        task = _Task(40, "1")
        panel = PvpPanel(task)
        self.assertEqual(panel.multiplier.value(), 40)
        self.assertEqual((panel.count.minimum(), panel.count.maximum()), (1, 1))
        self.assertFalse(panel.count.isEnabled())  # 40 倍 leaves one 场
        panel.multiplier._nudge(1)
        self.assertEqual(task.config["竞技场战斗倍数"], 40)
        self.assertEqual(panel.cups_text.text(), "40 / 40 杯")

    def test_multiplier_slider_snaps_to_the_whole_stops(self):
        task = _Task(1, "40")
        panel = PvpPanel(task)
        panel.multiplier._slide_to(0.5, jump=True)  # middle of 1 2 4 5 8 10 20 40
        self.assertIn(task.config["竞技场战斗倍数"], (5, 8))
        panel.multiplier._nudge(1)
        self.assertIn(task.config["竞技场战斗倍数"], (8, 10))
        panel.multiplier.edit.setText("3")  # any 1~40 can still be typed
        panel.multiplier.edit.editingFinished.emit()
        self.assertEqual(task.config["竞技场战斗倍数"], 3)
        self.assertEqual(panel.count.maximum(), 13)
        self.assertLessEqual(3 * int(task.config["战斗场数"]), 40)

    def test_max_stays_max_and_follows_the_multiplier(self):
        task = _Task(10, "2")
        panel = PvpPanel(task)
        panel.max_button.click()
        self.assertEqual(task.config["战斗场数"], "MAX")
        panel.multiplier.setValue(20)
        self.assertEqual(task.config["战斗场数"], "MAX")
        self.assertEqual(panel.count.edit.text(), "2")
        panel.count.setValue(1)  # picking a number turns MAX off
        self.assertEqual(task.config["战斗场数"], "1")
        self.assertFalse(panel.max_button.isChecked())

    def test_saved_values_keep_their_types(self):
        task = _Task(10, "3")
        panel = PvpPanel(task)
        panel.multiplier._nudge(1)
        panel.count._nudge(-1)
        self.assertIsInstance(task.config["竞技场战斗倍数"], int)
        self.assertIsInstance(task.config["战斗场数"], str)

    def test_task_settings_form_shows_the_panel_once(self):
        form = config_form.ConfigForm(PVPTask(), skip=("启用",))
        self.assertEqual(len(form.findChildren(PvpPanel)), 1)
        self.assertNotIn("竞技场战斗倍数", form._rows)
        self.assertNotIn("战斗场数", form._rows)
        self.assertIn("舞台移动方式", form._rows)
        form.task.config["竞技场战斗倍数"] = 20
        form.reset()
        self.assertEqual(form.findChild(PvpPanel).multiplier.edit.text(), "40")


if __name__ == "__main__":
    unittest.main()
