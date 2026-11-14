"""跑商 page: the 招募书 / 史莱姆 rows, 额外料理 and the calendar (Leo 2026-11-10)."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QApplication

from src.tasks.map_trade import asset_keep, sale_days
from src.tasks.map_trade.models import EXTRA_COOKING_RECIPES
from src.ui.shell import data, trade
from src.ui.shell.trade_assets import BalancedFlow, KeepBox, StepRow, hold

BEFORE = date(2026, 11, 10)  # the old table, the new one waits for 11/19
AFTER = date(2026, 11, 19)


def _task(**config):
    return SimpleNamespace(
        name=trade.TASK_NAME,
        config={"买": True, "卖": True, "制作料理": True, **config},
        config_type={
            "料理清单": {"options": ["香草牛排", "冰镇甜点", trade.LAST_DISH]},
            "5星料理": {"options": ["闪闪铁板虾"]},
            "额外料理": {"options": list(EXTRA_COOKING_RECIPES)},
        },
        config_description={},
    )


class TradePageAssetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def page(self, today=BEFORE, **config):
        task = _task(**config)
        for target, name, value in (
            (trade.TradePage, "task", lambda _self: task),
            (data, "sale_date", lambda now=None: today),
            (data, "current_task", lambda: None),
            (data, "done_today", lambda _name: False),
            (data, "trade_phases_done", lambda: {}),
            (trade.TradePage, "_refresh_bargain", lambda _self: None),
            (trade.actions, "can_start", lambda: True),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        page = trade.TradePage()
        self.addCleanup(page.deleteLater)
        page.refresh()
        return page, task

    # ------------------------------------------------------------ the boxes

    def test_nothing_is_filled_in_and_empty_means_not_sold(self):
        page, task = self.page(
            **{asset_keep.SELL_SLIMES_KEY: True, asset_keep.SELL_CONTRACTS_KEY: True}
        )
        self.assertEqual("", page.contract_box.text())
        self.assertTrue(all(box.text() == "" for box in page.slime_boxes.values()))
        self.assertEqual("还没填，不会卖", page.slime_block.state.full_text())
        self.assertEqual("还没填，不会卖", page.contract_block.state.full_text())
        self.assertEqual({}, data.asset_sale_days(task.config))

    def test_typing_saves_what_the_box_shows(self):
        page, task = self.page(**{asset_keep.SELL_SLIMES_KEY: True})
        box = page.slime_boxes["黄色史莱姆保留"]
        box.edit.setText("20000")
        box.edit.textEdited.emit("20000")
        self.assertEqual("20000", task.config["黄色史莱姆保留"])
        self.assertEqual(20000, asset_keep.parse_keep(task.config["黄色史莱姆保留"]))
        self.assertEqual("每月 10 号卖，各留这么多", page.slime_block.state.full_text())
        # Letters never get in.
        box.edit.setText("2a0")
        box.edit.textEdited.emit("2a0")
        self.assertEqual("20", task.config["黄色史莱姆保留"])

    def test_a_zero_is_warned_about(self):
        page, task = self.page(**{asset_keep.SELL_SLIMES_KEY: True})
        page.show()
        self.addCleanup(page.hide)
        box = page.slime_boxes["红色史莱姆保留"]
        box.edit.setText("0")
        box.edit.textEdited.emit("0")
        self.assertTrue(box.is_zero())
        self.assertEqual("填 0 会全卖", page.slime_block.state.full_text())
        self.assertIsNone(page.zero_note.anchor())
        box.settled.emit()  # typing paused
        self.assertIs(box, page.zero_note.anchor())
        self.assertIn("填 0 代表全卖", page.zero_note.TEXT)
        # Typing a real number takes the warning away again.
        box.edit.setText("05")
        box.edit.textEdited.emit("05")
        self.assertEqual(0.0, page.zero_note._fade.target)  # fading out
        self.assertEqual("05", task.config["红色史莱姆保留"])
        self.assertEqual(5, asset_keep.parse_keep(task.config["红色史莱姆保留"]))

    def test_the_warning_stays_inside_the_sell_card(self):
        # Live 2560x1440 2026-11-10: under the red slime box (the last one) it
        # stuck 12 px out of the 卖 card's right edge.
        from src.ui.shell.widgets import SHADOW_MARGINS

        page, _task = self.page(**{asset_keep.SELL_SLIMES_KEY: True})
        for width in (1100, 1600, 2300):
            with self.subTest(width=width):
                page.resize(width, 900)
                page.show()
                self.addCleanup(page.hide)
                QApplication.processEvents()
                box = page.slime_boxes["红色史莱姆保留"]
                box.edit.setText("0")
                box.edit.textEdited.emit("0")
                box.settled.emit()
                note = page.zero_note.geometry()
                card = page.sell_card
                left = card.mapTo(page.view, card.rect().topLeft()).x() + SHADOW_MARGINS[0]
                right = left + card.width() - SHADOW_MARGINS[0] - SHADOW_MARGINS[2]
                self.assertGreaterEqual(note.left(), left)
                self.assertLessEqual(note.right() + 1, right)

    def test_contract_box_steps_from_empty_and_warns_at_zero(self):
        page, task = self.page(**{asset_keep.SELL_CONTRACTS_KEY: True})
        page.show()
        self.addCleanup(page.hide)
        box = page.contract_box
        box._nudge(1)
        self.assertEqual("1", task.config[asset_keep.CONTRACT_KEEP_KEY])
        box._nudge(-1)
        self.assertEqual("0", task.config[asset_keep.CONTRACT_KEEP_KEY])
        self.assertIs(box, page.zero_note.anchor())
        box._nudge(-1)
        self.assertEqual("0", box.text())
        self.assertEqual("填 0 会全卖", page.contract_block.state.full_text())

    def test_the_contract_row_carries_the_hint(self):
        page, _task = self.page()
        self.assertIn("工具会自动计算招募书数量进行贩售", page.contract_block.info.toolTip())

    def test_switches_save_and_hide_the_boxes(self):
        page, task = self.page()
        self.assertFalse(page.slime_block.is_on())
        self.assertFalse(page.slime_block.controls.isVisibleTo(page.slime_block))
        self.assertEqual("不卖", page.slime_block.state.full_text())
        page.slime_block.toggle.click()
        self.assertTrue(task.config[asset_keep.SELL_SLIMES_KEY])
        page.contract_block.toggle.click()
        self.assertTrue(task.config[asset_keep.SELL_CONTRACTS_KEY])
        page.contract_block.toggle.click()
        self.assertFalse(task.config[asset_keep.SELL_CONTRACTS_KEY])

    def test_a_switched_off_row_shows_its_pictures_beside_the_switch(self):
        # Leo 2026-11-14: off, the row still shows what it sells; on, the
        # pictures give way to the boxes.
        page, _task = self.page()
        page.resize(1500, 900)
        page.show()
        self.addCleanup(page.hide)
        self.app.processEvents()
        for block, count in ((page.contract_block, 3), (page.slime_block, 3)):
            pile = block.pile
            self.assertEqual(count, len(pile._pixmaps))
            self.assertTrue(pile.isVisibleTo(block))
            self.assertEqual(1.0, pile.fade)
            gap = block.toggle.geometry().left() - pile.geometry().right()
            self.assertTrue(0 < gap <= 14, gap)
            head = block.state.parentWidget()
            self.assertLess(head.geometry().right(), pile.geometry().left())
            block.set_on(True)
            self.assertFalse(pile.isVisibleTo(block))
            self.assertTrue(block.controls.isVisibleTo(block))
            block.set_on(False)
            self.assertTrue(pile.isVisibleTo(block))
            self.assertFalse(block.controls.isVisibleTo(block))

    # ------------------------------------------------------------ calendar

    def test_set_up_assets_are_on_the_calendar_and_in_today(self):
        page, task = self.page(
            **{
                asset_keep.SELL_SLIMES_KEY: True,
                "黄色史莱姆保留": "20000",
                "红色史莱姆保留": "0",
                asset_keep.SELL_CONTRACTS_KEY: True,
                asset_keep.CONTRACT_KEEP_KEY: "3",
            }
        )
        self.assertEqual(["黄色史莱姆", "红色史莱姆"], page._cells[10].items[-2:])
        self.assertEqual(asset_keep.CONTRACTS_NAME, page._cells[1].items[-1])
        self.assertNotIn("蓝色史莱姆", page._cells[10].items)  # not filled in: not sold
        bundled = len(sale_days.bundled_sale_days(BEFORE).get(10, ()))
        self.assertEqual(f"今天卖 {bundled + 2} 件", page.sell_title.full_text())
        # Switched off again: gone from the calendar.
        page.slime_block.toggle.click()
        self.assertNotIn("黄色史莱姆", page._cells[10].items)
        self.assertEqual(f"今天卖 {bundled} 件", page.sell_title.full_text())

    def test_dates_after_the_change_show_the_new_table_and_wait(self):
        page, task = self.page()
        old = sale_days._table_days(sale_days.OLD_TABLE)
        new = sale_days._table_days(sale_days.NEXT_TABLE)
        self.assertEqual(sale_days.day_items(old[17]), page._cells[17].items)
        self.assertEqual(sale_days.day_items(new[24]), page._cells[24].items)
        self.assertNotEqual(sale_days.day_items(old[24]), page._cells[24].items)
        self.assertFalse(page.cal_change.isHidden())
        page._pick_day(25)
        self.assertIn("巧克力面包", page._panel_checks)
        self.assertTrue(page._panel_checks["巧克力面包"].isChecked())  # new goods start ticked
        self.assertFalse(page._panel_checks["巧克力面包"].isEnabled())
        before = dict(task.config)
        page._tick_item(25, "巧克力面包", False)
        self.assertEqual(before, task.config)

    def test_once_changed_the_whole_month_is_the_new_table(self):
        page, _task = self.page(today=AFTER)
        new = sale_days._table_days(sale_days.NEXT_TABLE)
        self.assertEqual(sale_days.day_items(new[2]), page._cells[2].items)
        self.assertTrue(page.cal_change.isHidden())
        self.assertEqual("最后才做", page.extra_note.full_text())

    # ------------------------------------------------------------ dishes

    def test_extra_dishes_toggle_and_say_when_they_start(self):
        page, task = self.page(**{"额外料理": list(EXTRA_COOKING_RECIPES)})
        self.assertEqual(list(EXTRA_COOKING_RECIPES), list(page.extra))
        self.assertEqual("11/19 改版后才做", page.extra_note.full_text())
        page.extra["土豆汤"].clicked.emit()
        self.assertNotIn("土豆汤", task.config["额外料理"])
        self.assertEqual(5, len(task.config["额外料理"]))


class TradeLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ten_tiles_split_evenly(self):
        box, flow = hold(BalancedFlow, 6)
        self.addCleanup(box.deleteLater)
        from PySide6.QtWidgets import QWidget

        for _ in range(10):
            tile = QWidget()
            tile.setFixedSize(52, 52)
            flow.addWidget(tile)
        self.assertEqual(10, flow.per_row(flow.row_width()))
        self.assertEqual(5, flow.per_row(flow.row_width() - 1))
        self.assertEqual(5, flow.per_row(7 * 58))  # never 7 + 3
        self.assertEqual(4, flow.per_row(4 * 58))

    def test_cards_share_one_height_or_stack(self):
        box, row = hold(StepRow)
        self.addCleanup(box.deleteLater)
        from PySide6.QtWidgets import QWidget

        cards = []
        for height in (100, 240, 180):
            card = QWidget()
            card.setMinimumHeight(height)
            row.addWidget(card)
            cards.append(card)
        box.resize(1040, row.heightForWidth(1040))
        row.setGeometry(box.rect())
        self.assertEqual({240}, {card.height() for card in cards})
        self.assertEqual(1040, cards[-1].geometry().right() + 1)
        self.assertLess(cards[0].width(), cards[2].width())
        self.assertIsNone(row.widths(600))
        self.assertEqual(100 + 240 + 180 + 2 * 14, row.heightForWidth(600))

    def test_keep_box_keeps_only_digits(self):
        box = KeepBox(digits=7)
        self.addCleanup(box.deleteLater)
        box.set_text("12,345")
        self.assertEqual("12345", box.text())
        box.set_text("")
        self.assertEqual("", box.text())
        self.assertFalse(box.is_zero())
        box.set_text("000")
        self.assertTrue(box.is_zero())


class AssetCalendarRulesTest(unittest.TestCase):
    def test_only_switched_on_and_filled_assets_are_listed(self):
        self.assertEqual({}, asset_keep.asset_sale_days({}))
        self.assertEqual(
            {},
            asset_keep.asset_sale_days({"黄色史莱姆保留": "5", asset_keep.CONTRACT_KEEP_KEY: "1"}),
        )
        days = asset_keep.asset_sale_days(
            {
                asset_keep.SELL_SLIMES_KEY: True,
                "蓝色史莱姆保留": "0",
                asset_keep.SELL_CONTRACTS_KEY: True,
                asset_keep.CONTRACT_KEEP_KEY: "2",
            }
        )
        self.assertEqual([asset_keep.AssetLine("蓝色史莱姆", 0)], days[asset_keep.SLIME_SALE_DAY])
        self.assertEqual(
            [asset_keep.AssetLine(asset_keep.CONTRACTS_NAME, 2, recruits=True)],
            days[asset_keep.CONTRACT_SALE_DAY],
        )

    def test_month_view_and_the_ticks_that_wait(self):
        days, change = sale_days.month_sale_days(BEFORE)
        self.assertEqual(sale_days.NEXT_CALENDAR_FROM, change)
        self.assertIn("巧克力面包", sale_days.day_items(days[25]))  # from 11/19: the new table
        self.assertIn("土豆", sale_days.day_items(days[17]))  # before it: still the old one
        days, change = sale_days.month_sale_days(AFTER)
        self.assertIsNone(change)
        self.assertEqual(sale_days._table_days(sale_days.NEXT_TABLE), days)
        self.assertEqual(
            (sale_days._table_days(sale_days.OLD_TABLE), None),
            sale_days.month_sale_days(date(2026, 10, 30)),
        )

    def test_ticks_after_change_match_the_real_carry_over(self):
        old = sale_days._table_days(sale_days.OLD_TABLE)
        for day in (17, 24, 25):
            kept = sale_days.day_items(old.get(day, ()))[:1]
            config = {sale_days.sale_day_key(day): list(kept)}
            expected = sale_days.ticks_after_change(config, day)
            sale_days.carry_checklists_over(config, AFTER)
            self.assertEqual(config[sale_days.sale_day_key(day)], expected, day)


if __name__ == "__main__":
    unittest.main()
