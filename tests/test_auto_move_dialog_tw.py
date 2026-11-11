"""Player v0.3.8 繁中 4K 2026-11-10 (YES-BD2 #78): 每周跑图 第6章 (area-map
exit to 施塔因之塔第5层) and 第14章 (area-map circle in 阿尔卡迪亚居住区域)
failed, the only two map walks of the run; every teleport worked.

The 自动移动 dialog was known only by its 简中 question.  Worded otherwise
it was taken for the walk itself (第14章: 确认 never pressed, the map stayed
open, 45 s of waiting for the hand) or for an exit that did not react
(第6章).  Its title 自动移动 is in every client and is no walk banner."""

import unittest
from types import SimpleNamespace

from src.tasks.map_trade.navigator import Navigator


class QuestionWordingTest(unittest.TestCase):
    def test_the_dialog_is_known_by_its_title(self):
        for text in (
            "自动移动是否自动移动前往所选目的地不再显示取消确认",  # 简中, as before
            "自动移动要自动移动到选择的目的地吗取消确认",
            "自动移动不再显示取消确定",
            "自动移动",
        ):
            with self.subTest(text=text):
                self.assertTrue(Navigator._auto_move_question_shown(text))

    def test_walk_banners_are_no_question(self):
        for text in (
            "自动移动中魔法阵",
            "自动移动中：战斗区域",
            "已完成自动移动",
            "已中止自动移动",
            "此处无正在进行中的任务剑之神殿中央回廊e",
            "",
        ):
            with self.subTest(text=text):
                self.assertFalse(Navigator._auto_move_question_shown(text))


class CirclePressTest(unittest.TestCase):
    """第14章: the circle pressed on the area map opened the dialog."""

    def _navigator(self, walk_texts, confirm=True):
        texts = iter(walk_texts)
        presses = []
        navigator = Navigator(
            SimpleNamespace(sleep=lambda *_a: None),
            SimpleNamespace(capture=lambda: "frame"),
        )
        navigator._status = lambda *_a: None
        navigator._walk_text = lambda _frame: next(texts, "")
        navigator._click_sandbox_navigation_menu_teleport = lambda _frame: False

        def press(_frame):
            presses.append("确认")
            return confirm

        navigator._click_sandbox_navigation_destination_confirmation = press
        return navigator, presses

    def test_other_wording_is_confirmed_not_taken_for_the_walk(self):
        navigator, presses = self._navigator(["自动移动要自动移动到选择的目的地吗取消确定"])

        self.assertEqual((True, False), navigator._follow_teleport_icon_press())
        self.assertEqual(["确认"], presses)

    def test_a_walk_already_going_needs_no_press(self):
        navigator, presses = self._navigator(["自动移动中魔法阵"])

        self.assertEqual((True, False), navigator._follow_teleport_icon_press())
        self.assertEqual([], presses)


class ExitClickTest(unittest.TestCase):
    """第6章: the exit click opened the dialog; the header still named 第6层."""

    def test_the_exit_dialog_is_confirmed(self):
        navigator = Navigator(
            SimpleNamespace(sleep=lambda *_a: None),
            SimpleNamespace(capture=lambda: "frame"),
        )
        navigator._status = lambda *_a: None
        navigator._walk_text = lambda _frame: "自动移动要自动移动到选择的目的地吗不再显示取消确定"
        pressed = []
        navigator._click_sandbox_navigation_destination_confirmation = (
            lambda _frame: pressed.append(1) or True
        )
        navigator._field_map_header = lambda: ""

        self.assertTrue(navigator._confirm_exit_walk_question(("施塔因之塔第6层",)))
        self.assertEqual([1], pressed)


class ConfirmButtonTest(unittest.TestCase):
    def _button(self, names):
        vision = SimpleNamespace(
            ocr_boxes=lambda *_a, **_k: [
                SimpleNamespace(name=name, x=900, y=700, width=80, height=30) for name in names
            ],
            simplify=lambda text: text,
        )
        return Navigator(SimpleNamespace(), vision)._sandbox_navigation_destination_button("frame")

    def test_both_wordings_of_the_button(self):
        self.assertEqual("确认", self._button(["取消", "确认"])[0])
        self.assertEqual("确定", self._button(["取消", "确定"])[0])

    def test_generate_circle_title_is_no_button(self):
        self.assertIsNone(self._button(["生成魔法阵", "取消"]))


if __name__ == "__main__":
    unittest.main()
