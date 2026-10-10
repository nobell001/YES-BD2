import json
import tempfile
import unittest
from pathlib import Path

from src.ui.shell import update_notes


class UpdateNotesTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "update_notes.json"
        self.path.write_text(
            json.dumps(
                {
                    "versions": [
                        {"version": "v0.1.18", "notes": [f"改动{i}" for i in range(65)]},
                        {"version": "v0.1.17", "notes": ["甲", "乙"]},
                        {"version": "v0.1.16", "notes": ["丙"]},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.versions = update_notes.load(self.path)

    def test_every_note_of_the_update_not_just_ten(self):
        notes = update_notes.notes_between(self.versions, "v0.1.17", "v0.1.18")
        self.assertEqual(65, len(notes))

    def test_skipped_versions_are_listed_newest_first(self):
        notes = update_notes.notes_between(self.versions, "v0.1.15", "v0.1.18")
        self.assertEqual(68, len(notes))
        self.assertEqual("改动0", notes[0])
        self.assertEqual("丙", notes[-1])
        self.assertEqual(notes, update_notes.notes_between(self.versions, "v0.1.18", "0.1.15"))

    def test_one_version_alone(self):
        self.assertEqual(["甲", "乙"], update_notes.notes_between(self.versions, None, "v0.1.17"))
        self.assertEqual(
            ["甲", "乙"], update_notes.notes_between(self.versions, "v0.1.17", "v0.1.17")
        )

    def test_unknown_version_keeps_the_launcher_lines(self):
        self.assertIsNone(update_notes.notes_between(self.versions, "v0.1.18", "v0.1.19"))
        self.assertIsNone(update_notes.notes_between(self.versions, None, "dev"))

    def test_missing_or_broken_file_is_empty(self):
        self.assertEqual({}, update_notes.load(self.path.with_name("none.json")))
        self.path.write_text("{", encoding="utf-8")
        self.assertEqual({}, update_notes.load(self.path))
        self.path.write_text('{"versions": 3}', encoding="utf-8")
        self.assertEqual({}, update_notes.load(self.path))

    def test_launcher_bullets_are_dropped(self):
        self.assertEqual(["一", "二"], update_notes.split_lines("• 一\n\n• 二\n• 一"))


if __name__ == "__main__":
    unittest.main()
