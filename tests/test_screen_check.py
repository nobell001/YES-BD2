"""The screen library check counts a look-alike taken for a screen as wrong.

Leo 2026-11-05 「像之前學校1樓 3樓 就是你設計錯誤」: a recognizer change is
held back when one frame that was right turns wrong.  These tests pin the
scoring rules of tools/dev/screen_check.py so the gate itself can't loosen.
"""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("screen_check", ROOT / "tools" / "dev" / "screen_check.py")
screen_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen_check)


class AcceptedAnswersTest(unittest.TestCase):
    def test_a_known_screen_needs_its_own_name(self):
        self.assertEqual(screen_check.accepted("home"), ("home",))
        self.assertEqual(screen_check.accepted("area_map"), ("area_map",))

    def test_any_other_screen_must_come_back_unknown(self):
        self.assertEqual(screen_check.accepted("other:bag"), ("unknown",))
        self.assertEqual(screen_check.accepted("home_dimmed"), ("unknown",))

    def test_field_map_and_teleport_map_are_not_interchangeable(self):
        self.assertNotIn("sandbox_map", screen_check.accepted("area_map"))
        self.assertNotIn("area_map", screen_check.accepted("sandbox_map"))


class CompareTest(unittest.TestCase):
    def _compare(self, labels, old, new):
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for key, data in (("labels", labels), ("old", old), ("new", new)):
                paths[key] = Path(tmp) / f"{key}.json"
                paths[key].write_text(json.dumps(data), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(SystemExit) as stop:
                screen_check.cmd_compare(SimpleNamespace(check="classify", **{k: str(v) for k, v in paths.items()}))
        return stop.exception.code, out.getvalue()

    def test_one_frame_turning_wrong_fails_the_change(self):
        labels = {"a.png": "home", "b.png": "other:bag", "c.png": "junk"}
        old = {"a.png": {"classify": "home"}, "b.png": {"classify": "unknown"}, "c.png": {"classify": "x"}}
        new = {"a.png": {"classify": "home"}, "b.png": {"classify": "home"}, "c.png": {"classify": "y"}}
        code, text = self._compare(labels, old, new)
        self.assertEqual(code, 1)
        self.assertIn("b.png: is other:bag, now read as home", text)
        self.assertNotIn("c.png", text)

    def test_only_improvements_pass(self):
        labels = {"a.png": "area_map"}
        code, _ = self._compare(labels, {"a.png": {"classify": "unknown"}}, {"a.png": {"classify": "area_map"}})
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
