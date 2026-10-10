import unittest
from time import monotonic
from types import SimpleNamespace

import numpy as np

from src.tasks.trigger.AutoLoginTask import (
    TERMS_MESSAGE,
    AutoLoginTask,
    MatchResult,
)

TERMS_SCREEN = ["同意《棕色尘埃2》使用条款", "全部同意", "开始游戏"]


def _box(name):
    return SimpleNamespace(name=name, x=100, y=100, width=40, height=20)


class AutoLoginTermsDialogTest(unittest.TestCase):
    """Live 10-10 (4K PC): the game opened on its terms dialog and the
    auto-login waited 10 minutes logging only "state=browndustx"."""

    def _task(self, texts, state="browndustx"):
        task = object.__new__(AutoLoginTask)
        task.config = {"BrownDustX OCR 阈值": 0.2, "登录后主页总等待秒数": 300.0}
        task.info = {}
        task.warnings = []
        task.clicks = []
        task.texts = list(texts)
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_args, **_kwargs: None
        task.log_warning = lambda message, **kwargs: task.warnings.append(
            (message, kwargs.get("notify", False))
        )
        task.sleep = lambda *_args, **_kwargs: None
        task.ocr = lambda *_args, **_kwargs: [_box(text) for text in task.texts]
        task.operate_click = lambda *args, **_kwargs: task.clicks.append(args)
        task.capture_frame = lambda: np.zeros((10, 10, 3), dtype=np.uint8)
        # Every template "hits": nothing may be pressed while the dialog is up.
        task._match = lambda _frame, _spec: MatchResult(0.99, (0, 0), (1, 1), pixel_score=0.99)
        task._home_confirmation_signals = lambda _frame: (False, None, None, 0.0, "")
        task._clear_popups_until_home = lambda *_a, **_k: task.clicks.append("clear") or False
        task._click_login_after_touch = lambda *_a, **_k: task.clicks.append("login")
        task._state = state
        task._finished = False
        task._login_clicked_at = None
        task._login_retry_not_before = 0.0
        task._no_login_signal_since = None
        task._last_confirm_click_at = 0.0
        task._last_download_click_at = 0.0
        task.batch = SimpleNamespace(_start_after_login=True, info={})
        task.batch.info_set = lambda key, value: task.batch.info.__setitem__(key, value)
        task._executor = SimpleNamespace(get_task_by_class=lambda _cls: task.batch)
        return task

    def test_never_presses_and_tells_why_on_the_second_frame(self):
        task = self._task(TERMS_SCREEN)
        AutoLoginTask.run(task)
        self.assertEqual([], task.clicks)
        self.assertEqual([], task.warnings)

        AutoLoginTask.run(task)
        self.assertEqual([], task.clicks)
        self.assertEqual("terms", task._state)
        self.assertEqual([(f"自动登录：{TERMS_MESSAGE}", True)], task.warnings)
        self.assertIn("全部同意", TERMS_MESSAGE)
        self.assertIn("开始游戏", TERMS_MESSAGE)
        self.assertEqual("等你同意使用条款", task.info["状态"])
        self.assertIn("使用条款", task.batch.info["状态"])

    def test_warns_once_while_the_dialog_stays(self):
        task = self._task(TERMS_SCREEN)
        for _ in range(10):
            AutoLoginTask.run(task)
        self.assertEqual(1, len(task.warnings))
        self.assertEqual([], task.clicks)

    def test_goes_on_logging_in_once_the_player_agreed(self):
        task = self._task(TERMS_SCREEN)
        AutoLoginTask.run(task)
        AutoLoginTask.run(task)
        task.texts = ["TOUCH TO START"]
        AutoLoginTask.run(task)
        self.assertEqual(["login"], task.clicks)
        self.assertEqual(0, task._terms_hits)

    def test_shows_up_again_after_closing_warns_again(self):
        task = self._task(TERMS_SCREEN)
        AutoLoginTask.run(task)
        AutoLoginTask.run(task)
        task.texts = []
        task._match = lambda _f, _s: MatchResult(-1.0, (0, 0), (0, 0), pixel_score=-1.0)
        AutoLoginTask.run(task)
        task.texts = TERMS_SCREEN
        AutoLoginTask.run(task)
        AutoLoginTask.run(task)
        self.assertEqual(2, len(task.warnings))

    def test_dialog_after_touch_to_start_blocks_popup_clearing(self):
        task = self._task(TERMS_SCREEN, state="clearing")
        task._login_clicked_at = monotonic() - 299
        for _ in range(3):
            AutoLoginTask.run(task)
        self.assertEqual([], task.clicks)
        self.assertEqual(1, len(task.warnings))
        # Waiting on the player does not run out the loading budget.
        self.assertLess(monotonic() - task._login_clicked_at, 5)
        self.assertEqual("clearing", task._state)

    def test_other_client_languages(self):
        for texts in (
            ["同意《棕色塵埃2》使用條款", "全部同意", "開始遊戲"],
            ["Brown Dust 2 Terms of Service", "Agree to All", "Start"],
            ["利用規約に同意", "すべて同意"],
            ["이용약관 동의", "모두 동의"],
        ):
            with self.subTest(texts=texts):
                task = self._task(texts)
                self.assertTrue(task._is_terms_dialog([_box(text) for text in texts]))

    def test_title_and_update_screens_are_not_the_dialog(self):
        for texts in (
            ["TOUCH TO START", "Ver 1.2.3"],
            ["BrownDustX", "CONFIRM"],
            ["下载容量 1.2GB", "可用空间 30GB", "取消", "下载"],
            ["使用条款", "隐私政策"],  # title-screen links, nothing to agree to
            [],
        ):
            with self.subTest(texts=texts):
                task = self._task(texts)
                self.assertFalse(task._is_terms_dialog([_box(text) for text in texts]))


if __name__ == "__main__":
    unittest.main()
