"""亲密度谈心 (Leo 2026-10-21): answer bank, page reading, the plan."""

from __future__ import annotations

import unittest
import unittest.mock
from difflib import SequenceMatcher
from pathlib import Path
from types import SimpleNamespace

import cv2

from src.tasks.affinity import answers, plan, record, screen

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "affinity"


def box(text, x=0, y=0, w=60, h=20):
    return SimpleNamespace(name=text, x=x, y=y, width=w, height=h)


_ENGINE = None


def real_reference_boxes(path: Path, roi):
    """OCR like the task's _reference_boxes: crop the reference ROI, read at 1080 scale."""
    global _ENGINE
    try:
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
    except ImportError as exc:  # pragma: no cover - CI without OCR
        raise unittest.SkipTest(f"onnxocr missing: {exc}")
    if _ENGINE is None:
        try:
            _ENGINE = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True)
        except ImportError:
            _ENGINE = ONNXPaddleOcr(use_angle_cls=False)
    frame = cv2.resize(cv2.imread(str(path)), (1920, 1080), interpolation=cv2.INTER_AREA)
    x, y, w, h = roi
    found = _ENGINE.ocr(frame[y : y + h, x : x + w])[0] or []
    result = []
    for points, (text, _score) in found:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        result.append(box(text, min(xs) + x, min(ys) + y, max(xs) - min(xs), max(ys) - min(ys)))
    return result


class ListPageTest(unittest.TestCase):
    def test_cards_from_synthetic_boxes(self):
        boxes = [
            box("白色猫咪", 181, 311),
            box("鲁", 188, 339),
            box("❤LV.20(0%)", 184, 357),
            box("回归偶像", 644, 528),
            box("尤里", 644, 552),
            box("LV.15(66%)", 642, 576),
        ]
        cards = screen.parse_cards(boxes)
        self.assertEqual(
            [(c.costume, c.character, c.level) for c in cards],
            [("白色猫咪", "鲁", 20), ("回归偶像", "尤里", 15)],
        )
        self.assertEqual(cards[0].key, "白色猫咪/鲁")

    def test_remaining_talks(self):
        self.assertEqual(screen.read_remaining("? 今日剩余谈心次数|3"), 3)
        self.assertEqual(screen.read_remaining("今日剩余談心次數 | 0"), 0)
        self.assertIsNone(screen.read_remaining("亲密度增益"))

    def test_real_list_page(self):
        cards = screen.parse_cards(
            real_reference_boxes(FIXTURES / "list_2k.jpg", screen.LIST_GRID_ROI)
        )
        self.assertEqual(len(cards), 22)
        by_key = {c.key: c for c in cards}
        self.assertEqual(by_key["白色猫咪/鲁"].level, 20)
        self.assertEqual(by_key["回归偶像/尤里"].level, 15)
        self.assertEqual(sum(1 for c in cards if c.level == 20), 17)
        self.assertEqual(sum(1 for c in cards if answers.find_costume(c.costume, c.character)), 22)


class DetailPageTest(unittest.TestCase):
    def _detail(self, name):
        path = FIXTURES / f"{name}.jpg"
        header = real_reference_boxes(path, screen.DETAIL_HEADER_ROI)
        button = " ".join(b.name for b in real_reference_boxes(path, screen.DETAIL_TALK_BUTTON_ROI))
        return screen.parse_detail(header, button)

    def test_lv20_full_record(self):
        detail = self._detail("detail_lv20_done_2k")
        self.assertEqual((detail.character, detail.costume), ("鲁", "白色猫咪"))
        self.assertEqual((detail.level, detail.record, detail.locked), (20, (15, 15), False))

    def test_lv20_record_not_full(self):
        detail = self._detail("detail_lv20_3of15_2k")
        self.assertEqual((detail.key, detail.level, detail.record), ("剑后/席比雅", 20, (3, 15)))

    def test_below_20_used_today(self):
        detail = self._detail("detail_lv16_used_2k")
        self.assertEqual((detail.level, detail.daily, detail.record), (16, 0, (3, 15)))

    def test_locked_lv15_with_a_talk_left(self):
        detail = self._detail("detail_lv15_locked_2k")
        self.assertEqual(
            (detail.key, detail.level, detail.daily, detail.locked),
            ("沙漠之刺/露比雅", 15, 1, True),
        )


class PanelNameTest(unittest.TestCase):
    """4K clone 2026-10-21: the gift icon read as 「f」 made 白缕轻缠木乃伊's
    panel 「f/内肯达莉亚」 and the task gave up on it 20 times."""

    def header(self):
        return [
            box("内肯达莉亚", 926, 100, 120, 26),
            box("f", 1594, 118, 12, 20),
            box("白缕轻缠木乃伊", 926, 135, 160, 24),
            box("LV.15", 930, 175, 70, 26),
            box("30/150(20%)", 1520, 178, 110, 18),
            box("谈心记录 0/15", 926, 255, 150, 24),
        ]

    def test_gift_icon_is_not_a_name(self):
        detail = screen.parse_detail(self.header(), "谈心 1/1")
        self.assertEqual(
            (detail.key, detail.level, detail.record, detail.daily),
            ("白缕轻缠木乃伊/内肯达莉亚", 15, (0, 15), 1),
        )

    def test_garbled_costume_still_matches_the_pressed_card(self):
        def detail(costume, character):
            return screen.Detail(costume, character, 15, (0, 15), 1, False)

        key = "白缕轻缠木乃伊/内肯达莉亚"
        self.assertTrue(screen.same_costume(detail("白缕轻缠木乃", "内肯达莉亚"), key))
        self.assertTrue(screen.same_costume(detail("f", "内肯达莉亚"), key))
        self.assertTrue(screen.same_costume(detail("", "内肯达莉亚"), key))
        # Another costume of the same character is another card.
        self.assertFalse(screen.same_costume(detail("剑后", "席比雅"), "沙漠之花/席比雅"))
        self.assertFalse(screen.same_costume(detail("f", "鲁"), key))


class PlanTest(unittest.TestCase):
    def cards(self):
        from src.tasks.affinity.screen import Card

        return [
            Card("白色猫咪", "鲁", 20, (0, 0)),
            Card("剑后", "席比雅", 20, (1, 0)),
            Card("回归偶像", "尤里", 16, (2, 0)),
            Card("沙漠之刺", "露比雅", 15, (3, 0)),
            Card("新衣服", "某人", 10, (4, 0)),
            Card("沙漠之花", "席比雅", 15, (5, 0)),
            Card("没持有", "某人", None, (6, 0)),
        ]

    def test_finished_costumes_never_opened_again(self):
        from src.tasks.affinity import plan, record

        rec = record.TalkRecord(done={"白色猫咪/鲁"})
        work = plan.make_plan(self.cards(), rec, "2026-10-21", 3)
        self.assertEqual([c.costume for c in work.finish], ["剑后"])

    def test_daily_order_known_answers_first_locked_last(self):
        from src.tasks.affinity import plan, record

        rec = record.TalkRecord(locked={"沙漠之刺/露比雅"})
        work = plan.make_plan(self.cards(), rec, "2026-10-21", 3)
        self.assertEqual(
            [c.costume for c in work.daily], ["回归偶像", "沙漠之花", "新衣服", "沙漠之刺"]
        )

    def test_talked_today_and_no_talks_left(self):
        from src.tasks.affinity import plan, record

        rec = record.TalkRecord(day="2026-10-21", talked={"回归偶像/尤里"})
        work = plan.make_plan(self.cards(), rec, "2026-10-21", 2)
        self.assertNotIn("回归偶像", [c.costume for c in work.daily])
        # yesterday's talks do not count today
        work = plan.make_plan(self.cards(), rec, "2026-10-22", 3)
        self.assertIn("回归偶像", [c.costume for c in work.daily])
        self.assertEqual(plan.make_plan(self.cards(), rec, "2026-10-22", 0).daily, [])

    def test_unowned_card_without_level_is_left_alone(self):
        from src.tasks.affinity import plan, record

        work = plan.make_plan(self.cards(), record.TalkRecord(), "2026-10-21", 3)
        keys = [c.costume for c in work.finish + work.daily]
        self.assertNotIn("没持有", keys)


class LockedNoteTest(unittest.TestCase):
    def test_report_says_why_locked_costumes_waited(self):
        # Leo 2026-10-22 「維持原做法 但報表說一下就好」.
        from src.tasks.AffinityTalkTask import locked_note

        note = locked_note(["沙漠之刺", "沙漠之花", "沙漠之刺"])
        self.assertTrue(note.startswith("沙漠之刺、沙漠之花还没释放潜力"))
        self.assertIn("谈心次数用完", note)


class RecordTest(unittest.TestCase):
    def test_round_trip_and_broken_file(self):
        import tempfile

        from src.tasks.affinity import record

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "affinity_talk.json"
            rec = record.TalkRecord(done={"白色猫咪/鲁"})
            rec.mark_talked("回归偶像/尤里", "2026-10-21")
            self.assertTrue(record.save(rec, path))
            back = record.load(path)
            self.assertEqual(back.done, {"白色猫咪/鲁"})
            self.assertEqual(back.talked_today("2026-10-21"), {"回归偶像/尤里"})
            self.assertEqual(back.talked_today("2026-10-22"), set())
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(record.load(path).done, set())


class KeyboardFirstTest(unittest.TestCase):
    """Leo 2026-10-21: keys first, the mouse when a key changed nothing."""

    def task(self):
        from src.tasks.AffinityTalkTask import AffinityTalkTask

        task = AffinityTalkTask.__new__(AffinityTalkTask)
        task._keys = {}
        task.sent, task.clicks, task.logs = [], [], []
        task._send_game_key = lambda code, seconds: task.sent.append(code) or True
        task._click_reference = lambda x, y, after_sleep=0.0: task.clicks.append((x, y))
        task.info_set = lambda *a, **k: None
        task.log_info = task.logs.append
        task.log_warning = task.logs.append
        task.sleep = lambda s: None
        return task

    def test_key_that_never_worked_is_dropped_after_two_misses(self):
        task = self.task()
        task._key_result("Enter", False)
        self.assertTrue(task._key_usable("Enter"))
        task._key_result("Enter", False)
        self.assertFalse(task._key_usable("Enter"))
        self.assertFalse(task._key("Enter"))
        self.assertEqual(task.sent, [])

    def test_key_that_worked_survives_a_miss_but_not_harm(self):
        task = self.task()
        task._key_result("Esc", True)
        task._key_result("Esc", False)
        task._key_result("Esc", False)
        self.assertTrue(task._key_usable("Esc"))
        task._key_result("Esc", False, drop=True)
        self.assertFalse(task._key_usable("Esc"))

    def test_back_to_list_by_esc_needs_no_click(self):
        task = self.task()
        task.capture_frame = lambda: None
        task._list_visible = lambda frame: bool(task.sent)
        self.assertTrue(task._back_to_list())
        self.assertEqual((task.sent, task.clicks), ([0x1B], []))
        self.assertEqual(task._keys["Esc"], [1, 0])

    def test_back_to_list_falls_back_to_the_arrow(self):
        from src.tasks.claim_page import BACK_BUTTON_POINT

        task = self.task()
        task.capture_frame = lambda: None
        task._list_visible = lambda frame: bool(task.clicks)
        task._wait_for_home_confirmation = lambda *a, **k: False
        task._poll = lambda check, seconds: check()
        self.assertTrue(task._back_to_list())
        self.assertEqual(task.clicks, [BACK_BUTTON_POINT])
        self.assertEqual(task._keys["Esc"], [0, 1])

    def test_confirm_dialog_by_key_when_one_is_set(self):
        from unittest import mock

        task = self.task()
        state = {"dialog": True}

        def send(code, seconds):
            task.sent.append(code)
            state["dialog"] = False
            return True

        task._send_game_key = send
        task._talk_dialog = lambda frame=None: box("确认") if state["dialog"] else None
        task._read_detail = lambda *a, **k: None
        with mock.patch("src.tasks.AffinityTalkTask.CONFIRM_KEY", "Enter"):
            self.assertTrue(task._confirm_talk(SimpleNamespace(costume="剑后")))
        self.assertEqual((task.sent, task.clicks), ([0x0D], []))

    def test_confirm_dialog_is_clicked_without_a_key(self):
        task = self.task()
        state = {"dialog": True}

        def click(x, y, after_sleep=0.0):
            task.clicks.append((x, y))
            state["dialog"] = False

        task._click_reference = click
        task._talk_dialog = lambda frame=None: (
            box("确认", 1040, 640, 60, 30) if state["dialog"] else None
        )
        task._read_detail = lambda *a, **k: None
        self.assertTrue(task._confirm_talk(SimpleNamespace(costume="剑后")))
        self.assertEqual((task.sent, task.clicks), ([], [(1070, 655)]))


class ReadingSafetyTest(unittest.TestCase):
    """Leo 2026-10-21 「主要辨識不要有問題 不要又甚麼數字沒辯到」."""

    def test_level_digits_read_as_letters(self):
        self.assertEqual(screen.read_level("❤LV.2O(0%)"), 20)
        self.assertEqual(screen.read_level("LV.l5(31%)"), 15)
        self.assertIsNone(screen.read_level("亲密度增益"))

    def task(self, reads):
        from src.tasks.AffinityTalkTask import AffinityTalkTask

        task = AffinityTalkTask.__new__(AffinityTalkTask)
        task.sleep = lambda s: None
        task.logs = []
        task.log_info = task.logs.append
        task.look_again = lambda look, label="": look()
        reads = list(reads)
        task._read_detail = lambda key=None, frame=None: reads.pop(0) if reads else None
        return task

    def detail(self, record, daily=None):
        return screen.Detail("剑后", "席比雅", 20, (record, 15), daily, False)

    def test_panel_numbers_must_agree_on_two_reads(self):
        task = self.task([self.detail(15), self.detail(15)])
        self.assertEqual(task._settled_detail("剑后/席比雅", "x").record, (15, 15))

    def test_one_misread_is_outvoted(self):
        task = self.task([self.detail(15), self.detail(5), self.detail(5)])
        self.assertEqual(task._settled_detail("剑后/席比雅", "x").record, (5, 15))

    def test_reads_that_never_agree_are_not_trusted(self):
        task = self.task([self.detail(15), self.detail(5), self.detail(6)])
        self.assertIsNone(task._settled_detail("剑后/席比雅", "x"))

    def test_none_left_today_reads_as_zero_at_once(self):
        from src.tasks.AffinityTalkTask import AffinityTalkTask

        task = AffinityTalkTask.__new__(AffinityTalkTask)
        task.capture_frame = lambda: None
        task._roi_boxes = lambda frame, roi, label: [box("今日剩余谈心次数 | 0")]
        task._boxes_text = lambda boxes: " ".join(b.name for b in boxes)
        self.assertEqual(task._remaining_read(), (0,))


class ChoiceLayoutTest(unittest.TestCase):
    def test_two_stacked_buttons_found_top_first(self):
        from src.tasks.AffinityTalkTask import stacked_choices

        found = stacked_choices(
            [
                box("想去山洞那边。", 820, 520, 280, 30),
                box("想去草地那边。", 820, 420, 280, 30),
                box("右上角的字", 1500, 210, 100, 20),
            ]
        )
        self.assertEqual([b.name for b in found], ["想去草地那边。", "想去山洞那边。"])

    def test_short_centred_answers_are_choices(self):
        from src.tasks.AffinityTalkTask import choice_line, stacked_choices

        lines = [
            box("不。", 930, 470, 40, 30),
            box("是的。", 920, 576, 60, 30),
            box("Q", 1500, 300, 20, 20),
        ]
        found = stacked_choices([b for b in lines if choice_line(b)])
        self.assertEqual([b.name for b in found], ["不。", "是的。"])

    def test_lone_glyph_from_the_art_is_not_a_choice(self):
        from src.tasks.AffinityTalkTask import choice_line

        self.assertFalse(choice_line(box("漆", 950, 300, 24, 24)))
        self.assertTrue(choice_line(box("心灵上的交流。", 880, 490, 160, 30)))

    def test_short_line_off_centre_is_not_a_choice(self):
        from src.tasks.AffinityTalkTask import choice_line

        self.assertFalse(choice_line(box("F1", 1620, 100, 30, 20)))
        self.assertTrue(choice_line(box("想去山洞那边。", 400, 520, 280, 30)))

    def test_single_line_is_not_a_choice(self):
        from src.tasks.AffinityTalkTask import stacked_choices

        self.assertEqual(stacked_choices([box("对话里的一句话", 600, 900, 500, 30)]), [])


if __name__ == "__main__":
    unittest.main()


class ShortAnswerTest(unittest.TestCase):
    """Player v0.2.31 2026-11-05: 提尔「澄心无邪兔女郎」 question 1 answers
    「山莓」/「葡萄。」; 「山莓」 (two characters, no ending) was not taken for
    a button, so the answer screen was never seen and the talk ran 120 s."""

    TYR = ("澄心无邪兔女郎", "提尔")

    def test_bank_short_answers_of_the_costume(self):
        known = answers.short_answers(answers.find_costume(*self.TYR))
        self.assertIn("山莓", known)
        self.assertIn("葡萄", known)  # the 繁中 form has no 「。」
        self.assertNotIn("我也会", known)
        self.assertEqual(answers.short_answers(None), frozenset())

    def test_short_bank_answer_centred_is_a_choice(self):
        from src.tasks.AffinityTalkTask import choice_line, stacked_choices

        known = answers.short_answers(answers.find_costume(*self.TYR))
        lines = [box("山莓", 935, 470, 50, 30), box("葡萄。", 925, 576, 70, 30)]
        self.assertFalse(choice_line(lines[0]))  # before: not a button
        found = stacked_choices([b for b in lines if choice_line(b, known)])
        self.assertEqual([b.name for b in found], ["山莓", "葡萄。"])
        pick = answers.pick_answer([b.name for b in found], answers.find_costume(*self.TYR))
        self.assertEqual((pick.index, pick.known), (0, True))

    def test_stray_glyph_still_not_a_choice(self):
        from src.tasks.AffinityTalkTask import choice_line

        known = answers.short_answers(answers.find_costume(*self.TYR))
        self.assertFalse(choice_line(box("漆", 950, 300, 24, 24), known))
        self.assertFalse(choice_line(box("山莓", 1500, 300, 50, 24), known))  # off the column

    def test_every_bank_answer_is_read_and_picked(self):
        """Every question of every costume, 简中 and 繁中: both buttons are
        taken for choices and the 100 answer is pressed.  A refreshed bank with
        an answer the reading would miss fails here, not on a player's PC."""
        import json

        from src.tasks.AffinityTalkTask import choice_line, stacked_choices

        data = json.loads(answers.BANK_FILE.read_text(encoding="utf-8"))
        misses = []
        for entry in data["costumes"]:
            costume = answers.find_costume(entry["costume_zh_cn"], entry["character_zh_cn"])
            known = answers.short_answers(costume)
            for question in entry["questions"]:
                for lang in ("cn", "tw"):
                    texts = [a["text"].get(lang, "") for a in question["answers"]]
                    exps = [a["exp"] for a in question["answers"]]
                    if not all(texts):
                        continue
                    lines = [
                        box(t, 960 - 15 * len(t), 470 + 106 * i, 30 * len(t), 30)
                        for i, t in enumerate(texts)
                    ]
                    found = stacked_choices([b for b in lines if choice_line(b, known)])
                    # The question's line is on the screen with its answers.
                    prompt = question["prompt"].get(lang, "")
                    pick = answers.pick_answer([b.name for b in found], costume, "谈心 " + prompt)
                    if len(found) != len(texts) or exps[pick.index] != max(exps):
                        misses.append(f"{entry['costume_zh_cn']} 第{question['id']}题 {lang} {texts}")
        self.assertEqual(misses, [])

    def test_swapped_answers_go_by_the_question_on_screen(self):
        # 暗黑圣女 6 「有捉弄过朋友吗」 有=100; 7 「愿望真的实现了」 没有=100.
        saint = answers.find_costume("暗黑圣女", "")
        q6 = answers.pick_answer(["有。", "没有。"], saint, "店长有捉弄过朋友吗？")
        q7 = answers.pick_answer(["没有。", "有。"], saint, "店长，你有没有过那种虔诚祈祷之后，愿望真的实现了的经历？")
        self.assertEqual((q6.index, q7.index), (0, 0))

    def talk(self, lines, keys_answer=True):
        """_talk_once on a fake answer screen showing ``lines`` until 1/2 or a
        click lands; then the panel.  A fake clock moves with every sleep."""
        from src.tasks import AffinityTalkTask as module

        task = KeyboardFirstTest().task()
        clock = {"t": 0.0}
        state = {"answered": False}

        def sleep(seconds):
            clock["t"] += max(seconds, 0.1)

        def send(code, seconds):
            task.sent.append(code)
            if keys_answer and code in (0x31, 0x32):
                state["answered"] = True
            return True

        def click(x, y, after_sleep=0.0):
            task.clicks.append((x, y))
            if 400 <= y <= 640:
                state["answered"] = True
            sleep(after_sleep)

        task.sleep = sleep
        task._send_game_key = send
        task._click_reference = click
        task._press_talk = lambda card: True
        task.capture_frame = lambda: None
        task._roi_boxes = lambda frame, roi, label: []
        task._boxes_text = lambda boxes: ""
        task._close_reward = lambda frame, boxes, text: False
        task._read_detail = lambda *a, **k: object() if state["answered"] else None
        task._region_thumbs = lambda frame, regions: "same"
        task._thumbs_changed = lambda a, b: False
        task._reference_boxes = lambda frame, roi, label: [] if state["answered"] else list(lines)
        task._save_flow_diagnostic = lambda name: None
        task.tap_escape = lambda after_sleep=0.0: task.sent.append(0x1B)
        task._note_why = task.logs.append
        card = SimpleNamespace(costume=self.TYR[0], character=self.TYR[1])
        with unittest.mock.patch.object(module, "monotonic", lambda: clock["t"]):
            done = task._talk_once(card, first_answer=False)
        return done, task, clock["t"]

    def test_tyr_question_one_is_answered(self):
        done, task, spent = self.talk([box("山莓", 935, 470, 50, 30), box("葡萄。", 925, 576, 70, 30)])
        self.assertTrue(done)
        self.assertEqual(task.sent, [0x31])  # 「山莓」 is the 100 answer: key 1
        self.assertLess(spent, 5)

    def test_lone_read_line_is_pressed_when_the_key_does_nothing(self):
        # 「山莓」 missed (no bank entry) and key 1 not taken: 「葡萄。」 is clicked.
        from src.tasks import AffinityTalkTask as module

        lines = [box("葡萄。", 925, 576, 70, 30)]
        with unittest.mock.patch.object(module.answers, "find_costume", lambda *a: None):
            done, task, spent = self.talk(lines, keys_answer=False)
        self.assertTrue(done)
        self.assertIn((960, 591), task.clicks)
        self.assertLess(spent, 60)

    def test_unread_answer_screen_gets_the_first_answer_key(self):
        # A costume souseha does not have yet, answers too short to read.
        done, task, spent = self.talk([box("冰", 950, 470, 24, 30), box("火", 950, 576, 24, 30)])
        self.assertTrue(done)
        self.assertIn(0x31, task.sent)
        self.assertLess(spent, 60)
        self.assertTrue(any("没认出选项" in str(line) for line in task.logs))


class NotOwnedTest(unittest.TestCase):
    """YES-BD2 #58: 「白雷」 on the list, not owned; pressing it opened no
    panel and the whole task was reported failed."""

    def task(self, outcomes):
        from src.tasks.affinity import record
        from src.tasks.AffinityTalkTask import AffinityTalkTask

        task = AffinityTalkTask.__new__(AffinityTalkTask)
        task.config = {}
        task.info_set = lambda *a, **k: None
        task.logs, task.whys = [], []
        task.log_info = task.logs.append
        task._open_list = lambda: True
        cards = [screen.Card(name, "某人", 16, (0, 0)) for name in outcomes]
        task._read_list = lambda: (cards, 3)
        task._daily_talk = lambda card, allow_locked: outcomes[card.costume]
        task._report_keys = lambda: None
        task._go_home = lambda: True
        task._note_why = task.whys.append
        task._claim_fail = lambda step: False
        self.patches = [
            unittest.mock.patch.object(record, "load", return_value=record.TalkRecord()),
            unittest.mock.patch.object(record, "save", return_value=True),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        return task

    def test_a_costume_with_no_panel_is_skipped_and_told(self):
        from src.tasks import run_report

        task = self.task({"白雷": "no_panel", "回归偶像": "talked"})
        with unittest.mock.patch.object(run_report, "add_current_note") as note:
            self.assertTrue(task.run_claim())
        [[text], _] = note.call_args
        self.assertIn("「白雷」没出现谈心面板（可能还没拥有这件服装）", text)
        self.assertEqual(task.whys, [])

    def test_no_panel_anywhere_still_fails(self):
        task = self.task({"白雷": "no_panel", "回归偶像": "no_panel"})
        self.assertFalse(task.run_claim())
        self.assertIn("可能还没拥有", task.whys[0])

    def test_unfinished_talk_is_tried_once_more(self):
        # Player v0.2.31 11-05: one stuck talk failed the whole 亲密度谈心.
        from src.tasks.AffinityTalkTask import TALK_UNFINISHED

        task = self.task({"澄心无邪兔女郎": None})
        tries = [TALK_UNFINISHED, "talked"]
        task._daily_talk = lambda card, allow_locked: tries.pop(0)
        self.assertTrue(task.run_claim())
        self.assertEqual((tries, task.whys), ([], []))
        self.assertTrue(any("再试一次" in line for line in task.logs))

    def test_talk_unfinished_twice_still_fails_with_why(self):
        from src.tasks.AffinityTalkTask import TALK_UNFINISHED

        task = self.task({"澄心无邪兔女郎": TALK_UNFINISHED})
        self.assertFalse(task.run_claim())
        self.assertIn("澄心无邪兔女郎：谈心没完成", task.whys[0])

    def test_open_card_back_on_the_list_is_no_panel(self):
        from src.tasks.AffinityTalkTask import NO_PANEL, AffinityTalkTask

        task = AffinityTalkTask.__new__(AffinityTalkTask)
        card = screen.Card("白雷", "尤里", 1, (100, 100))
        task._scrolled = 0
        task._grid_cards = lambda: [card]
        task.info_set = lambda *a, **k: None
        task.log_info = lambda *a: None
        task._click_reference = lambda *a, **k: None
        task._settled_detail = lambda *a: None
        task.capture_frame = lambda: None
        task._list_visible = lambda frame: True
        task._unowned_toast = lambda: False  # the game's toast unread
        task._back_to_list = lambda: True
        self.assertEqual(NO_PANEL, task._open_card(card))
        task._back_to_list = lambda: False
        self.assertIsNone(task._open_card(card))


class UnownedLabelTest(unittest.TestCase):
    """Leo 2026-10-28 「看到未擁有就不要點 純浪費時間」: a player's v0.2.15
    summary showed 暗黑圣女 pressed twice and waited on, though the list
    marks it 「未拥有」 (greyed, still 「LV.1 (0%)」)."""

    def test_real_list_with_unowned_costumes(self):
        # The game picture of that summary, scaled back to 1920x1080.
        cards = screen.parse_cards(
            real_reference_boxes(FIXTURES / "list_unowned_1080p_summary.jpg", screen.LIST_GRID_ROI)
        )
        by_key = {c.key: c for c in cards}
        self.assertFalse(by_key["暗黑圣女/黎维塔"].owned)
        self.assertFalse(by_key["白雷/尤里"].owned)
        self.assertTrue(by_key["白色猫咪/鲁"].owned)
        self.assertTrue(by_key["被封印的欲望/阿奇拉"].owned)
        owned = sorted(c.key for c in cards if c.owned)
        expected = [
            "白色猫咪/鲁", "沙漠之花/席比雅", "澄心无邪兔女郎/提尔",
            "白缕轻缠木乃伊/内肯达莉亚", "玄夜/马莫尼勒", "客栈晴晖/海伦娜",
            "恶作剧幽灵/格兰希特", "被封印的欲望/阿奇拉",
        ]
        # Which cards are owned is what is tested, not every glyph of their
        # names: the same picture reads 澄心 as 温心 on one machine (2026-10-28
        # cloud, score 0.93), and answers.find_costume takes such a misread.
        self.assertEqual(len(expected), len(owned), owned)
        for name in expected:
            alike = [key for key in owned if SequenceMatcher(None, name, key).ratio() >= 0.85]
            self.assertEqual(1, len(alike), (name, owned))
        self.assertGreaterEqual(sum(1 for c in cards if not c.owned), 14)
        work = plan.make_plan(cards, record.TalkRecord(), "2026-10-28", 3)
        self.assertEqual(sorted(c.key for c in work.daily), owned)

    def test_label_over_the_picture_marks_the_card(self):
        boxes = [
            box("白色猫咪", 181, 311), box("鲁", 188, 339), box("LV.10(0%)", 184, 357),
            box("未拥有", 1125, 260), box("暗黑圣女", 1103, 312), box("黎维塔", 1103, 334),
            box("LV.1(0%)", 1108, 360),
        ]
        cards = screen.parse_cards(boxes)
        self.assertEqual(
            [(c.costume, c.owned) for c in cards], [("白色猫咪", True), ("暗黑圣女", False)]
        )
        work = plan.make_plan(cards, record.TalkRecord(), "2026-10-28", 3)
        self.assertEqual([c.costume for c in work.daily], ["白色猫咪"])

    def test_the_games_toast_is_not_a_card_label(self):
        toast = "未拥有穿戴该服装的角色，拥有后即可进行谈心。"
        self.assertFalse(screen.unowned_label(toast))
        self.assertTrue(screen.unowned_toast(toast))
        self.assertTrue(screen.unowned_label("未擁有"))
        boxes = [box(toast, 600, 230, 500, 24), box("白色猫咪", 181, 311), box("鲁", 188, 339),
                 box("LV.10(0%)", 184, 357)]
        self.assertTrue(screen.parse_cards(boxes)[0].owned)

    def test_level_eight_read_as_b(self):
        self.assertEqual(screen.read_level("LV.B(33%)"), 8)

    def test_the_games_toast_ends_the_press_at_once(self):
        from src.tasks.AffinityTalkTask import NO_PANEL, AffinityTalkTask

        task = AffinityTalkTask.__new__(AffinityTalkTask)
        card = screen.Card("暗黑圣女", "黎维塔", 1, (1503, 283))
        task._scrolled = 0
        task._grid_cards = lambda: [card]
        task.info_set = lambda *a, **k: None
        task.logs = []
        task.log_info = task.logs.append
        presses = []
        task._click_reference = lambda *a, **k: presses.append(a)
        task.capture_frame = lambda: None
        toast = "未拥有穿戴该服装的角色，拥有后即可进行谈心。"
        task._roi_boxes = lambda frame, roi, label: [box(toast)]
        task._settled_detail = lambda *a: self.fail("waited for a panel")
        task._back_to_list = lambda: self.fail("left the list")
        self.assertEqual(NO_PANEL, task._open_card(card))
        self.assertEqual(1, len(presses))
        self.assertIn("还没拥有「暗黑圣女」", task.logs[-1])

    def test_unowned_costumes_are_told_once_and_never_pressed(self):
        from src.tasks.AffinityTalkTask import AffinityTalkTask

        task = AffinityTalkTask.__new__(AffinityTalkTask)
        task.config = {}
        task.info_set = lambda *a, **k: None
        task.logs = []
        task.log_info = task.logs.append
        task._open_list = lambda: True
        cards = [
            screen.Card("回归偶像", "尤里", 15, (0, 0)),
            screen.Card("暗黑圣女", "黎维塔", 1, (0, 0), owned=False),
        ]
        task._read_list = lambda: (cards, 3)
        pressed = []
        task._daily_talk = lambda card, allow_locked: pressed.append(card.costume) or "talked"
        task._report_keys = lambda: None
        task._go_home = lambda: True
        task._note_why = lambda *a: None
        task._claim_fail = lambda step: False
        with unittest.mock.patch.object(record, "load", return_value=record.TalkRecord()), \
                unittest.mock.patch.object(record, "save", return_value=True):
            self.assertTrue(task.run_claim())
        self.assertEqual(pressed, ["回归偶像"])
        self.assertIn("列表上标着「未拥有」的服装不点：暗黑圣女。", " ".join(task.logs))
