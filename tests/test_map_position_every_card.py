"""「確認在哪張圖」 for every card and every map (Leo 2026-11-05 「你要有系統性
方案性的方式確認」「你不要一個地方沒辨識到就出錯 明明有很多方法」).

Player v0.2.31 2560x1440: 第18章's town check after the 艾琳 trip failed and
the card was skipped.  The shared reading (`_position_key_in_read`) must:
  * name the map from its clean area-map title, with the 安全/战斗 tag and the
    「普通」/「出现…怪物」 tail;
  * still name it when one character is misread;
  * never name a wrong map: another card's map, or one of this card's
    neighbours that differs only in a floor / number / side (3楼 and 1楼).
A new card is covered here as soon as it is in COLLECTABLE_CARDS.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.tasks.map_trade.models import COLLECTABLE_CARDS, CollectionMapRole
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_constants import MAP_NAME_TELLING_CHARS
from src.tasks.map_trade.vision import normalize_text


def _navigator() -> Navigator:
    navigator = Navigator(SimpleNamespace(), SimpleNamespace())
    navigator._status = lambda *_a: None
    return navigator


def _header(target, name: str) -> str:
    if target.role == CollectionMapRole.MAIN_AREA:
        return normalize_text(f"安全 {name} 普通 ?")
    return normalize_text(f"战斗Ⅰ {name} 出现暗属性怪物 ?")


def _misread(name: str) -> str | None:
    """``name`` with one character in its middle swapped for a look-alike
    blot, never a character that tells maps apart; None when too short."""
    if len(name) < 4:
        return None
    for index in range(len(name) // 2, len(name)):
        if name[index] not in MAP_NAME_TELLING_CHARS:
            return name[:index] + "口" + name[index + 1 :]
    return None


# The neighbour a floor / number / side character makes: 3楼 and 1楼.
SWAPS = ("0123456789", "一二三四五六七八九", "左右", "前后", "上下")

# Area-map titles the app read on Leo's 2K PC (logs 2026-09-29..10-22),
# misreads included: (card id, read, map key or None).
REAL_READS = (
    ("Q_sp18", "安全科库托斯暗黑神殿普通", "main_area"),
    ("Q_sp18", "战斗科库托斯圣域出现暗属性怪物", "battle_area_1"),
    ("Q_sp18", "战斗第一记忆空间出现暗属性怪物", "battle_area_2"),
    ("Q_sp6", "施塔因之塔第6屋", "battle_area_1"),
    ("Q_sp6", "战斗施塔因之塔第5层出现暗属性怪物", "battle_area_2"),
    ("Q_sp7", "战斗隐藏神殿c出现水属性怪物", "battle_area_2"),
    ("Q_sp14", "战斗剑之神殿中央回廊出现光属性怪物", "battle_area_2"),
    ("Q_sp14", "安全阿尔卡迪亚居住区域普通", "main_area"),
    ("Q_sp19", "安全t亡者安息处普通", "main_area"),
)


class EveryCardPositionTest(unittest.TestCase):
    def setUp(self):
        self.navigator = _navigator()

    def test_clean_titles_name_their_map(self):
        for card in COLLECTABLE_CARDS:
            for target in card.targets:
                with self.subTest(card=card.card_id, map=target.title):
                    self.assertEqual(
                        target.key,
                        self.navigator._position_key_in_read(card, _header(target, target.title)),
                    )

    def test_one_misread_character_still_names_the_map(self):
        for card in COLLECTABLE_CARDS:
            for target in card.targets:
                misread = _misread(normalize_text(target.title))
                if misread is None:
                    continue
                with self.subTest(card=card.card_id, map=target.title, read=misread):
                    found = self.navigator._position_key_in_read(card, _header(target, misread))
                    # Never another map; None only when a neighbour is as close.
                    self.assertIn(found, (target.key, None))
                    if found is None:
                        others = [
                            self.navigator._name_closeness(misread, other)
                            for other in card.targets
                            if other is not target
                        ]
                        self.assertGreaterEqual(
                            max(others), self.navigator._name_closeness(misread, target)
                        )

    def test_no_other_map_is_ever_taken_for_one_of_the_card(self):
        names = {
            normalize_text(title)
            for card in COLLECTABLE_CARDS
            for target in card.targets
            for title in target.titles
        }
        for card in COLLECTABLE_CARDS:
            own = {normalize_text(title) for target in card.targets for title in target.titles}
            for name in sorted(names - own):
                if any(mine in name for mine in own):
                    continue  # holds this card's whole name: a real neighbour label
                found = self.navigator._position_key_in_read(card, normalize_text(f"安全 {name} 普通"))
                with self.subTest(card=card.card_id, read=name):
                    self.assertIsNone(found)

    def test_floor_and_side_neighbours_are_not_the_map(self):
        # 学校3楼 / 学校1楼 (player v0.2.29 2026-11-04) and the rest of the class.
        for card in COLLECTABLE_CARDS:
            for target in card.targets:
                name = normalize_text(target.title)
                for index, char in enumerate(name):
                    swap = next(
                        (
                            group[(group.index(char) + 1) % len(group)]
                            for group in SWAPS
                            if char in group
                        ),
                        None,
                    )
                    if swap is None:
                        continue
                    other = name[:index] + swap + name[index + 1 :]
                    if any(normalize_text(alias) in other for alias in target.aliases):
                        # A short alias set from live reads (避难所 for 避难所166,
                        # 室内泳池): the card has no such neighbour map.
                        continue
                    if any(normalize_text(t.title) == other for t in card.targets):
                        continue
                    with self.subTest(card=card.card_id, map=target.title, read=other):
                        self.assertNotEqual(
                            target.key,
                            self.navigator._position_key_in_read(card, _header(target, other)),
                        )

    def test_real_reads_from_the_logs(self):
        cards = {card.card_id: card for card in COLLECTABLE_CARDS}
        for card_id, read, key in REAL_READS:
            with self.subTest(card=card_id, read=read):
                self.assertEqual(
                    key, self.navigator._position_key_in_read(cards[card_id], normalize_text(read))
                )


if __name__ == "__main__":
    unittest.main()


class PositionRemediesTest(unittest.TestCase):
    """An unclear read is read again enlarged, then the map is opened once
    more; a failure keeps every read for the message."""

    def _navigator(self, headers, rereads=()):
        navigator = _navigator()
        headers = iter(headers)
        rereads = iter(rereads)
        navigator.vision = SimpleNamespace(
            capture=lambda: None,
            simplify=lambda text: text,
            ocr_text=lambda *_a, **_k: next(rereads, ""),
        )
        navigator.ensure_small_minimap = lambda: True
        navigator._open_field_map = lambda: next(headers)
        navigator._close_field_map = lambda: None
        return navigator

    CARD = next(card for card in COLLECTABLE_CARDS if card.card_id == "Q_sp18")

    def test_enlarged_reread_names_the_map(self):
        navigator = self._navigator(["安全科库托"], ["安全 科库托斯暗黑神殿 普通"])
        self.assertEqual("main_area", navigator.current_collection_target(self.CARD))

    def test_map_opened_again_after_an_unclear_read(self):
        navigator = self._navigator(["安全科库托", "安全科库托斯暗黑神殿普通"])
        self.assertEqual("main_area", navigator.current_collection_target(self.CARD))

    def test_clean_read_of_another_map_is_not_opened_again(self):
        opened = []
        navigator = self._navigator(["安全记忆岔路口普通", "安全科库托斯暗黑神殿普通"])
        inner = navigator._open_field_map
        navigator._open_field_map = lambda: opened.append(1) or inner()
        self.assertIsNone(navigator.current_collection_target(self.CARD))
        self.assertEqual(1, len(opened))
        self.assertIn("记忆岔路口", navigator._last_position_header)

    def test_failure_keeps_every_read(self):
        navigator = self._navigator(["安全科库托", None])
        self.assertIsNone(navigator.current_collection_target(self.CARD))
        self.assertEqual("安全科库托 / 区域地图没打开", navigator._last_position_header)
