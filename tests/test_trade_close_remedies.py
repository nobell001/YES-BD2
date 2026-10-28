"""跑商: the steps that gave up after one press now follow the shared recovery
order (docs/dev-notes/bug-prevention.md): the press once more while the screen
from before still shows, then the game's key, and only then the failure.

- 价目表: ✕ dropped, selling went on under the list (only 「价目表关闭失败」 was
  logged);
- the sale dialog: ✕ dropped, the day's selling stopped
  (「出售弹窗无法关闭，停止出售」);
- 料理: 返回 pressed twice on a page that stayed (YES-BD2 #13, player v0.2.11
  2026-10-24), then nothing;
- the merchant menu: his prompt pressed and the menu never opened (another
  player's name can sit over his prompt, live 1080p 2026-10-20).

Each remedy runs only while the screen from before the press is still read,
so no press lands on the page under it.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.tasks.map_trade.models import CalendarEntry, NavigationResult, ScreenState


class _Clock:
    """Half a second per look, so every wait ends at once."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.5
        return self.now


def _patch_clock(test, module):
    patcher = mock.patch(f"src.tasks.map_trade.{module}.monotonic", _Clock())
    patcher.start()
    test.addCleanup(patcher.stop)


# 价目表 --------------------------------------------------------------------


class _PriceList:
    """The 价目表 over the sell page; each ✕ closes it or is dropped."""

    def __init__(self, closes=(True,), esc_closes=True, esc_leaves_shop=False):
        self.closes = list(closes)
        self.esc_closes = esc_closes
        self.esc_leaves_shop = esc_leaves_shop
        self.open = True
        self.in_shop = True
        self.presses = []

    def close(self):
        self.presses.append("✕")
        if self.closes.pop(0) if self.closes else False:
            self.open = False

    def escape(self):
        self.presses.append("Esc")
        if self.esc_closes:
            self.open = False
            self.in_shop = not self.esc_leaves_shop
        return True


BUTTON = SimpleNamespace(name="价目表", x=1400, y=990, width=80, height=30)


def _price_reader(screen, *, esc=True):
    from src.tasks.map_trade.trader_price_list import PriceListMixin

    reader = object.__new__(PriceListMixin)
    logs = []
    task = SimpleNamespace(
        operate_click=lambda *_a, **_k: screen.close(),
        sleep=lambda *_a: None,
        log_info=logs.append,
        log_warning=logs.append,
    )
    if esc:
        task.tap_escape = lambda after_sleep=0.0: screen.escape()
    reader.task = task
    reader._ref_point = lambda x, y: (x, y)
    reader._price_list_open = lambda: screen.open
    reader._price_list_button = lambda: BUTTON if screen.in_shop else None
    return reader, logs


class PriceListCloseTest(unittest.TestCase):
    def setUp(self):
        _patch_clock(self, "trader_price_list")

    def test_a_close_that_works_is_pressed_once(self):
        screen = _PriceList(closes=(True,))
        reader, _logs = _price_reader(screen)
        self.assertTrue(reader._close_price_list())
        self.assertEqual(["✕"], screen.presses)

    def test_a_dropped_close_is_pressed_again(self):
        screen = _PriceList(closes=(False, True))
        reader, _logs = _price_reader(screen)
        self.assertTrue(reader._close_price_list())
        self.assertEqual(["✕", "✕"], screen.presses)

    def test_esc_after_two_dropped_closes(self):
        screen = _PriceList(closes=(False, False))
        reader, logs = _price_reader(screen)
        self.assertTrue(reader._close_price_list())
        self.assertEqual(["✕", "✕", "Esc"], screen.presses)
        self.assertIn("卖：价目表按了两次✕还开着，改按 Esc。", logs)

    def test_esc_that_left_the_shop_too_is_not_a_success(self):
        # The next presses are on the sell list: they must not run elsewhere.
        screen = _PriceList(closes=(False, False), esc_leaves_shop=True)
        reader, _logs = _price_reader(screen)
        self.assertFalse(reader._close_price_list())

    def test_nothing_more_after_esc(self):
        screen = _PriceList(closes=(False, False), esc_closes=False)
        reader, _logs = _price_reader(screen)
        self.assertFalse(reader._close_price_list())
        self.assertEqual(["✕", "✕", "Esc"], screen.presses)

    def test_no_esc_without_the_key(self):
        screen = _PriceList(closes=(False, False))
        reader, _logs = _price_reader(screen, esc=False)
        self.assertFalse(reader._close_price_list())
        self.assertEqual(["✕", "✕"], screen.presses)

    def test_a_list_left_open_stops_the_sale(self):
        from src.tasks.map_trade.trader_price_list import PriceListMixin

        reader = object.__new__(PriceListMixin)
        logs = []
        reader.task = SimpleNamespace(log_info=logs.append, log_warning=logs.append)
        reader._status = lambda *_a: None
        reader._open_price_list = lambda: True
        reader._ticked_within = lambda _seconds: True
        reader._settled_rows = lambda: [("苹果", True), ("红酒", False)]
        reader._close_price_list = lambda: False
        self.assertEqual({"苹果"}, reader.owned_items_at_max_rate())
        self.assertTrue(reader._price_list_left_open)
        self.assertIn("卖：价目表关不掉（按了✕和 Esc），这次先不卖，免得点到价目表上。", logs)

    def test_selling_does_not_go_on_under_the_list(self):
        from src.tasks.map_trade.trader import Trader

        trader = object.__new__(Trader)
        trader.task = SimpleNamespace(log_info=lambda *_a: None, log_warning=lambda *_a, **_k: None)
        trader._status = lambda *_a: None
        trader._buy_completed_in_current_shop = False
        entries = [CalendarEntry("苹果", "S6")]
        trader._resolve_sale_entries = lambda: entries
        trader.navigator = SimpleNamespace(
            enter_q_sp6_buy_flow=lambda bargain: NavigationResult(True, ScreenState.SHOP)
        )
        trader._ensure_sell_page = lambda: True

        def keep(found):
            trader._price_list_left_open = True
            return found

        trader._keep_owned_at_max_rate = keep
        trader.sell_max_price_items = lambda: self.fail("sold under the 价目表")
        self.assertFalse(trader.run_sell())


# The sale dialog -----------------------------------------------------------


class _SaleDialog:
    """The quantity dialog over the shop list; each ✕ closes it or is dropped."""

    def __init__(self, closes=(True,), esc_closes=True, esc_leaves_shop=False, after=""):
        self.closes = list(closes)
        self.esc_closes = esc_closes
        self.esc_leaves_shop = esc_leaves_shop
        # What the dialog's place reads once a dropped press left it unread.
        self.after = after
        self.shown = True
        self.unread = False
        self.in_shop = True
        self.presses = []

    def text(self, _frame=None):
        if self.unread:
            return ""
        if self.shown:
            return "拥有 400个 可购买 50 出售"
        return "火烤鱼板棒 食物" if self.in_shop else "洛兹 欢迎光临"

    def close(self):
        self.presses.append("✕")
        landed = self.closes.pop(0) if self.closes else False
        if landed == "unread":
            self.unread = True
        elif landed:
            self.shown = False

    def escape(self):
        self.presses.append("Esc")
        if self.esc_closes:
            self.shown = False
            self.in_shop = not self.esc_leaves_shop
        return True


def _sale_trader(screen, *, esc=True):
    from src.tasks.map_trade.trader_sell import SellFlowMixin

    trader = object.__new__(SellFlowMixin)
    logs = []
    task = SimpleNamespace(
        operate_click=lambda *_a, **_k: screen.close(),
        sleep=lambda *_a: None,
        log_info=logs.append,
        log_warning=lambda message, **_k: logs.append(message),
    )
    if esc:
        task.tap_escape = lambda after_sleep=0.0: screen.escape()
    trader.task = task
    trader.vision = SimpleNamespace(capture=lambda: None, simplify=lambda value: value)
    trader._sale_dialog_text = screen.text
    trader._shop_mode_title = lambda _frame: "出售" if screen.in_shop else "洛兹"
    return trader, logs


class SaleDialogCloseTest(unittest.TestCase):
    def setUp(self):
        _patch_clock(self, "trader_sell")

    def test_a_close_that_works_is_pressed_once(self):
        screen = _SaleDialog(closes=(True,))
        trader, _logs = _sale_trader(screen)
        self.assertTrue(trader._close_sale_dialog())
        self.assertEqual(["✕"], screen.presses)

    def test_a_dropped_close_is_pressed_again(self):
        screen = _SaleDialog(closes=(False, True))
        trader, _logs = _sale_trader(screen)
        self.assertTrue(trader._close_sale_dialog())
        self.assertEqual(["✕", "✕"], screen.presses)

    def test_esc_after_two_dropped_closes(self):
        screen = _SaleDialog(closes=(False, False))
        trader, logs = _sale_trader(screen)
        self.assertTrue(trader._close_sale_dialog())
        self.assertEqual(["✕", "✕", "Esc"], screen.presses)
        self.assertIn("卖：出售弹窗按了两次✕还在，改按 Esc。", logs)

    def test_esc_that_left_the_shop_too_is_not_a_success(self):
        screen = _SaleDialog(closes=(False, False), esc_leaves_shop=True)
        trader, logs = _sale_trader(screen)
        self.assertFalse(trader._close_sale_dialog())
        self.assertIn("卖：按 Esc 关掉出售弹窗后，没看到出售页的标题。", logs)

    def test_no_second_press_when_the_dialog_is_not_read(self):
        # Neither the dialog nor the shop reads: a press could land anywhere.
        screen = _SaleDialog(closes=("unread",))
        trader, _logs = _sale_trader(screen)
        self.assertFalse(trader._close_sale_dialog())
        self.assertEqual(["✕"], screen.presses)

    def test_nothing_more_after_esc(self):
        screen = _SaleDialog(closes=(False, False), esc_closes=False)
        trader, _logs = _sale_trader(screen)
        self.assertFalse(trader._close_sale_dialog())
        self.assertEqual(["✕", "✕", "Esc"], screen.presses)

    def test_no_esc_without_the_key(self):
        screen = _SaleDialog(closes=(False, False))
        trader, _logs = _sale_trader(screen, esc=False)
        self.assertFalse(trader._close_sale_dialog())
        self.assertEqual(["✕", "✕"], screen.presses)


# 料理 ----------------------------------------------------------------------


class _CookingPages:
    """The cooking detail page, its list and the field; 返回 and Esc each step
    back one page when the game takes them."""

    def __init__(self, page="detail", backs=(), esc_lands=True):
        self.page = page
        self.backs = list(backs)
        self.esc_lands = esc_lands
        self.presses = []

    def back(self, context):
        self.presses.append(context)
        if self.backs.pop(0) if self.backs else False:
            self._step_back()

    def escape(self):
        self.presses.append("Esc")
        if self.esc_lands:
            self._step_back()
        return True

    def _step_back(self):
        self.page = {"detail": "list", "list": "field"}.get(self.page, self.page)


def _cook_trader(screen, *, esc=True):
    import numpy as np

    from src.tasks.map_trade.trader import Trader
    from src.tasks.map_trade.trader_cooking import CookingDetailSnapshot

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    logs = []
    trader = object.__new__(Trader)
    task = SimpleNamespace(
        sleep=lambda *_a: None,
        log_info=logs.append,
        log_warning=lambda message, **_k: logs.append(message),
        info_set=lambda *_a: None,
    )
    if esc:
        task.tap_escape = lambda after_sleep=0.0: screen.escape()
    trader.task = task
    trader._status = lambda *_a: None
    trader._cooking_opened = True
    detail = CookingDetailSnapshot(frame, None, False, 0.0)
    listed = SimpleNamespace(frame="list")
    trader._wait_for_cooking_detail = lambda _r, _t: detail if screen.page == "detail" else None
    trader._generic_cooking_detail_snapshot = lambda frame=None: (
        detail if screen.page == "detail" else None
    )
    trader._wait_for_cooking_list = lambda _t: listed if screen.page == "list" else None
    trader._cooking_list_snapshot = lambda *_a, **_k: listed if screen.page == "list" else None
    trader._recover_cooking_list = lambda: screen.page == "list"
    trader._click_cooking_back = lambda _frame, *, context: screen.back(context)
    trader.navigator = SimpleNamespace(
        wait_for_q_sp6_sandbox=lambda _timeout: screen.page == "field"
    )
    return trader, logs


class CookingEscTest(unittest.TestCase):
    def setUp(self):
        _patch_clock(self, "trader_cooking")

    def test_esc_when_the_detail_page_stays_after_two_backs(self):
        screen = _CookingPages("detail", backs=(False, False))
        trader, logs = _cook_trader(screen)
        self.assertTrue(trader._return_from_detail_to_list("香草牛排"))
        self.assertEqual(["香草牛排详情", "香草牛排详情补按", "Esc"], screen.presses)
        self.assertIn("料理：香草牛排详情按返回后详情页还在，改按 Esc。", logs)

    def test_no_esc_once_the_second_back_worked(self):
        screen = _CookingPages("detail", backs=(False, True))
        trader, _logs = _cook_trader(screen)
        self.assertTrue(trader._return_from_detail_to_list("香草牛排"))
        self.assertNotIn("Esc", screen.presses)

    def test_no_esc_when_the_detail_page_is_gone(self):
        # Neither the detail page nor the list: Esc could land on the field.
        screen = _CookingPages("detail", backs=(False,))
        trader, _logs = _cook_trader(screen)
        trader._generic_cooking_detail_snapshot = lambda frame=None: None
        self.assertFalse(trader._return_from_detail_to_list("香草牛排"))
        self.assertNotIn("Esc", screen.presses)

    def test_esc_when_the_list_stays_on_the_way_out(self):
        screen = _CookingPages("list", backs=(False, False))
        trader, logs = _cook_trader(screen)
        self.assertTrue(trader._leave_cooking_to_q_sp6())
        self.assertEqual(["料理列表", "料理列表补按", "Esc"], screen.presses)
        self.assertIn("料理：按返回后料理列表还在，改按 Esc。", logs)

    def test_no_esc_on_the_way_out_when_the_list_is_not_read(self):
        screen = _CookingPages("list", backs=(False, False))
        trader, _logs = _cook_trader(screen)
        looks = {"n": 0}

        def list_then_unread(*_a, **_k):
            # Read for the two 返回 presses, then nothing readable.
            looks["n"] += 1
            return SimpleNamespace(frame="list") if looks["n"] <= 2 else None

        trader._cooking_list_snapshot = list_then_unread
        self.assertFalse(trader._leave_cooking_to_q_sp6())
        self.assertNotIn("Esc", screen.presses)

    def test_one_esc_only(self):
        screen = _CookingPages("list", backs=(False, False), esc_lands=False)
        trader, _logs = _cook_trader(screen)
        self.assertFalse(trader._leave_cooking_to_q_sp6())
        self.assertEqual(1, screen.presses.count("Esc"))


# The merchant menu ---------------------------------------------------------


class _Merchant:
    """Beside the merchant: his prompt press and F each open his menu or not."""

    def __init__(self, prompt_opens=False, key_opens=True, on_field=True, key_sent=True):
        self.prompt_opens = prompt_opens
        self.key_opens = key_opens
        self.on_field = on_field
        self.key_sent = key_sent
        self.menu = False
        self.presses = []

    def press_prompt(self):
        self.presses.append("prompt")
        if self.prompt_opens:
            self.menu = True
        return True

    def key(self, key):
        if not self.key_sent:
            return False
        self.presses.append(key)
        if self.key_opens:
            self.menu = True
        return True


def _merchant_navigator(screen):
    from src.tasks.map_trade.navigator import Navigator

    logs = []
    task = SimpleNamespace(
        sleep=lambda *_a: None,
        log_info=logs.append,
        log_warning=lambda message, **_k: logs.append(message),
        info_set=lambda *_a: None,
        tap_key=lambda key, after_sleep=0.0: screen.key(key),
    )
    navigator = Navigator(task, SimpleNamespace(capture=lambda: None))
    navigator._status = lambda *_a: None
    navigator._ocr_keywords_in_frame = lambda *_a, **_k: (
        screen.menu,
        "砍价" if screen.menu else "",
    )
    navigator._click_merchant_interaction = lambda *_a, **_k: screen.press_prompt()
    navigator._field_keycaps_shown = lambda frame=None: screen.on_field and not screen.menu
    return navigator, logs


class MerchantMenuKeyTest(unittest.TestCase):
    def setUp(self):
        _patch_clock(self, "navigator_trade")

    def test_f_when_the_prompt_presses_did_not_open_the_menu(self):
        screen = _Merchant(prompt_opens=False)
        navigator, logs = _merchant_navigator(screen)
        self.assertTrue(navigator._confirm_merchant_menu())
        self.assertEqual("F", screen.presses[-1])
        self.assertEqual(1, screen.presses.count("F"))
        self.assertIn("跑商：点商人后菜单没打开，改按 F 键和他说话。", logs)

    def test_no_f_when_the_prompt_opened_the_menu(self):
        screen = _Merchant(prompt_opens=True)
        navigator, _logs = _merchant_navigator(screen)
        self.assertTrue(navigator._confirm_merchant_menu())
        self.assertNotIn("F", screen.presses)

    def test_no_f_off_the_field(self):
        # No C/H/P key caps: not on the field (or his menu is up unread).
        screen = _Merchant(prompt_opens=False, on_field=False)
        navigator, _logs = _merchant_navigator(screen)
        self.assertFalse(navigator._confirm_merchant_menu())
        self.assertNotIn("F", screen.presses)

    def test_a_key_that_was_not_sent_is_a_failure(self):
        screen = _Merchant(prompt_opens=False, key_sent=False)
        navigator, logs = _merchant_navigator(screen)
        self.assertFalse(navigator._confirm_merchant_menu())
        self.assertIn("跑商：点击商人后未打开对话/商店菜单（未识别到砍价）。", logs)

    def test_f_that_opened_nothing_is_a_failure(self):
        screen = _Merchant(prompt_opens=False, key_opens=False)
        navigator, logs = _merchant_navigator(screen)
        self.assertFalse(navigator._confirm_merchant_menu())
        self.assertEqual(1, screen.presses.count("F"))
        self.assertIn("跑商：点击商人后未打开对话/商店菜单（未识别到砍价）。", logs)


if __name__ == "__main__":
    unittest.main()
