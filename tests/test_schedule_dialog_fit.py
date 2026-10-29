"""The 定时启动 window as it really opens: nothing squashed or cut.

Leo's v0.2.7 (2026-10-22, 繁中, 2560x1440): the slot rows were squashed to
half their height and their text overlapped, and the time wheel sat crooked.
These open the real window with slots in all 5 languages, light and dark,
and look at every widget inside it, without placing it by hand first.
"""

import gettext
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from src.ui.traditional import to_traditional
from src.utils import scheduled_start as ss
from src.utils.scheduled_start import Settings, Slot
from tests.ui_fit_audit import problems

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("zh_CN", "zh_TW", "en_US", "ja_JP", "ko_KR")


def _translator(language: str):
    if language == "zh_CN":
        return lambda text: text
    if language == "zh_TW":
        return to_traditional
    # The compiled catalog the tool ships (polib is not a project dependency).
    with (ROOT / "i18n" / language / "LC_MESSAGES" / "ok.mo").open("rb") as file:
        return gettext.GNUTranslations(file).gettext


def _slots(count: int) -> list[Slot]:
    # Quarters, an hour or more apart: slots that can be saved.
    # (2 + 5 + 7 blocks for the first three.)
    slots = [
        Slot(hour=8, minute=15, days=[5, 6]),
        Slot(hour=21, days=[0, 1, 2, 3, 4]),
    ]
    slots += [Slot(hour=hour, minute=30) for hour in (10, 12, 14)]
    return slots[:count]


class ScheduleDialogFitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from src.ui.quest_theme import apply_app_font

        apply_app_font()

    def setUp(self):
        from ok import og

        from src.ui.shell import data, schedule_ui, theme

        self.ui = schedule_ui
        self.theme = theme
        batch = SimpleNamespace(
            name=data.DAILY_BATCH, child_tasks=[], config={}, info={}, batch_label="一键完成日常"
        )
        patches = [
            mock.patch.object(data, "task_by_name", lambda name: batch),
            mock.patch.object(schedule_ui, "problem", ""),
            mock.patch.object(og, "app", SimpleNamespace(tr=lambda text: text), create=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(theme.set_theme_mode, theme.theme_mode())

    def _two_accounts(self):
        from src.utils import accounts

        known = [accounts.Account("1", "", ""), accounts.Account("2", "", "")]
        for patch in (
            mock.patch.object(accounts, "accounts", lambda: known),
            mock.patch.object(accounts, "current", lambda: known[0]),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        return known

    def _open(self, slots: int = 3, size=(1100, 760)):
        host = QWidget()
        host.resize(*size)
        host.setStyleSheet(self.theme.style_sheet())
        host.show()
        self.addCleanup(host.close)
        with mock.patch.object(self.ui, "_settings", Settings(True, True, _slots(slots))):
            dialog = self.ui.ScheduleDialog(host)
        dialog.resize(*size)
        dialog.show()
        self.addCleanup(dialog.close)
        # As it opens for the player: the window places itself, nothing by hand.
        for _ in range(30):
            self.app.processEvents()
        dialog._open.go(1.0, animate=False)
        for _ in range(5):
            self.app.processEvents()
        return dialog

    def test_nothing_is_squashed_or_cut_in_any_language_or_look(self):
        from ok import og

        for language in LANGUAGES:
            for mode in ("light", "dark"):
                with self.subTest(language=language, mode=mode):
                    og.app.tr = _translator(language)
                    self.theme.set_theme_mode(mode)
                    dialog = self._open()
                    self.assertEqual([], problems(dialog.panel))
                    # One block per slot per day it runs.
                    self.assertEqual(2 + 5 + 7, len(dialog.week.blocks))
                    dialog.close()
        og.app.tr = lambda text: text

    def test_a_short_window_scrolls_the_hours_instead_of_squashing(self):
        dialog = self._open(slots=5, size=(1100, 420))
        self.assertLessEqual(dialog.panel.height(), 420 - dialog.MARGIN)
        self.assertLess(dialog.week.scroll.height(), dialog.week.body.height())
        self.assertEqual([], problems(dialog.panel))

    def test_a_click_on_an_hour_adds_a_slot_there(self):
        # Leo 2026-10-29 「點該時間也可以新增」.
        from src.ui.shell import schedule_week

        dialog = self._open(slots=1)
        with mock.patch.object(schedule_week.SlotEditor, "exec", lambda d: True):
            dialog.week.body._on_add(2, 18)
        added = dialog.working.slots[-1]
        self.assertEqual((18, 0, [2]), (added.hour, added.minute, added.days))
        self.assertEqual(2 + 1, len(dialog.week.blocks))

    def test_the_plus_adds_today_at_a_free_hour(self):
        from src.ui.shell import schedule_week

        dialog = self._open(slots=2)
        with mock.patch.object(schedule_week.SlotEditor, "exec", lambda d: True):
            dialog.add_button.click()
        added = dialog.working.slots[-1]
        self.assertEqual([ss.local_now().weekday()], added.days)
        self.assertEqual([""] * 3, ss.slot_problems(dialog.working.slots))

    def test_an_account_dropped_on_an_hour_asks_what_to_run(self):
        # Leo 2026-10-29 「上面帳號也要可以拖曳 到特定時間段」「從上面拖曳下來的
        # 時候就要選任務了」.
        from src.ui.shell import schedule_week

        self._two_accounts()
        dialog = self._open(slots=2)
        self.assertEqual(["1", "2"], [chip.account_id for chip in dialog.legend])

        asked = []

        def pick(picker):
            asked.append(picker)
            return True

        with (
            mock.patch.object(schedule_week.SlotEditor, "exec", side_effect=AssertionError),
            mock.patch.object(schedule_week.TaskPickDialog, "exec", pick),
        ):
            dialog.week.body._on_add(3, 18, account="2", dropped=True)
        added = dialog.working.slots[-1]
        self.assertEqual(("2", 18, [3]), (added.account, added.hour, added.days))
        self.assertEqual(1, len(asked))
        self.assertEqual(asked[0].tasks(), added.tasks)
        # 取消 there: nothing is added.
        with mock.patch.object(schedule_week.TaskPickDialog, "exec", lambda d: False):
            dialog.week.body._on_add(5, 10, account="2", dropped=True)
        self.assertEqual(3, len(dialog.working.slots))

    def test_a_card_is_not_dragged(self):
        # Leo 2026-10-29 「不要開放拖曳」「上面到下面可以托」: only the 帳號 above.
        from src.ui.shell import schedule_week

        self.assertNotIn("mouseMoveEvent", vars(schedule_week.SlotBlock))
        self.assertIn("mouseMoveEvent", vars(schedule_week.LegendChip))

    def test_a_window_gone_before_its_queued_place_raises_nothing(self):
        # 2K test 2026-10-29: 29 「Internal C++ object (SlotEditor) already
        # deleted」 errors from a place queued for the next pass.
        import sys

        import shiboken6

        from src.ui.shell import schedule_week

        dialog = self._open(slots=1)
        editor = schedule_week.SlotEditor(Slot(hour=9, days=[0]), [], [], dialog)
        editor._place_queued = False
        editor._queue_place()
        shiboken6.delete(editor)
        caught = []
        with mock.patch.object(sys, "excepthook", lambda *error: caught.append(error)):
            for _ in range(5):
                self.app.processEvents()
        self.assertEqual([], caught)

    def test_a_dropped_account_makes_no_throwaway_editor(self):
        from src.ui.shell import schedule_week

        self._two_accounts()
        dialog = self._open(slots=2)
        with (
            mock.patch.object(schedule_week, "SlotEditor", side_effect=AssertionError),
            mock.patch.object(schedule_week.TaskPickDialog, "exec", lambda d: True),
        ):
            dialog.week.body._on_add(3, 18, account="2", dropped=True)
        self.assertEqual(3, len(dialog.working.slots))

    def test_a_slot_added_with_a_click_keeps_its_own_items(self):
        # No 「照帳號勾選」 any more: the 帳號's ticks at that moment.
        from src.ui.shell import schedule_week

        dialog = self._open(slots=1)
        with mock.patch.object(schedule_week.SlotEditor, "exec", lambda d: True):
            dialog.week.body._on_add(2, 18)
        self.assertIsInstance(dialog.working.slots[-1].tasks, list)

    def test_an_account_dropped_too_close_opens_the_editor(self):
        from src.ui.shell import schedule_week

        self._two_accounts()
        dialog = self._open(slots=2)
        opened = []
        with mock.patch.object(
            schedule_week.SlotEditor, "exec", lambda d: opened.append(d.why_not())
        ):
            # 帳號 2 at 21:00 on Monday, where 帳號 1 (the current one) runs at 21:00.
            dialog.week.body._on_add(0, 21, account="2", dropped=True)
        self.assertEqual(1, len(opened))
        self.assertIn("半小时", opened[0])
        self.assertEqual(2, len(dialog.working.slots))

    def test_a_block_opens_the_editor_that_changes_or_deletes_it(self):
        from src.ui.shell import schedule_week

        dialog = self._open(slots=2)
        block = dialog.week.blocks[0]

        def change(editor):
            editor.hour.setCurrentIndex(7)
            return True

        with mock.patch.object(schedule_week.SlotEditor, "exec", change):
            block.click()
        self.assertEqual(7, dialog.working.slots[0].hour)

        def delete(editor):
            editor._delete()
            return True

        with mock.patch.object(schedule_week.SlotEditor, "exec", delete):
            dialog.week.blocks[0].click()
        self.assertEqual(1, len(dialog.working.slots))

    def test_a_paused_account_hides_its_slots_and_they_do_not_run(self):
        # Leo 2026-10-29 「點帳號可以讓該帳號變淺變深 變淺該帳號行程隱藏(失效)」.
        self._two_accounts()
        with mock.patch.object(
            self.ui,
            "_settings",
            Settings(
                True,
                True,
                [
                    Slot(hour=21, account="1"),
                    Slot(hour=8, days=[5], account="2"),
                ],
            ),
        ):
            dialog = self.ui.ScheduleDialog(None)
        self.addCleanup(dialog.close)
        self.assertEqual(8, len(dialog.week.blocks))
        dialog.legend[1].click()
        self.assertEqual(["2"], dialog.working.paused)
        self.assertEqual(7, len(dialog.week.blocks))
        with mock.patch.object(ss, "_current_account", lambda: "1"):
            self.assertEqual(["1"], [s.account for s in dialog.working.active_slots()])
        dialog.legend[1].click()
        self.assertEqual([], dialog.working.paused)

    def test_a_clash_marks_the_blocks_and_blocks_saving(self):
        dialog = self._open(slots=2)
        dialog.working.slots.append(Slot(hour=21, minute=30, days=[0]))
        dialog._fill()
        bad = [block for block in dialog.week.blocks if block.problem]
        self.assertEqual(2, len(bad))  # Monday 21:00 and Monday 21:30
        self.assertTrue(dialog.problem.isVisibleTo(dialog))
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertEqual([], problems(dialog.panel))

    def test_the_editor_fits_in_any_language_or_look(self):
        from ok import og

        from src.ui.shell import schedule_week

        known = self._two_accounts()
        self._items()
        for language in LANGUAGES:
            for mode in ("light", "dark"):
                with self.subTest(language=language, mode=mode):
                    og.app.tr = _translator(language)
                    self.theme.set_theme_mode(mode)
                    host = QWidget()
                    host.resize(1100, 760)
                    host.show()
                    editor = schedule_week.SlotEditor(Slot(hour=21, account="2"), [], known, host)
                    editor.resize(1100, 760)
                    editor.show()
                    for _ in range(30):
                        self.app.processEvents()
                    editor._open.go(1.0, animate=False)
                    self.app.processEvents()
                    self.assertEqual([], problems(editor.panel))
                    self.assertEqual([False, True], [pill.isChecked() for pill in editor.pills])
                    editor.close()
                    host.close()
        og.app.tr = lambda text: text

    def test_the_editor_says_why_it_cannot_be_kept(self):
        from src.ui.shell import schedule_week

        known = self._two_accounts()
        with (
            mock.patch.object(ss, "_current_account", lambda: "1"),
            mock.patch.object(schedule_week, "current_id", lambda: "1"),
        ):
            others = [Slot(hour=21, account="1")]
            editor = schedule_week.SlotEditor(
                Slot(hour=21, minute=30, account="1"), others, known, None
            )
            self.addCleanup(editor.close)
            self.assertIn("1 小时", editor.problem.text())
            self.assertFalse(editor.ok.isEnabled())
            editor._pick_account("2")
            self.assertEqual("", editor.why_not())
            self.assertTrue(editor.ok.isEnabled())
            for chip in editor.days:
                chip.setChecked(False)
            self.assertIn("星期", editor.problem.text())

    def test_one_account_shows_no_account_list(self):
        self._items()
        self.assertEqual([], self._pick(Slot(hour=21)).pills)

    def test_each_slot_picks_its_account(self):
        known = self._two_accounts()
        self._items()
        pick = self._pick(Slot(hour=21), known)
        # 当前账号, 账号 1, 账号 2, as pills (Leo 2026-10-29 「帳號那邊排的不好」).
        self.assertEqual(["", "1", "2"], [pill.account_id for pill in pick.pills])
        self.assertEqual([True, False, False], [pill.isChecked() for pill in pick.pills])
        self.assertEqual("", pick.account())
        pick.pills[2].click()
        self.assertEqual("2", pick.account())
        self.assertEqual([False, False, True], [pill.isChecked() for pill in pick.pills])
        pick.pills[0].click()
        self.assertEqual("", pick.account())

    def test_a_deleted_account_shows_as_the_current_one(self):
        known = self._two_accounts()
        self._items()
        pick = self._pick(Slot(hour=21, account="9"), known)
        self.assertTrue(pick.pills[0].isChecked())
        self.assertEqual("", pick.account())

    def _items(self):
        from src.ui.shell import data

        names = [
            "公会、小屋、酒馆",
            "快速狩猎",
            "白嫖抽抽乐",
            "广场女神像",
            "镜中之战",
            "每日跑商",
            "活动每日战斗",
            "救赎之塔",
            "亲密度谈心",
            "领取邮件",
            "每周跑图",
            "末日之书",
        ]
        items = [
            data.Child(name, None, name, name, "circle", "plain", index % 3 != 0)
            for index, name in enumerate(names)
        ]
        patch = mock.patch.object(self.ui, "_batch_items", lambda: items)
        patch.start()
        self.addCleanup(patch.stop)
        return items

    def _pick(self, slot, known=None):
        host = QWidget()
        host.resize(1100, 760)
        host.setStyleSheet(self.theme.style_sheet())
        host.show()
        self.addCleanup(host.close)
        dialog = self.ui.TaskPickDialog(slot, host, known)
        dialog.resize(1100, 760)
        dialog.show()
        self.addCleanup(dialog.close)
        for _ in range(30):
            self.app.processEvents()
        dialog._open.go(1.0, animate=False)
        for _ in range(5):
            self.app.processEvents()
        return dialog

    def test_the_task_window_fits_in_any_language_or_look(self):
        # Leo 2026-10-29 「跳出視窗 選擇」.
        from ok import og

        self._items()
        for language in LANGUAGES:
            for mode in ("light", "dark"):
                with self.subTest(language=language, mode=mode):
                    og.app.tr = _translator(language)
                    self.theme.set_theme_mode(mode)
                    dialog = self._pick(Slot(hour=21, tasks=["快速狩猎"]))
                    self.assertEqual([], problems(dialog.panel))
                    dialog.close()
        og.app.tr = lambda text: text

    def test_picking_the_tasks_of_a_slot(self):
        items = self._items()
        with mock.patch.object(self.ui.accounts, "current_id", lambda: "1"):
            dialog = self._pick(Slot(hour=21))
            # It starts as the 帳號's ticks, free to change (no 「照帳號勾選」).
            self.assertEqual([i.included for i in items], [b.isChecked() for b in dialog.boxes])
            self.assertTrue(all(box.isEnabled() for box in dialog.boxes))
            # The 全选 box on top ticks all, then clears all.
            dialog.every.setChecked(True)
            self.assertTrue(all(box.isChecked() for box in dialog.boxes))
            self.assertEqual([i.key for i in items], dialog.tasks())
            dialog.every.setChecked(False)
            self.assertFalse(dialog.ok.isEnabled())  # nothing ticked never runs anything
            dialog.boxes[1].setChecked(True)
            dialog.boxes[9].setChecked(True)
            self.assertTrue(dialog.ok.isEnabled())
            self.assertEqual(["快速狩猎", "领取邮件"], dialog.tasks())


class ItemSettingsTest(unittest.TestCase):
    """Leo 2026-10-29 「鏡中之戰也可以選倍數那些」: an item's settings for one
    slot, drawn as on its own page, never written to the item itself."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ok import og

        from src.ui.shell import schedule_ui

        self.ui = schedule_ui
        patch = mock.patch.object(og, "app", SimpleNamespace(tr=lambda text: text), create=True)
        patch.start()
        self.addCleanup(patch.stop)

        class Config(dict):
            def get_default(self, key):
                return {"自动战斗": True, "难度": "普通"}.get(key)

        class PVPTask:  # the stand-in keeps the class name: same panel as the page
            name = "镜中之战"
            config = Config({"启用": True, "自动战斗": True, "难度": "普通"})
            config_type = {"难度": {"type": "drop_down", "options": ["普通", "困难"]}}
            config_description = {}
            default_config = {"启用": True, "自动战斗": True, "难度": "普通"}

        self.task = PVPTask()
        self.item = SimpleNamespace(key="镜中之战", name="镜中之战", task=self.task)

    def test_only_the_slots_changes_are_kept(self):
        self.assertEqual(["自动战斗", "难度"], self.ui.item_setting_keys(self.task))
        dialog = self.ui.ItemSettingsDialog(self.item, {}, None)
        self.addCleanup(dialog.close)
        stand_in = dialog.task
        self.assertEqual("PVPTask", type(stand_in).__name__)
        stand_in.config["难度"] = "困难"
        stand_in.config["自动战斗"] = True  # the same as the item's own
        self.assertEqual({"难度": "困难"}, dialog.changed())
        self.assertEqual("普通", self.task.config["难度"])  # the item itself is untouched
        stand_in.config["难度"] = "普通"
        self.assertEqual({}, dialog.changed())

    def test_opens_with_the_slots_settings_and_goes_back(self):
        dialog = self.ui.ItemSettingsDialog(self.item, {"难度": "困难"}, None)
        self.addCleanup(dialog.close)
        self.assertEqual("困难", dialog.task.config["难度"])
        dialog._same_as_item()
        self.assertEqual({}, dialog.changed())
        self.assertEqual("普通", dialog.task.config["难度"])

    def test_items_without_settings_have_no_gear(self):
        self.assertEqual([], self.ui.item_setting_keys(None))
        bare = SimpleNamespace(config={"启用": True}, config_type={}, default_config={})
        self.assertEqual([], self.ui.item_setting_keys(bare))


class DefaultSlotsTest(unittest.TestCase):
    def test_a_new_install_has_no_slot(self):
        # Leo 2026-10-22 「預設的8:05不要」.
        self.assertEqual([], Settings().slots)
        self.assertEqual([], Settings.from_json({}).slots)
        self.assertIsNone(ss.next_run(Settings(enabled=True), ss.local_now()))


class ImportOrderTest(unittest.TestCase):
    """Either module can be imported first (a cycle broke schedule_week first)."""

    def test_both_orders(self):
        import subprocess
        import sys

        root = str(Path(__file__).resolve().parents[1])
        for first, second in (("schedule_week", "schedule_ui"), ("schedule_ui", "schedule_week")):
            code = (
                f"from src.ui.shell import {first}, {second}\n"
                "assert schedule_ui.ScheduleDialog is schedule_week.ScheduleDialog\n"
            )
            run = subprocess.run(
                [sys.executable, "-c", code],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(run.returncode, 0, run.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
