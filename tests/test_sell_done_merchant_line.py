"""跑商出售：卖成功却当成出错，又在清单里上下找已卖光的商品。

Player via Leo 2026-11-25 (v0.4.16, 简中): 巧克力面包 400 of 400 sold in the
game, yet the tool logged 「出错，已关闭弹窗，当场重试一次」 and searched the
sell list up and down for the bread, which no longer existed.

Two fixes, both without new screen words, tested on 简中 and 繁中 text:
1. The "page changed" cue reads only the item cards.  The shop keeper's line
   above the list names the item too (「这里好像正在收购巧克力面包」, real
   positions from the player frame sell_page_back_dead_player_1080_v046.jpg),
   and OCR cuts that line differently on every read (Leo's 4K log 11-22:
   「这里好像正在购 葡萄」 then 「这里好像正在购入 葡萄」), so two reads in a
   row never matched.
2. When a sale of everything owned was not confirmed but the dialog closed
   after 出售, the retry that finds no card with the name anywhere in the list
   counts the earlier press as sold, instead of switching cartridges and
   searching again and leaving the item for the next run.
"""

from __future__ import annotations

import itertools
import unittest
from types import SimpleNamespace

import numpy as np

from src.tasks.map_trade.calendar import CalendarEntry
from src.tasks.map_trade.trader import Trader

FRAME = np.zeros((1080, 1920, 3), dtype=np.uint8)

# 简中 / 繁中: the card name, the keeper's line cut two ways.
CLIENTS = {
    "简中": ("巧克力面包", "这里好像正在收购巧克力面包", "这里好像正在收购巧克力面包如果有多余的就卖掉吧"),
    "繁中": ("巧克力麵包", "這裡好像正在收購巧克力麵包", "這裡好像正在收購巧克力麵包如果有多餘的就賣掉吧"),
}


def _box(name, x, y, width, height):
    return SimpleNamespace(name=name, x=x, y=y, width=width, height=height)


def _card(name):
    # Where the player frame shows 巧克力面包 (x=1260, y=169) at 1080p.
    return _box(name, 1260, 169, 106, 26)


def _keeper(line, width):
    # Where the player frame shows 「这里好像正在收购哈密瓜」: above the list.
    return _box(line, 590, 85, width, 20)


def _entry():
    return CalendarEntry("巧克力面包", "S25", aliases=("巧克力麵包",))


def _trader(pages, logs):
    trader = object.__new__(Trader)
    trader._sale_title_catalog_cache = None
    trader._sale_title_entries = []
    trader.task = SimpleNamespace(
        sleep=lambda *_args: None,
        info_set=lambda *_args: None,
        log_info=logs.append,
        log_warning=lambda message, **_kw: logs.append(message),
    )
    # One page per captured frame, however often that frame is read.
    page_iter = iter(pages)
    last = [None]
    shown: dict[int, list] = {}

    def capture():
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        last[0] = next(page_iter, last[0])
        shown[id(frame)] = last[0]
        return frame

    def ocr_boxes(frame, label, **_kwargs):
        if label == "出售商品卡库存":
            return []
        return shown.get(id(frame), last[0] or [])

    trader.vision = SimpleNamespace(
        capture=capture,
        ocr_text=lambda _frame, _name, **_kwargs: "",
        simplify=lambda value: value,
        ocr_boxes=ocr_boxes,
    )
    return trader


class KeeperLineIsNotACardTest(unittest.TestCase):
    def test_signature_holds_the_card_and_not_the_keeper_line(self):
        for client, (card, short_line, long_line) in CLIENTS.items():
            with self.subTest(client=client):
                trader = _trader([[_keeper(short_line, 216), _card(card)]], [])
                signature = trader._sale_name_signature(_entry(), trader.vision.capture())
                self.assertEqual(1, len(signature))
                self.assertEqual(1260, signature[0][1])
                # The keeper's line cut another way changes nothing.
                trader = _trader([[_keeper(long_line, 420), _card(card)]], [])
                self.assertEqual(
                    signature, trader._sale_name_signature(_entry(), trader.vision.capture())
                )

    def test_sold_out_card_is_confirmed_while_the_keeper_line_flickers(self):
        """Fails before the fix: the jittering line kept the signature moving."""

        for client, (card, short_line, long_line) in CLIENTS.items():
            with self.subTest(client=client):
                before_page = [_keeper(short_line, 216), _card(card)]
                # The card is gone; the keeper's line keeps being cut two
                # ways, read after read, for as long as the wait lasts.
                after_pages = itertools.cycle(
                    [[_keeper(short_line, 216)], [_keeper(long_line, 420)]]
                )
                logs = []
                trader = _trader([before_page], logs)
                before = trader._sale_name_signature(_entry(), trader.vision.capture())
                trader = _trader(after_pages, logs)
                trader._last_sale_toast_id = None
                self.assertTrue(
                    trader._wait_sale_completion(
                        _entry(),
                        FRAME,
                        before,
                        timeout=0.5,
                        before_toast_id=None,
                        owned=400,
                        selected=400,
                        name_box=_card(card),
                    ),
                    logs,
                )
                self.assertTrue(trader._sale_dialog_closed_after_press)


def _retry_seller(scans, *, name_seen=False, ocr_output=True, dialog_closed=True):
    """First attempt: the sale of all 400 is pressed but not confirmed."""

    trader = object.__new__(Trader)
    logs, warnings, events, notes = [], [], [], []
    trader.task = SimpleNamespace(
        config={},
        sleep=lambda *_args: None,
        log_info=logs.append,
        log_warning=lambda message, **_kw: warnings.append(message),
        info_set=lambda *_args: None,
    )
    trader.trade_detail = SimpleNamespace(add_sale=lambda item, qty: notes.append((item, qty)))
    trader._start_sale_search = lambda _entry: events.append("start") or -1
    trader._candidate_unmoved = lambda _candidate, _frame: True
    trader._sale_dialog_shown = lambda *_args: False
    def reopen(_entry):  # once per cartridge visit, as the real one
        if "reopen" in events:
            return False
        events.append("reopen")
        return True

    trader._reopen_sale_cartridge = reopen

    def find(_entry, direction=-1, settled=False):
        located = scans.pop(0)
        trader._last_sale_name_seen = name_seen if located is None else True
        trader._last_sale_ocr_output = ocr_output
        trader._last_sale_unavailable = located is None and not name_seen and ocr_output
        trader._last_sale_reason = "全画面OCR未形成可用商品候选" if located is None else ""
        trader._last_sale_page_empty = located is None
        return located

    trader._find_sale_item_candidates = find

    def sell_one(entry, _candidate, _frame, *, previous_owned):
        events.append("pressed")
        # What _sell_one_candidate leaves when _wait_sale_completion fails.
        trader._sale_dialog_rejected = False
        trader._last_sale_cleared = True
        trader._sale_dialog_closed_after_press = dialog_closed
        trader._unconfirmed_sale = (entry.item, 400, 400)
        if dialog_closed:
            trader._unconfirmed_clear_all = (entry.item, 400)
        return None

    trader._sell_one_candidate = sell_one
    return trader, logs, warnings, events, notes


class SoldOutRetryTest(unittest.TestCase):
    def test_retry_that_finds_the_item_gone_counts_the_sale(self):
        candidate = SimpleNamespace(center=(1300, 182))
        trader, logs, warnings, events, notes = _retry_seller(
            [([candidate], FRAME), None]
        )

        self.assertTrue(trader._sell_entry_with_retry(_entry()))

        self.assertEqual([("巧克力面包", 400)], notes)
        # One search for it, no cartridge switch and no second search.
        self.assertEqual(["start", "pressed", "start"], events)
        self.assertTrue(any("按了出售但没确认到成交" in line for line in logs))
        self.assertFalse(any("已关闭弹窗" in line for line in logs))
        self.assertTrue(any("整个出售清单都找不到它了" in line for line in logs))
        self.assertEqual([], warnings)
        self.assertFalse(trader._last_sale_unavailable)

    def test_unread_list_is_no_proof_of_a_sale(self):
        candidate = SimpleNamespace(center=(1300, 182))
        trader, _logs, _warnings, events, notes = _retry_seller(
            [([candidate], FRAME), None, None], ocr_output=False
        )

        self.assertFalse(trader._sell_entry_with_retry(_entry()))
        self.assertEqual([], notes)

    def test_dialog_still_up_after_the_press_is_no_proof_either(self):
        candidate = SimpleNamespace(center=(1300, 182))
        trader, _logs, _warnings, events, notes = _retry_seller(
            [([candidate], FRAME), None, None], dialog_closed=False
        )

        self.assertFalse(trader._sell_entry_with_retry(_entry()))
        self.assertEqual([], notes)
        self.assertIn("reopen", events)  # the usual search goes on
        self.assertTrue(trader._last_sale_unavailable)

    def test_name_still_on_the_list_is_not_counted_as_gone(self):
        candidate = SimpleNamespace(center=(1300, 182))
        trader, _logs, _warnings, _events, notes = _retry_seller(
            [([candidate], FRAME), None], name_seen=True
        )

        self.assertFalse(trader._sell_entry_with_retry(_entry()))
        self.assertEqual([], notes)


if __name__ == "__main__":
    unittest.main()
