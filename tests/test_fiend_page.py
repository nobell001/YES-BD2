import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from src.tasks import FiendHuntTask as fiend
from src.tasks.fiend_hunt import costumes
from src.ui.shell import data, fiend_page, guide_page, hotkeys

_SEEN = mock.patch.object(guide_page, "SEEN_FILE", Path(tempfile.mkdtemp()) / "ui_guide.json")


def setUpModule():
    _SEEN.start()  # never the real configs/ui_guide.json


def tearDownModule():
    _SEEN.stop()


class FiendPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.replay = SimpleNamespace(
            name="魔兽追踪者自动站位",
            enabled=False,
            info={},
            config={"模式": fiend.MODE_REPLAY, "存档": "", "技能判断": fiend.CARDS_SUMMONS},
        )
        self.record = SimpleNamespace(name="魔兽录制", enabled=False, info={}, config={"存档": ""})
        tasks = {"FiendHuntTask": self.replay, "FiendHuntRecordTask": self.record}
        for patch in (
            mock.patch.object(fiend_page, "saves_root", lambda: self.root),
            mock.patch.object(data, "task_by_class_name", tasks.get),
            mock.patch.object(data, "last_run", lambda _name: None),
            mock.patch.object(data, "busy", lambda: False),
            mock.patch.object(data, "executor", lambda: None),
            mock.patch.object(hotkeys, "KEYS_FILE", self.root / "hotkeys.json"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_saves_of_every_kind_are_listed(self):
        (self.root / "空的").mkdir()
        shots = self.root / "截图"
        shots.mkdir()
        (shots / "T01.png").write_bytes(b"")
        (shots / "说明.txt").write_text("x", encoding="utf-8")
        saves = {save.name: save for save in fiend_page.list_saves(self.root)}
        self.assertEqual(saves["空的"].kind, "empty")
        self.assertEqual(saves["截图"].kind, "shots")
        self.assertEqual(len(saves["截图"].shots), 1)

    def test_picking_a_save_points_both_tasks_at_it(self):
        folder = self.root / "10月"
        folder.mkdir()
        page = fiend_page.FiendPage()
        page.refresh()
        self.assertEqual(page._folder, folder)
        other = self.root / "11月"
        other.mkdir()
        page.select(other)
        self.assertEqual(self.replay.config["存档"], str(other))
        self.assertEqual(self.record.config["存档"], str(other))

    def test_card_check_setting_keeps_the_task_values(self):
        (self.root / "10月").mkdir()
        page = fiend_page.FiendPage()
        page.refresh()
        page._set(self.replay, "技能判断", fiend.CARDS_ALL)
        self.assertIn(self.replay.config["技能判断"], fiend.CARD_CHOICES)

    def test_a_save_offers_both_ways_and_warns_about_the_costume_order(self):
        # Leo 2026-10-06: 调整服装技能 or 不调整 (只看召唤物), with a reminder.
        from src.tasks.fiend_hunt.record import FightRecord, TurnState, save_record

        folder = self.root / "10月"
        folder.mkdir()
        state = TurnState(1, 1, ("克蕾西亚",), {"克蕾西亚": (2, 0)}, skills={"克蕾西亚": "攻击"})
        save_record(FightRecord({1: state}, title="t"), folder / "record.json")
        page = fiend_page.FiendPage()
        page.refresh()
        self.assertIn("服装顺序设置", page.card_note.text())
        self.replay.config["技能判断"] = fiend.CARDS_ALL
        page._detail_key = None
        page.refresh()
        self.assertNotIn("服装顺序设置", page.card_note.text())

    def test_the_record_key_is_picked_from_f6_to_f12(self):
        # Leo 2026-10-06; F11/F12 added 2026-10-09 (YES-BD2 issue #1)
        (self.root / "10月").mkdir()
        page = fiend_page.FiendPage()
        page.refresh()
        box = page.key_box
        self.assertEqual(
            [f"F{n}" for n in range(6, 13)], [box.itemText(i) for i in range(box.count())]
        )
        self.assertEqual("F8", box.currentText())
        box.setCurrentText("F9")
        self.assertEqual("F9", self.record.config["录制按键"])
        page.refresh()
        self.assertIn("F9", page.run_note.text())

    def test_boss_pushing_is_a_switch_left_off(self):
        # Leo 2026-10-06: ticked only for a boss that moves the units.
        (self.root / "10月").mkdir()
        page = fiend_page.FiendPage()
        page.refresh()
        self.assertFalse(page.push_switch.isChecked())
        page.push_switch.setChecked(True)
        self.assertIs(True, self.replay.config[fiend.PUSH_OPTION])

    def test_switching_ways_changes_the_page_in_place(self):
        # Leo 2026-10-06: the switch froze the page, then showed the old way.
        from src.tasks.fiend_hunt.record import FightRecord, TurnState, save_record

        folder = self.root / "10月"
        folder.mkdir()
        state = TurnState(1, 1, ("克蕾西亚",), {"克蕾西亚": (2, 0)}, skills={"克蕾西亚": "攻击"})
        save_record(FightRecord({1: state}, title="t"), folder / "record.json")
        page = fiend_page.FiendPage()
        page.refresh()
        settings = page.cards_switch
        with mock.patch("src.tasks.fiend_hunt.chart.build_chart") as build:
            settings._buttons["all"].click()
            QApplication.processEvents()
        build.assert_not_called()  # the chart's turns are kept
        self.assertEqual(fiend.CARDS_ALL, self.replay.config["技能判断"])
        self.assertIs(settings, page.cards_switch)  # the page wasn't rebuilt
        self.assertNotIn("服装顺序设置", page.card_note.text())
        self.assertTrue(page._chart_box._everyone)

    def test_no_save_shows_the_guide(self):
        page = fiend_page.FiendPage()
        page.refresh()
        self.assertFalse(page.start_button.isEnabled())
        self.assertFalse(page.guide.content.isHidden())

    def test_guide_opens_on_the_first_visit_only(self):
        # Leo 2026-10-06: under the turns, open the first time the page is seen.
        (self.root / "10月").mkdir()
        (self.root / "10月" / "a.png").write_bytes(b"")
        guide_page.SEEN_FILE.unlink(missing_ok=True)
        page = fiend_page.FiendPage()
        page.refresh()
        self.assertTrue(page.guide.content.isHidden())  # a save exists, not shown yet
        layout = page.body
        self.assertGreater(layout.indexOf(page.guide), layout.indexOf(page.turns_card))
        page.show()
        page.refresh()
        QApplication.processEvents()
        self.assertFalse(page.guide.content.isHidden())
        self.assertTrue(guide_page.seen("fiend"))
        page.close()
        again = fiend_page.FiendPage()
        again.show()
        again.refresh()
        QApplication.processEvents()
        self.assertTrue(again.guide.content.isHidden())
        again.close()

    def test_record_and_start_sit_in_the_save_card(self):
        # Leo 2026-10-06: not top right, somewhere you see them.
        (self.root / "10月").mkdir()
        page = fiend_page.FiendPage()
        page.refresh()
        for button in (page.record_button, page.start_button):
            self.assertTrue(page.detail.isAncestorOf(button))
        self.assertEqual("开始录制", page.record_button.text())
        self.assertIn("F8", page.run_note.text())

    def test_a_rebuild_keeps_the_buttons(self):
        folder = self.root / "10月"
        folder.mkdir()
        page = fiend_page.FiendPage()
        page.refresh()
        page._detail_key = None
        page.refresh()
        self.assertTrue(page.detail.isAncestorOf(page.record_button))
        self.record.enabled = True
        page.refresh()
        self.assertEqual("停止录制", page.record_button.text())

    def test_stop_recording_shows_at_once_and_a_second_press_does_nothing(self):
        # Leo 2026-10-10: a press shows at once, or the player keeps pressing.
        (self.root / "10月").mkdir()
        self.record.enabled = True
        self.record.disable = lambda: setattr(self.record, "enabled", False)
        self.record.unpause = lambda: None
        with (
            mock.patch.object(data, "current_task", lambda: self.record),
            mock.patch.object(data, "onetime_tasks", lambda: []),
            mock.patch("src.ui.shell.clone_flow.drop_waiting_job", lambda: False),
            mock.patch("src.ui.shell.actions.start") as start,
        ):
            page = fiend_page.FiendPage()
            page.refresh()
            page.record_or_stop()
            self.assertEqual("正在停止…", page.record_button.text())
            self.assertFalse(page.record_button.isEnabled())
            page.record_or_stop()  # the recording is still ending its step
            start.assert_not_called()
        page.refresh()  # it ended
        self.assertEqual("开始录制", page.record_button.text())


class PageSpeedTest(unittest.TestCase):
    """Leo 2026-10-06 (效能、防卡死): the page reads no more than it must."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.replay = SimpleNamespace(
            name="r", enabled=False, info={}, config={"模式": fiend.MODE_REPLAY, "存档": ""}
        )
        self.record = SimpleNamespace(name="w", enabled=False, info={}, config={"存档": ""})
        tasks = {"FiendHuntTask": self.replay, "FiendHuntRecordTask": self.record}
        for patch in (
            mock.patch.object(fiend_page, "saves_root", lambda: self.root),
            mock.patch.object(data, "task_by_class_name", tasks.get),
            mock.patch.object(data, "last_run", lambda _name: None),
            mock.patch.object(data, "busy", lambda: False),
            mock.patch.object(data, "executor", lambda: None),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def save(self, name, turns, cells=None):
        import cv2
        import numpy as np

        from src.tasks.fiend_hunt.record import FightRecord, TurnState, save_record

        folder = self.root / name
        folder.mkdir(exist_ok=True)
        states, shots = {}, {}
        for turn in turns:
            cell = (cells or {}).get(turn, (2, 0))
            states[turn] = TurnState(
                turn, 1, ("克蕾西亚",), {"克蕾西亚": cell}, skills={"克蕾西亚": "攻击"}
            )
            shots[turn] = f"turn{turn:02d}.png"
            frame = np.full((2160, 3840, 3), 40 + turn, np.uint8)
            (folder / shots[turn]).write_bytes(cv2.imencode(".png", frame)[1].tobytes())
        save_record(FightRecord(states, title=name, screenshots=shots), folder / "record.json")
        return folder

    def wait(self, done, seconds=3.0):
        import time

        end = time.monotonic() + seconds
        while not done() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        return done()

    def test_screenshots_are_read_small_and_only_for_the_screenshot_view(self):
        self.save("10月", (1, 3))
        page = fiend_page.FiendPage()
        page.refresh()
        tiles = list(page._tiles.values())
        self.assertTrue(all(not tile.picture.has_picture() for tile in tiles))  # 排轴 shown
        page._set_view("shots")
        self.assertTrue(self.wait(lambda: all(tile.picture.has_picture() for tile in tiles)))
        for tile in tiles:
            self.assertLessEqual(tile.picture._pixmap.width(), fiend_page.THUMB.width() * 2)

    def test_a_turn_recorded_again_shows_on_the_page(self):
        folder = self.save("10月", (1, 3))
        page = fiend_page.FiendPage()
        page.refresh()
        before = page._chart_box
        self.save("10月", (1, 3), cells={3: (1, 1)})  # turn 3 recorded again
        page.refresh()
        self.assertIsNot(before, page._chart_box)
        units = page._chart_box._turns[3].units
        self.assertEqual([(1, 1)], [unit.cell for unit in units if unit.name == "克蕾西亚"])
        self.assertEqual(folder, page._folder)

    def test_the_list_shows_turns_recorded_meanwhile(self):
        # Leo 2026-10-06: a save just recorded still said 还没录.
        (self.root / "礦山").mkdir()
        page = fiend_page.FiendPage()
        page.refresh()
        self.assertIn("还没录", page._rows["礦山"].findChildren(fiend_page.Text)[-1].text())
        self.save("礦山", (1, 3))
        page.refresh()
        texts = [text.text() for text in page._rows["礦山"].findChildren(fiend_page.Text)]
        self.assertIn("2 回合", texts)

    def test_unchanged_saves_are_not_read_again(self):
        for name in ("a", "b", "c"):
            self.save(name, (1,))
        fiend_page.list_saves(self.root)
        with mock.patch.object(fiend_page, "SaveInfo", side_effect=AssertionError) as info:
            self.assertEqual(3, len(fiend_page.list_saves(self.root)))
        info.assert_not_called()


class TeamEditorTest(unittest.TestCase):
    """编辑队伍 (Leo 2026-10-06): TEAM1/2/3, add and remove characters."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def editor(self):
        from src.ui.shell.fiend_team import TeamEditor

        return TeamEditor({1: ["克蕾西亚", "艾尼尔"], 2: ["黛安娜"]}, {}, 1)

    def test_tabs_for_three_teams_only_recorded_ones_open(self):
        editor = self.editor()
        buttons = editor.tabs._buttons
        self.assertEqual(["1", "2", "3"], list(buttons))
        self.assertEqual(["TEAM1", "TEAM2", "TEAM3"], [b.text() for b in buttons.values()])
        self.assertFalse(buttons["3"].isEnabled())

    def test_adding_and_removing_change_only_that_team(self):
        editor = self.editor()
        editor.toggle("马莫尼勒")
        editor.remove("艾尼尔")
        self.assertEqual({1: ["克蕾西亚", "马莫尼勒"]}, editor.changed_teams())
        editor._reset()
        self.assertEqual({}, editor.changed_teams())

    def test_five_characters_at_most_and_one_kept(self):
        editor = self.editor()
        for name in ("马莫尼勒", "黛安娜", "帕莱特", "班塔纳"):
            editor.toggle(name)
        self.assertEqual(5, len(editor.members[1]))
        editor.toggle("莉亚特里斯")  # a sixth isn't taken
        self.assertEqual(5, len(editor.members[1]))
        editor._show_team(2)
        editor.remove("黛安娜")
        self.assertEqual(["黛安娜"], editor.members[2])

    def test_a_character_in_another_team_cant_be_added(self):
        # Leo 2026-10-06: one character, one team.
        editor = self.editor()
        editor.toggle("黛安娜")
        self.assertEqual({}, editor.changed_teams())
        self.assertIn("TEAM2", editor.count.text())
        tile = next(t for t in editor.tiles if t.character.name == "黛安娜")
        self.assertEqual(2, tile.taken)
        editor._show_team(2)
        self.assertIsNone(tile.taken)
        self.assertTrue(tile.chosen)

    def test_a_click_redraws_tiles_instead_of_rebuilding_them(self):
        editor = self.editor()
        tiles = list(editor.tiles)
        editor.toggle("马莫尼勒")
        editor.search.setText("Glacia")
        editor._show_team(2)
        self.assertEqual(tiles, editor.tiles)

    def test_search_finds_by_any_language(self):
        editor = self.editor()
        editor.search.setText("Glacia")
        self.assertEqual(["克蕾西亚"], [c.name for c in editor._shown()])
        editor.search.setText("")
        editor.stars.set_value("3")
        self.assertTrue(all(c.star == 3 for c in editor._shown()))


if __name__ == "__main__":
    unittest.main()


class ChartEditTest(unittest.TestCase):
    """The chart can be adjusted after recording (Leo 2026-10-06)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from src.tasks.fiend_hunt.record import FightRecord, TurnState, save_record

        self.folder = Path(tempfile.mkdtemp())
        cells = {"克蕾西亚": (2, 0), "马莫尼勒": (1, 3), "艾尼尔": (2, 1)}
        order = ("克蕾西亚", "马莫尼勒", "艾尼尔")
        skills = {"克蕾西亚": "攻击", "马莫尼勒": "技能2", "艾尼尔": "攻击"}
        state = TurnState(1, 1, order, cells, skills=skills, bursts={"马莫尼勒": 3})
        save_record(FightRecord({1: state}, title="t"), self.folder / "record.json")

    def view(self):
        from src.tasks.fiend_hunt.chart import build_chart
        from src.tasks.fiend_hunt.saves import edit_turn, load_save
        from src.ui.shell.fiend_chart import ChartView

        record = load_save(self.folder)
        turns = build_chart(record, self.folder, lambda _path: None)
        return ChartView(
            turns, record=record, save=lambda state, changed: edit_turn(self.folder, state, changed)
        )

    def saved(self):
        from src.tasks.fiend_hunt.saves import load_save

        return load_save(self.folder)

    def rows(self, view):
        from src.ui.shell.fiend_chart import OrderRow

        self.app.processEvents()
        return [row for row in view.findChildren(OrderRow) if row.isVisibleTo(view)]

    def test_a_card_change_is_saved_and_marked(self):
        view = self.view()
        view._edit(1, "克蕾西亚", "card", "技能1")
        record = self.saved()
        self.assertEqual("技能1", record.turns[1].skills["克蕾西亚"])
        self.assertEqual(0, record.turns[1].bursts["克蕾西亚"])
        self.assertEqual({1: frozenset({"克蕾西亚"})}, record.edited)

    def test_an_attack_drops_the_burst(self):
        view = self.view()
        view._edit(1, "马莫尼勒", "card", "攻击")
        self.assertNotIn("马莫尼勒", self.saved().turns[1].bursts)

    def drag(self, widget, start, end):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        def send(kind, local, buttons):
            point = QPointF(local)
            event = QMouseEvent(
                kind,
                point,
                QPointF(widget.mapToGlobal(point.toPoint())),
                Qt.LeftButton,
                buttons,
                Qt.NoModifier,
            )
            QApplication.sendEvent(widget, event)

        send(QEvent.MouseButtonPress, start, Qt.LeftButton)
        middle = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
        send(QEvent.MouseMove, middle, Qt.LeftButton)
        send(QEvent.MouseMove, end, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, end, Qt.NoButton)

    def test_dragging_a_row_down_changes_the_order(self):
        # Leo 2026-10-06: the order cards are dragged, no arrows.
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest

        view = self.view()
        view.resize(1100, 700)
        view.show()
        first, _second, last = self.rows(view)
        below_last = last.mapTo(first, QPoint(20, last.height() - 4))
        self.drag(first, QPoint(20, 20), below_last)
        QTest.qWait(400)  # the row slides into its place, then the order is saved
        record = self.saved()
        self.assertEqual(("马莫尼勒", "艾尼尔", "克蕾西亚"), record.turns[1].order)
        self.assertEqual(frozenset(record.turns[1].order), record.edited[1])
        self.assertEqual(["马莫尼勒", "艾尼尔", "克蕾西亚"], [r.unit.name for r in self.rows(view)])

    def test_a_dragged_row_follows_the_mouse_and_the_others_make_room(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        view = self.view()
        view.resize(1100, 700)
        view.show()
        first, second, _last = self.rows(view)
        start = (first.y(), second.y())

        def send(kind, y, buttons):
            point = QPointF(20, y)
            event = QMouseEvent(
                kind,
                point,
                QPointF(first.mapToGlobal(point.toPoint())),
                Qt.LeftButton,
                buttons,
                Qt.NoModifier,
            )
            QApplication.sendEvent(first, event)

        send(QEvent.MouseButtonPress, 20, Qt.LeftButton)
        send(QEvent.MouseMove, 30, Qt.LeftButton)
        send(QEvent.MouseMove, 20 + second.y() - start[0], Qt.LeftButton)
        from PySide6.QtTest import QTest

        QTest.qWait(300)
        self.assertGreater(first.y(), start[0])  # held under the mouse
        self.assertEqual(start[0], second.y())  # slid up into the free place
        self.assertIsNone(self.saved().edited.get(1))  # nothing saved mid-drag

    def test_not_adjusting_shows_only_order_cells_and_summons(self):
        # Leo 2026-10-06: 不调整 hides the characters' skills and 爆发.
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        from src.tasks.fiend_hunt.chart import build_chart
        from src.tasks.fiend_hunt.saves import edit_turn, load_save
        from src.ui.shell.fiend_chart import ChartView, OrderRow, UnitEditor

        record = load_save(self.folder)
        view = ChartView(
            build_chart(record, self.folder, lambda _path: None),
            lambda name: name == "马莫尼勒",  # as if the only summon
            record=record,
            save=lambda state, changed: edit_turn(self.folder, state, changed),
        )
        view.resize(1100, 700)
        view.show()
        rows = [r for r in view.findChildren(OrderRow) if r.isVisibleTo(view)]
        glacia = next(r for r in rows if r.unit.name == "克蕾西亚")
        QTest.mouseClick(glacia, Qt.LeftButton, pos=QPoint(40, 20))
        QTest.qWait(20)
        self.assertFalse([e for e in view.findChildren(UnitEditor) if e.isVisibleTo(view)])
        self.assertFalse(glacia.show_card)
        view._edit(1, "克蕾西亚", "move_to", 2)  # marked as changed in the save
        QTest.qWait(20)
        rows = [r for r in view.findChildren(OrderRow) if r.isVisibleTo(view)]
        self.assertFalse(any(r.edited for r in rows))  # no 「已改」 in this mode
        texts = [
            w.text() for w in view.findChildren(QWidget) if hasattr(w, "text") and callable(w.text)
        ]
        self.assertIn("召唤物每回合", texts)

    def test_a_card_in_the_table_opens_a_small_window_to_change_it(self):
        # Leo 2026-10-06: every turn's card can be changed, not only at the top.
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        from src.ui.shell.fiend_chart import ActionCell, CardChip

        view = self.view()
        view.resize(1100, 900)
        view.show()
        cell = next(
            c for c in view.findChildren(ActionCell) if c.unit and c.unit.name == "马莫尼勒"
        )
        QTest.mouseClick(cell, Qt.LeftButton, pos=QPoint(40, 40))
        popup = view.popup
        self.assertTrue(popup.isVisible())
        attack = next(c for c in popup.findChildren(CardChip) if c._text == "攻击")
        attack.click()
        QTest.qWait(20)
        saved = self.saved().turns[1]
        self.assertEqual("攻击", saved.skills["马莫尼勒"])
        self.assertTrue(popup.isVisible())  # stays open for the next pick
        chosen = [c._text for c in popup.editor.findChildren(CardChip) if c.chosen]
        self.assertEqual(["攻击"], chosen)
        popup.close()
        QTest.qWait(20)

    def test_each_team_in_the_table_folds_away(self):
        # Leo 2026-10-06: a small arrow per team; a rebuild keeps it folded.
        view = self.view()
        view.show()
        view._timelines.toggle(1)
        self.assertFalse(view._timelines.tables[1].isVisibleTo(view))
        view._redraw(1)
        self.assertFalse(view._timelines.tables[1].isVisibleTo(view))
        self.assertEqual({1}, view.folded)

    def test_a_summon_has_only_attack_and_one_skill_without_burst(self):
        # Leo 2026-10-06: 魔法增幅器 has 普攻 and 技能1, no 爆发.
        from src.tasks.fiend_hunt.chart import ChartUnit
        from src.ui.shell.fiend_chart import CardChip, UnitEditor
        from src.ui.shell.widgets import Segmented

        unit = ChartUnit("魔法增幅器ET001", 0, (1, 1), "技能1")
        picks = []
        editor = UnitEditor(unit, lambda *change: picks.append(change))
        chips = editor.findChildren(CardChip)
        self.assertEqual(["攻击", "技能1"], [c._text for c in chips])
        self.assertTrue(chips[1].chosen)
        self.assertFalse(chips[1]._pixmap.isNull())  # the summon's own picture
        self.assertEqual([], editor.findChildren(Segmented))
        chips[0].click()
        self.assertEqual([("魔法增幅器ET001", "card", "攻击")], picks)

    def test_a_short_press_still_opens_the_editor(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        from src.ui.shell.fiend_chart import UnitEditor

        view = self.view()
        view.resize(1100, 700)
        view.show()
        QTest.mouseClick(self.rows(view)[1], Qt.LeftButton, pos=QPoint(40, 20))
        QTest.qWait(20)
        self.assertEqual(1, len([e for e in view.findChildren(UnitEditor) if e.isVisibleTo(view)]))
        self.assertIsNone(self.saved().edited.get(1))

    def test_dragging_on_the_grid_swaps_two_units(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest

        from src.ui.shell.fiend_chart import CELL, GAP, Grid

        view = self.view()
        view.resize(1100, 700)
        view.show()
        self.app.processEvents()
        grid = view.findChild(Grid)

        def centre(row, col):
            return QPoint(col * (CELL + GAP) + CELL // 2, row * (CELL + GAP) + CELL // 2)

        self.drag(grid, centre(2, 0), centre(2, 1))  # 克蕾西亚 onto 艾尼尔
        QTest.qWait(20)
        cells = self.saved().turns[1].cells
        self.assertEqual((2, 1), cells["克蕾西亚"])
        self.assertEqual((2, 0), cells["艾尼尔"])
        grid = view.findChild(Grid)
        self.drag(grid, centre(1, 3), centre(0, 0))  # 马莫尼勒 to an empty cell
        QTest.qWait(20)
        self.assertEqual((0, 0), self.saved().turns[1].cells["马莫尼勒"])
        self.assertIsNone(self.saved().edited.get(1))  # no card to check by label

    def test_a_rebuilt_chart_keeps_the_turn_and_open_unit(self):
        from src.tasks.fiend_hunt.chart import build_chart
        from src.tasks.fiend_hunt.saves import load_save
        from src.ui.shell.fiend_chart import ChartView, UnitEditor

        record = load_save(self.folder)
        turns = build_chart(record, self.folder, lambda _path: None)
        view = ChartView(turns, record=record, save=lambda *_: None, shown=1, opened="艾尼尔")
        self.assertEqual(1, view.shown)
        self.assertEqual("艾尼尔", view.opened)
        self.assertEqual(1, len(view.findChildren(UnitEditor)))

    def editor(self, view, name):
        from PySide6.QtTest import QTest

        from src.ui.shell.fiend_chart import UnitEditor

        view._toggle(name)

        def shown():
            return [e for e in view.findChildren(UnitEditor) if e.isVisibleTo(view)]

        # the turn is rebuilt once the click returns, and shown after that
        for _ in range(50):
            if len(shown()) == 1:
                break
            QTest.qWait(20)
        editors = shown()
        self.assertEqual(1, len(editors))
        return editors[0]

    def test_the_editor_has_no_arrows(self):
        from src.ui.shell.widgets import Button

        view = self.view()
        view.show()
        editor = self.editor(view, "克蕾西亚")
        icons = {b._icon_name for b in editor.findChildren(Button)}
        self.assertFalse(icons & {"chevron-up", "chevron-down"})

    def test_skills_are_picked_by_costume_picture(self):
        # Leo 2026-10-06: not 技能1/2/3 but the costume's portrait.
        from PySide6.QtTest import QTest

        from src.ui.shell.fiend_chart import CardChip

        view = self.view()
        view.show()
        chips = self.editor(view, "克蕾西亚").findChildren(CardChip)
        captions = [chip.toolTip().split("\n")[0] for chip in chips]
        wardrobe = [c.name for c in costumes.book().costumes("克蕾西亚")]  # souseha's wording
        self.assertEqual(["攻击", "击退", *wardrobe], captions)
        chips[3].click()
        state = self.saved().turns[1]
        QTest.qWait(20)
        self.assertEqual("Glacia_2", state.costumes["克蕾西亚"])
        self.assertEqual("技能", state.skills["克蕾西亚"])  # its row is found in the game
        self.assertEqual({1: frozenset({"克蕾西亚"})}, self.saved().edited)

    def test_a_costume_seen_while_recording_keeps_its_card(self):
        from src.tasks.fiend_hunt.record import save_record
        from src.tasks.fiend_hunt.saves import load_save

        record = load_save(self.folder)
        record.cards["克蕾西亚"] = {"技能3": "Glacia_2"}
        save_record(record, self.folder / "record.json")
        view = self.view()
        view._edit(1, "克蕾西亚", "costume", "Glacia_2")
        self.assertEqual("技能3", self.saved().turns[1].skills["克蕾西亚"])

    def test_attack_drops_the_costume(self):
        view = self.view()
        view._edit(1, "马莫尼勒", "costume", "Mamonir_2")
        view._edit(1, "马莫尼勒", "card", "攻击")
        state = self.saved().turns[1]
        self.assertNotIn("马莫尼勒", state.costumes)
        self.assertEqual("攻击", state.skills["马莫尼勒"])
