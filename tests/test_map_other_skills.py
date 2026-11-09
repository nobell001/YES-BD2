"""跑图 blacklist (Leo 2026-11-09 「把那些不相干的技能放進黑名單」, strict:
「分數要求要嚴格一點 有時候會因為地圖原因 被遮住」).

Templates come from the live 4K 繁中 field bar (slot 5).  These checks use
other pictures: the skill setup screen crops (another background), and two
players' 1080p bars where slot 5 holds 迅速 / 飞奔 and slots 1-4 the
collection skills (which must never read as blacklisted)."""

import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from src.tasks.map_trade import other_skills
from src.tasks.map_trade.action_icons import ACTION_SLOT_CENTERS_REFERENCE
from src.tasks.map_trade.collector_constants import BATTLE_ACTIONS
from src.tasks.map_trade.skill_layout import SkillLayoutWrong
from src.utils.ocr_count import CountRead
from tests.test_map_partial_skill_bar import BATTLE, CARD, _player_collector

FIXTURES = Path(__file__).parent / "fixtures" / "map_trade"
SETUP = {
    "swift": "迅速",
    "cooking": "料理",
    "craft": "制作装备",
    "revive": "复活",
    "danger": "侦测危险",
    "dash": "飞奔",
    "circle": "创建魔法阵",
    "hide": "藏身",
    "dispatch": "派遣",
    "alchemy": "炼金术",
}


def _bar(name):
    image = cv2.imread(str(FIXTURES / "skill_bar" / name))
    if image.shape[:2] == (1080, 1920):
        return image
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[640:1080, 1300:1920] = image
    return frame


def _in_slot(crop, slot, size=(1440, 2560)):
    frame = np.full((*size, 3), 20, np.uint8)
    scale = size[0] / 1080
    cx, cy = (round(v * scale) for v in ACTION_SLOT_CENTERS_REFERENCE[slot])
    h, w = crop.shape[:2]
    frame[cy - h // 2 : cy - h // 2 + h, cx - w // 2 : cx - w // 2 + w] = crop
    return frame


class BlacklistRecognitionTest(unittest.TestCase):
    def test_each_skill_from_the_setup_screen_is_named(self):
        for key, label in SETUP.items():
            crop = cv2.imread(str(FIXTURES / "other_skills" / f"setup_{key}.png"))
            for slot in ("subdue", "teleport"):
                with self.subTest(skill=label, slot=slot):
                    self.assertEqual(label, other_skills.other_skill_at(_in_slot(crop, slot), slot))

    def test_players_slot_five_skills_are_named(self):
        self.assertEqual(
            "迅速",
            other_skills.other_skill_at(_bar("summon_used_under_count_player_1080.png"), "teleport"),
        )
        self.assertEqual(
            "飞奔", other_skills.other_skill_at(_bar("layout_wrong_player_1080.png"), "teleport")
        )

    def test_collection_skills_are_never_blacklisted(self):
        for name in ("summon_used_under_count_player_1080.png", "layout_wrong_player_1080.png"):
            frame = _bar(name)
            for slot in ("search", "absorb", "summon", "subdue"):
                with self.subTest(frame=name, slot=slot):
                    self.assertIsNone(other_skills.other_skill_at(frame, slot))
                    self.assertLess(max(other_skills.scores(frame, slot).values()), 0.7)

    def test_an_empty_or_dark_slot_is_no_hit(self):
        self.assertIsNone(other_skills.other_skill_at(np.zeros((1080, 1920, 3), np.uint8), "subdue"))


class BlacklistVetoTest(unittest.TestCase):
    def test_alchemy_in_the_suppress_slot_is_never_pressed_and_named(self):
        # Live 4K 2026-11-09 before the fix: slot 4's potion skill pressed as
        # 压制 opened 炼金术.  Even with digits read there, no press.
        game, collector = _player_collector({"吸收": [None], "召集": [None], "压制": [None]})

        def read(action, *_a, **_k):
            collector._last_count_read = CountRead(None, ("5",))
            return None

        collector._read_count = read
        target = "src.tasks.map_trade.other_skills.other_skill_at"
        with mock.patch(target, lambda _frame, slot: "炼金术" if slot == "subdue" else None):
            with self.assertRaises(SkillLayoutWrong) as caught:
                collector._use_actions(BATTLE_ACTIONS, card_id=CARD, map_role=BATTLE)
        self.assertNotIn("压制", game.presses)
        self.assertIn("第4格是炼金术，不是压制", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
