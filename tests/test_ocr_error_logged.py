"""An OCR error is written to the log once per read, not silently taken as
"no text" (audit #64)."""

import unittest

from src.tasks.task_vision_mixin import TaskVisionMixin


class _Task(TaskVisionMixin):
    def __init__(self, error=None):
        self.config = {}
        self.error = error
        self.infos = {}
        self.warnings = []

    def ocr(self, **_kwargs):
        if self.error is not None:
            raise self.error
        return []

    def info_set(self, key, value):
        self.infos[key] = value

    def log_warning(self, message, **_kwargs):
        self.warnings.append(message)


class OcrErrorLoggedTest(unittest.TestCase):
    def test_an_error_is_logged_once_per_read_name(self):
        task = _Task(RuntimeError("onnx session failed"))
        for _ in range(3):
            self.assertEqual("", task._ocr_text(None, "主页按钮"))
        task._ocr_text(None, "抽抽乐")
        self.assertEqual(2, len(task.warnings))
        self.assertIn("主页按钮", task.warnings[0])
        self.assertIn("onnx session failed", task.warnings[0])
        self.assertEqual("onnx session failed", task.infos["主页按钮 OCR 错误"])

    def test_a_normal_read_logs_nothing(self):
        task = _Task()
        self.assertEqual("", task._ocr_text(None, "主页按钮"))
        self.assertEqual([], task.warnings)


if __name__ == "__main__":
    unittest.main()
