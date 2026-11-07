"""The 繁中 game client: OCR text becomes the 简中 client's words (Leo
2026-10-09), and the tool remembers which client it read."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.tasks.BaseBD2Task import BaseBD2Task
from src.utils import game_language, game_text
from src.utils.home_confirmation import home_gacha_ocr_matches, home_left_column_hits


class _Task:
    def __init__(self):
        self.info = {}

    def info_set(self, key, value):
        self.info[key] = value


class GameLanguageTest(unittest.TestCase):
    def setUp(self):
        game_language.reset()
        self.addCleanup(game_language.reset)

    def test_traditional_home_text_is_recognised(self):
        self.assertTrue(game_language.looks_traditional("我的小屋格魯TALK街機遊戲"))
        self.assertTrue(game_language.looks_traditional("抽抽樂 經營管理"))

    def test_simplified_home_text_is_not(self):
        self.assertFalse(game_language.looks_traditional("我的小屋格鲁TALK街机游戏"))
        self.assertFalse(game_language.looks_traditional("抽抽乐"))
        self.assertFalse(game_language.looks_traditional(""))
        self.assertFalse(game_language.looks_traditional(None))

    def test_one_stray_character_is_not_enough(self):
        self.assertFalse(game_language.looks_traditional("抽抽樂"))

    def test_the_latest_clear_reading_names_the_client(self):
        self.assertFalse(game_language.client_is_traditional())
        game_language.note_text("街機遊戲", now=10.0)
        self.assertTrue(game_language.client_is_traditional())
        # A player name or a number says nothing either way.
        game_language.note_text("Leo 12345", now=11.0)
        self.assertTrue(game_language.client_is_traditional())
        # The player switched the game back to 简中.
        game_language.note_text("街机游戏", now=12.0)
        self.assertFalse(game_language.client_is_traditional())

    def test_the_problem_summary_names_the_traditional_client(self):
        from src.tasks import problem_report

        self.assertNotIn("game_language", problem_report.environment(None))
        game_language.note_text("街機遊戲", now=10.0)
        self.assertEqual("繁体中文", problem_report.environment(None)["game_language"])

    def test_a_players_traditional_text_leaves_no_trace(self):
        # A 繁中 guild description read where home's left column would be.
        game_language.note_text("8 30/30 审核 申請請DC聯絡公 #zaga12022")
        game_language.note_text("小尤里樂園Ⅱ 申請請DC聯絡公會長")
        self.assertFalse(game_language.seen_since(0.0))
        self.assertFalse(game_language.client_is_traditional())

    def test_simplified_home_leaves_no_trace(self):
        home_left_column_hits("我的小屋格鲁TALK街机游戏")
        home_gacha_ocr_matches("抽抽乐")
        self.assertFalse(game_language.seen_since(0.0))

    def test_failure_on_the_traditional_client_is_noted_not_blamed(self):
        game_language.note_text("街機遊戲", now=100.0)
        task = _Task()
        self.assertEqual("", game_language.warn_after_failure(task, 50.0, now=101.0))
        self.assertEqual(game_language.TRADITIONAL_LABEL, task.info[game_language.INFO_KEY])

    def test_text_from_an_earlier_run_does_not_count(self):
        game_language.note_text("街機遊戲", now=100.0)
        task = _Task()
        game_language.warn_after_failure(task, 200.0, now=201.0)
        self.assertEqual({}, task.info)


class GameTextTest(unittest.TestCase):
    def setUp(self):
        game_language.reset()
        self.addCleanup(game_language.reset)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        table = Path(folder.name) / "zh_tw.json"
        table.write_text(
            json.dumps(
                {
                    "ui": {"搜索": "探查", "討價還價": "砍价", "X": "单字"},
                    "names": {"故事遊戲卡帶": "剧情游戏卡带", "故事": "剧情"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        patch = mock.patch.object(game_text, "TABLE_PATH", table)
        patch.start()
        self.addCleanup(patch.stop)
        game_text._table.cache_clear()
        self.addCleanup(game_text._table.cache_clear)

    def test_traditional_text_becomes_simplified(self):
        self.assertEqual("街机游戏", game_text.to_tool_text("街機遊戲", False))
        self.assertEqual("抽抽乐", game_text.to_tool_text("抽抽樂", False))

    def test_simplified_text_is_left_alone(self):
        self.assertEqual("街机游戏", game_text.to_tool_text("街机游戏", False))
        # 搜索 on the 简中 client is not the skill 探查.
        self.assertEqual("搜索", game_text.to_tool_text("搜索", False))

    def test_traditional_words_become_the_simplified_clients_words(self):
        self.assertEqual("剧情游戏卡带", game_text.to_tool_text("故事遊戲卡帶", False))
        self.assertEqual("砍价", game_text.to_tool_text("討價還價", False))

    def test_words_spelled_the_same_follow_the_client(self):
        self.assertEqual("探查", game_text.to_tool_text("搜索", True))

    def test_one_character_words_are_never_rewritten(self):
        self.assertNotIn("X", game_text.table_words())

    def test_a_simplified_word_holding_a_shorter_traditional_one_stays(self):
        # 御劍傳 is 繁中 for 御剑传, and 劍傳 alone is 繁中 for 御剑传 too.
        with mock.patch.object(game_text, "_table", lambda: ({"剑传": "御剑传"}, re.compile("剑传"))):
            self.assertEqual("御剑传", game_text.to_cn_words("御剑传"))
            self.assertEqual("御剑传", game_text.to_cn_words("剑传"))

    def test_longest_word_wins(self):
        self.assertEqual("剧情游戏卡带 剧情", game_text.to_tool_text("故事遊戲卡帶 故事", True))

    def test_boxes_are_rewritten_after_noting_the_raw_text(self):
        boxes = [SimpleNamespace(name="街機遊戲"), SimpleNamespace(name="搜索"), SimpleNamespace(name="")]
        game_text.note_boxes(boxes)
        game_text.fix_boxes(boxes)
        self.assertEqual(["街机游戏", "探查", ""], [box.name for box in boxes])
        self.assertTrue(game_language.client_is_traditional())

    def test_a_missing_table_still_simplifies(self):
        with mock.patch.object(game_text, "TABLE_PATH", Path("/nonexistent/zh_tw.json")):
            game_text._table.cache_clear()
            self.assertEqual("故事游戏卡带", game_text.to_tool_text("故事遊戲卡帶", True))

    def test_home_checks_read_the_traditional_home(self):
        self.assertGreaterEqual(home_left_column_hits(game_text.to_tool_text("我的小屋格魯TALK街機遊戲")), 2)
        self.assertTrue(home_gacha_ocr_matches(game_text.to_tool_text("抽抽樂")))

    def test_the_shipped_table_loads(self):
        patch = mock.patch.object(
            game_text,
            "TABLE_PATH",
            Path(game_text.__file__).resolve().parents[2] / "assets" / "game_text" / "zh_tw.json",
        )
        with patch:
            game_text._table.cache_clear()
            words = game_text.table_words()
        self.assertEqual("探查", words.get("搜索"))
        for key in words:
            self.assertGreaterEqual(len(key), 2, key)

    def test_live_traditional_pages_read_as_the_tools_keywords(self):
        """Words read off the 繁中 client in the 2026-10-23 clone run."""
        from src.tasks.map_trade.trader_constants import SHOP_CARTRIDGE_CATEGORY_PATTERN
        from src.utils.cartridge_quick_switch import QUICK_SWITCH_PAGE_LABELS

        shipped = Path(game_text.__file__).resolve().parents[2] / "assets" / "game_text" / "zh_tw.json"
        with mock.patch.object(game_text, "TABLE_PATH", shipped):
            game_text._table.cache_clear()
            self.addCleanup(game_text._table.cache_clear)
            switch = game_text.to_tool_text(
                "最近 店長遊戲卡帶 故事遊戲卡帶 角色遊戲卡帶 戰鬥遊戲卡帶 生活遊戲卡帶 活動遊戲卡帶", True
            )
            for label in QUICK_SWITCH_PAGE_LABELS:
                self.assertIn(label, switch)
            self.assertIn("游戏卡珍藏集", game_text.to_tool_text("遊戲卡帶收藏集", True))
            self.assertIn("段位下滑", game_text.to_tool_text("階級已下滑。", True))
            self.assertIn("出售", game_text.to_tool_text("販售", True))
            # 10-24: the promotion page, and a reward line read cut at both ends.
            self.assertIn("恭喜晋级", game_text.to_tool_text("恭喜升級", True))
            clipped = game_text.to_tool_text("擊畫面將回到上一個畫", True)
            self.assertTrue("点击" in clipped and "返回" in clipped, clipped)
            from src.tasks.map_trade.trader_constants import BUY_CONFIRM_KEYWORDS, SALE_OWNED_PATTERN
            from src.utils.pvp_dialog import parse_start_cost

            self.assertEqual(5, parse_start_cost(game_text.to_tool_text("5倍開始戰鬥5", True)))
            owned = SALE_OWNED_PATTERN.search(game_text.to_tool_text("持有51,809個", True))
            self.assertEqual("51,809", owned.group(1))
            self.assertIn(BUY_CONFIRM_KEYWORDS[1], game_text.to_tool_text("確定要購買所有登錄的商品嗎？", True))
            # The PVP result page after 4 battles, 10-24.
            import re as _re
            from src.tasks.PVPTask import PVPTask

            page = game_text.to_tool_text(
                "重複戰鬥結果 積分2631 已完成4次的戰鬥。 攻擊戰績 3勝1負 積分變化 +積分20 鬥志的獎牌總獲得量 345", True
            )
            hits = [p for p in PVPTask._pvp_result_patterns(None, 4) if _re.search(p, page)]
            self.assertGreaterEqual(len(hits), 4, hits)
            self.assertEqual("恶梦之冬", game_text.to_tool_text("夢魘冬季", True))
            from src.tasks.FreeGachaTask import BACK_PAGE_KEYWORDS, FREE_GACHA_KEYWORDS

            self.assertIn(FREE_GACHA_KEYWORDS[0], game_text.to_tool_text("全部免費抽取", True))
            # 10-25: 精炼 is 煉製 on 繁中, and the gear detail's 自訂標記設定.
            from src.tasks.GearTasks import CONTINUOUS_REFINE_TEXT, REFINE_PAGE_TITLE, REFINE_TRACE_TEXT
            from src.tasks.JunkGearTask import DETAIL_OPEN_KEYWORD

            self.assertIn(REFINE_PAGE_TITLE[0], game_text.to_tool_text("裝備分數煉製", True))
            self.assertIn(CONTINUOUS_REFINE_TEXT, game_text.to_tool_text("連續煉製", True))
            self.assertIn(REFINE_TRACE_TEXT, game_text.to_tool_text("煉製痕跡8,943", True))
            self.assertIn(DETAIL_OPEN_KEYWORD, game_text.to_tool_text("自訂標記設定", True))
            ticket = game_text.to_tool_text("抽抽樂券 持有71個 可免費抽1次的抽抽樂券 道具獲取處", True)
            for keyword in BACK_PAGE_KEYWORDS:
                self.assertIn(keyword, ticket)
            row = SHOP_CARTRIDGE_CATEGORY_PATTERN.search(game_text.to_tool_text("故事遊戲卡帶 1", True))
            self.assertEqual(("剧情", "1"), row.groups())

    def test_misreads_from_the_2k_clone_run_read_as_the_tools_keywords(self):
        """Reads off the 繁中 client in the 2026-11-03 2K clone run."""
        import re as _re

        from src.tasks.PVPTask import PVP_BATTLE_ONGOING_PATTERN
        from src.utils.cartridge_quick_switch import QUICK_SWITCH_PAGE_LABELS

        shipped = Path(game_text.__file__).resolve().parents[2] / "assets" / "game_text" / "zh_tw.json"
        with mock.patch.object(game_text, "TABLE_PATH", shipped):
            game_text._table.cache_clear()
            self.addCleanup(game_text._table.cache_clear)
            # The small 戰鬥 read as 戰門: the page stayed unconfirmed and 每周跑图 stopped.
            switch = game_text.to_tool_text(
                "最近 店長遊戲卡帶 故事遊戲卡帶 角色遊戲卡帶 戰門遊戲卡帶 生活遊戲卡帶 活動遊戲卡帶", True
            )
            for label in QUICK_SWITCH_PAGE_LABELS:
                self.assertIn(label, switch)
            battle = game_text.to_tool_text("目前於1次之中進行1次", True)
            self.assertTrue(_re.search(PVP_BATTLE_ONGOING_PATTERN, battle), battle)
            self.assertEqual("恶作剧幽灵", game_text.to_tool_text("惡作劇幽霊", True))
            # The area map's footer: 3 of 3 words, as on 简中 「在战场中查看 探索0 世界地图」.
            from src.tasks.map_trade.navigator_constants import SANDBOX_NAVIGATION_PAGE_KEYWORDS

            footer = game_text.to_tool_text("剩下5日 在場域中查看 任務0 世界地圖", True)
            hits = [words for words in SANDBOX_NAVIGATION_PAGE_KEYWORDS if any(w in footer for w in words)]
            self.assertEqual(len(SANDBOX_NAVIGATION_PAGE_KEYWORDS), len(hits), footer)

    def test_the_nightmare_winter_town_is_found_by_its_traditional_name(self):
        """4K 繁中 route test 2026-11-06: 活动卡 2's safe zone reads
        「雷瓦汀祕密基地」 (OCR also 秘) where 简中 says 雷瓦汀据点; E2 failed."""
        shipped = Path(game_text.__file__).resolve().parents[2] / "assets" / "game_text" / "zh_tw.json"
        with mock.patch.object(game_text, "TABLE_PATH", shipped):
            game_text._table.cache_clear()
            self.addCleanup(game_text._table.cache_clear)
            for read in ("安全 雷瓦汀祕密基地", "安全 雷瓦汀秘密基地"):
                self.assertIn("雷瓦汀据点", game_text.to_tool_text(read, True))

    def test_a_broad_word_leaves_the_gacha_pages_sentence_alone(self):
        # 販售 -> 出售 (the sell tab) must not rewrite the 抽抽乐 page's
        # 「重新贩售或发放」, one of its page keywords (10-25 collision audit).
        from src.tasks.FreeGachaTask import GACHA_PAGE_KEYWORDS

        shipped = Path(game_text.__file__).resolve().parents[2] / "assets" / "game_text" / "zh_tw.json"
        with mock.patch.object(game_text, "TABLE_PATH", shipped):
            game_text._table.cache_clear()
            self.addCleanup(game_text._table.cache_clear)
            line = game_text.to_tool_text("角色和裝備在未來可能會透過其他方式重新販售或發放", True)
        self.assertIn("重新贩售或发放", line)
        self.assertTrue(any("重新贩售或发放" in keyword for keyword in GACHA_PAGE_KEYWORDS))

    def test_the_pool_party_map_is_found_by_its_traditional_name(self):
        from src.tasks.map_trade.models import EVENT_COLLECTION_TARGETS

        self.assertIn("泳池派对", EVENT_COLLECTION_TARGETS[1][0].titles)

    def test_walking_out_of_a_map_accepts_its_other_names(self):
        """4K 2026-11-06: leaving 泳池派对场 on the 繁中 client (header 泳池派對)
        the walk only checked the 简中 title, took the area map for closed and
        活动卡1 stalled.  Every map-name check uses all of a map's names."""
        import re

        from src.tasks.map_trade import navigator_sandbox
        from src.tasks.map_trade.models import EVENT_COLLECTION_TARGETS

        town = EVENT_COLLECTION_TARGETS[1][0]
        header = navigator_sandbox.normalize_text(game_text.to_tool_text("安全 泳池派對", True))
        self.assertTrue(navigator_sandbox._named(navigator_sandbox._title_words(town), header))
        self.assertFalse(navigator_sandbox._named(navigator_sandbox._title_words(town), ""))
        source = Path(navigator_sandbox.__file__).read_text(encoding="utf-8")
        self.assertEqual([], re.findall(r"normalize_text\(\w+\.title\)", source))

    def test_a_shop_row_number_read_apart_is_joined_back(self):
        from src.tasks.map_trade.trader_cartridge import join_split_row_numbers
        from src.tasks.map_trade.trader_constants import ShopCartridgeOcrText as Text

        texts = [
            Text("剧情游戏卡带", 0.9, (300.0, 131.0)),
            Text("1", 0.8, (420.0, 136.0)),
            Text("血骑士", 0.9, (300.0, 156.0)),
            Text("剧情游戏卡带2", 0.9, (300.0, 225.0)),
            Text("4", 0.9, (300.0, 294.0)),
        ]
        names = sorted(value.text for value in join_split_row_numbers(texts, 1.0, 1.0))
        self.assertEqual(sorted(["剧情游戏卡带1", "血骑士", "剧情游戏卡带2", "4"]), names)


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


class FixTextsTest(unittest.TestCase):
    """BaseBD2Task.fix_texts: every task's OCR goes through game_text."""

    def setUp(self):
        game_language.reset()
        self.addCleanup(game_language.reset)

    def test_every_ocr_result_is_turned_into_simplified_words(self):
        task = object.__new__(BaseBD2Task)
        boxes = [SimpleNamespace(name="全部領取"), SimpleNamespace(name="街機遊戲")]
        with mock.patch("ok.BaseTask.fix_texts", lambda _self, _boxes: None):
            task.fix_texts(boxes)
        self.assertEqual(["全部领取", "街机游戏"], [box.name for box in boxes])
        self.assertTrue(game_language.client_is_traditional())

    def test_the_raw_text_is_noted_before_ok_script_simplifies_it(self):
        task = object.__new__(BaseBD2Task)
        boxes = [SimpleNamespace(name="街機遊戲")]

        def ok_simplifies(_self, detected):
            for box in detected:
                box.name = "街机游戏"

        with mock.patch("ok.BaseTask.fix_texts", ok_simplifies):
            task.fix_texts(boxes)
        self.assertTrue(game_language.client_is_traditional())


if __name__ == "__main__":
    unittest.main()
