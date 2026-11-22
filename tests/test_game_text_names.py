"""The shipped 繁中 word table (assets/game_text/zh_tw.json) against the
character list.  Kept apart from test_game_language so the daily
角色名单更新 job can run it without ok-script (2026-11-22: a new costume whose
繁中 name the table lacked failed that job from 11-19 on)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from src.utils import game_language, game_text


class ShippedNamesTest(unittest.TestCase):
    """Leo 2026-10-25 「角色名翻譯 都不一樣 親密度的台詞 技能 你要去完整核對」:
    every 繁中 name read off the game reaches the tool as its 简中 name."""

    def setUp(self):
        game_language.reset()
        self.addCleanup(game_language.reset)
        shipped = Path(game_text.__file__).resolve().parents[2] / "assets" / "game_text" / "zh_tw.json"
        patch = mock.patch.object(game_text, "TABLE_PATH", shipped)
        patch.start()
        self.addCleanup(patch.stop)
        game_text._table.cache_clear()
        self.addCleanup(game_text._table.cache_clear)

    def test_every_character_costume_and_skill_name(self):
        root = Path(game_text.__file__).resolve().parents[2]
        data = json.loads((root / "src" / "tasks" / "fiend_hunt" / "data" / "characters.json").read_text(encoding="utf-8"))
        pairs = []
        for character in data["characters"]:
            pairs.append((character.get("name_zh_tw"), character.get("name_zh_cn")))
            for costume in character.get("costumes") or []:
                pairs.append((costume.get("name_zh_tw"), costume.get("name_zh_cn")))
                pairs.append((costume.get("skill_zh_tw"), costume.get("skill_zh_cn")))
        wrong = [
            (tw, cn, game_text.to_tool_text(tw, True))
            for tw, cn in pairs
            if tw and cn and game_text.to_tool_text(tw, True) != cn
        ]
        self.assertGreater(len(pairs), 400)
        self.assertEqual([], wrong)

    def test_a_word_both_clients_spell_alike_is_left_alone(self):
        # 泳池派對 is the costume 泳池派对 (and the map 泳池派对场).
        self.assertEqual("泳池派对", game_text.to_tool_text("泳池派對", True))
        self.assertEqual("梦幻广场", game_text.to_tool_text("夢幻廣場", True))


if __name__ == "__main__":
    unittest.main()
