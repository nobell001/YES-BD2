"""The 魔兽追踪者 planning-screen readers on saved frames at 1080p, 2K and 4K.

Fixtures (tests/fixtures/fiend_hunt/README.md) are 4K captures from the 4K
PC scaled to 1920x1080 with only the read regions kept; 2K and 4K are the
same frames scaled back up.
"""

import unittest
from pathlib import Path

import cv2
import numpy as np

from src.tasks.fiend_hunt import layout, vision
from src.tasks.fiend_hunt.names import snap_name
from src.tasks.fiend_hunt.record import FightRecord, TurnState
from src.tasks.fiend_hunt.screen import bursts_from_screenshots
from tests.helpers.recognition_fixtures import load_fhd_bgr

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fiend_hunt"
SIZES = ((1920, 1080), (2560, 1440), (3840, 2160))
TEAM1 = ("克蕾西亚", "马莫尼勒", "艾尼尔", "杰尼斯", "班塔纳")
TEAM2 = ("帕莱特", "黛安娜", "鲁", "海伦娜", "格兰希特", "魔法增幅器")

try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships onnxocr
    ONNXPaddleOcr = None

_ENGINE = None


def ocr(image):
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True)
    return [line[1][0] for line in (_ENGINE.ocr(image)[0] or [])]


def frames(name):
    base = load_fhd_bgr(FIXTURES / name)
    for size in SIZES:
        frame = base if size == SIZES[0] else cv2.resize(base, size, interpolation=cv2.INTER_CUBIC)
        yield size, frame


class PixelReadersTest(unittest.TestCase):
    def check(self, name, *, planning, topdown, slots, out=(), selected=(), end=False):
        for size, frame in frames(name):
            with self.subTest(fixture=name, size=size):
                self.assertEqual(planning, vision.planning_visible(frame))
                self.assertEqual(end, vision.battle_end_visible(frame))
                self.assertEqual(topdown, vision.is_topdown(frame))
                self.assertEqual(slots, vision.slot_count(frame))
                self.assertEqual(list(out), vision.out_slots(frame, max(slots, 0)))
                self.assertEqual(list(selected), vision.selected_slots(frame, max(slots, 0)))

    def test_planning_top_down(self):
        self.check("planning_topdown_t1.png", planning=True, topdown=True, slots=5)

    def test_held_cell_selects_its_unit(self):
        self.check("held_cell_slot4.png", planning=True, topdown=True, slots=5, selected=[3])

    def test_team2_lists_six_slots_with_the_summon(self):
        self.check("team2_planning_t13.png", planning=True, topdown=False, slots=6)
        self.check("team2_summon_selected.png", planning=True, topdown=False, slots=6, selected=[5])

    def test_selection_found_on_a_list_sitting_lower(self):
        # 2K PC 2026-10-07: every hold read as empty, 「找不到第 [2] 位」.
        self.check(
            "list_2k_two_units_lower.png", planning=True, topdown=True, slots=2, selected=[1]
        )

    def test_dead_units_are_out_at_the_bottom(self):
        self.check("out_slots_t11.png", planning=True, topdown=False, slots=5, out=[2, 3, 4])

    def test_battle_end(self):
        self.check("battle_end.png", planning=False, topdown=False, slots=0, end=True)

    def test_talos_victory_is_an_end_but_not_battle_end(self):
        for name in ("talos_victory_2k.png", "talos_victory_sparkle_2k.png"):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertTrue(vision.victory_visible(frame))
                    self.assertFalse(vision.battle_end_visible(frame))
                    self.assertFalse(vision.planning_visible(frame))

    def test_talos_defeat_is_a_lost_fight(self):
        # 2K PC 2026-10-28 stage 7: 「DEFEAT」 on a red band mid-screen; the
        # tool took it for a frozen battle.
        for size, frame in frames("talos_defeat_2k.png"):
            with self.subTest(size=size):
                self.assertTrue(vision.defeat_band(frame))
                self.assertIn("DEFEAT", vision.lost_word(frame, ocr))
                self.assertFalse(vision.victory_visible(frame))
                self.assertFalse(vision.planning_visible(frame))

    def test_no_defeat_band_on_wins_and_fights(self):
        for name in (
            "talos_victory_2k.png",
            "talos_victory_sparkle_2k.png",
            "talos_angled_s4_2k.png",
            "talos_planning_2k.png",
            "battle_end.png",
        ):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertFalse(vision.defeat_band(frame))
                    self.assertIsNone(vision.lost_word(frame, ocr))

    def test_talos_zoom_percent(self):
        for name, percent in (
            ("talos_zoom_78_2k.png", 78),
            ("talos_zoom_97_2k.png", 97),
            ("talos_zoom_114_2k.png", 114),
            ("talos_zoom_none_2k.png", None),
        ):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertEqual(percent, vision.zoom_percent(frame, ocr))

    def test_talos_view_told_by_its_floor(self):
        # 2K PC 2026-10-28: stage 3's angled view on light stone, which the
        # floor check alone took for the top-down grey; stage 5's angled view
        # with 切换画面 greyed out (no sign of the view).
        for name, topdown in (
            ("talos_angled_s3_light_floor_2k.png", False),
            ("talos_angled_s4_2k.png", False),
            ("talos_angled_s5_grey_switch_2k.png", False),
            ("talos_topdown_s3_2k.png", True),
            ("talos_topdown_s5_2k.png", True),
            # stage 8's dark floor (2K PC 2026-10-28, run without help)
            ("talos_angled_s8_dark_2k.png", False),
            ("talos_topdown_s8_dark_2k.png", True),
        ):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertTrue(vision.talos_layout(frame))
                    self.assertEqual(topdown, vision.is_topdown(frame))
        for name in ("real_cave_isometric_t1.png", "real_cave_topdown_t1.png"):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertFalse(vision.talos_layout(frame))  # a 魔兽 fight

    def test_no_victory_on_other_screens(self):
        for name in (
            "battle_end.png",
            "battle_end_hp_run1.png",
            "planning_topdown_t1.png",
            "talos_planning_2k.png",
            "real_cave_isometric_t1.png",
            "team2_planning_t13.png",
        ):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertFalse(vision.victory_visible(frame))

    def test_dialog_over_the_planning_screen_hides_the_list(self):
        # the BATTLE pill still matches under the dim dialog; the list doesn't
        for size, frame in frames("change_team_dialog.png"):
            with self.subTest(size=size):
                self.assertEqual(0, vision.slot_count(frame))

    def test_busy_cells_come_first(self):
        frame = load_fhd_bgr(FIXTURES / "planning_topdown_t1.png")
        # TURN 1: four units on the bottom row, one front of the middle row
        occupied = {(2, 0), (2, 1), (2, 2), (2, 3), (1, 3)}
        self.assertEqual(occupied, set(vision.cells_by_busy(frame)[:5]))


class TalosBusyCellsTest(unittest.TestCase):
    """塔洛斯's grid is bigger: which cells hold someone is read on the grid as
    drawn, not layout's (the five units of the planning frame)."""

    def test_units_found_on_the_drawn_grid(self):
        frame = load_fhd_bgr(FIXTURES / "talos_planning_2k.png")
        grid = vision.grid_on_screen(frame)
        self.assertIsNotNone(grid)
        units = {(0, 2), (0, 3), (1, 2), (1, 3), (2, 3)}
        self.assertEqual(units, set(vision.cells_by_busy(frame, grid)[:5]))
        self.assertLess(
            max(vision.cell_busy_score(frame, cell, grid) for cell in vision_cells() - units),
            min(vision.cell_busy_score(frame, cell, grid) for cell in units),
        )


def vision_cells():
    return {(row, col) for row in range(vision.ROWS) for col in range(vision.COLS)}


class KnockbackTest(unittest.TestCase):
    # 塔洛斯战术教材 (Leo 2026-10-22): 击退 shows a white arrow where the skill
    # icon sits, pointing each character's own way.  A 2K capture (all five on
    # 击退) and turns of a 720p guide video; only the list is kept.
    CASES = {
        "talos_list_knockback_2k.png": ["击退"] * 5,
        "talos_list_video_00.png": ["技能", "技能", "技能", "攻击", "技能"],
        "talos_list_video_01.png": ["击退", "击退", "攻击", "击退", "攻击"],
        "talos_list_video_28.png": ["技能", "击退", "击退", "击退"],
    }

    def test_each_entry_reads_as_attack_knockback_or_skill(self):
        for name, wanted in self.CASES.items():
            frame = cv2.imread(str(FIXTURES / name))
            with self.subTest(name=name):
                seen = [vision.list_action(frame, slot) for slot in range(len(wanted))]
                self.assertEqual(wanted, seen)
                skills = [vision.has_skill_icon(frame, slot) for slot in range(len(wanted))]
                self.assertEqual([action == "技能" for action in wanted], skills)

    def test_same_card_tells_knockback_from_attack(self):
        video_01 = cv2.imread(str(FIXTURES / "talos_list_video_01.png"))
        self.assertFalse(vision.same_card(video_01, 0, video_01, 2))  # 击退 vs 攻击
        self.assertTrue(vision.same_card(video_01, 0, video_01, 1))  # 击退 vs 击退


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class CardColumnTest(unittest.TestCase):
    """The selected unit's card column: how many cards and which one is lit."""

    def check(self, name, *, selected, cards, lit, label):
        for size, frame in frames(name):
            with self.subTest(fixture=name, size=size):
                self.assertEqual(
                    [selected] if selected is not None else [], vision.selected_slots(frame)
                )
                self.assertEqual(cards, vision.card_count(frame))
                self.assertEqual(lit, vision.lit_card(frame))
                if lit is not None:
                    self.assertEqual(label, vision.card_label(lit))

    def test_no_column_on_the_4k_floor(self):
        # 4K PC 2026-10-08, 水魔兽 T3 with nobody held: at native 4K the
        # strip beside the ⇅ buttons scored 7/6 and passed for 2 cards (only
        # the card area kept; cards at least 14, empty floor at most 7)
        frame = cv2.imread(str(FIXTURES / "cards_4k_none_water_t3.png"))
        self.assertEqual((2160, 3840), frame.shape[:2])
        self.assertEqual(0, vision.card_count(frame))

    def test_attack_lit(self):
        # TURN 1 top-down: 克蕾西亚 on 最前方 (the normal attack), three skill cards
        self.check("cards_t1_attack_lit.png", selected=0, cards=5, lit=0, label="攻击")

    def test_skill_lit(self):
        # 马莫尼勒 on her second skill card (lit pale blue)
        self.check("cards_t1_skill_lit.png", selected=1, cards=4, lit=3, label="技能2")

    def test_knockback_lit(self):
        self.check("cards_t1_knockback_lit.png", selected=4, cards=5, lit=1, label="击退")

    def test_four_skill_cards(self):
        # TURN 13 isometric: 鲁 has four costumes, a card on every list row
        self.check("cards_t13_four_skills.png", selected=2, cards=6, lit=0, label="攻击")

    def test_summon_on_its_skill(self):
        self.check("cards_t13_summon.png", selected=5, cards=3, lit=2, label="技能1")

    def test_greyed_preempt_cards_still_count_and_stay_dim(self):
        # 格兰希特 with both 先发制人 switches on: skill cards 1-2 greyed with a clock
        self.check("cards_t13_preempt_on.png", selected=4, cards=6, lit=0, label="攻击")

    def test_bright_skill_art_is_not_taken_for_the_lit_card(self):
        # TURN 21 top-down: 帕莱特 on 越过 (attack); her purple skill art is
        # nearly as saturated, and her 2nd skill card is greyed (cooldown 1)
        self.check("cards_t21_bright_skill_art.png", selected=0, cards=4, lit=0, label="攻击")

    def test_preempt_switch_beside_the_skill_card(self):
        # 塔洛斯 stage 7 (2K PC 2026-10-28): 格兰希特's 「先发制人」, off then on
        for name, on in (("talos_preempt_off_2k.png", False), ("talos_preempt_on_2k.png", True)):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertEqual([1], vision.selected_slots(frame))
                    self.assertEqual(3, vision.card_count(frame))
                    self.assertFalse(vision.preempt_beside(frame, ocr, 1))
                    self.assertTrue(vision.preempt_beside(frame, ocr, 2))
                    self.assertEqual(on, vision.preempt_on(frame, 2))

    def test_no_column_while_nobody_is_selected(self):
        self.check("cards_t13_none.png", selected=None, cards=0, lit=None, label=None)

    def test_labels_and_rows(self):
        for row, label in enumerate(("攻击", "击退", "技能1", "技能2", "技能3", "技能4")):
            self.assertEqual(label, vision.card_label(row))
            self.assertEqual(row, vision.card_row(label))
        for label in ("技能", "技能0", "技能1·B3", "最前方"):
            self.assertIsNone(vision.card_row(label))


def frame_pairs(first, second):
    """Both fixtures at each size (a replay compares frames from the same PC)."""
    for (size, one), (_, other) in zip(frames(first), frames(second)):
        yield size, one, other


class ListCardTest(unittest.TestCase):
    """The card a list entry shows: a skill's costume and round icon, or an attack (no icon)."""

    ICONS = {
        "list_t1_start.png": [False, True, False, False, False],
        "list_t1_slot2_skill1.png": [False, True, False, False, False],
        "list_t1_slot2_skill1_arc.png": [False, True, False, False, False],
        "list_t1_slot1_skill2.png": [True, True, False, False, False],
        "list_t13_start.png": [True, True, False, True, False, True],
        "list_t13_summon_attack.png": [True, True, False, True, False, False],
        "list_t11_saved_arc.png": [True, False, True, True, True],
    }

    def test_round_skill_icon_or_none(self):
        for name, icons in self.ICONS.items():
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertEqual(len(icons), vision.slot_count(frame))
                    seen = [vision.has_skill_icon(frame, slot) for slot in range(len(icons))]
                    self.assertEqual(icons, seen)

    def check(self, live, saved, same):
        for size, one, other in frame_pairs(live, saved):
            with self.subTest(live=live, saved=saved, size=size):
                seen = [vision.same_card(one, slot, other, slot) for slot in range(len(same))]
                self.assertEqual(same, seen)

    def test_another_skill_is_another_costume(self):
        # T1: 马莫尼勒 (slot 2) on her 1st skill, saved on her 2nd
        self.check("list_t1_slot2_skill1.png", "list_t1_start.png", [True, False, True, True, True])

    def test_skill_instead_of_attack(self):
        # T1: 克蕾西亚 (slot 1) on her 2nd skill, saved on attack; and back
        self.check("list_t1_slot1_skill2.png", "list_t1_start.png", [False, True, True, True, True])
        self.check("list_t1_start.png", "list_t1_slot1_skill2.png", [False, True, True, True, True])

    def test_summon_attack_vs_its_skill(self):
        # T13: 魔法增幅器ET001 (slot 6) on attack, saved on its one skill
        self.check(
            "list_t13_summon_attack.png",
            "list_t13_start.png",
            [True, True, True, True, True, False],
        )

    def test_arc_after_a_pick_in_the_saved_frame(self):
        # the glow that sweeps an entry for ~0.1 s after a pick or a ⇅ tap
        self.check("list_t1_slot2_skill1.png", "list_t1_slot2_skill1_arc.png", [True] * 5)
        # T11 of self_1001b (arc over 班塔纳) against the same turn replayed
        self.check("list_t11_live.png", "list_t11_saved_arc.png", [True] * 5)

    def test_list_steady(self):
        for size, one, other in frame_pairs("list_t1_slot2_skill1.png", "list_t1_start.png"):
            with self.subTest(size=size):
                self.assertTrue(vision.list_steady(one, one.copy(), 5))
                self.assertFalse(vision.list_steady(one, other, 5))


class BurstFlameTest(unittest.TestCase):
    def test_flame_on_each_list_entry_gives_the_level(self):
        # self_2k_b (2K PC, 2026-10-01): the levels the chart and Leo give.
        cases = {
            "list_2k_t01_bursts.png": [0, 3, 0, 0, 0],  # 马莫尼勒 L3
            "list_2k_t07_bursts.png": [2, 0, 0, 0, 0],  # 克蕾西亚 L2
            "list_2k_t23_bursts.png": [1, 3, 0, 0, 0, 0],  # 帕莱特 L1, 海伦娜 L3
        }
        for name, levels in cases.items():
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    read = [vision.burst_flame(frame, slot) for slot in range(len(levels))]
                    self.assertEqual(levels, read)

    def test_a_save_without_levels_gets_them_from_its_screenshots(self):
        cells = {unit: (2, col) for col, unit in enumerate(TEAM1[:4])} | {TEAM1[4]: (1, 3)}
        turns = {n: TurnState(n, 1, TEAM1, cells) for n in (1, 7)}
        turns[3] = TurnState(3, 1, TEAM1, cells, bursts={"马莫尼勒": 2})  # kept as saved
        shots = {1: "list_2k_t01_bursts.png", 3: "x.png", 7: "list_2k_t07_bursts.png"}
        record = FightRecord(turns, "测试", screenshots=shots)

        filled = bursts_from_screenshots(
            record, FIXTURES, load=lambda path: load_fhd_bgr(FIXTURES / path.name)
        )

        self.assertEqual({"马莫尼勒": 3}, filled.turns[1].bursts)
        self.assertEqual({"马莫尼勒": 2}, filled.turns[3].bursts)
        self.assertEqual(
            {"克蕾西亚": 2, "马莫尼勒": 0}, filled.turns[7].bursts
        )  # 0: skill, no burst


class CardIconTest(unittest.TestCase):
    def test_the_card_with_the_saved_skill_icon(self):
        # T19, 帕莱特 selected: 技能1 (恐惧之梦, on cooldown) and 技能2 (奇迹紫罗兰).
        saved_t17 = load_fhd_bgr(FIXTURES / "list_2k_t17.png")  # 帕莱特 on 恐惧之梦
        saved_t23 = load_fhd_bgr(FIXTURES / "list_2k_t23_bursts.png")  # on 奇迹紫罗兰
        for size, frame in frames("cards_2k_t19_palette.png"):
            with self.subTest(size=size):
                cards = vision.card_count(frame)
                self.assertEqual(4, cards)
                self.assertEqual(2, vision.card_with_icon(frame, cards, saved_t17, 0))
                self.assertEqual(3, vision.card_with_icon(frame, cards, saved_t23, 0))


@unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
class BossHpTest(unittest.TestCase):
    """HP left under BATTLE END, read exactly (2K PC 2026-10-01, practice fight)."""

    def test_hp_left_and_full(self):
        for name, left in (
            ("battle_end_hp_run1.png", 39_446_800_693),
            ("battle_end_hp_run2.png", 49_399_316_779),
            ("battle_end_hp_real_cave.png", 39_447_115_732),  # over the red HP bar
        ):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertEqual((left, 64_500_000_000), vision.read_boss_hp(frame, ocr))

    def test_a_number_missing_a_digit_is_not_read(self):
        for text in ("49,39,316,779/64,500,000,000", "49399316779/64500000000", "64,500,000,000"):
            with self.subTest(text=text):
                frame = load_fhd_bgr(FIXTURES / "battle_end_hp_run2.png")
                self.assertIsNone(vision.read_boss_hp(frame, lambda image, text=text: [text]))


class RealFightTest(unittest.TestCase):
    """A real fight's backdrop (cave, 2K PC 2026-10-01), not the practice room."""

    def test_view_is_told_over_the_cave(self):
        for name, topdown in (
            ("real_cave_isometric_t1.png", False),
            ("real_cave_topdown_t1.png", True),
        ):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertTrue(vision.planning_visible(frame))
                    self.assertEqual(topdown, vision.is_topdown(frame))

    def test_diamond_read_over_the_cave(self):
        for name, on in (("real_cave_isometric_t1.png", True), ("real_cave_topdown_t1.png", False)):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertEqual(on, vision.auto_skill_on(frame))


class ViewOffsetTest(unittest.TestCase):
    """The top-down camera's place, in both rooms and with TEAM2."""

    def test_camera_in_place(self):
        for name in ("real_cave_topdown_t1.png", "planning_topdown_t1.png"):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    dx, dy = vision.view_offset(frame)
                    self.assertLess(max(abs(dx), abs(dy)), layout.VIEW_SHIFT_MAX)

    def test_dragged_camera_is_measured(self):
        frame = load_fhd_bgr(FIXTURES / "planning_topdown_t1.png")
        moved = cv2.warpAffine(
            frame,
            np.float32([[1, 0, -22], [0, 1, -75]]),
            (1920, 1080),
            borderMode=cv2.BORDER_REPLICATE,
        )
        dx, dy = vision.view_offset(moved)
        self.assertAlmostEqual(-22, dx, delta=2)
        self.assertAlmostEqual(-75, dy, delta=2)


class GridOnScreenTest(unittest.TestCase):
    """Where the cells are drawn, from their corner brackets."""

    TOPDOWN = (
        "real_cave_topdown_t1.png",
        "planning_topdown_t1.png",
        "held_cell_slot4.png",
        "list_2k_two_units_lower.png",
        "shots_2k_a_t07.png",
        "shots_2k_a_t15.png",
        "shots_2k_b_t07.png",
        "shots_2k_b_t15.png",
    )

    def test_cells_where_layout_has_them(self):
        for name in self.TOPDOWN:
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    drawn = vision.grid_on_screen(frame)
                    self.assertIsNotNone(drawn)
                    self.assertFalse(drawn.off(vision.LAYOUT_GRID), drawn)

    def test_zoomed_out_grid(self):
        # 4K PC 2026-10-08, 水魔兽 T3: the cells 0.9 the size, 48 px right
        for size, frame in frames("planning_4k_water_t3_zoomed.png"):
            with self.subTest(size=size):
                drawn = vision.grid_on_screen(frame)
                self.assertAlmostEqual(0.90, drawn.scale, delta=0.015)
                self.assertAlmostEqual(529, drawn.left, delta=2)
                self.assertAlmostEqual(442, drawn.top, delta=2)
                # the top-left cell's press lands inside its bracket (529-590, 442-498)
                x, y = drawn.point(layout.cell_press((0, 0)))
                self.assertTrue(535 < x < 585 and 450 < y < 495, (x, y))

    def test_talos_big_grid(self):
        # 2K PC 2026-10-22, 塔洛斯战术教材 stage 1: the cells 1.31 the size,
        # higher and left of layout's; the fixed cells pressed the floor
        for size, frame in frames("talos_planning_2k.png"):
            with self.subTest(size=size):
                drawn = vision.grid_on_screen(frame)
                self.assertAlmostEqual(1.31, drawn.scale, delta=0.015)
                self.assertAlmostEqual(395, drawn.left, delta=3)
                self.assertAlmostEqual(264, drawn.top, delta=3)
                # row 1 col 4 (the red-hat unit) lands inside its bracket (690-780, 262-352)
                x, y = drawn.point(layout.cell_press((0, 3)))
                self.assertTrue(695 < x < 775 and 270 < y < 350, (x, y))

    def test_talos_grid_at_each_zoom(self):
        # 2K PC zoom probe 2026-10-28, scale ~1.32 x N/100.  At 88-92% the
        # usual room's search had read 1.10-1.12 (92%: 1.11, the player's
        # 「格子大小还是 1.11」 2026-10-31), so the wheel never got it back.
        for name, scale in (
            ("talos_grid_zoom_88_2k.png", 1.16),
            ("talos_grid_zoom_91_2k.png", 1.20),
            ("talos_grid_zoom_92_2k.png", 1.22),
            ("talos_grid_zoom_101_2k.png", 1.33),
            ("talos_grid_zoom_114_2k.png", 1.49),
        ):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    drawn = vision.grid_on_screen(frame)
                    self.assertIsNotNone(drawn)
                    self.assertAlmostEqual(scale, drawn.scale, delta=0.025)

    def test_no_grid_off_the_top_down_view(self):
        for name in ("real_cave_isometric_t1.png", "battle_end.png"):
            with self.subTest(fixture=name):
                self.assertIsNone(vision.grid_on_screen(load_fhd_bgr(FIXTURES / name)))


class ViewToggleTest(unittest.TestCase):
    def test_found_where_each_fight_puts_it(self):
        # 魔兽: where layout has it; 塔洛斯 (2K PC 2026-10-22): 100 px left,
        # with the greyed-out 切换画面 where 魔兽 has 切换视角
        for name, (x, y) in (
            ("real_cave_isometric_t1.png", layout.VIEW_TOGGLE),
            ("real_cave_topdown_t1.png", layout.VIEW_TOGGLE),
            ("talos_view_buttons_2k.png", (1420.0, 974.0)),
        ):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    found = vision.view_toggle_point(frame)
                    self.assertIsNotNone(found)
                    self.assertAlmostEqual(x, found[0], delta=6)
                    self.assertAlmostEqual(y, found[1], delta=8)

    def test_none_without_the_button(self):
        for name in ("battle_end.png", "planning_topdown_t1.png", "talos_planning_2k.png"):
            with self.subTest(fixture=name):
                self.assertIsNone(vision.view_toggle_point(load_fhd_bgr(FIXTURES / name)))


class AutoSkillTest(unittest.TestCase):
    def test_diamond_icon_on_and_off(self):
        for name, on in (("auto_skill_on.png", True), ("auto_skill_off.png", False)):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertEqual(on, vision.auto_skill_on(frame))

    def test_a_capture_with_an_alpha_channel_is_read_too(self):
        for name, on in (("auto_skill_on.png", True), ("auto_skill_off.png", False)):
            frame = cv2.cvtColor(load_fhd_bgr(FIXTURES / name), cv2.COLOR_BGR2BGRA)
            with self.subTest(fixture=name):
                self.assertEqual(on, vision.auto_skill_on(frame))

    def test_the_spin_is_seen_only_while_on(self):
        for state, on in (("on", True), ("off", False)):
            pairs = zip(
                frames(f"auto_skill_spin_{state}_a.png"), frames(f"auto_skill_spin_{state}_b.png")
            )
            for (size, first), (_, second) in pairs:
                with self.subTest(state=state, size=size):
                    self.assertEqual(on, vision.auto_skill_on(second))
                    self.assertEqual(on, vision.auto_skill_turning(first, second))
                    alpha = [cv2.cvtColor(f, cv2.COLOR_BGR2BGRA) for f in (first, second)]
                    self.assertEqual(on, vision.auto_skill_turning(*alpha))

    def test_talos_4k_on_then_off_after_one_tap(self):
        # 4K PC 2026-10-28, 塔洛斯 stage 7 T1 (auto skill on, 8 SP queued);
        # the tap at (1497.5, 50) turned it off within 0.7 s
        for state, on in (("on", True), ("off", False)):
            pairs = frame_pairs(f"talos_autoskill_{state}_a.png", f"talos_autoskill_{state}_b.png")
            for size, first, second in pairs:
                with self.subTest(state=state, size=size):
                    self.assertTrue(vision.icons_lit(second))
                    self.assertEqual(on, vision.auto_skill_on(second))
                    self.assertEqual(on, vision.auto_skill_turning(first, second))

    def test_icons_still_fading_in_are_not_read(self):
        # the planning screen's BATTLE shows before the scenery and icons do
        for size, frame in frames("talos_fading_in.png"):
            with self.subTest(size=size):
                self.assertTrue(vision.planning_visible(frame))
                self.assertFalse(vision.icons_lit(frame))
        for name in ("auto_skill_on.png", "auto_skill_off.png", "real_cave_isometric_t1.png"):
            with self.subTest(fixture=name):
                self.assertTrue(vision.icons_lit(load_fhd_bgr(FIXTURES / name)))

    def test_moving_scenery_behind_a_still_icon_is_not_a_spin(self):
        # Flickering backdrop (effects, water): every dark pixel changes between
        # the two captures, the white icon doesn't.
        rng = np.random.default_rng(1)
        first = load_fhd_bgr(FIXTURES / "auto_skill_spin_off_a.png")
        second = load_fhd_bgr(FIXTURES / "auto_skill_spin_off_b.png")
        for frame in (first, second):
            box = frame[18:82, 1466:1529]
            dark = box.max(axis=2) < 140
            box[dark] = rng.integers(0, 120, size=(int(dark.sum()), 3), dtype=np.uint8)
        self.assertFalse(vision.auto_skill_turning(first, second))

    def test_blue_scenery_behind_the_icon_is_not_read_as_on(self):
        # A real fight's backdrop (sky, water) can be blue where the practice
        # room is grey: paint every dark pixel of the box blue, icon kept.
        for name, on in (("auto_skill_on.png", True), ("auto_skill_off.png", False)):
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    painted = frame.copy()
                    scale = frame.shape[1] / 1920
                    x0, y0, x1, y1 = (round(v * scale) for v in layout.AUTO_SKILL_BOX)
                    box = painted[y0:y1, x0:x1]
                    dark = box.max(axis=2) < 140
                    box[dark] = (210, 150, 60)  # BGR: a saturated sky blue
                    self.assertEqual(on, vision.auto_skill_on(painted))


class TextReadersTest(unittest.TestCase):
    def test_turn_and_team(self):
        cases = {
            "planning_topdown_t1.png": (1, 1),
            "team2_planning_t13.png": (13, 2),
            "out_slots_t11.png": (11, 1),
        }
        for name, (turn, team) in cases.items():
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertEqual(turn, vision.read_turn(frame, ocr))
                    self.assertEqual(team, vision.read_team(frame, ocr))

    def test_a_third_team_is_read(self):
        # Leo 2026-10-01: some fights have TEAM3.
        _, frame = next(iter(frames("planning_topdown_t1.png")))
        self.assertEqual(3, vision.read_team(frame, lambda image: ["TEAM3"]))
        self.assertIsNone(vision.read_team(frame, lambda image: ["TEAM4"]))

    def test_selected_names_snap_to_the_team(self):
        cases = {
            "held_cell_slot4.png": ("杰尼斯", TEAM1),
            "team2_summon_selected.png": ("魔法增幅器", TEAM2),
        }
        for name, (unit, known) in cases.items():
            for size, frame in frames(name):
                with self.subTest(fixture=name, size=size):
                    self.assertEqual(unit, snap_name(vision.read_name(frame, ocr), known))
                    self.assertIsNone(vision.read_team(frame, ocr))  # name replaces TEAM

    def test_burst_level_in_the_header(self):
        for size, frame in frames("burst_header_t11_l2.png"):
            with self.subTest(size=size):
                self.assertEqual(2, vision.read_burst(frame, ocr))
        for size, frame in frames("planning_topdown_t1.png"):  # nobody selected
            with self.subTest(size=size):
                self.assertIsNone(vision.read_burst(frame, ocr))

    def test_change_team_dialog_title(self):
        for size, frame in frames("change_team_dialog.png"):
            with self.subTest(size=size):
                self.assertIn("更换队伍", vision.read_dialog_title(frame, ocr))


class LayoutTest(unittest.TestCase):
    def test_points_scale_with_the_client(self):
        # 1772.5 rounds half to even
        self.assertEqual((1772, 985), layout.to_client(layout.BATTLE, 1920, 1080))
        self.assertEqual((3545, 1970), layout.to_client(layout.BATTLE, 3840, 2160))
        self.assertEqual((2363, 1313), layout.to_client(layout.BATTLE, 2560, 1440))

    def test_cells_run_left_to_right_top_to_bottom(self):
        xs = [layout.cell_press((0, col))[0] for col in range(4)]
        ys = [layout.cell_press((row, 0))[1] for row in range(3)]
        self.assertEqual(sorted(xs), xs)
        self.assertEqual(sorted(ys), ys)
        left, top, right, bottom = layout.cell_box((2, 3))
        x, y = layout.cell_press((2, 3))
        self.assertTrue(left < x < right and top < y < bottom)


if __name__ == "__main__":
    unittest.main()
