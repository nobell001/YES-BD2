"""Look-alike pages (bug class A in docs/dev-notes/bug-prevention.md).

Every page check runs on every picture in tests/fixtures/pages.json and may
say yes only on the pages it is for.  The merchant's open 对话/商店 menu passed
for 「beside him」 (player summary v0.2.15 2026-10-28) because that check had
never been run on the menu.

With each fix, add the player's picture to pages.json; with each new page
check, add it to CHECKS (or a page to TRADE_STATES).
"""

import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - CI without OCR
    ONNXPaddleOcr = None

from src.tasks.map_trade.models import ScreenState
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.vision import Vision
from src.utils import known_popups

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = FIXTURES / "pages.json"

# classify_trade's answer on each page; a page not listed is UNKNOWN.
TRADE_STATES = {
    "home": ScreenState.HOME,
    "field": ScreenState.SANDBOX,
    # Parts of the field's HUD on black: still named the field.
    "part_field": ScreenState.SANDBOX,
    # The minimap's ≡ menu, open over the field.
    "field_nav_menu": ScreenState.SANDBOX,
    "merchant_menu": ScreenState.MERCHANT_DIALOG,
    # The 价目表 opens over the shop's sell page.
    "price_list": ScreenState.SHOP,
    "teleport_map": ScreenState.AREA_MAP,
    "field_map": ScreenState.SANDBOX_MAP,
    # The 珍藏集 page and the quick-switch bar both show the 剧情游戏卡 tab.
    "card_collection": ScreenState.CARD_MENU,
    "quick_switch_bar": ScreenState.CARD_MENU,
}

# name -> (check, the pages it says yes on)
CHECKS = {
    "主页": (lambda nav, frame: nav._home_confirmation_signals(frame)[0], {"home"}),
    "商人菜单": (lambda nav, frame: nav._merchant_menu_in_frame(frame), {"merchant_menu"}),
    # His 「洛兹 欢迎光临!」 on the open menu reads as the prompt too, so
    # 「beside him on the field」 is the prompt with the menu closed.
    "商人互动按钮": (
        lambda nav, frame: nav._merchant_prompt_box(frame) is not None,
        {"merchant_field", "merchant_menu"},
    ),
    # 跑图 presses ≡ once more only while no menu row reads, and a tab once
    # more only while the bar's tab names show.
    "≡菜单": (
        lambda nav, frame: nav._nav_menu_shown(frame),
        {"field_nav_menu"},
    ),
    "快速切换栏": (
        lambda nav, frame: nav._story_category_read(frame, "story")[1],
        {"quick_switch_bar"},
    ),
    # F, M and P are sent only on it: on 主页 F opens the recent cartridge.
    "场景按键": (
        lambda nav, frame: nav._field_keycaps_shown(frame),
        {"field", "field_nav_menu"},
    ),
    # 跑商 presses the 价目表's ✕ again, then Esc, only while its title reads,
    # and the sale dialog's ✕ only while 拥有/可购买 read (no picture of the
    # dialog yet: it may say yes on none of these).
    "价目表": (lambda nav, frame: _trader(nav)._price_list_open(frame), {"price_list"}),
    "出售弹窗": (lambda nav, frame: _trader(nav)._sale_dialog_shown(frame), set()),
    # Only 「点击继续」 is pressed on it, never its 「关闭」 setting (Leo's 4K
    # 2026-10-28 16:02).
    "战斗暂停菜单": (
        lambda nav, frame: known_popups.is_battle_menu(nav.task.ocr(frame=frame)),
        {"battle_pause_menu"},
    ),
}


def _trader(nav):
    """The trade side's page checks, on the navigator's vision."""
    from src.tasks.map_trade.trader import Trader

    trader = object.__new__(Trader)
    trader.task, trader.vision = nav.task, nav.vision
    return trader


def navigator_with_real_ocr():
    engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True, use_npu=False)
    cache = {}

    def ocr(*, frame, threshold=0.2, **_kwargs):
        # The checks read the same areas again; one OCR per area and picture.
        key = (hashlib.md5(frame.tobytes()).hexdigest(), frame.shape, threshold)
        if key not in cache:
            boxes = []
            for points, (text, score) in engine.ocr(frame)[0] or []:
                if score < threshold:
                    continue
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                boxes.append(
                    SimpleNamespace(
                        name=text, x=min(xs), y=min(ys),
                        width=max(xs) - min(xs), height=max(ys) - min(ys), confidence=score,
                    )
                )
            cache[key] = boxes
        return list(cache[key])

    task = SimpleNamespace(
        config={},
        vision_threshold_key="跑图跑商识图阈值",
        info_set=lambda *_a, **_k: None,
        log_info=lambda *_a, **_k: None,
        log_warning=lambda *_a, **_k: None,
        sleep=lambda *_a: None,
        ocr=ocr,
    )
    navigator = Navigator(task, Vision(task))
    navigator._status = lambda *_a: None
    return navigator


def load_pages():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["pages"]


class ManifestTest(unittest.TestCase):
    def test_every_listed_picture_exists(self):
        for path in load_pages():
            with self.subTest(picture=path):
                self.assertTrue((FIXTURES / path).is_file())

    def test_every_page_a_check_names_is_known(self):
        named = set(TRADE_STATES)
        for _check, pages in CHECKS.values():
            named |= pages
        listed = set(load_pages().values())
        # merchant_field has no picture yet: none was saved beside him.
        self.assertEqual(set(), named - listed - {"merchant_field"})


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class PageLookalikeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = load_pages()
        cls.navigator = navigator_with_real_ocr()
        cls.frames = {}

    def frame(self, path):
        if path not in self.frames:
            image = cv2.imread(str(FIXTURES / path))
            self.assertIsNotNone(image, path)
            if image.shape[1] != 1920:
                # The checks were written on 1920x1080 game pictures.
                shrink = image.shape[1] > 1920
                image = cv2.resize(
                    image, (1920, 1080),
                    interpolation=cv2.INTER_AREA if shrink else cv2.INTER_CUBIC,
                )
            self.frames[path] = image
        return self.frames[path]

    def test_each_check_says_yes_only_on_its_pages(self):
        for name, (check, pages) in CHECKS.items():
            for path, page in self.pages.items():
                with self.subTest(check=name, picture=path):
                    said = bool(check(self.navigator, self.frame(path)))
                    self.assertEqual(page in pages, said, f"「{name}」 on a {page} picture")

    def test_trade_screen_names_each_page(self):
        for path, page in self.pages.items():
            with self.subTest(picture=path):
                self.assertEqual(
                    TRADE_STATES.get(page, ScreenState.UNKNOWN),
                    self.navigator.classify_trade(self.frame(path)),
                    f"a {page} picture",
                )


if __name__ == "__main__":
    unittest.main()
