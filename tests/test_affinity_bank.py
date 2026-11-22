"""The 亲密度谈心 answer bank (src/tasks/affinity/data/counseling.json, Leo
2026-10-21); also run by the daily character-list job after a refresh."""

from __future__ import annotations

import unittest

from src.tasks.affinity import answers


class BankTest(unittest.TestCase):
    def test_bank_has_every_costume_with_fifteen_questions(self):
        costumes = answers.bank()
        self.assertGreaterEqual(len(costumes), 22)
        for costume in costumes:
            self.assertEqual(len(costume.questions), 15, costume.id)
            self.assertTrue(costume.costume and costume.character, costume.id)

    def test_costume_found_by_its_game_names(self):
        self.assertEqual(answers.find_costume("白色猫咪", "鲁").id, "Rou_1")
        self.assertEqual(answers.find_costume("剑后", "席比雅").id, "Sylvia_2")
        # 繁中 client and a misread character
        self.assertEqual(answers.find_costume("沙漠之花", "席比雅").id, "Sylvia_1")
        self.assertEqual(answers.find_costume("澄心無邪兔女郎", "提爾").id, "Tyr_2")
        self.assertIsNone(answers.find_costume("没有这件衣服", "某人"))

    def test_best_answer_picked_in_either_order(self):
        rou = answers.find_costume("白色猫咪", "鲁")
        pick = answers.pick_answer(["想去草地那边。", "想去山洞那边。"], rou)
        self.assertEqual((pick.index, pick.known), (0, True))
        pick = answers.pick_answer(["想去山洞那边", "想去草地那边"], rou)
        self.assertEqual((pick.index, pick.known), (1, True))

    def test_misread_and_traditional_answers_still_match(self):
        rou = answers.find_costume("白色猫咪", "鲁")
        # one character dropped, and the 繁中 wording
        misread = ["夸奖鲁的身体很柔", "试着模仿鲁的动作。"]
        self.assertEqual(answers.pick_answer(misread, rou).index, 1)
        self.assertEqual(answers.pick_answer(["稱讚魯身體很柔軟", "模仿魯的動作"], rou).index, 1)

    def test_same_answers_in_two_questions_follow_the_question_on_screen(self):
        # 暗黑圣女: 有/没有 in two questions with opposite values.
        saint = next(c for c in answers.bank() if c.costume == answers.normalize("暗黑圣女"))
        prank = "店长曾经捉弄过朋友吗？"
        prayer = "店长，你有没有过那种虔诚祈祷之后，愿望真的实现了的经历？"
        self.assertEqual(0, answers.pick_answer(["有。", "没有。"], saint, prank).index)
        self.assertEqual(1, answers.pick_answer(["有。", "没有。"], saint, prayer).index)
        self.assertEqual(0, answers.pick_answer(["没有", "有"], saint, "店長有過那種誠心祈禱後，願望成真的經驗嗎？").index)

    def test_every_traditional_answer_picks_the_best_one(self):
        """Each bank question as the 繁中 client shows it, both orders."""
        import json

        from src.utils import game_text

        data = json.loads(answers.BANK_FILE.read_text(encoding="utf-8"))
        wrong = []
        for entry in data["costumes"]:
            costume = answers.find_costume(
                game_text.to_tool_text(entry.get("costume_zh_tw"), True),
                game_text.to_tool_text(entry.get("character_zh_tw"), True),
            )
            self.assertIsNotNone(costume, entry.get("costume_zh_tw"))
            self.assertEqual(str(entry["id"]), costume.id)
            for question in entry["questions"]:
                values = [answer["exp"] for answer in question["answers"]]
                reads = [game_text.to_tool_text(a["text"].get("tw"), True) for a in question["answers"]]
                screen = game_text.to_tool_text(question["prompt"].get("tw"), True)
                for order in ((0, 1), (1, 0)):
                    pick = answers.pick_answer([reads[i] for i in order], costume, screen)
                    if values[order[pick.index]] != max(values):
                        wrong.append((entry["id"], question["id"], order))
        self.assertEqual([], wrong)

    def test_unknown_question_takes_the_first(self):
        rou = answers.find_costume("白色猫咪", "鲁")
        pick = answers.pick_answer(["完全不同的话", "另外一句话"], rou)
        self.assertEqual((pick.index, pick.known), (0, False))

    def test_costume_not_in_the_bank_takes_the_first(self):
        # Leo 2026-11-22: 題庫沒抓到的話 應該要固定選第一個. 鲁's answers, but
        # the costume on screen is not in the bank: no guessing from them.
        for choices in (["想去山洞那边。", "想去草地那边。"], ["想去山洞那邊。", "想去草地那邊。"]):
            pick = answers.pick_answer(choices, None)
            self.assertEqual((pick.index, pick.known), (0, False))
            self.assertIn("第一个", pick.why)

    def test_new_costume_found_by_either_client_name(self):
        """A costume the 繁中 client names differently, before the word table
        knows the name (贝那卡 折桂之姿 = 勝利應援, 2026-11-19)."""
        import json
        import tempfile
        from pathlib import Path

        from src.utils import game_text

        entry = {
            "id": "Venaka_3",
            "character_zh_cn": "贝那卡",
            "character_zh_tw": "貝那卡",
            "costume_zh_cn": "折桂之姿",
            "costume_zh_tw": "勝利應援",
            "questions": [
                {
                    "id": 1,
                    "prompt": {"cn": "店长喜欢赢吗？", "tw": "店長喜歡贏嗎？"},
                    "answers": [
                        {"exp": 80, "text": {"cn": "还好。", "tw": "還好。"}},
                        {"exp": 100, "text": {"cn": "当然！", "tw": "當然！"}},
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "counseling.json"
            path.write_text(json.dumps({"costumes": [entry]}, ensure_ascii=False), encoding="utf-8")
            simplified = answers.find_costume("折桂之姿", "贝那卡", path)
            traditional = answers.find_costume(
                game_text.to_tool_text("勝利應援", True), game_text.to_tool_text("貝那卡", True), path
            )
            self.assertEqual("Venaka_3", simplified.id)
            self.assertEqual("Venaka_3", traditional.id)
            for costume, choices in ((simplified, ["还好。", "当然！"]), (traditional, ["還好。", "當然！"])):
                pick = answers.pick_answer(choices, costume)
                self.assertEqual((pick.index, pick.known), (1, True))


if __name__ == "__main__":
    unittest.main()
