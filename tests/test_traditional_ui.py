"""With the app set to Chinese, untranslated text is converted to its script."""

import unittest
from types import SimpleNamespace

from src.ui.traditional import is_simplified, is_traditional, to_simplified, to_traditional, wrap_tr


class TraditionalTest(unittest.TestCase):
    def _app(self, locale, catalog=None):
        catalog = catalog or {}

        def original(self, key):
            return catalog.get(key, key)

        app = SimpleNamespace(locale=SimpleNamespace(name=lambda: locale))
        tr = wrap_tr(original)
        return lambda key: tr(app, key)

    def test_untranslated_text_turns_traditional_on_zh_tw(self):
        tr = self._app("zh_TW")
        self.assertEqual("一鍵完成日常", tr("一键完成日常"))
        self.assertEqual("設定", tr("设置"))  # Taiwan wording

    def test_simplified_and_other_locales_are_untouched(self):
        self.assertEqual("一键完成日常", self._app("zh_CN")("一键完成日常"))
        self.assertEqual("一键完成日常", self._app("en_US")("一键完成日常"))

    def test_a_real_translation_wins(self):
        tr = self._app("zh_TW", {"跑商": "跑商（自訂）"})
        self.assertEqual("跑商（自訂）", tr("跑商"))

    def test_a_traditional_character_turns_simplified_on_zh_cn(self):
        # YES-BD2 #57: 爛装分解 showed in Traditional on a Simplified screen.
        tr = self._app("zh_CN")
        self.assertEqual("烂装强化分解", tr("爛装强化分解"))
        self.assertEqual("爛装强化分解", self._app("en_US")("爛装强化分解"))

    def test_simplified_text_survives_the_simplified_pass(self):
        texts = (
            "一键完成日常",
            "跑完会在这里看到今天的结果",
            "游戏开着但还在登录画面时，自动点进主页",
            "后来",
            "里面",
            "头发",
            "乾坤",
            "账号 1",
        )
        for text in texts:
            with self.subTest(text):
                self.assertEqual(text, to_simplified(text))

    def test_shown_task_names_are_simplified(self):
        from src.tasks.JunkGearTask import LABEL
        from src.ui.shell.data import CHILD_META

        for text in [LABEL] + [short for short, _icon, _kind in CHILD_META.values()]:
            with self.subTest(text):
                self.assertEqual(to_simplified(text), text)

    def test_locale_names(self):
        self.assertTrue(is_traditional("zh_TW"))
        self.assertTrue(is_traditional("zh-HK"))
        self.assertFalse(is_traditional("zh_CN"))
        self.assertTrue(is_simplified("zh_CN"))
        self.assertTrue(is_simplified("zh-SG"))
        self.assertFalse(is_simplified("zh_TW"))
        self.assertEqual("鏡中之戰", to_traditional("镜中之战"))


if __name__ == "__main__":
    unittest.main()
