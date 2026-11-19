"""tools/talos_gamekee.py: GameKee's 阵容模拟器 charts as the shipped 塔洛斯 records
(Leo 2026-11-19 「只要這網站更新 這邊就照著排軸」)."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from src.tasks.fiend_hunt.record import load_record
from src.tasks.fiend_hunt.recording import RECORD_FILE
from src.tasks.talos import stages
from tools import talos_gamekee as gamekee

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "talos"


def charts(season: int = 9) -> dict[int, tuple[int, dict]]:
    """stage -> (chart id, chart) of the 10-22 period (title 「Ⅸ战术教材N」) or the 11-19 one (「Ⅹ…」)."""
    data = json.loads((FIXTURES / f"gamekee_season{season}_charts.json").read_text(encoding="utf-8"))
    return {int(chart["title"].split("战术教材")[1]): (int(key), chart) for key, chart in data.items()}


def bursts(item) -> dict[tuple[int, str], int]:
    return {
        (turn["turn"], unit): level
        for turn in item.record["turns"]
        for unit, level in turn.get("bursts", {}).items()
        if level
    }


def tab(title, chart=None):
    children = [{"type": "paragraph", "children": [{"text": "说明"}]}]
    if chart is not None:
        children.append({"type": "battle-array", "data": {"tempId": chart}, "children": [{"text": ""}]})
    return {"type": "tab-item", "title": title, "children": children}


def page(*sections):
    """A page like 697611: per season a heading, then the stages' tabs."""
    content = [{"type": "paragraph", "children": [{"text": "战术教材攻略"}]}]
    for heading, tabs in sections:
        content.append({"type": "header-two", "children": [{"text": heading}]})
        content.append({"type": "tabs", "children": tabs})
    return content


class PageTest(unittest.TestCase):
    def test_the_newest_season_stages(self):
        content = page(
            ("第八赛季攻略", [tab("1", 2200), tab("2", 2201)]),
            ("第九赛季攻略", [tab("﻿1", 2308), tab("2", 2305), tab("3"), tab("说明")]),
        )
        season, found = gamekee.season_stages(content)
        self.assertEqual("第九赛季攻略", season)
        self.assertEqual({1: 2308, 2: 2305, 3: None}, found)  # 3: listed, no chart yet


class ConvertTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.converted = {
            stage: gamekee.convert(stage, chart_id, chart) for stage, (chart_id, chart) in charts().items()
        }

    def test_every_stage_converts_to_a_record_the_task_loads(self):
        self.assertEqual(list(range(1, 10)), sorted(self.converted))
        for stage, item in self.converted.items():
            with self.subTest(stage=stage):
                self.assertEqual([], item.unsure)
                self.assertEqual(date(2026, 10, 22), item.made)
                turns = [turn["turn"] for turn in item.record["turns"]]
                self.assertEqual(list(range(1, 2 * len(turns), 2)), turns)  # TURN 1, 3, 5 ...

    def test_cells_and_moves_of_a_chart(self):
        # 「Ⅸ战术教材3」: 帕莱特 on slot 3 (row 0, front), 格雷 on slot 11 (row 2, front)
        first = self.converted[3].record["turns"][0]
        self.assertEqual({"帕莱特": [0, 3], "格雷": [2, 3]}, first["cells"])
        self.assertEqual(["格雷", "帕莱特"], first["order"])
        self.assertEqual({"格雷": "击退", "帕莱特": "击退"}, first["skills"])
        self.assertEqual({"帕莱特": "技能1", "格雷": "技能1"}, self.converted[3].record["turns"][1]["skills"])

    def test_bursts_and_preempt_from_the_note(self):
        # 「3回合，开紫色皮蛋（2号位）的3级爆发」: 2号位 of the list is 帕莱特
        self.assertEqual({(3, "帕莱特"): 3}, bursts(self.converted[3]))
        self.assertEqual({(1, "马莫尼勒"): 3, (3, "帕莱特"): 3, (7, "帕莱特"): 1}, bursts(self.converted[5]))
        self.assertEqual({(3, "尤里"): 3, (7, "尤里"): 3, (11, "尤里"): 3}, bursts(self.converted[9]))
        preempt = [turn.get("preempt") for turn in self.converted[7].record["turns"]]
        self.assertIn("格兰希特", preempt[0])

    def test_a_note_it_cannot_place_is_listed_for_a_person(self):
        turns = gamekee.chart_turns(charts()[3][1]["content"])
        unsure = gamekee.apply_notes(turns, "3回合，开不存在的人的3级爆发")
        self.assertEqual(["3回合，开不存在的人的3级爆发"], unsure)

    def test_the_next_season_notes(self):
        # 2026-11-19 (第十赛季): the notes wrote bursts five new ways; a line read
        # wrong (or not at all) plays the stage without the burst it needs
        converted = {stage: gamekee.convert(stage, chart_id, chart) for stage, (chart_id, chart) in charts(10).items()}
        self.assertEqual(list(range(1, 17)), sorted(converted))
        self.assertEqual({}, {stage: item.unsure for stage, item in converted.items() if item.unsure})
        expected = {
            1: {(3, "神圣悠丝缇亚"): 3},  # 「3回合，开神ut 3级爆发」
            5: {(1, "安洁莉卡"): 1},  # 「安洁莉卡开1级爆发」 (no turn: the one round)
            6: {  # 「第7回合，拉菲娜2级，莱维娅1级，罗安3级」 (no 爆发; 莱维亚 in the chart)
                (7, "拉菲娜"): 2, (7, "莱维亚"): 1, (7, "罗安"): 3, (13, "莱维亚"): 1, (13, "罗安"): 3,
            },
            7: {(1, "提尔"): 3},  # 「1回合，小狗（3号位）开3级爆发」; 「5回合，…开不开无所谓」: none
            9: {(1, "奥利维耶"): 3},  # 「1回合，奥利维耶3级爆发」
            10: {(3, "神圣悠丝缇亚"): 3},
            11: {(1, "拉德尔"): 2},  # 「开铁面具（1号位）2级爆发」
            12: {(1, "莎赫拉查德"): 3},  # 「1回合，开莎拉3级爆发」
            15: {(1, "达丽安"): 1},  # 「开达利安9（2号位）1级爆发」
            16: {(1, "露比雅"): 3, (3, "西利亚"): 3},
        }
        for stage, item in converted.items():
            with self.subTest(stage=stage):
                self.assertEqual(expected.get(stage, {}), bursts(item))
                self.assertEqual(date(2026, 11, 19), item.made)
        self.assertEqual({"格兰希特": "技能1"}, converted[14].record["turns"][0]["preempt"])

    def test_a_short_name_fits_one_unit_only(self):
        turns = gamekee.chart_turns(charts(10)[11][1]["content"])  # 悠丝缇亚 and 莎赫拉查德, no 神圣悠丝缇亚
        self.assertEqual(["1回合，开神ut 3级爆发"], gamekee.apply_notes(turns, "1回合，开神ut 3级爆发"))
        self.assertEqual([], gamekee.apply_notes(turns, "1回合，开ut 2级爆发"))
        self.assertEqual(2, turns[0]["bursts"]["悠丝缇亚"])

    def test_written_records_replace_the_last_season(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = stages.record_folder(12, root)
            old.mkdir(parents=True)
            (old / RECORD_FILE).write_text("{}", encoding="utf-8")
            items = [self.converted[stage] for stage in (1, 2, 3)]
            gamekee.write(items, "第九赛季攻略", 9, root)
            self.assertFalse(old.exists())
            self.assertEqual(9, stages.stage_count(root))  # 4-9 listed on the page, no chart yet
            self.assertEqual(list(range(4, 10)), stages.missing_records(root))
            self.assertEqual(date(2026, 10, 22), stages.records_made(root))
            record = load_record(stages.record_folder(3, root) / RECORD_FILE)
            self.assertEqual(sorted(record.turns), [1, 3])
            source = json.loads((root / stages.SOURCE_FILE).read_text(encoding="utf-8"))
            self.assertEqual({"1": 2308, "2": 2305, "3": 2300}, source["charts"])


class RunTest(unittest.TestCase):
    def test_season_names_match_with_or_without_dates(self):
        self.assertEqual(gamekee.season_name("第九赛季攻略"), gamekee.season_name("第九赛季（10-22 ~ 11-18）"))
        self.assertNotEqual(gamekee.season_name("第十赛季攻略"), gamekee.season_name("第九赛季攻略"))

    def test_the_hand_made_season_is_left_alone(self):
        # the shipped nine (10-22) were made from videos; the page still shows that season
        content = page(("第九赛季攻略", [tab("1", 2308)]))
        hand_made = {"season": "第九赛季（10-22 ~ 11-18）", "stages": 9, "made": "2026-10-22"}
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(gamekee, "fetch_page", lambda: content),
            mock.patch.object(gamekee, "fetch_chart", side_effect=AssertionError("fetched")),
            mock.patch.object(gamekee, "write", side_effect=AssertionError("written")),
        ):
            (Path(folder) / stages.SOURCE_FILE).write_text(json.dumps(hand_made), encoding="utf-8")
            self.assertEqual(0, gamekee.main([], Path(folder)))

    def test_a_new_season_is_written_with_its_player_note(self):
        by_id = {chart_id: chart for chart_id, chart in charts().values()}
        content = page(("第十赛季攻略", [tab("1", 2308), tab("2", 2305), tab("3")]))
        with tempfile.TemporaryDirectory() as folder:
            root, message = Path(folder), Path(folder) / "message.txt"
            with (
                mock.patch.object(gamekee, "fetch_page", lambda: content),
                mock.patch.object(gamekee, "fetch_chart", lambda chart_id: by_id[chart_id]),
            ):
                self.assertEqual(0, gamekee.main(["--message", str(message)], root))
            self.assertEqual(3, stages.stage_count(root))
            self.assertEqual([3], stages.missing_records(root))
            text = message.read_text(encoding="utf-8")
            self.assertIn("玩家：塔洛斯战术教材换成第十赛季的轴（2 关，第 [3] 关攻略网站还没出）", text)

    def test_a_season_heading_without_charts_keeps_the_records(self):
        content = page(("第九赛季攻略", [tab("1", 2308)]), ("第十赛季攻略", [tab("1"), tab("2")]))
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(gamekee, "fetch_page", lambda: content):
            self.assertEqual(0, gamekee.main([], Path(folder)))
            self.assertEqual([], list(Path(folder).iterdir()))

    def test_a_page_without_season_headings_is_an_error(self):
        # the site changed its page: the daily job opens an issue
        with mock.patch.object(gamekee, "fetch_page", lambda: [tab("1", 2308)]):
            self.assertEqual(1, gamekee.main([], Path("/nonexistent")))

if __name__ == "__main__":
    unittest.main()
